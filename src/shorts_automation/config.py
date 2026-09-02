"""Load cấu hình từ config/config.yaml + biến môi trường (.env) thành 1 object AppConfig.

Quy ước:
- Giá trị không nhạy cảm (đường dẫn, số lượng, style...) nằm trong config.yaml.
- Secrets (API key, token, playlist id, chat id) nằm trong biến môi trường (.env),
  có thể override một số giá trị non-secret của config.yaml nếu cần (ví dụ playlist id).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class InputConfig:
    mode: str  # "video" | "photos"
    video_path: Optional[Path]
    narration_path: Path
    music_path: Optional[Path]


@dataclass
class OutputConfig:
    dir: Path
    work_dir: Path
    state_file: Path


@dataclass
class GenerationConfig:
    count: int
    min_duration_sec: float
    max_duration_sec: float
    stop_if_exhausted: bool


@dataclass
class VideoConfig:
    width: int
    height: int
    fps: int
    video_bitrate: str
    audio_bitrate: str
    crf: int
    codec: str
    preset: str
    speed_factor: float


@dataclass
class PhotosConfig:
    source: str  # "ai_generated" | "folder"
    photos_dir: Optional[Path]
    seconds_per_photo_min: float
    seconds_per_photo_max: float
    zoom_max: float
    alternate_direction: bool


@dataclass
class ImageGenConfig:
    provider: str  # "pollinations" | "openai"
    openai_model: str
    style_suffix: str
    timeout_sec: float
    openai_api_key: Optional[str] = None


@dataclass
class AudioMixConfig:
    music_volume: float
    narration_volume: float
    music_fade_sec: float


@dataclass
class WhisperConfig:
    model_size: str
    device: str
    compute_type: str
    language: str
    word_timestamps: bool


@dataclass
class SubtitleConfig:
    font_path: Path
    font_name: str
    font_size: int
    primary_color: str
    outline_color: str
    back_color: str
    outline: int
    shadow: int
    alignment: int
    margin_v: int
    max_chars_per_line: int
    max_words_per_caption: int


@dataclass
class BrandingConfig:
    enabled: bool
    logo_path: Optional[Path]
    logo_height: int
    logo_top_y: int
    gap_after_logo: int
    line_spacing: int
    channel_handle: str
    channel_name: str
    handle_font_size: int
    name_font_size: int
    font_path: Path
    font_name: str
    text_color: str
    outline_color: str
    outline: int
    shadow: int


@dataclass
class LLMConfig:
    provider: str
    groq_model: str
    claude_model: str
    max_title_length: int
    temperature: float
    groq_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None


@dataclass
class YouTubeConfig:
    playlist_id: str
    privacy_status: str
    category_id: str
    default_tags: list[str]
    made_for_kids: bool
    publish_delay_minutes: int
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    refresh_token: Optional[str] = None


@dataclass
class TelegramConfig:
    enabled: bool
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


@dataclass
class AppConfig:
    input: InputConfig
    output: OutputConfig
    generation: GenerationConfig
    video: VideoConfig
    photos: PhotosConfig
    image_generation: ImageGenConfig
    audio_mix: AudioMixConfig
    whisper: WhisperConfig
    subtitle: SubtitleConfig
    branding: BrandingConfig
    llm: LLMConfig
    youtube: YouTubeConfig
    telegram: TelegramConfig
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def _resolve(path_str: str | None) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def load_config(config_path: str | Path = "config/config.yaml", env_path: str | Path | None = ".env") -> AppConfig:
    """Đọc config.yaml + .env, trả về AppConfig đã typed và đường dẫn tuyệt đối."""
    if env_path is not None:
        env_file = _resolve(str(env_path))
        if env_file and env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)
        else:
            # Vẫn cho phép load biến môi trường đã set sẵn (ví dụ trong GitHub Actions).
            load_dotenv(override=False)

    cfg_file = _resolve(str(config_path))
    if not cfg_file or not cfg_file.exists():
        raise FileNotFoundError(f"Không tìm thấy file config: {cfg_file}")

    with open(cfg_file, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    input_raw = raw.get("input", {})
    music_path_raw = input_raw.get("music_path")
    music_path = _resolve(music_path_raw) if music_path_raw else None
    mode = str(input_raw.get("mode", "video")).lower()
    if mode not in ("video", "photos"):
        raise ValueError(f"input.mode phải là 'video' hoặc 'photos', nhận được: {mode!r}")

    input_cfg = InputConfig(
        mode=mode,
        video_path=_resolve(input_raw.get("video_path")),
        narration_path=_resolve(input_raw["narration_path"]),
        music_path=music_path,
    )

    output_cfg = OutputConfig(
        dir=_resolve(raw["output"]["dir"]),
        work_dir=_resolve(raw["output"]["work_dir"]),
        state_file=_resolve(raw["output"]["state_file"]),
    )

    gen_raw = raw.get("generation", {})
    generation_cfg = GenerationConfig(
        count=int(gen_raw.get("count", 5)),
        min_duration_sec=float(gen_raw.get("min_duration_sec", 30)),
        max_duration_sec=float(gen_raw.get("max_duration_sec", 60)),
        stop_if_exhausted=bool(gen_raw.get("stop_if_exhausted", True)),
    )

    video_raw = raw.get("video", {})
    video_cfg = VideoConfig(
        width=int(video_raw.get("width", 1080)),
        height=int(video_raw.get("height", 1920)),
        fps=int(video_raw.get("fps", 30)),
        video_bitrate=str(video_raw.get("video_bitrate", "6M")),
        audio_bitrate=str(video_raw.get("audio_bitrate", "192k")),
        crf=int(video_raw.get("crf", 20)),
        codec=str(video_raw.get("codec", "libx264")),
        preset=str(video_raw.get("preset", "medium")),
        speed_factor=float(video_raw.get("speed_factor", 1.25)),
    )

    photos_raw = raw.get("photos", {})
    photos_source = str(photos_raw.get("source", "ai_generated")).lower()
    if photos_source not in ("ai_generated", "folder"):
        raise ValueError(f"photos.source phải là 'ai_generated' hoặc 'folder', nhận được: {photos_source!r}")
    photos_cfg = PhotosConfig(
        source=photos_source,
        photos_dir=_resolve(photos_raw.get("photos_dir")),
        seconds_per_photo_min=float(photos_raw.get("seconds_per_photo_min", 3.0)),
        seconds_per_photo_max=float(photos_raw.get("seconds_per_photo_max", 6.0)),
        zoom_max=float(photos_raw.get("zoom_max", 1.15)),
        alternate_direction=bool(photos_raw.get("alternate_direction", True)),
    )

    imgen_raw = raw.get("image_generation", {})
    image_gen_cfg = ImageGenConfig(
        provider=str(imgen_raw.get("provider", "pollinations")).lower(),
        openai_model=str(imgen_raw.get("openai_model", "gpt-image-1")),
        style_suffix=str(imgen_raw.get("style_suffix", "")),
        timeout_sec=float(imgen_raw.get("timeout_sec", 60)),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
    )

    mix_raw = raw.get("audio_mix", {})
    audio_mix_cfg = AudioMixConfig(
        music_volume=float(mix_raw.get("music_volume", 0.15)),
        narration_volume=float(mix_raw.get("narration_volume", 1.0)),
        music_fade_sec=float(mix_raw.get("music_fade_sec", 1.5)),
    )

    whisper_raw = raw.get("whisper", {})
    whisper_cfg = WhisperConfig(
        model_size=str(whisper_raw.get("model_size", "medium")),
        device=str(whisper_raw.get("device", "auto")),
        compute_type=str(whisper_raw.get("compute_type", "auto")),
        language=str(whisper_raw.get("language", "vi")),
        word_timestamps=bool(whisper_raw.get("word_timestamps", True)),
    )

    sub_raw = raw.get("subtitle", {})
    subtitle_cfg = SubtitleConfig(
        font_path=_resolve(sub_raw.get("font_path", "assets/fonts/BeVietnamPro-ExtraBold.ttf")),
        font_name=str(sub_raw.get("font_name", "Be Vietnam Pro ExtraBold")),
        font_size=int(sub_raw.get("font_size", 72)),
        primary_color=str(sub_raw.get("primary_color", "&H00FFFFFF")),
        outline_color=str(sub_raw.get("outline_color", "&H00000000")),
        back_color=str(sub_raw.get("back_color", "&H99000000")),
        outline=int(sub_raw.get("outline", 4)),
        shadow=int(sub_raw.get("shadow", 2)),
        alignment=int(sub_raw.get("alignment", 5)),
        margin_v=int(sub_raw.get("margin_v", 0)),
        max_chars_per_line=int(sub_raw.get("max_chars_per_line", 30)),
        max_words_per_caption=int(sub_raw.get("max_words_per_caption", 6)),
    )

    brand_raw = raw.get("branding", {})
    branding_cfg = BrandingConfig(
        enabled=bool(brand_raw.get("enabled", False)),
        logo_path=_resolve(brand_raw.get("logo_path")),
        logo_height=int(brand_raw.get("logo_height", 180)),
        logo_top_y=int(brand_raw.get("logo_top_y", 380)),
        gap_after_logo=int(brand_raw.get("gap_after_logo", 30)),
        line_spacing=int(brand_raw.get("line_spacing", 64)),
        channel_handle=str(brand_raw.get("channel_handle", "")),
        channel_name=str(brand_raw.get("channel_name", "")),
        handle_font_size=int(brand_raw.get("handle_font_size", 40)),
        name_font_size=int(brand_raw.get("name_font_size", 56)),
        font_path=_resolve(brand_raw.get("font_path", "assets/fonts/BeVietnamPro-ExtraBold.ttf")),
        font_name=str(brand_raw.get("font_name", "Be Vietnam Pro ExtraBold")),
        text_color=str(brand_raw.get("text_color", "&H00FFFFFF")),
        outline_color=str(brand_raw.get("outline_color", "&H00000000")),
        outline=int(brand_raw.get("outline", 3)),
        shadow=int(brand_raw.get("shadow", 2)),
    )

    llm_raw = raw.get("llm", {})
    llm_cfg = LLMConfig(
        provider=os.environ.get("LLM_PROVIDER", llm_raw.get("provider", "groq")).lower(),
        groq_model=str(llm_raw.get("groq_model", "openai/gpt-oss-120b")),
        claude_model=str(llm_raw.get("claude_model", "claude-sonnet-5")),
        max_title_length=int(llm_raw.get("max_title_length", 90)),
        temperature=float(llm_raw.get("temperature", 0.6)),
        groq_api_key=os.environ.get("GROQ_API_KEY"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )

    yt_raw = raw.get("youtube", {})
    youtube_cfg = YouTubeConfig(
        playlist_id=os.environ.get("YOUTUBE_PLAYLIST_ID", yt_raw.get("playlist_id", "")) or "",
        privacy_status=str(yt_raw.get("privacy_status", "public")),
        category_id=str(yt_raw.get("category_id", "22")),
        default_tags=list(yt_raw.get("default_tags", [])),
        made_for_kids=bool(yt_raw.get("made_for_kids", False)),
        publish_delay_minutes=int(yt_raw.get("publish_delay_minutes", 60)),
        client_id=os.environ.get("YOUTUBE_CLIENT_ID"),
        client_secret=os.environ.get("YOUTUBE_CLIENT_SECRET"),
        refresh_token=os.environ.get("YOUTUBE_REFRESH_TOKEN"),
    )

    tg_raw = raw.get("telegram", {})
    telegram_cfg = TelegramConfig(
        enabled=bool(tg_raw.get("enabled", True)),
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
    )

    return AppConfig(
        input=input_cfg,
        output=output_cfg,
        generation=generation_cfg,
        video=video_cfg,
        photos=photos_cfg,
        image_generation=image_gen_cfg,
        audio_mix=audio_mix_cfg,
        whisper=whisper_cfg,
        subtitle=subtitle_cfg,
        branding=branding_cfg,
        llm=llm_cfg,
        youtube=youtube_cfg,
        telegram=telegram_cfg,
        raw=raw,
    )
