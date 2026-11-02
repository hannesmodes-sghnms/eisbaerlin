import json

from delstats.dashboard import _data_quality_by_team, extract_upcoming_games


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



def test_data_quality_flags_only_affected_teams(tmp_path):
    discovery = {
        "matches": [
            {
                "match_id": 4486,
                "home_team_id": 15,
                "away_team_id": 5,
            },
            {
                "match_id": 4487,
                "home_team_id": 8,
                "away_team_id": 13,
            },
        ]
    }
    quality = {
        "integrity": {
            "warnings": [
                {
                    "code": "shot_player_reference",
                    "match_id": 4486,
                    "team_id": 5,
                    "details": {"shot_id": 123, "player_id": 456},
                },
                {
                    "code": "goal_balance_attendant_disagreement",
                    "match_id": 4486,
                    "team_id": 15,
                },
            ],
            "hard_failures": [],
        },
        "pipeline": {
            "import_errors": [
                {"match_id": 4487, "error": "raw data incomplete"},
            ]
        },
    }
    discovery_path = tmp_path / "discovery.json"
    quality_path = tmp_path / "quality.json"
    discovery_path.write_text(json.dumps(discovery), encoding="utf-8")
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    result = _data_quality_by_team(quality_path, discovery_path)

    assert result[5]["warning"] is True
    assert result[5]["codes"] == ["shot_player_reference"]
    assert result[5]["match_ids"] == [4486]
    assert 15 not in result
    assert result[8]["codes"] == ["raw_data_incomplete"]
    assert result[13]["codes"] == ["raw_data_incomplete"]
