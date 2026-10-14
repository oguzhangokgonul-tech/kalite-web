from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from functools import wraps
import hashlib
import hmac
from io import BytesIO
from pathlib import Path
import re
import secrets
import warnings
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from sqlalchemy import cast, inspect, or_, text
from sqlalchemy.exc import IntegrityError, OperationalError
from PIL import Image, ImageOps, UnidentifiedImageError

from .audit import record_audit_event
from .company_packages import get_package_module_keys
from .extensions import db
from .mail import send_recipient_email
from .models import (
    Action,
    AppSetting,
    Company,
    CompanyDepartment,
    CompanyModule,
    ComplaintFile,
    ComplaintMessage,
    ComplaintRecord,
    ComplaintStatusHistory,
    CUSTOMER_FEEDBACK_SOURCES,
    CUSTOMER_PORTAL_SOURCE,
    INTERNAL_FEEDBACK_SOURCE,
    CustomerPortalAttempt,
    CustomerPortalSetting,
    CustomerPortalToken,
    Dof,
    User,
)
from .notifications import add_notifications
from .request_security import request_client_ip
from .tenant import assign_current_company, scoped_query, tenant_url_for_company


bp = Blueprint("customer_portal", __name__)

MODULE_KEY = "customer_feedback_portal"
RECORD_TYPES = ("Şikayet", "Talep", "Öneri", "Bilgi İsteği", "Memnuniyet")
PRIORITIES = ("Düşük", "Orta", "Yüksek", "Kritik")
INTERNAL_STATUSES = (
    "Yeni",
    "Ön İncelemede",
    "Atandı",
    "İncelemede",
    "Müşteriden Bilgi Bekleniyor",
    "Aksiyon Açıldı",
    "IF/DÖF Açıldı",
    "Çözüm Bildirildi",
    "Kapatıldı",
    "Reddedildi",
)
PUBLIC_STATUS_BY_INTERNAL = {
    "E-posta Doğrulaması Bekleniyor": "Alındı",
    "Yeni": "Alındı",
    "Ön İncelemede": "İnceleniyor",
    "Atandı": "İnceleniyor",
    "İncelemede": "İnceleniyor",
    "Müşteriden Bilgi Bekleniyor": "Yanıtınız Bekleniyor",
    "Aksiyon Açıldı": "İnceleniyor",
    "IF/DÖF Açıldı": "İnceleniyor",
    "Çözüm Bildirildi": "Çözüldü",
    "Kapatıldı": "Kapatıldı",
    "Kapandı": "Kapatıldı",
    "Reddedildi": "Kapatıldı",
    "Arşiv": "Kapatıldı",
}
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DEFAULT_CONSENT = "Kişisel verilerimin talebimin yönetilmesi amacıyla işlenmesini kabul ediyorum."


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_customer_portal_schema():
    if current_app.extensions.get("customer_portal_schema_checked"):
        return
    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        if "complaint_records" in tables:
            columns = {column["name"] for column in inspector.get_columns("complaint_records")}
            definitions = {
                "contact_email": "VARCHAR(255)",
                "record_type": "VARCHAR(40) NOT NULL DEFAULT 'Şikayet'",
                "source": "VARCHAR(40) NOT NULL DEFAULT 'İç Kayıt'",
                "customer_reference": "VARCHAR(120)",
                "product_reference": "VARCHAR(180)",
                "public_status": "VARCHAR(40) NOT NULL DEFAULT 'Alındı'",
                "email_verified_at": "DATETIME",
                "first_response_due_at": "DATETIME",
                "resolution_due_at": "DATETIME",
                "first_response_at": "DATETIME",
                "resolved_at": "DATETIME",
                "customer_solution_summary": "TEXT",
                "customer_rating": "INTEGER",
                "customer_rating_comment": "TEXT",
                "consent_text": "TEXT",
                "consent_version": "VARCHAR(40)",
                "consented_at": "DATETIME",
                "last_customer_message_at": "DATETIME",
                "is_archived": "BOOLEAN NOT NULL DEFAULT 0",
                "archived_at": "DATETIME",
                "archived_by_user_id": "INTEGER",
            }
            with db.engine.begin() as connection:
                for name, definition in definitions.items():
                    if name not in columns:
                        connection.execute(text(f"ALTER TABLE complaint_records ADD COLUMN {name} {definition}"))

        for model in (
            CustomerPortalSetting,
            CustomerPortalToken,
            ComplaintMessage,
            ComplaintFile,
            ComplaintStatusHistory,
            CustomerPortalAttempt,
        ):
            model.__table__.create(bind=db.engine, checkfirst=True)

        file_columns = {column["name"] for column in inspect(db.engine).get_columns("complaint_files")}
        if "evidence_stage" not in file_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE complaint_files ADD COLUMN evidence_stage VARCHAR(20) NOT NULL DEFAULT 'general'"
                ))

        with db.engine.begin() as connection:
            if "company_modules" in set(inspect(db.engine).get_table_names()):
                company_rows = connection.execute(text("SELECT id, package_key FROM companies")).fetchall()
                for company_id, package_key in company_rows:
                    enabled = MODULE_KEY in get_package_module_keys(package_key)
                    connection.execute(
                        text(
                            "INSERT INTO company_modules (company_id, module_key, is_enabled) "
                            "SELECT :company_id, :module_key, :enabled WHERE NOT EXISTS ("
                            "SELECT 1 FROM company_modules WHERE company_id=:company_id AND module_key=:module_key)"
                        ),
                        {"company_id": company_id, "module_key": MODULE_KEY, "enabled": int(enabled)},
                    )
        current_app.extensions["customer_portal_schema_checked"] = True
    except OperationalError:
        db.session.rollback()
        current_app.logger.exception("Müşteri portalı şeması kontrol edilemedi.")


def _tenant_company():
    company = getattr(g, "tenant_company", None)
    if company is None or not company.is_active:
        abort(404)
    return company


def _module_enabled_for_company(company):
    row = CompanyModule.query.filter_by(company_id=company.id, module_key=MODULE_KEY).first()
    if row is not None:
        return bool(row.is_enabled)
    return MODULE_KEY in get_package_module_keys(company.package_key)


def _portal_setting(company, create=True):
    setting = CustomerPortalSetting.query.filter_by(company_id=company.id).first()
    if setting is None and create:
        setting = CustomerPortalSetting(company_id=company.id, consent_text=DEFAULT_CONSENT)
        db.session.add(setting)
        db.session.flush()
    return setting


def _public_company():
    company = _tenant_company()
    if not _module_enabled_for_company(company):
        abort(404)
    setting = _portal_setting(company)
    if not setting.is_enabled:
        abort(404)
    return company, setting


def _has_permission(key):
    user = getattr(g, "current_user", None)
    return bool(user and user.has_permission(key))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def _internal_company():
    company = getattr(g, "current_company", None)
    if company is None or not _module_enabled_for_company(company):
        abort(404)
    return company


def _user_matches_department(user, department):
    if not user or not department:
        return False
    values = {
        str(getattr(user, "title", "") or "").strip().casefold(),
        str(getattr(getattr(user, "personnel_contact", None), "department", "") or "").strip().casefold(),
        str(getattr(getattr(user, "personnel_contact", None), "title", "") or "").strip().casefold(),
    }
    department_key = department.strip().casefold()
    return any(
        department_key == value
        or re.match(rf"^{re.escape(department_key)}(?:\s|/|-|\(|$)", value)
        for value in values
        if value
    )


def _can_access(record, user=None):
    user = user if user is not None else getattr(g, "current_user", None)
    if not user or not user.is_active or not user.has_permission("customer_portal.view"):
        return False
    if user.company_id != record.company_id and not user.has_role("super_admin"):
        return False
    if (
        user.has_permission("customer_portal.assign")
        or user.has_role("management")
        or (
            user.has_permission("customer_portal.triage")
            and not user.has_role("department_manager")
        )
    ):
        return True
    if record.responsible_user_id == user.id or (
        record.is_internal_feedback and record.created_by_user_id == user.id
    ):
        return True
    return bool(user.has_role("department_manager") and _user_matches_department(user, record.department))


def _visible_query(include_archived=False):
    company = _internal_company()
    query = scoped_query(ComplaintRecord.query, ComplaintRecord).filter(
        ComplaintRecord.company_id == company.id,
        ComplaintRecord.source.in_(CUSTOMER_FEEDBACK_SOURCES),
    )
    if not include_archived:
        query = query.filter(ComplaintRecord.is_archived.is_(False))
    user = g.current_user
    ownership = or_(
        ComplaintRecord.responsible_user_id == user.id,
        (ComplaintRecord.source == INTERNAL_FEEDBACK_SOURCE) & (ComplaintRecord.created_by_user_id == user.id),
    )
    if (
        _has_permission("customer_portal.assign")
        or user.has_role("management")
        or (
            _has_permission("customer_portal.triage")
            and not user.has_role("department_manager")
        )
    ):
        return query
    if user.has_role("department_manager"):
        departments = [
            row.name for row in CompanyDepartment.query.filter_by(company_id=company.id, is_active=True).all()
            if _user_matches_department(user, row.name)
        ]
        return query.filter(or_(ownership, ComplaintRecord.department.in_(departments)))
    return query.filter(ownership)


def _record_or_404(record_id):
    record = scoped_query(ComplaintRecord.query, ComplaintRecord).filter(
        ComplaintRecord.id == record_id,
        ComplaintRecord.company_id == _internal_company().id,
        ComplaintRecord.source.in_(CUSTOMER_FEEDBACK_SOURCES),
    ).first_or_404()
    if not _can_access(record):
        abort(403)
    return record


def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _new_token(record, purpose, lifetime):
    raw_token = secrets.token_urlsafe(32)
    token = CustomerPortalToken(
        company_id=record.company_id,
        complaint_id=record.id,
        purpose=purpose,
        token_hash=_hash_token(raw_token),
        expires_at=_utcnow() + lifetime,
    )
    db.session.add(token)
    return raw_token, token


def _valid_token(raw_token, purpose):
    company, _setting = _public_company()
    token = CustomerPortalToken.query.filter_by(
        company_id=company.id,
        purpose=purpose,
        token_hash=_hash_token(raw_token),
    ).first()
    if (
        token is None
        or token.revoked_at is not None
        or token.expires_at < _utcnow()
        or (purpose == "verification" and token.used_at is not None)
    ):
        abort(404)
    if token.complaint.company_id != company.id or token.complaint.source != CUSTOMER_PORTAL_SOURCE:
        abort(404)
    return token


def _request_ip_hash():
    address = request_client_ip()
    secret = str(current_app.config.get("SECRET_KEY", "portal"))
    return hmac.new(secret.encode(), address.encode(), hashlib.sha256).hexdigest()


def _email_hash(email):
    return hashlib.sha256(str(email or "").strip().casefold().encode()).hexdigest()


def _check_rate_limit(company, setting, email=None, action="submit"):
    cutoff = _utcnow() - timedelta(hours=1)
    ip_hash = _request_ip_hash()
    email_hash = _email_hash(email) if email else None
    scope_filter = CustomerPortalAttempt.ip_hash == ip_hash
    if email_hash:
        scope_filter = or_(
            CustomerPortalAttempt.ip_hash == ip_hash,
            CustomerPortalAttempt.email_hash == email_hash,
        )
    count = CustomerPortalAttempt.query.filter(
        CustomerPortalAttempt.company_id == company.id,
        CustomerPortalAttempt.action == action,
        scope_filter,
        CustomerPortalAttempt.created_at >= cutoff,
    ).count()
    if count >= max(1, setting.submission_limit_hour):
        abort(429)
    attempt = CustomerPortalAttempt(
        company_id=company.id,
        action=action,
        ip_hash=ip_hash,
        email_hash=email_hash,
    )
    db.session.add(attempt)
    return attempt


def _next_record_no(company_id):
    prefix = f"MGB-{date.today().year}-"
    rows = ComplaintRecord.query.with_entities(ComplaintRecord.complaint_no).filter(
        ComplaintRecord.company_id == company_id,
        ComplaintRecord.complaint_no.like(f"{prefix}%"),
    ).all()
    numbers = []
    for (number,) in rows:
        try:
            numbers.append(int(str(number).removeprefix(prefix)))
        except ValueError:
            continue
    return f"{prefix}{(max(numbers) + 1 if numbers else 1):04d}"


def _status_history(record, source, note=None):
    db.session.add(
        ComplaintStatusHistory(
            company_id=record.company_id,
            complaint_id=record.id,
            internal_status=record.status,
            public_status=record.public_status,
            changed_by_user_id=getattr(getattr(g, "current_user", None), "id", None),
            source=source,
            note=(note or "")[:255] or None,
        )
    )


def _audit(record, action, details=None):
    record_audit_event(
        "CustomerFeedbackPortal",
        action,
        record.complaint_no,
        entity_id=record.id,
        company_id=record.company_id,
        details=details or {},
        commit=False,
    )


def _notify_internal(record, message, source_suffix, *, event_type):
    from .notification_policy import queue_notification_event
    from .reminder_sources import customer_portal_recipients

    users = customer_portal_recipients(record)
    notifications = add_notifications(
        users,
        message,
        company_id=record.company_id,
        notification_type="info",
        source_key=f"customer-portal:{record.id}:{source_suffix}",
        target_url=url_for("customer_portal.detail", record_id=record.id),
        due_date=record.due_date,
    )
    for notification in notifications:
        queue_notification_event(notification, "customer-portal", record.id, event_type)


def _extension(filename):
    return str(filename or "").rsplit(".", 1)[-1].lower() if "." in str(filename or "") else ""


def _clean_filename(filename):
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = "".join(char for char in name if char not in '<>:"/\\|?*' and ord(char) >= 32).strip(" .")
    return (name or "dosya")[:255]


def _file_signature_valid(upload, extension):
    stream = upload.stream
    position = stream.tell()
    head = stream.read(8)
    stream.seek(position)
    if extension == "pdf":
        return head.startswith(b"%PDF-")
    if extension in {"jpg", "jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    if extension == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {"docx", "xlsx"}:
        return head.startswith(b"PK\x03\x04")
    if extension in {"doc", "xls"}:
        return head.startswith(b"\xd0\xcf\x11\xe0")
    return False


def _folder_usage(path):
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def _image_mimetype(stream, extension):
    expected = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}.get(extension)
    if expected is None:
        raise ValueError("invalid_image")
    try:
        stream.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stream) as picture:
                if picture.format != expected:
                    raise ValueError("invalid_image")
                if picture.width * picture.height > 20_000_000:
                    raise ValueError("image_dimensions")
                picture.verify()
            stream.seek(0)
            with Image.open(stream) as picture:
                picture.load()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("invalid_image") from error
    finally:
        stream.seek(0)
    return "image/png" if expected == "PNG" else "image/jpeg"


@contextmanager
def _file_transaction():
    # Paths survive ORM rollback, including a failed flush or commit.
    paths = []
    try:
        yield paths
    except Exception:
        try:
            db.session.rollback()
        finally:
            for path in paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    current_app.logger.exception("Geri alınan müşteri portalı eki silinemedi.")
        raise


def _store_file(upload, record, message, visibility, by_customer, *, evidence_stage="general", stored_paths=None):
    if not upload or not upload.filename:
        return None
    extension = _extension(upload.filename)
    if extension not in ALLOWED_EXTENSIONS or not _file_signature_valid(upload, extension):
        raise ValueError("invalid_file")
    upload.stream.seek(0, 2)
    size = upload.stream.tell()
    upload.stream.seek(0)
    setting = _portal_setting(db.session.get(Company, record.company_id))
    if size <= 0 or size > max(1, setting.max_file_mb) * 1024 * 1024:
        raise ValueError("file_size")
    if evidence_stage not in {"general", "before", "after"}:
        raise ValueError("invalid_stage")
    mime_type = upload.mimetype
    if evidence_stage != "general":
        if by_customer or visibility != "internal":
            raise ValueError("invalid_stage")
        mime_type = _image_mimetype(upload.stream, extension)
        # Normalize orientation and omit camera metadata and trailing payloads.
        with Image.open(upload.stream) as picture:
            normalized = ImageOps.exif_transpose(picture).convert("RGB")
            clean = BytesIO()
            normalized.save(clean, format="PNG" if extension == "png" else "JPEG")
            normalized.close()
        clean.seek(0)
        upload.stream = clean
        size = clean.getbuffer().nbytes
        if size > max(1, setting.max_file_mb) * 1024 * 1024:
            raise ValueError("file_size")
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    company_root = (root / f"company-{record.company_id:03d}").resolve()
    company_root.mkdir(parents=True, exist_ok=True)
    company = db.session.get(Company, record.company_id)
    if company.storage_quota_mb and _folder_usage(company_root) + size > company.storage_quota_mb * 1024 * 1024:
        raise ValueError("storage_quota")
    relative = Path(f"company-{record.company_id:03d}") / "customer-feedback" / str(record.id) / f"{uuid4().hex}.{extension}"
    absolute = (root / relative).resolve()
    try:
        company_root.relative_to(root)
        absolute.relative_to(company_root)
    except ValueError:
        raise ValueError("invalid_file") from None
    absolute.parent.mkdir(parents=True, exist_ok=True)
    if stored_paths is not None:
        stored_paths.append(absolute)
    try:
        upload.save(absolute)
        digest = hashlib.sha256(absolute.read_bytes()).hexdigest()
    except Exception:
        absolute.unlink(missing_ok=True)
        raise
    row = ComplaintFile(
        company_id=record.company_id,
        complaint_id=record.id,
        message_id=message.id if message and message.id else None,
        visibility=visibility,
        evidence_stage=evidence_stage,
        original_name=_clean_filename(upload.filename),
        stored_path=relative.as_posix(),
        mime_type=mime_type,
        file_size=size,
        sha256_hash=digest,
        uploaded_by_user_id=None if by_customer else g.current_user.id,
        uploaded_by_customer=by_customer,
    )
    db.session.add(row)
    return row


def _store_evidence(record, stored_paths):
    count = sum(bool(upload.filename) for stage in ("before", "after")
                for upload in request.files.getlist(f"{stage}_images"))
    if count > 12:
        raise ValueError("too_many_images")
    rows = []
    for stage in ("before", "after"):
        for upload in request.files.getlist(f"{stage}_images"):
            row = _store_file(
                upload, record, None, "internal", False,
                evidence_stage=stage, stored_paths=stored_paths,
            )
            if row is not None:
                rows.append(row)
    return rows


def _send_verification(record, raw_token):
    company = db.session.get(Company, record.company_id)
    url = tenant_url_for_company(company, url_for("customer_portal.verify", raw_token=raw_token))
    body = (
        f"Merhaba {record.contact_name or record.customer_name},\n\n"
        f"{record.complaint_no} numaralı geri bildiriminizi doğrulamak için bağlantıyı açın:\n{url}\n\n"
        "Bu bağlantı süre dolduğunda geçersiz olur."
    )
    send_recipient_email(record.contact_email, f"{record.complaint_no} e-posta doğrulaması", body)
    return url


def _send_tracking(record, raw_token, subject, lead):
    if record.source != CUSTOMER_PORTAL_SOURCE:
        return None
    company = db.session.get(Company, record.company_id)
    url = tenant_url_for_company(company, url_for("customer_portal.track", raw_token=raw_token))
    send_recipient_email(
        record.contact_email,
        subject,
        f"Merhaba {record.contact_name or record.customer_name},\n\n{lead}\n\nTakip bağlantınız:\n{url}",
    )
    return url


@bp.before_request
def prepare_schema():
    ensure_customer_portal_schema()


@bp.route("/musteri-portali", methods=["GET", "POST"])
def public_form():
    company, setting = _public_company()
    verification_url = None
    if request.method == "POST":
        if request.form.get("website", "").strip():
            abort(400)
        email = request.form.get("contact_email", "").strip().lower()
        attempt = _check_rate_limit(company, setting, email=email)
        values = {
            "record_type": request.form.get("record_type", "").strip(),
            "customer_name": request.form.get("customer_name", "").strip(),
            "contact_name": request.form.get("contact_name", "").strip(),
            "contact_email": email,
            "contact_phone": request.form.get("contact_phone", "").strip(),
            "subject": request.form.get("subject", "").strip(),
            "description": request.form.get("description", "").strip(),
            "customer_reference": request.form.get("customer_reference", "").strip(),
            "product_reference": request.form.get("product_reference", "").strip(),
        }
        if (
            values["record_type"] not in RECORD_TYPES
            or not values["customer_name"]
            or not values["contact_name"]
            or not EMAIL_RE.match(email)
            or not values["contact_phone"]
            or not values["customer_reference"]
            or not values["product_reference"]
            or not values["subject"]
            or not values["description"]
            or request.form.get("consent") != "on"
        ):
            db.session.commit()
            flash("Zorunlu alanları ve veri işleme onayını kontrol edin.", "danger")
        else:
            now = _utcnow()
            record = ComplaintRecord(
                company_id=company.id,
                complaint_no=_next_record_no(company.id),
                record_type=values["record_type"],
                source="Müşteri Portalı",
                customer_name=values["customer_name"][:180],
                contact_name=values["contact_name"][:160],
                contact_email=email[:255],
                contact_phone=values["contact_phone"][:80] or None,
                subject=values["subject"][:180],
                description=values["description"][:5000],
                customer_reference=values["customer_reference"][:120] or None,
                product_reference=values["product_reference"][:180] or None,
                received_date=date.today(),
                status="E-posta Doğrulaması Bekleniyor",
                public_status="Alındı",
                priority="Orta",
                consent_text=setting.consent_text,
                consent_version=setting.consent_version,
                consented_at=now,
            )
            db.session.add(record)
            try:
                with _file_transaction() as paths:
                    db.session.flush()
                    message = ComplaintMessage(
                        company_id=company.id,
                        complaint_id=record.id,
                        sender_type="customer",
                        sender_name=record.contact_name,
                        body=record.description,
                        visibility="public",
                    )
                    db.session.add(message)
                    db.session.flush()
                    _store_file(
                        request.files.get("attachment"), record, message, "public", True,
                        stored_paths=paths,
                    )
                    raw_token, _token = _new_token(record, "verification", timedelta(hours=max(1, setting.verification_hours)))
                    attempt.success = True
                    _status_history(record, "public", "E-posta doğrulaması bekleniyor")
                    _audit(record, "submitted", {"record_type": record.record_type, "source": record.source})
                    db.session.commit()
            except (ValueError, IntegrityError) as error:
                db.session.rollback()
                flash(
                    "Ek dosya türü, boyutu veya depolama kotasını kontrol edin."
                    if isinstance(error, ValueError)
                    else "Kayıt numarası oluşturulamadı; lütfen tekrar deneyin.",
                    "danger",
                )
            else:
                verification_url = _send_verification(record, raw_token)
                flash("Kaydınız alındı. E-posta adresinize gönderilen bağlantıyla doğrulayın.", "success")
                if not current_app.testing:
                    return redirect(url_for("customer_portal.public_form"))
    return render_template(
        "customer_portal/public_form.html",
        company=company,
        setting=setting,
        record_types=RECORD_TYPES,
        verification_url=verification_url,
    )


@bp.get("/musteri-portali/dogrula/<raw_token>")
def verify(raw_token):
    token = _valid_token(raw_token, "verification")
    record = token.complaint
    setting = _portal_setting(db.session.get(Company, record.company_id))
    now = _utcnow()
    token.used_at = now
    record.email_verified_at = now
    record.status = "Yeni"
    record.public_status = "Alındı"
    record.first_response_due_at = now + timedelta(hours=max(1, setting.first_response_hours))
    record.resolution_due_at = now + timedelta(hours=max(1, setting.resolution_hours))
    record.due_date = record.resolution_due_at.date()
    tracking_raw, _tracking_token = _new_token(record, "tracking", timedelta(days=max(1, setting.tracking_days)))
    _status_history(record, "customer", "E-posta doğrulandı")
    _audit(record, "verified", {"verification": "completed"})
    _notify_internal(record, f"{record.complaint_no} numaralı yeni müşteri geri bildirimi ön inceleme bekliyor.", "verified", event_type="approval")
    db.session.commit()
    _send_tracking(record, tracking_raw, f"{record.complaint_no} takip bağlantısı", "Geri bildiriminiz doğrulandı ve incelemeye alındı.")
    return redirect(url_for("customer_portal.track", raw_token=tracking_raw))


@bp.route("/musteri-portali/takip/<raw_token>", methods=["GET", "POST"])
def track(raw_token):
    token = _valid_token(raw_token, "tracking")
    record = token.complaint
    setting = _portal_setting(db.session.get(Company, record.company_id))
    if request.method == "POST":
        if record.is_closed:
            flash("Kapanmış kayda yeni mesaj eklenemez.", "warning")
            return redirect(url_for("customer_portal.track", raw_token=raw_token))
        attempt = _check_rate_limit(
            db.session.get(Company, record.company_id),
            setting,
            email=record.contact_email,
            action="message",
        )
        body = request.form.get("message", "").strip()
        if not body or len(body) > 3000:
            flash("Mesaj alanı zorunludur ve en fazla 3000 karakter olabilir.", "danger")
        else:
            message = ComplaintMessage(
                company_id=record.company_id,
                complaint_id=record.id,
                sender_type="customer",
                sender_name=record.contact_name,
                body=body,
                visibility="public",
            )
            db.session.add(message)
            try:
                with _file_transaction() as paths:
                    db.session.flush()
                    _store_file(request.files.get("attachment"), record, message, "public", True, stored_paths=paths)
                    record.last_customer_message_at = _utcnow()
                    if record.status != "Yeni":
                        record.status = "İncelemede"
                        record.public_status = "İnceleniyor"
                        _status_history(record, "customer", "Müşteri yanıt verdi")
                    attempt.success = True
                    _audit(record, "customer_message", {"attachment": bool(request.files.get("attachment"))})
                    _notify_internal(record, f"{record.complaint_no} kaydına müşteri yanıt verdi.", f"customer-message:{message.id}", event_type="rescheduled")
                    db.session.commit()
                flash("Mesajınız kaydedildi.", "success")
                return redirect(url_for("customer_portal.track", raw_token=raw_token))
            except ValueError:
                db.session.rollback()
                flash("Ek dosya türü, boyutu veya depolama kotasını kontrol edin.", "danger")
    messages = ComplaintMessage.query.filter_by(
        company_id=record.company_id, complaint_id=record.id, visibility="public"
    ).order_by(ComplaintMessage.created_at.asc()).all()
    files = ComplaintFile.query.filter_by(
        company_id=record.company_id, complaint_id=record.id, visibility="public", is_active=True
    ).order_by(ComplaintFile.created_at.asc()).all()
    return render_template(
        "customer_portal/track.html",
        record=record,
        messages=messages,
        files=files,
        raw_token=raw_token,
    )


@bp.post("/musteri-portali/takip/<raw_token>/memnuniyet")
def rate(raw_token):
    token = _valid_token(raw_token, "tracking")
    record = token.complaint
    if not record.is_closed or record.customer_rating is not None:
        abort(400)
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()
    if rating not in range(1, 6):
        flash("1 ile 5 arasında bir memnuniyet puanı seçin.", "danger")
    else:
        record.customer_rating = rating
        record.customer_rating_comment = comment[:1000] or None
        _audit(record, "rated", {"rating": rating})
        db.session.commit()
        flash("Değerlendirmeniz için teşekkür ederiz.", "success")
    return redirect(url_for("customer_portal.track", raw_token=raw_token))


def _safe_file_path(row):
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    record_root = (root / f"company-{row.company_id:03d}" / "customer-feedback" / str(row.complaint_id)).resolve()
    candidate = (root / row.stored_path).resolve()
    try:
        record_root.relative_to(root)
        candidate.relative_to(record_root)
    except ValueError:
        abort(404)
    if not candidate.is_file():
        abort(404)
    return candidate


def _private_file_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


def _delete_stored_file(row):
    if row is None:
        return
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    candidate = (root / row.stored_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        current_app.logger.exception("Geri alınan müşteri portalı eki silinemedi.")


@bp.get("/musteri-portali/takip/<raw_token>/dosya/<int:file_id>")
def public_file(raw_token, file_id):
    token = _valid_token(raw_token, "tracking")
    row = ComplaintFile.query.filter_by(
        id=file_id,
        company_id=token.company_id,
        complaint_id=token.complaint_id,
        visibility="public",
        is_active=True,
    ).first_or_404()
    path = _safe_file_path(row)
    _audit(token.complaint, "public_file_download", {"file_id": row.id})
    db.session.commit()
    return _private_file_response(send_from_directory(path.parent, path.name, as_attachment=True, download_name=row.original_name))


@bp.route("/musteri-geri-bildirimleri/yeni", methods=["GET", "POST"])
@login_required
def new_record():
    if not (_has_permission("customer_portal.create") and _has_permission("customer_portal.view")):
        abort(403)
    company = _internal_company()
    users = scoped_query(User.query, User).filter_by(is_active=True).order_by(User.full_name).all()
    users = [user for user in users if user.has_permission("customer_portal.view")]
    departments = scoped_query(CompanyDepartment.query, CompanyDepartment).filter_by(is_active=True).order_by(
        CompanyDepartment.sort_order, CompanyDepartment.name,
    ).all()
    errors = []
    if request.method == "POST":
        try:
            values = {
                key: request.form.get(key, "").strip()
                for key in ("customer_name", "customer_reference", "subject", "description", "department", "corrective_action")
            }
            limits = {"customer_name": 180, "customer_reference": 120, "subject": 180,
                      "description": 5000, "department": 80, "corrective_action": 5000}
            if any(len(values[key]) > limit for key, limit in limits.items()) or any(
                not values[key] for key in ("customer_name", "subject", "description")
            ):
                raise ValueError("required_fields")
            received = date.fromisoformat(request.form.get("received_date", "").strip())
            due_value = request.form.get("due_date", "").strip()
            due = date.fromisoformat(due_value) if due_value else None
            if received > date.today() or (due and due < received):
                raise ValueError("invalid_dates")
            responsible_value = request.form.get("responsible_user_id", "").strip()
            responsible_id = int(responsible_value) if responsible_value else None
            if responsible_id is not None and responsible_id not in {user.id for user in users}:
                raise ValueError("invalid_responsible")
            if responsible_id not in {None, g.current_user.id} and not _has_permission("customer_portal.assign"):
                abort(403)
            if values["department"] and values["department"] not in {row.name for row in departments}:
                raise ValueError("invalid_department")
            if values["department"] and not _has_permission("customer_portal.assign"):
                abort(403)
            record_type = request.form.get("record_type", "Şikayet").strip()
            priority = request.form.get("priority", "Orta").strip()
            if record_type not in RECORD_TYPES or priority not in PRIORITIES:
                raise ValueError("invalid_options")
            with _file_transaction() as paths:
                record = assign_current_company(ComplaintRecord(
                    complaint_no=_next_record_no(company.id), source=INTERNAL_FEEDBACK_SOURCE,
                    record_type=record_type, priority=priority,
                    customer_name=values["customer_name"], customer_reference=values["customer_reference"] or None,
                    subject=values["subject"], description=values["description"],
                    department=values["department"] or None, corrective_action=values["corrective_action"] or None,
                    received_date=received, due_date=due,
                    resolution_due_at=datetime.combine(due, time.max) if due else None,
                    responsible_user_id=responsible_id, created_by_user_id=g.current_user.id,
                    status="Atandı" if responsible_id else "Yeni", public_status="Alındı",
                ))
                db.session.add(record)
                db.session.flush()
                files = _store_evidence(record, paths)
                _status_history(record, "internal", "Personel tarafından oluşturuldu")
                _audit(record, "created", {"source": record.source, "evidence_count": len(files)})
                _notify_internal(record, f"{record.complaint_no} numaralı müşteri geri bildirimi oluşturuldu.", "created", event_type="approval")
                db.session.commit()
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            errors.append("Alanları, tarihleri ve PNG/JPEG dosyalarının tür, boyut ve kotasını kontrol edin."
                          if isinstance(error, ValueError) else "Kayıt oluşturulamadı; lütfen tekrar deneyin.")
            flash(errors[-1], "danger")
        else:
            flash("Müşteri geri bildirimi kaydedildi.", "success")
            return redirect(url_for("customer_portal.detail", record_id=record.id))
    return render_template(
        "customer_portal/form.html", users=users, departments=departments,
        record_types=RECORD_TYPES, priorities=PRIORITIES, today=date.today(), errors=errors,
        form_data=request.form if request.method == "POST" else {},
        can_assign=_has_permission("customer_portal.assign"),
    ), (400 if errors else 200)


@bp.get("/musteri-geri-bildirimleri")
@login_required
def dashboard():
    if not _has_permission("customer_portal.view"):
        abort(403)
    show_archived = request.args.get("archived") == "1"
    query = _visible_query(include_archived=show_archived).filter(
        or_(ComplaintRecord.source == INTERNAL_FEEDBACK_SOURCE, ComplaintRecord.email_verified_at.isnot(None))
    )
    if show_archived:
        query = query.filter(ComplaintRecord.is_archived.is_(True))
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()
    if search:
        value = f"%{search}%"
        query = query.filter(or_(ComplaintRecord.complaint_no.ilike(value), ComplaintRecord.customer_name.ilike(value), ComplaintRecord.subject.ilike(value), ComplaintRecord.customer_reference.ilike(value)))
    if status:
        query = query.filter(ComplaintRecord.status == status)
    records = query.all()
    records.sort(key=lambda row: (row.is_closed, row.due_date is None, row.due_date or date.max, -row.id))
    now = _utcnow()
    return render_template(
        "customer_portal/dashboard.html",
        records=records,
        statuses=INTERNAL_STATUSES + (("Arşiv", "Silindi") if show_archived else ()),
        search=search,
        selected_status=status,
        show_archived=show_archived,
        now=now,
        can_export=_has_permission("customer_portal.export"),
        can_settings=_has_permission("customer_portal.settings"),
        can_create=_has_permission("customer_portal.create"),
        can_delete=_has_permission("customer_portal.archive"),
    )


@bp.get("/musteri-geri-bildirimleri/<int:record_id>")
@login_required
def detail(record_id):
    if not _has_permission("customer_portal.view"):
        abort(403)
    record = _record_or_404(record_id)
    company = _internal_company()
    users = User.query.filter_by(company_id=company.id, is_active=True).order_by(User.full_name).all()
    users = [user for user in users if user.has_permission("customer_portal.view")]
    departments = CompanyDepartment.query.filter_by(company_id=company.id, is_active=True).order_by(CompanyDepartment.sort_order, CompanyDepartment.name).all()
    actions = Action.query.filter_by(company_id=company.id).order_by(Action.id.desc()).all() if _has_permission("customer_portal.assign") else ([record.action] if record.action else [])
    dofs = Dof.query.filter_by(company_id=company.id).order_by(Dof.id.desc()).all() if _has_permission("customer_portal.assign") else ([record.dof] if record.dof else [])
    can_add_evidence = not record.is_archived and (
        any(_has_permission(key) for key in (
            "customer_portal.respond", "customer_portal.triage", "customer_portal.assign",
        )) or (record.is_internal_feedback and record.created_by_user_id == g.current_user.id
               and _has_permission("customer_portal.create"))
    )
    return render_template(
        "customer_portal/detail.html",
        record=record,
        messages=ComplaintMessage.query.filter_by(company_id=company.id, complaint_id=record.id).order_by(ComplaintMessage.created_at).all(),
        files=ComplaintFile.query.filter_by(company_id=company.id, complaint_id=record.id, is_active=True).order_by(ComplaintFile.created_at).all(),
        users=users,
        departments=departments,
        actions=actions,
        dofs=dofs,
        statuses=INTERNAL_STATUSES,
        priorities=PRIORITIES,
        can_triage=_has_permission("customer_portal.triage"),
        can_assign=_has_permission("customer_portal.assign"),
        can_respond=_has_permission("customer_portal.respond"),
        can_close=_has_permission("customer_portal.close"),
        can_archive=_has_permission("customer_portal.archive"),
        can_download=_has_permission("customer_portal.file_download"),
        is_internal=record.is_internal_feedback,
        can_add_evidence=can_add_evidence,
        can_update=(
            _has_permission("customer_portal.triage")
            or _has_permission("customer_portal.assign")
            or _has_permission("customer_portal.close")
            or _has_permission("customer_portal.respond")
        ),
    )


@bp.post("/musteri-geri-bildirimleri/<int:record_id>/guncelle")
@login_required
def update(record_id):
    can_triage = _has_permission("customer_portal.triage")
    can_assign = _has_permission("customer_portal.assign")
    can_close = _has_permission("customer_portal.close")
    can_respond = _has_permission("customer_portal.respond")
    if not (can_triage or can_assign or can_close or can_respond):
        abort(403)
    record = _record_or_404(record_id)
    if record.is_archived:
        abort(400)
    if not (can_triage or can_assign or can_close):
        protected_values = {
            "status": record.status, "priority": record.priority,
            "department": record.department or "", "responsible_user_id": str(record.responsible_user_id or ""),
            "action_id": str(record.action_id or ""), "dof_id": str(record.dof_id or ""),
            "customer_solution_summary": record.customer_solution_summary or "",
            "due_date": record.due_date.isoformat() if record.due_date else "",
            "first_response_due_at": record.first_response_due_at.isoformat(timespec="minutes") if record.first_response_due_at else "",
            "resolution_due_at": record.resolution_due_at.isoformat(timespec="minutes") if record.resolution_due_at else "",
        }
        if any(key in request.form and request.form[key].strip() != value for key, value in protected_values.items()):
            abort(403)
        work_summary = request.form.get("corrective_action", record.corrective_action or "").strip()
        if len(work_summary) > 5000:
            abort(400)
        record.corrective_action = work_summary or None
        _audit(record, "work_summary_updated")
        db.session.commit()
        flash("Çalışma özeti kaydedildi.", "success")
        return redirect(url_for("customer_portal.detail", record_id=record.id))
    old_status = record.status
    old_responsible_id = record.responsible_user_id
    old_due_date = record.due_date
    status = request.form.get("status", record.status).strip()
    priority = request.form.get("priority", record.priority).strip()
    department = request.form.get("department", record.department or "").strip()
    try:
        responsible_value = request.form.get("responsible_user_id", str(record.responsible_user_id or "")).strip()
        responsible_id = int(responsible_value) if responsible_value else None
    except ValueError:
        abort(400)
    if status not in INTERNAL_STATUSES or priority not in PRIORITIES:
        abort(400)
    if not can_triage and status != old_status and not (can_close and status in {"Kapatıldı", "Reddedildi"}):
        abort(403)
    if not can_triage:
        priority = record.priority
    company = _internal_company()
    valid_departments = {row.name for row in CompanyDepartment.query.filter_by(company_id=company.id, is_active=True).all()}
    if department and department not in valid_departments:
        abort(400)
    responsible = User.query.filter_by(id=responsible_id, company_id=company.id, is_active=True).first() if responsible_id else None
    if responsible_id and (responsible is None or not responsible.has_permission("customer_portal.view")):
        abort(400)
    if status != old_status and status in {"Kapatıldı", "Reddedildi"} and not can_close:
        abort(403)
    try:
        action_value = request.form.get("action_id", str(record.action_id or "")).strip()
        dof_value = request.form.get("dof_id", str(record.dof_id or "")).strip()
        action_id = int(action_value) if action_value else None
        dof_id = int(dof_value) if dof_value else None
    except ValueError:
        abort(400)
    action = Action.query.filter_by(id=action_id, company_id=company.id).first() if action_id else None
    dof = Dof.query.filter_by(id=dof_id, company_id=company.id).first() if dof_id else None
    if (action_id and action is None) or (dof_id and dof is None):
        abort(400)
    effective_action = action if can_assign else record.action
    effective_dof = dof if can_assign else record.dof
    work_summary = request.form.get("corrective_action", record.corrective_action or "").strip()
    if len(work_summary) > 5000:
        abort(400)
    first_due = record.first_response_due_at
    resolution_due = record.resolution_due_at
    due_date = record.due_date
    try:
        if can_triage:
            first_value = request.form.get("first_response_due_at", "").strip()
            resolution_value = request.form.get("resolution_due_at", "").strip()
            first_due = datetime.fromisoformat(first_value) if first_value else first_due
            resolution_due = datetime.fromisoformat(resolution_value) if resolution_value else resolution_due
            if any(value is not None and value.tzinfo is not None for value in (first_due, resolution_due)):
                raise ValueError("invalid_timezone")
        if "due_date" in request.form and (can_triage or can_assign):
            due_value = request.form.get("due_date", "").strip()
            due_date = date.fromisoformat(due_value) if due_value else None
            resolution_due = datetime.combine(due_date, time.max) if due_date else None
        elif resolution_due:
            due_date = resolution_due.date()
        if due_date and record.received_date and due_date < record.received_date:
            raise ValueError("invalid_dates")
    except ValueError:
        abort(400)
    solution = request.form.get("customer_solution_summary", record.customer_solution_summary or "").strip()
    if len(solution) > 5000:
        abort(400)
    is_resolution_status = status in {"Çözüm Bildirildi", "Kapatıldı", "Reddedildi"}
    if is_resolution_status:
        if effective_action and not effective_action.is_completed:
            flash("Bağlı aksiyon tamamlanmadan kayıt kapatılamaz.", "danger")
            return redirect(url_for("customer_portal.detail", record_id=record.id))
        if effective_dof and effective_dof.status != "Tamamlandı":
            flash("Bağlı IF/DÖF tamamlanmadan kayıt kapatılamaz.", "danger")
            return redirect(url_for("customer_portal.detail", record_id=record.id))
        if not solution:
            flash("Çözüm veya kapanış sonucu zorunludur." if record.is_internal_feedback else
                  "Çözüm veya kapanış için müşteriye gösterilecek özet zorunludur.", "danger")
            return redirect(url_for("customer_portal.detail", record_id=record.id))
        record.resolved_at = record.resolved_at or _utcnow()
        if status in {"Kapatıldı", "Reddedildi"}:
            record.closed_at = record.closed_at or _utcnow()
    record.status = status
    record.public_status = PUBLIC_STATUS_BY_INTERNAL[status]
    record.priority = priority
    record.corrective_action = work_summary or None
    record.customer_solution_summary = solution or None
    if can_assign:
        record.department = department or None
        record.responsible_user_id = responsible.id if responsible else None
        record.action_id = action.id if action else None
        record.dof_id = dof.id if dof else None
    record.first_response_due_at = first_due
    record.resolution_due_at = resolution_due
    record.due_date = due_date
    if status not in {"Kapatıldı", "Reddedildi"}:
        record.closed_at = None
        if status != "Çözüm Bildirildi":
            record.resolved_at = None
    if old_status != record.status:
        _status_history(record, "internal", "İç süreç durumu güncellendi")
    _audit(record, "triaged", {"status": record.status, "priority": record.priority, "department": record.department})
    if record.is_internal_feedback and not record.is_closed and (
        old_responsible_id != record.responsible_user_id or old_due_date != record.due_date
    ):
        _notify_internal(record, f"{record.complaint_no} kaydının sorumlusu veya termini güncellendi.",
                         f"updated:{uuid4().hex}", event_type="rescheduled")
    db.session.commit()
    became_resolved = (
        status in {"Çözüm Bildirildi", "Kapatıldı", "Reddedildi"}
        and old_status != status
    )
    if became_resolved and record.source == CUSTOMER_PORTAL_SOURCE:
        raw, _ = _new_token(record, "tracking", timedelta(days=max(1, _portal_setting(company).tracking_days)))
        db.session.commit()
        _send_tracking(
            record,
            raw,
            f"{record.complaint_no} güncellendi",
            record.customer_solution_summary,
        )
    flash("Geri bildirim kaydı güncellendi.", "success")
    return redirect(url_for("customer_portal.detail", record_id=record.id))


@bp.post("/musteri-geri-bildirimleri/<int:record_id>/mesaj")
@login_required
def add_message(record_id):
    if not _has_permission("customer_portal.respond"):
        abort(403)
    record = _record_or_404(record_id)
    if record.is_archived:
        abort(400)
    body = request.form.get("message", "").strip()
    visibility = request.form.get("visibility", "public")
    if not body or len(body) > 3000 or visibility not in {"public", "internal"}:
        abort(400)
    if record.is_internal_feedback:
        visibility = "internal"
    message = ComplaintMessage(
        company_id=record.company_id,
        complaint_id=record.id,
        sender_type="user",
        sender_user_id=g.current_user.id,
        sender_name=g.current_user.full_name,
        body=body,
        visibility=visibility,
    )
    db.session.add(message)
    try:
        with _file_transaction() as paths:
            db.session.flush()
            _store_file(request.files.get("attachment"), record, message, visibility, False, stored_paths=paths)
            if visibility == "public":
                now = _utcnow()
                record.first_response_at = record.first_response_at or now
                record.public_status = "İnceleniyor" if not record.is_closed else record.public_status
                _audit(record, "public_response", {"attachment": bool(request.files.get("attachment"))})
            else:
                _audit(record, "internal_note", {"attachment": bool(request.files.get("attachment"))})
            db.session.commit()
    except ValueError:
        db.session.rollback()
        flash("Ek dosya türü, boyutu veya depolama kotasını kontrol edin.", "danger")
        return redirect(url_for("customer_portal.detail", record_id=record.id))
    if visibility == "public":
        setting = _portal_setting(_internal_company())
        raw, _ = _new_token(record, "tracking", timedelta(days=max(1, setting.tracking_days)))
        db.session.commit()
        _send_tracking(record, raw, f"{record.complaint_no} kaydınıza yanıt geldi", body)
    flash("Mesaj kaydedildi.", "success")
    return redirect(url_for("customer_portal.detail", record_id=record.id))


@bp.post("/musteri-geri-bildirimleri/<int:record_id>/arsivle")
@login_required
def archive(record_id):
    if not _has_permission("customer_portal.archive"):
        abort(403)
    record = _record_or_404(record_id)
    if record.is_archived:
        abort(409, description="Kayıt zaten arşivlenmiş veya silinmiş.")
    if not record.is_closed:
        flash("Yalnızca kapatılmış kayıtlar arşivlenebilir.", "danger")
        return redirect(url_for("customer_portal.detail", record_id=record.id))
    record.is_archived = True
    record.archived_at = _utcnow()
    record.archived_by_user_id = g.current_user.id
    record.status = "Arşiv"
    record.public_status = "Kapatıldı"
    CustomerPortalToken.query.filter_by(complaint_id=record.id).update(
        {"revoked_at": _utcnow()}
    )
    _status_history(record, "internal", "Arşive alındı")
    _audit(record, "archived")
    db.session.commit()
    flash("Kayıt denetim izi korunarak arşivlendi.", "success")
    return redirect(url_for("customer_portal.dashboard"))


@bp.route("/musteri-geri-bildirimleri/<int:record_id>/sil", methods=["GET", "POST"])
@login_required
def delete(record_id):
    if not _has_permission("customer_portal.archive"):
        abort(403)
    record = _record_or_404(record_id)
    if record.is_archived:
        abort(409, description="Kayıt zaten arşivlenmiş veya silinmiş.")
    error = None
    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if request.form.get("confirm_delete") != "yes" or not reason or len(reason) > 250:
            error = "Silme gerekçesini yazın ve onay kutusunu işaretleyin."
        elif request.form.get("updated_at") != record.updated_at.isoformat():
            abort(409, description="Kayıt değişti. Sayfayı yenileyip tekrar kontrol edin.")
        else:
            previous_status = record.status
            now = _utcnow()
            try:
                unchanged = ComplaintRecord.updated_at == record.updated_at
                # SQLite server defaults omit fractions; ORM datetime binds include them.
                if db.engine.dialect.name == "sqlite" and not record.updated_at.microsecond:
                    unchanged = or_(unchanged, cast(ComplaintRecord.updated_at, db.String) ==
                                    record.updated_at.strftime("%Y-%m-%d %H:%M:%S"))
                changed = ComplaintRecord.query.filter_by(
                    id=record.id, company_id=record.company_id, is_archived=False,
                ).filter(unchanged).update({
                    "is_archived": True, "archived_at": now,
                    "archived_by_user_id": g.current_user.id, "status": "Silindi",
                    "updated_at": now,
                }, synchronize_session=False)
                if changed != 1:
                    abort(409, description="Kayıt değişti. Sayfayı yenileyin.")
                db.session.refresh(record)
                CustomerPortalToken.query.filter_by(
                    company_id=record.company_id, complaint_id=record.id,
                ).update({"revoked_at": now})
                _status_history(record, "internal", f"Silindi: {reason}")
                _audit(record, "deleted", {"soft_delete": True, "reason": reason,
                                           "previous_status": previous_status, "status": "Silindi"})
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise
            flash("Kayıt aktif listeden silindi. Görseller ve geçmiş arşivde korunuyor.", "success")
            return redirect(url_for("customer_portal.dashboard"))
    return render_template("customer_portal/delete.html", record=record, error=error), (400 if error else 200)


@bp.get("/musteri-geri-bildirimleri/<int:record_id>/dosya/<int:file_id>")
@login_required
def internal_file(record_id, file_id):
    if not _has_permission("customer_portal.file_download"):
        abort(403)
    record = _record_or_404(record_id)
    row = ComplaintFile.query.filter_by(id=file_id, company_id=record.company_id, complaint_id=record.id, is_active=True).first_or_404()
    path = _safe_file_path(row)
    _audit(record, "internal_file_download", {"file_id": row.id, "visibility": row.visibility})
    db.session.commit()
    return _private_file_response(send_from_directory(path.parent, path.name, as_attachment=True, download_name=row.original_name))


@bp.get("/musteri-geri-bildirimleri/<int:record_id>/dosya/<int:file_id>/onizle")
@login_required
def preview_file(record_id, file_id):
    if not _has_permission("customer_portal.file_download"):
        abort(403)
    record = _record_or_404(record_id)
    row = scoped_query(ComplaintFile.query, ComplaintFile).filter_by(
        id=file_id, complaint_id=record.id, is_active=True,
    ).first_or_404()
    path = _safe_file_path(row)
    try:
        with path.open("rb") as stream:
            mime_type = _image_mimetype(stream, path.suffix.lower().lstrip("."))
    except ValueError:
        abort(404)
    _audit(record, "internal_file_preview", {"file_id": row.id, "evidence_stage": row.evidence_stage})
    db.session.commit()
    return _private_file_response(send_file(
        path, mimetype=mime_type, as_attachment=False, download_name=row.original_name,
    ))


@bp.post("/musteri-geri-bildirimleri/<int:record_id>/kanit-yukle")
@login_required
def upload_evidence(record_id):
    record = _record_or_404(record_id)
    if record.is_archived:
        abort(400)
    if not (any(_has_permission(key) for key in (
        "customer_portal.respond", "customer_portal.triage", "customer_portal.assign",
    )) or (record.is_internal_feedback and record.created_by_user_id == g.current_user.id
           and _has_permission("customer_portal.create"))):
        abort(403)
    try:
        with _file_transaction() as paths:
            rows = _store_evidence(record, paths)
            if not rows:
                raise ValueError("missing_images")
            db.session.flush()
            _audit(record, "evidence_uploaded", {"files": [
                {"id": row.id, "stage": row.evidence_stage} for row in rows
            ]})
            db.session.commit()
    except (ValueError, IntegrityError):
        flash("PNG/JPEG dosyalarını, boyutlarını ve depolama kotasını kontrol edin.", "danger")
    else:
        flash("Kanıt görselleri kaydedildi.", "success")
    return redirect(url_for("customer_portal.detail", record_id=record.id))


@bp.route("/musteri-geri-bildirimleri/ayarlar", methods=["GET", "POST"])
@login_required
def settings():
    if not _has_permission("customer_portal.settings"):
        abort(403)
    company = _internal_company()
    setting = _portal_setting(company)
    if request.method == "POST":
        try:
            values = {
                "verification_hours": int(request.form.get("verification_hours", 24)),
                "tracking_days": int(request.form.get("tracking_days", 90)),
                "submission_limit_hour": int(request.form.get("submission_limit_hour", 5)),
                "max_file_mb": int(request.form.get("max_file_mb", 10)),
                "first_response_hours": int(request.form.get("first_response_hours", 24)),
                "resolution_hours": int(request.form.get("resolution_hours", 168)),
            }
        except ValueError:
            flash("Sayısal ayarları kontrol edin.", "danger")
        else:
            limits = {
                "verification_hours": (1, 168),
                "tracking_days": (1, 365),
                "submission_limit_hour": (1, 100),
                "max_file_mb": (1, 25),
                "first_response_hours": (1, 720),
                "resolution_hours": (1, 8760),
            }
            if any(
                value < limits[key][0] or value > limits[key][1]
                for key, value in values.items()
            ):
                flash("Sayısal ayarlardan biri izin verilen aralığın dışında.", "danger")
            else:
                for key, value in values.items():
                    setattr(setting, key, value)
                setting.is_enabled = request.form.get("is_enabled") == "on"
                setting.welcome_text = request.form.get("welcome_text", "").strip()[:2000] or None
                setting.consent_text = request.form.get("consent_text", "").strip()[:2000] or DEFAULT_CONSENT
                setting.consent_version = request.form.get("consent_version", "1.0").strip()[:40] or "1.0"
                record_audit_event("CustomerPortalSetting", "updated", company.name, company_id=company.id, details={"portal_enabled": setting.is_enabled}, commit=False)
                db.session.commit()
                flash("Müşteri portalı ayarları kaydedildi.", "success")
                return redirect(url_for("customer_portal.settings"))
    return render_template("customer_portal/settings.html", setting=setting)


@bp.get("/musteri-geri-bildirimleri/rapor.xlsx")
@login_required
def export_excel():
    if not (_has_permission("customer_portal.export") and _has_permission("customer_portal.view")):
        abort(403)
    from .routes import build_simple_xlsx

    rows = []
    for record in _visible_query(include_archived=True).filter(
        or_(ComplaintRecord.source == INTERNAL_FEEDBACK_SOURCE, ComplaintRecord.email_verified_at.isnot(None))
    ).order_by(
        ComplaintRecord.received_date.desc(),
        ComplaintRecord.id.desc(),
    ).all():
        rows.append((
            record.complaint_no,
            record.record_type,
            record.customer_name,
            record.contact_name or "",
            record.contact_email or "",
            record.subject,
            record.department or "",
            record.responsible.full_name if record.responsible else "",
            record.priority,
            record.status,
            record.public_status,
            record.received_date.strftime("%d.%m.%Y") if record.received_date else "",
            record.first_response_due_at.strftime("%d.%m.%Y %H:%M") if record.first_response_due_at else "",
            record.resolution_due_at.strftime("%d.%m.%Y %H:%M") if record.resolution_due_at else "",
            record.customer_rating or "",
            record.customer_reference or "",
            record.created_by.full_name if record.created_by else (record.contact_name or ""),
            record.corrective_action or "",
            record.due_date.strftime("%d.%m.%Y") if record.due_date else "",
            (record.due_date - date.today()).days if record.due_date and not record.is_closed else "",
            record.closed_at.strftime("%d.%m.%Y") if record.closed_at else "",
            record.customer_solution_summary or "",
        ))
    workbook = build_simple_xlsx(
        ("Kayıt No", "Tür", "Müşteri", "İlgili Kişi", "E-posta", "Konu", "Departman", "Sorumlu", "Öncelik", "İç Durum", "Müşteri Durumu", "Alınma Tarihi", "İlk Yanıt Termini", "Çözüm Termini", "Memnuniyet", "Proje No", "Kaydeden", "Yapılan İşlem Özeti", "Termin", "Kalan Gün", "Sonuçlanma Tarihi", "Sonuç Özeti"),
        rows,
        sheet_name="Müşteri Geri Bildirimleri",
    )
    record_audit_event("CustomerFeedbackPortal", "exported", "Excel raporu", company_id=_internal_company().id, details={"row_count": len(rows)})
    return send_file(
        workbook,
        as_attachment=True,
        download_name=f"musteri-geri-bildirimleri-{date.today():%Y%m%d}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
