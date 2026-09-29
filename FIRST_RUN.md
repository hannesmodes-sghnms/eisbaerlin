# v0.6.0 – erster Lauf

## 1. Projekt installieren

```bash
cd /workspaces/eisbaerlin
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest -q
```

## 2. EBB-Daten aktualisieren

```bash
python scripts/update_season.py \
  --season 2026 \
  --game-type 1 \
  --refresh-days 3 \
  --team-id 3
```

Die DuckDB enthält danach nur die bisher abgeschlossenen EBB-Spiele sowie jeweils beide Mannschaften des betreffenden Spiels.

## 3. Qualität prüfen

```bash
python scripts/validate_season.py
```

## 4. Dashboard erzeugen

```bash
python scripts/generate_dashboard.py \
  --db data/del_2026_27.duckdb \
  --discovery data/discovery/season_2026_27_type_1.json \
  --output-dir site/data \
  --upcoming 3
```

Danach existieren:

```text
site/data/games.json
site/data/games/<match_id>.json
```

`games.json` enthält die abgeschlossenen EBB-Spiele und die nächsten drei EBB-Partien.

## 5. UI lokal prüfen

```bash
python -m http.server 8000 --directory site
```

Im Codespace Port 8000 öffnen.

## 6. GitHub Pages einmalig aktivieren

- Settings → Pages → Source: **GitHub Actions**
- Settings → Secrets and variables → Actions → Variables
- `ENABLE_DASHBOARD_PAGES=true`
- Workflow manuell starten

Danach aktualisiert die tägliche Pipeline das veröffentlichte Dashboard automatisch.
