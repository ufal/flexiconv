"""Simple registries for input and output formats.

This mirrors the design of flexipipe's IORegistry in a lightweight way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

from .core.model import Document


@dataclass
class InputFormat:
    name: str
    aliases: tuple[str, ...]
    loader: Callable[..., Document]
    description: str = ""
    # Coarse document-type label (e.g. 'richtext', 'tei/pivot', 'ocr', ...).
    # Used by the CLI to group and describe formats.
    data_type: str = "other"

    def matches(self, value: str) -> bool:
        v = value.lower()
        return v == self.name.lower() or v in (a.lower() for a in self.aliases)


@dataclass
class OutputFormat:
    name: str
    aliases: tuple[str, ...]
    saver: Callable[..., None]
    description: str = ""
    # Coarse document-type label (e.g. 'richtext', 'tei/pivot', 'ocr', ...).
    data_type: str = "other"
    # Names of layers this output format knows how to export.
    # Used only for verbose lossiness reporting in the CLI.
    supported_layers: tuple[str, ...] = ()

    def matches(self, value: str) -> bool:
        v = value.lower()
        return v == self.name.lower() or v in (a.lower() for a in self.aliases)


class Registry:
    def __init__(self) -> None:
        self._inputs: Dict[str, InputFormat] = {}
        self._outputs: Dict[str, OutputFormat] = {}

    def register_input(self, fmt: InputFormat) -> None:
        self._inputs[fmt.name.lower()] = fmt
        for alias in fmt.aliases:
            self._inputs[alias.lower()] = fmt

    def register_output(self, fmt: OutputFormat) -> None:
        self._outputs[fmt.name.lower()] = fmt
        for alias in fmt.aliases:
            self._outputs[alias.lower()] = fmt

    def get_input(self, name: str) -> Optional[InputFormat]:
        return self._inputs.get(name.lower())

    def get_output(self, name: str) -> Optional[OutputFormat]:
        return self._outputs.get(name.lower())


registry = Registry()

