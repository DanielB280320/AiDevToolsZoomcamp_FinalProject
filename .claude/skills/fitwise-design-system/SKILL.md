---
name: fitwise-design-system
description: FitWise's own visual design system - the colour, type and spacing tokens in frontend/src/index.css and the shipped component patterns (buttons, form fields, tabs, badges, cards, KPI tiles, rings, charts). Use whenever you build, change or review any UI in frontend/, so new screens match the ones already shipped. Complements the generic frontend-design skill; where the two disagree, this one wins.
---

# FitWise design system

FitWise already has a look. This skill records it so that every new screen reads as part of the same app. The generic `frontend-design` skill is about finding a direction; here the direction is already chosen, so use that skill only for craft inside these rules (hierarchy, composition, copy), not to pick new palettes or fonts.

The look in one sentence: **light, calm and modern** - a near-white page, white cards with a hairline border, soft 8 px controls, condensed semibold headings, one green for actions and one yellow used sparingly, and short, quiet feedback when you press things (D111).

Source of truth is the code: tokens in `frontend/src/index.css` (`@theme`), patterns in `frontend/src/components/` and `frontend/src/features/`. If this skill and the code disagree, the code is right and this skill needs fixing in the same PR.

Before building a component, open [components.md](components.md): it lists every shipped pattern with its file and exact classes. Reuse or import the existing one before writing a new one.

## Tokens

Use only these, through their Tailwind utilities (`bg-page`, `text-iron`, `border-line`, `rounded-card`, ...). Never use Tailwind's default palette (`gray-500`, `green-600`, ...) or a raw hex in a class.

| Token | Value | Role |
|---|---|---|
| `page` | `#f8f9f8` | Page background; the soft fill of a figure well, of a quiet callout and of the sticky save bar |
| `card` | `#ffffff` | Card surface and the fill of form controls |
| `chalk` | `#f2f4f1` | Text on dark (iron, spruce, alert) fills only; never a surface |
| `iron` | `#1c2530` | Text, the header, selected segmented choices, note side lines |
| `spruce` | `#1e6b57` | **Actions**: primary buttons, links, the active tab, focus ring. Also "done / good" |
| `spruce-dark` | `#154d3f` | Hover and press of spruce fills only |
| `plate` | `#e8b931` | **Accent, rare**: brand bar under the header, PR badge, "partial" status, small tags, one highlight callout. Always with `text-iron`, never as text on white |
| `slate` | `#56616c` | Secondary text: hints, captions, KPI labels, neutral deltas; hover border of a control |
| `line` | `#d3d9d4` | Hairlines: card border, row dividers, tab-strip rule, hover fill of outline buttons, empty ring track, chart grid |
| `edge` | `#868f98` | 1 px border of inputs and secondary buttons (3.3:1 on white, so the control is identifiable) |
| `alert` | `#a3321f` | Errors, destructive, "missed", a figure that got worse |
| `rounded-card` | 12 px | Cards and wells |
| `rounded-control` | 8 px | Buttons, inputs, selects, segmented choices, set cards |
| `--duration-press` / `--duration-open` / `--duration-fill` | 150 / 200 / 400 ms | Press and hover; sections opening; rings and bars filling. `--ease-soft` is the one easing |

New values go in `@theme` in `frontend/src/index.css`; components never hold their own.

**Type.** `font-sans` (Barlow) for everything read; `font-display` (Barlow Condensed) for the wordmark, headings, tab labels and big figures - always `font-semibold`, never `font-bold`. Sizes come only from the 1.25 scale, never `text-sm`/`text-lg`/`text-xl`:

| Class | Use |
|---|---|
| `text-step--1` | Hints, captions, errors under a field, badges, KPI labels |
| `text-step-0` | Body (the default; rarely written out) |
| `text-step-1` | `h2` section headings, `h3`, tab labels, ring centre, loading text, lead figure in a row |
| `text-step-2` | A compact page `h1` (a range title) or a large figure |
| `text-step-3` | Wordmark; a compact page `h1`; KPI figures |
| `text-step-4` | Page `h1` |
| `text-step-5` | Landing/auth hero only, from `sm:` up |

Emphasis in body text is `font-semibold`. Small all-caps labels are `text-step--1 font-semibold uppercase tracking-wide text-slate` (KPI titles only).

**Shape and depth.** Structure comes from white cards on the near-white page, separated by space, not from heavy rules or shadows:

- A **card** is `CARD` (components/card.tsx): `rounded-card border border-line bg-card p-4`. Every titled section and every standalone chart block is one. No shadow, no gradient, no blur; the only shadow is on a layer that floats over content (the Month day popover, `shadow-lg`).
- **No card inside a card.** A section card holds its figures and charts directly. A KPI figure inside a section is a `TILE` (a soft `bg-page` well, no border); a repeated item inside a section (an exercise or meal inside a plan-day card) is an `ITEM` (hairline outline only). A figure, chart or row that is *not* inside a section card is a card itself.
- **Callouts are not cards.** A note, a decision prompt or an error keeps a 3 px coloured side line (`border-l-[3px] pl-3`): `border-iron` note, `border-alert` error, `border-plate` highlight, `border-line` quiet aside. Text or `role="alert"` says what it is, not the colour.
- Rows in a list are separated by `border-b border-line` / `divide-y divide-line`; rows that open something are `CARD_LINK` cards.
- Tab strips sit on a 1 px `line` rule (see Tabs in components.md). `border-b-4 border-plate` under the header is the only heavy rule left.
- `rounded-control` for buttons and fields, `rounded-card` for cards, `rounded-sm` for badges and tags; `rounded-full` only for a true circle or a thin progress bar.

**Spacing.** Tailwind's scale, in a small set: `mt-1`/`mt-2` inside a group, `mt-3`/`mt-4` between groups, `mt-6`/`mt-8` between cards and sections; `gap-2`/`gap-3` in rows of controls, `gap-4` in grids. Card padding is 16 px (`p-4`). Content column `max-w-[40rem]` (`38rem` for a lone message); long prose `max-w-[52ch]`-`[60ch]`. The shell supplies page padding (`AppShell`: `max-w-5xl px-4 py-8 sm:px-8 sm:py-12`); pages don't add their own.

**Motion.** Short and quiet, and always off under `prefers-reduced-motion` (the global rule in `index.css` zeroes CSS transitions and animations; `useChartAnimation` in `lib/motion.ts` turns Recharts off):

- Press and hover: every `button` gets a colour/border transition and a 0.98 scale while pressed (global base rule); links that act as controls (tabs, month cells) add the `press` utility; a card or row that opens something uses `CARD_LINK` (`card-link`: border darkens on hover, fill on press). Cards that do nothing on click show no hover.
- Opening: `Collapse` (components/card.tsx) or the `expand-in` utility fades and grows content in over 200 ms. The content is in the DOM and focusable at once, `hidden` only while closed; closing is instant. Keep `aria-expanded`/`aria-controls`.
- Filling: `ProgressRing` fills from empty in 400 ms; a bar uses `transition-[width]`; a set check pops in with `check-pop`.
- Charts: every series spreads `{...anim}` from `useChartAnimation()` (400 ms, ease-out).
- Never delay content, focus or a test on an animation, and never animate layout beyond the above.

## Rules that hold on every screen

1. **Touch targets**: interactive elements are `min-h-12` (48 px); `min-h-11` (44 px) is the floor, for inline links and header items.
2. **One primary action per view** is a spruce fill. Everything else is an outline button or a spruce underlined link. Destructive actions are the outline button with `border-alert text-alert` plus a confirmation, not a red fill. An outline (secondary) button and every input have a 1 px `border-edge` that darkens to `slate` on hover.
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

Changing or removing an existing token, font or pattern is a redesign, not an addition: stop and ask the owner (D111 was one).

## Checklist (engineer self-check, QA review)

For a PR that adds or changes UI in `frontend/`, check the diff:

- [ ] Colours: only theme tokens; no Tailwind default palette, no raw hex outside `index.css` / `CHART_COLORS`; `chalk` only as text on dark fills.
- [ ] Type: only `text-step-*`; headings use `font-display font-semibold` at the level's size (`h2` is `text-step-1`).
- [ ] Surfaces: titled sections and standalone chart blocks use `CARD`; no card inside a card (`TILE` / `ITEM` inside); callouts keep a 3 px side line and are not cards; no `border-t-4` rules, no shadow except a floating layer, no gradient or `dark:`.
- [ ] Shape: `rounded-card` / `rounded-control` / `rounded-sm` (`rounded-full` only for circles and progress bars); inputs and secondary buttons use `border border-edge`.
- [ ] Buttons, fields, tabs, badges, callouts match components.md (shared component or constant reused where one exists).
- [ ] Motion: press feedback is inherited (buttons) or uses `press` / `CARD_LINK`; openings use `Collapse`; chart series spread `useChartAnimation()`; nothing waits on an animation; reduced motion switches it all off.
- [ ] At most one spruce-filled primary action per view; plate only in its listed roles.
- [ ] Targets at least 44 px; state not carried by colour alone; focus ring intact.
- [ ] No sideways scroll at 360 px; reads well at 1280 px (screenshots of both in the PR).
- [ ] Anything new in the system is in `index.css`/a shared component, documented here, and named in the PR description.

QA: a miss on this checklist is reported under `Notes:` in the verdict; it fails the PR only when it also breaks an acceptance criterion or a spec rule (§6.1: no sideways scroll at 360 px, labelled inputs, keyboard navigation, AA contrast; state by colour alone where an AC says so).
