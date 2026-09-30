from delstats.advanced import (
    annotate_forward_matchups,
    player_impact_5v5_from_shots,
    score_state_corsi_5v5,
    scoring_summary_from_events,
    zone_starts_5v5,
)


def test_scoring_summary_keeps_ordered_assists():
    raw = {
        "data": {
            "currentScore": "2:0",
            "balance": "EQ",
            "scorer": {"playerId": 1, "jersey": 9, "name": "A", "surname": "Scorer"},
            "assistants": [
                {"playerId": 2, "jersey": 10, "name": "B", "surname": "Primary"},
                {"playerId": 3, "jersey": 11, "name": "C", "surname": "Secondary"},
            ],
        }
    }
    rows = scoring_summary_from_events(
        [{"event_type": "goal", "game_time_s": 123, "team_id": 3, "balance": "EQ", "raw_json": raw}],
        focus_team_id=3,
        opponent_team_id=7,
        focus_abbr="EBB",
        opponent_abbr="IEC",
    )
    assert rows[0]["primary_assist"]["name"] == "B Primary"
    assert rows[0]["secondary_assist"]["name"] == "C Secondary"


def test_player_impact_and_relative_corsi():
    players = [
        {"team_id": 3, "player_id": 1, "full_name": "One", "last_name": "One", "jersey": 1, "position": "FO"},
        {"team_id": 3, "player_id": 2, "full_name": "Two", "last_name": "Two", "jersey": 2, "position": "FO"},
    ]
    shots = [
        {"team_id": 3, "manpower": "5v5", "result": "on_goal", "on_ice_for_player_ids": [1], "on_ice_against_player_ids": []},
        {"team_id": 3, "manpower": "5v5", "result": "blocked", "on_ice_for_player_ids": [1], "on_ice_against_player_ids": []},
        {"team_id": 7, "manpower": "5v5", "result": "goal", "on_ice_for_player_ids": [], "on_ice_against_player_ids": [1]},
        {"team_id": 3, "manpower": "5v5", "result": "on_goal", "on_ice_for_player_ids": [2], "on_ice_against_player_ids": []},
        {"team_id": 7, "manpower": "5v5", "result": "on_goal", "on_ice_for_player_ids": [], "on_ice_against_player_ids": [2]},
    ]
    rows = {r["player_id"]: r for r in player_impact_5v5_from_shots(shots, players, focus_team_id=3)}
    assert rows[1]["cf"] == 2 and rows[1]["ca"] == 1
    assert rows[1]["ff"] == 1
    assert rows[1]["relative_cf_pct"] > 0


def test_score_state_uses_score_before_goal_shot():
    goals = [
        {"event_type": "goal", "game_time_s": 100, "raw_json": {"data": {"currentScore": "1:0"}}},
    ]
    shots = [
        {"shot_id": 1, "game_time_s": 50, "team_id": 3, "manpower": "5v5"},
        {"shot_id": 2, "game_time_s": 100, "team_id": 3, "manpower": "5v5"},
        {"shot_id": 3, "game_time_s": 101, "team_id": 7, "manpower": "5v5"},
    ]
    rows = {r["state"]: r for r in score_state_corsi_5v5(shots, goals, focus_team_id=3, focus_is_home=True)}
    assert rows["tied"]["cf"] == 2
    assert rows["leading"]["ca"] == 1


def test_zone_starts_are_deployment_not_faceoff_result():
    players = [
        *[{"team_id": 3, "player_id": pid, "last_name": f"F{pid}", "position": "FO", "jersey": pid} for pid in (1,2,3)],
        *[{"team_id": 3, "player_id": pid, "last_name": f"D{pid}", "position": "DE", "jersey": pid} for pid in (4,5)],
        *[{"team_id": 7, "player_id": pid, "last_name": f"O{pid}", "position": "FO" if pid < 103 else "DE", "jersey": pid} for pid in (100,101,102,103,104)],
    ]
    shifts = []
    for pid in (1,2,3,4,5): shifts.append({"team_id":3,"player_id":pid,"start_time_s":0,"end_time_s":100})
    for pid in (100,101,102,103,104): shifts.append({"team_id":7,"player_id":pid,"start_time_s":0,"end_time_s":100})
    faceoffs = [{"game_time_s":10,"position_shortcut":"ADL"}]
    result = zone_starts_5v5(shifts, players, faceoffs, focus_team_id=3, opponent_team_id=7, home_team_id=3)
    assert result["forward_units"][0]["oz"] == 1
    assert result["forward_units"][0]["dz"] == 0


def test_matchup_performance_counts_only_stable_interval():
    matchups = [{"ebb_label":"A-B-C","opponent_label":"X-Y-Z","intervals":[{"start_s":10,"end_s":20,"period":1}]}]
    shots = [
        {"game_time_s":11,"team_id":3,"manpower":"5v5","result":"on_goal","shot_zone":"SLOT"},
        {"game_time_s":12,"team_id":7,"manpower":"5v5","result":"goal","shot_zone":"SLOT"},
        {"game_time_s":21,"team_id":3,"manpower":"5v5","result":"goal","shot_zone":"SLOT"},
    ]
    row = annotate_forward_matchups(matchups, shots, focus_team_id=3)[0]
    assert (row["cf"], row["ca"]) == (1,1)
    assert (row["gf"], row["ga"]) == (0,1)
    assert "intervals" not in row

from delstats.advanced import stable_forward_matchup_performance


def test_stable_forward_matchup_performance_filters_rolling_change_fragments():
    players=[]
    for pid in (1,2,3): players.append({"team_id":3,"player_id":pid,"last_name":f"F{pid}","position":"FO","jersey":pid})
    for pid in (4,5): players.append({"team_id":3,"player_id":pid,"last_name":f"D{pid}","position":"DE","jersey":pid})
    for pid in (101,102,103): players.append({"team_id":7,"player_id":pid,"last_name":f"O{pid}","position":"FO","jersey":pid})
    for pid in (104,105): players.append({"team_id":7,"player_id":pid,"last_name":f"OD{pid}","position":"DE","jersey":pid})
    shifts=[]
    for pid in (1,2,3,4,5): shifts.append({"team_id":3,"player_id":pid,"start_time_s":0,"end_time_s":30})
    for pid in (101,102,103,104,105): shifts.append({"team_id":7,"player_id":pid,"start_time_s":0,"end_time_s":30})
    shots=[{"game_time_s":10,"team_id":3,"manpower":"5v5","result":"on_goal","shot_zone":"SLOT"}]
    rows=stable_forward_matchup_performance(shifts,players,shots,focus_team_id=3,opponent_team_id=7)
    assert rows[0]["total_s"]==30
    assert rows[0]["cf"]==1 and rows[0]["slot_for"]==1

from delstats.advanced import forward_matchup_report


def _matchup_players(include_mik=False):
    players = [
        {"team_id": 3, "player_id": 1, "full_name": "A One", "last_name": "One", "jersey": 1, "position": "FO"},
        {"team_id": 3, "player_id": 2, "full_name": "B Two", "last_name": "Two", "jersey": 2, "position": "FO"},
        {"team_id": 3, "player_id": 3, "full_name": "C Three", "last_name": "Three", "jersey": 3, "position": "FO"},
        {"team_id": 3, "player_id": 4, "full_name": "D Four", "last_name": "Four", "jersey": 4, "position": "DE"},
        {"team_id": 3, "player_id": 5, "full_name": "E Five", "last_name": "Five", "jersey": 5, "position": "DE"},
        {"team_id": 3, "player_id": 6, "full_name": "Goalie", "last_name": "Goalie", "jersey": 30, "position": "GK"},
    ]
    if include_mik:
        players = [row for row in players if row["player_id"] != 3]
        players.append({"team_id": 3, "player_id": 1425, "full_name": "Eric Mik", "last_name": "Mik", "jersey": 12, "position": "DE"})
    players += [
        {"team_id": 7, "player_id": 101, "full_name": "O One", "last_name": "O1", "jersey": 11, "position": "FO"},
        {"team_id": 7, "player_id": 102, "full_name": "O Two", "last_name": "O2", "jersey": 12, "position": "FO"},
        {"team_id": 7, "player_id": 103, "full_name": "O Three", "last_name": "O3", "jersey": 13, "position": "FO"},
        {"team_id": 7, "player_id": 104, "full_name": "OD Four", "last_name": "OD4", "jersey": 14, "position": "DE"},
        {"team_id": 7, "player_id": 105, "full_name": "OD Five", "last_name": "OD5", "jersey": 15, "position": "DE"},
        {"team_id": 7, "player_id": 106, "full_name": "O Goalie", "last_name": "OG", "jersey": 31, "position": "GK"},
        {"team_id": 7, "player_id": 107, "full_name": "O Alt", "last_name": "O7", "jersey": 17, "position": "FO"},
    ]
    return players


def _goal_event(time_s, scoring_team, focus_skaters, opp_skaters, focus_scores=True):
    focus_att = [{"playerId": pid} for pid in focus_skaters] + [{"playerId": 6}]
    opp_att = [{"playerId": pid} for pid in opp_skaters] + [{"playerId": 106}]
    positive = focus_att if focus_scores else opp_att
    negative = opp_att if focus_scores else focus_att
    return {
        "event_type": "goal",
        "game_time_s": time_s,
        "team_id": scoring_team,
        "balance": "EQ",
        "raw_json": {
            "data": {
                "balance": "EQ",
                "en": False,
                "currentScore": "1:0",
                "attendants": {"positive": positive, "negative": negative},
            }
        },
    }


def test_forward_matchup_report_shows_multiple_relevant_opponents():
    players = _matchup_players()
    shifts = []
    for pid in (1, 2, 3, 4, 5):
        shifts.append({"team_id": 3, "player_id": pid, "start_time_s": 0, "end_time_s": 60})
    for pid in (101, 102, 103, 104, 105):
        shifts.append({"team_id": 7, "player_id": pid, "start_time_s": 0, "end_time_s": 30})
    for pid in (101, 102, 107, 104, 105):
        shifts.append({"team_id": 7, "player_id": pid, "start_time_s": 30, "end_time_s": 60})
    shots = [
        {"shot_id": 1, "game_time_s": 10, "team_id": 3, "manpower": "5v5", "result": "on_goal", "shot_zone": "SLOT", "on_ice_for_player_ids": [1,2,3,4,5], "on_ice_against_player_ids": [101,102,103,104,105]},
        {"shot_id": 2, "game_time_s": 40, "team_id": 7, "manpower": "5v5", "result": "on_goal", "shot_zone": "LEFT", "on_ice_for_player_ids": [101,102,107,104,105], "on_ice_against_player_ids": [1,2,3,4,5]},
    ]
    report = forward_matchup_report(shifts, players, shots, [], focus_team_id=3, opponent_team_id=7)
    assert len(report["relevant_matchups"]) == 2
    assert {row["total_s"] for row in report["relevant_matchups"]} == {30}
    assert report["line_performance"][0]["total_s"] == 60
    assert report["coverage"]["corsi_assigned"] == 2
    assert report["coverage"]["corsi_total"] == 2


def test_goal_attendants_cover_shift_boundary_and_fix_goal_context():
    players = _matchup_players()
    shifts = []
    for pid in (1, 2, 3, 4, 5):
        shifts.append({"team_id": 3, "player_id": pid, "start_time_s": 0, "end_time_s": 50})
    for pid in (101, 102, 103, 104, 105):
        shifts.append({"team_id": 7, "player_id": pid, "start_time_s": 0, "end_time_s": 50})
    shots = [{
        "shot_id": 10, "game_time_s": 49, "team_id": 3, "manpower": "4v5", "result": "goal", "shot_zone": "SLOT",
        "on_ice_for_player_ids": [1,2,4,5], "on_ice_against_player_ids": [101,102,103,104,105],
    }]
    goals = [_goal_event(50, 3, [1,2,3,4,5], [101,102,103,104,105], True)]
    report = forward_matchup_report(shifts, players, shots, goals, focus_team_id=3, opponent_team_id=7)
    assert report["coverage"]["goals_total"] == 1
    assert report["coverage"]["goals_assigned"] == 1
    assert report["coverage"]["goal_shot_context_mismatches"] == 1
    assert report["relevant_matchups"][0]["gf"] == 1
    assert report["unresolved_goals"] == []


def test_goal_attendants_resolve_mik_as_forward():
    players = _matchup_players(include_mik=True)
    shifts = []
    focus = [1, 2, 1425, 4, 5]
    opp = [101, 102, 103, 104, 105]
    for pid in focus:
        shifts.append({"team_id": 3, "player_id": pid, "start_time_s": 0, "end_time_s": 60})
    for pid in opp:
        shifts.append({"team_id": 7, "player_id": pid, "start_time_s": 0, "end_time_s": 60})
    goals = [_goal_event(30, 3, focus, opp, True)]
    report = forward_matchup_report(shifts, players, [], goals, focus_team_id=3, opponent_team_id=7)
    assert report["coverage"]["goals_assigned"] == 1
    row = report["relevant_matchups"][0]
    assert 1425 in row["ebb_player_ids"]
    assert "Mik→FO" in row["role_notes"]
    assert row["gf"] == 1
