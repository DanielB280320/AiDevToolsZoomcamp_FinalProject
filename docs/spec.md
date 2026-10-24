# FitWise — Product & Technical Specification (MVP)

| | |
|---|---|
| **Status** | Draft v1 — ready for backlog grooming |
| **Date** | 2026-10-21 |
| **Owner** | DanielB280320 |
| **Context** | Final project, AI Dev Tools Zoomcamp 2026 ([criteria](https://github.com/DataTalksClub/ai-dev-tools-zoomcamp/tree/main/project)) |

---

## 1. Problem

Most people who start training cannot afford a personal trainer. They end up tracking workouts in notes apps or spreadsheets, guessing what weight to lift next, eating without knowing whether it matches their goal, and never seeing whether they actually followed their plan. Experienced lifters have the opposite problem: their data is scattered across several apps (one for workouts, one for food, one for body weight) and nothing ties it together.

**FitWise** is a single source of truth for training and nutrition:

1. A new user registers their body metrics, lifestyle and goal.
2. FitWise calculates their calorie and macro targets and **suggests a weekly training plan and meal plan**.
3. Every day, the user opens the calendar, sees **today's workout and meals**, logs what they actually did and ate, and checks items off.
4. FitWise compares **planned vs. actual** performance, estimates **calories eaten vs. burned**, and suggests (with an explained reason) **what to do next session** — acting as a free, rule-based coach.
5. Users can switch to **custom mode** and design their own training and meal plans.
6. Users who have a human coach can link to them; the coach sees the same data and charts, edits the plan and leaves notes.

All guidance is produced by **deterministic, explainable rules** (no AI/LLM in the product), which keeps it free to run, testable and transparent.

> FitWise is not a medical product. All numbers are estimates. See §6.3.

## 2. Goals and non-goals

### 2.1 Goals (MVP)
- G1. A user can go from sign-up to a complete, personalised weekly training + meal plan in under 5 minutes.
- G2. Logging a set or checking off a meal takes at most 2 taps on a phone.
- G3. Every suggestion (calories, weights, reps, adjustments) shows the rule and numbers that produced it.
- G4. Athletes and their coaches can see planned vs. actual performance per day and over time.
- G5. The system is production-ready per the course criteria: tests, containers, dev/prod deployment on AWS, CI/CD with manual prod promotion and rollback, observability, user-impact alerts and an on-call agent.

### 2.2 Non-goals (MVP)
- Payments, subscriptions or a coach marketplace (roadmap, §17).
- AI/LLM features, including body-fat estimation from photos (roadmap).
- Native mobile apps, offline mode, push/email notifications, chat.
- Medical advice, injury diagnosis, or handling of medical conditions.
- Wearable or third-party fitness app integrations.

## 3. Users and roles

| Role | Description | How created |
|---|---|---|
| **Athlete** | Trains and eats according to a plan; logs everything. Self-coached by default. | Chooses "I'm an athlete" at sign-up |
| **Coach** | Supervises linked athletes: views their data, edits their plans, accepts/rejects suggestions, leaves notes. Cannot log on an athlete's behalf. Does not train inside FitWise (a coach who also trains uses a separate athlete account). | Chooses "I'm a coach" at sign-up |

Roles are fixed per account. An athlete has **at most one active coach**. A coach can have many athletes.

### 3.1 Personas
- **Ana, beginner (athlete):** wants to lose fat, has never followed a program, trains at home with dumbbells 3×/week, cannot afford a trainer.
- **Marco, experienced (athlete):** bulking, trains 5×/week at a gym, wants one place for lifts, food and body weight.
- **Lucía, personal trainer (coach):** has 10 clients who send her screenshots; wants to see their adherence and stalls in one dashboard.

## 4. Glossary

| Term | Meaning |
|---|---|
| **Plan** | An athlete's active weekly template: training days + meal days. Repeats every week. Source is `generated` or `custom`. |
| **Session** | A dated instance of a planned training day (e.g. "Upper A on 2026-11-03"). |
| **Working set** | A planned set with target reps/weight (or duration). |
| **Set log** | What was actually performed for a set. |
| **Completion** | Actual ÷ target for a set, exercise, session or day, capped at 100 %. |
| **Suggestion** | A proposed change computed by an engine (next-session targets, calorie adjustment) awaiting accept/reject. |
| **BMR / TDEE** | Basal metabolic rate / total daily energy expenditure. |
| **MET** | Metabolic equivalent of a task, used to estimate exercise calories. |
| **Lifestyle factor** | Multiplier for non-exercise daily activity (job, walking). Excludes training to avoid double counting. |

## 5. Functional requirements

Each requirement has an ID used by the backlog (GitHub Issues). Priority uses MoSCoW (see §16). Acceptance criteria (AC) are written to be directly testable.

### F1. Accounts and authentication — *Must*

- Sign up with email, password, display name, role (athlete/coach), date of birth, preferred units (metric/imperial) and time zone.
- Sign in / sign out. Passwords hashed (argon2id). Session via JWT in an `HttpOnly`, `SameSite=Lax` cookie, 24 h expiry.
- Rate limit: 5 failed sign-ins per email per 15 min.

**AC**
- [ ] F1.1 Sign-up rejects users younger than 18 (computed from date of birth in the user's time zone) with a clear message.
- [ ] F1.2 Sign-up requires accepting the disclaimer (§6.3); acceptance timestamp is stored.
- [ ] F1.3 Duplicate email (case-insensitive) is rejected.
- [ ] F1.4 Password must be ≥ 10 characters.
- [ ] F1.5 Protected API endpoints return 401 without a valid session; role-restricted endpoints return 403 for the wrong role.
- [ ] F1.6 The 6th failed sign-in within 15 min returns 429 (lockout semantics: D49).

### F2. Onboarding and profile (athlete) — *Must*

A step-by-step wizard after first sign-in. All values editable later in Profile.

| Field | Required | Notes |
|---|---|---|
| Sex for calculations | Yes | `male`, `female`, `prefer not to say` (uses midpoint constants) |
| Height | Yes | cm or ft/in |
| Weight | Yes | kg or lb |
| Body fat % | No | Known value, **or** Navy tape method (F3.3), **or** skip |
| Neck / waist / hip | No | Required only when using the Navy method (hip for female/unspecified) |
| Lifestyle (non-exercise) activity | Yes | Sedentary / Lightly active / Active / Very active (see F3.2) |
| Goal | Yes | Body recomposition, Muscle gain, Cutting, Maintenance, Overall wellness |
| Experience | Yes | Beginner (< 6 months), Intermediate (6 months–2 years), Advanced (> 2 years) |
| Training days per week | Yes | 2–6 |
| Preferred training days | Yes | Weekdays to place sessions on (count must match) |
| Session length | Yes | 30 / 45 / 60 / 75 / 90 min |
| Equipment | Yes | Full gym, Home dumbbells, Bodyweight only |
| Exercises to avoid | No | Pick from catalog (injuries/limitations) |
| Diet preference | Yes | Omnivore, Vegetarian, Vegan, Pescatarian |
| Allergies / exclusions | No | Gluten, Lactose, Nuts, Eggs, Soy, Shellfish, Fish |
| Meals per day | Yes | 3, 4 or 5 |

**AC**
- [ ] F2.1 Completing the wizard stores a `BodyMetric` entry (weight, optional body fat, optional measurements) dated today.
- [ ] F2.2 Completing the wizard computes targets (F3) and generates a plan (F5 + F7) in one action; the user lands on the Today view.
- [ ] F2.3 Values outside plausible ranges are rejected (height 120–230 cm, weight 35–300 kg, body fat 3–60 %, measurements 20–200 cm).
- [ ] F2.4 Number of preferred training days must equal training days per week.
- [ ] F2.5 Units shown follow the user's setting; values are stored in metric.
- [ ] F2.6 If the Navy method (F3.3) yields a body fat outside 3–60 %, the result is ignored (not stored as the body fat), the targets fall back to Mifflin-St Jeor (F3.1) and the explanation says so (D55).

### F3. Calculation engine (targets) — *Must*

Pure functions with no I/O; every output includes a human-readable explanation. Constants live in one configuration module.

**F3.1 BMR**
- Body fat known (entered or Navy): **Katch-McArdle** — `BMR = 370 + 21.6 × LBM_kg`, `LBM = weight × (1 − bf%)`.
- Otherwise (including when the Navy estimate is outside 3–60 %, which is ignored, D55) **Mifflin-St Jeor** — `BMR = 10·kg + 6.25·cm − 5·age + s`, where `s = +5` (male), `−161` (female), `−78` (prefer not to say).

**F3.2 Baseline (non-exercise) expenditure** — `baseline = BMR × lifestyle_factor`

| Lifestyle | Factor | Example |
|---|---|---|
| Sedentary | 1.20 | Desk job, little walking |
| Lightly active | 1.30 | Desk job + daily walks |
| Active | 1.45 | On your feet most of the day |
| Very active | 1.60 | Physical labour |

Training calories are **not** included in the lifestyle factor; they are added from the plan (targets) or from logs (actuals). This prevents double counting.

**F3.3 Navy body-fat estimate** (cm, log base 10)
- Male: `495 / (1.0324 − 0.19077·log10(waist − neck) + 0.15456·log10(height)) − 450`
- Female / unspecified: `495 / (1.29579 − 0.35004·log10(waist + hip − neck) + 0.22100·log10(height)) − 450`

**F3.4 Daily calorie target**
`target = (baseline + avg_daily_planned_exercise_kcal) × (1 + goal_adjustment)`, where `avg_daily_planned_exercise_kcal` = planned weekly exercise kcal (F13.2) ÷ 7.

| Goal | Adjustment | Protein (g/kg body weight) |
|---|---|---|
| Cutting | −20 % | 2.2 |
| Body recomposition | −10 % | 2.2 |
| Muscle gain | +10 % | 1.8 |
| Maintenance | 0 % | 1.6 |
| Overall wellness | 0 % | 1.4 |

**F3.5 Macros**
- Protein from the table above.
- Fat = 25 % of target kcal, but never below 0.6 g/kg.
- Carbohydrates = remaining kcal ÷ 4 (minimum 0).
- Energy: protein 4 kcal/g, carbs 4 kcal/g, fat 9 kcal/g.

**F3.6 Calorie floor** — the target is never below 1500 kcal (male), 1200 kcal (female), 1350 kcal (unspecified). When the floor applies, the explanation says so.

**AC**
- [ ] F3.1 Unit tests cover each formula with published reference examples (tolerance ± 1 kcal / ± 0.5 % BF).
- [ ] F3.2 Katch-McArdle is used if and only if a body-fat value exists.
- [ ] F3.3 Floor is applied and explained when the computed target falls below it.
- [ ] F3.4 Macro kcal sum equals target kcal ± 1 % (except when carbs are clamped at 0, which is explained).
- [ ] F3.5 Every result exposes `explanation` text listing the formula and inputs used.
- [ ] F3.6 A Navy body-fat result outside 3–60 % is ignored: BMR uses Mifflin-St Jeor and the explanation states that the Navy estimate was out of range and ignored (D55).

### F4. Exercise catalog — *Must*

- Seeded with 60–80 exercises. Each has: name, primary muscle group, equipment (`barbell`, `dumbbell`, `machine`, `cable`, `bodyweight`, `band`, `cardio_machine`, `none`), type (`strength`, `bodyweight`, `timed`), MET value, default load increment (kg) and body region (upper/lower/full/cardio).
- Athletes and coaches can create **custom exercises** (private to the creator and, for coaches, usable in their athletes' plans).

**AC**
- [ ] F4.1 Seed data loads idempotently in the migration step (§11, D50); running it again changes nothing.
- [ ] F4.2 Catalog is searchable by name and filterable by muscle group, equipment and type.
- [ ] F4.3 Custom exercises are not visible to unrelated users.

### F5. Training plan generator — *Must*

Input: experience, goal, training days/week, preferred days, session length, equipment, exercises to avoid. Output: a `Plan` with `TrainingDay`s placed on the preferred weekdays.

| Days/week | Split |
|---|---|
| 2–3 | Full body (A/B alternating) |
| 4 | Upper / Lower (×2) |
| 5 | Upper / Lower / Push / Pull / Legs |
| 6 | Push / Pull / Legs (×2) |

Each split has variants for **Full gym**, **Home dumbbells** and **Bodyweight only**.

Rep ranges and cardio by goal:

| Goal | Main lifts | Accessories | Cardio added per session |
|---|---|---|---|
| Muscle gain | 6–10 | 8–12 | 0–10 min |
| Body recomposition | 6–10 | 10–15 | 10 min |
| Cutting | 6–10 | 10–15 | 15–20 min |
| Maintenance | 6–12 | 10–15 | 10 min |
| Overall wellness | 8–12 | 12–15 | 20 min |

- Working sets per exercise: beginner 2–3, intermediate 3–4, advanced 3–5. Exercises per session scale with session length.
- **Estimated session duration** (D54): `Σ over exercises (sets × (rest_seconds + 45 s)) + cardio minutes + 5 min warm-up`. The 45 s is the assumed working time per set; the default `rest_seconds` is 90.
- Default progression rule: **linear** for beginners' main lifts, **double progression** otherwise; **deload** enabled for both. Under linear progression the fixed target reps are the **middle of the rep range**, rounded down if not an integer (e.g. 8 for 6–10, 9 for 6–12; D54).
- **Equipment per variant** (engine constant `EQUIPMENT_BY_VARIANT`, same mapping as the F4.1 seed-coverage test): Full gym = every equipment; Home dumbbells = `dumbbell`, `bodyweight`, `band`, `none`; Bodyweight only = `bodyweight`, `none`.
- **Engine choices inside the ranges** (constants in `app/engines/constants.py`): sets (main/accessory) beginner 3/2, intermediate 4/3, advanced 5/3, retried at 2/3/3 when an exercise does not fit the remaining time; rest 90 s; cardio per session 5 min (muscle gain), 10 (recomposition, maintenance), 15 (cutting), 20 (wellness). Exercises are added in priority order until the session length is used, so longer sessions hold more. Only when a 30-minute session could not hold even one exercise (wellness, intermediate/advanced) is cardio shortened in 5-minute steps (20 to 15).
- **Engine selection rules** (generator choices the ranges leave open):
  - *Exercise ranking:* main lifts take the highest MET first, accessories the lowest MET first; ties break by name, then id; exercises not yet used in the plan are preferred, so repeated days vary.
  - *Full-gym accessory equipment* (D60): in the Full gym variant, accessory slots rank by equipment tier first (engine constant `ACCESSORY_PREFERRED_EQUIPMENT`): `machine` and `cable`, then `dumbbell`, `barbell`, `bodyweight`, `band`. Inside a tier the ranking above applies, and the tier outranks "not yet used in the plan". A slot falls back to the other equipment only when no machine or cable exercise is left for it that day. Main lifts, Home dumbbells and Bodyweight only are unchanged.
  - *Linear progression* applies only to strength-type main lifts of beginners; bodyweight main lifts use double progression with the rep range.
  - *Cardio entries* are one set with `target_seconds` (cardio minutes x 60) and no rest.
  - *Bodyweight fallback* (F5.6) considers equipment `bodyweight` only, not `none`.
  - *Empty slots:* a slot with no usable exercise (none left in the variant, or all already used that day) is skipped, so some sessions are shorter than the length allows.
- **Calibration (starting weights):** generated targets have no weight in week 1 ("choose a weight you can do for the target reps with 2 reps left"). The first logged weight becomes the baseline.
- Exercises on the user's "avoid" list are replaced by the nearest alternative (same muscle group and equipment). If there is none, fall back to a **bodyweight** exercise of the same muscle group; if there is none either, the exercise is dropped and the plan carries a warning naming the dropped exercise (D54).

**AC**
- [ ] F5.1 For every (days, equipment) combination the generator returns a valid plan whose sessions fit the session length (estimated duration ≤ chosen length).
- [ ] F5.2 Avoided exercises never appear in the generated plan.
- [ ] F5.3 Sessions are placed exactly on the user's preferred weekdays.
- [ ] F5.4 Week-1 strength targets have empty weight and show the calibration hint.
- [ ] F5.5 The generator is deterministic for the same inputs (snapshot tests).
- [ ] F5.6 An avoided exercise with no same-muscle/same-equipment alternative is replaced by a bodyweight exercise of the same muscle group; if none exists it is dropped and the plan returns a warning (D54).

### F6. Foods and meals — *Must*

- **Food**: name, kcal / protein / carbs / fat per 100 g, diet tags, allergen tags, source (`seed`, `custom`, `openfoodfacts`).
- **Meal**: name, slot tags (`breakfast`, `lunch`, `dinner`, `snack`), list of `(food, grams)`; macros computed from foods.
- Seeded library: ~50 meals covering all slots and diet preferences.
- **Custom foods and meals** can be created by athletes and coaches.
- **Open Food Facts search**: text search for packaged foods. A selected result is copied into the local `Food` table (source `openfoodfacts`, with its product code) so it never needs to be fetched again.
  - Requests use a descriptive `User-Agent` (`FitWise/<version> (<contact>)`), a 3 s timeout and a server-side cache of search results (24 h).
  - Behind the feature flag `off_search_enabled`. When disabled or failing, the UI says "Online food search is unavailable — use the library or create a custom food" and everything else keeps working.

**AC**
- [ ] F6.1 Meal macros equal the sum of `food_per_100g × grams / 100` (unit-tested).
- [ ] F6.2 A food imported from Open Food Facts is stored once (unique on product code) and reused.
- [ ] F6.3 Open Food Facts timeout or 5xx returns a handled "unavailable" response, never a 500 from FitWise.
- [ ] F6.4 Integration tests use a fake Open Food Facts server; no real network calls in CI.
- [ ] F6.5 Foods with excluded allergens or conflicting diet tags are not offered by the generator.

### F7. Meal plan generator — *Must*

Input: daily kcal/macro targets, meals per day, diet preference, allergies. Output: 7 `MealDay`s, each with one meal per slot.

Slot calorie split:

| Meals/day | Split |
|---|---|
| 3 | Breakfast 25 % · Lunch 35 % · Dinner 40 % |
| 4 | Breakfast 25 % · Lunch 30 % · Snack 15 % · Dinner 30 % |
| 5 | Breakfast 20 % · Snack 10 % · Lunch 30 % · Snack 10 % · Dinner 30 % |

Rules:
- Candidate meals must match the slot, diet preference and allergy exclusions.
- Portions are scaled by a factor between 0.75 and 1.5 to fit the slot's kcal.
- Each day's total kcal is within **± 5 %** of the target; protein ≥ 90 % of target.
- The same meal appears **at most 2 times per week**.
- Selection uses a seeded pseudo-random generator (`seed = user_id + ISO week`) so results are reproducible in tests.
- If no feasible combination exists, the best attempt is returned with a visible warning ("Couldn't hit your protein target with the current library — add custom meals").
- Training days and rest days use the same target in the MVP.

**AC**
- [ ] F7.1 Property test: for random valid inputs, every generated day is within ± 5 % kcal or carries the warning.
- [ ] F7.2 No meal appears more than twice in a generated week.
- [ ] F7.3 Diet and allergy filters are never violated.
- [ ] F7.4 Same inputs + same seed → same plan.

### F8. Custom mode (plan editor) — *Must*

The generated plan is a starting point. Athletes (and their linked coach) can edit everything:

- Training: add/remove/reorder training days and exercises; set sets, target reps (fixed or range), target weight or duration, rest time, progression rule (`linear`, `double`, `manual`) and increment per exercise; enable/disable deload.
- Meals: add/remove/replace meals per slot and day; change grams; create custom foods/meals.
- "Regenerate suggested plan": creates a new plan version from the current profile; previous versions are kept (read-only) for history.
- Any manual edit sets the plan `source` to `custom`. Edits by a coach are labelled "edited by <coach name>".

**AC**
- [ ] F8.1 Editing the plan affects only today-and-future sessions; past sessions and logs never change.
- [ ] F8.2 Regenerating keeps the previous version and its history accessible.
- [ ] F8.3 Plan changes are recorded with author (athlete/coach) and timestamp.
- [ ] F8.4 A coach can edit only plans of athletes with an active link to them.

### F9. Calendar — *Must*

- **Today view** (home screen): today's session (exercises with sets to log) and meals (with check-offs), today's energy balance (F13), pending suggestions, coach notes.
- **Week view**: 7 days (Monday-start) with sessions, meals and completion status per day.
- **Month view**: per-day status badges (training ✅/⚠️/❌/rest, nutrition completion %).
- The weekly plan repeats indefinitely; sessions are materialised for a date when first viewed or logged.
- **Missed sessions**: a planned session with no logs whose date has passed (in the user's time zone) is shown as *missed* and counts against adherence.
- **Moving a session**: the athlete can move a session to another day **within the same ISO week** (one session per day max). Moving does not change the template.

**AC**
- [ ] F9.1 "Today" is calculated in the user's time zone.
- [ ] F9.2 A session moved to Thursday shows on Thursday and not on its original day; adherence counts it as done if logged on Thursday.
- [ ] F9.3 Past days with no logs show as missed; rest days never show as missed.
- [ ] F9.4 Week and Month views load in < 500 ms p95 for a user with 1 year of data (seeded perf test).

### F10. Training logging — *Must*

- For each planned set: enter actual reps and weight (strength), reps and optional added weight (bodyweight), or duration and optional distance (timed/cardio). "Done as planned" fills targets in one tap.
- Add extra sets or exercises not in the plan; skip a set/exercise.
- Rest timer after each set (planned rest, default 90 s).
- **Finish workout**: closes the session, records start/end time, computes completion and calories (F13), and triggers the progression engine (F11).
- **Extra activities**: log off-plan activities (e.g. football 60 min, cycling 30 min) from the timed/cardio catalog on any day; counted in calories burned.

**AC**
- [ ] F10.1 Logging a set is idempotent per (session, exercise, set number) — retrying the same request doesn't duplicate it.
- [ ] F10.2 Session completion = Σ min(actual, target) ÷ Σ target over planned working sets (reps × weight-agnostic; duration for timed).
- [ ] F10.3 A session can be edited after finishing (same day + 1 day); edits recompute completion and suggestions.
- [ ] F10.4 Extra activities appear in the day's burned calories but not in training completion.

### F11. Progression engine — *Must*

Runs per exercise when a session is finished. Pure functions; each output has a reason string.

| Rule | Logic |
|---|---|
| **Linear** | Fixed target reps. All working sets ≥ target reps at target weight → next weight = weight + increment. Otherwise keep. |
| **Double progression** | Rep range [min, max]. All working sets ≥ max reps at target weight → weight + increment and target reps reset to min. Otherwise keep weight; target reps = min(max, best reps achieved + 1). |
| **Deload** (modifier) | 3 consecutive finished sessions failing the target at the same weight → next weight = 90 % rounded down to the plate step. Counter resets after a deload or a success. |
| **Manual** | No suggestions. |
| **Bodyweight** | Reps progress like double progression; at the top of the range suggest "+ added weight" (if the exercise allows) or "ready for a harder variation". |
| **Timed / cardio** | All sets completed → duration + 10 % (rounded to 5 s for holds, 1 min for cardio). |
| **Calibration** | After the first logged session of an exercise, the suggestion sets the target weight to the weight used. |

- **Rounding**: to the exercise's plate step (default 2.5 kg barbell/machine, 2 kg dumbbell; imperial users 5 lb / 5 lb), never below the minimum weight.
- **Minimum weight** (D56): barbell exercises 20 kg (the empty bar; displayed as 45 lb for imperial users), all other equipment 0.
- **Bodyweight "added weight"** (D56): at the top of the rep range the engine suggests "+ added weight" only when the exercise has `allows_added_weight = true`; otherwise "ready for a harder variation".
- **Calibration with mixed weights** (D56): if the first session used several weights, the target weight is the weight used on the most sets; ties are broken by the heaviest weight.
- **Engine v1 definitions** (#31): *working sets* are the logged sets at the planned target weight (sets at other weights are ignored). A session *succeeds* when the planned number of working sets (sets beyond the plan are ignored) reach the top goal (fixed reps, range max, or target seconds). It *fails* (for the deload counter) when fewer than the planned number of working sets were logged or any working set is below the bottom goal (fixed reps or range min). A skipped exercise produces no suggestion and leaves the counter unchanged. If the increment is smaller than the plate step, the weight is kept. Reasons are written in the user's units.
  - **Plate grid**: starts at the minimum weight, not at 0 (barbell: 20 kg + k × plate step). For imperial users the barbell grid is 20 kg + k × 5 lb and is *displayed* as 45, 50, 55 … lb (the 20 kg bar reads 45 lb, D56). Storage stays metric; the conversion happens only when the reason is written; weights off the grid display as a plain kg→lb conversion.
  - **Caller contract**: the caller passes the consecutive-failure count and the first-session flag in; the engine returns the updated count (reset to 0 on success or deload). The engine never reads history.
  - **Cardio rounding** (1 min) applies when the equipment is `cardio_machine` or the exercise `region` is `cardio`; other timed exercises round to 5 s. If the rounded +10 % equals the current duration, the engine holds and says so.
  - **Bodyweight** exercises never deload. "Add weight" starts from the target weight (0 when none) plus one increment.
  - **Deload never adds weight**: if the target is already below the minimum weight, the engine holds at the minimum and says so.
  - A missing rep target (set-based) or duration target (timed) returns no suggestion.
- **Suggestions must be accepted**: suggestions are created with status `pending`. The athlete or the linked coach can accept, reject or edit-then-accept. Accepted values become the targets for the next sessions of that exercise. If a session starts while a suggestion is pending, it uses the current targets and shows a banner.

**AC**
- [ ] F11.1 Table-driven unit tests for every rule, including edge cases: partial sets, extra sets, skipped exercise, mixed weights within a session (uses the planned target weight), first session (calibration).
- [ ] F11.2 Property tests: a suggestion never increases weight by more than one increment; a deload never goes below the minimum weight.
- [ ] F11.3 Rejected suggestions change nothing; the next finished session generates a fresh suggestion.
- [ ] F11.4 Every suggestion stores rule, inputs and reason (e.g. "All 3 sets reached 12 reps at 40 kg → 42.5 kg × 8").
- [ ] F11.6 Calibration with mixed weights uses the weight on the most sets (tie: heaviest); no suggested weight is ever below the minimum weight; bodyweight top-of-range suggestions follow `allows_added_weight` (D56).
- [ ] F11.5 Engine version is selected by the feature flag `progression_engine` (`v1` default). Unknown versions fall back to `v1`.

### F12. Meal logging — *Must*

For each planned meal: **Eaten as planned** (one tap), **Adjust** grams per food, or **Skip**. Plus **Add food** for anything off-plan (from library, custom, or Open Food Facts).

**AC**
- [ ] F12.1 Day "eaten" totals use logged quantities only (planned-but-unlogged meals count as 0 eaten).
- [ ] F12.2 Nutrition completion for the day = planned meals marked eaten (as planned or adjusted) ÷ planned meals.
- [ ] F12.3 Check-off is idempotent per (date, planned meal).

### F13. Daily energy balance — *Must*

**F13.1 Calories burned (estimated)** = `baseline (F3.2)` + `Σ exercise kcal` from logged sessions and extra activities.

**F13.2 Exercise kcal** — `kcal = MET × 3.5 × body_weight_kg ÷ 200 × minutes`
- Timed/cardio: minutes = logged duration.
- Strength/bodyweight: minutes per exercise = sets × (rest_seconds + 45 s) ÷ 60.
- Body weight = most recent weight on or before that date.
- Planned version (for F3.4 targets) uses the same formula with planned sets and durations.

**F13.3 Display** — Today and each day in Week view show: eaten, burned, balance (eaten − burned), the goal's target balance, and macro progress bars. All values are labelled "estimated".

**AC**
- [ ] F13.1 Unit tests for the MET formula and minute estimation.
- [ ] F13.2 Changing body weight on a later date doesn't alter past days' calculations.
- [ ] F13.3 Extra activities logged on a rest day add to burned calories.

### F14. Body tracking and adaptive calories — *Must*

- Log weight on any day (one entry per day; re-logging replaces it). Optionally log body fat % or measurements (Navy method recalculates body fat).
- Chart: daily weight + **7-day moving average** trend.
- When weight changes by ≥ 2 % from the weight used for current targets, prompt the athlete to recalculate targets (shows old vs. new; accept/reject).
- **Weekly adaptive calorie suggestion** (every Monday, for the previous two complete weeks):
  - Requires ≥ 4 weigh-ins in each of the two weeks; otherwise no suggestion and a hint to weigh in more.
  - Expected weekly change: Cutting −0.75 % BW; Recomposition/Maintenance/Wellness 0 % (± 0.25 % tolerance); Muscle gain +0.25 % BW (± 0.15 % tolerance); Cutting tolerance ± 0.25 %.
  - If the 7-day-average trend is outside tolerance **in the same direction for 2 consecutive weeks**: suggest −150 kcal (losing too slowly / gaining too fast) or +150 kcal (losing too fast / gaining too slowly), never below the floor (F3.6).
  - The suggestion is `pending` until the athlete or coach accepts; accepting updates targets and regenerates **future** meal days' portions.

**AC**
- [ ] F14.1 7-day average is computed only from existing weigh-ins in the window (unit-tested with gaps).
- [ ] F14.2 No suggestion with insufficient data.
- [ ] F14.3 Suggestion direction and amount are correct for each goal (table-driven tests).
- [ ] F14.4 Accepting changes only future days.

### F15. Progress and performance charts — *Must*

Available to the athlete and to the linked coach (same views).

| View | Content | Chart |
|---|---|---|
| **Session detail** | Per exercise and set: target vs. actual reps and weight (or duration); completion per set | Grouped bars (target vs. actual) + ✅/⚠️ per set |
| **Exercise over time** | Target weight vs. actual top-set weight, total volume (Σ sets × reps × weight), personal-record markers; range 4 / 12 / 26 / 52 weeks | Line chart |
| **Adherence** | Daily training and nutrition completion % | Calendar heat map (Month view) + weekly bars |
| **Weekly summary** | Sessions done/planned, average completion, average daily balance vs. target, weight trend | Stat tiles + sparklines |
| **Body** | Weight + 7-day average, body fat if available | Line chart |

**AC**
- [ ] F15.1 Chart data comes from dedicated API endpoints that return pre-aggregated series (no raw-log aggregation in the browser).
- [ ] F15.2 Exercise history shows the planned target at the time of each session, not the current target.
- [ ] F15.3 Charts render with empty-state messages when there is no data.
- [ ] F15.4 Charts use the user's display units.

### F16. Coach mode — *Must*

**Linking**
- A coach has a profile: display name, short bio, `discoverable` toggle (default on).
- An athlete **searches coaches** by display name (min 3 characters) or exact email; results show display name and bio only (never email).
- The athlete sends a link request; the coach **approves or declines**. An athlete can have one active coach and at most one pending request.
- Either side can **end** the link at any time; access is revoked immediately.

**Coach capabilities** (only for actively linked athletes)
- Client list sorted by "needs attention": training adherence < 70 % over the last 7 days, any exercise with deload pending/applied in the last 14 days, or no logs for 3+ days.
- View everything the athlete sees: profile, targets, calendar, logs, charts, body metrics.
- Edit the athlete's plan (F8), accept/reject/edit their pending suggestions (F11, F14).
- Leave **notes** on a day, session or exercise. Notes are one-way, visible to the athlete, editable/deletable by the author.
- Cannot log sets, meals or weigh-ins on the athlete's behalf.

**AC**
- [ ] F16.1 Authorization matrix tests: a coach gets 403 for every athlete endpoint of an athlete not actively linked to them (including after the link ends).
- [ ] F16.2 Search never returns non-discoverable coaches or athletes, and never exposes emails.
- [ ] F16.3 An athlete with an active coach cannot send another request.
- [ ] F16.4 Coach logging attempts return 403.
- [ ] F16.5 "Needs attention" ordering is covered by unit tests.

### F17. In-app notifications — *Must*

An inbox (bell icon with unread count) and banners on Today. No email/push.

Events: pending progression suggestion, pending calorie adjustment, target-recalculation prompt, new coach note, link request received (coach), link request approved/declined/ended (athlete), plan edited by coach.

**AC**
- [ ] F17.1 Each event creates exactly one notification for the right recipient.
- [ ] F17.2 Opening a notification marks it read; "mark all read" works.

### F18. Data ownership — *Must*

- **Export**: one ZIP containing `profile.json`, `plan_versions.json`, and CSVs for set logs, meal logs, body metrics, extra activities and suggestions.
- **Delete account**: requires password re-entry; permanently deletes all user data, ends coach links and removes notes the user authored. A coach deleting their account ends all links; athletes' data is unaffected.

**AC**
- [ ] F18.1 Export contains only the requesting user's data (integration test with two users).
- [ ] F18.2 After deletion, no rows referencing the user remain (integration test over all tables).
- [ ] F18.3 Coaches cannot export or delete an athlete's account.

## 6. Non-functional requirements

### 6.1 Usability
- Mobile-first responsive web; primary breakpoints 360 px and 1280 px. Coach dashboard optimised for desktop, usable on mobile.
- Logging a set as planned and checking off a meal: ≤ 2 taps each from Today.
- Basic accessibility: semantic HTML, labelled inputs, keyboard navigation, WCAG AA contrast.

### 6.2 Internationalisation and units
- UI in **English** for the MVP. All UI strings go through an i18n layer (`react-i18next`) so Spanish can be added later without code changes.
- All values stored in metric (kg, cm, kcal, grams); conversion happens only at display/input.
- Dates stored in UTC; "today" and week boundaries computed in the user's time zone.

### 6.3 Safety and disclaimer
- Users must be 18+.
- Disclaimer accepted at sign-up and shown in the footer: "FitWise provides general fitness and nutrition estimates, not medical advice. Consult a professional before starting a new training or diet program."
- Calorie floor (F3.6) always enforced. All calorie and body-fat numbers labelled "estimated".

### 6.4 Security
- Passwords: argon2id. JWT secret and DB credentials from environment variables/secrets; never committed.
- Input validation with Pydantic on every endpoint; SQL only via ORM/parameterised queries.
- Authorization enforced server-side on every resource (ownership or active coach link).
- Rate limiting on auth endpoints (F1.6).
- **Known limitation — plain HTTP**: the MVP is served over HTTP on the EC2 public DNS name (no domain, no TLS). Credentials and health data are not encrypted in transit. The README must warn reviewers to use **test accounts and fake data only**. HTTPS (domain + Caddy/Let's Encrypt) is the first roadmap item. The cookie `Secure` flag is configurable and turned on once HTTPS exists.
- Dependency and secret scanning in CI (see [§13](#13-cicd-github-actions)).

### 6.5 Privacy (health data)
- Body metrics, food logs and training logs are health-related personal data.
- **Telemetry must never contain**: emails, names, passwords, tokens, body metrics (weight, height, body fat, measurements), food names or notes. User identity in telemetry = salted hash of the user ID.
- Logs are structured JSON with an allow-list of fields; a unit test asserts sensitive keys are dropped.

### 6.6 Performance and reliability targets (SLOs)
| Journey | SLO |
|---|---|
| Logging endpoints (log set, check off meal, finish workout) | 99 % success; p95 latency < 500 ms |
| Today / Week view API | p95 < 500 ms |
| Open Food Facts search | Best effort; degraded mode allowed |

## 7. Architecture

```
            Browser (React SPA, mobile-first)
                         │  HTTP (REST, OpenAPI contract)
                         ▼
   ┌──────────────── EC2 (per environment) ─────────────────┐
   │  nginx (serves SPA, proxies /api)                       │
   │      │                                                  │
   │  FastAPI backend ── SQLAlchemy ──► Postgres 16          │
   │      │  OpenTelemetry SDK                               │
   │      ▼                                                  │
   │  OTel Collector ─────────────────────────────┐          │
   └──────────────────────────────────────────────┼──────────┘
                                                  ▼ (dev → prod collector, SG-restricted)
   Prod EC2 only: Prometheus · Loki · Tempo · Grafana ──alert webhook──► On-call responder (host)
                                                                             │ headless Claude Code
                                                                             ▼
                                                     allow-listed ops scripts · GitHub issue/PR
```

### 7.1 Tech stack
| Layer | Choice |
|---|---|
| Frontend | React + TypeScript + Vite, React Router, TanStack Query, Recharts, react-i18next, Tailwind CSS |
| API contract | OpenAPI 3.1 (`openapi.yaml`) — source of truth; frontend client generated from it |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, `uv` |
| Database | PostgreSQL 16 (container) |
| Tests | pytest, Hypothesis (property tests), Vitest + React Testing Library, Playwright |
| Containers | Docker, Docker Compose |
| Cloud | AWS EC2 (dev + prod instances), images in GitHub Container Registry |
| CI/CD | GitHub Actions with GitHub Environments (`dev`, `production` with required reviewer) |
| Observability | OpenTelemetry → Collector → Prometheus, Loki, Tempo → Grafana |
| On-call agent | Python webhook receiver + headless Claude Code (`claude -p`) |
| Coding agents | Claude Code (subagents, skills, git worktrees) |

### 7.2 Repository layout (planned)
```
/
├── CLAUDE.md                 # entry point for coding agents → links to docs/
├── README.md
├── Makefile                  # make up / test / lint / e2e
├── compose.yaml              # app + db (local, single command)
├── compose.observability.yaml
├── openapi.yaml
├── backend/                  # FastAPI app, engines/, alembic/, tests/
├── frontend/                 # React app, tests/
├── e2e/                      # Playwright
├── observability/            # collector, prometheus, loki, tempo, grafana provisioning + alert rules
├── oncall/                   # responder service, prompts, allow-listed ops scripts
├── deploy/                   # EC2 bootstrap, compose overrides, deploy/rollback scripts
├── .claude/                  # agents (pm, engineer, qa, devops), skills
└── docs/                     # spec.md, process.md, team.md, architecture.md, runbooks/, adr/
```

## 8. Data model (main entities)

| Entity | Key fields |
|---|---|
| `User` | id, email, password_hash, display_name, role, birth_date, units, timezone, disclaimer_accepted_at |
| `AthleteProfile` | user_id, sex, height_cm, lifestyle, goal, experience, days_per_week, preferred_days, session_minutes, equipment, avoided_exercise_ids, diet, allergies, meals_per_day |
| `CoachProfile` | user_id, bio, discoverable |
| `CoachLink` | id, coach_id, athlete_id, status (`pending`/`active`/`declined`/`ended`), source (`request`; later `subscription`), created/updated_at |
| `Entitlement` (stub) | user_id, key (`can_have_coach`), value — always true in MVP; future paid tier hook |
| `BodyMetric` | user_id, date, weight_kg, body_fat_pct, neck/waist/hip_cm, bf_method |
| `Targets` | user_id, valid_from, bmr, baseline, kcal, protein_g, carbs_g, fat_g, explanation, inputs (json) |
| `Exercise` | id, owner_id (null = seed), name, muscle_group, equipment, type, met, increment_kg, region, allows_added_weight (bool; D56) |
| `Food` | id, owner_id, source, external_code, name, kcal/protein/carbs/fat per 100 g, diet_tags, allergen_tags |
| `Meal` / `MealItem` | meal: id, owner_id, name, slots · item: meal_id, food_id, grams |
| `Plan` | id, athlete_id, version, source (`generated`/`custom`), active (partial unique index: one active per athlete), revision (D42), created_by, created_at, updated_at |
| `TrainingDay` / `PlannedExercise` | weekday, name, order, edited_by (nullable) · exercise_id, sets, reps_min, reps_max, target_weight_kg, target_seconds, rest_seconds, rule, increment_kg, deload_enabled |
| `MealDay` / `PlannedMeal` | weekday · slot, meal_id, portion_factor |
| `Session` | id, athlete_id, plan_id, training_day_id, date, status (`planned`/`in_progress`/`done`/`missed`), started_at, finished_at, completion, kcal |
| `SetLog` | session_id, planned_exercise_id (nullable for extras), exercise_id, set_no, target_reps/weight/seconds (snapshot), reps, weight_kg, seconds, distance_m |
| `MealLog` | athlete_id, date, planned_meal_id (nullable), status (`eaten`/`adjusted`/`skipped`/`extra`), items (food_id, grams) |
| `ActivityLog` | athlete_id, date, exercise_id, minutes, kcal |
| `Suggestion` | id, athlete_id, kind (`progression`/`calories`/`recalc`), target ref, payload, rule, reason, status (`pending`/`accepted`/`rejected`), decided_by, decided_at |
| `Note` | id, coach_id, athlete_id, scope (`day`/`session`/`exercise`), ref, text |
| `Notification` | id, user_id, type, payload, read_at |
| `PlanChange` | plan_id, author_id, change (json), created_at |
| `FeatureFlag` | key, value, updated_by, updated_at |

Targets in `SetLog` are **snapshots**, so history and charts never change when the plan changes.

## 9. API outline

Full contract in `openapi.yaml` (written before implementation). All paths under `/api/v1`. Coaches use the same athlete-scoped endpoints with `athletes/{id}`; the backend resolves `me` to the current athlete.

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/signup` · `POST /auth/login` · `POST /auth/logout` · `GET/PATCH /me` |
| Profile & targets | `GET/PUT /athletes/{id}/profile` · `POST /athletes/{id}/onboarding` · `GET /athletes/{id}/targets` |
| Body | `GET/POST /athletes/{id}/body-metrics` |
| Catalog | `GET/POST /exercises` · `GET/POST /foods` · `GET /foods/search?q=` (Open Food Facts) · `GET/POST /meals` |
| Plan | `GET /athletes/{id}/plan` · `PUT /athletes/{id}/plan/...` · `POST /athletes/{id}/plan/regenerate` · `GET /athletes/{id}/plan/versions` |
| Calendar | `GET /athletes/{id}/days/{date}` · `GET /athletes/{id}/calendar?from=&to=` · `POST /sessions/{id}/move` |
| Logging | `POST /sessions/{id}/sets` · `POST /sessions/{id}/finish` · `POST /athletes/{id}/meal-logs` · `POST /athletes/{id}/activities` |
| Suggestions | `GET /athletes/{id}/suggestions?status=pending` · `POST /suggestions/{id}/accept` · `POST /suggestions/{id}/reject` |
| Charts | `GET /athletes/{id}/charts/session/{sid}` · `/charts/exercise/{eid}` · `/charts/adherence` · `/charts/weekly-summary` · `/charts/body` |
| Coach | `GET /coaches/search?q=` · `POST /coach-links` · `POST /coach-links/{id}/approve|decline|end` · `GET /coach/athletes` · `GET/POST/PUT/DELETE /athletes/{id}/notes` |
| Notifications | `GET /notifications` · `POST /notifications/{id}/read` · `POST /notifications/read-all` |
| Data | `GET /me/export` · `POST /me/delete` (D48) |
| Ops | `GET /healthz` · `GET /readyz` |

Contract v1 adds or makes precise these endpoints, which the screens in §5 need (D39–D47):

| Area | Endpoints |
|---|---|
| Me | `PATCH /me` (display name, units, time zone) |
| Catalog | `POST /foods/import` (copy an Open Food Facts result into `Food`) |
| Plan | `PUT /athletes/{id}/plan/training` · `PUT /athletes/{id}/plan/meals` (the `plan/...` edits) · `GET /athletes/{id}/plan/versions/{version}` |
| Calendar / Logging | `GET /sessions/{id}` · `DELETE /sessions/{id}/sets/{set_log_id}` · `DELETE /athletes/{id}/meal-logs/{log_id}` · `DELETE /athletes/{id}/activities/{activity_id}` |
| Coach | `GET/PUT /coach/profile` · `GET /coach-links?status=` (incoming/outgoing requests) · notes edit/delete at `/athletes/{id}/notes/{note_id}` |

## 10. Testing strategy

Single command: **`make test`** runs everything below (except e2e, which runs with `make e2e` and in CI).

| Level | Scope | Tools |
|---|---|---|
| Unit — engines | F3, F5, F7, F11, F13, F14 rules; table-driven + property-based | pytest, Hypothesis |
| Unit — backend | Services, validators, telemetry field filter | pytest |
| Integration | API + real Postgres (Compose service in CI): auth, authorization matrix, logging idempotency, export/delete, Open Food Facts fake | pytest + httpx, Docker |
| Frontend unit | Components, unit conversion, forms | Vitest + RTL |
| Contract | Backend responses validate against `openapi.yaml` | schemathesis (smoke) |
| End-to-end | Key journeys: (1) sign up → onboarding → Today; (2) log sets → finish → accept suggestion; (3) check off meals → balance updates; (4) coach link → coach views chart → leaves note | Playwright |

Coverage target: ≥ 90 % lines for `backend/app/engines/`, ≥ 75 % backend overall.

## 11. Containerization and local run

- `make up` → `docker compose up --build --wait`: Postgres, a one-shot **migration step** (`alembic upgrade head`, then the idempotent F4.1 seed), backend, frontend (nginx serving the built SPA and proxying `/api`). The backend starts only after the migration step succeeds, and it **only starts the app**. It never migrates or seeds on start ([D50](#19-decisions-log), [ADR 0009](adr/0009-separate-migration-step.md)).
- `make up-obs` adds the observability stack locally.
- Seeded demo data command: `make seed-demo` (one athlete with 8 weeks of history, one coach).
- Health checks on every service; `docker compose up --wait` succeeds only when all are healthy.

## 12. Deployment (AWS)

- **Two EC2 instances**: `fitwise-dev` and `fitwise-prod` (Amazon Linux 2023 or Ubuntu LTS, Docker + Compose). Prod also runs the observability stack and the on-call responder. Region **us-east-2**; `fitwise-dev` is a **t3.small** and `fitwise-prod` a **c7i-flex.large** (t3.medium is rejected by the account's Free plan; about USD 89 per month in total; D52).
- Reached via each instance's **public DNS name over HTTP** (see §6.4 limitation). Elastic IPs keep addresses stable.
- Security groups: 80 open; 22 closed (the owner uses **SSM**; deploys are pull-based); Grafana port restricted to the owner's IP; prod OTLP port open only to the dev instance.
- **Pull-based deploys** ([ADR 0010](adr/0010-pull-based-deploy.md), D57): GitHub holds no AWS credentials and the hosts open no inbound ports for deployment. CI records the approved tag; a systemd timer on each host polls it through the public GitHub API, then pulls, deploys, health-checks and rolls back by itself. This needs the repository and GHCR packages to be public.
- Images are built once per commit and pushed to GHCR tagged with the git SHA. Each server keeps `CURRENT_TAG` and `PREVIOUS_TAG` for rollback.
- Database backups: nightly `pg_dump` to S3 (prod), 7-day retention.
- Infrastructure steps documented in `deploy/README.md` (scripted bootstrap; IaC is a roadmap item).

## 13. CI/CD (GitHub Actions)

| Trigger | Pipeline |
|---|---|
| Pull request | Lint (ruff, eslint), type-check (mypy, tsc), unit + integration tests, frontend tests, OpenAPI validation, dependency scan, secret scan, build images (no push) |
| Merge to `main` | Same checks → build & push images (`sha` tag) → **record the approved tag for dev** (move ref `deploy/dev` to the SHA) → the dev host's timer pulls and deploys → smoke test (`/readyz` + e2e smoke) against the public URL |
| Manual `workflow_dispatch` "Promote to production" | Choose an already-deployed-to-dev SHA → GitHub Environment `production` requires approval → the job in that environment moves `deploy/prod` to the SHA → the prod host's timer deploys it → smoke test → if the health check fails, **the host rolls back to `PREVIOUS_TAG` by itself** |
| Manual "Rollback production" | Moves `deploy/prod` back to the `PREVIOUS_TAG` SHA (the host also rolls back locally on a failed health check, and the on-call agent's script rolls back on the host) |

Deploys are **pull-based** ([ADR 0010](adr/0010-pull-based-deploy.md), D57). The AWS Organization policy denies GitHub OIDC and every action for IAM users, so CI cannot reach the hosts. Instead a systemd timer on each host polls its `deploy/<env>` ref through the public GitHub API, pulls the images, runs the migration step, starts the new tag, health-checks `/readyz`, records `CURRENT_TAG`/`PREVIOUS_TAG` and rolls back on failure. A failed or rolled-back tag is not retried until the ref moves. Prod is only reachable through the `production` environment approval, because only that job may move `deploy/prod`.

Migrations must be backward compatible with the previous release (expand → migrate → contract) so rollback never needs a down-migration.
For the same reason `GET /readyz` reports `migrations: ok` when the database is at **or ahead of** the release's Alembic head (ahead = a newer release migrated it and this one was rolled back); it reports `pending` (503) only when a revision this release ships is not applied.

Where migrations run ([D50](#19-decisions-log), [ADR 0009](adr/0009-separate-migration-step.md)):

| Situation | Migration step (`alembic upgrade head` + F4.1 seed, from the image being deployed) |
|---|---|
| Local `make up` | Runs before the backend starts |
| Deploy to dev, promote to prod (`deploy/deploy.sh <sha>`) | Runs before the backend starts. If it fails, the deploy fails and the backend isn't started on the new tag |
| Rollback to `PREVIOUS_TAG` (automatic on the host after a failed health check, "Rollback production", on-call `rollback.sh`) | **Skipped.** The previous backend starts against the newer schema as it is. No down-migration |
| Backend restart (on-call `restart`, container restart policy) | Not involved. The backend never migrates on start |

## 14. Observability

**Key user journey:** *Today → log sets / check off meals → finish workout → suggestions generated.*

- **Traces**: FastAPI, SQLAlchemy and outgoing HTTP (Open Food Facts) auto-instrumented; custom spans for `engine.progression`, `engine.meal_plan`, `engine.targets`.
- **Metrics** (Prometheus):
  - `http_server_duration` (route, method, status) — RED metrics
  - `fitwise_sets_logged_total`, `fitwise_meal_checkoffs_total`, `fitwise_workouts_finished_total`
  - `fitwise_suggestions_generated_total{kind, rule}`, `fitwise_suggestions_decided_total{kind, decision}`
  - `fitwise_off_search_total{outcome}`
- **Logs**: structured JSON to stdout → Collector → Loki, each line with `trace_id`, `span_id`, `env`, `route`, `user_hash`; allow-listed fields only (§6.5).
- **Privacy rules in the pipeline**: `route` is always the route template (`unmatched` for unknown paths), never the raw path; the app writes its own access log (route, method, status, duration — no query string) instead of uvicorn's; spans keep only allow-listed attributes and lose exception messages and status descriptions; `user_hash` = HMAC-SHA256 of the user id keyed by `USER_HASH_SALT` (required in dev/prod); `Problem.request_id` = the request's `trace_id`. Health probes are measured but not traced or access-logged when healthy.
- **Export**: OTLP/HTTP to `OTEL_EXPORTER_OTLP_ENDPOINT`; when unset nothing is exported and no network call is made (tests, `make up` without the observability stack). `env`, `service.name` and `service.version` (git SHA) are resource attributes.
- **Correlation**: Grafana links metric exemplars → Tempo traces → Loki logs by `trace_id`.
- **Dashboards** (provisioned as code): "Key journey" (rate, errors, p95 per logging endpoint), "Engines" (suggestions by rule/decision), "Service health".
- Both environments send telemetry, labelled `env=dev|prod`.

## 15. Alerting and on-call agent

### 15.1 Alerts (Grafana-managed, provisioned as code; `env=prod`)
| Alert | Condition | Severity |
|---|---|---|
| **KeyJourneyErrors** | 5xx ratio > 5 % on logging endpoints (`POST /sessions/*/sets`, `POST /sessions/*/finish`, `POST /athletes/*/meal-logs`) over 5 min, with ≥ 20 requests | page |
| **KeyJourneyLatency** | p95 latency > 1 s on the same endpoints over 10 min | page |

Both include the affected route, time window, dashboard link and runbook link, handle "no data" as OK, and notify the on-call responder via webhook.

**Sequencing (D53):** the rules, contact point and notification policy are provisioned as code in M1, but the logging endpoints they watch only exist from M2 (#29) and M3 (#37). The "fires and resolves" test and demo scenario S1 therefore run after #29, not in M1.

### 15.2 On-call responder
- A small Python service on the prod host (systemd) receives Grafana webhooks at `/alerts`, deduplicates per alert fingerprint, and saves context (Prometheus series, Loki error logs, Tempo failing traces) to `incidents/<id>/`.
- It launches **headless Claude Code** with a runbook prompt and a strict tool allow-list:
  - read-only queries to Prometheus/Loki/Tempo, read-only `docker compose ps/logs`
  - `oncall/ops/flag.sh <key> <value>` (allow-listed keys only)
  - `oncall/ops/rollback.sh` (redeploy `PREVIOUS_TAG`)
  - `oncall/ops/restart.sh <service>` (backend or frontend only)
  - `gh issue create`, and `git` + `gh pr create` on a separate clone (branch push only, never to `main`)
- No database writes, no secrets access beyond its own env file, no arbitrary shell. Timeout 20 min. API key with a spend limit.

**Flow:** alert fires → agent investigates → applies **one runtime mitigation** (flag / rollback / restart) → verifies recovery (error ratio / latency back under threshold for 5 min) → opens a **GitHub issue** with an incident report (timeline, evidence, mitigation) → opens a **PR** with the root-cause fix that goes through normal CI/CD and human review.

### 15.3 Demo scenarios (documented in `docs/runbooks/`)
| # | Fault | Expected mitigation | Follow-up PR |
|---|---|---|---|
| S1 | **Bad release**: a build where finishing a workout raises an error is promoted to prod | `rollback.sh` → previous tag | Fix + regression test |
| S2 | **Faulty engine version**: `progression_engine=v2` enabled; v2 fails on bodyweight exercises | `flag.sh progression_engine v1` | Fix v2 + test |
| S3 *(optional)* | **Latency fault**: `fault_injection_latency_ms` flag adds delay to logging endpoints | `flag.sh fault_injection_latency_ms 0` | Runbook note |

Fault-injection flags exist only for demonstrations, are off by default and are documented.

## 16. Scope and delivery order

### 16.1 Priorities
- **Must (MVP):** F1–F18, §10–§15.
- **Should (if time allows, may be promoted):** meal swap suggestions ("similar kcal" alternatives), duplicate-a-day in the plan editor, PR (personal record) badges, CSV import of past workouts.
- **Could:** different targets on training vs. rest days, more templates, notes reactions, dark mode.

### 16.2 Delivery order (walking skeleton first)
Infrastructure criteria are secured before features grow:

1. **M0 — Foundations:** repo, CLAUDE.md + docs, agent team definitions, backlog with acceptance criteria, `openapi.yaml` skeleton.
2. **M1 — Walking skeleton:** sign-up/login + a minimal Today page + Postgres; `make up`, `make test`; Docker Compose; CI on PRs; deploy to dev on merge; manual prod promotion with rollback; OTel + Grafana stack; both alert rules provisioned as code; on-call responder.
3. **M2 — Athlete core:** onboarding, targets engine, catalog, training generator, calendar, training logging, progression engine (+ S2 scenario); once the training logging API (#29) exists, the alerts' "fires and resolves" test and demo scenario S1 (D53).
4. **M3 — Nutrition:** foods/meals, Open Food Facts, meal plan generator, meal logging, energy balance.
5. **M4 — Custom mode & insights:** plan editor, charts, body tracking + adaptive calories, notifications.
6. **M5 — Coach mode:** linking, coach dashboard, plan editing, notes.
7. **M6 — Data & polish:** export/delete, demo data, README, screenshots/demo video.

If time runs out, milestones are cut from the end; M0–M2 alone satisfy every grading criterion.

## 17. Roadmap (post-MVP)
1. HTTPS (domain or sslip.io + Caddy/Let's Encrypt), `Secure` cookies.
2. Spanish UI.
3. Body-fat estimate from a face-free photo (explicit consent, processed in memory, never stored, EXIF stripped, result as a range, behind a flag).
4. **Paid coaching**: coach marketplace, subscriptions via a billing provider behind an interface; `CoachLink.source = subscription`; `Entitlement` checks.
5. Email/push notifications; PWA/offline logging.
6. Barcode scanning; richer food databases.
7. Infrastructure as code (Terraform/CDK).
8. Wearable integrations.

## 18. Course criteria mapping

| Criterion | Where it's addressed |
|---|---|
| Problem description | §1, README |
| Product specification + tracker | This spec + GitHub Issues/Projects with AC per issue, PRs linked `Closes #N` |
| Agent team | [docs/team.md](team.md), [docs/process.md](process.md), `.claude/agents/` (PM, Engineer, QA, DevOps/SRE) |
| Context management | `CLAUDE.md` → `docs/` (process, team, architecture, runbooks, ADRs) |
| Application | §5, §11 (`make up`) |
| Testing | §10 (`make test`) |
| Containerization | §11 |
| Deployment | §12 |
| CI/CD | §13 (dev auto, prod manual with approval + rollback) |
| Observability | §14 |
| Alerting on user impact | §15.1 |
| On-call agent | §15.2–15.3 |

## 19. Decisions log

Decisions with architectural trade-offs have an ADR in [`docs/adr/`](adr/README.md), linked from the matching row ([process.md §8](process.md#8-changing-the-spec)). [ADR 0004](adr/0004-pure-calculation-engines.md) (pure, explainable calculation engines) has no single row; it underpins F3, F5, F7, F11, F13 and F14.

| # | Decision |
|---|---|
| D1 | Stack: FastAPI + React + Postgres ([ADR 0001](adr/0001-stack-fastapi-react-postgres.md)) |
| D2 | Hosting: AWS, EC2 + Docker Compose, Postgres in a container ([ADR 0002](adr/0002-ec2-docker-compose-deployment.md)) |
| D3 | Environments: two EC2 instances (dev, prod) ([ADR 0002](adr/0002-ec2-docker-compose-deployment.md)) |
| D4 | Public access: EC2 public DNS over plain HTTP, documented limitation ([ADR 0003](adr/0003-plain-http-known-limitation.md)) |
| D5 | UI language: English now, i18n-ready, Spanish later |
| D6 | Units: metric + imperial per user, stored metric |
| D7 | Mobile-first responsive web |
| D8 | Auth: own email + password, JWT cookie |
| D9 | Roles chosen at sign-up; separate accounts |
| D10 | Coach linking: athlete searches, coach approves |
| D11 | Coach can view everything and edit the plan; cannot log |
| D12 | One-way coach notes on day/session/exercise |
| D13 | 18+ and disclaimer; calorie floor enforced |
| D14 | Body fat: known %, Navy method or skip; photo estimate on roadmap |
| D15 | Weight loggable any day; measurements optional; 7-day trend |
| D16 | Exercise catalog: seeded + custom |
| D17 | Exercise types: strength, bodyweight, timed/cardio |
| D18 | Progression: linear, double, deload, manual |
| D19 | Suggestions require acceptance (athlete or coach) |
| D20 | Templates: splits by days/week × equipment |
| D21 | Starting weights: calibration first session |
| D22 | Food data: seeded library + Open Food Facts search + custom |
| D23 | Meals composed of foods × grams |
| D24 | Meal plan: rotating, ± 5 % kcal, ≤ 2 repeats/week |
| D25 | Meal logging: check off, adjust grams, skip, add extra food |
| D26 | Burned = BMR × lifestyle + logged exercise + extra activities |
| D27 | Missed sessions marked; move within the week |
| D28 | Calendar: Today / Week / Month; weekly template repeats |
| D29 | Adaptive calories: weekly suggestion, requires acceptance |
| D30 | Notifications: in-app only |
| D31 | Export (JSON/CSV) + delete account |
| D32 | Observability stack self-hosted on prod EC2 ([ADR 0006](adr/0006-self-hosted-observability-on-prod.md)) |
| D33 | On-call: runtime mitigation (flag/rollback/restart) + GitHub issue + fix PR ([ADR 0007](adr/0007-on-call-agent-with-allow-listed-mitigations.md)) |
| D34 | Alerts: key-journey error rate and latency ([ADR 0006](adr/0006-self-hosted-observability-on-prod.md)) |
| D35 | Coding agents: Claude Code only |
| D36 | Agent team: PM, Engineer, QA, DevOps/SRE |
| D37 | Tracker: public GitHub repo + Issues + Projects board |
| D38 | Product name: FitWise |
| D39 | API conventions (`openapi.yaml`): `snake_case` JSON; metric only, with the unit in the field name (`_kg`, `_cm`, `_g`, `kcal`, `seconds`); `date` = calendar day in the athlete's time zone, `date-time` = UTC instant with `Z`; weekdays as `mon`…`sun`; lists wrapped in `{items}`, catalog/notifications cursor-paginated. `openapi.yaml` is the API source of truth ([ADR 0005](adr/0005-contract-first-openapi.md)) |
| D40 | Errors are RFC 9457 `application/problem+json` with a stable `code` and field `errors[]`. **400** = the request line or envelope is invalid: unparseable JSON, or an invalid query/path parameter (wrong type or format, e.g. a non-date `{date}`; invalid range, e.g. `from` after `to` or a range that is too long; `week_start` not a Monday). **422** = the JSON request body is well-formed but fails validation (schema, F1.1 under 18, F1.2 disclaimer, F2.3 plausible ranges). 409 = state conflict |
| D41 | `athletes/{id}` accepts `me`; an unknown or not-actively-linked athlete id returns 403 (never 404) so ids cannot be enumerated. Each operation declares its access rule in `x-fitwise-access` for the authorization matrix tests |
| D42 | Custom-mode plan edits replace the whole training or meal template (`PUT /plan/training`, `PUT /plan/meals`) with an optimistic-concurrency `revision`; a stale revision returns 409. Gram overrides on a planned meal are stored as an athlete-owned copy of the meal |
| D43 | Logging endpoints are upserts on their natural key (set: session + exercise + set number; meal: date + planned meal); 201 on create, 200 on replace. Body metrics upsert per day the same way |
| D44 | Open Food Facts search degrades to `200 {available: false, message}` when the flag is off or upstream fails; imports go through `POST /foods/import` (unique on product code), which returns 503 only if the product is not cached and upstream is down |
| D45 | A session can be moved only if not finished, to a day in the same ISO week that is today or later and has no other session |
| D46 | Editing the profile (owner only; coaches can view) recomputes targets from today and rescales future meal portions without a suggestion, because the athlete made the change; the training plan is regenerated only on request |
| D47 | `target_balance_kcal` (goal's target daily balance) = target kcal − (baseline + average daily planned exercise kcal). Exercise muscle groups are a fixed enum (chest, back, shoulders, biceps, triceps, forearms, core, quads, hamstrings, glutes, calves, full_body, cardio). Custom exercises/foods/meals are visible to their creator and the creator's active-link counterpart |
| D48 | Account deletion is `POST /me/delete` with the current password in a JSON body, not `DELETE /me` with a body: request bodies on `DELETE` have no defined semantics (RFC 9110) and some proxies and clients drop them. Wrong password → 403; F18 unchanged |
| D49 | *Proposed (PM, implemented in #8; awaiting owner confirmation).* F1.6 sign-in lockout: failures are counted per email, case-insensitively, whether or not an account exists, in a sliding 15-minute window. Once 5 failures are in the window, **every** sign-in for that email returns `429 rate_limited` with `Retry-After` (seconds until the oldest of them leaves the window), **even with the correct password**, and is not evaluated or counted. Answering 200 to a correct password during the lockout would turn the 429 into a password oracle. A successful sign-in clears the count. Failures are stored as a SHA-256 of the lower-cased email, never the email itself, and only for the window |
| D50 | Migrations and the F4.1 seed run as a **separate one-shot step** from the image being deployed, before the backend starts: on `make up` and on forward deploys. A rollback to `PREVIOUS_TAG` **skips** the step. The backend container only starts the app and never migrates or seeds on start (§11, §13; [ADR 0009](adr/0009-separate-migration-step.md); #82) |
| D51 | Every subagent (PM, Engineer, QA, DevOps) runs on **Sonnet with medium effort**, pinned in its frontmatter; the orchestrator may run QA on Opus for a security-, hook-, auth- or migration-heavy PR. To cut repeated QA work without weakening verification, QA cites CI for the exact head SHA rather than re-running lint and tests, re-verifies only the failing and touched AC after a FAIL, judges AC as written (CLAUDE.md rules always block), reads only the referenced spec sections, and escalates to the owner after 3 FAILs ([process.md §6](process.md#6-qa-verification), [team.md](team.md#models-and-effort)) |
| D52 | AWS region **us-east-2**; `fitwise-dev` = t3.small, `fitwise-prod` = **c7i-flex.large** (t3.medium is not allowed on the account's Free plan), about USD 89 per month in total including EBS and public IPv4 (owner, 2026-10-24; #12). Deploy credentials: see D57 |
| D53 | Alert rules KeyJourneyErrors/KeyJourneyLatency are provisioned as code in M1 (#18). The "fires and resolves" test and demo scenario S1 (#20) move to after the logging API (#29), because the watched endpoints do not exist in M1 (owner chose option b, 2026-10-24) |
| D54 | F5 generator: (1) estimated session duration = Σ sets × (rest_seconds + 45 s) + cardio minutes + 5 min warm-up, default rest 90 s; (2) beginners' main lifts under linear progression use the middle of the rep range, rounded down; (3) an avoided exercise with no same-muscle/same-equipment alternative falls back to a bodyweight exercise of the same muscle group, else is dropped with a plan warning (owner, 2026-10-24; #23) |
| D55 | A Navy body-fat result outside 3–60 % is ignored; BMR falls back to Mifflin-St Jeor and the explanation says so (owner, 2026-10-24; #25) |
| D56 | F11 progression: (1) `Exercise.allows_added_weight` (bool) decides between "+ added weight" and "ready for a harder variation" for bodyweight exercises; (2) calibration with mixed weights uses the weight on the most sets, ties broken by the heaviest; (3) minimum weight is the empty bar, 20 kg (45 lb displayed for imperial users), for barbell exercises and 0 for all other equipment (owner, 2026-10-24; #31) |
| D57 | Deploys are **pull-based** ([ADR 0010](adr/0010-pull-based-deploy.md)). The org policy (SCP) denies GitHub OIDC and every action for IAM users, so GitHub holds no AWS keys. CI pushes images to GHCR and records the approved tag (ref `deploy/dev` after merge, `deploy/prod` only from the `production` environment job); a systemd timer on each host polls it via the public GitHub API, deploys, health-checks and rolls back by itself. No inbound ports; the repository and GHCR packages must be public. The poller is built in #13/#14 (owner, 2026-10-24; #12) |
| D58 | CD to dev ([#13](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/13)): (1) the `deploy/dev` and `deploy/prod` branch refs are moved by the built-in `GITHUB_TOKEN` (`contents: write` on that job only), not by PATs or Apps; (2) merge to deployed on dev target = 10 minutes; (3) the ref points at a deploy commit (parent = release commit, same tree) whose message carries the source SHA and the image digests, so one unauthenticated request per poll (every 150 s, 24 per hour) gives the host everything; (4) `GET /healthz` returns `version` (the release's commit SHA, `APP_VERSION`); (5) a ruleset limiting `deploy/*` to GitHub Actions is impossible on a personal repository (the Actions app cannot be a bypass actor), so the owner being the only writer is the accepted protection until the repository is in an organization (owner, 2026-10-24) |
| D59 | Lower QA token cost (owner, 2026-10-24): (1) QA keeps tool output short (`pytest -q --tb=short`, `\| tail`, `logs --tail`) and doesn't re-read `CLAUDE.md` or all of `process.md` §6; (2) the engineer runs QA's blocking project-rule checklist on its own diff before opening the PR, to cut FAIL rounds; (3) the orchestrator may run QA on Haiku for a re-verification round after a FAIL or a docs/config-only PR, never for a first verification of a code PR; (4) the orchestrator starts QA with the PR, head SHA, CI run URL and AC list. See [team.md](team.md#models-and-effort) |
| D60 | Full-gym accessories prefer machines and cables (owner, 2026-10-24, from QA of #23; #110): ranking accessories by lowest MET first picked band exercises ahead of machines and cables, which is odd in a gym. In `full_gym` the accessory ranking is now equipment tier first (`machine`, `cable`), then MET, name, id; the tier outranks "not yet used in the plan". Main lifts and the other variants are unchanged. Avoided-exercise replacement (F5.6) still looks for the same equipment first |
| D60 | Prod auto-rollback demo (#14): to demonstrate the host rollback on prod without a build that is bad only on prod, a **host-side switch** is used: while the line `FITWISE_DEMO_FAIL_HEALTH=1` is in the root-only `/opt/fitwise/.env`, `deploy/deploy.sh` treats the post-deploy health check as failed and runs the normal `rollback.sh` path (no migration, D50). Off unless that exact line exists, on any host; `rollback.sh` ignores it; the application does not read it; the file is never printed. It is added for the demo and removed afterwards (procedure in `deploy/README.md`) (owner, 2026-10-24) |

## 20. Assumptions and open questions

- **A1.** Deadline and weekly availability are unknown; the delivery order (§16.2) is designed so any prefix of milestones is gradable.
- **A2.** Formula constants (lifestyle factors, goal adjustments, protein, floors, MET values, adaptive thresholds) are reasonable defaults from common practice, kept in one config module and easy to change.
- **A3.** Open Food Facts data quality varies; imported foods are shown with their source.
- **Q1.** Should training days and rest days have different calorie targets? (Currently *Could*.)
- **Q2.** Should coaches be able to create reusable program templates to assign to several athletes? (Not in MVP.)
