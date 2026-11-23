from __future__ import annotations

from abc import ABC, abstractmethod

from econ_pdf_extract.core.models import Claim, Document


class ClaimRefiner(ABC):
    """Optional post-extraction hook for refining extracted claims."""

    @abstractmethod
    def refine(self, claims: list[Claim], document: Document) -> list[Claim]: ...


class NullClaimRefiner(ClaimRefiner):
    """Default no-op refiner that preserves deterministic extraction output unchanged."""

    def refine(self, claims: list[Claim], document: Document) -> list[Claim]:
        return claims
