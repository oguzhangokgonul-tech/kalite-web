from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = (BASE_DIR / "instance" / "actions.db").as_posix()
UPLOAD_FOLDER = BASE_DIR / "instance" / "uploads"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATABASE_PATH}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", str(UPLOAD_FOLDER))
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", os.environ.get("MAIL_USERNAME", "")
    )
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    MAIL_ENABLED = os.environ.get("MAIL_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
