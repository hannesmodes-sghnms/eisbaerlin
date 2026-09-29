from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from .lineups import analyze_5v5_lineups

FOCUS_TEAM_ID = 3
FOCUS_TEAM_ABBR = "EBB"
FOCUS_TEAM_NAME = "Eisbären Berlin"


def _row_dict(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    return {desc[0]: value for desc, value in zip(cursor.description, row)}


def _one(con: Any, sql: str, params: list[Any]) -> dict[str, Any] | None:
    cur = con.execute(sql, params)
    row = cur.fetchone()
    return _row_dict(cur, row) if row else None


def _all(con: Any, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    return [_row_dict(cur, row) for row in cur.fetchall()]


def _fmt_time(seconds: int | None) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _metric(label: str, key: str, ebb: dict[str, Any], opp: dict[str, Any], *, kind: str = "number") -> dict[str, Any]:
    return {"label": label, "key": key, "kind": kind, "ebb": ebb.get(key), "opponent": opp.get(key)}


def _build_facts(
    match: dict[str, Any],
    ebb: dict[str, Any],
    opp: dict[str, Any],
    players: list[dict[str, Any]],
    lineups: dict[str, Any],
) -> list[str]:
    facts: list[str] = []
    if ebb.get("corsi_for") is not None:
        facts.append(
            f"Corsi: EBB {ebb['corsi_for']}:{ebb['corsi_against']}; bei 5v5 {ebb['corsi_5v5_for']}:{ebb['corsi_5v5_against']}."
        )
    facts.append(
        f"Slot Attempts: EBB {ebb.get('slot_attempts_for', 0)}:{ebb.get('slot_attempts_against', 0)}; bei 5v5 {ebb.get('slot_attempts_5v5_for', 0)}:{ebb.get('slot_attempts_5v5_against', 0)}."
    )
    facts.append(
        f"Zeit in Führung: {_fmt_time(ebb.get('time_leading_s'))}; ausgeglichen {_fmt_time(ebb.get('time_tied_s'))}; im Rückstand {_fmt_time(ebb.get('time_trailing_s'))}."
    )

    if players:
        top_toi = max(players, key=lambda row: row["toi_s"])
        top_pp = max(players, key=lambda row: row["pp_s"])
        top_pk = max(players, key=lambda row: row["pk_s"])
        facts.append(f"Meiste Eiszeit EBB: {top_toi['name']} mit {_fmt_time(top_toi['toi_s'])}.")
        if top_pp["pp_s"] > 0:
            facts.append(f"Meiste PP-Eiszeit: {top_pp['name']} ({_fmt_time(top_pp['pp_s'])}).")
        if top_pk["pk_s"] > 0:
            facts.append(f"Meiste PK-Eiszeit: {top_pk['name']} ({_fmt_time(top_pk['pk_s'])}).")

    rotation = lineups.get("rotation", {})
    pre = rotation.get("top9_forward_share_pre_p3_pct")
    p3 = rotation.get("top9_forward_share_p3_pct")
    active = rotation.get("active_forwards", {})
    if pre is not None and p3 is not None:
        statement = (
            f"5v5-Forward-Nutzung: Top 9 kamen in P1+P2 auf {pre:.1f}% der Forward-TOI, in P3 auf {p3:.1f}%. "
            f"Forwards mit mindestens 30s 5v5-TOI: P1 {active.get('p1', 0)}, P2 {active.get('p2', 0)}, P3 {active.get('p3', 0)}."
        )
        facts.append(statement)
    if rotation.get("shortened_bank_detected"):
        reasons = "; ".join(rotation.get("shortened_bank_reasons") or [])
        facts.append(f"Hinweis auf verkürzte Bank im 3. Drittel ({reasons}).")
    new_units = rotation.get("new_p3_forward_trios") or []
    if new_units:
        labels = ", ".join(f"{u['label']} ({_fmt_time(u['p3_s'])})" for u in new_units[:3])
        facts.append(f"Neue stabile 5v5-Forward-Units in P3: {labels}.")
    new_pairs = rotation.get("new_p3_defense_pairs") or []
    if new_pairs:
        labels = ", ".join(f"{u['label']} ({_fmt_time(u['p3_s'])})" for u in new_pairs[:3])
        facts.append(f"Neue stabile 5v5-Defense-Pairs in P3: {labels}.")
    dropped = rotation.get("dropped_p3_forward_trios") or []
    if dropped:
        labels = ", ".join(u["label"] for u in dropped[:3])
        facts.append(f"In P1/P2 etablierte Forward-Units, die in P3 praktisch verschwanden: {labels}.")
    usage_drops = rotation.get("p3_toi_drops") or []
    if usage_drops:
        labels = ", ".join(
            f"{u['last_name']} ({u['pre_p3_share_pct']:.1f}% → {u['p3_share_pct']:.1f}%)"
            for u in usage_drops[:4]
        )
        facts.append(f"Deutlich geringerer 5v5-Nutzungsanteil in P3 gegenüber P1+P2: {labels}.")
    usage_increases = rotation.get("p3_toi_increases") or []
    if usage_increases:
        labels = ", ".join(
            f"{u['last_name']} ({u['pre_p3_share_pct']:.1f}% → {u['p3_share_pct']:.1f}%)"
            for u in usage_increases[:4]
        )
        facts.append(f"Deutlich höherer 5v5-Nutzungsanteil in P3 gegenüber P1+P2: {labels}.")

    top_trios = lineups.get("forward_trios") or []
    if top_trios:
        top = top_trios[0]
        facts.append(f"Häufigste stabile 5v5-Forward-Unit: {top['label']} mit {_fmt_time(top['total_s'])} gemeinsamer Eiszeit.")
    top_pairs = lineups.get("defense_pairs") or []
    if top_pairs:
        top = top_pairs[0]
        facts.append(f"Häufigstes 5v5-Verteidigerpaar: {top['label']} mit {_fmt_time(top['total_s'])}.")
    return facts


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
    return analyze_5v5_lineups(
        shifts,
        players,
        focus_team_id=FOCUS_TEAM_ID,
        opponent_team_id=opponent_team_id,
    )


def build_game_payload(con: Any, match_id: int) -> dict[str, Any]:
    match = _one(con, "SELECT * FROM matches WHERE match_id=?", [match_id])
    if not match:
        raise ValueError(f"Unknown match_id {match_id}")
    if FOCUS_TEAM_ID not in {match["home_team_id"], match["away_team_id"]}:
        raise ValueError(f"Match {match_id} is not an EBB game")

    opponent_team_id = match["away_team_id"] if match["home_team_id"] == FOCUS_TEAM_ID else match["home_team_id"]
    opponent_name = match["away_team_name"] if match["home_team_id"] == FOCUS_TEAM_ID else match["home_team_name"]
    ebb = _one(con, "SELECT * FROM team_game_stats WHERE match_id=? AND team_id=?", [match_id, FOCUS_TEAM_ID]) or {}
    opp = _one(con, "SELECT * FROM team_game_stats WHERE match_id=? AND team_id=?", [match_id, opponent_team_id]) or {}

    lineups = _lineup_report(con, match_id, opponent_team_id)
    usage_5v5 = {row["player_id"]: row for row in lineups.get("player_5v5_usage", [])}
    player_rows = _all(
        con,
        """
        SELECT player_id, player_name, jersey, position, goals, assists, points,
               time_on_ice_s, time_on_ice_pp_s, time_on_ice_sh_s, shifts
        FROM player_game_stats
        WHERE match_id=? AND team_id=?
        ORDER BY time_on_ice_s DESC, jersey
        """,
        [match_id, FOCUS_TEAM_ID],
    )
    players = []
    for row in player_rows:
        total = int(row.get("time_on_ice_s") or 0)
        pp = int(row.get("time_on_ice_pp_s") or 0)
        pk = int(row.get("time_on_ice_sh_s") or 0)
        five = usage_5v5.get(row["player_id"], {})
        players.append(
            {
                "player_id": row["player_id"],
                "name": row["player_name"],
                "jersey": row["jersey"],
                "position": row["position"],
                "goals": row["goals"],
                "assists": row["assists"],
                "points": row["points"],
                "toi_s": total,
                "eq_s": max(0, total - pp - pk),
                "pp_s": pp,
                "pk_s": pk,
                "shifts": int(row.get("shifts") or 0),
                "avg_shift_s": round(total / row["shifts"], 1) if row.get("shifts") else None,
                "five_v_five_p1_s": int(five.get("p1_s") or 0),
                "five_v_five_p2_s": int(five.get("p2_s") or 0),
                "five_v_five_p3_s": int(five.get("p3_s") or 0),
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

    zone_rows = _all(
        con,
        """
        SELECT team_id, coalesce(shot_zone, 'UNKNOWN') AS shot_zone, count(*) AS attempts,
               sum(CASE WHEN result IN ('on_goal','goal') THEN 1 ELSE 0 END) AS sog
        FROM shots WHERE match_id=? GROUP BY team_id, shot_zone
        """,
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

    shots = _all(
        con,
        """
        SELECT s.shot_id, s.game_time_s, s.team_id, s.player_id, s.result,
               s.shot_x_m AS x_m, s.shot_y_m AS y_m, s.shot_distance_m AS distance_m,
               s.shot_zone, c.manpower
        FROM shots s JOIN shot_context c USING(match_id, shot_id)
        WHERE s.match_id=? ORDER BY s.game_time_s, s.shot_id
        """,
        [match_id],
    )

    name_map = {row["player_id"]: row["full_name"] for row in _all(con, "SELECT player_id, full_name FROM players WHERE match_id=?", [match_id])}
    event_rows = _all(
        con,
        """
        SELECT game_time_s, event_type, team_id, balance, scorer_player_id, raw_json
        FROM events WHERE match_id=? AND event_type IN ('goal','penalty')
        ORDER BY game_time_s, sequence
        """,
        [match_id],
    )
    timeline = []
    for event in event_rows:
        raw = event.get("raw_json")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            payload = {}
        data = payload.get("data") or {}
        timeline.append(
            {
                "time_s": event["game_time_s"],
                "type": event["event_type"],
                "team_id": event["team_id"],
                "balance": event["balance"],
                "scorer": name_map.get(event.get("scorer_player_id")),
                "score": data.get("currentScore"),
                "penalty": data.get("codename"),
                "duration_s": data.get("duration"),
            }
        )

    facts = _build_facts(match, ebb, opp, players, lineups)
    return {
        "match": {
            "match_id": match_id,
            "date": str(match.get("match_date") or ""),
            "home_team_id": match["home_team_id"],
            "home_team_name": match["home_team_name"],
            "away_team_id": match["away_team_id"],
            "away_team_name": match["away_team_name"],
            "home_score": match["home_score"],
            "away_score": match["away_score"],
            "opponent_team_id": opponent_team_id,
            "opponent_name": opponent_name,
            "ebb_home": match["home_team_id"] == FOCUS_TEAM_ID,
        },
        "focus_team": {"team_id": FOCUS_TEAM_ID, "abbr": FOCUS_TEAM_ABBR, "name": FOCUS_TEAM_NAME},
        "opponent": {"team_id": opponent_team_id, "name": opponent_name, "abbr": opp.get("team_shortcut")},
        "metrics": metrics,
        "facts": facts,
        "players": players,
        "lineups": lineups,
        "shot_zones": shot_zones,
        "shots": shots,
        "timeline": timeline,
    }



def extract_upcoming_games(
    discovery_payload: dict[str, Any],
    *,
    focus_team_id: int = FOCUS_TEAM_ID,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return the next scheduled games for the focus team from season discovery data."""
    games = []
    for match in discovery_payload.get("matches") or []:
        if match.get("status") != "BEFORE_MATCH":
            continue
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        if focus_team_id not in {home_id, away_id}:
            continue
        start_date = str(match.get("start_date") or "")
        opponent_name = match.get("away_team_name") if home_id == focus_team_id else match.get("home_team_name")
        games.append(
            {
                "match_id": match.get("match_id"),
                "start_date": start_date,
                "home_team_id": home_id,
                "home_team_name": match.get("home_team_name"),
                "away_team_id": away_id,
                "away_team_name": match.get("away_team_name"),
                "ebb_home": home_id == focus_team_id,
                "opponent_name": opponent_name,
            }
        )
    games.sort(key=lambda row: (row["start_date"], row.get("match_id") or 0))
    return games[: max(0, int(limit))]


def load_upcoming_games(
    discovery_path: Path,
    *,
    focus_team_id: int = FOCUS_TEAM_ID,
    limit: int = 3,
) -> list[dict[str, Any]]:
    if not discovery_path.exists():
        return []
    payload = json.loads(discovery_path.read_text(encoding="utf-8"))
    return extract_upcoming_games(payload, focus_team_id=focus_team_id, limit=limit)

def generate_dashboard_data(
    *,
    db_path: Path = Path("data/del_2026_27.duckdb"),
    discovery_path: Path = Path("data/discovery/season_2026_27_type_1.json"),
    output_dir: Path = Path("site/data"),
    upcoming_limit: int = 3,
) -> tuple[Path, list[Path]]:
    # Import lazily so pure lineup/dashboard helper tests do not require DuckDB.
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
            WHERE (home_team_id=? OR away_team_id=?)
              AND home_score IS NOT NULL AND away_score IS NOT NULL
            ORDER BY match_date DESC, match_id DESC
            """,
            [FOCUS_TEAM_ID, FOCUS_TEAM_ID],
        )
        summaries = []
        paths = []
        for match in matches:
            payload = build_game_payload(con, int(match["match_id"]))
            path = games_dir / f"{match['match_id']}.json"
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
            paths.append(path)
            date = str(match.get("match_date") or "")
            score = f"{match['home_score']}:{match['away_score']}"
            summaries.append(
                {
                    "match_id": match["match_id"],
                    "date": date,
                    "home_team_name": match["home_team_name"],
                    "away_team_name": match["away_team_name"],
                    "home_score": match["home_score"],
                    "away_score": match["away_score"],
                    "ebb_home": match["home_team_id"] == FOCUS_TEAM_ID,
                    "opponent_name": match["away_team_name"] if match["home_team_id"] == FOCUS_TEAM_ID else match["home_team_name"],
                    "label": f"{date} · {match['home_team_name']} {score} {match['away_team_name']}",
                    "data_path": f"data/games/{match['match_id']}.json",
                }
            )
        index_payload = {
            "focus_team": {"team_id": FOCUS_TEAM_ID, "abbr": FOCUS_TEAM_ABBR, "name": FOCUS_TEAM_NAME},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "completed_games": summaries,
            "upcoming_games": load_upcoming_games(discovery_path, limit=upcoming_limit),
        }
        index_path = output_dir / "games.json"
        index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        return index_path, paths
    finally:
        con.close()

