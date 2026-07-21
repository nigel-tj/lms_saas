/* LMS Insurance portal — policies, claims, stats */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_insurance");
} else {
	window.lms_insurance = window.lms_insurance || {};
}

lms_insurance._currentTab = "policies";

lms_insurance.init = function () {
	var root = document.getElementById("lms-insurance-root");
	if (!root) return;

	var isAdmin = (window.frappe && frappe.boot && frappe.boot.user_roles &&
		(frappe.boot.user_roles.indexOf("System Manager") >= 0 ||
		 frappe.boot.user_roles.indexOf("Administrator") >= 0));

	var tabs = [
		{ id: "policies", label: "Policies", icon: "🛡️" },
		{ id: "claims", label: "Claims", icon: "📋" },
		{ id: "stats", label: "Stats", icon: "📊" },
	];
	var actions = isAdmin
		? [
			{ label: "+ New Policy", id: "lms-ins-new-policy", primary: true },
			{ label: "File Claim", id: "lms-ins-file-claim" },
		  ]
		: [{ label: "File Claim", id: "lms-ins-file-claim" }];
	var html = lms_portal.pageStart() +
		lms_portal.pageHeader({ title: "Insurance", actions: actions }) +
		lms_portal.tabNav(tabs, lms_insurance._currentTab) +
		'<div id="lms-ins-tab-content"></div>' +
		lms_portal.pageEnd();
	root.innerHTML = html;

	lms_portal.bindTabs({
		root: root,
		tabs: tabs,
		onTab: function (tabId) { lms_insurance._currentTab = tabId; lms_insurance._showTab(tabId); },
	});

	var newPolicyBtn = root.querySelector("#lms-ins-new-policy");
	if (newPolicyBtn) {
		newPolicyBtn.addEventListener("click", function () {
			lms_insurance._showCreatePolicyModal();
		});
	}
	var fileClaimBtn = root.querySelector("#lms-ins-file-claim");
	if (fileClaimBtn) {
		fileClaimBtn.addEventListener("click", function () {
			lms_insurance._showFileClaimModal();
		});
	}

	lms_insurance._showTab(lms_insurance._currentTab);
};

lms_insurance._showTab = function (tabId) {
	var content = document.getElementById("lms-ins-tab-content");
	if (!content) return;
	content.innerHTML = lms_portal.loading("Loading…");

	if (tabId === "policies") lms_insurance._loadPolicies(content);
	else if (tabId === "claims") lms_insurance._loadClaims(content);
	else if (tabId === "stats") lms_insurance._loadStats(content);
};

lms_insurance._loadPolicies = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.insurance.get_policies",
		callback: function (r) {
			var policies = (r && r.message && r.message.policies) || [];
			if (!policies.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("🛡️") + '<h3>No policies</h3><p>No insurance policies found.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Policy #</th><th>Loan</th><th>Customer</th><th>Type</th><th>Provider</th><th>Premium</th><th>Coverage</th><th>Status</th><th>Action</th></tr></thead><tbody>";
			policies.forEach(function (p) {
				var statusClass = p.status === "Active" ? "lms-badge--success" : (p.status === "Lapsed" ? "lms-badge--danger" : (p.status === "Expired" ? "lms-badge--warning" : ""));
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(p.policy_number) + "</strong></td>";
				html += "<td>" + lms_portal.escape(p.loan || "—") + "</td>";
				html += "<td>" + lms_portal.escape(p.customer || "—") + "</td>";
				html += "<td>" + lms_portal.escape(p.insurance_type || "—") + "</td>";
				html += "<td>" + lms_portal.escape(p.provider || "—") + "</td>";
				html += "<td>" + format_currency(p.premium_amount || 0) + "</td>";
				html += "<td>" + format_currency(p.coverage_amount || 0) + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(p.status || "—") + "</span></td>";
				html += '<td><button type="button" class="lms-btn lms-btn--ghost lms-btn--sm lms-ins-view-policy" data-name="' + lms_portal.escape(p.name) + '">View</button></td>';
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;

			content.querySelectorAll(".lms-ins-view-policy").forEach(function (btn) {
				btn.addEventListener("click", function () {
					lms_insurance._showPolicyDetail(btn.getAttribute("data-name"));
				});
			});
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load policies.");
		},
	});
};

lms_insurance._showPolicyDetail = function (policyName) {
	lms_portal.safeCall({
		method: "lms_saas.api.insurance.get_policy_detail",
		args: { policy_name: policyName },
		callback: function (r) {
			var data = (r && r.message) || {};
			lms_insurance._renderPolicyDetail(data);
		},
	});
};

lms_insurance._renderPolicyDetail = function (data) {
	var p = data.policy || {};
	var loan = data.loan || {};
	var claims = data.claims || [];

	var html = '<div class="lms-form">';
	html += '<h3 style="margin:0 0 0.5rem;">Policy: ' + lms_portal.escape(p.policy_number || "") + '</h3>';
	html += '<div class="lms-summary" style="margin-bottom:1rem;">';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Type</div><div class="lms-summary-value">' + lms_portal.escape(p.insurance_type || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Status</div><div class="lms-summary-value">' + lms_portal.escape(p.status || "—") + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Premium</div><div class="lms-summary-value">' + format_currency(p.premium_amount || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Coverage</div><div class="lms-summary-value">' + format_currency(p.coverage_amount || 0) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">Start</div><div class="lms-summary-value">' + lms_portal.formatDate(p.start_date) + '</div></div>';
	html += '<div class="lms-summary-card"><div class="lms-summary-label">End</div><div class="lms-summary-value">' + lms_portal.formatDate(p.end_date) + '</div></div>';
	html += '</div>';

	if (loan && loan.name) {
		html += '<h4 style="margin:1rem 0 0.5rem;">Linked Loan</h4>';
		html += '<div class="lms-panel" style="padding:0.75rem;margin-bottom:1rem;">';
		html += '<p style="margin:0;"><strong>' + lms_portal.escape(loan.name) + '</strong> · ' + format_currency(loan.loan_amount || 0) + ' · ' + lms_portal.escape(loan.status || "—") + '</p>';
		html += '</div>';
	}

	if (claims.length) {
		html += '<h4 style="margin:1rem 0 0.5rem;">Claims</h4>';
		html += '<div class="lms-data-table__wrap"><table class="lms-data-table"><thead><tr><th>Date</th><th>Amount</th><th>Type</th><th>Status</th></tr></thead><tbody>';
		claims.forEach(function (c) {
			html += "<tr>";
			html += "<td>" + lms_portal.formatDate(c.claim_date) + "</td>";
			html += "<td>" + format_currency(c.claim_amount || 0) + "</td>";
			html += "<td>" + lms_portal.escape(c.claim_type || "—") + "</td>";
			html += "<td>" + lms_portal.escape(c.status || "—") + "</td>";
			html += "</tr>";
		});
		html += "</tbody></table></div>";
	}

	html += '</div>';

	lms_portal.modal({
		title: "Policy Detail",
		body: html,
		size: "xl",
		confirmText: "Close",
		confirmVariant: "primary",
		onConfirm: function () {},
	});
};

lms_insurance._loadClaims = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.insurance.get_claims",
		callback: function (r) {
			var claims = (r && r.message && r.message.claims) || [];
			if (!claims.length) {
				content.innerHTML = '<div class="lms-panel"><div class="lms-empty">' + lms_icons.empty("📋") + '<h3>No claims</h3><p>No insurance claims found.</p></div></div>';
				return;
			}
			var html = '<div class="lms-panel"><div class="lms-data-table__wrap"><table class="lms-data-table">';
			html += "<thead><tr><th>Claim</th><th>Policy</th><th>Date</th><th>Amount</th><th>Type</th><th>Status</th></tr></thead><tbody>";
			claims.forEach(function (c) {
				var statusClass = c.status === "Paid" ? "lms-badge--success" : (c.status === "Rejected" ? "lms-badge--danger" : (c.status === "Approved" ? "lms-badge--info" : "lms-badge--warning"));
				html += "<tr>";
				html += "<td><strong>" + lms_portal.escape(c.name) + "</strong></td>";
				html += "<td>" + lms_portal.escape(c.policy || "—") + "</td>";
				html += "<td>" + lms_portal.formatDate(c.claim_date) + "</td>";
				html += "<td>" + format_currency(c.claim_amount || 0) + "</td>";
				html += "<td>" + lms_portal.escape(c.claim_type || "—") + "</td>";
				html += '<td><span class="lms-badge ' + statusClass + '">' + lms_portal.escape(c.status || "—") + "</span></td>";
				html += "</tr>";
			});
			html += "</tbody></table></div></div>";
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load claims.");
		},
	});
};

lms_insurance._loadStats = function (content) {
	lms_portal.safeCall({
		method: "lms_saas.api.insurance.get_insurance_stats",
		callback: function (r) {
			var s = (r && r.message) || {};
			var html = lms_portal.pageStart() +
				lms_portal.kpiStrip([
					{ label: "Total Policies", value: s.total_policies || 0 },
					{ label: "Active Policies", value: s.active_policies || 0, tone: "success" },
					{ label: "Lapsed", value: s.lapsed_policies || 0, tone: "danger" },
					{ label: "Expired", value: s.expired_policies || 0, tone: "warning" },
				]) +
				lms_portal.kpiStrip([
					{ label: "Total Claims", value: s.total_claims || 0 },
					{ label: "Filed", value: s.filed_claims || 0, tone: "warning" },
					{ label: "Approved", value: s.approved_claims || 0 },
					{ label: "Paid", value: s.paid_claims || 0, tone: "success" },
				]) +
				lms_portal.kpiStrip([
					{ label: "Total Coverage", value: format_currency(s.total_coverage || 0) },
					{ label: "Total Premiums", value: format_currency(s.total_premiums || 0) },
				]) +
				lms_portal.pageEnd();
			content.innerHTML = html;
		},
		error: function () {
			content.innerHTML = lms_portal.error("Could not load stats.");
		},
	});
};

lms_insurance._showCreatePolicyModal = function () {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Policy Number</label>';
	html += '<input type="text" id="lms-ins-polnum" class="lms-input" placeholder="POL-00001"></div>';
	html += '<div class="lms-field"><label>Loan</label>';
	html += '<input type="text" id="lms-ins-loan" class="lms-input" placeholder="LOAN-00001"></div>';
	html += '<div class="lms-field"><label>Customer</label>';
	html += '<input type="text" id="lms-ins-customer" class="lms-input" placeholder="Customer name"></div>';
	html += '<div style="display:flex;gap:1rem;">';
	html += '<div class="lms-field" style="flex:1;"><label>Insurance Type</label>';
	html += '<select id="lms-ins-type" class="lms-input lms-fallback-select">';
	html += '<option value="Credit Life">Credit Life</option><option value="Asset Insurance">Asset Insurance</option><option value="Property">Property</option>';
	html += '</select></div>';
	html += '<div class="lms-field" style="flex:1;"><label>Company</label>';
	html += '<input type="text" id="lms-ins-company" class="lms-input" placeholder="Company"></div>';
	html += '</div>';
	html += '<div style="display:flex;gap:1rem;">';
	html += '<div class="lms-field" style="flex:1;"><label>Provider</label>';
	html += '<input type="text" id="lms-ins-provider" class="lms-input" placeholder="Insurance provider"></div>';
	html += '<div class="lms-field" style="flex:1;"><label>Premium Amount</label>';
	html += '<input type="number" id="lms-ins-premium" class="lms-input" placeholder="0.00"></div>';
	html += '</div>';
	html += '<div style="display:flex;gap:1rem;">';
	html += '<div class="lms-field" style="flex:1;"><label>Coverage Amount</label>';
	html += '<input type="number" id="lms-ins-coverage" class="lms-input" placeholder="0.00"></div>';
	html += '<div class="lms-field" style="flex:1;"><label>Start Date</label>';
	html += '<input type="date" id="lms-ins-start" class="lms-input"></div>';
	html += '</div>';
	html += '<div class="lms-field"><label>End Date</label>';
	html += '<input type="date" id="lms-ins-end" class="lms-input"></div>';
	html += '</div>';

	lms_portal.modal({
		title: "New Insurance Policy",
		body: html,
		confirmText: "Create",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var policyNumber = overlay.querySelector("#lms-ins-polnum").value;
			var loan = overlay.querySelector("#lms-ins-loan").value;
			var customer = overlay.querySelector("#lms-ins-customer").value;
			var insuranceType = overlay.querySelector("#lms-ins-type").value;
			var company = overlay.querySelector("#lms-ins-company").value;
			var provider = overlay.querySelector("#lms-ins-provider").value;
			var premium = overlay.querySelector("#lms-ins-premium").value;
			var coverage = overlay.querySelector("#lms-ins-coverage").value;
			var startDate = overlay.querySelector("#lms-ins-start").value;
			var endDate = overlay.querySelector("#lms-ins-end").value;

			if (!policyNumber || !loan || !customer || !insuranceType || !company) {
				lms_portal.toast("Policy number, loan, customer, type, and company are required.", "danger");
				return false;
			}

			lms_portal.safeCall({
				method: "lms_saas.api.insurance.create_policy",
				args: {
					policy_number: policyNumber,
					loan: loan,
					customer: customer,
					insurance_type: insuranceType,
					company: company,
					provider: provider,
					premium_amount: premium,
					coverage_amount: coverage,
					start_date: startDate,
					end_date: endDate,
				},
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Policy created: " + (res.policy_number || ""), "success");
					lms_insurance._showTab("policies");
				},
				error: function () {
					lms_portal.toast("Could not create policy.", "danger");
				},
			});
		},
	});
};

lms_insurance._showFileClaimModal = function () {
	var html = '<div class="lms-form">';
	html += '<div class="lms-field"><label>Policy</label>';
	html += '<input type="text" id="lms-ins-claim-policy" class="lms-input" placeholder="Policy name/number"></div>';
	html += '<div style="display:flex;gap:1rem;">';
	html += '<div class="lms-field" style="flex:1;"><label>Claim Date</label>';
	html += '<input type="date" id="lms-ins-claim-date" class="lms-input"></div>';
	html += '<div class="lms-field" style="flex:1;"><label>Claim Amount</label>';
	html += '<input type="number" id="lms-ins-claim-amount" class="lms-input" placeholder="0.00"></div>';
	html += '</div>';
	html += '<div class="lms-field"><label>Claim Type</label>';
	html += '<select id="lms-ins-claim-type" class="lms-input lms-fallback-select">';
	html += '<option value="Death">Death</option><option value="Disability">Disability</option><option value="Asset Damage">Asset Damage</option><option value="Other">Other</option>';
	html += '</select></div>';
	html += '<div class="lms-field"><label>Description</label>';
	html += '<textarea id="lms-ins-claim-desc" class="lms-input" rows="3" placeholder="Claim description…"></textarea></div>';
	html += '</div>';

	lms_portal.modal({
		title: "File Insurance Claim",
		body: html,
		confirmText: "Submit",
		confirmVariant: "primary",
		onConfirm: function (overlay) {
			var policy = overlay.querySelector("#lms-ins-claim-policy").value;
			var claimDate = overlay.querySelector("#lms-ins-claim-date").value;
			var claimAmount = overlay.querySelector("#lms-ins-claim-amount").value;
			var claimType = overlay.querySelector("#lms-ins-claim-type").value;
			var desc = overlay.querySelector("#lms-ins-claim-desc").value;

			if (!policy || !claimDate || !claimAmount || !claimType) {
				lms_portal.toast("Policy, date, amount, and type are required.", "danger");
				return false;
			}

			lms_portal.safeCall({
				method: "lms_saas.api.insurance.file_claim",
				args: {
					policy: policy,
					claim_date: claimDate,
					claim_amount: claimAmount,
					claim_type: claimType,
					description: desc,
				},
				callback: function (r) {
					var res = (r && r.message) || {};
					lms_portal.toast("Claim filed: " + (res.name || ""), "success");
					lms_insurance._showTab("claims");
				},
				error: function () {
					lms_portal.toast("Could not file claim.", "danger");
				},
			});
		},
	});
};