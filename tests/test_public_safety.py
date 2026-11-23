from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".txt", ".toml", ".json", ".cfg", ".ini", ".sh"}

FORBIDDEN_LITERALS = (
    "/workspace" + "/",
    "/Users" + "/",
)


def _private_names() -> list[str]:
    # One name per line, kept outside the repo so the list itself is never published
    path = os.environ.get("ECON_PDF_PRIVATE_NAMES")
    if not path:
        return []
    return [line.strip().lower() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _tracked_files() -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    entries = [p for p in proc.stdout.decode("utf-8").split("\x00") if p]
    return [ROOT / rel for rel in entries]


def test_tracked_files_contain_no_sensitive_paths_or_private_names():
    private_names = _private_names()
    violations: list[str] = []
    for path in _tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        rel_lower = rel.lower()
        for name in private_names:
            if name in rel_lower:
                violations.append(f"forbidden filename {rel!r} contains {name!r}")
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".gitignore":
            continue
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for literal in FORBIDDEN_LITERALS:
            if literal in content:
                violations.append(f"{rel}: contains forbidden literal {literal!r}")
        content_lower = content.lower()
        for name in private_names:
            if name in content_lower:
                violations.append(f"{rel}: contains forbidden private name {name!r}")
    assert not violations, "Public-safety violations:\n" + "\n".join(violations)
