# v0.5 first run / upgrade in GitHub Codespaces

From the repository root:

```bash
source .venv/bin/activate 2>/dev/null || true
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest -q
```

v0.5 adds columns/tables/views to the DuckDB. For the cleanest local test, rebuild the DB from the already persisted raw data rather than reusing a v0.4 binary database.

Run the normal season pipeline manually:

```bash
python scripts/update_season.py \
  --season 2026 \
  --game-type 1 \
  --refresh-days 3

python scripts/validate_season.py
python scripts/generate_season_reports.py
python scripts/generate_upcoming_reports.py --days 7 --last-games 5
```

Expected generated files include:

```text
data/del_2026_27.duckdb

data/reports/analytics/
├── team_game_stats.csv
└── team_season_stats.csv

data/reports/podcast/
└── <TEAM_A>_vs_<TEAM_B>/
    ├── summary.md
    ├── summary.csv
    ├── head_to_head.csv
    ├── recent_games.csv
    ├── notes.md
    └── metadata.json
```

Manual podcast report example:

```bash
python scripts/generate_podcast_report.py \
  --team-a EBB \
  --team-b MAN \
  --last-games 5
```

Useful DuckDB checks:

```sql
SELECT shot_zone, count(*)
FROM shots
GROUP BY 1
ORDER BY 2 DESC;
```

```sql
SELECT *
FROM team_season_stats
ORDER BY team_shortcut;
```

```sql
SELECT
  team_shortcut,
  shooting_pct_5v5,
  save_pct_5v5,
  pdo_5v5
FROM team_season_stats
ORDER BY team_shortcut;
```

## GitHub Actions

After pushing v0.5.0, run **Actions -> Update DEL 2026-27 dataset -> Run workflow** once manually.

In addition to the v0.4 data update, the job now also:

1. exports `team_game_stats.csv` and `team_season_stats.csv`,
2. creates podcast prep for every scheduled game in the next seven days for which both teams already have imported season data,
3. commits those reports to the private repo,
4. attaches the analytics CSVs to the rolling `dataset-2026-27-latest` Release.

The daily collection itself still runs independently of Codespaces.
