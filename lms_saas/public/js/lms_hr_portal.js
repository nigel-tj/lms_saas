/* LMS HR Management portal — leave, attendance, expenses, shifts, directory */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_hr");
} else {
	window.lms_hr = window.lms_hr || {};
}

lms_hr._currentTab = "dashboard";

lms_hr.init = function () {
	var root = document.getElementById("lms-hr-root");
	if (!root) return;

	var tabs = [
		{ id: "dashboard", label: "Dashboard", icon: "📊" },
		{ id: "leaves", label: "Leave Approvals", icon: "📅" },
		{ id: "attendance", label: "Attendance", icon: "✅" },
		{ id: "expenses", label: "Expenses", icon: "💰" },
		{ id: "shifts", label: "Shift Requests", icon: "⏰" },
		{ id: "directory", label: "Directory", icon: "👥" },
	];
	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "HR Management" }) +
		lms_portal.tabNav(tabs, lms_hr._currentTab) +
		'<div id="lms-hr-tab-content"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_portal.bindTabs({
		root: root,
		tabs: tabs,
		onTab: function (tabId) { lms_hr._currentTab = tabId; lms_hr._showTab(tabId); },
	});

	lms_hr._showTab(lms_hr._currentTab);
};

lms_hr._showTab = function (tabId) {
	var content = document.getElementById("lms-hr-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "dashboard") lms_hr._loadDashboard(content);
	else if (tabId === "leaves") lms_hr._loadLeaves(content);
	else if (tabId === "attendance") lms_hr._loadAttendance(content);
	else if (tabId === "expenses") lms_hr._loadExpenses(content);
	else if (tabId === "shifts") lms_hr._loadShifts(content);
	else if (tabId === "directory") lms_hr._loadDirectory(content);
};

lms_hr._loadDashboard = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.get_hr_dashboard",
		callback: function (r) {
			var d = (r && r.message) || {};
			content.innerHTML = lms_portal.kpiStrip([
				{ label: "Team Members", value: d.team_count || 0 },
				{ label: "Present Today", value: d.present_today || 0, tone: "success" },
				{ label: "Absent Today", value: d.absent_today || 0, tone: "danger" },
				{ label: "Pending Leaves", value: d.pending_leaves || 0, tone: "warning" },
				{ label: "Pending Expenses", value: d.pending_expenses || 0, tone: "warning" },
				{ label: "Shift Requests", value: d.pending_shift_requests || 0 },
			]);
		},
	});
};

lms_hr._loadLeaves = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.get_pending_leaves",
		callback: function (r) {
			var leaves = (r && r.message && r.message.leaves) || [];
			if (!leaves.length) {
				content.innerHTML = lms_portal.emptyPanel("✓", "All caught up", "No leave applications pending.");
				return;
			}
			var body = '<div class="lms-data-table__wrap"><table class="lms-data-table">';
			body += "<thead><tr><th>Employee</th><th>Type</th><th>From</th><th>To</th><th>Days</th><th>Actions</th></tr></thead><tbody>";
			leaves.forEach(function (l) {
				body += "<tr>";
				body += "<td><strong>" + lms_portal.escape(l.employee_name) + "</strong></td>";
				body += "<td>" + lms_portal.escape(l.leave_type) + "</td>";
				body += "<td>" + lms_portal.formatDate(l.from_date) + "</td>";
				body += "<td>" + lms_portal.formatDate(l.to_date) + "</td>";
				body += "<td>" + (l.total_leave_days || 0) + "</td>";
				body += '<td><div class="lms-data-table__actions">';
				body += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-hr-approve-leave" data-name="' + lms_portal.escape(l.name) + '">Approve</button>';
				body += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-hr-reject-leave" data-name="' + lms_portal.escape(l.name) + '">Reject</button>';
				body += '</div></td></tr>';
			});
			body += "</tbody></table></div>";
			content.innerHTML = lms_portal.panel({ body: body });

			content.querySelectorAll(".lms-hr-approve-leave").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_hr._processLeave(btn.getAttribute("data-name"), "Approved");
				});
			});
			content.querySelectorAll(".lms-hr-reject-leave").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_hr._processLeave(btn.getAttribute("data-name"), "Rejected");
				});
			});
		},
	});
};

lms_hr._processLeave = function (name, status) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.approve_leave",
		args: { leave_name: name, status: status },
		callback: function () {
			lms_portal.toast("Leave " + status, status === "Approved" ? "success" : "warning");
			lms_hr._showTab("leaves");
		},
		error: function () {
			lms_portal.toast("Could not process leave.", "danger");
		},
	});
};

lms_hr._loadAttendance = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.get_attendance_today",
		callback: function (r) {
			var data = (r && r.message) || {};
			var records = data.records || [];
			var absentees = data.absentees || [];
			var html = lms_portal.pageStart();
			// Present
			var presentBody = "<h3>Present (" + records.length + ")</h3>";
			if (records.length) {
				presentBody += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Employee</th><th>Status</th><th>In Time</th><th>Out Time</th></tr></thead><tbody>';
				records.forEach(function (a) {
					presentBody += "<tr><td><strong>" + lms_portal.escape(a.employee_name) + "</strong></td>";
					presentBody += '<td><span class="lms-badge lms-badge--success">' + lms_portal.escape(a.status) + "</span></td>";
					presentBody += "<td>" + lms_portal.escape(a.in_time || "—") + "</td>";
					presentBody += "<td>" + lms_portal.escape(a.out_time || "—") + "</td></tr>";
				});
				presentBody += "</tbody></table></div>";
			} else {
				presentBody += '<p class="lms-muted">No attendance records for today.</p>';
			}
			html += lms_portal.panel({ body: presentBody });

			// Absentees
			if (absentees.length) {
				var absBody = "<h3>Absentees / No Record (" + absentees.length + ")</h3>" +
					'<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Employee</th><th>Status</th></tr></thead><tbody>';
				absentees.forEach(function (a) {
					absBody += "<tr><td><strong>" + lms_portal.escape(a.employee_name) + "</strong></td>";
					absBody += '<td><span class="lms-badge lms-badge--warning">' + lms_portal.escape(a.status) + "</span></td></tr>";
				});
				absBody += "</tbody></table></div>";
				html += lms_portal.panel({ body: absBody });
			}
			html += lms_portal.pageEnd();
			content.innerHTML = html;
		},
	});
};

lms_hr._loadExpenses = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.get_pending_expenses",
		callback: function (r) {
			var claims = (r && r.message && r.message.claims) || [];
			if (!claims.length) {
				content.innerHTML = lms_portal.emptyPanel("✓", "All caught up", "No expense claims pending.");
				return;
			}
			var body = '<div class="lms-data-table__wrap"><table class="lms-data-table">' +
				"<thead><tr><th>Employee</th><th>Type</th><th>Amount</th><th>Date</th><th>Actions</th></tr></thead><tbody>";
			claims.forEach(function (c) {
			body += "<tr>";
			body += "<td><strong>" + lms_portal.escape(c.employee_name) + "</strong></td>";
			body += "<td>" + lms_portal.escape(c.expense_type || "—") + "</td>";
			body += "<td>" + format_currency(c.total_amount || 0) + "</td>";
			body += "<td>" + lms_portal.formatDate(c.posting_date) + "</td>";
			body += '<td><div class="lms-data-table__actions">';
			body += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-hr-approve-exp" data-name="' + lms_portal.escape(c.name) + '">Approve</button>';
			body += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-hr-reject-exp" data-name="' + lms_portal.escape(c.name) + '">Reject</button>';
			body += '</div></td></tr>';
		});
		body += "</tbody></table></div>";
		content.innerHTML = lms_portal.panel({ body: body });

		content.querySelectorAll(".lms-hr-approve-exp").forEach(function (btn) {
			btn.addEventListener("click", function () {
				lms_hr._processExpense(btn.getAttribute("data-name"), "Approved");
			});
		});
		content.querySelectorAll(".lms-hr-reject-exp").forEach(function (btn) {
			btn.addEventListener("click", function () {
				lms_hr._processExpense(btn.getAttribute("data-name"), "Rejected");
			});
		});
	},
});
};

lms_hr._processExpense = function (name, status) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.approve_expense",
		args: { claim_name: name, status: status },
		callback: function () {
			lms_portal.toast("Expense " + status, status === "Approved" ? "success" : "warning");
			lms_hr._showTab("expenses");
		},
	});
};

lms_hr._loadShifts = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.get_pending_shift_requests",
		callback: function (r) {
			var reqs = (r && r.message && r.message.requests) || [];
			if (!reqs.length) {
				content.innerHTML = lms_portal.emptyPanel("✓", "All caught up", "No shift requests pending.");
				return;
			}
			var body = '<div class="lms-data-table__wrap"><table class="lms-data-table">';
			body += "<thead><tr><th>Employee</th><th>Shift</th><th>From</th><th>To</th><th>Actions</th></tr></thead><tbody>";
			reqs.forEach(function (s) {
				body += "<tr>";
				body += "<td><strong>" + lms_portal.escape(s.employee_name) + "</strong></td>";
				body += "<td>" + lms_portal.escape(s.shift_type || "—") + "</td>";
				body += "<td>" + lms_portal.formatDate(s.from_date) + "</td>";
				body += "<td>" + lms_portal.formatDate(s.to_date) + "</td>";
				body += '<td><button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-hr-approve-shift" data-name="' + lms_portal.escape(s.name) + '">Approve</button></td>';
				body += "</tr>";
			});
			body += "</tbody></table></div>";
			content.innerHTML = lms_portal.panel({ body: body });

			content.querySelectorAll(".lms-hr-approve-shift").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_portal.safeCall({
						method: "lms_saas.api.hr.approve_shift_request",
						args: { request_name: btn.getAttribute("data-name") },
						callback: function () {
							lms_portal.toast("Shift approved.", "success");
							lms_hr._showTab("shifts");
						},
					});
				});
			});
		},
	});
};

lms_hr._loadDirectory = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.get_team_directory",
		callback: function (r) {
			var staff = (r && r.message && r.message.staff) || [];
			if (!staff.length) {
				content.innerHTML = lms_portal.emptyPanel("👥", "No staff found", "");
				return;
			}
			var body = '<div class="lms-data-table__wrap"><table class="lms-data-table">';
			body += "<thead><tr><th>Name</th><th>Designation</th><th>Persona</th><th>Mobile</th><th>Email</th></tr></thead><tbody>";
			staff.forEach(function (s) {
				body += "<tr>";
				body += "<td><strong>" + lms_portal.escape(s.employee_name) + "</strong></td>";
				body += "<td>" + lms_portal.escape(s.designation || "—") + "</td>";
				body += '<td><span class="lms-badge">' + lms_portal.escape(s.custom_lms_persona || "—") + "</span></td>";
				body += "<td>" + lms_portal.escape(s.cell_number || "—") + "</td>";
				body += "<td>" + lms_portal.escape(s.personal_email || "—") + "</td>";
				body += "</tr>";
			});
			body += "</tbody></table></div>";
			content.innerHTML = lms_portal.panel({ body: body });
		},
	});
};