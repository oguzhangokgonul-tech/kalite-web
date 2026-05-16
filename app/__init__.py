from flask import Flask
from flask.cli import with_appcontext
from pathlib import Path

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

    return app
