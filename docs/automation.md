# Daily GitHub automation

The production collection path is GitHub Actions, not Codespaces.

## Schedule

`.github/workflows/update-del-data.yml` runs every day at **04:30 Europe/Berlin** and can also be started manually with `workflow_dispatch`.

Each successful v0.5 run:

1. discovers the current DEL 2026/27 regular-season schedule,
2. selects every match with `status=AFTER_MATCH`,
3. downloads raw JSON for new matches,
4. refreshes completed matches from the last three calendar days,
5. rebuilds `data/del_2026_27.duckdb` from all persisted raw matches,
6. creates a season-level quality report,
7. validates completed-match imports,
8. exports team game and season analytics CSVs,
9. generates podcast prep for upcoming matches in the next seven days,
10. commits changed raw JSON, discovery files and reports back to the private repository,
11. uploads DuckDB + reports as a 30-day workflow artifact,
12. creates or replaces assets on the `dataset-2026-27-latest` GitHub Release.

## Persistence

Tracked in Git:

- `data/raw/<match_id>/*.json`
- `data/raw/<match_id>/team-stats/*.json`
- `data/discovery/*.json`
- `data/discovery/*.csv`
- `data/reports/*.json`
- `data/reports/*.md`
- `data/reports/**/*.csv`

Not tracked in Git:

- `data/del_2026_27.duckdb`
- per-run `download_manifest.json` files when ignored by `.gitignore`
- ad-hoc schema inspection output

The DuckDB is reproducible from tracked raw JSON and is also published as a rolling Release asset.

## Analytics generated daily

```text
data/reports/analytics/team_game_stats.csv
data/reports/analytics/team_season_stats.csv
```

For upcoming games:

```text
data/reports/podcast/<TEAM_A>_vs_<TEAM_B>/
```

These folders are normal text/CSV artifacts and are committed so podcast prep can be read directly from GitHub without opening a Codespace.

## Repository settings

The workflow uses `GITHUB_TOKEN` with `contents: write`. The repository must allow GitHub Actions write access to repository contents. If the default branch is protected against bot pushes, either allow the GitHub Actions bot to push this data update or change the workflow to a separate data branch / pull request flow.

The rolling release tag `dataset-2026-27-latest` remains mutable because the workflow replaces its assets with `gh release upload --clobber`.

## Manual equivalent

```bash
python -m pip install -e ".[dev]"
pytest -q
python scripts/update_season.py --season 2026 --game-type 1 --refresh-days 3
python scripts/validate_season.py
python scripts/generate_season_reports.py
python scripts/generate_upcoming_reports.py --days 7 --last-games 5
```
