from delstats.roles import resolve_skater_roles


def test_eric_mik_can_be_resolved_as_forward_in_3f2d_unit():
    players = {
        1: {"player_id": 1, "position": "FO"},
        2: {"player_id": 2, "position": "FO"},
        1425: {"player_id": 1425, "position": "DE", "last_name": "Mik"},
        4: {"player_id": 4, "position": "DE"},
        5: {"player_id": 5, "position": "DE"},
    }
    result = resolve_skater_roles([1, 2, 1425, 4, 5], players)
    assert result.standard is True
    assert set(result.forwards) == {1, 2, 1425}
    assert set(result.defense) == {4, 5}
    assert result.assignments[1425] == "FO"
    assert result.inferred_player_ids == (1425,)
