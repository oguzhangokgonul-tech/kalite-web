"""Explicit, idempotent project release steps under the real service environment.

Run from the repo with PYTHONPATH=. after db upgrade. configure adds only new
project defaults; smoke does not create business records; mark is a separate
operator-authorized step after QA, backups, migration and live smoke checks.
"""
import argparse
from html.parser import HTMLParser

from app import create_app
from app.audit import record_audit_event
from app.extensions import db
from app.models import AppSetting, Company, CompanyModule, ProjectRecord, ProjectTask, Role, RolePermission, User
from app.routes import sales_readiness_completed_ids
from app.seed import PROJECT_ROLE_PERMISSIONS
from app.tenant import company_primary_domain, normalize_link_domain, tenant_base_domain, tenant_company_from_host


def configure_defaults():
    grants = dict(PROJECT_ROLE_PERMISSIONS)
    grants["super_admin"] = tuple(sorted({key for keys in grants.values() for key in keys}))
    changed = []
    for role_key, permissions in grants.items():
        role = Role.query.filter_by(key=role_key).first()
        if role is None:
            continue
        existing = {item.permission_key for item in role.permissions}
        for key in permissions:
            if key not in existing:
                role.permissions.append(RolePermission(permission_key=key))
                changed.append(f"role:{role_key}:{key}")
    for company in Company.query.all():
        module = CompanyModule.query.filter_by(company_id=company.id, module_key="projects").first()
        if module is None:
            enabled = company.package_key in {"iso_core", "production_plus"}
            db.session.add(CompanyModule(company_id=company.id, module_key="projects", is_enabled=enabled))
            changed.append(f"company:{company.id}:projects:{enabled}")
    if changed:
        record_audit_event("ProjectRelease", "configured", "Proje planlama varsayılanları eklendi",
            details={"changes": changed}, commit=False)
    db.session.commit()
    return changed


def smoke(app):
    before = (ProjectRecord.query.count(), ProjectTask.query.count())
    checks = 0
    missing_roles = []
    companies = Company.query.filter_by(is_active=True).all()
    for company in companies:
        domain = company_primary_domain(company)
        assert domain, f"Active company {company.id} has no routable domain"
        domains = {normalize_link_domain(value) for value in (company.primary_domain, company.custom_domain)}
        domains.discard("")
        domains.add(domain)
        for host in domains:
            resolved = tenant_company_from_host(host)
            assert resolved and resolved.id == company.id, f"Domain {host} does not resolve to company {company.id}"
        module = CompanyModule.query.filter_by(company_id=company.id, module_key="projects").one()
        company_checks = 0
        for role_key in ("management_representative", "department_manager", "department_staff", "viewer"):
            user = User.query.filter(User.company_id == company.id, User.is_active.is_(True), User.roles.any(key=role_key)).first()
            if user is None:
                missing_roles.append(f"company:{company.id}:{role_key}")
                continue
            for host in domains:
                base = "https://" + host
                client = app.test_client()
                with client.session_transaction(base_url=base) as session:
                    session["user_id"], session["company_id"] = user.id, company.id
                response = client.get("/projeler", base_url=base)
                if not module.is_enabled:
                    assert response.status_code in (403,404)
                else:
                    assert response.status_code == 200, (company.id,role_key,host,response.status_code)
                    assert "Proje Yönetimi" in response.get_data(as_text=True)
                    create = client.get("/projeler/yeni", base_url=base)
                    assert create.status_code == (200 if user.has_permission("projects.create") else 403)
                checks += 1
                company_checks += 1
        assert company_checks, f"Active company {company.id} has no eligible smoke-test user"
        other = next((row for row in companies if row.id != company.id), None)
        if other is not None:
            foreign_user = User.query.filter_by(company_id=other.id, is_active=True).first()
            assert foreign_user is not None, f"Company {other.id} has no cross-tenant test user"
            cross_client = app.test_client()
            cross_base = "https://" + domain
            with cross_client.session_transaction(base_url=cross_base) as session:
                session["user_id"], session["company_id"] = foreign_user.id, other.id
            denied = cross_client.get("/projeler", base_url=cross_base)
            assert denied.status_code == 302 and "/login" in denied.location, (
                company.id, other.id, denied.status_code, denied.location)
    assert checks, "No tenant/role smoke checks executed"
    assert before == (ProjectRecord.query.count(), ProjectTask.query.count())
    return {"checks": checks, "roles_without_live_users": missing_roles}


class CsrfParser(HTMLParser):
    token = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "input" and values.get("name") == "csrf_token":
            self.token = values.get("value")


def mark(app):
    admin = User.query.filter_by(username="superadmin", company_id=None, is_active=True).one()
    assert admin.has_role("super_admin")
    before = {row.key: row.value for row in AppSetting.query.filter(AppSetting.key.like("sales_readiness:%"))}
    client = app.test_client()
    base = "https://" + (tenant_base_domain() or "localhost")
    with client.session_transaction(base_url=base) as session:
        session["user_id"] = admin.id
    with app.test_request_context():
        from flask import url_for
        path = url_for("main.sales_readiness")
        selected = sales_readiness_completed_ids() | {"module_project_planning"}
    response = client.get(path, base_url=base)
    assert response.status_code == 200
    parser = CsrfParser()
    parser.feed(response.get_data(as_text=True))
    assert parser.token
    response = client.post(path, base_url=base, headers={"Referer": base + path},
        data={"csrf_token": parser.token, "completed_items": sorted(selected)})
    assert response.status_code == 302 and response.location.endswith(path), (
        response.status_code, response.location)
    db.session.expire_all()
    assert db.session.get(AppSetting,"sales_readiness:module_project_planning").value == "1"
    for key,value in before.items():
        if key != "sales_readiness:module_project_planning":
            assert db.session.get(AppSetting,key).value == value, key
    return "module_project_planning"


def mark_gantt(app):
    """Mark Gantt only after the planning foundation and Gantt gates pass."""
    admin = User.query.filter_by(username="superadmin", company_id=None, is_active=True).one()
    assert admin.has_role("super_admin")
    before = {row.key: row.value for row in AppSetting.query.filter(AppSetting.key.like("sales_readiness:%"))}
    client = app.test_client()
    base = "https://" + (tenant_base_domain() or "localhost")
    with client.session_transaction(base_url=base) as session:
        session["user_id"] = admin.id
    with app.test_request_context():
        from flask import url_for
        path = url_for("main.sales_readiness")
        selected = sales_readiness_completed_ids() | {"module_project_gantt"}
        assert "module_project_planning" in selected, "Project planning prerequisite is not marked complete"
    response = client.get(path, base_url=base)
    assert response.status_code == 200
    parser = CsrfParser()
    parser.feed(response.get_data(as_text=True))
    assert parser.token
    response = client.post(path, base_url=base, headers={"Referer": base + path},
        data={"csrf_token": parser.token, "completed_items": sorted(selected)})
    assert response.status_code == 302 and response.location.endswith(path), (
        response.status_code, response.location)
    db.session.expire_all()
    assert db.session.get(AppSetting, "sales_readiness:module_project_planning").value == "1"
    assert db.session.get(AppSetting, "sales_readiness:module_project_gantt").value == "1"
    for key, value in before.items():
        if key not in {"sales_readiness:module_project_planning", "sales_readiness:module_project_gantt"}:
            assert db.session.get(AppSetting, key).value == value, key
    return "module_project_gantt"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("configure", "smoke", "mark", "mark-gantt"))
    args = parser.parse_args()
    app = create_app()
    app.config.update(MAIL_ENABLED=False, NOTIFICATION_AUTO_REMINDERS_ENABLED=False)
    with app.app_context():
        if args.step == "configure":
            print("Project configuration changes:", len(configure_defaults()))
        elif args.step == "smoke":
            print("Project tenant/role smoke checks:", smoke(app))
        elif args.step == "mark":
            print("Checklist marked:", mark(app))
        else:
            print("Checklist marked:", mark_gantt(app))


if __name__ == "__main__":
    main()
