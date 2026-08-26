from pathlib import Path
from datetime import timedelta
import os


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "instance"))
DATABASE_PATH = (DATA_DIR / "actions.db").as_posix()
UPLOAD_FOLDER = DATA_DIR / "uploads"
APP_ENV = os.environ.get("APP_ENV", os.environ.get("FLASK_ENV", "development")).lower()
IS_PRODUCTION = APP_ENV == "production"
SECRET_KEY = os.environ.get("SECRET_KEY")

if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError(
        "Production ortamında SECRET_KEY environment variable olarak tanımlanmalıdır."
    )


class Config:
    APP_ENV = APP_ENV
    SITE_NAME = os.environ.get("SITE_NAME", "VolkaPortal")
    ASSET_VERSION = os.environ.get("ASSET_VERSION", "20260826-document-flow-cards")
    SECRET_KEY = SECRET_KEY or "dev-only-change-me"
    DATA_DIR = str(DATA_DIR)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATABASE_PATH}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", str(UPLOAD_FOLDER))
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    TENANT_BASE_DOMAIN = os.environ.get("TENANT_BASE_DOMAIN", "volkaportal.com").lower()
    PREFERRED_URL_SCHEME = os.environ.get(
        "PREFERRED_URL_SCHEME",
        "https" if IS_PRODUCTION else "http",
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_DOMAIN = os.environ.get("SESSION_COOKIE_DOMAIN") or (
        f".{TENANT_BASE_DOMAIN}" if IS_PRODUCTION and TENANT_BASE_DOMAIN else None
    )
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    REMEMBER_ME_DAYS = int(os.environ.get("REMEMBER_ME_DAYS", "30"))
    PERMANENT_SESSION_LIFETIME = timedelta(days=REMEMBER_ME_DAYS)
    SESSION_REFRESH_EACH_REQUEST = True
    LOGIN_MAX_FAILED_ATTEMPTS = int(os.environ.get("LOGIN_MAX_FAILED_ATTEMPTS", "5"))
    LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", "10"))
    LOGIN_IP_MAX_FAILED_ATTEMPTS = int(
        os.environ.get("LOGIN_IP_MAX_FAILED_ATTEMPTS", "20")
    )
    PASSWORD_MIN_LENGTH = int(os.environ.get("PASSWORD_MIN_LENGTH", "4"))

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
