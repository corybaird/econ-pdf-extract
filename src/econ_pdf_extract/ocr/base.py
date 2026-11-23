from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from econ_pdf_extract.core.models import BBox

OcrMode = Literal["formula", "page", "table"]
OcrPolicy = Literal["none", "fallback", "all_displays"]


class OcrError(RuntimeError):
    """Base error raised by OCR backends."""


class OcrBackendUnavailableError(OcrError):
    """Raised when an OCR backend endpoint or service is unset or unreachable."""


@dataclass
class OcrResult:
    markdown: str
    latex: str | None
    kind: Literal["text", "formula", "table"]
    bbox: BBox | None
    backend: str
    model: str | None = None
    elapsed_ms: float = 0.0


class OcrBackend(ABC):
    """Contract for pluggable OCR backends."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def transcribe(self, image_bytes: bytes, mode: OcrMode = "formula", region: BBox | None = None) -> OcrResult | None: ...


class NullOcrBackend(OcrBackend):
    """Default no-op OCR backend that leaves extraction purely on PyMuPDF text."""

    @property
    def name(self) -> str:
        return "none"

    def is_available(self) -> bool:
        return True

    def transcribe(self, image_bytes: bytes, mode: OcrMode = "formula", region: BBox | None = None) -> OcrResult | None:
        return None
