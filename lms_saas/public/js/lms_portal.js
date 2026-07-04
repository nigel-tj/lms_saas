/* LMS borrower portal — UX-focused UI */
frappe.provide("lms_portal");

lms_portal.escape = function (s) {
	const d = document.createElement("div");
	d.textContent = s == null ? "" : String(s);
	return d.innerHTML;
};

lms_portal.formatDate = function (value) {
	if (!value) return "—";
	if (typeof frappe !== "undefined" && frappe.datetime && frappe.datetime.str_to_user) {
		return frappe.datetime.str_to_user(value);
	}
	return String(value).slice(0, 10);
};

lms_portal.skeleton = function (rows) {
	let html = '<div class="lms-skeleton-grid" aria-hidden="true">';
	for (let i = 0; i < (rows || 2); i++) {
		html += '<div class="lms-skeleton-card"><div class="lms-skeleton-line lms-skeleton-line--short"></div>';
		html += '<div class="lms-skeleton-line"></div><div class="lms-skeleton-line lms-skeleton-line--medium"></div></div>';
	}
	html += "</div>";
	return html;
};

lms_portal.loading = function (message) {
	var text = lms_portal.escape(message || "Loading…");
	if (window.lms_brand && lms_brand.loadingHtml) {
		return lms_brand.loadingHtml(text);
	}
	var favicon =
		window.lms_brand && lms_brand.faviconUrl
			? lms_brand.faviconUrl()
			: "/assets/lms_saas/images/lms-favicon.svg";
	return (
		'<div class="lms-loading" role="status" aria-live="polite">' +
		'<img class="lms-brand-loader" src="' +
		favicon +
		'" width="40" height="40" alt="Loading">' +
		"<p>" +
		text +
		"</p></div>"
	);
};

lms_portal.error = function (message, retryFn) {
	const id = "lms-retry-" + Date.now();
	let html =
		'<div class="lms-error" role="alert">' +
		"<p>" +
		lms_portal.escape(message) +
		"</p>";
	if (retryFn) {
		html +=
			'<button type="button" class="lms-btn lms-btn--primary" id="' +
			id +
			'">Try again</button>';
	}
	html += "</div>";
	setTimeout(function () {
		const btn = document.getElementById(id);
		if (btn) btn.onclick = retryFn;
	}, 0);
	return html;
};

lms_portal.badgeClass = function (dpd, status) {
	if ((dpd || 0) > 90) return "lms-badge--npa";
	if ((dpd || 0) > 30) return "lms-badge--watch";
	if (status === "Disbursed" || status === "Active") return "lms-badge--current";
	return "lms-badge--default";
};

lms_portal.badgeLabel = function (dpd, status) {
	if ((dpd || 0) > 90) return "NPA";
	if ((dpd || 0) > 30) return "Watchlist";
	return status || "Active";
};

lms_portal.simpleBars = function (rows, options) {
	options = options || {};
	if (!rows || !rows.length) {
		return '<p class="lms-muted">No data yet.</p>';
	}
	const asCount = options.format === "count";
	const max = Math.max.apply(
		null,
		rows.map(function (row) {
			return row.value || 0;
		})
	);
	return (
		'<div class="lms-mini-bars">' +
		rows
			.map(function (row) {
				const width = max > 0 ? Math.max(6, Math.round(((row.value || 0) / max) * 100)) : 0;
				const display = asCount
					? lms_portal.escape(row.value || 0)
					: format_currency(row.value || 0);
				return (
					'<div class="lms-mini-row"><div class="lms-mini-row-head"><span>' +
					lms_portal.escape(row.label || "") +
					"</span><strong>" +
					display +
					'</strong></div><div class="lms-mini-track"><span style="width:' +
					width +
					'%"></span></div></div>'
				);
			})
			.join("") +
		"</div>"
	);
};

lms_portal._renderOrFallback = function (el, renderFn, fallbackFn) {
	// Try to render a chart; if the chart library is missing, use the fallback.
	try {
		var result = renderFn(el);
		if (result) return result;
	} catch (e) {
		// fall through
	}
	if (fallbackFn) {
		return fallbackFn(el);
	}
	el.innerHTML = '<p class="lms-muted">Chart could not be rendered.</p>';
};

lms_portal.renderSummary = function (container, summary) {
	if (!container || !summary) {
		if (container) container.innerHTML = "";
		return;
	}
	const next = summary.next_due;
	let nextHtml = '<span class="lms-summary-next">No upcoming payment</span>';
	if (next && next.payment_date) {
		nextHtml =
			'<span class="lms-summary-next">Next due <strong>' +
			lms_portal.formatDate(next.payment_date) +
			"</strong> · " +
			format_currency(next.total_payment) +
			(next.loan ? ' · <a href="/lms/loan?name=' + encodeURIComponent(next.loan) + '">View loan</a>' : "") +
			"</span>";
	}
	container.innerHTML =
		'<section class="lms-summary" aria-label="Account overview">' +
		'<div class="lms-summary-card">' +
		'<div class="lms-summary-label">Total outstanding</div>' +
		'<div class="lms-summary-value">' +
		format_currency(summary.total_outstanding) +
		"</div></div>" +
		'<div class="lms-summary-card">' +
		'<div class="lms-summary-label">Active loans</div>' +
		'<div class="lms-summary-value">' +
		lms_portal.escape(summary.active_count || 0) +
		"</div></div>" +
		'<div class="lms-summary-card">' +
		'<div class="lms-summary-label">At risk accounts</div>' +
		'<div class="lms-summary-value">' +
		lms_portal.escape(summary.at_risk_count || 0) +
		"</div></div>" +
		'<div class="lms-summary-card">' +
		'<div class="lms-summary-label">Delinquency ratio</div>' +
		'<div class="lms-summary-value">' +
		lms_portal.escape(((summary.delinquency_ratio || 0) * 100).toFixed(1)) +
		"%</div></div>" +
		'<div class="lms-summary-card lms-summary-card--wide">' +
		'<div class="lms-summary-label">Upcoming</div>' +
		nextHtml +
		"</div></section>";
};

lms_portal.renderDashboardPanels = function (payload) {
	const dashboard = payload && payload.dashboard ? payload.dashboard : {};
	const riskEl = document.getElementById("lms-portal-risk");
	const loanMixEl = document.getElementById("lms-portal-loan-mix");
	const upcomingEl = document.getElementById("lms-portal-upcoming");
	if (riskEl) {
		const buckets = dashboard.bucket_totals || {};
		riskEl.innerHTML = lms_portal.simpleBars([
			{ label: "Current", value: buckets.current || 0 },
			{ label: "PAR 30+", value: buckets.par30 || 0 },
			{ label: "PAR 60+", value: buckets.par60 || 0 },
			{ label: "PAR 90+", value: buckets.par90 || 0 },
		]);
	}
	if (loanMixEl) {
		const mix = dashboard.loan_mix || {};
		loanMixEl.innerHTML = lms_portal.simpleBars(
			[
				{ label: "Current", value: mix.current || 0 },
				{ label: "Watchlist", value: mix.watchlist || 0 },
				{ label: "NPA", value: mix.npa || 0 },
			],
			{ format: "count" }
		);
	}
	if (upcomingEl) {
		upcomingEl.innerHTML = lms_portal.simpleBars(dashboard.upcoming_due || []);
	}
};

lms_portal.renderLoans = function (container, payload) {
	const loans = payload && payload.loans ? payload.loans : payload;
	const summaryEl = document.getElementById("lms-portal-summary");
	if (summaryEl && payload && payload.summary) {
		lms_portal.renderSummary(summaryEl, payload.summary);
	}
	lms_portal.renderDashboardPanels(payload);

	if (!loans || !loans.length) {
		container.innerHTML =
			'<div class="lms-empty" role="status">' +
			'<div class="lms-empty-icon" aria-hidden="true">◇</div>' +
			"<h3>No loans yet</h3>" +
			"<p>When a loan is linked to your account, it will appear here.</p>" +
			'<p class="lms-empty-hint">Need help? Contact your lender support team.</p></div>';
		return;
	}

	container.innerHTML =
		'<div class="lms-grid" role="list">' +
		loans
			.map(function (loan) {
				const badge = lms_portal.badgeClass(loan.dpd, loan.status);
				const label = lms_portal.badgeLabel(loan.dpd, loan.status);
				const href = "/lms/loan?name=" + encodeURIComponent(loan.name);
				return (
					'<article class="lms-card" role="listitem">' +
					'<a class="lms-card-link" href="' +
					href +
					'" aria-label="View loan ' +
					lms_portal.escape(loan.name) +
					'">' +
					'<span class="lms-badge ' +
					badge +
					'">' +
					lms_portal.escape(label) +
					"</span>" +
					'<h3 class="lms-card-title">' +
					lms_portal.escape(loan.name) +
					"</h3>" +
					'<dl class="lms-card-meta">' +
					"<div><dt>Outstanding</dt><dd>" +
					format_currency(loan.outstanding) +
					"</dd></div>" +
					"<div><dt>Days past due</dt><dd>" +
					lms_portal.escape(loan.dpd || 0) +
					"</dd></div>" +
					"<div><dt>Rate</dt><dd>" +
					lms_portal.escape(loan.rate_of_interest || 0) +
					"%</dd></div>" +
					"</dl>" +
					'<span class="lms-card-cta">View details →</span>' +
					"</a></article>"
				);
			})
			.join("") +
		"</div>";

	// Pagination: "Load more" button
	var totalCount = (payload && payload.total_count) || loans.length;
	var showingCount = loans.length;
	if (showingCount < totalCount) {
		container.innerHTML +=
			'<div class="lms-load-more">' +
			'<p class="lms-muted">Showing ' +
			showingCount +
			" of " +
			totalCount +
			"</p>" +
			'<button type="button" class="lms-btn lms-btn--ghost" id="lms-load-more-btn">Load more</button>' +
			"</div>";
	}

	var loadMoreBtn = document.getElementById("lms-load-more-btn");
	if (loadMoreBtn) {
		loadMoreBtn.addEventListener("click", function () {
			loadMoreBtn.disabled = true;
			loadMoreBtn.textContent = "Loading…";
			lms_portal._loadMoreLoans(container);
		});
	}
};

lms_portal.renderLoanDetail = function (container, data, loanId) {
	if (!data) {
		container.innerHTML = lms_portal.error("Unable to load loan details.", function () {
			lms_portal.initLoanDetailPage();
		});
		return;
	}
	const loan = data.loan || {};
	const dpd = data.dpd || 0;
	const badge = lms_portal.badgeClass(dpd, loan.status);
	const badgeLabel = lms_portal.badgeLabel(dpd, loan.status);

	let html = '<div class="lms-detail-hero">';
	html += '<span class="lms-badge ' + badge + '">' + lms_portal.escape(badgeLabel) + "</span>";
	if ((dpd || 0) > 0) {
		html +=
			'<p class="lms-detail-alert">' +
			lms_portal.escape(dpd) +
			' days past due — please <a href="mailto:' +
			lms_portal.escape(window.__lms_support_email || "support@kesari") +
			'">contact support</a> if you need assistance.</p>';
	}
	html += "</div>";

	html += '<div class="lms-stat-row">';
	html +=
		'<div class="lms-stat"><div class="lms-stat-label">Outstanding</div><div class="lms-stat-value">' +
		format_currency(data.outstanding) +
		"</div></div>";
	html +=
		'<div class="lms-stat"><div class="lms-stat-label">Interest rate</div><div class="lms-stat-value">' +
		lms_portal.escape(loan.rate_of_interest || 0) +
		"%</div></div>";
	html +=
		'<div class="lms-stat"><div class="lms-stat-label">Status</div><div class="lms-stat-value">' +
		lms_portal.escape(loan.status || "") +
		"</div></div>";
	if (data.next_payment && data.next_payment.payment_date) {
		html +=
			'<div class="lms-stat lms-stat--highlight"><div class="lms-stat-label">Next payment</div><div class="lms-stat-value lms-stat-value--sm">' +
			lms_portal.formatDate(data.next_payment.payment_date) +
			"<br><span>" +
			format_currency(data.next_payment.total_payment) +
			"</span></div></div>";
	}
	html += "</div>";

	html += '<div class="lms-actions">';
	html +=
		'<a class="lms-btn lms-btn--primary" href="/lms/pay?loan=' +
		encodeURIComponent(loanId) +
		'">Pay now</a>';
	html +=
		'<button type="button" class="lms-btn lms-btn--ghost" id="btn-statement">Download statement</button>';
	html +=
		'<button type="button" class="lms-btn lms-btn--ghost" id="btn-agreement">Download agreement</button>';
	html += '<a class="lms-btn lms-btn--ghost" href="/lms">← All loans</a>';
	html += "</div>";

	// Collateral section
	if (data.collateral && data.collateral.items && data.collateral.items.length) {
		html += '<h3 class="lms-section-title">Collateral</h3>';
		html +=
			'<div class="lms-table-wrap"><table class="lms-table"><thead><tr><th>Asset</th><th>Type</th><th>Net realizable value</th><th>Allocated</th></tr></thead><tbody>';
		data.collateral.items.forEach(function (item) {
			html +=
				"<tr><td>" +
				lms_portal.escape(item.collateral || "—") +
				"</td><td>" +
				lms_portal.escape(item.collateral_type || "—") +
				"</td><td>" +
				format_currency(item.net_realizable_value || 0) +
				"</td><td>" +
				format_currency(item.allocated_value || 0) +
				"</td></tr>";
		});
		html += "</tbody></table></div>";
		html +=
			'<p class="lms-muted">Coverage ratio: ' +
			lms_portal.escape((data.collateral.coverage_ratio || 0).toFixed(2)) +
			"x</p>";
	}

	// Amortization chart
	html += '<h3 class="lms-section-title">Repayment schedule</h3>';
	const schedule = data.schedule || [];
	if (!schedule.length) {
		html += '<p class="lms-muted">No schedule lines available.</p>';
	} else {
		// Amortization mini-chart (principal vs interest)
		var maxPayment = Math.max.apply(
			null,
			schedule.map(function (r) { return r.total_payment || 0; })
		);
		html += '<div class="lms-amort-chart" aria-label="Amortization chart">';
		schedule.forEach(function (row) {
			var total = row.total_payment || 0;
			var principal = row.principal_amount || 0;
			var interest = row.interest_amount || 0;
			var pPct = total > 0 ? (principal / total) * 100 : 0;
			var iPct = total > 0 ? (interest / total) * 100 : 0;
			var heightPct = maxPayment > 0 ? (total / maxPayment) * 100 : 0;
			html +=
				'<div class="lms-amort-bar" style="height:' +
				heightPct +
				'%" title="' +
				lms_portal.formatDate(row.payment_date) +
				": " +
				format_currency(total) +
				'"><div class="lms-amort-bar--principal" style="height:' +
				pPct +
				'%"></div><div class="lms-amort-bar--interest" style="height:' +
				iPct +
				'%"></div></div>';
		});
		html += "</div>";
		html +=
			'<div class="lms-amort-legend"><span class="lms-amort-legend-item"><span class="lms-amort-swatch lms-amort-swatch--principal"></span>Principal</span><span class="lms-amort-legend-item"><span class="lms-amort-swatch lms-amort-swatch--interest"></span>Interest</span></div>';

		// Schedule table
		html +=
			'<div class="lms-table-wrap"><table class="lms-table"><thead><tr><th>Due date</th><th>Principal</th><th>Interest</th><th>Total</th><th>Status</th></tr></thead><tbody>';
		schedule.forEach(function (row) {
			const state = row.schedule_state || "upcoming";
			const stateLabel =
				state === "past"
					? "Paid / past"
					: state === "due_today"
						? "Due today"
						: "Upcoming";
			html +=
				'<tr class="lms-row--' +
				state +
				'"><td>' +
				lms_portal.formatDate(row.payment_date) +
				"</td><td>" +
				format_currency(row.principal_amount || 0) +
				"</td><td>" +
				format_currency(row.interest_amount || 0) +
				"</td><td>" +
				format_currency(row.total_payment) +
				'</td><td><span class="lms-pill lms-pill--' +
				state +
				'">' +
				stateLabel +
				"</span></td></tr>";
		});
		html += "</tbody></table></div>";
	}

	if (data.repayments && data.repayments.length) {
		html += '<h3 class="lms-section-title">Payment history</h3>';
		html +=
			'<div class="lms-table-wrap"><table class="lms-table"><thead><tr><th>Date</th><th>Amount</th><th>Reference</th></tr></thead><tbody>';
		data.repayments.forEach(function (row) {
			html +=
				"<tr><td>" +
				lms_portal.formatDate(row.posting_date) +
				"</td><td>" +
				format_currency(row.amount_paid) +
				"</td><td>" +
				lms_portal.escape(row.name) +
				"</td></tr>";
		});
		html += "</tbody></table></div>";
	}

	container.innerHTML = html;

	const btn = document.getElementById("btn-statement");
	if (btn) {
		btn.onclick = function () {
			btn.disabled = true;
			btn.textContent = "Preparing PDF…";
			window.open(
				"/api/method/lms_saas.api.documents.download_loan_statement_pdf?loan_id=" +
					encodeURIComponent(loanId),
				"_blank"
			);
			setTimeout(function () {
				btn.disabled = false;
				btn.textContent = "Download statement";
			}, 2000);
		};
	}
	const btnAgreement = document.getElementById("btn-agreement");
	if (btnAgreement) {
		btnAgreement.onclick = function () {
			btnAgreement.disabled = true;
			btnAgreement.textContent = "Preparing PDF…";
			window.open(
				"/api/method/lms_saas.api.documents.download_loan_agreement_pdf?loan_id=" +
					encodeURIComponent(loanId),
				"_blank"
			);
			setTimeout(function () {
				btnAgreement.disabled = false;
				btnAgreement.textContent = "Download agreement";
			}, 2000);
		};
	}
};

lms_portal._loansState = { offset: 0, pageSize: 20, total: 0, allLoans: [] };

lms_portal.initLoansPage = function () {
	const el = document.getElementById("lms-portal-loans");
	const summaryEl = document.getElementById("lms-portal-summary");
	const riskEl = document.getElementById("lms-portal-risk");
	const loanMixEl = document.getElementById("lms-portal-loan-mix");
	const upcomingEl = document.getElementById("lms-portal-upcoming");
	if (!el) return;
	if (summaryEl) summaryEl.innerHTML = lms_portal.skeleton(1);
	if (riskEl) riskEl.innerHTML = lms_portal.skeleton(1);
	if (loanMixEl) loanMixEl.innerHTML = lms_portal.skeleton(1);
	if (upcomingEl) upcomingEl.innerHTML = lms_portal.skeleton(1);
	el.innerHTML = lms_portal.loading("Loading your loans…");

	lms_portal._loansState = { offset: 0, pageSize: 20, total: 0, allLoans: [] };

	frappe.call({
		method: "lms_saas.api.portal.get_my_loans",
		args: { limit_start: 0, limit_page_length: lms_portal._loansState.pageSize },
		callback: function (r) {
			if (r.message && r.message.no_customer_linked) {
				if (summaryEl) summaryEl.innerHTML = "";
				if (riskEl) riskEl.innerHTML = "";
				if (loanMixEl) loanMixEl.innerHTML = "";
				if (upcomingEl) upcomingEl.innerHTML = "";
				el.innerHTML =
					'<div class="lms-empty" role="status">' +
					"<h3>No borrower profile linked</h3>" +
					"<p>Your login is active, but no Customer record is connected to this account.</p>" +
					'<p class="lms-empty-hint">Ask your loan officer/admin to link this user to a Customer profile.</p></div>';
				return;
			}
			lms_portal._loansState.total = (r.message && r.message.total_count) || 0;
			lms_portal._loansState.allLoans = (r.message && r.message.loans) || [];
			lms_portal._loansState.offset = lms_portal._loansState.allLoans.length;
			lms_portal.renderLoans(el, r.message);
		},
		error: function () {
			if (summaryEl) summaryEl.innerHTML = "";
			if (riskEl) riskEl.innerHTML = "";
			if (loanMixEl) loanMixEl.innerHTML = "";
			if (upcomingEl) upcomingEl.innerHTML = "";
			el.innerHTML = lms_portal.error("Could not load loans. Check your connection and try again.", function () {
				lms_portal.initLoansPage();
			});
		},
	});
};

lms_portal._loadMoreLoans = function (container) {
	var state = lms_portal._loansState;
	if (state.offset >= state.total) return;
	frappe.call({
		method: "lms_saas.api.portal.get_my_loans",
		args: { limit_start: state.offset, limit_page_length: state.pageSize },
		callback: function (r) {
			var newLoans = (r.message && r.message.loans) || [];
			state.allLoans = state.allLoans.concat(newLoans);
			state.offset = state.allLoans.length;
			lms_portal.renderLoans(container, { loans: state.allLoans, total_count: state.total });
		},
	});
};

lms_portal.initLoanDetailPage = function () {
	const params = new URLSearchParams(window.location.search);
	const name = params.get("name");
	if (!name) {
		window.location.href = "/lms";
		return;
	}
	const titleEl = document.getElementById("loan-title");
	if (titleEl) titleEl.textContent = name;
	const el = document.getElementById("loan-detail");
	if (!el) return;
	el.innerHTML = lms_portal.loading("Loading loan…");

	frappe.call({
		method: "lms_saas.api.portal.get_loan_detail",
		args: { loan_id: name },
		callback: function (r) {
			lms_portal.renderLoanDetail(el, r.message, name);
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load loan details.", function () {
				lms_portal.initLoanDetailPage();
			});
		},
	});
};

lms_portal.renderPortalHeader = function (shell) {
	const brand = (shell && shell.brand) || {};
	const navActive = (shell && shell.nav_active) || "account";
	const showStaff = shell && shell.show_staff_desk;
	const title = lms_portal.escape(brand.portal_title || "Kesari");
	const tagline = lms_portal.escape(brand.tagline || "Stewardship in every repayment");
	const logo = brand.logo_url
		? '<div class="lms-portal-logo"><img src="' + lms_portal.escape(brand.logo_url) + '" alt="Logo"></div>'
		: '<div class="lms-portal-logo">K</div>';

	let nav =
		'<a href="/lms"' + (navActive === "loans" ? ' class="is-active"' : "") + ">My Loans</a>" +
		'<a href="/lms/account"' + (navActive === "account" ? ' class="is-active"' : "") + ">My Account</a>";
	if (showStaff) {
		nav += '<a href="' + (window.__lms_desk_home || "/desk/lending") + '">Staff desk</a>';
	}
	nav += '<a href="/?cmd=web_logout">Log out</a>';

	return (
		'<div class="lms-portal-wrap lms-portal-wrap--legacy">' +
		'<header class="lms-portal-header">' +
		'<div class="lms-portal-brand">' +
		logo +
		"<div><h1 class=\"lms-portal-title\">" +
		title +
		"</h1><p class=\"lms-portal-tagline\">" +
		tagline +
		"</p></div></div>" +
		'<nav class="lms-portal-nav" aria-label="Portal navigation">' +
		nav +
		"</nav></header>"
	);
};

lms_portal.mountLegacyChrome = function () {
	if (document.querySelector(".lms-portal-wrap")) {
		return;
	}

	frappe.call({
		method: "lms_saas.api.portal.get_portal_shell",
		callback: function (r) {
			const shell = r.message || {};
			const wrap = document.createElement("div");
			wrap.innerHTML = lms_portal.renderPortalHeader(shell);
			const headerWrap = wrap.firstChild;
			document.body.insertBefore(headerWrap, document.body.firstChild);

			const main = document.querySelector(".page_content, .page-content-wrapper, main");
			if (main) {
				main.classList.add("lms-portal-board", "lms-portal-board--legacy");
			}

			const footer = document.createElement("footer");
			footer.className = "lms-portal-footer";
			footer.textContent = (shell.brand && shell.brand.footer_text) || "Powered by Kesari";
			document.body.appendChild(footer);
		},
	});
};

lms_portal.initApplyPage = function () {
	var root = document.getElementById("lms-apply-root");
	if (!root) return;
	root.innerHTML = lms_portal.loading("Loading application form…");

	var wizardState = {
		step: 1,
		products: [],
		compliance: {},
		selectedProduct: null,
		loanAmount: 0,
		repaymentPeriods: 6,
		idDoc: null,
		addressDoc: null,
		estimate: null,
	};

	frappe.call({
		method: "lms_saas.api.portal.get_apply_context",
		callback: function (r) {
			var ctx = r.message || {};
			wizardState.products = ctx.products || [];
			wizardState.compliance = ctx.compliance || {};
			if (!wizardState.compliance.consent_given) {
				root.innerHTML =
					'<div class="lms-error" role="alert"><p>Consent is required before applying. Contact your loan officer.</p></div>';
				return;
			}
			lms_portal._renderApplyWizard(root, wizardState);
		},
		error: function () {
			root.innerHTML = lms_portal.error("Could not load the application form.", function () {
				lms_portal.initApplyPage();
			});
		},
	});
};

lms_portal._renderApplyWizard = function (root, state) {
	root.innerHTML = lms_portal._applyWizardHtml(state);
	lms_portal._bindWizardEvents(root, state);
};

lms_portal._applyWizardHtml = function (state) {
	var steps = [
		'<div class="lms-wizard" id="lms-apply-wizard">',
		'<div class="lms-wizard__steps">',
		'<div class="lms-wizard__step' + (state.step >= 1 ? " is-active" : "") + '"><span class="lms-wizard__num">1</span><span class="lms-wizard__label">Product</span></div>',
		'<div class="lms-wizard__step' + (state.step >= 2 ? " is-active" : "") + '"><span class="lms-wizard__num">2</span><span class="lms-wizard__label">Amount</span></div>',
		'<div class="lms-wizard__step' + (state.step >= 3 ? " is-active" : "") + '"><span class="lms-wizard__num">3</span><span class="lms-wizard__label">Documents</span></div>',
		'<div class="lms-wizard__step' + (state.step >= 4 ? " is-active" : "") + '"><span class="lms-wizard__num">4</span><span class="lms-wizard__label">Review</span></div>',
		"</div>",
		'<div class="lms-wizard__body" id="lms-wizard-body">',
		lms_portal._applyStepHtml(state),
		"</div>",
		'<div class="lms-wizard__nav">',
		state.step > 1 ? '<button type="button" class="lms-btn lms-btn--ghost" id="lms-wizard-back">← Back</button>' : '<span></span>',
		state.step < 4
			? '<button type="button" class="lms-btn lms-btn--primary" id="lms-wizard-next">Continue →</button>'
			: '<button type="button" class="lms-btn lms-btn--primary" id="lms-wizard-submit">Submit application</button>',
		"</div>",
		"</div>",
	].join("");
	return steps;
};

lms_portal._applyStepHtml = function (state) {
	if (state.step === 1) {
		var cards = (state.products || [])
			.map(function (p) {
				var isSelected = state.selectedProduct === p.name;
				return (
					'<label class="lms-product-card' +
					(isSelected ? " is-selected" : "") +
					'" data-product="' +
					lms_portal.escape(p.name) +
					'">' +
					'<input type="radio" name="product" value="' +
					lms_portal.escape(p.name) +
					'"' +
					(isSelected ? " checked" : "") +
					">" +
					'<div class="lms-product-card__body">' +
					'<h4 class="lms-product-card__name">' +
					lms_portal.escape(p.product_name || p.name) +
					"</h4>" +
					'<p class="lms-product-card__rate">Interest rate: <strong>' +
					lms_portal.escape(p.rate_of_interest || 0) +
					"%</strong></p>" +
					'<p class="lms-product-card__max">Max: ' +
					format_currency(p.maximum_loan_amount || 0) +
					"</p>" +
					"</div></label>"
				);
			})
			.join("");
		return '<h3 class="lms-wizard__title">Choose a loan product</h3><div class="lms-product-grid">' + cards + "</div>";
	}
	if (state.step === 2) {
		var maxAmt = 0;
		var prod = (state.products || []).find(function (p) { return p.name === state.selectedProduct; });
		if (prod) maxAmt = prod.maximum_loan_amount || 0;
		var estimateHtml = "";
		if (state.estimate) {
			estimateHtml =
				'<div class="lms-estimate-card">' +
				'<div class="lms-estimate-row"><span>Monthly payment</span><strong>' +
				format_currency(state.estimate.monthly_payment) +
				"</strong></div>" +
				'<div class="lms-estimate-row"><span>Total payable</span><strong>' +
				format_currency(state.estimate.total_payable) +
				"</strong></div>" +
				'<div class="lms-estimate-row"><span>Total interest</span><strong>' +
				format_currency(state.estimate.total_interest) +
				"</strong></div>" +
				"</div>";
		}
		return (
			'<h3 class="lms-wizard__title">Loan amount & repayment term</h3>' +
			'<div class="lms-form">' +
			'<label>Loan amount<input type="number" id="lms-wizard-amount" class="lms-input" value="' +
			(state.loanAmount || "") +
			'" min="1"' +
			(maxAmt ? ' max="' + maxAmt + '"' : "") +
			' required></label>' +
			'<label>Repayment periods (months)<input type="number" id="lms-wizard-periods" class="lms-input" value="' +
			(state.repaymentPeriods || 6) +
			'" min="1" max="60"></label>' +
			"</div>" +
			'<div id="lms-estimate-container">' +
			estimateHtml +
			"</div>"
		);
	}
	if (state.step === 3) {
		return (
			'<h3 class="lms-wizard__title">Upload supporting documents</h3>' +
			'<div class="lms-form">' +
			'<div class="lms-upload-field">' +
			'<label>ID document</label>' +
			'<button type="button" class="lms-btn lms-btn--ghost" id="lms-upload-id">Upload ID document</button>' +
			'<span class="lms-upload-status" id="lms-id-status">' +
			(state.idDoc ? "✓ Uploaded" : "No file uploaded") +
			"</span>" +
			"</div>" +
			'<div class="lms-upload-field">' +
			'<label>Proof of address</label>' +
			'<button type="button" class="lms-btn lms-btn--ghost" id="lms-upload-addr">Upload proof of address</button>' +
			'<span class="lms-upload-status" id="lms-addr-status">' +
			(state.addressDoc ? "✓ Uploaded" : "No file uploaded") +
			"</span>" +
			"</div>" +
			"</div>"
		);
	}
	if (state.step === 4) {
		var prodName = state.selectedProduct || "—";
		var prod = (state.products || []).find(function (p) { return p.name === state.selectedProduct; });
		if (prod) prodName = prod.product_name || prod.name;
		return (
			'<h3 class="lms-wizard__title">Review & submit</h3>' +
			'<div class="lms-review-card">' +
			'<div class="lms-review-row"><span>Product</span><strong>' +
			lms_portal.escape(prodName) +
			"</strong></div>" +
			'<div class="lms-review-row"><span>Amount</span><strong>' +
			format_currency(state.loanAmount || 0) +
			"</strong></div>" +
			'<div class="lms-review-row"><span>Repayment periods</span><strong>' +
			lms_portal.escape(state.repaymentPeriods || 6) +
			" months</strong></div>" +
			(state.estimate
				? '<div class="lms-review-row"><span>Monthly payment</span><strong>' +
				  format_currency(state.estimate.monthly_payment) +
				  "</strong></div>"
				: "") +
			'<div class="lms-review-row"><span>ID document</span><strong>' +
			(state.idDoc ? "✓ Uploaded" : "Not uploaded") +
			"</strong></div>" +
			'<div class="lms-review-row"><span>Proof of address</span><strong>' +
			(state.addressDoc ? "✓ Uploaded" : "Not uploaded") +
			"</strong></div>" +
			"</div>" +
			'<label class="lms-consent-check"><input type="checkbox" id="lms-wizard-consent" required> I confirm the information is accurate and consent to credit assessment.</label>'
		);
	}
	return "";
};

lms_portal._bindWizardEvents = function (root, state) {
	// Product selection
	root.querySelectorAll(".lms-product-card").forEach(function (card) {
		card.addEventListener("click", function () {
			state.selectedProduct = card.getAttribute("data-product");
			root.querySelectorAll(".lms-product-card").forEach(function (c) {
				c.classList.remove("is-selected");
			});
			card.classList.add("is-selected");
			card.querySelector("input[type=radio]").checked = true;
		});
	});

	// Amount/periods inputs
	var amountInput = document.getElementById("lms-wizard-amount");
	var periodsInput = document.getElementById("lms-wizard-periods");
	if (amountInput) {
		amountInput.addEventListener("input", function () {
			state.loanAmount = parseFloat(amountInput.value) || 0;
			lms_portal._debounceEstimate(state);
		});
	}
	if (periodsInput) {
		periodsInput.addEventListener("input", function () {
			state.repaymentPeriods = parseInt(periodsInput.value, 10) || 6;
			lms_portal._debounceEstimate(state);
		});
	}

	// File upload buttons
	var idBtn = document.getElementById("lms-upload-id");
	var addrBtn = document.getElementById("lms-upload-addr");
	if (idBtn) {
		idBtn.addEventListener("click", function () {
			lms_portal._openFileUploader("id_document_proof", function (fileUrl) {
				state.idDoc = fileUrl;
				var statusEl = document.getElementById("lms-id-status");
				if (statusEl) statusEl.textContent = "✓ Uploaded";
			});
		});
	}
	if (addrBtn) {
		addrBtn.addEventListener("click", function () {
			lms_portal._openFileUploader("proof_of_address", function (fileUrl) {
				state.addressDoc = fileUrl;
				var statusEl = document.getElementById("lms-addr-status");
				if (statusEl) statusEl.textContent = "✓ Uploaded";
			});
		});
	}

	// Nav buttons
	var backBtn = document.getElementById("lms-wizard-back");
	var nextBtn = document.getElementById("lms-wizard-next");
	var submitBtn = document.getElementById("lms-wizard-submit");

	if (backBtn) {
		backBtn.addEventListener("click", function () {
			if (state.step > 1) {
				state.step--;
				lms_portal._renderApplyWizard(root, state);
			}
		});
	}
	if (nextBtn) {
		nextBtn.addEventListener("click", function () {
			if (lms_portal._validateStep(state)) {
				state.step++;
				lms_portal._renderApplyWizard(root, state);
			}
		});
	}
	if (submitBtn) {
		submitBtn.addEventListener("click", function () {
			var consent = document.getElementById("lms-wizard-consent");
			if (consent && !consent.checked) {
				frappe.show_alert({ message: "Please confirm consent to proceed.", indicator: "orange" });
				return;
			}
			lms_portal._submitApplication(root, state);
		});
	}
};

lms_portal._debounceTimer = null;
lms_portal._debounceEstimate = function (state) {
	clearTimeout(lms_portal._debounceTimer);
	lms_portal._debounceTimer = setTimeout(function () {
		if (!state.selectedProduct || !state.loanAmount || !state.repaymentPeriods) return;
		frappe.call({
			method: "lms_saas.api.portal.get_loan_estimate",
			args: {
				loan_product: state.selectedProduct,
				loan_amount: state.loanAmount,
				repayment_periods: state.repaymentPeriods,
			},
			callback: function (r) {
				if (r.message) {
					state.estimate = r.message;
					var container = document.getElementById("lms-estimate-container");
					if (container) {
						container.innerHTML =
							'<div class="lms-estimate-card">' +
							'<div class="lms-estimate-row"><span>Monthly payment</span><strong>' +
							format_currency(r.message.monthly_payment) +
							"</strong></div>" +
							'<div class="lms-estimate-row"><span>Total payable</span><strong>' +
							format_currency(r.message.total_payable) +
							"</strong></div>" +
							'<div class="lms-estimate-row"><span>Total interest</span><strong>' +
							format_currency(r.message.total_interest) +
							"</strong></div>" +
							"</div>";
					}
				}
			},
		});
	}, 300);
};

lms_portal._validateStep = function (state) {
	if (state.step === 1 && !state.selectedProduct) {
		frappe.show_alert({ message: "Please select a loan product.", indicator: "orange" });
		return false;
	}
	if (state.step === 2) {
		if (!state.loanAmount || state.loanAmount <= 0) {
			frappe.show_alert({ message: "Please enter a loan amount.", indicator: "orange" });
			return false;
		}
		var prod = (state.products || []).find(function (p) { return p.name === state.selectedProduct; });
		if (prod && prod.maximum_loan_amount && state.loanAmount > prod.maximum_loan_amount) {
			frappe.show_alert({
				message: "Amount exceeds the maximum for this product (" + format_currency(prod.maximum_loan_amount) + ").",
				indicator: "red",
			});
			return false;
		}
	}
	return true;
};

lms_portal._openFileUploader = function (fieldname, callback) {
	new frappe.ui.FileUploader({
		folder: "Home/Attachments",
		method: "frappe.handler.upload_file",
		on_success: function (file) {
			if (file.file_url) {
				frappe.call({
					method: "lms_saas.api.portal.upload_kyc_document",
					args: { file_url: file.file_url, fieldname: fieldname },
					callback: function () {
						callback(file.file_url);
						frappe.show_alert({ message: "Document uploaded.", indicator: "green" });
					},
					error: function () {
						frappe.show_alert({ message: "Upload failed. Please try again.", indicator: "red" });
					},
				});
			}
		},
	});
};

lms_portal._submitApplication = function (root, state) {
	var submitBtn = document.getElementById("lms-wizard-submit");
	if (submitBtn) {
		submitBtn.disabled = true;
		submitBtn.textContent = "Submitting…";
	}
	frappe.call({
		method: "lms_saas.api.portal.submit_loan_application",
		args: {
			loan_amount: state.loanAmount,
			loan_product: state.selectedProduct,
			repayment_periods: state.repaymentPeriods,
		},
		callback: function (res) {
			var app = res.message || {};
			root.innerHTML =
				'<div class="lms-panel lms-success-card">' +
				'<div class="lms-success-icon">✓</div>' +
				"<h3>Application submitted!</h3>" +
				"<p>Your application reference is <strong>" +
				lms_portal.escape(app.application || "") +
				"</strong></p>" +
				'<p class="lms-muted">It is now under review. You can track its status from your applications list.</p>' +
				'<div class="lms-actions">' +
				'<a class="lms-btn lms-btn--primary" href="/lms/applications">View my applications</a>' +
				'<a class="lms-btn lms-btn--ghost" href="/lms">Back to dashboard</a>' +
				"</div></div>";
		},
		error: function () {
			if (submitBtn) {
				submitBtn.disabled = false;
				submitBtn.textContent = "Submit application";
			}
			frappe.show_alert({ message: "Submission failed. Please try again.", indicator: "red" });
		},
	});
};

lms_portal.initApplicationsPage = function () {
	var el = document.getElementById("lms-applications-root");
	if (!el) return;
	el.innerHTML = lms_portal.loading("Loading your applications…");
	frappe.call({
		method: "lms_saas.api.portal.get_my_applications",
		callback: function (r) {
			var apps = (r.message && r.message.applications) || [];
			if (!apps.length) {
				el.innerHTML =
					'<div class="lms-empty"><div class="lms-empty-icon">◇</div><h3>No applications yet</h3>' +
					'<p>When you submit a loan application, it will appear here.</p>' +
					'<a class="lms-btn lms-btn--primary" href="/lms/apply">Apply for a loan</a></div>';
				return;
			}
			el.innerHTML =
				'<div class="lms-grid" role="list">' +
				apps
					.map(function (app) {
						var statusBadge = lms_portal._applicationStatusBadge(app.status);
						return (
							'<article class="lms-card" role="listitem">' +
							'<div class="lms-card-head">' +
							'<span class="lms-badge ' +
							statusBadge.cls +
							'">' +
							lms_portal.escape(statusBadge.label) +
							"</span>" +
							'<h3 class="lms-card-title">' +
							lms_portal.escape(app.name) +
							"</h3></div>" +
							'<dl class="lms-card-meta">' +
							"<div><dt>Product</dt><dd>" +
							lms_portal.escape(app.product_name || "—") +
							"</dd></div>" +
							"<div><dt>Amount</dt><dd>" +
							format_currency(app.loan_amount || 0) +
							"</dd></div>" +
							"<div><dt>Periods</dt><dd>" +
							lms_portal.escape(app.repayment_periods || "—") +
							" months</dd></div>" +
							"<div><dt>Submitted</dt><dd>" +
							lms_portal.formatDate(app.creation) +
							"</dd></div>" +
							"</dl></article>"
						);
					})
					.join("") +
				"</div>";
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load applications.", function () {
				lms_portal.initApplicationsPage();
			});
		},
	});
};

lms_portal._applicationStatusBadge = function (status) {
	var map = {
		Draft: { cls: "lms-badge--default", label: "Draft" },
		Submitted: { cls: "lms-badge--watch", label: "Under Review" },
		Approved: { cls: "lms-badge--current", label: "Approved" },
		Rejected: { cls: "lms-badge--npa", label: "Rejected" },
	};
	return map[status] || { cls: "lms-badge--default", label: status || "Unknown" };
};

lms_portal.initPayPage = function () {
	var root = document.getElementById("lms-pay-root");
	if (!root) return;
	root.innerHTML = lms_portal.loading("Loading loans…");
	frappe.call({
		method: "lms_saas.api.portal.get_my_loans",
		callback: function (r) {
			if (r.message && r.message.no_customer_linked) {
				root.innerHTML =
					'<div class="lms-panel"><p>No borrower profile linked to this account yet.</p>' +
					"<p class=\"lms-muted\">Please ask your loan officer/admin to link your user to a Customer record.</p></div>";
				return;
			}
			var loans = (r.message && r.message.loans) || [];
			if (!loans.length) {
				root.innerHTML = '<div class="lms-panel"><p>No active loans to pay.</p></div>';
				return;
			}
			var opts = loans
				.map(function (loan) {
					return (
						'<option value="' +
						lms_portal.escape(loan.name) +
						'">' +
						lms_portal.escape(loan.name) +
						" — outstanding " +
						format_currency(loan.outstanding) +
						"</option>"
					);
				})
				.join("");
			root.innerHTML =
				'<form class="lms-panel lms-form" id="lms-pay-form">' +
				'<label>Loan<select name="loan_id" class="lms-input">' +
				opts +
				"</select></label>" +
				'<label>Amount<input type="number" name="amount" class="lms-input" min="1" required></label>' +
				'<label>Provider<select name="provider" class="lms-input"><option value="ecocash">EcoCash</option><option value="onemoney">OneMoney</option><option value="bank_transfer">Bank transfer</option></select></label>' +
				'<button type="submit" class="lms-btn lms-btn--primary">Continue</button>' +
				"</form><div id=\"lms-pay-result\"></div>";
			document.getElementById("lms-pay-form").addEventListener("submit", function (ev) {
				ev.preventDefault();
				var fd = new FormData(ev.target);
				var loanId = fd.get("loan_id");
				var amount = fd.get("amount");
				var provider = fd.get("provider");
				lms_portal._showPayConfirmation(root, loanId, amount, provider);
			});
		},
		error: function () {
			root.innerHTML = lms_portal.error("Could not load loans.", function () {
				lms_portal.initPayPage();
			});
		},
	});
};

lms_portal._showPayConfirmation = function (root, loanId, amount, provider) {
	var providerLabels = { ecocash: "EcoCash", onemoney: "OneMoney", bank_transfer: "Bank Transfer" };
	var providerLabel = providerLabels[provider] || provider;
	var resultEl = document.getElementById("lms-pay-result");
	if (!resultEl) return;
	resultEl.innerHTML =
		'<div class="lms-confirm-card" id="lms-pay-confirm">' +
		"<h3>Confirm payment</h3>" +
		'<div class="lms-confirm-row"><span>Loan</span><strong>' +
		lms_portal.escape(loanId) +
		"</strong></div>" +
		'<div class="lms-confirm-row"><span>Amount</span><strong>' +
		format_currency(amount) +
		"</strong></div>" +
		'<div class="lms-confirm-row"><span>Provider</span><strong>' +
		lms_portal.escape(providerLabel) +
		"</strong></div>" +
		'<div class="lms-confirm-actions">' +
		'<button type="button" class="lms-btn lms-btn--ghost" id="lms-pay-cancel">Cancel</button>' +
		'<button type="button" class="lms-btn lms-btn--primary" id="lms-pay-confirm-btn">Confirm & Pay</button>' +
		"</div></div>";
	document.getElementById("lms-pay-cancel").addEventListener("click", function () {
		resultEl.innerHTML = "";
	});
	document.getElementById("lms-pay-confirm-btn").addEventListener("click", function () {
		var btn = this;
		btn.disabled = true;
		btn.textContent = "Processing…";
		frappe.call({
			method: "lms_saas.api.portal.initiate_repayment",
			args: { loan_id: loanId, amount: amount, provider_code: provider },
			callback: function (res) {
				var msg = res.message || {};
				lms_portal._renderPayResult(resultEl, msg, providerLabel);
			},
			error: function () {
				btn.disabled = false;
				btn.textContent = "Confirm & Pay";
				frappe.show_alert({ message: "Payment failed. Please try again.", indicator: "red" });
			},
		});
	});
};

lms_portal._renderPayResult = function (el, msg, providerLabel) {
	if (msg.redirect_url) {
		el.innerHTML =
			'<div class="lms-panel lms-pay-result">' +
			"<h3>Redirecting to " +
			lms_portal.escape(providerLabel) +
			"…</h3>" +
			'<p class="lms-muted">Payment reference: <strong>' +
			lms_portal.escape(msg.intent || msg.external_ref || "") +
			"</strong></p>" +
			'<a class="lms-btn lms-btn--primary" href="' +
			lms_portal.escape(msg.redirect_url) +
			'">Continue to payment →</a>' +
			"</div>";
		window.location.href = msg.redirect_url;
		return;
	}
	if (msg.instructions) {
		var ins = msg.instructions || {};
		el.innerHTML =
			'<div class="lms-panel lms-bank-instructions">' +
			"<h3>Bank transfer instructions</h3>" +
			'<p class="lms-muted">Use the reference below when making your transfer. Your loan will be credited once the transfer is confirmed.</p>' +
			'<div class="lms-bank-row"><span>Bank</span><strong>' +
			lms_portal.escape(ins.bank_name || "—") +
			"</strong></div>" +
			'<div class="lms-bank-row"><span>Account name</span><strong>' +
			lms_portal.escape(ins.account_name || "—") +
			"</strong></div>" +
			'<div class="lms-bank-row"><span>Account number</span><strong>' +
			lms_portal.escape(ins.account_number || "—") +
			"</strong></div>" +
			'<div class="lms-bank-row lms-bank-row--ref"><span>Reference</span><code id="lms-bank-ref">' +
			lms_portal.escape(ins.reference || msg.external_ref || "") +
			'</code><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-copy-ref">Copy</button></div>' +
			'<p class="lms-muted lms-pay-ref">Payment reference: ' +
			lms_portal.escape(msg.intent || "") +
			"</p>" +
			"</div>";
		var copyBtn = document.getElementById("lms-copy-ref");
		if (copyBtn) {
			copyBtn.addEventListener("click", function () {
				var refEl = document.getElementById("lms-bank-ref");
				if (refEl && navigator.clipboard) {
					navigator.clipboard.writeText(refEl.textContent).then(function () {
						copyBtn.textContent = "Copied!";
						setTimeout(function () { copyBtn.textContent = "Copy"; }, 2000);
					});
				}
			});
		}
		return;
	}
	el.innerHTML =
		'<div class="lms-panel lms-pay-result">' +
		"<h3>Payment initiated</h3>" +
		'<p>Payment reference: <strong>' +
		lms_portal.escape(msg.intent || "") +
		"</strong></p>" +
		'<p class="lms-muted">Your payment is being processed.</p></div>';
};

frappe.ready(function () {
	document.body.classList.add("lms-themed");
	if (document.body.classList.contains("lms-portal-legacy")) {
		lms_portal.mountLegacyChrome();
	}
	lms_portal._initNotificationCenter();
	lms_portal._initMobileMenu();
});

lms_portal._initNotificationCenter = function () {
	var bell = document.getElementById("lms-notification-bell");
	var panel = document.getElementById("lms-notification-panel");
	var closeBtn = document.getElementById("lms-notification-close");
	var body = document.getElementById("lms-notification-body");
	var badge = document.getElementById("lms-notification-badge");
	if (!bell || !panel) return;

	bell.addEventListener("click", function () {
		var isOpen = panel.getAttribute("aria-hidden") === "false";
		if (isOpen) {
			panel.setAttribute("aria-hidden", "true");
			return;
		}
		panel.setAttribute("aria-hidden", "false");
		if (body) {
			body.innerHTML = lms_portal.loading("Loading notifications…");
		}
		frappe.call({
			method: "lms_saas.api.portal.get_portal_notifications",
			callback: function (r) {
				var data = r.message || {};
				var notifs = data.notifications || [];
				if (!notifs.length) {
					body.innerHTML = '<p class="lms-muted">No notifications.</p>';
					return;
				}
				body.innerHTML = notifs
					.map(function (n) {
						var unreadCls = n.read_on ? "" : " lms-notification-item--unread";
						return (
							'<div class="lms-notification-item' + unreadCls + '">' +
							'<p class="lms-notification-item__type">' +
							lms_portal.escape(n.reminder_type || "Notification") +
							"</p>" +
							'<p class="lms-notification-item__preview">' +
							lms_portal.escape((n.message_preview || "").slice(0, 120)) +
							"</p>" +
							'<p class="lms-notification-item__meta">' +
							lms_portal.formatDate(n.notification_date) +
							" · " +
							lms_portal.escape(n.channel || "") +
							"</p></div>"
						);
					})
					.join("");
				// Mark all as read now that the borrower has seen them.
				if (data.unread_count > 0) {
					frappe.call({
						method: "lms_saas.api.portal.mark_notifications_read",
						callback: function () {
							if (badge) badge.style.display = "none";
						},
					});
				}
			},
			error: function () {
				body.innerHTML = '<p class="lms-muted">Could not load notifications.</p>';
			},
		});
	});

	if (closeBtn) {
		closeBtn.addEventListener("click", function () {
			panel.setAttribute("aria-hidden", "true");
		});
	}

	// Load unread count
	frappe.call({
		method: "lms_saas.api.portal.get_portal_notifications",
		callback: function (r) {
			var count = (r.message && r.message.unread_count) || 0;
			if (count > 0 && badge) {
				badge.textContent = count > 99 ? "99+" : String(count);
				badge.style.display = "inline-block";
			}
		},
	});
};

lms_portal._initSidebarDrawer = function () {
	var sidebar = document.getElementById("lms-sidebar");
	var appBody = document.querySelector(".lms-app-body, .lms-main");
	var topbarBtn = document.getElementById("lms-topbar-menu-btn");
	var sidebarToggle = document.getElementById("lms-sidebar-toggle");
	if (!sidebar) return;

	// Create backdrop element for mobile overlay
	var backdrop = document.createElement("div");
	backdrop.className = "lms-sidebar-backdrop";
	backdrop.id = "lms-sidebar-backdrop";
	document.body.appendChild(backdrop);

	// Restore persisted state (desktop collapse only)
	try {
		var saved = localStorage.getItem("lms_sidebar_collapsed");
		if (saved === "1" && window.innerWidth > 900) {
			sidebar.classList.add("is-collapsed");
			if (appBody) appBody.classList.add("is-expanded");
		}
	} catch (e) {
		// localStorage may be unavailable
	}

	function isMobile() {
		return window.innerWidth <= 900;
	}

	function toggleSidebar() {
		if (isMobile()) {
			// Mobile: overlay drawer with backdrop
			var isOpen = sidebar.classList.contains("is-open");
			if (isOpen) {
				sidebar.classList.remove("is-open");
				backdrop.classList.remove("is-visible");
			} else {
				sidebar.classList.add("is-open");
				backdrop.classList.add("is-visible");
			}
		} else {
			// Desktop: collapse to icon rail or expand to full
			var isCollapsed = sidebar.classList.contains("is-collapsed");
			if (isCollapsed) {
				sidebar.classList.remove("is-collapsed");
				if (appBody) appBody.classList.remove("is-expanded");
				try { localStorage.setItem("lms_sidebar_collapsed", "0"); } catch (e) {}
			} else {
				sidebar.classList.add("is-collapsed");
				if (appBody) appBody.classList.add("is-expanded");
				try { localStorage.setItem("lms_sidebar_collapsed", "1"); } catch (e) {}
			}
		}
	}

	function closeMobileSidebar() {
		sidebar.classList.remove("is-open");
		backdrop.classList.remove("is-visible");
	}

	if (topbarBtn) {
		topbarBtn.addEventListener("click", toggleSidebar);
	}
	if (sidebarToggle) {
		sidebarToggle.addEventListener("click", toggleSidebar);
	}
	backdrop.addEventListener("click", closeMobileSidebar);

	// Close mobile sidebar on window resize to desktop
	window.addEventListener("resize", function () {
		if (!isMobile()) {
			closeMobileSidebar();
		}
	});
};

lms_portal._initMobileMenu = lms_portal._initSidebarDrawer;

lms_portal.initAccountOverview = function () {
	var el = document.getElementById("lms-account-overview");
	if (!el) return;
	el.innerHTML = lms_portal.loading("Loading account details…");
	frappe.call({
		method: "lms_saas.api.portal.get_account_overview",
		callback: function (r) {
			var data = r.message || {};
			var compliance = data.compliance || {};
			var customer = data.customer || {};
			var html = "";

			// KYC / Compliance status
			html += '<h3 class="lms-section-title">Compliance status</h3>';
			html += '<div class="lms-account">';
			html += '<article class="lms-account-card lms-panel">';
			html += '<div class="lms-account-row"><div>';
			html += '<p class="lms-account-item-title">KYC status</p>';
			var kycCls = compliance.kyc_status === "Approved" ? "lms-badge--current" : "lms-badge--watch";
			html += '<span class="lms-badge ' + kycCls + '">' + lms_portal.escape(compliance.kyc_status || "Pending") + "</span>";
			html += "</div></div></article>";

			if (compliance.aml_status) {
				html += '<article class="lms-account-card lms-panel">';
				html += '<div class="lms-account-row"><div>';
				html += '<p class="lms-account-item-title">AML status</p>';
				var amlCls = compliance.aml_status === "Clear" ? "lms-badge--current" : "lms-badge--watch";
				html += '<span class="lms-badge ' + amlCls + '">' + lms_portal.escape(compliance.aml_status) + "</span>";
				html += "</div></div></article>";
			}

			if (compliance.consent_given) {
				html += '<article class="lms-account-card lms-panel">';
				html += '<div class="lms-account-row"><div>';
				html += '<p class="lms-account-item-title">Consent</p>';
				html += '<p class="lms-account-item-desc">Consent given on ' + lms_portal.formatDate(compliance.consent_date) + "</p>";
				html += "</div></div></article>";
			}

			if (compliance.credit_score) {
				html += '<article class="lms-account-card lms-panel">';
				html += '<div class="lms-account-row"><div>';
				html += '<p class="lms-account-item-title">Credit score</p>';
				html += '<p class="lms-account-item-desc">' + lms_portal.escape(compliance.credit_score) + "</p>";
				html += "</div></div></article>";
			}
			html += "</div>";

			// Documents
			html += '<h3 class="lms-section-title">My documents</h3>';
			html += '<div class="lms-account">';
			if (compliance.id_document_proof) {
				html += '<article class="lms-account-card lms-panel"><div class="lms-account-row"><div>';
				html += '<p class="lms-account-item-title">ID document</p>';
				html += '<p class="lms-account-item-desc">Uploaded</p>';
				html += "</div>";
				html += '<a class="lms-btn lms-btn--ghost" href="' + lms_portal.escape(compliance.id_document_proof) + '" target="_blank">View</a>';
				html += "</div></article>";
			}
			if (compliance.proof_of_address) {
				html += '<article class="lms-account-card lms-panel"><div class="lms-account-row"><div>';
				html += '<p class="lms-account-item-title">Proof of address</p>';
				html += '<p class="lms-account-item-desc">Uploaded</p>';
				html += "</div>";
				html += '<a class="lms-btn lms-btn--ghost" href="' + lms_portal.escape(compliance.proof_of_address) + '" target="_blank">View</a>';
				html += "</div></article>";
			}
			if (!compliance.id_document_proof && !compliance.proof_of_address) {
				html += '<p class="lms-muted">No documents on file. Contact your loan officer to upload KYC documents.</p>';
			}
			html += "</div>";

			// Support
			html += '<h3 class="lms-section-title">Support</h3>';
			html += '<div class="lms-account">';
			html += '<article class="lms-account-card lms-panel"><div class="lms-account-row"><div>';
			html += '<p class="lms-account-item-title">Contact support</p>';
			if (customer.mobile_no) {
				html += '<p class="lms-account-item-desc">Phone: ' + lms_portal.escape(customer.mobile_no) + "</p>";
			}
			html += "</div>";
			if (window.__lms_support_email) {
				html += '<a class="lms-btn lms-btn--ghost" href="mailto:' + lms_portal.escape(window.__lms_support_email) + '">Email</a>';
			}
			html += "</div></article>";
			html += "</div>";

			el.innerHTML = html;
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load account details.", function () {
				lms_portal.initAccountOverview();
			});
		},
	});
};

/* ------------------------------------------------------------------ */
/* Toast notifications                                                 */
/* ------------------------------------------------------------------ */
lms_portal.toast = function (message, type) {
	type = type || "info"; // success | warning | danger | info
	var stack = document.getElementById("lms-toast-stack");
	if (!stack) {
		stack = document.createElement("div");
		stack.id = "lms-toast-stack";
		stack.className = "lms-toast-stack";
		stack.setAttribute("aria-live", "polite");
		document.body.appendChild(stack);
	}
	var icons = { success: "✓", warning: "!", danger: "✕", info: "i" };
	var cls = type === "info" ? "" : " lms-toast--" + type;
	var el = document.createElement("div");
	el.className = "lms-toast" + cls;
	el.innerHTML =
		'<span class="lms-toast__icon">' + (icons[type] || "i") + "</span>" +
		'<span class="lms-toast__msg">' + lms_portal.escape(message) + "</span>" +
		'<button type="button" class="lms-toast__close" aria-label="Dismiss">×</button>';
	stack.appendChild(el);
	var close = function () {
		el.style.opacity = "0";
		el.style.transform = "translateX(20px)";
		setTimeout(function () { el.remove(); }, 200);
	};
	el.querySelector(".lms-toast__close").addEventListener("click", close);
	setTimeout(close, 4500);
};

/* ------------------------------------------------------------------ */
/* Modal helper                                                        */
/* ------------------------------------------------------------------ */
lms_portal.modal = function (opts) {
	opts = opts || {};
	var root = document.getElementById("lms-modal-root");
	if (!root) {
		root = document.createElement("div");
		root.id = "lms-modal-root";
		root.className = "lms-modal-root";
		document.body.appendChild(root);
	}
	var overlay = document.createElement("div");
	overlay.className = "lms-modal-overlay";
	var sizeClass = opts.size === "lg" ? " lms-modal--lg" : "";
	overlay.innerHTML =
		'<div class="lms-modal' + sizeClass + '">' +
		'<div class="lms-modal__header"><h3>' + lms_portal.escape(opts.title || "") + "</h3>" +
		'<button type="button" class="lms-modal__close" aria-label="Close">×</button></div>' +
		'<div class="lms-modal__body">' + (opts.body || "") + "</div>" +
		'<div class="lms-modal__actions">' +
		(opts.cancelText !== null ? '<button type="button" class="lms-btn lms-btn--ghost" data-lms-modal-cancel>' + lms_portal.escape(opts.cancelText || "Cancel") + "</button>" : "") +
		(opts.confirmText ? '<button type="button" class="lms-btn lms-btn--' + (opts.confirmVariant || "primary") + '" data-lms-modal-confirm>' + lms_portal.escape(opts.confirmText) + "</button>" : "") +
		"</div></div>";
	root.appendChild(overlay);

	function close() {
		overlay.style.opacity = "0";
		setTimeout(function () { overlay.remove(); }, 150);
	}
	overlay.querySelector(".lms-modal__close").addEventListener("click", close);
	var cancelBtn = overlay.querySelector("[data-lms-modal-cancel]");
	if (cancelBtn) cancelBtn.addEventListener("click", function () { if (opts.onCancel) opts.onCancel(); close(); });
	var confirmBtn = overlay.querySelector("[data-lms-modal-confirm]");
	if (confirmBtn) confirmBtn.addEventListener("click", function () {
		if (opts.onConfirm) {
			var result = opts.onConfirm(overlay);
			if (result !== false) close();
		} else {
			close();
		}
	});
	overlay.addEventListener("click", function (e) {
		if (e.target === overlay && opts.dismissOnOverlay !== false) close();
	});
	return { close: close, el: overlay };
};
