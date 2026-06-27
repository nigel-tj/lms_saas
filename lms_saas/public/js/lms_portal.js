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
			" days past due — please contact support if you need assistance.</p>";
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
		'<button type="button" class="lms-btn lms-btn--primary" id="btn-statement">Download statement (PDF)</button>';
	html += '<a class="lms-btn lms-btn--ghost" href="/lms">← All loans</a>';
	html += "</div>";

	html += '<h3 class="lms-section-title">Repayment schedule</h3>';
	const schedule = data.schedule || [];
	if (!schedule.length) {
		html += '<p class="lms-muted">No schedule lines available.</p>';
	} else {
		html +=
			'<div class="lms-table-wrap"><table class="lms-table"><thead><tr><th>Due date</th><th>Amount</th><th>Status</th></tr></thead><tbody>';
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
				btn.textContent = "Download statement (PDF)";
			}, 2000);
		};
	}
};

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

	frappe.call({
		method: "lms_saas.api.portal.get_my_loans",
		callback: function (r) {
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
	const title = lms_portal.escape(brand.portal_title || "LMS Portal");
	const tagline = lms_portal.escape(brand.tagline || "Manage your loans securely");
	const logo = brand.logo_url
		? '<div class="lms-portal-logo"><img src="' + lms_portal.escape(brand.logo_url) + '" alt="Logo"></div>'
		: '<div class="lms-portal-logo">LMS</div>';

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
			footer.textContent = (shell.brand && shell.brand.footer_text) || "Powered by LMS SaaS";
			document.body.appendChild(footer);
		},
	});
};

lms_portal.initApplyPage = function () {
	var root = document.getElementById("lms-apply-root");
	if (!root) return;
	root.innerHTML = lms_portal.loading("Loading application form…");
	frappe.call({
		method: "lms_saas.api.portal.get_apply_context",
		callback: function (r) {
			var ctx = r.message || {};
			var compliance = ctx.compliance || {};
			if (!compliance.consent_given) {
				root.innerHTML =
					'<div class="lms-error" role="alert"><p>Consent is required before applying. Contact your loan officer.</p></div>';
				return;
			}
			var productOpts = (ctx.products || [])
				.map(function (p) {
					return (
						'<option value="' +
						lms_portal.escape(p.name) +
						'">' +
						lms_portal.escape(p.product_name || p.name) +
						"</option>"
					);
				})
				.join("");
			root.innerHTML =
				'<form class="lms-panel lms-form" id="lms-apply-form">' +
				'<label>Loan product<select name="loan_product" class="lms-input">' +
				productOpts +
				"</select></label>" +
				'<label>Amount<input type="number" name="loan_amount" class="lms-input" min="1" required></label>' +
				'<label>Repayment periods (months)<input type="number" name="repayment_periods" class="lms-input" value="6" min="1"></label>' +
				'<label>ID document URL<input type="text" name="id_doc" class="lms-input" placeholder="/files/..."></label>' +
				'<button type="submit" class="lms-btn lms-btn--primary">Submit application</button>' +
				"</form>";
			document.getElementById("lms-apply-form").addEventListener("submit", function (ev) {
				ev.preventDefault();
				var fd = new FormData(ev.target);
				frappe.call({
					method: "lms_saas.api.portal.submit_loan_application",
					args: {
						loan_amount: fd.get("loan_amount"),
						loan_product: fd.get("loan_product"),
						repayment_periods: fd.get("repayment_periods"),
					},
					callback: function (res) {
						var idDoc = fd.get("id_doc");
						if (idDoc) {
							frappe.call({
								method: "lms_saas.api.portal.upload_kyc_document",
								args: { file_url: idDoc, fieldname: "id_document_proof" },
							});
						}
						root.innerHTML =
							'<div class="lms-panel"><p>Application <strong>' +
							lms_portal.escape(res.message.application) +
							"</strong> submitted for desk review.</p></div>";
					},
				});
			});
		},
	});
};

lms_portal.initPayPage = function () {
	var root = document.getElementById("lms-pay-root");
	if (!root) return;
	root.innerHTML = lms_portal.loading("Loading loans…");
	frappe.call({
		method: "lms_saas.api.portal.get_my_loans",
		callback: function (r) {
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
						lms_portal.escape(String(loan.outstanding)) +
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
				'<button type="submit" class="lms-btn lms-btn--primary">Pay now</button>' +
				"</form><div id=\"lms-pay-result\"></div>";
			document.getElementById("lms-pay-form").addEventListener("submit", function (ev) {
				ev.preventDefault();
				var fd = new FormData(ev.target);
				frappe.call({
					method: "lms_saas.api.portal.initiate_repayment",
					args: {
						loan_id: fd.get("loan_id"),
						amount: fd.get("amount"),
						provider_code: fd.get("provider"),
					},
					callback: function (res) {
						var msg = res.message || {};
						var out = document.getElementById("lms-pay-result");
						if (msg.redirect_url) {
							out.innerHTML =
								'<p class="lms-panel"><a class="lms-btn lms-btn--primary" href="' +
								lms_portal.escape(msg.redirect_url) +
								'">Continue to payment</a></p>';
							window.location.href = msg.redirect_url;
						} else if (msg.instructions) {
							out.innerHTML =
								'<pre class="lms-panel">' +
								lms_portal.escape(JSON.stringify(msg.instructions, null, 2)) +
								"</pre>";
						} else {
							out.innerHTML =
								'<p class="lms-panel">Payment intent ' +
								lms_portal.escape(msg.intent || "") +
								" created.</p>";
						}
					},
				});
			});
		},
	});
};

frappe.ready(function () {
	document.body.classList.add("lms-themed");
	if (document.body.classList.contains("lms-portal-legacy")) {
		lms_portal.mountLegacyChrome();
	}
});
