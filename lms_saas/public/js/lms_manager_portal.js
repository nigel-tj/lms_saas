/* LMS Branch Manager portal — dashboard, approvals, team performance, borrowers, loans, reports, collateral */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_manager");
} else {
	window.lms_manager = window.lms_manager || {};
}

lms_manager._charts = {};
lms_manager._currentTab = "dashboard";
// R18-14: keep a per-tab timeout so a stuck safeCall can never leave the
// content area on a perpetual "Loading…" spinner. After 6 s we render an
// error card with a Retry button instead.
lms_manager._TAB_TIMEOUT_MS = 6000;

lms_manager.init = function () {
	// R18-defensive: defer init if lms_portal hasn't finished parsing yet.
	if (typeof lms_portal === "undefined" || typeof lms_portal.tabNav !== "function") {
		return setTimeout(lms_manager.init, 0);
	}
	var root = document.getElementById("lms-manager-root");
	if (!root) return;

	// Render tab navigation first
	root.innerHTML = lms_manager._tabNav() + '<div id="lms-manager-tab-content"></div>';
	lms_manager._bindTabs();
	lms_manager._showTab(lms_manager._currentTab);
};

lms_manager._tabNav = function () {
	// R18-15: add the Approvals tab between Loans and Reports. Four-eyes
	// approvals are the single most important action on this page for a
	// branch manager; not having a tab for them was the #1 staff-side
	// complaint from the R18 board.
	var tabs = [
		{ id: "dashboard", label: "Dashboard", icon: "bar-chart" },
		{ id: "borrowers", label: "Borrowers", icon: "user" },
		{ id: "loans", label: "Loans", icon: "wallet" },
		{ id: "approvals", label: "Approvals", icon: "check-square" },
		{ id: "reports", label: "Reports", icon: "trending-up" },
		{ id: "collateral", label: "Collateral", icon: "home" },
		{ id: "team", label: "Team", icon: "users" },
	];
	var html = '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_manager._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + (window.lms_icons ? lms_icons.icon(t.icon, { cls: "lms-tab-icon" }) : t.icon) + " " + lms_portal.escape(t.label) + "</button>";
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

/* R18-14: render a clear "this tab timed out" card instead of leaving a
 * perpetual spinner. The card includes a Retry button that re-invokes the
 * caller-supplied renderFn. Always reachable: every timeout path produces
 * the same DOM. */
lms_manager._renderTabError = function (content, tabId, message) {
	content.innerHTML =
		'<div class="lms-panel lms-error" role="alert">' +
		'<h3 style="margin:0 0 0.5rem;">' + lms_portal.escape(tabId) + ' could not load</h3>' +
		'<p>' + lms_portal.escape(message || "The server did not respond in time.") + '</p>' +
		'<p class="lms-muted" style="margin-top:0.5rem;">You can retry, or switch to another tab — your session is still active.</p>' +
		'<div style="display:flex;gap:0.5rem;margin-top:1rem;">' +
		'<button type="button" class="lms-btn lms-btn--primary" id="lms-tab-retry-' + lms_portal.escape(tabId) + '">Retry</button>' +
		'</div></div>';
	var retry = document.getElementById("lms-tab-retry-" + tabId);
	if (retry) {
		retry.addEventListener("click", function () {
			lms_manager._showTab(tabId);
		});
	}
};

/* R18-14: timeout-guarded wrapper around safeCall. Resolves on success
 * or on a 4 s timeout with an error object. Use this instead of raw
 * safeCall for any tab that has more than one render dependency. */
lms_manager._guardedCall = function (opts) {
	return new Promise(function (resolve) {
		var settled = false;
		var finish = function (ok, payload) {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			resolve({ ok: ok, payload: payload });
		};
		var timer = setTimeout(function () {
			finish(false, { status: 0, message: "Timed out after " + lms_manager._TAB_TIMEOUT_MS + " ms" });
		}, lms_manager._TAB_TIMEOUT_MS);

		lms_portal.safeCall({
			method: opts.method,
			args: opts.args,
			callback: function (r) {
				finish(true, r);
			},
			error: function (err) {
				finish(false, err || { status: 0, message: "Unknown error" });
			},
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
	} else if (tabId === "approvals") {
		lms_manager._loadApprovals(content);
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
	// R18-14: replaced the old `dashLoaded`/`queueLoaded` flag dance (which
	// could leave `Loading…` forever if the second safeCall errored
	// silently) with a guarded Promise.all + timeout. Both endpoints have
	// to resolve; if either times out, the dashboard renders the existing
	// approval-queue data we already have (if any) plus an error strip.
	var timeoutHandles = [];
	var guard = function (p) {
		var t = setTimeout(function () {}, 0);
		clearTimeout(t);
		return p;
	};

	var dashP = lms_manager._guardedCall({ method: "lms_saas.api.manager.get_manager_dashboard" });
	var queueP = lms_manager._guardedCall({ method: "lms_saas.api.manager.get_approval_queue" });

	Promise.all([dashP, queueP]).then(function (results) {
		var dashRes = results[0];
		var queueRes = results[1];
		if (!dashRes.ok && !queueRes.ok) {
			lms_manager._renderTabError(content, "dashboard", "Both the dashboard metrics and the approval queue failed to load. Check the API status and try again.");
			return;
		}
		var dashData = dashRes.ok ? ((dashRes.payload && dashRes.payload.message) || {}) : {};
		var queueData = queueRes.ok ? ((queueRes.payload && queueRes.payload.message) || { applications: [] }) : { applications: [] };
		if (!dashRes.ok) {
			// One endpoint down — show the queue + a soft warning, do not
			// crash the whole dashboard.
			content.innerHTML =
				'<div class="lms-panel" role="status">' +
				'<p class="lms-muted">Dashboard metrics are temporarily unavailable. Approval queue is shown below.</p>' +
				'</div>';
			lms_manager._renderApprovalsTable(content, queueData, false);
			return;
		}
		lms_manager._renderAll(content, dashData, queueData);
	});
};

// ---------------------------------------------------------------------------
// Approvals tab (R18-15)
// ---------------------------------------------------------------------------
lms_manager._loadApprovals = function (content) {
	lms_manager._guardedCall({ method: "lms_saas.api.manager.get_approval_queue" }).then(function (res) {
		if (!res.ok) {
			lms_manager._renderTabError(content, "approvals", "The approval queue did not respond. Try again in a moment.");
			return;
		}
		var data = (res.payload && res.payload.message) || { applications: [] };
		lms_manager._renderApprovalsTable(content, data, true);
	});
};

lms_manager._renderApprovalsTable = function (content, queueData, showHeader) {
	var apps = (queueData && queueData.applications) || [];
	var html = "";
	if (showHeader) {
		html += '<div class="lms-panel lms-portal-board" role="region" aria-label="Approval queue">';
		html += '<div class="lms-section-header"><h3>Approval Queue</h3>';
		html += '<span class="lms-muted">' + apps.length + " pending</span></div>";
	} else {
		html += '<div class="lms-panel lms-portal-board" role="region" aria-label="Approval queue (partial)">';
		html += '<div class="lms-section-header"><h3>Approval Queue</h3>';
		html += '<span class="lms-muted">' + apps.length + " pending</span></div>";
	}
	if (queueData && queueData.sandbox_filtered) {
		html += '<p class="lms-muted" style="margin:0 0 0.75rem;">Demo seed applicants are hidden in sandbox mode.</p>';
	}
	if (!apps.length) {
		html += '<div class="lms-empty">' + (window.lms_icons ? lms_icons.empty("check") : "") +
			"<h3>All caught up</h3><p>No applications pending approval.</p></div>";
	} else {
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
		html += "<thead><tr><th>Applicant</th><th>Product</th><th>Amount</th><th>Officer</th><th>Branch</th><th>Created</th><th>Actions</th></tr></thead><tbody>";
		apps.forEach(function (app) {
			html += "<tr>";
			html += "<td><strong>" + lms_portal.escape(app.customer_name || app.applicant || "—") + "</strong></td>";
			html += "<td>" + lms_portal.escape(app.product_name || app.loan_product || "") + "</td>";
			html += "<td class=\"is-num\">" + (window.format_currency ? format_currency(app.loan_amount || 0) : (app.loan_amount || 0)) + "</td>";
			html += "<td>" + lms_portal.escape(app.officer_name || app.custom_loan_officer || "—") + "</td>";
			html += "<td>" + lms_portal.escape(app.custom_lms_branch || "—") + "</td>";
			html += "<td>" + lms_portal.escape((app.creation || "").slice(0, 10)) + "</td>";
			html += '<td><div class="lms-data-table__actions">';
			html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-review-btn" data-app="' + lms_portal.escape(app.name) + '">Review</button>';
			html += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-approve-btn" data-app="' + lms_portal.escape(app.name) + '">Approve</button>';
			html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-reject-btn" data-app="' + lms_portal.escape(app.name) + '">Reject</button>';
			html += "</div></td></tr>";
		});
		html += "</tbody></table></div>";
	}
	html += "</div>";
	content.insertAdjacentHTML("beforeend", html);

	content.querySelectorAll(".lms-review-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._reviewApplication(btn.getAttribute("data-app"));
		});
	});
	content.querySelectorAll(".lms-approve-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._approve(btn.getAttribute("data-app"));
		});
	});
	content.querySelectorAll(".lms-reject-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._reject(btn.getAttribute("data-app"));
		});
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
		html += '<div class="lms-empty">' + lms_icons.empty("check");
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
			html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-review-btn" data-app="' + lms_portal.escape(app.name) + '">Review</button>';
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

	/* ---- Bind review / approve / reject buttons ---- */
	root.querySelectorAll(".lms-review-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._reviewApplication(btn.getAttribute("data-app"));
		});
	});
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
	// Prefer the shared lms_icons registry so every page uses one icon source;
	// fall back to the inline map for any key not yet in the registry.
	if (window.lms_icons && typeof lms_icons.icon === "function") {
		var svg = lms_icons.icon(name);
		if (svg) return svg;
	}
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

lms_manager._reviewApplication = function (appName) {
	// R25: full review modal for the manager approval queue. Loads the
	// application via the portal API and renders it with full detail
	// (KYC, schedule, collateral, audit) + Approve / Reject buttons.
	if (!appName) return;
	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_manager_application_detail",
		args: { application_name: appName },
		callback: function (r) {
			var data = (r && r.message) || {};
			if (data._lms_error) {
				lms_portal.toast("Could not load application details.", "danger");
				return;
			}
			lms_manager._showReviewModal(data);
		},
		error: function (err) {
			var msg = (err && (err.message || err._server_message)) || "Could not load application details.";
			lms_portal.toast(msg, "danger");
		},
	});
};

lms_manager._showReviewModal = function (data) {
	var a = data.application || {};
	var p = data.product || {};
	var kyc = data.kyc || {};
	var schedule = data.schedule || [];
	var collateral = data.collateral || [];
	var audit = data.audit || [];
	var existingLoans = data.existing_loans || [];

	var html = '<div class="lms-form">';

	// Summary cards
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Borrower</div><div class="lms-summary-value">' + lms_portal.escape(a.applicant_name || "—") + "</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Mobile</div><div class="lms-summary-value">' + lms_portal.escape(a.applicant_mobile || "—") + "</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Email</div><div class="lms-summary-value">' + lms_portal.escape(a.applicant_email || "—") + "</div></div>";
	html += '<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Amount</div><div class="lms-summary-value">' + format_currency(a.loan_amount || 0) + "</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Product</div><div class="lms-summary-value">' + lms_portal.escape(p.product_name || a.loan_product || "—") + "</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Rate / Periods</div><div class="lms-summary-value">' + (a.rate_of_interest || 0) + "% / " + (a.repayment_periods || 0) + " mo</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Officer</div><div class="lms-summary-value">' + lms_portal.escape(a.officer_name || "—") + "</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Branch</div><div class="lms-summary-value">' + lms_portal.escape(a.custom_lms_branch || "—") + "</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(a.status || "—") + "</div></div>";
	html += "</div>";

	if (a.loan_purpose) {
		html += '<p><strong>Purpose:</strong> ' + lms_portal.escape(a.loan_purpose) + "</p>";
	}

	// KYC + AML block
	if (kyc && kyc.name) {
		html += "<h4>KYC & AML</h4>";
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><tbody>';
		html += "<tr><td>KYC status</td><td>" + lms_portal.escape(kyc.kyc_status || "—") + "</td></tr>";
		html += "<tr><td>AML status</td><td>" + (kyc.aml_status === "Clear" ? "✓ " : "⚠ ") + lms_portal.escape(kyc.aml_status || "—") + "</td></tr>";
		html += "<tr><td>AML screened</td><td>" + lms_portal.escape(kyc.aml_screened_at || "—") + "</td></tr>";
		html += "<tr><td>National ID</td><td>" + lms_portal.escape(kyc.national_id_number || "—") + "</td></tr>";
		html += "<tr><td>Consent</td><td>" + (kyc.consent_captured ? "✓ captured" : "—") + (kyc.consent_date ? " on " + lms_portal.escape(kyc.consent_date) : "") + "</td></tr>";
		if (kyc.credit_score) {
			html += "<tr><td>Credit score</td><td>" + lms_portal.escape(String(kyc.credit_score)) + "</td></tr>";
		}
		if (kyc.debt_to_income_ratio) {
			html += "<tr><td>Debt-to-income</td><td>" + lms_portal.escape(String(kyc.debt_to_income_ratio)) + "</td></tr>";
		}
		html += "</tbody></table></div>";
	}

	// Existing loans (manager decision input)
	if (existingLoans.length) {
		html += "<h4>Existing loans (" + existingLoans.length + ")</h4>";
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Loan</th><th>Amount</th><th>Status</th></tr></thead><tbody>';
		existingLoans.forEach(function (l) {
			html += "<tr>";
			html += "<td><strong>" + lms_portal.escape(l.name) + "</strong></td>";
			html += "<td>" + format_currency(l.loan_amount) + "</td>";
			html += "<td>" + lms_portal.escape(l.status || "") + "</td>";
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}

	// Repayment schedule
	if (schedule.length) {
		html += "<h4>Repayment Schedule</h4>";
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Date</th><th>Principal</th><th>Interest</th><th>Total</th><th>Balance</th></tr></thead><tbody>';
		schedule.forEach(function (s) {
			html += "<tr>";
			html += "<td>" + lms_portal.escape(s.date || "") + "</td>";
			html += "<td>" + format_currency(s.principal) + "</td>";
			html += "<td>" + format_currency(s.interest) + "</td>";
			html += "<td>" + format_currency(s.total) + "</td>";
			html += "<td>" + format_currency(s.balance) + "</td>";
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}

	// Collateral
	if (collateral.length) {
		html += "<h4>Collateral</h4>";
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Type</th><th>Title</th><th>Market value</th><th>Status</th></tr></thead><tbody>';
		collateral.forEach(function (c) {
			html += "<tr>";
			html += "<td>" + lms_portal.escape(c.collateral_type || "") + "</td>";
			html += "<td>" + lms_portal.escape(c.collateral_title || c.name || "") + "</td>";
			html += "<td>" + format_currency(c.market_value) + "</td>";
			html += "<td>" + lms_portal.escape(c.status || "") + "</td>";
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}

	// Audit trail
	if (audit.length) {
		html += "<h4>Audit trail</h4>";
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>When</th><th>Who</th><th>Event</th><th>Details</th></tr></thead><tbody>';
		audit.forEach(function (e) {
			html += "<tr>";
			html += "<td>" + lms_portal.escape(e.creation || "") + "</td>";
			html += "<td>" + lms_portal.escape(e.actor || "") + "</td>";
			html += "<td>" + lms_portal.escape(e.event_type || "") + "</td>";
			html += "<td>" + lms_portal.escape(e.details || "") + "</td>";
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}

	html += "</div>";

	// Approve / Reject actions (only for submitted applications)
	var canDecide = a.docstatus === 1;
	var modalOpts = {
		title: "Review — " + (a.applicant_name || a.name || ""),
		size: "xl",
		body: html,
		confirmText: canDecide ? "Approve" : "Close",
		confirmVariant: canDecide ? "success" : "primary",
		showReject: canDecide,
		rejectText: "Reject",
	};
	if (canDecide) {
		modalOpts.onConfirm = function () {
			lms_portal.safeCall({
				method: "lms_saas.api.manager.approve_application",
				args: { application_name: a.name },
				callback: function (r) {
					var res = (r && r.message) || {};
					if (res.status === "approved" && res.loan) {
						lms_portal.toast("Approved — Loan " + res.loan + " created.", "success");
					} else {
						lms_portal.toast((res && res.message) || "Approval did not complete.", "danger");
					}
					lms_manager._refreshDashboardData();
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Approval failed.";
					lms_portal.toast(msg, "danger");
				},
			});
		};
		modalOpts.onReject = function (overlay) {
			// Open the reject reason modal (reuse _reject flow)
			lms_manager._reject(a.name);
		};
	}

	lms_portal.modal(modalOpts);
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

	var html = '<div class="lms-panel">';
	html += '<div class="lms-section-header"><h3>Borrowers</h3>';
	html += '<div style="display:flex;gap:0.5rem;align-items:center;">';
	html += '<input type="text" id="lms-borrower-search" class="lms-input" placeholder="Search by name, mobile, email, ID…" style="flex:1;min-width:200px;">';
	html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-borrower-search-btn">Search</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-borrower-list-all">List All</button>';
	html += '</div></div>';
	html += '<div id="lms-borrower-results"></div>';
	html += '</div>';
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
			// R18-14: replace spinner with an actionable error card.
			results.innerHTML =
				'<div class="lms-panel lms-error" role="alert">' +
				'<p>Could not load borrowers.</p>' +
				'<button type="button" class="lms-btn lms-btn--primary" id="lms-borrowers-retry">Retry</button>' +
				'</div>';
			var retry = results.querySelector("#lms-borrowers-retry");
			if (retry) retry.addEventListener("click", function () {
				lms_manager._fetchBorrowers(content, query);
			});
		},
	});
};

lms_manager._renderBorrowerTable = function (el, borrowers) {
	if (!borrowers.length) {
		el.innerHTML = '<div class="lms-empty">' + lms_icons.empty("user") + '<h3>No borrowers found</h3><p>Try a different search or add a new borrower.</p></div>';
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
	var html = '<div class="lms-panel">';
	html += '<div class="lms-section-header"><h3>All Loans</h3>';
	html += '<div style="display:flex;gap:0.5rem;align-items:center;">';
	html += '<select id="lms-loan-status-filter" class="lms-input lms-fallback-select" style="width:auto;">';
	html += '<option value="">All Statuses</option>';
	html += '<option value="Disbursed">Disbursed</option>';
	html += '<option value="Active">Active</option>';
	html += '<option value="Partially Disbursed">Partially Disbursed</option>';
	html += '<option value="Closed">Closed</option>';
	html += '<option value="Written Off">Written Off</option>';
	html += '</select>';
	html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-loans-refresh">Refresh</button>';
	html += '</div></div>';
	html += '<div id="lms-loan-results"></div>';
	html += '</div>';
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
			// R18-14: actionable error card, not a stuck spinner.
			results.innerHTML =
				'<div class="lms-panel lms-error" role="alert">' +
				'<p>Could not load loans.</p>' +
				'<button type="button" class="lms-btn lms-btn--primary" id="lms-loans-retry">Retry</button>' +
				'</div>';
			var retry = results.querySelector("#lms-loans-retry");
			if (retry) retry.addEventListener("click", function () {
				lms_manager._fetchLoans(content, status);
			});
		},
	});
};

lms_manager._renderLoanTable = function (el, loans) {
	if (!loans.length) {
		el.innerHTML = '<div class="lms-empty">' + lms_icons.empty("wallet") + '<h3>No loans found</h3><p>No loans match the current filter.</p></div>';
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
			html += "<td>" + (s.paid ? lms_icons.icon("check") : "—") + "</td></tr>";
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
	var html = '<div class="lms-panel">';
	html += '<div class="lms-section-header"><h3>Reports</h3></div>';
	html += '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:1rem;">';
	html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-report-btn" data-report="arrears">Arrears Aging</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-report-btn" data-report="disbursement">Disbursement Report</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-report-btn" data-report="collections">Collections Report</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-report-btn" data-report="portfolio">Portfolio Summary</button>';
	html += '</div>';
	html += '<div id="lms-report-content"></div>';
	html += '</div>';
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
		html += '<div class="lms-empty">' + lms_icons.empty("banknote") + '<h3>No disbursements in this period</h3><p>Once the manager / officer disburses a loan it will appear here.</p></div>';
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
		html += '<div class="lms-empty">' + lms_icons.empty("inbox") + '<h3>No collections in this period</h3><p>Once repayments are recorded they will appear here.</p></div>';
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
			// R18-14: actionable error card with retry, not a stuck spinner.
			lms_manager._renderTabError(content, "collateral", "The collateral register did not respond.");
		},
	});
};

lms_manager._renderCollateralRegister = function (el, collateral) {
	if (!collateral.length) {
		el.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("home") + '<h3>No collateral registered</h3><p>Collateral will appear here once loans have pledged assets.</p></div></div>';
		return;
	}
	var html = '<div class="lms-panel">';
	html += '<div class="lms-section-header"><h3>Collateral Register</h3><span class="lms-muted">' + collateral.length + ' items</span></div>';
	html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Collateral #</th><th>Type</th><th>Description</th><th>Market Value</th><th>NRV</th><th>Status</th><th>Linked Loans</th></tr></thead><tbody>";
	collateral.forEach(function (c) {
		html += "<tr>";
		html += "<td><strong>" + lms_portal.escape(c.name || "") + "</strong></td>";
		html += "<td>" + lms_portal.escape(c.collateral_type || "—") + "</td>";
		html += "<td>" + lms_portal.escape(c.collateral_title || "—") + "</td>";
		html += "<td>" + format_currency(c.market_value || 0) + "</td>";
		html += "<td>" + format_currency(c.net_realizable_value || 0) + "</td>";
		html += "<td>" + lms_portal.escape(c.status || "—") + "</td>";
		html += "<td>" + ((c.linked_loans || []).length) + "</td>";
		html += "</tr>";
	});
	html += "</tbody></table></div></div>";
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
			// R18-14: actionable error card with retry, not a stuck spinner.
			lms_manager._renderTabError(content, "team", "The branch team list did not respond.");
		},
	});
};

lms_manager._renderTeam = function (el, staff) {
	if (!staff.length) {
		el.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("users") + '<h3>No staff found</h3><p>No active staff in your branch.</p></div></div>';
		return;
	}
	var html = '<div class="lms-panel">';
	html += '<div class="lms-section-header"><h3>Branch Team</h3><span class="lms-muted">' + staff.length + ' members</span></div>';
	html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Name</th><th>Designation</th><th>Persona</th><th>Loans</th><th>Borrowers</th><th>User</th></tr></thead><tbody>";
	staff.forEach(function (s) {
		var rowId = "lms-team-row-" + lms_portal.escape(s.name);
		html += '<tr class="lms-clickable" data-employee="' + lms_portal.escape(s.name) + '" id="' + rowId + '">';
		html += "<td><strong>" + lms_portal.escape(s.employee_name || s.name) + "</strong></td>";
		html += "<td>" + lms_portal.escape(s.designation || "—") + "</td>";
		html += '<td><span class="lms-badge">' + lms_portal.escape(s.persona || "—") + "</span></td>";
		html += "<td>" + (s.loan_count || 0) + "</td>";
		html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-team-toggle" data-employee="' + lms_portal.escape(s.name) + '">' + (s.borrower_count || 0) + " borrowers</button></td>";
		html += "<td>" + lms_portal.escape(s.user_id || "—") + "</td>";
		html += "</tr>";
		html += '<tr class="lms-team-detail" id="lms-team-detail-' + lms_portal.escape(s.name) + '" style="display:none;"><td colspan="6"><div class="lms-team-borrowers" data-loaded="0">Loading borrowers…</div></td></tr>';
	});
	html += "</tbody></table></div></div>";
	el.innerHTML = html;

	el.querySelectorAll(".lms-team-toggle").forEach(function (btn) {
		btn.addEventListener("click", function (e) {
			e.stopPropagation();
			var emp = btn.getAttribute("data-employee");
			var detail = el.querySelector("#lms-team-detail-" + CSS.escape(emp));
			if (!detail) return;
			var visible = detail.style.display !== "none";
			detail.style.display = visible ? "none" : "table-row";
			if (!visible) lms_manager._loadOfficerBorrowers(detail.querySelector(".lms-team-borrowers"), emp);
		});
	});
};

lms_manager._loadOfficerBorrowers = function (container, employee) {
	if (!container || container.getAttribute("data-loaded") === "1") return;
	container.innerHTML = lms_portal.loading("Loading borrowers…");
	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_officer_borrowers",
		args: { employee: employee },
		callback: function (r) {
			var borrowers = (r && r.message && r.message.borrowers) || [];
			if (!borrowers.length) {
				container.innerHTML = '<div class="lms-empty">' + lms_icons.empty("user") + '<h3>No borrowers assigned</h3><p>This officer has no active loans yet.</p></div>';
				container.setAttribute("data-loaded", "1");
				return;
			}
			var html = '<div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Borrower</th><th>Active loans</th><th>Outstanding</th></tr></thead><tbody>";
			borrowers.forEach(function (b) {
				html += "<tr><td><strong>" + lms_portal.escape(b.customer_name || b.customer) + "</strong></td>";
				html += "<td>" + (b.active_loans || 0) + "</td>";
				html += "<td>" + format_currency(b.outstanding || 0) + "</td></tr>";
			});
			html += "</tbody></table></div>";
			container.innerHTML = html;
			container.setAttribute("data-loaded", "1");
		},
		error: function () {
			container.innerHTML = lms_portal.error("Could not load borrowers.");
		},
	});
};