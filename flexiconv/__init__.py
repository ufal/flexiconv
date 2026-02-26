"""Flexiconv – corpus and document conversion toolkit.

Public API is still experimental. The core concepts are:

- flexiconv.core.model: pivot data structures (Document, Layer, Node, Span, Edge, Anchor)
- flexiconv.registry: simple registries for input/output formats
- flexiconv.io.*: format-specific importers/exporters
"""

from .core.model import Document, Layer, Node, Span, Edge, Anchor, AnchorType
from . import registry
from .io.teitok_xml import load_teitok, save_teitok
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
    "load_tei_p5",
    "save_tei_p5",
    "load_rtf",
    "save_rtf",
]

