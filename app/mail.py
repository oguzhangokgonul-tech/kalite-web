import smtplib
from email.message import EmailMessage

from flask import current_app


def mail_is_configured():
    return all(
        [
            current_app.config.get("MAIL_ENABLED"),
            current_app.config.get("MAIL_SERVER"),
            current_app.config.get("MAIL_DEFAULT_SENDER"),
        ]
    )


def send_email(to_address, subject, body):
    if not to_address or not mail_is_configured():
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = current_app.config["MAIL_DEFAULT_SENDER"]
    message["To"] = to_address
    message.set_content(body)

    server = current_app.config["MAIL_SERVER"]
    port = current_app.config["MAIL_PORT"]
    username = current_app.config.get("MAIL_USERNAME")
    password = current_app.config.get("MAIL_PASSWORD")

    with smtplib.SMTP(server, port, timeout=20) as smtp:
        if current_app.config.get("MAIL_USE_TLS"):
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)

    return True


def action_number(action):
    return f"#{action.id}"


def send_action_created_email(action):
    subject = f"Hakkınızda açılan aksiyon {action_number(action)}"
    body = "\n".join(
        [
            f"Aksiyon No: {action_number(action)}",
            f"Aksiyon Başlığı: {action.title}",
            f"Departman: {action.department}",
            f"Aksiyon Sorumlusu: {action.responsible_owner}",
            f"Termin: {action.termin_date.strftime('%d.%m.%Y')}",
            "",
            "Aksiyon İçeriği:",
            action.description or "Açıklama girilmemiş.",
            "",
            f"Aksiyonunuz açılmıştır, son termininiz {action.termin_date.strftime('%d.%m.%Y')}.",
        ]
    )
    return send_email(action.responsible_user.email if action.responsible_user else None, subject, body)


def send_action_completed_email(action, closed_by):
    subject = f"Aksiyonunuz kapatılmıştır {action_number(action)}"
    body = "\n".join(
        [
            f"Aksiyon No: {action_number(action)}",
            f"Aksiyon Başlığı: {action.title}",
            "",
            f"{closed_by.full_name} tarafından aksiyonunuz kapatılmıştır.",
        ]
    )
    return send_email(action.responsible_user.email if action.responsible_user else None, subject, body)
