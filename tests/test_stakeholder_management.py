from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    CompanyDepartment,
    CompanyModule,
    Notification,
    PersonnelContact,
    StakeholderParty,
    StakeholderRequirement,
    StakeholderReview,
)
from app.seed import ensure_runtime_schema
from app.reminders import generate_due_reminders

from .helpers import assert_xlsx_response, create_company, create_user, login, sheet_values


MANAGER_PERMISSIONS = (
    "stakeholder.view",
    "stakeholder.manage",
    "stakeholder.review",
    "stakeholder.export",
    "stakeholder.archive",
)


def setup_users(code="951"):
    company = create_company(code)
    db.session.add_all(
        [
            CompanyDepartment(company_id=company.id, name="Kalite", sort_order=1),
            CompanyDepartment(company_id=company.id, name="Üretim", sort_order=2),
        ]
    )
    db.session.commit()
    manager = create_user(
        f"manager-{code}",
        company=company,
        permissions=MANAGER_PERMISSIONS,
        full_name="Yönetim Temsilcisi",
    )
    owner = create_user(
        f"owner-{code}",
        company=company,
        permissions=("stakeholder.view",),
        full_name="Beklenti Sorumlusu",
    )
    return company, manager, owner


def party_payload(owner, **overrides):
    values = {
        "name": "Büyük Müşteri A.Ş.",
        "internal_external": "external",
        "category": "Müşteri",
        "relevance_status": "relevant",
        "relevance_reason": "Ürün şartlarını belirler.",
        "department": "Kalite",
        "owner_user_id": str(owner.id),
        "influence_score": "4",
        "importance_score": "5",
        "review_interval_months": "12",
        "next_review_date": (date.today() + timedelta(days=20)).isoformat(),
    }
    values.update(overrides)
    return values


def requirement_payload(owner, **overrides):
    values = {
        "requirement_type": "customer",
        "title": "Zamanında teslimat",
        "description": "Siparişler sözleşme tarihinde teslim edilmeli.",
        "source": "Müşteri sözleşmesi",
        "process": "Sevkiyat",
        "fulfillment_status": "not_assessed",
        "responsible_user_id": str(owner.id),
        "due_date": (date.today() + timedelta(days=10)).isoformat(),
        "improvement_plan": "",
        "climate_related": "on",
    }
    values.update(overrides)
    return values


def create_party(client, manager, owner):
    login(client, manager)
    response = client.post("/ilgili-taraflar/yeni", data=party_payload(owner))
    assert response.status_code == 302
    return StakeholderParty.query.filter_by(company_id=manager.company_id).one()


def add_requirement(client, party, owner, **overrides):
    response = client.post(
        f"/ilgili-taraflar/{party.id}/beklenti/yeni",
        data=requirement_payload(owner, **overrides),
    )
    assert response.status_code == 302
    return StakeholderRequirement.query.filter_by(party_id=party.id).one()


def test_crud_number_assignment_activation_and_audit(client):
    _company, manager, owner = setup_users("951")
    party = create_party(client, manager, owner)
    assert party.party_no == f"ILT-{date.today().year}-0001"
    assert party.priority_score == 20
    assert Notification.query.filter_by(user_id=owner.id).count() == 1
    requirement = add_requirement(client, party, owner)
    assert requirement.climate_related is True
    assert Notification.query.filter_by(user_id=owner.id).count() == 2

    response = client.post(f"/ilgili-taraflar/{party.id}/aktiflestir")
    assert response.status_code == 302
    db.session.refresh(party)
    assert party.status == "active"
    assert db.session.get(AppSetting, "sales_readiness:competitor_stakeholder_management").value == "1"
    assert AuditLog.query.filter_by(action="stakeholder_activated").count() == 1
    reminder_stats = generate_due_reminders(company_id=party.company_id, run_date=date.today())
    db.session.commit()
    assert reminder_stats["notifications"] >= 1
    assert Notification.query.filter(
        Notification.source_key.like("stakeholder-review:%")
    ).count() >= 1
    assert Notification.query.filter(
        Notification.source_key.like("stakeholder-requirement-due:%")
    ).count() >= 1
    page = client.get("/ilgili-taraflar")
    assert page.status_code == 200
    assert party.party_no in page.get_data(as_text=True)


def test_negative_fulfillment_requires_link_or_improvement_plan(client):
    _company, manager, owner = setup_users("952")
    party = create_party(client, manager, owner)
    response = client.post(
        f"/ilgili-taraflar/{party.id}/beklenti/yeni",
        data=requirement_payload(owner, fulfillment_status="not_met"),
    )
    assert response.status_code == 200
    assert "iyileştirme planı" in response.get_data(as_text=True)
    assert StakeholderRequirement.query.count() == 0
    add_requirement(
        client,
        party,
        owner,
        fulfillment_status="partial",
        improvement_plan="Teslimat planı haftalık izlenecek.",
    )
    assert StakeholderRequirement.query.one().fulfillment_status == "partial"


def test_review_history_is_immutable_and_updates_dates(client):
    _company, manager, owner = setup_users("953")
    party = create_party(client, manager, owner)
    requirement = add_requirement(client, party, owner, improvement_plan="Takip planı")
    client.post(f"/ilgili-taraflar/{party.id}/aktiflestir")

    login(client, owner)
    next_date = date.today() + timedelta(days=90)
    response = client.post(
        f"/ilgili-taraflar/{party.id}/degerlendir",
        data={
            "requirement_id": str(requirement.id),
            "outcome": "partial",
            "summary": "Teslimat performansı izleniyor.",
            "evidence_note": "Aylık KPI raporu",
            "next_review_date": next_date.isoformat(),
        },
    )
    assert response.status_code == 302
    review = StakeholderReview.query.one()
    assert review.reviewer_user_id == owner.id
    assert review.requirement_id == requirement.id
    assert db.session.get(StakeholderParty, party.id).next_review_date == next_date
    assert db.session.get(StakeholderRequirement, requirement.id).fulfillment_status == "partial"
    assert review.party_name_snapshot == "Büyük Müşteri A.Ş."
    assert review.requirement_title_snapshot == "Zamanında teslimat"
    assert review.requirement_source_snapshot == "Müşteri sözleşmesi"
    assert review.fulfillment_status_before == "not_assessed"

    party.name = "Yeni Müşteri Adı"
    requirement.title = "Yeni Beklenti Başlığı"
    db.session.commit()
    db.session.refresh(review)
    assert review.party_name_snapshot == "Büyük Müşteri A.Ş."
    assert review.requirement_title_snapshot == "Zamanında teslimat"

    review.summary = "Geçmiş değiştirilmeye çalışıldı"
    with pytest.raises(ValueError, match="değiştirilemez"):
        db.session.commit()
    db.session.rollback()
    assert db.session.get(StakeholderReview, review.id).summary == "Teslimat performansı izleniyor."


def test_access_department_draft_and_tenant_isolation(client):
    company, manager, owner = setup_users("954")
    party = create_party(client, manager, owner)
    foreign_company = create_company("955")
    foreign = create_user(
        "foreign-955", company=foreign_company, permissions=MANAGER_PERMISSIONS
    )
    login(client, foreign)
    assert client.get(f"/ilgili-taraflar/{party.id}").status_code == 404
    assert client.post(f"/ilgili-taraflar/{party.id}/arsivle").status_code == 404

    contact = PersonnelContact(
        company_id=company.id,
        full_name="Kalite Müdürü",
        department="Kalite",
        is_active=True,
    )
    db.session.add(contact)
    db.session.commit()
    department_manager = create_user(
        "department-manager-954",
        company=company,
        role_key="department_manager",
        full_name="Kalite Müdürü",
    )
    department_manager.personnel_contact_id = contact.id
    db.session.commit()
    login(client, department_manager)
    assert client.post("/ilgili-taraflar/yeni", data=party_payload(owner)).status_code == 302
    own = StakeholderParty.query.filter_by(created_by_user_id=department_manager.id).one()
    assert client.get(f"/ilgili-taraflar/{own.id}/duzenle").status_code == 200
    blocked = client.post(
        f"/ilgili-taraflar/{own.id}/duzenle",
        data=party_payload(owner, department="Üretim"),
    )
    assert blocked.status_code == 403
    assert client.post(f"/ilgili-taraflar/{own.id}/aktiflestir").status_code == 403


def test_tasks_excel_archive_and_archived_immutability(client):
    _company, manager, owner = setup_users("956")
    party = create_party(client, manager, owner)
    requirement = add_requirement(client, party, owner)
    client.post(f"/ilgili-taraflar/{party.id}/aktiflestir")

    login(client, owner)
    tasks = client.get("/uzerime-atananlar?module=stakeholder")
    assert tasks.status_code == 200
    assert party.party_no in tasks.get_data(as_text=True)

    login(client, manager)
    report = client.get("/ilgili-taraflar/excel")
    assert_xlsx_response(report)
    rows = sheet_values(report.data)
    assert "İlgili Taraf" in rows[0]
    assert "Beklenti Durumu" in rows[0]
    assert "Son Değerlendirme Özeti" in rows[0]
    assert party.party_no in rows[1]
    assert "Zamanında teslimat" in rows[1]

    assert client.post(f"/ilgili-taraflar/{party.id}/arsivle").status_code == 302
    assert db.session.get(StakeholderParty, party.id).status == "archived"
    assert client.get(f"/ilgili-taraflar/{party.id}/duzenle").status_code == 403
    assert client.get(f"/ilgili-taraflar/beklenti/{requirement.id}/duzenle").status_code == 403
    assert client.get(f"/ilgili-taraflar/{party.id}/degerlendir").status_code == 403


def test_archived_requirement_leaves_tasks_and_clears_assignment(client):
    _company, manager, owner = setup_users("958")
    party = create_party(client, manager, owner)
    requirement = add_requirement(client, party, owner)
    client.post(f"/ilgili-taraflar/{party.id}/aktiflestir")

    login(client, owner)
    before = client.get("/uzerime-atananlar?module=stakeholder").get_data(as_text=True)
    assert requirement.title in before

    login(client, manager)
    assert client.post(
        f"/ilgili-taraflar/beklenti/{requirement.id}/arsivle"
    ).status_code == 302
    assignment = Notification.query.filter_by(
        company_id=party.company_id,
        source_key=f"stakeholder-requirement:{requirement.id}",
    ).one()
    assert assignment.is_read is True

    login(client, owner)
    after = client.get("/uzerime-atananlar?module=stakeholder").get_data(as_text=True)
    assert requirement.title not in after


def test_disabled_module_and_runtime_schema_marker(client):
    company, manager, _owner = setup_users("957")
    setting = CompanyModule.query.filter_by(
        company_id=company.id, module_key="stakeholder_management"
    ).one()
    setting.is_enabled = False
    db.session.commit()
    login(client, manager)
    assert client.get("/ilgili-taraflar").status_code == 403
    assert client.get("/ilgili-taraflar/yeni").status_code == 403

    ensure_runtime_schema()
    readiness = db.session.get(AppSetting, "sales_readiness:competitor_stakeholder_management")
    assert readiness is not None
    assert readiness.value == "1"
