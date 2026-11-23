from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import Attribution, Claim, PaperMetadata, Statistic
from econ_pdf_extract.targets.statistics import clause


def escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


class TargetDrafter:
    """Links canonical claims and statistics into MaRCo@BIS-style timestamped draft target YAML."""

    def __init__(self, paper: PaperMetadata | Any, claims: list[Claim | Any], statistics: list[Statistic], units: dict[str, str] | None = None, include_literature: bool = False, include_duplicates: bool = False):
        self._paper = paper
        self._claims = claims
        self._statistics = statistics
        self._units = units if units is not None else ConfigLoader().load("target_patterns.yaml")["units"]
        self._include_literature = include_literature
        self._include_duplicates = include_duplicates

    @property
    def _paper_id(self) -> str:
        return getattr(self._paper, "paper_id", None) or getattr(self._paper, "id", "paper")

    def _eligible_claims(self) -> list[Any]:
        out: list[Any] = []
        for claim in self._claims:
            if not self._include_duplicates and getattr(claim, "duplicate_of", None) is not None:
                continue
            attr = getattr(claim, "attribution", None)
            if not self._include_literature and attr == Attribution.LITERATURE:
                continue
            out.append(claim)
        return out

    @staticmethod
    def _claim_text(claim: Any) -> str:
        return getattr(claim, "quote", None) or getattr(claim, "claim_text", "")

    @staticmethod
    def _claim_section(claim: Any) -> str:
        return getattr(claim, "section", None) or getattr(claim, "section_heading", "")

    def targets(self) -> list[dict[str, Any]]:
        drafts: list[dict[str, Any]] = []
        seen: set[tuple[str, str, float]] = set()
        linked: set[tuple[str, float, int, str]] = set()

        for claim in self._eligible_claims():
            c_text = self._claim_text(claim)
            c_sec = self._claim_section(claim)
            for stat in self._statistics:
                if stat.text.lower() not in c_text.lower() or (claim.claim_id, stat.kind, stat.value) in seen:
                    continue
                seen.add((claim.claim_id, stat.kind, stat.value))
                linked.add((stat.kind, stat.value, stat.page, stat.context))
                drafts.append(
                    {
                        "description": clause(c_text),
                        "location": f"Section '{c_sec}', page {claim.page}",
                        "paper_value": stat.value,
                        "paper_units": self._units.get(stat.kind, "unspecified"),
                        "source": "claim",
                        "our_key": None,
                        "tolerance": None,
                        "tolerance_kind": None,
                    }
                )

        for stat in self._statistics:
            if (stat.kind, stat.value, stat.page, stat.context) in linked:
                continue
            drafts.append(
                {
                    "description": clause(stat.context, 160),
                    "location": f"Section '{stat.section}', page {stat.page}",
                    "paper_value": stat.value,
                    "paper_units": self._units.get(stat.kind, "unspecified"),
                    "source": "section",
                    "our_key": None,
                    "tolerance": None,
                    "tolerance_kind": None,
                }
            )
        return drafts

    def run(self, reports_dir: Path = Path("reports/tables")) -> Path:
        reports_dir = Path(reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        dest = reports_dir / f"draft_paper_targets_{self._paper_id}_{ts}.yaml"
        dest.write_text(self.to_yaml(), encoding="utf-8")
        return dest

    def to_yaml(self) -> str:
        lines = [
            f"# Draft paper targets for {self._paper_id} - auto-drafted from the PDF by econ-pdf-extract, not validated.",
            "# TODO: fill in our_key / tolerance / tolerance_kind during replication; never invent them from the PDF.",
            "targets:",
        ]
        entries = self.targets()
        if not entries:
            return "\n".join(lines[:-1]) + "\ntargets: []\n"
        for t in entries:
            lines.append(f' - description: "{escape(t["description"])}"')
            lines.append(f'   location: "{escape(t["location"])}"')
            lines.append(f'   source: "{t["source"]}"')
            lines.append(f'   paper_value: {t["paper_value"]}')
            lines.append(f'   paper_units: "{t["paper_units"]}"')
            lines.append("   our_key: null # TODO")
            lines.append("   tolerance: null # TODO")
            lines.append("   tolerance_kind: null # TODO")
        return "\n".join(lines) + "\n"
