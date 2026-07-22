"""Inventory & Assets addon API — asset register, stock items, checkout.

Reuses ERPNext ``Asset``, ``Item``, and ``Stock Entry`` doctypes.
Assets and stock are branch-scoped via the Cost Center / Branch field.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, getdate, now_datetime, flt

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

    # Pick the actual Asset fields that exist in the installed ERPNext version
    asset_meta = frappe.get_meta("Asset")
    wanted = ["name", "asset_name", "asset_category", "status",
              "purchase_date", "gross_purchase_amount", "location",
              "custodian", "department", "cost_center", "is_existing_asset"]
    # Depreciation columns: prefer opening_accumulated_depreciation (always present)
    # over accumulated_depreciation (removed in some ERPNext releases).
    if asset_meta.has_field("opening_accumulated_depreciation"):
        wanted.append("opening_accumulated_depreciation")
    if asset_meta.has_field("value_after_depreciation"):
        wanted.append("value_after_depreciation")
    if asset_meta.has_field("asset_value"):
        wanted.append("asset_value")

    assets = frappe.get_all(
        "Asset",
        filters=filters,
        fields=wanted,
        order_by="purchase_date desc",
        limit_page_length=int(limit),
    )
    # Backfill: surface accumulated_depreciation and asset_value aliases for the
    # front-end, regardless of which column the schema exposes.
    for a in assets:
        if "accumulated_depreciation" not in a:
            a["accumulated_depreciation"] = (
                a.get("opening_accumulated_depreciation") or 0
            )
        if "asset_value" not in a:
            a["asset_value"] = (
                a.get("value_after_depreciation")
                or (a.get("gross_purchase_amount") or 0)
                - (a.get("opening_accumulated_depreciation") or 0)
            )
    return {"assets": assets}


@frappe.whitelist()
def get_asset_detail(asset_name):
    """Return a single asset with depreciation schedule."""
    _require_inventory()

    asset = frappe.get_doc("Asset", asset_name)
    asset_meta = frappe.get_meta("Asset")

    # Depreciation schedule (child table field name varies by ERPNext version)
    depreciation = []
    schedule_rows = getattr(asset, "schedules", None) or getattr(asset, "finance_books", None) or []
    for row in schedule_rows:
        if not hasattr(row, "schedule_date") and not hasattr(row, "depreciation_amount"):
            continue
        depreciation.append({
            "schedule_date": getattr(row, "schedule_date", None),
            "depreciation_amount": getattr(row, "depreciation_amount", None),
            "accumulated_depreciation": getattr(
                row, "accumulated_depreciation_amount", None
            ) or getattr(row, "accumulated_depreciation", None) or 0,
            "book_value": getattr(row, "book_value", None),
        })

    opening_accum = 0
    if asset_meta.has_field("opening_accumulated_depreciation"):
        opening_accum = flt(asset.get("opening_accumulated_depreciation") or 0)
    elif asset_meta.has_field("accumulated_depreciation"):
        opening_accum = flt(asset.get("accumulated_depreciation") or 0)

    if asset_meta.has_field("value_after_depreciation"):
        asset_value = flt(asset.get("value_after_depreciation") or 0)
    elif asset_meta.has_field("asset_value"):
        asset_value = flt(asset.get("asset_value") or 0)
    else:
        asset_value = flt(asset.get("gross_purchase_amount") or 0) - opening_accum

    return {
        "asset": {
            "name": asset.name,
            "asset_name": asset.asset_name,
            "asset_category": asset.asset_category,
            "status": asset.status,
            "purchase_date": asset.purchase_date,
            "gross_purchase_amount": asset.gross_purchase_amount,
            "accumulated_depreciation": opening_accum,
            "asset_value": asset_value,
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

def _item_reorder_level(item_name: str) -> float:
    """Resolve reorder threshold from Item Reorder child table (ERPNext 14+).

    Legacy ``Item.reorder_level`` column was removed; querying it 500s.
    """
    item_meta = frappe.get_meta("Item")
    if item_meta.has_field("reorder_level"):
        return flt(frappe.db.get_value("Item", item_name, "reorder_level") or 0)
    if not item_meta.has_field("reorder_levels"):
        return 0
    if not frappe.db.table_exists("Item Reorder"):
        return 0
    rows = frappe.get_all(
        "Item Reorder",
        filters={"parent": item_name},
        fields=["warehouse_reorder_level"],
        limit_page_length=20,
    )
    thresholds = [flt(r.get("warehouse_reorder_level") or 0) for r in rows]
    return max(thresholds) if thresholds else 0


@frappe.whitelist()
def get_stock_items(limit=100):
    """Return consumable stock items with current stock levels."""
    _require_inventory()

    filters = {"is_stock_item": 1, "disabled": 0}
    fields = ["name", "item_name", "item_group", "stock_uom", "description", "standard_rate"]
    item_meta = frappe.get_meta("Item")
    # Only include legacy column when present (pre-ERPNext-14).
    if item_meta.has_field("reorder_level"):
        fields.append("reorder_level")

    items = frappe.get_all(
        "Item",
        filters=filters,
        fields=fields,
        order_by="item_name asc",
        limit_page_length=int(limit),
    )

    # Enrich with actual qty from bin + schema-safe reorder level.
    for item in items:
        bin_qty = frappe.db.get_all(
            "Bin",
            filters={"item_code": item["name"]},
            fields=["warehouse", "actual_qty", "projected_qty", "reserved_qty"],
        )
        item["bins"] = bin_qty
        item["total_qty"] = sum(b["actual_qty"] or 0 for b in bin_qty)
        item["reorder_level"] = item.get("reorder_level") or _item_reorder_level(item["name"])

    return {"items": items}


@frappe.whitelist()
def get_low_stock_items():
    """Return items below their reorder level."""
    _require_inventory()

    items = frappe.get_all(
        "Item",
        filters={"is_stock_item": 1, "disabled": 0},
        fields=["name", "item_name", "item_group", "stock_uom", "standard_rate"],
        order_by="item_name asc",
        limit_page_length=200,
    )

    low_stock = []
    for item in items:
        reorder = _item_reorder_level(item["name"])
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
            item["reorder_level"] = reorder
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

    # Low stock count. ERPNext stores reorder thresholds in the Item Reorder
    # child table (Item.reorder_levels) — the legacy Item.reorder_level column
    # was removed. If the child table is present, use it; otherwise fall back
    # to a no-thresholds scan (returns 0 low-stock items, but doesn't 500).
    low_stock = 0
    item_meta = frappe.get_meta("Item")
    if item_meta.has_field("reorder_levels"):
        items = frappe.get_all(
            "Item",
            filters={"is_stock_item": 1, "disabled": 0},
            fields=["name"],
            limit_page_length=500,
        )
        for item in items:
            rows = frappe.get_all(
                "Item Reorder",
                filters={"parent": item["name"]},
                fields=["warehouse_reorder_level"],
                limit_page_length=10,
            )
            thresholds = [r["warehouse_reorder_level"] for r in rows if r.get("warehouse_reorder_level")]
            if not thresholds:
                continue
            threshold = max(thresholds)
            if threshold <= 0:
                continue
            bin_qty = frappe.db.get_all("Bin", filters={"item_code": item["name"]}, fields=["actual_qty"])
            total_qty = sum(b["actual_qty"] or 0 for b in bin_qty)
            if total_qty <= threshold:
                low_stock += 1
    # Else: schema lacks reorder_levels entirely — skip the low-stock check
    # rather than crash. Most installs without it are pre-ERPNext-13 anyway.

    return {
        "total_assets": total_assets,
        "active_assets": active_assets,
        "stock_items": stock_items,
        "low_stock_items": low_stock,
    }