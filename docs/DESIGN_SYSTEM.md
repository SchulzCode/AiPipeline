# AIpipe Design System

This documents the design system established for the v1.1 Control Center UI/UX
overhaul (GitHub issue #21). It exists so future pages stay consistent with
Overview, Tasks, the project workspace, task detail, project settings, and
diagnostics rather than each page reinventing tone/spacing/motion choices.

## Design intent

AIpipe is a **multi-project autonomous-engineering operations dashboard**, not
a marketing site or a generic admin-panel template. Every choice below is
made against that brief: dense-but-readable information, restrained color use
tied to real operational meaning, no decorative motion, no fabricated
progress or data the backend doesn't actually know.

Three design skills were used to arrive at and audit these choices:

- **UI/UX Pro Max** — used via its `search.py` tool to generate a design-system
  starting point for an "internal ops / devtool" product (`--design-system`),
  and targeted `--domain ux`/`--domain color` queries for status-badge and
  dark-console-palette guidance. Its first suggestion (a green-on-black "HUD /
  Sci-Fi FUI" style) was explicitly rejected — the issue bans fake-terminal
  styling — in favor of its "Developer Tool / IDE" and "Accessible & Ethical"
  matches, which anchor the navy/slate + single-accent palette below.
- **Emil Kowalski's design-engineering skill** — governs every motion decision:
  custom easing curves, sub-300ms UI transitions, `scale(0.97)` press
  feedback, `transform`/`opacity`-only animation, and the
  `prefers-reduced-motion` policy.
- **Taste Skill, `redesign-existing-projects` variant** — used instead of the
  default `design-taste-frontend` variant, which explicitly excludes
  dashboards/data tables/multi-step product UI ("not for dashboards, not data
  tables, not multi-step product UI") and is tuned for landing pages and
  portfolios. `redesign-existing-projects` is written for exactly this
  situation — auditing and upgrading an existing app in place — and its
  audit checklist (generic card look, one-accent-color discipline, tinted
  shadows, real hover/press/loading/empty states, "dashboard always has a
  left sidebar → try top navigation instead") drove the top-nav layout,
  status-tone consolidation, and component-state work below.

## Color

Dark-only (`color-scheme: dark` in `app/globals.css`), one cool-neutral
(blue-tinted slate) surface family, one product accent, and one hue per
operational status. **Never mix accent hues** — no purple/blue "AI gradient"
aesthetic, no gradients as decoration.

| Token | Value | Use |
|---|---|---|
| `--color-canvas` | `#090b10` | page background |
| `--color-surface` | `#10141d` | default card/panel background |
| `--color-surface-raised` | `#171d29` | hover/active surface, raised state |
| `--color-surface-sunken` | `#0b0e14` | inset wells: form inputs, code blocks |
| `--color-border` / `--color-border-strong` | `#232a39` / `#333d54` | hairline dividers / emphasized borders |
| `--color-fg` | `#eef1f6` | primary text |
| `--color-fg-muted` | `#98a2b8` | secondary text, descriptions |
| `--color-fg-faint` | `#78839a` | tertiary text: timestamps, IDs, captions |
| `--color-accent` | `#4c8dff` | text/links/icons/focus rings/borders on dark surfaces |
| `--color-accent-hover` | `#6fa2ff` | hover state for accent-colored *text* |
| `--color-accent-solid` / `--color-accent-solid-hover` | `#2f6fe0` / `#2557c9` | solid fill for primary buttons and active pills |
| `--color-accent-fg` | `#ffffff` | text on `accent-solid` |

**`accent` vs `accent-solid` is not arbitrary.** A single hex value cannot
simultaneously (a) read clearly as small text on `canvas` and (b) host white
button text at AA contrast — the luminance ranges that satisfy each
constraint don't overlap (see the contrast table below). `accent` is for
color used *as* foreground content (links, icons, the focus ring);
`accent-solid` is for color used *as a filled background* with text on top.
Picking one or the other correctly is the difference between an accessible
button and a 2.8:1-contrast one — the latter shipped in the first pass of
this work and was caught by the audit (see below).

### Status semantics

One hue per operational state, reused identically for project status, task
status, activity-feed status, and discovery-candidate status — this
replaces four independent, drifting color-tone tables that existed before
this overhaul (`StatusBadge`'s `Set`s, `TONES` in the task page,
`STATUS_TONE` in the discovery panel, and an inline stage-tone ladder).
`web/lib/status.ts` is now the single source of truth; see `TONE_META` there
for the exact Tailwind classes.

| Tone | Color | Meaning |
|---|---|---|
| `active` | `#4c8dff` (= accent) | currently running: routing through post-merge, project `BUSY` |
| `done` | `#34d399` | `DONE`, successful check/review result |
| `queued` | `#8b93a7` | `QUEUED`, waiting on a worker |
| `attention` | `#f5a623` | `BLOCKED`, `NEEDS_INPUT` — needs a human decision |
| `failed` | `#f2495c` | `FAILED`, failing check/CI result |
| `idle` | `#7b8499` | `CANCELLED`, project `IDLE`, discovery `duplicate` |

Status is **never conveyed by color alone**: every badge pairs the tone color
with a text label (and, for `active`, a pulsing dot) — see `TaskStatusBadge`/
`ProjectStatusBadge`/`ActivityStatusBadge`/`DiscoveryStatusBadge` in
`web/components/ui/badge.tsx`.

### Contrast (WCAG AA, verified)

Every text/background pairing below is >= 4.5:1 (normal text). This table is
what the final audit pass computed and fixed — two pairings failed in the
first implementation pass and are called out.

| Pairing | Ratio | Note |
|---|---|---|
| `fg` on `canvas` | 17.4:1 | |
| `fg` on `surface` | 16.3:1 | |
| `fg-muted` on `canvas`/`surface` | 7.7:1 / 7.2:1 | |
| `fg-faint` on `canvas`/`surface` | 5.2:1 / 4.8:1 | **fixed**: was `#616c82` at 3.5–3.7:1 (fails AA for normal text) |
| `accent` on `canvas` | 6.2:1 | text/link use |
| white on `accent-solid` | 4.7:1 | **fixed**: white on the original single `accent` (`#4c8dff`) was 2.8–3.2:1 (fails AA) — this is why `accent-solid` exists as a separate, darker token |
| `status-idle` on `canvas` | 5.3:1 | **fixed**: was `#616c82` at 3.7:1 |
| `status-{done,attention,failed,active,queued}` on `canvas` | 5.5–10.2:1 | |

## Typography

`Geist` (sans) / `Geist Mono` (monospace), loaded via `next/font/google` in
`app/layout.tsx` — self-hosted, no runtime Google Fonts request. Chosen over
the LLM-default `Inter` for a devtool with actual character, and over a
serif (never appropriate for an ops console). `font-variant-numeric:
tabular-nums` is set globally on `body` so stat tiles, token counts, and
durations don't jitter as digits change.

- Page titles: `text-xl font-semibold tracking-tight` (not oversized —
  this is a data tool, not a marketing hero).
- Section headings: `text-sm font-semibold`.
- Body/labels: `text-sm` / `text-xs`, `fg-muted` for secondary copy.
- Numeric/technical content (token counts, event kinds, YAML/log text,
  branch names): `font-mono`.

## Spacing, radius, layout

- One border-radius scale: `--radius-sm` (6px, inputs) / `--radius-md`
  (10px, cards) / `--radius-lg` (14px, unused today, reserved for large
  surfaces) / `--radius-pill` (badges, filter tabs). No mixed/arbitrary
  radii.
- Page container: `max-w-[1400px]` (dashboard density — wider than a
  marketing `max-w-7xl`, since this product needs to show more at once).
- Cards (`components/ui/card.tsx`) use a border + flat `surface` fill, not
  border+shadow+white-card — shadows are reserved for nothing at all in
  this dark palette (a shadow reads as *more* surface in a near-black UI,
  not depth; borders do the separating work instead).

## Components

- **Card / CardHeader / CardBody** (`components/ui/card.tsx`) — the one
  surface primitive; every panel across every page is built from it.
- **Badges** (`components/ui/badge.tsx`) — status pills, always
  dot+label, never bare color.
- **Button** (`components/ui/button.tsx`) — four variants (`primary`,
  `secondary`, `ghost`, `danger`); every variant has an explicit
  `active:scale-[0.98]` press state (Emil Kowalski: buttons must feel
  responsive to press) and a `transition-[transform,background-color,
  border-color] duration-150` — never `transition: all`.
- **EmptyState / Skeleton / ErrorBanner** (`components/ui/*`) — the
  shared loading/empty/error primitives that replace five independent
  hand-rolled copies of "Loading…" text, ad hoc red boxes, and no-skeleton
  blank-flash loading that existed before this overhaul.
- **PipelineStages** (`components/pipeline-stages.tsx`) — see below.
- **TaskRow** (`components/task-row.tsx`) — the one task-list-row
  component, shared by Overview's "Happening now"/"Needs attention",
  the global Tasks page, the project workspace task list, and discovery
  handoff tasks.

## Pipeline visualization

`PipelineStages` renders the twelve tracked phases
(`ROUTING…DONE`, matching `PHASE_ORDER` in `src/aipipe/control/activity.py`)
as a five-state grid: **done** (check), **active** (pulsing dot, current
phase), **pending** (empty dot), **skipped** (prohibit icon — a phase that
never appeared in the activity feed but a later phase did, e.g. `PLANNING`
for a non-`DEEP` task), and **failed** (X, the current phase when the task
stopped in `BLOCKED`/`FAILED`/`CANCELLED`/`NEEDS_INPUT`).

This is intentionally *only* what the backend actually recorded — no
interpolated/fabricated in-between progress. There is no explicit "Security"
node in the visual pipeline: security-review status is a real, distinct
piece of state (`checks.security_review`), but it is not a `TaskStatus`
phase the backend transitions through, so inventing a pipeline circle for it
would be exactly the "fake granular progress" the issue prohibits. It is
instead surfaced as its own labeled tile in the Checks & Review section,
next to the (also real) local-checks, review, and CI results.

## Activity & technical surfaces

The human-readable activity timeline (`ActivityCard` in
`app/tasks/[id]/page.tsx`) is the primary account of what happened; the raw
event log is demoted to a collapsed "Technical details" disclosure
(`font-mono`, `text-xs`, on `surface-sunken`) — present for anyone who wants
it, never the default view. Chain-of-thought is never rendered anywhere;
only structured phase/check/review events the control plane actually stores.

## Focus & accessibility

- Global `:focus-visible { outline: 2px solid var(--color-accent); }` —
  never removed, never `outline: none` without a replacement.
- A "Skip to content" link (`components/shell.tsx`) is the first focusable
  element on every page.
- Every icon-only affordance has an `aria-label` (e.g. the settings gear
  button, the per-command remove button in project settings).
- Icons are `aria-hidden`; the adjacent text is the accessible name.

## Motion policy

Per Emil Kowalski's design-engineering skill: reduced motion means fewer and
gentler animations, not zero.

- `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)` / `--ease-in-out:
  cubic-bezier(0.65, 0, 0.35, 1)` — custom curves, not the weak CSS
  built-ins. `ease-in` is never used for UI transitions.
- All interactive transitions are `<=260ms` and animate only `transform`/
  `opacity`/`background-color`/`border-color` — never `transition: all`,
  never layout properties.
- `.animate-live-pulse` (opacity breathing on the status dot for the
  `active` tone) and `.animate-enter` (260ms fade/rise on task-page mount)
  are the only two custom keyframe animations in the app. There is
  deliberately no per-row list-entry stagger: this is a dashboard whose
  lists re-poll every 5–10s, and staggering re-renders on every poll would
  read as distracting jitter rather than polish.
- `@media (prefers-reduced-motion: reduce)` collapses all animation/
  transition durations to near-zero globally and disables the live pulse,
  while leaving color/opacity state changes intact (per Emil's guidance —
  reduced motion keeps state-communicating changes, removes movement).
  Covered by `app/globals.css.test.ts`.

## Known, intentional deviations

- **Touch target size.** UI/UX Pro Max's touch-and-interaction checklist
  calls for a 44×44px minimum. Buttons here are ~36–38px tall
  (`px-3.5 py-2`, `text-sm`), matching the density of comparable
  professional dev tools (Linear, GitHub, Vercel dashboards) rather than a
  touch-first mobile app. This trades touch-target size for information
  density, which is the correct trade for an operations console — but it's
  a real, deliberate deviation from that checklist item, not an oversight.
- **No live region on status-badge changes.** Status badges update via
  polling/SSE without an `aria-live` announcement. Given the number of
  simultaneously-updating badges on a busy dashboard, adding live regions
  to all of them would likely be more disruptive (constant screen-reader
  interruption) than helpful; a scoped live region (e.g. only around the
  single task-detail "Currently" card) is a reasonable follow-up if this
  becomes a real accessibility complaint.
