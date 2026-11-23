from __future__ import annotations

import importlib
import logging
from typing import Any, ClassVar

from econ_pdf_extract.core.config import ConfigLoader

logger = logging.getLogger(__name__)

DEFAULT_SPACY_MODEL = "en_core_web_sm"


class SpacyUnavailableError(RuntimeError):
    """Raised when spaCy or the configured language model is not installed."""


class SpacyModelLoader:
    """Lazy loader and process cache for optional spaCy language models."""

    _cache: ClassVar[dict[tuple[str, tuple[str, ...]], Any]] = {}

    def __init__(self, model_name: str | None = None, config: dict[str, Any] | None = None):
        cfg = config if config is not None else ConfigLoader().load("extraction.yaml").get("nlp", {})
        self._model_name = model_name or str(cfg.get("spacy_model", DEFAULT_SPACY_MODEL))

    @property
    def model_name(self) -> str:
        return self._model_name

    @staticmethod
    def is_spacy_available() -> bool:
        try:
            importlib.import_module("spacy")
        except ImportError:
            return False
        return True

    def is_model_available(self, model_name: str | None = None) -> bool:
        target = model_name or self._model_name
        try:
            spacy = importlib.import_module("spacy")
        except ImportError:
            return False
        return bool(spacy.util.is_package(target))

    def load(self, model_name: str | None = None, disable: list[str] | tuple[str, ...] | None = None) -> Any:
        target = model_name or self._model_name
        disabled = tuple(sorted(disable)) if disable else ()
        cache_key = (target, disabled)
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            spacy = importlib.import_module("spacy")
        except ImportError as exc:
            raise SpacyUnavailableError(
                'spaCy is not installed. Install the optional NLP extra with: uv sync --extra nlp (or pip install "econ-pdf-extract[nlp]")'
            ) from exc

        try:
            nlp = spacy.load(target, disable=list(disabled))
        except OSError as exc:
            raise SpacyUnavailableError(
                f"spaCy model '{target}' is not installed. Install it with: python -m spacy download {target}"
            ) from exc

        logger.info("Loaded spaCy model %s (disabled=%s)", target, list(disabled))
        self._cache[cache_key] = nlp
        return nlp

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()
