from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


from .discovery import SeasonDiscoverer, save_match_discovery, save_season_discovery
from .raw import RawMatchDownloader


@dataclass
class MatchUpdateResult:
    match_id: int
    start_date: str | None
    home_team_name: str | None
    away_team_name: str | None
    action: str
    refresh: bool
    downloaded_resources: int = 0
    error: str | None = None


@dataclass
class SeasonUpdateSummary:
    season: int
    game_type: int
    generated_at_utc: str
    schedule_matches: int
    completed_matches: int
    refreshed_matches: int
    downloaded_matches: int
    skipped_matches: int
    failed_downloads: int
    imported_matches: int
    failed_imports: int
    db_path: str
    quality_report_path: str
    match_updates: list[MatchUpdateResult]
    import_errors: list[dict[str, Any]]


def _parse_match_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def should_refresh_match(start_date: str | None, *, refresh_days: int, today: date) -> bool:
    if refresh_days <= 0:
        return False
    match_date = _parse_match_date(start_date)
    if match_date is None:
        return False
    return match_date >= today - timedelta(days=refresh_days)


def _raw_match_ready(match_dir: Path) -> bool:
    required = [
        match_dir / "game-header.json",
        match_dir / "roster.json",
        match_dir / "shots.json",
        match_dir / "faceoffs.json",
        match_dir / "period-events.json",
    ]
    team_stats = list((match_dir / "team-stats").glob("*.json"))
    return (
        all(path.exists() for path in required)
        and any(match_dir.glob("shifts*.json"))
        and len(team_stats) >= 2
    )


def build_quality_report(db_path: Path, *, season: int, game_type: int) -> dict[str, Any]:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        counts = con.execute(
            """
            SELECT
              (SELECT count(*) FROM matches) AS matches,
              (SELECT count(*) FROM players) AS player_match_rows,
              (SELECT count(*) FROM shifts) AS shifts,
              (SELECT count(*) FROM shots) AS shots,
              (SELECT count(*) FROM faceoffs) AS faceoffs,
              (SELECT count(*) FROM events) AS events,
              (SELECT count(*) FROM player_game_stats) AS player_game_stats,
              (SELECT count(*) FROM team_game_stats) AS team_game_stats,
              (SELECT count(*) FROM shots WHERE shot_zone IS NULL) AS unclassified_shots
            """
        ).fetchone()
        cols = [d[0] for d in con.description]
        totals = dict(zip(cols, counts))

        quality_rows = con.execute(
            """
            SELECT on_ice_quality, count(*) AS shots
            FROM shot_context
            GROUP BY 1
            ORDER BY 1
            """
        ).fetchall()
        on_ice_quality = {row[0]: row[1] for row in quality_rows}

        manpower_rows = con.execute(
            """
            SELECT manpower, count(*) AS shots
            FROM shot_context
            GROUP BY 1
            ORDER BY shots DESC, manpower
            """
        ).fetchall()
        manpower = {row[0]: row[1] for row in manpower_rows}

        dzone = con.execute(
            """
            SELECT
              sum(CASE WHEN dzone_faceoff_to_shot_10s THEN 1 ELSE 0 END) AS dzone_to_shot_10s,
              sum(CASE WHEN dzone_faceoff_win_to_shot_10s THEN 1 ELSE 0 END) AS dzone_win_to_shot_10s
            FROM shot_context
            """
        ).fetchone()

        per_match_rows = con.execute(
            """
            SELECT
              m.match_id,
              m.match_date,
              m.home_team_name,
              m.away_team_name,
              (SELECT count(*) FROM shots s WHERE s.match_id = m.match_id) AS shots,
              (SELECT count(*) FROM faceoffs f WHERE f.match_id = m.match_id) AS faceoffs,
              (SELECT count(*) FROM shifts sh WHERE sh.match_id = m.match_id) AS shifts,
              (SELECT count(*) FROM shot_context c WHERE c.match_id = m.match_id AND c.on_ice_quality = 'boundary_adjusted') AS boundary_adjusted,
              (SELECT count(*) FROM shot_context c WHERE c.match_id = m.match_id AND c.on_ice_quality = 'low_confidence') AS low_confidence
            FROM matches m
            ORDER BY m.match_date, m.match_id
            """
        ).fetchall()
        per_match = [
            {
                "match_id": row[0],
                "match_date": str(row[1]) if row[1] is not None else None,
                "home_team_name": row[2],
                "away_team_name": row[3],
                "shots": row[4],
                "faceoffs": row[5],
                "shifts": row[6],
                "boundary_adjusted": row[7],
                "low_confidence": row[8],
            }
            for row in per_match_rows
        ]

        return {
            "season": season,
            "game_type": game_type,
            "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "totals": totals,
            "on_ice_quality": on_ice_quality,
            "manpower": manpower,
            "dzone_faceoff_to_shot_10s": int(dzone[0] or 0),
            "dzone_faceoff_win_to_shot_10s": int(dzone[1] or 0),
            "per_match": per_match,
        }
    finally:
        con.close()


def write_quality_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "season_quality.json"
    md_path = output_dir / "season_quality.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    totals = report["totals"]
    quality = report["on_ice_quality"]
    lines = [
        f"# DEL {report['season']}/{str(report['season'] + 1)[-2:]} data quality",
        "",
        f"Generated: {report['generated_at_utc']}",
        "",
        "## Totals",
        "",
        f"- Matches: {totals.get('matches', 0)}",
        f"- Shots: {totals.get('shots', 0)}",
        f"- Shifts: {totals.get('shifts', 0)}",
        f"- Faceoffs: {totals.get('faceoffs', 0)}",
        f"- Events: {totals.get('events', 0)}",
        f"- Player game stats: {totals.get('player_game_stats', 0)}",
        f"- Team game stats: {totals.get('team_game_stats', 0)}",
        f"- Unclassified shot zones: {totals.get('unclassified_shots', 0)}",
        "",
        "## On-ice quality",
        "",
        f"- Exact: {quality.get('exact', 0)}",
        f"- Boundary adjusted: {quality.get('boundary_adjusted', 0)}",
        f"- Low confidence: {quality.get('low_confidence', 0)}",
        "",
        "## D-zone faceoff sequences",
        "",
        f"- D-zone faceoff -> shot <=10s: {report['dzone_faceoff_to_shot_10s']}",
        f"- Won D-zone faceoff -> shot <=10s: {report['dzone_faceoff_win_to_shot_10s']}",
        "",
        "## Per match",
        "",
        "| Match | Date | Game | Shots | Faceoffs | Shifts | Boundary | Low confidence |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["per_match"]:
        game = f"{row['home_team_name']} – {row['away_team_name']}"
        lines.append(
            f"| {row['match_id']} | {row['match_date'] or ''} | {game} | {row['shots']} | {row['faceoffs']} | {row['shifts']} | {row['boundary_adjusted']} | {row['low_confidence']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def update_season(
    *,
    season: int,
    game_type: int = 1,
    refresh_days: int = 3,
    discovery_dir: Path = Path("data/discovery"),
    raw_dir: Path = Path("data/raw"),
    db_path: Path = Path("data/del_2026_27.duckdb"),
    reports_dir: Path = Path("data/reports"),
    timezone_name: str = "Europe/Berlin",
) -> SeasonUpdateSummary:
    discoverer = SeasonDiscoverer()
    downloader = RawMatchDownloader()

    season_discovery = discoverer.discover_season(season, game_type)
    season_json, _ = save_season_discovery(season_discovery, discovery_dir)
    completed = [m for m in season_discovery.matches if m.status == "AFTER_MATCH"]

    local_today = datetime.now(ZoneInfo(timezone_name)).date()
    updates: list[MatchUpdateResult] = []
    failed_downloads = 0
    downloaded_matches = 0
    refreshed_matches = 0
    skipped_matches = 0

    for match in completed:
        match_dir = raw_dir / str(match.match_id)
        refresh = should_refresh_match(match.start_date, refresh_days=refresh_days, today=local_today)
        needs_download = not _raw_match_ready(match_dir)
        if not needs_download and not refresh:
            updates.append(
                MatchUpdateResult(
                    match_id=match.match_id,
                    start_date=match.start_date,
                    home_team_name=match.home_team_name,
                    away_team_name=match.away_team_name,
                    action="skipped",
                    refresh=False,
                )
            )
            skipped_matches += 1
            continue

        try:
            resources = discoverer.discover_match_resources(match.match_id, verify_shots=True)
            manifest_path = save_match_discovery(resources, discovery_dir)
            _, raw_manifest = downloader.download_from_manifest(
                manifest_path,
                output_dir=raw_dir,
                include_shots=True,
                force=refresh,
            )
            updates.append(
                MatchUpdateResult(
                    match_id=match.match_id,
                    start_date=match.start_date,
                    home_team_name=match.home_team_name,
                    away_team_name=match.away_team_name,
                    action="refreshed" if refresh and not needs_download else "downloaded",
                    refresh=refresh,
                    downloaded_resources=sum(r.status == "downloaded" for r in raw_manifest.resources),
                )
            )
            if refresh and not needs_download:
                refreshed_matches += 1
            else:
                downloaded_matches += 1
        except Exception as exc:  # noqa: BLE001 - keep batch running and report all failures
            failed_downloads += 1
            updates.append(
                MatchUpdateResult(
                    match_id=match.match_id,
                    start_date=match.start_date,
                    home_team_name=match.home_team_name,
                    away_team_name=match.away_team_name,
                    action="failed",
                    refresh=refresh,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    if db_path.exists():
        db_path.unlink()

    from .database import build_match_database

    imported = 0
    import_errors: list[dict[str, Any]] = []
    for match in completed:
        match_dir = raw_dir / str(match.match_id)
        if not _raw_match_ready(match_dir):
            import_errors.append({"match_id": match.match_id, "error": "raw data incomplete"})
            continue
        try:
            build_match_database(match_dir=match_dir, db_path=db_path, discovery_path=season_json)
            imported += 1
        except Exception as exc:  # noqa: BLE001
            import_errors.append(
                {"match_id": match.match_id, "error": f"{type(exc).__name__}: {exc}"}
            )

    if imported == 0:
        raise RuntimeError("No completed matches could be imported into DuckDB")

    quality = build_quality_report(db_path, season=season, game_type=game_type)
    quality["pipeline"] = {
        "schedule_matches": len(season_discovery.matches),
        "completed_matches": len(completed),
        "failed_downloads": failed_downloads,
        "failed_imports": len(import_errors),
        "import_errors": import_errors,
    }
    quality_json, _ = write_quality_report(quality, reports_dir)

    summary = SeasonUpdateSummary(
        season=season,
        game_type=game_type,
        generated_at_utc=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        schedule_matches=len(season_discovery.matches),
        completed_matches=len(completed),
        refreshed_matches=refreshed_matches,
        downloaded_matches=downloaded_matches,
        skipped_matches=skipped_matches,
        failed_downloads=failed_downloads,
        imported_matches=imported,
        failed_imports=len(import_errors),
        db_path=str(db_path),
        quality_report_path=str(quality_json),
        match_updates=updates,
        import_errors=import_errors,
    )
    (reports_dir / "season_update_summary.json").write_text(
        json.dumps(asdict(summary), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary
