"""Disposable loopback-only company-code login preview."""
from pathlib import Path
from tempfile import TemporaryDirectory

from app import create_app
from app.extensions import db
from app.seed import ensure_default_roles
from tests.helpers import create_company, create_user


if __name__ == "__main__":
    with TemporaryDirectory(prefix="volka-login-preview-") as folder:
        class PreviewConfig:
            SECRET_KEY = "disposable-login-preview-only"
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///" + (Path(folder) / "preview.db").as_posix()
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            UPLOAD_FOLDER = str(Path(folder) / "uploads")
            MAIL_ENABLED = False
            AUTO_BOOTSTRAP_DATABASE = False
            NOTIFICATION_AUTO_REMINDERS_ENABLED = False
            TENANT_BASE_DOMAIN = "volkaportal.com"
            WTF_CSRF_ENABLED = True
            LOGIN_MAX_FAILED_ATTEMPTS = 5
            LOGIN_IP_MAX_FAILED_ATTEMPTS = 100
            LOGIN_LOCKOUT_MINUTES = 10
            TEMPLATES_AUTO_RELOAD = True
        app = create_app(PreviewConfig)
        with app.app_context():
            db.create_all()
            ensure_default_roles()
            for code in ("001", "002"):
                company = create_company(code)
                user = create_user("demo-user", company=company, role_key="department_staff")
                user.set_password("Local-preview-" + code)
            db.session.commit()
        app.run(host="127.0.0.1", port=5133, use_reloader=False, threaded=True)
