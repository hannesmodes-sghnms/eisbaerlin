# DEL Event Lab

Private/local tooling for building a DEL 2026/27 event log from the public Hokejovy zapis JSON source.

Current version: **0.2.0 — raw ingestion + schema inspection**.

## Confirmed 2026/27 source layout

The first live discovery run found:

- season prefix: `league-team-matches/2026/1/`
- 14 DEL team IDs
- 364 regular-season match IDs
- 29 matches already marked `AFTER_MATCH` at the time of discovery

For completed match `4411` (Eisbaeren Berlin vs. Iserlohn Roosters), the live source exposed:

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

This confirms that the current shift filename uses the `SC` suffix and that shots remain outside the `matches/{id}/` prefix.

## Project goal

The project will ultimately build a local DuckDB event database that combines:

- match metadata
- player rosters
- shift intervals
- shots and shot coordinates
- faceoffs
- period events such as goals and penalties

The main analytical layer will enrich every shot with context such as:

- players on ice for both teams
- manpower situation
- previous faceoff
- seconds since previous faceoff
- faceoff zone and winner
- later derived event sequences such as defensive-zone-faceoff-to-shot windows

A local shot-map UI will be added after the event model is stable.

## Why raw JSON is retained

Every source response is stored unchanged first. Derived tables are rebuilt from these raw files instead of modifying the source payloads. This lets us correct parser assumptions later without re-fetching historical data.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The current suite should report:

```text
10 passed
```

## Phase 1 — discovery

### Discover a season

```bash
python scripts/discover_season.py --season 2026 --game-type 1
```

Outputs:

```text
data/discovery/season_2026_27_type_1.json
data/discovery/season_2026_27_type_1_matches.csv
```

### Discover one match

```bash
python scripts/discover_match.py 4411 --verify-shots
```

Output:

```text
data/discovery/match_4411_resources.json
```

Shift filenames are discovered dynamically rather than hard-coded.

## Phase 2 — raw download

The live discovery outputs from the first successful 2026/27 run are included in this ZIP for convenience.

Download every discovered JSON resource for match 4411:

```bash
python scripts/download_match.py 4411
```

Raw files are stored under:

```text
data/raw/4411/
```

The bucket hierarchy below the match is preserved where useful, for example:

```text
data/raw/4411/team-stats/3.json
data/raw/4411/team-stats/7.json
```

The separate shot endpoint is normalized locally to:

```text
data/raw/4411/shots.json
```

A generated `download_manifest.json` records for each resource:

- source S3 key
- source URL
- local relative path
- whether it was downloaded or already present
- byte size
- SHA-256
- ETag when supplied
- Last-Modified when supplied

Existing raw files are not downloaded again unless `--force` is used:

```bash
python scripts/download_match.py 4411 --force
```

## Phase 2 — schema inspection

Once the raw match data exists:

```bash
python scripts/inspect_match.py 4411
```

Outputs:

```text
data/schema/match_4411_schema.json
data/schema/match_4411_schema.md
```

The inspector recursively records the observed shape of every JSON file:

- JSON path
- observed data types
- occurrence count
- non-null count
- array length range
- object keys
- a few scalar examples
- file SHA-256 and byte size

Example path notation:

```text
$.match.shots
$.match.shots[]
$.match.shots[].player_id
$.match.shots[].coordinate_x
```

The JSON report is intended as input for the next development step; the Markdown report is for human inspection.

## Repository structure

```text
del-event-lab/
├── data/
│   ├── discovery/
│   ├── raw/
│   └── schema/
├── scripts/
│   ├── discover_season.py
│   ├── discover_match.py
│   ├── download_match.py
│   └── inspect_match.py
├── src/delstats/
│   ├── config.py
│   ├── discovery.py
│   ├── http.py
│   ├── raw.py
│   ├── s3.py
│   └── schema.py
└── tests/
```

## Next milestone

After one real match has been downloaded and its schema report reviewed, version 0.3 will add DuckDB ingestion for the actual 2026/27 payloads. The first derived dataset will be a shot timeline enriched with shift/on-ice and previous-faceoff context.
