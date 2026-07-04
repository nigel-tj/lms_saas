"""Load / scale benchmark for LMS reports and cron."""

import time


def run(count=100):
	"""Seed bulk demo data and benchmark key reports. bench execute lms_saas.scripts.load_test_portfolio.run"""
	import frappe

	from lms_saas.setup.seed_demo import run_bulk

	start = time.perf_counter()
	run_bulk(count=int(count))
	seed_elapsed = time.perf_counter() - start

	report_times = {}
	for report_name, execute_fn in _report_executors():
		t0 = time.perf_counter()
		try:
			execute_fn({})
			report_times[report_name] = round(time.perf_counter() - t0, 3)
		except Exception as exc:
			report_times[report_name] = f"error: {exc}"

	cron_start = time.perf_counter()
	from lms_saas.tasks import run_daily_loan_cron

	run_daily_loan_cron()
	cron_elapsed = round(time.perf_counter() - cron_start, 3)

	return {
		"seed_count": int(count),
		"seed_seconds": round(seed_elapsed, 3),
		"report_seconds": report_times,
		"daily_cron_seconds": cron_elapsed,
	}


def _report_executors():
	from lms_saas.lms_saas.report.arrears_aging.arrears_aging import execute as arrears_execute
	from lms_saas.lms_saas.report.portfolio_at_risk.portfolio_at_risk import execute as par_execute

	return [
		("Portfolio At Risk", par_execute),
		("Arrears Aging", arrears_execute),
	]
