# Brand Configuration Quickstart

This document is the **canonical reference** for setting the operator's brand on a `lms_saas` site. The login page, the portal navbar, the desk chrome, and the email footers all read from a single source of truth — so a brand change happens in **one place, in one command**, and cannot silently drift.

> **TL;DR — fix a "LMS" / "Frappe" / generic-name login page in one command:**
>
> ```bash
> bench --site <your-site> execute lms_saas.utils.brand.set_brand \
>   --kwargs '{"portal_title": "Your Brand"}'
> ```
>
> No restart. The next request picks up the new brand.

---

## Why the live site shows "LMS" instead of your brand

The `lms_saas` package is **vendor-neutral**: the source code does not know which operator is running it, so every brand string falls back to the product-family name (`"LMS"`) by default. The operator's brand name lives in **one place** — the site's `site_config.json` — and is read at request time.

The login page resolves the brand in this order:

1. `brand.portal_title` (read from site_config → `lms_brand_portal_title`, with a default of `"LMS"`).
2. Frappe's `app_name` (from Website Settings / System Settings).
3. Empty string (so the heading is never blank — the page just shows whatever the next ancestor is set to).

If the live site shows `"LMS"`, it means **step 1 is falling through to the default** — `lms_brand_portal_title` is either unset, empty, or set to `"LMS"` explicitly. The fix is to set it.

> ⚠️ Do **not** hard-code a brand name in `www/login.html` or any template. The `R23-Q1-C1` regression pin (and the `R33` test added on top of it) catches hard-coded `"Kesari"` or any other operator name in user-facing strings. Templates must read from the brand chain.

---

## The one-call setter: `lms_saas.utils.brand.set_brand`

`set_brand` is the supported way to set the visible brand. It writes to **all three** places the brand is stored, in a single transaction, so the login page heading, the portal footer, and the desk title bar can never drift:

1. `site_config.json` — `lms_brand_portal_title`, `lms_brand_tagline`, `lms_brand_footer_text`, `lms_brand_primary_color`, `lms_support_email`, `lms_brand_logo_path`, `lms_brand_favicon_path`.
2. **Website Settings** — `app_name`, `brand_html` (and `app_logo` / `favicon` / `splash_image` if paths are provided).
3. **System Settings** — `app_name` (the title-bar / browser-tab string).

After the write, it clears the Frappe cache so the next request sees the new value without a restart.

### Quick fix — name only

```bash
bench --site <your-site> execute lms_saas.utils.brand.set_brand \
  --kwargs '{"portal_title": "Kesari"}'
```

### Full rebrand — name, tagline, footer, colour, support email, assets

```bash
bench --site <your-site> execute lms_saas.utils.brand.set_brand \
  --kwargs '{
    "portal_title": "Kesari",
    "tagline": "Stewardship in every repayment",
    "footer_text": "Powered by Kesari",
    "primary_color": "#2f4f46",
    "support_email": "support@kesari.africa",
    "logo_path": "/files/kesari-logo.svg",
    "favicon_path": "/files/kesari-favicon.svg"
  }'
```

### Dry-run first (recommended)

```bash
bench --site <your-site> execute lms_saas.utils.brand.set_brand \
  --kwargs '{"portal_title": "Kesari", "tagline": "...", "dry_run": true}'
```

The dry-run prints the planned writes and exits without touching anything.

### What the return value looks like

```json
{
  "applied": [
    "site_config.json: wrote 1 key(s)",
    "website_settings: app_name, brand_html updated",
    "system_settings: app_name updated",
    "frappe cache cleared"
  ],
  "skipped": [],
  "failed": []
}
```

If something goes wrong, the `failed` list names the exact step that didn't apply, and the `applied` list shows what did make it through — so a partial failure never leaves the brand in a half-applied state.

---

## Manual fallback (Frappe Cloud dashboard)

If you can't run a `bench execute` (e.g. you only have the Frappe Cloud dashboard), edit `site_config.json` directly:

1. Frappe Cloud dashboard → **Site** → **Configuration**.
2. Add (or update) these keys:

   ```json
   {
     "lms_brand_portal_title": "Kesari",
     "lms_brand_tagline": "Stewardship in every repayment",
     "lms_brand_footer_text": "Powered by Kesari",
     "lms_brand_primary_color": "#2f4f46"
   }
   ```

3. Click **Save**. The next request picks up the new value (no rebuild required for the config change, but the login page renders the `lms_login.css` bundle which IS cached — run `bench --site <site> clear-website-cache` or trigger a `bench build --app lms_saas` if the visual style hasn't picked up).

> The Frappe Cloud dashboard only writes the **site_config** half of the brand. The Website Settings + System Settings half is updated the next time `lms_saas.install.after_install` runs (or the next time you call `set_brand`). The login page reads from `site_config` first, so the page heading will be correct immediately — but the desk title bar will lag until after_install / set_brand.

---

## How the brand chain resolves (for the curious)

```
brand.portal_title
  └── site_config: lms_brand_portal_title  ← operator's value (or "LMS" if unset)
        ↓
Frappe app_name (from Website Settings or System Settings)
        ↓
empty string (last-resort; the heading is never blank)
```

The `lms_brand_<key>` site_config keys are also exposed via the helper `lms_saas.utils.brand._brand_alias`, which is used by templates and email subjects that need a per-key override (e.g. a custom `footer_text` without re-stating the `portal_title`).

### Spot-check the current brand

```python
# bench --site <site> execute lms_saas.utils.brand.get_portal_brand
import frappe, json
frappe.init(site="<site>", sites_path=frappe.utils.get_bench_path() + "/sites")
frappe.connect()
print(json.dumps(frappe.get_module("lms_saas.utils.brand").get_portal_brand(), indent=2))
```

Expected output (the brand set on the live site):

```json
{
  "portal_title": "Kesari",
  "tagline": "Stewardship in every repayment",
  ...
}
```

If `portal_title` comes back as `"LMS"` (the product-family default), the live site has not been branded yet — run the setter above.

### Diff helper: see every brand-touching value in one place

```bash
bench --site <site> execute lms_saas.setup.rebrand.diff
```

Returns a flat dict showing `site_config`, `Website Settings`, `System Settings`, and the default company. Use this after a rebrand to confirm the value made it everywhere.

---

## Why the brand sometimes "flips back to generic" — and how to stop it

The brand can silently revert to `"LMS"` (or whatever the product default is) when:

| Cause | What happens | Fix |
|---|---|---|
| `site_config.json` is regenerated by Frappe Cloud's deploy hooks | The `lms_brand_*` keys are stripped if they're not in the deployment's source-of-truth config. | Add the keys to your deployment's site_config source (not just the dashboard). On Frappe Cloud, the dashboard is the source — but a custom `frappe-cloud-postinstall.sh` hook may overwrite it. |
| A `bench migrate` resets the System Settings / Website Settings | The desk title bar (System Settings) and the desk chrome (Website Settings) revert to Frappe's `app_name` default. | Re-run `set_brand` after `bench migrate` (or run the full rebrand via `lms_saas.setup.rebrand.run`). |
| The login template is edited and the resolution chain is reordered | A future engineer moves `app_name` ahead of `brand.portal_title`, or adds a hard-coded corporate name as a fallback. | The `R33` test (`lms_saas.tests.test_r33_brand_wiring.TestR33LoginHtmlBrandResolution`) pins the chain order and refuses hard-coded literals. If you see the R33 test fail, the chain is being reordered — fix the template, don't bypass the test. |
| `app_name` is set to the corporate name in `hooks.py` | `app_title` / `app_name` in `hooks.py` is the source of Frappe's `app_name` fallback. The R30 board kept the operator's brand in `hooks.app_title` so a fresh install shows the right wordmark without any site_config editing. The runtime override on `bootinfo.app_name` reaches the desk navbar / login page even if `Website Settings.app_name` is stale. | The R23 test (`TestR23AppTitleIsVendorNeutral`) pins the current value. The R32 test (`TestR32AppNameOverride`) pins the runtime override chain. |

### The brand is wired in three places — always set all three

1. `site_config.json` (operator's preferred value).
2. `Website Settings.app_name` + `brand_html` (the desk chrome).
3. `System Settings.app_name` (the title bar / browser tab).

`set_brand` writes all three in one call. The full `lms_saas.setup.rebrand.run` runner writes them plus the operator profile keys, the company onboarding, and the SMTP config.

---

## CI guards (what stops a future change from breaking this)

The brand contract is pinned in three test files. If any of these fail in CI, the brand wiring is being changed in a way that is **not** safe to ship:

| Test file | What it pins |
|---|---|
| `lms_saas.tests.test_r23_rebrand` | No hard-coded `"Kesari"` (or any operator name) in `utils/brand.py` or `utils/email.py`; `app_title == "LMS"` in `hooks.py`; logo / favicon paths respect the operator override. |
| `lms_saas.tests.test_r33_brand_wiring` | `www/login.html` has no hard-coded operator name; the resolution chain puts `brand.portal_title` first; `set_brand` exists and writes all three places; the chain falls through to the vendor-neutral `"LMS"` (not to a corporate name) when no brand is configured. |
| `lms_saas.tests.test_r23_rebrand.TestR23RebrandRunner` | The full rebrand runner is importable, dry-run prints a plan, and required-key validation refuses to no-op. |

Run all three locally before opening a PR that touches brand wiring:

```bash
cd frappe-bench
source env/bin/activate
python3 -c "
import sys, os
sys.path.insert(0, 'apps/frappe')
sys.path.insert(0, 'apps/lms_saas')
os.environ['FRAPPE_SITE'] = 'lms.localhost'
import frappe
frappe.init(site='lms.localhost', sites_path=os.path.join(os.getcwd(), 'sites'))
frappe.connect()
frappe.set_user('Administrator')
import unittest
loader = unittest.TestLoader()
suite = unittest.TestSuite()
for m in ['lms_saas.tests.test_r22_regressions',
         'lms_saas.tests.test_r23_rebrand',
         'lms_saas.tests.test_r33_brand_wiring']:
    suite.addTests(loader.loadTestsFromName(m))
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
frappe.destroy()
sys.exit(0 if result.wasSuccessful() else 1)
"
```

---

## See also

- [`docs/site_config.example.json`](../apps/lms_saas/site_config.example.json) — annotated example showing every `lms_brand_*` key.
- [`lms_saas.utils.brand`](../apps/lms_saas/lms_saas/utils/brand.py) — the brand module (`set_brand`, `enrich_brand`, `get_portal_brand`, `_brand_alias`).
- [`lms_saas.setup.rebrand`](../apps/lms_saas/lms_saas/setup/rebrand.py) — the full-rebrand runner (company + SMTP + license + brand).
- [`lms_saas.www.login`](../apps/lms_saas/lms_saas/www/login.html) — the login template that consumes the brand chain.
- [`lms_saas.tests.test_r33_brand_wiring`](../apps/lms_saas/lms_saas/tests/test_r33_brand_wiring.py) — the regression test that pins this contract.
