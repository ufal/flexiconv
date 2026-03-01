"""Flexiconv – corpus and document conversion toolkit.

Public API is still experimental. The core concepts are:

- flexiconv.core.model: pivot data structures (Document, Layer, Node, Span, Edge, Anchor)
- flexiconv.registry: simple registries for input/output formats
- flexiconv.io.*: format-specific importers/exporters
"""

def __get_version() -> str:
    try:
        from importlib.metadata import version
        return version("flexiconv")
    except Exception:
        return "0.1.0"

__version__ = __get_version()

from .core.model import Document, Layer, Node, Span, Edge, Anchor, AnchorType
from . import registry
from .io.teitok_xml import load_teitok, save_teitok, teitok_text_fingerprint, teitok_text_fingerprint_hash, find_duplicate_teitok_files
from .io.tei_p5 import load_tei_p5, save_tei_p5
from .io.rtf import load_rtf, save_rtf

__all__ = [
    "Document",
    "Layer",
    "Node",
    "Span",
    "Edge",
    "Anchor",
    "AnchorType",
    "registry",
    "load_teitok",
    "save_teitok",
    "teitok_text_fingerprint",
    "teitok_text_fingerprint_hash",
    "find_duplicate_teitok_files",
    "load_tei_p5",
    "save_tei_p5",
    "load_rtf",
    "save_rtf",
]

