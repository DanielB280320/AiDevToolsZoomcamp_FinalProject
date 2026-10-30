"""Body tracking (spec F14, F3.3): weigh-ins and the 2 % recalculation suggestion.

* One `BodyMetric` row per athlete and local day; logging a day again replaces it (D43). All
  weights are stored in kg.
* Neck/waist (and hip unless male) without `body_fat_pct` give a Navy body-fat estimate from the
  targets engine (F3.3); a result outside 3-60 % or one that cannot be computed is ignored (D55).
* A weigh-in that is the athlete's latest and differs by at least 2 % from the weight used for the
  targets valid today creates a pending `recalc` suggestion holding the old and the recomputed
  targets; an older pending one is replaced. Accepting stores the stored proposal as the
  targets valid from today, so earlier days keep theirs (rule 7).

Nothing here logs and no span or metric carries values: weights, body fat and measurements are
health data (spec section 6.5).
"""

import dataclasses
import datetime as dt
import uuid
from typing import Any, Final

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.engines import body_tracking
from app.engines import constants as c
from app.engines import targets as targets_engine
from app.errors import ProblemError
from app.models import AthleteProfile, BodyMetric, Suggestion, User
from app.schemas import athlete as athlete_out
from app.schemas.body import BodyMetricInput
from app.schemas.problem import FieldError
from app.services import athlete
from app.services.clock import age_on, local_today
from app.telemetry import Telemetry

LIST_DEFAULT_DAYS = 90
RECALC_RULE: Final = "weight_change"


@dataclasses.dataclass
class LogOutcome:
    metric: BodyMetric
    created: bool
    recalc: Suggestion | None


def metric_view(row: BodyMetric) -> athlete_out.BodyMetric:
    return athlete._metric_view(row)


def list_metrics(
    session: Session,
    athlete_id: uuid.UUID,
    timezone: str,
    now: dt.datetime,
    start: dt.date | None,
    end: dt.date | None,
) -> list[BodyMetric]:
    """Entries from `start` to `end` inclusive, oldest first (default: the last 90 days)."""
    end = end or local_today(now, timezone)
    start = start or end - dt.timedelta(days=LIST_DEFAULT_DAYS - 1)
    if start > end:
        raise ProblemError(400, "bad_request", "`from` must not be after `to`.")
    return list(
        session.scalars(
            select(BodyMetric)
            .where(
                BodyMetric.user_id == athlete_id, BodyMetric.date >= start, BodyMetric.date <= end
            )
            .order_by(BodyMetric.date)
        )
    )


def _body_fat(
    profile: AthleteProfile, data: BodyMetricInput
) -> tuple[float | None, str | None, str | None]:
    """(body fat %, method, Navy explanation). A given value wins over measurements."""
    if data.body_fat_pct is not None:
        return round(data.body_fat_pct, 1), "entered", None
    needs_hip = profile.sex != "male"
    if data.neck_cm is None or data.waist_cm is None or (needs_hip and data.hip_cm is None):
        return None, None, None
    try:
        navy = targets_engine.navy_body_fat(
            targets_engine.Sex(profile.sex),
            float(profile.height_cm),
            data.neck_cm,
            data.waist_cm,
            data.hip_cm,
        )
    except ValueError:
        return None, None, None
    value = round(navy.body_fat_pct, 1)
    if not athlete.BODY_FAT_MIN_PCT <= value <= athlete.BODY_FAT_MAX_PCT:
        return None, None, None
    return value, "navy", navy.explanation


def _latest_weight_date(session: Session, athlete_id: uuid.UUID) -> dt.date | None:
    return session.scalar(
        select(BodyMetric.date)
        .where(BodyMetric.user_id == athlete_id, BodyMetric.weight_kg.is_not(None))
        .order_by(BodyMetric.date.desc())
        .limit(1)
    )


def _macros(row: Any) -> dict[str, Any]:
    return {
        "kcal": row.kcal,
        "protein_g": float(row.protein_g),
        "carbs_g": float(row.carbs_g),
        "fat_g": float(row.fat_g),
    }


def _recalc_suggestion(
    session: Session,
    user: User,
    profile: AthleteProfile,
    weight_kg: float,
    today: dt.date,
    now: dt.datetime,
    telemetry: Telemetry,
) -> Suggestion | None:
    """Replace the pending recalc suggestion by a fresh one when the 2 % rule fires (F14)."""
    session.execute(
        delete(Suggestion).where(
            Suggestion.athlete_id == user.id,
            Suggestion.kind == "recalc",
            Suggestion.status == "pending",
        )
    )
    current = athlete.targets_on(session, user.id, today)
    if current is None:
        return None
    check = body_tracking.check_recalculation(float(current.weight_used_kg), weight_kg)
    if not check.needed:
        return None
    _, body_fat = athlete._latest_inputs(session, user.id, today)
    proposed = athlete._compute_targets(
        telemetry,
        sex=profile.sex,
        height_cm=float(profile.height_cm),
        lifestyle=profile.lifestyle,
        goal=profile.goal,
        age_years=age_on(user.birth_date, today),
        weight_kg=weight_kg,
        body_fat_pct=body_fat,
        planned_weekly_kcal_exact=athlete._active_plan_weekly_kcal(session, user.id, weight_kg),
        note=None,
    )
    stored = dataclasses.asdict(proposed)
    stored["bmr_formula"] = proposed.bmr_formula.value
    row = Suggestion(
        athlete_id=user.id,
        kind="recalc",
        status="pending",
        rule=RECALC_RULE,
        reason=f"{check.reason} {proposed.explanation}",
        inputs={
            "weight_used_kg": float(current.weight_used_kg),
            "new_weight_kg": weight_kg,
            "change_pct": check.change_pct,
            "threshold_pct": c.RECALC_THRESHOLD_PCT,
            "proposed_targets": stored,
        },
        payload={
            "weight_used_kg": float(current.weight_used_kg),
            "new_weight_kg": weight_kg,
            "change_pct": check.change_pct,
            "current": _macros(current),
            "proposed": _macros(proposed),
        },
        created_at=now,
    )
    session.add(row)
    session.flush()
    telemetry.metrics.suggestion_generated("recalc", RECALC_RULE)
    return row


def log_metric(
    session: Session,
    user: User,
    data: BodyMetricInput,
    now: dt.datetime,
    telemetry: Telemetry,
) -> LogOutcome:
    athlete.require_athlete(user)
    # Serialises concurrent weigh-ins (and onboarding/profile changes) of the same athlete.
    session.execute(select(User.id).where(User.id == user.id).with_for_update()).one()
    profile = session.get(AthleteProfile, user.id)
    if profile is None:
        raise ProblemError(404, "not_onboarded", "Complete onboarding first.")
    today = local_today(now, user.timezone)
    if data.date > today:
        raise ProblemError(
            422,
            "validation_error",
            errors=[FieldError(field="date", code="future_date", message="Use today or earlier.")],
        )

    body_fat, method, explanation = _body_fat(profile, data)
    row = session.scalar(
        select(BodyMetric).where(BodyMetric.user_id == user.id, BodyMetric.date == data.date)
    )
    created = row is None
    if row is None:
        row = BodyMetric(user_id=user.id, date=data.date)
        session.add(row)
    row.weight_kg = None if data.weight_kg is None else round(data.weight_kg, 2)
    row.body_fat_pct = body_fat
    row.bf_method = method
    row.body_fat_explanation = explanation
    row.neck_cm = None if data.neck_cm is None else round(data.neck_cm, 1)
    row.waist_cm = None if data.waist_cm is None else round(data.waist_cm, 1)
    row.hip_cm = None if data.hip_cm is None else round(data.hip_cm, 1)
    row.created_at = now
    session.flush()

    recalc: Suggestion | None = None
    if row.weight_kg is not None and _latest_weight_date(session, user.id) == data.date:
        recalc = _recalc_suggestion(session, user, profile, row.weight_kg, today, now, telemetry)
    session.commit()
    return LogOutcome(row, created, recalc)


def accept_recalc(session: Session, user: User, row: Suggestion, now: dt.datetime) -> None:
    """Store the proposed targets from today; earlier `Targets` rows stay as they are."""
    proposed = dict(row.inputs["proposed_targets"])
    proposed["bmr_formula"] = targets_engine.BmrFormula(proposed["bmr_formula"])
    result = targets_engine.TargetsResult(**proposed)
    today = local_today(now, user.timezone)
    athlete._store_targets(session, user.id, today, result, now)
