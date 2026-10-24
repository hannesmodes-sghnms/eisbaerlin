from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .lineups import analyze_5v5_lineups


@dataclass(frozen=True)
class StoryFact:
    category: str
    score: int
    kind: str
    text: str


CATEGORY_META: tuple[tuple[str, str, int], ...] = (
    ("current_story", "🔥 Aktuelle Story", 2),
    ("lineup", "🔄 Lineup & Reihen", 2),
    ("form", "📈 Form & Serien", 2),
    ("nerd", "🔬 Nerd Fact", 2),
)


def _fmt_time(seconds: int | float | None) -> str:
    value = int(seconds or 0)
    return f"{value // 60}:{value % 60:02d}"


def _fmt_decimal(value: float | int | None, decimals: int = 1) -> str:
    if value is None:
        return "–"
    return f"{float(value):.{decimals}f}".replace(".", ",")


def _plural(value: int, singular: str, plural: str) -> str:
    return singular if int(value) == 1 else plural


def scoring_streaks(
    con: Any,
    *,
    team_id: int,
    match_id: int,
    min_games: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    game_rows = con.execute(
        """
        SELECT match_id, match_date
        FROM team_game_stats
        WHERE team_id=?
        ORDER BY match_date, match_id
        """,
        [team_id],
    ).fetchall()
    game_ids = [int(row[0]) for row in game_rows]
    if match_id not in game_ids:
        return {"active": [], "ended_this_game": []}
    allowed = set(game_ids[: game_ids.index(match_id) + 1])

    cur = con.execute(
        """
        SELECT p.match_id, t.match_date, p.player_id, p.player_name, p.jersey,
               p.goals, p.assists, p.points, p.games
        FROM player_game_stats p
        JOIN team_game_stats t ON t.match_id=p.match_id AND t.team_id=p.team_id
        WHERE p.team_id=? AND coalesce(p.position, '') <> 'GK'
        ORDER BY t.match_date, p.match_id, p.player_id
        """,
        [team_id],
    )
    cols = [d[0] for d in cur.description]
    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for raw in cur.fetchall():
        row = dict(zip(cols, raw))
        if int(row["match_id"]) not in allowed:
            continue
        if row.get("games") is not None and int(row.get("games") or 0) <= 0:
            continue
        by_player[int(row["player_id"])].append(row)

    active: list[dict[str, Any]] = []
    ended: list[dict[str, Any]] = []
    for rows in by_player.values():
        rows.sort(key=lambda row: (row.get("match_date"), int(row["match_id"])))
        if not rows or int(rows[-1]["match_id"]) != int(match_id):
            continue

        current = rows[-1]
        if int(current.get("points") or 0) > 0:
            streak_rows = []
            for row in reversed(rows):
                if int(row.get("points") or 0) <= 0:
                    break
                streak_rows.append(row)
            if len(streak_rows) >= min_games:
                active.append(
                    {
                        "player_id": int(current["player_id"]),
                        "player_name": current.get("player_name"),
                        "jersey": current.get("jersey"),
                        "games": len(streak_rows),
                        "goals": sum(int(row.get("goals") or 0) for row in streak_rows),
                        "assists": sum(int(row.get("assists") or 0) for row in streak_rows),
                        "points": sum(int(row.get("points") or 0) for row in streak_rows),
                    }
                )
        else:
            streak_rows = []
            for row in reversed(rows[:-1]):
                if int(row.get("points") or 0) <= 0:
                    break
                streak_rows.append(row)
            if len(streak_rows) >= min_games:
                ended.append(
                    {
                        "player_id": int(current["player_id"]),
                        "player_name": current.get("player_name"),
                        "jersey": current.get("jersey"),
                        "games": len(streak_rows),
                        "goals": sum(int(row.get("goals") or 0) for row in streak_rows),
                        "assists": sum(int(row.get("assists") or 0) for row in streak_rows),
                        "points": sum(int(row.get("points") or 0) for row in streak_rows),
                    }
                )

    key = lambda row: (int(row["games"]), int(row["points"]), int(row["goals"]))
    active.sort(key=key, reverse=True)
    ended.sort(key=key, reverse=True)
    return {"active": active, "ended_this_game": ended}


def _regular_units(
    lineups: dict[str, Any],
    key: str,
    *,
    limit: int,
    min_seconds: int,
) -> list[dict[str, Any]]:
    rows = sorted(
        list(lineups.get(key) or []),
        key=lambda row: (int(row.get("total_s") or 0), int(row.get("appearances") or 0)),
        reverse=True,
    )
    regular = [row for row in rows if int(row.get("total_s") or 0) >= min_seconds]
    return regular[:limit]


def _unit_identity(row: dict[str, Any]) -> tuple[int, ...]:
    return tuple(sorted(int(player_id) for player_id in row.get("player_ids") or []))


def _active_skaters(con: Any, match_id: int, team_id: int) -> list[dict[str, Any]]:
    cur = con.execute(
        """
        SELECT player_id, player_name, jersey
        FROM player_game_stats
        WHERE match_id=? AND team_id=? AND coalesce(position, '') <> 'GK'
        ORDER BY jersey, player_name
        """,
        [match_id, team_id],
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def previous_game_lineup_diff(
    con: Any,
    *,
    team_id: int,
    match_id: int,
    current_lineups: dict[str, Any],
) -> dict[str, Any]:
    games = con.execute(
        """
        SELECT t.match_id, t.match_date, m.home_team_id, m.home_team_name,
               m.away_team_id, m.away_team_name
        FROM team_game_stats t
        JOIN matches m USING(match_id)
        WHERE t.team_id=?
        ORDER BY t.match_date, t.match_id
        """,
        [team_id],
    ).fetchall()
    game_ids = [int(row[0]) for row in games]
    if match_id not in game_ids:
        return {"available": False}
    idx = game_ids.index(match_id)
    if idx <= 0:
        return {"available": False}

    prev = games[idx - 1]
    prev_match_id = int(prev[0])
    home_team_id = int(prev[2])
    away_team_id = int(prev[4])
    opponent_team_id = away_team_id if home_team_id == team_id else home_team_id
    opponent_name = str(prev[5] if home_team_id == team_id else prev[3])

    shifts_cur = con.execute(
        """
        SELECT team_id, player_id, start_time_s, end_time_s
        FROM shifts
        WHERE match_id=?
        ORDER BY start_time_s, shift_id
        """,
        [prev_match_id],
    )
    shift_cols = [d[0] for d in shifts_cur.description]
    shifts = [dict(zip(shift_cols, row)) for row in shifts_cur.fetchall()]

    players_cur = con.execute(
        """
        SELECT team_id, player_id, full_name, last_name, jersey, position
        FROM players
        WHERE match_id=?
        """,
        [prev_match_id],
    )
    player_cols = [d[0] for d in players_cur.description]
    players = [dict(zip(player_cols, row)) for row in players_cur.fetchall()]
    previous_lineups = analyze_5v5_lineups(
        shifts,
        players,
        focus_team_id=team_id,
        opponent_team_id=opponent_team_id,
    )

    current_players = _active_skaters(con, match_id, team_id)
    previous_players = _active_skaters(con, prev_match_id, team_id)
    current_names = {int(row["player_id"]): str(row.get("player_name") or row["player_id"]) for row in current_players}
    previous_names = {int(row["player_id"]): str(row.get("player_name") or row["player_id"]) for row in previous_players}

    current_ids = set(current_names)
    previous_ids = set(previous_names)
    players_in = [
        {"player_id": player_id, "name": current_names[player_id]}
        for player_id in sorted(current_ids - previous_ids, key=lambda pid: current_names[pid])
    ]
    players_out = [
        {"player_id": player_id, "name": previous_names[player_id]}
        for player_id in sorted(previous_ids - current_ids, key=lambda pid: previous_names[pid])
    ]

    def compare_units(
        key: str,
        *,
        limit: int,
        min_seconds: int,
    ) -> dict[str, Any]:
        current_rows = _regular_units(current_lineups, key, limit=limit, min_seconds=min_seconds)
        previous_rows = _regular_units(previous_lineups, key, limit=limit, min_seconds=min_seconds)
        current_map = {_unit_identity(row): row for row in current_rows}
        previous_map = {_unit_identity(row): row for row in previous_rows}
        stable_ids = set(current_map) & set(previous_map)
        new_ids = set(current_map) - set(previous_map)
        dropped_ids = set(previous_map) - set(current_map)

        sort_key = lambda pair: int(pair[1].get("total_s") or 0)
        return {
            "current_count": len(current_rows),
            "previous_count": len(previous_rows),
            "stable": [row.get("label") for _, row in sorted(((uid, current_map[uid]) for uid in stable_ids), key=sort_key, reverse=True)],
            "new": [row.get("label") for _, row in sorted(((uid, current_map[uid]) for uid in new_ids), key=sort_key, reverse=True)],
            "dropped": [row.get("label") for _, row in sorted(((uid, previous_map[uid]) for uid in dropped_ids), key=sort_key, reverse=True)],
        }

    return {
        "available": True,
        "previous_match": {
            "match_id": prev_match_id,
            "date": str(prev[1]),
            "opponent_team_id": opponent_team_id,
            "opponent_name": opponent_name,
        },
        "players_in": players_in,
        "players_out": players_out,
        "forwards": compare_units("forward_trios", limit=4, min_seconds=120),
        "defense": compare_units("defense_pairs", limit=4, min_seconds=120),
    }


def _p3_rebuild_fact(lineups: dict[str, Any]) -> StoryFact | None:
    rotation = lineups.get("rotation") or {}
    dropped = list(rotation.get("dropped_p3_forward_trios") or [])
    new = list(rotation.get("new_p3_forward_trios") or [])
    if len(dropped) < 2 or not new:
        return None
    top = max(new, key=lambda row: (int(row.get("p3_s") or 0), int(row.get("p3_appearances") or 0)))
    dropped_count = len(dropped)
    text = (
        f"Umbau im Schlussdrittel: {dropped_count} zuvor regelmäßig eingesetzte Sturmreihen verschwanden "
        f"aus der 5v5-Rotation. {top.get('label')} war mit {_fmt_time(top.get('p3_s'))} Minuten und "
        f"{int(top.get('p3_appearances') or 0)} gemeinsamen Einsätzen die häufigste neue Kombination."
    )
    return StoryFact("lineup", 100 if dropped_count >= 3 else 88, "p3_rebuild", text)


def _previous_lineup_fact(diff: dict[str, Any]) -> StoryFact | None:
    if not diff.get("available"):
        return None
    previous = diff.get("previous_match") or {}
    opponent = previous.get("opponent_name") or "dem vorherigen Spiel"
    players_in = [row.get("name") for row in diff.get("players_in") or [] if row.get("name")]
    players_out = [row.get("name") for row in diff.get("players_out") or [] if row.get("name")]
    forwards = diff.get("forwards") or {}
    defense = diff.get("defense") or {}

    parts = [f"Lineup gegenüber {opponent}:"]
    if players_in:
        parts.append("neu dabei " + ", ".join(players_in) + ".")
    if players_out:
        parts.append("nicht mehr dabei " + ", ".join(players_out) + ".")

    stable_f = len(forwards.get("stable") or [])
    current_f = int(forwards.get("current_count") or 0)
    stable_d = len(defense.get("stable") or [])
    current_d = int(defense.get("current_count") or 0)
    if current_f:
        parts.append(f"Im Sturm blieben {stable_f} der {current_f} meistgenutzten Kombinationen identisch.")
    if current_d and stable_d == current_d:
        parts.append("Die meistgenutzten Verteidigerpaare blieben unverändert.")
    elif current_d:
        parts.append(f"In der Defense blieben {stable_d} der {current_d} meistgenutzten Paare identisch.")

    if len(parts) <= 1:
        return None
    changed_units = len(forwards.get("new") or []) + len(defense.get("new") or [])
    score = 92 if players_in or players_out else 84 if changed_units >= 2 else 72
    return StoryFact("lineup", score, "previous_game_lineup", " ".join(parts))


def _possession_danger_fact(
    ebb: dict[str, Any],
    game_insight: dict[str, Any] | None,
) -> StoryFact | None:
    cf = int(ebb.get("corsi_5v5_for") or 0)
    ca = int(ebb.get("corsi_5v5_against") or 0)
    sf = int(ebb.get("slot_attempts_5v5_for") or 0)
    sa = int(ebb.get("slot_attempts_5v5_against") or 0)
    if cf + ca < 20 or sf + sa < 8:
        return None
    corsi_share = cf / (cf + ca) * 100.0
    slot_share = sf / (sf + sa) * 100.0
    divergence = corsi_share - slot_share
    if abs(divergence) < 5.0:
        return None

    if divergence > 0:
        lead = (
            f"Mehr Schussvolumen als klare Chancenüberlegenheit: Berlin hatte {_fmt_decimal(corsi_share)} % "
            f"der 5v5-Schussversuche ({cf}:{ca}), die Slot Attempts lagen aber bei {sf}:{sa}."
        )
    else:
        lead = (
            f"Weniger Schussvolumen, aber mehr Gefahr aus dem Zentrum: Berlin hatte nur {_fmt_decimal(corsi_share)} % "
            f"der 5v5-Schussversuche ({cf}:{ca}), die Slot Attempts lagen dagegen bei {sf}:{sa}."
        )

    insight = game_insight or {}
    ebb_summary = ((insight.get("ebb") or {}).get("summary") or {})
    opp_summary = ((insight.get("opponent") or {}).get("summary") or {})
    if ebb_summary.get("xg_sum") is not None and opp_summary.get("xg_sum") is not None:
        lead += (
            f" Die DEL-xG-Auswertung lag insgesamt bei "
            f"{_fmt_decimal(ebb_summary.get('xg_sum'), 2)}:{_fmt_decimal(opp_summary.get('xg_sum'), 2)}."
        )
    return StoryFact("current_story", 96, "shot_volume_vs_danger", lead)


def _xg_player_fact(game_insight: dict[str, Any] | None) -> StoryFact | None:
    players = list((((game_insight or {}).get("ebb") or {}).get("players") or []))
    candidates = [row for row in players if row.get("xg_sum") is not None]
    if not candidates:
        return None
    top = max(candidates, key=lambda row: float(row.get("xg_sum") or 0.0))
    xg = float(top.get("xg_sum") or 0.0)
    goals = int(top.get("goals") or 0)
    if xg < 0.35 or goals > 0:
        return None
    name = str(top.get("player_name") or "Ein Berliner Spieler")
    text = (
        f"Gefahr ohne Treffer: {name} blieb ohne Tor, erzeugte mit {_fmt_decimal(xg, 2)} xG "
        f"aber den höchsten individuellen Erwartungswert der Eisbären."
    )
    return StoryFact("nerd", 90, "individual_xg", text)


def _streak_facts(
    streaks: dict[str, list[dict[str, Any]]],
    opponent_name: str,
) -> list[StoryFact]:
    facts: list[StoryFact] = []
    for row in (streaks.get("active") or [])[:2]:
        games = int(row["games"])
        goals = int(row["goals"])
        assists = int(row["assists"])
        facts.append(
            StoryFact(
                "form",
                94 + min(games, 5),
                "active_scoring_streak",
                (
                    f"{row.get('player_name')} punktet jetzt im {games}. Spiel in Folge: "
                    f"{goals} {_plural(goals, 'Tor', 'Tore')} und {assists} {_plural(assists, 'Assist', 'Assists')} "
                    f"während dieser Serie."
                ),
            )
        )
    for row in (streaks.get("ended_this_game") or [])[:1]:
        games = int(row["games"])
        facts.append(
            StoryFact(
                "form",
                91 + min(games, 4),
                "ended_scoring_streak",
                (
                    f"Die Punkteserie von {row.get('player_name')} über {games} Spiele ist gegen "
                    f"{opponent_name} gerissen."
                ),
            )
        )
    return facts


def _momentum_fact(
    shots: list[dict[str, Any]],
    *,
    focus_team_id: int,
    opponent_team_id: int,
    opponent_label: str,
) -> StoryFact | None:
    rows = [
        row
        for row in shots
        if row.get("game_time_s") is not None
        and 0 <= int(row.get("game_time_s") or 0) <= 3600
        and int(row.get("team_id") or -1) in {focus_team_id, opponent_team_id}
    ]
    if len(rows) < 12:
        return None

    best: tuple[float, int, int, int, int, int] | None = None
    window_s = 8 * 60
    for start in range(0, 3600 - window_s + 1, 60):
        end = start + window_s
        ebb = sum(1 for row in rows if start <= int(row["game_time_s"]) < end and int(row["team_id"]) == focus_team_id)
        opp = sum(1 for row in rows if start <= int(row["game_time_s"]) < end and int(row["team_id"]) == opponent_team_id)
        total = ebb + opp
        if total < 10:
            continue
        dominant = max(ebb, opp)
        share = dominant / total
        margin = abs(ebb - opp)
        if share < 0.75 or margin < 6:
            continue
        score = share * 100 + min(total, 20) + margin
        candidate = (score, start, end, ebb, opp, total)
        if best is None or candidate[0] > best[0]:
            best = candidate

    if best is None:
        return None
    _score, start, end, ebb, opp, total = best
    if ebb > opp:
        text = (
            f"Dominante Phase: Zwischen Minute {start // 60} und {end // 60} gingen "
            f"{ebb} der {total} Schussversuche an Berlin ({ebb}:{opp})."
        )
    else:
        text = (
            f"Druckphase des Gegners: Zwischen Minute {start // 60} und {end // 60} hatte "
            f"{opponent_label} {opp} der {total} Schussversuche ({opp}:{ebb})."
        )
    return StoryFact("current_story", 86, "momentum_window", text)


def _matchup_fact(advanced: dict[str, Any]) -> StoryFact | None:
    rows = list(advanced.get("relevant_forward_matchups") or advanced.get("primary_forward_matchups") or [])
    rows = [
        row
        for row in rows
        if int(row.get("total_s") or 0) >= 300
        and int(row.get("slot_for") or 0) + int(row.get("slot_against") or 0) >= 4
    ]
    if not rows:
        return None
    top = max(rows, key=lambda row: (int(row.get("total_s") or 0), int(row.get("appearances") or 0)))
    text = (
        f"Line-Matching mit Substanz: {top.get('ebb_label')} stand {_fmt_time(top.get('total_s'))} Minuten "
        f"gegen {top.get('opponent_label')} auf dem Eis. In dieser Zeit lagen die Slot Attempts bei "
        f"{int(top.get('slot_for') or 0)}:{int(top.get('slot_against') or 0)}."
    )
    return StoryFact("nerd", 78, "line_matchup", text)


def _scoring_breadth_fact(
    scoring_summary: list[dict[str, Any]],
    *,
    focus_team_id: int,
) -> StoryFact | None:
    goals = [row for row in scoring_summary if int(row.get("team_id") or -1) == focus_team_id]
    if len(goals) < 2:
        return None
    participants: set[str] = set()
    for goal in goals:
        scorer = (goal.get("scorer") or {}).get("name")
        if scorer:
            participants.add(str(scorer))
        for assist in goal.get("assists") or []:
            if assist.get("name"):
                participants.add(str(assist["name"]))
    if len(participants) < 5:
        return None
    text = (
        f"Scoring-Breite: An den {len(goals)} Berliner Toren waren {len(participants)} verschiedene Spieler beteiligt."
    )
    return StoryFact("current_story", 74, "scoring_breadth", text)


def _efficiency_fact(ebb: dict[str, Any]) -> StoryFact | None:
    goals = int(ebb.get("goals_for") or 0)
    cf = int(ebb.get("corsi_5v5_for") or 0)
    ca = int(ebb.get("corsi_5v5_against") or 0)
    sog = int(ebb.get("shots_on_goal_for") or 0)
    if goals < 3 or cf >= ca or sog <= 0:
        return None
    shooting = goals / sog * 100.0
    if shooting < 12.0:
        return None
    text = (
        f"Effizient trotz weniger 5v5-Volumen: Berlin lag bei den 5v5-Schussversuchen {cf}:{ca} hinten, "
        f"erzielte aber {goals} Tore aus {sog} Schüssen aufs Tor."
    )
    return StoryFact("current_story", 84, "efficiency_vs_volume", text)


def select_story_facts(
    candidates: list[StoryFact],
    *,
    max_facts: int = 8,
    min_score: int = 70,
) -> tuple[list[str], list[dict[str, Any]]]:
    unique: dict[tuple[str, str], StoryFact] = {}
    for candidate in candidates:
        key = (candidate.kind, candidate.text)
        current = unique.get(key)
        if current is None or candidate.score > current.score:
            unique[key] = candidate

    sorted_candidates = sorted(unique.values(), key=lambda row: (row.score, row.kind), reverse=True)
    limits = {category: limit for category, _title, limit in CATEGORY_META}
    selected: list[StoryFact] = []
    counts: dict[str, int] = defaultdict(int)
    for candidate in sorted_candidates:
        if candidate.score < min_score:
            continue
        if counts[candidate.category] >= limits.get(candidate.category, max_facts):
            continue
        selected.append(candidate)
        counts[candidate.category] += 1
        if len(selected) >= max_facts:
            break

    groups: list[dict[str, Any]] = []
    for category, title, _limit in CATEGORY_META:
        rows = [row for row in selected if row.category == category]
        if rows:
            rows.sort(key=lambda row: row.score, reverse=True)
            groups.append(
                {
                    "category": category,
                    "title": title,
                    "facts": [row.text for row in rows],
                }
            )

    flat = [row.text for row in sorted(selected, key=lambda row: row.score, reverse=True)]
    return flat, groups


def build_story_facts(
    *,
    ebb: dict[str, Any],
    lineups: dict[str, Any],
    previous_lineup: dict[str, Any],
    streaks: dict[str, list[dict[str, Any]]],
    advanced: dict[str, Any],
    game_insight: dict[str, Any] | None,
    shots: list[dict[str, Any]],
    scoring_summary: list[dict[str, Any]],
    focus_team_id: int,
    opponent_team_id: int,
    opponent_name: str,
    opponent_label: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    candidates: list[StoryFact] = []
    for candidate in (
        _p3_rebuild_fact(lineups),
        _previous_lineup_fact(previous_lineup),
        _possession_danger_fact(ebb, game_insight),
        _xg_player_fact(game_insight),
        _momentum_fact(
            shots,
            focus_team_id=focus_team_id,
            opponent_team_id=opponent_team_id,
            opponent_label=opponent_label,
        ),
        _matchup_fact(advanced),
        _scoring_breadth_fact(scoring_summary, focus_team_id=focus_team_id),
        _efficiency_fact(ebb),
    ):
        if candidate is not None:
            candidates.append(candidate)
    candidates.extend(_streak_facts(streaks, opponent_name))
    return select_story_facts(candidates)
