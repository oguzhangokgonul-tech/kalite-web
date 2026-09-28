"""Add tenant API, webhook and ERP integration foundation.

Revision ID: 202609280002
Revises: 202609280001
Create Date: 2026-09-28
"""

from alembic import op
import sqlalchemy as sa


revision = "202609280002"
down_revision = "202609280001"
branch_labels = None
depends_on = None


def _create_sqlite_tenant_triggers(table_name, predicate):
    if op.get_bind().dialect.name != "sqlite":
        return
    for operation in ("INSERT", "UPDATE"):
        trigger_name = f"trg_{table_name}_tenant_{operation.lower()}"
        op.execute(
            sa.text(
                f"CREATE TRIGGER IF NOT EXISTS {trigger_name} BEFORE {operation} ON {table_name} "
                f"WHEN NOT ({predicate}) "
                "BEGIN SELECT RAISE(ABORT, 'integration tenant mismatch'); END"
            )
        )


def _drop_sqlite_tenant_triggers():
    if op.get_bind().dialect.name != "sqlite":
        return
    for table_name in (
        "webhook_deliveries",
        "webhook_delivery_attempts",
        "integration_api_requests",
        "integration_api_rate_buckets",
        "integration_api_auth_rate_buckets",
    ):
        for operation in ("insert", "update"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table_name}_tenant_{operation}"))


def upgrade():
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    required_tables = {
        "integration_api_clients",
        "integration_api_rate_buckets",
        "webhook_endpoints",
        "integration_events",
        "webhook_deliveries",
        "webhook_delivery_attempts",
        "integration_api_requests",
    }
    if required_tables.issubset(existing_tables):
        _create_sqlite_tenant_triggers(
            "webhook_deliveries",
            "EXISTS (SELECT 1 FROM webhook_endpoints e "
            "WHERE e.id = NEW.webhook_endpoint_id AND e.company_id = NEW.company_id) "
            "AND EXISTS (SELECT 1 FROM integration_events i "
            "WHERE i.id = NEW.integration_event_id AND i.company_id = NEW.company_id)",
        )
        _create_sqlite_tenant_triggers(
            "webhook_delivery_attempts",
            "EXISTS (SELECT 1 FROM webhook_deliveries d "
            "WHERE d.id = NEW.delivery_id AND d.company_id = NEW.company_id)",
        )
        _create_sqlite_tenant_triggers(
            "integration_api_requests",
            "EXISTS (SELECT 1 FROM integration_api_clients c "
            "WHERE c.id = NEW.api_client_id AND c.company_id = NEW.company_id)",
        )
        _create_sqlite_tenant_triggers(
            "integration_api_rate_buckets",
            "EXISTS (SELECT 1 FROM integration_api_clients c "
            "WHERE c.id = NEW.api_client_id AND c.company_id = NEW.company_id)",
        )
        return
    op.create_table(
        "integration_api_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_last_four", sa.String(length=4), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "key_prefix", name="uq_integration_api_clients_company_prefix"),
        sa.UniqueConstraint("company_id", "id", name="uq_integration_api_clients_company_id"),
        sa.CheckConstraint("rate_limit_per_minute BETWEEN 1 AND 600", name="ck_integration_api_clients_rate_limit"),
    )
    op.create_index("ix_integration_api_clients_company_id", "integration_api_clients", ["company_id"])
    op.create_index("ix_integration_api_clients_key_prefix", "integration_api_clients", ["key_prefix"])

    op.create_table(
        "integration_api_rate_buckets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("api_client_id", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("api_client_id", "window_start", name="uq_integration_api_rate_bucket_window"),
        sa.ForeignKeyConstraint(
            ("company_id", "api_client_id"),
            ("integration_api_clients.company_id", "integration_api_clients.id"),
            name="fk_integration_api_rate_company_client",
        ),
        sa.CheckConstraint("request_count >= 1", name="ck_integration_api_rate_bucket_count"),
    )
    op.create_index("ix_integration_api_rate_buckets_company_id", "integration_api_rate_buckets", ["company_id"])
    op.create_index("ix_integration_api_rate_buckets_api_client_id", "integration_api_rate_buckets", ["api_client_id"])
    op.create_index("ix_integration_api_rate_buckets_window_start", "integration_api_rate_buckets", ["window_start"])

    op.create_table(
        "integration_api_auth_rate_buckets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "ip_hash",
            "window_start",
            name="uq_integration_api_auth_rate_bucket_window",
        ),
        sa.CheckConstraint(
            "request_count >= 1",
            name="ck_integration_api_auth_rate_bucket_count",
        ),
    )
    op.create_index(
        "ix_integration_api_auth_rate_buckets_ip_hash",
        "integration_api_auth_rate_buckets",
        ["ip_hash"],
    )
    op.create_index(
        "ix_integration_api_auth_rate_buckets_window_start",
        "integration_api_auth_rate_buckets",
        ["window_start"],
    )

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("events_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("disabled_reason", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "id", name="uq_webhook_endpoints_company_id"),
        sa.CheckConstraint("timeout_seconds BETWEEN 3 AND 10", name="ck_webhook_endpoints_timeout"),
    )
    op.create_index("ix_webhook_endpoints_company_id", "webhook_endpoints", ["company_id"])

    op.create_table(
        "integration_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_uuid", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("subject_type", sa.String(length=80), nullable=False),
        sa.Column("subject_id", sa.String(length=80), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("dispatched_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("company_id", "event_uuid", name="uq_integration_events_company_uuid"),
        sa.UniqueConstraint("company_id", "id", name="uq_integration_events_company_id"),
    )
    op.create_index("ix_integration_events_event_uuid", "integration_events", ["event_uuid"])
    op.create_index("ix_integration_events_company_id", "integration_events", ["company_id"])
    op.create_index("ix_integration_events_event_type", "integration_events", ["event_type"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_uuid", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("webhook_endpoint_id", sa.Integer(), nullable=False),
        sa.Column("integration_event_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("delivery_uuid", name="uq_webhook_deliveries_uuid"),
        sa.UniqueConstraint("company_id", "id", name="uq_webhook_deliveries_company_id"),
        sa.UniqueConstraint("webhook_endpoint_id", "integration_event_id", name="uq_webhook_delivery_endpoint_event"),
        sa.ForeignKeyConstraint(
            ("company_id", "webhook_endpoint_id"),
            ("webhook_endpoints.company_id", "webhook_endpoints.id"),
            name="fk_webhook_delivery_company_endpoint",
        ),
        sa.ForeignKeyConstraint(
            ("company_id", "integration_event_id"),
            ("integration_events.company_id", "integration_events.id"),
            name="fk_webhook_delivery_company_event",
        ),
        sa.CheckConstraint("status IN ('pending','processing','retry','delivered','failed')", name="ck_webhook_deliveries_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_webhook_deliveries_attempt_count"),
    )
    op.create_index("ix_webhook_deliveries_delivery_uuid", "webhook_deliveries", ["delivery_uuid"])
    op.create_index("ix_webhook_deliveries_company_id", "webhook_deliveries", ["company_id"])
    op.create_index("ix_webhook_deliveries_webhook_endpoint_id", "webhook_deliveries", ["webhook_endpoint_id"])
    op.create_index("ix_webhook_deliveries_integration_event_id", "webhook_deliveries", ["integration_event_id"])
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])
    op.create_index("ix_webhook_deliveries_next_attempt_at", "webhook_deliveries", ["next_attempt_at"])

    op.create_table(
        "webhook_delivery_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("delivery_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("response_excerpt", sa.String(length=500), nullable=True),
        sa.UniqueConstraint("delivery_id", "attempt_no", name="uq_webhook_attempt_delivery_no"),
        sa.ForeignKeyConstraint(
            ("company_id", "delivery_id"),
            ("webhook_deliveries.company_id", "webhook_deliveries.id"),
            name="fk_webhook_attempt_company_delivery",
        ),
        sa.CheckConstraint("attempt_no > 0", name="ck_webhook_attempt_number"),
    )
    op.create_index("ix_webhook_delivery_attempts_company_id", "webhook_delivery_attempts", ["company_id"])
    op.create_index("ix_webhook_delivery_attempts_delivery_id", "webhook_delivery_attempts", ["delivery_id"])

    op.create_table(
        "integration_api_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("api_client_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint", sa.String(length=160), nullable=False),
        sa.Column("method", sa.String(length=12), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("request_id", name="uq_integration_api_requests_request_id"),
        sa.ForeignKeyConstraint(
            ("company_id", "api_client_id"),
            ("integration_api_clients.company_id", "integration_api_clients.id"),
            name="fk_integration_api_request_company_client",
        ),
        sa.CheckConstraint("status_code >= 0", name="ck_integration_api_requests_status"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_integration_api_requests_duration"),
    )
    op.create_index("ix_integration_api_requests_company_id", "integration_api_requests", ["company_id"])
    op.create_index("ix_integration_api_requests_api_client_id", "integration_api_requests", ["api_client_id"])
    op.create_index("ix_integration_api_requests_request_id", "integration_api_requests", ["request_id"])
    op.create_index("ix_integration_api_requests_created_at", "integration_api_requests", ["created_at"])

    _create_sqlite_tenant_triggers(
        "webhook_deliveries",
        "EXISTS (SELECT 1 FROM webhook_endpoints e "
        "WHERE e.id = NEW.webhook_endpoint_id AND e.company_id = NEW.company_id) "
        "AND EXISTS (SELECT 1 FROM integration_events i "
        "WHERE i.id = NEW.integration_event_id AND i.company_id = NEW.company_id)",
    )
    _create_sqlite_tenant_triggers(
        "webhook_delivery_attempts",
        "EXISTS (SELECT 1 FROM webhook_deliveries d "
        "WHERE d.id = NEW.delivery_id AND d.company_id = NEW.company_id)",
    )
    _create_sqlite_tenant_triggers(
        "integration_api_requests",
        "EXISTS (SELECT 1 FROM integration_api_clients c "
        "WHERE c.id = NEW.api_client_id AND c.company_id = NEW.company_id)",
    )
    _create_sqlite_tenant_triggers(
        "integration_api_rate_buckets",
        "EXISTS (SELECT 1 FROM integration_api_clients c "
        "WHERE c.id = NEW.api_client_id AND c.company_id = NEW.company_id)",
    )

def downgrade():
    _drop_sqlite_tenant_triggers()
    op.execute(
        sa.text(
            "DELETE FROM app_settings "
            "WHERE key = 'sales_readiness:competitor_api_webhooks'"
        )
    )
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in (
        "integration_api_requests",
        "integration_api_auth_rate_buckets",
        "integration_api_rate_buckets",
        "webhook_delivery_attempts",
        "webhook_deliveries",
        "integration_events",
        "webhook_endpoints",
        "integration_api_clients",
    ):
        if table_name in existing_tables:
            op.drop_table(table_name)
