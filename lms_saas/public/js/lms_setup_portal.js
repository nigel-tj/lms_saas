/* LMS Operations Manager Setup Portal — R52-T5.
 *
 * Nine-tab portal:
 *   1. Loan Products          (Tier A — draft→approve flow)
 *   2. Credit Policies        (Tier A — T3 future)
 *   3. Loan Purposes          (Tier B)
 *   4. Centers                (Tier B)
 *   5. Lending Groups         (Tier B)
 *   6. Announcements          (Tier B)
 *   7. Document Categories    (Tier B)
 *   8. Payment Providers      (Tier B)
 *   9. Change Requests        (Tier A — review + approve/reject)
 *
 * The Tier A tabs surface a "Propose Change" button that opens the
 * draft modal. Submission creates an LMS Setup Change Request row and
 * switches to the Change Requests tab. The Tier B tabs use an inline
 * modal editor + an "Add new" button.
 *
 * The portal page already gates on can_setup before this script loads,
 * so every API call here expects 200. If we see 403/401 we render an
 * access card via lms_portal.forbiddenOrError instead of crashing.
 */

if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_setup");
} else {
	window.lms_setup = window.lms_setup || {};
}

lms_setup._currentTab = "loan_products";
lms_setup._TAB_TIMEOUT_MS = 6000;
lms_setup._tabs = [
	{ id: "loan_products",        label: "Loan Products",       singular: "Loan Product",      icon: "briefcase",   kind: "tierA" },
	{ id: "credit_policies",      label: "Credit Policies",     singular: "Credit Policy",     icon: "shield",      kind: "tierA" },
	{ id: "loan_purposes",        label: "Loan Purposes",       singular: "Loan Purpose",      icon: "tag",         kind: "tierB" },
	{ id: "centers",              label: "Centers",             singular: "Center",            icon: "map-pin",     kind: "tierB" },
	{ id: "lending_groups",       label: "Lending Groups",      singular: "Lending Group",     icon: "users",       kind: "tierB" },
	{ id: "announcements",        label: "Announcements",       singular: "Announcement",      icon: "bell",        kind: "tierB" },
	{ id: "document_categories",  label: "Document Categories", singular: "Document Category", icon: "file-text",   kind: "tierB" },
	{ id: "payment_providers",    label: "Payment Providers",   singular: "Payment Provider",  icon: "credit-card", kind: "tierB" },
	{ id: "change_requests",      label: "Change Requests",     singular: "Change Request",    icon: "inbox",       kind: "tierA" },
];

lms_setup.init = function () {
	if (typeof lms_portal === "undefined" || typeof lms_portal.tabNav !== "function") {
		return setTimeout(lms_setup.init, 0);
	}
	var root = document.getElementById("lms-setup-root");
	if (!root) return;

	lms_setup._currentTab = lms_portal.persistedTab("setup", lms_setup._currentTab);

	root.innerHTML = lms_setup._header() + lms_setup._tabNav() +
		'<div id="lms-setup-tab-content" class="lms-setup-content"></div>';
	lms_setup._bindTabs();
	lms_setup._showTab(lms_setup._currentTab);
};

lms_setup._header = function () {
	// Two-line header: title + helper. The badge on each panel shows
	// whether changes need approval; the subtitle explains the split in
	// plain language without internal release terminology.
	return '<div class="lms-setup-header">' +
		'<h1 class="lms-setup-title">Operations Manager Setup</h1>' +
		'<p class="lms-setup-subtitle lms-muted">Configure loan products, credit policies, and operational settings. Loan products and credit policies need administrator approval before changes take effect; everything else on this page updates immediately.</p>' +
		'</div>';
};

lms_setup._tabNav = function () {
	var tabs = lms_setup._tabs;
	var html = '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_setup._currentTab === t.id ? " is-active" : "";
		var icon = (window.lms_icons && lms_icons.icon)
			? lms_icons.icon(t.icon, { size: 16, cls: "lms-tab-icon" })
			: "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + icon + '<span class="lms-tab-label">' + lms_portal.escape(t.label) + '</span></button>';
	});
	html += "</nav>";
	return html;
};

lms_setup._bindTabs = function () {
	var root = document.getElementById("lms-setup-root");
	if (!root) return;
	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			var tabId = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.setAttribute("aria-selected", "true");
			lms_setup._currentTab = tabId;
			lms_portal.saveActiveTab("setup", tabId);
			lms_setup._showTab(tabId);
		});
	});
};

lms_setup._guardedCall = function (opts) {
	return lms_portal.guardedCall(Object.assign({}, opts, { timeoutMs: lms_setup._TAB_TIMEOUT_MS }));
};

lms_setup._showTab = function (tabId) {
	var content = document.getElementById("lms-setup-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	var handler = lms_setup._tabHandlers[tabId];
	if (typeof handler === "function") {
		try { handler(content); }
		catch (e) { console.error("[lms_setup] handler error", e); content.innerHTML = lms_portal.error("Tab failed to render."); }
	} else {
		content.innerHTML = lms_portal.error("Unknown tab: " + lms_portal.escape(tabId));
	}
};

// ===========================================================================
// Tier A — Loan Products
// ===========================================================================

lms_setup._tabHandlers = {};

lms_setup._tabHandlers.loan_products = function (content) {
	lms_setup._loadTierAList(content, {
		tabId: "loan_products",
		title: "Loan Products",
		subtitle: "Products the company offers to borrowers. Any change you make here is sent to an administrator for approval before it takes effect.",
		listMethod: "lms_saas.api.setup.list_loan_products",
		listKey: "products",
		emptyMessage: "No loan products configured yet. Use Propose New Product to draft the first one.",
		columns: [
			{ key: "name",              label: "Name",           render: function (r) { return lms_portal.escape(r.name || ""); } },
			{ key: "product_code",      label: "Code" },
			{ key: "product_name",      label: "Product Name" },
			{ key: "rate_of_interest",  label: "Rate %", render: function (r) { return r.rate_of_interest != null ? Number(r.rate_of_interest).toFixed(2) : ""; } },
			{ key: "maximum_loan_amount", label: "Max Amount", render: function (r) { return r.maximum_loan_amount != null ? lms_portal.formatCurrency(r.maximum_loan_amount) : ""; } },
			{ key: "disabled",          label: "Status", render: function (r) { return r.disabled ? '<span class="lms-badge lms-badge--npa">Disabled</span>' : '<span class="lms-badge lms-badge--current">Active</span>'; } },
		],
		primaryAction: { label: "Propose New Product", kind: "create" },
		rowActions: [
			{ label: "Edit", kind: "edit" },
			{ label: "Disable", kind: "disable", confirm: true },
		],
		draftSchema: {
			fields: [
				{ key: "product_code",         label: "Product Code",         type: "text",   required: true },
				{ key: "product_name",         label: "Product Name",         type: "text",   required: true },
				{ key: "rate_of_interest",     label: "Rate of Interest (%)", type: "number",  required: true, step: "0.01" },
				{ key: "maximum_loan_amount",  label: "Maximum Loan Amount",  type: "number",  required: true, step: "0.01" },
				{ key: "minimum_loan_amount",  label: "Minimum Loan Amount",  type: "number",  step: "0.01" },
				{ key: "repayment_periods",    label: "Repayment Periods",    type: "number",  step: "1" },
				{ key: "repayment_frequency",  label: "Repayment Frequency",  type: "select",  options: ["Daily", "Weekly", "Biweekly", "Monthly"] },
				{ key: "interest_method",      label: "Interest Method",      type: "select",  options: ["Flat", "Reducing", "Compound"] },
				{ key: "description",          label: "Description",          type: "textarea" },
			],
		},
	});
};

lms_setup._tabLabel = function (tab) {
	return (tab && tab.singular) ? tab.singular : ((tab && tab.label) ? tab.label.replace(/s$/, "") : "");
};

lms_setup._tabHandlers.credit_policies = function (content) {
	content.innerHTML = lms_portal.panel({
		title: "Credit Policies",
		body:
			'<div class="lms-empty">' +
			(lms_icons.empty ? lms_icons.empty("shield") : '<div class="lms-empty-icon">◇</div>') +
			'<h3>Credit policy editor coming soon</h3>' +
			'<p>You will be able to draft credit policies here for administrator approval. In the meantime, you can review existing proposals under Change Requests.</p>' +
			'<p style="margin-top:0.75rem;"><a class="lms-btn lms-btn--primary" href="#" role="button" data-lms-setup-jump-tab="change_requests">View change requests</a></p>' +
			'</div>',
	});
	// Bind the jump link inside the panel so the empty state actually
	// takes the user somewhere. Falls back to no-op if the element is
	// removed by a future editor implementation.
	var jumpBtn = content.querySelector("[data-lms-setup-jump-tab]");
	if (jumpBtn) {
		jumpBtn.addEventListener("click", function (e) {
			e.preventDefault();
			var root = document.getElementById("lms-setup-root");
			if (root) {
				var target = jumpBtn.getAttribute("data-lms-setup-jump-tab");
				root.querySelectorAll(".lms-tab").forEach(function (b) {
					var match = b.getAttribute("data-tab") === target;
					b.classList.toggle("is-active", match);
					b.setAttribute("aria-selected", match ? "true" : "false");
				});
				lms_setup._currentTab = target;
				if (typeof lms_portal.saveActiveTab === "function") {
					lms_portal.saveActiveTab("setup", target);
				}
				lms_setup._showTab(target);
			}
		});
	}
};

lms_setup._loadTierAList = function (content, opts) {
	var listP = lms_setup._guardedCall({ method: opts.listMethod });
	listP.then(function (r) {
		if (!r.ok) {
			content.innerHTML = lms_portal.forbiddenOrError(
				{ status: r.payload.status, message: r.payload.message },
				"Could not load " + opts.title + "."
			);
			return;
		}
		var rows = (r.payload.message && r.payload.message[opts.listKey]) || [];
		var headerActions = "";
		if (opts.primaryAction) {
			headerActions = '<button type="button" class="lms-btn lms-btn--primary" data-lms-setup-action="' + opts.primaryAction.kind + '">' + lms_portal.escape(opts.primaryAction.label) + '</button>';
		}
		var body = "";
		if (!rows.length) {
			body = '<div class="lms-callout lms-callout--info"><p>' + lms_portal.escape(opts.emptyMessage || "Nothing here yet.") + '</p></div>';
		} else {
			body = lms_setup._renderTable({
				rows: rows,
				columns: opts.columns,
				rowActions: opts.rowActions,
				rowKey: opts.rowKey || "name",
			});
		}
		// Panel header carries the title, an approval-status badge (so the
		// user knows edits need sign-off before they take effect), and
		// the subtitle rendered as a faint paragraph inside the body. Uses
		// the shared .lms-section-header classes so it matches other portals.
		var header = '<div class="lms-section-header">' +
			'<div class="lms-section-header__title"><h3>' + lms_portal.escape(opts.title || "") +
			' <span class="lms-badge lms-badge--watch" title="Changes made here are sent for administrator approval before they take effect">Approval required</span></h3></div>' +
			(headerActions ? '<div class="lms-section-header__controls">' + headerActions + '</div>' : '') +
			'</div>';
		var headerBlock = (opts.subtitle
			? header + '<p class="lms-muted" style="margin: 0 0 1rem 0; font-size: 0.875rem;">' + lms_portal.escape(opts.subtitle) + '</p>'
			: header);
		content.innerHTML = lms_portal.panel({
			body: headerBlock + body,
		});

		if (opts.primaryAction) {
			var btn = content.querySelector("[data-lms-setup-action='" + opts.primaryAction.kind + "']");
			if (btn) btn.addEventListener("click", function () { lms_setup._openTierACreate(content, opts); });
		}
		var actionButtons = content.querySelectorAll("[data-lms-setup-row-action]");
		actionButtons.forEach(function (btn) {
			btn.addEventListener("click", function () {
				var rowName = btn.getAttribute("data-row-name");
				var actionKind = btn.getAttribute("data-lms-setup-row-action");
				var row = rows.find(function (r) { return (r[opts.rowKey || "name"]) === rowName; });
				lms_setup._handleTierARowAction(content, opts, row, actionKind);
			});
		});
	});
};

lms_setup._renderTable = function (cfg) {
	var rows = cfg.rows || [];
	var cols = cfg.columns || [];
	var html = '<div class="lms-table-wrap"><table class="lms-table"><thead><tr>';
	cols.forEach(function (c) { html += '<th>' + lms_portal.escape(c.label || c.key) + '</th>'; });
	if (cfg.rowActions && cfg.rowActions.length) html += '<th class="lms-table-actions-col">Actions</th>';
	html += '</tr></thead><tbody>';
	rows.forEach(function (row) {
		html += '<tr>';
		cols.forEach(function (c) {
			var v = c.render ? c.render(row) : lms_portal.escape(row[c.key] != null ? String(row[c.key]) : "");
			html += '<td>' + v + '</td>';
		});
		if (cfg.rowActions && cfg.rowActions.length) {
			html += '<td class="lms-table-actions"><div class="lms-row-actions">';
			cfg.rowActions.forEach(function (a) {
				html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" data-lms-setup-row-action="' + a.kind + '" data-row-name="' + lms_portal.escape(row[cfg.rowKey || "name"] || "") + '">' + lms_portal.escape(a.label) + '</button>';
			});
			html += '</div></td>';
		}
		html += '</tr>';
	});
	html += '</tbody></table></div>';
	return html;
};

lms_setup._openTierACreate = function (content, opts) {
	lms_setup._openTierAFormModal(opts, null, function () { lms_setup._showTab(lms_setup._currentTab); });
};

lms_setup._handleTierARowAction = function (content, opts, row, actionKind) {
	if (!row) return;
	if (actionKind === "edit") {
		lms_setup._openTierAFormModal(opts, row, function () { lms_setup._showTab(lms_setup._currentTab); });
		return;
	}
	if (actionKind === "disable") {
		lms_setup._confirmAndDisable(opts, row);
		return;
	}
};

lms_setup._openTierAFormModal = function (opts, row, onSuccess) {
	var schema = opts.draftSchema || { fields: [] };
	var isEdit = !!row;
	// opts.singular comes from the tab config so compound plurals like
	// "Credit Policies" render as "Credit Policy" instead of "Credit
	// Policie" (which the old opts.title.slice(0, -1) trick produced).
	var singular = opts.singular || (opts.title || "").replace(/s$/, "");
	var title = isEdit ? "Edit " + singular : "Propose New " + singular;
	var formHtml = '<form class="lms-form" id="lms-setup-form">';
	schema.fields.forEach(function (f) {
		var val = row ? (row[f.key] != null ? row[f.key] : "") : "";
		formHtml += '<div class="lms-form-row"><label class="lms-form-label">' + lms_portal.escape(f.label || f.key) + '</label>';
		if (f.type === "textarea") {
			formHtml += '<textarea name="' + lms_portal.escape(f.key) + '" class="lms-input lms-textarea"' + (f.required ? " required" : "") + '>' + lms_portal.escape(val) + '</textarea>';
		} else if (f.type === "select") {
			formHtml += '<select name="' + lms_portal.escape(f.key) + '" class="lms-input"' + (f.required ? " required" : "") + '>';
			(f.options || []).forEach(function (o) {
				var sel = String(val) === o ? " selected" : "";
				formHtml += '<option value="' + lms_portal.escape(o) + '"' + sel + '>' + lms_portal.escape(o) + '</option>';
			});
			formHtml += '</select>';
		} else {
			formHtml += '<input type="' + lms_portal.escape(f.type || "text") + '" name="' + lms_portal.escape(f.key) + '" class="lms-input" value="' + lms_portal.escape(val) + '"' + (f.required ? " required" : "") + (f.step ? ' step="' + lms_portal.escape(f.step) + '"' : "") + ' />';
		}
		formHtml += '</div>';
	});
	formHtml += '<div class="lms-callout lms-callout--info" style="margin-top: 1rem;"><p style="margin: 0; font-size: 0.85rem;">These details are not applied immediately. Your submission goes to an administrator for approval, and the loan product only changes once they approve it.</p></div>';
	formHtml += '</form>';

	lms_portal.modal({
		title: title,
		size: "lg",
		body: formHtml,
		confirmText: isEdit ? "Submit Edit Request" : "Submit Proposal",
		cancelText: "Cancel",
		onConfirm: function (overlay) {
			var form = overlay.querySelector("#lms-setup-form");
			if (form && !form.checkValidity()) { form.reportValidity(); return false; }
			var fields = {};
			new FormData(form).forEach(function (v, k) { fields[k] = v; });
			var method = isEdit ? "lms_saas.api.setup.edit_loan_product_draft" : "lms_saas.api.setup.create_loan_product_draft";
			var args = isEdit ? { name: row.name, fields: fields } : fields;
			lms_setup._guardedCall({
				method: method,
				args: args,
			}).then(function (r) {
				if (!r.ok) {
					lms_portal.toast(r.payload.message || "Could not submit change request", "error");
					return false;
				}
				lms_portal.toast("Submitted for approval. An administrator will review your changes.", "success");
				setTimeout(function () { if (typeof onSuccess === "function") onSuccess(); }, 200);
				return true;
			});
			return false; // keep modal open until async resolves
		},
	});
};

lms_setup._confirmAndDisable = function (opts, row) {
	var singular = opts.singular || (opts.title || "").replace(/s$/, "");
	lms_portal.modal({
		title: "Disable " + singular,
		size: "sm",
		body: '<p>Disabling <strong>' + lms_portal.escape(row.name) + '</strong> will stop new loans being created with this product. Existing loans are not affected. Your request will be reviewed by an administrator before the product is disabled.</p>',
		confirmText: "Submit Disable Request",
		confirmVariant: "danger",
		onConfirm: function () {
			lms_setup._guardedCall({
				method: "lms_saas.api.setup.disable_loan_product_draft",
				args: { name: row.name },
			}).then(function (r) {
				if (!r.ok) { lms_portal.toast(r.payload.message || "Could not submit disable request", "error"); return false; }
				lms_portal.toast("Disable request submitted for review.", "success");
				setTimeout(function () { lms_setup._showTab(lms_setup._currentTab); }, 200);
				return true;
			});
			return false;
		},
	});
};

// ===========================================================================
// Tier B — direct-write tabs
// ===========================================================================

lms_setup._tierBTabs = {
	loan_purposes: {
		title: "Loan Purposes",
		singular: "Loan Purpose",
		listMethod: "lms_saas.api.setup.list_loan_purposes",
		listKey: "purposes",
		itemKey: "purpose",
		emptyMessage: "No loan purposes defined yet. Add one to start categorising loans on the loan application form.",
		columns: [
			{ key: "name", label: "Purpose" },
		],
		createMethod: "lms_saas.api.setup.create_loan_purpose",
		createFields: [{ key: "name", label: "Purpose Name", type: "text", required: true }],
		editMethod: "lms_saas.api.setup.edit_loan_purpose",
		editFields: [{ key: "new_name", label: "New Purpose Name", type: "text", required: true }],
	},
	centers: {
		title: "Centers",
		singular: "Center",
		listMethod: "lms_saas.api.setup.list_centers",
		listKey: "centers",
		itemKey: "center",
		emptyMessage: "No centers configured yet. Centers group borrowers for branch collection meetings.",
		columns: [
			{ key: "name",         label: "Name" },
			{ key: "center_name",  label: "Display Name" },
			{ key: "branch",       label: "Branch" },
		],
		createMethod: "lms_saas.api.setup.create_center",
		createFields: [{ key: "center_name", label: "Center Name", type: "text", required: true }],
		editMethod: "lms_saas.api.setup.edit_center",
		editFields: [{ key: "center_name", label: "Display Name", type: "text" }],
	},
	lending_groups: {
		title: "Lending Groups",
		singular: "Lending Group",
		listMethod: "lms_saas.api.setup.list_lending_groups",
		listKey: "groups",
		itemKey: "group",
		emptyMessage: "No lending groups yet. Lending groups sit inside Centers and are used for joint-liability microloans.",
		columns: [
			{ key: "name",        label: "Name" },
			{ key: "group_name",  label: "Display Name" },
			{ key: "center",      label: "Center" },
			{ key: "branch",      label: "Branch" },
			{ key: "status",      label: "Status" },
		],
		createMethod: "lms_saas.api.setup.create_lending_group",
		createFields: [{ key: "group_name", label: "Group Name", type: "text", required: true }],
		editMethod: "lms_saas.api.setup.edit_lending_group",
		editFields: [{ key: "group_name", label: "Display Name", type: "text" }],
	},
	announcements: {
		title: "Announcements",
		singular: "Announcement",
		listMethod: "lms_saas.api.setup.list_announcements",
		listKey: "announcements",
		itemKey: "announcement",
		emptyMessage: "No announcements configured. Use this tab to broadcast policy changes or downtime notices to staff portals.",
		columns: [
			{ key: "name",      label: "Title" },
			{ key: "audience",  label: "Audience" },
			{ key: "status",    label: "Status" },
		],
		createMethod: "lms_saas.api.setup.create_announcement",
		createFields: [
			{ key: "title",    label: "Title",    type: "text",   required: true },
			{ key: "message",  label: "Message",  type: "textarea" },
			{ key: "audience", label: "Audience", type: "select", options: ["All Staff", "Loan Officers", "Branch Managers", "Operations Managers"] },
		],
	},
	document_categories: {
		title: "Document Categories",
		singular: "Document Category",
		listMethod: "lms_saas.api.setup.list_document_categories",
		listKey: "categories",
		itemKey: "category",
		emptyMessage: "No document categories configured. Categories drive which KYC documents are requested on new loan applications.",
		columns: [
			{ key: "name",          label: "Name" },
			{ key: "category_name", label: "Display Name" },
			{ key: "required",      label: "Required" },
		],
		createMethod: "lms_saas.api.setup.create_document_category",
		createFields: [{ key: "category_name", label: "Category Name", type: "text", required: true }],
		editMethod: "lms_saas.api.setup.edit_document_category",
		editFields: [{ key: "category_name", label: "Display Name", type: "text" }],
	},
	payment_providers: {
		title: "Payment Providers",
		singular: "Payment Provider",
		listMethod: "lms_saas.api.setup.list_payment_providers",
		listKey: "providers",
		itemKey: "provider",
		emptyMessage: "No payment providers configured. Enable a provider to start accepting mobile-money or card repayments.",
		columns: [
			{ key: "name",     label: "Provider" },
			{ key: "provider_name", label: "Display Name" },
			{ key: "enabled",  label: "Status", render: function (r) { return r.enabled ? '<span class="lms-badge lms-badge--current">Enabled</span>' : '<span class="lms-badge lms-badge--default">Disabled</span>'; } },
		],
		toggleMethod: "lms_saas.api.setup.toggle_payment_provider",
	},
};

Object.keys(lms_setup._tierBTabs).forEach(function (tabId) {
	lms_setup._tabHandlers[tabId] = function (content) {
		lms_setup._loadTierBList(content, tabId);
	};
});

lms_setup._loadTierBList = function (content, tabId) {
	var cfg = lms_setup._tierBTabs[tabId];
	lms_setup._guardedCall({ method: cfg.listMethod }).then(function (r) {
		if (!r.ok) {
			content.innerHTML = lms_portal.forbiddenOrError(
				{ status: r.payload.status, message: r.payload.message },
				"Could not load " + cfg.title + "."
			);
			return;
		}
		var rows = (r.payload.message && r.payload.message[cfg.listKey]) || [];
		var body = rows.length
			? lms_setup._renderTable({ rows: rows, columns: cfg.columns, rowKey: "name", rowActions: lms_setup._tierBRowActions(tabId) })
			: '<div class="lms-callout lms-callout--info"><p>' + lms_portal.escape(cfg.emptyMessage) + '</p></div>';
		// Panel: title + badge so the user knows these records save
		// instantly. Identical layout to the approval-required header.
		var header = '<div class="lms-section-header">' +
			'<div class="lms-section-header__title"><h3>' + lms_portal.escape(cfg.title) +
			' <span class="lms-badge lms-badge--current" title="Changes made here take effect immediately">Applies instantly</span></h3></div>' +
			'<div class="lms-section-header__controls"><button type="button" class="lms-btn lms-btn--primary" data-lms-setup-tierb-add>Add New</button></div>' +
			'</div>';
		content.innerHTML = lms_portal.panel({
			body: header + body,
		});
		var addBtn = content.querySelector("[data-lms-setup-tierb-add]");
		if (addBtn) addBtn.addEventListener("click", function () { lms_setup._openTierBCreate(content, tabId); });

		content.querySelectorAll("[data-lms-setup-row-action]").forEach(function (btn) {
			btn.addEventListener("click", function () {
				var rowName = btn.getAttribute("data-row-name");
				var actionKind = btn.getAttribute("data-lms-setup-row-action");
				var row = rows.find(function (r) { return r.name === rowName; });
				if (actionKind === "edit") lms_setup._openTierBEdit(content, tabId, row);
				if (actionKind === "toggle") lms_setup._toggleTierB(content, tabId, row);
			});
		});
	});
};

lms_setup._tierBRowActions = function (tabId) {
	var cfg = lms_setup._tierBTabs[tabId];
	var actions = [];
	if (cfg.editMethod) actions.push({ label: "Edit", kind: "edit" });
	if (cfg.toggleMethod) actions.push({ label: "Toggle", kind: "toggle" });
	return actions;
};

lms_setup._openTierBCreate = function (content, tabId) {
	var cfg = lms_setup._tierBTabs[tabId];
	var singular = cfg.singular || (cfg.title || "").replace(/s$/, "");
	lms_setup._openTierBFormModal("Add " + singular, cfg.createFields, function (values) {
		lms_setup._guardedCall({ method: cfg.createMethod, args: values }).then(function (r) {
			if (!r.ok) { lms_portal.toast(r.payload.message || "Could not create " + singular.toLowerCase(), "error"); return false; }
			lms_portal.toast(singular + " created.", "success");
			setTimeout(function () { lms_setup._showTab(lms_setup._currentTab); }, 200);
			return true;
		});
		return false;
	});
};

lms_setup._openTierBEdit = function (content, tabId, row) {
	var cfg = lms_setup._tierBTabs[tabId];
	if (!cfg.editMethod || !row) return;
	var singular = cfg.singular || (cfg.title || "").replace(/s$/, "");
	lms_setup._openTierBFormModal("Edit " + singular, cfg.editFields, function (values) {
		var args = Object.assign({ name: row.name }, values);
		lms_setup._guardedCall({ method: cfg.editMethod, args: args }).then(function (r) {
			if (!r.ok) { lms_portal.toast(r.payload.message || "Could not update " + singular.toLowerCase(), "error"); return false; }
			lms_portal.toast(singular + " updated.", "success");
			setTimeout(function () { lms_setup._showTab(lms_setup._currentTab); }, 200);
			return true;
		});
		return false;
	});
};

lms_setup._toggleTierB = function (content, tabId, row) {
	var cfg = lms_setup._tierBTabs[tabId];
	var next = !row.enabled;
	lms_setup._guardedCall({ method: cfg.toggleMethod, args: { name: row.name, enabled: next ? 1 : 0 } }).then(function (r) {
		if (!r.ok) { lms_portal.toast(r.payload.message || "Could not toggle provider", "error"); return; }
		lms_portal.toast(next ? "Provider enabled." : "Provider disabled.", "success");
		setTimeout(function () { lms_setup._showTab(lms_setup._currentTab); }, 200);
	});
};

lms_setup._openTierBFormModal = function (title, fields, onSubmit) {
	var html = '<form class="lms-form" id="lms-setup-tierb-form">';
	(fields || []).forEach(function (f) {
		html += '<div class="lms-form-row"><label class="lms-form-label">' + lms_portal.escape(f.label || f.key) + '</label>';
		if (f.type === "textarea") {
			html += '<textarea name="' + lms_portal.escape(f.key) + '" class="lms-input lms-textarea"' + (f.required ? " required" : "") + '></textarea>';
		} else if (f.type === "select") {
			html += '<select name="' + lms_portal.escape(f.key) + '" class="lms-input"' + (f.required ? " required" : "") + '>';
			(f.options || []).forEach(function (o) { html += '<option value="' + lms_portal.escape(o) + '">' + lms_portal.escape(o) + '</option>'; });
			html += '</select>';
		} else {
			html += '<input type="' + lms_portal.escape(f.type || "text") + '" name="' + lms_portal.escape(f.key) + '" class="lms-input"' + (f.required ? " required" : "") + ' />';
		}
		html += '</div>';
	});
	html += '</form>';
	lms_portal.modal({
		title: title,
		size: "sm",
		body: html,
		confirmText: "Save",
		onConfirm: function (overlay) {
			var form = overlay.querySelector("#lms-setup-tierb-form");
			if (form && !form.checkValidity()) { form.reportValidity(); return false; }
			var values = {};
			new FormData(form).forEach(function (v, k) { values[k] = v; });
			return onSubmit(values);
		},
	});
};

// ===========================================================================
// Tier A — Change Requests queue
// ===========================================================================

lms_setup._tabHandlers.change_requests = function (content) {
	lms_setup._guardedCall({ method: "lms_saas.api.setup.list_change_requests", args: {} }).then(function (r) {
		if (!r.ok) {
			content.innerHTML = lms_portal.forbiddenOrError(
				{ status: r.payload.status, message: r.payload.message },
				"Could not load change requests."
			);
			return;
		}
		var rows = (r.payload.message && r.payload.message.change_requests) || [];
		var body = rows.length
			? lms_setup._renderChangeRequestTable(rows)
			: lms_setup._changeRequestsEmpty();
		content.innerHTML = lms_portal.panel({
			title: "Change Requests",
			controls: '<span class="lms-muted" style="font-size: 0.85rem;">Changes waiting for an administrator to review.</span>',
			body: body,
		});
	});
};

lms_setup._changeRequestsEmpty = function () {
	return '<div class="lms-callout lms-callout--info"><p>No change requests yet. To propose a change, open the <strong>Loan Products</strong> tab and use <strong>Propose New Product</strong> or <strong>Edit</strong>.</p></div>';
};

lms_setup._renderChangeRequestTable = function (rows) {
	var html = '<div class="lms-table-wrap"><table class="lms-table"><thead><tr>' +
		'<th>Request</th><th>Target</th><th>Type</th><th>Status</th><th>Proposed By</th><th>Created</th>' +
		'</tr></thead><tbody>';
	rows.forEach(function (cr) {
		var statusBadge = lms_setup._statusBadge(cr);
		// Compose Target cell as "Loan Product · LMS-STD" so the parent
		// doctype reads as a label, not just smashed next to the name.
		var targetLabel = cr.target_doctype || "";
		var targetName = cr.target_name || "—";
		var targetCell = targetName
			? (targetLabel
				? '<span class="lms-muted">' + lms_portal.escape(targetLabel) + '</span> &middot; <strong>' + lms_portal.escape(targetName) + '</strong>'
				: '<strong>' + lms_portal.escape(targetName) + '</strong>')
			: '<span class="lms-muted">—</span>';
		html += '<tr>' +
			'<td>' + lms_portal.escape(cr.name || "") + '</td>' +
			'<td>' + targetCell + '</td>' +
			'<td>' + lms_portal.escape(cr.change_type || "") + '</td>' +
			'<td>' + statusBadge + '</td>' +
			'<td>' + lms_portal.escape(cr.requested_by || "") + '</td>' +
			'<td>' + lms_portal.formatDate(cr.requested_at) + '</td>' +
			'</tr>';
	});
	html += '</tbody></table></div>';
	html += '<p class="lms-muted" style="margin-top: 1rem; font-size: 0.85rem;">Requests are approved or rejected by an administrator (Admin Console &rarr; Setup Change Requests). Requests marked <strong>Missing account details</strong> include notes explaining what must be set up first.</p>';
	return html;
};

lms_setup._statusBadge = function (cr) {
	// Badge text is shortened so the pill stays readable. The full
	// status is preserved in the title attribute for hover detail.
	// "Missing GL Accounts" (server-side status) is shown to users as
	// "Missing account details" — plain language, no ledger jargon.
	var status = cr && cr.status ? cr.status : "";
	var short = status;
	var title = "";
	if (status === "Pending") { short = "Pending review"; }
	else if (status === "Pending — Missing GL Accounts") {
		short = "Missing account details";
		title = "Pending — Missing GL Accounts (needs ledger setup by an administrator first)";
	}
	else if (status === "Approved") { short = "Approved"; title = "Approved"; }
	else if (status === "Applied") { short = "Applied"; title = "Approved and applied to the live record"; }
	else if (status === "Rejected") { short = "Rejected"; }
	else if (status === "Cancelled") { short = "Cancelled"; }
	var cls = "lms-badge--default";
	if (status === "Pending") cls = "lms-badge--watch";
	else if (status === "Approved" || status === "Applied") cls = "lms-badge--current";
	else if (status === "Pending — Missing GL Accounts") cls = "lms-badge--npa";
	else if (status === "Rejected" || status === "Cancelled") cls = "lms-badge--npa";
	var titleAttr = title ? ' title="' + lms_portal.escape(title) + '"' : ' title="' + lms_portal.escape(status) + '"';
	return '<span class="lms-badge ' + cls + '"' + titleAttr + '>' + lms_portal.escape(short) + '</span>';
};