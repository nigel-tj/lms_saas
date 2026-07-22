/* LMS Loan Officer portal — dashboard, applications, assigned loans */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_officer");
} else {
	window.lms_officer = window.lms_officer || {};
}

lms_officer._currentTab = "dashboard";

lms_officer.init = function () {
	var root = document.getElementById("lms-officer-root");
	if (!root) return;

	root.innerHTML = lms_officer._pageHeader() + lms_officer._tabNav() + '<div id="lms-officer-tab-content"></div>';
	lms_officer._bindTabs();
	lms_officer._bindPrimaryAction();
	lms_officer._showTab(lms_officer._currentTab);
};

lms_officer._pageHeader = function () {
	// Topbar quick actions. NOTE: "My Loans" is NOT here — it would be a
	// duplicate of the 💰 My Loans tab. Tabs already expose the same view
	// without an extra click, so the topbar only carries the two primary
	// actions: start a new application, onboard a new borrower.
	return (
		'<div class="lms-quick-actions" role="toolbar" aria-label="Officer quick actions">' +
		'<button type="button" class="lms-btn lms-btn--primary lms-quick-action" id="lms-officer-new-app-top">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M12 18v-6"/><path d="M9 15h6"/></svg>' +
		'New Application' +
		'</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-quick-action" id="lms-officer-add-borrower">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>' +
		'Add Borrower' +
		'</button>' +
		'</div>'
	);
};

lms_officer._tabs = [
	{ id: "dashboard", label: "Dashboard", icon: "bar-chart" },
	{ id: "borrowers", label: "Borrowers", icon: "users" },
	{ id: "loans", label: "My Loans", icon: "wallet" },
	{ id: "leads", label: "Leads", icon: "phone" },
	{ id: "reports", label: "Reports", icon: "trending-up" },
];

lms_officer._tabNav = function () {
	return lms_portal.tabNav(lms_officer._tabs, lms_officer._currentTab);
};

lms_officer._bindPrimaryAction = function () {
	var root = document.getElementById("lms-officer-root");
	if (!root) return;
	var btn = root.querySelector("#lms-officer-new-app-top");
	if (btn) {
		btn.addEventListener("click", function () {
			lms_officer._openApplicationModalFromHeader();
		});
	}
	var addBorrowerBtn = root.querySelector("#lms-officer-add-borrower");
	if (addBorrowerBtn) {
		addBorrowerBtn.addEventListener("click", function () {
			lms_officer._openBorrowerModal();
		});
	}
	// The "View Loans" topbar button was removed (it duplicated the
	// 💰 My Loans tab); the binding stays as a no-op for any cached markup.
	var viewLoansBtn = root.querySelector("#lms-officer-view-loans");
	if (viewLoansBtn) {
		viewLoansBtn.addEventListener("click", function () {
			lms_officer._currentTab = "loans";
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.toggle("is-active", b.getAttribute("data-tab") === "loans");
				b.setAttribute("aria-selected", b.getAttribute("data-tab") === "loans" ? "true" : "false");
			});
			lms_officer._showTab("loans");
		});
	}
};

lms_officer._bindTabs = function () {
	lms_portal.bindTabs({
		root: document.getElementById("lms-officer-root"),
		tabs: lms_officer._tabs,
		onTab: function (tabId) {
			lms_officer._currentTab = tabId;
			lms_officer._showTab(tabId);
		},
	});
};

lms_officer._showTab = function (tabId) {
	var content = document.getElementById("lms-officer-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "dashboard") {
		lms_officer._loadDashboard(content);
	} else if (tabId === "borrowers") {
		lms_officer._loadBorrowers(content);
	} else if (tabId === "loans") {
		lms_officer._loadLoans(content);
	} else if (tabId === "leads") {
		lms_officer._loadLeads(content);
	} else if (tabId === "reports") {
		lms_officer._loadReports(content);
	}
};

lms_officer._loadDashboard = function (content) {
	var dashboardLoaded = false;
	var appsLoaded = false;
	var loansLoaded = false;
	var branchLoaded = false;
	var collectionsLoaded = false;
	var dashboardData = null;
	var appsData = null;
	var loansData = null;
	var branchData = null;
	var collectionsData = null;
	var customersData = null;
	var productsData = null;

	function tryRender() {
		if (!dashboardLoaded || !appsLoaded || !loansLoaded || !branchLoaded || !collectionsLoaded) return;
		lms_officer._renderAll(content, dashboardData, appsData, loansData, branchData, collectionsData, customersData, productsData);
	}

	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_officer_dashboard",
		callback: function (r) {
			dashboardData = (r && r.message) || {};
			dashboardLoaded = true;
			tryRender();
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load dashboard.", function () {
				lms_officer._showTab("dashboard");
			});
		},
	});

	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_pending_applications",
		callback: function (r) {
			appsData = (r && r.message) || { applications: [] };
			appsLoaded = true;
			tryRender();
		},
	});

	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_my_loans_as_officer",
		callback: function (r) {
			loansData = (r && r.message) || { loans: [] };
			loansLoaded = true;
			tryRender();
		},
	});

	lms_portal.safeCall({
		method: "lms_saas.api.dashboard.get_branch_overview",
		callback: function (r) {
			branchData = (r && r.message) || { officer_performance: [] };
			branchLoaded = true;
			tryRender();
		},
	});

	lms_portal.safeCall({
		method: "lms_saas.api.dashboard.get_collections_overview",
		callback: function (r) {
			collectionsData = (r && r.message) || { today_total: 0, par30: 0, par60: 0, par90: 0 };
			collectionsLoaded = true;
			tryRender();
		},
	});

	// Pre-load customers and products for the application modal
	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_officer_customers",
		callback: function (r) {
			customersData = (r && r.message) || { customers: [] };
		},
	});
	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_loan_products",
		callback: function (r) {
			productsData = (r && r.message) || { products: [] };
		},
	});

	// Pre-load customers and products for the application modal is handled by _openApplicationModalFromHeader
};

lms_officer._renderAll = function (root, dash, apps, loans, branch, collections, customers, products) {
	var html = '<div class="lms-stack">';
	var k = dash.kpis || {};
	var appRows = (apps.applications || []);

	// 1) Work queue first — pending applications (actionable)
	if (!appRows.length) {
		html += lms_portal.emptyPanel(
			"📋",
			"No pending applications",
			"When a borrower submits an application, it will appear here."
		);
	} else {
		html += '<div class="lms-panel">';
		html += '<div class="lms-section-header"><h3>Pending applications</h3>';
		html += '<span class="lms-muted">' + appRows.length + " pending</span></div>";
		html += '<ul class="lms-list">';
		appRows.forEach(function (row) {
			var borrower = row.customer_name || row.applicant || "—";
			html +=
				'<li class="lms-list__item">' +
				'<div class="lms-list__info">' +
				"<strong>" + lms_portal.escape(borrower) + "</strong>" +
				" — " + lms_portal.escape(row.product_name || row.loan_product || "") +
				" — " + format_currency(row.loan_amount || 0) +
				" — " + lms_portal.escape(row.status || "Draft") +
				"</div>" +
				'<div class="lms-data-table__actions">' +
				'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-of-app-review" ' +
				'data-app="' + lms_portal.escape(row.name || "") + '" ' +
				'data-borrower="' + lms_portal.escape(borrower) + '" ' +
				'data-product="' + lms_portal.escape(row.product_name || row.loan_product || "") + '" ' +
				'data-amount="' + lms_portal.escape(String(row.loan_amount || 0)) + '" ' +
				'data-status="' + lms_portal.escape(row.status || "Draft") + '">' +
				"Review</button>" +
				"</div></li>";
		});
		html += "</ul></div>";
	}

	// 2) Compact KPI strip (max 4) — below the queue
	html += lms_portal.kpiStrip([
		{ label: "Pending applications", value: k.pending_applications || 0, tone: (k.pending_applications || 0) ? "warning" : "" },
		{ label: "Awaiting disbursement", value: k.pending_disbursement || 0, tone: (k.pending_disbursement || 0) ? "warning" : "" },
		{ label: "My active loans", value: k.my_active_loans || 0 },
		{ label: "PAR count", value: k.par_count || 0, tone: (k.par_count || 0) ? "danger" : "" },
	]);

	// 3) Charts below
	html += '<div class="lms-chart-slot">';
	html += '<div class="lms-chart-slot__head"><h3>Today\'s collections</h3></div>';
	html += '<div class="lms-chart-slot__body"><canvas id="lms-officer-today-gauge" aria-live="polite"></canvas></div>';
	html += '</div>';

	html += '<div class="lms-chart-slot lms-chart-slot--lg">';
	html += '<div class="lms-chart-slot__head"><h3>Officer performance</h3></div>';
	html += '<div class="lms-chart-slot__body"><canvas id="lms-officer-performance" aria-live="polite"></canvas></div>';
	html += '</div>';

	// Active loans summary (counts only — the full list lives on the My
	// Loans tab to avoid duplicating the table and the disburse actions).
	if ((k.my_active_loans || 0) > 0) {
		var topOfficer = (loans.loans || []).slice(0, 3);
		html += '<div class="lms-panel">';
		html += '<div class="lms-section-header">';
		html += '<h3>Recent active loans</h3>';
		html += '<a href="#" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-officer-view-all-loans">View all</a>';
		html += '</div>';
		html += '<ul class="lms-list">';
		topOfficer.forEach(function (row) {
			var badge = lms_portal.badgeClass(row.dpd, row.status);
			var badgeLabel = lms_portal.badgeLabel(row.dpd, row.status);
			html +=
				'<li class="lms-list__item">' +
				'<div class="lms-list__info">' +
				"<strong>" + lms_portal.escape(row.customer_name || row.applicant || "—") + "</strong>" +
				" — " + format_currency(row.outstanding || 0) +
				' <span class="lms-badge ' + badge + '">' + lms_portal.escape(badgeLabel) + "</span>" +
				"</div></li>";
		});
		html += "</ul></div>";
	}

	html += "</div>"; // .lms-stack

	root.innerHTML = html;

	// Review buttons — open application detail modal
	root.querySelectorAll(".lms-of-app-review").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_officer._reviewApplication({
				name: btn.getAttribute("data-app"),
				borrower: btn.getAttribute("data-borrower"),
				product: btn.getAttribute("data-product"),
				amount: parseFloat(btn.getAttribute("data-amount")) || 0,
				status: btn.getAttribute("data-status"),
			});
		});
	});

	// -------- Charts ------------------------------------------------
	// Wire the dashboard's "View all" loan shortcut to jump to the My Loans tab.
	var viewAll = root.querySelector("#lms-officer-view-all-loans");
	if (viewAll) {
		viewAll.addEventListener("click", function (e) {
			e.preventDefault();
			lms_officer._currentTab = "loans";
			var nav = document.getElementById("lms-officer-root");
			if (nav) {
				nav.querySelectorAll(".lms-tab").forEach(function (b) {
					b.classList.toggle("is-active", b.getAttribute("data-tab") === "loans");
				});
			}
			lms_officer._showTab("loans");
		});
	}

	// NOTE: switched from the legacy LMSChart API to lms_charts.* which is
	// the current chart library used elsewhere in the portal. Wrapped in
	// try/catch so a chart failure never breaks the dashboard render.
	var gaugeEl = document.getElementById("lms-officer-today-gauge");
	if (gaugeEl && typeof lms_charts !== "undefined") {
		var todayTotal = (collections && collections.today_total) || 0;
		var parTotal = ((collections && (collections.par30 || 0)) +
			(collections && (collections.par60 || 0) || 0) +
			(collections && (collections.par90 || 0) || 0)) || 0;
		try {
			lms_charts.donut("lms-officer-today-gauge", [
				{ label: "Collected today", value: todayTotal, color: lms_officer._resolveColor("var(--lms-success)") },
				{ label: "PAR outstanding", value: parTotal, color: lms_officer._resolveColor("var(--lms-danger)") },
			]);
		} catch (e) {
			gaugeEl.innerHTML =
				'<div class="lms-stat-row">' +
				'<div class="lms-stat"><div class="lms-stat-label">Collected today</div>' +
				'<div class="lms-stat-value">' + format_currency(todayTotal) + '</div></div>' +
				'<div class="lms-stat"><div class="lms-stat-label">PAR outstanding</div>' +
				'<div class="lms-stat-value">' + format_currency(parTotal) + '</div></div>' +
				'</div>';
		}
	}

	var perfEl = document.getElementById("lms-officer-performance");
	if (perfEl && typeof lms_charts !== "undefined") {
		var perf = (branch && branch.officer_performance) || [];
		if (!perf.length) {
			perfEl.innerHTML = '<p class="lms-muted">No officer data yet.</p>';
		} else {
			var perfData = perf.map(function (o) {
				return { label: o.officer || "Unassigned", value: o.outstanding || 0 };
			});
			try {
				lms_charts.bars("lms-officer-performance", perfData);
			} catch (e) {
				perfEl.innerHTML = (lms_portal.simpleBars && lms_portal.simpleBars(perfData)) || "";
			}
		}
	}
};

lms_officer._reviewApplication = function (app) {
	app = app || {};
	var deskHref = "/app/loan-application/" + encodeURIComponent(app.name || "");
	lms_portal.modal({
		title: "Application — " + (app.borrower || app.name || ""),
		size: "lg",
		body:
			'<div class="lms-form">' +
			'<div class="lms-summary" style="margin-bottom:1rem;">' +
			'<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Borrower</div><div class="lms-summary-value">' + lms_portal.escape(app.borrower || "—") + "</div></div>" +
			'<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Amount</div><div class="lms-summary-value">' + format_currency(app.amount || 0) + "</div></div>" +
			'<div class="lms-summary-card"><div class="lms-summary-label">Product</div><div class="lms-summary-value">' + lms_portal.escape(app.product || "—") + "</div></div>" +
			'<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(app.status || "—") + "</div></div>" +
			'<div class="lms-summary-card"><div class="lms-summary-label">Application #</div><div class="lms-summary-value">' + lms_portal.escape(app.name || "—") + "</div></div>" +
			"</div>" +
			'<p class="lms-muted">Open the full record in Desk to edit or submit for manager approval.</p>' +
			'<p><a class="lms-btn lms-btn--ghost lms-btn--sm" href="' + deskHref + '" target="_blank" rel="noopener">Open in Desk</a></p>' +
			"</div>",
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});
};

lms_officer._openApplicationModalFromHeader = function () {
	var root = document.getElementById("lms-officer-tab-content");
	if (!root) return;
	var customers = { customers: [] };
	var products = { products: [] };
	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_officer_customers",
		callback: function (r) {
			customers = (r && r.message) || { customers: [] };
			lms_portal.safeCall({
				method: "lms_saas.api.officer.get_loan_products",
				callback: function (r2) {
					products = (r2 && r2.message) || { products: [] };
					lms_officer._openApplicationModal(customers, products, root);
				}
			});
		}
	});
};

lms_officer._kpiCard = function (label, value) {
	return (
		'<div class="lms-summary-card">' +
		'<div class="lms-summary-label">' + lms_portal.escape(label) + "</div>" +
		'<div class="lms-summary-value">' + lms_portal.escape(value) + "</div>" +
		"</div>"
	);
};

lms_officer._resolveColor = function (cssVar) {
	if (!cssVar || cssVar.indexOf("var(") !== 0) return cssVar || "#2f4f46";
	var name = cssVar.replace(/var\(|\)/g, "").split(",")[0].trim();
	try {
		var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
		return v || "#2f4f46";
	} catch (e) {
		return "#2f4f46";
	}
};

lms_officer._openApplicationModal = function (customers, products, root) {
	var customerOpts = (customers.customers || []).map(function (c) {
		return '<option value="' + lms_portal.escape(c.name) + '">' +
			lms_portal.escape(c.customer_name) + "</option>";
	}).join("");
	var productOpts = (products.products || []).map(function (p) {
		return '<option value="' + lms_portal.escape(p.name) + '">' +
			lms_portal.escape(p.product_name) + "</option>";
	}).join("");

	// Phase 2.2/2.3 — native <dialog> via LMSModal; native <select>s get the
	// pop-out combobox upgrade so customer + product pickers are searchable
	// (data-searchable on the customer select, since the list can be long).
	var body =
		'<div class="lms-form">' +
		'<label>Customer' +
		'<select id="lms-app-customer" class="lms-input lms-fallback-select lms-pop-select" data-searchable>' +
		'<option value="">— Select customer —</option>' +
		'<option value="__new__">+ New borrower…</option>' +
		customerOpts +
		"</select></label>" +
		'<div id="lms-new-borrower-fields" hidden>' +
		'<label>First name<input type="text" id="lms-new-first" class="lms-input" placeholder="John"></label>' +
		'<label>Last name<input type="text" id="lms-new-last" class="lms-input" placeholder="Doe"></label>' +
		'<label>Email (optional)<input type="email" id="lms-new-email" class="lms-input" placeholder="john@example.com"></label>' +
		'<label>Mobile (optional)<input type="tel" id="lms-new-mobile" class="lms-input" placeholder="0772..."></label>' +
		'<label>National ID (optional)<input type="text" id="lms-new-national" class="lms-input" placeholder="99-000000-A99"></label>' +
		"</div>" +
		'<label>Loan product' +
		'<select id="lms-app-product" class="lms-input lms-fallback-select lms-pop-select">' +
		productOpts +
		"</select></label>" +
		'<div class="lms-grid-2">' +
		'<label>Loan amount<input type="number" id="lms-app-amount" class="lms-input" min="1" step="0.01" placeholder="10000"></label>' +
		'<label>Rate of interest (% / yr)<input type="number" id="lms-app-rate" class="lms-input" min="0" max="100" step="0.01" placeholder="24"></label>' +
		'<label>Repayment periods (months)<input type="number" id="lms-app-periods" class="lms-input" min="1" value="6"></label>' +
		'<label>Repayment method<select id="lms-app-method" class="lms-input lms-fallback-select">' +
		'<option value="Repay Over Number of Periods" selected>Repay Over Number of Periods</option>' +
		'<option value="Repay Fixed Amount per Period">Repay Fixed Amount per Period</option>' +
		'</select></label>' +
		'<label>Repayment start date<input type="date" id="lms-app-start" class="lms-input"></label>' +
		'<label>Posting date<input type="date" id="lms-app-posting" class="lms-input"></label>' +
		'</div>' +
		"</div>";

	var dlg = LMSModal.open({
		title: "New loan application",
		body: body,
		actions: [
			{ label: "Cancel", value: false },
			{ label: "Submit", value: true, primary: true }
		]
	});
	// Bind pop-out comboboxes to the <select>s we just rendered inside the dialog
	if (window.LMSForms && typeof LMSForms.bindAll === "function") {
		LMSForms.bindAll(dlg.dialog);
	}

	// Toggle new-borrower fields when the customer select changes
	var customerSelect = dlg.dialog.querySelector("#lms-app-customer");
	var newBorrowerFields = dlg.dialog.querySelector("#lms-new-borrower-fields");
	if (customerSelect && newBorrowerFields) {
		customerSelect.addEventListener("change", function () {
			newBorrowerFields.hidden = customerSelect.value !== "__new__";
		});
	}

	dlg.then(function (submit) {
		if (!submit) return; // cancelled
		var $ = function (id) { return (dlg.dialog.querySelector("#" + id) || {}).value || ""; };
		var customerVal = $("lms-app-customer");
		var product = $("lms-app-product");
		var amount = parseFloat($("lms-app-amount")) || 0;
		var rate = parseFloat($("lms-app-rate")) || 0;
		var periods = parseInt($("lms-app-periods")) || 6;
		var method = $("lms-app-method") || "Repay Over Number of Periods";
		var startDate = $("lms-app-start") || "";
		var postingDate = $("lms-app-posting") || "";

		// Collect all the new-borrower sub-fields too in case the user picked
		// "+ New borrower…" in the dropdown.
		var newBorrower = {};
		if (customerVal === "__new__") {
			["lms-new-first","lms-new-last","lms-new-email","lms-new-mobile","lms-new-national"].forEach(function (id) {
				var el = dlg.dialog.querySelector("#" + id);
				if (el) newBorrower[id.replace("lms-new-", "")] = el.value || "";
			});
		}

		if (customerVal === "__new__") {
			if (!newBorrower.first || !newBorrower.first.trim()) {
				lms_portal.toast("First name is required.", "danger");
				return;
			}
			lms_portal.safeCall({
				method: "lms_saas.api.officer.create_borrower",
				args: {
					first_name: newBorrower.first,
					last_name: newBorrower.last,
					email: newBorrower.email,
					mobile_no: newBorrower.mobile,
					national_id: newBorrower.national,
				},
				callback: function (r) {
					var res = (r && r.message) || {};
					if (!res.customer) {
						lms_portal.toast("Could not create borrower.", "danger");
						return;
					}
					lms_officer._submitApp(res.customer, product, amount, periods, rate, method, startDate, postingDate);
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Could not create borrower.";
					lms_portal.toast(msg, "danger");
				},
			});
		} else if (!customerVal) {
			lms_portal.toast("Please select a customer.", "danger");
		} else {
			lms_officer._submitApp(customerVal, product, amount, periods, rate, method, startDate, postingDate);
		}
	});
};

lms_officer._submitApp = function (customer, product, amount, periods, rate, method, startDate, postingDate) {
	lms_portal.safeCall({
		method: "lms_saas.api.officer.submit_application_on_behalf",
		args: {
			customer: customer,
			loan_amount: amount,
			loan_product: product,
			repayment_periods: periods,
			repayment_method: method || "Repay Over Number of Periods",
			repayment_start_date: startDate || null,
			rate_of_interest: rate > 0 ? rate : null,
			posting_date: postingDate || null,
		},
		callback: function (r) {
			var res = (r && r.message) || {};
			lms_portal.toast("Application submitted. Reference: " + (res.application || ""), "success");
			lms_officer._showTab("dashboard");
		},
		error: function (err) {
			var msg = (err && (err.message || err._server_message)) || "Something went wrong. Please try again.";
			lms_portal.toast(msg, "danger");
		},
	});
};

lms_officer._openBorrowerModal = function () {
	// Full onboarding form. Captures: identity (name, DOB, gender, national ID,
	// ID document upload, proof-of-address upload), contact (email, mobile,
	// address), KYC (status, consent), so the borrower is fully onboarded in
	// one step and the manager can approve a loan application immediately.
	var body =
		'<div class="lms-form">' +
		// --- Section: Identity ---
		'<div class="lms-section-header"><h4>Identity</h4></div>' +
		'<div class="lms-grid-2">' +
		'<label>First name *<input type="text" id="lms-of-b-first" class="lms-input" placeholder="John" required></label>' +
		'<label>Last name<input type="text" id="lms-of-b-last" class="lms-input" placeholder="Doe"></label>' +
		'<label>Date of birth<input type="date" id="lms-of-b-dob" class="lms-input"></label>' +
		'<label>Gender<select id="lms-of-b-gender" class="lms-input lms-fallback-select">' +
		'<option value="">—</option><option value="Male">Male</option><option value="Female">Female</option><option value="Other">Other</option>' +
		'</select></label>' +
		'<label class="lms-grid-2__full">National ID *<input type="text" id="lms-of-b-national" class="lms-input" placeholder="63-000000-A99" required></label>' +
		'</div>' +

		// --- Section: Contact ---
		'<div class="lms-section-header"><h4>Contact</h4></div>' +
		'<div class="lms-grid-2">' +
		'<label>Email<input type="email" id="lms-of-b-email" class="lms-input" placeholder="john@example.com"></label>' +
		'<label>Mobile<input type="tel" id="lms-of-b-mobile" class="lms-input" placeholder="0772..."></label>' +
		'<label class="lms-grid-2__full">Address line 1<input type="text" id="lms-of-b-addr1" class="lms-input" placeholder="House / plot number, street"></label>' +
		'<label>City<input type="text" id="lms-of-b-city" class="lms-input" placeholder="Harare"></label>' +
		'<label>Customer group<select id="lms-of-b-cgroup" class="lms-input lms-fallback-select"><option value="">— Default —</option></select></label>' +
		'</div>' +

		// --- Section: KYC ---
		'<div class="lms-section-header"><h4>KYC &amp; consent</h4></div>' +
		'<div class="lms-grid-2">' +
		'<label>KYC status<select id="lms-of-b-kyc" class="lms-input lms-fallback-select">' +
		'<option value="Pending" selected>Pending — collect later</option>' +
		'<option value="Approved">Approved — documents verified</option>' +
		'<option value="Rejected">Rejected</option>' +
		'</select></label>' +
		'<label class="lms-grid-2__full"><input type="checkbox" id="lms-of-b-consent"> Customer consents to data processing</label>' +
		'</div>' +
		'<p class="lms-muted" style="margin:0.5rem 0 0;font-size:0.8rem;">Click <strong>Upload</strong> to attach a file from your device. Required only if KYC status is <strong>Approved</strong>.</p>' +
		'<div class="lms-grid-2" style="margin-top:0.5rem;">' +
		lms_portal._fileUploadField({
			id: "lms-of-b-iddoc",
			label: "ID document",
			fieldname: null,
			required: false,
			accept: "image/*,application/pdf",
			buttonLabel: "Upload ID document",
		}) +
		lms_portal._fileUploadField({
			id: "lms-of-b-poa",
			label: "Proof of address",
			fieldname: null,
			required: false,
			accept: "image/*,application/pdf",
			buttonLabel: "Upload proof of address",
		}) +
		'</div>' +
		'</div>';

	// Prefer LMSModal (consistent with New Application) — fallback to
	// lms_portal.modal only if LMSModal isn't loaded for some reason.
	var open = window.LMSModal && window.LMSModal.open
		? function (content) {
			return window.LMSModal.open({
				title: "Add new borrower",
				body: content,
				size: "lg",
				actions: [
					{ label: "Cancel", value: false },
					{ label: "Create borrower", value: true, primary: true },
				],
			});
		}
		: function (content) {
			return lms_portal.modal({
				title: "Add new borrower",
				body: content,
				size: "lg",
				confirmText: "Create borrower",
				confirmVariant: "primary",
			});
		};

	// LMSModal.open returns a Promise-like { then(cb) }; lms_portal.modal
	// returns { close, el }. Normalise both to a callback-based flow.
	var dlg = open(body);
	// Upgrade the dialog's <select> elements to popout comboboxes so
	// dropdowns look consistent across the portal.
	if (dlg && dlg.dialog && window.LMSForms && typeof LMSForms.bindAll === "function") {
		LMSForms.bindAll(dlg.dialog);
	}
	// Read field values from the dialog element while it is still in the DOM.
	// Once the LMSModal action is clicked, the dialog is removed from the
	// document immediately, so `document.body.querySelector("#lms-of-b-…")`
	// returns nothing. Use the captured dlg/dialog reference instead.
	var dlgRoot = (dlg && dlg.dialog) || (dlg && dlg.el) || null;
	// Wire up the file-upload widgets (ID document + proof of address).
	// Do this AFTER we have a reference to the dialog element so the
	// handlers can read the file_url back into the matching hidden input.
	// Pass null as the fieldname so the upload skips the borrower-side
	// upload_kyc_document registration — the officer will save the
	// file_url directly on the new LMS Borrower Compliance record when
	// the borrower is created.
	lms_portal._bindUploadWidgets(dlgRoot, {
		"lms-of-b-iddoc": null,
		"lms-of-b-poa": null,
	});
	var onSubmit = function (submit) {
		if (!submit) return;
		var root = dlgRoot || document.body;
		var $ = function (id) { return (root.querySelector ? root.querySelector("#" + id) : null); };
		var first = ($("lms-of-b-first") || {}).value || "";
		var last = ($("lms-of-b-last") || {}).value || "";
		var dob = ($("lms-of-b-dob") || {}).value || "";
		var gender = ($("lms-of-b-gender") || {}).value || "";
		var national = ($("lms-of-b-national") || {}).value || "";
		var email = ($("lms-of-b-email") || {}).value || "";
		var mobile = ($("lms-of-b-mobile") || {}).value || "";
		var addr1 = ($("lms-of-b-addr1") || {}).value || "";
		var city = ($("lms-of-b-city") || {}).value || "";
		var cgroup = ($("lms-of-b-cgroup") || {}).value || "";
		var kyc = ($("lms-of-b-kyc") || {}).value || "Pending";
		var consent = ($("lms-of-b-consent") || {}).checked ? 1 : 0;
		var iddoc = ($("lms-of-b-iddoc") || {}).value || "";
		var poa = ($("lms-of-b-poa") || {}).value || "";

		if (!first.trim()) {
			lms_portal.toast("First name is required.", "danger");
			return;
		}
		// Only require the file uploads if the officer is approving KYC
		// at the counter. For "Pending — collect later" the server is
		// happy with empty file fields; matching the server keeps the
		// officer's workflow friction-free.
		if (kyc === "Approved" && !iddoc) {
			lms_portal.toast("Please upload the ID document or set KYC to Pending.", "danger");
			return;
		}
		if (kyc === "Approved" && !poa) {
			lms_portal.toast("Please upload the proof of address or set KYC to Pending.", "danger");
			return;
		}
		lms_portal.safeCall({
			method: "lms_saas.api.officer.create_borrower",
			args: {
				first_name: first,
				last_name: last,
				email: email,
				mobile_no: mobile,
				national_id: national,
				date_of_birth: dob,
				gender: gender,
				address_line1: addr1,
				city: city,
				id_document_proof: iddoc,
				proof_of_address: poa,
				consent_given: consent,
				kyc_status: kyc,
				customer_group: cgroup,
			},
			callback: function (r) {
				var res = (r && r.message) || {};
				if (!res.customer) {
					lms_portal.toast("Could not create borrower.", "danger");
					return;
				}
				lms_portal.toast(
					"Borrower created: " + (res.customer_name || res.customer) +
					(res.kyc ? " (KYC " + res.kyc_status + ")" : ""),
					"success"
				);
				lms_officer._showTab("borrowers");
			},
			error: function (err) {
				var msg = (err && (err.message || err._server_message)) || "Could not create borrower.";
				lms_portal.toast(msg, "danger");
			},
		});
	};

	if (dlg && typeof dlg.then === "function") {
		// LMSModal: returns a Promise-like { then }
		dlg.then(onSubmit);
	} else if (dlg && dlg.el) {
		// lms_portal.modal: bind to the confirm button manually
		var confirmBtn = dlg.el.querySelector("[data-lms-modal-confirm]");
		if (confirmBtn) {
			confirmBtn.addEventListener("click", function () { onSubmit(true); });
		}
	}
};

// ---------------------------------------------------------------------------
// Borrowers tab
// ---------------------------------------------------------------------------
lms_officer._loadBorrowers = function (content) {
	// KPI cards are populated by _renderBorrowerTable from the same dataset
	// the table uses, so they never go out of sync. The ids are referenced
	// there, so keep them stable.
	var kpis = lms_portal.kpiStrip([
		{ label: "Total borrowers", value: "—", id: "lms-of-bk-total" },
		{ label: "Active loans", value: "—", id: "lms-of-bk-active" },
		{ label: "KYC approved", value: "—", id: "lms-of-bk-kyc" },
		{ label: "KYC pending", value: "—", id: "lms-of-bk-kyc-pending" },
	]);

	var controls =
		'<input type="text" id="lms-of-borrower-search" class="lms-input" placeholder="Search by name, mobile, email, ID…">' +
		'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-of-borrower-search-btn">Search</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-of-borrower-list-all">List All</button>';
	var html = lms_portal.pageStart() +
		kpis +
		lms_portal.panel({ title: "Borrowers", controls: controls, body: '<div id="lms-of-borrower-results"></div>' }) +
		lms_portal.pageEnd();
	content.innerHTML = html;

	lms_officer._fetchBorrowers(content, "");

	content.querySelector("#lms-of-borrower-search-btn").addEventListener("click", function () {
		lms_officer._fetchBorrowers(content, content.querySelector("#lms-of-borrower-search").value);
	});
	content.querySelector("#lms-of-borrower-search").addEventListener("keypress", function (e) {
		if (e.key === "Enter") {
			lms_officer._fetchBorrowers(content, content.querySelector("#lms-of-borrower-search").value);
		}
	});
	content.querySelector("#lms-of-borrower-list-all").addEventListener("click", function () {
		lms_officer._fetchBorrowers(content, "");
	});
};

lms_officer._fetchBorrowers = function (content, query) {
	var results = content.querySelector("#lms-of-borrower-results");
	if (!results) return;
	results.innerHTML = lms_portal.loading("Searching…");

	lms_portal.safeCall({
		method: "lms_saas.api.officer.search_borrowers",
		args: { query: query },
		callback: function (r) {
			var borrowers = (r && r.message && r.message.borrowers) || [];
			lms_officer._renderBorrowerTable(results, borrowers);
		},
		error: function () {
			results.innerHTML = lms_portal.error("Could not load borrowers.");
		},
	});
};

lms_officer._renderBorrowerTable = function (el, borrowers) {
	// Update KPI cards from the same dataset. Done before the empty-state
	// check so a "no results" search still shows 0 / — rather than stale
	// counts from a previous list.
	var root = document.getElementById("lms-officer-root");
	if (root) {
		var total = borrowers.length;
		var activeLoans = 0;
		var kycApproved = 0;
		var kycPending = 0;
		borrowers.forEach(function (b) {
			activeLoans += (b.active_loans || 0);
			if (b.kyc_status === "Approved") kycApproved += 1;
			else kycPending += 1;
		});
		var setKpi = function (id, val) { var n = root.querySelector("#" + id); if (n) n.textContent = val; };
		setKpi("lms-of-bk-total", total);
		setKpi("lms-of-bk-active", activeLoans);
		setKpi("lms-of-bk-kyc", kycApproved);
		setKpi("lms-of-bk-kyc-pending", kycPending);
	}

	if (!borrowers.length) {
		el.innerHTML = '<div class="lms-empty">' + lms_icons.empty("👤") + '<h3>No borrowers found</h3><p>Try a different search.</p></div>';
		return;
	}
	var html = '<div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Name</th><th>Mobile</th><th>Email</th><th>Loans</th><th>Active</th><th>KYC</th><th>Actions</th></tr></thead><tbody>";
	borrowers.forEach(function (b) {
		html += "<tr>";
		html += "<td><strong>" + lms_portal.escape(b.customer_name || b.name) + "</strong></td>";
		html += "<td>" + lms_portal.escape(b.mobile_no || "—") + "</td>";
		html += "<td>" + lms_portal.escape(b.email_id || "—") + "</td>";
		html += "<td>" + (b.loan_count || 0) + "</td>";
		html += "<td>" + (b.active_loans || 0) + "</td>";
		html += '<td><span class="lms-badge ' + (b.kyc_status === "Approved" ? "lms-badge--success" : "lms-badge--warning") + '">' + lms_portal.escape(b.kyc_status || "Pending") + "</span></td>";
		html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-borrower-view" data-customer="' + lms_portal.escape(b.name) + '">View</button></td>';
		html += "</tr>";
	});
	html += "</tbody></table></div>";
	el.innerHTML = html;

	el.querySelectorAll(".lms-of-borrower-view").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_officer._viewBorrower(btn.getAttribute("data-customer"));
		});
	});
};

lms_officer._viewBorrower = function (customerName) {
	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_borrower_detail",
		args: { customer_name: customerName },
		callback: function (r) {
			var b = (r && r.message && r.message.borrower) || {};
			lms_officer._showBorrowerModal(b);
		},
	});
};

lms_officer._showBorrowerModal = function (b) {
	var html = '<div class="lms-form">';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Name</div><div class="lms-summary-value">' + lms_portal.escape(b.customer_name || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Mobile</div><div class="lms-summary-value">' + lms_portal.escape(b.mobile_no || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Email</div><div class="lms-summary-value">' + lms_portal.escape(b.email_id || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">National ID</div><div class="lms-summary-value">' + lms_portal.escape(b.custom_national_id_number || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">KYC Status</div><div class="lms-summary-value">' + lms_portal.escape((b.compliance || {}).kyc_status || "Pending") + '</div></div>';
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
	html += '</div>';

	lms_portal.modal({
		title: "Borrower Profile — " + (b.customer_name || ""),
		body: html,
		size: "xl",
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});
};

// ---------------------------------------------------------------------------
// Loans tab

// ---------------------------------------------------------------------------
lms_officer._loadLoans = function (content) {
	content.innerHTML = lms_portal.loading("Loading loans…");

	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_assigned_loans",
		callback: function (r) {
			var data = (r && r.message) || {};
			var pending = data.pending || [];
			var active = data.active || [];
			lms_officer._renderLoansTab(content, pending, active);
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load loans.");
		},
	});
};

lms_officer._renderLoansTab = function (el, pending, active) {
	// KPI summary — pending / active / total outstanding / avg ticket. Computed
	// once from the same data the tables render so the cards never drift.
	var totalOutstanding = 0;
	var totalDisbursed = 0;
	active.forEach(function (l) {
		totalOutstanding += l.outstanding || 0;
		totalDisbursed += l.loan_amount || 0;
	});
	pending.forEach(function (l) {
		totalDisbursed += l.loan_amount || 0;
	});
	var avgTicket = (pending.length + active.length)
		? totalDisbursed / (pending.length + active.length)
		: 0;

	var html = lms_portal.pageStart() +
		lms_portal.kpiStrip([
			{ label: "Pending disbursement", value: pending.length, tone: pending.length ? "warning" : "" },
			{ label: "Active loans", value: active.length },
			{ label: "Total outstanding", value: format_currency(totalOutstanding) },
			{ label: "Avg ticket", value: format_currency(avgTicket) },
		]);

	if (!pending.length && !active.length) {
		html += lms_portal.emptyPanel("💰", "No loans assigned", "You have no loans assigned. Approved applications will appear here for disbursement.");
		html += lms_portal.pageEnd();
		el.innerHTML = html;
		return;
	}

	// Pending disbursement section — manager has approved, officer acts next.
	if (pending.length) {
		var pendingBody = '<p class="lms-muted">Manager-approved loans waiting for you to disburse funds.</p>' +
			'<div class="lms-data-table__wrap"><table class="lms-data-table">' +
			"<thead><tr><th>Loan #</th><th>Borrower</th><th>Product</th><th>Amount</th><th>Tenure</th><th>Rate</th><th>Actions</th></tr></thead><tbody>";
		pending.forEach(function (l) {
			pendingBody += "<tr>";
			pendingBody += "<td><strong>" + lms_portal.escape(l.name) + "</strong></td>";
			pendingBody += "<td>" + lms_portal.escape(l.customer_name || l.applicant || "—") + "</td>";
			pendingBody += "<td>" + lms_portal.escape(l.loan_product || "—") + "</td>";
			pendingBody += "<td>" + format_currency(l.loan_amount || 0) + "</td>";
			pendingBody += "<td>" + (l.repayment_periods || 0) + " mo</td>";
			pendingBody += "<td>" + (l.rate_of_interest || 0) + "%</td>";
			pendingBody += '<td><div class="lms-data-table__actions">';
			pendingBody += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-of-disburse-btn" data-loan="' + lms_portal.escape(l.name) + '">Disburse</button>';
			pendingBody += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-loan-view" data-loan="' + lms_portal.escape(l.name) + '">View</button>';
			pendingBody += '</div></td>';
			pendingBody += "</tr>";
		});
		pendingBody += "</tbody></table></div>";
		html += lms_portal.panel({
			title: "Pending Disbursement",
			badge: pending.length + " awaiting",
			badgeClass: "lms-badge--warning",
			body: pendingBody,
		});
	}

	// Active loans section — already disbursed, in repayment.
	if (active.length) {
		var activeBody = '<div class="lms-data-table__wrap"><table class="lms-data-table">' +
			"<thead><tr><th>Loan #</th><th>Borrower</th><th>Amount</th><th>Outstanding</th><th>Status</th><th>DPD</th><th>Actions</th></tr></thead><tbody>";
		active.forEach(function (l) {
			activeBody += "<tr>";
			activeBody += "<td><strong>" + lms_portal.escape(l.name) + "</strong></td>";
			activeBody += "<td>" + lms_portal.escape(l.customer_name || l.applicant || "—") + "</td>";
			activeBody += "<td>" + format_currency(l.loan_amount || 0) + "</td>";
			activeBody += "<td>" + format_currency(l.outstanding || 0) + "</td>";
			activeBody += '<td><span class="lms-badge ' + lms_portal.badgeClass(l.dpd, l.status) + '">' + lms_portal.escape(l.status || "") + "</span></td>";
			activeBody += "<td>" + (l.dpd || 0) + "</td>";
			activeBody += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-loan-view" data-loan="' + lms_portal.escape(l.name) + '">View</button></td>';
			activeBody += "</tr>";
		});
		activeBody += "</tbody></table></div>";
		html += lms_portal.panel({
			title: "Active Loans",
			badge: active.length + " loans",
			body: activeBody,
		});
	}

	html += lms_portal.pageEnd();
	el.innerHTML = html;

	el.querySelectorAll(".lms-of-loan-view").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_officer._viewLoan(btn.getAttribute("data-loan"));
		});
	});
	el.querySelectorAll(".lms-of-disburse-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_officer._confirmDisburse(btn.getAttribute("data-loan"));
		});
	});
};

lms_officer._confirmDisburse = function (loanName) {
	// Find the row to surface the amount in the confirmation.
	var row = document.querySelector('button.lms-of-disburse-btn[data-loan="' + loanName + '"]');
	var tr = row ? row.closest("tr") : null;
	var amount = "—";
	var borrower = "—";
	if (tr) {
		var cells = tr.querySelectorAll("td");
		// Cols: Loan #, Borrower, Product, Amount, Tenure, Rate, Actions
		borrower = cells[1] ? cells[1].textContent.trim() : borrower;
		amount = cells[3] ? cells[3].textContent.trim() : amount;
	}

	lms_portal.modal({
		title: "Disburse Loan",
		size: "lg",
		body:
			'<div class="lms-form">' +
			'<p class="lms-muted">Confirm disbursement of the approved loan. This will submit the loan record and create a Loan Disbursement for the borrower.</p>' +
			'<div class="lms-summary" style="margin:1rem 0;">' +
			'<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Loan #</div><div class="lms-summary-value">' + lms_portal.escape(loanName) + '</div></div>' +
			'<div class="lms-summary-card"><div class="lms-summary-label">Borrower</div><div class="lms-summary-value">' + lms_portal.escape(borrower) + '</div></div>' +
			'<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Amount</div><div class="lms-summary-value">' + lms_portal.escape(amount) + '</div></div>' +
			'</div>' +
			'<div class="lms-field"><label>Disbursement amount</label>' +
			'<input type="number" id="lms-of-disburse-amount" class="lms-input" step="0.01" min="0" value="' + lms_portal.escape(amount.replace(/[^0-9.]/g, "")) + '">' +
			'<div class="lms-field__hint">Defaults to the full sanctioned amount. Adjust only if a partial disbursement is intended.</div></div>' +
			'</div>',
		confirmText: "Disburse",
		confirmVariant: "success",
		onConfirm: function (overlay) {
			var amtInput = overlay.querySelector("#lms-of-disburse-amount");
			var amt = amtInput && amtInput.value ? parseFloat(amtInput.value) : null;
			lms_officer._doDisburse(loanName, amt);
		},
	});
};

lms_officer._doDisburse = function (loanName, amount) {
	lms_portal.safeCall({
		method: "lms_saas.api.officer.disburse_assigned_loan",
		args: { loan_name: loanName, disbursed_amount: amount || null },
		callback: function (r) {
			var data = (r && r.message) || {};
			if (data._lms_error) {
				lms_portal.toast("Disbursement failed.", "danger");
				return;
			}
			lms_portal.toast("Disbursed \u2014 " + (data.disbursement || loanName), "success");
			// Re-render the Loans tab so the loan moves from Pending to Active.
			// We use _currentTab + _showTab so charts on other tabs aren't
			// rebuilt and we stay on the same tab the user was on.
			if (lms_officer._currentTab === "loans") {
				var content = document.getElementById("lms-officer-tab-content");
				if (content) lms_officer._loadLoans(content);
			} else {
				lms_officer._showTab(lms_officer._currentTab);
			}
		},
		error: function (err) {
			var msg = (err && (err.message || err._server_message)) || "Disbursement failed.";
			lms_portal.toast(msg, "danger");
		},
	});
};

lms_officer._viewLoan = function (loanName) {
	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_loan_detail",
		args: { loan_name: loanName },
		callback: function (r) {
			var data = (r && r.message) || {};
			if (data._lms_error) {
				lms_portal.toast("Could not load loan details.", "danger");
				return;
			}
			lms_officer._showLoanModal(data);
		},
		error: function (err) {
			var msg = (err && (err.message || err._server_message)) || "Could not load loan details.";
			lms_portal.toast(msg, "danger");
		},
	});
};

lms_officer._showLoanModal = function (data) {
	var l = data.loan || {};
	var html = '<div class="lms-form">';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Loan #</div><div class="lms-summary-value">' + lms_portal.escape(l.name || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Borrower</div><div class="lms-summary-value">' + lms_portal.escape(l.borrower_name || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Amount</div><div class="lms-summary-value">' + format_currency(l.loan_amount || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Outstanding</div><div class="lms-summary-value">' + format_currency(l.outstanding || 0) + '</div></div>';
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
	html += '</div>';

	lms_portal.modal({
		title: "Loan Detail — " + (l.name || ""),
		body: html,
		size: "xl",
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});
};

// ---------------------------------------------------------------------------
// Leads tab

// ---------------------------------------------------------------------------
lms_officer._loadLeads = function (content) {
	content.innerHTML = lms_portal.loading("Loading leads…");

	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_officer_leads",
		callback: function (r) {
			var leads = (r && r.message && r.message.leads) || [];
			lms_officer._renderLeadsTab(content, leads);
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load leads.");
		},
	});
};

lms_officer._renderLeadsTab = function (el, leads) {
	// KPI summary — total / consented / convert-ready. Computed once from
	// the same dataset the table renders.
	var consented = 0;
	var convertReady = 0;
	leads.forEach(function (l) {
		if (l.custom_consent_given) consented += 1;
		if (l.custom_consent_given && l.status !== "Converted") convertReady += 1;
	});

	var controls = '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-of-new-lead">+ New Lead</button>';
	var body = "";
	if (!leads.length) {
		body = '<div class="lms-empty">' + lms_icons.empty("📞") + '<h3>No leads</h3><p>No leads in your branch yet.</p></div>';
	} else {
		body = '<div class="lms-data-table__wrap"><table class="lms-data-table">' +
			"<thead><tr><th>Name</th><th>Mobile</th><th>Email</th><th>Status</th><th>Source</th><th>Consent</th><th>Actions</th></tr></thead><tbody>";
		leads.forEach(function (l) {
			body += "<tr>";
			body += "<td><strong>" + lms_portal.escape(l.lead_name || l.name) + "</strong></td>";
			body += "<td>" + lms_portal.escape(l.mobile_no || "—") + "</td>";
			body += "<td>" + lms_portal.escape(l.email_id || "—") + "</td>";
			body += "<td>" + lms_portal.escape(l.status || "—") + "</td>";
			body += "<td>" + lms_portal.escape(l.source || "—") + "</td>";
			body += '<td><span class="lms-badge ' + (l.custom_consent_given ? "lms-badge--success" : "lms-badge--muted") + '">' + (l.custom_consent_given ? "Yes" : "No") + "</span></td>";
			body += '<td><div class="lms-data-table__actions">';
			if (l.custom_consent_given) {
				body += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-of-convert-lead" data-lead="' + lms_portal.escape(l.name) + '">Convert</button>';
			}
			body += '</div></td>';
			body += "</tr>";
		});
		body += "</tbody></table></div>";
	}

	var html = lms_portal.pageStart() +
		lms_portal.kpiStrip([
			{ label: "Total leads", value: leads.length },
			{ label: "With consent", value: consented, tone: "success" },
			{ label: "Ready to convert", value: convertReady, tone: "warning" },
		]) +
		lms_portal.panel({ title: "Leads", controls: controls, body: body }) +
		lms_portal.pageEnd();
	el.innerHTML = html;

	var newLeadBtn = el.querySelector("#lms-of-new-lead");
	if (newLeadBtn) {
		newLeadBtn.addEventListener("click", function () {
			lms_officer._openLeadModal(el);
		});
	}
	el.querySelectorAll(".lms-of-convert-lead").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_officer._convertLead(btn.getAttribute("data-lead"));
		});
	});
};

lms_officer._openLeadModal = function (content) {
	var body = '<div class="lms-form">' +
		'<label>First name<input type="text" id="lms-lead-first" class="lms-input" placeholder="John"></label>' +
		'<label>Last name<input type="text" id="lms-lead-last" class="lms-input" placeholder="Doe"></label>' +
		'<label>Email (optional)<input type="email" id="lms-lead-email" class="lms-input" placeholder="john@example.com"></label>' +
		'<label>Mobile (optional)<input type="tel" id="lms-lead-mobile" class="lms-input" placeholder="0772..."></label>' +
		'<label>Source<input type="text" id="lms-lead-source" class="lms-input" placeholder="Walk-in, Facebook, etc."></label>' +
		'</div>';

	var dlg = LMSModal.open({
		title: "New Lead",
		body: body,
		actions: [
			{ label: "Cancel", value: false },
			{ label: "Create", value: true, primary: true }
		]
	});

	dlg.then(function (submit) {
		if (!submit) return;
		var first = (dlg.dialog.querySelector("#lms-lead-first") || {}).value || "";
		var last = (dlg.dialog.querySelector("#lms-lead-last") || {}).value || "";
		var email = (dlg.dialog.querySelector("#lms-lead-email") || {}).value || "";
		var mobile = (dlg.dialog.querySelector("#lms-lead-mobile") || {}).value || "";
		var source = (dlg.dialog.querySelector("#lms-lead-source") || {}).value || "";

		if (!first) {
			frappe.show_alert({ message: "First name is required.", indicator: "red" });
			return;
		}
		lms_portal.safeCall({
			method: "lms_saas.api.officer.create_lead",
			args: { first_name: first, last_name: last, email: email, mobile_no: mobile, source: source },
			callback: function (r) {
				var res = (r && r.message) || {};
				frappe.show_alert({ message: "Lead created: " + (res.lead_name || ""), indicator: "green" });
				lms_officer._showTab("leads");
			},
			error: function () {
				frappe.show_alert({ message: "Could not create lead.", indicator: "red" });
			},
		});
	});
};

lms_officer._convertLead = function (leadName) {
	lms_portal.modal({
		title: "Convert Lead",
		body: '<p class="lms-muted">Convert <strong>' + lms_portal.escape(leadName) + '</strong> to a Customer? This requires consent to be recorded.</p>',
		confirmText: "Convert",
		confirmVariant: "success",
		onConfirm: function () {
			lms_portal.safeCall({
				method: "lms_saas.api.officer.convert_lead",
				args: { lead_name: leadName },
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Lead converted to Customer: " + (res.customer || ""), "success");
					lms_officer._showTab("leads");
				},
				error: function () {
					lms_portal.toast("Conversion failed.", "danger");
				},
			});
		},
	});
};

// ---------------------------------------------------------------------------
// Reports tab
// ---------------------------------------------------------------------------
lms_officer._loadReports = function (content) {
	// Same lms-stack pattern as the other tabs: report-switcher panel first,
	// then a full-width results panel below. The KPIs live inside the report
	// content itself (rendered by _loadReport) so they stay in sync with the
	// active report.
	var controls =
		'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-of-report-btn" data-report="portfolio">Portfolio Summary</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-report-btn" data-report="arrears">Arrears Aging</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-report-btn" data-report="collections">Collections Report</button>';
	var html = lms_portal.pageStart() +
		lms_portal.panel({ title: "My Reports", controls: controls }) +
		'<div class="lms-panel" id="lms-of-report-content"></div>' +
		lms_portal.pageEnd();
	content.innerHTML = html;

	lms_officer._loadReport(content, "portfolio");

	content.querySelectorAll(".lms-of-report-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			content.querySelectorAll(".lms-of-report-btn").forEach(function (b) {
				b.classList.remove("lms-btn--primary");
				b.classList.add("lms-btn--ghost");
			});
			btn.classList.remove("lms-btn--ghost");
			btn.classList.add("lms-btn--primary");
			lms_officer._loadReport(content, btn.getAttribute("data-report"));
		});
	});
};

lms_officer._loadReport = function (content, reportType) {
	var rc = content.querySelector("#lms-of-report-content");
	if (!rc) return;
	rc.innerHTML = lms_portal.loading("Loading report…");

	// Each report declares its API + a renderer. An error handler shows a
	// retry so a 500 doesn't leave the user staring at "Loading report…"
	// forever, and a no-rows result shows a clear empty state.
	var endpoints = {
		portfolio: {
			method: "lms_saas.api.officer.get_my_portfolio_summary",
			unwrap: function (m) { return (m && m.summary) || {}; },
			render: function (s) {
				var html = '<h4>My Portfolio Summary</h4>';
				html += '<div class="lms-summary" style="margin-bottom:1rem;">';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Loans</div><div class="lms-summary-value">' + (s.total_loans || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Outstanding</div><div class="lms-summary-value">' + format_currency(s.total_outstanding || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Current</div><div class="lms-summary-value">' + (s.current_count || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR 30+</div><div class="lms-summary-value">' + (s.par30_count || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR 60+</div><div class="lms-summary-value">' + (s.par60_count || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR 90+</div><div class="lms-summary-value">' + (s.par90_count || 0) + '</div></div>';
				html += '</div>';
				return html;
			},
		},
		arrears: {
			method: "lms_saas.api.officer.get_my_arrears_report",
			unwrap: function (m) { return m || {}; },
			render: function (data) {
				var b = data.buckets || {};
				var html = '<h4>My Arrears Aging</h4>';
				var bucketLabels = { current: "Current", "1_30": "1-30 Days", "31_60": "31-60 Days", "61_90": "61-90 Days", "90_plus": "90+ Days" };
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
				if (!html.match(/<h5/)) {
					html += '<div class="lms-empty">' + lms_icons.empty("✅") + '<h3>No arrears</h3><p>All loans are current.</p></div>';
				}
				return html;
			},
		},
		collections: {
			method: "lms_saas.api.officer.get_my_collections_report",
			unwrap: function (m) { return m || {}; },
			render: function (data) {
				var html = '<h4>My Collections Report</h4>';
				html += '<div class="lms-summary" style="margin-bottom:1rem;">';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Collected</div><div class="lms-summary-value">' + format_currency(data.total_collected || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Count</div><div class="lms-summary-value">' + (data.count || 0) + '</div></div>';
				html += '</div>';
				if (data.repayments && data.repayments.length) {
					html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Date</th><th>Loan</th><th>Borrower</th><th>Amount</th></tr></thead><tbody>';
					data.repayments.forEach(function (r) {
						html += "<tr><td>" + lms_portal.escape(r.posting_date || "") + "</td>";
						html += "<td>" + lms_portal.escape(r.against_loan || "") + "</td>";
						html += "<td>" + lms_portal.escape(r.customer_name || "") + "</td>";
						html += "<td>" + format_currency(r.amount_paid || 0) + "</td></tr>";
					});
					html += "</tbody></table></div>";
				}
				if (!data.repayments || !data.repayments.length) {
					html += '<div class="lms-empty">' + lms_icons.empty("📭") + '<h3>No collections yet</h3><p>Once repayments are recorded they will appear here.</p></div>';
				}
				return html;
			},
		},
	};
	var ep = endpoints[reportType];
	if (!ep) {
		rc.innerHTML = lms_portal.error("Unknown report type.");
		return;
	}
	lms_portal.safeCall({
		method: ep.method,
		callback: function (r) { rc.innerHTML = ep.render(ep.unwrap(r && r.message)); },
		error: function () {
			rc.innerHTML = lms_portal.error("Could not load report.", function () {
				lms_officer._loadReport(content, reportType);
			});
		},
	});
};
