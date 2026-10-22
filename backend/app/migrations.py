"""Location of the Alembic scripts and the revisions this release knows about."""

from dataclasses import dataclass
from pathlib import Path

from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_DIR = BACKEND_DIR / "alembic"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


@dataclass(frozen=True)
class MigrationScripts:
    heads: frozenset[str]
    known: frozenset[str]


def load_migration_scripts(directory: Path = ALEMBIC_DIR) -> MigrationScripts:
    script = ScriptDirectory(str(directory))
    return MigrationScripts(
        heads=frozenset(script.get_heads()),
        known=frozenset(rev.revision for rev in script.walk_revisions()),
    )
