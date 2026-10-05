from .extensions import db
from sqlalchemy import event


class ProjectRecord(db.Model):
    __tablename__ = "project_records"
    __table_args__ = (
        db.UniqueConstraint("company_id", "id", name="uq_project_records_company_id"),
        db.CheckConstraint("status IN ('draft', 'active', 'completed', 'archived')", name="ck_project_records_status"),
        db.CheckConstraint("due_date >= start_date", name="ck_project_records_dates"),
    )
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    title = db.Column(db.String(240), nullable=False)
    description = db.Column(db.Text)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="draft", server_default="draft", index=True)
    completion_note = db.Column(db.Text)
    archive_note = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version_id}
    owner = db.relationship("User", foreign_keys=[owner_user_id],
        primaryjoin="and_(ProjectRecord.owner_user_id == User.id, ProjectRecord.company_id == User.company_id)")
    creator = db.relationship("User", foreign_keys=[created_by_user_id])
    tasks = db.relationship("ProjectTask", back_populates="project", order_by="ProjectTask.due_date, ProjectTask.id")

    @property
    def project_no(self):
        return f"PRJ-{self.created_at.year}-{self.id:04d}"

    @property
    def progress(self):
        tasks = [item for item in self.tasks if item.status != "cancelled"]
        return round(100 * sum(item.status == "completed" for item in tasks) / len(tasks)) if tasks else 0

    @property
    def completion_ready(self):
        tasks = [item for item in self.tasks if item.status != "cancelled"]
        return bool(tasks) and all(item.status == "completed" for item in tasks)

    @property
    def activation_ready(self):
        return bool(self.description and self.description.strip()) and any(
            item.status != "cancelled" for item in self.tasks)

    @property
    def archive_ready(self):
        return self.status in {"draft", "completed"} or (
            self.status == "active" and bool(self.tasks) and all(item.status == "cancelled" for item in self.tasks)
        )


class ProjectTask(db.Model):
    __tablename__ = "project_tasks"
    __table_args__ = (
        db.ForeignKeyConstraint(["company_id", "project_id"], ["project_records.company_id", "project_records.id"], name="fk_project_tasks_company_project"),
        db.CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'cancelled')", name="ck_project_tasks_status"),
        db.CheckConstraint("due_date >= start_date", name="ck_project_tasks_dates"),
    )
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, nullable=False, index=True)
    title = db.Column(db.String(240), nullable=False)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", server_default="pending", index=True)
    completion_note = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)
    version_id = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version_id}
    project = db.relationship("ProjectRecord", back_populates="tasks")
    owner = db.relationship("User", foreign_keys=[owner_user_id],
        primaryjoin="and_(ProjectTask.owner_user_id == User.id, ProjectTask.company_id == User.company_id)")


@event.listens_for(ProjectTask.__table__, "after_create")
def install_project_guards(table, connection, **kwargs):
    from .project_schema import ensure_project_sqlite_guards
    ensure_project_sqlite_guards(connection)


@event.listens_for(ProjectTask.__table__, "before_drop")
def remove_project_parent_guards(table, connection, **kwargs):
    from .project_schema import drop_project_sqlite_guards
    drop_project_sqlite_guards(connection)
