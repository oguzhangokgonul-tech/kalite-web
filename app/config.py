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
