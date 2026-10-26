"""Private, company-scoped register for signed contracts and their scans."""

from datetime import date
from pathlib import Path
from uuid import uuid4
import warnings

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from PIL import Image, UnidentifiedImageError
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from .audit import record_audit_event
from .contract_models import ContractFile, ContractRecord, utc_now
from .extensions import db
from .tenant import assign_current_company, current_company_id, scoped_query


bp = Blueprint("contracts", __name__, url_prefix="/sozlesmeler")
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 10
MIME_BY_SUFFIX = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def can_view():
    user = getattr(g, "current_user", None)
    return bool(user and current_company_id() and (
        user.has_permission("contracts.view") or user.has_permission("contracts.manage")
    ))


def can_manage():
    return can_view() and g.current_user.has_permission("contracts.manage")


@bp.before_request
def guard():
    if getattr(g, "current_user", None) is None:
        return redirect(url_for("main.login", next=request.full_path))
    if not current_company_id() or not g.company_module_enabled("contracts") or not can_view():
        abort(403)


@bp.context_processor
def template_context():
    return {"contracts_can_manage": can_manage(), "contracts_today": date.today()}


def record_query():
    return scoped_query(ContractRecord.query, ContractRecord).filter(
        ContractRecord.company_id == current_company_id()
    )


def record_or_404(record_id):
    return record_query().filter_by(id=record_id).first_or_404()


def file_or_404(record, file_id):
    return ContractFile.query.filter_by(
        id=file_id, record_id=record.id, company_id=record.company_id, is_active=True
    ).first_or_404()


def snapshot(record):
    return {key: getattr(record, key) for key in (
        "title", "counterparty", "contract_no", "signed_on", "starts_on", "ends_on", "note", "archived_at"
    )}


def audit(record, action, old=None, extra=None):
    values = snapshot(record)
    if extra:
        values.update(extra)
    record_audit_event(
        "ContractRecord", action, record.title, entity_id=record.id,
        company_id=record.company_id, user_id=g.current_user.id,
        old_values=old, new_values=values, commit=False,
    )


def form_values():
    values = {}
    for key, limit, required in (
        ("title", 180, True), ("counterparty", 180, True), ("contract_no", 100, False), ("note", 5000, False),
    ):
        value = request.form.get(key, "").strip()
        if len(value) > limit or (required and not value) or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Zorunlu alanları ve metin uzunluklarını kontrol edin.")
        values[key] = value or None
    for key in ("signed_on", "starts_on", "ends_on"):
        raw = request.form.get(key, "").strip()
        try:
            values[key] = date.fromisoformat(raw) if raw else None
        except ValueError:
            raise ValueError("Tarihleri kontrol edin.") from None
    if values["starts_on"] and values["ends_on"] and values["ends_on"] < values["starts_on"]:
        raise ValueError("Bitiş tarihi başlangıç tarihinden önce olamaz.")
    return values


def selected_files(required=False):
    uploads = [item for item in request.files.getlist("documents") if item and item.filename]
    if (required and not uploads) or len(uploads) > MAX_FILES:
        raise ValueError("En az bir, en fazla on belge seçin.")
    return uploads


def file_metadata(upload):
    suffix = Path(upload.filename).suffix.lower()
    mime = MIME_BY_SUFFIX.get(suffix)
    if not mime:
        raise ValueError("Yalnızca PDF, JPEG veya PNG yüklenebilir.")
    from .routes import uploaded_stream_size

    size = uploaded_stream_size(upload)
    if size is None or not 0 < size <= MAX_FILE_BYTES:
        raise ValueError("Her belge 10 MB veya daha küçük olmalıdır.")
    upload.stream.seek(0)
    head = upload.stream.read(8)
    upload.stream.seek(0)
    if suffix == ".pdf":
        if not head.startswith(b"%PDF-"):
            raise ValueError("PDF içeriği geçersiz.")
    else:
        expected = "PNG" if suffix == ".png" else "JPEG"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(upload.stream) as image:
                    if image.format != expected or image.width * image.height > 20_000_000:
                        raise ValueError("Görsel biçimi veya boyutları geçersiz.")
                    image.verify()
                upload.stream.seek(0)
                with Image.open(upload.stream) as image:
                    image.load()
        except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ValueError("Görsel içeriği geçersiz.") from error
        finally:
            upload.stream.seek(0)
    return suffix, mime, size


def save_files(record, uploads, saved_paths):
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path

    validated = [(upload, *file_metadata(upload)) for upload in uploads]
    assert_company_storage_quota(record.company_id, sum(size for _upload, _suffix, _mime, size in validated))
    rows = []
    for upload, suffix, mime, size in validated:
        relative, absolute = upload_storage_path(f"{uuid4().hex}{suffix}", "contracts", record.company_id)
        saved_paths.append(absolute)
        upload.stream.seek(0)
        upload.save(absolute)
        if absolute.stat().st_size != size:
            raise ValueError("Dosya yüklemesi tamamlanamadı.")
        row = ContractFile(
            company_id=record.company_id, record=record,
            original_name=safe_original_filename(upload.filename, "sozlesme-belgesi"),
            stored_path=relative.as_posix(), mime_type=mime, size_bytes=size,
            uploaded_by_user_id=g.current_user.id,
        )
        db.session.add(row)
        rows.append(row)
    db.session.flush()
    return rows


def rollback_files(saved_paths):
    db.session.rollback()
    for path in saved_paths:
        path.unlink(missing_ok=True)


def commit_or_conflict():
    try:
        db.session.commit()
    except (IntegrityError, StaleDataError):
        db.session.rollback()
        abort(409, description="Kayıt başka bir işlemle değişti. Sayfayı yenileyin.")


@bp.get("")
@bp.get("/")
def dashboard():
    query = record_query()
    if request.args.get("archive") == "1":
        query = query.filter(ContractRecord.archived_at.is_not(None))
    else:
        query = query.filter(ContractRecord.archived_at.is_(None))
    search = request.args.get("q", "").strip()[:100]
    if search:
        like = f"%{search}%"
        query = query.filter(or_(ContractRecord.title.ilike(like), ContractRecord.counterparty.ilike(like), ContractRecord.contract_no.ilike(like)))
    pagination = query.order_by(ContractRecord.created_at.desc(), ContractRecord.id.desc()).paginate(
        page=max(1, request.args.get("page", 1, type=int)), per_page=25, error_out=False
    )
    return render_template("contracts/dashboard.html", pagination=pagination, search=search)


@bp.route("/yeni", methods=["GET", "POST"])
def create():
    if not can_manage():
        abort(403)
    error = None
    if request.method == "POST":
        saved_paths = []
        try:
            values = form_values()
            uploads = selected_files(required=True)
            record = ContractRecord(**values, created_by_user_id=g.current_user.id)
            assign_current_company(record)
            db.session.add(record)
            db.session.flush()
            rows = save_files(record, uploads, saved_paths)
            audit(record, "created", extra={"file_ids": [row.id for row in rows]})
            commit_or_conflict()
            flash("Sözleşme kaydedildi.", "success")
            return redirect(url_for("contracts.detail", record_id=record.id))
        except ValueError as exc:
            rollback_files(saved_paths)
            error = str(exc)
        except Exception:
            rollback_files(saved_paths)
            raise
    return render_template("contracts/form.html", record=None, values=request.form, error=error), (400 if error else 200)


@bp.get("/<int:record_id>")
def detail(record_id):
    return render_template("contracts/detail.html", record=record_or_404(record_id))


@bp.route("/<int:record_id>/duzenle", methods=["GET", "POST"])
def edit(record_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id)
    if record.archived_at:
        abort(409)
    error = None
    if request.method == "POST":
        saved_paths = []
        try:
            values = form_values()
            uploads = selected_files()
            old = snapshot(record)
            for key, value in values.items():
                setattr(record, key, value)
            rows = save_files(record, uploads, saved_paths) if uploads else []
            record.updated_at = utc_now()
            audit(record, "updated", old, {"file_ids": [row.id for row in rows]})
            commit_or_conflict()
            flash("Sözleşme güncellendi.", "success")
            return redirect(url_for("contracts.detail", record_id=record.id))
        except ValueError as exc:
            rollback_files(saved_paths)
            error = str(exc)
        except Exception:
            rollback_files(saved_paths)
            raise
    return render_template("contracts/form.html", record=record, values=request.form if request.method == "POST" else {}, error=error), (400 if error else 200)


@bp.post("/<int:record_id>/belge")
def upload(record_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id)
    if record.archived_at:
        abort(409)
    saved_paths = []
    try:
        rows = save_files(record, selected_files(required=True), saved_paths)
        record.updated_at = utc_now()
        audit(record, "document_uploaded", extra={"file_ids": [row.id for row in rows]})
        commit_or_conflict()
        flash("Belgeler eklendi.", "success")
    except ValueError as exc:
        rollback_files(saved_paths)
        flash(str(exc), "danger")
    except Exception:
        rollback_files(saved_paths)
        raise
    return redirect(url_for("contracts.detail", record_id=record.id))


def serve_document(record, row, *, attachment):
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    path = (root / row.stored_path).resolve()
    expected = root / f"company-{record.company_id:03d}" / "contracts"
    if not path.is_relative_to(expected) or not path.is_file():
        abort(404)
    record_audit_event(
        "ContractFile", "downloaded" if attachment else "viewed", row.original_name,
        entity_id=row.id, company_id=record.company_id, user_id=g.current_user.id,
    )
    response = send_file(path, mimetype=row.mime_type, as_attachment=attachment, download_name=row.original_name)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "sandbox"
    return response


@bp.get("/<int:record_id>/belge/<int:file_id>")
def document(record_id, file_id):
    record = record_or_404(record_id)
    return serve_document(record, file_or_404(record, file_id), attachment=False)


@bp.get("/<int:record_id>/belge/<int:file_id>/indir")
def download(record_id, file_id):
    record = record_or_404(record_id)
    return serve_document(record, file_or_404(record, file_id), attachment=True)


@bp.post("/<int:record_id>/belge/<int:file_id>/kaldir")
def remove_file(record_id, file_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id)
    if record.archived_at:
        abort(409)
    row = file_or_404(record, file_id)
    if sum(item.is_active for item in record.files) <= 1:
        abort(409, description="Sözleşmenin son belgesi kaldırılamaz.")
    row.is_active = False
    record.updated_at = utc_now()
    audit(record, "document_removed", extra={"file_id": row.id, "file_name": row.original_name})
    commit_or_conflict()
    flash("Belge kayıttan kaldırıldı; denetim izi korundu.", "success")
    return redirect(url_for("contracts.detail", record_id=record.id))


@bp.post("/<int:record_id>/arsivle")
def archive(record_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id)
    if record.archived_at:
        abort(409)
    old = snapshot(record)
    record.archived_at = utc_now()
    audit(record, "archived", old)
    commit_or_conflict()
    flash("Sözleşme arşivlendi.", "success")
    return redirect(url_for("contracts.dashboard"))
