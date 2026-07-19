/* LMS Task Management portal — Kanban board, task CRUD, comments */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_tasks");
} else {
	window.lms_tasks = window.lms_tasks || {};
}

lms_tasks.init = function () {
	var root = document.getElementById("lms-tasks-root");
	if (!root) return;

	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "Tasks", actions: [{ label: "+ New Task", id: "lms-task-new", primary: true }] }) +
		'<div id="lms-task-stats"></div>' +
		'<div id="lms-task-board"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_tasks._loadStats();
	lms_tasks._loadBoard();

	var btn = root.querySelector("#lms-task-new");
	if (btn) {
		btn.addEventListener("click", function () {
			lms_tasks._showCreateModal();
		});
	}
};

lms_tasks._loadStats = function () {
	var el = document.getElementById("lms-task-stats");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.tasks.get_task_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			el.innerHTML = lms_portal.kpiStrip([
				{ label: "Total", value: s.total || 0 },
				{ label: "In Progress", value: s.in_progress || 0 },
				{ label: "Overdue", value: s.overdue || 0, tone: "danger" },
				{ label: "Completed", value: s.completed || 0, tone: "success" },
			]);
		},
	});
};

lms_tasks._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
};

lms_tasks._loadBoard = function () {
	var el = document.getElementById("lms-task-board");
	if (!el) return;
	el.innerHTML = lms_portal.loading("Loading board…");

	lms_portal.safeCall({
		method: "lms_saas.api.tasks.get_task_board",
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_tasks._renderBoard(el, data);
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load task board.");
		},
	});
};

lms_tasks._renderBoard = function (el, data) {
	var columns = data.columns || [];
	var board = data.board || {};

	// Grid layout with auto-fit so columns wrap into multiple rows on
	// narrow viewports (no horizontal scroll). Each column min 240px;
	// grows to fill available space up to ~360px.
	var html = '<div class="lms-kanban-board">';
	columns.forEach(function (col) {
		var tasks = board[col.key] || [];
		html += '<div class="lms-kanban-col">';
		html += '<div class="lms-kanban-col-header">';
		html += '<strong>' + lms_portal.escape(col.label) + '</strong>';
		html += '<span class="lms-badge">' + tasks.length + '</span>';
		html += '</div>';
		html += '<div class="lms-kanban-col-body">';
		if (!tasks.length) {
			html += '<p class="lms-muted lms-kanban-empty">No tasks</p>';
		} else {
			tasks.forEach(function (t) {
				var priorityClass = t.priority === "High" ? "lms-badge--danger" : (t.priority === "Medium" ? "lms-badge--warning" : "");
				html += '<div class="lms-kanban-card lms-panel" data-task="' + lms_portal.escape(t.name) + '" data-status="' + col.key + '">';
				html += '<div class="lms-kanban-card__title">' + lms_portal.escape(t.subject) + '</div>';
				if (t.reference_name) {
					html += '<div class="lms-muted lms-kanban-card__ref">' + lms_portal.escape(t.reference_type || "") + ": " + lms_portal.escape(t.reference_name) + '</div>';
				}
				html += '<div class="lms-kanban-card__footer">';
				if (t.priority) {
					html += '<span class="lms-badge ' + priorityClass + '">' + lms_portal.escape(t.priority) + '</span>';
				}
				if (t.exp_end_date) {
					html += '<span class="lms-muted lms-kanban-card__date">' + lms_portal.formatDate(t.exp_end_date) + '</span>';
				}
				html += '</div>';
				html += '</div>';
			});
		}
		html += '</div></div>';
	});
	html += '</div>';
	el.innerHTML = html;

	// Bind card clicks
	el.querySelectorAll(".lms-kanban-card").forEach(function (card) {
		card.addEventListener("click", function () {
			lms_tasks._showTaskDetail(card.getAttribute("data-task"));
		});
	});
};

lms_tasks._showCreateModal = function () {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Subject</label>';
	html += '<input type="text" id="lms-task-subject" class="lms-input" placeholder="Task title"></div>';
	html += '<div class="lms-field"><label>Description</label>';
	html += '<textarea id="lms-task-desc" class="lms-input" rows="3"></textarea></div>';
	html += '<div style="display:flex;gap:1rem;">';
	html += '<div class="lms-field" style="flex:1;"><label>Priority</label>';
	html += '<select id="lms-task-priority" class="lms-input lms-fallback-select">';
	html += '<option value="Low">Low</option><option value="Medium" selected>Medium</option><option value="High">High</option>';
	html += '</select></div>';
	html += '<div class="lms-field" style="flex:1;"><label>Due date</label>';
	html += '<input type="date" id="lms-task-due" class="lms-input"></div>';
	html += '</div>';
	html += '<div class="lms-field"><label>Link to loan (optional)</label>';
	html += '<input type="text" id="lms-task-loan" class="lms-input" placeholder="LOAN-00001"></div>';
	html += '</div>';

	lms_portal.modal({
		title: "New Task",
		body: html,
		confirmText: "Create",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var subject = overlay.querySelector("#lms-task-subject").value;
			var desc = overlay.querySelector("#lms-task-desc").value;
			var priority = overlay.querySelector("#lms-task-priority").value;
			var due = overlay.querySelector("#lms-task-due").value;
			var loan = overlay.querySelector("#lms-task-loan").value;

			if (!subject) {
				lms_portal.toast("Subject is required.", "danger");
				return;
			}

			var args = { subject: subject, description: desc, priority: priority };
			if (due) args.exp_end_date = due;
			if (loan) {
				args.reference_type = "Loan";
				args.reference_name = loan;
			}

			lms_portal.safeCall({
				method: "lms_saas.api.tasks.create_task",
				args: args,
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Task created: " + (res.subject || ""), "success");
					lms_tasks._loadStats();
					lms_tasks._loadBoard();
				},
				error: function () {
					lms_portal.toast("Could not create task.", "danger");
				},
			});
		},
	});
};

lms_tasks._showTaskDetail = function (taskName) {
	lms_portal.safeCall({
		method: "lms_saas.api.tasks.get_task_detail",
		args: { task_name: taskName },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_tasks._renderTaskDetail(data);
		},
	});
};

lms_tasks._renderTaskDetail = function (data) {
	var t = data.task || {};
	var comments = data.comments || [];

	var html = '<div class="lms-form">';
	html += '<h3 style="margin:0 0 0.5rem;">' + lms_portal.escape(t.subject || "") + '</h3>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(t.status || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Priority</div><div class="lms-summary-value">' + lms_portal.escape(t.priority || "") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Due</div><div class="lms-summary-value">' + lms_portal.formatDate(t.exp_end_date) + '</div></div>';
	html += '</div>';
	if (t.description) {
		html += '<p style="margin:0 0 1rem;">' + lms_portal.escape(t.description) + '</p>';
	}
	if (t.reference_name) {
		html += '<p class="lms-muted">Linked: ' + lms_portal.escape(t.reference_type || "") + ' ' + lms_portal.escape(t.reference_name) + '</p>';
	}

	// Status changer
	html += '<div class="lms-field" style="margin:1rem 0;"><label>Change status</label>';
	html += '<select id="lms-task-status-change" class="lms-input lms-fallback-select">';
	["Open", "Working", "Pending Review", "Completed", "Cancelled"].forEach(function (s) {
		var sel = s === t.status ? " selected" : "";
		html += '<option value="' + s + '"' + sel + '>' + s + '</option>';
	});
	html += '</select></div>';

	// Comments
	html += '<h4 style="margin:1.5rem 0 0.5rem;">Comments</h4>';
	html += '<div id="lms-task-comments" style="margin-bottom:1rem;">';
	comments.forEach(function (c) {
		html += '<div class="lms-panel" style="padding:0.75rem;margin-bottom:0.5rem;">';
		html += '<div style="display:flex;justify-content:space-between;margin-bottom:0.25rem;">';
		html += '<strong style="font-size:var(--lms-fs-sm);">' + lms_portal.escape(c.comment_by) + '</strong>';
		html += '<span class="lms-muted" style="font-size:var(--lms-fs-xs);">' + lms_portal.formatDate(c.creation) + '</span>';
		html += '</div>';
		html += '<p style="margin:0;font-size:var(--lms-fs-sm);">' + lms_portal.escape(c.content) + '</p>';
		html += '</div>';
	});
	html += '</div>';
	html += '<div class="lms-field"><textarea id="lms-task-new-comment" class="lms-input" rows="2" placeholder="Add a comment…"></textarea></div>';
	html += '</div>';

	lms_portal.modal({
		title: "Task Detail",
		body: html,
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});

	// Bind status change
	var statusSel = document.querySelector("#lms-task-status-change");
	if (statusSel) {
		statusSel.addEventListener("change", function () {
			lms_portal.safeCall({
				method: "lms_saas.api.tasks.update_task_status",
				args: { task_name: t.name, status: this.value },
				callback: function () {
					lms_portal.toast("Status updated.", "success");
					lms_tasks._loadStats();
					lms_tasks._loadBoard();
				},
			});
		});
	}

	// Bind comment submit (on Ctrl+Enter)
	var commentBox = document.querySelector("#lms-task-new-comment");
	if (commentBox) {
		commentBox.addEventListener("keydown", function (e) {
			if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
				var content = commentBox.value.trim();
				if (!content) return;
				lms_portal.safeCall({
					method: "lms_saas.api.tasks.add_comment",
					args: { task_name: t.name, content: content },
					callback: function () {
						commentBox.value = "";
						lms_portal.toast("Comment added.", "success");
						lms_tasks._showTaskDetail(t.name);
					},
				});
			}
		});
	}
};