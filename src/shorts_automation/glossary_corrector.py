"""Sửa lỗi hậu kỳ transcript Whisper theo 1 (hoặc nhiều) danh sách thuật ngữ tham chiếu.

glossary.path có thể là:
- 1 file .txt (mỗi dòng 1 thuật ngữ, dòng trống hoặc bắt đầu bằng "#" bị bỏ qua) hoặc .pdf
  (trích text bằng pypdf, coi mỗi dòng là 1 thuật ngữ).
- 1 THƯ MỤC (ví dụ data/input/pdf/) chứa nhiều file .txt/.pdf - sách/tài liệu tham chiếu (ebook
  PDF, danh sách thuật ngữ...) - tất cả được gộp lại thành 1 danh sách thuật ngữ duy nhất. Xử
  lý theo thứ tự tên file để ổn định giữa các lần chạy.

Lưu ý khi dùng nguyên 1 cuốn sách PDF: cơ chế này vẫn coi MỖI DÒNG trích ra là 1 "thuật ngữ" -
với sách in dạng đoạn văn dài (PDF ngắt dòng theo khổ trang, không phải ngắt theo câu/thuật
ngữ), nhiều dòng sẽ là các câu/cụm dài không khớp với bất kỳ cửa sổ transcript nào (vô hại,
chỉ đơn giản không có tác dụng sửa lỗi) - hiệu quả nhất vẫn là dùng file dạng danh sách thuật
ngữ ngắn gọn (mỗi dòng 1 cụm từ, xem data/input/pdf/glossary.txt làm ví dụ).

Sau khi có danh sách thuật ngữ, duyệt transcript theo cửa sổ trượt cùng số âm tiết với từng
thuật ngữ - nếu 1 cụm từ liên tiếp GẦN GIỐNG (fuzzy, so khớp từng âm tiết theo đúng vị trí)
nhưng chưa khớp tuyệt đối 1 thuật ngữ, thay chữ của từng âm tiết bằng đúng chính tả thuật ngữ
đó, giữ nguyên timestamp (start/end) của từng từ - không làm lệch phụ đề/audio sync.

Chỉ so khớp cửa sổ ĐÚNG số âm tiết với thuật ngữ để tránh phải "gộp/tách" timestamp phức tạp.
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path

from .transcriber import Word
from .utils.pdf_text import extract_pdf_text

logger = logging.getLogger(__name__)

_SOURCE_EXTENSIONS = {".txt", ".pdf"}

# Bộ nhớ đệm trong tiến trình theo đường dẫn file - tránh trích lại PDF/đọc lại file nhiều lần
# nếu gọi lặp lại trong 1 lần chạy (ví dụ nhiều short trong 1 lần chạy script).
_TERMS_CACHE: dict[str, list[str]] = {}


def _load_terms_from_file(path: Path) -> list[str]:
    cache_key = str(path.resolve())
    cached = _TERMS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    raw_text = extract_pdf_text(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")
    terms: list[str] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    _TERMS_CACHE[cache_key] = terms
    return terms


def load_glossary_terms(path: Path) -> list[str]:
    """Đọc danh sách thuật ngữ từ 1 file .txt/.pdf, HOẶC gộp từ mọi file .txt/.pdf trong 1 thư
    mục (không đệ quy, xử lý theo thứ tự tên file). Trả về [] nếu không tìm thấy gì hợp lệ."""
    if not path.exists():
        logger.warning("Không tìm thấy file/thư mục glossary: %s -> bỏ qua sửa lỗi theo glossary.", path)
        return []

    if path.is_dir():
        source_files = sorted(
            p for p in path.iterdir() if p.is_file() and p.suffix.lower() in _SOURCE_EXTENSIONS
        )
        if not source_files:
            logger.warning(
                "Thư mục glossary %s không có file .txt/.pdf nào -> bỏ qua sửa lỗi theo glossary.", path
            )
            return []
        logger.info("Glossary: đọc %d file tham chiếu trong %s: %s", len(source_files), path, [f.name for f in source_files])
        terms: list[str] = []
        for source_file in source_files:
            terms.extend(_load_terms_from_file(source_file))
        return terms

    return _load_terms_from_file(path)


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


# Sàn độ giống TỐI THIỂU cho TỪNG âm tiết (không chỉ trung bình cả cụm) - nếu thiếu điều kiện
# này, 1 âm tiết sai hoàn toàn (ratio thấp) vẫn có thể "trót lọt" nhờ các âm tiết khác trong
# cùng cụm khớp tuyệt đối kéo trung bình lên cao, dẫn tới sửa nhầm 1 từ ĐÚNG thành SAI (phát
# hiện khi test với glossary lớn ghép từ nguyên sách PDF - nhiều dòng tiêu đề/mục lục ngắn làm
# tăng nguy cơ trùng khớp ngẫu nhiên).
_MIN_SYLLABLE_RATIO = 0.6


def _syllable_ratios(window_words: list[str], term_syllables: list[str]) -> list[float]:
    """Độ giống theo TỪNG VỊ TRÍ âm tiết (word[i] so với syllable[i]), KHÔNG dùng ratio trên cả
    cụm đã ghép chuỗi. Ghép chuỗi rồi so ratio dễ bị "lệch pha" - 1 cửa sổ dịch lệch 1 từ so với
    thuật ngữ vẫn có thể ra điểm giống cao chỉ vì phần lớn ký tự trùng nhau ở vị trí khác, dẫn
    tới sửa nhầm đúng thành sai. So khớp theo đúng vị trí từng âm tiết tránh được vấn đề đó."""
    return [
        difflib.SequenceMatcher(None, w.strip().lower(), t.strip().lower()).ratio()
        for w, t in zip(window_words, term_syllables)
    ]


def apply_glossary_corrections(
    words: list[Word], terms: list[str], *, similarity_threshold: float = 0.72
) -> tuple[list[Word], int]:
    """Trả về (words đã sửa theo glossary, số lần sửa). Không sửa gì nếu terms hoặc words rỗng."""
    if not terms or not words:
        return words, 0

    # Nhóm thuật ngữ theo số âm tiết - chỉ so khớp cửa sổ transcript cùng độ dài với thuật ngữ.
    # Bỏ qua thuật ngữ 1 âm tiết: 1 từ đơn tiếng Việt quá phổ biến/mơ hồ để so khớp mờ an toàn -
    # dễ trùng ngẫu nhiên với từ hoàn toàn không liên quan (xem lịch sử sửa lỗi này).
    terms_by_len: dict[int, list[str]] = {}
    for term in terms:
        syllables = term.split()
        if len(syllables) >= 2:
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
            window_words = [w.word for w in window]
            window_text = _normalize(" ".join(window_words))
            for term in terms_by_len[length]:
                term_syllables = term.split()
                if window_text == _normalize(term):
                    matched_length = length  # đã đúng sẵn, không cần sửa nhưng vẫn nhảy qua
                    break
                ratios = _syllable_ratios(window_words, term_syllables)
                avg_ratio = sum(ratios) / len(ratios) if ratios else 0.0
                min_ratio = min(ratios) if ratios else 0.0
                if avg_ratio >= similarity_threshold and min_ratio >= _MIN_SYLLABLE_RATIO:
                    before = " ".join(window_words)
                    for w, syllable in zip(window, term_syllables):
                        w.word = syllable
                    logger.info(
                        'Sửa theo glossary: "%s" -> "%s" (độ giống TB %.2f, thấp nhất %.2f)',
                        before, term, avg_ratio, min_ratio,
                    )
                    correction_count += 1
                    matched_length = length
                    break
            if matched_length:
                break
        i += matched_length if matched_length else 1

    return corrected, correction_count
