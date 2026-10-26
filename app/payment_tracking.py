"""Internal receivable and payable records; no money is moved by this module."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.exc import StaleDataError

from .audit import record_audit_event
from .extensions import db
from .models import Notification, User
from .notifications import add_user_notification
from .payment_models import PaymentAttachment, PaymentInstallment, PaymentRecord, PaymentTransaction
from .tenant import assign_current_company, current_company_id, scoped_query


bp = Blueprint("payments", __name__, url_prefix="/odemeler")
DIRECTIONS = {"receivable": "Alınacak Ödemeler", "payable": "Yapılacak Ödemeler"}
STATUSES = {"open": "Açık", "closed": "Tamamlandı", "cancelled": "İptal"}
CURRENCIES = ("TRY", "USD", "EUR")
PAYMENT_METHODS = {
    "unspecified": "Belirtilmedi", "bank_transfer": "Havale / EFT",
    "cash": "Nakit", "check": "Çek", "promissory_note": "Senet", "other": "Diğer",
}
MAX_INSTALLMENTS = 24
MAX_PDF_BYTES = 10 * 1024 * 1024


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def can_view():
    user = getattr(g, "current_user", None)
    return bool(user and current_company_id() and (
        user.has_permission("payments.view") or user.has_permission("payments.manage")
    ))


def can_manage():
    return can_view() and g.current_user.has_permission("payments.manage")


@bp.before_request
def guard():
    if getattr(g, "current_user", None) is None:
        return redirect(url_for("main.login", next=request.full_path))
    if not current_company_id() or not g.company_module_enabled("payment_tracking") or not can_view():
        abort(403)


@bp.errorhandler(StaleDataError)
@bp.errorhandler(IntegrityError)
def concurrent_payment_change(_error):
    db.session.rollback()
    abort(409, description="Kayıt başka bir işlemle değişti. Sayfayı yenileyin.")


@bp.context_processor
def template_context():
    return {"payment_directions": DIRECTIONS, "payment_statuses": STATUSES,
            "payment_can_manage": can_manage(), "payment_today": date.today(),
            "payment_methods": PAYMENT_METHODS}


def direction_or_404(direction):
    if direction not in DIRECTIONS:
        abort(404)
    return direction


def record_query(direction=None):
    query = scoped_query(PaymentRecord.query, PaymentRecord).filter(
        PaymentRecord.company_id == current_company_id()
    )
    return query.filter_by(direction=direction) if direction else query


def record_or_404(record_id, direction):
    return record_query(direction_or_404(direction)).filter_by(id=record_id).first_or_404()


def active_responsibles():
    return [user for user in scoped_query(User.query, User).filter_by(
        company_id=current_company_id(), is_active=True, deleted_at=None
    ).order_by(User.full_name).all() if user.has_permission("payments.view") or user.has_permission("payments.manage")]


def snapshot(record):
    return {key: getattr(record, key) for key in (
        "direction", "counterparty", "description", "reference_no", "project_no",
        "amount", "settled_amount", "currency", "payment_method", "due_date", "responsible_user_id",
        "status", "settled_on", "note", "archived_at",
    )}


def audit(record, action, old=None, extra=None):
    db.session.flush()
    values = snapshot(record)
    if extra:
        values.update(extra)
    record_audit_event(
        "PaymentRecord", action, record.number_label,
        entity_id=record.id, company_id=record.company_id, user_id=g.current_user.id,
        old_values=old, new_values=values, commit=False,
    )


def text_value(name, limit, required=False):
    value = request.form.get(name, "").strip()
    if len(value) > limit or (required and not value) or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("Zorunlu alanları ve metin uzunluklarını kontrol edin.")
    return value or None


def parse_money(raw, allow_zero=False):
    raw = str(raw or "").strip().replace(",", ".")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError("Tutarı kontrol edin.") from None
    if (not value.is_finite() or value.as_tuple().exponent < -2 or
            value >= Decimal("1000000000000") or value < 0 or (not allow_zero and value == 0)):
        raise ValueError("Tutar pozitif ve en fazla iki ondalık basamaklı olmalıdır.")
    return value


def money_value(name, allow_zero=False):
    return parse_money(request.form.get(name), allow_zero)


def date_value(name, required=False):
    raw = request.form.get(name, "").strip()
    if not raw and not required:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Tarihi kontrol edin.") from None


def form_values(record=None):
    currency = request.form.get("currency", "TRY")
    if currency not in CURRENCIES:
        raise ValueError("Para birimini seçin.")
    responsible_raw = request.form.get("responsible_user_id", "").strip()
    if responsible_raw and not responsible_raw.isdigit():
        raise ValueError("Geçerli bir takip sorumlusu seçin.")
    responsible_id = int(responsible_raw) if responsible_raw else None
    if responsible_id and responsible_id not in {user.id for user in active_responsibles()}:
        raise ValueError("Takip sorumlusu bu şirkette yetkili olmalıdır.")
    amount = money_value("amount")
    if record is not None and amount < record.settled_amount:
        raise ValueError("Toplam tutar gerçekleşen tutardan küçük olamaz.")
    payment_method = request.form.get("payment_method", record.payment_method if record else "unspecified")
    if payment_method not in PAYMENT_METHODS:
        raise ValueError("Ödeme seçeneğini seçin.")
    return dict(
        counterparty=text_value("counterparty", 180, True),
        description=text_value("description", 500, True),
        reference_no=text_value("reference_no", 100),
        project_no=text_value("project_no", 100),
        amount=amount, currency=currency, payment_method=payment_method,
        due_date=date_value("due_date") if not request.form.getlist("installment_due_date") else None,
        responsible_user_id=responsible_id, note=text_value("note", 3000),
    )


def schedule_values(amount, fallback_due, record=None):
    raw_dates = request.form.getlist("installment_due_date")
    raw_amounts = request.form.getlist("installment_amount")
    count_raw = request.form.get("installment_count", "1").strip()
    if not count_raw.isdigit() or not 1 <= int(count_raw) <= MAX_INSTALLMENTS:
        raise ValueError("Taksit sayısı 1 ile 24 arasında olmalıdır.")
    count = int(count_raw)
    if not raw_dates and not raw_amounts:
        if record and len(record.installments) > 1:
            if amount != record.amount or (fallback_due and fallback_due != record.due_date):
                raise ValueError("Taksit planını düzenlemek için her taksit tarihini ve tutarını girin.")
            return [(item.due_date, item.amount) for item in record.installments]
        if record and fallback_due is None:
            fallback_due = record.installments[0].due_date
        if not fallback_due or count != 1:
            raise ValueError("Taksit tarihi ve tutarını girin.")
        return [(fallback_due, amount)]
    if len(raw_dates) != count or len(raw_amounts) != count:
        raise ValueError("Taksit sayısı ile tarih/tutar satırları eşleşmiyor.")
    rows = []
    for raw_date, raw_amount in zip(raw_dates, raw_amounts):
        try:
            due = date.fromisoformat(raw_date)
        except ValueError:
            raise ValueError("Her taksit için geçerli bir tarih girin.") from None
        rows.append((due, parse_money(raw_amount)))
    if rows != sorted(rows, key=lambda row: row[0]):
        raise ValueError("Taksit tarihlerini eskiden yeniye sıralayın.")
    if sum((row[1] for row in rows), Decimal("0")) != amount:
        raise ValueError("Taksit tutarları toplamı ödeme tutarına eşit olmalıdır.")
    return rows


def has_payment_history(record):
    return any(item.legacy_settled_amount or item.transactions for item in record.installments)


def replace_schedule(record, rows):
    if has_payment_history(record):
        current = [(item.due_date, item.amount) for item in record.installments]
        if rows != current:
            raise ValueError("Gerçekleşme kaydı olan taksit planı değiştirilemez.")
        return
    existing = list(record.installments)
    changed = len(existing) != len(rows)
    for index, (due, amount) in enumerate(rows, 1):
        if index <= len(existing):
            item = existing[index - 1]
            if item.due_date != due:
                set_installment_reminders_read(record, item, True)
                reactivate_due_reminder(record, item, due)
            if item.due_date != due or item.amount != amount:
                changed = True
            item.due_date, item.amount = due, amount
        else:
            item = PaymentInstallment(company_id=record.company_id, sequence_no=index,
                                      amount=amount, due_date=due)
            record.installments.append(item)
            db.session.add(item)
    for item in existing[len(rows):]:
        set_installment_reminders_read(record, item, True)
        record.installments.remove(item)
        db.session.delete(item)
    if changed:
        record.updated_at = now_utc()
    record.due_date = rows[0][0]


def set_installment_reminders_read(record, installment, is_read):
    kind = "payment-receivable" if record.direction == "receivable" else "payment-payable"
    Notification.query.filter(
        Notification.company_id == record.company_id,
        Notification.source_key.like(f"{kind}:{installment.id}:%:policy"),
    ).update({Notification.is_read: is_read}, synchronize_session=False)


def reactivate_due_reminder(record, installment, due_date):
    kind = "payment-receivable" if record.direction == "receivable" else "payment-payable"
    Notification.query.filter(
        Notification.company_id == record.company_id,
        Notification.source_key.like(f"{kind}:{installment.id}:{due_date}:%:policy"),
    ).update({Notification.is_read: False}, synchronize_session=False)


def refresh_progress(record):
    record.settled_amount = sum((item.settled_amount for item in record.installments), Decimal("0"))
    record.status = "closed" if record.settled_amount == record.amount else "open"
    record.closed_at = now_utc() if record.status == "closed" else None
    open_dates = [item.due_date for item in record.installments if item.remaining_amount > 0]
    record.due_date = min(open_dates) if open_dates else max(item.due_date for item in record.installments)
    movements = PaymentTransaction.query.filter_by(
        record_id=record.id, company_id=record.company_id).order_by(PaymentTransaction.id).all()
    reversed_ids = {item.reversal_of_id for item in movements if item.reversal_of_id}
    payment_dates = []
    for installment in record.installments:
        active = []
        legacy_remaining = installment.legacy_settled_amount
        for movement in movements:
            if movement.installment_id != installment.id:
                continue
            if movement.amount > 0 and movement.id not in reversed_ids:
                active.append([movement.occurred_on, movement.amount])
            elif movement.amount < 0 and movement.reversal_of_id is None:
                correction = -movement.amount
                for payment in reversed(active):
                    deducted = min(payment[1], correction)
                    payment[1] -= deducted
                    correction -= deducted
                    if correction == 0:
                        break
                legacy_remaining = max(Decimal("0"), legacy_remaining - correction)
        payment_dates.extend(day for day, remaining in active if remaining > 0)
        if legacy_remaining > 0 and installment.legacy_settled_on:
            payment_dates.append(installment.legacy_settled_on)
    record.settled_on = max(payment_dates) if record.settled_amount > 0 and payment_dates else None
    record.confirmed_by_user_id = g.current_user.id


def append_movement(record, installment, amount, occurred_on, note=None, instrument_no=None, reversal_of_id=None):
    if installment.company_id != record.company_id or installment.record_id != record.id:
        abort(404)
    was_complete = installment.remaining_amount == 0
    updated = installment.settled_amount + amount
    if updated < 0 or updated > installment.amount:
        raise ValueError("Taksit gerçekleşen tutarı sıfırın altına inemez veya taksit tutarını aşamaz.")
    installment.settled_amount = updated
    movement = PaymentTransaction(
        company_id=record.company_id, record=record, installment=installment,
        amount=amount, occurred_on=occurred_on, note=note, instrument_no=instrument_no,
        created_by_user_id=g.current_user.id, reversal_of_id=reversal_of_id,
    )
    db.session.add(movement)
    db.session.flush()
    refresh_progress(record)
    if installment.remaining_amount == 0:
        set_installment_reminders_read(record, installment, True)
    elif was_complete:
        reactivate_due_reminder(record, installment, installment.due_date)
    return movement


def displayed_schedule(record=None):
    dates = request.form.getlist("installment_due_date") if request.method == "POST" else []
    amounts = request.form.getlist("installment_amount") if request.method == "POST" else []
    if dates or amounts:
        return [{"due_date": dates[index] if index < len(dates) else "",
                 "amount": amounts[index] if index < len(amounts) else ""}
                for index in range(max(len(dates), len(amounts)))]
    if record:
        return [{"due_date": item.due_date.isoformat(), "amount": str(item.amount)}
                for item in record.installments]
    return [{"due_date": "", "amount": ""}]


def check_version(record):
    if request.form.get("version_id") != str(record.version_id):
        abort(409, description="Kayıt değişti. Sayfayı yenileyin.")


def commit_or_conflict():
    try:
        db.session.commit()
    except (IntegrityError, StaleDataError):
        db.session.rollback()
        abort(409, description="Kayıt değişti veya işlem tamamlanamadı. Sayfayı yenileyin.")


def notify_responsible(record):
    user = record.responsible_user
    if not user or not user.is_active or user.id == g.current_user.id or user.company_id != record.company_id:
        return
    add_user_notification(
        user, f"{record.number_label} ödeme kaydı takibinize atandı.",
        company_id=record.company_id,
        source_key=f"payment-assigned:{record.id}:u{user.id}",
        target_url=url_for("payments.detail", direction=record.direction, record_id=record.id),
        due_date=record.due_date, notification_type="info",
    )


def pdf_upload(upload, record):
    if not upload or not upload.filename:
        return None, None
    if Path(upload.filename).suffix.lower() != ".pdf":
        raise ValueError("Yalnızca PDF dosyası yüklenebilir.")
    from .routes import assert_company_storage_quota, safe_original_filename, upload_storage_path, uploaded_stream_size

    size = uploaded_stream_size(upload)
    if size is None or size <= 0 or size > MAX_PDF_BYTES:
        raise ValueError("PDF boyutu 10 MB veya daha küçük olmalıdır.")
    upload.stream.seek(0)
    if not upload.stream.read(5).startswith(b"%PDF-"):
        raise ValueError("PDF dosyasının içeriği geçersiz.")
    upload.stream.seek(0)
    assert_company_storage_quota(record.company_id, size)
    relative_path, absolute_path = upload_storage_path(f"{uuid4().hex}.pdf", "payments", record.company_id)
    try:
        upload.save(absolute_path)
        if absolute_path.stat().st_size != size:
            raise ValueError("PDF yüklemesi tamamlanamadı.")
        row = PaymentAttachment(
            company_id=record.company_id, record=record,
            original_name=safe_original_filename(upload.filename, "odeme-belgesi.pdf"),
            stored_path=relative_path.as_posix(), size_bytes=size,
            uploaded_by_user_id=g.current_user.id,
        )
        db.session.add(row)
        db.session.flush()
        return row, absolute_path
    except Exception:
        absolute_path.unlink(missing_ok=True)
        raise


@bp.get("/<direction>")
def dashboard(direction):
    direction_or_404(direction)
    query = record_query(direction)
    status = request.args.get("status", "open")
    if status not in {"open", "overdue", "upcoming", "closed", "cancelled", "all", "archived"}:
        status = "open"
    today = date.today()
    if status == "archived":
        query = query.filter(PaymentRecord.archived_at.is_not(None))
    else:
        query = query.filter(PaymentRecord.archived_at.is_(None))
        if status == "overdue":
            query = query.filter_by(status="open").filter(PaymentRecord.due_date < today)
        elif status == "upcoming":
            query = query.filter_by(status="open").filter(PaymentRecord.due_date.between(today, today + timedelta(days=7)))
        elif status != "all":
            query = query.filter_by(status=status)
    search = request.args.get("q", "").strip()[:100]
    if search:
        like = f"%{search}%"
        query = query.filter(or_(PaymentRecord.counterparty.ilike(like), PaymentRecord.description.ilike(like),
                                 PaymentRecord.reference_no.ilike(like), PaymentRecord.project_no.ilike(like)))
    all_open = record_query(direction).filter_by(status="open").filter(PaymentRecord.archived_at.is_(None))
    counts = {
        "open": all_open.count(),
        "overdue": all_open.filter(PaymentRecord.due_date < today).count(),
        "upcoming": all_open.filter(PaymentRecord.due_date.between(today, today + timedelta(days=7))).count(),
    }
    pagination = query.options(
        selectinload(PaymentRecord.installments), joinedload(PaymentRecord.responsible_user)
    ).order_by(
        PaymentRecord.due_date.asc(), PaymentRecord.id.desc()
    ).paginate(page=max(1, request.args.get("page", 1, type=int)), per_page=25, error_out=False)
    return render_template("payments/dashboard.html", direction=direction, status=status,
                           search=search, counts=counts, pagination=pagination)


@bp.route("/<direction>/yeni", methods=["GET", "POST"])
def create(direction):
    direction_or_404(direction)
    if not can_manage():
        abort(403)
    error = None
    if request.method == "POST":
        saved_path = None
        try:
            values = form_values()
            schedule = schedule_values(values["amount"], values["due_date"])
            values["due_date"] = schedule[0][0]
            record = PaymentRecord(direction=direction, created_by_user_id=g.current_user.id, **values)
            assign_current_company(record)
            db.session.add(record)
            db.session.flush()
            replace_schedule(record, schedule)
            db.session.flush()
            _, saved_path = pdf_upload(request.files.get("pdf"), record)
            audit(record, "created")
            notify_responsible(record)
            commit_or_conflict()
            flash("Ödeme kaydı oluşturuldu.", "success")
            return redirect(url_for("payments.detail", direction=direction, record_id=record.id))
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)
        except Exception:
            db.session.rollback()
            if saved_path:
                saved_path.unlink(missing_ok=True)
            raise
        finally:
            if error and saved_path:
                saved_path.unlink(missing_ok=True)
    return render_template("payments/form.html", direction=direction, record=None,
                           values=request.form if request.method == "POST" else {},
                           responsibles=active_responsibles(), schedule_rows=displayed_schedule(),
                           plan_locked=False, error=error), (400 if error else 200)


@bp.get("/<direction>/<int:record_id>")
def detail(direction, record_id):
    record = record_or_404(record_id, direction)
    reversed_ids = {item.reversal_of_id for item in record.transactions if item.reversal_of_id}
    return render_template("payments/detail.html", record=record, direction=direction,
                           reversed_ids=reversed_ids)


@bp.route("/<direction>/<int:record_id>/duzenle", methods=["GET", "POST"])
def edit(direction, record_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id, direction)
    if record.status == "cancelled" or record.archived_at:
        abort(409)
    error = None
    if request.method == "POST":
        check_version(record)
        try:
            old = snapshot(record)
            previous_responsible_id = record.responsible_user_id
            values = form_values(record)
            schedule = schedule_values(values["amount"], values["due_date"], record)
            plan_locked = has_payment_history(record)
            if plan_locked and (values["amount"] != record.amount or values["currency"] != record.currency or
                                values["payment_method"] != record.payment_method or
                                schedule != [(item.due_date, item.amount) for item in record.installments]):
                raise ValueError("Gerçekleşme kaydı olan ödeme planının tutarı, yöntemi ve taksitleri değiştirilemez.")
            values["due_date"] = record.due_date if plan_locked else schedule[0][0]
            for key, value in values.items():
                setattr(record, key, value)
            if not plan_locked:
                replace_schedule(record, schedule)
            audit(record, "updated", old, {"installments": [
                {"due_date": str(due), "amount": str(amount)} for due, amount in schedule]})
            if previous_responsible_id != record.responsible_user_id:
                notify_responsible(record)
            commit_or_conflict()
            flash("Ödeme kaydı güncellendi.", "success")
            return redirect(url_for("payments.detail", direction=direction, record_id=record.id))
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)
    values = request.form if request.method == "POST" else snapshot(record)
    return render_template("payments/form.html", direction=direction, record=record,
                           values=values, responsibles=active_responsibles(),
                           schedule_rows=displayed_schedule(record), plan_locked=has_payment_history(record),
                           error=error), (400 if error else 200)


@bp.post("/<direction>/<int:record_id>/gerceklesen")
def settle(direction, record_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id, direction)
    if record.status == "cancelled" or record.archived_at:
        abort(409)
    check_version(record)
    try:
        amount = money_value("settled_amount", allow_zero=True)
        if amount > record.amount:
            raise ValueError("Gerçekleşen tutar toplamı aşamaz.")
        reason = text_value("reason", 500)
        if amount < record.settled_amount and not reason:
            raise ValueError("Tutar azaltılırken düzeltme gerekçesi yazın.")
        settled_on = date_value("settled_on")
        if amount and not settled_on:
            raise ValueError("Gerçekleşme tarihini girin.")
        old = snapshot(record)
        delta = amount - record.settled_amount
        remaining = abs(delta)
        items = sorted(record.installments, key=lambda item: (item.due_date, item.sequence_no),
                       reverse=delta < 0)
        for item in items:
            capacity = item.remaining_amount if delta > 0 else item.settled_amount
            portion = min(remaining, capacity)
            if portion:
                append_movement(record, item, portion if delta > 0 else -portion,
                                settled_on or date.today(), note=reason)
                remaining -= portion
            if remaining == 0:
                break
        if remaining:
            raise ValueError("Taksit planı ile gerçekleşen tutar uyuşmuyor.")
        if amount == 0:
            record.settled_on = None
        audit(record, "settlement_updated", old, {"reason": reason, "delta": str(delta)})
        commit_or_conflict()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("payments.detail", direction=direction, record_id=record_id))
    flash("Gerçekleşen tutar kaydedildi.", "success")
    return redirect(url_for("payments.detail", direction=direction, record_id=record_id))


@bp.route("/<direction>/<int:record_id>/taksit/<int:installment_id>/islem", methods=["GET", "POST"])
def installment_transaction(direction, record_id, installment_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id, direction)
    installment = PaymentInstallment.query.filter_by(
        id=installment_id, record_id=record.id, company_id=record.company_id).first_or_404()
    if record.status != "open" or record.archived_at or installment.remaining_amount <= 0:
        abort(409)
    error = None
    if request.method == "POST":
        check_version(record)
        try:
            amount = money_value("amount")
            if amount > installment.remaining_amount:
                raise ValueError("Tutar taksitin kalan tutarını aşamaz.")
            occurred_on = date_value("occurred_on", True)
            note = text_value("note", 500)
            instrument_no = text_value("instrument_no", 100)
            old = snapshot(record)
            movement = append_movement(record, installment, amount, occurred_on,
                                       note=note, instrument_no=instrument_no)
            audit(record, "installment_paid", old, {
                "installment_id": installment.id, "movement_id": movement.id,
                "amount": str(amount), "occurred_on": str(occurred_on),
                "instrument_no": instrument_no, "note": note,
            })
            commit_or_conflict()
            flash("Kısmi gerçekleşme kaydedildi." if record.status == "open" else
                  "Tüm taksitler tamamlandı; kayıt kapandı.", "success")
            return redirect(url_for("payments.detail", direction=direction, record_id=record.id))
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)
    return render_template("payments/transaction_form.html", record=record, direction=direction,
                           installment=installment, values=request.form if request.method == "POST" else {},
                           error=error), (400 if error else 200)


@bp.post("/<direction>/<int:record_id>/islem/<int:movement_id>/geri-al")
def reverse_transaction(direction, record_id, movement_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id, direction)
    if record.status == "cancelled" or record.archived_at:
        abort(409)
    check_version(record)
    movement = PaymentTransaction.query.filter_by(
        id=movement_id, record_id=record.id, company_id=record.company_id).first_or_404()
    if movement.amount <= 0 or PaymentTransaction.query.filter_by(reversal_of_id=movement.id).first():
        abort(409)
    try:
        reason = text_value("reason", 500, True)
        installment = PaymentInstallment.query.filter_by(
            id=movement.installment_id, record_id=record.id, company_id=record.company_id).first_or_404()
        old = snapshot(record)
        reversal = append_movement(record, installment, -movement.amount, date.today(),
                                   note=reason, reversal_of_id=movement.id)
        audit(record, "installment_payment_reversed", old, {
            "movement_id": movement.id, "reversal_id": reversal.id, "reason": reason,
        })
        commit_or_conflict()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("payments.detail", direction=direction, record_id=record_id))
    flash("Hareket gerekçesiyle geri alındı; kalan tutar güncellendi.", "success")
    return redirect(url_for("payments.detail", direction=direction, record_id=record_id))


@bp.post("/<direction>/<int:record_id>/iptal")
def cancel(direction, record_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id, direction)
    if record.status != "open" or record.archived_at:
        abort(409)
    check_version(record)
    try:
        reason = text_value("reason", 500, True)
    except ValueError:
        flash("İptal gerekçesi yazın.", "danger")
        return redirect(url_for("payments.detail", direction=direction, record_id=record_id))
    old = snapshot(record)
    record.status = "cancelled"
    record.cancelled_at = now_utc()
    for installment in record.installments:
        set_installment_reminders_read(record, installment, True)
    audit(record, "cancelled", old, {"reason": reason})
    commit_or_conflict()
    flash("Kayıt iptal edildi; geçmişi korunuyor.", "success")
    return redirect(url_for("payments.detail", direction=direction, record_id=record_id))


@bp.post("/<direction>/<int:record_id>/arsivle")
def archive(direction, record_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id, direction)
    if record.status == "open" or record.archived_at:
        abort(409)
    check_version(record)
    old = snapshot(record)
    record.archived_at = now_utc()
    audit(record, "archived", old)
    commit_or_conflict()
    flash("Kayıt arşivlendi.", "success")
    return redirect(url_for("payments.dashboard", direction=direction))


@bp.post("/<direction>/<int:record_id>/belge")
def upload_document(direction, record_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id, direction)
    if record.archived_at:
        abort(409)
    saved_path = None
    try:
        row, saved_path = pdf_upload(request.files.get("pdf"), record)
        if row is None:
            raise ValueError("Bir PDF seçin.")
        audit(record, "document_uploaded", extra={"attachment_id": row.id, "file_name": row.original_name})
        commit_or_conflict()
    except ValueError as exc:
        db.session.rollback()
        if saved_path:
            saved_path.unlink(missing_ok=True)
        flash(str(exc), "danger")
        return redirect(url_for("payments.detail", direction=direction, record_id=record_id))
    except Exception:
        db.session.rollback()
        if saved_path:
            saved_path.unlink(missing_ok=True)
        raise
    flash("PDF eklendi.", "success")
    return redirect(url_for("payments.detail", direction=direction, record_id=record_id))


@bp.get("/<direction>/<int:record_id>/belge/<int:file_id>")
def download_document(direction, record_id, file_id):
    record = record_or_404(record_id, direction)
    row = PaymentAttachment.query.filter_by(
        id=file_id, record_id=record.id, company_id=record.company_id, is_active=True
    ).first_or_404()
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    path = (root / row.stored_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        abort(404)
    record_audit_event("PaymentAttachment", "downloaded", row.original_name,
                       entity_id=row.id, company_id=record.company_id, user_id=g.current_user.id)
    response = send_file(path, mimetype="application/pdf", as_attachment=True, download_name=row.original_name)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.post("/<direction>/<int:record_id>/belge/<int:file_id>/kaldir")
def remove_document(direction, record_id, file_id):
    if not can_manage():
        abort(403)
    record = record_or_404(record_id, direction)
    if record.archived_at:
        abort(409)
    row = PaymentAttachment.query.filter_by(
        id=file_id, record_id=record.id, company_id=record.company_id, is_active=True
    ).first_or_404()
    row.is_active = False
    audit(record, "document_removed", extra={"attachment_id": row.id, "file_name": row.original_name})
    commit_or_conflict()
    flash("PDF kayıttan kaldırıldı; denetim izi korundu.", "success")
    return redirect(url_for("payments.detail", direction=direction, record_id=record_id))
