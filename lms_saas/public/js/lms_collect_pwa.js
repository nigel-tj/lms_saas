/* LMS field collection PWA */
// Guard frappe.provide: this file is in web_include_js, so it loads on the
// login page too, where Frappe's desk JS bundle (and frappe.provide) is not
// available. No-op when missing to avoid breaking the page.
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_collect");
} else {
	window.lms_collect = window.lms_collect || {};
}

lms_collect.DB_NAME = "lms_collect_queue";
lms_collect.STORE = "repayments";

lms_collect.init = function () {
	var root = document.getElementById("lms-collect-root");
	if (!root) return;
	root.innerHTML = lms_portal.loading("Loading run sheet…");
	lms_collect._registerServiceWorker();
	lms_collect._loadRunSheet(root);
	lms_collect._loadCharts();
	lms_collect._initInstallPrompt();
};

lms_collect._registerServiceWorker = function () {
	if (!("serviceWorker" in navigator)) return;
	navigator.serviceWorker.register("/assets/lms_saas/js/lms_collect_sw.js").catch(function () {});
};

lms_collect._loadRunSheet = function (root) {
	frappe.call({
		method: "lms_saas.api.field_collection.get_collection_run_sheet",
		callback: function (r) {
			var rows = (r.message && r.message.rows) || [];
			lms_collect._renderRunSheet(root, rows);
		},
		error: function () {
			root.innerHTML = lms_portal.error("Could not load run sheet.", function () {
				lms_collect.init();
			});
		},
	});
};

lms_collect._safeChartRender = function (el, primary, fallback) {
	// Prefer shared helper; fall back inline if an older cached lms_portal.js
	// is missing _renderOrFallback (B-01 regression guard).
	if (lms_portal && typeof lms_portal._renderOrFallback === "function") {
		lms_portal._renderOrFallback(el, primary, fallback);
		return;
	}
	try {
		if (typeof primary === "function") primary(el);
	} catch (e) {
		if (typeof fallback === "function") fallback(el);
	}
};

lms_collect._loadCharts = function () {
	// 7-day collection trend line -------------------------------------
	var trendEl = document.getElementById("lms-collect-trend");
	if (trendEl) {
		frappe.call({
			method: "lms_saas.api.dashboard.get_chart_data",
			args: { filters: JSON.stringify({ metric: "collections_trend" }) },
			callback: function (r) {
				var data = (r && r.message) || { labels: [], datasets: [{ name: "Collections", values: [] }] };
				var labels = data.labels || [];
				var values = (data.datasets && data.datasets[0] && data.datasets[0].values) || [];
				if (labels.length < 2) {
					if (window.LMSChart && LMSChart.empty) LMSChart.empty(trendEl, "No collection data yet.");
					else trendEl.innerHTML = '<p class="lms-muted">No collection data yet.</p>';
					return;
				}
				lms_collect._safeChartRender(trendEl, function (el) {
					if (!window.LMSChart || !LMSChart.line) throw new Error("LMSChart.line unavailable");
					return LMSChart.line(el, labels, values, {
						name: "Collected",
						height: 180,
						hideLegend: true
					});
				}, function () {
					trendEl.innerHTML = lms_portal.simpleBars(
						labels.map(function (l, i) { return { label: l, value: values[i] || 0 }; })
					);
				});
			},
			error: function () {
				trendEl.innerHTML = lms_portal.error("Could not load 7-day trend.", function () {
					lms_collect._loadCharts();
				});
			},
		});
	}

	// Collector leaderboard bar --------------------------------------
	var leaderEl = document.getElementById("lms-collect-leaderboard");
	if (leaderEl) {
		frappe.call({
			method: "lms_saas.api.dashboard.get_collections_overview",
			callback: function (r) {
				var data = (r && r.message) || { leaderboard: [] };
				var rows = data.leaderboard || [];
				if (!rows.length) {
					if (window.LMSChart && LMSChart.empty) LMSChart.empty(leaderEl, "No collection activity today.");
					else leaderEl.innerHTML = '<p class="lms-muted">No collection activity today.</p>';
					return;
				}
				var labels = rows.map(function (r) { return r.collector || "Unknown"; });
				var values = rows.map(function (r) { return r.amount || 0; });
				lms_collect._safeChartRender(leaderEl, function (el) {
					if (!window.LMSChart || !LMSChart.bar) throw new Error("LMSChart.bar unavailable");
					return LMSChart.bar(el, labels, values, {
						name: "Collected",
						height: 180,
						hideLegend: true,
						horizontal: true
					});
				}, function () {
					leaderEl.innerHTML = lms_portal.simpleBars(
						rows.map(function (r) { return { label: r.collector, value: r.amount }; })
					);
				});
			},
			error: function () {
				leaderEl.innerHTML = lms_portal.error("Could not load leaderboard.", function () {
					lms_collect._loadCharts();
				});
			},
		});
	}
};

lms_collect._queuedLoanSet = function () {
	var set = {};
	try {
		var q = JSON.parse(localStorage.getItem(lms_collect.DB_NAME) || "[]");
		(q || []).forEach(function (item) {
			if (item && item.loan) set[item.loan] = true;
		});
	} catch (e) { /* ignore */ }
	return set;
};

lms_collect._renderRunSheet = function (root, rows) {
	var queueCount = lms_collect._offlineQueueCount();
	var queued = lms_collect._queuedLoanSet();
	var totalDue = 0;
	rows.forEach(function (row) { totalDue += parseFloat(row.amount) || 0; });

	var listBody = "";
	if (!rows.length) {
		listBody = '<p class="lms-muted">No dues in range.</p>';
	} else {
		listBody = '<ul class="lms-list">';
		rows.forEach(function (row) {
			var mobile = row.borrower_mobile || "";
			var callBtn = mobile
				? '<a class="lms-btn lms-btn--ghost lms-btn--sm" href="tel:' + lms_portal.escape(mobile) + '">Call</a>'
				: "";
			var pending = !!queued[row.loan];
			var syncBadge = pending
				? ' <span class="lms-badge lms-badge--warning" title="Queued on this device — tap Sync">Pending sync</span>'
				: ' <span class="lms-badge lms-badge--success" title="No offline queue for this stop">Synced</span>';
			listBody +=
				'<li class="lms-list__item' + (pending ? " is-pending-sync" : "") + '">' +
				'<div class="lms-list__info">' +
				'<strong>' + lms_portal.escape(row.borrower) + "</strong>" +
				" — " + lms_portal.formatDate(row.due_date) +
				" — " + format_currency(row.amount) +
				syncBadge +
				(mobile ? ' <span class="lms-muted">· ' + lms_portal.escape(mobile) + "</span>" : "") +
				"</div>" +
				'<div class="lms-list__actions">' +
				callBtn +
				'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-collect-btn" data-loan="' +
				lms_portal.escape(row.loan) +
				'" data-amount="' +
				lms_portal.escape(String(row.amount)) +
				'">Collect</button>' +
				'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-promise-btn" data-loan="' +
				lms_portal.escape(row.loan) +
				'">Promise</button>' +
				"</div></li>";
		});
		listBody += "</ul>";
	}

	var syncControls =
		'<div class="lms-collect-sync">' +
		'<button type="button" class="lms-btn lms-btn--secondary" id="lms-sync-offline">Sync offline queue' +
		(queueCount > 0 ? ' <span class="lms-badge lms-badge--watch">' + queueCount + "</span>" : "") +
		"</button></div>";

	var html = lms_portal.pageStart() +
		lms_portal.connectivityBanner() +
		lms_portal.kpiStrip([
			{ label: "Stops today", value: rows.length },
			{ label: "Amount due", value: format_currency(totalDue) },
			{ label: "Offline queue", value: queueCount, tone: queueCount ? "warning" : "success" },
		]) +
		lms_portal.panel({ title: "Due today & upcoming", body: listBody + syncControls }) +
		lms_portal.pageEnd();

	root.innerHTML = html;
	if (typeof lms_portal.bindConnectivity === "function") {
		lms_portal.bindConnectivity();
	}

	// Bind collect buttons — open action menu
	root.querySelectorAll(".lms-collect-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_collect._openCollectModal(
				btn.getAttribute("data-loan"),
				parseFloat(btn.getAttribute("data-amount")),
				root
			);
		});
	});

	// Bind promise buttons
	root.querySelectorAll(".lms-promise-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_collect._openPromiseModal(btn.getAttribute("data-loan"), root);
		});
	});

	var syncBtn = document.getElementById("lms-sync-offline");
	if (syncBtn) {
		syncBtn.addEventListener("click", function () {
			lms_collect._syncOffline(root);
		});
	}
};

lms_collect._openCollectModal = function (loan, fullAmount, root) {
	// Phase 2.2/2.3 — native <dialog> + pop-out combobox for payment mode
	var body =
		'<div class="lms-form">' +
		'<label>Amount<input type="number" id="lms-collect-amount" class="lms-input" value="' +
		fullAmount +
		'" min="0.01" step="0.01"></label>' +
		'<label>Payment mode' +
		'<select id="lms-collect-mode" class="lms-input lms-fallback-select lms-pop-select">' +
		'<option value="Cash">Cash</option>' +
		'<option value="EcoCash">EcoCash</option>' +
		'<option value="OneMoney">OneMoney</option>' +
		'<option value="Bank Transfer">Bank Transfer</option>' +
		"</select></label>" +
		'<label>Note (optional)<input type="text" id="lms-collect-note" class="lms-input" placeholder="e.g. partial payment"></label>' +
		"</div>";
	var dlg = LMSModal.open({
		title: "Collect payment",
		body: body,
		actions: [
			{ label: "Cancel", value: false },
			{ label: "Collect", value: true, primary: true }
		]
	});
	if (window.LMSForms && typeof LMSForms.bindAll === "function") {
		LMSForms.bindAll(dlg.dialog);
	}
	dlg.then(function (ok) {
		if (!ok) return;
		var amount = parseFloat((dlg.dialog.querySelector("#lms-collect-amount") || {}).value) || 0;
		var mode = (dlg.dialog.querySelector("#lms-collect-mode") || {}).value || "Cash";
		var note = (dlg.dialog.querySelector("#lms-collect-note") || {}).value || "";
		lms_collect._collect(loan, amount, mode, root, note, fullAmount);
	});
};

lms_collect._openPromiseModal = function (loan, root) {
	var today = new Date().toISOString().slice(0, 10);
	// Phase 2.3 — native <dialog>
	var body =
		'<div class="lms-form">' +
		'<label>Promised date<input type="date" id="lms-promise-date" class="lms-input" value="' +
		today +
		'"></label>' +
		'<label>Amount (optional)<input type="number" id="lms-promise-amount" class="lms-input" min="0" step="0.01"></label>' +
		'<label>Note<input type="text" id="lms-promise-note" class="lms-input" placeholder="e.g. will pay after salary"></label>' +
		"</div>";
	var dlg = LMSModal.open({
		title: "Promise to pay",
		body: body,
		actions: [
			{ label: "Cancel", value: false },
			{ label: "Save promise", value: true, primary: true }
		]
	});
	dlg.then(function (ok) {
		if (!ok) return;
		var date = (dlg.dialog.querySelector("#lms-promise-date") || {}).value || today;
		var amount = (dlg.dialog.querySelector("#lms-promise-amount") || {}).value || "";
		var note = (dlg.dialog.querySelector("#lms-promise-note") || {}).value || "";
		frappe.call({
			method: "lms_saas.api.field_collection.create_promise_to_pay",
			args: { loan: loan, promised_date: date, promised_amount: amount, note: note },
			callback: function () {
				frappe.show_alert({
					message: lms_copy.tSync("generic.save", "Promise to pay recorded."),
					indicator: "green"
				});
			},
			error: function () {
				frappe.show_alert({
					message: lms_copy.tSync("generic.error", "Something went wrong. Please try again."),
					indicator: "red"
				});
			},
		});
	});
};

lms_collect._collect = function (loan, amount, payment_mode, root, note, fullAmount) {
	var isPartial = fullAmount && amount < fullAmount;
	if (!navigator.onLine) {
		lms_collect._queueOffline({ loan: loan, amount: amount, payment_mode: payment_mode, note: note });
		// Phase 2.6 — softened offline copy (the borrower-friendly "saved on this device" framing)
		frappe.show_alert({
			message: lms_copy.tSync("collector.offline_saved", "Saved on this device. Will sync when you're back online."),
			indicator: "orange"
		});
		lms_collect._loadRunSheet(root);
		return;
	}
	var method = isPartial
		? "lms_saas.api.field_collection.record_partial_repayment"
		: "lms_saas.api.field_collection.record_field_repayment";
	frappe.call({
		method: method,
		args: { loan: loan, amount: amount, payment_mode: payment_mode, note: note || "" },
		callback: function (r) {
			var res = r.message || {};
			frappe.show_alert({
				message: lms_copy.tSync("collector.collected", "Collected {amount} from {customer}.", { amount: format_currency(amount), customer: loan }),
				indicator: "green"
			});
			if (res.repayment) {
				lms_collect._showReceiptPrompt(res.repayment);
			}
			lms_collect._loadRunSheet(root);
		},
		error: function () {
			frappe.show_alert({
				message: lms_copy.tSync("generic.error", "Something went wrong. Please try again."),
				indicator: "red"
			});
		},
	});
};

lms_collect._showReceiptPrompt = function (repaymentName) {
	// Phase 2.3 — native <dialog>
	var dlg = LMSModal.open({
		title: "Collection successful",
		body: "<p>Repayment <strong>" + lms_portal.escape(repaymentName) + "</strong> recorded.</p>",
		actions: [
			{ label: "Close", value: false },
			{ label: "Download receipt", value: true, primary: true }
		]
	});
	dlg.then(function (download) {
		if (download) {
			window.open(
				"/api/method/lms_saas.api.field_collection.generate_collection_receipt?repayment_name=" +
					encodeURIComponent(repaymentName),
				"_blank"
			);
		}
	});
};

lms_collect._queueOffline = function (item) {
	try {
		var q = JSON.parse(localStorage.getItem(lms_collect.DB_NAME) || "[]");
		q.push(item);
		localStorage.setItem(lms_collect.DB_NAME, JSON.stringify(q));
	} catch (e) {}
};

lms_collect._offlineQueueCount = function () {
	try {
		var q = JSON.parse(localStorage.getItem(lms_collect.DB_NAME) || "[]");
		return q.length;
	} catch (e) {
		return 0;
	}
};

lms_collect._syncOffline = function (root) {
	var q = [];
	try {
		q = JSON.parse(localStorage.getItem(lms_collect.DB_NAME) || "[]");
	} catch (e) {}
	if (!q.length) {
		frappe.show_alert({
			message: lms_copy.tSync("generic.no_data", "Nothing to sync"),
			indicator: "blue"
		});
		return;
	}
	frappe.call({
		method: "lms_saas.api.field_collection.sync_offline_batch",
		args: { batch_json: JSON.stringify(q) },
		callback: function (r) {
			var results = (r.message && r.message.results) || [];
			var failed = results.filter(function (x) { return !x.ok; });
			if (failed.length) {
				// Keep only failed items in queue
				var failedLoans = failed.map(function (x) { return x.loan; });
				var remaining = q.filter(function (item) {
					return failedLoans.indexOf(item.loan) !== -1;
				});
				localStorage.setItem(lms_collect.DB_NAME, JSON.stringify(remaining));
				lms_collect._showSyncErrors(failed);
			} else {
				localStorage.removeItem(lms_collect.DB_NAME);
				frappe.show_alert({
					message: lms_copy.tSync("collector.synced", "Synced {when}", { when: results.length + " items" }),
					indicator: "green"
				});
			}
			lms_collect._loadRunSheet(root);
		},
		error: function () {
			frappe.show_alert({
				message: lms_copy.tSync("generic.error", "Something went wrong. Please try again."),
				indicator: "red"
			});
		},
	});
};

lms_collect._showSyncErrors = function (failed) {
	// Phase 2.3 — native <dialog>
	var body =
		'<p class="lms-muted">' + failed.length + " item(s) could not be synced:</p>" +
		'<ul class="lms-sync-error-list">';
	failed.forEach(function (item) {
		body +=
			"<li><strong>" + lms_portal.escape(item.loan) + "</strong>: " +
			lms_portal.escape(item.error || "Unknown error") + "</li>";
	});
	body += "</ul>";
	LMSModal.open({
		title: "Sync conflicts",
		body: body,
		actions: [{ label: "Close", value: true, primary: true }]
	});
};

lms_collect._initInstallPrompt = function () {
	lms_collect._deferredPrompt = null;
	window.addEventListener("beforeinstallprompt", function (e) {
		e.preventDefault();
		lms_collect._deferredPrompt = e;
		lms_collect._showInstallBanner();
	});
};

lms_collect._showInstallBanner = function () {
	if (document.getElementById("lms-install-banner")) return;
	var banner =
		'<div class="lms-install-banner" id="lms-install-banner">' +
		"<p>Install the collection app for offline use.</p>" +
		'<div class="lms-install-banner__actions">' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-install-dismiss">Later</button>' +
		'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-install-btn">Install</button>' +
		"</div></div>";
	var root = document.getElementById("lms-collect-root");
	if (root) root.insertAdjacentHTML("beforebegin", banner);
	document.getElementById("lms-install-dismiss").addEventListener("click", function () {
		document.getElementById("lms-install-banner").remove();
	});
	document.getElementById("lms-install-btn").addEventListener("click", function () {
		if (lms_collect._deferredPrompt) {
			lms_collect._deferredPrompt.prompt();
			lms_collect._deferredPrompt.userChoice.then(function () {
				lms_collect._deferredPrompt = null;
				document.getElementById("lms-install-banner").remove();
			});
		}
	});
};
