"""Entry point: tạo N YouTube Shorts từ 1 video gốc + 1 audio thuyết minh, upload + báo Telegram.

Chạy: python -m shorts_automation.main --count 5
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import traceback

from . import (
    audio_cutter,
    image_generator,
    image_prompt_generator,
    photo_cutter,
    title_generator,
    transcriber,
    video_composer,
    video_cutter,
)
from .config import AppConfig, load_config
from .state import StateStore
from .utils.ffmpeg_utils import FFmpegError, check_binaries_available
from .utils.logging_config import setup_logging
from .video_cutter import VideoSegment

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tự động tạo và đăng YouTube Shorts.")
    parser.add_argument("--config", default="config/config.yaml", help="Đường dẫn config.yaml")
    parser.add_argument("--env", default=".env", help="Đường dẫn file .env chứa secrets")
    parser.add_argument("--count", type=int, default=None, help="Số lượng short muốn tạo (override config)")
    parser.add_argument("--skip-upload", action="store_true", help="Chỉ tạo video local, không upload YouTube")
    parser.add_argument("--skip-telegram", action="store_true", help="Không gửi thông báo Telegram")
    parser.add_argument("--force-retranscribe", action="store_true", help="Bỏ qua cache transcript, chạy lại Whisper")
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    return parser.parse_args(argv)


def validate_inputs(config: AppConfig) -> None:
    if config.input.mode == "photos":
        if config.photos.source in ("folder", "mix"):
            if not config.photos.photos_dir:
                raise FileNotFoundError(
                    f"photos.source = '{config.photos.source}' nhưng chưa cấu hình photos.photos_dir."
                )
            photos_found = photo_cutter.list_photos(config.photos.photos_dir)
            if config.photos.source == "folder" and not photos_found:
                raise FileNotFoundError(f"Không tìm thấy ảnh nào trong thư mục: {config.photos.photos_dir}")
            if config.photos.source == "mix" and not photos_found:
                logger.warning(
                    "photos.source = 'mix' nhưng không tìm thấy ảnh nào trong %s -> mọi short sẽ dùng AI.",
                    config.photos.photos_dir,
                )
        # source == "ai_generated": không cần ảnh có sẵn, ảnh được sinh tự động mỗi short.
    else:
        if not config.input.video_path or not config.input.video_path.exists():
            raise FileNotFoundError(f"Không tìm thấy video input: {config.input.video_path}")

    if not config.input.narration_path.exists():
        raise FileNotFoundError(f"Không tìm thấy audio narration input: {config.input.narration_path}")
    if not audio_cutter.list_narration_files(config.input.narration_path):
        raise FileNotFoundError(
            f"narration_path là thư mục nhưng không chứa file .mp3 nào: {config.input.narration_path}"
        )
    if config.input.music_path is not None and not config.input.music_path.exists():
        logger.warning("music_path được cấu hình nhưng không tồn tại: %s -> bỏ qua nhạc nền.", config.input.music_path)
        config.input.music_path = None

    if config.branding.enabled and (
        not config.branding.logo_path or not config.branding.logo_path.exists()
    ):
        logger.warning(
            "branding.enabled=true nhưng không tìm thấy logo tại %s -> bỏ qua overlay logo (vẫn hiển thị tên kênh).",
            config.branding.logo_path,
        )
        config.branding.logo_path = None


YOUTUBE_DESCRIPTION_MAX_LENGTH = 5000


def build_description(title: str, transcript_text: str, hashtags: list[str]) -> str:
    """Mô tả video = tiêu đề + toàn bộ nội dung transcript của đoạn mp3 dùng cho short này
    + hashtag (tăng độ nhận diện & SEO).

    Chỉ cắt bớt nếu vượt quá giới hạn 5000 ký tự của YouTube (rất hiếm với 1 đoạn 30-60s).
    """
    full_text = transcript_text.strip()
    parts = [title]
    if full_text:
        parts.append(full_text)
    if hashtags:
        parts.append(" ".join(hashtags))
    description = "\n\n".join(parts)

    if len(description) > YOUTUBE_DESCRIPTION_MAX_LENGTH:
        description = description[: YOUTUBE_DESCRIPTION_MAX_LENGTH - 1].rstrip() + "…"
    return description


YOUTUBE_TITLE_MAX_LENGTH = 100


def build_video_title(title: str, short_index: int, channel_name: str) -> str:
    """Tiêu đề YouTube = tiêu đề AI sinh + số thứ tự short + tên kênh, đặt ở CUỐI tiêu đề.

    Số thứ tự + tên kênh luôn được giữ nguyên vẹn; nếu tổng vượt quá giới hạn 100 ký tự của
    YouTube thì cắt bớt phần tiêu đề gốc (không bao giờ cắt phần số thứ tự/tên kênh).
    """
    suffix_parts = [f"#{short_index}"]
    if channel_name:
        suffix_parts.append(channel_name)
    suffix = " | " + " ".join(suffix_parts)

    base = title.strip()
    available = YOUTUBE_TITLE_MAX_LENGTH - len(suffix)
    if len(base) > available:
        base = base[: max(available - 1, 0)].rstrip() + "…"
    return f"{base}{suffix}"


def run(args: argparse.Namespace) -> int:
    setup_logging(args.log_level)
    logger.info("Bắt đầu stillnessShorts.")

    try:
        check_binaries_available()
        config = load_config(args.config, args.env)
        validate_inputs(config)
    except (FileNotFoundError, FFmpegError) as e:
        logger.error("Lỗi cấu hình/input: %s", e)
        return 1

    if args.skip_telegram:
        config.telegram.enabled = False

    target_count = args.count if args.count is not None else config.generation.count
    if target_count <= 0:
        logger.error("--count phải > 0.")
        return 1

    from . import telegram_notifier

    photos_mode = config.input.mode == "photos"
    photos_source = config.photos.source if photos_mode else None
    uses_folder = photos_source in ("folder", "mix")
    photos_list: list = []
    video_duration = 0.0

    if photos_mode and uses_folder:
        photos_list = photo_cutter.list_photos(config.photos.photos_dir)
        logger.info("Mode photos (%s): %d ảnh trong %s", photos_source, len(photos_list), config.photos.photos_dir)
        if photos_source == "mix":
            logger.info(
                "Mix: %.0f%% khả năng dùng ảnh có sẵn cho mỗi short, tự động chuyển sang AI khi hết ảnh.",
                config.photos.mix_folder_ratio * 100,
            )
        source_identifier = config.photos.photos_dir
    elif photos_mode:
        logger.info(
            "Mode photos (ai_generated): mỗi short tự sinh 1 ảnh bằng AI (provider=%s).",
            config.image_generation.provider,
        )
        # Không có thư mục ảnh cố định để làm định danh nguồn -> dùng 1 sentinel path riêng
        # (khác narration_path) để state.json vẫn phân biệt được theo cặp (nguồn, narration).
        source_identifier = config.output.work_dir / "__ai_generated_photos__"
    else:
        video_duration = video_cutter.get_video_duration(config.input.video_path)
        logger.info("Video gốc: %.1fs", video_duration)
        source_identifier = config.input.video_path

    # ensure_wav_cache tự ghép nhiều file .mp3 (nếu narration_path là thư mục) theo thứ tự tên
    # file thành 1 timeline liên tục - audio_duration lấy trên chính WAV cache này để đúng cho
    # cả trường hợp 1 file lẫn nhiều file.
    narration_wav_cache = audio_cutter.ensure_wav_cache(config.input.narration_path, config.output.work_dir)
    audio_duration = audio_cutter.get_audio_duration(narration_wav_cache)
    logger.info("Audio thuyết minh: %.1fs", audio_duration)

    state_store = StateStore(config.output.state_file)
    source_key, source_state = state_store.get_source_state(source_identifier, config.input.narration_path)

    # Chỉ transcribe đúng đoạn audio đợt này sẽ dùng tới (tổng thời lượng tối đa của target_count
    # short, tính từ vị trí pointer hiện tại) thay vì toàn bộ file narration - nhanh hơn nhiều
    # với narration dài khi mỗi đợt chỉ tạo vài short.
    window_start = source_state.audio_pointer_sec
    window_end = min(window_start + target_count * config.generation.max_duration_sec, audio_duration)
    transcript = transcriber.transcribe_narration_window(
        wav_path=narration_wav_cache,
        work_dir=config.output.work_dir,
        whisper_cfg=config.whisper,
        window_start=window_start,
        window_end=window_end,
        force=args.force_retranscribe,
    )

    succeeded = 0
    failed = 0
    attempted = 0

    for _ in range(target_count):
        attempted += 1
        duration_sec = random.uniform(config.generation.min_duration_sec, config.generation.max_duration_sec)

        photo_start_index: int | None = None
        photo_end_index: int | None = None
        visual = None
        use_ai_this_short = False

        if photos_mode:
            if photos_source == "ai_generated":
                use_ai_this_short = True
            elif photos_source == "mix":
                folder_has_photos_left = source_state.photo_pointer_index < len(photos_list)
                if folder_has_photos_left:
                    # Bộ đếm dồn (kiểu Bresenham) thay vì random độc lập mỗi short: đảm bảo tỉ
                    # lệ folder/AI hội tụ đúng mix_folder_ratio ngay cả khi mỗi đợt chỉ chạy 1-2
                    # short, thay vì có thể "trật" AI nhiều lần liên tiếp do random không may.
                    source_state.mix_credit += config.photos.mix_folder_ratio
                    if source_state.mix_credit >= 1.0:
                        source_state.mix_credit -= 1.0
                        use_ai_this_short = False
                    else:
                        use_ai_this_short = True
                else:
                    use_ai_this_short = True
            # photos_source == "folder": use_ai_this_short giữ nguyên False.

        if photos_mode and use_ai_this_short:
            audio_seg = audio_cutter.plan_next_segment(
                audio_duration=audio_duration,
                pointer_sec=source_state.audio_pointer_sec,
                duration_sec=duration_sec,
            )
            if audio_seg is None:
                logger.warning("Đã hết audio thuyết minh, dừng sớm.")
                if not config.generation.stop_if_exhausted:
                    logger.error("stop_if_exhausted=false nhưng không còn nội dung, dừng script.")
                break

            sync_duration = audio_seg.duration
            if sync_duration < 5:
                logger.warning("Đoạn còn lại quá ngắn (%.1fs), dừng.", sync_duration)
                break

            # visual (ảnh AI) chỉ được sinh trong try block bên dưới vì cần title/transcript trước.
            visual_log = "photos[ai_generated]"
            source_state.audio_pointer_sec = audio_seg.end
        elif photos_mode:
            photo_slots, new_photo_pointer = photo_cutter.plan_next_photos(
                photos=photos_list,
                pointer_index=source_state.photo_pointer_index,
                target_duration=duration_sec,
                photos_cfg=config.photos,
            )
            audio_seg = audio_cutter.plan_next_segment(
                audio_duration=audio_duration,
                pointer_sec=source_state.audio_pointer_sec,
                duration_sec=duration_sec,
            )
            if not photo_slots or audio_seg is None:
                logger.warning("Đã hết ảnh hoặc audio để tạo thêm short không trùng lặp, dừng sớm.")
                if not config.generation.stop_if_exhausted:
                    logger.error("stop_if_exhausted=false nhưng không còn nội dung, dừng script.")
                break

            total_photo_duration = sum(slot.duration for slot in photo_slots)
            sync_duration = min(total_photo_duration, audio_seg.duration)
            if sync_duration < 5:
                logger.warning("Đoạn còn lại quá ngắn (%.1fs), dừng.", sync_duration)
                break

            visual = photo_cutter.trim_slots_to_duration(photo_slots, sync_duration)
            audio_seg.end = audio_seg.start + sync_duration
            photo_start_index = source_state.photo_pointer_index
            photo_end_index = new_photo_pointer
            visual_log = f"photos[{photo_start_index}-{photo_end_index}]"

            source_state.photo_pointer_index = new_photo_pointer
            source_state.audio_pointer_sec = audio_seg.end
        else:
            video_seg = video_cutter.plan_next_segment(
                video_duration=video_duration,
                pointer_sec=source_state.video_pointer_sec,
                duration_sec=duration_sec,
            )
            audio_seg = audio_cutter.plan_next_segment(
                audio_duration=audio_duration,
                pointer_sec=source_state.audio_pointer_sec,
                duration_sec=duration_sec,
            )
            if video_seg is None or audio_seg is None:
                logger.warning("Đã hết video hoặc audio để cắt thêm short không trùng lặp, dừng sớm.")
                if not config.generation.stop_if_exhausted:
                    logger.error("stop_if_exhausted=false nhưng không còn nội dung, dừng script.")
                break

            sync_duration = min(video_seg.duration, audio_seg.duration)
            if sync_duration < 5:
                logger.warning("Đoạn còn lại quá ngắn (%.1fs), dừng.", sync_duration)
                break

            video_seg.end = video_seg.start + sync_duration
            audio_seg.end = audio_seg.start + sync_duration
            visual = video_seg
            visual_log = f"video[{video_seg.start:.1f}-{video_seg.end:.1f}]"

            source_state.video_pointer_sec = video_seg.end
            source_state.audio_pointer_sec = audio_seg.end

        # Đánh dấu đoạn này đã "dùng" ngay để lần chạy sau (kể cả nếu bước dưới lỗi)
        # không lấy lại đúng đoạn/ảnh này nữa.
        state_store.update_source_state(source_key, source_state)
        state_store.save()

        short_index = state_store.next_short_index(source_state)
        logger.info(
            "=== Short #%d: %s audio[%.1f-%.1f] (%.1fs) ===",
            short_index,
            visual_log,
            audio_seg.start,
            audio_seg.end,
            sync_duration,
        )

        image_prompt: str | None = None

        try:
            transcript_slice = transcript.slice(audio_seg.start, audio_seg.end)
            transcript_text = transcript_slice.full_text or f"Đoạn video số {short_index}"

            title = title_generator.generate_title(transcript_text, config.llm)

            if photos_mode and use_ai_this_short:
                image_prompt = image_prompt_generator.generate_image_prompt(transcript_text, title, config.llm)
                photo_path = image_generator.generate_photo(
                    prompt=image_prompt,
                    output_path=config.output.work_dir / f"short_{short_index:03d}_ai_photo.jpg",
                    image_cfg=config.image_generation,
                    width=config.video.width,
                    height=config.video.height,
                )
                visual = [photo_cutter.PhotoSlot(path=photo_path, duration=sync_duration, zoom_in=short_index % 2 == 1)]
                logger.info("Short #%d: ảnh AI (prompt: %s)", short_index, image_prompt)

            output_path = video_composer.compose_short(
                index=short_index,
                visual=visual,
                audio_segment=audio_seg,
                transcript_slice=transcript_slice,
                narration_wav_cache=narration_wav_cache,
                config=config,
            )
            logger.info("Short #%d đã tạo xong: %s", short_index, output_path)

            youtube_title = build_video_title(title, short_index, config.branding.channel_name)

            youtube_video_id = None
            youtube_url = None
            if not args.skip_upload:
                from . import youtube_uploader

                description = build_description(title, transcript_text, config.youtube.description_hashtags)
                youtube_video_id = youtube_uploader.upload_and_add_to_playlist(
                    video_path=output_path,
                    title=youtube_title,
                    description=description,
                    youtube_cfg=config.youtube,
                )
                youtube_url = youtube_uploader.video_url(youtube_video_id)

            state_store.record_short(
                source_key,
                source_state,
                audio_start=audio_seg.start,
                audio_end=audio_seg.end,
                title=title,
                output_file=str(output_path),
                video_start=visual.start if isinstance(visual, VideoSegment) else None,
                video_end=visual.end if isinstance(visual, VideoSegment) else None,
                photo_start_index=photo_start_index,
                photo_end_index=photo_end_index,
                image_prompt=image_prompt,
                youtube_video_id=youtube_video_id,
                youtube_url=youtube_url,
                uploaded=youtube_video_id is not None,
            )

            if youtube_url:
                telegram_notifier.notify_short_uploaded(
                    title=youtube_title, youtube_url=youtube_url, index=short_index, telegram_cfg=config.telegram
                )

            succeeded += 1

        except Exception as e:  # noqa: BLE001 - không muốn 1 short lỗi làm dừng cả batch
            logger.error("Short #%d thất bại: %s", short_index, e)
            logger.debug(traceback.format_exc())
            telegram_notifier.notify_short_failed(index=short_index, error=str(e), telegram_cfg=config.telegram)
            failed += 1
            continue

    logger.info("Hoàn tất: %d/%d short thành công, %d thất bại.", succeeded, attempted, failed)

    return 0 if failed == 0 else 2


def main() -> None:
    args = parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
