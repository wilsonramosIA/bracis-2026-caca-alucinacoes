from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


CitationType = Literal["jurisprudencia", "lei"]
Classification = Literal["real", "inventada", "incompleta"]


@dataclass(frozen=True)
class Mention:
    start: int
    end: int
    text: str
    citation_type: CitationType
    source: str = "regex"
    detector_score: float = 1.0

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class CanonicalCandidate:
    canonical_id: str
    document_id: str
    tribunal: str | None
    nature: str
    key: str
    identity_score: float
    first_position: int
    occurrences: int


@dataclass
class Resolution:
    classification: Classification
    canonical_id: str | None = None
    confidence: float | None = None
    candidates: list[CanonicalCandidate] = field(default_factory=list)
    query_complete: bool = False
    reason: str = ""
    match_kind: str = "none"
    normalization_cost: float = 0.0


@dataclass
class Prediction:
    mention: Mention
    resolution: Resolution
    citation_id: str = ""

    def to_contract(self) -> dict:
        resolution = None
        if self.resolution.classification == "real":
            resolution = {
                "fonte": "jusbrasil",
                "id_canonico": str(self.resolution.canonical_id),
            }
        item = {
            "id": self.citation_id,
            "inicio": self.mention.start,
            "fim": self.mention.end,
            "trecho": self.mention.text,
            "tipo": self.mention.citation_type,
            "classificacao": self.resolution.classification,
            "resolucao": resolution,
        }
        if self.resolution.confidence is not None:
            item["confianca"] = round(float(self.resolution.confidence), 4)
        return item

    def debug_dict(self) -> dict:
        return {
            "prediction": self.to_contract(),
            "reason": self.resolution.reason,
            "match_kind": self.resolution.match_kind,
            "query_complete": self.resolution.query_complete,
            "normalization_cost": self.resolution.normalization_cost,
            "candidates": [asdict(candidate) for candidate in self.resolution.candidates],
        }

