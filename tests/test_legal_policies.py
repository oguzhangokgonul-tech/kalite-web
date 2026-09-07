from datetime import date, datetime

from app.extensions import db
from app.legal import (
    LEGAL_POLICY_VERSION,
    ensure_legal_schema,
    pending_legal_documents_for_user,
)
from app.models import AppSetting, AuditLog, Company, CompanyLegalProfile, LegalAcceptance, LegalDocument
from app.routes import SALES_READINESS_SETTING_PREFIX
from .helpers import create_company, create_user, login


def test_public_legal_pages_render_without_login(app, client):
    response = client.get("/legal/kullanim-sartlari")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "VolkaPortal" in body
    assert "Kullan\u0131m \u015eartlar\u0131" in body
    assert f"Versiyon {LEGAL_POLICY_VERSION}" in body
    assert client.get("/legal/bilinmeyen").status_code == 404


def test_login_page_links_to_legal_documents(app, client):
    response = client.get("/login")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/legal/kullanim-sartlari" in body
    assert "/legal/gizlilik-politikasi" in body
    assert "/legal/kvkk-aydinlatma-metni" in body


def test_legal_documents_admin_requires_superadmin_account(app, client):
    viewer = create_user("legal-viewer")
    login(client, viewer)

    assert client.get("/sistem/legal-metinler").status_code == 403

    superadmin = create_user("superadmin")
    login(client, superadmin)

    response = client.get("/sistem/legal-metinler")

    assert response.status_code == 200
    assert "Hukuki Metinler" in response.get_data(as_text=True)


def test_superadmin_can_create_and_publish_legal_revision(app, client):
    superadmin = create_user("superadmin")
    login(client, superadmin)

    response = client.post(
        "/sistem/legal-metinler/yeni-revizyon",
        data={
            "document_type": "privacy",
            "version": "2026.10",
            "effective_date": "2026-10-01",
            "title": "Gizlilik Politikasi R2",
            "content": "Yeni gizlilik metni.",
            "publish_now": "1",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    published = LegalDocument.query.filter_by(
        document_type="privacy",
        status="published",
    ).one()
    assert published.version == "2026.10"
    assert LegalDocument.query.filter_by(
        document_type="privacy",
        version=LEGAL_POLICY_VERSION,
        status="archived",
    ).count() == 1
    assert AuditLog.query.filter_by(
        entity_type="LegalDocument",
        action="legal_document_published",
    ).count() == 1
    setting = db.session.get(AppSetting, f"{SALES_READINESS_SETTING_PREFIX}month4_legal")
    assert setting is not None
    assert setting.value == "1"


def test_legal_acceptance_flow_records_current_documents(app, client):
    app.config["LEGAL_ACCEPTANCE_REQUIRED"] = True
    company = create_company("671")
    user = create_user("legal-user", company=company)
    login(client, user, company)

    response = client.get("/")

    assert response.status_code == 302
    assert "/legal/kabul" in response.headers["Location"]

    response = client.post(
        "/legal/kabul",
        data={"accept_legal_documents": "1", "next": "/"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert LegalAcceptance.query.filter_by(
        user_id=user.id,
        company_id=company.id,
    ).count() == 4
    assert AuditLog.query.filter_by(
        entity_type="LegalAcceptance",
        action="legal_acceptance_recorded",
    ).count() == 4
    assert client.get("/").status_code == 200


def test_new_published_legal_version_requires_reacceptance(app):
    app.config["LEGAL_ACCEPTANCE_REQUIRED"] = True
    company = create_company("672")
    user = create_user("legal-version-user", company=company)
    ensure_legal_schema()
    for document in pending_legal_documents_for_user(user, company):
        db.session.add(
            LegalAcceptance(
                company_id=company.id,
                user_id=user.id,
                legal_document_id=document.id,
                document_type=document.document_type,
                version=document.version,
            )
        )
    db.session.commit()

    assert pending_legal_documents_for_user(user, company) == []
    for document in LegalDocument.query.filter_by(
        document_type="terms",
        status="published",
    ).all():
        document.status = "archived"
    db.session.add(
        LegalDocument(
            document_type="terms",
            slug="kullanim-sartlari",
            title="Kullanim Sartlari R2",
            version="2026.11",
            content="Yeni kullanim sartlari.",
            status="published",
            effective_date=date(2026, 11, 1),
            published_at=datetime.utcnow(),
        )
    )
    db.session.commit()

    pending = pending_legal_documents_for_user(user, company)

    assert len(pending) == 1
    assert pending[0].document_type == "terms"
    assert pending[0].version == "2026.11"


def test_company_form_saves_legal_profile(app, client):
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)

    response = client.post(
        "/companies/new",
        data={
            "code": "673",
            "name": "Legal Firma",
            "slug": "legal-firma",
            "primary_domain": "",
            "custom_domain": "",
            "package_key": "iso_core",
            "is_active": "on",
            "legal_name": "Legal Firma A.S.",
            "data_controller_name": "Legal Firma A.S.",
            "kvkk_contact_email": "kvkk@example.test",
            "tax_number": "1234567890",
            "mersis_number": "0123456789012345",
            "dpo_contact": "hukuk@example.test",
            "legal_address": "Organize Sanayi Bolgesi",
            "enabled_modules": ["documents", "if_management"],
        },
    )

    assert response.status_code == 302
    company = Company.query.filter_by(code="673").one()
    profile = CompanyLegalProfile.query.filter_by(company_id=company.id).one()
    assert profile.legal_name == "Legal Firma A.S."
    assert profile.kvkk_contact_email == "kvkk@example.test"
    assert profile.updated_by_user_id == superadmin.id


def test_runtime_schema_marks_sales_readiness_legal_done(app):
    from app.seed import ensure_runtime_schema

    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:month4_legal")
    assert setting is not None
    assert setting.value == "1"
