from flask import Flask
from flask.cli import with_appcontext
from pathlib import Path
import click

from .config import Config
from .extensions import db, migrate
from .routes import bp
from .seed import ensure_default_users


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    app.register_blueprint(bp)

    @app.cli.command("seed-users")
    @with_appcontext
    def seed_users_command():
        ensure_default_users(reset_passwords=True)
        print("Varsayılan kullanıcılar oluşturuldu/güncellendi.")

    @app.cli.command("test-mail")
    @click.argument("to_address")
    @with_appcontext
    def test_mail_command(to_address):
        from .mail import send_email

        sent = send_email(
            to_address,
            "Aksiyon Takip test maili",
            "Bu e-posta Aksiyon Takip mail ayarlarını test etmek için gönderildi.",
        )
        if sent:
            print(f"Test maili gönderildi: {to_address}")
        else:
            print(
                "Mail gönderilmedi. MAIL_ENABLED, RESEND_API_KEY/RESEND_FROM "
                "veya SMTP ayarlarını kontrol edin."
            )

    return app
