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

	root.innerHTML = lms_manager._pageHeader() + lms_manager._tabNav() + '<div id="lms-manager-tab-content"></div>';
	lms_manager._bindTabs();
	lms_manager._showTab(lms_manager._currentTab);
};

lms_manager._pageHeader = function () {
	return (
		'<div class="lms-quick-actions">' +
		'<button type="button" class="lms-btn lms-btn--primary lms-quick-action" id="lms-manager-new-application">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M12 18v-6"/><path d="M9 15h6"/></svg>' +
		'New Application' +
		'</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-quick-action" id="lms-manager-add-borrower">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>' +
		'Add Borrower' +
		'</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-quick-action" id="lms-manager-approval-queue-top">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>' +
		'Approval Queue' +
		'</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-quick-action" id="lms-manager-view-loans">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>' +
		'View Loans' +
		'</button>' +
		'</div>'
	);
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
		var active = lms_manager._currentTab === t.id ? " lms-tab--active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
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
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("lms-tab--active");
			});
			btn.classList.add("lms-tab--active");
			lms_manager._showTab(lms_manager._currentTab);
		});
	});

	var approvalBtn = root.querySelector("#lms-manager-approval-queue-top");
	if (approvalBtn) {
		approvalBtn.addEventListener("click", function () {
			lms_manager._currentTab = "dashboard";
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.toggle("lms-tab--active", b.getAttribute("data-tab") === "dashboard");
			});
			lms_manager._showTab("dashboard");
			setTimeout(function () {
				var queue = document.getElementById("lms-manager-approval-queue");
				if (queue) queue.scrollIntoView({ behavior: "smooth", block: "start" });
			}, 300);
		});
	}

	var newAppBtn = root.querySelector("#lms-manager-new-application");
	if (newAppBtn) {
		newAppBtn.addEventListener("click", function () {
			lms_manager._openApplicationModal();
		});
	}

	var addBorrowerBtn = root.querySelector("#lms-manager-add-borrower");
	if (addBorrowerBtn) {
		addBorrowerBtn.addEventListener("click", function () {
			lms_manager._openBorrowerModal();
		});
	}

	var viewLoansBtn = root.querySelector("#lms-manager-view-loans");
	if (viewLoansBtn) {
		viewLoansBtn.addEventListener("click", function () {
			lms_manager._currentTab = "loans";
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.toggle("lms-tab--active", b.getAttribute("data-tab") === "loans");
			});
			lms_manager._showTab("loans");
		});
	}
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

	frappe.call({
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

	frappe.call({
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

	/* ---- KPI stat cards ---- */
	var k = dash.kpis || {};
	html += '<section class="lms-grid-3" aria-label="Branch KPIs">';
	html += lms_manager._statCard("Portfolio Outstanding", format_currency(k.portfolio_outstanding || 0), "bank");
	html += lms_manager._statCard("Active Loans", k.active_loans || 0, "file");
	html += lms_manager._statCard("PAR 30+ Outstanding", format_currency(k.par30_outstanding || 0), "alert", "danger");
	html += lms_manager._statCard("NPA Count", k.npa_count || 0, "x-circle", "warning");
	html += lms_manager._statCard("Approval Queue", k.approval_queue_count || 0, "clock", k.approval_queue_count ? "warning" : "");
	html += lms_manager._statCard("Team Members", k.team_count || 0, "users");
	html += "</section>";

	/* ---- Charts row: risk donut + team bars ---- */
	html += '<div class="lms-grid-2">';

	/* Risk mix donut */
	var buckets = dash.risk_buckets || {};
	html += '<div class="lms-portal-board">';
	html += '<div class="lms-section-header"><h3>Risk Mix</h3></div>';
	html += '<div class="lms-chart-wrap"><canvas id="lms-risk-chart"></canvas></div>';
	html += "</div>";

	/* Team performance bars */
	html += '<div class="lms-portal-board">';
	html += '<div class="lms-section-header"><h3>Team Performance</h3></div>';
	html += '<div class="lms-chart-wrap"><canvas id="lms-team-chart"></canvas></div>';
	html += "</div>";

	html += "</div>";

	/* ---- Approval queue table ---- */
	html += '<div class="lms-panel lms-portal-board" id="lms-manager-approval-queue">';
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

	html += "</div>"; // .lms-stack

	root.innerHTML = html;

	/* ---- Render charts ---- */
	var riskData = [
		{ label: "Current", value: buckets.current || 0, color: lms_manager._resolveColor("var(--lms-success)") },
		{ label: "PAR 30+", value: buckets.par30 || 0, color: lms_manager._resolveColor("var(--lms-warning)") },
		{ label: "PAR 60+", value: buckets.par60 || 0, color: lms_manager._resolveColor("var(--lms-tone-orange)") },
		{ label: "PAR 90+", value: buckets.par90 || 0, color: lms_manager._resolveColor("var(--lms-danger)") },
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

lms_manager._resolveColor = function (cssVar) {
	if (!cssVar || cssVar.indexOf("var(") !== 0) return cssVar || "#2f4f46";
	var name = cssVar.replace(/var\(|\)/g, "").split(",")[0].trim();
	try {
		var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
		return v || "#2f4f46";
	} catch (e) {
		return "#2f4f46";
	}
};

lms_manager._statCard = function (label, value, icon, tone) {
	var iconSvg = lms_manager._icon(icon || "file");
	var toneClass = tone ? " lms-stat--" + tone : "";
	return (
		'<div class="lms-stat-card lms-stat lms-stat-card--row' + toneClass + '">' +
		'<div class="lms-stat-card__body"><div class="lms-stat-label">' + lms_portal.escape(label) + "</div>" +
		'<div class="lms-stat-value">' + value + "</div></div>" +
		'<span class="lms-stat-card__icon">' + iconSvg + "</span>" +
		"</div>"
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
			frappe.call({
				method: "lms_saas.api.manager.approve_application",
				args: { application_name: appName },
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Approved — Loan " + (res.loan || "") + " created.", "success");
					lms_manager.init();
				},
				error: function () {
					lms_portal.toast("Approval failed.", "danger");
				},
			});
		},
	});
};

lms_manager._reject = function (appName) {
	lms_portal.modal({
		title: "Reject Application",
		body:
			'<div class="lms-field"><label>Reason</label>' +
			'<input type="text" id="lms-reject-reason" class="lms-input" placeholder="e.g. insufficient collateral">' +
			'<div class="lms-field__hint">This reason will be logged on the application.</div></div>',
		confirmText: "Reject",
		confirmVariant: "danger",
		onConfirm: function (overlay) {
			var reasonInput = overlay.querySelector("#lms-reject-reason");
			var reason = reasonInput ? reasonInput.value : "";
			frappe.call({
				method: "lms_saas.api.manager.reject_application",
				args: { application_name: appName, reason: reason },
				callback: function () {
					lms_portal.toast("Application rejected.", "warning");
					lms_manager.init();
				},
				error: function () {
					lms_portal.toast("Rejection failed.", "danger");
				},
			});
		},
	});
};

// ---------------------------------------------------------------------------
// Quick-action modals (New Application, Add Borrower)
// ---------------------------------------------------------------------------
lms_manager._openApplicationModal = function () {
	// Reuse officer API — _require_officer allows Branch Manager persona
	frappe.call({
		method: "lms_saas.api.officer.get_officer_customers",
		callback: function (r) {
			var customers = (r && r.message) || { customers: [] };
			frappe.call({
				method: "lms_saas.api.officer.get_loan_products",
				callback: function (r2) {
					var products = (r2 && r2.message) || { products: [] };
					lms_manager._renderApplicationModal(customers, products);
				}
			});
		}
	});
};

lms_manager._renderApplicationModal = function (customers, products) {
	var customerOpts = (customers.customers || []).map(function (c) {
		return '<option value="' + lms_portal.escape(c.name) + '">' +
			lms_portal.escape(c.customer_name) + "</option>";
	}).join("");
	var productOpts = (products.products || []).map(function (p) {
		return '<option value="' + lms_portal.escape(p.name) + '">' +
			lms_portal.escape(p.product_name) + "</option>";
	}).join("");

	var body =
		'<div class="lms-form">' +
		'<label>Customer' +
		'<select id="lms-mgr-app-customer" class="lms-input">' +
		'<option value="">— Select customer —</option>' +
		'<option value="__new__">+ New borrower…</option>' +
		customerOpts +
		"</select></label>" +
		'<div id="lms-mgr-new-borrower-fields" hidden>' +
		'<label>First name<input type="text" id="lms-mgr-new-first" class="lms-input" placeholder="John"></label>' +
		'<label>Last name<input type="text" id="lms-mgr-new-last" class="lms-input" placeholder="Doe"></label>' +
		'<label>Email (optional)<input type="email" id="lms-mgr-new-email" class="lms-input" placeholder="john@example.com"></label>' +
		'<label>Mobile (optional)<input type="tel" id="lms-mgr-new-mobile" class="lms-input" placeholder="0772..."></label>' +
		'<label>National ID (optional)<input type="text" id="lms-mgr-new-national" class="lms-input" placeholder="99-000000-A99"></label>' +
		"</div>" +
		'<label>Loan product' +
		'<select id="lms-mgr-app-product" class="lms-input">' +
		productOpts +
		"</select></label>" +
		'<label>Loan amount<input type="number" id="lms-mgr-app-amount" class="lms-input" min="1" step="0.01" placeholder="10000"></label>' +
		'<label>Repayment periods<input type="number" id="lms-mgr-app-periods" class="lms-input" min="1" value="6"></label>' +
		"</div>";

	lms_portal.modal({
		title: "New loan application",
		body: body,
		confirmText: "Submit",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var customerVal = (overlay.querySelector("#lms-mgr-app-customer") || {}).value || "";
			var product = (overlay.querySelector("#lms-mgr-app-product") || {}).value || "";
			var amount = parseFloat((overlay.querySelector("#lms-mgr-app-amount") || {}).value) || 0;
			var periods = parseInt((overlay.querySelector("#lms-mgr-app-periods") || {}).value) || 6;

			if (customerVal === "__new__") {
				var first = (overlay.querySelector("#lms-mgr-new-first") || {}).value || "";
				var last = (overlay.querySelector("#lms-mgr-new-last") || {}).value || "";
				var email = (overlay.querySelector("#lms-mgr-new-email") || {}).value || "";
				var mobile = (overlay.querySelector("#lms-mgr-new-mobile") || {}).value || "";
				var national = (overlay.querySelector("#lms-mgr-new-national") || {}).value || "";
				if (!first) {
					frappe.show_alert({ message: "First name is required.", indicator: "red" });
					return;
				}
				frappe.call({
					method: "lms_saas.api.officer.create_borrower",
					args: { first_name: first, last_name: last, email: email, mobile_no: mobile, national_id: national },
					callback: function (r) {
						var res = (r && r.message) || {};
						if (!res.customer) {
							frappe.show_alert({ message: "Could not create borrower.", indicator: "red" });
							return;
						}
						lms_manager._submitApp(res.customer, product, amount, periods);
					},
					error: function () {
						frappe.show_alert({ message: "Could not create borrower.", indicator: "red" });
					},
				});
			} else if (!customerVal) {
				frappe.show_alert({ message: "Please select a customer.", indicator: "red" });
			} else {
				lms_manager._submitApp(customerVal, product, amount, periods);
			}
		},
	});

	// Toggle new-borrower fields when the customer select changes
	setTimeout(function () {
		var dlg = document.querySelector(".lms-modal-overlay");
		if (!dlg) return;
		var customerSelect = dlg.querySelector("#lms-mgr-app-customer");
		var newBorrowerFields = dlg.querySelector("#lms-mgr-new-borrower-fields");
		if (customerSelect && newBorrowerFields) {
			customerSelect.addEventListener("change", function () {
				newBorrowerFields.hidden = customerSelect.value !== "__new__";
			});
		}
	}, 50);
};

lms_manager._submitApp = function (customer, product, amount, periods) {
	frappe.call({
		method: "lms_saas.api.officer.submit_application_on_behalf",
		args: { customer: customer, loan_amount: amount, loan_product: product, repayment_periods: periods },
		callback: function (r) {
			var res = (r && r.message) || {};
			lms_portal.toast("Application submitted. Reference: " + (res.application || ""), "success");
			lms_manager._showTab("dashboard");
		},
		error: function () {
			lms_portal.toast("Something went wrong. Please try again.", "danger");
		},
	});
};

lms_manager._openBorrowerModal = function () {
	var body =
		'<div class="lms-form">' +
		'<label>First name<input type="text" id="lms-mgr-b-first" class="lms-input" placeholder="John"></label>' +
		'<label>Last name<input type="text" id="lms-mgr-b-last" class="lms-input" placeholder="Doe"></label>' +
		'<label>Email (optional)<input type="email" id="lms-mgr-b-email" class="lms-input" placeholder="john@example.com"></label>' +
		'<label>Mobile (optional)<input type="tel" id="lms-mgr-b-mobile" class="lms-input" placeholder="0772..."></label>' +
		'<label>National ID (optional)<input type="text" id="lms-mgr-b-national" class="lms-input" placeholder="99-000000-A99"></label>' +
		"</div>";

	lms_portal.modal({
		title: "Add new borrower",
		body: body,
		confirmText: "Create borrower",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var first = (overlay.querySelector("#lms-mgr-b-first") || {}).value || "";
			var last = (overlay.querySelector("#lms-mgr-b-last") || {}).value || "";
			var email = (overlay.querySelector("#lms-mgr-b-email") || {}).value || "";
			var mobile = (overlay.querySelector("#lms-mgr-b-mobile") || {}).value || "";
			var national = (overlay.querySelector("#lms-mgr-b-national") || {}).value || "";
			if (!first) {
				frappe.show_alert({ message: "First name is required.", indicator: "red" });
				return;
			}
			frappe.call({
				method: "lms_saas.api.officer.create_borrower",
				args: { first_name: first, last_name: last, email: email, mobile_no: mobile, national_id: national },
				callback: function (r) {
					var res = (r && r.message) || {};
					if (!res.customer) {
						frappe.show_alert({ message: "Could not create borrower.", indicator: "red" });
						return;
					}
					lms_portal.toast("Borrower created: " + (res.customer_name || res.customer), "success");
					lms_manager._showTab("borrowers");
				},
				error: function () {
					frappe.show_alert({ message: "Could not create borrower.", indicator: "red" });
				},
			});
		},
	});
};

// ---------------------------------------------------------------------------
// Borrowers tab
// ---------------------------------------------------------------------------
lms_manager._loadBorrowers = function (content) {
	var html = '<div class="lms-stack">';
	html += '<div class="lms-panel">';
	html += '<div class="lms-section-header">';
	html += '<div class="lms-section-header__title"><h3>Borrowers</h3></div>';
	html += '<div class="lms-section-header__controls">';
	html += '<input type="text" id="lms-borrower-search" class="lms-input" placeholder="Search by name, mobile, email, ID…">';
	html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-borrower-search-btn">Search</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-borrower-list-all">List All</button>';
	html += '</div></div>';
	html += '<div id="lms-borrower-results"></div>';
	html += '</div></div>';
	content.innerHTML = html;

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

	// Auto-load all borrowers on tab open
	lms_manager._fetchBorrowers(content, "");
};

lms_manager._fetchBorrowers = function (content, query) {
	var results = content.querySelector("#lms-borrower-results");
	if (!results) return;
	results.innerHTML = lms_portal.loading("Searching…");

	frappe.call({
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
	frappe.call({
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
	var html = '<div class="lms-stack">';
	html += '<div class="lms-panel">';
	html += '<div class="lms-section-header">';
	html += '<div class="lms-section-header__title"><h3>All Loans</h3></div>';
	html += '<div class="lms-section-header__controls">';
	html += '<select id="lms-loan-status-filter" class="lms-input lms-fallback-select">';
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
	html += '</div></div>';
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

	frappe.call({
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
	frappe.call({
		method: "lms_saas.api.manager.get_loan_detail",
		args: { loan_name: loanName },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_manager._showLoanModal(data);
		},
	});
};

lms_manager._showLoanModal = function (data) {
	var l = data.loan || {};
	var html = '<div class="lms-form">';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Loan #</div><div class="lms-summary-value">' + lms_portal.escape(l.name || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Borrower</div><div class="lms-summary-value">' + lms_portal.escape(l.borrower_name || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Amount</div><div class="lms-summary-value">' + format_currency(l.loan_amount || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Outstanding</div><div class="lms-summary-value">' + format_currency(l.outstanding || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Rate</div><div class="lms-summary-value">' + (l.rate_of_interest || 0) + '%</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(l.status || "") + '</div></div>';
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
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});
};

// ---------------------------------------------------------------------------
// Reports tab
// ---------------------------------------------------------------------------
lms_manager._loadReports = function (content) {
	var html = '<div class="lms-stack">';
	html += '<div class="lms-panel">';
	html += '<div class="lms-section-header"><h3>Reports</h3></div>';
	html += '<div class="lms-report-tabs">';
	html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-report-btn" data-report="arrears">Arrears Aging</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-report-btn" data-report="disbursement">Disbursement Report</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-report-btn" data-report="collections">Collections Report</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-report-btn" data-report="portfolio">Portfolio Summary</button>';
	html += '</div>';
	html += '<div id="lms-report-content"></div>';
	html += '</div></div>';
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

	if (reportType === "arrears") {
		frappe.call({
			method: "lms_saas.api.manager.get_arrears_aging_report",
			callback: function (r) {
				lms_manager._renderArrearsReport(rc, (r && r.message) || {});
			},
		});
	} else if (reportType === "disbursement") {
		frappe.call({
			method: "lms_saas.api.manager.get_disbursement_report",
			callback: function (r) {
				lms_manager._renderDisbursementReport(rc, (r && r.message) || {});
			},
		});
	} else if (reportType === "collections") {
		frappe.call({
			method: "lms_saas.api.manager.get_collections_report",
			callback: function (r) {
				lms_manager._renderCollectionsReport(rc, (r && r.message) || {});
			},
		});
	} else if (reportType === "portfolio") {
		frappe.call({
			method: "lms_saas.api.manager.get_portfolio_summary",
			callback: function (r) {
				lms_manager._renderPortfolioReport(rc, (r && r.message && r.message.summary) || {});
			},
		});
	}
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
	frappe.call({
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
	if (!collateral.length) {
		el.innerHTML = '<div class="lms-stack"><div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">🏠</div><h3>No collateral registered</h3><p>Collateral will appear here once loans have pledged assets.</p></div></div></div>';
		return;
	}
	var html = '<div class="lms-stack">';
	html += '<div class="lms-panel">';
	html += '<div class="lms-section-header"><h3>Collateral Register</h3><span class="lms-muted">' + collateral.length + ' items</span></div>';
	html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Collateral #</th><th>Type</th><th>Description</th><th>Market Value</th><th>NRV</th><th>Status</th><th>Linked Loans</th></tr></thead><tbody>";
	collateral.forEach(function (c) {
		html += "<tr>";
		html += "<td><strong>" + lms_portal.escape(c.name || "") + "</strong></td>";
		html += "<td>" + lms_portal.escape(c.collateral_type || "—") + "</td>";
		html += "<td>" + lms_portal.escape(c.description || "—") + "</td>";
		html += "<td>" + format_currency(c.market_value || 0) + "</td>";
		html += "<td>" + format_currency(c.net_realizable_value || 0) + "</td>";
		html += "<td>" + lms_portal.escape(c.status || "—") + "</td>";
		html += "<td>" + ((c.linked_loans || []).length) + "</td>";
		html += "</tr>";
	});
	html += "</tbody></table></div></div></div>";
	el.innerHTML = html;
};

// ---------------------------------------------------------------------------
// Team tab
// ---------------------------------------------------------------------------
lms_manager._loadTeam = function (content) {
	content.innerHTML = lms_portal.loading("Loading team…");
	frappe.call({
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
	if (!staff.length) {
		el.innerHTML = '<div class="lms-stack"><div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">👥</div><h3>No staff found</h3><p>No active staff in your branch.</p></div></div></div>';
		return;
	}
	var html = '<div class="lms-stack"><div class="lms-panel">';
	var memberLabel = staff.length === 1 ? '1 member' : staff.length + ' members';
	html += '<div class="lms-section-header">';
	html += '<div class="lms-section-header__title"><h3>Branch Team</h3><span class="lms-badge lms-badge--default">' + memberLabel + '</span></div>';
	html += '</div>';
	html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Name</th><th>Designation</th><th>Persona</th><th>Loans</th><th>User</th></tr></thead><tbody>";
	staff.forEach(function (s) {
		html += "<tr>";
		html += "<td><strong>" + lms_portal.escape(s.employee_name || s.name) + "</strong></td>";
		html += "<td>" + lms_portal.escape(s.designation || "—") + "</td>";
		html += '<td><span class="lms-badge">' + lms_portal.escape(s.persona || "—") + "</span></td>";
		html += "<td>" + (s.loan_count || 0) + "</td>";
		html += "<td>" + lms_portal.escape(s.user_id || "—") + "</td>";
		html += "</tr>";
	});
	html += "</tbody></table></div></div></div>";
	el.innerHTML = html;
};