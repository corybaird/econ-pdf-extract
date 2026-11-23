from __future__ import annotations

import difflib
import re
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import Claim, ProvenanceRef

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "with",
        "this",
        "from",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "been",
        "also",
        "our",
        "their",
        "these",
        "those",
        "into",
        "over",
        "than",
        "then",
        "when",
        "where",
        "while",
        "which",
        "overall",
        "moreover",
        "furthermore",
        "however",
        "therefore",
        "paper",
        "study",
        "results",
        "findings",
        "show",
        "shows",
        "find",
        "finds",
        "demonstrate",
        "demonstrates",
    }
)
_WORD_RE = re.compile(r"[a-z0-9_]{3,}")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _content_tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


def _numbers(text: str) -> set[str]:
    return set(_NUM_RE.findall(text))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


class ClaimDeduplicator:
    """Clusters near-duplicate paraphrase claims across sections while retaining also_seen_on provenance."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config if config is not None else ConfigLoader().load("extraction.yaml").get("claims", {}).get("dedup", {})
        self._jaccard_thresh = float(cfg.get("token_jaccard_threshold", 0.55))
        self._number_thresh = float(cfg.get("number_overlap_threshold", 0.50))
        self._seq_thresh = float(cfg.get("sequence_ratio_threshold", 0.72))
        priority = cfg.get("canonical_role_priority", ["results", "abstract", "conclusion", "introduction", "robustness", "other"])
        self._role_rank = {role: idx for idx, role in enumerate(priority)}

    def deduplicate(self, claims: list[Claim]) -> list[Claim]:
        if len(claims) < 2:
            return claims

        n = len(claims)
        tokens = [_content_tokens(c.quote) for c in claims]
        nums = [_numbers(c.quote) for c in claims]
        norms = [_norm_text(c.quote) for c in claims]

        # Build adjacency via Union-Find
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        for i in range(n):
            for j in range(i + 1, n):
                if self._is_near_duplicate(norms[i], norms[j], tokens[i], tokens[j], nums[i], nums[j]):
                    union(i, j)

        clusters: dict[int, list[int]] = {}
        for idx in range(n):
            clusters.setdefault(find(idx), []).append(idx)

        for members in clusters.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda idx: self._canonical_sort_key(claims[idx], nums[idx]))
            canonical = claims[members[0]]
            seen_refs = {(r.page, r.section) for r in canonical.also_seen_on}
            for dup_idx in members[1:]:
                dup = claims[dup_idx]
                dup.duplicate_of = canonical.claim_id
                ref_key = (dup.page, dup.section)
                if ref_key not in seen_refs:
                    seen_refs.add(ref_key)
                    canonical.also_seen_on.append(ProvenanceRef(page=dup.page, section=dup.section, bbox=dup.bbox))

        return claims

    def _is_near_duplicate(self, norm_a: str, norm_b: str, tok_a: set[str], tok_b: set[str], num_a: set[str], num_b: set[str]) -> bool:
        if difflib.SequenceMatcher(None, norm_a, norm_b).ratio() >= self._seq_thresh:
            return True
        tok_j = _jaccard(tok_a, tok_b)
        if tok_j < self._jaccard_thresh:
            return False
        if not num_a and not num_b:
            return True
        return _jaccard(num_a, num_b) >= self._number_thresh

    def _canonical_sort_key(self, claim: Claim, nums: set[str]) -> tuple[int, int, int, int]:
        rank = self._role_rank.get(claim.section_role.value, len(self._role_rank))
        return (rank, -len(nums), -len(claim.quote), claim.page)
