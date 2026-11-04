"""Bounded text extraction for document search; never expose extracted text in logs."""

import json
import hashlib
from itertools import islice
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from xml.etree import ElementTree
from zipfile import ZipFile


MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_XML_TOTAL = 24 * 1024 * 1024
MAX_ZIP_PARTS = 512
MAX_TEXT_CHARS = 250_000
MAX_PDF_PAGES = 200
WORKER_TIMEOUT_SECONDS = 25


def normalize_search_text(value):
    value = unicodedata.normalize("NFKD", (value or "").replace("ı", "i"))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.casefold().split())[:MAX_TEXT_CHARS]


def source_fingerprint(source_path, extension, preview_path=None):
    paths = [Path(source_path)]
    if (extension or "").lower().lstrip(".") in {"doc", "xls", "ppt"} and preview_path:
        paths.append(Path(preview_path))
    digest = hashlib.sha256()
    for path in paths:
        if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            return None
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _xml_root(archive, member):
    if member.file_size > MAX_XML_BYTES:
        raise ValueError("xml_too_large")
    with archive.open(member) as stream:
        content = stream.read(MAX_XML_BYTES + 1)
    if len(content) > MAX_XML_BYTES or b"<!DOCTYPE" in content.upper():
        raise ValueError("invalid_xml")
    return ElementTree.fromstring(content)


def _office_text(path, extension):
    parts = []
    total = 0
    text_size = 0
    shared_strings = []
    with ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_PARTS:
            raise ValueError("too_many_parts")
        if extension == "xlsx":
            members.sort(key=lambda member: member.filename != "xl/sharedStrings.xml")
        for member in members:
            name = member.filename
            selected = (
                extension == "docx" and name.startswith("word/")
                and (name == "word/document.xml" or re.fullmatch(r"word/(header|footer|footnotes|endnotes)\d*\.xml", name))
            ) or (
                extension == "xlsx" and (name == "xl/sharedStrings.xml" or re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
            ) or (
                extension == "pptx" and re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            )
            if not selected:
                continue
            total += member.file_size
            if total > MAX_XML_TOTAL:
                raise ValueError("archive_too_large")
            root = _xml_root(archive, member)
            if name == "xl/sharedStrings.xml":
                shared_strings = [
                    "".join(node.text or "" for node in item.iter() if _local_name(node.tag) == "t")
                    for item in root.iter() if _local_name(item.tag) == "si"
                ]
                continue
            if extension == "xlsx":
                for cell in root.iter():
                    if _local_name(cell.tag) != "c":
                        continue
                    value = next((node.text for node in cell.iter() if _local_name(node.tag) == "v"), None)
                    if cell.attrib.get("t") == "s" and value is not None:
                        try:
                            value = shared_strings[int(value)]
                        except (IndexError, ValueError):
                            value = None
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(node.text or "" for node in cell.iter() if _local_name(node.tag) == "t")
                    if value:
                        parts.append(value)
                        text_size += len(value)
            else:
                for node in root.iter():
                    if _local_name(node.tag) == "t" and node.text:
                        parts.append(node.text)
                        text_size += len(node.text)
                        if text_size > MAX_TEXT_CHARS:
                            break
            if text_size > MAX_TEXT_CHARS:
                break
    return normalize_search_text(" ".join(parts))


def _pdf_text(path):
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        return ""
    parts = []
    size = 0
    for page in islice(reader.pages, MAX_PDF_PAGES):
        value = page.extract_text() or ""
        parts.append(value)
        size += len(value)
        if size >= MAX_TEXT_CHARS:
            break
    return normalize_search_text(" ".join(parts))


def extract_text(source_path, extension, preview_path=None):
    extension = (extension or "").lower().lstrip(".")
    path = Path(source_path)
    if not path.is_file():
        return "missing", ""
    if path.stat().st_size > MAX_SOURCE_BYTES:
        return "error", ""
    if extension in {"doc", "xls", "ppt"}:
        path = Path(preview_path) if preview_path else path
        if not path.is_file():
            return "unsupported", ""
        if path.stat().st_size > MAX_SOURCE_BYTES:
            return "error", ""
        extension = "pdf"
    if extension not in {"pdf", "docx", "xlsx", "pptx"}:
        return "unsupported", ""
    try:
        value = _pdf_text(path) if extension == "pdf" else _office_text(path, extension)
    except Exception:
        return "error", ""
    return ("ready" if value else "empty"), value


def extract_text_bounded(source_path, extension, preview_path=None):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.document_search", str(source_path), extension or "", str(preview_path or "")],
            capture_output=True,
            text=True,
            timeout=WORKER_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if payload.get("status") in {"ready", "empty", "missing", "unsupported", "error"}:
                return payload["status"], payload.get("text", "")[:MAX_TEXT_CHARS]
    except (subprocess.SubprocessError, ValueError, OSError):
        pass
    return "error", ""


if __name__ == "__main__":
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except ImportError:
        pass
    status, text = extract_text(sys.argv[1], sys.argv[2], sys.argv[3] or None)
    print(json.dumps({"status": status, "text": text}, ensure_ascii=False))
