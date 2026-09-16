from datetime import UTC, date, datetime
from functools import wraps
import hashlib
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_

from .extensions import db
from .models import FiveSAudit, FiveSAuditFile, FiveSAuditItem, User
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query


bp = Blueprint("five_s", __name__, url_prefix="/5s-denetim")
STATUSES = {"planned": "Planlandı", "in_progress": "Devam Ediyor", "review_pending": "İnceleme Bekliyor", "correction_pending": "Düzeltme Bekliyor", "completed": "Tamamlandı", "archived": "Arşiv"}
CATEGORIES = (
    ("Ayıklama", "Seiri", ("Gereksiz malzeme ve ekipman çalışma alanından uzaklaştırılmış.", "Kırmızı etiketli malzemeler tanımlı alanda ve süresi içinde yönetiliyor.", "Geçiş yolları ve acil çıkışlar gereksiz malzemeden arındırılmış.")),
    ("Düzenleme", "Seiton", ("Araç, ekipman ve malzemelerin tanımlı yerleri bulunuyor.", "Raf, dolap, zemin ve stok alanı işaretlemeleri anlaşılır.", "Sık kullanılan malzemelere güvenli ve hızlı erişilebiliyor.")),
    ("Temizlik", "Seiso", ("Makine, zemin ve çalışma yüzeyleri temiz durumda.", "Sızıntı, döküntü ve kirlilik kaynakları kontrol altına alınmış.", "Temizlik sorumluları ve periyotları tanımlanmış.")),
    ("Standartlaştırma", "Seiketsu", ("Görsel standartlar ve kontrol listeleri güncel ve erişilebilir.", "İlk üç S için sorumluluk ve uygulama yöntemi standartlaştırılmış.", "Uygunsuzlukların tekrarını önleyen kontroller uygulanıyor.")),
    ("Disiplin", "Shitsuke", ("Çalışanlar 5S kurallarını biliyor ve düzenli uyguluyor.", "Önceki denetim bulguları zamanında kapatılmış.", "5S sonuçları ekiplerle paylaşılıyor ve iyileştirme sürdürülüyor.")),
)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png"}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def has_permission(key):
    return bool(getattr(g, "current_user", None) and g.current_user.has_permission(key))


def require_permission(*keys):
    if not any(has_permission(key) for key in keys): abort(403)


def module_enabled():
    checker = getattr(g, "company_module_enabled", None)
    return checker("five_s_audit") if checker else True


def audit_query(): return scoped_query(FiveSAudit.query, FiveSAudit)
def file_query(): return scoped_query(FiveSAuditFile.query, FiveSAuditFile)


def can_access(audit):
    return bool(has_permission("five_s.view_all") or has_permission("five_s.manage") or audit.auditor_user_id == g.current_user.id or audit.reviewer_user_id == g.current_user.id or any(item.responsible_user_id == g.current_user.id for item in audit.items))


def get_audit_or_404(audit_id):
    audit = audit_query().filter_by(id=audit_id).first_or_404()
    if not can_access(audit): abort(404)
    return audit


def active_users():
    return User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name.asc()).all()


def parse_user(name):
    try: user_id = int(request.form.get(name, ""))
    except ValueError: raise ValueError("Aktif bir personel seçin.") from None
    if not User.query.filter_by(id=user_id, company_id=current_company_id(), is_active=True).first(): raise ValueError("Seçilen personel bu şirkette aktif değil.")
    return user_id


def parse_date(name, required=False):
    raw = request.form.get(name, "").strip()
    if not raw:
        if required: raise ValueError("Plan tarihi zorunludur.")
        return None
    try: return date.fromisoformat(raw)
    except ValueError: raise ValueError("Tarih bilgisini kontrol edin.") from None


def next_audit_no():
    prefix = f"5S-{date.today().year}-"; values = []
    for (number,) in audit_query().with_entities(FiveSAudit.audit_no).filter(FiveSAudit.audit_no.like(f"{prefix}%")).all():
        try: values.append(int(number.rsplit("-", 1)[-1]))
        except (TypeError, ValueError): pass
    return f"{prefix}{max(values, default=0) + 1:04d}"


def store_file(upload, audit, item=None):
    if not upload or not upload.filename: return
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS: raise ValueError("Yalnızca PDF, Word, Excel veya görsel yükleyin.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    original = safe_original_filename(upload.filename, "5s-kanit")
    relative, absolute = upload_storage_path(f"{uuid4().hex}.{extension}", "five-s", audit.company_id)
    assert_company_storage_quota(audit.company_id, uploaded_stream_size(upload)); upload.save(absolute)
    db.session.add(FiveSAuditFile(company_id=audit.company_id, audit=audit, item=item, original_name=original, stored_path=str(relative).replace("\\", "/"), mime_type=upload.mimetype, file_size=absolute.stat().st_size, sha256_hash=hashlib.sha256(absolute.read_bytes()).hexdigest(), uploaded_by_user_id=g.current_user.id))


def notify(user_id, audit, message, suffix):
    user = User.query.filter_by(id=user_id, company_id=audit.company_id, is_active=True).first()
    if user:
        add_user_notification(user, f"{audit.audit_no} - {message}", company_id=audit.company_id, source_key=f"five-s:{suffix}:{audit.id}:{user.id}", target_url=url_for("five_s.detail", audit_id=audit.id), due_date=audit.due_date)


@bp.before_request
def guard_module():
    if not module_enabled(): abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("five_s.view", "five_s.view_all", "five_s.manage")
    query = audit_query()
    if not (has_permission("five_s.view_all") or has_permission("five_s.manage")):
        item_ids = db.session.query(FiveSAuditItem.audit_id).filter_by(company_id=current_company_id(), responsible_user_id=g.current_user.id)
        query = query.filter(or_(FiveSAudit.auditor_user_id == g.current_user.id, FiveSAudit.reviewer_user_id == g.current_user.id, FiveSAudit.id.in_(item_ids)))
    search, status = request.args.get("q", "").strip(), request.args.get("status", "").strip()
    archived = request.args.get("archived", "active") == "archived"
    query = query.filter(FiveSAudit.archived_at.is_not(None) if archived else FiveSAudit.archived_at.is_(None))
    if search:
        term = f"%{search}%"; query = query.filter(or_(FiveSAudit.audit_no.ilike(term), FiveSAudit.title.ilike(term), FiveSAudit.area.ilike(term), FiveSAudit.department.ilike(term)))
    if status in STATUSES: query = query.filter_by(status=status)
    audits = query.order_by(FiveSAudit.planned_date.desc(), FiveSAudit.id.desc()).all()
    completed = [row.score_percent for row in audits if row.score_percent is not None]
    return render_template("five_s/dashboard.html", audits=audits, status_labels=STATUSES, search=search, selected_status=status, archived=archived, today=date.today(), average_score=(sum(completed) / len(completed) if completed else None), can_create=has_permission("five_s.create") or has_permission("five_s.manage"), can_manage=has_permission("five_s.manage"))


@bp.route("/yeni", methods=["GET", "POST"])
@login_required
def create():
    require_permission("five_s.create", "five_s.manage")
    if request.method == "POST":
        try:
            title, area = request.form.get("title", "").strip(), request.form.get("area", "").strip()
            if not title or not area: raise ValueError("Denetim adı ve saha/alan zorunludur.")
            auditor_id, reviewer_id = parse_user("auditor_user_id"), parse_user("reviewer_user_id")
            if auditor_id == reviewer_id: raise ValueError("Denetçi ve inceleyen farklı kişiler olmalıdır.")
            audit = FiveSAudit(company_id=current_company_id(), audit_no=next_audit_no(), title=title, area=area, department=request.form.get("department", "").strip() or None, auditor_user_id=auditor_id, reviewer_user_id=reviewer_id, planned_date=parse_date("planned_date", True), due_date=parse_date("due_date"), summary=request.form.get("summary", "").strip() or None, created_by_user_id=g.current_user.id)
            db.session.add(audit); db.session.flush(); order = 0
            for category, _, criteria in CATEGORIES:
                for criterion in criteria:
                    order += 1; db.session.add(FiveSAuditItem(company_id=audit.company_id, audit=audit, category=category, criterion=criterion, sort_order=order))
            store_file(request.files.get("attachment"), audit)
            notify(audit.auditor_user_id, audit, f"{audit.area} alanı için 5S denetimi atandı.", "assigned")
            db.session.commit(); flash(f"{audit.audit_no} 5S denetimi oluşturuldu.", "success")
            return redirect(url_for("five_s.detail", audit_id=audit.id))
        except ValueError as error:
            db.session.rollback(); flash(str(error), "danger")
    return render_template("five_s/form.html", values=request.form, users=active_users(), today=date.today().isoformat())


@bp.get("/<int:audit_id>")
@login_required
def detail(audit_id):
    require_permission("five_s.view", "five_s.view_all", "five_s.manage")
    audit = get_audit_or_404(audit_id)
    category_scores = []
    for category, label, _ in CATEGORIES:
        items = [item for item in audit.items if item.category == category and item.score is not None]
        category_scores.append((category, label, round(sum(item.score for item in items) / (len(items) * 5) * 100, 1) if items else None))
    return render_template("five_s/detail.html", audit=audit, category_scores=category_scores, status_labels=STATUSES, can_perform=(has_permission("five_s.perform") or has_permission("five_s.manage")) and (audit.auditor_user_id == g.current_user.id or has_permission("five_s.manage")), can_review=(has_permission("five_s.review") or has_permission("five_s.manage")) and (audit.reviewer_user_id == g.current_user.id or has_permission("five_s.manage")), can_resolve=has_permission("five_s.resolve") or has_permission("five_s.manage"), can_archive=has_permission("five_s.archive") or has_permission("five_s.manage"), can_download=has_permission("five_s.file_download") or has_permission("five_s.manage"))


@bp.route("/<int:audit_id>/uygula", methods=["GET", "POST"])
@login_required
def perform(audit_id):
    require_permission("five_s.perform", "five_s.manage")
    audit = get_audit_or_404(audit_id)
    if audit.auditor_user_id != g.current_user.id and not has_permission("five_s.manage"): abort(403)
    if audit.status not in {"planned", "in_progress", "correction_pending"}: abort(409)
    if request.method == "POST":
        submit = request.form.get("intent") == "submit"
        try:
            scores = []
            valid_users = {user.id for user in active_users()}
            for item in audit.items:
                raw = request.form.get(f"score_{item.id}", "").strip()
                if not raw:
                    item.score = None
                    if submit: raise ValueError("Göndermeden önce tüm kriterleri puanlayın.")
                    continue
                try: score = int(raw)
                except ValueError: raise ValueError("Puanlar 0 ile 5 arasında olmalıdır.") from None
                if score not in range(6): raise ValueError("Puanlar 0 ile 5 arasında olmalıdır.")
                item.score, item.observation = score, request.form.get(f"observation_{item.id}", "").strip() or None; scores.append(score)
                responsible = request.form.get(f"responsible_{item.id}", "").strip()
                due = request.form.get(f"due_{item.id}", "").strip()
                if score < 3:
                    if not item.observation or not responsible or not due: raise ValueError("3 puanın altındaki kriterlerde açıklama, sorumlu ve termin zorunludur.")
                    if int(responsible) not in valid_users: raise ValueError("Bulgu sorumlusu bu şirkette aktif değil.")
                    item.responsible_user_id, item.due_date = int(responsible), date.fromisoformat(due)
                else:
                    item.responsible_user_id, item.due_date = None, None
            audit.score_percent = round(sum(scores) / (len(audit.items) * 5) * 100, 1) if scores else None
            audit.status = "review_pending" if submit else "in_progress"
            audit.submitted_at = datetime.now(UTC).replace(tzinfo=None) if submit else audit.submitted_at
            store_file(request.files.get("attachment"), audit)
            if submit:
                notify(audit.reviewer_user_id, audit, "5S denetimi incelemenizi bekliyor.", "review")
                for item in audit.items:
                    if item.responsible_user_id: notify(item.responsible_user_id, audit, f"5S bulgusu atandı: {item.criterion}", f"finding-{item.id}")
            db.session.commit(); flash("Denetim incelemeye gönderildi." if submit else "5S taslağı kaydedildi.", "success")
            return redirect(url_for("five_s.detail", audit_id=audit.id))
        except (ValueError, TypeError) as error:
            db.session.rollback(); flash(str(error) or "Denetim bilgilerini kontrol edin.", "danger")
    return render_template("five_s/perform.html", audit=audit, categories=CATEGORIES, users=active_users())


@bp.post("/<int:audit_id>/incele")
@login_required
def review(audit_id):
    require_permission("five_s.review", "five_s.manage")
    audit = get_audit_or_404(audit_id)
    if audit.reviewer_user_id != g.current_user.id and not has_permission("five_s.manage"): abort(403)
    if audit.status != "review_pending": abort(409)
    decision, note = request.form.get("decision", ""), request.form.get("review_note", "").strip()
    if decision == "return":
        if not note: flash("Düzeltme nedeni zorunludur.", "danger"); return redirect(url_for("five_s.detail", audit_id=audit.id))
        audit.status = "correction_pending"; notify(audit.auditor_user_id, audit, "Denetim düzeltme için iade edildi.", "returned")
    elif decision == "approve":
        audit.status = "completed"; audit.completed_at = datetime.now(UTC).replace(tzinfo=None)
    else: abort(400)
    audit.review_note, audit.reviewed_at = note or None, datetime.now(UTC).replace(tzinfo=None)
    db.session.commit(); flash("İnceleme kararı kaydedildi.", "success")
    return redirect(url_for("five_s.detail", audit_id=audit.id))


@bp.post("/bulgu/<int:item_id>/kapat")
@login_required
def resolve_item(item_id):
    require_permission("five_s.resolve", "five_s.manage")
    item = scoped_query(FiveSAuditItem.query, FiveSAuditItem).filter_by(id=item_id).first_or_404(); audit = get_audit_or_404(item.audit_id)
    if item.responsible_user_id != g.current_user.id and not has_permission("five_s.manage"): abort(403)
    note = request.form.get("resolution_note", "").strip()
    if not note: flash("Kapatma açıklaması zorunludur.", "danger"); return redirect(url_for("five_s.detail", audit_id=audit.id))
    item.is_resolved, item.resolution_note, item.resolved_at = True, note, datetime.now(UTC).replace(tzinfo=None)
    store_file(request.files.get("attachment"), audit, item); db.session.commit(); flash("5S bulgusu kapatıldı.", "success")
    return redirect(url_for("five_s.detail", audit_id=audit.id))


@bp.post("/<int:audit_id>/arsivle")
@login_required
def archive(audit_id):
    require_permission("five_s.archive", "five_s.manage")
    audit = get_audit_or_404(audit_id)
    if audit.status != "completed" or audit.open_finding_count: flash("Arşiv için denetim tamamlanmalı ve tüm bulgular kapatılmalıdır.", "danger"); return redirect(url_for("five_s.detail", audit_id=audit.id))
    audit.status, audit.archived_at = "archived", datetime.now(UTC).replace(tzinfo=None); db.session.commit(); flash("5S denetimi arşivlendi.", "success")
    return redirect(url_for("five_s.dashboard", archived="archived"))


@bp.get("/dosya/<int:file_id>")
@login_required
def download_file(file_id):
    require_permission("five_s.file_download", "five_s.manage")
    row = file_query().filter_by(id=file_id).first_or_404()
    if not can_access(row.audit): abort(404)
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve(); path = (root / row.stored_path).resolve()
    try: path.relative_to(root)
    except ValueError: abort(404)
    if not path.is_file(): abort(404)
    return send_file(path, as_attachment=True, download_name=row.original_name)


def assigned_task_rows(scope, row_builder):
    if not module_enabled(): return []
    query = audit_query().filter(FiveSAudit.archived_at.is_(None), FiveSAudit.status != "archived")
    if scope == "created": query = query.filter_by(created_by_user_id=g.current_user.id)
    else:
        findings = db.session.query(FiveSAuditItem.audit_id).filter_by(company_id=current_company_id(), responsible_user_id=g.current_user.id, is_resolved=False)
        query = query.filter(or_(FiveSAudit.auditor_user_id == g.current_user.id, FiveSAudit.reviewer_user_id == g.current_user.id, FiveSAudit.id.in_(findings)))
    rows = []
    for audit in query.all():
        if audit.status in {"completed", "archived"} and not audit.open_finding_count: continue
        due = min([value for value in [audit.due_date, *[item.due_date for item in audit.items if item.responsible_user_id == g.current_user.id and not item.is_resolved]] if value], default=audit.planned_date)
        delayed = bool(due and due < date.today())
        rows.append(row_builder(module_key="five_s", module_label="5S Denetimi", module_icon="grid-3x3-gap", module_tone="quality", title=audit.title, description=f"{audit.area} · {audit.department or '-'}", reference_no=audit.audit_no, department=audit.department or "5S", due_date=due, status="Termin Geçti" if delayed else STATUSES.get(audit.status, audit.status), status_key="delayed" if delayed else "pending", priority="Yüksek" if delayed or audit.open_finding_count else "Orta", detail_url=url_for("five_s.detail", audit_id=audit.id), created_at=audit.created_at, sort_id=audit.id, date_label="Termin"))
    return rows
