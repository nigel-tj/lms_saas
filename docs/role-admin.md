# LMS Admin Help

This guide is for **Administrators** — the people who set up the system, manage users, and keep everything running. You do most of your work in the back office.

> Last updated: 22 July 2026.

## What you do here

- Set up new sites, branches, and users.
- Manage roles and what each role can see.
- Keep the sandbox rules working: KYC, four-eyes, weekly reports.
- Turn the optional addons on or off.
- Look after backups, the daily jobs, and the integrations (credit bureau, AML, SMS, payments).

## Sign in

1. Open the sign-in page in Chrome, Firefox, or Edge. Your IT team will give you the link.
2. Type your admin email and password.
3. You will land on the **back office** home page, which shows the loan book at a glance.

## The back office home page

The home page is a dashboard. It shows the live state of the loan book in six panels:

| Panel | What it tells you |
|---|---|
| Portfolio KPIs | How much is outstanding, how many loans are active, how many are 30+ or 90+ days late, how many are non-performing |
| Application pipeline | How many applications are at each step, from draft to disbursed |
| Today’s collections | How much came in today, the arrears buckets, and the top collectors |
| KYC and AML queue | How many borrower records are still waiting for identity and consent |
| System health | Whether the daily jobs ran, when the last backup was, and any errors in the last 24 hours |
| Recent activity | The last few audit events — money movements and approvals |

You can narrow every panel to a single branch using the **Branch** selector at the top right.

## The Admin Console

The **Admin Console** is a single page that puts every panel above into one place. It is meant for spot-checking, not for day-to-day work.

- Use the **Refresh** button to drop the short cache and pull fresh numbers.
- A yellow “Showing the first 50,000 loans” banner appears if the loan book is very large. Pick a branch to narrow the page down.
- The **Health** pill at the top of every back office page is green, amber, or red. Click it to jump straight to the Admin Console.

## Workspaces

The back office is split into five workspaces:

1. **Loan Management** — the landing workspace, with portfolio KPIs and the dashboards
2. **Reports** — portfolio, arrears, provisions, collections
3. **Compliance and Risk** — provisions, incidents, audit log, weekly sandbox summary
4. **Investors** — investor book, transactions, payments
5. **Addons** — turn portal addons (Announcements, Tasks, Documents, Support, HR, Analytics, and so on) on or off

Each workspace has shortcuts for the most common lists and reports.

## Roles and access

| Role | What they can do |
|---|---|
| System Manager | Full access to the back office, including investors and compliance |
| LMS Admin | All back office workspaces, including investors |
| LMS Portal Staff | Borrower portal only. The portal page they see depends on the persona set on their staff profile (Loan Officer, Branch Manager, or Collector) |

Only System Manager and Administrator can see the back office. Everyone else works in the portal.

## Adding a user

For almost every case, use the **LMS User Setup** form in the back office. One submit does the whole job:

- Creates the sign-in account.
- Creates the contact record.
- Creates the customer record (for borrowers) or the staff record (for staff).
- Applies the right role and persona.

The persona field on the staff record decides which portal page the user lands on. If a Collector is being sent to the borrower page, the persona field is missing or wrong.

For emergency recovery (the form is not available), the manual steps are kept in the system admin guide, but they are not the recommended path.

## Sandbox and compliance

Your branch follows the Reserve Bank sandbox rules. The most important settings live in the site configuration:

- **KYC must be Approved** before a loan can be submitted. This is always on.
- **Four-eyes on disbursements** — turn it on in the site config; the system then makes sure a different staff member from the one who created the loan is the one who submits the disbursement.
- **Sandbox window** — the site will stop accepting new applications after the end date. Adjust the date in the site config if you need to extend.
- **Loan limits** — set a maximum loan size and a maximum number of active borrowers in the site config.

The weekly compliance summary is built from the data already in the system. You can read it under **Compliance and Risk** → **Weekly summary**, or you can ask the system to email it to the compliance team.

## When you have learned the basics

You can tick these off:

- [ ] Sign in and reach the back office home page.
- [ ] Add a new user for each role (Loan Officer, Branch Manager, Collector, Borrower) using the LMS User Setup form.
- [ ] Turn an addon on and off in the Addons workspace, and check that the right users can see it.
- [ ] Open the Admin Console and read every panel.

## Need help?

| Problem | Who to ask |
|---|---|
| Roles, access, permissions | System Manager |
| Sandbox rules, four-eyes, limits | System Manager |
| Outages, backups, scheduling | IT / System Manager |
| Addon not working | IT / vendor support |
| Loans data questions | System Manager |
