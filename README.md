# DEL Event Lab – EBB Game Dashboard

Automatisierte DEL-Datenpipeline für die Saison 2026/27 mit Fokus auf **Eisbären Berlin (Team-ID 3)**.

Das Dashboard bleibt EBB-zentriert: als abgeschlossene Analysefälle sind ausschließlich bereits gespielte EBB-Spiele auswählbar. Für die Vorschau auf die nächsten drei EBB-Spiele werden im Hintergrund jedoch alle abgeschlossenen DEL-Spiele importiert, damit Form, direkte Vergleiche und Gegner-Stats vollständig sind.

## Dashboard

Für jedes abgeschlossene EBB-Spiel stehen bereit:

- Corsi und Corsi 5v5
- Shots on Goal
- Slot Attempts und Slot Attempts 5v5
- Tore / EQ-Tore / PPG
- Zeit in Führung / Gleichstand / Rückstand
- SH%, SV% und PDO bei 5v5
- EBB Player Usage mit sortierbaren TOI / EQ / PP / PK / 5v5 / P1 / P2 / P3
- stabile Forward-Trios und Defense-Pairs
- Abdeckungscheck der stabilen Units gegen die vollständige rekonstruierte 5v5-TOI
- automatische Lineup-Changes zwischen P1→P2 und P2→P3
- Hinweise auf verkürzte Bank in P3
- 5v5 Line Matching: häufigste gegnerische Forward-Unit je EBB-Reihe
- Shot-Zonen nach der historischen `leaffan/del_stats`-Kategorisierung
- Shotmap mit korrekter Blue-Line-Geometrie, Torraum und Filtern nach Team, Spielsituation, EBB-Spieler, Drittel und Ergebnis
- unterschiedliche Shot-Symbole für Tor / aufs Tor / daneben / geblockt
- Tor-/Strafen-Timeline mit Teamkürzel

## Vorschau auf die nächsten drei EBB-Spiele

Jedes kommende Spiel erhält eine aufklappbare Matchup-Vorschau mit:

- Saison-Key-Stats EBB vs. Gegner
- Form der letzten fünf Spiele beider Teams
- direkten Duellen aus der aktuell importierten Saison 2026/27

Die Key Stats sind bewusst deskriptiv und enthalten u. a. Corsi 5v5 %, Corsi/Spiel, SOG/Spiel, Slot Attempts/Spiel, Tore/Gegentore pro Spiel, PDO 5v5 und Zeit in Führung pro Spiel.

## Automatische Pipeline

Der GitHub-Workflow läuft täglich um 04:30 Uhr Europe/Berlin und kann zusätzlich manuell gestartet werden.

1. vollständigen DEL-Spielplan 2026/27 entdecken
2. alle abgeschlossenen DEL-Spiele aktualisieren/importieren
3. Spiele der letzten drei Tage erneut prüfen
4. DuckDB aus den Raw-Daten neu bauen
5. Qualitätschecks durchführen
6. EBB-Dashboard-JSON erzeugen
7. Raw-Daten, Discovery und Dashboard-Daten versionieren
8. DuckDB als Release-Asset aktualisieren
9. optional das Dashboard über GitHub Pages veröffentlichen

Die ligaweite Datengrundlage ist nötig, damit die nächsten Gegner mit ihren letzten fünf Spielen und Saisonwerten verglichen werden können. Das UI bleibt trotzdem EBB-only für abgeschlossene Spiele.

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
  --refresh-days 3

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

`games.json` enthält:

- `completed_games`: nur bereits gespielte EBB-Spiele
- `upcoming_games`: nächste drei EBB-Spiele inkl. Matchup-Vorschau

## 5v5-Lineups und Fact Check

Die Lineup-Analyse trennt zwei Ebenen:

1. **vollständige rekonstruierte 5v5-TOI**: jede Zeitspanne, in der laut Shift-Feed auf beiden Seiten exakt fünf Feldspieler auf dem Eis stehen;
2. **stabile Units**: exakte Forward-Trios bzw. Defense-Pairs, die mindestens 8 Sekunden am Stück bestehen.

Damit wird der Filterverlust transparent. Die UI zeigt zusätzlich pro Spieler und für das Team, wie viel der rekonstruierten 5v5-TOI einer stabilen Unit zugeordnet werden konnte.

Wichtig: `EQ` aus den offiziellen Player-Stats ist nicht dasselbe wie `5v5`. `EQ = TOI - PP - PK` kann auch 4v4, 3v3 und weitere Even-Strength-/Empty-Net-Situationen enthalten. Eine größere Differenz zwischen EQ und der Summe der 5v5-Reihen ist deshalb nicht automatisch ein Fehler der Lineup-Erkennung.

Lineup-Changes werden nun period-to-period erkannt. Eine neue Unit wird hervorgehoben, wenn sie im neuen Drittel mindestens 30 Sekunden stabil eingesetzt wird und im vorherigen Drittel praktisch nicht vorkam; ein einzelner vollständiger Shift ab 45 Sekunden reicht ebenfalls als starkes Signal.

## Line Matching

Für jedes stabile EBB-Forward-Trio wird die gegnerische Forward-Unit ermittelt, gegen die es die meiste gleichzeitig stabile 5v5-Eiszeit hatte. Dadurch lassen sich Matchups und mögliche gezielte Line Matchings direkt aus dem Shift-Feed erkennen.

## Shotmap-Geometrie

Das Dashboard verwendet dieselbe Raw-Koordinatenlogik wie die Shot-Zonen:

- Rink-Grenze: x ±105
- blaue Linien: x ±29
- Torlinien: x ±87
- offensive Bullypunkte: x ±69 / y ±46

Der frühere UI-Fehler lag darin, die blaue Linie bei ±52 einzuzeichnen. ±52 ist die zweite Grenze der `BLUE_LINE`-Shot-Zone, nicht die tatsächliche blaue Linie. Zusätzlich wird nun ein Torraum eingezeichnet.

## Shot-Zonen

Übernommen aus `leaffan/del_stats`:

- SLOT
- LEFT
- RIGHT
- BLUE_LINE
- NEUTRAL_ZONE
- BEHIND_GOAL

xG wird bewusst nicht nachgebaut. Historische xG-Werte stammen aus Wisehockey und wären ohne deren Modell nicht vergleichbar.
