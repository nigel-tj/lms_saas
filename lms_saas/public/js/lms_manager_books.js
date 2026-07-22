/* Manager Books & Import portal page. */
(function () {
	'use strict';

	const ROOT = document.querySelector('.lms-page[data-page="manager-books"]');
	if (!ROOT) return;

	const tabButtons = ROOT.querySelectorAll('.lms-tab');
	const tabPanels = ROOT.querySelectorAll('.lms-tabpanel');

	function activateTab(name) {
		tabButtons.forEach((b) => {
			const isActive = b.dataset.tab === name;
			b.setAttribute('aria-selected', isActive ? 'true' : 'false');
		});
		tabPanels.forEach((p) => {
			const isActive = p.dataset.tabPanel === name;
			p.setAttribute('aria-hidden', isActive ? 'false' : 'true');
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
				currency: currency || window.__lms_currency || 'ZAR',
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

	// ---------------------------------------------------------------------
	// Books tab
	// ---------------------------------------------------------------------

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

	// ---------------------------------------------------------------------
	// Import tab
	// ---------------------------------------------------------------------

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

	// ---------------------------------------------------------------------
	// Reconciliation tab
	// ---------------------------------------------------------------------

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

	// ---------------------------------------------------------------------
	// Action wiring
	// ---------------------------------------------------------------------

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

	// Initial load
	loadBooks();
})();
