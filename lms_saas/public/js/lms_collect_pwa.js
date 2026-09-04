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
	// R59: restore the last active tab (Run sheet | My collections) so a
	// refresh lands where the collector left off — same behaviour as the
	// officer/manager/setup portals.
	lms_collect._currentTab = lms_portal.persistedTab("collect", lms_collect._currentTab);
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
			// R58: per-bucket KPI totals come from the server (#80), derived
			// from the same scoped rows the page renders — the strip and the
			// lists cannot disagree (R35-#27).
			var kpis = (r.message && r.message.kpis) || null;
			// R59: what this collector banked today — feeds the new
			// "Collected today" lead KPI card.
			var collectedToday = (r.message && r.message.collected_today) || null;
			lms_collect._renderRunSheet(root, rows, kpis, collectedToday);
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

/* R58: shared row builder for both bucket lists. One function means
 * Collect / Call / Promise / Reveal / pending-sync behave identically on
 * an overdue row and an upcoming row. Overdue rows get a red-tinted
 * "Overdue" eyebrow instead of the plain "Due" label. */
lms_collect._runSheetRowHtml = function (row, queued, isOverdue) {
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
		? '<span class="lms-badge lms-badge--warning" title="Queued on this device — tap Sync">Pending sync</span>'
		: '<span class="lms-badge lms-badge--success" title="No offline queue for this stop">Synced</span>';
	var dueLabel = isOverdue ? "Overdue" : "Due";
	var dueTone = isOverdue ? ' style="color:#b3261e;"' : "";
	return (
		'<li class="lms-queue-list__item' + (pending ? " is-pending-sync" : "") + (isOverdue ? " is-overdue" : "") + '">' +
		'<div class="lms-queue-list__main">' +
		'<div class="lms-queue-list__head">' +
		'<span class="lms-queue-list__name">' + lms_portal.escape(row.borrower) + '</span>' +
		syncBadge +
		'</div>' +
		'<div class="lms-queue-list__sub">' +
		'<span' + dueTone + '>' + lms_portal.escape(dueLabel + " " + lms_portal.formatDate(row.due_date)) + '</span>' +
		'</div>' +
		'<div class="lms-pii-mobile" data-loan="' + lms_portal.escape(row.loan) + '" style="margin-top:0.15rem;font-size:0.8rem;">' +
		(mobile ? (masked ? '<span class="lms-pii-masked">' + lms_portal.escape(mobile) + '</span> ' + revealBtn : '<span>' + lms_portal.escape(mobile) + '</span>') : '<span class="lms-muted">No mobile on file</span>') +
		'</div>' +
		'</div>' +
		'<div class="lms-queue-list__amount">' +
		'<span class="lms-queue-list__amount-label"' + dueTone + '>' + lms_portal.escape(dueLabel) + '</span>' +
		'<span class="lms-queue-list__amount-value">' + format_currency(row.amount) + '</span>' +
		'</div>' +
		'<div class="lms-queue-list__action">' +
		callBtn +
		'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-collect-btn" data-loan="' +
		lms_portal.escape(row.loan) +
		'" data-amount="' +
		lms_portal.escape(String(row.amount)) +
		'">Collect</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-promise-btn" data-loan="' +
		lms_portal.escape(row.loan) +
		'">Promise</button>' +
		'</div></li>'
	);
};

lms_collect._renderRunSheet = function (root, rows, kpis, collectedToday) {
	kpis = kpis || null;
	collectedToday = collectedToday || null;
	var queueCount = lms_collect._offlineQueueCount();
	var queued = lms_collect._queuedLoanSet();

	// R58: split the server's bucket-tagged rows into two lists. The same
	// row builder serves both, so Collect / Call / Promise / Reveal /
	// pending-sync badges behave identically on overdue rows.
	var overdueRows = [];
	var upcomingRows = [];
	(rows || []).forEach(function (row) {
		if (row.bucket === "overdue") overdueRows.push(row);
		else if (row.bucket === "upcoming") upcomingRows.push(row);
		else upcomingRows.push(row); // legacy/untagged rows stay upcoming
	});

	var listBody = "";

	// R59: search over 70+ stops — a field collector must find a borrower
	// by name or loan number without scrolling. Client-side filter over
	// the already-loaded rows; re-render per keystroke is fine at this n.
	var searchControls =
		'<div class="lms-collect-search">' +
		'<input type="text" class="lms-input" id="lms-collect-search" ' +
		'placeholder="Search borrower or loan #…" autocomplete="off">' +
		'</div>';

	// Overdue first — the riskiest stops lead the page.
	listBody += '<h3 class="lms-section-title lms-overdue-heading">Overdue</h3>';
	if (!overdueRows.length) {
		listBody += '<p class="lms-muted lms-overdue-empty">No arrears — nothing overdue.</p>';
	} else {
		listBody += '<ul class="lms-list lms-queue-list lms-overdue-list">';
		overdueRows.forEach(function (row) {
			listBody += lms_collect._runSheetRowHtml(row, queued, true);
		});
		listBody += "</ul>";
	}

	// Upcoming: today and the forward window.
	listBody += '<h3 class="lms-section-title lms-upcoming-heading">Due today &amp; upcoming</h3>';
	if (!upcomingRows.length) {
		listBody += '<p class="lms-muted lms-upcoming-empty">No upcoming dues in range.</p>';
	} else {
		listBody += '<ul class="lms-list lms-queue-list lms-upcoming-list">';
		upcomingRows.forEach(function (row) {
			listBody += lms_collect._runSheetRowHtml(row, queued, false);
		});
		listBody += "</ul>";
	}

	var syncControls =
		'<div class="lms-collect-sync">' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-sync-offline">' +
		(window.lms_icons ? lms_icons.icon("refresh", { size: 14 }) : "") +
		'Sync offline queue' +
		(queueCount > 0 ? ' <span class="lms-badge lms-badge--watch">' + queueCount + "</span>" : "") +
		"</button></div>";

	// R58 KPI strip: Stops/Amount describe the UPCOMING stops; Overdue is
	// its own headline number fed straight from the server's kpis payload
	// (never recounted here — R35-#27 single source of truth).
	// R59: Collected today leads the strip — the first thing a collector
	// wants to know is "what did I bank today", not what is still owed.
	var kpiOverdueCount = kpis && kpis.overdue ? (kpis.overdue.count || 0) : 0;
	var kpiOverdueAmount = kpis && kpis.overdue ? (kpis.overdue.amount || 0) : 0;
	var kpiUpcomingCount = kpis && kpis.upcoming ? (kpis.upcoming.count || 0) : upcomingRows.length;
	var kpiUpcomingAmount = kpis && kpis.upcoming ? (kpis.upcoming.amount || 0) : 0;
	var collected = collectedToday || { amount: 0, count: 0 };

	var historyPanel =
		'<section class="lms-collect-history" id="lms-collect-history" hidden>' +
		'<div class="lms-collect-history__body" id="lms-collect-history-body"></div>' +
		'</section>';

	// R59-FIX: use the SAME tab navigation as every other portal dashboard
	// (officer/manager/setup) instead of a one-off toggle button. The KPI
	// strip lives inside the Run sheet tab; History is its own tab with
	// the 7/30/90-day window switcher. Tab choice persists per session,
	// consistent with lms_portal.persistedTab elsewhere.
	// R59 board polish: the connectivity pill is injected into the page's
	// .lms-collect-meta row (in collect.html) instead of rendering as a
	// full-width strip above the tabs.
	var html = lms_portal.pageStart() +
		lms_portal.tabNav(lms_collect._tabs, lms_collect._currentTab) +
		'<div id="lms-collect-tab-content">' +
		// -- Run sheet panel (default tab) --
		'<section class="lms-collect-panel" data-panel="runsheet">' +
		lms_portal.kpiStrip([
			{ label: "Collected today", value: format_currency(collected.amount) + " (" + collected.count + ")", tone: "success", id: "lms-kpi-collected" },
			{ label: "Overdue", value: format_currency(kpiOverdueAmount) + " (" + kpiOverdueCount + ")", tone: kpiOverdueCount ? "warning" : "success" },
			{ label: "Stops today", value: kpiUpcomingCount },
			{ label: "Amount due", value: format_currency(kpiUpcomingAmount) },
			{ label: "Offline queue", value: queueCount, tone: queueCount ? "warning" : "success" },
		]) +
		// R59 board review: no panel title — the active tab label directly
		// above already says "Run sheet"; a second heading wasted ~55px.
		lms_portal.panel({ body: searchControls + listBody + syncControls }) +
		'</section>' +
		// -- History panel (lazy-loaded on first view) --
		historyPanel +
		'</div>' +
		lms_portal.pageEnd();

	root.innerHTML = html;
	// R59 board polish: move the live connectivity pill into the page's
	// .lms-collect-meta row (after the last separator) so status reads as
	// part of one meta line instead of a stacked strip. bindConnectivity()
	// updates it in place by id, so the relocation is transparent.
	var metaRow = document.querySelector(".lms-collect-meta");
	if (metaRow) {
		var bannerHtml = lms_portal.connectivityBanner();
		var holder = document.createElement("span");
		holder.innerHTML = bannerHtml;
		var pill = holder.firstChild;
		if (pill) metaRow.appendChild(pill);
	}
	// R59: if a non-default tab was restored from persistence, apply its
	// panel visibility + tab highlight now that the markup exists.
	if (lms_collect._currentTab && lms_collect._currentTab !== "runsheet") {
		root.querySelectorAll(".lms-tab").forEach(function (b) {
			var active = b.getAttribute("data-tab") === lms_collect._currentTab;
			b.classList.toggle("is-active", active);
			b.setAttribute("aria-selected", active ? "true" : "false");
		});
		lms_collect._switchTab(lms_collect._currentTab);
	}
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

	// R59: run-sheet search — hide non-matching rows as the collector
	// types; show an inline count so an empty result reads as "no match",
	// not a broken page.
	var searchInput = document.getElementById("lms-collect-search");
	if (searchInput) {
		searchInput.addEventListener("input", function () {
			var q = (searchInput.value || "").trim().toLowerCase();
			root.querySelectorAll(".lms-queue-list").forEach(function (list) {
				var visible = 0;
				list.querySelectorAll(".lms-queue-list__item").forEach(function (li) {
					var hay = (li.textContent || "").toLowerCase();
					var show = !q || hay.indexOf(q) !== -1;
					li.style.display = show ? "" : "none";
					if (show) visible += 1;
				});
				list.hidden = q !== "" && visible === 0;
			});
			var emptyMsg = root.querySelector("#lms-collect-no-match");
			if (q) {
				if (!emptyMsg) {
					emptyMsg = document.createElement("p");
					emptyMsg.id = "lms-collect-no-match";
					emptyMsg.className = "lms-muted";
					searchInput.parentNode.appendChild(emptyMsg);
				}
				var anyVisible = [...root.querySelectorAll(".lms-queue-list__item")]
					.some(function (li) { return li.style.display !== "none"; });
				emptyMsg.textContent = anyVisible ? "" : "No stops match \"" + searchInput.value + "\".";
				emptyMsg.hidden = anyVisible;
			} else if (emptyMsg) {
				emptyMsg.hidden = true;
			}
		});
	}

	// R59: tab navigation — Run sheet | History, wired through
	// lms_portal.bindTabs like the officer/manager portals. Switching to
	// History lazy-loads (or re-uses) the collection history.
	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			var tabId = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.setAttribute("aria-selected", "true");
			lms_collect._switchTab(tabId);
		});
	});

	// R59: history toggle — lazy-load the collector's past collections on
	// first open; subsequent toggles reuse the loaded data.
	var historyToggle = document.getElementById("lms-history-toggle");
	if (historyToggle) {
		historyToggle.addEventListener("click", function () {
			lms_collect._toggleHistory();
		});
	}
};

lms_collect._tabs = [
	{ id: "runsheet", label: "Run sheet", icon: "clipboard" },
	{ id: "history", label: "My collections", icon: "receipt" },
];

lms_collect._currentTab = "runsheet";

lms_collect._switchTab = function (tabId) {
	lms_collect._currentTab = tabId;
	lms_portal.saveActiveTab("collect", tabId);
	var runsheet = document.querySelector('[data-panel="runsheet"]');
	var history = document.getElementById("lms-collect-history");
	if (!runsheet || !history) return;
	var showHistory = tabId === "history";
	// Keep both in the DOM; toggle visibility like the other portals'
	// tab-content swap, but without re-rendering the run sheet (state
	// like the search query survives the round-trip).
	runsheet.hidden = showHistory;
	history.hidden = !showHistory;
	if (showHistory) {
		var state = lms_collect._historyState;
		if (!state.loaded) {
			lms_collect._loadHistory(state.days);
		}
	}
};

lms_collect._historyState = { loaded: false, open: false, days: 30 };

lms_collect._loadHistory = function (days) {
	var state = lms_collect._historyState;
	var body = document.getElementById("lms-collect-history-body");
	if (!body) return;
	body.innerHTML = lms_portal.loading("Loading history…");
	lms_portal.safeCall({
		method: "lms_saas.api.field_collection.get_collection_history",
		args: { days: days },
		callback: function (r) {
			var data = (r && r.message) || {};
			state.loaded = true;
			state.days = days;
			lms_collect._renderHistory(body, data);
		},
		error: function () {
			body.innerHTML = lms_portal.error("Could not load history.", function () {
				lms_collect._loadHistory(state.days);
			});
		},
	});
};

lms_collect._renderHistory = function (body, data) {
	var days = data.days || 30;
	var windows = [7, 30, 90];
	var tabs = windows.map(function (w) {
		var active = w === days ? " is-active" : "";
		return '<button type="button" class="lms-collect-history__tab' + active + '" data-days="' + w + '">' + w + 'd</button>';
	}).join("");

	var summary =
		'<div class="lms-collect-history__summary">' +
		'<div><span class="lms-collect-history__amount">' + format_currency(data.total || 0) + '</span>' +
		'<span class="lms-collect-history__meta">collected in ' + lms_portal.escape(String(days)) + ' days · ' + (data.count || 0) + ' stops</span></div>' +
		'</div>';

	var rowsHtml = "";
	var items = data.items || [];
	if (!items.length) {
		rowsHtml = '<p class="lms-muted lms-collect-history__empty">No collections in this window.</p>';
	} else {
		// Group by date — day headers keep a month of stops scannable.
		var currentDay = null;
		rowsHtml += '<ul class="lms-list lms-queue-list lms-collect-history__list">';
		items.forEach(function (it) {
			if (it.date !== currentDay) {
				currentDay = it.date;
				rowsHtml += '<li class="lms-collect-history__day">' + lms_portal.formatDate(it.date) + '</li>';
			}
			rowsHtml +=
				'<li class="lms-queue-list__item lms-collect-history__row">' +
				'<div class="lms-queue-list__main">' +
				'<span class="lms-queue-list__name">' + lms_portal.escape(it.borrower || "—") + '</span>' +
				'<span class="lms-queue-list__sub">' + lms_portal.escape(it.loan || "") + (it.mode ? " · " + lms_portal.escape(it.mode) : "") + '</span>' +
				'</div>' +
				'<div class="lms-queue-list__amount">' +
				'<a class="lms-collect-history__receipt" href="/api/method/lms_saas.api.field_collection.generate_collection_receipt?repayment_name=' + encodeURIComponent(it.repayment || "") + '" target="_blank" rel="noopener">' + (window.lms_icons ? lms_icons.icon("download", { size: 13 }) : "") + ' Receipt</a>' +
				'</div>' +
				'<div class="lms-queue-list__amount">' +
				'<span class="lms-queue-list__amount-value">' + format_currency(it.amount) + '</span>' +
				'</div>' +
				'</li>';
		});
		rowsHtml += "</ul>";
	}

	body.innerHTML =
		'<div class="lms-collect-history__tabs">' + tabs + "</div>" +
		summary + rowsHtml;

	body.querySelectorAll(".lms-collect-history__tab").forEach(function (tab) {
		tab.addEventListener("click", function () {
			lms_collect._loadHistory(parseInt(tab.getAttribute("data-days"), 10) || 30);
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
	// Step 2: confirm "I've counted {currency} X in hand" before submission.
	// A typo of "2000" when "200" was meant loses the customer's money;
	// the explicit confirm sentence + checkbox is the cheapest defense
	// that does not require a network round-trip.
	// R57: the confirm sentence reads in the company's currency (USD,
	// ZAR, KES, NGN, …) rather than the hard-coded ZAR that the demo
	// started with. The currency resolution chain lives in ONE place —
	// lms_portal.resolveCurrency() — which the formatCurrency helper
	// also uses, so this modal and every other currency display on the
	// portal can never disagree about which currency is in play.
	var confirmCurrency = lms_portal.resolveCurrency();
	var formatMoney = function (v) {
		return lms_portal.formatCurrency(v, confirmCurrency);
	};
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
		// R57: the placeholder is rendered immediately so the first frame
		// already shows the correct currency, not the previous "ZAR 0.00".
		'<label class="lms-collect-confirm" style="margin-top:0.75rem;display:flex;align-items:flex-start;gap:0.5rem;font-weight:500;">' +
		'<input type="checkbox" id="lms-collect-confirm" style="margin-top:0.2rem;">' +
		'<span>I have <strong id="lms-collect-confirm-amount">' +
		formatMoney(0) +
		"</strong> in hand and confirm this amount is correct.</span>" +
		"</label>" +
		"</div>";
	var dlg = LMSModal.open({
		title: "Collect payment",
		titleIcon: "wallet",
		titleIcon: "wallet",
		body: body,
		size: "lg",
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
		// R57: use the same currency-aware formatter as the initial render
		// so the placeholder text and the live preview stay in lockstep.
		if (confirmAmount) confirmAmount.textContent = formatMoney(amount);
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
		titleIcon: "clock",
		titleIcon: "clock",
		body: body,
		size: "lg",
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
		titleIcon: "check-circle",
		titleIcon: "check-circle",
		size: "sm",
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
		// R59: stamp the queue entry at collection time. Without this the
		// repayment posted at sync time — daily KPIs and "Collected today"
		// attributed an 11:00 collection to whenever signal returned.
		item.collected_at = new Date().toISOString();
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
			var succeeded = results.filter(function (x) { return x.ok; });
			if (failed.length) {
				// R59: keep only the FAILED entries. Match on the queue
				// item identity (loan + amount + collected_at) rather than
				// loan alone — two stops for the same loan must not both
				// survive, or the succeeded one re-posts next sync.
				var failedKeys = {};
				failed.forEach(function (f) {
					failedKeys[f.loan + "|" + f.amount] = true;
				});
				var remaining = q.filter(function (item) {
					return failedKeys[item.loan + "|" + item.amount];
				});
				localStorage.setItem(lms_collect.DB_NAME, JSON.stringify(remaining));
				lms_collect._showSyncErrors(failed);
			} else {
				localStorage.removeItem(lms_collect.DB_NAME);
				frappe.show_alert({
					message: lms_copy.tSync("collector.synced", "Synced {when}", { when: results.length + " items" }),
					indicator: "green"
				});
				// R59: offline collections previously never got a receipt
				// prompt — the first synced repayment with a reference
				// gets the same prompt as the online path.
				var firstOk = succeeded.find(function (x) { return x.repayment; });
				if (firstOk && firstOk.repayment) {
					lms_collect._showReceiptPrompt(firstOk.repayment);
				}
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
		titleIcon: "alert-triangle",
		titleIcon: "alert-triangle",
		body: body,
		size: "md",
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
