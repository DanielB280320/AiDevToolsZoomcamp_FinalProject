import datetime as dt

import pytest

from app.services.clock import age_on, is_valid_timezone, local_today


@pytest.mark.parametrize(
    ("birth", "day", "age"),
    [
        (dt.date(2008, 10, 22), dt.date(2026, 10, 21), 17),
        (dt.date(2008, 10, 22), dt.date(2026, 10, 22), 18),
        (dt.date(2008, 10, 22), dt.date(2026, 10, 23), 18),
        (dt.date(2008, 2, 29), dt.date(2026, 2, 28), 17),  # non-leap year: birthday is 1 Mar
        (dt.date(2008, 2, 29), dt.date(2026, 3, 1), 18),
        (dt.date(2008, 2, 29), dt.date(2028, 2, 29), 20),
        (dt.date(1990, 1, 1), dt.date(2026, 12, 31), 36),
        (dt.date(2030, 1, 1), dt.date(2026, 1, 1), -4),  # future birth date is never adult
    ],
)
def test_age_on(birth: dt.date, day: dt.date, age: int) -> None:
    assert age_on(birth, day) == age


@pytest.mark.parametrize(
    ("instant", "timezone", "day"),
    [
        ("2026-10-21T23:30:00+00:00", "UTC", dt.date(2026, 10, 21)),
        ("2026-10-21T23:30:00+00:00", "Pacific/Auckland", dt.date(2026, 10, 22)),
        ("2026-10-22T03:00:00+00:00", "America/Los_Angeles", dt.date(2026, 10, 21)),
        ("2026-10-22T03:00:00+00:00", "Europe/Madrid", dt.date(2026, 10, 22)),
    ],
)
def test_local_today_uses_the_users_time_zone(instant: str, timezone: str, day: dt.date) -> None:
    assert local_today(dt.datetime.fromisoformat(instant), timezone) == day


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("Europe/Madrid", True),
        ("America/Argentina/Buenos_Aires", True),
        ("UTC", True),
        ("Mars/Olympus_Mons", False),
        ("europe/madrid", False),
        ("../../etc/passwd", False),
        ("", False),
    ],
)
def test_is_valid_timezone(name: str, valid: bool) -> None:
    assert is_valid_timezone(name) is valid
