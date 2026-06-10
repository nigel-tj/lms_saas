# LMS Branding & Theme System

## Overview

Branding lives entirely in `apps/lms_saas` — no changes to `frappe` or `erpnext` core.

| Surface | Assets | Hooks |
|---------|--------|-------|
| **Desk** (staff) | tokens → themes → components → `lms_desk.css`, `lms_theme.js`, `lms_desk.js` | `app_include_css`, `app_include_js` |
| **Portal** (`/lms`) | same stack → `lms_portal.css`, `lms_portal.js` | `web_include_css`, `web_include_js` |
| **PDF** | `templates/print/lms_*.html` | Seeded via `install.py` |

## Theme architecture (switchable CSS)

Load order is fixed in `hooks.py`:

1. **`lms_tokens.css`** — structural tokens (radii, fonts, layout) + semantic aliases
2. **`lms_themes/default.css`** — default palette (teal fintech)
3. **`lms_themes/midnight.css`** — alternate palette (deep navy)
4. **`lms_components.css`** — shared UI patterns (hero, panel, action tiles, pills)
5. **`lms_desk.css`** or **`lms_portal.css`** — surface-specific layout only

The active theme is selected with `data-lms-theme` on `<html>`:

```html
<html data-lms-theme="default">
```

`lms_theme.js` applies this on desk boot; portal sets it from template context.

### Switch theme

Add to site config (`frappe-bench/sites/lms.localhost/site_config.json`):

```json
{
  "lms_theme": "midnight"
}
```

Valid values: `default`, `midnight`. Then:

```bash
bench --site lms.localhost clear-cache
```

Hard-refresh the browser. Desk and portal both pick up the new palette.

### Add a new theme

1. Create `lms_saas/public/css/lms_themes/your-theme.css` setting all `--theme-*` variables.
2. Register the file in `hooks.py` → `_lms_css_stack()`.
3. Add the id to `VALID_LMS_THEMES` in `utils/brand.py` and `lms_theme.js`.

No desk/portal CSS changes required if you only override `--theme-*` tokens.

## Shared component classes

Use these in templates and JS for consistent look across desk + portal:

| Class | Purpose |
|-------|---------|
| `.lms-hero` | Page header banner with accent stripe |
| `.lms-hero__title`, `.lms-hero__subtitle` | Hero typography |
| `.lms-panel` / `.lms-portal-board` | White rounded content panel |
| `.lms-section-pill` | Uppercase section label chip |
| `.lms-action-tile` | Shortcut / action card |
| `.lms-tile--{cyan,blue,green,...}` | Tile accent colour |

Desk workspace shortcuts auto-receive `.lms-action-tile` via `lms_desk.js`.

## Portal

- Base template: `lms_saas/templates/lms_portal/base.html`
- Pages: `www/lms/index.html`, `www/lms/loan.html`
- Brand context: `lms_saas/utils/brand.py`

## Desk navigation

LMS staff use **Frappe Lending** native navigation (`/app/loans`) and the **Loan Dashboard** page (12 lending KPIs + LMS risk cards/charts). Compliance and investor screens live under **Lms Saas** workspaces (re-applied on migrate via `install._sync_lms_workspaces()`).

The desk **Help** dropdown is replaced with role-filtered links to `/lms-help/*` pages (markdown from `apps/lms_saas/docs/`). Menu items are defined in `lms_saas/utils/help.py` and applied on migrate via Navbar Settings plus `lms_desk.js`.

## White-label surfaces

| Surface | Brand source | Stock chrome hidden |
|---------|--------------|---------------------|
| Desk | `boot.py` favicon/splash; `lms_desk.js` navbar + title | Help dropdown, frappe.io links, `.footer-powered` |
| Login / logout | `www/login.html` + `apply_login_context()` | `web_footer`, navbar; logout → `/login?logged_out=1` |
| Portal `/lms` | `templates/lms_portal/base.html` + `apply_portal_context()` | `web_footer`; legacy account pages via `get_portal_shell` |
| Help `/lms-help` | `apply_help_page_context()` + shared CSS stack | Same as portal |
| Email | `templates/email/lms_email_base.html` + `get_email_brand_context()` | Branded header/footer only |
| Print PDF | `templates/print/lms_*.html` | Company name from Global Defaults |

Optional `site_config.json` overrides (read in `enrich_brand()`): `lms_brand_tagline`, `lms_brand_footer_text`, `lms_brand_primary_color`.

Automated leak scan (templates/www/JS):

```bash
bench --site lms.localhost execute lms_saas.setup.verify_styling.run_all
```

## Customize logo & favicon

| Asset | Default file | Override |
|-------|----------------|----------|
| **Logo** (navbar, login, portal header) | `public/images/lms-logo.svg` | Website Settings → App Logo |
| **Favicon** (browser tab, loading spinner, desk splash) | `public/images/lms-favicon.svg` | Website Settings → Favicon |
| **Desk boot splash** | Same as favicon | Website Settings → Splash Image |

On migrate, `install._setup_navbar_branding()` sets logo, favicon, and splash to the bundled assets. Portal/desk loading states use the favicon mark (pulse animation) via `lms_brand.js`.

1. **Desk / global:** Setup → Website Settings → App Logo / Favicon / Splash Image.
2. **Portal title:** Uses default company from Global Defaults.

## Deploy after UI changes

```bash
cd frappe-bench
bench build --app lms_saas
bench --site lms.localhost clear-cache
```

Hard-refresh the browser (Ctrl+Shift+R) on Desk and `/lms`.

## Logout

Portal and help pages link to `/?cmd=web_logout`. `lms_saas` overrides Frappe's stock
"Logged Out" message page and redirects to the branded `/login?logged_out=1` screen
(same layout and CSS as sign-in). Hook key must be `web_logout` (shorthand cmd), not only
`frappe.handler.web_logout`. Implementation: `utils/web_auth.py`, `www/login.py` +
`www/login.html`.

## URLs

- Desk home (Lending app): `/app/loans`
- Loan Dashboard: `/app/dashboard-view/Loan Dashboard` (default route for LMS staff)
- LMS compliance workspaces: `/app/compliance-&-risk`, etc. (Lms Saas module)
- Borrower portal: `/lms`
