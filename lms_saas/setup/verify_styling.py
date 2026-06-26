"""LMS desk/portal styling audit — assets, hooks, and route class expectations.

Run:
  bench --site lms.localhost execute lms_saas.setup.verify_styling.run_all
"""

from __future__ import annotations

import os
import re

import frappe

from lms_saas.install import LMS_NAV_SPEC

APP_PATH = frappe.get_app_path("lms_saas")

DESK_ROUTES = (
    {"path": "/app/loans", "body_classes": ("lms-desk-enhanced", "lms-nav-lending-home", "lms-nav-screen")},
    {"path": "/app/crm", "body_classes": ("lms-desk-enhanced", "lms-nav-crm", "lms-nav-screen")},
    {"path": "/app/applications", "body_classes": ("lms-desk-enhanced", "lms-nav-screen")},
    {"path": "/app/collections", "body_classes": ("lms-desk-enhanced", "lms-nav-screen")},
    {"path": "/app/reports", "body_classes": ("lms-desk-enhanced", "lms-nav-screen")},
    {
        "path": "/app/dashboard-view/Loan%20Dashboard",
        "body_classes": ("lms-desk-enhanced", "lms-nav-dashboard"),
    },
    {
        "path": "/app/dashboard-view/CRM",
        "body_classes": ("lms-desk-enhanced", "lms-nav-crm-dashboard"),
    },
    {
        "path": "/app/company/LMS%20Demo%20Co",
        "body_classes": ("lms-desk-enhanced", "lms-nav-company"),
    },
    {
        "path": "/app/loan-application/view/list",
        "body_classes": ("lms-desk-enhanced", "lms-nav-lending-form", "lms-nav-loan-application"),
    },
    {
        "path": "/app/loan-application/ACC-LOAP-2026-00018",
        "body_classes": ("lms-desk-enhanced", "lms-nav-lending-form", "lms-nav-loan-application"),
    },
)

CSS_FILES = (
    "public/css/lms_tokens.css",
    "public/css/lms_components.css",
    "public/css/lms_desk.css",
    "public/css/lms_login.css",
    "public/css/lms_portal.css",
)

CSS_MARKERS = (
    ("lms_desk.css", r"\.lms-navbar-brand"),
    ("lms_desk.css", r"lms-nav-company #page-Company \.page-head \.page-title"),
    ("lms_desk.css", r"\.lms-nav-lending-form \.layout-main-section-wrapper"),
    ("lms_desk.css", r"\.lms-loan-application-hero"),
    ("lms_desk.css", r"\.lms-doctype-hero"),
    ("lms_desk.css", r"\.lms-nav-report \.(query-report-area|report-wrapper)"),
    ("lms_desk.css", r":has\(\.page-actions"),
    ("lms_desk.css", r"\.lms-nav-crm"),
    ("lms_components.css", r"\.lms-hero"),
    ("lms_components.css", r"\.lms-action-tile"),
    ("lms_components.css", r"\.lms-crm-hero"),
    ("lms_login.css", r"\.lms-login-route-card:hover"),
)


# Manual browser QA matrix (see STAFF_GUIDE). Automated checks cover assets/hooks only.
BROWSER_QA_ROUTES = (
    {"url": "/app/loans", "expect_class": "lms-nav-lending-home", "expect_hero": "lms-lending-hero"},
    {"url": "/app/crm", "expect_class": "lms-nav-crm", "expect_hero": "lms-crm-hero"},
    {"url": "/app/applications", "expect_class": "lms-nav-screen", "expect_hero": "lms-workspace-hero"},
    {"url": "/app/reports", "expect_class": "lms-nav-screen", "expect_hero": "lms-workspace-hero"},
    {
        "url": "/app/dashboard-view/Loan%20Dashboard",
        "expect_class": "lms-nav-dashboard",
        "expect_hero": "lms-loan-dashboard-hero",
    },
    {
        "url": "/app/dashboard-view/CRM",
        "expect_class": "lms-nav-crm-dashboard",
        "expect_hero": "lms-crm-dashboard-hero",
    },
    {
        "url": "/app/company/LMS%20Demo%20Co",
        "expect_class": "lms-nav-company",
        "expect_hero": "lms-company-hero",
    },
    {
        "url": "/app/loan-application/view/list",
        "expect_class": "lms-nav-loan-application",
        "expect_hero": "lms-loan-application-hero",
    },
    {
        "url": "/app/loan-application/ACC-LOAP-2026-00018",
        "expect_class": "lms-nav-loan-application",
        "expect_hero": "lms-loan-application-hero",
    },
    {"url": "/lms", "expect_class": "lms-portal", "expect_hero": None},
    {"url": "/login", "expect_class": "lms-login-page", "expect_hero": None},
)


def run_all():
    results = {"ok": True, "checks": {}}

    def check(name, fn):
        try:
            row = fn()
            results["checks"][name] = row
            if isinstance(row, dict) and row.get("ok") is False:
                results["ok"] = False
        except Exception as exc:
            results["ok"] = False
            results["checks"][name] = {"ok": False, "error": str(exc)}

    check("assets", _check_assets)
    check("hooks", _check_hooks)
    check("css_markers", _check_css_markers)
    check("workspaces", _check_workspaces)
    check("crm_workspace", _check_crm_workspace)
    check("route_expectations", _check_route_expectations)
    check("boot_nav", _check_boot_nav)
    check("browser_qa_matrix", _check_browser_qa_matrix)
    check("white_label_leaks", _check_white_label_leaks)
    check("navbar_branding", _check_navbar_branding)
    check("help_docs", _check_help_docs)
    check("help_markdown", _check_help_markdown)
    return results


def _check_help_docs():
    """Every /lms-help slug must have a markdown file under apps/lms_saas/docs."""
    from lms_saas.utils.help import DOCS_DIR, HELP_PAGES

    if not os.path.isdir(DOCS_DIR):
        return {"ok": False, "docs_dir": DOCS_DIR, "error": "DOCS_DIR missing"}
    missing = []
    for spec in HELP_PAGES:
        path = os.path.join(DOCS_DIR, spec["file"])
        if not os.path.isfile(path):
            missing.append({"slug": spec["slug"], "file": spec["file"]})
    return {"ok": not missing, "docs_dir": DOCS_DIR, "missing": missing}


def _check_help_markdown():
    """Help pages must render markdown to HTML, not escaped pre fallback."""
    from lms_saas.utils.help import (
        HELP_PAGES,
        load_help_markdown,
        markdown_to_html,
        rewrite_help_links,
    )

    sample = markdown_to_html("# Title\n\n**bold** and [staff](STAFF_GUIDE.md)")
    if "lms-help-pre" in sample or "<h1" not in sample or "<strong>" not in sample:
        return {"ok": False, "sample": sample[:240]}

    linked = rewrite_help_links(sample, "http://lms.localhost:8000")
    staff_href = 'href="/lms-help/staff"'
    if staff_href not in linked:
        return {"ok": False, "sample": linked[:240], "expected": staff_href}

    admin = markdown_to_html(load_help_markdown("SYSADMIN_GUIDE.md"))
    if "lms-help-pre" in admin or "<h1" not in admin or "**" in admin:
        return {"ok": False, "error": "SYSADMIN_GUIDE not rendered", "sample": admin[:240]}

    admin_linked = rewrite_help_links(admin, "http://lms.localhost:8000")
    if 'href="/lms-help/staff"' not in admin_linked:
        return {"ok": False, "error": "SYSADMIN_GUIDE links not rewritten", "sample": admin_linked[:240]}

    return {"ok": True, "pages": len(HELP_PAGES)}


def _check_browser_qa_matrix():
    return {"ok": True, "routes": BROWSER_QA_ROUTES, "note": "Run in browser while logged in as LMS staff"}


def _check_assets():
    missing = []
    for rel in CSS_FILES + ("public/js/lms_desk.js", "public/js/lms_brand.js"):
        if not os.path.isfile(os.path.join(APP_PATH, rel)):
            missing.append(rel)
    return {"ok": not missing, "missing": missing}


def _check_hooks():
    from lms_saas import hooks

    css = hooks.app_include_css or []
    js = hooks.app_include_js or []
    desk_css = any("lms_desk.css" in c for c in css)
    desk_js = any("lms_desk.js" in c for c in js)
    return {
        "ok": desk_css and desk_js,
        "desk_css": desk_css,
        "desk_js": desk_js,
        "css_count": len(css),
        "js_count": len(js),
    }


def _check_css_markers():
    failures = []
    for filename, pattern in CSS_MARKERS:
        path = os.path.join(APP_PATH, "public/css", filename)
        text = open(path, encoding="utf-8").read()
        if not re.search(pattern, text):
            failures.append({"file": filename, "pattern": pattern})
    return {"ok": not failures, "failures": failures}


def _check_workspaces():
    visible = [s["title"] for s in LMS_NAV_SPEC if not s.get("hidden")]
    hidden = [s["title"] for s in LMS_NAV_SPEC if s.get("hidden")]
    exists = {}
    for title in visible + hidden:
        exists[title] = bool(frappe.db.exists("Workspace", title))
    missing_visible = [t for t in visible if not exists[t]]
    return {
        "ok": not missing_visible,
        "visible": visible,
        "hidden": hidden,
        "exists": exists,
        "missing_visible": missing_visible,
    }


def _check_crm_workspace():
    native = frappe.db.exists("Workspace", "CRM")
    prospects_hidden = True
    if frappe.db.exists("Workspace", "CRM & Prospects"):
        prospects_hidden = bool(frappe.get_doc("Workspace", "CRM & Prospects").is_hidden)
    return {
        "ok": bool(native and prospects_hidden),
        "native_crm": bool(native),
        "crm_prospects_hidden": prospects_hidden,
    }


def _check_route_expectations():
    """Document expected body classes per route (for manual / browser QA)."""
    return {"ok": True, "routes": DESK_ROUTES}


_WHITE_LABEL_LEAK_PATTERNS = (
    (r"Powered\s+by\s+ERPNext", "Powered by ERPNext"),
    (r"Powered\s+by\s+Frappe", "Powered by Frappe"),
    (r'alt="LMS Suite"', "login fallback alt LMS Suite"),
)

_WHITE_LABEL_SCAN_DIRS = (
    "www",
    "templates",
    "public/js",
)


def _check_white_label_leaks():
    """Fail if user-facing templates/JS still expose stock framework branding."""
    hits = []
    for subdir in _WHITE_LABEL_SCAN_DIRS:
        root = os.path.join(APP_PATH, subdir)
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                if not name.endswith((".html", ".js", ".css")):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    text = open(path, encoding="utf-8").read()
                except OSError:
                    continue
                rel = os.path.relpath(path, APP_PATH)
                for pattern, label in _WHITE_LABEL_LEAK_PATTERNS:
                    if re.search(pattern, text, re.IGNORECASE):
                        hits.append({"file": rel, "leak": label})
    return {"ok": not hits, "hits": hits}


def _check_navbar_branding():
    logo = None
    if frappe.db.exists("DocType", "Navbar Settings"):
        logo = frappe.db.get_single_value("Navbar Settings", "app_logo")
    favicon = frappe.db.get_single_value("Website Settings", "favicon")
    logo_ok = bool(logo and "lms_saas" in (logo or "").lower())
    favicon_ok = bool(favicon and "lms_saas" in (favicon or "").lower())
    return {
        "ok": logo_ok and favicon_ok,
        "navbar_logo": logo,
        "website_favicon": favicon,
        "logo_ok": logo_ok,
        "favicon_ok": favicon_ok,
    }


def _check_boot_nav():
    from lms_saas.utils.desk_nav import get_lms_desk_nav

    frappe.set_user("demo.lms.officer@example.com")
    try:
        nav = get_lms_desk_nav()
        enabled = nav.get("enabled")
        items = [i.get("title") for i in nav.get("items") or []]
        return {
            "ok": enabled and "Applications" in items and "CRM & Prospects" not in items,
            "enabled": enabled,
            "items": items,
            "home_url": nav.get("home_url"),
        }
    finally:
        frappe.set_user("Administrator")
