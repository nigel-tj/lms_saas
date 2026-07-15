/* LMS Helpdesk portal — ticket queue, create, reply, stats */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_helpdesk");
} else {
	window.lms_helpdesk = window.lms_helpdesk || {};
}

lms_helpdesk.init = function () {
	var root = document.getElementById("lms-helpdesk-root");
	if (!root) return;

	var persona = (window.frappe && frappe.boot && frappe.boot.lms_persona) || "";
	var isBorrower = (window.frappe && frappe.boot && frappe.boot.user_roles &&
		frappe.boot.user_roles.indexOf("Customer") >= 0 &&
		frappe.boot.user_roles.indexOf("LMS Portal Staff") < 0);

	var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;">';
	html += '<h2 style="margin:0;font-size:var(--lms-fs-xl);font-weight:700;">' + (isBorrower ? "My Support Tickets" : "Support Desk") + '</h2>';
	html += '<button type="button" class="lms-btn lms-btn--primary" id="lms-hd-new">+ New Ticket</button>';
	html += '</div>';
	html += '<div id="lms-hd-stats" style="margin-bottom:1rem;"></div>';
	html += '<div id="lms-hd-queue"></div>';
	root.innerHTML = html;

	lms_helpdesk._loadStats(isBorrower);
	lms_helpdesk._loadQueue(isBorrower);

	var btn = root.querySelector("#lms-hd-new");
	if (btn) {
		btn.addEventListener("click", function () {
			lms_helpdesk._showCreateModal();
		});
	}
};

lms_helpdesk._loadStats = function (isBorrower) {
	var el = document.getElementById("lms-hd-stats");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.helpdesk.get_ticket_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = '<section class="lms-grid-4">';
			html += lms_helpdesk._statCard("Total", s.total || 0);
			html += lms_helpdesk._statCard("Open", s.open || 0, "warning");
			html += lms_helpdesk._statCard("Replied", s.replied || 0, "info");
			html += lms_helpdesk._statCard("Closed", s.closed || 0, "success");
			html += "</section>";
			el.innerHTML = html;
		},
	});
};

lms_helpdesk._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_helpdesk._loadQueue = function (isBorrower) {
	var el = document.getElementById("lms-hd-queue");
	if (!el) return;
	el.innerHTML = lms_portal.loading("Loading tickets…");

	var method = isBorrower
		? "lms_saas.api.helpdesk.get_my_tickets"
		: "lms_saas.api.helpdesk.get_ticket_queue";

	lms_portal.safeCall({
		method: method,
		callback: function (r) {
			var tickets = (r && r.message && r.message.tickets) || [];
			lms_helpdesk._renderQueue(el, tickets);
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load tickets.");
		},
	});
};

lms_helpdesk._renderQueue = function (el, tickets) {
	if (!tickets.length) {
		el.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">🎫</div><h3>No tickets</h3><p>No support tickets right now.</p></div></div>';
		return;
	}

	var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Ticket</th><th>Subject</th><th>Priority</th><th>Status</th><th>Date</th><th>Action</th></tr></thead><tbody>";
	tickets.forEach(function (t) {
		var priorityClass = t.priority === "High" ? "lms-badge--danger" : (t.priority === "Medium" ? "lms-badge--warning" : "");
		var statusClass = t.status === "Closed" ? "lms-badge--success" : (t.status === "Open" ? "lms-badge--warning" : "");
		html += "<tr>";
		html += "<td><strong>" + lms_portal.escape(t.name) + "</strong></td>";
		html += "<td>" + lms_portal.escape(t.subject) + "</td>";
		html += '<td><span class="lms-badge ' + priorityClass + '">' + lms_portal.escape(t.priority || "") + "</span></td>";
		html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(t.status || "") + "</span></td>";
		html += "<td>" + lms_portal.formatDate(t.opening_date) + "</td>";
		html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-hd-view" data-name="' + lms_portal.escape(t.name) + '">View</button></td>';
		html += "</tr>";
	});
	html += "</tbody></table></div></div>";
	el.innerHTML = html;

	el.querySelectorAll(".lms-hd-view").forEach(function (btn) {
		btn.addEventListener("click", function () {
			lms_helpdesk._showTicketDetail(btn.getAttribute("data-name"));
		});
	});
};

lms_helpdesk._showCreateModal = function () {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Subject</label>';
	html += '<input type="text" id="lms-hd-subject" class="lms-input" placeholder="Brief description of your issue"></div>';
	html += '<div class="lms-field"><label>Description</label>';
	html += '<textarea id="lms-hd-desc" class="lms-input" rows="4" placeholder="Describe your issue in detail…"></textarea></div>';
	html += '<div style="display:flex;gap:1rem;">';
	html += '<div class="lms-field" style="flex:1;"><label>Priority</label>';
	html += '<select id="lms-hd-priority" class="lms-input lms-fallback-select">';
	html += '<option value="Low">Low</option><option value="Medium" selected>Medium</option><option value="High">High</option>';
	html += '</select></div>';
	html += '<div class="lms-field" style="flex:1;"><label>Type</label>';
	html += '<select id="lms-hd-type" class="lms-input lms-fallback-select">';
	html += '<option value="">General</option><option value="Payment Issue">Payment Issue</option>';
	html += '<option value="Statement Request">Statement Request</option><option value="Complaint">Complaint</option>';
	html += '<option value="Account Update">Account Update</option>';
	html += '</select></div></div>';
	html += '</div>';

	lms_portal.modal({
		title: "New Support Ticket",
		body: html,
		confirmText: "Submit",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var subject = overlay.querySelector("#lms-hd-subject").value;
			var desc = overlay.querySelector("#lms-hd-desc").value;
			var priority = overlay.querySelector("#lms-hd-priority").value;
			var type = overlay.querySelector("#lms-hd-type").value;

			if (!subject || !desc) {
				lms_portal.toast("Subject and description are required.", "danger");
				return;
			}

			lms_portal.safeCall({
				method: "lms_saas.api.helpdesk.create_ticket",
				args: { subject: subject, description: desc, priority: priority, issue_type: type },
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Ticket created: " + (res.name || ""), "success");
					lms_helpdesk._loadStats();
					lms_helpdesk._loadQueue();
				},
				error: function () {
					lms_portal.toast("Could not create ticket.", "danger");
				},
			});
		},
	});
};

lms_helpdesk._showTicketDetail = function (name) {
	lms_portal.safeCall({
		method: "lms_saas.api.helpdesk.get_ticket_detail",
		args: { ticket_name: name },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_helpdesk._renderTicketDetail(data);
		},
	});
};

lms_helpdesk._renderTicketDetail = function (data) {
	var t = data.ticket || {};
	var comms = data.communications || [];

	var html = '<div class="lms-form">';
	html += '<h3 style="margin:0 0 0.5rem;">' + lms_portal.escape(t.subject || "") + '</h3>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(t.status || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Priority</div><div class="lms-summary-value">' + lms_portal.escape(t.priority || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Opened</div><div class="lms-summary-value">' + lms_portal.formatDate(t.opening_date) + '</div></div>';
	html += '</div>';
	html += '<p style="margin:0 0 1rem;">' + lms_portal.escape(t.description || "") + '</p>';

	if (comms.length) {
		html += '<h4 style="margin:1rem 0 0.5rem;">Conversation</h4>';
		comms.forEach(function (c) {
			html += '<div class="lms-panel" style="padding:0.75rem;margin-bottom:0.5rem;">';
			html += '<div style="display:flex;justify-content:space-between;margin-bottom:0.25rem;">';
			html += '<strong style="font-size:var(--lms-fs-sm);">' + lms_portal.escape(c.sender) + '</strong>';
			html += '<span class="lms-muted" style="font-size:var(--lms-fs-xs);">' + lms_portal.formatDate(c.creation) + '</span>';
			html += '</div>';
			html += '<p style="margin:0;font-size:var(--lms-fs-sm);">' + lms_portal.escape(c.content) + '</p>';
			html += '</div>';
		});
	}

	html += '<div class="lms-field" style="margin-top:1rem;"><textarea id="lms-hd-reply" class="lms-input" rows="3" placeholder="Type a reply… (Ctrl+Enter to send)"></textarea></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Ticket " + (t.name || ""),
		body: html,
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});

	var replyBox = document.querySelector("#lms-hd-reply");
	if (replyBox) {
		replyBox.addEventListener("keydown", function (e) {
			if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
				var content = replyBox.value.trim();
				if (!content) return;
				lms_portal.safeCall({
					method: "lms_saas.api.helpdesk.reply_to_ticket",
					args: { ticket_name: t.name, content: content },
					callback: function () {
						replyBox.value = "";
						lms_portal.toast("Reply sent.", "success");
						lms_helpdesk._showTicketDetail(t.name);
					},
				});
			}
		});
	}
};