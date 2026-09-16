from datetime import UTC, date, datetime
from functools import wraps
import hashlib
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_

from .extensions import db
from .models import Action, Dof, KaizenProject, ProblemSolvingCase, ProblemSolvingFile, ProblemSolvingStep, ProblemSolvingTeamMember, RiskRecord, User
from .notifications import add_user_notification
from .tenant import current_company_id, scoped_query

bp = Blueprint("problem_solving", __name__, url_prefix="/problem-cozme")
METHODS = ("A3", "8D")
PRIORITIES = ("Düşük", "Orta", "Yüksek", "Kritik")
STATUSES = ("Açık", "Devam Ediyor", "İnceleme Bekliyor", "Tamamlandı", "İptal", "Arşiv")
STEP_TEMPLATES = {
    "A3": (
        ("A1", "Arka Plan ve Problem", "Problemi, iş etkisini ve mevcut durumu verilerle tanımlayın."),
        ("A2", "Hedef Durum", "Ölçülebilir hedefi ve başarı ölçütünü belirleyin."),
        ("A3", "Kök Neden Analizi", "5 Neden, balık kılçığı veya veriye dayalı yöntemle kök nedeni doğrulayın."),
        ("A4", "Karşı Önlemler", "Kök nedenleri ortadan kaldıracak çözüm seçeneklerini belirleyin."),
        ("A5", "Uygulama Planı", "Sorumlu, termin, kaynak ve takip noktalarını tanımlayın."),
        ("A6", "Sonuç ve Etkinlik", "Önce/sonra verileriyle etkinliği doğrulayın."),
        ("A7", "Standartlaştırma", "Öğrenilenleri süreç, doküman ve eğitimlere aktarın."),
    ),
    "8D": (
        ("D1", "Ekip Oluşturma", "Yetkin, çapraz fonksiyonlu ekip ve rolleri tanımlayın."),
        ("D2", "Problemi Tanımlama", "Kim, ne, nerede, ne zaman, neden ve nasıl sorularıyla problemi sınırlandırın."),
        ("D3", "Geçici Önlem", "Müşteri ve prosesi koruyacak geçici kontrolü uygulayın ve doğrulayın."),
        ("D4", "Kök Neden", "Oluşum ve kaçış kök nedenlerini kanıtlarla doğrulayın."),
        ("D5", "Kalıcı Düzeltici Faaliyet", "Kök nedeni gideren çözümü seçin ve riskini değerlendirin."),
        ("D6", "Uygulama ve Doğrulama", "Kalıcı çözümü uygulayın, sonuçlarını ölçün."),
        ("D7", "Tekrarı Önleme", "Benzer süreçlere yayılımı ve sistem güncellemelerini tamamlayın."),
        ("D8", "Kapanış ve Takdir", "Sonuçları belgeleyin, ekibi ve öğrenilen dersleri kaydedin."),
    ),
}
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "jpg", "jpeg", "png"}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None: return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def has_permission(key): return bool(getattr(g, "current_user", None) and g.current_user.has_permission(key))
def require_permission(*keys):
    if not any(has_permission(key) for key in keys): abort(403)
def module_enabled():
    checker = getattr(g, "company_module_enabled", None); return checker("problem_solving") if checker else True
def case_query(): return scoped_query(ProblemSolvingCase.query, ProblemSolvingCase)
def active_users(): return User.query.filter_by(company_id=current_company_id(), is_active=True).order_by(User.full_name).all()


def can_access(case):
    uid = g.current_user.id
    return bool(has_permission("problem_solving.view_all") or has_permission("problem_solving.manage") or case.created_by_user_id == uid or case.leader_user_id == uid or case.reviewer_user_id == uid or any(row.user_id == uid for row in case.team_members))


def get_case_or_404(case_id):
    case = case_query().filter_by(id=case_id).first_or_404()
    if not can_access(case): abort(404)
    return case


def parse_date(name, required=False):
    raw = request.form.get(name, "").strip()
    if not raw:
        if required: raise ValueError("Açılış tarihi zorunludur.")
        return None
    try: return date.fromisoformat(raw)
    except ValueError: raise ValueError("Tarih bilgisini kontrol edin.") from None


def parse_user(name):
    try: uid = int(request.form.get(name, ""))
    except ValueError: raise ValueError("Aktif bir personel seçin.") from None
    if not User.query.filter_by(id=uid, company_id=current_company_id(), is_active=True).first(): raise ValueError("Seçilen personel bu şirkette aktif değil.")
    return uid


def team_ids():
    valid = {u.id for u in active_users()}
    try: chosen = {int(v) for v in request.form.getlist("team_user_ids")}
    except ValueError: raise ValueError("Ekip seçimini kontrol edin.") from None
    if not chosen.issubset(valid): raise ValueError("Ekipte yalnızca aktif şirket personeli seçilebilir.")
    return chosen


def optional_id(name, model):
    raw = request.form.get(name, "").strip()
    if not raw: return None
    try: row_id = int(raw)
    except ValueError: raise ValueError("Bağlantılı kayıt geçersiz.") from None
    if not scoped_query(model.query, model).filter_by(id=row_id).first(): raise ValueError("Bağlantılı kayıt bu şirkete ait değil.")
    return row_id


def next_case_no(method):
    prefix = f"{method}-{date.today().year}-"; nums = []
    for (value,) in case_query().with_entities(ProblemSolvingCase.case_no).filter(ProblemSolvingCase.case_no.like(f"{prefix}%")).all():
        try: nums.append(int(value.rsplit("-", 1)[-1]))
        except (TypeError, ValueError): pass
    return f"{prefix}{max(nums, default=0) + 1:04d}"


def sync_team(case, selected):
    existing = {row.user_id: row for row in case.team_members}
    for uid in set(existing) - selected: db.session.delete(existing[uid])
    for uid in selected - set(existing): db.session.add(ProblemSolvingTeamMember(company_id=case.company_id, case=case, user_id=uid))


def store_file(upload, case, step=None):
    if not upload or not upload.filename: return
    extension = Path(upload.filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS: raise ValueError("Yalnızca PDF, Word, Excel, CSV, metin veya görsel yükleyin.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size
    original = safe_original_filename(upload.filename, "problem-cozme-kaniti")
    relative, absolute = upload_storage_path(f"{uuid4().hex}.{extension}", "problem-solving", case.company_id)
    assert_company_storage_quota(case.company_id, uploaded_stream_size(upload)); upload.save(absolute)
    db.session.add(ProblemSolvingFile(company_id=case.company_id, case=case, step=step, original_name=original, stored_path=str(relative).replace("\\", "/"), mime_type=upload.mimetype, file_size=absolute.stat().st_size, sha256_hash=hashlib.sha256(absolute.read_bytes()).hexdigest(), uploaded_by_user_id=g.current_user.id))


def notify(uid, case, text, suffix):
    user = User.query.filter_by(id=uid, company_id=case.company_id, is_active=True).first()
    if user: add_user_notification(user, f"{case.case_no} - {text}", company_id=case.company_id, source_key=f"problem-solving:{suffix}:{case.id}:{uid}", target_url=url_for("problem_solving.detail", case_id=case.id), due_date=case.target_date)


def context(case=None):
    return {"case": case, "values": request.form, "users": active_users(), "methods": METHODS, "priorities": PRIORITIES, "today": date.today().isoformat(), "selected_team": {int(v) for v in request.form.getlist("team_user_ids") if v.isdigit()} if request.form else ({m.user_id for m in case.team_members} if case else set()), "dofs": scoped_query(Dof.query,Dof).order_by(Dof.id.desc()).all(), "actions": scoped_query(Action.query,Action).order_by(Action.id.desc()).all(), "risks": scoped_query(RiskRecord.query,RiskRecord).order_by(RiskRecord.id.desc()).all(), "kaizens": scoped_query(KaizenProject.query,KaizenProject).order_by(KaizenProject.id.desc()).all()}


@bp.before_request
def guard():
    if not module_enabled(): abort(404)


@bp.get("")
@login_required
def dashboard():
    require_permission("problem_solving.view", "problem_solving.view_all", "problem_solving.manage")
    query = case_query()
    if not (has_permission("problem_solving.view_all") or has_permission("problem_solving.manage")):
        memberships = db.session.query(ProblemSolvingTeamMember.case_id).filter_by(company_id=current_company_id(), user_id=g.current_user.id)
        query = query.filter(or_(ProblemSolvingCase.created_by_user_id == g.current_user.id, ProblemSolvingCase.leader_user_id == g.current_user.id, ProblemSolvingCase.reviewer_user_id == g.current_user.id, ProblemSolvingCase.id.in_(memberships)))
    q, method, status = (request.args.get(k, "").strip() for k in ("q", "method", "status")); archived = request.args.get("archived", "active") == "archived"
    query = query.filter(ProblemSolvingCase.archived_at.is_not(None) if archived else ProblemSolvingCase.archived_at.is_(None))
    if q:
        term=f"%{q}%"; query=query.filter(or_(ProblemSolvingCase.case_no.ilike(term),ProblemSolvingCase.title.ilike(term),ProblemSolvingCase.department.ilike(term)))
    if method in METHODS: query=query.filter_by(method=method)
    if status in STATUSES: query=query.filter_by(status=status)
    return render_template("problem_solving/dashboard.html", cases=query.order_by(ProblemSolvingCase.target_date.asc(),ProblemSolvingCase.id.desc()).all(), methods=METHODS, statuses=STATUSES, search=q, selected_method=method, selected_status=status, archived=archived, today=date.today(), can_create=has_permission("problem_solving.create") or has_permission("problem_solving.manage"))


@bp.route("/yeni", methods=["GET","POST"])
@login_required
def create():
    require_permission("problem_solving.create", "problem_solving.manage")
    if request.method == "POST":
        try:
            method=request.form.get("method","").strip(); title=request.form.get("title","").strip(); problem=request.form.get("problem_statement","").strip(); leader=parse_user("leader_user_id"); reviewer=parse_user("reviewer_user_id")
            if method not in METHODS or not title or not problem: raise ValueError("Yöntem, başlık ve problem tanımı zorunludur.")
            if leader == reviewer: raise ValueError("Problem lideri ve inceleyen farklı kişiler olmalıdır.")
            priority=request.form.get("priority","Orta").strip()
            if priority not in PRIORITIES: raise ValueError("Öncelik geçersiz.")
            case=ProblemSolvingCase(company_id=current_company_id(),case_no=next_case_no(method),method=method,title=title,department=request.form.get("department","").strip() or None,leader_user_id=leader,reviewer_user_id=reviewer,priority=priority,opened_date=parse_date("opened_date",True),target_date=parse_date("target_date"),problem_statement=problem,impact=request.form.get("impact","").strip() or None,dof_id=optional_id("dof_id",Dof),action_id=optional_id("action_id",Action),risk_id=optional_id("risk_id",RiskRecord),kaizen_project_id=optional_id("kaizen_project_id",KaizenProject),created_by_user_id=g.current_user.id)
            db.session.add(case); db.session.flush(); selected=team_ids() | {leader}; sync_team(case,selected)
            for order,(key,step_title,guidance) in enumerate(STEP_TEMPLATES[method],1): db.session.add(ProblemSolvingStep(company_id=case.company_id,case=case,step_order=order,step_key=key,title=step_title,guidance=guidance,status="Devam Ediyor" if order==1 else "Bekliyor",owner_user_id=leader,due_date=case.target_date))
            store_file(request.files.get("attachment"),case)
            for uid in selected | {reviewer}: notify(uid,case,"Problem çözme vakasında görevlendirildiniz.",f"assignment-{uid}")
            db.session.commit(); flash(f"{case.case_no} problem çözme vakası oluşturuldu.","success"); return redirect(url_for("problem_solving.detail",case_id=case.id))
        except ValueError as error: db.session.rollback(); flash(str(error),"danger")
    return render_template("problem_solving/form.html",**context())


@bp.get("/<int:case_id>")
@login_required
def detail(case_id):
    require_permission("problem_solving.view", "problem_solving.view_all", "problem_solving.manage")
    case=get_case_or_404(case_id); current=next((s for s in case.steps if s.step_order==case.current_step),None)
    return render_template("problem_solving/detail.html",case=case,current_step=current,statuses=STATUSES,can_update=(has_permission("problem_solving.update") or has_permission("problem_solving.manage")) and (case.leader_user_id==g.current_user.id or any(m.user_id==g.current_user.id for m in case.team_members) or has_permission("problem_solving.manage")),can_review=(has_permission("problem_solving.review") or has_permission("problem_solving.manage")) and (case.reviewer_user_id==g.current_user.id or has_permission("problem_solving.manage")),can_archive=has_permission("problem_solving.archive") or has_permission("problem_solving.manage"),can_download=has_permission("problem_solving.file_download") or has_permission("problem_solving.manage"))


@bp.post("/<int:case_id>/asama")
@login_required
def update_step(case_id):
    require_permission("problem_solving.update", "problem_solving.manage")
    case=get_case_or_404(case_id)
    if case.status in {"Tamamlandı","İptal","Arşiv"}: abort(409)
    if case.leader_user_id != g.current_user.id and not any(m.user_id==g.current_user.id for m in case.team_members) and not has_permission("problem_solving.manage"): abort(403)
    step=next((s for s in case.steps if s.step_order==case.current_step),None)
    if not step: abort(409)
    content=request.form.get("content","").strip()
    if not content: flash("Aşama açıklaması zorunludur.","danger"); return redirect(url_for("problem_solving.detail",case_id=case.id))
    step.content=content; step.status="İnceleme Bekliyor"; step.submitted_at=datetime.now(UTC).replace(tzinfo=None); case.status="İnceleme Bekliyor"; store_file(request.files.get("attachment"),case,step); notify(case.reviewer_user_id,case,f"{step.step_key} aşaması incelemenizi bekliyor.",f"review-{step.id}"); db.session.commit(); flash("Aşama incelemeye gönderildi.","success"); return redirect(url_for("problem_solving.detail",case_id=case.id))


@bp.post("/<int:case_id>/incele")
@login_required
def review_step(case_id):
    require_permission("problem_solving.review", "problem_solving.manage")
    case=get_case_or_404(case_id)
    if case.reviewer_user_id != g.current_user.id and not has_permission("problem_solving.manage"): abort(403)
    step=next((s for s in case.steps if s.step_order==case.current_step),None)
    if not step or step.status!="İnceleme Bekliyor": abort(409)
    decision=request.form.get("decision"); note=request.form.get("review_note","").strip(); now=datetime.now(UTC).replace(tzinfo=None)
    if decision=="return":
        if not note: flash("İade açıklaması zorunludur.","danger"); return redirect(url_for("problem_solving.detail",case_id=case.id))
        step.status="Revizyon Bekliyor"; step.review_note=note; case.status="Devam Ediyor"; notify(case.leader_user_id,case,f"{step.step_key} aşaması revizyona gönderildi.",f"returned-{step.id}")
    elif decision=="approve":
        step.status="Onaylandı"; step.review_note=note or None; step.approved_at=now; step.approved_by_user_id=g.current_user.id
        if case.current_step >= len(case.steps): case.status="Tamamlandı"; case.completed_at=now
        else:
            case.current_step += 1; case.status="Devam Ediyor"; next_step=next(s for s in case.steps if s.step_order==case.current_step); next_step.status="Devam Ediyor"; notify(case.leader_user_id,case,f"{next_step.step_key} aşaması başladı.",f"step-{next_step.id}")
    else: abort(400)
    db.session.commit(); flash("Aşama kararı kaydedildi.","success"); return redirect(url_for("problem_solving.detail",case_id=case.id))


@bp.post("/<int:case_id>/arsivle")
@login_required
def archive(case_id):
    require_permission("problem_solving.archive", "problem_solving.manage"); case=get_case_or_404(case_id)
    if case.status not in {"Tamamlandı","İptal"}: flash("Yalnızca tamamlanan veya iptal edilen vaka arşivlenebilir.","danger"); return redirect(url_for("problem_solving.detail",case_id=case.id))
    case.status="Arşiv"; case.archived_at=datetime.now(UTC).replace(tzinfo=None); db.session.commit(); flash("Problem çözme vakası arşivlendi.","success"); return redirect(url_for("problem_solving.dashboard",archived="archived"))


@bp.get("/dosya/<int:file_id>")
@login_required
def download_file(file_id):
    require_permission("problem_solving.file_download", "problem_solving.manage")
    row=scoped_query(ProblemSolvingFile.query,ProblemSolvingFile).filter_by(id=file_id).first_or_404()
    if not can_access(row.case): abort(404)
    root=Path(current_app.config["UPLOAD_FOLDER"]).resolve(); path=(root/row.stored_path).resolve()
    try: path.relative_to(root)
    except ValueError: abort(404)
    if not path.is_file(): abort(404)
    return send_file(path,as_attachment=True,download_name=row.original_name)


def assigned_task_rows(scope,row_builder):
    if not module_enabled(): return []
    query=case_query().filter(ProblemSolvingCase.archived_at.is_(None),~ProblemSolvingCase.status.in_(("Tamamlandı","İptal","Arşiv")))
    if scope=="created": query=query.filter_by(created_by_user_id=g.current_user.id)
    else:
        memberships=db.session.query(ProblemSolvingTeamMember.case_id).filter_by(company_id=current_company_id(),user_id=g.current_user.id)
        query=query.filter(or_(ProblemSolvingCase.leader_user_id==g.current_user.id,ProblemSolvingCase.reviewer_user_id==g.current_user.id,ProblemSolvingCase.id.in_(memberships)))
    rows=[]
    for case in query.all():
        delayed=bool(case.target_date and case.target_date<date.today())
        step=next((s for s in case.steps if s.step_order==case.current_step),None)
        rows.append(row_builder(module_key="problem_solving",module_label=f"{case.method} Problem Çözme",module_icon="diagram-2",module_tone="quality",title=case.title,description=f"{step.step_key + ' · ' + step.title if step else case.problem_statement}",reference_no=case.case_no,department=case.department or "Kalite",due_date=case.target_date or case.opened_date,status="Termin Geçti" if delayed else case.status,status_key="delayed" if delayed else "pending",priority="Yüksek" if delayed else case.priority,detail_url=url_for("problem_solving.detail",case_id=case.id),created_at=case.created_at,sort_id=case.id,date_label="Hedef"))
    return rows
