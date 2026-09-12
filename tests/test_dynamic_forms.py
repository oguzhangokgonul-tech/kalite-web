from datetime import date, timedelta

from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    CompanyDepartment,
    DynamicFormAnswer,
    DynamicFormAssignment,
    DynamicFormAssignmentRecipient,
    DynamicFormField,
    DynamicFormSubmission,
    DynamicFormTemplate,
    DynamicFormVersion,
    Notification,
    PersonnelContact,
)
from app.seed import ensure_runtime_schema

from .helpers import assert_xlsx_response, create_company, create_user, login, sheet_values


MANAGER_PERMISSIONS = (
    "dynamic_forms.view",
    "dynamic_forms.manage",
    "dynamic_forms.assign",
    "dynamic_forms.respond",
    "dynamic_forms.export",
)


def designer_payload(name="Uretim Kontrol Formu"):
    return {
        "name": name,
        "description": "Vardiya kontrol listesi",
        "field_label": ["Kontrol sonucu", "Aciklama", "Miktar"],
        "field_type": ["single_choice", "long_text", "number"],
        "field_options": ["Uygun\nUygun Degil", "", ""],
        "field_required": ["0", "2"],
    }


def setup_published_form(client, code="801"):
    company = create_company(code)
    manager = create_user(
        f"manager-{code}",
        company=company,
        permissions=MANAGER_PERMISSIONS,
        full_name="Kalite Yoneticisi",
    )
    worker = create_user(
        f"worker-{code}",
        company=company,
        permissions=("dynamic_forms.respond",),
        full_name="Uretim Personeli",
    )
    db.session.add(CompanyDepartment(company_id=company.id, name="Uretim", sort_order=1))
    db.session.commit()
    login(client, manager)
    response = client.post("/dinamik-formlar/sablon/yeni", data=designer_payload())
    assert response.status_code == 302
    template = DynamicFormTemplate.query.filter_by(company_id=company.id).one()
    version = DynamicFormVersion.query.filter_by(template_id=template.id).one()
    response = client.post(f"/dinamik-formlar/surum/{version.id}/yayinla")
    assert response.status_code == 302
    db.session.refresh(version)
    assert version.status == "published"
    dashboard_response = client.get("/dinamik-formlar")
    assert dashboard_response.status_code == 200
    assert "Uretim Kontrol Formu" in dashboard_response.get_data(as_text=True)
    return company, manager, worker, template, version


def test_template_crud_publish_is_immutable_and_new_version_copies_fields(client):
    _company, manager, _worker, template, version = setup_published_form(client)
    original_name = version.name_snapshot
    original_field_ids = [field.id for field in version.fields]

    response = client.post(
        f"/dinamik-formlar/surum/{version.id}/duzenle",
        data=designer_payload("Degistirilemez"),
    )
    assert response.status_code == 302
    db.session.refresh(version)
    assert version.name_snapshot == original_name
    assert [field.id for field in version.fields] == original_field_ids

    response = client.post(f"/dinamik-formlar/sablon/{template.id}/yeni-surum")
    assert response.status_code == 302
    draft = DynamicFormVersion.query.filter_by(template_id=template.id, status="draft").one()
    assert draft.version_number == 2
    assert [(field.label, field.field_type) for field in draft.fields] == [
        (field.label, field.field_type) for field in version.fields
    ]

    response = client.post(f"/dinamik-formlar/sablon/{template.id}/kopyala")
    assert response.status_code == 302
    assert DynamicFormTemplate.query.count() == 2
    assert AuditLog.query.filter_by(action="form_version_published").count() == 1


def test_designer_validation_preserves_submitted_fields(client):
    company = create_company("809")
    manager = create_user(
        "manager-809",
        company=company,
        permissions=MANAGER_PERMISSIONS,
    )
    login(client, manager)

    response = client.post(
        "/dinamik-formlar/sablon/yeni",
        data={
            "name": "Kontrol Formu",
            "field_label": ["Korunacak Alan"],
            "field_type": ["single_choice"],
            "field_options": ["Tek seçenek"],
            "field_required": ["0"],
        },
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "en az iki seçenek" in body
    assert 'value="Korunacak Alan"' in body
    assert "Tek seçenek</textarea>" in body
    assert DynamicFormTemplate.query.count() == 0


def test_required_validation_assignment_notification_task_completion_and_audit(client):
    company, manager, worker, _template, version = setup_published_form(client, "802")
    due = date.today() + timedelta(days=2)
    response = client.post(
        f"/dinamik-formlar/surum/{version.id}/ata",
        data={
            "target_type": "user",
            "assigned_user_id": str(worker.id),
            "due_date": due.isoformat(),
        },
    )
    assert response.status_code == 302
    assignment = DynamicFormAssignment.query.one()
    assert {
        row.user_id
        for row in DynamicFormAssignmentRecipient.query.filter_by(
            assignment_id=assignment.id
        ).all()
    } == {worker.id}
    assert Notification.query.filter_by(user_id=worker.id, due_date=due).count() == 1

    login(client, worker)
    task_response = client.get("/uzerime-atananlar?module=dynamic_form")
    assert task_response.status_code == 200
    assert "Uretim Kontrol Formu" in task_response.get_data(as_text=True)

    fields = {field.label: field for field in version.fields}
    response = client.post(
        f"/dinamik-formlar/atama/{assignment.id}/doldur",
        data={"action": "complete", f"field_{fields['Aciklama'].id}": "Not"},
        follow_redirects=True,
    )
    assert "Zorunlu alanları" in response.get_data(as_text=True)
    assert ">Not</textarea>" in response.get_data(as_text=True)
    assert DynamicFormSubmission.query.count() == 0

    response = client.post(
        f"/dinamik-formlar/atama/{assignment.id}/doldur",
        data={
            "action": "draft",
            f"field_{fields['Kontrol sonucu'].id}": "Uygun",
            f"field_{fields['Aciklama'].id}": "Turkce test: Ölçüm",
        },
    )
    assert response.status_code == 302
    assert DynamicFormSubmission.query.one().status == "draft"

    response = client.post(
        f"/dinamik-formlar/atama/{assignment.id}/doldur",
        data={
            "action": "complete",
            f"field_{fields['Kontrol sonucu'].id}": "Uygun",
            f"field_{fields['Aciklama'].id}": "Turkce test: Ölçüm",
            f"field_{fields['Miktar'].id}": "12,5",
        },
    )
    assert response.status_code == 302
    submission = DynamicFormSubmission.query.one()
    assert submission.status == "completed"
    assert assignment.status == "completed"
    assert db.session.get(AppSetting, "sales_readiness:competitor_dynamic_checklist").value == "1"
    assert db.session.get(AppSetting, "sales_readiness:competitor_form_designer") is None
    audit = AuditLog.query.filter_by(action="form_submission_completed").one()
    assert "Olcum" not in (audit.new_values or "")
    assert "answered_field_ids" in audit.new_values
    assert not any(log.entity_type == "DynamicFormAnswer" for log in AuditLog.query.all())

    task_response = client.get("/uzerime-atananlar?module=dynamic_form")
    assert "Tamamland" in task_response.get_data(as_text=True)


def test_department_assignment_access_permissions_and_tenant_isolation(client):
    company, manager, worker, _template, version = setup_published_form(client, "803")
    contact = PersonnelContact(
        company_id=company.id,
        full_name=worker.full_name,
        department="Uretim",
        is_active=True,
    )
    db.session.add(contact)
    db.session.flush()
    worker.personnel_contact_id = contact.id
    db.session.commit()
    login(client, manager)
    response = client.post(
        f"/dinamik-formlar/surum/{version.id}/ata",
        data={"target_type": "department", "assigned_department": "Uretim"},
    )
    assert response.status_code == 302
    assignment = DynamicFormAssignment.query.one()

    plain = create_user("plain-803", company=company)
    login(client, plain)
    assert client.get("/dinamik-formlar").status_code == 403
    assert client.get(f"/dinamik-formlar/atama/{assignment.id}/doldur").status_code == 403

    viewer = create_user(
        "viewer-803",
        company=company,
        permissions=("dynamic_forms.view",),
    )
    login(client, viewer)
    assert client.get("/dinamik-formlar").status_code == 200
    assert client.get(f"/dinamik-formlar/surum/{version.id}/sonuclar").status_code == 403

    other_company = create_company("804")
    foreign_user = create_user(
        "foreign-804",
        company=other_company,
        permissions=("dynamic_forms.respond",),
        title="Uretim",
    )
    login(client, foreign_user)
    assert client.get(f"/dinamik-formlar/atama/{assignment.id}/doldur").status_code == 404

    login(client, worker)
    assert client.get(f"/dinamik-formlar/atama/{assignment.id}/doldur").status_code == 200


def test_department_match_does_not_authorize_partial_word_collision(client):
    company, manager, _worker, _template, version = setup_published_form(client, "806")
    it_user = create_user(
        "quality-806",
        company=company,
        permissions=("dynamic_forms.respond",),
        full_name="Kalite Personeli",
    )
    it_user.title = "Kalite Yöneticisi"
    db.session.add(CompanyDepartment(company_id=company.id, name="IT", sort_order=2))
    db.session.commit()

    login(client, manager)
    response = client.post(
        f"/dinamik-formlar/surum/{version.id}/ata",
        data={"target_type": "department", "assigned_department": "IT"},
        follow_redirects=True,
    )

    assert "yanıtlayabilecek aktif kullanıcı bulunamadı" in response.get_data(as_text=True)
    assert DynamicFormAssignment.query.count() == 0


def test_department_recipient_snapshot_and_submission_privacy(client):
    company, manager, worker, _template, version = setup_published_form(client, "808")
    contact = PersonnelContact(
        company_id=company.id,
        full_name=worker.full_name,
        department="Uretim",
        is_active=True,
    )
    db.session.add(contact)
    db.session.flush()
    worker.personnel_contact_id = contact.id
    db.session.commit()

    login(client, manager)
    client.post(
        f"/dinamik-formlar/surum/{version.id}/ata",
        data={"target_type": "department", "assigned_department": "Uretim"},
    )
    assignment = DynamicFormAssignment.query.one()

    late_worker = create_user(
        "late-worker-808",
        company=company,
        permissions=("dynamic_forms.respond",),
        full_name="Sonradan Gelen Personel",
    )
    late_contact = PersonnelContact(
        company_id=company.id,
        full_name=late_worker.full_name,
        department="Uretim",
        is_active=True,
    )
    db.session.add(late_contact)
    db.session.flush()
    late_worker.personnel_contact_id = late_contact.id
    db.session.commit()

    login(client, late_worker)
    assert client.get(f"/dinamik-formlar/atama/{assignment.id}/doldur").status_code == 403

    fields = {field.label: field for field in version.fields}
    login(client, worker)
    client.post(
        f"/dinamik-formlar/atama/{assignment.id}/doldur",
        data={
            "action": "complete",
            f"field_{fields['Kontrol sonucu'].id}": "Uygun",
            f"field_{fields['Miktar'].id}": "1",
        },
    )
    submission = DynamicFormSubmission.query.one()

    login(client, late_worker)
    assert client.get(f"/dinamik-formlar/sonuc/{submission.id}").status_code == 403


def test_department_assignment_completes_after_all_recipients_respond(client):
    company, manager, first_worker, _template, version = setup_published_form(client, "807")
    second_worker = create_user(
        "worker-two-807",
        company=company,
        permissions=("dynamic_forms.respond",),
        full_name="İkinci Üretim Personeli",
    )
    for worker in (first_worker, second_worker):
        contact = PersonnelContact(
            company_id=company.id,
            full_name=worker.full_name,
            department="Uretim",
            is_active=True,
        )
        db.session.add(contact)
        db.session.flush()
        worker.personnel_contact_id = contact.id
    db.session.commit()

    login(client, manager)
    client.post(
        f"/dinamik-formlar/surum/{version.id}/ata",
        data={"target_type": "department", "assigned_department": "Uretim"},
    )
    assignment = DynamicFormAssignment.query.one()
    fields = {field.label: field for field in version.fields}
    complete_payload = {
        "action": "complete",
        f"field_{fields['Kontrol sonucu'].id}": "Uygun",
        f"field_{fields['Miktar'].id}": "1",
    }

    login(client, first_worker)
    client.post(f"/dinamik-formlar/atama/{assignment.id}/doldur", data=complete_payload)
    db.session.refresh(assignment)
    assert assignment.status == "assigned"

    login(client, second_worker)
    client.post(f"/dinamik-formlar/atama/{assignment.id}/doldur", data=complete_payload)
    db.session.refresh(assignment)
    assert assignment.status == "completed"

    login(client, manager)
    body = client.get("/dinamik-formlar").get_data(as_text=True)
    assert "Tamamlandı" in body


def test_results_excel_contains_snapshot_and_answers(client):
    _company, manager, worker, _template, version = setup_published_form(client, "805")
    login(client, manager)
    client.post(
        f"/dinamik-formlar/surum/{version.id}/ata",
        data={"target_type": "user", "assigned_user_id": str(worker.id)},
    )
    assignment = DynamicFormAssignment.query.one()
    fields = {field.label: field for field in version.fields}
    login(client, worker)
    client.post(
        f"/dinamik-formlar/atama/{assignment.id}/doldur",
        data={
            "action": "complete",
            f"field_{fields['Kontrol sonucu'].id}": "Uygun Degil",
            f"field_{fields['Miktar'].id}": "7",
        },
    )
    login(client, manager)
    response = client.get(f"/dinamik-formlar/surum/{version.id}/excel")
    assert_xlsx_response(response)
    values = sheet_values(response.data)
    assert "Kontrol sonucu" in values[0]
    assert "Uygun Degil" in values[1]
    assert "Uretim Personeli" in values[1]


def test_runtime_schema_creates_tables_and_marks_existing_modules(app):
    with app.app_context():
        ensure_runtime_schema()
        assert db.session.get(AppSetting, "sales_readiness:competitor_change_management").value == "1"
        assert db.session.get(AppSetting, "sales_readiness:competitor_deviation_management").value == "1"
        assert db.session.get(AppSetting, "sales_readiness:competitor_dynamic_checklist").value == "1"
