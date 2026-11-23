from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from econ_pdf_extract.core import load_dictionary

ROOT = Path(__file__).resolve().parents[1]


def test_wheel_ships_exactly_the_tracked_references():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    included = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    proc = subprocess.run(["git", "ls-files", "references/configs", "references/dictionaries"], cwd=ROOT, check=True, capture_output=True, text=True)
    assert set(included) == set(proc.stdout.split())
    assert "references/configs/papers.yaml" not in included
    assert all(dest == f"econ_pdf_extract/_{src}" for src, dest in included.items())


def test_load_dictionary_rejects_unknown_name():
    assert load_dictionary("greek_to_latex").GREEK_TO_LATEX
    with pytest.raises(FileNotFoundError):
        load_dictionary("missing")
