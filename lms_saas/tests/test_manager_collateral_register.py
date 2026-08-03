from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase, mock

from lms_saas.api import manager as mgr


class TestManagerCollateralRegister(TestCase):
	def test_collateral_surfaces_without_loan_child_link(self):
		collateral_row = {
			"name": "COL-00001",
			"collateral_title": "Toyota Hilux 2019",
			"collateral_type": "Vehicle",
			"market_value": 18000,
			"net_realizable_value": 14400,
			"status": "Pledged",
			"owner_customer": "CUST-0001",
			"branch": "",
			"loan_application": "APP-0001",
		}
		fake_frappe = SimpleNamespace(
			get_all=mock.Mock(side_effect=[
				[collateral_row],  # LMS Collateral rows
				[{"name": "APP-0001", "custom_lms_branch": "Main Branch - LS"}],  # app branch batch
				[{"name": "CUST-0001", "custom_lms_branch": "Main Branch - LS"}],  # cust branch batch
				[],  # LMS Loan Collateral links
			]),
			db=SimpleNamespace(get_value=mock.Mock(return_value="Main Branch - LS")),
		)

		with mock.patch.object(mgr, "_require_manager"), \
			mock.patch.object(mgr, "_manager_branch", return_value="Main Branch - LS"), \
			mock.patch.object(mgr, "frappe", fake_frappe):
			out = mgr.get_collateral_register()

		self.assertEqual(len(out["collateral"]), 1)
		self.assertEqual(out["collateral"][0]["name"], "COL-00001")
		self.assertEqual(out["collateral"][0]["linked_loans"], [])
