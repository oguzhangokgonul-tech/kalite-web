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


def test_image_migration_round_trip_keeps_existing_notes(tmp_path):
    path = Path(__file__).parents[1] / "migrations/versions/202611040001_ohs_note_images.py"
    spec = importlib.util.spec_from_file_location("ohs_note_images_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'images.db'}")
    try:
        with engine.begin() as conn:
            for table in ("companies", "users"):
                conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
                conn.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
            conn.execute(text("CREATE TABLE ohs_notes (id INTEGER PRIMARY KEY, title TEXT)"))
            conn.execute(text("INSERT INTO ohs_notes (id, title) VALUES (1, 'Kaygan zemin')"))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            migration.upgrade()
            conn.execute(text("INSERT INTO ohs_note_images (company_id, note_id, uploaded_by_user_id, original_name, stored_path, mime_type, size_bytes) VALUES (1, 1, 1, 'foto.png', 'company-001/ohs-notes/1/a.png', 'image/png', 3)"))
            assert conn.execute(text("SELECT COUNT(*) FROM ohs_note_images")).scalar_one() == 1
            migration.downgrade()
            assert not inspect(conn).has_table("ohs_note_images")
            assert conn.execute(text("SELECT title FROM ohs_notes")).scalar_one() == "Kaygan zemin"
            migration.upgrade()
            assert inspect(conn).has_table("ohs_note_images")
            assert conn.execute(text("SELECT title FROM ohs_notes")).scalar_one() == "Kaygan zemin"
    finally:
        engine.dispose()
