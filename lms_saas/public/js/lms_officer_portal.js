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
	return (
		'<div class="lms-quick-actions">' +
		'<button type="button" class="lms-btn lms-btn--primary lms-quick-action" id="lms-officer-new-app-top">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M12 18v-6"/><path d="M9 15h6"/></svg>' +
		'New Application' +
		'</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-quick-action" id="lms-officer-add-borrower">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>' +
		'Add Borrower' +
		'</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-quick-action" id="lms-officer-view-loans">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>' +
		'My Loans' +
		'</button>' +
		'</div>'
	);
};

lms_officer._tabNav = function () {
	var tabs = [
		{ id: "dashboard", label: "Dashboard", icon: "📊" },
		{ id: "borrowers", label: "Borrowers", icon: "👤" },
		{ id: "loans", label: "My Loans", icon: "💰" },
		{ id: "leads", label: "Leads", icon: "📞" },
		{ id: "reports", label: "Reports", icon: "📈" },
	];
	var html = '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_officer._currentTab === t.id ? " lms-tab--active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	return html;
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
	var viewLoansBtn = root.querySelector("#lms-officer-view-loans");
	if (viewLoansBtn) {
		viewLoansBtn.addEventListener("click", function () {
			lms_officer._currentTab = "loans";
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.toggle("lms-tab--active", b.getAttribute("data-tab") === "loans");
			});
			lms_officer._showTab("loans");
		});
	}
};

lms_officer._bindTabs = function () {
	var root = document.getElementById("lms-officer-root");
	if (!root) return;
	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_officer._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("lms-tab--active");
			});
			btn.classList.add("lms-tab--active");
			lms_officer._showTab(lms_officer._currentTab);
		});
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

	frappe.call({
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

	frappe.call({
		method: "lms_saas.api.officer.get_pending_applications",
		callback: function (r) {
			appsData = (r && r.message) || { applications: [] };
			appsLoaded = true;
			tryRender();
		},
	});

	frappe.call({
		method: "lms_saas.api.officer.get_my_loans_as_officer",
		callback: function (r) {
			loansData = (r && r.message) || { loans: [] };
			loansLoaded = true;
			tryRender();
		},
	});

	frappe.call({
		method: "lms_saas.api.dashboard.get_branch_overview",
		callback: function (r) {
			branchData = (r && r.message) || { officer_performance: [] };
			branchLoaded = true;
			tryRender();
		},
	});

	frappe.call({
		method: "lms_saas.api.dashboard.get_collections_overview",
		callback: function (r) {
			collectionsData = (r && r.message) || { today_total: 0, par30: 0, par60: 0, par90: 0 };
			collectionsLoaded = true;
			tryRender();
		},
	});

	// Pre-load customers and products for the application modal
	frappe.call({
		method: "lms_saas.api.officer.get_officer_customers",
		callback: function (r) {
			customersData = (r && r.message) || { customers: [] };
		},
	});
	frappe.call({
		method: "lms_saas.api.officer.get_loan_products",
		callback: function (r) {
			productsData = (r && r.message) || { products: [] };
		},
	});

	// Pre-load customers and products for the application modal is handled by _openApplicationModalFromHeader
};

lms_officer._renderAll = function (root, dash, apps, loans, branch, collections, customers, products) {
	var html = '<div class="lms-stack">';

	// KPI cards
	var k = dash.kpis || {};
	html += '<section class="lms-summary" aria-label="Officer KPIs">';
	html += lms_officer._kpiCard("Pending applications", k.pending_applications || 0);
	html += lms_officer._kpiCard("My active loans", k.my_active_loans || 0);
	html += lms_officer._kpiCard("Disbursed this month", k.disbursed_this_month || 0);
	html += lms_officer._kpiCard("PAR count", k.par_count || 0);
	html += lms_officer._kpiCard("Branch leads", k.branch_leads || 0);
	html += "</section>";

	// Today vs PAR gauge
	html += '<div class="lms-chart-slot">';
	html += '<div class="lms-chart-slot__head"><h3>Today\'s collections</h3></div>';
	html += '<div class="lms-chart-slot__body" id="lms-officer-today-gauge" aria-live="polite"></div>';
	html += '</div>';

	// Officer performance bar
	html += '<div class="lms-chart-slot lms-chart-slot--lg">';
	html += '<div class="lms-chart-slot__head"><h3>Officer performance</h3></div>';
	html += '<div class="lms-chart-slot__body" id="lms-officer-performance" aria-live="polite"></div>';
	html += '</div>';

	// Pending applications
	html += '<div class="lms-panel">';
	html += "<h3>Pending applications</h3>";
	var appRows = (apps.applications || []);
	if (!appRows.length) {
		html +=
			'<div class="staff-empty-state">' +
			"<p>No pending applications. When a borrower submits an application, it will appear here.</p>" +
			"</div>";
	} else {
		html += '<ul class="lms-list">';
		appRows.forEach(function (row) {
			html +=
				'<li class="lms-list__item">' +
				'<div class="lms-list__info">' +
				"<strong>" + lms_portal.escape(row.customer_name || row.applicant || "—") + "</strong>" +
				" — " + lms_portal.escape(row.product_name || row.loan_product || "") +
				" — " + format_currency(row.loan_amount || 0) +
				" — " + lms_portal.escape(row.status || "Draft") +
				"</div></li>";
		});
		html += "</ul>";
	}
	html += "</div>";

	// My assigned loans
	html += '<div class="lms-panel">';
	html += "<h3>My assigned loans</h3>";
	var loanRows = (loans.loans || []);
	if (!loanRows.length) {
		html +=
			'<div class="staff-empty-state">' +
			"<p>No loans assigned to you yet.</p>" +
			"</div>";
	} else {
		html += '<ul class="lms-list">';
		loanRows.forEach(function (row) {
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
		html += "</ul>";
	}
	html += "</div>";

	html += "</div>"; // .lms-stack

	root.innerHTML = html;

	// -------- Charts ------------------------------------------------
	var gaugeEl = document.getElementById("lms-officer-today-gauge");
	if (gaugeEl) {
		var todayTotal = (collections && collections.today_total) || 0;
		var parTotal = ((collections && (collections.par30 || 0)) +
			(collections && (collections.par60 || 0) || 0) +
			(collections && (collections.par90 || 0) || 0)) || 0;
		lms_portal._renderOrFallback(gaugeEl, function (el) {
			return LMSChart.donut(el,
				["Collected today", "PAR outstanding"],
				[todayTotal, parTotal],
				{ height: 220, hideLegend: true }
			);
		}, function () {
			gaugeEl.innerHTML =
				'<div class="lms-stat-row">' +
				'<div class="lms-stat"><div class="lms-stat-label">Collected today</div>' +
				'<div class="lms-stat-value">' + format_currency(todayTotal) + '</div></div>' +
				'<div class="lms-stat"><div class="lms-stat-label">PAR outstanding</div>' +
				'<div class="lms-stat-value">' + format_currency(parTotal) + '</div></div>' +
				'</div>';
		});
	}

	var perfEl = document.getElementById("lms-officer-performance");
	if (perfEl) {
		var perf = (branch && branch.officer_performance) || [];
		if (!perf.length) {
			LMSChart.empty(perfEl, "No officer data yet.");
		} else {
			var pLabels = perf.map(function (o) { return o.officer || "Unassigned"; });
			var pValues = perf.map(function (o) { return o.outstanding || 0; });
			lms_portal._renderOrFallback(perfEl, function (el) {
				return LMSChart.bar(el, pLabels, pValues, {
					name: "Outstanding",
					height: 220,
					hideLegend: true
				});
			}, function () {
				perfEl.innerHTML = lms_portal.simpleBars(
					perf.map(function (o) { return { label: o.officer, value: o.outstanding }; })
				);
			});
		}
	}
};

lms_officer._openApplicationModalFromHeader = function () {
	var root = document.getElementById("lms-officer-tab-content");
	if (!root) return;
	var customers = { customers: [] };
	var products = { products: [] };
	frappe.call({
		method: "lms_saas.api.officer.get_officer_customers",
		callback: function (r) {
			customers = (r && r.message) || { customers: [] };
			frappe.call({
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
		'<label>Loan amount<input type="number" id="lms-app-amount" class="lms-input" min="1" step="0.01" placeholder="10000"></label>' +
		'<label>Repayment periods<input type="number" id="lms-app-periods" class="lms-input" min="1" value="6"></label>' +
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
		var customerVal = (dlg.dialog.querySelector("#lms-app-customer") || {}).value || "";
		var product = (dlg.dialog.querySelector("#lms-app-product") || {}).value || "";
		var amount = parseFloat((dlg.dialog.querySelector("#lms-app-amount") || {}).value) || 0;
		var periods = parseInt((dlg.dialog.querySelector("#lms-app-periods") || {}).value) || 6;

		if (customerVal === "__new__") {
			var first = (dlg.dialog.querySelector("#lms-new-first") || {}).value || "";
			var last = (dlg.dialog.querySelector("#lms-new-last") || {}).value || "";
			var email = (dlg.dialog.querySelector("#lms-new-email") || {}).value || "";
			var mobile = (dlg.dialog.querySelector("#lms-new-mobile") || {}).value || "";
			var national = (dlg.dialog.querySelector("#lms-new-national") || {}).value || "";
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
					lms_officer._submitApp(res.customer, product, amount, periods);
				},
				error: function () {
					frappe.show_alert({ message: "Could not create borrower.", indicator: "red" });
				},
			});
		} else if (!customerVal) {
			frappe.show_alert({ message: "Please select a customer.", indicator: "red" });
		} else {
			lms_officer._submitApp(customerVal, product, amount, periods);
		}
	});
};

lms_officer._submitApp = function (customer, product, amount, periods) {
	frappe.call({
		method: "lms_saas.api.officer.submit_application_on_behalf",
		args: { customer: customer, loan_amount: amount, loan_product: product, repayment_periods: periods },
		callback: function (r) {
			var res = (r && r.message) || {};
			frappe.show_alert({
				message: lms_copy.tSync("wizard.submitted", "Application submitted. Reference: {reference}", { reference: res.application || "" }),
				indicator: "green",
			});
			lms_officer._showTab("dashboard");
		},
		error: function () {
			frappe.show_alert({
				message: lms_copy.tSync("generic.error", "Something went wrong. Please try again."),
				indicator: "red"
			});
		},
	});
};

lms_officer._openBorrowerModal = function () {
	var body =
		'<div class="lms-form">' +
		'<label>First name<input type="text" id="lms-of-b-first" class="lms-input" placeholder="John"></label>' +
		'<label>Last name<input type="text" id="lms-of-b-last" class="lms-input" placeholder="Doe"></label>' +
		'<label>Email (optional)<input type="email" id="lms-of-b-email" class="lms-input" placeholder="john@example.com"></label>' +
		'<label>Mobile (optional)<input type="tel" id="lms-of-b-mobile" class="lms-input" placeholder="0772..."></label>' +
		'<label>National ID (optional)<input type="text" id="lms-of-b-national" class="lms-input" placeholder="99-000000-A99"></label>' +
		"</div>";

	lms_portal.modal({
		title: "Add new borrower",
		body: body,
		confirmText: "Create borrower",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var first = (overlay.querySelector("#lms-of-b-first") || {}).value || "";
			var last = (overlay.querySelector("#lms-of-b-last") || {}).value || "";
			var email = (overlay.querySelector("#lms-of-b-email") || {}).value || "";
			var mobile = (overlay.querySelector("#lms-of-b-mobile") || {}).value || "";
			var national = (overlay.querySelector("#lms-of-b-national") || {}).value || "";
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
					lms_officer._showTab("borrowers");
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
lms_officer._loadBorrowers = function (content) {
	var html = '<div class="lms-panel">';
	html += '<div class="lms-section-header">';
	html += '<div class="lms-section-header__title"><h3>Borrowers</h3></div>';
	html += '<div class="lms-section-header__controls">';
	html += '<input type="text" id="lms-of-borrower-search" class="lms-input" placeholder="Search by name, mobile, email, ID…">';
	html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-of-borrower-search-btn">Search</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-of-borrower-list-all">List All</button>';
	html += '</div></div>';
	html += '<div id="lms-of-borrower-results"></div>';
	html += '</div>';
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

	frappe.call({
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
	if (!borrowers.length) {
		el.innerHTML = '<div class="lms-empty"><div class="lms-empty-icon">👤</div><h3>No borrowers found</h3><p>Try a different search.</p></div>';
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
	frappe.call({
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

	frappe.call({
		method: "lms_saas.api.officer.get_my_loans_as_officer",
		callback: function (r) {
			var loans = (r && r.message && r.message.loans) || [];
			lms_officer._renderLoansTab(content, loans);
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load loans.");
		},
	});
};

lms_officer._renderLoansTab = function (el, loans) {
	if (!loans.length) {
		el.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">💰</div><h3>No loans assigned</h3><p>No active loans are assigned to you.</p></div></div>';
		return;
	}
	var html = '<div class="lms-panel">';
	html += '<div class="lms-section-header"><h3>My Assigned Loans</h3><span class="lms-muted">' + loans.length + ' loans</span></div>';
	html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Loan #</th><th>Borrower</th><th>Amount</th><th>Outstanding</th><th>Status</th><th>DPD</th><th>Actions</th></tr></thead><tbody>";
	loans.forEach(function (l) {
		html += "<tr>";
		html += "<td><strong>" + lms_portal.escape(l.name) + "</strong></td>";
		html += "<td>" + lms_portal.escape(l.customer_name || l.applicant || "—") + "</td>";
		html += "<td>" + format_currency(l.loan_amount || 0) + "</td>";
		html += "<td>" + format_currency(l.outstanding || 0) + "</td>";
		html += '<td><span class="lms-badge ' + lms_portal.badgeClass(l.dpd, l.status) + '">' + lms_portal.escape(l.status || "") + "</span></td>";
		html += "<td>" + (l.dpd || 0) + "</td>";
		html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-loan-view" data-loan="' + lms_portal.escape(l.name) + '">View</button></td>';
		html += "</tr>";
	});
	html += "</tbody></table></div></div>";
	el.innerHTML = html;

	el.querySelectorAll(".lms-of-loan-view").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_officer._viewLoan(btn.getAttribute("data-loan"));
		});
	});
};

lms_officer._viewLoan = function (loanName) {
	frappe.call({
		method: "lms_saas.api.officer.get_loan_detail",
		args: { loan_name: loanName },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_officer._showLoanModal(data);
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

	frappe.call({
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
	var html = '<div class="lms-panel">';
	html += '<div class="lms-section-header">';
	html += '<div class="lms-section-header__title"><h3>Leads</h3></div>';
	html += '<div class="lms-section-header__controls">';
	html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-of-new-lead">+ New Lead</button>';
	html += '</div></div>';

	if (!leads.length) {
		html += '<div class="lms-empty"><div class="lms-empty-icon">📞</div><h3>No leads</h3><p>No leads in your branch yet.</p></div>';
	} else {
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
		html += "<thead><tr><th>Name</th><th>Mobile</th><th>Email</th><th>Status</th><th>Source</th><th>Consent</th><th>Actions</th></tr></thead><tbody>";
		leads.forEach(function (l) {
			html += "<tr>";
			html += "<td><strong>" + lms_portal.escape(l.lead_name || l.name) + "</strong></td>";
			html += "<td>" + lms_portal.escape(l.mobile_no || "—") + "</td>";
			html += "<td>" + lms_portal.escape(l.email_id || "—") + "</td>";
			html += "<td>" + lms_portal.escape(l.status || "—") + "</td>";
			html += "<td>" + lms_portal.escape(l.source || "—") + "</td>";
			html += '<td><span class="lms-badge ' + (l.custom_consent_given ? "lms-badge--success" : "lms-badge--muted") + '">' + (l.custom_consent_given ? "Yes" : "No") + "</span></td>";
			html += '<td><div class="lms-data-table__actions">';
			if (l.custom_consent_given) {
				html += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-of-convert-lead" data-lead="' + lms_portal.escape(l.name) + '">Convert</button>';
			}
			html += '</div></td>';
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}
	html += '</div>';
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
		frappe.call({
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
			frappe.call({
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
	var html = '<div class="lms-panel">';
	html += '<div class="lms-section-header"><h3>My Reports</h3></div>';
	html += '<div class="lms-report-tabs">';
	html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-of-report-btn" data-report="portfolio">Portfolio Summary</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-report-btn" data-report="arrears">Arrears Aging</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-report-btn" data-report="collections">Collections Report</button>';
	html += '</div>';
	html += '<div id="lms-of-report-content"></div>';
	html += '</div>';
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

	if (reportType === "portfolio") {
		frappe.call({
			method: "lms_saas.api.officer.get_my_portfolio_summary",
			callback: function (r) {
				var s = (r && r.message && r.message.summary) || {};
				var html = '<h4>My Portfolio Summary</h4>';
				html += '<div class="lms-summary" style="margin-bottom:1rem;">';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Loans</div><div class="lms-summary-value">' + (s.total_loans || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Total Outstanding</div><div class="lms-summary-value">' + format_currency(s.total_outstanding || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Current</div><div class="lms-summary-value">' + (s.current_count || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR 30+</div><div class="lms-summary-value">' + (s.par30_count || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR 60+</div><div class="lms-summary-value">' + (s.par60_count || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">PAR 90+</div><div class="lms-summary-value">' + (s.par90_count || 0) + '</div></div>';
				html += '</div>';
				rc.innerHTML = html;
			},
		});
	} else if (reportType === "arrears") {
		frappe.call({
			method: "lms_saas.api.officer.get_my_arrears_report",
			callback: function (r) {
				var data = (r && r.message) || {};
				var b = data.buckets || {};
				var html = '<h4>My Arrears Aging</h4>';
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
				if (!html.match(/<h5/)) {
					html += '<p>No arrears — all loans are current.</p>';
				}
				rc.innerHTML = html;
			},
		});
	} else if (reportType === "collections") {
		frappe.call({
			method: "lms_saas.api.officer.get_my_collections_report",
			callback: function (r) {
				var data = (r && r.message) || {};
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
				rc.innerHTML = html;
			},
		});
	}
};
