from datetime import date, datetime
from functools import wraps
from pathlib import Path
import re
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
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
from .mail import send_action_notification_email
from .models import (
    Action,
    ActionComment,
    ActionClosureFile,
    ActionHistory,
    AppSetting,
    DEPARTMENTS,
    Notification,
    ORGANIZATION_NODE_TYPES,
    OrientationNode,
    User,
)


bp = Blueprint("main", __name__)
HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
ALLOWED_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "jpg",
    "jpeg",
    "png",
    "webp",
}


@bp.app_errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.current_user = User.query.get(user_id) if user_id else None
    g.current_user_initials = ""
    g.unread_notification_count = 0
    g.latest_notifications = []
    if g.current_user is not None:
        g.current_user_initials = user_initials(g.current_user)
        notification_query = Notification.query.filter_by(user_id=g.current_user.id)
        g.unread_notification_count = notification_query.filter_by(is_read=False).count()
        g.latest_notifications = (
            notification_query.order_by(Notification.created_at.desc())
            .limit(5)
            .all()
        )


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


def is_related_to_current_user(action):
    return (
        g.current_user is not None
        and g.current_user.id
        in {action.related_user_1_id, action.related_user_2_id}
    )


def is_oguzhan_admin():
    return g.current_user is not None and g.current_user.username == "oguzhan"


def can_manage_orientation():
    return g.current_user is not None and (
        is_oguzhan_admin() or g.current_user.can_manage_users
    )


def can_complete_action(action):
    if g.current_user is None:
        return False
    return can_approve_closure_action(action)


def can_request_closure_action(action):
    if (
        g.current_user is None
        or is_oguzhan_admin()
        or action.is_completed
        or action.closure_approval_requested
    ):
        return False
    return (
        (
            g.current_user.can_close_assigned_actions
            and is_assigned_to_current_user(action)
        )
        or (
            g.current_user.can_comment_assigned_actions
            and is_related_to_current_user(action)
        )
    )


def can_approve_closure_action(action):
    return (
        is_oguzhan_admin()
        and not action.is_completed
        and action.closure_approval_requested
    )


def can_comment_action(action):
    if g.current_user is None:
        return False
    return is_oguzhan_admin() or (
        g.current_user.can_comment_assigned_actions
        and (is_assigned_to_current_user(action) or is_related_to_current_user(action))
    )


def can_reassign_action(action):
    if g.current_user is None:
        return False
    return is_oguzhan_admin() or (
        g.current_user.can_close_assigned_actions and is_assigned_to_current_user(action)
    )


def can_view_action(action):
    if g.current_user is None:
        return False
    return (
        is_oguzhan_admin()
        or is_assigned_to_current_user(action)
        or is_related_to_current_user(action)
    )


def can_revise_termin(action):
    if g.current_user is None or action.is_completed:
        return False
    return (
        is_oguzhan_admin()
        or is_assigned_to_current_user(action)
        or is_related_to_current_user(action)
    )


def visible_actions_query():
    query = Action.query
    if is_oguzhan_admin():
        return query
    return query.filter(
        or_(
            Action.responsible_user_id == g.current_user.id,
            Action.related_user_1_id == g.current_user.id,
            Action.related_user_2_id == g.current_user.id,
        )
    )


def active_users():
    return User.query.filter_by(is_active=True).order_by(User.full_name.asc()).all()


def user_initials(user):
    parts = (user.full_name or user.username or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def oguzhan_user():
    return User.query.filter_by(username="oguzhan", is_active=True).first()


def reserve_action_number():
    max_number = (
        db.session.query(db.func.max(db.func.coalesce(Action.action_number, Action.id)))
        .scalar()
        or 0
    )
    setting = db.session.get(AppSetting, "next_action_number")
    if setting is None:
        setting = AppSetting(key="next_action_number", value=str(max_number + 1))
        db.session.add(setting)

    next_number = int(setting.value)
    if next_number <= max_number:
        next_number = max_number + 1

    setting.value = str(next_number + 1)
    return next_number


def parse_optional_user(field_name):
    value = request.form.get(field_name, "").strip()
    if not value:
        return None

    try:
        user_id = int(value)
    except ValueError:
        raise ValueError("invalid_user") from None

    user = User.query.filter_by(id=user_id, is_active=True).first()
    if user is None:
        raise ValueError("invalid_user")
    return user


def user_name(user_id):
    if not user_id:
        return "-"
    user = User.query.get(user_id)
    return user.full_name if user else "-"


def format_date(value):
    return value.strftime("%d.%m.%Y") if value else "-"


def action_snapshot(action):
    return {
        "title": action.title,
        "responsible_user_id": action.responsible_user_id,
        "related_user_1_id": action.related_user_1_id,
        "related_user_2_id": action.related_user_2_id,
        "department": action.department,
        "description": action.description or "",
        "termin_date": action.termin_date,
        "file_original_name": action.file_original_name,
    }


def describe_action_changes(before, action):
    changes = []
    if before["title"] != action.title:
        changes.append(f"başlığı \"{before['title']}\" -> \"{action.title}\"")
    if before["responsible_user_id"] != action.responsible_user_id:
        changes.append(
            "sorumlusu "
            f"{user_name(before['responsible_user_id'])} -> {user_name(action.responsible_user_id)}"
        )
    if before["related_user_1_id"] != action.related_user_1_id:
        changes.append(
            "İlgili 1 "
            f"{user_name(before['related_user_1_id'])} -> {user_name(action.related_user_1_id)}"
        )
    if before["related_user_2_id"] != action.related_user_2_id:
        changes.append(
            "İlgili 2 "
            f"{user_name(before['related_user_2_id'])} -> {user_name(action.related_user_2_id)}"
        )
    if before["department"] != action.department:
        changes.append(f"departmanı {before['department']} -> {action.department}")
    if before["termin_date"] != action.termin_date:
        changes.append(
            f"termini {format_date(before['termin_date'])} -> {format_date(action.termin_date)}"
        )
    if before["description"] != (action.description or ""):
        changes.append("açıklaması güncellendi")
    if before["file_original_name"] != action.file_original_name:
        changes.append("dosyası güncellendi")
    return changes


def add_action_history(action, event_type, message, actor=None):
    history = ActionHistory(
        action=action,
        actor_user_id=actor.id if actor else None,
        event_type=event_type,
        message=message,
    )
    db.session.add(history)
    return history


def notify_users(user_ids, action, message, exclude_user_id=None):
    target_user_ids = {user_id for user_id in user_ids if user_id}
    if exclude_user_id:
        target_user_ids.discard(exclude_user_id)

    users = (
        User.query.filter(User.id.in_(target_user_ids), User.is_active.is_(True)).all()
        if target_user_ids
        else []
    )

    for user in users:
        user_id = user.id
        if exclude_user_id and user_id == exclude_user_id:
            continue
        db.session.add(
            Notification(
                user_id=user_id,
                action=action,
                message=message,
            )
        )
    send_action_notification_email(users, action, message)


def notify_action_participants(action, message, exclude_user_id=None, extra_user_ids=None):
    user_ids = set(action.participant_user_ids())
    if extra_user_ids:
        user_ids.update(extra_user_ids)
    notify_users(user_ids, action, message, exclude_user_id=exclude_user_id)


def orientation_nodes_payload():
    nodes = (
        OrientationNode.query.order_by(
            OrientationNode.y.asc(),
            OrientationNode.x.asc(),
            OrientationNode.id.asc(),
        )
        .all()
    )
    payloads = [node.to_dict() for node in nodes]
    payload_by_id = {payload["id"]: payload for payload in payloads}
    child_map = {}
    for payload in payloads:
        child_map.setdefault(payload["parent_id"], []).append(payload["id"])

    def descendant_person_count(node_id):
        total = 0
        for child_id in child_map.get(node_id, []):
            child = payload_by_id[child_id]
            if child["node_type"] == "person":
                total += 1
            total += descendant_person_count(child_id)
        return total

    for payload in payloads:
        payload["descendant_count"] = descendant_person_count(payload["id"])
    return payloads


def parse_node_parent(parent_id, current_node=None):
    if parent_id in (None, "", "null"):
        return None

    try:
        parent_id = int(parent_id)
    except (TypeError, ValueError):
        raise ValueError("invalid_parent") from None

    parent = OrientationNode.query.get(parent_id)
    if parent is None:
        raise ValueError("invalid_parent")

    if current_node is not None:
        check_parent = parent
        while check_parent is not None:
            if check_parent.id == current_node.id:
                raise ValueError("invalid_parent")
            check_parent = check_parent.parent

    return parent


def parse_coordinate(data, key, default):
    try:
        value = int(float(data.get(key, default)))
    except (TypeError, ValueError):
        value = default
    return max(20, min(value, 4000))


def parse_node_color(value):
    value = (value or "").strip()
    if HEX_COLOR_PATTERN.match(value):
        return value.lower()
    return "#198754"


def short_text(value, length=90):
    value = " ".join((value or "").split())
    if len(value) <= length:
        return value
    return f"{value[: length - 3]}..."


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
                action.related_user_1.full_name if action.related_user_1 else "",
                action.related_user_2.full_name if action.related_user_2 else "",
                action.department or "",
            ]
        ).lower():
            continue
        if department and action.department != department:
            continue
        if responsible_user_id and action.responsible_user_id != responsible_user_id:
            continue
        if status == "open" and (
            action.is_completed
            or action.closure_approval_requested
            or action.closure_rejection_reason
            or action.delay_days > 0
        ):
            continue
        if status == "pending" and (
            action.is_completed or not action.closure_approval_requested
        ):
            continue
        if status == "rejected" and (
            action.is_completed
            or action.closure_approval_requested
            or not action.closure_rejection_reason
        ):
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


def store_uploaded_file(uploaded_file):
    if not allowed_file(uploaded_file.filename):
        raise ValueError("invalid_file_type")

    safe_name = secure_filename(uploaded_file.filename)
    extension = safe_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid4().hex}.{extension}"
    upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / stored_name
    uploaded_file.save(upload_path)
    return safe_name, stored_name, uploaded_file.mimetype


def save_uploaded_file(action):
    uploaded_file = request.files.get("action_file")
    if not uploaded_file or not uploaded_file.filename:
        return

    delete_uploaded_file(action)
    safe_name, stored_name, mime_type = store_uploaded_file(uploaded_file)

    action.file_original_name = safe_name
    action.file_stored_name = stored_name
    action.file_mime_type = mime_type


def delete_closure_evidence_file(action):
    for closure_file in list(action.closure_files):
        file_path = Path(current_app.config["UPLOAD_FOLDER"]) / closure_file.stored_name
        if file_path.exists():
            file_path.unlink()
        db.session.delete(closure_file)

    if action.closure_file_stored_name:
        file_path = Path(current_app.config["UPLOAD_FOLDER"]) / action.closure_file_stored_name
        if file_path.exists():
            file_path.unlink()

    action.closure_file_original_name = None
    action.closure_file_stored_name = None
    action.closure_file_mime_type = None


def closure_evidence_uploads():
    uploaded_files = request.files.getlist("closure_files")
    if not uploaded_files:
        uploaded_file = request.files.get("closure_file")
        uploaded_files = [uploaded_file] if uploaded_file else []
    return [uploaded_file for uploaded_file in uploaded_files if uploaded_file.filename]


def save_closure_evidence_files(action):
    uploaded_files = closure_evidence_uploads()
    for uploaded_file in uploaded_files:
        if not allowed_file(uploaded_file.filename):
            raise ValueError("invalid_file_type")

    delete_closure_evidence_file(action)
    for uploaded_file in uploaded_files:
        safe_name, stored_name, mime_type = store_uploaded_file(uploaded_file)
        db.session.add(
            ActionClosureFile(
                action=action,
                original_name=safe_name,
                stored_name=stored_name,
                mime_type=mime_type,
            )
        )


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
    related_user_1 = parse_optional_user("related_user_1_id")
    related_user_2 = parse_optional_user("related_user_2_id")

    action.title = title
    action.responsible_user_id = responsible_user.id
    action.responsible_owner = responsible_user.full_name
    action.related_user_1_id = related_user_1.id if related_user_1 else None
    action.related_user_2_id = related_user_2.id if related_user_2 else None
    action.department = department
    action.description = request.form.get("description", "").strip()

    termin_value = request.form.get("termin_date", "")
    action.termin_date = datetime.strptime(termin_value, "%Y-%m-%d").date()
    action.refresh_delay()
    save_uploaded_file(action)
    return action


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


@bp.get("/notifications")
@login_required
def notifications():
    notification_list = (
        Notification.query.filter_by(user_id=g.current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )
    unread_notifications = Notification.query.filter_by(
        user_id=g.current_user.id, is_read=False
    ).all()
    for notification in unread_notifications:
        notification.is_read = True
    if unread_notifications:
        db.session.commit()
        g.unread_notification_count = 0
    return render_template("notifications.html", notifications=notification_list)


@bp.get("/notifications/count")
@login_required
def notification_count():
    unread_count = Notification.query.filter_by(
        user_id=g.current_user.id, is_read=False
    ).count()
    return jsonify({"count": unread_count})


@bp.get("/notifications/<int:notification_id>/open")
@login_required
def open_notification(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id, user_id=g.current_user.id
    ).first_or_404()
    notification.is_read = True
    db.session.commit()
    if notification.action and can_view_action(notification.action):
        return redirect(url_for("main.action_detail", action_id=notification.action.id))
    return redirect(url_for("main.notifications"))


@bp.get("/organization")
@login_required
def organization():
    return render_template(
        "organization.html",
        nodes=orientation_nodes_payload(),
        can_edit=can_manage_orientation(),
    )


@bp.get("/organization1")
@login_required
def organization_legacy():
    return render_template(
        "orientation.html",
        nodes=orientation_nodes_payload(),
        can_edit=can_manage_orientation(),
    )


@bp.get("/orientation")
@login_required
def orientation():
    return redirect(url_for("main.organization"))


@bp.post("/orientation/nodes")
@login_required
def create_orientation_node():
    if not can_manage_orientation():
        abort(403)

    data = request.get_json(silent=True) or {}
    node_type = (data.get("node_type") or "person").strip()
    if node_type not in ORGANIZATION_NODE_TYPES:
        node_type = "person"

    default_name = "Yeni departman" if node_type == "department" else "Yeni kişi"
    name = (data.get("name") or default_name).strip()
    title = (data.get("title") or "").strip()
    color = parse_node_color(data.get("color"))

    try:
        parent = parse_node_parent(data.get("parent_id"))
    except ValueError:
        return jsonify({"ok": False, "message": "Geçerli bir üst kişi seçin."}), 400

    if parent is not None:
        child_count = OrientationNode.query.filter_by(parent_id=parent.id).count()
        default_x = parent.x + (child_count * 24)
        default_y = parent.y + 170
    else:
        root_count = OrientationNode.query.filter_by(parent_id=None).count()
        default_x = 120 + (root_count * 32)
        default_y = 80

    node = OrientationNode(
        parent_id=parent.id if parent else None,
        name=name[:160],
        title=title[:160],
        node_type=node_type,
        color=color,
        x=parse_coordinate(data, "x", default_x),
        y=parse_coordinate(data, "y", default_y),
    )
    db.session.add(node)
    db.session.commit()
    return jsonify({"ok": True, "node": node.to_dict(), "nodes": orientation_nodes_payload()})


@bp.post("/orientation/nodes/<int:node_id>/update")
@login_required
def update_orientation_node(node_id):
    if not can_manage_orientation():
        abort(403)

    node = OrientationNode.query.get_or_404(node_id)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    title = (data.get("title") or "").strip()
    node_type = (data.get("node_type") or node.node_type or "person").strip()
    if node_type not in ORGANIZATION_NODE_TYPES:
        node_type = "person"
    color = parse_node_color(data.get("color") or node.color)

    if not name:
        return jsonify({"ok": False, "message": "İsim alanı boş bırakılamaz."}), 400

    try:
        parent = parse_node_parent(data.get("parent_id"), current_node=node)
    except ValueError:
        return jsonify({"ok": False, "message": "Geçerli bir üst kişi seçin."}), 400

    node.name = name[:160]
    node.title = title[:160]
    node.node_type = node_type
    node.color = color
    node.parent_id = parent.id if parent else None
    db.session.commit()
    return jsonify({"ok": True, "node": node.to_dict(), "nodes": orientation_nodes_payload()})


@bp.post("/orientation/nodes/<int:node_id>/move")
@login_required
def move_orientation_node(node_id):
    if not can_manage_orientation():
        abort(403)

    node = OrientationNode.query.get_or_404(node_id)
    data = request.get_json(silent=True) or {}
    node.x = parse_coordinate(data, "x", node.x)
    node.y = parse_coordinate(data, "y", node.y)
    db.session.commit()
    return jsonify({"ok": True, "node": node.to_dict()})


@bp.post("/orientation/nodes/<int:node_id>/delete")
@login_required
def delete_orientation_node(node_id):
    if not can_manage_orientation():
        abort(403)

    node = OrientationNode.query.get_or_404(node_id)
    db.session.delete(node)
    db.session.commit()
    return jsonify({"ok": True, "nodes": orientation_nodes_payload()})


def dashboard_context():
    all_actions = refresh_all_actions()
    filters = dashboard_filters()
    actions = filtered_actions(all_actions, filters)
    delayed_count = sum(
        1 for action in all_actions if not action.is_completed and action.delay_days > 0
    )
    completed_count = sum(1 for action in all_actions if action.is_completed)
    pending_approval_count = sum(
        1
        for action in all_actions
        if not action.is_completed and action.closure_approval_requested
    )
    total_count = len(all_actions)

    return {
        "actions": actions,
        "delayed_count": delayed_count,
        "completed_count": completed_count,
        "pending_approval_count": pending_approval_count,
        "total_count": total_count,
        "can_complete_action": can_complete_action,
        "can_request_closure_action": can_request_closure_action,
        "can_approve_closure_action": can_approve_closure_action,
        "departments": DEPARTMENTS,
        "filters": filters,
        "users": active_users(),
        "current_user_initials": user_initials(g.current_user),
    }


@bp.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", **dashboard_context())


@bp.route("/dashboard-liste")
@login_required
def dashboard_list():
    return render_template("dashboard_list.html", **dashboard_context())


@bp.route("/dashboard-eski")
@login_required
def dashboard_legacy():
    return render_template("dashboard_legacy.html", **dashboard_context())


@bp.route("/actions/new", methods=["GET", "POST"])
@login_required
@permission_required("can_create_actions")
def create_action():
    if request.method == "POST":
        try:
            action = parse_action_form()
            action.action_number = reserve_action_number()
            db.session.add(action)
            db.session.flush()
            add_action_history(
                action,
                "created",
                f"{g.current_user.full_name} aksiyonu oluşturdu.",
                actor=g.current_user,
            )
            notify_action_participants(
                action,
                f"{action.number_label} {action.title} aksiyonu size atandı.",
                exclude_user_id=g.current_user.id,
            )
            db.session.commit()
            flash("Aksiyon kaydı başarıyla eklendi.", "success")
            return redirect(url_for("main.dashboard"))
        except ValueError as error:
            if str(error) == "invalid_file_type":
                flash(
                    "Sadece PDF, Word, Excel veya görsel dosyası yükleyebilirsiniz.",
                    "danger",
                )
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
        can_request_closure=can_request_closure_action(action),
        can_approve_closure=can_approve_closure_action(action),
        can_comment=can_comment_action(action),
        can_reassign=can_reassign_action(action),
        can_revise_termin=can_revise_termin(action),
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

    try:
        related_user_1 = parse_optional_user("related_user_1_id")
        related_user_2 = parse_optional_user("related_user_2_id")
    except ValueError:
        flash("Lütfen geçerli ilgili kullanıcı seçin.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    before = action_snapshot(action)
    action.responsible_user_id = responsible_user.id
    action.responsible_owner = responsible_user.full_name
    action.related_user_1_id = related_user_1.id if related_user_1 else None
    action.related_user_2_id = related_user_2.id if related_user_2 else None

    changes = describe_action_changes(before, action)
    if not changes:
        flash("Sorumlu ve ilgili bilgilerinde değişiklik yapılmadı.", "warning")
        return redirect(url_for("main.action_detail", action_id=action.id))

    add_action_history(
        action,
        "reassigned",
        (
            f"{g.current_user.full_name} sorumlu/ilgili bilgilerini güncelledi: "
            + "; ".join(changes)
        ),
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        (
            f"{action.number_label} {action.title} aksiyonunda "
            "sorumlu/ilgili bilgileri güncellendi."
        ),
        exclude_user_id=g.current_user.id,
        extra_user_ids={
            before["responsible_user_id"],
            before["related_user_1_id"],
            before["related_user_2_id"],
        },
    )
    db.session.commit()
    flash("Sorumlu ve ilgili bilgileri güncellendi.", "success")

    if can_view_action(action):
        return redirect(url_for("main.action_detail", action_id=action.id))
    return redirect(url_for("main.dashboard"))


@bp.post("/actions/<int:action_id>/revise-termin")
@login_required
def revise_action_termin(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_revise_termin(action):
        abort(403)

    termin_value = request.form.get("termin_date", "")
    try:
        new_termin_date = datetime.strptime(termin_value, "%Y-%m-%d").date()
    except ValueError:
        flash("Lütfen geçerli bir termin tarihi girin.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    old_termin_date = action.termin_date
    if old_termin_date == new_termin_date:
        flash("Termin tarihi zaten bu değerle kayıtlı.", "warning")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.termin_date = new_termin_date
    action.refresh_delay()
    add_action_history(
        action,
        "termin_revised",
        (
            f"{g.current_user.full_name} termini "
            f"{format_date(old_termin_date)} -> {format_date(new_termin_date)} "
            "olarak revize etti."
        ),
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        f"{action.number_label} {action.title} aksiyonunda termin revize edildi.",
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("Termin tarihi revize edildi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


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
    add_action_history(
        action,
        "commented",
        f"{g.current_user.full_name} yorum ekledi: \"{short_text(comment_text)}\"",
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        f"{action.number_label} {action.title} aksiyonuna yeni yorum eklendi.",
        exclude_user_id=g.current_user.id,
    )
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
            before = action_snapshot(action)
            parse_action_form(action)
            changes = describe_action_changes(before, action)
            if changes:
                add_action_history(
                    action,
                    "updated",
                    (
                        f"{g.current_user.full_name} aksiyonu revize etti: "
                        + "; ".join(changes)
                    ),
                    actor=g.current_user,
                )
                notify_action_participants(
                    action,
                    f"{action.number_label} {action.title} aksiyonunda revizyon yapıldı.",
                    exclude_user_id=g.current_user.id,
                    extra_user_ids={
                        before["responsible_user_id"],
                        before["related_user_1_id"],
                        before["related_user_2_id"],
                    },
                )
            db.session.commit()
            flash("Aksiyon kaydı güncellendi.", "success")
            return redirect(url_for("main.dashboard"))
        except ValueError as error:
            if str(error) == "invalid_file_type":
                flash(
                    "Sadece PDF, Word, Excel veya görsel dosyası yükleyebilirsiniz.",
                    "danger",
                )
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


@bp.post("/actions/<int:action_id>/request-closure")
@login_required
def request_action_closure(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_request_closure_action(action):
        abort(403)

    evidence_note = request.form.get("closure_evidence_note", "").strip()
    if not evidence_note:
        flash("Kapatma onayı için açıklama alanını doldurun.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    try:
        save_closure_evidence_files(action)
    except ValueError:
        flash("Sadece PDF, Word, Excel veya görsel dosyası yükleyebilirsiniz.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.closure_approval_requested = True
    action.closure_requested_at = datetime.utcnow()
    action.closure_requested_by_user_id = g.current_user.id
    action.closure_evidence_note = evidence_note
    action.closure_rejected_at = None
    action.closure_rejected_by_user_id = None
    action.closure_rejection_reason = None
    add_action_history(
        action,
        "closure_requested",
        f"{g.current_user.full_name} kapatma onayı gönderdi.",
        actor=g.current_user,
    )
    admin_user = oguzhan_user()
    if admin_user:
        notify_users(
            {admin_user.id},
            action,
            f"{action.number_label} {action.title} aksiyonu için kapatma onayı bekliyor.",
            exclude_user_id=g.current_user.id,
        )
    db.session.commit()
    flash("Kapatma onayı Oğuzhan'a gönderildi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.post("/actions/<int:action_id>/complete")
@login_required
def complete_action(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_approve_closure_action(action):
        abort(403)

    action.mark_completed()
    add_action_history(
        action,
        "completed",
        f"{g.current_user.full_name} kapatma onayını verdi ve aksiyonu tamamladı.",
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        f"{action.number_label} {action.title} aksiyonunun kapanışı Oğuzhan tarafından onaylandı.",
        exclude_user_id=g.current_user.id,
    )
    db.session.commit()
    flash("Kapatma onayı verildi ve aksiyon tamamlandı.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.post("/actions/<int:action_id>/reject-closure")
@login_required
def reject_action_closure(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_approve_closure_action(action):
        abort(403)

    rejection_reason = request.form.get("closure_rejection_reason", "").strip()
    if not rejection_reason:
        flash("Red sebebi alanını doldurun.", "danger")
        return redirect(url_for("main.action_detail", action_id=action.id))

    action.closure_approval_requested = False
    action.closure_rejected_at = datetime.utcnow()
    action.closure_rejected_by_user_id = g.current_user.id
    action.closure_rejection_reason = rejection_reason
    add_action_history(
        action,
        "closure_rejected",
        (
            f"{g.current_user.full_name} kapatma onayını reddetti: "
            f"\"{short_text(rejection_reason)}\""
        ),
        actor=g.current_user,
    )
    notify_action_participants(
        action,
        (
            f"{action.number_label} {action.title} aksiyonunun kapatma onayı "
            f"reddedildi. Sebep: {short_text(rejection_reason)}"
        ),
        exclude_user_id=g.current_user.id,
        extra_user_ids={action.closure_requested_by_user_id},
    )
    db.session.commit()
    flash("Kapatma onayı reddedildi.", "success")
    return redirect(url_for("main.action_detail", action_id=action.id))


@bp.route("/actions/<int:action_id>/delete", methods=["GET", "POST"])
@login_required
@permission_required("can_delete_actions")
def delete_action(action_id):
    action = Action.query.get_or_404(action_id)

    if request.method == "POST":
        delete_uploaded_file(action)
        delete_closure_evidence_file(action)
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


@bp.get("/actions/<int:action_id>/closure-evidence/<int:file_id>/download")
@login_required
def download_closure_evidence_file(action_id, file_id):
    action = Action.query.get_or_404(action_id)
    if not can_view_action(action):
        abort(403)

    closure_file = ActionClosureFile.query.filter_by(
        id=file_id,
        action_id=action.id,
    ).first_or_404()

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        closure_file.stored_name,
        as_attachment=True,
        download_name=closure_file.original_name,
    )


@bp.get("/actions/<int:action_id>/closure-evidence/download")
@login_required
def download_latest_closure_evidence_file(action_id):
    action = Action.query.get_or_404(action_id)
    if not can_view_action(action):
        abort(403)

    if action.closure_files:
        closure_file = action.closure_files[-1]
        return redirect(
            url_for(
                "main.download_closure_evidence_file",
                action_id=action.id,
                file_id=closure_file.id,
            )
        )

    if not action.closure_file_stored_name:
        flash("Bu aksiyona ait kapanış kanıt dosyası bulunamadı.", "warning")
        return redirect(url_for("main.action_detail", action_id=action.id))

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        action.closure_file_stored_name,
        as_attachment=True,
        download_name=action.closure_file_original_name,
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
