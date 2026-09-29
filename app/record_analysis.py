"""Local, read-only record triage. No external AI service or automatic decisions."""

from collections import Counter
from datetime import datetime, timezone
from functools import wraps
from itertools import combinations
import re
import unicodedata

from flask import Blueprint, abort, render_template, request, send_file, url_for

from .models import Action, Dof
from .routes import (
    build_simple_xlsx, can_export_reports, can_view_action, can_view_dof,
    can_view_report_center, company_module_enabled, dof_display_status,
    login_required, log_report_export, report_action_status, report_scope_label,
)
from .tenant import current_company_id


bp = Blueprint("record_analysis", __name__, url_prefix="/rapor-merkezi/analiz")
RECORD_LIMIT = 300
PAIR_LIMIT = 20
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
            pairs.append({"left": left, "right": right, "score": round(overlap * 100)})
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
        key: label for key, label in SOURCES.items()
        if key == "actions" or company_module_enabled("if_management")
    }


def analysis_data(source):
    allowed = available_sources()
    if source not in allowed:
        abort(404)
    company_id = current_company_id()
    # An explicit company filter is mandatory even for a global superadmin.
    if not company_id:
        abort(400)
    if source == "actions":
        query = Action.query.filter(Action.company_id == company_id)
        model, can_view = Action, can_view_action
    else:
        query = Dof.query.filter(Dof.company_id == company_id)
        model, can_view = Dof, can_view_dof
    fetched = []
    for record in query.order_by(model.id.desc()).yield_per(100):
        if can_view(record):
            fetched.append(record)
            if len(fetched) > RECORD_LIMIT:
                break
    records = []
    for record in fetched[:RECORD_LIMIT]:
        is_action = source == "actions"
        description = record.description if is_action else record.nonconformity_description
        excerpt = " ".join(str(description or "")[:8192].split())
        status = report_action_status(record) if is_action else dof_display_status(record)
        records.append({
            "id": record.id,
            "code": record.number_label if is_action else record.dof_no,
            "title": record.title or "Başlık yok",
            "excerpt": excerpt[:240] + ("…" if len(excerpt) > 240 else ""),
            "status": status,
            "due": record.termin_date if is_action else record.due_date,
            "url": url_for("main.action_detail", action_id=record.id) if is_action
                else url_for("main.dof_detail", dof_id=record.id),
        })
    pairs, pair_count = similar_pairs(records)
    return {
        "source": source, "source_label": allowed[source], "records": records,
        "pairs": pairs, "pair_count": pair_count, "record_limit": RECORD_LIMIT,
        "limited": len(fetched) > RECORD_LIMIT,
        "statuses": sorted(Counter(record["status"] for record in records).items()),
        "generated_at": datetime.now(timezone.utc),
    }


@bp.get("")
@analysis_access
def dashboard():
    sources = available_sources()
    source = request.args.get("source") or next(iter(sources), None)
    data = analysis_data(source) if source else None
    response = render_template(
        "reports/analysis.html", data=data, sources=sources,
        scope_label=report_scope_label(), can_export=can_export_reports(),
    )
    return response, 200, {"Cache-Control": "no-store"}


@bp.get("/excel")
@analysis_access
def excel():
    if not can_export_reports():
        abort(403)
    data = analysis_data(request.args.get("source") or "actions")
    records = data["records"]
    report = {
        "key": f"local_analysis_{data['source']}",
        "title": f"{data['source_label']} Yerel Analiz",
        "module_key": "report_center",
        "rows": [(r["code"], r["title"], r["status"],
                  r["due"].strftime("%d.%m.%Y") if r["due"] else "", r["excerpt"])
                 for r in records],
    }
    headers = ("Kayıt No", "Başlık", "Durum", "Termin", "Kaynak Metin Alıntısı")
    metadata = [
        ("Şirket", report_scope_label()), ("Oluşturulma UTC", data["generated_at"].isoformat()),
        ("Kapsam", f"Yetkili son {RECORD_LIMIT} kayıt; seçilen modül"),
        ("Sınır uygulandı", "Evet" if data["limited"] else "Hayır"),
        ("Yöntem", "Yerel başlık sözcük benzerliği; üretken AI kullanılmadı"),
        ("İncelenen kayıt", str(len(records))),
        ("Benzer aday çifti", str(data["pair_count"])),
    ]
    metadata.extend((f"Durum: {name}", str(count)) for name, count in data["statuses"])
    metadata.extend((f"Benzer aday: {p['left']['code']} / {p['right']['code']}",
                     f"Başlık benzerliği %{p['score']}") for p in data["pairs"])
    workbook = build_simple_xlsx(headers, report["rows"], sheet_name="Yerel Analiz",
                                 column_widths=(22, 48, 28, 18, 65), metadata=metadata)
    filename = f"yerel-analiz-{data['source']}-{data['generated_at']:%Y%m%d}.xlsx"
    log_report_export(report, "excel", filename)
    response = send_file(workbook, as_attachment=True, download_name=filename,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response.headers["Cache-Control"] = "no-store"
    return response
