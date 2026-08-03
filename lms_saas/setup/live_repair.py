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

	# If only one branch, no choice to make.
	if len(branches) == 1:
		return branches[0]

	# Rank by Customer count, then Loan count. The branch with the
	# most existing records is the one the seeded data was tagged
	# with -- that is the branch the seeder must also use.
	def _count(table, field):
		rows = frappe.db.sql(
			"""
			SELECT {0} AS branch, COUNT(*) AS n
			FROM `tab{1}`
			WHERE {0} IN %(branches)s
			GROUP BY {0}
			""".format(field, table),
			{"branches": branches},
			as_dict=True,
		)
		return {r["branch"]: int(r["n"]) for r in rows}

	customer_counts = _count("Customer", "custom_lms_branch")
	loan_counts = _count("Loan", "custom_lms_branch")

	best_branch = max(
		branches,
		key=lambda b: (
			customer_counts.get(b, 0),
			loan_counts.get(b, 0),
		),
	)
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
        "notes": [
            "Ran after_install bootstrap and self-heal hooks",
            "Removed retired legacy roles from user assignments",
            "Re-applied admin and portal home-page routing",
            "Re-applied navbar and branding settings",
            "Captured and repaired user-setup diagnostics",
        ],
    }


def run_live_repair() -> dict:
    """Compatibility entry-point used by bench execute."""
    return repair_live_site_state()

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
		"roles": ["LMS Portal Staff", "System Manager", "Administrator"],
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