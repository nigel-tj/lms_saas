/* LMS Desk — branded loan-app shell (Frappe desk) */
(function () {
	var LMS_WS_TITLES = {
		Loans: 1,
		"Loan Management": 1,
		Applications: 1,
		"Loans & Disbursements": 1,
		Collections: 1,
		"Borrowers & Collateral": 1,
		Reports: 1,
		"Compliance & Risk": 1,
		Investors: 1,
		"CRM & Prospects": 1,
		CRM: 1,
	};

	var SIDEBAR_COLLAPSE_KEY = "lms_sidebar_collapsed";
	var SIDEBAR_AUTO_MAX_WIDTH = 1366;
	var LOAN_DASHBOARD_NAME = "Loan Dashboard";
	var CRM_DASHBOARD_NAME = "CRM";
	/* Desk form/list routes that receive LMS canvas + hero chrome (see install._lms_doctypes). */
	var LMS_FORM_DOCTYPES = {
		"Loan Application": 1,
		Loan: 1,
		"Loan Disbursement": 1,
		"Loan Repayment": 1,
		"Loan Product": 1,
		Customer: 1,
		Lead: 1,
		Opportunity: 1,
		Communication: 1,
		"LMS Borrower Compliance": 1,
		"LMS Collateral": 1,
		"LMS Investor": 1,
		"LMS Investor Transaction": 1,
		"LMS Incident Log": 1,
		"LMS Audit Event": 1,
		"LMS Notification Log": 1,
		"LMS Payment Intent": 1,
		"LMS Payment Provider": 1,
		"LMS Payment Reconciliation": 1,
		"LMS Credit Policy": 1,
		"LMS Lending Group": 1,
		"LMS Group Meeting": 1,
		"LMS Center": 1,
		"LMS Savings Account": 1,
		"LMS Savings Transaction": 1,
	};

	var DOCTYPE_HERO = {
		Loan: { listTitle: "Loans", desc: "Live loan book — balances and schedules" },
		"Loan Disbursement": { listTitle: "Disbursements", desc: "Pending and posted disbursements" },
		"Loan Repayment": { listTitle: "Repayments", desc: "Collections ledger and allocation history" },
		"Loan Product": { listTitle: "Loan products", desc: "Product terms, rates, and GL mapping" },
		Customer: { listTitle: "Borrowers", desc: "Customer records and KYC status" },
		Lead: { listTitle: "Leads", desc: "Prospect pipeline and new inquiries" },
		Opportunity: { listTitle: "Opportunities", desc: "Qualified deals and conversion stage" },
		Communication: { listTitle: "Communications", desc: "Borrower and prospect correspondence" },
		"LMS Borrower Compliance": { listTitle: "Compliance queue", desc: "Pending AML / KYC approvals" },
		"LMS Collateral": { listTitle: "Collateral register", desc: "Pledged assets and valuations" },
		"LMS Investor": { listTitle: "Investor book", desc: "Registered investors and balances" },
		"LMS Investor Transaction": { listTitle: "Investor transactions", desc: "Capital calls and distributions" },
		"LMS Incident Log": { listTitle: "Incident register", desc: "Operational and cyber incidents" },
		"LMS Audit Event": { listTitle: "Audit trail", desc: "Immutable money-movement log" },
		"LMS Notification Log": { listTitle: "Notification log", desc: "SMS and email delivery history" },
		"LMS Payment Intent": { listTitle: "Payment intents", desc: "Borrower payment requests and status" },
		"LMS Payment Provider": { listTitle: "Payment providers", desc: "EcoCash, OneMoney, and bank rails" },
		"LMS Payment Reconciliation": { listTitle: "Payment reconciliation", desc: "Match inbound payments to loans" },
		"LMS Credit Policy": { listTitle: "Credit policies", desc: "Scorecards and approval rules" },
		"LMS Lending Group": { listTitle: "Lending groups", desc: "Group lending structures and members" },
		"LMS Group Meeting": { listTitle: "Group meetings", desc: "Meeting records and attendance" },
		"LMS Center": { listTitle: "Centers", desc: "Branch and field office locations" },
		"LMS Savings Account": { listTitle: "Savings accounts", desc: "Member savings balances" },
		"LMS Savings Transaction": { listTitle: "Savings transactions", desc: "Deposits and withdrawals" },
	};
	var SYNC_DEBOUNCE_MS = 80;
	var SYNC_FOLLOWUP_MS = 450;
	var OBS_DEBOUNCE_MS = 120;
	var MODULE_HOME_HERO_RETRY_MS = 48;
	var MODULE_HOME_HERO_RETRY_MAX = 14;

	function desk_prefix() {
		return (window.frappe && frappe.boot && frappe.boot.lms_desk_prefix) || "/app";
	}

	function desk_url(path) {
		var p = (path || "").replace(/^\//, "");
		return p ? desk_prefix() + "/" + p : desk_prefix();
	}

	function path_ends_with(path, suffix) {
		var normalized = (path || "").replace(/\/$/, "");
		var target = desk_prefix() + suffix;
		return normalized === target || normalized.slice(-target.length) === target;
	}

	var TILE_COPY = {
		Company: { desc: "Company profile and accounting defaults", icon: "es-line-building", tone: "grey", countLabel: "set up" },
		"Loan Application": {
			desc: "Origination pipeline and open requests",
			icon: "es-line-edit",
			tone: "cyan",
			countLabel: "open",
		},
		Loan: { desc: "Live loan book — balances and schedules", icon: "es-line-loan", tone: "blue", countLabel: "loans" },
		Dashboard: {
			desc: "Portfolio KPIs, charts, and analytics",
			icon: "es-line-chart",
			tone: "green",
		},
		"Loan Pipeline": { desc: "Review open applications in your queue", icon: "es-line-bullet-list", tone: "cyan", countLabel: "open" },
		"New Application": { desc: "Capture a new borrower loan request", icon: "es-line-add", tone: "blue" },
		"Active Loans": { desc: "Browse the live loan book", icon: "es-line-book", tone: "blue" },
		Disbursements: { desc: "Track pending and posted disbursements", icon: "es-line-payments", tone: "green" },
		"Collections Ledger": { desc: "Repayments and allocation history", icon: "es-line-bullet-list", tone: "orange" },
		"PAR Snapshot": { desc: "Portfolio-at-risk overview", icon: "es-line-chart", tone: "red" },
		"Arrears Ladder": { desc: "Delinquency buckets and aging", icon: "es-line-time", tone: "orange" },
		"Collector Run Sheet": { desc: "Daily field collection worksheet", icon: "es-line-activity", tone: "green" },
		"Borrower Ledger": { desc: "Customer records and KYC status", icon: "es-line-customer", tone: "cyan" },
		"Collateral Register": { desc: "Pledged assets and valuations", icon: "es-line-lock", tone: "green" },
		"Compliance Queue": { desc: "Pending AML / KYC approvals", icon: "es-line-alert-triangle", tone: "purple" },
		"Portfolio At Risk": { desc: "PAR ratio and trend analysis", icon: "es-line-chart", tone: "red" },
		"Arrears Aging": { desc: "Overdue balances by bucket", icon: "es-line-time", tone: "orange" },
		"Collection Sheet": { desc: "Collector route and targets", icon: "es-line-activity", tone: "green" },
		"IFRS9 ECL Provision": { desc: "Expected credit loss provision", icon: "es-line-reports", tone: "red" },
		"Incident & Risk Register": { desc: "Operational and cyber incidents", icon: "es-line-alert-triangle", tone: "orange" },
		"Audit Trail": { desc: "Immutable money-movement log", icon: "es-line-time", tone: "grey" },
		"Investor Book": { desc: "Registered investors and balances", icon: "es-line-people", tone: "blue" },
		"Investor Transactions": { desc: "Capital calls and distributions", icon: "es-line-payments", tone: "cyan" },
		Lead: { desc: "Prospect pipeline and new inquiries", icon: "es-line-customer", tone: "cyan", countLabel: "leads" },
		Opportunity: { desc: "Qualified deals and conversion stage", icon: "es-line-chart", tone: "green", countLabel: "open" },
		Customer: { desc: "Borrower and prospect accounts", icon: "es-line-people", tone: "blue" },
		"Sales Analytics": { desc: "Pipeline and conversion analytics", icon: "es-line-chart", tone: "purple" },
	};

	function lms_dom_paused() {
		return !!window.__lms_dom_pause;
	}

	function with_lms_dom_pause(fn) {
		window.__lms_dom_pause = true;
		try {
			return fn();
		} finally {
			window.__lms_dom_pause = false;
		}
	}

	function debounce_lms(key, fn, wait) {
		var timerKey = "__lms_debounce_" + key;
		clearTimeout(window[timerKey]);
		window[timerKey] = setTimeout(fn, wait == null ? OBS_DEBOUNCE_MS : wait);
	}

	function get_company_brand_name() {
		var sys = (frappe.boot && frappe.boot.sysdefaults) || {};
		var raw = sys.company || frappe.boot.default_company || frappe.boot.company || "";
		return raw ? String(raw).trim() : "LMS";
	}

	function get_brand_logo_url() {
		var boot = frappe.boot || {};
		return boot.app_logo_url || boot.app_logo || boot.website_logo || null;
	}

	function get_brand_favicon_url() {
		var boot = frappe.boot || {};
		return boot.lms_favicon_url || boot.favicon || null;
	}

	function enforce_desk_branding() {
		var brandName = get_company_brand_name();
		var logoUrl = get_brand_logo_url();
		document.body.setAttribute("data-lms-desk-branding", "1");

		if (document.title) {
			document.title = document.title.replace(/frappe/gi, "").replace(/\s+-\s+$/, "").trim();
			if (!document.title || /erpnext/i.test(document.title)) {
				document.title = brandName + " LMS";
			}
		}

		var homeLink = document.querySelector(".navbar-home");
		if (homeLink) {
			homeLink.classList.add("lms-navbar-brand");
			homeLink.setAttribute("aria-label", brandName + " LMS");
			homeLink.setAttribute("title", brandName + " LMS");
			if (user_is_lms_staff()) {
				var nav = frappe.boot && frappe.boot.lms_desk_nav;
				homeLink.setAttribute("href", (nav && nav.home_url) || desk_url("loans"));
			}
		}

		var logoImg = document.querySelector(".navbar-home img");
		if (logoImg) {
			if (logoUrl) logoImg.setAttribute("src", logoUrl);
			logoImg.setAttribute("alt", brandName + " LMS");
		}
	}

	function strip_frappe_branding_links() {
		var blockPatterns = [/frappe/i, /erpnext/i, /framework/i, /community/i, /documentation/i];
		[".dropdown-help .dropdown-item", ".dropdown-navbar-user .dropdown-item"].forEach(function (sel) {
			document.querySelectorAll(sel).forEach(function (node) {
				var text = (node.textContent || "").trim();
				if (!text) return;
				if (blockPatterns.some(function (re) { return re.test(text); })) {
					(node.closest("li, .dropdown-item") || node).classList.add("lms-hide-frappe-branding");
				}
			});
		});
	}

	function override_lms_help_dropdown() {
		var menuSpec = frappe.boot && frappe.boot.lms_help_menu;
		if (!menuSpec || !menuSpec.enabled || !(menuSpec.items && menuSpec.items.length)) {
			return;
		}

		var dropdown = document.querySelector(".dropdown-help .dropdown-menu");
		if (!dropdown) return;

		var signature = menuSpec.items.map(function (item) {
			return item.separator ? "|" : item.label + ":" + (item.url || "");
		}).join(";");
		if (dropdown.getAttribute("data-lms-help-signature") === signature) {
			return;
		}

		dropdown.innerHTML = "";
		menuSpec.items.forEach(function (item) {
			if (item.separator) {
				var sep = document.createElement("li");
				sep.innerHTML = '<hr class="dropdown-divider">';
				dropdown.appendChild(sep);
				return;
			}
			var li = document.createElement("li");
			var link = document.createElement("a");
			link.className = "dropdown-item";
			link.textContent = item.label;
			link.setAttribute("href", item.url || "#");
			if ((item.url || "").indexOf("mailto:") === 0) {
				link.setAttribute("target", "_self");
			} else {
				link.setAttribute("target", "_blank");
				link.setAttribute("rel", "noopener noreferrer");
			}
			if (item.description) {
				link.setAttribute("title", item.description);
			}
			li.appendChild(link);
			dropdown.appendChild(li);
		});

		dropdown.setAttribute("data-lms-help-ready", "1");
		dropdown.setAttribute("data-lms-help-signature", signature);
		document.body.classList.add("lms-help-menu-ready");
	}

	function user_can_manage_workspace() {
		var roles = user_roles_list();
		return roles.indexOf("System Manager") !== -1 || roles.indexOf("Workspace Manager") !== -1;
	}

	function user_roles_list() {
		if (window.frappe && frappe.user_roles && frappe.user_roles.length) {
			return frappe.user_roles;
		}
		if (frappe.boot && frappe.boot.user && frappe.boot.user.roles) {
			return frappe.boot.user.roles;
		}
		return [];
	}

	function user_is_lms_staff() {
		var nav = frappe.boot && frappe.boot.lms_desk_nav;
		if (nav && nav.enabled) return true;
		var roles = user_roles_list();
		var staff = [
			"LMS Admin",
			"LMS Branch Manager",
			"LMS Loan Officer",
			"LMS Collector",
			"System Manager",
		];
		return staff.some(function (role) {
			return roles.indexOf(role) !== -1;
		});
	}

	function resolve_lms_nav_workspace() {
		var nav = frappe.boot && frappe.boot.lms_desk_nav;
		if (!nav || !nav.enabled || !window.frappe || !frappe.get_route) return null;

		var route = frappe.get_route() || [];
		if (route[0] === "Workspaces" && route[1]) return route[1];

		var map = nav.route_map || {};
		var key2 = route.slice(0, 2).join("/");
		if (map[key2]) return map[key2];
		if (route[0] && map[route[0]]) return map[route[0]];
		return null;
	}

	function lending_home_url() {
		var nav = frappe.boot && frappe.boot.lms_desk_nav;
		return (nav && nav.home_url) || desk_url("loans");
	}

	function doctype_slug(doctype) {
		if (frappe.router && frappe.router.slug) {
			return frappe.router.slug(doctype);
		}
		if (frappe.utils && frappe.utils.slug) {
			return frappe.utils.slug(doctype);
		}
		return String(doctype || "")
			.toLowerCase()
			.replace(/\s+/g, "-");
	}

	function doctype_new_url(doctype) {
		return desk_url(doctype_slug(doctype) + "/new");
	}

	function apply_loan_dashboard_hero_layout(hero) {
		if (!hero) return;
		/* Flush with KPI cards — page-body already has horizontal padding */
		hero.style.setProperty("margin-left", "0", "important");
		hero.style.setProperty("margin-right", "0", "important");
		hero.style.setProperty("width", "100%", "important");
		hero.style.setProperty("max-width", "100%", "important");
	}

	function get_dashboard_view_name() {
		if (!window.frappe || !frappe.get_route) return null;
		var route = frappe.get_route() || [];
		if (route[0] === "dashboard-view" && route[1]) {
			return route[1];
		}
		var dataRoute = document.body.getAttribute("data-route") || "";
		if (dataRoute.indexOf("dashboard-view/") === 0) {
			return decodeURIComponent(dataRoute.slice("dashboard-view/".length));
		}
		return null;
	}

	function remove_dashboard_heroes(page) {
		if (!page) return;
		page.querySelectorAll("[data-lms-dashboard-hero], [data-lms-loan-dashboard-hero]").forEach(function (node) {
			node.remove();
		});
	}

	function insert_dashboard_hero(page, pageContent, hero) {
		apply_loan_dashboard_hero_layout(hero);
		var dashboard = pageContent.querySelector(".dashboard");
		if (dashboard) {
			pageContent.insertBefore(hero, dashboard);
		} else {
			pageContent.insertBefore(hero, pageContent.firstChild);
		}
	}

	function build_dashboard_hero(spec) {
		var hero = document.createElement("div");
		hero.className = spec.className + " lms-hero lms-hero--inner-shell";
		hero.setAttribute("data-lms-dashboard-hero", spec.key);
		hero.innerHTML =
			'<div class="lms-hero__inner">' +
			'<div class="lms-hero__copy">' +
			'<h1 class="lms-hero__title">' +
			spec.title +
			"</h1>" +
			'<p class="lms-hero__subtitle">' +
			spec.subtitle +
			"</p>" +
			"</div>" +
			'<div class="lms-hero__actions">' +
			'<a class="btn btn-default btn-sm" href="' +
			spec.backUrl +
			'">' +
			spec.backLabel +
			"</a>" +
			"</div>" +
			"</div>";
		return hero;
	}

	/** Branded hero for dashboard-view routes (Loan Dashboard, CRM, etc.). */
	function inject_dashboard_hero() {
		if (!user_is_lms_staff()) return;

		var page = document.getElementById("page-dashboard-view");
		if (!page) return;

		var pageContent = page.querySelector(".page-content");
		if (!pageContent) return;

		var dashboardName = get_dashboard_view_name();
		remove_dashboard_heroes(page);

		if (!dashboardName) return;

		var brand = get_company_brand_name();
		var spec = null;

		if (dashboardName === LOAN_DASHBOARD_NAME) {
			spec = {
				key: "loan",
				className: "lms-loan-dashboard-hero",
				title: LOAN_DASHBOARD_NAME,
				subtitle:
					"Portfolio KPIs, risk metrics, and lending analytics. Use the Lending menu for applications, collections, and compliance.",
				backUrl: lending_home_url(),
				backLabel: "← Back to Lending menu",
			};
		} else if (dashboardName === CRM_DASHBOARD_NAME) {
			spec = {
				key: "crm",
				className: "lms-crm-dashboard-hero",
				title: brand + " CRM",
				subtitle: "Lead pipeline, opportunities, and conversion metrics for prospect origination.",
				backUrl: desk_url("crm"),
				backLabel: "← Back to CRM workspace",
			};
		}

		if (!spec) return;

		var existing = page.querySelector("[data-lms-dashboard-hero=\"" + spec.key + "\"]");
		if (existing) {
			apply_loan_dashboard_hero_layout(existing);
			return;
		}

		with_lms_dom_pause(function () {
			insert_dashboard_hero(page, pageContent, build_dashboard_hero(spec));
		});
	}

	function bind_loan_dashboard_hero_hooks() {
		if (!user_is_lms_staff()) return;

		var page = document.getElementById("page-dashboard-view");
		if (!page || page.__lms_hero_hooks_bound) return;
		page.__lms_hero_hooks_bound = true;

		$(page).on("show.lms-dashboard-hero", function () {
			inject_dashboard_hero();
		});

		var content = page.querySelector(".page-content");
		if (content && !content.__lms_hero_observed) {
			content.__lms_hero_observed = true;
			new MutationObserver(function () {
				if (lms_dom_paused() || !get_dashboard_view_name()) return;
				debounce_lms("dashboard_hero", inject_dashboard_hero, OBS_DEBOUNCE_MS);
			}).observe(content, { childList: true, subtree: false });
		}
	}

	function use_native_lending_nav() {
		var nav = frappe.boot && frappe.boot.lms_desk_nav;
		return !!(nav && nav.use_native_lending);
	}

	function sync_lms_app_nav() {
		var show = user_is_lms_staff();
		var nativeNav = show && use_native_lending_nav();
		document.body.classList.toggle("lms-desk-staff", show);
		document.body.classList.toggle("lms-native-lending-nav", nativeNav);
		var bar = document.querySelector(".lms-desk-app-nav");
		if (show && !use_native_lending_nav()) {
			render_lms_app_nav();
		} else if (bar) {
			bar.remove();
		}
		sync_lms_app_nav_active();
	}

	function render_lms_app_nav() {
		var nav = frappe.boot && frappe.boot.lms_desk_nav;
		if (!nav || !nav.enabled) return;

		var bar = document.querySelector(".lms-desk-app-nav");
		if (!bar) {
			bar = document.createElement("nav");
			bar.className = "lms-desk-app-nav";
			bar.setAttribute("aria-label", "Loan Management navigation");
			bar.innerHTML =
				'<div class="lms-desk-app-nav__inner">' +
				'<div class="lms-desk-app-nav__items" role="list"></div>' +
				"</div>";

			var navbar = document.querySelector("header.navbar") || document.querySelector(".navbar");
			if (navbar && navbar.parentNode) {
				navbar.parentNode.insertBefore(bar, navbar.nextSibling);
			} else {
				document.body.insertBefore(bar, document.body.firstChild);
			}
		}

		var itemsWrap = bar.querySelector(".lms-desk-app-nav__items");
		if (!itemsWrap || itemsWrap.getAttribute("data-lms-nav-ready") === "1") {
			sync_lms_app_nav_active();
			return;
		}

		itemsWrap.innerHTML = "";
		(nav.items || []).forEach(function (item) {
			var link = document.createElement("a");
			link.className = "lms-desk-app-nav__link";
			link.href = item.url;
			link.setAttribute("role", "listitem");
			link.setAttribute("data-lms-workspace", item.title);
			if (item.is_landing) {
				link.classList.add("lms-desk-app-nav__link--home");
				link.textContent = "Home";
				link.setAttribute("title", item.title);
			} else {
				link.textContent = item.title;
			}
			link.addEventListener("click", function (e) {
				if (window.frappe && frappe.set_route) {
					e.preventDefault();
					var parts = (item.route || "").split("/");
					frappe.set_route.apply(frappe, parts);
				}
			});
			itemsWrap.appendChild(link);
		});

		itemsWrap.setAttribute("data-lms-nav-ready", "1");
		sync_lms_app_nav_active();
	}

	function sync_lms_app_nav_active() {
		var active = resolve_lms_nav_workspace();
		document.querySelectorAll(".lms-desk-app-nav__link").forEach(function (link) {
			var ws = link.getAttribute("data-lms-workspace");
			link.classList.toggle("is-active", !!active && ws === active);
			link.setAttribute("aria-current", active && ws === active ? "page" : "false");
		});
	}

	function is_loan_dashboard_route() {
		return get_dashboard_view_name() === LOAN_DASHBOARD_NAME;
	}

	function is_crm_dashboard_route() {
		return get_dashboard_view_name() === CRM_DASHBOARD_NAME;
	}

	function is_branded_dashboard_route() {
		return is_loan_dashboard_route() || is_crm_dashboard_route();
	}

	function get_company_form_name() {
		if (!window.frappe) return null;
		var route = (frappe.get_route && frappe.get_route()) || [];
		if (route[0] === "Form" && route[1] === "Company" && route[2]) {
			return route[2];
		}
		var dataRoute = document.body.getAttribute("data-route") || "";
		if (dataRoute.indexOf("Form/Company/") === 0) {
			return decodeURIComponent(dataRoute.slice("Form/Company/".length));
		}
		return null;
	}

	function is_company_form_route() {
		return !!get_company_form_name();
	}

	function inject_company_form_hero() {
		if (!user_is_lms_staff()) return;

		var companyName = get_company_form_name();
		if (!companyName) return;

		var page = document.getElementById("page-Company");
		if (!page) return;

		var pageContent = page.querySelector(".page-content");
		if (!pageContent) return;

		var existing = page.querySelector("[data-lms-company-hero]");
		if (existing) {
			var titleEl = existing.querySelector(".lms-hero__title");
			if (titleEl && titleEl.textContent !== companyName) {
				titleEl.textContent = companyName;
			}
			return;
		}

		var hero = document.createElement("div");
		hero.className = "lms-company-hero lms-hero lms-hero--inner-shell";
		hero.setAttribute("data-lms-company-hero", "1");
		hero.innerHTML =
			'<div class="lms-hero__inner">' +
			'<div class="lms-hero__copy">' +
			'<h1 class="lms-hero__title">' +
			companyName +
			"</h1>" +
			'<p class="lms-hero__subtitle">Company profile, chart of accounts, and lending defaults for this site.</p>' +
			"</div>" +
			'<div class="lms-hero__actions">' +
			'<a class="btn btn-default btn-sm" href="' +
			lending_home_url() +
			'">← Back to Lending menu</a>' +
			'<a class="btn btn-default btn-sm" href="' + desk_url("website-settings") + '">Website branding</a>' +
			"</div>" +
			"</div>";

		apply_loan_dashboard_hero_layout(hero);
		with_lms_dom_pause(function () {
			var layoutMain = pageContent.querySelector(".layout-main");
			if (layoutMain) {
				pageContent.insertBefore(hero, layoutMain);
			} else {
				pageContent.insertBefore(hero, pageContent.firstChild);
			}
		});
	}

	function sync_company_form_flag() {
		if (!document.body.classList.contains("lms-desk-enhanced")) return;
		var active = is_company_form_route();
		document.body.classList.toggle("lms-nav-company", active);
		if (active) {
			inject_company_form_hero();
		}
	}

	function get_lms_form_doctype_route() {
		if (!window.frappe) return null;
		var route = (frappe.get_route && frappe.get_route()) || [];
		if (route[0] === "Form" && LMS_FORM_DOCTYPES[route[1]]) {
			return { doctype: route[1], mode: "form", docname: route[2] || null };
		}
		if (route[0] === "List" && LMS_FORM_DOCTYPES[route[1]]) {
			return { doctype: route[1], mode: "list" };
		}
		var dataRoute = document.body.getAttribute("data-route") || "";
		if (dataRoute.indexOf("Form/") === 0) {
			var formParts = dataRoute.split("/");
			if (formParts.length >= 2 && LMS_FORM_DOCTYPES[formParts[1]]) {
				return {
					doctype: formParts[1],
					mode: "form",
					docname: formParts[2] ? decodeURIComponent(formParts[2]) : null,
				};
			}
		}
		if (dataRoute.indexOf("List/") === 0) {
			var listParts = dataRoute.split("/");
			if (listParts.length >= 2 && LMS_FORM_DOCTYPES[listParts[1]]) {
				return { doctype: listParts[1], mode: "list" };
			}
		}
		return null;
	}

	function get_query_report_route() {
		if (!window.frappe) return null;
		var route = (frappe.get_route && frappe.get_route()) || [];
		if (route[0] === "query-report" && route[1]) {
			return { report: route[1], mode: "query-report" };
		}
		var dataRoute = document.body.getAttribute("data-route") || "";
		if (dataRoute.indexOf("query-report/") === 0) {
			return { report: decodeURIComponent(dataRoute.slice("query-report/".length)), mode: "query-report" };
		}
		return null;
	}

	function is_loan_application_route() {
		var ctx = get_lms_form_doctype_route();
		return !!(ctx && ctx.doctype === "Loan Application");
	}

	function doctype_hero_meta(doctype) {
		var hero = DOCTYPE_HERO[doctype] || {};
		var tile = TILE_COPY[doctype] || {};
		return {
			listTitle: hero.listTitle || doctype,
			desc: hero.desc || tile.desc || "",
		};
	}

	function inject_lms_doctype_hero() {
		if (!user_is_lms_staff()) return;

		var ctx = get_lms_form_doctype_route();
		if (!ctx || ctx.doctype === "Loan Application") return;

		var page = get_lms_form_doctype_page(ctx);
		if (!page) return;

		var pageContent = page.querySelector(".page-content");
		if (!pageContent) return;

		var meta = doctype_hero_meta(ctx.doctype);
		var heroKey = ctx.mode + ":" + ctx.doctype;
		var existing = page.querySelector('[data-lms-doctype-hero="' + heroKey + '"]');
		var title =
			ctx.mode === "list"
				? meta.listTitle
				: ctx.docname || ctx.doctype;

		if (existing) {
			var titleEl = existing.querySelector(".lms-hero__title");
			if (titleEl && titleEl.textContent !== title) {
				titleEl.textContent = title;
			}
			return;
		}

		var hero = document.createElement("div");
		hero.className = "lms-doctype-hero lms-hero lms-hero--inner-shell";
		hero.setAttribute("data-lms-doctype-hero", heroKey);
		hero.innerHTML =
			'<div class="lms-hero__inner">' +
			'<div class="lms-hero__copy">' +
			'<h1 class="lms-hero__title">' +
			title +
			"</h1>" +
			(meta.desc ? '<p class="lms-hero__subtitle">' + meta.desc + "</p>" : "") +
			"</div>" +
			'<div class="lms-hero__actions">' +
			'<a class="btn btn-default btn-sm" href="' +
			lending_home_url() +
			'">← Back to Lending menu</a>' +
			(ctx.mode === "list"
				? '<a class="btn btn-primary btn-sm lms-hero__cta" href="' +
				  doctype_new_url(ctx.doctype) +
				  '">New</a>'
				: "") +
			"</div>" +
			"</div>";

		apply_loan_dashboard_hero_layout(hero);
		with_lms_dom_pause(function () {
			var layoutMain = pageContent.querySelector(".layout-main");
			if (layoutMain) {
				pageContent.insertBefore(hero, layoutMain);
			} else {
				pageContent.insertBefore(hero, pageContent.firstChild);
			}
		});
	}

	function inject_query_report_hero() {
		if (!user_is_lms_staff()) return;

		var ctx = get_query_report_route();
		if (!ctx) return;

		var page = document.getElementById("page-query-report");
		if (!page) return;

		var pageContent = page.querySelector(".page-content");
		if (!pageContent) return;

		var reportName = ctx.report;
		var existing = page.querySelector("[data-lms-report-hero]");
		if (existing) {
			var titleEl = existing.querySelector(".lms-hero__title");
			if (titleEl && titleEl.textContent !== reportName) {
				titleEl.textContent = reportName;
			}
			return;
		}

		var tile = TILE_COPY[reportName] || {};
		var hero = document.createElement("div");
		hero.className = "lms-report-hero lms-hero lms-hero--inner-shell";
		hero.setAttribute("data-lms-report-hero", "1");
		hero.innerHTML =
			'<div class="lms-hero__inner">' +
			'<div class="lms-hero__copy">' +
			'<h1 class="lms-hero__title">' +
			reportName +
			"</h1>" +
			(tile.desc ? '<p class="lms-hero__subtitle">' + tile.desc + "</p>" : "") +
			"</div>" +
			'<div class="lms-hero__actions">' +
			'<a class="btn btn-default btn-sm" href="' +
			lending_home_url() +
			'">← Back to Lending menu</a>' +
			"</div>" +
			"</div>";

		apply_loan_dashboard_hero_layout(hero);
		with_lms_dom_pause(function () {
			var layoutMain = pageContent.querySelector(".layout-main");
			if (layoutMain) {
				pageContent.insertBefore(hero, layoutMain);
			} else {
				pageContent.insertBefore(hero, pageContent.firstChild);
			}
		});
	}

	function get_lms_form_doctype_page(ctx) {
		if (!ctx) return null;
		if (ctx.mode === "form") {
			return document.getElementById("page-" + ctx.doctype);
		}
		return document.querySelector('[id^="page-List/' + ctx.doctype + '"]');
	}

	function inject_loan_application_form_hero() {
		if (!user_is_lms_staff()) return;

		var ctx = get_lms_form_doctype_route();
		if (!ctx || ctx.doctype !== "Loan Application" || ctx.mode !== "form") return;

		var page = get_lms_form_doctype_page(ctx);
		if (!page) return;

		var pageContent = page.querySelector(".page-content");
		if (!pageContent) return;

		var title = ctx.docname || "Loan Application";
		var existing = page.querySelector("[data-lms-loan-application-hero]");
		if (existing) {
			var titleEl = existing.querySelector(".lms-hero__title");
			if (titleEl && titleEl.textContent !== title) {
				titleEl.textContent = title;
			}
			return;
		}

		var meta = TILE_COPY["Loan Application"] || {};
		var hero = document.createElement("div");
		hero.className = "lms-loan-application-hero lms-hero lms-hero--inner-shell";
		hero.setAttribute("data-lms-loan-application-hero", "form");
		hero.innerHTML =
			'<div class="lms-hero__inner">' +
			'<div class="lms-hero__copy">' +
			'<h1 class="lms-hero__title">' +
			title +
			"</h1>" +
			'<p class="lms-hero__subtitle">' +
			(meta.desc || "Origination pipeline and open requests") +
			"</p>" +
			"</div>" +
			'<div class="lms-hero__actions">' +
			'<a class="btn btn-default btn-sm" href="' +
			lending_home_url() +
			'">← Back to Lending menu</a>' +
			'<a class="btn btn-default btn-sm" href="' + desk_url("loan-application/view/list") + '">All applications</a>' +
			"</div>" +
			"</div>";

		apply_loan_dashboard_hero_layout(hero);
		with_lms_dom_pause(function () {
			var layoutMain = pageContent.querySelector(".layout-main");
			if (layoutMain) {
				pageContent.insertBefore(hero, layoutMain);
			} else {
				pageContent.insertBefore(hero, pageContent.firstChild);
			}
		});
	}

	function inject_loan_application_list_hero() {
		if (!user_is_lms_staff()) return;

		var ctx = get_lms_form_doctype_route();
		if (!ctx || ctx.doctype !== "Loan Application" || ctx.mode !== "list") return;

		var page = get_lms_form_doctype_page(ctx);
		if (!page) return;

		var pageContent = page.querySelector(".page-content");
		if (!pageContent) return;

		if (page.querySelector("[data-lms-loan-application-hero]")) return;

		var hero = document.createElement("div");
		hero.className = "lms-loan-application-hero lms-hero lms-hero--inner-shell";
		hero.setAttribute("data-lms-loan-application-hero", "list");
		hero.innerHTML =
			'<div class="lms-hero__inner">' +
			'<div class="lms-hero__copy">' +
			'<h1 class="lms-hero__title">Loan applications</h1>' +
			'<p class="lms-hero__subtitle">Origination pipeline — review, approve, and convert requests into loans.</p>' +
			"</div>" +
			'<div class="lms-hero__actions">' +
			'<a class="btn btn-primary btn-sm lms-hero__cta" href="' + desk_url("loan-application/new") + '">New application</a>' +
			'<a class="btn btn-default btn-sm" href="' +
			lending_home_url() +
			'">← Back to Lending menu</a>' +
			"</div>" +
			"</div>";

		apply_loan_dashboard_hero_layout(hero);
		with_lms_dom_pause(function () {
			var layoutMain = pageContent.querySelector(".layout-main");
			if (layoutMain) {
				pageContent.insertBefore(hero, layoutMain);
			} else {
				pageContent.insertBefore(hero, pageContent.firstChild);
			}
		});
	}

	function sync_lms_form_doctype_flag() {
		if (!document.body.classList.contains("lms-desk-enhanced")) return;
		var ctx = get_lms_form_doctype_route();
		var active = !!ctx;
		document.body.classList.toggle("lms-nav-lending-form", active);
		document.body.classList.toggle("lms-nav-loan-application", !!(ctx && ctx.doctype === "Loan Application"));
		if (ctx && ctx.doctype === "Loan Application") {
			if (ctx.mode === "form") {
				inject_loan_application_form_hero();
			} else {
				inject_loan_application_list_hero();
			}
		} else if (ctx) {
			inject_lms_doctype_hero();
		}
	}

	function sync_query_report_flag() {
		if (!document.body.classList.contains("lms-desk-enhanced")) return;
		var active = !!get_query_report_route();
		document.body.classList.toggle("lms-nav-report", active);
		if (active) {
			inject_query_report_hero();
		}
	}

	function bind_lending_doctype_hero_hooks() {
		if (!user_is_lms_staff()) return;

		var page = document.getElementById("page-Loan Application");
		if (page && !page.__lms_loan_app_form_hero_hooks_bound) {
			page.__lms_loan_app_form_hero_hooks_bound = true;
			$(page).on("show.lms-loan-application-hero", inject_loan_application_form_hero);
		}

		document.querySelectorAll('[id^="page-List/Loan Application"]').forEach(function (listPage) {
			if (listPage.__lms_loan_app_list_hero_hooks_bound) return;
			listPage.__lms_loan_app_list_hero_hooks_bound = true;
			$(listPage).on("show.lms-loan-application-hero", inject_loan_application_list_hero);
		});
	}

	function bind_company_form_hero_hooks() {
		if (!user_is_lms_staff()) return;

		var page = document.getElementById("page-Company");
		if (!page || page.__lms_company_hero_hooks_bound) return;
		page.__lms_company_hero_hooks_bound = true;

		$(page).on("show.lms-company-hero", function () {
			inject_company_form_hero();
		});
	}

	function current_lms_screen() {
		if (!window.frappe) return null;
		var route = frappe.get_route && frappe.get_route();
		if (route && route[0] === "Workspaces" && LMS_WS_TITLES[route[1]]) {
			return route[1];
		}
		var dataRoute = document.body.getAttribute("data-route") || "";
		if (dataRoute.indexOf("Workspaces/") === 0) {
			var name = dataRoute.slice("Workspaces/".length);
			if (LMS_WS_TITLES[name]) return name;
		}
		if (dataRoute === "Workspaces/Loans" || dataRoute.indexOf("Workspaces/Loans") === 0) {
			return "Loans";
		}
		var path = (window.location.pathname || "").replace(/\/$/, "");
		if (path_ends_with(path, "/loans")) {
			return "Loans";
		}
		if (dataRoute === "Workspaces/CRM" || dataRoute.indexOf("Workspaces/CRM") === 0) {
			return "CRM";
		}
		if (path_ends_with(path, "/crm")) {
			return "CRM";
		}
		return null;
	}

	function sync_lms_workspace_flag() {
		if (!window.frappe || !document.body.classList.contains("lms-desk-enhanced")) return;

		var screen = current_lms_screen();
		var active = !!screen;
		var canManage = user_can_manage_workspace();

		document.body.setAttribute("data-lms-can-manage", canManage ? "1" : "0");
		document.body.classList.toggle("lms-nav-screen", active);
		document.body.classList.toggle("lms-nav-landing", screen === "Loan Management");
		document.body.classList.toggle("lms-nav-lending-home", screen === "Loans");
		document.body.classList.toggle("lms-nav-crm", screen === "CRM" || is_crm_dashboard_route());
		document.body.classList.toggle("lms-nav-dashboard", is_loan_dashboard_route());
		document.body.classList.toggle("lms-nav-crm-dashboard", is_crm_dashboard_route());

		if (active) {
			document.body.setAttribute("data-lms-workspace", "1");
			if (screen === "Loans" || screen === "CRM") {
				schedule_module_home_hero(screen);
			}
			enhance_lms_workspace(screen);
		} else {
			document.body.removeAttribute("data-lms-workspace");
		}

		tag_sidebar_items();
		sync_lms_app_nav();
	}

	function tag_sidebar_items() {
		var sidebar = document.querySelector(".desk-sidebar");
		if (sidebar) sidebar.classList.add("lms-desk-sidebar");

		setup_sidebar_toolbar(sidebar);

		var screen = current_lms_screen() || resolve_lms_nav_workspace();
		var collapsed = document.body.classList.contains("lms-sidebar-collapsed");

		if (!sidebar) return;

		sidebar.querySelectorAll(".sidebar-item-container").forEach(function (container) {
			var name = container.getAttribute("item-name");
			if (!name || !LMS_WS_TITLES[name]) return;

			var parent = container.getAttribute("item-parent");
			var label = container.querySelector(".sidebar-item-label");

			container.classList.add("lms-sidebar-item");
			container.classList.toggle("lms-sidebar-root", !parent);
			container.classList.toggle("lms-sidebar-child", !!parent);
			container.classList.toggle("is-active", name === screen);

			var clean = "";
			if (label) {
				label.removeAttribute("title");
				clean = (label.textContent || "").replace(/\s+/g, " ").trim();
				if (clean && label.textContent !== clean) {
					label.textContent = clean;
				}
			}
			var anchor = container.querySelector(".item-anchor");
			if (anchor) {
				if (collapsed) {
					anchor.setAttribute("title", clean || name);
				} else {
					anchor.removeAttribute("title");
				}
			}
		});

		sidebar.querySelectorAll(".standard-sidebar-section:not(.hidden) .section-title").forEach(function (el) {
			var text = (el.textContent || "").trim().toLowerCase();
			if (text === "public") el.textContent = "Menu";
		});
	}

	function sidebar_preference_stored() {
		try {
			return localStorage.getItem(SIDEBAR_COLLAPSE_KEY);
		} catch (e) {
			return null;
		}
	}

	function sidebar_should_auto_collapse() {
		return window.innerWidth < SIDEBAR_AUTO_MAX_WIDTH;
	}

	function apply_responsive_sidebar() {
		if (sidebar_preference_stored() !== null) return;
		set_sidebar_collapsed(sidebar_should_auto_collapse(), false);
	}

	function sidebar_is_collapsed() {
		return document.body.classList.contains("lms-sidebar-collapsed");
	}

	function set_sidebar_collapsed(collapsed, persist) {
		document.body.classList.toggle("lms-sidebar-collapsed", collapsed);
		if (persist !== false) {
			try {
				localStorage.setItem(SIDEBAR_COLLAPSE_KEY, collapsed ? "1" : "0");
			} catch (e) { /* ignore */ }
		}
		var btn = document.querySelector(".lms-sidebar-collapse-btn");
		if (btn) {
			btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
			btn.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
			btn.setAttribute("title", collapsed ? "Expand sidebar (Ctrl+Shift+M)" : "Collapse sidebar (Ctrl+Shift+M)");
			var use = btn.querySelector("use");
			if (use) use.setAttribute("href", collapsed ? "#icon-sidebar-expand" : "#icon-sidebar-collapse");
		}
		tag_sidebar_items();
		layout_tile_grid(get_workspace_main());
	}

	function toggle_sidebar_collapsed() {
		set_sidebar_collapsed(!sidebar_is_collapsed());
	}

	function restore_sidebar_collapsed() {
		var stored = sidebar_preference_stored();
		if (stored === "1") {
			document.body.classList.add("lms-sidebar-collapsed");
			return;
		}
		if (stored === "0") {
			return;
		}
		if (sidebar_should_auto_collapse()) {
			document.body.classList.add("lms-sidebar-collapsed");
		}
	}

	function parse_col_span(classList, prefix) {
		for (var i = 0; i < classList.length; i++) {
			var cls = classList[i];
			if (cls.indexOf(prefix) === 0) {
				var n = parseInt(cls.slice(prefix.length), 10);
				if (!isNaN(n) && n > 0 && n <= 12) return n;
			}
		}
		return null;
	}

	function resolve_block_grid_span(block, viewportWidth) {
		var classes = block.classList;
		var lg = parse_col_span(classes, "col-lg-");
		var md = parse_col_span(classes, "col-md-");
		var sm = parse_col_span(classes, "col-sm-");
		var xs = parse_col_span(classes, "col-xs-");

		if (viewportWidth >= 992 && lg) return lg;
		if (viewportWidth >= 768 && md) return md;
		if (viewportWidth >= 768 && sm) return sm;
		if (xs) return xs;
		return 12;
	}

	function apply_workspace_grid_spans(main) {
		if (!main) return;
		var redactor = main.querySelector(".codex-editor__redactor");
		if (!redactor) return;

		redactor.classList.remove("lms-tile-grid--solo", "lms-tile-grid--pair", "lms-tile-grid--many");

		var viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1200;
		redactor.querySelectorAll(".ce-block").forEach(function (block) {
			var span = resolve_block_grid_span(block, viewportWidth);
			block.style.gridColumn = "span " + span;
		});
	}

	function layout_tile_grid(main) {
		apply_workspace_grid_spans(main);
	}

	function sync_layout_tier() {
		var wrap = document.querySelector(".layout-main-section-wrapper");
		if (!wrap) return;

		var width = wrap.getBoundingClientRect().width;
		var tier = "compact";
		if (width >= 1400) tier = "ultra";
		else if (width >= 1100) tier = "wide";
		else if (width >= 720) tier = "comfortable";

		document.body.setAttribute("data-lms-layout", tier);
	}

	function bind_layout_responsive() {
		if (window.__lms_layout_responsive_bound) return;
		window.__lms_layout_responsive_bound = true;

		var wrap = document.querySelector(".layout-main-section-wrapper");
		if (wrap && window.ResizeObserver) {
			var ro = new ResizeObserver(function () {
				sync_layout_tier();
				apply_responsive_sidebar();
				var main = get_workspace_main();
				if (main) layout_tile_grid(main);
			});
			ro.observe(wrap);
		}

		window.addEventListener("resize", function () {
			sync_layout_tier();
			apply_responsive_sidebar();
			var main = get_workspace_main();
			if (main) apply_workspace_grid_spans(main);
		}, { passive: true });

		sync_layout_tier();
	}

	function setup_sidebar_toolbar(sidebar) {
		if (!sidebar || sidebar.querySelector(".lms-sidebar-toolbar")) return;

		var toolbar = document.createElement("div");
		toolbar.className = "lms-sidebar-toolbar";
		toolbar.innerHTML =
			'<span class="lms-sidebar-toolbar-label section-title">Menu</span>' +
			'<button type="button" class="lms-sidebar-collapse-btn" aria-expanded="true" aria-label="Collapse sidebar" title="Collapse sidebar (Ctrl+Shift+M)">' +
			'<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-sidebar-collapse"></use></svg>' +
			"</button>";
		sidebar.insertBefore(toolbar, sidebar.firstChild);
		toolbar.querySelector(".lms-sidebar-collapse-btn").addEventListener("click", toggle_sidebar_collapsed);

		if (sidebar_is_collapsed()) {
			set_sidebar_collapsed(true, false);
		}
	}

	function sync_help_dropdown_branding() {
		if (lms_dom_paused()) return;
		override_lms_help_dropdown();
		strip_frappe_branding_links();
	}

	function bind_help_dropdown_observer() {
		if (window.__lms_help_obs_bound) return;
		window.__lms_help_obs_bound = true;
		var root = document.querySelector("header.navbar") || document.querySelector(".navbar");
		if (!root) return;
		new MutationObserver(function () {
			debounce_lms("help_dropdown", sync_help_dropdown_branding, OBS_DEBOUNCE_MS);
		}).observe(root, { childList: true, subtree: true });
	}

	function bind_sidebar_shortcuts() {
		if (window.__lms_sidebar_shortcuts_bound) return;
		window.__lms_sidebar_shortcuts_bound = true;
		document.addEventListener("keydown", function (e) {
			if (!document.body.classList.contains("lms-desk-enhanced")) return;
			if (!(e.ctrlKey && e.shiftKey && (e.key === "M" || e.key === "m"))) return;
			var tag = (document.activeElement && document.activeElement.tagName) || "";
			if (tag === "INPUT" || tag === "TEXTAREA" || document.activeElement.isContentEditable) return;
			e.preventDefault();
			toggle_sidebar_collapsed();
		});
	}

	function is_module_home_screen(title) {
		return title === "Loans" || title === "CRM";
	}

	/** Workspace canvas may not be the first .layout-main-section after SPA route changes. */
	function get_workspace_main() {
		var mains = document.querySelectorAll(".layout-main-section");
		for (var i = 0; i < mains.length; i++) {
			if (mains[i].querySelector(".codex-editor__redactor")) {
				return mains[i];
			}
		}
		return (
			document.querySelector(".layout-main-section.lms-workspace-canvas") ||
			document.querySelector(".layout-main .layout-main-section") ||
			document.querySelector(".layout-main-section")
		);
	}

	function pump_module_home_hero(screen, attempt) {
		if (lms_dom_paused() || !is_module_home_screen(screen)) return;

		var main = get_workspace_main();
		if (!main) {
			if (attempt < MODULE_HOME_HERO_RETRY_MAX) {
				setTimeout(function () {
					pump_module_home_hero(screen, attempt + 1);
				}, MODULE_HOME_HERO_RETRY_MS);
			}
			return;
		}

		main.classList.add("lms-workspace-canvas");
		var redactor = main.querySelector(".codex-editor__redactor");
		if (!redactor) {
			if (attempt < MODULE_HOME_HERO_RETRY_MAX) {
				setTimeout(function () {
					pump_module_home_hero(screen, attempt + 1);
				}, MODULE_HOME_HERO_RETRY_MS);
			}
			return;
		}

		var injected = false;
		with_lms_dom_pause(function () {
			if (screen === "Loans") {
				inject_lending_home_hero(main);
				injected = !!redactor.querySelector(".lms-lending-hero");
			} else {
				inject_crm_home_hero(main);
				injected = !!redactor.querySelector(".lms-crm-hero");
			}
		});

		if (!injected && attempt < MODULE_HOME_HERO_RETRY_MAX) {
			setTimeout(function () {
				pump_module_home_hero(screen, attempt + 1);
			}, MODULE_HOME_HERO_RETRY_MS);
		}
	}

	function schedule_module_home_hero(screen) {
		if (!is_module_home_screen(screen)) return;
		clearTimeout(window.__lms_module_hero_kick);
		pump_module_home_hero(screen, 0);
		window.__lms_module_hero_kick = setTimeout(function () {
			pump_module_home_hero(screen, 0);
		}, MODULE_HOME_HERO_RETRY_MS);
	}

	function enhance_lms_workspace(title) {
		var main = get_workspace_main();
		if (!main) return;

		main.classList.add("lms-workspace-canvas");
		var moduleHome = is_module_home_screen(title);
		if (moduleHome) {
			schedule_module_home_hero(title);
		}

		var delay = moduleHome
			? 0
			: main.querySelector(".codex-editor__redactor")
				? 50
				: 400;

		function run_enhance() {
			with_lms_dom_pause(function () {
				if (title === "Loans") {
					inject_lending_home_hero(main);
					style_lending_section_headers(main);
				} else if (title === "CRM") {
					inject_crm_home_hero(main);
					style_lending_section_headers(main);
				} else {
					style_workspace_hero(main, title);
					style_section_headers(main);
				}
				enhance_shortcut_tiles(main);
				enhance_links_cards(main);
				mark_equal_height_blocks(main);
				prune_empty_sections(main);
				layout_tile_grid(main);
			});
		}

		if (delay) {
			setTimeout(run_enhance, delay);
		} else {
			run_enhance();
		}
	}

	function inject_lending_home_hero(main) {
		var redactor = main.querySelector(".codex-editor__redactor");
		if (!redactor || redactor.querySelector(".lms-lending-hero")) return;

		var brand = get_company_brand_name();
		var hero = document.createElement("div");
		hero.className =
			"lms-lending-hero lms-hero lms-hero--inner-shell ce-block col-xs-12";
		hero.setAttribute("data-lms-lending-hero", "1");
		hero.innerHTML =
			'<div class="lms-hero__inner">' +
			'<div class="lms-hero__copy">' +
			'<h1 class="lms-hero__title">' +
			brand +
			" Lending</h1>" +
			'<p class="lms-hero__subtitle">Applications, disbursements, collections, and portfolio analytics in one place.</p>' +
			"</div>" +
			'<div class="lms-hero__actions">' +
			'<a class="btn btn-primary btn-sm lms-hero__cta" href="' + desk_url("dashboard-view/Loan%20Dashboard") + '">Open Loan Dashboard</a>' +
			'<a class="btn btn-default btn-sm" href="' + desk_url("loan-application") + '">Loan applications</a>' +
			"</div>" +
			"</div>";
		redactor.insertBefore(hero, redactor.firstChild);
	}

	function inject_crm_home_hero(main) {
		var redactor = main.querySelector(".codex-editor__redactor");
		if (!redactor || redactor.querySelector(".lms-crm-hero")) return;

		var brand = get_company_brand_name();
		var hero = document.createElement("div");
		hero.className =
			"lms-crm-hero lms-hero lms-hero--inner-shell ce-block col-xs-12";
		hero.setAttribute("data-lms-crm-hero", "1");
		hero.innerHTML =
			'<div class="lms-hero__inner">' +
			'<div class="lms-hero__copy">' +
			'<h1 class="lms-hero__title">' +
			brand +
			" CRM</h1>" +
			'<p class="lms-hero__subtitle">Capture leads, track opportunities, and convert prospects into borrowers.</p>' +
			"</div>" +
			'<div class="lms-hero__actions">' +
			'<a class="btn btn-primary btn-sm lms-hero__cta" href="' + desk_url("lead/new") + '">New lead</a>' +
			'<a class="btn btn-default btn-sm" href="' + desk_url("lead") + '">Lead pipeline</a>' +
			'<a class="btn btn-default btn-sm" href="' + desk_url("loans") + '">Lending menu</a>' +
			"</div>" +
			"</div>";
		redactor.insertBefore(hero, redactor.firstChild);
	}

	function style_lending_section_headers(main) {
		main.querySelectorAll(".ce-header").forEach(function (header) {
			if (header.classList.contains("lms-lending-hero") || header.closest(".lms-lending-hero")) return;
			if (header.querySelector(".h4") && !header.classList.contains("lms-section-head")) {
				header.classList.add("lms-section-head", "lms-lending-section-head");
			}
			if (header.querySelector(".h5") && !header.classList.contains("lms-section-head")) {
				header.classList.add("lms-section-head");
			}
		});
	}

	function mark_equal_height_blocks(main) {
		main.querySelectorAll(".widget.links-widget-box, .widget.shortcut-widget-box").forEach(function (widget) {
			var block = widget.closest(".ce-block");
			if (block) block.classList.add("lms-equal-height-block");
		});
	}

	function enhance_links_cards(main) {
		main.querySelectorAll(".widget.links-widget-box").forEach(function (widget) {
			if (widget.classList.contains("lms-links-ready")) return;
			widget.classList.add("lms-links-ready", "lms-links-card");

			var titleEl = widget.querySelector(".widget-title .widget-label");
			var title = titleEl ? titleEl.textContent.trim() : "";
			if (title && titleEl && !titleEl.querySelector(".lms-links-card__icon")) {
				var icon = document.createElement("span");
				icon.className = "lms-links-card__icon";
				icon.setAttribute("aria-hidden", "true");
				icon.innerHTML =
					'<svg class="es-icon es-line icon-sm"><use href="#' +
					link_card_icon(title) +
					'"></use></svg>';
				titleEl.insertBefore(icon, titleEl.firstChild);
			}
		});
	}

	function link_card_icon(cardTitle) {
		var map = {
			Loan: "es-line-loan",
			"Loan Processes": "es-line-settings",
			"Disbursement and Repayment": "es-line-payments",
			"Loan Security": "es-line-lock",
			Reports: "es-line-reports",
			"Loan Classification": "es-line-chart",
			Banking: "es-line-bank",
		};
		return map[cardTitle] || "es-line-folder";
	}

	function style_section_headers(main) {
		main.querySelectorAll(".ce-header .h5").forEach(function (heading) {
			var header = heading.closest(".ce-header");
			if (!header || header.classList.contains("lms-section-head")) return;
			header.classList.add("lms-section-head");
		});
	}

	function enhance_shortcut_tiles(main) {
		main.querySelectorAll(".widget.shortcut-widget-box").forEach(function (widget) {
			if (widget.classList.contains("lms-tile-ready")) return;

			var titleEl = widget.querySelector(".widget-title span");
			var title = titleEl ? titleEl.textContent.trim() : "";
			var meta = TILE_COPY[title] || {
				desc: "Open this workspace action",
				icon: "es-line-arrow-up-right",
				tone: "blue",
			};
			var pill = widget.querySelector(".indicator-pill");
			var count = pill ? (pill.textContent || "").trim() : "";
			var countLabel = meta.countLabel || "items";

			widget.classList.add("lms-tile-ready", "lms-action-tile", "lms-tile--" + (meta.tone || "blue"));

			var subtitle = widget.querySelector(".widget-subtitle");
			if (subtitle) subtitle.textContent = meta.desc;

			var head = widget.querySelector(".widget-head");
			if (head && !head.querySelector(".lms-tile-icon")) {
				var iconWrap = document.createElement("div");
				iconWrap.className = "lms-tile-icon";
				iconWrap.setAttribute("aria-hidden", "true");
				iconWrap.innerHTML =
					'<svg class="es-icon es-line icon-md"><use href="#' + meta.icon + '"></use></svg>';
				head.insertBefore(iconWrap, head.firstChild);
			}

			var footer = widget.querySelector(".lms-tile-footer") || widget.querySelector(".widget-footer");
			if (!footer) {
				footer = document.createElement("div");
				footer.className = "widget-footer lms-tile-footer";
				widget.appendChild(footer);
			} else {
				footer.classList.add("lms-tile-footer");
			}

			var countText = count;
			if (count && countLabel && !/\s/.test(count)) {
				countText = count + " " + countLabel;
			}
			footer.innerHTML =
				(countText
					? '<span class="lms-tile-count">' + countText + "</span>"
					: '<span class="lms-tile-count lms-tile-count--muted">Ready</span>') +
				'<span class="lms-tile-action">Open<svg class="es-icon es-line icon-xs" aria-hidden="true">' +
				'<use href="#es-line-arrow-up-right"></use></svg></span>';
		});
	}

	function style_workspace_hero(main, title) {
		var firstHeader = main.querySelector(".ce-block .ce-header");
		if (!firstHeader) return;

		if (!firstHeader.classList.contains("lms-hero-styled")) {
			firstHeader.classList.add("lms-hero-styled", "lms-workspace-hero");
		}

		if (!firstHeader.querySelector(".lms-hero__inner")) {
			var inner = document.createElement("div");
			inner.className = "lms-hero__inner";
			while (firstHeader.firstChild) {
				inner.appendChild(firstHeader.firstChild);
			}
			firstHeader.appendChild(inner);
			firstHeader.classList.add("lms-hero--inner-shell");
		}

		var subtitle = firstHeader.querySelector(".text-muted");
		if (subtitle) {
			subtitle.classList.add("lms-hero__subtitle");
			subtitle.removeAttribute("style");
		}
		var titleWrap = firstHeader.querySelector(".h4");
		if (titleWrap) {
			titleWrap.classList.add("lms-hero__title-wrap");
		}

		if (title) {
			firstHeader.setAttribute("data-lms-screen", title);
		}
	}

	function prune_empty_sections(main) {
		var blocks = Array.prototype.slice.call(main.querySelectorAll(".ce-block"));
		var i = 0;
		while (i < blocks.length) {
			var block = blocks[i];
			var isSubHeader = !!block.querySelector(".ce-header .h5");
			if (!isSubHeader) {
				i++;
				continue;
			}
			var j = i + 1;
			var hasContent = false;
			var between = [];
			while (j < blocks.length && !blocks[j].querySelector(".ce-header")) {
				var widget = blocks[j].querySelector(".widget");
				if (widget && !widget.classList.contains("spacer")) hasContent = true;
				between.push(blocks[j]);
				j++;
			}
			if (!hasContent) {
				block.classList.add("lms-empty-section");
				between.forEach(function (b) { b.classList.add("lms-empty-section"); });
			}
			i = j;
		}
	}

	function run_sync() {
		if (window.__lms_sync_running || lms_dom_paused()) return;
		window.__lms_sync_running = true;
		try {
			bind_loan_dashboard_hero_hooks();
			bind_company_form_hero_hooks();
			bind_lending_doctype_hero_hooks();
			sync_lms_workspace_flag();
			sync_company_form_flag();
			sync_lms_form_doctype_flag();
			sync_query_report_flag();
			sync_lms_app_nav();
			inject_dashboard_hero();
			inject_company_form_hero();
			if (is_loan_application_route()) {
				var laCtx = get_lms_form_doctype_route();
				if (laCtx && laCtx.mode === "form") {
					inject_loan_application_form_hero();
				} else if (laCtx && laCtx.mode === "list") {
					inject_loan_application_list_hero();
				}
			}
		} finally {
			window.__lms_sync_running = false;
		}
	}

	function schedule_sync(run_now) {
		if (lms_dom_paused()) return;
		clearTimeout(window.__lms_sync_debounce_timer);
		clearTimeout(window.__lms_sync_followup_timer);
		if (run_now) {
			run_sync();
		}
		window.__lms_sync_debounce_timer = setTimeout(run_sync, SYNC_DEBOUNCE_MS);
		window.__lms_sync_followup_timer = setTimeout(run_sync, SYNC_FOLLOWUP_MS);
	}

	function init_lms_desk() {
		if (!window.frappe || window.__lms_desk_initialized) return;
		window.__lms_desk_initialized = true;
		if (window.lms_theme && lms_theme.apply) {
			lms_theme.apply(frappe.boot && frappe.boot.lms_theme);
		}
		document.body.classList.add("lms-desk-enhanced");
		bind_loan_dashboard_hero_hooks();
		bind_company_form_hero_hooks();
		bind_lending_doctype_hero_hooks();
		restore_sidebar_collapsed();
		bind_layout_responsive();
		bind_sidebar_shortcuts();
		bind_help_dropdown_observer();
		if (window.lms_brand) {
			lms_brand.applyFavicon(get_brand_favicon_url());
			lms_brand.initDesk();
		}
		enforce_desk_branding();
		strip_frappe_branding_links();
		override_lms_help_dropdown();
		schedule_sync(true);

		if (frappe.router && frappe.router.on) {
			frappe.router.on("change", function () {
				debounce_lms("route_sync", function () {
					var screen = current_lms_screen();
					if (screen === "Loans" || screen === "CRM") {
						refresh_workspace_observers();
						schedule_module_home_hero(screen);
					}
					schedule_sync(true);
				}, 60);
			});
		}

		$(document).on("app_ready", function () {
			var screen = current_lms_screen();
			if (screen === "Loans" || screen === "CRM") {
				refresh_workspace_observers();
				schedule_module_home_hero(screen);
			}
			schedule_sync(true);
		});

		$(document).on("page-change", function () {
			setTimeout(function () {
				enforce_desk_branding();
				strip_frappe_branding_links();
				override_lms_help_dropdown();
				var screen = current_lms_screen();
				if (screen === "Loans" || screen === "CRM") {
					refresh_workspace_observers();
					schedule_module_home_hero(screen);
				}
				schedule_sync(true);
			}, 200);
		});

		new MutationObserver(function () {
			if (lms_dom_paused()) return;
			var screen = current_lms_screen();
			if (screen === "Loans" || screen === "CRM") {
				debounce_lms("module_hero_route", function () {
					refresh_workspace_observers();
					schedule_module_home_hero(screen);
				}, OBS_DEBOUNCE_MS);
			}
			schedule_sync();
		}).observe(document.body, { attributes: true, attributeFilter: ["data-route"] });

		refresh_workspace_observers();
	}

	function bind_workspace_content_observer() {
		var root = get_workspace_main();
		if (!root || !root.isConnected) return;
		if (window.__lms_workspace_obs_bound && window.__lms_workspace_obs_root === root) {
			return;
		}
		if (window.__lms_workspace_obs) {
			window.__lms_workspace_obs.disconnect();
		}

		window.__lms_workspace_obs_bound = true;
		window.__lms_workspace_obs_root = root;
		window.__lms_workspace_obs = new MutationObserver(function () {
			if (lms_dom_paused() || !document.body.classList.contains("lms-desk-enhanced")) return;
			var screen = current_lms_screen();
			if (!screen) return;
			if (screen === "Loans" || screen === "CRM") {
				debounce_lms("module_hero_obs", function () {
					pump_module_home_hero(screen, 0);
				}, OBS_DEBOUNCE_MS);
			}
			debounce_lms("workspace_enhance", function () {
				enhance_lms_workspace(screen);
			}, 200);
		});
		window.__lms_workspace_obs.observe(root, { childList: true, subtree: true });
	}

	function refresh_workspace_observers() {
		bind_workspace_content_observer();
	}

	function bootstrap_lms_desk() {
		if (!window.frappe || typeof frappe.get_route !== "function") return;
		init_lms_desk();
	}

	function wait_for_frappe(tries) {
		if (window.frappe && typeof frappe.get_route === "function") {
			if (typeof frappe.ready === "function") {
				frappe.ready(bootstrap_lms_desk);
				return;
			}
			if (frappe.boot && frappe.boot.sitename) {
				bootstrap_lms_desk();
				return;
			}
		}
		if ((tries || 0) > 200) return;
		setTimeout(function () { wait_for_frappe((tries || 0) + 1); }, 50);
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", function () { wait_for_frappe(0); });
	} else {
		wait_for_frappe(0);
	}

	if (window.$) {
		$(document).on("startup", bootstrap_lms_desk);
	}
})();
