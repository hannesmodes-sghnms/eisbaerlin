from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://www.penny-del.org/statistik/saison-{season}/{phase}/playerstats/{category}"
CATEGORIES = {
    "passes": "paesse",
    "defense": "verteidigung",
    "xg": "xg",
}
PLAYER_ID_RE = re.compile(r"-(\d+)/details(?:[/?#]|$)")
TEAM_ID_RE = re.compile(r"team_(\d+)\.svg(?:[?#]|$)", re.I)

ADDITIVE_FIELDS = (
    "passes_completed",
    "passes_attempted",
    "total_pass_distance_m",
    "forward_pass_distance_m",
    "received_passes",
    "pcw_won",
    "pcw_total",
    "blocked_shots",
    "xg_sum",
    "goals",
)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, Any]]]] = []
        self._table: list[list[dict[str, Any]]] | None = None
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: v for k, v in attrs}
        if tag == "table":
            if self._table_depth == 0:
                self._table = []
            self._table_depth += 1
            return
        if self._table_depth <= 0:
            return
        if tag == "tr" and self._row is None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None and self._cell is None:
            self._cell = {"tag": tag, "text": [], "hrefs": [], "imgs": []}
        elif tag == "a" and self._cell is not None and attrs_dict.get("href"):
            self._cell["hrefs"].append(attrs_dict["href"])
        elif tag == "img" and self._cell is not None and attrs_dict.get("src"):
            self._cell["imgs"].append(attrs_dict["src"])

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._table_depth <= 0:
            return
        if tag in {"th", "td"} and self._cell is not None:
            self._cell["text"] = _clean_text(" ".join(self._cell["text"]))
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._table is not None and self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth == 0 and self._table is not None:
                if self._table:
                    self.tables.append(self._table)
                self._table = None


def _clean_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _parse_int(value: str | None) -> int | None:
    text = _clean_text(value or "")
    if not text or text in {"-", "–"}:
        return None
    text = text.replace("%", "").replace(" ", "")
    # These columns are integer counts/distances. DEL uses a dot as a
    # thousands separator here (e.g. 1.045 m).
    text = text.replace(".", "").replace(",", "")
    match = re.search(r"-?\d+", text)
    return int(match.group(0)) if match else None


def _parse_float(value: str | None) -> float | None:
    text = _clean_text(value or "")
    if not text or text in {"-", "–"}:
        return None
    text = text.replace("%", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def _parse_pair(value: str | None) -> tuple[int | None, int | None]:
    text = _clean_text(value or "")
    match = re.search(r"(\d[\d.]*)\s*/\s*(\d[\d.]*)", text)
    if not match:
        return None, None
    return _parse_int(match.group(1)), _parse_int(match.group(2))


def _display_name(raw: str) -> str:
    raw = _clean_text(raw)
    if "," not in raw:
        return raw
    surname, given = [part.strip() for part in raw.split(",", 1)]
    return f"{given} {surname}".strip()


def _cell_map(table: list[list[dict[str, Any]]], required_header: str) -> tuple[dict[str, int], list[list[dict[str, Any]]]]:
    for idx, row in enumerate(table):
        headers = [_clean_text(str(cell.get("text") or "")) for cell in row]
        if required_header in headers and "Spieler" in headers and "Team" in headers:
            return {name: pos for pos, name in enumerate(headers)}, table[idx + 1 :]
    raise ValueError(f"Could not find DEL Insight table header {required_header!r}")


def _find_table(html: str, required_header: str) -> tuple[dict[str, int], list[list[dict[str, Any]]]]:
    parser = _TableParser()
    parser.feed(html)
    for table in parser.tables:
        try:
            return _cell_map(table, required_header)
        except ValueError:
            continue
    raise ValueError(f"DEL page did not contain expected table {required_header!r}")


def _row_identity(row: list[dict[str, Any]]) -> dict[str, Any] | None:
    hrefs = [href for cell in row for href in cell.get("hrefs", [])]
    player_href = next((href for href in hrefs if "/spielerdetails/" in href), None)
    if not player_href:
        return None
    player_match = PLAYER_ID_RE.search(player_href)
    if not player_match:
        return None

    imgs = [src for cell in row for src in cell.get("imgs", [])]
    team_match = next((TEAM_ID_RE.search(src) for src in imgs if TEAM_ID_RE.search(src)), None)
    if not team_match:
        return None

    return {
        "player_id": int(player_match.group(1)),
        "team_id": int(team_match.group(1)),
    }


def _text(row: list[dict[str, Any]], columns: dict[str, int], key: str) -> str:
    idx = columns.get(key)
    if idx is None or idx >= len(row):
        return ""
    return _clean_text(str(row[idx].get("text") or ""))


def parse_passes_html(html: str) -> list[dict[str, Any]]:
    columns, rows = _find_table(html, "Passes")
    result: list[dict[str, Any]] = []
    for row in rows:
        identity = _row_identity(row)
        if not identity:
            continue
        completed, attempted = _parse_pair(_text(row, columns, "Passes"))
        result.append(
            {
                **identity,
                "jersey": _parse_int(_text(row, columns, "#")),
                "player_name": _display_name(_text(row, columns, "Spieler")),
                "position": _text(row, columns, "POS"),
                "passes_completed": completed,
                "passes_attempted": attempted,
                "pass_pct": _parse_float(_text(row, columns, "Pass%")),
                "total_pass_distance_m": _parse_int(_text(row, columns, "TP DIST (m)")),
                "forward_pass_distance_m": _parse_int(_text(row, columns, "FP DIST (m)")),
                "received_passes": _parse_int(_text(row, columns, "Rcvd Passes")),
            }
        )
    if len(result) < 20:
        raise ValueError(f"DEL passes table unexpectedly small: {len(result)} player rows")
    return result


def parse_defense_html(html: str) -> list[dict[str, Any]]:
    columns, rows = _find_table(html, "PCW")
    result: list[dict[str, Any]] = []
    for row in rows:
        identity = _row_identity(row)
        if not identity:
            continue
        won, total = _parse_pair(_text(row, columns, "PCW"))
        result.append(
            {
                **identity,
                "jersey": _parse_int(_text(row, columns, "#")),
                "player_name": _display_name(_text(row, columns, "Spieler")),
                "position": _text(row, columns, "POS"),
                "pcw_won": won,
                "pcw_total": total,
                "pcw_pct": _parse_float(_text(row, columns, "PCW%")),
                "blocked_shots": _parse_int(_text(row, columns, "BKS")),
            }
        )
    if len(result) < 20:
        raise ValueError(f"DEL defense table unexpectedly small: {len(result)} player rows")
    return result


def parse_xg_html(html: str) -> list[dict[str, Any]]:
    columns, rows = _find_table(html, "xGsum")
    result: list[dict[str, Any]] = []
    for row in rows:
        identity = _row_identity(row)
        if not identity:
            continue
        result.append(
            {
                **identity,
                "jersey": _parse_int(_text(row, columns, "#")),
                "player_name": _display_name(_text(row, columns, "Spieler")),
                "position": _text(row, columns, "POS"),
                "xg_sum": _parse_float(_text(row, columns, "xGsum")),
                "xg_avg": _parse_float(_text(row, columns, "xGavg")),
                "goals": _parse_int(_text(row, columns, "Tore")),
                "xg_diff": _parse_float(_text(row, columns, "xGDiff")),
            }
        )
    if len(result) < 20:
        raise ValueError(f"DEL xG table unexpectedly small: {len(result)} player rows")
    return result


def _merge_player_rows(groups: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for rows in groups:
        for row in rows:
            player_id = int(row["player_id"])
            current = merged.setdefault(player_id, {"player_id": player_id})
            for key, value in row.items():
                if value is not None and value != "":
                    current[key] = value
    return sorted(merged.values(), key=lambda row: (int(row.get("team_id") or 999), str(row.get("player_name") or "")))


def _ratio(numerator: int | float | None, denominator: int | float | None) -> float | None:
    if denominator in (None, 0):
        return None
    return round(float(numerator or 0) / float(denominator) * 100.0, 2)


def aggregate_team(players: Iterable[dict[str, Any]], team_id: int, *, games_played: int | None = None) -> dict[str, Any]:
    rows = [row for row in players if int(row.get("team_id") or -1) == int(team_id)]

    def sum_int(key: str) -> int:
        return sum(int(row.get(key) or 0) for row in rows)

    def sum_float(key: str) -> float:
        return round(sum(float(row.get(key) or 0.0) for row in rows), 2)

    passes_completed = sum_int("passes_completed")
    passes_attempted = sum_int("passes_attempted")
    pcw_won = sum_int("pcw_won")
    pcw_total = sum_int("pcw_total")
    xg_sum = sum_float("xg_sum")
    goals = sum_int("goals")
    result = {
        "team_id": int(team_id),
        "passes_completed": passes_completed,
        "passes_attempted": passes_attempted,
        "pass_pct": _ratio(passes_completed, passes_attempted),
        "total_pass_distance_m": sum_int("total_pass_distance_m"),
        "forward_pass_distance_m": sum_int("forward_pass_distance_m"),
        "received_passes": sum_int("received_passes"),
        "pcw_won": pcw_won,
        "pcw_total": pcw_total,
        "pcw_pct": _ratio(pcw_won, pcw_total),
        "blocked_shots": sum_int("blocked_shots"),
        "xg_sum": xg_sum,
        "goals": goals,
        "xg_diff": round(goals - xg_sum, 2),
        "players": len(rows),
    }
    if games_played:
        result["xg_per_game"] = round(xg_sum / int(games_played), 2)
    else:
        result["xg_per_game"] = None
    return result


def _snapshot_signature(players: list[dict[str, Any]]) -> str:
    material = json.dumps(players, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def fetch_snapshot(
    *,
    season: str = "2026-27",
    phase: str = "hauptrunde",
    timeout: int = 30,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    http = session or requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DEL-Event-Lab/0.9; +https://github.com/hannesmodes-sghnms/eisbaerlin)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
    }
    pages: dict[str, str] = {}
    urls: dict[str, str] = {}
    for name, category in CATEGORIES.items():
        url = BASE_URL.format(season=season, phase=phase, category=category)
        response = http.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        pages[name] = response.text
        urls[name] = url

    players = _merge_player_rows(
        [
            parse_passes_html(pages["passes"]),
            parse_defense_html(pages["defense"]),
            parse_xg_html(pages["xg"]),
        ]
    )
    if len(players) < 100:
        raise ValueError(f"Merged DEL Insight snapshot unexpectedly small: {len(players)} players")

    generated = datetime.now(timezone.utc).replace(microsecond=0)
    team_ids = sorted({int(row["team_id"]) for row in players if row.get("team_id") is not None})
    snapshot = {
        "schema_version": 1,
        "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
        "season": season,
        "phase": phase,
        "source": "PENNY DEL / Wisehockey public player statistics",
        "source_urls": urls,
        "players": players,
        "teams": [aggregate_team(players, team_id) for team_id in team_ids],
    }
    snapshot["content_sha256"] = _snapshot_signature(players)
    return snapshot


def load_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_latest_snapshot(root: Path = Path("data/del_insight")) -> dict[str, Any] | None:
    return load_snapshot(root / "latest.json")


def persist_snapshot(snapshot: dict[str, Any], root: Path = Path("data/del_insight")) -> tuple[Path, bool]:
    root.mkdir(parents=True, exist_ok=True)
    history = root / "snapshots"
    history.mkdir(parents=True, exist_ok=True)
    latest = root / "latest.json"
    previous = load_snapshot(latest)
    changed = not previous or previous.get("content_sha256") != snapshot.get("content_sha256")
    if not changed:
        return latest, False

    stamp = str(snapshot["generated_at_utc"]).replace("-", "").replace(":", "").replace("+00:00", "Z")
    stamp = stamp.replace("Z", "") + "Z"
    history_path = history / f"{stamp}.json"
    text = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    history_path.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return history_path, True


def list_snapshots(root: Path = Path("data/del_insight")) -> list[dict[str, Any]]:
    snapshots = []
    for path in sorted((root / "snapshots").glob("*.json")):
        try:
            payload = load_snapshot(path)
            if payload:
                payload["_path"] = str(path)
                snapshots.append(payload)
        except (OSError, json.JSONDecodeError):
            continue
    snapshots.sort(key=lambda row: _parse_utc(str(row.get("generated_at_utc") or "1970-01-01T00:00:00Z")))
    return snapshots


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _player_map(snapshot: dict[str, Any], team_id: int) -> dict[int, dict[str, Any]]:
    return {
        int(row["player_id"]): row
        for row in snapshot.get("players", [])
        if int(row.get("team_id") or -1) == int(team_id)
    }


def _team_signature(snapshot: dict[str, Any], team_id: int) -> tuple[Any, ...]:
    rows = _player_map(snapshot, team_id)
    material = []
    for player_id, row in sorted(rows.items()):
        material.append((player_id, *(row.get(key) for key in ADDITIVE_FIELDS)))
    return tuple(material)


def _delta_value(after: Any, before: Any, *, decimals: int | None = None) -> int | float | None:
    if after is None and before is None:
        return None
    value = float(after or 0) - float(before or 0)
    # Small xG corrections from source rounding can produce -0.00.
    if abs(value) < 1e-9:
        value = 0.0
    if decimals is not None:
        return round(value, decimals)
    return int(round(value))


def _player_delta(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any] | None:
    before = before or {}
    row = {
        "player_id": int(after["player_id"]),
        "team_id": int(after["team_id"]),
        "player_name": after.get("player_name"),
        "jersey": after.get("jersey"),
        "position": after.get("position"),
    }
    for key in (
        "passes_completed",
        "passes_attempted",
        "total_pass_distance_m",
        "forward_pass_distance_m",
        "received_passes",
        "pcw_won",
        "pcw_total",
        "blocked_shots",
        "goals",
    ):
        row[key] = _delta_value(after.get(key), before.get(key))
    row["xg_sum"] = _delta_value(after.get("xg_sum"), before.get("xg_sum"), decimals=2)

    row["pass_pct"] = _ratio(row.get("passes_completed"), row.get("passes_attempted"))
    row["pcw_pct"] = _ratio(row.get("pcw_won"), row.get("pcw_total"))
    goals = row.get("goals")
    xg = row.get("xg_sum")
    row["xg_diff"] = round(float(goals or 0) - float(xg or 0), 2) if xg is not None else None

    activity = [row.get("passes_attempted"), row.get("pcw_total"), row.get("xg_sum"), row.get("blocked_shots"), row.get("goals")]
    if not any(abs(float(value or 0)) > 1e-9 for value in activity):
        return None
    return row


def _team_delta(before: dict[str, Any], after: dict[str, Any], team_id: int) -> dict[str, Any]:
    before_map = _player_map(before, team_id)
    after_map = _player_map(after, team_id)
    rows: list[dict[str, Any]] = []
    for player_id, after_row in after_map.items():
        delta = _player_delta(before_map.get(player_id), after_row)
        if delta:
            rows.append(delta)
    rows.sort(key=lambda row: (-float(row.get("xg_sum") or 0), -int(row.get("passes_attempted") or 0), str(row.get("player_name") or "")))
    return {
        "summary": aggregate_team(rows, team_id),
        "players": rows,
    }


def _match_start_utc(match: dict[str, Any], timezone_name: str) -> datetime | None:
    value = match.get("start_date")
    if not value:
        return None
    local = datetime.fromisoformat(str(value))
    if local.tzinfo is None:
        local = local.replace(tzinfo=ZoneInfo(timezone_name))
    return local.astimezone(timezone.utc)


def derive_game_deltas(
    *,
    root: Path = Path("data/del_insight"),
    discovery_path: Path = Path("data/discovery/season_2026_27_type_1.json"),
    timezone_name: str = "Europe/Berlin",
) -> list[Path]:
    snapshots = list_snapshots(root)
    if len(snapshots) < 2 or not discovery_path.exists():
        return []

    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    matches = [row for row in discovery.get("matches", []) if row.get("status") == "AFTER_MATCH"]
    timed_matches = []
    for match in matches:
        start = _match_start_utc(match, timezone_name)
        if start:
            timed_matches.append((start, match))
    timed_matches.sort(key=lambda item: item[0])

    output_dir = root / "games"
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    snap_times = [(_parse_utc(str(snap["generated_at_utc"])), snap) for snap in snapshots]

    for start, match in timed_matches:
        before_candidates = [(t, snap) for t, snap in snap_times if t < start]
        if not before_candidates:
            continue
        before_time, before = before_candidates[-1]
        teams_payload: dict[str, Any] = {}
        reasons: dict[str, str] = {}

        for team_id in (int(match["home_team_id"]), int(match["away_team_id"])):
            baseline_signature = _team_signature(before, team_id)
            after_pair: tuple[datetime, dict[str, Any]] | None = None
            for snap_time, snap in snap_times:
                if snap_time <= start:
                    continue
                if _team_signature(snap, team_id) != baseline_signature:
                    after_pair = (snap_time, snap)
                    break
            if not after_pair:
                reasons[str(team_id)] = "no changed post-game DEL Insight snapshot yet"
                continue

            after_time, after = after_pair
            intervening = [
                other
                for other_start, other in timed_matches
                if start < other_start < after_time
                and team_id in {int(other["home_team_id"]), int(other["away_team_id"])}
            ]
            if intervening:
                reasons[str(team_id)] = "multiple team games occurred before the next changed snapshot"
                continue

            delta = _team_delta(before, after, team_id)
            delta["snapshot_before"] = before.get("generated_at_utc")
            delta["snapshot_after"] = after.get("generated_at_utc")
            teams_payload[str(team_id)] = delta

        if not teams_payload:
            continue

        payload = {
            "schema_version": 1,
            "match_id": int(match["match_id"]),
            "start_date": match.get("start_date"),
            "home_team_id": int(match["home_team_id"]),
            "away_team_id": int(match["away_team_id"]),
            "method": "difference between cumulative PENNY DEL / Wisehockey snapshots",
            "teams": teams_payload,
            "unavailable": reasons,
        }
        path = output_dir / f"{match['match_id']}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written


def load_game_insight(root: Path, match_id: int) -> dict[str, Any] | None:
    return load_snapshot(root / "games" / f"{int(match_id)}.json")


def team_season_summary(snapshot: dict[str, Any] | None, team_id: int, *, games_played: int | None = None) -> dict[str, Any] | None:
    if not snapshot:
        return None
    rows = snapshot.get("players") or []
    if not any(int(row.get("team_id") or -1) == int(team_id) for row in rows):
        return None
    result = aggregate_team(rows, int(team_id), games_played=games_played)
    result["snapshot_at"] = snapshot.get("generated_at_utc")
    return result
