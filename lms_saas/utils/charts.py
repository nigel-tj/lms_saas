"""Chart helpers for desk reports, emails, and digest HTML."""

from __future__ import annotations

from frappe.utils import flt

RISK_BUCKET_LABELS = ("Current", "PAR 30+", "PAR 60+", "PAR 90+")


def rows_from_risk_buckets(risk_buckets: dict | None) -> list[dict]:
	"""Map dashboard risk_buckets keys to labelled bar rows."""
	buckets = risk_buckets or {}
	return [
		{"label": "Current", "value": flt(buckets.get("current"))},
		{"label": "PAR 30+", "value": flt(buckets.get("par30"))},
		{"label": "PAR 60+", "value": flt(buckets.get("par60"))},
		{"label": "PAR 90+", "value": flt(buckets.get("par90"))},
	]


def to_frappe_report_chart(labels, values, chart_type="bar", colors=None):
	"""Frappe script report chart dict."""
	dataset = {"values": [flt(v) for v in values]}
	if colors:
		dataset["colors"] = colors
	return {
		"data": {"labels": list(labels), "datasets": [dataset]},
		"type": chart_type,
	}


def render_email_bar_chart(rows, title=None, bar_color="#0f4c5c") -> str:
	"""Email-safe HTML bar chart using nested tables (no JS)."""
	if not rows:
		return '<p style="margin:0;color:#64748b;font-size:13px;">No data.</p>'

	max_val = max((flt(r.get("value")) for r in rows), default=0)
	title_html = ""
	if title:
		title_html = (
			f'<p style="margin:0 0 12px;font-size:14px;font-weight:600;color:#0f172a;">{title}</p>'
		)

	bars = []
	for row in rows:
		label = row.get("label") or ""
		value = flt(row.get("value"))
		width = max(4, int((value / max_val) * 100)) if max_val else 0
		value_display = row.get("value_display") or f"{value:,.2f}"
		bars.append(
			f'<tr><td style="padding:6px 8px 6px 0;font-size:12px;color:#334155;white-space:nowrap;'
			f'vertical-align:middle;width:120px;">{label}</td>'
			f'<td style="padding:6px 0;vertical-align:middle;">'
			f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0">'
			f'<tr><td style="background:#e2e8f0;border-radius:4px;height:18px;width:100%;">'
			f'<div style="background:{bar_color};border-radius:4px;height:18px;width:{width}%;'
			f'max-width:100%;"></div></td></tr></table></td>'
			f'<td style="padding:6px 0 6px 8px;font-size:12px;font-weight:600;color:#0f172a;'
			f'text-align:right;white-space:nowrap;vertical-align:middle;">{value_display}</td></tr>'
		)

	return (
		title_html
		+ '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0;">'
		+ "".join(bars)
		+ "</table>"
	)
