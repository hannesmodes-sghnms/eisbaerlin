from __future__ import annotations

from math import exp
from typing import Any


def _game_end_seconds(
    shots: list[dict[str, Any]],
    shifts: list[dict[str, Any]],
    goals: list[dict[str, Any]],
    *,
    minimum_s: int = 3600,
) -> int:
    values = [int(minimum_s)]
    values.extend(int(row.get("game_time_s") or 0) for row in shots)
    values.extend(int(row.get("end_time_s") or 0) for row in shifts)
    values.extend(int(row.get("time_s") or 0) for row in goals)
    return max(values)


def _powerplay_intervals(
    shifts: list[dict[str, Any]],
    players: list[dict[str, Any]],
    *,
    focus_team_id: int,
    opponent_team_id: int,
    game_end_s: int,
    min_interval_s: int = 5,
) -> list[dict[str, Any]]:
    """Reconstruct manpower advantages from skater shifts.

    Skater counts are capped at five so an empty-net 6v5 is not mistaken for
    a powerplay. Short boundary fragments are discarded because DEL shift
    timestamps occasionally have one-second handover gaps.
    """
    position = {
        (int(row["team_id"]), int(row["player_id"])): str(row.get("position") or "")
        for row in players
        if row.get("team_id") is not None and row.get("player_id") is not None
    }
    skater_shifts = [
        row
        for row in shifts
        if int(row.get("team_id") or -1) in {focus_team_id, opponent_team_id}
        and position.get((int(row.get("team_id") or -1), int(row.get("player_id") or -1)), "") != "GK"
    ]
    if not skater_shifts:
        return []

    boundaries = {0, int(game_end_s)}
    for row in skater_shifts:
        start = max(0, min(int(game_end_s), int(row.get("start_time_s") or 0)))
        end = max(0, min(int(game_end_s), int(row.get("end_time_s") or 0)))
        if end > start:
            boundaries.add(start)
            boundaries.add(end)

    ordered = sorted(boundaries)
    raw: list[dict[str, Any]] = []
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        probe = start + (end - start) / 2

        counts: dict[int, int] = {}
        for team_id in (focus_team_id, opponent_team_id):
            active = {
                int(row["player_id"])
                for row in skater_shifts
                if int(row["team_id"]) == team_id
                and int(row.get("start_time_s") or 0) <= probe < int(row.get("end_time_s") or 0)
            }
            # Ignore the sixth skater from an empty-net situation.
            counts[team_id] = min(5, len(active))

        focus_count = counts[focus_team_id]
        opponent_count = counts[opponent_team_id]
        if focus_count == opponent_count:
            continue

        if focus_count > opponent_count and opponent_count < 5:
            pp_team_id = focus_team_id
        elif opponent_count > focus_count and focus_count < 5:
            pp_team_id = opponent_team_id
        else:
            continue

        raw.append({"team_id": pp_team_id, "start_s": int(start), "end_s": int(end)})

    merged: list[dict[str, Any]] = []
    for row in raw:
        if (
            merged
            and merged[-1]["team_id"] == row["team_id"]
            and int(row["start_s"]) - int(merged[-1]["end_s"]) <= 2
        ):
            merged[-1]["end_s"] = max(int(merged[-1]["end_s"]), int(row["end_s"]))
        else:
            merged.append(dict(row))

    result = []
    for row in merged:
        if int(row["end_s"]) - int(row["start_s"]) < int(min_interval_s):
            continue
        team_id = int(row["team_id"])
        result.append(
            {
                **row,
                "side": "ebb" if team_id == focus_team_id else "opponent",
            }
        )
    return result


def _shot_density(
    shot_times: list[int],
    *,
    game_end_s: int,
    step_s: int,
    sigma_s: int,
) -> list[float]:
    if not shot_times:
        return [0.0 for _ in range(0, game_end_s + step_s, step_s)]

    window = sigma_s * 3
    values = []
    for t in range(0, game_end_s + step_s, step_s):
        value = 0.0
        for shot_t in shot_times:
            delta = t - shot_t
            if abs(delta) > window:
                continue
            value += exp(-0.5 * (delta / sigma_s) ** 2)
        values.append(round(value, 3))
    return values


def build_game_flow(
    shots: list[dict[str, Any]],
    shifts: list[dict[str, Any]],
    players: list[dict[str, Any]],
    goals: list[dict[str, Any]],
    *,
    focus_team_id: int,
    opponent_team_id: int,
    step_s: int = 15,
    sigma_s: int = 45,
) -> dict[str, Any]:
    """Build a transparent shot-attempt momentum series for one game.

    Every DEL shot attempt contributes equally. The curve is a Gaussian-smoothed
    event density, not xG and not a probability model.
    """
    game_end_s = _game_end_seconds(shots, shifts, goals)
    ebb_times = [
        int(row.get("game_time_s") or 0)
        for row in shots
        if int(row.get("team_id") or -1) == focus_team_id
    ]
    opponent_times = [
        int(row.get("game_time_s") or 0)
        for row in shots
        if int(row.get("team_id") or -1) == opponent_team_id
    ]
    ebb_density = _shot_density(ebb_times, game_end_s=game_end_s, step_s=step_s, sigma_s=sigma_s)
    opponent_density = _shot_density(opponent_times, game_end_s=game_end_s, step_s=step_s, sigma_s=sigma_s)

    points = []
    for index, t in enumerate(range(0, game_end_s + step_s, step_s)):
        points.append(
            {
                "time_s": t,
                "ebb": ebb_density[index],
                "opponent": opponent_density[index],
            }
        )

    goal_rows = []
    for row in goals:
        team_id = int(row.get("team_id") or -1)
        if team_id not in {focus_team_id, opponent_team_id}:
            continue
        scorer = row.get("scorer") or {}
        goal_rows.append(
            {
                "time_s": int(row.get("time_s") or 0),
                "team_id": team_id,
                "side": "ebb" if team_id == focus_team_id else "opponent",
                "team_abbr": row.get("team_abbr"),
                "score": row.get("score"),
                "balance": row.get("balance"),
                "scorer": scorer.get("name"),
            }
        )

    return {
        "method": "gaussian_shot_attempt_density",
        "label": "geglättete Shot-Attempt-Dichte",
        "step_s": int(step_s),
        "sigma_s": int(sigma_s),
        "game_end_s": int(game_end_s),
        "points": points,
        "powerplays": _powerplay_intervals(
            shifts,
            players,
            focus_team_id=focus_team_id,
            opponent_team_id=opponent_team_id,
            game_end_s=game_end_s,
        ),
        "goals": goal_rows,
    }
