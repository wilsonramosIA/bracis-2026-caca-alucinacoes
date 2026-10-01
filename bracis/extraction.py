from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Mention
from .normalization import NUMERICISH_RE, fold_text, numericish_to_digits


LAW_PATTERN = re.compile(
    r"\b(?:art(?:igo)?)[.\s]*\d{1,4}(?:\.\d{3})?(?:[ºo°])?"
    r"(?:\s*,\s*(?:§\s*\d+(?:[ºo°])?(?:-\s*[A-Z])?|[IVXLCDM]+|inciso\s+[IVXLCDM]+|['\"]?[a-z]['\"]?\)?))*"
    r"(?:\s*,?\s*(?:do|da|de)\s+)?"
    r"(?:Constitui(?:ç|c)[aã]o(?:\s+(?:Federal|da\s+Rep[uú]blica))?"
    r"|C[oó]dig[o0]\s+(?:de\s+)?(?:Processo\s+Civil|Processo\s+Penal|Defesa\s+do\s+Consumidor|Penal\s+Militar|Civil|Eleitoral)"
    r"|Consolida(?:ç|c)[aã]o\s+das\s+Leis\s+do\s+Trabalho"
    r"|CPC|CPP|CPM|CDC|CLT|CF(?:/88)?|CC|CE|LC\s*(?:n(?:[ºo°]|\.)?)?\s*64(?:/1990)?"
    r"|Lei(?:\s+Complementar)?\s*(?:n(?:[ºo°]|\.)?)?\s*[\d.]+(?:/\d{2,4})?)",
    re.IGNORECASE | re.DOTALL,
)

SUMULA_PATTERN = re.compile(
    r"\b(?:(?:S|5)[uú]mu[lI]a|S[uú]m\.)\s*(?:Vinculante\s*)?"
    r"(?:n(?:[ºo°]|\.)?)?\s*\d{1,4}(?:\s+(?:do|da)\s+(?:STF|STJ|TST|TSE|STM))?",
    re.IGNORECASE,
)

INCOMPLETE_PATTERN = re.compile(
    r"\b(?:julgado|precedente|ac[oó]rd[aã]o|Reclama(?:ç|c)[aã]o|Rcl|APL|"
    r"REsp|AREsp|REspe|AIRR|ARR|RR|RE|AR|RHC|RMS|HC|AI|RO|RSE|AgInt|"
    r"Habeas\s+Corpus|Agravo\s+em\s+Recurso\s+Especial|Recurso\s+em\s+Habeas\s+Corpus)\b"
    r"[^.;:]{0,120}?\b(?:relatoria|Rel\.)\s+(?:de\s+|do\s+|da\s+|Min\.\s*)?"
    r"[A-ZÀ-Ý][A-Za-zÀ-ÿ' -]{2,60}",
    re.IGNORECASE | re.DOTALL,
)

CASE_CUE_PATTERN = re.compile(
    r"\b(?:"
    r"EDcl|EDs?|AgInt|Ag\.?\s*Int\.?|AgRg|AgR|AgREsp|AREsp|A\.REsp|REsp|R\.Esp|Rec\.\s*Esp|Recurso\s+Especial|"
    r"RHC|HC|H\.C\.|Habeas\s+Corpus|Recurso\s+em\s+Habeas\s+Corpus|RMS|Recurso\s+em\s+Mandado\s+de\s+Seguran(?:ç|c)a|"
    r"Rcl|Recl\.|Reclama(?:ç|c)[aã]o|RE|Recurso\s+Extraordin[aá]rio|AI|RO|Recurso\s+Ordin[aá]rio|AR|A(?:ç|c)[aã]o\s+Rescis[oó]ria|"
    r"REspe|RESPE|AGR-RESPE|AgR-AI|R-Rp|Recurso\s+Especial\s+Eleitoral|"
    r"RR|AIRR|ARR|Recurso\s+de\s+Revista|TST-[A-Z-]+|Processo\s+n(?:[ºo°]|\.)?\s*TST-|"
    r"APL|Apela(?:ç|c)[aã]o(?:\s+Criminal)?|RSE|Recurso\s+em\s+Sentido\s+Estrito|"
    r"Agravo\s+(?:Interno|em\s+Recurso\s+Especial|Regimental|de\s+Instrumento)|Tem."
    r")(?![A-Za-zÀ-ÿ])",
    re.IGNORECASE,
)

PREFIX_PATTERN = re.compile(
    r"(?:\b(?:EDcl|EDs?|AgInt|AgRg|AgR|Processo|TST)\b(?:\s+(?:nos?|no|na|em|do|da|de))?[\s-]*)+$",
    re.IGNORECASE,
)

AGREG_PREFIX_RE = re.compile(
    r"(?:\b(?:Primeiro|Segundo|Terceiro|Quarto)\s+)?AG\.?\s*REG\.?\s+(?:na|no)\s*$",
    re.IGNORECASE,
)

INCOMPLETE_CUE_RE = re.compile(
    r"\b(?:julgado|precedente|ac[oó]rd[aã]o|Reclama(?:ç|c)[aã]o|Rcl|APL|"
    r"REsp|AREsp|REspe|AIRR|ARR|RR|RE|AR|RHC|RMS|HC|AI|RO|RSE|AgInt|"
    r"Habeas\s+Corpus|Agravo\s+em\s+Recurso\s+Especial|Recurso\s+em\s+Habeas\s+Corpus)\b",
    re.IGNORECASE,
)


def _iou(a: Mention, b: Mention) -> float:
    intersection = max(0, min(a.end, b.end) - max(a.start, b.start))
    if not intersection:
        return 0.0
    union = a.length + b.length - intersection
    return intersection / union


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    while end > start and text[end - 1] in ",;:." and not text[end - 1 : end + 1].isdigit():
        end -= 1
    return start, end


def _regex_mentions(text: str, pattern: re.Pattern[str], citation_type: str, score: float) -> list[Mention]:
    mentions: list[Mention] = []
    for match in pattern.finditer(text):
        start, end = _trim_span(text, match.start(), match.end())
        mentions.append(
            Mention(
                start=start,
                end=end,
                text=text[start:end],
                citation_type=citation_type,  # type: ignore[arg-type]
                source="regex",
                detector_score=score,
            )
        )
    return mentions


def _incomplete_mentions(text: str) -> list[Mention]:
    mentions: list[Mention] = []
    for match in INCOMPLETE_PATTERN.finditer(text):
        # If a generic phrase such as "acórdão recorrido" precedes the actual
        # reference, the last citation cue is the correct start of the span.
        cues = list(INCOMPLETE_CUE_RE.finditer(match.group(0)))
        relative_start = cues[-1].start() if cues else 0
        start, end = _trim_span(text, match.start() + relative_start, match.end())
        mentions.append(
            Mention(
                start=start,
                end=end,
                text=text[start:end],
                citation_type="jurisprudencia",
                source="regex",
                detector_score=0.96,
            )
        )
    return mentions


_LEGAL_ABBREVIATION_PERIOD = re.compile(
    r"\b(?:Rec|Esp|Ag|Int|H|C|Recl|R|Rel|Min|Des|n)\.",
    re.IGNORECASE,
)


def _has_sentence_boundary(prefix: str) -> bool:
    """Ignore known abbreviation dots, but retain actual sentence stops.

    This temporary view is only used for a boundary decision. Extraction
    continues on the original text, so offsets and OCR bytes are preserved.
    """
    without_abbreviation_dots = _LEGAL_ABBREVIATION_PERIOD.sub(
        lambda match: match.group(0)[:-1], prefix
    )
    return bool(re.search(r"[;!?]|\.(?:\s+)(?=[A-Z])", without_abbreviation_dots))


def _case_mentions(
    text: str, cue_pattern: re.Pattern[str] = CASE_CUE_PATTERN,
    strict_boundaries: bool = False,
) -> list[Mention]:
    mentions: list[Mention] = []
    for cue in cue_pattern.finditer(text):
        if strict_boundaries and cue.end() < len(text):
            following = text[cue.end()]
            # A replacement glyph inside a surname is not a word boundary:
            # otherwise e.g. "Ar\ufffd..." can be mistaken for the class AR.
            if following.isalpha() or following == "\ufffd":
                continue
        window_start = max(0, cue.start() - 70)
        is_tema = cue.group(0).casefold().startswith("tem")
        maximum_gap = 32 if is_tema else 115
        window_end = min(len(text), cue.end() + maximum_gap)
        window = text[cue.start() : window_end]
        number_match = None
        for match in NUMERICISH_RE.finditer(window):
            digits, _ = numericish_to_digits(match.group(0))
            if len(digits) < 4:
                continue
            if len(digits) == 4 and 1900 <= int(digits) <= 2099:
                continue
            number_match = match
            break
        if number_match is None:
            # A clean number can be only four characters and fail the noisy matcher.
            clean = re.search(r"(?<!\d)\d{4,8}(?!\d)", window)
            if clean and not (len(clean.group(0)) == 4 and 1900 <= int(clean.group(0)) <= 2099):
                number_match = clean
        if number_match is None:
            continue

        # A class followed by year + relator is an intentionally incomplete
        # reference.  Do not attach it to an unrelated protocol in the next
        # sentence merely because that protocol falls inside the scan window.
        before_number = window[: number_match.start()]
        if strict_boundaries and _has_sentence_boundary(before_number):
            continue
        if re.search(
            r"\b(?:19|20)\d{2}\b[^.;]{0,50}\b(?:relatoria|rel(?:ator(?:a)?)?\.)",
            before_number,
            re.IGNORECASE,
        ):
            continue

        start = cue.start()
        prefix = text[window_start:start]
        prefix_match = PREFIX_PATTERN.search(prefix)
        if prefix_match:
            start = window_start + prefix_match.start()
        agreg_prefix = AGREG_PREFIX_RE.search(prefix)
        if agreg_prefix:
            start = window_start + agreg_prefix.start()

        end = cue.start() + number_match.end()
        suffix = text[end : min(len(text), end + 18)]
        suffix_match = re.match(r"\s*(?:[/\-–—�]\s*|\(\s*)?[A-Z]{2}(?:\s*\))?", suffix)
        if suffix_match:
            end += suffix_match.end()
        if is_tema:
            tema_suffix = re.match(
                r"\s+da\s+repercuss[aã]o\s+geral", text[end : min(len(text), end + 40)], re.IGNORECASE
            )
            if tema_suffix:
                end += tema_suffix.end()
        start, end = _trim_span(text, start, end)
        mentions.append(
            Mention(
                start=start,
                end=end,
                text=text[start:end],
                citation_type="jurisprudencia",
                source="regex",
                detector_score=0.94,
            )
        )
    return mentions


def non_maximum_suppression(mentions: Iterable[Mention]) -> list[Mention]:
    ordered = sorted(
        mentions,
        key=lambda mention: (-mention.detector_score, -mention.length, mention.start, mention.end),
    )
    kept: list[Mention] = []
    for mention in ordered:
        if any(_iou(mention, current) >= 0.5 for current in kept):
            continue
        kept.append(mention)
    return sorted(kept, key=lambda mention: (mention.start, mention.end))


class RegexCitationExtractor:
    def extract(self, text: str) -> list[Mention]:
        mentions: list[Mention] = []
        mentions.extend(_regex_mentions(text, LAW_PATTERN, "lei", 0.99))
        mentions.extend(_regex_mentions(text, SUMULA_PATTERN, "jurisprudencia", 0.99))
        mentions.extend(_incomplete_mentions(text))
        mentions.extend(_case_mentions(text))
        return non_maximum_suppression(mentions)


V2_ADDITIONAL_CASE_CUES = re.compile(
    r"\b(?:"
    r"ADI|ADC|ADPF|ADO|MI|MS|EREsp|EAREsp|PET|ACO|SL|SS|"
    r"A(?:ç|c)[aã]o\s+Direta\s+de\s+Inconstitucionalidade|"
    r"Argui(?:ç|c)[aã]o\s+de\s+Descumprimento\s+de\s+Preceito\s+Fundamental|"
    r"Mandado\s+de\s+Seguran(?:ç|c)a|Conflito\s+de\s+Compet[eê]ncia|"
    r"Embargos\s+(?:de\s+Diverg[eê]ncia|Infringentes)|"
    r"Recurso\s+Ordin[aá]rio"
    r")(?![A-Za-zÀ-ÿ])",
    re.IGNORECASE,
)

V2_INCOMPLETE_PATTERN = re.compile(
    r"\b(?:julgado|precedente|ac[oó]rd[aã]o|decis[aã]o|entendimento)\b"
    r"[^.;:]{0,180}?\b(?:STF|STJ|TST|TSE|STM)\b"
    r"[^.;:]{0,100}?(?:19|20)\d{2}"
    r"[^.;:]{0,120}?\b(?:relatoria|relator(?:a)?|Rel\.)\s+(?:de\s+|do\s+|da\s+|Min\.\s*)?"
    r"[A-ZÀ-Ý][A-Za-zÀ-ÿ' -]{2,70}",
    re.IGNORECASE | re.DOTALL,
)


# The V2 incomplete-reference pattern intentionally favoured recall.  It can,
# however, span a long piece of narrative prose when a generic word such as
# "acordao" appears before the actual citation cue.  V3 builds the span from
# the fields that make an incomplete reference meaningful instead: a cue,
# court/year (or a procedural class/year), and a relator field.
V3_RELATOR_PATTERN = re.compile(
    r"\b(?i:(?:da\s+|do\s+|sob\s+)?(?:relatoria|relator(?:a)?|rel\.))\s+"
    r"(?i:(?:de\s+|do\s+|da\s+)?(?:Min\.\s*)?)"
    r"[A-Z\u00c0-\u00dd][A-Za-z\u00c0-\u00ff'’-]*"
    r"(?:\s+(?:(?:de|da|do|dos|das)\s+)?[A-Z\u00c0-\u00dd][A-Za-z\u00c0-\u00ff'’-]*){0,6}"
)
V3_TRIBUNAL_PATTERN = re.compile(r"\b(?:STF|STJ|TST|TSE|STM)\b", re.IGNORECASE)
V3_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
V3_GENERIC_CUE_PATTERN = re.compile(
    r"\b(?:julgado|precedente|ac\w{0,2}rd\w{0,2}o|decis\w{0,3}o|entendimento)\b",
    re.IGNORECASE,
)


def _contains_substantial_case_identifier(text: str) -> bool:
    """Whether text already contains a process-like number, not merely a year.

    Complete process references belong to ``_case_mentions``.  Keeping them
    out of the incomplete parser prevents a vague relational clause from
    replacing a stronger, fully resolvable process span.
    """

    for match in NUMERICISH_RE.finditer(text):
        raw = match.group(0)
        # OCR conversion maps letters such as S/I/O into digits.  A relator's
        # surname may contain those letters, so a token with no original digit
        # cannot by itself prove that this is a complete process reference.
        if not any(character.isdigit() for character in raw):
            continue
        digits, _ = numericish_to_digits(raw)
        if len(digits) > 4:
            return True
        if len(digits) == 4 and not (1900 <= int(digits) <= 2099):
            return True
    return False


def _structured_incomplete_mentions(
    text: str, relator_pattern: re.Pattern[str] = V3_RELATOR_PATTERN,
    strict_boundaries: bool = False,
) -> list[Mention]:
    """Extract the shortest supported incomplete jurisprudence reference.

    For each relator field, scan a bounded prefix for citation cues and choose
    the last cue that has enough nearby structure.  Choosing the last cue is
    important in ordinary prose such as "the decision discusses the precedent
    of STF ...": the legal reference begins at ``precedent``, not ``decision``.
    The decision is based only on public citation grammar, not document labels.
    """

    mentions: list[Mention] = []
    for relator_match in relator_pattern.finditer(text):
        scan_start = max(0, relator_match.start() - 260)
        prefix = text[scan_start : relator_match.start()]
        # INCOMPLETE_CUE_RE contains the established procedural classes.  The
        # V3 generic list adds ``decisao`` and ``entendimento`` while allowing
        # the common one- or two-character OCR corruptions in those words.
        cues = list(INCOMPLETE_CUE_RE.finditer(prefix)) + list(
            V3_GENERIC_CUE_PATTERN.finditer(prefix)
        )
        if strict_boundaries:
            cues.extend(V2_ADDITIONAL_CASE_CUES.finditer(prefix))
        cues.sort(key=lambda item: (item.start(), item.end()))
        for cue in reversed(cues):
            start = scan_start + cue.start()
            end = relator_match.end()
            start, end = _trim_span(text, start, end)
            candidate = text[start:end]
            if strict_boundaries:
                field_prefix = text[start:relator_match.start()]
                # Do not borrow a court/year from a previous sentence or a
                # different reference. Abbreviated procedural classes are
                # permitted; sentence punctuation followed by prose is not.
                if _has_sentence_boundary(field_prefix):
                    continue
            if end - start > 240 or _contains_substantial_case_identifier(candidate):
                continue

            # A generic cue needs both court and year.  A named procedural
            # class can be incomplete without an explicit court, but still
            # needs a year to avoid treating prose such as "recurso do autor"
            # as a citation.
            has_tribunal = bool(V3_TRIBUNAL_PATTERN.search(candidate))
            has_year = bool(V3_YEAR_PATTERN.search(candidate))
            has_case_class = bool(CASE_CUE_PATTERN.search(candidate))
            if not has_year or not (has_tribunal or has_case_class):
                continue

            folded = fold_text(candidate)
            # These describe an administrative record, not a judicial source.
            # They are deliberately broad, public-language exclusions used to
            # guard the structured grammar against obvious false positives.
            if "administrativ" in folded or "nao cita" in folded or "sem citar" in folded:
                continue
            mentions.append(
                Mention(
                    start=start,
                    end=end,
                    text=candidate,
                    citation_type="jurisprudencia",
                    source="regex",
                    detector_score=0.96,
                )
            )
            break
    return mentions


def suppress_nested_mentions(
    mentions: Iterable[Mention], containment: float = 0.90
) -> list[Mention]:
    """Remove redundant fragments almost entirely contained in a larger span.

    Gold citations are disjoint by contract, so a same-type inner fragment is a
    detector artifact rather than a second citation.  This particularly removes
    BERT fragments containing only the relator name.
    """

    items = list(mentions)
    keep: list[Mention] = []
    for mention in items:
        redundant = False
        for other in items:
            if mention is other or mention.citation_type != other.citation_type:
                continue
            if other.length <= mention.length:
                continue
            overlap = max(0, min(mention.end, other.end) - max(mention.start, other.start))
            if mention.length and overlap / mention.length >= containment:
                redundant = True
                break
        if not redundant:
            keep.append(mention)
    return sorted(keep, key=lambda mention: (mention.start, mention.end))


class RegexCitationExtractorV2:
    """Conservative extractor derived from DB/header conventions and synthetic v2.

    It keeps the stable v1 rules, adds common procedural classes independent of
    the distributed goldenset, and removes nested fragments before resolution.
    """

    def extract(self, text: str) -> list[Mention]:
        mentions = RegexCitationExtractor().extract(text)
        mentions.extend(_case_mentions(text, V2_ADDITIONAL_CASE_CUES))
        mentions.extend(
            _regex_mentions(
                text,
                V2_INCOMPLETE_PATTERN,
                "jurisprudencia",
                0.95,
            )
        )
        return suppress_nested_mentions(non_maximum_suppression(mentions))


class RegexCitationExtractorV3:
    """Regex extractor with field-based incomplete-reference boundaries.

    V3 retains the stable law, sumula and process-number grammars, including
    V2's extra procedural classes.  It deliberately does *not* reuse V1/V2's
    open-ended incomplete-reference regex; ``_structured_incomplete_mentions``
    supplies that coverage with explicit anchors instead.
    """

    def extract(self, text: str) -> list[Mention]:
        mentions: list[Mention] = []
        mentions.extend(_regex_mentions(text, LAW_PATTERN, "lei", 0.99))
        mentions.extend(_regex_mentions(text, SUMULA_PATTERN, "jurisprudencia", 0.99))
        mentions.extend(_case_mentions(text))
        mentions.extend(_case_mentions(text, V2_ADDITIONAL_CASE_CUES))
        mentions.extend(_structured_incomplete_mentions(text))
        return suppress_nested_mentions(non_maximum_suppression(mentions))


# Keep matching on the original string: normalizing damaged names before
# extraction would shift the character offsets required by the contract.
_V4_NAME_WORD = r"[A-Z\u00c0-\u00dd\ufffd][A-Za-z\u00c0-\u00ff\ufffd'\u2019-]*"
V4_RELATOR_PATTERN = re.compile(
    r"\b(?i:(?:(?:da|do|sob|pela|pelo)\s+)?"
    r"(?:relatoria|relator(?:a)?|rel\.))\s+"
    r"(?i:(?:d[aeoc]\s+)?"
    r"(?:(?:min(?:istro|istra)?\.?|des(?:embargador(?:a)?)?\.?)\s+)?)"
    + _V4_NAME_WORD
    + r"(?:\s+(?:(?i:de|da|do|dos|das|e)\s+)?"
    + _V4_NAME_WORD + r"){0,6}"
)


class RegexCitationExtractorV4:
    """V3 identifiers plus bounded, OCR-tolerant relator fields."""

    def extract(self, text: str) -> list[Mention]:
        mentions = _regex_mentions(text, LAW_PATTERN, "lei", 0.99)
        mentions.extend(_regex_mentions(text, SUMULA_PATTERN, "jurisprudencia", 0.99))
        mentions.extend(_case_mentions(text, strict_boundaries=True))
        mentions.extend(_case_mentions(text, V2_ADDITIONAL_CASE_CUES, True))
        mentions.extend(_structured_incomplete_mentions(text, V4_RELATOR_PATTERN, True))
        return suppress_nested_mentions(non_maximum_suppression(mentions))
