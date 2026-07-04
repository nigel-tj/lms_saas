frappe.ui.form.on('LMS Investor', {
    setup: function(frm) {
        frm.set_query('investor_liability_account', function() {
            return {
                filters: {
                    company: frm.doc.company,
                    root_type: 'Liability',
                    account_type: ['not in', ['Payable']],
                    is_group: 0,
                },
            };
        });
    },
});
