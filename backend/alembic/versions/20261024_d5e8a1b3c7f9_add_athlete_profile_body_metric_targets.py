"""add athlete_profile, body_metric, targets and planned kcal columns

Onboarding data (spec §8, F2, F3). Expand-only (D50): three new tables with foreign keys to
`users`, and two new `planned_kcal` columns on the plan tables that are NOT NULL with a server
default of 0, so the previous release can still insert plan rows without naming them.
Nothing existing is dropped, renamed or tightened.

Revision ID: d5e8a1b3c7f9
Revises: c3b9f1a2d4e7
Create Date: 2026-10-24 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e8a1b3c7f9"
down_revision: str | Sequence[str] | None = "c3b9f1a2d4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "athlete_profile",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("sex", sa.String(length=16), nullable=False),
        sa.Column("height_cm", sa.Numeric(4, 1, asdecimal=False), nullable=False),
        sa.Column("lifestyle", sa.String(length=16), nullable=False),
        sa.Column("goal", sa.String(length=16), nullable=False),
        sa.Column("experience", sa.String(length=16), nullable=False),
        sa.Column("days_per_week", sa.Integer(), nullable=False),
        sa.Column("preferred_days", _JSON, nullable=False),
        sa.Column("session_minutes", sa.Integer(), nullable=False),
        sa.Column("equipment", sa.String(length=16), nullable=False),
        sa.Column("avoided_exercise_ids", _JSON, nullable=False),
        sa.Column("diet", sa.String(length=16), nullable=False),
        sa.Column("allergies", _JSON, nullable=False),
        sa.Column("meals_per_day", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sex IN ('male', 'female', 'unspecified')", name=op.f("ck_athlete_profile_sex")
        ),
        sa.CheckConstraint(
            "lifestyle IN ('sedentary', 'lightly_active', 'active', 'very_active')",
            name=op.f("ck_athlete_profile_lifestyle"),
        ),
        sa.CheckConstraint(
            "goal IN ('recomposition', 'muscle_gain', 'cutting', 'maintenance', 'wellness')",
            name=op.f("ck_athlete_profile_goal"),
        ),
        sa.CheckConstraint(
            "experience IN ('beginner', 'intermediate', 'advanced')",
            name=op.f("ck_athlete_profile_experience"),
        ),
        sa.CheckConstraint(
            "equipment IN ('full_gym', 'home_dumbbells', 'bodyweight_only')",
            name=op.f("ck_athlete_profile_equipment"),
        ),
        sa.CheckConstraint(
            "diet IN ('omnivore', 'vegetarian', 'vegan', 'pescatarian')",
            name=op.f("ck_athlete_profile_diet"),
        ),
        sa.CheckConstraint(
            "height_cm BETWEEN 120 AND 230", name=op.f("ck_athlete_profile_height_cm")
        ),
        sa.CheckConstraint(
            "days_per_week BETWEEN 2 AND 6", name=op.f("ck_athlete_profile_days_per_week")
        ),
        sa.CheckConstraint(
            "session_minutes IN (30, 45, 60, 75, 90)",
            name=op.f("ck_athlete_profile_session_minutes"),
        ),
        sa.CheckConstraint(
            "meals_per_day IN (3, 4, 5)", name=op.f("ck_athlete_profile_meals_per_day")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_athlete_profile_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_athlete_profile")),
    )

    op.create_table(
        "body_metric",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(5, 2, asdecimal=False), nullable=True),
        sa.Column("body_fat_pct", sa.Numeric(4, 1, asdecimal=False), nullable=True),
        sa.Column("neck_cm", sa.Numeric(4, 1, asdecimal=False), nullable=True),
        sa.Column("waist_cm", sa.Numeric(4, 1, asdecimal=False), nullable=True),
        sa.Column("hip_cm", sa.Numeric(4, 1, asdecimal=False), nullable=True),
        sa.Column("bf_method", sa.String(length=16), nullable=True),
        sa.Column("body_fat_explanation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "bf_method IS NULL OR bf_method IN ('entered', 'navy')",
            name=op.f("ck_body_metric_bf_method"),
        ),
        sa.CheckConstraint(
            "weight_kg IS NULL OR weight_kg BETWEEN 35 AND 300",
            name=op.f("ck_body_metric_weight_kg"),
        ),
        sa.CheckConstraint(
            "body_fat_pct IS NULL OR body_fat_pct BETWEEN 3 AND 60",
            name=op.f("ck_body_metric_body_fat_pct"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_body_metric_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_body_metric")),
        sa.UniqueConstraint("user_id", "date", name="uq_body_metric_user_id_date"),
    )
    op.create_index(op.f("ix_body_metric_user_id"), "body_metric", ["user_id"], unique=False)

    op.create_table(
        "targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("bmr_formula", sa.String(length=16), nullable=False),
        sa.Column("bmr_kcal", sa.Integer(), nullable=False),
        sa.Column("lifestyle_factor", sa.Float(), nullable=False),
        sa.Column("baseline_kcal", sa.Integer(), nullable=False),
        sa.Column("planned_exercise_kcal_per_day", sa.Integer(), nullable=False),
        sa.Column("goal_adjustment_pct", sa.Float(), nullable=False),
        sa.Column("kcal", sa.Integer(), nullable=False),
        sa.Column("protein_g", sa.Numeric(6, 1, asdecimal=False), nullable=False),
        sa.Column("carbs_g", sa.Numeric(6, 1, asdecimal=False), nullable=False),
        sa.Column("fat_g", sa.Numeric(6, 1, asdecimal=False), nullable=False),
        sa.Column("target_balance_kcal", sa.Integer(), nullable=False),
        sa.Column("floor_applied", sa.Boolean(), nullable=False),
        sa.Column("floor_kcal", sa.Integer(), nullable=False),
        sa.Column("carbs_clamped", sa.Boolean(), nullable=False),
        sa.Column("weight_used_kg", sa.Numeric(5, 2, asdecimal=False), nullable=False),
        sa.Column("body_fat_pct_used", sa.Numeric(4, 1, asdecimal=False), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("inputs", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "bmr_formula IN ('katch_mcardle', 'mifflin_st_jeor')",
            name=op.f("ck_targets_bmr_formula"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_targets_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_targets")),
        sa.UniqueConstraint("user_id", "valid_from", name="uq_targets_user_id_valid_from"),
    )
    op.create_index(op.f("ix_targets_user_id"), "targets", ["user_id"], unique=False)

    # Planned exercise kcal (F13.2), computed from the athlete's weight when a plan is created.
    op.add_column(
        "training_day",
        sa.Column("planned_kcal", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "planned_exercise",
        sa.Column("planned_kcal", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("planned_exercise", "planned_kcal")
    op.drop_column("training_day", "planned_kcal")
    op.drop_table("targets")
    op.drop_table("body_metric")
    op.drop_table("athlete_profile")
