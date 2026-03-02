from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
import subprocess
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from . import (
    load_rtf,
    load_tei_p5,
    load_teitok,
    save_rtf,
    save_tei_p5,
    save_teitok,
    __version__,
)
from .registry import InputFormat, OutputFormat, registry
from .mime import describe_unsupported_mime, detect_mime, mime_to_format, path_to_input_format, path_to_output_format
from .io.teitok_xml import _find_teitok_project_root, find_duplicate_teitok_files, teitok_text_fingerprint, teitok_text_fingerprint_hash
from .io.txt import document_to_plain_text, normalize_text_for_fingerprint
from .io.near_dup import (
    lsh_bands,
    minhash_signature,
    signature_from_blob,
    signature_similarity,
    signature_to_blob,
    shingle_text,
)


def _lazy_loader(module: str, attr: str):
    """Create a loader callable that imports the real function on first use."""

    def _wrapped(*args, **kwargs):
        mod = __import__(module, fromlist=[attr])
        func = getattr(mod, attr)
        return func(*args, **kwargs)

    return _wrapped


def _lazy_saver(module: str, attr: str):
    """Create a saver callable that imports the real function on first use."""

    def _wrapped(*args, **kwargs):
        mod = __import__(module, fromlist=[attr])
        func = getattr(mod, attr)
        return func(*args, **kwargs)

    return _wrapped


def _linux_safe_basename(path: str) -> str:
    """Return a Linux-safe basename: no spaces, ASCII when possible, safe for filenames."""
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    # Normalize (NFD) so accents become base + combining; drop combining marks
    stem_nfd = unicodedata.normalize("NFD", stem)
    safe = "".join(
        c for c in stem_nfd if unicodedata.category(c) != "Mn"
    )
    # Keep only ASCII letters, digits, and ._-
    safe = "".join(
        c if ord(c) < 128 and (c.isalnum() or c in "._-") else "_"
        for c in safe
    )
    safe = re.sub(r"_+", "_", safe).strip("._-") or "document"
    return safe + (ext.lower() if ext else ".xml")


_FMT_DEFAULT_EXT = {
    "teitok": ".xml",
    "tei": ".xml",
    "rtf": ".rtf",
    "txt": ".txt",
    "html": ".html",
    "hocr": ".hocr",
    "conllu": ".conllu",
    "srt": ".srt",
    "doreco": ".eaf",
    "exb": ".exb",
    "raw": ".raw",
}


def _default_ext_for_format(fmt_name: str) -> str:
    """Default file extension for an output format name."""
    fmt = (fmt_name or "").lower()
    return _FMT_DEFAULT_EXT.get(fmt, ".xml")


def _default_output_in_teitok_project(input_path: str) -> Optional[str]:
    """If input is under or we're in a TEITOK project, return project/xmlfiles/{safe_basename}.xml."""
    project = _find_teitok_project_root(input_path) or _find_teitok_project_root(
        os.path.join(os.getcwd(), "x")
    )
    if not project:
        return None
    safe_name = _linux_safe_basename(input_path)
    if not safe_name.lower().endswith(".xml"):
        safe_name = os.path.splitext(safe_name)[0] + ".xml"
    return os.path.join(project, "xmlfiles", safe_name)


def _register_builtin_formats() -> None:
    """Register core formats in the global registry."""
    registry.register_input(
        InputFormat(
            name="teitok",
            aliases=("tt",),
            loader=load_teitok,
            description="TEITOK-style TEI/XML with <tok> tokens and rich token attributes.",
            data_type="tei/pivot",
        )
    )
    registry.register_input(
        InputFormat(
            name="tei",
            aliases=("tei-p5",),
            loader=load_tei_p5,
            description="Generic TEI P5 documents (tokens via <w> (and <tok> when present), sentences via <s>).",
            data_type="tei/pivot",
        )
    )
    registry.register_input(
        InputFormat(
            name="rtf",
            aliases=(),
            loader=load_rtf,
            description="Rich Text Format; imported as plain text with simple line-based sentences.",
            data_type="richtext",
        )
    )
    registry.register_input(
        InputFormat(
            name="html",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.html", "load_html"),
            description="HTML; imported as paragraph-like blocks in a 'structure' layer (no tokens).",
            data_type="richtext",
        )
    )
    registry.register_input(
        InputFormat(
            name="docx",
            aliases=("word",),
            loader=_lazy_loader("flexiconv.io.docx", "load_docx"),
            description="Word DOCX; converted to TEITOK-style TEI (styles, tables, images, links, footnotes).",
            data_type="richtext",
        )
    )
    registry.register_input(
        InputFormat(
            name="pdf",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.pdf", "load_pdf"),
            description="PDF; best-effort text and image extraction into TEITOK-style TEI.",
            data_type="richtext",
        )
    )
    registry.register_input(
        InputFormat(
            name="odt",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.odt", "load_odt"),
            description="OpenDocument Text (ODT); converted to TEITOK-style TEI with plain-text paragraphs.",
            data_type="richtext",
        )
    )
    registry.register_input(
        InputFormat(
            name="epub",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.epub", "load_epub"),
            description="EPUB; XHTML chapters converted to TEITOK-style TEI with head/p/list/table/hi.",
            data_type="richtext",
        )
    )
    registry.register_input(
        InputFormat(
            name="txt",
            aliases=("text", "plain"),
            loader=_lazy_loader("flexiconv.io.txt", "load_txt"),
            description="Plain text; line-break meaning set by --linebreaks (sentence, paragraph, double).",
            data_type="plain",
        )
    )
    registry.register_input(
        InputFormat(
            name="md",
            aliases=("markdown",),
            loader=_lazy_loader("flexiconv.io.md", "load_md"),
            description="Markdown; converted to structure (paragraphs, headings, lists) via HTML extraction.",
            data_type="richtext",
        )
    )
    registry.register_input(
        InputFormat(
            name="hocr",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.hocr", "load_hocr"),
            description="hOCR (HTML with ocr_page/ocr_line/ocrx_word); converted to TEITOK-style TEI with bbox.",
            data_type="ocr",
        )
    )
    registry.register_input(
        InputFormat(
            name="pagexml",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.page_xml", "load_page_xml"),
            description="PAGE XML (PcGts); converted to TEITOK-style TEI with facsimile/zones and bbox.",
            data_type="ocr",
        )
    )
    registry.register_input(
        InputFormat(
            name="alto",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.alto", "load_alto"),
            description="ALTO XML; converted to TEITOK-style TEI with facsimile/zones and bbox, similar to PAGE XML.",
            data_type="ocr",
        )
    )
    registry.register_input(
        InputFormat(
            name="srt",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.srt", "load_srt"),
            description="SRT subtitles; converted to TEITOK-style TEI with <u start/end> and an audio recordingStmt.",
            data_type="oral/transcription",
        )
    )
    registry.register_input(
        InputFormat(
            name="eaf",
            aliases=("elan",),
            loader=_lazy_loader("flexiconv.io.eaf", "load_eaf"),
            description="ELAN EAF; converted to TEITOK-style TEI with time-aligned <u> utterances and audio recordingStmt.",
            data_type="oral/transcription",
        )
    )
    registry.register_input(
        InputFormat(
            name="textgrid",
            aliases=("praat", "trs-praat"),
            loader=_lazy_loader("flexiconv.io.textgrid", "load_textgrid"),
            description="Praat TextGrid; converted to TEITOK-style TEI with <u start/end who> and recordingStmt.",
            data_type="oral/transcription",
        )
    )
    registry.register_input(
        InputFormat(
            name="doreco",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.doreco", "load_doreco"),
            description="DoReCo-specific ELAN EAF; converted with DoReCo tier mappings into TEITOK-style TEI.",
            data_type="oral/transcription",
        )
    )
    registry.register_input(
        InputFormat(
            name="exb",
            aliases=("exmaralda",),
            loader=_lazy_loader("flexiconv.io.exb", "load_exb"),
            description="EXMARaLDA basic transcription (.exb) to TEITOK-style TEI with time-aligned <u>.",
            data_type="oral/transcription",
        )
    )
    registry.register_input(
        InputFormat(
            name="chat",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.chat", "load_chat"),
            description="CHAT/CHILDES transcripts (.cha) converted to TEI/TEITOK <u>/<note> structure.",
            data_type="oral/transcription",
        )
    )
    registry.register_input(
        InputFormat(
            name="tmx",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.tmx", "load_tmx"),
            description="TMX translation memories; TEI with <div lang>/<ab tuid> alignment blocks.",
            data_type="translation",
        )
    )
    registry.register_input(
        InputFormat(
            name="conllu",
            aliases=("conll-u",),
            loader=_lazy_loader("flexiconv.io.conllu", "load_conllu"),
            description="CoNLL-U; UD-style sentences/tokens with standardized metadata in comments.",
            data_type="treebank",
        )
    )
    registry.register_input(
        InputFormat(
            name="tbt",
            aliases=("toolbox",),
            loader=_lazy_loader("flexiconv.io.tbt", "load_tbt"),
            description="Toolbox (TBT) interlinear text; converted to TEITOK-style TEI with <s>/<tok>/<morph>.",
            data_type="igt",
        )
    )
    registry.register_input(
        InputFormat(
            name="tcf",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.tcf", "load_tcf"),
            description="TCF (Text Corpus Format, D-Spin/WebLicht); converted to TEITOK-style TEI with <s>/<tok>, lemma, pos, deps, <name>.",
            data_type="corpus",
        )
    )
    registry.register_input(
        InputFormat(
            name="trs",
            aliases=("transcriber",),
            loader=_lazy_loader("flexiconv.io.trs", "load_trs"),
            description="Transcriber TRS; converted to TEITOK-style TEI with <ab>/<ug>/<u start end who>/<tok start end> and recordingStmt.",
            data_type="oral/transcription",
        )
    )
    registry.register_input(
        InputFormat(
            name="brat",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.brat", "load_brat"),
            description="Brat stand-off (.ann + .txt); converted to TEITOK-style TEI with <tok idx> and standOff <span>/<link> elements.",
            data_type="stand-off annotations",
        )
    )
    registry.register_input(
        InputFormat(
            name="folia",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.folia", "load_folia"),
            description="FoLiA (Format for Linguistic Annotation); converted to TEITOK-style TEI with <s>/<tok>, lemma, pos, head, deprel.",
            data_type="corpus",
        )
    )
    registry.register_input(
        InputFormat(
            name="vert",
            aliases=("vrt",),
            loader=_lazy_loader("flexiconv.io.vert", "load_vert"),
            description="Vertical/VRT corpora; converted to TEITOK-style TEI with <div>/<s>/<tok> and heuristic spacing.",
            data_type="corpus",
        )
    )
    registry.register_input(
        InputFormat(
            name="webanno",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.webanno", "load_webanno"),
            description="WebAnno TSV (e.g. INCEpTION export); converted to TEITOK-style TEI with <s>/<tok> and standOff <spanGrp>.",
            data_type="stand-off annotations",
        )
    )

    registry.register_output(
        OutputFormat(
            name="teitok",
            aliases=("tt",),
            saver=save_teitok,
            description="Write a minimal TEITOK-style TEI with <tok> tokens and <s> sentences.",
            data_type="tei/pivot",
            supported_layers=("tokens", "sentences", "structure", "rendition"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="hocr",
            aliases=(),
            saver=_lazy_loader("flexiconv.io.hocr", "save_hocr"),
            description="hOCR (from TEI with bbox or future FPM); supports round-trip hOCR→TEI→hOCR.",
            data_type="ocr",
            supported_layers=("tokens", "structure"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="tei",
            aliases=("tei-p5",),
            saver=save_tei_p5,
            description="Write simple TEI P5 with <w> tokens and <s> sentences (or plain <p> from structure).",
            data_type="tei/pivot",
            supported_layers=("tokens", "sentences", "structure"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="raw",
            aliases=(),
            saver=_lazy_loader("flexiconv.io.raw", "save_raw"),
            description="Dump the pivot Document (meta, layers, nodes) as a plain-text report.",
            data_type="other",
            supported_layers=None,
        )
    )
    registry.register_output(
        OutputFormat(
            name="rtf",
            aliases=(),
            saver=save_rtf,
            description="Write a text-only RTF; each sentence becomes one paragraph.",
            data_type="richtext",
            supported_layers=("tokens", "sentences"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="html",
            aliases=(),
            saver=_lazy_saver("flexiconv.io.html", "save_html"),
            description="Write simple HTML with one <p> per paragraph (and spans for inline styles when available).",
            data_type="richtext",
            supported_layers=("tokens", "sentences", "structure", "rendition"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="txt",
            aliases=("text", "plain"),
            saver=_lazy_saver("flexiconv.io.txt", "save_txt"),
            description="Plain text; one line per sentence/paragraph or blocks separated by blank lines (--linebreaks).",
            data_type="plain",
            supported_layers=("tokens", "sentences", "structure"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="srt",
            aliases=(),
            saver=_lazy_saver("flexiconv.io.srt", "save_srt"),
            description="SRT subtitles from TEI <u start/end> or an 'utterances' layer with TIME anchors.",
            data_type="oral/transcription",
            supported_layers=("utterances",),
        )
    )
    registry.register_output(
        OutputFormat(
            name="conllu",
            aliases=("conll-u",),
            saver=_lazy_saver("flexiconv.io.conllu", "save_conllu"),
            description="CoNLL-U with standardized file/sentence metadata and SpaceAfter=No from space_after.",
            data_type="treebank",
            supported_layers=("tokens", "sentences"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="doreco",
            aliases=(),
            saver=_lazy_saver("flexiconv.io.doreco", "save_doreco"),
            description="DoReCo-style ELAN EAF from TEITOK DoReCo TEI (<u>/<tok>/<m>).",
            data_type="oral/transcription",
            supported_layers=(),
        )
    )
    registry.register_output(
        OutputFormat(
            name="exb",
            aliases=("exmaralda",),
            saver=_lazy_saver("flexiconv.io.exb", "save_exb"),
            description="EXMARaLDA basic transcription from TEITOK TEI with time-aligned <u>.",
            data_type="oral/transcription",
            supported_layers=("utterances",),
        )
    )


def _detect_input_format(path: str) -> Optional[str]:
    return path_to_input_format(path)


def _detect_output_format(path: str) -> Optional[str]:
    return path_to_output_format(path)


def _format_data_type(fmt_name: str) -> str:
    """Return a coarse data-type label for a given format name."""
    name = (fmt_name or "").lower()
    if name in {"teitok", "tei"}:
        return "tei/pivot"
    if name in {"rtf", "docx", "html", "md", "pdf", "odt", "epub"}:
        return "richtext"
    if name in {"txt"}:
        return "plain"
    if name in {"hocr", "pagexml", "alto"}:
        return "ocr"
    if name in {"eaf", "doreco", "textgrid", "exb", "trs", "chat", "srt"}:
        return "oral/transcription"
    if name in {"tmx"}:
        return "translation"
    if name in {"conllu"}:
        return "treebank"
    if name in {"tbt"}:
        return "igt"
    if name in {"tcf", "folia", "vert"}:
        return "corpus"
    if name in {"brat", "webanno"}:
        return "stand-off annotations"
    return "other"


# Brief explanations for each document-type group (used by "info formats").
FORMAT_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "tei/pivot": "Pivot document model (layers, anchors, spans) supporting crossing annotations; exported as TEI-style XML (hierarchical or stand-off).",
    "richtext": "Document formats with rich layout and styling (headings, lists, tables, inline styles).",
    "plain": "Unstructured plain text without markup.",
    "ocr": "Text-recognition output for Optical Character Recognition and Handwritten Text Recognition.",
    "oral/transcription": "Time-aligned or segment-based transcripts of spoken or multimodal content (including subtitles).",
    "subtitles": "Subtitle and caption streams.",
    "translation": "Parallel or aligned text segments for translation memories.",
    "treebank": "Tokenized text with morpho-syntactic and dependency annotation.",
    "igt": "Interlinear glossed examples with aligned tiers (object language, gloss, translation).",
    "corpus": "Corpus containers with tokens, structural hierarchy, and annotation layers.",
    "stand-off annotations": "Annotation formats that reference a separate primary text by offsets or IDs.",
    "other": "Miscellaneous formats that do not fit other categories.",
}


def _cmd_info(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="flexiconv info",
        description="Show information about available formats.",
    )
    parser.add_argument(
        "what",
        nargs="?",
        default="formats",
        help="'formats' or 'format'",
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="Format name for 'format' (e.g. teitok, tei, rtf).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON (for TEITOK / scripts).",
    )
    args = parser.parse_args(argv)

    def _format_to_json(fmt: InputFormat | OutputFormat) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "name": fmt.name,
            "aliases": list(fmt.aliases),
            "data_type": getattr(fmt, "data_type", "") or _format_data_type(fmt.name),
            "description": fmt.description or "",
        }
        if isinstance(fmt, OutputFormat) and getattr(fmt, "supported_layers", ()):
            out["supported_layers"] = list(fmt.supported_layers)
        return out

    if args.what == "formats":
        input_list: List[Dict[str, Any]] = []
        seen_in = set()
        for key, fmt in registry._inputs.items():  # type: ignore[attr-defined]
            if fmt.name in seen_in:
                continue
            seen_in.add(fmt.name)
            input_list.append(_format_to_json(fmt))
        output_list: List[Dict[str, Any]] = []
        seen_out = set()
        for key, fmt in registry._outputs.items():  # type: ignore[attr-defined]
            if fmt.name in seen_out:
                continue
            seen_out.add(fmt.name)
            output_list.append(_format_to_json(fmt))
        if args.json:
            print(json.dumps({"input": input_list, "output": output_list}, indent=2))
            return 0

        def _group_by_type(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for fmt in items:
                dtype = fmt.get("data_type") or "other"
                grouped.setdefault(dtype, []).append(fmt)
            return grouped

        input_grouped = _group_by_type(input_list)
        output_grouped = _group_by_type(output_list)

        print("Input formats by data type:")
        for dtype in sorted(input_grouped.keys()):
            desc_line = FORMAT_TYPE_DESCRIPTIONS.get(dtype, "")
            print(f"  [{dtype}] {desc_line}")
            for fmt in sorted(input_grouped[dtype], key=lambda f: f["name"]):
                aliases = ", ".join(fmt["aliases"]) if fmt["aliases"] else "-"
                desc = f" – {fmt['description']}" if fmt.get("description") else ""
                print(f"    {fmt['name']} (aliases: {aliases}){desc}")

        print("\nOutput formats by data type:")
        for dtype in sorted(output_grouped.keys()):
            desc_line = FORMAT_TYPE_DESCRIPTIONS.get(dtype, "")
            print(f"  [{dtype}] {desc_line}")
            for fmt in sorted(output_grouped[dtype], key=lambda f: f["name"]):
                aliases = ", ".join(fmt["aliases"]) if fmt["aliases"] else "-"
                desc = f" – {fmt['description']}" if fmt.get("description") else ""
                layers = fmt.get("supported_layers")
                layers_str = f" [layers: {', '.join(layers)}]" if layers else ""
                print(f"    {fmt['name']} (aliases: {aliases}){layers_str}{desc}")
        return 0

    if args.what == "format":
        if not args.name:
            parser.error("Please specify a format name, e.g. 'flexiconv info format teitok'.")
        name = args.name
        fmt_in = registry.get_input(name)
        fmt_out = registry.get_output(name)
        if not fmt_in and not fmt_out:
            parser.error(f"Unknown format: {name}")
        if args.json:
            payload: Dict[str, Any] = {
                "input": _format_to_json(fmt_in) if fmt_in else None,
                "output": _format_to_json(fmt_out) if fmt_out else None,
            }
            print(json.dumps(payload, indent=2))
            return 0
        if fmt_in:
            aliases = ", ".join(fmt_in.aliases) if fmt_in.aliases else "-"
            print(f"Input format '{fmt_in.name}'")
            print(f"  Aliases: {aliases}")
            print(f"  Data type: {_format_data_type(fmt_in.name)}")
            if fmt_in.description:
                print(f"  Description: {fmt_in.description}")
        if fmt_out:
            aliases = ", ".join(fmt_out.aliases) if fmt_out.aliases else "-"
            print(f"\nOutput format '{fmt_out.name}'")
            print(f"  Aliases: {aliases}")
            print(f"  Data type: {_format_data_type(fmt_out.name)}")
            if fmt_out.description:
                print(f"  Description: {fmt_out.description}")
        return 0

    parser.error(f"Unknown info topic: {args.what}")
    return 1


def _cmd_install(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="flexiconv install",
        description="Show how to install optional plugins or third-party tools.",
    )
    parser.add_argument(
        "name",
        help="Name of the plugin or extra (e.g. 'rtf', 'tei-corpo', 'annatto').",
    )
    args = parser.parse_args(argv)

    name = args.name.lower()
    if name == "wrapper":
        print("The 'flexiconv' wrapper (command) is installed automatically when")
        print("you install the package with pip. On your dev machine, run:")
        print("  python -m pip install -e .")
        print()
        print("After that, you can call:")
        print("  flexiconv input.ext output.ext")
        print()
        print("Without installation you can always use:")
        print("  python -m flexiconv input.ext output.ext")
    elif name == "rtf":
        print("Installing RTF support via pip in this Python environment:")
        cmd = [sys.executable, "-m", "pip", "install", "flexiconv[rtf]"]
        print("  " + " ".join(cmd))
        try:
            result = subprocess.run(cmd, check=False)
        except Exception as exc:  # pragma: no cover
            print(f"Installation failed: {exc}")
            return 1
        if result.returncode != 0:
            print("Installation failed; please check the pip output above.")
            return result.returncode
        print("RTF support installed successfully.")
    elif name in {"tei-corpo", "teicorpo"}:
        print("TEI-CORPO integration will require the teicorpo Java tools.")
        print("Please install TEI-CORPO separately and configure its path in flexiconv in the future.")
    elif name in {"annatto"}:
        print("Annatto integration will require the annatto binary.")
        print("Please install annatto from https://github.com/korpling/annatto and ensure it is on your PATH.")
    else:
        print(f"No dedicated installer for '{args.name}'.")
        print("For Python-based plugins, install the package with pip, then re-run flexiconv.")
    return 0


def _cmd_update(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="flexiconv update",
        description="Show how to update flexiconv and its optional dependencies.",
    )
    parser.parse_args(argv)

    print("To update flexiconv from PyPI, run:")
    print("  pip install --upgrade flexiconv")
    print("\nTo update optional extras (e.g. RTF support):")
    print("  pip install --upgrade 'flexiconv[rtf]'")
    return 0


def _make_convert_parser(prog: str = "flexiconv convert") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="Convert documents and corpora via a TEI/TEITOK-compatible pivot format.")
    p.add_argument("input", help="Input file path.")
    p.add_argument("output", nargs="?", default=None, help="Output file path (optional in a TEITOK project).")
    p.add_argument("-f", "--from", dest="from_format", help="Input format (e.g. teitok, tei, rtf, txt).")
    p.add_argument("-t", "--to", dest="to_format", help="Output format.")
    p.add_argument(
        "-R",
        "--recursive",
        action="store_true",
        help="When INPUT is a directory, convert all files in it (recursively).",
    )
    p.add_argument("--list-formats", action="store_true", help="List formats and exit.")
    p.add_argument("-v", "--verbose", action="store_true", help="Print format and output path.")
    p.add_argument("--teitok-project", metavar="DIR", help="Teitok project root (writes to DIR/xmlfiles/).")
    p.add_argument("--copy-original", action="store_true", help="Copy input to project Originals/ when using --teitok-project.")
    p.add_argument("--force", action="store_true", help="Overwrite existing output.")
    p.add_argument(
        "--linebreaks",
        choices=("sentence", "paragraph", "double"),
        default="paragraph",
        help="Txt: newline = sentence | paragraph | only double newline = paragraph.",
    )
    p.add_argument(
        "--hocr-no-split-punct",
        action="store_true",
        help="hOCR: keep punctuation attached to words (disable default punctuation splitting).",
    )
    p.add_argument(
        "--hocr-hyphen-truncation",
        action="store_true",
        help="hOCR: merge word- at line end with next line's first word into one <tok><gtok><lb/><gtok></tok>.",
    )
    p.add_argument(
        "--spacing-mode",
        "--spacing_mode",
        choices=("guess", "none"),
        default="guess",
        help="Vert: spacing heuristic for reconstructed spacing (guess|none).",
    )
    p.add_argument(
        "--vert-no-doc-split",
        action="store_true",
        help="Vert: do not start a new <div> at <doc>/<text> boundaries.",
    )
    p.add_argument(
        "--eaf-style",
        choices=("generic", "doreco"),
        default="generic",
        help="EAF: interpret tiers using a style preset (e.g. 'doreco' for DoReCo conventions).",
    )
    p.add_argument(
        "--flexipipe",
        nargs="?",
        const="",
        metavar="ARGS",
        help=(
            "After successful TEITOK conversion, run 'flexipipe' on the result. "
            "Optional ARGS are inserted before the XML path; use {project} to "
            "refer to the TEITOK project root (if detected)."
        ),
    )
    p.add_argument(
        "--option",
        help="Format-specific option (e.g. TMX: join|annotate).",
    )
    p.add_argument(
        "--prettyprint",
        action="store_true",
        help="Ask the output format (when supported) to pretty-print for readability without changing spacing.",
    )
    return p


def _cmd_convert(argv: list[str]) -> int:
    return _run_convert(_make_convert_parser("flexiconv convert"), argv)


def _run_convert(parser: argparse.ArgumentParser, argv: list[str]) -> int:
    args = parser.parse_args(argv)

    def _fail(message: str, code: int = 2) -> int:
        """Print a flexiconv-style error without argparse usage noise."""
        sys.stderr.write(f"[flexiconv] {message}\n")
        return code

    if args.list_formats:
        return _cmd_info(["formats"])

    # If the user explicitly specified an output format with -t/--to, validate it
    # before we derive any output paths or attempt to write files. This ensures
    # that unknown or write-only formats fail fast instead of silently falling
    # back to a generic extension like .xml.
    if args.to_format is not None:
        requested_out = args.to_format
        out_fmt = registry.get_output(requested_out)
        if out_fmt is None:
            # Known only as input?
            if registry.get_input(requested_out) is not None:
                return _fail(
                    f"Output format '{requested_out}' is not available: no writer is registered for this format."
                )
            return _fail(f"Unknown output format: {requested_out}")

    input_path = args.input
    output_path = args.output

    # Directory + --recursive: batch-convert all files under INPUT.
    if os.path.isdir(input_path) and getattr(args, "recursive", False):
        # Determine base output directory.
        if output_path is None:
            # Inside a TEITOK project: use its xmlfiles folder; otherwise mirror
            # next to the input directory.
            project = _find_teitok_project_root(input_path) or _find_teitok_project_root(
                os.path.join(os.getcwd(), "x")
            )
            if project:
                out_dir = os.path.join(project, "xmlfiles")
            else:
                out_dir = input_path
        else:
            if os.path.exists(output_path) and not os.path.isdir(output_path):
                return _fail("When INPUT is a directory, OUTPUT (if given) must be a directory.")
            if not os.path.exists(output_path):
                os.makedirs(output_path, exist_ok=True)
            out_dir = output_path

        # Decide default output format for directory targets.
        out_fmt_name = args.to_format or "teitok"
        out_fmt = registry.get_output(out_fmt_name)
        if out_fmt is None:
            # Known only as input?
            if registry.get_input(out_fmt_name) is not None:
                return _fail(
                    f"Output format '{out_fmt_name}' is not available: no writer is registered for this format."
                )
            return _fail(f"Unknown output format: {out_fmt_name}")

        # Build a common argv prefix for per-file conversions (propagate flags).
        common: list[str] = []
        if args.from_format:
            common += ["-f", args.from_format]
        if args.to_format:
            common += ["-t", args.to_format]
        if args.verbose:
            common.append("-v")
        if args.teitok_project:
            common += ["--teitok-project", args.teitok_project]
        if args.copy_original:
            common.append("--copy-original")
        if args.force:
            common.append("--force")
        if getattr(args, "linebreaks", None):
            common += ["--linebreaks", args.linebreaks]
        if getattr(args, "hocr_no_split_punct", False):
            common.append("--hocr-no-split-punct")
        if getattr(args, "hocr_hyphen_truncation", False):
            common.append("--hocr-hyphen-truncation")
        if getattr(args, "eaf_style", None):
            common += ["--eaf-style", args.eaf_style]
        if getattr(args, "option", None):
            common += ["--option", args.option]
        if getattr(args, "prettyprint", False):
            common.append("--prettyprint")
        if getattr(args, "spacing_mode", None):
            common += ["--spacing-mode", args.spacing_mode]
        if getattr(args, "vert_no_doc_split", False):
            common.append("--vert-no-doc-split")
        if getattr(args, "flexipipe", None):
            common += ["--flexipipe", args.flexipipe]

        total = 0
        errors = 0
        ext = _default_ext_for_format(out_fmt_name)
        for root, _dirs, files in os.walk(input_path):
            for fname in files:
                in_file = os.path.join(root, fname)
                if not os.path.isfile(in_file):
                    continue
                rel = os.path.relpath(in_file, input_path)
                rel_dir = os.path.dirname(rel)
                out_subdir = out_dir if rel_dir in ("", ".") else os.path.join(out_dir, rel_dir)
                os.makedirs(out_subdir, exist_ok=True)
                safe_base = _linux_safe_basename(in_file)
                stem, _ = os.path.splitext(safe_base)
                out_file = os.path.join(out_subdir, stem + ext)

                argv_file = common + [in_file, out_file]
                rc = _run_convert(_make_convert_parser("flexiconv"), argv_file)
                if rc != 0:
                    errors += 1
                else:
                    total += 1

        if args.verbose:
            sys.stderr.write(
                f"[flexiconv] Batch converted {total} file(s) under {input_path}"
                + (f"; {errors} failed\n" if errors else "\n")
            )
        return 0 if errors == 0 else 1

    # When no output is given, mimic tools like pandoc/ImageMagick:
    # - Inside a TEITOK project: default to teitok + xmlfiles/{safe_basename}.xml
    # - Otherwise: write next to the input file with a sensible extension.
    if output_path is None:
        default_out = _default_output_in_teitok_project(input_path)
        if default_out is not None:
            output_path = default_out
            if args.to_format is None:
                args.to_format = "teitok"
        else:
            safe_base = _linux_safe_basename(input_path)
            stem, _ = os.path.splitext(safe_base)
            # Use the default extension for the requested output format when known,
            # otherwise fall back to .xml.
            ext = _default_ext_for_format(args.to_format or "")
            output_path = os.path.join(os.path.dirname(input_path), stem + ext)

    # Detect input format and remember detected MIME type for TEITOK headers.
    detected_mime = detect_mime(input_path)
    in_fmt_name = args.from_format or _detect_input_format(input_path)

    # If TMX + --option split: special-case multi-output behaviour (one TEI per language).
    opt_val = getattr(args, "option", None)
    if in_fmt_name == "tmx" and opt_val is not None and opt_val.lower() == "split":
        if output_path is None or not os.path.isdir(output_path):
            return _fail(
                "TMX split mode requires OUTPUT to be an existing directory (one TEI per language will be written there)."
            )
        from .io.tmx import split_tmx_to_teitok_files

        written = split_tmx_to_teitok_files(input_path, output_path)
        if args.verbose:
            sys.stderr.write(
                f"[flexiconv] TMX split wrote {len(written)} files into {output_path}\n"
            )
        return 0

    # If CoNLL-U + --option split: one TEI per # newtext block.
    if in_fmt_name == "conllu" and opt_val is not None and opt_val.lower() == "split":
        if output_path is None or not os.path.isdir(output_path):
            return _fail(
                "CoNLL-U split mode requires OUTPUT to be an existing directory (one TEI per # newtext will be written there)."
            )
        # Only teitok output is meaningful for split at the moment.
        if args.to_format not in (None, "teitok"):
            return _fail(
                "CoNLL-U split mode currently only supports TEITOK XML output; omit -t or use --to teitok."
            )
        from .io.conllu import split_conllu_to_teitok_files

        written = split_conllu_to_teitok_files(input_path, output_path)
        if args.verbose:
            sys.stderr.write(
                f"[flexiconv] CoNLL-U split wrote {len(written)} files into {output_path}\n"
            )
        return 0

    # If VERT + --option split: one TEI per <doc>/<text> block.
    if in_fmt_name == "vert" and opt_val is not None:
        # Parse VERT-specific options to detect split and optional registry/cols.
        want_split = False
        registry_opt: Optional[str] = None
        columns_opt: Optional[list[str]] = None
        opt_raw = opt_val
        for part in opt_raw.split(";"):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                if part.lower() == "split":
                    want_split = True
                continue
            key, val = part.split("=", 1)
            key = key.strip().lower()
            val = val.strip()
            if not val:
                continue
            if key == "split" and val.lower() in {"doc", "docs", "text", "texts", "1"}:
                want_split = True
            elif key == "registry":
                registry_opt = val
            elif key in {"cols", "columns"}:
                columns_opt = [c.strip() for c in val.split(",") if c.strip()]

        if want_split:
            if output_path is None or not os.path.isdir(output_path):
                return _fail(
                    "Vert split mode requires OUTPUT to be an existing directory (one TEI per <doc>/<text> will be written there)."
                )
            # Only teitok output is meaningful for split at the moment.
            if args.to_format not in (None, "teitok"):
                return _fail(
                    "Vert split mode currently only supports TEITOK XML output; omit -t or use --to teitok."
                )
            from .io.vert import split_vert_to_teitok_files

            spacing_mode = getattr(args, "spacing_mode", "guess")
            written = split_vert_to_teitok_files(
                input_path,
                output_path,
                registry=registry_opt,
                columns=columns_opt,
                spacing_mode=spacing_mode,
            )
            if args.verbose:
                sys.stderr.write(
                    f"[flexiconv] Vert split wrote {len(written)} files into {output_path}\n"
                )
            return 0

    # If output path is an existing directory and has no explicit extension, assume the user
    # meant "write into this folder using a sanitized source name and the right extension".
    if os.path.isdir(output_path):
        out_fmt_for_dir = args.to_format
        if out_fmt_for_dir is None:
            # Default: for directory targets without -t, assume TEITOK-style TEI output.
            out_fmt_for_dir = "teitok"
            args.to_format = out_fmt_for_dir
        safe_base = _linux_safe_basename(input_path)
        stem, _ = os.path.splitext(safe_base)
        ext = _default_ext_for_format(out_fmt_for_dir)
        output_path = os.path.join(output_path, stem + ext)

    out_fmt_name = args.to_format or _detect_output_format(output_path)

    if not in_fmt_name:
        return _fail("Could not detect input format; please use -f/--from.")
    if not out_fmt_name:
        return _fail("Could not detect output format; please use -t/--to.")

    # Heuristic: DOCX/hOCR → .xml should default to TEITOK-style TEI,
    # since load_docx/load_hocr produce a ready-made TEITOK TEI tree.
    if args.to_format is None and out_fmt_name == "tei" and in_fmt_name in ("docx", "hocr"):
        out_fmt_name = "teitok"

    if os.path.isfile(output_path) and not getattr(args, "force", False):
        sys.stderr.write(
            f"[flexiconv] Refusing to overwrite existing file: {output_path}\n"
            "[flexiconv] Use --force to overwrite.\n"
        )
        return 1

    if args.verbose:
        sys.stderr.write(
            f"[flexiconv] Input format: {in_fmt_name}\n"
            f"[flexiconv] Output format: {out_fmt_name}\n"
            f"[flexiconv] Output file: {output_path}\n"
        )

    in_fmt = registry.get_input(in_fmt_name)
    if in_fmt is None:
        # If we saw a MIME type, tell the user if the MIME is known but unsupported
        mime = detect_mime(input_path)
        if mime and not mime_to_format(mime):
            return _fail(describe_unsupported_mime(mime))
        return _fail(f"Unknown input format: {in_fmt_name}")
    out_fmt = registry.get_output(out_fmt_name)
    if out_fmt is None:
        # Distinguish between formats we know only as inputs vs completely unknown names.
        if registry.get_input(out_fmt_name) is not None:
            return _fail(
                f"Output format '{out_fmt_name}' is not available: no writer is registered for this format."
            )
        return _fail(f"Unknown output format: {out_fmt_name}")

    # Load → convert (pivot) → save (via API for progress/GUI integration)
    convert_options = {
        "force": getattr(args, "force", False),
        "linebreaks": getattr(args, "linebreaks", "paragraph"),
        "hocr_no_split_punct": getattr(args, "hocr_no_split_punct", False),
        "hocr_hyphen_truncation": getattr(args, "hocr_hyphen_truncation", False),
        "eaf_style": getattr(args, "eaf_style", None),
        "option": getattr(args, "option", None),
        "prettyprint": getattr(args, "prettyprint", False),
        "spacing_mode": getattr(args, "spacing_mode", None),
        "vert_no_doc_split": getattr(args, "vert_no_doc_split", False),
        "teitok_project": getattr(args, "teitok_project", None),
        "copy_original": getattr(args, "copy_original", False),
    }
    def _progress_cb(current: int, total: int, message: str) -> None:
        sys.stderr.write(f"  {message}: {current}/{total}\r")
        sys.stderr.flush()

    try:
        from .api import run_convert as api_run_convert, CancelError
        result = api_run_convert(
            input_path,
            output_path,
            from_format=in_fmt_name,
            to_format=out_fmt_name,
            options=convert_options,
            progress_callback=_progress_cb if args.verbose else None,
            cancel_check=None,
        )
    except CancelError:
        sys.stderr.write("[flexiconv] Conversion cancelled.\n")
        return 130
    if not result.success:
        return _fail(result.error_message or "Conversion failed")

    # Verbose reporting is done inside the API when options contain verbose; CLI skips here.

    # Optional post-processing: run flexipipe on the resulting TEITOK file.
    flexipipe_args_tmpl = getattr(args, "flexipipe", None)
    if flexipipe_args_tmpl is not None and out_fmt_name == "teitok":
        project_root = getattr(args, "teitok_project", None) or _find_teitok_project_root(
            output_path
        )
        # Substitute only {project}; the XML path is always appended as final arg.
        try:
            extra_args_str = (flexipipe_args_tmpl or "").format(
                project=project_root or "",
            )
        except Exception as exc:
            sys.stderr.write(f"[flexiconv] Invalid flexipipe args: {exc}\n")
            return 1
        try:
            extra_args = shlex.split(extra_args_str) if extra_args_str else []
        except ValueError as exc:
            sys.stderr.write(f"[flexiconv] Invalid flexipipe args: {exc}\n")
            return 1
        cmd = ["flexipipe"] + extra_args + [output_path]
        if args.verbose:
            sys.stderr.write(f"[flexiconv] Running flexipipe: {' '.join(cmd)}\n")
        try:
            result = subprocess.run(cmd, check=False)
        except Exception as exc:
            sys.stderr.write(f"[flexiconv] flexipipe command failed: {exc}\n")
            return 1
        if result.returncode != 0:
            sys.stderr.write(
                f"[flexiconv] flexipipe returned non-zero exit code {result.returncode}\n"
            )
            return result.returncode

    return 0


def _content_fingerprint_hash(path: str) -> Optional[str]:
    """Hash of convert-to-text content (any supported format). Load → document_to_plain_text → normalize → SHA-256.
    Returns None if format unknown or load fails."""
    fmt_name = path_to_input_format(path)
    if not fmt_name:
        return None
    in_fmt = registry.get_input(fmt_name)
    if not in_fmt or not getattr(in_fmt, "loader", None):
        return None
    loader_kwargs: Dict[str, Any] = {}
    if fmt_name == "txt":
        loader_kwargs["linebreaks"] = "paragraph"
    if fmt_name == "hocr":
        loader_kwargs["split_punct"] = True
    try:
        try:
            doc = in_fmt.loader(path, **loader_kwargs)
        except TypeError:
            doc = in_fmt.loader(path)
    except Exception:
        return None
    text = document_to_plain_text(doc)
    normalized = normalize_text_for_fingerprint(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalized_text_for_path(path: str, by_content: bool) -> Optional[str]:
    """Return normalized text for path (for near-dup shingling). Same source as exact hash."""
    if by_content:
        fmt_name = path_to_input_format(path)
        if not fmt_name:
            return None
        in_fmt = registry.get_input(fmt_name)
        if not in_fmt or not getattr(in_fmt, "loader", None):
            return None
        try:
            doc = in_fmt.loader(path)
        except Exception:
            return None
        text = document_to_plain_text(doc)
        return normalize_text_for_fingerprint(text) or None
    try:
        return teitok_text_fingerprint(path)
    except Exception:
        return None


def _common_base(paths: List[str]) -> Optional[str]:
    """Return a common base directory for paths, or None. Used to show relative paths in duplicate output."""
    if not paths:
        return None
    try:
        abs_paths = [os.path.abspath(p) for p in paths]
        if len(abs_paths) == 1:
            return os.path.dirname(abs_paths[0])
        return os.path.commonpath(abs_paths)
    except (ValueError, TypeError):
        return None


def _path_relative_to_base(path: str, base: Optional[str]) -> str:
    """Path relative to base, or basename if no base. Uses forward slashes for readability."""
    if base:
        try:
            rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
            return rel.replace(os.sep, "/")
        except ValueError:
            pass
    return os.path.basename(path)


def _chunks(lst: List[str], n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _progress_iter(iterable: List[str], total: int, desc: str = "files", enabled: bool = True):
    """Wrap an iterable and write progress to stderr (e.g. '  files: 123/456\\r'). Does not touch stdout."""
    if not enabled or total == 0:
        yield from iterable
        return
    n = 0
    for item in iterable:
        n += 1
        sys.stderr.write(f"  {desc}: {n}/{total}\r")
        sys.stderr.flush()
        yield item
    sys.stderr.write("\n")
    sys.stderr.flush()


def _cmd_duplicates(argv: list[str]) -> int:
    """List TEITOK XML files that are duplicates (same space-normalized <text> content).
    Detection is exact only: identical normalized text → same hash. Near-identical texts are not grouped."""
    p = argparse.ArgumentParser(
        prog="flexiconv duplicates",
        description="Find TEITOK XML files with identical text content (space-normalized <text>). Exact match only; near-identical texts are not detected.",
    )
    p.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Paths to TEITOK XML files or a directory (scans for *.xml). Omit when using --from-list, --from-index, or when run inside a TEITOK project (defaults to xmlfiles/).",
    )
    p.add_argument(
        "--from-list",
        metavar="FILE",
        help="Read paths from FILE (one path per line). Use to avoid long command lines (e.g. from PHP).",
    )
    p.add_argument(
        "--from-index",
        metavar="PATH",
        help="List duplicate groups from this index. In a TEITOK project, defaults to tmp/deduplication.sqlite when omitted (and no paths/--from-list/--index).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output duplicate groups as JSON array of filename arrays (applies to both index and path scan).",
    )
    p.add_argument(
        "--index",
        action="store_true",
        help="Output one line per file: SHA256(fingerprint)\\tbasename (for easycorp). Only printed when --verbose.",
    )
    p.add_argument(
        "--output",
        metavar="PATH",
        help="Write index to PATH. If PATH ends with .sqlite, use SQLite (WaC-style). Inside a TEITOK project with --index, defaults to tmp/deduplication.sqlite when omitted.",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="With --index: print each hash\\tbasename line to stdout. Omit for large corpora to avoid slowdown.",
    )
    p.add_argument(
        "--by-content",
        action="store_true",
        help="Use convert-to-text fingerprint for any supported format (RTF, DOCX, XML, etc.): load file, extract plain text (same as save_txt), normalize spaces, hash. Enables comparing mixed folders (e.g. RTF and DOCX versions of the same text). Scans all supported extensions.",
    )
    p.add_argument(
        "--incremental",
        action="store_true",
        help="With --index and SQLite: only re-hash files whose mtime/size changed; remove index entries for deleted files. Much faster for large corpora after the first run.",
    )
    p.add_argument(
        "--near-identical",
        action="store_true",
        help="With --index: also build MinHash+LSH index for near-duplicate detection. With --from-index: list near-duplicate groups (similarity >= --threshold). Requires SQLite.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        metavar="F",
        help="Similarity threshold for near-identical (0.0–1.0). Default 0.8. Used with --near-identical.",
    )
    p.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="No progress bar on stderr. Use when parsing stdout (e.g. --json in scripts) and you want no progress output.",
    )
    args = p.parse_args(argv)
    paths: list[str] = []
    teitok_project: Optional[str] = None
    from_index = (getattr(args, "from_index", None) or "").strip()
    # Default index when only comparing (no --index, no paths/list): use TEITOK tmp/deduplication.sqlite
    if not from_index and not args.index and not args.paths and not args.from_list:
        cwd = os.getcwd()
        proj = _find_teitok_project_root(cwd) or _find_teitok_project_root(
            os.path.join(cwd, "xmlfiles")
        )
        if proj:
            from_index = os.path.join(proj, "tmp", "deduplication.sqlite")

    # List duplicates from an existing index (no path scan)
    if from_index:
        idx_path = os.path.abspath(os.path.normpath(from_index))
        if not os.path.isfile(idx_path):
            print("Index file not found: " + idx_path, file=sys.stderr)
            print("Run with --index to build the index (e.g. flexiconv duplicates --index).", file=sys.stderr)
            return 1
        groups: List[List[str]] = []
        if idx_path.lower().endswith(".sqlite"):
            try:
                import sqlite3
                conn = sqlite3.connect(idx_path)
                near_identical = getattr(args, "near_identical", False)
                threshold = max(0.0, min(1.0, getattr(args, "threshold", 0.8)))
                if near_identical:
                    try:
                        rows = conn.execute("SELECT path, sig FROM near_dup_sigs").fetchall()
                    except sqlite3.OperationalError:
                        rows = []
                    if rows:
                        path_to_sig: Dict[str, List[int]] = {}
                        for path, sig_blob in rows:
                            if path and sig_blob:
                                path_to_sig[path] = signature_from_blob(sig_blob)
                        buckets: Dict[Tuple[int, str], set] = {}
                        for band_id, bucket, path in conn.execute("SELECT band_id, bucket, path FROM near_dup_lsh").fetchall():
                            key = (band_id, bucket)
                            buckets.setdefault(key, set()).add(path)
                        candidate_pairs: set = set()
                        for path, sig in path_to_sig.items():
                            for band_id, bucket in lsh_bands(sig):
                                key = (band_id, bucket)
                                for other in buckets.get(key, set()):
                                    if other != path:
                                        candidate_pairs.add((min(path, other), max(path, other)))
                        uf: Dict[str, str] = {}

                        def find(x: str) -> str:
                            if x not in uf:
                                uf[x] = x
                            if uf[x] != x:
                                uf[x] = find(uf[x])
                            return uf[x]

                        def union(x: str, y: str) -> None:
                            uf[find(x)] = find(y)

                        for p, q in candidate_pairs:
                            if signature_similarity(path_to_sig[p], path_to_sig[q]) >= threshold:
                                union(p, q)
                        roots: Dict[str, List[str]] = {}
                        for path in path_to_sig:
                            r = find(path)
                            roots.setdefault(r, []).append(path)
                        groups = [sorted(comp) for comp in roots.values() if len(comp) >= 2]
                        conn.close()
                        if getattr(args, "json", False):
                            print(json.dumps(groups, indent=2))
                            return 0 if not groups else 1
                        for g in groups:
                            print("Near-identical set (%d files, >=%.2f):" % (len(g), threshold))
                            for fn in g:
                                print("  ", fn)
                            print()
                        return 0 if not groups else 1
                cur = conn.execute("SELECT hash, filename FROM dedup_index")
                hash_to_files = {}
                for row in cur.fetchall():
                    h, fn = (row[0] or "").strip(), (row[1] or "").strip()
                    if h and fn:
                        hash_to_files.setdefault(h, []).append(fn)
                conn.close()
                groups = [sorted(files) for files in hash_to_files.values() if len(files) > 1]
            except Exception as e:
                print("Error reading SQLite index: " + str(e), file=sys.stderr)
                return 1
        else:
            try:
                with open(idx_path, encoding="utf-8") as f:
                    hash_to_files = {}
                    for line in f:
                        parts = line.strip().split("\t", 1)
                        if len(parts) == 2:
                            h, fn = parts[0].strip(), parts[1].strip()
                            if h and fn:
                                hash_to_files.setdefault(h, []).append(fn)
                    groups = [sorted(files) for files in hash_to_files.values() if len(files) > 1]
            except OSError as e:
                print("Error reading index file: " + str(e), file=sys.stderr)
                return 1
        if getattr(args, "json", False):
            print(json.dumps(groups, indent=2))
            return 0 if not groups else 1
        for g in groups:
            print("Duplicate set (%d files):" % len(g))
            for fn in g:
                print("  ", fn)
            print()
        return 0 if not groups else 1

    if args.from_list:
        try:
            with open(args.from_list, encoding="utf-8") as f:
                for line in f:
                    pth = line.strip()
                    if pth:
                        paths.append(os.path.abspath(os.path.normpath(pth)))
        except OSError:
            pass
    else:
        if not args.paths:
            cwd = os.getcwd()
            teitok_project = _find_teitok_project_root(cwd) or _find_teitok_project_root(
                os.path.join(cwd, "xmlfiles")
            )
            if teitok_project:
                xmlfiles_dir = os.path.join(teitok_project, "xmlfiles")
                if os.path.isdir(xmlfiles_dir):
                    args.paths = [xmlfiles_dir]
        for x in args.paths:
            # Resolve to absolute so directory detection works when cwd differs from caller (e.g. PHP/Apache)
            x_abs = os.path.abspath(os.path.normpath(x))
            if os.path.isdir(x_abs):
                by_content = getattr(args, "by_content", False)
                for root, _dirs, files in os.walk(x_abs):
                    for f in files:
                        full = os.path.join(root, f)
                        if by_content:
                            if path_to_input_format(full) is not None:
                                paths.append(full)
                        elif f.lower().endswith(".xml"):
                            paths.append(full)
            else:
                paths.append(x_abs)
        if teitok_project is None and paths:
            first_dir = os.path.dirname(paths[0])
            teitok_project = _find_teitok_project_root(first_dir)
    base_for_display = _common_base(paths)
    if not paths:
        if args.json:
            print("[]")
        return 0
    if args.index:
        # One line per file: hash\tbasename. Used by easycorp to rebuild duplicate index from <text> content.
        # Optional --output PATH: if PATH ends with .sqlite, also write to SQLite for fast lookup (WaC-style).
        # Inside a TEITOK project, default --output to tmp/deduplication.sqlite when omitted.
        sqlite_path = None
        out_arg = getattr(args, "output", None)
        if out_arg and out_arg.strip():
            out = out_arg.strip()
            if out.lower().endswith(".sqlite"):
                sqlite_path = os.path.abspath(os.path.normpath(out))
        elif teitok_project:
            default_sqlite = os.path.join(teitok_project, "tmp", "deduplication.sqlite")
            sqlite_path = os.path.abspath(os.path.normpath(default_sqlite))
        conn = None
        incremental = getattr(args, "incremental", False) and bool(sqlite_path)
        near_identical = getattr(args, "near_identical", False)
        if sqlite_path:
            try:
                import sqlite3
                parent = os.path.dirname(sqlite_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                conn = sqlite3.connect(sqlite_path)
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS dedup_index (hash TEXT NOT NULL, filename TEXT NOT NULL, PRIMARY KEY (hash, filename))"
                )
                if incremental:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS dedup_meta (path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL, hash TEXT NOT NULL)"
                    )
                else:
                    conn.execute("DELETE FROM dedup_index")
                near_identical = getattr(args, "near_identical", False) and bool(sqlite_path)
                if near_identical:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS near_dup_sigs (path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL, sig BLOB NOT NULL)"
                    )
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS near_dup_lsh (band_id INTEGER NOT NULL, bucket TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY (band_id, bucket, path))"
                    )
                    if not incremental:
                        conn.execute("DELETE FROM near_dup_sigs")
                        conn.execute("DELETE FROM near_dup_lsh")
                conn.commit()
            except Exception:
                conn = None
                sqlite_path = None
                incremental = False
        hash_to_files: Dict[str, List[str]] = {}
        current_rels: set[str] = set()
        paths_sorted = sorted(paths)
        show_progress = not getattr(args, "quiet", False)
        for path in _progress_iter(paths_sorted, len(paths_sorted), "files", enabled=show_progress):
            rel = _path_relative_to_base(path, base_for_display)
            current_rels.add(rel)
            if incremental and conn is not None:
                try:
                    mtime = os.path.getmtime(path)
                    size = os.path.getsize(path)
                except OSError:
                    mtime = size = None
                if mtime is not None and size is not None:
                    row = conn.execute(
                        "SELECT mtime, size, hash FROM dedup_meta WHERE path = ?", (rel,)
                    ).fetchone()
                    if row is not None and row[0] == mtime and row[1] == size:
                        hash_to_files.setdefault(row[2], []).append(rel)
                        continue
                h = _content_fingerprint_hash(path) if getattr(args, "by_content", False) else teitok_text_fingerprint_hash(path)
                try:
                    conn.execute("DELETE FROM dedup_index WHERE filename = ?", (rel,))
                    conn.execute("DELETE FROM dedup_meta WHERE path = ?", (rel,))
                    if h is not None:
                        conn.execute(
                            "INSERT INTO dedup_index (hash, filename) VALUES (?, ?)", (h, rel)
                        )
                        if mtime is not None and size is not None:
                            conn.execute(
                                "INSERT OR REPLACE INTO dedup_meta (path, mtime, size, hash) VALUES (?, ?, ?, ?)",
                                (rel, mtime, size, h),
                            )
                        hash_to_files.setdefault(h, []).append(rel)
                        if getattr(args, "verbose", False):
                            print(h + "\t" + rel)
                except Exception:
                    pass
                if near_identical and conn is not None:
                    text = _normalized_text_for_path(path, getattr(args, "by_content", False))
                    if text:
                        shingles = shingle_text(text)
                        if shingles:
                            sig = minhash_signature(shingles)
                            try:
                                conn.execute("DELETE FROM near_dup_sigs WHERE path = ?", (rel,))
                                conn.execute("DELETE FROM near_dup_lsh WHERE path = ?", (rel,))
                                conn.execute(
                                    "INSERT OR REPLACE INTO near_dup_sigs (path, mtime, size, sig) VALUES (?, ?, ?, ?)",
                                    (rel, mtime if mtime is not None else 0, size if size is not None else 0, signature_to_blob(sig)),
                                )
                                for band_id, bucket in lsh_bands(sig):
                                    conn.execute("INSERT OR REPLACE INTO near_dup_lsh (band_id, bucket, path) VALUES (?, ?, ?)", (band_id, bucket, rel))
                            except Exception:
                                pass
                continue
            h = _content_fingerprint_hash(path) if getattr(args, "by_content", False) else teitok_text_fingerprint_hash(path)
            if h is not None:
                hash_to_files.setdefault(h, []).append(rel)
                if getattr(args, "verbose", False):
                    print(h + "\t" + rel)
                if conn is not None:
                    try:
                        conn.execute("INSERT INTO dedup_index (hash, filename) VALUES (?, ?)", (h, rel))
                    except Exception:
                        pass
            if near_identical and conn is not None:
                text = _normalized_text_for_path(path, getattr(args, "by_content", False))
                if text:
                    shingles = shingle_text(text)
                    if shingles:
                        sig = minhash_signature(shingles)
                        try:
                            mtime = os.path.getmtime(path) if os.path.exists(path) else 0
                            size = os.path.getsize(path) if os.path.exists(path) else 0
                            conn.execute("DELETE FROM near_dup_sigs WHERE path = ?", (rel,))
                            conn.execute("DELETE FROM near_dup_lsh WHERE path = ?", (rel,))
                            conn.execute(
                                "INSERT OR REPLACE INTO near_dup_sigs (path, mtime, size, sig) VALUES (?, ?, ?, ?)",
                                (rel, mtime, size, signature_to_blob(sig)),
                            )
                            for band_id, bucket in lsh_bands(sig):
                                conn.execute("INSERT OR REPLACE INTO near_dup_lsh (band_id, bucket, path) VALUES (?, ?, ?)", (band_id, bucket, rel))
                        except Exception:
                            pass
        if conn is not None and incremental:
            try:
                meta_paths = set(row[0] for row in conn.execute("SELECT path FROM dedup_meta").fetchall())
                to_remove = meta_paths - current_rels
                for batch in _chunks(sorted(to_remove), 5000):
                    placeholders = ",".join(["?"] * len(batch))
                    conn.execute("DELETE FROM dedup_meta WHERE path IN (" + placeholders + ")", batch)
                    conn.execute("DELETE FROM dedup_index WHERE filename IN (" + placeholders + ")", batch)
                    if near_identical:
                        conn.execute("DELETE FROM near_dup_sigs WHERE path IN (" + placeholders + ")", batch)
                        conn.execute("DELETE FROM near_dup_lsh WHERE path IN (" + placeholders + ")", batch)
            except Exception:
                pass
        if conn is not None:
            try:
                conn.commit()
                conn.close()
            except Exception:
                pass
        # Always report duplicate groups (build index only when --index; report in both cases)
        index_groups: List[List[str]] = [sorted(files) for files in hash_to_files.values() if len(files) > 1]
        if getattr(args, "json", False):
            print(json.dumps(index_groups, indent=2))
            return 0 if not index_groups else 1
        for g in index_groups:
            print("Duplicate set (%d files):" % len(g))
            for fn in g:
                print("  ", fn)
            print()
        return 0 if not index_groups else 1
    if getattr(args, "by_content", False):
        hash_to_paths_list: Dict[str, List[str]] = {}
        show_progress = not getattr(args, "quiet", False)
        for path in _progress_iter(paths, len(paths), "files", enabled=show_progress):
            h = _content_fingerprint_hash(path)
            if h is not None:
                hash_to_paths_list.setdefault(h, []).append(path)
        groups = [g for g in hash_to_paths_list.values() if len(g) > 1]
    else:
        show_progress = not getattr(args, "quiet", False)
        paths_iter = _progress_iter(paths, len(paths), "files", enabled=show_progress)
        groups = find_duplicate_teitok_files(paths_iter)
    if args.json:
        # Output relative paths in JSON when we have a common base
        if base_for_display and groups:
            groups_for_json = [[_path_relative_to_base(p, base_for_display) for p in g] for g in groups]
        else:
            groups_for_json = groups
        print(json.dumps(groups_for_json, indent=2))
        return 0 if not groups else 1
    for g in groups:
        print("Duplicate set (%d files):" % len(g))
        for path in sorted(g):
            print("  ", _path_relative_to_base(path, base_for_display))
        print()
    return 0 if not groups else 1


def main(argv: Optional[list[str]] = None) -> int:
    _register_builtin_formats()

    if argv is None:
        argv = sys.argv[1:]

    # Global --version / -V
    if "--version" in argv or "-V" in argv:
        print(__version__)
        return 0

    # Global --list-formats shortcut, mirroring flexipipe-style UX
    if "--list-formats" in argv and not any(
        cmd in argv for cmd in ("info", "install", "update", "convert", "duplicates")
    ):
        info_argv = ["formats"]
        if "--json" in argv:
            info_argv.append("--json")
        return _cmd_info(info_argv)

    # Subcommands: flexiconv info|install|update|convert|duplicates ...
    if argv:
        cmd = argv[0]
        rest = argv[1:]
        if cmd == "info":
            return _cmd_info(rest)
        if cmd == "install":
            return _cmd_install(rest)
        if cmd == "update":
            return _cmd_update(rest)
        if cmd == "convert":
            return _cmd_convert(rest)
        if cmd == "duplicates":
            return _cmd_duplicates(rest)

    # Default: convert INPUT [OUTPUT]
    return _run_convert(_make_convert_parser("flexiconv"), argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

