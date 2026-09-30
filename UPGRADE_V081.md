# v0.8.1 – Line Matching Accuracy

This update focuses on the 5v5 line matching model.

## What changed

- Shows all relevant trio-vs-trio matchups instead of only one opponent line per EBB unit.
- Adds an EBB line-performance summary across all opponent units.
- Assigns 5v5 goals from DEL goal-event `attendants` instead of relying on shot timestamps at shift boundaries.
- Adds explicit coverage checks for stable matchup TOI, Corsi assignment and 5v5 goal assignment.
- Adds flexible on-ice roles. Eric Mik (player_id 1425) can resolve as FO or DE per five-skater unit while his roster position remains unchanged.
- Uses the same flexible role resolution for forward units, defense pairs and zone starts.
- Player Usage can show a dynamic usage role such as `DE → FO/DE`.
- Integrates the earlier CSS containment fix for the expandable upcoming-game previews.

## Relevant matchup rule

A matchup is displayed when at least one of these is true:

- >= 30 seconds stable shared TOI
- >= 2 stable appearances
- >= 3 Corsi events assigned to the matchup
- >= 1 goal for or against

Goals are always kept even if the exact unit existed only around the scoring event.

## Install

Overlay the files from this package onto the current repository, then run:

```bash
python -m pip install -e ".[dev]"
pytest -q
python scripts/generate_dashboard.py \
  --db data/del_2026_27.duckdb \
  --discovery data/discovery/season_2026_27_type_1.json \
  --raw-dir data/raw \
  --output-dir site/data \
  --upcoming 3
```

No workflow change is required. The daily workflow will regenerate the static dashboard JSON with the new model.
