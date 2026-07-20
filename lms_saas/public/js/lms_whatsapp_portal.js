/* LMS WhatsApp Business portal — send, templates, log, stats */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_whatsapp");
} else {
	window.lms_whatsapp = window.lms_whatsapp || {};
}

lms_whatsapp._currentTab = "send";

lms_whatsapp.init = function () {
	var root = document.getElementById("lms-whatsapp-root");
	if (!root) return;

	var isAdmin = (window.frappe && frappe.boot && frappe.boot.user_roles &&
		(frappe.boot.user_roles.indexOf("System Manager") >= 0 ||
		 frappe.boot.user_roles.indexOf("Administrator") >= 0));

	var tabs = [
		{ id: "send", label: "Send", icon: "📤" },
		{ id: "templates", label: "Templates", icon: "📝" },
		{ id: "log", label: "Log", icon: "📜" },
		{ id: "stats", label: "Stats", icon: "📊" },
	];
	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "WhatsApp Business" }) +
		lms_portal.tabNav(tabs, lms_whatsapp._currentTab) +
		'<div id="lms-wa-tab-content"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_portal.bindTabs({
		root: root,
		tabs: tabs,
		onTab: function (tabId) { lms_whatsapp._currentTab = tabId; lms_whatsapp._showTab(tabId); },
	});

	lms_whatsapp._showTab(lms_whatsapp._currentTab);
};

lms_whatsapp._showTab = function (tabId) {
	var content = document.getElementById("lms-wa-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "send") lms_whatsapp._loadSend(content);
	else if (tabId === "templates") lms_whatsapp._loadTemplates(content);
	else if (tabId === "log") lms_whatsapp._loadLog(content);
	else if (tabId === "stats") lms_whatsapp._loadStats(content);
};


lms_whatsapp._loadSend = function (content) {
	// Load templates for the dropdown first
	lms_portal.safeCall({
		method: "lms_saas.api.whatsapp.get_templates",
		callback: function (r) {
			var templates = (r && r.message && r.message.templates) || [];
			var html = '<div class="lms-panel" style="max-width:600px;">';
			html += '<h3 style="margin:0 0 1rem;">Send WhatsApp Message</h3>';
			html += '<div class="lms-form">';
			html += '<div class="lms-field"><label>Recipient</label>';
			html += '<input type="text" id="lms-wa-recipient" class="lms-input" placeholder="whatsapp:+263771234567"></div>';
			html += '<div class="lms-field"><label>Template (optional)</label>';
			html += '<select id="lms-wa-template" class="lms-input lms-fallback-select">';
			html += '<option value="">— No template —</option>';
			templates.forEach(function (t) {
				html += '<option value="' + lms_portal.escape(t.name) + '">' + lms_portal.escape(t.template_name) + '</option>';
			});
			html += '</select></div>';
			html += '<div class="lms-field"><label>Message</label>';
			html += '<textarea id="lms-wa-message" class="lms-input" rows="5" placeholder="Type your message…"></textarea></div>';
			html += '<div class="lms-field"><label>Loan (optional)</label>';
			html += '<input type="text" id="lms-wa-loan" class="lms-input" placeholder="LOAN-00001"></div>';
			html += '<button type="button" class="lms-btn lms-btn--primary" id="lms-wa-send-btn">Send Message</button>';
			html += '</div></div>';
			content.innerHTML = html;

			var sendBtn = content.querySelector("#lms-wa-send-btn");
			if (sendBtn) {
				sendBtn.addEventListener("click", function () {
					lms_whatsapp._sendMessage();
				});
			}

			// Auto-fill message when template selected
			var templateSel = content.querySelector("#lms-wa-template");
			if (templateSel) {
				templateSel.addEventListener("change", function () {
					var tplName = templateSel.value;
					if (!tplName) return;
					var selected = templates.filter(function (t) { return t.name === tplName; })[0];
					if (selected) {
						content.querySelector("#lms-wa-message").value = selected.template_body || "";
					}
				});
			}
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load templates.");
		},
	});
};

lms_whatsapp._sendMessage = function () {
	var recipient = document.getElementById("lms-wa-recipient").value;
	var message = document.getElementById("lms-wa-message").value;
	var templateName = document.getElementById("lms-wa-template").value;
	var loan = document.getElementById("lms-wa-loan").value;

	if (!recipient || !message) {
		lms_portal.toast("Recipient and message are required.", "danger");
		return;
	}

	var args = { recipient: recipient, message: message };
	if (templateName) args.template_name = templateName;
	if (loan) args.loan = loan;

	lms_portal.safeCall({
		method: "lms_saas.api.whatsapp.send_whatsapp",
		args: args,
		callback: function (r) {
			var res = (r && r.message) || {};
			if (res.ok) {
				lms_portal.toast("Message sent.", "success");
				document.getElementById("lms-wa-recipient").value = "";
				document.getElementById("lms-wa-message").value = "";
				document.getElementById("lms-wa-loan").value = "";
			} else {
				lms_portal.toast("Send failed: " + (res.error || "Unknown error"), "danger");
			}
		},
		error: function () {
			lms_portal.toast("Could not send message.", "danger");
		},
	});
};

lms_whatsapp._loadTemplates = function (content) {
	var isAdmin = (window.frappe && frappe.boot && frappe.boot.user_roles &&
		(frappe.boot.user_roles.indexOf("System Manager") >= 0 ||
		 frappe.boot.user_roles.indexOf("Administrator") >= 0));

	var html = '<div style="margin-bottom:1rem;">';
	if (isAdmin) {
		html += '<button type="button" class="lms-btn lms-btn--primary" id="lms-wa-new-template">+ New Template</button>';
	}
	html += '</div>';
	html += '<div id="lms-wa-templates-list"></div>';
	content.innerHTML = html;

	if (isAdmin) {
		var newBtn = content.querySelector("#lms-wa-new-template");
		if (newBtn) {
			newBtn.addEventListener("click", function () {
				lms_whatsapp._showCreateTemplateModal();
			});
		}
	}

	lms_whatsapp._renderTemplatesList();
};

lms_whatsapp._renderTemplatesList = function () {
	var el = document.getElementById("lms-wa-templates-list");
	if (!el) return;
	el.innerHTML = lms_portal.loading("Loading templates…");

	lms_portal.safeCall({
		method: "lms_saas.api.whatsapp.get_templates",
		callback: function (r) {
			var templates = (r && r.message && r.message.templates) || [];
			if (!templates.length) {
				el.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📝</div><h3>No templates</h3><p>No WhatsApp templates found.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Name</th><th>Category</th><th>Language</th><th>Approved</th><th>Variables</th></tr></thead><tbody>";
			templates.forEach(function (t) {
				var approvedClass = t.is_approved ? "lms-badge--success" : "lms-badge--warning";
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(t.template_name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(t.category || "—") + "</td>";
				html += "<td>" + lms_portal.escape(t.language || "—") + "</td>";
				html += '<td><span class="lms-badge ' + approvedClass + '">' + (t.is_approved ? "Yes" : "No") + "</span></td>";
				html += "<td>" + lms_portal.escape(t.variables || "—") + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			el.innerHTML = html;
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load templates.");
		},
	});
};

lms_whatsapp._showCreateTemplateModal = function () {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Template Name</label>';
	html += '<input type="text" id="lms-wa-tpl-name" class="lms-input" placeholder="Payment Reminder"></div>';
	html += '<div class="lms-field"><label>Template Body</label>';
	html += '<textarea id="lms-wa-tpl-body" class="lms-input" rows="4" placeholder="Dear {{customer_name}}, your payment of {{amount}} is due on {{date}}."></textarea></div>';
	html += '<div style="display:flex;gap:1rem;">';
	html += '<div class="lms-field" style="flex:1;"><label>Category</label>';
	html += '<select id="lms-wa-tpl-category" class="lms-input lms-fallback-select">';
	html += '<option value="Payment Reminder">Payment Reminder</option><option value="Disbursement Notice">Disbursement Notice</option><option value="Welcome">Welcome</option><option value="Marketing">Marketing</option><option value="Support">Support</option>';
	html += '</select></div>';
	html += '<div class="lms-field" style="flex:1;"><label>Language</label>';
	html += '<input type="text" id="lms-wa-tpl-lang" class="lms-input" value="en"></div>';
	html += '</div>';
	html += '<div class="lms-field"><label>Variables</label>';
	html += '<input type="text" id="lms-wa-tpl-vars" class="lms-input" placeholder="customer_name, amount, date"></div>';
	html += '<div class="lms-field"><label>Approved</label>';
	html += '<input type="checkbox" id="lms-wa-tpl-approved"></div>';
	html += '</div>';

	lms_portal.modal({
		title: "New WhatsApp Template",
		body: html,
		confirmText: "Create",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var name = overlay.querySelector("#lms-wa-tpl-name").value;
			var body = overlay.querySelector("#lms-wa-tpl-body").value;
			var category = overlay.querySelector("#lms-wa-tpl-category").value;
			var lang = overlay.querySelector("#lms-wa-tpl-lang").value;
			var vars = overlay.querySelector("#lms-wa-tpl-vars").value;
			var approved = overlay.querySelector("#lms-wa-tpl-approved").checked;

			if (!name || !body || !category) {
				lms_portal.toast("Name, body, and category are required.", "danger");
				return false;
			}

			lms_portal.safeCall({
				method: "lms_saas.api.whatsapp.create_template",
				args: {
					template_name: name,
					template_body: body,
					category: category,
					language: lang,
					is_approved: approved,
					variables: vars,
				},
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Template created: " + (res.template_name || ""), "success");
					lms_whatsapp._renderTemplatesList();
				},
				error: function () {
					lms_portal.toast("Could not create template.", "danger");
				},
			});
		},
	});
};

lms_whatsapp._loadLog = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.whatsapp.get_whatsapp_log",
		callback: function (r) {
			var logs = (r && r.message && r.message.logs) || [];
			if (!logs.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📜</div><h3>No messages</h3><p>No WhatsApp messages logged.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Date</th><th>Recipient</th><th>Loan</th><th>Type</th><th>Preview</th><th>Status</th><th>Read</th></tr></thead><tbody>";
			logs.forEach(function (l) {
				var statusClass = l.status === "Sent" ? "lms-badge--success" : (l.status === "Failed" ? "lms-badge--danger" : "lms-badge--warning");
				html += "<tr>";
				html += "<td>" + lms_portal.formatDate(l.notification_date) + "</td>";
				html += "<td>" + lms_portal.escape(l.recipient || "—") + "</td>";
				html += "<td>" + lms_portal.escape(l.loan || "—") + "</td>";
				html += "<td>" + lms_portal.escape(l.reminder_type || "—") + "</td>";
				html += "<td>" + lms_portal.escape((l.message_preview || "").substring(0, 50)) + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(l.status || "—") + "</span></td>";
				html += "<td>" + (l.read_on ? lms_portal.formatDate(l.read_on) : "—") + "</td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load log.");
		},
	});
};

lms_whatsapp._loadStats = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.whatsapp.get_whatsapp_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = lms_portal.pageStart() +
				lms_portal.kpiStrip([
					{ label: "Total Sent", value: s.total_sent || 0 },
					{ label: "Delivered", value: s.delivered || 0, tone: "success" },
					{ label: "Failed", value: s.failed || 0, tone: "danger" },
					{ label: "Skipped", value: s.skipped || 0, tone: "warning" },
				]) +
				lms_portal.kpiStrip([
					{ label: "Read", value: s.read || 0 },
					{ label: "Delivery Rate", value: (s.delivery_rate || 0) + "%" },
					{ label: "Read Rate", value: (s.read_rate || 0) + "%" },
				]) +
				lms_portal.kpiStrip([
					{ label: "Total Templates", value: s.total_templates || 0 },
					{ label: "Approved Templates", value: s.approved_templates || 0, tone: "success" },
				]) +
				lms_portal.pageEnd();
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load stats.");
		},
	});
};