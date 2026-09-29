import pytest

from delstats.rink import classify_shot_zone, shot_geometry


def test_classifies_leaffan_shot_zones_in_both_directions():
    assert classify_shot_zone(60, 0) == "SLOT"
    assert classify_shot_zone(-60, 0) == "SLOT"
    assert classify_shot_zone(40, 0) == "BLUE_LINE"
    assert classify_shot_zone(-40, 0) == "BLUE_LINE"
    assert classify_shot_zone(70, 80) == "LEFT"
    assert classify_shot_zone(70, -80) == "RIGHT"
    assert classify_shot_zone(-70, -80) == "LEFT"
    assert classify_shot_zone(-70, 80) == "RIGHT"
    assert classify_shot_zone(10, 0) == "NEUTRAL_ZONE"
    assert classify_shot_zone(95, 0) == "BEHIND_GOAL"


def test_zone_boundary_uses_first_matching_polygon_like_old_intersects_fallback():
    assert classify_shot_zone(52, 46) == "SLOT"


def test_shot_geometry_uses_correct_attacking_goal():
    home = shot_geometry(87, 0, shooting_team_id=3, home_team_id=3)
    road = shot_geometry(-87, 0, shooting_team_id=7, home_team_id=3)
    assert home is not None and road is not None
    assert home.distance_m == pytest.approx(0.0)
    assert road.distance_m == pytest.approx(0.0)
