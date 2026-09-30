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
