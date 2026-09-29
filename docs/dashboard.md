# EBB Game Dashboard – Datenvertrag

## Fokus

- Team: Eisbären Berlin
- DEL Team-ID: `3`
- analysierbar: ausschließlich `AFTER_MATCH`-Spiele mit EBB-Beteiligung
- Vorschau: nächste drei `BEFORE_MATCH`-Spiele mit EBB-Beteiligung

## `site/data/games.json`

```json
{
  "focus_team": {"team_id": 3, "abbr": "EBB", "name": "Eisbären Berlin"},
  "generated_at": "...",
  "completed_games": [],
  "upcoming_games": []
}
```

`completed_games` liefert die Spielauswahl. `upcoming_games` ist reine Vorschau und wird nicht als Analysefall angeboten.

## `site/data/games/<match_id>.json`

Enthält:

- Match-Metadaten
- Teammetriken EBB vs. Gegner
- Podcast-Fakten
- EBB Player Usage
- 5v5 Forward-Trios / Defense-Pairs
- P3-Rotationsanalyse
- Shot-Zonen
- einzelne Shots mit Koordinaten und Manpower
- Goal-/Penalty-Timeline

## TOI

Player Usage nutzt die offiziellen Team-Stats-Felder:

- `TOI`: `timeOnIce`
- `PP`: `timeOnIcePP`
- `PK`: `timeOnIceSH`
- `EQ`: `TOI - PP - PK`

Die P1/P2/P3-Splits werden separat aus den Shift-Daten als 5v5-Eiszeit rekonstruiert.
