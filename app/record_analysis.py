"""Tenant-scoped local decision support for Actions and IF/DÖF records."""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from itertools import combinations
import hashlib
import json
import re
import time
import unicodedata

from flask import Blueprint, abort, g, render_template, request, send_file, url_for
from sqlalchemy.orm import selectinload

from .audit import record_audit_event
from .extensions import db
from .models import Action, AuditLog, Dof
from .request_security import request_client_ip
from .routes import (
    build_simple_xlsx,
    can_export_reports,
    can_view_report_center,
    company_module_enabled,
    current_user_can,
    dof_display_status,
    action_is_finally_completed,
    effectiveness_is_done,
    login_required,
    log_report_export,
    mark_sales_readiness_item_done_without_commit,
    is_superadmin_account,
    report_action_status,
    report_scope_label,
    visible_actions_query,
    visible_dofs_query,
)
from .tenant import current_company_id


bp = Blueprint("record_analysis", __name__, url_prefix="/rapor-merkezi/analiz")
RECORD_LIMIT = 300
SCAN_LIMIT = 1000
PAIR_LIMIT = 20
EVIDENCE_LIMIT = 12
VISIBLE_RECORD_LIMIT = 25
ASSIST_MINUTE_LIMIT = 10
ASSIST_DAY_LIMIT = 100
ASSIST_COMPANY_MINUTE_LIMIT = 30
ASSIST_COMPANY_DAY_LIMIT = 500
SOURCES = {"actions": "Aksiyonlar", "dofs": "IF / DÖF"}
STOP_WORDS = {"ve", "ile", "bir", "bu", "icin", "olan", "olarak", "da", "de"}


def title_tokens(value):
    text = str(value or "")[:200].replace("I", "ı").replace("İ", "i").lower()
    text = text.translate(str.maketrans("ıöüçşğ", "ioucsg"))
    text = unicodedata.normalize("NFKC", text)
    return set(re.findall(r"\w+", text)) - STOP_WORDS


def similar_pairs(records):
    """Jaccard title overlap is a review hint, not proof of duplicate records."""
    indexed = [(record, title_tokens(record["title"])) for record in records]
    pairs = []
    for (left, a), (right, b) in combinations(indexed, 2):
        if min(len(a), len(b)) < 2:
            continue
        overlap = len(a & b) / len(a | b)
        if overlap >= 0.65:
            pairs.append({
                "left": left,
                "right": right,
                "score": round(overlap * 100),
                "common_terms": sorted(a & b)[:8],
            })
    pairs.sort(key=lambda item: (-item["score"], item["left"]["id"], item["right"]["id"]))
    return pairs[:PAIR_LIMIT], len(pairs)


def analysis_access(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not company_module_enabled("report_center") or not can_view_report_center():
            abort(403)
        if not current_company_id():
            abort(400, description="Analiz için bir şirket seçmelisiniz.")
        return view(*args, **kwargs)

    return wrapped


def available_sources():
    return {
        key: label
        for key, label in SOURCES.items()
        if key == "actions" or company_module_enabled("if_management")
    }


def can_run_decision_support():
    return current_user_can("reports.assist")


def _record_facts(record, source, today):
    if source == "actions":
        completed = action_is_finally_completed(record)
        due = record.termin_date
        evidence_present = bool(
            record.closure_evidence_note
            or record.closure_file_stored_name
            or record.closure_files
        )
        return {
            "is_completed": completed,
            "description_present": bool((record.description or "").strip()),
            "responsible_present": bool(record.responsible_user_id or record.responsible_owner),
            "due_present": due is not None,
            "overdue": bool(not completed and due and due < today),
            "due_soon": bool(not completed and due and today <= due <= today + timedelta(days=7)),
            "closure_waiting": bool(record.closure_approval_requested and not completed),
            "closure_evidence_present": evidence_present,
            "effectiveness_required": bool(record.effectiveness_required),
            "effectiveness_done": effectiveness_is_done(record.effectiveness_result),
            "ineffective": record.effectiveness_result == "Etkin Değil",
            "root_cause_present": True,
            "root_cause_method_present": True,
            "corrective_action_present": True,
            "requires_root_cause": False,
        }

    completed = record.status == "Tamamlandı" or record.approval_step == "completed"
    due = record.due_date
    evidence_present = bool(
        (record.closing_evidence or "").strip()
        or record.evidence_stored_name
        or record.files
    )
    requires_root_cause = record.approval_step != "draft" and record.status != "Taslak"
    return {
        "is_completed": completed,
        "description_present": bool((record.nonconformity_description or "").strip()),
        "responsible_present": record.responsible_id is not None,
        "due_present": due is not None,
        "overdue": bool(not completed and due and due < today),
        "due_soon": bool(not completed and due and today <= due <= today + timedelta(days=7)),
        "closure_waiting": record.approval_step in {
            "management_representative", "general_manager_deputy", "effectiveness_review",
        },
        "closure_evidence_present": evidence_present,
        "effectiveness_required": bool(record.effectiveness_required),
        "effectiveness_done": effectiveness_is_done(record.effectiveness_result),
        "ineffective": record.effectiveness_result == "Etkin Değil",
        "root_cause_present": bool((record.root_cause_analysis or "").strip()),
        "root_cause_method_present": bool((record.root_cause_method or "").strip()),
        "corrective_action_present": bool((record.corrective_action or "").strip()),
        "requires_root_cause": requires_root_cause,
    }


def analysis_data(source):
    allowed = available_sources()
    if source not in allowed:
        abort(404)
    company_id = current_company_id()
    if not company_id:
        abort(400)
    if source == "actions":
        query = visible_actions_query().options(selectinload(Action.closure_files))
        model = Action
    else:
        query = visible_dofs_query().options(selectinload(Dof.files))
        model = Dof

    candidates = query.order_by(model.id.desc()).limit(SCAN_LIMIT + 1).all()
    scan_limited = len(candidates) > SCAN_LIMIT
    fetched = candidates[:SCAN_LIMIT]

    today = date.today()
    records = []
    for record in fetched[:RECORD_LIMIT]:
        is_action = source == "actions"
        description = record.description if is_action else record.nonconformity_description
        excerpt = " ".join(str(description or "")[:8192].split())
        records.append({
            "id": record.id,
            "code": record.number_label if is_action else record.dof_no,
            "title": record.title or "Başlık yok",
            "excerpt": excerpt[:240] + ("…" if len(excerpt) > 240 else ""),
            "status": report_action_status(record) if is_action else dof_display_status(record),
            "due": record.termin_date if is_action else record.due_date,
            "url": (
                url_for("main.action_detail", action_id=record.id)
                if is_action else url_for("main.dof_detail", dof_id=record.id)
            ),
            "revision": record.updated_at.isoformat() if record.updated_at else "",
            "facts": _record_facts(record, source, today),
        })
    pairs, pair_count = similar_pairs(records)
    return {
        "source": source,
        "source_label": allowed[source],
        "records": records,
        "pairs": pairs,
        "pair_count": pair_count,
        "record_limit": RECORD_LIMIT,
        "visible_record_limit": VISIBLE_RECORD_LIMIT,
        "scan_limit": SCAN_LIMIT,
        "limited": scan_limited or len(fetched) > RECORD_LIMIT,
        "statuses": sorted(Counter(record["status"] for record in records).items()),
        "generated_at": datetime.now(timezone.utc),
    }


def _finding(rule_code, title, detail, records, tone="warning"):
    unique_records = []
    seen_record_ids = set()
    for record in records:
        record_key = (record.get("source"), record.get("id"))
        if record_key in seen_record_ids:
            continue
        seen_record_ids.add(record_key)
        unique_records.append(record)
    return {
        "rule_code": rule_code,
        "title": title,
        "detail": detail,
        "count": len(unique_records),
        "records": unique_records[:EVIDENCE_LIMIT],
        "tone": tone,
    }


def _matched(records, key, expected=True):
    return [record for record in records if record["facts"].get(key) is expected]


class LocalRulesProvider:
    provider = "local-rules"
    algorithm_version = "local-rules-v1"

    def generate(self, data):
        records = data["records"]
        completed = _matched(records, "is_completed")
        open_records = [record for record in records if not record["facts"]["is_completed"]]
        overdue = _matched(records, "overdue")
        due_soon = _matched(records, "due_soon")
        waiting = _matched(records, "closure_waiting")
        ineffective = _matched(records, "ineffective")

        attention_items = []
        if overdue:
            attention_items.append(_finding(
                "OVERDUE", "Geciken kayıtlar",
                "Termin tarihi geçmiş açık kayıtlar önceliklendirilmelidir.", overdue, "danger",
            ))
        if due_soon:
            attention_items.append(_finding(
                "DUE_SOON", "Yedi gün içinde termin",
                "Yaklaşan kayıtların sorumlu ve kanıt hazırlığı doğrulanmalıdır.", due_soon,
            ))
        if waiting:
            attention_items.append(_finding(
                "WAITING_REVIEW", "İnceleme veya onay bekleyenler",
                "Bekleyen adımın yetkili kullanıcısı ve kanıt yeterliliği kontrol edilmelidir.", waiting, "info",
            ))
        if ineffective:
            attention_items.append(_finding(
                "INEFFECTIVE", "Etkin bulunmayan kayıtlar",
                "Kök neden ve faaliyet planı yeniden değerlendirilmelidir.", ineffective, "danger",
            ))

        data_quality_findings = []
        for code, title, fact, detail in (
            ("DESCRIPTION_MISSING", "Açıklama eksik", "description_present", "Kaynak açıklama tamamlanmalıdır."),
            ("OWNER_MISSING", "Sorumlu eksik", "responsible_present", "Yetkili bir sorumlu atanmalıdır."),
            ("DUE_MISSING", "Termin eksik", "due_present", "İzlenebilir bir termin tarihi belirlenmelidir."),
        ):
            matches = _matched(records, fact, False)
            if matches:
                data_quality_findings.append(_finding(code, title, detail, matches))

        root_cause_missing = [r for r in records if r["facts"]["requires_root_cause"] and not r["facts"]["root_cause_present"]]
        method_missing = [r for r in records if r["facts"]["requires_root_cause"] and not r["facts"]["root_cause_method_present"]]
        corrective_missing = [r for r in records if r["facts"]["requires_root_cause"] and not r["facts"]["corrective_action_present"]]
        completed_without_evidence = [r for r in completed if not r["facts"]["closure_evidence_present"]]
        effectiveness_missing = [
            r for r in completed
            if r["facts"]["effectiveness_required"] and not r["facts"]["effectiveness_done"]
        ]
        for code, title, detail, matches in (
            ("ROOT_CAUSE_MISSING", "Kök neden analizi eksik", "5 Neden veya Balık Kılçığı gibi bir yöntemle neden kanıtlanmalıdır.", root_cause_missing),
            ("ROOT_CAUSE_METHOD_MISSING", "Kök neden yöntemi eksik", "Kullanılan analiz yöntemi kayıt altına alınmalıdır.", method_missing),
            ("CORRECTIVE_ACTION_MISSING", "Düzeltici faaliyet eksik", "Doğrulanan kök nedene bağlı faaliyet tanımlanmalıdır.", corrective_missing),
            ("CLOSURE_EVIDENCE_MISSING", "Kapanış kanıtı eksik", "Tamamlanan kayıt için objektif kapanış kanıtı eklenmelidir.", completed_without_evidence),
            ("EFFECTIVENESS_MISSING", "Etkinlik sonucu eksik", "Gerekli etkinlik kontrolü bağımsız kanıtla tamamlanmalıdır.", effectiveness_missing),
        ):
            if matches:
                data_quality_findings.append(_finding(code, title, detail, matches))

        cause_hypotheses = [
            {
                "rule_code": "CAUSE_REVIEW_AREAS",
                "title": f"{record['code']} için doğrulanacak neden alanları",
                "detail": "Yöntem, insan, ekipman, malzeme, ölçüm ve çevre başlıklarında kanıt toplayın; belirtiyi kök neden olarak kabul etmeyin.",
                "record": record,
            }
            for record in root_cause_missing[:EVIDENCE_LIMIT]
        ]

        recommended_next_steps = []
        if overdue:
            recommended_next_steps.append(_finding(
                "REVIEW_OVERDUE", "Geciken planı gözden geçirin",
                "Sorumlu, engel ve gerçekçi yeni termin yetkili kullanıcı tarafından doğrulansın.", overdue, "danger",
            ))
        if root_cause_missing or corrective_missing:
            recommended_next_steps.append(_finding(
                "COMPLETE_CAUSE_ACTION", "Neden-faaliyet bağını tamamlayın",
                "Önce kök nedeni kanıtlayın; ardından nedene doğrudan bağlı düzeltici faaliyet seçin.",
                root_cause_missing + corrective_missing,
            ))
        if completed_without_evidence or effectiveness_missing:
            recommended_next_steps.append(_finding(
                "VERIFY_CLOSURE", "Kapanış ve etkinlik kanıtını tamamlayın",
                "Kapanış kararı vermeden önce uygulama ve etkinlik kanıtlarını doğrulayın.",
                completed_without_evidence + effectiveness_missing,
            ))
        if data["pairs"]:
            pair_records, seen = [], set()
            for pair in data["pairs"]:
                for record in (pair["left"], pair["right"]):
                    if record["id"] not in seen:
                        seen.add(record["id"])
                        pair_records.append(record)
            recommended_next_steps.append(_finding(
                "REVIEW_DUPLICATES", "Benzer kayıt adaylarını karşılaştırın",
                "Yeni kayıt açmadan veya birleştirmeden önce kapsam, neden ve kanıtları insan incelemesiyle karşılaştırın.",
                pair_records, "info",
            ))
        if not recommended_next_steps:
            recommended_next_steps.append(_finding(
                "MAINTAIN", "Mevcut takibi sürdürün",
                "Kritik bir kural bulgusu oluşmadı; termin ve etkinlik kontrollerini planlandığı şekilde sürdürün.",
                records[:1], "success",
            ))

        summary = [
            f"Yetkiniz kapsamındaki {len(records)} kaydın {len(open_records)} tanesi açık, {len(completed)} tanesi tamamlanmış durumda.",
            f"{len(overdue)} geciken ve önümüzdeki yedi gün içinde termini olan {len(due_soon)} kayıt bulunuyor.",
            f"{len(data_quality_findings)} veri kalitesi kuralı ile {data['pair_count']} benzer kayıt adayı tespit edildi.",
        ]
        input_hash = hashlib.sha256(json.dumps([
            {
                "id": record["id"],
                "revision": record["revision"],
                "title": record.get("title"),
                "status": record.get("status"),
                "due": (
                    record["due"].isoformat()
                    if record.get("due") else None
                ),
                "facts": record["facts"],
            }
            for record in records
        ], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        result_payload = {
            "summary": summary,
            "attention": [
                (item["rule_code"], [record["id"] for record in item["records"]])
                for item in attention_items
            ],
            "quality": [
                (item["rule_code"], [record["id"] for record in item["records"]])
                for item in data_quality_findings
            ],
            "causes": [item["record"]["id"] for item in cause_hypotheses],
            "recommendations": [
                (item["rule_code"], [record["id"] for record in item["records"]])
                for item in recommended_next_steps
            ],
            "pairs": data["pair_count"],
        }
        result_hash = hashlib.sha256(json.dumps(
            result_payload, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")).hexdigest()
        return {
            "provider": self.provider,
            "algorithm_version": self.algorithm_version,
            "summary": summary,
            "attention_items": attention_items,
            "data_quality_findings": data_quality_findings,
            "cause_hypotheses": cause_hypotheses,
            "recommended_next_steps": recommended_next_steps,
            "input_hash": input_hash,
            "result_hash": result_hash,
            "caveats": (
                "Yerel kurallarla üretilmiştir; veriler dış servise gönderilmez.",
                "Bulgular karar değildir. Kök neden, sorumlu, termin, onay ve kapanış yetkili kullanıcı tarafından doğrulanır.",
                "Asistan kaynak kaydı oluşturmaz, değiştirmez, birleştirmez veya kapatmaz.",
            ),
        }


def decision_support_result(data):
    return LocalRulesProvider().generate(data)


def enforce_decision_support_rate_limit():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    company_id = current_company_id()
    user_id = g.current_user.id
    ip_address = request_client_ip(default=None)
    base = AuditLog.query.filter(
        AuditLog.entity_type == "DecisionSupport",
        AuditLog.action == "generated",
        AuditLog.company_id == company_id,
    )
    user_minute = base.filter(
        AuditLog.user_id == user_id, AuditLog.created_at >= now - timedelta(minutes=1)
    ).count()
    user_day = base.filter(
        AuditLog.user_id == user_id, AuditLog.created_at >= now - timedelta(days=1)
    ).count()
    company_minute = base.filter(
        AuditLog.created_at >= now - timedelta(minutes=1)
    ).count()
    company_day = base.filter(
        AuditLog.created_at >= now - timedelta(days=1)
    ).count()
    ip_minute = 0
    if ip_address:
        ip_minute = base.filter(
            AuditLog.ip_address == ip_address,
            AuditLog.created_at >= now - timedelta(minutes=1),
        ).count()
    if user_minute >= ASSIST_MINUTE_LIMIT or ip_minute >= ASSIST_MINUTE_LIMIT:
        abort(429, description="Karar desteği dakikalık kullanım sınırına ulaştı.")
    if user_day >= ASSIST_DAY_LIMIT:
        abort(429, description="Karar desteği günlük kullanım sınırına ulaştı.")
    if company_minute >= ASSIST_COMPANY_MINUTE_LIMIT:
        abort(429, description="Şirket karar desteği dakikalık kullanım sınırına ulaştı.")
    if company_day >= ASSIST_COMPANY_DAY_LIMIT:
        abort(429, description="Şirket karar desteği günlük kullanım sınırına ulaştı.")


def render_analysis(data, decision_support=None):
    return (
        render_template(
            "reports/analysis.html",
            data=data,
            decision_support=decision_support,
            sources=available_sources(),
            scope_label=report_scope_label(),
            can_assist=can_run_decision_support(),
            can_export=can_export_reports(),
        ),
        200,
        {"Cache-Control": "no-store"},
    )


@bp.get("")
@analysis_access
def dashboard():
    sources = available_sources()
    source = request.args.get("source") or next(iter(sources), None)
    return render_analysis(analysis_data(source) if source else None)


@bp.post("/calistir")
@analysis_access
def run():
    if not can_run_decision_support():
        abort(403)
    enforce_decision_support_rate_limit()
    started = time.perf_counter()
    source = request.form.get("source", "").strip()
    data = analysis_data(source)
    result = decision_support_result(data)
    duration_ms = round((time.perf_counter() - started) * 1000)
    record_audit_event(
        "DecisionSupport",
        "generated",
        "Yerel karar destek analizi çalıştırıldı",
        entity_id=f"{source}:{result['result_hash'][:16]}",
        details={
            "source": source,
            "provider": result["provider"],
            "algorithm_version": result["algorithm_version"],
            "record_count": len(data["records"]),
            "attention_count": len(result["attention_items"]),
            "quality_rule_count": len(result["data_quality_findings"]),
            "recommendation_count": len(result["recommended_next_steps"]),
            "duplicate_pair_count": data["pair_count"],
            "input_hash": result["input_hash"],
            "result_hash": result["result_hash"],
            "duration_ms": duration_ms,
        },
        commit=False,
    )
    if is_superadmin_account():
        mark_sales_readiness_item_done_without_commit("competitor_ai_assistants")
    db.session.commit()
    return render_analysis(data, result)


@bp.post("/excel")
@analysis_access
def excel():
    if not can_export_reports() or not can_run_decision_support():
        abort(403)
    enforce_decision_support_rate_limit()
    started = time.perf_counter()
    data = analysis_data(request.args.get("source") or "actions")
    support = decision_support_result(data)
    rows = []
    for group, findings in (
        ("Dikkat", support["attention_items"]),
        ("Veri Kalitesi", support["data_quality_findings"]),
        ("Önerilen Adım", support["recommended_next_steps"]),
    ):
        for item in findings:
            for record in item["records"] or [None]:
                rows.append((
                    group,
                    item["rule_code"],
                    item["title"],
                    item["detail"],
                    item["count"],
                    record["code"] if record else "",
                    record["title"] if record else "",
                ))
    for item in support["cause_hypotheses"]:
        record = item["record"]
        rows.append((
            "Kök Neden İncelemesi",
            "HUMAN_REVIEW",
            item["title"],
            item["detail"],
            1,
            record["code"],
            record["title"],
        ))
    for record in data["records"]:
        rows.append((
            "Kaynak Kayıt", record["code"], record["title"], record["status"], "",
            record["due"].strftime("%d.%m.%Y") if record["due"] else "",
            record["excerpt"],
        ))
    report = {
        "key": f"decision_support_{data['source']}",
        "title": f"{data['source_label']} Yerel Karar Destek",
        "module_key": "report_center",
        "rows": rows,
    }
    metadata = [
        ("Şirket", report_scope_label()),
        ("Oluşturulma UTC", data["generated_at"].isoformat()),
        ("Kapsam", f"Yetkili son {RECORD_LIMIT} kayıt; SQL tarama sınırı {SCAN_LIMIT}"),
        ("Sağlayıcı", support["provider"]),
        ("Algoritma", support["algorithm_version"]),
        ("Benzerlik yöntemi", "Yerel başlık sözcük benzerliği"),
        ("Veri aktarımı", "Harici servise veri gönderilmedi"),
        ("İncelenen kayıt", str(len(data["records"]))),
        ("Benzer aday çifti", str(data["pair_count"])),
        ("Girdi özeti", support["input_hash"]),
        ("Sonuç özeti", support["result_hash"]),
    ]
    metadata.extend((f"Özet {index}", text) for index, text in enumerate(support["summary"], 1))
    workbook = build_simple_xlsx(
        (
            "Tür", "Kural / Kayıt", "Başlık", "Bulgu / Durum",
            "Adet / Kanıt No", "Termin / Kanıt", "Kaynak / Kanıt Başlığı",
        ),
        rows,
        sheet_name="Karar Destek",
        column_widths=(20, 28, 42, 70, 12, 18, 65),
        metadata=metadata,
    )
    filename = f"karar-destek-{data['source']}-{data['generated_at']:%Y%m%d}.xlsx"
    record_audit_event(
        "DecisionSupport",
        "generated",
        "Yerel karar destek Excel analizi çalıştırıldı",
        entity_id=f"{data['source']}:{support['result_hash'][:16]}",
        details={
            "source": data["source"],
            "provider": support["provider"],
            "algorithm_version": support["algorithm_version"],
            "record_count": len(data["records"]),
            "input_hash": support["input_hash"],
            "result_hash": support["result_hash"],
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "output": "excel",
        },
        commit=False,
    )
    if is_superadmin_account():
        mark_sales_readiness_item_done_without_commit("competitor_ai_assistants")
    log_report_export(report, "excel", filename)
    response = send_file(
        workbook,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Cache-Control"] = "no-store"
    return response
