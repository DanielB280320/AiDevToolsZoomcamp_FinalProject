/**
 * GENERATED FILE - do not edit by hand.
 * Source: openapi.yaml (repository root). Regenerate with `npm run generate:api`.
 */

export interface paths {
    "/auth/signup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create an account and start a session
         * @description Creates an athlete or coach account (role is fixed afterwards) and sets the session cookie.
         *     Rejects users younger than 18 computed from `birth_date` in `timezone` (F1.1, code
         *     `underage`), a missing disclaimer acceptance (F1.2, code `disclaimer_required`), passwords
         *     shorter than 10 characters (F1.4) and duplicate emails compared case-insensitively
         *     (F1.3, `409 email_taken`). The disclaimer acceptance time is stored as
         *     `disclaimer_accepted_at`.
         */
        post: operations["signUp"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Sign in
         * @description Verifies the password (argon2id) and sets the session cookie. Wrong email or password returns
         *     `401 invalid_credentials` without saying which one was wrong. The 6th failed attempt for the
         *     same email within 15 minutes returns `429` (F1.6).
         */
        post: operations["logIn"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Sign out
         * @description Clears the session cookie. Idempotent; succeeds without a session.
         */
        post: operations["logOut"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get the signed-in user
         * @description Account, settings, onboarding state, coach link and unread notification count.
         */
        get: operations["getMe"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update account settings
         * @description Partial update of display name, display units and time zone. Email, role and birth date cannot change.
         */
        patch: operations["updateMe"];
        trace?: never;
    };
    "/me/delete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Delete my account and all my data
         * @description Requires the current password in the body (F18). `POST` rather than `DELETE`, because
         *     request bodies on `DELETE` have no defined semantics (spec D48). Permanently deletes every
         *     row referencing the user, ends all coach links and removes notes the user authored. A coach
         *     deleting their account ends all links; athletes' data is unaffected. Only the account holder
         *     can call this, so a coach can never delete an athlete's account (F18.3). Clears the session
         *     cookie.
         */
        post: operations["deleteMe"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export my data as a ZIP
         * @description ZIP with `profile.json`, `plan_versions.json` and CSVs for set logs, meal logs, body metrics,
         *     extra activities and suggestions (F18). Contains only the caller's own data (F18.1). There is
         *     no athlete-scoped export, so coaches cannot export an athlete's data (F18.3).
         */
        get: operations["exportMyData"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/onboarding": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Complete the onboarding wizard
         * @description One action that stores the profile, a `BodyMetric` dated today in the athlete's time zone
         *     (F2.1), computes targets (F3) and generates the training and meal plan (F5, F7) (F2.2).
         *     Values outside plausible ranges are rejected with 422 (F2.3); the number of
         *     `preferred_days` must equal `days_per_week` (F2.4). Returns `409 already_onboarded` if the
         *     athlete already completed onboarding (use the profile and plan endpoints instead).
         */
        post: operations["completeOnboarding"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/profile": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * Get the athlete profile
         * @description `404 not_onboarded` if the athlete has not completed onboarding yet (there is no profile).
         *     An unknown or inaccessible `athlete_id` is `403`, never `404`.
         */
        get: operations["getAthleteProfile"];
        /**
         * Replace the athlete profile
         * @description Replaces the profile (same validation as onboarding). If a target-relevant field changed
         *     (sex, height, lifestyle, goal, training volume), targets are recomputed with
         *     `valid_from` = today and future meal-day portions are rescaled; past days never change.
         *     The training plan is **not** regenerated automatically — call
         *     `POST /athletes/{athlete_id}/plan/regenerate`. Coaches can view but not edit the profile.
         *     `404 not_onboarded` if onboarding was not completed (create the profile with
         *     `POST /athletes/{athlete_id}/onboarding`). An unknown or inaccessible `athlete_id` is `403`,
         *     never `404`.
         */
        put: operations["updateAthleteProfile"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/targets": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * Get calorie and macro targets
         * @description Targets valid on `date` (default: today in the athlete's time zone), with the formulas and
         *     inputs used in `explanation` (F3.5). `404 not_onboarded` before onboarding.
         */
        get: operations["getTargets"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/body-metrics": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * List body metrics
         * @description Entries between `from` and `to` (inclusive), oldest first. Both default to the last 90 days.
         */
        get: operations["listBodyMetrics"];
        put?: never;
        /**
         * Log weight, body fat or measurements for a day
         * @description One entry per day: logging again for the same `date` replaces it (`200`), otherwise `201`.
         *     When neck/waist (and hip for female/unspecified) are given without `body_fat_pct`, body fat
         *     is estimated with the Navy method (F3.3). `date` cannot be in the future. When the weight
         *     differs by ≥ 2 % from the weight used for current targets, a pending `recalc` suggestion is
         *     created and returned (F14). Coaches cannot log weigh-ins (403).
         */
        post: operations["logBodyMetric"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/exercises": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search the exercise catalog
         * @description Seed exercises plus the caller's own custom exercises plus custom exercises of the caller's
         *     active-link counterpart (an athlete sees their coach's; a coach sees their athletes').
         *     Custom exercises are never visible to unrelated users (F4.3). Filterable by name, muscle
         *     group, equipment and type (F4.2).
         */
        get: operations["listExercises"];
        put?: never;
        /**
         * Create a custom exercise
         * @description Private to the creator; for coaches also usable in their linked athletes' plans.
         *     `409` (`exercise_name_taken`) when the name, compared case-insensitively, is already a seed
         *     exercise or one of the caller's own exercises.
         */
        post: operations["createExercise"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/foods": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search the local food library
         * @description Seed, imported (Open Food Facts) and the caller's custom foods; same visibility rule as exercises.
         */
        get: operations["listFoods"];
        put?: never;
        /** Create a custom food */
        post: operations["createFood"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/foods/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search packaged foods on Open Food Facts
         * @description Server-side proxy with a 3 s timeout and a 24 h result cache (F6). Behind the feature flag
         *     `off_search_enabled`. When the flag is off or the upstream times out / fails, the response
         *     is still `200` with `available: false` and a user-facing `message` (F6.3) — never a 5xx.
         */
        get: operations["searchOpenFoodFacts"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/foods/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Copy an Open Food Facts product into the local library
         * @description Stores the product as a `Food` with source `openfoodfacts` and its product `code`. Unique on
         *     `code`: importing an already-imported product returns the existing food with `200` (F6.2),
         *     otherwise `201`. Uses the cached search result when available; if the product is not cached
         *     and Open Food Facts is unavailable or disabled, returns `503 off_unavailable`.
         */
        post: operations["importOpenFoodFactsFood"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/meals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search the meal library
         * @description Seed meals plus visible custom meals. Macros are computed from the foods (F6.1).
         */
        get: operations["listMeals"];
        put?: never;
        /** Create a custom meal from foods and grams */
        post: operations["createMeal"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/plan": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * Get the active weekly plan
         * @description Training days and meal days of the active plan version. `404 not_onboarded` if there is no plan yet.
         */
        get: operations["getActivePlan"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/plan/training": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        get?: never;
        /**
         * Replace the training template (custom mode)
         * @description Replaces all training days and their planned exercises; array order is the display order.
         *     Items with an `id` are updated, items without are added, missing ones are removed. Sends the
         *     plan `revision` read with `GET /plan`; a stale revision returns `409 plan_revision_conflict`
         *     (e.g. athlete and coach editing at once). Sets the plan `source` to `custom`, records a
         *     `PlanChange` with author and timestamp (F8.3) and affects only today-and-future sessions;
         *     past sessions and logs never change (F8.1). Coach edits are labelled with the coach in
         *     `edited_by` and notify the athlete. At most one training day per weekday.
         */
        put: operations["updateTrainingPlan"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/plan/meals": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        get?: never;
        /**
         * Replace the meal template (custom mode)
         * @description Replaces the planned meals of each weekday (add/remove/replace meals per slot, change
         *     portion or grams). Same `revision`, `source`, history and authorization rules as
         *     `updateTrainingPlan`. Gram overrides in `items` are stored as a private copy of the meal
         *     owned by the athlete, so the shared library meal is never changed.
         */
        put: operations["updateMealPlan"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/plan/regenerate": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Regenerate the suggested plan from the current profile
         * @description Creates a new plan version (source `generated`) from the current profile and targets and
         *     makes it active. Previous versions stay readable (F8.2). `scope` limits regeneration to the
         *     training or meal part; the other part is copied from the current version.
         */
        post: operations["regeneratePlan"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/plan/versions": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * List plan versions
         * @description All versions, newest first.
         */
        get: operations["listPlanVersions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/plan/versions/{version}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                version: number;
            };
            cookie?: never;
        };
        /** Get a plan version (read-only) */
        get: operations["getPlanVersion"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/days/{date}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                /**
                 * @description Calendar day `YYYY-MM-DD` in the athlete's time zone, or `today`.
                 * @example 2026-11-03
                 */
                date: components["parameters"]["DayDate"];
            };
            cookie?: never;
        };
        /**
         * Get one day (Today view)
         * @description Everything the Today view needs for one calendar day (F9): the session with exercises,
         *     planned sets and logs; planned meals with their check-off state; extra meal logs and
         *     activities; the estimated energy balance and macro progress (F13.3); completions; pending
         *     suggestions; coach notes for the day, its session and its exercises. `date` may be `today`
         *     (resolved in the athlete's time zone, F9.1). Viewing a planned day materialises its session
         *     so it has an id for logging (idempotent).
         */
        get: operations["getDay"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/calendar": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * Get Week or Month view summaries
         * @description One summary per day from `from` to `to` inclusive (max 42 days, i.e. a 6-week month grid).
         *     Week view uses Monday–Sunday; month view the weeks covering the month. Past planned
         *     sessions without logs are `missed`; rest days are never missed (F9.3). A moved session is
         *     reported on its new date (F9.2). `400 range_too_large` above 42 days, `400 invalid_range`
         *     when `from` is after `to`.
         */
        get: operations["getCalendar"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        /** Get a session with its sets and logs */
        get: operations["getSession"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sessions/{session_id}/move": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Move a session to another day in the same ISO week
         * @description Moves a not-yet-finished session to `date` (F9). The new date must be in the same ISO week
         *     (Monday start, athlete's time zone), today or later, and must not already hold a session
         *     (`409 day_occupied`). Moving does not change the plan template. Only the athlete can move
         *     sessions.
         */
        post: operations["moveSession"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sessions/{session_id}/sets": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Log (or re-log) a set
         * @description Upsert keyed by (session, `exercise_id`, `set_no`) — retrying the same request never
         *     duplicates a set (F10.1): `201` on create, `200` on replace. `as_planned: true` copies the
         *     targets into the actuals ("done as planned", one tap). Extra sets/exercises use
         *     `planned_exercise_id: null` or a `set_no` beyond the planned sets. The first log moves the
         *     session to `in_progress`. The log stores a snapshot of the targets it was performed against.
         *     After finishing, sets can be edited until `Session.editable_until` (same day + 1 day,
         *     F10.3); later returns `409 edit_window_closed`. Coaches get `403` (F16.4).
         */
        post: operations["logSet"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sessions/{session_id}/sets/{set_log_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
                set_log_id: components["schemas"]["Id"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Remove a logged set
         * @description Removes a set log (e.g. an extra set added by mistake). Same edit window as `logSet`.
         */
        delete: operations["deleteSetLog"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sessions/{session_id}/finish": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Finish the workout
         * @description Closes the session (`done`), records start/end time, computes completion (F10.2) and
         *     estimated exercise kcal (F13.2), and runs the progression engine (F11), returning the new
         *     pending suggestions. Calling it again within the edit window recomputes completion and
         *     replaces this session's pending suggestions (F10.3); after the window `409 edit_window_closed`.
         */
        post: operations["finishSession"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/meal-logs": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Check off, adjust, skip or add a meal
         * @description For a planned meal (`planned_meal_id` set): `eaten` (as planned, one tap), `adjusted`
         *     (with `items` grams) or `skipped`. Upsert keyed by (`date`, `planned_meal_id`), so
         *     repeating a check-off is idempotent (F12.3): `201` on create, `200` on replace.
         *     For off-plan food: `extra` with `planned_meal_id: null` and `items` (always creates).
         *     Returns the log plus the day's updated energy balance and nutrition completion (F12.1, F12.2).
         *     `date` cannot be in the future. Coaches get `403`.
         */
        post: operations["logMeal"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/meal-logs/{meal_log_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                meal_log_id: components["schemas"]["Id"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Undo a meal check-off or remove extra food */
        delete: operations["deleteMealLog"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/activities": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Log an extra (off-plan) activity
         * @description Off-plan timed/cardio activity on any day, including rest days (F10, F13.3). Counted in
         *     burned calories but not in training completion (F10.4). `exercise_id` must be a `timed`
         *     exercise (422 otherwise). Coaches get `403`.
         */
        post: operations["logActivity"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/activities/{activity_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                activity_id: components["schemas"]["Id"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove an extra activity */
        delete: operations["deleteActivity"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/suggestions": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * List suggestions
         * @description Newest first. Defaults to `status=pending`.
         */
        get: operations["listSuggestions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/suggestions/{suggestion_id}/accept": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                suggestion_id: components["parameters"]["SuggestionId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Accept (optionally edit-then-accept) a suggestion
         * @description Accepted values become the targets for the next sessions of that exercise (progression) or
         *     the new daily targets from today, rescaling future meal-day portions only (calories, recalc;
         *     F14.4). Optional `overrides` implement edit-then-accept; overrides must match the suggestion
         *     kind (422) and calorie overrides are never below the floor (F3.6). Already decided →
         *     `409 suggestion_already_decided`. The athlete or their linked coach can decide.
         */
        post: operations["acceptSuggestion"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/suggestions/{suggestion_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                suggestion_id: components["parameters"]["SuggestionId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reject a suggestion
         * @description Changes nothing else (F11.3). Already decided → `409 suggestion_already_decided`.
         */
        post: operations["rejectSuggestion"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/charts/session/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        /**
         * Session detail — target vs. actual per set
         * @description Uses the target snapshots stored with each set log (F15.2). Empty `exercises` when nothing was logged (F15.3).
         */
        get: operations["getSessionChart"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/charts/exercise/{exercise_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                exercise_id: components["parameters"]["ExerciseId"];
            };
            cookie?: never;
        };
        /**
         * Exercise over time
         * @description One point per finished session containing the exercise: the target at the time of that
         *     session (snapshot, F15.2), the actual top set, total volume and personal-record markers.
         */
        get: operations["getExerciseChart"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/charts/adherence": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * Daily and weekly training and nutrition completion
         * @description Range up to 371 days (heat map + weekly bars). `400 range_too_large` above that.
         */
        get: operations["getAdherenceChart"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/charts/weekly-summary": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /** Weekly summary tiles and sparklines */
        get: operations["getWeeklySummary"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/charts/body": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * Weight, 7-day average and body fat
         * @description The 7-day average uses only existing weigh-ins in each window (F14.1).
         */
        get: operations["getBodyChart"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/coach/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get my coach profile */
        get: operations["getCoachProfile"];
        /** Update my coach profile */
        put: operations["updateCoachProfile"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/coaches/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search discoverable coaches
         * @description By display name (≥ 3 characters, case-insensitive contains) or exact email. Returns only
         *     discoverable coaches, never athletes, and never exposes emails (F16.2).
         */
        get: operations["searchCoaches"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/coach-links": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List my coach links
         * @description For athletes, their links; for coaches, links with their athletes (e.g. `status=pending` for incoming requests).
         */
        get: operations["listCoachLinks"];
        put?: never;
        /**
         * Send a link request to a coach
         * @description Creates a `pending` link and notifies the coach. An athlete with an active coach or a pending
         *     request gets `409 link_exists` (F16.3). Unknown or non-discoverable coach → `404`.
         */
        post: operations["requestCoachLink"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/coach-links/{link_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                link_id: components["parameters"]["LinkId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Approve a pending link request
         * @description Only the requested coach. Link must be `pending` (409 otherwise). Notifies the athlete.
         */
        post: operations["approveCoachLink"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/coach-links/{link_id}/decline": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                link_id: components["parameters"]["LinkId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Decline a pending link request
         * @description Only the requested coach. Link must be `pending` (409 otherwise). Notifies the athlete.
         */
        post: operations["declineCoachLink"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/coach-links/{link_id}/end": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                link_id: components["parameters"]["LinkId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * End a link (either side)
         * @description Either party; an athlete may also withdraw a `pending` request. Access is revoked
         *     immediately — subsequent coach calls on that athlete return `403`. Link must be `pending` or
         *     `active` (409 otherwise). Notifies the other party.
         */
        post: operations["endCoachLink"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/coach/athletes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Client list sorted by "needs attention"
         * @description Actively linked athletes. Athletes needing attention come first (training adherence < 70 %
         *     over the last 7 days, a deload pending/applied in the last 14 days, or no logs for 3+ days),
         *     then by display name (F16).
         */
        get: operations["listCoachAthletes"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/notes": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        /**
         * List coach notes for an athlete
         * @description Visible to the athlete and their linked coach. Filter by date range, scope, session or exercise.
         */
        get: operations["listNotes"];
        put?: never;
        /**
         * Leave a note (coach)
         * @description Only an actively linked coach; athletes get `403` (notes are one-way). Notifies the athlete.
         */
        post: operations["createNote"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/athletes/{athlete_id}/notes/{note_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                note_id: components["parameters"]["NoteId"];
            };
            cookie?: never;
        };
        get?: never;
        /** Edit a note (author) */
        put: operations["updateNote"];
        post?: never;
        /** Delete a note (author) */
        delete: operations["deleteNote"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/notifications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List my notifications
         * @description Newest first, with the unread count for the bell icon.
         */
        get: operations["listNotifications"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/notifications/{notification_id}/read": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                notification_id: components["parameters"]["NotificationId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Mark one notification read
         * @description Idempotent (F17.2). Another user's notification → `403`.
         */
        post: operations["markNotificationRead"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/notifications/read-all": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Mark all my notifications read */
        post: operations["markAllNotificationsRead"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/healthz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Liveness probe
         * @description The process is up. Does not touch the database.
         */
        get: operations["getHealth"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/readyz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Readiness probe
         * @description Ready to serve traffic (database reachable, migrations applied). Used by Compose health checks and deploy smoke tests.
         */
        get: operations["getReadiness"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * Format: uuid
         * @example 3f0b6a1e-6a55-4f3c-9a43-1c2a3a4b5c6d
         */
        Id: string;
        /** @description An athlete user id or the literal `me`. */
        AthleteRef: string | "me";
        /**
         * Format: date
         * @description Calendar day in the athlete's time zone.
         * @example 2026-11-03
         */
        LocalDate: string;
        /**
         * Format: date-time
         * @description UTC instant (RFC 3339, `Z` suffix).
         * @example 2026-11-03T17:48:00Z
         */
        Timestamp: string;
        /** @enum {string} */
        Weekday: "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
        /** @description Kilocalories (estimated, rounded). */
        Kcal: number;
        /** @description Grams. */
        Grams: number;
        /** @description Completion ratio 0–1 (actual ÷ target, capped at 1). */
        Ratio: number;
        Macros: {
            kcal: components["schemas"]["Kcal"];
            protein_g: components["schemas"]["Grams"];
            carbs_g: components["schemas"]["Grams"];
            fat_g: components["schemas"]["Grams"];
        };
        /** @description Pass as `cursor` to get the next page; `null` on the last page. */
        Cursor: string | null;
        /** @description RFC 9457 problem details. */
        Problem: {
            /**
             * Format: uri-reference
             * @description `/problems/<code>`.
             */
            type: string;
            title: string;
            status: number;
            /** @description Human-readable, safe to show to the user. Never contains health data. */
            detail?: string;
            /** Format: uri-reference */
            instance?: string;
            /**
             * @description Stable machine-readable code. Known codes: `bad_request`, `invalid_range`,
             *     `range_too_large`, `not_authenticated`, `invalid_credentials`, `forbidden`,
             *     `wrong_role`, `not_linked`, `not_found`, `not_onboarded`, `email_taken`,
             *     `already_onboarded`, `plan_revision_conflict`, `day_occupied`, `session_finished`,
             *     `outside_week`, `date_in_past`,
             *     `edit_window_closed`, `suggestion_already_decided`, `link_exists`, `link_not_pending`,
             *     `validation_error`, `underage`, `disclaimer_required`, `rate_limited`,
             *     `off_unavailable`, `not_ready`. New codes may be added.
             */
            code: string;
            /** @description Field-level errors — invalid parameters (400) or invalid request-body fields (422). `field` is the parameter name or the body path. */
            errors?: components["schemas"]["FieldError"][];
            /** @description Correlates with server logs/traces. */
            request_id?: string;
        };
        FieldError: {
            /** @description Dotted path to the offending field, e.g. `profile.preferred_days`. */
            field: string;
            /** @description e.g. `required`, `out_of_range`, `too_short`, `invalid_choice`, `mismatch`. */
            code: string;
            message: string;
        };
        /** @enum {string} */
        Role: "athlete" | "coach";
        /**
         * @description Display/input preference only; the API is always metric.
         * @enum {string}
         */
        Units: "metric" | "imperial";
        /**
         * @description IANA time zone name.
         * @example Europe/Madrid
         */
        Timezone: string;
        /** Format: email */
        Email: string;
        UserRef: {
            id: components["schemas"]["Id"];
            display_name: string;
            role: components["schemas"]["Role"];
        };
        SignUpRequest: {
            email: components["schemas"]["Email"];
            /** Format: password */
            password: string;
            display_name: string;
            role: components["schemas"]["Role"];
            /**
             * Format: date
             * @description Must make the user ≥ 18 today in `timezone` (F1.1).
             */
            birth_date: string;
            units: components["schemas"]["Units"];
            timezone: components["schemas"]["Timezone"];
            /** @description Must be `true` (F1.2); the server stores the acceptance time. */
            accept_disclaimer: boolean;
        };
        LogInRequest: {
            email: components["schemas"]["Email"];
            /** Format: password */
            password: string;
        };
        User: {
            id: components["schemas"]["Id"];
            email: components["schemas"]["Email"];
            display_name: string;
            role: components["schemas"]["Role"];
            /** Format: date */
            birth_date: string;
            units: components["schemas"]["Units"];
            timezone: components["schemas"]["Timezone"];
            disclaimer_accepted_at: components["schemas"]["Timestamp"];
            created_at: components["schemas"]["Timestamp"];
        };
        Me: components["schemas"]["User"] & {
            /** @description Athletes only; always `true` for coaches. */
            onboarding_completed: boolean;
            /** @description Athletes only; the actively linked coach. */
            active_coach: components["schemas"]["UserRef"] | null;
            /** @description Athletes only; their pending link request. */
            pending_coach_link_id: components["schemas"]["Id"] | null;
            unread_notification_count: number;
        };
        UpdateMeRequest: {
            display_name?: string;
            units?: components["schemas"]["Units"];
            timezone?: components["schemas"]["Timezone"];
        };
        DeleteAccountRequest: {
            /**
             * Format: password
             * @description Current password; wrong password → `403 forbidden`.
             */
            password: string;
        };
        /**
         * @description `unspecified` = "prefer not to say" (midpoint constants).
         * @enum {string}
         */
        Sex: "male" | "female" | "unspecified";
        /** @enum {string} */
        Lifestyle: "sedentary" | "lightly_active" | "active" | "very_active";
        /** @enum {string} */
        Goal: "recomposition" | "muscle_gain" | "cutting" | "maintenance" | "wellness";
        /** @enum {string} */
        Experience: "beginner" | "intermediate" | "advanced";
        /** @enum {string} */
        TrainingEquipment: "full_gym" | "home_dumbbells" | "bodyweight_only";
        /** @enum {string} */
        Diet: "omnivore" | "vegetarian" | "vegan" | "pescatarian";
        /** @enum {string} */
        Allergen: "gluten" | "lactose" | "nuts" | "eggs" | "soy" | "shellfish" | "fish";
        AthleteProfileInput: {
            sex: components["schemas"]["Sex"];
            height_cm: number;
            lifestyle: components["schemas"]["Lifestyle"];
            goal: components["schemas"]["Goal"];
            experience: components["schemas"]["Experience"];
            days_per_week: number;
            /** @description Weekdays for sessions; length must equal `days_per_week` (F2.4). */
            preferred_days: components["schemas"]["Weekday"][];
            /** @enum {integer} */
            session_minutes: 30 | 45 | 60 | 75 | 90;
            equipment: components["schemas"]["TrainingEquipment"];
            /** @default [] */
            avoided_exercise_ids: components["schemas"]["Id"][];
            diet: components["schemas"]["Diet"];
            /** @default [] */
            allergies: components["schemas"]["Allergen"][];
            /** @enum {integer} */
            meals_per_day: 3 | 4 | 5;
        };
        AthleteProfile: components["schemas"]["AthleteProfileInput"] & {
            athlete_id: components["schemas"]["Id"];
            updated_at: components["schemas"]["Timestamp"];
        };
        /**
         * @description `entered` = known value typed in; `navy` = estimated from tape measurements (F3.3).
         * @enum {string}
         */
        BodyFatMethod: "entered" | "navy";
        /**
         * @description `body_fat_method`: `entered` requires `body_fat_pct`; `navy` requires `neck_cm` and
         *     `waist_cm` (plus `hip_cm` for female/unspecified); `skip` uses neither.
         */
        OnboardingBodyMetric: {
            weight_kg: number;
            /** @enum {string} */
            body_fat_method: "entered" | "navy" | "skip";
            body_fat_pct?: number;
            neck_cm?: components["schemas"]["MeasurementCm"];
            waist_cm?: components["schemas"]["MeasurementCm"];
            hip_cm?: components["schemas"]["MeasurementCm"];
        };
        /** @description Circumference in cm (F2.3). */
        MeasurementCm: number;
        OnboardingRequest: {
            profile: components["schemas"]["AthleteProfileInput"];
            body_metric: components["schemas"]["OnboardingBodyMetric"];
        };
        OnboardingResult: {
            profile: components["schemas"]["AthleteProfile"];
            body_metric: components["schemas"]["BodyMetric"];
            targets: components["schemas"]["Targets"];
            plan: components["schemas"]["Plan"];
        };
        ProfileUpdateResult: {
            profile: components["schemas"]["AthleteProfile"];
            targets: components["schemas"]["Targets"];
            /** @description `true` when new targets were computed from today. */
            targets_changed: boolean;
        };
        /** @description Daily targets (F3). All values are estimates. */
        Targets: {
            id: components["schemas"]["Id"];
            athlete_id: components["schemas"]["Id"];
            valid_from: components["schemas"]["LocalDate"];
            /** @constant */
            estimated: true;
            /**
             * @description Katch-McArdle if and only if a body-fat value exists (F3.2).
             * @enum {string}
             */
            bmr_formula: "katch_mcardle" | "mifflin_st_jeor";
            bmr_kcal: components["schemas"]["Kcal"];
            /** @enum {number} */
            lifestyle_factor: 1.2 | 1.3 | 1.45 | 1.6;
            baseline_kcal: components["schemas"]["Kcal"];
            planned_exercise_kcal_per_day: components["schemas"]["Kcal"];
            /** @description e.g. `-20` for cutting. */
            goal_adjustment_pct: number;
            kcal: components["schemas"]["Kcal"];
            protein_g: components["schemas"]["Grams"];
            carbs_g: components["schemas"]["Grams"];
            fat_g: components["schemas"]["Grams"];
            /**
             * @description The goal's target daily balance (eaten − burned): `kcal − (baseline_kcal +
             *     planned_exercise_kcal_per_day)`. Negative for a deficit.
             */
            target_balance_kcal: number;
            /** @description The calorie floor raised the target (F3.6); the explanation says so. */
            floor_applied: boolean;
            floor_kcal: components["schemas"]["Kcal"];
            /** @description Carbs were clamped at 0 (F3.4); explained. */
            carbs_clamped: boolean;
            /** @description Body weight the targets were computed from (kg). */
            weight_used_kg: number;
            body_fat_pct_used: number | null;
            /** @description Human-readable formulas and inputs used (F3.5). */
            explanation: string;
            /** @description Engine inputs as stored (for audit and tests). */
            inputs: {
                [key: string]: unknown;
            };
            created_at: components["schemas"]["Timestamp"];
        };
        /** @description At least one of weight, body fat or measurements. */
        BodyMetricInput: {
            date: components["schemas"]["LocalDate"];
            weight_kg?: number;
            /** @description Known value. Omit and send measurements to use the Navy method. */
            body_fat_pct?: number;
            neck_cm?: components["schemas"]["MeasurementCm"];
            waist_cm?: components["schemas"]["MeasurementCm"];
            hip_cm?: components["schemas"]["MeasurementCm"];
        };
        BodyMetric: {
            id: components["schemas"]["Id"];
            date: components["schemas"]["LocalDate"];
            weight_kg: number | null;
            /** @description Estimated when `body_fat_method` is `navy`. */
            body_fat_pct: number | null;
            body_fat_method: components["schemas"]["BodyFatMethod"] | null;
            /** @description Navy formula and inputs, when estimated. */
            body_fat_explanation: string | null;
            neck_cm: number | null;
            waist_cm: number | null;
            hip_cm: number | null;
            created_at: components["schemas"]["Timestamp"];
        };
        BodyMetricList: {
            items: components["schemas"]["BodyMetric"][];
        };
        BodyMetricResult: {
            body_metric: components["schemas"]["BodyMetric"];
            /** @description Created when weight moved ≥ 2 % from the weight used for current targets. */
            recalc_suggestion: components["schemas"]["Suggestion"] | null;
        };
        /** @enum {string} */
        MuscleGroup: "chest" | "back" | "shoulders" | "biceps" | "triceps" | "forearms" | "core" | "quads" | "hamstrings" | "glutes" | "calves" | "full_body" | "cardio";
        /** @enum {string} */
        ExerciseEquipment: "barbell" | "dumbbell" | "machine" | "cable" | "bodyweight" | "band" | "cardio_machine" | "none";
        /**
         * @description `timed` covers holds and cardio.
         * @enum {string}
         */
        ExerciseType: "strength" | "bodyweight" | "timed";
        /** @enum {string} */
        BodyRegion: "upper" | "lower" | "full" | "cardio";
        ExerciseSummary: {
            id: components["schemas"]["Id"];
            name: string;
            type: components["schemas"]["ExerciseType"];
            equipment: components["schemas"]["ExerciseEquipment"];
            muscle_group: components["schemas"]["MuscleGroup"];
        };
        /** @description Request body of `createExercise`; unknown properties are rejected. */
        ExerciseInput: components["schemas"]["ExerciseFields"];
        /** @description Properties shared by `ExerciseInput` and `Exercise`. */
        ExerciseFields: {
            name: string;
            muscle_group: components["schemas"]["MuscleGroup"];
            equipment: components["schemas"]["ExerciseEquipment"];
            type: components["schemas"]["ExerciseType"];
            met: number;
            /** @default 2.5 */
            increment_kg: number;
            region: components["schemas"]["BodyRegion"];
            /**
             * @description True for bodyweight exercises that can take extra load (belt, vest, dumbbell), so the progression engine may add weight once the rep target is reached.
             * @default false
             */
            allows_added_weight: boolean;
        };
        Exercise: components["schemas"]["ExerciseFields"] & {
            id: components["schemas"]["Id"];
            is_custom: boolean;
            /** @description Creator of a custom exercise; `null` for seed exercises. */
            owner: components["schemas"]["UserRef"] | null;
        };
        ExercisePage: {
            items: components["schemas"]["Exercise"][];
            next_cursor: components["schemas"]["Cursor"];
        };
        /** @enum {string} */
        FoodSource: "seed" | "custom" | "openfoodfacts";
        /**
         * @description Diets the food is suitable for (every food suits `omnivore`).
         * @enum {string}
         */
        DietTag: "vegetarian" | "vegan" | "pescatarian";
        Per100g: {
            kcal_per_100g: number;
            protein_g_per_100g: number;
            carbs_g_per_100g: number;
            fat_g_per_100g: number;
        };
        FoodInput: components["schemas"]["Per100g"] & {
            name: string;
            brand?: string | null;
            /** @default [] */
            diet_tags: components["schemas"]["DietTag"][];
            /** @default [] */
            allergen_tags: components["schemas"]["Allergen"][];
        };
        FoodSummary: {
            id: components["schemas"]["Id"];
            name: string;
            source: components["schemas"]["FoodSource"];
        };
        Food: components["schemas"]["FoodInput"] & {
            id: components["schemas"]["Id"];
            source: components["schemas"]["FoodSource"];
            /** @description Open Food Facts product code (unique) for imported foods. */
            external_code: string | null;
            owner: components["schemas"]["UserRef"] | null;
        };
        FoodPage: {
            items: components["schemas"]["Food"][];
            next_cursor: components["schemas"]["Cursor"];
        };
        OffProduct: components["schemas"]["Per100g"] & {
            code: string;
            name: string;
            brand: string | null;
            /** @description Local food id if already imported. */
            imported_food_id: components["schemas"]["Id"] | null;
        };
        OffSearchResult: {
            available: boolean;
            /** @enum {string|null} */
            unavailable_reason: "disabled" | "timeout" | "upstream_error" | null;
            /** @description User-facing message when unavailable. */
            message: string | null;
            items: components["schemas"]["OffProduct"][];
        };
        FoodImportRequest: {
            /** @description Open Food Facts product code from a search result. */
            code: string;
        };
        /** @enum {string} */
        MealSlot: "breakfast" | "lunch" | "dinner" | "snack";
        FoodGrams: {
            food_id: components["schemas"]["Id"];
            grams: number;
        };
        MealItem: components["schemas"]["Macros"] & {
            food: components["schemas"]["FoodSummary"];
            grams: components["schemas"]["Grams"];
        };
        MealInput: {
            name: string;
            slots: components["schemas"]["MealSlot"][];
            items: components["schemas"]["FoodGrams"][];
        };
        MealSummary: {
            id: components["schemas"]["Id"];
            name: string;
            slots: components["schemas"]["MealSlot"][];
        };
        Meal: components["schemas"]["MealSummary"] & {
            items: components["schemas"]["MealItem"][];
            totals: components["schemas"]["Macros"];
            /** @description Diets every food in the meal suits. */
            diet_tags: components["schemas"]["DietTag"][];
            /** @description Union of the foods' allergens. */
            allergen_tags: components["schemas"]["Allergen"][];
            is_custom: boolean;
            owner: components["schemas"]["UserRef"] | null;
        };
        MealPage: {
            items: components["schemas"]["Meal"][];
            next_cursor: components["schemas"]["Cursor"];
        };
        /** @enum {string} */
        PlanSource: "generated" | "custom";
        /**
         * @description Bodyweight and timed exercises progress by their type (F11) unless `manual`.
         * @enum {string}
         */
        ProgressionRule: "linear" | "double" | "manual";
        /**
         * @description Strength/bodyweight need `reps_min` (and `reps_max` ≥ `reps_min`; equal = fixed reps).
         *     Timed need `target_seconds`. `target_weight_kg: null` = calibration (choose a weight).
         *     For bodyweight exercises `target_weight_kg` is *added* weight.
         */
        PlannedExerciseInput: {
            /** @description Existing planned exercise to update; omit to add. */
            id?: components["schemas"]["Id"];
            exercise_id: components["schemas"]["Id"];
            sets: number;
            reps_min?: number | null;
            reps_max?: number | null;
            target_weight_kg?: number | null;
            target_seconds?: number | null;
            /** @default 90 */
            rest_seconds: number;
            rule: components["schemas"]["ProgressionRule"];
            /** @description Defaults to the exercise's increment. */
            increment_kg?: number;
            /** @default true */
            deload_enabled: boolean;
        };
        PlannedExercise: {
            id: components["schemas"]["Id"];
            exercise: components["schemas"]["ExerciseSummary"];
            order: number;
            sets: number;
            reps_min: number | null;
            reps_max: number | null;
            /** @description `null` until calibrated (F5.4). */
            target_weight_kg: number | null;
            target_seconds: number | null;
            rest_seconds: number;
            rule: components["schemas"]["ProgressionRule"];
            increment_kg: number;
            deload_enabled: boolean;
            /** @description Shown while `target_weight_kg` is null, e.g. "Choose a weight you can do for the target reps with 2 reps left". */
            calibration_hint: string | null;
        };
        TrainingDayInput: {
            /** @description Existing training day to update; omit to add. */
            id?: components["schemas"]["Id"];
            weekday: components["schemas"]["Weekday"];
            name: string;
            exercises: components["schemas"]["PlannedExerciseInput"][];
        };
        TrainingDay: {
            id: components["schemas"]["Id"];
            weekday: components["schemas"]["Weekday"];
            name: string;
            order: number;
            exercises: components["schemas"]["PlannedExercise"][];
            /** @description Estimated session duration (F5.1). */
            estimated_minutes: number;
            planned_kcal: components["schemas"]["Kcal"];
            /** @description Last editor when the day was edited by hand; shown as "edited by <coach name>" for coaches (F8). */
            edited_by: components["schemas"]["UserRef"] | null;
        };
        PlannedMealInput: {
            /** @description Existing planned meal to update; omit to add. */
            id?: components["schemas"]["Id"];
            slot: components["schemas"]["MealSlot"];
            meal_id: components["schemas"]["Id"];
            /** @default 1 */
            portion_factor: number;
            /** @description Optional gram overrides for this planned meal (stored as an athlete-owned copy of the meal). */
            items?: components["schemas"]["FoodGrams"][];
        };
        PlannedMeal: {
            id: components["schemas"]["Id"];
            slot: components["schemas"]["MealSlot"];
            order: number;
            meal: components["schemas"]["MealSummary"];
            portion_factor: number;
            /** @description Foods with grams already scaled by `portion_factor`. */
            items: components["schemas"]["MealItem"][];
            totals: components["schemas"]["Macros"];
        };
        MealDayInput: {
            weekday: components["schemas"]["Weekday"];
            meals: components["schemas"]["PlannedMealInput"][];
        };
        MealDay: {
            id: components["schemas"]["Id"];
            weekday: components["schemas"]["Weekday"];
            meals: components["schemas"]["PlannedMeal"][];
            totals: components["schemas"]["Macros"];
            /** @description Generator warning when targets could not be hit (F7). */
            warning: string | null;
            edited_by: components["schemas"]["UserRef"] | null;
        };
        Plan: {
            id: components["schemas"]["Id"];
            athlete_id: components["schemas"]["Id"];
            version: number;
            source: components["schemas"]["PlanSource"];
            /** @description Only the active version is editable. */
            active: boolean;
            /** @description Optimistic-concurrency counter; send it back with plan updates. */
            revision: number;
            created_by: components["schemas"]["UserRef"];
            created_at: components["schemas"]["Timestamp"];
            updated_at: components["schemas"]["Timestamp"];
            /** @description Ordered Monday → Sunday; weekdays not listed are rest days. */
            training_days: components["schemas"]["TrainingDay"][];
            meal_days: components["schemas"]["MealDay"][];
            warnings: string[];
        };
        TrainingPlanUpdate: {
            revision: number;
            training_days: components["schemas"]["TrainingDayInput"][];
        };
        MealPlanUpdate: {
            revision: number;
            meal_days: components["schemas"]["MealDayInput"][];
        };
        RegeneratePlanRequest: {
            /**
             * @default all
             * @enum {string}
             */
            scope: "all" | "training" | "meals";
        };
        PlanVersionSummary: {
            id: components["schemas"]["Id"];
            version: number;
            source: components["schemas"]["PlanSource"];
            active: boolean;
            created_by: components["schemas"]["UserRef"];
            created_at: components["schemas"]["Timestamp"];
        };
        PlanVersionList: {
            items: components["schemas"]["PlanVersionSummary"][];
        };
        /** @enum {string} */
        SessionStatus: "planned" | "in_progress" | "done" | "missed";
        /**
         * @description Strength: `reps` + `weight_kg`. Bodyweight: `reps` (+ optional added `weight_kg`).
         *     Timed: `seconds` (+ optional `distance_m`). Or `as_planned: true` / `skipped: true` alone.
         */
        SetLogInput: {
            exercise_id: components["schemas"]["Id"];
            /** @description `null` for an exercise added to the session (extra). */
            planned_exercise_id?: components["schemas"]["Id"] | null;
            set_no: number;
            /** @default false */
            as_planned: boolean;
            /** @default false */
            skipped: boolean;
            reps?: number;
            weight_kg?: number;
            seconds?: number;
            distance_m?: number;
        };
        SetLog: {
            id: components["schemas"]["Id"];
            session_id: components["schemas"]["Id"];
            planned_exercise_id: components["schemas"]["Id"] | null;
            exercise_id: components["schemas"]["Id"];
            set_no: number;
            skipped: boolean;
            /** @description Snapshot of the target at logging time. */
            target_reps: number | null;
            /** @description Snapshot. */
            target_weight_kg: number | null;
            /** @description Snapshot. */
            target_seconds: number | null;
            reps: number | null;
            weight_kg: number | null;
            seconds: number | null;
            distance_m: number | null;
            logged_at: components["schemas"]["Timestamp"];
        };
        SessionSet: {
            set_no: number;
            is_extra: boolean;
            /** @description For rep ranges, the current target within the range. */
            target_reps: number | null;
            target_weight_kg: number | null;
            target_seconds: number | null;
            log: components["schemas"]["SetLog"] | null;
        };
        SessionExercise: {
            planned_exercise_id: components["schemas"]["Id"] | null;
            exercise: components["schemas"]["ExerciseSummary"];
            order: number;
            is_extra: boolean;
            rule: components["schemas"]["ProgressionRule"] | null;
            sets: components["schemas"]["SessionSet"][];
            reps_min: number | null;
            reps_max: number | null;
            /** @description Rest-timer duration after each set. */
            rest_seconds: number;
            calibration_hint: string | null;
            completion: components["schemas"]["Ratio"] | null;
            /** @description Set when a suggestion for this exercise is pending — the session uses current targets and shows a banner (F11). */
            pending_suggestion_id: components["schemas"]["Id"] | null;
        };
        Session: {
            id: components["schemas"]["Id"];
            athlete_id: components["schemas"]["Id"];
            plan_id: components["schemas"]["Id"];
            plan_version: number;
            training_day_id: components["schemas"]["Id"];
            training_day_name: string;
            date: components["schemas"]["LocalDate"];
            /** @description Planned date before a move; `null` if not moved. */
            original_date: components["schemas"]["LocalDate"] | null;
            status: components["schemas"]["SessionStatus"];
            started_at: components["schemas"]["Timestamp"] | null;
            finished_at: components["schemas"]["Timestamp"] | null;
            /** @description End of the edit window (day after the session date, athlete's time zone, in UTC). */
            editable_until: components["schemas"]["Timestamp"];
            /** @description Σ min(actual, target) ÷ Σ target over planned working sets (F10.2); `null` until something is logged. */
            completion: components["schemas"]["Ratio"] | null;
            /** @description Estimated exercise kcal (F13.2); `null` until finished. */
            kcal: components["schemas"]["Kcal"] | null;
            /** @constant */
            estimated: true;
            exercises: components["schemas"]["SessionExercise"][];
        };
        MoveSessionRequest: {
            date: components["schemas"]["LocalDate"];
        };
        FinishSessionRequest: {
            /** @description Defaults to now. */
            finished_at?: components["schemas"]["Timestamp"];
        };
        FinishSessionResult: {
            session: components["schemas"]["Session"];
            /** @description Pending progression suggestions created by this finish. */
            suggestions: components["schemas"]["Suggestion"][];
        };
        /** @enum {string} */
        MealLogStatus: "eaten" | "adjusted" | "skipped" | "extra";
        /**
         * @description `eaten`/`skipped`: no `items` (eaten copies the planned grams). `adjusted`: `items` required.
         *     `extra`: `planned_meal_id: null`, `items` required, `slot` optional.
         */
        MealLogInput: {
            date: components["schemas"]["LocalDate"];
            planned_meal_id: components["schemas"]["Id"] | null;
            status: components["schemas"]["MealLogStatus"];
            slot?: components["schemas"]["MealSlot"];
            items?: components["schemas"]["FoodGrams"][];
        };
        MealLog: {
            id: components["schemas"]["Id"];
            date: components["schemas"]["LocalDate"];
            planned_meal_id: components["schemas"]["Id"] | null;
            status: components["schemas"]["MealLogStatus"];
            slot: components["schemas"]["MealSlot"] | null;
            /** @description Logged quantities (empty when skipped). */
            items: components["schemas"]["MealItem"][];
            totals: components["schemas"]["Macros"];
            logged_at: components["schemas"]["Timestamp"];
        };
        MealLogResult: components["schemas"]["DayEnergyUpdate"] & {
            meal_log: components["schemas"]["MealLog"];
        };
        ActivityInput: {
            date: components["schemas"]["LocalDate"];
            exercise_id: components["schemas"]["Id"];
            minutes: number;
        };
        Activity: {
            id: components["schemas"]["Id"];
            date: components["schemas"]["LocalDate"];
            exercise: components["schemas"]["ExerciseSummary"];
            minutes: number;
            kcal: components["schemas"]["Kcal"];
            /** @constant */
            estimated: true;
            created_at: components["schemas"]["Timestamp"];
        };
        ActivityResult: components["schemas"]["DayEnergyUpdate"] & {
            activity: components["schemas"]["Activity"];
        };
        DayEnergyUpdate: {
            energy: components["schemas"]["EnergyBalance"];
            nutrition_completion: components["schemas"]["Ratio"] | null;
        };
        /** @description Estimated daily energy balance (F13). All numbers are estimates. */
        EnergyBalance: {
            date: components["schemas"]["LocalDate"];
            /** @constant */
            estimated: true;
            /** @description From logged quantities only (F12.1). */
            eaten: components["schemas"]["Macros"];
            /** @description Sum of the day's planned meals. */
            planned: components["schemas"]["Macros"];
            /** @description Daily targets valid on this date (for macro progress bars). */
            target: components["schemas"]["Macros"];
            burned: components["schemas"]["Burned"];
            /** @description `eaten.kcal − burned.total_kcal`. */
            balance_kcal: number;
            /** @description The goal's target balance (see `Targets.target_balance_kcal`). */
            target_balance_kcal: number;
        };
        /** @description Baseline (BMR × lifestyle) + logged training + extra activities (F13.1), using the most recent weight on or before the date. */
        Burned: {
            total_kcal: components["schemas"]["Kcal"];
            baseline_kcal: components["schemas"]["Kcal"];
            training_kcal: components["schemas"]["Kcal"];
            activities_kcal: components["schemas"]["Kcal"];
        };
        DayMeal: {
            planned_meal: components["schemas"]["PlannedMeal"];
            /** @description `null` = not checked off yet (counts as 0 eaten). */
            log: components["schemas"]["MealLog"] | null;
        };
        /**
         * @description `rest` = no session that day (never missed). `missed` = past planned session without logs (F9.3).
         * @enum {string}
         */
        TrainingStatus: "rest" | "planned" | "in_progress" | "done" | "missed";
        DayView: {
            date: components["schemas"]["LocalDate"];
            weekday: components["schemas"]["Weekday"];
            is_today: boolean;
            training_status: components["schemas"]["TrainingStatus"];
            /** @description `null` on rest days. */
            session: components["schemas"]["Session"] | null;
            /** @description Planned meals in slot order with their check-off state. */
            meals: components["schemas"]["DayMeal"][];
            extra_meal_logs: components["schemas"]["MealLog"][];
            activities: components["schemas"]["Activity"][];
            energy: components["schemas"]["EnergyBalance"];
            training_completion: components["schemas"]["Ratio"] | null;
            /** @description Planned meals eaten or adjusted ÷ planned meals (F12.2). */
            nutrition_completion: components["schemas"]["Ratio"] | null;
            pending_suggestions: components["schemas"]["Suggestion"][];
            /** @description Same as `SuggestionList.weigh_in_hint`; set only when `date` is in the current week. */
            weigh_in_hint: components["schemas"]["WeighInHint"] | null;
            /** @description Coach notes for this day, its session and its exercises. */
            notes: components["schemas"]["Note"][];
            meal_warning: string | null;
        };
        CalendarDay: {
            date: components["schemas"]["LocalDate"];
            weekday: components["schemas"]["Weekday"];
            is_today: boolean;
            training_status: components["schemas"]["TrainingStatus"];
            /** @description `null` for rest days and for future sessions not yet materialised. */
            session_id: components["schemas"]["Id"] | null;
            training_day_name: string | null;
            /** @description The session on this day was moved here from another day. */
            moved: boolean;
            training_completion: components["schemas"]["Ratio"] | null;
            nutrition_completion: components["schemas"]["Ratio"] | null;
            planned_meal_count: number;
            eaten_meal_count: number;
            energy: components["schemas"]["EnergyBalance"];
        };
        CalendarRange: {
            from: components["schemas"]["LocalDate"];
            to: components["schemas"]["LocalDate"];
            timezone: components["schemas"]["Timezone"];
            days: components["schemas"]["CalendarDay"][];
        };
        /** @enum {string} */
        SuggestionKind: "progression" | "calories" | "recalc";
        /** @enum {string} */
        SuggestionStatus: "pending" | "accepted" | "rejected";
        /** @enum {string} */
        SuggestionRule: "linear" | "double" | "deload" | "bodyweight" | "timed" | "calibration" | "adaptive_calories" | "weight_change";
        SuggestionBase: {
            id: components["schemas"]["Id"];
            athlete_id: components["schemas"]["Id"];
            kind: components["schemas"]["SuggestionKind"];
            status: components["schemas"]["SuggestionStatus"];
            rule: components["schemas"]["SuggestionRule"];
            /** @description Human-readable rule and numbers (F11.4), e.g. "All 3 sets reached 12 reps at 40 kg → 42.5 kg × 8". */
            reason: string;
            /** @description Engine inputs as stored. */
            inputs: {
                [key: string]: unknown;
            };
            created_at: components["schemas"]["Timestamp"];
            decided_by: components["schemas"]["UserRef"] | null;
            decided_at: components["schemas"]["Timestamp"] | null;
        };
        ExerciseTargets: {
            target_weight_kg: number | null;
            reps_min: number | null;
            reps_max: number | null;
            target_seconds: number | null;
        };
        ProgressionPayload: {
            exercise: components["schemas"]["ExerciseSummary"];
            planned_exercise_id: components["schemas"]["Id"];
            source_session_id: components["schemas"]["Id"];
            current: components["schemas"]["ExerciseTargets"];
            proposed: components["schemas"]["ExerciseTargets"];
            /** @description e.g. "Ready for a harder variation" (bodyweight at top of range). */
            hint: string | null;
            /** @description Values that became the targets on accept (after edits). */
            applied: components["schemas"]["ExerciseTargets"] | null;
        };
        CaloriesPayload: {
            current_kcal: components["schemas"]["Kcal"];
            proposed_kcal: components["schemas"]["Kcal"];
            /** @enum {integer} */
            delta_kcal: -150 | 150;
            floor_applied: boolean;
            expected_weekly_change_pct: number;
            tolerance_pct: number;
            /** @description 7-day-average trend for the two complete weeks, oldest first. */
            observed_weekly_change_pct: number[];
            applied_kcal: components["schemas"]["Kcal"] | null;
        };
        RecalcPayload: {
            weight_used_kg: number;
            new_weight_kg: number;
            change_pct: number;
            current: components["schemas"]["Macros"];
            proposed: components["schemas"]["Macros"];
        };
        ProgressionSuggestion: components["schemas"]["SuggestionBase"] & {
            /** @constant */
            kind: "progression";
            payload: components["schemas"]["ProgressionPayload"];
        } & {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "progression";
        };
        CaloriesSuggestion: components["schemas"]["SuggestionBase"] & {
            /** @constant */
            kind: "calories";
            payload: components["schemas"]["CaloriesPayload"];
        } & {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "calories";
        };
        RecalcSuggestion: components["schemas"]["SuggestionBase"] & {
            /** @constant */
            kind: "recalc";
            payload: components["schemas"]["RecalcPayload"];
        } & {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "recalc";
        };
        /** @description A pending or decided suggestion; `payload` shape depends on `kind`. */
        Suggestion: components["schemas"]["ProgressionSuggestion"] | components["schemas"]["CaloriesSuggestion"] | components["schemas"]["RecalcSuggestion"];
        SuggestionList: {
            items: components["schemas"]["Suggestion"][];
            /** @description Set when this week's adaptive calorie check produced no suggestion for lack of weigh-ins (F14); otherwise `null`. */
            weigh_in_hint: components["schemas"]["WeighInHint"] | null;
        };
        /**
         * @description F14: the weekly adaptive calorie check (Mondays, over the previous two complete ISO weeks)
         *     needs ≥ 4 weigh-ins in each week. When either week has fewer, no `calories` suggestion is
         *     created and this hint is returned instead, from that Monday until the next check.
         */
        WeighInHint: {
            /** @description Safe to show to the user, e.g. "Weigh in at least 4 times a week to get an adaptive calorie suggestion." */
            message: string;
            evaluated_on: components["schemas"]["LocalDate"];
            /** @constant */
            required_per_week: 4;
            /** @description The two evaluated weeks, oldest first. */
            weeks: {
                week_start: components["schemas"]["LocalDate"];
                weigh_ins: number;
            }[];
        };
        /** @description Edit-then-accept. Progression accepts the target fields; calories accepts `kcal`; recalc accepts no overrides. */
        AcceptSuggestionRequest: {
            overrides?: {
                target_weight_kg?: number | null;
                reps_min?: number;
                reps_max?: number;
                target_seconds?: number;
                kcal?: number;
            };
        };
        /**
         * @description `met` ✅ actual ≥ target; `partial` ⚠️; `missed` no log; `extra` not planned.
         * @enum {string}
         */
        SetStatus: "met" | "partial" | "missed" | "skipped" | "extra";
        SessionChartSet: {
            set_no: number;
            status: components["schemas"]["SetStatus"];
            completion: components["schemas"]["Ratio"] | null;
            target_reps: number | null;
            target_weight_kg: number | null;
            target_seconds: number | null;
            reps: number | null;
            weight_kg: number | null;
            seconds: number | null;
        };
        SessionChartExercise: {
            exercise: components["schemas"]["ExerciseSummary"];
            is_extra: boolean;
            completion: components["schemas"]["Ratio"] | null;
            sets: components["schemas"]["SessionChartSet"][];
        };
        SessionChart: {
            session_id: components["schemas"]["Id"];
            date: components["schemas"]["LocalDate"];
            training_day_name: string;
            status: components["schemas"]["SessionStatus"];
            completion: components["schemas"]["Ratio"] | null;
            kcal: components["schemas"]["Kcal"] | null;
            exercises: components["schemas"]["SessionChartExercise"][];
        };
        ExerciseChartPoint: {
            date: components["schemas"]["LocalDate"];
            session_id: components["schemas"]["Id"];
            /** @description Target at the time of the session (snapshot). */
            target_weight_kg: number | null;
            target_reps: number | null;
            target_seconds: number | null;
            top_set_weight_kg: number | null;
            top_set_reps: number | null;
            top_set_seconds: number | null;
            /** @description Σ reps × weight over the session's sets of this exercise. */
            volume_kg: number;
            /** @description Personal record (heaviest top set so far, or longest duration for timed). */
            is_pr: boolean;
        };
        ExerciseChart: {
            exercise: components["schemas"]["ExerciseSummary"];
            /** @enum {integer} */
            weeks: 4 | 12 | 26 | 52;
            points: components["schemas"]["ExerciseChartPoint"][];
        };
        AdherenceDay: {
            date: components["schemas"]["LocalDate"];
            training_status: components["schemas"]["TrainingStatus"];
            /** @description `null` on rest days. */
            training_completion: components["schemas"]["Ratio"] | null;
            nutrition_completion: components["schemas"]["Ratio"] | null;
        };
        AdherenceWeek: {
            week_start: components["schemas"]["LocalDate"];
            sessions_planned: number;
            sessions_done: number;
            training_completion: components["schemas"]["Ratio"] | null;
            nutrition_completion: components["schemas"]["Ratio"] | null;
        };
        AdherenceChart: {
            from: components["schemas"]["LocalDate"];
            to: components["schemas"]["LocalDate"];
            days: components["schemas"]["AdherenceDay"][];
            weeks: components["schemas"]["AdherenceWeek"][];
        };
        /** @description One point of a sparkline. The unit of `value` is set by the series that contains it. */
        DatedValue: {
            date: components["schemas"]["LocalDate"];
            /**
             * @description In the unit carried by the series name: `daily_balance_kcal` → kcal,
             *     `training_completion` → ratio 0–1 (see `Ratio`), `weight_avg_kg` → kg.
             *     `null` when there is no data for that day.
             */
            value: number | null;
        };
        WeeklySummary: {
            week_start: components["schemas"]["LocalDate"];
            week_end: components["schemas"]["LocalDate"];
            /** @constant */
            estimated: true;
            sessions_planned: number;
            sessions_done: number;
            sessions_missed: number;
            avg_completion: components["schemas"]["Ratio"] | null;
            avg_daily_balance_kcal: number | null;
            target_daily_balance_kcal: number | null;
            /** @description 7-day average at the start of the week. */
            weight_avg_start_kg: number | null;
            weight_avg_end_kg: number | null;
            weight_change_kg: number | null;
            sparklines: {
                daily_balance_kcal: components["schemas"]["DatedValue"][];
                training_completion: components["schemas"]["DatedValue"][];
                weight_avg_kg: components["schemas"]["DatedValue"][];
            };
        };
        BodyChartPoint: {
            date: components["schemas"]["LocalDate"];
            weight_kg: number | null;
            /** @description Mean of existing weigh-ins in the 7 days ending on `date`. */
            weight_avg_7d_kg: number | null;
            body_fat_pct: number | null;
        };
        BodyChart: {
            /** @enum {integer} */
            weeks: 4 | 12 | 26 | 52;
            /**
             * @description Body fat values are estimates.
             * @constant
             */
            estimated: true;
            points: components["schemas"]["BodyChartPoint"][];
        };
        CoachProfileInput: {
            bio: string;
            /** @default true */
            discoverable: boolean;
        };
        CoachProfile: components["schemas"]["CoachProfileInput"] & {
            user_id: components["schemas"]["Id"];
            display_name: string;
        };
        /** @description Never contains the coach's email (F16.2). */
        CoachSearchResult: {
            id: components["schemas"]["Id"];
            display_name: string;
            bio: string;
        };
        CoachSearchResultList: {
            items: components["schemas"]["CoachSearchResult"][];
        };
        /** @enum {string} */
        CoachLinkStatus: "pending" | "active" | "declined" | "ended";
        CoachLinkRequest: {
            coach_id: components["schemas"]["Id"];
        };
        CoachLink: {
            id: components["schemas"]["Id"];
            status: components["schemas"]["CoachLinkStatus"];
            /**
             * @description `subscription` will be added with paid coaching (roadmap).
             * @enum {string}
             */
            source: "request";
            coach: components["schemas"]["UserRef"];
            athlete: components["schemas"]["UserRef"];
            created_at: components["schemas"]["Timestamp"];
            updated_at: components["schemas"]["Timestamp"];
        };
        CoachLinkList: {
            items: components["schemas"]["CoachLink"][];
        };
        /**
         * @description `low_adherence` < 70 % training adherence over 7 days; `deload` pending/applied in 14 days; `inactive` no logs for 3+ days.
         * @enum {string}
         */
        AttentionReason: "low_adherence" | "deload" | "inactive";
        CoachAthleteSummary: {
            athlete: components["schemas"]["UserRef"];
            link_id: components["schemas"]["Id"];
            linked_since: components["schemas"]["Timestamp"];
            needs_attention: boolean;
            attention_reasons: components["schemas"]["AttentionReason"][];
            training_adherence_7d: components["schemas"]["Ratio"] | null;
            last_log_date: components["schemas"]["LocalDate"] | null;
            pending_suggestion_count: number;
        };
        CoachAthleteList: {
            items: components["schemas"]["CoachAthleteSummary"][];
        };
        /** @enum {string} */
        NoteScope: "day" | "session" | "exercise";
        /** @description `day` requires `date`; `session` requires `session_id`; `exercise` requires `exercise_id` (optionally with `session_id` for context). */
        NoteInput: {
            scope: components["schemas"]["NoteScope"];
            date?: components["schemas"]["LocalDate"];
            session_id?: components["schemas"]["Id"];
            exercise_id?: components["schemas"]["Id"];
            text: string;
        };
        NoteUpdate: {
            text: string;
        };
        Note: {
            id: components["schemas"]["Id"];
            athlete_id: components["schemas"]["Id"];
            author: components["schemas"]["UserRef"];
            scope: components["schemas"]["NoteScope"];
            date: components["schemas"]["LocalDate"] | null;
            session_id: components["schemas"]["Id"] | null;
            exercise: components["schemas"]["ExerciseSummary"] | null;
            text: string;
            created_at: components["schemas"]["Timestamp"];
            updated_at: components["schemas"]["Timestamp"];
        };
        NoteList: {
            items: components["schemas"]["Note"][];
        };
        /** @enum {string} */
        NotificationType: "progression_suggestion" | "calorie_suggestion" | "recalc_prompt" | "coach_note" | "link_request_received" | "link_request_approved" | "link_request_declined" | "link_ended" | "plan_edited_by_coach";
        Notification: {
            id: components["schemas"]["Id"];
            type: components["schemas"]["NotificationType"];
            payload: components["schemas"]["NotificationPayload"];
            created_at: components["schemas"]["Timestamp"];
            read_at: components["schemas"]["Timestamp"] | null;
        };
        /** @description References for navigation; the client renders the text from `type`. Only the ids relevant to the type are present. */
        NotificationPayload: {
            athlete_id?: components["schemas"]["Id"];
            suggestion_id?: components["schemas"]["Id"];
            note_id?: components["schemas"]["Id"];
            link_id?: components["schemas"]["Id"];
            plan_id?: components["schemas"]["Id"];
            date?: components["schemas"]["LocalDate"];
            actor?: components["schemas"]["UserRef"];
        };
        NotificationPage: {
            items: components["schemas"]["Notification"][];
            unread_count: number;
            next_cursor: components["schemas"]["Cursor"];
        };
        MarkAllReadResult: {
            updated: number;
        };
        Health: {
            /** @constant */
            status: "ok";
            /**
             * @description Release the running backend belongs to: the commit SHA of its image (`APP_VERSION`, default the image tag), or `dev`/`local` outside a deploy. Deploys and the post-deploy smoke test wait until dev serves the expected SHA. Not sensitive.
             * @example 1f22fc4a9b3c5d7e8f001122334455667788aabb
             */
            version: string;
        };
        Readiness: {
            /** @enum {string} */
            status: "ok" | "unavailable";
            checks: {
                /** @enum {string} */
                database: "ok" | "fail";
                /** @enum {string} */
                migrations?: "ok" | "pending";
            };
        };
    };
    responses: {
        /** @description Unparseable JSON or an invalid query/path parameter. */
        BadRequest: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "/problems/invalid_range",
                 *       "title": "Bad request",
                 *       "status": 400,
                 *       "code": "invalid_range",
                 *       "detail": "`from` must not be after `to`."
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Missing or invalid session, or wrong credentials. */
        Unauthorized: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "/problems/not_authenticated",
                 *       "title": "Not authenticated",
                 *       "status": 401,
                 *       "code": "not_authenticated",
                 *       "detail": "Sign in to continue."
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Wrong role, not the owner, or no active coach link. */
        Forbidden: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "/problems/forbidden",
                 *       "title": "Forbidden",
                 *       "status": 403,
                 *       "code": "forbidden",
                 *       "detail": "You do not have access to this athlete."
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Resource does not exist. */
        NotFound: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "/problems/not_found",
                 *       "title": "Not found",
                 *       "status": 404,
                 *       "code": "not_found",
                 *       "detail": "Session not found."
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description The athlete has not completed onboarding, so there is no profile or targets yet (`code` = `not_onboarded`). */
        NotOnboarded: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "/problems/not_onboarded",
                 *       "title": "Not onboarded",
                 *       "status": 404,
                 *       "code": "not_onboarded",
                 *       "detail": "Complete onboarding first."
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Conflicts with the current state. */
        Conflict: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "/problems/email_taken",
                 *       "title": "Conflict",
                 *       "status": 409,
                 *       "code": "email_taken",
                 *       "detail": "An account with this email already exists."
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description The request body failed validation. */
        UnprocessableEntity: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "/problems/validation_error",
                 *       "title": "Validation failed",
                 *       "status": 422,
                 *       "code": "validation_error",
                 *       "detail": "Some values are outside the allowed range.",
                 *       "errors": [
                 *         {
                 *           "field": "body_metric.weight_kg",
                 *           "code": "out_of_range",
                 *           "message": "Weight must be between 35 and 300 kg."
                 *         }
                 *       ]
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Rate limit exceeded. */
        TooManyRequests: {
            headers: {
                "Retry-After": components["headers"]["RetryAfter"];
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "/problems/rate_limited",
                 *       "title": "Too many requests",
                 *       "status": 429,
                 *       "code": "rate_limited",
                 *       "detail": "Too many failed sign-in attempts. Try again in 15 minutes."
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description A dependency is unavailable. */
        ServiceUnavailable: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "/problems/off_unavailable",
                 *       "title": "Service unavailable",
                 *       "status": 503,
                 *       "code": "off_unavailable",
                 *       "detail": "Online food search is unavailable — use the library or create a custom food."
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
    };
    parameters: {
        /** @description Athlete user id, or `me` for the signed-in athlete. */
        AthleteId: components["schemas"]["AthleteRef"];
        SessionId: components["schemas"]["Id"];
        SuggestionId: components["schemas"]["Id"];
        LinkId: components["schemas"]["Id"];
        NoteId: components["schemas"]["Id"];
        NotificationId: components["schemas"]["Id"];
        ExerciseId: components["schemas"]["Id"];
        /**
         * @description Calendar day `YYYY-MM-DD` in the athlete's time zone, or `today`.
         * @example 2026-11-03
         */
        DayDate: string;
        /** @description First calendar day (inclusive), athlete's time zone. */
        From: string;
        /** @description Last calendar day (inclusive), athlete's time zone. */
        To: string;
        /** @description First calendar day (inclusive), athlete's time zone. */
        FromOptional: string;
        /** @description Last calendar day (inclusive), athlete's time zone. */
        ToOptional: string;
        /** @description Range ending today. */
        ChartWeeks: 4 | 12 | 26 | 52;
        /** @description Case-insensitive name search. */
        SearchQuery: string;
        /** @description Exclude items with any of these allergens (comma-separated). */
        ExcludeAllergens: components["schemas"]["Allergen"][];
        Limit: number;
        /** @description Opaque cursor from a previous page's `next_cursor`. */
        Cursor: string;
    };
    requestBodies: never;
    headers: {
        /** @description `fitwise_session=<jwt>; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400` */
        SetSessionCookie: string;
        /** @description `fitwise_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0` */
        ClearSessionCookie: string;
        /** @description Seconds until the client may retry. */
        RetryAfter: number;
    };
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    signUp: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SignUpRequest"];
            };
        };
        responses: {
            /** @description Account created; session cookie set. */
            201: {
                headers: {
                    "Set-Cookie": components["headers"]["SetSessionCookie"];
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Me"];
                };
            };
            400: components["responses"]["BadRequest"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
            429: components["responses"]["TooManyRequests"];
        };
    };
    logIn: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LogInRequest"];
            };
        };
        responses: {
            /** @description Signed in; session cookie set. */
            200: {
                headers: {
                    "Set-Cookie": components["headers"]["SetSessionCookie"];
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Me"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            422: components["responses"]["UnprocessableEntity"];
            429: components["responses"]["TooManyRequests"];
        };
    };
    logOut: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Signed out; cookie cleared. */
            204: {
                headers: {
                    "Set-Cookie": components["headers"]["ClearSessionCookie"];
                    [name: string]: unknown;
                };
                content?: never;
            };
            400: components["responses"]["BadRequest"];
        };
    };
    getMe: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The signed-in user. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Me"];
                };
            };
            401: components["responses"]["Unauthorized"];
        };
    };
    updateMe: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateMeRequest"];
            };
        };
        responses: {
            /** @description Updated user. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Me"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    deleteMe: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DeleteAccountRequest"];
            };
        };
        responses: {
            /** @description Account deleted; cookie cleared. */
            204: {
                headers: {
                    "Set-Cookie": components["headers"]["ClearSessionCookie"];
                    [name: string]: unknown;
                };
                content?: never;
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    exportMyData: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ZIP archive. */
            200: {
                headers: {
                    /** @description `attachment; filename="fitwise-export-<YYYY-MM-DD>.zip"` */
                    "Content-Disposition"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/zip": string;
                };
            };
            401: components["responses"]["Unauthorized"];
        };
    };
    completeOnboarding: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OnboardingRequest"];
            };
        };
        responses: {
            /** @description Onboarding completed. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingResult"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    getAthleteProfile: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Profile. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AthleteProfile"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotOnboarded"];
        };
    };
    updateAthleteProfile: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AthleteProfileInput"];
            };
        };
        responses: {
            /** @description Updated profile and current targets. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProfileUpdateResult"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotOnboarded"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    getTargets: {
        parameters: {
            query?: {
                /** @description Calendar day (athlete's time zone). Defaults to today. */
                date?: string;
            };
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Targets. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Targets"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotOnboarded"];
        };
    };
    listBodyMetrics: {
        parameters: {
            query?: {
                /** @description First calendar day (inclusive), athlete's time zone. */
                from?: components["parameters"]["FromOptional"];
                /** @description Last calendar day (inclusive), athlete's time zone. */
                to?: components["parameters"]["ToOptional"];
            };
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Body metrics. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BodyMetricList"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    logBodyMetric: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BodyMetricInput"];
            };
        };
        responses: {
            /** @description Existing entry for that day replaced. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BodyMetricResult"];
                };
            };
            /** @description Entry created. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BodyMetricResult"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    listExercises: {
        parameters: {
            query?: {
                /** @description Case-insensitive name search. */
                q?: components["parameters"]["SearchQuery"];
                muscle_group?: components["schemas"]["MuscleGroup"];
                equipment?: components["schemas"]["ExerciseEquipment"];
                type?: components["schemas"]["ExerciseType"];
                region?: components["schemas"]["BodyRegion"];
                limit?: components["parameters"]["Limit"];
                /** @description Opaque cursor from a previous page's `next_cursor`. */
                cursor?: components["parameters"]["Cursor"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Page of exercises, ordered by name. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExercisePage"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
        };
    };
    createExercise: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExerciseInput"];
            };
        };
        responses: {
            /** @description Created. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Exercise"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    listFoods: {
        parameters: {
            query?: {
                /** @description Case-insensitive name search. */
                q?: components["parameters"]["SearchQuery"];
                /** @description Only foods compatible with this diet. */
                diet?: components["schemas"]["Diet"];
                /** @description Exclude items with any of these allergens (comma-separated). */
                exclude_allergens?: components["parameters"]["ExcludeAllergens"];
                source?: components["schemas"]["FoodSource"];
                limit?: components["parameters"]["Limit"];
                /** @description Opaque cursor from a previous page's `next_cursor`. */
                cursor?: components["parameters"]["Cursor"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Page of foods. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FoodPage"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
        };
    };
    createFood: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FoodInput"];
            };
        };
        responses: {
            /** @description Created (source `custom`). */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Food"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    searchOpenFoodFacts: {
        parameters: {
            query: {
                q: string;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Results, or `available:false` in degraded mode. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OffSearchResult"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
        };
    };
    importOpenFoodFactsFood: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FoodImportRequest"];
            };
        };
        responses: {
            /** @description Already imported; existing food returned. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Food"];
                };
            };
            /** @description Imported. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Food"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            422: components["responses"]["UnprocessableEntity"];
            503: components["responses"]["ServiceUnavailable"];
        };
    };
    listMeals: {
        parameters: {
            query?: {
                /** @description Case-insensitive name search. */
                q?: components["parameters"]["SearchQuery"];
                slot?: components["schemas"]["MealSlot"];
                diet?: components["schemas"]["Diet"];
                /** @description Exclude items with any of these allergens (comma-separated). */
                exclude_allergens?: components["parameters"]["ExcludeAllergens"];
                limit?: components["parameters"]["Limit"];
                /** @description Opaque cursor from a previous page's `next_cursor`. */
                cursor?: components["parameters"]["Cursor"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Page of meals. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MealPage"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
        };
    };
    createMeal: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MealInput"];
            };
        };
        responses: {
            /** @description Created. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Meal"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    getActivePlan: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Active plan. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Plan"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    updateTrainingPlan: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TrainingPlanUpdate"];
            };
        };
        responses: {
            /** @description Updated plan. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Plan"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    updateMealPlan: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MealPlanUpdate"];
            };
        };
        responses: {
            /** @description Updated plan. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Plan"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    regeneratePlan: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RegeneratePlanRequest"];
            };
        };
        responses: {
            /** @description New active plan version. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Plan"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    listPlanVersions: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Versions. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlanVersionList"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    getPlanVersion: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                version: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Plan version. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Plan"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    getDay: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                /**
                 * @description Calendar day `YYYY-MM-DD` in the athlete's time zone, or `today`.
                 * @example 2026-11-03
                 */
                date: components["parameters"]["DayDate"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Day view. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DayView"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    getCalendar: {
        parameters: {
            query: {
                /** @description First calendar day (inclusive), athlete's time zone. */
                from: components["parameters"]["From"];
                /** @description Last calendar day (inclusive), athlete's time zone. */
                to: components["parameters"]["To"];
            };
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Day summaries. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CalendarRange"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    getSession: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Session. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Session"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    moveSession: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MoveSessionRequest"];
            };
        };
        responses: {
            /** @description Moved session. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Session"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    logSet: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetLogInput"];
            };
        };
        responses: {
            /** @description Existing set log replaced. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetLog"];
                };
            };
            /** @description Set log created. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetLog"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    deleteSetLog: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
                set_log_id: components["schemas"]["Id"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Deleted. */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
        };
    };
    finishSession: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["FinishSessionRequest"];
            };
        };
        responses: {
            /** @description Finished session and generated suggestions. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FinishSessionResult"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    logMeal: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MealLogInput"];
            };
        };
        responses: {
            /** @description Existing log for this planned meal replaced. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MealLogResult"];
                };
            };
            /** @description Log created. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MealLogResult"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    deleteMealLog: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                meal_log_id: components["schemas"]["Id"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Deleted; the day's updated energy balance. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DayEnergyUpdate"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    logActivity: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActivityInput"];
            };
        };
        responses: {
            /** @description Logged. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActivityResult"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    deleteActivity: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                activity_id: components["schemas"]["Id"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Deleted; the day's updated energy balance. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DayEnergyUpdate"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    listSuggestions: {
        parameters: {
            query?: {
                status?: components["schemas"]["SuggestionStatus"];
                kind?: components["schemas"]["SuggestionKind"];
            };
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Suggestions. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuggestionList"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    acceptSuggestion: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                suggestion_id: components["parameters"]["SuggestionId"];
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["AcceptSuggestionRequest"];
            };
        };
        responses: {
            /** @description Accepted suggestion. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Suggestion"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    rejectSuggestion: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                suggestion_id: components["parameters"]["SuggestionId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Rejected suggestion. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Suggestion"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
        };
    };
    getSessionChart: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                session_id: components["parameters"]["SessionId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Session chart data. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionChart"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    getExerciseChart: {
        parameters: {
            query?: {
                /** @description Range ending today. */
                weeks?: components["parameters"]["ChartWeeks"];
            };
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                exercise_id: components["parameters"]["ExerciseId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Exercise series. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExerciseChart"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    getAdherenceChart: {
        parameters: {
            query: {
                /** @description First calendar day (inclusive), athlete's time zone. */
                from: components["parameters"]["From"];
                /** @description Last calendar day (inclusive), athlete's time zone. */
                to: components["parameters"]["To"];
            };
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Adherence series. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdherenceChart"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    getWeeklySummary: {
        parameters: {
            query?: {
                /** @description Monday of the ISO week (athlete's time zone). Defaults to the current week. Must be a Monday (400). */
                week_start?: string;
            };
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Weekly summary. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WeeklySummary"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    getBodyChart: {
        parameters: {
            query?: {
                /** @description Range ending today. */
                weeks?: components["parameters"]["ChartWeeks"];
            };
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Body series. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BodyChart"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    getCoachProfile: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Coach profile. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoachProfile"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    updateCoachProfile: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CoachProfileInput"];
            };
        };
        responses: {
            /** @description Updated coach profile. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoachProfile"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    searchCoaches: {
        parameters: {
            query: {
                q: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Matching coaches (max 20). */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoachSearchResultList"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    listCoachLinks: {
        parameters: {
            query?: {
                status?: components["schemas"]["CoachLinkStatus"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Links, newest first. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoachLinkList"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
        };
    };
    requestCoachLink: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CoachLinkRequest"];
            };
        };
        responses: {
            /** @description Pending link. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoachLink"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    approveCoachLink: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                link_id: components["parameters"]["LinkId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Active link. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoachLink"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
        };
    };
    declineCoachLink: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                link_id: components["parameters"]["LinkId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Declined link. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoachLink"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
        };
    };
    endCoachLink: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                link_id: components["parameters"]["LinkId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Ended link. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoachLink"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
        };
    };
    listCoachAthletes: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Athlete summaries. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CoachAthleteList"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    listNotes: {
        parameters: {
            query?: {
                /** @description First calendar day (inclusive), athlete's time zone. */
                from?: components["parameters"]["FromOptional"];
                /** @description Last calendar day (inclusive), athlete's time zone. */
                to?: components["parameters"]["ToOptional"];
                scope?: components["schemas"]["NoteScope"];
                session_id?: components["schemas"]["Id"];
                exercise_id?: components["schemas"]["Id"];
            };
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Notes, newest first. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NoteList"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    createNote: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NoteInput"];
            };
        };
        responses: {
            /** @description Created. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Note"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    updateNote: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                note_id: components["parameters"]["NoteId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NoteUpdate"];
            };
        };
        responses: {
            /** @description Updated. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Note"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            422: components["responses"]["UnprocessableEntity"];
        };
    };
    deleteNote: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Athlete user id, or `me` for the signed-in athlete. */
                athlete_id: components["parameters"]["AthleteId"];
                note_id: components["parameters"]["NoteId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Deleted. */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    listNotifications: {
        parameters: {
            query?: {
                unread_only?: boolean;
                limit?: components["parameters"]["Limit"];
                /** @description Opaque cursor from a previous page's `next_cursor`. */
                cursor?: components["parameters"]["Cursor"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Page of notifications. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificationPage"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
        };
    };
    markNotificationRead: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                notification_id: components["parameters"]["NotificationId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Notification. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Notification"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    markAllNotificationsRead: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Number of notifications marked read. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarkAllReadResult"];
                };
            };
            401: components["responses"]["Unauthorized"];
        };
    };
    getHealth: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Alive. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Health"];
                };
            };
            400: components["responses"]["BadRequest"];
        };
    };
    getReadiness: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Ready. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Readiness"];
                };
            };
            400: components["responses"]["BadRequest"];
            /** @description Not ready. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Readiness"];
                };
            };
        };
    };
}
