# FitWise component catalogue

Every shipped visual pattern, where it lives and its exact classes. Paths are relative to `frontend/src/`. Import the component or constant when one exists; copy the class string only where the pattern is still written inline. When you add a pattern, add it here in the same PR.

## Contents

- [Page frame](#page-frame)
- [Headings](#headings)
- [Buttons and links](#buttons-and-links)
- [Form fields](#form-fields)
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
| Header | `components/Header.tsx` | `border-b-4 border-plate bg-iron text-chalk`; wordmark `font-display text-step-3 font-bold leading-none tracking-tight`. On iron, an outline button is `border-2 border-chalk/60 text-chalk hover:border-chalk`, and an error message is `text-plate` (alert red fails contrast on iron). |
| Auth pages | `components/AuthLayout.tsx` | Sign-in / sign-up frame. |
| Page column | `pages/*.tsx` | `<article className="max-w-[40rem]">`; add `min-w-0` when it holds charts; `max-w-[38rem]` for a lone message (not found, load error). |
| Sticky action bar | `features/plan/SaveBar.tsx` | `sticky bottom-0 mt-6 border-t-4 border-iron bg-chalk py-3`, buttons in `flex flex-wrap gap-3`, status lines under them. |

## Headings

| Level | Classes |
|---|---|
| Page `h1` | `font-display text-step-4 font-bold` (hero: add `text-balance sm:text-step-5`; compact page: `text-step-3`) |
| Section `h2` | `font-display text-step-2 font-bold` (with an icon: `flex items-center gap-2 ...`) |
| Sub-section `h3` | `font-display text-step-1 font-bold`, usually `mt-4` or `mt-6` |
| Row title | `font-semibold` (plain Barlow) |
| KPI label | `text-step--1 font-semibold uppercase tracking-wide text-slate` |

An `h1` focused after navigation gets `tabIndex={-1}` and `focus:outline-none`.

## Buttons and links

Constants are exported from `features/plan/fields.tsx`; use them rather than retyping.

| Pattern | Where | Classes |
|---|---|---|
| Primary | `PRIMARY` | `min-h-12 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark disabled:opacity-60` |
| Outline (secondary) | `BUTTON` | `min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line disabled:opacity-60` |
| Icon / square | `ICON_BUTTON` | `min-h-12 min-w-12 rounded-md border-2 border-iron/60 px-2 font-semibold hover:bg-line disabled:opacity-40` |
| Form submit | `SubmitButton` in `components/form/fields.tsx` | Primary at `px-6 py-3`, `w-full sm:w-auto`; while pending it stays focusable: `aria-disabled` with `aria-disabled:cursor-progress aria-disabled:opacity-75` |
| Destructive | `features/plan/VersionHistory.tsx` | `${BUTTON} border-alert text-alert`, behind a confirmation |
| Text button | inline | `min-h-12 rounded-md px-4 font-semibold text-spruce underline underline-offset-4` |
| Link | inline | `font-semibold text-spruce underline underline-offset-4`; standalone: add `inline-flex min-h-11 items-center` |
| Link on iron | `Header` | `font-semibold text-chalk underline-offset-4 hover:underline` |

Rows of buttons: `flex flex-wrap gap-3`. Toggle buttons carry `aria-pressed`; a pressed "done" check is a spruce fill with a `✓` (see `features/workout/ExerciseCard.tsx`).

## Form fields

Use the components; don't hand-roll a label + input.

| Pattern | Where | Notes |
|---|---|---|
| `TextField`, `SelectField`, `ChoiceField`, `CheckboxField`, `FormAlert`, `SubmitButton` | `components/form/fields.tsx` | Auth, account and onboarding forms. |
| Wizard fields | `components/form/wizardFields.tsx` | Onboarding steps. |
| `TextInput` and friends, `FieldError` | `features/plan/fields.tsx` | Editors with many compact fields (`inputMode` decimal/numeric). |

Anatomy, top to bottom: label `block font-semibold` → hint `mt-1 text-step--1 text-slate` → control → error `mt-1.5 text-step--1 font-semibold text-alert`. Hint and error ids go in `aria-describedby`; an invalid control has `aria-invalid`.

- Control: `mt-1.5 block min-h-12 w-full rounded-md border-2 border-iron/35 bg-white px-3 py-2 text-step-0 text-iron hover:border-iron/60 aria-[invalid=true]:border-alert`
- Narrow inline number input (in a row of controls): `min-h-12 w-28 rounded-md border-2 border-iron px-2` with a `text-step--1 font-semibold` label above.
- Segmented choice (`ChoiceField`): native radios hidden with `sr-only` inside labels in `grid grid-cols-2 gap-2`; each label `min-h-14 rounded-md border-2 bg-white px-3 py-2`, selected `has-[:checked]:border-iron has-[:checked]:bg-iron has-[:checked]:text-chalk`; option title `font-display text-step-1 font-semibold leading-tight`, detail `text-step--1 opacity-80`.
- Checkbox: `size-6 accent-spruce`, label beside it in `flex items-start gap-3`.
- Form-level error (`FormAlert`): `role="alert"`, `border-l-4 border-alert bg-white px-4 py-3 font-semibold text-alert`, focused when shown.

## Tabs

| Pattern | Where | Classes |
|---|---|---|
| Main tab strip | `features/calendar/CalendarNav.tsx` (same shape: `features/coach/ClientNav.tsx`, `CoachNav.tsx`) | `<nav aria-label>` → `ul` `no-scrollbar flex overflow-x-auto border-b-4 border-iron` → `li` `flex-1 shrink-0` → `NavLink` `flex min-h-12 items-center justify-center whitespace-nowrap px-3 font-display text-step-1 font-bold no-underline`; active `bg-iron text-chalk`, rest `text-iron hover:bg-line`. `useActiveTabInView` (`lib/`) keeps the active tab visible on a phone. |
| Period / range switch | `features/charts/PeriodSelector.tsx`, `features/calendar/RangeControls.tsx` | Preset buttons plus previous/next; reuse for any date-range control. |

The active state is a fill (iron), not a colour change of the text alone, and `NavLink` sets `aria-current`.

## Badges and tags

All badges: `inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-step--1 font-semibold leading-none`, a glyph with `aria-hidden` plus a text label (`sr-only` in compact mode).

| Pattern | Where | Fill |
|---|---|---|
| `StatusBadge` | `features/calendar/StatusBadge.tsx` | done `✓` `bg-spruce text-chalk` · partial `◐` `bg-plate text-iron` · missed `✕` `bg-alert text-chalk` · rest `–` `bg-line text-iron` · planned `○` `border-2 border-iron bg-chalk text-iron` |
| `PrBadge` | `components/PrBadge.tsx` | `★` `bg-plate text-iron` |
| Inline tag (e.g. "estimated") | `features/charts/PeriodOverview.tsx` | `rounded-sm bg-plate px-1.5 text-iron normal-case` |
| Unread count | `features/notifications/Bell.tsx` | The only round badge: `min-w-5 rounded-full bg-plate px-1 text-center text-step--1 font-bold leading-5 text-iron`. |

A new status reuses one of the five fills with its own glyph; don't introduce a sixth colour for it.

## Sections, cards and callouts

| Pattern | Classes | Used for |
|---|---|---|
| Section opener | `mt-8 border-t-4 border-iron pt-3` (`mt-6` when tighter; `scroll-mt-4` if linked to) | Each titled block on a page |
| Emphasised section | `border-t-4 border-spruce pt-3` | The block holding the view's main action or result (finish summary) |
| Card | `border-2 border-iron/30 p-3` (`border-iron` when selected/open) | A set, a day, an item you act on |
| List row | `border-b border-line py-3`, or `divide-y divide-line` on the list | Suggestions, inbox, clients |
| Note callout | `border-l-4 border-iron pl-3` (prose: `max-w-[52ch]`) | Coach note, explanation, reason |
| Highlight callout | `border-l-4 border-plate pl-3`, or `border-l-4 border-plate bg-white p-4` when it must stand out | A prompt asking for a decision (recalculation, banner) |
| Error callout | `border-l-4 border-alert pl-3` + `role="alert"`, text `text-alert` or `font-semibold` | Inline failure |
| Quiet aside | `border-l-4 border-line pl-4` | Disclaimer, secondary info |

No filled panels: a block is separated by a rule and space. `bg-white` appears only on controls, `FormAlert` and the highlight callout.

A suggestion row (`features/suggestions/SuggestionCard.tsx`) is the model for "item + reason + actions": title `font-semibold`, the change `font-display text-step-1 font-bold`, the engine's reason `text-step--1 text-slate`, then `flex flex-wrap gap-3` with one `PRIMARY` (accept) and `BUTTON`s (edit, reject).

## Loading, error and empty states

| Pattern | Where | Notes |
|---|---|---|
| `QueryState` | `features/calendar/QueryState.tsx` | Loading: `<p role="status" className="text-step-1 text-slate">`. Error: `role="alert"` `max-w-[38rem] border-l-4 border-alert pl-4`, message `text-step-1 font-semibold`, retry = primary button `mt-4`. |
| `ChartState` | `features/charts/ChartState.tsx` | Same for chart blocks, plus the empty state. |
| Empty / no data | inline | A sentence in `text-slate` saying what will appear and what to do; a figure with no data shows `—`, never `0`. |
| Pending button | | Label changes ("Saving…"), `aria-disabled` or `disabled`; no spinner. |

No skeletons or spinners anywhere; keep it that way.

## KPI tiles, rings and deltas

| Pattern | Where | Notes |
|---|---|---|
| KPI tile | `features/charts/PeriodOverview.tsx` (also `features/calendar/MonthKpis.tsx`, `ProgressKpis.tsx`, `EnergySummary.tsx`) | `<section className="min-w-0 border-t-4 border-iron bg-chalk pt-2">`: KPI label, big value in `font-display font-bold`, hint `mt-1 text-step--1 text-slate`, then a `DeltaLine`. Grid: `grid min-w-0 grid-cols-1 gap-4 min-[420px]:grid-cols-2` (rings: `min-[420px]:grid-cols-3`). |
| `ProgressRing` | `features/charts/ProgressRing.tsx` | 80 px, `stroke-line` track, `stroke-spruce` value, centre `font-display text-step-1 font-bold`; `role="progressbar"`; `null` draws an empty ring with `—`. Sits in `flex min-w-0 items-start gap-3` beside its label and caption. |
| `DeltaLine` | `features/charts/DeltaLine.tsx` | Arrow glyph + screen-reader direction + signed value. `tone="higherIsBetter"`: up `text-spruce`, down `text-alert`; `tone="neutral"` (weight, energy): always `text-slate`. No data: slate sentence. |

| Progress bar | `features/calendar/EnergySummary.tsx`, `TodayView.tsx` | Track `h-2 overflow-hidden rounded-full bg-line`, fill in spruce, with the figures in text beside it. |
| Floating popover | `features/calendar/MonthView.tsx` | `absolute z-20 w-48 rounded-md border-2 border-iron bg-chalk p-2 text-step--1 shadow-lg`, shown on hover and on keyboard focus. The only shadow in the app. |

Figures that change in place or line up in columns use `tabular-nums` (rest timer, set values). Energy figures carry the "estimated" tag or wording.

## Charts

Recharts, always inside `ChartBox` (`features/charts/ChartBox.tsx`: `role="img"` + `aria-label`, fixed height 220, `min-w-0` so it shrinks at 360 px), with an accessible data table or summary alongside (see `PeriodTimelines.tsx`).

Colours only from `CHART_COLORS` in `features/charts/chartData.ts` (hex copies of the theme tokens; keep both in step):

| Key | Token | Meaning |
|---|---|---|
| `actual` | spruce | What the user did: main line (`strokeWidth={2}`) or bar |
| `target` | slate | The plan/target: dashed line `strokeDasharray="5 4"`, no dots; or the paired bar |
| `accent` | plate | Second measured series (dashed to differ by more than colour) or a highlighted point (PR dot, with an `ink` stroke) |
| `ink` | iron | Third series or an overlay line on bars |
| `alert` | alert | A series whose rise is unwelcome (body fat) |
| `line` | line | `CartesianGrid` (`vertical={false}`) |

Every series has `isAnimationActive={false}` and a translated `name`; two lines on one chart differ by dash or dots as well as colour; a `<Legend />` is shown when there is more than one series; axis ticks use the default text colour and `minTickGap`. Units (kg/lb, %, kcal) appear on the axis or in the series name.

## Icons and logo

- `components/icons.tsx`: `FlameIcon` (energy), `UtensilsIcon` (meals), `DumbbellIcon` (training), `LightbulbIcon` (suggestions), `CheckCircleIcon`, `NoteIcon`, `ScaleIcon` (body), `TargetIcon`, `ChevronDownIcon` (disclosure; the one thing that may rotate), `HistoryIcon`, `ClipboardIcon`, `PlusCircleIcon`, `ChecklistIcon`. Line icons, 24 px (`size-6`), `stroke="currentColor"`, `aria-hidden`; always beside a text label. Add a new icon to that file in the same style (24 px viewBox, 2 px round stroke).
- `components/Logo.tsx`: `LogoMark`, used in the header and as the favicon. Don't redraw or recolour it.
