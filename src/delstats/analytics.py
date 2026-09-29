from __future__ import annotations

from pathlib import Path
from typing import Any

from .transform import load_json

ANALYTICS_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS teams (
    team_id BIGINT PRIMARY KEY,
    team_name VARCHAR,
    shortcut VARCHAR
);

CREATE TABLE IF NOT EXISTS player_game_stats (
    match_id BIGINT,
    team_id BIGINT,
    player_id BIGINT,
    player_name VARCHAR,
    jersey INTEGER,
    position VARCHAR,
    games INTEGER,
    goals INTEGER,
    assists INTEGER,
    points INTEGER,
    pp_goals INTEGER,
    sh_goals INTEGER,
    shots_attempts INTEGER,
    shots_on_goal INTEGER,
    shots_missed INTEGER,
    shots_blocked INTEGER,
    blocked_shots INTEGER,
    faceoffs_won INTEGER,
    faceoffs_lost INTEGER,
    time_on_ice_s INTEGER,
    time_on_ice_pp_s INTEGER,
    time_on_ice_sh_s INTEGER,
    shifts INTEGER,
    PRIMARY KEY (match_id, team_id, player_id)
);

CREATE TABLE IF NOT EXISTS team_game_stats (
    match_id BIGINT,
    match_date DATE,
    team_id BIGINT,
    team_shortcut VARCHAR,
    team_name VARCHAR,
    opponent_team_id BIGINT,
    opponent_shortcut VARCHAR,
    opponent_name VARCHAR,
    home_road VARCHAR,
    corsi_for INTEGER,
    corsi_against INTEGER,
    corsi_pct DOUBLE,
    corsi_5v5_for INTEGER,
    corsi_5v5_against INTEGER,
    corsi_5v5_pct DOUBLE,
    shots_on_goal_for INTEGER,
    shots_on_goal_against INTEGER,
    shots_on_goal_5v5_for INTEGER,
    shots_on_goal_5v5_against INTEGER,
    slot_attempts_for INTEGER,
    slot_attempts_against INTEGER,
    slot_attempts_5v5_for INTEGER,
    slot_attempts_5v5_against INTEGER,
    goals_for INTEGER,
    goals_against INTEGER,
    goals_eq_for INTEGER,
    goals_eq_against INTEGER,
    goals_5v5_for INTEGER,
    goals_5v5_against INTEGER,
    pp_goals_for INTEGER,
    pp_goals_against INTEGER,
    sh_goals_for INTEGER,
    sh_goals_against INTEGER,
    time_leading_s INTEGER,
    time_tied_s INTEGER,
    time_trailing_s INTEGER,
    scoring_players INTEGER,
    defenseman_points INTEGER,
    shooting_pct_5v5 DOUBLE,
    save_pct_5v5 DOUBLE,
    pdo_5v5 DOUBLE,
    PRIMARY KEY (match_id, team_id)
);
"""


def _split_stat(value: Any) -> int:
    if isinstance(value, dict):
        return int(sum((v or 0) for v in value.values()))
    return int(value or 0)


def _scalar(con: Any, sql: str, params: list[Any]) -> int:
    row = con.execute(sql, params).fetchone()
    return int((row[0] if row else 0) or 0)


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 3)


def import_player_game_stats(con: Any, *, match_dir: Path, match_id: int) -> int:
    con.execute(ANALYTICS_SCHEMA_SQL)
    con.execute("DELETE FROM player_game_stats WHERE match_id = ?", [match_id])
    count = 0
    for path in sorted((match_dir / "team-stats").glob("*.json")):
        try:
            team_id = int(path.stem)
        except ValueError:
            continue
        players = load_json(path)
        for player in players:
            stats = player.get("statistics") or {}
            name = player.get("name") or " ".join(
                x for x in [player.get("firstname"), player.get("surname")] if x
            )
            con.execute(
                """
                INSERT INTO player_game_stats VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    match_id,
                    team_id,
                    player.get("id"),
                    name,
                    player.get("jersey"),
                    player.get("position"),
                    stats.get("games"),
                    _split_stat(stats.get("goals")),
                    _split_stat(stats.get("assists")),
                    _split_stat(stats.get("points")),
                    stats.get("ppGoals") or 0,
                    stats.get("shGoals") or 0,
                    stats.get("shotsAttempts") or 0,
                    _split_stat(stats.get("shotsOnGoal")),
                    stats.get("shotsMissed") or 0,
                    stats.get("shotsBlocked") or 0,
                    stats.get("blockedShotsByPlayer") or 0,
                    stats.get("faceoffsWin") or 0,
                    stats.get("faceoffsLosses") or 0,
                    stats.get("timeOnIce") or 0,
                    stats.get("timeOnIcePP") or 0,
                    stats.get("timeOnIceSH") or 0,
                    stats.get("shifts") or 0,
                ],
            )
            count += 1
    return count


def _state_durations(period_events: dict[str, Any], game_end_s: int) -> dict[str, dict[str, int]]:
    """Return leading/tied/trailing seconds for home and visitor."""
    goals = []
    for events in period_events.values():
        for event in events:
            if event.get("type") != "goal":
                continue
            data = event.get("data") or {}
            score = data.get("currentScore")
            if not score or ":" not in score:
                continue
            try:
                home, visitor = (int(v) for v in score.split(":", 1))
                goals.append((int(event.get("time") or 0), home, visitor))
            except (TypeError, ValueError):
                continue
    goals.sort(key=lambda x: x[0])

    result = {
        "home": {"leading": 0, "tied": 0, "trailing": 0},
        "visitor": {"leading": 0, "tied": 0, "trailing": 0},
    }
    score_home = score_visitor = 0
    cursor = 0

    def add(duration: int) -> None:
        if duration <= 0:
            return
        if score_home > score_visitor:
            result["home"]["leading"] += duration
            result["visitor"]["trailing"] += duration
        elif score_home < score_visitor:
            result["home"]["trailing"] += duration
            result["visitor"]["leading"] += duration
        else:
            result["home"]["tied"] += duration
            result["visitor"]["tied"] += duration

    for event_time, new_home, new_visitor in goals:
        event_time = max(cursor, min(event_time, game_end_s))
        add(event_time - cursor)
        score_home, score_visitor = new_home, new_visitor
        cursor = event_time
    add(max(0, game_end_s - cursor))
    return result


def refresh_team_game_stats(
    con: Any,
    *,
    match_id: int,
    game_header: dict[str, Any],
    period_events: dict[str, Any],
) -> None:
    con.execute(ANALYTICS_SCHEMA_SQL)
    con.execute("DELETE FROM team_game_stats WHERE match_id = ?", [match_id])

    match = con.execute(
        """
        SELECT match_date, home_team_id, home_team_name, away_team_id, away_team_name
        FROM matches WHERE match_id = ?
        """,
        [match_id],
    ).fetchone()
    if not match:
        return
    match_date, home_id, home_name, away_id, away_name = match
    team_info = game_header.get("teamInfo") or {}
    home_short = (team_info.get("home") or {}).get("shortcut")
    away_short = (team_info.get("visitor") or {}).get("shortcut")
    con.execute("INSERT OR REPLACE INTO teams VALUES (?, ?, ?)", [home_id, home_name, home_short])
    con.execute("INSERT OR REPLACE INTO teams VALUES (?, ?, ?)", [away_id, away_name, away_short])

    game_end_s = int(game_header.get("lastEventTime") or 3600)
    durations = _state_durations(period_events, game_end_s)

    for side, team_id, team_name, team_short, opp_id, opp_name, opp_short in (
        ("home", home_id, home_name, home_short, away_id, away_name, away_short),
        ("visitor", away_id, away_name, away_short, home_id, home_name, home_short),
    ):
        cf = _scalar(con, "SELECT count(*) FROM shots WHERE match_id=? AND team_id=?", [match_id, team_id])
        ca = _scalar(con, "SELECT count(*) FROM shots WHERE match_id=? AND team_id=?", [match_id, opp_id])
        cf5 = _scalar(
            con,
            """SELECT count(*) FROM shots s JOIN shot_context c USING(match_id, shot_id)
               WHERE s.match_id=? AND s.team_id=? AND c.manpower='5v5'""",
            [match_id, team_id],
        )
        ca5 = _scalar(
            con,
            """SELECT count(*) FROM shots s JOIN shot_context c USING(match_id, shot_id)
               WHERE s.match_id=? AND s.team_id=? AND c.manpower='5v5'""",
            [match_id, opp_id],
        )
        sogf = _scalar(
            con,
            "SELECT count(*) FROM shots WHERE match_id=? AND team_id=? AND result IN ('on_goal','goal')",
            [match_id, team_id],
        )
        soga = _scalar(
            con,
            "SELECT count(*) FROM shots WHERE match_id=? AND team_id=? AND result IN ('on_goal','goal')",
            [match_id, opp_id],
        )
        sogf5 = _scalar(
            con,
            """SELECT count(*) FROM shots s JOIN shot_context c USING(match_id, shot_id)
               WHERE s.match_id=? AND s.team_id=? AND s.result IN ('on_goal','goal') AND c.manpower='5v5'""",
            [match_id, team_id],
        )
        soga5 = _scalar(
            con,
            """SELECT count(*) FROM shots s JOIN shot_context c USING(match_id, shot_id)
               WHERE s.match_id=? AND s.team_id=? AND s.result IN ('on_goal','goal') AND c.manpower='5v5'""",
            [match_id, opp_id],
        )
        slotf = _scalar(con, "SELECT count(*) FROM shots WHERE match_id=? AND team_id=? AND shot_zone='SLOT'", [match_id, team_id])
        slota = _scalar(con, "SELECT count(*) FROM shots WHERE match_id=? AND team_id=? AND shot_zone='SLOT'", [match_id, opp_id])
        slotf5 = _scalar(
            con,
            """SELECT count(*) FROM shots s JOIN shot_context c USING(match_id, shot_id)
               WHERE s.match_id=? AND s.team_id=? AND s.shot_zone='SLOT' AND c.manpower='5v5'""",
            [match_id, team_id],
        )
        slota5 = _scalar(
            con,
            """SELECT count(*) FROM shots s JOIN shot_context c USING(match_id, shot_id)
               WHERE s.match_id=? AND s.team_id=? AND s.shot_zone='SLOT' AND c.manpower='5v5'""",
            [match_id, opp_id],
        )

        gf = _scalar(con, "SELECT count(*) FROM events WHERE match_id=? AND event_type='goal' AND team_id=?", [match_id, team_id])
        ga = _scalar(con, "SELECT count(*) FROM events WHERE match_id=? AND event_type='goal' AND team_id=?", [match_id, opp_id])
        eqf = _scalar(con, "SELECT count(*) FROM events WHERE match_id=? AND event_type='goal' AND team_id=? AND balance='EQ'", [match_id, team_id])
        eqa = _scalar(con, "SELECT count(*) FROM events WHERE match_id=? AND event_type='goal' AND team_id=? AND balance='EQ'", [match_id, opp_id])
        gf5 = _scalar(
            con,
            """SELECT count(*) FROM shots s JOIN shot_context c USING(match_id, shot_id)
               WHERE s.match_id=? AND s.team_id=? AND s.result='goal' AND c.manpower='5v5'""",
            [match_id, team_id],
        )
        ga5 = _scalar(
            con,
            """SELECT count(*) FROM shots s JOIN shot_context c USING(match_id, shot_id)
               WHERE s.match_id=? AND s.team_id=? AND s.result='goal' AND c.manpower='5v5'""",
            [match_id, opp_id],
        )
        ppgf = _scalar(
            con,
            """SELECT count(*) FROM events WHERE match_id=? AND event_type='goal' AND team_id=?
               AND balance LIKE 'PP%' AND balance <> 'PP0'""",
            [match_id, team_id],
        )
        ppga = _scalar(
            con,
            """SELECT count(*) FROM events WHERE match_id=? AND event_type='goal' AND team_id=?
               AND balance LIKE 'PP%' AND balance <> 'PP0'""",
            [match_id, opp_id],
        )
        shgf = _scalar(con, "SELECT count(*) FROM events WHERE match_id=? AND event_type='goal' AND team_id=? AND balance LIKE 'SH%'", [match_id, team_id])
        shga = _scalar(con, "SELECT count(*) FROM events WHERE match_id=? AND event_type='goal' AND team_id=? AND balance LIKE 'SH%'", [match_id, opp_id])

        scoring_players = _scalar(con, "SELECT count(DISTINCT player_id) FROM player_game_stats WHERE match_id=? AND team_id=? AND points>0", [match_id, team_id])
        defenseman_points = _scalar(con, "SELECT coalesce(sum(points),0) FROM player_game_stats WHERE match_id=? AND team_id=? AND position='DE'", [match_id, team_id])

        shooting = _pct(gf5, sogf5)
        save = round((1.0 - ga5 / soga5) * 100.0, 3) if soga5 > 0 else None
        pdo = round(shooting + save, 3) if shooting is not None and save is not None else None
        corsi_pct = _pct(cf, cf + ca)
        corsi_5v5_pct = _pct(cf5, cf5 + ca5)
        time_state = durations[side]

        con.execute(
            """
            INSERT INTO team_game_stats VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                match_id, match_date, team_id, team_short, team_name, opp_id, opp_short, opp_name, side,
                cf, ca, corsi_pct, cf5, ca5, corsi_5v5_pct,
                sogf, soga, sogf5, soga5,
                slotf, slota, slotf5, slota5,
                gf, ga, eqf, eqa, gf5, ga5, ppgf, ppga, shgf, shga,
                time_state["leading"], time_state["tied"], time_state["trailing"],
                scoring_players, defenseman_points, shooting, save, pdo,
            ],
        )

    refresh_season_views(con)


def refresh_season_views(con: Any) -> None:
    con.execute(
        """
        CREATE OR REPLACE VIEW team_season_stats AS
        WITH base AS (
            SELECT
                team_id,
                any_value(team_shortcut) AS team_shortcut,
                any_value(team_name) AS team_name,
                count(*) AS games_played,
                sum(corsi_for)::BIGINT AS corsi_for,
                sum(corsi_against)::BIGINT AS corsi_against,
                sum(corsi_5v5_for)::BIGINT AS corsi_5v5_for,
                sum(corsi_5v5_against)::BIGINT AS corsi_5v5_against,
                sum(shots_on_goal_for)::BIGINT AS shots_on_goal_for,
                sum(shots_on_goal_against)::BIGINT AS shots_on_goal_against,
                sum(shots_on_goal_5v5_for)::BIGINT AS shots_on_goal_5v5_for,
                sum(shots_on_goal_5v5_against)::BIGINT AS shots_on_goal_5v5_against,
                sum(slot_attempts_for)::BIGINT AS slot_attempts_for,
                sum(slot_attempts_against)::BIGINT AS slot_attempts_against,
                sum(slot_attempts_5v5_for)::BIGINT AS slot_attempts_5v5_for,
                sum(slot_attempts_5v5_against)::BIGINT AS slot_attempts_5v5_against,
                sum(goals_for)::BIGINT AS goals_for,
                sum(goals_against)::BIGINT AS goals_against,
                sum(goals_eq_for)::BIGINT AS goals_eq_for,
                sum(goals_eq_against)::BIGINT AS goals_eq_against,
                sum(goals_5v5_for)::BIGINT AS goals_5v5_for,
                sum(goals_5v5_against)::BIGINT AS goals_5v5_against,
                sum(pp_goals_for)::BIGINT AS pp_goals_for,
                sum(pp_goals_against)::BIGINT AS pp_goals_against,
                sum(sh_goals_for)::BIGINT AS sh_goals_for,
                sum(sh_goals_against)::BIGINT AS sh_goals_against,
                sum(time_leading_s)::BIGINT AS time_leading_s,
                sum(time_tied_s)::BIGINT AS time_tied_s,
                sum(time_trailing_s)::BIGINT AS time_trailing_s
            FROM team_game_stats
            GROUP BY team_id
        ), scorer AS (
            SELECT
                team_id,
                count(DISTINCT CASE WHEN points > 0 THEN player_id END)::BIGINT AS scoring_players,
                coalesce(sum(CASE WHEN position='DE' THEN points ELSE 0 END), 0)::BIGINT AS defenseman_points
            FROM player_game_stats
            GROUP BY team_id
        )
        SELECT
            b.*,
            CASE WHEN (b.corsi_for + b.corsi_against) > 0
                 THEN round(b.corsi_for * 100.0 / (b.corsi_for + b.corsi_against), 3) END AS corsi_pct,
            CASE WHEN (b.corsi_5v5_for + b.corsi_5v5_against) > 0
                 THEN round(b.corsi_5v5_for * 100.0 / (b.corsi_5v5_for + b.corsi_5v5_against), 3) END AS corsi_5v5_pct,
            coalesce(s.scoring_players, 0) AS scoring_players,
            coalesce(s.defenseman_points, 0) AS defenseman_points,
            CASE WHEN b.shots_on_goal_5v5_for > 0
                 THEN round(b.goals_5v5_for * 100.0 / b.shots_on_goal_5v5_for, 3) END AS shooting_pct_5v5,
            CASE WHEN b.shots_on_goal_5v5_against > 0
                 THEN round((1.0 - b.goals_5v5_against * 1.0 / b.shots_on_goal_5v5_against) * 100.0, 3) END AS save_pct_5v5,
            CASE WHEN b.shots_on_goal_5v5_for > 0 AND b.shots_on_goal_5v5_against > 0
                 THEN round(
                    b.goals_5v5_for * 100.0 / b.shots_on_goal_5v5_for
                    + (1.0 - b.goals_5v5_against * 1.0 / b.shots_on_goal_5v5_against) * 100.0,
                    3
                 ) END AS pdo_5v5
        FROM base b
        LEFT JOIN scorer s USING(team_id)
        """
    )
