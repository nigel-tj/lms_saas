frappe.ui.form.on('Loan', {
    refresh: function(frm) {
        // Strict compliance control: Prevent edits or adjustments to submitted financial documents
        if (frm.doc.docstatus === 1) {
            frm.disable_save();
            frm.page.clear_primary_action();
            frm.page.clear_secondary_action();
        }

        if (!frm.is_new()) {
            frm.add_custom_button(__('Generate Agreement'), function() {
                frappe.call({
                    method: 'lms_saas.api.documents.generate_loan_agreement_pdf',
                    args: { loan_id: frm.doc.name },
                    callback: function(r) {
                        if (r.message) {
                            window.open(frappe.urllib.get_full_url(r.message));
                        }
                    }
                });
            });
        }
    }
});
