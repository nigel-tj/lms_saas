/* LMS Savings Club portal — my savings, goals, transactions */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_savings");
} else {
	window.lms_savings = window.lms_savings || {};
}

lms_savings._currentTab = "accounts";

lms_savings.init = function () {
	var root = document.getElementById("lms-savings-root");
	if (!root) return;

	var tabs = [
		{ id: "accounts", label: "My Savings", icon: "🏦" },
		{ id: "goals", label: "Goals", icon: "🎯" },
		{ id: "transactions", label: "Transactions", icon: "📋" },
	];
	var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;">';
	html += '<h2 style="margin:0;font-size:var(--lms-fs-xl);font-weight:700;">Savings Club</h2>';
	html += '<div style="display:flex;gap:0.5rem;">';
	html += '<button type="button" class="lms-btn lms-btn--primary" id="lms-sav-deposit">+ Deposit</button>';
	html += '<button type="button" class="lms-btn lms-btn--ghost" id="lms-sav-withdraw">Withdraw</button>';
	html += '</div></div>';
	html += '<div id="lms-sav-stats" style="margin-bottom:1rem;"></div>';
	html += '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_savings._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	html += '<div id="lms-savings-tab-content"></div>';
	root.innerHTML = html;

	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_savings._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.style.borderBottom = "2px solid var(--lms-primary)";
			btn.style.color = "var(--lms-primary)";
			btn.style.fontWeight = "600";
			lms_savings._showTab(lms_savings._currentTab);
		});
	});

	lms_savings._loadStats();

	var depositBtn = root.querySelector("#lms-sav-deposit");
	if (depositBtn) {
		depositBtn.addEventListener("click", function () {
			lms_savings._showDepositModal();
		});
	}
	var withdrawBtn = root.querySelector("#lms-sav-withdraw");
	if (withdrawBtn) {
		withdrawBtn.addEventListener("click", function () {
			lms_savings._showWithdrawModal();
		});
	}

	lms_savings._showTab(lms_savings._currentTab);
};

lms_savings._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_savings._loadStats = function () {
	var el = document.getElementById("lms-sav-stats");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.savings_club.get_savings_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = '<section class="lms-grid-4">';
			html += lms_savings._statCard("Total Saved", format_currency(s.total_saved || 0), "success");
			html += lms_savings._statCard("Active Accounts", s.active_accounts || 0);
			html += lms_savings._statCard("Active Goals", s.goals || 0, "info");
			html += "</section>";
			el.innerHTML = html;
		},
	});
};

lms_savings._showTab = function (tabId) {
	var content = document.getElementById("lms-savings-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "accounts") lms_savings._loadAccounts(content);
	else if (tabId === "goals") lms_savings._loadGoals(content);
	else if (tabId === "transactions") lms_savings._loadTransactions(content);
};

// ── Accounts ──

lms_savings._loadAccounts = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.savings_club.get_savings_accounts",
		callback: function (r) {
			var accounts = (r && r.message && r.message.accounts) || [];
			if (!accounts.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">🏦</div><h3>No savings accounts</h3><p>You have no savings accounts yet.</p></div></div>';
				return;
			}

			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Account</th><th>Customer</th><th>Group</th><th>Balance</th><th>Status</th><th>Action</th></tr></thead><tbody>";
			accounts.forEach(function (a) {
				var statusCls = a.status === "Active" ? "lms-badge--success" : "";
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(a.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(a.customer_name || "") + "</td>";
				html += "<td>" + lms_portal.escape(a.group_name || "—") + "</td>";
				html += "<td>" + format_currency(a.balance || 0) + "</td>";
				html += '<td><span class="lms-badge ' + statusCls + '">' + lms_portal.escape(a.status) + "</span></td>";
				html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-sav-view" data-name="' + lms_portal.escape(a.name) + '">View</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-sav-view").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_savings._showAccountDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load savings accounts.");
		},
	});
};

lms_savings._showAccountDetail = function (accountName) {
	lms_portal.safeCall({
		method: "lms_saas.api.savings_club.get_savings_detail",
		args: { account_name: accountName },
		callback: function (r) {
			var data = (r && r.message) || {};
			var acc = data.account || {};
			var txns = data.transactions || [];

			var html = '<div class="lms-form">';
			html += '<div class="lms-field"><label>Account</label><div>' + lms_portal.escape(acc.name || "") + '</div></div>';
			html += '<div class="lms-field"><label>Customer</label><div>' + lms_portal.escape(acc.customer_name || "") + '</div></div>';
			html += '<div class="lms-field"><label>Group</label><div>' + lms_portal.escape(acc.group_name || "—") + '</div></div>';
			html += '<div class="lms-field"><label>Balance</label><div>' + format_currency(acc.balance || 0) + '</div></div>';
			html += '<div class="lms-field"><label>Status</label><div>' + lms_portal.escape(acc.status || "") + '</div></div>';
			html += '<h4 style="margin-top:1.5rem;">Transactions</h4>';
			if (!txns.length) {
				html += '<p class="lms-muted">No transactions yet.</p>';
			} else {
				html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
				html += "<thead><tr><th>Type</th><th>Amount</th><th>Date</th></tr></thead><tbody>";
				txns.forEach(function (t) {
					var cls = t.transaction_type === "Deposit" ? "lms-badge--success" : "lms-badge--warning";
					html += "<tr>";
					html += '<td><span class="lms-badge ' + cls + '">' + lms_portal.escape(t.transaction_type) + "</span></td>";
					html += "<td>" + format_currency(t.amount || 0) + "</td>";
					html += "<td>" + lms_portal.formatDate(t.posting_date) + "</td>";
					html += "</tr>";
				});
				html += "</tbody></table></div>";
			}
			html += '</div>';

			lms_portal.modal({
				title: "Savings Account Detail",
				body: html,
				size: "lg",
				confirmText: "Close",
				confirmVariant: "primary",
			});
		},
		error: function () {
			lms_portal.toast("Could not load account detail.", "danger");
		},
	});
};

// ── Goals ──

lms_savings._loadGoals = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.savings_club.get_savings_goals",
		callback: function (r) {
			var goals = (r && r.message && r.message.goals) || [];
			if (!goals.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">🎯</div><h3>No savings goals</h3><p>No savings goals set yet.</p></div></div>';
				return;
			}

			var html = "";
			goals.forEach(function (g) {
				var progress = g.progress || 0;
				var progressCls = progress >= 100 ? "lms-badge--success" : (progress >= 50 ? "lms-badge--info" : "lms-badge--warning");
				var statusCls = g.status === "Achieved" ? "lms-badge--success" : (g.status === "Expired" ? "lms-badge--danger" : "lms-badge--info");
				html += '<div class="lms-panel" style="margin-bottom:1rem;padding:1rem;">';
				html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
				html += '<div><strong>' + lms_portal.escape(g.group_name || g.lending_group) + '</strong>';
				html += ' <span class="lms-badge ' + statusCls + '">' + lms_portal.escape(g.status) + '</span></div>';
				html += '<div class="lms-muted">Target: ' + format_currency(g.target_amount || 0) + '</div>';
				html += '</div>';
				html += '<div style="margin-top:0.75rem;">';
				html += '<div style="display:flex;justify-content:space-between;font-size:var(--lms-fs-sm);margin-bottom:0.25rem;">';
				html += '<span>Current: ' + format_currency(g.current_balance || 0) + '</span>';
				html += '<span class="lms-badge ' + progressCls + '">' + progress.toFixed(1) + '%</span>';
				html += '</div>';
				html += '<div style="background:var(--lms-surface-2);border-radius:var(--lms-radius);height:8px;overflow:hidden;">';
				html += '<div style="background:var(--lms-primary);height:100%;width:' + Math.min(progress, 100) + '%;border-radius:var(--lms-radius);"></div>';
				html += '</div>';
				if (g.target_date) {
					html += '<div class="lms-muted" style="margin-top:0.5rem;font-size:var(--lms-fs-sm);">Target date: ' + lms_portal.formatDate(g.target_date) + '</div>';
				}
				html += '</div>';
				html += '</div>';
			});
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load savings goals.");
		},
	});
};

// ── Transactions ──

lms_savings._loadTransactions = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.savings_club.get_savings_accounts",
		callback: function (r) {
			var accounts = (r && r.message && r.message.accounts) || [];
			if (!accounts.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📋</div><h3>No accounts</h3><p>No savings accounts to show transactions for.</p></div></div>';
				return;
			}

			// Load detail for first account
			lms_portal.safeCall({
				method: "lms_saas.api.savings_club.get_savings_detail",
				args: { account_name: accounts[0].name },
				callback: function (r2) {
					var data = (r2 && r.message) || {};
					var txns = (r2 && r2.message && r2.message.transactions) || [];
					if (!txns.length) {
						content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📋</div><h3>No transactions</h3><p>No transactions yet.</p></div></div>';
						return;
					}

					var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
					html += "<thead><tr><th>Account</th><th>Type</th><th>Amount</th><th>Date</th></tr></thead><tbody>";
					txns.forEach(function (t) {
						var cls = t.transaction_type === "Deposit" ? "lms-badge--success" : "lms-badge--warning";
						html += "<tr>";
						html += "<td>" + lms_portal.escape(t.savings_account || accounts[0].name) + "</td>";
						html += '<td><span class="lms-badge ' + cls + '">' + lms_portal.escape(t.transaction_type) + "</span></td>";
						html += "<td>" + format_currency(t.amount || 0) + "</td>";
						html += "<td>" + lms_portal.formatDate(t.posting_date) + "</td>";
						html += "</tr>";
					});
					html += "</tbody></table></div></div>";
					content.innerHTML = html;
				},
				error: function () {
					content.innerHTML = lms_portal.error("Could not load transactions.");
				},
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load accounts.");
		},
	});
};

// ── Deposit Modal ──

lms_savings._showDepositModal = function () {
	lms_portal.safeCall({
		method: "lms_saas.api.savings_club.get_savings_accounts",
		callback: function (r) {
			var accounts = (r && r.message && r.message.accounts) || [];
			if (!accounts.length) {
				lms_portal.toast("No savings accounts available.", "warning");
				return;
			}

			var html = '<div class="lms-form">';
			html += '<div class="lms-field"><label>Savings Account</label>';
			html += '<select id="lms-sav-dep-account" class="lms-input lms-fallback-select">';
			accounts.forEach(function (a) {
				html += '<option value="' + lms_portal.escape(a.name) + '">' + lms_portal.escape(a.name) + ' — ' + format_currency(a.balance || 0) + '</option>';
			});
			html += '</select></div>';
			html += '<div class="lms-field"><label>Amount</label>';
			html += '<input type="number" id="lms-sav-dep-amount" class="lms-input" placeholder="0.00" step="0.01" min="0"></div>';
			html += '<div class="lms-field"><label>Posting Date</label>';
			html += '<input type="date" id="lms-sav-dep-date" class="lms-input"></div>';
			html += '</div>';

			var m = lms_portal.modal({
				title: "Make a Deposit",
				body: html,
				confirmText: "Deposit",
				confirmVariant: "success",
				onConfirm: function (overlay) {
					var accountName = overlay.querySelector("#lms-sav-dep-account").value;
					var amount = overlay.querySelector("#lms-sav-dep-amount").value;
					var postingDate = overlay.querySelector("#lms-sav-dep-date").value;

					if (!amount || parseFloat(amount) <= 0) {
						lms_portal.toast("Please enter a valid amount.", "danger");
						return false;
					}

					lms_portal.safeCall({
						method: "lms_saas.api.savings_club.make_deposit",
						args: {
							account_name: accountName,
							amount: amount,
							posting_date: postingDate || undefined,
						},
						callback: function (r) {
							var newBalance = (r && r.message && r.message.new_balance) || 0;
							lms_portal.toast("Deposit successful. New balance: " + format_currency(newBalance), "success");
							lms_savings._loadStats();
							lms_savings._showTab(lms_savings._currentTab);
						},
						error: function () {
							lms_portal.toast("Deposit failed.", "danger");
						},
					});
				},
			});
		},
	});
};

// ── Withdraw Modal ──

lms_savings._showWithdrawModal = function () {
	lms_portal.safeCall({
		method: "lms_saas.api.savings_club.get_savings_accounts",
		callback: function (r) {
			var accounts = (r && r.message && r.message.accounts) || [];
			if (!accounts.length) {
				lms_portal.toast("No savings accounts available.", "warning");
				return;
			}

			var html = '<div class="lms-form">';
			html += '<div class="lms-field"><label>Savings Account</label>';
			html += '<select id="lms-sav-wd-account" class="lms-input lms-fallback-select">';
			accounts.forEach(function (a) {
				html += '<option value="' + lms_portal.escape(a.name) + '">' + lms_portal.escape(a.name) + ' — ' + format_currency(a.balance || 0) + '</option>';
			});
			html += '</select></div>';
			html += '<div class="lms-field"><label>Amount</label>';
			html += '<input type="number" id="lms-sav-wd-amount" class="lms-input" placeholder="0.00" step="0.01" min="0"></div>';
			html += '<div class="lms-field"><label>Notes</label>';
			html += '<textarea id="lms-sav-wd-notes" class="lms-input" rows="3" placeholder="Reason for withdrawal…"></textarea></div>';
			html += '</div>';

			lms_portal.modal({
				title: "Request Withdrawal",
				body: html,
				confirmText: "Submit Request",
				confirmVariant: "warning",
				onConfirm: function (overlay) {
					var accountName = overlay.querySelector("#lms-sav-wd-account").value;
					var amount = overlay.querySelector("#lms-sav-wd-amount").value;
					var notes = overlay.querySelector("#lms-sav-wd-notes").value;

					if (!amount || parseFloat(amount) <= 0) {
						lms_portal.toast("Please enter a valid amount.", "danger");
						return false;
					}

					lms_portal.safeCall({
						method: "lms_saas.api.savings_club.request_withdrawal",
						args: {
							account_name: accountName,
							amount: amount,
							notes: notes || undefined,
						},
						callback: function (r) {
							lms_portal.toast((r && r.message && r.message.message) || "Withdrawal request submitted.", "success");
							lms_savings._showTab(lms_savings._currentTab);
						},
						error: function () {
							lms_portal.toast("Withdrawal request failed.", "danger");
						},
					});
				},
			});
		},
	});
};