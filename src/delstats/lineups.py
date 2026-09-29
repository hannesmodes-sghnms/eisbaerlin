from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

MIN_STABLE_UNIT_SECONDS = 8
REGULATION_END_S = 3600
PERIOD_BOUNDS = (0, 1200, 2400, 3600)


@dataclass(frozen=True)
class UnitUsage:
    player_ids: tuple[int, ...]
    names: tuple[str, ...]
    jerseys: tuple[int | None, ...]
    total_s: int
    p1_s: int
    p2_s: int
    p3_s: int
    appearances: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "player_ids": list(self.player_ids),
            "names": list(self.names),
            "jerseys": list(self.jerseys),
            "label": " – ".join(self.names),
            "total_s": self.total_s,
            "p1_s": self.p1_s,
            "p2_s": self.p2_s,
            "p3_s": self.p3_s,
            "appearances": self.appearances,
        }


def _period_for_time(game_time_s: int) -> int | None:
    if 0 <= game_time_s < 1200:
        return 1
    if 1200 <= game_time_s < 2400:
        return 2
    if 2400 <= game_time_s < 3600:
        return 3
    return None


def _normalize_shift(row: Any) -> dict[str, int]:
    if isinstance(row, dict):
        return {
            "team_id": int(row["team_id"]),
            "player_id": int(row["player_id"]),
            "start": int(row.get("start_time_s", row.get("start", 0))),
            "end": int(row.get("end_time_s", row.get("end", 0))),
        }
    team_id, player_id, start, end = row[:4]
    return {"team_id": int(team_id), "player_id": int(player_id), "start": int(start), "end": int(end)}


def _normalize_player(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return {
            "team_id": int(row["team_id"]),
            "player_id": int(row["player_id"]),
            "full_name": str(row.get("full_name") or row.get("player_name") or row.get("name") or row["player_id"]),
            "last_name": str(row.get("last_name") or row.get("surname") or row.get("full_name") or row["player_id"]),
            "jersey": row.get("jersey"),
            "position": str(row.get("position") or ""),
        }
    team_id, player_id, full_name, last_name, jersey, position = row[:6]
    return {
        "team_id": int(team_id),
        "player_id": int(player_id),
        "full_name": str(full_name or player_id),
        "last_name": str(last_name or full_name or player_id),
        "jersey": jersey,
        "position": str(position or ""),
    }


def _merge_occurrences(intervals: list[tuple[int, int, int]], *, max_gap_s: int = 1) -> list[tuple[int, int, int]]:
    if not intervals:
        return []
    merged: list[list[int]] = []
    for start, end, period in sorted(intervals):
        if merged and merged[-1][2] == period and start - merged[-1][1] <= max_gap_s:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end, period])
    return [(a, b, p) for a, b, p in merged]


def _aggregate_units(
    raw: dict[tuple[int, ...], list[tuple[int, int, int]]],
    players: dict[int, dict[str, Any]],
    *,
    min_stable_seconds: int,
) -> list[UnitUsage]:
    result: list[UnitUsage] = []
    for player_ids, intervals in raw.items():
        occurrences = [
            item for item in _merge_occurrences(intervals) if item[1] - item[0] >= min_stable_seconds
        ]
        if not occurrences:
            continue
        period_seconds = defaultdict(int)
        for start, end, period in occurrences:
            period_seconds[period] += end - start
        total = sum(period_seconds.values())
        ordered = tuple(sorted(player_ids, key=lambda pid: (players[pid].get("jersey") or 999, players[pid]["last_name"])))
        result.append(
            UnitUsage(
                player_ids=ordered,
                names=tuple(players[pid]["last_name"] for pid in ordered),
                jerseys=tuple(players[pid].get("jersey") for pid in ordered),
                total_s=total,
                p1_s=period_seconds[1],
                p2_s=period_seconds[2],
                p3_s=period_seconds[3],
                appearances=len(occurrences),
            )
        )
    return sorted(result, key=lambda item: (item.total_s, item.appearances), reverse=True)


def analyze_5v5_lineups(
    shifts: Iterable[Any],
    players: Iterable[Any],
    *,
    focus_team_id: int,
    opponent_team_id: int,
    min_stable_seconds: int = MIN_STABLE_UNIT_SECONDS,
) -> dict[str, Any]:
    """Reconstruct stable 5v5 EBB units from skater shifts.

    A unit occurrence only counts when the exact forward trio / defense pair is
    continuously present for at least ``min_stable_seconds``. This filters out
    short combinations created by rolling line changes.
    """

    shift_rows = [_normalize_shift(row) for row in shifts]
    player_rows = [_normalize_player(row) for row in players]
    pmap = {row["player_id"]: row for row in player_rows}

    boundaries = set(PERIOD_BOUNDS)
    for row in shift_rows:
        if 0 <= row["start"] <= REGULATION_END_S:
            boundaries.add(row["start"])
        if 0 <= row["end"] <= REGULATION_END_S:
            boundaries.add(row["end"])
    ordered_boundaries = sorted(boundaries)

    trio_intervals: dict[tuple[int, ...], list[tuple[int, int, int]]] = defaultdict(list)
    pair_intervals: dict[tuple[int, ...], list[tuple[int, int, int]]] = defaultdict(list)
    player_5v5 = defaultdict(lambda: defaultdict(int))
    team_5v5_seconds = defaultdict(int)

    for start, end in zip(ordered_boundaries, ordered_boundaries[1:]):
        if end <= start or start >= REGULATION_END_S:
            continue
        period = _period_for_time(start)
        if period is None:
            continue
        focus_active = {
            row["player_id"]
            for row in shift_rows
            if row["team_id"] == focus_team_id and row["start"] <= start < row["end"]
        }
        opp_active = {
            row["player_id"]
            for row in shift_rows
            if row["team_id"] == opponent_team_id and row["start"] <= start < row["end"]
        }
        if len(focus_active) != 5 or len(opp_active) != 5:
            continue

        duration = end - start
        team_5v5_seconds[period] += duration
        for player_id in focus_active:
            player_5v5[player_id][period] += duration

        forwards = tuple(sorted(pid for pid in focus_active if pmap.get(pid, {}).get("position") == "FO"))
        defense = tuple(sorted(pid for pid in focus_active if pmap.get(pid, {}).get("position") == "DE"))
        if len(forwards) == 3:
            trio_intervals[forwards].append((start, end, period))
        if len(defense) == 2:
            pair_intervals[defense].append((start, end, period))

    trios = _aggregate_units(trio_intervals, pmap, min_stable_seconds=min_stable_seconds)
    pairs = _aggregate_units(pair_intervals, pmap, min_stable_seconds=min_stable_seconds)

    player_usage = []
    for player_id, periods in player_5v5.items():
        info = pmap.get(player_id, {})
        player_usage.append(
            {
                "player_id": player_id,
                "name": info.get("full_name", str(player_id)),
                "last_name": info.get("last_name", str(player_id)),
                "jersey": info.get("jersey"),
                "position": info.get("position"),
                "p1_s": periods[1],
                "p2_s": periods[2],
                "p3_s": periods[3],
                "total_s": periods[1] + periods[2] + periods[3],
            }
        )
    player_usage.sort(key=lambda row: row["total_s"], reverse=True)

    def active_count(period: int, position: str) -> int:
        return sum(
            1
            for row in player_usage
            if row["position"] == position and row[f"p{period}_s"] >= 30
        )

    def concentration(periods: tuple[int, ...], position: str, top_n: int) -> float | None:
        candidates = []
        total = 0
        for row in player_usage:
            if row["position"] != position:
                continue
            seconds = sum(row[f"p{p}_s"] for p in periods)
            candidates.append(seconds)
            total += seconds
        if total <= 0:
            return None
        return round(sum(sorted(candidates, reverse=True)[:top_n]) / total * 100.0, 1)

    top9_pre = concentration((1, 2), "FO", 9)
    top9_p3 = concentration((3,), "FO", 9)
    top4d_pre = concentration((1, 2), "DE", 4)
    top4d_p3 = concentration((3,), "DE", 4)
    active_forwards = {f"p{p}": active_count(p, "FO") for p in (1, 2, 3)}
    active_defense = {f"p{p}": active_count(p, "DE") for p in (1, 2, 3)}

    new_p3_trios = [
        unit.as_dict()
        for unit in trios
        if unit.p1_s + unit.p2_s < 15 and unit.p3_s >= 30 and unit.appearances >= 2
    ]
    dropped_p3_trios = [
        unit.as_dict()
        for unit in trios
        if unit.p1_s + unit.p2_s >= 120 and unit.p3_s < 15
    ]
    new_p3_pairs = [
        unit.as_dict()
        for unit in pairs
        if unit.p1_s + unit.p2_s < 15 and unit.p3_s >= 30 and unit.appearances >= 1
    ]

    usage_changes = []
    pre_team_seconds = team_5v5_seconds[1] + team_5v5_seconds[2]
    p3_team_seconds = team_5v5_seconds[3]
    for row in player_usage:
        position_slots = 3 if row["position"] == "FO" else 2 if row["position"] == "DE" else 1
        pre_denominator = pre_team_seconds * position_slots
        p3_denominator = p3_team_seconds * position_slots
        pre_share_pct = ((row["p1_s"] + row["p2_s"]) / pre_denominator * 100.0) if pre_denominator else 0.0
        p3_share_pct = (row["p3_s"] / p3_denominator * 100.0) if p3_denominator else 0.0
        usage_changes.append({
            "player_id": row["player_id"],
            "name": row["name"],
            "last_name": row["last_name"],
            "jersey": row["jersey"],
            "position": row["position"],
            "pre_p3_share_pct": round(pre_share_pct, 1),
            "p3_share_pct": round(p3_share_pct, 1),
            "delta_pp": round(p3_share_pct - pre_share_pct, 1),
        })
    p3_toi_drops = sorted(
        [row for row in usage_changes if row["pre_p3_share_pct"] >= 8.0 and row["delta_pp"] <= -4.0],
        key=lambda row: row["delta_pp"],
    )
    p3_toi_increases = sorted(
        [row for row in usage_changes if row["p3_share_pct"] >= 8.0 and row["delta_pp"] >= 4.0],
        key=lambda row: row["delta_pp"],
        reverse=True,
    )

    shortened = False
    reasons: list[str] = []
    if top9_pre is not None and top9_p3 is not None and top9_p3 - top9_pre >= 5.0:
        shortened = True
        reasons.append(f"Top-9-Forward-Anteil +{top9_p3 - top9_pre:.1f} Prozentpunkte")
    baseline_active = min(active_forwards["p1"], active_forwards["p2"])
    if baseline_active and active_forwards["p3"] <= baseline_active - 2:
        shortened = True
        reasons.append(f"aktive Forwards {baseline_active} → {active_forwards['p3']}")

    return {
        "min_stable_unit_seconds": min_stable_seconds,
        "five_v_five_seconds": {"p1": team_5v5_seconds[1], "p2": team_5v5_seconds[2], "p3": team_5v5_seconds[3]},
        "forward_trios": [unit.as_dict() for unit in trios],
        "defense_pairs": [unit.as_dict() for unit in pairs],
        "player_5v5_usage": player_usage,
        "rotation": {
            "active_forwards": active_forwards,
            "active_defense": active_defense,
            "top9_forward_share_pre_p3_pct": top9_pre,
            "top9_forward_share_p3_pct": top9_p3,
            "top4_defense_share_pre_p3_pct": top4d_pre,
            "top4_defense_share_p3_pct": top4d_p3,
            "shortened_bank_detected": shortened,
            "shortened_bank_reasons": reasons,
            "new_p3_forward_trios": new_p3_trios,
            "dropped_p3_forward_trios": dropped_p3_trios,
            "new_p3_defense_pairs": new_p3_pairs,
            "p3_toi_drops": p3_toi_drops,
            "p3_toi_increases": p3_toi_increases,
        },
    }
