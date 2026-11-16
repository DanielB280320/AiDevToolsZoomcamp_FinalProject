# FitWise component catalogue

Every shipped visual pattern, where it lives and its exact classes. Paths are relative to `frontend/src/`. Import the component or constant when one exists; copy the class string only where the pattern is still written inline. When you add a pattern, add it here in the same PR.

## Contents

- [Page frame](#page-frame)
- [Headings](#headings)
- [Buttons and links](#buttons-and-links)
- [Form fields](#form-fields)
- [Compact editor rows](#compact-editor-rows)
- [Tabs](#tabs)
- [Badges and tags](#badges-and-tags)
- [Sections, cards and callouts](#sections-cards-and-callouts)
- [Loading, error and empty states](#loading-error-and-empty-states)
- [KPI tiles, rings and deltas](#kpi-tiles-rings-and-deltas)
- [Charts](#charts)
- [Icons and logo](#icons-and-logo)

## Page frame

| Pattern | Where | Classes / notes |
|---|---|---|
| Shell | `components/AppShell.tsx` | Skip link, `Header`, `<main>` with `mx-auto w-full max-w-5xl px-4 py-8 sm:px-8 sm:py-12`, `Footer` (disclaimer). Every route renders inside it. |
| Header | `components/Header.tsx` | `border-b-4 border-plate bg-iron text-chalk` (unchanged by D111); wordmark `font-display text-step-3 font-semibold leading-none tracking-tight`. On iron, an outline button is `border-2 border-chalk/60 text-chalk hover:border-chalk`, and an error message is `text-plate` (alert red fails contrast on iron). |
| Auth pages | `components/AuthLayout.tsx` | Sign-in / sign-up frame. |
| Page column | `pages/*.tsx` | `<article className="max-w-[40rem]">`; add `min-w-0` when it holds charts; `max-w-[38rem]` for a lone message (not found, load error). |
| Sticky action bar | `features/plan/SaveBar.tsx` | `sticky bottom-0 mt-6 border-t border-line bg-page py-3`, buttons in `flex flex-wrap gap-3`, status lines under them. |

## Headings

| Level | Classes |
|---|---|
| Page `h1` | `font-display text-step-4 font-semibold` (hero: add `text-balance sm:text-step-5`; compact page: `text-step-3`) |
| Section `h2` | `font-display text-step-1 font-semibold` (with an icon: `flex items-center gap-2 ...`); the first thing inside a `CARD` |
| Sub-section `h3` | `font-display text-step-1 font-semibold`, usually `mt-4` or `mt-6` |
| Row title | `font-semibold` (plain Barlow) |
| KPI label | `text-step--1 font-semibold uppercase tracking-wide text-slate` |
| Page or section description (the sentence under an `h1`/`h2`) | `text-step--1 text-slate`, `mt-2` under an `h1` and `mt-1` under an `h2`; the same on every tab |

An `h1` focused after navigation gets `tabIndex={-1}` and `focus:outline-none`.

## Buttons and links

Constants are exported from `features/plan/fields.tsx`; use them rather than retyping.

| Pattern | Where | Classes |
|---|---|---|
| Primary | `PRIMARY` | `min-h-12 rounded-control bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark active:bg-spruce-dark disabled:opacity-60` |
| Outline (secondary) | `BUTTON` | `min-h-12 rounded-control border border-edge px-4 font-semibold hover:border-slate hover:bg-line disabled:opacity-60` |
| Icon / square | `ICON_BUTTON` | `min-h-12 min-w-12 rounded-control border border-edge px-2 font-semibold hover:border-slate hover:bg-line disabled:opacity-40` |
| Form submit | `SubmitButton` in `components/form/fields.tsx` | Primary at `px-6 py-3`, `w-full sm:w-auto`; while pending it stays focusable: `aria-disabled` with `aria-disabled:cursor-progress aria-disabled:opacity-75` |
| Destructive | `features/plan/VersionHistory.tsx` | `${BUTTON} border-alert text-alert`, behind a confirmation |
| Text button | inline | `min-h-12 rounded-control px-4 font-semibold text-spruce underline underline-offset-4` |
| Link | inline | `font-semibold text-spruce underline underline-offset-4`; standalone: add `inline-flex min-h-11 items-center` |
| Link on iron | `Header` | `font-semibold text-chalk underline-offset-4 hover:underline` |

Press feedback is global: every `button` transitions colour and border in 150 ms and scales to 0.98 while pressed (not for `disabled` / `aria-disabled`), so buttons need no extra classes. Rows of buttons: `flex flex-wrap gap-3`. Toggle buttons carry `aria-pressed`; a pressed "done" check is a spruce fill with a `✓` (see `features/workout/ExerciseCard.tsx`).

## Form fields

Use the components; don't hand-roll a label + input.

| Pattern | Where | Notes |
|---|---|---|
| `TextField`, `SelectField`, `ChoiceField`, `CheckboxField`, `FormAlert`, `SubmitButton` | `components/form/fields.tsx` | Auth, account and onboarding forms. |
| Wizard fields | `components/form/wizardFields.tsx` | Onboarding steps. |
| `TextInput` and friends, `FieldError` | `features/plan/fields.tsx` | Editors with many compact fields (`inputMode` decimal/numeric). Add `compact` for a field in a row (small slate label, 44 px control), `labelHidden` when the row already names it, `describedBy` for a shared hint line (see Compact editor rows). |

Anatomy, top to bottom: label `block font-semibold` → hint `mt-1 text-step--1 text-slate` → control → error `mt-1.5 text-step--1 font-semibold text-alert`. Hint and error ids go in `aria-describedby`; an invalid control has `aria-invalid`.

- Control: `mt-1.5 block min-h-12 w-full rounded-control border border-edge bg-card px-3 py-2 text-step-0 text-iron hover:border-slate aria-[invalid=true]:border-alert` (focus: the global spruce outline)
- Narrow inline number input (in a row of controls): `min-h-12 w-28 rounded-control border border-edge hover:border-slate px-2` with a `text-step--1 font-semibold` label above.
- Segmented choice (`ChoiceField`): native radios hidden with `sr-only` inside labels in `grid grid-cols-2 gap-2`; each label `min-h-14 rounded-control border bg-card px-3 py-2` with the control border, selected `has-[:checked]:border-iron has-[:checked]:bg-iron has-[:checked]:text-chalk`; option title `font-display text-step-1 font-semibold leading-tight`, detail `text-step--1 opacity-80`.
- Checkbox: `size-6 accent-spruce`, label beside it in `flex items-start gap-3`.
- Form-level error (`FormAlert`): `role="alert"`, `border-l-[3px] border-alert bg-card px-4 py-3 font-semibold text-alert`, focused when shown.

## Compact editor rows

The plan editors (D112) keep each item to one or two lines. Three shipped patterns:

- **Compact exercise field row** (`ExerciseCard` in `features/plan/TrainingEditor.tsx`): the item (`ITEM`) is the name (`font-display text-step-1 font-semibold`), the type in `text-step--1 text-slate` and the move/remove `ICON_BUTTON`s, then `grid grid-cols-2 gap-2 sm:grid-cols-4` of `TextInput compact` fields (sets, reps min, reps max, weight, rest; a timed exercise has sets, seconds, rest). Two rows of two on a 360 px phone, one row from `sm:`. A `compact` field is a `text-step--1 font-semibold text-slate` label over a `min-h-11` control with `px-2` (`TextInput`/`SelectInput` in `features/plan/fields.tsx`). Hints that apply to every item are **one** `text-step--1 text-slate` line at the top of the group (`data-testid="day-hint"`), referenced from each field with `describedBy={hintId}`; do not repeat them under each item. A per-item warning (out of range) stays under the item's row as an `border-l-[3px] border-alert pl-3` callout with `role="status"`.
- **One-row meal with disclosure** (`MealEditor`): the item is `flex flex-wrap items-end gap-x-2 gap-y-2` with the name (`basis-full` on a phone, flexible from `sm:`), a `compact` slot select (`w-32 sm:w-36`), a `compact` portion input (`w-24`) and the remove `ICON_BUTTON`. Below it, a disclosure button `min-h-11 text-step--1 font-semibold text-spruce` with a `ChevronDownIcon` (rotates when open) and the summary ("N foods, X kcal"), with `aria-expanded` and `aria-controls` pointing at a `Collapse`. In the `Collapse`: one `border-b border-line py-1` row per food (name, then a `compact labelHidden` grams input `w-28` plus a "g" suffix; the label stays the accessible name) and then the secondary actions (Replace, Swap) as `BUTTON`s. Open it by script when something inside has an error, so the error is never hidden.
- **Thin search result row** (`RESULT_ROW` in `components/card.tsx`): `flex min-h-11 w-full items-center justify-between gap-3 border-b border-line px-1 py-1 text-left hover:bg-line`, the name `font-semibold` left (`min-w-0 break-words`), a `text-step--1 text-slate` detail (kcal per 100 g, kcal, type) right (`shrink-0`). The `ul` has no gap and no border boxes. Used by the exercise, meal, food and Open Food Facts searches. The button keeps its `aria-label` where it had one.

## Tabs

| Pattern | Where | Classes |
|---|---|---|
| Main tab strip | `features/calendar/CalendarNav.tsx` (same shape: `features/coach/ClientNav.tsx`, `CoachNav.tsx`, the Plan editor's tablist) | `<nav aria-label>` → `ul` with `TAB_STRIP` (`flex border-b border-line`, plus `no-scrollbar overflow-x-auto` where it scrolls) → `li` `flex-1 shrink-0` → `NavLink` with `tabClass(isActive, extra)` from `components/tabs.ts`: `press flex min-h-12 items-center justify-center border-b-[3px] font-display text-step-1 font-semibold no-underline`; active `border-spruce text-spruce`, rest `border-transparent text-iron hover:bg-line/50 hover:text-spruce`. Padding comes through `extra` (`px-3`). `useActiveTabInView` (`lib/`) keeps the active tab visible on a phone. |
| Period / range switch | `features/charts/PeriodSelector.tsx`, `features/calendar/RangeControls.tsx` | Preset buttons plus previous/next; reuse for any date-range control. The previous/next pair is `‹ label ›`: two step buttons (`min-h-11 min-w-11 rounded-control border border-edge hover:border-slate font-semibold hover:bg-line disabled:cursor-not-allowed disabled:opacity-40`, glyphs from `charts.period.prevGlyph`/`nextGlyph`, each with an `aria-label`) around a `min-w-0 flex-1 text-center font-semibold` label with `aria-live="polite"`; a step that cannot move is `disabled`. The month pager of the adherence heat map (D113) is the same pair. |

The active tab is spruce text with a 3 px spruce underline (not colour alone: the underline is the second cue), and `NavLink` sets `aria-current` (a button tablist sets `aria-selected`).

## Badges and tags

All badges: `inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-step--1 font-semibold leading-none`, a glyph with `aria-hidden` plus a text label (`sr-only` in compact mode).

| Pattern | Where | Fill |
|---|---|---|
| `StatusBadge` | `features/calendar/StatusBadge.tsx` | done `✓` `bg-spruce text-chalk` · partial `◐` `bg-plate text-iron` · missed `✕` `bg-alert text-chalk` · rest `–` `bg-line text-iron` · planned `○` `border border-iron bg-card text-iron` |
| `PrBadge` | `components/PrBadge.tsx` | `★` `bg-plate text-iron` |
| Inline tag (e.g. "estimated") | `features/charts/PeriodOverview.tsx` | `rounded-sm bg-plate px-1.5 text-iron normal-case` |
| Unread count | `features/notifications/Bell.tsx` | The only round badge: `min-w-5 rounded-full bg-plate px-1 text-center text-step--1 font-semibold leading-5 text-iron`. |

A new status reuses one of the five fills with its own glyph; don't introduce a sixth colour for it.

## Sections, cards and callouts

All from `components/card.tsx` unless noted.

| Pattern | Classes | Used for |
|---|---|---|
| `CARD` | `min-w-0 rounded-card border border-line bg-card shadow-card p-4`; add `mt-6`/`mt-8` between cards (`scroll-mt-4` if linked to) | Each titled section on a page (Today, Week days, Month, Body, Plan, Progress, Coach, Workout, Notifications, Account) and each standalone chart block |
| `CARD_FLUSH` | `CARD` without padding | A card that sets its own padding (the Month grid at `p-2`, a notification row) |
| `CARD_LINK` | `CARD_FLUSH card-link` | A card or row that opens something (notification, client row on a phone): border darkens on hover, fill on press. Never on a card that does nothing |
| `CARD` emphasised | `CARD` plus `border-spruce!` | The block holding the view's main result or action (finish summary, finish button) |
| `TILE` | `min-w-0 rounded-card bg-well p-3` | A KPI figure inside a section card (`Kpi`, `Tile`): a soft well, no border |
| `ITEM` | `rounded-control border border-line p-3` | A repeated item inside a section card (a training exercise or meal inside a plan-day card, the duplicate-day panel); the plan day itself and a plan version are `CARD`s |
| List row | `border-b border-line py-3`, or `divide-y divide-line` on the list | Suggestions, checklist, meal rows |
| Note callout | `border-l-[3px] border-iron pl-3` (prose: `max-w-[52ch]`) | Coach note, explanation, reason |
| Highlight callout | `border-l-[3px] border-plate pl-3`, or `border-l-[3px] border-plate bg-card p-4` when it must stand out | A prompt asking for a decision (recalculation, banner) |
| Error callout | `border-l-[3px] border-alert pl-3` + `role="alert"`, text `text-alert` or `font-semibold` | Inline failure |
| Quiet aside | `border-l-[3px] border-line pl-4` | Disclaimer, secondary info |
| `RESULT_ROW` | see Compact editor rows | A thin search-result button row |
| `Collapse` | `<Collapse id open>` renders `div#id[hidden]` with the `expand-in` animation | Expanding content (exercise sets, plan day, the foods of a meal, progression help); content stays in the DOM |

Rule: **no card inside a card**. Decide per screen which is the card: a titled section is a `CARD` and what it holds is a `TILE`, an `ITEM`, a row or a chart; a figure or chart that sits outside any section card is a `CARD`. Callouts are never cards, and `bg-card` on a callout is only for one that must stand off the page.

A suggestion row (`features/suggestions/SuggestionCard.tsx`) is the model for "item + reason + actions": title `font-semibold`, the change `font-display text-step-1 font-semibold`, the engine's reason `text-step--1 text-slate`, then `flex flex-wrap gap-3` with one `PRIMARY` (accept) and `BUTTON`s (edit, reject).

## Loading, error and empty states

| Pattern | Where | Notes |
|---|---|---|
| `QueryState` | `features/calendar/QueryState.tsx` | Loading: `<p role="status" className="text-step-1 text-slate">`. Error: `role="alert"` `max-w-[38rem] border-l-[3px] border-alert pl-4`, message `text-step-1 font-semibold`, retry = primary button `mt-4`. |
| `ChartState` | `features/charts/ChartState.tsx` | Same for chart blocks, plus the empty state. |
| Empty / no data | inline | A sentence in `text-slate` saying what will appear and what to do; a figure with no data shows `—`, never `0`. |
| Pending button | | Label changes ("Saving…"), `aria-disabled` or `disabled`; no spinner. |

No skeletons or spinners anywhere; keep it that way.

## KPI tiles, rings and deltas

| Pattern | Where | Notes |
|---|---|---|
| KPI tile | `features/charts/PeriodOverview.tsx` (also `features/calendar/MonthKpis.tsx`, `ProgressKpis.tsx`, `EnergySummary.tsx`) | `<section className={TILE}>`: KPI label, big value in `font-display font-semibold`, hint `mt-1 text-step--1 text-slate`, then a `DeltaLine`. Grid: `grid min-w-0 grid-cols-1 gap-4 min-[420px]:grid-cols-2` (rings: `min-[420px]:grid-cols-3`). |
| `ProgressRing` | `features/charts/ProgressRing.tsx` | 80 px, `stroke-line` track, `stroke-spruce` value that fills from empty in 400 ms (state flipped on the next frame, CSS `transition-[stroke-dashoffset]`), centre `font-display text-step-1 font-semibold`; `role="progressbar"`; `null` draws an empty ring with `—`. Sits in `flex min-w-0 items-start gap-3` beside its label and caption. |
| `DeltaLine` | `features/charts/DeltaLine.tsx` | Arrow glyph + screen-reader direction + signed value. `tone="higherIsBetter"`: up `text-spruce`, down `text-alert`; `tone="neutral"` (weight, energy): always `text-slate`. No data: slate sentence. |

| Progress bar | `features/calendar/EnergySummary.tsx`, `TodayView.tsx` | Track `h-2 overflow-hidden rounded-full bg-line`, fill in spruce with `transition-[width]`, with the figures in text beside it. |
| Floating popover | `features/calendar/MonthView.tsx`, day detail in `features/charts/AdherenceView.tsx` (D113) | `absolute z-20 rounded-control border border-line bg-card p-2 text-left text-step--1 text-iron shadow-lg` (`w-48`, or `w-max max-w-[13rem]`), `pointer-events-none`, shown on hover and on keyboard focus (and on tap where the cell is a button); `role="tooltip"` linked with `aria-describedby`, Escape closes it. First line `font-semibold` (the date), then one line per figure. In a grid it opens inwards on the outer columns (`left-0` / `right-0`, centred otherwise) so it never causes sideways scroll at 360 px. `shadow-lg` is the only shadow besides the cards' `shadow-card`. |

Figures that change in place or line up in columns use `tabular-nums` (rest timer, set values). Energy figures carry the "estimated" tag or wording.

## Charts

Recharts, always inside `ChartBox` (`features/charts/ChartBox.tsx`: `role="img"` + `aria-label`, fixed height 220, `min-w-0` so it shrinks at 360 px), with an accessible data table or summary alongside (see `PeriodTimelines.tsx`), and the whole block inside a `CARD` (usually its section's card).

Colours only from `CHART_COLORS` in `features/charts/chartData.ts` (hex copies of the theme tokens; keep both in step):

| Key | Token | Meaning |
|---|---|---|
| `actual` | spruce | What the user did: main line (`strokeWidth={2}`) or bar |
| `target` | slate | The plan/target: dashed line `strokeDasharray="5 4"`, no dots; or the paired bar |
| `accent` | plate | Second measured series (dashed to differ by more than colour) or a highlighted point (PR dot, with an `ink` stroke) |
| `ink` | iron | Third series or an overlay line on bars |
| `alert` | alert | A series whose rise is unwelcome (body fat) |
| `line` | line | `CartesianGrid` (`vertical={false}`) |

Every chart has a `<ChartTooltip label={...} unit={...} />` (`features/charts/ChartTooltip.tsx`): hovering or tapping a point shows the x label, then each series' name and value with its unit, in a small white box with a hairline border (ink text, never the series colour; `bars` shades the hovered column instead of a guide line; leave `unit` out when the series names carry their units). Every `YAxis` on the left uses `width="auto"` and the chart's left margin is `0`, so labels such as `100%` or `102.5 kg` are never cut off; don't set a fixed width or a negative margin. Every series spreads `{...anim}` from `useChartAnimation()` (`lib/motion.ts`: 400 ms ease-out, off under `prefers-reduced-motion`) and has a translated `name`; two lines on one chart differ by dash or dots as well as colour; a `<Legend />` is shown when there is more than one series; axis ticks use the default text colour and `minTickGap`. Units (kg/lb, %, kcal) appear on the axis or in the series name.

**Calendar heat map** (`AdherenceView`, D113): a centred block (`mx-auto max-w-[28rem]`, legend included) holding a `grid grid-cols-7 gap-1` `ol` that starts on Monday. Each day is a `button` (`aspect-square w-full rounded-sm text-step--1 font-semibold`, day number inside, the value in its `aria-label`): a value is a spruce fill whose opacity grows with the percentage (`text-chalk` from 60 %, below that `text-iron` with a `border-alert/40` outline); no value (rest, not yet due, no plan) is `border border-dashed border-line bg-page text-slate` with no number, never 0 %. A period over 31 days shows one calendar month at a time with the `‹ Month Year ›` step pair above the grid (see Period / range switch), opening on the latest month; up to 31 days it is one block without the pair. Never let a calendar grow with the period: page it. Pointing at, focusing or tapping a day opens the Floating popover with the date and both metrics. A legend line (`text-step--1 text-slate`) explains the dashed days.

## Icons and logo

- `components/icons.tsx`: `FlameIcon` (energy), `UtensilsIcon` (meals), `DumbbellIcon` (training), `LightbulbIcon` (suggestions), `CheckCircleIcon`, `NoteIcon`, `ScaleIcon` (body), `TargetIcon`, `ChevronDownIcon` (disclosure; the one thing that may rotate), `HistoryIcon`, `ClipboardIcon`, `PlusCircleIcon`, `ChecklistIcon`. Line icons, 24 px (`size-6`), `stroke="currentColor"`, `aria-hidden`; always beside a text label. Add a new icon to that file in the same style (24 px viewBox, 2 px round stroke).
- `components/Logo.tsx`: `LogoMark`, used in the header and as the favicon. Don't redraw or recolour it.
