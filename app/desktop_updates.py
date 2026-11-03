import re
from pathlib import Path

from flask import Blueprint, abort, current_app, send_file


bp = Blueprint("desktop_updates", __name__, url_prefix="/desktop-updates")
INSTALLER_NAME = re.compile(r"^VolkaPortal-Setup-\d+\.\d+\.\d+-win-x64\.exe$")


def release_dir():
    return Path(current_app.config["DESKTOP_UPDATE_DIR"])


@bp.get("/latest.json")
def latest():
    path = release_dir() / "latest.json"
    if not path.is_file():
        abort(404)
    response = send_file(path, mimetype="application/json", conditional=True)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/<name>")
def download(name):
    if not INSTALLER_NAME.fullmatch(name):
        abort(404)
    path = release_dir() / name
    if not path.is_file():
        abort(404)
    response = send_file(path, mimetype="application/octet-stream",
                         as_attachment=True, download_name=name, conditional=True)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
