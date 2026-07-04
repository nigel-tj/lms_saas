# LMS SaaS — Design System v3

> Source of truth for the visual + interaction language. Brand colors are
> **not negotiable** — see [BRANDING.md](BRANDING.md). All new components
> MUST consume design tokens, not raw values.

---

## 1. Tokens (the only numbers allowed)

All design tokens live in [`public/css/lms_tokens.css`](../lms_saas/public/css/lms_tokens.css).
The CSS files under [`public/css/lms_themes/`](../lms_saas/public/css/lms_themes/)
resolve the semantic aliases. **Do not introduce a second namespace.**

### 1.1 Shape (radius scale — 5 values, no others)

| Token | Value | Where it is used |
|---|---|---|
| `--lms-radius-sm` | 6 px | Pills, small chips |
| `--lms-radius` | 12 px | Buttons, inputs, KPI cells |
| `--lms-radius-lg` | 16 px | Cards, panels, modals |
| `--lms-radius-panel` | 20 px | Page-level panels, the hero card |
| `--lms-radius-xl` | 24 px | Hero / hero KPI card only |

> If you find yourself wanting `border-radius: 10px`, **don't** — pick the
> nearest token. The whole point of the scale is that it does not drift.

### 1.2 Elevation (shadow ramp — 3 values, in `oklch`)

| Token | Value | Where |
|---|---|---|
| `--lms-shadow-1` | `0 1px 0 oklch(95% 0 0), 0 1px 2px oklch(20% 0 0 / 0.04)` | Tile, list item (rest) |
| `--lms-shadow-2` | `0 1px 0 oklch(95% 0 0), 0 4px 12px oklch(20% 0 0 / 0.08)` | Card hover, panel, KPI hover |
| `--lms-shadow-3` | `0 1px 0 oklch(95% 0 0), 0 12px 32px oklch(20% 0 0 / 0.12)` | Modal, slide-over, popover, toast |

Dark and midnight themes swap the highlight to `oklch(8% 0 0)` and lower
the alpha. No `box-shadow` declarations outside the theme files.

### 1.3 Motion (4 durations + 2 easings)

| Token | Value |
|---|---|
| `--lms-motion-fast` | 200 ms |
| `--lms-transition-fast` | `--lms-motion-fast var(--lms-ease-out-quart)` |
| `--lms-transition-base` | 320 ms `var(--lms-ease-out-quart)` |
| `--lms-transition-slow-ease` | 480 ms `var(--lms-ease-in-out-cubic)` |
| `--lms-ease-out-quart` | `cubic-bezier(0.25, 1, 0.5, 1)` |
| `--lms-ease-in-out-cubic` | `cubic-bezier(0.65, 0, 0.35, 1)` |

A single global `prefers-reduced-motion` rule at the bottom of `lms_tokens.css`
overrides every transition to 0.01 ms. Do not add a second one.

### 1.4 Type scale (9 sizes)

`--lms-fs-{xs(12) sm(14) base(16) md(18) lg(20) xl(24) 2xl(30) 3xl(36) 4xl(48)}` and
`--lms-lh-{tight(1.2) base(1.45) relaxed(1.6)}`. All currency and KPI values
get `font-variant-numeric: tabular-nums` via the `.lms-money` class.

### 1.5 Brand colors (do not change)

| Token | Light (default) | Midnight | Dark (auto) |
|---|---|---|---|
| `--theme-primary` | `#2f4f46` (forest green) | `#9fcab0` | `#a8d4b6` |
| `--theme-accent` | `#b9f19d` (signature light green) | `#b9f19d` | `#b9f19d` |
| `--theme-success` | `#5faf61` | `#7fcf81` | `#7fcf81` |
| `--theme-warning` | `#f4b942` | `#f6c871` | `#f6c871` |
| `--theme-danger` | `#e15c5c` | `#ec8080` | `#ec8080` |
| `--theme-info` | `#5d9cec` | `#7fb0f0` | `#7fb0f0` |

WCAG AA pairs verified at design time. Run `lms_saas.setup.verify_styling`
before any release to re-verify.

---

## 2. Components

### 2.1 Card (`.lms-card`, `.lms-panel`, `.lms-summary-card`, etc.)

`border: 1px solid var(--lms-border); border-radius: var(--lms-radius-lg);
box-shadow: var(--lms-shadow-1); transition: ... base`. On hover:
`box-shadow: var(--lms-shadow-2)` and `translateY(-1px)`. Never use the
hard-coded `rgba(0, 0, 0, 0.06)` pattern — it is non-theme-aware.

### 2.2 KPI card (`.lms-kpi`)

4-cell grid (2-cell on mobile) inside a single panel. Each cell has:

- `.lms-kpi__label` — uppercase, 0.7 rem, `var(--lms-text-muted)`
- `.lms-kpi__value` — `var(--lms-primary)`, `font-variant-numeric: tabular-nums`
- `.lms-kpi__delta--up / --down / --flat` — color + arrow + percent
- `.lms-kpi__spark` — 28-px-tall inline SVG sparkline (no axes)

Add `.lms-kpi--hero` to the panel for the "next action" cell on
`var(--lms-primary)` background; the CTA chip uses
`background: var(--lms-accent); color: var(--lms-primary)`.

### 2.3 Form

| Class | Purpose |
|---|---|
| `.lms-form` | Form wrapper (max-width 640 px, vertical gap) |
| `.lms-form-group` | Single field row (label + control + hint) |
| `.lms-label` | Visible field label (12 px, 600) |
| `.lms-input` | `<input>`, themed (border, focus ring, invalid state) |
| `.lms-select` | `<select>`, themed with custom SVG chevron |
| `.lms-hint` / `.lms-error` | Below-field text in muted / danger color |

Native `<select>` is themed; a popover-based listbox replacement is a
Phase 2 deliverable.

### 2.4 Chart slot (`.lms-chart-slot`)

Three-row grid: head, optional legend, body. The body hosts a
`frappe-charts` instance loaded via `LMSChart.line / bar / donut / area`
or a vanilla SVG sparkline from `LMSChart.sparkline()`. Theme-aware
colors are read from `getComputedStyle(documentElement)` — no JS branching
on theme.

States:
- **Loading** — `LMSChart.skeleton(el, count)` renders 8 px-tall shimmering
  bars.
- **Empty** — `LMSChart.empty(el, "No data yet")` renders centered muted
  text. No placeholder image.
- **Error** — surface as a toast (don't render a chart-shaped error).

### 2.5 Toast region (`.lms-toast-region`)

A single `role="status" aria-live="polite"` region at
`document.body > .lms-toast-region` (created on first use by
`lms_portal._ensureToastRegion()`). Bottom-right, max 360 px, 4-second
auto-dismiss, slide-in / slide-out via `--lms-motion-fast` / `--lms-motion-base`.

Use `lms_portal.toast(message, { variant: "success" | "error" | "warning" | "info" })`
to fire one. The legacy `frappe.show_alert` calls are auto-rerouted to the
toast region on portal pages.

### 2.6 Modal (`<dialog>`)

Use the native `<dialog>` element with `showModal()`. Style via
`dialog::backdrop { background: oklch(0% 0 0 / 0.45); backdrop-filter: blur(2px); }`.
The `closedby="any"` attribute (when supported) gives free backdrop-click
dismiss. Buttons inside a `<form method="dialog">` get native Esc / cancel.

### 2.7 Mobile menu (Popover API)

`<nav popover="manual" id="lms-portal-nav">` + `<button popovertarget="lms-portal-nav"
command="toggle-popover">`. Free outside-click + Esc + `inert` on the rest
of the page. Animate with `transition-behavior: allow-discrete; @starting-style`
for the slide-down + fade.

### 2.8 Skeleton (`.lms-skeleton`)

Single class, one `@keyframes lms-shimmer` (1.4 s, 200 % bg-size, no JS).
Used for KPI cells, list rows, chart containers, account cards.

---

## 3. Interaction primitives

### 3.1 Popover / dropdown

- **Native HTML**: `<div popover="auto" id="x">` triggered by
  `<button popovertarget="x" command="toggle-popover">`. No JS required
  for open / close / dismiss.
- **Custom positioning**: CSS Anchor Positioning
  (`position-anchor: --anchor; position-area: block-end;`).
- **Animation**: `transition-behavior: allow-discrete; @starting-style { opacity: 0; transform: translateY(-4px); }`.

### 3.2 Modal

See §2.6.

### 3.3 Tooltip

Plain CSS, no library. `[data-tooltip]` element gets a `::after`
pseudo-element with the tooltip text. Use for single-word abbrevs only
(DPD, NPA, APR). Multi-line explanations go in an "i" popover instead.

### 3.4 Toast

See §2.5.

### 3.5 Command palette (deferred)

Borrowed from Linear / Raycast. Single `Ctrl/Cmd-K` opens a `<dialog>` with
a search input + listbox. Phase 3 candidate.

---

## 4. Accessibility baseline (WCAG 2.2 AA)

- All interactive elements get a 2 px solid `var(--lms-focus)` outline at
  2 px offset on `:focus-visible`. **Never `outline: none` on a focusable
  element** — see the global focus rule in `lms_components.css`.
- 44 × 44 px touch target. The notification bell is now 44 × 44.
- Color is never the only signal — every status carries an icon + label
  pair (see `.lms-toast__icon`, the badge variants in `lms_portal.js`).
- `prefers-reduced-motion` is honored globally.
- `prefers-contrast: more` is honored via a future high-contrast theme
  file (`lms_themes/high-contrast.css`, Phase 3).

---

## 5. Themes

Four themes ship today:

| Theme ID | When to use |
|---|---|
| `default` | Light, default |
| `midnight` | Dark, professional, low blue-light |
| `dark` | Dark, brighter accent (for low-light offices) |
| `auto` | Follows `prefers-color-scheme` |

The active theme is set on `<html data-lms-theme="...">` at template render
time by `lms_brand.js`. The theme switcher in `lms_theme.js` is a 4-way
picker (System / Light / Midnight / Dark).

---

## 6. Microcopy (the voice)

- **Plain words over jargon.** "repayment" not "amortization installment".
- **Second person, present tense.** "You paid ₹2,450 on 4 July."
- **Specific, blame-free errors.** "We couldn't reach EcoCash. Check your
  signal and try again." Never "Something went wrong."
- **Confirm the action.** "Payment recorded." Not "Success!" Not "✓" alone.
- **Risk without alarm.** "This payment is 12 days late" is a fact, not a
  verdict. The DPD risk message on the loan detail page reads:
  "This payment is N days late. We can help you get back on track — call
  us at <number>."

A central `lms_saas/copy.py` is the planned home for every user-facing
string. Today, copy lives inline in the JS / template; a search-and-replace
into `copy.py` is a Phase 3 deliverable.

---

## 7. Files in this design system

- **Tokens** — [public/css/lms_tokens.css](../lms_saas/public/css/lms_tokens.css)
- **Components** — [public/css/lms_components.css](../lms_saas/public/css/lms_components.css)
- **Borrower portal layout** — [public/css/lms_portal.css](../lms_saas/public/css/lms_portal.css)
- **Staff portal layout** — [public/css/lms_staff_portal.css](../lms_saas/public/css/lms_staff_portal.css)
- **Login layout** — [public/css/lms_login.css](../lms_saas/public/css/lms_login.css)
- **Help docs** — [public/css/lms_help.css](../lms_saas/public/css/lms_help.css)
- **Themes** — [public/css/lms_themes/](../lms_saas/public/css/lms_themes/)
- **Charts wrapper** — [public/js/lms_charts.js](../lms_saas/public/js/lms_charts.js)
- **Borrower portal JS** — [public/js/lms_portal.js](../lms_saas/public/js/lms_portal.js)
- **Staff portal JS** — [public/js/lms_staff_portal.js](../lms_saas/public/js/lms_staff_portal.js)
- **Hook registration** — [hooks.py](../lms_saas/hooks.py)

---

## 8. Out of scope (for v3)

- New third-party libraries (no new chart libs, no icon fonts).
- New DocTypes.
- New business workflows (loan approval, disbursement, etc.).
- Native mobile apps.
- Icon font (SVG stays inline).
