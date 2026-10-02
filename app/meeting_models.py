from .extensions import db


class MeetingRecord(db.Model):
    __tablename__ = "meeting_records"
    __table_args__ = (
        db.UniqueConstraint("company_id", "id", name="uq_meeting_records_company_id"),
        db.CheckConstraint(
            "status IN ('draft', 'open', 'completed', 'archived')",
            name="ck_meeting_records_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    title = db.Column(db.String(240), nullable=False)
    meeting_at = db.Column(db.DateTime, nullable=False, index=True)
    location = db.Column(db.String(240))
    agenda = db.Column(db.Text)
    minutes = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="draft", server_default="draft", index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version_id}

    creator = db.relationship("User", foreign_keys=[created_by_user_id])
    participants = db.relationship(
        "MeetingParticipant", back_populates="meeting", cascade="all, delete-orphan",
        order_by="MeetingParticipant.id",
    )
    decisions = db.relationship("MeetingDecision", back_populates="meeting", order_by="MeetingDecision.id")

    @property
    def meeting_no(self):
        return f"TPL-{self.created_at.year}-{self.id:04d}" if self.id and self.created_at else None


class MeetingParticipant(db.Model):
    __tablename__ = "meeting_participants"
    __table_args__ = (
        db.UniqueConstraint("meeting_id", "user_id", name="uq_meeting_participants_meeting_user"),
        db.ForeignKeyConstraint(
            ["company_id", "meeting_id"], ["meeting_records.company_id", "meeting_records.id"],
            name="fk_meeting_participants_company_meeting",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    meeting_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    meeting = db.relationship("MeetingRecord", back_populates="participants")
    user = db.relationship(
        "User", foreign_keys=[user_id],
        primaryjoin="and_(MeetingParticipant.user_id == User.id, MeetingParticipant.company_id == User.company_id)",
    )


class MeetingDecision(db.Model):
    __tablename__ = "meeting_decisions"
    __table_args__ = (
        db.ForeignKeyConstraint(
            ["company_id", "meeting_id"], ["meeting_records.company_id", "meeting_records.id"],
            name="fk_meeting_decisions_company_meeting",
        ),
        db.CheckConstraint("status IN ('open', 'completed')", name="ck_meeting_decisions_status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    meeting_id = db.Column(db.Integer, nullable=False, index=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(240), nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="open", server_default="open", index=True)
    completion_note = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version_id}

    meeting = db.relationship("MeetingRecord", back_populates="decisions")
    owner = db.relationship(
        "User", foreign_keys=[owner_user_id],
        primaryjoin="and_(MeetingDecision.owner_user_id == User.id, MeetingDecision.company_id == User.company_id)",
    )
    action_link = db.relationship("MeetingDecisionAction", back_populates="decision", uselist=False)


class MeetingDecisionAction(db.Model):
    __tablename__ = "meeting_decision_actions"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    decision_id = db.Column(
        db.Integer, db.ForeignKey("meeting_decisions.id", ondelete="RESTRICT"), nullable=False, unique=True,
    )
    action_id = db.Column(
        db.Integer, db.ForeignKey("actions.id", ondelete="RESTRICT"), nullable=False, unique=True,
    )
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    decision = db.relationship("MeetingDecision", back_populates="action_link")
    action = db.relationship(
        "Action", foreign_keys=[action_id],
        primaryjoin="and_(MeetingDecisionAction.action_id == Action.id, MeetingDecisionAction.company_id == Action.company_id)",
    )
