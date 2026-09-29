# First live run — Phase 2

The 2026/27 discovery has already confirmed match `4411` and the current resource layout, including `shiftsSC.json`, `faceoffs.json`, `period-events.json`, and the separate shots object.

## 1. Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Expected: `10 passed`.

## 2. Download raw data for match 4411

The supplied discovery manifest is already included at:

```text
data/discovery/match_4411_resources.json
```

Run:

```bash
python scripts/download_match.py 4411
```

This stores the source JSON unchanged below:

```text
data/raw/4411/
```

Expected resources include:

```text
faceoffs.json
game-header.json
period-events.json
roster.json
shiftsSC.json
team-stats/3.json
team-stats/7.json
top-goalies.json
top-scorers.json
shots.json
download_manifest.json
```

`download_manifest.json` records source URLs, SHA-256 hashes, sizes, and available HTTP metadata.

## 3. Generate the schema report

```bash
python scripts/inspect_match.py 4411
```

Outputs:

```text
data/schema/match_4411_schema.json
data/schema/match_4411_schema.md
```

The JSON report is machine-readable. The Markdown report is convenient for inspecting field names, observed types, array sizes, examples, and nested paths.

## 4. Send back

For the next iteration, send back either:

```text
data/raw/4411/
```

as a ZIP, or at minimum:

```text
data/schema/match_4411_schema.json
data/raw/4411/shiftsSC.json
data/raw/4411/faceoffs.json
data/raw/4411/period-events.json
data/raw/4411/shots.json
```

With those real 2026/27 payloads, the next package will create the DuckDB tables and the first enriched shot timeline with on-ice players and previous-faceoff context.
