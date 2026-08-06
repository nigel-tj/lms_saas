/* Manager Books & Import portal page. */
if (typeof frappe !== "undefined" && typeof frappe.provide === "function") {
	frappe.provide("lms_manager_books");
} else {
	window.lms_manager_books = window.lms_manager_books || {};
}

(function () {
	'use strict';

	const ROOT_SELECTOR = '#lms-manager-books-root';

	function todayISO() {
		return new Date().toISOString().slice(0, 10);
	}
	function monthStartISO() {
		const d = new Date();
		return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-01';
	}

	function renderShell(root) {
		root.innerHTML = `
			<div class="lms-page-header">
				<div class="lms-page-header__controls">
					<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" data-action="refresh">Refresh</button>
				</div>
			</div>

			<nav class="lms-tab-nav" role="tablist" aria-label="Books & Import sections">
				<button type="button" class="lms-tab is-active" role="tab" data-tab="books" aria-selected="true">Books</button>
				<button type="button" class="lms-tab" role="tab" data-tab="import" aria-selected="false">Import</button>
				<button type="button" class="lms-tab" role="tab" data-tab="recon" aria-selected="false">Reconciliation</button>
			</nav>

			<section data-tab-panel="books" role="tabpanel">
				<section class="lms-summary" data-role="books-kpis" aria-label="Branch books summary">
					<div class="lms-summary-card"><div class="lms-summary-label">Total income</div><div class="lms-summary-value" data-kpi="income">—</div></div>
					<div class="lms-summary-card"><div class="lms-summary-label">Total expense</div><div class="lms-summary-value" data-kpi="expense">—</div></div>
					<div class="lms-summary-card"><div class="lms-summary-label">Net position</div><div class="lms-summary-value" data-kpi="net">—</div></div>
					<div class="lms-summary-card"><div class="lms-summary-label">Rows shown</div><div class="lms-summary-value" data-kpi="rows">—</div></div>
				</section>

				<div class="lms-panel">
					<div class="lms-panel__controls" style="display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;">
						<label class="lms-muted">From <input type="date" name="from_date" value="${monthStartISO()}" /></label>
						<label class="lms-muted">To <input type="date" name="to_date" value="${todayISO()}" /></label>
						<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" data-action="load-books">Load</button>
						<span style="flex:1"></span>
						<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" data-action="export-books" data-fmt="csv">Export CSV</button>
						<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" data-action="export-books" data-fmt="xlsx">Export XLSX</button>
						<span class="lms-muted" data-role="books-total"></span>
					</div>
					<div data-role="books-rows" aria-live="polite"></div>
				</div>
			</section>

			<section data-tab-panel="import" role="tabpanel" hidden>
				<div class="lms-panel">
					<h2 class="lms-section-title">Import GL / Loans / Customers</h2>
					<p class="lms-muted">Stage a CSV or XLSX file, review the preview, then run a dry-run commit before applying for real.</p>

					<div style="display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;">
						<label class="lms-muted">Doctype
							<select name="doctype">
								<option>Loan Repayment</option>
								<option>Customer</option>
								<option>LMS Borrower Compliance</option>
							</select>
						</label>
						<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" data-action="download-template">Download template</button>
						<input type="file" name="file" accept=".csv,.xlsx" />
						<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" data-action="stage-import">Stage file</button>
					</div>

					<section data-role="preview-panel" class="lms-panel" hidden>
						<header><h3>Preview</h3><p class="lms-muted" data-role="preview-summary"></p></header>
						<div data-role="preview-rows"></div>
						<div style="display:flex;gap:.5rem;">
							<button type="button" class="lms-btn lms-btn--ghost lms-btn--sm" data-action="commit-dry-run">Dry run</button>
							<button type="button" class="lms-btn lms-btn--primary lms-btn--sm" data-action="commit-real">Commit</button>
						</div>
					</section>
				</div>
			</section>

			<section data-tab-panel="recon" role="tabpanel" hidden>
				<section class="lms-summary" data-role="recon-kpis" aria-label="Reconciliation summary">
					<div class="lms-summary-card"><div class="lms-summary-label">Statements</div><div class="lms-summary-value" data-kpi="total">—</div></div>
					<div class="lms-summary-card"><div class="lms-summary-label">Matched</div><div class="lms-summary-value" data-kpi="matched">—</div></div>
					<div class="lms-summary-card"><div class="lms-summary-label">Unmatched</div><div class="lms-summary-value" data-kpi="unmatched">—</div></div>
					<div class="lms-summary-card"><div class="lms-summary-label">Unmatched value</div><div class="lms-summary-value" data-kpi="unmatched_value">—</div></div>
				</section>
				<div class="lms-panel">
					<div data-role="recon-rows" aria-live="polite"></div>
				</div>
			</section>
		`;
	}

	function init() {
		const root = document.querySelector(ROOT_SELECTOR);
		if (!root) return false;
		renderShell(root);

		const ROOT = root;
		const tabButtons = ROOT.querySelectorAll('.lms-tab');
		const tabPanels = ROOT.querySelectorAll('[data-tab-panel]');

		function activateTab(name) {
			tabButtons.forEach((b) => {
				const isActive = b.dataset.tab === name;
				b.classList.toggle('is-active', isActive);
				b.setAttribute('aria-selected', isActive ? 'true' : 'false');
			});
			tabPanels.forEach((p) => {
				const isActive = p.dataset.tabPanel === name;
				p.hidden = !isActive;
			});
			if (name === 'recon') loadRecon();
		}

		tabButtons.forEach((b) => {
			b.addEventListener('click', () => activateTab(b.dataset.tab));
		});

		function formatMoney(value, currency) {
			if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
			try {
				return new Intl.NumberFormat(undefined, {
					style: 'currency',
					currency: currency || window.__lms_currency || 'USD',
					maximumFractionDigits: 2,
				}).format(Number(value));
			} catch (e) {
				return Number(value).toFixed(2);
			}
		}

		function escapeHTML(s) {
			return String(s == null ? '' : s)
				.replace(/&/g, '&amp;')
				.replace(/</g, '&lt;')
				.replace(/>/g, '&gt;')
				.replace(/"/g, '&quot;')
				.replace(/'/g, '&#39;');
		}

		async function call(method, args) {
			const r = await fetch('/api/method/lms_saas.api.manager_books.' + method, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': window.frappe?.csrf_token || '' },
				body: JSON.stringify(args || {}),
			});
			const j = await r.json();
			if (j.exc) throw new Error(j.exc);
			return j.message;
		}

		async function loadBooks() {
			const fromDate = ROOT.querySelector('input[name="from_date"]').value;
			const toDate = ROOT.querySelector('input[name="to_date"]').value;
			const kpiWrap = ROOT.querySelector('[data-role="books-kpis"]');
			const rowsEl = ROOT.querySelector('[data-role="books-rows"]');
			const totalEl = ROOT.querySelector('[data-role="books-total"]');
			rowsEl.innerHTML = '<p class="lms-empty">Loading…</p>';
			try {
				const data = await call('get_branch_books', { from_date: fromDate, to_date: toDate, limit: 200 });
				const income = (data.class_totals && data.class_totals.Income && data.class_totals.Income.net) || 0;
				const expense = (data.class_totals && data.class_totals.Expense && data.class_totals.Expense.net) || 0;
				const net = income - expense;
				kpiWrap.querySelector('[data-kpi="income"]').textContent = formatMoney(income);
				kpiWrap.querySelector('[data-kpi="expense"]').textContent = formatMoney(expense);
				kpiWrap.querySelector('[data-kpi="net"]').textContent = formatMoney(net);
				kpiWrap.querySelector('[data-kpi="rows"]').textContent = (data.rows || []).length;
				totalEl.textContent = 'Showing ' + (data.rows || []).length + ' of ' + (data.total_rows || 0) + ' rows';
				renderBooksRows(rowsEl, data.rows || []);
			} catch (err) {
				rowsEl.innerHTML = '<p class="lms-error">Failed to load: ' + escapeHTML(err.message) + '</p>';
			}
		}

		function renderBooksRows(el, rows) {
			if (!rows.length) {
				el.innerHTML = '<p class="lms-empty">No GL rows for this period.</p>';
				return;
			}
			const header = ['Posting date', 'Account', 'Party', 'Debit', 'Credit', 'Voucher'];
			let html = '<table class="lms-table"><thead><tr>' + header.map((h) => '<th>' + escapeHTML(h) + '</th>').join('') + '</tr></thead><tbody>';
			for (const r of rows) {
				html += '<tr>' +
					'<td>' + escapeHTML(r.posting_date) + '</td>' +
					'<td>' + escapeHTML(r.account) + '</td>' +
					'<td>' + escapeHTML((r.party_type || '') + ' ' + (r.party || '')) + '</td>' +
					'<td>' + formatMoney(r.debit) + '</td>' +
					'<td>' + formatMoney(r.credit) + '</td>' +
					'<td>' + escapeHTML((r.voucher_type || '') + ' ' + (r.voucher_no || '')) + '</td>' +
					'</tr>';
			}
			html += '</tbody></table>';
			el.innerHTML = html;
		}

		async function exportBooks(fmt) {
			const fromDate = ROOT.querySelector('input[name="from_date"]').value;
			const toDate = ROOT.querySelector('input[name="to_date"]').value;
			try {
				const data = await call('export_branch_books', { from_date: fromDate, to_date: toDate, fmt });
				const blob = base64ToBlob(data.data, data.mime);
				const url = URL.createObjectURL(blob);
				const a = document.createElement('a');
				a.href = url;
				a.download = data.filename;
				document.body.appendChild(a);
				a.click();
				a.remove();
				URL.revokeObjectURL(url);
			} catch (err) {
				alert('Export failed: ' + err.message);
			}
		}

		function base64ToBlob(b64, mime) {
			const bin = atob(b64);
			const arr = new Uint8Array(bin.length);
			for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
			return new Blob([arr], { type: mime });
		}

		const TEMPLATES = {
			'Loan Repayment': 'against_loan,applicant_type,applicant,company,posting_date,amount_paid\n',
			'Customer': 'name,customer_name,custom_lms_branch\n',
			'LMS Borrower Compliance': 'customer,kyc_status,consent_given,consent_date\n',
		};

		function downloadTemplate() {
			const doctype = ROOT.querySelector('select[name="doctype"]').value;
			const csv = TEMPLATES[doctype] || '';
			const blob = new Blob([csv], { type: 'text/csv' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = (doctype.replace(/\s+/g, '_').toLowerCase()) + '_template.csv';
			document.body.appendChild(a);
			a.click();
			a.remove();
			URL.revokeObjectURL(url);
		}

		async function stageImport() {
			const fileInput = ROOT.querySelector('input[name="file"]');
			const doctype = ROOT.querySelector('select[name="doctype"]').value;
			const file = fileInput.files && fileInput.files[0];
			if (!file) return alert('Please choose a CSV or XLSX file.');
			const reader = new FileReader();
			reader.onload = async () => {
				try {
					const data = await call('create_import_batch', {
						doctype: doctype,
						file_b64: reader.result.split(',')[1] || reader.result,
						mime_hint: file.type || (file.name.endsWith('.xlsx') ? 'vnd.openxmlformats-officedocument.spreadsheetml.sheet' : 'text/csv'),
					});
					window.__lms_last_batch = data;
					renderPreview(data);
				} catch (err) {
					alert('Stage failed: ' + err.message);
				}
			};
			reader.readAsDataURL(file);
		}

		function renderPreview(data) {
			const panel = ROOT.querySelector('[data-role="preview-panel"]');
			const summaryEl = ROOT.querySelector('[data-role="preview-summary"]');
			const rowsEl = ROOT.querySelector('[data-role="preview-rows"]');
			panel.hidden = false;
			summaryEl.textContent = 'Batch ' + data.batch + ' — ' + data.valid_count + ' valid, ' + data.error_count + ' errors of ' + data.row_count + ' rows.';
			if (!data.preview || !data.preview.length) {
				rowsEl.innerHTML = '<p class="lms-empty">No rows.</p>';
				return;
			}
			const header = ['#', 'Status', 'Mapped data', 'Errors'];
			let html = '<table class="lms-table"><thead><tr>' + header.map((h) => '<th>' + escapeHTML(h) + '</th>').join('') + '</tr></thead><tbody>';
			for (const row of data.preview) {
				html += '<tr class="' + (row.ok ? 'lms-row-ok' : 'lms-row-error') + '">' +
					'<td>' + row.row + '</td>' +
					'<td>' + (row.ok ? 'OK' : 'Error') + '</td>' +
					'<td><code>' + escapeHTML(JSON.stringify(row.data)) + '</code></td>' +
					'<td>' + (row.errors.length ? row.errors.map(escapeHTML).join('; ') : '') + '</td>' +
					'</tr>';
			}
			html += '</tbody></table>';
			rowsEl.innerHTML = html;
		}

		async function commitBatch(dryRun) {
			const data = window.__lms_last_batch;
			if (!data) return alert('Stage a file first.');
			try {
				const result = await call('commit_import_batch', { batch: data.batch, dry_run: dryRun ? 1 : 0 });
				if (result.status === 'Failed') {
					alert('Commit failed: ' + (result.errors || []).map((e) => e.message).join('; '));
				} else {
					alert((dryRun ? 'Dry run: ' : 'Committed: ') + result.committed + ' rows. Status ' + result.status);
				}
			} catch (err) {
				alert('Commit failed: ' + err.message);
			}
		}

		async function loadRecon() {
			const wrap = ROOT.querySelector('[data-role="recon-kpis"]');
			const rowsEl = ROOT.querySelector('[data-role="recon-rows"]');
			rowsEl.innerHTML = '<p class="lms-empty">Loading…</p>';
			try {
				const data = await call('get_reconciliation_summary', { limit: 50 });
				wrap.querySelector('[data-kpi="total"]').textContent = data.total;
				wrap.querySelector('[data-kpi="matched"]').textContent = data.matched;
				wrap.querySelector('[data-kpi="unmatched"]').textContent = data.unmatched;
				wrap.querySelector('[data-kpi="unmatched_value"]').textContent = formatMoney(data.unmatched_value);
				if (!data.unmatched_rows || !data.unmatched_rows.length) {
					rowsEl.innerHTML = '<p class="lms-empty">All statements are matched.</p>';
					return;
				}
				const header = ['Date', 'Provider', 'External ref', 'Amount'];
				let html = '<table class="lms-table"><thead><tr>' + header.map((h) => '<th>' + escapeHTML(h) + '</th>').join('') + '</tr></thead><tbody>';
				for (const r of data.unmatched_rows) {
					html += '<tr>' +
						'<td>' + escapeHTML(r.statement_date) + '</td>' +
						'<td>' + escapeHTML(r.provider_code) + '</td>' +
						'<td>' + escapeHTML(r.external_ref || '') + '</td>' +
						'<td>' + formatMoney(r.amount) + '</td>' +
						'</tr>';
				}
				html += '</tbody></table>';
				rowsEl.innerHTML = html;
			} catch (err) {
				rowsEl.innerHTML = '<p class="lms-error">Failed to load: ' + escapeHTML(err.message) + '</p>';
			}
		}

		ROOT.addEventListener('click', (ev) => {
			const target = ev.target.closest('[data-action]');
			if (!target) return;
			const action = target.dataset.action;
			switch (action) {
				case 'refresh': loadBooks(); break;
				case 'load-books': loadBooks(); break;
				case 'export-books': exportBooks(target.dataset.fmt || 'csv'); break;
				case 'download-template': downloadTemplate(); break;
				case 'stage-import': stageImport(); break;
				case 'commit-dry-run': commitBatch(true); break;
				case 'commit-real': commitBatch(false); break;
			}
		});

		loadBooks();
		return true;
	}

	// Expose init on the lms_manager_books global so the page template's
	// frappe.ready handler can call lms_manager_books.init() after the
	// root div is in the DOM. Also auto-init as a fallback if the template
	// script block is absent (e.g. legacy includes).
	lms_manager_books.init = init;
	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', init);
	} else {
		init();
	}
})();
