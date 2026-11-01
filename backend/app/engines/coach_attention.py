"""F16.5 coach client list: which athletes need attention, and in which order.

Pure functions: dates and flags in, reasons plus an explanation out. No database, HTTP or clock
(rule 3); the caller passes the athlete's local "today". Thresholds live in `constants.py`.

Rules (spec F16.5, D83):

* `low_adherence`: 7-day training adherence below 0.70. `None` (nothing planned) never triggers.
* `deload`: a deload suggestion is pending, or one was applied 14 or fewer days ago.
* `inactive`: no set, meal or weigh-in log for 3 or more days; an athlete who never logged is
  counted from the day the link started.

Order: athletes needing attention first, then everyone else; inside each group by display name
(case-insensitive), then athlete id.
"""

import datetime as dt
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from app.engines.constants import (
    ATTENTION_DELOAD_WINDOW_DAYS,
    ATTENTION_INACTIVE_DAYS,
    ATTENTION_LOW_ADHERENCE_RATIO,
)

Reason = Literal["low_adherence", "deload", "inactive"]
REASON_ORDER: tuple[Reason, ...] = ("low_adherence", "deload", "inactive")


@dataclass(frozen=True)
class AttentionInput:
    today: dt.date  # the athlete's local day
    linked_since: dt.date  # local day the link became active
    training_adherence_7d: float | None
    last_log_date: dt.date | None
    deload_pending: bool
    deload_applied_on: dt.date | None  # local day of the latest applied deload


@dataclass(frozen=True)
class Attention:
    reasons: tuple[Reason, ...]
    explanation: str

    @property
    def needs_attention(self) -> bool:
        return bool(self.reasons)


def evaluate(data: AttentionInput) -> Attention:
    reasons: list[Reason] = []
    notes: list[str] = []
    adherence = data.training_adherence_7d
    if adherence is not None and adherence < ATTENTION_LOW_ADHERENCE_RATIO:
        reasons.append("low_adherence")
        notes.append(
            f"7-day training adherence {adherence:.0%} is below {ATTENTION_LOW_ADHERENCE_RATIO:.0%}"
        )
    if data.deload_pending:
        reasons.append("deload")
        notes.append("a deload suggestion is pending")
    elif data.deload_applied_on is not None:
        age = (data.today - data.deload_applied_on).days
        if age <= ATTENTION_DELOAD_WINDOW_DAYS:
            reasons.append("deload")
            notes.append(f"a deload was applied {age} days ago")
    since = data.last_log_date or data.linked_since
    quiet = (data.today - since).days
    if quiet >= ATTENTION_INACTIVE_DAYS:
        reasons.append("inactive")
        notes.append(
            f"no log for {quiet} days"
            if data.last_log_date
            else f"no log since the link started {quiet} days ago"
        )
    return Attention(
        tuple(reasons), "; ".join(notes).capitalize() if notes else "Nothing needs attention"
    )


def order_athletes[T](
    items: Iterable[T],
    *,
    needs_attention: Callable[[T], bool],
    display_name: Callable[[T], str],
    athlete_id: Callable[[T], object],
) -> list[T]:
    """Attention group first, then by display name (case-insensitive) and athlete id.

    The sort is stable, so items with equal keys keep their input order."""
    return sorted(
        items,
        key=lambda i: (
            not needs_attention(i),
            display_name(i).casefold(),
            str(athlete_id(i)),
        ),
    )
