from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
import re
from statistics import mean
from zipfile import ZipFile
from xml.etree import ElementTree as ET


SPREADSHEET_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
RELATIONSHIP_NS = {
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships"
}

CONCRETE_TEST_FILE = Path(__file__).parent / "data" / "concrete_tests.xlsx"
CONCRETE_RESULT_SHEET = "GENEL SONUÇ"

CONCRETE_COLUMN_MAP = {
    "A": "test_no",
    "B": "break_no",
    "C": "sample_date",
    "D": "customer",
    "E": "element",
    "F": "cement_name",
    "G": "aggregate_place",
    "H": "natural_sand",
    "I": "powder_0_5",
    "J": "aggregate_5_15",
    "K": "aggregate_15_25",
    "L": "cement_kg",
    "M": "dmax",
    "N": "additive_company",
    "O": "hyper_name",
    "P": "hyper_percent",
    "Q": "hyper_kg",
    "R": "super_name",
    "S": "super_percent",
    "T": "super_kg",
    "U": "water",
    "V": "water_cement_ratio",
    "W": "description",
    "X": "slump_0",
    "Y": "slump_30",
    "Z": "tbha",
    "AA": "air_temperature",
    "AB": "concrete_temperature",
    "AC": "safe_strength_2",
    "AD": "safe_strength_7",
    "AE": "safe_strength_28",
    "AF": "transition_7_28",
    "AG": "strength_2_date",
    "AH": "strength_2",
    "AI": "strength_7_date",
    "AJ": "strength_7_1",
    "AK": "strength_7_2",
    "AL": "strength_7_3",
    "AM": "strength_28_date",
    "AN": "strength_28_1",
    "AO": "strength_28_2",
    "AP": "strength_28_3",
    "AQ": "prestress_1",
    "AR": "prestress_2",
    "AS": "prestress_3",
}

CONCRETE_DATE_FIELDS = {
    "sample_date",
    "strength_2_date",
    "strength_7_date",
    "strength_28_date",
}
CONCRETE_TEXT_FIELDS = {
    "customer",
    "element",
    "cement_name",
    "aggregate_place",
    "natural_sand",
    "powder_0_5",
    "aggregate_5_15",
    "aggregate_15_25",
    "additive_company",
    "hyper_name",
    "super_name",
    "description",
}


def _column_from_ref(cell_ref):
    match = re.match(r"([A-Z]+)", cell_ref or "")
    return match.group(1) if match else ""


def _row_from_ref(cell_ref):
    match = re.match(r"[A-Z]+(\d+)", cell_ref or "")
    return int(match.group(1)) if match else 0


def _read_shared_strings(workbook):
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []

    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    strings = []
    for item in root.findall("m:si", SPREADSHEET_NS):
        strings.append("".join(text.text or "" for text in item.findall(".//m:t", SPREADSHEET_NS)))
    return strings


def _read_sheet_paths(workbook):
    workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
    rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    rels = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in rels_root.findall("pr:Relationship", RELATIONSHIP_NS)
    }
    sheets = {}
    for sheet in workbook_root.findall(".//m:sheet", SPREADSHEET_NS):
        relation_id = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        target = rels[relation_id]
        sheet_path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
        sheets[sheet.attrib["name"]] = sheet_path
    return sheets


def _cell_value(cell, shared_strings):
    value = cell.find("m:v", SPREADSHEET_NS)
    inline_string = cell.find("m:is", SPREADSHEET_NS)
    if cell.attrib.get("t") == "s" and value is not None:
        index = int(value.text)
        return shared_strings[index] if index < len(shared_strings) else ""
    if cell.attrib.get("t") == "inlineStr" and inline_string is not None:
        return "".join(text.text or "" for text in inline_string.findall(".//m:t", SPREADSHEET_NS))
    return value.text if value is not None else ""


def _clean_text(value):
    value = str(value or "").strip()
    return "" if value in {"-", "#DIV/0!", "#VALUE!"} else value


def _float_value(value):
    try:
        if value in (None, "", "#DIV/0!", "#VALUE!"):
            return None
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _excel_date(value):
    numeric_value = _float_value(value)
    if numeric_value is None:
        return None
    return date(1899, 12, 30) + timedelta(days=int(numeric_value))


def _format_date(value):
    return value.strftime("%d.%m.%Y") if value else "-"


def _format_number(value, digits=1):
    number = _float_value(value)
    if number is None:
        return "-"
    rounded = round(number, digits)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{digits}f}".replace(".", ",")


def _average(values):
    numbers = [_float_value(value) for value in values]
    numbers = [number for number in numbers if number is not None]
    return mean(numbers) if numbers else None


def _concrete_grade(description):
    match = re.search(r"\bC\s*(\d{2,3})\b", description or "", re.IGNORECASE)
    return f"C{match.group(1)}" if match else ""


def _status_for_row(row):
    grade = row["grade"]
    safe_strength_28 = _float_value(row.get("safe_strength_28"))
    average_strength_28 = row["average_strength_28"]
    if safe_strength_28 is None and average_strength_28 is None:
        return "28 Gün Bekliyor", "warning"

    if not grade:
        return "Kayıtlı", "muted"

    target = _float_value(grade.replace("C", ""))
    if target is None:
        return "Kayıtlı", "muted"

    control_value = safe_strength_28 if safe_strength_28 is not None else average_strength_28
    if control_value >= target:
        return "Uygun", "success"
    return "Kontrol Gerekli", "danger"


def _normalize_row(raw_row, index):
    row = {"index": index}
    for key in CONCRETE_COLUMN_MAP.values():
        raw_value = raw_row.get(key, "")
        if key in CONCRETE_DATE_FIELDS:
            row[key] = _excel_date(raw_value)
        elif key in CONCRETE_TEXT_FIELDS:
            row[key] = _clean_text(raw_value)
        else:
            row[key] = _float_value(raw_value)

    row["grade"] = _concrete_grade(row["description"])
    row["average_strength_7"] = _average(
        [row.get("strength_7_1"), row.get("strength_7_2"), row.get("strength_7_3")]
    )
    row["average_strength_28"] = _average(
        [row.get("strength_28_1"), row.get("strength_28_2"), row.get("strength_28_3")]
    )
    row["average_prestress"] = _average(
        [row.get("prestress_1"), row.get("prestress_2"), row.get("prestress_3")]
    )
    row["status"], row["status_tone"] = _status_for_row(row)

    row["test_no_display"] = _format_number(row.get("test_no"), 0)
    row["break_no_display"] = _format_number(row.get("break_no"), 0)
    row["sample_date_display"] = _format_date(row.get("sample_date"))
    row["strength_2_date_display"] = _format_date(row.get("strength_2_date"))
    row["strength_7_date_display"] = _format_date(row.get("strength_7_date"))
    row["strength_28_date_display"] = _format_date(row.get("strength_28_date"))
    row["safe_strength_7_display"] = _format_number(row.get("safe_strength_7"), 1)
    row["safe_strength_28_display"] = _format_number(row.get("safe_strength_28"), 1)
    row["average_strength_7_display"] = _format_number(row.get("average_strength_7"), 1)
    row["average_strength_28_display"] = _format_number(row.get("average_strength_28"), 1)
    row["average_prestress_display"] = _format_number(row.get("average_prestress"), 1)
    row["strength_2_display"] = _format_number(row.get("strength_2"), 1)
    row["cement_kg_display"] = _format_number(row.get("cement_kg"), 0)
    row["water_display"] = _format_number(row.get("water"), 0)
    row["water_cement_ratio_display"] = _format_number(row.get("water_cement_ratio"), 2)
    row["dmax_display"] = _format_number(row.get("dmax"), 0)
    row["tbha_display"] = _format_number(row.get("tbha"), 0)
    row["hyper_percent_display"] = _format_number(row.get("hyper_percent"), 2)
    row["hyper_kg_display"] = _format_number(row.get("hyper_kg"), 2)
    row["super_percent_display"] = _format_number(row.get("super_percent"), 2)
    row["super_kg_display"] = _format_number(row.get("super_kg"), 2)
    row["air_temperature_display"] = _format_number(row.get("air_temperature"), 1)
    row["concrete_temperature_display"] = _format_number(row.get("concrete_temperature"), 1)
    row["slump_display"] = " / ".join(
        value
        for value in (
            _format_number(row.get("slump_0"), 0),
            _format_number(row.get("slump_30"), 0),
        )
        if value != "-"
    )
    row["temperature_display"] = " / ".join(
        value
        for value in (
            _format_number(row.get("air_temperature"), 1),
            _format_number(row.get("concrete_temperature"), 1),
        )
        if value != "-"
    )
    return row


@lru_cache(maxsize=1)
def load_concrete_test_rows():
    if not CONCRETE_TEST_FILE.exists():
        return tuple()

    with ZipFile(CONCRETE_TEST_FILE) as workbook:
        shared_strings = _read_shared_strings(workbook)
        sheet_paths = _read_sheet_paths(workbook)
        sheet_path = sheet_paths.get(CONCRETE_RESULT_SHEET) or next(iter(sheet_paths.values()))
        sheet_root = ET.fromstring(workbook.read(sheet_path))

        rows = []
        for sheet_row in sheet_root.findall(".//m:sheetData/m:row", SPREADSHEET_NS):
            if int(sheet_row.attrib.get("r", "0")) < 5:
                continue

            raw_row = {}
            for cell in sheet_row.findall("m:c", SPREADSHEET_NS):
                column = _column_from_ref(cell.attrib.get("r"))
                key = CONCRETE_COLUMN_MAP.get(column)
                if key:
                    raw_row[key] = _cell_value(cell, shared_strings)

            if not any(
                raw_row.get(field)
                for field in ("sample_date", "customer", "element", "description")
            ):
                continue

            rows.append(_normalize_row(raw_row, len(rows) + 1))

    return tuple(rows)


def _option_values(rows, key):
    return sorted({row[key] for row in rows if row.get(key)}, key=str.casefold)


def _matches_query(row, query):
    if not query:
        return True
    searchable = " ".join(
        str(row.get(key) or "")
        for key in (
            "test_no_display",
            "break_no_display",
            "customer",
            "element",
            "grade",
            "description",
        )
    )
    return query.casefold() in searchable.casefold()


def _filter_rows(rows, filters):
    filtered_rows = []
    for row in rows:
        if not _matches_query(row, filters["search"]):
            continue
        if filters["customer"] and row.get("customer") != filters["customer"]:
            continue
        if filters["element"] and row.get("element") != filters["element"]:
            continue
        if filters["grade"] and row.get("grade") != filters["grade"]:
            continue
        if filters["status"] and row.get("status") != filters["status"]:
            continue
        filtered_rows.append(row)
    return filtered_rows


def _metric_average(rows, key):
    values = [_float_value(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    return _format_number(mean(values), 1) if values else "-"


def concrete_test_context(args):
    rows = list(load_concrete_test_rows())
    filters = {
        "search": args.get("search", "").strip(),
        "customer": args.get("customer", "").strip(),
        "element": args.get("element", "").strip(),
        "grade": args.get("grade", "").strip(),
        "status": args.get("status", "").strip(),
    }
    filtered_rows = _filter_rows(rows, filters)

    return {
        "rows": filtered_rows,
        "all_rows_count": len(rows),
        "filtered_count": len(filtered_rows),
        "filters": filters,
        "customer_options": _option_values(rows, "customer"),
        "element_options": _option_values(rows, "element"),
        "grade_options": _option_values(rows, "grade"),
        "status_options": _option_values(rows, "status"),
        "average_28": _metric_average(filtered_rows, "average_strength_28"),
        "suitable_count": sum(1 for row in filtered_rows if row["status"] == "Uygun"),
        "waiting_count": sum(1 for row in filtered_rows if row["status"] == "28 Gün Bekliyor"),
        "control_count": sum(1 for row in filtered_rows if row["status"] == "Kontrol Gerekli"),
    }
