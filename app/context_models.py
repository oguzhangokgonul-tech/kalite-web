from sqlalchemy import event

from .extensions import db


class OrganizationContext(db.Model):
    __tablename__ = "organization_contexts"
    __table_args__ = (
        db.CheckConstraint("climate_relevance IN ('under_review', 'relevant', 'not_relevant')",
                           name="ck_organization_contexts_climate_relevance"),
        db.CheckConstraint("status IN ('draft', 'reviewed', 'archived')", name="ck_organization_contexts_status"),
        db.CheckConstraint("review_date > analysis_date", name="ck_organization_contexts_dates"),
        db.CheckConstraint("length(trim(title)) BETWEEN 1 AND 240", name="ck_organization_contexts_title"),
        db.CheckConstraint("version_id > 0", name="ck_organization_contexts_version"),
        db.CheckConstraint(
            "status != 'reviewed' OR ("
            "length(trim(coalesce(scope, ''))) > 0 AND "
            "length(trim(coalesce(internal_issues, ''))) > 0 AND "
            "length(trim(coalesce(external_issues, ''))) > 0 AND "
            "length(trim(coalesce(climate_reason, ''))) > 0 AND "
            "climate_relevance IN ('relevant', 'not_relevant') AND "
            "length(trim(coalesce(evidence_sources, ''))) > 0 AND "
            "length(trim(coalesce(strategy, ''))) > 0 AND "
            "length(trim(coalesce(review_note, ''))) > 0 AND "
            "reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_organization_contexts_reviewed",
        ),
        db.CheckConstraint(
            "status != 'draft' OR (review_note IS NULL AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="ck_organization_contexts_draft",
        ),
        db.CheckConstraint(
            "status != 'archived' OR length(trim(coalesce(archive_note, ''))) > 0",
            name="ck_organization_contexts_archive",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    title = db.Column(db.String(240), nullable=False)
    scope = db.Column(db.Text)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    analysis_date = db.Column(db.Date, nullable=False, index=True)
    review_date = db.Column(db.Date, nullable=False, index=True)
    internal_issues = db.Column(db.Text)
    external_issues = db.Column(db.Text)
    climate_relevance = db.Column(db.String(20), nullable=False, default="under_review", server_default="under_review")
    climate_reason = db.Column(db.Text)
    evidence_sources = db.Column(db.Text)
    strategy = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="draft", server_default="draft", index=True)
    review_note = db.Column(db.Text)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    archive_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version_id}
    owner = db.relationship("User", foreign_keys=[owner_user_id],
        primaryjoin="and_(OrganizationContext.owner_user_id == User.id, OrganizationContext.company_id == User.company_id)")
    creator = db.relationship("User", foreign_keys=[created_by_user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by_user_id])

    @property
    def record_no(self):
        year = (self.created_at or self.analysis_date).year
        return f"BAG-{year}-{self.id:04d}"


@event.listens_for(OrganizationContext.__table__, "after_create")
def install_context_guards(table, connection, **kwargs):
    from .context_schema import ensure_context_sqlite_guards
    ensure_context_sqlite_guards(connection)


@event.listens_for(OrganizationContext.__table__, "before_drop")
def remove_context_guards(table, connection, **kwargs):
    from .context_schema import drop_context_sqlite_guards
    drop_context_sqlite_guards(connection)
