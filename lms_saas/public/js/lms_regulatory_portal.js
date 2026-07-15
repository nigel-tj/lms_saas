/* LMS Regulatory Hub portal — calendar, generate, archive */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_regulatory");
} else {
	window.lms_regulatory = window.lms_regulatory || {};
}

lms_regulatory._currentTab = "calendar";

lms_regulatory.init = function () {
	var root = document.getElementById("lms-regulatory-root");
	if (!root) return;

	var tabs = [
		{ id: "calendar", label: "Calendar", icon: "📅" },
		{ id: "generate", label: "Generate", icon: "📋" },
		{ id: "archive", label: "Archive", icon: "🗄️" },
	];
	var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;">';
	html += '<h2 style="margin:0;font-size:var(--lms-fs-xl);font-weight:700;">Regulatory Hub</h2>';
	html += '</div>';
	html += '<div id="lms-reg-stats" style="margin-bottom:1rem;"></div>';
	html += '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_regulatory._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	html += '<div id="lms-regulatory-tab-content"></div>';
	root.innerHTML = html;

	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_regulatory._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.style.borderBottom = "2px solid var(--lms-primary)";
			btn.style.color = "var(--lms-primary)";
			btn.style.fontWeight = "600";
			lms_regulatory._showTab(lms_regulatory._currentTab);
		});
	});

	lms_regulatory._loadStats();
	lms_regulatory._showTab(lms_regulatory._currentTab);
};

lms_regulatory._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_regulatory._loadStats = function () {
	var el = document.getElementById("lms-reg-stats");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.regulatory_hub.get_regulatory_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = '<section class="lms-grid-4">';
			html += lms_regulatory._statCard("Total Submissions", s.total_submissions || 0);
			html += lms_regulatory._statCard("Draft", s.draft || 0, "warning");
			html += lms_regulatory._statCard("Submitted", s.submitted || 0, "info");
			html += lms_regulatory._statCard("Upcoming Deadlines", s.upcoming_deadlines || 0, "warning");
			html += "</section>";
			el.innerHTML = html;
		},
	});
};

lms_regulatory._showTab = function (tabId) {
	var content = document.getElementById("lms-regulatory-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "calendar") lms_regulatory._loadCalendar(content);
	else if (tabId === "generate") lms_regulatory._loadGenerate(content);
	else if (tabId === "archive") lms_regulatory._loadArchive(content);
};

// ── Calendar ──

lms_regulatory._loadCalendar = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.regulatory_hub.get_report_calendar",
		args: { months_ahead: 3 },
		callback: function (r) {
			var deadlines = (r && r.message && r.message.deadlines) || [];
			if (!deadlines.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📅</div><h3>No deadlines</h3><p>No upcoming regulatory deadlines.</p></div></div>';
				return;
			}

			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Report Type</th><th>Frequency</th><th>Due Date</th><th>Status</th><th>Description</th></tr></thead><tbody>";
			deadlines.forEach(function (d) {
				var statusBadge = "";
				if (d.is_overdue) {
					statusBadge = '<span class="lms-badge lms-badge--danger">Overdue</span>';
				} else if (d.is_due_soon) {
					statusBadge = '<span class="lms-badge lms-badge--warning">Due Soon</span>';
				} else {
					statusBadge = '<span class="lms-badge lms-badge--success">Upcoming</span>';
				}
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(d.report_type) + "</strong></td>";
				html += "<td>" + lms_portal.escape(d.frequency) + "</td>";
				html += "<td>" + lms_portal.formatDate(d.due_date) + "</td>";
				html += "<td>" + statusBadge + "</td>";
				html += '<td class="lms-muted">' + lms_portal.escape(d.description) + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load calendar.");
		},
	});
};

// ── Generate ──

lms_regulatory._loadGenerate = function (content) {
	var reportTypes = [
		{ value: "weekly_kpi", label: "Weekly KPI" },
		{ value: "par", label: "Portfolio At Risk" },
		{ value: "arrears", label: "Arrears Aging" },
		{ value: "ecl", label: "IFRS9 ECL" },
		{ value: "transaction_summary", label: "Transaction Summary" },
		{ value: "complaint_summary", label: "Complaint Summary" },
		{ value: "incident_log", label: "Incident Log" },
	];

	var html = '<div class="lms-panel" style="padding:1.5rem;">';
	html += '<div class="lms-form">';
	html += '<div class="lms-field"><label>Report Type</label>';
	html += '<select id="lms-reg-report-type" class="lms-input lms-fallback-select">';
	reportTypes.forEach(function (rt) {
		html += '<option value="' + rt.value + '">' + lms_portal.escape(rt.label) + "</option>";
	});
	html += '</select></div>';
	html += '<div style="display:flex;gap:1rem;">';
	html += '<div class="lms-field" style="flex:1;"><label>Period Start</label>';
	html += '<input type="date" id="lms-reg-period-start" class="lms-input"></div>';
	html += '<div class="lms-field" style="flex:1;"><label>Period End</label>';
	html += '<input type="date" id="lms-reg-period-end" class="lms-input"></div>';
	html += '</div>';
	html += '<div style="margin-top:1rem;"><button type="button" class="lms-btn lms-btn--primary" id="lms-reg-generate-btn">Generate Report</button></div>';
	html += '</div></div>';
	html += '<div id="lms-reg-report-output" style="margin-top:1.5rem;"></div>';
	content.innerHTML = html;

	var btn = content.querySelector("#lms-reg-generate-btn");
	if (btn) {
		btn.addEventListener("click", function () {
			lms_regulatory._generateReport();
		});
	}
};

lms_regulatory._generateReport = function () {
	var reportType = document.getElementById("lms-reg-report-type").value;
	var periodStart = document.getElementById("lms-reg-period-start").value;
	var periodEnd = document.getElementById("lms-reg-period-end").value;
	var output = document.getElementById("lms-reg-report-output");

	if (!output) return;
	output.innerHTML = lms_portal.loading("Generating report…");

	lms_portal.safeCall({
		method: "lms_saas.api.regulatory_hub.generate_report",
		args: {
			report_type: reportType,
			period_start: periodStart || undefined,
			period_end: periodEnd || undefined,
		},
		callback: function (r) {
			var data = (r && r.message) || {};
			var title = data.report_title || "Report";
			var html = '<div class="lms-panel" style="padding:1.5rem;">';
			html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;">';
			html += '<h3 style="margin:0;">' + lms_portal.escape(title) + '</h3>';
			html += '<div style="display:flex;gap:0.5rem;">';
			html += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm" id="lms-reg-save-submission">Save to Archive</button>';
			html += '</div></div>';
			html += '<div class="lms-muted" style="margin-bottom:1rem;">Period: ' + lms_portal.formatDate(data.period_start) + ' — ' + lms_portal.formatDate(data.period_end) + '</div>';
			html += '<pre style="background:var(--lms-surface-2);padding:1rem;border-radius:var(--lms-radius);overflow-x:auto;font-size:var(--lms-fs-sm);line-height:1.5;">' + lms_portal.escape(JSON.stringify(data, null, 2)) + '</pre>';
			html += '</div>';
			output.innerHTML = html;

			var saveBtn = output.querySelector("#lms-reg-save-submission");
			if (saveBtn) {
				saveBtn.addEventListener("click", function () {
					lms_regulatory._saveSubmission(reportType, periodStart, periodEnd, data);
				});
			}
		},
		error: function () {
			output.innerHTML = lms_portal.error("Could not generate report.");
		},
	});
};

lms_regulatory._saveSubmission = function (reportType, periodStart, periodEnd, data) {
	lms_portal.safeCall({
		method: "lms_saas.api.regulatory_hub.save_submission",
		args: {
			report_type: reportType,
			period_start: periodStart,
			period_end: periodEnd,
			status: "Submitted",
			notes: "Generated via Regulatory Hub portal",
		},
		callback: function (r) {
			var name = (r && r.message && r.message.name) || "";
			lms_portal.toast("Submission saved: " + name, "success");
		},
		error: function () {
			lms_portal.toast("Could not save submission.", "danger");
		},
	});
};

// ── Archive ──

lms_regulatory._loadArchive = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.regulatory_hub.get_report_archive",
		callback: function (r) {
			var submissions = (r && r.message && r.message.submissions) || [];
			if (!submissions.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">🗄️</div><h3>No submissions</h3><p>No regulatory submissions archived yet.</p></div></div>';
				return;
			}

			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Report Type</th><th>Period</th><th>Generated On</th><th>Generated By</th><th>Status</th><th>File</th></tr></thead><tbody>";
			submissions.forEach(function (s) {
				var statusCls = s.status === "Acknowledged" ? "lms-badge--success" : (s.status === "Submitted" ? "lms-badge--info" : "lms-badge--warning");
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(s.report_type) + "</strong></td>";
				html += "<td>" + lms_portal.formatDate(s.period_start) + " — " + lms_portal.formatDate(s.period_end) + "</td>";
				html += "<td>" + lms_portal.formatDate(s.generated_on) + "</td>";
				html += "<td>" + lms_portal.escape(s.generated_by || "") + "</td>";
				html += '<td><span class="lms-badge ' + statusCls + '">' + lms_portal.escape(s.status) + "</span></td>";
				html += "<td>" + (s.file_attachment ? '<a href="' + lms_portal.escape(s.file_attachment) + '" target="_blank">📎 View</a>' : "—") + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load archive.");
		},
	});
};