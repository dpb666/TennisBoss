"""Extraction de texte depuis PDF / CSV / TXT pour injection dans le contexte LLM."""
from __future__ import annotations

import csv
import io
from typing import Tuple

MAX_CHARS = 2000  # limite pour ne pas saturer le contexte LLM


def parse(filename: str, data: bytes) -> Tuple[str, str]:
    """Retourne (texte_extrait, type_détecté). Lève ValueError si type inconnu."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return _parse_pdf(data), "pdf"
    if name.endswith(".csv"):
        return _parse_csv(data), "csv"
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")[:MAX_CHARS], "txt"
    raise ValueError(f"Type de fichier non supporté : {filename}")


def _parse_pdf(data: bytes) -> str:
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        parts.append(text.strip())
        if sum(len(p) for p in parts) >= MAX_CHARS:
            break
    return "\n".join(parts)[:MAX_CHARS]


def _parse_csv(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = []
    for i, row in enumerate(reader):
        rows.append(", ".join(row))
        if i >= 50:  # max 50 lignes
            rows.append("...")
            break
    return "\n".join(rows)[:MAX_CHARS]
