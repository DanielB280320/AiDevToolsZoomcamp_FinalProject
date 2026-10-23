"""Feature flags: validation, the cached reader used by services, and the audited write.

* `FlagReader` (in `app.state.flags`, `FlagsDep` in routers) loads the whole `feature_flag`
  table at most once per `FLAG_CACHE_TTL_SECONDS` and returns typed `FlagValues`. A change made
  with the ops CLI is therefore seen by every running backend within that TTL, without a
  restart. A missing row or an invalid stored value reads as the default; for
  `progression_engine` that is `v1` (F11.5). If the database cannot be read, the last values
  (or the defaults) are kept and the read is retried after the TTL.
* `set_flag` is the only writer (used by `app.cli.flags`): it validates key, value and actor
  against `app.config.FEATURE_FLAGS` before touching the database, records `updated_by` and
  `updated_at` (UTC), and writes one allow-listed log line with key, old/new value and actor.

Engines never import this module: services read a flag and pass the value to the engine.
"""

import datetime as dt
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Final, Literal, cast

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import FEATURE_FLAGS, FLAG_CACHE_TTL_SECONDS, FlagSpec
from app.models import FeatureFlag
from app.telemetry import get_logger

log = get_logger(__name__)

ProgressionEngineVersion = Literal["v1", "v2"]

# Actor labels recorded in `updated_by` and logged: lower-case words joined by hyphens, e.g.
# `oncall-agent`, `owner`, `devops-agent`. No `@`, dots or spaces, so never an email or a name.
ACTOR_PATTERN: Final = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
ACTOR_MAX_LENGTH: Final = 32
_DIGITS: Final = re.compile(r"[0-9]+")


class FlagError(ValueError):
    """An unknown key, a value outside the flag's allow-list, or an invalid actor."""


def flag_spec(key: str) -> FlagSpec:
    spec = FEATURE_FLAGS.get(key)
    if spec is None:
        allowed = ", ".join(sorted(FEATURE_FLAGS))
        raise FlagError(f"unknown flag {key!r}; allowed flags: {allowed}")
    return spec


def describe_values(spec: FlagSpec) -> str:
    if spec.int_max is not None:
        return f"an integer from 0 to {spec.int_max}"
    return "one of " + ", ".join(spec.choices)


def normalize_value(key: str, raw: str) -> str:
    """The canonical stored form of `raw` for flag `key`, or `FlagError`.

    Choice flags accept exactly one of their values (case-sensitive). Integer flags accept
    plain decimal digits only (no sign, spaces or exponent) within 0..int_max; `"007"` -> `"7"`.
    """
    spec = flag_spec(key)
    if spec.int_max is not None:
        if _DIGITS.fullmatch(raw) and int(raw) <= spec.int_max:
            return str(int(raw))
    elif raw in spec.choices:
        return raw
    raise FlagError(f"invalid value for {key}: expected {describe_values(spec)}")


def validate_actor(actor: str) -> str:
    if len(actor) > ACTOR_MAX_LENGTH or not ACTOR_PATTERN.fullmatch(actor):
        raise FlagError(
            "invalid actor: use a lower-case label such as oncall-agent or owner "
            f"(letters, digits, hyphens; at most {ACTOR_MAX_LENGTH} characters)"
        )
    return actor


def effective_value(key: str, stored: str | None) -> str:
    """What the app uses for `key` given the stored text: the default if missing or invalid."""
    spec = flag_spec(key)
    if stored is None:
        return spec.default
    try:
        return normalize_value(key, stored)
    except FlagError:
        return spec.default


@dataclass(frozen=True)
class FlagValues:
    """Typed, effective flag values (defaults applied)."""

    progression_engine: ProgressionEngineVersion
    off_search_enabled: bool
    fault_injection_latency_ms: int

    @classmethod
    def from_stored(cls, stored: Mapping[str, str]) -> "FlagValues":
        def get(key: str) -> str:
            return effective_value(key, stored.get(key))

        return cls(
            progression_engine=cast(ProgressionEngineVersion, get("progression_engine")),
            off_search_enabled=get("off_search_enabled") == "true",
            fault_injection_latency_ms=int(get("fault_injection_latency_ms")),
        )


DEFAULT_FLAGS: Final = FlagValues.from_stored({})


def invalid_stored_keys(stored: Mapping[str, str]) -> set[str]:
    """Allow-listed keys whose stored value is not valid (they read as the default)."""
    invalid: set[str] = set()
    for key, value in stored.items():
        if key not in FEATURE_FLAGS:
            continue
        try:
            normalize_value(key, value)
        except FlagError:
            invalid.add(key)
    return invalid


def read_stored_flags(session: Session) -> dict[str, str]:
    rows = session.execute(select(FeatureFlag.key, FeatureFlag.value)).all()
    return {key: value for key, value in rows}  # noqa: C416  (Row -> str pairs)


class FlagReader:
    """Flag values cached for `ttl_seconds` of the injected clock (thread-safe)."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        now: Callable[[], dt.datetime],
        ttl_seconds: float = FLAG_CACHE_TTL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._now = now
        self._ttl = dt.timedelta(seconds=ttl_seconds)
        self._lock = threading.Lock()
        self._values: FlagValues | None = None
        self._loaded_at: dt.datetime | None = None
        self._warned_invalid: frozenset[str] = frozenset()

    def values(self) -> FlagValues:
        now = self._now()
        with self._lock:
            if self._values is not None and self._is_fresh(now):
                return self._values
            self._values = self._load(fallback=self._values or DEFAULT_FLAGS)
            self._loaded_at = now
            return self._values

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = None

    def _is_fresh(self, now: dt.datetime) -> bool:
        loaded_at = self._loaded_at
        # A clock that went backwards also counts as stale.
        return loaded_at is not None and loaded_at <= now < loaded_at + self._ttl

    def _load(self, fallback: FlagValues) -> FlagValues:
        try:
            with self._session_factory() as session:
                stored = read_stored_flags(session)
        except SQLAlchemyError as error:
            # Never the message: it can quote connection details (spec §6.5).
            log.warning(
                "feature flags unavailable",
                outcome="kept_previous",
                error_type=type(error).__name__,
            )
            return fallback
        invalid = frozenset(invalid_stored_keys(stored))
        for key in sorted(invalid - self._warned_invalid):
            log.warning("feature flag invalid stored value", flag_key=key, outcome="default_used")
        self._warned_invalid = invalid
        return FlagValues.from_stored(stored)


def get_flags(request: Request) -> FlagValues:
    reader: FlagReader = request.app.state.flags
    return reader.values()


FlagsDep = Annotated[FlagValues, Depends(get_flags)]


@dataclass(frozen=True)
class FlagChange:
    key: str
    old_value: str  # the effective value before the change (the default if no row existed)
    new_value: str
    actor: str
    updated_at: dt.datetime

    @property
    def changed(self) -> bool:
        return self.old_value != self.new_value


def validate_change(key: str, raw_value: str, actor: str) -> tuple[str, str]:
    """(normalized value, actor) or `FlagError`. Needs no database."""
    value = normalize_value(key, raw_value)
    return value, validate_actor(actor)


def set_flag(
    session: Session, key: str, raw_value: str, actor: str, now: dt.datetime
) -> FlagChange:
    """Store `key = raw_value` as set by `actor` at `now` (UTC), commit, and log the change.

    Raises `FlagError` before any database access if the key, value or actor is invalid.
    """
    value, actor = validate_change(key, raw_value, actor)
    updated_at = now.astimezone(dt.UTC)
    current = session.execute(
        select(FeatureFlag.value).where(FeatureFlag.key == key).with_for_update()
    ).scalar_one_or_none()
    old_value = effective_value(key, current)
    upsert = insert(FeatureFlag).values(
        key=key, value=value, updated_by=actor, updated_at=updated_at
    )
    session.execute(
        upsert.on_conflict_do_update(
            index_elements=[FeatureFlag.key],
            set_={"value": value, "updated_by": actor, "updated_at": updated_at},
        )
    )
    session.commit()
    change = FlagChange(key, old_value, value, actor, updated_at)
    log.info(
        "feature flag changed",
        flag_key=key,
        flag_old_value=old_value,
        flag_new_value=value,
        actor=actor,
        outcome="changed" if change.changed else "unchanged",
    )
    return change
