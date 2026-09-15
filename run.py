import os
from app import create_app, db
from app.seed import ensure_default_users

app = create_app()


def bootstrap_development_database():
    """Prepare a local database without mutating production during WSGI import."""
    with app.app_context():
        db.create_all()
        reset_default_passwords = os.environ.get(
            "RESET_DEFAULT_USER_PASSWORDS", "false"
        ).lower() in {"1", "true", "yes", "on"}
        ensure_default_users(reset_passwords=reset_default_passwords)


if __name__ == "__main__":
    if app.config.get("APP_ENV") == "development" and os.environ.get("AUTO_BOOTSTRAP_DATABASE", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        bootstrap_development_database()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5001)),
        debug=app.config.get("APP_ENV") == "development",
    )
