/* LMS Procurement portal — requests, orders, suppliers, stats */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_procurement");
} else {
	window.lms_procurement = window.lms_procurement || {};
}

lms_procurement._currentTab = "requests";

lms_procurement.init = function () {
	var root = document.getElementById("lms-procurement-root");
	if (!root) return;

	var tabs = [
		{ id: "requests", label: "Requests", icon: "📝" },
		{ id: "orders", label: "Orders", icon: "📦" },
		{ id: "suppliers", label: "Suppliers", icon: "🏢" },
		{ id: "stats", label: "Stats", icon: "📊" },
	];
	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "Procurement" }) +
		lms_portal.tabNav(tabs, lms_procurement._currentTab) +
		'<div id="lms-proc-tab-content"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_portal.bindTabs({
		root: root,
		tabs: tabs,
		onTab: function (tabId) { lms_procurement._currentTab = tabId; lms_procurement._showTab(tabId); },
	});

	lms_procurement._showTab(lms_procurement._currentTab);
};

lms_procurement._showTab = function (tabId) {
	var content = document.getElementById("lms-proc-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "requests") lms_procurement._loadRequests(content);
	else if (tabId === "orders") lms_procurement._loadOrders(content);
	else if (tabId === "suppliers") lms_procurement._loadSuppliers(content);
	else if (tabId === "stats") lms_procurement._loadStats(content);
};

lms_procurement._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_procurement._loadRequests = function (content) {
	var html = '<div class="lms-proc-actions"><button type="button" class="lms-btn lms-btn--primary" id="lms-proc-new-req">+ New Purchase Request</button></div>';
	content.innerHTML = html + '<div id="lms-proc-req-list"></div>';

	var btn = content.querySelector("#lms-proc-new-req");
	if (btn) {
		btn.addEventListener("click", function () {
			lms_procurement._showCreateRequestModal();
		});
	}

	var listEl = content.querySelector("#lms-proc-req-list");
	listEl.innerHTML = lms_portal.loading("Loading…");

	lms_portal.safeCall({
		method: "lms_saas.api.procurement.get_purchase_requests",
		callback: function (r) {
			var msg = r && r.message;
			if (msg && msg._missing) {
				listEl.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("📝") + '<h3>Procurement is unavailable</h3><p>' + lms_portal.escape(msg.message || "") + '</p></div></div>';
				return;
			}
			var requests = (msg && msg.requests) || [];
			if (!requests.length) {
				listEl.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("📝") + '<h3>No requests</h3><p>No purchase requests found for your branch.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Request</th><th>Type</th><th>Status</th><th>Date</th><th>% Ordered</th><th>Total Qty</th></tr></thead><tbody>";
			requests.forEach(function (req) {
				var statusClass = req.status === "Ordered" ? "lms-badge--success" : (req.status === "Pending" ? "lms-badge--warning" : (req.status === "Cancelled" ? "lms-badge--danger" : ""));
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(req.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(req.material_request_type || "—") + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(req.status || "") + "</span></td>";
				html += "<td>" + lms_portal.formatDate(req.transaction_date) + "</td>";
				html += "<td>" + (req.per_ordered || 0) + "%</td>";
				html += "<td>" + (req.total_req_qty || 0) + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			listEl.innerHTML = html;
		},
		error: function () {
			listEl.innerHTML = lms_portal.error("Could not load purchase requests.");
		},
	});
};

lms_procurement._showCreateRequestModal = function () {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Request Type</label>';
	html += '<select id="lms-proc-type" class="lms-input lms-fallback-select">';
	html += '<option value="Purchase">Purchase</option>';
	html += '<option value="Material Transfer">Material Transfer</option>';
	html += '<option value="Material Issue">Material Issue</option>';
	html += '<option value="Store Material">Store Material</option>';
	html += '</select></div>';
	html += '<div class="lms-field"><label>Schedule Date</label>';
	html += '<input type="date" id="lms-proc-schedule" class="lms-input"></div>';
	html += '<div class="lms-field"><label>Remark</label>';
	html += '<input type="text" id="lms-proc-remark" class="lms-input" placeholder="Optional note"></div>';
	html += '<hr style="margin:1rem 0;border:none;border-top:1px solid var(--lms-border);">';
	html += '<h4>Items</h4>';
	html += '<div id="lms-proc-items"></div>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-proc-add-item">+ Add Item</button>';
	html += '</div>';

	lms_portal.modal({
		title: "New Purchase Request",
		body: html,
		size: "lg",
		confirmText: "Submit",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var type = overlay.querySelector("#lms-proc-type").value;
			var schedule = overlay.querySelector("#lms-proc-schedule").value;
			var remark = overlay.querySelector("#lms-proc-remark").value;
			var items = [];
			overlay.querySelectorAll(".lms-proc-item-row").forEach(function (row) {
				var code = row.querySelector(".lms-proc-item-code").value;
				var qty = row.querySelector(".lms-proc-item-qty").value;
				var uom = row.querySelector(".lms-proc-item-uom").value;
				var rate = row.querySelector(".lms-proc-item-rate").value;
				if (code && qty) {
					var item = { item_code: code, qty: qty, uom: uom || "Nos" };
					if (rate) item.rate = rate;
					items.push(item);
				}
			});
			if (!items.length) {
				lms_portal.toast("At least one item is required.", "danger");
				return false;
			}
			lms_portal.safeCall({
				method: "lms_saas.api.procurement.create_purchase_request",
				args: {
					material_request_type: type,
					items: JSON.stringify(items),
					remark: remark,
					schedule_date: schedule,
				},
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Request created: " + (res.name || ""), "success");
					lms_procurement._showTab("requests");
				},
				error: function () {
					lms_portal.toast("Could not create request.", "danger");
				},
			});
		},
	});

	// Add item rows
	var itemsContainer = document.querySelector("#lms-proc-items");
	var addBtn = document.querySelector("#lms-proc-add-item");
	if (addBtn && itemsContainer) {
		var addItemRow = function () {
			var idx = itemsContainer.querySelectorAll(".lms-proc-item-row").length;
			var rowHtml = '<div class="lms-proc-item-row" style="display:flex;gap:0.5rem;margin-bottom:0.5rem;align-items:end;">';
			rowHtml += '<div class="lms-field" style="flex:2;"><label>Item Code</label><input type="text" class="lms-input lms-proc-item-code" placeholder="ITEM-0001"></div>';
			rowHtml += '<div class="lms-field" style="flex:1;"><label>Qty</label><input type="number" class="lms-input lms-proc-item-qty" value="1" min="1"></div>';
			rowHtml += '<div class="lms-field" style="flex:1;"><label>UOM</label><input type="text" class="lms-input lms-proc-item-uom" value="Nos"></div>';
			rowHtml += '<div class="lms-field" style="flex:1;"><label>Rate</label><input type="number" class="lms-input lms-proc-item-rate" placeholder="0.00" step="0.01"></div>';
			rowHtml += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-proc-remove-item" style="margin-bottom:0.35rem;">×</button>';
			rowHtml += '</div>';
			var div = document.createElement("div");
			div.innerHTML = rowHtml;
			itemsContainer.appendChild(div.firstChild);
			itemsContainer.lastChild.querySelector(".lms-proc-remove-item").addEventListener("click", function (e) {
				e.target.closest(".lms-proc-item-row").remove();
			});
		};
		addItemRow(); // Start with one row
		addBtn.addEventListener("click", addItemRow);
	}
};

lms_procurement._loadOrders = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.procurement.get_purchase_orders",
		callback: function (r) {
			var msg = r && r.message;
			if (msg && msg._missing) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("📦") + '<h3>Procurement is unavailable</h3><p>' + lms_portal.escape(msg.message || "") + '</p></div></div>';
				return;
			}
			var orders = (msg && msg.orders) || [];
			if (!orders.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("📦") + '<h3>No orders</h3><p>No purchase orders found for your branch.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>PO</th><th>Supplier</th><th>Status</th><th>Date</th><th>Total</th><th>% Received</th><th>% Billed</th></tr></thead><tbody>";
			orders.forEach(function (o) {
				var statusClass = o.status === "Completed" ? "lms-badge--success" : (o.status === "To Receive and Bill" ? "lms-badge--warning" : (o.status === "Cancelled" ? "lms-badge--danger" : ""));
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(o.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(o.supplier_name || "—") + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(o.status || "") + "</span></td>";
				html += "<td>" + lms_portal.formatDate(o.transaction_date) + "</td>";
				html += "<td>" + format_currency(o.grand_total || 0) + "</td>";
				html += "<td>" + (o.per_received || 0) + "%</td>";
				html += "<td>" + (o.per_billed || 0) + "%</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load purchase orders.");
		},
	});
};

lms_procurement._loadSuppliers = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.procurement.get_suppliers",
		callback: function (r) {
			var msg = r && r.message;
			if (msg && msg._missing) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("🏢") + '<h3>Procurement is unavailable</h3><p>' + lms_portal.escape(msg.message || "") + '</p></div></div>';
				return;
			}
			var suppliers = (msg && msg.suppliers) || [];
			if (!suppliers.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("🏢") + '<h3>No suppliers</h3><p>No approved suppliers found.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Supplier</th><th>Group</th><th>Country</th><th>Type</th><th>Payment Terms</th></tr></thead><tbody>";
			suppliers.forEach(function (s) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(s.supplier_name || s.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(s.supplier_group || "—") + "</td>";
				html += "<td>" + lms_portal.escape(s.country || "—") + "</td>";
				html += "<td>" + lms_portal.escape(s.supplier_type || "—") + "</td>";
				html += "<td>" + lms_portal.escape(s.payment_terms || "—") + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load suppliers.");
		},
	});
};

lms_procurement._loadStats = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.procurement.get_procurement_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			if (s._missing) {
				content.innerHTML = lms_portal.emptyPanel("📊", "Procurement is unavailable", s.message || "");
				return;
			}
			var html = '<section class="lms-grid-4 lms-proc-kpis">';
			html += lms_procurement._statCard("Spend This Month", format_currency(s.total_spend_this_month || 0));
			html += lms_procurement._statCard("Orders This Month", s.total_orders_this_month || 0);
			html += lms_procurement._statCard("Pending Requests", s.pending_requests || 0, "warning");
			html += lms_procurement._statCard("Suppliers", s.supplier_count || 0);
			html += "</section>";

			// Monthly spend chart
			var monthly = s.monthly_spend || [];
			if (monthly.length) {
				html += '<div class="lms-panel lms-proc-chart-panel"><h3>Monthly Spend (6 months)</h3>';
				html += lms_portal.simpleBars(monthly);
				html += '</div>';
			}

			// Top suppliers
			var suppliers = s.spend_by_supplier || [];
			if (suppliers.length) {
				html += '<div class="lms-panel"><h3>Top Suppliers This Month</h3>';
				html += lms_portal.simpleBars(suppliers);
				html += '</div>';
			}

			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load procurement stats.");
		},
	});
};