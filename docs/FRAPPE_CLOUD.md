# Deploy LMS SaaS on Frappe Cloud

## Prerequisites

- [Frappe Cloud](https://frappecloud.com) account with **payment method** (private bench required for custom apps)
- GitHub repo: `**lms_saas`** app at repository root (see publish script below)
- Stack apps on **Frappe v16**: ERPNext, Lending, HRMS, LMS SaaS (v15 supported locally; desk URLs auto-switch `/app` ↔ `/desk`)

## 1. Publish app to GitHub (one-time)

From the monorepo:

```bash
./scripts/publish-lms-saas-app.sh
./scripts/validate-frappe-cloud-app.sh dist/lms_saas-publish
```

Create GitHub repo `lms_saas` (empty), then:

```bash
cd dist/lms_saas-publish
git init
git add .
git commit -m "Initial lms_saas release for Frappe Cloud"
git branch -M main
git remote add origin https://github.com/nigel-tj/lms_saas.git
git push -u origin main
```

> Frappe Cloud expects the **app root** at repo root (`lms_saas/hooks.py` package inside). Do not push the whole `erp-loan-microfin` monorepo unless you symlink manually on a private VM.

## 2. Create private bench group

1. Dashboard → **Benches** → **New** (private bench group)
2. Framework: **v16**
3. **Apps** → Add from marketplace/GitHub:


| App      | Source                                      |
| -------- | ------------------------------------------- |
| erpnext  | Frappe Cloud / `version-16`                 |
| lending  | GitHub `frappe/lending` branch `version-16-beta` or `version-16` |
| hrms     | GitHub `frappe/hrms` branch `version-16`    |
| lms_saas | GitHub `nigel-tj/lms_saas` branch `main`    |


1. **Validate** each custom app → **Deploy** bench group

## 3. Create site

1. **Sites** → **New** on the private bench
2. Hostname: e.g. `lms-saas.frappe.cloud` (custom domain `app.kesari.africa` added later under **Domains** — this is the live production URL)
3. Install apps: `erpnext`, `lending`, `hrms`, `lms_saas`
4. Set Administrator password

## 4. Post-install (bench console or SSH)

One command (recommended):

```bash
# On Frappe Cloud bench (SSH). Use the *.frappe.cloud site folder name, not the custom domain.
export FC_SITE=lms-saas.frappe.cloud
bash apps/lms_saas/scripts/frappe-cloud-postinstall.sh
```

Pipe from laptop (download FC SSH key from dashboard first):

```bash
ssh -i ~/.ssh/frappe-cloud.pem -p 2222 bench-42841-000002-f20nm@n1-mumbai-frappe.frappe.cloud \
  'bash -s' < scripts/frappe-cloud-postinstall.sh
```

Or run steps manually:

```bash
bench --site <site> migrate
bench build --app lms_saas
bench --site <site> clear-cache
bench --site <site> enable-scheduler
bench --site <site> execute lms_saas.setup.verify_spec.run_all_checks
```

> `migrate` runs the `after_migrate` hook (`lms_saas.install.after_install`). No separate `after_install` call needed on updates.

## 5. Site configuration

Merge keys from `[site_config.example.json](../site_config.example.json)` in **Site → Configuration**. Add integration URLs/secrets only in cloud UI, never in git.

## 6. DNS & SSL

Point your domain A/CNAME per Frappe Cloud dashboard → enable SSL.

## 7. Demo data (SSH)

After migrate/build, seed a portfolio like local dev (sets borrower consent on compliance records):

```bash
export FC_SITE=lms-saas.frappe.cloud
bash apps/lms_saas/scripts/frappe-cloud-seed-demo.sh
```

Requires the **bench SSH private key** from Frappe Cloud (Dashboard → Bench → SSH). Save as `~/.ssh/frappe-cloud.pem` (`chmod 600`) and connect:

```bash
ssh -i ~/.ssh/frappe-cloud.pem -o IdentitiesOnly=yes -p 2222 \
  bench-42841-000002-f20nm@n1-mumbai-frappe.frappe.cloud
```

Local `~/.ssh/id_rsa` will **not** work unless that public key is registered on the bench in FC.

## 7. Updates

### Local monorepo (symlinked bench)

After editing `apps/lms_saas/`:

```bash
./scripts/bench.sh start-redis
./scripts/bench.sh update
```

`update` = migrate + build + clear-cache + verify_spec + verify_styling.

Pull latest Frappe v16 stack apps to match cloud:

```bash
./scripts/bench.sh bench-update
```

### Frappe Cloud (lms_saas GitHub repo)

```bash
./scripts/push-lms-saas-app.sh "your release message"
```

Then in [Frappe Cloud](https://cloud.frappe.io/):

1. **Benches** → **Deploy** (pulls latest `lms_saas` from GitHub)
2. **Sites** → **Update** on `lms-saas.frappe.cloud`

SSH post-update (no site config overwrite):

```bash
export FC_SITE=lms-saas.frappe.cloud
LMS_SKIP_SITE_CONFIG=1 bash apps/lms_saas/scripts/frappe-cloud-update.sh
```

Or use the full post-install script for first-time setup only.

### What `frappe-cloud-update.sh` does (and why)

The Frappe Cloud dashboard's generic `Benches → Deploy` + `Sites → Update`
covers the framework side: it runs `bench migrate`, rebuilds the JS bundles,
clears the cache, and restarts the scheduler. That is identical for every
Frappe app. It does NOT know about lms_saas-specific state, which is what
this script reconciles after every deploy:

1. **`bench migrate`** — schema migrations (patches.txt)
2. **`bench build --app lms_saas`** — re-bundle JS so the browser stops
   loading stale `?v=…` cache-bust hashes on `lms_portal.js`,
   `lms_desk.js`, `lms_officer_portal.js`, etc.
3. **`bench clear-cache`** — drop document + Redis + browser cache
4. **`enable-scheduler`** — restart SMS queue + audit pipeline workers
5. **`lms_saas.install._reconcile_loan_dashboard`** — re-link LMS Number
   Cards / Charts to the Loan Dashboard workspace (idempotent)
6. **`lms_saas.install._set_portal_role_home_pages`** — re-point LMS
   Portal Staff / Loan Officer / Collector / Branch Manager to their
   landing workspace
7. **`lms_saas.install._set_admin_home_page`** — re-point Admin / System
   Manager to the admin landing page
8. **`lms_saas.setup.verify_spec.run_all_checks`** — the operator's
   verification suite. Catches workspace drift, role-home desync, audit
   pipeline gaps, and brand-chain leaks. A red ✗ line in its output
   means a deploy broke something the framework's `migrate` would NOT
   catch. Run `--dry-run` next to see what it would have flagged.

#### Auto-detection

If `FC_SITE` is not set, the script auto-detects:

- the only site on the bench (most common case)
- otherwise the site whose name starts with `lms` (case-insensitive)
- otherwise prompts with the list of available sites and an explicit
  `FC_SITE=<site>` override example

So for a bench with one site, **no env var is required**:

```bash
bash apps/lms_saas/scripts/frappe-cloud-update.sh
```

#### Flags

| Flag | Behaviour |
|---|---|
| `--dry-run` | Print every `bench` command, do not execute it. Safe to run on any bench to preview. |
| `--check-only` | Skip `migrate` / `build` / `clear-cache` / `enable-scheduler`. Run only steps 5–8. Cheap, ~10 seconds. |
| `--skip-build` | Skip `bench build --app lms_saas` only (use when deploy hooks already rebuilt). |
| `--help` | Print the comment header and exit. |

#### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success, no drift |
| `2` | A `bench` command failed (migrate / build / cache). Run again or inspect. |
| `3` | `verify_spec` reported drift (a red ✗ line). The script prints the offending check. |

#### Idempotency

Every step above is documented to be idempotent. Running the script
twice produces the same end-state as running it once. Running it after
a no-op pull (no new commits) is a no-op. Total runtime ~1 minute on
a typical bench.

## Bench app manifest (reference)

```text
frappe
erpnext
lending
hrms
lms_saas
```

## Troubleshooting


| Issue                 | Fix                                          |
| --------------------- | -------------------------------------------- |
| `required_apps` error | Install lending + hrms before lms_saas       |
| verify_spec fails     | Run `after_install`; enable scheduler        |
| Portal 404            | `bench build --app lms_saas`; clear-cache    |
| Payments/AML          | Enable in site_config + provider credentials |
| `404 Not Found: <domain> does not exist` | Use the site folder from `ls sites/` (e.g. `lms-saas.frappe.cloud`), not the custom domain |
| SSH hangs locally     | Download bench SSH private key from Frappe Cloud dashboard; `ssh -i <key.pem> -p 2222 ...` |


See also: [SYSADMIN_GUIDE.md](SYSADMIN_GUIDE.md), [ONBOARDING.md](ONBOARDING.md)