# Pilot staging on a VM — `lms.embleconsulting.com`

Deploy the LMS stack (Frappe v15 + ERPNext + Lending + HRMS + `lms_saas`) on a
public VM for RBZ sandbox pilot testing.

**Pilot URL**

| Surface | URL |
|---------|-----|
| Desk (staff) | https://lms.embleconsulting.com/app/loans |
| Borrower portal | https://lms.embleconsulting.com/lms |
| API | https://lms.embleconsulting.com/api |

**Site name on bench:** `lms.embleconsulting.com` (must match the hostname Frappe
serves).

---

## 1. VM and DNS

### Recommended VM (free tier)

**Oracle Cloud Always Free** — Ampere ARM `VM.Standard.A1.Flex`:

| Setting | Value |
|---------|-------|
| OS | Ubuntu 22.04 LTS (aarch64) |
| Shape | 2 OCPU, 12 GB RAM (minimum for pilot) |
| Boot disk | 100 GB |
| Public IPv4 | Yes |

Upgrade the account to **Pay-As-You-Go** (card required) if ARM provisioning
fails on a pure free account; stay within Always Free limits to avoid charges.

Any Ubuntu 22.04 VM with **≥ 2 vCPU, 8 GB RAM, 50 GB disk** works (Hetzner,
DigitalOcean, etc.).

### DNS (Emble Consulting domain)

In your DNS provider for `embleconsulting.com`, add:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | `lms` | `<VM_PUBLIC_IP>` | 300 |

Verify before continuing:

```bash
dig +short lms.embleconsulting.com
# must return your VM public IP
```

### Firewall

Open inbound **TCP 22, 80, 443** on the cloud security list / firewall group.
On Oracle, also check the instance **subnet security list** and **NSG** if used.

---

## 2. Server bootstrap (run as root on the VM)

```bash
apt update && apt upgrade -y

apt install -y git python3-dev python3-pip python3-venv python3-setuptools \
  redis-server mariadb-server mariadb-client \
  nginx supervisor libffi-dev libssl-dev \
  xvfb libfontconfig wkhtmltopdf \
  curl build-essential

# --- MariaDB (utf8mb4 required by Frappe) ---
cat >> /etc/mysql/mariadb.conf.d/50-server.cnf <<'EOF'

[mysqld]
character-set-client-handshake = FALSE
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci

[mysql]
default-character-set = utf8mb4
EOF

systemctl restart mariadb
mysql_secure_installation
```

Set a strong MariaDB root password and record it — you need it for
`bench new-site`.

Optional: create a dedicated DB admin (recommended):

```bash
mysql -u root -p <<'SQL'
CREATE USER IF NOT EXISTS 'frappe'@'localhost' IDENTIFIED BY 'CHANGE_ME_STRONG';
GRANT ALL PRIVILEGES ON *.* TO 'frappe'@'localhost' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL
```

### Create the `frappe` Linux user

```bash
adduser --disabled-password --gecos "" frappe
usermod -aG sudo frappe
echo "frappe ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/frappe
chmod 440 /etc/sudoers.d/frappe
```

Install Node 18 and Yarn (Frappe v15):

```bash
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt install -y nodejs
npm install -g yarn
```

Switch to the frappe user for all remaining steps:

```bash
su - frappe
```

---

## 3. Install Bench and apps

```bash
pip install frappe-bench

export PATH="$HOME/.local/bin:$PATH"

bench init frappe-bench --frappe-branch version-15
cd ~/frappe-bench

bench get-app erpnext --branch version-15
bench get-app lending --branch version-15
bench get-app hrms --branch version-15
```

### Install `lms_saas` (pick one method)

**Option A — from GitHub** (after you push this repo):

```bash
bench get-app https://github.com/YOUR_ORG/erp-loan-microfin.git --branch main
# app folder name may be erp-loan-microfin; if so, symlink or rename:
# ln -s apps/erp-loan-microfin/apps/lms_saas apps/lms_saas
```

If the repo root contains `apps/lms_saas`, clone and point bench at the app path:

```bash
git clone https://github.com/YOUR_ORG/erp-loan-microfin.git ~/erp-loan-microfin
bench get-app ~/erp-loan-microfin/apps/lms_saas
```

**Option B — copy from your dev machine** (no GitHub yet):

On your **local** machine:

```bash
rsync -avz --exclude '__pycache__' --exclude '*.pyc' \
  /home/nigel/work/erp-loan-microfin/apps/lms_saas/ \
  frappe@<VM_IP>:~/frappe-bench/apps/lms_saas/
```

On the **VM**:

```bash
cd ~/frappe-bench
bench setup requirements
bench build --app lms_saas
```

---

## 4. Create the pilot site

Replace passwords before running.

```bash
cd ~/frappe-bench
export PATH="$HOME/.local/bin:$PATH"

bench new-site lms.embleconsulting.com \
  --mariadb-root-password 'YOUR_MARIADB_ROOT_PASSWORD' \
  --admin-password 'YOUR_DESK_ADMIN_PASSWORD'

bench --site lms.embleconsulting.com install-app erpnext
bench --site lms.embleconsulting.com install-app lending
bench --site lms.embleconsulting.com install-app hrms
bench --site lms.embleconsulting.com install-app lms_saas

bench --site lms.embleconsulting.com migrate
bench build --app lms_saas
bench --site lms.embleconsulting.com execute lms_saas.install.after_install
bench --site lms.embleconsulting.com enable-scheduler
bench --site lms.embleconsulting.com clear-cache
```

---

## 5. Production setup (Nginx + Supervisor + SSL)

Still as user `frappe`:

```bash
cd ~/frappe-bench
sudo bench setup production frappe --yes
```

Install Certbot and obtain a certificate (DNS must already resolve):

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d lms.embleconsulting.com
```

Certbot adds HTTPS and redirects HTTP → HTTPS. Renewal is automatic via systemd
timer.

Confirm services:

```bash
sudo supervisorctl status
sudo systemctl status nginx
```

---

## 6. Pilot / RBZ sandbox configuration

Edit `~/frappe-bench/sites/lms.embleconsulting.com/site_config.json`.
Merge these keys (keep any existing keys such as `db_name`):

```json
{
  "lms_enforce_four_eyes": true,
  "lms_require_consent": true,
  "lms_max_loan_amount": 50000,
  "lms_max_active_customers": 100,
  "lms_sandbox_end_date": "2027-02-28",
  "lms_credit_bureau_enabled": false,
  "developer_mode": 0
}
```

Apply and verify:

```bash
bench --site lms.embleconsulting.com clear-cache
bench --site lms.embleconsulting.com execute lms_saas.setup.verify_spec.run_all_checks
```

Weekly RBZ KPI export:

```bash
bench --site lms.embleconsulting.com execute lms_saas.api.compliance.get_sandbox_report
```

See [COMPLIANCE.md](COMPLIANCE.md) for the full control mapping.

---

## 7. Load data for the pilot

### Option A — restore from local dev (recommended if you have demo data)

On **local** dev machine:

```bash
cd frappe-bench
export PATH="$HOME/.local/bin:$PATH"
bench --site lms.localhost backup --with-files
ls sites/lms.localhost/private/backups/
```

Copy the latest `.sql.gz` and `*-files.tar` to the VM:

```bash
scp sites/lms.localhost/private/backups/2026* \
  frappe@<VM_IP>:/tmp/lms-restore/
```

On the **VM** (stop web workers briefly to avoid conflicts):

```bash
cd ~/frappe-bench
export PATH="$HOME/.local/bin:$PATH"

bench --site lms.embleconsulting.com restore /tmp/lms-restore/2026*_database.sql.gz
bench --site lms.embleconsulting.com restore --with-public-files /tmp/lms-restore/2026*_files.tar
bench --site lms.embleconsulting.com migrate
bench --site lms.embleconsulting.com clear-cache
```

After restore, reset the Administrator password if needed:

```bash
bench --site lms.embleconsulting.com set-admin-password 'NEW_ADMIN_PASSWORD'
```

### Option B — fresh demo seed on the VM

```bash
bench --site lms.embleconsulting.com execute lms_saas.setup.seed_demo.run_bulk --kwargs '{"count":16}'
```

Interest accrual must run before repayments behave correctly:

```bash
bench --site lms.embleconsulting.com execute lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual.process_loan_interest_accrual_for_term_loans
```

---

## 8. Portal pilot users

For each volunteer borrower:

1. Create **Customer** with email address.
2. Create **User** with the same email; assign role **Customer**.
3. Add **Contact** linked to the Customer (email must match the User).
4. On **LMS Borrower Compliance**: set KYC **Approved**, `consent_given = 1`,
   and `consent_date`.
5. User opens https://lms.embleconsulting.com/lms after login.

Staff roles (LMS Admin, Branch Manager, Loan Officer, Collector) are seeded by
`lms_saas.install.after_install` — assign users via **Role Manager**.

---

## 9. Email and SMS (optional for pilot)

Configure in Desk after first login:

| Integration | Where |
|-------------|-------|
| Outgoing email | Setup → Email Account |
| SMS gateway | Setup → SMS Settings (`sms_gateway_url` JSON POST) |

Do **not** put API keys in code or Git. Use Desk settings or `site_config.json`
on the server only.

---

## 10. Backups on the VM

Daily cron as user `frappe`:

```bash
crontab -e
```

Add:

```cron
0 2 * * * cd /home/frappe/frappe-bench && /home/frappe/.local/bin/bench --site lms.embleconsulting.com backup --with-files >> /home/frappe/backup.log 2>&1
```

Backups land in:

`~/frappe-bench/sites/lms.embleconsulting.com/private/backups/`

See [BACKUP.md](BACKUP.md) for restore and off-site copy (S3, etc.).

---

## 11. Deploy updates from dev

When you change `lms_saas` locally:

```bash
# On VM — if using git:
cd ~/frappe-bench/apps/lms_saas && git pull

# Or rsync from dev:
# rsync -avz apps/lms_saas/ frappe@<VM_IP>:~/frappe-bench/apps/lms_saas/

cd ~/frappe-bench
bench --site lms.embleconsulting.com migrate
bench build --app lms_saas
bench --site lms.embleconsulting.com clear-cache
sudo supervisorctl restart all
```

Run tests before/after major changes:

```bash
bench --site lms.embleconsulting.com run-tests --module lms_saas.tests.test_calculations
```

---

## 12. Pre-pilot checklist

- [ ] https://lms.embleconsulting.com loads with valid SSL
- [ ] Scheduler enabled (`bench --site lms.embleconsulting.com doctor`)
- [ ] `verify_spec.run_all_checks` → overall OK
- [ ] Desk Loan Dashboard shows lending + LMS KPIs at `/app/dashboard-view/Loan Dashboard`
- [ ] Portal login works at `/lms`
- [ ] Sandbox limits in `site_config.json` (consent, max customers, end date)
- [ ] Credit bureau **disabled** or pointed at a sandbox API only
- [ ] Daily backup cron configured
- [ ] Administrator password stored securely (password manager)
- [ ] No production payment rails or real bureau credentials on staging

---

## 13. Troubleshooting

| Symptom | Fix |
|---------|-----|
| 502 Bad Gateway | `sudo supervisorctl status` — restart: `sudo supervisorctl restart all` |
| Assets/CSS missing | `bench build --app lms_saas` then `bench clear-cache` |
| Scheduler not running | `bench --site lms.embleconsulting.com enable-scheduler` |
| MariaDB charset errors | Confirm utf8mb4 in `/etc/mysql/mariadb.conf.d/50-server.cnf` |
| Certbot fails | DNS must point to VM; port 80 open; wait for TTL |
| Negative outstanding on portal | Run migrate; ensure latest `lms_saas` is deployed |
| Loan repayments fail | Run interest accrual job (see section 7) |

Logs:

```bash
tail -f ~/frappe-bench/logs/web.error.log
tail -f ~/frappe-bench/logs/worker.error.log
sudo tail -f /var/log/nginx/error.log
```

---

## Related docs

- [SYSADMIN_GUIDE.md](SYSADMIN_GUIDE.md) — full system administrator reference
- [STAFF_GUIDE.md](STAFF_GUIDE.md) — onboard desk staff (roles, workflows, FAQs)
- [SETUP.md](SETUP.md) — app stack, cron jobs, verification
- [COMPLIANCE.md](COMPLIANCE.md) — RBZ sandbox mapping
- [BACKUP.md](BACKUP.md) — backup and restore
- [BRANDING.md](BRANDING.md) — desk/portal UI assets
