from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import DelSourceConfig
from .http import DelHttpClient
from .s3 import PublicS3Bucket, S3Object


@dataclass
class MatchRecord:
    match_id: int
    start_date: str | None
    status: str | None
    home_team_id: int | None
    home_team_name: str | None
    away_team_id: int | None
    away_team_name: str | None
    source_schedule_keys: list[str]


@dataclass
class SeasonDiscovery:
    season: int
    game_type: int
    schedule_prefix: str
    schedule_keys: list[str]
    team_ids: list[int]
    matches: list[MatchRecord]


@dataclass
class MatchResourceDiscovery:
    match_id: int
    match_prefix: str
    resources: dict[str, list[str]]
    all_keys: list[str]
    shot_key: str
    shot_url: str
    shot_exists: bool | None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _team_fields(value: Any) -> tuple[int | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    team_id = _int_or_none(value.get("id") or value.get("team_id") or value.get("teamId"))
    name = (
        value.get("name")
        or value.get("title")
        or value.get("shortcut")
        or value.get("short_name")
    )
    return team_id, str(name) if name is not None else None


def normalize_match(match: dict[str, Any], schedule_key: str) -> MatchRecord | None:
    match_id = _int_or_none(match.get("id") or match.get("match_id") or match.get("matchId"))
    if match_id is None:
        return None

    home_obj = match.get("home") or match.get("home_team") or match.get("homeTeam")
    away_obj = (
        match.get("guest")
        or match.get("away")
        or match.get("visitor")
        or match.get("away_team")
        or match.get("visitor_team")
        or match.get("awayTeam")
    )
    home_id, home_name = _team_fields(home_obj)
    away_id, away_name = _team_fields(away_obj)

    start_date = (
        match.get("start_date")
        or match.get("startDate")
        or match.get("date")
        or match.get("datetime")
    )
    status = match.get("status") or match.get("state")

    return MatchRecord(
        match_id=match_id,
        start_date=str(start_date) if start_date is not None else None,
        status=str(status) if status is not None else None,
        home_team_id=home_id,
        home_team_name=home_name,
        away_team_id=away_id,
        away_team_name=away_name,
        source_schedule_keys=[schedule_key],
    )


def extract_matches(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("matches", "games", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = value.get("matches") or value.get("games")
            if isinstance(nested, list):
                return [x for x in nested if isinstance(x, dict)]
    return []


def team_id_from_schedule_key(key: str) -> int | None:
    filename = key.rsplit("/", 1)[-1]
    stem = filename.removesuffix(".json")
    return _int_or_none(stem)


def classify_match_keys(keys: Iterable[str], match_id: int) -> dict[str, list[str]]:
    resources: dict[str, list[str]] = {
        "game_header": [],
        "roster": [],
        "period_events": [],
        "shifts": [],
        "faceoffs": [],
        "team_stats": [],
        "goalies": [],
        "other": [],
    }
    prefix = f"matches/{match_id}/"
    for key in keys:
        relative = key[len(prefix):] if key.startswith(prefix) else key
        lower = relative.lower()
        if "game-header" in lower or "game_header" in lower:
            bucket = "game_header"
        elif lower.startswith("roster") or "/roster" in lower:
            bucket = "roster"
        elif "period-events" in lower or "period_events" in lower:
            bucket = "period_events"
        elif "shift" in lower:
            bucket = "shifts"
        elif "faceoff" in lower:
            bucket = "faceoffs"
        elif "team-stats" in lower or "team_stats" in lower:
            bucket = "team_stats"
        elif "goalie" in lower:
            bucket = "goalies"
        else:
            bucket = "other"
        resources[bucket].append(key)

    for value in resources.values():
        value.sort()
    return resources


class SeasonDiscoverer:
    def __init__(
        self,
        *,
        bucket: PublicS3Bucket | None = None,
        http: DelHttpClient | None = None,
        config: DelSourceConfig | None = None,
    ) -> None:
        self.config = config or DelSourceConfig()
        self.http = http or DelHttpClient()
        self.bucket = bucket or PublicS3Bucket(client=self.http, config=self.config)

    def discover_season(self, season: int, game_type: int = 1) -> SeasonDiscovery:
        prefix = f"league-team-matches/{season}/{game_type}/"
        schedule_objects = self.bucket.list_objects(prefix)
        schedule_keys = sorted(
            obj.key for obj in schedule_objects if obj.key.endswith(".json")
        )

        if not schedule_keys:
            raise RuntimeError(
                f"No schedule JSON files found under {prefix!r}. "
                "Check season/game type or source layout."
            )

        records: dict[int, MatchRecord] = {}
        team_ids: set[int] = set()

        for key in schedule_keys:
            team_id = team_id_from_schedule_key(key)
            if team_id is not None:
                team_ids.add(team_id)

            payload = self.http.get_json(self.config.object_url(key))
            for raw_match in extract_matches(payload):
                record = normalize_match(raw_match, key)
                if record is None:
                    continue
                if record.match_id in records:
                    existing = records[record.match_id]
                    if key not in existing.source_schedule_keys:
                        existing.source_schedule_keys.append(key)
                    # Schedules for home/away teams should describe the same match.
                    # Fill blanks without overwriting already-populated values.
                    for field in (
                        "start_date", "status", "home_team_id", "home_team_name",
                        "away_team_id", "away_team_name"
                    ):
                        if getattr(existing, field) is None and getattr(record, field) is not None:
                            setattr(existing, field, getattr(record, field))
                else:
                    records[record.match_id] = record

        matches = sorted(
            records.values(),
            key=lambda x: ((x.start_date or "9999"), x.match_id),
        )
        for record in matches:
            record.source_schedule_keys.sort()

        return SeasonDiscovery(
            season=season,
            game_type=game_type,
            schedule_prefix=prefix,
            schedule_keys=schedule_keys,
            team_ids=sorted(team_ids),
            matches=matches,
        )

    def discover_match_resources(
        self,
        match_id: int,
        *,
        verify_shots: bool = False,
    ) -> MatchResourceDiscovery:
        prefix = f"matches/{match_id}/"
        objects = self.bucket.list_objects(prefix)
        keys = sorted(obj.key for obj in objects)
        resources = classify_match_keys(keys, match_id)

        shot_key = f"visualization/shots/{match_id}.json"
        shot_url = self.config.object_url(shot_key)
        shot_exists: bool | None = None
        if verify_shots:
            response = self.http.get(shot_url, headers={"Range": "bytes=0-0"})
            shot_exists = response.status_code in {200, 206}

        return MatchResourceDiscovery(
            match_id=match_id,
            match_prefix=prefix,
            resources=resources,
            all_keys=keys,
            shot_key=shot_key,
            shot_url=shot_url,
            shot_exists=shot_exists,
        )


def save_season_discovery(result: SeasonDiscovery, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"season_{result.season}_{str(result.season + 1)[-2:]}_type_{result.game_type}"
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}_matches.csv"

    json_path.write_text(
        json.dumps(asdict(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    fieldnames = [
        "match_id", "start_date", "status", "home_team_id", "home_team_name",
        "away_team_id", "away_team_name", "source_schedule_keys"
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for match in result.matches:
            row = asdict(match)
            row["source_schedule_keys"] = "|".join(match.source_schedule_keys)
            writer.writerow(row)

    return json_path, csv_path


def save_match_discovery(result: MatchResourceDiscovery, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"match_{result.match_id}_resources.json"
    path.write_text(
        json.dumps(asdict(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
