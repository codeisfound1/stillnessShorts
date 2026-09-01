"""Fallback rule-based sinh tiêu đề khi không có API key nào (Groq/Claude) khả dụng.

Chiến lược: tách transcript thành câu, chọn câu có mật độ từ khóa cao nhất
(từ xuất hiện nhiều lần trong đoạn, bỏ qua stopword tiếng Việt phổ biến), rồi cắt
gọn về đúng độ dài tối đa cho phép.
"""

from __future__ import annotations

import re
from collections import Counter

from .base import TitleProvider, TitleProviderError

_VIETNAMESE_STOPWORDS = {
    "và", "là", "của", "có", "được", "trong", "cho", "một", "này", "đó", "khi",
    "để", "với", "các", "những", "đã", "sẽ", "thì", "mà", "nên", "vì", "nếu",
    "như", "ra", "vào", "lên", "xuống", "đi", "lại", "cũng", "rất", "nhiều",
    "không", "còn", "nhưng", "hay", "hoặc", "ở", "tại", "về", "theo", "từ",
    "bị", "phải", "chỉ", "đây", "kia", "ai", "gì", "sao", "vậy", "thế",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_WORD_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)


class RuleBasedTitleProvider(TitleProvider):
    name = "rule_based"

    def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> str:
        raise TitleProviderError("Provider 'rule_based' không hỗ trợ generate_image_prompt (cần LLM thật).")

    def generate_title(self, transcript_text: str, *, max_length: int) -> str:
        text = transcript_text.strip()
        if not text:
            raise TitleProviderError("Transcript rỗng, không thể sinh tiêu đề rule-based.")

        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
        if not sentences:
            sentences = [text]

        all_words = [w.lower() for w in _WORD_RE.findall(text) if w.lower() not in _VIETNAMESE_STOPWORDS]
        freq = Counter(all_words)

        def score(sentence: str) -> float:
            words = [w.lower() for w in _WORD_RE.findall(sentence) if w.lower() not in _VIETNAMESE_STOPWORDS]
            if not words:
                return 0.0
            return sum(freq[w] for w in words) / len(words)

        best_sentence = max(sentences, key=score)
        title = best_sentence.strip()

        if not title:
            title = text

        if len(title) > max_length:
            title = title[: max_length - 1].rstrip() + "…"

        return title[0].upper() + title[1:] if title else title
