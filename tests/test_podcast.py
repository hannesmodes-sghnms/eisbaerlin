import json
from datetime import date

from delstats.podcast import format_duration, upcoming_matchups


def test_format_duration_uses_total_minutes_like_podcast_sheet():
    assert format_duration(221 * 60 + 17) == "221:17"


def test_upcoming_matchups_filters_before_match_window(tmp_path):
    path = tmp_path / "season.json"
    path.write_text(json.dumps({"matches": [
        {"match_id": 1, "start_date": "2026-09-27 14:00:00", "status": "AFTER_MATCH"},
        {"match_id": 2, "start_date": "2026-10-01 19:30:00", "status": "BEFORE_MATCH"},
        {"match_id": 3, "start_date": "2026-10-10 19:30:00", "status": "BEFORE_MATCH"},
    ]}), encoding="utf-8")
    result = upcoming_matchups(season_json=path, today=date(2026, 9, 29), days=7)
    assert [m["match_id"] for m in result] == [2]
