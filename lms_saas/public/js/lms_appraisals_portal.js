/* LMS Appraisals portal — cycles, my appraisals, goals */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_appraisals");
} else {
	window.lms_appraisals = window.lms_appraisals || {};
}

lms_appraisals._currentTab = "cycles";

lms_appraisals.init = function () {
	var root = document.getElementById("lms-appraisals-root");
	if (!root) return;

	var tabs = [
		{ id: "cycles", label: "Cycles", icon: "🔄" },
		{ id: "mine", label: "My Appraisals", icon: "📋" },
		{ id: "goals", label: "Goals", icon: "🎯" },
	];
	var html = '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_appraisals._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	html += '<div id="lms-appraisals-tab-content"></div>';
	root.innerHTML = html;

	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_appraisals._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.style.borderBottom = "2px solid var(--lms-primary)";
			btn.style.color = "var(--lms-primary)";
			btn.style.fontWeight = "600";
			lms_appraisals._showTab(lms_appraisals._currentTab);
		});
	});

	lms_appraisals._showTab(lms_appraisals._currentTab);
};

lms_appraisals._showTab = function (tabId) {
	var content = document.getElementById("lms-appraisals-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "cycles") lms_appraisals._loadCycles(content);
	else if (tabId === "mine") lms_appraisals._loadMine(content);
	else if (tabId === "goals") lms_appraisals._loadGoals(content);
};

lms_appraisals._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_appraisals._loadCycles = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.appraisals.get_appraisal_cycles",
		callback: function (r) {
			var cycles = (r && r.message && r.message.cycles) || [];
			if (!cycles.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">🔄</div><h3>No cycles</h3><p>No appraisal cycles found.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Cycle</th><th>From</th><th>To</th><th>Status</th><th>Appraisals</th><th>Completed</th><th>Rate</th></tr></thead><tbody>";
			cycles.forEach(function (c) {
				var statusClass = c.status === "Completed" ? "lms-badge--success" : (c.status === "In Progress" ? "lms-badge--warning" : "");
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(c.cycle_name || c.name) + "</strong></td>";
				html += "<td>" + lms_portal.formatDate(c.from_date) + "</td>";
				html += "<td>" + lms_portal.formatDate(c.to_date) + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(c.status || "") + "</span></td>";
				html += "<td>" + (c.total_appraisals || 0) + "</td>";
				html += "<td>" + (c.completed || 0) + "</td>";
				html += "<td><strong>" + (c.completion_rate || 0) + "%</strong></td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load appraisal cycles.");
		},
	});
};

lms_appraisals._loadMine = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.appraisals.get_appraisals",
		callback: function (r) {
			var appraisals = (r && r.message && r.message.appraisals) || [];
			if (!appraisals.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📋</div><h3>No appraisals</h3><p>No appraisals found for your branch.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Employee</th><th>Cycle</th><th>Status</th><th>Score</th><th>Date</th><th>Action</th></tr></thead><tbody>";
			appraisals.forEach(function (a) {
				var statusClass = a.docstatus === 1 ? "lms-badge--success" : (a.docstatus === 0 ? "lms-badge--warning" : "lms-badge--danger");
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(a.employee_name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(a.appraisal_cycle || "—") + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(a.status || "") + "</span></td>";
				html += "<td>" + (a.final_score || a.total_score || 0) + "</td>";
				html += "<td>" + lms_portal.formatDate(a.posting_date) + "</td>";
				html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-apr-view" data-name="' + lms_portal.escape(a.name) + '">View</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-apr-view").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_appraisals._showAppraisalDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load appraisals.");
		},
	});
};

lms_appraisals._showAppraisalDetail = function (name) {
	lms_portal.safeCall({
		method: "lms_saas.api.appraisals.get_appraisal_detail",
		args: { appraisal_name: name },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_appraisals._renderAppraisalDetail(data);
		},
	});
};

lms_appraisals._renderAppraisalDetail = function (data) {
	var a = data.appraisal || {};
	var goals = data.goals || [];
	var kras = data.kras || [];

	var html = '<div class="lms-form">';
	html += '<h3 style="margin:0 0 0.5rem;">' + lms_portal.escape(a.employee_name || "") + '</h3>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Cycle</div><div class="lms-summary-value">' + lms_portal.escape(a.appraisal_cycle || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(a.status || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Final Score</div><div class="lms-summary-value">' + (a.final_score || a.total_score || 0) + '</div></div>';
	html += '</div>';

	if (goals.length) {
		html += '<h4 style="margin:1rem 0 0.5rem;">Goals</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Goal</th><th>KRA</th><th>Weight</th><th>Score</th><th>Action</th></tr></thead><tbody>';
		goals.forEach(function (g) {
			html += "<tr>";
			html += "<td>" + lms_portal.escape(g.goal) + "</td>";
			html += "<td>" + lms_portal.escape(g.kra || "—") + "</td>";
			html += "<td>" + (g.per_weightage || 0) + "%</td>";
			html += "<td>" + (g.score || 0) + "</td>";
			html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-apr-score" data-row="' + lms_portal.escape(g.name) + '" data-appraisal="' + lms_portal.escape(a.name) + '">Score</button></td>';
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}

	if (kras.length) {
		html += '<h4 style="margin:1rem 0 0.5rem;">KRA Scores</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>KRA</th><th>Weight</th><th>Score</th><th>Earned</th><th>Action</th></tr></thead><tbody>';
		kras.forEach(function (k) {
			html += "<tr>";
			html += "<td>" + lms_portal.escape(k.kra) + "</td>";
			html += "<td>" + (k.per_weightage || 0) + "%</td>";
			html += "<td>" + (k.score || 0) + "</td>";
			html += "<td>" + (k.score_earned || 0) + "</td>";
			html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-apr-score-kra" data-row="' + lms_portal.escape(k.name) + '" data-appraisal="' + lms_portal.escape(a.name) + '">Score</button></td>';
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}

	html += '<div style="margin-top:1rem;"><button type="button" class="lms-btn lms-btn--primary lms-apr-add-goal" data-appraisal="' + lms_portal.escape(a.name) + '">+ Add Goal</button></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Appraisal " + (a.name || ""),
		body: html,
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});

	// Bind score buttons for goals
	document.querySelectorAll(".lms-apr-score").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_appraisals._showScoreModal(btn.getAttribute("data-appraisal"), btn.getAttribute("data-row"), "goal");
		});
	});
	// Bind score buttons for KRAs
	document.querySelectorAll(".lms-apr-score-kra").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_appraisals._showScoreModal(btn.getAttribute("data-appraisal"), btn.getAttribute("data-row"), "kra");
		});
	});
	// Bind add goal
	document.querySelectorAll(".lms-apr-add-goal").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_appraisals._showAddGoalModal(btn.getAttribute("data-appraisal"));
		});
	});
};

lms_appraisals._showScoreModal = function (appraisalName, rowName, type) {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Score (0-5)</label>';
	html += '<select id="lms-apr-score-val" class="lms-input lms-fallback-select">';
	html += '<option value="0">0 — Unsatisfactory</option>';
	html += '<option value="1">1 — Needs Improvement</option>';
	html += '<option value="2">2 — Meets Expectations</option>';
	html += '<option value="3" selected>3 — Good</option>';
	html += '<option value="4">4 — Very Good</option>';
	html += '<option value="5">5 — Outstanding</option>';
	html += '</select></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Score " + (type === "kra" ? "KRA" : "Goal"),
		body: html,
		confirmText: "Save Score",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var score = overlay.querySelector("#lms-apr-score-val").value;
			lms_portal.safeCall({
				method: "lms_saas.api.appraisals.score_kra",
				args: { appraisal_name: appraisalName, kra_row_name: rowName, score: score },
				callback: function () {
					lms_portal.toast("Score saved.", "success");
					lms_appraisals._showAppraisalDetail(appraisalName);
				},
				error: function () {
					lms_portal.toast("Could not save score.", "danger");
				},
			});
		},
	});
};

lms_appraisals._showAddGoalModal = function (appraisalName) {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Goal Title</label>';
	html += '<input type="text" id="lms-apr-goal-title" class="lms-input" placeholder="e.g. Increase loan disbursements by 20%"></div>';
	html += '<div class="lms-field"><label>KRA (optional)</label>';
	html += '<input type="text" id="lms-apr-goal-kra" class="lms-input" placeholder="Key Result Area"></div>';
	html += '<div class="lms-field"><label>Weight (%)</label>';
	html += '<input type="number" id="lms-apr-goal-weight" class="lms-input" value="0" min="0" max="100"></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Add Goal",
		body: html,
		confirmText: "Add",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var title = overlay.querySelector("#lms-apr-goal-title").value;
			var kra = overlay.querySelector("#lms-apr-goal-kra").value;
			var weight = overlay.querySelector("#lms-apr-goal-weight").value;
			if (!title) {
				lms_portal.toast("Goal title is required.", "danger");
				return false;
			}
			lms_portal.safeCall({
				method: "lms_saas.api.appraisals.create_goal",
				args: { appraisal_name: appraisalName, goal_title: title, kra: kra, per_weightage: weight },
				callback: function () {
					lms_portal.toast("Goal added.", "success");
					lms_appraisals._showAppraisalDetail(appraisalName);
				},
				error: function () {
					lms_portal.toast("Could not add goal.", "danger");
				},
			});
		},
	});
};

lms_appraisals._loadGoals = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.appraisals.get_appraisals",
		callback: function (r) {
			var appraisals = (r && r.message && r.message.appraisals) || [];
			if (!appraisals.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">🎯</div><h3>No goals</h3><p>No appraisals with goals found.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><p class="lms-muted" style="margin-bottom:1rem;">Select an appraisal to view and manage goals.</p>';
			html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Employee</th><th>Cycle</th><th>Status</th><th>Score</th><th>Action</th></tr></thead><tbody>";
			appraisals.forEach(function (a) {
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(a.employee_name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(a.appraisal_cycle || "—") + "</td>";
				html += "<td>" + lms_portal.escape(a.status || "") + "</td>";
				html += "<td>" + (a.final_score || a.total_score || 0) + "</td>";
				html += '<td><button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-apr-goal-view" data-name="' + lms_portal.escape(a.name) + '">Manage Goals</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-apr-goal-view").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_appraisals._showAppraisalDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load goals.");
		},
	});
};