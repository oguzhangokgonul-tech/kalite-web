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
from .dynamic_forms import bp as dynamic_forms_bp
from .inspections import bp as inspections_bp
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
    app.register_blueprint(dynamic_forms_bp)
    app.register_blueprint(inspections_bp)

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

    @app.cli.command("db-check")
    @with_appcontext
    def db_check_command():
        from .database_ops import (
            DatabaseOperationError,
            record_database_audit,
            sqlite_health_check,
        )

        try:
            check = sqlite_health_check()
        except DatabaseOperationError as error:
            raise click.ClickException(str(error))

        click.echo(f"Veritabani: {check.source_path}")
        click.echo(f"Boyut: {check.size_bytes} bayt")
        click.echo(f"quick_check: {check.quick_check}")
        click.echo(f"integrity_check: {check.integrity_check}")
        click.echo(f"Alembic mevcut: {check.alembic_version or '-'}")
        click.echo(f"Alembic beklenen: {check.expected_revision or '-'}")
        if check.migration_warning:
            click.echo("UYARI: Alembic surumu beklenen head ile ayni degil.")

        record_database_audit(
            "integrity_checked",
            "SQLite veritabani butunluk kontrolu",
            {
                "database_path": str(check.source_path),
                "size_bytes": check.size_bytes,
                "quick_check": check.quick_check,
                "integrity_check": check.integrity_check,
                "alembic_version": check.alembic_version,
                "expected_revision": check.expected_revision,
            },
        )

        if not check.is_ok:
            raise click.ClickException("SQLite butunluk kontrolu basarisiz.")

    @app.cli.command("db-backup")
    @click.option(
        "--output-dir",
        type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
        default=None,
        help="Yedegin yazilacagi klasor. Varsayilan: DATA_DIR/backups.",
    )
    @click.option(
        "--keep-last",
        type=int,
        default=None,
        help="Ayni veritabani icin tutulacak son yedek adedi.",
    )
    @with_appcontext
    def db_backup_command(output_dir, keep_last):
        from .database_ops import (
            DatabaseOperationError,
            create_sqlite_backup,
            record_database_audit,
        )

        try:
            result = create_sqlite_backup(output_dir=output_dir, keep_last=keep_last)
        except DatabaseOperationError as error:
            raise click.ClickException(str(error))

        click.echo(f"Yedek olusturuldu: {result.backup_path}")
        click.echo(f"Kaynak: {result.source_path}")
        click.echo(f"Boyut: {result.size_bytes} bayt")
        click.echo(f"quick_check: {result.quick_check}")
        click.echo(f"integrity_check: {result.integrity_check}")

        record_database_audit(
            "backup_created",
            "SQLite veritabani yedegi olusturuldu",
            {
                "source_path": str(result.source_path),
                "backup_path": str(result.backup_path),
                "size_bytes": result.size_bytes,
                "quick_check": result.quick_check,
                "integrity_check": result.integrity_check,
            },
        )

    @app.cli.command("full-backup")
    @click.option(
        "--output-dir",
        type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
        default=None,
        help="Tam yedegin yazilacagi klasor. Varsayilan: FULL_BACKUP_DIR.",
    )
    @click.option(
        "--keep-last",
        type=int,
        default=None,
        help="Tutulacak son tam yedek adedi.",
    )
    @click.option(
        "--without-uploads",
        is_flag=True,
        help="Sadece veritabani yedegi al; upload dosyalarini pakete koyma.",
    )
    @with_appcontext
    def full_backup_command(output_dir, keep_last, without_uploads):
        from .database_ops import (
            DatabaseOperationError,
            create_full_backup,
            record_database_audit,
        )
        from .models import AppSetting

        try:
            result = create_full_backup(
                output_dir=output_dir,
                keep_last=keep_last,
                include_uploads=not without_uploads,
            )
        except DatabaseOperationError as error:
            raise click.ClickException(str(error))

        click.echo(f"Tam yedek olusturuldu: {result.backup_path}")
        click.echo(f"Kaynak veritabani: {result.source_path}")
        click.echo(f"Paket boyutu: {result.size_bytes} bayt")
        click.echo(f"Upload dosyasi: {result.upload_file_count}")
        click.echo(f"quick_check: {result.quick_check}")
        click.echo(f"integrity_check: {result.integrity_check}")

        setting = db.session.get(AppSetting, "sales_readiness:month4_backup")
        if setting is None:
            db.session.add(AppSetting(key="sales_readiness:month4_backup", value="1"))
        else:
            setting.value = "1"

        record_database_audit(
            "full_backup_created",
            "Tam sistem yedegi olusturuldu",
            {
                "source_path": str(result.source_path),
                "backup_path": str(result.backup_path),
                "size_bytes": result.size_bytes,
                "upload_file_count": result.upload_file_count,
                "upload_total_bytes": result.upload_total_bytes,
                "quick_check": result.quick_check,
                "integrity_check": result.integrity_check,
            },
        )

    @app.cli.command("backup-verify")
    @click.argument(
        "backup_path",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @with_appcontext
    def backup_verify_command(backup_path):
        from .database_ops import record_database_audit, validate_backup_package

        result = validate_backup_package(backup_path)
        click.echo(f"Yedek: {result.backup_path}")
        click.echo(f"Durum: {'OK' if result.is_ok else 'HATALI'}")
        click.echo(f"Checksum dosyasi: {result.checksum_count}")
        click.echo(f"Upload dosyasi: {result.upload_file_count}")
        click.echo(f"quick_check: {result.quick_check or '-'}")
        click.echo(f"integrity_check: {result.integrity_check or '-'}")
        if result.issues:
            click.echo("Sorunlar:")
            for issue in result.issues:
                click.echo(f"- {issue}")

        record_database_audit(
            "backup_verified",
            "Tam sistem yedegi dogrulandi",
            {
                "backup_path": str(result.backup_path),
                "is_ok": result.is_ok,
                "issues": list(result.issues),
                "checksum_count": result.checksum_count,
                "upload_file_count": result.upload_file_count,
                "quick_check": result.quick_check,
                "integrity_check": result.integrity_check,
            },
        )
        if not result.is_ok:
            raise click.ClickException("Yedek dogrulamasi basarisiz.")

    @app.cli.command("restore-backup")
    @click.argument(
        "backup_path",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option(
        "--apply",
        "apply_restore",
        is_flag=True,
        help="Gercek geri yukleme yap. Varsayilan dry-run'dir.",
    )
    @click.option(
        "--confirm",
        default="",
        help="Gercek geri yukleme onay metni.",
    )
    @with_appcontext
    def restore_backup_command(backup_path, apply_restore, confirm):
        from .database_ops import (
            DatabaseOperationError,
            FULL_BACKUP_CONFIRMATION_TEXT,
            record_database_audit,
            restore_full_backup_apply,
            restore_full_backup_dry_run,
        )

        if not apply_restore:
            result = restore_full_backup_dry_run(backup_path)
            click.echo(f"Dry-run tamamlandi: {result.backup_path}")
            click.echo(f"Durum: {'OK' if not result.issues else 'HATALI'}")
            click.echo(f"Upload dosyasi: {result.restored_upload_files}")
            click.echo(f"quick_check: {result.quick_check or '-'}")
            click.echo(f"integrity_check: {result.integrity_check or '-'}")
            if result.issues:
                click.echo("Sorunlar:")
                for issue in result.issues:
                    click.echo(f"- {issue}")
                record_database_audit(
                    "restore_dry_run",
                    "Tam sistem yedegi dry-run kontrolu basarisiz",
                    {
                        "backup_path": str(result.backup_path),
                        "issues": list(result.issues),
                    },
                )
                raise click.ClickException("Dry-run basarisiz.")

            record_database_audit(
                "restore_dry_run",
                "Tam sistem yedegi dry-run kontrolu basarili",
                {
                    "backup_path": str(result.backup_path),
                    "upload_file_count": result.restored_upload_files,
                    "quick_check": result.quick_check,
                    "integrity_check": result.integrity_check,
                },
            )
            click.echo(
                "Gercek geri yukleme icin: "
                f"--apply --confirm {FULL_BACKUP_CONFIRMATION_TEXT}"
            )
            return

        try:
            result = restore_full_backup_apply(backup_path, confirm=confirm)
        except DatabaseOperationError as error:
            record_database_audit(
                "restore_failed",
                "Tam sistem yedegi geri yukleme basarisiz",
                {"backup_path": str(backup_path), "error": str(error)},
            )
            raise click.ClickException(str(error))

        click.echo(f"Geri yukleme tamamlandi: {result.backup_path}")
        click.echo(f"On yedek: {result.pre_restore_backup_path}")
        click.echo(f"Veritabani: {result.restored_database_path}")
        click.echo(f"Upload dosyasi: {result.restored_upload_files}")
        click.echo(f"quick_check: {result.quick_check}")
        click.echo(f"integrity_check: {result.integrity_check}")
        record_database_audit(
            "restore_completed",
            "Tam sistem yedegi geri yukleme tamamlandi",
            {
                "backup_path": str(result.backup_path),
                "pre_restore_backup_path": str(result.pre_restore_backup_path),
                "database_path": str(result.restored_database_path),
                "upload_file_count": result.restored_upload_files,
                "quick_check": result.quick_check,
                "integrity_check": result.integrity_check,
            },
        )

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
