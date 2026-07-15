"""Document Center addon API — centralised document repository.

Reuses Frappe ``File`` doctype. Documents are categorised via the new
``LMS Document Category`` doctype and linked to loans, borrowers, or
collateral via the File's ``attached_to_*`` fields.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, add_days, getdate

from lms_saas.utils.addons import require_addon_persona


def _require_docs():
    require_addon_persona("document_center")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_categories():
    """Return all document categories."""
    _require_docs()
    cats = frappe.get_all(
        "LMS Document Category",
        fields=["name", "category_name", "description"],
        order_by="category_name asc",
    )
    return {"categories": cats}


@frappe.whitelist()
def create_category(category_name, description=None):
    """Admin-only: create a document category."""
    _require_docs()
    if not _is_admin():
        frappe.throw(_("Only administrators can create categories."), frappe.PermissionError)

    doc = frappe.new_doc("LMS Document Category")
    doc.category_name = category_name
    doc.description = description
    doc.flags.ignore_permissions = True
    doc.insert()
    return {"name": doc.name}


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_documents(category=None, reference_doctype=None, reference_name=None, limit=50):
    """Return documents (Files) matching the filters."""
    _require_docs()

    # Build query on File doctype
    filters = {"is_folder": 0}
    if reference_doctype and reference_name:
        filters["attached_to_doctype"] = reference_doctype
        filters["attached_to_name"] = reference_name

    files = frappe.get_all(
        "File",
        filters=filters,
        fields=["name", "file_name", "file_url", "file_size", "attached_to_doctype",
                "attached_to_name", "modified", "owner"],
        order_by="modified desc",
        limit_page_length=int(limit),
    )

    # Enrich with category (from custom field if present)
    file_meta = frappe.get_meta("File")
    has_category = file_meta.has_field("custom_lms_doc_category")
    has_expiry = file_meta.has_field("custom_lms_doc_expiry_date")
    for f in files:
        f["category"] = (frappe.db.get_value("File", f.name, "custom_lms_doc_category") if has_category else None) or "Uncategorized"
        f["expiry_date"] = frappe.db.get_value("File", f.name, "custom_lms_doc_expiry_date") if has_expiry else None
        f["is_expired"] = bool(f.get("expiry_date") and getdate(f["expiry_date"]) < getdate(today()))

    # Category filter (post-query since it's a custom field)
    if category and category != "Uncategorized":
        files = [f for f in files if f.get("category") == category]

    return {"documents": files}


@frappe.whitelist()
def upload_document(file_url, category=None, reference_doctype=None, reference_name=None, expiry_date=None):
    """Register an uploaded file in the document center."""
    _require_docs()

    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        frappe.throw(_("File not found."))

    file_meta = frappe.get_meta("File")
    if category and file_meta.has_field("custom_lms_doc_category"):
        frappe.db.set_value("File", file_name, "custom_lms_doc_category", category)
    if expiry_date and file_meta.has_field("custom_lms_doc_expiry_date"):
        frappe.db.set_value("File", file_name, "custom_lms_doc_expiry_date", expiry_date)
    if reference_doctype and reference_name:
        frappe.db.set_value("File", file_name, {
            "attached_to_doctype": reference_doctype,
            "attached_to_name": reference_name,
        })

    return {"ok": True, "file_name": file_name}


@frappe.whitelist()
def get_expiring_documents(days=30):
    """Return documents expiring within the given window."""
    _require_docs()
    cutoff = add_days(today(), int(days))

    # Files with expiry date in the window (only if custom field exists)
    file_meta = frappe.get_meta("File")
    if not file_meta.has_field("custom_lms_doc_expiry_date"):
        return {"documents": [], "days": int(days)}

    files = frappe.get_all(
        "File",
        filters={
            "custom_lms_doc_expiry_date": ("between", [today(), cutoff]),
            "is_folder": 0,
        },
        fields=["name", "file_name", "file_url", "custom_lms_doc_category",
                "custom_lms_doc_expiry_date", "attached_to_doctype", "attached_to_name"],
        order_by="custom_lms_doc_expiry_date asc",
    )

    return {"documents": files, "days": int(days)}


@frappe.whitelist()
def get_document_stats():
    """Overview stats."""
    _require_docs()

    total = frappe.db.count("File", {"is_folder": 0})
    categories = frappe.db.count("LMS Document Category")
    file_meta = frappe.get_meta("File")
    if file_meta.has_field("custom_lms_doc_expiry_date"):
        expiring_30 = len(frappe.get_all("File", filters={
            "custom_lms_doc_expiry_date": ("between", [today(), add_days(today(), 30)]),
            "is_folder": 0,
        }, pluck="name"))
        expired = len(frappe.get_all("File", filters={
            "custom_lms_doc_expiry_date": ("<", today()),
            "is_folder": 0,
        }, pluck="name"))
    else:
        expiring_30 = 0
        expired = 0

    return {
        "total_documents": total,
        "categories": categories,
        "expiring_30_days": expiring_30,
        "expired": expired,
    }