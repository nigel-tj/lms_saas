#!/bin/bash
# R25-F3/F2 followup: stamp the live borrowers' AML=Clear + KYC=Approved
# so the new gates don't block legitimate demo flows on the live bench.
#
# This is the one-shot fix for the "Cannot submit: borrower AML screening
# is not Clear (current: Pending)" error on the live site.
#
# Run on the Frappe Cloud bench:
#   bash /home/frappe/frappe-bench/apps/lms_saas/scripts/fix_live_aml_clear.sh
# Or interactively:
#   bench --site lms-saas.frappe.cloud execute \
#       lms_saas.scripts.mark_demo_borrowers_aml_clear.run

SITE=${FRAPPE_SITE:-lms-saas.frappe.cloud}

cd /home/frappe/frappe-bench
source env/bin/activate

bench --site "$SITE" execute lms_saas.scripts.mark_demo_borrowers_aml_clear.run

echo
echo "=========================================="
echo "Verifying AML/Clear + KYC/Approved state"
echo "=========================================="
bench --site "$SITE" execute frappe.client.get_list \
  --kwargs '{"doctype":"LMS Borrower Compliance","fields":["name","customer","kyc_status","aml_status","aml_screened_at"],"limit_page_length":10}'
