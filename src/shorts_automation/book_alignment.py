"""Căn chỉnh (forced alignment) transcript Whisper với văn bản gốc trong sách .pdf tham chiếu
(ví dụ chính cuốn sách/bài giảng đang thuyết minh) - sửa được cả câu dài theo đúng văn bản gốc,
không chỉ từng thuật ngữ riêng lẻ như glossary_corrector.py.

Cách hoạt động, cho mỗi cửa sổ transcript:
1. Định vị THÔ: tra index đảo ngược (từ -> danh sách vị trí trong sách) để tìm vùng trong sách
   có nhiều từ trùng khớp nhất với transcript, ưu tiên từ hiếm (xuất hiện ít lần trong sách) vì
   có giá trị định vị cao hơn từ phổ biến.
2. So khớp TINH: dùng difflib.SequenceMatcher trên đúng vùng đã định vị (+ đệm 2 phía) để tính
   điểm khớp chính xác và tìm các đoạn thẳng hàng.
3. CHỈ dùng văn bản sách nếu điểm khớp (coverage ratio) >= min_match_ratio - đoạn audio không
   khớp sách nào (người đọc paraphrase, đọc ngoài sách, hoặc sách không phải nguồn của đoạn này)
   thì GIỮ NGUYÊN transcript Whisper, không chèn nhầm văn bản không liên quan (rủi ro nặng hơn
   cả việc không sửa được gì).
4. Khi đã đạt ngưỡng: TIN TƯỞNG HOÀN TOÀN văn bản sách làm nguồn chuẩn chính tả, bỏ qua hẳn chữ
   Whisper nghe được cho toàn bộ cửa sổ này (kể cả các đoạn không thẳng hàng 1-1) - Whisper chỉ
   còn dùng để CĂN THỜI GIAN (timeframe) khớp với giọng đọc mp3:
   - "equal": giữ nguyên từ + timestamp (đã đúng sẵn).
   - "replace" cùng độ dài: thay chữ bằng từ trong sách, giữ nguyên timestamp.
   - "replace" lệch độ dài, hoặc "insert" (sách có từ mà Whisper không nghe ra): dùng đúng số
     từ trong sách tại vị trí đó, CHIA ĐỀU thời gian theo khoảng thời gian gốc bên Whisper tương
     ứng (nội suy tuyến tính) - không có mốc thời gian riêng cho từng từ mới nên đây là cách ước
     lượng hợp lý nhất để khớp video với giọng đọc.
   - "delete" (Whisper nghe thêm từ mà sách không có, ví dụ nghe lặp/ảo giác): bỏ hẳn các từ này
     - sách là nguồn chuẩn nên không giữ lại phần Whisper tự thêm.
   Khi đó BỎ QUA glossary_corrector cho cửa sổ này luôn (đã có nguồn chuẩn, không cần so khớp mờ
   thêm nữa) - glossary chỉ chạy khi không sách nào khớp đủ ngưỡng.

Nếu có nhiều sách trong thư mục tham chiếu, thử từng sách và chọn sách cho điểm khớp cao nhất.
Tên sách khớp được trả về cho caller (transcriber.py) để dùng làm nguồn tham khảo hiển thị trong
mô tả video YouTube và overlay trên chính video (xem book_reference trong config.py/subtitles.py).
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


def _interpolate_timestamps(start_time: float, end_time: float, count: int) -> list[tuple[float, float]]:
    """Chia đều khoảng [start_time, end_time] thành count đoạn liên tiếp bằng nhau - dùng khi số
    từ trong sách khác số từ Whisper nghe được tại cùng vị trí, nên không có mốc thời gian gốc
    cho từng từ mới; chia đều theo tỉ lệ thời gian của cả đoạn là cách ước lượng hợp lý nhất."""
    if count <= 0:
        return []
    if count == 1:
        return [(start_time, end_time)]
    step = (end_time - start_time) / count
    return [(start_time + i * step, start_time + (i + 1) * step) for i in range(count)]


def _coverage_ratio(query_len: int, opcodes: list[tuple[str, int, int, int, int]]) -> float:
    """Điểm khớp = tỉ lệ từ trong CỬA SỔ TRANSCRIPT có vị trí tương ứng rõ ràng trong sách (dù
    đúng hay sai nội dung - "equal" hoặc "replace" cùng độ dài), KHÔNG dùng matcher.ratio() trực
    tiếp - ratio() chuẩn hóa theo tổng độ dài CẢ 2 chuỗi nên bị pha loãng bởi phần đệm
    (_ANCHOR_PAD) 2 bên vùng định vị, khiến 1 đoạn khớp gần như tuyệt đối vẫn ra điểm rất thấp
    một cách giả tạo."""
    matched = 0
    for tag, i1, i2, _j1, _j2 in opcodes:
        if tag == "equal" or (tag == "replace" and (i2 - i1) == (_j2 - _j1)):
            matched += i2 - i1
    return matched / query_len if query_len else 0.0


def _build_book_text_words(words: list[Word], book_slice: list[str], opcodes: list[tuple[str, int, int, int, int]]) -> list[Word]:
    """Dựng lại toàn bộ danh sách từ theo ĐÚNG văn bản sách (nguồn chuẩn chính tả), chỉ dùng
    Whisper để suy ra thời gian xuất hiện. Bỏ phần đệm đầu/cuối vùng định vị KHÔNG thuộc về cửa
    sổ transcript (opcode "insert" nằm trọn ở đầu hoặc cuối danh sách opcode, không có từ Whisper
    tương ứng) - nếu không sẽ chèn nhầm cả đoạn đệm dài vào kết quả."""
    n = len(opcodes)
    output: list[Word] = []
    for idx, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "insert" and i1 == i2 and (idx == 0 or idx == n - 1):
            # Phần đệm ở đầu/cuối vùng định vị, không tương ứng với bất kỳ từ Whisper nào trong
            # cửa sổ này - bỏ qua, không phải nội dung thật của cửa sổ.
            continue
        if tag == "equal":
            output.extend(Word(word=w.word, start=w.start, end=w.end) for w in words[i1:i2])
            continue
        if tag == "delete":
            # Whisper nghe thêm từ mà sách không có ở vị trí này (nghe lặp/ảo giác...) - bỏ hẳn,
            # tin tưởng sách là nguồn chuẩn.
            continue
        # "replace" hoặc "insert" giữa chừng: dùng từ trong sách, chia đều thời gian theo
        # khoảng thời gian Whisper tương ứng (hoặc mốc biên nếu insert thuần không có từ Whisper).
        book_words_here = book_slice[j1:j2]
        if i2 > i1:
            time_start, time_end = words[i1].start, words[i2 - 1].end
        else:
            boundary = words[i1].start if i1 < len(words) else words[-1].end
            time_start = time_end = boundary
        for word_text, (s, e) in zip(book_words_here, _interpolate_timestamps(time_start, time_end, len(book_words_here))):
            output.append(Word(word=word_text, start=s, end=e))
    return output


def _align_against_book(
    words: list[Word], book_words: list[str], index: dict[str, list[int]]
) -> tuple[list[Word], float]:
    query_norm = [_normalize_word(w.word) for w in words]
    region = _locate_candidate_region(query_norm, index, len(book_words))
    if region is None:
        return words, 0.0

    start, end = region
    book_slice = book_words[start:end]
    book_slice_norm = [_normalize_word(w) for w in book_slice]

    matcher = difflib.SequenceMatcher(None, query_norm, book_slice_norm, autojunk=False)
    opcodes = matcher.get_opcodes()
    ratio = _coverage_ratio(len(query_norm), opcodes)
    replaced = _build_book_text_words(words, book_slice, opcodes)
    return replaced, ratio


def apply_book_alignment(
    words: list[Word],
    books: list[tuple[str, list[str], dict[str, list[int]]]],
    *,
    min_match_ratio: float = 0.75,
) -> tuple[list[Word], Optional[str]]:
    """Thử căn chỉnh transcript với từng sách, chọn sách cho điểm khớp cao nhất. Nếu điểm khớp
    tốt nhất >= min_match_ratio, DÙNG HẲN văn bản sách đó làm nguồn chuẩn (bỏ chữ Whisper, chỉ
    giữ lại việc căn thời gian) - nếu không sách nào khớp đủ tốt, giữ nguyên transcript Whisper
    (an toàn hơn chèn nhầm văn bản không liên quan). Trả về (words, tên sách đã khớp hoặc None) -
    tên sách để caller vừa biết có cần chạy tiếp glossary_corrector hay không (không cần nữa nếu
    đã có nguồn chuẩn từ sách), vừa dùng làm nguồn tham khảo hiển thị trên video/mô tả YouTube."""
    if not books or not words:
        return words, None

    best: Optional[tuple[list[Word], float, str]] = None
    for book_name, book_words, index in books:
        replaced, ratio = _align_against_book(words, book_words, index)
        if best is None or ratio > best[1]:
            best = (replaced, ratio, book_name)

    if best is None or best[1] < min_match_ratio:
        return words, None

    replaced, ratio, book_filename = best
    book_name = Path(book_filename).stem
    logger.info(
        'Book alignment: khớp với sách "%s" (điểm khớp %.2f) - dùng văn bản sách làm nguồn chuẩn, '
        "chỉ căn thời gian theo Whisper (%d từ -> %d từ).",
        book_name,
        ratio,
        len(words),
        len(replaced),
    )
    return replaced, book_name
