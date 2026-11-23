from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import BBox


class RegionCropper:
    """Renders padded display-equation bboxes (excluding right-margin tags) to PNG bytes."""

    def __init__(self, dpi: int = 250, pad_x: float = 6.0, pad_y: float = 4.0, tag_gap: float = 4.0):
        self._dpi = int(dpi)
        self._pad_x = float(pad_x)
        self._pad_y = float(pad_y)
        self._tag_gap = float(tag_gap)

    @classmethod
    def from_config(cls, ocr_cfg: dict[str, Any] | None = None) -> RegionCropper:
        cfg = ocr_cfg if ocr_cfg is not None else ConfigLoader().load("extraction.yaml").get("ocr", {})
        return cls(
            dpi=int(cfg.get("crop_dpi", 250)),
            pad_x=float(cfg.get("pad_x_pt", 6.0)),
            pad_y=float(cfg.get("pad_y_pt", 4.0)),
            tag_gap=float(cfg.get("tag_gap_pt", 4.0)),
        )

    def compute_crop_rect(self, page_rect: BBox, bbox: BBox, tag_bbox: BBox | None = None) -> BBox:
        x0, y0, x1, y1 = bbox
        cx0 = max(page_rect[0], x0 - self._pad_x)
        cy0 = max(page_rect[1], y0 - self._pad_y)
        cx1 = min(page_rect[2], x1 + self._pad_x)
        cy1 = min(page_rect[3], y1 + self._pad_y)

        if tag_bbox is not None and tag_bbox[0] > x0 + 10.0:
            clipped_x1 = tag_bbox[0] - self._tag_gap
            if clipped_x1 > cx0 + 4.0:
                cx1 = min(cx1, clipped_x1)

        if cx1 <= cx0:
            cx1 = min(page_rect[2], cx0 + 1.0)
        if cy1 <= cy0:
            cy1 = min(page_rect[3], cy0 + 1.0)
        return (cx0, cy0, cx1, cy1)

    def crop(self, pdf_path: Path | str, page: int, bbox: BBox, tag_bbox: BBox | None = None) -> tuple[bytes, BBox]:
        with pymupdf.open(Path(pdf_path)) as doc:
            raw_page = doc[page - 1]
            page_rect = (float(raw_page.rect.x0), float(raw_page.rect.y0), float(raw_page.rect.x1), float(raw_page.rect.y1))
            crop_rect = self.compute_crop_rect(page_rect, bbox, tag_bbox=tag_bbox)
            pix = raw_page.get_pixmap(clip=pymupdf.Rect(*crop_rect), dpi=self._dpi)
            return pix.tobytes("png"), crop_rect
