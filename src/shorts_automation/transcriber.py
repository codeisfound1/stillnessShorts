"""Transcript + timestamp cho file audio thuyết minh, dùng faster-whisper (hỗ trợ tiếng Việt).

Kết quả transcript (word-level timestamps) được cache ra JSON trong work_dir để không phải
chạy lại Whisper (tốn thời gian/tài nguyên) mỗi lần script chạy lại trên cùng 1 input.

Mặc định chỉ transcribe đúng đoạn audio (cửa sổ) cần dùng cho đợt chạy hiện tại - bằng tổng
thời lượng các short muốn tạo - thay vì toàn bộ file narration (có thể dài hàng giờ), giúp
tiết kiệm đáng kể thời gian chạy khi narration dài nhưng mỗi đợt chỉ tạo vài short.
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


def _run_whisper(audio_path: Path, whisper_cfg: WhisperConfig) -> TranscriptResult:
    """Chạy faster-whisper trên đúng 1 file, trả về timestamp TƯƠNG ĐỐI so với đầu file đó."""
    from faster_whisper import WhisperModel

    device, compute_type = _resolve_device_and_compute(whisper_cfg)
    model = WhisperModel(whisper_cfg.model_size, device=device, compute_type=compute_type)

    segments, _info = model.transcribe(
        str(audio_path),
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

    return TranscriptResult(words=words, full_text=" ".join(full_text_parts).strip())


def _save_cache(cache_file: Path, result: TranscriptResult) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump({"words": [asdict(w) for w in result.words], "full_text": result.full_text}, f, ensure_ascii=False, indent=2)
    logger.info("Đã lưu transcript cache: %s", cache_file)


def _load_cache(cache_file: Path) -> TranscriptResult:
    logger.info("Dùng transcript cache: %s", cache_file)
    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    words = [Word(**w) for w in data["words"]]
    return TranscriptResult(words=words, full_text=data["full_text"])


def transcribe_narration(
    *,
    wav_path: Path,
    work_dir: Path,
    whisper_cfg: WhisperConfig,
    force: bool = False,
) -> TranscriptResult:
    """Chạy (hoặc load cache) transcript word-level cho TOÀN BỘ file narration.

    Chậm với file dài - ưu tiên dùng transcribe_narration_window() để chỉ transcribe đúng
    phần audio cần dùng cho đợt chạy hiện tại.
    """
    safe_model = whisper_cfg.model_size.replace("/", "_")
    cache_file = work_dir / f"{wav_path.stem}_transcript_{safe_model}_{whisper_cfg.language}_full.json"

    if cache_file.exists() and not force:
        return _load_cache(cache_file)

    logger.info("Transcribe toàn bộ %s bằng faster-whisper (model=%s)...", wav_path.name, whisper_cfg.model_size)
    result = _run_whisper(wav_path, whisper_cfg)
    _save_cache(cache_file, result)
    return result


def transcribe_narration_window(
    *,
    wav_path: Path,
    work_dir: Path,
    whisper_cfg: WhisperConfig,
    window_start: float,
    window_end: float,
    force: bool = False,
) -> TranscriptResult:
    """Chỉ transcribe đoạn [window_start, window_end) của narration (nhanh hơn nhiều so với
    transcribe toàn bộ file khi narration dài). Timestamp trả về TUYỆT ĐỐI theo mốc gốc của
    toàn bộ file (cộng window_start vào từng word) để tương thích với audio_pointer_sec.
    """
    window_start = max(window_start, 0.0)
    window_end = max(window_end, window_start)

    safe_model = whisper_cfg.model_size.replace("/", "_")
    cache_file = work_dir / (
        f"{wav_path.stem}_transcript_{safe_model}_{whisper_cfg.language}"
        f"_{window_start:.1f}-{window_end:.1f}.json"
    )

    if cache_file.exists() and not force:
        return _load_cache(cache_file)

    if window_end - window_start <= 0:
        result = TranscriptResult(words=[], full_text="")
        _save_cache(cache_file, result)
        return result

    from .audio_cutter import AudioSegment, extract_narration_clip

    window_clip_path = work_dir / f"{wav_path.stem}_transcribe_window.wav"
    extract_narration_clip(wav_path, AudioSegment(start=window_start, end=window_end), window_clip_path)

    logger.info(
        "Transcribe đoạn [%.1fs-%.1fs] (%.1fs) của %s bằng faster-whisper (model=%s)...",
        window_start,
        window_end,
        window_end - window_start,
        wav_path.name,
        whisper_cfg.model_size,
    )
    local_result = _run_whisper(window_clip_path, whisper_cfg)

    words = [Word(word=w.word, start=w.start + window_start, end=w.end + window_start) for w in local_result.words]
    result = TranscriptResult(words=words, full_text=local_result.full_text)

    _save_cache(cache_file, result)
    return result
