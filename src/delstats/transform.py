from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SHOT_RESULT_MAP = {
    1: "on_goal",
    2: "missed",
    3: "blocked",
    4: "goal",
    5: "post",
}

NEUTRAL_FACE_OFFS = {"C", "ABL", "ABR", "HBL", "HBR"}
HOME_OFFENSIVE_FACE_OFFS = {"ADL", "ADR"}
HOME_DEFENSIVE_FACE_OFFS = {"HDL", "HDR"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def match_team_ids(match_dir: Path) -> tuple[int, int]:
    shots = load_json(match_dir / "shots.json")["match"]
    return int(shots["home_id"]), int(shots["visitor_id"])


def player_team_map(match_dir: Path) -> dict[int, int]:
    home_id, away_id = match_team_ids(match_dir)
    roster = load_json(match_dir / "roster.json")
    result: dict[int, int] = {}
    for side, team_id in (("home", home_id), ("visitor", away_id)):
        for player in roster.get(side, {}).values():
            result[int(player["playerId"])] = team_id
    return result


def faceoff_zone_for_team(position_shortcut: str | None, team_id: int, home_team_id: int) -> str:
    if not position_shortcut:
        return "unknown"
    if position_shortcut in NEUTRAL_FACE_OFFS:
        return "neutral"
    if team_id == home_team_id:
        if position_shortcut in HOME_OFFENSIVE_FACE_OFFS:
            return "offensive"
        if position_shortcut in HOME_DEFENSIVE_FACE_OFFS:
            return "defensive"
    else:
        if position_shortcut in HOME_OFFENSIVE_FACE_OFFS:
            return "defensive"
        if position_shortcut in HOME_DEFENSIVE_FACE_OFFS:
            return "offensive"
    return "unknown"


def resolve_on_ice_players(
    shifts: list[dict[str, Any]],
    *,
    team_id: int,
    game_time_s: int,
) -> tuple[list[int], str]:
    """Resolve skaters on ice for one team at an event timestamp.

    Shift feeds generally behave like half-open intervals [start, end). This is
    the default. Some event timestamps land exactly on a recorded shift end,
    which can produce an implausibly small active set because the feed is only
    precise to integer seconds. In that case only, add shifts ending exactly at
    the event second and mark the row as boundary_adjusted.
    """
    team_shifts = [s for s in shifts if int(s["team"]["id"]) == team_id]
    active = {
        int(s["player"]["id"])
        for s in team_shifts
        if int(s["startTime"]["time"]) <= game_time_s < int(s["endTime"]["time"])
    }
    if len(active) >= 3:
        return sorted(active), "exact"

    boundary = {
        int(s["player"]["id"])
        for s in team_shifts
        if int(s["endTime"]["time"]) == game_time_s
    }
    adjusted = active | boundary
    if len(adjusted) > len(active):
        return sorted(adjusted), "boundary_adjusted"
    return sorted(active), "low_confidence"


def previous_faceoff(faceoffs: list[dict[str, Any]], game_time_s: int) -> dict[str, Any] | None:
    candidates = [f for f in faceoffs if int(f["time"]) <= game_time_s]
    if not candidates:
        return None
    return max(candidates, key=lambda x: int(x["time"]))


def flatten_period_events(payload: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sequence = 0
    for period_key in ("1", "2", "3", "overtime", "shootout"):
        for event in payload.get(period_key, []):
            sequence += 1
            rows.append({"period_key": period_key, "sequence": sequence, **event})
    return rows


def resolve_on_ice_pair(
    shifts: list[dict[str, Any]],
    *,
    team_a_id: int,
    team_b_id: int,
    game_time_s: int,
) -> tuple[list[int], list[int], str, str]:
    """Resolve both teams together so second-boundary fallback is symmetric.

    If either half-open active set has fewer than three skaters, the timestamp is
    likely sitting on a one-second shift boundary. In that case, shifts ending
    exactly at the event second are added for both teams.
    """
    # Resolve the pure half-open sets first. If one side falls below the
    # minimum of three skaters, apply the same second-boundary fallback to both.
    def half_open(team_id: int) -> set[int]:
        return {
            int(s["player"]["id"])
            for s in shifts
            if int(s["team"]["id"]) == team_id
            and int(s["startTime"]["time"]) <= game_time_s < int(s["endTime"]["time"])
        }

    pure_a = half_open(team_a_id)
    pure_b = half_open(team_b_id)
    if len(pure_a) >= 3 and len(pure_b) >= 3:
        return sorted(pure_a), sorted(pure_b), "exact", "exact"

    def with_boundary(team_id: int, active: set[int]) -> list[int]:
        ending = {
            int(s["player"]["id"])
            for s in shifts
            if int(s["team"]["id"]) == team_id
            and int(s["endTime"]["time"]) == game_time_s
        }
        return sorted(active | ending)

    adj_a = with_boundary(team_a_id, pure_a)
    adj_b = with_boundary(team_b_id, pure_b)
    method_a = "boundary_adjusted" if adj_a != sorted(pure_a) else "low_confidence"
    method_b = "boundary_adjusted" if adj_b != sorted(pure_b) else "low_confidence"
    return adj_a, adj_b, method_a, method_b
