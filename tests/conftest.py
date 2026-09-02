from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.seed import ensure_default_roles


@pytest.fixture()
def app(tmp_path):
    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"
        PASSWORD_MIN_LENGTH = 4
        MAIL_ENABLED = False

    test_app = create_app(TestConfig)
    with test_app.app_context():
        db.create_all()
        ensure_default_roles()
        db.session.commit()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
