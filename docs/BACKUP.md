# LMS Site Backup

Full backup/restore and disaster-recovery context: [SYSADMIN_GUIDE.md](SYSADMIN_GUIDE.md).

## Manual backup

```bash
cd frappe-bench
export PATH="$HOME/.local/bin:$PATH"
bench --site lms.localhost backup --with-files
```

Backups are stored under `sites/lms.localhost/private/backups/`.

## Scripted backup

```bash
./apps/lms_saas/scripts/backup-site.sh lms.localhost
```

## Restore

```bash
bench --site lms.localhost restore /path/to/database.sql.gz
bench --site lms.localhost restore --with-public-files /path/to/files.tar
```

## Off-site (S3)

Copy the latest `.sql.gz` and `files.tar` to your bucket after each backup. Example with AWS CLI:

```bash
aws s3 cp sites/lms.localhost/private/backups/ s3://your-bucket/lms-backups/ --recursive
```

Schedule via host cron (not managed by this repo).

## Production checklist

- Daily `bench backup` with files
- Test restore quarterly
- Encrypt backups at rest
- Restrict access to `sites/*/private/backups`
