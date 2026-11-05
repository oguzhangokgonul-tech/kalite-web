"""Company-scoped index of standards and live document references."""

from .extensions import db


class StandardDocumentationHeading(db.Model):
    __tablename__ = "standard_documentation_headings"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    related_standard = db.Column(db.String(200), nullable=True)
    technical_heading_no = db.Column(db.String(80), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    links = db.relationship(
        "StandardDocumentationLink",
        back_populates="heading",
        cascade="all, delete-orphan",
        order_by="(StandardDocumentationLink.sort_order, StandardDocumentationLink.id)",
    )


class StandardDocumentationLink(db.Model):
    __tablename__ = "standard_documentation_links"
    __table_args__ = (
        db.UniqueConstraint("heading_id", "document_id", name="uq_standard_documentation_heading_document"),
    )

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    heading_id = db.Column(db.Integer, db.ForeignKey("standard_documentation_headings.id"), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    heading = db.relationship("StandardDocumentationHeading", back_populates="links")
    document = db.relationship("Document")
