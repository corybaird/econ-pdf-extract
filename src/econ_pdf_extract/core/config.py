from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from econ_pdf_extract.core.models import PaperMetadata
from econ_pdf_extract.core.paths import CONFIGS_DIR, PROJECT_ROOT


class ConfigLoader:
    """Loads and validates YAML configuration files."""

    def __init__(self, config_dir: Path | None = None):
        self._config_dir = Path(config_dir) if config_dir is not None else CONFIGS_DIR

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    def load(self, filename: str, required_keys: tuple[str, ...] | None = None) -> dict[str, Any]:
        return self.load_path(self._config_dir / filename, required_keys=required_keys)

    def load_path(self, path: Path, required_keys: tuple[str, ...] | None = None) -> dict[str, Any]:
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(f"Config file not found: {target}")
        with target.open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
        if not isinstance(data, dict):
            raise TypeError(f"Expected YAML mapping in {target}, got {type(data).__name__}")
        if required_keys:
            missing = [k for k in required_keys if k not in data]
            if missing:
                raise ValueError(f"Missing required keys {missing} in {target}")
        return data

    def load_papers(self, config_path: Path | None = None) -> list[PaperMetadata]:
        target = Path(config_path) if config_path is not None else self._config_dir / "papers.yaml"
        if not target.exists():
            example = self._config_dir / "papers.example.yaml"
            raise FileNotFoundError(
                f"Paper registry not found at {target}. Copy {example} to {target} or pass --config."
            )
        cfg = self.load_path(target, required_keys=("papers",))
        specs = cfg["papers"]
        if not isinstance(specs, list):
            raise TypeError(f"Expected 'papers' to be a list in {target}")
        return [PaperMetadata.from_spec(spec, root=PROJECT_ROOT) for spec in specs]
