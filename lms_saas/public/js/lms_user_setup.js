/* LMS User Setup — conditional field visibility driven by the Persona select.
 *
 * No business logic lives here (the server on_submit is the single source of
 * truth). This only shows/hides the persona-specific sections so the end user
 * sees a clean, normal-looking form. The desk theme (lms_desk.js) applies the
 * uniform app chrome automatically because "LMS User Setup" is in
 * LMS_FORM_DOCTYPES.
 */
frappe.ui.form.on("LMS User Setup", {
	setup: function (frm) {
		// Pre-filter the Branch link to non-group Cost Centers (branches), so the
		// picker doesn't show parent/group cost centers that aren't real branches.
		frm.set_query("branch", function () {
			return {
				filters: { is_group: 0 },
			};
		});
	},

	onload: function (frm) {
		// Default the branch to the current user's branch when known. The desk
		// staff's branch is the Cost Center on their Employee record (or the
		// User Permission on Cost Center). Resolved server-side to stay DRY and
		// avoid relying on a boot structure that may not be present.
		if (frm.is_new() && !frm.doc.branch) {
			frappe.call({
				method: "lms_saas.lms_saas.api.staff.get_current_user_branch",
				callback: function (r) {
					if (r && r.message) {
						frm.set_value("branch", r.message);
					}
				},
			});
		}
	},

	refresh: function (frm) {
		// After submit the created-record links are read-only; make them clickable.
		if (frm.doc.created_user) {
			frm.set_df_property("created_user", "read_only", 1);
			frm.set_df_property("created_customer", "read_only", 1);
			frm.set_df_property("created_employee", "read_only", 1);
		}
		// Keep the persona-driven sections in sync on refresh too.
		lms_user_setup_toggle_sections(frm);
	},

	persona: function (frm) {
		lms_user_setup_toggle_sections(frm);
		// Clear persona-specific fields when switching personas to avoid stale
		// values leaking across personas (e.g. national_id left on a staff record).
		var persona = frm.doc.persona;
		if (persona !== "Borrower") {
			frm.set_value("national_id", "");
		}
	},
});

function lms_user_setup_toggle_sections(frm) {
	var persona = frm.doc.persona;
	var isBorrower = persona === "Borrower";
	var isStaff = persona && !isBorrower;

	// Staff-only fields
	frm.toggle_display("branch", isStaff);
	frm.toggle_display("department", isStaff);
	frm.toggle_display("gender", isStaff);
	frm.toggle_display("date_of_birth", isStaff);
	frm.toggle_reqd("branch", !!isStaff);

	// Borrower-only fields
	frm.toggle_display("national_id", isBorrower);
	frm.toggle_reqd("national_id", !!isBorrower);
}