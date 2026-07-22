/* LMS Training portal — programs, events, my training */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_training");
} else {
	window.lms_training = window.lms_training || {};
}

lms_training._currentTab = "programs";

lms_training.init = function () {
	var root = document.getElementById("lms-training-root");
	if (!root) return;

	var tabs = [
		{ id: "programs", label: "Programs", icon: "book-open" },
		{ id: "events", label: "Events", icon: "calendar" },
		{ id: "mine", label: "My Training", icon: "graduation-cap" },
	];
	var home = window.__lms_home_route || "/lms";
	var html = lms_portal.pageStart() +
		lms_portal.backLink({ href: home, label: "Back" }) +
		lms_portal.tabNav(tabs, lms_training._currentTab) +
		'<div id="lms-training-tab-content"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_portal.bindTabs({
		root: root,
		tabs: tabs,
		onTab: function (tabId) { lms_training._currentTab = tabId; lms_training._showTab(tabId); },
	});

	lms_training._showTab(lms_training._currentTab);
};

lms_training._showTab = function (tabId) {
	var content = document.getElementById("lms-training-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "programs") lms_training._loadPrograms(content);
	else if (tabId === "events") lms_training._loadEvents(content);
	else if (tabId === "mine") lms_training._loadMine(content);
};

lms_training._loadPrograms = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.training.get_training_programs",
		callback: function (r) {
			var msg = r && r.message;
			if (msg && msg._missing) {
				content.innerHTML = lms_portal.moduleUnavailable({
					icon: "book-open",
					title: "Training module not ready",
					message: msg.message || "Training Program tables are not available on this site.",
					hint: "Install/sync HRMS Training doctypes with a standard bench migrate, then refresh. This page never hangs on Loading.",
					ctaLabel: "Back to dashboard",
				});
				return;
			}
			var programs = (msg && msg.programs) || [];
			if (!programs.length) {
				content.innerHTML = lms_portal.emptyPanel("book-open", "No programs yet", "No training programs are published for your organisation. Ask HR to create a Training Program in Desk.");
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Program</th><th>Status</th><th>Description</th><th>Created</th></tr></thead><tbody>";
			programs.forEach(function (p) {
				var statusClass = p.status === "Active" || p.status === "Published" ? "lms-badge--success" : "";
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(p.program_name || p.name) + "</strong></td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(p.status || "") + "</span></td>";
				html += "<td>" + lms_portal.escape((p.description || "").slice(0, 80)) + "</td>";
				html += "<td>" + lms_portal.formatDate(p.created_on || p.creation) + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load training programs.");
		},
	});
};

lms_training._loadEvents = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.training.get_training_events",
		args: { upcoming: true },
		callback: function (r) {
			var msg = r && r.message;
			if (msg && msg._missing) {
				content.innerHTML = lms_portal.moduleUnavailable({
					icon: "calendar",
					title: "Training module not ready",
					message: msg.message || "Training Event tables are not available on this site.",
					hint: "Install/sync HRMS Training doctypes with a standard bench migrate, then refresh.",
					ctaLabel: "Back to dashboard",
				});
				return;
			}
			var events = (msg && msg.events) || [];
			if (!events.length) {
				content.innerHTML = lms_portal.emptyPanel("calendar", "No upcoming events", "When HR schedules a Training Event, it will appear here for registration.");
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Event</th><th>Program</th><th>Start</th><th>End</th><th>Location</th><th>Registered</th><th>Status</th><th>Action</th></tr></thead><tbody>";
			events.forEach(function (e) {
				var statusClass = e.status === "Scheduled" ? "lms-badge--info" : (e.status === "Completed" ? "lms-badge--success" : "");
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(e.event_name || e.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(e.training_program || "—") + "</td>";
				html += "<td>" + lms_portal.formatDate(e.start_time) + "</td>";
				html += "<td>" + lms_portal.formatDate(e.end_time) + "</td>";
				html += "<td>" + lms_portal.escape(e.location || "—") + "</td>";
				html += "<td>" + (e.registered_count || 0) + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(e.status || "") + "</span></td>";
				html += '<td><button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-tr-register" data-name="' + lms_portal.escape(e.name) + '">Register</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-tr-register").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_training._registerForEvent(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load training events.");
		},
	});
};

lms_training._registerForEvent = function (eventName) {
	lms_portal.safeCall({
		method: "lms_saas.api.training.register_for_event",
		args: { event_name: eventName },
		callback: function (r) {
			var res = (r && r.message) || {};
			if (res.already_registered) {
				lms_portal.toast("You are already registered.", "info");
			} else {
				lms_portal.toast("Registered successfully!", "success");
			}
			lms_training._showTab("events");
		},
		error: function () {
			lms_portal.toast("Could not register for event.", "danger");
		},
	});
};

lms_training._loadMine = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.training.get_my_training_results",
		callback: function (r) {
			var msg = r && r.message;
			if (msg && msg._missing) {
				content.innerHTML = lms_portal.moduleUnavailable({
					icon: "graduation-cap",
					title: "Training module not ready",
					message: msg.message || "Training Result tables are not available on this site.",
					ctaLabel: "Back to dashboard",
				});
				return;
			}
			var results = (msg && msg.results) || [];
			var html = lms_portal.kpiStrip([
				{ label: "Training Completed", value: results.length, tone: "success" },
			]);

			if (!results.length) {
				html += lms_portal.emptyPanel("graduation-cap", "No results yet", "Complete a registered training event and your results will show here.");
				content.innerHTML = html;
				return;
			}

			var body = '<div class="lms-data-table__wrap"><table class="lms-data-table">';
			body += "<thead><tr><th>Event</th><th>Status</th><th>Result</th><th>Score</th><th>Date</th><th>Feedback</th></tr></thead><tbody>";
			results.forEach(function (res) {
				var statusClass = res.status === "Completed" ? "lms-badge--success" : (res.status === "Failed" ? "lms-badge--danger" : "lms-badge--warning");
				body += "<tr>";
				body += "<td><strong>" + lms_portal.escape(res.training_event || res.name) + "</strong></td>";
				body += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(res.status || "") + "</span></td>";
				body += "<td>" + lms_portal.escape(res.result || "—") + "</td>";
				body += "<td>" + (res.score || "—") + "</td>";
				body += "<td>" + lms_portal.formatDate(res.posting_date) + "</td>";
				body += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-tr-feedback" data-event="' + lms_portal.escape(res.training_event || res.name) + '">Give Feedback</button></td>';
				body += "</tr>";
			});
			body += "</tbody></table></div>";
			html += lms_portal.panel({ body: body });
			content.innerHTML = html;

			content.querySelectorAll(".lms-tr-feedback").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_training._showFeedbackModal(btn.getAttribute("data-event"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load your training results.");
		},
	});
};

lms_training._showFeedbackModal = function (eventName) {
	// First check if feedback already exists
	lms_portal.safeCall({
		method: "lms_saas.api.training.get_training_feedback",
		args: { event_name: eventName },
		callback: function (r) {
			var data = (r && r.message) || {};
			if (data.already_submitted) {
				lms_portal.toast("You have already submitted feedback for this event.", "info");
				return;
			}
			lms_training._renderFeedbackForm(eventName);
		},
	});
};

lms_training._renderFeedbackForm = function (eventName) {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Rating</label>';
	html += '<select id="lms-tr-rating" class="lms-input lms-fallback-select">';
	html += '<option value="1">1 — Poor</option>';
	html += '<option value="2">2 — Fair</option>';
	html += '<option value="3" selected>3 — Good</option>';
	html += '<option value="4">4 — Very Good</option>';
	html += '<option value="5">5 — Excellent</option>';
	html += '</select></div>';
	html += '<div class="lms-field"><label>Feedback</label>';
	html += '<textarea id="lms-tr-feedback" class="lms-input" rows="4" placeholder="Share your thoughts on this training…"></textarea></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Training Feedback",
		body: html,
		confirmText: "Submit",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var rating = overlay.querySelector("#lms-tr-rating").value;
			var feedback = overlay.querySelector("#lms-tr-feedback").value;
			if (!feedback) {
				lms_portal.toast("Feedback is required.", "danger");
				return false;
			}
			lms_portal.safeCall({
				method: "lms_saas.api.training.submit_training_feedback",
				args: { event_name: eventName, feedback: feedback, rating: rating },
				callback: function () {
					lms_portal.toast("Feedback submitted.", "success");
					lms_training._showTab("mine");
				},
				error: function () {
					lms_portal.toast("Could not submit feedback.", "danger");
				},
			});
		},
	});
};