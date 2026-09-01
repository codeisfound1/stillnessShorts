"""Ghép 1 short hoàn chỉnh: video đã crop/scale/burn-sub (câm) + audio (narration [+ nhạc nền]).

Mux bước cuối dùng -c copy (không encode lại) vì cả 2 nhánh video/audio đã ở đúng
codec đích, giúp bước cuối rất nhanh.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

from . import audio_cutter, photo_cutter, subtitles, video_cutter
from .audio_cutter import AudioSegment
from .config import AppConfig
from .photo_cutter import PhotoSlot
from .transcriber import TranscriptResult
from .utils.ffmpeg_utils import run
from .video_cutter import VideoSegment

logger = logging.getLogger(__name__)

VisualInput = Union[VideoSegment, list[PhotoSlot]]


def compose_short(
    *,
    index: int,
    visual: VisualInput,
    audio_segment: AudioSegment,
    transcript_slice: TranscriptResult,
    narration_wav_cache: Path,
    config: AppConfig,
) -> Path:
    """Tạo 1 file short hoàn chỉnh (mp4, 9:16, có sub, có audio) và trả về đường dẫn output.

    `visual` là VideoSegment (mode "video", cắt từ nguồn dài) hoặc list[PhotoSlot]
    (mode "photos", dựng slideshow Ken Burns từ nhiều ảnh).
    """
    work_dir = config.output.work_dir
    output_dir = config.output.dir
    output_dir.mkdir(parents=True, exist_ok=True)

    short_tag = f"short_{index:03d}"
    ass_path = work_dir / f"{short_tag}.ass"
    silent_video_path = work_dir / f"{short_tag}_video.mp4"
    narration_clip_path = work_dir / f"{short_tag}_narration.wav"
    mixed_audio_path = work_dir / f"{short_tag}_audio.m4a"
    final_output_path = output_dir / f"{short_tag}.mp4"

    duration = visual.duration if isinstance(visual, VideoSegment) else sum(slot.duration for slot in visual)

    captions = subtitles.build_captions(
        transcript_slice.words,
        segment_start=audio_segment.start,
        max_words_per_caption=config.subtitle.max_words_per_caption,
    )
    subtitles.write_ass_file(
        captions=captions,
        output_path=ass_path,
        subtitle_cfg=config.subtitle,
        play_res_x=config.video.width,
        play_res_y=config.video.height,
    )
    logger.info("Short #%d: %d cụm phụ đề.", index, len(captions))

    if isinstance(visual, VideoSegment):
        video_cutter.extract_processed_clip(
            video_path=config.input.video_path,
            segment=visual,
            ass_subtitle_path=ass_path,
            output_path=silent_video_path,
            video_cfg=config.video,
            fonts_dir=config.subtitle.font_path.parent,
        )
    else:
        photo_cutter.build_processed_clip(
            photo_slots=visual,
            ass_subtitle_path=ass_path,
            output_path=silent_video_path,
            video_cfg=config.video,
            photos_cfg=config.photos,
            work_dir=work_dir,
            fonts_dir=config.subtitle.font_path.parent,
        )

    audio_cutter.extract_narration_clip(narration_wav_cache, audio_segment, narration_clip_path)
    audio_cutter.build_mixed_audio(
        narration_clip_path=narration_clip_path,
        music_path=config.input.music_path,
        duration=duration,
        output_path=mixed_audio_path,
        mix_cfg=config.audio_mix,
        audio_bitrate=config.video.audio_bitrate,
    )

    logger.info("Short #%d: mux video + audio -> %s", index, final_output_path.name)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(silent_video_path),
        "-i",
        str(mixed_audio_path),
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-shortest",
        str(final_output_path),
    ]
    run(cmd, description=f"mux final {short_tag}")

    return final_output_path
