"""Trích text thô từ 1 file .pdf bằng pypdf - dùng chung cho glossary_corrector.py và
book_alignment.py.
"""

from __future__ import annotations

from pathlib import Path


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
