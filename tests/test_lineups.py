from delstats.lineups import analyze_5v5_lineups


def _add_interval(shifts, start, end, focus_ids, opp_ids):
    for pid in focus_ids:
        shifts.append({"team_id": 3, "player_id": pid, "start_time_s": start, "end_time_s": end})
    for pid in opp_ids:
        shifts.append({"team_id": 7, "player_id": pid, "start_time_s": start, "end_time_s": end})


def test_detects_shortened_p3_rotation():
    players = []
    for pid in range(1, 13):
        players.append({"team_id": 3, "player_id": pid, "full_name": f"F{pid}", "last_name": f"F{pid}", "jersey": pid, "position": "FO"})
    players += [
        {"team_id": 3, "player_id": 21, "full_name": "D1", "last_name": "D1", "jersey": 21, "position": "DE"},
        {"team_id": 3, "player_id": 22, "full_name": "D2", "last_name": "D2", "jersey": 22, "position": "DE"},
    ]
    opp_ids = [101, 102, 103, 104, 105]
    players += [
        {"team_id": 7, "player_id": pid, "full_name": f"O{pid}", "last_name": f"O{pid}", "jersey": pid, "position": "FO" if i < 3 else "DE"}
        for i, pid in enumerate(opp_ids)
    ]
    shifts = []
    lines = [(1,2,3),(4,5,6),(7,8,9),(10,11,12)]
    # P1/P2: four lines, each used for 60 seconds.
    t = 0
    for period_start in (0, 1200):
        t = period_start
        for line in lines:
            _add_interval(shifts, t, t+60, list(line)+[21,22], opp_ids)
            t += 60
    # P3: only the first three lines rotate; line 4 is cut.
    t = 2400
    for line in lines[:3]:
        _add_interval(shifts, t, t+60, list(line)+[21,22], opp_ids)
        t += 60

    result = analyze_5v5_lineups(shifts, players, focus_team_id=3, opponent_team_id=7)
    rotation = result["rotation"]
    assert rotation["active_forwards"]["p1"] == 12
    assert rotation["active_forwards"]["p3"] == 9
    assert rotation["shortened_bank_detected"] is True
    assert rotation["top9_forward_share_p3_pct"] == 100.0
    assert result["forward_trios"][0]["total_s"] >= 180


def test_line_matching_and_midgame_change_detection():
    players = []
    for pid in range(1, 7):
        players.append({"team_id": 3, "player_id": pid, "full_name": f"F{pid}", "last_name": f"F{pid}", "jersey": pid, "position": "FO"})
    players += [
        {"team_id": 3, "player_id": 21, "full_name": "D1", "last_name": "D1", "jersey": 21, "position": "DE"},
        {"team_id": 3, "player_id": 22, "full_name": "D2", "last_name": "D2", "jersey": 22, "position": "DE"},
    ]
    for pid in range(101, 107):
        players.append({"team_id": 7, "player_id": pid, "full_name": f"O{pid}", "last_name": f"O{pid}", "jersey": pid, "position": "FO"})
    players += [
        {"team_id": 7, "player_id": 121, "full_name": "OD1", "last_name": "OD1", "jersey": 21, "position": "DE"},
        {"team_id": 7, "player_id": 122, "full_name": "OD2", "last_name": "OD2", "jersey": 22, "position": "DE"},
    ]

    shifts = []
    # P1: regular line 1 against opponent line A for 90s.
    _add_interval(shifts, 0, 90, [1, 2, 3, 21, 22], [101, 102, 103, 121, 122])
    # P2: EBB changes one forward and keeps that unit for one full 50s shift.
    _add_interval(shifts, 1200, 1250, [1, 2, 4, 21, 22], [104, 105, 106, 121, 122])

    result = analyze_5v5_lineups(shifts, players, focus_team_id=3, opponent_team_id=7)
    assert result["coverage"]["forward_stable_pct"] == 100.0
    assert result["forward_matchups"][0]["total_s"] == 90
    assert any(
        row["kind"] == "forward" and row["period"] == 2 and row["change_type"] == "introduced"
        for row in result["lineup_changes"]
    )
