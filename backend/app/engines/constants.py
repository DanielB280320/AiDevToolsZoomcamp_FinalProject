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
