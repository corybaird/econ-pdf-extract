from __future__ import annotations

from typing import Any

from econ_pdf_extract.ocr.base import NullOcrBackend, OcrBackend

SUPPORTED_OCR_BACKENDS = ("none", "glm_ocr")


class OcrBackendFactory:
    """Resolves configured OCR backend names ('none', 'glm_ocr') into backend instances."""

    @staticmethod
    def create(name: str = "none", config: dict[str, Any] | None = None) -> OcrBackend:
        key = (name or "none").strip().lower()
        if key == "none":
            return NullOcrBackend()
        if key == "glm_ocr":
            from econ_pdf_extract.ocr.glm_ocr import GlmOcrBackend

            return GlmOcrBackend.from_config(config)
        supported = ", ".join(SUPPORTED_OCR_BACKENDS)
        raise ValueError(f"Unknown OCR backend {name!r}. Supported backends: {supported}.")
