import json
from pathlib import Path

from delstats.discovery import (
    SeasonDiscoverer,
    classify_match_keys,
    normalize_match,
)
from delstats.s3 import S3Object


FIXTURES = Path(__file__).parent / "fixtures"


class FakeBucket:
    def list_objects(self, prefix: str):
        if prefix == "league-team-matches/2026/1/":
            return [
                S3Object("league-team-matches/2026/1/1.json"),
                S3Object("league-team-matches/2026/1/2.json"),
            ]
        if prefix == "matches/9001/":
            return [
                S3Object("matches/9001/game-header.json"),
                S3Object("matches/9001/period-events.json"),
                S3Object("matches/9001/faceoffs.json"),
                S3Object("matches/9001/shifts-v2.json"),
                S3Object("matches/9001/team-stats/1.json"),
                S3Object("matches/9001/team-stats/2.json"),
            ]
        return []


class FakeHttp:
    def get_json(self, url: str):
        filename = url.rsplit("/", 1)[-1]
        fixture = FIXTURES / f"schedule_team_{filename}"
        return json.loads(fixture.read_text(encoding="utf-8"))

    def get(self, url: str, **kwargs):
        class Response:
            status_code = 206
        return Response()


def test_normalize_match():
    raw = {
        "id": "42",
        "start_date": "2026-09-20 14:00:00",
        "home": {"id": 7, "name": "Home"},
        "guest": {"id": 8, "name": "Away"},
    }
    result = normalize_match(raw, "schedule.json")
    assert result is not None
    assert result.match_id == 42
    assert result.home_team_id == 7
    assert result.away_team_id == 8


def test_discover_season_deduplicates_matches():
    discoverer = SeasonDiscoverer(bucket=FakeBucket(), http=FakeHttp())
    result = discoverer.discover_season(2026, 1)

    assert result.team_ids == [1, 2]
    assert [m.match_id for m in result.matches] == [9001, 9002]
    game = result.matches[0]
    assert len(game.source_schedule_keys) == 2


def test_match_resource_classification_handles_shift_suffixes():
    discoverer = SeasonDiscoverer(bucket=FakeBucket(), http=FakeHttp())
    result = discoverer.discover_match_resources(9001, verify_shots=True)

    assert result.resources["shifts"] == ["matches/9001/shifts-v2.json"]
    assert result.resources["faceoffs"] == ["matches/9001/faceoffs.json"]
    assert len(result.resources["team_stats"]) == 2
    assert result.shot_key == "visualization/shots/9001.json"
    assert result.shot_exists is True


def test_classify_unknown_resource():
    resources = classify_match_keys(["matches/12/something-new.json"], 12)
    assert resources["other"] == ["matches/12/something-new.json"]
