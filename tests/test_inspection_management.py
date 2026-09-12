from datetime import date, timedelta

from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    CompanyModule,
    DynamicFormField,
    DynamicFormTemplate,
    DynamicFormVersion,
    InspectionFinding,
    InspectionItemResult,
    InspectionRecord,
    Notification,
)
from app.seed import ensure_runtime_schema

from .helpers import assert_xlsx_response, create_company, create_user, login, sheet_values


MANAGER_PERMISSIONS = (
    "inspection.view",
    "inspection.manage",
    "inspection.perform",
    "inspection.review",
    "inspection.export",
    "inspection.archive",
)


def create_form_version(company, manager, *, status="published", name="Saha Kontrol Listesi"):
    template = DynamicFormTemplate(
        company_id=company.id,
        code=f"DF-{company.code}-{name[:8]}",
        name=name,
        status=status,
        current_version_number=1,
        created_by_user_id=manager.id,
    )
    version = DynamicFormVersion(
        company_id=company.id,
        template=template,
        version_number=1,
        status=status,
        name_snapshot=name,
        created_by_user_id=manager.id,
        published_by_user_id=manager.id if status == "published" else None,
    )
    fields = [
        DynamicFormField(
            company_id=company.id,
            version=version,
            field_key="field_1",
            label="Makine koruyucusu",
            field_type="yes_no",
            is_required=True,
            sort_order=1,
        ),
        DynamicFormField(
            company_id=company.id,
            version=version,
            field_key="field_2",
            label="Kontrol notu",
            field_type="long_text",
            is_required=False,
            sort_order=2,
        ),
    ]
    db.session.add_all([template, version, *fields])
    db.session.commit()
    return version


def setup_inspection_users(code="901"):
    company = create_company(code)
    manager = create_user(
        f"manager-{code}",
        company=company,
        permissions=MANAGER_PERMISSIONS,
        full_name="Kalite Yöneticisi",
    )
    inspector = create_user(
        f"inspector-{code}",
        company=company,
        permissions=("inspection.perform",),
        full_name="Saha Personeli",
    )
    reviewer = create_user(
        f"reviewer-{code}",
        company=company,
        permissions=("inspection.view", "inspection.review"),
        full_name="İnceleme Sorumlusu",
    )
    version = create_form_version(company, manager)
    return company, manager, inspector, reviewer, version


def create_inspection_via_route(client, manager, inspector, reviewer, version, title="Pres Kontrolü"):
    login(client, manager)
    response = client.post(
        "/saha-kontrol/yeni",
        data={
            "title": title,
            "version_id": str(version.id),
            "department": "Üretim",
            "location": "Hat 1",
            "reference": "PRS-01",
            "inspector_user_id": str(inspector.id),
            "reviewer_user_id": str(reviewer.id),
            "planned_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=3)).isoformat(),
        },
    )
    assert response.status_code == 302
    return InspectionRecord.query.filter_by(company_id=manager.company_id, title=title).one()


def valid_results(version, *, first_result="Uygun", first_value="Evet", note="Türkçe ölçüm notu"):
    first, second = version.fields
    return {
        "action": "submit",
        f"answer_{first.id}": first_value,
        f"result_{first.id}": first_result,
        f"explanation_{first.id}": "Koruyucu yerinde" if first_result == "Uygun" else "Koruyucu eksik",
        f"answer_{second.id}": note,
        f"result_{second.id}": "Uygun",
        f"explanation_{second.id}": "",
    }


def test_only_published_template_can_be_selected_and_number_is_company_scoped(client):
    company, manager, inspector, reviewer, version = setup_inspection_users("901")
    draft = create_form_version(company, manager, status="draft", name="Taslak Liste")
    login(client, manager)

    page = client.get("/saha-kontrol/yeni")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert version.name_snapshot in body
    assert draft.name_snapshot not in body

    response = client.post(
        "/saha-kontrol/yeni",
        data={
            "title": "Geçersiz",
            "version_id": str(draft.id),
            "inspector_user_id": str(inspector.id),
            "reviewer_user_id": str(reviewer.id),
            "due_date": date.today().isoformat(),
        },
    )
    assert response.status_code == 200
    assert "Yayınlanmış bir kontrol şablonu seçin" in response.get_data(as_text=True)
    assert InspectionRecord.query.count() == 0

    first = create_inspection_via_route(client, manager, inspector, reviewer, version, "Birinci")
    second = create_inspection_via_route(client, manager, inspector, reviewer, version, "İkinci")
    assert first.inspection_no == f"MUY-{date.today().year}-0001"
    assert second.inspection_no == f"MUY-{date.today().year}-0002"
    assert Notification.query.filter_by(user_id=inspector.id).count() == 2

    response = client.post(
        f"/saha-kontrol/{first.id}/duzenle",
        data={
            "title": "Güncellenen Muayene",
            "version_id": str(version.id),
            "department": "Kalite",
            "location": "Hat 2",
            "reference": "PRS-02",
            "inspector_user_id": str(inspector.id),
            "reviewer_user_id": str(reviewer.id),
            "planned_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=4)).isoformat(),
        },
    )
    assert response.status_code == 302
    db.session.refresh(first)
    assert first.title == "Güncellenen Muayene"
    assert first.department == "Kalite"
    assert AuditLog.query.filter_by(action="inspection_updated").count() == 1


def test_assignment_access_required_validation_value_preservation_and_normal_completion(client):
    company, manager, inspector, reviewer, version = setup_inspection_users("902")
    inspection = create_inspection_via_route(client, manager, inspector, reviewer, version)
    unrelated = create_user(
        "unrelated-902",
        company=company,
        permissions=("inspection.perform",),
    )

    login(client, unrelated)
    assert client.get(f"/saha-kontrol/{inspection.id}").status_code == 403
    assert client.get(f"/saha-kontrol/{inspection.id}/uygula").status_code == 403

    login(client, inspector)
    tasks = client.get("/uzerime-atananlar?module=inspection")
    assert tasks.status_code == 200
    assert inspection.inspection_no in tasks.get_data(as_text=True)
    assert client.post(f"/saha-kontrol/{inspection.id}/baslat").status_code == 302

    first, second = version.fields
    invalid = client.post(
        f"/saha-kontrol/{inspection.id}/uygula",
        data={
            "action": "submit",
            f"answer_{first.id}": "",
            f"result_{first.id}": "Uygun",
            f"answer_{second.id}": "Korunacak Türkçe değer",
            f"result_{second.id}": "Uygun",
        },
    )
    invalid_body = invalid.get_data(as_text=True)
    assert invalid.status_code == 200
    assert "zorunlu değeri girin" in invalid_body
    assert "Korunacak Türkçe değer" in invalid_body
    assert InspectionItemResult.query.count() == 0

    response = client.post(
        f"/saha-kontrol/{inspection.id}/uygula",
        data=valid_results(version),
    )
    assert response.status_code == 302
    db.session.refresh(inspection)
    assert inspection.status == "review_pending"
    assert inspection.overall_result == "Uygun"
    assert db.session.get(AppSetting, "sales_readiness:competitor_inspection_management") is None
    audit = AuditLog.query.filter_by(action="inspection_submitted").one()
    assert "Türkçe ölçüm notu" not in (audit.new_values or "")
    assert "result_item_ids" in (audit.new_values or "")

    login(client, reviewer)
    assert client.post(f"/saha-kontrol/{inspection.id}/onayla").status_code == 302
    db.session.refresh(inspection)
    assert inspection.status == "completed"
    assert db.session.get(AppSetting, "sales_readiness:competitor_inspection_management").value == "1"
    assert AuditLog.query.filter_by(action="inspection_completed").count() == 1


def test_nonconformity_requires_finding_open_finding_blocks_completion_then_closes(client):
    _company, manager, inspector, reviewer, version = setup_inspection_users("903")
    inspection = create_inspection_via_route(client, manager, inspector, reviewer, version)
    login(client, inspector)
    client.post(f"/saha-kontrol/{inspection.id}/baslat")

    response = client.post(
        f"/saha-kontrol/{inspection.id}/uygula",
        data=valid_results(version, first_result="Uygun Değil"),
        follow_redirects=True,
    )
    assert "bulgu oluşturun" in response.get_data(as_text=True)
    db.session.refresh(inspection)
    assert inspection.status == "in_progress"
    item = InspectionItemResult.query.filter_by(
        inspection_id=inspection.id,
        compliance_result="Uygun Değil",
    ).one()

    response = client.post(
        f"/saha-kontrol/{inspection.id}/bulgu/yeni",
        data={
            "item_result_id": str(item.id),
            "title": "Makine koruyucusu eksik",
            "description": "Koruyucu yenilenecek",
            "severity": "Yüksek",
            "responsible_user_id": str(inspector.id),
            "due_date": (date.today() + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 302
    finding = InspectionFinding.query.one()
    assert finding.item_label_snapshot == "Makine koruyucusu"
    assert finding.result_snapshot == "Uygun Değil"
    finding_audits = AuditLog.query.filter_by(entity_type="InspectionFinding").all()
    assert all("Koruyucu eksik" not in (row.new_values or "") for row in finding_audits)
    response = client.post(
        f"/saha-kontrol/{inspection.id}/uygula",
        data=valid_results(version, first_result="Uygun Değil"),
    )
    assert response.status_code == 302
    db.session.refresh(inspection)
    assert inspection.status == "correction_pending"

    inspection.status = "effectiveness_review"
    db.session.commit()
    login(client, reviewer)
    blocked = client.post(f"/saha-kontrol/{inspection.id}/onayla", follow_redirects=True)
    assert "Açık bulgular kapanmadan" in blocked.get_data(as_text=True)
    db.session.refresh(inspection)
    assert inspection.status == "effectiveness_review"

    inspection.status = "correction_pending"
    db.session.commit()
    login(client, inspector)
    assert client.post(
        f"/saha-kontrol/bulgu/{finding.id}/kapat",
        data={"resolution": "Yeni koruyucu takıldı."},
    ).status_code == 302
    db.session.refresh(inspection)
    db.session.refresh(finding)
    assert finding.status == "closed"
    assert inspection.status == "effectiveness_review"

    login(client, reviewer)
    client.post(f"/saha-kontrol/{inspection.id}/onayla")
    assert db.session.get(InspectionRecord, inspection.id).status == "completed"


def test_reviewer_can_return_record_for_correction_and_findings_lock_results(client):
    _company, manager, inspector, reviewer, version = setup_inspection_users("907")
    inspection = create_inspection_via_route(client, manager, inspector, reviewer, version)
    login(client, inspector)
    client.post(f"/saha-kontrol/{inspection.id}/baslat")
    client.post(f"/saha-kontrol/{inspection.id}/uygula", data=valid_results(version))

    login(client, reviewer)
    response = client.post(
        f"/saha-kontrol/{inspection.id}/duzeltmeye-gonder",
        data={"review_note": "Kontrol açıklamasını netleştirin."},
    )
    assert response.status_code == 302
    db.session.refresh(inspection)
    assert inspection.status == "in_progress"
    assert inspection.review_note == "Kontrol açıklamasını netleştirin."
    assert AuditLog.query.filter_by(action="inspection_returned_for_correction").count() == 1

    login(client, inspector)
    assert client.get(f"/saha-kontrol/{inspection.id}/uygula").status_code == 200
    client.post(f"/saha-kontrol/{inspection.id}/uygula", data=valid_results(version))
    db.session.refresh(inspection)
    assert inspection.status == "review_pending"

    inspection.status = "correction_pending"
    db.session.commit()
    response = client.get(f"/saha-kontrol/{inspection.id}/uygula")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/saha-kontrol/{inspection.id}")

    finding = InspectionFinding(
        company_id=inspection.company_id,
        inspection=inspection,
        item_result=inspection.item_results[0],
        item_label_snapshot=inspection.item_results[0].field.label,
        observed_value_json=inspection.item_results[0].value_json,
        result_snapshot="Uygun Değil",
        explanation_snapshot="İlk uygunsuzluk",
        title="Geçmiş bulgu",
        severity="Orta",
        responsible_user_id=inspector.id,
        due_date=date.today(),
        status="closed",
        resolution="Düzeltildi",
    )
    db.session.add(finding)
    inspection.item_results[0].compliance_result = "Uygun"
    db.session.commit()
    assert finding.result_snapshot == "Uygun Değil"


def test_reviewer_visibility_is_limited_to_assigned_records(client):
    company, manager, inspector, reviewer, version = setup_inspection_users("908")
    own = create_inspection_via_route(client, manager, inspector, reviewer, version, "Atanan Kontrol")
    other_inspector = create_user(
        "other-inspector-908",
        company=company,
        permissions=("inspection.perform",),
        full_name="Diğer Uygulayıcı",
    )
    other_reviewer = create_user(
        "other-reviewer-908",
        company=company,
        permissions=("inspection.view", "inspection.review"),
        full_name="Diğer İnceleyen",
    )
    hidden = create_inspection_via_route(
        client, manager, other_inspector, other_reviewer, version, "Başka Kontrol"
    )

    login(client, reviewer)
    body = client.get("/saha-kontrol").get_data(as_text=True)
    assert own.inspection_no in body
    assert hidden.inspection_no not in body
    assert client.get(f"/saha-kontrol/{hidden.id}").status_code == 403


def test_tenant_isolation_excel_and_archive(client):
    company, manager, inspector, reviewer, version = setup_inspection_users("904")
    inspection = create_inspection_via_route(client, manager, inspector, reviewer, version)
    other_company = create_company("905")
    foreign = create_user(
        "foreign-905",
        company=other_company,
        permissions=MANAGER_PERMISSIONS,
    )
    login(client, foreign)
    assert client.get(f"/saha-kontrol/{inspection.id}").status_code == 404
    assert client.post(f"/saha-kontrol/{inspection.id}/baslat").status_code == 404

    login(client, inspector)
    client.post(f"/saha-kontrol/{inspection.id}/baslat")
    client.post(f"/saha-kontrol/{inspection.id}/uygula", data=valid_results(version))
    login(client, reviewer)
    client.post(f"/saha-kontrol/{inspection.id}/onayla")

    login(client, manager)
    report = client.get("/saha-kontrol/excel")
    assert_xlsx_response(report)
    rows = sheet_values(report.data)
    assert "Muayene No" in rows[0]
    assert inspection.inspection_no in rows[1]
    assert "Saha Personeli" in rows[1]
    assert client.post(f"/saha-kontrol/{inspection.id}/arsivle").status_code == 302
    assert db.session.get(InspectionRecord, inspection.id).status == "archived"


def test_disabled_module_blocks_routes_and_runtime_does_not_precomplete_checklist(client):
    company, manager, _inspector, _reviewer, _version = setup_inspection_users("906")
    setting = CompanyModule.query.filter_by(
        company_id=company.id,
        module_key="inspection_management",
    ).one()
    setting.is_enabled = False
    db.session.commit()
    login(client, manager)

    assert client.get("/saha-kontrol").status_code == 403
    assert client.get("/saha-kontrol/yeni").status_code == 403
    assert db.session.get(AppSetting, "sales_readiness:competitor_inspection_management") is None


def test_runtime_schema_marks_completed_inspection_module(app):
    ensure_runtime_schema()
    setting = db.session.get(AppSetting, "sales_readiness:competitor_inspection_management")
    assert setting is not None
    assert setting.value == "1"
