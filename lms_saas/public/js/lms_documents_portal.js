/* LMS Document Center portal — categories, document list, expiry alerts */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_documents");
} else {
	window.lms_documents = window.lms_documents || {};
}

lms_documents.init = function () {
	var root = document.getElementById("lms-documents-root");
	if (!root) return;

	var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;">';
	html += '<h2 style="margin:0;font-size:var(--lms-fs-xl);font-weight:700;">Document Center</h2>';
	html += '<div style="display:flex;gap:0.5rem;">';
	html += '<select id="lms-doc-cat-filter" class="lms-input lms-fallback-select" style="width:auto;"><option value="">All Categories</option></select>';
	html += '<button type="button" class="lms-btn lms-btn--primary" id="lms-doc-refresh">Refresh</button>';
	html += '</div></div>';
	html += '<div id="lms-doc-stats" style="margin-bottom:1rem;"></div>';
	html += '<div id="lms-doc-list"></div>';
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
};

lms_documents._loadStats = function () {
	var el = document.getElementById("lms-doc-stats");
	if (!el) return;
	lms_portal.safeCall({
		method: "lms_saas.api.documents_center.get_document_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = '<section class="lms-grid-4">';
			html += lms_documents._statCard("Total Documents", s.total_documents || 0);
			html += lms_documents._statCard("Categories", s.categories || 0);
			html += lms_documents._statCard("Expiring (30d)", s.expiring_30_days || 0, "warning");
			html += lms_documents._statCard("Expired", s.expired || 0, "danger");
			html += "</section>";
			el.innerHTML = html;
		},
	});
};

lms_documents._statCard = function (label, value, tone) {
	var cls = tone ? " lms-stat--" + tone : "";
	return '<div class="lms-stat-card lms-stat' + cls + '" style="padding:1rem;"><div class="lms-stat-label">' +
		lms_portal.escape(label) + '</div><div class="lms-stat-value">' + value + '</div></div>';
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
		el.innerHTML = '<div class="lms-panel"><div class="lms-empty"><div class="lms-empty-icon">📁</div><h3>No documents</h3><p>Documents will appear here once uploaded.</p></div></div>';
		return;
	}

	var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
	html += "<thead><tr><th>Name</th><th>Category</th><th>Linked To</th><th>Size</th><th>Modified</th><th>Status</th><th>Action</th></tr></thead><tbody>";
	docs.forEach(function (d) {
		var size = d.file_size ? (d.file_size / 1024).toFixed(1) + " KB" : "—";
		var linked = d.attached_to_doctype ? d.attached_to_doctype + ": " + (d.attached_to_name || "") : "—";
		var status = "Active";
		var statusClass = "lms-badge--success";
		if (d.is_expired) {
			status = "Expired";
			statusClass = "lms-badge--danger";
		} else if (d.expiry_date) {
			status = "Expires " + lms_portal.formatDate(d.expiry_date);
			statusClass = "lms-badge--warning";
		}
		html += "<tr>";
		html += "<td><strong>" + lms_portal.escape(d.file_name || "") + "</strong></td>";
		html += "<td>" + lms_portal.escape(d.category || "Uncategorized") + "</td>";
		html += "<td>" + lms_portal.escape(linked) + "</td>";
		html += "<td>" + size + "</td>";
		html += "<td>" + lms_portal.formatDate(d.modified) + "</td>";
		html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(status) + "</span></td>";
		html += '<td><a href="' + lms_portal.escape(d.file_url || "#") + '" target="_blank" class="lms-btn lms-btn--ghost lms-btn--sm">Download</a></td>';
		html += "</tr>";
	});
	html += "</tbody></table></div></div>";
	el.innerHTML = html;
};