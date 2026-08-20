import datetime as dt

from src.query.time_range import parse_time_range

NOW = dt.datetime(2026, 8, 20, 12, 0, 0, tzinfo=dt.UTC)


def test_past_week() -> None:
    since, until = parse_time_range("what did I work on in the past week", now=NOW)
    assert since == NOW - dt.timedelta(days=7)
    assert until == NOW


def test_last_month() -> None:
    since, until = parse_time_range("changes from last month", now=NOW)
    assert since == NOW - dt.timedelta(days=30)


def test_past_n_days() -> None:
    since, _ = parse_time_range("what changed in the past 3 days", now=NOW)
    assert since == NOW - dt.timedelta(days=3)


def test_today() -> None:
    since, until = parse_time_range("what did I do today", now=NOW)
    assert since == NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    assert until == NOW


def test_yesterday() -> None:
    since, until = parse_time_range("what happened yesterday", now=NOW)
    start_of_today = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    assert since == start_of_today - dt.timedelta(days=1)
    assert until == start_of_today


def test_recently_defaults_to_two_weeks() -> None:
    since, _ = parse_time_range("what changed recently", now=NOW)
    assert since == NOW - dt.timedelta(days=14)


def test_unrecognized_time_phrase_defaults_to_thirty_days() -> None:
    since, _ = parse_time_range("what did I do", now=NOW)
    assert since == NOW - dt.timedelta(days=30)


def test_this_week_starts_at_monday() -> None:
    # NOW is 2026-08-20, a Thursday
    since, _ = parse_time_range("what did I do this week", now=NOW)
    assert since.weekday() == 0
    assert since <= NOW
