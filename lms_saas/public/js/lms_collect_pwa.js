/* LMS field collection PWA */
frappe.provide("lms_collect");

lms_collect.DB_NAME = "lms_collect_queue";
lms_collect.STORE = "repayments";

lms_collect.init = function () {
	var root = document.getElementById("lms-collect-root");
	if (!root) return;
	root.innerHTML = lms_portal.loading("Loading run sheet…");
	lms_collect._registerServiceWorker();
	lms_collect._loadRunSheet(root);
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

lms_collect._renderRunSheet = function (root, rows) {
	var queueCount = lms_collect._offlineQueueCount();
	var html = '<div class="lms-panel"><h3>Due today & upcoming</h3>';

	if (!rows.length) {
		html += '<p class="lms-muted">No dues in range.</p>';
	} else {
		html += '<ul class="lms-list">';
		rows.forEach(function (row) {
			var mobile = row.borrower_mobile || "";
			var callBtn = mobile
				? '<a class="lms-btn lms-btn--ghost lms-btn--sm" href="tel:' + lms_portal.escape(mobile) + '">Call</a>'
				: "";
			html +=
				'<li class="lms-list__item">' +
				'<div class="lms-list__info">' +
				'<strong>' + lms_portal.escape(row.borrower) + "</strong>" +
				" — " + lms_portal.formatDate(row.due_date) +
				" — " + format_currency(row.amount) +
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
		html += "</ul>";
	}

	html += '<div class="lms-collect-sync">';
	html += '<button type="button" class="lms-btn lms-btn--secondary" id="lms-sync-offline">Sync offline queue';
	if (queueCount > 0) {
		html += ' <span class="lms-badge lms-badge--watch">' + queueCount + "</span>";
	}
	html += "</button></div></div>";

	root.innerHTML = html;

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
	var modalHtml =
		'<div class="lms-modal-overlay" id="lms-collect-modal">' +
		'<div class="lms-modal">' +
		"<h3>Collect payment</h3>" +
		'<div class="lms-form">' +
		'<label>Amount<input type="number" id="lms-collect-amount" class="lms-input" value="' +
		fullAmount +
		'" min="0.01" step="0.01"></label>' +
		'<label>Payment mode<select id="lms-collect-mode" class="lms-input">' +
		'<option value="Cash">Cash</option>' +
		'<option value="EcoCash">EcoCash</option>' +
		'<option value="OneMoney">OneMoney</option>' +
		'<option value="Bank Transfer">Bank Transfer</option>' +
		"</select></label>" +
		'<label>Note (optional)<input type="text" id="lms-collect-note" class="lms-input" placeholder="e.g. partial payment"></label>' +
		"</div>" +
		'<div class="lms-modal-actions">' +
		'<button type="button" class="lms-btn lms-btn--ghost" id="lms-collect-cancel">Cancel</button>' +
		'<button type="button" class="lms-btn lms-btn--primary" id="lms-collect-confirm">Collect</button>' +
		"</div></div></div>";

	document.body.insertAdjacentHTML("beforeend", modalHtml);
	var modal = document.getElementById("lms-collect-modal");

	document.getElementById("lms-collect-cancel").addEventListener("click", function () {
		modal.remove();
	});
	document.getElementById("lms-collect-confirm").addEventListener("click", function () {
		var amount = parseFloat(document.getElementById("lms-collect-amount").value) || 0;
		var mode = document.getElementById("lms-collect-mode").value;
		var note = document.getElementById("lms-collect-note").value;
		modal.remove();
		lms_collect._collect(loan, amount, mode, root, note, fullAmount);
	});
};

lms_collect._openPromiseModal = function (loan, root) {
	var today = new Date().toISOString().slice(0, 10);
	var modalHtml =
		'<div class="lms-modal-overlay" id="lms-promise-modal">' +
		'<div class="lms-modal">' +
		"<h3>Promise to pay</h3>" +
		'<div class="lms-form">' +
		'<label>Promised date<input type="date" id="lms-promise-date" class="lms-input" value="' +
		today +
		'"></label>' +
		'<label>Amount (optional)<input type="number" id="lms-promise-amount" class="lms-input" min="0" step="0.01"></label>' +
		'<label>Note<input type="text" id="lms-promise-note" class="lms-input" placeholder="e.g. will pay after salary"></label>' +
		"</div>" +
		'<div class="lms-modal-actions">' +
		'<button type="button" class="lms-btn lms-btn--ghost" id="lms-promise-cancel">Cancel</button>' +
		'<button type="button" class="lms-btn lms-btn--primary" id="lms-promise-confirm">Save promise</button>' +
		"</div></div></div>";

	document.body.insertAdjacentHTML("beforeend", modalHtml);
	var modal = document.getElementById("lms-promise-modal");

	document.getElementById("lms-promise-cancel").addEventListener("click", function () {
		modal.remove();
	});
	document.getElementById("lms-promise-confirm").addEventListener("click", function () {
		var date = document.getElementById("lms-promise-date").value;
		var amount = document.getElementById("lms-promise-amount").value;
		var note = document.getElementById("lms-promise-note").value;
		modal.remove();
		frappe.call({
			method: "lms_saas.api.field_collection.create_promise_to_pay",
			args: { loan: loan, promised_date: date, promised_amount: amount, note: note },
			callback: function () {
				frappe.show_alert({ message: "Promise to pay recorded.", indicator: "green" });
			},
			error: function () {
				frappe.show_alert({ message: "Could not save promise.", indicator: "red" });
			},
		});
	});
};

lms_collect._collect = function (loan, amount, payment_mode, root, note, fullAmount) {
	var isPartial = fullAmount && amount < fullAmount;
	if (!navigator.onLine) {
		lms_collect._queueOffline({ loan: loan, amount: amount, payment_mode: payment_mode, note: note });
		frappe.show_alert({ message: "Saved offline — sync when online", indicator: "orange" });
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
			frappe.show_alert({ message: "Repayment recorded", indicator: "green" });
			if (res.repayment) {
				lms_collect._showReceiptPrompt(res.repayment);
			}
			lms_collect._loadRunSheet(root);
		},
		error: function () {
			frappe.show_alert({ message: "Collection failed. Try again.", indicator: "red" });
		},
	});
};

lms_collect._showReceiptPrompt = function (repaymentName) {
	var modalHtml =
		'<div class="lms-modal-overlay" id="lms-receipt-modal">' +
		'<div class="lms-modal">' +
		"<h3>Collection successful</h3>" +
		'<p>Repayment <strong>' + lms_portal.escape(repaymentName) + "</strong> recorded.</p>" +
		'<div class="lms-modal-actions">' +
		'<button type="button" class="lms-btn lms-btn--ghost" id="lms-receipt-close">Close</button>' +
		'<button type="button" class="lms-btn lms-btn--primary" id="lms-receipt-download">Download receipt</button>' +
		"</div></div></div>";
	document.body.insertAdjacentHTML("beforeend", modalHtml);
	var modal = document.getElementById("lms-receipt-modal");
	document.getElementById("lms-receipt-close").addEventListener("click", function () {
		modal.remove();
	});
	document.getElementById("lms-receipt-download").addEventListener("click", function () {
		window.open(
			"/api/method/lms_saas.api.field_collection.generate_collection_receipt?repayment_name=" +
				encodeURIComponent(repaymentName),
			"_blank"
		);
		modal.remove();
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
		frappe.show_alert({ message: "Nothing to sync", indicator: "blue" });
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
				frappe.show_alert({ message: "Offline queue synced (" + results.length + ")", indicator: "green" });
			}
			lms_collect._loadRunSheet(root);
		},
		error: function () {
			frappe.show_alert({ message: "Sync failed. Try again.", indicator: "red" });
		},
	});
};

lms_collect._showSyncErrors = function (failed) {
	var html =
		'<div class="lms-modal-overlay" id="lms-sync-error-modal">' +
		'<div class="lms-modal">' +
		"<h3>Sync conflicts</h3>" +
		'<p class="lms-muted">' + failed.length + " item(s) could not be synced:</p>" +
		'<ul class="lms-sync-error-list">';
	failed.forEach(function (item) {
		html +=
			"<li><strong>" + lms_portal.escape(item.loan) + "</strong>: " +
			lms_portal.escape(item.error || "Unknown error") + "</li>";
	});
	html += "</ul>";
	html +=
		'<div class="lms-modal-actions">' +
		'<button type="button" class="lms-btn lms-btn--ghost" id="lms-sync-error-close">Close</button>' +
		"</div></div></div>";
	document.body.insertAdjacentHTML("beforeend", html);
	document.getElementById("lms-sync-error-close").addEventListener("click", function () {
		document.getElementById("lms-sync-error-modal").remove();
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
