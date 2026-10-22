import pytest

from app.migrations import load_migration_scripts
from app.services.health import MigrationState, migration_state

HEAD = "c"
KNOWN = {"a", "b", "c"}


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        pytest.param(set(), "pending", id="never migrated"),
        pytest.param({"c"}, "ok", id="at head"),
        pytest.param({"b"}, "pending", id="behind: older known revision"),
        pytest.param({"a"}, "pending", id="far behind"),
        pytest.param({"zz"}, "ok", id="ahead: newer release migrated, this one rolled back"),
    ],
)
def test_migration_state(current: set[str], expected: MigrationState) -> None:
    assert migration_state(current, {HEAD}, KNOWN) == expected


def test_the_release_has_exactly_one_migration_head() -> None:
    scripts = load_migration_scripts()
    assert len(scripts.heads) == 1, "merge Alembic branches before release"
    assert scripts.heads <= scripts.known
