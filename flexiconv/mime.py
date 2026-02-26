from __future__ import annotations

import mimetypes
import os
from typing import Optional


def detect_mime(path: str) -> Optional[str]:
    """Best-effort MIME type detection for a file.

    This uses the standard library 'mimetypes' based on file extensions
    and falls back to light content sniffing for common text/XML types.
    """
    mime, _ = mimetypes.guess_type(path)
    if mime:
        return mime

    # Fallback: quick sniff for XML / text / RTF
    try:
        with open(path, "rb") as f:
            snippet = f.read(1024)
    except OSError:
        return None

    lower = snippet.lstrip().lower()
    if lower.startswith(b"<?xml") or b"<tei" in lower or b"<TEI" in snippet:
        return "application/xml"
    if b"{\\rtf" in snippet[:32]:
        return "application/rtf"
    if b"<html" in lower:
        # Prefer hOCR when ocr_page/ocrx_word present
        if b"ocr_page" in lower or b"ocrx_word" in lower:
            return "application/vnd.hocr+html"
        return "text/html"

    # Generic text fallback
    try:
        snippet.decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return None


def mime_to_format(mime: str) -> Optional[str]:
    """Map a MIME type to a flexiconv format name, where supported."""
    mime = mime.split(";")[0].strip().lower()
    if mime in {"application/rtf", "text/rtf"}:
        return "rtf"
    if mime in {"application/vnd.hocr+html"}:
        return "hocr"
    if mime in {"text/html", "application/xhtml+xml"}:
        return "html"
    if mime in {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}:
        return "docx"
    if mime in {"application/exmaralda+xml"}:
        return "exb"
    if mime in {"application/x-tmx+xml"}:
        return "tmx"
    if mime in {"text/plain"}:
        return "txt"
    if mime in {"text/markdown"}:
        return "md"
    if mime in {"text/praat-textgrid"}:
        return "textgrid"
    if mime in {"text/x-toolbox-text", "application/x-toolbox"}:
        return "tbt"
    if mime in {"text/tcf+xml", "application/tcf+xml"}:
        return "tcf"
    if mime in {"text/x-trs", "application/x-trs"}:
        return "trs"
    if mime in {"text/x-vertical", "text/x-vrt"}:
        return "vert"
    if mime in {"application/alto+xml", "text/alto+xml"}:
        return "alto"
    if mime in {"text/x-brat"}:
        return "brat"
    if mime in {"text/folia+xml", "application/folia+xml"}:
        return "folia"
    if mime in {"application/xml", "text/xml", "application/tei+xml"}:
        # XML will be further sniffed later as TEITOK vs generic TEI
        return "tei"
    # Other text/* could later map to html, markdown, etc.
    return None


def describe_unsupported_mime(mime: str) -> str:
    """Human-readable message for a known but unsupported MIME type."""
    return f"MIME type '{mime}' is recognised but not currently supported for reading/writing."


_EXT_TO_INPUT = {
    ".rtf": "rtf",
    ".docx": "docx",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".hocr": "hocr",
    ".page.xml": "pagexml",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".srt": "srt",
    ".eaf": "eaf",
    ".textgrid": "textgrid",
    ".TextGrid": "textgrid",
    ".exb": "exb",
    ".tmx": "tmx",
    ".conllu": "conllu",
    ".conllup": "conllu",
    ".cupt": "conllu",
    ".cha": "chat",
    ".tbt": "tbt",
    ".tbtx": "tbt",
    ".tcf": "tcf",
    ".trs": "trs",
    ".vrt": "vert",
    ".vert": "vert",
    ".alto.xml": "alto",
    ".alto": "alto",
    ".ann": "brat",
    ".folia.xml": "folia",
    ".folia": "folia",
}
_EXT_TO_OUTPUT = {
    ".rtf": "rtf",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".hocr": "hocr",
    ".txt": "txt",
    ".xml": "tei",
    ".tei": "tei",
    ".conllu": "conllu",
    ".srt": "srt",
    ".exb": "exb",
}


def path_to_input_format(path: str) -> Optional[str]:
    """Infer input format from path (extension + MIME/content sniffing)."""
    path_lower = path.lower()
    if path_lower.endswith(".folia.xml"):
        return "folia"
    ext = os.path.splitext(path)[1].lower()
    if ext in _EXT_TO_INPUT:
        return _EXT_TO_INPUT[ext]
    if ext in (".xml", ".tei"):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                snippet = f.read(8192)
        except OSError:
            return None
        # XML-based formats: detect by root tag / key elements.
        lowered = snippet.lower()
        # PAGE XML detection: PcGts root
        if "<pcgts" in lowered:
            return "pagexml"
        # ALTO XML detection: alto root
        if "<alto" in lowered:
            return "alto"
        # EXMARaLDA basic transcription
        if "<basic-transcription" in lowered:
            return "exb"
        # TMX translation memory
        if "<tmx" in lowered:
            return "tmx"
        # ELAN EAF (generic or DoReCo)
        if "<annotation_document" in lowered:
            return "eaf"
        # TCF (D-Spin/WebLicht)
        if "<d-spin" in lowered or "<textcorpus" in lowered:
            return "tcf"
        # Transcriber TRS
        if "<trans" in lowered:
            return "trs"
        # FoLiA (Format for Linguistic Annotation)
        if "<folia" in lowered:
            return "folia"
        # TEI / TEITOK (fall back to TEITOK when <tok> present)
        return "teitok" if "<tok" in snippet else "tei"

    # CoNLL-U / CoNLL-U-Plus detection by content (for unknown extensions).
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            snippet = f.read(4096)
    except OSError:
        snippet = ""
    if snippet:
        # CoNLL-U-Plus header
        if "# global.columns" in snippet:
            return "conllu"
        # Plain CoNLL-U: look for lines like "1\t..."
        for line in snippet.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "\t" in stripped:
                first = stripped.split("\t", 1)[0]
                if first.isdigit():
                    return "conllu"
            break

    # Fallback: MIME-based detection when extension is not known
    mime = detect_mime(path)
    if mime:
        mapped = mime_to_format(mime)
        if mapped and mapped != "tei":
            return mapped
    return None


def path_to_output_format(path: str) -> Optional[str]:
    """Infer output format from path (extension only)."""
    ext = os.path.splitext(path)[1].lower()
    return _EXT_TO_OUTPUT.get(ext)

