from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

import pytest

from app import create_app
from app.extensions import db
from app.models import Action, AppSetting, AuditLog, Company, CompanyModule, Dof, Role, User, UserPermission
from app.record_analysis import (
    ASSIST_MINUTE_LIMIT,
    LocalRulesProvider,
    similar_pairs,
    title_tokens,
)


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
        LEGAL_ACCEPTANCE_REQUIRED = False
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


def test_decision_support_requires_permission_then_audits_without_raw_content(setup):
    client, user, companies, records = setup
    before = [
        tuple(getattr(row, column.name) for column in Action.__table__.columns)
        for row in Action.query.order_by(Action.id)
    ]
    assert client.post("/rapor-merkezi/analiz/calistir", data={"source": "actions"}).status_code == 403

    user.extra_permissions.append(UserPermission(permission_key="reports.manage"))
    db.session.commit()
    assert client.post("/rapor-merkezi/analiz/calistir", data={"source": "actions"}).status_code == 403

    user.extra_permissions.append(UserPermission(permission_key="reports.assist"))
    db.session.commit()
    response = client.post("/rapor-merkezi/analiz/calistir", data={"source": "actions"})

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Karar desteği hazır" in body
    assert "Öncelikli Dikkat Noktaları" in body
    assert "Kayıt Kalitesi" in body
    assert "Önerilen Sonraki Adımlar" in body
    assert "veriler dış servise gönderilmedi" in body
    db.session.expire_all()
    assert before == [
        tuple(getattr(row, column.name) for column in Action.__table__.columns)
        for row in Action.query.order_by(Action.id)
    ]
    audit = AuditLog.query.filter_by(entity_type="DecisionSupport", action="generated").one()
    assert audit.company_id == companies[0].id and audit.user_id == user.id
    assert "Kaynak açıklaması" not in (audit.new_values or "")
    assert "algorithm_version" in audit.new_values and "result_hash" in audit.new_values
    assert db.session.get(AppSetting, "sales_readiness:competitor_ai_assistants") is None


def test_only_superadmin_account_marks_global_sales_checklist(setup):
    client, user, companies, records = setup
    role = Role(
        key="super_admin",
        name="Süper Admin",
        hierarchy_level=100,
        is_system=True,
    )
    db.session.add(role)
    user.username = "superadmin"
    user.company_id = None
    user.roles.append(role)
    db.session.commit()
    with client.session_transaction() as session:
        session["company_id"] = companies[0].id

    response = client.post(
        "/rapor-merkezi/analiz/calistir", data={"source": "actions"}
    )

    assert response.status_code == 200
    assert db.session.get(
        AppSetting, "sales_readiness:competitor_ai_assistants"
    ).value == "1"


def test_decision_support_is_deterministic_and_root_cause_guidance_is_evidence_linked():
    data = {
        "records": [
            {
                "id": 4, "code": "IF-4", "title": "Kaynak hatası", "url": "/dofs/4",
                "revision": "v1", "facts": {
                    "is_completed": False, "overdue": True, "due_soon": False,
                    "closure_waiting": False, "ineffective": False,
                    "description_present": True, "responsible_present": True,
                    "due_present": True, "requires_root_cause": True,
                    "root_cause_present": False, "root_cause_method_present": False,
                    "corrective_action_present": False, "closure_evidence_present": False,
                    "effectiveness_required": False, "effectiveness_done": False,
                },
            }
        ],
        "pairs": [], "pair_count": 0,
    }
    first = LocalRulesProvider().generate(data)
    second = LocalRulesProvider().generate(data)
    assert first == second
    assert first["result_hash"] == second["result_hash"]
    assert first["cause_hypotheses"][0]["record"]["url"] == "/dofs/4"
    assert {item["rule_code"] for item in first["data_quality_findings"]} >= {
        "ROOT_CAUSE_MISSING", "ROOT_CAUSE_METHOD_MISSING", "CORRECTIVE_ACTION_MISSING",
    }
    cause_action = next(
        item for item in first["recommended_next_steps"]
        if item["rule_code"] == "COMPLETE_CAUSE_ACTION"
    )
    assert cause_action["count"] == 1
    assert [record["id"] for record in cause_action["records"]] == [4]


def test_decision_support_rate_limit_is_company_and_user_scoped(setup):
    client, user, companies, records = setup
    user.extra_permissions.append(UserPermission(permission_key="reports.assist"))
    db.session.add_all([
        AuditLog(
            company_id=companies[0].id, user_id=user.id, entity_type="DecisionSupport",
            action="generated", summary="limit", ip_address="127.0.0.1",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        for _ in range(ASSIST_MINUTE_LIMIT)
    ])
    db.session.commit()
    response = client.post("/rapor-merkezi/analiz/calistir", data={"source": "actions"})
    assert response.status_code == 429
    assert AuditLog.query.filter_by(entity_type="DecisionSupport", action="generated").count() == ASSIST_MINUTE_LIMIT


def test_explicit_view_all_permissions_are_canonical_for_analysis(setup):
    client, user, companies, records = setup
    user.extra_permissions.append(UserPermission(permission_key="roles.manage"))
    db.session.commit()
    assert "Yetkisiz aynı şirket kaydı" not in client.get("/rapor-merkezi/analiz").get_data(as_text=True)
    user.extra_permissions.append(UserPermission(permission_key="actions.view_all"))
    db.session.commit()
    assert "Yetkisiz aynı şirket kaydı" in client.get("/rapor-merkezi/analiz").get_data(as_text=True)

    hidden_dof = Dof(company_id=companies[0].id, dof_no="IF-ALL", title="Tüm IF yetkisi")
    db.session.add(hidden_dof)
    db.session.commit()
    assert "Tüm IF yetkisi" not in client.get("/rapor-merkezi/analiz?source=dofs").get_data(as_text=True)
    user.extra_permissions.append(UserPermission(permission_key="if.view_all"))
    db.session.commit()
    assert "Tüm IF yetkisi" in client.get("/rapor-merkezi/analiz?source=dofs").get_data(as_text=True)


def test_export_requires_permission_and_has_scoped_valid_xlsx(setup):
    client, user, companies, records = setup
    assert client.get("/rapor-merkezi/analiz/excel").status_code in {403, 405}
    assert client.post("/rapor-merkezi/analiz/excel").status_code == 403
    user.extra_permissions.append(UserPermission(permission_key="reports.export"))
    db.session.commit()
    assert client.post("/rapor-merkezi/analiz/excel").status_code == 403
    user.extra_permissions.append(UserPermission(permission_key="reports.assist"))
    db.session.commit()
    response = client.post("/rapor-merkezi/analiz/excel")
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


@pytest.mark.parametrize(("path", "method"), [
    ("/rapor-merkezi/analiz", "get"),
    ("/rapor-merkezi/analiz/excel", "post"),
])
def test_no_permission_or_no_company_denied(app, path, method):
    client = app.test_client()
    request = getattr(client, method)
    assert request(path).status_code == 302
    user = User(username="viewer", full_name="Viewer", password_hash="unused", is_active=True)
    db.session.add(user)
    db.session.commit()
    with client.session_transaction() as session:
        session["user_id"] = user.id
    assert request(path).status_code == 403
    user.extra_permissions.append(UserPermission(permission_key="reports.view"))
    db.session.commit()
    assert request(path).status_code == 400


def test_disabled_module_and_unknown_source(setup):
    client, user, companies, records = setup
    assert client.get("/rapor-merkezi/analiz?source=unknown").status_code == 404
    db.session.add(CompanyModule(company_id=companies[0].id, module_key="if_management", is_enabled=False))
    db.session.commit()
    assert client.get("/rapor-merkezi/analiz?source=dofs").status_code == 404
    db.session.add(CompanyModule(company_id=companies[0].id, module_key="report_center", is_enabled=False))
    db.session.commit()
    assert client.get("/rapor-merkezi/analiz").status_code == 403


def test_decision_support_post_requires_csrf(tmp_path):
    class CsrfConfig:
        TESTING = True
        LEGAL_ACCEPTANCE_REQUIRED = False
        SECRET_KEY = "csrf-test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = True
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"
        AUTO_BOOTSTRAP_DATABASE = False

    application = create_app(CsrfConfig)
    with application.app_context():
        db.create_all()
        company = Company(code="201", name="CSRF Firma", slug="csrf")
        db.session.add(company)
        db.session.flush()
        user = User(
            username="csrf-user", full_name="CSRF User", password_hash="unused",
            company_id=company.id, is_active=True,
        )
        user.extra_permissions.extend([
            UserPermission(permission_key="reports.view"),
            UserPermission(permission_key="reports.assist"),
            UserPermission(permission_key="reports.export"),
        ])
        db.session.add_all([
            user,
            CompanyModule(company_id=company.id, module_key="report_center", is_enabled=True),
        ])
        db.session.commit()
        client = application.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user.id
        response = client.post(
            "/rapor-merkezi/analiz/calistir",
            data={"source": "actions"},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 400
        excel_response = client.post(
            "/rapor-merkezi/analiz/excel",
            headers={"Accept": "application/json"},
        )
        assert excel_response.status_code == 400
        assert AuditLog.query.filter_by(entity_type="DecisionSupport").count() == 0
        db.session.remove()
        db.drop_all()


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


def test_cross_company_linked_dof_never_grants_action_visibility(setup):
    client, user, companies, records = setup
    foreign_dof = Dof(
        company_id=companies[1].id,
        dof_no="IF-CROSS",
        title="Başka şirket IF kaydı",
        created_by_user_id=user.id,
        status="Açık",
        approval_step="management_representative",
    )
    db.session.add(foreign_dof)
    db.session.flush()
    cross_linked_action = Action(
        company_id=companies[0].id,
        action_number=21,
        title="Çapraz şirket bağlantısı görünmemeli",
        responsible_owner="Başka Kullanıcı",
        termin_date=date.today(),
        dof_id=foreign_dof.id,
    )
    db.session.add(cross_linked_action)
    db.session.commit()

    body = client.get("/rapor-merkezi/analiz?source=actions").get_data(as_text=True)

    assert "Çapraz şirket bağlantısı görünmemeli" not in body


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


def test_scan_limit_is_applied_after_sql_authorization(setup, monkeypatch):
    import app.record_analysis as analysis

    client, user, companies, records = setup
    hidden = Action(
        company_id=companies[0].id,
        action_number=99,
        title="En yeni fakat yetkisiz kayıt",
        responsible_owner="Başka Kullanıcı",
        termin_date=date.today(),
    )
    db.session.add(hidden)
    db.session.commit()
    monkeypatch.setattr(analysis, "SCAN_LIMIT", 1)

    body = client.get("/rapor-merkezi/analiz").get_data(as_text=True)

    assert "KALİTE KONTROL CİHAZI ARIZASI" in body
    assert "En yeni fakat yetkisiz kayıt" not in body


def test_effectiveness_waiting_action_is_not_counted_as_finally_completed(setup):
    client, user, companies, records = setup
    records[0].is_completed = True
    records[0].effectiveness_required = True
    records[0].effectiveness_result = "Bekliyor"
    user.extra_permissions.append(UserPermission(permission_key="reports.assist"))
    db.session.commit()

    body = client.post(
        "/rapor-merkezi/analiz/calistir", data={"source": "actions"}
    ).get_data(as_text=True)

    assert "1 tanesi açık, 1 tanesi tamamlanmış durumda" in body
