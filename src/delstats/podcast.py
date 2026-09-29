from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TeamRef:
    team_id: int
    name: str
    shortcut: str


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "n/a"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def format_number(value: Any, decimals: int = 1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{decimals}f}"


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return value.strip("_") or "team"


def resolve_team(con: Any, value: str | int) -> TeamRef:
    raw = str(value).strip()
    row = None
    if raw.isdigit():
        row = con.execute(
            "SELECT team_id, team_name, shortcut FROM teams WHERE team_id=?", [int(raw)]
        ).fetchone()
    if row is None:
        row = con.execute(
            """
            SELECT team_id, team_name, shortcut
            FROM teams
            WHERE upper(shortcut)=upper(?) OR lower(team_name)=lower(?)
            ORDER BY team_id
            LIMIT 1
            """,
            [raw, raw],
        ).fetchone()
    if row is None:
        # Partial-name fallback is useful for interactive podcast prep, but only
        # accepts one unambiguous result.
        rows = con.execute(
            """SELECT team_id, team_name, shortcut FROM teams
               WHERE lower(team_name) LIKE lower(?) ORDER BY team_id""",
            [f"%{raw}%"],
        ).fetchall()
        if len(rows) == 1:
            row = rows[0]
        elif len(rows) > 1:
            raise ValueError(f"Ambiguous team '{value}': {[r[1] for r in rows]}")
    if row is None:
        raise ValueError(f"Unknown team '{value}'")
    return TeamRef(int(row[0]), row[1], row[2] or str(row[0]))


def _row_dict(con: Any, sql: str, params: list[Any]) -> dict[str, Any] | None:
    cur = con.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([d[0] for d in cur.description], row))


def season_stats(con: Any, team_id: int) -> dict[str, Any]:
    row = _row_dict(con, "SELECT * FROM team_season_stats WHERE team_id=?", [team_id])
    if row is None:
        raise ValueError(f"No season stats available for team {team_id}")
    return row


def team_game_rows(con: Any, team_id: int, *, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT t.*, m.home_score, m.away_score, m.home_team_id, m.away_team_id
        FROM team_game_stats t
        JOIN matches m USING(match_id)
        WHERE t.team_id=?
        ORDER BY t.match_date DESC, t.match_id DESC
    """
    params: list[Any] = [team_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def head_to_head(con: Any, team_a_id: int, team_b_id: int) -> list[dict[str, Any]]:
    cur = con.execute(
        """
        SELECT
            a.match_id,
            a.match_date,
            m.home_team_id,
            m.home_team_name,
            m.away_team_id,
            m.away_team_name,
            m.home_score,
            m.away_score,
            a.corsi_for AS a_corsi,
            b.corsi_for AS b_corsi,
            a.corsi_5v5_for AS a_corsi_5v5,
            b.corsi_5v5_for AS b_corsi_5v5,
            a.slot_attempts_for AS a_slot_attempts,
            b.slot_attempts_for AS b_slot_attempts,
            a.slot_attempts_5v5_for AS a_slot_attempts_5v5,
            b.slot_attempts_5v5_for AS b_slot_attempts_5v5,
            a.goals_for AS a_goals,
            b.goals_for AS b_goals,
            a.goals_eq_for AS a_goals_eq,
            b.goals_eq_for AS b_goals_eq,
            a.pp_goals_for AS a_pp_goals,
            b.pp_goals_for AS b_pp_goals,
            a.pdo_5v5 AS a_pdo_5v5,
            b.pdo_5v5 AS b_pdo_5v5
        FROM team_game_stats a
        JOIN team_game_stats b ON b.match_id=a.match_id AND b.team_id=?
        JOIN matches m ON m.match_id=a.match_id
        WHERE a.team_id=?
        ORDER BY a.match_date, a.match_id
        """,
        [team_b_id, team_a_id],
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


SEASON_METRICS: tuple[tuple[str, str, str], ...] = (
    ("Corsi", "corsi_for", "int"),
    ("Corsi 5v5", "corsi_5v5_for", "int"),
    ("Corsi %", "corsi_pct", "pct"),
    ("Corsi 5v5 %", "corsi_5v5_pct", "pct"),
    ("Slot Attempts", "slot_attempts_for", "int"),
    ("Slot Attempts 5v5", "slot_attempts_5v5_for", "int"),
    ("Tore", "goals_for", "int"),
    ("Tore EQ", "goals_eq_for", "int"),
    ("Tore 5v5", "goals_5v5_for", "int"),
    ("PPG", "pp_goals_for", "int"),
    ("SHG", "sh_goals_for", "int"),
    ("Zeit in Führung", "time_leading_s", "time"),
    ("Anzahl scorender Spieler", "scoring_players", "int"),
    ("Verteidigerpunkte", "defenseman_points", "int"),
    ("5v5 Shooting %", "shooting_pct_5v5", "pct"),
    ("5v5 Save %", "save_pct_5v5", "pct"),
    ("PDO 5v5", "pdo_5v5", "pdo"),
)


def _metric_value(stats: dict[str, Any], key: str, kind: str) -> str:
    value = stats.get(key)
    if kind == "time":
        return format_duration(value)
    if kind == "int":
        return str(int(value or 0))
    if value is None:
        return "n/a"
    if kind == "pct":
        return f"{float(value):.2f}%"
    if kind == "pdo":
        return f"{float(value):.1f}"
    return str(value)


def _write_csv(path: Path, rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle, delimiter=";").writerows(rows)


def _result_for_team(row: dict[str, Any], team_id: int) -> str:
    if row["home_score"] is None or row["away_score"] is None:
        return ""
    if int(row["home_team_id"]) == team_id:
        own, opp = int(row["home_score"]), int(row["away_score"])
    else:
        own, opp = int(row["away_score"]), int(row["home_score"])
    return f"{own}:{opp}"


def generate_matchup_report(
    *,
    db_path: Path,
    team_a: str | int,
    team_b: str | int,
    output_root: Path = Path("data/reports/podcast"),
    last_games: int = 5,
    season_label: str = "2026/27",
) -> Path:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        a = resolve_team(con, team_a)
        b = resolve_team(con, team_b)
        a_stats = season_stats(con, a.team_id)
        b_stats = season_stats(con, b.team_id)
        h2h = head_to_head(con, a.team_id, b.team_id)
        a_recent = team_game_rows(con, a.team_id, limit=last_games)
        b_recent = team_game_rows(con, b.team_id, limit=last_games)

        out = output_root / f"{_slug(a.shortcut)}_vs_{_slug(b.shortcut)}"
        out.mkdir(parents=True, exist_ok=True)

        summary_rows: list[list[Any]] = [["Metrik", a.shortcut, b.shortcut]]
        for label, key, kind in SEASON_METRICS:
            summary_rows.append([label, _metric_value(a_stats, key, kind), _metric_value(b_stats, key, kind)])
        _write_csv(out / "summary.csv", summary_rows)

        h2h_rows = [[
            "match_id", "date", "home", "away", "score",
            f"{a.shortcut}_corsi", f"{b.shortcut}_corsi",
            f"{a.shortcut}_corsi_5v5", f"{b.shortcut}_corsi_5v5",
            f"{a.shortcut}_slot_attempts", f"{b.shortcut}_slot_attempts",
            f"{a.shortcut}_slot_attempts_5v5", f"{b.shortcut}_slot_attempts_5v5",
            f"{a.shortcut}_goals", f"{b.shortcut}_goals",
            f"{a.shortcut}_goals_eq", f"{b.shortcut}_goals_eq",
            f"{a.shortcut}_ppg", f"{b.shortcut}_ppg",
            f"{a.shortcut}_pdo_5v5", f"{b.shortcut}_pdo_5v5",
        ]]
        for row in h2h:
            h2h_rows.append([
                row["match_id"], row["match_date"], row["home_team_name"], row["away_team_name"],
                f"{row['home_score']}:{row['away_score']}",
                row["a_corsi"], row["b_corsi"], row["a_corsi_5v5"], row["b_corsi_5v5"],
                row["a_slot_attempts"], row["b_slot_attempts"],
                row["a_slot_attempts_5v5"], row["b_slot_attempts_5v5"],
                row["a_goals"], row["b_goals"], row["a_goals_eq"], row["b_goals_eq"],
                row["a_pp_goals"], row["b_pp_goals"], row["a_pdo_5v5"], row["b_pdo_5v5"],
            ])
        _write_csv(out / "head_to_head.csv", h2h_rows)

        recent_rows = [["team", "date", "match_id", "opponent", "result", "corsi", "corsi_5v5", "slot_attempts", "pdo_5v5"]]
        for team, rows in ((a, a_recent), (b, b_recent)):
            for row in rows:
                recent_rows.append([
                    team.shortcut, row["match_date"], row["match_id"], row["opponent_name"],
                    _result_for_team(row, team.team_id), row["corsi_for"], row["corsi_5v5_for"],
                    row["slot_attempts_for"], row["pdo_5v5"],
                ])
        _write_csv(out / "recent_games.csv", recent_rows)

        md = [
            f"# Podcast Prep: {a.name} vs. {b.name}", "",
            f"Saison: {season_label}", "",
            "## Saisonvergleich", "",
            f"| Metrik | {a.shortcut} | {b.shortcut} |",
            "|---|---:|---:|",
        ]
        for label, key, kind in SEASON_METRICS:
            md.append(f"| {label} | {_metric_value(a_stats, key, kind)} | {_metric_value(b_stats, key, kind)} |")
        md.extend(["", "**xG:** nicht enthalten. Die historischen xG-Werte stammen aus Wisehockey; ohne Zugang zu Quelle/Modell wird hier kein Ersatzmodell erfunden.", ""])

        md.extend(["## Direkte Duelle", ""])
        if not h2h:
            md.append("Noch kein direktes Duell in der importierten Saison.")
        for idx, row in enumerate(h2h, start=1):
            md.extend([
                f"### Spiel {idx}: {row['home_team_name']} – {row['away_team_name']} ({row['home_score']}:{row['away_score']})", "",
                f"| Metrik | {a.shortcut} | {b.shortcut} |", "|---|---:|---:|",
                f"| Corsi | {row['a_corsi']} | {row['b_corsi']} |",
                f"| Corsi 5v5 | {row['a_corsi_5v5']} | {row['b_corsi_5v5']} |",
                f"| Slot Attempts | {row['a_slot_attempts']} | {row['b_slot_attempts']} |",
                f"| Slot Attempts 5v5 | {row['a_slot_attempts_5v5']} | {row['b_slot_attempts_5v5']} |",
                f"| Tore | {row['a_goals']} | {row['b_goals']} |",
                f"| Tore EQ | {row['a_goals_eq']} | {row['b_goals_eq']} |",
                f"| PPG | {row['a_pp_goals']} | {row['b_pp_goals']} |",
                f"| PDO 5v5 | {format_number(row['a_pdo_5v5'])} | {format_number(row['b_pdo_5v5'])} |",
                "",
            ])

        def recent_section(team: TeamRef, rows: list[dict[str, Any]]) -> list[str]:
            lines = [f"### {team.shortcut} – letzte {len(rows)} Spiele", "", "| Datum | Gegner | Ergebnis | Corsi | Corsi 5v5 | Slot | PDO 5v5 |", "|---|---|---:|---:|---:|---:|---:|"]
            for row in rows:
                lines.append(
                    f"| {row['match_date']} | {row['opponent_name']} | {_result_for_team(row, team.team_id)} | {row['corsi_for']} | {row['corsi_5v5_for']} | {row['slot_attempts_for']} | {format_number(row['pdo_5v5'])} |"
                )
            lines.append("")
            return lines

        md.extend(["## Letzte Spiele", ""])
        md.extend(recent_section(a, a_recent))
        md.extend(recent_section(b, b_recent))
        (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

        notes = [
            f"# Podcast Notes: {a.shortcut} vs. {b.shortcut}", "",
            "Automatisch erzeugte, deskriptive Fakten aus der aktuellen DEL-Datenbank.", "",
            "## Saison", "",
            f"- Shot Attempts (Corsi): {a.shortcut} {a_stats['corsi_for']}, {b.shortcut} {b_stats['corsi_for']}.",
            f"- 5v5 Shot Attempts: {a.shortcut} {a_stats['corsi_5v5_for']}, {b.shortcut} {b_stats['corsi_5v5_for']}.",
            f"- Slot Attempts: {a.shortcut} {a_stats['slot_attempts_for']}, {b.shortcut} {b_stats['slot_attempts_for']}.",
            f"- Tore: {a.shortcut} {a_stats['goals_for']}, {b.shortcut} {b_stats['goals_for']}; davon EQ {a_stats['goals_eq_for']} bzw. {b_stats['goals_eq_for']}.",
            f"- Powerplay-Tore: {a.shortcut} {a_stats['pp_goals_for']}, {b.shortcut} {b_stats['pp_goals_for']}.",
            f"- Zeit in Führung: {a.shortcut} {format_duration(a_stats['time_leading_s'])}, {b.shortcut} {format_duration(b_stats['time_leading_s'])}.",
            f"- Scoring-Breite: {a.shortcut} {a_stats['scoring_players']} Spieler mit mindestens einem Punkt, {b.shortcut} {b_stats['scoring_players']}.",
            f"- Verteidigerpunkte: {a.shortcut} {a_stats['defenseman_points']}, {b.shortcut} {b_stats['defenseman_points']}.",
            f"- 5v5 PDO: {a.shortcut} {format_number(a_stats['pdo_5v5'])} ({format_number(a_stats['shooting_pct_5v5'],2)}% SH + {format_number(a_stats['save_pct_5v5'],2)}% SV), {b.shortcut} {format_number(b_stats['pdo_5v5'])} ({format_number(b_stats['shooting_pct_5v5'],2)}% SH + {format_number(b_stats['save_pct_5v5'],2)}% SV).",
            "- xG wird bewusst nicht berechnet; historische xG-Werte stammen aus Wisehockey.",
        ]
        if h2h:
            notes.extend(["", "## Direkte Duelle", ""])
            for idx, row in enumerate(h2h, start=1):
                notes.append(
                    f"- Spiel {idx}: Corsi {row['a_corsi']}:{row['b_corsi']}, 5v5 {row['a_corsi_5v5']}:{row['b_corsi_5v5']}, Slot Attempts {row['a_slot_attempts']}:{row['b_slot_attempts']} ({a.shortcut}:{b.shortcut})."
                )
        (out / "notes.md").write_text("\n".join(notes) + "\n", encoding="utf-8")

        metadata = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "season": season_label,
            "team_a": a.__dict__,
            "team_b": b.__dict__,
            "head_to_head_games": len(h2h),
            "last_games": last_games,
            "xg": {"included": False, "reason": "Wisehockey source/model unavailable"},
        }
        (out / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        return out
    finally:
        con.close()


def export_season_tables(*, db_path: Path, output_dir: Path) -> tuple[Path, Path]:
    import duckdb

    output_dir.mkdir(parents=True, exist_ok=True)
    game_path = output_dir / "team_game_stats.csv"
    season_path = output_dir / "team_season_stats.csv"
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        for path, sql in (
            (game_path, "SELECT * FROM team_game_stats ORDER BY match_date, match_id, team_id"),
            (season_path, "SELECT * FROM team_season_stats ORDER BY team_shortcut"),
        ):
            cur = con.execute(sql)
            rows = [[d[0] for d in cur.description], *cur.fetchall()]
            _write_csv(path, rows)
    finally:
        con.close()
    return game_path, season_path


def upcoming_matchups(
    *,
    season_json: Path,
    today: date,
    days: int,
) -> list[dict[str, Any]]:
    payload = json.loads(season_json.read_text(encoding="utf-8"))
    end = today + timedelta(days=days)
    result = []
    for match in payload.get("matches", []):
        if match.get("status") != "BEFORE_MATCH":
            continue
        try:
            dt = datetime.fromisoformat(match["start_date"])
        except (TypeError, ValueError):
            continue
        if today <= dt.date() <= end:
            result.append(match)
    return sorted(result, key=lambda x: (x.get("start_date") or "", int(x.get("match_id") or 0)))
