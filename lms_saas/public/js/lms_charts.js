/* LMS Charts — thin wrapper around Chart.js with brand-aware defaults */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_charts");
} else {
	window.lms_charts = window.lms_charts || {};
}

(function () {
	"use strict";

	/** Read a CSS variable from the active theme. */
	function token(name, fallback) {
		try {
			var v = getComputedStyle(document.documentElement)
				.getPropertyValue(name)
				.trim();
			return v || fallback;
		} catch (e) {
			return fallback;
		}
	}

	function palette() {
		return {
			primary: token("--lms-primary", "#2f4f46"),
			accent: token("--lms-accent", "#b9f19d"),
			success: token("--lms-success", "#16a34a"),
			warning: token("--lms-warning", "#f59e0b"),
			danger: token("--lms-danger", "#dc2626"),
			text: token("--lms-text", "#1f2937"),
			textMuted: token("--lms-text-muted", "#6b7280"),
			border: token("--lms-border", "#e5e7eb"),
			surface: token("--lms-surface", "#ffffff"),
		};
	}

	function commonOptions(extra) {
		var c = palette();
		var opts = {
			responsive: true,
			maintainAspectRatio: false,
			plugins: {
				legend: {
					labels: { color: c.text, font: { family: "Inter, sans-serif", size: 12 } },
				},
				tooltip: {
					backgroundColor: c.surface,
					titleColor: c.text,
					bodyColor: c.textMuted,
					borderColor: c.border,
					borderWidth: 1,
					padding: 10,
					cornerRadius: 8,
				},
			},
		};
		if (extra) opts = lms_charts._merge(opts, extra);
		return opts;
	}

	lms_charts._merge = function (base, extra) {
		var out = JSON.parse(JSON.stringify(base));
		if (!extra) return out;
		for (var k in extra) {
			if (extra.hasOwnProperty(k)) out[k] = extra[k];
		}
		return out;
	};

	/** Donut / doughnut chart.  data = [{label, value, color?}] */
	lms_charts.donut = function (canvasId, data, options) {
		var el = document.getElementById(canvasId);
		if (!el || typeof Chart === "undefined") return null;
		var c = palette();
		var labels = data.map(function (d) { return d.label; });
		var values = data.map(function (d) { return d.value || 0; });
		var colors = data.map(function (d, i) {
			return d.color || [c.primary, c.accent, c.warning, c.danger, c.success][i % 5];
		});
		return new Chart(el, {
			type: "doughnut",
			data: {
				labels: labels,
				datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: c.surface }],
			},
			options: commonOptions({
				cutout: "62%",
				plugins: {
					legend: {
						position: "bottom",
						labels: { color: c.text, font: { family: "Inter, sans-serif", size: 11 }, padding: 12 },
					},
				},
			}),
		});
	};

	/** Horizontal bar chart.  data = [{label, value, color?}] */
	lms_charts.bars = function (canvasId, data, options) {
		var el = document.getElementById(canvasId);
		if (!el || typeof Chart === "undefined") return null;
		var c = palette();
		var labels = data.map(function (d) { return d.label; });
		var values = data.map(function (d) { return d.value || 0; });
		var colors = data.map(function (d, i) {
			return d.color || [c.primary, c.accent, c.warning, c.danger, c.success][i % 5];
		});
		return new Chart(el, {
			type: "bar",
			data: {
				labels: labels,
				datasets: [{ data: values, backgroundColor: colors, borderRadius: 6, maxBarThickness: 36 }],
			},
			options: commonOptions({
				indexAxis: "y",
				plugins: { legend: { display: false } },
				scales: {
					x: { grid: { color: c.border }, ticks: { color: c.textMuted, font: { size: 11 } } },
					y: { grid: { display: false }, ticks: { color: c.text, font: { size: 12 } } },
				},
			}),
		});
	};

	/** Vertical bar chart (for time series).  data = {labels:[], datasets:[{label,data,color?}]} */
	lms_charts.column = function (canvasId, data, options) {
		var el = document.getElementById(canvasId);
		if (!el || typeof Chart === "undefined") return null;
		var c = palette();
		var datasets = (data.datasets || []).map(function (ds, i) {
			return {
				label: ds.label || "",
				data: ds.data || [],
				backgroundColor: ds.color || [c.primary, c.accent, c.warning][i % 3],
				borderRadius: 6,
				maxBarThickness: 40,
			};
		});
		return new Chart(el, {
			type: "bar",
			data: { labels: data.labels || [], datasets: datasets },
			options: commonOptions({
				plugins: { legend: { display: datasets.length > 1 } },
				scales: {
					x: { grid: { display: false }, ticks: { color: c.textMuted, font: { size: 11 } } },
					y: { grid: { color: c.border }, ticks: { color: c.textMuted, font: { size: 11 } } },
				},
			}),
		});
	};

	/** Line chart.  data = {labels:[], datasets:[{label,data,color?}]} */
	lms_charts.line = function (canvasId, data, options) {
		var el = document.getElementById(canvasId);
		if (!el || typeof Chart === "undefined") return null;
		var c = palette();
		var datasets = (data.datasets || []).map(function (ds, i) {
			var col = ds.color || [c.primary, c.accent, c.warning][i % 3];
			return {
				label: ds.label || "",
				data: ds.data || [],
				borderColor: col,
				backgroundColor: col + "22",
				fill: ds.fill !== false,
				tension: 0.35,
				borderWidth: 2,
				pointRadius: 3,
			};
		});
		return new Chart(el, {
			type: "line",
			data: { labels: data.labels || [], datasets: datasets },
			options: commonOptions({
				plugins: { legend: { display: datasets.length > 1 } },
				scales: {
					x: { grid: { display: false }, ticks: { color: c.textMuted, font: { size: 11 } } },
					y: { grid: { color: c.border }, ticks: { color: c.textMuted, font: { size: 11 } } },
				},
			}),
		});
	};

	lms_charts.destroy = function (chart) {
		if (chart && typeof chart.destroy === "function") chart.destroy();
	};
})();