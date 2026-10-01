"""Single offline entry point for the frozen regex V4 corrected solution."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from bracis.canonical import CanonicalIndex
from bracis.extraction import (
    RegexCitationExtractorV4,
    non_maximum_suppression,
    suppress_nested_mentions,
)
from bracis.models import Prediction
from bracis.resolver import CitationResolver


def predict(db_path: Path, text_dir: Path) -> list[tuple[str, str]]:
    if not db_path.is_file():
        raise ValueError(f"Banco SQLite inexistente: {db_path}")
    if not text_dir.is_dir():
        raise ValueError(f"Pasta de textos inexistente: {text_dir}")
    files = sorted(text_dir.glob("*.txt"))
    if not files:
        raise ValueError(f"Nenhum .txt encontrado em: {text_dir}")

    # The canonical index is rebuilt from the supplied DB on every invocation.
    index = CanonicalIndex.from_sqlite(db_path)
    extractor = RegexCitationExtractorV4()
    resolver = CitationResolver(index)
    by_document: dict[str, list[Prediction]] = {}

    for path in files:
        document_id = path.stem
        text = path.read_text(encoding="utf-8")
        mentions = suppress_nested_mentions(non_maximum_suppression(extractor.extract(text)))
        predictions: list[Prediction] = []
        cutoff = min(450, max(180, len(text) // 8))
        for mention in mentions:
            resolution = resolver.resolve(mention)
            if (
                mention.citation_type == "jurisprudencia"
                and not resolution.match_kind.startswith("sumula")
                and mention.start < cutoff
            ):
                continue
            predictions.append(Prediction(mention=mention, resolution=resolution))
        predictions.sort(key=lambda item: (item.mention.start, item.mention.end))
        for number, item in enumerate(predictions, start=1):
            item.citation_id = f"c{number}"
        by_document[document_id] = predictions

    # Reproduce the frozen pipeline's selective confidence bonus exactly.
    by_level: dict[int, list[tuple[float, Prediction]]] = {1: [], 2: []}
    for document_id, predictions in by_document.items():
        level = 2 if "_n2_" in document_id else 1
        for item in predictions:
            resolution = item.resolution
            score = 0.0
            if resolution.match_kind in {"law-exact", "sumula-exact"}:
                score = 100.0
            elif resolution.match_kind == "case-index" and resolution.normalization_cost == 0:
                score = 50.0 + item.mention.detector_score
            if score:
                by_level[level].append((score, item))
    for candidates in by_level.values():
        if candidates:
            max(candidates, key=lambda pair: pair[0])[1].resolution.confidence = 0.999

    rows: list[tuple[str, str]] = []
    for document_id, predictions in by_document.items():
        blocks = []
        for item in predictions:
            resolution = item.resolution
            canonical_id = str(resolution.canonical_id) if resolution.classification == "real" else "-"
            confidence = "-" if resolution.confidence is None else f"{resolution.confidence:.4f}"
            blocks.append(
                f"{item.mention.start},{item.mention.end},{resolution.classification},"
                f"{canonical_id},{confidence}"
            )
        rows.append((document_id, "|".join(blocks) if blocks else "-"))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path, help="SQLite no formato original do desafio")
    parser.add_argument("text_dir", type=Path, help="Pasta com os documentos .txt")
    parser.add_argument("output", type=Path, help="CSV de submissão a gerar")
    args = parser.parse_args()
    rows = predict(args.db, args.text_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("documento_id", "citacoes"))
        writer.writerows(rows)
    print(f"{len(rows)} documentos processados: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
