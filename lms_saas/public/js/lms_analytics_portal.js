/* LMS Branch Analytics portal — comparison, leaderboard, trends */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_analytics");
} else {
	window.lms_analytics = window.lms_analytics || {};
}

lms_analytics._currentTab = "comparison";

lms_analytics.init = function () {
	var root = document.getElementById("lms-analytics-root");
	if (!root) return;

	var tabs = [
		{ id: "comparison", label: "Comparison", icon: "bar-chart" },
		{ id: "leaderboard", label: "Leaderboard", icon: "trophy" },
		{ id: "trends", label: "Trends", icon: "trending-up" },
	];
	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "Branch Analytics" }) +
		'<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_analytics._currentTab === t.id ? " is-active" : "";
		var iconHtml = (window.lms_icons && lms_icons.icon) ? lms_icons.icon(t.icon, { size: 16, cls: "lms-tab-icon" }) : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + iconHtml + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	html += '<div id="lms-analytics-tab-content"></div>';
	html += lms_portal.pageEnd();
	root.innerHTML = html;

	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_analytics._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.setAttribute("aria-selected", "true");
			lms_analytics._showTab(lms_analytics._currentTab);
		});
	});

	lms_analytics._showTab(lms_analytics._currentTab);
};

lms_analytics._showTab = function (tabId) {
	var content = document.getElementById("lms-analytics-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "comparison") lms_analytics._loadComparison(content);
	else if (tabId === "leaderboard") lms_analytics._loadLeaderboard(content);
	else if (tabId === "trends") lms_analytics._loadTrends(content);
};

lms_analytics._fmtCurrency = function (v) {
	if (v === null || v === undefined) return "—";
	return format_currency(v);
};

// ── Comparison ──

lms_analytics._loadComparison = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.branch_analytics.get_branch_comparison",
		callback: function (r) {
			var data = (r && r.message) || {};
			var branches = data.branches || [];
			if (!branches.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("📊") + '<h3>No data</h3><p>No branch data available.</p></div></div>';
				return;
			}

			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Branch</th><th>Portfolio Outstanding</th><th>Active Loans</th><th>PAR30</th><th>PAR90</th><th>Collections (30d)</th><th>PAR30 %</th><th>PAR90 %</th></tr></thead><tbody>";
			branches.forEach(function (b) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(b.branch) + "</strong></td>";
				html += "<td>" + lms_analytics._fmtCurrency(b.portfolio_outstanding) + "</td>";
				html += "<td>" + (b.active_loans || 0) + "</td>";
				html += "<td>" + lms_analytics._fmtCurrency(b.par30) + "</td>";
				html += "<td>" + lms_analytics._fmtCurrency(b.par90) + "</td>";
				html += "<td>" + lms_analytics._fmtCurrency(b.collections) + "</td>";
				var par30Pct = (b.par30_ratio * 100).toFixed(2);
				var par90Pct = (b.par90_ratio * 100).toFixed(2);
				var par30Cls = b.par30_ratio > 0.05 ? "lms-badge--danger" : (b.par30_ratio > 0.02 ? "lms-badge--warning" : "lms-badge--success");
				var par90Cls = b.par90_ratio > 0.02 ? "lms-badge--danger" : "lms-badge--success";
				html += '<td><span class="lms-badge ' + par30Cls + '">' + par30Pct + "%</span></td>";
				html += '<td><span class="lms-badge ' + par90Cls + '">' + par90Pct + "%</span></td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";

			// Benchmark alerts
			html += '<div id="lms-analytics-alerts"></div>';
			content.innerHTML = html;
			lms_analytics._loadAlerts();
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load branch comparison.");
		},
	});
};

lms_analytics._loadAlerts = function () {
	var el = document.getElementById("lms-analytics-alerts");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.branch_analytics.get_benchmark_alerts",
		callback: function (r) {
			var alerts = (r && r.message && r.message.alerts) || [];
			if (!alerts.length) {
				el.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("✓") + '<h3>All clear</h3><p>No benchmark alerts.</p></div></div>';
				return;
			}
			var html = '<div class="lms-stack" style="margin-top:1rem;">';
			html += '<h3 style="margin:0;font-size:var(--lms-fs-lg);">Benchmark Alerts</h3>';
			alerts.forEach(function (a) {
				var cls = a.severity === "danger" ? "lms-badge--danger" : "lms-badge--warning";
				html += '<div class="lms-panel">';
				html += '<div class="lms-section-header">';
				html += '<div><strong>' + lms_portal.escape(a.branch) + '</strong> — ' + lms_portal.escape(a.metric) + '</div>';
				html += '<span class="lms-badge ' + cls + '">' + lms_portal.escape(a.value) + ' / ' + lms_portal.escape(a.threshold) + '</span>';
				html += '</div>';
				html += '<div class="lms-muted">' + lms_portal.escape(a.message) + '</div>';
				html += '</div>';
			});
			html += '</div>';
			el.innerHTML = html;
		},
	});
};

// ── Leaderboard ──

lms_analytics._leaderboardMetric = "disbursements";

lms_analytics._loadLeaderboard = function (content) {
	// Metric switcher buttons built as controls HTML, then passed to panel().
	var metrics = [
		{ id: "disbursements", label: "Disbursements" },
		{ id: "collections", label: "Collections" },
		{ id: "par", label: "PAR (30+)" },
	];
	var controls = "";
	metrics.forEach(function (m) {
		var active = lms_analytics._leaderboardMetric === m.id;
		controls += '<button type="button" class="lms-btn ' + (active ? "lms-btn--primary" : "lms-btn--ghost") + ' lms-btn--sm lms-analytic-metric" data-metric="' + m.id + '">' + lms_portal.escape(m.label) + "</button>";
	});
	var html = lms_portal.panel({ title: "Leaderboard", controls: controls }) +
		'<div id="lms-analytics-leaderboard-table"></div>';
	content.innerHTML = html;

	content.querySelectorAll(".lms-analytic-metric").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_analytics._leaderboardMetric = btn.getAttribute("data-metric");
			lms_analytics._loadLeaderboard(content);
		});
	});

	lms_analytics._fetchLeaderboard();
};

lms_analytics._fetchLeaderboard = function () {
	var el = document.getElementById("lms-analytics-leaderboard-table");
	if (!el) return;
	el.innerHTML = lms_portal.loading("Loading leaderboard…");

	lms_portal.safeCall({
		method: "lms_saas.api.branch_analytics.get_officer_leaderboard",
		args: { metric: lms_analytics._leaderboardMetric, period_days: 30 },
		callback: function (r) {
			var data = (r && r.message) || {};
			var officers = data.officers || [];
			if (!officers.length) {
				el.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("🏆") + '<h3>No data</h3><p>No officer data for this metric.</p></div></div>';
				return;
			}

			var valueLabel = data.metric === "par" ? "PAR Outstanding" : (data.metric === "collections" ? "Collected" : "Disbursed");
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Rank</th><th>Officer</th><th>" + lms_portal.escape(valueLabel) + "</th><th>Count</th></tr></thead><tbody>";
			officers.forEach(function (o, i) {
				var rankCls = i === 0 ? "lms-badge--warning" : (i === 1 ? "" : (i === 2 ? "lms-badge--info" : ""));
				html += "<tr>";
				html += '<td><span class="lms-badge ' + rankCls + '">#' + (i + 1) + "</span></td>";
				html += "<td><strong>" + lms_portal.escape(o.officer_name) + "</strong></td>";
				html += "<td>" + lms_analytics._fmtCurrency(o.value) + "</td>";
				html += "<td>" + (o.count || 0) + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			el.innerHTML = html;
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load leaderboard.");
		},
	});
};

// ── Trends ──

lms_analytics._trendMetric = "portfolio_outstanding";
lms_analytics._trendMonths = 6;

lms_analytics._loadTrends = function (content) {
	var metrics = [
		{ id: "portfolio_outstanding", label: "Portfolio Outstanding" },
		{ id: "active_loans", label: "Active Loans" },
		{ id: "par30", label: "PAR30" },
		{ id: "par90", label: "PAR90" },
		{ id: "collections", label: "Collections" },
	];
	var periods = [3, 6, 12];

	// Metric + period switcher buttons as controls HTML.
	var controls = "";
	metrics.forEach(function (m) {
		var active = lms_analytics._trendMetric === m.id;
		controls += '<button type="button" class="lms-btn ' + (active ? "lms-btn--primary" : "lms-btn--ghost") + ' lms-btn--sm lms-trend-metric" data-metric="' + m.id + '">' + lms_portal.escape(m.label) + "</button>";
	});
	periods.forEach(function (p) {
		var active = lms_analytics._trendMonths === p;
		controls += '<button type="button" class="lms-btn ' + (active ? "lms-btn--primary" : "lms-btn--ghost") + ' lms-btn--sm lms-trend-period" data-months="' + p + '">' + p + "M</button>";
	});
	var html = lms_portal.panel({ title: "Trends", controls: controls }) +
		'<div id="lms-analytics-trend-chart"></div>';
	content.innerHTML = html;

	content.querySelectorAll(".lms-trend-metric").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_analytics._trendMetric = btn.getAttribute("data-metric");
			lms_analytics._loadTrends(content);
		});
	});
	content.querySelectorAll(".lms-trend-period").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_analytics._trendMonths = parseInt(btn.getAttribute("data-months"), 10);
			lms_analytics._loadTrends(content);
		});
	});

	lms_analytics._fetchTrend();
};

lms_analytics._fetchTrend = function () {
	var el = document.getElementById("lms-analytics-trend-chart");
	if (!el) return;
	el.innerHTML = lms_portal.loading("Loading trends…");

	lms_portal.safeCall({
		method: "lms_saas.api.branch_analytics.get_branch_trends",
		args: { months: lms_analytics._trendMonths, metric: lms_analytics._trendMetric },
		callback: function (r) {
			var data = (r && r.message) || {};
			var branches = data.branches || [];
			var labels = data.labels || [];
			if (!branches.length) {
				el.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("📈") + '<h3>No data</h3><p>No trend data available.</p></div></div>';
				return;
			}

			var isCurrency = lms_analytics._trendMetric !== "active_loans";
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Branch</th>";
			labels.forEach(function (l) { html += "<th>" + lms_portal.escape(l) + "</th>"; });
			html += "</tr></thead><tbody>";
			branches.forEach(function (b) {
				html += "<tr><td><strong>" + lms_portal.escape(b.branch) + "</strong></td>";
				(b.trend || []).forEach(function (v) {
					html += "<td>" + (isCurrency ? lms_analytics._fmtCurrency(v) : v) + "</td>";
				});
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			el.innerHTML = html;
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load trends.");
		},
	});
};