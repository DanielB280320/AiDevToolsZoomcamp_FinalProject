"""session: recompute the stored completion with the per-set formula (F10.2, D110)

Data only, no schema change (CLAUDE.md rule 8). F10.2 used to be Σ min(actual, target) ÷ Σ target,
which adds reps and seconds together; it is now the average over the planned working sets of
min(actual ÷ target, 1). Every stored `session.completion` is recalculated the way
`app.services.training_log.recompute` does: logged sets against their target snapshot, unlogged
planned sets against the plan with an actual of 0, sets without a positive target left out.
Sessions without a stored completion (nothing logged, imported) are not touched.

Rounding is half up to 4 decimals, like the engine; the inner `round(..., 10)` removes the
representation error of non-terminating shares (1/3 + 2/3) before the tie is decided.

The previous release reads the column as a plain ratio, so it keeps working on the new values; the
downgrade recalculates them with the previous formula.

Revision ID: f4b1d8e3a527
Revises: e2a7c9d1b346
Create Date: 2026-11-15 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b1d8e3a527"
down_revision: str | Sequence[str] | None = "e2a7c9d1b346"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One row per planned working set of every session that has a stored completion.
_PLANNED_SETS = """
    SELECT s.id AS session_id,
           (CASE WHEN l.id IS NULL
                 THEN CASE WHEN e.type = 'timed' THEN pe.target_seconds ELSE pe.reps_min END
                 ELSE CASE WHEN e.type = 'timed' THEN l.target_seconds ELSE l.target_reps END
            END)::numeric AS target,
           (CASE WHEN l.id IS NULL OR l.skipped THEN 0
                 ELSE coalesce(CASE WHEN e.type = 'timed' THEN l.seconds ELSE l.reps END, 0)
            END)::numeric AS actual
    FROM session s
    JOIN planned_exercise pe ON pe.training_day_id = s.training_day_id
    JOIN exercise e ON e.id = pe.exercise_id
    CROSS JOIN LATERAL generate_series(1, pe.sets) AS n(set_no)
    LEFT JOIN set_log l
           ON l.session_id = s.id AND l.exercise_id = pe.exercise_id AND l.set_no = n.set_no
    WHERE s.completion IS NOT NULL
"""

_PER_SET = "avg(least(actual / target, 1))"  # D110
_PER_UNIT = "sum(least(actual, target)) / sum(target)"  # before D110


def _recompute(aggregate: str) -> None:
    op.execute(
        f"""
        UPDATE session
        SET completion = least(1, round(round(c.ratio, 10), 4))
        FROM (
            SELECT session_id, {aggregate} AS ratio
            FROM ({_PLANNED_SETS}) planned_sets
            WHERE target > 0
            GROUP BY session_id
        ) c
        WHERE session.id = c.session_id
        """  # noqa: S608 - fixed SQL fragments, no user input
    )


def upgrade() -> None:
    _recompute(_PER_SET)


def downgrade() -> None:
    _recompute(_PER_UNIT)
