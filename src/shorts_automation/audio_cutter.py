"""Chọn và cắt các đoạn audio thuyết minh (mp3), trộn với nhạc nền tùy chọn.

Để đảm bảo timestamp phụ đề (lấy từ Whisper chạy trên toàn bộ file thuyết minh) khớp
chính xác với đoạn audio thực tế dùng cho short, ta convert file mp3 gốc sang 1 file
WAV PCM cache duy nhất (không mất mát, seek chính xác tuyệt đối), rồi cắt từ file WAV đó.

input.narration_path có thể là 1 file .mp3 duy nhất, HOẶC 1 thư mục chứa nhiều file .mp3 -
khi đó các file được ghép nối tuần tự theo tên file (sắp xếp alphabet) thành 1 timeline
audio liên tục duy nhất trước khi cache ra WAV, để toàn bộ logic pointer/transcribe/cắt
đoạn phía sau không cần biết gì về việc có nhiều file nguồn.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import AudioMixConfig
from .utils.ffmpeg_utils import probe_duration, run

logger = logging.getLogger(__name__)

WAV_SAMPLE_RATE = 44100


@dataclass
class AudioSegment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def get_audio_duration(audio_path: Path) -> float:
    return probe_duration(audio_path)


def plan_next_segment(
    *,
    audio_duration: float,
    pointer_sec: float,
    duration_sec: float,
) -> Optional[AudioSegment]:
    """Trả về đoạn audio thuyết minh tiếp theo, tương tự video_cutter.plan_next_segment."""
    if pointer_sec >= audio_duration:
        return None
    end = min(pointer_sec + duration_sec, audio_duration)
    if end - pointer_sec <= 0:
        return None
    return AudioSegment(start=pointer_sec, end=end)


def list_narration_files(narration_path: Path) -> list[Path]:
    """Trả về danh sách file .mp3 nguồn, sắp xếp theo tên file (thứ tự dùng ổn định).

    narration_path là 1 file -> trả về [narration_path]. Là 1 thư mục -> liệt kê mọi file
    .mp3 trực tiếp trong đó, sắp xếp theo tên.
    """
    if narration_path.is_dir():
        return sorted(
            (p for p in narration_path.iterdir() if p.is_file() and p.suffix.lower() == ".mp3"),
            key=lambda p: p.name,
        )
    if narration_path.is_file():
        return [narration_path]
    return []


def ensure_wav_cache(narration_path: Path, work_dir: Path) -> Path:
    """Convert narration (1 file hoặc nhiều file .mp3 trong 1 thư mục) -> 1 WAV PCM cache
    duy nhất, tái sử dụng cho mọi lần cắt & Whisper.

    Nếu là nhiều file, ghép nối chúng theo đúng thứ tự tên file thành 1 timeline liên tục
    (dùng ffmpeg filter `concat`, decode đầy đủ nên không yêu cầu các file có cùng
    codec/sample rate).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    files = list_narration_files(narration_path)
    if not files:
        raise FileNotFoundError(f"Không tìm thấy file .mp3 nào trong: {narration_path}")

    base_name = narration_path.stem if narration_path.is_file() else narration_path.name
    cache_path = work_dir / f"{base_name}_cache.wav"
    if cache_path.exists():
        return cache_path

    if len(files) == 1:
        logger.info("Chuyển đổi %s sang WAV cache (chạy 1 lần)...", files[0].name)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(files[0]),
            "-ac",
            "1",
            "-ar",
            str(WAV_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(cache_path),
        ]
    else:
        logger.info("Ghép %d file mp3 theo thứ tự tên file thành 1 narration liên tục (chạy 1 lần):", len(files))
        for f in files:
            logger.info("  - %s", f.name)
        cmd = ["ffmpeg", "-y"]
        for f in files:
            cmd += ["-i", str(f)]
        concat_inputs = "".join(f"[{i}:a]" for i in range(len(files)))
        filter_complex = f"{concat_inputs}concat=n={len(files)}:v=0:a=1[out]"
        cmd += [
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-ac",
            "1",
            "-ar",
            str(WAV_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(cache_path),
        ]

    run(cmd, description="tạo WAV cache cho narration")
    return cache_path


def extract_narration_clip(wav_cache_path: Path, segment: AudioSegment, output_path: Path) -> Path:
    """Cắt chính xác đoạn narration [start, end] từ file WAV cache (sample-accurate)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{segment.start:.3f}",
        "-i",
        str(wav_cache_path),
        "-t",
        f"{segment.duration:.3f}",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    run(cmd, description=f"trích xuất narration {output_path.name}")
    return output_path


def _atempo_filter(speed_factor: float) -> str:
    """Trả về đoạn filter `atempo=...` (có thể nối chuỗi nhiều atempo nếu ngoài khoảng
    0.5-2.0 mà 1 atempo hỗ trợ), giữ nguyên cao độ giọng nói khi tăng/giảm tốc độ."""
    factor = speed_factor
    parts = []
    while factor > 2.0:
        parts.append("atempo=2.0")
        factor /= 2.0
    while factor < 0.5:
        parts.append("atempo=0.5")
        factor /= 0.5
    parts.append(f"atempo={factor:.6f}")
    return ",".join(parts)


def build_mixed_audio(
    *,
    narration_clip_path: Path,
    music_path: Optional[Path],
    duration: float,
    output_path: Path,
    mix_cfg: AudioMixConfig,
    audio_bitrate: str,
    speed_factor: float = 1.0,
) -> Path:
    """Encode audio cuối cùng cho 1 short: chỉ narration, hoặc narration + nhạc nền đã hạ volume.

    Nhạc nền được loop nếu ngắn hơn đoạn short, cắt đúng độ dài, fade in/out nhẹ,
    rồi trộn (amix) với narration ở volume thấp hơn để không lấn tiếng nói. Nếu
    speed_factor != 1.0, tăng/giảm tốc độ phát ở bước cuối (giữ nguyên cao độ giọng nói)
    để khớp với video đã tăng/giảm tốc cùng hệ số.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    apply_speed = abs(speed_factor - 1.0) > 1e-6
    final_duration = duration / speed_factor if apply_speed else duration

    if music_path is None or not music_path.exists():
        narration_filter = f"volume={mix_cfg.narration_volume}"
        if apply_speed:
            narration_filter += f",{_atempo_filter(speed_factor)}"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(narration_clip_path),
            "-filter:a",
            narration_filter,
            "-t",
            f"{final_duration:.3f}",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            str(output_path),
        ]
        run(cmd, description=f"encode audio (chỉ narration) {output_path.name}")
        return output_path

    fade_out_start = max(duration - mix_cfg.music_fade_sec, 0)
    music_filter = (
        f"volume={mix_cfg.music_volume},"
        f"afade=t=in:st=0:d={mix_cfg.music_fade_sec},"
        f"afade=t=out:st={fade_out_start:.3f}:d={mix_cfg.music_fade_sec}"
    )
    narration_filter = f"volume={mix_cfg.narration_volume}"

    mix_out_label = "mixed" if apply_speed else "out"
    filter_complex = (
        f"[0:a]{narration_filter}[narr];"
        f"[1:a]aloop=loop=-1:size=2147483647,atrim=0:{duration:.3f},{music_filter}[music];"
        f"[narr][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[{mix_out_label}]"
    )
    if apply_speed:
        filter_complex += f";[mixed]{_atempo_filter(speed_factor)}[out]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(narration_clip_path),
        "-i",
        str(music_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-t",
        f"{final_duration:.3f}",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        str(output_path),
    ]
    run(cmd, description=f"encode audio (narration + nhạc nền) {output_path.name}")
    return output_path
