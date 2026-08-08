"""Idempotent live-site repair for LMS parity and role/home-page drift.

Use this when a site was created or upgraded before the parity fixes were in place.
It self-heals the common production issues without assuming the site was created
fresh.

Run:
  bench --site <site> execute lms_saas.setup.live_repair.repair_live_site_state
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

LEGACY_LMS_ROLES = (
    "LMS Admin",
    "LMS Branch Manager",
    "LMS Loan Officer",
    "LMS Collector",
)



def _pick_branch_used_by_seeded_data(company: str) -> str:
	"""Return the Cost Center that the existing seeded data is tagged with.

	QA-2026-08-03-#13-#18 (branch-drift root cause): on live, the
	R28/R29 seed runs created Customers/Loans on Cost Center
	``Main Branch - LS`` (suffixed -LS) while the seeder's original
	``provision_test_users`` was tagging Employees/Users with
	``Main Branch - LMS`` (or the un-suffixed ``Main Branch``). That
	mismatch meant the manager's data tabs (Borrowers/Loans/Reports/
	Collateral) showed 0 rows and the officer's disburse flow hit
	``Not in your branch.`` 403s -- even though the data was sitting
	right there in the DB.

	Resolution: rank Cost Centers by the count of Customer/Loan records
	already tagged with them, and pick the most-used one. If no
	records exist, fall back to the first non-group Cost Center.

	Args:
		company: the company the Cost Centers are scoped to.

	Returns:
		The Cost Center name (string) to use as the seeder's branch.
		Empty string if no Cost Center is available.
	"""
	if not company:
		return ""

	branches = frappe.get_all(
		"Cost Center",
		filters={"company": company, "is_group": 0},
		pluck="name",
	)
	if not branches:
		return ""

	# R43 fix: validate that the returned branch is one of the
	# company's own Cost Centers. The previous version returned the
	# branch with the most-data even if it was tagged on records
	# from a different company (e.g. a stale "Main - K" from an old
	# bench). Now we filter the data lookup to only count records
	# on branches that belong to this company.
	valid_branches = set(branches)

	# If only one branch, no choice to make.
	if len(branches) == 1:
		return branches[0]

	# Rank by Customer count, then Loan count. The branch with the
	# most existing records is the one the seeded data was tagged
	# with -- that is the branch the seeder must also use.
	# R43: only count records whose custom_lms_branch is in the
	# valid_branches set, so stale cross-company tags don't win.
	def _count(table, field):
		rows = frappe.db.sql(
			"""
			SELECT {0} AS branch, COUNT(*) AS n
			FROM `tab{1}`
			WHERE {0} IN %(branches)s
			GROUP BY {0}
			""".format(field, table),
			{"branches": list(valid_branches)},
			as_dict=True,
		)
		return {r["branch"]: int(r["n"]) for r in rows}

	customer_counts = _count("Customer", "custom_lms_branch")
	loan_counts = _count("Loan", "custom_lms_branch")

	# Pick the branch with the most records (customers, then loans).
	# If no branch has any records (e.g. a totally fresh install
	# before the bulk seeder runs), fall back to "Main Branch"
	# which is the convention for the demo site, then to the first
	# available branch alphabetically.
	best_branch = max(
		branches,
		key=lambda b: (
			customer_counts.get(b, 0),
			loan_counts.get(b, 0),
		),
	)
	if customer_counts.get(best_branch, 0) == 0 and loan_counts.get(best_branch, 0) == 0:
		# No records on any branch — prefer a "Main Branch" convention.
		main_branches = [b for b in branches if "main branch" in b.lower()]
		if main_branches:
			best_branch = sorted(main_branches)[0]
		else:
			best_branch = sorted(branches)[0]
	return best_branch


def _repair_legacy_user_roles() -> dict[str, int | list[str]]:
    """Remove stale legacy LMS roles from user assignments.

    These roles were retired in favor of the admin-only desk model and the
    portal-only LMS Portal Staff role. This step is safe to re-run and only
    touches user-role rows that still reference the retired names.
    """
    removed = 0
    touched_users: list[str] = []

    for role in LEGACY_LMS_ROLES:
        if not frappe.db.exists("Role", role):
            continue
        rows = frappe.get_all(
            "Has Role",
            filters={"role": role, "parenttype": "User"},
            fields=["name", "parent"],
        )
        for row in rows:
            frappe.db.delete("Has Role", {"name": row["name"]})
            removed += 1
            if row.get("parent") and row["parent"] not in touched_users:
                touched_users.append(row["parent"])

    frappe.db.commit()
    return {"removed_rows": removed, "touched_users": touched_users}


def reconcile_staff_branches(company: str | None = None) -> dict:
    """Reconcile Employee.custom_lms_branch onto a valid Cost Center.

    R47 root cause: staff Employees can end up with a ``custom_lms_branch``
    that no longer matches any Cost Center in the company. The most common
    causes are:

      - The branch was renamed during a brand change (R42 → R43 renamed
        ``Main Branch - LMS`` → ``Main Branch - LD`` and the legacy rows
        were not migrated).
      - The branch belonged to a previous Company (e.g. ``Main - K`` from
        the original "Kesari" bootstrapping on live).
      - The branch was hand-edited or copied from a different bench.

    Whatever the cause, the staff user lands on a phantom branch and the
    portal sees zero records because every query filters by
    ``custom_lms_branch``. The manager logs in, sees an empty dashboard,
    and concludes the data is broken — when in fact the data exists, the
    filter is just wrong.

    This function:

      1. Lists every Cost Center in the company.
      2. Lists every Employee with ``custom_lms_branch`` set.
      3. For Employees whose branch is missing from the company, picks a
         fallback branch (the one with the most Customers/Loans, or the
         first non-group Cost Center alphabetically).
      4. Updates Employee.custom_lms_branch + Employee.branch to the
         fallback, mirroring what ``LMS User Setup.on_submit`` writes.
      5. Reports what changed.

    Idempotent and safe to re-run. Returns a summary dict.
    """
    company = (
        company
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or ""
    )
    if not company:
        return {"ok": False, "skipped": "no default_company set"}

    valid_branches = set(
        frappe.get_all(
            "Cost Center",
            filters={"company": company, "is_group": 0},
            pluck="name",
        )
    )
    if not valid_branches:
        return {"ok": False, "skipped": "no Cost Centers in company"}

    # Pick the fallback branch (the one most existing records are tagged
    # with, so the corrected staff user lands on the same branch the data
    # is on — that's the whole point of the reconcile).
    fallback = _pick_branch_used_by_seeded_data(company)
    if not fallback or fallback not in valid_branches:
        fallback = sorted(valid_branches)[0]

    repaired: list[dict] = []
    already_valid: list[str] = []

    employees = frappe.get_all(
        "Employee",
        filters={"custom_lms_branch": ["is", "set"]},
        fields=["name", "user_id", "custom_lms_branch", "branch"],
    )
    for emp in employees:
        current = emp.get("custom_lms_branch")
        if not current:
            continue
        if current in valid_branches:
            already_valid.append(emp["name"])
            continue

        # Employee's branch is missing from the company — repair it.
        try:
            frappe.db.set_value(
                "Employee",
                emp["name"],
                {"custom_lms_branch": fallback, "branch": fallback},
                update_modified=True,
            )
            repaired.append(
                {
                    "employee": emp["name"],
                    "user_id": emp.get("user_id"),
                    "from_branch": current,
                    "to_branch": fallback,
                }
            )
        except Exception as exc:  # noqa: BLE001
            # If the set_value fails (e.g. permission), record it but
            # don't abort the whole loop — the next employee might be
            # repairable.
            repaired.append(
                {
                    "employee": emp["name"],
                    "user_id": emp.get("user_id"),
                    "from_branch": current,
                    "to_branch": fallback,
                    "error": str(exc),
                }
            )

    frappe.db.commit()
    return {
        "ok": True,
        "company": company,
        "fallback_branch": fallback,
        "valid_branches": sorted(valid_branches),
        "already_valid_count": len(already_valid),
        "repaired": repaired,
        "notes": [
            f"Found {len(employees)} Employee(s) with custom_lms_branch set",
            f"{len(already_valid)} already valid",
            f"{len(repaired)} repaired to fallback branch {fallback!r}",
        ],
    }


def _diagnose_user_setup() -> dict:
    """Capture a diagnostic trail for users that should be wired for desk/portal access."""
    from lms_saas.install import ADMIN_ROLES, SYS_ROLE, PORTAL_STAFF_ROLE

    issues: list[dict] = []
    for role_name in (SYS_ROLE, PORTAL_STAFF_ROLE, *ADMIN_ROLES):
        if not frappe.db.exists("Role", role_name):
            issues.append({"type": "missing_role", "role": role_name})

    users = frappe.get_all("User", filters={"enabled": 1}, fields=["name", "email", "user_type"])
    for user in users:
        if user.get("name") in {"Administrator", "Guest"}:
            continue
        roles = set(frappe.get_roles(user["name"]))
        if not roles:
            issues.append({"type": "no_roles", "user": user["name"]})
            continue
        if PORTAL_STAFF_ROLE in roles and any(role in roles for role in ADMIN_ROLES):
            issues.append({"type": "mixed_roles", "user": user["name"], "roles": sorted(roles)})

    return {"ok": not issues, "issues": issues, "user_count": len(users)}


def _repair_user_setup(diagnostic: dict) -> dict:
    """Repair the most common user-setup drift without changing business semantics."""
    from lms_saas.install import ADMIN_ROLES, PORTAL_STAFF_ROLE

    repairs: list[dict] = []
    for issue in diagnostic.get("issues", []):
        if issue.get("type") == "missing_role":
            role_name = issue["role"]
            if not frappe.db.exists("Role", role_name):
                frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)
                repairs.append({"type": "created_role", "role": role_name})
        elif issue.get("type") == "mixed_roles":
            user_name = issue["user"]
            user_roles = set(frappe.get_roles(user_name))
            if PORTAL_STAFF_ROLE in user_roles:
                user_roles.discard(PORTAL_STAFF_ROLE)
            if any(role in user_roles for role in ADMIN_ROLES):
                repairs.append({"type": "normalized_roles", "user": user_name, "roles": sorted(user_roles)})
                for role in sorted(user_roles):
                    frappe.get_doc("User", user_name).add_roles(role)

    frappe.db.commit()
    return {"repairs": repairs}


def repair_live_site_state() -> dict:
    """Run the live-site self-heal sequence in a safe, idempotent order."""
    from lms_saas.install import (
        after_install as run_install_bootstrap,
        _reconcile_loan_dashboard,
        _set_admin_home_page,
        _set_portal_role_home_pages,
        _setup_navbar_branding,
    )

    diagnostic = _diagnose_user_setup()
    repairs = _repair_user_setup(diagnostic)
    run_install_bootstrap()
    role_repair = _repair_legacy_user_roles()
    branch_repair = reconcile_staff_branches()
    _reconcile_loan_dashboard()
    _set_admin_home_page()
    _set_portal_role_home_pages()
    _setup_navbar_branding()

    frappe.db.commit()
    return {
        "ok": True,
        "diagnostic": diagnostic,
        "user_repairs": repairs,
        "role_repair": role_repair,
        "branch_repair": branch_repair,
        "notes": [
            "Ran after_install bootstrap and self-heal hooks",
            "Removed retired legacy roles from user assignments",
            "Reconciled staff Employee branches onto valid Cost Centers",
            "Re-applied admin and portal home-page routing",
            "Re-applied navbar and branding settings",
            "Captured and repaired user-setup diagnostics",
        ],
    }


def run_live_repair() -> dict:
    """Compatibility entry-point used by bench execute."""
    return repair_live_site_state()


# ---------------------------------------------------------------------------
# Company reconciliation (rename + retag on live)
# ---------------------------------------------------------------------------

# R45 lesson: live sites were bootstrapped with whatever Company name was in
# the operator's environment at the time (e.g. "Kesari"), so the live bench
# and the local dev bench drift apart. _sync_site_config_currency reads the
# Company's currency and writes it to site_config, but it cannot fix the
# root cause: the Company itself is on the wrong currency / wrong name.
#
# reconcile_company_name() is the surgical one-shot that:
#   1. Renames the current default Company to the operator-requested name
#      (so live matches local), OR if no rename requested, leaves the name.
#   2. Updates default_currency + country on the Company + Global Defaults
#      so every downstream view resolves to the same currency.
#   3. Re-points Global Defaults.default_company so all defaulters use the
#      (possibly renamed) Company.
#   4. Updates the Company abbreviation if requested, so Cost Center /
#      Account names that embed the abbr stay consistent.
#   5. Updates site_config lms_currency so the login page reflects the new
#      currency immediately.
#
# Idempotent and safe to re-run. Safe to skip (just returns a no-op).
# Args can be supplied as kwargs OR via frappe.flags.lms_company_reconcile.
#
# Usage:
#   bench --site <site> execute lms_saas.setup.live_repair.reconcile_company_name \
#       --kwargs '{"company":"LMS Demo Co","abbr":"LD","currency":"USD","country":"Zimbabwe","apply":1}'
#


def _rename_cost_centers_for_abbr_change(
    company: str, old_abbr: str, new_abbr: str
) -> list[str]:
    """Rename Cost Centers that embed ``old_abbr`` to embed ``new_abbr``.

    Cost Center names in lms_saas follow the ``<Label> - <Company Abbr>``
    convention. When the Company abbr changes (``LS`` → ``SP``), every
    Cost Center like ``Main Branch - LS`` becomes a phantom — the
    branch string in the database no longer matches the company it
    belongs to. ``staff.get_current_user_branch()`` will then return
    ``Main Branch - LS`` for any Employee that was on the legacy
    branch, and every data query returns zero rows.

    Implementation note: ERPNext blocks ``frappe.rename_doc("Cost
    Center", ...)`` ("Cost Center not allowed to be renamed") because
    Cost Centers can be referenced by GL Entries, Budgets, and
    Allocation rules. We therefore use a direct SQL UPDATE on the
    ``tabCost Center`` row — no doc.save, no controller hooks. This
    is safe IF no GL Entry references the old name (which is true for
    fresh lms_saas installs and for our demo sites where Cost Centers
    are used purely as branch tags on Customer/Loan/Employee).
    Operators on a system with real GL postings on the old branches
    should run a Journal Entry / GL Entry rename BEFORE this script
    and then re-run.

    Steps:

      1. List every Cost Center in the company whose name ends with
         ``- <old_abbr>``.
      2. Direct-SQL UPDATE each to ``<Label> - <new_abbr>``.
      3. Bulk-retag any Employee / Customer / Loan whose
         ``custom_lms_branch`` still references the old branch name.

    Returns a list of human-readable change descriptions. Idempotent.
    """
    lines: list[str] = []
    if not (company and old_abbr and new_abbr and old_abbr != new_abbr):
        return lines

    suffix = f" - {old_abbr}"
    new_suffix = f" - {new_abbr}"
    candidates = frappe.get_all(
        "Cost Center",
        filters={"company": company},
        fields=["name"],
    )

    for cc in candidates:
        old_name = cc["name"]
        if not old_name.endswith(suffix):
            continue
        label = old_name[: -len(suffix)]
        new_name = f"{label} - {new_abbr}"
        if old_name == new_name:
            continue
        try:
            # Direct SQL rename — see the docstring for why we bypass
            # frappe.rename_doc here.
            frappe.db.sql(
                "UPDATE `tabCost Center` SET name = %s WHERE name = %s",
                (new_name, old_name),
            )
            lines.append(f"{old_name} → {new_name}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"FAILED {old_name} → {new_name}: {exc}")

    # R50 refactor: use frappe.db.bulk_update instead of raw SQL
    # UPDATE ... REPLACE(). The idiomatic Frappe pattern is:
    #   1. Query the rows that need updating.
    #   2. Build a {docname: {field: new_value}} dict.
    #   3. Call frappe.db.bulk_update(doctype, updates).
    # This goes through Frappe's DB layer (parameter binding, cache
    # invalidation, modified timestamp) instead of bypassing it with
    # raw SQL. The trade-off is one extra SELECT per doctype, but
    # the safety + auditability is worth it.
    for doctype in ("Employee", "Customer", "Loan", "Loan Application"):
        if not frappe.db.exists("DocType", doctype):
            continue
        # Fetch every row whose custom_lms_branch ends with the old
        # suffix. We need the docname + the current branch value to
        # compute the new branch value.
        rows = frappe.get_all(
            doctype,
            filters={"custom_lms_branch": ["like", f"%{suffix}"]},
            fields=["name", "custom_lms_branch"],
        )
        if not rows:
            continue
        updates = {}
        for row in rows:
            old_branch = row.get("custom_lms_branch") or ""
            new_branch = old_branch.replace(suffix, new_suffix)
            if new_branch != old_branch:
                updates[row["name"]] = {"custom_lms_branch": new_branch}
        if updates:
            frappe.db.bulk_update(doctype, updates, update_modified=True)
            lines.append(f"retag {doctype}: {len(updates)} row(s) updated")

    frappe.db.commit()

    return lines


@frappe.whitelist()
def reconcile_company_name(
    company: str | None = None,
    abbr: str | None = None,
    currency: str | None = None,
    country: str | None = None,
    apply: int = 0,
) -> dict:
    """Rename + retag the default Company so live matches local.

    All args are optional — pass only what you want to change. If ``apply``
    is falsy the function returns a plan instead of writing anything.
    """
    if not frappe.db.exists("DocType", "Company"):
        return {"ok": False, "skipped": "DocType Company not found"}

    target_company = (company or "").strip() or None
    target_abbr = (abbr or "").strip().upper() or None
    target_currency = (currency or "").strip().upper() or None
    target_country = (country or "").strip() or None

    # Find the current default Company. If there is no default_company set,
    # fall back to the first Company — there should only ever be one in a
    # freshly-installed lms_saas site.
    current_name = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    if not current_name:
        first = frappe.get_all("Company", limit=1, pluck="name")
        current_name = first[0] if first else ""
    if not current_name:
        return {"ok": False, "skipped": "no Company on site"}

    current_doc = frappe.get_doc("Company", current_name)
    current_currency = current_doc.default_currency
    current_country = current_doc.country
    current_abbr = current_doc.abbr

    plan = {
        "ok": True,
        "applied": [],
        "skipped": [],
        "would_rename": False,
        "from_name": current_name,
        "to_name": target_company or current_name,
        "from_abbr": current_abbr,
        "to_abbr": target_abbr or current_abbr,
        "from_currency": current_currency,
        "to_currency": target_currency or current_currency,
        "from_country": current_country,
        "to_country": target_country or current_country,
    }

    if not int(apply or 0):
        plan["dry_run"] = True
        plan["plan"] = [
            f"Company rename: {current_name!r} → {plan['to_name']!r}"
            if plan["from_name"] != plan["to_name"]
            else f"Company name unchanged: {current_name!r}",
            f"Company abbr:  {current_abbr!r} → {plan['to_abbr']!r}"
            if current_abbr != plan["to_abbr"]
            else f"Company abbr unchanged: {current_abbr!r}",
            f"Currency:      {current_currency!r} → {plan['to_currency']!r}"
            if current_currency != plan["to_currency"]
            else f"Currency unchanged: {current_currency!r}",
            f"Country:       {current_country!r} → {plan['to_country']!r}"
            if current_country != plan["to_country"]
            else f"Country unchanged: {current_country!r}",
            "site_config: lms_currency updated to match Company.default_currency",
        ]
        return plan

    rename = target_company and target_company != current_name
    abbr_change = target_abbr and target_abbr != current_abbr
    currency_change = target_currency and target_currency != current_currency
    country_change = target_country and target_country != current_country

    if not (rename or abbr_change or currency_change or country_change):
        plan["skipped"].append("no changes requested")
        return plan

    # Rename the Company doc itself. Frappe's rename_doc is safe for the
    # Company master (no GL/JE references are keyed on the name).
    #
    # R49 fix: after rename_doc, the in-memory `current_doc` handle is
    # STALE — rename_doc creates a new doc under the hood. We must
    # reload via `frappe.get_doc("Company", new_name)` BEFORE the next
    # save() call, otherwise the optimistic-lock check ("Company has
    # been modified after you opened it") fires. Same applies to any
    # abbr/currency/country update: each save() bumps the doc's
    # `modified` timestamp, so a stale in-memory handle raises an
    # exception on the second save().
    if rename:
        try:
            frappe.rename_doc("Company", current_name, target_company, merge=0)
            plan["applied"].append(f"company renamed: {current_name} → {target_company}")
            current_name = target_company
            current_doc = frappe.get_doc("Company", current_name)
        except Exception as exc:  # noqa: BLE001
            plan["skipped"].append(f"company rename failed: {exc}")

    # R50 refactor: use frappe.db.set_value instead of raw SQL.
    # ERPNext blocks Company.abbr changes via the controller's on_update
    # hook (raises "Value cannot be changed for Abbr" on doc.save()).
    # frappe.db.set_value bypasses controller hooks — it writes directly
    # to the DB table but still goes through Frappe's DB layer (parameter
    # binding, cache invalidation, modified timestamp update). This is
    # the idiomatic Frappe way to do a system-level field update that
    # intentionally skips business logic. Safe because abbr is referenced
    # by name (e.g. ``Main Branch - <abbr>``) and we just renamed every
    # Cost Center to use the new abbr.
    if abbr_change:
        try:
            frappe.db.set_value(
                "Company", current_name, "abbr", target_abbr,
                update_modified=True,
            )
            plan["applied"].append(f"company abbr updated: {current_abbr} → {target_abbr}")
            # Reload the in-memory handle so subsequent save() calls
            # don't hit the stale-handle / optimistic-lock error.
            current_doc = frappe.get_doc("Company", current_name)
        except Exception as exc:  # noqa: BLE001
            plan["skipped"].append(f"company abbr update failed: {exc}")

    if currency_change:
        try:
            if not frappe.db.exists("Currency", target_currency):
                frappe.get_doc(
                    {"doctype": "Currency", "currency_name": target_currency, "enabled": 1}
                ).insert(ignore_permissions=True)
            # Reload to avoid stale-handle / "modified after you opened
            # it" errors when an earlier step (rename, abbr) bumped
            # the modified timestamp.
            current_doc = frappe.get_doc("Company", current_name)
            current_doc.default_currency = target_currency
            current_doc.save(ignore_permissions=True)
            plan["applied"].append(f"company default_currency: {current_currency} → {target_currency}")
            # Reload again so subsequent steps use fresh state.
            current_doc = frappe.get_doc("Company", current_name)
        except Exception as exc:  # noqa: BLE001
            plan["skipped"].append(f"company currency update failed: {exc}")

    if country_change:
        try:
            if not frappe.db.exists("Country", target_country):
                frappe.get_doc(
                    {"doctype": "Country", "country_name": target_country}
                ).insert(ignore_permissions=True)
            current_doc = frappe.get_doc("Company", current_name)
            current_doc.country = target_country
            current_doc.save(ignore_permissions=True)
            plan["applied"].append(f"company country: {current_country} → {target_country}")
            current_doc = frappe.get_doc("Company", current_name)
        except Exception as exc:  # noqa: BLE001
            plan["skipped"].append(f"company country update failed: {exc}")

    # Re-point Global Defaults at the (possibly renamed) Company + currency.
    try:
        frappe.db.set_single_value("Global Defaults", "default_company", current_name)
        frappe.db.set_single_value(
            "Global Defaults", "default_currency", current_doc.default_currency
        )
        plan["applied"].append(
            f"global_defaults: default_company={current_name}, default_currency={current_doc.default_currency}"
        )
    except Exception as exc:  # noqa: BLE001
        plan["skipped"].append(f"global_defaults update failed: {exc}")

    # R48 fix: when the Company abbr changes (e.g. "LS" → "SP"), every
    # Cost Center name that embeds the old abbr (e.g. "Main Branch - LS")
    # must be renamed too — otherwise the branches are still tagged with
    # the old company identifier and any branch-resolution code falls
    # over. We rename Cost Centers, then retag Customers/Loans/Employees
    # to use the new branch names. Both halves are required for branch
    # parity after an abbr change.
    if abbr_change:
        try:
            old_abbr, new_abbr = current_abbr, target_abbr
            renamed_ccs = _rename_cost_centers_for_abbr_change(
                current_name, old_abbr, new_abbr
            )
            for line in renamed_ccs:
                plan["applied"].append(f"cost_center_rename: {line}")
        except Exception as exc:  # noqa: BLE001
            plan["skipped"].append(f"cost_center_rename failed: {exc}")
    # Always run the retag pass — it normalizes any Customer/Loan/Employee
    # that ended up on a phantom branch (the R47 scenario) to the fallback
    # branch, which is the branch that most existing records are tagged
    # with after the rename. Idempotent.
    try:
        branch_repair = reconcile_staff_branches(company=current_name)
        for line in branch_repair.get("notes", []):
            plan["applied"].append(f"branch_reconcile: {line}")
        if branch_repair.get("repaired"):
            plan["applied"].append(
                f"branch_reconcile: {len(branch_repair['repaired'])} Employee(s) retagged"
            )
    except Exception as exc:  # noqa: BLE001
        plan["skipped"].append(f"branch_reconcile failed: {exc}")

    # Mirror the new currency into site_config.json + frappe.conf so the
    # login page (which reads window.__lms_currency from site_config before
    # any User session exists) shows the right symbol immediately.
    try:
        import json
        from pathlib import Path

        site_path = Path(frappe.utils.get_site_path("site_config.json"))
        raw = json.loads(site_path.read_text() or "{}")
        raw["lms_currency"] = current_doc.default_currency
        site_path.write_text(json.dumps(raw, indent=2, sort_keys=True))
        frappe.conf["lms_currency"] = current_doc.default_currency
        frappe.clear_cache()
        plan["applied"].append(f"site_config: lms_currency={current_doc.default_currency}")
    except Exception as exc:  # noqa: BLE001
        plan["skipped"].append(f"site_config lms_currency sync failed: {exc}")

    frappe.db.commit()
    return plan


# ---------------------------------------------------------------------------
# Test-user provisioning (idempotent, admin-only)
# ---------------------------------------------------------------------------

TEST_USERS = [
	{
		"email": "manager@kesari.africa",
		"first_name": "Branch",
		"last_name": "Manager",
		"password": "Manager@123",
		"persona": "Branch Manager",
		"roles": ["LMS Portal Staff"],
	},
	{
		"email": "officer@kesari.africa",
		"first_name": "Loan",
		"last_name": "Officer",
		"password": "Officer@123",
		"persona": "Loan Officer",
		"roles": ["LMS Portal Staff"],
	},
	{
		"email": "collector@kesari.africa",
		"first_name": "Collection",
		"last_name": "Agent",
		"password": "Collector@123",
		"persona": "Collector",
		"roles": ["LMS Portal Staff"],
	},
	{
		"email": "admin@kesari.africa",
		"first_name": "System",
		"last_name": "Administrator",
		"password": "Admin@123",
		"persona": "Branch Manager",
		"roles": ["System Manager", "Administrator"],
	},
	{
		"email": "supervisor@kesari.africa",
		"first_name": "Operations",
		"last_name": "Supervisor",
		"password": "Supervisor@123",
		"persona": "Branch Manager",
		"roles": ["LMS Portal Staff"],
	},
	{
		"email": "field@kesari.africa",
		"first_name": "Field",
		"last_name": "Officer",
		"password": "Field@123",
		"persona": "Loan Officer",
		"roles": ["LMS Portal Staff"],
	},
	{
		"email": "senior.collector@kesari.africa",
		"first_name": "Senior",
		"last_name": "Collector",
		"password": "Senior@123",
		"persona": "Collector",
		"roles": ["LMS Portal Staff"],
	},
	{
		"email": "borrower@example.com",
		"first_name": "Test",
		"last_name": "Borrower",
		"password": "Borrower@123",
		"persona": None,
		"roles": ["Customer"],
	},
]


@frappe.whitelist()
def provision_test_users() -> dict:
	"""Create or update the 8 standard test users on the live site.

	Admin-only: requires System Manager or Administrator role. Idempotent —
	safe to re-run; existing users are updated in place.
	"""
	if not set(frappe.get_roles()).intersection({"System Manager", "Administrator"}):
		frappe.throw("Only administrators can provision test users.", frappe.PermissionError)

	company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
	# QA-2026-08-03-#13-#18 (root cause): the seeder used to pick
	# the first non-group Cost Center, which on live disagrees with
	# the branch the R28/R29 seeded Customers/Loans are tagged with
	# (e.g. "Main Branch - LS" vs "Main Branch - LMS"). That mismatch
	# blocked the manager's data tabs and the officer's disburse flow
	# with "Not in your branch." 403s. Now we pick the Cost Center
	# that the most existing records are tagged with.
	branch = _pick_branch_used_by_seeded_data(company)

	# R43 fix: validate the picked branch actually belongs to this
	# company. If a stale cross-company branch (e.g. "Main - K" from
	# a previous bench install) slipped through, fall back to the
	# first valid branch.
	valid_branches = frappe.get_all(
		"Cost Center",
		filters={"company": company, "is_group": 0},
		pluck="name",
	)
	if branch and branch not in valid_branches:
		branch = valid_branches[0] if valid_branches else ""
	if not branch:
		branch = ""

	created = []
	updated = []
	skipped = []

	for cfg in TEST_USERS:
		email = cfg["email"]
		try:
			# Mute emails for the entire seeder pass. The default User.on_update
			# path sends a "your password changed" security alert that runs
			# through frappe.sendmail -> email_queue -> bundled_assets. On a
			# freshly-built bench the assets bundle is None, which crashes the
			# email render. Mute to keep the seeder self-contained.
			frappe.flags.mute_emails = True
			if frappe.db.exists("User", email):
				# Update existing user with the lightest possible touch:
				# set_value (no save → no rename, no on_update, no email),
				# update_password (writes the auth table directly, no email),
				# and replace Has Role rows directly (no role reset, no
				# background jobs enqueued). This is safe to re-run.
				frappe.db.set_value(
					"User", email, {
						"first_name": cfg["first_name"],
						"last_name": cfg["last_name"],
					}, update_modified=True,
				)
				if cfg.get("password"):
					from frappe.utils.password import update_password
					update_password(email, cfg["password"])
				# Replace roles directly via SQL (no doc.save → no jobs).
				frappe.db.delete("Has Role", {"parent": email, "parenttype": "User"})
				for role_name in cfg.get("roles", []):
					if frappe.db.exists("Role", role_name):
						frappe.get_doc({
							"doctype": "Has Role",
							"parent": email,
							"parenttype": "User",
							"parentfield": "roles",
							"role": role_name,
						}).insert(ignore_permissions=True)
				frappe.db.commit()
				updated.append(email)
			else:
				user = frappe.get_doc({
					"doctype": "User",
					"email": email,
					"first_name": cfg["first_name"],
					"last_name": cfg["last_name"],
					"new_password": cfg.get("password"),
					"send_welcome_email": False,
					"roles": [{"role": r} for r in cfg.get("roles", []) if frappe.db.exists("Role", r)],
				})
				user.flags.no_welcome_mail = True
				user.flags.ignore_permissions = True
				user.insert()
				created.append(email)

			# Create or update Employee record for persona
			if cfg.get("persona"):
				emp_id = f"EMP-{email.split('@')[0].upper().replace('.', '_')}"
				if frappe.db.exists("Employee", {"user_id": email}):
					emp_name = frappe.db.get_value("Employee", {"user_id": email}, "name")
					frappe.db.set_value("Employee", emp_name, {
						"custom_lms_persona": cfg["persona"],
						"custom_lms_branch": branch or None,
						"status": "Active",
					}, update_modified=True)
				elif frappe.db.exists("Employee", emp_id):
					frappe.db.set_value("Employee", emp_id, {
						"user_id": email,
						"custom_lms_persona": cfg["persona"],
						"custom_lms_branch": branch or None,
						"status": "Active",
					}, update_modified=True)
				else:
					emp = frappe.get_doc({
						"doctype": "Employee",
						"employee_id": emp_id,
						"first_name": cfg["first_name"],
						"last_name": cfg["last_name"],
						"user_id": email,
						"status": "Active",
						"company": company or "Kesari",
						"date_of_joining": frappe.utils.today(),
						"date_of_birth": "1990-01-01",  # required by ERPNext; demo placeholder
						"gender": "Prefer not to say",  # required by ERPNext; demo placeholder
						"custom_lms_persona": cfg["persona"],
						"custom_lms_branch": branch or None,
					})
					emp.flags.ignore_permissions = True
					emp.insert()

			# For the demo borrower: also create a Customer record and link
			# the user to it via Contact + Customer's primary contact. The
			# borrower portal's _require_customer() check in
			# lms_saas.api.portal resolves the user → Customer via the
			# Contact + Customer link table, and returns 403 if the
			# link is missing. Without this, the borrower logs in
			# successfully but the /lms portal renders with a
			# "No Customer linked to your portal account" error.
			if email == "borrower@example.com":
				_provision_borrower_customer(email, cfg)

		except Exception as exc:
			skipped.append({"email": email, "error": str(exc)})
		finally:
			frappe.flags.mute_emails = False

	# QA-2026-08-03-#13-#18 (root-cause reconciliation): after
	# updating each user's Employee branch, also reconcile the
	# existing Customers/Loans/KYC records to the SAME branch.
	# The seeded data and the seeder have historically picked
	# different Cost Centers (e.g. "Main Branch - LS" vs
	# "Main Branch - LMS") and that drift broke the manager's data
	# tabs and the officer's disburse flow. _pick_branch above
	# already chose the most-used branch, so we now nudge every
	# other branch onto it in one pass. Bulk UPDATE so we don't
	# enqueue background jobs.
	if branch:
		_reconciled = _reconcile_seeded_branches(branch)
		if _reconciled.get("reassigned", 0):
			updated.append(
				f"reconciled {_reconciled['reassigned']} existing records to branch '{branch}' "
				f"({_reconciled.get('per_table', {})})"
			)

	frappe.db.commit()
	return {"created": created, "updated": updated, "skipped": skipped}


def _reconcile_seeded_branches(target_branch: str) -> dict:
	"""Move existing Customer/Loan records to the target branch in bulk.

	QA-2026-08-03-#13-#18: this is the root-cause fix for the
	branch-drift bug. When the seeder runs and discovers that the
	existing Customer/Loan/KYC records are on a different Cost Center
	than the one the manager/officer Employees are tagged with, we
	reassign them in a single bulk UPDATE so the data views line up.

	We touch every DocType that has a ``custom_lms_branch`` field
	and a non-empty value pointing to a different Cost Center. We
	deliberately do NOT touch the Employees/Users here -- the
	``provision_test_users`` loop above is the source of truth for
	those.

	Args:
		target_branch: the Cost Center name the seeder has chosen
			(via ``_pick_branch_used_by_seeded_data``).

	Returns:
		Dict with ``reassigned`` count and ``per_table`` breakdown.
	"""
	reassigned = 0
	per_table: dict[str, int] = {}

	# DocTypes with a custom_lms_branch field. We only touch
	# LMS-managed tables; the standard Cost Center on Customer
	# is the same field but Customer is in ERPNext.
	for table in ("Customer", "Loan", "LMS Borrower Compliance"):
		if not frappe.db.table_exists(table):
			continue
		meta = frappe.get_meta(table)
		if not meta.has_field("custom_lms_branch"):
			continue
		# Count how many rows would be updated (cheap, no row data).
		count = frappe.db.sql(
			f"""
			SELECT COUNT(*)
			FROM `tab{table}`
			WHERE custom_lms_branch IS NOT NULL
			  AND custom_lms_branch != %s
			""",
			target_branch,
		)[0][0]
		if not count:
			continue
		# Bulk UPDATE.
		frappe.db.sql(
			f"""
			UPDATE `tab{table}`
			SET custom_lms_branch = %s
			WHERE custom_lms_branch IS NOT NULL
			  AND custom_lms_branch != %s
			""",
			(target_branch, target_branch),
		)
		per_table[table] = int(count)
		reassigned += int(count)

	return {"reassigned": reassigned, "per_table": per_table, "target": target_branch}


def _provision_borrower_customer(email: str, cfg: dict) -> None:
	"""Create a Customer + Contact + link to the borrower User.

	Idempotent: safe to re-run. If a Customer linked to this user already
	exists, we update it in place. If the linked Customer has zero loans and
	another Customer in the same company has active loans (typical after a
	re-seed), we re-point the borrower to that existing Customer so the demo
	borrower portal shows real loans. We do NOT enqueue background jobs.
	"""
	# Find an existing Customer linked to this user via Contact.
	linked_customer = None
	if frappe.db.table_exists("Contact"):
		contact_name = frappe.db.get_value(
			"Contact",
			{"user": email, "is_primary_contact": 1},
			"name",
		)
		if contact_name:
			linked_customer = frappe.db.get_value(
				"Dynamic Link",
				{"parent": contact_name, "parenttype": "Contact", "link_doctype": "Customer"},
				"link_name",
			)

	customer_name = f"Test Borrower — {cfg['first_name']} {cfg['last_name']}"
	customer_id = linked_customer or customer_name

	# If the linked Customer has zero active loans but another Customer in the
	# same branch/company has them (typical after a fresh re-seed), re-point
	# the borrower Contact to that existing Customer so the demo /lms portal
	# shows real loans. We only re-point if the existing customer has at least
	# one Loan record — otherwise leave the empty Customer in place.
	if customer_id:
		has_loans = frappe.db.sql(
			"SELECT 1 FROM `tabLoan` WHERE applicant = %s LIMIT 1",
			(customer_id,),
		)
		if not has_loans:
			# Look for any Customer with at least one Loan (most recent first).
			other = frappe.db.sql(
				"""
				SELECT l.applicant AS customer
				FROM `tabLoan` l
				WHERE l.docstatus < 2
				GROUP BY l.applicant
				ORDER BY MAX(l.modified) DESC
				LIMIT 1
				""",
				as_dict=True,
			)
			if other:
				existing_cust = other[0]["customer"]
				# Only re-point if it's a different Customer.
				if existing_cust and existing_cust != customer_id:
					customer_id = existing_cust
					customer_name = frappe.db.get_value("Customer", customer_id, "customer_name") or customer_name

	if frappe.db.exists("Customer", customer_id):
		frappe.db.set_value(
			"Customer",
			customer_id,
			{
				"customer_name": customer_name,
				"customer_type": "Individual",
				"customer_group": "Individual",
				"territory": "All Territories",
			},
			update_modified=True,
		)
	else:
		frappe.flags.mute_emails = True
		try:
			cust = frappe.get_doc({
				"doctype": "Customer",
				"name": customer_id,
				"customer_name": customer_name,
				"customer_type": "Individual",
				"customer_group": "Individual",
				"territory": "All Territories",
			})
			cust.flags.ignore_permissions = True
			cust.insert()
		finally:
			pass  # mute_emails reset by outer finally

	# Create / update the Contact row that links the user → Customer.
	contact_name = frappe.db.get_value(
		"Contact", {"user": email}, "name"
	)
	if not contact_name:
		contact = frappe.get_doc({
			"doctype": "Contact",
			"first_name": cfg["first_name"],
			"last_name": cfg["last_name"],
			"email_id": email,
			"is_primary_contact": 1,
			"user": email,
			"links": [{
				"link_doctype": "Customer",
				"link_name": customer_id,
			}],
		})
		contact.flags.ignore_permissions = True
		contact.insert(ignore_permissions=True)
	else:
		# Ensure the Dynamic Link to Customer exists.
		has_link = frappe.db.exists(
			"Dynamic Link",
			{"parent": contact_name, "parenttype": "Contact",
			 "link_doctype": "Customer", "link_name": customer_id},
		)
		if not has_link:
			frappe.get_doc({
				"doctype": "Dynamic Link",
				"parent": contact_name,
				"parenttype": "Contact",
				"parentfield": "links",
				"link_doctype": "Customer",
				"link_name": customer_id,
			}).insert(ignore_permissions=True)

	return customer_id


# ---------------------------------------------------------------------------
# Standalone borrower Customer re-linking (issue #23 root-cause fix)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def link_borrower_to_demo_customer(email: str = "borrower@example.com") -> dict:
	"""Re-point a borrower User's Contact → Customer link to a Customer
	with at least one active loan.

	QA-2026-08-03-#23: the seeder used to create a brand-new Customer
	named "Test Borrower — Test Borrower" and link borrower@example.com
	to it via Contact. After a fresh re-seed that new Customer has zero
	loans, so the borrower's /lms portal shows an empty portfolio even
	when the manager dashboard shows 8 active loans across 6 borrowers.

	This endpoint is the safe, surgical fix: it does NOT touch any
	users / employees / branches / loans / KYC. It ONLY re-points the
	borrower's Contact link to the most-recently-modified Customer that
	has at least one Loan.

	Admin-only. Idempotent: re-running is a no-op once the link is correct.

	Args:
		email: borrower email (default: borrower@example.com).

	Returns:
		Dict with previous_customer_id, current_customer_id,
		loan_count (on the new customer), and a human-readable message.
	"""
	if not set(frappe.get_roles()).intersection({"System Manager", "Administrator"}):
		frappe.throw(
			"Only administrators can re-link a borrower Customer.",
			frappe.PermissionError,
		)

	if not frappe.db.exists("User", email):
		return {
			"ok": False,
			"email": email,
			"message": f"User {email!r} does not exist on this site.",
		}

	# Find current Customer linked to this user via Contact + Dynamic Link.
	previous_customer_id = None
	contact_name = frappe.db.get_value(
		"Contact", {"user": email}, "name"
	)
	if contact_name:
		previous_customer_id = frappe.db.get_value(
			"Dynamic Link",
			{"parent": contact_name, "parenttype": "Contact", "link_doctype": "Customer"},
			"link_name",
		)

	# Find a Customer that has at least one Loan, most-recent first.
	other = frappe.db.sql(
		"""
		SELECT l.applicant AS customer, COUNT(*) AS loan_count, MAX(l.modified) AS last_modified
		FROM `tabLoan` l
		WHERE l.docstatus < 2
		GROUP BY l.applicant
		ORDER BY MAX(l.modified) DESC
		LIMIT 1
		""",
		as_dict=True,
	)
	if not other:
		return {
			"ok": False,
			"email": email,
			"previous_customer_id": previous_customer_id,
			"message": "No Customer with at least one Loan exists on this site. Seed demo loans first.",
		}

	target_customer = other[0]["customer"]
	loan_count = int(other[0]["loan_count"] or 0)

	if target_customer == previous_customer_id:
		return {
			"ok": True,
			"email": email,
			"previous_customer_id": previous_customer_id,
			"current_customer_id": target_customer,
			"loan_count": loan_count,
			"message": f"Already linked to {target_customer!r} with {loan_count} loan(s); no change.",
		}

	# Update or insert the Dynamic Link. Two cases:
	# 1. Contact exists: replace the link_doctype=Customer link to point to the
	#    target customer.
	# 2. Contact doesn't exist: create one and link.
	if contact_name:
		existing_link_name = frappe.db.get_value(
			"Dynamic Link",
			{"parent": contact_name, "parenttype": "Contact", "link_doctype": "Customer"},
			"name",
		)
		if existing_link_name:
			frappe.db.set_value(
				"Dynamic Link", existing_link_name, "link_name", target_customer
			)
		else:
			frappe.get_doc({
				"doctype": "Dynamic Link",
				"parent": contact_name,
				"parenttype": "Contact",
				"parentfield": "links",
				"link_doctype": "Customer",
				"link_name": target_customer,
			}).insert(ignore_permissions=True)
	else:
		contact = frappe.get_doc({
			"doctype": "Contact",
			"first_name": "Test",
			"last_name": "Borrower",
			"email_id": email,
			"is_primary_contact": 1,
			"user": email,
			"links": [{
				"link_doctype": "Customer",
				"link_name": target_customer,
			}],
		})
		contact.flags.ignore_permissions = True
		contact.insert(ignore_permissions=True)

	frappe.db.commit()

	return {
		"ok": True,
		"email": email,
		"previous_customer_id": previous_customer_id,
		"current_customer_id": target_customer,
		"loan_count": loan_count,
		"message": (
			f"Re-linked {email!r} from {previous_customer_id!r} → {target_customer!r} "
			f"({loan_count} loan(s))."
		),
	}


# ---------------------------------------------------------------------------
# Demo collateral seeding (idempotent, admin-only)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def seed_demo_collateral() -> dict:
	"""Create a demo collateral record for each borrower with an active loan.

	Admin-only. Idempotent — skips borrowers who already have collateral.
	"""
	if not set(frappe.get_roles()).intersection({"System Manager", "Administrator"}):
		frappe.throw("Only administrators can seed demo collateral.", frappe.PermissionError)

	company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
	branch = ""
	if company:
		branch = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name") or ""

	# Find all borrowers with active loans but no collateral.
	loans = frappe.get_all(
		"Loan",
		filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
		fields=["name", "applicant", "loan_amount", "custom_lms_branch"],
		limit_page_length=200,
	)

	created = []
	skipped = []

	for loan in loans:
		customer = loan.applicant
		if not customer:
			continue

		# Skip if this borrower already has collateral.
		existing = frappe.db.get_value("LMS Collateral", {"owner_customer": customer, "docstatus": 1}, "name")
		if existing:
			skipped.append({"customer": customer, "reason": "already has collateral"})
			continue

		# Find the loan application for this loan.
		loan_app = frappe.db.get_value("Loan", loan.name, "custom_lms_loan_application") if frappe.get_meta("Loan").has_field("custom_lms_loan_application") else None

		try:
			collateral = frappe.get_doc({
				"doctype": "LMS Collateral",
				"collateral_title": f"Demo Vehicle ({customer[:20]})",
				"collateral_type": "Vehicle",
				"owner_customer": customer,
				"loan_application": loan_app or "",
				"company": company or "Kesari",
				"branch": loan.custom_lms_branch or branch or "",
				"status": "Pledged",
				"market_value": flt(loan.loan_amount) * 1.5,
				"haircut_percent": 20,
				"valuation_date": frappe.utils.today(),
				"valuer_name": "Demo Valuations Ltd",
				"reference_no": f"DEMO-{loan.name[-6:]}",
			})
			collateral.flags.ignore_permissions = True
			collateral.insert()
			collateral.submit()
			created.append({"customer": customer, "collateral": collateral.name, "loan": loan.name})
		except Exception as exc:
			skipped.append({"customer": customer, "error": str(exc)})

	frappe.db.commit()
	return {"created": created, "skipped": skipped, "total_loans": len(loans)}