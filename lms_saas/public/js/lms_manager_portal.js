/* LMS Branch Manager portal — dashboard, approvals, team performance, borrowers, loans, reports, collateral */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_manager");
} else {
	window.lms_manager = window.lms_manager || {};
}

lms_manager._charts = {};
lms_manager._currentTab = "dashboard";

lms_manager.init = function () {
	var root = document.getElementById("lms-manager-root");
	if (!root) return;

	// Render tab navigation first
	root.innerHTML = lms_manager._tabNav() + '<div id="lms-manager-tab-content"></div>';
	lms_manager._bindTabs();
	lms_manager._showTab(lms_manager._currentTab);
};

lms_manager._tabNav = function () {
	var tabs = [
		{ id: "dashboard", label: "Dashboard", icon: "📊" },
		{ id: "borrowers", label: "Borrowers", icon: "👤" },
		{ id: "loans", label: "Loans", icon: "💰" },
		{ id: "reports", label: "Reports", icon: "📈" },
		{ id: "collateral", label: "Collateral", icon: "🏠" },
		{ id: "team", label: "Team", icon: "👥" },
	];
	var html = '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_manager._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	return html;
};

lms_manager._bindTabs = function () {
	var root = document.getElementById("lms-manager-root");
	if (!root) return;
	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._currentTab = btn.getAttribute("data-tab");
			// Update active styles via class
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.setAttribute("aria-selected", "true");
			lms_manager._showTab(lms_manager._currentTab);
		});
	});
};

lms_manager._showTab = function (tabId) {
	var content = document.getElementById("lms-manager-tab-content");
	if (!content) return;

	// Destroy old charts
	Object.keys(lms_manager._charts).forEach(function (k) {
		lms_charts.destroy(lms_manager._charts[k]);
	});
	lms_manager._charts = {};

	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "dashboard") {
		lms_manager._loadDashboard(content);
	} else if (tabId === "borrowers") {
		lms_manager._loadBorrowers(content);
	} else if (tabId === "loans") {
		lms_manager._loadLoans(content);
	} else if (tabId === "reports") {
		lms_manager._loadReports(content);
	} else if (tabId === "collateral") {
		lms_manager._loadCollateral(content);
	} else if (tabId === "team") {
		lms_manager._loadTeam(content);
	}
};

// ---------------------------------------------------------------------------
// Dashboard tab
// ---------------------------------------------------------------------------
lms_manager._loadDashboard = function (content) {
	var dashLoaded = false;
	var queueLoaded = false;
	var dashData = null;
	var queueData = null;

	function tryRender() {
		if (!dashLoaded || !queueLoaded) return;
		lms_manager._renderAll(content, dashData, queueData);
	}

	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_manager_dashboard",
		callback: function (r) {
			dashData = (r && r.message) || {};
			dashLoaded = true;
			tryRender();
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load dashboard.", function () {
				lms_manager._showTab("dashboard");
			});
		},
	});

	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_approval_queue",
		callback: function (r) {
			queueData = (r && r.message) || { applications: [] };
			queueLoaded = true;
			tryRender();
		},
	});
};

lms_manager._renderAll = function (root, dash, queue) {
	var html = "";

	/* ---- KPI stat cards ---- */
	var k = dash.kpis || {};
	html += '<section class="lms-grid-4" aria-label="Branch KPIs">';
	html += lms_manager._statCard("Portfolio Outstanding", format_currency(k.portfolio_outstanding || 0), "bank");
	html += lms_manager._statCard("Active Loans", k.active_loans || 0, "file");
	html += lms_manager._statCard("PAR 30+ Outstanding", format_currency(k.par30_outstanding || 0), "alert", "danger");
	html += lms_manager._statCard("NPA Count", k.npa_count || 0, "x-circle", "warning");
	html += lms_manager._statCard("Approval Queue", k.approval_queue_count || 0, "clock", k.approval_queue_count ? "warning" : "");
	html += lms_manager._statCard("Team Members", k.team_count || 0, "users");
	html += "</section>";

	/* ---- Charts row: risk donut + team bars ---- */
	html += '<div class="lms-grid-2" style="margin-top:1.25rem;">';

	/* Risk mix donut */
	var buckets = dash.risk_buckets || {};
	html += '<div class="lms-panel lms-portal-board">';
	html += '<div class="lms-section-header"><h3>Risk Mix</h3></div>';
	html += '<div class="lms-chart-wrap"><canvas id="lms-risk-chart"></canvas></div>';
	html += "</div>";

	/* Team performance bars */
	html += '<div class="lms-panel lms-portal-board">';
	html += '<div class="lms-section-header"><h3>Team Performance</h3></div>';
	html += '<div class="lms-chart-wrap"><canvas id="lms-team-chart"></canvas></div>';
	html += "</div>";

	html += "</div>";

	/* ---- Approval queue table ---- */
	html += '<div class="lms-panel lms-portal-board" style="margin-top:1.25rem;">';
	html += '<div class="lms-section-header"><h3>Approval Queue</h3>';
	html += '<span class="lms-muted">' + ((queue.applications || []).length) + " pending</span></div>";
	var apps = queue.applications || [];
	if (!apps.length) {
		html += '<div class="lms-empty"><div class="lms-empty-icon">✓</div>';
		html += "<h3>All caught up</h3><p>No applications pending approval.</p></div>";
	} else {
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
		html += "<thead><tr><th>Applicant</th><th>Product</th><th>Amount</th><th>Officer</th><th>Actions</th></tr></thead><tbody>";
		apps.forEach(function (app) {
			html += "<tr>";
			html += "<td><strong>" + lms_portal.escape(app.customer_name || app.applicant || "—") + "</strong></td>";
			html += "<td>" + lms_portal.escape(app.product_name || app.loan_product || "") + "</td>";
			html += "<td>" + format_currency(app.loan_amount || 0) + "</td>";
			html += "<td>" + lms_portal.escape(app.officer_name || "—") + "</td>";
			html += '<td><div class="lms-data-table__actions">';
			html += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-approve-btn" data-app="' + lms_portal.escape(app.name) + '">Approve</button>';
			html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-reject-btn" data-app="' + lms_portal.escape(app.name) + '">Reject</button>';
			html += "</div></td></tr>";
		});
		html += "</tbody></table></div>";
	}
	html += "</div>";

	root.innerHTML = html;

	/* ---- Render charts ---- */
	// Each chart slice passes an explicit hex fallback so an empty
	// token (theme missing the variable) still shows a meaningful color.
	var riskData = [
		{ label: "Current", value: buckets.current || 0, color: lms_manager._resolveColor("var(--lms-success)", "#16a34a") },
		{ label: "PAR 30+", value: buckets.par30 || 0, color: lms_manager._resolveColor("var(--lms-warning)", "#f59e0b") },
		{ label: "PAR 60+", value: buckets.par60 || 0, color: lms_manager._resolveColor("var(--lms-tone-orange)", "#f97316") },
		{ label: "PAR 90+", value: buckets.par90 || 0, color: lms_manager._resolveColor("var(--lms-danger)", "#dc2626") },
	];
	lms_manager._charts.risk = lms_charts.donut("lms-risk-chart", riskData);

	var officers = (dash.team && dash.team.officers) || [];
	var teamData = officers.map(function (o) {
		return { label: o.officer_name || o.officer || "—", value: o.loan_count || 0 };
	});
	lms_manager._charts.team = lms_charts.bars("lms-team-chart", teamData);

	/* ---- Bind approve/reject buttons ---- */
	root.querySelectorAll(".lms-approve-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._approve(btn.getAttribute("data-app"));
		});
	});
	root.querySelectorAll(".lms-reject-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._reject(btn.getAttribute("data-app"));
		});
	});
};

lms_manager._resolveColor = function (cssVar, fallback) {
	if (!cssVar || cssVar.indexOf("var(") !== 0) return cssVar || fallback || "#2f4f46";
	var name = cssVar.replace(/var\(|\)/g, "").split(",")[0].trim();
	try {
		var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
		return v || (fallback || "#2f4f46");
	} catch (e) {
		return fallback || "#2f4f46";
	}
};

lms_manager._statCard = function (label, value, icon, tone) {
	var iconSvg = lms_manager._icon(icon || "file");
	var toneClass = tone ? " lms-stat--" + tone : "";
	return (
		'<div class="lms-stat-card lms-stat' + toneClass + '" style="padding:1.1rem 1.25rem;">' +
		'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:0.5rem;">' +
		'<div><div class="lms-stat-label">' + lms_portal.escape(label) + "</div>" +
		'<div class="lms-stat-value">' + value + "</div></div>" +
		'<span class="lms-sidebar__icon" style="color:var(--lms-text-muted);opacity:0.5;">' + iconSvg + "</span>" +
		"</div></div>"
	);
};

lms_manager._icon = function (name) {
	var icons = {
		bank: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18"/><path d="M3 10h18"/><path d="M5 6l7-3 7 3"/><path d="M4 10v11"/><path d="M20 10v11"/></svg>',
		file: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
		"alert": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
		"x-circle": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
		clock: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
		users: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
	};
	return icons[name] || icons.file;
};

lms_manager._approve = function (appName) {
	lms_portal.modal({
		title: "Approve Application",
		body: '<p class="lms-muted">Confirm approval of <strong>' + lms_portal.escape(appName) + "</strong>. A loan will be created and disbursed.</p>",
		confirmText: "Approve",
		confirmVariant: "success",
		onConfirm: function () {
			lms_portal.safeCall({
				method: "lms_saas.api.manager.approve_application",
				args: { application_name: appName },
				callback: function (r) {
					var res = (r && r.message) || {};
					if (res.status === "approved" && res.loan) {
						lms_portal.toast("Approved \u2014 Loan " + res.loan + " created.", "success");
						// Partial refresh — preserve the active tab and don't
						// rebuild charts. Full init() yanks the user back to
						// the dashboard and causes a visible chart flicker.
						lms_manager._refreshDashboardData();
					} else {
						lms_portal.toast((res && res.message) || "Approval did not complete.", "danger");
					}
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Approval failed.";
					lms_portal.toast(msg, "danger");
				},
			});
		},
	});
};

lms_manager._reject = function (appName) {
	lms_portal.modal({
		title: "Reject Application",
		body:
			'<div class="lms-form">' +
			'<div class="lms-field"><label>Reason <span class="lms-muted">(required)</span></label>' +
			'<input type="text" id="lms-reject-reason" class="lms-input" placeholder="e.g. insufficient collateral" autocomplete="off">' +
			'<div class="lms-field__hint">This reason will be logged on the application for the audit trail.</div></div>' +
			'</div>',
		confirmText: "Reject",
		confirmVariant: "danger",
		onConfirm: function (overlay) {
			var reasonInput = overlay.querySelector("#lms-reject-reason");
			var reason = reasonInput ? reasonInput.value : "";
			if (!reason.trim()) {
				lms_portal.toast("Please provide a rejection reason.", "warning");
				if (reasonInput) reasonInput.focus();
				return false; // keep modal open
			}
			lms_portal.safeCall({
				method: "lms_saas.api.manager.reject_application",
				args: { application_name: appName, reason: reason },
				callback: function (r) {
					var res = (r && r.message) || {};
					if (res.status === "rejected") {
						lms_portal.toast("Application rejected.", "warning");
					} else {
						lms_portal.toast((res && res.message) || "Rejection did not complete.", "danger");
					}
					lms_manager._refreshDashboardData();
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Rejection failed.";
					lms_portal.toast(msg, "danger");
				},
			});
		},
	});
};

// Partial refresh — re-fetches dashboard KPIs + approval queue, re-renders
// the dashboard section if it's the active tab, and invalidates the table
// on any other tab. Avoids the chart-flicker + tab-jump of a full init().
lms_manager._refreshDashboardData = function () {
	// Invalidate cached portfolio metrics so KPIs reflect any new loans.
	if (typeof lms_saas !== "undefined" && lms_saas.api && lms_saas.api.dashboard) {
		try { lms_saas.api.dashboard.invalidate_dashboard_cache(); } catch (e) { /* ignore */ }
	}

	var content = document.getElementById("lms-manager-tab-content");
	if (!content) return;

	if (lms_manager._currentTab === "dashboard") {
		// Destroy existing charts so they don't leak when re-rendered.
		Object.keys(lms_manager._charts || {}).forEach(function (k) {
			try { lms_charts.destroy(lms_manager._charts[k]); } catch (e) { /* ignore */ }
		});
		lms_manager._charts = {};
		lms_manager._loadDashboard(content);
	} else {
		// On non-dashboard tabs, just re-load that tab so the underlying
		// data is fresh (e.g. a new borrower shows up in the search).
		lms_manager._showTab(lms_manager._currentTab);
	}
};

// ---------------------------------------------------------------------------
// Borrowers tab
// ---------------------------------------------------------------------------
lms_manager._loadBorrowers = function (content) {
	content.innerHTML = lms_portal.loading("Loading borrowers…");

	// KPI cards are populated by _renderBorrowerTable from the same dataset.
	var kpis = lms_portal.kpiStrip([
		{ label: "Total borrowers", value: "—", id: "lms-mn-bk-total" },
		{ label: "Active loans", value: "—", id: "lms-mn-bk-active" },
		{ label: "KYC approved", value: "—", id: "lms-mn-bk-kyc" },
		{ label: "Total outstanding", value: "—", id: "lms-mn-bk-outstanding" },
	]);
	var controls =
		'<input type="text" id="lms-borrower-search" class="lms-input" placeholder="Search by name, mobile, email, ID…">' +
		'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-borrower-search-btn">Search</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-borrower-list-all">List All</button>';
	var html = lms_portal.pageStart() +
		kpis +
		lms_portal.panel({ title: "Borrowers", controls: controls, body: '<div id="lms-borrower-results"></div>' }) +
		lms_portal.pageEnd();
	content.innerHTML = html;

	lms_manager._fetchBorrowers(content, "");

	content.querySelector("#lms-borrower-search-btn").addEventListener("click", function () {
		var q = content.querySelector("#lms-borrower-search").value;
		lms_manager._fetchBorrowers(content, q);
	});
	content.querySelector("#lms-borrower-search").addEventListener("keypress", function (e) {
		if (e.key === "Enter") {
			lms_manager._fetchBorrowers(content, content.querySelector("#lms-borrower-search").value);
		}
	});
	content.querySelector("#lms-borrower-list-all").addEventListener("click", function () {
		lms_manager._fetchBorrowers(content, "");
	});
};

lms_manager._fetchBorrowers = function (content, query) {
	var results = content.querySelector("#lms-borrower-results");
	if (!results) return;
	results.innerHTML = lms_portal.loading("Searching…");

	lms_portal.safeCall({
		method: "lms_saas.api.manager.search_borrowers",
		args: { query: query },
		callback: function (r) {
			var borrowers = (r && r.message && r.message.borrowers) || [];
			lms_manager._renderBorrowerTable(results, borrowers);
		},
		error: function () {
			results.innerHTML = lms_portal.error("Could not load borrowers.");
		},
	});
};

lms_manager._renderBorrowerTable = function (el, borrowers) {
	// Update KPI cards from the same dataset. Done before the empty-state
	// check so a "no results" search still shows 0 / — rather than stale
	// counts from a previous list.
	var root = document.getElementById("lms-manager-root");
	if (root) {
		var totalActive = 0;
		var totalKyc = 0;
		var totalOutstanding = 0;
		borrowers.forEach(function (b) {
			totalActive += (b.active_loans || 0);
			if (b.kyc_status === "Approved") totalKyc += 1;
			totalOutstanding += (b.total_outstanding || 0);
		});
		var setKpi = function (id, val) { var n = root.querySelector("#" + id); if (n) n.textContent = val; };
		setKpi("lms-mn-bk-total", borrowers.length);
		setKpi("lms-mn-bk-active", totalActive);
		setKpi("lms-mn-bk-kyc", totalKyc);
		setKpi("lms-mn-bk-outstanding", format_currency(totalOutstanding));
	}

	if (!borrowers.length) {
		el.innerHTML = '<div class="lms-empty"><div class="lms-empty-icon">👤</div><h3>No borrowers found</h3><p>Try a different search or add a new borrower.</p></div>';
		return;
	}
	var html = '<div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Name</th><th>Mobile</th><th>Email</th><th>Loans</th><th>Active</th><th>KYC</th><th>Outstanding</th><th>Actions</th></tr></thead><tbody>";
	borrowers.forEach(function (b) {
		html += "<tr>";
		html += "<td><strong>" + lms_portal.escape(b.customer_name || b.name) + "</strong></td>";
		html += "<td>" + lms_portal.escape(b.mobile_no || "—") + "</td>";
		html += "<td>" + lms_portal.escape(b.email_id || "—") + "</td>";
		html += "<td>" + (b.loan_count || 0) + "</td>";
		html += "<td>" + (b.active_loans || 0) + "</td>";
		html += '<td><span class="lms-badge ' + (b.kyc_status === "Approved" ? "lms-badge--success" : "lms-badge--warning") + '">' + lms_portal.escape(b.kyc_status || "Pending") + "</span></td>";
		html += "<td>" + format_currency(b.total_outstanding || 0) + "</td>";
		html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-borrower-view" data-customer="' + lms_portal.escape(b.name) + '">View</button></td>';
		html += "</tr>";
	});
	html += "</tbody></table></div>";
	el.innerHTML = html;

	el.querySelectorAll(".lms-borrower-view").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._viewBorrower(btn.getAttribute("data-customer"));
		});
	});
};

lms_manager._viewBorrower = function (customerName) {
	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_borrower_detail",
		args: { customer_name: customerName },
		callback: function (r) {
			var b = (r && r.message && r.message.borrower) || {};
			lms_manager._showBorrowerModal(b);
		},
	});
};

lms_manager._showBorrowerModal = function (b) {
	var html = '<div class="lms-form">';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Name</div><div class="lms-summary-value">' + lms_portal.escape(b.customer_name || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Mobile</div><div class="lms-summary-value">' + lms_portal.escape(b.mobile_no || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Email</div><div class="lms-summary-value">' + lms_portal.escape(b.email_id || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">National ID</div><div class="lms-summary-value">' + lms_portal.escape(b.custom_national_id_number || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">KYC Status</div><div class="lms-summary-value">' + lms_portal.escape((b.compliance || {}).kyc_status || "Pending") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Credit Score</div><div class="lms-summary-value">' + lms_portal.escape(String((b.compliance || {}).credit_score || "—")) + '</div></div>';
	html += '</div>';

	if (b.loans && b.loans.length) {
		html += '<h4>Loans (' + b.loans.length + ')</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Loan</th><th>Amount</th><th>Outstanding</th><th>Status</th><th>DPD</th></tr></thead><tbody>';
		b.loans.forEach(function (l) {
			html += "<tr><td><strong>" + lms_portal.escape(l.name) + "</strong></td>";
			html += "<td>" + format_currency(l.loan_amount || 0) + "</td>";
			html += "<td>" + format_currency(l.outstanding || 0) + "</td>";
			html += '<td><span class="lms-badge ' + lms_portal.badgeClass(l.dpd, l.status) + '">' + lms_portal.escape(l.status || "") + "</span></td>";
			html += "<td>" + (l.dpd || 0) + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}

	if (b.recent_repayments && b.recent_repayments.length) {
		html += '<h4 style="margin-top:1rem;">Recent Repayments</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Date</th><th>Loan</th><th>Amount</th><th>Status</th></tr></thead><tbody>';
		b.recent_repayments.forEach(function (r) {
			html += "<tr><td>" + lms_portal.escape(r.posting_date || "") + "</td>";
			html += "<td>" + lms_portal.escape(r.against_loan || "") + "</td>";
			html += "<td>" + format_currency(r.amount_paid || 0) + "</td>";
			html += "<td>" + lms_portal.escape(r.status || "") + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}
	html += '</div>';

	lms_portal.modal({
		title: "Borrower Profile — " + (b.customer_name || ""),
		body: html,
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});
};

// ---------------------------------------------------------------------------
// Loans tab
// ---------------------------------------------------------------------------
lms_manager._loadLoans = function (content) {
	// KPIs are populated by _renderLoanTable from the same dataset.
	var kpis = lms_portal.kpiStrip([
		{ label: "Total loans", value: "—", id: "lms-mn-ln-total" },
		{ label: "Active", value: "—", id: "lms-mn-ln-active" },
		{ label: "Disbursed amount", value: "—", id: "lms-mn-ln-disbursed" },
		{ label: "Outstanding", value: "—", id: "lms-mn-ln-outstanding" },
	]);
	var controls =
		'<select id="lms-loan-status-filter" class="lms-input lms-fallback-select">' +
		'<option value="">All Statuses</option>' +
		'<option value="Disbursed">Disbursed</option>' +
		'<option value="Active">Active</option>' +
		'<option value="Partially Disbursed">Partially Disbursed</option>' +
		'<option value="Closed">Closed</option>' +
		'<option value="Written Off">Written Off</option>' +
		'</select>' +
		'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-loans-refresh">Refresh</button>';
	var html = lms_portal.pageStart() +
		kpis +
		lms_portal.panel({ title: "All Loans", controls: controls, body: '<div id="lms-loan-results"></div>' }) +
		lms_portal.pageEnd();
	content.innerHTML = html;

	lms_manager._fetchLoans(content, "");

	content.querySelector("#lms-loan-status-filter").addEventListener("change", function () {
		lms_manager._fetchLoans(content, this.value);
	});
	content.querySelector("#lms-loans-refresh").addEventListener("click", function () {
		var status = content.querySelector("#lms-loan-status-filter").value;
		lms_manager._fetchLoans(content, status);
	});
};

lms_manager._fetchLoans = function (content, status) {
	var results = content.querySelector("#lms-loan-results");
	if (!results) return;
	results.innerHTML = lms_portal.loading("Loading loans…");

	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_branch_loans",
		args: { status: status || "" },
		callback: function (r) {
			var loans = (r && r.message && r.message.loans) || [];
			lms_manager._renderLoanTable(results, loans);
		},
		error: function () {
			results.innerHTML = lms_portal.error("Could not load loans.");
		},
	});
};

lms_manager._renderLoanTable = function (el, loans) {
	// Update KPI cards from the same dataset.
	var root = document.getElementById("lms-manager-root");
	if (root) {
		var activeCount = 0;
		var totalDisbursed = 0;
		var totalOutstanding = 0;
		loans.forEach(function (l) {
			if (l.status === "Active" || l.status === "Disbursed" || l.status === "Partially Disbursed") activeCount += 1;
			totalDisbursed += l.loan_amount || 0;
			totalOutstanding += l.outstanding || 0;
		});
		var setKpi = function (id, val) { var n = root.querySelector("#" + id); if (n) n.textContent = val; };
		setKpi("lms-mn-ln-total", loans.length);
		setKpi("lms-mn-ln-active", activeCount);
		setKpi("lms-mn-ln-disbursed", format_currency(totalDisbursed));
		setKpi("lms-mn-ln-outstanding", format_currency(totalOutstanding));
	}

	if (!loans.length) {
		el.innerHTML = '<div class="lms-empty"><div class="lms-empty-icon">💰</div><h3>No loans found</h3><p>No loans match the current filter.</p></div>';
		return;
	}
	var html = '<div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Loan #</th><th>Borrower</th><th>Amount</th><th>Outstanding</th><th>Status</th><th>DPD</th><th>Officer</th><th>Actions</th></tr></thead><tbody>";
	loans.forEach(function (l) {
		html += "<tr>";
		html += "<td><strong>" + lms_portal.escape(l.name) + "</strong></td>";
		html += "<td>" + lms_portal.escape(l.customer_name || l.applicant || "—") + "</td>";
		html += "<td>" + format_currency(l.loan_amount || 0) + "</td>";
		html += "<td>" + format_currency(l.outstanding || 0) + "</td>";
		html += '<td><span class="lms-badge ' + lms_portal.badgeClass(l.dpd, l.status) + '">' + lms_portal.escape(l.status || "") + "</span></td>";
		html += "<td>" + (l.dpd || 0) + "</td>";
		html += "<td>" + lms_portal.escape(l.officer_name || "—") + "</td>";
		html += '<td><div class="lms-data-table__actions">';
		html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-loan-view" data-loan="' + lms_portal.escape(l.name) + '">View</button>';
		html += '</div></td>';
		html += "</tr>";
	});
	html += "</tbody></table></div>";
	el.innerHTML = html;

	el.querySelectorAll(".lms-loan-view").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._viewLoan(btn.getAttribute("data-loan"));
		});
	});
};

lms_manager._viewLoan = function (loanName) {
	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_loan_detail",
		args: { loan_name: loanName },
		callback: function (r) {
			var data = (r && r.message) || {};
			// safeCall routes server errors to the callback with _lms_error
			// set — surface those as a toast instead of rendering an empty modal.
			if (data._lms_error || data.message === null && !data.loan) {
				lms_portal.toast("Could not load loan details. Please try again.", "danger");
				return;
			}
			lms_manager._showLoanModal(data);
		},
		error: function (err) {
			var msg = (err && (err.message || err._server_message)) || "Could not load loan details.";
			lms_portal.toast(msg, "danger");
		},
	});
};

lms_manager._showLoanModal = function (data) {
	var l = data.loan || {};
	// Reorder so the two primary financial metrics (Amount, Outstanding) lead —
	// CSS auto-fit grid will lay them out as 4-up at xl width, 2-up at md, 1-up
	// at sm. The --primary modifier makes them visually heavier than the rest.
	var html = '<div class="lms-form">';
	html += '<div class="lms-summary" style="margin-bottom:1.25rem;">';
	html += '<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Amount</div><div class="lms-summary-value">' + format_currency(l.loan_amount || 0) + '</div></div>';
	html += '<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Outstanding</div><div class="lms-summary-value">' + format_currency(l.outstanding || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Loan #</div><div class="lms-summary-value">' + lms_portal.escape(l.name || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Borrower</div><div class="lms-summary-value">' + lms_portal.escape(l.borrower_name || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(l.status || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Rate</div><div class="lms-summary-value">' + (l.rate_of_interest || 0) + '%</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">DPD</div><div class="lms-summary-value">' + (l.dpd || 0) + '</div></div>';
	html += '</div>';

	if (data.schedule && data.schedule.length) {
		html += '<h4>Repayment Schedule</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Date</th><th>Principal</th><th>Interest</th><th>Total</th><th>Paid</th></tr></thead><tbody>';
		data.schedule.forEach(function (s) {
			html += "<tr><td>" + lms_portal.escape(s.payment_date || "") + "</td>";
			html += "<td>" + format_currency(s.principal_amount || 0) + "</td>";
			html += "<td>" + format_currency(s.interest_amount || 0) + "</td>";
			html += "<td>" + format_currency(s.total_payment || 0) + "</td>";
			html += "<td>" + (s.paid ? "✓" : "—") + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}

	if (data.repayments && data.repayments.length) {
		html += '<h4 style="margin-top:1rem;">Repayments</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Date</th><th>Amount</th><th>Status</th></tr></thead><tbody>';
		data.repayments.forEach(function (r) {
			html += "<tr><td>" + lms_portal.escape(r.posting_date || "") + "</td>";
			html += "<td>" + format_currency(r.amount_paid || 0) + "</td>";
			html += "<td>" + lms_portal.escape(r.status || "") + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}

	if (data.collateral && data.collateral.length) {
		html += '<h4 style="margin-top:1rem;">Collateral</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Collateral</th><th>Type</th><th>Allocated</th></tr></thead><tbody>';
		data.collateral.forEach(function (c) {
			html += "<tr><td>" + lms_portal.escape(c.collateral || "") + "</td>";
			html += "<td>" + lms_portal.escape(c.collateral_type || "") + "</td>";
			html += "<td>" + format_currency(c.allocated_value || 0) + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}

	html += '</div>';

	lms_portal.modal({
		title: "Loan Detail — " + (l.name || ""),
		body: html,
		size: "xl",          // 960px so the summary grid engages (4/2/1 cols)
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});
};

// ---------------------------------------------------------------------------
// Reports tab
// ---------------------------------------------------------------------------
lms_manager._loadReports = function (content) {
	// Report switcher on top, full-width results panel below. The KPIs live
	// inside the report content itself (rendered by _loadReport) so they
	// stay in sync with the active report.
	var controls =
		'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-report-btn" data-report="arrears">Arrears Aging</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-report-btn" data-report="disbursement">Disbursement Report</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-report-btn" data-report="collections">Collections Report</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-report-btn" data-report="portfolio">Portfolio Summary</button>';
	var html = lms_portal.pageStart() +
		lms_portal.panel({ title: "Reports", controls: controls }) +
		'<div class="lms-panel" id="lms-report-content"></div>' +
		lms_portal.pageEnd();
	content.innerHTML = html;

	lms_manager._loadReport(content, "arrears");

	content.querySelectorAll(".lms-report-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			content.querySelectorAll(".lms-report-btn").forEach(function (b) {
				b.classList.remove("lms-btn--primary");
				b.classList.add("lms-btn--ghost");
			});
			btn.classList.remove("lms-btn--ghost");
			btn.classList.add("lms-btn--primary");
			lms_manager._loadReport(content, btn.getAttribute("data-report"));
		});
	});
};

lms_manager._loadReport = function (content, reportType) {
	var rc = content.querySelector("#lms-report-content");
	if (!rc) return;
	rc.innerHTML = lms_portal.loading("Loading report…");

	// Each report call now declares both callback AND error so a 500 doesn't
	// leave the user staring at "Loading report…" forever.
	var endpoints = {
		arrears:      { method: "lms_saas.api.manager.get_arrears_aging_report", render: lms_manager._renderArrearsReport,      unwrap: function (m) { return m || {}; } },
		disbursement: { method: "lms_saas.api.manager.get_disbursement_report",  render: lms_manager._renderDisbursementReport, unwrap: function (m) { return m || {}; } },
		collections:  { method: "lms_saas.api.manager.get_collections_report",   render: lms_manager._renderCollectionsReport,  unwrap: function (m) { return m || {}; } },
		portfolio:    { method: "lms_saas.api.manager.get_portfolio_summary",     render: lms_manager._renderPortfolioReport,    unwrap: function (m) { return (m && m.summary) || {}; } },
	};
	var ep = endpoints[reportType];
	if (!ep) {
		rc.innerHTML = lms_portal.error("Unknown report type.");
		return;
	}
	lms_portal.safeCall({
		method: ep.method,
		callback: function (r) { ep.render(rc, ep.unwrap(r && r.message)); },
		error: function () {
			rc.innerHTML = lms_portal.error("Could not load report.", function () {
				lms_manager._loadReport(content, reportType);
			});
		},
	});
};

lms_manager._renderArrearsReport = function (el, data) {
	var b = data.buckets || {};
	var t = data.totals || {};
	var html = '<h4>Arrears Aging — as at ' + lms_portal.escape(data.as_on_date || "") + '</h4>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Current</div><div class="lms-summary-value">' + format_currency(t.current || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">1-30 days</div><div class="lms-summary-value">' + format_currency(t["1_30"] || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">31-60 days</div><div class="lms-summary-value">' + format_currency(t["31_60"] || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">61-90 days</div><div class="lms-summary-value">' + format_currency(t["61_90"] || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">90+ days</div><div class="lms-summary-value">' + format_currency(t["90_plus"] || 0) + '</div></div>';
	html += '</div>';

	var bucketLabels = {"current": "Current", "1_30": "1-30 Days", "31_60": "31-60 Days", "61_90": "61-90 Days", "90_plus": "90+ Days"};
	Object.keys(bucketLabels).forEach(function (key) {
		var rows = b[key] || [];
		if (!rows.length) return;
		html += '<h5 style="margin-top:1rem;">' + bucketLabels[key] + ' (' + rows.length + ' loans)</h5>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Loan</th><th>Borrower</th><th>Outstanding</th><th>DPD</th><th>Status</th></tr></thead><tbody>';
		rows.forEach(function (r) {
			html += "<tr><td>" + lms_portal.escape(r.loan) + "</td>";
			html += "<td>" + lms_portal.escape(r.customer_name || "") + "</td>";
			html += "<td>" + format_currency(r.outstanding || 0) + "</td>";
			html += "<td>" + (r.dpd || 0) + "</td>";
			html += "<td>" + lms_portal.escape(r.status || "") + "</td></tr>";
		});
		html += "</tbody></table></div>";
	});
	el.innerHTML = html;
};

lms_manager._renderDisbursementReport = function (el, data) {
	var html = '<h4>Disbursement Report</h4>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Disbursed</div><div class="lms-summary-value">' + format_currency(data.total_disbursed || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Count</div><div class="lms-summary-value">' + (data.count || 0) + '</div></div>';
	html += '</div>';
	var hasAny = (data.by_officer && data.by_officer.length) || (data.disbursements && data.disbursements.length);
	if (!hasAny) {
		html += '<div class="lms-empty"><div class="lms-empty-icon">💸</div><h3>No disbursements in this period</h3><p>Once the manager / officer disburses a loan it will appear here.</p></div>';
		el.innerHTML = html;
		return;
	}
	if (data.by_officer && data.by_officer.length) {
		html += '<h5>By Officer</h5>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Officer</th><th>Count</th><th>Total</th></tr></thead><tbody>';
		data.by_officer.forEach(function (o) {
			html += "<tr><td>" + lms_portal.escape(o.officer_name || "") + "</td><td>" + (o.count || 0) + "</td><td>" + format_currency(o.total || 0) + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}
	if (data.disbursements && data.disbursements.length) {
		html += '<h5 style="margin-top:1rem;">Detail</h5>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Date</th><th>Loan</th><th>Borrower</th><th>Amount</th><th>Officer</th></tr></thead><tbody>';
		data.disbursements.forEach(function (d) {
			html += "<tr><td>" + lms_portal.escape(d.posting_date || "") + "</td><td>" + lms_portal.escape(d.against_loan || "") + "</td><td>" + lms_portal.escape(d.customer_name || "") + "</td><td>" + format_currency(d.disbursed_amount || 0) + "</td><td>" + lms_portal.escape(d.officer_name || "") + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}
	el.innerHTML = html;
};

lms_manager._renderCollectionsReport = function (el, data) {
	var html = '<h4>Collections Report</h4>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Collected</div><div class="lms-summary-value">' + format_currency(data.total_collected || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Count</div><div class="lms-summary-value">' + (data.count || 0) + '</div></div>';
	html += '</div>';
	// Empty state: a report can be perfectly valid with zero rows.
	var hasAny = (data.by_officer && data.by_officer.length) || (data.repayments && data.repayments.length);
	if (!hasAny) {
		html += '<div class="lms-empty"><div class="lms-empty-icon">📭</div><h3>No collections in this period</h3><p>Once repayments are recorded they will appear here.</p></div>';
		el.innerHTML = html;
		return;
	}
	if (data.by_officer && data.by_officer.length) {
		html += '<h5>By Officer</h5>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Officer</th><th>Count</th><th>Total</th></tr></thead><tbody>';
		data.by_officer.forEach(function (o) {
			html += "<tr><td>" + lms_portal.escape(o.officer_name || "") + "</td><td>" + (o.count || 0) + "</td><td>" + format_currency(o.total || 0) + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}
	if (data.repayments && data.repayments.length) {
		html += '<h5 style="margin-top:1rem;">Detail</h5>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Date</th><th>Loan</th><th>Borrower</th><th>Amount</th><th>Officer</th></tr></thead><tbody>';
		data.repayments.forEach(function (r) {
			html += "<tr><td>" + lms_portal.escape(r.posting_date || "") + "</td><td>" + lms_portal.escape(r.against_loan || "") + "</td><td>" + lms_portal.escape(r.customer_name || "") + "</td><td>" + format_currency(r.amount_paid || 0) + "</td><td>" + lms_portal.escape(r.officer_name || "") + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}
	el.innerHTML = html;
};

lms_manager._renderPortfolioReport = function (el, s) {
	var html = '<h4>Portfolio Summary</h4>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Loans</div><div class="lms-summary-value">' + (s.total_loans || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Outstanding</div><div class="lms-summary-value">' + format_currency(s.total_outstanding || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Current</div><div class="lms-summary-value">' + format_currency(s.current_outstanding || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR 30+</div><div class="lms-summary-value">' + format_currency(s.par30_outstanding || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR 60+</div><div class="lms-summary-value">' + format_currency(s.par60_outstanding || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR 90+</div><div class="lms-summary-value">' + format_currency(s.par90_outstanding || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">NPA Count</div><div class="lms-summary-value">' + (s.npa_count || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR Ratio</div><div class="lms-summary-value">' + ((s.par_ratio || 0) * 100).toFixed(1) + '%</div></div>';
	html += '</div>';
	el.innerHTML = html;
};

// ---------------------------------------------------------------------------
// Collateral tab
// ---------------------------------------------------------------------------
lms_manager._loadCollateral = function (content) {
	content.innerHTML = lms_portal.loading("Loading collateral register…");
	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_collateral_register",
		callback: function (r) {
			var collateral = (r && r.message && r.message.collateral) || [];
			lms_manager._renderCollateralRegister(content, collateral);
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load collateral register.");
		},
	});
};

lms_manager._renderCollateralRegister = function (el, collateral) {
	// Compute KPIs from the dataset so the strip and table stay in sync.
	var totalMarket = 0;
	var totalNrv = 0;
	var linkedLoans = 0;
	collateral.forEach(function (c) {
		totalMarket += c.market_value || 0;
		totalNrv += c.net_realizable_value || 0;
		linkedLoans += ((c.linked_loans || []).length);
	});

	var html = lms_portal.pageStart() +
		lms_portal.kpiStrip([
			{ label: "Items", value: collateral.length },
			{ label: "Market value", value: format_currency(totalMarket) },
			{ label: "Net realisable", value: format_currency(totalNrv) },
			{ label: "Linked loans", value: linkedLoans },
		]);

	if (!collateral.length) {
		html += lms_portal.emptyPanel("🏠", "No collateral registered", "Collateral will appear here once loans have pledged assets.");
		html += lms_portal.pageEnd();
		el.innerHTML = html;
		return;
	}

	var body = '<div class="lms-data-table__wrap"><table class="lms-data-table">' +
		"<thead><tr><th>Collateral #</th><th>Type</th><th>Description</th><th>Market Value</th><th>NRV</th><th>Status</th><th>Linked Loans</th></tr></thead><tbody>";
	collateral.forEach(function (c) {
		body += "<tr>";
		body += "<td><strong>" + lms_portal.escape(c.name || "") + "</strong></td>";
		body += "<td>" + lms_portal.escape(c.collateral_type || "—") + "</td>";
		body += "<td>" + lms_portal.escape(c.collateral_title || "—") + "</td>";
		body += "<td>" + format_currency(c.market_value || 0) + "</td>";
		body += "<td>" + format_currency(c.net_realizable_value || 0) + "</td>";
		body += "<td>" + lms_portal.escape(c.status || "—") + "</td>";
		body += "<td>" + ((c.linked_loans || []).length) + "</td>";
		body += "</tr>";
	});
	body += "</tbody></table></div>";
	html += lms_portal.panel({ title: "Collateral Register", badge: collateral.length + " items", body: body });
	html += lms_portal.pageEnd();
	el.innerHTML = html;
};

// ---------------------------------------------------------------------------
// Team tab
// ---------------------------------------------------------------------------
lms_manager._loadTeam = function (content) {
	content.innerHTML = lms_portal.loading("Loading team…");
	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_branch_staff",
		callback: function (r) {
			var staff = (r && r.message && r.message.staff) || [];
			lms_manager._renderTeam(content, staff);
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load team.");
		},
	});
};

lms_manager._renderTeam = function (el, staff) {
	// Compute KPIs from the dataset.
	var totalLoans = 0;
	var byPersona = {};
	staff.forEach(function (s) {
		totalLoans += s.loan_count || 0;
		var p = s.persona || "—";
		byPersona[p] = (byPersona[p] || 0) + 1;
	});
	// Pick the dominant persona for the "Top role" card.
	var topPersona = "—";
	var topCount = 0;
	Object.keys(byPersona).forEach(function (k) {
		if (byPersona[k] > topCount) { topCount = byPersona[k]; topPersona = k; }
	});

	var html = lms_portal.pageStart() +
		lms_portal.kpiStrip([
			{ label: "Members", value: staff.length },
			{ label: "Loans managed", value: totalLoans },
			{ label: "Avg per member", value: staff.length ? Math.round(totalLoans / staff.length) : 0 },
			{ label: "Top role", value: topPersona },
		]);

	if (!staff.length) {
		html += lms_portal.emptyPanel("👥", "No staff found", "No active staff in your branch.");
		html += lms_portal.pageEnd();
		el.innerHTML = html;
		return;
	}

	var body = '<div class="lms-data-table__wrap"><table class="lms-data-table">' +
		"<thead><tr><th>Name</th><th>Designation</th><th>Persona</th><th>Loans</th><th>User</th></tr></thead><tbody>";
	staff.forEach(function (s) {
		body += "<tr>";
		body += "<td><strong>" + lms_portal.escape(s.employee_name || s.name) + "</strong></td>";
		body += "<td>" + lms_portal.escape(s.designation || "—") + "</td>";
		body += '<td><span class="lms-badge">' + lms_portal.escape(s.persona || "—") + "</span></td>";
		body += "<td>" + (s.loan_count || 0) + "</td>";
		body += "<td>" + lms_portal.escape(s.user_id || "—") + "</td>";
		body += "</tr>";
	});
	body += "</tbody></table></div>";
	html += lms_portal.panel({ title: "Branch Team", badge: staff.length + " members", body: body });
	html += lms_portal.pageEnd();
	el.innerHTML = html;
};