"""Savings Club addon API — group savings goals, deposits, withdrawals, statements.

Reuses existing ``LMS Savings Account`` and ``LMS Savings Transaction``
doctypes. Adds the new ``LMS Savings Goal`` doctype for group target tracking.
Borrowers see their own accounts; staff see branch-scoped accounts.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, today, now_datetime

from lms_saas.utils.addons import require_addon_persona


# ---------------------------------------------------------------------------
# Guards & helpers
# ---------------------------------------------------------------------------

def _require_savings():
    require_addon_persona("savings_club")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


def _current_customer():
    """Resolve the Customer linked to the current user (for borrowers)."""
    from lms_saas.permissions import _portal_customer
    return _portal_customer(frappe.session.user)


def _is_borrower():
    from lms_saas.utils.portal import is_portal_borrower
    return is_portal_borrower()


# ---------------------------------------------------------------------------
# Savings Accounts
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_savings_accounts(limit=50):
    """List LMS Savings Accounts for the current borrower or branch."""
    _require_savings()

    if _is_borrower():
        customer = _current_customer()
        if not customer:
            return {"accounts": []}
        filters = {"customer": customer}
    else:
        # Staff: branch-scoped via lending group's branch
        branch = _branch()
        if branch and not _is_admin():
            # Get lending groups in this branch
            groups = frappe.get_all("LMS Lending Group", filters={"branch": branch}, pluck="name")
            if groups:
                filters = {"lending_group": ("in", groups)}
            else:
                filters = {}
        else:
            filters = {}

    accounts = frappe.get_all(
        "LMS Savings Account",
        filters=filters,
        fields=[
            "name", "customer", "lending_group", "company",
            "balance", "status",
        ],
        order_by="creation desc",
        limit_page_length=int(limit),
    )

    # Enrich with customer names
    for acc in accounts:
        if acc.get("customer"):
            acc["customer_name"] = frappe.db.get_value("Customer", acc["customer"], "customer_name") or ""
        if acc.get("lending_group"):
            acc["group_name"] = frappe.db.get_value("LMS Lending Group", acc["lending_group"], "group_name") or ""

    return {"accounts": accounts}


@frappe.whitelist()
def get_savings_detail(account_name):
    """Return a single savings account with its transactions."""
    _require_savings()

    if not frappe.db.exists("LMS Savings Account", account_name):
        frappe.throw(_("Savings account {0} not found.").format(account_name))

    account = frappe.get_doc("LMS Savings Account", account_name)

    # Borrower can only see their own account
    if _is_borrower():
        customer = _current_customer()
        if account.customer != customer:
            frappe.throw(_("Not permitted"), frappe.PermissionError)

    transactions = frappe.get_all(
        "LMS Savings Transaction",
        filters={"savings_account": account_name, "docstatus": 1},
        fields=["name", "transaction_type", "amount", "posting_date", "reference_journal_entry"],
        order_by="posting_date desc",
        limit_page_length=200,
    )

    return {
        "account": {
            "name": account.name,
            "customer": account.customer,
            "customer_name": frappe.db.get_value("Customer", account.customer, "customer_name") if account.customer else "",
            "lending_group": account.lending_group,
            "group_name": frappe.db.get_value("LMS Lending Group", account.lending_group, "group_name") if account.lending_group else "",
            "company": account.company,
            "balance": flt(account.balance),
            "status": account.status,
        },
        "transactions": transactions,
    }


# ---------------------------------------------------------------------------
# Deposits & Withdrawals
# ---------------------------------------------------------------------------

@frappe.whitelist()
def make_deposit(account_name, amount, posting_date=None):
    """Create a LMS Savings Transaction (Deposit) and update the account balance."""
    _require_savings()

    if not frappe.db.exists("LMS Savings Account", account_name):
        frappe.throw(_("Savings account {0} not found.").format(account_name))

    account = frappe.get_doc("LMS Savings Account", account_name)

    # Borrower can only deposit to their own account
    if _is_borrower():
        customer = _current_customer()
        if account.customer != customer:
            frappe.throw(_("Not permitted"), frappe.PermissionError)

    amount = flt(amount)
    if amount <= 0:
        frappe.throw(_("Deposit amount must be positive."))

    txn = frappe.new_doc("LMS Savings Transaction")
    txn.savings_account = account_name
    txn.transaction_type = "Deposit"
    txn.amount = amount
    txn.posting_date = posting_date or today()
    txn.flags.ignore_permissions = True
    txn.insert()
    txn.submit()

    # Update account balance
    account.reload()
    account.balance = flt(account.balance) + amount
    account.flags.ignore_permissions = True
    account.save()

    return {"name": txn.name, "new_balance": flt(account.balance)}


@frappe.whitelist()
def request_withdrawal(account_name, amount, notes=None):
    """Create a withdrawal request as a ToDo for staff approval."""
    _require_savings()

    if not frappe.db.exists("LMS Savings Account", account_name):
        frappe.throw(_("Savings account {0} not found.").format(account_name))

    account = frappe.get_doc("LMS Savings Account", account_name)

    # Borrower can only withdraw from their own account
    if _is_borrower():
        customer = _current_customer()
        if account.customer != customer:
            frappe.throw(_("Not permitted"), frappe.PermissionError)

    amount = flt(amount)
    if amount <= 0:
        frappe.throw(_("Withdrawal amount must be positive."))

    if flt(account.balance) < amount:
        frappe.throw(_("Insufficient savings balance."))

    # Create a ToDo for staff to process the withdrawal
    todo = frappe.new_doc("ToDo")
    todo.description = _("Savings withdrawal request: {0} from account {1}").format(
        frappe.format_value(amount, {"fieldtype": "Currency"}),
        account_name,
    )
    if notes:
        todo.description += f"\n\nNotes: {notes}"
    todo.reference_type = "LMS Savings Account"
    todo.reference_name = account_name
    todo.allocated_to = account.owner or frappe.session.user
    todo.flags.ignore_permissions = True
    todo.insert()

    return {"todo": todo.name, "message": _("Withdrawal request submitted for approval.")}


# ---------------------------------------------------------------------------
# Savings Goals
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_savings_goals(lending_group=None, limit=50):
    """Return savings goals for a group (or all goals for admins)."""
    _require_savings()

    filters = {}
    if lending_group:
        filters["lending_group"] = lending_group
    elif _is_borrower():
        # Borrower: show goals for groups they belong to
        customer = _current_customer()
        if customer:
            # Find lending groups where the customer is a member
            group_members = frappe.get_all(
                "LMS Group Member",
                filters={"customer": customer},
                pluck="parent",
            )
            if group_members:
                filters["lending_group"] = ("in", group_members)
            else:
                return {"goals": []}
        else:
            return {"goals": []}
    elif not _is_admin():
        # Staff: branch-scoped
        branch = _branch()
        if branch:
            groups = frappe.get_all("LMS Lending Group", filters={"branch": branch}, pluck="name")
            if groups:
                filters["lending_group"] = ("in", groups)

    goals = frappe.get_all(
        "LMS Savings Goal",
        filters=filters,
        fields=["name", "lending_group", "target_amount", "target_date",
                "current_balance", "status", "company"],
        order_by="creation desc",
        limit_page_length=int(limit),
    )

    for goal in goals:
        if goal.get("lending_group"):
            goal["group_name"] = frappe.db.get_value("LMS Lending Group", goal["lending_group"], "group_name") or ""
            goal["progress"] = (
                flt(goal["current_balance"]) / flt(goal["target_amount"]) * 100
                if goal["target_amount"] else 0
            )

    return {"goals": goals}


@frappe.whitelist()
def create_savings_goal(lending_group, target_amount, target_date, company=None):
    """Set a savings target for a lending group."""
    _require_savings()

    if not _is_admin():
        # Staff can create goals for groups in their branch
        branch = _branch()
        if branch:
            group_branch = frappe.db.get_value("LMS Lending Group", lending_group, "branch")
            if group_branch and group_branch != branch:
                frappe.throw(_("You can only create goals for groups in your branch."), frappe.PermissionError)
        # Borrowers cannot create goals
        if _is_borrower():
            frappe.throw(_("Only staff can create savings goals."), frappe.PermissionError)

    target_amount = flt(target_amount)
    if target_amount <= 0:
        frappe.throw(_("Target amount must be positive."))

    if not company:
        company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_default("company")

    doc = frappe.new_doc("LMS Savings Goal")
    doc.lending_group = lending_group
    doc.target_amount = target_amount
    doc.target_date = target_date
    doc.company = company
    doc.current_balance = 0
    doc.status = "Active"
    doc.flags.ignore_permissions = True
    doc.insert()

    return {"name": doc.name, "target_amount": flt(doc.target_amount)}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_savings_stats():
    """Summary stats for the savings club dashboard."""
    _require_savings()

    if _is_borrower():
        customer = _current_customer()
        if not customer:
            return {"total_saved": 0, "active_accounts": 0, "goals": 0}
        filters = {"customer": customer}
    else:
        branch = _branch()
        if branch and not _is_admin():
            groups = frappe.get_all("LMS Lending Group", filters={"branch": branch}, pluck="name")
            if groups:
                filters = {"lending_group": ("in", groups)}
            else:
                filters = {}
        else:
            filters = {}

    accounts = frappe.get_all(
        "LMS Savings Account",
        filters={**filters, "status": "Active"},
        fields=["balance"],
    )
    total_saved = sum(flt(a.balance) for a in accounts)

    goal_filters = {}
    if _is_borrower():
        customer = _current_customer()
        if customer:
            group_members = frappe.get_all("LMS Group Member", filters={"customer": customer}, pluck="parent")
            if group_members:
                goal_filters["lending_group"] = ("in", group_members)
    elif not _is_admin() and branch:
        groups = frappe.get_all("LMS Lending Group", filters={"branch": branch}, pluck="name")
        if groups:
            goal_filters["lending_group"] = ("in", groups)

    active_goals = frappe.db.count("LMS Savings Goal", {**goal_filters, "status": "Active"})

    return {
        "total_saved": flt(total_saved),
        "active_accounts": len(accounts),
        "goals": active_goals,
    }