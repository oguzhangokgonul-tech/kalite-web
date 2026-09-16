"""Loopback-only responsive preview with disposable data, never the real DB."""
import argparse
import logging
import secrets
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import jsonify, redirect, request, session

from app import create_app
from app.extensions import db
from app.models import (CalibrationRecord, CompanyDepartment, InternalAudit,
                        InternalAuditQuestion, InternalAuditAnswer, PersonnelContact,
                        QualityTestRecord, Suggestion, SuggestionScoreParameter,
                        RiskRecord, SupplierRecord, TrainingRecord, DynamicFormAssignment,
                        DynamicFormAssignmentRecipient, InspectionRecord)
from app.seed import ensure_default_roles
from tests.helpers import create_company, create_user, make_document
from tests.test_action_management import make_action
from tests.test_dof_management import make_dof
from tests.test_role_navigation_smoke import _SidebarLinkParser
from tests.test_inspection_management import create_form_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5067)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="volkaportal-responsive-") as folder:
        class PreviewConfig:
            TESTING = True
            SECRET_KEY = "isolated-ui-preview-only"
            SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(Path(folder) / "preview.db")
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            UPLOAD_FOLDER = str(Path(folder) / "uploads")
            WTF_CSRF_ENABLED = True
            TENANT_BASE_DOMAIN = "volkaportal.com"
            PASSWORD_MIN_LENGTH = 4
            LOGIN_MAX_FAILED_ATTEMPTS = 5
            LOGIN_LOCKOUT_MINUTES = 10
            LOGIN_IP_MAX_FAILED_ATTEMPTS = 20
            MAIL_ENABLED = False
            AUTO_BOOTSTRAP_DATABASE = False
            TEMPLATES_AUTO_RELOAD = True
            APP_ENV = "testing"
            PREFERRED_URL_SCHEME = "http"
            PUBLIC_BASE_URL = f"http://127.0.0.1:{args.port}"
        app = create_app(PreviewConfig)
        with app.app_context():
            db.create_all()
            ensure_default_roles()
            company = create_company("ui-preview", name="Mobil Test Firması")
            company.primary_domain = f"firma-ui-preview.volkaportal.com:{args.port}"
            preview_password = secrets.token_urlsafe(24)
            db.session.add(CompanyDepartment(company_id=company.id, name="Kalite", sort_order=1))
            db.session.commit()
            roles = ["super_admin", "management_representative", "management",
                     "department_manager", "department_staff", "viewer"]
            users = {role: create_user("superadmin" if role == "super_admin" else f"preview-{role}",
                                      role_key=role, company=None if role == "super_admin" else company,
                                      full_name="Oğuzhan Gökgönül" if role == "super_admin" else role,
                                      permissions=("suggestions.evaluate",) if role == "management_representative" else
                                          (("actions.request_close_assigned", "actions.comment_assigned") if role == "department_staff" else ()),
                                      title="Kalite") for role in roles}
            owner = users["management_representative"]
            users["super_admin"].set_password(preview_password)
            db.session.commit()
            make_action(company, users["department_staff"], title="Uzun başlıklı üretim hattı iyileştirme aksiyonu")
            dof = make_dof(company, owner, title="FRM.13 Alt Yapı Teslim Alma Formu")
            document = make_document(app, company, uploader=owner, title="Kalite İç Tetkik Prosedürü",
                                     description="Üretim süreçleri için güncel kontrol dokümanı")
            for i in range(1, 4):
                db.session.add(PersonnelContact(company_id=company.id,
                    full_name=f"Şule Öztürk Gökgönül {i}", phone=f"0532 000 00 0{i}",
                    title="Üretim ve Kalite Kontrol Sorumlusu", email=f"personel{i}@example.com"))
                db.session.add(CalibrationRecord(company_id=company.id, device_code=f"CK0{i}",
                    device_name="METAL TEL ÖRGÜLÜ ELEK", manufacturer="KALİTE LTD",
                    brand_model="125 um", serial_no=f"SN-00{i}", certificate_no=f"0064K-1225-0022{i}",
                    calibration_date=date.today() - timedelta(days=180),
                    next_calibration_date=date.today() + timedelta(days=i * 10 - 20),
                    measurement_range="125 um", deviation_range="+/- 12,4 um"))
            concrete = QualityTestRecord(company_id=company.id, test_type="beton-deneyi",
                record_number=1, title="Bergama Plastik", project_number="PRJ-2026-001",
                record_date=date.today() - timedelta(days=14), sample_name="Kolon",
                concrete_class="C30", air_temperature=13, strength_2_day=17.4,
                strength_7_day=33, strength_28_day=45, created_by_user_id=owner.id)
            suggestion = Suggestion(company_id=company.id, owner_name=owner.full_name,
                created_by_user_id=owner.id, definition="Üretim süreçlerinde kalite kontrol iyileştirmesi",
                status="Değerlendirmede")
            db.session.add_all([concrete, suggestion])
            for i, name in enumerate(["Önerinin Kritikliği", "Maliyet/Malzeme Azaltımı", "Zaman Tasarrufu"]):
                db.session.add(SuggestionScoreParameter(company_id=company.id, name=name,
                               score=15, sort_order=i + 1, is_active=True))
            audit = InternalAudit(company_id=company.id, audit_no="ICD-2026-0001",
                title="Üretim ve Proje Denetimi", auditor_id=owner.id,
                audited_user_id=owner.id, evaluated_department="Kalite", planned_date=date.today())
            db.session.add(audit)
            db.session.flush()
            question = InternalAuditQuestion(company_id=company.id, audit_id=audit.id, order_no=1,
                standard="ISO 9001:2015", audit_topic="Doküman kontrolü",
                question_text="Güncel prosedürler üretim alanında erişilebilir mi?")
            db.session.add(question)
            db.session.flush()
            db.session.add(InternalAuditAnswer(company_id=company.id, audit_id=audit.id,
                question_id=question.id, standard=question.standard, audit_topic=question.audit_topic,
                question_text=question.question_text, result="Uygun", technical_findings="Kontrol edildi",
                answered_by_user_id=owner.id, is_draft=False))
            db.session.add_all([
                RiskRecord(company_id=company.id, risk_no="RSK-2026-0001",
                    title="Üretim hattında ölçüm ve kontrol riski", department="Kalite",
                    owner_user_id=owner.id, likelihood=4, severity=5, due_date=date.today()),
                SupplierRecord(company_id=company.id, supplier_no="TED-2026-0001",
                    name="Kalite Metal Ltd.", product_group="Çelik bağlantı elemanları",
                    contact_person="Ayşe Yılmaz", department="Kalite", phone="0232 000 00 00"),
                TrainingRecord(company_id=company.id, training_no="EGT-2026-0001",
                    title="ISO 9001 Doküman Kontrol Eğitimi", document_id=document.id,
                    instructor_user_id=owner.id, planned_date=date.today(), due_date=date.today()),
            ])
            db.session.commit()
            version = create_form_version(company, owner)
            assignment = DynamicFormAssignment(company_id=company.id, version_id=version.id,
                assigned_user_id=owner.id, due_date=date.today(), created_by_user_id=owner.id)
            inspection = InspectionRecord(company_id=company.id, version_id=version.id,
                inspection_no="MUA-2026-0001", title="Üretim Alanı Kontrolü",
                inspector_user_id=owner.id, reviewer_user_id=owner.id,
                department="Kalite", status="in_progress", planned_date=date.today(), due_date=date.today())
            db.session.add_all([assignment, inspection])
            db.session.flush()
            db.session.add(DynamicFormAssignmentRecipient(company_id=company.id,
                assignment_id=assignment.id, user_id=owner.id))
            db.session.commit()
            company_id = company.id
            user_ids = {role: user.id for role, user in users.items()}
            details = [f"/actions/1", f"/dofs/{dof.id}", f"/documents/{document.id}",
                       f"/oneri-sikayet/oneri/{suggestion.id}",
                       f"/kalite-deneyleri/beton-deneyi/{concrete.id}/olcum-duzenle"]
            details.extend([f"/ic-denetim/{audit.id}/soru/{question.id}",
                            f"/dinamik-formlar/atama/{assignment.id}/doldur",
                            f"/saha-kontrol/{inspection.id}",
                            f"/saha-kontrol/{inspection.id}/uygula"])
        # This auth shortcut exists only in this standalone disposable preview process.
        @app.get("/__ui/login/<role>")
        def preview_login(role):
            if role not in user_ids:
                return "Unknown preview role", 404
            session.clear()
            session.update(user_id=user_ids[role], company_id=company_id)
            if request.args.get("open") == "1":
                return redirect("/")
            return jsonify(ok=True)

        @app.get("/__ui/manifest")
        def manifest():
            client = app.test_client()
            with client.session_transaction() as test_session:
                test_session.update(user_id=user_ids["super_admin"], company_id=company_id)
            html = client.get("/").get_data(as_text=True)
            links = _SidebarLinkParser()
            links.feed(html)
            paths = set(links.links)
            for rule in app.url_map.iter_rules():
                if "GET" not in rule.methods or rule.arguments or rule.endpoint.startswith("static"):
                    continue
                if str(rule).endswith(("/yeni", "/new", "/olustur", "/upload")):
                    paths.add(str(rule))
            paths.update(details)
            paths.add("/documents/list")
            valid = sorted(path for path in paths if path.startswith("/") and client.get(path).status_code == 200)
            return jsonify(paths=valid, roles=list(user_ids), preview_password=preview_password)

        print(f"Disposable UI preview: http://127.0.0.1:{args.port}/__ui/login/super_admin", flush=True)
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        app.run(host="127.0.0.1", port=args.port, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
