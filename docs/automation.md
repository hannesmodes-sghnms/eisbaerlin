# Daily GitHub automation

The production collection path is GitHub Actions, not Codespaces.

## Schedule

`.github/workflows/update-del-data.yml` runs every day at **04:30 Europe/Berlin** and can also be started manually with `workflow_dispatch`.

Each successful run:

1. discovers the current DEL 2026/27 regular-season schedule,
2. selects every match with `status=AFTER_MATCH`,
3. downloads raw JSON for new matches,
4. refreshes completed matches from the last three calendar days,
5. rebuilds `data/del_2026_27.duckdb` from all persisted raw matches,
6. creates a season-level quality report,
7. fails on missing/failed completed-match imports,
8. commits changed raw JSON, discovery files and reports back to the private repository,
9. uploads DuckDB + reports as a 30-day workflow artifact,
10. creates or replaces the assets on the `dataset-2026-27-latest` GitHub Release.

## Persistence

Tracked in Git:

- `data/raw/<match_id>/*.json`
- `data/discovery/*.json`
- `data/discovery/*.csv`
- `data/reports/*.json`
- `data/reports/*.md`

Not tracked in Git:

- `data/del_2026_27.duckdb`
- per-run `download_manifest.json` files (timestamps would create noisy commits)
- ad-hoc schema inspection output

The DuckDB file is reproducible from the tracked raw JSON and is also exposed as a Release asset for convenience.

## Repository settings

The workflow uses `GITHUB_TOKEN` with `contents: write`. The repository must therefore allow GitHub Actions write access to repository contents. If the default branch is protected against bot pushes, either allow the GitHub Actions bot to push this data update or change the workflow to use a separate data branch / pull request flow.

The rolling release tag `dataset-2026-27-latest` must remain mutable because the workflow replaces its assets with `gh release upload --clobber`.

## Manual run

The same pipeline can be executed locally or inside Codespaces:

```bash
python -m pip install -e ".[dev]"
pytest -q
python scripts/update_season.py --season 2026 --game-type 1 --refresh-days 3
python scripts/validate_season.py
```
