import frappe
from frappe.model.document import Document
from frappe.utils import flt

from lms_saas.api.collateral import compute_net_realizable_value


class LMSCollateral(Document):
    def validate(self):
        if flt(self.market_value) <= 0 and flt(self.forced_sale_value) <= 0:
            frappe.throw("Provide a Market Value or Forced Sale Value for the collateral.")
        if flt(self.haircut_percent) < 0 or flt(self.haircut_percent) > 100:
            frappe.throw("Haircut % must be between 0 and 100.")
        if not self.status:
            self.status = "Pledged"
        self.net_realizable_value = compute_net_realizable_value(
            self.market_value, self.haircut_percent, self.forced_sale_value
        )
