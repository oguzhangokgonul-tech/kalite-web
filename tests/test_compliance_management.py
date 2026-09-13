from datetime import date, timedelta
from io import BytesIO

import pytest

from app.extensions import db
from app.models import (
    Action,
    AppSetting,
    AuditLog,
    CompanyDepartment,
    CompanyModule,
    ComplianceEvaluation,
    ComplianceFile,
    ComplianceObligation,
    ComplianceRevision,
    Notification,
)
from app.reminders import generate_due_reminders
from app.seed import ensure_runtime_schema

from .helpers import assert_xlsx_response, create_company, create_user, login, sheet_values


MANAGE_PERMISSIONS = (
    "compliance.view",
    "compliance.manage",
    "compliance.export",
    "compliance.archive",
    "compliance.evidence_download",
)


def setup_users(code="981"):
    company = create_company(code)
    db.session.add_all([
        CompanyDepartment(company_id=company.id, name="Kalite", sort_order=1),
        CompanyDepartment(company_id=company.id, name="Üretim", sort_order=2),
    ])
    db.session.commit()
    manager = create_user(
        f"compliance-manager-{code}", company=company,
        permissions=MANAGE_PERMISSIONS, full_name="Mevzuat Yöneticisi",
    )
    verifier = create_user(
        f"compliance-verifier-{code}", company=company,
        permissions=("compliance.view", "compliance.verify", "compliance.evidence_download"),
        full_name="Yönetim Doğrulayıcısı",
    )
    owner = create_user(
        f"compliance-owner-{code}", company=company,
        permissions=("compliance.view", "compliance.evaluate", "compliance.evidence_download"),
        full_name="Uygunluk Sorumlusu",
    )
    return company, manager, verifier, owner


def obligation_payload(owner, **overrides):
    values = {
        "title": "Çevre İzin ve Lisans Yükümlülüğü",
        "category": "Çevre",
        "authority": "Çevre, Şehircilik ve İklim Değişikliği Bakanlığı",
        "region": "Türkiye",
        "obligation_type": "Yönetmelik",
        "legal_reference": "RG 29115",
        "applicability_status": "applicable",
        "applicability_reason": "Üretim tesisi kapsam dahilindedir.",
        "department": "Kalite",
        "process": "Çevre Yönetimi",
        "owner_user_id": str(owner.id),
        "criticality": "high",
        "review_interval_months": "12",
        "next_review_date": (date.today() + timedelta(days=30)).isoformat(),
        "revision_no": "R0",
        "publication_date": date.today().isoformat(),
        "effective_date": date.today().isoformat(),
        "repeal_date": "",
        "official_source_url": "https://www.resmigazete.gov.tr/ornek",
        "change_summary": "İlk mevzuat kaydı ve uygulanabilir şartlar.",
    }
    values.update(overrides)
    return values


def create_obligation(client, manager, owner, **overrides):
    login(client, manager)
    response = client.post("/mevzuat-takibi/yeni", data=obligation_payload(owner, **overrides))
    assert response.status_code == 302
    return ComplianceObligation.query.filter_by(company_id=manager.company_id).one()


def verify(client, verifier, obligation):
    login(client, verifier)
    revision = ComplianceRevision.query.filter_by(obligation_id=obligation.id).one()
    response = client.post(f"/mevzuat-takibi/revizyon/{revision.id}/dogrula")
    assert response.status_code == 302
    db.session.refresh(obligation)
    db.session.refresh(revision)
    return revision


def test_crud_number_self_verify_and_audit(client):
    _company, manager, verifier, owner = setup_users("981")
    obligation = create_obligation(client, manager, owner)
    revision = ComplianceRevision.query.one()
    assert obligation.obligation_no == f"MEV-{date.today().year}-0001"
    assert obligation.status == "verification_pending"
    assert revision.status == "verification_pending"
    assert AuditLog.query.filter_by(action="compliance_created").count() == 1
    assert Notification.query.filter_by(
        source_key=f"compliance-verification:{revision.id}", user_id=verifier.id
    ).count() == 1
    assert client.get("/mevzuat-takibi").status_code == 200
    assert client.get(f"/mevzuat-takibi/{obligation.id}").status_code == 200

    assert client.post(f"/mevzuat-takibi/revizyon/{revision.id}/dogrula").status_code == 403
    verified = verify(client, verifier, obligation)
    assert verified.status == "verified"
    assert verified.verified_by_user_id == verifier.id
    assert obligation.status == "active"
    assert db.session.get(
        AppSetting, "sales_readiness:competitor_compliance_obligations"
    ).value == "1"


def test_verified_revision_is_immutable_and_new_revision_supersedes(client):
    _company, manager, verifier, owner = setup_users("982")
    obligation = create_obligation(client, manager, owner)
    first = verify(client, verifier, obligation)

    first.change_summary = "Geçmiş değiştirilmeye çalışıldı"
    with pytest.raises(ValueError, match="değiştirilemez"):
        db.session.commit()
    db.session.rollback()

    login(client, manager)
    response = client.post(
        f"/mevzuat-takibi/{obligation.id}/revizyon",
        data={
            "revision_no": "R1",
            "publication_date": date.today().isoformat(),
            "effective_date": date.today().isoformat(),
            "repeal_date": "",
            "official_source_url": "https://www.resmigazete.gov.tr/ornek-r1",
            "change_summary": "Yeni madde eklendi.",
        },
    )
    assert response.status_code == 302
    second = ComplianceRevision.query.filter_by(obligation_id=obligation.id, revision_no="R1").one()
    db.session.refresh(obligation)
    assert obligation.status == "active"
    assert obligation.latest_verified_revision.id == first.id
    login(client, verifier)
    assert client.post(f"/mevzuat-takibi/revizyon/{second.id}/dogrula").status_code == 302
    db.session.refresh(first)
    db.session.refresh(second)
    assert first.status == "superseded"
    assert second.status == "verified"
    login(client, manager)
    report_rows = sheet_values(client.get("/mevzuat-takibi/excel").data)
    revision_column = report_rows[0].index("Revizyon")
    assert {row[revision_column] for row in report_rows[1:]} == {"R0", "R1"}


def test_negative_evaluation_requires_control_and_keeps_snapshot(client):
    _company, manager, verifier, owner = setup_users("983")
    obligation = create_obligation(client, manager, owner)
    revision = verify(client, verifier, obligation)
    login(client, owner)
    evaluation_url = f"/mevzuat-takibi/{obligation.id}/degerlendir"
    assert client.get(evaluation_url).status_code == 200
    payload = {
        "outcome": "noncompliant",
        "summary": "Emisyon ölçümü güncel değil.",
        "evidence_note": "Saha kontrol tutanağı",
        "next_review_date": (date.today() + timedelta(days=7)).isoformat(),
        "improvement_plan": "",
    }
    response = client.post(evaluation_url, data=payload)
    assert response.status_code == 200
    assert "iyileştirme planı zorunludur" in response.get_data(as_text=True)
    assert ComplianceEvaluation.query.count() == 0

    payload["improvement_plan"] = "Ölçüm laboratuvarı ile sözleşme yapılacak."
    response = client.post(evaluation_url, data=payload)
    assert response.status_code == 302
    evaluation = ComplianceEvaluation.query.one()
    assert evaluation.revision_id == revision.id
    assert evaluation.obligation_title_snapshot == "Çevre İzin ve Lisans Yükümlülüğü"
    assert evaluation.revision_no_snapshot == "R0"
    assert evaluation.owner_name_snapshot == "Uygunluk Sorumlusu"

    obligation.title = "Yeni başlık"
    db.session.commit()
    assert db.session.get(ComplianceEvaluation, evaluation.id).obligation_title_snapshot != obligation.title
    evaluation.summary = "Geçmiş değiştirilemez"
    with pytest.raises(ValueError, match="değiştirilemez"):
        db.session.commit()
    db.session.rollback()


def test_tenant_permissions_upload_download_and_excel(client):
    company, manager, verifier, owner = setup_users("984")
    login(client, manager)
    payload = obligation_payload(owner)
    payload["source_file"] = (BytesIO(b"official source"), "resmi-kaynak.pdf")
    response = client.post(
        "/mevzuat-takibi/yeni", data=payload, content_type="multipart/form-data"
    )
    assert response.status_code == 302
    obligation = ComplianceObligation.query.one()
    file_row = ComplianceFile.query.one()
    assert file_row.sha256_hash
    assert file_row.original_name == "resmi-kaynak.pdf"
    assert client.get(f"/mevzuat-takibi/dosya/{file_row.id}").status_code == 200
    assert AuditLog.query.filter_by(
        entity_type="ComplianceFile",
        entity_id=str(file_row.id),
        action="compliance_file_downloaded",
    ).count() == 1

    report = client.get("/mevzuat-takibi/excel")
    assert_xlsx_response(report)
    rows = sheet_values(report.data)
    assert "Kayıt No" in rows[0]
    assert "Resmî Kaynak" in rows[0]
    assert obligation.obligation_no in rows[1]

    foreign_company = create_company("985")
    foreign = create_user(
        "foreign-compliance-985", company=foreign_company, permissions=MANAGE_PERMISSIONS
    )
    login(client, foreign)
    assert client.get(f"/mevzuat-takibi/{obligation.id}").status_code == 404
    assert client.get(f"/mevzuat-takibi/dosya/{file_row.id}").status_code == 404

    unauthorized = create_user("no-compliance-984", company=company, permissions=())
    login(client, unauthorized)
    assert client.get("/mevzuat-takibi").status_code == 403


def test_tasks_reminders_dedup_archive_and_runtime_module(client):
    company, manager, verifier, owner = setup_users("986")
    obligation = create_obligation(client, manager, owner)

    login(client, verifier)
    tasks = client.get("/uzerime-atananlar?module=compliance")
    assert tasks.status_code == 200
    assert "doğrulaması" in tasks.get_data(as_text=True)
    verify(client, verifier, obligation)

    login(client, owner)
    tasks = client.get("/uzerime-atananlar?module=compliance")
    assert obligation.obligation_no in tasks.get_data(as_text=True)
    stats = generate_due_reminders(company_id=company.id, run_date=date.today())
    db.session.commit()
    assert stats["notifications"] >= 1
    first_count = Notification.query.filter(
        Notification.source_key.like("compliance-review:%")
    ).count()
    generate_due_reminders(company_id=company.id, run_date=date.today())
    db.session.commit()
    assert Notification.query.filter(
        Notification.source_key.like("compliance-review:%")
    ).count() == first_count

    login(client, manager)
    assert client.post(f"/mevzuat-takibi/{obligation.id}/arsivle").status_code == 302
    assert db.session.get(ComplianceObligation, obligation.id).status == "archived"
    login(client, owner)
    assert obligation.obligation_no not in client.get(
        "/uzerime-atananlar?module=compliance"
    ).get_data(as_text=True)
    before = Notification.query.count()
    generate_due_reminders(company_id=company.id, run_date=date.today() + timedelta(days=1))
    db.session.commit()
    assert Notification.query.count() == before

    ensure_runtime_schema()
    assert db.session.get(
        AppSetting, "sales_readiness:competitor_compliance_obligations"
    ).value == "1"
    module = CompanyModule.query.filter_by(
        company_id=company.id, module_key="compliance_management"
    ).one()
    module.is_enabled = False
    db.session.commit()
    login(client, manager)
    assert client.get("/mevzuat-takibi").status_code in {403, 404}


def test_department_manager_cannot_access_another_departments_obligation(client):
    company, manager, verifier, owner = setup_users("987")
    obligation = create_obligation(client, manager, owner, department="Üretim")
    verify(client, verifier, obligation)
    department_manager = create_user(
        "quality-manager-987",
        company=company,
        role_key="department_manager",
        full_name="Kalite Müdürü",
        title="Kalite Müdürü",
    )

    login(client, department_manager)
    dashboard = client.get("/mevzuat-takibi")
    assert dashboard.status_code == 200
    assert obligation.obligation_no not in dashboard.get_data(as_text=True)
    assert client.get(f"/mevzuat-takibi/{obligation.id}").status_code == 403
    assert client.get(f"/mevzuat-takibi/{obligation.id}/degerlendir").status_code == 403


def test_open_linked_action_blocks_compliant_result(client):
    _company, manager, verifier, owner = setup_users("988")
    obligation = create_obligation(client, manager, owner)
    verify(client, verifier, obligation)
    action = Action(
        company_id=obligation.company_id,
        title="Mevzuat uygunsuzluğunu gider",
        responsible_owner=owner.full_name,
        responsible_user_id=owner.id,
        department="Kalite",
        termin_date=date.today() + timedelta(days=7),
    )
    db.session.add(action)
    db.session.commit()

    login(client, owner)
    evaluation_url = f"/mevzuat-takibi/{obligation.id}/degerlendir"
    first = client.post(
        evaluation_url,
        data={
            "outcome": "noncompliant",
            "summary": "Yasal şart henüz karşılanmıyor.",
            "next_review_date": (date.today() + timedelta(days=7)).isoformat(),
            "action_id": str(action.id),
        },
    )
    assert first.status_code == 302

    blocked = client.post(
        evaluation_url,
        data={
            "outcome": "compliant",
            "summary": "Uygunluk sağlandı.",
            "next_review_date": (date.today() + timedelta(days=30)).isoformat(),
        },
    )
    assert blocked.status_code == 200
    assert "açık aksiyonlar tamamlanmadan" in blocked.get_data(as_text=True)
    assert ComplianceEvaluation.query.filter_by(obligation_id=obligation.id).count() == 1


def test_revision_can_be_returned_corrected_and_resubmitted(client):
    _company, manager, verifier, owner = setup_users("989")
    obligation = create_obligation(client, manager, owner)
    revision = ComplianceRevision.query.filter_by(obligation_id=obligation.id).one()

    login(client, verifier)
    returned = client.post(
        f"/mevzuat-takibi/revizyon/{revision.id}/duzeltmeye-gonder",
        data={"reason": "Resmî kaynak bağlantısını güncelleyin."},
    )
    assert returned.status_code == 302
    db.session.refresh(revision)
    assert revision.status == "returned"
    assert revision.verification_note == "Resmî kaynak bağlantısını güncelleyin."
    assert AuditLog.query.filter_by(action="compliance_revision_returned").count() == 1

    login(client, manager)
    corrected = client.post(
        f"/mevzuat-takibi/revizyon/{revision.id}/duzenle",
        data={
            "revision_no": "R0",
            "publication_date": date.today().isoformat(),
            "effective_date": date.today().isoformat(),
            "repeal_date": "",
            "official_source_url": "https://www.resmigazete.gov.tr/duzeltilmis",
            "change_summary": "Doğrulanabilir resmî kaynak eklendi.",
        },
    )
    assert corrected.status_code == 302
    db.session.refresh(revision)
    assert revision.status == "verification_pending"
    assert revision.verification_note is None
    assert revision.official_source_url.endswith("/duzeltilmis")


def test_owner_must_have_compliance_access_and_evaluation_permissions(client):
    company, manager, _verifier, _owner = setup_users("990")
    unauthorized_owner = create_user(
        "unauthorized-owner-990",
        company=company,
        permissions=(),
        full_name="Yetkisiz Personel",
    )
    login(client, manager)
    response = client.post(
        "/mevzuat-takibi/yeni",
        data=obligation_payload(unauthorized_owner),
    )
    assert response.status_code == 200
    assert "görüntüleme ve değerlendirme yetkisi" in response.get_data(as_text=True)
    assert ComplianceObligation.query.filter_by(company_id=company.id).count() == 0


def test_due_reminder_run_repeals_verified_revision_on_its_date(client):
    company, manager, verifier, owner = setup_users("991")
    repeal_date = date.today() + timedelta(days=2)
    obligation = create_obligation(
        client,
        manager,
        owner,
        repeal_date=repeal_date.isoformat(),
    )
    verify(client, verifier, obligation)
    assert obligation.status == "active"

    generate_due_reminders(company_id=company.id, run_date=repeal_date)
    db.session.commit()
    db.session.refresh(obligation)
    assert obligation.status == "repealed"
    assert obligation.repealed_at is not None
