/* LMS Wallet Reconciliation portal — dashboard, import, unmatched, matched */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_recon");
} else {
	window.lms_recon = window.lms_recon || {};
}

lms_recon._currentTab = "dashboard";

lms_recon.init = function () {
	var root = document.getElementById("lms-recon-root");
	if (!root) return;

	var tabs = [
		{ id: "dashboard", label: "Dashboard", icon: "📊" },
		{ id: "import", label: "Import", icon: "📥" },
		{ id: "unmatched", label: "Unmatched", icon: "⚠️" },
		{ id: "matched", label: "Matched", icon: "✓" },
	];
	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "Wallet Reconciliation" }) +
		lms_portal.tabNav(tabs, lms_recon._currentTab) +
		'<div id="lms-recon-tab-content"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_portal.bindTabs({
		root: root,
		tabs: tabs,
		onTab: function (tabId) { lms_recon._currentTab = tabId; lms_recon._showTab(tabId); },
	});

	lms_recon._showTab(lms_recon._currentTab);
};

lms_recon._showTab = function (tabId) {
	var content = document.getElementById("lms-recon-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "dashboard") lms_recon._loadDashboard(content);
	else if (tabId === "import") lms_recon._loadImport(content);
	else if (tabId === "unmatched") lms_recon._loadUnmatched(content);
	else if (tabId === "matched") lms_recon._loadMatched(content);
};

lms_recon._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_recon._loadDashboard = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.wallet_recon.get_recon_dashboard",
		callback: function (r) {
			var d = (r && r.message) || {};
			var html = '<section class="lms-grid-4 lms-recon-kpis">';
			html += lms_recon._statCard("Total Statements", d.total || 0);
			html += lms_recon._statCard("Matched", d.matched || 0, "success");
			html += lms_recon._statCard("Unmatched", d.unmatched || 0, "danger");
			html += lms_recon._statCard("Ignored", d.ignored || 0, "warning");
			html += "</section>";
			html += '<section class="lms-grid-4">';
			html += lms_recon._statCard("Matched Value", format_currency(d.matched_value || 0));
			html += lms_recon._statCard("Unmatched Value", format_currency(d.unmatched_value || 0), "danger");
			html += "</section>";

			// Auto-match button
			html += '<div class="lms-recon-actions"><button type="button" class="lms-btn lms-btn--primary" id="lms-recon-auto-match">Run Auto-Match</button></div>';
			content.innerHTML = html;

			var autoMatchBtn = content.querySelector("#lms-recon-auto-match");
			if (autoMatchBtn) {
				autoMatchBtn.addEventListener("click", function () {
					autoMatchBtn.disabled = true;
					autoMatchBtn.textContent = "Matching…";
					lms_portal.safeCall({
						method: "lms_saas.api.wallet_recon.auto_match",
						callback: function (r) {
							var res = (r && r.message) || {};
							lms_portal.toast("Matched " + (res.matched || 0) + " statements, " + (res.remaining || 0) + " remaining.", "success");
							lms_recon._showTab("dashboard");
						},
						error: function () {
							autoMatchBtn.disabled = false;
							autoMatchBtn.textContent = "Run Auto-Match";
							lms_portal.toast("Auto-match failed.", "danger");
						},
					});
				});
			}
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load dashboard.");
		},
	});
};

lms_recon._loadImport = function (content) {
	var html = '<div class="lms-panel" style="max-width:700px;">';
	html += '<h3 style="margin:0 0 1rem;">Import Wallet Statement</h3>';
	html += '<p class="lms-muted" style="margin:0 0 1rem;">Paste statement lines as JSON array. Each line should have: provider_code, statement_date, external_ref, amount.</p>';
	html += '<div class="lms-form">';
	html += '<div class="lms-field"><label>Company (optional)</label>';
	html += '<input type="text" id="lms-recon-company" class="lms-input" placeholder="Company name"></div>';
	html += '<div class="lms-field"><label>Statement Lines (JSON)</label>';
	html += '<textarea id="lms-reon-lines" class="lms-input" rows="10" placeholder=\'[\n  {"provider_code": "ECOCASH", "statement_date": "2026-01-15", "external_ref": "TXN001", "amount": 150.00},\n  {"provider_code": "ECOCASH", "statement_date": "2026-01-15", "external_ref": "TXN002", "amount": 300.00}\n]\'></textarea></div>';
	html += '<button type="button" class="lms-btn lms-btn--primary" id="lms-recon-import-btn">Import & Auto-Match</button>';
	html += '</div></div>';
	content.innerHTML = html;

	var importBtn = content.querySelector("#lms-recon-import-btn");
	if (importBtn) {
		importBtn.addEventListener("click", function () {
			var lines = content.querySelector("#lms-reon-lines").value;
			var company = content.querySelector("#lms-recon-company").value;

			if (!lines) {
				lms_portal.toast("Please paste statement lines.", "danger");
				return;
			}

			importBtn.disabled = true;
			importBtn.textContent = "Importing…";

			lms_portal.safeCall({
				method: "lms_saas.api.wallet_recon.import_wallet_statement",
				args: { lines: lines, company: company || "" },
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Imported " + (res.imported || 0) + " lines, auto-matched " + (res.auto_matched || 0) + ".", "success");
					importBtn.disabled = false;
					importBtn.textContent = "Import & Auto-Match";
					content.querySelector("#lms-reon-lines").value = "";
				},
				error: function () {
					lms_portal.toast("Import failed.", "danger");
					importBtn.disabled = false;
					importBtn.textContent = "Import & Auto-Match";
				},
			});
		});
	}
};

lms_recon._loadUnmatched = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.wallet_recon.get_unmatched",
		callback: function (r) {
			var statements = (r && r.message && r.message.statements) || [];
			if (!statements.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("✓") + '<h3>All matched</h3><p>No unmatched transactions.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Statement</th><th>Provider</th><th>Date</th><th>Ext Ref</th><th>Amount</th><th>Suggestions</th><th>Action</th></tr></thead><tbody>";
			statements.forEach(function (s) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(s.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(s.provider_code || "—") + "</td>";
				html += "<td>" + lms_portal.formatDate(s.statement_date) + "</td>";
				html += "<td>" + lms_portal.escape(s.external_ref || "—") + "</td>";
				html += "<td>" + format_currency(s.amount || 0) + "</td>";
				// Suggestions dropdown
				var suggestions = s.suggestions || [];
				html += '<td><select class="lms-input lms-fallback-select lms-recon-suggest" data-statement="' + lms_portal.escape(s.name) + '" style="width:auto;">';
				html += '<option value="">— Select match —</option>';
				suggestions.forEach(function (sg) {
					html += '<option value="' + lms_portal.escape(sg.name) + '">' + lms_portal.escape(sg.name) + ' · ' + lms_portal.escape(sg.loan || "") + ' · ' + lms_portal.escape(sg.customer || "") + '</option>';
				});
				html += '</select></td>';
				html += '<td><button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-recon-match-btn" data-statement="' + lms_portal.escape(s.name) + '">Match</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-recon-match-btn").forEach(function (btn) {
				btn.addEventListener("click", function () {
					var statementName = btn.getAttribute("data-statement");
					var select = content.querySelector('.lms-recon-suggest[data-statement="' + statementName + '"]');
					if (!select || !select.value) {
						lms_portal.toast("Select a payment intent to match.", "warning");
						return;
					}
					lms_recon._matchTransaction(statementName, select.value);
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load unmatched transactions.");
		},
	});
};

lms_recon._matchTransaction = function (statementName, paymentIntent) {
	lms_portal.safeCall({
		method: "lms_saas.api.wallet_recon.match_transaction",
		args: { statement_name: statementName, payment_intent: paymentIntent },
		callback: function (r) {
			var res = (r && r.message) || {};
			if (res.ok) {
				lms_portal.toast("Transaction matched.", "success");
				lms_recon._showTab("unmatched");
			} else {
				lms_portal.toast("Match failed.", "danger");
			}
		},
		error: function () {
			lms_portal.toast("Could not match transaction.", "danger");
		},
	});
};

lms_recon._loadMatched = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.wallet_recon.get_recon_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = '<section class="lms-grid-4 lms-recon-kpis">';
			html += lms_recon._statCard("Total Statements", s.total_statements || 0);
			html += lms_recon._statCard("Matched", s.matched || 0, "success");
			html += lms_recon._statCard("Match Rate", (s.match_rate || 0) + "%");
			html += lms_recon._statCard("Total Value", format_currency(s.total_value || 0));
			html += "</section>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load stats.");
		},
	});
};