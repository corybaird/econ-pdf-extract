from __future__ import annotations

import importlib.util
from functools import cache
from pathlib import Path
from types import ModuleType

_CHECKOUT_ROOT = Path(__file__).resolve().parents[3]
_IS_CHECKOUT = (_CHECKOUT_ROOT / "pyproject.toml").is_file() and (_CHECKOUT_ROOT / "references" / "configs").is_dir()

# Installed wheels carry the references inside the package, see force-include in pyproject.toml
PROJECT_ROOT = _CHECKOUT_ROOT if _IS_CHECKOUT else Path.cwd()
REFERENCES_DIR = _CHECKOUT_ROOT / "references" if _IS_CHECKOUT else Path(__file__).resolve().parents[1] / "_references"
CONFIGS_DIR = REFERENCES_DIR / "configs"
DICTIONARIES_DIR = REFERENCES_DIR / "dictionaries"


@cache
def load_dictionary(name: str) -> ModuleType:
    """Load a lookup-table module from the dictionaries folder by file path."""
    path = DICTIONARIES_DIR / f"{name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"Dictionary not found: {path}")
    spec = importlib.util.spec_from_file_location(f"econ_pdf_extract._dictionary_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
