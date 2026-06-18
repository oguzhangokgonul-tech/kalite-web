from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "instance"))
DATABASE_PATH = (DATA_DIR / "actions.db").as_posix()
UPLOAD_FOLDER = DATA_DIR / "uploads"


class Config:
    SITE_NAME = os.environ.get("SITE_NAME", "TOKEN")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    DATA_DIR = str(DATA_DIR)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATABASE_PATH}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", str(UPLOAD_FOLDER))
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

    MAIL_ENABLED = os.environ.get("MAIL_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    MAIL_SUPPRESS_SEND = os.environ.get("MAIL_SUPPRESS_SEND", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
    MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "")
    MAIL_SUBJECT_PREFIX = os.environ.get("MAIL_SUBJECT_PREFIX", f"[{SITE_NAME}]")
    MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT", "10"))
