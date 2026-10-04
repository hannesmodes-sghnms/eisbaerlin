# DEL Insight integration

Adds public PENNY DEL / Wisehockey season aggregates to the EBB dashboard.

## Data used

- `playerstats/paesse`: successful / attempted passes, pass percentage, pass distances, received passes
- `playerstats/verteidigung`: Puck Contest Wins / participations (PCW), PCW%, blocked shots
- `playerstats/xg`: xGsum, xGavg, goals, xGDiff

Player IDs and team IDs are taken directly from the public DEL HTML links/images and match the IDs already used by the DEL Event Lab.

## How game-level values work

The public pages expose cumulative season values, not match event feeds. The workflow therefore stores changed cumulative snapshots under `data/del_insight/snapshots/`.

For a completed game, the pipeline finds:

1. the last snapshot before puck drop;
2. the first later snapshot where that team's cumulative Insight values changed;
3. no second game by that team may have occurred in between.

The difference is persisted as `data/del_insight/games/<match_id>.json`.

This produces per-game:

- passes successful / attempted + weighted pass percentage;
- Puck Contests won / participations + PCW%;
- xGsum;
- goals and G-xG;
- blocked shots;
- player-level rows for the same metrics.

If the interval is ambiguous, the game/team is left unavailable rather than guessing.

**xG caveat:** the DEL page exposes player xGsum rounded to two decimals. A game xG derived by snapshot subtraction is therefore based on the published rounded values, not Wisehockey's underlying shot-level xG precision.

## Fallback behavior

`update_del_insight.py` is optional by design. HTTP errors, HTML changes, login changes, or parser failures emit a GitHub Actions warning and return exit code 0 unless `--strict` is supplied. The main DEL ingestion/dashboard job continues with the last valid Insight snapshot.

## Install into the current repo

Copy/extract this ZIP into the repository root, overwriting `scripts/validate_season.py`, then run:

```bash
python apply_del_insight_patch.py
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest -q
```

Create the first baseline immediately:

```bash
python scripts/update_del_insight.py \
  --season 2026-27 \
  --phase hauptrunde \
  --output-dir data/del_insight \
  --discovery data/discovery/season_2026_27_type_1.json
```

Then rebuild the dashboard:

```bash
python scripts/generate_dashboard.py \
  --db data/del_2026_27.duckdb \
  --discovery data/discovery/season_2026_27_type_1.json \
  --raw-dir data/raw \
  --insight-dir data/del_insight \
  --output-dir site/data \
  --upcoming 3
```

The first snapshot immediately enables cumulative DEL Insight values in upcoming-game previews. Per-game DEL Insight values require a pre-game and post-game snapshot, so they begin with the first game after the baseline unless older snapshots are backfilled later.
