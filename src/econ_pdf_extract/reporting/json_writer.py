from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from econ_pdf_extract.core.models import Attribution, ExtractionResult


class JsonReportWriter:
    """Serializes ExtractionResult with full provenance to JSON strings or timestamped files."""

    def __init__(self, include_literature: bool = True, include_duplicates: bool = True, indent: int = 2):
        self._include_literature = include_literature
        self._include_duplicates = include_duplicates
        self._indent = indent

    def to_payload(self, result: ExtractionResult) -> dict[str, Any]:
        payload = result.to_dict()
        if not self._include_literature or not self._include_duplicates:
            filtered = []
            for claim in payload.get("claims", []):
                if not self._include_literature and claim.get("attribution") == Attribution.LITERATURE.value:
                    continue
                if not self._include_duplicates and claim.get("duplicate_of") is not None:
                    continue
                filtered.append(claim)
            payload["claims"] = filtered
        return payload

    def to_json(self, result: ExtractionResult) -> str:
        return json.dumps(self.to_payload(result), indent=self._indent, ensure_ascii=False)

    def write(self, result: ExtractionResult, output_dir: Path, timestamp: str | None = None) -> Path:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        dest = out_dir / f"extracted_{result.paper.paper_id}_{ts}.json"
        dest.write_text(self.to_json(result) + "\n", encoding="utf-8")
        return dest
