from delstats.transform import (
    SHOT_RESULT_MAP,
    faceoff_zone_for_team,
    flatten_period_events,
    previous_faceoff,
    resolve_on_ice_pair,
)


def _shift(team, player, start, end):
    return {
        "player": {"id": player, "name": str(player)},
        "team": {"id": team, "name": str(team)},
        "startTime": {"time": start},
        "endTime": {"time": end},
    }


def test_shot_result_mapping():
    assert SHOT_RESULT_MAP[1] == "on_goal"
    assert SHOT_RESULT_MAP[4] == "goal"


def test_faceoff_zone_is_relative_to_team_side():
    assert faceoff_zone_for_team("ADL", team_id=3, home_team_id=3) == "offensive"
    assert faceoff_zone_for_team("ADL", team_id=7, home_team_id=3) == "defensive"
    assert faceoff_zone_for_team("HDL", team_id=3, home_team_id=3) == "defensive"
    assert faceoff_zone_for_team("HDL", team_id=7, home_team_id=3) == "offensive"
    assert faceoff_zone_for_team("C", team_id=3, home_team_id=3) == "neutral"


def test_previous_faceoff_uses_latest_at_or_before_shot():
    faceoffs = [
        {"id": 1, "time": 100},
        {"id": 2, "time": 130},
        {"id": 3, "time": 180},
    ]
    assert previous_faceoff(faceoffs, 129)["id"] == 1
    assert previous_faceoff(faceoffs, 130)["id"] == 2
    assert previous_faceoff(faceoffs, 99) is None


def test_on_ice_pair_uses_symmetric_boundary_fallback():
    shifts = [
        _shift(3, 101, 10, 20),
        _shift(3, 102, 10, 20),
        _shift(3, 103, 10, 20),
        _shift(3, 104, 10, 21),
        _shift(3, 105, 10, 21),
        _shift(7, 201, 10, 20),
        _shift(7, 202, 10, 20),
        _shift(7, 203, 10, 21),
        _shift(7, 204, 10, 21),
        _shift(7, 205, 10, 21),
    ]
    home, away, home_method, away_method = resolve_on_ice_pair(
        shifts, team_a_id=3, team_b_id=7, game_time_s=20
    )
    assert home == [101, 102, 103, 104, 105]
    assert away == [201, 202, 203, 204, 205]
    assert home_method == "boundary_adjusted"
    assert away_method == "boundary_adjusted"


def test_flatten_period_events_keeps_game_order():
    payload = {
        "1": [{"time": 0, "type": "periodStart"}],
        "2": [{"time": 1200, "type": "periodStart"}],
        "3": [{"time": 2400, "type": "periodStart"}],
        "overtime": [],
        "shootout": [],
    }
    rows = flatten_period_events(payload)
    assert [r["period_key"] for r in rows] == ["1", "2", "3"]
    assert [r["sequence"] for r in rows] == [1, 2, 3]
