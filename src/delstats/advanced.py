from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .transform import faceoff_zone_for_team
from .roles import DEFAULT_FLEXIBLE_ROLES, RoleResolution, resolve_skater_roles


def _pct(numerator: int | float, denominator: int | float, digits: int = 1) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator) * 100.0, digits)


def _safe_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def scoring_summary_from_events(
    events: Iterable[dict[str, Any]],
    *,
    focus_team_id: int,
    opponent_team_id: int,
    focus_abbr: str,
    opponent_abbr: str,
) -> list[dict[str, Any]]:
    """Return goal events with ordered primary/secondary assists."""
    rows: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") != "goal":
            continue
        payload = _safe_json(event.get("raw_json"))
        data = payload.get("data") or {}
        scorer = data.get("scorer") or {}
        assistants = []
        for idx, assistant in enumerate(data.get("assistants") or [], start=1):
            assistants.append(
                {
                    "order": idx,
                    "player_id": assistant.get("playerId"),
                    "name": " ".join(
                        x for x in [assistant.get("name"), assistant.get("surname")] if x
                    ),
                    "jersey": assistant.get("jersey"),
                }
            )
        team_id = event.get("team_id")
        rows.append(
            {
                "time_s": int(event.get("game_time_s") or 0),
                "period": event.get("period_key"),
                "team_id": team_id,
                "team_abbr": focus_abbr if team_id == focus_team_id else opponent_abbr if team_id == opponent_team_id else "–",
                "score": data.get("currentScore"),
                "balance": event.get("balance") or data.get("balance"),
                "scorer": {
                    "player_id": scorer.get("playerId"),
                    "name": " ".join(x for x in [scorer.get("name"), scorer.get("surname")] if x),
                    "jersey": scorer.get("jersey"),
                },
                "assists": assistants,
                "primary_assist": assistants[0] if assistants else None,
                "secondary_assist": assistants[1] if len(assistants) > 1 else None,
                "empty_net": bool(data.get("en")),
            }
        )
    return rows


def player_impact_5v5_from_shots(
    shots: Iterable[dict[str, Any]],
    players: Iterable[dict[str, Any]],
    *,
    focus_team_id: int,
) -> list[dict[str, Any]]:
    """Calculate single-game 5v5 on-ice shot impact for focus-team skaters."""
    pmap = {
        int(row["player_id"]): row
        for row in players
        if int(row.get("team_id") or -1) == int(focus_team_id) and row.get("position") != "GK"
    }
    stats = {
        pid: defaultdict(int)
        for pid in pmap
    }
    team = defaultdict(int)

    for shot in shots:
        if shot.get("manpower") != "5v5":
            continue
        shooting_team = int(shot.get("team_id") or -1)
        result = shot.get("result")
        is_for = shooting_team == int(focus_team_id)
        team["cf" if is_for else "ca"] += 1
        if result != "blocked":
            team["ff" if is_for else "fa"] += 1
        if result in {"on_goal", "goal"}:
            team["sogf" if is_for else "soga"] += 1
        if result == "goal":
            team["gf" if is_for else "ga"] += 1

        active = shot.get("on_ice_for_player_ids") if is_for else shot.get("on_ice_against_player_ids")
        for player_id in active or []:
            pid = int(player_id)
            if pid not in stats:
                continue
            row = stats[pid]
            row["cf" if is_for else "ca"] += 1
            if result != "blocked":
                row["ff" if is_for else "fa"] += 1
            if result in {"on_goal", "goal"}:
                row["sogf" if is_for else "soga"] += 1
            if result == "goal":
                row["gf" if is_for else "ga"] += 1

    rows: list[dict[str, Any]] = []
    for pid, counts in stats.items():
        cf, ca = counts["cf"], counts["ca"]
        if cf + ca <= 0:
            continue
        off_cf = max(0, team["cf"] - cf)
        off_ca = max(0, team["ca"] - ca)
        cf_pct = _pct(cf, cf + ca)
        off_cf_pct = _pct(off_cf, off_cf + off_ca)
        sh_pct = _pct(counts["gf"], counts["sogf"])
        sv_pct = (round((1.0 - counts["ga"] / counts["soga"]) * 100.0, 1) if counts["soga"] else None)
        rows.append(
            {
                "player_id": pid,
                "name": pmap[pid].get("full_name") or pmap[pid].get("player_name") or str(pid),
                "last_name": pmap[pid].get("last_name") or pmap[pid].get("full_name") or str(pid),
                "jersey": pmap[pid].get("jersey"),
                "position": pmap[pid].get("position"),
                "cf": cf,
                "ca": ca,
                "cf_pct": cf_pct,
                "relative_cf_pct": round(cf_pct - off_cf_pct, 1) if cf_pct is not None and off_cf_pct is not None else None,
                "ff": counts["ff"],
                "fa": counts["fa"],
                "ff_pct": _pct(counts["ff"], counts["ff"] + counts["fa"]),
                "sog_for": counts["sogf"],
                "sog_against": counts["soga"],
                "gf": counts["gf"],
                "ga": counts["ga"],
                "goal_share_pct": _pct(counts["gf"], counts["gf"] + counts["ga"]),
                "on_ice_shooting_pct": sh_pct,
                "on_ice_save_pct": sv_pct,
                "pdo": round(sh_pct + sv_pct, 1) if sh_pct is not None and sv_pct is not None else None,
            }
        )
    return sorted(rows, key=lambda row: ((row["cf_pct"] or 0), row["cf"] + row["ca"]), reverse=True)


def score_state_corsi_5v5(
    shots: Iterable[dict[str, Any]],
    goal_events: Iterable[dict[str, Any]],
    *,
    focus_team_id: int,
    focus_is_home: bool,
) -> list[dict[str, Any]]:
    """Split 5v5 Corsi by score state immediately before each shot."""
    goals: list[tuple[int, int, int]] = []
    for event in goal_events:
        if event.get("event_type") != "goal":
            continue
        payload = _safe_json(event.get("raw_json"))
        score = (payload.get("data") or {}).get("currentScore")
        if not score or ":" not in str(score):
            continue
        try:
            home, away = (int(v) for v in str(score).split(":", 1))
        except ValueError:
            continue
        goals.append((int(event.get("game_time_s") or 0), home, away))
    goals.sort()

    counts = {state: {"cf": 0, "ca": 0} for state in ("tied", "leading", "trailing")}
    for shot in sorted(shots, key=lambda row: (int(row.get("game_time_s") or 0), int(row.get("shot_id") or 0))):
        if shot.get("manpower") != "5v5":
            continue
        t = int(shot.get("game_time_s") or 0)
        home = away = 0
        for gt, gh, ga in goals:
            if gt >= t:
                break
            home, away = gh, ga
        own, opp = (home, away) if focus_is_home else (away, home)
        state = "leading" if own > opp else "trailing" if own < opp else "tied"
        key = "cf" if int(shot.get("team_id") or -1) == int(focus_team_id) else "ca"
        counts[state][key] += 1

    labels = {"tied": "Gleichstand", "leading": "In Führung", "trailing": "Im Rückstand"}
    rows = []
    for state in ("tied", "leading", "trailing"):
        cf, ca = counts[state]["cf"], counts[state]["ca"]
        rows.append({"state": state, "label": labels[state], "cf": cf, "ca": ca, "cf_pct": _pct(cf, cf + ca)})
    return rows


def _active_players(shifts: list[dict[str, Any]], team_id: int, t: int) -> set[int]:
    return {
        int(row["player_id"])
        for row in shifts
        if int(row.get("team_id") or -1) == int(team_id)
        and int(row.get("start_time_s", row.get("start", 0)) or 0) <= t < int(row.get("end_time_s", row.get("end", 0)) or 0)
    }


def zone_starts_5v5(
    shifts: Iterable[dict[str, Any]],
    players: Iterable[dict[str, Any]],
    faceoffs: Iterable[dict[str, Any]],
    *,
    focus_team_id: int,
    opponent_team_id: int,
    home_team_id: int,
    flexible_roles: Mapping[int, Iterable[str]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """5v5 deployment starts by zone for players, forward units and D-pairs.

    This intentionally ignores who won the faceoff. It is a deployment metric,
    not a faceoff-performance metric. Flexible players such as Eric Mik are
    assigned an on-ice role per unit instead of being frozen to the roster
    position.
    """
    shifts = list(shifts)
    pmap = {int(p["player_id"]): p for p in players}
    flexible_roles = flexible_roles or DEFAULT_FLEXIBLE_ROLES
    player_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    trio_counts: dict[tuple[int, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    pair_counts: dict[tuple[int, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for faceoff in faceoffs:
        t = int(faceoff.get("game_time_s") or 0)
        focus_active = _active_players(shifts, focus_team_id, t)
        opp_active = _active_players(shifts, opponent_team_id, t)
        # Shift feeds occasionally put a line change exactly on the faceoff
        # boundary. Mirror the shot-context philosophy and allow a one-second
        # boundary adjustment rather than silently dropping the start.
        if len(focus_active) != 5 or len(opp_active) != 5:
            for probe in (t + 1, max(0, t - 1)):
                fa = _active_players(shifts, focus_team_id, probe)
                oa = _active_players(shifts, opponent_team_id, probe)
                if len(fa) == 5 and len(oa) == 5:
                    focus_active, opp_active = fa, oa
                    break
        if len(focus_active) != 5 or len(opp_active) != 5:
            continue
        zone = faceoff_zone_for_team(faceoff.get("position_shortcut"), focus_team_id, home_team_id)
        bucket = {"offensive": "oz", "defensive": "dz", "neutral": "nz"}.get(zone)
        if not bucket:
            continue
        for pid in focus_active:
            player_counts[pid][bucket] += 1

        roles = resolve_skater_roles(focus_active, pmap, flexible_roles=flexible_roles)
        if roles.standard:
            trio_counts[tuple(sorted(roles.forwards))][bucket] += 1
            pair_counts[tuple(sorted(roles.defense))][bucket] += 1

    def rows(source: dict[Any, dict[str, int]], kind: str) -> list[dict[str, Any]]:
        result = []
        for key, c in source.items():
            ids = (key,) if kind == "player" else key
            oz, dz, nz = c["oz"], c["dz"], c["nz"]
            non_neutral = oz + dz
            ordered = sorted(ids, key=lambda pid: (pmap.get(pid, {}).get("jersey") or 999, pmap.get(pid, {}).get("last_name") or ""))
            names = [pmap.get(pid, {}).get("last_name") or pmap.get(pid, {}).get("full_name") or str(pid) for pid in ordered]
            info = pmap.get(ordered[0], {}) if kind == "player" else {}
            result.append(
                {
                    "player_ids": list(ordered),
                    "player_id": ordered[0] if kind == "player" else None,
                    "label": (info.get("full_name") or names[0]) if kind == "player" else " – ".join(names),
                    "jersey": info.get("jersey") if kind == "player" else None,
                    "position": info.get("position") if kind == "player" else None,
                    "oz": oz,
                    "dz": dz,
                    "nz": nz,
                    "non_neutral": non_neutral,
                    "oz_share_pct": _pct(oz, non_neutral),
                }
            )
        return sorted(result, key=lambda row: (row["non_neutral"], row["oz"] + row["dz"] + row["nz"]), reverse=True)

    return {
        "players": rows(player_counts, "player"),
        "forward_units": rows(trio_counts, "forward"),
        "defense_pairs": rows(pair_counts, "defense"),
    }

def annotate_forward_matchups(
    matchups: Iterable[dict[str, Any]],
    shots: Iterable[dict[str, Any]],
    *,
    focus_team_id: int,
) -> list[dict[str, Any]]:
    """Attach Corsi/slot/goals to already-filtered stable line matchups."""
    shot_rows = [row for row in shots if row.get("manpower") == "5v5"]
    result = []
    for matchup in matchups:
        intervals = matchup.get("intervals") or []
        counts = defaultdict(int)
        for shot in shot_rows:
            t = int(shot.get("game_time_s") or 0)
            if not any(int(iv["start_s"]) <= t < int(iv["end_s"]) for iv in intervals):
                continue
            is_for = int(shot.get("team_id") or -1) == int(focus_team_id)
            counts["cf" if is_for else "ca"] += 1
            if shot.get("shot_zone") == "SLOT":
                counts["slot_for" if is_for else "slot_against"] += 1
            if shot.get("result") == "goal":
                counts["gf" if is_for else "ga"] += 1
        row = {k: v for k, v in matchup.items() if k != "intervals"}
        row.update(
            {
                "cf": counts["cf"],
                "ca": counts["ca"],
                "cf_pct": _pct(counts["cf"], counts["cf"] + counts["ca"]),
                "slot_for": counts["slot_for"],
                "slot_against": counts["slot_against"],
                "gf": counts["gf"],
                "ga": counts["ga"],
            }
        )
        result.append(row)
    return result


def _event_assist_totals(con: Any, team_id: int, match_ids: set[int] | None = None) -> dict[int, dict[str, int]]:
    sql = "SELECT match_id, team_id, raw_json FROM events WHERE event_type='goal' AND team_id=?"
    params: list[Any] = [team_id]
    if match_ids:
        marks = ",".join("?" for _ in match_ids)
        sql += f" AND match_id IN ({marks})"
        params.extend(sorted(match_ids))
    rows = con.execute(sql, params).fetchall()
    result: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for _match_id, _team_id, raw in rows:
        data = (_safe_json(raw).get("data") or {})
        for idx, assistant in enumerate(data.get("assistants") or [], start=1):
            pid = assistant.get("playerId")
            if pid is None:
                continue
            result[int(pid)]["assists"] += 1
            if idx == 1:
                result[int(pid)]["primary_assists"] += 1
            elif idx == 2:
                result[int(pid)]["secondary_assists"] += 1
    return result


def season_top_scorers(con: Any, team_id: int, *, limit: int = 5, recent_games: int = 5) -> list[dict[str, Any]]:
    cur = con.execute(
        """
        SELECT player_id, any_value(player_name) AS player_name, any_value(jersey) AS jersey,
               any_value(position) AS position, sum(games)::BIGINT AS games,
               sum(goals)::BIGINT AS goals, sum(assists)::BIGINT AS assists,
               sum(points)::BIGINT AS points, sum(shots_on_goal)::BIGINT AS shots_on_goal
        FROM player_game_stats
        WHERE team_id=? AND position <> 'GK'
        GROUP BY player_id
        ORDER BY points DESC, goals DESC, player_name
        """,
        [team_id],
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    assist_totals = _event_assist_totals(con, team_id)

    recent_ids = {
        int(row[0])
        for row in con.execute(
            "SELECT match_id FROM team_game_stats WHERE team_id=? ORDER BY match_date DESC, match_id DESC LIMIT ?",
            [team_id, recent_games],
        ).fetchall()
    }
    recent_by_player: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    if recent_ids:
        marks = ",".join("?" for _ in recent_ids)
        q = f"""
            SELECT player_id, sum(games), sum(goals), sum(assists), sum(points), sum(shots_on_goal)
            FROM player_game_stats WHERE team_id=? AND match_id IN ({marks}) GROUP BY player_id
        """
        for pid, games, goals, assists, points, sog in con.execute(q, [team_id, *sorted(recent_ids)]).fetchall():
            recent_by_player[int(pid)].update(games=int(games or 0), goals=int(goals or 0), assists=int(assists or 0), points=int(points or 0), shots_on_goal=int(sog or 0))
    recent_assists = _event_assist_totals(con, team_id, recent_ids) if recent_ids else {}

    enriched = []
    for row in rows[: max(limit * 2, limit)]:
        pid = int(row["player_id"])
        games = int(row.get("games") or 0)
        a = assist_totals.get(pid, {})
        recent = recent_by_player.get(pid, {})
        ra = recent_assists.get(pid, {})
        enriched.append(
            {
                **row,
                "games": games,
                "goals": int(row.get("goals") or 0),
                "assists": int(row.get("assists") or 0),
                "points": int(row.get("points") or 0),
                "shots_on_goal": int(row.get("shots_on_goal") or 0),
                "primary_assists": int(a.get("primary_assists") or 0),
                "secondary_assists": int(a.get("secondary_assists") or 0),
                "primary_points": int(row.get("goals") or 0) + int(a.get("primary_assists") or 0),
                "points_per_game": round(int(row.get("points") or 0) / games, 2) if games else None,
                "last5_games": int(recent.get("games") or 0),
                "last5_goals": int(recent.get("goals") or 0),
                "last5_assists": int(recent.get("assists") or 0),
                "last5_points": int(recent.get("points") or 0),
                "last5_primary_assists": int(ra.get("primary_assists") or 0),
            }
        )
    enriched.sort(key=lambda row: (row["points"], row["goals"], row["primary_points"]), reverse=True)
    return enriched[:limit]


def _goalie_intervals_from_events(raw_dir: Path, match_id: int, team_side: str, game_end_s: int = 3900) -> list[tuple[int, int, int]]:
    path = raw_dir / str(match_id) / "period-events.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    changes = []
    for events in payload.values():
        for event in events:
            if event.get("type") != "goalkeeperChange":
                continue
            data = event.get("data") or {}
            if data.get("team") != team_side:
                continue
            player = data.get("player") or {}
            if player.get("playerId") is not None:
                changes.append((int(event.get("time") or 0), int(player["playerId"])))
    changes.sort()
    intervals = []
    for idx, (start, pid) in enumerate(changes):
        end = changes[idx + 1][0] if idx + 1 < len(changes) else game_end_s
        if end > start:
            intervals.append((start, end, pid))
    return intervals


def goalie_watch(con: Any, raw_dir: Path, team_id: int, *, limit: int = 2) -> list[dict[str, Any]]:
    """Aggregate opponent goalie form and 5v5 shot-stopping from raw game data."""
    match_rows = con.execute(
        """
        SELECT match_id, home_team_id, away_team_id FROM matches
        WHERE home_team_id=? OR away_team_id=? ORDER BY match_date, match_id
        """,
        [team_id, team_id],
    ).fetchall()
    totals: dict[int, dict[str, Any]] = defaultdict(lambda: defaultdict(int))
    names: dict[int, str] = {}
    jerseys: dict[int, int | None] = {}
    appearances: dict[int, list[dict[str, int]]] = defaultdict(list)

    for match_id, home_id, away_id in match_rows:
        match_id = int(match_id)
        goalie_path = raw_dir / str(match_id) / "top-goalies.json"
        if not goalie_path.exists():
            continue
        try:
            goalie_rows = json.loads(goalie_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        played = [g for g in goalie_rows if int(g.get("teamId") or -1) == int(team_id) and (int(g.get("timeOnIce") or 0) > 0 or int(g.get("matches") or 0) > 0)]
        for g in played:
            pid = int(g["playerId"])
            names[pid] = " ".join(x for x in [g.get("name"), g.get("surname")] if x)
            jerseys[pid] = g.get("jersey")
            saves, ga, toi = int(g.get("saves") or 0), int(g.get("goalsAgainst") or 0), int(g.get("timeOnIce") or 0)
            totals[pid]["games"] += int(g.get("matches") or (1 if toi else 0))
            totals[pid]["saves"] += saves
            totals[pid]["ga"] += ga
            totals[pid]["toi_s"] += toi
            totals[pid]["wins"] += int(g.get("wonMatches") or 0)
            totals[pid]["losses"] += int(g.get("lostMatches") or 0)
            appearances[pid].append({"saves": saves, "ga": ga, "toi_s": toi})

        side = "home" if int(home_id) == int(team_id) else "visitor"
        intervals = _goalie_intervals_from_events(raw_dir, match_id, side)
        if not intervals:
            continue
        shots = con.execute(
            """
            SELECT s.game_time_s, s.result, s.shot_zone, c.manpower
            FROM shots s JOIN shot_context c USING(match_id, shot_id)
            WHERE s.match_id=? AND s.team_id<>?
            """,
            [match_id, team_id],
        ).fetchall()
        for t, result, zone, manpower in shots:
            if result not in {"on_goal", "goal"}:
                continue
            goalie_id = next((pid for start, end, pid in intervals if start <= int(t) < end), None)
            if goalie_id is None:
                continue
            if manpower == "5v5":
                totals[goalie_id]["sa_5v5"] += 1
                if result == "goal":
                    totals[goalie_id]["ga_5v5"] += 1
                if zone == "SLOT":
                    totals[goalie_id]["slot_sa_5v5"] += 1
                    if result == "goal":
                        totals[goalie_id]["slot_ga_5v5"] += 1

    league_sog5, league_goals5 = con.execute(
        """
        SELECT count(*), sum(CASE WHEN s.result='goal' THEN 1 ELSE 0 END)
        FROM shots s JOIN shot_context c USING(match_id, shot_id)
        WHERE c.manpower='5v5' AND s.result IN ('on_goal','goal')
        """
    ).fetchone()
    league_sv5 = (1.0 - float(league_goals5 or 0) / float(league_sog5)) if league_sog5 else None

    rows = []
    for pid, t in totals.items():
        sa = int(t["saves"] + t["ga"])
        sa5, ga5 = int(t["sa_5v5"]), int(t["ga_5v5"])
        slot_sa, slot_ga = int(t["slot_sa_5v5"]), int(t["slot_ga_5v5"])
        last = appearances[pid][-5:]
        last_sa = sum(x["saves"] + x["ga"] for x in last)
        last_saves = sum(x["saves"] for x in last)
        rows.append(
            {
                "player_id": pid,
                "name": names.get(pid, str(pid)),
                "jersey": jerseys.get(pid),
                "games": int(t["games"]),
                "wins": int(t["wins"]),
                "losses": int(t["losses"]),
                "toi_s": int(t["toi_s"]),
                "saves": int(t["saves"]),
                "goals_against": int(t["ga"]),
                "save_pct": _pct(t["saves"], sa),
                "gaa": round(int(t["ga"]) * 3600.0 / int(t["toi_s"]), 2) if t["toi_s"] else None,
                "sa_5v5": sa5,
                "ga_5v5": ga5,
                "save_pct_5v5": round((1.0 - ga5 / sa5) * 100.0, 1) if sa5 else None,
                "gsaa_5v5": round(sa5 * (1.0 - league_sv5) - ga5, 2) if sa5 and league_sv5 is not None else None,
                "slot_sa_5v5": slot_sa,
                "slot_save_pct_5v5": round((1.0 - slot_ga / slot_sa) * 100.0, 1) if slot_sa else None,
                "last5_games": len(last),
                "last5_save_pct": _pct(last_saves, last_sa),
            }
        )
    rows.sort(key=lambda row: (row["toi_s"], row["games"]), reverse=True)
    return rows[:limit]


def stable_forward_matchup_performance(
    shifts: Iterable[dict[str, Any]],
    players: Iterable[dict[str, Any]],
    shots: Iterable[dict[str, Any]],
    *,
    focus_team_id: int,
    opponent_team_id: int,
    min_stable_seconds: int = 8,
) -> list[dict[str, Any]]:
    """Reconstruct stable trio-vs-trio matchups and attach 5v5 results.

    A matchup occurrence must persist continuously for at least
    ``min_stable_seconds``. This applies the same rolling-change protection as
    the normal lineup view before counting Corsi, slot attempts and goals.
    """
    shifts = list(shifts)
    players = list(players)
    pmap = {int(row["player_id"]): row for row in players}
    boundaries = {0, 1200, 2400, 3600}
    for row in shifts:
        start = int(row.get("start_time_s", row.get("start", 0)) or 0)
        end = int(row.get("end_time_s", row.get("end", 0)) or 0)
        if 0 <= start <= 3600:
            boundaries.add(start)
        if 0 <= end <= 3600:
            boundaries.add(end)
    ordered = sorted(boundaries)
    raw: dict[tuple[tuple[int, ...], tuple[int, ...]], list[tuple[int, int, int]]] = defaultdict(list)

    def period_for(t: int) -> int | None:
        if 0 <= t < 1200: return 1
        if 1200 <= t < 2400: return 2
        if 2400 <= t < 3600: return 3
        return None

    for start, end in zip(ordered, ordered[1:]):
        if end <= start or start >= 3600:
            continue
        period = period_for(start)
        if period is None:
            continue
        fa = _active_players(shifts, focus_team_id, start)
        oa = _active_players(shifts, opponent_team_id, start)
        if len(fa) != 5 or len(oa) != 5:
            continue
        ff = tuple(sorted(pid for pid in fa if pmap.get(pid, {}).get("position") == "FO"))
        of = tuple(sorted(pid for pid in oa if pmap.get(pid, {}).get("position") == "FO"))
        if len(ff) == 3 and len(of) == 3:
            raw[(ff, of)].append((start, end, period))

    def merge(items: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
        merged: list[list[int]] = []
        for start, end, period in sorted(items):
            if merged and merged[-1][2] == period and start - merged[-1][1] <= 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end, period])
        return [(a, b, p) for a, b, p in merged]

    def label(ids: tuple[int, ...]) -> str:
        ordered_ids = sorted(ids, key=lambda pid: (pmap.get(pid, {}).get("jersey") or 999, pmap.get(pid, {}).get("last_name") or ""))
        return " – ".join(pmap.get(pid, {}).get("last_name") or pmap.get(pid, {}).get("full_name") or str(pid) for pid in ordered_ids)

    rows = []
    shot_rows = [s for s in shots if s.get("manpower") == "5v5"]
    for (ebb_ids, opp_ids), items in raw.items():
        occ = [x for x in merge(items) if x[1] - x[0] >= min_stable_seconds]
        if not occ:
            continue
        periods = defaultdict(int)
        for start, end, period in occ:
            periods[period] += end - start
        counts = defaultdict(int)
        for shot in shot_rows:
            t = int(shot.get("game_time_s") or 0)
            if not any(start <= t < end for start, end, _ in occ):
                continue
            is_for = int(shot.get("team_id") or -1) == int(focus_team_id)
            counts["cf" if is_for else "ca"] += 1
            if shot.get("shot_zone") == "SLOT":
                counts["slot_for" if is_for else "slot_against"] += 1
            if shot.get("result") == "goal":
                counts["gf" if is_for else "ga"] += 1
        rows.append({
            "ebb_player_ids": list(ebb_ids),
            "opponent_player_ids": list(opp_ids),
            "ebb_label": label(ebb_ids),
            "opponent_label": label(opp_ids),
            "total_s": sum(periods.values()),
            "p1_s": periods[1], "p2_s": periods[2], "p3_s": periods[3],
            "appearances": len(occ),
            "cf": counts["cf"], "ca": counts["ca"],
            "cf_pct": _pct(counts["cf"], counts["cf"] + counts["ca"]),
            "slot_for": counts["slot_for"], "slot_against": counts["slot_against"],
            "gf": counts["gf"], "ga": counts["ga"],
        })

    # Add share within all stable matchup time for that EBB trio.
    totals = defaultdict(int)
    for row in rows:
        totals[tuple(sorted(row["ebb_player_ids"]))] += row["total_s"]
    for row in rows:
        total = totals[tuple(sorted(row["ebb_player_ids"]))]
        row["matchup_share_pct"] = _pct(row["total_s"], total)
    return sorted(rows, key=lambda row: (row["total_s"], row["appearances"]), reverse=True)



def forward_matchup_report(
    shifts: Iterable[dict[str, Any]],
    players: Iterable[dict[str, Any]],
    shots: Iterable[dict[str, Any]],
    goal_events: Iterable[dict[str, Any]],
    *,
    focus_team_id: int,
    opponent_team_id: int,
    min_stable_seconds: int = 8,
    relevant_min_toi_s: int = 30,
    flexible_roles: Mapping[int, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Build a complete 5v5 line-performance and line-matching report.

    TOI remains based on stable shift intervals so rolling changes do not create
    fake lines. Event performance is assigned from the actual on-ice skaters at
    the event. Goals use DEL ``attendants`` from the goal event as the source of
    truth, which avoids one-second shot/shift boundary mismatches.

    Flexible roster roles are resolved per unit. For EBB this currently allows
    Eric Mik to be treated as either FO or DE when that produces the observed
    3F/2D five-skater unit.
    """
    shifts = list(shifts)
    players = list(players)
    shots = list(shots)
    goal_events = [row for row in goal_events if row.get("event_type") == "goal"]
    pmap = {int(row["player_id"]): row for row in players}
    flexible_roles = flexible_roles or DEFAULT_FLEXIBLE_ROLES

    def period_for(t: int) -> int | None:
        if 0 <= t < 1200:
            return 1
        if 1200 <= t < 2400:
            return 2
        if 2400 <= t < 3600:
            return 3
        return None

    def merge(items: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
        merged: list[list[int]] = []
        for start, end, period in sorted(items):
            if merged and merged[-1][2] == period and start - merged[-1][1] <= 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end, period])
        return [(a, b, p) for a, b, p in merged]

    def ordered_ids(ids: Iterable[int]) -> tuple[int, ...]:
        return tuple(
            sorted(
                (int(pid) for pid in ids),
                key=lambda pid: (
                    pmap.get(pid, {}).get("jersey") or 999,
                    pmap.get(pid, {}).get("last_name") or pmap.get(pid, {}).get("full_name") or str(pid),
                ),
            )
        )

    def label(ids: Iterable[int]) -> str:
        return " – ".join(
            pmap.get(pid, {}).get("last_name") or pmap.get(pid, {}).get("full_name") or str(pid)
            for pid in ordered_ids(ids)
        )

    def role_notes(resolution: RoleResolution) -> list[str]:
        notes = []
        for pid in resolution.inferred_player_ids:
            name = pmap.get(pid, {}).get("last_name") or pmap.get(pid, {}).get("full_name") or str(pid)
            notes.append(f"{name}→{resolution.assignments.get(pid)}")
        return notes

    boundaries = {0, 1200, 2400, 3600}
    for row in shifts:
        start = int(row.get("start_time_s", row.get("start", 0)) or 0)
        end = int(row.get("end_time_s", row.get("end", 0)) or 0)
        if 0 <= start <= 3600:
            boundaries.add(start)
        if 0 <= end <= 3600:
            boundaries.add(end)
    ordered_boundaries = sorted(boundaries)

    line_raw: dict[tuple[int, ...], list[tuple[int, int, int]]] = defaultdict(list)
    matchup_raw: dict[tuple[tuple[int, ...], tuple[int, ...]], list[tuple[int, int, int]]] = defaultdict(list)
    team_5v5_shift_s = 0
    line_role_notes: dict[tuple[int, ...], set[str]] = defaultdict(set)
    matchup_role_notes: dict[tuple[tuple[int, ...], tuple[int, ...]], set[str]] = defaultdict(set)

    for start, end in zip(ordered_boundaries, ordered_boundaries[1:]):
        if end <= start or start >= 3600:
            continue
        period = period_for(start)
        if period is None:
            continue
        focus_active = _active_players(shifts, focus_team_id, start)
        opp_active = _active_players(shifts, opponent_team_id, start)
        if len(focus_active) != 5 or len(opp_active) != 5:
            continue
        duration = end - start
        team_5v5_shift_s += duration
        fr = resolve_skater_roles(focus_active, pmap, flexible_roles=flexible_roles)
        oroles = resolve_skater_roles(opp_active, pmap, flexible_roles=flexible_roles)
        if fr.standard:
            fkey = tuple(sorted(fr.forwards))
            line_raw[fkey].append((start, end, period))
            line_role_notes[fkey].update(role_notes(fr))
            if oroles.standard:
                okey = tuple(sorted(oroles.forwards))
                mkey = (fkey, okey)
                matchup_raw[mkey].append((start, end, period))
                matchup_role_notes[mkey].update(role_notes(fr))
                matchup_role_notes[mkey].update(role_notes(oroles))

    line_intervals: dict[tuple[int, ...], list[tuple[int, int, int]]] = {}
    matchup_intervals: dict[tuple[tuple[int, ...], tuple[int, ...]], list[tuple[int, int, int]]] = {}
    for key, items in line_raw.items():
        kept = [iv for iv in merge(items) if iv[1] - iv[0] >= min_stable_seconds]
        if kept:
            line_intervals[key] = kept
    for key, items in matchup_raw.items():
        kept = [iv for iv in merge(items) if iv[1] - iv[0] >= min_stable_seconds]
        if kept:
            matchup_intervals[key] = kept

    line_rows: dict[tuple[int, ...], dict[str, Any]] = {}
    matchup_rows: dict[tuple[tuple[int, ...], tuple[int, ...]], dict[str, Any]] = {}

    def ensure_line(key: tuple[int, ...]) -> dict[str, Any]:
        if key not in line_rows:
            periods = defaultdict(int)
            occ = line_intervals.get(key, [])
            for start, end, period in occ:
                periods[period] += end - start
            line_rows[key] = {
                "ebb_player_ids": list(ordered_ids(key)),
                "ebb_label": label(key),
                "total_s": sum(periods.values()),
                "p1_s": periods[1],
                "p2_s": periods[2],
                "p3_s": periods[3],
                "appearances": len(occ),
                "cf": 0,
                "ca": 0,
                "slot_for": 0,
                "slot_against": 0,
                "gf": 0,
                "ga": 0,
                "role_notes": sorted(line_role_notes.get(key, set())),
            }
        return line_rows[key]

    def ensure_matchup(key: tuple[tuple[int, ...], tuple[int, ...]]) -> dict[str, Any]:
        if key not in matchup_rows:
            ebb_ids, opp_ids = key
            periods = defaultdict(int)
            occ = matchup_intervals.get(key, [])
            for start, end, period in occ:
                periods[period] += end - start
            matchup_rows[key] = {
                "ebb_player_ids": list(ordered_ids(ebb_ids)),
                "opponent_player_ids": list(ordered_ids(opp_ids)),
                "ebb_label": label(ebb_ids),
                "opponent_label": label(opp_ids),
                "total_s": sum(periods.values()),
                "p1_s": periods[1],
                "p2_s": periods[2],
                "p3_s": periods[3],
                "appearances": len(occ),
                "cf": 0,
                "ca": 0,
                "slot_for": 0,
                "slot_against": 0,
                "gf": 0,
                "ga": 0,
                "role_notes": sorted(matchup_role_notes.get(key, set())),
            }
        return matchup_rows[key]

    for key in line_intervals:
        ensure_line(key)
    for key in matchup_intervals:
        ensure_matchup(key)

    def resolve_pair(
        focus_ids: Iterable[int], opp_ids: Iterable[int]
    ) -> tuple[RoleResolution, RoleResolution] | None:
        focus_ids = set(int(pid) for pid in focus_ids)
        opp_ids = set(int(pid) for pid in opp_ids)
        if len(focus_ids) != 5 or len(opp_ids) != 5:
            return None
        return (
            resolve_skater_roles(focus_ids, pmap, flexible_roles=flexible_roles),
            resolve_skater_roles(opp_ids, pmap, flexible_roles=flexible_roles),
        )

    def active_pair_with_tolerance(
        t: int,
        provided_focus: set[int],
        provided_opp: set[int],
    ) -> tuple[set[int], set[int]] | None:
        candidates = []
        for delta in (0, 1, -1, 2, -2):
            probe = max(0, t + delta)
            fa = _active_players(shifts, focus_team_id, probe)
            oa = _active_players(shifts, opponent_team_id, probe)
            if len(fa) != 5 or len(oa) != 5:
                continue
            overlap = len(fa & provided_focus) + len(oa & provided_opp)
            candidates.append((overlap, -abs(delta), fa, oa))
        if not candidates:
            return None
        _overlap, _distance, fa, oa = max(candidates, key=lambda item: (item[0], item[1]))
        return fa, oa

    # Corsi/slot: keep the project's existing shot-context definition of 5v5,
    # but assign each event to the actual five skaters. This preserves agreement
    # with the headline Corsi metric while greatly improving matchup coverage.
    total_corsi_5v5 = 0
    assigned_corsi = 0
    for shot in shots:
        if shot.get("manpower") != "5v5":
            continue
        total_corsi_5v5 += 1
        shooting_team = int(shot.get("team_id") or -1)
        on_for = {int(pid) for pid in (shot.get("on_ice_for_player_ids") or [])}
        on_against = {int(pid) for pid in (shot.get("on_ice_against_player_ids") or [])}
        if shooting_team == int(focus_team_id):
            focus_ids, opp_ids = on_for, on_against
        else:
            focus_ids, opp_ids = on_against, on_for

        pair = resolve_pair(focus_ids, opp_ids)
        if pair is None:
            repaired = active_pair_with_tolerance(int(shot.get("game_time_s") or 0), focus_ids, opp_ids)
            if repaired:
                focus_ids, opp_ids = repaired
                pair = resolve_pair(focus_ids, opp_ids)
        if pair is None:
            continue
        fr, oroles = pair
        is_for = shooting_team == int(focus_team_id)
        result = shot.get("result")

        if fr.standard:
            fkey = tuple(sorted(fr.forwards))
            line = ensure_line(fkey)
            line["role_notes"] = sorted(set(line.get("role_notes") or []) | set(role_notes(fr)))
            line["cf" if is_for else "ca"] += 1
            if shot.get("shot_zone") == "SLOT":
                line["slot_for" if is_for else "slot_against"] += 1

        if fr.standard and oroles.standard:
            mkey = (tuple(sorted(fr.forwards)), tuple(sorted(oroles.forwards)))
            matchup = ensure_matchup(mkey)
            matchup["role_notes"] = sorted(
                set(matchup.get("role_notes") or []) | set(role_notes(fr)) | set(role_notes(oroles))
            )
            matchup["cf" if is_for else "ca"] += 1
            if shot.get("shot_zone") == "SLOT":
                matchup["slot_for" if is_for else "slot_against"] += 1
            assigned_corsi += 1

    def skater_ids(entries: Iterable[dict[str, Any]]) -> list[int]:
        ids = []
        for entry in entries or []:
            pid = entry.get("playerId")
            if pid is None:
                continue
            pid = int(pid)
            if str(pmap.get(pid, {}).get("position") or "").upper() == "GK":
                continue
            ids.append(pid)
        return ids

    total_goal_events_5v5 = 0
    assigned_goals = 0
    unresolved_goals: list[dict[str, Any]] = []
    goal_contexts: list[dict[str, Any]] = []
    for event in goal_events:
        payload = _safe_json(event.get("raw_json"))
        data = payload.get("data") or {}
        balance = event.get("balance") or data.get("balance")
        if balance != "EQ" or bool(data.get("en")):
            continue
        attendants = data.get("attendants") or {}
        team_id = int(event.get("team_id") or -1)
        if team_id == int(focus_team_id):
            focus_entries = attendants.get("positive") or []
            opp_entries = attendants.get("negative") or []
        elif team_id == int(opponent_team_id):
            focus_entries = attendants.get("negative") or []
            opp_entries = attendants.get("positive") or []
        else:
            continue
        focus_ids = skater_ids(focus_entries)
        opp_ids = skater_ids(opp_entries)
        if len(set(focus_ids)) != 5 or len(set(opp_ids)) != 5:
            continue
        total_goal_events_5v5 += 1
        fr = resolve_skater_roles(focus_ids, pmap, flexible_roles=flexible_roles)
        oroles = resolve_skater_roles(opp_ids, pmap, flexible_roles=flexible_roles)
        is_for = team_id == int(focus_team_id)
        goal_contexts.append(
            {
                "time_s": int(event.get("game_time_s") or 0),
                "team_id": team_id,
                "focus_ids": list(focus_ids),
                "opponent_ids": list(opp_ids),
                "focus_shape": fr.shape,
                "opponent_shape": oroles.shape,
                "standard": fr.standard and oroles.standard,
            }
        )

        if fr.standard:
            fkey = tuple(sorted(fr.forwards))
            line = ensure_line(fkey)
            line["role_notes"] = sorted(set(line.get("role_notes") or []) | set(role_notes(fr)))
            line["gf" if is_for else "ga"] += 1

        if fr.standard and oroles.standard:
            mkey = (tuple(sorted(fr.forwards)), tuple(sorted(oroles.forwards)))
            matchup = ensure_matchup(mkey)
            matchup["role_notes"] = sorted(
                set(matchup.get("role_notes") or []) | set(role_notes(fr)) | set(role_notes(oroles))
            )
            matchup["gf" if is_for else "ga"] += 1
            assigned_goals += 1
        else:
            unresolved_goals.append(
                {
                    "time_s": int(event.get("game_time_s") or 0),
                    "team_id": team_id,
                    "score": data.get("currentScore"),
                    "focus_shape": fr.shape,
                    "opponent_shape": oroles.shape,
                    "focus_skaters": label(focus_ids),
                    "opponent_skaters": label(opp_ids),
                    "focus_role_notes": role_notes(fr),
                    "opponent_role_notes": role_notes(oroles),
                }
            )

    # Quality flag: DEL goal events can be one second ahead of the shot feed.
    # Count cases where the event is clearly 5v5 but the closest goal shot's
    # current shot_context says otherwise. Goals are still assigned from the
    # goal-event attendants, never silently dropped.
    goal_shot_context_mismatches = 0
    goal_shots = [s for s in shots if s.get("result") == "goal"]
    for ctx in goal_contexts:
        candidates = [
            shot for shot in goal_shots
            if int(shot.get("team_id") or -1) == ctx["team_id"]
            and abs(int(shot.get("game_time_s") or 0) - ctx["time_s"]) <= 2
        ]
        if not candidates:
            continue
        closest = min(candidates, key=lambda shot: abs(int(shot.get("game_time_s") or 0) - ctx["time_s"]))
        if closest.get("manpower") != "5v5":
            goal_shot_context_mismatches += 1

    # Finalize line totals before matchup shares.
    line_list = []
    for key, row in line_rows.items():
        row["cf_pct"] = _pct(row["cf"], row["cf"] + row["ca"])
        row["matchup_count"] = 0
        row["relevant_matchup_count"] = 0
        row["event_only"] = row["total_s"] <= 0 and (row["gf"] + row["ga"] > 0 or row["cf"] + row["ca"] > 0)
        line_list.append(row)

    line_total_lookup = {tuple(sorted(row["ebb_player_ids"])): int(row.get("total_s") or 0) for row in line_list}
    all_matchups = []
    for key, row in matchup_rows.items():
        ebb_key = tuple(sorted(row["ebb_player_ids"]))
        line_total = line_total_lookup.get(ebb_key, 0)
        row["ebb_line_total_s"] = line_total
        row["matchup_share_pct"] = _pct(row["total_s"], line_total)
        row["cf_pct"] = _pct(row["cf"], row["cf"] + row["ca"])
        row["event_only"] = row["total_s"] <= 0 and (row["gf"] + row["ga"] > 0 or row["cf"] + row["ca"] > 0)
        row["relevant"] = bool(
            row["total_s"] >= relevant_min_toi_s
            or row["appearances"] >= 2
            or row["gf"] + row["ga"] > 0
            or row["cf"] + row["ca"] >= 3
        )
        all_matchups.append(row)

    # Matchup counters per EBB line.
    for row in line_list:
        key = tuple(sorted(row["ebb_player_ids"]))
        matches = [m for m in all_matchups if tuple(sorted(m["ebb_player_ids"])) == key]
        row["matchup_count"] = len(matches)
        row["relevant_matchup_count"] = sum(bool(m["relevant"]) for m in matches)

    line_list.sort(key=lambda row: (row["total_s"], row["cf"] + row["ca"], row["gf"] + row["ga"]), reverse=True)
    line_order = {tuple(sorted(row["ebb_player_ids"])): idx for idx, row in enumerate(line_list)}
    all_matchups.sort(
        key=lambda row: (
            line_order.get(tuple(sorted(row["ebb_player_ids"])), 999),
            -int(row.get("total_s") or 0),
            -(int(row.get("gf") or 0) + int(row.get("ga") or 0)),
        )
    )
    relevant_matchups = [row for row in all_matchups if row["relevant"]]

    stable_matchup_toi_s = sum(int(row.get("total_s") or 0) for row in all_matchups)
    stable_line_toi_s = sum(int(row.get("total_s") or 0) for row in line_list)
    coverage = {
        "team_5v5_shift_s": team_5v5_shift_s,
        "stable_line_toi_s": stable_line_toi_s,
        "stable_line_toi_pct": _pct(stable_line_toi_s, team_5v5_shift_s),
        "stable_matchup_toi_s": stable_matchup_toi_s,
        "stable_matchup_toi_pct": _pct(stable_matchup_toi_s, team_5v5_shift_s),
        "corsi_total": total_corsi_5v5,
        "corsi_assigned": assigned_corsi,
        "corsi_coverage_pct": _pct(assigned_corsi, total_corsi_5v5),
        "goals_total": total_goal_events_5v5,
        "goals_assigned": assigned_goals,
        "goal_coverage_pct": _pct(assigned_goals, total_goal_events_5v5),
        "goal_shot_context_mismatches": goal_shot_context_mismatches,
    }

    return {
        "line_performance": line_list,
        "all_matchups": all_matchups,
        "relevant_matchups": relevant_matchups,
        "coverage": coverage,
        "unresolved_goals": unresolved_goals,
    }

def primary_forward_matchups(rows: Iterable[dict[str, Any]], *, min_ebb_total_s: int = 60) -> list[dict[str, Any]]:
    by_line: dict[tuple[int, ...], list[dict[str, Any]]] = defaultdict(list)
    totals = defaultdict(int)
    for row in rows:
        key = tuple(sorted(int(x) for x in row["ebb_player_ids"]))
        by_line[key].append(row)
        totals[key] += int(row.get("total_s") or 0)
    result = []
    for key, items in by_line.items():
        if totals[key] < min_ebb_total_s:
            continue
        result.append(max(items, key=lambda row: (row.get("total_s") or 0, row.get("appearances") or 0)))
    return sorted(result, key=lambda row: totals[tuple(sorted(int(x) for x in row["ebb_player_ids"]))], reverse=True)
