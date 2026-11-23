# OCR

Pluggable, targeted OCR for degraded display equations. Source: `src/econ_pdf_extract/ocr/`. Defaults live in `extraction.yaml` under `ocr:`.

## OcrBackend interface

`ocr/base.py`:

```python
class OcrBackend(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    def is_available(self) -> bool: ...
    @abstractmethod
    def transcribe(self, image_bytes: bytes, mode: OcrMode = "formula",
                   region: BBox | None = None) -> OcrResult | None: ...
```

- `OcrMode` = `formula` | `page` | `table` (`OcrPolicy` = `none` | `fallback` | `all_displays`)
- `OcrResult` carries `markdown`, `latex` (formula mode only), `kind`, `bbox`, `backend`, `model`, `elapsed_ms`
- Errors: `OcrError`, `OcrBackendUnavailableError` (endpoint unset or unreachable)

## Backends

| Backend | `--ocr` value | Behaviour |
|---|---|---|
| `NullOcrBackend` | `none` (default) | No-op; pure PyMuPDF text extraction, `transcribe()` returns `None` |
| `GlmOcrBackend` | `glm_ocr` | stdlib-only OpenAI-compatible HTTP client for a remote vLLM GLM-OCR server (`zai-org/GLM-OCR`) |

`OcrBackendFactory.create(name, config)` resolves backend names to instances; unknown names raise `ValueError`.

### GLM-OCR server

The backend reads, in order: constructor args, `extraction.yaml` → `ocr.base_url`/`ocr.api_key`, then environment variables:

- `VLLM_BASE_URL` — OpenAI-compatible base URL (e.g. `http://host:8000` or `.../v1`); required, raises `OcrBackendUnavailableError` when unset
- `VLLM_API_KEY` — optional Bearer token

Request: base64 PNG in an `image_url` message + a text prompt. Prompts (`ocr/glm_ocr.py` → `_PROMPTS`): `formula` → `Formula Recognition:`, `page` → `Text Recognition:`, `table` → `Table Recognition:`. Model, timeout (`timeout_seconds`), and crop parameters are configured in `extraction.yaml` (`glm_model`, `timeout_seconds`, `crop_dpi`, `pad_x_pt`, `pad_y_pt`, `tag_gap_pt`). `strip_latex_delimiters()` removes Markdown fences and LaTeX delimiters, and `is_available()` probes `GET /v1/models` with a short timeout.

## Region cropping and targeted policy

`RegionCropper` renders the equation bbox to PNG (padded by `pad_x_pt`/`pad_y_pt`, right-margin tag excluded by `tag_gap_pt`, `crop_dpi`). `MathExtractor._run_targeted_ocr` only OCRs display-equation kinds, gated by `--ocr-policy`:

| Policy | What gets OCR'd |
|---|---|
| `none` | Nothing (extraction stays text-only) |
| `fallback` (default) | Only displays with `needs_ocr=True` |
| `all_displays` | Every tagged/unnumbered display |

Successful calls set `MathObject.latex` and `source_channel = ocr`; `ocr_calls` is reported in `diagnostics`.

## How to add a backend

1. Subclass `OcrBackend` in a new module under `src/econ_pdf_extract/ocr/`.
2. Implement `name`, `is_available()`, and `transcribe()` returning `OcrResult` (or `None`).
3. Register it in `OcrBackendFactory.create` and add its name to `SUPPORTED_OCR_BACKENDS`.
4. Add tests against a mock server following the existing pattern in `tests/test_ocr_backends.py`.

## CI status

The GPU/vLLM path is **untested in CI**; `tests/test_ocr_backends.py` exercises the backend against a stdlib mock server only. No real GLM-OCR endpoint is contacted during tests.
