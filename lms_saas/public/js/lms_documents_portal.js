/* LMS Document Center portal — categories, document list, expiry alerts */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_documents");
} else {
	window.lms_documents = window.lms_documents || {};
}

lms_documents.init = function () {
	var root = document.getElementById("lms-documents-root");
	if (!root) return;

	// Header panel with category filter + upload + refresh action.
	var controls =
		'<select id="lms-doc-cat-filter" class="lms-input lms-fallback-select"><option value="">All Categories</option></select>' +
		'<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" id="lms-doc-upload">Upload</button>' +
		'<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" id="lms-doc-refresh">Refresh</button>';
	var html = lms_portal.pageStart() +
		lms_portal.panel({ title: "Document Center", controls: controls }) +
		'<div id="lms-doc-stats"></div>' +
		'<div id="lms-doc-list"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_documents._loadStats();
	lms_documents._loadCategories();
	lms_documents._loadDocuments("");

	var refreshBtn = root.querySelector("#lms-doc-refresh");
	if (refreshBtn) {
		refreshBtn.addEventListener("click", function () {
			var cat = root.querySelector("#lms-doc-cat-filter").value;
			lms_documents._loadDocuments(cat);
		});
	}
	var catFilter = root.querySelector("#lms-doc-cat-filter");
	if (catFilter) {
		catFilter.addEventListener("change", function () {
			lms_documents._loadDocuments(this.value);
		});
	}
	var uploadBtn = root.querySelector("#lms-doc-upload");
	if (uploadBtn) {
		uploadBtn.addEventListener("click", function () {
			lms_documents._openUploadModal();
		});
	}
};

lms_documents._openUploadModal = function () {
	var body =
		'<div class="lms-form">' +
		'<label>File<input type="file" id="lms-doc-file" class="lms-input"></label>' +
		'<label>Category<input type="text" id="lms-doc-category" class="lms-input" placeholder="Optional category name"></label>' +
		'<p class="lms-muted" style="margin:0;">Files attach to the Document Center. Link to a borrower or loan from Desk if needed.</p>' +
		"</div>";
	var dlg = LMSModal.open({
		title: "Upload document",
		body: body,
		actions: [
			{ label: "Cancel", value: false },
			{ label: "Upload", value: true, primary: true },
		],
	});
	var dlgRoot = (dlg && dlg.dialog) || null;
	dlg.then(function (submit) {
		if (!submit) return;
		var root = dlgRoot || document.body;
		var input = root.querySelector ? root.querySelector("#lms-doc-file") : null;
		var catInput = root.querySelector ? root.querySelector("#lms-doc-category") : null;
		var file = input && input.files && input.files[0];
		if (!file) {
			lms_portal.toast("Choose a file first.", "warning");
			return;
		}
		var cat = (catInput && catInput.value) || "";
		var fd = new FormData();
		fd.append("file", file, file.name);
		fd.append("is_private", "1");
		fd.append("folder", "Home");
		fetch("/api/method/upload_file", {
			method: "POST",
			headers: { "X-Frappe-CSRF-Token": (frappe.csrf_token || "") },
			body: fd,
			credentials: "same-origin",
		})
			.then(function (res) { return res.json(); })
			.then(function (payload) {
				var fileUrl = (payload && payload.message && payload.message.file_url) || "";
				if (!fileUrl) throw new Error("Upload failed");
				return new Promise(function (resolve, reject) {
					frappe.call({
						method: "lms_saas.api.documents_center.upload_document",
						args: { file_url: fileUrl, category: cat || null },
						callback: function (r) { resolve(r); },
						error: reject,
					});
				});
			})
			.then(function () {
				lms_portal.toast("Document uploaded.", "success");
				lms_documents._loadDocuments((document.getElementById("lms-doc-cat-filter") || {}).value || "");
				lms_documents._loadStats();
			})
			.catch(function () {
				lms_portal.toast("Upload failed.", "danger");
			});
	});
};

lms_documents._loadStats = function () {
	var el = document.getElementById("lms-doc-stats");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.documents_center.get_document_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			el.innerHTML = lms_portal.kpiStrip([
				{ label: "Total Documents", value: s.total_documents || 0 },
				{ label: "Categories", value: s.categories || 0 },
				{ label: "Expiring (30d)", value: s.expiring_30_days || 0, tone: "warning" },
				{ label: "Expired", value: s.expired || 0, tone: "danger" },
			]);
		},
	});
};

lms_documents._loadCategories = function () {
	lms_portal.safeCall({
		method: "lms_saas.api.documents_center.get_categories",
		callback: function (r) {
			var cats = (r && r.message && r.message.categories) || [];
			var sel = document.getElementById("lms-doc-cat-filter");
			if (!sel) return;
			cats.forEach(function (c) {
				var opt = document.createElement("option");
				opt.value = c.name;
				opt.textContent = c.category_name;
				sel.appendChild(opt);
			});
		},
	});
};

lms_documents._loadDocuments = function (category) {
	var el = document.getElementById("lms-doc-list");
	if (!el) return;
	el.innerHTML = lms_portal.loading("Loading documents…");

	lms_portal.safeCall({
		method: "lms_saas.api.documents_center.get_documents",
		args: { category: category || "" },
		callback: function (r) {
			var docs = (r && r.message && r.message.documents) || [];
			lms_documents._renderList(el, docs);
		},
		error: function () {
			el.innerHTML = lms_portal.error("Could not load documents.");
		},
	});
};

lms_documents._renderList = function (el, docs) {
	if (!docs.length) {
		el.innerHTML = lms_portal.emptyPanel("📁", "No documents", "Documents will appear here once uploaded.");
		return;
	}

	var body = '<div class="lms-data-table__wrap"><table class="lms-data-table">';
	body += "<thead><tr><th>Name</th><th>Category</th><th>Linked To</th><th>Size</th><th>Modified</th><th>Status</th><th>Action</th></tr></thead><tbody>";
	docs.forEach(function (d) {
		var size = d.file_size ? (d.file_size / 1024).toFixed(1) + " KB" : "—";
		var linked = d.linked_to_label || (
			d.attached_to_doctype
				? (d.attached_to_name && String(d.attached_to_name).indexOf("#####") === -1
					? d.attached_to_doctype + ": " + d.attached_to_name
					: d.attached_to_doctype)
				: "—"
		);
		var status = "Active";
		var statusClass = "lms-badge--success";
		if (d.is_expired) {
			status = "Expired";
			statusClass = "lms-badge--danger";
		} else if (d.expiry_date) {
			status = "Expires " + lms_portal.formatDate(d.expiry_date);
			statusClass = "lms-badge--warning";
		}
		body += "<tr>";
		body += "<td><strong>" + lms_portal.escape(d.file_name || "") + "</strong></td>";
		body += "<td>" + lms_portal.escape(d.category || "Uncategorized") + "</td>";
		body += "<td>" + lms_portal.escape(linked) + "</td>";
		body += "<td>" + size + "</td>";
		body += "<td>" + lms_portal.formatDate(d.modified) + "</td>";
		body += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(status) + "</span></td>";
		body += '<td><a href="' + lms_portal.escape(d.download_url || "#") + '" class="lms-btn lms-btn--ghost lms-btn--sm" rel="noopener">Download</a></td>';
		body += "</tr>";
	});
	body += "</tbody></table></div>";
	el.innerHTML = lms_portal.panel({ body: body });
};