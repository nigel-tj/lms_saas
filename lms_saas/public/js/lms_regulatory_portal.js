/* LMS Regulatory Hub portal — calendar, generate (admin), archive, BM summary */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_regulatory");
} else {
	window.lms_regulatory = window.lms_regulatory || {};
}

lms_regulatory._currentTab = "calendar";
lms_regulatory._isAdmin = false;
lms_regulatory._stats = {};

lms_regulatory.init = function () {
	var root = document.getElementById("lms-regulatory-root");
	if (!root) return;

	var home = window.__lms_home_route || "/lms";
	var tabs = [
		{ id: "calendar", label: "Calendar", icon: "calendar" },
		{ id: "generate", label: "Generate", icon: "file-text" },
		{ id: "archive", label: "Archive", icon: "archive" },
		{ id: "recipients", label: "Recipients", icon: "mail" },
	];
	var html = lms_portal.pageStart() +
		lms_portal.backLink({ href: home, label: "Manager home" }) +
		'<div id="lms-reg-branch-banner"></div>' +
		'<div id="lms-reg-stats"></div>' +
		lms_portal.tabNav(tabs, lms_regulatory._currentTab) +
		'<div id="lms-regulatory-tab-content"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_portal.bindTabs({
		root: root,
		tabs: tabs,
		onTab: function (tabId) { lms_regulatory._currentTab = tabId; lms_regulatory._showTab(tabId); },
	});

	lms_regulatory._loadStats();
	lms_regulatory._showTab(lms_regulatory._currentTab);
};

lms_regulatory._loadStats = function () {
	var el = document.getElementById("lms-reg-stats");
	var banner = document.getElementById("lms-reg-branch-banner");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.regulatory_hub.get_regulatory_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			lms_regulatory._stats = s;
			lms_regulatory._isAdmin = !!s.is_admin;
			el.innerHTML = lms_portal.kpiStrip([
				{ label: "Total Submissions", value: s.total_submissions || 0 },
				{ label: "Draft / Pending", value: s.draft || 0, tone: (s.draft ? "warning" : "success") },
				{ label: "Submitted", value: s.submitted || 0 },
				{ label: "Upcoming Deadlines", value: s.upcoming_deadlines || 0, tone: "warning" },
			]);
			if (banner) {
				var pending = s.pending_submissions || s.draft || 0;
				var tone = pending ? "warning" : "success";
				var line = pending
					? ("Your organisation has " + pending + " pending draft submission" + (pending === 1 ? "" : "s") + ". Filing is admin-only.")
					: "No draft submissions pending. Review the calendar for upcoming deadlines.";
				banner.innerHTML =
					'<div class="lms-reg-banner lms-reg-banner--' + tone + '" role="status">' +
					'<strong>Branch view</strong> — ' + lms_portal.escape(line) +
					(lms_regulatory._isAdmin ? ' <span class="lms-badge lms-badge--info">Admin write access</span>' : ' <span class="lms-badge">Read-only</span>') +
					"</div>";
			}
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load regulatory stats.");
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
	else if (tabId === "recipients") lms_regulatory._loadRecipients(content);
};

// ── Calendar ──

lms_regulatory._loadCalendar = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.regulatory_hub.get_report_calendar",
		args: { months_ahead: 3 },
		callback: function (r) {
			var deadlines = (r && r.message && r.message.deadlines) || [];
			if (!deadlines.length) {
				content.innerHTML = lms_portal.emptyPanel("calendar", "No deadlines", "No upcoming regulatory deadlines in the next 3 months.");
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

// ── Generate (admin write; BM sees read-only notice) ──

lms_regulatory._loadGenerate = function (content) {
	if (!lms_regulatory._isAdmin) {
		content.innerHTML =
			lms_portal.emptyPanel(
				"shield",
				"Admin filing only",
				"Branch Managers can review deadlines and the archive. Generating and saving regulatory submissions requires a System Manager."
			);
		return;
	}

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
			html += '<pre style="background:var(--lms-surface-alt);padding:1rem;border-radius:var(--lms-radius);overflow-x:auto;font-size:var(--lms-fs-sm);line-height:1.5;">' + lms_portal.escape(JSON.stringify(data, null, 2)) + '</pre>';
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
			lms_regulatory._loadStats();
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
				content.innerHTML = lms_portal.emptyPanel("archive", "No submissions", "No regulatory submissions archived yet.");
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
				html += "<td>" + (s.file_attachment ? '<a href="' + lms_portal.escape(s.file_attachment) + '" target="_blank">View</a>' : "—") + "</td>";
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

// ── Recipients (B-19) ──

lms_regulatory._loadRecipients = function (content) {
	var s = lms_regulatory._stats || {};
	var load = function (stats) {
		var recipients = (stats && stats.compliance_recipients) || [];
		var html = '<div class="lms-panel" style="padding:1.5rem;">';
		html += "<h3 style=\"margin:0 0 .5rem;\">Compliance report recipients</h3>";
		html += '<p class="lms-muted" style="margin:0 0 1rem;">Weekly KPI / sandbox packs are emailed to these addresses (site_config: <code>lms_compliance_report_recipients</code>).</p>';
		if (!recipients.length) {
			html += '<div class="lms-empty" style="padding:1.25rem 0;">';
			html += "<p><strong>No recipients configured.</strong></p>";
			html += "<p class=\"lms-muted\">Ask a System Manager to set <code>lms_compliance_report_recipients</code> (comma-separated emails) so weekly packs are delivered.</p>";
			html += "</div>";
		} else {
			html += '<ul class="lms-list">';
			recipients.forEach(function (email) {
				html += '<li class="lms-list__item"><div class="lms-list__info">' + lms_portal.escape(email) + "</div></li>";
			});
			html += "</ul>";
		}
		html += "</div>";
		content.innerHTML = html;
	};

	if (s.compliance_recipients !== undefined) {
		load(s);
		return;
	}
	lms_portal.safeCall({
		method: "lms_saas.api.regulatory_hub.get_regulatory_stats",
		callback: function (r) {
			lms_regulatory._stats = (r && r.message) || {};
			load(lms_regulatory._stats);
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load recipients.");
		},
	});
};
