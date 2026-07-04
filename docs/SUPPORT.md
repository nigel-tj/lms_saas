# LMS Support & SLA

## Service tiers

| Tier | Audience | Response (business hours) | Channels |
|------|----------|---------------------------|----------|
| **Pilot** | RBZ sandbox / single-site beta | Best effort, 48h | Email |
| **Standard** | Production MFI (single tenant) | P1: 4h, P2: 1 business day | Email + desk escalation |
| **Enterprise** | Multi-branch / high volume | P1: 1h, P2: 4h | Email, phone, dedicated contact |

## Severity definitions

- **P1 — Critical:** Money movement blocked, site down, data integrity risk
- **P2 — Major:** Origination/collections impaired, integration failure with workaround
- **P3 — Minor:** UI, reporting, non-blocking defects

## Incident response

1. Log in **LMS Incident Log** (Compliance & Risk workspace)
2. Capture timeline, affected loans/customers, rollback steps
3. P1: notify sysadmin + vendor within SLA window
4. Post-incident: root cause in incident record; update runbooks

## Escalation

| Step | Owner |
|------|--------|
| L1 | Branch manager / LMS Admin |
| L2 | System administrator (see [SYSADMIN_GUIDE.md](SYSADMIN_GUIDE.md)) |
| L3 | Development team (`apps/lms_saas`) |

## Related

- [BACKUP.md](BACKUP.md) — restore procedures
- [ONBOARDING.md](ONBOARDING.md) — new tenant checklist
- [SYSADMIN_GUIDE.md](SYSADMIN_GUIDE.md) — scheduler, integrations, verify_spec
