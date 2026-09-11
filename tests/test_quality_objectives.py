from datetime import date, timedelta

from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    CompanyModule,
    QUALITY_OBJECTIVE_DIRECTION_MINIMUM,
    QUALITY_OBJECTIVE_PERSPECTIVES,
    QUALITY_OBJECTIVE_STATUS_ACTIVE,
    QUALITY_OBJECTIVE_STATUS_ARCHIVED,
    QUALITY_OBJECTIVE_STATUS_COMPLETED,
    Notification,
    QualityObjective,
    QualityObjectiveMeasurement,
)
from app.seed import ensure_runtime_schema
from app.reminders import run_due_reminders_once_for_company

from .helpers import assert_xlsx_response, create_company, create_user, login, sheet_values


def objective_payload(owner, **overrides):
    data = {
        "title": "Musteri sikayetlerini azaltma",
        "bsc_perspective": QUALITY_OBJECTIVE_PERSPECTIVES[1],
        "department": "Kalite",
        "owner_user_id": str(owner.id),
        "process_id": "",
        "action_id": "",
        "metric_name": "Aylik sikayet sayisi",
        "unit": "adet",
        "baseline_value": "20",
        "target_value": "10",
        "target_direction": "En Fazla",
        "weight": "25",
        "period_start": date.today().replace(month=1, day=1).isoformat(),
        "period_end": date.today().replace(month=12, day=31).isoformat(),
        "next_measurement_date": date.today().isoformat(),
        "measurement_frequency": "Aylık",
        "description": "ISO 9001 kalite hedefi",
    }
    data.update(overrides)
    return data


def create_objective(company, owner, creator, **overrides):
    objective = QualityObjective(
        company_id=company.id,
        objective_no=overrides.pop("objective_no", "KH-2026-0001"),
        title=overrides.pop("title", "Teslimat performansi"),
        bsc_perspective=overrides.pop("bsc_perspective", QUALITY_OBJECTIVE_PERSPECTIVES[2]),
        department=overrides.pop("department", "Kalite"),
        owner_user_id=owner.id,
        metric_name=overrides.pop("metric_name", "Zamaninda teslimat"),
        unit=overrides.pop("unit", "%"),
        baseline_value=overrides.pop("baseline_value", 80),
        target_value=overrides.pop("target_value", 100),
        target_direction=overrides.pop("target_direction", QUALITY_OBJECTIVE_DIRECTION_MINIMUM),
        weight=overrides.pop("weight", 25),
        period_start=overrides.pop("period_start", date.today().replace(month=1, day=1)),
        period_end=overrides.pop("period_end", date.today().replace(month=12, day=31)),
        next_measurement_date=overrides.pop("next_measurement_date", date.today()),
        measurement_frequency=overrides.pop("measurement_frequency", "Aylık"),
        status=overrides.pop("status", QUALITY_OBJECTIVE_STATUS_ACTIVE),
        created_by_user_id=creator.id,
        **overrides,
    )
    db.session.add(objective)
    db.session.commit()
    return objective


def test_quality_objective_full_flow_audits_scores_tasks_and_checklist(client):
    company = create_company("1201")
    manager = create_user(
        "quality-objective-manager",
        company=company,
        full_name="Yonetim Temsilcisi",
        permissions=(
            "quality_objective.view",
            "quality_objective.create",
            "quality_objective.manage",
            "quality_objective.measure",
            "quality_objective.approve",
            "quality_objective.delete",
            "quality_objective.export",
            "reports.view",
            "reports.export",
        ),
    )
    owner = create_user(
        "quality-objective-owner",
        company=company,
        full_name="Kalite Sorumlusu",
        permissions=("quality_objective.view", "quality_objective.measure"),
    )
    login(client, manager)

    response = client.post(
        "/kalite-hedefleri/yeni",
        data=objective_payload(owner),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Musteri sikayetlerini azaltma" in response.get_data(as_text=True)
    objective = QualityObjective.query.one()
    assert objective.objective_no.startswith(f"KH-{date.today().year}-")
    assert AuditLog.query.filter_by(action="quality_objective_created").count() == 1

    response = client.post(
        f"/kalite-hedefleri/{objective.id}/aktiflestir",
        follow_redirects=True,
    )
    assert response.status_code == 200
    db.session.refresh(objective)
    assert objective.status == QUALITY_OBJECTIVE_STATUS_ACTIVE

    login(client, owner)
    measurement_date = date.today() - timedelta(days=40)
    response = client.post(
        f"/kalite-hedefleri/{objective.id}/olcum",
        data={
            "measurement_date": measurement_date.isoformat(),
            "period_label": "Agustos",
            "actual_value": "15",
            "note": "Ilk olcum",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    measurement = QualityObjectiveMeasurement.query.one()
    assert float(measurement.target_value_snapshot) == 10
    assert round(objective.achievement_rate, 2) == 50.0
    assert round(objective.weighted_score, 2) == 12.5
    assert AuditLog.query.filter_by(action="measurement_recorded").count() == 1
    assert db.session.get(
        AppSetting,
        "sales_readiness:competitor_quality_objectives",
    ).value == "1"

    tasks_response = client.get("/uzerime-atananlar?module=quality_objective")
    assert tasks_response.status_code == 200
    assert "Musteri sikayetlerini azaltma" in tasks_response.get_data(as_text=True)

    login(client, manager)
    complete_response = client.post(
        f"/kalite-hedefleri/{objective.id}/tamamla",
        follow_redirects=True,
    )
    assert complete_response.status_code == 200
    db.session.refresh(objective)
    assert objective.status == QUALITY_OBJECTIVE_STATUS_COMPLETED
    assert AuditLog.query.filter_by(action="quality_objective_completed").count() == 1

    archive_response = client.post(
        f"/kalite-hedefleri/{objective.id}/arsivle",
        follow_redirects=True,
    )
    assert archive_response.status_code == 200
    db.session.refresh(objective)
    assert objective.status == QUALITY_OBJECTIVE_STATUS_ARCHIVED
    assert objective.archived_at is not None


def test_quality_objective_measurement_duplicate_and_correction_are_controlled(client):
    company = create_company("1202")
    manager = create_user(
        "quality-objective-correction-manager",
        company=company,
        permissions=(
            "quality_objective.view",
            "quality_objective.manage",
            "quality_objective.measure",
        ),
    )
    objective = create_objective(company, manager, manager)
    login(client, manager)

    payload = {
        "measurement_date": date.today().isoformat(),
        "period_label": "Eylul",
        "actual_value": "90",
        "note": "Ilk kayit",
    }
    assert client.post(
        f"/kalite-hedefleri/{objective.id}/olcum", data=payload
    ).status_code == 302
    duplicate = client.post(
        f"/kalite-hedefleri/{objective.id}/olcum",
        data=payload,
        follow_redirects=True,
    )
    assert duplicate.status_code == 200
    assert QualityObjectiveMeasurement.query.count() == 1

    measurement = QualityObjectiveMeasurement.query.one()
    correction = client.post(
        f"/kalite-hedefleri/{objective.id}/olcum/{measurement.id}/duzenle",
        data={**payload, "actual_value": "95", "note": "Dogrulandi"},
        follow_redirects=True,
    )
    assert correction.status_code == 200
    db.session.refresh(measurement)
    assert float(measurement.actual_value) == 95
    assert AuditLog.query.filter_by(action="measurement_corrected").count() == 1


def test_quality_objective_correction_preserves_snapshot_and_completed_record_is_locked(client):
    company = create_company("1211")
    manager = create_user(
        "quality-objective-lock-manager",
        company=company,
        permissions=(
            "quality_objective.view",
            "quality_objective.manage",
            "quality_objective.measure",
            "quality_objective.approve",
        ),
    )
    objective = create_objective(
        company,
        manager,
        manager,
        baseline_value=20,
        target_value=10,
        target_direction="En Fazla",
    )
    measurement = QualityObjectiveMeasurement(
        company_id=company.id,
        objective_id=objective.id,
        measurement_date=date(date.today().year, 7, 1),
        actual_value=15,
        target_value_snapshot=10,
        entered_by_user_id=manager.id,
    )
    db.session.add(measurement)
    db.session.commit()
    login(client, manager)

    update_response = client.post(
        f"/kalite-hedefleri/{objective.id}/duzenle",
        data=objective_payload(manager, target_value="8"),
        follow_redirects=True,
    )
    assert update_response.status_code == 200
    correction_date = date(date.today().year, 8, 1)
    correction_response = client.post(
        f"/kalite-hedefleri/{objective.id}/olcum/{measurement.id}/duzenle",
        data={
            "measurement_date": correction_date.isoformat(),
            "period_label": "Agustos",
            "actual_value": "12",
            "note": "Duzeltilen veri",
        },
        follow_redirects=True,
    )
    assert correction_response.status_code == 200
    db.session.refresh(measurement)
    db.session.refresh(objective)
    assert float(measurement.target_value_snapshot) == 10
    assert objective.next_measurement_date == date(date.today().year, 9, 1)

    assert client.post(f"/kalite-hedefleri/{objective.id}/tamamla").status_code == 302
    db.session.refresh(objective)
    assert objective.status == QUALITY_OBJECTIVE_STATUS_COMPLETED
    assert client.get(f"/kalite-hedefleri/{objective.id}/duzenle").status_code == 403
    assert client.get(
        f"/kalite-hedefleri/{objective.id}/olcum/{measurement.id}/duzenle"
    ).status_code == 403
    assert client.post(
        f"/kalite-hedefleri/{objective.id}/olcum/{measurement.id}/sil"
    ).status_code == 403


def test_quality_objective_measurement_must_be_inside_period_and_staff_cannot_delete(client):
    company = create_company("1212")
    representative = create_user(
        "quality-objective-period-representative",
        company=company,
        permissions=(
            "quality_objective.view",
            "quality_objective.manage",
            "quality_objective.measure",
        ),
    )
    owner = create_user(
        "quality-objective-period-owner",
        company=company,
        permissions=("quality_objective.view", "quality_objective.measure"),
    )
    objective = create_objective(company, owner, representative)
    login(client, owner)

    outside_response = client.post(
        f"/kalite-hedefleri/{objective.id}/olcum",
        data={
            "measurement_date": date(date.today().year - 1, 12, 31).isoformat(),
            "actual_value": "90",
        },
        follow_redirects=True,
    )
    assert outside_response.status_code == 200
    assert QualityObjectiveMeasurement.query.count() == 0

    assert client.post(
        f"/kalite-hedefleri/{objective.id}/olcum",
        data={
            "measurement_date": date.today().isoformat(),
            "actual_value": "90",
        },
    ).status_code == 302
    measurement = QualityObjectiveMeasurement.query.one()
    detail_body = client.get(
        f"/kalite-hedefleri/{objective.id}"
    ).get_data(as_text=True)
    assert f"/olcum/{measurement.id}/duzenle" in detail_body
    assert f"/olcum/{measurement.id}/sil" not in detail_body
    assert client.post(
        f"/kalite-hedefleri/{objective.id}/olcum/{measurement.id}/sil"
    ).status_code == 403


def test_department_manager_cannot_create_objective_for_another_department(client):
    company = create_company("1213")
    manager = create_user(
        "quality-objective-department-scope-manager",
        company=company,
        role_key="department_manager",
        full_name="Kalite Muduru",
        title="Kalite Müdürü",
    )
    other_staff = create_user(
        "quality-objective-shipping-staff",
        company=company,
        role_key="department_staff",
        full_name="Sevkiyat Personeli",
        title="Sevkiyat Personeli",
    )
    login(client, manager)

    form_body = client.get("/kalite-hedefleri/yeni").get_data(as_text=True)
    assert "Sevkiyat Personeli" not in form_body
    response = client.post(
        "/kalite-hedefleri/yeni",
        data=objective_payload(
            other_staff,
            department="Sevkiyat",
        ),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert QualityObjective.query.count() == 0


def test_quality_objective_owner_must_have_measurement_permission(client):
    company = create_company("1214")
    representative = create_user(
        "quality-objective-owner-check-manager",
        company=company,
        permissions=(
            "quality_objective.view",
            "quality_objective.create",
            "quality_objective.manage",
        ),
    )
    viewer = create_user(
        "quality-objective-owner-check-viewer",
        company=company,
        permissions=("quality_objective.view",),
    )
    login(client, representative)

    response = client.post(
        "/kalite-hedefleri/yeni",
        data=objective_payload(viewer),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert QualityObjective.query.count() == 0


def test_quality_objective_permissions_module_and_company_isolation(client):
    company_a = create_company("1203")
    company_b = create_company("1204")
    plain = create_user("quality-objective-plain", company=company_a)
    viewer = create_user(
        "quality-objective-viewer",
        company=company_a,
        permissions=("quality_objective.view",),
    )
    other_owner = create_user("quality-objective-other-owner", company=company_b)
    other_objective = create_objective(company_b, other_owner, other_owner)

    login(client, plain)
    assert client.get("/kalite-hedefleri").status_code == 403

    login(client, viewer)
    assert client.get("/kalite-hedefleri").status_code == 200
    assert client.get(f"/kalite-hedefleri/{other_objective.id}").status_code == 404
    assert client.get("/kalite-hedefleri/yeni").status_code == 403

    module = CompanyModule.query.filter_by(
        company_id=company_a.id,
        module_key="quality_objectives",
    ).one()
    module.is_enabled = False
    db.session.commit()
    assert client.get("/kalite-hedefleri").status_code == 403


def test_quality_objective_default_role_matrix_and_sidebar(client):
    company = create_company("1210")
    representative = create_user(
        "quality-objective-representative",
        company=company,
        role_key="management_representative",
        full_name="Yonetim Temsilcisi",
    )
    management = create_user(
        "quality-objective-management",
        company=company,
        role_key="management",
        full_name="Yonetim Uyesi",
    )
    department_manager = create_user(
        "quality-objective-department-manager",
        company=company,
        role_key="department_manager",
        full_name="Kalite Muduru",
        title="Kalite Müdürü",
    )
    personnel = create_user(
        "quality-objective-personnel",
        company=company,
        role_key="department_staff",
        full_name="Kalite Personeli",
        title="Kalite Personeli",
    )
    viewer = create_user(
        "quality-objective-role-viewer",
        company=company,
        role_key="viewer",
    )
    draft = create_objective(
        company,
        personnel,
        representative,
        status="Taslak",
    )

    login(client, representative)
    body = client.get("/kalite-hedefleri").get_data(as_text=True)
    assert "Kalite Hedefleri" in body
    assert 'href="/kalite-hedefleri"' in body
    assert client.get("/kalite-hedefleri/yeni").status_code == 200

    login(client, management)
    assert client.get("/kalite-hedefleri").status_code == 200
    assert client.get("/kalite-hedefleri/yeni").status_code == 403
    assert client.post(f"/kalite-hedefleri/{draft.id}/aktiflestir").status_code == 302

    login(client, department_manager)
    assert client.get("/kalite-hedefleri/yeni").status_code == 200
    assert client.get(f"/kalite-hedefleri/{draft.id}/duzenle").status_code == 200
    assert client.post(f"/kalite-hedefleri/{draft.id}/tamamla").status_code == 403

    login(client, personnel)
    assert client.get("/kalite-hedefleri").status_code == 200
    assert client.get("/kalite-hedefleri/yeni").status_code == 403
    assert client.post(
        f"/kalite-hedefleri/{draft.id}/olcum",
        data={
            "measurement_date": date.today().isoformat(),
            "period_label": "Eylul",
            "actual_value": "90",
            "note": "Personel olcumu",
        },
    ).status_code == 302

    login(client, viewer)
    assert client.get("/kalite-hedefleri").status_code == 200
    assert client.post(
        f"/kalite-hedefleri/{draft.id}/olcum",
        data={
            "measurement_date": date.today().isoformat(),
            "actual_value": "95",
        },
    ).status_code == 403


def test_quality_objective_rejects_cross_company_owner(client):
    company_a = create_company("1205")
    company_b = create_company("1206")
    manager = create_user(
        "quality-objective-cross-manager",
        company=company_a,
        permissions=(
            "quality_objective.view",
            "quality_objective.create",
            "quality_objective.manage",
        ),
    )
    other_owner = create_user("quality-objective-cross-owner", company=company_b)
    login(client, manager)

    response = client.post(
        "/kalite-hedefleri/yeni",
        data=objective_payload(other_owner),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert QualityObjective.query.count() == 0


def test_quality_objective_report_is_scoped_and_requires_export_permission(client):
    company_a = create_company("1207")
    company_b = create_company("1208")
    owner_a = create_user("quality-objective-report-owner-a", company=company_a)
    owner_b = create_user("quality-objective-report-owner-b", company=company_b)
    reporter = create_user(
        "quality-objective-reporter",
        company=company_a,
        permissions=(
            "reports.view",
            "reports.export",
            "quality_objective.view",
            "quality_objective.export",
        ),
    )
    blocked = create_user(
        "quality-objective-report-blocked",
        company=company_a,
        permissions=("reports.view", "reports.export", "quality_objective.view"),
    )
    create_objective(company_a, owner_a, reporter, title="Gorunen kalite hedefi")
    create_objective(
        company_b,
        owner_b,
        owner_b,
        objective_no="KH-2026-0099",
        title="Gorunmeyen kalite hedefi",
    )

    login(client, blocked)
    assert client.get("/rapor-merkezi/quality_objectives/excel").status_code == 404

    login(client, reporter)
    response = client.get("/rapor-merkezi/quality_objectives/excel")
    assert_xlsx_response(response)
    rows = sheet_values(response.data)
    content = "\n".join("\t".join(row) for row in rows)
    assert "Gorunen kalite hedefi" in content
    assert "Gorunmeyen kalite hedefi" not in content


def test_quality_objective_due_reminder_is_scoped_and_deduplicated(client):
    company = create_company("1209")
    owner = create_user("quality-objective-reminder-owner", company=company)
    objective = create_objective(
        company,
        owner,
        owner,
        next_measurement_date=date.today() - timedelta(days=2),
    )

    first = run_due_reminders_once_for_company(
        company.id,
        force=True,
        run_date=date.today(),
    )
    second = run_due_reminders_once_for_company(
        company.id,
        force=True,
        run_date=date.today(),
    )

    assert first["notifications"] == 1
    assert second["notifications"] == 0
    notification = Notification.query.one()
    assert notification.user_id == owner.id
    assert notification.company_id == company.id
    assert notification.notification_type == "danger"
    assert notification.source_key.startswith("quality-objective:")
    assert notification.target_url == f"/kalite-hedefleri/{objective.id}"


def test_runtime_schema_marks_quality_objective_readiness(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(
        AppSetting,
        "sales_readiness:competitor_quality_objectives",
    )
    assert setting is not None
    assert setting.value == "1"
