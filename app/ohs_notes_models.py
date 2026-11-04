from .extensions import db


class OhsNote(db.Model):
    __tablename__ = "ohs_notes"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200))
    action_id = db.Column(db.Integer, db.ForeignKey("actions.id", ondelete="SET NULL"), unique=True)
    converted_at = db.Column(db.DateTime)
    deleted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version_id}
    author = db.relationship("User", foreign_keys=[author_id])
    action = db.relationship("Action", foreign_keys=[action_id])
    images = db.relationship("OhsNoteImage", back_populates="note", order_by="OhsNoteImage.id")

    @property
    def number(self):
        return f"ISG-N-{self.id:04d}"


class OhsNoteImage(db.Model):
    __tablename__ = "ohs_note_images"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    note_id = db.Column(db.Integer, db.ForeignKey("ohs_notes.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(30), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    deleted_at = db.Column(db.DateTime)

    note = db.relationship("OhsNote", back_populates="images")
