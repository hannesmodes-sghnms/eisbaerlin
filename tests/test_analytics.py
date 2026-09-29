from delstats.analytics import _state_durations


def test_state_durations_for_4411_like_score_progression():
    events = {
        "1": [{"time": 835, "type": "goal", "data": {"currentScore": "1:0"}}],
        "2": [
            {"time": 1265, "type": "goal", "data": {"currentScore": "2:0"}},
            {"time": 2022, "type": "goal", "data": {"currentScore": "3:0"}},
            {"time": 2365, "type": "goal", "data": {"currentScore": "4:0"}},
        ],
        "3": [],
    }
    result = _state_durations(events, 3600)
    assert result["home"] == {"leading": 2765, "tied": 835, "trailing": 0}
    assert result["visitor"] == {"leading": 0, "tied": 835, "trailing": 2765}
