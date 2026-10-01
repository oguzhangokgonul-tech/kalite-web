from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
import unicodedata
from uuid import uuid4
import zipfile
from xml.etree import ElementTree as ET

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
    url_for,
)
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from .audit import record_audit_event
from .extensions import db
from .models import (
    CalibrationRecord,
    Company,
    CompanyDepartment,
    DataImportBatch,
    DataImportRow,
    PersonnelContact,
    SupplierRecord,
)


bp = Blueprint("import_center", __name__, url_prefix="/veri-ice-aktarma")

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 100
MAX_ROWS = 2000
MAX_COLUMNS = 50
MAX_CELL_LENGTH = 2000
TEMPLATE_VERSION = "1"
ALLOWED_EXTENSIONS = {"csv", "xlsx"}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


IMPORT_MODULES = {
    "departments": {
        "label": "Departmanlar",
        "icon": "bi-diagram-3",
        "headers": ("Departman Adı", "Sıralama"),
        "required": ("name",),
        "aliases": {
            "name": ("Departman Adı", "Departman", "Bölüm", "Birim"),
            "sort_order": ("Sıralama", "Sıra", "Sıra No"),
        },
        "entity_type": "CompanyDepartment",
    },
    "personnel": {
        "label": "Personel Listesi",
        "icon": "bi-person-vcard",
        "headers": ("İsim Soyisim", "Telefon No", "Görev/Ünvan", "E-posta"),
        "required": ("full_name",),
        "aliases": {
            "full_name": ("İsim Soyisim", "Ad Soyad", "Personel", "İsim"),
            "phone": ("Telefon No", "Telefon", "Cep Telefonu"),
            "title": ("Görev/Ünvan", "Görev Ünvan", "Ünvan", "Görev", "Departman"),
            "email": ("E-posta", "Eposta", "Email", "Mail"),
        },
        "entity_type": "PersonnelContact",
    },
    "calibrations": {
        "label": "Kalibrasyon Cihazları",
        "icon": "bi-rulers",
        "headers": (
            "Cihaz Kodu", "Cihaz / Ekipman", "İmalatçı", "Marka / Model",
            "Seri No", "Sertifika No", "Son Kalibrasyon", "Gelecek Kalibrasyon", "Durum",
        ),
        "required": ("device_code", "device_name"),
        "aliases": {
            "device_code": ("Cihaz Kodu", "Kod"),
            "device_name": ("Cihaz / Ekipman", "Cihaz", "Ekipman", "Cihaz Adı"),
            "manufacturer": ("İmalatçı", "Üretici"),
            "brand_model": ("Marka / Model", "Marka Model", "Model"),
            "serial_no": ("Seri No", "Seri Numarası"),
            "certificate_no": ("Sertifika No", "Sertifika Numarası"),
            "calibration_date": ("Son Kalibrasyon", "Kalibrasyon Tarihi"),
            "next_calibration_date": ("Gelecek Kalibrasyon", "Sonraki Kalibrasyon"),
            "status": ("Durum",),
        },
        "entity_type": "CalibrationRecord",
    },
    "suppliers": {
        "label": "Tedarikçiler",
        "icon": "bi-truck",
        "headers": (
            "Tedarikçi No", "Tedarikçi Adı", "Ürün Grubu", "Departman",
            "Yetkili", "Telefon", "E-posta", "Durum",
        ),
        "required": ("supplier_no", "name"),
        "aliases": {
            "supplier_no": ("Tedarikçi No", "Tedarikçi Kodu", "Kod"),
            "name": ("Tedarikçi Adı", "Tedarikçi", "Firma Adı"),
            "product_group": ("Ürün Grubu", "Ürün/Hizmet", "Ürün"),
            "department": ("Departman", "Birim"),
            "contact_person": ("Yetkili", "İlgili Kişi"),
            "phone": ("Telefon", "Telefon No"),
            "email": ("E-posta", "Eposta", "Email", "Mail"),
            "status": ("Durum",),
        },
        "entity_type": "SupplierRecord",
    },
}


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _normalize_header(value):
    value = str(value or "").strip().casefold().replace("ı", "i")
    value = "".join(
        character for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _text(value, limit=MAX_CELL_LENGTH):
    text_value = " ".join(str(value or "").replace("\x00", "").split()).strip()
    if len(text_value) > limit:
        raise ValueError(f"Değer {limit} karakter sınırını aşıyor.")
    if text_value.startswith(("=", "@")):
        raise ValueError("Formül benzeri değer kabul edilmez.")
    return text_value


def _optional_text(value, limit):
    parsed = _text(value, limit)
    return parsed or None


def _parse_positive_int(value, default):
    text_value = _text(value, 20)
    if not text_value:
        return default
    try:
        parsed = int(float(text_value.replace(",", ".")))
    except ValueError as error:
        raise ValueError("Pozitif tam sayı olmalıdır.") from error
    if parsed < 1:
        raise ValueError("Pozitif tam sayı olmalıdır.")
    return parsed


def _parse_date(value):
    if value in (None, ""):
        return None
    text_value = _text(value, 40)
    if re.fullmatch(r"\d+(?:\.\d+)?", text_value):
        serial = float(text_value)
        if 1 <= serial <= 100000:
            return date(1899, 12, 30) + timedelta(days=int(serial))
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text_value, pattern).date()
        except ValueError:
            continue
    raise ValueError("Tarih GG.AA.YYYY veya YYYY-AA-GG biçiminde olmalıdır.")


def _read_csv(content):
    decoded = None
    for encoding in ("utf-8-sig", "cp1254"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError("CSV dosyası UTF-8 veya Windows Türkçe kodlamasında olmalıdır.")
    try:
        dialect = csv.Sniffer().sniff(decoded[:4096], delimiters=",;\t")
        return list(csv.reader(StringIO(decoded), dialect))
    except csv.Error:
        return list(csv.reader(StringIO(decoded), delimiter=";"))


def _column_index(reference):
    letters = re.match(r"[A-Z]+", reference or "")
    if not letters:
        return None
    result = 0
    for character in letters.group(0):
        result = result * 26 + ord(character) - 64
    return result - 1


def _read_xlsx(content):
    stream = BytesIO(content)
    if not zipfile.is_zipfile(stream):
        raise ValueError("Geçerli bir XLSX dosyası yükleyin.")
    with zipfile.ZipFile(stream) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise ValueError("XLSX arşivi beklenenden fazla dosya içeriyor.")
        total_size = sum(item.file_size for item in entries)
        if total_size > MAX_ARCHIVE_BYTES:
            raise ValueError("XLSX açılmış boyut sınırını aşıyor.")
        for item in entries:
            if item.filename.startswith(("/", "\\")) or ".." in Path(item.filename).parts:
                raise ValueError("XLSX içinde geçersiz dosya yolu bulundu.")
        if "xl/worksheets/sheet1.xml" not in archive.namelist():
            raise ValueError("XLSX ilk çalışma sayfası bulunamadı.")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.findall(".//m:t", NS)) for item in root.findall("m:si", NS)]
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        if root.find(".//m:f", NS) is not None:
            raise ValueError("Güvenlik nedeniyle formül içeren XLSX dosyaları kabul edilmez.")
        rows = []
        for row in root.findall(".//m:sheetData/m:row", NS):
            values = []
            for cell in row.findall("m:c", NS):
                index = _column_index(cell.get("r"))
                if index is None or index >= MAX_COLUMNS:
                    continue
                while len(values) <= index:
                    values.append("")
                cell_type = cell.get("t")
                if cell_type == "inlineStr":
                    value = "".join(node.text or "" for node in cell.findall(".//m:t", NS))
                else:
                    node = cell.find("m:v", NS)
                    value = node.text if node is not None and node.text is not None else ""
                    if cell_type == "s" and value:
                        try:
                            value = shared[int(value)]
                        except (ValueError, IndexError):
                            value = ""
                values[index] = value
            rows.append(values)
        return rows


def parse_tabular_file(filename, content):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Yalnızca CSV veya XLSX dosyası yükleyin.")
    rows = _read_csv(content) if extension == "csv" else _read_xlsx(content)
    rows = [row[:MAX_COLUMNS] for row in rows if any(str(value or "").strip() for value in row)]
    if not rows:
        raise ValueError("Dosyada başlık satırı bulunamadı.")
    if len(rows) == 1:
        raise ValueError("Dosyada başlık dışında veri satırı bulunamadı.")
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError(f"Bir dosyada en fazla {MAX_ROWS} veri satırı olabilir.")
    return rows


def _header_mapping(module_key, headers):
    spec = IMPORT_MODULES[module_key]
    normalized_headers = [_normalize_header(header) for header in headers]
    mapping = {}
    for field, aliases in spec["aliases"].items():
        alias_keys = {_normalize_header(alias) for alias in aliases}
        matches = [index for index, header in enumerate(normalized_headers) if header in alias_keys]
        if len(matches) > 1:
            raise ValueError(f"{aliases[0]} sütunu birden fazla kez eşleşti.")
        if matches:
            mapping[field] = matches[0]
    missing = [field for field in spec["required"] if field not in mapping]
    if missing:
        labels = [spec["aliases"][field][0] for field in missing]
        raise ValueError("Zorunlu sütunlar eksik: " + ", ".join(labels))
    return mapping


def _raw_value(row, mapping, field):
    index = mapping.get(field)
    return row[index] if index is not None and index < len(row) else ""


def _normalize_row(module_key, row, mapping, row_number):
    errors = []
    values = {}
    try:
        if module_key == "departments":
            values = {
                "name": _text(_raw_value(row, mapping, "name"), 160),
                "sort_order": _parse_positive_int(_raw_value(row, mapping, "sort_order"), row_number - 1),
                "is_active": True,
            }
        elif module_key == "personnel":
            values = {
                "full_name": _text(_raw_value(row, mapping, "full_name"), 180),
                "phone": _optional_text(_raw_value(row, mapping, "phone"), 60),
                "title": _optional_text(_raw_value(row, mapping, "title"), 160),
                "email": _optional_text(_raw_value(row, mapping, "email"), 255),
                "is_active": True,
            }
            values["department"] = values["title"]
            if values["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["email"]):
                errors.append("E-posta biçimi geçersiz.")
        elif module_key == "calibrations":
            status = (_text(_raw_value(row, mapping, "status"), 40) or "UYGUN").upper()
            if status not in {"UYGUN", "KONTROL", "GECİKTİ", "PASİF"}:
                errors.append("Durum UYGUN, KONTROL, GECİKTİ veya PASİF olmalıdır.")
            values = {
                "device_code": _text(_raw_value(row, mapping, "device_code"), 80),
                "device_name": _text(_raw_value(row, mapping, "device_name"), 220),
                "manufacturer": _optional_text(_raw_value(row, mapping, "manufacturer"), 160),
                "brand_model": _optional_text(_raw_value(row, mapping, "brand_model"), 180),
                "serial_no": _optional_text(_raw_value(row, mapping, "serial_no"), 160),
                "certificate_no": _optional_text(_raw_value(row, mapping, "certificate_no"), 160),
                "calibration_date": _parse_date(_raw_value(row, mapping, "calibration_date")),
                "next_calibration_date": _parse_date(_raw_value(row, mapping, "next_calibration_date")),
                "status": status,
                "is_active": status != "PASİF",
            }
            if values["calibration_date"] and values["next_calibration_date"] and values["next_calibration_date"] < values["calibration_date"]:
                errors.append("Gelecek kalibrasyon tarihi son kalibrasyondan önce olamaz.")
        else:
            values = {
                "supplier_no": _text(_raw_value(row, mapping, "supplier_no"), 30),
                "name": _text(_raw_value(row, mapping, "name"), 180),
                "product_group": _optional_text(_raw_value(row, mapping, "product_group"), 160),
                "department": _optional_text(_raw_value(row, mapping, "department"), 80),
                "contact_person": _optional_text(_raw_value(row, mapping, "contact_person"), 160),
                "phone": _optional_text(_raw_value(row, mapping, "phone"), 80),
                "email": _optional_text(_raw_value(row, mapping, "email"), 160),
                "status": _optional_text(_raw_value(row, mapping, "status"), 40) or "Değerlendirme Bekliyor",
                "is_active": True,
            }
            if values["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["email"]):
                errors.append("E-posta biçimi geçersiz.")
    except ValueError as error:
        errors.append(str(error))
    for field in IMPORT_MODULES[module_key]["required"]:
        if not values.get(field):
            errors.append(f"{IMPORT_MODULES[module_key]['aliases'][field][0]} zorunludur.")
    return values, list(dict.fromkeys(errors))


def _duplicate_key(module_key, values):
    if module_key == "departments":
        return (str(values.get("name") or "").casefold(),)
    if module_key == "personnel":
        return (str(values.get("full_name") or "").casefold(), str(values.get("phone") or ""))
    if module_key == "calibrations":
        return (str(values.get("device_code") or "").casefold(),)
    return (str(values.get("supplier_no") or "").casefold(),)


def _database_duplicate(module_key, company_id, values):
    if module_key == "departments":
        return CompanyDepartment.query.filter(
            CompanyDepartment.company_id == company_id,
            db.func.lower(CompanyDepartment.name) == values["name"].lower(),
        ).first()
    if module_key == "personnel":
        return PersonnelContact.query.filter_by(
            company_id=company_id, full_name=values["full_name"], phone=values["phone"]
        ).first()
    if module_key == "calibrations":
        return CalibrationRecord.query.filter_by(company_id=company_id, device_code=values["device_code"]).first()
    return SupplierRecord.query.filter_by(company_id=company_id, supplier_no=values["supplier_no"]).first()


def _serialize_values(values):
    return {
        key: value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in values.items()
    }


def _deserialize_values(values):
    restored = dict(values)
    for field in ("calibration_date", "next_calibration_date"):
        if restored.get(field):
            restored[field] = date.fromisoformat(restored[field])
    return restored


def _create_target(batch, values):
    common = {"company_id": batch.company_id}
    if batch.module_key == "departments":
        return CompanyDepartment(**common, **values)
    if batch.module_key == "personnel":
        return PersonnelContact(**common, created_by_user_id=g.current_user.id, **values)
    if batch.module_key == "calibrations":
        return CalibrationRecord(**common, created_by_user_id=g.current_user.id, **values)
    return SupplierRecord(**common, created_by_user_id=g.current_user.id, **values)


def _target_model(module_key):
    return {
        "departments": CompanyDepartment,
        "personnel": PersonnelContact,
        "calibrations": CalibrationRecord,
        "suppliers": SupplierRecord,
    }[module_key]


def _snapshot_target(module_key, record):
    fields = {
        "departments": ("name", "sort_order", "is_active"),
        "personnel": ("full_name", "phone", "title", "email", "department", "is_active"),
        "calibrations": (
            "device_code", "device_name", "manufacturer", "brand_model", "serial_no",
            "certificate_no", "calibration_date", "next_calibration_date", "status", "is_active",
        ),
        "suppliers": (
            "supplier_no", "name", "product_group", "department", "contact_person",
            "phone", "email", "status", "is_active",
        ),
    }[module_key]
    return _serialize_values({field: getattr(record, field) for field in fields})


def _is_superadmin():
    return bool(getattr(g, "current_user_is_superadmin_account", False))


def import_access(permission):
    def decorator(view):
        from functools import wraps

        @wraps(view)
        def wrapped(*args, **kwargs):
            if getattr(g, "current_user", None) is None:
                return redirect(url_for("main.login", next=request.full_path))
            if not _is_superadmin() or not g.current_user.has_permission(permission):
                abort(403)
            return view(*args, **kwargs)

        return wrapped
    return decorator


def _batch_or_404(batch_id):
    return DataImportBatch.query.filter_by(id=batch_id).first_or_404()


@bp.get("")
@import_access("imports.view")
def dashboard():
    batches = DataImportBatch.query.order_by(DataImportBatch.created_at.desc(), DataImportBatch.id.desc()).limit(100).all()
    companies = Company.query.filter_by(is_active=True).order_by(Company.code.asc()).all()
    return render_template(
        "import_center/dashboard.html",
        batches=batches,
        companies=companies,
        modules=IMPORT_MODULES,
        max_file_mb=MAX_FILE_BYTES // (1024 * 1024),
    )


@bp.get("/sablon/<module_key>.xlsx")
@import_access("imports.view")
def template(module_key):
    spec = IMPORT_MODULES.get(module_key)
    if spec is None:
        abort(404)
    from .routes import build_simple_xlsx

    content = build_simple_xlsx(spec["headers"], [], sheet_name=spec["label"][:31])
    return send_file(
        content,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"volkaportal-{module_key}-sablon-v{TEMPLATE_VERSION}.xlsx",
    )


@bp.post("/onizle")
@import_access("imports.prepare")
def preview():
    module_key = request.form.get("module_key", "").strip()
    spec = IMPORT_MODULES.get(module_key)
    if spec is None:
        abort(400, description="Geçerli bir aktarım modülü seçin.")
    try:
        company_id = int(request.form.get("company_id", ""))
    except ValueError:
        abort(400, description="Geçerli bir şirket seçin.")
    company = Company.query.filter_by(id=company_id, is_active=True).first_or_404()
    upload = request.files.get("source_file")
    filename = secure_filename(upload.filename or "") if upload else ""
    if not upload or not filename:
        abort(400, description="CSV veya XLSX dosyası seçin.")
    content = upload.read(MAX_FILE_BYTES + 1)
    if not content or len(content) > MAX_FILE_BYTES:
        abort(413, description=f"Dosya en fazla {MAX_FILE_BYTES // (1024 * 1024)} MB olabilir.")
    try:
        parsed_rows = parse_tabular_file(filename, content)
        mapping = _header_mapping(module_key, parsed_rows[0])
    except ValueError as error:
        flash(str(error), "danger")
        return redirect(url_for("import_center.dashboard"))
    file_hash = hashlib.sha256(content).hexdigest()
    existing = DataImportBatch.query.filter_by(
        company_id=company.id, module_key=module_key, file_sha256=file_hash
    ).first()
    if existing is not None:
        flash("Bu dosya bu şirket ve modül için daha önce yüklenmiş; mevcut parti açıldı.", "warning")
        return redirect(url_for("import_center.detail", batch_id=existing.id))

    seen = set()
    counts = {"valid": 0, "warning": 0, "error": 0}
    prepared_rows = []
    for row_number, source_row in enumerate(parsed_rows[1:], start=2):
        values, messages = _normalize_row(module_key, source_row, mapping, row_number)
        duplicate_key = _duplicate_key(module_key, values)
        planned_action = "create"
        status = "error" if messages else "valid"
        if status != "error" and duplicate_key in seen:
            status, planned_action = "warning", "skip"
            messages.append("Aynı dosyada mükerrer kayıt; aktarımda atlanacak.")
        elif status != "error" and _database_duplicate(module_key, company.id, values) is not None:
            status, planned_action = "warning", "skip"
            messages.append("Şirkette aynı anahtara sahip kayıt var; aktarımda atlanacak.")
        seen.add(duplicate_key)
        counts[status] += 1
        source = {
            str(parsed_rows[0][index] or f"Sütun {index + 1}")[:120]: str(value or "")[:MAX_CELL_LENGTH]
            for index, value in enumerate(source_row[:len(parsed_rows[0])])
        }
        prepared_rows.append({
            "row_number": row_number,
            "status": status,
            "planned_action": planned_action,
            "source_json": _json(source),
            "normalized_json": _json(_serialize_values(values)),
            "messages_json": _json(messages),
        })

    relative_path = f"company-{company.id:03d}/imports/{uuid4().hex}-{filename[:180]}"
    destination = Path(current_app.config["UPLOAD_FOLDER"]) / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    try:
        batch = DataImportBatch(
            company_id=company.id,
            module_key=module_key,
            template_version=TEMPLATE_VERSION,
            original_filename=filename[:255],
            stored_file_path=relative_path,
            file_sha256=file_hash,
            file_size=len(content),
            status="validated",
            created_by_user_id=g.current_user.id,
            total_count=sum(counts.values()),
            valid_count=counts["valid"],
            warning_count=counts["warning"],
            error_count=counts["error"],
        )
        db.session.add(batch)
        db.session.flush()
        for row in prepared_rows:
            db.session.add(DataImportRow(company_id=company.id, batch_id=batch.id, **row))
        record_audit_event(
            "DataImportBatch", "validated", "Veri içe aktarma dosyası doğrulandı",
            entity_id=batch.id,
            company_id=company.id,
            details={
                "company_id": company.id, "module_key": module_key, "template_version": TEMPLATE_VERSION,
                "file_sha256": file_hash, "file_size": len(content), "total_count": batch.total_count,
                "valid_count": batch.valid_count, "warning_count": batch.warning_count,
                "error_count": batch.error_count,
            },
            commit=False,
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        destination.unlink(missing_ok=True)
        existing = DataImportBatch.query.filter_by(
            company_id=company.id, module_key=module_key, file_sha256=file_hash
        ).first()
        if existing is not None:
            flash("Bu dosya bu şirket ve modül için daha önce yüklenmiş; mevcut parti açıldı.", "warning")
            return redirect(url_for("import_center.detail", batch_id=existing.id))
        raise
    except Exception:
        db.session.rollback()
        destination.unlink(missing_ok=True)
        raise
    flash("Dosya doğrulandı. Veriler henüz sisteme yazılmadı.", "success")
    return redirect(url_for("import_center.detail", batch_id=batch.id))


@bp.get("/<int:batch_id>")
@import_access("imports.view")
def detail(batch_id):
    batch = _batch_or_404(batch_id)
    return render_template(
        "import_center/detail.html",
        batch=batch,
        module=IMPORT_MODULES[batch.module_key],
        load_json=_load_json,
    )


@bp.post("/<int:batch_id>/uygula")
@import_access("imports.apply")
def apply(batch_id):
    batch = _batch_or_404(batch_id)
    if batch.status != "validated":
        abort(409, description="Bu aktarım partisi uygulanabilir durumda değil.")
    if batch.error_count:
        abort(409, description="Hatalı satırlar düzeltilmeden aktarım uygulanamaz.")
    if batch.valid_count < 1:
        abort(409, description="Aktarılacak yeni ve geçerli kayıt bulunmuyor.")
    if request.form.get("confirm") != "yes":
        abort(400, description="Aktarımı açıkça onaylamalısınız.")
    created_count = 0
    try:
        for item in batch.rows:
            if item.status != "valid" or item.planned_action != "create":
                continue
            values = _deserialize_values(_load_json(item.normalized_json, {}))
            if _database_duplicate(batch.module_key, batch.company_id, values) is not None:
                item.status = "warning"
                item.planned_action = "skip"
                item.messages_json = _json(["Uygulama sırasında mükerrer bulundu; atlandı."])
                batch.warning_count += 1
                batch.valid_count -= 1
                continue
            target = _create_target(batch, values)
            db.session.add(target)
            db.session.flush()
            item.target_entity_type = IMPORT_MODULES[batch.module_key]["entity_type"]
            item.target_entity_id = target.id
            item.after_json = _json(_snapshot_target(batch.module_key, target))
            created_count += 1
        batch.created_count = created_count
        batch.status = "applied"
        batch.applied_by_user_id = g.current_user.id
        batch.applied_at = _utcnow()
        record_audit_event(
            "DataImportBatch", "applied", "Veri içe aktarma partisi uygulandı",
            entity_id=batch.id,
            company_id=batch.company_id,
            details={
                "company_id": batch.company_id, "module_key": batch.module_key,
                "file_sha256": batch.file_sha256, "created_count": created_count,
                "skipped_count": batch.warning_count, "error_count": batch.error_count,
            },
            commit=False,
        )
        if created_count:
            from .routes import mark_sales_readiness_item_done_without_commit
            mark_sales_readiness_item_done_without_commit("competitor_import_center")
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Veri içe aktarma partisi uygulanamadı: %s", batch_id)
        abort(500, description="Aktarım uygulanamadı; hiçbir satır kaydedilmedi.")
    flash(f"Aktarım tamamlandı: {created_count} yeni kayıt oluşturuldu.", "success")
    return redirect(url_for("import_center.detail", batch_id=batch.id))


@bp.post("/<int:batch_id>/geri-al")
@import_access("imports.rollback")
def rollback(batch_id):
    batch = _batch_or_404(batch_id)
    if batch.status != "applied":
        abort(409, description="Yalnız uygulanmış bir aktarım geri alınabilir.")
    if request.form.get("confirm") != "yes":
        abort(400, description="Geri alma işlemini açıkça onaylamalısınız.")
    model = _target_model(batch.module_key)
    targets = []
    for item in batch.rows:
        if not item.target_entity_id:
            continue
        target = db.session.get(model, item.target_entity_id)
        if target is None or target.company_id != batch.company_id:
            abort(409, description="Aktarılan kayıtlardan biri bulunamadı; güvenli geri alma durduruldu.")
        if _snapshot_target(batch.module_key, target) != _load_json(item.after_json, {}):
            abort(409, description="Aktarılan kayıtlardan biri sonradan değişmiş; güvenli geri alma durduruldu.")
        targets.append(target)
    try:
        for target in targets:
            db.session.delete(target)
        batch.status = "rolled_back"
        batch.rolled_back_by_user_id = g.current_user.id
        batch.rolled_back_at = _utcnow()
        record_audit_event(
            "DataImportBatch", "rolled_back", "Veri içe aktarma partisi geri alındı",
            entity_id=batch.id,
            company_id=batch.company_id,
            details={
                "company_id": batch.company_id, "module_key": batch.module_key,
                "file_sha256": batch.file_sha256, "deleted_count": len(targets),
            },
            commit=False,
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, description="Aktarılan kayıtlar kullanımda olduğu için geri alma güvenle tamamlanamadı.")
    flash(f"Aktarım geri alındı: {len(targets)} kayıt kaldırıldı.", "success")
    return redirect(url_for("import_center.detail", batch_id=batch.id))


@bp.get("/<int:batch_id>/hata-raporu.xlsx")
@import_access("imports.view")
def error_report(batch_id):
    batch = _batch_or_404(batch_id)
    from .routes import build_simple_xlsx

    rows = []
    for item in batch.rows:
        if item.status == "valid":
            continue
        source = _load_json(item.source_json, {})
        rows.append((
            item.row_number,
            "Hatalı" if item.status == "error" else "Atlanacak",
            "; ".join(_load_json(item.messages_json, [])),
            " | ".join(f"{key}: {value}" for key, value in source.items()),
        ))
    workbook = build_simple_xlsx(
        ("Satır", "Durum", "Açıklama", "Kaynak Değerler"), rows,
        sheet_name="Aktarım Hataları",
    )
    return send_file(
        workbook,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"aktarim-{batch.id}-hata-raporu.xlsx",
    )
