from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from .transform import (
    SHOT_RESULT_MAP,
    faceoff_zone_for_team,
    flatten_period_events,
    load_json,
    player_team_map,
    previous_faceoff,
    resolve_on_ice_pair,
)

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS matches (
    match_id BIGINT PRIMARY KEY,
    match_date DATE,
    start_datetime TIMESTAMP,
    status VARCHAR,
    home_team_id BIGINT,
    home_team_name VARCHAR,
    away_team_id BIGINT,
    away_team_name VARCHAR,
    stadium VARCHAR,
    viewers BIGINT,
    home_score INTEGER,
    away_score INTEGER,
    overtime BOOLEAN,
    shootout BOOLEAN
);

CREATE TABLE IF NOT EXISTS players (
    match_id BIGINT,
    team_id BIGINT,
    team_side VARCHAR,
    player_id BIGINT,
    match_player_id BIGINT,
    first_name VARCHAR,
    last_name VARCHAR,
    full_name VARCHAR,
    jersey INTEGER,
    position VARCHAR,
    captain BOOLEAN,
    starting_six BOOLEAN,
    roster_slot VARCHAR,
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE IF NOT EXISTS shifts (
    match_id BIGINT,
    shift_id BIGINT,
    team_id BIGINT,
    team_name VARCHAR,
    player_id BIGINT,
    player_name VARCHAR,
    start_time_s INTEGER,
    end_time_s INTEGER,
    duration_s INTEGER,
    start_realtime TIMESTAMP,
    end_realtime TIMESTAMP,
    PRIMARY KEY (match_id, shift_id)
);

CREATE TABLE IF NOT EXISTS shots (
    match_id BIGINT,
    shot_id BIGINT,
    game_time_s INTEGER,
    real_time TIMESTAMP,
    team_id BIGINT,
    player_id BIGINT,
    jersey INTEGER,
    first_name VARCHAR,
    last_name VARCHAR,
    result_id INTEGER,
    result VARCHAR,
    coordinate_x DOUBLE,
    coordinate_y DOUBLE,
    polygon VARCHAR,
    PRIMARY KEY (match_id, shot_id)
);

CREATE TABLE IF NOT EXISTS faceoffs (
    match_id BIGINT,
    faceoff_id BIGINT,
    game_time_s INTEGER,
    real_time TIMESTAMP,
    position VARCHAR,
    position_shortcut VARCHAR,
    winner_player_id BIGINT,
    winner_name VARCHAR,
    winner_team_id BIGINT,
    loser_player_id BIGINT,
    loser_name VARCHAR,
    loser_team_id BIGINT,
    PRIMARY KEY (match_id, faceoff_id)
);

CREATE TABLE IF NOT EXISTS events (
    match_id BIGINT,
    sequence INTEGER,
    period_key VARCHAR,
    game_time_s INTEGER,
    event_type VARCHAR,
    event_id BIGINT,
    team_side VARCHAR,
    team_id BIGINT,
    balance VARCHAR,
    scorer_player_id BIGINT,
    disciplined_player_id BIGINT,
    penalty_code VARCHAR,
    penalty_duration_s INTEGER,
    raw_json JSON,
    PRIMARY KEY (match_id, sequence)
);

CREATE TABLE IF NOT EXISTS shot_on_ice (
    match_id BIGINT,
    shot_id BIGINT,
    team_id BIGINT,
    player_id BIGINT,
    relation VARCHAR,
    selection_method VARCHAR,
    PRIMARY KEY (match_id, shot_id, player_id)
);

CREATE TABLE IF NOT EXISTS shot_context (
    match_id BIGINT,
    shot_id BIGINT,
    game_time_s INTEGER,
    shooting_team_id BIGINT,
    opponent_team_id BIGINT,
    on_ice_for_player_ids BIGINT[],
    on_ice_against_player_ids BIGINT[],
    on_ice_for_count INTEGER,
    on_ice_against_count INTEGER,
    manpower VARCHAR,
    on_ice_method_for VARCHAR,
    on_ice_method_against VARCHAR,
    on_ice_quality VARCHAR,
    previous_faceoff_id BIGINT,
    previous_faceoff_time_s INTEGER,
    seconds_since_faceoff INTEGER,
    previous_faceoff_position VARCHAR,
    previous_faceoff_position_shortcut VARCHAR,
    previous_faceoff_zone_for_shooting_team VARCHAR,
    previous_faceoff_winner_team_id BIGINT,
    previous_faceoff_won_by_shooting_team BOOLEAN,
    dzone_faceoff_to_shot_10s BOOLEAN,
    dzone_faceoff_win_to_shot_10s BOOLEAN,
    PRIMARY KEY (match_id, shot_id)
);
"""


def _schedule_match(discovery_path: Path | None, match_id: int) -> dict[str, Any] | None:
    if not discovery_path or not discovery_path.exists():
        return None
    payload = load_json(discovery_path)
    for match in payload.get("matches", []):
        if int(match.get("match_id", -1)) == match_id:
            return match
    return None


def _event_team_id(team_side: str | None, home_team_id: int, away_team_id: int) -> int | None:
    if team_side == "home":
        return home_team_id
    if team_side == "visitor":
        return away_team_id
    return None


def _on_ice_quality(count_for: int, count_against: int, method_for: str, method_against: str) -> str:
    plausible = 3 <= count_for <= 6 and 3 <= count_against <= 6
    if not plausible:
        return "low_confidence"
    if "boundary_adjusted" in {method_for, method_against}:
        return "boundary_adjusted"
    return "exact"


def build_match_database(
    *,
    match_dir: Path,
    db_path: Path,
    discovery_path: Path | None = None,
) -> dict[str, Any]:
    match_id = int(match_dir.name)
    required = ["game-header.json", "roster.json", "shots.json", "faceoffs.json", "period-events.json"]
    missing = [name for name in required if not (match_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing raw match files: {', '.join(missing)}")
    shift_files = sorted(match_dir.glob("shifts*.json"))
    if not shift_files:
        raise FileNotFoundError(f"No shifts*.json file found below {match_dir}")
    if len(shift_files) > 1:
        raise RuntimeError(f"Multiple shift files found below {match_dir}: {shift_files}")
    shift_path = shift_files[0]

    game_header = load_json(match_dir / "game-header.json")
    roster = load_json(match_dir / "roster.json")
    shifts = load_json(shift_path)
    shots_payload = load_json(match_dir / "shots.json")["match"]
    shots = shots_payload["shots"]
    faceoffs = load_json(match_dir / "faceoffs.json")
    period_events = load_json(match_dir / "period-events.json")

    home_team_id = int(shots_payload["home_id"])
    away_team_id = int(shots_payload["visitor_id"])
    pteam = player_team_map(match_dir)
    schedule = _schedule_match(discovery_path, match_id)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(SCHEMA_SQL)
        for table in ("shot_on_ice", "shot_context", "events", "faceoffs", "shots", "shifts", "players", "matches"):
            con.execute(f"DELETE FROM {table} WHERE match_id = ?", [match_id])

        result = game_header.get("results", {})
        score = result.get("score", {}).get("final", {})
        con.execute(
            """INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                match_id,
                shots_payload.get("date"),
                schedule.get("start_date") if schedule else None,
                schedule.get("status") if schedule else game_header.get("actualTimeName"),
                home_team_id,
                game_header.get("teamInfo", {}).get("home", {}).get("name") or shots_payload.get("home_name"),
                away_team_id,
                game_header.get("teamInfo", {}).get("visitor", {}).get("name") or shots_payload.get("visitor_name"),
                game_header.get("stadium"),
                game_header.get("numberOfViewers"),
                score.get("score_home"),
                score.get("score_guest"),
                result.get("extra_time"),
                result.get("shooting"),
            ],
        )

        for side, team_id in (("home", home_team_id), ("visitor", away_team_id)):
            for roster_slot, player in roster.get(side, {}).items():
                con.execute(
                    """INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        match_id,
                        team_id,
                        side,
                        player.get("playerId"),
                        player.get("matchPlayerId"),
                        player.get("name"),
                        player.get("surname"),
                        " ".join(x for x in [player.get("name"), player.get("surname")] if x),
                        player.get("jersey"),
                        player.get("position"),
                        player.get("captain"),
                        player.get("startingSix"),
                        roster_slot,
                    ],
                )

        for shift in shifts:
            start = int(shift["startTime"]["time"])
            end = int(shift["endTime"]["time"])
            con.execute(
                """INSERT INTO shifts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    match_id,
                    shift.get("id"),
                    shift.get("team", {}).get("id"),
                    shift.get("team", {}).get("name"),
                    shift.get("player", {}).get("id"),
                    shift.get("player", {}).get("name"),
                    start,
                    end,
                    max(0, end - start),
                    shift.get("startTime", {}).get("realtime"),
                    shift.get("endTime", {}).get("realtime"),
                ],
            )

        for shot in shots:
            result_id = int(shot["match_shot_resutl_id"])
            polygon = shot.get("polygon")
            con.execute(
                """INSERT INTO shots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    match_id,
                    shot.get("id"),
                    shot.get("time"),
                    shot.get("real_date"),
                    shot.get("team_id"),
                    shot.get("player_id"),
                    shot.get("jersey"),
                    shot.get("first_name"),
                    shot.get("last_name"),
                    result_id,
                    SHOT_RESULT_MAP.get(result_id, "unknown"),
                    shot.get("coordinate_x"),
                    shot.get("coordinate_y"),
                    polygon if isinstance(polygon, str) else None,
                ],
            )

        for faceoff in faceoffs:
            winner_id = int(faceoff["winner"]["id"])
            loser_id = int(faceoff["losser"]["id"])
            con.execute(
                """INSERT INTO faceoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    match_id,
                    faceoff.get("id"),
                    faceoff.get("time"),
                    faceoff.get("realtime"),
                    faceoff.get("position"),
                    faceoff.get("positionShortcut"),
                    winner_id,
                    faceoff.get("winner", {}).get("name"),
                    pteam.get(winner_id),
                    loser_id,
                    faceoff.get("losser", {}).get("name"),
                    pteam.get(loser_id),
                ],
            )

        for event in flatten_period_events(period_events):
            data = event.get("data") or {}
            team_side = data.get("team")
            con.execute(
                """INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    match_id,
                    event["sequence"],
                    event["period_key"],
                    event.get("time"),
                    event.get("type"),
                    data.get("id"),
                    team_side,
                    _event_team_id(team_side, home_team_id, away_team_id),
                    data.get("balance"),
                    (data.get("scorer") or {}).get("playerId"),
                    (data.get("disciplinedPlayer") or {}).get("playerId"),
                    data.get("codename"),
                    data.get("duration"),
                    json.dumps(event, ensure_ascii=False),
                ],
            )

        sorted_faceoffs = sorted(faceoffs, key=lambda x: int(x["time"]))
        boundary_adjusted = 0
        low_confidence = 0
        dzone_10s = 0
        dzone_win_10s = 0
        for shot in shots:
            t = int(shot["time"])
            shooting_team_id = int(shot["team_id"])
            opponent_team_id = away_team_id if shooting_team_id == home_team_id else home_team_id
            on_for, on_against, method_for, method_against = resolve_on_ice_pair(
                shifts,
                team_a_id=shooting_team_id,
                team_b_id=opponent_team_id,
                game_time_s=t,
            )
            quality = _on_ice_quality(len(on_for), len(on_against), method_for, method_against)
            if quality == "boundary_adjusted":
                boundary_adjusted += 1
            elif quality == "low_confidence":
                low_confidence += 1

            prev = previous_faceoff(sorted_faceoffs, t)
            prev_id = prev_time = seconds_since = prev_winner_team = None
            prev_pos = prev_short = prev_zone = None
            won_by_shooting = None
            if prev:
                prev_id = int(prev["id"])
                prev_time = int(prev["time"])
                seconds_since = t - prev_time
                prev_pos = prev.get("position")
                prev_short = prev.get("positionShortcut")
                prev_zone = faceoff_zone_for_team(prev_short, shooting_team_id, home_team_id)
                prev_winner_team = pteam.get(int(prev["winner"]["id"]))
                won_by_shooting = prev_winner_team == shooting_team_id if prev_winner_team is not None else None
            flag_dzone = bool(prev and prev_zone == "defensive" and seconds_since is not None and 0 <= seconds_since <= 10)
            flag_dzone_win = bool(flag_dzone and won_by_shooting)
            dzone_10s += int(flag_dzone)
            dzone_win_10s += int(flag_dzone_win)

            for player_id in on_for:
                con.execute(
                    "INSERT INTO shot_on_ice VALUES (?, ?, ?, ?, ?, ?)",
                    [match_id, shot.get("id"), shooting_team_id, player_id, "for", method_for],
                )
            for player_id in on_against:
                con.execute(
                    "INSERT INTO shot_on_ice VALUES (?, ?, ?, ?, ?, ?)",
                    [match_id, shot.get("id"), opponent_team_id, player_id, "against", method_against],
                )

            con.execute(
                """INSERT INTO shot_context VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    match_id,
                    shot.get("id"),
                    t,
                    shooting_team_id,
                    opponent_team_id,
                    on_for,
                    on_against,
                    len(on_for),
                    len(on_against),
                    f"{len(on_for)}v{len(on_against)}",
                    method_for,
                    method_against,
                    quality,
                    prev_id,
                    prev_time,
                    seconds_since,
                    prev_pos,
                    prev_short,
                    prev_zone,
                    prev_winner_team,
                    won_by_shooting,
                    flag_dzone,
                    flag_dzone_win,
                ],
            )

        con.execute(
            """
            CREATE OR REPLACE VIEW event_log AS
            SELECT match_id, game_time_s, 30 AS sort_order, 'shot' AS log_type, shot_id AS source_id,
                   team_id, player_id, result AS detail, coordinate_x, coordinate_y
            FROM shots
            UNION ALL
            SELECT match_id, game_time_s, 10 AS sort_order, 'faceoff' AS log_type, faceoff_id AS source_id,
                   winner_team_id AS team_id, winner_player_id AS player_id, position_shortcut AS detail,
                   NULL::DOUBLE AS coordinate_x, NULL::DOUBLE AS coordinate_y
            FROM faceoffs
            UNION ALL
            SELECT match_id, game_time_s, 20 AS sort_order, event_type AS log_type, coalesce(event_id, sequence) AS source_id,
                   team_id, coalesce(scorer_player_id, disciplined_player_id) AS player_id,
                   coalesce(balance, penalty_code, period_key) AS detail,
                   NULL::DOUBLE AS coordinate_x, NULL::DOUBLE AS coordinate_y
            FROM events
            """
        )

        con.execute(
            """
            CREATE OR REPLACE VIEW shot_log AS
            SELECT
                s.match_id,
                s.shot_id,
                s.game_time_s,
                s.real_time,
                s.team_id,
                s.player_id,
                trim(coalesce(s.first_name, '') || ' ' || coalesce(s.last_name, '')) AS shooter,
                s.result_id,
                s.result,
                s.coordinate_x,
                s.coordinate_y,
                s.polygon,
                c.opponent_team_id,
                c.on_ice_for_player_ids,
                c.on_ice_against_player_ids,
                c.on_ice_for_count,
                c.on_ice_against_count,
                c.manpower,
                c.on_ice_quality,
                c.previous_faceoff_id,
                c.seconds_since_faceoff,
                c.previous_faceoff_position_shortcut,
                c.previous_faceoff_zone_for_shooting_team,
                c.previous_faceoff_winner_team_id,
                c.previous_faceoff_won_by_shooting_team,
                c.dzone_faceoff_to_shot_10s,
                c.dzone_faceoff_win_to_shot_10s
            FROM shots s
            JOIN shot_context c USING (match_id, shot_id)
            """
        )

        return {
            "match_id": match_id,
            "db_path": str(db_path),
            "players": len(pteam),
            "shifts": len(shifts),
            "shift_file": shift_path.name,
            "shots": len(shots),
            "faceoffs": len(faceoffs),
            "events": sum(len(v) for v in period_events.values()),
            "boundary_adjusted_shots": boundary_adjusted,
            "low_confidence_shots": low_confidence,
            "dzone_faceoff_to_shot_10s": dzone_10s,
            "dzone_faceoff_win_to_shot_10s": dzone_win_10s,
        }
    finally:
        con.close()
