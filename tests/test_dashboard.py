from delstats.dashboard import extract_upcoming_games


def test_extracts_next_three_ebb_games_only():
    payload = {
        "matches": [
            {"match_id": 1, "start_date": "2026-09-27 14:00:00", "status": "AFTER_MATCH", "home_team_id": 3, "home_team_name": "EBB", "away_team_id": 7, "away_team_name": "IEC"},
            {"match_id": 2, "start_date": "2026-10-01 19:30:00", "status": "BEFORE_MATCH", "home_team_id": 2, "home_team_name": "MAN", "away_team_id": 7, "away_team_name": "IEC"},
            {"match_id": 3, "start_date": "2026-10-02 19:30:00", "status": "BEFORE_MATCH", "home_team_id": 44, "home_team_name": "FRA", "away_team_id": 3, "away_team_name": "EBB"},
            {"match_id": 4, "start_date": "2026-10-04 14:00:00", "status": "BEFORE_MATCH", "home_team_id": 3, "home_team_name": "EBB", "away_team_id": 14, "away_team_name": "NIT"},
            {"match_id": 5, "start_date": "2026-10-09 19:30:00", "status": "BEFORE_MATCH", "home_team_id": 3, "home_team_name": "EBB", "away_team_id": 8, "away_team_name": "WOB"},
            {"match_id": 6, "start_date": "2026-10-10 19:30:00", "status": "BEFORE_MATCH", "home_team_id": 3, "home_team_name": "EBB", "away_team_id": 1, "away_team_name": "ING"},
        ]
    }
    result = extract_upcoming_games(payload, focus_team_id=3, limit=3)
    assert [row["match_id"] for row in result] == [3, 4, 5]
    assert result[0]["ebb_home"] is False
    assert result[0]["opponent_name"] == "FRA"
    assert result[1]["ebb_home"] is True
