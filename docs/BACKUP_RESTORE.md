# VolkaPortal Backup and Restore Runbook

This runbook covers the minimum production-safe backup and restore flow for the
current Flask + SQLite deployment.

## What A Full Backup Contains

`flask full-backup` creates one zip package:

- SQLite database copy
- All files under `UPLOAD_FOLDER`
- `manifest.json`
- `checksums.json`

Default location:

```text
FULL_BACKUP_DIR=/var/data/aksiyon-takip/backups/full
```

## Before Every Deploy

Run a full backup before pulling new code:

```bash
cd /var/www/aksiyon-takip
sudo -u aksiyon ./venv/bin/python -m flask --app run.py full-backup
sudo -u aksiyon ./venv/bin/python -m flask --app run.py backup-verify /var/data/aksiyon-takip/backups/full/volkaportal-backup-YYYYMMDD-HHMMSS.zip
```

Then deploy:

```bash
sudo -u aksiyon git pull origin main
sudo -u aksiyon ./venv/bin/python -m flask --app run.py db upgrade
sudo systemctl restart aksiyon-takip
sudo systemctl status aksiyon-takip --no-pager -l
sudo journalctl -u aksiyon-takip -n 80 --no-pager -l
```

## Restore Dry Run

Restore is dry-run by default and does not change live data:

```bash
cd /var/www/aksiyon-takip
sudo -u aksiyon ./venv/bin/python -m flask --app run.py restore-backup /path/to/volkaportal-backup.zip
```

The dry-run validates:

- Zip structure
- Manifest format
- SHA256 checksums
- SQLite `quick_check`
- SQLite `integrity_check`

## Real Restore

Real restore overwrites the current database and upload folder. Do this only
after explicit leader approval.

Recommended live sequence:

```bash
cd /var/www/aksiyon-takip
sudo systemctl stop aksiyon-takip
sudo -u aksiyon env RESTORE_ENABLED=true ./venv/bin/python -m flask --app run.py restore-backup /path/to/volkaportal-backup.zip --apply --confirm RESTORE_CANLI_VERIYI_EZER
sudo -u aksiyon ./venv/bin/python -m flask --app run.py db upgrade
sudo systemctl start aksiyon-takip
sudo systemctl status aksiyon-takip --no-pager -l
sudo journalctl -u aksiyon-takip -n 80 --no-pager -l
```

The restore command automatically creates a pre-restore full backup before it
overwrites anything.

## Config

```text
DATABASE_BACKUP_DIR=/var/data/aksiyon-takip/backups
DATABASE_BACKUP_KEEP_LAST=20
FULL_BACKUP_DIR=/var/data/aksiyon-takip/backups/full
FULL_BACKUP_KEEP_LAST=10
BACKUP_INCLUDE_UPLOADS=true
RESTORE_ENABLED=false
```

Keep `RESTORE_ENABLED=false` in production. Enable it only for the single
restore command.

## Audit

Backup and restore operations write audit records to the database when possible.
Restore events are also appended to:

```text
DATA_DIR/backups/restore-events.log
```
