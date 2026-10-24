import pytest

duckdb = pytest.importorskip("duckdb")

from delstats.story_facts import (
    StoryFact,
    _pair_unit_changes,
    build_story_facts,
    scoring_streaks,
    select_story_facts,
)


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

    active = [(1, 1, 2), (0, 1, 1), (1, 1, 2), (0, 1, 1)]
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
            "points": 6,
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
                {
                    "label": "Ronning – Kirk – Tiffels",
                    "player_ids": [2209, 3410, 1402],
                    "p1_s": 188,
                    "p2_s": 265,
                    "appearances": 10,
                },
                {
                    "label": "Eder – Foudy – Pföderl",
                    "player_ids": [546, 4895, 92],
                    "p1_s": 89,
                    "p2_s": 173,
                    "appearances": 8,
                },
                {
                    "label": "Wiederer – Griva – Hördler",
                    "player_ids": [1823, 4310, 2126],
                    "p1_s": 149,
                    "p2_s": 106,
                    "appearances": 6,
                },
            ],
            "new_p3_forward_trios": [
                {
                    "label": "Wiederer – Pföderl – Tiffels",
                    "player_ids": [1823, 92, 1402],
                    "p3_s": 174,
                    "p3_appearances": 6,
                },
                {
                    "label": "Eder – Foudy – Hördler",
                    "player_ids": [546, 4895, 2126],
                    "p3_s": 83,
                    "p3_appearances": 3,
                },
                {
                    "label": "Ronning – Vikingstad – Kirk",
                    "player_ids": [2209, 1796, 3410],
                    "p3_s": 69,
                    "p3_appearances": 2,
                },
            ],
        }
    }
    previous_lineup = {
        "available": True,
        "previous_match": {"opponent_name": "Krefeld Pinguine"},
        "players_in": [],
        "players_out": [],
        "forwards": {
            "previous": ["Old 1", "Old 2", "Stable 3"],
            "current": ["New 1", "New 2", "Stable 3"],
            "previous_units": [
                {"label": "Old 1", "player_ids": [1, 2, 3], "total_s": 600},
                {"label": "Old 2", "player_ids": [4, 5, 6], "total_s": 500},
                {"label": "Stable 3", "player_ids": [7, 8, 9], "total_s": 400},
            ],
            "current_units": [
                {"label": "New 1", "player_ids": [1, 2, 10], "total_s": 590},
                {"label": "New 2", "player_ids": [4, 11, 12], "total_s": 480},
                {"label": "Stable 3", "player_ids": [7, 8, 9], "total_s": 410},
            ],
            "stable": ["Stable 3"],
            "new": ["New 1", "New 2"],
            "dropped": ["Old 1", "Old 2"],
            "current_count": 3,
            "previous_count": 3,
        },
        "defense": {
            "previous": ["Old D1", "Old D2"],
            "current": ["New D1", "New D2"],
            "previous_units": [
                {"label": "Old D1", "player_ids": [21, 22], "total_s": 700},
                {"label": "Old D2", "player_ids": [23, 24], "total_s": 550},
            ],
            "current_units": [
                {"label": "New D1", "player_ids": [23, 24], "total_s": 680},
                {"label": "New D2", "player_ids": [21, 22], "total_s": 500},
            ],
            "stable": [],
            "new": ["New D1", "New D2"],
            "dropped": ["Old D1", "Old D2"],
            "current_count": 2,
            "previous_count": 2,
        },
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

    assert 4 <= len(facts) <= 12
    assert any(
        "Umbau im Schlussdrittel" in fact
        and "Ronning – Kirk – Tiffels → Ronning – Vikingstad – Kirk" in fact
        and "Eder – Foudy – Pföderl → Eder – Foudy – Hördler" in fact
        for fact in facts
    )
    assert any(
        "Sturmreihen gegenüber Krefeld Pinguine" in fact
        and "Old 1 → New 1" in fact
        and "Old 2 → New 2" in fact
        for fact in facts
    )
    assert any("Mehr Schussvolumen als klare Chancenüberlegenheit" in fact for fact in facts)
    assert any("Frederik Tiffels" in fact and "0,53 xG" in fact for fact in facts)
    assert any(group["title"] == "🔥 Aktuelle Story" for group in groups)
    assert any(group["title"] == "🔄 Lineup & Reihen" for group in groups)
    assert any(group["title"] == "🔬 Nerd Fact" for group in groups)
    lineup_group = next(group for group in groups if group["title"] == "🔄 Lineup & Reihen")
    assert any(
        "Verteidigerpaare gegenüber Krefeld Pinguine" in fact
        and "Old D1 → New D1" in fact
        and "Old D2 → New D2" in fact
        for fact in lineup_group["facts"]
    )



def test_story_selection_can_fill_twelve_fact_slots():
    categories = ("current_story", "lineup", "form", "nerd")
    candidates = []
    for category in categories:
        for idx in range(3):
            candidates.append(
                StoryFact(
                    category=category,
                    score=100 - idx,
                    kind=f"{category}_{idx}",
                    text=f"{category} fact {idx}",
                )
            )

    facts, groups = select_story_facts(candidates)

    assert len(facts) == 12
    assert sum(len(group["facts"]) for group in groups) == 12



def test_forward_pairing_prefers_two_player_overlap_but_not_single_player_overlap():
    previous = [
        {"label": "Old 1", "player_ids": [1, 2, 3], "total_s": 600},
        {"label": "Old 2", "player_ids": [4, 5, 6], "total_s": 500},
        {"label": "Old 3", "player_ids": [7, 8, 9], "total_s": 400},
    ]
    current = [
        {"label": "New 1", "player_ids": [1, 2, 10], "total_s": 550},
        {"label": "New 2", "player_ids": [7, 11, 12], "total_s": 450},
        {"label": "New 3", "player_ids": [4, 13, 14], "total_s": 350},
    ]

    pairs = _pair_unit_changes(
        previous,
        current,
        previous_toi_keys=("total_s",),
        current_toi_keys=("total_s",),
        prefer_overlap=True,
    )

    assert [
        (pair["previous"]["label"], pair["current"]["label"])
        for pair in pairs
    ] == [
        ("Old 1", "New 1"),
        ("Old 2", "New 2"),
        ("Old 3", "New 3"),
    ]
    assert pairs[0]["overlap"] == 2
    assert pairs[1]["overlap"] == 0
    assert pairs[2]["overlap"] == 0


def test_defense_pairing_uses_toi_rank_even_when_player_overlap_points_elsewhere():
    previous = [
        {"label": "Old D1", "player_ids": [1, 2], "total_s": 700},
        {"label": "Old D2", "player_ids": [3, 4], "total_s": 500},
    ]
    current = [
        {"label": "New D1", "player_ids": [3, 4], "total_s": 650},
        {"label": "New D2", "player_ids": [1, 2], "total_s": 450},
    ]

    pairs = _pair_unit_changes(
        previous,
        current,
        previous_toi_keys=("total_s",),
        current_toi_keys=("total_s",),
        prefer_overlap=False,
    )

    assert [
        (pair["previous"]["label"], pair["current"]["label"])
        for pair in pairs
    ] == [
        ("Old D1", "New D1"),
        ("Old D2", "New D2"),
    ]
