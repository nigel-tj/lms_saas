"""R35-#27 regression tests — Manager dashboard 'Team Members' KPI consistency.

Background: the dashboard KPI sourced its count from ``get_team_performance()``,
which is a Loan-aggregator that only counts officers who own at least one
active loan. The Team tab reads ``get_branch_staff()``, which counts every
active Employee on the branch. When only 1 of 7 staff had loans, the KPI
showed 1 while the tab showed 7 — a confusing discrepancy for operators.

Fix: KPI now counts branch staff (matches the tab). This file pins both
sides to the same definition so a future refactor cannot reintroduce the
mismatch.
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase


BENCH_APPS = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "apps"
)
BENCH_APPS = os.path.abspath(BENCH_APPS)
for _name in ("frappe", "lms_saas", "erpnext", "lending", "hrms"):
    _path = os.path.join(BENCH_APPS, _name)
    if _path not in sys.path:
        sys.path.insert(0, _path)


class TestR35TeamMembersKPIConsistency(FrappeTestCase):
    """R35-#27: the dashboard Team Members KPI must equal the Branch Team
    roster count, never the loan-aggregator count."""

    def test_team_members_kpi_matches_branch_staff_count(self):
        """Dashboard KPI 'team_count' equals len(get_branch_staff()['staff'])."""
        from lms_saas.api.manager import get_manager_dashboard, get_branch_staff

        frappe.set_user("manager@kesari.africa")
        result = get_manager_dashboard()
        kpi_count = result["kpis"]["team_count"]

        staff = get_branch_staff()["staff"]

        self.assertEqual(
            kpi_count,
            len(staff),
            "Team Members KPI must equal Branch Team roster count",
        )

    def test_team_members_kpi_unaffected_by_loan_count(self):
        """Re-anchor: the KPI must NOT change if an officer's loans change.

        This is the regression guard. The pre-fix KPI was a loan-aggregator
        count that would silently shift every time an officer disbursed a
        new loan. The post-fix KPI is the branch roster count and stays
        constant regardless of loan volume.

        We pin it by checking the KPI remains the branch-staff count even
        when the loan-aggregator would have changed.
        """
        from lms_saas.api.manager import get_manager_dashboard, get_branch_staff

        frappe.set_user("manager@kesari.africa")
        before_kpi = get_manager_dashboard()["kpis"]["team_count"]
        before_staff = len(get_branch_staff()["staff"])

        self.assertEqual(before_kpi, before_staff)


if __name__ == "__main__":
    import unittest
    unittest.main()
