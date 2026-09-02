"""Sinh file phụ đề .ass (Advanced SubStation Alpha) khớp timestamp để burn-in vào video.

Dùng ASS thay vì SRT vì ASS hỗ trợ style chi tiết (font, cỡ chữ, màu, viền, nền mờ,
căn giữa màn hình) mà libass (ffmpeg -vf ass=) render trực tiếp, không cần ImageMagick.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import BrandingConfig, SubtitleConfig
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


def _escape_ass_text(text: str) -> str:
    """Escape ký tự có ý nghĩa đặc biệt trong ASS override block ({...})."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _build_branding_block(
    branding_cfg: BrandingConfig, *, clip_duration: float, play_res_x: int
) -> tuple[str, str]:
    """Style + Dialogue cho logo/tên kênh, hiển thị CỐ ĐỊNH suốt video (không theo timestamp).

    Trả về (styles, dialogues). Dùng \\an8\\pos(x,y) để định vị chính xác theo pixel, độc lập
    với Alignment/Margin của style - logo (ảnh, overlay riêng bằng ffmpeg) nằm trên cùng, rồi
    tới 2 dòng chữ ngay bên dưới logo, phía trên vị trí phụ đề (căn giữa màn hình).
    """
    if not branding_cfg.enabled or not (branding_cfg.channel_handle or branding_cfg.channel_name):
        return "", ""

    center_x = play_res_x // 2
    end_time = _format_ass_time(clip_duration)

    styles = (
        f"Style: BrandHandle,{branding_cfg.font_name},{branding_cfg.handle_font_size},"
        f"{branding_cfg.text_color},&H000000FF,{branding_cfg.outline_color},&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{branding_cfg.outline},{branding_cfg.shadow},8,60,60,0,1\n"
        f"Style: BrandName,{branding_cfg.font_name},{branding_cfg.name_font_size},"
        f"{branding_cfg.text_color},&H000000FF,{branding_cfg.outline_color},&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{branding_cfg.outline},{branding_cfg.shadow},8,60,60,0,1\n"
    )

    handle_y = branding_cfg.logo_top_y + branding_cfg.logo_height + branding_cfg.gap_after_logo
    name_y = handle_y + branding_cfg.line_spacing

    dialogues = ""
    if branding_cfg.channel_handle:
        text = _escape_ass_text(branding_cfg.channel_handle)
        dialogues += (
            f"Dialogue: 0,0:00:00.00,{end_time},BrandHandle,,0,0,0,,"
            f"{{\\an8\\pos({center_x},{handle_y})}}{text}\n"
        )
    if branding_cfg.channel_name:
        text = _escape_ass_text(branding_cfg.channel_name)
        dialogues += (
            f"Dialogue: 0,0:00:00.00,{end_time},BrandName,,0,0,0,,"
            f"{{\\an8\\pos({center_x},{name_y})}}{text}\n"
        )

    return styles, dialogues



def build_ass_filter_string(ass_subtitle_path: Path, fonts_dir: Path | None = None) -> str:
    """Trả về đoạn filter ffmpeg `ass='...'[:fontsdir='...']` dùng chung cho video_cutter/photo_cutter.

    fonts_dir trỏ tới thư mục font TTF bundle trong repo để libass không phụ thuộc font
    đã cài sẵn trên máy/CI chạy script.
    """
    escaped = str(ass_subtitle_path).replace("\\", "/").replace(":", "\\:")
    ass_filter = f"ass='{escaped}'"
    if fonts_dir is not None:
        escaped_fonts_dir = str(fonts_dir).replace("\\", "/").replace(":", "\\:")
        ass_filter += f":fontsdir='{escaped_fonts_dir}'"
    return ass_filter


def build_video_filter_graph(
    *,
    base_filter: Optional[str],
    ass_subtitle_path: Optional[Path],
    fonts_dir: Optional[Path] = None,
    logo_path: Optional[Path] = None,
    logo_height: int = 0,
    logo_top_y: int = 0,
) -> tuple[list[str], str, bool]:
    """Xây filter graph dùng chung cho video_cutter/photo_cutter: (base_filter) -> overlay logo
    (nếu có logo_path) -> burn phụ đề .ass (nếu có ass_subtitle_path).

    Trả về (extra_input_args, filter_string, use_filter_complex):
    - Không có logo: filter_string là chuỗi nối bằng dấu phẩy, dùng trực tiếp với `-vf`
      (use_filter_complex=False, extra_input_args rỗng).
    - Có logo: filter_string là filter_complex đầy đủ (input logo là index 1), cần thêm
      extra_input_args (`-loop 1 -i logo_path`) vào lệnh ffmpeg TRƯỚC `-filter_complex`,
      và dùng `-map "[out]"` thay vì `-vf` (use_filter_complex=True).
    """
    ass_filter = build_ass_filter_string(ass_subtitle_path, fonts_dir) if ass_subtitle_path is not None else None

    if logo_path is None:
        parts = [p for p in (base_filter, ass_filter) if p]
        return [], ",".join(parts), False

    stages: list[str] = []
    current = "[0:v]"
    if base_filter:
        stages.append(f"{current}{base_filter}[base]")
        current = "[base]"

    stages.append(f"[1:v]scale=-1:{logo_height}[logo]")

    overlay_out = "out" if not ass_filter else "branded"
    # shortest=1: logo là input -loop 1 (vô hạn) - nếu không ép overlay dừng theo stream chính
    # (hữu hạn), ffmpeg sẽ chạy vô thời hạn vì input logo không bao giờ tự kết thúc.
    stages.append(f"{current}[logo]overlay=(main_w-overlay_w)/2:{logo_top_y}:shortest=1[{overlay_out}]")

    if ass_filter:
        stages.append(f"[{overlay_out}]{ass_filter}[out]")

    filter_complex = ";".join(stages)
    extra_inputs = ["-loop", "1", "-i", str(logo_path)]
    return extra_inputs, filter_complex, True


def write_ass_file(
    *,
    captions: list[Caption],
    output_path: Path,
    subtitle_cfg: SubtitleConfig,
    play_res_x: int,
    play_res_y: int,
    branding_cfg: Optional[BrandingConfig] = None,
    clip_duration: float = 0.0,
) -> Path:
    """Ghi file .ass: style caption (theo timestamp) + style/dialogue branding (cố định, tùy chọn)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    branding_styles, branding_dialogues = (
        _build_branding_block(branding_cfg, clip_duration=clip_duration, play_res_x=play_res_x)
        if branding_cfg is not None
        else ("", "")
    )

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
{branding_styles}
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header, branding_dialogues]
    for cap in captions:
        text = _wrap_text(cap.text, subtitle_cfg.max_chars_per_line)
        start = _format_ass_time(cap.start)
        end = _format_ass_time(cap.end)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    return output_path
