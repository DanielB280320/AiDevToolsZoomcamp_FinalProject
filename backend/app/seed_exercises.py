"""F4.1 exercise catalog seed: 60-80 exercises, loaded by the migration step (D50).

Idempotent: the matching key is the deterministic id, uuid5 of the lower-cased name, OR the
lower-cased name among seed rows (owner_id IS NULL). An entry is inserted only when neither
exists, so a second run changes nothing, a seed row renamed or edited later is never
overwritten, and the seed never updates or deletes a row. Renaming an entry in SEED_EXERCISES
does not rename existing rows (no automatic rename migration): the old row stays and the new
name is added next to it. Ids are derived from the name, so every environment gets the same ids.

MET values follow the 2011 Compendium of Physical Activities. `increment_kg` is the default
progression step (F11): 2.5 for barbell and machine/cable work, 2 for dumbbells, 0 for
bodyweight and timed work.
"""

import uuid
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Exercise

_NAMESPACE = uuid.UUID("5e1f7c0e-3a52-4c1b-9d58-0f1d2a6b7c40")


class SeedExercise(NamedTuple):
    name: str
    muscle_group: str
    equipment: str
    type: str
    met: float
    increment_kg: float
    region: str
    allows_added_weight: bool = False


S, B, T = "strength", "bodyweight", "timed"
U, L, F, C = "upper", "lower", "full", "cardio"

SEED_EXERCISES: tuple[SeedExercise, ...] = (
    # chest
    SeedExercise("Barbell bench press", "chest", "barbell", S, 5.0, 2.5, U),
    SeedExercise("Incline barbell bench press", "chest", "barbell", S, 5.0, 2.5, U),
    SeedExercise("Dumbbell bench press", "chest", "dumbbell", S, 5.0, 2.0, U),
    SeedExercise("Incline dumbbell press", "chest", "dumbbell", S, 5.0, 2.0, U),
    SeedExercise("Dumbbell fly", "chest", "dumbbell", S, 3.5, 2.0, U),
    SeedExercise("Machine chest press", "chest", "machine", S, 4.5, 2.5, U),
    SeedExercise("Cable crossover", "chest", "cable", S, 3.5, 2.5, U),
    SeedExercise("Push-up", "chest", "bodyweight", B, 3.8, 0, U, True),
    SeedExercise("Incline push-up", "chest", "bodyweight", B, 3.5, 0, U),
    SeedExercise("Band chest press", "chest", "band", S, 3.5, 1.0, U),
    # back
    SeedExercise("Barbell row", "back", "barbell", S, 5.0, 2.5, U),
    SeedExercise("Deadlift", "back", "barbell", S, 6.0, 2.5, F),
    SeedExercise("Pull-up", "back", "bodyweight", B, 4.0, 0, U, True),
    SeedExercise("Lat pulldown", "back", "cable", S, 4.0, 2.5, U),
    SeedExercise("Seated cable row", "back", "cable", S, 4.0, 2.5, U),
    SeedExercise("One-arm dumbbell row", "back", "dumbbell", S, 4.5, 2.0, U),
    SeedExercise("Machine row", "back", "machine", S, 4.0, 2.5, U),
    SeedExercise("Inverted row", "back", "bodyweight", B, 4.0, 0, U),
    SeedExercise("Superman", "back", "none", B, 3.0, 0, F),
    SeedExercise("Band pull-apart", "back", "band", S, 3.0, 1.0, U),
    # shoulders
    SeedExercise("Overhead press", "shoulders", "barbell", S, 5.0, 2.5, U),
    SeedExercise("Dumbbell shoulder press", "shoulders", "dumbbell", S, 4.5, 2.0, U),
    SeedExercise("Dumbbell lateral raise", "shoulders", "dumbbell", S, 3.5, 1.0, U),
    SeedExercise("Machine shoulder press", "shoulders", "machine", S, 4.5, 2.5, U),
    SeedExercise("Face pull", "shoulders", "cable", S, 3.5, 2.5, U),
    SeedExercise("Pike push-up", "shoulders", "bodyweight", B, 4.0, 0, U),
    # biceps
    SeedExercise("Barbell curl", "biceps", "barbell", S, 3.5, 2.5, U),
    SeedExercise("Dumbbell curl", "biceps", "dumbbell", S, 3.5, 2.0, U),
    SeedExercise("Cable curl", "biceps", "cable", S, 3.5, 2.5, U),
    SeedExercise("Chin-up", "biceps", "bodyweight", B, 4.0, 0, U, True),
    # triceps
    SeedExercise("Triceps pushdown", "triceps", "cable", S, 3.5, 2.5, U),
    SeedExercise("Skull crusher", "triceps", "barbell", S, 3.5, 2.5, U),
    SeedExercise("Overhead dumbbell extension", "triceps", "dumbbell", S, 3.5, 2.0, U),
    SeedExercise("Bench dip", "triceps", "bodyweight", B, 3.8, 0, U, True),
    SeedExercise("Diamond push-up", "triceps", "bodyweight", B, 4.0, 0, U),
    # forearms
    SeedExercise("Wrist curl", "forearms", "dumbbell", S, 2.5, 1.0, U),
    SeedExercise("Farmer's carry", "forearms", "dumbbell", T, 4.5, 2.0, F),
    # core
    SeedExercise("Crunch", "core", "bodyweight", B, 3.8, 0, F),
    SeedExercise("Hanging leg raise", "core", "bodyweight", B, 4.0, 0, F),
    SeedExercise("Cable crunch", "core", "cable", S, 3.8, 2.5, F),
    SeedExercise("Russian twist", "core", "bodyweight", B, 3.8, 0, F),
    SeedExercise("Dead bug", "core", "bodyweight", B, 3.0, 0, F),
    SeedExercise("Bicycle crunch", "core", "bodyweight", B, 3.8, 0, F),
    SeedExercise("Plank", "core", "none", T, 3.0, 0, F),
    SeedExercise("Side plank", "core", "none", T, 3.0, 0, F),
    # quads
    SeedExercise("Barbell back squat", "quads", "barbell", S, 6.0, 2.5, L),
    SeedExercise("Front squat", "quads", "barbell", S, 6.0, 2.5, L),
    SeedExercise("Leg press", "quads", "machine", S, 5.0, 5.0, L),
    SeedExercise("Leg extension", "quads", "machine", S, 3.5, 2.5, L),
    SeedExercise("Goblet squat", "quads", "dumbbell", S, 5.0, 2.0, L),
    SeedExercise("Dumbbell lunge", "quads", "dumbbell", S, 5.0, 2.0, L),
    SeedExercise("Bulgarian split squat", "quads", "dumbbell", S, 5.0, 2.0, L),
    SeedExercise("Bodyweight squat", "quads", "bodyweight", B, 5.0, 0, L, True),
    SeedExercise("Walking lunge", "quads", "bodyweight", B, 4.0, 0, L, True),
    SeedExercise("Wall sit", "quads", "none", T, 3.5, 0, L),
    # hamstrings
    SeedExercise("Romanian deadlift", "hamstrings", "barbell", S, 5.0, 2.5, L),
    SeedExercise("Dumbbell Romanian deadlift", "hamstrings", "dumbbell", S, 5.0, 2.0, L),
    SeedExercise("Lying leg curl", "hamstrings", "machine", S, 3.5, 2.5, L),
    SeedExercise("Nordic curl", "hamstrings", "bodyweight", B, 4.0, 0, L),
    SeedExercise("Single-leg Romanian deadlift", "hamstrings", "bodyweight", B, 4.0, 0, L),
    # glutes
    SeedExercise("Barbell hip thrust", "glutes", "barbell", S, 4.5, 2.5, L),
    SeedExercise("Glute bridge", "glutes", "bodyweight", B, 3.0, 0, L, True),
    SeedExercise("Single-leg glute bridge", "glutes", "bodyweight", B, 3.5, 0, L),
    SeedExercise("Banded lateral walk", "glutes", "band", S, 3.5, 1.0, L),
    # calves
    SeedExercise("Standing calf raise", "calves", "machine", S, 3.0, 2.5, L),
    SeedExercise("Bodyweight calf raise", "calves", "bodyweight", B, 2.8, 0, L),
    # full body
    SeedExercise("Burpee", "full_body", "bodyweight", B, 8.0, 0, F),
    SeedExercise("Dumbbell thruster", "full_body", "dumbbell", S, 6.0, 2.0, F),
    SeedExercise("Mountain climber", "full_body", "bodyweight", B, 8.0, 0, F),
    # cardio (timed)
    SeedExercise("Treadmill run", "cardio", "cardio_machine", T, 9.8, 0, C),
    SeedExercise("Treadmill walk", "cardio", "cardio_machine", T, 4.3, 0, C),
    SeedExercise("Stationary bike", "cardio", "cardio_machine", T, 7.0, 0, C),
    SeedExercise("Rowing machine", "cardio", "cardio_machine", T, 7.0, 0, C),
    SeedExercise("Elliptical", "cardio", "cardio_machine", T, 5.0, 0, C),
    SeedExercise("Jump rope", "cardio", "none", T, 11.0, 0, C),
    SeedExercise("Jumping jacks", "cardio", "none", T, 8.0, 0, C),
    SeedExercise("High knees", "cardio", "none", T, 8.0, 0, C),
    SeedExercise("Outdoor running", "cardio", "none", T, 9.8, 0, C),
    SeedExercise("Brisk walking", "cardio", "none", T, 4.3, 0, C),
)


def load_exercises(session: Session) -> int:
    """Insert the seed exercises that are missing. Returns how many rows were inserted."""
    existing_names = set(
        session.scalars(select(func.lower(Exercise.name)).where(Exercise.owner_id.is_(None)))
    )
    ids = {item.name: uuid.uuid5(_NAMESPACE, item.name.lower()) for item in SEED_EXERCISES}
    existing_ids = set(session.scalars(select(Exercise.id).where(Exercise.id.in_(ids.values()))))
    inserted = 0
    for item in SEED_EXERCISES:
        if item.name.lower() in existing_names or ids[item.name] in existing_ids:
            continue
        session.add(
            Exercise(
                id=ids[item.name],
                owner_id=None,
                name=item.name,
                muscle_group=item.muscle_group,
                equipment=item.equipment,
                type=item.type,
                met=item.met,
                increment_kg=item.increment_kg,
                region=item.region,
                allows_added_weight=item.allows_added_weight,
            )
        )
        inserted += 1
    session.flush()
    return inserted
