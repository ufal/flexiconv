from __future__ import annotations

import argparse
import os
import re
import sys
import subprocess
import unicodedata
from typing import Optional

from . import (
    load_rtf,
    load_tei_p5,
    load_teitok,
    save_rtf,
    save_tei_p5,
    save_teitok,
)
from .registry import InputFormat, OutputFormat, registry
from .mime import describe_unsupported_mime, detect_mime, mime_to_format, path_to_input_format, path_to_output_format
from .io.teitok_xml import _find_teitok_project_root


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
        )
    )
    registry.register_input(
        InputFormat(
            name="tei",
            aliases=("tei-p5",),
            loader=load_tei_p5,
            description="Generic TEI P5 documents (tokens via <w> or <tok>, sentences via <s>).",
        )
    )
    registry.register_input(
        InputFormat(
            name="rtf",
            aliases=(),
            loader=load_rtf,
            description="Rich Text Format; imported as plain text with simple line-based sentences.",
        )
    )
    registry.register_input(
        InputFormat(
            name="html",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.html", "load_html"),
            description="HTML; imported as paragraph-like blocks in a 'structure' layer (no tokens).",
        )
    )
    registry.register_input(
        InputFormat(
            name="docx",
            aliases=("word",),
            loader=_lazy_loader("flexiconv.io.docx", "load_docx"),
            description="Word DOCX; converted to TEITOK-style TEI (styles, tables, images, links, footnotes).",
        )
    )
    registry.register_input(
        InputFormat(
            name="txt",
            aliases=("text", "plain"),
            loader=_lazy_loader("flexiconv.io.txt", "load_txt"),
            description="Plain text; line-break meaning set by --linebreaks (sentence, paragraph, double).",
        )
    )
    registry.register_input(
        InputFormat(
            name="md",
            aliases=("markdown",),
            loader=_lazy_loader("flexiconv.io.md", "load_md"),
            description="Markdown; converted to structure (paragraphs, headings, lists) via HTML extraction.",
        )
    )
    registry.register_input(
        InputFormat(
            name="hocr",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.hocr", "load_hocr"),
            description="hOCR (HTML with ocr_page/ocr_line/ocrx_word); converted to TEITOK-style TEI with bbox.",
        )
    )
    registry.register_input(
        InputFormat(
            name="pagexml",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.page_xml", "load_page_xml"),
            description="PAGE XML (PcGts); converted to TEITOK-style TEI with facsimile/zones and bbox.",
        )
    )
    registry.register_input(
        InputFormat(
            name="alto",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.alto", "load_alto"),
            description="ALTO XML; converted to TEITOK-style TEI with facsimile/zones and bbox, similar to PAGE XML.",
        )
    )
    registry.register_input(
        InputFormat(
            name="srt",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.srt", "load_srt"),
            description="SRT subtitles; converted to TEITOK-style TEI with <u start/end> and an audio recordingStmt.",
        )
    )
    registry.register_input(
        InputFormat(
            name="eaf",
            aliases=("elan",),
            loader=_lazy_loader("flexiconv.io.eaf", "load_eaf"),
            description="ELAN EAF; converted to TEITOK-style TEI with time-aligned <u> utterances and audio recordingStmt.",
        )
    )
    registry.register_input(
        InputFormat(
            name="textgrid",
            aliases=("praat", "trs-praat"),
            loader=_lazy_loader("flexiconv.io.textgrid", "load_textgrid"),
            description="Praat TextGrid; converted to TEITOK-style TEI with <u start/end who> and recordingStmt.",
        )
    )
    registry.register_input(
        InputFormat(
            name="doreco",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.doreco", "load_doreco"),
            description="DoReCo-specific ELAN EAF; converted with DoReCo tier mappings into TEITOK-style TEI.",
        )
    )
    registry.register_input(
        InputFormat(
            name="exb",
            aliases=("exmaralda",),
            loader=_lazy_loader("flexiconv.io.exb", "load_exb"),
            description="EXMARaLDA basic transcription (.exb) to TEITOK-style TEI with time-aligned <u>.",
        )
    )
    registry.register_input(
        InputFormat(
            name="chat",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.chat", "load_chat"),
            description="CHAT/CHILDES transcripts (.cha) converted to TEI/TEITOK <u>/<note> structure.",
        )
    )
    registry.register_input(
        InputFormat(
            name="tmx",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.tmx", "load_tmx"),
            description="TMX translation memories; TEI with <div lang>/<ab tuid> alignment blocks.",
        )
    )
    registry.register_input(
        InputFormat(
            name="conllu",
            aliases=("conll-u",),
            loader=_lazy_loader("flexiconv.io.conllu", "load_conllu"),
            description="CoNLL-U; UD-style sentences/tokens with standardized metadata in comments.",
        )
    )
    registry.register_input(
        InputFormat(
            name="tbt",
            aliases=("toolbox",),
            loader=_lazy_loader("flexiconv.io.tbt", "load_tbt"),
            description="Toolbox (TBT) interlinear text; converted to TEITOK-style TEI with <s>/<tok>/<morph>.",
        )
    )
    registry.register_input(
        InputFormat(
            name="tcf",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.tcf", "load_tcf"),
            description="TCF (Text Corpus Format, D-Spin/WebLicht); converted to TEITOK-style TEI with <s>/<tok>, lemma, pos, deps, <name>.",
        )
    )
    registry.register_input(
        InputFormat(
            name="trs",
            aliases=("transcriber",),
            loader=_lazy_loader("flexiconv.io.trs", "load_trs"),
            description="Transcriber TRS; converted to TEITOK-style TEI with <ab>/<ug>/<u start end who>/<tok start end> and recordingStmt.",
        )
    )
    registry.register_input(
        InputFormat(
            name="brat",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.brat", "load_brat"),
            description="Brat stand-off (.ann + .txt); converted to TEITOK-style TEI with <tok idx> and standOff <span>/<link> elements.",
        )
    )
    registry.register_input(
        InputFormat(
            name="folia",
            aliases=(),
            loader=_lazy_loader("flexiconv.io.folia", "load_folia"),
            description="FoLiA (Format for Linguistic Annotation); converted to TEITOK-style TEI with <s>/<tok>, lemma, pos, head, deprel.",
        )
    )
    registry.register_input(
        InputFormat(
            name="vert",
            aliases=("vrt",),
            loader=_lazy_loader("flexiconv.io.vert", "load_vert"),
            description="Vertical/VRT corpora; converted to TEITOK-style TEI with <div>/<s>/<tok> and heuristic spacing.",
        )
    )

    registry.register_output(
        OutputFormat(
            name="teitok",
            aliases=("tt",),
            saver=save_teitok,
            description="Write a minimal TEITOK-style TEI with <tok> tokens and <s> sentences.",
            supported_layers=("tokens", "sentences", "structure", "rendition"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="hocr",
            aliases=(),
            saver=_lazy_loader("flexiconv.io.hocr", "save_hocr"),
            description="hOCR (from TEI with bbox or future FPM); supports round-trip hOCR→TEI→hOCR.",
            supported_layers=("tokens", "structure"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="tei",
            aliases=("tei-p5",),
            saver=save_tei_p5,
            description="Write simple TEI P5 with <w> tokens and <s> sentences (or plain <p> from structure).",
            supported_layers=("tokens", "sentences", "structure"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="rtf",
            aliases=(),
            saver=save_rtf,
            description="Write a text-only RTF; each sentence becomes one paragraph.",
            supported_layers=("tokens", "sentences"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="html",
            aliases=(),
            saver=_lazy_saver("flexiconv.io.html", "save_html"),
            description="Write simple HTML with one <p> per paragraph (and spans for inline styles when available).",
            supported_layers=("tokens", "sentences", "structure", "rendition"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="txt",
            aliases=("text", "plain"),
            saver=_lazy_saver("flexiconv.io.txt", "save_txt"),
            description="Plain text; one line per sentence/paragraph or blocks separated by blank lines (--linebreaks).",
            supported_layers=("tokens", "sentences", "structure"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="srt",
            aliases=(),
            saver=_lazy_saver("flexiconv.io.srt", "save_srt"),
            description="SRT subtitles from TEI <u start/end> or an 'utterances' layer with TIME anchors.",
            supported_layers=("utterances",),
        )
    )
    registry.register_output(
        OutputFormat(
            name="conllu",
            aliases=("conll-u",),
            saver=_lazy_saver("flexiconv.io.conllu", "save_conllu"),
            description="CoNLL-U with standardized file/sentence metadata and SpaceAfter=No from space_after.",
            supported_layers=("tokens", "sentences"),
        )
    )
    registry.register_output(
        OutputFormat(
            name="doreco",
            aliases=(),
            saver=_lazy_saver("flexiconv.io.doreco", "save_doreco"),
            description="DoReCo-style ELAN EAF from TEITOK DoReCo TEI (<u>/<tok>/<m>).",
            supported_layers=(),
        )
    )
    registry.register_output(
        OutputFormat(
            name="exb",
            aliases=("exmaralda",),
            saver=_lazy_saver("flexiconv.io.exb", "save_exb"),
            description="EXMARaLDA basic transcription from TEITOK TEI with time-aligned <u>.",
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
    if name in {"rtf", "docx", "html", "md"}:
        return "richtext"
    if name in {"txt"}:
        return "plain"
    if name in {"hocr", "pagexml", "alto"}:
        return "ocr"
    if name in {"eaf", "doreco", "textgrid", "exb", "trs", "chat"}:
        return "oral/transcription"
    if name in {"srt"}:
        return "subtitles"
    if name in {"tmx"}:
        return "translation"
    if name in {"conllu"}:
        return "treebank"
    if name in {"tbt"}:
        return "igt"
    if name in {"tcf", "folia", "vert"}:
        return "corpus"
    if name in {"brat"}:
        return "stand-off annotations"
    return "other"


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
    args = parser.parse_args(argv)

    if args.what == "formats":
        print("Input formats:")
        seen = set()
        for key, fmt in registry._inputs.items():  # type: ignore[attr-defined]
            if fmt.name in seen:
                continue
            seen.add(fmt.name)
            aliases = ", ".join(fmt.aliases) if fmt.aliases else "-"
            dtype = _format_data_type(fmt.name)
            desc = f" – {fmt.description}" if fmt.description else ""
            print(f"  {fmt.name} (aliases: {aliases}; type: {dtype}){desc}")
        print("\nOutput formats:")
        seen.clear()
        for key, fmt in registry._outputs.items():  # type: ignore[attr-defined]
            if fmt.name in seen:
                continue
            seen.add(fmt.name)
            aliases = ", ".join(fmt.aliases) if fmt.aliases else "-"
            dtype = _format_data_type(fmt.name)
            desc = f" – {fmt.description}" if fmt.description else ""
            print(f"  {fmt.name} (aliases: {aliases}; type: {dtype}){desc}")
        return 0

    if args.what == "format":
        if not args.name:
            parser.error("Please specify a format name, e.g. 'flexiconv info format teitok'.")
        name = args.name
        fmt_in = registry.get_input(name)
        fmt_out = registry.get_output(name)
        if not fmt_in and not fmt_out:
            parser.error(f"Unknown format: {name}")
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

    # Load → convert (pivot) → save
    loader_kwargs: dict = {}
    if in_fmt_name == "txt":
        loader_kwargs["linebreaks"] = getattr(args, "linebreaks", "paragraph")
    if in_fmt_name == "hocr":
        # Allow disabling hOCR punctuation splitting so downstream tools (e.g. flexipipe)
        # can apply more sophisticated tokenization and to avoid creating extra tokens
        # without clear bbox correspondence when converting back to hOCR.
        loader_kwargs["split_punct"] = not getattr(args, "hocr_no_split_punct", False)
        loader_kwargs["hyphen_truncation"] = getattr(args, "hocr_hyphen_truncation", False)
    if in_fmt_name == "eaf":
        loader_kwargs["style"] = getattr(args, "eaf_style", "generic")
    if in_fmt_name == "tmx" and getattr(args, "option", None):
        opt = getattr(args, "option", "").lower()
        # Map split→join for now, since flexiconv does not yet emit multiple files.
        if opt in {"join", "annotate"}:
            loader_kwargs["mode"] = opt
        elif opt == "split":
            loader_kwargs["mode"] = "join"
    if in_fmt_name == "brat" and getattr(args, "option", None):
        # Parse BRAT-specific options of the form:
        #   --option "plain=/path/to/text.txt;ann=/path/to/anno1.ann,/path/to/anno2.ann"
        opt_raw = getattr(args, "option", "")
        for part in opt_raw.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, val = part.split("=", 1)
            key = key.strip().lower()
            val = val.strip()
            if key == "plain" and val:
                loader_kwargs["plain_path"] = val
            elif key == "ann" and val:
                loader_kwargs["ann_paths"] = [p.strip() for p in val.split(",") if p.strip()]
    if in_fmt_name == "vert" and getattr(args, "option", None):
        # Parse VERT-specific options of the form:
        #   --option "cols=form,lemma,pos,feats"
        #   --option "registry=/path/to/registry"
        opt_raw = getattr(args, "option", "")
        for part in opt_raw.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, val = part.split("=", 1)
            key = key.strip().lower()
            val = val.strip()
            if not val:
                continue
            if key == "registry":
                loader_kwargs["registry"] = val
            elif key in {"cols", "columns"}:
                loader_kwargs["columns"] = [c.strip() for c in val.split(",") if c.strip()]
    if in_fmt_name == "vert":
        # CLI flags for spacing and doc-splitting.
        loader_kwargs["spacing_mode"] = getattr(args, "spacing_mode", "guess")
        if getattr(args, "vert_no_doc_split", False):
            loader_kwargs["split_on_doc"] = False
    if in_fmt_name == "vert" and getattr(args, "option", None):
        # Parse VERT-specific options of the form:
        #   --option "cols=form,lemma,pos,feats"
        #   --option "registry=/path/to/registry"
        opt_raw = getattr(args, "option", "")
        for part in opt_raw.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, val = part.split("=", 1)
            key = key.strip().lower()
            val = val.strip()
            if not val:
                continue
            if key == "registry":
                loader_kwargs["registry"] = val
            elif key in {"cols", "columns"}:
                loader_kwargs["columns"] = [c.strip() for c in val.split(",") if c.strip()]
    try:
        try:
            doc = in_fmt.loader(path=input_path, **loader_kwargs)
        except TypeError:
            # Fallback for loaders that just take a positional path
            doc = in_fmt.loader(input_path, **loader_kwargs)
    except RuntimeError as exc:
        # Gracefully report loader-specific runtime problems (e.g. missing optional deps)
        sys.stderr.write(f"[flexiconv] {exc}\n")
        return 1

    # Verbose reporting about potential information loss
    if args.verbose:
        # Layers not handled by this output format
        supported_layers = set(out_fmt.supported_layers or ())
        present_layers = set(doc.layers.keys())
        unsupported = sorted(present_layers - supported_layers)
        if unsupported:
            sys.stderr.write(
                f"[flexiconv] Warning: output format '{out_fmt.name}' does not export "
                f"the following layers; they will be ignored: {', '.join(unsupported)}\n"
            )
        # Media/timelines not used by current simple exporters
        if doc.media or doc.timelines:
            sys.stderr.write(
                f"[flexiconv] Warning: output format '{out_fmt.name}' currently ignores "
                "media resources and timelines.\n"
            )

    saver_kwargs: dict = {}
    if out_fmt_name == "teitok":
        saver_kwargs["source_path"] = input_path
        if detected_mime:
            doc.meta["source_mime"] = detected_mime
        if getattr(args, "teitok_project", None):
            saver_kwargs["teitok_project_root"] = args.teitok_project
        if getattr(args, "copy_original", False):
            saver_kwargs["copy_original_to_originals"] = True
        if getattr(args, "prettyprint", False):
            saver_kwargs["prettyprint"] = True
    if out_fmt_name == "txt":
        saver_kwargs["linebreaks"] = getattr(args, "linebreaks", "paragraph")

    try:
        out_fmt.saver(doc, path=output_path, **saver_kwargs)
    except TypeError:
        # Savers that only accept (doc, path) or (doc, path=...)
        out_fmt.saver(doc, output_path)  # type: ignore[arg-type]

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    _register_builtin_formats()

    if argv is None:
        argv = sys.argv[1:]

    # Global --list-formats shortcut, mirroring flexipipe-style UX
    if "--list-formats" in argv and not any(
        cmd in argv for cmd in ("info", "install", "update", "convert")
    ):
        # Ignore everything else and just list formats
        return _cmd_info(["formats"])

    # Subcommands: flexiconv info|install|update|convert ...
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

    # Default: convert INPUT [OUTPUT]
    return _run_convert(_make_convert_parser("flexiconv"), argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

