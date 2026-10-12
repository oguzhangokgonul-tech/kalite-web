import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_evidence_migration_round_trip_preserves_legacy_files(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/202610120001_feedback_evidence_stage.py'
    spec = importlib.util.spec_from_file_location('feedback_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite:///' + (tmp_path / 'migration.db').as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(sa.text('CREATE TABLE complaint_files (id INTEGER PRIMARY KEY, original_name VARCHAR(255))'))
            connection.execute(sa.text("INSERT INTO complaint_files VALUES (1, 'old.png')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                assert connection.execute(sa.text('SELECT evidence_stage FROM complaint_files')).scalar() == 'general'
                migration.downgrade()
                assert connection.execute(sa.text('SELECT original_name FROM complaint_files')).scalar() == 'old.png'
                migration.upgrade()
                assert connection.execute(sa.text('SELECT evidence_stage FROM complaint_files')).scalar() == 'general'
    finally:
        engine.dispose()
