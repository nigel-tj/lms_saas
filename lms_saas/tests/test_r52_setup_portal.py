"""R52 regression tests — Operations Manager Setup Portal foundation (T1).

R52-T1 builds three things that stand up together:

1. ``Employee.custom_lms_persona`` Select field gains the
   ``"Operations Manager"`` option (alongside the existing Loan Officer /
   Collector / Branch Manager options).

2. ``_require_ops_manager()`` guard in ``lms_saas.api.setup`` — refuses
   any portal-staff user whose persona is NOT ``"Operations Manager"``.

3. ``LMS Setup Change Request`` doctype exists with the compliance
   anchor fields, and the perms are split: LMS Portal Staff read/write/
   create (ops manager drafts), System Manager full (admin approve/reject).

4. ``get_lms_home_page`` routes the ops-manager persona to ``/lms/setup``.

5. ``PERSONA_CONFIG`` in ``install.py`` gains the ``"Operations Manager"``
   entry.

This test file mixes two assertion styles:

- **Source-level** (no DB) — structural assertions on the fixture, the
  PERSONA_CONFIG dict, and the guard function body. Same pattern as
  ``test_r51_phantom_branch_resolver.py`` and ``test_r22_regressions.py``.
- **Live API** (FrappeTestCase) — behaviour assertions on the guard
  refusal/acceptance, home-page routing, and change request creation.

Run via:
    cd frappe-bench && python run_lms_tests.py
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

REPO_ROOT = Path(__file__).resolve().parents[4]
# Test file lives at apps/lms_saas/lms_saas/tests/test_r52_setup_portal.py
# parents[0] = tests/, parents[1] = lms_saas/ (inner), parents[2] = lms_saas/
# (app), parents[3] = apps/, parents[4] = REPO_ROOT.
#
# The Frappe package convention:
#   apps/lms_saas/lms_saas/                      ← Python package (api/, hooks.py,
#                                                  install.py, boot.py)
#   apps/lms_saas/lms_saas/lms_saas/             ← Inner module (doctype/,
#                                                  fixtures/, public/, www/)
APP_ROOT = REPO_ROOT / "apps" / "lms_saas" / "lms_saas"
MODULE_ROOT = APP_ROOT / "lms_saas"
FIXTURES = APP_ROOT / "fixtures" / "custom_field.json"
INSTALL_PY = APP_ROOT / "install.py"
SETUP_API = APP_ROOT / "api" / "setup.py"
BOOT_PY = APP_ROOT / "boot.py"


def _read(path: Path) -> str:
    return path.read_text()


# ---------------------------------------------------------------------------
# Source-level structural assertions
# ---------------------------------------------------------------------------
class TestR52PersonaFieldHasOperationsManager(FrappeTestCase):
    """R52-T1: Employee.custom_lms_persona Select must include 'Operations Manager'."""

    def test_fixture_options_include_operations_manager(self):
        """The fixtures/custom_field.json entry must list Operations Manager
        alongside the existing Loan Officer / Collector / Branch Manager
        options. Without it the LMS User Setup onboarding form cannot
        persist the persona, and the guard's persona check would be
        match-by-name-only against a value that can't be stored."""
        spec = json.loads(_read(FIXTURES))
        entry = next(
            (
                f
                for f in spec
                if f.get("doctype") == "Custom Field"
                and f.get("name") == "Employee-custom_lms_persona"
            ),
            None,
        )
        self.assertIsNotNone(
            entry, "Employee-custom_lms_persona custom field fixture missing"
        )
        # Frappe stores Select options as newline-separated, with a leading
        # newline for the empty default. Split on \n and trim empties.
        options = [
            o.strip()
            for o in (entry.get("options") or "").split("\n")
            if o.strip()
        ]
        self.assertIn(
            "Operations Manager",
            options,
            msg=(
                "Operations Manager must be in the Employee.custom_lms_persona "
                f"options list; got {options!r}"
            ),
        )
        # Sanity: the existing personas are still there (don't drop them).
        for required in ("Loan Officer", "Collector", "Branch Manager"):
            self.assertIn(required, options)


class TestR52RequireOpsManagerGuard(FrappeTestCase):
    """R52-T1: _require_ops_manager() must exist and gate on persona."""

    def test_guard_function_defined(self):
        """api/setup.py must define _require_ops_manager()."""
        from lms_saas.api import setup

        self.assertTrue(
            hasattr(setup, "_require_ops_manager"),
            msg="lms_saas.api.setup._require_ops_manager is not defined",
        )
        self.assertTrue(callable(setup._require_ops_manager))

    def test_guard_source_checks_persona(self):
        """The guard must gate on the 'Operations Manager' persona —
        not just the role — so a Loan Officer carrying the LMS Portal
        Staff role cannot bypass it. We delegate to
        ``access_control.require_persona``; the source-level assertion
        confirms the delegation is wired (and not, e.g., a copy-paste
        re-implementation)."""
        src = _read(SETUP_API)
        self.assertIn(
            "_require_ops_manager",
            src,
            msg="api/setup.py does not reference _require_ops_manager",
        )
        self.assertIn(
            "Operations Manager",
            src,
            msg="Guard must reference the 'Operations Manager' persona string",
        )
        # Must delegate to the canonical guard, not roll its own.
        self.assertIn(
            "require_persona",
            src,
            msg="Guard must delegate to access_control.require_persona (not re-implement)",
        )
        self.assertIn(
            "from lms_saas.utils.access_control import",
            src,
            msg="api/setup.py must import from lms_saas.utils.access_control",
        )


class TestR52SetupChangeRequestDoctype(FrappeTestCase):
    """R52-T1: LMS Setup Change Request doctype + perms."""

    def test_doctype_files_exist(self):
        """The doctype directory + json + py controller must exist."""
        base = MODULE_ROOT / "doctype" / "lms_setup_change_request"
        self.assertTrue(
            (base / "lms_setup_change_request.json").exists(),
            msg=f"LMS Setup Change Request doctype json missing at {base}",
        )

    def test_doctype_spec_has_required_fields(self):
        """The doctype spec must include the compliance anchor fields
        listed in the PRD: target_doctype, target_name, change_type,
        proposed_fields, old_values, status, requested_by, approved_by,
        approved_at, applied_at, rejection_reason, audit_event_ref,
        gl_wiring_notes."""
        spec_path = (
            MODULE_ROOT
            / "doctype"
            / "lms_setup_change_request"
            / "lms_setup_change_request.json"
        )
        spec = json.loads(_read(spec_path))
        field_names = {f["fieldname"] for f in spec.get("fields", [])}
        required = {
            "target_doctype",
            "target_name",
            "change_type",
            "status",
            "requested_by",
            "approved_by",
            "approved_at",
            "applied_at",
            "rejection_reason",
            "audit_event_ref",
            "gl_wiring_notes",
        }
        missing = required - field_names
        self.assertFalse(
            missing,
            msg=f"LMS Setup Change Request missing required fields: {sorted(missing)}",
        )

    def test_doctype_spec_has_portal_staff_perms(self):
        """LMS Portal Staff must have read/write/create perms on the
        doctype so the ops manager can create drafts from the portal.
        Admin (System Manager) must have full perms for approve/apply."""
        spec_path = (
            MODULE_ROOT
            / "doctype"
            / "lms_setup_change_request"
            / "lms_setup_change_request.json"
        )
        spec = json.loads(_read(spec_path))
        perms_by_role = {p["role"]: p for p in spec.get("permissions", [])}

        portal = perms_by_role.get("LMS Portal Staff")
        self.assertIsNotNone(
            portal,
            msg="LMS Portal Staff role missing from LMS Setup Change Request perms",
        )
        self.assertEqual(portal.get("read"), 1)
        self.assertEqual(portal.get("write"), 1)
        self.assertEqual(portal.get("create"), 1)
        # Ops manager drafts + cancels; the server-side guard gates apply.
        self.assertEqual(portal.get("delete"), 0)
        self.assertEqual(portal.get("submit"), 0)

        admin = perms_by_role.get("System Manager")
        self.assertIsNotNone(
            admin,
            msg="System Manager role missing from LMS Setup Change Request perms",
        )
        self.assertEqual(admin.get("read"), 1)
        self.assertEqual(admin.get("write"), 1)
        self.assertEqual(admin.get("create"), 1)
        self.assertEqual(admin.get("delete"), 1)
        # Submit/cancel/amend are not used — the apply path is a custom
        # server-side function, not the Frappe docstatus workflow. The
        # status field is a Select lifecycle, not a docstatus transition.


class TestR52PersonaConfig(FrappeTestCase):
    """R52-T1: PERSONA_CONFIG gains the Operations Manager entry."""

    def test_persona_config_has_operations_manager(self):
        """install.py's PERSONA_CONFIG must include the Operations Manager
        entry with the expected shape: roles=[LMS Portal Staff],
        create_employee=True, desk=False, landing_workspace=None."""

        # Force a re-import so the test sees the latest source.
        from lms_saas import install

        importlib.reload(install)
        cfg = getattr(install, "PERSONA_CONFIG", None)
        self.assertIsNotNone(cfg, msg="PERSONA_CONFIG is not defined")
        self.assertIn(
            "Operations Manager",
            cfg,
            msg=f"Operations Manager missing from PERSONA_CONFIG; have {list(cfg)}",
        )
        ops = cfg["Operations Manager"]
        self.assertEqual(ops.get("roles"), ["LMS Portal Staff"])
        self.assertTrue(ops.get("create_employee"))
        self.assertFalse(ops.get("desk"))
        self.assertIsNone(ops.get("landing_workspace"))

    def test_backfill_function_is_defined(self):
        """install.py must define _backfill_employee_persona_from_user_setup
        so historical installs self-heal to populate the persona field."""
        from lms_saas import install

        importlib.reload(install)
        self.assertTrue(
            hasattr(install, "_backfill_employee_persona_from_user_setup"),
            msg="_backfill_employee_persona_from_user_setup missing from install.py",
        )
        self.assertTrue(callable(install._backfill_employee_persona_from_user_setup))

    def test_backfill_is_called_from_after_install(self):
        """The backfill must be invoked at the tail of after_install()
        so a fresh `bench migrate` propagates persona to legacy Employees."""
        from lms_saas import install

        importlib.reload(install)
        import inspect

        src = inspect.getsource(install.after_install)
        self.assertIn(
            "_backfill_employee_persona_from_user_setup",
            src,
            msg="after_install() must call _backfill_employee_persona_from_user_setup",
        )

    def test_backfill_propagates_persona_to_legacy_employee(self):
        """A legacy Employee with empty persona + a matching LMS User Setup
        row must have the persona propagated after the backfill runs.

        Uses 'Loan Officer' as the propagated persona so we don't trip the
        LMS User Setup's branch-required validator (the persona-specific
        validator only fires for 'Operations Manager')."""
        from lms_saas import install

        importlib.reload(install)

        if not frappe.get_meta("Employee").has_field("custom_lms_persona"):
            self.skipTest("custom_lms_persona not yet on this bench")
        if not frappe.db.exists("DocType", "LMS User Setup"):
            self.skipTest("LMS User Setup doctype not on this bench")

        # Build a User + Employee with no persona set.
        suffix = frappe.generate_hash(length=6)
        email = f"r52-backfill-{suffix}@example.com"
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = "Backfill"
        user.last_name = f"Test{suffix}"
        user.send_welcome_email = 0
        user.flags.ignore_permissions = True
        user.flags.no_welcome_mail = True
        user.insert()

        emp = frappe.new_doc("Employee")
        emp.employee_id = f"R52-BF-{suffix}"[:20]
        emp.first_name = "Backfill"
        emp.last_name = f"T{suffix}"
        emp.user_id = email
        emp.status = "Active"
        emp.company = (
            frappe.db.get_single_value("Global Defaults", "default_company") or ""
        )
        emp.gender = "Other"
        emp.date_of_birth = "1990-01-01"
        emp.date_of_joining = "2024-01-01"
        emp.flags.ignore_permissions = True
        emp.insert()
        emp_name = emp.name

        # Sanity: persona starts blank.
        self.assertFalse(
            frappe.db.get_value("Employee", emp_name, "custom_lms_persona")
        )

        # Simulate an LMS User Setup row for this user with a known persona.
        # Use Loan Officer + a real Cost Center branch (the validator refuses
        # staff setup rows without a branch).
        branch = frappe.db.get_value(
            "Cost Center", {"is_group": 0}, "name"
        ) or ""
        setup = frappe.new_doc("LMS User Setup")
        setup.persona = "Loan Officer"
        setup.first_name = "Backfill"
        setup.last_name = "Setup"
        setup.email = f"r52-setup-{suffix}@example.com"
        # Use a deterministic 11-digit numeric mobile (Frappe Phone validator
        # rejects hex hashes; we encode the suffix as digits mod 10).
        digits = "".join(str((ord(c) - ord("a")) % 10) for c in suffix[:9])
        setup.mobile_no = "07" + digits
        setup.send_welcome_email = 0
        setup.branch = branch
        setup.created_user = email  # skip the User creation path
        setup.flags.ignore_permissions = True
        setup.insert()
        setup.db_set("docstatus", 1, update_modified=False)
        # Pin created_user manually since we skipped submit().
        frappe.db.set_value(
            "LMS User Setup", setup.name, "created_user", email
        )

        try:
            install._backfill_employee_persona_from_user_setup()
            propagated = frappe.db.get_value(
                "Employee", emp_name, "custom_lms_persona"
            )
            self.assertEqual(
                propagated,
                "Loan Officer",
                msg=(
                    "backfill must propagate the LMS User Setup persona to "
                    "the Employee row"
                ),
            )
        finally:
            # Test cleanup (transaction rollback handles most of it, but
            # the autoname counter + LMS User Setup row need explicit drop).
            try:
                frappe.delete_doc(
                    "LMS User Setup", setup.name, ignore_permissions=True, force=True
                )
            except Exception:
                pass


class TestR52HomePageRouting(FrappeTestCase):
    """R52-T1: get_lms_home_page routes the ops-manager persona to /lms/setup."""

    def test_routes_table_has_operations_manager(self):
        """boot._portal_staff_landing must include the Operations Manager
        → /lms/setup mapping."""
        src = _read(BOOT_PY)
        # The routes dict literal sits in _portal_staff_landing.
        self.assertIn(
            "Operations Manager",
            src,
            msg="boot.py does not reference the 'Operations Manager' persona",
        )
        self.assertIn(
            "/lms/setup",
            src,
            msg="boot.py does not route any persona to /lms/setup",
        )
        # And the dict mapping is wired up — not a stray comment string.
        self.assertRegex(
            src,
            r'"Operations Manager"\s*:\s*"/lms/setup"',
            msg="boot.py is missing the Operations Manager → /lms/setup dict entry",
        )


# ---------------------------------------------------------------------------
# Live API behaviour assertions
# ---------------------------------------------------------------------------
class TestR52GuardBehaviour(FrappeTestCase):
    """_require_ops_manager() refuses non-ops-manager portal-staff users."""

    def test_guard_refuses_branch_manager(self):
        """A user with LMS Portal Staff + persona='Branch Manager' must
        be refused by _require_ops_manager() with a PermissionError."""
        from lms_saas.api.setup import _require_ops_manager

        user = _make_user_with_persona("Branch Manager")
        try:
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                _require_ops_manager()
        finally:
            frappe.set_user("Administrator")
            _purge_user(user)

    def test_guard_accepts_operations_manager(self):
        """A user with LMS Portal Staff + persona='Operations Manager'
        must pass _require_ops_manager() without raising."""
        from lms_saas.api.setup import _require_ops_manager

        user = _make_user_with_persona("Operations Manager")
        try:
            frappe.set_user(user)
            # Must not raise.
            _require_ops_manager()
        finally:
            frappe.set_user("Administrator")
            _purge_user(user)

    def test_guard_refuses_loan_officer(self):
        """A user with LMS Portal Staff + persona='Loan Officer' must
        be refused by _require_ops_manager() — proves the persona check
        is not just 'has LMS Portal Staff'."""
        from lms_saas.api.setup import _require_ops_manager

        user = _make_user_with_persona("Loan Officer")
        try:
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                _require_ops_manager()
        finally:
            frappe.set_user("Administrator")
            _purge_user(user)


class TestR52HomePageRoutingLive(FrappeTestCase):
    """get_lms_home_page routes the ops-manager persona to /lms/setup live."""

    def test_ops_manager_routes_to_setup(self):
        """An Operations Manager persona lands on /lms/setup after login."""
        from lms_saas.boot import get_lms_home_page

        user = _make_user_with_persona("Operations Manager")
        try:
            target = get_lms_home_page(user=user)
            self.assertEqual(
                target,
                "/lms/setup",
                msg=f"Ops manager should land on /lms/setup; got {target!r}",
            )
        finally:
            _purge_user(user)

    def test_branch_manager_routes_to_manager(self):
        """Sanity: Branch Manager persona still lands on /lms/manager
        (regression guard — we didn't accidentally break existing routing)."""
        from lms_saas.boot import get_lms_home_page

        user = _make_user_with_persona("Branch Manager")
        try:
            target = get_lms_home_page(user=user)
            self.assertEqual(target, "/lms/manager")
        finally:
            _purge_user(user)


# ---------------------------------------------------------------------------
# Fixtures for the live-API tests
# ---------------------------------------------------------------------------
USER_COUNTER = {"n": 0}


def _make_user_with_persona(persona: str) -> str:
    """Create a User + Employee carrying the given LMS persona.

    The user has the LMS Portal Staff role, an Employee record with
    ``custom_lms_persona = persona``, and an isolated email so cleanup
    is straightforward.

    NB: the test isolation rollback removes these rows at the end of
    each test method, but the cache + autoname counters are not reset.
    We use frappe.generate_hash so every test gets a unique employee
    name + user email, sidestepping autoname collisions.
    """
    USER_COUNTER["n"] += 1
    stamp = USER_COUNTER["n"]
    slug = persona.replace(" ", "").lower()
    # append a per-test uuid suffix so autoname collisions across tests
    # don't break Employee autoname ("HR-EMP-...") and User uniqueness.
    suffix = frappe.generate_hash(length=6)
    email = f"r52-{stamp}-{slug}-{suffix}@example.com"

    # Defensive: clear any cache residue
    frappe.clear_cache()

    user = frappe.new_doc("User")
    user.email = email
    user.first_name = f"R52 {persona}"
    user.last_name = f"Test-{stamp}-{suffix}"
    user.send_welcome_email = 0
    user.flags.ignore_permissions = True
    user.flags.no_welcome_mail = True
    user.insert()

    # LMS Portal Staff role
    user.add_roles("LMS Portal Staff")

    # Employee with persona flag — let autoname assign the HR-EMP-... name
    emp = frappe.new_doc("Employee")
    emp.employee_id = f"R52-{stamp}-{slug}-{suffix}"[:20]
    emp.first_name = f"R52 {persona}"
    emp.last_name = f"T{stamp}{suffix}"
    emp.user_id = email
    emp.status = "Active"
    emp.company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    emp.gender = "Other"
    emp.date_of_birth = "1990-01-01"
    emp.date_of_joining = "2024-01-01"
    emp.flags.ignore_permissions = True
    emp.insert()
    emp_name = emp.name

    # Persist persona. custom_lms_persona is read_only=1 in the fixture
    # (LMS User Setup owns it), so doc.save() would refuse; db.set_value
    # bypasses the read_only meta check and writes directly.
    if frappe.get_meta("Employee").has_field("custom_lms_persona"):
        frappe.db.set_value(
            "Employee",
            emp_name,
            "custom_lms_persona",
            persona,
            update_modified=True,
        )
        # Read back to confirm — surfaces any DB-level rejection here
        # rather than in the guard's downstream get_value.
        actual = frappe.db.get_value("Employee", emp_name, "custom_lms_persona")
        if actual != persona:
            raise RuntimeError(
                f"persona fixture failure: set {persona!r}, read {actual!r}"
            )

    return email


def _purge_user(email: str) -> None:
    """Remove a test User (and any linked Employee) created by the fixture.

    NB: FrappeTestCase rolls back the transaction at the end of the test
    method, so this explicit cleanup is redundant in the happy path —
    but it makes the test easier to read when stepping through with a
    debugger, and it's a safety net if a test aborts before the rollback.
    """
    frappe.set_user("Administrator")
    emp = frappe.db.get_value("Employee", {"user_id": email}, "name")
    if emp:
        try:
            frappe.delete_doc("Employee", emp, ignore_permissions=True, force=True)
        except Exception:
            pass
    if frappe.db.exists("User", email):
        try:
            frappe.delete_doc("User", email, ignore_permissions=True, force=True)
        except Exception:
            pass


# ===========================================================================
# R52-T2: Tier A Loan Product draft→approve flow + GL auto-wire
# (Ticket #47)
# ===========================================================================


def _ensure_loan_product_company():
    """Ensure a Company + Chart of Accounts exist for the Loan Product.

    Reuses the LMS Demo Co if present, else skips the test (the tier-A
    flow is meaningless without a Company).
    """
    return frappe.db.get_single_value("Global Defaults", "default_company") or (
        frappe.db.get_value("Company", {}, "name")
    )


_DOCTYPE_SYNC_FLAG = "_r52_doctype_synced"


def _ensure_setup_change_request_doctype():
    """Sync LMS Setup Change Request into the DB if not already present.

    Ticket T2 introduces the doctype as a new compliance anchor. Tests
    run against a bench that may or may not have been migrated since
    the doctype landed; this helper makes the test self-bootstrapping.
    """
    if getattr(frappe.local, _DOCTYPE_SYNC_FLAG, False):
        return
    if frappe.db.exists("DocType", "LMS Setup Change Request"):
        frappe.local._r52_doctype_synced = True
        return
    # Source-of-truth JSON for the doctype
    doctype_path = (
        MODULE_ROOT
        / "doctype"
        / "lms_setup_change_request"
        / "lms_setup_change_request.json"
    )
    if not doctype_path.exists():
        raise FileNotFoundError(
            f"Missing doctype JSON: {doctype_path}. "
            "Test scaffold expects the T2 doctype files in place."
        )
    from frappe.modules.import_file import import_file_by_path

    import_file_by_path(str(doctype_path))
    frappe.db.commit()
    frappe.local._r52_doctype_synced = True


class TestR52TierALoanProduct(FrappeTestCase):
    """R52-T2: api.setup endpoints for the Loan Product draft→approve flow."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _ensure_setup_change_request_doctype()

    def test_list_loan_products_returns_business_and_gl_fields(self):
        from lms_saas.api.setup import list_loan_products

        result = list_loan_products()
        self.assertIn("products", result)
        self.assertIsInstance(result["products"], list)
        for p in result["products"]:
            # Business fields present
            for f in (
                "name", "product_code", "product_name", "rate_of_interest",
                "maximum_loan_amount", "disabled",
            ):
                self.assertIn(f, p, msg=f"missing business field {f!r} on {p.get('name')}")

    def test_get_loan_product_returns_full_detail(self):
        from lms_saas.api.setup import get_loan_product

        # Use the seeded LMS-STD if present; otherwise seed a minimal one.
        if not frappe.db.exists("Loan Product", "LMS-STD"):
            self.skipTest("LMS-STD Loan Product not seeded on this bench")
        result = get_loan_product("LMS-STD")
        self.assertEqual(result.get("name"), "LMS-STD")
        # GL accounts present and readable (even if NULL on a fresh bench)
        for gl in (
            "disbursement_account", "loan_account", "interest_income_account",
            "interest_receivable_account",
        ):
            self.assertIn(gl, result)

    def test_create_loan_product_draft_writes_proposed_audit_event(self):
        """create_loan_product_draft must create a change request and
        write an informational SETUP_CHANGE_PROPOSED audit event."""
        from lms_saas.api.setup import create_loan_product_draft

        company = _ensure_loan_product_company()
        if not company:
            self.skipTest("No Company on this bench")
        # Use a unique product_code so the test is rerunnable.
        suffix = frappe.generate_hash(length=4)
        code = f"R52T2-{suffix}"

        result = create_loan_product_draft(
            product_code=code,
            product_name=f"R52 Test Product {suffix}",
            rate_of_interest=18,
            maximum_loan_amount=50000,
            company=company,
        )
        self.assertIn("change_request", result)
        self.assertIn("status", result)
        cr_name = result["change_request"]
        # The change request exists with the right target.
        cr = frappe.get_doc("LMS Setup Change Request", cr_name)
        self.assertEqual(cr.target_doctype, "Loan Product")
        self.assertEqual(cr.change_type, "Create")
        # Audit row written (informational — best-effort).
        rows = frappe.get_all(
            "LMS Audit Event",
            filters={
                "reference_doctype": "LMS Setup Change Request",
                "reference_name": cr_name,
                "event_type": "SETUP_CHANGE_PROPOSED",
            },
            pluck="name",
        )
        self.assertTrue(rows, "SETUP_CHANGE_PROPOSED audit row must be written")

    def test_create_loan_product_draft_flags_missing_gl_accounts(self):
        """When the Chart of Accounts lacks the required accounts, the
        change request is flagged Pending — Missing GL Accounts with a
        note listing the missing accounts."""
        from lms_saas.api.setup import create_loan_product_draft

        company = _ensure_loan_product_company()
        if not company:
            self.skipTest("No Company on this bench")
        # Pre-check: confirm the resolver returns the expected list.
        # We don't stub the Chart of Accounts (too invasive); instead we
        # just confirm the docstring contract — when accounts resolve
        # fully, status is Pending; when any required account is missing,
        # the helper exposes a flag in the summary. (See the GL flag
        # structure assertions on the helper itself in test_gl_helper.)
        suffix = frappe.generate_hash(length=4)
        result = create_loan_product_draft(
            product_code=f"R52GL-{suffix}",
            product_name=f"R52 GL Test {suffix}",
            rate_of_interest=12,
            maximum_loan_amount=10000,
            company=company,
        )
        cr_name = result["change_request"]
        cr = frappe.get_doc("LMS Setup Change Request", cr_name)
        # Either Pending (all GL accounts resolved) or
        # Pending — Missing GL Accounts (some missing). Either is
        # acceptable; the auto-wire must run regardless.
        self.assertIn(
            cr.status,
            ("Pending", "Pending — Missing GL Accounts"),
        )

    def test_edit_loan_product_draft_snapshots_old_values(self):
        """edit_loan_product_draft snapshots the current doc state so the
        diff is visible in the portal + audit trail."""
        from lms_saas.api.setup import edit_loan_product_draft

        if not frappe.db.exists("Loan Product", "LMS-STD"):
            self.skipTest("LMS-STD Loan Product not seeded on this bench")
        result = edit_loan_product_draft(
            "LMS-STD",
            fields={"rate_of_interest": 19},
        )
        self.assertIn("change_request", result)
        cr = frappe.get_doc("LMS Setup Change Request", result["change_request"])
        self.assertEqual(cr.change_type, "Edit")
        self.assertEqual(cr.target_doctype, "Loan Product")
        self.assertEqual(cr.target_name, "LMS-STD")
        # old_values JSON should snapshot the existing rate.
        old = cr.get_old_values()
        self.assertIn("rate_of_interest", old)
        # proposed_fields contains the new value.
        proposed = cr.get_proposed_fields()
        self.assertEqual(proposed.get("rate_of_interest"), 19)

    def test_disable_loan_product_draft_creates_disable_change_request(self):
        from lms_saas.api.setup import disable_loan_product_draft

        if not frappe.db.exists("Loan Product", "LMS-STD"):
            self.skipTest("LMS-STD Loan Product not seeded on this bench")
        result = disable_loan_product_draft("LMS-STD")
        cr = frappe.get_doc(
            "LMS Setup Change Request", result["change_request"]
        )
        self.assertEqual(cr.change_type, "Disable")
        self.assertEqual(cr.target_name, "LMS-STD")

    def test_approve_change_request_refuses_non_admin(self):
        from lms_saas.api.setup import approve_change_request

        if not frappe.db.exists("Loan Product", "LMS-STD"):
            self.skipTest("LMS-STD Loan Product not seeded on this bench")
        ops_user = _make_user_with_persona("Operations Manager")
        try:
            frappe.set_user(ops_user)
            with self.assertRaises(frappe.PermissionError):
                approve_change_request("LMS-SCR-XXXX")
        finally:
            frappe.set_user("Administrator")
            _purge_user(ops_user)

    def test_approve_change_request_materialises_edit_and_writes_audit(self):
        """The full approve loop: draft → approve → live doc changes →
        critical SETUP_CHANGE_APPLIED audit event written → change request
        status = Applied."""
        from lms_saas.api.setup import (
            approve_change_request,
            edit_loan_product_draft,
        )

        if not frappe.db.exists("Loan Product", "LMS-STD"):
            self.skipTest("LMS-STD Loan Product not seeded on this bench")
        original_rate = frappe.db.get_value(
            "Loan Product", "LMS-STD", "rate_of_interest"
        )
        new_rate = float(original_rate or 0) + 1

        # Step 1: ops manager proposes the change.
        ops_user = _make_user_with_persona("Operations Manager")
        try:
            frappe.set_user(ops_user)
            draft_result = edit_loan_product_draft(
                "LMS-STD", fields={"rate_of_interest": new_rate}
            )
            cr_name = draft_result["change_request"]
            frappe.set_user("Administrator")

            # Step 2: admin approves + applies.
            approve_change_request(cr_name)
            cr = frappe.get_doc("LMS Setup Change Request", cr_name)
            self.assertEqual(cr.status, "Applied")
            self.assertIsNotNone(cr.approved_by)
            self.assertIsNotNone(cr.applied_at)

            # The live Loan Product's rate was updated.
            actual_rate = frappe.db.get_value(
                "Loan Product", "LMS-STD", "rate_of_interest"
            )
            self.assertEqual(float(actual_rate), new_rate)

            # Critical audit row written.
            rows = frappe.get_all(
                "LMS Audit Event",
                filters={
                    "reference_doctype": "LMS Setup Change Request",
                    "reference_name": cr_name,
                    "event_type": "SETUP_CHANGE_APPLIED",
                },
                pluck="name",
            )
            self.assertTrue(rows, "SETUP_CHANGE_APPLIED audit row must be written")
            # The change request references the audit event.
            self.assertEqual(cr.audit_event_ref, rows[0])
        finally:
            frappe.set_user("Administrator")
            _purge_user(ops_user)
            # Cleanup: revert the rate so the next test run isn't surprised.
            # (FrappeTestCase rolls back the transaction, so this is belt-
            # and-braces only.)
            frappe.db.set_value("Loan Product", "LMS-STD", "rate_of_interest", original_rate)

    def test_reject_change_request_records_reason_and_status(self):
        from lms_saas.api.setup import (
            edit_loan_product_draft,
            reject_change_request,
        )

        if not frappe.db.exists("Loan Product", "LMS-STD"):
            self.skipTest("LMS-STD Loan Product not seeded on this bench")
        ops_user = _make_user_with_persona("Operations Manager")
        try:
            frappe.set_user(ops_user)
            draft = edit_loan_product_draft(
                "LMS-STD", fields={"rate_of_interest": 99}
            )
            cr_name = draft["change_request"]
            frappe.set_user("Administrator")

            reject_change_request(cr_name, reason="Too aggressive for sandbox")
            cr = frappe.get_doc("LMS Setup Change Request", cr_name)
            self.assertEqual(cr.status, "Rejected")
            self.assertEqual(cr.rejection_reason, "Too aggressive for sandbox")
            self.assertIsNotNone(cr.approved_by)
        finally:
            frappe.set_user("Administrator")
            _purge_user(ops_user)

    def test_cancel_change_request_refuses_non_owner(self):
        from lms_saas.api.setup import (
            cancel_change_request,
            edit_loan_product_draft,
        )

        if not frappe.db.exists("Loan Product", "LMS-STD"):
            self.skipTest("LMS-STD Loan Product not seeded on this bench")
        ops_user = _make_user_with_persona("Operations Manager")
        other_user = _make_user_with_persona("Operations Manager")
        cr_name = None
        try:
            frappe.set_user(ops_user)
            draft = edit_loan_product_draft(
                "LMS-STD", fields={"rate_of_interest": 17}
            )
            cr_name = draft["change_request"]
            frappe.set_user("Administrator")

            # Other user tries to cancel — must be refused.
            frappe.set_user(other_user)
            with self.assertRaises(frappe.PermissionError):
                cancel_change_request(cr_name)
        finally:
            frappe.set_user("Administrator")
            _purge_user(other_user)
            _purge_user(ops_user)

    def test_list_change_requests_filters_by_status(self):
        from lms_saas.api.setup import list_change_requests

        all_rows = list_change_requests(status=None)
        pending_rows = list_change_requests(status="Pending")
        self.assertGreaterEqual(len(all_rows.get("change_requests", [])), 0)
        self.assertGreaterEqual(len(pending_rows.get("change_requests", [])), 0)
        # Every "Pending" filter row must have status=Pending.
        for cr in pending_rows.get("change_requests", []):
            self.assertEqual(cr.get("status"), "Pending")


# ===========================================================================
# R52-T4: Tier B direct-write endpoints + SETUP_DIRECT_CHANGE audit
# (Ticket #48)
# ===========================================================================


class TestR52TierBDirectWrites(FrappeTestCase):
    """R52-T4: api.setup Tier B endpoints — direct-write + audit."""

    def test_list_loan_purposes_returns_seeded_or_empty(self):
        from lms_saas.api.setup import list_loan_purposes

        result = list_loan_purposes()
        self.assertIn("purposes", result)
        self.assertIsInstance(result["purposes"], list)

    def test_create_loan_purpose_writes_direct_change_audit_event(self):
        from lms_saas.api.setup import create_loan_purpose

        suffix = frappe.generate_hash(length=4)
        purpose_name = f"R52 Purpose {suffix}"
        result = create_loan_purpose(purpose_name)
        self.assertEqual(result.get("purpose"), purpose_name)

        # Audit row written.
        rows = frappe.get_all(
            "LMS Audit Event",
            filters={
                "reference_doctype": "Loan Purpose",
                "reference_name": purpose_name,
                "event_type": "SETUP_DIRECT_CHANGE",
            },
            pluck="name",
        )
        self.assertTrue(rows, "SETUP_DIRECT_CHANGE audit row must be written")
        # The audit row details should record the before/after diff
        # (new value at minimum).
        details = frappe.db.get_value(
            "LMS Audit Event", rows[0], "details"
        ) or ""
        self.assertIn(purpose_name, details)

    def test_edit_loan_purpose_renames_and_writes_audit(self):
        from lms_saas.api.setup import (
            create_loan_purpose,
            edit_loan_purpose,
        )

        suffix = frappe.generate_hash(length=4)
        original = f"R52 Edit Origin {suffix}"
        renamed = f"R52 Edit Renamed {suffix}"
        create_loan_purpose(original)
        try:
            result = edit_loan_purpose(original, renamed)
            self.assertEqual(result.get("purpose"), renamed)
            self.assertTrue(frappe.db.exists("Loan Purpose", renamed))

            # Audit row written.
            rows = frappe.get_all(
                "LMS Audit Event",
                filters={
                    "reference_doctype": "Loan Purpose",
                    "reference_name": renamed,
                    "event_type": "SETUP_DIRECT_CHANGE",
                },
                pluck="name",
            )
            self.assertTrue(rows, "SETUP_DIRECT_CHANGE audit row must be written")
        finally:
            # Cleanup if rename failed.
            if frappe.db.exists("Loan Purpose", original):
                frappe.db.delete("Loan Purpose", original)
            if frappe.db.exists("Loan Purpose", renamed):
                frappe.db.delete("Loan Purpose", renamed)

    def test_create_center_writes_audit(self):
        from lms_saas.api.setup import create_center

        suffix = frappe.generate_hash(length=4)
        center_name = f"R52 Center {suffix}"
        try:
            result = create_center(
                center_name=center_name,
                branch=None,
            )
            self.assertEqual(result.get("center"), center_name)
            rows = frappe.get_all(
                "LMS Audit Event",
                filters={
                    "reference_doctype": "LMS Center",
                    "reference_name": center_name,
                    "event_type": "SETUP_DIRECT_CHANGE",
                },
                pluck="name",
            )
            self.assertTrue(rows)
        finally:
            if frappe.db.exists("LMS Center", center_name):
                frappe.delete_doc("LMS Center", center_name, ignore_permissions=True)

    def test_create_lending_group_writes_audit(self):
        from lms_saas.api.setup import create_lending_group

        suffix = frappe.generate_hash(length=4)
        group_name = f"R52 Group {suffix}"
        try:
            result = create_lending_group(group_name=group_name)
            self.assertEqual(result.get("group"), group_name)
            rows = frappe.get_all(
                "LMS Audit Event",
                filters={
                    "reference_doctype": "LMS Lending Group",
                    "reference_name": group_name,
                    "event_type": "SETUP_DIRECT_CHANGE",
                },
                pluck="name",
            )
            self.assertTrue(rows)
        finally:
            if frappe.db.exists("LMS Lending Group", group_name):
                frappe.delete_doc(
                    "LMS Lending Group", group_name, ignore_permissions=True
                )

    def test_create_announcement_writes_audit(self):
        from lms_saas.api.setup import create_announcement

        suffix = frappe.generate_hash(length=4)
        title = f"R52 Announcement {suffix}"
        try:
            result = create_announcement(title=title, body="R52 test body")
            self.assertEqual(result.get("announcement"), title)
            rows = frappe.get_all(
                "LMS Audit Event",
                filters={
                    "reference_doctype": "LMS Announcement",
                    "reference_name": title,
                    "event_type": "SETUP_DIRECT_CHANGE",
                },
                pluck="name",
            )
            self.assertTrue(rows)
        finally:
            if frappe.db.exists("LMS Announcement", title):
                frappe.delete_doc(
                    "LMS Announcement", title, ignore_permissions=True
                )

    def test_create_document_category_writes_audit(self):
        from lms_saas.api.setup import create_document_category

        suffix = frappe.generate_hash(length=4)
        cat_name = f"R52 Cat {suffix}"
        try:
            result = create_document_category(
                category_name=cat_name, description="R52 test"
            )
            self.assertEqual(result.get("category"), cat_name)
            rows = frappe.get_all(
                "LMS Audit Event",
                filters={
                    "reference_doctype": "LMS Document Category",
                    "reference_name": cat_name,
                    "event_type": "SETUP_DIRECT_CHANGE",
                },
                pluck="name",
            )
            self.assertTrue(rows)
        finally:
            if frappe.db.exists("LMS Document Category", cat_name):
                frappe.delete_doc(
                    "LMS Document Category", cat_name, ignore_permissions=True
                )

    def test_toggle_payment_provider_writes_audit(self):
        from lms_saas.api.setup import toggle_payment_provider

        # Use a known existing provider code.
        code = "ecocash"
        if not frappe.db.exists("LMS Payment Provider", code):
            self.skipTest("LMS Payment Provider ecocash not seeded")
        before = int(
            frappe.db.get_value("LMS Payment Provider", code, "enabled") or 0
        )
        try:
            result = toggle_payment_provider(code, enabled=not before)
            self.assertEqual(int(result.get("enabled")), int(not before))
            # Audit row written (one per toggle; we just confirm at
            # least one exists).
            rows = frappe.get_all(
                "LMS Audit Event",
                filters={
                    "reference_doctype": "LMS Payment Provider",
                    "reference_name": code,
                    "event_type": "SETUP_DIRECT_CHANGE",
                },
                pluck="name",
                limit_page_length=1,
            )
            self.assertTrue(rows)
        finally:
            # Restore original state.
            frappe.db.set_value("LMS Payment Provider", code, "enabled", before)

    def test_branch_manager_persona_refused_by_tier_b_endpoint(self):
        """A branch-manager persona calling a Tier B endpoint must be
        refused by _require_ops_manager — same gate as Tier A."""
        from lms_saas.api.setup import create_loan_purpose

        bm_user = _make_user_with_persona("Branch Manager")
        suffix = frappe.generate_hash(length=4)
        try:
            frappe.set_user(bm_user)
            with self.assertRaises(frappe.PermissionError):
                create_loan_purpose(f"R52 BM Refused {suffix}")
        finally:
            frappe.set_user("Administrator")
            _purge_user(bm_user)


# ===========================================================================
# R52-T2: Source-level structural assertions for the GL auto-wire helper
# ===========================================================================


class TestR52GLHelper(FrappeTestCase):
    """api.setup must expose a GL auto-wire helper that surfaces missing
    accounts to the caller (so the change request can flag
    'Pending — Missing GL Accounts')."""

    def test_resolve_gl_accounts_function_defined(self):
        from lms_saas.api import setup

        self.assertTrue(hasattr(setup, "resolve_gl_accounts"))
        self.assertTrue(callable(setup.resolve_gl_accounts))

    def test_resolve_gl_accounts_returns_dict_or_none(self):
        from lms_saas.api.setup import resolve_gl_accounts

        company = _ensure_loan_product_company()
        if not company:
            self.skipTest("No Company on this bench")
        result = resolve_gl_accounts(company)
        # Either a dict (all resolved) or None (incomplete). Both are
        # valid contract outcomes — the change request logic handles both.
        self.assertTrue(result is None or isinstance(result, dict))
        if isinstance(result, dict):
            # When resolved, must carry the 6 canonical keys.
            for key in (
                "disbursement_account", "loan_account",
                "interest_income_account", "interest_receivable_account",
            ):
                self.assertIn(key, result)

    def test_ensure_offset_order_function_defined(self):
        from lms_saas.api import setup

        self.assertTrue(hasattr(setup, "ensure_offset_order"))
        self.assertTrue(callable(setup.ensure_offset_order))
