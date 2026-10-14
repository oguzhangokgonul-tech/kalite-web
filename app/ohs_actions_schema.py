"""Additive action classification for databases created before OHS actions."""
from sqlalchemy import inspect, text


def ensure_ohs_actions_schema(engine=None):
    """Keep legacy actions general without rebuilding the shared actions table."""
    if engine is None:
        from .extensions import db
        engine = db.engine

    with engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table("actions"):
            return
        columns = {column["name"] for column in inspector.get_columns("actions")}
        if "action_category" not in columns:
            connection.execute(text(
                "ALTER TABLE actions ADD COLUMN action_category "
                "VARCHAR(16) NOT NULL DEFAULT 'general'"
            ))
        connection.execute(text(
            "UPDATE actions SET action_category = 'general' "
            "WHERE action_category IS NULL OR trim(action_category) = ''"
        ))
        indexes = {index["name"] for index in inspector.get_indexes("actions")}
        if "ix_actions_action_category" not in indexes:
            connection.execute(text(
                "CREATE INDEX ix_actions_action_category ON actions (action_category)"
            ))
