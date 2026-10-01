from __future__ import annotations

import re

from .canonical import CanonicalIndex
from .models import Mention, Resolution
from .normalization import (
    canonical_case_class,
    canonical_law_source,
    canonical_tribunal,
    extract_article,
    extract_number_keys,
    fold_text,
)


SUMULA_RE = re.compile(
    r"(?:sumula|sumuia|5umula|s.m[.]?)\s*(vinculante\s*)?(?:n(?:umero)?[. o]*)?([0-9]{1,4})",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def _is_structured_incomplete(text: str) -> bool:
    folded = fold_text(text)
    relator_match = re.search(r"\b(?:rel|relator|relatora|relatoria)\b", folded)
    if relator_match is None:
        return False
    # OCR-aware numeric extraction can turn a surname such as "Lóssio" into
    # digits.  Only identifiers before the relator field can make this form a
    # complete citation; the name itself must never become a process number.
    searchable_prefix = folded[: relator_match.start()]
    substantial_numbers = []
    for key, _, _ in extract_number_keys(searchable_prefix):
        digits = key.split(":", 1)[1]
        if not YEAR_RE.match(digits):
            substantial_numbers.append(key)
    return not substantial_numbers


def _sumula_fields(text: str) -> tuple[str | None, str | None, bool]:
    folded = fold_text(text)
    match = SUMULA_RE.search(folded)
    if not match:
        return None, None, False
    vinculante = bool(match.group(1))
    tribunal = canonical_tribunal(text)
    if vinculante and tribunal is None:
        tribunal = "STF"
    return tribunal, str(int(match.group(2))), vinculante


class CitationResolver:
    def __init__(self, canonical_index: CanonicalIndex) -> None:
        self.index = canonical_index

    def resolve(self, mention: Mention) -> Resolution:
        if mention.citation_type == "lei":
            return self._resolve_law(mention.text)
        return self._resolve_jurisprudence(mention.text)

    def _resolve_law(self, text: str) -> Resolution:
        source = canonical_law_source(text)
        article = extract_article(text)
        if not source or not article:
            return Resolution(
                classification="incompleta",
                query_complete=False,
                reason="lei sem artigo ou diploma identificavel",
                match_kind="law-incomplete",
            )
        canonical_id = self.index.lookup_law(source, article)
        if canonical_id:
            return Resolution(
                classification="real",
                canonical_id=canonical_id,
                query_complete=True,
                reason=f"dispositivo exato {source}:{article}",
                match_kind="law-exact",
            )
        return Resolution(
            classification="inventada",
            query_complete=True,
            reason=f"dispositivo ausente {source}:{article}",
            match_kind="law-absent",
        )

    def _resolve_jurisprudence(self, text: str) -> Resolution:
        tribunal, number, vinculante = _sumula_fields(text)
        if number is not None:
            if tribunal is None:
                return Resolution(
                    classification="incompleta",
                    query_complete=False,
                    reason="sumula sem tribunal",
                    match_kind="sumula-incomplete",
                )
            canonical_id = self.index.lookup_sumula(tribunal, number, vinculante)
            if canonical_id:
                return Resolution(
                    classification="real",
                    canonical_id=canonical_id,
                    query_complete=True,
                    reason=f"sumula exata {tribunal}:{number}:{int(vinculante)}",
                    match_kind="sumula-exact",
                )
            return Resolution(
                classification="inventada",
                query_complete=True,
                reason=f"sumula ausente {tribunal}:{number}:{int(vinculante)}",
                match_kind="sumula-absent",
            )

        if _is_structured_incomplete(text):
            return Resolution(
                classification="incompleta",
                query_complete=False,
                reason="referencia por tribunal/ano/relatoria sem numero",
                match_kind="case-incomplete",
            )

        tribunal = canonical_tribunal(text)
        candidates, correction_cost = self.index.lookup_case(text, tribunal=tribunal)
        number_keys = [key for key, _, _ in extract_number_keys(text)]
        significant_keys = [
            key
            for key in number_keys
            if key.startswith("cnj:") or not YEAR_RE.match(key.split(":", 1)[1])
        ]
        query_complete = bool(significant_keys)
        if not query_complete:
            return Resolution(
                classification="incompleta",
                candidates=candidates[:5],
                query_complete=False,
                reason="referencia jurisprudencial sem identificador suficiente",
                match_kind="case-incomplete",
                normalization_cost=correction_cost,
            )

        if not candidates:
            return Resolution(
                classification="inventada",
                query_complete=True,
                reason="identificador completo ausente do indice canonico",
                match_kind="case-absent",
                normalization_cost=correction_cost,
            )

        top = candidates[0]
        margin = top.identity_score - candidates[1].identity_score if len(candidates) > 1 else 99.0
        strong = top.identity_score >= 8.0 and (margin >= 1.25 or top.identity_score >= 12.0)
        if strong:
            return Resolution(
                classification="real",
                canonical_id=top.canonical_id,
                candidates=candidates[:5],
                query_complete=True,
                reason=f"candidato canonico unico; score={top.identity_score:.2f}; margem={margin:.2f}",
                match_kind="case-index",
                normalization_cost=correction_cost,
            )

        return Resolution(
            classification="inventada",
            candidates=candidates[:5],
            query_complete=True,
            reason=f"candidato fraco/nao-identitario; score={top.identity_score:.2f}; margem={margin:.2f}",
            match_kind="case-weak",
            normalization_cost=correction_cost,
        )
