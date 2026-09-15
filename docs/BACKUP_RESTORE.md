# VolkaPortal Backup and Restore Runbook

This runbook covers the minimum production-safe backup and restore flow for the
current Flask + SQLite deployment.

Current live runtime (2026-09-15): `venv-py312` is active; `venv` remains the
old Python 3.8 rollback environment. Commands below use the active interpreter
and factory. Preserve the actual service environment (including its private
SECRET_KEY and database/upload paths); sudo does not inherit systemd settings.
See `LIVE_RUNTIME_2026-09-15.md` for verified backup evidence.

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

Stop the service and any other database/upload writers before the consistent
backup and code update. First prepare a separate Python environment if needed;
do not replace a working environment in place.

```bash
cd /var/www/aksiyon-takip
./venv-py312/bin/python --version
sudo systemctl stop aksiyon-takip
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app full-backup
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app backup-verify /var/data/aksiyon-takip/backups/full/volkaportal-backup-YYYYMMDD-HHMMSS.zip
```

Then deploy:

Verify the backup before proceeding and copy it off-server. Review duplicate
user/parameter evaluations before schema changes; never delete scores blindly.
The active interpreter must be Python 3.10 or newer.

```bash
sudo -u aksiyon git pull --ff-only origin main
sudo -u aksiyon ./venv-py312/bin/python -m pip install -r requirements.txt
sudo -u aksiyon ./venv-py312/bin/python -m pip check
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app db upgrade
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app tenant-health
sudo systemctl start aksiyon-takip
sudo systemctl status aksiyon-takip --no-pager -l
sudo journalctl -u aksiyon-takip -n 80 --no-pager -l
```

Run each command separately and stop if it fails. If migration or health checks
fail, keep the service stopped until the cause is resolved or the verified backup
is restored. The schema reconciliation migrations intentionally refuse downgrade:
they cannot distinguish pre-existing runtime tables from newly migrated tables.

## Restore Dry Run

Restore is dry-run by default and does not change live data:

```bash
cd /var/www/aksiyon-takip
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app restore-backup /path/to/volkaportal-backup.zip
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
sudo -u aksiyon env RESTORE_ENABLED=true ./venv-py312/bin/python -m flask --app app:create_app restore-backup /path/to/volkaportal-backup.zip --apply --confirm RESTORE_CANLI_VERIYI_EZER
sudo -u aksiyon ./venv-py312/bin/python -m flask --app app:create_app db upgrade
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
