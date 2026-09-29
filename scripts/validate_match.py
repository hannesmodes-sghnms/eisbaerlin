#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


def print_rows(con: duckdb.DuckDBPyConnection, sql: str, params: list[object]) -> None:
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    print(" | ".join(cols))
    print("-" * min(160, max(20, len(" | ".join(cols)))))
    for row in cur.fetchall():
        print(" | ".join("" if v is None else str(v) for v in row))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate one imported DEL match.")
    parser.add_argument("match_id", type=int)
    parser.add_argument("--db", type=Path, default=Path("data/del_2026_27.duckdb"))
    args = parser.parse_args()

    con = duckdb.connect(str(args.db), read_only=True)
    try:
        print("\nMATCH")
        print_rows(con, "SELECT match_id, match_date, home_team_name, away_team_name, home_score, away_score FROM matches WHERE match_id = ?", [args.match_id])

        print("\nCOUNTS")
        print_rows(
            con,
            """
            SELECT
              (SELECT count(*) FROM players WHERE match_id = ?) AS players,
              (SELECT count(*) FROM shifts WHERE match_id = ?) AS shifts,
              (SELECT count(*) FROM shots WHERE match_id = ?) AS shots,
              (SELECT count(*) FROM faceoffs WHERE match_id = ?) AS faceoffs,
              (SELECT count(*) FROM events WHERE match_id = ?) AS events
            """,
            [args.match_id] * 5,
        )

        print("\nSHOT RESULTS")
        print_rows(con, "SELECT result, count(*) AS shots FROM shots WHERE match_id = ? GROUP BY result ORDER BY shots DESC", [args.match_id])

        print("\nON-ICE QUALITY")
        print_rows(con, "SELECT on_ice_quality, manpower, count(*) AS shots FROM shot_context WHERE match_id = ? GROUP BY 1,2 ORDER BY shots DESC, 1,2", [args.match_id])

        print("\nBOUNDARY / LOW-CONFIDENCE SHOTS")
        print_rows(
            con,
            """
            SELECT shot_id, game_time_s, manpower, on_ice_quality,
                   on_ice_for_count, on_ice_against_count,
                   on_ice_for_player_ids, on_ice_against_player_ids
            FROM shot_context
            WHERE match_id = ? AND on_ice_quality <> 'exact'
            ORDER BY game_time_s
            """,
            [args.match_id],
        )

        print("\nD-ZONE FACEOFF -> SHOT <= 10s")
        print_rows(
            con,
            """
            SELECT shot_id, game_time_s, shooting_team_id, seconds_since_faceoff,
                   previous_faceoff_position_shortcut,
                   previous_faceoff_won_by_shooting_team,
                   result
            FROM shot_log
            WHERE match_id = ? AND dzone_faceoff_to_shot_10s
            ORDER BY game_time_s
            """,
            [args.match_id],
        )
    finally:
        con.close()


if __name__ == "__main__":
    main()
