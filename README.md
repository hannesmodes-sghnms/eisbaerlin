# DEL Event Lab

Private/local tooling for building a DEL 2026/27 event-log database from the public Hokejovy zapis JSON source.

Current version: **0.3.0 — DuckDB event model + shot context**.

## What is confirmed for 2026/27

Season discovery works via:

```text
league-team-matches/2026/1/
```

The first live run found all 14 DEL teams and 364 regular-season games.

For completed match `4411` (Eisbären Berlin vs. Iserlohn Roosters), the live source exposed:

```text
matches/4411/game-header.json
matches/4411/roster.json
matches/4411/period-events.json
matches/4411/shiftsSC.json
matches/4411/faceoffs.json
matches/4411/team-stats/3.json
matches/4411/team-stats/7.json
matches/4411/top-goalies.json
matches/4411/top-scorers.json
visualization/shots/4411.json
```

Shift filenames remain discovered dynamically. The database importer accepts `shifts*.json` rather than hard-coding `shiftsSC.json`.

## Project goal

Build a reproducible local DEL event database that combines:

- season/match metadata
- player rosters
- shift intervals
- shots and coordinates
- faceoffs
- goals, penalties and other period events

The analytical layer enriches each shot with:

- skaters on ice for and against
- manpower state (`5v5`, `5v4`, ...)
- on-ice join quality
- previous faceoff
- seconds since previous faceoff
- faceoff zone relative to the shooting team
- faceoff winner
- defensive-zone-faceoff -> shot flags

A local shot-map UI comes next, once several matches have passed data validation.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## End-to-end flow for one match

```bash
python scripts/discover_season.py --season 2026 --game-type 1
python scripts/discover_match.py 4411 --verify-shots
python scripts/download_match.py 4411
python scripts/inspect_match.py 4411
python scripts/build_database.py 4411
python scripts/validate_match.py 4411
```

The database is written to:

```text
data/del_2026_27.duckdb
```

## Database tables

### `matches`

One row per game with teams, date, score, stadium and status.

### `players`

Roster snapshot per game. Goalies remain here even though they are absent from the shift feed.

### `shifts`

One row per skater shift interval.

### `shots`

One row per shot attempt with result and coordinates.

### `faceoffs`

One row per faceoff. Winner/loser team IDs are derived through the match roster.

### `events`

Flattened `period-events.json`: goals, penalties, period starts/ends and goalkeeper changes. The complete original event is also retained in `raw_json`.

### `shot_context`

One row per shot with derived event context, including manpower, previous faceoff and D-zone faceoff flags.

### `shot_on_ice`

Normalized one-row-per-shot-per-skater relation. This is the basis for later Corsi/Fenwick/on-ice and line-combination analyses.

## Views

### `event_log`

A single chronological log surface combining faceoffs, period events and shots on the shared `game_time_s` axis.

Example:

```sql
SELECT *
FROM event_log
WHERE match_id = 4411
ORDER BY game_time_s, sort_order;
```

### `shot_log`

Convenience view joining shots and `shot_context`.

Example:

```sql
SELECT
    game_time_s,
    shooter,
    result,
    manpower,
    seconds_since_faceoff,
    previous_faceoff_zone_for_shooting_team
FROM shot_log
WHERE match_id = 4411
ORDER BY game_time_s;
```

Defensive-zone faceoff -> shot within 10 seconds:

```sql
SELECT *
FROM shot_log
WHERE dzone_faceoff_to_shot_10s
ORDER BY match_id, game_time_s;
```

Require the shooting team to have won that faceoff:

```sql
SELECT *
FROM shot_log
WHERE dzone_faceoff_win_to_shot_10s
ORDER BY match_id, game_time_s;
```

## Shift boundary rule

Normal matching uses half-open intervals:

```text
start_time <= event_time < end_time
```

Because timestamps are integer seconds, an event can occasionally land exactly at a recorded shift end. If either team would otherwise have fewer than three active skaters, the importer applies a symmetric boundary fallback for both teams and marks the shot `boundary_adjusted`.

It does **not** silently turn uncertain joins into exact data.

## Match 4411 reference

The real match used to design this version produces the expected reference values documented in:

```text
docs/match_4411_findings.md
docs/match_4411_expected.json
```

Important checkpoints:

- 41 rostered players
- 37 players in shifts (the four goalies are absent)
- 772 shifts
- 84 shots
- 50 faceoffs
- 21 period events
- 83 exact shot/on-ice joins
- 1 boundary-adjusted shot/on-ice join
- 0 low-confidence shots

## Repository structure

```text
del-event-lab/
├── data/
│   ├── discovery/
│   ├── raw/
│   └── schema/
├── docs/
├── scripts/
│   ├── discover_season.py
│   ├── discover_match.py
│   ├── download_match.py
│   ├── inspect_match.py
│   ├── build_database.py
│   └── validate_match.py
├── src/delstats/
│   ├── config.py
│   ├── database.py
│   ├── discovery.py
│   ├── http.py
│   ├── raw.py
│   ├── s3.py
│   ├── schema.py
│   └── transform.py
└── tests/
```

## Next milestone

Run v0.3 against several completed 2026/27 games. Once the schema and join-quality distribution remain stable, add the local Streamlit/Plotly shot map and season-wide batch ingestion.
