/* LMS Budgeting portal — budgets, vs actual, forecast, variance */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_budgeting");
} else {
	window.lms_budgeting = window.lms_budgeting || {};
}

lms_budgeting._currentTab = "budgets";

lms_budgeting.init = function () {
	var root = document.getElementById("lms-budgeting-root");
	if (!root) return;

	var tabs = [
		{ id: "budgets", label: "Budgets", icon: "💰" },
		{ id: "vsactual", label: "vs Actual", icon: "📊" },
		{ id: "forecast", label: "Forecast", icon: "📈" },
		{ id: "variance", label: "Variance", icon: "⚠️" },
	];
	var html = '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_budgeting._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	html += '<div id="lms-bud-stats" style="margin-bottom:1rem;"></div>';
	html += '<div id="lms-bud-tab-content"></div>';
	root.innerHTML = html;

	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_budgeting._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.style.borderBottom = "2px solid var(--lms-primary)";
			btn.style.color = "var(--lms-primary)";
			btn.style.fontWeight = "600";
			lms_budgeting._showTab(lms_budgeting._currentTab);
		});
	});

	lms_budgeting._loadStats();
	lms_budgeting._showTab(lms_budgeting._currentTab);
};

lms_budgeting._showTab = function (tabId) {
	var content = document.getElementById("lms-bud-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "budgets") lms_budgeting._loadBudgets(content);
	else if (tabId === "vsactual") lms_budgeting._loadVsActual(content);
	else if (tabId === "forecast") lms_budgeting._loadForecast(content);
	else if (tabId === "variance") lms_budgeting._loadVariance(content);
};

lms_budgeting._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_budgeting._loadStats = function () {
	var el = document.getElementById("lms-bud-stats");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.budgeting.get_budgeting_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = '<section class="lms-grid-4">';
			html += lms_budgeting._statCard("Total Budgets", s.total_budgets || 0);
			html += lms_budgeting._statCard("Fiscal Years", s.active_fiscal_years || 0);
			html += lms_budgeting._statCard("Total Budgeted", format_currency(s.total_budgeted || 0));
			html += lms_budgeting._statCard("Over Budget", s.accounts_over_budget || 0, "danger");
			html += "</section>";
			el.innerHTML = html;
		},
	});
};

lms_budgeting._loadBudgets = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.budgeting.get_branch_budgets",
		callback: function (r) {
			var budgets = (r && r.message && r.message.budgets) || [];
			if (!budgets.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">💰</div><h3>No budgets</h3><p>No budgets found for your branch.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Budget</th><th>Cost Center</th><th>Fiscal Year</th><th>Accounts</th><th>Total Budget</th></tr></thead><tbody>";
			budgets.forEach(function (b) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(b.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(b.cost_center || "—") + "</td>";
				html += "<td>" + lms_portal.escape(b.fiscal_year || "—") + "</td>";
				html += "<td>" + (b.account_count || 0) + "</td>";
				html += "<td>" + format_currency(b.total_budget || 0) + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load budgets.");
		},
	});
};

lms_budgeting._loadVsActual = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.budgeting.get_budget_vs_actual",
		callback: function (r) {
			var data = (r && r.message) || {};
			var comparisons = data.comparisons || [];
			if (!comparisons.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📊</div><h3>No data</h3><p>No budget vs actual data available.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Account</th><th>Budgeted</th><th>Actual</th><th>Variance</th><th>Utilization</th></tr></thead><tbody>";
			comparisons.forEach(function (c) {
				var varClass = c.variance < 0 ? "lms-badge--danger" : "lms-badge--success";
				var utilClass = c.utilization_pct > 100 ? "lms-badge--danger" : (c.utilization_pct > 80 ? "lms-badge--warning" : "lms-badge--success");
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(c.account) + "</strong></td>";
				html += "<td>" + format_currency(c.budgeted || 0) + "</td>";
				html += "<td>" + format_currency(c.actual || 0) + "</td>";
				html += '<td><span class="lms-badge ' + varClass + '">' + format_currency(c.variance || 0) + "</span></td>";
				html += '<td><span class="lms-badge ' + utilClass + '">' + (c.utilization_pct || 0) + "%</span></td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load budget vs actual.");
		},
	});
};

lms_budgeting._loadForecast = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.budgeting.get_forecast",
		args: { months: 12 },
		callback: function (r) {
			var data = (r && r.message) || {};
			var historical = data.historical || [];
			var forecast = data.forecast || [];
			var growth = data.avg_growth_rate || 0;

			var html = '<div class="lms-panel" style="margin-bottom:1rem;">';
			html += '<div class="lms-summary"><div class="lms-summary-card"><div class="lms-summary-label">Avg Growth Rate</div><div class="lms-summary-value">' + (growth > 0 ? "+" : "") + growth + "%</div></div></div>';
			html += '</div>';

			if (historical.length) {
				html += '<div class="lms-panel" style="margin-bottom:1rem;"><h3>Historical Disbursements</h3>';
				html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Month</th><th>Amount</th></tr></thead><tbody>';
				historical.forEach(function (h) {
					html += "<tr><td>" + lms_portal.escape(h.month) + "</td><td>" + format_currency(h.amount || 0) + "</td></tr>";
				});
				html += "</tbody></table></div></div>";
			}

			if (forecast.length) {
				html += '<div class="lms-panel"><h3>Forecast (12 months)</h3>';
				html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Month</th><th>Projected</th></tr></thead><tbody>';
				forecast.forEach(function (f) {
					html += "<tr><td>" + lms_portal.escape(f.month) + "</td><td>" + format_currency(f.projected || 0) + "</td></tr>";
				});
				html += "</tbody></table></div></div>";
			}

			if (!historical.length && !forecast.length) {
				html = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📈</div><h3>No data</h3><p>Not enough historical data for forecasting.</p></div></div>';
			}

			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load forecast.");
		},
	});
};

lms_budgeting._loadVariance = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.budgeting.get_variance_analysis",
		args: { threshold: 10 },
		callback: function (r) {
			var data = (r && r.message) || {};
			var variances = data.variances || [];
			if (!variances.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">✓</div><h3>Within budget</h3><p>No accounts exceeding the variance threshold.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Budget</th><th>Cost Center</th><th>Account</th><th>Budgeted</th><th>Actual</th><th>Variance</th><th>Variance %</th></tr></thead><tbody>";
			variances.forEach(function (v) {
				var varClass = v.variance_pct > 0 ? "lms-badge--danger" : "lms-badge--warning";
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(v.budget) + "</strong></td>";
				html += "<td>" + lms_portal.escape(v.cost_center || "—") + "</td>";
				html += "<td>" + lms_portal.escape(v.account) + "</td>";
				html += "<td>" + format_currency(v.budgeted || 0) + "</td>";
				html += "<td>" + format_currency(v.actual || 0) + "</td>";
				html += "<td>" + format_currency(v.variance || 0) + "</td>";
				html += '<td><span class="lms-badge ' + varClass + '">' + (v.variance_pct || 0) + "%</span></td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load variance analysis.");
		},
	});
};