/* LMS Inventory & Assets portal — asset register, stock, low stock alerts */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_inventory");
} else {
	window.lms_inventory = window.lms_inventory || {};
}

lms_inventory._currentTab = "assets";

lms_inventory.init = function () {
	var root = document.getElementById("lms-inventory-root");
	if (!root) return;

	var tabs = [
		{ id: "assets", label: "Assets", icon: "📦" },
		{ id: "stock", label: "Stock", icon: "📋" },
		{ id: "lowstock", label: "Low Stock Alerts", icon: "⚠️" },
	];
	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "Inventory & Assets" }) +
		lms_portal.tabNav(tabs, lms_inventory._currentTab) +
		'<div id="lms-inv-stats"></div>' +
		'<div id="lms-inv-tab-content"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_portal.bindTabs({
		root: root,
		tabs: tabs,
		onTab: function (tabId) { lms_inventory._currentTab = tabId; lms_inventory._showTab(tabId); },
	});

	lms_inventory._loadStats();
	lms_inventory._showTab(lms_inventory._currentTab);
};

lms_inventory._showTab = function (tabId) {
	var content = document.getElementById("lms-inv-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "assets") lms_inventory._loadAssets(content);
	else if (tabId === "stock") lms_inventory._loadStock(content);
	else if (tabId === "lowstock") lms_inventory._loadLowStock(content);
};

lms_inventory._loadStats = function () {
	var el = document.getElementById("lms-inv-stats");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.inventory.get_inventory_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			el.innerHTML = lms_portal.kpiStrip([
				{ label: "Total Assets", value: s.total_assets || 0 },
				{ label: "Active Assets", value: s.active_assets || 0, tone: "success" },
				{ label: "Stock Items", value: s.stock_items || 0 },
				{ label: "Low Stock", value: s.low_stock_items || 0, tone: "danger" },
			]);
		},
	});
};

lms_inventory._loadAssets = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.inventory.get_asset_register",
		callback: function (r) {
			var assets = (r && r.message && r.message.assets) || [];
			if (!assets.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📦</div><h3>No assets</h3><p>No assets found for your branch.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Asset</th><th>Category</th><th>Status</th><th>Purchase Date</th><th>Value</th><th>Custodian</th><th>Action</th></tr></thead><tbody>";
			assets.forEach(function (a) {
				var statusClass = a.status === "Submitted" ? "lms-badge--success" : (a.status === "Cancelled" ? "lms-badge--danger" : "");
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(a.asset_name || a.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(a.asset_category || "—") + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(a.status || "—") + "</span></td>";
				html += "<td>" + lms_portal.formatDate(a.purchase_date) + "</td>";
				html += "<td>" + format_currency(a.asset_value || a.gross_purchase_amount || 0) + "</td>";
				html += "<td>" + lms_portal.escape(a.custodian || "—") + "</td>";
				html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-inv-view-asset" data-name="' + lms_portal.escape(a.name) + '">View</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-inv-view-asset").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_inventory._showAssetDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load assets.");
		},
	});
};

lms_inventory._showAssetDetail = function (assetName) {
	lms_portal.safeCall({
		method: "lms_saas.api.inventory.get_asset_detail",
		args: { asset_name: assetName },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_inventory._renderAssetDetail(data);
		},
	});
};

lms_inventory._renderAssetDetail = function (data) {
	var a = data.asset || {};
	var dep = data.depreciation || [];

	var html = '<div class="lms-form">';
	html += '<h3 style="margin:0 0 0.5rem;">' + lms_portal.escape(a.asset_name || a.name) + '</h3>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(a.status || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Category</div><div class="lms-summary-value">' + lms_portal.escape(a.asset_category || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Purchase Date</div><div class="lms-summary-value">' + lms_portal.formatDate(a.purchase_date) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Value</div><div class="lms-summary-value">' + format_currency(a.asset_value || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Acc. Depreciation</div><div class="lms-summary-value">' + format_currency(a.accumulated_depreciation || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Custodian</div><div class="lms-summary-value">' + lms_portal.escape(a.custodian || "—") + '</div></div>';
	html += '</div>';

	if (dep.length) {
		html += '<h4 style="margin:1rem 0 0.5rem;">Depreciation Schedule</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
		html += "<thead><tr><th>Date</th><th>Depreciation</th><th>Accumulated</th><th>Book Value</th></tr></thead><tbody>";
		dep.forEach(function (d) {
			html += "<tr>";
			html += "<td>" + lms_portal.formatDate(d.schedule_date) + "</td>";
			html += "<td>" + format_currency(d.depreciation_amount || 0) + "</td>";
			html += "<td>" + format_currency(d.accumulated_depreciation || 0) + "</td>";
			html += "<td>" + format_currency(d.book_value || 0) + "</td>";
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}

	html += '</div>';

	lms_portal.modal({
		title: "Asset Detail",
		body: html,
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});
};

lms_inventory._loadStock = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.inventory.get_stock_items",
		callback: function (r) {
			var items = (r && r.message && r.message.items) || [];
			if (!items.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📋</div><h3>No stock items</h3><p>No stock items found.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Item</th><th>Group</th><th>UOM</th><th>Total Qty</th><th>Reorder Level</th><th>Rate</th></tr></thead><tbody>";
			items.forEach(function (it) {
				var lowClass = (it.reorder_level && it.total_qty <= it.reorder_level) ? "lms-badge--danger" : "";
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(it.item_name || it.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(it.item_group || "—") + "</td>";
				html += "<td>" + lms_portal.escape(it.stock_uom || "—") + "</td>";
				html += '<td><span class="lms-badge ' + lowClass + '">' + (it.total_qty || 0) + "</span></td>";
				html += "<td>" + (it.reorder_level || 0) + "</td>";
				html += "<td>" + format_currency(it.standard_rate || 0) + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load stock items.");
		},
	});
};

lms_inventory._loadLowStock = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.inventory.get_low_stock_items",
		callback: function (r) {
			var items = (r && r.message && r.message.items) || [];
			if (!items.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">✓</div><h3>All stocked</h3><p>No items below reorder level.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Item</th><th>Group</th><th>Current Qty</th><th>Reorder Level</th><th>Shortfall</th><th>Rate</th></tr></thead><tbody>";
			items.forEach(function (it) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(it.item_name || it.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(it.item_group || "—") + "</td>";
				html += '<td><span class="lms-badge lms-badge--danger">' + (it.total_qty || 0) + "</span></td>";
				html += "<td>" + (it.reorder_level || 0) + "</td>";
				html += '<td><span class="lms-badge lms-badge--warning">' + (it.shortfall || 0) + "</span></td>";
				html += "<td>" + format_currency(it.standard_rate || 0) + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load low stock items.");
		},
	});
};