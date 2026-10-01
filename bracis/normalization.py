from __future__ import annotations

import re
import unicodedata


SPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

TRIBUNALS = ("STF", "STJ", "TSE", "TST", "STM")

COURT_CLASS_ALIASES: dict[str, tuple[str, ...]] = {
    "resp": ("resp", "r esp", "rec esp", "recurso especial"),
    "aresp": ("aresp", "a resp", "agravo em recurso especial", "agravo no recurso especial"),
    "rhc": ("rhc", "recurso em habeas corpus"),
    "hc": ("hc", "habeas corpus"),
    "rms": ("rms", "recurso em mandado de seguranca"),
    "rcl": ("rcl", "recl", "reclamacao"),
    "re": ("re", "recurso extraordinario"),
    "ai": ("ai", "agravo de instrumento"),
    "ar": ("ar", "acao rescisoria"),
    "respe": ("respe", "recurso especial eleitoral"),
    "ro": ("ro", "recurso ordinario"),
    "rr": ("rr", "recurso de revista"),
    "airr": ("airr", "agravo de instrumento em recurso de revista"),
    "arr": ("arr",),
    "apl": ("apl", "apelacao", "apelacao criminal"),
    "rse": ("rse", "recurso em sentido estrito"),
    "agint": ("agint", "agravo interno"),
}

LAW_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "cf": ("constituicao federal", "constituicao da republica", "cf 88", "cf88", "cf"),
    "cpc": ("codigo de processo civil", "cpc"),
    "cc": ("codigo civil", "cc"),
    "clt": ("consolidacao das leis do trabalho", "clt"),
    "cpp": ("codigo de processo penal", "cpp"),
    "cpm": ("codigo penal militar", "cpm"),
    "cdc": ("codigo de defesa do consumidor", "cdc"),
    "ce": ("codigo eleitoral", "ce"),
    "lc64": ("lei complementar 64", "lc 64", "lc64"),
}


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold_text(value: str) -> str:
    value = strip_accents(unicodedata.normalize("NFC", value)).casefold()
    # Both true Unicode symbols and common mojibake/replacement forms occur in
    # the snapshot. They are separators, not semantic characters.
    value = value.replace("º", "o").replace("ª", "a").replace("§", " paragrafo ")
    value = value.replace("âº", "o").replace("âª", "a").replace("â§", " paragrafo ")
    return SPACE_RE.sub(" ", value).strip()


def compact_text(value: str) -> str:
    return NON_ALNUM_RE.sub("", fold_text(value))


def canonical_tribunal(value: str) -> str | None:
    folded = f" {fold_text(value)} "
    for tribunal in TRIBUNALS:
        if re.search(rf"(?<![a-z]){tribunal.casefold()}(?![a-z])", folded):
            return tribunal
    return None


def canonical_case_class(value: str) -> str | None:
    compact = NON_ALNUM_RE.sub(" ", fold_text(value))
    # Match the most specific name globally.  Iterating the dictionary would
    # classify "recurso especial eleitoral" as the shorter "recurso especial"
    # and "agravo em recurso especial" as REsp.
    ordered_aliases = sorted(
        (
            (alias, canonical)
            for canonical, aliases in COURT_CLASS_ALIASES.items()
            for alias in aliases
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for alias, canonical in ordered_aliases:
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", compact):
            return canonical
    return None


def canonical_law_source(value: str) -> str | None:
    folded = fold_text(value)
    folded = folded.replace("codig0", "codigo")
    words = NON_ALNUM_RE.sub(" ", folded)
    if "constituicao" in words:
        return "cf"
    if "lei complementar" in words and re.search(r"\b64\b", words):
        return "lc64"
    if re.search(r"\blc\s*(?:n\s*o?)?\s*64\b", words):
        return "lc64"

    # Database headers use a law/decree number while citations often use a
    # familiar code acronym. These stable identifiers join both forms.
    digits = re.sub(r"\D", "", folded)
    for number, source in {
        "13105": "cpc",
        "10406": "cc",
        "5452": "clt",
        "3689": "cpp",
        "1001": "cpm",
        "8078": "cdc",
        "4737": "ce",
    }.items():
        if number in digits:
            return source

    for source, aliases in LAW_SOURCE_ALIASES.items():
        if any(
            re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", words)
            for alias in aliases
        ):
            return source
    generic_law = re.search(
        r"\blei(?: complementar)?\s+(?:n\s*)?[^0-9]{0,3}([0-9][0-9. ]{0,8}?)(?:/|\s+de\b)",
        folded,
    )
    if generic_law:
        law_number = re.sub(r"\D", "", generic_law.group(1)).lstrip("0") or "0"
        return f"law:{law_number}"
    return None


OCR_DIGIT_MAP = {
    "o": "0",
    "O": "0",
    "i": "1",
    "I": "1",
    "l": "1",
    "L": "1",
    "|": "1",
    "s": "5",
    "S": "5",
    "g": "9",
    "G": "9",
}

OCR_NUMBER_CHAR = r"0-9OIlLsSgG|"
NUMBER_SEPARATOR = r"[\s.\-/–—�]"

# CNJ's first field is sometimes printed without leading zeroes. Separating
# the six fields lets us restore the canonical 20-digit representation.
CNJ_RE = re.compile(
    rf"(?<![A-Za-z0-9])"
    rf"([{OCR_NUMBER_CHAR}]{{1,7}}){NUMBER_SEPARATOR}{{1,5}}"
    rf"([{OCR_NUMBER_CHAR}]{{2}}){NUMBER_SEPARATOR}{{1,5}}"
    rf"([{OCR_NUMBER_CHAR}]{{4}}){NUMBER_SEPARATOR}{{1,5}}"
    rf"([{OCR_NUMBER_CHAR}]){NUMBER_SEPARATOR}{{1,5}}"
    rf"([{OCR_NUMBER_CHAR}]{{2}}){NUMBER_SEPARATOR}{{1,5}}"
    rf"([{OCR_NUMBER_CHAR}]{{4}})(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# Frequent OCR damage removes every CNJ separator except the hyphen after the
# sequence number, e.g. 7001184-1520197000000.
COMPACT_CNJ_RE = re.compile(
    rf"(?<![A-Za-z0-9])([{OCR_NUMBER_CHAR}]{{1,7}})\s*[-–—�]+\s*"
    rf"([{OCR_NUMBER_CHAR}]{{13}})(?![A-Za-z0-9])",
    re.IGNORECASE,
)

SHORT_NUMBER_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:[{OCR_NUMBER_CHAR}]{{1,3}}(?:[\s.\-–—�]{{1,5}}[{OCR_NUMBER_CHAR}]{{3}}){{1,2}}|"
    rf"[{OCR_NUMBER_CHAR}]{{4,8}})(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# Public compatibility name used by the span extractor.
NUMERICISH_RE = re.compile(
    rf"(?:{CNJ_RE.pattern})|(?:{COMPACT_CNJ_RE.pattern})|(?:{SHORT_NUMBER_RE.pattern})",
    re.IGNORECASE,
)


def numericish_to_digits(value: str) -> tuple[str, int]:
    out: list[str] = []
    corrections = 0
    for char in value:
        if char.isdigit():
            out.append(char)
        elif char in OCR_DIGIT_MAP:
            out.append(OCR_DIGIT_MAP[char])
            corrections += 1
    return "".join(out), corrections


def extract_number_keys(value: str) -> list[tuple[str, int, int]]:
    """Return normalized ``(key, character position, OCR cost)`` tuples."""
    found: dict[tuple[str, int], int] = {}
    cnj_spans: list[tuple[int, int]] = []
    for match in CNJ_RE.finditer(value):
        fields: list[str] = []
        cost = 0
        for group in match.groups():
            digits, group_cost = numericish_to_digits(group)
            fields.append(digits)
            cost += group_cost
        fields[0] = fields[0].zfill(7)
        found[("cnj:" + "".join(fields), match.start())] = cost
        cnj_spans.append(match.span())

    for match in COMPACT_CNJ_RE.finditer(value):
        if any(start <= match.start() and match.end() <= end for start, end in cnj_spans):
            continue
        first, first_cost = numericish_to_digits(match.group(1))
        rest, rest_cost = numericish_to_digits(match.group(2))
        found[(f"cnj:{first.zfill(7)}{rest}", match.start())] = first_cost + rest_cost
        cnj_spans.append(match.span())

    for match in SHORT_NUMBER_RE.finditer(value):
        if any(start <= match.start() and match.end() <= end for start, end in cnj_spans):
            continue
        digits, corrections = numericish_to_digits(match.group(0))
        if 4 <= len(digits) <= 8:
            key = f"num:{digits.lstrip('0') or '0'}"
            found[(key, match.start())] = min(
                corrections, found.get((key, match.start()), corrections)
            )

    return [
        (key, position, cost)
        for (key, position), cost in sorted(found.items(), key=lambda item: item[0][1])
    ]


def extract_article(value: str) -> str | None:
    folded = fold_text(value)
    match = re.search(r"\b(?:art(?:igo)?)[ .]*([0-9]{1,4}(?:\.[0-9]{3})?)", folded)
    if not match:
        return None
    return str(int(match.group(1).replace(".", "")))


def normalize_person_name(value: str) -> str:
    folded = fold_text(value)
    folded = re.sub(r"\b(?:min(?:istro|istra)?|rel(?:ator|atora)?|dr|dra)\b", " ", folded)
    return SPACE_RE.sub(" ", re.sub(r"[^a-z ]+", " ", folded)).strip()
