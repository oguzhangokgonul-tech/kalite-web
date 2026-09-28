from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime


REPORT_PERIOD_CHOICES = (
    ("month", "Aylık"),
    ("quarter", "3 Aylık"),
    ("half_year", "6 Aylık"),
    ("year", "Yıllık"),
)
REPORT_PERIOD_KEYS = {key for key, _label in REPORT_PERIOD_CHOICES}
TURKISH_MONTHS = (
    "",
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)


@dataclass(frozen=True)
class ReportPeriod:
    key: str
    label: str
    code: str
    start_date: date
    end_date: date
    anchor_date: date

    @property
    def range_label(self):
        return f"{self.start_date:%d.%m.%Y} - {self.end_date:%d.%m.%Y}"

    @property
    def query_args(self):
        return {"period": self.key, "anchor": self.anchor_date.isoformat()}


def resolve_report_period(period_key=None, anchor_value=None, *, today=None):
    if not period_key:
        return None
    if period_key not in REPORT_PERIOD_KEYS:
        raise ValueError("invalid_period")

    today = today or date.today()
    if anchor_value:
        try:
            anchor = date.fromisoformat(str(anchor_value))
        except (TypeError, ValueError) as error:
            raise ValueError("invalid_anchor") from error
    else:
        anchor = today
    if anchor > today:
        raise ValueError("future_anchor")

    if period_key == "month":
        start = anchor.replace(day=1)
        natural_end = anchor.replace(day=monthrange(anchor.year, anchor.month)[1])
        code = f"{anchor.year}-M{anchor.month:02d}"
        label = f"Aylık · {TURKISH_MONTHS[anchor.month]} {anchor.year}"
    elif period_key == "quarter":
        quarter = ((anchor.month - 1) // 3) + 1
        start_month = ((quarter - 1) * 3) + 1
        end_month = start_month + 2
        start = date(anchor.year, start_month, 1)
        natural_end = date(anchor.year, end_month, monthrange(anchor.year, end_month)[1])
        code = f"{anchor.year}-Q{quarter}"
        label = f"3 Aylık · {anchor.year} / {quarter}. Çeyrek"
    elif period_key == "half_year":
        half = 1 if anchor.month <= 6 else 2
        start_month = 1 if half == 1 else 7
        end_month = 6 if half == 1 else 12
        start = date(anchor.year, start_month, 1)
        natural_end = date(anchor.year, end_month, monthrange(anchor.year, end_month)[1])
        code = f"{anchor.year}-H{half}"
        label = f"6 Aylık · {anchor.year} / {half}. Yarıyıl"
    else:
        start = date(anchor.year, 1, 1)
        natural_end = date(anchor.year, 12, 31)
        code = f"{anchor.year}-Y"
        label = f"Yıllık · {anchor.year}"

    end = min(natural_end, today) if start <= today <= natural_end else natural_end
    return ReportPeriod(period_key, label, code, start, end, anchor)


def parse_report_date(value):
    if value is None or value == "" or value == "-":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    try:
        parsed_month = datetime.strptime(text, "%m.%Y").date()
    except ValueError:
        return None
    return parsed_month.replace(day=1)


def apply_period_to_report(report, period, *, date_headers=(), mode="activity"):
    result = dict(report)
    result["period"] = period
    result["period_mode"] = mode
    result["date_basis"] = " / ".join(date_headers) if date_headers else "Kayıt hareket tarihi"
    result["undated_count"] = 0
    if period is None or mode == "snapshot":
        result["source_row_count"] = len(result.get("rows", ()))
        return result

    headers = list(result.get("headers", ()))
    indexes = [headers.index(header) for header in date_headers if header in headers]
    if not indexes:
        result["period_mode"] = "snapshot"
        result["source_row_count"] = len(result.get("rows", ()))
        return result

    rows = list(result.get("rows", ()))
    filtered_rows = []
    undated_count = 0
    for row in rows:
        dates = [parse_report_date(row[index]) for index in indexes if index < len(row)]
        dates = [item for item in dates if item is not None]
        if not dates:
            undated_count += 1
            continue
        if any(period.start_date <= item <= period.end_date for item in dates):
            filtered_rows.append(row)

    result["rows"] = filtered_rows
    result["source_row_count"] = len(rows)
    result["undated_count"] = undated_count
    return result


def report_period_metadata(report, *, scope_label, generated_by, generated_at):
    period = report.get("period")
    period_mode = report.get("period_mode", "activity")
    mode_label = "Dönem hareketi" if period_mode == "activity" else "Dönem sonu görünümü"
    return (
        ("Rapor", report.get("title", "-")),
        ("Modül", report.get("module_name") or report.get("module_key") or "Genel"),
        ("Şirket / Kapsam", scope_label),
        ("Dönem", period.label if period else "Tüm kayıtlar"),
        ("Dönem Kodu", period.code if period else "ALL"),
        ("Tarih Aralığı", period.range_label if period else "Sınırsız"),
        ("Rapor Tipi", mode_label),
        ("Tarih Esası", report.get("date_basis") or "Kayıt hareket tarihi"),
        ("Oluşturan", generated_by or "Sistem"),
        ("Oluşturulma", generated_at.strftime("%d.%m.%Y %H:%M UTC")),
        ("Kayıt Sayısı", len(report.get("rows", ()))),
        ("Tarihsiz Hariç Tutulan", report.get("undated_count", 0)),
        ("Protokol", "VolkaPortal Dönemsel Raporlama v1"),
    )
