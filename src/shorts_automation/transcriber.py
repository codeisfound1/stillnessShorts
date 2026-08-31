"""Transcript + timestamp cho file audio thuyết minh, dùng faster-whisper (hỗ trợ tiếng Việt).

Kết quả transcript (word-level timestamps) được cache ra JSON trong work_dir để không phải
chạy lại Whisper (tốn thời gian/tài nguyên) mỗi lần script chạy lại trên cùng 1 input.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .config import WhisperConfig

logger = logging.getLogger(__name__)


@dataclass
class Word:
    word: str
    start: float
    end: float


@dataclass
class TranscriptResult:
    words: list[Word]
    full_text: str

    def slice(self, start: float, end: float) -> "TranscriptResult":
        """Lấy các từ nằm trong [start, end), timestamp giữ nguyên theo mốc gốc của toàn bộ audio."""
        picked = [w for w in self.words if w.start >= start and w.start < end]
        text = " ".join(w.word.strip() for w in picked).strip()
        return TranscriptResult(words=picked, full_text=text)


def _cache_path(work_dir: Path, audio_stem: str, whisper_cfg: WhisperConfig) -> Path:
    safe_model = whisper_cfg.model_size.replace("/", "_")
    return work_dir / f"{audio_stem}_transcript_{safe_model}_{whisper_cfg.language}.json"


def _resolve_device_and_compute(whisper_cfg: WhisperConfig) -> tuple[str, str]:
    device = whisper_cfg.device
    compute_type = whisper_cfg.compute_type
    if device == "auto":
        try:
            import torch  # noqa: F401  (chỉ dùng để kiểm tra CUDA nếu torch có sẵn)

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def transcribe_narration(
    *,
    wav_path: Path,
    work_dir: Path,
    whisper_cfg: WhisperConfig,
    force: bool = False,
) -> TranscriptResult:
    """Chạy (hoặc load cache) transcript word-level cho toàn bộ file narration."""
    cache_file = _cache_path(work_dir, wav_path.stem, whisper_cfg)

    if cache_file.exists() and not force:
        logger.info("Dùng transcript cache: %s", cache_file)
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        words = [Word(**w) for w in data["words"]]
        return TranscriptResult(words=words, full_text=data["full_text"])

    logger.info("Transcribe %s bằng faster-whisper (model=%s)...", wav_path.name, whisper_cfg.model_size)
    from faster_whisper import WhisperModel

    device, compute_type = _resolve_device_and_compute(whisper_cfg)
    model = WhisperModel(whisper_cfg.model_size, device=device, compute_type=compute_type)

    segments, _info = model.transcribe(
        str(wav_path),
        language=whisper_cfg.language,
        word_timestamps=whisper_cfg.word_timestamps,
        vad_filter=True,
    )

    words: list[Word] = []
    full_text_parts: list[str] = []
    for seg in segments:
        full_text_parts.append(seg.text.strip())
        if whisper_cfg.word_timestamps and seg.words:
            for w in seg.words:
                words.append(Word(word=w.word, start=float(w.start), end=float(w.end)))
        else:
            # Không có word timestamps -> coi cả segment là 1 "word" để vẫn cắt được theo thời gian.
            words.append(Word(word=seg.text.strip(), start=float(seg.start), end=float(seg.end)))

    result = TranscriptResult(words=words, full_text=" ".join(full_text_parts).strip())

    work_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump({"words": [asdict(w) for w in result.words], "full_text": result.full_text}, f, ensure_ascii=False, indent=2)
    logger.info("Đã lưu transcript cache: %s", cache_file)

    return result
