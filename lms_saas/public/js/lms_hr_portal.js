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
	var html = '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_hr._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	html += '<div id="lms-hr-tab-content"></div>';
	root.innerHTML = html;

	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_hr._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.style.borderBottom = "2px solid var(--lms-primary)";
			btn.style.color = "var(--lms-primary)";
			btn.style.fontWeight = "600";
			lms_hr._showTab(lms_hr._currentTab);
		});
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

lms_hr._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_hr._loadDashboard = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.get_hr_dashboard",
		callback: function (r) {
			var d = (r && r.message) || {};
			var html = '<section class="lms-grid-4">';
			html += lms_hr._statCard("Team Members", d.team_count || 0);
			html += lms_hr._statCard("Present Today", d.present_today || 0, "success");
			html += lms_hr._statCard("Absent Today", d.absent_today || 0, "danger");
			html += lms_hr._statCard("Pending Leaves", d.pending_leaves || 0, "warning");
			html += lms_hr._statCard("Pending Expenses", d.pending_expenses || 0, "warning");
			html += lms_hr._statCard("Shift Requests", d.pending_shift_requests || 0);
			html += "</section>";
			content.innerHTML = html;
		},
	});
};

lms_hr._loadLeaves = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.hr.get_pending_leaves",
		callback: function (r) {
			var leaves = (r && r.message && r.message.leaves) || [];
			if (!leaves.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">✓</div><h3>All caught up</h3><p>No leave applications pending.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Employee</th><th>Type</th><th>From</th><th>To</th><th>Days</th><th>Actions</th></tr></thead><tbody>";
			leaves.forEach(function (l) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(l.employee_name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(l.leave_type) + "</td>";
				html += "<td>" + lms_portal.formatDate(l.from_date) + "</td>";
				html += "<td>" + lms_portal.formatDate(l.to_date) + "</td>";
				html += "<td>" + (l.total_leave_days || 0) + "</td>";
				html += '<td><div class="lms-data-table__actions">';
				html += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-hr-approve-leave" data-name="' + lms_portal.escape(l.name) + '">Approve</button>';
				html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-hr-reject-leave" data-name="' + lms_portal.escape(l.name) + '">Reject</button>';
				html += '</div></td></tr>';
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

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
			var html = '<div class="lms-panel" style="margin-bottom:1rem;"><h3>Present (' + records.length + ')</h3>';
			if (records.length) {
				html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Employee</th><th>Status</th><th>In Time</th><th>Out Time</th></tr></thead><tbody>';
				records.forEach(function (a) {
					html += "<tr><td><strong>" + lms_portal.escape(a.employee_name) + "</strong></td>";
					html += '<td><span class="lms-badge lms-badge--success">' + lms_portal.escape(a.status) + "</span></td>";
					html += "<td>" + lms_portal.escape(a.in_time || "—") + "</td>";
					html += "<td>" + lms_portal.escape(a.out_time || "—") + "</td></tr>";
				});
				html += "</tbody></table></div>";
			} else {
				html += '<p class="lms-muted">No attendance records for today.</p>';
			}
			html += '</div>';

			if (absentees.length) {
				html += '<div class="lms-panel"><h3>Absentees / No Record (' + absentees.length + ')</h3>';
				html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Employee</th><th>Status</th></tr></thead><tbody>';
				absentees.forEach(function (a) {
					html += "<tr><td><strong>" + lms_portal.escape(a.employee_name) + "</strong></td>";
					html += '<td><span class="lms-badge lms-badge--warning">' + lms_portal.escape(a.status) + "</span></td></tr>";
				});
				html += "</tbody></table></div></div>";
			}
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
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">✓</div><h3>All caught up</h3><p>No expense claims pending.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Employee</th><th>Type</th><th>Amount</th><th>Date</th><th>Actions</th></tr></thead><tbody>";
			claims.forEach(function (c) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(c.employee_name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(c.expense_type || "—") + "</td>";
				html += "<td>" + format_currency(c.total_amount || 0) + "</td>";
				html += "<td>" + lms_portal.formatDate(c.posting_date) + "</td>";
				html += '<td><div class="lms-data-table__actions">';
				html += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-hr-approve-exp" data-name="' + lms_portal.escape(c.name) + '">Approve</button>';
				html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-hr-reject-exp" data-name="' + lms_portal.escape(c.name) + '">Reject</button>';
				html += '</div></td></tr>';
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

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
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">✓</div><h3>All caught up</h3><p>No shift requests pending.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Employee</th><th>Shift</th><th>From</th><th>To</th><th>Actions</th></tr></thead><tbody>";
			reqs.forEach(function (s) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(s.employee_name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(s.shift_type || "—") + "</td>";
				html += "<td>" + lms_portal.formatDate(s.from_date) + "</td>";
				html += "<td>" + lms_portal.formatDate(s.to_date) + "</td>";
				html += '<td><button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-hr-approve-shift" data-name="' + lms_portal.escape(s.name) + '">Approve</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

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
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">👥</div><h3>No staff found</h3></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Name</th><th>Designation</th><th>Persona</th><th>Mobile</th><th>Email</th></tr></thead><tbody>";
			staff.forEach(function (s) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(s.employee_name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(s.designation || "—") + "</td>";
				html += '<td><span class="lms-badge">' + lms_portal.escape(s.custom_lms_persona || "—") + "</span></td>";
				html += "<td>" + lms_portal.escape(s.cell_number || "—") + "</td>";
				html += "<td>" + lms_portal.escape(s.personal_email || "—") + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
	});
};