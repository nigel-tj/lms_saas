"""Document Center addon API — centralised document repository.

Reuses Frappe ``File`` doctype. Documents are categorised via the new
``LMS Document Category`` doctype and linked to loans, borrowers, or
collateral via the File's ``attached_to_*`` fields.
"""

from __future__ import annotations

import frappe
from frappe import _
from urllib.parse import quote

from frappe.utils import today, add_days, getdate, cint

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
        # Linked-to display label — never surface Frappe's #####-masked PII
        # (e.g. COMP-.#####). Resolve a safe human label instead (B-14).
        f["linked_to_label"] = _safe_linked_label(
            f.get("attached_to_doctype"), f.get("attached_to_name")
        )
        # Authz download endpoint — never expose raw /files/ URLs in the UI (Naledi P0).
        f["download_url"] = (
            "/api/method/lms_saas.api.documents_center.download_document"
            f"?file_name={quote(f['name'])}"
        )
        # Keep file_url server-side only for upload plumbing; clients must use download_url.
        f.pop("file_url", None)

    # Category filter (post-query since it's a custom field)
    if category and category != "Uncategorized":
        files = [f for f in files if f.get("category") == category]

    return {"documents": files}


def _safe_linked_label(doctype: str | None, name: str | None) -> str:
    """Return a non-sensitive Linked-To label for the document center UI.

    Frappe permission-masks document names as ``COMP-.#####`` when the caller
    lacks read access. Showing that string looks like a PII leak / redaction
    bug. Prefer a customer/loan display name resolved with ignore_permissions
    only for the label (never for file content).
    """
    if not doctype:
        return "—"
    if not name or "#####" in str(name):
        # Masked or missing identifier — show doctype only.
        return doctype

    try:
        if doctype == "LMS Borrower Compliance":
            customer = frappe.db.get_value(
                "LMS Borrower Compliance", name, "customer",
            )
            if customer:
                cust_name = frappe.db.get_value("Customer", customer, "customer_name")
                return f"Borrower Compliance — {cust_name or customer}"
            return "Borrower Compliance"
        if doctype == "Customer":
            cust_name = frappe.db.get_value("Customer", name, "customer_name")
            return f"Customer — {cust_name or name}"
        if doctype == "Loan":
            applicant = frappe.db.get_value("Loan", name, "applicant")
            cust_name = (
                frappe.db.get_value("Customer", applicant, "customer_name")
                if applicant else None
            )
            return f"Loan — {cust_name or name}"
        if doctype == "Loan Application":
            applicant = frappe.db.get_value("Loan Application", name, "applicant")
            cust_name = (
                frappe.db.get_value("Customer", applicant, "customer_name")
                if applicant else None
            )
            return f"Application — {cust_name or name}"
    except Exception:
        pass
    return f"{doctype} — {name}"


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

    # Prefer private storage so /files/ is not anonymously readable.
    try:
        frappe.db.set_value("File", file_name, "is_private", 1)
    except Exception:
        pass

    return {"ok": True, "file_name": file_name}


@frappe.whitelist()
def download_document(file_name: str | None = None):
    """Stream a File after portal authz — replaces unauthenticated /files/ links.

    Requires an authenticated session with Document Center addon access.
    Borrowers may only download files attached to their own Customer /
    LMS Borrower Compliance / Loan / Loan Application records.
    """
    _require_docs()

    if frappe.session.user == "Guest":
        frappe.throw(_("Please log in to download documents."), frappe.PermissionError)

    file_name = (file_name or "").strip()
    if not file_name or not frappe.db.exists("File", file_name):
        frappe.throw(_("File not found."), frappe.DoesNotExistError)

    file_doc = frappe.get_doc("File", file_name)
    if cint(file_doc.is_folder):
        frappe.throw(_("Folders cannot be downloaded."))

    _assert_file_download_allowed(file_doc)

    try:
        content = file_doc.get_content()
    except Exception:
        frappe.log_error(title="LMS document download failed", message=frappe.get_traceback())
        frappe.throw(_("Could not read file contents."))

    frappe.local.response.filename = file_doc.file_name or file_doc.name
    frappe.local.response.filecontent = content
    frappe.local.response.type = "download"


def _assert_file_download_allowed(file_doc) -> None:
    """Staff with document_center persona may download; borrowers only own links."""
    from lms_saas.utils.portal import is_portal_borrower, resolve_portal_persona

    if _is_admin():
        return

    persona = resolve_portal_persona()
    if persona in ("Branch Manager", "Loan Officer", "Collector", "Admin"):
        return

    if not is_portal_borrower():
        # Other authenticated staff that passed require_addon_persona
        if persona:
            return
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    # Borrower: must be attached to their customer graph.
    from lms_saas.api.portal import _require_customer

    customer = _require_customer(raise_exception=False)
    if not customer:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    dt = file_doc.attached_to_doctype
    dn = file_doc.attached_to_name
    if not dt or not dn:
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if dt == "Customer" and dn == customer:
        return
    if dt == "LMS Borrower Compliance":
        linked = frappe.db.get_value("LMS Borrower Compliance", dn, "customer")
        if linked == customer:
            return
    if dt == "Loan":
        applicant = frappe.db.get_value("Loan", dn, "applicant")
        if applicant == customer:
            return
    if dt == "Loan Application":
        applicant = frappe.db.get_value("Loan Application", dn, "applicant")
        if applicant == customer:
            return

    frappe.throw(_("Not permitted"), frappe.PermissionError)


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
    for f in files:
        f["download_url"] = (
            "/api/method/lms_saas.api.documents_center.download_document"
            f"?file_name={quote(f['name'])}"
        )
        f.pop("file_url", None)

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