from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _example(value: Any) -> Any:
    if isinstance(value, str) and len(value) > 160:
        return value[:157] + "..."
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


@dataclass
class PathStats:
    occurrences: int = 0
    observed_types: set[str] = field(default_factory=set)
    non_null: int = 0
    examples: list[Any] = field(default_factory=list)
    array_lengths: list[int] = field(default_factory=list)
    object_keys: set[str] = field(default_factory=set)

    def observe(self, value: Any) -> None:
        self.occurrences += 1
        value_type = json_type(value)
        self.observed_types.add(value_type)
        if value is not None:
            self.non_null += 1

        if isinstance(value, list):
            self.array_lengths.append(len(value))
        elif isinstance(value, dict):
            self.object_keys.update(str(k) for k in value.keys())
        else:
            candidate = _example(value)
            if candidate not in self.examples and len(self.examples) < 3:
                self.examples.append(candidate)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "occurrences": self.occurrences,
            "observed_types": sorted(self.observed_types),
            "non_null": self.non_null,
        }
        if self.examples:
            result["examples"] = self.examples
        if self.array_lengths:
            result["array_length_min"] = min(self.array_lengths)
            result["array_length_max"] = max(self.array_lengths)
            result["array_length_observations"] = len(self.array_lengths)
        if self.object_keys:
            result["object_keys"] = sorted(self.object_keys)
        return result


def collect_schema(value: Any) -> dict[str, PathStats]:
    stats: dict[str, PathStats] = {}

    def visit(node: Any, path: str) -> None:
        entry = stats.setdefault(path, PathStats())
        entry.observe(node)

        if isinstance(node, dict):
            for key, child in node.items():
                visit(child, f"{path}.{key}")
        elif isinstance(node, list):
            item_path = f"{path}[]"
            for child in node:
                visit(child, item_path)

    visit(value, "$")
    return stats


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_json_file(path: Path, *, base_dir: Path | None = None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    stats = collect_schema(payload)
    relative = path.relative_to(base_dir) if base_dir else path
    return {
        "file": str(relative).replace("\\", "/"),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        "root_type": json_type(payload),
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
        "path_count": len(stats),
        "paths": {key: value.to_dict() for key, value in sorted(stats.items())},
    }


def inspect_match_directory(match_dir: Path) -> dict[str, Any]:
    if not match_dir.is_dir():
        raise FileNotFoundError(f"Raw match directory not found: {match_dir}")

    files = sorted(
        path for path in match_dir.rglob("*.json")
        if path.name not in {"download_manifest.json", "schema_report.json"}
    )
    if not files:
        raise RuntimeError(f"No JSON resources found below {match_dir}")

    return {
        "match_id": int(match_dir.name) if match_dir.name.isdigit() else match_dir.name,
        "raw_dir": str(match_dir),
        "file_count": len(files),
        "files": [inspect_json_file(path, base_dir=match_dir) for path in files],
    }


def _md_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        rendered = str(value)
    return rendered.replace("|", "\\|").replace("\n", " ")


def write_schema_report(
    report: dict[str, Any],
    *,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    match_id = report["match_id"]
    json_path = output_dir / f"match_{match_id}_schema.json"
    md_path = output_dir / f"match_{match_id}_schema.md"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines: list[str] = [
        f"# DEL match {match_id} — raw JSON schema",
        "",
        f"Files inspected: **{report['file_count']}**",
        "",
    ]

    for file_report in report["files"]:
        lines.extend([
            f"## `{file_report['file']}`",
            "",
            f"- Root type: `{file_report['root_type']}`",
            f"- Size: `{file_report['size_bytes']}` bytes",
            f"- SHA-256: `{file_report['sha256']}`",
            f"- Distinct JSON paths: `{file_report['path_count']}`",
            "",
            "| Path | Types | Occurrences | Non-null | Array length | Examples / object keys |",
            "|---|---|---:|---:|---|---|",
        ])

        for path, path_stats in file_report["paths"].items():
            array_len = ""
            if "array_length_min" in path_stats:
                if path_stats["array_length_min"] == path_stats["array_length_max"]:
                    array_len = str(path_stats["array_length_min"])
                else:
                    array_len = (
                        f"{path_stats['array_length_min']}.."
                        f"{path_stats['array_length_max']}"
                    )
            details = path_stats.get("examples") or path_stats.get("object_keys") or ""
            lines.append(
                "| "
                + " | ".join([
                    f"`{_md_cell(path)}`",
                    _md_cell(path_stats["observed_types"]),
                    str(path_stats["occurrences"]),
                    str(path_stats["non_null"]),
                    _md_cell(array_len),
                    _md_cell(details),
                ])
                + " |"
            )
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
