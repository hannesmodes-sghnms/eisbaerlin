from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .advanced import (
    goalie_watch,
    forward_matchup_report,
    player_impact_5v5_from_shots,
    primary_forward_matchups,
    score_state_corsi_5v5,
    scoring_summary_from_events,
    season_top_scorers,
    zone_starts_5v5,
)
from .lineups import analyze_5v5_lineups
from .del_insight import load_game_insight, load_latest_snapshot, team_season_summary

FOCUS_TEAM_ID = 3
FOCUS_TEAM_ABBR = "EBB"
FOCUS_TEAM_NAME = "Eisbären Berlin"


def _row_dict(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    return {desc[0]: value for desc, value in zip(cursor.description, row)}


def _one(con: Any, sql: str, params: list[Any] | None = None) -> dict[str, Any] | None:
    cur = con.execute(sql, params or [])
    row = cur.fetchone()
    return _row_dict(cur, row) if row else None


def _all(con: Any, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    return [_row_dict(cur, row) for row in cur.fetchall()]


def _fmt_time(seconds: int | float | None) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _metric(label: str, key: str, ebb: dict[str, Any], opp: dict[str, Any], *, kind: str = "number") -> dict[str, Any]:
    return {"label": label, "key": key, "kind": kind, "ebb": ebb.get(key), "opponent": opp.get(key)}


def _period_for_time(seconds: int | None) -> str:
    value = int(seconds or 0)
    if value < 1200:
        return "P1"
    if value < 2400:
        return "P2"
    if value < 3600:
        return "P3"
    return "OT"


def _team_abbr(con: Any, team_id: int, fallback: str | None = None) -> str:
    row = _one(con, "SELECT shortcut FROM teams WHERE team_id=?", [team_id])
    if row and row.get("shortcut"):
        return str(row["shortcut"])
    row = _one(
        con,
        "SELECT team_shortcut AS shortcut FROM team_game_stats WHERE team_id=? ORDER BY match_date DESC LIMIT 1",
        [team_id],
    )
    return str((row or {}).get("shortcut") or fallback or team_id)


def _team_record(con: Any, team_id: int) -> dict[str, Any]:
    rows = _all(con, "SELECT goals_for, goals_against FROM team_game_stats WHERE team_id=?", [team_id])
    wins = sum(1 for row in rows if (row.get("goals_for") or 0) > (row.get("goals_against") or 0))
    losses = sum(1 for row in rows if (row.get("goals_for") or 0) < (row.get("goals_against") or 0))
    ties = len(rows) - wins - losses
    return {"games": len(rows), "wins": wins, "losses": losses, "ties": ties, "label": f"{wins}-{losses}" + (f"-{ties}" if ties else "")}


def _recent_games(con: Any, team_id: int, *, limit: int = 5) -> list[dict[str, Any]]:
    rows = _all(
        con,
        """
        SELECT match_id, match_date, opponent_team_id, opponent_shortcut, opponent_name,
               home_road, goals_for, goals_against, corsi_5v5_pct, slot_attempts_for, pdo_5v5
        FROM team_game_stats
        WHERE team_id=?
        ORDER BY match_date DESC, match_id DESC
        LIMIT ?
        """,
        [team_id, limit],
    )
    for row in rows:
        gf, ga = int(row.get("goals_for") or 0), int(row.get("goals_against") or 0)
        row["result"] = f"{gf}:{ga}"
        row["outcome"] = "W" if gf > ga else "L" if gf < ga else "T"
    return rows


def _head_to_head(con: Any, opponent_team_id: int, *, limit: int = 5) -> list[dict[str, Any]]:
    rows = _all(
        con,
        """
        SELECT e.match_id, e.match_date, m.home_team_id, m.home_team_name, m.away_team_id, m.away_team_name,
               m.home_score, m.away_score, e.corsi_5v5_for AS ebb_corsi_5v5,
               o.corsi_5v5_for AS opponent_corsi_5v5, e.slot_attempts_for AS ebb_slot,
               o.slot_attempts_for AS opponent_slot
        FROM team_game_stats e
        JOIN team_game_stats o ON o.match_id=e.match_id AND o.team_id=?
        JOIN matches m ON m.match_id=e.match_id
        WHERE e.team_id=?
        ORDER BY e.match_date DESC, e.match_id DESC
        LIMIT ?
        """,
        [opponent_team_id, FOCUS_TEAM_ID, limit],
    )
    for row in rows:
        ebb_home = int(row["home_team_id"]) == FOCUS_TEAM_ID
        own = row["home_score"] if ebb_home else row["away_score"]
        opp = row["away_score"] if ebb_home else row["home_score"]
        row["ebb_result"] = f"{own}:{opp}"
    return rows


def _season_key_stats(con: Any, team_id: int) -> dict[str, Any]:
    stats = _one(con, "SELECT * FROM team_season_stats WHERE team_id=?", [team_id]) or {}
    games = int(stats.get("games_played") or 0)

    def per_game(key: str) -> float | None:
        return round(float(stats.get(key) or 0) / games, 2) if games else None

    return {
        "games_played": games,
        "record": _team_record(con, team_id)["label"],
        "corsi_per_game": per_game("corsi_for"),
        "corsi_5v5_pct": stats.get("corsi_5v5_pct"),
        "sog_per_game": per_game("shots_on_goal_for"),
        "slot_per_game": per_game("slot_attempts_for"),
        "goals_per_game": per_game("goals_for"),
        "goals_against_per_game": per_game("goals_against"),
        "pdo_5v5": stats.get("pdo_5v5"),
        "time_leading_per_game_s": round(float(stats.get("time_leading_s") or 0) / games) if games else None,
    }


def _key_stat_rows(ebb: dict[str, Any], opp: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [
        ("Bilanz", "record", "text"),
        ("Corsi 5v5 %", "corsi_5v5_pct", "percent"),
        ("Corsi / Spiel", "corsi_per_game", "decimal"),
        ("SOG / Spiel", "sog_per_game", "decimal"),
        ("Slot Attempts / Spiel", "slot_per_game", "decimal"),
        ("Tore / Spiel", "goals_per_game", "decimal"),
        ("Gegentore / Spiel", "goals_against_per_game", "decimal"),
        ("PDO 5v5", "pdo_5v5", "decimal"),
        ("Zeit in Führung / Spiel", "time_leading_per_game_s", "time"),
    ]
    return [{"label": label, "key": key, "kind": kind, "ebb": ebb.get(key), "opponent": opp.get(key)} for label, key, kind in specs]



def _insight_preview_rows(ebb: dict[str, Any] | None, opp: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not ebb and not opp:
        return []

    def pair(row: dict[str, Any] | None, a: str, b: str) -> str | None:
        if not row:
            return None
        av, bv = row.get(a), row.get(b)
        if av is None and bv is None:
            return None
        return f"{int(av or 0)} / {int(bv or 0)}"

    specs = [
        ("Pässe", pair(ebb, "passes_completed", "passes_attempted"), pair(opp, "passes_completed", "passes_attempted"), "text"),
        ("Passquote", (ebb or {}).get("pass_pct"), (opp or {}).get("pass_pct"), "percent"),
        ("Puck Contests", pair(ebb, "pcw_won", "pcw_total"), pair(opp, "pcw_won", "pcw_total"), "text"),
        ("PCW%", (ebb or {}).get("pcw_pct"), (opp or {}).get("pcw_pct"), "percent"),
        ("xG Summe", (ebb or {}).get("xg_sum"), (opp or {}).get("xg_sum"), "decimal2"),
        ("xG / Spiel", (ebb or {}).get("xg_per_game"), (opp or {}).get("xg_per_game"), "decimal2"),
    ]
    return [{"label": label, "ebb": a, "opponent": b, "kind": kind} for label, a, b, kind in specs]


def enrich_upcoming_games(con: Any, games: list[dict[str, Any]], *, raw_dir: Path = Path("data/raw"), insight_dir: Path = Path("data/del_insight")) -> list[dict[str, Any]]:
    ebb_stats = _season_key_stats(con, FOCUS_TEAM_ID)
    ebb_recent = _recent_games(con, FOCUS_TEAM_ID, limit=5)
    insight_snapshot = load_latest_snapshot(insight_dir)
    ebb_insight = team_season_summary(insight_snapshot, FOCUS_TEAM_ID, games_played=int(ebb_stats.get("games_played") or 0))
    result = []
    for game in games:
        opponent_team_id = int(game["away_team_id"] if game["ebb_home"] else game["home_team_id"])
        opponent_abbr = _team_abbr(con, opponent_team_id, game.get("opponent_name"))
        opponent_stats = _season_key_stats(con, opponent_team_id)
        opponent_insight = team_season_summary(insight_snapshot, opponent_team_id, games_played=int(opponent_stats.get("games_played") or 0))
        result.append(
            {
                **game,
                "opponent_team_id": opponent_team_id,
                "opponent_abbr": opponent_abbr,
                "key_stats": _key_stat_rows(ebb_stats, opponent_stats),
                "del_insight": {
                    "available": bool(ebb_insight or opponent_insight),
                    "snapshot_at": (insight_snapshot or {}).get("generated_at_utc"),
                    "rows": _insight_preview_rows(ebb_insight, opponent_insight),
                },
                "ebb_recent": ebb_recent,
                "opponent_recent": _recent_games(con, opponent_team_id, limit=5),
                "head_to_head": _head_to_head(con, opponent_team_id, limit=5),
                "opponent_top_scorers": season_top_scorers(con, opponent_team_id, limit=5, recent_games=5),
                "opponent_goalies": goalie_watch(con, raw_dir, opponent_team_id, limit=2),
            }
        )
    return result


def _lineup_report(con: Any, match_id: int, opponent_team_id: int) -> dict[str, Any]:
    shifts = _all(
        con,
        "SELECT team_id, player_id, start_time_s, end_time_s FROM shifts WHERE match_id=? ORDER BY start_time_s, shift_id",
        [match_id],
    )
    players = _all(
        con,
        "SELECT team_id, player_id, full_name, last_name, jersey, position FROM players WHERE match_id=?",
        [match_id],
    )
    return analyze_5v5_lineups(shifts, players, focus_team_id=FOCUS_TEAM_ID, opponent_team_id=opponent_team_id)


def _build_facts(
    ebb: dict[str, Any],
    players: list[dict[str, Any]],
    lineups: dict[str, Any],
    advanced: dict[str, Any],
) -> list[str]:
    facts: list[str] = []
    if ebb.get("corsi_for") is not None:
        facts.append(f"Corsi: EBB {ebb['corsi_for']}:{ebb['corsi_against']}; bei 5v5 {ebb['corsi_5v5_for']}:{ebb['corsi_5v5_against']}.")
    facts.append(
        f"Slot Attempts: EBB {ebb.get('slot_attempts_for', 0)}:{ebb.get('slot_attempts_against', 0)}; "
        f"bei 5v5 {ebb.get('slot_attempts_5v5_for', 0)}:{ebb.get('slot_attempts_5v5_against', 0)}."
    )
    facts.append(
        f"Zeit in Führung: {_fmt_time(ebb.get('time_leading_s'))}; ausgeglichen {_fmt_time(ebb.get('time_tied_s'))}; "
        f"im Rückstand {_fmt_time(ebb.get('time_trailing_s'))}."
    )

    skaters = [row for row in players if row.get("position") != "GK"]
    if skaters:
        top_toi = max(skaters, key=lambda row: row["toi_s"])
        facts.append(f"Meiste Eiszeit EBB: {top_toi['name']} mit {_fmt_time(top_toi['toi_s'])}.")

    tied = next((r for r in advanced.get("score_state_corsi_5v5", []) if r["state"] == "tied"), None)
    if tied and tied["cf"] + tied["ca"] >= 10:
        pct = "–" if tied["cf_pct"] is None else f"{tied['cf_pct']:.1f}%"
        facts.append(f"5v5 bei Gleichstand: Corsi {tied['cf']}:{tied['ca']} ({pct} EBB).")

    impact = [r for r in advanced.get("player_impact_5v5", []) if r["cf"] + r["ca"] >= 10 and r.get("relative_cf_pct") is not None]
    if impact:
        top = max(impact, key=lambda r: r["relative_cf_pct"])
        facts.append(
            f"5v5 On-Ice: {top['last_name']} {top['cf']}:{top['ca']} Corsi ({top['cf_pct']:.1f}%), "
            f"{top['relative_cf_pct']:+.1f} Prozentpunkte gegenüber EBB ohne ihn auf dem Eis."
        )

    changes = []
    for change in lineups.get("lineup_changes") or []:
        period = change["period"]
        unit_name = "Sturmreihe" if change["kind"] == "forward" else "Verteidigerpaar"
        if change["change_type"] in {"introduced", "returned"}:
            verb = "neu stabil eingesetzt" if change["change_type"] == "introduced" else "wieder stabil eingesetzt"
            changes.append(f"Reihenänderung P{period}: {unit_name} {change['label']} wurde {verb} ({_fmt_time(change['current_s'])}).")
        elif change["change_type"] == "dropped":
            changes.append(
                f"Reihenänderung P{period}: {unit_name} {change['label']} fiel nahezu aus der 5v5-Rotation "
                f"(P{period-1} {_fmt_time(change['previous_s'])} → P{period} {_fmt_time(change['current_s'])})."
            )
    facts.extend(changes[:5])

    rotation = lineups.get("rotation", {})
    if rotation.get("shortened_bank_detected"):
        reasons = "; ".join(rotation.get("shortened_bank_reasons") or [])
        facts.append(f"Hinweis auf verkürzte Bank im 3. Drittel ({reasons}).")

    matchups = advanced.get("relevant_forward_matchups") or advanced.get("primary_forward_matchups") or []
    if matchups:
        top = max(matchups, key=lambda row: (int(row.get("total_s") or 0), int(row.get("appearances") or 0)))
        pct = "–" if top.get("cf_pct") is None else f"{top['cf_pct']:.1f}%"
        facts.append(
            f"Häufigstes Line-Matching: {top['ebb_label']} gegen {top['opponent_label']} mit {_fmt_time(top['total_s'])}; "
            f"Corsi {top['cf']}:{top['ca']} ({pct}), Slot {top['slot_for']}:{top['slot_against']}, Tore {top['gf']}:{top['ga']}."
        )

    zone_units = [r for r in (advanced.get("zone_starts") or {}).get("forward_units", []) if r["non_neutral"] >= 4 and r.get("oz_share_pct") is not None]
    if zone_units:
        most_def = min(zone_units, key=lambda r: r["oz_share_pct"])
        if most_def["oz_share_pct"] <= 30:
            facts.append(
                f"Deployment: {most_def['label']} startete bei {most_def['non_neutral']} nicht-neutralen 5v5-Starts "
                f"{most_def['dz']}× in der eigenen und {most_def['oz']}× in der offensiven Zone."
            )

    coverage = lineups.get("coverage") or {}
    if coverage.get("forward_stable_pct") is not None and coverage.get("defense_stable_pct") is not None:
        facts.append(
            f"Lineup-Datencheck: stabile Units decken {coverage['forward_stable_pct']:.1f}% der rekonstruierten 5v5-Forward-TOI "
            f"und {coverage['defense_stable_pct']:.1f}% der 5v5-Defense-TOI ab."
        )
    return facts


def build_game_payload(con: Any, match_id: int, *, insight_dir: Path = Path("data/del_insight")) -> dict[str, Any]:
    match = _one(con, "SELECT * FROM matches WHERE match_id=?", [match_id])
    if not match:
        raise ValueError(f"Unknown match_id {match_id}")
    if FOCUS_TEAM_ID not in {match["home_team_id"], match["away_team_id"]}:
        raise ValueError(f"Match {match_id} is not an EBB game")

    opponent_team_id = int(match["away_team_id"] if match["home_team_id"] == FOCUS_TEAM_ID else match["home_team_id"])
    opponent_name = match["away_team_name"] if match["home_team_id"] == FOCUS_TEAM_ID else match["home_team_name"]
    ebb = _one(con, "SELECT * FROM team_game_stats WHERE match_id=? AND team_id=?", [match_id, FOCUS_TEAM_ID]) or {}
    opp = _one(con, "SELECT * FROM team_game_stats WHERE match_id=? AND team_id=?", [match_id, opponent_team_id]) or {}
    opponent_abbr = str(opp.get("team_shortcut") or _team_abbr(con, opponent_team_id, opponent_name))

    lineups = _lineup_report(con, match_id, opponent_team_id)
    usage_5v5 = {row["player_id"]: row for row in lineups.get("player_5v5_usage", [])}

    player_rows = _all(
        con,
        """
        SELECT player_id, player_name, jersey, position, goals, assists, points,
               time_on_ice_s, time_on_ice_pp_s, time_on_ice_sh_s, shifts
        FROM player_game_stats WHERE match_id=? AND team_id=?
        ORDER BY time_on_ice_s DESC, jersey
        """,
        [match_id, FOCUS_TEAM_ID],
    )
    players = []
    for row in player_rows:
        total, pp, pk = int(row.get("time_on_ice_s") or 0), int(row.get("time_on_ice_pp_s") or 0), int(row.get("time_on_ice_sh_s") or 0)
        five = usage_5v5.get(row["player_id"], {})
        players.append(
            {
                "player_id": row["player_id"], "name": row["player_name"], "jersey": row["jersey"], "position": row["position"],
                "usage_role": five.get("usage_role") or row["position"],
                "role_fo_s": int(five.get("role_fo_s") or 0), "role_de_s": int(five.get("role_de_s") or 0),
                "goals": row["goals"], "assists": row["assists"], "points": row["points"], "toi_s": total,
                "eq_s": max(0, total - pp - pk), "pp_s": pp, "pk_s": pk, "shifts": int(row.get("shifts") or 0),
                "avg_shift_s": round(total / row["shifts"], 1) if row.get("shifts") else None,
                "five_v_five_s": int(five.get("total_s") or 0),
                "five_v_five_p1_s": int(five.get("p1_s") or 0), "five_v_five_p2_s": int(five.get("p2_s") or 0), "five_v_five_p3_s": int(five.get("p3_s") or 0),
                "stable_unit_s": int(five.get("stable_unit_s") or 0), "stable_unit_coverage_pct": five.get("stable_unit_coverage_pct"),
            }
        )

    metrics = [
        _metric("Corsi", "corsi_for", ebb, {"corsi_for": ebb.get("corsi_against")}),
        _metric("Corsi 5v5", "corsi_5v5_for", ebb, {"corsi_5v5_for": ebb.get("corsi_5v5_against")}),
        _metric("Corsi-Anteil 5v5", "corsi_5v5_pct", ebb, {"corsi_5v5_pct": opp.get("corsi_5v5_pct")}, kind="percent"),
        _metric("Shots on Goal", "shots_on_goal_for", ebb, {"shots_on_goal_for": ebb.get("shots_on_goal_against")}),
        _metric("Slot Attempts", "slot_attempts_for", ebb, {"slot_attempts_for": ebb.get("slot_attempts_against")}),
        _metric("Slot Attempts 5v5", "slot_attempts_5v5_for", ebb, {"slot_attempts_5v5_for": ebb.get("slot_attempts_5v5_against")}),
        _metric("Tore", "goals_for", ebb, {"goals_for": ebb.get("goals_against")}),
        _metric("Tore EQ", "goals_eq_for", ebb, {"goals_eq_for": ebb.get("goals_eq_against")}),
        _metric("PPG", "pp_goals_for", ebb, {"pp_goals_for": ebb.get("pp_goals_against")}),
        _metric("Zeit in Führung", "time_leading_s", ebb, {"time_leading_s": opp.get("time_leading_s")}, kind="time"),
        _metric("Scorende Spieler", "scoring_players", ebb, opp),
        _metric("Verteidigerpunkte", "defenseman_points", ebb, opp),
        _metric("SH% 5v5", "shooting_pct_5v5", ebb, opp, kind="percent"),
        _metric("SV% 5v5", "save_pct_5v5", ebb, opp, kind="percent"),
        _metric("PDO 5v5", "pdo_5v5", ebb, opp, kind="decimal"),
    ]

    shots = _all(
        con,
        """
        SELECT s.shot_id, s.game_time_s, s.team_id, s.player_id, s.result,
               s.shot_x_m AS x_m, s.shot_y_m AS y_m, s.shot_distance_m AS distance_m,
               s.shot_zone, c.manpower, c.on_ice_for_player_ids, c.on_ice_against_player_ids
        FROM shots s JOIN shot_context c USING(match_id, shot_id)
        WHERE s.match_id=? ORDER BY s.game_time_s, s.shot_id
        """,
        [match_id],
    )
    player_info = _all(con, "SELECT team_id, player_id, full_name, last_name, jersey, position FROM players WHERE match_id=?", [match_id])
    name_map = {row["player_id"]: row["full_name"] for row in player_info}
    jersey_map = {row["player_id"]: row.get("jersey") for row in player_info}
    for shot in shots:
        shot["player_name"] = name_map.get(shot.get("player_id"))
        shot["jersey"] = jersey_map.get(shot.get("player_id"))
        shot["period"] = _period_for_time(shot.get("game_time_s"))
        shot["team_abbr"] = FOCUS_TEAM_ABBR if shot.get("team_id") == FOCUS_TEAM_ID else opponent_abbr

    event_rows = _all(
        con,
        """SELECT game_time_s, period_key, event_type, team_id, balance, scorer_player_id, raw_json
           FROM events WHERE match_id=? AND event_type IN ('goal','penalty') ORDER BY game_time_s, sequence""",
        [match_id],
    )
    scoring_summary = scoring_summary_from_events(
        event_rows, focus_team_id=FOCUS_TEAM_ID, opponent_team_id=opponent_team_id,
        focus_abbr=FOCUS_TEAM_ABBR, opponent_abbr=opponent_abbr,
    )
    goal_by_time = {(row["time_s"], row["team_id"]): row for row in scoring_summary}
    timeline = []
    for event in event_rows:
        raw = event.get("raw_json")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            payload = {}
        data = payload.get("data") or {}
        team_id = event.get("team_id")
        team_abbr = FOCUS_TEAM_ABBR if team_id == FOCUS_TEAM_ID else opponent_abbr if team_id == opponent_team_id else "–"
        goal = goal_by_time.get((int(event.get("game_time_s") or 0), team_id)) if event["event_type"] == "goal" else None
        timeline.append(
            {
                "time_s": event["game_time_s"], "period": _period_for_time(event.get("game_time_s")), "type": event["event_type"],
                "team_id": team_id, "team_abbr": team_abbr, "balance": event["balance"],
                "scorer": name_map.get(event.get("scorer_player_id")) or ((goal or {}).get("scorer") or {}).get("name"),
                "assists": (goal or {}).get("assists") or [], "score": data.get("currentScore"), "penalty": data.get("codename"), "duration_s": data.get("duration"),
            }
        )

    shifts = _all(con, "SELECT team_id, player_id, start_time_s, end_time_s FROM shifts WHERE match_id=?", [match_id])
    faceoffs = _all(con, "SELECT game_time_s, position_shortcut FROM faceoffs WHERE match_id=? ORDER BY game_time_s", [match_id])
    impact = player_impact_5v5_from_shots(shots, player_info, focus_team_id=FOCUS_TEAM_ID)
    impact_by_id = {row["player_id"]: row for row in impact}
    for player in players:
        if player["player_id"] in impact_by_id:
            impact_by_id[player["player_id"]]["toi_5v5_s"] = player["five_v_five_s"]

    matchup_report = forward_matchup_report(
        shifts, player_info, shots, event_rows,
        focus_team_id=FOCUS_TEAM_ID, opponent_team_id=opponent_team_id,
    )
    advanced = {
        "player_impact_5v5": impact,
        "score_state_corsi_5v5": score_state_corsi_5v5(
            shots, event_rows, focus_team_id=FOCUS_TEAM_ID, focus_is_home=int(match["home_team_id"]) == FOCUS_TEAM_ID,
        ),
        "zone_starts": zone_starts_5v5(
            shifts, player_info, faceoffs, focus_team_id=FOCUS_TEAM_ID, opponent_team_id=opponent_team_id,
            home_team_id=int(match["home_team_id"]),
        ),
        "forward_matchups": matchup_report["all_matchups"],
        "relevant_forward_matchups": matchup_report["relevant_matchups"],
        "line_performance": matchup_report["line_performance"],
        "matchup_coverage": matchup_report["coverage"],
        "unresolved_matchup_goals": matchup_report["unresolved_goals"],
        "primary_forward_matchups": primary_forward_matchups(matchup_report["all_matchups"]),
    }

    zone_rows = _all(
        con,
        """SELECT team_id, coalesce(shot_zone, 'UNKNOWN') AS shot_zone, count(*) AS attempts,
                  sum(CASE WHEN result IN ('on_goal','goal') THEN 1 ELSE 0 END) AS sog
           FROM shots WHERE match_id=? GROUP BY team_id, shot_zone""",
        [match_id],
    )
    zone_names = ["SLOT", "LEFT", "RIGHT", "BLUE_LINE", "NEUTRAL_ZONE", "BEHIND_GOAL", "UNKNOWN"]
    zone_map = {(row["team_id"], row["shot_zone"]): row for row in zone_rows}
    shot_zones = [
        {
            "zone": zone,
            "ebb_attempts": int((zone_map.get((FOCUS_TEAM_ID, zone)) or {}).get("attempts") or 0),
            "ebb_sog": int((zone_map.get((FOCUS_TEAM_ID, zone)) or {}).get("sog") or 0),
            "opponent_attempts": int((zone_map.get((opponent_team_id, zone)) or {}).get("attempts") or 0),
            "opponent_sog": int((zone_map.get((opponent_team_id, zone)) or {}).get("sog") or 0),
        }
        for zone in zone_names
    ]

    raw_game_insight = load_game_insight(insight_dir, match_id)
    game_insight = None
    if raw_game_insight:
        insight_teams = raw_game_insight.get("teams") or {}
        ebb_insight = insight_teams.get(str(FOCUS_TEAM_ID))
        opponent_insight = insight_teams.get(str(opponent_team_id))
        game_insight = {
            "available": bool(ebb_insight or opponent_insight),
            "method": raw_game_insight.get("method"),
            "ebb": ebb_insight,
            "opponent": opponent_insight,
            "unavailable": raw_game_insight.get("unavailable") or {},
        }

    facts = _build_facts(ebb, players, lineups, advanced)
    if game_insight and game_insight.get("ebb") and game_insight.get("opponent"):
        ebb_i = game_insight["ebb"].get("summary") or {}
        opp_i = game_insight["opponent"].get("summary") or {}
        if ebb_i.get("xg_sum") is not None and opp_i.get("xg_sum") is not None:
            facts.append(
                f"DEL Insight: xG {float(ebb_i['xg_sum']):.2f}:{float(opp_i['xg_sum']):.2f}; "
                f"Passquote {float(ebb_i.get('pass_pct') or 0):.1f}%:{float(opp_i.get('pass_pct') or 0):.1f}%; "
                f"Puck Contests {float(ebb_i.get('pcw_pct') or 0):.1f}%:{float(opp_i.get('pcw_pct') or 0):.1f}%."
            )
    return {
        "match": {
            "match_id": match_id, "date": str(match.get("match_date") or ""),
            "home_team_id": match["home_team_id"], "home_team_name": match["home_team_name"],
            "away_team_id": match["away_team_id"], "away_team_name": match["away_team_name"],
            "home_score": match["home_score"], "away_score": match["away_score"],
            "opponent_team_id": opponent_team_id, "opponent_name": opponent_name, "opponent_abbr": opponent_abbr,
            "ebb_home": int(match["home_team_id"]) == FOCUS_TEAM_ID,
        },
        "focus_team": {"team_id": FOCUS_TEAM_ID, "abbr": FOCUS_TEAM_ABBR, "name": FOCUS_TEAM_NAME},
        "opponent": {"team_id": opponent_team_id, "name": opponent_name, "abbr": opponent_abbr},
        "metrics": metrics, "facts": facts, "players": players, "lineups": lineups,
        "advanced": advanced, "scoring_summary": scoring_summary, "del_insight": game_insight,
        "shot_zones": shot_zones, "shots": shots, "timeline": timeline,
    }


def extract_upcoming_games(
    discovery_payload: dict[str, Any], *, focus_team_id: int = FOCUS_TEAM_ID, limit: int = 3,
) -> list[dict[str, Any]]:
    games = []
    for match in discovery_payload.get("matches") or []:
        if match.get("status") != "BEFORE_MATCH":
            continue
        home_id, away_id = match.get("home_team_id"), match.get("away_team_id")
        if focus_team_id not in {home_id, away_id}:
            continue
        games.append(
            {
                "match_id": match.get("match_id"), "start_date": str(match.get("start_date") or ""),
                "home_team_id": home_id, "home_team_name": match.get("home_team_name"),
                "away_team_id": away_id, "away_team_name": match.get("away_team_name"),
                "ebb_home": home_id == focus_team_id,
                "opponent_name": match.get("away_team_name") if home_id == focus_team_id else match.get("home_team_name"),
            }
        )
    games.sort(key=lambda row: (row["start_date"], row.get("match_id") or 0))
    return games[: max(0, int(limit))]


def load_upcoming_games(discovery_path: Path, *, focus_team_id: int = FOCUS_TEAM_ID, limit: int = 3) -> list[dict[str, Any]]:
    if not discovery_path.exists():
        return []
    return extract_upcoming_games(json.loads(discovery_path.read_text(encoding="utf-8")), focus_team_id=focus_team_id, limit=limit)


def generate_dashboard_data(
    *,
    db_path: Path = Path("data/del_2026_27.duckdb"),
    discovery_path: Path = Path("data/discovery/season_2026_27_type_1.json"),
    raw_dir: Path = Path("data/raw"),
    insight_dir: Path = Path("data/del_insight"),
    output_dir: Path = Path("site/data"),
    upcoming_limit: int = 3,
) -> tuple[Path, list[Path]]:
    import duckdb

    output_dir.mkdir(parents=True, exist_ok=True)
    games_dir = output_dir / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        matches = _all(
            con,
            """
            SELECT match_id, match_date, home_team_id, home_team_name, away_team_id, away_team_name,
                   home_score, away_score, status
            FROM matches
            WHERE (home_team_id=? OR away_team_id=?) AND home_score IS NOT NULL AND away_score IS NOT NULL
            ORDER BY match_date DESC, match_id DESC
            """,
            [FOCUS_TEAM_ID, FOCUS_TEAM_ID],
        )
        summaries, paths = [], []
        for match in matches:
            payload = build_game_payload(con, int(match["match_id"]), insight_dir=insight_dir)
            path = games_dir / f"{match['match_id']}.json"
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
            paths.append(path)
            date = str(match.get("match_date") or "")
            score = f"{match['home_score']}:{match['away_score']}"
            summaries.append(
                {
                    "match_id": match["match_id"], "date": date,
                    "home_team_name": match["home_team_name"], "away_team_name": match["away_team_name"],
                    "home_score": match["home_score"], "away_score": match["away_score"],
                    "ebb_home": match["home_team_id"] == FOCUS_TEAM_ID,
                    "opponent_name": match["away_team_name"] if match["home_team_id"] == FOCUS_TEAM_ID else match["home_team_name"],
                    "label": f"{date} · {match['home_team_name']} {score} {match['away_team_name']}",
                    "data_path": f"data/games/{match['match_id']}.json",
                }
            )

        upcoming_basic = load_upcoming_games(discovery_path, limit=upcoming_limit)
        index_payload = {
            "focus_team": {"team_id": FOCUS_TEAM_ID, "abbr": FOCUS_TEAM_ABBR, "name": FOCUS_TEAM_NAME},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "completed_games": summaries,
            "upcoming_games": enrich_upcoming_games(con, upcoming_basic, raw_dir=raw_dir, insight_dir=insight_dir),
        }
        index_path = output_dir / "games.json"
        index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        return index_path, paths
    finally:
        con.close()
