from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from fixtures.synthetic_paper import build_synthetic_paper


@pytest.fixture(scope="session")
def synthetic_paper_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("synthetic_paper")
    return build_synthetic_paper(out_dir / "synthetic_paper.pdf")
