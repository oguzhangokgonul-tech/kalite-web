# SQLite Production Safety

VolkaPortal can run on file-based SQLite for early SaaS pilots. Before every live deploy,
take a checked backup and verify the active database.

## Pre-Deploy Checklist

```bash
cd /var/www/aksiyon-takip
sudo -u aksiyon ./venv/bin/flask db-check
sudo -u aksiyon ./venv/bin/flask db-backup
sudo -u aksiyon git pull
sudo systemctl restart aksiyon-takip
sudo systemctl status aksiyon-takip --no-pager
sudo journalctl -u aksiyon-takip -n 80 --no-pager
```

## Commands

`flask db-check`

- Resolves the configured SQLite file.
- Runs `PRAGMA quick_check`.
- Runs `PRAGMA integrity_check`.
- Shows the active Alembic version and the newest local migration revision.
- Writes an `AuditLog` row with `entity_type=DatabaseSafety`.

`flask db-backup`

- Uses the SQLite `backup()` API, so it is safer than a raw file copy while the app is running.
- Writes backups to `DATA_DIR/backups` by default.
- Verifies the created backup with quick and integrity checks.
- Keeps the latest 20 backups by default.
- Writes an `AuditLog` row with `entity_type=DatabaseSafety`.

## Environment Settings

```bash
DATABASE_BACKUP_DIR=/var/www/aksiyon-takip/instance/backups
DATABASE_BACKUP_KEEP_LAST=20
```

The backup directory must be writable by the service user:

```bash
sudo mkdir -p /var/www/aksiyon-takip/instance/backups
sudo chown -R aksiyon:aksiyon /var/www/aksiyon-takip/instance/backups
```

## Restore Note

Restore is intentionally not automated. Restoring a live database can overwrite customer
data, so it must be handled with a separate approval and a manual rollback procedure.
