from pathlib import Path

from app.extensions import db
from app.models import AppSetting, AuditLog, Company, Notification
from app.seed import ensure_runtime_schema
from app.system_admin import sanitize_admin_log_line
from tests.helpers import create_company, create_user, login, make_document


def test_system_admin_panel_is_superadmin_account_only(app, client):
    company = create_company("701")
    viewer = create_user("admin-panel-viewer", company=company)
    manager = create_user(
        "admin-panel-manager",
        company=company,
        permissions=("users.manage",),
    )
    superadmin_role_user = create_user(
        "role-super-admin",
        role_key="super_admin",
    )

    login(client, viewer, company)
    assert client.get("/sistem/admin-paneli").status_code == 403

    login(client, manager, company)
    assert client.get("/sistem/admin-paneli").status_code == 403

    login(client, superadmin_role_user)
    assert client.get("/sistem/admin-paneli").status_code == 403


def test_system_admin_panel_renders_for_superadmin_and_marks_checklist(app, client):
    company = create_company("702", name="Panel Firma", package_key="iso_core")
    company.storage_quota_mb = 1
    company.user_limit = 3
    user = create_user("panel-user", company=company)
    create_user("panel-passive", company=company)
    make_document(app, company, uploader=user, content=b"panel file")
    upload_path = Path(app.config["UPLOAD_FOLDER"]) / f"company-{company.id:03d}" / "extra.txt"
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_text("disk", encoding="utf-8")
    db.session.add(
        AuditLog(
            company_id=company.id,
            user_id=user.id,
            entity_type="Document",
            entity_id="1",
            action="created",
            summary="Panel dokuman kaydi",
        )
    )
    db.session.add(Notification(user_id=user.id, company_id=company.id, message="Mail", email_sent_at=db.func.now()))
    db.session.commit()
    superadmin = create_user("superadmin")
    login(client, superadmin)

    response = client.get("/sistem/admin-paneli")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Admin Paneli" in body
    assert "Panel Firma" in body
    assert "Müşteri, lisans, disk, yedek, mail ve hata" in body
    assert "Veritaban" in body
    assert "Mail" in body
    assert "Yedek" in body
    assert "Disk" in body
    setting = db.session.get(AppSetting, "sales_readiness:month4_admin_panel")
    assert setting is not None
    assert setting.value == "1"


def test_system_admin_sidebar_link_only_for_superadmin_account(app, client):
    company = create_company("703")
    manager = create_user(
        "admin-panel-sidebar-manager",
        company=company,
        permissions=("users.manage",),
    )
    login(client, manager, company)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/sistem/admin-paneli"' not in response.get_data(as_text=True)

    superadmin = create_user("superadmin")
    login(client, superadmin)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/sistem/admin-paneli"' in response.get_data(as_text=True)


def test_system_admin_log_sanitizer_masks_sensitive_values():
    line = "ERROR password=secret token:abc api_key=xyz Authorization=Bearer"

    result = sanitize_admin_log_line(line)

    assert "secret" not in result
    assert "abc" not in result
    assert "xyz" not in result
    assert result.count("***") >= 3


def test_runtime_schema_marks_sales_readiness_admin_panel_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:month4_admin_panel")
    assert setting is not None
    assert setting.value == "1"
