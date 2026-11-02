from datetime import date

import duckdb

from delstats.season import _existing_match_ids, should_refresh_match


def test_should_refresh_recent_match():
    assert should_refresh_match(
        "2026-09-27 14:00:00",
        refresh_days=3,
        today=date(2026, 9, 29),
    )


def test_should_not_refresh_old_match():
    assert not should_refresh_match(
        "2026-09-20 14:00:00",
        refresh_days=3,
        today=date(2026, 9, 29),
    )


def test_should_not_refresh_when_disabled():
    assert not should_refresh_match(
        "2026-09-29 14:00:00",
        refresh_days=0,
        today=date(2026, 9, 29),
    )



def test_existing_match_ids_reads_incremental_database(tmp_path):
    db_path = tmp_path / "season.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE matches (match_id BIGINT)")
        con.execute("INSERT INTO matches VALUES (100), (200)")
    finally:
        con.close()

    assert _existing_match_ids(db_path) == {100, 200}


def test_existing_match_ids_is_empty_without_database(tmp_path):
    assert _existing_match_ids(tmp_path / "missing.duckdb") == set()
