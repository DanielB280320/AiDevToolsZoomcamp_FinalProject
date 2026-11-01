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

Implementation notes (#25): onboarding is one transaction (profile, first `BodyMetric`, `Targets`, plan v1); a second call is `409 already_onboarded`, and reads before it are `404 not_onboarded`. A Navy result the formula cannot compute (waist not larger than neck) is treated like an out-of-range one (F2.6). `body_fat_pct` is accepted only with method `entered`; `navy` needs neck and waist (plus hip for female / unspecified). Plans created by onboarding store F13.2 planned kcal per exercise and per day at the weight entered. `PUT /profile` recomputes targets (from the latest weight and body fat on or before today and the active plan's planned kcal) when sex, height, lifestyle, goal, days per week or session length changed; a second recompute on the same local day replaces that day's `Targets` row, earlier days keep theirs. `GET /targets?date=` returns the latest row with `valid_from <= date`, and the first row for earlier dates.

Implementation notes (#26): the wizard is at `/onboarding` with steps Body, Body fat, Lifestyle, Goal, Training, Diet and a Review step. Targets only exist after `POST /athletes/{id}/onboarding` (there is no preview endpoint), so the wizard submits from Review and then shows the computed targets, their F3.5 explanation and the plan summary on a result screen; the user leaves it with "Go to Today". Until then `GET /me` has `onboarding_completed: false`, and an athlete opening Today is redirected to the wizard; a completed athlete opening the wizard is redirected to Today. Imperial users type feet and inches, pounds and inches (tape measures); values are validated against the F2.3 limits after conversion (messages show the range in the user's units) and sent in metric, rounded to 0.1 cm / 0.1 kg. "Exercises to avoid" searches `GET /exercises?q=` (at least 2 characters).

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
- Seeded library: ~50 meals covering all slots and diet preferences (D64).
- **Custom foods and meals** can be created by athletes and coaches.
- **Open Food Facts search**: text search for packaged foods. A selected result is copied into the local `Food` table (source `openfoodfacts`, with its product code) so it never needs to be fetched again.
  - Requests use a descriptive `User-Agent` (`FitWise/<version> (<contact>)`), a 3 s timeout and a server-side cache of search results (24 h).
  - Products without a numeric code of 4-14 digits, a name, or kcal/protein/carbs/fat per 100 g within the `Food` limits are left out of results (kcal falls back to kJ / 4.184). Allergen and diet tags are copied only when Open Food Facts states them. Configured by `OFF_BASE_URL`, `OFF_CONTACT`, `OFF_TIMEOUT_SECONDS`.
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
- **Engine choices inside the rules** (D68; constants in `app/engines/constants.py`): the library is the seed meals plus the athlete's own meals; a meal's diets and allergens come from its foods (F6). For each day the generator tries up to 60 random combinations (one meal per slot, never the same meal twice in a day, never a meal already used twice that week) and keeps the first that is within ± 5 % kcal with protein ≥ 90 %, else the best attempt. A slot prefers meals whose portion factor for the slot's kcal falls in 0.75–1.5; the day's factors are then rescaled together to the day target (clamped to 0.75–1.5, two decimals). When a slot has no meal left, it is left out and the day carries a warning. A day's `warning` (calorie, protein or slot wording) is stored on the `MealDay`; `Plan.warnings` stays for training-plan warnings. The seed is `user_id + ISO week` (the ISO year is added so weeks do not repeat); the generator uses its own SplitMix64 generator so plans are identical on every platform.
- Onboarding (F2.2) generates the meal plan from the targets just computed, in the same transaction and plan version as the training plan; an empty or unusable library never blocks onboarding (days carry warnings instead).

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
- **Implementation notes (#27)**: a `session` row is created on first view of a planned day (`GET /athletes/{id}/days/{date}`), idempotently (unique athlete + date); `GET .../calendar` never writes, it derives not-yet-materialised days from the active plan's template, only for days on or after the plan's creation date (local). `missed` is derived on read, not stored. An unknown session id returns 403, like another athlete's session (D41). A rejected move returns 409 with `day_occupied` (the target already has a session, materialised or still only on the template; also moving onto the same day), `session_finished`, `outside_week` (target not in the session's ISO week) or `date_in_past`.
- **Implementation notes (UI, #28)**: routes `/today` (home), `/week` (`?week=YYYY-MM-DD`) and `/month` (`?month=YYYY-MM`), switched with a Today / Week / Month tab bar at the top of each page (thumb-sized, full width on mobile). Badges: *done* (finished at 100 %), *partial* (in progress, or finished below 100 % completion), *missed*, *rest*, and *planned* for a not-yet-started session; each badge carries a glyph and a label, never colour alone. Month cells link to their week. A session can be moved only if it is `planned`, the target is a free (rest) day of the same week and today or later; the UI offers only those days, and the server stays the authority (409 reasons shown as messages). A future day without a session row is materialised by `GET .../days/{date}` just before the move, to obtain its id. Coaches are sent from `/today` to the client list (#48, D83): the athlete views need an athlete context, which the coach shell provides. Today currently lists the session's exercises with planned sets, planned meals (read-only), the energy balance and a count of pending suggestions/notes; logging sets, meal check-offs and suggestion actions arrive with #29-#31.

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

- **Implementation notes (#29)**: a set log is unique per (session, exercise, set number); the first log copies the planned targets onto the row and re-logging never rewrites them. Completion is stored on the session after every change (`null` until something is logged, `0` when a session is finished empty); logged sets use their snapshot targets, unlogged planned sets the current plan, and extra sets/exercises are excluded. Finish stores `Session.kcal` from the F13.2 engine with the most recent weight on or before the session date (the earliest weigh-in for earlier dates); the first finish counts one `fitwise_workouts_finished_total`, a re-finish inside the edit window does not. The edit window ends at the start of the second day after the session date in the athlete's time zone; after it logging, deleting and finishing return `409 edit_window_closed`. Errors: `422 invalid_set` (values that do not fit the exercise type, `as_planned` + `skipped`, `as_planned` with nothing to copy), `422 planned_exercise_mismatch`, `422 invalid_finished_at`, `404 exercise_not_found` / `set_log_not_found` / `activity_not_found`, `422 not_timed_exercise`. Extra activities store their kcal when logged (weight on or before their date). `burned.total_kcal` is the baseline plus finished-session kcal plus extra activities (#38); the `suggestions` of `finish` stay empty until #85.

- **Implementation notes (UI, #30)**: route `/workout/:sessionId`, reached from the Start / Continue / View workout button on Today (tap 1); "Done as planned" on a set is tap 2. Each set offers Done as planned (only when it has a target), Edit (reps + weight, reps + optional added weight, or duration + optional distance, in the user's units) and Skip; "Add set" and "Add exercise" (catalog search) log extras. After every logged, non-skipped set a rest timer counts down the exercise's `rest_seconds` (90 s for an exercise added on the spot); it is derived from an injected clock and stops when the workout is finished. Finish shows completion, estimated kcal, duration and the `suggestions` returned by `finishSession`; finishing again inside the edit window updates the summary. Once `editable_until` has passed the screen is read-only. Coaches are redirected to Today (F16.4).

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

Behaviour details (D70): a check-off stays matched to its meal across plan versions; a repeated check-off returns the existing log (`200`), creates no second row and does not count again in `fitwise_meal_checkoffs_total`; sending a different status or grams for the same planned meal replaces that log. Extra food always creates a new log. A day cannot be logged in the future. Only the athlete writes meal logs (a coach gets `403`).

### F13. Daily energy balance — *Must*

**F13.1 Calories burned (estimated)** = `baseline (F3.2)` + `Σ exercise kcal` from logged sessions and extra activities.

**F13.2 Exercise kcal** — `kcal = MET × 3.5 × body_weight_kg ÷ 200 × minutes`
- Timed/cardio: minutes = logged duration.
- Strength/bodyweight: minutes per exercise = sets × (rest_seconds + 45 s) ÷ 60.
- Body weight = most recent weight on or before that date.
- Planned version (for F3.4 targets) uses the same formula with planned sets and durations.

**F13.3 Display** — Today and each day in Week view show: eaten, burned, balance (eaten − burned), the goal's target balance, and macro progress bars. All values are labelled "estimated".

**Implementation notes (#38)**: `energy` (day view, calendar days, and the `energy` of log/activity responses) takes `baseline_kcal`, `target` (kcal and macros) and `target_balance_kcal` from the `Targets` row valid on that date (latest `valid_from <= date`, the first row for earlier dates, as `GET /targets`), so a later profile change or weigh-in never alters a past day. Without targets (not onboarded) they are zero. `burned.total_kcal = baseline + training + activities`; `balance_kcal = eaten - burned`. The calendar computes the whole range in a fixed number of queries and returns the same `energy` as the day view. Today and each Week day card show eaten, burned, balance, target balance, an "estimated" label and protein/carbs/fat progress bars (`role="progressbar"`).

**AC**
- [ ] F13.1 Unit tests for the MET formula and minute estimation.
- [ ] F13.2 Changing body weight on a later date doesn't alter past days' calculations.
- [ ] F13.3 Extra activities logged on a rest day add to burned calories.

### F14. Body tracking and adaptive calories — *Must*

- Log weight on any day (one entry per day; re-logging replaces it). Optionally log body fat % or measurements (Navy method recalculates body fat).
- UI (`/body`, athlete only; coaches see no form): the weigh-in form takes weight, optional body fat % and neck/waist/hip in the user's units (converted to kg/cm before sending), rejects a future date inline, and shows API `422` messages next to their field. Re-logging a date shows a "replaced" confirmation and the list keeps one row per date. When the response carries a `recalc_suggestion` (or one is still pending on load) a prompt shows old vs. new kcal and macros with Accept and Reject; nothing changes until Accept.
- Chart: daily weight + **7-day moving average** trend.
- When weight changes by ≥ 2 % from the weight used for current targets, prompt the athlete to recalculate targets (shows old vs. new; accept/reject).
- **Weekly adaptive calorie suggestion** (every Monday, for the previous two complete weeks):
  - Requires ≥ 4 weigh-ins in each of the two weeks; otherwise no suggestion and a hint to weigh in more.
  - Expected weekly change: Cutting −0.75 % BW; Recomposition/Maintenance/Wellness 0 % (± 0.25 % tolerance); Muscle gain +0.25 % BW (± 0.15 % tolerance); Cutting tolerance ± 0.25 %.
  - If the 7-day-average trend is outside tolerance **in the same direction for 2 consecutive weeks**: suggest −150 kcal (losing too slowly / gaining too fast) or +150 kcal (losing too fast / gaining too slowly), never below the floor (F3.6).
  - Mechanics (D78): the job (`python -m app.cli.adaptive_calories`) is run by `fitwise-adaptive-calories.timer` on Monday and Tuesday 01:00 UTC; the weeks are the two complete Monday-to-Sunday weeks before this Monday, and a week's trend is the change of the 7-day average from its Monday to its Sunday, in percent of the Monday average.
  - A -150 kcal step that would land below the floor is not created (no clamped step); the weigh-in hint is returned in `weigh_in_hint` of the suggestion list.
  - The suggestion is `pending` until the athlete or coach accepts; accepting updates targets and rescales the `portion_factor` of meal days **from today on** (D74); past days keep theirs.

**AC**
- [ ] F14.1 7-day average is computed only from existing weigh-ins in the window (unit-tested with gaps).
- [ ] F14.2 No suggestion with insufficient data.
- [ ] F14.3 Suggestion direction and amount are correct for each goal (table-driven tests).
- [ ] F14.4 Accepting changes only today and future days (D74).

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
- Client list sorted by "needs attention": training adherence < 70 % over the last 7 days, any exercise with deload pending/applied in the last 14 days, or no logs for 3+ days. Exact rules, order and the empty cases are in D83.
- View everything the athlete sees: profile, targets, calendar, logs, charts, body metrics.
- Edit the athlete's plan (F8), accept/reject/edit their pending suggestions (F11, F14).
- Leave **notes** on a day, session or exercise. Notes are one-way, visible to the athlete (also after the link ends, D84), editable/deletable by the author.
- Cannot log sets, meals or weigh-ins on the athlete's behalf.

**AC**
- [x] F16.1 Authorization matrix tests (#47): a coach gets 403 for every athlete endpoint of an athlete not actively linked to them (including after the link ends).
- [ ] F16.2 Search never returns non-discoverable coaches or athletes, and never exposes emails.
- [ ] F16.3 An athlete with an active coach cannot send another request.
- [x] F16.4 Coach logging attempts return 403 (#47 matrix, #48 UI offers no logging controls in coach context).
- [x] F16.5 "Needs attention" rules and ordering are covered by unit tests (`engines/coach_attention.py`, #48).
- [x] F16.6 Notes (#49, D84): only a linked coach creates them, only the author edits or deletes (403 for the athlete, another coach and a stranger), the athlete gets one `coach_note` notification per note, notes stay readable by the athlete after the link ends, and note text never reaches telemetry (`backend/tests/integration/test_notes.py`).

### F17. In-app notifications — *Must*

An inbox (bell icon with unread count) and banners on Today. No email/push.

Events: pending progression suggestion, pending calorie adjustment, target-recalculation prompt, new coach note, link request received (coach), link request approved/declined/ended (athlete), plan edited by coach, food or meal removed from a meal or plan because its owner deleted their account (D66, D71).

**AC**
- [ ] F17.1 Each event creates exactly one notification for the right recipient.
- [ ] F17.2 Opening a notification marks it read; "mark all read" works.

Decisions on creation, banners and the `content_removed` type: D79.

**Implementation notes (backend, #45).** Table `notification` (`user_id` cascades with the user, `payload` JSON of ids and dates only, `read_at` null while unread); a partial unique index on (`user_id`, `type`, `payload.suggestion_id`) makes a retried event a no-op. Producers call only `services/notifications.notify(db, user_id, type, payload, now)`, which writes in the caller's transaction (never commits) and rejects payload keys outside the contract's `NotificationPayload`. Wired today: the progression finish hook, the weekly calorie job, and the weigh-in recalc (which deletes the replaced pending suggestion's notification if unread). `notify_content_removed(db, deleted_user_id, now)` collects the other users whose meals or logged meals contain a custom food of the deleted user (logged meals added in #50, D85), or whose meal plans (any version) contain one of their meals, and notifies each once; `deleteMe` (#50) must call it in the same transaction before the delete. `GET /notifications` pages by a `(created_at, id)` cursor, newest first. No metric is added: notification creation is visible through the existing request metrics, and nothing about notifications carries a name or free text.

**Implementation notes (UI, #186).** Bell in the header for every signed-in user (link to `/notifications`, accessible name "Notifications, N unread", badge `99+` above 99, hidden at 0, 44 px target); its count is `Me.unread_notification_count`, and every read call invalidates `me` and the notification queries so the count updates without a reload. The inbox pages with `next_cursor` ("Load more"); unread rows carry a visible "Unread" tag and `data-unread`, not colour alone. Text comes from `notifications.types.<type>` and types without text (`link_*`, `plan_edited_by_coach`; `coach_note` got its own text and a target in #49) use `notifications.types.generic` and have no target, so the coach issues add only a key and a target in `features/notifications/model.ts`. Targets: `progression_suggestion`, `calorie_suggestion` and `content_removed` open Today (where every kind of pending suggestion is listed), `recalc_prompt` opens the Body page (the only place that renders the recalculation prompt). Opening marks the notification read first and navigates on success; a failed mark shows an error and stays. Today banners come from `listNotifications?unread_only=true`, filtered to the four banner types, 3 shown, "See all" when more exist. The client never logs or sends notification content.

### F18. Data ownership — *Must*

- **Export**: one ZIP containing `profile.json`, `plan_versions.json`, and CSVs for set logs, meal logs, body metrics, extra activities and suggestions.
- **Delete account**: requires password re-entry; permanently deletes all user data, ends coach links and removes notes the user authored. A coach deleting their account ends all links; athletes' data is unaffected. Plans, plan changes, edited days and decided suggestions that a deleted coach authored stay with the athlete; only the reference to the coach is cleared (shown as no author, D69). Custom foods of the deleted user that appear in a linked user's meal are removed from that meal, the meal keeps its other items, and the linked user is notified (D66). Planned meals that use a meal of the deleted user, in a linked user's meal plan, are removed in the same way: the meal day and its other planned meals stay and the linked user is notified (D71).

**AC**
- [x] F18.1 Export contains only the requesting user's data (integration test with two users).
- [x] F18.2 After deletion, no rows referencing the user remain (integration test over all tables).
- [x] F18.5 Deleting a coach who created or edited a linked athlete's plan, meal day or training day, or decided one of their suggestions, succeeds; the athlete's rows remain and the coach reference is null (integration tests, D69).
- [x] F18.3 Coaches cannot export or delete an athlete's account.
- [x] F18.4 Deleting a user whose custom food is used in a linked user's meal succeeds: that `meal_item` is removed, the meal and its other items remain, and the linked user gets exactly one in-app notification, even if several meals or items are affected; a user whose account no longer exists gets none, and a user who is no longer linked still does (integration tests with two users, D66).
- [x] F18.6 Deleting a user whose meal is referenced by a `planned_meal`, in their own meal plan or in a linked user's plan, succeeds: in the linked user's plan only those planned meals are removed (the meal day, the other planned meals and the other user's meals remain), and the affected linked user gets the same single notification as in F18.4 (integration tests, real Postgres, D71).

**Implementation notes (#50).** `GET /me/export` builds the ZIP in memory (`services/data_export.py`); every query is scoped to the caller, `password_hash` is not exported, and columns that name another user (`created_by`, `edited_by`, `decided_by`) are left out, so a coach's id never appears in an athlete's archive. Plan versions include their training days, planned exercises, meal days and planned meals. File name uses the user's local date. The UI is the page `/account` (link "Account" in the header): "Export my data" downloads the ZIP; "Delete account" reveals a password field, a wrong password (403) shows "nothing was deleted", success signs the user out and lands on the sign-in page. `POST /me/delete` (`services/accounts.delete_account`) runs in one transaction: verify the password (403 `forbidden`, nothing changes), delete other users' notifications that name the user as `actor` or `athlete_id`, send `link_ended` (empty payload) to the other side of every active link, call `notify_content_removed`, delete the user's failed sign-in rows, delete the user; the database cascades the rest. Nothing is logged. This ships in a release after #157 (a null `plan.created_by` appears only after a deletion).

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
| `MealDay` / `PlannedMeal` | plan_id, weekday (unique per plan), order, warning (nullable), edited_by (nullable) · slot, order, meal_id, portion_factor, meal_key (D73) |
| `Session` | id, athlete_id, plan_id, training_day_id, date, status (`planned`/`in_progress`/`done`/`missed`), started_at, finished_at, completion, kcal |
| `SetLog` | session_id, planned_exercise_id (nullable for extras), exercise_id, set_no, target_reps/weight/seconds (snapshot), reps, weight_kg, seconds, distance_m |
| `MealLog` / `MealLogItem` | athlete_id, date, planned_meal_id (nullable, plain id), slot, meal_key (D73; planned meals: unique per athlete, date, meal_key; copied from `PlannedMeal.meal_key`), slot_index (deprecated), status (`eaten`/`adjusted`/`skipped`/`extra`), logged_at · food_id, position, grams |
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
- Seeded demo data command: `make seed-demo` runs `python -m app.cli.seed_demo` in the running backend container, after the migration step and never on app start. It loads one athlete (onboarded, targets, generated training and meal plan, time zone Europe/Madrid) with 8 weeks of history up to today and one coach with an `active` link to them, all through the same services the API uses. History: at least 20 finished sessions with set logs (some partial, some missed), meal logs on at least 40 days, at least 8 weigh-ins, extra activities, and pending and decided progression suggestions. It is idempotent (a finished demo is left untouched; a half-built one from a failed run is rebuilt), refuses to run when `APP_ENV` or `FITWISE_ENV` is `prod`, and logs counts only. Credentials (test data) are in the README.
- Health checks on every service; `docker compose up --wait` succeeds only when all are healthy.

## 12. Deployment (AWS)

- **Two EC2 instances**: `fitwise-dev` and `fitwise-prod` (Amazon Linux 2023 or Ubuntu LTS, Docker + Compose). Prod also runs the observability stack and the on-call responder. Region **us-east-2**; `fitwise-dev` is a **t3.small** and `fitwise-prod` a **c7i-flex.large** (t3.medium is rejected by the account's Free plan; about USD 89 per month in total; D52).
- Reached via each instance's **public DNS name over HTTP** (see §6.4 limitation). Elastic IPs keep addresses stable.
- Security groups: 80 open; 22 closed (the owner uses **SSM**; deploys are pull-based); Grafana port restricted to the owner's IP; prod OTLP port open only to the dev instance.
- **Pull-based deploys** ([ADR 0010](adr/0010-pull-based-deploy.md), D57): GitHub holds no AWS credentials and the hosts open no inbound ports for deployment. CI records the approved tag; a systemd timer on each host polls it through the public GitHub API, then pulls, deploys, health-checks and rolls back by itself. This needs the repository and GHCR packages to be public.
- Images are built once per commit and pushed to GHCR tagged with the git SHA. Each server keeps `CURRENT_TAG` and `PREVIOUS_TAG` for rollback.
- Database backups: nightly `pg_dump` to S3 (prod), 7-day retention. A systemd timer (`fitwise-backup.timer`, 03:00 UTC) runs `deploy/backup.sh`, which writes a validated custom-format dump to the private, encrypted bucket `fitwise-prod-backups-<account id>` under `prod/`; a lifecycle rule expires objects after 7 days. The prod instance role `fitwise-ec2-prod` can only put/get `prod/*` in that bucket (no keys on the host). A failed run exits non-zero and the unit shows as failed in `journalctl -u fitwise-backup`. Restore procedure: `deploy/README.md`.
- Infrastructure steps documented in `deploy/README.md` (scripted bootstrap; IaC is a roadmap item).

## 13. CI/CD (GitHub Actions)

| Trigger | Pipeline |
|---|---|
| Pull request | Lint (ruff, eslint), type-check (mypy, tsc), unit + integration tests, frontend tests, OpenAPI validation, dependency scan, secret scan, build images (no push) |
| Merge to `main` | Same checks → build & push images (`sha` tag) → **record the approved tag for dev** (move ref `deploy/dev` to the SHA) → the dev host's timer pulls and deploys → smoke test (`/readyz` + e2e smoke) against the public URL |
| Manual `workflow_dispatch` "Promote to production" | Choose an already-deployed-to-dev SHA → GitHub Environment `production` requires approval → the job in that environment moves `deploy/prod` to the SHA → the prod host's timer deploys it → smoke test → if the health check fails, **the host rolls back to `PREVIOUS_TAG` by itself** |
| Manual "Rollback production" | Same approval gate. Moves `deploy/prod` back to the last release that was **verified good on prod** before the current one (read from the `deploy/prod` history and the version on prod's `/healthz`; a record counts only if the run that wrote it succeeded, D67; see `deploy/README.md`); the host restarts it from `PREVIOUS_TAG` without the migration step and the job checks `/healthz` `version`, `/readyz` and the e2e smoke. The host also rolls back locally on a failed health check, and the on-call agent's `oncall/ops/rollback.sh` wraps the same host script |

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
- No database writes, no secrets access beyond its own env file, no arbitrary shell. Timeout 20 min. Authenticates with the owner's Claude subscription token (`CLAUDE_CODE_OAUTH_TOKEN`, from `claude setup-token`; an `ANTHROPIC_API_KEY` is the alternative, D72). Spend is bounded by the plan's usage limits and the timeout, plus a per-run cap of USD 5 (`--max-budget-usd`, `ONCALL_AGENT_MAX_BUDGET_USD`). The credential lives only in `/etc/fitwise-oncall.env`, root-only.
- Enforcement (#69): the allow-list is the agent's `--settings` permission rules (default mode `dontAsk`), and a `PreToolUse` guard hook re-checks every Bash/Read/Write/Edit call against the exact allowed shapes, refuses chained commands, and lets only the first of `flag.sh`/`rollback.sh`/`restart.sh` run per incident. On the host the agent is the unprivileged `fitwise-oncall` user (no docker group); compose and rollback go through `sudo -n` helpers that validate their arguments again. The full transcript is saved to `incidents/<id>/transcript`.

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
| D46 | Editing the profile (owner only; coaches can view) recomputes targets from today and rescales meal portions from today on (D74) without a suggestion, because the athlete made the change; the training plan is regenerated only on request |
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
| D58 | CD to dev ([#13](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/13)): (1) the `deploy/dev` and `deploy/prod` branch refs are moved by the built-in `GITHUB_TOKEN` (`contents: write` on that job only), not by PATs or Apps; (2) merge to deployed on dev target = 10 minutes; (3) the ref points at a deploy commit (parent and tree = the previous deploy commit, so a ref update never changes `.github/workflows/`, which GITHUB_TOKEN may not do; the first deploy of a new ref has no parent commit and a README-only tree; amended under [#14](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/14)) whose message carries the source SHA and the image digests, so one unauthenticated request per poll (every 150 s, 24 per hour) gives the host everything; (4) `GET /healthz` returns `version` (the release's commit SHA, `APP_VERSION`); (5) a ruleset limiting `deploy/*` to GitHub Actions is impossible on a personal repository (the Actions app cannot be a bypass actor), so the owner being the only writer is the accepted protection until the repository is in an organization (owner, 2026-10-24) |
| D59 | Lower QA token cost (owner, 2026-10-24): (1) QA keeps tool output short (`pytest -q --tb=short`, `\| tail`, `logs --tail`) and doesn't re-read `CLAUDE.md` or all of `process.md` §6; (2) the engineer runs QA's blocking project-rule checklist on its own diff before opening the PR, to cut FAIL rounds; (3) the orchestrator may run QA on Haiku for a re-verification round after a FAIL or a docs/config-only PR, never for a first verification of a code PR; (4) the orchestrator starts QA with the PR, head SHA, CI run URL and AC list. See [team.md](team.md#models-and-effort) |
| D60 | Full-gym accessories prefer machines and cables (owner, 2026-10-24, from QA of #23; #110): ranking accessories by lowest MET first picked band exercises ahead of machines and cables, which is odd in a gym. In `full_gym` the accessory ranking is now equipment tier first (`machine`, `cable`), then MET, name, id; the tier outranks "not yet used in the plan". Main lifts and the other variants are unchanged. Avoided-exercise replacement (F5.6) still looks for the same equipment first |
| D61 | Prod auto-rollback demo (#14): to demonstrate the host rollback on prod without a build that is bad only on prod, a **host-side switch** is used: while the line `FITWISE_DEMO_FAIL_HEALTH=1` is in the root-only `/opt/fitwise/.env`, `deploy/deploy.sh` treats the post-deploy health check as failed and runs the normal `rollback.sh` path (no migration, D50). Off unless that exact line exists, on any host; `rollback.sh` ignores it; the application does not read it; the file is never printed. It is added for the demo and removed afterwards (procedure in `deploy/README.md`) (owner, 2026-10-24) |
| D62 | "Rollback production" ([#113](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/113)): the previous SHA is read from the history of the ref `deploy/prod` relative to the version prod's `/healthz` reports (CI cannot reach the host); the poller sends a release equal to `PREVIOUS_TAG` to `rollback.sh` (no migration step, D50), anything else to the normal deploy; `oncall/ops/rollback.sh` takes no arguments and wraps the host's `rollback.sh` (owner brief, 2026-10-24) |
| D63 | Prod database backups ([#66](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/66)): `pg_dump -Fc` (custom format, already compressed) rather than plain SQL + gzip, so a restore is `pg_restore` and a dump can be validated with `pg_restore --list` before upload. The prod host gets its own role `fitwise-ec2-prod` (not the shared `fitwise-ec2-ssm`) so the dev host cannot read production dumps; no `s3:DeleteObject` (the 7-day lifecycle rule deletes). Dumps contain health data: bucket is private, encrypted and TLS-only (orchestrator brief, 2026-10-24) |
| D64 | Foods and meals (#34): a food's `diet_tags` list every diet it suits besides omnivore, so a vegan food carries `vegan`, `vegetarian` and `pescatarian`, a vegetarian one `vegetarian` and `pescatarian`, fish `pescatarian`, and meat none (omnivore suits every food). A meal's diets are the intersection of its foods' tags and its allergens their union, computed in `engines/meal_macros.py`, never stored. Meal macros round once at the end (kcal to a whole number, grams to 0.1). `POST /meals` with a food that does not exist or is not visible to the caller returns the same `404 food_not_found` (no id probing). Until coach links land (#47) a custom food or meal is visible to its creator only. Seed foods and meals are matched by deterministic id or lower-cased name, so renaming a seed row never breaks the seed (owner brief, 2026-10-24) |
| D65 | Suggestions persistence (#85): (1) the finish hook and any edit of a finished session inside its window (log/replace/delete a set, re-finish) replace the session's *pending* progression suggestions; exercises that already have a decided suggestion from that session are not suggested again. A skipped or `manual` exercise gets none; every other performed exercise gets exactly one, including `hold`. (2) The engine's failure counter and first-session flag are derived from the athlete's earlier suggestions (`inputs.consecutive_failures_after`) and earlier set logs of the exercise. (3) Accepting stores the accepted (or overridden) targets as a **new plan version** (F8.2) with a `PlanChange`, like any other plan edit; the version keeps the old plan's `created_at` so the calendar template still starts on the same day. Finished and in-progress sessions stay on the version they were performed against, so their targets, completion and later late-logged set snapshots never change (F8.1, rule 7); untouched `planned` sessions from today on move to the new version, and pending suggestions follow their exercise to it. Linear exercises keep one rep target (`reps_min = reps_max`); overrides of the wrong kind (calorie `kcal`, seconds on a set-based exercise, weight/reps on a timed one, two different linear rep targets, `reps_max < reps_min`) are `422 invalid_overrides`. (4) Other athletes, unlinked coaches and unknown suggestion ids are `403 not_linked` (D41); a linked coach may list and decide since #47 (D82). (5) The `progression_engine` flag selects the engine from a registry; only `v1` exists, so any other value runs `v1`; the version used is stored in `inputs.engine_version`. (6) An older still-pending suggestion for an exercise is not superseded by a newer one; the session banner shows the newest. |
| D64 | Foods and meals (#34): a food's `diet_tags` list every diet it suits besides omnivore, so a vegan food carries `vegan`, `vegetarian` and `pescatarian`, a vegetarian one `vegetarian` and `pescatarian`, fish `pescatarian`, and meat none (omnivore suits every food). A meal's diets are the intersection of its foods' tags and its allergens their union, computed in `engines/meal_macros.py`, never stored. Meal macros round once at the end (kcal to a whole number, grams to 0.1). `POST /meals` with a food that does not exist or is not visible to the caller returns the same `404 food_not_found` (no id probing). Until coach links land (#47) a custom food or meal is visible to its creator only. Seed foods and meals are matched by deterministic id or lower-cased name, so renaming a seed row never breaks the seed (orchestrator decision, 2026-10-24) |
| D66 | Account deletion and custom foods (#131, owner decision 2026-10-28): `meal_item.food_id` must not block the user-deletion cascade. When a user is deleted, any `meal_item` that references one of their custom foods is removed, including items in a linked user's meal (linking: D10); the linked user's meal and its other items stay. The deleted account produces one in-app notification (F17) for each affected linked user, however many meals or items are affected. A notification is sent only if that user's account still exists, whether or not they are still linked. A deleted user's own meals and foods are deleted with them (F18.2). The migration is expand-only (rule 8). F18 and F18.4 updated. Implementation (#131): a BEFORE DELETE trigger on `users` removes those items, so `food_id` stays RESTRICT and deleting one used food through the API is still refused (#34); the notification is added by #45/#50, which must collect the affected user ids before the delete |
| D67 | Last good release for "Rollback production" ([#122](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/122)): the `deploy/prod` history is only a candidate list. `scripts/rollback-plan.sh` targets the newest older release whose record was written by a "Promote to production" or "Rollback production" run on `main` that finished **successfully** (its last job, prod serves the SHA + readyz + e2e smoke, is green), found through the `run:` line CI adds to every deploy commit and the Actions API with `GITHUB_TOKEN` (`actions: read`); a release that failed on the host and was rolled back automatically is skipped, and if no earlier good release exists the plan fails. Records from before the `run:` line count only if listed in `deploy/legacy-good-releases.txt`. This keeps the pull-based model (ADR 0010; no host-to-CI channel, no AWS identity under the SCP). On the host, `rollback.sh` leaves `PREVIOUS_TAG` unchanged (so after a rollback `PREVIOUS_TAG == CURRENT_TAG`) and writes the release it rolled back from to `/opt/fitwise/ROLLED_BACK_FROM` (the failed release after an automatic rollback); a no-argument rollback (on-call) with `PREVIOUS_TAG == CURRENT_TAG` exits 3 and one whose target equals `ROLLED_BACK_FROM` exits 4, both meaning escalate to the owner; going forward again is "Promote to production". A successful deploy clears the note (orchestrator on behalf of the owner, 2026-10-24) |
| D68 | Meal plan generator (#36): engine selection rules, warnings and seed as listed under F7 "Engine choices inside the rules"; meal days are stored per plan version in `meal_day` / `planned_meal` (expand-only migration, rule 8); `planned_meal.meal_id` is `ON DELETE RESTRICT`; the view scales each food's grams by `portion_factor` (rounded to 0.1 g) and computes macros from the scaled grams (orchestrator brief, 2026-10-29) |
| D69 | Account deletion and author/editor references (#148): the foreign keys `plan.created_by`, `plan_change.author_id`, `training_day.edited_by`, `meal_day.edited_by` and `suggestion.decided_by` to `users.id` are `ON DELETE SET NULL`, so deleting a user (athlete or linked coach) is never blocked by them. A coach's deletion leaves the athlete's plan, changes and suggestions in place and clears only the coach reference; the API returns `created_by: null` (OpenAPI `Plan` and `PlanVersion`) like `edited_by` and `decided_by` already could. `plan.created_by` and `plan_change.author_id` become nullable (expand-only; the previous release still writes values). `planned_meal.meal_id` RESTRICT is handled in D71 (#154) |
| D70 | Meal logging (#37): `fitwise_meal_checkoffs_total` counts each newly created log of a planned meal (eaten, adjusted or skipped), once; repeats and status changes on an existing log do not count, and extra food does not count. Every plan version creates new `planned_meal` ids, so a planned meal is identified across versions by a stable `meal_key` (D73, which replaces the original (date, slot, slot index) position rule) and the check-off is unique on (athlete, date, meal key); `planned_meal_id` is a plain id (not a foreign key) and the day view returns the current id. A day's planned meals come from the latest plan version created on or before the end of that day that has a meal day for its weekday, so a later version never rewrites an earlier day and a version that lacks meal days (#158) does not hide the meal plan. A log that matches no planned meal (for example its slot no longer exists) is returned in `extra_meal_logs` with its status, so everything that counts in `energy.eaten` can be seen and undone. `eaten` stores the planned grams at logging time. `meal_log_item.food_id` cascades on food delete (never blocks user deletion, D66). Day energy fills `eaten`, `planned` and `balance_kcal = eaten - burned`; `target` and the baseline arrive with #38. Migration is expand-only (two new tables). |
| D71 | Account deletion and planned meals (#154): `planned_meal.meal_id` must not block the user-deletion cascade, with the same rule as D66. When a user is deleted, any `planned_meal` that references one of their meals is removed, including rows in a linked user's meal plan; the linked user's plan, meal days, other planned meals and meals stay. The affected linked user gets the one in-app notification of D66 (the same event, "food removed from a meal" is extended to "meal or food removed because its owner deleted their account"; at most one per deleted account, however many rows are affected), added by #45/#50, which must collect affected user ids before the delete. Implementation: a second BEFORE DELETE trigger on `users`; `meal_id` stays RESTRICT so deleting one used meal through the API is still refused (#34). Expand-only migration. See [ADR 0011](adr/0011-user-deletion-vs-shared-references.md) |
| D72 | On-call agent authentication (#69): the owner will not use an Anthropic API key with a Console spend limit. The agent on fitwise-prod authenticates with a Claude subscription token (`claude setup-token`, run by the owner locally) in `/etc/fitwise-oncall.env` as `CLAUDE_CODE_OAUTH_TOKEN`. With the agent enabled the responder requires `GH_TOKEN` and one Claude credential (the token preferred, `ANTHROPIC_API_KEY` as alternative; if both are set only the token is passed to `claude`), and refuses to start with neither. `--max-budget-usd` stays as a per-run cap; there is no Console limit, so spend is bounded by the subscription's usage limits and the 20-minute timeout. Supersedes the API-key and monthly-limit wording in spec §15.2 and ADR 0007 |
| D73 | Meal log identity (#159, replaces the position rule of D70): a meal log belongs to the meal it was made for, not to a position. `planned_meal.meal_key` (uuid) is the stable identity of a meal slot across plan versions: `create_plan_version` copies it forward when it carries meals over, and any code that rebuilds meal days (the meal-plan editor, #39) must pass the key of every meal it keeps; a meal added by hand gets a new key. `meal_log.meal_key` stores the key of the planned meal at logging time; the check-off is unique on (athlete, date, meal key) and a CHECK rejects a planned-meal log without a key. Consequences: after a same-day reorder a logged meal still shows its log and `energy.eaten` never counts it twice; a repeat check-off returns the existing log (`200`, not counted again); the same meal twice in a slot has two keys and two independent logs; a removed meal's log moves to `extra_meal_logs` (visible and undoable). A meal with a new key (replaced rather than edited) does not inherit logs. `meal_log.slot_index` is deprecated: written for rollback compatibility, never read. Migration is expand-only and rollback-safe: two nullable columns, backfilled with the D70 position rule (key = md5 of athlete, weekday, slot and position in slot) so existing logs keep their meal; the old position unique index is replaced by the key index. The previous release, running on this schema after a rollback, inserts planned meals and planned logs without a key, so BEFORE INSERT OR UPDATE triggers on both tables fill a missing key (a log takes the key of the planned meal it points to, so it matches meals created by either release, and falls back to the position formula only when that meal is unknown; a meal takes the position formula), so the CHECK holds for both releases; the new code keeps writing `meal_log.slot_index` so the previous release still matches new logs. Contract step (a later migration, once no release older than D73 can run): drop the two triggers and `slot_index`, and make the keys NOT NULL. A rollback uses the previous image on this schema, not the downgrade; running the downgrade and then upgrading again re-derives every key from position, so the identity of logs after a reorder is lost (the downgrade is for development and emergencies). Downgrade drops the triggers and keys and nulls duplicate `slot_index` values before recreating the old index. No API change. |
| D74 | Targets change rescales meal portions (#171, owner decision, 2026-10-30): whenever the athlete's targets change, `portion_factor` is recomputed on meal days **from today on**, so each day's planned kcal follow the new target. The three paths are accepting a `recalc` suggestion, editing the profile (D46) and accepting a `calories` suggestion (F14, #42); all call one shared service. Past days are never touched (rule 7). Mechanics: the rescale is stored as a new plan version (`create_plan_version`) that carries every `meal_id` and `meal_key` (D73) forward and changes only `portion_factor` (clamped to the existing `0 < factor <= 3` check, never an error), so logs stay attached. Today is included: unlogged meals of today are rescaled, while a meal already logged today keeps its logged grams (`eaten` stores grams at logging time, D70) and still matches by key. A plan with no meal days is left as is. Custom (edited) plans are rescaled the same way: meals, foods and keys are never replaced, only portions. Supersedes the narrower `acceptSuggestion` wording in `openapi.yaml` (code and contract follow in #171) |
| D75 | Plan editor (#39): (1) Every custom edit (`PUT /plan/training`, `PUT /plan/meals`) and every regeneration stores a **new plan version** (D65 pattern); the previous version stays readable. Edits set `source = custom`, regeneration `generated`. (2) `revision` is monotone across versions: a new version has the previous `revision + 1`, so a client holding an older one gets `409 plan_revision_conflict` (the athlete row is locked, so concurrent edits are serialised). (3) `plan_change` gets `author_role` (`athlete`/`coach`, expand-only nullable column, backfilled) next to `author_id` and `created_at`; `change` holds the kind and counts only, never plan content. (4) New versions get `created_at = now` (meals are resolved by version creation time, D70) and the calendar template starts at the athlete's *first* plan, so edits do not move the start. Sessions that were started or finished stay on their version; untouched `planned` sessions from today on move to the new version (or are dropped if their weekday is no longer a training day); pending progression suggestions follow their exercise, or are rejected when it was removed or replaced. Days that were never opened are still derived from the current template (D65). (5) Training edits: strength/bodyweight need `reps_min` (linear: one rep target), timed need `target_seconds` and no reps or weight; `increment_kg` defaults to the exercise\'s; unchanged days keep their stored F13.2 kcal and `edited_by`, changed or new days are priced at the current weight and labelled with the author. Violations are `422 invalid_plan` with `errors[]`. (6) Meal edits: a planned meal sent with its `id` keeps its `meal_key` whatever changes (reorder, other meal, portion, grams, even another weekday), so its log keeps showing (D73); no `id` = new meal, new key, no logs; weekdays missing from the request end up with no meals; days whose meals did not change keep the generator warning, edited days lose it. Gram overrides (`items`) are the final amounts: they create an athlete-owned copy of the meal at portion factor 1 (reused when the grams equal the base meal\'s), so the shared meal is never changed; the copy is listed in the athlete\'s own meals. (7) Regenerate: training is generated from the profile at the latest weight, meals from the current targets (no recalculation of targets); regenerated meals get new keys, so their logs move to `extra_meal_logs` (D73). (8) F8.4: the plan editor UI is for the athlete; the API accepts a linked coach since #47 (D82), coaches without a link and strangers get `403 not_linked`. |
| D76 | Chart data API (#43, F15): (1) Series are built on the server in a fixed number of queries per range; p95 < 500 ms with a year of data is measured by `backend/tests/integration/test_charts_perf.py`. (2) Weights are returned in kg and converted to the user's display units by the client (rule 5, F15.4). (3) **Set status**: `met` when reps (seconds if timed) reach the target and the weight reaches the target weight when there is one, else `partial`; a planned set never logged is `missed`, a skipped one `skipped`, a set beyond the plan `extra`. Set completion is min(actual, target) ÷ target on reps (seconds if timed). (4) **Exercise over time**: one point per *finished* session containing the exercise, skipped sets excluded; the target is the snapshot on the set logs; top set = heaviest set (most reps on a tie; longest for timed; bodyweight exercises rank by reps); `is_pr` = the top set beats every earlier finished session of the exercise, including those before the chosen range, and is above zero. (5) **Adherence**: the day training completion is `null` on rest, planned and future days and `0` for a missed session; day nutrition completion is F12.2 for days up to today (`null` without a meal plan or in the future); week values are the mean of the days that have a value; weeks start on Monday and `sessions_planned` counts the non-rest days of the week inside the range. (6) **Weekly summary**: `avg_completion` is the mean of the day completions as above; `avg_daily_balance_kcal` averages only elapsed days that have food logged (an untracked day would otherwise show just minus the burned kcal); `target_daily_balance_kcal` is the `Targets` row valid on the last elapsed day; `weight_avg_start_kg` / `_end_kg` are the 7-day averages (F14.1) ending on Monday and on the last elapsed day of the week. (7) **Body**: one point per day that has a weigh-in or a body-fat value in the last `weeks` weeks; the 7-day average also uses weigh-ins from the 6 days before the range. (8) Access is owner or linked coach (D82); other ids are `403 not_linked` (D41), as are unknown or foreign session ids. A `weeks` outside 4/12/26/52 is `400 bad_request`. |
| D77 | Backend CI headroom (#181): (1) The backend test job runs pytest-xdist (`-n auto`; each integration test already creates its own database, so tests are isolated) and keeps its 15-minute timeout, about 2x the parallel duration (was ~13 min serial). Parametrize ids must be deterministic (no random uuids) or xdist aborts with "different tests were collected". (2) Wall-clock perf tests carry the `perf` marker (`test_charts_perf.py`, D76(1)); `make test-backend` skips them and CI runs them serially in the separate `backend-perf` job with `continue-on-error`, not part of `ci-passed`: a noisy runner shows a red step there but never blocks a merge. Run them locally with `make test-backend-perf`. (3) `getSessionChart` has no 404 in `openapi.yaml`: unknown ids are `403 not_linked` (D41, D76(8)). |
| D78 | Adaptive calories (#42, F14): (1) The job evaluates each athlete once per Monday (`inputs.evaluated_on`), so re-running it is harmless; it can run on any day and covers the weeks before the current local week. A new check replaces an older still-pending `calories` suggestion; decided ones are kept. (2) A week's trend is the change of the 7-day average (F14.1) ending on its Sunday versus the one ending on its Monday, in percent of the latter; if either average has no weigh-in the week cannot be measured and nothing is suggested (no hint). (3) A week has "enough" data with ≥ 4 weigh-ins dated Monday to Sunday; otherwise no suggestion and `weigh_in_hint` (counts per week) is returned from `GET /athletes/{id}/suggestions` for the current week. (4) Band edges are inside the tolerance. (5) **Calorie floor (F3.6)**: a −150 step that would land below the floor is not created (the engine's reason says so); +150 is never limited, so `floor_applied` stays `false` and `delta_kcal` is always ±150. Accepting still clamps to the floor and rescales through the shared D74 service. (6) Owner-only like every suggestion decision until #180. (7) **Scheduling**: `fitwise-adaptive-calories.timer` (Persistent, 01:00 UTC +- 10 min) runs `deploy/adaptive-calories.sh`, which executes the CLI inside the running backend container, on dev and prod (installed by `deploy/bootstrap.sh`). "This week" is decided per athlete in their own time zone, so the timer fires on Monday and on Tuesday: the Monday run serves UTC and the zones east of it, the Tuesday run the zones west of UTC (UTC-12 reaches Monday at 12:00 UTC); the per-Monday idempotence (1) makes the second run harmless. The unit logs only statuses and the created count. |
| D79 | In-app notifications (#45, F17; owner decisions 2026-10-31): (1) **Progression**: one `progression_suggestion` notification per suggestion created (`payload.suggestion_id`), not one per session; a re-finish inside the edit window notifies only suggestions it newly creates, and a notification is unique per (user, type, suggestion). (2) **Recalc**: when a newer pending `recalc` suggestion replaces an older one, the older suggestion's notification is deleted if still unread, so at most one unread `recalc_prompt` exists; calorie and progression notifications stay after their suggestion is replaced or decided. (3) **Today banners**: unread `progression_suggestion`, `calorie_suggestion`, `recalc_prompt` and `content_removed` notifications show as banners on Today, at most 3, then a "See all" link to the inbox; a banner can be opened or dismissed, and both mark the notification read. (4) **New type `content_removed`** for D66/D71 (food or meal removed because its owner deleted their account), with an empty payload (no names, no ids of the deleted account); one per affected linked user per deleted account, collected before the delete; the delete endpoint (#50) calls the collector. (5) `POST /notifications/{id}/read` for another user's or an unknown id is `403` (D41); the `404` is removed from the contract. (6) Only the owner reads their notifications; coach events (`coach_note`, link events, `plan_edited_by_coach`) are created by #46, #47 and #49 through the shared `notify()` service. (7) #45 is split: the backend stays in #45, the bell, inbox and banners move to a UI issue that depends on it. |
| D80 | Plan editor UI (#40): route `/plan` (tab next to Progress in the calendar navigation) with Training, Meals and History tabs; shown to the athlete only (D75(8)), a coach sees a notice. Both drafts live in the browser until saved; a save sends the `revision` the draft started from. Every save, reload or regeneration rebuilds both drafts from the new version (planned meal ids change per version, D73), so saving is blocked while the other tab has unsaved edits. On `409 plan_revision_conflict` the plan is refetched and the draft is kept: the athlete either saves over the latest plan (sends the refetched revision) or reloads and drops the draft; nothing is overwritten silently. `422 invalid_plan` `errors[]` are shown next to the field named by the API path. Weights are shown in the user's units and sent in kg. Replacing a meal keeps its `id` (so its log stays, D75(6)); edited grams are sent as final amounts with portion factor 1. Regenerate (scope all) asks for confirmation first (D75(7)). |
| D81 | Coach linking (#46, F16): (1) Tables `coach_profile` (a coach without a row is `bio=""`, `discoverable=true`), `coach_link` (one row per request; partial unique indexes allow one `active` and one `pending` link per athlete, so a race ends in `409 link_exists`) and `entitlement` (no row = `can_have_coach` true; a false row gives `403 entitlement_required` on `POST /coach-links`). (2) A link notification payload is `{link_id, actor}` where `actor` is `{id, role}` only: no display name, so rule 6 holds for stored notifications too; the contract's `NotificationPayload.actor` changes from `UserRef` to the new `NotificationActor`, and `CoachProfile` is a flat schema (the `allOf` with the closed `CoachProfileInput` could never validate). (3) Search is submitted, not typed live: the UI sends a request only for 3+ characters. An exact-email match returns only discoverable coaches, like a name match. (4) The athlete UI is the `/coach` page (a `Coach` tab next to Progress): search with Request, then a card with End link for a pending or active link. The coach opens the same page from Today (profile form, incoming requests with Approve/Decline, linked athletes with End link). `Me.active_coach` and `Me.pending_coach_link_id` are now filled. (5) Unknown link id is `404`; a user who is not a party gets `403`; a wrong-role caller of approve/decline gets `403 wrong_role`. |
| D82 | Coach authorization layer (#47, F16; owner confirmations 2026-10-31): (1) One place decides athlete access: `app.services.access.resolve` behind the dependencies `OwnerAccess`, `OwnerOrCoachAccess`, `OwnerSession`, `OwnerOrCoachSession` and `OwnerOrCoachSuggestion` in `app/dependencies.py`, driven by the operation's `x-fitwise-access`. Routers pass `access.athlete` (the owner) to services and `access.actor` where the author matters. Only a `coach_link` with `status = 'active'` counts, queried on every request, so ending a link applies to the next request. (2) `owner`: a coach with an active link gets `403 wrong_role` (F16.4); a coach with no, `pending`, `declined` or `ended` link, any other athlete and an unknown athlete id get the same `403 not_linked` (D41); a coach calling `athletes/me/...` gets `403 wrong_role` on `owner` operations and `403 not_linked` on `owner-or-coach` operations; a malformed id stays `400`. (3) `owner-or-coach` includes writes: a linked coach may call `PUT plan/training`, `PUT plan/meals`, `POST plan/regenerate` and accept or reject suggestions through the API; the new plan version stores `PlanChange.author_role = coach` and `author_id` = the coach (D75(3)). D75(8) only restricted the athlete-facing editor UI; the coach-facing edit UI arrives with #48. (4) `/suggestions/{id}` keeps D65(4): an unknown id and another athlete's suggestion are `403 not_linked` for owner and coach alike, and `openapi.yaml` now says `403` instead of `404`. D65(4), D75(8) and D76(8) ("owner only until #47") are superseded by (1)-(3). (5) `GET body-metrics` is `owner-or-coach` as in the contract. (6) The authorization matrix test (`backend/tests/integration/test_authorization_matrix.py`) is generated from `x-fitwise-access`, fails on a missing or unknown value, and keeps a `NOT_YET_IMPLEMENTED` list (`/coach/athletes` #48, notes #49, `/me/delete` and `/me/export` #50) whose entries the owning issue removes. |
| D83 | Coach dashboard (#48, F16, F16.5; owner decisions 2026-10-31): (1) **Order**: `needs_attention = true` athletes first, then the rest; inside both groups by display name (case-insensitive), then athlete id. (2) **`inactive`** = no log of any kind (set, meal or weigh-in) for 3 or more days (2 days does not trigger); an athlete who never logged is counted from `linked_since`, so is flagged no earlier than 3 days after the link. The days are counted on the athlete's own "today" (rule 5). (3) **`training_adherence_7d`** is `null` when no session was planned in the last 7 days (nothing with a value in `today-6 .. today`: rest, or only today's untouched session); it never triggers `low_adherence` and the UI shows it as "–". Otherwise it is the mean completion of the planned days of that window, a missed session counting 0, like the adherence chart. `low_adherence` is strictly below 0.70. (4) **`deload`** when a deload suggestion is pending, or one was accepted at most 14 days ago (day 14 triggers, day 15 does not; local days of the athlete). (5) The rules and the order are the pure `engines/coach_attention.py` (constants in `engines/constants.py`); `GET /coach/athletes` runs a fixed number of queries whatever the number of clients and `CoachAthleteSummary` also carries the athlete's `units` and `timezone` so the coach context can show the client's display units and "today". (6) **UI**: `/coach/clients` (a table from 1024 px, cards below; the API order is never re-sorted), `/coach/clients/:athleteId[/week|/month|/body|/plan|/progress|/progress/session/:id|/profile]` inside a shell with a banner (client name, "Back to clients"). The shell takes the client from the list of active links, so an id that is not (or no longer) linked shows a not-linked page and requests no data. Every request there uses the athlete id, never `me`; there are no logging controls (F16.4). Coaches land on the client list instead of Today. The athlete's own Today lists the latest accepted/rejected suggestions, naming the coach when a coach decided. "Edited by <name>" is shown only when the last editor of a plan day is a coach (a later hand edit by the athlete clears it). The UI has English strings only (D5; no Spanish resource exists yet, so the "EN and ES" wording of #48 is not applicable). (7) **Suggestion decisions**: accepting a progression suggestion writes one `PlanChange` (`suggestion_accepted`) per decision, like every other accept (D65(3)); the extra default `created` row it wrote before #48 is gone. (8) **Ending a pending link** (D81): a coach ending a `pending` request declines it, so the link becomes `declined` and the athlete gets `link_request_declined`; an athlete ending their own pending request withdraws it (`ended`, coach gets `link_ended`); an `active` link ended by either side is `ended`. |
| D84 | Coach notes (#49, F16, F17; owner confirmation 2026-10-31): (1) **Confirmed owner decision: notes stay visible to the athlete after the coach link ends.** F18 removes a note only when its author deletes their account (or the athlete deletes theirs). The former coach loses `create`, `list`, `edit` and `delete` at once (403 `not_linked`, F16.1). (2) Table `coach_note` (expand-only, rule 8): `athlete_id`, `author_id`, `session_id` and `exercise_id` all `ON DELETE CASCADE`; check constraints keep `scope` and its target consistent and the text at 1 to 2000 characters. (3) Create is `x-fitwise-access: coach` (an athlete, also on themselves, gets `403 wrong_role`; no or ended link `403 not_linked`); a `session_id` of another athlete, an unknown session or exercise, or a custom exercise of another user is `404`. `scope=session` and `exercise` with a `session_id` store that session's date as `date`; an exercise note without a session has no date. (4) Edit and delete are `author`: the access check (owner or active coach) runs first, then authorship: the athlete gets `403 forbidden`, another coach, a stranger and the former coach `403 not_linked`; an unknown note id is `404`. (5) Exactly one `coach_note` notification per created note (not per edit), payload `{note_id, date?, actor: {id, role}}`: ids only, never the text (D79(6), rule 6). (6) The day view's `notes` holds notes with `scope=day` on that date, notes on that day's session, exercise notes with that `session_id`, and standing exercise notes (no session) for any exercise in that day's session; newest first. `GET notes` filters `from`/`to` on `date`, so standing exercise notes appear only without a date filter. (7) Opening a `coach_note` notification goes to `/today?date=<date>` (Today when it has no date). (8) The coach shell no longer sticks on the not-linked page: the list of active links is refetched every 15 s and by "Check again" while the page shows, and a list fetched after the error that holds the client under a new link id (a re-link) brings the views back; the same link id means a stale list and the page stays (#48 QA note); a client that stays unlinked still shows the page and requests no data (D83(6)). |
| D85 | Account deletion notifications (#50, F18): (1) **Owner decision 2026-10-31:** deleting an account also notifies every user whose logged meals (`meal_log_item`, not only meals and planned meals) lost the deleted user's custom food, once each (D66, D71, D79(4), empty payload). (2) Engineer decisions, agreed in QA: a coach or athlete deletion sends `link_ended` with an empty payload to the other side of each active link and removes notifications that name the deleted user. Export omits columns that point at other users |

## 20. Assumptions and open questions

- **A1.** Deadline and weekly availability are unknown; the delivery order (§16.2) is designed so any prefix of milestones is gradable.
- **A2.** Formula constants (lifestyle factors, goal adjustments, protein, floors, MET values, adaptive thresholds) are reasonable defaults from common practice, kept in one config module and easy to change.
- **A3.** Open Food Facts data quality varies; imported foods are shown with their source.
- **Q1.** Should training days and rest days have different calorie targets? (Currently *Could*.)
- **Q2.** Should coaches be able to create reusable program templates to assign to several athletes? (Not in MVP.)
