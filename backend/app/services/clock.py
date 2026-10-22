"""The clock and "today in the user's time zone" (spec §6.2). Only services read the clock.

The app keeps its clock in `app.state.clock`; tests swap in a controllable one.
"""

import datetime as dt
from functools import lru_cache
from typing import Annotated, Protocol
from zoneinfo import ZoneInfo, available_timezones

from fastapi import Depends, Request


class Clock(Protocol):
    def now(self) -> dt.datetime:
        """The current instant, timezone-aware, in UTC."""
        ...


class SystemClock:
    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC)


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


ClockDep = Annotated[Clock, Depends(get_clock)]


@lru_cache(maxsize=1)
def _iana_names() -> frozenset[str]:
    return frozenset(available_timezones())


def is_valid_timezone(name: str) -> bool:
    """True for IANA zone names known to the bundled tz database (e.g. `Europe/Madrid`)."""
    return name in _iana_names()


def local_today(now: dt.datetime, timezone: str) -> dt.date:
    """The calendar day it is at instant `now` in the IANA `timezone`."""
    return now.astimezone(ZoneInfo(timezone)).date()


def age_on(birth_date: dt.date, day: dt.date) -> int:
    """Completed years of age on `day`. Someone born on 29 Feb turns a year older on 1 Mar in
    non-leap years."""
    had_birthday = (day.month, day.day) >= (birth_date.month, birth_date.day)
    return day.year - birth_date.year - (0 if had_birthday else 1)
