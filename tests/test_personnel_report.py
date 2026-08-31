from pathlib import Path
from io import BytesIO
import zipfile
from xml.etree import ElementTree as ET

import pytest

from app import create_app
from app.extensions import db
from app.models import PersonnelContact, User


@pytest.fixture()
def app(tmp_path):
    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"

    test_app = create_app(TestConfig)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, user):
    with client.session_transaction() as session:
        session["user_id"] = user.id


def sheet_values(xlsx_bytes):
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(BytesIO(xlsx_bytes)) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.findall(".//m:row", namespace):
        values = []
        for cell in row.findall("m:c", namespace):
            text = cell.find("m:is/m:t", namespace)
            values.append(text.text if text is not None and text.text is not None else "")
        rows.append(values)
    return rows


def test_personnel_report_download_includes_active_and_deleted_contacts(app, client):
    user = User(
        username="report-user",
        full_name="Report User",
        password_hash="not-used",
        is_active=True,
    )
    active = PersonnelContact(
        full_name="Ayşe Yılmaz",
        phone="0555 111 22 33",
        title="Kalite Sorumlusu",
        department="Kalite",
        is_active=True,
    )
    deleted = PersonnelContact(
        full_name="Mehmet Öztürk",
        phone="0555 444 55 66",
        department="Bakım",
        is_active=False,
    )
    db.session.add_all([user, active, deleted])
    db.session.commit()

    login(client, user)
    response = client.get("/insan-kaynaklari/personel-listesi/rapor?q=raporda-filtre-yok")

    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response.headers["Content-Disposition"].startswith(
        "attachment; filename=personel-iletisim-listesi-"
    )

    rows = sheet_values(response.data)
    assert rows[0] == ["İsim Soyisim", "Telefon No", "Departman", "Durum"]
    assert ["Ayşe Yılmaz", "0555 111 22 33", "Kalite Sorumlusu", "Aktif"] in rows
    assert ["Mehmet Öztürk", "0555 444 55 66", "Bakım", "Silinmiş"] in rows


def test_personnel_report_button_is_visible_on_list_page(app, client):
    user = User(
        username="viewer",
        full_name="Viewer",
        password_hash="not-used",
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()

    login(client, user)
    response = client.get("/insan-kaynaklari/personel-listesi")

    assert response.status_code == 200
    assert "Rapor İndir" in response.get_data(as_text=True)
    assert "/insan-kaynaklari/personel-listesi/rapor" in response.get_data(as_text=True)
