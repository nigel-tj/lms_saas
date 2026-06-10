"""Ad-hoc collateral smoke test.

Run: bench --site lms.localhost execute lms_saas.setup.test_collateral_smoke.run
Safe to re-run; rolls back all writes at the end.
"""

import frappe
from frappe.utils import flt

from lms_saas.api import collateral as col_api


def run():
    out = {}
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    customer = frappe.db.get_value("Customer", {}, "name")
    branch = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

    # 1. NRV via haircut and via forced sale value
    out["nrv_haircut"] = col_api.compute_net_realizable_value(10000, 25)  # -> 7500
    out["nrv_forced"] = col_api.compute_net_realizable_value(10000, 25, 6000)  # -> 6000

    # 2. Create + submit a collateral record, confirm stored NRV
    doc = frappe.get_doc(
        {
            "doctype": "LMS Collateral",
            "collateral_title": "SMOKE TEST ASSET",
            "collateral_type": "Equipment / Machinery",
            "owner_customer": customer,
            "company": company,
            "branch": branch,
            "market_value": 10000,
            "haircut_percent": 25,
        }
    )
    doc.insert(ignore_permissions=True)
    doc.submit()
    out["collateral_name"] = doc.name
    out["stored_nrv"] = flt(doc.net_realizable_value)
    out["status_default"] = doc.status

    # 3. Coverage calc against a mock loan application doc (in-memory, not saved)
    app = frappe.new_doc("Loan Application")
    app.loan_amount = 5000
    app.append("custom_collateral", {"collateral": doc.name})
    coverage = col_api.get_collateral_coverage(app)
    out["coverage_ratio"] = coverage["coverage_ratio"]  # 7500/5000 = 1.5
    out["coverage_total_nrv"] = coverage["total_net_realizable_value"]

    # 4. Enforcement: simulate require + min coverage breach (over-amount loan)
    big_app = frappe.new_doc("Loan Application")
    big_app.loan_amount = 100000  # 7500 NRV -> 0.075x, below 1.25x
    big_app.append("custom_collateral", {"collateral": doc.name})
    breach_raised = False
    try:
        frappe.conf.lms_min_collateral_coverage = 1.25
        col_api.enforce_collateral_coverage(big_app, "before_submit")
    except frappe.ValidationError:
        breach_raised = True
    finally:
        frappe.conf.pop("lms_min_collateral_coverage", None)
    out["coverage_breach_blocked"] = breach_raised

    # 5. Require-collateral enforcement on empty application
    empty_app = frappe.new_doc("Loan Application")
    empty_app.loan_amount = 5000
    require_raised = False
    try:
        frappe.conf.lms_require_collateral = True
        col_api.enforce_collateral_coverage(empty_app, "before_submit")
    except frappe.ValidationError:
        require_raised = True
    finally:
        frappe.conf.pop("lms_require_collateral", None)
    out["require_collateral_blocked"] = require_raised

    # Roll back all writes so the smoke test leaves no residue.
    frappe.db.rollback()

    out["all_passed"] = (
        out["nrv_haircut"] == 7500.0
        and out["nrv_forced"] == 6000.0
        and out["stored_nrv"] == 7500.0
        and out["status_default"] == "Pledged"
        and out["coverage_ratio"] == 1.5
        and out["coverage_breach_blocked"] is True
        and out["require_collateral_blocked"] is True
    )
    return out
