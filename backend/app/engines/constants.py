"""The single home for engine constants (formula coefficients, thresholds, step sizes).

Each engine issue (F3, F5, F7, F11, F13, F14) adds its constants here with a comment pointing to
the spec section that defines them, so tuning a rule never means hunting through engine code.
"""

# --- F13.2 Exercise kcal (issue #84) -----------------------------------------------------------
# kcal = MET × 3.5 × body_weight_kg ÷ 200 × minutes (spec F13.2).
# Planned weekly kcal ÷ 7 feeds the F3.4 daily target.

# Resting oxygen uptake in ml O2 per kg per minute (1 MET).
MET_O2_ML_PER_KG_MIN = 3.5
# ml O2/min → kcal/min: ≈ 5 kcal per litre of O2 and 1000 ml per litre, so 5 ÷ 1000 = 1 ÷ 200.
MET_KCAL_DIVISOR = 200.0
# Estimated working time per strength/bodyweight set, added to its rest (spec F13.2).
WORKING_SECONDS_PER_SET = 45
# Rest assumed for a logged set that has no planned rest (extra exercises; spec F10 default rest).
DEFAULT_REST_SECONDS = 90
# Planned weekly exercise kcal is spread evenly over the week for the daily target (spec F3.4).
PLANNED_EXERCISE_KCAL_DAYS = 7
# --- end F13.2 ---------------------------------------------------------------------------------

# ============================================================================================
# F3 Targets engine (#21) — used by app/engines/targets.py. Keep this block self-contained:
# other engines append their own blocks below it.
# ============================================================================================

# F3.1 Katch-McArdle: BMR = 370 + 21.6 × LBM_kg.
KATCH_MCARDLE_INTERCEPT_KCAL = 370.0
KATCH_MCARDLE_KCAL_PER_KG_LBM = 21.6

# F3.1 Mifflin-St Jeor: BMR = 10·kg + 6.25·cm − 5·age + s.
MIFFLIN_KCAL_PER_KG = 10.0
MIFFLIN_KCAL_PER_CM = 6.25
MIFFLIN_KCAL_PER_YEAR = -5.0
# F3.1 sex constant s; "unspecified" (prefer not to say) uses the midpoint.
MIFFLIN_SEX_CONSTANT_KCAL: dict[str, float] = {
    "male": 5.0,
    "female": -161.0,
    "unspecified": -78.0,
}

# F3.2 lifestyle (non-exercise) activity factors. Training kcal are added separately.
LIFESTYLE_FACTORS: dict[str, float] = {
    "sedentary": 1.20,
    "lightly_active": 1.30,
    "active": 1.45,
    "very_active": 1.60,
}

# F3.3 US Navy body-fat estimate (cm, log10): BF% = 495 / (a − b·log10(x) + c·log10(height)) − 450,
# with x = waist − neck (male) or waist + hip − neck (female / unspecified).
NAVY_NUMERATOR = 495.0
NAVY_OFFSET = 450.0
NAVY_MALE_COEFFICIENTS = (1.0324, 0.19077, 0.15456)
NAVY_FEMALE_COEFFICIENTS = (1.29579, 0.35004, 0.22100)

# F3.4 goal adjustment (fraction of baseline + planned exercise).
GOAL_ADJUSTMENTS: dict[str, float] = {
    "cutting": -0.20,
    "recomposition": -0.10,
    "muscle_gain": 0.10,
    "maintenance": 0.0,
    "wellness": 0.0,
}
# F3.4 protein per goal (g per kg body weight).
PROTEIN_G_PER_KG: dict[str, float] = {
    "cutting": 2.2,
    "recomposition": 2.2,
    "muscle_gain": 1.8,
    "maintenance": 1.6,
    "wellness": 1.4,
}
# F3.4 planned exercise kcal are given per week (F13.2) and averaged over 7 days.
DAYS_PER_WEEK = 7

# F3.5 macros: fat = max(25 % of target kcal, 0.6 g/kg); carbs = the rest (minimum 0).
FAT_SHARE_OF_KCAL = 0.25
FAT_MIN_G_PER_KG = 0.6
# F3.5 energy per gram.
KCAL_PER_G_PROTEIN = 4.0
KCAL_PER_G_CARBS = 4.0
KCAL_PER_G_FAT = 9.0

# F3.6 calorie floor per sex (kcal/day).
CALORIE_FLOOR_KCAL: dict[str, int] = {
    "male": 1500,
    "female": 1200,
    "unspecified": 1350,
}

# ============================================================================================
# F11 Progression engine v1 (#31) - used by app/engines/progression.py.
# ============================================================================================

# F11 plate step by equipment (kg); dumbbells 2 kg, everything else 2.5 kg. Imperial users 5 lb.
PLATE_STEP_KG_DEFAULT = 2.5
PLATE_STEP_KG_BY_EQUIPMENT: dict[str, float] = {"dumbbell": 2.0}
KG_PER_LB = 0.45359237
PLATE_STEP_LB = 5.0
# F11 minimum weight (D56): the empty bar for barbell exercises (45 lb shown to imperial users).
MIN_WEIGHT_KG_BY_EQUIPMENT: dict[str, float] = {"barbell": 20.0}
# F11 deload: this many consecutive failing sessions at the same weight trigger a deload.
DELOAD_FAILING_SESSIONS = 3
# F11 deload weight = this share of the current weight, rounded down to the plate step.
DELOAD_FACTOR = 0.9
# F11 timed / cardio: duration grows by this share when every set was completed.
TIMED_PROGRESSION_FACTOR = 0.10
# F11 duration rounding (seconds): 5 s for holds, 1 min for cardio (equipment cardio_machine).
TIMED_ROUNDING_SECONDS = 5
CARDIO_ROUNDING_SECONDS = 60
