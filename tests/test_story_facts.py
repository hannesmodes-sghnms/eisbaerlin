import pytest

duckdb = pytest.importorskip("duckdb")

from delstats.story_facts import build_story_facts, scoring_streaks


def test_scoring_streaks_detects_active_and_ended_series():
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE team_game_stats (
            match_id INTEGER,
            team_id INTEGER,
            match_date DATE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE player_game_stats (
            match_id INTEGER,
            team_id INTEGER,
            player_id INTEGER,
            player_name VARCHAR,
            jersey INTEGER,
            position VARCHAR,
            goals INTEGER,
            assists INTEGER,
            points INTEGER,
            games INTEGER
        )
        """
    )
    for match_id, day in enumerate(("2026-10-01", "2026-10-03", "2026-10-05", "2026-10-07"), start=1):
        con.execute("INSERT INTO team_game_stats VALUES (?, 3, ?)", [match_id, day])

    active = [(1, 1, 0), (0, 1, 1), (1, 1, 0), (0, 1, 1)]
    ended = [(0, 1, 1), (1, 0, 1), (0, 2, 2), (0, 0, 0)]
    for idx, (goals, assists, points) in enumerate(active, start=1):
        con.execute(
            "INSERT INTO player_game_stats VALUES (?, 3, 10, 'Active Player', 10, 'FO', ?, ?, ?, 1)",
            [idx, goals, assists, points],
        )
    for idx, (goals, assists, points) in enumerate(ended, start=1):
        con.execute(
            "INSERT INTO player_game_stats VALUES (?, 3, 20, 'Ended Player', 20, 'FO', ?, ?, ?, 1)",
            [idx, goals, assists, points],
        )

    result = scoring_streaks(con, team_id=3, match_id=4)
    assert result["active"] == [
        {
            "player_id": 10,
            "player_name": "Active Player",
            "jersey": 10,
            "games": 4,
            "goals": 2,
            "assists": 4,
            "points": 4,
        }
    ]
    assert result["ended_this_game"] == [
        {
            "player_id": 20,
            "player_name": "Ended Player",
            "jersey": 20,
            "games": 3,
            "goals": 1,
            "assists": 3,
            "points": 4,
        }
    ]


def test_story_engine_prefers_sendable_augsburg_style_facts():
    ebb = {
        "corsi_5v5_for": 53,
        "corsi_5v5_against": 42,
        "slot_attempts_5v5_for": 10,
        "slot_attempts_5v5_against": 10,
        "goals_for": 2,
        "shots_on_goal_for": 26,
    }
    lineups = {
        "rotation": {
            "dropped_p3_forward_trios": [
                {"label": "Ronning – Kirk – Tiffels"},
                {"label": "Eder – Foudy – Pföderl"},
                {"label": "Wiederer – Griva – Hördler"},
            ],
            "new_p3_forward_trios": [
                {
                    "label": "Wiederer – Pföderl – Tiffels",
                    "p3_s": 174,
                    "p3_appearances": 6,
                },
                {
                    "label": "Eder – Foudy – Hördler",
                    "p3_s": 83,
                    "p3_appearances": 3,
                },
            ],
        }
    }
    previous_lineup = {
        "available": True,
        "previous_match": {"opponent_name": "Krefeld Pinguine"},
        "players_in": [],
        "players_out": [],
        "forwards": {"stable": ["A", "B"], "new": ["C", "D"], "dropped": ["E", "F"], "current_count": 4, "previous_count": 4},
        "defense": {"stable": ["G", "H", "I"], "new": [], "dropped": [], "current_count": 3, "previous_count": 3},
    }
    insight = {
        "ebb": {
            "summary": {"xg_sum": 2.71},
            "players": [
                {"player_name": "Frederik Tiffels", "xg_sum": 0.53, "goals": 0},
                {"player_name": "Manuel Wiederer", "xg_sum": 0.43, "goals": 1},
            ],
        },
        "opponent": {"summary": {"xg_sum": 2.30}, "players": []},
    }
    shots = []
    for second in (100, 140, 180, 220, 260, 300, 340, 380):
        shots.append({"game_time_s": second, "team_id": 3})
    for second in (160, 360):
        shots.append({"game_time_s": second, "team_id": 13})
    shots += [{"game_time_s": 1200 + idx * 40, "team_id": 3 if idx % 2 == 0 else 13} for idx in range(8)]

    scoring_summary = [
        {
            "team_id": 3,
            "scorer": {"name": "Yannick Veilleux"},
            "assists": [{"name": "Jonas Müller"}, {"name": "Kai Wissmann"}],
        },
        {
            "team_id": 3,
            "scorer": {"name": "Manuel Wiederer"},
            "assists": [{"name": "Liam Kirk"}, {"name": "Leonhard Pföderl"}],
        },
    ]

    facts, groups = build_story_facts(
        ebb=ebb,
        lineups=lineups,
        previous_lineup=previous_lineup,
        streaks={"active": [], "ended_this_game": []},
        advanced={},
        game_insight=insight,
        shots=shots,
        scoring_summary=scoring_summary,
        focus_team_id=3,
        opponent_team_id=13,
        opponent_name="Augsburger Panther",
        opponent_label="AEV",
    )

    assert 4 <= len(facts) <= 8
    assert any("Umbau im Schlussdrittel" in fact for fact in facts)
    assert any("Mehr Schussvolumen als klare Chancenüberlegenheit" in fact for fact in facts)
    assert any("Frederik Tiffels" in fact and "0,53 xG" in fact for fact in facts)
    assert any(group["title"] == "🔥 Aktuelle Story" for group in groups)
    assert any(group["title"] == "🔄 Lineup & Reihen" for group in groups)
    assert any(group["title"] == "🔬 Nerd Fact" for group in groups)
