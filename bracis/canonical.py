from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import CanonicalCandidate
from .normalization import (
    canonical_law_source,
    canonical_tribunal,
    extract_article,
    extract_number_keys,
    fold_text,
)


@dataclass(frozen=True)
class CanonicalDocument:
    canonical_id: str
    document_id: str
    tribunal: str | None
    year: int | None
    relator: str | None
    nature: str
    text_length: int


class CanonicalIndex:
    """Closed-world identifier index built from the supplied SQLite snapshot."""

    def __init__(self) -> None:
        self.documents: dict[str, CanonicalDocument] = {}
        self.aliases: dict[str, list[CanonicalCandidate]] = defaultdict(list)
        self.laws: dict[tuple[str, str], str] = {}
        self.sumulas: dict[tuple[str, str, bool], str] = {}

    @classmethod
    def from_sqlite(cls, database: str | Path) -> "CanonicalIndex":
        instance = cls()
        uri = f"file:{Path(database).resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = connection.execute(
                """
                SELECT documento_id, id, tribunal, ano, relator, natureza, texto, texto_len
                FROM documentos
                ORDER BY documento_id
                """
            )
            for document_id, canonical_id, tribunal, year, relator, nature, text, text_length in rows:
                canonical_id = str(canonical_id)
                doc = CanonicalDocument(
                    canonical_id=canonical_id,
                    document_id=str(document_id),
                    tribunal=tribunal,
                    year=year,
                    relator=relator,
                    nature=nature,
                    text_length=text_length,
                )
                instance.documents[canonical_id] = doc
                if nature == "dispositivo":
                    instance._index_law(doc, text)
                elif nature == "sumula":
                    instance._index_sumula(doc, text)
                else:
                    instance._index_case(doc, text)
        finally:
            connection.close()
        instance._finalize()
        return instance

    def _index_law(self, document: CanonicalDocument, text: str) -> None:
        source = canonical_law_source(text[:220])
        article = extract_article(text[:120])
        if source and article:
            self.laws[(source, article)] = document.canonical_id

    def _index_sumula(self, document: CanonicalDocument, text: str) -> None:
        folded = fold_text(text[:160])
        match = re.search(r"sumula(?: vinculante)?\s*(?:n[. o]*)?([0-9]{1,4})", folded)
        if not match or not document.tribunal:
            return
        number = str(int(match.group(1)))
        vinculante = "vinculante" in folded
        self.sumulas[(document.tribunal, number, vinculante)] = document.canonical_id
        # "Súmula Vinculante" is unambiguously an STF record even when STF is omitted.
        if vinculante:
            self.sumulas[("STF", number, True)] = document.canonical_id

    def _index_case(self, document: CanonicalDocument, text: str) -> None:
        occurrences: dict[str, list[int]] = defaultdict(list)
        for key, position, _ in extract_number_keys(text):
            occurrences[key].append(position)

        for key, positions in occurrences.items():
            first = min(positions)
            count = len(positions)
            identity_positions = [
                position
                for position in positions
                if re.search(
                    r"\b(?:estes autos de|processo em epigrafe|autos do processo em epigrafe)\b",
                    fold_text(text[max(0, position - 180) : position]),
                )
            ]
            # Mentions deep in the body that occur once usually describe a
            # different case. Some TST documents put their own docket after a
            # long ementa; an explicit identity phrase safely rescues those.
            if first >= 2500 and count < 2 and not identity_positions:
                continue
            header_bonus = 12.0 if first < 350 else 8.0 if first < 1000 else 4.0 if first < 2500 else 0.0
            repeat_bonus = min(8.0, 1.75 * math.log2(count + 1))
            cnj_bonus = 1.5 if key.startswith("cnj:") else 0.0
            identity_bonus = 8.0 if identity_positions else 0.0
            candidate = CanonicalCandidate(
                canonical_id=document.canonical_id,
                document_id=document.document_id,
                tribunal=document.tribunal,
                nature=document.nature,
                key=key,
                identity_score=round(
                    header_bonus + repeat_bonus + cnj_bonus + identity_bonus, 6
                ),
                first_position=first,
                occurrences=count,
            )
            self.aliases[key].append(candidate)

    def _finalize(self) -> None:
        for key, candidates in self.aliases.items():
            self.aliases[key] = sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.identity_score,
                    candidate.first_position,
                    candidate.canonical_id,
                ),
            )

    def lookup_case(self, text: str, tribunal: str | None = None) -> tuple[list[CanonicalCandidate], float]:
        by_id: dict[str, CanonicalCandidate] = {}
        minimum_cost = 0.0
        keys = extract_number_keys(text)
        if keys:
            minimum_cost = min(cost for _, _, cost in keys)
        for key, _, correction_cost in keys:
            for candidate in self.aliases.get(key, []):
                tribunal_bonus = 2.0 if tribunal and candidate.tribunal == tribunal else 0.0
                mismatch_penalty = 3.0 if tribunal and candidate.tribunal and candidate.tribunal != tribunal else 0.0
                adjusted = CanonicalCandidate(
                    canonical_id=candidate.canonical_id,
                    document_id=candidate.document_id,
                    tribunal=candidate.tribunal,
                    nature=candidate.nature,
                    key=candidate.key,
                    identity_score=candidate.identity_score + tribunal_bonus - mismatch_penalty - 0.35 * correction_cost,
                    first_position=candidate.first_position,
                    occurrences=candidate.occurrences,
                )
                current = by_id.get(adjusted.canonical_id)
                if current is None or adjusted.identity_score > current.identity_score:
                    by_id[adjusted.canonical_id] = adjusted
        result = sorted(
            by_id.values(),
            key=lambda candidate: (-candidate.identity_score, candidate.first_position, candidate.canonical_id),
        )
        return result, float(minimum_cost)

    def lookup_law(self, source: str, article: str) -> str | None:
        return self.laws.get((source, str(int(article))))

    def lookup_sumula(self, tribunal: str, number: str, vinculante: bool) -> str | None:
        return self.sumulas.get((tribunal, str(int(number)), vinculante))

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "documents": {key: asdict(value) for key, value in self.documents.items()},
            "aliases": {key: [asdict(candidate) for candidate in value] for key, value in self.aliases.items()},
            "laws": {f"{source}:{article}": canonical_id for (source, article), canonical_id in self.laws.items()},
            "sumulas": {
                f"{tribunal}:{number}:{int(vinculante)}": canonical_id
                for (tribunal, number, vinculante), canonical_id in self.sumulas.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "CanonicalIndex":
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported canonical index schema")
        instance = cls()
        instance.documents = {
            key: CanonicalDocument(**value) for key, value in payload["documents"].items()
        }
        instance.aliases = defaultdict(
            list,
            {
                key: [CanonicalCandidate(**candidate) for candidate in candidates]
                for key, candidates in payload["aliases"].items()
            },
        )
        instance.laws = {
            tuple(key.split(":", 1)): value for key, value in payload.get("laws", {}).items()
        }
        instance.sumulas = {}
        for key, value in payload.get("sumulas", {}).items():
            tribunal, number, vinculante = key.split(":")
            instance.sumulas[(tribunal, number, bool(int(vinculante)))] = value
        return instance

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "CanonicalIndex":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def statistics(self) -> dict:
        collisions = Counter(len(candidates) for candidates in self.aliases.values())
        return {
            "documents": len(self.documents),
            "case_aliases": len(self.aliases),
            "laws": len(self.laws),
            "sumulas": len(set(self.sumulas.values())),
            "alias_cardinality": dict(sorted(collisions.items())),
        }
