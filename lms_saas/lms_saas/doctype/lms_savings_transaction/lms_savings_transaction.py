import frappe
from frappe.model.document import Document
from frappe.utils import flt


class LMSSavingsTransaction(Document):
	def on_submit(self):
		self._post_gl()

	def on_cancel(self):
		if self.reference_journal_entry:
			je = frappe.get_doc("Journal Entry", self.reference_journal_entry)
			if je.docstatus == 1:
				je.cancel()

	def _post_gl(self):
		account = frappe.get_doc("LMS Savings Account", self.savings_account)
		liquid = _company_liquid_account(account.company)
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": account.company,
				"posting_date": self.posting_date,
				"voucher_type": "Journal Entry",
				"accounts": [],
			}
		)
		amount = flt(self.amount)
		if self.transaction_type == "Deposit":
			je.append("accounts", {"account": liquid, "debit": amount, "credit": 0})
			je.append(
				"accounts",
				{"account": account.liability_account, "party_type": "Customer", "party": account.customer, "debit": 0, "credit": amount},
			)
			new_balance = flt(account.balance) + amount
		else:
			je.append(
				"accounts",
				{"account": account.liability_account, "party_type": "Customer", "party": account.customer, "debit": amount, "credit": 0},
			)
			je.append("accounts", {"account": liquid, "debit": 0, "credit": amount})
			new_balance = flt(account.balance) - amount

		je.insert(ignore_permissions=True)
		je.submit()
		self.db_set("reference_journal_entry", je.name)
		frappe.db.set_value("LMS Savings Account", account.name, "balance", new_balance)


def _company_liquid_account(company):
	name = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Bank", "is_group": 0},
		"name",
	)
	if not name:
		name = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Cash", "is_group": 0},
			"name",
		)
	return name
