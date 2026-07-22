"""Procurement addon API — purchase requests, orders, suppliers, spend stats.

Reuses ERPNext doctypes: Material Request, Purchase Order, Supplier.
Branch-scoped via Cost Center / Branch on the document.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, getdate, now_datetime, get_first_day, get_last_day

from lms_saas.utils.addons import require_addon_persona


def _require_procurement():
    require_addon_persona("procurement")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


def _branch_employees(branch=None):
    """Return Employee names for the given branch (or current user's branch)."""
    branch = branch or _branch()
    if not branch:
        return []

    meta = frappe.get_meta("Employee")
    filters = {"status": "Active"}
    for field in ("branch", "cost_center", "custom_lms_branch"):
        if meta.has_field(field):
            filters[field] = branch
            break
    return frappe.get_all("Employee", filters=filters, pluck="name")


def _branch_cost_center():
    """Resolve the cost center for the current user's branch."""
    branch = _branch()
    if not branch:
        return None
    # The branch itself may be a cost center, or we look it up
    if frappe.db.exists("Cost Center", branch):
        return branch
    # Try to find a cost center matching the branch name
    meta = frappe.get_meta("Cost Center")
    if meta.has_field("branch"):
        cc = frappe.db.get_value("Cost Center", {"branch": branch, "is_group": 0}, "name")
        if cc:
            return cc
    return branch  # Fall back to branch as the filter value


def _has_table(doctype: str) -> bool:
    """True if a Frappe table exists for the DocType.

    ``frappe.db.table_exists`` expects the DocType name (it prefixes ``tab``
    itself). Passing ``tabMaterial Request`` incorrectly looks for
    ``tabtabMaterial Request`` and always returns False.
    """
    try:
        name = (doctype or "").strip()
        if name.startswith("tab"):
            name = name[3:]
        return bool(name and frappe.db.table_exists(name))
    except Exception:
        return False


def _missing_doctype_response(doctype: str) -> dict:
    return {
        "_missing": True,
        "_missing_doctype": doctype,
        "message": _(
            "The {0} module is not ready on this site "
            "(DocType missing or database tables not created). "
            "Ask a System Manager to enable ERPNext Buying and run a standard bench migrate."
        ).format(doctype),
        "requests": [],
        "orders": [],
        "suppliers": [],
        "total_spend_this_month": 0,
        "total_orders_this_month": 0,
        "pending_requests": 0,
        "supplier_count": 0,
        "monthly_spend": [],
        "spend_by_supplier": [],
    }


# ---------------------------------------------------------------------------
# Purchase Requests (Material Requests)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_purchase_requests(limit=100):
    """List Material Requests for the branch."""
    _require_procurement()

    if not _has_table("Material Request"):
        return _missing_doctype_response("Material Request")

    filters = {}
    cost_center = _branch_cost_center()
    if cost_center and not _is_admin():
        meta = frappe.get_meta("Material Request")
        for field in ("cost_center", "branch", "custom_lms_branch"):
            if meta.has_field(field):
                filters[field] = cost_center
                break

    meta = frappe.get_meta("Material Request")
    wanted = ["name", "status", "transaction_date", "company"]
    for field in ("material_request_type", "per_ordered", "total_req_qty", "schedule_date"):
        if meta.has_field(field):
            wanted.append(field)

    try:
        requests = frappe.get_all(
            "Material Request",
            filters=filters,
            fields=wanted,
            order_by="transaction_date desc",
            limit_page_length=int(limit),
        )
    except Exception:
        frappe.log_error(title="LMS procurement requests query failed", message=frappe.get_traceback())
        return _missing_doctype_response("Material Request")
    return {"requests": requests}


# ---------------------------------------------------------------------------
# Purchase Orders
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_purchase_orders(limit=100):
    """List Purchase Orders for the branch."""
    _require_procurement()

    if not _has_table("Purchase Order"):
        return _missing_doctype_response("Purchase Order")

    filters = {"docstatus": ["!=", 2]}
    cost_center = _branch_cost_center()
    if cost_center and not _is_admin():
        meta = frappe.get_meta("Purchase Order")
        for field in ("cost_center", "branch", "custom_lms_branch"):
            if meta.has_field(field):
                filters[field] = cost_center
                break

    orders = frappe.get_all(
        "Purchase Order",
        filters=filters,
        fields=["name", "supplier", "supplier_name", "status", "transaction_date",
                "company", "total", "net_total", "grand_total",
                "per_received", "per_billed"],
        order_by="transaction_date desc",
        limit_page_length=int(limit),
    )
    return {"orders": orders}


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_suppliers(limit=200):
    """Return approved suppliers list."""
    _require_procurement()

    if not _has_table("Supplier"):
        return _missing_doctype_response("Supplier")

    suppliers = frappe.get_all(
        "Supplier",
        filters={"disabled": 0},
        fields=["name", "supplier_name", "supplier_group", "country",
                "supplier_type", "default_price_list", "payment_terms"],
        order_by="supplier_name asc",
        limit_page_length=int(limit),
    )
    return {"suppliers": suppliers}


# ---------------------------------------------------------------------------
# Create Purchase Request
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_purchase_request(material_request_type="Purchase",
                             items=None, remark=None, schedule_date=None):
    """Manager raises a Material Request."""
    _require_procurement()

    import json

    if not items:
        frappe.throw(_("At least one item is required."))

    if isinstance(items, str):
        items = json.loads(items)

    if not isinstance(items, list) or not items:
        frappe.throw(_("At least one item is required."))

    doc = frappe.new_doc("Material Request")
    doc.material_request_type = material_request_type
    doc.transaction_date = today()
    if schedule_date:
        doc.schedule_date = schedule_date
    if remark:
        doc.remark = remark

    cost_center = _branch_cost_center()
    for item in items:
        row = {
            "item_code": item.get("item_code"),
            "qty": float(item.get("qty") or 0),
            "uom": item.get("uom") or "Nos",
            "schedule_date": schedule_date or today(),
        }
        if cost_center and frappe.get_meta("Material Request Item").has_field("cost_center"):
            row["cost_center"] = cost_center
        if item.get("rate"):
            row["rate"] = float(item.get("rate"))
        doc.append("items", row)

    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()

    return {"name": doc.name, "status": doc.status}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_procurement_stats():
    """Spending by category and month for the branch."""
    _require_procurement()

    if not _has_table("Purchase Order"):
        return _missing_doctype_response("Purchase Order")

    cost_center = _branch_cost_center()
    filters = {"docstatus": 1}
    if cost_center and not _is_admin():
        meta = frappe.get_meta("Purchase Order")
        for field in ("cost_center", "branch", "custom_lms_branch"):
            if meta.has_field(field):
                filters[field] = cost_center
                break

    # Total spend this month
    month_start = get_first_day(today())
    month_end = get_last_day(today())
    month_filters = dict(filters)
    month_filters["transaction_date"] = ["between", [month_start, month_end]]

    total_spend = frappe.db.sum("Purchase Order", month_filters, "grand_total") or 0
    total_orders = frappe.db.count("Purchase Order", month_filters)

    # Pending material requests
    pending_requests = frappe.db.count("Material Request", {
        "status": ["in", ["Pending", "Partially Ordered"]],
    })

    # Approved suppliers
    supplier_count = frappe.db.count("Supplier", {"disabled": 0})

    # Spend by month (last 6 months)
    monthly_spend = []
    for i in range(5, -1, -1):
        ref_date = getdate(today())
        m_start = get_first_day(frappe.utils.add_months(ref_date, -i))
        m_end = get_last_day(frappe.utils.add_months(ref_date, -i))
        m_filters = dict(filters)
        m_filters["transaction_date"] = ["between", [m_start, m_end]]
        spend = frappe.db.sum("Purchase Order", m_filters, "grand_total") or 0
        monthly_spend.append({
            "label": m_start.strftime("%b %Y"),
            "value": spend,
        })

    # Spend by supplier (top 5 this month)
    top_suppliers = frappe.get_all(
        "Purchase Order",
        filters=month_filters,
        fields=["supplier_name", "sum(grand_total) as total"],
        group_by="supplier_name",
        order_by="total desc",
        limit=5,
    )
    spend_by_supplier = [{"label": s["supplier_name"], "value": s["total"] or 0} for s in top_suppliers]

    return {
        "total_spend_this_month": total_spend,
        "total_orders_this_month": total_orders,
        "pending_requests": pending_requests,
        "supplier_count": supplier_count,
        "monthly_spend": monthly_spend,
        "spend_by_supplier": spend_by_supplier,
    }