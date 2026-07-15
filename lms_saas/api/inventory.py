"""Inventory & Assets addon API — asset register, stock items, checkout.

Reuses ERPNext ``Asset``, ``Item``, and ``Stock Entry`` doctypes.
Assets and stock are branch-scoped via the Cost Center / Branch field.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, getdate, now_datetime

from lms_saas.utils.addons import require_addon_persona


def _require_inventory():
    require_addon_persona("inventory")


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


# ---------------------------------------------------------------------------
# Asset Register
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_asset_register(limit=100):
    """Return ERPNext Assets for the branch."""
    _require_inventory()

    filters = {}
    if not _is_admin():
        branch = _branch()
        if branch:
            # Assets are typically linked to a Cost Center; filter by branch
            asset_meta = frappe.get_meta("Asset")
            for field in ("branch", "cost_center", "custom_lms_branch"):
                if asset_meta.has_field(field):
                    filters[field] = branch
                    break

    assets = frappe.get_all(
        "Asset",
        filters=filters,
        fields=["name", "asset_name", "asset_category", "status",
                "purchase_date", "gross_purchase_amount",
                "accumulated_depreciation", "asset_value", "location",
                "custodian", "department", "cost_center", "is_existing_asset"],
        order_by="purchase_date desc",
        limit_page_length=int(limit),
    )
    return {"assets": assets}


@frappe.whitelist()
def get_asset_detail(asset_name):
    """Return a single asset with depreciation schedule."""
    _require_inventory()

    asset = frappe.get_doc("Asset", asset_name)

    # Depreciation schedule
    depreciation = []
    if hasattr(asset, "schedules") and asset.schedules:
        for row in asset.schedules:
            depreciation.append({
                "schedule_date": row.schedule_date,
                "depreciation_amount": row.depreciation_amount,
                "accumulated_depreciation": row.accumulated_depreciation,
                "book_value": row.book_value,
            })

    return {
        "asset": {
            "name": asset.name,
            "asset_name": asset.asset_name,
            "asset_category": asset.asset_category,
            "status": asset.status,
            "purchase_date": asset.purchase_date,
            "gross_purchase_amount": asset.gross_purchase_amount,
            "accumulated_depreciation": asset.accumulated_depreciation,
            "asset_value": asset.asset_value,
            "location": getattr(asset, "location", None),
            "custodian": getattr(asset, "custodian", None),
            "department": getattr(asset, "department", None),
            "cost_center": getattr(asset, "cost_center", None),
        },
        "depreciation": depreciation,
    }


# ---------------------------------------------------------------------------
# Stock Items
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_stock_items(limit=100):
    """Return consumable stock items with current stock levels."""
    _require_inventory()

    filters = {"is_stock_item": 1, "disabled": 0}
    items = frappe.get_all(
        "Item",
        filters=filters,
        fields=["name", "item_name", "item_group", "stock_uom",
                "reorder_level", "description", "standard_rate"],
        order_by="item_name asc",
        limit_page_length=int(limit),
    )

    # Enrich with actual qty from bin
    for item in items:
        bin_qty = frappe.db.get_all(
            "Bin",
            filters={"item_code": item["name"]},
            fields=["warehouse", "actual_qty", "projected_qty", "reserved_qty"],
        )
        item["bins"] = bin_qty
        item["total_qty"] = sum(b["actual_qty"] or 0 for b in bin_qty)
        item["reorder_level"] = item.get("reorder_level") or 0

    return {"items": items}


@frappe.whitelist()
def get_low_stock_items():
    """Return items below their reorder level."""
    _require_inventory()

    items = frappe.get_all(
        "Item",
        filters={"is_stock_item": 1, "disabled": 0},
        fields=["name", "item_name", "item_group", "stock_uom",
                "reorder_level", "standard_rate"],
        order_by="item_name asc",
        limit_page_length=200,
    )

    low_stock = []
    for item in items:
        reorder = item.get("reorder_level") or 0
        if not reorder:
            continue
        bin_qty = frappe.db.get_all(
            "Bin",
            filters={"item_code": item["name"]},
            fields=["actual_qty"],
        )
        total_qty = sum(b["actual_qty"] or 0 for b in bin_qty)
        if total_qty <= reorder:
            item["total_qty"] = total_qty
            item["shortfall"] = reorder - total_qty
            low_stock.append(item)

    return {"items": low_stock}


# ---------------------------------------------------------------------------
# Asset Checkout
# ---------------------------------------------------------------------------

@frappe.whitelist()
def checkout_asset(asset_name, employee):
    """Assign an asset to an employee (set custodian)."""
    _require_inventory()
    if not _is_admin():
        frappe.throw(_("Only administrators can checkout assets."), frappe.PermissionError)

    asset = frappe.get_doc("Asset", asset_name)
    if asset.status != "Submitted":
        frappe.throw(_("Asset must be active to checkout."))

    asset.custodian = employee
    asset.flags.ignore_permissions = True
    asset.save()

    # Create a Stock Entry for the transfer if applicable
    try:
        se = frappe.new_doc("Stock Entry")
        se.stock_entry_type = "Material Transfer"
        se.purpose = "Material Transfer"
        se.to_employee = employee
        se.flags.ignore_permissions = True
        se.insert()
    except Exception:
        pass  # Stock Entry creation is best-effort

    return {"ok": True, "asset": asset.name, "custodian": employee}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_inventory_stats():
    """Overview stats for the inventory dashboard."""
    _require_inventory()

    total_assets = frappe.db.count("Asset")
    active_assets = frappe.db.count("Asset", {"status": "Submitted"})
    stock_items = frappe.db.count("Item", {"is_stock_item": 1, "disabled": 0})

    # Low stock count
    low_stock = 0
    items = frappe.get_all(
        "Item",
        filters={"is_stock_item": 1, "disabled": 0},
        fields=["name", "reorder_level"],
    )
    for item in items:
        reorder = item.get("reorder_level") or 0
        if not reorder:
            continue
        bin_qty = frappe.db.get_all("Bin", filters={"item_code": item["name"]}, fields=["actual_qty"])
        total_qty = sum(b["actual_qty"] or 0 for b in bin_qty)
        if total_qty <= reorder:
            low_stock += 1

    return {
        "total_assets": total_assets,
        "active_assets": active_assets,
        "stock_items": stock_items,
        "low_stock_items": low_stock,
    }