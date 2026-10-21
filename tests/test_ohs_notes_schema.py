import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_upgrade_downgrade_upgrade_preserves_existing_records(tmp_path):
    path = Path(__file__).parents[1] / "migrations/versions/202610200001_ohs_notes.py"
    spec = importlib.util.spec_from_file_location("ohs_notes_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with engine.begin() as conn:
            for table in ("companies", "users", "actions"):
                conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
                conn.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            migration.upgrade()
            conn.execute(text("INSERT INTO ohs_notes (company_id,author_id,title,description) VALUES (1,1,'İSG','Türkçe')"))
            assert conn.execute(text("SELECT description, version_id FROM ohs_notes")).one() == ("Türkçe", 1)
            migration.downgrade()
            assert not inspect(conn).has_table("ohs_notes")
            migration.upgrade()
            assert inspect(conn).has_table("ohs_notes")
            assert {index["name"] for index in inspect(conn).get_indexes("ohs_notes")} == {"ix_ohs_notes_company_id"}
            for table in ("companies", "users", "actions"):
                assert conn.execute(text(f"SELECT id FROM {table}")).all() == [(1,)]
    finally:
        engine.dispose()
