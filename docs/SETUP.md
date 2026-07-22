# LMS SaaS Setup Guide

**System administration:** install, config, backups, compliance, troubleshooting → [SYSADMIN_GUIDE.md](SYSADMIN_GUIDE.md).

**Staff training:** desk workflows, roles, and daily operations → [STAFF_GUIDE.md](STAFF_GUIDE.md).

## Stack

Install apps in order (do not modify `frappe` or `erpnext` core):

```bash
cd frappe-bench
export PATH="$HOME/.local/bin:$PATH"
bench get-app erpnext --branch version-15
bench get-app lending
bench get-app hrms --branch version-15
bench --site lms.localhost install-app erpnext lending hrms lms_saas
bench --site lms.localhost migrate
bench build --app lms_saas
bench --site lms.localhost execute lms_saas.install.after_install
```

## Blueprint mapping

| Feature | Implementation |
|---------|----------------|
| Branches | Cost Centers + `custom_lms_branch` on Loan / Application / Customer |
| Borrowers | ERPNext Customer + LMS Borrower Compliance |
| Loan products | `LMS-STD` seeded in `install.py` |
| Staff RBAC | LMS Admin, Branch Manager, Loan Officer, Collector roles |
| Reports | Portfolio At Risk, Arrears Aging, Collection Sheet |
| CRM | ERPNext Lead/Opportunity + **CRM & Prospects** workspace; convert Lead → Customer |
| Notifications | Branded HTML email (`utils/email.py`) + daily SMS/email reminders in `tasks.py` |
| Borrower portal | `/lms` — login as Customer-linked user |
| PDF documents | Print Formats LMS Loan Statement / Agreement |
| HRMS | Required app; `custom_loan_officer` links Employee |
| Investor GL | LMS Investor Transaction submit → Journal Entry |

## SMS and email

### Dev site (local)

If desk shows *missing email account* when sending mail from CRM or Communication:

```bash
bench --site lms.localhost execute lms_saas.setup.seed_dev_email.run
```

This creates **LMS Dev Outgoing** (`noreply@lms.localhost` → SMTP `127.0.0.1:1025`, no auth). Optional: run [Mailpit](https://github.com/axllent/mailpit) (`mailpit` or Docker on port 1025) to catch messages. Otherwise inspect **Email Queue** in Desk.

Auto-seed on migrate when `developer_mode` is on or `lms_seed_dev_email` is set in `site_config.json`.

### Production / staging

1. **Email Account** — Setup → Email Account (outgoing).
2. **SMS Settings** — Setup → SMS Settings → set `sms_gateway_url` (JSON POST `{to, message}`). If unset, messages are logged only.
3. **Branded email** — HTML templates in `lms_saas/templates/email/` (logo, teal header, footer). Seeded on migrate as **Email Template** records. Used for payment reminders, repayment confirmations, and lead acknowledgements.
4. **Optional** — `site_config.json` → `lms_email_legal_footer` for sandbox/legal text in the email footer.

## CRM (prospects)

1. Desk → **CRM & Prospects** workspace (Lead pipeline, Opportunities, Communications).
2. On each **Lead**, record **Customer Consent Given** before marketing email or **Convert to Borrower**.
3. **Convert to Borrower** creates a Customer (and LMS Borrower Compliance stub when National ID is set).
4. CRM module is enabled for LMS staff via the **LMS Staff** module profile (alongside Lending and Lms Saas).

## Data import (repayments)

Use **Data Import** on DocType `Loan Repayment` with columns: `against_loan`, `applicant_type`, `applicant`, `posting_date`, `amount_paid`, `company`.

## Portal users (admin emergency recovery only)

> **Preferred path:** use the **LMS User Setup** desk form (one-screen onboarding). The steps below are kept for emergency recovery when the form is unavailable.

1. Create **Customer** with email.
2. Create **User** with same email; assign role **Customer**.
3. Add **Contact** linked to Customer (email must match User).
4. Borrower opens `/lms` after login.

## Demo loan path

```bash
bench --site lms.localhost execute lms_saas.setup.seed_demo.run
```

## Loan lifecycle background jobs (required)

Interest accrual, DPD/NPA classification (incl. suspense-ledger postings) and
payment reminders run via scheduled jobs. The scheduler MUST be enabled:

```bash
bench --site lms.localhost enable-scheduler
```

Key jobs (owned by the `lending` app + LMS cron):

| Job | Owner | Frequency |
|-----|-------|-----------|
| `process_loan_interest_accrual_for_term_loans` | lending | daily_long |
| `create_process_loan_classification` (native DPD/NPA + suspense) | lending | daily_long |
| `lms_saas.tasks.run_daily_loan_cron` (mirrors DPD to `custom_*`, reminders) | lms_saas | daily |

The LMS nightly cron only mirrors delinquency into reporting fields; it does
NOT post GL, so it never fails on account configuration. Native NPA suspense
postings require the loan product / company accounts to be configured.

## Credit bureau integration (config-driven, non-blocking)

External credit scoring is optional and fail-open by default so a bureau
outage cannot halt loan origination. Configure in `site_config.json`:

```json
{
  "lms_credit_bureau_enabled": true,
  "lms_credit_bureau_url": "https://bureau.example.com/v1/score",
  "lms_credit_bureau_min_score": 600,
  "lms_credit_bureau_block_on_error": false,
  "lms_credit_bureau_timeout": 10
}
```

The KYC "Approved" gate on `LMS Borrower Compliance` is always enforced.

## Bulk feasibility seed (non-production)

```bash
bench --site lms.localhost execute lms_saas.setup.seed_demo.run_bulk --kwargs '{"count":16}'
```

Seeds borrowers across branches with current/watchlist/NPA profiles and partial
repayments for exercising dashboards and PAR/Arrears/Collection reports.

## Multi-tenant, isolation & scaling

- Each tenant is a separate Frappe site (own DB) on the shared bench; app code
  is shared, data is isolated by site.
- Branch/company isolation within a site uses Frappe **User Permissions**:
  assign a User Permission on `Cost Center` (branch) and/or `Company` to branch
  staff. The desk dashboard (`api/dashboard.get_desk_dashboard`) uses
  `frappe.get_list`, so it automatically scopes to the user's allowed branch;
  query reports set `apply_user_permissions: 1`.
- Performance: `custom_days_past_due`, `custom_lms_branch`, and
  `custom_loan_officer` are indexed (`search_index`) for fast PAR/arrears/ECL
  filtering. For very large portfolios, prefer SQL `GROUP BY` aggregation over
  in-Python loops in custom dashboards.

## Compliance (RBZ Fintech Sandbox)

See [COMPLIANCE.md](COMPLIANCE.md). Weekly KPI report:

```bash
bench --site lms.localhost execute lms_saas.api.compliance.get_sandbox_report
```

Production controls (enable in `site_config.json`): `lms_enforce_four_eyes`,
`lms_require_consent`, `lms_max_loan_amount`, `lms_max_active_customers`,
`lms_sandbox_end_date`.

## Pilot staging (VM)

Deploy to **https://app.kesari.africa** — full VM guide:
[STAGING.md](STAGING.md).

## Verification

```bash
bench --site lms.localhost execute lms_saas.setup.verify_spec.run_all_checks
```

## New company onboarding (repeatable)

Use the onboarding command for each new company. It is idempotent and returns a JSON summary.

1. Run dry-run first.

```bash
bench --site <site> execute lms_saas.setup.onboard_company.run --kwargs '{"company":"<Company Name>","dry_run":1}'
```

2. Apply once dry-run looks correct.

```bash
bench --site <site> execute lms_saas.setup.onboard_company.run --kwargs '{"company":"<Company Name>","apply":1,"run_verify":1}'
```

3. Optional actions:

- Test SMTP send: add `"send_test_email":1` and optional `"test_email_recipient":"ops@example.com"`
- Seed demo data: add `"include_demo":1` and optional `"demo_count":16`
- One-run SMTP overrides: add `smtp_server`, `smtp_port`, `smtp_email_id`, `smtp_password`, `smtp_use_ssl`

4. Wrapper script (bench root):

```bash
FC_SITE=<site> COMPANY="<Company Name>" DRY_RUN=1 bash apps/lms_saas/scripts/onboard-company.sh
FC_SITE=<site> COMPANY="<Company Name>" APPLY=1 RUN_VERIFY=1 bash apps/lms_saas/scripts/onboard-company.sh
```

What it wires by default:

- Company identity fields (if provided)
- Branch cost centers and LMS standard loan product/account sync
- LMS roles, permissions, dashboards, workspaces, portal/menu setup
- Branded email template sync and optional live SMTP account configuration
- Post-check verification (targeted by default; full checks optional)

## User permissions (branch isolation)

Assign **User Permission** on Cost Center for branch staff. Combine with `custom_lms_branch` on loans for reporting filters.

## Modern UI / branding

Desk and borrower portal use the LMS design system (tokens, branded portal shell, workspace shortcuts). See [BRANDING.md](BRANDING.md) for customization and asset paths.

After UI changes: `bench build --app lms_saas` and `bench --site lms.localhost clear-cache`.
