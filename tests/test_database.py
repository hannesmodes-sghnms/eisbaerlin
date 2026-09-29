import json
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
from delstats.database import build_match_database


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
    finally:
        con.close()
