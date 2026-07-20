/* LMS Customer Feedback portal — surveys, responses, dashboard */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_feedback");
} else {
	window.lms_feedback = window.lms_feedback || {};
}

lms_feedback._currentTab = "surveys";

lms_feedback.init = function () {
	var root = document.getElementById("lms-feedback-root");
	if (!root) return;

	var isBorrower = (window.frappe && frappe.boot && frappe.boot.user_roles &&
		frappe.boot.user_roles.indexOf("Customer") >= 0 &&
		frappe.boot.user_roles.indexOf("LMS Portal Staff") < 0);
	var isAdmin = (window.frappe && frappe.boot && frappe.boot.user_roles &&
		(frappe.boot.user_roles.indexOf("System Manager") >= 0 ||
		 frappe.boot.user_roles.indexOf("Administrator") >= 0));

	var tabs;
	if (isBorrower) {
		tabs = [
			{ id: "surveys", label: "Take Survey", icon: "📝" },
			{ id: "responses", label: "My Responses", icon: "📋" },
		];
	} else {
		tabs = [
			{ id: "dashboard", label: "Dashboard", icon: "📊" },
			{ id: "responses", label: "Recent Feedback", icon: "💬" },
		];
		if (isAdmin) {
			tabs.push({ id: "surveys", label: "Surveys", icon: "📝" });
		}
	}

	var actions = isAdmin ? [{ label: "+ New Survey", id: "lms-fb-new-survey", primary: true }] : [];
	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "Customer Feedback", actions: actions }) +
		lms_portal.tabNav(tabs, lms_feedback._currentTab) +
		'<div id="lms-feedback-tab-content"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_portal.bindTabs({
		root: root,
		tabs: tabs,
		onTab: function (tabId) { lms_feedback._currentTab = tabId; lms_feedback._showTab(tabId); },
	});

	if (isAdmin) {
		var newBtn = root.querySelector("#lms-fb-new-survey");
		if (newBtn) {
			newBtn.addEventListener("click", function () {
				lms_feedback._showCreateSurveyModal();
			});
		}
	}

	lms_feedback._showTab(lms_feedback._currentTab);
};

lms_feedback._showTab = function (tabId) {
	var content = document.getElementById("lms-feedback-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "surveys") lms_feedback._loadSurveys(content);
	else if (tabId === "responses") lms_feedback._loadResponses(content);
	else if (tabId === "dashboard") lms_feedback._loadDashboard(content);
};

// ── Surveys ──

lms_feedback._loadSurveys = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.feedback.get_surveys",
		callback: function (r) {
			var surveys = (r && r.message && r.message.surveys) || [];
			if (!surveys.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📝</div><h3>No surveys</h3><p>There are no active surveys right now.</p></div></div>';
				return;
			}

			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Title</th><th>Trigger</th><th>Questions</th><th>Status</th><th>Action</th></tr></thead><tbody>";
			surveys.forEach(function (s) {
				var activeCls = s.is_active ? "lms-badge--success" : "lms-badge--muted";
				var statusLabel = s.is_active ? "Active" : "Inactive";
				if (s.responded) {
					statusLabel = "Completed";
					activeCls = "lms-badge--info";
				}
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(s.title) + "</strong></td>";
				html += "<td>" + lms_portal.escape(s.trigger_event || "") + "</td>";
				html += "<td>" + (s.question_count || 0) + "</td>";
				html += '<td><span class="lms-badge ' + activeCls + '">' + statusLabel + "</span></td>";
				if (s.responded) {
					html += "<td>—</td>";
				} else {
					html += '<td><button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-fb-take" data-name="' + lms_portal.escape(s.name) + '">Take Survey</button></td>';
				}
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-fb-take").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_feedback._showTakeSurveyModal(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load surveys.");
		},
	});
};

lms_feedback._showTakeSurveyModal = function (surveyName) {
	lms_portal.safeCall({
		method: "lms_saas.api.feedback.get_survey_detail",
		args: { survey_name: surveyName },
		callback: function (r) {
			var survey = (r && r.message) || {};
			var questions = survey.questions || [];

			var html = '<div class="lms-form">';
			if (survey.description) {
				html += '<p class="lms-muted" style="margin-bottom:1rem;">' + lms_portal.escape(survey.description) + '</p>';
			}

			// NPS score
			html += '<div class="lms-field"><label>How likely are you to recommend us? (0-10)</label>';
			html += '<select id="lms-fb-nps" class="lms-input lms-fallback-select">';
			for (var i = 0; i <= 10; i++) {
				html += '<option value="' + i + '">' + i + '</option>';
			}
			html += '</select></div>';

			questions.forEach(function (q, idx) {
				html += '<div class="lms-field"><label>' + (idx + 1) + '. ' + lms_portal.escape(q.question_text) + '</label>';
				if (q.question_type === "Rating") {
					html += '<select class="lms-input lms-fallback-select lms-fb-answer" data-question="' + lms_portal.escape(q.question_text) + '">';
					for (var i = 1; i <= 5; i++) {
						html += '<option value="' + i + '">' + i + ' star' + (i > 1 ? 's' : '') + '</option>';
					}
					html += '</select>';
				} else if (q.question_type === "Multiple Choice") {
					html += '<select class="lms-input lms-fallback-select lms-fb-answer" data-question="' + lms_portal.escape(q.question_text) + '">';
					(q.options || []).forEach(function (opt) {
						if (opt.trim()) {
							html += '<option value="' + lms_portal.escape(opt.trim()) + '">' + lms_portal.escape(opt.trim()) + '</option>';
						}
					});
					html += '</select>';
				} else {
					html += '<textarea class="lms-input lms-fb-answer" data-question="' + lms_portal.escape(q.question_text) + '" rows="3" placeholder="Your answer…"></textarea>';
				}
				html += '</div>';
			});
			html += '</div>';

			lms_portal.modal({
				title: survey.title || "Take Survey",
				body: html,
				size: "lg",
				confirmText: "Submit",
				confirmVariant: "primary",
				onConfirm: function (overlay) {
					var npsScore = overlay.querySelector("#lms-fb-nps").value;
					var answers = [];
					overlay.querySelectorAll(".lms-fb-answer").forEach(function (el) {
						answers.push({
							question: el.getAttribute("data-question"),
							answer: el.value,
						});
					});

					lms_portal.safeCall({
						method: "lms_saas.api.feedback.submit_survey_response",
						args: {
							survey_name: surveyName,
							responses: JSON.stringify(answers),
							nps_score: npsScore,
						},
						callback: function (r) {
							lms_portal.toast((r && r.message && r.message.message) || "Survey submitted. Thank you!", "success");
							lms_feedback._showTab(lms_feedback._currentTab);
						},
						error: function () {
							lms_portal.toast("Could not submit survey.", "danger");
						},
					});
				},
			});
		},
		error: function () {
			lms_portal.toast("Could not load survey.", "danger");
		},
	});
};

// ── Responses ──

lms_feedback._loadResponses = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.feedback.get_feedback_list",
		callback: function (r) {
			var responses = (r && r.message && r.message.responses) || [];
			if (!responses.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">💬</div><h3>No responses</h3><p>No feedback responses yet.</p></div></div>';
				return;
			}

			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Survey</th><th>Customer</th><th>NPS</th><th>Submitted</th></tr></thead><tbody>";
			responses.forEach(function (resp) {
				var npsCls = (resp.nps_score >= 9) ? "lms-badge--success" : (resp.nps_score <= 6 ? "lms-badge--danger" : "lms-badge--warning");
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(resp.survey_title || "") + "</strong></td>";
				html += "<td>" + lms_portal.escape(resp.customer_name || "") + "</td>";
				html += '<td><span class="lms-badge ' + npsCls + '">' + (resp.nps_score !== null && resp.nps_score !== undefined ? resp.nps_score : "—") + "</span></td>";
				html += "<td>" + lms_portal.formatDate(resp.submitted_on) + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load responses.");
		},
	});
};

// ── Dashboard ──

lms_feedback._loadDashboard = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.feedback.get_feedback_dashboard",
		callback: function (r) {
			var d = (r && r.message) || {};
			var html = lms_portal.kpiStrip([
				{ label: "Total Responses", value: d.total_responses || 0 },
				{ label: "Overall NPS", value: (d.overall_nps || 0).toFixed(1), tone: d.overall_nps >= 0 ? "success" : "danger" },
			]);

			// By survey
			var bySurvey = d.by_survey || [];
			if (bySurvey.length) {
				html += '<h3 style="margin:1rem 0 0.5rem;font-size:var(--lms-fs-lg);">By Survey</h3>';
				html += '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
				html += "<thead><tr><th>Survey</th><th>Responses</th><th>Avg NPS</th></tr></thead><tbody>";
				bySurvey.forEach(function (s) {
					html += "<tr>";
					html += "<td><strong>" + lms_portal.escape(s.survey) + "</strong></td>";
					html += "<td>" + (s.count || 0) + "</td>";
					html += "<td>" + (s.avg_nps || 0).toFixed(1) + "</td>";
					html += "</tr>";
				});
				html += "</tbody></table></div></div>";
			}

			// By branch
			var byBranch = d.by_branch || [];
			if (byBranch.length) {
				html += '<h3 style="margin:1.5rem 0 0.5rem;font-size:var(--lms-fs-lg);">By Branch</h3>';
				html += '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
				html += "<thead><tr><th>Branch</th><th>Responses</th><th>Avg NPS</th></tr></thead><tbody>";
				byBranch.forEach(function (b) {
					html += "<tr>";
					html += "<td><strong>" + lms_portal.escape(b.branch) + "</strong></td>";
					html += "<td>" + (b.count || 0) + "</td>";
					html += "<td>" + (b.avg_nps || 0).toFixed(1) + "</td>";
					html += "</tr>";
				});
				html += "</tbody></table></div></div>";
			}

			// By officer
			var byOfficer = d.by_officer || [];
			if (byOfficer.length) {
				html += '<h3 style="margin:1.5rem 0 0.5rem;font-size:var(--lms-fs-lg);">By Officer</h3>';
				html += '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
				html += "<thead><tr><th>Officer</th><th>Responses</th><th>Avg NPS</th></tr></thead><tbody>";
				byOfficer.forEach(function (o) {
					html += "<tr>";
					html += "<td><strong>" + lms_portal.escape(o.officer_name || o.officer) + "</strong></td>";
					html += "<td>" + (o.count || 0) + "</td>";
					html += "<td>" + (o.avg_nps || 0).toFixed(1) + "</td>";
					html += "</tr>";
				});
				html += "</tbody></table></div></div>";
			}

			if (!bySurvey.length && !byBranch.length && !byOfficer.length) {
				html += '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📊</div><h3>No data</h3><p>No feedback data to display yet.</p></div></div>';
			}

			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load dashboard.");
		},
	});
};

// ── Create Survey (admin) ──

lms_feedback._showCreateSurveyModal = function () {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Title</label>';
	html += '<input type="text" id="lms-fb-title" class="lms-input" placeholder="Survey title"></div>';
	html += '<div class="lms-field"><label>Description</label>';
	html += '<textarea id="lms-fb-desc" class="lms-input" rows="3" placeholder="Survey description…"></textarea></div>';
	html += '<div class="lms-field"><label>Trigger Event</label>';
	html += '<select id="lms-fb-trigger" class="lms-input lms-fallback-select">';
	html += '<option value="Manual">Manual</option>';
	html += '<option value="Post-Disbursement">Post-Disbursement</option>';
	html += '<option value="Post-Collection">Post-Collection</option>';
	html += '</select></div>';
	html += '<hr style="margin:1rem 0;border:none;border-top:1px solid var(--lms-border);">';
	html += '<h4>Questions</h4>';
	html += '<div id="lms-fb-questions"></div>';
	html += '<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-fb-add-q">+ Add Question</button>';
	html += '</div>';

	var m = lms_portal.modal({
		title: "Create Survey",
		body: html,
		size: "lg",
		confirmText: "Create",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var title = overlay.querySelector("#lms-fb-title").value;
			var desc = overlay.querySelector("#lms-fb-desc").value;
			var trigger = overlay.querySelector("#lms-fb-trigger").value;

			if (!title.trim()) {
				lms_portal.toast("Title is required.", "danger");
				return false;
			}

			var questions = [];
			overlay.querySelectorAll(".lms-fb-q-row").forEach(function (row) {
				var qText = row.querySelector(".lms-fb-q-text").value;
				var qType = row.querySelector(".lms-fb-q-type").value;
				var qOptions = row.querySelector(".lms-fb-q-options").value;
				if (qText.trim()) {
					questions.push({
						question_text: qText,
						question_type: qType,
						options: qOptions,
					});
				}
			});

			lms_portal.safeCall({
				method: "lms_saas.api.feedback.create_survey",
				args: {
					title: title,
					description: desc || undefined,
					trigger_event: trigger,
					questions: JSON.stringify(questions),
				},
				callback: function (r) {
					lms_portal.toast("Survey created: " + ((r && r.message && r.message.name) || ""), "success");
					lms_feedback._showTab(lms_feedback._currentTab);
				},
				error: function () {
					lms_portal.toast("Could not create survey.", "danger");
				},
			});
		},
	});

	// Add question row
	var addQBtn = m.el.querySelector("#lms-fb-add-q");
	if (addQBtn) {
		addQBtn.addEventListener("click", function () {
			var container = m.el.querySelector("#lms-fb-questions");
			var row = document.createElement("div");
			row.className = "lms-fb-q-row";
			row.style.cssText = "border:1px solid var(--lms-border);border-radius:var(--lms-radius);padding:0.75rem;margin-bottom:0.5rem;";
			row.innerHTML = '<div class="lms-field"><label>Question</label>' +
				'<input type="text" class="lms-input lms-fb-q-text" placeholder="Question text"></div>' +
				'<div style="display:flex;gap:0.5rem;">' +
				'<div class="lms-field" style="flex:1;"><label>Type</label>' +
				'<select class="lms-input lms-fallback-select lms-fb-q-type">' +
				'<option value="Rating">Rating</option>' +
				'<option value="Multiple Choice">Multiple Choice</option>' +
				'<option value="Open Text">Open Text</option>' +
				'</select></div>' +
				'<div class="lms-field" style="flex:2;"><label>Options (one per line)</label>' +
				'<textarea class="lms-input lms-fb-q-options" rows="2" placeholder="For Multiple Choice only"></textarea></div>' +
				'</div>';
			container.appendChild(row);
		});
	}
};