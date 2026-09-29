from datetime import date
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

import pytest

from app import create_app
from app.extensions import db
from app.models import Action, AppSetting, AuditLog, Company, CompanyModule, Dof, User, UserPermission
from app.record_analysis import similar_pairs, title_tokens


@pytest.fixture()
def app(tmp_path):
    class Config:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"
        AUTO_BOOTSTRAP_DATABASE = False
    application = create_app(Config)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def setup(app):
    companies = [Company(code="101", name="A Firma", slug="a"), Company(code="102", name="B Firma", slug="b")]
    db.session.add_all(companies)
    db.session.flush()
    user = User(username="analyst", full_name="Analiz Kullanıcısı", password_hash="unused",
                company_id=companies[0].id, is_active=True)
    user.extra_permissions.append(UserPermission(permission_key="reports.view"))
    db.session.add(user)
    db.session.flush()
    records = [
        Action(company_id=companies[0].id, action_number=1, title="Kalite kontrol cihazı arızası",
               responsible_user_id=user.id, description="Kaynak açıklaması", termin_date=date.today()),
        Action(company_id=companies[0].id, action_number=2, title="KALİTE KONTROL CİHAZI ARIZASI",
               responsible_user_id=user.id, is_completed=True),
        Action(company_id=companies[0].id, action_number=3, title="Yetkisiz aynı şirket kaydı"),
        Action(company_id=companies[1].id, action_number=4, title="Diğer şirket gizli kaydı",
               responsible_user_id=user.id),
    ]
    for record in records:
        record.responsible_owner = user.full_name
        record.termin_date = date.today()
    db.session.add_all(records)
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user.id
    return client, user, companies, records


def test_local_title_similarity_is_deterministic_and_bounded():
    assert title_tokens("İŞ GÜVENLİĞİ ve ışık") == title_tokens("is guvenligi isik")
    records = [{"id": i, "title": "Aynı kontrol cihazı"} for i in range(8)]
    pairs, total = similar_pairs(records)
    assert total == 28 and len(pairs) == 20
    assert all(p["score"] == 100 for p in pairs)
    assert similar_pairs([{"id": 1, "title": "ve"}, {"id": 2, "title": ""}]) == ([], 0)


def test_analysis_is_scoped_and_does_not_modify_source_or_mark_ai(setup):
    client, user, companies, records = setup
    before = [(r.id, r.title, r.is_completed) for r in Action.query.order_by(Action.id)]
    response = client.get("/rapor-merkezi/analiz")
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    body = response.get_data(as_text=True)
    assert "Kaynak açıklaması" in body
    assert "Yetkisiz aynı şirket kaydı" not in body
    assert "Diğer şirket gizli kaydı" not in body
    assert "Benzer Kayıt Adayları" in body and "%100" in body
    assert "Üretken AI yok" in body and "Excel İndir" not in body
    db.session.expire_all()
    assert before == [(r.id, r.title, r.is_completed) for r in Action.query.order_by(Action.id)]
    assert db.session.get(AppSetting, "sales_readiness:competitor_ai_assistants") is None


def test_export_requires_permission_and_has_scoped_valid_xlsx(setup):
    client, user, companies, records = setup
    assert client.get("/rapor-merkezi/analiz/excel").status_code == 403
    user.extra_permissions.append(UserPermission(permission_key="reports.export"))
    db.session.commit()
    response = client.get("/rapor-merkezi/analiz/excel")
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert archive.testzip() is None
        xml = "\n".join(archive.read(name).decode() for name in archive.namelist() if name.endswith('.xml'))
        for name in archive.namelist():
            if name.endswith('.xml'):
                ET.fromstring(archive.read(name))
    assert "Kaynak açıklaması" in xml
    assert "Diğer şirket gizli kaydı" not in xml
    assert "Yetkisiz aynı şirket kaydı" not in xml
    assert "Yerel başlık sözcük benzerliği" in xml
    assert AuditLog.query.filter_by(entity_type="ReportCenter", action="exported", company_id=companies[0].id).count() == 1


@pytest.mark.parametrize("path", ["/rapor-merkezi/analiz", "/rapor-merkezi/analiz/excel"])
def test_no_permission_or_no_company_denied(app, path):
    client = app.test_client()
    assert client.get(path).status_code == 302
    user = User(username="viewer", full_name="Viewer", password_hash="unused", is_active=True)
    db.session.add(user)
    db.session.commit()
    with client.session_transaction() as session:
        session["user_id"] = user.id
    assert client.get(path).status_code == 403
    user.extra_permissions.append(UserPermission(permission_key="reports.view"))
    db.session.commit()
    assert client.get(path).status_code == 400


def test_disabled_module_and_unknown_source(setup):
    client, user, companies, records = setup
    assert client.get("/rapor-merkezi/analiz?source=unknown").status_code == 404
    db.session.add(CompanyModule(company_id=companies[0].id, module_key="if_management", is_enabled=False))
    db.session.commit()
    assert client.get("/rapor-merkezi/analiz?source=dofs").status_code == 404
    db.session.add(CompanyModule(company_id=companies[0].id, module_key="report_center", is_enabled=False))
    db.session.commit()
    assert client.get("/rapor-merkezi/analiz").status_code == 403


def test_dof_visibility_and_no_normalization_write(setup):
    client, user, companies, records = setup
    mine = Dof(company_id=companies[0].id, dof_no="IF-1", title="Görünür uygunsuzluk",
               created_by_user_id=user.id, status="Açık", approval_step="legacy",
               nonconformity_description="<script>alert(1)</script>")
    db.session.add_all([mine, Dof(company_id=companies[0].id, dof_no="IF-2", title="Gizli uygunsuzluk"),
                       Dof(company_id=companies[1].id, dof_no="IF-3", title="Diğer firma uygunsuzluk", created_by_user_id=user.id)])
    db.session.commit()
    response = client.get("/rapor-merkezi/analiz?source=dofs")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Görünür uygunsuzluk" in body
    assert "Gizli uygunsuzluk" not in body and "Diğer firma uygunsuzluk" not in body
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    db.session.expire_all()
    assert db.session.get(Dof, mine.id).approval_step == "legacy"


def test_action_visible_through_linked_dof_is_included(setup):
    client, user, companies, records = setup
    dof = Dof(company_id=companies[0].id, dof_no="IF-LINK", title="Bağlı IF",
              created_by_user_id=user.id, status="Açık", approval_step="management_representative")
    db.session.add(dof)
    db.session.flush()
    linked = Action(company_id=companies[0].id, action_number=20, title="Bağlı IF üzerinden görünür aksiyon",
                    responsible_owner="Başka Kullanıcı", termin_date=date.today(), dof_id=dof.id)
    db.session.add(linked)
    db.session.commit()

    response = client.get("/rapor-merkezi/analiz?source=actions")

    assert response.status_code == 200
    assert "Bağlı IF üzerinden görünür aksiyon" in response.get_data(as_text=True)


def test_description_is_bounded_before_normalization(setup):
    client, user, companies, records = setup
    records[0].description = "A" * 9000 + "SON-ISARET"
    db.session.commit()
    response = client.get("/rapor-merkezi/analiz")
    body = response.get_data(as_text=True)
    assert "A" * 240 + "…" in body
    assert "SON-ISARET" not in body


def test_record_limit_is_applied_after_record_authorization(setup, monkeypatch):
    import app.record_analysis as analysis
    client, user, companies, records = setup
    monkeypatch.setattr(analysis, "RECORD_LIMIT", 1)
    response = client.get("/rapor-merkezi/analiz")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Kayıt sınırı uygulandı" in body
    assert "Son 1 kayıt kapsamı" in body
    assert "Kaynak açıklaması" not in body
