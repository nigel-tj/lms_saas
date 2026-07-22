/* LMS Recruitment portal — openings, applicants, staffing plan */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_recruitment");
} else {
	window.lms_recruitment = window.lms_recruitment || {};
}

lms_recruitment._currentTab = "openings";

lms_recruitment.init = function () {
	var root = document.getElementById("lms-recruitment-root");
	if (!root) return;

	var tabs = [
		{ id: "openings", label: "Openings", icon: "💼" },
		{ id: "applicants", label: "Applicants", icon: "👤" },
		{ id: "staffing", label: "Staffing Plan", icon: "📊" },
	];
	var html = '<nav class="lms-tab-nav" role="tablist">';
	tabs.forEach(function (t) {
		var active = lms_recruitment._currentTab === t.id ? " is-active" : "";
		html += '<button type="button" class="lms-tab' + active + '" data-tab="' + t.id + '" role="tab" aria-selected="' + (active ? "true" : "false") + '">' + t.icon + " " + lms_portal.escape(t.label) + "</button>";
	});
	html += "</nav>";
	html += '<div id="lms-recruitment-tab-content"></div>';
	root.innerHTML = html;

	root.querySelectorAll(".lms-tab").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_recruitment._currentTab = btn.getAttribute("data-tab");
			root.querySelectorAll(".lms-tab").forEach(function (b) {
				b.classList.remove("is-active");
				b.setAttribute("aria-selected", "false");
			});
			btn.classList.add("is-active");
			btn.style.borderBottom = "2px solid var(--lms-primary)";
			btn.style.color = "var(--lms-primary)";
			btn.style.fontWeight = "600";
			lms_recruitment._showTab(lms_recruitment._currentTab);
		});
	});

	lms_recruitment._showTab(lms_recruitment._currentTab);
};

lms_recruitment._showTab = function (tabId) {
	var content = document.getElementById("lms-recruitment-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "openings") lms_recruitment._loadOpenings(content);
	else if (tabId === "applicants") lms_recruitment._loadApplicants(content);
	else if (tabId === "staffing") lms_recruitment._loadStaffing(content);
};

lms_recruitment._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_recruitment._loadOpenings = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.recruitment.get_job_openings",
		callback: function (r) {
			var openings = (r && r.message && r.message.openings) || [];
			if (!openings.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">💼</div><h3>No openings</h3><p>No open job positions right now.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Job Title</th><th>Designation</th><th>Positions</th><th>Applicants</th><th>Posted</th><th>Status</th><th>Action</th></tr></thead><tbody>";
			openings.forEach(function (o) {
				var statusClass = o.status === "Open" || o.status === "Published" ? "lms-badge--success" : "";
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(o.job_title || o.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(o.designation || "—") + "</td>";
				html += "<td>" + (o.no_of_positions || 1) + "</td>";
				html += "<td>" + (o.applicant_count || 0) + "</td>";
				html += "<td>" + lms_portal.formatDate(o.posting_date || o.publish_date) + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(o.status || "") + "</span></td>";
				html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-rec-view-applicants" data-opening="' + lms_portal.escape(o.name) + '">Applicants</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-rec-view-applicants").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_recruitment._currentOpening = btn.getAttribute("data-opening");
					lms_recruitment._showTab("applicants");
					// Update tab nav active state
					document.querySelectorAll(".lms-tab").forEach(function (b) {
						b.classList.remove("is-active");
						b.style.borderBottom = "2px solid transparent";
						b.style.color = "var(--lms-text-muted)";
						b.style.fontWeight = "400";
					});
					var applicantsTab = document.querySelector('.lms-tab[data-tab="applicants"]');
					if (applicantsTab) {
						applicantsTab.classList.add("is-active");
						applicantsTab.style.borderBottom = "2px solid var(--lms-primary)";
						applicantsTab.style.color = "var(--lms-primary)";
						applicantsTab.style.fontWeight = "600";
					}
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load job openings.");
		},
	});
};

lms_recruitment._loadApplicants = function (content) {
	var opening = lms_recruitment._currentOpening || null;
	lms_portal.safeCall({
		method: "lms_saas.api.recruitment.get_applicants",
		args: { job_opening: opening },
		callback: function (r) {
			var applicants = (r && r.message && r.message.applicants) || [];
			if (!applicants.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">👤</div><h3>No applicants</h3><p>' + (opening ? "No applicants for this opening." : "No applicants found.") + '</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel">';
			if (opening) {
				html += '<p class="lms-muted" style="margin-bottom:1rem;">Applicants for <strong>' + lms_portal.escape(opening) + '</strong></p>';
			}
			html += '<div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Status</th><th>Applied</th><th>Action</th></tr></thead><tbody>";
			applicants.forEach(function (a) {
				var statusClass = a.status === "Accepted" ? "lms-badge--success" : (a.status === "Rejected" ? "lms-badge--danger" : "lms-badge--warning");
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(a.applicant_name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(a.email_id || "—") + "</td>";
				html += "<td>" + lms_portal.escape(a.phone_number || "—") + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(a.status || "") + "</span></td>";
				html += "<td>" + lms_portal.formatDate(a.creation) + "</td>";
				html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-rec-view-applicant" data-name="' + lms_portal.escape(a.name) + '">View</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-rec-view-applicant").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_recruitment._showApplicantDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load applicants.");
		},
	});
};

lms_recruitment._showApplicantDetail = function (name) {
	lms_portal.safeCall({
		method: "lms_saas.api.recruitment.get_applicant_detail",
		args: { applicant_name: name },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_recruitment._renderApplicantDetail(data);
		},
	});
};

lms_recruitment._renderApplicantDetail = function (data) {
	var a = data.applicant || {};
	var interviews = data.interviews || [];

	var html = '<div class="lms-form">';
	html += '<h3 style="margin:0 0 0.5rem;">' + lms_portal.escape(a.applicant_name || "") + '</h3>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Email</div><div class="lms-summary-value">' + lms_portal.escape(a.email_id || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Phone</div><div class="lms-summary-value">' + lms_portal.escape(a.phone_number || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(a.status || "") + '</div></div>';
	html += '</div>';

	if (a.cover_letter) {
		html += '<h4 style="margin:1rem 0 0.5rem;">Cover Letter</h4>';
		html += '<div class="lms-panel" style="padding:0.75rem;"><p style="margin:0;font-size:var(--lms-fs-sm);">' + lms_portal.escape(a.cover_letter) + '</p></div>';
	}

	if (interviews.length) {
		html += '<h4 style="margin:1rem 0 0.5rem;">Interview History</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Round</th><th>Scheduled</th><th>Status</th><th>Rating</th></tr></thead><tbody>';
		interviews.forEach(function (iv) {
			html += "<tr>";
			html += "<td><strong>" + lms_portal.escape(iv.interview_round || "—") + "</strong></td>";
			html += "<td>" + lms_portal.formatDate(iv.scheduled_on) + "</td>";
			html += "<td>" + lms_portal.escape(iv.status || "—") + "</td>";
			html += "<td>" + (iv.rating || "—") + "</td>";
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}

	html += '<div style="margin-top:1rem;"><button type="button" class="lms-btn lms-btn--primary lms-rec-schedule" data-applicant="' + lms_portal.escape(a.name) + '">Schedule Interview</button></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Applicant " + (a.name || ""),
		body: html,
		size: "xl",
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});

	var scheduleBtn = document.querySelector(".lms-rec-schedule");
	if (scheduleBtn) {
		scheduleBtn.addEventListener("click", function () {
			lms_recruitment._showScheduleModal(scheduleBtn.getAttribute("data-applicant"));
		});
	}
};

lms_recruitment._showScheduleModal = function (applicantName) {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Interview Round</label>';
	html += '<input type="text" id="lms-rec-round" class="lms-input" placeholder="e.g. Technical Round 1"></div>';
	html += '<div class="lms-field"><label>Scheduled Date</label>';
	html += '<input type="date" id="lms-rec-date" class="lms-input"></div>';
	html += '<div class="lms-field"><label>Designation (optional)</label>';
	html += '<input type="text" id="lms-rec-designation" class="lms-input" placeholder="Job designation"></div>';
	html += '<div class="lms-field"><label>Interviewers (comma-separated emails)</label>';
	html += '<input type="text" id="lms-rec-interviewers" class="lms-input" placeholder="manager@company.com"></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Schedule Interview",
		body: html,
		confirmText: "Schedule",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var round = overlay.querySelector("#lms-rec-round").value;
			var date = overlay.querySelector("#lms-rec-date").value;
			var designation = overlay.querySelector("#lms-rec-designation").value;
			var interviewers = overlay.querySelector("#lms-rec-interviewers").value;

			if (!round || !date) {
				lms_portal.toast("Round and date are required.", "danger");
				return false;
			}

			lms_portal.safeCall({
				method: "lms_saas.api.recruitment.schedule_interview",
				args: {
					applicant_name: applicantName,
					interview_round: round,
					scheduled_on: date,
					designation: designation,
					interviewers: interviewers,
				},
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Interview scheduled: " + (res.name || ""), "success");
					lms_recruitment._showApplicantDetail(applicantName);
				},
				error: function () {
					lms_portal.toast("Could not schedule interview.", "danger");
				},
			});
		},
	});
};

lms_recruitment._loadStaffing = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.recruitment.get_staffing_plan",
		callback: function (r) {
			var data = (r && r.message) || {};
			var plans = data.plans || [];
			var actual = data.actual_headcount || 0;
			var branch = data.branch || "—";

			var html = '<section class="lms-grid-4" style="margin-bottom:1rem;">';
			html += lms_recruitment._statCard("Actual Headcount", actual);
			html += lms_recruitment._statCard("Branch", lms_portal.escape(branch));
			html += "</section>";

			if (!plans.length) {
				html += '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📊</div><h3>No staffing plan</h3><p>No active staffing plans for your branch.</p></div></div>';
				content.innerHTML = html;
				return;
			}

			plans.forEach(function (p) {
				html += '<div class="lms-panel" style="margin-bottom:1rem;">';
				html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;">';
				html += '<h3 style="margin:0;">' + lms_portal.escape(p.name) + '</h3>';
				html += '<span class="lms-muted">' + lms_portal.formatDate(p.from_date) + ' → ' + lms_portal.formatDate(p.to_date) + '</span>';
				html += '</div>';
				html += '<div class="lms-summary" style="margin-bottom:0.75rem;">';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Planned Positions</div><div class="lms-summary-value">' + (p.planned_positions || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Open Vacancies</div><div class="lms-summary-value">' + (p.open_vacancies || 0) + '</div></div>';
				html += '<div class="lms-summary-card"><div class="lms-summary-label">Budget</div><div class="lms-summary-value">' + format_currency(p.total_estimated_budget || 0) + '</div></div>';
				html += '</div>';

				var details = p.details || [];
				if (details.length) {
					html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Designation</th><th>Positions</th><th>Vacancies</th><th>Cost/Position</th><th>Total Cost</th></tr></thead><tbody>';
					details.forEach(function (d) {
						html += "<tr>";
						html += "<td><strong>" + lms_portal.escape(d.designation || "—") + "</strong></td>";
						html += "<td>" + (d.no_of_positions || 0) + "</td>";
						html += "<td>" + (d.vacancies || 0) + "</td>";
						html += "<td>" + format_currency(d.estimated_cost_per_position || 0) + "</td>";
						html += "<td>" + format_currency(d.estimated_cost || 0) + "</td>";
						html += "</tr>";
					});
					html += "</tbody></table></div>";
				}
				html += '</div>';
			});

			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load staffing plan.");
		},
	});
};