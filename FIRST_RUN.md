# v0.7.0 – erster Lauf

## 1. Projekt installieren

```bash
cd /workspaces/eisbaerlin
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest -q
```

## 2. DEL-Daten aktualisieren

```bash
python scripts/update_season.py \
  --season 2026 \
  --game-type 1 \
  --refresh-days 3
```

Ab v0.7.0 wird die Datenbank ligaweit aufgebaut. Das ist nötig für Gegner-Vorschauen, letzte fünf Spiele und direkte Vergleiche. Im Dashboard sind abgeschlossene Spiele weiterhin nur für EBB auswählbar.

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

## 5. UI lokal prüfen

```bash
python -m http.server 8000 --directory site
```

## 6. GitHub Pages

- Settings → Pages → Source: **GitHub Actions**
- `ENABLE_DASHBOARD_PAGES=true`
- Workflow einmal vollständig neu über **Run workflow** starten

Die Pipeline published danach das aktualisierte Dashboard automatisch.
