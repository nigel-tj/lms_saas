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
	// R18-defensive: defer init if lms_portal hasn't finished parsing yet.
	if (typeof lms_portal === "undefined" || typeof lms_portal.tabNav !== "function") {
		return setTimeout(lms_collect.init, 0);
	}
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
			// R18-4: mobile is masked by default. Show a Reveal button that
			// hits `reveal_borrower_pii` (which writes one audit-log row).
			var mobile = row.borrower_mobile || "";
			var masked = !!row.borrower_mobile_masked;
			var callBtn = (mobile && !masked)
				? '<a class="lms-btn lms-btn--ghost lms-btn--sm" href="tel:' + lms_portal.escape(mobile) + '">Call</a>'
				: "";
			var revealBtn = masked
				? '<button type="button" class="lms-pii-reveal lms-reveal-pii-btn" data-loan="' + lms_portal.escape(row.loan) + '" title="Tap to reveal the full mobile number. This is recorded for audit.">Reveal mobile</button>'
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
				' <span class="lms-pii-mobile" data-loan="' + lms_portal.escape(row.loan) + '">' +
				(mobile ? (masked ? '<span class="lms-pii-masked">' + lms_portal.escape(mobile) + '</span>' + " " + revealBtn : '<span>' + lms_portal.escape(mobile) + '</span>') : '<span class="lms-muted">No mobile on file</span>') +
				"</span>" +
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

	// R18-4: bind Reveal PII buttons. Each click POSTs to the whitelisted
	// reveal endpoint which writes one audit-log row.
	root.querySelectorAll(".lms-reveal-pii-btn").forEach(function (btn) {
		btn.addEventListener("click", function () {
			var loan = btn.getAttribute("data-loan");
			lms_collect._revealPii(loan, btn, root);
		});
	});
};

/* R18-4: fetch the cleartext mobile for a single loan, swap the masked
 * span in place. The server writes an audit row per call. */
lms_collect._revealPii = function (loan, btn, root) {
	btn.disabled = true;
	btn.textContent = "Revealing…";
	lms_portal.safeCall({
		method: "lms_saas.api.field_collection.reveal_borrower_pii",
		args: { loan: loan, field: "mobile_no" },
		callback: function (r) {
			var value = (r && r.message && r.message.value) || "";
			var cell = root.querySelector('.lms-pii-mobile[data-loan="' + CSS.escape(loan) + '"]');
			if (cell) {
				cell.innerHTML =
					'<span>' + lms_portal.escape(value) + '</span> ' +
					'<a class="lms-btn lms-btn--ghost lms-btn--sm" href="tel:' + lms_portal.escape(value) + '">Call</a>';
			}
			btn.remove();
		},
		error: function () {
			btn.disabled = false;
			btn.textContent = "Reveal mobile";
			frappe.show_alert({
				message: lms_copy.tSync("generic.error", "Could not reveal PII. Please try again."),
				indicator: "red",
			});
		},
	});
};

lms_collect._openCollectModal = function (loan, fullAmount, root) {
	// R18-6: TWO-STEP COLLECT.
	// Step 1: enter amount + payment mode + note.
	// Step 2: confirm "I've counted ZAR X in hand" before submission.
	// A typo of "2000" when "200" was meant loses the customer's money;
	// the explicit confirm sentence + checkbox is the cheapest defense
	// that does not require a network round-trip.
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
		// R18-6: confirm checkbox. The Collect button stays disabled until
		// the collector ticks this — this is the intentional friction that
		// catches a mis-typed amount on the first try.
		'<label class="lms-collect-confirm" style="margin-top:0.75rem;display:flex;align-items:flex-start;gap:0.5rem;font-weight:500;">' +
		'<input type="checkbox" id="lms-collect-confirm" style="margin-top:0.2rem;">' +
		'<span>I have <strong id="lms-collect-confirm-amount">ZAR 0.00</strong> in hand and confirm this amount is correct.</span>' +
		'</label>' +
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
	// R18-6: keep the Collect button disabled until the confirm box is
	// checked. Re-validate the amount field every keystroke.
	var dlgRoot = dlg.dialog;
	var collectBtn = dlgRoot.querySelector('[data-lms-modal-action="true"]');
	if (collectBtn) {
		collectBtn.disabled = true;
		collectBtn.style.opacity = "0.55";
		collectBtn.style.cursor = "not-allowed";
	}
	var amountInput = dlgRoot.querySelector("#lms-collect-amount");
	var confirmBox = dlgRoot.querySelector("#lms-collect-confirm");
	var confirmAmount = dlgRoot.querySelector("#lms-collect-confirm-amount");
	var syncConfirm = function () {
		var amount = parseFloat((amountInput && amountInput.value) || "0") || 0;
		if (confirmAmount) confirmAmount.textContent = "ZAR " + amount.toFixed(2);
		var ok = confirmBox && confirmBox.checked && amount > 0;
		if (collectBtn) {
			collectBtn.disabled = !ok;
			collectBtn.style.opacity = ok ? "1" : "0.55";
			collectBtn.style.cursor = ok ? "pointer" : "not-allowed";
		}
	};
	if (amountInput) amountInput.addEventListener("input", syncConfirm);
	if (confirmBox) confirmBox.addEventListener("change", syncConfirm);
	syncConfirm();
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
			// R18-6: replace the static success toast with a 5-second Undo
			// toast. Within that window, the collector can cancel the
			// repayment — the server's undo endpoint reverses the GL entry
			// and clears the offline queue entry.
			var repaymentName = res.repayment || null;
			lms_collect._showUndoToast({
				loan: loan,
				amount: amount,
				repayment: repaymentName,
				onDone: function () {
					if (repaymentName) lms_collect._showReceiptPrompt(repaymentName);
					lms_collect._loadRunSheet(root);
				},
			});
		},
		error: function () {
			frappe.show_alert({
				message: lms_copy.tSync("generic.error", "Something went wrong. Please try again."),
				indicator: "red"
			});
		},
	});
};

/* R18-6: 5-second Undo toast. The collector can cancel the repayment
 * within the timeout; afterwards the toast collapses to a "Recorded"
 * confirmation. */
lms_collect._showUndoToast = function (opts) {
	opts = opts || {};
	var loan = opts.loan;
	var amount = opts.amount;
	var repayment = opts.repayment;
	var onDone = opts.onDone || function () {};
	var undoWindowMs = 5000;
	var container = document.getElementById("lms-toast-stack") || document.body;
	var el = document.createElement("div");
	el.className = "lms-toast lms-toast--success lms-undo-toast";
	el.setAttribute("role", "status");
	el.innerHTML =
		'<div class="lms-undo-toast__msg">' +
		'Recorded <strong>' + lms_portal.escape(format_currency(amount)) + '</strong>' +
		' against <strong>' + lms_portal.escape(loan) + '</strong>.' +
		'</div>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-undo-btn">Undo (5s)</button>';
	container.appendChild(el);
	var remaining = undoWindowMs / 1000;
	var undoBtn = el.querySelector(".lms-undo-btn");
	var timer = setInterval(function () {
		remaining -= 1;
		if (remaining <= 0) {
			clearInterval(timer);
			undoBtn.disabled = true;
			undoBtn.textContent = "Recorded";
			setTimeout(function () { el.remove(); }, 1200);
			if (typeof onDone === "function") onDone();
		} else {
			undoBtn.textContent = "Undo (" + remaining + "s)";
		}
	}, 1000);
	undoBtn.addEventListener("click", function () {
		clearInterval(timer);
		undoBtn.disabled = true;
		undoBtn.textContent = "Undoing…";
		lms_collect._undoCollection(loan, repayment, function () {
			el.remove();
			frappe.show_alert({ message: "Collection reversed.", indicator: "green" });
			if (typeof onDone === "function") onDone();
		}, function () {
			undoBtn.textContent = "Undo failed — try again";
			undoBtn.disabled = false;
		});
	});
};

lms_collect._undoCollection = function (loan, repayment, onOk, onErr) {
	lms_portal.safeCall({
		method: "lms_saas.api.field_collection.undo_collection",
		args: { loan: loan, repayment: repayment },
		callback: function () {
			if (typeof onOk === "function") onOk();
		},
		error: function () {
			if (typeof onErr === "function") onErr();
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
	// R18-7: kick off real health-check polling. navigator.onLine alone is
	// unreliable on 1-bar GPRS / Spotty Wi-Fi — the OS reports "online" but
	// every API call hangs. ping the server every 30 s and surface the
	// actual state on the connectivity pill.
	lms_collect._initHealthCheck();
};

/* R18-7: real connectivity check. Polls /api/method/lms_saas.api.healthcheck.ping
 * every 30 s, plus on every 'online' / 'offline' event. Updates the
 * `lms-connectivity` pill's class + label so the collector sees the real
 * state instead of the OS-level guess. */
lms_collect._initHealthCheck = function () {
	if (lms_collect._healthTimer) return; // already initialised
	var update = function (state, label) {
		var el = document.getElementById("lms-connectivity");
		if (!el) return;
		el.classList.remove("is-online", "is-offline", "is-degraded");
		el.classList.add("is-" + state);
		var text = el.querySelector(".lms-connectivity__label");
		if (text) text.textContent = label;
	};
	var probe = function () {
		// Treat OS offline as hard-offline; no need to probe.
		if (typeof navigator !== "undefined" && navigator.onLine === false) {
			update("offline", "Offline — payments will queue on this device");
			return;
		}
		var start = Date.now();
		// R18-7: use raw fetch (no safeCall spinner) so a slow probe does not
		// fight the rest of the UI. Cast to a Promise for callers that await.
		fetch("/api/method/lms_saas.api.healthcheck.ping", {
			method: "GET",
			credentials: "same-origin",
			cache: "no-store",
		})
			.then(function (resp) {
				var ms = Date.now() - start;
				if (!resp.ok) {
					update("offline", "Server unreachable — payments will queue");
					return;
				}
				if (ms > 5000) {
					update("degraded", "Online — server slow (" + ms + " ms)");
				} else {
					update("online", "Online — sync OK (" + ms + " ms)");
				}
			})
			.catch(function () {
				update("offline", "Offline — payments will queue on this device");
			});
	};
	probe();
	lms_collect._healthTimer = setInterval(probe, 30000);
	window.addEventListener("online", probe);
	window.addEventListener("offline", probe);
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
