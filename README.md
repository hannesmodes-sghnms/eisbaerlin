# DEL Event Lab — Discovery Starter

First building block for a private DEL 2026/27 event-data project.

This version deliberately focuses on **discovery before assumptions**:

1. discover schedule files for a season/game type from the public S3 bucket;
2. fetch each team schedule;
3. deduplicate matches by match ID;
4. discover every object below `matches/{match_id}/`;
5. classify known resources such as shifts, faceoffs and period events;
6. construct and optionally verify the separate shot endpoint.

The next layer will ingest the discovered raw JSON into DuckDB and merge event timestamps with shift intervals.

## Known source conventions

Historical DEL/Hokejovy zapis data uses these patterns:

```text
league-team-matches/{season}/{game_type}/{team_id}.json
matches/{match_id}/...
visualization/shots/{match_id}.json
```

Historically `game_type=1` represents regular-season games. The code does not hard-code DEL team IDs. It discovers schedule object names below the season prefix.

## Codespaces setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## 1. Discover DEL 2026/27

```bash
python scripts/discover_season.py --season 2026 --game-type 1
```

Expected output files:

```text
data/discovery/season_2026_27_type_1.json
data/discovery/season_2026_27_type_1_matches.csv
```

The JSON contains the schedule keys, discovered team IDs and the normalized/deduplicated match list. The CSV is a convenient human-readable match index.

## 2. Inspect one match

Choose a `match_id` from the generated CSV:

```bash
python scripts/discover_match.py MATCH_ID --verify-shots
```

This performs an S3 prefix lookup for:

```text
matches/MATCH_ID/
```

and classifies discovered resources. Shift filenames are **not assumed**; any object containing `shift` below the match prefix is discovered, so a future/current suffix does not break the code.

Shots are separate from the match prefix. Their candidate path is:

```text
visualization/shots/MATCH_ID.json
```

`--verify-shots` requests that object and reports whether it exists.

A resource manifest is written to:

```text
data/discovery/match_MATCH_ID_resources.json
```

## What to send back after the first live run

For the next step, the most useful files are:

```text
data/discovery/season_2026_27_type_1.json
data/discovery/season_2026_27_type_1_matches.csv
data/discovery/match_MATCH_ID_resources.json
```

If the match resource manifest shows shots, shifts, faceoffs and period events, the next iteration can implement raw downloading + DuckDB tables immediately.

## Design decisions

- Source JSON remains raw and reproducible.
- Match IDs come from the season schedule, not guessed numeric ranges.
- Shift filenames are discovered, not hard-coded.
- Parsing tolerates several common field-name variants.
- HTTP calls use retries/backoff.
- S3 ListObjects v1 pagination is implemented because the source bucket has historically exposed the `marker` interface.

## Current limitation of this starter package

The package has parser/discovery unit tests, but the generated copy was not able to perform a live S3 request from the build environment because that environment could not resolve the S3 hostname. The intended first Codespaces run above is therefore also the live-source verification.
