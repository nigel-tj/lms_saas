"""Minimal demo rows for Training (and no-op if already present).

bench --site lms.localhost execute lms_saas.setup.seed_r8_demo.run
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, today


def run():
	out = {"training_program": None, "training_event": None}

	if not frappe.db.table_exists("Training Program"):
		return {"ok": False, "reason": "Training Program table missing"}

	meta = frappe.get_meta("Training Program")
	title_field = "program_name" if meta.has_field("program_name") else (meta.title_field or "name")
	demo_title = "LMS Field Collections Basics"

	existing = None
	if title_field != "name" and meta.has_field(title_field):
		existing = frappe.db.get_value("Training Program", {title_field: demo_title}, "name")
	if not existing:
		# Fall back: any program counts as seeded
		existing = frappe.db.get_value("Training Program", {}, "name", order_by="creation asc")

	if existing:
		out["training_program"] = existing
	else:
		doc = frappe.new_doc("Training Program")
		if meta.has_field("program_name"):
			doc.program_name = demo_title
		elif meta.has_field("training_program"):
			doc.training_program = demo_title
		if meta.has_field("status"):
			opts = [o for o in (meta.get_field("status").options or "").split("\n") if o.strip()]
			chosen = None
			for cand in ("Open", "Scheduled", "Active", "Published"):
				if cand in opts:
					chosen = cand
					break
			doc.status = chosen or (opts[0] if opts else "Open")
		if meta.has_field("description"):
			doc.description = "Demo program: field collections, KYC reminders, and offline PWA basics."
		doc.flags.ignore_permissions = True
		doc.insert()
		out["training_program"] = doc.name
		out["training_fields"] = [f.fieldname for f in meta.fields if f.fieldtype not in ("Section Break", "Column Break", "Tab Break")]

	if frappe.db.table_exists("Training Event") and out["training_program"]:
		emeta = frappe.get_meta("Training Event")
		ev_title = "Collections Kickoff (Demo)"
		ev = None
		if emeta.has_field("event_name"):
			ev = frappe.db.get_value("Training Event", {"event_name": ev_title}, "name")
		if not ev:
			ev = frappe.db.get_value("Training Event", {}, "name", order_by="creation asc")
		if ev:
			out["training_event"] = ev
		else:
			edoc = frappe.new_doc("Training Event")
			if emeta.has_field("event_name"):
				edoc.event_name = ev_title
			if emeta.has_field("training_program"):
				edoc.training_program = out["training_program"]
			if emeta.has_field("introduction"):
				edoc.introduction = "Demo kickoff for field collections and offline sync."
			if emeta.has_field("start_time"):
				edoc.start_time = f"{add_days(today(), 7)} 09:00:00"
			if emeta.has_field("end_time"):
				edoc.end_time = f"{add_days(today(), 7)} 12:00:00"
			if emeta.has_field("location"):
				edoc.location = "Head Office Training Room"
			if emeta.has_field("status"):
				opts = [o for o in (emeta.get_field("status").options or "").split("\n") if o.strip()]
				for cand in ("Scheduled", "Open", "Confirmed"):
					if cand in opts:
						edoc.status = cand
						break
			edoc.flags.ignore_permissions = True
			try:
				edoc.insert()
				out["training_event"] = edoc.name
			except Exception as e:
				out["training_event_error"] = f"{type(e).__name__}: {str(e)[:200]}"

	frappe.db.commit()
	print(out)
	return out
