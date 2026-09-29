# Shot-zone definition

v0.5.0 intentionally reuses the historical DEL shot-zone geometry from the public `leaffan/del_stats` project rather than defining new zones.

Reference files:

- `backend/rink_dimensions.py`
- `backend/get_shots.py`

Repository: `https://github.com/leaffan/del_stats`

## Coordinate conversion

```text
X_TO_M = 0.3048
Y_TO_M = 0.1524
```

Goal locations in source coordinates:

```text
-87, 0
+87, 0
```

The home team attacks the `+87` goal; the road team attacks `-87`.

## Polygons

### Positive-x attacking end

```python
SLOT = [[52,46], [67,46], [87,8], [87,-8], [67,-46], [52,-46]]
BLUE_LINE = [[29,100], [52,100], [52,-100], [29,-100]]
LEFT = [[52,100], [87,100], [87,8], [67,46], [52,46]]
RIGHT = [[52,-100], [87,-100], [87,-8], [67,-46], [52,-46]]
NEUTRAL_ZONE = [[0,100], [0,-100], [29,-100], [29,100]]
BEHIND_GOAL = [[87,100], [87,-100], [105,-100], [105,100]]
```

The negative-x polygons are mirrored, including the left/right orientation so the labels remain relative to the attacking team.

## Classification behavior

The old implementation first used Shapely `contains`, then retried with `intersects` for boundary points. v0.5 implements the equivalent behavior in pure Python and keeps the original polygon order. A point exactly on a shared boundary is therefore assigned to the first matching polygon, which keeps behavior compatible with the historical implementation.

The raw DEL shot payload may also contain an old `polygon` field such as `home_center_polygon`. That field remains stored, but the database field `shot_zone` is derived from coordinates and these polygons, just as the historical processing code did.

## Metric naming

`Slot Attempts` means **all shot attempts** from the SLOT polygon, including on-goal, goal, missed, blocked and post attempts.

`Slot Attempts 5v5` applies the same geometric definition but additionally requires derived manpower `5v5`.
