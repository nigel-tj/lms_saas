# LMS Tenant Onboarding (30-day checklist)

## Week 1 — Platform

- [ ] Provision site: `bench new-site` + install erpnext, lending, hrms, lms_saas
- [ ] Run `lms_saas.install.after_install` and `verify_spec.run_all_checks`
- [ ] Enable scheduler; configure backup ([BACKUP.md](BACKUP.md))
- [ ] Create LMS staff users with **LMS Staff** module profile
- [ ] Branch User Permissions on Cost Center

## Week 2 — Compliance & integrations

- [ ] Configure sandbox limits: `lms_max_loan_amount`, `lms_sandbox_end_date`, consent
- [ ] Enable four-eyes if required: `lms_enforce_four_eyes`
- [ ] AML provider: `lms_aml_enabled`, `lms_aml_url` ([COMPLIANCE.md](COMPLIANCE.md))
- [ ] Credit bureau (optional): bureau keys in site_config
- [ ] SMS gateway (SMS Settings)
- [ ] Payment providers: enable rows in **LMS Payment Provider**, set `lms_payments_enabled`

## Week 3 — Operations

- [ ] Seed or import customers + **LMS Borrower Compliance** (KYC Approved)
- [ ] Train staff ([STAFF_GUIDE.md](STAFF_GUIDE.md)): origination, disbursement, collections
- [ ] Test borrower portal: `/lms`, `/lms/apply`, `/lms/pay`
- [ ] Test collector PWA: `/lms/collect` (LMS Collector role)
- [ ] Issue **LMS API Key** for integrations ([INTEGRATIONS.md](INTEGRATIONS.md))

## Week 4 — Go-live

- [ ] Pilot loan end-to-end with audit trail review
- [ ] Weekly KPI export: `lms_saas.api.compliance.get_sandbox_report`
- [ ] Document support tier ([SUPPORT.md](SUPPORT.md))
- [ ] Sign-off: PAR/ECL reports, incident log empty or triaged
