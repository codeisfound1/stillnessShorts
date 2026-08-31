"""Upload video lên YouTube (Data API v3) và thêm vào playlist chỉ định.

Dùng OAuth refresh token lấy sẵn (xem scripts/get_youtube_refresh_token.py + README)
để chạy hoàn toàn non-interactive trong GitHub Actions, không cần đăng nhập lại mỗi lần.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .config import YouTubeConfig

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


class YouTubeUploadError(RuntimeError):
    """Raised khi upload hoặc thêm playlist thất bại."""


def _build_credentials(youtube_cfg: YouTubeConfig):
    from google.oauth2.credentials import Credentials

    if not (youtube_cfg.client_id and youtube_cfg.client_secret and youtube_cfg.refresh_token):
        raise YouTubeUploadError(
            "Thiếu YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN. "
            "Xem README để lấy OAuth credentials."
        )

    return Credentials(
        token=None,
        refresh_token=youtube_cfg.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=youtube_cfg.client_id,
        client_secret=youtube_cfg.client_secret,
        scopes=SCOPES,
    )


def _build_service(youtube_cfg: YouTubeConfig):
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = _build_credentials(youtube_cfg)
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_video(
    *,
    video_path: Path,
    title: str,
    description: str,
    youtube_cfg: YouTubeConfig,
) -> str:
    """Upload 1 video lên YouTube, trả về video_id."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    service = _build_service(youtube_cfg)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": youtube_cfg.default_tags,
            "categoryId": youtube_cfg.category_id,
        },
        "status": {
            "privacyStatus": youtube_cfg.privacy_status,
            "selfDeclaredMadeForKids": youtube_cfg.made_for_kids,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")

    logger.info("Upload lên YouTube: %s (%s)", title, video_path.name)
    try:
        request = service.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info("Upload progress: %d%%", int(status.progress() * 100))
        video_id = response["id"]
        logger.info("Upload thành công, video_id=%s", video_id)
        return video_id
    except HttpError as e:
        raise YouTubeUploadError(f"Lỗi upload video lên YouTube: {e}") from e


def add_to_playlist(*, video_id: str, playlist_id: str, youtube_cfg: YouTubeConfig) -> None:
    """Thêm video vào playlist. Bỏ qua (log warning) nếu không có playlist_id."""
    if not playlist_id:
        logger.warning("Không có playlist_id, bỏ qua bước thêm vào playlist.")
        return

    from googleapiclient.errors import HttpError

    service = _build_service(youtube_cfg)
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    try:
        service.playlistItems().insert(part="snippet", body=body).execute()
        logger.info("Đã thêm video %s vào playlist %s", video_id, playlist_id)
    except HttpError as e:
        raise YouTubeUploadError(f"Lỗi thêm video vào playlist: {e}") from e


def upload_and_add_to_playlist(
    *,
    video_path: Path,
    title: str,
    description: str,
    youtube_cfg: YouTubeConfig,
    playlist_id: Optional[str] = None,
) -> str:
    """Tiện ích gộp: upload + thêm playlist, trả về video_id."""
    video_id = upload_video(video_path=video_path, title=title, description=description, youtube_cfg=youtube_cfg)
    add_to_playlist(video_id=video_id, playlist_id=playlist_id or youtube_cfg.playlist_id, youtube_cfg=youtube_cfg)
    return video_id


def video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"
