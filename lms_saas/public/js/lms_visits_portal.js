/* LMS Field Visits portal — schedule, my visits, stats */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_visits");
} else {
	window.lms_visits = window.lms_visits || {};
}

lms_visits._currentTab = "schedule";

lms_visits.init = function () {
	var root = document.getElementById("lms-visits-root");
	if (!root) return;

	var tabs = [
		{ id: "schedule", label: "Schedule", icon: "📅" },
		{ id: "myvisits", label: "My Visits", icon: "🗺️" },
		{ id: "stats", label: "Stats", icon: "📊" },
	];
	var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;">';
	html += '<h2 style="margin:0;font-size:var(--lms-fs-xl);font-weight:700;">Field Visits</h2>';
	html += '<div style="display:flex;gap:0.5rem;">';
	html += '<button type="button" class="lms-btn lms-btn--primary" id="lms-vis-new">+ Schedule Visit</button>';
	html += '</div></div>';
	html += '<div id="lms-vis-stats" style="margin-bottom:1rem;"></div>';
	html += '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_visits._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	html += '<div id="lms-visits-tab-content"></div>';
	root.innerHTML = html;

	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_visits._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.style.borderBottom = "2px solid var(--lms-primary)";
			btn.style.color = "var(--lms-primary)";
			btn.style.fontWeight = "600";
			lms_visits._showTab(lms_visits._currentTab);
		});
	});

	lms_visits._loadStats();

	var newBtn = root.querySelector("#lms-vis-new");
	if (newBtn) {
		newBtn.addEventListener("click", function () {
			lms_visits._showCreateModal();
		});
	}

	lms_visits._showTab(lms_visits._currentTab);
};

lms_visits._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_visits._loadStats = function () {
	var el = document.getElementById("lms-vis-stats");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.field_visits.get_visit_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = '<section class="lms-grid-4">';
			html += lms_visits._statCard("Total", s.total || 0);
			html += lms_visits._statCard("Today", s.today || 0, "info");
			html += lms_visits._statCard("In Progress", s.in_progress || 0, "warning");
			html += lms_visits._statCard("Completed", s.completed || 0, "success");
			html += "</section>";
			el.innerHTML = html;
		},
	});
};

lms_visits._showTab = function (tabId) {
	var content = document.getElementById("lms-visits-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "schedule") lms_visits._loadSchedule(content);
	else if (tabId === "myvisits") lms_visits._loadMyVisits(content);
	else if (tabId === "stats") lms_visits._loadStatsTab(content);
};

// ── Schedule ──

lms_visits._loadSchedule = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.field_visits.get_visit_schedule",
		args: { status: "Planned" },
		callback: function (r) {
			var visits = (r && r.message && r.message.visits) || [];
			if (!visits.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📅</div><h3>No scheduled visits</h3><p>No planned field visits.</p></div></div>';
				return;
			}

			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Type</th><th>Customer</th><th>Officer</th><th>Planned Date</th><th>Status</th><th>Actions</th></tr></thead><tbody>";
			visits.forEach(function (v) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(v.visit_type) + "</strong></td>";
				html += "<td>" + lms_portal.escape(v.customer_name || "—") + "</td>";
				html += "<td>" + lms_portal.escape(v.officer_name || "—") + "</td>";
				html += "<td>" + lms_portal.formatDate(v.planned_date) + "</td>";
				html += '<td><span class="lms-badge lms-badge--info">' + lms_portal.escape(v.status) + "</span></td>";
				html += '<td><div class="lms-data-table__actions">';
				html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-vis-checkin" data-name="' + lms_portal.escape(v.name) + '">Check In</button>';
				html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-vis-view" data-name="' + lms_portal.escape(v.name) + '">View</button>';
				html += '</div></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-vis-checkin").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_visits._checkIn(btn.getAttribute("data-name"));
				});
			});
			content.querySelectorAll(".lms-vis-view").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_visits._showVisitDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load schedule.");
		},
	});
};

// ── My Visits ──

lms_visits._loadMyVisits = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.field_visits.get_visit_schedule",
		callback: function (r) {
			var visits = (r && r.message && r.message.visits) || [];
			if (!visits.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">🗺️</div><h3>No visits</h3><p>No field visits found.</p></div></div>';
				return;
			}

			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Type</th><th>Customer</th><th>Planned Date</th><th>Check-In</th><th>Status</th><th>Actions</th></tr></thead><tbody>";
			visits.forEach(function (v) {
				var statusCls = v.status === "Completed" ? "lms-badge--success" : (v.status === "In Progress" ? "lms-badge--warning" : (v.status === "Cancelled" ? "lms-badge--danger" : "lms-badge--info"));
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(v.visit_type) + "</strong></td>";
				html += "<td>" + lms_portal.escape(v.customer_name || "—") + "</td>";
				html += "<td>" + lms_portal.formatDate(v.planned_date) + "</td>";
				html += "<td>" + (v.check_in_time ? lms_portal.formatDate(v.check_in_time) : "—") + "</td>";
				html += '<td><span class="lms-badge ' + statusCls + '">' + lms_portal.escape(v.status) + "</span></td>";
				html += '<td><div class="lms-data-table__actions">';
				if (v.status === "In Progress") {
					html += '<button type="button" class="lms-btn lms-btn--success lms-btn--sm lms-vis-complete" data-name="' + lms_portal.escape(v.name) + '">Complete</button>';
				}
				html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-vis-view" data-name="' + lms_portal.escape(v.name) + '">View</button>';
				html += '</div></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-vis-complete").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_visits._showCompleteModal(btn.getAttribute("data-name"));
				});
			});
			content.querySelectorAll(".lms-vis-view").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_visits._showVisitDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load visits.");
		},
	});
};

// ── Stats Tab ──

lms_visits._loadStatsTab = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.field_visits.get_visit_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = '<section class="lms-grid-4">';
			html += lms_visits._statCard("Total Visits", s.total || 0);
			html += lms_visits._statCard("Planned", s.planned || 0, "info");
			html += lms_visits._statCard("In Progress", s.in_progress || 0, "warning");
			html += lms_visits._statCard("Completed", s.completed || 0, "success");
			html += lms_visits._statCard("Cancelled", s.cancelled || 0, "danger");
			html += lms_visits._statCard("Today", s.today || 0, "info");
			html += "</section>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load stats.");
		},
	});
};

// ── Create Visit Modal ──

lms_visits._showCreateModal = function () {
	var visitTypes = [
		"KYC Verification",
		"Collateral Inspection",
		"Collections Follow-up",
		"Pre-Disbursement Assessment",
		"Customer Visit",
	];

	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Visit Type</label>';
	html += '<select id="lms-vis-type" class="lms-input lms-fallback-select">';
	visitTypes.forEach(function (vt) {
		html += '<option value="' + vt + '">' + vt + '</option>';
	});
	html += '</select></div>';
	html += '<div class="lms-field"><label>Customer</label>';
	html += '<input type="text" id="lms-vis-customer" class="lms-input" placeholder="Customer name (optional)"></div>';
	html += '<div class="lms-field"><label>Loan</label>';
	html += '<input type="text" id="lms-vis-loan" class="lms-input" placeholder="Loan ID (optional)"></div>';
	html += '<div class="lms-field"><label>Planned Date & Time</label>';
	html += '<input type="datetime-local" id="lms-vis-date" class="lms-input"></div>';
	html += '<div class="lms-field"><label>Notes</label>';
	html += '<textarea id="lms-vis-notes" class="lms-input" rows="3" placeholder="Visit notes…"></textarea></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Schedule Field Visit",
		body: html,
		confirmText: "Schedule",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var visitType = overlay.querySelector("#lms-vis-type").value;
			var customer = overlay.querySelector("#lms-vis-customer").value;
			var loan = overlay.querySelector("#lms-vis-loan").value;
			var plannedDate = overlay.querySelector("#lms-vis-date").value;
			var notes = overlay.querySelector("#lms-vis-notes").value;

			if (!plannedDate) {
				lms_portal.toast("Planned date is required.", "danger");
				return false;
			}

			lms_portal.safeCall({
				method: "lms_saas.api.field_visits.create_visit",
				args: {
					visit_type: visitType,
					planned_date: plannedDate,
					customer: customer || undefined,
					loan: loan || undefined,
					notes: notes || undefined,
				},
				callback: function (r) {
					lms_portal.toast("Visit scheduled: " + ((r && r.message && r.message.name) || ""), "success");
					lms_visits._loadStats();
					lms_visits._showTab(lms_visits._currentTab);
				},
				error: function () {
					lms_portal.toast("Could not schedule visit.", "danger");
				},
			});
		},
	});
};

// ── Check In ──

lms_visits._checkIn = function (visitName) {
	if (!navigator.geolocation) {
		lms_portal.toast("Geolocation not available on this device.", "warning");
		return;
	}

	lms_portal.toast("Getting your location…", "info");

	navigator.geolocation.getCurrentPosition(
		function (position) {
			var lat = position.coords.latitude;
			var lon = position.coords.longitude;

			lms_portal.safeCall({
				method: "lms_saas.api.field_visits.check_in",
				args: {
					visit_name: visitName,
					latitude: lat,
					longitude: lon,
				},
				callback: function (r) {
					lms_portal.toast("Checked in at " + lat.toFixed(4) + ", " + lon.toFixed(4), "success");
					lms_visits._loadStats();
					lms_visits._showTab(lms_visits._currentTab);
				},
				error: function () {
					lms_portal.toast("Check-in failed.", "danger");
				},
			});
		},
		function (err) {
			lms_portal.toast("Could not get location: " + (err.message || "permission denied"), "danger");
		},
		{ enableHighAccuracy: true, timeout: 10000 }
	);
};

// ── Visit Detail ──

lms_visits._showVisitDetail = function (visitName) {
	lms_portal.safeCall({
		method: "lms_saas.api.field_visits.get_visit_detail",
		args: { visit_name: visitName },
		callback: function (r) {
			var v = (r && r.message) || {};
			var html = '<div class="lms-form">';
			html += '<div class="lms-field"><label>Visit Type</label><div>' + lms_portal.escape(v.visit_type || "") + '</div></div>';
			html += '<div class="lms-field"><label>Customer</label><div>' + lms_portal.escape(v.customer_name || "—") + '</div></div>';
			html += '<div class="lms-field"><label>Officer</label><div>' + lms_portal.escape(v.officer_name || "—") + '</div></div>';
			html += '<div class="lms-field"><label>Planned Date</label><div>' + lms_portal.formatDate(v.planned_date) + '</div></div>';
			html += '<div class="lms-field"><label>Check-In Time</label><div>' + (v.check_in_time ? lms_portal.formatDate(v.check_in_time) : "—") + '</div></div>';
			if (v.check_in_lat && v.check_in_lon) {
				html += '<div class="lms-field"><label>Geo-Location</label><div>' + lms_portal.escape(v.check_in_lat) + ', ' + lms_portal.escape(v.check_in_lon) + '</div></div>';
			}
			html += '<div class="lms-field"><label>Status</label><div>' + lms_portal.escape(v.status || "") + '</div></div>';
			html += '<div class="lms-field"><label>Notes</label><div>' + lms_portal.escape(v.notes || "—") + '</div></div>';
			if (v.photos) {
				html += '<div class="lms-field"><label>Photos</label><div><a href="' + lms_portal.escape(v.photos) + '" target="_blank">📎 View Photo</a></div></div>';
			}
			html += '</div>';

			lms_portal.modal({
				title: "Visit Detail",
				body: html,
				size: "lg",
				confirmText: "Close",
				confirmVariant: "primary",
			});
		},
		error: function () {
			lms_portal.toast("Could not load visit detail.", "danger");
		},
	});
};

// ── Complete Visit Modal ──

lms_visits._showCompleteModal = function (visitName) {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Completion Notes</label>';
	html += '<textarea id="lms-vis-complete-notes" class="lms-input" rows="4" placeholder="Visit outcome, findings, recommendations…"></textarea></div>';
	html += '<div class="lms-field"><label>Photo URL (optional)</label>';
	html += '<input type="text" id="lms-vis-complete-photos" class="lms-input" placeholder="/files/visit-photo.jpg"></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Complete Visit",
		body: html,
		confirmText: "Complete",
		confirmVariant: "success",
		onConfirm: function (overlay) {
			var notes = overlay.querySelector("#lms-vis-complete-notes").value;
			var photos = overlay.querySelector("#lms-vis-complete-photos").value;

			lms_portal.safeCall({
				method: "lms_saas.api.field_visits.complete_visit",
				args: {
					visit_name: visitName,
					notes: notes || undefined,
					photos: photos || undefined,
				},
				callback: function (r) {
					lms_portal.toast("Visit completed: " + ((r && r.message && r.message.name) || ""), "success");
					lms_visits._loadStats();
					lms_visits._showTab(lms_visits._currentTab);
				},
				error: function () {
					lms_portal.toast("Could not complete visit.", "danger");
				},
			});
		},
	});
};