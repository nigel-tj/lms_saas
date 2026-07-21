#!/usr/bin/env bash
# Create test users with correct permissions for LMS SaaS staff testing
# Run this on Frappe Cloud bench after SSH or locally on dev bench
#
# Usage:
#   export FC_SITE=lms-saas.frappe.cloud  # On Frappe Cloud
#   export FC_SITE=lms.localhost          # Locally
#   bash scripts/create-test-users.sh

set -euo pipefail

SITE="${FC_SITE:-lms.localhost}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { printf '%s\n' "$*"; }
warn()  { printf "${YELLOW}%s${NC}\n" "$*" >&2; }
success() { printf "${GREEN}%s${NC}\n" "$*" >&2; }
step()  { printf "${BLUE}>>> %s${NC}\n" "$*"; }

# Check if bench is available
if ! command -v bench >/dev/null 2>&1; then
    if [[ -d "$HOME/frappe-bench" ]]; then
        cd "$HOME/frappe-bench"
    elif [[ -d "/home/frappe/frappe-bench" ]]; then
        cd "/home/frappe/frappe-bench"
    else
        warn "bench not found in PATH"
        exit 1
    fi
fi

# Check if site exists
if [[ ! -d "sites/$SITE" ]]; then
    warn "Site directory sites/$SITE not found"
    info "Available sites:"
    ls -1 sites/ 2>/dev/null | grep -v '^assets$' || true
    exit 1
fi

info ""
info "╔══════════════════════════════════════════════════════════╗"
info "║     Create Test Users for LMS SaaS                      ║"
info "╚══════════════════════════════════════════════════════════╝"
info ""
info "Site: $SITE"
info ""

# Python script to create users with proper permissions
python3 << 'PYTHON_SCRIPT'
import frappe
import sys

# Initialize Frappe
frappe.init(site=frappe.flags.site or 'lms.localhost')
frappe.connect()

# Test Users Configuration
# Each user has: email, first_name, last_name, password, persona, roles
TEST_USERS = [
    {
        "email": "manager@kesari.africa",
        "first_name": "Branch",
        "last_name": "Manager",
        "password": "Manager@123",
        "persona": "Branch Manager",
        "roles": ["LMS Portal Staff"],
        "description": "Can see Manager tab and all manager functions"
    },
    {
        "email": "officer@kesari.africa",
        "first_name": "Loan",
        "last_name": "Officer",
        "password": "Officer@123",
        "persona": "Loan Officer",
        "roles": ["LMS Portal Staff"],
        "description": "Can see Officer tab, manager tab hidden"
    },
    {
        "email": "collector@kesari.africa",
        "first_name": "Collection",
        "last_name": "Agent",
        "password": "Collector@123",
        "persona": "Collection Agent",
        "roles": ["LMS Portal Staff"],
        "description": "Can see Collection tab only"
    },
    {
        "email": "admin@kesari.africa",
        "first_name": "System",
        "last_name": "Administrator",
        "password": "Admin@123",
        "persona": "Branch Manager",
        "roles": ["LMS Portal Staff", "System Manager", "Administrator"],
        "description": "Full system access with manager persona"
    },
    {
        "email": "supervisor@kesari.africa",
        "first_name": "Operations",
        "last_name": "Supervisor",
        "password": "Supervisor@123",
        "persona": "Branch Manager",
        "roles": ["LMS Portal Staff"],
        "description": "Manager persona for oversight without system admin"
    },
    {
        "email": "field@kesari.africa",
        "first_name": "Field",
        "last_name": "Officer",
        "password": "Field@123",
        "persona": "Loan Officer",
        "roles": ["LMS Portal Staff"],
        "description": "Field officer for loan origination and verification"
    },
    {
        "email": "senior.collector@kesari.africa",
        "first_name": "Senior",
        "last_name": "Collector",
        "password": "Senior@123",
        "persona": "Collection Agent",
        "roles": ["LMS Portal Staff"],
        "description": "Senior collector with escalation handling"
    },
    {
        "email": "borrower@example.com",
        "first_name": "Test",
        "last_name": "Borrower",
        "password": "Borrower@123",
        "persona": None,
        "roles": ["Customer"],
        "description": "Test borrower account for portal testing"
    }
]

def create_or_update_user(user_config):
    """Create or update a user with specified configuration"""
    email = user_config["email"]
    
    try:
        # Check if user exists
        existing_user = frappe.get_doc("User", email)
        
        # Update user
        existing_user.first_name = user_config["first_name"]
        existing_user.last_name = user_config["last_name"]
        
        # Set password if provided
        if user_config.get("password"):
            existing_user.new_password = user_config["password"]
        
        existing_user.save(ignore_permissions=True)
        
        # Update roles
        if user_config.get("roles"):
            # Clear existing roles
            existing_user.roles = []
            
            # Add new roles
            for role_name in user_config["roles"]:
                if frappe.db.exists("Role", role_name):
                    existing_user.append("roles", {"role": role_name})
            
            existing_user.save(ignore_permissions=True)
        
        # Create or update Employee record for persona
        employee_id = f"EMP-{email.split('@')[0].upper()}"
        try:
            employee = frappe.get_doc("Employee", employee_id)
            employee.custom_lms_persona = user_config.get("persona")
            employee.save(ignore_permissions=True)
        except frappe.exceptions.DoesNotExistError:
            # Create new Employee record
            employee = frappe.get_doc({
                "doctype": "Employee",
                "employee_id": employee_id,
                "first_name": user_config["first_name"],
                "last_name": user_config["last_name"],
                "custom_lms_persona": user_config.get("persona"),
                "status": "Active",
                "company": "Kesari",
                "date_of_joining": frappe.utils.nowdate(),
            })
            employee.insert(ignore_permissions=True)
        
        return True, f"Updated user {email}"
        
    except frappe.exceptions.DoesNotExistError:
        # Create new user
        try:
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": user_config["first_name"],
                "last_name": user_config["last_name"],
                "new_password": user_config.get("password"),
                "send_welcome_email": False,
                "roles": [{"role": role_name} for role_name in user_config.get("roles", []) if frappe.db.exists("Role", role_name)]
            })
            user.insert(ignore_permissions=True)
            
            # Create Employee record for persona
            if user_config.get("persona"):
                employee_id = f"EMP-{email.split('@')[0].upper()}"
                employee = frappe.get_doc({
                    "doctype": "Employee",
                    "employee_id": employee_id,
                    "first_name": user_config["first_name"],
                    "last_name": user_config["last_name"],
                    "custom_lms_persona": user_config["persona"],
                    "status": "Active",
                    "company": "Kesari",
                    "date_of_joining": frappe.utils.nowdate(),
                })
                employee.insert(ignore_permissions=True)
            
            return True, f"Created user {email}"
            
        except Exception as e:
            return False, f"Error creating {email}: {str(e)}"

# Main execution
print("Creating/updating test users...\n")

success_count = 0
error_count = 0

for user_config in TEST_USERS:
    success, message = create_or_update_user(user_config)
    
    if success:
        print(f"✅ {message}")
        print(f"   Persona: {user_config.get('persona', 'N/A')}")
        print(f"   Roles: {', '.join(user_config.get('roles', []))}")
        print(f"   Description: {user_config['description']}")
        print(f"   Password: {user_config.get('password', 'N/A')}")
        print()
        success_count += 1
    else:
        print(f"❌ {message}")
        print()
        error_count += 1

print("=" * 60)
print(f"Summary: {success_count} successful, {error_count} errors")
print("=" * 60)

# Commit changes to database
frappe.db.commit()

print("\n✅ Test users created successfully!")
print("\nLogin URLs:")
print("  Staff Desk: https://<your-site>/desk")
print("  Borrower Portal: https://<your-site>/lms")
print("\nTest credentials:")
for user_config in TEST_USERS:
    print(f"  {user_config['email']} / {user_config.get('password', 'N/A')}")

frappe.destroy()
PYTHON_SCRIPT

success() ""
success "╔══════════════════════════════════════════════════════════╗"
success "║  Test Users Created Successfully!                        ║"
success "╚══════════════════════════════════════════════════════════╝"
success() ""

info "Test Accounts:"
info "─────────────────────────────────────────────────────────────"
info ""
info "👤 Branch Manager:"
info "   Email: manager@kesari.africa"
info "   Password: Manager@123"
info "   Persona: Branch Manager"
info "   Expected: Manager tab VISIBLE"
info ""
info "👤 Loan Officer:"
info "   Email: officer@kesari.africa"
info "   Password: Officer@123"
info "   Persona: Loan Officer"
info "   Expected: Manager tab HIDDEN, Officer tab VISIBLE"
info ""
info "👤 Collection Agent:"
info "   Email: collector@kesari.africa"
info "   Password: Collector@123"
info "   Persona: Collection Agent"
info "   Expected: Collection tab VISIBLE only"
info ""
info "👤 System Administrator:"
info "   Email: admin@kesari.africa"
info "   Password: Admin@123"
info "   Persona: Branch Manager + System Manager"
info "   Expected: Full access"
info ""
info "👤 Borrower/Customer:"
info "   Email: borrower@example.com"
info "   Password: Borrower@123"
info "   Expected: Portal charts visible"
info ""
info "═════════════════════════════════════════════════════════════"
info ""
info "Next Steps:"
info "1. Login to Staff Desk: https://<your-site>/desk"
info "2. Login to Borrower Portal: https://<your-site>/lms"
info "3. Test persona-based navigation gating"
info "4. Verify Manager tab visibility per persona"
info "5. Test charts on borrower portal"
info ""
