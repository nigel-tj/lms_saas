"""bench --site lms.localhost execute lms_saas.setup.check_perms.run"""


def run(user="admin@lms.localhost"):
    import frappe
    from frappe.desk.query_report import run

    frappe.set_user(user)
    roles = frappe.get_roles(user)
    can_read = frappe.has_permission("Loan", "read")
    report_rows = None
    report_error = None
    try:
        result = run("Portfolio At Risk", filters={})
        report_rows = len(result.get("result") or [])
    except Exception as e:
        report_error = str(e)

    return {
        "user": user,
        "roles": roles,
        "loan_read": can_read,
        "par_rows": report_rows,
        "par_error": report_error,
    }
