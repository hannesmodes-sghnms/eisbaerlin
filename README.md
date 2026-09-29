# DEL Event Lab – EBB Game Dashboard

Automatisierte DEL-Datenpipeline für die Saison 2026/27 mit Fokus auf **Eisbären Berlin (Team-ID 3)**.

Das Projekt lädt täglich nur bereits abgeschlossene EBB-Spiele, baut daraus eine DuckDB und erzeugt ein statisches Dashboard für die Podcast-Vorbereitung. Zusätzlich zeigt das Dashboard die nächsten drei EBB-Spiele aus dem aktuellen DEL-Spielplan.

## Dashboard

Das UI zeigt ausschließlich bereits gespielte EBB-Spiele als auswählbare Analysefälle. Für jedes Spiel stehen bereit:

- Corsi und Corsi 5v5
- Shots on Goal
- Slot Attempts und Slot Attempts 5v5
- Tore / EQ-Tore / PPG
- Zeit in Führung / Gleichstand / Rückstand
- SH%, SV% und PDO bei 5v5
- EBB Player Usage mit TOI / EQ / PP / PK / Shifts / Ø Shift
- 5v5-Eiszeit je Spieler nach Drittel
- stabile Forward-Trios und Defense-Pairs
- automatische Hinweise auf verkürzte Bank in P3
- neue bzw. verschwundene 5v5-Units in P3
- Shot-Zonen nach der historischen `leaffan/del_stats`-Kategorisierung
- Shotmap
- Tor-/Strafen-Timeline

Oben im Dashboard werden zusätzlich die **nächsten drei EBB-Spiele** angezeigt. Zukünftige Spiele sind reine Vorschau und haben noch keine Stats.

## Automatische Pipeline

Der GitHub-Workflow läuft täglich um 04:30 Uhr Europe/Berlin und kann zusätzlich manuell gestartet werden.

1. vollständigen DEL-Spielplan 2026/27 entdecken
2. auf EBB-Spiele filtern
3. neue abgeschlossene EBB-Spiele herunterladen
4. EBB-Spiele der letzten drei Tage erneut prüfen
5. DuckDB aus den Raw-Daten neu bauen
6. Qualitätschecks durchführen
7. Dashboard-JSON erzeugen
8. Raw-Daten, Discovery und Dashboard-Daten versionieren
9. DuckDB als Release-Asset aktualisieren
10. optional das Dashboard über GitHub Pages veröffentlichen

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest -q
```

## Pipeline lokal testen

```bash
python scripts/update_season.py \
  --season 2026 \
  --game-type 1 \
  --refresh-days 3 \
  --team-id 3

python scripts/validate_season.py

python scripts/generate_dashboard.py \
  --db data/del_2026_27.duckdb \
  --discovery data/discovery/season_2026_27_type_1.json \
  --output-dir site/data \
  --upcoming 3
```

Das statische Dashboard kann lokal zum Testen über einen einfachen HTTP-Server geöffnet werden:

```bash
python -m http.server 8000 --directory site
```

Dann im Browser den vom Codespace freigegebenen Port 8000 öffnen.

## GitHub Pages

Das Dashboard ist als statische Seite unter `site/` gebaut. Für die automatische Veröffentlichung:

1. Repository **Settings → Pages** öffnen.
2. Source auf **GitHub Actions** setzen.
3. Unter **Settings → Secrets and variables → Actions → Variables** die Repository-Variable `ENABLE_DASHBOARD_PAGES` mit Wert `true` anlegen.
4. Workflow `Update DEL 2026-27 dataset` einmal manuell starten.

Danach wird die Seite mit jedem erfolgreichen täglichen Datenlauf aktualisiert.

## Datenstruktur

```text
data/
├── discovery/
├── raw/<match_id>/
├── reports/
└── del_2026_27.duckdb   # lokal/generated, nicht in Git

site/
├── index.html
└── data/
    ├── games.json
    └── games/<match_id>.json
```

`games.json` enthält zwei Bereiche:

- `completed_games`: nur bereits gespielte EBB-Spiele
- `upcoming_games`: die nächsten drei EBB-Spiele aus dem Saisonspielplan

## 5v5-Lineups

Die Lineup-Analyse rekonstruiert stabile 5v5-Kombinationen aus den Shift-Daten. Kurzlebige Kombinationen während fliegender Wechsel werden gefiltert: Eine Unit wird erst ab mindestens 8 Sekunden stabiler gemeinsamer Eiszeit gezählt.

Für P3 werden u. a. ausgewertet:

- aktive Forwards je Drittel
- Konzentration der 5v5-TOI auf die Top 9 Forwards
- Konzentration der Defense-TOI auf die Top 4 Verteidiger
- neue Forward-Trios in P3
- Units aus P1/P2, die in P3 praktisch verschwinden

Die automatische Aussage beschreibt nur die beobachtete Nutzung. Eine qualitative Einstufung wie „Defensive Unit“ wird nicht aus den Daten erfunden.

## Shot-Zonen

Übernommen aus `leaffan/del_stats`:

- SLOT
- LEFT
- RIGHT
- BLUE_LINE
- NEUTRAL_ZONE
- BEHIND_GOAL

xG wird bewusst nicht nachgebaut. Historische xG-Werte stammen aus Wisehockey und wären ohne deren Modell nicht vergleichbar.
