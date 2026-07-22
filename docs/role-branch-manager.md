# Branch Manager Help

This guide is for **Branch Managers**. You spend most of your day in the Manager Portal, approving loans, watching collections, and looking after the team.

> Last updated: 22 July 2026.

## What you do here

- Approve or reject loan applications that your officers send up.
- Watch the daily collections and step in when arrears grow.
- Approve leave and expenses for your team.
- See reports for your branch and compare with other branches.
- Make sure your branch is following the sandbox rules (KYC, four-eyes, audit log).
- Do your **books and imports** for the branch — read GL, export to CSV/XLSX, and bring in repayments and KYC updates from a spreadsheet.

## Sign in

1. Open the sign-in page in Chrome, Firefox, or Edge. Your administrator will give you the link.
2. Type your staff email and password.
3. You will land on the **Manager Portal**.

If the page sends you to the Officer Portal or the Collection Run, your profile is not set up correctly. Ask your administrator to mark you as a Branch Manager.

## Your home page

The Manager Portal is built around four panels:

| Panel | What it shows |
|---|---|
| Approval queue | Loan applications waiting for your decision |
| Collections today | How much came in today, by branch and by officer |
| Team | Who is on duty, who is on leave, who has open expenses |
| Branch KPIs | Your branch compared to the rest of the network |

Use the **Branch** selector (top right) to switch the whole page between branches if you look after more than one.

## Approving a loan

1. In the **Approval queue**, click a row to open the application.
2. Read the applicant’s details, the proposed amount, and the risk notes.
3. Open the linked **KYC** record and the **Collateral** record to make sure they are complete.
4. Click **Approve** or **Reject** and write a short reason.

When the four-eyes rule is on for your branch, a yellow **Four-eyes required** badge shows. That means a different staff member must be the one who actually submits the disbursement — the person who created it cannot be the same one.

## Looking at the audit trail

Every approval and rejection writes a permanent record. To find it:

1. In the Manager Portal, open the **Audit** tab on the approval panel.
2. Use the branch and date filters to narrow the list.
3. Click any row to see the full details, including who did what and when.

These records cannot be edited. If a mistake was made, a new record is written to correct it. The original stays.

## Watching collections

- The **Collections** sidebar link opens the daily run sheet. You will see what was due, what came in, and what is still outstanding.
- Use the **Arrears ladder** to see how many borrowers are in each bucket (current, 30+ days late, 60+ days late, 90+ days late).
- Use the **Top movers** list to see which officers are collecting the most, and which need help.

## Addons (the optional pages in the sidebar)

The sidebar shows only the addons that are turned on for your branch. Each one opens a different page:

| Page | What it is for |
|---|---|
| **HR** | Leave approvals, team directory, attendance |
| **Analytics** | Branch-by-branch comparisons, officer leaderboard |
| **Payroll** | Run tracking and payslips |
| **Regulatory** | A read-only summary of your branch’s sandbox submissions |
| **Procurement** | Purchase requests and supplier directory |

If a page is stuck on **Loading…** and never finishes, the addon may be turned off or temporarily broken. Report it to your administrator.

## Sandbox and compliance

Your branch follows the Reserve Bank sandbox rules. Two of them affect your day:

- **KYC and consent must be Approved** before a loan can be submitted.
- **Four-eyes on disbursements** means a different staff member from the one who created the loan must press **Submit** on the disbursement.

The weekly compliance summary is prepared by your administrator. You can read it in the Manager Portal under **Compliance** → **Weekly summary**. If you cannot find it, ask your administrator.

## Books and import

Open **Books & Import** from the sidebar (the manager-only entry under the Manager Portal). The page has three tabs:

### Books tab
Read-only view of the branch general ledger.
- Pick a **From** and **To** date, then click **Load**.
- The four KPIs at the top show Income, Expense, Net, and the row count for the period.
- The table below shows the most recent 200 GL rows for your branch.
- Click **Export CSV** or **Export XLSX** to download the full set. Exports are recorded in the audit trail.

### Import tab
Bring in data from a spreadsheet without leaving the portal. The flow is staging-first so you can see the result before anything changes.

1. Pick a **DocType**:
   - **Loan Repayment** — for daily collections brought in by the field team.
   - **Customer** — for branch reassignment.
   - **LMS Borrower Compliance** — for bulk KYC / consent updates.
2. Click **Download CSV template** to get a starter file with the right columns.
3. Upload your completed file (CSV or XLSX).
4. Click **Stage & preview**. The system validates every row and shows you which are OK and which have errors. No live records change at this point.
5. Fix the rows with errors in your spreadsheet, re-upload, and stage again.
6. When the preview shows all rows OK (or only the ones you want to keep), click **Dry run** to confirm counts, then **Commit to live records**.

The commit happens in one transaction. If any row fails, the whole batch rolls back and the batch is marked **Failed** — your books stay clean. Each batch gets an **idempotency key**, so re-committing the same file is a no-op.

A successful commit writes an **LMS Audit Event** with the action `import_commit:<doctype>` and the row count.

### Reconciliation tab
Quick view of mobile-money statement matching. Shows total, matched, and unmatched counts for the branch company, plus a list of the most recent unmatched lines. To match them, ask an Admin — full statement import is a desk task today.

## When something is stuck

| What you see | What it means | What to do |
|---|---|---|
| Four-eyes warning on a disbursement | You are also the one who created it | Ask another Manager or the Admin to submit |
| You cannot see another branch’s data | Your branch permission is limited | Ask the administrator to widen your access |
| A page is stuck on Loading | The addon may be off or broken | Tell the administrator |

## When you have learned the basics

You can tick these off:

- [ ] Sign in and reach the Manager Portal.
- [ ] Approve or reject a loan application, respecting the four-eyes rule.
- [ ] Open the Audit tab and find the record for an approval you just made.
- [ ] Open one of the addon pages (HR, Analytics, Payroll, Regulatory, or Procurement) and know when to ask for help.
- [ ] Open **Books & Import**, load a date range, and export the books to CSV.
- [ ] Stage a sample CSV of Loan Repayments, preview, dry-run, then commit.
- [ ] Open the Reconciliation tab and find the unmatched line count.

## Need help?

| Problem | Who to ask |
|---|---|
| Roles, access, permissions | Your administrator |
| Four-eyes conflicts | Another Branch Manager or your administrator |
| Outages, backups, scheduling | Your administrator / IT |
| Borrower account details | The Loan Officer who onboarded them |
