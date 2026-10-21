"""Disposable local preview; no production data or outbound mail."""
from pathlib import Path
from tempfile import TemporaryDirectory

from app import create_app
from app.extensions import db
from app.seed import ensure_default_roles
from tests.helpers import create_company, create_user


if __name__ == "__main__":
    with TemporaryDirectory(prefix="volka-ohs-notes-") as folder:
        class PreviewConfig:
            SECRET_KEY = "local-ohs-notes-preview-only"
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///" + (Path(folder) / "preview.db").as_posix()
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            UPLOAD_FOLDER = str(Path(folder) / "uploads")
            MAIL_ENABLED = False
            AUTO_BOOTSTRAP_DATABASE = False
            NOTIFICATION_AUTO_REMINDERS_ENABLED = False
            TENANT_BASE_DOMAIN = "volkaportal.com"
            WTF_CSRF_ENABLED = True
            LOGIN_MAX_FAILED_ATTEMPTS = 10
            LOGIN_IP_MAX_FAILED_ATTEMPTS = 100
            LOGIN_LOCKOUT_MINUTES = 10
            TEMPLATES_AUTO_RELOAD = True

        app = create_app(PreviewConfig)
        with app.app_context():
            db.create_all()
            ensure_default_roles()
            company = create_company("001")
            for name, role in (("personel", "department_staff"), ("yonetici", "management_representative")):
                user = create_user(name, company=company, role_key=role)
                user.set_password("Local-preview-001")
            db.session.commit()
        app.run(host="127.0.0.1", port=5134, use_reloader=False, threaded=True)
