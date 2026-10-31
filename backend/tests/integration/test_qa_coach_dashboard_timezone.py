"""QA (#48): F16.5 rules use each athlete's own "today" (rule 5), not UTC and not the coach's."""

from sqlalchemy.orm import Session

from app.models import User
from tests.integration.test_coach_dashboard import World, w  # noqa: F401  (fixture)


def _set_timezone(world: World, who_id: object, tz: str) -> None:
    with Session(world.api.app.state.engine) as db:
        user = db.get(User, who_id)
        assert user is not None
        user.timezone = tz
        db.commit()


def test_inactive_counts_days_on_each_athletes_local_today(w: World) -> None:  # noqa: F811
    # Linked at 2026-10-22 09:00 UTC: 23:00 on the 22nd in Kiritimati (UTC+14), 02:00 on the
    # 22nd in Los Angeles (UTC-7). Two days and one hour later it is 10:00 UTC on the 24th:
    # already the 25th in Kiritimati (3 local days, inactive), still the 24th in LA (2 days).
    east = w.athlete("East")
    west = w.athlete("West")
    _set_timezone(w, east.id, "Pacific/Kiritimati")
    _set_timezone(w, west.id, "America/Los_Angeles")
    w.advance(days=2, hours=1)
    assert w.by_name("East")["attention_reasons"] == ["inactive"]
    assert w.by_name("West")["attention_reasons"] == []
    assert w.by_name("East")["timezone"] == "Pacific/Kiritimati"
