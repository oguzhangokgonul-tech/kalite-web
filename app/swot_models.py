from sqlalchemy import event

from .extensions import db


class SwotAnalysis(db.Model):
    __tablename__ = "swot_analyses"
    __table_args__ = (
        db.CheckConstraint("status IN ('draft', 'reviewed', 'archived')", name="ck_swot_analyses_status"),
        db.CheckConstraint("review_date > analysis_date", name="ck_swot_analyses_dates"),
        db.CheckConstraint("length(trim(title)) BETWEEN 1 AND 240", name="ck_swot_analyses_title"),
        db.CheckConstraint("version_id > 0", name="ck_swot_analyses_version"),
        db.CheckConstraint(
            "status != 'reviewed' OR ("
            "length(trim(coalesce(strengths, ''))) > 0 AND "
            "length(trim(coalesce(weaknesses, ''))) > 0 AND "
            "length(trim(coalesce(opportunities, ''))) > 0 AND "
            "length(trim(coalesce(threats, ''))) > 0 AND "
            "length(trim(coalesce(strategy, ''))) > 0 AND "
            "length(trim(coalesce(review_note, ''))) > 0 AND "
            "reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_swot_analyses_reviewed",
        ),
        db.CheckConstraint(
            "status != 'draft' OR (review_note IS NULL AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="ck_swot_analyses_draft",
        ),
        db.CheckConstraint(
            "status != 'archived' OR length(trim(coalesce(archive_note, ''))) > 0",
            name="ck_swot_analyses_archive",
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
    strengths = db.Column(db.Text)
    weaknesses = db.Column(db.Text)
    opportunities = db.Column(db.Text)
    threats = db.Column(db.Text)
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
        primaryjoin="and_(SwotAnalysis.owner_user_id == User.id, SwotAnalysis.company_id == User.company_id)")
    creator = db.relationship("User", foreign_keys=[created_by_user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by_user_id])

    @property
    def record_no(self):
        return f"SWOT-{self.analysis_date.year}-{self.id:04d}"


@event.listens_for(SwotAnalysis.__table__, "after_create")
def install_swot_guards(table, connection, **kwargs):
    from .swot_schema import ensure_swot_sqlite_guards
    ensure_swot_sqlite_guards(connection)


@event.listens_for(SwotAnalysis.__table__, "before_drop")
def remove_swot_guards(table, connection, **kwargs):
    from .swot_schema import drop_swot_sqlite_guards
    drop_swot_sqlite_guards(connection)
