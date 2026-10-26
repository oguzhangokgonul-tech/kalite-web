"""Exercise the payment schema on a pre-existing SQLite installation."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_payment_migration_upgrade_downgrade_upgrade(tmp_path):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/202610250004_payment_tracking.py"
    spec = importlib.util.spec_from_file_location("payment_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///" + (tmp_path / "payments.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                tables = set(sa.inspect(connection).get_table_names())
                assert {"payment_records", "payment_attachments"} <= tables
                migration.downgrade()
                assert "payment_records" not in sa.inspect(connection).get_table_names()
                migration.upgrade()
                assert "payment_attachments" in sa.inspect(connection).get_table_names()
    finally:
        engine.dispose()


def test_installment_migration_preserves_legacy_balances_and_is_idempotent(tmp_path):
    versions = Path(__file__).resolve().parents[1] / "migrations/versions"
    def load(name, file_name):
        spec = importlib.util.spec_from_file_location(name, versions / file_name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    base = load("payment_base_migration", "202610250004_payment_tracking.py")
    plan = load("payment_plan_migration", "202610260001_payment_installments.py")
    engine = sa.create_engine("sqlite:///" + (tmp_path / "legacy-payments.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO companies (id) VALUES (1)"))
            connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
            with Operations.context(MigrationContext.configure(connection)):
                base.upgrade()
                for index, (status, settled) in enumerate((
                    ("open", "0"), ("open", "25.50"), ("closed", "100"), ("cancelled", "12")), 1):
                    connection.execute(sa.text("""
                        INSERT INTO payment_records
                        (id, company_id, direction, counterparty, description, amount,
                         settled_amount, settled_on, due_date, created_by_user_id, status)
                        VALUES (:id, 1, 'receivable', 'Eski kayıt', 'Test', 100,
                                :settled, '2026-10-01', '2026-11-15', 1, :status)
                    """), {"id": index, "settled": settled, "status": status})
                plan.upgrade()
                connection.execute(sa.text("UPDATE payment_installments SET legacy_settled_on = NULL WHERE id = 2"))
                plan.upgrade()
                rows = connection.execute(sa.text("""
                    SELECT p.id, p.status, p.settled_amount, i.amount,
                           i.settled_amount, i.legacy_settled_amount, i.legacy_settled_on, i.due_date,
                           p.payment_method
                    FROM payment_records p JOIN payment_installments i ON i.record_id = p.id
                    ORDER BY p.id
                """)).all()
                assert len(rows) == 4
                assert [(row[1], float(row[2]), float(row[4])) for row in rows] == [
                    ("open", 0, 0), ("open", 25.5, 25.5),
                    ("closed", 100, 100), ("cancelled", 12, 12)]
                assert all(float(row[3]) == 100 and row[6] == "2026-10-01" and
                           row[7] == "2026-11-15" and row[8] == "unspecified" for row in rows)
                assert connection.execute(sa.text("SELECT COUNT(*) FROM payment_transactions")).scalar_one() == 0
                with pytest.raises(RuntimeError):
                    plan.downgrade()
    finally:
        engine.dispose()
