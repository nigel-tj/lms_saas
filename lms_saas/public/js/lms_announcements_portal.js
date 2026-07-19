/* LMS Announcements portal — list, acknowledge, create (admin) */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_announcements");
} else {
	window.lms_announcements = window.lms_announcements || {};
}

lms_announcements.init = function () {
	var root = document.getElementById("lms-announcements-root");
	if (!root) return;

	// Check if user is admin (show create button)
	var isAdmin = (window.frappe && frappe.boot && frappe.boot.user_roles &&
		(frappe.boot.user_roles.indexOf("System Manager") >= 0 ||
		 frappe.boot.user_roles.indexOf("Administrator") >= 0));

	var actions = isAdmin ? [{ label: "+ New Announcement", id: "lms-ann-new", primary: true }] : [];
	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "Announcements", actions: actions }) +
		'<div id="lms-ann-list"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_announcements._loadList();

	if (isAdmin) {
		var btn = root.querySelector("#lms-ann-new");
		if (btn) {
			btn.addEventListener("click", function () {
				lms_announcements._showCreateModal();
			});
		}
	}
};

lms_announcements._loadList = function () {
	var container = document.getElementById("lms-ann-list");
	if (!container) return;
	container.innerHTML = lms_portal.loading("Loading announcements…");

	lms_portal.safeCall({
		method: "lms_saas.api.announcements.get_announcements",
		callback: function (r) {
			var items = (r && r.message && r.message.announcements) || [];
			lms_announcements._renderList(container, items);
		},
		error: function () {
			container.innerHTML = lms_portal.error("Could not load announcements.");
		},
	});
};

lms_announcements._renderList = function (el, items) {
	if (!items.length) {
		el.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📢</div><h3>No announcements</h3><p>There are no active announcements right now.</p></div></div>';
		return;
	}

	var html = '<div class="lms-stack">';
	items.forEach(function (ann) {
		var date = lms_portal.formatDate(ann.publish_date);
		var ackBadge = "";
		if (ann.requires_acknowledgement && !ann.acknowledged) {
			ackBadge = ' <span class="lms-badge lms-badge--warning">Action required</span>';
		} else if (ann.acknowledged) {
			ackBadge = ' <span class="lms-badge lms-badge--success">✓ Acknowledged</span>';
		}

		html += '<div class="lms-panel">';
		html += '<div class="lms-section-header"><h3 style="margin:0;">' + lms_portal.escape(ann.title) + ackBadge + '</h3>';
		html += '<span class="lms-muted">' + date + '</span></div>';
		html += '<div class="lms-ann-body">' + (ann.body || "") + "</div>";

		if (ann.requires_acknowledgement && !ann.acknowledged) {
			html += '<div style="margin-top:1rem;">';
			html += '<button type="button" class="lms-btn lms-btn--primary lms-btn--sm lms-ann-ack" data-name="' + lms_portal.escape(ann.name) + '">Acknowledge</button>';
			html += '</div>';
		}

		html += '</div>';
	});
	html += '</div>'; // .lms-stack
	el.innerHTML = html;

	// Bind acknowledge buttons
	el.querySelectorAll(".lms-ann-ack").forEach(function (btn) {
		btn.addEventListener("click", function () {
			var name = btn.getAttribute("data-name");
			btn.disabled = true;
			btn.textContent = "Acknowledging…";
			lms_portal.safeCall({
				method: "lms_saas.api.announcements.acknowledge_announcement",
				args: { announcement_name: name },
				callback: function () {
					lms_portal.toast("Acknowledged.", "success");
					lms_announcements._loadList();
				},
				error: function () {
					btn.disabled = false;
					btn.textContent = "Acknowledge";
					lms_portal.toast("Could not acknowledge.", "danger");
				},
			});
		});
	});
};

lms_announcements._showCreateModal = function () {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Title</label>';
	html += '<input type="text" id="lms-ann-title" class="lms-input" placeholder="Announcement title"></div>';
	html += '<div class="lms-field"><label>Body</label>';
	html += '<textarea id="lms-ann-body" class="lms-input" rows="5" placeholder="Announcement content…"></textarea></div>';
	html += '<div class="lms-field"><label>Target</label>';
	html += '<select id="lms-ann-target" class="lms-input lms-fallback-select">';
	html += '<option value="All Staff">All Staff</option>';
	html += '<option value="Admin">Admins only</option>';
	html += '<option value="Branch Manager">Branch Managers</option>';
	html += '<option value="Loan Officer">Loan Officers</option>';
	html += '<option value="Collector">Collectors</option>';
	html += '<option value="Borrower">Borrowers</option>';
	html += '</select></div>';
	html += '<div class="lms-field"><label>Requires acknowledgement</label>';
	html += '<input type="checkbox" id="lms-ann-ack-req"></div>';
	html += '</div>';

	lms_portal.modal({
		title: "New Announcement",
		body: html,
		confirmText: "Publish",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var title = overlay.querySelector("#lms-ann-title").value;
			var body = overlay.querySelector("#lms-ann-body").value;
			var target = overlay.querySelector("#lms-ann-target").value;
			var ackReq = overlay.querySelector("#lms-ann-ack-req").checked;

			if (!title || !body) {
				lms_portal.toast("Title and body are required.", "danger");
				return;
			}

			lms_portal.safeCall({
				method: "lms_saas.api.announcements.create_announcement",
				args: {
					title: title,
					body: body,
					target_persona: target,
					requires_acknowledgement: ackReq,
				},
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Published: " + (res.title || ""), "success");
					lms_announcements._loadList();
				},
				error: function () {
					lms_portal.toast("Could not publish.", "danger");
				},
			});
		},
	});
};