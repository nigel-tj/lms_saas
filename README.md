# LMS SaaS

Enterprise loan management for microfinance — RBZ sandbox compliance, borrower portal, payments, collections, and ERPNext GL integration.

## Requirements

| App | Branch |
|-----|--------|
| [Frappe](https://github.com/frappe/frappe) | version-16 (v15 supported) |
| [ERPNext](https://github.com/frappe/erpnext) | version-16 |
| [Lending](https://github.com/frappe/lending) | version-16-beta or version-16 |
| [HRMS](https://github.com/frappe/hrms) | version-16 |

Frappe v16 uses `/desk/…` routes (v15 uses `/app/…`). This app detects the major version and builds URLs accordingly.

Install order: `erpnext` → `lending` → `hrms` → `lms_saas`

## Install (bench)

```bash
bench get-app https://github.com/nigel-tj/lms_saas.git --branch main
bench --site <site> install-app lms_saas
bench --site <site> migrate
bench --site <site> execute lms_saas.install.after_install
bench build --app lms_saas
bench --site <site> enable-scheduler
```

## Verify

```bash
bench --site <site> execute lms_saas.setup.verify_spec.run_all_checks
```

## Company onboarding (live-safe, reusable)

Use this to wire a new company from day one (idempotent; defaults to dry-run).

Dry-run:

```bash
bench --site <site> execute lms_saas.setup.onboard_company.run --kwargs '{"company":"Kesari","dry_run":1}'
```

Apply:

```bash
bench --site <site> execute lms_saas.setup.onboard_company.run --kwargs '{"company":"Kesari","apply":1,"company_name":"Kesari","domain":"kesari.africa","run_verify":1}'
```

Optional flags:

- `send_test_email`: send SMTP test after setup (`test_email_recipient` optional)
- `include_demo`: seed demo portfolio (`demo_count` optional)
- `smtp_*`: override SMTP values for this run (`smtp_server`, `smtp_port`, `smtp_email_id`, `smtp_password`, `smtp_use_ssl`)

Shell wrapper (from bench root after the app is installed):

```bash
FC_SITE=<site> COMPANY=Kesari DRY_RUN=1 bash apps/lms_saas/scripts/onboard-company.sh
FC_SITE=<site> COMPANY=Kesari APPLY=1 COMPANY_NAME=Kesari DOMAIN=kesari.africa bash apps/lms_saas/scripts/onboard-company.sh
```

## Documentation

| Doc | Audience |
|-----|----------|
| [docs/FRAPPE_CLOUD.md](docs/FRAPPE_CLOUD.md) | Frappe Cloud deploy |
| [docs/SYSADMIN_GUIDE.md](docs/SYSADMIN_GUIDE.md) | Operators |
| [docs/STAFF_GUIDE.md](docs/STAFF_GUIDE.md) | Desk staff |
| [docs/COMPLIANCE.md](docs/COMPLIANCE.md) | RBZ sandbox mapping |

## Configuration

Copy `site_config.example.json` keys into site config (never commit secrets). See SYSADMIN_GUIDE §5.

## License

MIT
