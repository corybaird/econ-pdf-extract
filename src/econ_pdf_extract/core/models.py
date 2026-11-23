from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

BBox = tuple[float, float, float, float]


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _serialize(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple):
        return [_serialize(v) for v in value]
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    return value


class _SerializableMixin:
    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


class SourceChannel(str, Enum):
    TEXT = "text"
    OCR = "ocr"


class BlockKind(str, Enum):
    PROSE = "prose"
    HEADING = "heading"
    DISPLAY_MATH = "display_math"
    FOOTNOTE = "footnote"
    TABLE = "table"
    CAPTION = "caption"
    MARGIN_NOISE = "margin_noise"
    HEADER_FOOTER = "header_footer"


class SectionRole(str, Enum):
    FRONT_MATTER = "front_matter"
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    METHODOLOGY = "methodology"
    DATA = "data"
    RESULTS = "results"
    ROBUSTNESS = "robustness"
    CONCLUSION = "conclusion"
    APPENDIX = "appendix"
    REFERENCES = "references"
    OTHER = "other"


class ClaimType(str, Enum):
    FORECAST_ACCURACY = "forecast_accuracy"
    MAGNITUDE = "magnitude"
    SIGNIFICANCE = "significance"
    ROBUSTNESS = "robustness"
    MECHANISM = "mechanism"
    PROPOSAL = "proposal"
    NEGATIVE_RESULT = "negative_result"
    ECONOMIC_VALUE = "economic_value"
    GENERAL = "general"


class Attribution(str, Enum):
    OWN = "own"
    LITERATURE = "literature"
    COMPARISON = "comparison"
    UNCLEAR = "unclear"


class MathKind(str, Enum):
    DISPLAY_EQUATION = "display_equation"
    MODEL_SPECIFICATION = "model_specification"
    ESTIMATION_PROBLEM = "estimation_problem"
    EVALUATION_FORMULA = "evaluation_formula"
    ASSUMPTION = "assumption"
    ALGORITHM = "algorithm"
    PROPOSITION = "proposition"
    DEFINITION = "definition"


@dataclass
class Span(_SerializableMixin):
    text: str
    bbox: BBox
    font: str
    size: float
    flags: int
    is_bold: bool
    is_italic: bool
    is_math_font: bool
    is_big_op_font: bool


@dataclass
class Line(_SerializableMixin):
    text: str
    bbox: BBox
    page: int
    spans: list[Span] = field(default_factory=list)
    has_math_font: bool = False
    has_big_op_font: bool = False
    modal_size: float = 0.0

    @property
    def left(self) -> float:
        return self.bbox[0]

    @property
    def top(self) -> float:
        return self.bbox[1]

    @property
    def right(self) -> float:
        return self.bbox[2]

    @property
    def bottom(self) -> float:
        return self.bbox[3]


@dataclass
class Block(_SerializableMixin):
    block_id: str
    page: int
    bbox: BBox
    lines: list[Line] = field(default_factory=list)
    kind: BlockKind = BlockKind.PROSE
    is_bold: bool = False
    max_size: float = 0.0
    modal_size: float = 0.0
    text: str = ""


@dataclass
class Page(_SerializableMixin):
    page: int
    width: float
    height: float
    body_font_size: float
    printed_page: int | None = None
    blocks: list[Block] = field(default_factory=list)
    horizontal_rules: list[BBox] = field(default_factory=list)
    vertical_rules: list[BBox] = field(default_factory=list)
    table_bboxes: list[BBox] = field(default_factory=list)
    filled_rects: list[BBox] = field(default_factory=list)
    image_count: int = 0
    char_count: int = 0


@dataclass
class Section(_SerializableMixin):
    section_id: str
    heading: str
    role: SectionRole
    page_start: int
    page_end: int
    blocks: list[Block] = field(default_factory=list)
    is_duplicate_front_matter: bool = False


@dataclass
class Sentence(_SerializableMixin):
    sentence_id: str
    text: str
    page: int
    page_end: int
    bbox: BBox
    section_id: str
    section_heading: str
    section_role: SectionRole
    block_ids: list[str] = field(default_factory=list)
    math_tokens: list[str] = field(default_factory=list)


@dataclass
class Document(_SerializableMixin):
    paper_id: str
    source_path: Path
    page_count: int
    body_font_size: float
    pages: list[Page] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    sentences: list[Sentence] = field(default_factory=list)
    duplicate_front_matter_pages: list[int] = field(default_factory=list)


@dataclass
class ProvenanceRef(_SerializableMixin):
    page: int
    section: str
    bbox: BBox


@dataclass
class Claim(_SerializableMixin):
    claim_id: str
    paper_id: str
    claim_types: list[ClaimType]
    attribution: Attribution
    page: int
    page_end: int
    section: str
    section_role: SectionRole
    bbox: BBox
    quote: str
    source_channel: SourceChannel = SourceChannel.TEXT
    printed_page: int | None = None
    linked_equation_ids: list[str] = field(default_factory=list)
    linked_symbols: list[str] = field(default_factory=list)
    duplicate_of: str | None = None
    also_seen_on: list[ProvenanceRef] = field(default_factory=list)
    matched_cues: list[str] = field(default_factory=list)
    math_tokens: list[str] = field(default_factory=list)


@dataclass
class SymbolDef(_SerializableMixin):
    symbol_id: str
    symbol: str
    normalized: str
    description: str
    equation_id: str | None
    page: int
    section: str
    bbox: BBox
    source_channel: SourceChannel = SourceChannel.TEXT


@dataclass
class MathObject(_SerializableMixin):
    math_id: str
    paper_id: str
    kind: MathKind
    tag: str | None
    raw_text: str
    latex: str | None
    page: int
    page_end: int
    section: str
    bbox: BBox
    tag_bbox: BBox | None = None
    source_channel: SourceChannel = SourceChannel.TEXT
    needs_ocr: bool = False
    ocr_reasons: list[str] = field(default_factory=list)
    symbols_defined: list[SymbolDef] = field(default_factory=list)
    context_before: str = ""
    context_after: str = ""
    linked_claim_ids: list[str] = field(default_factory=list)


@dataclass
class CrossRefEdge(_SerializableMixin):
    claim_id: str
    math_id: str
    via: Literal["explicit_ref", "symbol", "named_metric"]
    matched_token: str


@dataclass
class Statistic(_SerializableMixin):
    kind: str
    text: str
    value: float
    page: int
    section: str
    bbox: BBox
    context: str


@dataclass
class CausalTriple(_SerializableMixin):
    triple_id: str
    paper_id: str
    cause: str
    direction: str
    outcome: str
    sentence: str
    page: int
    section: str
    verb: str = ""
    page_end: int = 0
    section_role: SectionRole = SectionRole.OTHER
    bbox: BBox = (0.0, 0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        if self.page_end == 0:
            self.page_end = self.page


@dataclass
class PaperMetadata(_SerializableMixin):
    paper_id: str
    source_path: str
    authors: str = ""
    title: str = ""
    journal: str = ""

    @property
    def pdf_path(self) -> Path:
        return Path(self.source_path)

    @classmethod
    def from_spec(cls, spec: dict[str, Any], root: Path | None = None) -> PaperMetadata:
        raw_path = spec.get("draft_pdf") or spec.get("pdf_path") or spec.get("source_path")
        if not raw_path:
            raise ValueError(f"Paper spec {spec.get('id')!r} missing 'draft_pdf' or 'pdf_path'")
        resolved = Path(raw_path)
        if not resolved.is_absolute() and root is not None:
            resolved = root / resolved
        return cls(
            paper_id=str(spec["id"]),
            source_path=str(resolved),
            authors=str(spec.get("authors", "")),
            title=str(spec.get("title", "")),
            journal=str(spec.get("journal", "")),
        )


@dataclass
class ExtractionResult(_SerializableMixin):
    paper: PaperMetadata
    page_count: int
    ocr_backend: str
    ocr_policy: str
    extracted_at: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    math_objects: list[MathObject] = field(default_factory=list)
    symbols: list[SymbolDef] = field(default_factory=list)
    links: list[CrossRefEdge] = field(default_factory=list)
    statistics: list[Statistic] = field(default_factory=list)
    causal_triples: list[CausalTriple] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
