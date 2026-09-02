"""Chọn và cắt các đoạn video nguồn thành clip 9:16, không trùng lặp giữa các short.

Việc chọn đoạn (planning) tách biệt với việc cắt thực tế (ffmpeg) để dễ test và
để state.py có thể ghi nhận lại (video_start, video_end) trước khi tốn thời gian encode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import VideoConfig
from .subtitles import build_video_filter_graph
from .utils.ffmpeg_utils import probe_duration, probe_resolution, run

logger = logging.getLogger(__name__)


@dataclass
class VideoSegment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def plan_next_segment(
    *,
    video_duration: float,
    pointer_sec: float,
    duration_sec: float,
) -> Optional[VideoSegment]:
    """Trả về đoạn video tiếp theo bắt đầu từ pointer_sec, dài duration_sec giây.

    Trả về None nếu không còn đủ video (đã dùng hết từ pointer trở đi).
    Không bao giờ trả về đoạn chồng lấn với các đoạn trước đó vì luôn bắt đầu từ pointer.
    """
    if pointer_sec >= video_duration:
        return None
    end = min(pointer_sec + duration_sec, video_duration)
    if end - pointer_sec <= 0:
        return None
    return VideoSegment(start=pointer_sec, end=end)


def get_video_duration(video_path: Path) -> float:
    return probe_duration(video_path)


def build_crop_scale_filter(src_width: int, src_height: int, target_width: int, target_height: int) -> str:
    """Trả về ffmpeg filter string crop-center + scale để đưa video về đúng tỉ lệ 9:16.

    Nếu video nguồn không đúng tỉ lệ target, crop phần thừa ở giữa (giữ trọng tâm khung hình)
    trước khi scale, tránh bị méo hình.
    """
    target_ratio = target_width / target_height
    src_ratio = src_width / src_height

    if abs(src_ratio - target_ratio) < 1e-3:
        crop = f"crop={src_width}:{src_height}"
    elif src_ratio > target_ratio:
        # Video nguồn rộng hơn tỉ lệ đích -> crop 2 bên trái/phải.
        new_width = int(round(src_height * target_ratio))
        new_width -= new_width % 2
        crop = f"crop={new_width}:{src_height}:(in_w-{new_width})/2:0"
    else:
        # Video nguồn cao hơn (hẹp hơn) tỉ lệ đích -> crop trên/dưới.
        new_height = int(round(src_width / target_ratio))
        new_height -= new_height % 2
        crop = f"crop={src_width}:{new_height}:0:(in_h-{new_height})/2"

    return f"{crop},scale={target_width}:{target_height}:flags=lanczos,setsar=1"


def extract_processed_clip(
    *,
    video_path: Path,
    segment: VideoSegment,
    ass_subtitle_path: Optional[Path],
    output_path: Path,
    video_cfg: VideoConfig,
    fonts_dir: Optional[Path] = None,
    logo_path: Optional[Path] = None,
    logo_height: int = 0,
    logo_top_y: int = 0,
) -> Path:
    """Cắt đoạn [segment.start, segment.end], crop/scale về 9:16, overlay logo (nếu có),
    burn phụ đề (nếu có), mute audio gốc.

    Dùng -ss/-t trước -i (input option): với transcode (không phải -c copy), ffmpeg vẫn seek
    chính xác tới từng frame nên vừa nhanh vừa đúng thời điểm, kể cả khi thêm input logo thứ 2.

    fonts_dir: thư mục chứa font TTF bundle trong repo, truyền vào libass qua fontsdir=
    để không phụ thuộc font đã cài sẵn trên máy/CI chạy script.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    src_w, src_h = probe_resolution(video_path)
    crop_scale = build_crop_scale_filter(src_w, src_h, video_cfg.width, video_cfg.height)

    extra_inputs, filter_str, use_filter_complex = build_video_filter_graph(
        base_filter=crop_scale,
        ass_subtitle_path=ass_subtitle_path,
        fonts_dir=fonts_dir,
        logo_path=logo_path,
        logo_height=logo_height,
        logo_top_y=logo_top_y,
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{segment.start:.3f}",
        "-t",
        f"{segment.duration:.3f}",
        "-i",
        str(video_path),
        *extra_inputs,
    ]
    if use_filter_complex:
        cmd += ["-filter_complex", filter_str, "-map", "[out]"]
    else:
        cmd += ["-vf", filter_str]
    cmd += [
        "-an",
        "-r",
        str(video_cfg.fps),
        "-c:v",
        video_cfg.codec,
        "-preset",
        video_cfg.preset,
        "-crf",
        str(video_cfg.crf),
        "-b:v",
        video_cfg.video_bitrate,
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    logger.info(
        "Cắt video [%.2fs -> %.2fs] (%.2fs) từ %s", segment.start, segment.end, segment.duration, video_path.name
    )
    run(cmd, description=f"trích xuất clip video {output_path.name}")
    return output_path
