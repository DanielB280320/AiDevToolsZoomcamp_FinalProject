"""Test doubles shared by unit and integration tests."""

import datetime as dt


class FakeClock:
    """A controllable `app.services.clock.Clock`."""

    def __init__(self, now: dt.datetime) -> None:
        assert now.tzinfo is not None
        self._now = now.astimezone(dt.UTC)

    def now(self) -> dt.datetime:
        return self._now

    def set(self, now: dt.datetime) -> None:
        self._now = now.astimezone(dt.UTC)

    def advance(self, **delta: float) -> None:
        self._now += dt.timedelta(**delta)
