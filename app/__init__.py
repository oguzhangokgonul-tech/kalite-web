from flask import Flask
from flask.cli import with_appcontext
from flask import flash, jsonify, redirect, request, url_for
from flask_wtf.csrf import CSRFError
from pathlib import Path
from dotenv import load_dotenv
import click

load_dotenv()

from .config import Config
from .extensions import csrf, db, migrate
from .routes import bp
from .seed import ensure_default_maintenance_machines, ensure_default_users


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    from .audit import register_audit_listeners

    register_audit_listeners()

    app.register_blueprint(bp)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        message = (
            "Güvenlik doğrulaması başarısız oldu. Lütfen sayfayı yenileyip tekrar deneyin."
        )
        if request.is_json or request.accept_mimetypes.best == "application/json":
            return jsonify({"ok": False, "message": message}), 400
        flash(
            message,
            "danger",
        )
        return redirect(request.referrer or url_for("main.dashboard"))

    @app.cli.command("seed-users")
    @with_appcontext
    def seed_users_command():
        ensure_default_users(reset_passwords=False)
        print("Varsayılan kullanıcılar oluşturuldu/güncellendi.")

    @app.cli.command("seed-maintenance-machines")
    @with_appcontext
    def seed_maintenance_machines_command():
        ensure_default_maintenance_machines()
        print("Bakım makine envanteri oluşturuldu/güncellendi.")

    @app.cli.command("test-mail")
    @click.argument("to_address")
    @with_appcontext
    def test_mail_command(to_address):
        from .mail import send_test_email

        if send_test_email(to_address):
            print(f"Test e-postası gönderildi: {to_address}")
        else:
            print("Mail gönderilemedi. MAIL_ENABLED ve SMTP ayarlarını kontrol edin.")

    @app.cli.command("send-reminders")
    @click.option(
        "--company-id",
        type=int,
        default=None,
        help="Sadece belirtilen firma icin hatirlatma uret.",
    )
    @click.option(
        "--force",
        is_flag=True,
        help="Ayni gun daha once calismis olsa bile yeniden uret.",
    )
    @with_appcontext
    def send_reminders_command(company_id, force):
        from .notifications import ensure_notification_schema
        from .reminders import (
            run_due_reminders_for_all_companies,
            run_due_reminders_once_for_company,
        )

        ensure_notification_schema()
        if company_id is not None:
            stats = run_due_reminders_once_for_company(company_id, force=force)
            click.echo(
                "Hatirlatma tamamlandi: "
                f"{stats['notifications']} bildirim, {stats['emails']} e-posta."
            )
            if stats.get("skipped"):
                click.echo("Bu firma icin bugunun hatirlatmalari zaten uretilmis.")
            return

        stats = run_due_reminders_for_all_companies(force=force)
        click.echo(
            "Hatirlatma tamamlandi: "
            f"{stats['companies']} kapsam, "
            f"{stats['notifications']} bildirim, "
            f"{stats['emails']} e-posta, "
            f"{stats['skipped']} atlanan."
        )

    @app.cli.command("reopen-completed-dofs")
    @click.option(
        "--apply",
        "apply_changes",
        is_flag=True,
        help="Listedeki IF kayitlarini Yonetim Temsilcisi onayina geri al.",
    )
    @click.option(
        "--dof-no",
        "dof_numbers",
        multiple=True,
        help="Sadece belirtilen IF numarasini geri al. Birden fazla kez kullanilabilir.",
    )
    @click.option(
        "--notify",
        is_flag=True,
        help="Geri alinan IF'ler icin bekleyen onay bildirimlerini tekrar gonder.",
    )
    @with_appcontext
    def reopen_completed_dofs_command(apply_changes, dof_numbers, notify):
        from flask import current_app
        from sqlalchemy import or_

        from .models import Dof, DofComment

        print(f"Veritabani: {current_app.config['SQLALCHEMY_DATABASE_URI']}")
        status_rows = (
            db.session.query(Dof.status, Dof.approval_step, db.func.count(Dof.id))
            .group_by(Dof.status, Dof.approval_step)
            .order_by(Dof.status.asc(), Dof.approval_step.asc())
            .all()
        )
        if status_rows:
            print("Mevcut IF durum ozeti:")
            for status, step, count in status_rows:
                print(f"- durum={status or '-'} | adim={step or '-'} | adet={count}")

        query = Dof.query.filter(
            or_(
                Dof.status.like("Tamamlan%"),
                Dof.approval_step == "completed",
                Dof.completed_at.isnot(None),
                Dof.deputy_approved_at.isnot(None),
            )
        )
        if dof_numbers:
            query = query.filter(Dof.dof_no.in_(dof_numbers))

        dofs = query.order_by(Dof.dof_no.asc(), Dof.id.asc()).all()
        if not dofs:
            print("Geri alinacak tamamlanmis IF kaydi bulunamadi.")
            return

        print(f"{len(dofs)} IF kaydi Yonetim Temsilcisi onayina geri alinacak:")
        for dof in dofs:
            print(
                f"- {dof.dof_no} | {dof.title or '-'} | "
                f"durum={dof.status} | adim={dof.approval_step}"
            )

        if not apply_changes:
            print("Dry-run tamamlandi. Degisiklik yapmak icin --apply ekleyin.")
            return

        for dof in dofs:
            dof.status = "Onay AkÄ±ÅŸÄ± Bekleniyor"
            dof.approval_step = "management_representative"
            dof.management_approved_by_user_id = None
            dof.management_approved_at = None
            dof.deputy_approved_by_user_id = None
            dof.deputy_approved_at = None
            dof.completed_at = None
            dof.rejection_reason = None
            dof.rejected_by_user_id = None
            dof.rejected_at = None
            dof.rejected_step = None
            db.session.add(
                DofComment(
                    dof=dof,
                    comment=(
                        "Sistem duzeltmesi: tamamlanmis IF kaydi "
                        "Yonetim Temsilcisi onayina geri alindi."
                    ),
                    comment_type="approval_reopen",
                )
            )
            if notify:
                from .routes import notify_dof_waiting_approvers

                notify_dof_waiting_approvers(dof)

        db.session.commit()
        print(f"{len(dofs)} IF kaydi geri alindi.")

    @app.cli.command("tenant-health")
    @with_appcontext
    def tenant_health_command():
        from .tenant_health import collect_tenant_health_checks, tenant_health_has_failures

        checks = collect_tenant_health_checks()
        for check in checks:
            click.echo(f"[{check.status}] {check.message}")

        if tenant_health_has_failures(checks):
            raise click.ClickException("Tenant health kontrolu basarisiz.")

    @app.cli.command("company-bootstrap")
    @click.argument("company_code")
    @with_appcontext
    def company_bootstrap_command(company_code):
        from .company_onboarding import initialize_company_onboarding
        from .models import Company

        company = Company.query.filter_by(code=company_code).first()
        if company is None:
            raise click.ClickException(f"Sirket bulunamadi: {company_code}")

        created_items = initialize_company_onboarding(company)
        db.session.commit()
        created_count = sum(len(items) for items in created_items.values())
        if created_count:
            click.echo(f"{company.label} icin {created_count} kurulum kalemi olusturuldu.")
            for group_name, items in created_items.items():
                for item in items:
                    click.echo(f"- {group_name}: {item}")
        else:
            click.echo(f"{company.label} kurulum kalemleri zaten hazir.")

    return app
