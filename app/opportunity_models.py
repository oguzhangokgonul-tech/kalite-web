from sqlalchemy import event

from .extensions import db


class Opportunity(db.Model):
    __tablename__ = "opportunities"
    __table_args__ = (
        db.CheckConstraint("status IN ('draft','active','realized','not_realized','archived')", name="ck_opportunities_status"),
        db.CheckConstraint("length(trim(title)) BETWEEN 1 AND 240", name="ck_opportunities_title"),
        db.CheckConstraint("likelihood IN (1,2,3,4,5) AND benefit IN (1,2,3,4,5)", name="ck_opportunities_scores"),
        db.CheckConstraint("due_date >= analysis_date AND (review_date IS NULL OR review_date >= analysis_date)", name="ck_opportunities_dates"),
        db.CheckConstraint("version_id > 0", name="ck_opportunities_version"),
        db.CheckConstraint(
            "status NOT IN ('active','realized','not_realized') OR ("
            "length(trim(coalesce(description,''))) > 0 AND "
            "length(trim(coalesce(expected_benefit,''))) > 0 AND "
            "length(trim(coalesce(planned_action,''))) > 0 AND "
            "length(trim(coalesce(success_criteria,''))) > 0 AND review_date IS NOT NULL)",
            name="ck_opportunities_active"),
        db.CheckConstraint(
            "status NOT IN ('realized','not_realized') OR ("
            "length(trim(coalesce(result_note,''))) > 0 AND "
            "length(trim(coalesce(evidence_sources,''))) > 0 AND "
            "reviewed_at IS NOT NULL AND reviewed_by_user_id IS NOT NULL)", name="ck_opportunities_closed"),
        db.CheckConstraint(
            "status NOT IN ('draft','active') OR (result_note IS NULL AND evidence_sources IS NULL "
            "AND reviewed_at IS NULL AND reviewed_by_user_id IS NULL)", name="ck_opportunities_open"),
        db.CheckConstraint("status != 'archived' OR length(trim(coalesce(archive_note,''))) > 0", name="ck_opportunities_archive"),
    )
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    title = db.Column(db.String(240), nullable=False)
    description = db.Column(db.Text)
    expected_benefit = db.Column(db.Text)
    planned_action = db.Column(db.Text)
    success_criteria = db.Column(db.Text)
    source_reference = db.Column(db.Text)
    likelihood = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    benefit = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    analysis_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False, index=True)
    review_date = db.Column(db.Date, index=True)
    action_id = db.Column(db.Integer, db.ForeignKey("actions.id"), index=True)
    status = db.Column(db.String(20), nullable=False, default="draft", server_default="draft", index=True)
    result_note = db.Column(db.Text)
    evidence_sources = db.Column(db.Text)
    reviewed_at = db.Column(db.DateTime)
    archive_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version_id}
    owner = db.relationship("User", foreign_keys=[owner_user_id],
        primaryjoin="and_(Opportunity.owner_user_id == User.id, Opportunity.company_id == User.company_id)")
    creator = db.relationship("User", foreign_keys=[created_by_user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by_user_id])

    @property
    def priority_score(self):
        return (self.likelihood or 0) * (self.benefit or 0)

    @property
    def record_no(self):
        return f"FRS-{(self.created_at or self.analysis_date).year}-{self.id:04d}"


@event.listens_for(Opportunity.__table__, "after_create")
def install_opportunity_guards(table, connection, **kwargs):
    from .opportunity_schema import ensure_opportunity_sqlite_guards
    ensure_opportunity_sqlite_guards(connection)


@event.listens_for(Opportunity.__table__, "before_drop")
def remove_opportunity_guards(table, connection, **kwargs):
    from .opportunity_schema import drop_opportunity_sqlite_guards
    drop_opportunity_sqlite_guards(connection)
