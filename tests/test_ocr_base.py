from __future__ import annotations

from pathlib import Path

import pytest

from econ_pdf_extract.ocr import (
    NullOcrBackend,
    OcrBackendFactory,
    RegionCropper,
)


def test_null_backend_and_factory():
    backend = OcrBackendFactory.create("none")
    assert isinstance(backend, NullOcrBackend)
    assert backend.name == "none"
    assert backend.is_available() is True
    assert backend.transcribe(b"fake-png", mode="formula") is None

    with pytest.raises(ValueError, match="Supported backends: none, glm_ocr"):
        OcrBackendFactory.create("got_ocr")

    with pytest.raises(ValueError, match="Unknown OCR backend"):
        OcrBackendFactory.create("nonexistent")


def test_region_cropper_excludes_tag_and_renders_png(synthetic_paper_pdf: Path):
    cropper = RegionCropper.from_config()
    page_rect = (0.0, 0.0, 612.0, 792.0)
    eq_bbox = (170.0, 175.0, 520.0, 192.0)
    tag_bbox = (500.0, 175.0, 520.0, 192.0)

    rect = cropper.compute_crop_rect(page_rect, eq_bbox, tag_bbox=tag_bbox)
    assert rect[0] == pytest.approx(164.0)
    assert rect[2] == pytest.approx(496.0)
    assert rect[2] < tag_bbox[0]
    assert rect[1] == pytest.approx(171.0)
    assert rect[3] == pytest.approx(196.0)

    png_bytes, rendered_rect = cropper.crop(synthetic_paper_pdf, page=4, bbox=eq_bbox, tag_bbox=tag_bbox)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png_bytes) > 200
    assert rendered_rect == rect
