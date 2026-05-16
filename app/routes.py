from datetime import date, datetime
from functools import wraps
from pathlib import Path
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
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename
from sqlalchemy import or_

from .extensions import db
from .mail import send_action_completed_email, send_action_created_email
from .models import Action, ActionComment, DEPARTMENTS, User


bp = Blueprint("main", __name__)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx"}


@bp.app_errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.current_user = User.query.get(user_id) if user_id else None


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for("main.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped_view


def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if g.current_user is None:
                return redirect(url_for("main.login", next=request.full_path))
            if not getattr(g.current_user, permission, False):
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def is_assigned_to_current_user(action):
    return (
        g.current_user is not None
        and action.responsible_user_id is not None
        and action.responsible_user_id == g.current_user.id
    )


def can_complete_action(action):
    if g.current_user is None:
        return False
    return g.current_user.can_edit_actions or (
        g.current_user.can_close_assigned_actions and is_assigned_to_current_user(action)
    )


def can_comment_action(action):
    if g.current_user is None:
        return False
    return g.current_user.can_edit_actions or (
        g.current_user.can_comment_assigned_actions and is_assigned_to_current_user(action)
    )


def can_reassign_action(action):
    if g.current_user is None:
        return False
    return g.current_user.can_edit_actions or (
        g.current_user.can_close_assigned_actions and is_assigned_to_current_user(action)
    )


def can_view_action(action):
    if g.current_user is None:
        return False
    return (
        g.current_user.can_create_actions
        or g.current_user.can_edit_actions
        or g.current_user.can_delete_actions
        or is_assigned_to_current_user(action)
    )


def visible_actions_query():
    query = Action.query
    if (
        g.current_user.can_create_actions
        or g.current_user.can_edit_actions
        or g.current_user.can_delete_actions
    ):
        return query
    return query.filter(Action.responsible_user_id == g.current_user.id)


def active_users():
    return User.query.filter_by(is_active=True).order_by(User.full_name.asc()).all()


def dashboard_filters():
    return {
        "search": request.args.get("search", "").strip(),
        "department": request.args.get("department", "").strip(),
        "responsible_user_id": request.args.get("responsible_user_id", "").strip(),
        "status": request.args.get("status", "").strip(),
    }


def filtered_actions(actions, filters):
    search = filters["search"].lower()
    department = filters["department"]
    responsible_user_id = filters["responsible_user_id"]
    status = filters["status"]

    if responsible_user_id:
        try:
            responsible_user_id = int(responsible_user_id)
        except ValueError:
            responsible_user_id = None

    result = []
    for action in actions:
        if search and search not in " ".join(
            [
                action.title or "",
                action.description or "",
                action.responsible_owner or "",
                action.department or "",
            ]
        ).lower():
            continue
        if department and action.department != department:
            continue
        if responsible_user_id and action.responsible_user_id != responsible_user_id:
            continue
        if status == "open" and (action.is_completed or action.delay_days > 0):
            continue
        if status == "delayed" and (action.is_completed or action.delay_days == 0):
            continue
        if status == "completed" and not action.is_completed:
            continue
        result.append(action)

    return result


def delete_uploaded_file(action):
    if not action.file_stored_name:
        return

    file_path = Path(current_app.config["UPLOAD_FOLDER"]) / action.file_stored_name
    if file_path.exists():
        file_path.unlink()

    action.file_original_name = None
    action.file_stored_name = None
    action.file_mime_type = None


def save_uploaded_file(action):
    uploaded_file = request.files.get("action_file")
    if not uploaded_file or not uploaded_file.filename:
        return

    if not allowed_file(uploaded_file.filename):
        raise ValueError("invalid_file_type")

    safe_name = secure_filename(uploaded_file.filename)
    extension = safe_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid4().hex}.{extension}"
    upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / stored_name

    delete_uploaded_file(action)
    uploaded_file.save(upload_path)

    action.file_original_name = safe_name
    action.file_stored_name = stored_name
    action.file_mime_type = uploaded_file.mimetype


def refresh_all_actions():
    actions = visible_actions_query().order_by(Action.termin_date.asc(), Action.id.asc()).all()
    changed = False
    for action in actions:
        old_delay_days = action.delay_days
        action.refresh_delay()
        changed = changed or old_delay_days != action.delay_days

    if changed:
        db.session.commit()

    return actions


def parse_action_form(action=None):
    action = action or Action()
    title = request.form.get("title", "").strip()
    responsible_user_id = request.form.get("responsible_user_id", "").strip()
    department = request.form.get("department", "").strip()

    if not title or not responsible_user_id or not department:
        raise ValueError("required_fields")
    if department not in DEPARTMENTS:
        raise ValueError("invalid_department")

    try:
        responsible_user_id = int(responsible_user_id)
    except ValueError:
        raise ValueError("invalid_user") from None

    responsible_user = User.query.filter_by(
        id=responsible_user_id, is_active=True
    ).first()
    if responsible_user is None:
        raise ValueError("invalid_user")

    action.title = title
    action.responsible_user_id = responsible_user.id
    action.responsible_owner = responsible_user.full_name
    action.department = department
    action.description = request.form.get("description", "").strip()

    termin_value = request.form.get("termin_date", "")
    action.termin_date = datetime.strptime(termin_value, "%Y-%m-%d").date()
    action.refresh_delay()
    save_uploaded_file(action)
    return action


def flash_mail_result(sent, recipient):
    if sent:
        flash(f"Bilgilendirme maili gönderildi: {recipient}", "success")
    elif recipient:
        flash("Mail gönderilemedi. Resend veya SMTP ayarlarını kontrol edin.", "warning")
    else:
        flash("Aksiyon sorumlusunun e-posta adresi olmadığı için mail gönderilmedi.", "warning")


def parse_user_form(user=None):
    user = user or User()
    username = request.form.get("username", "").strip().lower()
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "")

    if not username or not full_name:
        raise ValueError("required_fields")
    if user.id is None and not password:
        raise ValueError("password_required")

    existing_user = User.query.filter(User.username == username, User.id != user.id).first()
    if existing_user:
        raise ValueError("username_exists")

    user.username = username
    user.full_name = full_name
    user.title = request.form.get("title", "").strip()
    user.email = request.form.get("email", "").strip() or None
    user.is_active = request.form.get("is_active") == "on"
    user.can_create_actions = request.form.get("can_create_actions") == "on"
    user.can_edit_actions = request.form.get("can_edit_actions") == "on"
    user.can_delete_actions = request.form.get("can_delete_actions") == "on"
    user.can_comment_assigned_actions = (
        request.form.get("can_comment_assigned_actions") == "on"
    )
    user.can_close_assigned_actions = request.form.get("can_close_assigned_actions") == "on"
    user.can_manage_users = request.form.get("can_manage_users") == "on"

    if password:
        user.set_password(password)

    return user


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user is not None:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(
            or_(
                db.func.lower(User.username) == identity,
                db.func.lower(User.full_name) == identity,
            )
        ).first()

        if user and user.is_active and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            flash("Giriş başarılı.", "success")
            next_url = request.args.get("next") or url_for("main.dashboard")
            return redirect(next_url)

        flash("Kullanıcı adı veya şifre hatalı.", "danger")

    return render_template("login.html")


@bp.get("/logout")
def logout():
    session.clear()
    flash("Çıkış yapıldı.", "success")
    return redirect(url_for("main.login"))


@bp.route("/")
@login_required
def dashboard():
    all_actions = refresh_all_actions()
    filters = dashboard_filters()
    actions = filtered_actions(all_actions, filters)
    delayed_count = sum(
        1 for action in all_actions if not action.is_completed and action.delay_days > 0
    )
    completed_count = sum(1 for action in all_actions if action.is_completed)
    total_count = len(all_actions)

    return render_template(
        "dashboard.html",
        actions=actions,
        delayed_count=delayed_count,
        completed_count=completed_count,
        total_count=total_count,
        can_complete_action=can_complete_action,
        departments=DEPARTMENTS,
        filters=filters,
        users=active_users(),
    )


@bp.route("/actions/new", methods=["GET", "POST"])
@login_required
@permission_required("can_create_actions")
def create_action():
    if request.method == "POST":
        try:
            action = parse_action_form()
            db.session.add(action)
            db.session.commit()
            try:
                sent = send_action_created_email(action)
                flash_mail_result(
                    sent,
                    action.responsible_user.email if action.responsible_user else None,
                )
            except Exception as error:
                current_app.logger.exception("Aksiyon açılış maili gönderilemedi.")
                flash(f"Mail gönderilemedi: {error}", "warning")
            flash("Aksiyon kaydı başarıyla eklendi.", "success")
            return redirect(url_for("main.dashboard"))
        except ValueError as error:
            if str(error) == "invalid_file_type":
                flash("Sadece PDF, Word veya Excel dosyası yükleyebilirsiniz.", "danger")
            else:
                flash("Lütfen form alanlarını geçerli biçimde doldurun.", "danger")

    return render_template(
        "action_form.html",
        action=None,
        users=active_users(),
        departments=DEPARTMENTS,
        today=date.today().isoformat(),
        title="Yeni Aksiyon",
    )


@bp.route("/actions/<int:action_id>")
@login_required
def action_detail(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_view_action(action):
        abort(403)

    return render_template(
        "action_detail.html",
        action=action,
        users=active_users(),
        can_complete=can_complete_action(action),
        can_comment=can_comment_action(action),
        can_reassign=can_reassign_action(action),
    )


@bp.post("/actions/<int:action_id>/reassign")
@login_required
def reassign_action(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_reassign_action(action):
        abort(403)

    responsible_user_id = request.form.get("responsible_user_id", "").strip()
    try:
        responsible_user_id = int(responsible_user_id)
    except ValueError:
        flash("Lütfen geçerli bir aksiyon sorumlusu seçin.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    responsible_user = User.query.filter_by(
        id=responsible_user_id, is_active=True
    ).first()
    if responsible_user is None:
        flash("Seçilen kullanıcı bulunamadı.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.responsible_user_id = responsible_user.id
    action.responsible_owner = responsible_user.full_name
    db.session.commit()
    flash("Aksiyon sorumlusu güncellendi.", "success")

    if can_view_action(action):
        return redirect(url_for("main.action_detail", action_id=action.id))
    return redirect(url_for("main.dashboard"))


@bp.post("/actions/<int:action_id>/comments")
@login_required
def add_action_comment(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_comment_action(action):
        abort(403)

    comment_text = request.form.get("comment", "").strip()
    if not comment_text:
        flash("Yorum alanı boş bırakılamaz.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    comment = ActionComment(
        action_id=action.id,
        user_id=g.current_user.id,
        comment=comment_text,
    )
    db.session.add(comment)
    db.session.commit()
    flash("Yorum eklendi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.route("/actions/<int:action_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("can_edit_actions")
def edit_action(action_id):
    action = Action.query.get_or_404(action_id)

    if request.method == "POST":
        try:
            parse_action_form(action)
            db.session.commit()
            flash("Aksiyon kaydı güncellendi.", "success")
            return redirect(url_for("main.dashboard"))
        except ValueError as error:
            if str(error) == "invalid_file_type":
                flash("Sadece PDF, Word veya Excel dosyası yükleyebilirsiniz.", "danger")
            else:
                flash("Lütfen form alanlarını geçerli biçimde doldurun.", "danger")

    return render_template(
        "action_form.html",
        action=action,
        users=active_users(),
        departments=DEPARTMENTS,
        today=date.today().isoformat(),
        title="Aksiyon Düzenle",
    )


@bp.post("/actions/<int:action_id>/complete")
@login_required
def complete_action(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_complete_action(action):
        abort(403)

    closed_by = g.current_user
    action.mark_completed()
    db.session.commit()
    try:
        sent = send_action_completed_email(action, closed_by)
        flash_mail_result(
            sent,
            action.responsible_user.email if action.responsible_user else None,
        )
    except Exception as error:
        current_app.logger.exception("Aksiyon kapanış maili gönderilemedi.")
        flash(f"Mail gönderilemedi: {error}", "warning")
    flash("Aksiyon tamamlandı.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.route("/actions/<int:action_id>/delete", methods=["GET", "POST"])
@login_required
@permission_required("can_delete_actions")
def delete_action(action_id):
    action = Action.query.get_or_404(action_id)

    if request.method == "POST":
        delete_uploaded_file(action)
        db.session.delete(action)
        db.session.commit()
        flash("Aksiyon kaydı silindi.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("confirm_delete.html", action=action)


@bp.get("/actions/<int:action_id>/download")
@login_required
def download_action_file(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_view_action(action):
        abort(403)

    if not action.file_stored_name:
        flash("Bu kayda ait yüklenmiş dosya bulunamadı.", "warning")
        return redirect(url_for("main.dashboard"))

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        action.file_stored_name,
        as_attachment=True,
        download_name=action.file_original_name,
    )


@bp.route("/users")
@login_required
@permission_required("can_manage_users")
def users():
    user_list = User.query.order_by(User.full_name.asc()).all()
    return render_template("users.html", users=user_list)


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@permission_required("can_manage_users")
def create_user():
    if request.method == "POST":
        try:
            user = parse_user_form()
            db.session.add(user)
            db.session.commit()
            flash("Kullanıcı oluşturuldu.", "success")
            return redirect(url_for("main.users"))
        except ValueError as error:
            if str(error) == "username_exists":
                flash("Bu kullanıcı adı zaten kullanılıyor.", "danger")
            else:
                flash("Lütfen kullanıcı bilgilerini eksiksiz doldurun.", "danger")

    return render_template("user_form.html", user=None, title="Yeni Kullanıcı")


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("can_manage_users")
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        try:
            parse_user_form(user)
            db.session.commit()
            flash("Kullanıcı güncellendi.", "success")
            return redirect(url_for("main.users"))
        except ValueError as error:
            if str(error) == "username_exists":
                flash("Bu kullanıcı adı zaten kullanılıyor.", "danger")
            else:
                flash("Lütfen kullanıcı bilgilerini eksiksiz doldurun.", "danger")

    return render_template("user_form.html", user=user, title="Kullanıcı Düzenle")
