import smtplib
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage

from flask import current_app, url_for


_mail_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mail")


def _mail_settings():
    return {
        "enabled": current_app.config.get("MAIL_ENABLED"),
        "suppress_send": current_app.config.get("MAIL_SUPPRESS_SEND"),
        "server": current_app.config.get("MAIL_SERVER"),
        "port": current_app.config.get("MAIL_PORT"),
        "use_tls": current_app.config.get("MAIL_USE_TLS"),
        "use_ssl": current_app.config.get("MAIL_USE_SSL"),
        "username": current_app.config.get("MAIL_USERNAME"),
        "password": current_app.config.get("MAIL_PASSWORD"),
        "sender": current_app.config.get("MAIL_DEFAULT_SENDER"),
        "reply_to": current_app.config.get("MAIL_REPLY_TO"),
        "timeout": current_app.config.get("MAIL_TIMEOUT"),
    }


def _mail_enabled(settings):
    return bool(
        settings.get("enabled")
        and settings.get("server")
        and settings.get("sender")
    )


def _action_url(action):
    public_base_url = current_app.config.get("PUBLIC_BASE_URL")
    if public_base_url:
        return f"{public_base_url}/actions/{action.id}"
    try:
        return url_for("main.action_detail", action_id=action.id, _external=True)
    except RuntimeError:
        return ""


def _dof_url(dof):
    public_base_url = current_app.config.get("PUBLIC_BASE_URL")
    if public_base_url:
        return f"{public_base_url}/dofs/{dof.id}"
    try:
        return url_for("main.dof_detail", dof_id=dof.id, _external=True)
    except RuntimeError:
        return ""


def _format_date(value):
    return value.strftime("%d.%m.%Y") if value else "-"


def _site_name():
    return current_app.config.get("SITE_NAME", "TOKEN")


def build_action_email(action, message):
    action_url = _action_url(action)
    subject_prefix = current_app.config.get("MAIL_SUBJECT_PREFIX", f"[{_site_name()}]")
    subject = f"{subject_prefix} {action.number_label} {action.title}"
    if action.is_completed:
        status = "Tamamlandı"
    elif action.closure_approval_requested:
        status = "Kapanma Onayı Beklemede"
    elif action.closure_rejection_reason:
        status = "Kapanma Onayı Reddedildi"
    else:
        status = "Açık"

    lines = [
        message,
        "",
        f"Aksiyon No: {action.number_label}",
        f"Başlık: {action.title}",
        f"Sorumlu: {action.responsible_owner}",
        f"Departman: {action.department}",
        f"Termin: {_format_date(action.termin_date)}",
        f"Durum: {status}",
    ]

    if action.description:
        lines.extend(["", "Açıklama:", action.description])
    if action_url:
        lines.extend(["", f"Detay: {action_url}"])

    return subject, "\n".join(lines)


def build_dof_email(dof, message):
    dof_url = _dof_url(dof)
    subject_prefix = current_app.config.get("MAIL_SUBJECT_PREFIX", f"[{_site_name()}]")
    subject = f"{subject_prefix} {dof.dof_no}"

    lines = [
        message,
        "",
        f"İF No: {dof.dof_no}",
        f"Başlık: {dof.title or '-'}",
        f"Departman: {dof.department or '-'}",
        f"Sorumlu: {dof.responsible.full_name if dof.responsible else '-'}",
        f"Açılış Tarihi: {_format_date(dof.opening_date)}",
        f"Termin: {_format_date(dof.due_date)}",
        f"Öncelik: {dof.priority or '-'}",
        f"Kaynak: {dof.source or '-'}",
        f"Durum: {dof.status or '-'}",
    ]

    if dof.nonconformity_description:
        lines.extend(["", "Uygunsuzluk Açıklaması:", dof.nonconformity_description])
    if dof_url:
        lines.extend(["", f"Detay: {dof_url}"])

    return subject, "\n".join(lines)


def send_mail_now(settings, recipients, subject, body):
    recipients = [recipient for recipient in recipients if recipient]
    if not recipients or not _mail_enabled(settings):
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings["sender"]
    msg["To"] = ", ".join(recipients)
    reply_to = settings.get("reply_to")
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    if settings.get("suppress_send"):
        return True

    if settings.get("use_ssl"):
        smtp = smtplib.SMTP_SSL(
            settings["server"], settings["port"], timeout=settings["timeout"]
        )
    else:
        smtp = smtplib.SMTP(
            settings["server"], settings["port"], timeout=settings["timeout"]
        )

    with smtp:
        if settings.get("use_tls") and not settings.get("use_ssl"):
            smtp.starttls()
        username = settings.get("username")
        password = settings.get("password")
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)

    return True


def _send_mail_safely(settings, recipients, subject, body, logger):
    try:
        if settings.get("suppress_send"):
            logger.info("Mail sending suppressed: %s -> %s", subject, recipients)
            return
        send_mail_now(settings, recipients, subject, body)
    except Exception:
        logger.exception("E-posta gönderilemedi.")


def send_action_notification_email(users, action, message):
    recipients = sorted({user.email for user in users if user.email})
    if not recipients:
        return False

    settings = _mail_settings()
    if not _mail_enabled(settings):
        return False

    subject, body = build_action_email(action, message)
    _mail_executor.submit(
        _send_mail_safely,
        settings,
        recipients,
        subject,
        body,
        current_app.logger,
    )
    return True


def send_dof_notification_email(users, dof, message):
    recipients = sorted({user.email for user in users if user.email})
    if not recipients:
        return False

    settings = _mail_settings()
    if not _mail_enabled(settings):
        return False

    subject, body = build_dof_email(dof, message)
    _mail_executor.submit(
        _send_mail_safely,
        settings,
        recipients,
        subject,
        body,
        current_app.logger,
    )
    return True


def send_test_email(to_address):
    settings = _mail_settings()
    site_name = _site_name()
    subject = current_app.config.get("MAIL_SUBJECT_PREFIX", f"[{site_name}]")
    subject = f"{subject} Test e-postası"
    body = f"Bu e-posta {site_name} SMTP ayarlarını test etmek için gönderildi."
    return send_mail_now(settings, [to_address], subject, body)
