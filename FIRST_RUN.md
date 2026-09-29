# v0.3 first run in GitHub Codespaces

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

For match 4411, either keep the already downloaded raw folder in `data/raw/4411/` or download it again:

```bash
python scripts/download_match.py 4411
```

Build/update DuckDB:

```bash
python scripts/build_database.py 4411
```

Expected database path:

```text
data/del_2026_27.duckdb
```

Then validate the imported match:

```bash
python scripts/validate_match.py 4411
```

The key reference values should be:

```text
players:   41
shifts:    772
shots:     84
faceoffs:  50
events:    21
```

Expected shot/on-ice quality:

```text
exact:               83
boundary_adjusted:    1
low_confidence:       0
```

Expected manpower distribution at shot time:

```text
5v5  67
5v4  11
4v5   3
4v4   2
6v5   1
```

For this particular game, `D-ZONE FACEOFF -> SHOT <= 10s` should be empty. That is a property of match 4411, not an error in the query.

If those checks match, the next useful test is to repeat the workflow on several other completed matches before we build the shot-map frontend.
