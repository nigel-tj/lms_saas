/* LMS Payroll portal — overview, salary slips, loan deductions */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_payroll");
} else {
	window.lms_payroll = window.lms_payroll || {};
}

lms_payroll._currentTab = "overview";

lms_payroll.init = function () {
	var root = document.getElementById("lms-payroll-root");
	if (!root) return;

	var tabs = [
		{ id: "overview", label: "Overview", icon: "📊" },
		{ id: "slips", label: "Salary Slips", icon: "🧾" },
		{ id: "loans", label: "Loan Deductions", icon: "💰" },
	];
	var html = '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_payroll._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	html += '<div id="lms-payroll-tab-content"></div>';
	root.innerHTML = html;

	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_payroll._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.style.borderBottom = "2px solid var(--lms-primary)";
			btn.style.color = "var(--lms-primary)";
			btn.style.fontWeight = "600";
			lms_payroll._showTab(lms_payroll._currentTab);
		});
	});

	lms_payroll._showTab(lms_payroll._currentTab);
};

lms_payroll._showTab = function (tabId) {
	var content = document.getElementById("lms-payroll-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "overview") lms_payroll._loadOverview(content);
	else if (tabId === "slips") lms_payroll._loadSlips(content);
	else if (tabId === "loans") lms_payroll._loadLoanDeductions(content);
};

lms_payroll._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_payroll._loadOverview = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.payroll.get_payroll_overview",
		callback: function (r) {
			var d = (r && r.message) || {};
			var html = '<section class="lms-grid-4">';
			html += lms_payroll._statCard("Team Members", d.team_count || 0);
			html += lms_payroll._statCard("Payslips", d.slip_count || 0);
			html += lms_payroll._statCard("Submitted", d.submitted || 0, "success");
			html += lms_payroll._statCard("Draft", d.draft || 0, "warning");
			html += lms_payroll._statCard("Gross Pay", format_currency(d.total_gross || 0));
			html += lms_payroll._statCard("Net Pay", format_currency(d.total_net || 0));
			html += lms_payroll._statCard("Deductions", format_currency(d.total_deductions || 0), "warning");
			html += lms_payroll._statCard("Loan Deductions", format_currency(d.loan_deductions || 0), "danger");
			html += "</section>";

			// Payroll entries
			var entries = d.payroll_entries || [];
			if (entries.length) {
				html += '<div class="lms-panel" style="margin-top:1rem;"><h3>Payroll Entries</h3>';
				html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
				html += "<thead><tr><th>Entry</th><th>Status</th><th>Start</th><th>End</th><th>Employees</th></tr></thead><tbody>";
				entries.forEach(function (e) {
					var statusClass = e.status === "Submitted" ? "lms-badge--success" : (e.status === "Draft" ? "lms-badge--warning" : "");
					html += "<tr>";
					html += "<td><strong>" + lms_portal.escape(e.name) + "</strong></td>";
					html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(e.status || "") + "</span></td>";
					html += "<td>" + lms_portal.formatDate(e.start_date) + "</td>";
					html += "<td>" + lms_portal.formatDate(e.end_date) + "</td>";
					html += "<td>" + (e.number_of_employees || 0) + "</td>";
					html += "</tr>";
				});
				html += "</tbody></table></div></div>";
			}

			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load payroll overview.");
		},
	});
};

lms_payroll._loadSlips = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.payroll.get_salary_slips",
		callback: function (r) {
			var slips = (r && r.message && r.message.slips) || [];
			if (!slips.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">🧾</div><h3>No payslips</h3><p>No salary slips found for your branch.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Employee</th><th>Status</th><th>Gross</th><th>Deductions</th><th>Net Pay</th><th>Date</th><th>Action</th></tr></thead><tbody>";
			slips.forEach(function (s) {
				var statusClass = s.status === "Submitted" ? "lms-badge--success" : (s.status === "Draft" ? "lms-badge--warning" : "lms-badge--danger");
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(s.employee_name) + "</strong></td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(s.status || "") + "</span></td>";
				html += "<td>" + format_currency(s.gross_pay || 0) + "</td>";
				html += "<td>" + format_currency(s.total_deduction || 0) + "</td>";
				html += "<td><strong>" + format_currency(s.net_pay || 0) + "</strong></td>";
				html += "<td>" + lms_portal.formatDate(s.posting_date) + "</td>";
				html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-pr-view" data-name="' + lms_portal.escape(s.name) + '">View</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-pr-view").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_payroll._showSlipDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load salary slips.");
		},
	});
};

lms_payroll._showSlipDetail = function (slipName) {
	lms_portal.safeCall({
		method: "lms_saas.api.payroll.get_payslip_detail",
		args: { slip_name: slipName },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_payroll._renderSlipDetail(data);
		},
	});
};

lms_payroll._renderSlipDetail = function (data) {
	var s = data.slip || {};
	var earnings = data.earnings || [];
	var deductions = data.deductions || [];

	var html = '<div class="lms-form">';
	html += '<h3 style="margin:0 0 0.5rem;">' + lms_portal.escape(s.employee_name || "") + '</h3>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(s.status || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Period</div><div class="lms-summary-value">' + lms_portal.formatDate(s.start_date) + ' → ' + lms_portal.formatDate(s.end_date) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Net Pay</div><div class="lms-summary-value">' + format_currency(s.net_pay || 0) + '</div></div>';
	html += '</div>';

	html += '<div style="display:flex;gap:1rem;margin-bottom:1rem;">';
	// Earnings
	html += '<div class="lms-panel" style="flex:1;"><h4>Earnings</h4>';
	html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Component</th><th>Amount</th></tr></thead><tbody>';
	earnings.forEach(function (e) {
		html += "<tr><td>" + lms_portal.escape(e.component) + "</td><td>" + format_currency(e.amount || 0) + "</td></tr>";
	});
	html += "</tbody></table></div></div>";

	// Deductions
	html += '<div class="lms-panel" style="flex:1;"><h4>Deductions</h4>';
	html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Component</th><th>Amount</th></tr></tr></thead><tbody>';
	deductions.forEach(function (d) {
		var isLoan = (d.component || "").toLowerCase().indexOf("loan") >= 0;
		var cls = isLoan ? ' style="font-weight:600;color:var(--lms-danger);"' : "";
		html += "<tr" + cls + "><td>" + lms_portal.escape(d.component) + "</td><td>" + format_currency(d.amount || 0) + "</td></tr>";
	});
	html += "</tbody></table></div></div>";
	html += '</div>';

	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Gross Pay</div><div class="lms-summary-value">' + format_currency(s.gross_pay || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Deductions</div><div class="lms-summary-value">' + format_currency(s.total_deduction || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Net Pay</div><div class="lms-summary-value">' + format_currency(s.net_pay || 0) + '</div></div>';
	html += '</div>';
	html += '</div>';

	lms_portal.modal({
		title: "Payslip " + (s.name || ""),
		body: html,
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});
};

lms_payroll._loadLoanDeductions = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.payroll.get_salary_slips",
		callback: function (r) {
			var slips = (r && r.message && r.message.slips) || [];
			var loanSlips = [];
			var totalLoanDeduction = 0;

			// We need to fetch detail for each slip to find loan deductions
			// For efficiency, just show slips with deductions and let user drill in
			slips.forEach(function (s) {
				if ((s.total_deduction || 0) > 0) {
					loanSlips.push(s);
				}
			});

			if (!loanSlips.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">💰</div><h3>No loan deductions</h3><p>No salary slips with deductions found.</p></div></div>';
				return;
			}

			var html = '<div class="lms-panel"><p class="lms-muted" style="margin-bottom:1rem;">Click a payslip to view loan deduction breakdown.</p>';
			html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Employee</th><th>Deductions</th><th>Net Pay</th><th>Date</th><th>Action</th></tr></thead><tbody>";
			loanSlips.forEach(function (s) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(s.employee_name) + "</strong></td>";
				html += "<td>" + format_currency(s.total_deduction || 0) + "</td>";
				html += "<td>" + format_currency(s.net_pay || 0) + "</td>";
				html += "<td>" + lms_portal.formatDate(s.posting_date) + "</td>";
				html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-pr-loan-view" data-name="' + lms_portal.escape(s.name) + '">View Detail</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-pr-loan-view").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_payroll._showSlipDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load loan deductions.");
		},
	});
};