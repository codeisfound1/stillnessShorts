"""Quản lý trạng thái (state.json) để không tạo trùng đoạn video/audio/ảnh giữa các lần chạy.

Mỗi cặp (video_path hoặc photos_dir, narration_path) có một "source key" riêng, lưu:
- video_pointer_sec / audio_pointer_sec: mốc thời gian đã dùng tới (mode "video"), đoạn
  tiếp theo luôn bắt đầu từ đây trở đi (đảm bảo không lấy lại đoạn cũ, không lồng nhau).
- photo_pointer_index: số ảnh đã dùng tính từ đầu thư mục (mode "photos").
- shorts: danh sách các short đã tạo (kèm metadata) để tra cứu / báo cáo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _source_key(video_path: Path, narration_path: Path) -> str:
    raw = f"{video_path.resolve()}::{narration_path.resolve()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class SourceState:
    video_pointer_sec: float = 0.0
    audio_pointer_sec: float = 0.0
    photo_pointer_index: int = 0
    shorts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_pointer_sec": self.video_pointer_sec,
            "audio_pointer_sec": self.audio_pointer_sec,
            "photo_pointer_index": self.photo_pointer_index,
            "shorts": self.shorts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceState":
        return cls(
            video_pointer_sec=float(d.get("video_pointer_sec", 0.0)),
            audio_pointer_sec=float(d.get("audio_pointer_sec", 0.0)),
            photo_pointer_index=int(d.get("photo_pointer_index", 0)),
            shorts=list(d.get("shorts", [])),
        )


class StateStore:
    """Đọc/ghi state.json. Ghi atomically để tránh hỏng file nếu bị ngắt giữa chừng."""

    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        self._data: dict[str, Any] = {"sources": {}}
        self._load()

    def _load(self) -> None:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                if "sources" not in self._data:
                    self._data["sources"] = {}
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Không đọc được state file %s (%s), khởi tạo state mới.", self.state_file, e)
                self._data = {"sources": {}}
        else:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(self.state_file.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.state_file)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def get_source_state(self, video_path: Path, narration_path: Path) -> tuple[str, SourceState]:
        key = _source_key(video_path, narration_path)
        raw = self._data["sources"].get(key)
        state = SourceState.from_dict(raw) if raw else SourceState()
        return key, state

    def update_source_state(self, key: str, state: SourceState) -> None:
        self._data["sources"][key] = state.to_dict()

    def next_short_index(self, state: SourceState) -> int:
        return len(state.shorts) + 1

    def record_short(
        self,
        key: str,
        state: SourceState,
        *,
        audio_start: float,
        audio_end: float,
        title: str,
        output_file: str,
        video_start: Optional[float] = None,
        video_end: Optional[float] = None,
        photo_start_index: Optional[int] = None,
        photo_end_index: Optional[int] = None,
        image_prompt: Optional[str] = None,
        youtube_video_id: Optional[str] = None,
        youtube_url: Optional[str] = None,
        uploaded: bool = False,
    ) -> dict[str, Any]:
        """Ghi lại 1 short đã tạo. Truyền video_start/video_end (mode video), HOẶC
        photo_start_index/photo_end_index (mode photos + folder), HOẶC image_prompt
        (mode photos + ai_generated) tùy theo input.mode/photos.source đang dùng."""
        entry: dict[str, Any] = {
            "index": self.next_short_index(state),
            "audio_start": round(audio_start, 3),
            "audio_end": round(audio_end, 3),
            "duration": round(audio_end - audio_start, 3),
            "title": title,
            "output_file": output_file,
            "youtube_video_id": youtube_video_id,
            "youtube_url": youtube_url,
            "uploaded": uploaded,
        }
        if image_prompt is not None:
            entry["image_prompt"] = image_prompt
        if video_start is not None and video_end is not None:
            entry["video_start"] = round(video_start, 3)
            entry["video_end"] = round(video_end, 3)
        if photo_start_index is not None and photo_end_index is not None:
            entry["photo_start_index"] = photo_start_index
            entry["photo_end_index"] = photo_end_index

        state.shorts.append(entry)
        self.update_source_state(key, state)
        self.save()
        return entry
