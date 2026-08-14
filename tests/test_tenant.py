from datetime import date
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.exceptions import NotFound

from app.extensions import db
from app.models import Action, Company, User
from app.tenant import (
    assign_current_company,
    company_primary_domain,
    current_company_id,
    ensure_same_company,
    host_is_tenant_base,
    scoped_query,
    tenant_base_url,
    tenant_company_from_host,
    tenant_url_for_company,
)


@pytest.fixture()
def app(tmp_path):
    test_app = Flask(__name__)
    test_app.config.update(
        SECRET_KEY="test",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TENANT_BASE_DOMAIN="volkaportal.com",
        UPLOAD_FOLDER=tmp_path,
        PREFERRED_URL_SCHEME="https",
    )
    db.init_app(test_app)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def companies(app):
    erprefabrik = Company(
        code="001",
        name="Er Prefabrik",
        slug="erprefabrik",
        primary_domain="erprefabrik.volkaportal.com",
        is_active=True,
    )
    deneme = Company(
        code="000",
        name="Deneme Hesabi",
        slug="deneme",
        primary_domain="deneme.volkaportal.com",
        is_active=True,
    )
    passive = Company(
        code="999",
        name="Pasif Firma",
        slug="pasif",
        primary_domain="pasif.volkaportal.com",
        is_active=False,
    )
    db.session.add_all([erprefabrik, deneme, passive])
    db.session.commit()
    return erprefabrik, deneme, passive


def user_for(company):
    return User(
        username=f"user-{company.code}",
        full_name=f"User {company.code}",
        password_hash="not-used",
        company_id=company.id,
        is_active=True,
    )


def action_for(company, title):
    return Action(
        company_id=company.id,
        title=title,
        responsible_owner="Test User",
        department="Kalite",
        termin_date=date(2026, 8, 13),
    )


def test_tenant_company_from_primary_domain(app, companies):
    erprefabrik, _deneme, _passive = companies

    with app.app_context():
        company = tenant_company_from_host("erprefabrik.volkaportal.com")

    assert company.id == erprefabrik.id


def test_tenant_company_from_slug_subdomain(app, companies):
    _erprefabrik, deneme, _passive = companies

    with app.app_context():
        company = tenant_company_from_host("deneme.volkaportal.com")

    assert company.id == deneme.id


def test_tenant_company_ignores_passive_company(app, companies):
    with app.app_context():
        company = tenant_company_from_host("pasif.volkaportal.com")

    assert company is None


def test_tenant_base_host_accepts_www_and_port(app):
    with app.app_context():
        assert host_is_tenant_base("www.volkaportal.com:443")


def test_company_primary_domain_falls_back_to_slug(app, companies):
    _erprefabrik, deneme, _passive = companies
    deneme.primary_domain = None
    db.session.commit()

    with app.app_context():
        domain = company_primary_domain(deneme)

    assert domain == "deneme.volkaportal.com"


def test_oguzhan_user_is_scoped_to_current_company(app, companies):
    erprefabrik, deneme, _passive = companies
    oguzhan = User(
        username="oguzhan",
        full_name="Oguzhan",
        password_hash="not-used",
        company_id=erprefabrik.id,
        is_active=True,
    )
    db.session.add(oguzhan)
    db.session.commit()

    with app.test_request_context("/"):
        from flask import g
        from app.routes import oguzhan_user

        g.current_company = deneme
        g.current_user = None
        g.current_user_is_super_admin = False

        assert oguzhan_user() is None

        g.current_company = erprefabrik
        assert oguzhan_user().id == oguzhan.id


def test_tenant_urls_are_generated_from_configured_domains(app, companies):
    erprefabrik, _deneme, _passive = companies

    with app.app_context():
        company_url = tenant_url_for_company(erprefabrik, "/")
        base_url = tenant_base_url("/login")

    assert company_url == "https://erprefabrik.volkaportal.com/"
    assert base_url == "https://volkaportal.com/login"


def test_scoped_query_limits_records_to_current_company(app, companies):
    erprefabrik, deneme, _passive = companies
    db.session.add_all([
        action_for(erprefabrik, "Er Prefabrik Aksiyon"),
        action_for(deneme, "Deneme Aksiyon"),
    ])
    db.session.commit()

    with app.test_request_context("/"):
        db.session.add(user_for(erprefabrik))
        db.session.commit()
        from flask import g

        g.current_company = erprefabrik
        g.current_user_is_super_admin = False

        titles = [
            action.title
            for action in scoped_query(Action.query, Action).order_by(Action.title.asc()).all()
        ]

    assert titles == ["Er Prefabrik Aksiyon"]


def test_scoped_query_allows_superadmin_without_company_scope(app, companies):
    erprefabrik, deneme, _passive = companies
    db.session.add_all([
        action_for(erprefabrik, "Er Prefabrik Aksiyon"),
        action_for(deneme, "Deneme Aksiyon"),
    ])
    db.session.commit()

    with app.test_request_context("/"):
        from flask import g

        g.current_company = None
        g.current_user = None
        g.current_user_is_super_admin = True

        titles = {
            action.title
            for action in scoped_query(Action.query, Action).all()
        }

    assert titles == {"Er Prefabrik Aksiyon", "Deneme Aksiyon"}


def test_assign_current_company_sets_company_id(app, companies):
    erprefabrik, _deneme, _passive = companies

    with app.test_request_context("/"):
        from flask import g

        g.current_company = erprefabrik
        g.current_user = None
        g.current_user_is_super_admin = False
        action = action_for(erprefabrik, "Yeni Aksiyon")
        action.company_id = None

        assign_current_company(action)

    assert action.company_id == erprefabrik.id


def test_ensure_same_company_rejects_cross_company_record(app, companies):
    erprefabrik, deneme, _passive = companies
    action = action_for(deneme, "Deneme Aksiyon")
    db.session.add(action)
    db.session.commit()

    with app.test_request_context("/"):
        from flask import g

        g.current_company = erprefabrik
        g.current_user = None
        g.current_user_is_super_admin = False

        with pytest.raises(NotFound):
            ensure_same_company(action)


def test_current_company_id_prefers_current_company(app, companies):
    erprefabrik, _deneme, _passive = companies

    with app.test_request_context("/"):
        from flask import g

        g.current_company = erprefabrik
        g.current_user = None
        g.current_user_is_super_admin = False

        assert current_company_id() == erprefabrik.id


def test_upload_storage_path_uses_company_folder(app, companies):
    erprefabrik, _deneme, _passive = companies

    with app.test_request_context("/"):
        from flask import g
        from app.routes import upload_storage_path

        g.current_company = erprefabrik
        g.current_user = None
        g.current_user_is_super_admin = False

        relative_path, absolute_path = upload_storage_path("kanit.pdf", "actions/files")

    assert relative_path.as_posix() == f"company-{erprefabrik.id:03d}/actions/files/kanit.pdf"
    assert absolute_path.parent.exists()


def test_existing_uploaded_file_path_falls_back_to_legacy_path(app):
    with app.test_request_context("/"):
        from app.routes import existing_uploaded_file_path

        upload_dir = Path(app.config["UPLOAD_FOLDER"])
        legacy_path = upload_dir / "legacy.pdf"
        legacy_path.write_text("legacy", encoding="utf-8")

        file_path = existing_uploaded_file_path("company-001/actions/files/legacy.pdf")

    assert file_path == legacy_path
