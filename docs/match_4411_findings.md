# Match 4411 reference findings

This file records the expected output from the first real 2026/27 payload used to design the v0.3 importer.

## Source shape

Match 4411 is Eisbären Berlin vs. Iserlohn Roosters (4:0).

Observed raw resources relevant to the event model:

- `roster.json`: 41 rostered players, including 4 goalies
- `shiftsSC.json`: 772 shift intervals for 37 unique skaters
- `shots.json`: 84 shot attempts
- `faceoffs.json`: 50 faceoffs
- `period-events.json`: 21 events

The four goalies are the only rostered players absent from the shift feed. Therefore shift counts describe **skaters on ice**, which is what we want for manpower states such as 5v5 and 5v4.

## Shared time axis

The important event feeds use one game-time axis in seconds from the beginning of the match:

- `shiftsSC.json`: `startTime.time` / `endTime.time`
- `shots.json`: `time`
- `faceoffs.json`: `time`
- `period-events.json`: `time`

No period offset conversion is required for these feeds.

## Shot result mapping

The observed result IDs are compatible with the historical DEL mapping:

| ID | Meaning | Match 4411 |
|---:|---|---:|
| 1 | on_goal | 38 |
| 2 | missed | 28 |
| 3 | blocked | 14 |
| 4 | goal | 4 |
| 5 | post | 0 |

The four result-4 shots match the four goals in the period events.

## Faceoff positions

The historic DEL interpretation is used:

- neutral zone: `C`, `ABL`, `ABR`, `HBL`, `HBR`
- home offensive zone: `ADL`, `ADR`
- home defensive zone: `HDL`, `HDR`
- for the away team, offensive/defensive are reversed

This lets `shot_context` express the previous faceoff zone relative to the team taking the shot.

## Shift boundary handling

Most shots can be resolved with half-open shift intervals:

`start_time <= shot_time < end_time`

For 83 of 84 shots in this match that produces a plausible active skater set directly.

One goal shot (`shot_id=1650256`, `time=2021`) lands exactly on a shift timestamp boundary. The pure half-open join produces an implausible active set. For this case the importer adds shifts ending exactly at that second for **both teams**, yielding a 5v5 state. The row is kept and marked `boundary_adjusted` rather than pretending it was an exact match.

Expected quality distribution:

- `exact`: 83 shots
- `boundary_adjusted`: 1 shot
- `low_confidence`: 0 shots

## Expected manpower distribution at shots

- 5v5: 67
- 5v4: 11
- 4v5: 3
- 4v4: 2
- 6v5: 1

Goalies are not included in these counts.

## Defensive-zone faceoff -> shot example metric

For every shot the v0.3 context stores:

- previous faceoff ID/time
- seconds since previous faceoff
- faceoff zone relative to the shooting team
- faceoff winner team
- whether the shooting team won it
- `dzone_faceoff_to_shot_10s`
- `dzone_faceoff_win_to_shot_10s`

Match 4411 happens to contain **zero** shots within 10 seconds of a defensive-zone faceoff, so the implementation is present but needs more matches before we can evaluate the resulting rush-style sample.

## v0.5 analytics reference

Using the historical leaffan shot-zone polygons on the 2026/27 coordinates:

- EBB: 53 Corsi, 43 Corsi 5v5, 15 Slot Attempts, 11 Slot Attempts 5v5.
- IEC: 31 Corsi, 24 Corsi 5v5, 8 Slot Attempts, 5 Slot Attempts 5v5.
- 5v5 SOG: EBB 20, IEC 11.
- 5v5 goals: EBB 2, IEC 0.
- EQ goals from period events: EBB 2, IEC 0.
- PPG: EBB 1, IEC 0. SHG: EBB 1, IEC 0.
- EBB led for 2765 seconds (46:05); the game was tied for the first 835 seconds (13:55).
- Match-level scoring players from `team-stats`: EBB 8, IEC 0.
- Defenseman points: EBB 2, IEC 0.
- PDO 5v5: EBB 110.0 (10.0 SH% + 100.0 SV%), IEC 90.0 (0.0 SH% + 90.0 SV%).

The raw `polygon` label and geometry-derived zone are not identical for every shot. This is expected: the historical leaffan processor also preferred the coordinate-derived polygon and only used the raw polygon field as a consistency check.
