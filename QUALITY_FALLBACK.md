# Quality fallback patch

Observed failure on 2026-10-03:
- completed matches: 36
- imported matches: 35
- match 4424 (Straubing Tigers - Pinguins Bremerhaven) downloaded only 9 resources
- import status: `raw data incomplete`

Behavior after this patch:
- failed download / `raw data incomplete` => warning, workflow continues
- missing completed match caused only by those upstream gaps => warning, workflow continues
- real importer exception => hard failure
- inconsistent `team_game_stats` row count => hard failure
- configured low-confidence limit breach => hard failure

The incomplete match remains absent from that day's rebuilt DuckDB/dashboard and is retried automatically on later runs because `_raw_match_ready()` remains false.
