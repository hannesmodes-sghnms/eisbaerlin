from pathlib import Path

from delstats.del_insight import (
    aggregate_team,
    parse_defense_html,
    parse_passes_html,
    parse_xg_html,
)


def _html(header, row):
    return f"""
    <html><body><table><thead><tr>{''.join(f'<th>{x}</th>' for x in header)}</tr></thead>
    <tbody>{''.join(row for _ in range(25))}</tbody></table></body></html>
    """


def test_parse_passes_page():
    header = ["#", "Team", "#", "Spieler", "Nat", "POS", "Passes", "Pass%", "TP DIST (m)", "FP DIST (m)", "Rcvd Passes"]
    row = """<tr><td>1</td><td><img src='/fileadmin/images/teams/2023/team_3.svg'></td><td>9</td>
    <td><a href='/statistik/spielerdetails/hauptrunde-2627/ty_ronning-2209/details'>Ronning, Ty</a></td>
    <td>USA</td><td>S</td><td>47 / 56</td><td>83.93 %</td><td>1.045</td><td>534</td><td>70</td></tr>"""
    rows = parse_passes_html(_html(header, row))
    assert rows[0]["player_id"] == 2209
    assert rows[0]["team_id"] == 3
    assert rows[0]["player_name"] == "Ty Ronning"
    assert rows[0]["passes_completed"] == 47
    assert rows[0]["passes_attempted"] == 56
    assert rows[0]["pass_pct"] == 83.93
    assert rows[0]["total_pass_distance_m"] == 1045


def test_parse_defense_and_xg_pages_with_german_decimals():
    d_header = ["#", "Team", "#", "Spieler", "Nat", "POS", "PCW", "PCW%", "BKS"]
    d_row = """<tr><td>1</td><td><img src='/team_3.svg'></td><td>40</td>
    <td><a href='/statistik/spielerdetails/hauptrunde-2627/korbinian_geibel-1738/details'>Geibel, Korbinian</a></td>
    <td>GER</td><td>V</td><td>17 / 27</td><td>62,96 %</td><td>2</td></tr>"""
    x_header = ["#", "Team", "#", "Spieler", "Nat", "POS", "xGsum", "xGavg", "Tore", "xGDiff"]
    x_row = """<tr><td>1</td><td><img src='/team_3.svg'></td><td>9</td>
    <td><a href='/statistik/spielerdetails/hauptrunde-2627/ty_ronning-2209/details'>Ronning, Ty</a></td>
    <td>USA</td><td>S</td><td>2,78</td><td>0,15</td><td>4</td><td>1,22</td></tr>"""
    defense = parse_defense_html(_html(d_header, d_row))[0]
    xg = parse_xg_html(_html(x_header, x_row))[0]
    assert defense["pcw_won"] == 17
    assert defense["pcw_total"] == 27
    assert defense["pcw_pct"] == 62.96
    assert xg["xg_sum"] == 2.78
    assert xg["xg_avg"] == 0.15
    assert xg["xg_diff"] == 1.22


def test_team_aggregation_is_weighted_not_average_of_percentages():
    players = [
        {"team_id": 3, "passes_completed": 8, "passes_attempted": 10, "pcw_won": 2, "pcw_total": 4, "xg_sum": 0.4, "goals": 1},
        {"team_id": 3, "passes_completed": 1, "passes_attempted": 2, "pcw_won": 3, "pcw_total": 3, "xg_sum": 0.6, "goals": 0},
    ]
    team = aggregate_team(players, 3, games_played=2)
    assert team["passes_completed"] == 9
    assert team["passes_attempted"] == 12
    assert team["pass_pct"] == 75.0
    assert team["pcw_won"] == 5
    assert team["pcw_total"] == 7
    assert team["pcw_pct"] == 71.43
    assert team["xg_sum"] == 1.0
    assert team["xg_per_game"] == 0.5
