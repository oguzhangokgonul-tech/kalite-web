"""Immutable links from a quality objective to its project and action plans."""
from sqlalchemy import event

from .extensions import db


class ObjectivePlanLink(db.Model):
    __tablename__ = 'objective_plan_links'
    __table_args__ = (
        db.UniqueConstraint('company_id', 'objective_id', 'kind',
                            name='uq_objective_plan_links_objective_kind'),
        db.UniqueConstraint('project_id', name='uq_objective_plan_links_project'),
        db.UniqueConstraint('action_id', name='uq_objective_plan_links_action'),
        db.CheckConstraint("kind IN ('project', 'action')", name='ck_objective_plan_links_kind'),
        db.CheckConstraint(
            "(kind = 'project' AND project_id IS NOT NULL AND action_id IS NULL) OR "
            "(kind = 'action' AND action_id IS NOT NULL AND project_id IS NULL)",
            name='ck_objective_plan_links_target'),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    objective_id = db.Column(db.Integer, db.ForeignKey('quality_objectives.id'), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project_records.id'))
    action_id = db.Column(db.Integer, db.ForeignKey('actions.id'))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


@event.listens_for(ObjectivePlanLink.__table__, 'after_create')
def install_objective_plan_guards(table, connection, **kwargs):
    from .objective_plan_schema import ensure_objective_plan_sqlite_guards
    ensure_objective_plan_sqlite_guards(connection)


@event.listens_for(ObjectivePlanLink.__table__, 'before_drop')
def remove_objective_plan_guards(table, connection, **kwargs):
    from .objective_plan_schema import drop_objective_plan_sqlite_guards
    drop_objective_plan_sqlite_guards(connection)
