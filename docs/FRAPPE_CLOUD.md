# Deploy LMS SaaS on Frappe Cloud

## Prerequisites

- [Frappe Cloud](https://frappecloud.com) account with **payment method** (private bench required for custom apps)
- GitHub repo: `**lms_saas`** app at repository root (see publish script below)
- Stack apps on **Frappe v15**: ERPNext, Lending, HRMS, LMS SaaS

## 1. Publish app to GitHub (one-time)

From the monorepo:

```bash
./scripts/publish-lms-saas-app.shhttps://cloud.frappe.io/https://cloud.frappe.io/
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
2. Framework: **v15**
3. **Apps** → Add from marketplace/GitHub:


| App      | Source                                      |
| -------- | ------------------------------------------- |
| erpnext  | Frappe Cloud / `version-15`                 |
| lending  | GitHub `frappe/lending` branch `version-15` |
| hrms     | GitHub `frappe/hrms` branch `version-15`    |
| lms_saas | GitHub `nigel-tj/lms_saas` branch `main`    |


1. **Validate** each custom app → **Deploy** bench group

## 3. Create site

1. **Sites** → **New** on the private bench
2. Hostname: e.g. `lms.embleconsulting.com`
3. Install apps: `erpnext`, `lending`, `hrms`, `lms_saas`
4. Set Administrator password

## 4. Post-install (bench console or SSH)

```bash
bench --site <site> execute lms_saas.install.after_install
bench --site <site> migrate
bench build --app lms_saas
bench --site <site> clear-cache
bench --site <site> enable-scheduler
bench --site <site> execute lms_saas.setup.verify_spec.run_all_checks
```

## 5. Site configuration

Merge keys from `[site_config.example.json](../site_config.example.json)` in **Site → Configuration**. Add integration URLs/secrets only in cloud UI, never in git.

## 6. DNS & SSL

Point your domain A/CNAME per Frappe Cloud dashboard → enable SSL.

## 7. Updates

```text
git push (lms_saas repo) → Bench Deploy → Site Update → post-install commands above
```

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


See also: [SYSADMIN_GUIDE.md](SYSADMIN_GUIDE.md), [ONBOARDING.md](ONBOARDING.md)