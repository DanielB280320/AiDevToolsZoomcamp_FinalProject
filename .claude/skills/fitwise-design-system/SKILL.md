---
name: fitwise-design-system
description: FitWise's own visual design system - the colour, type and spacing tokens in frontend/src/index.css and the shipped component patterns (buttons, form fields, tabs, badges, cards, KPI tiles, rings, charts). Use whenever you build, change or review any UI in frontend/, so new screens match the ones already shipped. Complements the generic frontend-design skill; where the two disagree, this one wins.
---

# FitWise design system

FitWise already has a look. This skill records it so that every new screen reads as part of the same app. The generic `frontend-design` skill is about finding a direction; here the direction is already chosen, so use that skill only for craft inside these rules (hierarchy, composition, copy), not to pick new palettes or fonts.

The look in one sentence: **a gym floor on chalk paper** - flat, squared-off, heavy rules instead of boxes and shadows, condensed signage headings, one green for actions and one yellow used sparingly.

Source of truth is the code: tokens in `frontend/src/index.css` (`@theme`), patterns in `frontend/src/components/` and `frontend/src/features/`. If this skill and the code disagree, the code is right and this skill needs fixing in the same PR.

Before building a component, open [components.md](components.md): it lists every shipped pattern with its file and exact classes. Reuse or import the existing one before writing a new one.

## Tokens

Use only these, through their Tailwind utilities (`bg-chalk`, `text-iron`, `border-line`, ...). Never use Tailwind's default palette (`gray-500`, `green-600`, ...) or a raw hex in a class.

| Token | Hex | Role |
|---|---|---|
| `chalk` | `#f2f4f1` | Page background; text on dark (iron, spruce, alert) fills |
| `iron` | `#1c2530` | Text, heavy rules, the header, selected/active fills |
| `spruce` | `#1e6b57` | **Actions**: primary buttons, links, focus ring. Also "done / good" |
| `spruce-dark` | `#154d3f` | Hover of spruce fills only |
| `plate` | `#e8b931` | **Accent, rare**: brand bar under the header, PR badge, "partial" status, small tags, one highlight callout. Always with `text-iron`, never as text on chalk |
| `slate` | `#56616c` | Secondary text: hints, captions, KPI labels, neutral deltas |
| `line` | `#d3d9d4` | Hairline dividers, hover fill of outline buttons, empty ring track, chart grid |
| `alert` | `#a3321f` | Errors, destructive, "missed", a figure that got worse |
| `white` | | Only the fill of form controls and of a callout that must stand off the chalk page |

Opacity variants of `iron` are part of the system for quiet borders: `border-iron/35` (control at rest), `/60` (control hover, icon button), `/30` (card outline), `/20`.

**Type.** `font-sans` (Barlow) for everything read; `font-display` (Barlow Condensed) for the wordmark, headings, tab labels and big figures - always with `font-bold` (rarely `font-semibold`). Sizes come only from the 1.25 scale, never `text-sm`/`text-lg`/`text-xl`:

| Class | Use |
|---|---|
| `text-step--1` | Hints, captions, errors under a field, badges, KPI labels |
| `text-step-0` | Body (the default; rarely written out) |
| `text-step-1` | `h3`, tab labels, ring centre, loading text, lead figure in a row |
| `text-step-2` | `h2` section headings |
| `text-step-3` | Wordmark; a compact page `h1` |
| `text-step-4` | Page `h1` |
| `text-step-5` | Landing/auth hero only, from `sm:` up |

Emphasis in body text is `font-semibold`. Small all-caps labels are `text-step--1 font-semibold uppercase tracking-wide text-slate` (KPI tile titles only).

**Shape and depth.** `rounded-md` for buttons and controls, `rounded-sm` for badges and tags, nothing rounder (`rounded-full` only for a true circle or a thin progress bar). No gradients, no blur, and no shadows except on a layer that floats over content (the Month day popover, `shadow-lg`). Structure comes from borders:

- `border-t-4 border-iron pt-3` opens a section or a KPI tile; `border-b-4` closes the tab strip and the header (`border-plate` there).
- `border-l-4 pl-3`/`pl-4` marks a callout: `border-iron` note, `border-alert` error, `border-plate` highlight, `border-line` quiet aside.
- `border-2 border-iron/30 p-3` is the only "card" outline.
- `border-b border-line` / `divide-y divide-line` separates list rows.

**Spacing.** Tailwind's scale, in a small set: `mt-1`/`mt-2` inside a group, `mt-3`/`mt-4` between groups, `mt-6`/`mt-8` between sections; `gap-2`/`gap-3` in rows of controls, `gap-4` in grids. Content column `max-w-[40rem]` (`38rem` for a lone message); long prose `max-w-[52ch]`-`[60ch]`. The shell supplies page padding (`AppShell`: `max-w-5xl px-4 py-8 sm:px-8 sm:py-12`); pages don't add their own.

**Motion.** Almost none: state changes are instant, charts use `isAnimationActive={false}`. A small `transition-transform` (a chevron turning) is the ceiling. `prefers-reduced-motion` is already handled globally in `index.css`.

## Rules that hold on every screen

1. **Touch targets**: interactive elements are `min-h-12` (48 px); `min-h-11` (44 px) is the floor, for inline links and header items.
2. **One primary action per view** is a spruce fill. Everything else is an outline button or a spruce underlined link. Destructive actions are the outline button with `border-alert text-alert` plus a confirmation, not a red fill.
3. **Never colour alone.** Every state has a glyph or text as well (`StatusBadge`, `DeltaLine`, `PrBadge` show how), plus the matching ARIA state.
4. **Focus** is the global `:focus-visible` 3 px spruce outline. Don't restyle it; only remove it (`focus:outline-none`) on an element focused by script, such as a heading after navigation.
5. **No sideways page scroll at 360 px.** Put `min-w-0` on flex/grid children that hold text or charts, `break-words` on user text, `flex-wrap` on rows of controls. The only sideways scroller is a tab strip (`no-scrollbar overflow-x-auto`).
6. **Mobile first**: write the 360 px layout, then add `sm:` for wider. Check 360 px and 1280 px.
7. **Light only.** There are no dark tokens; don't add `dark:` variants or a theme switch unless an issue asks for dark mode.
8. **Icons** come from `components/icons.tsx` (24 px line icons, `currentColor`, decorative, always beside a text label). Status and direction marks are text glyphs (`✓ ◐ ✕ – ○ ★`). No emoji, no icon library.
9. **Charts** take colours from `CHART_COLORS` (`features/charts/chartData.ts`) and sit in `ChartBox`; spruce = actual, slate = target (dashed for a line), plate = second series/highlight, iron = third. See components.md.
10. **Copy** is plain and short, sentence case, in `src/i18n/en.json` (lint rejects literal JSX text).

## When the system doesn't have what you need

Reuse first: most "new" needs are an existing pattern with different content. If nothing fits:

1. Add the token to `@theme` in `frontend/src/index.css` (and to `CHART_COLORS` if a chart uses it), or build the pattern as a shared component/constant rather than a one-off class string. A new colour needs WCAG AA contrast (4.5:1 for text) on the surfaces it will sit on, and a role that no existing token covers.
2. Update this skill in the same PR: the token table above, or a new entry in [components.md](components.md).
3. Say so in the PR description under a "Design system" line: what was added and why nothing existing fit.

Changing or removing an existing token, font or pattern is a redesign, not an addition: stop and ask the owner.

## Checklist (engineer self-check, QA review)

For a PR that adds or changes UI in `frontend/`, check the diff:

- [ ] Colours: only theme tokens; no Tailwind default palette, no raw hex outside `index.css` / `CHART_COLORS`.
- [ ] Type: only `text-step-*`; headings use `font-display font-bold` at the level's size.
- [ ] Shape: `rounded-md` / `rounded-sm` (`rounded-full` only for circles and progress bars); no gradient or `dark:`; no shadow on anything that is not a floating layer.
- [ ] Buttons, fields, tabs, badges, callouts match components.md (shared component or constant reused where one exists).
- [ ] At most one spruce-filled primary action per view; plate only in its listed roles.
- [ ] Targets at least 44 px; state not carried by colour alone; focus ring intact.
- [ ] No sideways scroll at 360 px; reads well at 1280 px (screenshots of both in the PR).
- [ ] Anything new in the system is in `index.css`/a shared component, documented here, and named in the PR description.

QA: a miss on this checklist is reported under `Notes:` in the verdict; it fails the PR only when it also breaks an acceptance criterion or a spec rule (§6.1: no sideways scroll at 360 px, labelled inputs, keyboard navigation, AA contrast; state by colour alone where an AC says so).
