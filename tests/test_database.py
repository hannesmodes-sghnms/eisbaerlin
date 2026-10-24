import json
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
from delstats.database import (
    _goal_event_contexts,
    _goal_event_context_by_shot_id,
    build_match_database,
)
from delstats.quality import audit_database


def _write(path: Path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_match_database_end_to_end(tmp_path):
    match_dir = tmp_path / "999"
    match_dir.mkdir()
    _write(match_dir / "game-header.json", {
        "actualTimeName": "Ende",
        "stadium": "Test Arena",
        "numberOfViewers": 100,
        "teamInfo": {
            "home": {"id": 3, "name": "Home", "shortcut": "HOM"},
            "visitor": {"id": 7, "name": "Away", "shortcut": "AWY"},
        },
        "results": {
            "extra_time": False,
            "shooting": False,
            "score": {"final": {"score_home": 1, "score_guest": 0}},
        },
        "lastEventTime": 60,
    })
    roster = {"home": {}, "visitor": {}}
    for side, base in (("home", 100), ("visitor", 200)):
        for i in range(1, 4):
            pid = base + i
            roster[side][str(300 + i)] = {
                "playerId": pid,
                "matchPlayerId": 1000 + pid,
                "name": side,
                "surname": str(i),
                "jersey": i,
                "position": "FO",
                "captain": False,
                "startingSix": True,
                "roster": str(300 + i),
            }
    _write(match_dir / "roster.json", roster)
    shifts = []
    shift_id = 1
    for team, base in ((3, 100), (7, 200)):
        for i in range(1, 4):
            shifts.append({
                "id": shift_id,
                "startTime": {"time": 0, "realtime": "2026-09-01 12:00:00"},
                "endTime": {"time": 60, "realtime": "2026-09-01 12:01:00"},
                "player": {"id": base + i, "name": f"P{base+i}"},
                "team": {"id": team, "name": str(team)},
            })
            shift_id += 1
    _write(match_dir / "shiftsTEST.json", shifts)
    _write(match_dir / "shots.json", {
        "match": {
            "id": "999",
            "date": "2026-09-01",
            "home_id": 3,
            "home_name": "H",
            "visitor_id": 7,
            "visitor_name": "A",
            "shots": [{
                "id": 9001,
                "player_id": 101,
                "jersey": 1,
                "first_name": "home",
                "last_name": "1",
                "team_id": 3,
                "match_shot_resutl_id": 1,
                "coordinate_x": 10.0,
                "coordinate_y": 5.0,
                "real_date": "2026-09-01 12:00:10",
                "polygon": False,
                "time": 10,
            }],
        }
    })
    _write(match_dir / "faceoffs.json", [{
        "id": 8001,
        "time": 5,
        "realtime": "2026-09-01 12:00:05",
        "position": "HOME_DEFENSIVE_LEFT",
        "positionShortcut": "HDL",
        "winner": {"id": 101, "name": "home 1"},
        "losser": {"id": 201, "name": "away 1"},
    }])
    _write(match_dir / "period-events.json", {
        "1": [{"time": 0, "type": "periodStart"}],
        "2": [],
        "3": [],
        "overtime": [],
        "shootout": [],
    })
    (match_dir / "team-stats").mkdir()
    for team, base, shortcut in ((3, 100, "HOM"), (7, 200, "AWY")):
        payload = []
        for i in range(1, 4):
            payload.append({
                "id": base + i,
                "name": f"P{base+i}",
                "firstname": "P",
                "surname": str(base+i),
                "position": "DE" if i == 1 else "FO",
                "jersey": i,
                "statistics": {
                    "teamShortcut": shortcut,
                    "games": 1,
                    "goals": {"home": 0, "away": 0},
                    "assists": {"home": 0, "away": 0},
                    "points": {"home": 0, "away": 0},
                },
            })
        _write(match_dir / "team-stats" / f"{team}.json", payload)

    db_path = tmp_path / "test.duckdb"
    summary = build_match_database(match_dir=match_dir, db_path=db_path)
    assert summary["shots"] == 1
    assert summary["shift_file"] == "shiftsTEST.json"

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT manpower, seconds_since_faceoff, previous_faceoff_zone_for_shooting_team FROM shot_log"
        ).fetchone()
        assert row == ("3v3", 5, "defensive")
        assert con.execute("SELECT count(*) FROM shot_on_ice").fetchone()[0] == 6
        assert con.execute("SELECT count(*) FROM event_log").fetchone()[0] == 3
        row = con.execute(
            """
            SELECT shot_id, game_time_s, team_id AS shooting_team_id, seconds_since_faceoff
            FROM shot_log
            WHERE dzone_faceoff_to_shot_10s
            """
        ).fetchone()
        assert row == (9001, 10, 3, 5)
        geom = con.execute("SELECT shot_x_m, shot_y_m, shot_zone FROM shots").fetchone()
        assert geom[0] == pytest.approx(3.048)
        assert geom[1] == pytest.approx(0.762)
        assert geom[2] == "NEUTRAL_ZONE"
        assert con.execute("SELECT count(*) FROM team_game_stats").fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM team_season_stats").fetchone()[0] == 2
        audit = audit_database(con)
        assert any(issue["code"] == "final_score_vs_events" for issue in audit["hard_failures"])
    finally:
        con.close()



def test_goal_event_attendants_override_shift_boundary_context():
    period_events = {
        "2": [
            {
                "time": 2062,
                "type": "goal",
                "data": {
                    "team": "home",
                    "balance": "EQ",
                    "scorer": {"playerId": 10},
                    "attendants": {
                        "positive": [
                            *[{"playerId": pid} for pid in (10, 11, 12, 13, 14)],
                            {"playerId": 30},
                        ],
                        "negative": [
                            *[{"playerId": pid} for pid in (20, 21, 22, 23, 24)],
                            {"playerId": 40},
                        ],
                    },
                },
            }
        ],
        "1": [],
        "3": [],
        "overtime": [],
        "shootout": [],
    }
    contexts = _goal_event_contexts(
        period_events,
        home_team_id=3,
        away_team_id=13,
        goalie_ids={30, 40},
    )
    assert contexts == [
        {
            "time_s": 2062,
            "team_id": 3,
            "scorer_player_id": 10,
            "on_for": [10, 11, 12, 13, 14],
            "on_against": [20, 21, 22, 23, 24],
        }
    ]

    # The pairing is deliberately independent of a fixed time tolerance and
    # scorer equality. DEL examples exist with >30s timestamp drift and with a
    # shot-feed shooter who differs from the officially credited scorer.
    shots = [
        {
            "id": 9001,
            "time": 2031,
            "team_id": 3,
            "player_id": 99,
            "match_shot_resutl_id": 4,
        }
    ]
    mapping = _goal_event_context_by_shot_id(shots, contexts)
    assert mapping[9001]["time_s"] == 2062
    assert len(mapping[9001]["on_for"]) == 5
    assert len(mapping[9001]["on_against"]) == 5


def test_goal_event_context_mapping_refuses_count_mismatch():
    contexts = [
        {
            "time_s": 100,
            "team_id": 3,
            "scorer_player_id": 10,
            "on_for": [1, 2, 3, 4, 5],
            "on_against": [11, 12, 13, 14, 15],
        },
        {
            "time_s": 200,
            "team_id": 3,
            "scorer_player_id": 20,
            "on_for": [1, 2, 3, 4, 5],
            "on_against": [11, 12, 13, 14, 15],
        },
    ]
    shots = [
        {"id": 1, "time": 99, "team_id": 3, "player_id": 10, "match_shot_resutl_id": 4}
    ]
    assert _goal_event_context_by_shot_id(shots, contexts) == {}

