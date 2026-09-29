from datetime import date

from delstats.season import should_refresh_match


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
