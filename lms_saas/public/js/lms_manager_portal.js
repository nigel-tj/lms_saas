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

lms_manager._tabs = [
	{ id: "dashboard", label: "Dashboard", icon: "📊" },
	{ id: "borrowers", label: "Borrowers", icon: "👤" },
	{ id: "loans", label: "Loans", icon: "💰" },
	{ id: "reports", label: "Reports", icon: "📈" },
	{ id: "collateral", label: "Collateral", icon: "🏠" },
	{ id: "team", label: "Team", icon: "👥" },
];

lms_manager._tabNav = function () {
	return lms_portal.tabNav(lms_manager._tabs, lms_manager._currentTab);
};

lms_manager._bindTabs = function () {
	lms_portal.bindTabs({
		root: document.getElementById("lms-manager-root"),
		tabs: lms_manager._tabs,
		onTab: function (tabId) {
			lms_manager._currentTab = tabId;
			lms_manager._showTab(tabId);
		},
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
	var html = '<div class="lms-stack">';
	var k = dash.kpis || {};
	var apps = queue.applications || [];
	var buckets = dash.risk_buckets || {};

	/* ---- 1) KPI strip FIRST (at-a-glance overview) ---- */
	html += lms_portal.kpiStrip([
		{ label: "Approval queue", value: k.approval_queue_count || 0, tone: (k.approval_queue_count || 0) ? "warning" : "" },
		{ label: "Active loans", value: k.active_loans || 0 },
		{ label: "PAR 30+ outstanding", value: format_currency(k.par30_outstanding || 0), tone: (k.par30_outstanding || 0) ? "danger" : "" },
		{ label: "Portfolio outstanding", value: format_currency(k.portfolio_outstanding || 0) },
	]);

	/* ---- 2) Approval queue (primary work) ---- */
	if (!apps.length) {
		html += lms_portal.emptyPanel("✓", "All caught up", "No applications pending approval.");
	} else {
		html += '<div class="lms-panel lms-portal-board">';
		html += '<div class="lms-section-header"><h3>Approval Queue</h3>';
		html += '<span class="lms-muted">' + apps.length + " pending</span></div>";
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
		html += "<thead><tr><th>Applicant</th><th>Product</th><th>Amount</th><th>Tenure</th><th>Rate</th><th>KYC</th><th>Officer</th><th>Actions</th></tr></thead><tbody>";
		apps.forEach(function (app) {
			var borrower = app.customer_name || app.applicant || "—";
			// KYC badge for the row — risk-tiered visual.
			var kyc = (app.kyc_status || "Pending").toLowerCase();
			var kycBadge = '<span class="lms-badge lms-badge--muted">Pending</span>';
			if (kyc === "approved" || kyc === "verified" || kyc === "complete") {
				kycBadge = '<span class="lms-badge lms-badge--success">KYC OK</span>';
			} else if (kyc === "rejected" || kyc === "expired") {
				kycBadge = '<span class="lms-badge lms-badge--danger">' + lms_portal.escape(app.kyc_status) + '</span>';
			} else {
				kycBadge = '<span class="lms-badge lms-badge--warning">KYC ' + lms_portal.escape(app.kyc_status || "Pending") + '</span>';
			}
			// Existing exposure badge — warn if a new loan will compound the book.
			var exposure = app.exposure || 0;
			var amount = app.loan_amount || 0;
			var totalIfApproved = exposure + amount;
			var exposureTone = "";
			var exposureLabel = format_currency(exposure);
			if (exposure > 0 && amount > 0 && totalIfApproved / amount > 3) {
				exposureTone = " lms-text--warning";
			}
			// Worst-DPD hint.
			var dpd = app.worst_dpd || 0;
			var dpdBadge = "";
			if (dpd > 0) {
				var dpdTone = dpd > 60 ? "danger" : (dpd > 30 ? "warning" : "muted");
				dpdBadge = ' <span class="lms-badge lms-badge--' + dpdTone + '">DPD ' + dpd + '</span>';
			}
			html += "<tr>";
			html += "<td><strong>" + lms_portal.escape(borrower) + "</strong>" + dpdBadge + "</td>";
			html += "<td>" + lms_portal.escape(app.product_name || app.loan_product || "—") + "</td>";
			html += "<td>" + format_currency(amount) + (exposure > 0 ? '<br><span class="lms-muted' + exposureTone + '" style="font-size:0.7rem;">existing: ' + exposureLabel + "</span>" : "") + "</td>";
			html += "<td>" + (app.repayment_periods || "—") + " mo</td>";
			html += "<td>" + (app.rate_of_interest || 0) + "%</td>";
			html += "<td>" + kycBadge + "</td>";
			html += "<td>" + lms_portal.escape(app.officer_name || "Unassigned") + "</td>";
			html += '<td><div class="lms-data-table__actions">';
			html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-view-app-btn" data-app="' + lms_portal.escape(app.name) + '">Review</button>';
			html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-reject-btn" data-app="' + lms_portal.escape(app.name) + '">Reject</button>';
			html += "</div></td></tr>";
		});
		html += "</tbody></table></div></div>";
	}

	/* ---- 3) Charts below ---- */
	html += '<div class="lms-grid-2">';
	html += '<div class="lms-panel lms-portal-board">';
	html += '<div class="lms-section-header"><h3>Risk Mix</h3></div>';
	html += '<div class="lms-chart-wrap"><canvas id="lms-risk-chart" role="img" aria-label="Risk Mix chart"></canvas></div>';
	html += "</div>";
	html += '<div class="lms-panel lms-portal-board">';
	html += '<div class="lms-section-header"><h3>Team Performance</h3></div>';
	html += '<div class="lms-chart-wrap"><canvas id="lms-team-chart" role="img" aria-label="Team Performance chart"></canvas></div>';
	html += "</div>";
	html += "</div>";

	html += "</div>"; // .lms-stack

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
	if (typeof Chart === "undefined") {
		var riskEl = document.getElementById("lms-risk-chart");
		var teamEl = document.getElementById("lms-team-chart");
		if (riskEl && riskEl.parentElement) {
			riskEl.parentElement.innerHTML = lms_portal.simpleBars
				? lms_portal.simpleBars(riskData)
				: '<p class="lms-muted">Chart library unavailable — values: ' +
					riskData.map(function (d) { return d.label + " " + d.value; }).join(", ") + "</p>";
		}
		var officersFb = (dash.team && dash.team.officers) || [];
		var teamFb = officersFb.map(function (o) {
			return { label: o.officer_name || o.officer || "—", value: o.loan_count || 0 };
		});
		if (teamEl && teamEl.parentElement) {
			teamEl.parentElement.innerHTML = (lms_portal.simpleBars && teamFb.length)
				? lms_portal.simpleBars(teamFb)
				: '<p class="lms-muted">No team performance data yet.</p>';
		}
	} else {
		lms_manager._charts.risk = lms_charts.donut("lms-risk-chart", riskData, { title: "Risk Mix" });

		var officers = (dash.team && dash.team.officers) || [];
		var teamData = officers.map(function (o) {
			return { label: o.officer_name || o.officer || "—", value: o.loan_count || 0 };
		});
		lms_manager._charts.team = lms_charts.bars("lms-team-chart", teamData, { title: "Team Performance" });
	}

	/* ---- Bind approve/reject buttons ---- */
	root.querySelectorAll(".lms-view-app-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_manager._viewApplication(btn.getAttribute("data-app"));
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

lms_manager._viewApplication = function (appName) {
	// Pre-flight: fetch the full application detail (borrower + KYC + risk
	// + checklist) and render in a "View" modal. Approve / Reject are
	// available from the modal footer so the manager can act on what they
	// just reviewed without losing context.
	lms_portal.modal({
		title: "Application " + (appName || ""),
		body: '<div class="lms-muted" style="text-align:center;padding:2rem;">Loading application detail\u2026</div>',
		confirmText: "Approve",
		confirmVariant: "success",
		cancelText: "Close",
		size: "lg",
		showReject: true,
		onConfirm: function (overlay) {
			// R3 expert-board fix: the View modal IS the approval modal.
			// We add a Note textarea inline so the manager can record the
			// justification for the audit trail before clicking Approve.
			// No second modal stacks on top of the first — the body has
			// the note input already, we just need to read it on click.
			var id = overlay.getAttribute("data-app-name");
			if (!id) return;
			var noteEl = overlay.querySelector("#lms-approve-note");
			var note = noteEl ? noteEl.value.trim() : "";
			var borrowerEl = overlay.querySelector("[data-detail-borrower]");
			var amountEl = overlay.querySelector("[data-detail-amount]");
			// Lock the buttons to prevent double-clicks while the API call
			// is in flight; the modal will close on success.
			var btns = overlay.querySelectorAll("button");
			btns.forEach(function (b) { b.disabled = true; });
			lms_portal.safeCall({
				method: "lms_saas.api.manager.approve_application",
				args: { application_name: id, note: note },
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.closeModal(overlay);
					if (res.status === "approved" && res.loan) {
						lms_portal.toast("Approved — Loan " + res.loan + " created.", "success");
					} else {
						lms_portal.toast((res && res.message) || "Approval did not complete.", "danger");
					}
					lms_manager._refreshDashboardData();
				},
				error: function (err) {
					btns.forEach(function (b) { b.disabled = false; });
					var msg = (err && (err.message || err._server_message)) || "Approval failed.";
					var tmp = document.createElement("div");
					tmp.innerHTML = msg;
					msg = (tmp.textContent || tmp.innerText || msg).trim();
					lms_portal.toast(msg, "danger", 8000);
				},
			});
		},
		onReject: function (overlay) {
			var id = overlay.getAttribute("data-app-name");
			if (id) lms_manager._reject(id);
		},
		onShown: function (overlay) {
			overlay.setAttribute("data-app-name", appName);
			// Fetch the detail.
			lms_portal.safeCall({
				method: "lms_saas.api.manager.get_application_detail",
				args: { application_name: appName },
				callback: function (r) {
					var d = (r && r.message) || {};
					var body = overlay.querySelector(".lms-modal__body");
					if (body) body.innerHTML = lms_manager._renderApplicationDetail(d);
					// Disable Approve if can_approve is false.
					var confirmBtn = overlay.querySelector(".lms-modal__confirm");
					if (confirmBtn) {
						confirmBtn.disabled = !d.can_approve;
						confirmBtn.title = d.can_approve
							? "Submit and create Loan record"
							: "Cannot approve: see checklist below";
					}
				},
				error: function (err) {
					var body = overlay.querySelector(".lms-modal__body");
					if (body) {
						body.innerHTML = '<div class="lms-callout lms-callout--danger">' +
							lms_portal.escape((err && (err.message || err._server_message)) || "Could not load application.") +
							"</div>";
					}
				},
			});
		},
	});
};


lms_manager._renderApplicationDetail = function (d) {
	var a = d.application || {};
	var c = d.customer || {};
	var k = d.kyc || {};
	var r = d.risk || {};
	var checklist = d.checklist || [];

	var riskTier = "muted";
	if ((r.worst_dpd || 0) > 60) riskTier = "danger";
	else if ((r.worst_dpd || 0) > 30) riskTier = "warning";
	else if ((r.existing_exposure || 0) > 0) riskTier = "muted";

	var kycTone = "muted";
	if ((k.status || "").toLowerCase().match(/approved|verified|complete/)) kycTone = "success";
	else if ((k.status || "").toLowerCase().match(/rejected|expired/)) kycTone = "danger";
	else kycTone = "warning";

	var amlTone = "muted";
	if ((k.aml_status || "").toLowerCase().match(/clear|approved/)) amlTone = "success";
	else if ((k.aml_status || "").toLowerCase().match(/rejected/)) amlTone = "danger";
	else amlTone = "warning";

	var html = "";
	html += '<div class="lms-grid-2" style="gap:1rem;">';

	// LEFT: Applicant + terms
	html += '<div>';
	html += '<div class="lms-panel" style="padding:1rem;">';
	html += '<h4 style="margin:0 0 .5rem 0;">Applicant</h4>';
	html += '<div style="display:flex;flex-direction:column;gap:.25rem;font-size:.9rem;">';
	html += '<div><strong>' + lms_portal.escape(c.customer_name || a.applicant || "") + '</strong></div>';
	html += '<div class="lms-muted">' + lms_portal.escape(c.email_id || "no email on file") + '</div>';
	html += '<div class="lms-muted">' + lms_portal.escape(c.mobile_no || "no mobile on file") + '</div>';
	if (c.national_id) html += '<div class="lms-muted">National ID: ' + lms_portal.escape(c.national_id) + '</div>';
	if (c.branch) html += '<div class="lms-muted">Branch: ' + lms_portal.escape(c.branch) + '</div>';
	html += '</div>';
	html += '</div>';

	html += '<div class="lms-panel" style="padding:1rem;margin-top:.75rem;">';
	html += '<h4 style="margin:0 0 .5rem 0;">Requested terms</h4>';
	html += '<div class="lms-summary">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Amount</div><div class="lms-summary-value" data-detail-amount data-detail-borrower="' + lms_portal.escape(c.customer_name || "") + '">' + format_currency(a.loan_amount || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Tenure</div><div class="lms-summary-value">' + (a.repayment_periods || 0) + " mo</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Rate</div><div class="lms-summary-value">' + (a.rate_of_interest || 0) + "%</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Product</div><div class="lms-summary-value" style="font-size:.9rem;">' + lms_portal.escape(a.loan_product_name || a.loan_product || "\u2014") + '</div></div>';
	html += '</div>';
	html += '<div style="margin-top:.5rem;font-size:.85rem;color:var(--lms-text-muted);">';
	html += "Officer: <strong>" + lms_portal.escape(a.officer_name || a.custom_loan_officer || "Unassigned") + "</strong>";
	html += " &middot; Branch: " + lms_portal.escape(a.custom_lms_branch || "\u2014");
	html += '</div>';
	if (window.__lms_enforce_four_eyes) {
		html += '<div class="lms-four-eyes-note" style="margin-top:.75rem;padding:.6rem .75rem;border-radius:8px;background:color-mix(in oklab, var(--lms-warning,#f59e0b) 12%, transparent);font-size:.8rem;">';
		html += "<strong>4-eyes on:</strong> Approving this application records you as the approver. A different authorised user must disburse the loan.";
		html += "</div>";
	}
	html += '</div>';
	html += '</div>';

	// RIGHT: KYC + risk
	html += '<div>';
	html += '<div class="lms-panel" style="padding:1rem;">';
	html += '<h4 style="margin:0 0 .5rem 0;">KYC &amp; Compliance</h4>';
	html += '<div style="display:flex;flex-direction:column;gap:.35rem;font-size:.85rem;">';
	html += '<div>KYC: <span class="lms-badge lms-badge--' + kycTone + '">' + lms_portal.escape(k.status || "Pending") + '</span></div>';
	html += '<div>AML: <span class="lms-badge lms-badge--' + amlTone + '">' + lms_portal.escape(k.aml_status || "Pending") + '</span></div>';
	html += '<div>Consent: ' + (k.consent_given ? '<span class="lms-badge lms-badge--success">Signed</span>' : '<span class="lms-badge lms-badge--danger">Missing</span>') + '</div>';
	if (k.credit_score != null) html += '<div>Credit score: <strong>' + k.credit_score + '</strong></div>';
	html += '</div>';
	html += '</div>';

	html += '<div class="lms-panel" style="padding:1rem;margin-top:.75rem;">';
	html += '<h4 style="margin:0 0 .5rem 0;">Risk signals</h4>';
	html += '<div style="display:flex;flex-direction:column;gap:.35rem;font-size:.85rem;">';
	html += '<div>Existing exposure: <strong>' + format_currency(r.existing_exposure || 0) + '</strong></div>';
	html += '<div>Active loans: <strong>' + (r.active_loan_count || 0) + '</strong></div>';
	html += '<div>Worst DPD: <span class="lms-badge lms-badge--' + riskTier + '">' + (r.worst_dpd || 0) + ' days</span></div>';
	html += '</div>';
	if (r.active_loans && r.active_loans.length) {
		html += '<details style="margin-top:.5rem;"><summary style="cursor:pointer;font-size:.8rem;">View ' + r.active_loans.length + ' active loan(s)</summary>';
		html += '<ul style="margin:.5rem 0 0 1rem;padding:0;font-size:.8rem;">';
		(r.active_loans || []).forEach(function (l) {
			html += "<li>" + lms_portal.escape(l.name) + " &middot; " + format_currency(l.loan_amount || 0) + " &middot; " + lms_portal.escape(l.status || "") + " &middot; DPD " + (l.custom_days_past_due || 0) + "</li>";
		});
		html += "</ul></details>";
	}
	html += '</div>';
	html += '</div>';

	html += '</div>';  // .lms-grid-2

	// CHECKLIST (full width below)
	html += '<div class="lms-panel" style="padding:1rem;margin-top:1rem;">';
	html += '<h4 style="margin:0 0 .5rem 0;">Pre-approval checklist</h4>';
	html += '<div style="display:flex;flex-direction:column;gap:.35rem;">';
	checklist.forEach(function (item) {
		var ok = !!item.ok;
		var mark = ok
			? '<span style="color:var(--lms-success);">\u2713</span>'
			: '<span style="color:var(--lms-danger);">\u2717</span>';
		html += '<div style="display:flex;align-items:center;gap:.5rem;font-size:.9rem;">';
		html += '<span style="font-size:1.1rem;width:1.1rem;">' + mark + "</span>";
		html += '<div style="flex:1;display:flex;justify-content:space-between;gap:1rem;">';
		html += '<span style="font-weight:500;">' + lms_portal.escape(item.label) + "</span>";
		html += '<span class="lms-muted">' + lms_portal.escape(item.message || "") + "</span>";
		html += "</div></div>";
	});
	html += '</div></div>';

	// R3 expert-board: single-modal approval flow. The note textarea lives
	// INSIDE the View modal so the manager can record the audit-trail
	// justification in-place, then click Approve — no stacked confirmation.
	html += '<div class="lms-panel" style="padding:1rem;margin-top:1rem;">';
	html += '<h4 style="margin:0 0 .5rem 0;">Approval note</h4>';
	html += '<p class="lms-muted" style="margin:0 0 .5rem 0;font-size:.8rem;">Optional — logged in the LMS Audit Event and on the application comment.</p>';
	html += '<textarea id="lms-approve-note" class="lms-input" rows="3" maxlength="500" placeholder="e.g. Strong repayment history; KYC renewed 2026-07-10."></textarea>';
	html += '</div>';

	return html;
};

lms_manager._approve = function (appName, borrowerName, loanAmount, opts) {
	opts = opts || {};
	var prefillNote = opts.note || "";
	var origApprove = appName;
	var borrower = borrowerName || "—";
	var amountLabel = format_currency(loanAmount || 0);
	lms_portal.modal({
		title: "Approve Application",
		body:
			'<p class="lms-muted">Confirm approval. A loan will be created for disbursement.</p>' +
			'<div class="lms-summary" style="margin:1rem 0;">' +
			'<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Borrower</div><div class="lms-summary-value">' + lms_portal.escape(borrower) + "</div></div>" +
			'<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Amount</div><div class="lms-summary-value">' + amountLabel + "</div></div>" +
			'<div class="lms-summary-card"><div class="lms-summary-label">Application #</div><div class="lms-summary-value">' + lms_portal.escape(appName || "") + "</div></div>" +
			"</div>" +
			'<div class="lms-form" style="margin-top:.75rem;">' +
			'<div class="lms-field"><label>Approval note <span class="lms-muted">(optional)</span></label>' +
			'<textarea id="lms-approve-note-standalone" class="lms-input" rows="3" maxlength="500" placeholder="Logged in the LMS Audit Event.">' + lms_portal.escape(prefillNote) + '</textarea>' +
			"</div></div>",
		confirmText: "Approve",
		confirmVariant: "success",
		onConfirm: function (overlay) {
			var noteEl = overlay.querySelector("#lms-approve-note-standalone");
			var note = noteEl ? noteEl.value.trim() : "";
			var btns = overlay.querySelectorAll("button");
			btns.forEach(function (b) { b.disabled = true; });
			lms_portal.safeCall({
				method: "lms_saas.api.manager.approve_application",
				args: { application_name: appName, note: note },
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.closeModal(overlay);
					if (res.status === "approved" && res.loan) {
						lms_portal.toast("Approved \u2014 Loan " + res.loan + " created.", "success");
						lms_manager._refreshDashboardData();
					} else {
						lms_portal.toast((res && res.message) || "Approval did not complete.", "danger");
					}
				},
				error: function (err) {
					btns.forEach(function (b) { b.disabled = false; });
					var msg = (err && (err.message || err._server_message)) || "Approval failed.";
					var tmp = document.createElement("div");
					tmp.innerHTML = msg;
					msg = (tmp.textContent || tmp.innerText || msg).trim();
					lms_portal.toast(msg, "danger", 8000);
				},
			});
		},
	});
};

lms_manager._reject = function (appName) {
	// Round-1 expert-board fix: add a standard reason-code dropdown so
	// rejection-reason reports are structured (not free-text soup), with
	// a free-text field for the "Other" case. The reason code is logged
	// as a separate field; the free text is the human note.
	var reasonOptions = [
		{ value: "kyc_failed", label: "KYC failed / incomplete" },
		{ value: "aml_hit", label: "AML / sanctions hit" },
		{ value: "insufficient_income", label: "Insufficient income" },
		{ value: "exceeds_limit", label: "Exceeds credit limit" },
		{ value: "poor_repayment_history", label: "Poor repayment history" },
		{ value: "insufficient_collateral", label: "Insufficient collateral" },
		{ value: "credit_policy_breach", label: "Credit policy breach" },
		{ value: "duplicate_application", label: "Duplicate application" },
		{ value: "other", label: "Other (specify below)" },
	];
	var optionsHtml = reasonOptions
		.map(function (o) {
			return '<option value="' + lms_portal.escape(o.value) + '">' + lms_portal.escape(o.label) + "</option>";
		})
		.join("");
	var body =
		'<div class="lms-form">' +
		'<div class="lms-field"><label>Reason code <span class="lms-muted">(required)</span></label>' +
		'<select id="lms-reject-code" class="lms-input">' + optionsHtml + "</select>" +
		'<div class="lms-field__hint">Standard codes let us report on rejection reasons by category.</div></div>' +
		'<div class="lms-field" style="margin-top:.75rem;"><label>Detailed reason <span class="lms-muted">(required)</span></label>' +
		'<textarea id="lms-reject-reason" class="lms-input" rows="3" placeholder="e.g. KYC document expired; consent not signed" autocomplete="off" maxlength="500"></textarea>' +
		'<div class="lms-field__hint">Logged on the application for the audit trail.</div></div>' +
		"</div>";
	lms_portal.modal({
		title: "Reject Application",
		body: body,
		confirmText: "Reject",
		confirmVariant: "danger",
		size: "lg",
		onConfirm: function (overlay) {
			var codeSel = overlay.querySelector("#lms-reject-code");
			var reasonInput = overlay.querySelector("#lms-reject-reason");
			var reason = reasonInput ? reasonInput.value.trim() : "";
			var code = codeSel ? codeSel.value : "";
			if (!reason) {
				lms_portal.toast("Please provide a detailed rejection reason.", "warning");
				if (reasonInput) reasonInput.focus();
				return false;
			}
			lms_portal.safeCall({
				method: "lms_saas.api.manager.reject_application",
				args: { application_name: appName, reason: reason, reason_code: code },
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
					var tmp = document.createElement("div");
					tmp.innerHTML = msg;
					msg = (tmp.textContent || tmp.innerText || msg).trim();
					lms_portal.toast(msg, "danger", 8000);
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
		el.innerHTML = '<div class="lms-empty">' + lms_icons.empty("👤") + '<h3>No borrowers found</h3><p>Try a different search or add a new borrower.</p></div>';
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

	// Action buttons.
	html += '<div class="lms-data-table__actions" style="margin-bottom:1rem;gap:.5rem;">';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-borrower-edit">Edit Details</button>';
	if (b.disabled) {
		html += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm" id="lms-borrower-toggle">Enable</button>';
	} else {
		html += '<button type="button" class="lms-btn lms-btn--danger lms-btn--sm" id="lms-borrower-toggle">Disable</button>';
	}
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
		onShown: function (overlay) {
			// Wire up Edit button.
			var editBtn = overlay.querySelector("#lms-borrower-edit");
			if (editBtn) {
				editBtn.addEventListener("click", function () {
					lms_manager._showEditBorrowerModal(b, overlay);
				});
			}
			// Wire up Disable/Enable toggle.
			var toggleBtn = overlay.querySelector("#lms-borrower-toggle");
			if (toggleBtn) {
				toggleBtn.addEventListener("click", function () {
					var newDisabled = b.disabled ? 0 : 1;
					var action = b.disabled ? "Enable" : "Disable";
					lms_portal.safeCall({
						method: "lms_saas.api.manager.update_borrower",
						args: { customer_name: b.name, disabled: newDisabled },
						callback: function (r) {
							var res = (r && r.message) || {};
							if (res.status === "updated") {
								lms_portal.toast("Borrower " + action.toLowerCase() + "d.", "success");
								b.disabled = newDisabled;
								// Update the button label.
								if (newDisabled) {
									toggleBtn.textContent = "Enable";
									toggleBtn.classList.remove("lms-btn--danger");
									toggleBtn.classList.add("lms-btn--success");
								} else {
									toggleBtn.textContent = "Disable";
									toggleBtn.classList.remove("lms-btn--success");
									toggleBtn.classList.add("lms-btn--danger");
								}
							} else {
								lms_portal.toast("Could not update borrower.", "danger");
							}
						},
						error: function (err) {
							var msg = (err && (err.message || err._server_message)) || "Update failed.";
							var tmp = document.createElement("div");
							tmp.innerHTML = msg;
							lms_portal.toast((tmp.textContent || tmp.innerText || msg).trim(), "danger", 8000);
						},
					});
				});
			}
		},
	});
};

lms_manager._showEditBorrowerModal = function (b, parentOverlay) {
	var body =
		'<div class="lms-form">' +
		'<div class="lms-field"><label>Customer name</label>' +
		'<input type="text" id="lms-edit-customer-name" class="lms-input" value="' + lms_portal.escape(b.customer_name || "") + '">' +
		"</div>" +
		'<div class="lms-field" style="margin-top:.75rem;"><label>Email</label>' +
		'<input type="email" id="lms-edit-email" class="lms-input" value="' + lms_portal.escape(b.email_id || "") + '">' +
		"</div>" +
		'<div class="lms-field" style="margin-top:.75rem;"><label>Mobile</label>' +
		'<input type="text" id="lms-edit-mobile" class="lms-input" value="' + lms_portal.escape(b.mobile_no || "") + '">' +
		"</div>" +
		'<div class="lms-field" style="margin-top:.75rem;"><label>National ID</label>' +
		'<input type="text" id="lms-edit-national-id" class="lms-input" value="' + lms_portal.escape(b.custom_national_id_number || "") + '">' +
		"</div>" +
		"</div>";
	lms_portal.modal({
		title: "Edit Borrower — " + (b.customer_name || ""),
		body: body,
		confirmText: "Save",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var nameEl = overlay.querySelector("#lms-edit-customer-name");
			var emailEl = overlay.querySelector("#lms-edit-email");
			var mobileEl = overlay.querySelector("#lms-edit-mobile");
			var idEl = overlay.querySelector("#lms-edit-national-id");
			var btns = overlay.querySelectorAll("button");
			btns.forEach(function (b) { b.disabled = true; });
			lms_portal.safeCall({
				method: "lms_saas.api.manager.update_borrower",
				args: {
					customer_name: b.name,
					customer_name_new: nameEl ? nameEl.value : "",
					email_id: emailEl ? emailEl.value : "",
					mobile_no: mobileEl ? mobileEl.value : "",
					national_id: idEl ? idEl.value : "",
				},
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.closeModal(overlay);
					if (res.status === "updated") {
						lms_portal.toast("Borrower details updated.", "success");
						// Refresh the borrowers tab to reflect changes.
						var content = document.getElementById("lms-manager-tab-content");
						if (content) lms_manager._loadBorrowers(content);
					} else {
						lms_portal.toast("Update failed.", "danger");
					}
				},
				error: function (err) {
					btns.forEach(function (b) { b.disabled = false; });
					var msg = (err && (err.message || err._server_message)) || "Update failed.";
					var tmp = document.createElement("div");
					tmp.innerHTML = msg;
					lms_portal.toast((tmp.textContent || tmp.innerText || msg).trim(), "danger", 8000);
				},
			});
		},
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
		el.innerHTML = '<div class="lms-empty">' + lms_icons.empty("💰") + '<h3>No loans found</h3><p>No loans match the current filter.</p></div>';
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
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Officer</div><div class="lms-summary-value" id="lms-loan-officer-name">' + lms_portal.escape(l.custom_loan_officer || l.officer_name || "—") + '</div></div>';
	html += '</div>';

	// Action buttons — context-aware based on loan status.
	var canDisburse = (l.status === "Sanctioned" || l.status === "Draft" || (l.docstatus === 1 && l.status === "Sanctioned"));
	var canWriteOff = (l.status === "Disbursed" || l.status === "Active" || l.status === "Partially Disbursed");
	html += '<div class="lms-data-table__actions" style="margin-bottom:1rem;gap:.5rem;">';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-loan-assign-officer">Assign Officer</button>';
	if (canDisburse) {
		html += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm" id="lms-loan-disburse">Disburse</button>';
	}
	if (canWriteOff) {
		html += '<button type="button" class="lms-btn lms-btn--danger lms-btn--sm" id="lms-loan-writeoff">Write Off</button>';
	}
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
		onShown: function (overlay) {
			// Wire up the Assign Officer button.
			var assignBtn = overlay.querySelector("#lms-loan-assign-officer");
			if (assignBtn) {
				assignBtn.addEventListener("click", function () {
					lms_manager._showAssignOfficerModal(l.name, overlay);
				});
			}
			// Wire up the Disburse button.
			var disburseBtn = overlay.querySelector("#lms-loan-disburse");
			if (disburseBtn) {
				disburseBtn.addEventListener("click", function () {
					lms_manager._showDisburseModal(l.name, l.loan_amount, overlay);
				});
			}
			// Wire up the Write Off button.
			var writeoffBtn = overlay.querySelector("#lms-loan-writeoff");
			if (writeoffBtn) {
				writeoffBtn.addEventListener("click", function () {
					lms_manager._showWriteOffModal(l.name, l.outstanding, overlay);
				});
			}
		},
	});
};

// ---------------------------------------------------------------------------
// Loan action modals (assign officer, disburse, write off)
// ---------------------------------------------------------------------------

lms_manager._showAssignOfficerModal = function (loanName, parentOverlay) {
	// Fetch the list of available officers in the branch.
	lms_portal.safeCall({
		method: "lms_saas.api.manager.get_branch_officers",
		callback: function (r) {
			var officers = (r && r.message && r.message.officers) || [];
			var options = officers.map(function (o) {
				return '<option value="' + lms_portal.escape(o.name) + '">' +
					lms_portal.escape(o.employee_name) +
					" (" + (o.loan_count || 0) + " loans)" +
					"</option>";
			}).join("");
			if (!options) {
				lms_portal.toast("No active loan officers found in your branch.", "warning");
				return;
			}
			var body =
				'<div class="lms-form">' +
				'<div class="lms-field"><label>Assign to officer</label>' +
				'<select id="lms-assign-officer-select" class="lms-input">' + options + "</select>" +
				'<div class="lms-field__hint">Only active officers in your branch are listed.</div></div>' +
				"</div>";
			lms_portal.modal({
				title: "Assign Loan Officer — " + loanName,
				body: body,
				confirmText: "Assign",
				confirmVariant: "primary",
				onConfirm: function (overlay) {
					var sel = overlay.querySelector("#lms-assign-officer-select");
					var officer = sel ? sel.value : "";
					if (!officer) {
						lms_portal.toast("Please select an officer.", "warning");
						return false;
					}
					var btns = overlay.querySelectorAll("button");
					btns.forEach(function (b) { b.disabled = true; });
					lms_portal.safeCall({
						method: "lms_saas.api.manager.assign_loan_officer",
						args: { loan_name: loanName, officer_employee: officer },
						callback: function (r) {
							var res = (r && r.message) || {};
							lms_portal.closeModal(overlay);
							if (res.status === "reassigned") {
								lms_portal.toast(res.message || "Officer assigned.", "success");
								// Update the officer name in the parent modal.
								var officerEl = parentOverlay.querySelector("#lms-loan-officer-name");
								if (officerEl) officerEl.textContent = res.new_officer || "—";
							} else {
								lms_portal.toast(res.message || "Assignment failed.", "danger");
							}
						},
						error: function (err) {
							btns.forEach(function (b) { b.disabled = false; });
							var msg = (err && (err.message || err._server_message)) || "Assignment failed.";
							var tmp = document.createElement("div");
							tmp.innerHTML = msg;
							lms_portal.toast((tmp.textContent || tmp.innerText || msg).trim(), "danger", 8000);
						},
					});
				},
			});
		},
		error: function () {
			lms_portal.toast("Could not load officers list.", "danger");
		},
	});
};

lms_manager._showDisburseModal = function (loanName, loanAmount, parentOverlay) {
	var body =
		'<div class="lms-form">' +
		'<p class="lms-muted">Disburse this loan. A Loan Disbursement will be created and submitted.</p>' +
		'<div class="lms-summary" style="margin:1rem 0;">' +
		'<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Loan Amount</div><div class="lms-summary-value">' + format_currency(loanAmount || 0) + '</div></div>' +
		"</div>" +
		'<div class="lms-field"><label>Disbursement amount <span class="lms-muted">(leave blank for full amount)</span></label>' +
		'<input type="number" id="lms-disburse-amount" class="lms-input" placeholder="' + (loanAmount || 0) + '" step="0.01" min="0" max="' + (loanAmount || 0) + '">' +
		'<div class="lms-field__hint">Partial disbursements must not exceed the sanctioned amount.</div></div>' +
		"</div>";
	lms_portal.modal({
		title: "Disburse Loan — " + loanName,
		body: body,
		confirmText: "Disburse",
		confirmVariant: "success",
		onConfirm: function (overlay) {
			var amtInput = overlay.querySelector("#lms-disburse-amount");
			var amt = amtInput ? parseFloat(amtInput.value) : null;
			var btns = overlay.querySelectorAll("button");
			btns.forEach(function (b) { b.disabled = true; });
			lms_portal.safeCall({
				method: "lms_saas.api.manager.disburse_loan",
				args: { loan_name: loanName, disbursed_amount: amt || "" },
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.closeModal(overlay);
					if (res.status === "disbursed") {
						lms_portal.toast(res.message || "Loan disbursed.", "success");
						lms_manager._refreshDashboardData();
					} else {
						lms_portal.toast(res.message || "Disbursement failed.", "danger");
					}
				},
				error: function (err) {
					btns.forEach(function (b) { b.disabled = false; });
					var msg = (err && (err.message || err._server_message)) || "Disbursement failed.";
					var tmp = document.createElement("div");
					tmp.innerHTML = msg;
					lms_portal.toast((tmp.textContent || tmp.innerText || msg).trim(), "danger", 8000);
				},
			});
		},
	});
};

lms_manager._showWriteOffModal = function (loanName, outstanding, parentOverlay) {
	var body =
		'<div class="lms-form">' +
		'<p class="lms-muted" style="color:var(--lms-danger);">Write off this loan. This action is irreversible and audited.</p>' +
		'<div class="lms-summary" style="margin:1rem 0;">' +
		'<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Outstanding</div><div class="lms-summary-value">' + format_currency(outstanding || 0) + '</div></div>' +
		"</div>" +
		'<div class="lms-field"><label>Write-off amount <span class="lms-muted">(leave blank for full outstanding)</span></label>' +
		'<input type="number" id="lms-writeoff-amount" class="lms-input" placeholder="' + (outstanding || 0) + '" step="0.01" min="0">' +
		"</div>" +
		'<div class="lms-field" style="margin-top:.75rem;"><label>Reason <span class="lms-muted">(required for audit trail)</span></label>' +
		'<textarea id="lms-writeoff-reason" class="lms-input" rows="3" maxlength="500" placeholder="e.g. Borrower deceased, no recovery possible; NPA provisioned per IFRS9."></textarea>' +
		"</div>" +
		"</div>";
	lms_portal.modal({
		title: "Write Off Loan — " + loanName,
		body: body,
		confirmText: "Write Off",
		confirmVariant: "danger",
		onConfirm: function (overlay) {
			var amtInput = overlay.querySelector("#lms-writeoff-amount");
			var reasonInput = overlay.querySelector("#lms-writeoff-reason");
			var amt = amtInput ? parseFloat(amtInput.value) : null;
			var reason = reasonInput ? reasonInput.value.trim() : "";
			if (!reason) {
				lms_portal.toast("Write-off reason is required.", "warning");
				if (reasonInput) reasonInput.focus();
				return false;
			}
			var btns = overlay.querySelectorAll("button");
			btns.forEach(function (b) { b.disabled = true; });
			lms_portal.safeCall({
				method: "lms_saas.api.manager.write_off_loan",
				args: { loan_name: loanName, write_off_amount: amt || "", reason: reason },
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.closeModal(overlay);
					if (res.status === "written_off") {
						lms_portal.toast(res.message || "Loan written off.", "warning");
						lms_manager._refreshDashboardData();
					} else {
						lms_portal.toast(res.message || "Write-off failed.", "danger");
					}
				},
				error: function (err) {
					btns.forEach(function (b) { b.disabled = false; });
					var msg = (err && (err.message || err._server_message)) || "Write-off failed.";
					var tmp = document.createElement("div");
					tmp.innerHTML = msg;
					lms_portal.toast((tmp.textContent || tmp.innerText || msg).trim(), "danger", 8000);
				},
			});
		},
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
		html += '<div class="lms-empty">' + lms_icons.empty("💸") + '<h3>No disbursements in this period</h3><p>Once the manager / officer disburses a loan it will appear here.</p></div>';
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
		html += '<div class="lms-empty">' + lms_icons.empty("📭") + '<h3>No collections in this period</h3><p>Once repayments are recorded they will appear here.</p></div>';
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
		"<thead><tr><th>Name</th><th>Designation</th><th>Persona</th><th>Loans</th><th>PAR 30+</th><th>PAR Ratio</th><th>User</th><th>Actions</th></tr></thead><tbody>";
	staff.forEach(function (s) {
		body += "<tr>";
		body += "<td><strong>" + lms_portal.escape(s.employee_name || s.name) + "</strong></td>";
		body += "<td>" + lms_portal.escape(s.designation || "—") + "</td>";
		body += '<td><span class="lms-badge">' + lms_portal.escape(s.persona || "—") + "</span></td>";
		body += "<td>" + (s.loan_count || 0) + "</td>";
		// PAR count with tone badge.
		var parCount = s.par_count || 0;
		var parTone = parCount > 0 ? "lms-badge--warning" : "lms-badge--success";
		body += '<td><span class="lms-badge ' + parTone + '">' + parCount + "</span></td>";
		// PAR ratio as percentage.
		var parRatio = s.par_ratio || 0;
		var ratioTone = parRatio > 0.15 ? "lms-text--danger" : (parRatio > 0.05 ? "lms-text--warning" : "");
		body += '<td><span class="' + ratioTone + '">' + (parRatio * 100).toFixed(1) + "%</span></td>";
		body += "<td>" + lms_portal.escape(s.user_id || "—") + "</td>";
		body += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-staff-view-loans" data-officer="' + lms_portal.escape(s.name) + '">View Loans</button></td>';
		body += "</tr>";
	});
	body += "</tbody></table></div>";
	html += lms_portal.panel({ title: "Branch Team", badge: staff.length + " members", body: body });
	html += lms_portal.pageEnd();
	el.innerHTML = html;

	// Wire up "View Loans" buttons — filter the Loans tab by this officer.
	el.querySelectorAll(".lms-staff-view-loans").forEach(function (btn) {
		btn.addEventListener("click", function () {
			// Switch to Loans tab and filter by officer.
			lms_manager._currentTab = "loans";
			lms_manager._showTab("loans");
			// TODO: add officer filter to the loans tab.
		});
	});
};