"""Dựng đoạn video cho 1 short từ nhiều ảnh tĩnh (mode "photos"), hiệu ứng Ken Burns.

Thay vì cắt từ 1 video gốc dài, mỗi short ghép tuần tự N ảnh chưa dùng (không trùng lặp
giữa các short nhờ photo_pointer_index trong state.json), mỗi ảnh hiển thị vài giây với
hiệu ứng zoom chậm (Ken Burns), rồi nối lại (concat) thành 1 đoạn video liền mạch, burn
phụ đề giống hệt mode video.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import PhotosConfig, VideoConfig
from .subtitles import build_video_filter_graph
from .utils.ffmpeg_utils import probe_resolution, run
from .video_cutter import build_crop_scale_filter

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Working canvas lớn hơn kích thước đích để zoompan có đủ "chi tiết" mà zoom vào,
# tránh ảnh bị vỡ nét/mờ khi phóng to.
WORKING_SCALE = 2


@dataclass
class PhotoSlot:
    path: Path
    duration: float
    zoom_in: bool


def list_photos(photos_dir: Path) -> list[Path]:
    """Liệt kê ảnh trong thư mục, sắp xếp theo tên file để thứ tự dùng ổn định giữa các lần chạy."""
    if not photos_dir.exists():
        return []
    photos = [p for p in photos_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return sorted(photos, key=lambda p: p.name)


def plan_next_photos(
    *,
    photos: list[Path],
    pointer_index: int,
    target_duration: float,
    photos_cfg: PhotosConfig,
) -> tuple[list[PhotoSlot], int]:
    """Chọn các ảnh tiếp theo (chưa dùng) để lấp đầy khoảng target_duration giây.

    Trả về (danh sách PhotoSlot, pointer_index mới). Danh sách rỗng nếu đã dùng hết ảnh.
    Tổng duration của các slot trả về có thể lớn hơn hoặc nhỏ hơn target_duration một chút
    (nhỏ hơn nếu hết ảnh) - caller chịu trách nhiệm đồng bộ với độ dài audio.
    """
    slots: list[PhotoSlot] = []
    total = 0.0
    idx = pointer_index
    zoom_in = True

    while total < target_duration and idx < len(photos):
        duration = random.uniform(photos_cfg.seconds_per_photo_min, photos_cfg.seconds_per_photo_max)
        slots.append(PhotoSlot(path=photos[idx], duration=duration, zoom_in=zoom_in))
        total += duration
        idx += 1
        if photos_cfg.alternate_direction:
            zoom_in = not zoom_in

    return slots, idx


def trim_slots_to_duration(slots: list[PhotoSlot], target_duration: float) -> list[PhotoSlot]:
    """Cắt bớt/rút ngắn slot cuối để tổng duration khớp chính xác target_duration.

    Không bao giờ bỏ hẳn 1 ảnh đã "tiêu thụ" khỏi pointer - chỉ rút ngắn thời lượng hiển
    thị của nó trong video, pointer vẫn coi như đã dùng ảnh đó.
    """
    trimmed: list[PhotoSlot] = []
    remaining = target_duration
    for slot in slots:
        if remaining <= 0:
            break
        used = min(slot.duration, remaining)
        trimmed.append(PhotoSlot(path=slot.path, duration=used, zoom_in=slot.zoom_in))
        remaining -= used
    return trimmed


def _build_zoompan_filter(*, duration: float, zoom_in: bool, zoom_max: float, width: int, height: int, fps: int) -> str:
    frames = max(int(round(duration * fps)), 1)
    increment = (zoom_max - 1.0) / frames

    if zoom_in:
        z_expr = f"min(zoom+{increment:.8f},{zoom_max:.4f})"
    else:
        z_expr = f"if(eq(on,0),{zoom_max:.4f},max(zoom-{increment:.8f},1.0))"

    x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"

    return f"zoompan=z='{z_expr}':d=1:x='{x_expr}':y='{y_expr}':s={width}x{height}:fps={fps}"


def _render_single_photo_clip(
    *,
    slot: PhotoSlot,
    output_path: Path,
    video_cfg: VideoConfig,
    photos_cfg: PhotosConfig,
) -> Path:
    src_w, src_h = probe_resolution(slot.path)
    working_w = video_cfg.width * WORKING_SCALE
    working_h = video_cfg.height * WORKING_SCALE
    crop_scale = build_crop_scale_filter(src_w, src_h, working_w, working_h)
    zoompan = _build_zoompan_filter(
        duration=slot.duration,
        zoom_in=slot.zoom_in,
        zoom_max=photos_cfg.zoom_max,
        width=video_cfg.width,
        height=video_cfg.height,
        fps=video_cfg.fps,
    )
    vf = f"{crop_scale},{zoompan}"

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(video_cfg.fps),
        "-i",
        str(slot.path),
        "-t",
        f"{slot.duration:.3f}",
        "-vf",
        vf,
        "-an",
        "-c:v",
        video_cfg.codec,
        "-preset",
        video_cfg.preset,
        "-crf",
        str(video_cfg.crf),
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    run(cmd, description=f"render Ken Burns clip {slot.path.name}")
    return output_path


def build_processed_clip(
    *,
    photo_slots: list[PhotoSlot],
    ass_subtitle_path: Optional[Path],
    output_path: Path,
    video_cfg: VideoConfig,
    photos_cfg: PhotosConfig,
    work_dir: Path,
    fonts_dir: Optional[Path] = None,
    logo_path: Optional[Path] = None,
    logo_height: int = 0,
    logo_top_y: int = 0,
) -> Path:
    """Render từng ảnh thành clip Ken Burns riêng, nối lại (concat), rồi burn phụ đề.

    Output có cùng "hình dạng" (silent, đã crop/scale 9:16, đã burn sub) như
    video_cutter.extract_processed_clip để video_composer dùng chung 1 pipeline mux phía sau.
    """
    if not photo_slots:
        raise ValueError("photo_slots rỗng, không có gì để dựng video.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    clip_dir = work_dir / f"{output_path.stem}_photoclips"
    clip_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: list[Path] = []
    for i, slot in enumerate(photo_slots):
        clip_path = clip_dir / f"clip_{i:03d}.mp4"
        logger.info("Render ảnh %d/%d (%.1fs, %s): %s", i + 1, len(photo_slots), slot.duration, "zoom-in" if slot.zoom_in else "zoom-out", slot.path.name)
        _render_single_photo_clip(slot=slot, output_path=clip_path, video_cfg=video_cfg, photos_cfg=photos_cfg)
        clip_paths.append(clip_path)

    concat_list_path = clip_dir / "concat_list.txt"
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            escaped = str(p.resolve()).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    extra_inputs, filter_str, use_filter_complex = build_video_filter_graph(
        base_filter=None,
        ass_subtitle_path=ass_subtitle_path,
        fonts_dir=fonts_dir,
        logo_path=logo_path,
        logo_height=logo_height,
        logo_top_y=logo_top_y,
        speed_factor=video_cfg.speed_factor,
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        *extra_inputs,
    ]
    if filter_str:
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
    logger.info("Nối %d clip ảnh + burn phụ đề -> %s", len(clip_paths), output_path.name)
    run(cmd, description=f"concat + burn sub {output_path.name}")

    return output_path
