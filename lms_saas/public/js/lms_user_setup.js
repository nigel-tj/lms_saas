/* LMS User Setup — conditional field visibility driven by the Persona select.
 *
 * No business logic lives here (the server on_submit is the single source of
 * truth). This only shows/hides the persona-specific sections so the end user
 * sees a clean, normal-looking form. The desk theme (lms_desk.js) applies the
 * uniform app chrome automatically because "LMS User Setup" is in
 * LMS_FORM_DOCTYPES.
 *
 * DRY boundaries:
 *   - Persona metadata (which roles, which records) lives in
 *     lms_saas.install.PERSONA_CONFIG — this file does not duplicate it.
 *   - Field-options lists live in the DocType JSON (lms_user_setup.json) —
 *     these conditional toggles here only flip reqd/display.
 *   - The branch lookup for the signed-in user lives server-side in
 *     lms_saas.api.staff.get_current_user_branch — we call it, not duplicate
 *     it.
 */
frappe.ui.form.on("LMS User Setup", {
	setup: function (frm) {
		// Pre-filter the Branch link to non-group Cost Centers (branches), so
		// the picker doesn't show parent/group cost centers that aren't real
		// branches.
		frm.set_query("branch", function () {
			return {
				filters: { is_group: 0 },
			};
		});
	},

	onload: function (frm) {
		// Default the branch to the current user's branch when known. Resolved
		// server-side in lms_saas.api.staff.get_current_user_branch so we do
		// not reimplement branch resolution on the client.
		if (frm.is_new() && !frm.doc.branch) {
			frappe.call({
				method: "lms_saas.api.staff.get_current_user_branch",
				callback: function (r) {
					if (r && r.message) {
						frm.set_value("branch", r.message);
					}
				},
			});
		}
	},

	refresh: function (frm) {
		lms_user_setup_toggle_sections(frm);

		// After submit the created-record links are read-only; make them
		// clickable.
		if (frm.doc.created_user) {
			frm.set_df_property("created_user", "read_only", 1);
			frm.set_df_property("created_customer", "read_only", 1);
			frm.set_df_property("created_employee", "read_only", 1);
		}

		// R26-P4-6: when Admin persona is selected on a draft, surface a
		// warning — Admin grants full System Manager + Desk User roles, which
		// is a powerful privilege to grant by accident.
		lms_user_setup_warn_admin(frm);
	},

	persona: function (frm) {
		lms_user_setup_toggle_sections(frm);
		// Clear persona-specific fields when switching personas to avoid stale
		// values leaking across personas (e.g. national_id left on a staff
		// record).
		var persona = frm.doc.persona;
		if (persona !== "Borrower") {
			frm.set_value("national_id", "");
		}
		lms_user_setup_warn_admin(frm);
	},
});

/**
 * R26-P4-6 — soft alert when the operator selects Admin on a draft. The
 * server grants System Manager + Desk User roles atomically; we surface that
 * fact client-side so a slip-of-the-click does not become a privilege grant.
 */
function lms_user_setup_warn_admin(frm) {
	if (!frm.is_new) return;
	if (frm.doc.persona === "Admin") {
		frappe.show_alert(
			{
				message: __(
					"Admin persona grants System Manager + Desk User roles (full desk access). Confirm before submitting."
				),
				indicator: "orange",
			},
			7
		);
	}
}

/**
 * Toggle persona-driven sections. Single source of truth lives in the
 * DocType JSON's `depends_on` AND the Python validator; this only enforces
 * `reqd` (which Frappe does not expose declaratively) so the operator sees a
 * bright red asterisk on form load.
 */
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
