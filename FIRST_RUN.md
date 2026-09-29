# First live run in GitHub Codespaces

Run from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python scripts/discover_season.py --season 2026 --game-type 1
```

Then open:

```text
data/discovery/season_2026_27_type_1_matches.csv
```

Pick one completed match ID and run:

```bash
python scripts/discover_match.py MATCH_ID --verify-shots
```

Please return these generated files for the ingestion/DuckDB step:

```text
data/discovery/season_2026_27_type_1.json
data/discovery/season_2026_27_type_1_matches.csv
data/discovery/match_MATCH_ID_resources.json
```

If season discovery reports no schedule files, copy the full terminal output. That means the current bucket path/game-type convention differs from the historical one and we will use the bucket namespace to adjust discovery rather than guessing IDs.
