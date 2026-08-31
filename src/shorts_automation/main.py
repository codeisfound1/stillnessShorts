"""Entry point: tạo N YouTube Shorts từ 1 video gốc + 1 audio thuyết minh, upload + báo Telegram.

Chạy: python -m shorts_automation.main --count 5
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import traceback

from . import audio_cutter, title_generator, transcriber, video_composer, video_cutter
from .config import AppConfig, load_config
from .state import StateStore
from .utils.ffmpeg_utils import FFmpegError, check_binaries_available
from .utils.logging_config import setup_logging

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
    if not config.input.video_path.exists():
        raise FileNotFoundError(f"Không tìm thấy video input: {config.input.video_path}")
    if not config.input.narration_path.exists():
        raise FileNotFoundError(f"Không tìm thấy audio narration input: {config.input.narration_path}")
    if config.input.music_path is not None and not config.input.music_path.exists():
        logger.warning("music_path được cấu hình nhưng không tồn tại: %s -> bỏ qua nhạc nền.", config.input.music_path)
        config.input.music_path = None


def build_description(title: str, transcript_text: str) -> str:
    snippet = transcript_text.strip()
    if len(snippet) > 400:
        snippet = snippet[:400].rstrip() + "…"
    parts = [title]
    if snippet:
        parts.append(snippet)
    parts.append("#shorts")
    return "\n\n".join(parts)


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

    video_duration = video_cutter.get_video_duration(config.input.video_path)
    audio_duration = audio_cutter.get_audio_duration(config.input.narration_path)
    logger.info("Video gốc: %.1fs | Audio thuyết minh: %.1fs", video_duration, audio_duration)

    narration_wav_cache = audio_cutter.ensure_wav_cache(config.input.narration_path, config.output.work_dir)
    transcript = transcriber.transcribe_narration(
        wav_path=narration_wav_cache,
        work_dir=config.output.work_dir,
        whisper_cfg=config.whisper,
        force=args.force_retranscribe,
    )

    state_store = StateStore(config.output.state_file)
    source_key, source_state = state_store.get_source_state(config.input.video_path, config.input.narration_path)

    succeeded = 0
    failed = 0
    attempted = 0

    for _ in range(target_count):
        attempted += 1
        duration_sec = random.uniform(config.generation.min_duration_sec, config.generation.max_duration_sec)

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

        # Đánh dấu đoạn này đã "dùng" ngay để lần chạy sau (kể cả nếu bước dưới lỗi)
        # không lấy lại đúng đoạn này nữa.
        source_state.video_pointer_sec = video_seg.end
        source_state.audio_pointer_sec = audio_seg.end
        state_store.update_source_state(source_key, source_state)
        state_store.save()

        short_index = state_store.next_short_index(source_state)
        logger.info(
            "=== Short #%d: video[%.1f-%.1f] audio[%.1f-%.1f] (%.1fs) ===",
            short_index,
            video_seg.start,
            video_seg.end,
            audio_seg.start,
            audio_seg.end,
            sync_duration,
        )

        try:
            transcript_slice = transcript.slice(audio_seg.start, audio_seg.end)
            transcript_text = transcript_slice.full_text or f"Đoạn video số {short_index}"

            title = title_generator.generate_title(transcript_text, config.llm)

            output_path = video_composer.compose_short(
                index=short_index,
                video_segment=video_seg,
                audio_segment=audio_seg,
                transcript_slice=transcript_slice,
                narration_wav_cache=narration_wav_cache,
                config=config,
            )
            logger.info("Short #%d đã tạo xong: %s", short_index, output_path)

            youtube_video_id = None
            youtube_url = None
            if not args.skip_upload:
                from . import youtube_uploader

                description = build_description(title, transcript_text)
                youtube_video_id = youtube_uploader.upload_and_add_to_playlist(
                    video_path=output_path,
                    title=title,
                    description=description,
                    youtube_cfg=config.youtube,
                )
                youtube_url = youtube_uploader.video_url(youtube_video_id)

            state_store.record_short(
                source_key,
                source_state,
                video_start=video_seg.start,
                video_end=video_seg.end,
                audio_start=audio_seg.start,
                audio_end=audio_seg.end,
                title=title,
                output_file=str(output_path),
                youtube_video_id=youtube_video_id,
                youtube_url=youtube_url,
                uploaded=youtube_video_id is not None,
            )

            if youtube_url:
                telegram_notifier.notify_short_uploaded(
                    title=title, youtube_url=youtube_url, index=short_index, telegram_cfg=config.telegram
                )

            succeeded += 1

        except Exception as e:  # noqa: BLE001 - không muốn 1 short lỗi làm dừng cả batch
            logger.error("Short #%d thất bại: %s", short_index, e)
            logger.debug(traceback.format_exc())
            telegram_notifier.notify_short_failed(index=short_index, error=str(e), telegram_cfg=config.telegram)
            failed += 1
            continue

    logger.info("Hoàn tất: %d/%d short thành công, %d thất bại.", succeeded, attempted, failed)
    telegram_notifier.notify_run_summary(
        total=attempted, succeeded=succeeded, failed=failed, telegram_cfg=config.telegram
    )

    return 0 if failed == 0 else 2


def main() -> None:
    args = parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
