import frappe
from frappe.model.document import Document
from frappe.utils import random_string


class LMSAPIKey(Document):
	def before_insert(self):
		if not self.api_key:
			self.api_key = random_string(32)
		if not self.api_secret:
			self.api_secret = random_string(48)
