from __future__ import annotations

import logging
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import (
    Document,
    MathKind,
    MathObject,
    SourceChannel,
    SymbolDef,
)
from econ_pdf_extract.math_extract.displays import DisplayEquationDetector
from econ_pdf_extract.math_extract.logic import LogicExtractor
from econ_pdf_extract.math_extract.symbols import SymbolDefinitionExtractor

logger = logging.getLogger(__name__)

_DISPLAY_KINDS = frozenset(
    {
        MathKind.DISPLAY_EQUATION,
        MathKind.MODEL_SPECIFICATION,
        MathKind.ESTIMATION_PROBLEM,
        MathKind.EVALUATION_FORMULA,
    }
)


class MathExtractor:
    """Coordinates display detection, targeted OCR fallback, logic extraction, and symbol parsing."""

    def __init__(self, extraction_cfg: dict[str, Any] | None = None, math_cfg: dict[str, Any] | None = None):
        loader = ConfigLoader()
        ecfg = extraction_cfg if extraction_cfg is not None else loader.load("extraction.yaml")
        mcfg = math_cfg if math_cfg is not None else loader.load("math_patterns.yaml")
        self._displays = DisplayEquationDetector(ecfg.get("math", {}), mcfg)
        self._logic = LogicExtractor(mcfg)
        self._symbols = SymbolDefinitionExtractor(mcfg)

    def extract(self, doc: Document, ocr_backend: Any = None, ocr_policy: str = "none", cropper: Any = None) -> tuple[list[MathObject], list[SymbolDef], int]:
        displays = self._displays.detect(doc)
        self._logic.classify_displays(displays)

        ocr_calls = 0
        if ocr_backend is not None and ocr_policy != "none" and getattr(ocr_backend, "name", "none") != "none":
            ocr_calls = self._run_targeted_ocr(doc, displays, ocr_backend, ocr_policy, cropper)

        prose_logic = self._logic.extract_prose_logic(doc)
        all_math = sorted([*displays, *prose_logic], key=lambda m: (m.page, m.bbox[1], m.bbox[0]))
        symbols = self._symbols.extract(doc, all_math)
        return all_math, symbols, ocr_calls

    @staticmethod
    def _run_targeted_ocr(doc: Document, displays: list[MathObject], ocr_backend: Any, ocr_policy: str, cropper: Any) -> int:
        if cropper is None:
            raise ValueError("RegionCropper is required when running targeted OCR")
        calls = 0
        for obj in displays:
            if obj.kind not in _DISPLAY_KINDS:
                continue
            if ocr_policy == "fallback" and not obj.needs_ocr:
                continue
            if ocr_policy not in {"fallback", "all_displays"}:
                continue
            png_bytes, crop_rect = cropper.crop(doc.source_path, obj.page, obj.bbox, obj.tag_bbox)
            result = ocr_backend.transcribe(png_bytes, mode="formula", region=crop_rect)
            calls += 1
            if result is not None and result.latex:
                obj.latex = result.latex
                obj.source_channel = SourceChannel.OCR
        logger.debug("Ran %d targeted OCR calls on %s", calls, doc.paper_id)
        return calls
