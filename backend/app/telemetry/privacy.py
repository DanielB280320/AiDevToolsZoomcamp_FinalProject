"""What may leave the process as telemetry (spec §6.5, CLAUDE.md rule 6).

Everything here is an **allow-list**: a log field, span attribute or metric label that is not
listed is dropped. Adding a name is a privacy decision; it must never carry emails, names,
passwords, tokens, body metrics, food names or notes. Users appear only as `user_hash`.
"""

import hashlib
import hmac
import re
from collections.abc import Mapping
from typing import Final
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

# Field names that must never appear in telemetry, whatever the prefix (spec §6.5). Used as an
# extra guard for the open `fitwise.*` span-attribute namespace and in tests.
SENSITIVE_FIELD_NAMES: Final = frozenset(
    {
        "email",
        "display_name",
        "name",
        "first_name",
        "last_name",
        "password",
        "current_password",
        "new_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "set_cookie",
        "weight_kg",
        "height_cm",
        "body_fat_pct",
        "neck_cm",
        "waist_cm",
        "hip_cm",
        "food_name",
        "note",
        "notes",
        "text",
        "body",
        "query",
        "search_terms",
        "user_id",
    }
)

# Keys a JSON log line may contain. Base fields are filled by the formatter; the rest are what
# call sites may pass. None of them is a `logging.LogRecord` attribute, so they are safe `extra`s.
LOG_BASE_FIELDS: Final = (
    "timestamp",
    "level",
    "message",
    "logger",
    "trace_id",
    "span_id",
    "env",
    "service",
    "version",
)
LOG_EVENT_FIELDS: Final = frozenset(
    {
        "route",  # route template, e.g. /api/v1/sessions/{session_id}/sets; never a raw path
        "method",
        "status",
        "duration_ms",
        "user_hash",
        "error_type",  # exception class name only, never its message
        "check",  # readiness check name (database, migrations)
        "outcome",
        "kind",
        "rule",
        "decision",
        "engine",
        "count",
    }
)

# Span attributes that may be exported. Semantic-convention keys emitted by the FastAPI,
# SQLAlchemy and httpx instrumentations (old and stable conventions), minus anything that holds a
# query string, header, cookie, client address, user agent, body or bound SQL parameter.
SPAN_ATTRIBUTES: Final = frozenset(
    {
        # HTTP (server and client)
        "http.method",
        "http.request.method",
        "http.route",
        "http.status_code",
        "http.response.status_code",
        "http.scheme",
        "url.scheme",
        "http.flavor",
        "network.protocol.version",
        "server.address",
        "server.port",
        "net.host.name",
        "net.host.port",
        "net.peer.name",
        "net.peer.port",
        "net.transport",
        "network.transport",
        "network.peer.port",
        "error.type",
        # Outgoing HTTP only, scrubbed by `scrub_url` (no query, fragment or credentials)
        "http.url",
        "url.full",
        # Database: statement text has placeholders only and string literals are masked
        "db.system",
        "db.system.name",
        "db.name",
        "db.namespace",
        "db.statement",
        "db.query.text",
        "db.operation",
        "db.operation.name",
        "db.collection.name",
        "db.sql.table",
        # Exception events: the class name only
        "exception.type",
        "exception.escaped",
        # FitWise
        "user_hash",
    }
)
# Custom attributes may use this namespace, e.g. `fitwise.engine.rule`.
SPAN_ATTRIBUTE_PREFIX: Final = "fitwise."
# These only make sense for outgoing requests; on server spans they would hold the raw path.
CLIENT_ONLY_SPAN_ATTRIBUTES: Final = frozenset({"http.url", "url.full"})
SQL_SPAN_ATTRIBUTES: Final = frozenset({"db.statement", "db.query.text"})

# Metric labels that may be exported (custom instruments + library client/pool metrics).
METRIC_ATTRIBUTES: Final = frozenset(
    {
        "route",
        "method",
        "status",
        "kind",
        "rule",
        "decision",
        "outcome",
        # httpx client metrics
        "http.method",
        "http.request.method",
        "http.status_code",
        "http.response.status_code",
        "server.address",
        "net.peer.name",
        "error.type",
        # SQLAlchemy pool metrics (pool.name is driver://host:port/database, no credentials)
        "pool.name",
        "state",
        "db.client.connection.pool.name",
        "db.client.connection.state",
    }
)

MAX_STRING_LENGTH: Final = 256

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+")
_SQL_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")

Scalar = str | int | float | bool


def user_hash(user_id: UUID | str, salt: bytes) -> str:
    """Keyed pseudonym of a user id: HMAC-SHA256 with the `USER_HASH_SALT` key, 16 hex chars.

    Stable for the same user and salt, so dashboards can count distinct users, and not
    reversible without the salt.
    """
    digest = hmac.new(salt, str(user_id).encode(), hashlib.sha256).hexdigest()
    return digest[:16]


def scrub_text(value: str) -> str:
    """Mask things that look like emails or tokens and cap the length (free-text guard)."""
    value = _EMAIL.sub("[email]", value)
    value = _BEARER.sub("Bearer [token]", value)
    value = _JWT.sub("[token]", value)
    if len(value) > MAX_STRING_LENGTH:
        value = value[:MAX_STRING_LENGTH] + "..."
    return value


def scrub_url(url: str) -> str:
    """`scheme://host[:port]/path`: drop credentials, query string and fragment."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return ""
    return urlunsplit((parts.scheme, f"{host}{port}", parts.path, "", ""))


def scrub_sql(statement: str) -> str:
    """Mask string literals so an inlined value can never be exported (bound params are `%(x)s`)."""
    return _SQL_STRING_LITERAL.sub("'?'", statement)


def safe_scalar(value: object) -> Scalar | None:
    """Keep plain scalars (strings scrubbed and capped); drop anything structured."""
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return scrub_text(value)
    return None


def is_allowed_span_attribute(key: str) -> bool:
    if key in SPAN_ATTRIBUTES:
        return True
    if key.startswith(SPAN_ATTRIBUTE_PREFIX):
        return key.rsplit(".", 1)[-1] not in SENSITIVE_FIELD_NAMES
    return False


def filter_log_fields(fields: Mapping[str, object]) -> dict[str, Scalar]:
    """The allow-listed, scalar subset of `fields`; everything else is dropped."""
    kept: dict[str, Scalar] = {}
    for key, value in fields.items():
        if key not in LOG_EVENT_FIELDS:
            continue
        safe = safe_scalar(value)
        if safe is not None:
            kept[key] = safe
    return kept
