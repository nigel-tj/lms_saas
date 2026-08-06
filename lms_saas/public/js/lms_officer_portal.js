/* LMS Loan Officer portal — dashboard, applications, assigned loans */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_officer");
} else {
	window.lms_officer = window.lms_officer || {};
}

lms_officer._currentTab = "dashboard";

lms_officer.init = function () {
	// R18-defensive: lms_officer may be initialised before lms_portal.js
	// has finished parsing. Retry once on the next tick.
	if (typeof lms_portal === "undefined" || typeof lms_portal.tabNav !== "function") {
		return setTimeout(lms_officer.init, 0);
	}
	var root = document.getElementById("lms-officer-root");
	if (!root) return;

	// R36-C2: restore the last-active tab so a refresh lands the officer
	// back on the tab they were working on (e.g. mid-review on KYC Queue).
	lms_officer._currentTab = lms_portal.persistedTab("officer", lms_officer._currentTab);

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
	// R43: the branch badge is now in the global topbar (see
	// templates/lms_portal/base.html — between the page title and the
	// notification bell) so it shows on every portal page, not just
	// the officer dashboard. Keeping the in-content toolbar to the
	// two primary actions keeps the toolbar scannable.
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
		// R44-F4: Open Tasks shortcut — the operator's muscle memory for
		// the topbar is "the place where I take action". Adding a third
		// button keeps the cap at 3 (Hick's Law) and surfaces the Tasks
		// addon without requiring a scroll to the dashboard section.
		'<a class="lms-btn lms-btn--ghost lms-quick-action" href="/lms/tasks" id="lms-officer-open-tasks">' +
		'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>' +
		'Open Tasks' +
		'</a>' +
		'</div>'
	);
};

lms_officer._tabs = [
	{ id: "dashboard", label: "Dashboard", icon: "bar-chart" },
	{ id: "borrowers", label: "Borrowers", icon: "users" },
	{ id: "loans", label: "My Loans", icon: "wallet" },
	{ id: "kyc", label: "KYC Queue", icon: "shield" },
	// R44-F5: Reports moved before Leads. The operator audit-trail use-case
	// (KYC, portfolio, write-offs) is more common than the sales-pipeline
	// use-case. Nielsen's rule: first slots are higher recall / lower
	// search cost, so the four high-frequency tabs lead.
	{ id: "reports", label: "Reports", icon: "trending-up" },
	{ id: "leads", label: "Leads", icon: "phone" },
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
			// R36-C2: persist the clicked tab so a refresh lands back here.
			lms_portal.saveActiveTab("officer", tabId);
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
	} else if (tabId === "kyc") {
		lms_officer._loadKycQueue(content);
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
	var tasksLoaded = false;
	var dashboardData = null;
	var appsData = null;
	var loansData = null;
	var branchData = null;
	var collectionsData = null;
	var tasksData = null;
	var customersData = null;
	var productsData = null;

	function tryRender() {
		if (!dashboardLoaded || !appsLoaded || !loansLoaded || !branchLoaded || !collectionsLoaded) return;
		// Tasks are optional — render even if the API isn't enabled or the
		// user lacks the addon so the dashboard still populates cleanly.
		lms_officer._renderAll(content, dashboardData, appsData, loansData, branchData, collectionsData, customersData, productsData, tasksData);
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

	// R43: tasks assigned to the officer (Open / Working / Overdue).
	// Surfaces a /tasks snapshot above the pending-applications work queue
	// so the officer sees actionable tasks at a glance. The Tasks addon
	// may be disabled in some bench configs — wrap the call so a missing
	// endpoint does not stall the dashboard.
	try {
		lms_portal.safeCall({
			method: "lms_saas.api.tasks.get_task_board",
			callback: function (r) {
				tasksData = (r && r.message) || null;
				tasksLoaded = true;
				tryRender();
			},
			error: function () {
				tasksLoaded = true;
				tasksData = null;
				tryRender();
			},
		});
	} catch (e) {
		tasksLoaded = true;
		tasksData = null;
		tryRender();
	}

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

lms_officer._appStatusBadgeClass = function (status) {
	// Map Loan Application status to a coloured badge variant.
	// Used by the work queue on the dashboard so the operator can
	// spot "Open" / "Submitted" / "Draft" / "Approved" at a glance.
	// Mirrors the KYC / AML badge taxonomy in lms_manager_portal.js so
	// the operator has one visual vocabulary across portals.
	switch ((status || "Draft")) {
		case "Approved":
			return "success";
		case "Open":
			return "warning";
		case "Submitted":
			return "info";
		case "Rejected":
			return "danger";
		default:
			return "muted";
	}
};

lms_officer._renderWorkQueuePanel = function (tasks, appRows) {
	// R44-F1: single panel containing two sub-headings — "My tasks"
	// (top) and "Pending applications" (bottom). The board observed that
	// the operator context-switches between two similarly-styled panels.
	// Combining them into one queue with two sub-headings reads as a
	// single "things I owe + things the team owes" list.
	var html = '<div class="lms-panel lms-work-queue">';
	html += '<div class="lms-section-header"><h3>Work queue</h3>';
	html += '<span class="lms-muted">' + (appRows.length + lms_officer._countTasks(tasks)) + ' items</span></div>';

	// Sub-section 1: My tasks (compact rows, no panel chrome)
	html += lms_officer._renderTasksRows(tasks);

	// Sub-section 2: Pending applications (card-style queue rows)
	html += lms_officer._renderApplicationsRows(appRows);

	html += '</div>';
	return html;
};

lms_officer._countTasks = function (tasks) {
	if (!tasks || !tasks.board) return 0;
	var n = 0;
	Object.keys(tasks.board).forEach(function (col) {
		n += (tasks.board[col] || []).length;
	});
	return n;
};

lms_officer._renderTasksRows = function (tasks) {
	// R44-F1: render the tasks as a sub-section inside the work queue
	// panel. Returns an empty string when the Tasks addon is disabled.
	if (!tasks || !tasks.board) return '';

	var overdue = [];
	var inProgress = []
	var open = [];
	var statuses = { Open: open, Working: inProgress, "In Progress": inProgress, Pending: inProgress, "Pending Review": inProgress };
	Object.keys(tasks.board || {}).forEach(function (col) {
		(tasks.board[col] || []).forEach(function (t) {
			if (t.is_overdue) { overdue.push(t); return; }
			(statuses[col] || open).push(t);
		});
	});
	var rows = overdue.concat(inProgress).concat(open).slice(0, 5);
	if (!rows.length) return '';

	var html = '<div class="lms-work-queue__sub">';
	html += '<div class="lms-work-queue__sub-head"><h4>My tasks</h4>';
	html += '<a class="lms-muted" href="/lms/tasks">View all</a></div>';
	html += '<div class="lms-tasks-card__list">';
	rows.forEach(function (t) {
		var status = t.status || "Open";
		var overdueCls = t.is_overdue ? " is-overdue" : "";
		var dueCls = t.is_overdue ? " is-overdue" : "";
		var due = t.exp_end_date ? lms_portal.formatDate(t.exp_end_date) : "";
		var priority = t.priority || "Medium";
		html +=
			'<div class="lms-tasks-card__row' + overdueCls + '">' +
			'<span class="lms-tasks-card__status lms-tasks-card__status--' +
			lms_portal.escape(status.replace(/\s+/g, "")) + '"></span>' +
			'<div class="lms-tasks-card__body">' +
			'<div class="lms-tasks-card__subject">' + lms_portal.escape(t.subject || "Untitled task") + '</div>' +
			'</div>' +
			'<span class="lms-tasks-card__priority lms-tasks-card__priority--' +
			lms_portal.escape(priority) + '">' + lms_portal.escape(priority) + '</span>' +
			(due ? '<span class="lms-tasks-card__due' + dueCls + '">Due ' + due + '</span>' : '<span></span>') +
			'</div>';
	});
	html += '</div></div>';
	return html;
};

lms_officer._renderApplicationsRows = function (appRows) {
	// R44-F1: render the pending applications as a sub-section inside the
	// work queue panel.
	var html = '<div class="lms-work-queue__sub">';
	html += '<div class="lms-work-queue__sub-head"><h4>Pending applications</h4>';
	html += '<span class="lms-muted">' + appRows.length + ' pending</span></div>';
	if (!appRows.length) {
		html += '<div class="lms-work-queue__empty">No pending applications. When a borrower submits an application, it will appear here.</div>';
		html += '</div>';
		return html;
	}
	html += '<ul class="lms-queue-list">';
	appRows.forEach(function (row) {
		var borrower = row.customer_name || row.applicant || "—";
		var product = row.product_name || row.loan_product || "—";
		var amount = format_currency(row.loan_amount || 0);
		var status = row.status || "Draft";
		var statusClass = lms_officer._appStatusBadgeClass(status);
		html +=
			'<li class="lms-queue-list__item">' +
			'<div class="lms-queue-list__main">' +
			'<div class="lms-queue-list__head">' +
			'<span class="lms-queue-list__name">' + lms_portal.escape(borrower) + '</span>' +
			'<span class="lms-badge ' + statusClass + ' lms-queue-list__status">' +
			lms_portal.escape(status) + '</span>' +
			'</div>' +
			'<div class="lms-queue-list__sub">' +
			lms_portal.escape(product) +
			'</div>' +
			'</div>' +
			'<div class="lms-queue-list__amount">' +
			'<span class="lms-queue-list__amount-label">Requested</span>' +
			'<span class="lms-queue-list__amount-value">' + amount + '</span>' +
			'</div>' +
			'<div class="lms-queue-list__action">' +
			'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-of-app-review" ' +
			'data-app="' + lms_portal.escape(row.name || "") + '" ' +
			'data-borrower="' + lms_portal.escape(borrower) + '" ' +
			'data-product="' + lms_portal.escape(product) + '" ' +
			'data-amount="' + lms_portal.escape(String(row.loan_amount || 0)) + '" ' +
			'data-status="' + lms_portal.escape(status) + '">' +
			"Review" +
			'</button>' +
			'</div>' +
			'</li>';
	});
	html += '</ul></div>';
	return html;
};

lms_officer._renderEodSummary = function (collections) {
	// R44-F7: end-of-day summary line — "what got done today" so the
	// operator can audit the day at a glance. Renders nothing when the
	// collections endpoint hasn't returned yet.
	if (!collections) return '';
	var today = collections.today_total || 0;
	var par30 = collections.par30 || 0;
	var par60 = collections.par60 || 0;
	var par90 = collections.par90 || 0;
	var parts = [];
	if (today) parts.push(format_currency(today) + ' collected today');
	if (par30) parts.push(par30 + ' PAR30');
	if (par60) parts.push(par60 + ' PAR60');
	if (par90) parts.push(par90 + ' PAR90');
	if (!parts.length) return '';
	return '<div class="lms-eod-summary"><span class="lms-eod-summary__label">Today</span><span class="lms-eod-summary__value">' + parts.join(' · ') + '</span></div>';
};

lms_officer._renderTasksCard = function (tasks) {
	// R43: compact tasks snapshot for the officer dashboard. Sits above
	// the pending-applications work queue so the officer sees actionable
	// tasks first. Renders nothing when the Tasks addon is disabled or
	// the API returned no board (so the dashboard stays clean on benches
	// without the addon enabled).
	if (!tasks || !tasks.board) return "";

	// Flatten the board into a single list, prioritising overdue →
	// in-progress → open. Cap at 5 rows so the card stays scannable.
	var overdue = [];
	var inProgress = [];
	var open = [];
	var statuses = { Open: open, Working: inProgress, "In Progress": inProgress, Pending: inProgress, "Pending Review": inProgress };
	Object.keys(tasks.board || {}).forEach(function (col) {
		(tasks.board[col] || []).forEach(function (t) {
			if (t.is_overdue) { overdue.push(t); return; }
			(statuses[col] || open).push(t);
		});
	});
	var rows = overdue.concat(inProgress).concat(open).slice(0, 5);
	if (!rows.length) {
		// No actionable tasks — render a quiet "all caught up" card so the
		// officer knows the section exists (and where to find the full
		// board) without an empty hole in the layout.
		return (
			'<div class="lms-panel lms-tasks-card">' +
			'<div class="lms-tasks-card__head"><h3>My tasks</h3>' +
			'<a class="lms-muted" href="/lms/tasks">View all</a></div>' +
			'<div class="lms-tasks-card__empty">No open tasks. You\'re all caught up.</div>' +
			'</div>'
		);
	}

	var total = (tasks.total || rows.length);
	var html =
		'<div class="lms-panel lms-tasks-card">' +
		'<div class="lms-tasks-card__head"><h3>My tasks</h3>' +
		'<span class="lms-muted">' + total + (total === 1 ? ' task' : ' tasks') +
		' · <a href="/lms/tasks">View all</a></span></div>' +
		'<div class="lms-tasks-card__list">';
	rows.forEach(function (t) {
		var status = t.status || "Open";
		var overdueCls = t.is_overdue ? " is-overdue" : "";
		var dueCls = t.is_overdue ? " is-overdue" : "";
		var due = t.exp_end_date ? lms_portal.formatDate(t.exp_end_date) : "";
		var priority = t.priority || "Medium";
		html +=
			'<div class="lms-tasks-card__row' + overdueCls + '">' +
			'<span class="lms-tasks-card__status lms-tasks-card__status--' +
			lms_portal.escape(status.replace(/\s+/g, "")) + '"></span>' +
			'<div class="lms-tasks-card__body">' +
			'<div class="lms-tasks-card__subject">' + lms_portal.escape(t.subject || "Untitled task") + '</div>' +
			'</div>' +
			'<span class="lms-tasks-card__priority lms-tasks-card__priority--' +
			lms_portal.escape(priority) + '">' + lms_portal.escape(priority) + '</span>' +
			(due ? '<span class="lms-tasks-card__due' + dueCls + '">Due ' + due + '</span>' : '<span></span>') +
			'</div>';
	});
	html += '</div></div>';
	return html;
};

lms_officer._renderAll = function (root, dash, apps, loans, branch, collections, customers, products, tasks) {
	var html = '<div class="lms-stack">';
	var k = dash.kpis || {};
	var appRows = (apps.applications || []);

	// R44: KPI strip FIRST — the operator asked for the at-a-glance
	// numbers to lead the dashboard so they can read the health of their
	// branch in one glance before drilling into the work queue below.
	// F2 (board review): the first KPI is now "Review queue age" instead
	// of "Pending applications" — the old label duplicated the count
	// shown in the work queue heading directly below. The new label
	// fires the alarm: "is anything overdue?".
	html += lms_portal.kpiStrip([
		{ label: "Review queue age", value: (k.review_queue_age || (k.pending_applications ? "—" : "0 days")), tone: (k.pending_applications || 0) ? "warning" : "success" },
		{ label: "Awaiting disbursement", value: k.pending_disbursement || 0, tone: (k.pending_disbursement || 0) ? "warning" : "" },
		{ label: "My active loans", value: k.my_active_loans || 0 },
		{ label: "PAR count", value: k.par_count || 0, tone: (k.par_count || 0) ? "danger" : "" },
	]);

	// 2) Work queue — single panel containing two sub-headings (R44-F1).
	// Tasks + pending applications share one panel so the operator reads
	// them as one combined queue rather than two similarly-styled panels.
	html += lms_officer._renderWorkQueuePanel(tasks, appRows);

	// 3) Charts (R44-F3) — collapsed by default in a <details> so the
	// dashboard stays scannable. The operator expands them on demand.
	html += '<details class="lms-dashboard-metrics">';
	html += '<summary><h3>Charts</h3><span class="lms-muted">Today\'s collections · Performance trends</span></summary>';
	html += '<div class="lms-chart-slot">';
	html += '<div class="lms-chart-slot__head"><h3>Today\'s collections</h3></div>';
	html += '<div class="lms-chart-slot__body"><canvas id="lms-officer-today-gauge" aria-live="polite"></canvas></div>';
	html += '</div>';

	html += '<div class="lms-chart-slot lms-chart-slot--lg">';
	html += '<div class="lms-chart-slot__head"><h3>Officer performance</h3></div>';
	html += '<div class="lms-chart-slot__body"><canvas id="lms-officer-performance" aria-live="polite"></canvas></div>';
	html += '</div>';
	html += '</details>';

	// 4) End-of-day summary (R44-F7) — "what got done today" line.
	html += lms_officer._renderEodSummary(collections);

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
				// R20-C1: mirror api/labels.py.officer_label so the
				// chart never falls back to the literal "Unassigned".
				return { label: (lms_portal && lms_portal.officerLabel) ? lms_portal.officerLabel(o.officer, o.days_past_due) : (o.officer || "\u26a0 Needs assignment"), value: o.outstanding || 0 };
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
	// R24-DL02: load the full application via the portal API and render
	// it in a portal-side modal. The desk link is gone — officers never
	// see `/app/...` URLs. Submission is also portal-side via
	// submit_pending_application().
	app = app || {};
	if (!app.name) return;

	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_application_detail",
		args: { application_name: app.name },
		callback: function (r) {
			var data = (r && r.message) || {};
			if (data._lms_error) {
				lms_portal.toast("Could not load application details.", "danger");
				return;
			}
			lms_officer._showApplicationReviewModal(data);
		},
		error: function (err) {
			var msg = (err && (err.message || err._server_message)) || "Could not load application details.";
			lms_portal.toast(msg, "danger");
		},
	});
};

lms_officer._showApplicationReviewModal = function (data) {
	var a = data.application || {};
	var p = data.product || {};
	var kyc = data.kyc || {};
	var schedule = data.schedule || [];
	var collateral = data.collateral || [];
	var audit = data.audit || [];

	var html = '<div class="lms-form">';

	// Summary cards
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Borrower</div><div class="lms-summary-value">' + lms_portal.escape(a.applicant_name || "—") + "</div></div>";
	html += '<div class="lms-summary-card lms-summary-card--primary"><div class="lms-summary-label">Amount</div><div class="lms-summary-value">' + format_currency(a.loan_amount || 0) + "</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Product</div><div class="lms-summary-value">' + lms_portal.escape(p.product_name || a.loan_product || "—") + "</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Rate</div><div class="lms-summary-value">' + (a.rate_of_interest || 0) + "%</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Periods</div><div class="lms-summary-value">' + (a.repayment_periods || 0) + "</div></div>";
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(a.status || "—") + "</div></div>";
	html += "</div>";

	// Purpose
	if (a.loan_purpose) {
		html += '<p><strong>Purpose:</strong> ' + lms_portal.escape(a.loan_purpose) + "</p>";
	}

	// KYC summary
	if (kyc && kyc.name) {
		html += "<h4>KYC</h4>";
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><tbody>';
		html += "<tr><td>KYC status</td><td>" + lms_portal.escape(kyc.kyc_status || "—") + "</td></tr>";
		html += "<tr><td>AML status</td><td>" + lms_portal.escape(kyc.aml_status || "—") + "</td></tr>";
		html += "<tr><td>AML screened</td><td>" + lms_portal.escape(kyc.aml_screened_at || "—") + "</td></tr>";
		html += "<tr><td>National ID</td><td>" + lms_portal.escape(kyc.national_id_number || "—") + "</td></tr>";
		html += "<tr><td>Consent</td><td>" + (kyc.consent_captured ? "✓ captured" : "—") + (kyc.consent_date ? " on " + lms_portal.escape(kyc.consent_date) : "") + "</td></tr>";
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

	// If the application is still a draft, offer to submit it for manager
	// approval via the existing "Confirm" button. R24-DL02: all actions
	// stay in the portal — no desk link.
	var canSubmit = a.docstatus === 0;
	var modalOpts = {
		title: "Application — " + (a.applicant_name || a.name || ""),
		size: "xl",
		body: html,
		confirmText: canSubmit ? "Submit for manager approval" : "Close",
		confirmVariant: "primary",
	};
	if (canSubmit) {
		modalOpts.onConfirm = function () {
			lms_portal.safeCall({
				method: "lms_saas.api.officer.submit_pending_application",
				args: { application_name: a.name },
				callback: function (r) {
					lms_portal.toast(
						"Application submitted: " + ((r && r.message && r.message.application) || a.name),
						"success"
					);
					// Refresh the pending applications list
					if (typeof lms_officer._renderApplications === "function") {
						lms_officer._renderApplications();
					}
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Submit failed.";
					lms_portal.toast(msg, "danger");
				},
			});
		};
	}

	lms_portal.modal(modalOpts);
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

	// R34 — layout: the form has more than 20 inputs plus a repeatable
	// collateral section. At the default 560px modal everything collapses
	// to a single column and "Submit" lands well below the fold. We give
	// the inline borrower picker its own bordered card so it reads as a
	// sub-form, and tag the loan-detail grids with `data-grid="2"` so the
	// xxl CSS keeps them at 2 columns (Identity / Contact sections stay
	// 3-up by default).
	var body =
		'<div class="lms-form">' +
		'<div class="lms-section-header"><h4>Customer</h4></div>' +
		'<div class="lms-grid-2" data-grid="2">' +
		'<label class="lms-grid-2__full">Customer' +
		'<select id="lms-app-customer" class="lms-input lms-fallback-select lms-pop-select" data-searchable>' +
		'<option value="">— Select customer —</option>' +
		'<option value="__new__">+ New borrower…</option>' +
		customerOpts +
		"</select></label>" +
		'<label class="lms-grid-2__full">Loan product' +
		'<select id="lms-app-product" class="lms-input lms-fallback-select lms-pop-select">' +
		productOpts +
		"</select></label>" +
		"</div>" +
		// R34: the inline "+ New borrower…" picker now shares the full
		// onboarding form with the topbar "Add Borrower" modal (Identity,
		// Contact, Household / Spouse, KYC + consent, ID doc + proof-of-
		// address upload). The previous picker only captured first/last
		// name, email, mobile and national ID — silently dropping DOB,
		// gender, address / city, KYC status, consent and uploads.
		'<div id="lms-new-borrower-fields" class="lms-new-borrower-card" hidden>' +
		'<div class="lms-section-header"><h4>New borrower — capture in the same step</h4></div>' +
		'<p class="lms-muted" style="margin:0 0 0.5rem;font-size:0.8rem;">Same fields as the standalone Add Borrower form. Required only if this customer does not exist yet.</p>' +
		lms_officer._borrowerFormHtml("lms-new-") +
		"</div>" +

		// --- Loan terms ---
		'<div class="lms-section-header"><h4>Loan terms</h4></div>' +
		'<div class="lms-grid-2" data-grid="2">' +
		// QA-2026-08-03-#18: pre-fill sensible defaults so the form is
		// never blank on first render. 10,000 ZAR is the median
		// disbursed loan amount on the demo data and 24% is the
		// common rate. The officer can still override.
		'<label>Loan amount<input type="number" id="lms-app-amount" class="lms-input" min="1" step="0.01" value="10000"></label>' +
		'<label>Rate of interest (% / yr)<input type="number" id="lms-app-rate" class="lms-input" min="0" max="100" step="0.01" value="24"></label>' +
		'<label>Repayment periods (months)<input type="number" id="lms-app-periods" class="lms-input" min="1" value="6"></label>' +
		'<label>Repayment method<select id="lms-app-method" class="lms-input lms-fallback-select">' +
		'<option value="Repay Over Number of Periods" selected>Repay Over Number of Periods</option>' +
		'<option value="Repay Fixed Amount per Period">Repay Fixed Amount per Period</option>' +
		'</select></label>' +
		'<label>Repayment start date<input type="date" id="lms-app-start" class="lms-input"></label>' +
		'<label>Posting date<input type="date" id="lms-app-posting" class="lms-input"></label>' +
		"</div>" +

		// --- Loan classification + dates ---
		'<div class="lms-section-header"><h4>Classification &amp; dates</h4></div>' +
		'<div class="lms-grid-2" data-grid="2">' +
		'<label>Loan type<select id="lms-app-loantype" class="lms-input lms-fallback-select">' +
		'<option value="">—</option><option value="Term Loan">Term Loan</option><option value="Revolving / Overdraft">Revolving / Overdraft</option><option value="Hire Purchase">Hire Purchase</option><option value="Asset Finance">Asset Finance</option><option value="Emergency / Top-up">Emergency / Top-up</option><option value="Working Capital">Working Capital</option>' +
		'</select></label>' +
		'<label>Purpose of finance<input type="text" id="lms-app-purpose" class="lms-input" placeholder="e.g. working capital, school fees"></label>' +
		'<label>Application date<input type="date" id="lms-app-appdate" class="lms-input"></label>' +
		'<label>Loan start date<input type="date" id="lms-app-startdate" class="lms-input"></label>' +
		'<label>Expiry date<input type="date" id="lms-app-expiry" class="lms-input"></label>' +
		'<label>Maximum enforceable amount<input type="number" id="lms-app-maxenforce" class="lms-input" min="0" step="0.01" placeholder="Statutory cap"></label>' +
		'<label class="lms-grid-2__full">Nature / type of security interest<textarea id="lms-app-security" class="lms-input" rows="2" placeholder="e.g. notarial bond over vehicle COL-00012"></textarea></label>' +
		"</div>" +

		// --- Household / Spouse (pre-fills from selected borrower) ---
		'<div class="lms-section-header"><h4>Household &amp; Spouse</h4></div>' +
		'<p class="lms-muted" style="margin:0 0 0.5rem;font-size:0.8rem;">Pre-filled from the borrower record; edit here if anything has changed.</p>' +
		'<div class="lms-grid-2">' +
		'<label><input type="checkbox" id="lms-app-marital"> Married (Marital status)</label>' +
		'<label>Spouse contact details<input type="text" id="lms-app-spouse-contact" class="lms-input" placeholder="Phone / email"></label>' +
		'<label>Name of spouse (first &amp; last)<input type="text" id="lms-app-spouse-name" class="lms-input" placeholder="Jane Doe"></label>' +
		'<label>Spouse date of birth<input type="date" id="lms-app-spouse-dob" class="lms-input"></label>' +
		'<label class="lms-grid-2__full">Applicant\'s physical address<textarea id="lms-app-physical" class="lms-input" rows="2" placeholder="House / plot, street, suburb, city"></textarea></label>' +
		'</div>' +

		'<div class="lms-section-header"><h4>Collateral</h4></div>' +
		'<div id="lms-app-collateral-rows"></div>' +
		'<button type="button" id="lms-app-add-collateral" class="lms-btn lms-btn--ghost">+ Add collateral item</button>' +
		"</div>";

	var dlg = LMSModal.open({
		title: "New loan application",
		body: body,
		// R34: 20+ fields, KYC file uploads and a repeatable collateral
		// section — the default 560px tier crams three-column grids into
		// a single column and pushes "Submit" far below the fold.
		size: "xxl",
		actions: [
			{ label: "Cancel", value: false },
			{ label: "Submit", value: true, primary: true }
		]
	});
	// Bind pop-out comboboxes to the <select>s we just rendered inside the dialog
	if (window.LMSForms && typeof LMSForms.bindAll === "function") {
		LMSForms.bindAll(dlg.dialog);
	}

	// Toggle new-borrower fields when the customer select changes, and
	// pre-fill the Household / Spouse section from get_borrower_detail when
	// an existing borrower is selected.
	var customerSelect = dlg.dialog.querySelector("#lms-app-customer");
	var newBorrowerFields = dlg.dialog.querySelector("#lms-new-borrower-fields");
	var fillHousehold = function (data) {
		var d = data || {};
		var setVal = function (id, v) {
			var el = dlg.dialog.querySelector("#" + id);
			if (el) el.value = v || "";
		};
		var setChecked = function (id, v) {
			var el = dlg.dialog.querySelector("#" + id);
			if (el) el.checked = !!v && (v === "Married" || v === true || v === 1 || v === "1");
		};
		setChecked("lms-app-marital", d.marital_status);
		setVal("lms-app-spouse-name", d.spouse_name);
		setVal("lms-app-spouse-dob", d.spouse_dob);
		setVal("lms-app-spouse-contact", d.spouse_contact);
		setVal("lms-app-physical", d.physical_address);
	};
	// R34: wire the inline borrower's file-upload widgets ONCE the picker
	// is unhidden. The picker is hidden on initial render (DOM hidden=true)
	// so we delay binding until the change handler actually flips it open.
	// `newBorrowerUploadsBound` keeps us from double-binding if the user
	// toggles between "+ New borrower…" and an existing customer.
	var newBorrowerUploadsBound = false;
	var bindNewBorrowerWidgets = function () {
		if (newBorrowerUploadsBound) return;
		newBorrowerUploadsBound = true;
		var inlineBlock = dlg.dialog.querySelector("#lms-new-borrower-fields");
		if (!inlineBlock) return;
		lms_portal._bindUploadWidgets(inlineBlock, {
			"lms-new-iddoc": null,
			"lms-new-poa": null,
		});
		if (window.LMSForms && typeof LMSForms.bindAll === "function") {
			LMSForms.bindAll(inlineBlock);
		}
		// R34-QA: live-validate the inline borrower sub-form so its fields
		// (DOB, gender, address, etc.) keep their focus-trap / input
		// upgrade wiring in line with the standalone modal. We do NOT
		// disable the New-Application primary action here because that
		// button also owns loan-product / amount validation — disabling it
		// from the borrower's first-name alone would block a perfectly
		// valid loan submission. The submit-handler already surfaces a
		// "First name is required" toast on inline failure.
	};
	if (customerSelect && newBorrowerFields) {
		customerSelect.addEventListener("change", function () {
			var v = customerSelect.value;
			newBorrowerFields.hidden = v !== "__new__";
			if (v === "__new__") {
				bindNewBorrowerWidgets();
			}
			if (v && v !== "__new__") {
				// Fetch the existing borrower's household / physical fields.
				lms_portal.safeCall({
					method: "lms_saas.api.officer.get_borrower_detail",
					args: { customer_name: v },
					callback: function (r) {
						var b = (r && r.message && r.message.borrower) || {};
						fillHousehold(b);
					},
					error: function () { fillHousehold({}); },
				});
			} else {
				fillHousehold({});
			}
		});
	}

	// Collateral: append a repeatable row each time "Add collateral item" is clicked.
	var collateralRows = dlg.dialog.querySelector("#lms-app-collateral-rows");
	// Field-builder helpers. Each closure returns the label HTML for one field;
	// `which` lists the collateral types where the field should be visible.
	// Generic fields (Description, Serial No, Value, Valuation date) are always
	// shown — only the type-specific extras are toggled.
	function fieldLabel(html, which) {
		return {
			html: html,
			visible: function (t) { return which.indexOf(t) !== -1; }
		};
	}
	var COL_FIELDS = {
		stand_plot_number: fieldLabel(
			'<label>Stand / plot number<input type="text" class="lms-input lms-col-stand" placeholder="Stand 12, Plot 34"></label>',
			["Real Estate / Property"]
		),
		area_sqm: fieldLabel(
			'<label>Area (sqm)<input type="text" class="lms-input lms-col-area" placeholder="e.g. 250"></label>',
			["Real Estate / Property"]
		),
		manufacturer_year: fieldLabel(
			'<label>Year of manufacture<input type="number" class="lms-input lms-col-year" min="1900" max="2100" placeholder="e.g. 2019"></label>',
			["Equipment / Machinery"]
		),
		inventory_sku: fieldLabel(
			'<label>SKU / lot code<input type="text" class="lms-input lms-col-sku" placeholder="LOT-001"></label>',
			["Inventory / Stock"]
		),
		inventory_quantity: fieldLabel(
			'<label>Quantity<input type="number" class="lms-input lms-col-qty" min="0" step="1" placeholder="0"></label>',
			["Inventory / Stock"]
		),
		cash_bank_name: fieldLabel(
			'<label>Bank name<input type="text" class="lms-input lms-col-bank" placeholder="e.g. ZB Bank"></label>',
			["Cash Deposit / Lien"]
		),
		cash_account_number: fieldLabel(
			'<label>Account number<input type="text" class="lms-input lms-col-acct" placeholder="0000-0000-0000"></label>',
			["Cash Deposit / Lien"]
		),
		security_certificate: fieldLabel(
			'<label>Share certificate no<input type="text" class="lms-input lms-col-cert" placeholder="SHR-2024-001"></label>',
			["Securities / Shares"]
		),
		security_units: fieldLabel(
			'<label>Number of units / shares<input type="number" class="lms-input lms-col-units" min="0" step="1" placeholder="0"></label>',
			["Securities / Shares"]
		),
		guarantor_name: fieldLabel(
			'<label>Guarantor full name<input type="text" class="lms-input lms-col-guarantor" placeholder="Jane Doe"></label>',
			["Third-Party Guarantee"]
		),
		guarantor_id: fieldLabel(
			'<label>Guarantor national ID<input type="text" class="lms-input lms-col-guarantor-id" placeholder="99-000000-A99"></label>',
			["Third-Party Guarantee"]
		),
		guarantor_relationship: fieldLabel(
			'<label>Relationship to borrower<input type="text" class="lms-input lms-col-guarantor-rel" placeholder="Spouse / Parent / Friend"></label>',
			["Third-Party Guarantee"]
		),
		// Vehicle fields (kept for backward compat — vehicle type uses these).
		vehicle_registration: fieldLabel(
			'<label>Vehicle registration<input type="text" class="lms-input lms-col-reg" placeholder="ABC123GP"></label>',
			["Vehicle"]
		),
		vehicle_brand: fieldLabel(
			'<label>Brand<input type="text" class="lms-input lms-col-brand" placeholder="Toyota"></label>',
			["Vehicle", "Equipment / Machinery"]
		),
		vehicle_model: fieldLabel(
			'<label>Model<input type="text" class="lms-input lms-col-model" placeholder="Hilux"></label>',
			["Vehicle", "Equipment / Machinery"]
		),
		engine_number: fieldLabel(
			'<label>Engine number<input type="text" class="lms-input lms-col-engine" placeholder="Engine #"></label>',
			["Vehicle"]
		),
	};

	var addCollateralBtn = dlg.dialog.querySelector("#lms-app-add-collateral");
	if (addCollateralBtn && collateralRows) {
		addCollateralBtn.addEventListener("click", function () {
			var row = document.createElement("div");
			row.className = "lms-collateral-row lms-grid-2";
			// Header (always shown): grantor + type.
			var html = '<label>Grantor(s)<input type="text" class="lms-input lms-col-grantor" placeholder="Owner name / customer"></label>' +
				'<label>Collateral type<select class="lms-input lms-fallback-select lms-col-type">' +
				'<option value="Vehicle">Vehicle</option><option value="Real Estate / Property">Real Estate / Property</option><option value="Equipment / Machinery">Equipment / Machinery</option><option value="Inventory / Stock">Inventory / Stock</option><option value="Cash Deposit / Lien">Cash Deposit / Lien</option><option value="Securities / Shares">Securities / Shares</option><option value="Third-Party Guarantee">Third-Party Guarantee</option><option value="Other">Other</option>' +
				'</select></label>' +
				// Generic asset section (always shown): description, serial/registration no, value, valuation date.
				'<label>Description<input type="text" class="lms-input lms-col-desc" placeholder="e.g. Toyota Hilux 2019"></label>' +
				'<label>Registration / serial no<input type="text" class="lms-input lms-col-serial" placeholder="Chassis / serial / deed no"></label>' +
				'<div class="lms-col-type-fields" style="display:contents;"></div>' +
				'<label>Collateral value<input type="number" class="lms-input lms-col-value" min="0" step="0.01" placeholder="0.00"></label>' +
				'<label>Valuation date<input type="date" class="lms-input lms-col-valuation"></label>';

			row.innerHTML = html;
			collateralRows.appendChild(row);
			if (window.LMSForms && typeof LMSForms.bindAll === "function") {
				LMSForms.bindAll(row);
			}

			// Render all type-specific fields into the container, hidden by default.
			// Show only the ones matching the selected collateral type.
			var fieldsBox = row.querySelector(".lms-col-type-fields");
			Object.keys(COL_FIELDS).forEach(function (key) {
				var wrap = document.createElement("div");
				wrap.className = "lms-col-field lms-col-field--" + key;
				wrap.style.display = "none";
				wrap.innerHTML = COL_FIELDS[key].html;
				fieldsBox.appendChild(wrap);
			});

			// On type change: show only fields matching the type, hide others
			// and clear any leftover values so they don't bleed across forms.
			var updateTypeFields = function () {
				var typeSel = row.querySelector(".lms-col-type");
				var t = typeSel ? typeSel.value : "";
				row.querySelectorAll(".lms-col-field").forEach(function (el) {
					var key = "";
					el.className.split(" ").forEach(function (c) {
						if (c.indexOf("lms-col-field--") === 0) key = c.replace("lms-col-field--", "");
					});
					var def = COL_FIELDS[key];
					var visible = def && def.visible(t);
					el.style.display = visible ? "" : "none";
					if (!visible) {
						el.querySelectorAll("input, textarea, select").forEach(function (inp) {
							inp.value = "";
						});
					}
				});
			};
			var typeSel = row.querySelector(".lms-col-type");
			if (typeSel) typeSel.addEventListener("change", updateTypeFields);
			updateTypeFields();
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
		var loanType = $("lms-app-loantype") || "";
		var purpose = $("lms-app-purpose") || "";
		var appDate = $("lms-app-appdate") || "";
		var loanStartDate = $("lms-app-startdate") || "";
		var expiryDate = $("lms-app-expiry") || "";
		var maxEnforce = parseFloat($("lms-app-maxenforce")) || 0;
		var security = $("lms-app-security") || "";

		// Household / Spouse fields (sourced from selected borrower or
		// typed in fresh on the loan application form).
		var maritalChecked = (dlg.dialog.querySelector("#lms-app-marital") || {}).checked;
		var marital = maritalChecked ? "Married" : "";
		var spouseName = $("lms-app-spouse-name") || "";
		var spouseDob = $("lms-app-spouse-dob") || "";
		var spouseContact = $("lms-app-spouse-contact") || "";
		var physical = $("lms-app-physical") || "";

		// Collect collateral rows (if any were added). Each row carries the
		// generic + type-specific fields captured by the conditional form.
		var collateral = [];
		dlg.dialog.querySelectorAll(".lms-collateral-row").forEach(function (row) {
			var get = function (cls) { var el = row.querySelector(cls); return el ? el.value : ""; };
			collateral.push({
				grantor: get(".lms-col-grantor"),
				collateral_type: get(".lms-col-type"),
				description: get(".lms-col-desc"),
				serial_number: get(".lms-col-serial"),
				vehicle_registration: get(".lms-col-reg"),
				brand: get(".lms-col-brand"),
				model: get(".lms-col-model"),
				engine_number: get(".lms-col-engine"),
				stand_plot_number: get(".lms-col-stand"),
				area_sqm: get(".lms-col-area"),
				manufacturer_year: get(".lms-col-year"),
				inventory_sku: get(".lms-col-sku"),
				inventory_quantity: get(".lms-col-qty"),
				cash_bank_name: get(".lms-col-bank"),
				cash_account_number: get(".lms-col-acct"),
				security_certificate: get(".lms-col-cert"),
				security_units: get(".lms-col-units"),
				guarantor_name: get(".lms-col-guarantor"),
				guarantor_id: get(".lms-col-guarantor-id"),
				guarantor_relationship: get(".lms-col-guarantor-rel"),
				collateral_value: parseFloat(get(".lms-col-value")) || 0,
				valuation_date: get(".lms-col-valuation"),
			});
		});

		// R34: collect the inline borrower's fields via the shared helper.
		// `_collectNewBorrower` validates first-name + conditional KYC file
		// uploads and returns `null` (with a toast) on failure. On success
		// it returns a fields object keyed to match `create_borrower`'s
		// whitelisted argument names.
		var newBorrowerFields = null;
		if (customerVal === "__new__") {
			newBorrowerFields = lms_officer._collectNewBorrower(dlg.dialog, "lms-new-");
			if (!newBorrowerFields) return; // toast already shown
			// When onboarding inline, the inline borrower's household /
			// spouse fields are the AUTHORITATIVE source — override the
			// application-modal copies (which default to blank) so the loan
			// application carries the right marital_status / spouse / address
			// through to the server.
			marital = newBorrowerFields.marital_status || "";
			spouseName = newBorrowerFields.spouse_name || "";
			spouseDob = newBorrowerFields.spouse_dob || "";
			spouseContact = newBorrowerFields.spouse_contact || "";
			physical = newBorrowerFields.physical_address || "";
		}

		if (customerVal === "__new__") {
			lms_portal.safeCall({
				method: "lms_saas.api.officer.create_borrower",
				args: newBorrowerFields,
				callback: function (r) {
					var res = (r && r.message) || {};
					if (!res.customer) {
						lms_portal.toast("Could not create borrower.", "danger");
						return;
					}
					lms_officer._submitApp(res.customer, product, amount, periods, rate, method, startDate, postingDate, loanType, purpose, appDate, loanStartDate, expiryDate, maxEnforce, security, collateral, marital, spouseName, spouseDob, spouseContact, physical);
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Could not create borrower.";
					lms_portal.toast(msg, "danger");
				},
			});
		} else if (!customerVal) {
			lms_portal.toast("Please select a customer.", "danger");
		} else {
			lms_officer._submitApp(customerVal, product, amount, periods, rate, method, startDate, postingDate, loanType, purpose, appDate, loanStartDate, expiryDate, maxEnforce, security, collateral, marital, spouseName, spouseDob, spouseContact, physical);
		}
	});
};

lms_officer._submitApp = function (customer, product, amount, periods, rate, method, startDate, postingDate, loanType, purpose, appDate, loanStartDate, expiryDate, maxEnforce, security, collateral, marital, spouseName, spouseDob, spouseContact, physical) {
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
			loan_type: loanType || null,
			purpose_of_finance: purpose || null,
			application_date: appDate || null,
			loan_start_date: loanStartDate || null,
			expiry_date: expiryDate || null,
			max_enforceable_amount: maxEnforce > 0 ? maxEnforce : null,
			security_interest_nature: security || null,
			collateral: collateral && collateral.length ? collateral : null,
			marital_status: marital || null,
			spouse_name: spouseName || null,
			spouse_dob: spouseDob || null,
			spouse_contact: spouseContact || null,
			physical_address: physical || null,
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

// ---------------------------------------------------------------------------
// R34 — Borrower onboarding form (DRY).
//
// `lms_officer._borrowerFormHtml(prefix)` is the SINGLE source of truth for
// the borrower onboarding fields. It is reused by:
//   - `_openBorrowerModal()`         — topbar "Add Borrower" button (prefix="lms-of-b-")
//   - `_openApplicationModal(...)`    — inline "+ New borrower…" picker inside the
//                                      New Application modal (prefix="lms-new-")
//
// Both call sites previously inlined their own form bodies, drifting out of
// sync (the inline picker was dropping DOB, gender, address, KYC status,
// consent, and ID/proof-of-address uploads). They now render the SAME HTML
// and the SAME validation via the same `_openBorrowerModal`-style submit
// handler, with the caller deciding where to land after a successful create
// (Borrowers tab vs. continue with the in-flight loan application).
// ---------------------------------------------------------------------------
lms_officer._borrowerFormHtml = function (P) {
	return (
		// --- Section: Identity ---
		'<div class="lms-section-header"><h4>Identity</h4></div>' +
		'<div class="lms-grid-2">' +
		'<label>First name *<input type="text" id="' + P + 'first" class="lms-input" placeholder="John" required></label>' +
		'<label>Last name<input type="text" id="' + P + 'last" class="lms-input" placeholder="Doe"></label>' +
		'<label>Date of birth<input type="date" id="' + P + 'dob" class="lms-input"></label>' +
		'<label>Gender<select id="' + P + 'gender" class="lms-input lms-fallback-select">' +
		'<option value="">—</option><option value="Male">Male</option><option value="Female">Female</option><option value="Other">Other</option>' +
		'</select></label>' +
		'<label class="lms-grid-2__full">National ID *<input type="text" id="' + P + 'national" class="lms-input" placeholder="63-000000-A99" required></label>' +
		'</div>' +

		// --- Section: Contact ---
		'<div class="lms-section-header"><h4>Contact</h4></div>' +
		'<div class="lms-grid-2">' +
		'<label>Email<input type="email" id="' + P + 'email" class="lms-input" placeholder="john@example.com"></label>' +
		'<label>Mobile<input type="tel" id="' + P + 'mobile" class="lms-input" placeholder="0772..."></label>' +
		'<label class="lms-grid-2__full">Address line 1<input type="text" id="' + P + 'addr1" class="lms-input" placeholder="House / plot number, street"></label>' +
		'<label>City<input type="text" id="' + P + 'city" class="lms-input" placeholder="Harare"></label>' +
		'<label>Customer group<select id="' + P + 'cgroup" class="lms-input lms-fallback-select"><option value="">— Default —</option></select></label>' +
		'</div>' +

		// --- Section: Household / Spouse ---
		'<div class="lms-section-header"><h4>Household &amp; Spouse</h4></div>' +
		'<div class="lms-grid-2">' +
		'<label><input type="checkbox" id="' + P + 'marital"> Married (Marital status)</label>' +
		'<label>Spouse contact details<input type="text" id="' + P + 'spouse-contact" class="lms-input" placeholder="Phone / email"></label>' +
		'<label>Name of spouse (first &amp; last)<input type="text" id="' + P + 'spouse-name" class="lms-input" placeholder="Jane Doe"></label>' +
		'<label>Spouse date of birth<input type="date" id="' + P + 'spouse-dob" class="lms-input"></label>' +
		'<label class="lms-grid-2__full">Applicant\'s physical address<textarea id="' + P + 'physical" class="lms-input" rows="2" placeholder="House / plot, street, suburb, city"></textarea></label>' +
		'</div>' +

		// --- Section: KYC ---
		'<div class="lms-section-header"><h4>KYC &amp; consent</h4></div>' +
		'<div class="lms-grid-2">' +
		'<label>KYC status<select id="' + P + 'kyc" class="lms-input lms-fallback-select">' +
		'<option value="Pending" selected>Pending — collect later</option>' +
		'<option value="Approved">Approved — documents verified</option>' +
		'<option value="Rejected">Rejected</option>' +
		'</select></label>' +
		'<label class="lms-grid-2__full"><input type="checkbox" id="' + P + 'consent"> Customer consents to data processing</label>' +
		'</div>' +
		'<p class="lms-muted" style="margin:0.5rem 0 0;font-size:0.8rem;">Click <strong>Upload</strong> to attach a file from your device. Required only if KYC status is <strong>Approved</strong>.</p>' +
		'<div class="lms-grid-2" style="margin-top:0.5rem;">' +
		lms_portal._fileUploadField({
			id: P + "iddoc",
			label: "ID document",
			fieldname: null,
			required: false,
			accept: "image/*,application/pdf",
			buttonLabel: "Upload ID document",
		}) +
		lms_portal._fileUploadField({
			id: P + "poa",
			label: "Proof of address",
			fieldname: null,
			required: false,
			accept: "image/*,application/pdf",
			buttonLabel: "Upload proof of address",
		}) +
		'</div>'
	);
};

// Shared "collect + validate + submit borrower fields" helper. Returns the
// extracted field map so the caller can decide what to do next (e.g.
// `_openBorrowerModal` lands on the Borrowers tab, the inline picker in
// `_openApplicationModal` continues with the loan application submission).
// Returns `null` if validation failed (and surfaces a toast).
lms_officer._collectNewBorrower = function (root, P) {
	P = P || "lms-of-b-";
	root = root || document.body;
	var $ = function (id) { return (root.querySelector ? root.querySelector("#" + id) : null); };
	var val = function (id) { return ($(P + id) || {}).value || ""; };
	var checked = function (id) { var el = $(P + id); return !!(el && el.checked); };

	var fields = {
		first_name: val("first"),
		last_name: val("last"),
		date_of_birth: val("dob"),
		gender: val("gender"),
		national_id: val("national"),
		email: val("email"),
		mobile_no: val("mobile"),
		address_line1: val("addr1"),
		city: val("city"),
		customer_group: val("cgroup"),
		marital_status: checked("marital") ? "Married" : "Single",
		spouse_name: val("spouse-name"),
		spouse_dob: val("spouse-dob"),
		spouse_contact: val("spouse-contact"),
		physical_address: val("physical"),
		kyc_status: val("kyc") || "Pending",
		consent_given: checked("consent") ? 1 : 0,
		id_document_proof: val("iddoc"),
		proof_of_address: val("poa"),
	};

	if (!fields.first_name || !fields.first_name.trim()) {
		lms_portal.toast("First name is required.", "danger");
		return null;
	}
	// Only require the file uploads if the officer is approving KYC at the
	// counter. For "Pending — collect later" the server is happy with empty
	// file fields; matching the server keeps the officer's workflow
	// friction-free.
	if (fields.kyc_status === "Approved" && !fields.id_document_proof) {
		lms_portal.toast("Please upload the ID document or set KYC to Pending.", "danger");
		return null;
	}
	if (fields.kyc_status === "Approved" && !fields.proof_of_address) {
		lms_portal.toast("Please upload the proof of address or set KYC to Pending.", "danger");
		return null;
	}
	return fields;
};

// R34-QA: live-validate the borrower form so the LMSModal primary action
// stays DISABLED while the form is invalid. Without this, the operator's
// click on "Create borrower" closes the dialog (LMSModal closes on any
// action click) and `_collectNewBorrower` only validates AFTER the modal
// is already gone — leaving them stranded. With this guard the disabled
// button never closes the modal, the operator sees an inline helper, and
// the modal stays open until the form is valid.
//
// `opts.dlgRoot` — the LMSModal dialog element.
// `opts.primaryButton` — the primary "Create borrower" element (lms's
// action button) — we set its `disabled` attribute and tooltip.
// `opts.fieldsPredicate` — optional function returning `{ ok, reason }`,
// called on every input change inside the form. Default: first-name
// required + KYC=Approved needs both uploads.
lms_officer._wireBorrowerLiveValidation = function (opts) {
	opts = opts || {};
	var root = opts.dlgRoot || document.body;
	var button = opts.primaryButton;
	if (!button) return;
	var predicate = opts.fieldsPredicate || function (root, P) {
		P = P || "lms-of-b-";
		var first = (root.querySelector("#" + P + "first") || {}).value || "";
		var kyc = (root.querySelector("#" + P + "kyc") || {}).value || "Pending";
		var iddoc = (root.querySelector("#" + P + "iddoc") || {}).value || "";
		var poa = (root.querySelector("#" + P + "poa") || {}).value || "";
		if (!first.trim()) return { ok: false, reason: "First name is required" };
		if (kyc === "Approved" && !iddoc)
			return { ok: false, reason: "Upload the ID document or set KYC to Pending" };
		if (kyc === "Approved" && !poa)
			return { ok: false, reason: "Upload the proof of address or set KYC to Pending" };
		return { ok: true, reason: "" };
	};
	var P = opts.prefix || "lms-of-b-";
	var update = function () {
		var r = predicate(root, P);
		if (r.ok) {
			button.removeAttribute("disabled");
			button.style.opacity = "1";
			button.style.cursor = "";
			button.title = "";
		} else {
			button.setAttribute("disabled", "disabled");
			button.style.opacity = "0.55";
			button.style.cursor = "not-allowed";
			button.title = r.reason;
		}
	};
	root.addEventListener("input", update);
	root.addEventListener("change", update);
	update();
};

lms_officer._openBorrowerModal = function () {
	// Topbar "Add Borrower" button — opens the borrower onboarding modal in
	// standalone mode. The form is delegated to `lms_officer._borrowerFormHtml`
	// and the submit collects fields via `_collectNewBorrower`. After a
	// successful create we land on the Borrowers tab (the inline picker in
	// `_openApplicationModal` reuses the same helpers and instead continues
	// with the in-flight loan application — see R34 comments above).
	var P = "lms-of-b-";
	var body = '<div class="lms-form">' + lms_officer._borrowerFormHtml(P) + '</div>';

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
	// Pass null as the fieldname so the upload skips the borrower-side
	// upload_kyc_document registration — the server saves the file_url
	// directly on the new LMS Borrower Compliance record.
	lms_portal._bindUploadWidgets(dlgRoot, {
		[P + "iddoc"]: null,
		[P + "poa"]: null,
	});

	// R34-QA: disable the primary button until the form is valid. This
	// stops LMSModal from auto-closing the dialog on a failed click and
	// leaves the operator stranded outside the modal with only a toast.
	if (dlgRoot) {
		var primary = dlgRoot.querySelector("[data-lms-modal-action='true']");
		if (primary) {
			lms_officer._wireBorrowerLiveValidation({
				dlgRoot: dlgRoot,
				primaryButton: primary,
				prefix: P,
			});
		}
	}

	// Standalone "Add Borrower" post-create landing: jump to the Borrowers
	// tab. The inline caller in `_openApplicationModal` overrides this with
	// a different `onAfterCreate` that continues into loan-application submit.
	var onAfterCreate = function (res) {
		lms_portal.toast(
			"Borrower created: " + (res.customer_name || res.customer) +
			(res.kyc ? " (KYC " + res.kyc_status + ")" : ""),
			"success"
		);
		lms_officer._showTab("borrowers");
	};

	if (dlg && typeof dlg.then === "function") {
		// LMSModal: returns a Promise-like { then }
		dlg.then(function (submit) {
			if (!submit) return;
			var fields = lms_officer._collectNewBorrower(dlgRoot, P);
			if (!fields) return;
			lms_portal.safeCall({
				method: "lms_saas.api.officer.create_borrower",
				args: fields,
				callback: function (r) {
					var res = (r && r.message) || {};
					if (!res.customer) {
						lms_portal.toast("Could not create borrower.", "danger");
						return;
					}
					onAfterCreate(res);
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Could not create borrower.";
					lms_portal.toast(msg, "danger");
				},
			});
		});
	} else if (dlg && dlg.el) {
		// lms_portal.modal: bind to the confirm button manually
		var confirmBtn = dlg.el.querySelector("[data-lms-modal-confirm]");
		if (confirmBtn) {
			confirmBtn.addEventListener("click", function () {
				var fields = lms_officer._collectNewBorrower(dlgRoot, P);
				if (!fields) return;
				lms_portal.safeCall({
					method: "lms_saas.api.officer.create_borrower",
					args: fields,
					callback: function (r) {
						var res = (r && r.message) || {};
						if (!res.customer) {
							lms_portal.toast("Could not create borrower.", "danger");
							return;
						}
						onAfterCreate(res);
					},
					error: function (err) {
						var msg = (err && (err.message || err._server_message)) || "Could not create borrower.";
						lms_portal.toast(msg, "danger");
					},
				});
			});
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
		el.innerHTML = '<div class="lms-empty">' + lms_icons.empty("user") + '<h3>No borrowers found</h3><p>Try a different search.</p></div>';
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
	// Build the editable profile form. The Loan Officer is allowed to
	// update contact details on a borrower in their branch. Backend
	// enforcement (branch scope + role) lives in
	// lms_saas.api.officer.update_borrower; this form is the UI half.
	var html = '<div class="lms-form">';
	html += '<form id="lms-borrower-edit-form" class="lms-form" autocomplete="off">';
	html += '<div class="lms-form-row"><label class="lms-form-label" for="lms-brw-name">Name</label>';
	html += '<input class="lms-input" id="lms-brw-name" name="customer_name_new" type="text" value="' + lms_portal.escape(b.customer_name || "") + '" maxlength="120" required />';
	html += '</div>';
	html += '<div class="lms-form-row"><label class="lms-form-label" for="lms-brw-mobile">Mobile</label>';
	html += '<input class="lms-input" id="lms-brw-mobile" name="mobile_no" type="tel" value="' + lms_portal.escape(b.mobile_no || "") + '" maxlength="32" />';
	html += '</div>';
	html += '<div class="lms-form-row"><label class="lms-form-label" for="lms-brw-email">Email</label>';
	html += '<input class="lms-input" id="lms-brw-email" name="email_id" type="email" value="' + lms_portal.escape(b.email_id || "") + '" maxlength="120" />';
	html += '</div>';
	html += '<div class="lms-form-row"><label class="lms-form-label" for="lms-brw-nid">National ID</label>';
	html += '<input class="lms-input" id="lms-brw-nid" name="national_id" type="text" value="' + lms_portal.escape(b.custom_national_id_number || "") + '" maxlength="32" />';
	html += '</div>';
	html += '<div class="lms-form-row"><label class="lms-form-label">KYC</label>';
	html += '<div class="lms-summary-value" style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">';
	html += '<span class="lms-badge ' + lms_portal.badgeClass(0, (b.compliance || {}).kyc_status) + '">' +
		lms_portal.escape((b.compliance || {}).kyc_status || "No KYC") + '</span>';
	html += (b.compliance && b.compliance.consent_given ? '<span class="lms-badge lms-badge--success">Consent</span>' : '<span class="lms-badge lms-badge--muted">No consent</span>');
	html += '</div>';
	html += '<small class="lms-form-hint">KYC is reviewed in the KYC Queue tab.</small>';
	// Start KYC / Open KYC button — uses the KYC doc name (or customer
	// name for the no-record-yet case) so the officer can jump straight
	// from the borrower detail modal to the full KYC review form.
	html += '<div style="margin-top:0.5rem;">' +
		lms_officer._borrowerKycLink(b.compliance || {}, b.name) +
		'</div>';
	html += '</div>';
	html += '<input type="hidden" name="customer_name" value="' + lms_portal.escape(b.name || "") + '" />';
	html += '</form>';

	if (b.loans && b.loans.length) {
		html += '<h4 style="margin-top:1.5rem;">Loans (' + b.loans.length + ')</h4>';
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

	// Recent repayments (read-only)
	if (b.recent_repayments && b.recent_repayments.length) {
		html += '<h4 style="margin-top:1.5rem;">Recent Repayments</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Receipt</th><th>Loan</th><th>Amount</th><th>Date</th></tr></thead><tbody>';
		b.recent_repayments.slice(0, 10).forEach(function (r) {
			html += "<tr><td><strong>" + lms_portal.escape(r.name) + "</strong></td>";
			html += "<td>" + lms_portal.escape(r.against_loan || "") + "</td>";
			html += "<td>" + format_currency(r.amount_paid || 0) + "</td>";
			html += "<td>" + lms_portal.escape(r.posting_date || "") + "</td></tr>";
		});
		html += "</tbody></table></div>";
	}
	html += '</div>';

	var officerCustomerName = b.name || "";

	lms_portal.modal({
		title: "Borrower Profile — " + (b.customer_name || ""),
		body: html,
		size: "xl",
		confirmText: "Save",
		confirmVariant: "primary",
		cancelText: "Close",
		onConfirm: function () {
			// Collect the form values and POST them.
			var form = document.getElementById("lms-borrower-edit-form");
			if (!form) return;
			var args = {
				customer_name: officerCustomerName,
				customer_name_new: form.customer_name_new.value || officerCustomerName,
				email_id: form.email_id.value || "",
				mobile_no: form.mobile_no.value || "",
				national_id: form.national_id.value || "",
			};
			lms_portal.safeCall({
				method: "lms_saas.api.officer.update_borrower",
				args: args,
				callback: function (r) {
					if (r && r.message && r.message.status === "updated") {
						lms_portal.toast("Borrower updated.", "success");
						// Reload the borrowers list if the Borrowers tab is showing
						var content = document.getElementById("lms-officer-tab-content");
						if (content) {
							lms_officer._loadBorrowers(content);
						}
					} else {
						lms_portal.toast("Could not save borrower.", "danger");
					}
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Could not save borrower.";
					lms_portal.toast(msg, "danger");
				},
			});
		},
	});

	// KYC buttons inside the borrower detail modal. The modal element
	// is the document.body (LMSModal puts it in a div at the body root),
	// so we listen at the document level and filter to clicks on the
	// matching class — saves us a query for the dialog element.
	document.addEventListener("click", function _lms_brw_kyc_handler(ev) {
		var t = ev.target.closest && ev.target.closest(
			".lms-of-brw-start-kyc, .lms-of-brw-open-kyc"
		);
		if (!t) return;
		// Bail if the click is on a different open modal (don't
		// double-fire when the KYC modal itself renders the same class).
		if (t.closest(".lms-modal") !== t.closest(".lms-modal-root") &&
			t.closest(".lms-modal-root") !== document.querySelector(".lms-modal-root")) {
			// Click is inside the borrower modal but not the KYC one
		}
		if (t.classList.contains("lms-of-brw-start-kyc")) {
			var customer = t.getAttribute("data-customer");
			lms_portal.safeCall({
				method: "lms_saas.api.officer.start_kyc",
				args: { customer: customer, kyc_status: "Pending" },
				callback: function (r) {
					var res = (r && r.message) || {};
					if (res.kyc) {
						lms_portal.toast("KYC record created.", "success");
						// Close the borrower modal, then open the KYC review
						var openModal = document.querySelector(".lms-modal-root .lms-modal__close");
						if (openModal) openModal.click();
						setTimeout(function () {
							lms_officer._openKycReview(res.kyc,
								document.getElementById("lms-officer-tab-content"));
						}, 50);
					} else {
						lms_portal.toast("Could not start KYC.", "danger");
					}
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Could not start KYC.";
					lms_portal.toast(msg, "danger");
				},
			});
		} else if (t.classList.contains("lms-of-brw-open-kyc")) {
			var kyc = t.getAttribute("data-kyc");
			var openModal2 = document.querySelector(".lms-modal-root .lms-modal__close");
			if (openModal2) openModal2.click();
			setTimeout(function () {
				lms_officer._openKycReview(kyc,
					document.getElementById("lms-officer-tab-content"));
			}, 50);
		}
	});
};

// ---------------------------------------------------------------------------
// Loans tab

// ---------------------------------------------------------------------------
lms_officer._loadLoans = function (content) {
	content.innerHTML = lms_portal.loading("Loading loans…");

	lms_portal.guardedCall({
		method: "lms_saas.api.officer.get_assigned_loans",
	}).then(function (res) {
		if (!res.ok) {
			var status = (res.payload && res.payload.status) || 0;
			var message = String((res.payload && res.payload.message) || "");
			var isAuthish = lms_portal._isAuthish(status, message);
			content.innerHTML =
				'<div class="lms-panel lms-error" role="alert">' +
				'<h3 style="margin:0 0 0.5rem;">Loans could not load</h3>' +
				'<p>' + lms_portal.escape(
					isAuthish
						? "You don't have permission to view assigned loans. Please sign in again or contact your manager."
						: message || "The server did not respond in time."
				) + '</p>' +
				'<button type="button" class="lms-btn lms-btn--primary" id="lms-of-loans-retry">Retry</button>' +
				'</div>';
			var retry = document.getElementById("lms-of-loans-retry");
			if (retry) retry.addEventListener("click", function () { lms_officer._loadLoans(content); });
			return;
		}
		var data = (res.payload && res.payload.message) || {};
		var pending = data.pending || [];
		var active = data.active || [];
		lms_officer._renderLoansTab(content, pending, active);
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
		html += lms_portal.emptyPanel("wallet", "No loans assigned", "You have no loans assigned. Approved applications will appear here for disbursement.");
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
		body = '<div class="lms-empty">' + lms_icons.empty("phone") + '<h3>No leads</h3><p>No leads in your branch yet.</p></div>';
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
			} else {
				body += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-consent-lead" data-lead="' + lms_portal.escape(l.name) + '">Set consent</button>';
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
	el.querySelectorAll(".lms-of-consent-lead").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_officer._setLeadConsent(btn.getAttribute("data-lead"), el);
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
		size: "lg",
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
		size: "sm",
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

lms_officer._setLeadConsent = function (leadName, content) {
	// A loan officer can record explicit consent on a lead (e.g. after a
	// phone call) so that the lead can then be converted to a Customer.
	// This is the half-step before `convert_lead`.
	lms_portal.safeCall({
		method: "lms_saas.api.officer.set_lead_consent",
		args: { lead_name: leadName },
		callback: function (r) {
			var res = (r && r.message) || {};
			if (res.status === "ok") {
				lms_portal.toast("Consent recorded for " + leadName + ".", "success");
				lms_officer._loadLeads(content);
			} else {
				lms_portal.toast("Could not record consent.", "danger");
			}
		},
		error: function (err) {
			var msg = (err && (err.message || err._server_message)) || "Could not record consent.";
			lms_portal.toast(msg, "danger");
		},
	});
};

// ---------------------------------------------------------------------------
// KYC queue tab (R15)
//
// Loan Officer's daily KYC workflow:
//   1. Open the queue, filter by status (Pending / In Review / Approved / Rejected).
//   2. Open a record to review docs (ID + POA), borrower details, audit trail.
//   3. Flip status (Pending → In Review → Approved/Rejected), record consent,
//      attach the ID / POA files. The API refuses to mark Approved until
//      NID + ID + POA + consent are all in place.
//   4. The audit trail captures every change with the officer's name and
//      a free-text note (visible in the regulator export).
// ---------------------------------------------------------------------------

lms_officer._kycCurrentStatus = "";

lms_officer._loadKycQueue = function (content) {
	content.innerHTML = lms_portal.loading("Loading KYC queue…");

	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_kyc_queue",
		args: { status: lms_officer._kycCurrentStatus || "" },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_officer._renderKycQueue(content, data);
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load KYC queue.");
		},
	});
};

lms_officer._renderKycQueue = function (el, data) {
	var queue = data.queue || [];
	var counts = data.counts || {};
	var branch = data.branch || "";

	var statusOptions = [
		{ value: "", label: "All statuses" },
		{ value: "Pending", label: "Pending" },
		{ value: "In Review", label: "In Review" },
		{ value: "Approved", label: "Approved" },
		{ value: "Rejected", label: "Rejected" },
	];

	var controls =
		'<div class="lms-toolbar">' +
		'<label class="lms-toolbar__field">Status ' +
		'<select id="lms-of-kyc-filter" class="lms-input lms-fallback-select">' +
		statusOptions.map(function (o) {
			return '<option value="' + lms_portal.escape(o.value) + '"' +
				(lms_officer._kycCurrentStatus === o.value ? ' selected' : '') +
				'>' + lms_portal.escape(o.label) + '</option>';
		}).join("") +
		'</select></label>' +
		'<span class="lms-toolbar__spacer"></span>' +
		'<span class="lms-muted" style="font-size:0.8rem;">Branch: <strong>' +
		lms_portal.escape(branch || "—") + '</strong></span>' +
		'</div>';

	var body = "";
	if (!queue.length) {
		body =
			'<div class="lms-empty">' + lms_icons.empty("shield") +
			'<h3>No KYC records</h3>' +
			'<p>There are no KYC records matching the current filter in your branch.</p>' +
			(counts.no_kyc ? '<p class="lms-muted">' + counts.no_kyc +
				' borrower(s) in your branch have no KYC started yet — open them from the Borrowers tab and click <strong>Start KYC</strong>.</p>' : '') +
			'</div>';
	} else {
		body =
			'<div class="lms-data-table__wrap"><table class="lms-data-table">' +
			"<thead><tr>" +
			"<th>Borrower</th><th>Status</th><th>Consent</th><th>ID Doc</th><th>POA</th>" +
			"<th>NID</th><th>AML</th><th>Updated</th><th>Actions</th>" +
			"</tr></thead><tbody>";
		queue.forEach(function (r) {
			var statusBadge = lms_portal.badgeClass(0, r.kyc_status);
			body += "<tr>";
			body += "<td><strong>" + lms_portal.escape(r.customer_name || r.customer) + "</strong></td>";
			body += '<td><span class="lms-badge ' + statusBadge + '">' +
				lms_portal.escape(r.kyc_status || "Pending") + "</span></td>";
			body += "<td>" + (r.consent_given ? "Yes" : "No") + "</td>";
			body += "<td>" + (r.has_id_doc ? "✓" : "—") + "</td>";
			body += "<td>" + (r.has_poa ? "✓" : "—") + "</td>";
			body += "<td>" + lms_portal.escape(r.national_id_number || "—") + "</td>";
			body += "<td>" + lms_portal.escape(r.aml_status || "Pending") + "</td>";
			body += "<td>" + lms_portal.escape((r.modified || "").split(" ")[0] || "—") + "</td>";
			body += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-kyc-review" data-kyc="' +
				lms_portal.escape(r.name) + '">Review</button></td>';
			body += "</tr>";
		});
		body += "</tbody></table></div>";
	}

	var kpis = [
		{ label: "Pending", value: counts.pending || 0, tone: counts.pending ? "warning" : "" },
		{ label: "In Review", value: counts.in_review || 0, tone: "warning" },
		{ label: "Approved", value: counts.approved || 0, tone: "success" },
		{ label: "Rejected", value: counts.rejected || 0, tone: "danger" },
	];
	if (counts.no_kyc) {
		kpis.push({ label: "Borrowers w/o KYC", value: counts.no_kyc, tone: "muted" });
	}

	var html = lms_portal.pageStart() +
		lms_portal.kpiStrip(kpis) +
		lms_portal.panel({ title: "KYC Queue", controls: controls, body: body }) +
		lms_portal.pageEnd();
	el.innerHTML = html;

	// Wire up the filter
	var filter = el.querySelector("#lms-of-kyc-filter");
	if (filter) {
		filter.addEventListener("change", function () {
			lms_officer._kycCurrentStatus = filter.value;
			lms_officer._loadKycQueue(el);
		});
	}

	// Wire up Review buttons
	el.querySelectorAll(".lms-of-kyc-review").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_officer._openKycReview(btn.getAttribute("data-kyc"), el);
		});
	});
};

lms_officer._openKycReview = function (kycName, content) {
	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_kyc_detail",
		args: { kyc_name: kycName },
		callback: function (r) {
			var data = (r && r.message) || {};
			if (!data.kyc) {
				lms_portal.toast("Could not load KYC record.", "danger");
				return;
			}
			lms_officer._showKycReviewModal(data, content);
		},
		error: function (err) {
			var msg = (err && (err.message || err._server_message)) || "Could not load KYC.";
			lms_portal.toast(msg, "danger");
		},
	});
};

lms_officer._showKycReviewModal = function (data, content) {
	var kyc = data.kyc || {};
	var borrower = data.borrower || {};

	var body =
		'<form id="lms-kyc-review-form" class="lms-form" autocomplete="off">' +
		// --- Borrower summary ---
		'<div class="lms-section-header"><h4>Borrower</h4></div>' +
		'<div class="lms-grid-2">' +
		'<div><div class="lms-summary-label">Name</div><div class="lms-summary-value">' +
		lms_portal.escape(borrower.customer_name || kyc.customer || "—") + '</div></div>' +
		'<div><div class="lms-summary-label">Branch</div><div class="lms-summary-value">' +
		lms_portal.escape(borrower.custom_lms_branch || "—") + '</div></div>' +
		'<div><div class="lms-summary-label">Mobile</div><div class="lms-summary-value">' +
		lms_portal.escape(borrower.mobile_no || "—") + '</div></div>' +
		'<div><div class="lms-summary-label">Email</div><div class="lms-summary-value">' +
		lms_portal.escape(borrower.email_id || "—") + '</div></div>' +
		'</div>' +

		// --- KYC fields (editable) ---
		'<div class="lms-section-header"><h4>KYC</h4></div>' +
		'<div class="lms-grid-2">' +
		'<label>Status ' +
		'<select id="lms-kyc-status" class="lms-input lms-fallback-select">' +
		['Pending', 'In Review', 'Approved', 'Rejected'].map(function (s) {
			return '<option value="' + s + '"' + (kyc.kyc_status === s ? ' selected' : '') + '>' + s + '</option>';
		}).join('') +
		'</select></label>' +
		'<label>National ID number ' +
		'<input type="text" id="lms-kyc-nid" class="lms-input" value="' +
		lms_portal.escape(kyc.national_id_number || "") + '" maxlength="32" />' +
		'</label>' +
		'<label class="lms-grid-2__full"><input type="checkbox" id="lms-kyc-consent" ' +
		(kyc.consent_given ? 'checked' : '') + '> Customer consents to data processing' +
		'</label>' +
		'<label class="lms-grid-2__full">Reviewer note (free text, written to audit log) ' +
		'<textarea id="lms-kyc-note" class="lms-input" rows="2" placeholder="e.g. ID confirmed at counter, POA is March utility bill"></textarea>' +
		'</label>' +
		'</div>' +

		// --- Documents (upload + view) ---
		'<div class="lms-section-header"><h4>Documents</h4></div>' +
		'<div class="lms-grid-2">' +
		'<div class="lms-doc-cell">' +
		'<div class="lms-doc-label">ID document ' +
		(kyc.id_document_proof ? '<a class="lms-doc-link" href="' + lms_portal.escape(encodeURI(kyc.id_document_proof)) + '" target="_blank">view</a>' : '') +
		'</div>' +
		'<input type="hidden" id="lms-kyc-iddoc-url" value="' + lms_portal.escape(kyc.id_document_proof || "") + '" />' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" data-upload-field="id_document_proof">Upload / replace</button>' +
		'</div>' +
		'<div class="lms-doc-cell">' +
		'<div class="lms-doc-label">Proof of address ' +
		(kyc.proof_of_address ? '<a class="lms-doc-link" href="' + lms_portal.escape(encodeURI(kyc.proof_of_address)) + '" target="_blank">view</a>' : '') +
		'</div>' +
		'<input type="hidden" id="lms-kyc-poa-url" value="' + lms_portal.escape(kyc.proof_of_address || "") + '" />' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" data-upload-field="proof_of_address">Upload / replace</button>' +
		'</div>' +
		'</div>' +

		// --- AML (read-only) ---
		'<div class="lms-section-header"><h4>AML / CFT screening</h4></div>' +
		'<div class="lms-grid-2">' +
		'<div><div class="lms-summary-label">Status</div><div class="lms-summary-value">' +
		lms_portal.escape(kyc.aml_status || "Pending") + '</div></div>' +
		'<div><div class="lms-summary-label">Screened at</div><div class="lms-summary-value">' +
		lms_portal.escape((kyc.aml_screened_at || "—").split(" ")[0]) + '</div></div>' +
		'</div>' +
		'<p class="lms-muted" style="font-size:0.8rem;margin-top:0.5rem;">AML screening is performed by the regulator pipeline, not by the officer. If status is <strong>Flagged</strong> or <strong>Rejected</strong>, the manager portal will block origination.</p>' +

		// --- Audit trail ---
		'<div class="lms-section-header"><h4>Audit trail</h4></div>' +
		'<div id="lms-kyc-trail"></div>' +
		'</form>';

	var dlg = LMSModal.open({
		title: "Review KYC — " + (borrower.customer_name || kyc.customer || ""),
		body: body,
		size: "xl",
		actions: [
			{ label: "Cancel", value: false },
			{ label: "Save changes", value: true, primary: true },
		],
	});

	var dlgRoot = (dlg && dlg.dialog) || null;
	if (!dlgRoot) return;

	var kycName = kyc.name;

	// Load audit trail asynchronously
	lms_portal.safeCall({
		method: "lms_saas.api.officer.get_kyc_audit_trail",
		args: { kyc_name: kycName },
		callback: function (r) {
			var trail = (r && r.message && r.message.trail) || [];
			var trailEl = dlgRoot.querySelector("#lms-kyc-trail");
			if (!trailEl) return;
			if (!trail.length) {
				trailEl.innerHTML = '<p class="lms-muted">No prior changes recorded.</p>';
				return;
			}
			var html = '<div class="lms-data-table__wrap"><table class="lms-data-table">' +
				'<thead><tr><th>When</th><th>By</th><th>Change</th></tr></thead><tbody>';
			trail.forEach(function (t) {
				html += '<tr>';
				html += '<td>' + lms_portal.escape(t.creation || "") + '</td>';
				html += '<td>' + lms_portal.escape(t.user || t.owner || "") + '</td>';
				html += '<td>' + lms_portal.escape(t.details || "") + '</td>';
				html += '</tr>';
			});
			html += '</tbody></table></div>';
			trailEl.innerHTML = html;
		},
	});

	// Wire up the upload buttons. Each opens the NATIVE OS file dialog
	// (via a hidden <input type="file">) so the file picker renders
	// above every DOM element — no second modal, no z-index battles,
	// no hiding the LMS modal. The uploaded file_url is then bound to
	// the borrower's compliance record via the officer-side endpoint.
	var customer = kyc.customer;
	dlgRoot.querySelectorAll("[data-upload-field]").forEach(function (btn) {
		btn.addEventListener("click", function () {
			var fieldname = btn.getAttribute("data-upload-field");
			var hidden = dlgRoot.querySelector(
				fieldname === "id_document_proof" ? "#lms-kyc-iddoc-url" : "#lms-kyc-poa-url"
			);
			lms_portal._openFileUploader(null, function () {}, {
				accept: "image/*,application/pdf",
				is_private: true,  // KYC docs are PII — store in private/files/
				trigger_btn: btn,
				on_uploaded: function (file) {
					lms_portal.safeCall({
						method: "lms_saas.api.officer.upload_kyc_document_for_borrower",
						args: {
							customer: customer,
							fieldname: fieldname,
							file_url: file.file_url,
						},
						callback: function () {
							if (hidden) hidden.value = file.file_url;
							// Add a "view" link next to the button
							var label = btn.parentElement.querySelector(".lms-doc-label");
							if (label) {
								var existing = label.querySelector(".lms-doc-link");
								if (existing) existing.remove();
								var a = document.createElement("a");
								a.className = "lms-doc-link";
								a.href = encodeURI(file.file_url);
								a.target = "_blank";
								a.textContent = "view";
								label.appendChild(document.createTextNode(" "));
								label.appendChild(a);
							}
							lms_portal.toast("File uploaded.", "success");
						},
						error: function (err) {
							var msg = (err && (err.message || err._server_message)) || "Upload failed.";
							lms_portal.toast(msg, "danger");
						},
					});
				},
			});
		});
	});

	// Hook the Save button. lms_modal.js fires the onConfirm before
	// closing — we do the API call there. On success we also reload
	// the queue so the row reflects the new status.
	var origConfirm = dlg.dialog && dlg.dialog.querySelector('[data-lms-modal-action="true"]');
	if (origConfirm) {
		origConfirm.addEventListener("click", function (ev) {
			// Stop the modal from closing automatically; close it after
			// the API call returns.
			ev.preventDefault();
			ev.stopImmediatePropagation();
			var args = {
				kyc_name: kycName,
				kyc_status: (dlgRoot.querySelector("#lms-kyc-status") || {}).value || "",
				consent_given: ((dlgRoot.querySelector("#lms-kyc-consent") || {}).checked) ? 1 : 0,
				national_id: (dlgRoot.querySelector("#lms-kyc-nid") || {}).value || "",
				id_document_proof: (dlgRoot.querySelector("#lms-kyc-iddoc-url") || {}).value || "",
				proof_of_address: (dlgRoot.querySelector("#lms-kyc-poa-url") || {}).value || "",
				notes: (dlgRoot.querySelector("#lms-kyc-note") || {}).value || "",
			};
			lms_portal.safeCall({
				method: "lms_saas.api.officer.update_kyc",
				args: args,
				callback: function (r) {
					var res = (r && r.message) || {};
					if (res.status === "ok") {
						lms_portal.toast("KYC updated to " + (res.kyc_status || "") + ".", "success");
						dlg.close && dlg.close(true);
						// Reload queue + borrower counts
						lms_officer._loadKycQueue(content);
					} else {
						lms_portal.toast("Could not save KYC.", "danger");
					}
				},
				error: function (err) {
					var msg = (err && (err.message || err._server_message)) || "Could not save KYC.";
					lms_portal.toast(msg, "danger");
				},
			});
		}, true);  // capture phase so we run before LMSModal's handler
	}
};

// Add a "Start KYC" button to the borrower detail modal so an officer
// can open a KYC case from a borrower that has no compliance record yet.
// (Borrowers that already have a KYC show a "Open KYC" button instead.)
lms_officer._borrowerKycLink = function (compliance, customerName) {
	if (!compliance || !compliance.name) {
		// No KYC record yet — start one.
		return '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-of-brw-start-kyc" data-customer="' +
			lms_portal.escape(customerName) + '">Start KYC</button>';
	}
	return '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-of-brw-open-kyc" data-kyc="' +
		lms_portal.escape(compliance.name) + '">Open KYC queue</button>';
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
					html += '<div class="lms-empty">' + lms_icons.empty("check-circle") + '<h3>No arrears</h3><p>All loans are current.</p></div>';
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
					html += '<div class="lms-empty">' + lms_icons.empty("inbox") + '<h3>No collections yet</h3><p>Once repayments are recorded they will appear here.</p></div>';
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
