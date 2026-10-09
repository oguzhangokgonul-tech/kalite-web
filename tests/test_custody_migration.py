import hashlib
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from app.custody_models import CustodyRecord


def custody_legacy_snapshot(connection):
    """Fingerprint legacy schema/data without retaining customer values in failures."""
    excluded = ('custody_records', 'alembic_version')
    digest = hashlib.sha256()
    schema = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    ).fetchall()
    for kind, name, table, sql in schema:
        if table in excluded or (kind == 'trigger' and name.startswith('trg_custody_')):
            continue
        digest.update(repr((kind, name, table, sql)).encode('utf-8'))
        if kind == 'table':
            quoted = '"' + name.replace('"', '""') + '"'
            rows = sorted(
                hashlib.sha256(repr(row).encode('utf-8')).digest()
                for row in connection.execute('SELECT * FROM ' + quoted)
            )
            digest.update(str(len(rows)).encode('ascii'))
            for row_digest in rows:
                digest.update(row_digest)
    return digest.hexdigest()


def custody_fk_snapshot(connection):
    rows = sorted(repr(row) for row in connection.execute('PRAGMA foreign_key_check'))
    return hashlib.sha256(repr(rows).encode('utf-8')).hexdigest()


def custody_backup_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.mark.skipif(not os.environ.get('CUSTODY_BACKUP_ZIP'), reason='No custody production backup provided')
def test_backup_roundtrip(tmp_path):
    backup = Path(os.environ['CUSTODY_BACKUP_ZIP'])
    backup_before = custody_backup_digest(backup)
    try:
        # Remove the extracted production copy even when a rehearsal assertion fails.
        with tempfile.TemporaryDirectory(prefix='custody-copy-', dir=tmp_path) as directory:
            path = Path(directory) / 'rehearsal.db'
            with zipfile.ZipFile(backup) as archive, archive.open('database/actions.db') as source, path.open('xb') as target:
                shutil.copyfileobj(source, target)
            app = Flask('custody_backup_rehearsal', instance_path=directory)
            app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + path.as_posix()
            database = SQLAlchemy(app)
            Migrate(app, database, directory=str(Path(__file__).resolve().parents[1] / 'migrations'))
            try:
                with closing(sqlite3.connect(path)) as connection:
                    baseline = custody_legacy_snapshot(connection)
                    before_fk = custody_fk_snapshot(connection)
                    assert connection.execute('SELECT version_num FROM alembic_version').fetchall() == [('202610070001',)], 'Unexpected backup revision'
                    assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'Backup integrity check failed'
                    runner = app.test_cli_runner()
                    for direction, revision in [
                        ('upgrade', '202610080001'),
                        ('upgrade', '202610080001'),
                        ('downgrade', '202610070001'),
                        ('upgrade', '202610080001'),
                    ]:
                        result = runner.invoke(args=['db', direction, revision])
                        # Do not include CLI output or exceptions that may contain SQL values.
                        assert result.exit_code == 0, f'Custody {direction} to {revision} failed'
                        assert custody_legacy_snapshot(connection) == baseline, 'Legacy schema/data changed'
                        assert custody_fk_snapshot(connection) == before_fk, 'Foreign-key baseline changed'
                        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'Copy integrity check failed'
                        assert connection.execute('SELECT version_num FROM alembic_version').fetchall() == [(revision,)], 'Migration revision mismatch'
                        table_count = connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='custody_records'").fetchone()[0]
                        guard_count = connection.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND substr(name,1,12)='trg_custody_'").fetchone()[0]
                        assert table_count == (0 if direction == 'downgrade' else 1), 'Custody table state mismatch'
                        assert guard_count == (0 if direction == 'downgrade' else 9), 'Custody guard state mismatch'
                with app.app_context(), database.engine.connect() as connection:
                    context = MigrationContext.configure(connection, opts={
                        'compare_type': True, 'compare_server_default': True,
                        'include_object': lambda obj, name, kind, reflected, compare_to: name == 'custody_records' if kind == 'table' else True,
                    })
                    assert not compare_metadata(context, CustodyRecord.metadata), 'Custody metadata differs from migrated schema'
            finally:
                with app.app_context():
                    database.session.remove()
                    database.engine.dispose()
    finally:
        assert custody_backup_digest(backup) == backup_before, 'Source backup changed during rehearsal'


def test_upgrade_downgrade_upgrade_and_runtime_parity(tmp_path):
    path = tmp_path / 'custody.db'
    with sqlite3.connect(path) as c:
        c.executescript('''
        CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
        INSERT INTO alembic_version VALUES('202610070001');
        CREATE TABLE companies(id INTEGER PRIMARY KEY);
        INSERT INTO companies VALUES(1),(2);
        CREATE TABLE users(id INTEGER PRIMARY KEY, company_id INTEGER);
        INSERT INTO users VALUES(1,1),(2,2);
        CREATE TABLE roles(id INTEGER PRIMARY KEY, key VARCHAR(80));
        CREATE TABLE user_roles(user_id INTEGER, role_id INTEGER);
        CREATE TABLE personnel_contacts(id INTEGER PRIMARY KEY, company_id INTEGER);
        INSERT INTO personnel_contacts VALUES(1,1),(2,2);
        ''')
    app = Flask('custody_migration')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + path.as_posix()
    database = SQLAlchemy(app)
    Migrate(app, database, directory=str(Path(__file__).resolve().parents[1] / 'migrations'))
    runner = app.test_cli_runner()
    for direction, rev in [('upgrade','202610080001'), ('downgrade','202610070001'), ('upgrade','202610080001')]:
        result = runner.invoke(args=['db',direction,rev])
        assert result.exit_code == 0, result.output + repr(result.exception)
        with sqlite3.connect(path) as c:
            assert c.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            assert c.execute('SELECT * FROM companies').fetchall() == [(1,),(2,)]
            assert c.execute('SELECT * FROM users').fetchall() == [(1,1),(2,2)]
    with app.app_context(), database.engine.begin() as connection:
        context = MigrationContext.configure(connection, opts={'compare_type':True,'compare_server_default':True,
            'include_object':lambda obj,name,kind,reflected,compare_to: name=='custody_records' if kind=='table' else True})
        assert compare_metadata(context, CustodyRecord.metadata) == []
        CustodyRecord.__table__.drop(connection)
        CustodyRecord.__table__.create(connection)
        connection.execute(text("INSERT INTO custody_records(company_id,personnel_contact_id,item_name,assigned_date,created_by_user_id,request_token) VALUES(1,1,'Runtime','2026-10-08',1,'request')"))
        connection.execute(text("UPDATE alembic_version SET version_num='202610070001'"))
        connection.execute(text('DROP TRIGGER trg_custody_tenant_insert'))
        connection.execute(text("CREATE TRIGGER trg_custody_tenant_insert BEFORE INSERT ON custody_records BEGIN SELECT RAISE(ABORT, 'old guard'); END"))
    result = runner.invoke(args=['db','upgrade','202610080001'])
    assert result.exit_code == 0, result.output
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT item_name FROM custody_records').fetchall() == [('Runtime',)]
        assert c.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_custody_%'").fetchone()[0] == 9
        assert 'old guard' not in c.execute("SELECT sql FROM sqlite_master WHERE name='trg_custody_tenant_insert'").fetchone()[0]
    with app.app_context():
        database.engine.dispose()
