from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .roles import DEFAULT_FLEXIBLE_ROLES, resolve_skater_roles

MIN_STABLE_UNIT_SECONDS = 8
MIN_CHANGE_SECONDS = 30
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
    p1_appearances: int
    p2_appearances: int
    p3_appearances: int

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
            "p1_appearances": self.p1_appearances,
            "p2_appearances": self.p2_appearances,
            "p3_appearances": self.p3_appearances,
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


def _ordered_ids(player_ids: tuple[int, ...], players: dict[int, dict[str, Any]]) -> tuple[int, ...]:
    return tuple(sorted(player_ids, key=lambda pid: (players.get(pid, {}).get("jersey") or 999, players.get(pid, {}).get("last_name", str(pid)))))


def _aggregate_units(
    raw: dict[tuple[int, ...], list[tuple[int, int, int]]],
    players: dict[int, dict[str, Any]],
    *,
    min_stable_seconds: int,
) -> list[UnitUsage]:
    result: list[UnitUsage] = []
    for player_ids, intervals in raw.items():
        occurrences = [item for item in _merge_occurrences(intervals) if item[1] - item[0] >= min_stable_seconds]
        if not occurrences:
            continue
        period_seconds = defaultdict(int)
        period_apps = defaultdict(int)
        for start, end, period in occurrences:
            period_seconds[period] += end - start
            period_apps[period] += 1
        total = sum(period_seconds.values())
        ordered = _ordered_ids(player_ids, players)
        result.append(
            UnitUsage(
                player_ids=ordered,
                names=tuple(players.get(pid, {}).get("last_name", str(pid)) for pid in ordered),
                jerseys=tuple(players.get(pid, {}).get("jersey") for pid in ordered),
                total_s=total,
                p1_s=period_seconds[1],
                p2_s=period_seconds[2],
                p3_s=period_seconds[3],
                appearances=len(occurrences),
                p1_appearances=period_apps[1],
                p2_appearances=period_apps[2],
                p3_appearances=period_apps[3],
            )
        )
    return sorted(result, key=lambda item: (item.total_s, item.appearances), reverse=True)


def _aggregate_forward_matchups(
    raw: dict[tuple[tuple[int, ...], tuple[int, ...]], list[tuple[int, int, int]]],
    players: dict[int, dict[str, Any]],
    *,
    min_stable_seconds: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (ebb_ids, opp_ids), intervals in raw.items():
        occurrences = [item for item in _merge_occurrences(intervals) if item[1] - item[0] >= min_stable_seconds]
        if not occurrences:
            continue
        period_seconds = defaultdict(int)
        period_apps = defaultdict(int)
        for start, end, period in occurrences:
            period_seconds[period] += end - start
            period_apps[period] += 1
        ebb_ordered = _ordered_ids(ebb_ids, players)
        opp_ordered = _ordered_ids(opp_ids, players)
        ebb_names = [players.get(pid, {}).get("last_name", str(pid)) for pid in ebb_ordered]
        opp_names = [players.get(pid, {}).get("last_name", str(pid)) for pid in opp_ordered]
        rows.append(
            {
                "ebb_player_ids": list(ebb_ordered),
                "opponent_player_ids": list(opp_ordered),
                "ebb_label": " – ".join(ebb_names),
                "opponent_label": " – ".join(opp_names),
                "total_s": sum(period_seconds.values()),
                "p1_s": period_seconds[1],
                "p2_s": period_seconds[2],
                "p3_s": period_seconds[3],
                "appearances": len(occurrences),
                "p1_appearances": period_apps[1],
                "p2_appearances": period_apps[2],
                "p3_appearances": period_apps[3],
            }
        )
    return sorted(rows, key=lambda row: (row["total_s"], row["appearances"]), reverse=True)


def _lineup_changes(units: list[UnitUsage], *, kind: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for unit in units:
        seconds = {1: unit.p1_s, 2: unit.p2_s, 3: unit.p3_s}
        apps = {1: unit.p1_appearances, 2: unit.p2_appearances, 3: unit.p3_appearances}
        payload = unit.as_dict()
        for period in (2, 3):
            previous = period - 1
            current_s = seconds[period]
            previous_s = seconds[previous]
            prior_all_s = sum(seconds[p] for p in range(1, period))
            if current_s >= MIN_CHANGE_SECONDS and (apps[period] >= 2 or current_s >= 45) and previous_s < 15:
                changes.append(
                    {
                        "kind": kind,
                        "change_type": "introduced" if prior_all_s < 15 else "returned",
                        "period": period,
                        "label": payload["label"],
                        "player_ids": payload["player_ids"],
                        "current_s": current_s,
                        "previous_s": previous_s,
                        "prior_total_s": prior_all_s,
                        "appearances": apps[period],
                    }
                )
            if previous_s >= 60 and current_s < 15:
                changes.append(
                    {
                        "kind": kind,
                        "change_type": "dropped",
                        "period": period,
                        "label": payload["label"],
                        "player_ids": payload["player_ids"],
                        "current_s": current_s,
                        "previous_s": previous_s,
                        "prior_total_s": prior_all_s,
                        "appearances": apps[period],
                    }
                )
    return sorted(changes, key=lambda row: (row["period"], -max(row["current_s"], row["previous_s"]), row["label"]))


def analyze_5v5_lineups(
    shifts: Iterable[Any],
    players: Iterable[Any],
    *,
    focus_team_id: int,
    opponent_team_id: int,
    min_stable_seconds: int = MIN_STABLE_UNIT_SECONDS,
    flexible_roles: Mapping[int, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Reconstruct exact 5v5 units and line matching from skater shifts.

    The raw 5v5 player usage counts every interval in which both teams have
    exactly five skaters in the shift feed. "Stable" units are a filtered view:
    an exact trio/pair (or exact trio-vs-trio matchup) must persist for at least
    ``min_stable_seconds`` continuously. This removes most rolling-change noise
    while preserving the underlying 5v5 TOI separately for coverage checks.
    """

    shift_rows = [_normalize_shift(row) for row in shifts]
    player_rows = [_normalize_player(row) for row in players]
    pmap = {row["player_id"]: row for row in player_rows}
    flexible_roles = flexible_roles or DEFAULT_FLEXIBLE_ROLES

    boundaries = set(PERIOD_BOUNDS)
    for row in shift_rows:
        if 0 <= row["start"] <= REGULATION_END_S:
            boundaries.add(row["start"])
        if 0 <= row["end"] <= REGULATION_END_S:
            boundaries.add(row["end"])
    ordered_boundaries = sorted(boundaries)

    trio_intervals: dict[tuple[int, ...], list[tuple[int, int, int]]] = defaultdict(list)
    pair_intervals: dict[tuple[int, ...], list[tuple[int, int, int]]] = defaultdict(list)
    opponent_trio_intervals: dict[tuple[int, ...], list[tuple[int, int, int]]] = defaultdict(list)
    matchup_intervals: dict[tuple[tuple[int, ...], tuple[int, ...]], list[tuple[int, int, int]]] = defaultdict(list)
    player_5v5 = defaultdict(lambda: defaultdict(int))
    player_role_seconds = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
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

        focus_roles = resolve_skater_roles(focus_active, pmap, flexible_roles=flexible_roles)
        opponent_roles = resolve_skater_roles(opp_active, pmap, flexible_roles=flexible_roles)
        forwards = tuple(sorted(focus_roles.forwards))
        defense = tuple(sorted(focus_roles.defense))
        opp_forwards = tuple(sorted(opponent_roles.forwards))
        for pid, role in focus_roles.assignments.items():
            player_role_seconds[pid][role][period] += duration
        if focus_roles.standard:
            trio_intervals[forwards].append((start, end, period))
            pair_intervals[defense].append((start, end, period))
        if opponent_roles.standard:
            opponent_trio_intervals[opp_forwards].append((start, end, period))
        if focus_roles.standard and opponent_roles.standard:
            matchup_intervals[(forwards, opp_forwards)].append((start, end, period))

    trios = _aggregate_units(trio_intervals, pmap, min_stable_seconds=min_stable_seconds)
    pairs = _aggregate_units(pair_intervals, pmap, min_stable_seconds=min_stable_seconds)
    opponent_trios = _aggregate_units(opponent_trio_intervals, pmap, min_stable_seconds=min_stable_seconds)
    forward_matchups = _aggregate_forward_matchups(matchup_intervals, pmap, min_stable_seconds=min_stable_seconds)

    stable_by_player = defaultdict(int)
    stable_by_player_role = defaultdict(lambda: defaultdict(int))
    for unit in trios:
        for player_id in unit.player_ids:
            stable_by_player[player_id] += unit.total_s
            stable_by_player_role[player_id]["FO"] += unit.total_s
    for unit in pairs:
        for player_id in unit.player_ids:
            stable_by_player[player_id] += unit.total_s
            stable_by_player_role[player_id]["DE"] += unit.total_s

    player_usage = []
    for player_id, periods in player_5v5.items():
        info = pmap.get(player_id, {})
        total = periods[1] + periods[2] + periods[3]
        stable = stable_by_player[player_id]
        fo_total = sum(player_role_seconds[player_id]["FO"].values())
        de_total = sum(player_role_seconds[player_id]["DE"].values())
        usage_role = "FO/DE" if fo_total >= 30 and de_total >= 30 else "FO" if fo_total >= de_total else "DE"
        player_usage.append(
            {
                "player_id": player_id,
                "name": info.get("full_name", str(player_id)),
                "last_name": info.get("last_name", str(player_id)),
                "jersey": info.get("jersey"),
                "position": info.get("position"),
                "usage_role": usage_role,
                "role_fo_s": fo_total,
                "role_de_s": de_total,
                "p1_s": periods[1],
                "p2_s": periods[2],
                "p3_s": periods[3],
                "total_s": total,
                "stable_unit_s": stable,
                "stable_unit_coverage_pct": round(stable / total * 100.0, 1) if total else None,
            }
        )
    player_usage.sort(key=lambda row: row["total_s"], reverse=True)

    def active_count(period: int, role: str) -> int:
        return sum(1 for pid in player_5v5 if player_role_seconds[pid][role][period] >= 30)

    def concentration(periods: tuple[int, ...], role: str, top_n: int) -> float | None:
        candidates = []
        total = 0
        for pid in player_5v5:
            seconds = sum(player_role_seconds[pid][role][p] for p in periods)
            if seconds <= 0:
                continue
            candidates.append(seconds)
            total += seconds
        if total <= 0:
            return None
        return round(sum(sorted(candidates, reverse=True)[:top_n]) / total * 100.0, 1)

    def stable_coverage(role: str) -> float | None:
        denominator = sum(
            sum(player_role_seconds[pid][role].values())
            for pid in player_5v5
        )
        if denominator <= 0:
            return None
        numerator = sum(stable_by_player_role[pid][role] for pid in player_5v5)
        return round(numerator / denominator * 100.0, 1)

    top9_pre = concentration((1, 2), "FO", 9)
    top9_p3 = concentration((3,), "FO", 9)
    top4d_pre = concentration((1, 2), "DE", 4)
    top4d_p3 = concentration((3,), "DE", 4)
    active_forwards = {f"p{p}": active_count(p, "FO") for p in (1, 2, 3)}
    active_defense = {f"p{p}": active_count(p, "DE") for p in (1, 2, 3)}

    new_p3_trios = [
        unit.as_dict()
        for unit in trios
        if unit.p1_s + unit.p2_s < 15 and unit.p3_s >= 30 and unit.p3_appearances >= 2
    ]
    dropped_p3_trios = [unit.as_dict() for unit in trios if unit.p1_s + unit.p2_s >= 120 and unit.p3_s < 15]
    new_p3_pairs = [
        unit.as_dict()
        for unit in pairs
        if unit.p1_s + unit.p2_s < 15 and unit.p3_s >= 30 and unit.p3_appearances >= 1
    ]

    usage_changes = []
    pre_team_seconds = team_5v5_seconds[1] + team_5v5_seconds[2]
    p3_team_seconds = team_5v5_seconds[3]
    for row in player_usage:
        pid = row["player_id"]
        pre_fo = player_role_seconds[pid]["FO"][1] + player_role_seconds[pid]["FO"][2]
        pre_de = player_role_seconds[pid]["DE"][1] + player_role_seconds[pid]["DE"][2]
        p3_fo = player_role_seconds[pid]["FO"][3]
        p3_de = player_role_seconds[pid]["DE"][3]
        role = "FO" if (pre_fo + p3_fo) >= (pre_de + p3_de) else "DE"
        position_slots = 3 if role == "FO" else 2
        pre_seconds = pre_fo if role == "FO" else pre_de
        p3_seconds = p3_fo if role == "FO" else p3_de
        pre_denominator = pre_team_seconds * position_slots
        p3_denominator = p3_team_seconds * position_slots
        pre_share_pct = (pre_seconds / pre_denominator * 100.0) if pre_denominator else 0.0
        p3_share_pct = (p3_seconds / p3_denominator * 100.0) if p3_denominator else 0.0
        usage_changes.append(
            {
                "player_id": row["player_id"],
                "name": row["name"],
                "last_name": row["last_name"],
                "jersey": row["jersey"],
                "position": row["position"],
                "usage_role": row.get("usage_role"),
                "pre_p3_share_pct": round(pre_share_pct, 1),
                "p3_share_pct": round(p3_share_pct, 1),
                "delta_pp": round(p3_share_pct - pre_share_pct, 1),
            }
        )
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

    lineup_changes = _lineup_changes(trios, kind="forward") + _lineup_changes(pairs, kind="defense")
    kind_order = {"forward": 0, "defense": 1}
    lineup_changes.sort(key=lambda row: (row["period"], kind_order.get(row["kind"], 9), row["change_type"], row["label"]))

    # One primary opponent line for each stable EBB trio. This is easier to read
    # than a full cross-product while the full matchup table remains available.
    primary_matchups = []
    trio_totals = {tuple(unit.player_ids): unit.total_s for unit in trios}
    by_ebb: dict[tuple[int, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in forward_matchups:
        by_ebb[tuple(row["ebb_player_ids"])].append(row)
    for ebb_ids, rows in by_ebb.items():
        if trio_totals.get(ebb_ids, 0) < 60:
            continue
        top = max(rows, key=lambda row: (row["total_s"], row["appearances"]))
        primary_matchups.append(
            {
                **top,
                "ebb_unit_total_s": trio_totals.get(ebb_ids, 0),
                "matchup_share_pct": round(top["total_s"] / trio_totals[ebb_ids] * 100.0, 1)
                if trio_totals.get(ebb_ids)
                else None,
            }
        )
    primary_matchups.sort(key=lambda row: row["ebb_unit_total_s"], reverse=True)

    return {
        "min_stable_unit_seconds": min_stable_seconds,
        "five_v_five_seconds": {"p1": team_5v5_seconds[1], "p2": team_5v5_seconds[2], "p3": team_5v5_seconds[3]},
        "forward_trios": [unit.as_dict() for unit in trios],
        "defense_pairs": [unit.as_dict() for unit in pairs],
        "opponent_forward_trios": [unit.as_dict() for unit in opponent_trios],
        "forward_matchups": forward_matchups,
        "primary_forward_matchups": primary_matchups,
        "player_5v5_usage": player_usage,
        "coverage": {
            "forward_stable_pct": stable_coverage("FO"),
            "defense_stable_pct": stable_coverage("DE"),
        },
        "lineup_changes": lineup_changes,
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
