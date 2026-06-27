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
