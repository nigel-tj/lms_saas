def run():
	import frappe

	out = []
	for dt in (
		"Training Program",
		"Material Request",
		"LMS Regulatory Submission",
		"Employee",
		"Salary Slip",
		"Item",
	):
		out.append(
			{
				"dt": dt,
				"plain": bool(frappe.db.table_exists(dt)),
				"tabpref": bool(frappe.db.table_exists("tab" + dt)),
				"exists": bool(frappe.db.exists("DocType", dt)),
			}
		)
	print(out)
	return out
