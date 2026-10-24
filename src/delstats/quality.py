from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


FOR_AGAINST_FIELDS = (
    ("corsi_for", "corsi_against"),
    ("corsi_5v5_for", "corsi_5v5_against"),
    ("shots_on_goal_for", "shots_on_goal_against"),
    ("shots_on_goal_5v5_for", "shots_on_goal_5v5_against"),
    ("slot_attempts_for", "slot_attempts_against"),
    ("slot_attempts_5v5_for", "slot_attempts_5v5_against"),
    ("goals_for", "goals_against"),
    ("goals_eq_for", "goals_eq_against"),
    ("goals_5v5_for", "goals_5v5_against"),
    ("pp_goals_for", "pp_goals_against"),
    ("sh_goals_for", "sh_goals_against"),
)


def _rows(con: Any, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


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


def _num(value: Any) -> float:
    return float(value or 0)


def _close(a: Any, b: Any, tolerance: float = 0.01) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tolerance


def _issue(code: str, message: str, *, match_id: int | None = None, team_id: int | None = None, **details: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"code": code, "message": message}
    if match_id is not None:
        row["match_id"] = int(match_id)
    if team_id is not None:
        row["team_id"] = int(team_id)
    if details:
        row["details"] = details
    return row


def audit_database(con: Any) -> dict[str, Any]:
    """Cross-check independent DEL sources and derived analytics.

    Hard failures are mathematical or referential contradictions that should
    never be published. Warnings are suspicious source-data conditions that can
    be real but deserve inspection.
    """
    hard: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks = defaultdict(int)

    matches = {
        int(row["match_id"]): row
        for row in _rows(
            con,
            """
            SELECT match_id, home_team_id, away_team_id, home_score, away_score,
                   overtime, shootout
            FROM matches
            """,
        )
    }

    players_by_match_team: dict[tuple[int, int], set[int]] = defaultdict(set)
    goalies_by_match: dict[int, set[int]] = defaultdict(set)
    for row in _rows(con, "SELECT match_id, team_id, player_id, position FROM players"):
        mid, tid, pid = int(row["match_id"]), int(row["team_id"]), int(row["player_id"])
        players_by_match_team[(mid, tid)].add(pid)
        if str(row.get("position") or "").upper() == "GK":
            goalies_by_match[mid].add(pid)

    # 1) Derived team rows must be exact mirrors of each other.
    team_rows = _rows(con, "SELECT * FROM team_game_stats ORDER BY match_id, team_id")
    by_match: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in team_rows:
        by_match[int(row["match_id"])].append(row)

    for mid, rows in by_match.items():
        checks["team_game_matches"] += 1
        if len(rows) != 2:
            hard.append(_issue("team_row_count", f"expected 2 team rows, got {len(rows)}", match_id=mid))
            continue
        a, b = rows
        for own, against in FOR_AGAINST_FIELDS:
            if int(a.get(own) or 0) != int(b.get(against) or 0):
                hard.append(_issue(
                    "team_symmetry",
                    f"{own} does not mirror opponent {against}",
                    match_id=mid,
                    team_id=int(a["team_id"]),
                    field=own,
                    own=a.get(own),
                    opponent=b.get(against),
                ))
            if int(b.get(own) or 0) != int(a.get(against) or 0):
                hard.append(_issue(
                    "team_symmetry",
                    f"{own} does not mirror opponent {against}",
                    match_id=mid,
                    team_id=int(b["team_id"]),
                    field=own,
                    own=b.get(own),
                    opponent=a.get(against),
                ))

        for row in rows:
            tid = int(row["team_id"])
            corsi, sog, goals = int(row["corsi_for"] or 0), int(row["shots_on_goal_for"] or 0), int(row["goals_for"] or 0)
            corsi5, sog5, goals5 = int(row["corsi_5v5_for"] or 0), int(row["shots_on_goal_5v5_for"] or 0), int(row["goals_5v5_for"] or 0)
            slot, slot5 = int(row["slot_attempts_for"] or 0), int(row["slot_attempts_5v5_for"] or 0)
            if not (0 <= goals <= sog <= corsi):
                hard.append(_issue("shot_hierarchy", f"expected goals <= SOG <= Corsi, got {goals} <= {sog} <= {corsi}", match_id=mid, team_id=tid))
            if not (0 <= goals5 <= sog5 <= corsi5):
                hard.append(_issue("shot_hierarchy_5v5", f"expected 5v5 goals <= SOG <= Corsi, got {goals5} <= {sog5} <= {corsi5}", match_id=mid, team_id=tid))
            if slot > corsi or slot5 > corsi5:
                hard.append(_issue("slot_hierarchy", "slot attempts exceed all shot attempts", match_id=mid, team_id=tid, slot=slot, corsi=corsi, slot5=slot5, corsi5=corsi5))
            if goals5 > int(row["goals_eq_for"] or 0):
                hard.append(_issue("five_on_five_vs_eq", "5v5 goals exceed official EQ goals", match_id=mid, team_id=tid, goals5=goals5, eq=row["goals_eq_for"]))

            shooting = row.get("shooting_pct_5v5")
            save = row.get("save_pct_5v5")
            pdo = row.get("pdo_5v5")
            expected_shooting = round(goals5 * 100.0 / sog5, 3) if sog5 else None
            soga5 = int(row["shots_on_goal_5v5_against"] or 0)
            ga5 = int(row["goals_5v5_against"] or 0)
            expected_save = round((1.0 - ga5 / soga5) * 100.0, 3) if soga5 else None
            expected_pdo = round(expected_shooting + expected_save, 3) if expected_shooting is not None and expected_save is not None else None
            if not _close(shooting, expected_shooting, 0.001):
                hard.append(_issue("shooting_pct_formula", "5v5 shooting percentage does not match goals/SOG", match_id=mid, team_id=tid, actual=shooting, expected=expected_shooting))
            if not _close(save, expected_save, 0.001):
                hard.append(_issue("save_pct_formula", "5v5 save percentage does not match GA/SOGA", match_id=mid, team_id=tid, actual=save, expected=expected_save))
            if not _close(pdo, expected_pdo, 0.001):
                hard.append(_issue("pdo_formula", "PDO does not equal SH% + SV%", match_id=mid, team_id=tid, actual=pdo, expected=expected_pdo))
            for field in ("shooting_pct_5v5", "save_pct_5v5"):
                value = row.get(field)
                if value is not None and not (0 <= float(value) <= 100):
                    hard.append(_issue("percentage_range", f"{field} outside 0..100", match_id=mid, team_id=tid, field=field, value=value))
            if pdo is not None and not (0 <= float(pdo) <= 200):
                hard.append(_issue("pdo_range", "PDO outside 0..200", match_id=mid, team_id=tid, value=pdo))

    # 2) Goal events are the authoritative scoring source.
    goal_events = _rows(
        con,
        """
        SELECT match_id, sequence, period_key, game_time_s, team_id, scorer_player_id,
               balance, raw_json
        FROM events
        WHERE event_type='goal'
        ORDER BY match_id, game_time_s, sequence
        """,
    )
    goals_by_match: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in goal_events:
        goals_by_match[int(row["match_id"])].append(row)

    for mid, match in matches.items():
        goals = goals_by_match.get(mid, [])
        event_home = sum(int(g.get("team_id") or -1) == int(match["home_team_id"]) for g in goals)
        event_away = sum(int(g.get("team_id") or -1) == int(match["away_team_id"]) for g in goals)
        final_home, final_away = int(match.get("home_score") or 0), int(match.get("away_score") or 0)
        dh, da = final_home - event_home, final_away - event_away
        if bool(match.get("shootout")):
            if sorted((dh, da)) not in ([0, 0], [0, 1]):
                hard.append(_issue("final_score_vs_events", f"shootout score delta is not 0/1: final {final_home}:{final_away}, events {event_home}:{event_away}", match_id=mid))
        elif dh != 0 or da != 0:
            hard.append(_issue("final_score_vs_events", f"final score {final_home}:{final_away} != goal events {event_home}:{event_away}", match_id=mid))

        prev_home = prev_away = 0
        for event in goals:
            if str(event.get("period_key") or "").lower() == "shootout":
                continue
            data = _safe_json(event.get("raw_json")).get("data") or {}
            score = str(data.get("currentScore") or "")
            if ":" not in score:
                warnings.append(_issue("goal_missing_score", "goal event has no currentScore", match_id=mid, time_s=event.get("game_time_s")))
                continue
            try:
                home, away = (int(v) for v in score.split(":", 1))
            except ValueError:
                warnings.append(_issue("goal_invalid_score", f"invalid currentScore {score}", match_id=mid, time_s=event.get("game_time_s")))
                continue
            team_id = int(event.get("team_id") or -1)
            valid = (
                team_id == int(match["home_team_id"]) and home == prev_home + 1 and away == prev_away
            ) or (
                team_id == int(match["away_team_id"]) and away == prev_away + 1 and home == prev_home
            )
            if not valid:
                hard.append(_issue("goal_score_progression", f"goal score progression {prev_home}:{prev_away} -> {home}:{away} contradicts scoring team", match_id=mid, team_id=team_id, time_s=event.get("game_time_s")))
            prev_home, prev_away = home, away

    # 3) Every official non-shootout goal must pair to one goal shot.
    goal_shots = _rows(
        con,
        """
        SELECT s.match_id, s.shot_id, s.game_time_s, s.team_id, s.player_id,
               c.manpower, c.on_ice_for_player_ids, c.on_ice_against_player_ids,
               c.on_ice_method_for, c.on_ice_method_against
        FROM shots s
        JOIN shot_context c USING(match_id, shot_id)
        WHERE s.result='goal'
        ORDER BY s.match_id, s.game_time_s, s.shot_id
        """,
    )
    shots_by_match: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in goal_shots:
        shots_by_match[int(row["match_id"])].append(row)

    events_by_match_team: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    shots_by_match_team: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for event in goal_events:
        if str(event.get("period_key") or "").lower() == "shootout":
            continue
        if event.get("team_id") is not None:
            events_by_match_team[(int(event["match_id"]), int(event["team_id"]))].append(event)
    for shot in goal_shots:
        shots_by_match_team[(int(shot["match_id"]), int(shot["team_id"]))].append(shot)

    for key in sorted(set(events_by_match_team) | set(shots_by_match_team)):
        mid, team_id = key
        events = sorted(
            events_by_match_team.get(key, []),
            key=lambda row: (int(row.get("game_time_s") or 0), int(row.get("sequence") or 0)),
        )
        shots = sorted(
            shots_by_match_team.get(key, []),
            key=lambda row: (int(row.get("game_time_s") or 0), int(row.get("shot_id") or 0)),
        )
        if len(events) != len(shots):
            hard.append(_issue(
                "goal_feed_count_mismatch",
                f"official goal events ({len(events)}) != goal shots ({len(shots)}) for team",
                match_id=mid,
                team_id=team_id,
            ))
            continue

        for event, shot in zip(events, shots):
            event_time = int(event.get("game_time_s") or 0)
            shot_time = int(shot.get("game_time_s") or 0)
            delta = event_time - shot_time
            scorer = event.get("scorer_player_id")
            shot_player = shot.get("player_id")
            if abs(delta) > 5:
                warnings.append(_issue(
                    "goal_time_drift",
                    f"goal event/shot timestamps differ by {delta:+d}s",
                    match_id=mid,
                    team_id=team_id,
                    event_time_s=event_time,
                    shot_time_s=shot_time,
                    shot_id=int(shot["shot_id"]),
                ))
            if scorer is not None and shot_player is not None and int(scorer) != int(shot_player):
                warnings.append(_issue(
                    "goal_scorer_disagreement",
                    "official scorer differs from shot-feed shooter",
                    match_id=mid,
                    team_id=team_id,
                    event_time_s=event_time,
                    shot_time_s=shot_time,
                    official_scorer=int(scorer),
                    shot_player=int(shot_player),
                    shot_id=int(shot["shot_id"]),
                ))

            data = _safe_json(event.get("raw_json")).get("data") or {}
            attendants = data.get("attendants") or {}
            goalies = goalies_by_match.get(mid, set())

            def skaters(entries: list[dict[str, Any]]) -> list[int]:
                return sorted({
                    int(item["playerId"])
                    for item in entries
                    if item.get("playerId") is not None and int(item["playerId"]) not in goalies
                })

            expected_for = skaters(attendants.get("positive") or [])
            expected_against = skaters(attendants.get("negative") or [])
            if not (3 <= len(expected_for) <= 6 and 3 <= len(expected_against) <= 6):
                warnings.append(_issue(
                    "goal_attendants_incomplete",
                    "goal attendants do not resolve to 3..6 skaters per side",
                    match_id=mid,
                    team_id=team_id,
                    time_s=event_time,
                    for_count=len(expected_for),
                    against_count=len(expected_against),
                ))
                continue

            actual_for = sorted(int(x) for x in (shot.get("on_ice_for_player_ids") or []))
            actual_against = sorted(int(x) for x in (shot.get("on_ice_against_player_ids") or []))
            if actual_for != expected_for or actual_against != expected_against:
                hard.append(_issue(
                    "goal_context_mismatch",
                    "goal shot on-ice context differs from official goal attendants",
                    match_id=mid,
                    team_id=team_id,
                    time_s=event_time,
                    shot_id=int(shot["shot_id"]),
                    expected_for=expected_for,
                    actual_for=actual_for,
                    expected_against=expected_against,
                    actual_against=actual_against,
                ))
            expected_manpower = f"{len(expected_for)}v{len(expected_against)}"
            if str(shot.get("manpower")) != expected_manpower:
                hard.append(_issue(
                    "goal_manpower_mismatch",
                    f"goal manpower {shot.get('manpower')} != official attendants {expected_manpower}",
                    match_id=mid,
                    team_id=team_id,
                    time_s=event_time,
                    shot_id=int(shot["shot_id"]),
                ))

            balance = str(event.get("balance") or data.get("balance") or "")
            empty_net = bool(data.get("en"))
            if not empty_net:
                if balance == "EQ" and len(expected_for) != len(expected_against):
                    hard.append(_issue("goal_balance_mismatch", f"EQ goal has {expected_manpower} attendants", match_id=mid, team_id=team_id, time_s=event_time))
                elif balance.startswith("PP") and balance != "PP0" and len(expected_for) <= len(expected_against):
                    hard.append(_issue("goal_balance_mismatch", f"{balance} goal has {expected_manpower} attendants", match_id=mid, team_id=team_id, time_s=event_time))
                elif balance.startswith("SH") and len(expected_for) >= len(expected_against):
                    hard.append(_issue("goal_balance_mismatch", f"{balance} goal has {expected_manpower} attendants", match_id=mid, team_id=team_id, time_s=event_time))

    # 4) Referential integrity across shot, faceoff and on-ice data.
    bad_shot_refs = _rows(
        con,
        """
        SELECT s.match_id, s.shot_id, s.team_id, s.player_id
        FROM shots s
        LEFT JOIN players p
          ON p.match_id=s.match_id AND p.player_id=s.player_id AND p.team_id=s.team_id
        WHERE s.player_id IS NOT NULL AND p.player_id IS NULL
        LIMIT 50
        """,
    )
    for row in bad_shot_refs:
        hard.append(_issue("shot_player_reference", "shot references a player not on that team roster", match_id=int(row["match_id"]), team_id=int(row["team_id"]), shot_id=int(row["shot_id"]), player_id=int(row["player_id"])))

    for row in _rows(con, "SELECT match_id, shooting_team_id, opponent_team_id, shot_id, on_ice_for_player_ids, on_ice_against_player_ids FROM shot_context"):
        mid, for_team, against_team = int(row["match_id"]), int(row["shooting_team_id"]), int(row["opponent_team_id"])
        bad_for = sorted(int(pid) for pid in (row.get("on_ice_for_player_ids") or []) if int(pid) not in players_by_match_team[(mid, for_team)])
        bad_against = sorted(int(pid) for pid in (row.get("on_ice_against_player_ids") or []) if int(pid) not in players_by_match_team[(mid, against_team)])
        if bad_for or bad_against:
            warnings.append(_issue("on_ice_player_reference", "shot context contains player(s) outside roster/team", match_id=mid, shot_id=int(row["shot_id"]), bad_for=bad_for, bad_against=bad_against))

    bad_faceoffs = _rows(
        con,
        """
        SELECT match_id, faceoff_id, winner_team_id, loser_team_id
        FROM faceoffs
        WHERE winner_team_id IS NULL OR loser_team_id IS NULL OR winner_team_id=loser_team_id
        LIMIT 50
        """,
    )
    for row in bad_faceoffs:
        warnings.append(_issue("faceoff_team_reference", "faceoff winner/loser team mapping is missing or identical", match_id=int(row["match_id"]), faceoff_id=int(row["faceoff_id"]), winner_team_id=row.get("winner_team_id"), loser_team_id=row.get("loser_team_id")))

    # 5) Implausible manpower is not safe to auto-correct for normal shots.
    # Some DEL shift feeds contain real gaps or overlapping shifts. Keep these
    # visible as match-level warnings instead of inventing players.
    implausible = _rows(
        con,
        """
        SELECT match_id, count(*) AS shots,
               min(on_ice_for_count) AS min_for, max(on_ice_for_count) AS max_for,
               min(on_ice_against_count) AS min_against, max(on_ice_against_count) AS max_against
        FROM shot_context
        WHERE on_ice_for_count NOT BETWEEN 3 AND 6
           OR on_ice_against_count NOT BETWEEN 3 AND 6
        GROUP BY match_id
        ORDER BY shots DESC, match_id
        """,
    )
    for row in implausible:
        warnings.append(_issue(
            "implausible_manpower",
            f"{row['shots']} shot(s) have incomplete/overlapping shift context",
            match_id=int(row["match_id"]),
            shots=int(row["shots"]),
            for_range=[int(row["min_for"]), int(row["max_for"])],
            against_range=[int(row["min_against"]), int(row["max_against"])],
        ))

    # 6) Player-game aggregates should be internally coherent and reconcile to goals.
    pstats = _rows(
        con,
        """
        SELECT match_id, team_id, player_id, goals, assists, points,
               shots_attempts, shots_on_goal, shots_missed, shots_blocked,
               faceoffs_won, faceoffs_lost
        FROM player_game_stats
        """,
    )
    player_goal_totals: dict[tuple[int, int], int] = defaultdict(int)
    player_assist_totals: dict[tuple[int, int], int] = defaultdict(int)
    player_attempt_totals: dict[tuple[int, int], int] = defaultdict(int)
    player_sog_totals: dict[tuple[int, int], int] = defaultdict(int)
    player_faceoff_wins: dict[tuple[int, int], int] = defaultdict(int)
    player_faceoff_losses: dict[tuple[int, int], int] = defaultdict(int)
    for row in pstats:
        mid, tid = int(row["match_id"]), int(row["team_id"])
        goals, assists, points = int(row.get("goals") or 0), int(row.get("assists") or 0), int(row.get("points") or 0)
        key = (mid, tid)
        player_goal_totals[key] += goals
        player_assist_totals[key] += assists
        player_attempt_totals[key] += int(row.get("shots_attempts") or 0)
        player_sog_totals[key] += int(row.get("shots_on_goal") or 0)
        player_faceoff_wins[key] += int(row.get("faceoffs_won") or 0)
        player_faceoff_losses[key] += int(row.get("faceoffs_lost") or 0)
        if points != goals + assists:
            hard.append(_issue("player_points_formula", "player points != goals + assists", match_id=mid, team_id=tid, player_id=int(row["player_id"]), goals=goals, assists=assists, points=points))
        attempts, sog = int(row.get("shots_attempts") or 0), int(row.get("shots_on_goal") or 0)
        if attempts < 0 or sog < 0 or int(row.get("shots_missed") or 0) < 0 or int(row.get("shots_blocked") or 0) < 0:
            hard.append(_issue("negative_player_stat", "negative player shot statistic", match_id=mid, team_id=tid, player_id=int(row["player_id"])))
        if sog > attempts and attempts > 0:
            warnings.append(_issue("player_sog_vs_attempts", "player SOG exceeds reported shot attempts", match_id=mid, team_id=tid, player_id=int(row["player_id"]), sog=sog, attempts=attempts))

    event_goal_totals: dict[tuple[int, int], int] = defaultdict(int)
    for event in goal_events:
        if str(event.get("period_key") or "").lower() == "shootout":
            continue
        if event.get("team_id") is not None:
            event_goal_totals[(int(event["match_id"]), int(event["team_id"]))] += 1

    for key, event_goals in event_goal_totals.items():
        player_goals = player_goal_totals.get(key, 0)
        if player_goals != event_goals:
            warnings.append(_issue("player_goals_vs_events", "sum of player-game goals differs from official goal events", match_id=key[0], team_id=key[1], player_goals=player_goals, event_goals=event_goals))
        assists = player_assist_totals.get(key, 0)
        if assists > event_goals * 2:
            hard.append(_issue("assist_ceiling", "player assists exceed two per official goal", match_id=key[0], team_id=key[1], assists=assists, goals=event_goals))

    team_lookup = {
        (int(row["match_id"]), int(row["team_id"])): row
        for row in team_rows
    }
    for key, team in team_lookup.items():
        attempts = player_attempt_totals.get(key, 0)
        sog = player_sog_totals.get(key, 0)
        if attempts != int(team.get("corsi_for") or 0):
            warnings.append(_issue(
                "player_attempts_vs_shots",
                "sum of player shot attempts differs from raw shot-feed attempts",
                match_id=key[0],
                team_id=key[1],
                player_attempts=attempts,
                shot_feed_attempts=int(team.get("corsi_for") or 0),
            ))
        if sog != int(team.get("shots_on_goal_for") or 0):
            warnings.append(_issue(
                "player_sog_vs_shots",
                "sum of player SOG differs from raw shot-feed SOG",
                match_id=key[0],
                team_id=key[1],
                player_sog=sog,
                shot_feed_sog=int(team.get("shots_on_goal_for") or 0),
            ))

    raw_faceoff_wins: dict[tuple[int, int], int] = defaultdict(int)
    raw_faceoff_losses: dict[tuple[int, int], int] = defaultdict(int)
    for row in _rows(con, "SELECT match_id, winner_team_id, loser_team_id FROM faceoffs"):
        mid = int(row["match_id"])
        if row.get("winner_team_id") is not None:
            raw_faceoff_wins[(mid, int(row["winner_team_id"]))] += 1
        if row.get("loser_team_id") is not None:
            raw_faceoff_losses[(mid, int(row["loser_team_id"]))] += 1
    for key in set(raw_faceoff_wins) | set(raw_faceoff_losses) | set(player_faceoff_wins) | set(player_faceoff_losses):
        pw, pl = player_faceoff_wins.get(key, 0), player_faceoff_losses.get(key, 0)
        rw, rl = raw_faceoff_wins.get(key, 0), raw_faceoff_losses.get(key, 0)
        if pw != rw or pl != rl:
            warnings.append(_issue(
                "player_faceoffs_vs_feed",
                "player faceoff totals differ from raw faceoff feed",
                match_id=key[0],
                team_id=key[1],
                player_wins=pw,
                raw_wins=rw,
                player_losses=pl,
                raw_losses=rl,
            ))

    checks["matches"] = len(matches)
    checks["team_game_rows"] = len(team_rows)
    checks["goal_events"] = len(goal_events)
    checks["goal_shots"] = len(goal_shots)
    checks["player_game_rows"] = len(pstats)
    checks["hard_failures"] = len(hard)
    checks["warnings"] = len(warnings)
    return {
        "checks": dict(checks),
        "hard_failures": hard,
        "warnings": warnings,
    }
