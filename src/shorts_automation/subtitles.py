"""Sinh file phụ đề .ass (Advanced SubStation Alpha) khớp timestamp để burn-in vào video.

Dùng ASS thay vì SRT vì ASS hỗ trợ style chi tiết (font, cỡ chữ, màu, viền, nền mờ,
căn giữa màn hình) mà libass (ffmpeg -vf ass=) render trực tiếp, không cần ImageMagick.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import SubtitleConfig
from .transcriber import Word


@dataclass
class Caption:
    start: float
    end: float
    text: str


def _wrap_text(text: str, max_chars_per_line: int) -> str:
    """Ngắt dòng đơn giản theo số ký tự tối đa mỗi dòng, giữ nguyên từ (không cắt giữa từ)."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".strip()
        if len(candidate) > max_chars_per_line and current:
            lines.append(current)
            current = w
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\\N".join(lines)


def build_captions(words: list[Word], *, segment_start: float, max_words_per_caption: int) -> list[Caption]:
    """Gom các từ (đã có timestamp tuyệt đối) thành từng cụm phụ đề, thời gian tính từ đầu segment.

    Mỗi cụm hiển thị đồng thời tối đa max_words_per_caption từ, giúp dễ đọc trên mobile
    thay vì hiện nguyên câu dài hoặc nhấp nháy từng từ một.
    """
    captions: list[Caption] = []
    chunk: list[Word] = []

    def flush():
        if not chunk:
            return
        text = " ".join(w.word.strip() for w in chunk).strip()
        if not text:
            return
        start = chunk[0].start - segment_start
        end = chunk[-1].end - segment_start
        captions.append(Caption(start=max(start, 0.0), end=max(end, start + 0.1), text=text))

    for w in words:
        chunk.append(w)
        if len(chunk) >= max_words_per_caption:
            flush()
            chunk = []
    flush()

    return captions


def _format_ass_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis == 100:
        centis = 0
        secs += 1
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def write_ass_file(
    *,
    captions: list[Caption],
    output_path: Path,
    subtitle_cfg: SubtitleConfig,
    play_res_x: int,
    play_res_y: int,
) -> Path:
    """Ghi file .ass với 1 style duy nhất áp dụng cho toàn bộ caption, căn giữa màn hình."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    header = f"""[Script Info]
Title: stillnessShorts auto subtitle
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{subtitle_cfg.font_name},{subtitle_cfg.font_size},{subtitle_cfg.primary_color},&H000000FF,{subtitle_cfg.outline_color},{subtitle_cfg.back_color},-1,0,0,0,100,100,0,0,3,{subtitle_cfg.outline},{subtitle_cfg.shadow},{subtitle_cfg.alignment},60,60,{subtitle_cfg.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for cap in captions:
        text = _wrap_text(cap.text, subtitle_cfg.max_chars_per_line)
        start = _format_ass_time(cap.start)
        end = _format_ass_time(cap.end)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    return output_path
