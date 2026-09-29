# DEL Event Lab

Private tooling for automatically collecting, modelling and preparing DEL 2026/27 event data for analysis, shot maps and podcast preparation.

Current version: **0.5.0 — automated season pipeline + shot zones + podcast prep analytics**.

## What is confirmed for 2026/27

Season discovery works via:

```text
league-team-matches/2026/1/
```

The first live run found all 14 DEL teams and 364 regular-season games.

For completed match `4411` (Eisbären Berlin vs. Iserlohn Roosters), the live source exposed:

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

Shift filenames remain discovered dynamically. The importer accepts `shifts*.json` rather than hard-coding `shiftsSC.json`.

## Project goal

The project now has three layers:

1. **Collection:** daily GitHub Actions job discovers completed games and persists raw JSON.
2. **Analytics:** DuckDB combines shots, shifts, faceoffs, events, player stats and derived context.
3. **Outputs:** CSV/Markdown podcast prep plus the future local shot-map UI.

The event model enriches each shot with:

- skaters on ice for and against
- manpower state (`5v5`, `5v4`, ...)
- on-ice join quality
- previous faceoff and seconds since faceoff
- faceoff zone relative to the shooting team
- D-zone-faceoff -> shot flags
- shot coordinates in source units and metres
- distance to the attacked goal
- leaffan-compatible shot zone

## Shot zones

v0.5.0 reuses the zone geometry from `leaffan/del_stats` (`backend/rink_dimensions.py` / `backend/get_shots.py`) instead of inventing a new definition.

Available zones:

```text
SLOT
LEFT
RIGHT
BLUE_LINE
NEUTRAL_ZONE
BEHIND_GOAL
```

The importer classifies points using the same polygon ordering and boundary fallback as the historical project. See `docs/shot_zones.md`.

## xG

**xG is deliberately not calculated.**

The historical values used for podcast prep came from Wisehockey. Without access to the Wisehockey source data and model definition, this project does not create a look-alike xG metric that could be mistaken for the same statistic.

A future external xG import can be added separately if reliable values become available.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Daily season pipeline

Production collection runs via `.github/workflows/update-del-data.yml`, currently scheduled for 04:30 Europe/Berlin.

Manual equivalent:

```bash
python scripts/update_season.py --season 2026 --game-type 1 --refresh-days 3
python scripts/validate_season.py
python scripts/generate_season_reports.py
python scripts/generate_upcoming_reports.py --days 7 --last-games 5
```

The pipeline:

1. discovers the current schedule,
2. downloads new completed games,
3. refreshes the last three days,
4. rebuilds the complete DuckDB from tracked raw JSON,
5. validates import quality,
6. exports analytics tables,
7. generates podcast prep for upcoming games,
8. commits raw/discovery/report data,
9. publishes the latest DuckDB as a rolling Release asset.

## Podcast prep

Generate a report manually using team shortcut, id or name:

```bash
python scripts/generate_podcast_report.py \
  --team-a EBB \
  --team-b MAN \
  --last-games 5
```

Output:

```text
data/reports/podcast/EBB_vs_MAN/
├── summary.md
├── summary.csv
├── head_to_head.csv
├── recent_games.csv
├── notes.md
└── metadata.json
```

The season comparison includes:

- Corsi / Corsi 5v5
- Corsi share / Corsi 5v5 share
- Slot Attempts / Slot Attempts 5v5
- goals, EQ goals and 5v5 goals
- powerplay and shorthanded goals
- time leading
- number of scoring players
- defenseman points
- 5v5 shooting percentage
- 5v5 save percentage
- PDO 5v5

`notes.md` contains descriptive talking points only; it does not invent xG or evaluative conclusions.

## Database tables

### Core

- `matches`
- `players`
- `shifts`
- `shots`
- `faceoffs`
- `events`
- `shot_context`
- `shot_on_ice`

### Analytics

- `teams`
- `player_game_stats`
- `team_game_stats`

### Views

- `event_log`
- `shot_log`
- `team_season_stats`

Useful example:

```sql
SELECT
    team_shortcut,
    games_played,
    corsi_for,
    corsi_5v5_for,
    slot_attempts_for,
    goals_for,
    time_leading_s,
    scoring_players,
    defenseman_points,
    pdo_5v5
FROM team_season_stats
ORDER BY team_shortcut;
```

Shot zones:

```sql
SELECT shot_zone, count(*) AS attempts
FROM shot_log
WHERE match_id = 4411
GROUP BY shot_zone
ORDER BY attempts DESC;
```

## Metric definitions

### Corsi

Every shot attempt in the DEL shot feed counts: on goal, goal, missed, blocked and post.

### Corsi 5v5

Same definition, restricted to shots whose derived manpower is exactly `5v5`.

### Slot Attempts

All shot attempts whose coordinates fall into the historical leaffan `SLOT` polygon.

### Tore EQ

Goals whose period-event balance is `EQ`.

### Tore 5v5

Goal shots whose derived manpower state is `5v5`.

### PDO 5v5

```text
5v5 shooting % + 5v5 save %
```

The two components are exported separately as well.

### Zeit in Führung

Calculated from the chronological goal events and `currentScore`, from 00:00 through the recorded game end.

### Scoring players

Distinct players with at least one point in imported `team-stats` across the season.

### Defenseman points

Sum of player points for position code `DE` in imported `team-stats`.

## Match 4411 reference

The real match used to design the event model produced:

- 41 rostered players
- 37 players in shifts (four goalies absent)
- 772 shifts
- 84 shot attempts
- 50 faceoffs
- 21 period events
- 83 exact shot/on-ice joins
- 1 boundary-adjusted join
- 0 low-confidence shots

Using the leaffan shot-zone geometry, the 84 shots split into 53 EBB attempts and 31 IEC attempts; the zone logic is now part of the database import and will be validated across the full season.

## Repository structure

```text
del-event-lab/
├── .github/workflows/update-del-data.yml
├── data/
│   ├── discovery/
│   ├── raw/
│   ├── reports/
│   │   ├── analytics/
│   │   └── podcast/
│   └── schema/
├── docs/
│   ├── automation.md
│   ├── shot_zones.md
│   └── match_4411_*.md/json
├── scripts/
│   ├── discover_season.py
│   ├── discover_match.py
│   ├── download_match.py
│   ├── inspect_match.py
│   ├── build_database.py
│   ├── validate_match.py
│   ├── update_season.py
│   ├── validate_season.py
│   ├── generate_season_reports.py
│   ├── generate_podcast_report.py
│   └── generate_upcoming_reports.py
├── src/delstats/
│   ├── analytics.py
│   ├── podcast.py
│   ├── rink.py
│   └── ...
└── tests/
```

## Next milestone

Use the newly normalized `shot_x_m`, `shot_y_m`, `shot_distance_m` and `shot_zone` fields to build the local shot-map UI. After that, add transparent transition features such as rebound and D-zone-faceoff-to-shot sequences without labelling them as proprietary xG.
