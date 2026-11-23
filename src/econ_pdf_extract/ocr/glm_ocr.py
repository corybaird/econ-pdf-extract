from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Literal

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import BBox
from econ_pdf_extract.ocr.base import (
    OcrBackend,
    OcrBackendUnavailableError,
    OcrError,
    OcrMode,
    OcrResult,
)

_PROMPTS: dict[OcrMode, str] = {
    "formula": "Formula Recognition:",
    "page": "Text Recognition:",
    "table": "Table Recognition:",
}

_KINDS: dict[OcrMode, Literal["text", "formula", "table"]] = {
    "formula": "formula",
    "page": "text",
    "table": "table",
}


def strip_latex_delimiters(text: str) -> str:
    """Strip outer Markdown code fences and LaTeX math delimiters from an OCR formula string."""
    cleaned = text.strip()
    fence = re.match(r"^```(?:latex|tex|math)?\s*\n(.*?)\n```$", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    for left, right in (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)"), ("$", "$")):
        if cleaned.startswith(left) and cleaned.endswith(right) and len(cleaned) > len(left) + len(right):
            cleaned = cleaned[len(left) : -len(right)].strip()
            break
    return cleaned


class GlmOcrBackend(OcrBackend):
    """OpenAI-compatible stdlib HTTP client for a remote vLLM GLM-OCR server."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str = "zai-org/GLM-OCR", timeout_seconds: float = 60.0):
        self._base_url = (base_url if base_url is not None else os.environ.get("VLLM_BASE_URL", "")).strip()
        self._api_key = (api_key if api_key is not None else os.environ.get("VLLM_API_KEY", "")).strip()
        self._model = model
        self._timeout = float(timeout_seconds)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> GlmOcrBackend:
        cfg = config if config is not None else ConfigLoader().load("extraction.yaml").get("ocr", {})
        return cls(
            base_url=cfg.get("base_url"),
            api_key=cfg.get("api_key"),
            model=str(cfg.get("glm_model", "zai-org/GLM-OCR")),
            timeout_seconds=float(cfg.get("timeout_seconds", 60.0)),
        )

    @property
    def name(self) -> str:
        return "glm_ocr"

    @property
    def model(self) -> str:
        return self._model

    def _endpoint(self, suffix: str) -> str:
        base = self._base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}{suffix}"
        return f"{base}/v1{suffix}"

    def is_available(self) -> bool:
        if not self._base_url:
            return False
        req = urllib.request.Request(self._endpoint("/models"), method="GET")
        if self._api_key:
            req.add_header("Authorization", f"Bearer {self._api_key}")
        try:
            with urllib.request.urlopen(req, timeout=min(self._timeout, 5.0)) as resp:
                return int(getattr(resp, "status", 200)) == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def transcribe(self, image_bytes: bytes, mode: OcrMode = "formula", region: BBox | None = None) -> OcrResult:
        if not self._base_url:
            raise OcrBackendUnavailableError("VLLM_BASE_URL is not set; cannot call GlmOcrBackend.")
        if mode not in _PROMPTS:
            raise ValueError(f"Unsupported OCR mode: {mode!r}")

        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self._model,
            "temperature": 0.0,
            "max_tokens": 2048,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": _PROMPTS[mode]},
                    ],
                }
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        req = urllib.request.Request(self._endpoint("/chat/completions"), data=body, headers=headers, method="POST")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw_response = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise OcrError(f"GLM-OCR HTTP {exc.code}: {err_body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OcrBackendUnavailableError(f"GLM-OCR endpoint unreachable at {self._base_url}: {exc}") from exc
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        try:
            parsed = json.loads(raw_response)
            content = str(parsed["choices"][0]["message"]["content"]).strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise OcrError(f"Malformed GLM-OCR response payload: {exc}") from exc

        latex = strip_latex_delimiters(content) if mode == "formula" else None
        return OcrResult(
            markdown=content,
            latex=latex,
            kind=_KINDS[mode],
            bbox=None,
            backend=self.name,
            model=self._model,
            elapsed_ms=elapsed_ms,
        )
