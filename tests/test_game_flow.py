from delstats.game_flow import build_game_flow


def _players():
    return [
        *[
            {"team_id": 3, "player_id": pid, "position": "FO"}
            for pid in range(1, 7)
        ],
        *[
            {"team_id": 9, "player_id": pid, "position": "FO"}
            for pid in range(11, 17)
        ],
    ]


def test_game_flow_builds_positive_and_opponent_density_and_goal_marker():
    shots = [
        {"game_time_s": 100, "team_id": 3},
        {"game_time_s": 120, "team_id": 3},
        {"game_time_s": 200, "team_id": 9},
    ]
    shifts = []
    goals = [
        {
            "time_s": 120,
            "team_id": 3,
            "team_abbr": "EBB",
            "score": "1:0",
            "balance": "EQ",
            "scorer": {"name": "Test Player"},
        }
    ]

    flow = build_game_flow(
        shots,
        shifts,
        _players(),
        goals,
        focus_team_id=3,
        opponent_team_id=9,
        step_s=15,
        sigma_s=45,
    )

    assert flow["method"] == "gaussian_shot_attempt_density"
    assert flow["game_end_s"] == 3600
    assert max(row["ebb"] for row in flow["points"]) > 0
    assert max(row["opponent"] for row in flow["points"]) > 0
    assert flow["goals"][0]["scorer"] == "Test Player"
    assert flow["goals"][0]["side"] == "ebb"


def test_powerplay_is_reconstructed_from_skater_counts():
    players = _players()
    shifts = []
    # EBB: five skaters for the full window.
    for pid in range(1, 6):
        shifts.append({"team_id": 3, "player_id": pid, "start_time_s": 0, "end_time_s": 180})
    # Opponent: five skaters, but one leaves from 60-120.
    for pid in range(11, 15):
        shifts.append({"team_id": 9, "player_id": pid, "start_time_s": 0, "end_time_s": 180})
    shifts.extend(
        [
            {"team_id": 9, "player_id": 15, "start_time_s": 0, "end_time_s": 60},
            {"team_id": 9, "player_id": 15, "start_time_s": 120, "end_time_s": 180},
        ]
    )

    flow = build_game_flow(
        [],
        shifts,
        players,
        [],
        focus_team_id=3,
        opponent_team_id=9,
    )

    assert flow["powerplays"] == [
        {"team_id": 3, "start_s": 60, "end_s": 120, "side": "ebb"}
    ]


def test_empty_net_six_on_five_is_not_powerplay():
    players = _players()
    shifts = []
    for pid in range(1, 7):
        shifts.append({"team_id": 3, "player_id": pid, "start_time_s": 0, "end_time_s": 120})
    for pid in range(11, 16):
        shifts.append({"team_id": 9, "player_id": pid, "start_time_s": 0, "end_time_s": 120})

    flow = build_game_flow(
        [],
        shifts,
        players,
        [],
        focus_team_id=3,
        opponent_team_id=9,
    )

    assert flow["powerplays"] == []
