from flask import Flask
from flask.cli import with_appcontext
from pathlib import Path
from dotenv import load_dotenv
import click

load_dotenv()

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
        ensure_default_users(reset_passwords=False)
        print("Varsayılan kullanıcılar oluşturuldu/güncellendi.")

    @app.cli.command("test-mail")
    @click.argument("to_address")
    @with_appcontext
    def test_mail_command(to_address):
        from .mail import send_test_email

        if send_test_email(to_address):
            print(f"Test e-postası gönderildi: {to_address}")
        else:
            print("Mail gönderilemedi. MAIL_ENABLED ve SMTP ayarlarını kontrol edin.")

    return app
