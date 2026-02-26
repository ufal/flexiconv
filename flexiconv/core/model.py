from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AnchorType(str, Enum):
    """Type of anchor for a node/span."""

    CHAR = "char"
    TOKEN = "token"
    TIME = "time"


@dataclass
class Anchor:
    """Reference to a position or span in the underlying data."""

    type: AnchorType
    # Character offsets (inclusive start, exclusive end)
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    # Token indices (1-based, inclusive)
    token_start: Optional[int] = None
    token_end: Optional[int] = None
    # Time offsets (in seconds, or as defined by the timeline)
    timeline_id: Optional[str] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None


@dataclass
class Node:
    """Generic node in a layer."""

    id: str
    type: str
    anchors: List[Anchor] = field(default_factory=list)
    features: Dict[str, Any] = field(default_factory=dict)
    parent: Optional[str] = None
    children: List[str] = field(default_factory=list)


@dataclass
class Span:
    """Labeled span over an anchor range."""

    id: str
    label: str
    anchor: Anchor
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    """Directed labeled relation between nodes."""

    id: str
    source: str
    target: str
    label: str
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Layer:
    """Collection of nodes, spans, and edges of one conceptual type."""

    name: str
    nodes: Dict[str, Node] = field(default_factory=dict)
    spans: Dict[str, Span] = field(default_factory=dict)
    edges: Dict[str, Edge] = field(default_factory=dict)


@dataclass
class MediaResource:
    id: str
    uri: str
    mime_type: str = ""
    duration: Optional[float] = None
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Timeline:
    id: str
    unit: str = "seconds"
    media_id: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """Pivot document representation."""

    id: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    attrs: Dict[str, Any] = field(default_factory=dict)
    media: Dict[str, MediaResource] = field(default_factory=dict)
    timelines: Dict[str, Timeline] = field(default_factory=dict)
    layers: Dict[str, Layer] = field(default_factory=dict)

    def get_or_create_layer(self, name: str) -> Layer:
        layer = self.layers.get(name)
        if layer is None:
            layer = Layer(name=name)
            self.layers[name] = layer
        return layer

