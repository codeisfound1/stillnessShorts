"""Sửa lỗi hậu kỳ transcript Whisper theo 1 danh sách thuật ngữ tham chiếu (glossary).

Đọc thuật ngữ từ file .txt (mỗi dòng 1 thuật ngữ, dòng trống hoặc bắt đầu bằng "#" bị bỏ qua)
hoặc .pdf (trích text bằng pypdf, coi mỗi dòng là 1 thuật ngữ). Sau đó duyệt transcript theo
cửa sổ trượt cùng số âm tiết với từng thuật ngữ - nếu 1 cụm từ liên tiếp GẦN GIỐNG (fuzzy, theo
difflib) nhưng chưa khớp tuyệt đối 1 thuật ngữ, thay chữ của từng âm tiết bằng đúng chính tả
thuật ngữ đó, giữ nguyên timestamp (start/end) của từng từ - không làm lệch phụ đề/audio sync.

Chỉ so khớp cửa sổ ĐÚNG số âm tiết với thuật ngữ để tránh phải "gộp/tách" timestamp phức tạp.
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path

from .transcriber import Word

logger = logging.getLogger(__name__)


def _extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def load_glossary_terms(path: Path) -> list[str]:
    """Đọc danh sách thuật ngữ từ file .txt hoặc .pdf. Trả về [] nếu không tìm thấy file."""
    if not path.exists():
        logger.warning("Không tìm thấy file glossary: %s -> bỏ qua sửa lỗi theo glossary.", path)
        return []

    raw_text = _extract_pdf_text(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")

    terms: list[str] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    return terms


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def apply_glossary_corrections(
    words: list[Word], terms: list[str], *, similarity_threshold: float = 0.72
) -> tuple[list[Word], int]:
    """Trả về (words đã sửa theo glossary, số lần sửa). Không sửa gì nếu terms hoặc words rỗng."""
    if not terms or not words:
        return words, 0

    # Nhóm thuật ngữ theo số âm tiết - chỉ so khớp cửa sổ transcript cùng độ dài với thuật ngữ.
    terms_by_len: dict[int, list[str]] = {}
    for term in terms:
        syllables = term.split()
        if syllables:
            terms_by_len.setdefault(len(syllables), []).append(term)

    corrected = [Word(word=w.word, start=w.start, end=w.end) for w in words]
    correction_count = 0
    n = len(corrected)
    i = 0
    while i < n:
        matched_length = 0
        # Ưu tiên cụm dài hơn trước để không "chẻ" nhầm 1 thuật ngữ dài thành thuật ngữ ngắn hơn.
        for length in sorted(terms_by_len.keys(), reverse=True):
            if i + length > n:
                continue
            window = corrected[i : i + length]
            window_text = _normalize(" ".join(w.word for w in window))
            for term in terms_by_len[length]:
                term_norm = _normalize(term)
                if window_text == term_norm:
                    matched_length = length  # đã đúng sẵn, không cần sửa nhưng vẫn nhảy qua
                    break
                ratio = difflib.SequenceMatcher(None, window_text, term_norm).ratio()
                if ratio >= similarity_threshold:
                    before = " ".join(w.word for w in window)
                    for w, syllable in zip(window, term.split()):
                        w.word = syllable
                    logger.info('Sửa theo glossary: "%s" -> "%s" (độ giống %.2f)', before, term, ratio)
                    correction_count += 1
                    matched_length = length
                    break
            if matched_length:
                break
        i += matched_length if matched_length else 1

    return corrected, correction_count
