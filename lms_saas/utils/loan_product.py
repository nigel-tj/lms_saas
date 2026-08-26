"""R52: Shared Loan Product helpers.

Extracted from ``install.py`` + ``scripts/bootstrap_loan_product.py``
so both ``install.after_install`` and ``api.setup.create_loan_product_draft``
use the same account-resolution + offset-order logic. The previous copy
in install.py is preserved (it stays as the seeder; the bootstrap script
also keeps its own copy so the script is runnable without the app
loaded). This module is the canonical source for the api.setup path.

The helpers here are intentionally defensive: they never raise on missing
accounts (the caller decides how to surface the gap). The loan-product
controller in the lending app is the only thing that refuses to save a
Loan Product without GL accounts; we mirror that contract by surfacing
``None`` when any required account is missing.
"""

from __future__ import annotations

from typing import Optional

import frappe


# Standard offset sequence for LMS-Standard loans. Matches the order the
# lending app's controller expects (Penalty → Interest → Principal).
STANDARD_OFFSET_ORDER_TITLE = "Standard Collection Offset Order"

REQUIRED_GL_FIELDS = (
    "disbursement_account",
    "loan_account",
    "interest_income_account",
    "interest_receivable_account",
    "penalty_income_account",
    "penalty_receivable_account",
)


def _resolve_account(company: str, **filters) -> Optional[str]:
    """Return the first Account matching the filters, or None.

    Special filter ``account_name_contains`` is translated into a LIKE
    against the ``account_name`` column (Frappe's DB layer does not
    accept arbitrary column names as kwarg filters).
    """
    base = {"company": company, "is_group": 0}
    name_contains = filters.pop("account_name_contains", None)
    qb_filters = {**base, **filters}
    if name_contains is not None:
        # Use frappe.qb for the LIKE so the value is escaped properly.
        Account = frappe.qb.DocType("Account")
        query = (
            frappe.qb.from_(Account)
            .select(Account.name)
            .where(Account.company == company)
            .where(Account.is_group == 0)
            .where(Account.account_name.like(f"%{name_contains}%"))
        )
        for key, value in filters.items():
            query = query.where(getattr(Account, key) == value)
        result = query.run(as_dict=False)
        if result:
            return result[0][0]
        return None
    return frappe.db.get_value("Account", qb_filters, "name")


def _configured_account(key: str, company: str) -> Optional[str]:
    """Read an account override from site_config, validated to exist."""
    name = frappe.conf.get(key)
    if name and frappe.db.exists("Account", {"name": name, "company": company}):
        return name
    if name:
        frappe.log_error(
            title="LMS GL config",
            message=(
                f"Configured account '{name}' ({key}) not found for {company}"
            ),
        )
    return None


def resolve_gl_accounts(company: str) -> Optional[dict]:
    """Resolve the GL accounts the Loan Product needs for ``company``.

    Returns ``None`` if any required account is missing (the caller is
    expected to surface the gap to the ops manager — typically by
    flagging the change request ``Pending — Missing GL Accounts``).
    """
    if not company or not frappe.db.exists("Company", company):
        return None

    loan_account = (
        _configured_account("lms_loan_account", company)
        or _resolve_account(company, account_type="Receivable")
        or _resolve_account(company, account_name_contains="Debtors")
    )
    # Interest income: try Income-root accounts (some fresh installs ship
    # Interest Income with account_type blank under root_type=Income).
    income = (
        _configured_account("lms_interest_income_account", company)
        or _resolve_account(company, account_type="Income")
        or _resolve_account(company, root_type="Income", account_name_contains="Interest Income")
        or _resolve_account(company, root_type="Income", account_name_contains="Indirect Income")
        or _resolve_account(company, root_type="Income")
    )
    bank = (
        _configured_account("lms_disbursement_account", company)
        or _resolve_account(company, account_type="Cash")
        or _resolve_account(company, account_type="Bank")
        or _resolve_account(company, account_name_contains="Cash")
    )
    mop = frappe.db.get_value("Mode of Payment", {}, "name")
    receivable = loan_account

    if not (loan_account and bank and income):
        frappe.log_error(
            title="LMS GL mapping incomplete",
            message=(
                f"company={company} loan_account={loan_account} bank={bank} "
                f"income={income}. Set lms_loan_account / "
                f"lms_interest_income_account / lms_disbursement_account "
                f"in site_config."
            ),
        )
        return None

    return {
        "mode_of_payment": mop or "Cash",
        "disbursement_account": bank,
        "payment_account": bank,
        "loan_account": loan_account,
        "interest_income_account": income,
        "interest_receivable_account": receivable,
        "penalty_income_account": income,
        "penalty_receivable_account": receivable,
    }


def ensure_offset_order(
    company: str,
    title: str = STANDARD_OFFSET_ORDER_TITLE,
) -> Optional[str]:
    """Create the Loan Demand Offset Order if missing, and bind it to
    ``company`` (Company-side fields) + return its name.

    Returns the order name, or None if the lending app's offset doctype
    isn't installed.
    """
    if not frappe.db.exists("DocType", "Loan Demand Offset Order"):
        return None
    existing = frappe.db.exists("Loan Demand Offset Order", {"title": title})
    if existing:
        order_name = existing
    else:
        doc = frappe.get_doc(
            {
                "doctype": "Loan Demand Offset Order",
                "title": title,
                "components": [
                    {"demand_type": "Principal"},
                    {"demand_type": "Interest"},
                    {"demand_type": "Penalty"},
                    {"demand_type": "Charges"},
                ],
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        order_name = doc.name

    # Bind on the Company too — lending v15+ requires the Company to
    # carry the offset for each asset class.
    for field in (
        "collection_offset_sequence_for_standard_asset",
        "collection_offset_sequence_for_sub_standard_asset",
        "collection_offset_sequence_for_written_off_asset",
        "collection_offset_sequence_for_settlement_collection",
    ):
        if not frappe.db.get_value("Company", company, field):
            frappe.db.set_value("Company", company, field, order_name)
    return order_name


def apply_offset_order_to_product(product_name: str, order_name: str) -> None:
    """Mirror the offset sequences onto a Loan Product row."""
    for field in (
        "collection_offset_sequence_for_standard_asset",
        "collection_offset_sequence_for_sub_standard_asset",
        "collection_offset_sequence_for_written_off_asset",
        "collection_offset_sequence_for_settlement_collection",
    ):
        if not frappe.db.get_value("Loan Product", product_name, field):
            frappe.db.set_value("Loan Product", product_name, field, order_name)


def missing_gl_accounts(accounts: Optional[dict]) -> list:
    """Return the list of REQUIRED_GL_FIELDS whose value is missing or
    empty in ``accounts``. Used to build the GL wiring notes for the
    change request."""
    if not accounts:
        return list(REQUIRED_GL_FIELDS)
    return [k for k in REQUIRED_GL_FIELDS if not accounts.get(k)]
