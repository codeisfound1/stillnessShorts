"""Căn chỉnh (forced alignment) transcript Whisper với văn bản gốc trong sách .pdf tham chiếu
(ví dụ chính cuốn sách/bài giảng đang thuyết minh) - sửa được cả câu dài theo đúng văn bản gốc,
không chỉ từng thuật ngữ riêng lẻ như glossary_corrector.py.

Cách hoạt động, cho mỗi cửa sổ transcript:
1. Định vị THÔ: tra index đảo ngược (từ -> danh sách vị trí trong sách) để tìm vùng trong sách
   có nhiều từ trùng khớp nhất với transcript, ưu tiên từ hiếm (xuất hiện ít lần trong sách) vì
   có giá trị định vị cao hơn từ phổ biến.
2. So khớp TINH: dùng difflib.SequenceMatcher trên đúng vùng đã định vị (+ đệm 2 phía) để tính
   điểm khớp chính xác và tìm các đoạn thẳng hàng.
3. CHỈ áp dụng sửa nếu điểm khớp (ratio) >= min_match_ratio - đoạn audio không khớp sách nào
   (người đọc paraphrase, đọc ngoài sách, hoặc sách không phải nguồn của đoạn này) thì GIỮ
   NGUYÊN transcript Whisper, không chèn nhầm văn bản không liên quan (rủi ro nặng hơn cả việc
   không sửa được gì).
4. Chỉ thay thế tại các đoạn "equal" (đã đúng, không đổi) hoặc "replace" CÙNG ĐỘ DÀI (số từ
   Whisper nghe được = số từ trong sách tại đúng vị trí đó) - giữ nguyên timestamp từng từ. Các
   đoạn "insert"/"delete" hoặc "replace" lệch độ dài bị bỏ qua (không đoán thêm/bớt từ, vì sẽ
   phải tự tạo timestamp mới, không đáng tin cậy).

Nếu có nhiều sách trong thư mục tham chiếu, thử từng sách và chọn sách cho điểm khớp cao nhất.
"""

from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path
from typing import Optional

from .transcriber import Word
from .utils.pdf_text import extract_pdf_text

logger = logging.getLogger(__name__)

# Bộ nhớ đệm trong tiến trình (từ + index vị trí) theo đường dẫn file - tránh trích lại PDF và
# xây lại index nhiều lần nếu gọi lặp lại trong 1 lần chạy (ví dụ nhiều short trong 1 lần chạy).
_BOOK_CACHE: dict[str, tuple[list[str], dict[str, list[int]]]] = {}

_PUNCT_CHARS = " \t\n.,:;!?\"'()[]{}…“”‘’-–—"
_BUCKET_SIZE = 40
_ANCHOR_PAD = 60


def _normalize_word(w: str) -> str:
    return w.strip(_PUNCT_CHARS).lower()


def _build_position_index(book_words: list[str]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for i, w in enumerate(book_words):
        norm = _normalize_word(w)
        if norm:
            index.setdefault(norm, []).append(i)
    return index


def _load_book(pdf_path: Path) -> tuple[list[str], dict[str, list[int]]]:
    cache_key = str(pdf_path.resolve())
    cached = _BOOK_CACHE.get(cache_key)
    if cached is not None:
        return cached
    text = extract_pdf_text(pdf_path)
    words = text.split()
    index = _build_position_index(words)
    _BOOK_CACHE[cache_key] = (words, index)
    return words, index


def load_books(path: Path) -> list[tuple[str, list[str], dict[str, list[int]]]]:
    """Đọc mọi file .pdf trong path (1 file hoặc 1 thư mục, không đệ quy), trả về
    [(tên file, danh sách từ, index vị trí)]. Trả về [] nếu không tìm thấy file .pdf nào."""
    if not path.exists():
        logger.warning("Không tìm thấy file/thư mục book_alignment: %s -> bỏ qua căn chỉnh sách.", path)
        return []

    if path.is_dir():
        pdf_files = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    elif path.suffix.lower() == ".pdf":
        pdf_files = [path]
    else:
        pdf_files = []

    if not pdf_files:
        logger.warning("Không có file .pdf nào trong %s -> bỏ qua căn chỉnh sách.", path)
        return []

    books = []
    for f in pdf_files:
        words, index = _load_book(f)
        if words:
            books.append((f.name, words, index))
    return books


def _locate_candidate_region(
    query_norm: list[str], index: dict[str, list[int]], book_len: int
) -> Optional[tuple[int, int]]:
    """Định vị thô: gom phiếu theo "bucket" vị trí (mỗi bucket _BUCKET_SIZE từ liên tiếp),
    trọng số phiếu tỉ lệ nghịch với độ phổ biến của từ (từ hiếm đáng tin hơn). Trả về vùng
    [start, end) trong sách đáng để so khớp tinh, hoặc None nếu không có từ nào trùng."""
    bucket_votes: dict[int, float] = {}
    for w in query_norm:
        positions = index.get(w)
        if not positions:
            continue
        weight = 1.0 / len(positions)
        for pos in positions:
            bucket = pos // _BUCKET_SIZE
            bucket_votes[bucket] = bucket_votes.get(bucket, 0.0) + weight

    if not bucket_votes:
        return None

    best_bucket = max(bucket_votes, key=lambda b: bucket_votes[b])
    center = best_bucket * _BUCKET_SIZE
    start = max(center - _ANCHOR_PAD, 0)
    end = min(center + len(query_norm) + _ANCHOR_PAD, book_len)
    return start, end


def _align_against_book(
    words: list[Word], book_words: list[str], index: dict[str, list[int]]
) -> tuple[list[Word], int, float]:
    query_norm = [_normalize_word(w.word) for w in words]
    region = _locate_candidate_region(query_norm, index, len(book_words))
    if region is None:
        return words, 0, 0.0

    start, end = region
    book_slice = book_words[start:end]
    book_slice_norm = [_normalize_word(w) for w in book_slice]

    matcher = difflib.SequenceMatcher(None, query_norm, book_slice_norm, autojunk=False)

    corrected = [Word(word=w.word, start=w.start, end=w.end) for w in words]
    correction_count = 0
    matched_word_count = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        same_length = (i2 - i1) == (j2 - j1)
        if tag == "equal":
            matched_word_count += i2 - i1
            continue
        if tag != "replace" or not same_length:
            # "insert"/"delete" hoặc "replace" lệch độ dài: bỏ qua - không đoán thêm/bớt từ vì
            # sẽ phải tự tạo timestamp, không đáng tin cậy.
            continue
        matched_word_count += i2 - i1  # vẫn tính là "khớp vị trí", dù nội dung khác (sẽ sửa)
        for offset in range(i2 - i1):
            new_word = book_slice[j1 + offset]
            if corrected[i1 + offset].word != new_word:
                corrected[i1 + offset].word = new_word
                correction_count += 1

    # Điểm khớp = tỉ lệ từ trong CỬA SỔ TRANSCRIPT có vị trí tương ứng rõ ràng trong sách (dù
    # đúng hay sai nội dung), KHÔNG dùng matcher.ratio() trực tiếp - ratio() chuẩn hóa theo tổng
    # độ dài CẢ 2 chuỗi nên bị pha loãng bởi phần đệm (_ANCHOR_PAD) 2 bên vùng định vị, khiến 1
    # đoạn khớp gần như tuyệt đối vẫn ra điểm rất thấp một cách giả tạo.
    coverage_ratio = matched_word_count / len(query_norm) if query_norm else 0.0

    return corrected, correction_count, coverage_ratio


def apply_book_alignment(
    words: list[Word],
    books: list[tuple[str, list[str], dict[str, list[int]]]],
    *,
    min_match_ratio: float = 0.4,
) -> tuple[list[Word], int]:
    """Thử căn chỉnh transcript với từng sách, chọn sách cho điểm khớp cao nhất. CHỈ áp dụng
    sửa nếu điểm khớp tốt nhất >= min_match_ratio - nếu không sách nào khớp đủ tốt, giữ nguyên
    transcript Whisper (an toàn hơn chèn nhầm văn bản không liên quan). Trả về (words đã sửa
    hoặc giữ nguyên, số từ đã sửa)."""
    if not books or not words:
        return words, 0

    best: Optional[tuple[list[Word], int, float, str]] = None
    for book_name, book_words, index in books:
        corrected, count, ratio = _align_against_book(words, book_words, index)
        if best is None or ratio > best[2]:
            best = (corrected, count, ratio, book_name)

    if best is None or best[2] < min_match_ratio:
        return words, 0

    corrected, count, ratio, book_name = best
    if count:
        logger.info(
            'Book alignment: khớp với sách "%s" (điểm khớp %.2f), đã sửa %d từ theo văn bản gốc.',
            book_name,
            ratio,
            count,
        )
    return corrected, count
