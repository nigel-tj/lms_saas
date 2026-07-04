# RBZ Fintech Sandbox Compliance Mapping

**System administrators:** enabling controls, weekly KPI export, and pilot checklist → [SYSADMIN_GUIDE.md](SYSADMIN_GUIDE.md).

Reference: [RBZ Fintech Regulatory Sandbox Guidelines (Feb 2021)](compliance/RBZ-Fintech-Regulatory-Sandbox-Guidelines-2021.pdf).
Development rule: `.cursor/rules/rbz-fintech-compliance.mdc` (always applied).

This maps RBZ requirements to LMS implementation. Status: Done / Partial / Planned.

| RBZ ref | Requirement | LMS implementation | Status |
|---------|-------------|--------------------|--------|
| 3.18 | KYC/AML/CFT enforced | KYC "Approved" gate in `api/underwriting.py` | Done |
| 3.18 | AML/CFT screening | `api/aml.py` hook on compliance + origination | Done |
| 3.19 | Customer consent for testing | `consent_given` + `consent_date` on compliance | Done |
| 3.20 | Risk disclosure to customers | portal risk disclosure block | Done |
| 4.5 | Transaction/customer limits | `compliance.py` config-driven limit checks | Done |
| 4.5 | Sandbox window (<=24 months) | `lms_sandbox_end_date` config gate | Done |
| 3.17, 4.10 | Data security, no secrets in code | integrations via `site_config` | Done |
| 4.11 | Third-party due diligence | credit bureau/SMS config-driven, documented | Done |
| 5.1 | Immutable audit trail | Frappe Version + `LMS Audit Event` log | Done |
| 5.1 | Four-eyes on high-impact actions | maker-checker on disbursement/write-off | Done |
| 5.1 | Incident & risk register | `LMS Incident Log` doctype | Done |
| 5.1 | Weekly KPI reporting | `api/compliance.get_sandbox_report` | Done |
| 3.2 | No crypto/digital/CBDC | prohibited by rule; none built | Done |
| Annex 3.1 | Eligible: P2P/marketplace lending, digital KYC | core LMS scope | Done |
| 3.20 | Secured lending / collateral register | `LMS Collateral` + loan collateral table | Done |

## Collateral management

`LMS Collateral` is the security register (submittable for reversibility/audit).
Loans and Loan Applications pledge assets via the **Collateral** child table
(`LMS Loan Collateral`), supporting many-to-many pledging with a per-loan
allocated value.

- **Net realizable value** = forced sale value if provided, else
  `market_value * (1 - haircut% / 100)`.
- **Origination coverage** is enforced on Loan Application submit, config-gated
  in `site_config` (off by default so seeding/tests are unaffected):

```jsonc
{
  "lms_require_collateral": true,        // block submit if no collateral pledged
  "lms_min_collateral_coverage": 1.25    // min net-realizable / loan-amount ratio
}
```

- Coverage summary API: `lms_saas.api.collateral.get_loan_collateral_summary`
  (`doctype`, `name`) — permission-scoped.
- Submit/cancel of a collateral record is written to the `LMS Audit Event` trail.

## Weekly sandbox report

```bash
bench --site lms.localhost execute lms_saas.api.compliance.get_sandbox_report
```

Returns volunteer customer count, transaction value/volume, incident log,
complaints, and audit references for the RBZ weekly submission (Annex 5.1).
