/* LMS CRM — Lead desk actions */
frappe.ui.form.on("Lead", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("Convert to Borrower"), () => convert_to_borrower(frm), __("LMS"));
	},
});

function convert_to_borrower(frm) {
	if (!frm.doc.custom_consent_given) {
		frappe.msgprint({
			title: __("Consent required"),
			message: __("Record customer consent on this Lead before converting."),
			indicator: "orange",
		});
		return;
	}
	frappe.confirm(
		__("Create a Customer (and compliance stub when ID is set) from this Lead?"),
		() => {
			frappe.call({
				method: "lms_saas.api.crm.convert_lead_to_borrower",
				args: { lead_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Creating borrower…"),
				callback(r) {
					if (r.message && r.message.customer) {
						frappe.set_route("Form", "Customer", r.message.customer);
					}
				},
			});
		}
	);
}
