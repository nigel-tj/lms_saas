# LMS SaaS — Role-by-Role Sweep Design

> **Purpose**: Authoritative contract for the executable role-by-role sweep
> that gates "ready for pilot / ready for showcase". Every user-story in
> [`docs/USER_ROLE_PLAYBOOK.md`](../../docs/USER_ROLE_PLAYBOOK.md) maps to one
> Playwright step in this directory. A passing sweep with no exceptions = ready.

**Date**: 2026-08-04
**Status**: Design contract v1 — implementation begins immediately after.
**Owner**: Agent (writes code) + Operator (writes creds + Twilio test number).

---

## 1. Scope

The sweep must demonstrate that every persona's user-stories from
`docs/USER_ROLE_PLAYBOOK.md` render and behave correctly against the live
Frappe Cloud site `https://lms-saas.frappe.cloud`.

| Persona | Email | Password | Landing | Stories |
|---|---|---|---|---|
| Borrower | `borrower@example.com` | `Borrower@123` | `/lms` | B1–B5 |
| Loan Officer | `officer@kesari.africa` | `Officer@123` | `/lms/officer` | O1–O8 |
| Loan Officer | `field@kesari.africa` | `Field@123` | `/lms/officer` | (read-only re-check) |
| Branch Manager | `manager@kesari.africa` | `Manager@123` | `/lms/manager` | M1–M7 |
| Branch Manager | `supervisor@kesari.africa` | `Supervisor@123` | `/lms/manager` | (read-only re-check) |
| Branch Manager | `admin@kesari.africa` | `Admin@123` | `/desk` | A1–A2 |
| Collector | `collector@kesari.africa` | `Collector@123` | `/lms/collect` | C1–C2 |
| Collector | `senior.collector@kesari.africa` | `Senior@123` | `/lms/collect` | (read-only re-check) |

Source of truth for credentials:
[`apps/lms_saas/lms_saas/setup/live_repair.py#L212-L286`](../apps/lms_saas/lms_saas/setup/live_repair.py)
(the canonical `TEST_USERS` table).

---

## 2. Pass criteria

A user-story **passes** only if all three are true:

1. **Acceptance criteria** from `USER_ROLE_PLAYBOOK.md` evaluated to `True`
   (selectors / text presence / DOM count match).
2. **No console errors** — Playwright `page.on("console", …)` accumulates
   every `console.error`/`pageerror` for the duration; the story sees zero.
3. **No permission errors** — every `frappe.call`/fetch inside the story
   completes with HTTP 2xx; any 403/500 (other than documented allow-listed
   `payments-not-enabled`) fails the story.

A user-story **fails** otherwise. The sweep is binary: every story green OR
the sweep fails.

---

## 3. Architecture

```
scripts/role-sweep/
├── SWEEP_DESIGN.md                 # this file
├── run.sh                          # one-shot entrypoint
├── conftest.py                     # pytest fixtures (browser, page, login)
├── sweep.py                        # argparse driver — one role or `--all`
├── utils/
│   ├── __init__.py
│   ├── auth.py                     # login(), logout(), login_as(role)
│   ├── console.py                  # ConsoleErrorCollector
│   ├── evidence.py                 # screenshot, save_evidence, append_evidence
│   └── users.py                    # canonical users table (mirrors live_repair TEST_USERS)
├── tests/
│   ├── __init__.py
│   ├── test_01_borrower.py         # B1-B5
│   ├── test_02_officer.py          # O1-O8
│   ├── test_03_manager.py          # M1-M7
│   ├── test_04_collector.py        # C1-C2
│   ├── test_05_admin.py            # A1-A2
│   └── test_06_read_only_users.py  # field/supervisor/senior checks (smoke only)
└── allowlist.txt                   # one allow-listed error per line, justified
```

### Run order

1. **Preflight** — bash `preflight.sh` verifies env, Python deps,
   Playwright browsers, `FC_SITE` reachable, bench reachable.
2. **Read-only re-check** — `test_06` covers the 4 shadow personas
   (field, supervisor, senior.collector, expected = same as their persona).
3. **Primary roles** — `test_01`–`test_05` execute in the order borrower →
   officer → manager → collector → admin (login order is intentional;
   admin lands on /desk last so any portal session bleed is caught early).
4. **Twilio smoke** — after the primary roles pass, `test_twilio_smoke.py`
   sends a single test SMS to the operator's test number via the live
   `lms_saas.api.integrations.twilio_api.send_sms` whitelist.
5. **Evidence write-out** — per-role Markdown docs under `docs/sweep/<date>/role-*.md`
   + a `summary.md` + a `sweep-results.json` (machine-parseable).

### Exit codes

- `0` — every user-story passed.
- `1` — at least one user-story failed (see `summary.md` for which).
- `2` — preflight failed (env / Playwright / connectivity).

---

## 4. Per-user-story coverage

The full matrix lives inline in each `test_NN_*.py`. Below is the
contract — the test files must implement exactly these.

### 4.1 Borrower (`test_01_borrower.py`)

| ID | Story | URL | Key assertions | Pass = |
|---|---|---|---|---|
| B1 | My Loans | `/lms` | `data-testid="lms-total-outstanding"` renders a positive number; `data-testid="loan-list-item"` ≥ 1; schedule row visible | Text + count |
| B2 | Loan Detail | `/lms/loan?name=<loan_id>` | Status badge = "Disbursed"; Outstanding > 0; Pay button `data-testid="loan-pay"` visible | Text + presence |
| B3 | New Application wizard step 1 | `/lms/apply` | Step indicator shows "1 of 4"; Product dropdown populated; `data-testid="apply-product-select"` enabled | Text + interactable |
| B4 | Initiate payment | `/lms/pay` | Loan pre-selected; `data-testid="pay-amount"` accepts input; Provider dropdown shows EcoCash / OneMoney / bank transfer | DOM mutation |
| B5 | Account / KYC / Documents | `/lms/account` | KYC status badge visible; AML badge visible; Consent status visible; Documents count > 0 OR friendly empty state | Text + count |

### 4.2 Loan Officer — primary (`test_02_officer.py`)

| ID | Story | URL | Key assertions | Pass = |
|---|---|---|---|---|
| O1 | Dashboard KPIs | `/lms/officer` | Pending ≥ 0, Awaiting disbursement ≥ 0, Active loans ≥ 0, PAR ≥ 0 all render | Text |
| O2 | My Loans tab | `/lms/officer` → "My Loans" tab | Active loans table renders; Pending disbursement section renders if drafts exist | DOM |
| O3 | Borrowers tab | `/lms/officer` → "Borrowers" tab | 5 Approved + 1 Pending; columns Name/Mobile/Email/Loans/Active/KYC/Outstanding render | Count |
| O4 | KYC Queue tab | `/lms/officer` → "KYC Queue" | Pending=1, In Review=0, Approved=5, Rejected=0; Review buttons present | Count |
| O5 | Leads tab | `/lms/officer` → "Leads" tab | Either friendly empty state OR counts render (no 500) | No network error |
| O6 | Reports tab | `/lms/officer` → "Reports" | Portfolio Summary, Arrears Aging, Collections Report render | DOM |
| O7 | New Application modal | trigger | Modal opens with amount=10000, rate=24, customer dropdown populated, close button works | Interaction |
| O8 | Disburse | trigger on ACC-LOAN-2026-00008 | Toast "Disbursed — LM-DIS-00008"; loan moves to active without page reload | Interaction + DOM delta |

### 4.3 Branch Manager (`test_03_manager.py`)

| ID | Story | URL | Key assertions | Pass = |
|---|---|---|---|---|
| M1 | Dashboard with Portfolio KPIs | `/lms/manager` | All 6 KPIs render; Risk Mix donut renders; Team Performance bars render | Text + canvas |
| M2 | Borrowers tab — branch-wide | `/lms/manager` → "Borrowers" tab | 6 borrowers listed (incl TestBorrower) | Count |
| M3 | Loans tab — branch-wide | `/lms/manager` → "Loans" tab | 8 loans visible (not just officer's) | Count |
| M4 | Approvals tab | `/lms/manager` → "Approvals" tab | "All caught up" OR accurate count | Text |
| M5 | Reports tab | `/lms/manager` → "Reports" | Arrears / Disbursement / Collections / Portfolio Summary all render | DOM |
| M6 | Collateral tab (R39 fix) | `/lms/manager` → "Collateral" tab | 5 collateral items; **each row exposes a View button** (was missing pre-R39) | Count + interaction |
| M7 | Team tab | `/lms/manager` → "Team" tab | 7 members; Loan Officer cell shows 8 loans / 5 borrowers | Count |

### 4.4 Collector (`test_04_collector.py`)

| ID | Story | URL | Key assertions | Pass = |
|---|---|---|---|---|
| C1 | Field Collection landing | `/lms/collect` | Online status; Stops today / Amount due / Offline queue render; empty state if no dues; **no "Failed to create chart" console error (R25 fix)** | DOM + console clean |
| C2 | Today's run sheet | `/lms/collect` → run sheet | Borrowers due list renders (or empty state) | DOM |

### 4.5 Admin (`test_05_admin.py`)

| ID | Story | URL | Key assertions | Pass = |
|---|---|---|---|---|
| A1 | Desk landing | `/desk` | Full module nav renders; **`/desk/lending` 404 is allow-listed** (R35-#24) — does NOT fail the sweep | Text |
| A2 | LMS Portal as Branch Manager persona | `/lms/manager` | Identical to M1–M7; "Full Desk" link in sidebar | DOM |

### 4.6 Read-only persona re-check (`test_06_read_only_users.py`)

| Persona | URL | Assert |
|---|---|---|
| field@ | `/lms/officer` | Landing renders; primary KPI strip identical to officer@ |
| supervisor@ | `/lms/manager` | Landing renders; sidebar identical to manager@ |
| senior.collector@ | `/lms/collect` | Landing renders; identical to collector@ |

These are smoke tests — they catch role-mixing regressions but don't
re-execute every story.

---

## 5. Twilio smoke (`test_twilio_smoke.py`)

After every other test passes:

1. Login as `admin@kesari.africa` to obtain a session.
2. POST `/api/method/lms_saas.api.integrations.twilio_api.ping` →
   `{"enabled": true, "settings": …}` (else sweep **fails** this section).
3. POST `/api/method/lms_saas.api.integrations.twilio_api.send_sms` with
   `to_number=<OPERATOR_TEST_NUMBER>`, `body="LMS-SaaS sweep smoke test @ <timestamp>"`,
   `purpose="Sweep Smoke"`.
4. Wait ≤ 15s for the `LMS SMS Send Log` row to be written
   (`status = Delivered` or `Sent`).
5. Pass = SMS landed AND log row created. Fail otherwise.

`OPERATOR_TEST_NUMBER` is **never** checked in. Operator provides it via
the env var `SWEEP_TWILIO_TO`. If unset, the Twilio smoke section is
skipped (not failed) and emits `INFO: twilio smoke skipped — set
SWEEP_TWILIO_TO to enable`.

---

## 6. Allow-list

`allowlist.txt` entries (one per line): `regex<tab>justification`.

Default entries (initial):

- `^Page lending not found$` — `/desk/lending` is a documented known-broken
  page; admin uses `/desk` instead (R35-#24, fixed in routing but slug
  still 404s).
- `^Online payments are not enabled on this site\.?$` — only when the
  request URL contains `payments/service.py`. Collapse path for non-Twilio
  rails when `lms_payments_enabled=False`.

Any new entry requires a written justification + GitHub issue link.

---

## 7. Required env

```
# Required (no default)
FC_SITE                                       # e.g. https://lms-saas.frappe.cloud
FC_ADMIN_PASSWORD                             # bench Administrator password for direct API reset

# Optional
SWEEP_TWILIO_TO                               # operator's Twilio test number in E.164 (e.g. +263…)
SWEEP_ARTIFACTS_DIR=./_artifacts              # screenshot dump
SWEEP_HEADLESS=true                           # false to watch live
SWEEP_TIMEOUT=20                              # per-step timeout seconds
SWEEP_VIDEO=false                             # record per-role video for evidence
```

Pre-flight checks (in `preflight.sh`):

- `FC_SITE` reachable; login page returns 200.
- `/api/method/frappe.ping` returns `pong`.
- Administrator session obtainable with `FC_ADMIN_PASSWORD`.

---

## 8. Run commands

```bash
# Install once
pip install playwright pytest-playwright
python -m playwright install chromium

# Run full sweep
bash scripts/role-sweep/run.sh

# Run a single role
bash scripts/role-sweep/run.sh --role manager

# Dry run on local bench first
FC_SITE=http://lms.localhost:8000 bash scripts/role-sweep/run.sh --role borrower
```

Evidence output (default `./docs/sweep/<YYYY-MM-DD>/`):

- `role-borrower.md` … `role-admin.md`
- `summary.md`
- `sweep-results.json`
- `screenshots/<role>/<story>.png`
- `console/<role>/<story>.log`

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Multi-worker Frappe Cloud — sessions cross workers | Use cookie + Login using the form endpoint, not just bearer; each test logs in fresh (no shared state). |
| `set_user(Administrator)` corruption (R38) | Sweep never calls `set_user` directly — it always uses the live browser session. |
| Race conditions on first-load whitelist bootstrap | `preflight.sh` warms `/api/method/frappe.ping` + a sentinel whitelisted call before tests start. |
| Twilio carrier filtering | Use operator's own number; produce a `delivered_at` log row rather than asserting inbound. |
| Demo data drift (e.g. a fresh `frappe-cloud-seed-demo.sh` re-run) | `user story` assertions are counts that are *robust to drift* — they're sensitive to *presence*, not exact rows. |

---

## 10. Effort estimate

| Item | Files | Lines (est.) |
|---|---|---|
| SWEEP_DESIGN.md | 1 | 200 |
| `run.sh` + `preflight.sh` + `sweep.py` + `conftest.py` | 4 | 250 |
| `utils/{auth,console,evidence,users}.py` | 4 | 300 |
| `tests/test_01_borrower.py` … `test_06_read_only_users.py` | 6 | 600 |
| `tests/test_twilio_smoke.py` | 1 | 80 |
| Allow-list + evidence templates | 2 | 60 |
| Evidence-docs script (auto-generates `summary.md`) | 1 | 80 |
| **Total** | **19** | **~1,570 LOC** |

Estimated wall-clock: **1.5 days** for an author familiar with the
codebase + Playwright.

---

## 11. Definition of done

The sweep is considered **ready** (this phase) when ALL of:

- [ ] `bash scripts/role-sweep/run.sh` exits 0 against
      `https://lms-saas.frappe.cloud`.
- [ ] All 6 primary user-story tests (B/O/M/C/A + read-only) pass.
- [ ] Twilio smoke passes (or is documented skipped).
- [ ] Evidence written to `docs/sweep/<YYYY-MM-DD>/` with 8 per-role docs + summary.
- [ ] `[release/pilot-<YYYY-MM-DD>]` tag exists on the merge commit.
- [ ] GitHub release created with the summary + per-role docs attached.
- [ ] Any surfaced regressions filed as GitHub issues with label `post-sweep`.

Once that checklist is green, "is the app ready for pilot / showcase" is a
**yes**, and the answer is reproducible by anyone who can run
`bash scripts/role-sweep/run.sh`.
