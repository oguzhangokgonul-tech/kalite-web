from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import COMPANY_MODULE_KEYS, Company, User
from app.routes import store_uploaded_file

from .helpers import create_company, create_user, login


def company_form_payload(code="401"):
    return {
        "code": code,
        "name": f"Firma {code}",
        "slug": f"firma-{code}",
        "primary_domain": "",
        "custom_domain": "",
        "brand_primary_color": "#123456",
        "brand_accent_color": "#00aa88",
        "user_limit": "12",
        "storage_quota_mb": "256",
        "package_key": "production_plus",
        "is_active": "on",
        "enabled_modules": list(COMPANY_MODULE_KEYS),
    }


def test_company_form_saves_branding_limits_and_logo(app, client):
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)

    response = client.post(
        "/companies/new",
        data={
            **company_form_payload("401"),
            "company_logo": (BytesIO(b"logo-bytes"), "logo.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    company = Company.query.filter_by(code="401").one()
    assert company.brand_primary_color == "#123456"
    assert company.brand_accent_color == "#00aa88"
    assert company.user_limit == 12
    assert company.storage_quota_mb == 256
    assert company.logo_file_path.startswith(f"company-{company.id:03d}/company/logos/")

    logo_response = client.get(f"/companies/{company.id}/logo")
    assert logo_response.status_code == 200
    assert logo_response.get_data() == b"logo-bytes"


def test_company_logo_route_is_scoped_to_current_company(app, client):
    company_a = create_company("402")
    company_b = create_company("403")
    logo_path = Path(app.config["UPLOAD_FOLDER"]) / f"company-{company_b.id:03d}" / "company" / "logos" / "logo.png"
    logo_path.parent.mkdir(parents=True, exist_ok=True)
    logo_path.write_bytes(b"company-b-logo")
    company_b.logo_file_path = f"company-{company_b.id:03d}/company/logos/logo.png"
    company_b.logo_original_name = "logo.png"
    db.session.commit()
    user_a = create_user("company-a-user", company=company_a)
    login(client, user_a)

    response = client.get(f"/companies/{company_b.id}/logo")

    assert response.status_code == 404


def test_user_limit_blocks_new_active_user(app, client):
    company = create_company("404")
    company.user_limit = 1
    manager = create_user(
        "manager",
        company=company,
        permissions=("users.manage",),
    )
    db.session.commit()
    login(client, manager)

    response = client.post(
        "/users/new",
        data={
            "full_name": "Limit User",
            "username": "limit-user",
            "title": "Personel",
            "email": "",
            "password": "1234",
            "is_active": "on",
        },
    )

    assert response.status_code == 200
    assert User.query.filter_by(company_id=company.id, username="limit-user").first() is None


def test_inactive_users_do_not_count_against_user_limit(app, client):
    company = create_company("405")
    company.user_limit = 2
    manager = create_user(
        "manager-405",
        company=company,
        permissions=("users.manage",),
    )
    inactive_user = create_user("inactive-405", company=company)
    inactive_user.is_active = False
    db.session.commit()
    login(client, manager)

    response = client.post(
        "/users/new",
        data={
            "full_name": "Allowed User",
            "username": "allowed-user",
            "title": "Personel",
            "email": "",
            "password": "1234",
            "is_active": "on",
        },
    )

    assert response.status_code == 302
    assert User.query.filter_by(company_id=company.id, username="allowed-user").first()


def test_storage_quota_blocks_company_upload_without_counting_other_company(app):
    company_a = create_company("406")
    company_b = create_company("407")
    company_a.storage_quota_mb = 1
    company_b.storage_quota_mb = 1
    db.session.commit()
    upload_root = Path(app.config["UPLOAD_FOLDER"])
    company_a_folder = upload_root / f"company-{company_a.id:03d}" / "existing"
    company_b_folder = upload_root / f"company-{company_b.id:03d}" / "existing"
    company_a_folder.mkdir(parents=True, exist_ok=True)
    company_b_folder.mkdir(parents=True, exist_ok=True)
    (company_a_folder / "almost-full.bin").write_bytes(b"a" * (1024 * 1024 - 4))
    (company_b_folder / "other-company.bin").write_bytes(b"b" * (1024 * 1024 - 4))

    with app.test_request_context("/"):
        from flask import g

        g.current_company = company_a
        g.current_user = None
        g.current_user_is_super_admin = False
        uploaded_file = FileStorage(
            stream=BytesIO(b"too-large"),
            filename="kanit.pdf",
            content_type="application/pdf",
        )
        with pytest.raises(ValueError, match="storage_quota_exceeded"):
            store_uploaded_file(
                uploaded_file,
                folder="actions/files",
                company_id=company_a.id,
            )

    with app.test_request_context("/"):
        from flask import g

        g.current_company = company_b
        g.current_user = None
        g.current_user_is_super_admin = False
        uploaded_file = FileStorage(
            stream=BytesIO(b"ok"),
            filename="kanit.pdf",
            content_type="application/pdf",
        )
        _safe_name, stored_name, _mime_type = store_uploaded_file(
            uploaded_file,
            folder="actions/files",
            company_id=company_b.id,
        )

    assert stored_name.startswith(f"company-{company_b.id:03d}/actions/files/")
