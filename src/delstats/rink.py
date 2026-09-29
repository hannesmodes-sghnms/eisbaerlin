from __future__ import annotations

from dataclasses import dataclass
from math import hypot

# DEL / hokejovyzapis coordinate conversion used by leaffan/del_stats.
X_TO_M = 0.3048
Y_TO_M = 0.1524

HOME_GOAL_COORDS = (-87.0, 0.0)
ROAD_GOAL_COORDS = (87.0, 0.0)

# Raw rink landmarks used by the dashboard drawing. The blue line is at ±29
# in the same coordinate system as the shot-zone polygons (the BLUE_LINE shot
# zone itself spans 29..52). Keeping these separate avoids the old UI bug where
# the visual blue line was incorrectly drawn at ±52.
RINK_X_EXTENT_RAW = 105.0
RINK_Y_EXTENT_RAW = 100.0
BLUE_LINE_X_RAW = 29.0
GOAL_LINE_X_RAW = 87.0
FACEOFF_X_RAW = 69.0
FACEOFF_Y_RAW = 46.0
GOAL_CREASE_RADIUS_M = 1.83

# Polygon coordinates are intentionally copied from leaffan/del_stats
# backend/rink_dimensions.py so historical and current analyses use the same
# shot-zone definition.
POLYGONS: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = (
    ("HOME_SLOT", ((52, 46), (67, 46), (87, 8), (87, -8), (67, -46), (52, -46))),
    ("ROAD_SLOT", ((-52, 46), (-67, 46), (-87, 8), (-87, -8), (-67, -46), (-52, -46))),
    ("HOME_BLUE_LINE", ((29, 100), (52, 100), (52, -100), (29, -100))),
    ("ROAD_BLUE_LINE", ((-29, 100), (-52, 100), (-52, -100), (-29, -100))),
    ("HOME_LEFT", ((52, 100), (87, 100), (87, 8), (67, 46), (52, 46))),
    ("HOME_RIGHT", ((52, -100), (87, -100), (87, -8), (67, -46), (52, -46))),
    ("ROAD_LEFT", ((-52, -100), (-87, -100), (-87, -8), (-67, -46), (-52, -46))),
    ("ROAD_RIGHT", ((-52, 100), (-87, 100), (-87, 8), (-67, 46), (-52, 46))),
    ("HOME_NEUTRAL_ZONE", ((0, 100), (0, -100), (29, -100), (29, 100))),
    ("ROAD_NEUTRAL_ZONE", ((0, 100), (0, -100), (-29, -100), (-29, 100))),
    ("HOME_BEHIND_GOAL", ((87, 100), (87, -100), (105, -100), (105, 100))),
    ("ROAD_BEHIND_GOAL", ((-87, 100), (-87, -100), (-105, -100), (-105, 100))),
)

ZONE_NAMES = ("SLOT", "BLUE_LINE", "LEFT", "RIGHT", "NEUTRAL_ZONE", "BEHIND_GOAL")


@dataclass(frozen=True)
class ShotGeometry:
    coordinate_x: float
    coordinate_y: float
    x_m: float
    y_m: float
    distance_m: float
    zone: str | None


def _point_on_segment(px: float, py: float, a: tuple[float, float], b: tuple[float, float], eps: float = 1e-9) -> bool:
    ax, ay = a
    bx, by = b
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > eps:
        return False
    dot = (px - ax) * (px - bx) + (py - ay) * (py - by)
    return dot <= eps


def _contains_or_intersects(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    """Pure-Python equivalent of the old Shapely contains/intersects fallback."""
    x, y = point
    for i, a in enumerate(polygon):
        b = polygon[(i + 1) % len(polygon)]
        if _point_on_segment(x, y, a, b):
            return True

    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_at_y = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_at_y:
                inside = not inside
        j = i
    return inside


def classify_shot_zone(coordinate_x: float | int | None, coordinate_y: float | int | None) -> str | None:
    if coordinate_x is None or coordinate_y is None:
        return None
    point = (float(coordinate_x), float(coordinate_y))
    for polygon_name, polygon in POLYGONS:
        if _contains_or_intersects(point, polygon):
            # HOME_SLOT / ROAD_SLOT -> SLOT. HOME_BLUE_LINE -> BLUE_LINE, etc.
            if polygon_name.startswith("HOME_"):
                return polygon_name[5:]
            return polygon_name[5:]
    return None


def shot_geometry(
    coordinate_x: float | int | None,
    coordinate_y: float | int | None,
    *,
    shooting_team_id: int,
    home_team_id: int,
) -> ShotGeometry | None:
    if coordinate_x is None or coordinate_y is None:
        return None
    x = float(coordinate_x)
    y = float(coordinate_y)
    x_m = x * X_TO_M
    y_m = y * Y_TO_M

    # Home attacks the +x (ROAD_GOAL) side; road attacks the -x (HOME_GOAL) side.
    goal_x, goal_y = ROAD_GOAL_COORDS if int(shooting_team_id) == int(home_team_id) else HOME_GOAL_COORDS
    distance_m = hypot((x - goal_x) * X_TO_M, (y - goal_y) * Y_TO_M)
    return ShotGeometry(
        coordinate_x=x,
        coordinate_y=y,
        x_m=round(x_m, 3),
        y_m=round(y_m, 3),
        distance_m=round(distance_m, 3),
        zone=classify_shot_zone(x, y),
    )
