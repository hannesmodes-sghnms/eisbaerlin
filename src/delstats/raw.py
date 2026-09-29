from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DelSourceConfig
from .http import DelHttpClient, DelHttpError


@dataclass
class DownloadedResource:
    key: str
    url: str
    local_path: str
    status: str
    size_bytes: int
    sha256: str
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class RawDownloadManifest:
    match_id: int
    created_at_utc: str
    source_manifest: str | None
    resources: list[DownloadedResource]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_resource_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Resource manifest must contain a JSON object: {path}")
    if "match_id" not in payload or "all_keys" not in payload:
        raise ValueError(
            f"Resource manifest is missing match_id/all_keys fields: {path}"
        )
    return payload


def resource_keys_from_manifest(
    payload: dict[str, Any],
    *,
    include_shots: bool = True,
) -> list[str]:
    keys = [str(key) for key in payload.get("all_keys", []) if key]
    shot_key = payload.get("shot_key")
    shot_exists = payload.get("shot_exists")
    if include_shots and shot_key and shot_exists is not False:
        keys.append(str(shot_key))
    return sorted(dict.fromkeys(keys))


def local_relative_path(match_id: int, key: str) -> Path:
    match_prefix = f"matches/{match_id}/"
    if key.startswith(match_prefix):
        relative = key[len(match_prefix):]
        return Path(relative)
    if key == f"visualization/shots/{match_id}.json":
        return Path("shots.json")

    # Fallback for an unexpected resource discovered outside the match prefix.
    # Preserve hierarchy while avoiding accidental absolute paths.
    safe_parts = [part for part in key.split("/") if part not in {"", ".", ".."}]
    return Path("external", *safe_parts)


def _validate_json(data: bytes, url: str) -> None:
    try:
        json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DelHttpError(f"Downloaded resource is not valid JSON: {url}") from exc


class RawMatchDownloader:
    def __init__(
        self,
        *,
        http: DelHttpClient | None = None,
        config: DelSourceConfig | None = None,
    ) -> None:
        self.http = http or DelHttpClient()
        self.config = config or DelSourceConfig()

    def download_from_manifest(
        self,
        manifest_path: Path,
        *,
        output_dir: Path = Path("data/raw"),
        include_shots: bool = True,
        force: bool = False,
    ) -> tuple[Path, RawDownloadManifest]:
        payload = load_resource_manifest(manifest_path)
        match_id = int(payload["match_id"])
        keys = resource_keys_from_manifest(payload, include_shots=include_shots)
        if not keys:
            raise ValueError(f"No resource keys found in {manifest_path}")

        match_dir = output_dir / str(match_id)
        match_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[DownloadedResource] = []

        for key in keys:
            relative = local_relative_path(match_id, key)
            target = match_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            url = self.config.object_url(key)

            if target.exists() and not force:
                data = target.read_bytes()
                _validate_json(data, url)
                downloaded.append(
                    DownloadedResource(
                        key=key,
                        url=url,
                        local_path=str(relative).replace(os.sep, "/"),
                        status="existing",
                        size_bytes=len(data),
                        sha256=sha256_bytes(data),
                    )
                )
                continue

            response = self.http.get(url)
            if response.status_code != 200:
                raise DelHttpError(f"HTTP {response.status_code} for {url}")
            data = response.content
            _validate_json(data, url)

            temp_path = target.with_suffix(target.suffix + ".tmp")
            temp_path.write_bytes(data)
            temp_path.replace(target)

            downloaded.append(
                DownloadedResource(
                    key=key,
                    url=url,
                    local_path=str(relative).replace(os.sep, "/"),
                    status="downloaded",
                    size_bytes=len(data),
                    sha256=sha256_bytes(data),
                    etag=(response.headers.get("ETag") or "").strip('"') or None,
                    last_modified=response.headers.get("Last-Modified"),
                )
            )

        result = RawDownloadManifest(
            match_id=match_id,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            source_manifest=str(manifest_path),
            resources=downloaded,
        )
        output_manifest = match_dir / "download_manifest.json"
        output_manifest.write_text(
            json.dumps(asdict(result), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return output_manifest, result
