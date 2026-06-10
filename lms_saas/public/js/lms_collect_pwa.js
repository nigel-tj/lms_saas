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
			var html = '<div class="lms-panel"><h3>Due today & upcoming</h3><ul class="lms-list">';
			if (!rows.length) {
				html += "<li>No dues in range.</li>";
			}
			rows.forEach(function (row) {
				html +=
					'<li class="lms-list__item"><strong>' +
					lms_portal.escape(row.borrower) +
					"</strong> — " +
					lms_portal.formatDate(row.due_date) +
					" — " +
					lms_portal.escape(String(row.amount)) +
					' <button type="button" class="lms-btn lms-btn--primary lms-collect-btn" data-loan="' +
					lms_portal.escape(row.loan) +
					'" data-amount="' +
					lms_portal.escape(String(row.amount)) +
					'">Collect</button></li>';
			});
			html += "</ul>";
			html +=
				'<button type="button" class="lms-btn lms-btn--secondary" id="lms-sync-offline">Sync offline queue</button>';
			html += "</div>";
			root.innerHTML = html;
			root.querySelectorAll(".lms-collect-btn").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_collect._collect(btn.getAttribute("data-loan"), btn.getAttribute("data-amount"), root);
				});
			});
			var syncBtn = document.getElementById("lms-sync-offline");
			if (syncBtn) {
				syncBtn.addEventListener("click", function () {
					lms_collect._syncOffline(root);
				});
			}
		},
	});
};

lms_collect._collect = function (loan, amount, root) {
	if (!navigator.onLine) {
		lms_collect._queueOffline({ loan: loan, amount: amount, payment_mode: "Cash" });
		frappe.show_alert({ message: "Saved offline — sync when online", indicator: "orange" });
		return;
	}
	frappe.call({
		method: "lms_saas.api.field_collection.record_field_repayment",
		args: { loan: loan, amount: amount, payment_mode: "Cash" },
		callback: function () {
			frappe.show_alert({ message: "Repayment recorded", indicator: "green" });
			lms_collect._loadRunSheet(root);
		},
	});
};

lms_collect._queueOffline = function (item) {
	try {
		var q = JSON.parse(localStorage.getItem(lms_collect.DB_NAME) || "[]");
		q.push(item);
		localStorage.setItem(lms_collect.DB_NAME, JSON.stringify(q));
	} catch (e) {}
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
		callback: function () {
			localStorage.removeItem(lms_collect.DB_NAME);
			frappe.show_alert({ message: "Offline queue synced", indicator: "green" });
			lms_collect._loadRunSheet(root);
		},
	});
};
