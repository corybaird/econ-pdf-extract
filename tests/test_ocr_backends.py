from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Self

import pytest

from econ_pdf_extract.core.models import SourceChannel
from econ_pdf_extract.layout import LayoutCleaner, PdfReader, SectionBuilder
from econ_pdf_extract.math_extract import MathExtractor
from econ_pdf_extract.ocr import (
    OcrBackendFactory,
    OcrBackendUnavailableError,
    OcrError,
    RegionCropper,
)
from econ_pdf_extract.ocr.glm_ocr import GlmOcrBackend

_TINY_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"


class _MockVllmServer:
    def __init__(self, status: int = 200, reply_text: str = r"$$y_t = \beta_0 + \beta_1 x_t$$"):
        self.status = status
        self.reply_text = reply_text
        self.requests: list[dict[str, Any]] = []
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/v1/models":
                    self.send_response(outer.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"data": [{"id": "zai-org/GLM-OCR"}]}).encode("utf-8"))
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8")
                outer.requests.append(
                    {
                        "path": self.path,
                        "auth": self.headers.get("Authorization"),
                        "body": json.loads(raw),
                    }
                )
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if outer.status == 200:
                    payload = {"choices": [{"message": {"content": outer.reply_text}}]}
                else:
                    payload = {"error": "server failure"}
                self.wfile.write(json.dumps(payload).encode("utf-8"))

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)


def test_glm_ocr_formula_and_page_modes(monkeypatch: pytest.MonkeyPatch):
    with _MockVllmServer(status=200, reply_text=r"$$y_t = \beta_0 + \beta_1 f_t$$") as srv:
        monkeypatch.setenv("VLLM_BASE_URL", srv.base_url)
        monkeypatch.setenv("VLLM_API_KEY", "test-key")

        backend = OcrBackendFactory.create("glm_ocr")
        assert isinstance(backend, GlmOcrBackend)
        assert backend.is_available() is True

        res = backend.transcribe(_TINY_PNG, mode="formula")
        assert res.backend == "glm_ocr"
        assert res.kind == "formula"
        assert res.latex == r"y_t = \beta_0 + \beta_1 f_t"
        assert res.markdown == r"$$y_t = \beta_0 + \beta_1 f_t$$"

        page_res = backend.transcribe(_TINY_PNG, mode="page")
        assert page_res.kind == "text"
        assert page_res.latex is None

        assert len(srv.requests) == 2
        req0 = srv.requests[0]
        assert req0["path"] == "/v1/chat/completions"
        assert req0["auth"] == "Bearer test-key"
        assert req0["body"]["model"] == "zai-org/GLM-OCR"
        assert req0["body"]["temperature"] == 0.0
        content = req0["body"]["messages"][0]["content"]
        assert content[1]["text"] == "Formula Recognition:"
        data_url = content[0]["image_url"]["url"]
        assert data_url.startswith("data:image/png;base64,")
        decoded = base64.b64decode(data_url.split(",", 1)[1])
        assert decoded == _TINY_PNG

        assert srv.requests[1]["body"]["messages"][0]["content"][1]["text"] == "Text Recognition:"


def test_glm_ocr_unset_env_and_http_500(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    backend = GlmOcrBackend()
    assert backend.is_available() is False
    with pytest.raises(OcrBackendUnavailableError):
        backend.transcribe(_TINY_PNG, mode="formula")

    with _MockVllmServer(status=500) as srv:
        err_backend = GlmOcrBackend(base_url=srv.base_url)
        assert err_backend.is_available() is False
        with pytest.raises(OcrError, match="HTTP 500"):
            err_backend.transcribe(_TINY_PNG, mode="formula")


def test_targeted_ocr_fallback_only_crops_degraded_displays(synthetic_paper_pdf: Path):
    doc = SectionBuilder().build(LayoutCleaner().clean(PdfReader().read(synthetic_paper_pdf)))
    with _MockVllmServer(status=200, reply_text=r"\[\text{CER} = \mu - \frac{1}{2}\gamma\sqrt{\sigma^2}\]") as srv:
        backend = GlmOcrBackend(base_url=srv.base_url)
        cropper = RegionCropper.from_config()
        math_objs, _, ocr_calls = MathExtractor().extract(doc, ocr_backend=backend, ocr_policy="fallback", cropper=cropper)

        assert ocr_calls >= 2
        assert len(srv.requests) == ocr_calls
        ocr_objs = [m for m in math_objs if m.source_channel == SourceChannel.OCR]
        assert len(ocr_objs) == ocr_calls
        for m in ocr_objs:
            assert m.needs_ocr is True
            assert m.latex is not None and r"\text{CER}" in m.latex
            assert m.raw_text  # original PyMuPDF raw_text preserved
