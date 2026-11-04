from datetime import datetime, timezone
from contextlib import contextmanager
from functools import wraps
from io import BytesIO
from pathlib import Path
import re
from uuid import uuid4
import warnings

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import StaleDataError

from .audit import record_audit_event
from .extensions import db
from .ohs_notes_models import OhsNote, OhsNoteImage
from .tenant import assign_current_company, current_company_id, scoped_query

bp = Blueprint("ohs_notes", __name__, url_prefix="/isg-notlari")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGES_PER_REQUEST = 6
MAX_IMAGES_PER_NOTE = 12
IMAGE_FORMATS = {".jpg": ("JPEG", "image/jpeg"), ".jpeg": ("JPEG", "image/jpeg"),
                 ".png": ("PNG", "image/png")}


def require_access():
    if not getattr(g, "current_user", None) or not g.current_user.is_active:
        abort(403)
    if not current_company_id() or not g.company_module_enabled("ohs_actions"):
        abort(403)


@bp.before_request
def guard():
    if not getattr(g, "current_user", None):
        return redirect(url_for("main.login", next=request.full_path))
    require_access()


def records():
    return scoped_query(OhsNote.query, OhsNote).filter_by(
        company_id=current_company_id(), deleted_at=None)


def get_note(note_id):
    if not 0 < note_id < 2**63:
        abort(404)
    return records().filter_by(id=note_id).first_or_404()


def can_edit(note):
    user = g.current_user
    return bool(note.company_id == current_company_id() and (
        note.author_id == user.id or
        user.role_keys & {"super_admin", "company_admin", "management_representative"}))


def atomic(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except StaleDataError:
            db.session.rollback()
            abort(409, description="Not değişti. Sayfayı yenileyip tekrar deneyin.")
        except IntegrityError:
            db.session.rollback()
            abort(409, description="Kayıt eşzamanlı olarak değişti. Not havuzunu yenileyip kontrol edin.")
        except OperationalError as error:
            db.session.rollback()
            if "locked" in str(error.orig).lower():
                abort(409, description="Kayıt şu anda işleniyor. Kısa süre sonra tekrar deneyin.")
            raise
        except Exception:
            db.session.rollback()
            raise
    return wrapped


def check_version(note):
    if request.form.get("version_id", type=int) != note.version_id:
        abort(409, description="Not değişti. Sayfayı yenileyip tekrar deneyin.")


def snapshot(note):
    return {key: getattr(note, key) for key in (
        "title", "description", "location", "author_id", "action_id", "converted_at", "deleted_at")}


def audit(note, event, old=None):
    db.session.flush()
    record_audit_event("OhsNote", event, note.number, entity_id=note.id,
                       company_id=note.company_id, old_values=old,
                       new_values=snapshot(note), commit=False)


def form_values():
    result = {}
    for key, limit in (("title", 160), ("description", 5000), ("location", 200)):
        value = request.form.get(key, "").strip()
        if len(value) > limit or (key != "location" and not value) or re.search(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", value
        ):
            raise ValueError("Başlık ve not alanlarını doldurun; metin uzunluklarını kontrol edin.")
        result[key] = value
    return result


def active_images(note):
    return OhsNoteImage.query.filter_by(
        company_id=note.company_id, note_id=note.id, deleted_at=None
    ).order_by(OhsNoteImage.id).all()


def prepared_images():
    uploads = [item for item in request.files.getlist("images") if item and item.filename]
    if len(uploads) > MAX_IMAGES_PER_REQUEST:
        raise ValueError("Tek seferde en fazla 6 görsel ekleyebilirsiniz.")
    result = []
    total_bytes = 0
    processed_bytes = 0
    for upload in uploads:
        extension = Path(upload.filename).suffix.lower()
        if extension not in IMAGE_FORMATS:
            raise ValueError("Yalnızca JPEG ve PNG görselleri yükleyebilirsiniz.")
        expected_format, mime_type = IMAGE_FORMATS[extension]
        raw = upload.stream.read(MAX_IMAGE_BYTES + 1)
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Her görsel en fazla 8 MB olabilir.")
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError("Tek seferde yüklenen görseller toplam 20 MB sınırını aşamaz.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as picture:
                    if picture.format != expected_format or picture.width * picture.height > 20_000_000:
                        raise ValueError("Görsel biçimi veya boyutları geçersiz.")
                    picture.verify()
                with Image.open(BytesIO(raw)) as picture:
                    picture.load()
                    oriented = ImageOps.exif_transpose(picture)
                    clean_image = oriented.convert(
                        "RGBA" if expected_format == "PNG" and
                        ("A" in oriented.getbands() or "transparency" in oriented.info) else "RGB"
                    )
                    try:
                        clean = BytesIO()
                        clean_image.save(clean, format=expected_format)
                    finally:
                        clean_image.close()
                        oriented.close()
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as error:
            raise ValueError("Görsel dosyası açılamadı veya geçersiz.") from error
        data = clean.getvalue()
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("İşlenen görsel 8 MB sınırını aşıyor.")
        processed_bytes += len(data)
        if processed_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError("İşlenen görseller toplam 20 MB sınırını aşıyor.")
        from .routes import safe_original_filename
        result.append((data, extension, mime_type,
                       safe_original_filename(upload.filename, "isg-gorseli")))
    return result


def image_removals(images):
    values = request.form.getlist("remove_image_ids")
    if any(not value.isascii() or not value.isdigit() or len(value) > 18 for value in values):
        raise ValueError("Kaldırılacak görsel geçersiz.")
    selected = {int(value) for value in values}
    if selected - {image.id for image in images}:
        raise ValueError("Kaldırılacak görsel bu nota ait değil.")
    return [image for image in images if image.id in selected]


@contextmanager
def image_transaction():
    created_paths = []
    try:
        yield created_paths
    except Exception:
        db.session.rollback()
        for path in created_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                current_app.logger.exception("Geri alınan İSG görseli temizlenemedi.")
        raise


def store_images(note, uploads, created_paths):
    from .routes import upload_storage_path
    for data, extension, mime_type, original_name in uploads:
        relative, absolute = upload_storage_path(
            f"{uuid4().hex}{extension}", f"ohs-notes/{note.id}", note.company_id
        )
        created_paths.append(absolute)
        absolute.write_bytes(data)
        image = OhsNoteImage(
            company_id=note.company_id, note_id=note.id,
            uploaded_by_user_id=g.current_user.id, original_name=original_name,
            stored_path=relative.as_posix(), mime_type=mime_type, size_bytes=len(data),
        )
        db.session.add(image)
        db.session.flush()
        record_audit_event("OhsNoteImage", "created", note.number,
                           entity_id=image.id, company_id=note.company_id,
                           new_values={"note_id": note.id, "original_name": original_name,
                                       "size_bytes": len(data)}, commit=False)


def image_file_path(note, image, require_file=True):
    from .routes import safe_upload_path
    parts = Path(image.stored_path.replace("\\", "/")).parts
    if (image.company_id != note.company_id or image.note_id != note.id or
            len(parts) != 4 or parts[:3] !=
            (f"company-{note.company_id:03d}", "ohs-notes", str(note.id)) or
            not re.fullmatch(r"[0-9a-f]{32}\.(?:jpg|jpeg|png)", parts[3])):
        abort(404)
    path = safe_upload_path(image.stored_path)
    expected_dir = (
        Path(current_app.config["UPLOAD_FOLDER"]).resolve() /
        f"company-{note.company_id:03d}" / "ohs-notes" / str(note.id)
    ).resolve()
    if path is None or path.parent != expected_dir or (require_file and not path.is_file()):
        abort(404)
    return path


def image_error(error):
    message = str(error)
    if message == "storage_quota_exceeded":
        message = "Şirket depolama sınırı dolu. Görsel eklenemedi."
    flash(message, "danger")


@bp.get("")
def dashboard():
    query = records().options(joinedload(OhsNote.author))
    search = request.args.get("search", "").strip()[:160]
    status = request.args.get("status", "")
    if search:
        query = query.filter(or_(OhsNote.title.contains(search, autoescape=True),
                                 OhsNote.description.contains(search, autoescape=True)))
    if status == "open":
        query = query.filter(OhsNote.converted_at.is_(None))
    elif status == "converted":
        query = query.filter(OhsNote.converted_at.isnot(None))
    page = query.order_by(OhsNote.created_at.desc(), OhsNote.id.desc()).paginate(
        page=max(1, request.args.get("page", 1, type=int)), per_page=20, error_out=False)
    return render_template("ohs_notes/list.html", page=page, search=search, status=status)


@bp.route("/yeni", methods=["GET", "POST"])
@atomic
def create():
    if request.method == "POST":
        try:
            values = form_values()
            uploads = prepared_images()
            if len(uploads) > MAX_IMAGES_PER_NOTE:
                raise ValueError("Bir İSG notunda en fazla 12 görsel olabilir.")
            from .routes import assert_company_storage_quota
            assert_company_storage_quota(current_company_id(), sum(len(item[0]) for item in uploads))
        except ValueError as error:
            image_error(error)
        else:
            note = OhsNote(author_id=g.current_user.id, **values)
            assign_current_company(note)
            with image_transaction() as created_paths:
                db.session.add(note)
                db.session.flush()
                store_images(note, uploads, created_paths)
                audit(note, "created")
                db.session.commit()
            flash("İSG notu kaydedildi.", "success")
            return redirect(url_for("ohs_notes.detail", note_id=note.id))
    return render_template("ohs_notes/form.html", note=None)


@bp.get("/<int:note_id>")
def detail(note_id):
    from .routes import can_view_action
    note = get_note(note_id)
    action = note.action
    visible_action = action if action and action.company_id == current_company_id() and can_view_action(action) else None
    return render_template("ohs_notes/detail.html", note=note, images=active_images(note),
                           editable=can_edit(note),
                           visible_action=visible_action)


@bp.get("/<int:note_id>/gorseller/<int:image_id>")
def image(note_id, image_id):
    note = get_note(note_id)
    record = OhsNoteImage.query.filter_by(
        id=image_id, note_id=note.id, company_id=note.company_id, deleted_at=None
    ).first_or_404()
    path = image_file_path(note, record)
    response = send_file(BytesIO(path.read_bytes()), mimetype=record.mime_type,
                         download_name=record.original_name, as_attachment=False)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.route("/<int:note_id>/duzenle", methods=["GET", "POST"])
@atomic
def edit(note_id):
    note = get_note(note_id)
    if not can_edit(note):
        abort(403)
    if request.method == "POST":
        check_version(note)
        try:
            values = form_values()
            uploads = prepared_images()
            existing = active_images(note)
            removals = image_removals(existing)
            if len(existing) - len(removals) + len(uploads) > MAX_IMAGES_PER_NOTE:
                raise ValueError("Bir İSG notunda en fazla 12 görsel olabilir.")
            if uploads:
                from .routes import assert_company_storage_quota
                for record in removals:
                    image_file_path(note, record, require_file=False)
                assert_company_storage_quota(
                    note.company_id, sum(len(item[0]) for item in uploads),
                    replacing_paths=[record.stored_path for record in removals],
                )
        except ValueError as error:
            image_error(error)
        else:
            with image_transaction() as created_paths:
                old = snapshot(note)
                for key, value in values.items():
                    setattr(note, key, value)
                if removals or uploads:
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    note.updated_at = now
                    for record in removals:
                        record.deleted_at = now
                        record_audit_event("OhsNoteImage", "deleted", note.number,
                                           entity_id=record.id, company_id=note.company_id,
                                           old_values={"note_id": note.id,
                                                       "original_name": record.original_name},
                                           commit=False)
                store_images(note, uploads, created_paths)
                audit(note, "updated", old)
                db.session.commit()
            for record in removals:
                try:
                    image_file_path(note, record, require_file=False).unlink(missing_ok=True)
                except Exception:
                    current_app.logger.exception("Kaldırılan İSG görseli dosyası temizlenemedi.")
            flash("İSG notu güncellendi.", "success")
            return redirect(url_for("ohs_notes.detail", note_id=note.id))
    return render_template("ohs_notes/form.html", note=note, images=active_images(note))


@bp.post("/<int:note_id>/sil")
@atomic
def delete(note_id):
    note = get_note(note_id)
    if not can_edit(note):
        abort(403)
    check_version(note)
    old = snapshot(note)
    note.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    audit(note, "deleted", old)
    db.session.commit()
    flash("İSG notu silindi. Varsa bağlı aksiyon korundu.", "success")
    return redirect(url_for("ohs_notes.dashboard"))


def source_for_action():
    raw = (request.form if request.method == "POST" else request.args).get("ohs_note_id")
    if not raw:
        return None
    if request.endpoint != "main.create_ohs_action":
        abort(400)
    require_access()
    if not raw.isascii() or not raw.isdigit() or len(raw) > 18:
        abort(404)
    note = get_note(int(raw))
    if note.converted_at is not None:
        abort(409, description="Bu not daha önce aksiyona dönüştürüldü.")
    if request.method == "POST" and request.form.get("ohs_note_version", type=int) != note.version_id:
        abort(409, description="Not değişti. Aksiyon formunu yeniden açın.")
    return note


def link_action(note, action):
    from .routes import add_action_history
    if action.company_id != note.company_id or action.action_category != "ohs":
        abort(403)
    old = snapshot(note)
    note.action_id = action.id
    note.converted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    # Versioned flush claims this note before notifications; a competing save rolls back.
    audit(note, "action_created", old)
    add_action_history(action, "ohs_note_linked",
                       f"Kaynak İSG notu: {note.number} - {note.title}",
                       actor=g.current_user)
