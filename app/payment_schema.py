"""Idempotent runtime schema reconciliation for payment plans."""

import sqlalchemy as sa

from .extensions import db
from .payment_models import PaymentAttachment, PaymentInstallment, PaymentRecord, PaymentTransaction


def ensure_payment_schema():
    PaymentRecord.__table__.create(bind=db.engine, checkfirst=True)
    PaymentAttachment.__table__.create(bind=db.engine, checkfirst=True)
    with db.engine.begin() as connection:
        columns = {item["name"] for item in sa.inspect(connection).get_columns("payment_records")}
        if "payment_method" not in columns:
            connection.execute(sa.text(
                "ALTER TABLE payment_records ADD COLUMN payment_method VARCHAR(20) NOT NULL DEFAULT 'unspecified'"
            ))
    PaymentInstallment.__table__.create(bind=db.engine, checkfirst=True)
    PaymentTransaction.__table__.create(bind=db.engine, checkfirst=True)
    with db.engine.begin() as connection:
        columns = {item["name"] for item in sa.inspect(connection).get_columns("payment_installments")}
        if "legacy_settled_on" not in columns:
            connection.execute(sa.text("ALTER TABLE payment_installments ADD COLUMN legacy_settled_on DATE"))
        connection.execute(sa.text("""
            INSERT INTO payment_installments
                (company_id, record_id, sequence_no, amount, settled_amount, legacy_settled_amount, legacy_settled_on, due_date)
            SELECT p.company_id, p.id, 1, p.amount, p.settled_amount, p.settled_amount, p.settled_on, p.due_date
            FROM payment_records AS p
            WHERE NOT EXISTS (
                SELECT 1 FROM payment_installments AS i WHERE i.record_id = p.id
            )
        """))
        connection.execute(sa.text("""
            UPDATE payment_installments
            SET legacy_settled_on = (
                SELECT p.settled_on FROM payment_records AS p WHERE p.id = payment_installments.record_id
            )
            WHERE legacy_settled_amount > 0 AND legacy_settled_on IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM payment_transactions AS t
                  WHERE t.record_id = payment_installments.record_id
              )
        """))
