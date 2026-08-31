"""Helper dùng chung để gọi ffmpeg/ffprobe qua subprocess với logging + xử lý lỗi thống nhất."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    """Raised khi ffmpeg/ffprobe trả về mã lỗi khác 0."""


def check_binaries_available() -> None:
    """Kiểm tra ffmpeg/ffprobe có trong PATH, raise sớm với thông báo rõ ràng nếu thiếu."""
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise FFmpegError(
                f"Không tìm thấy '{binary}' trong PATH. Cài đặt ffmpeg trước khi chạy "
                "(vd: apt-get install ffmpeg, hoặc xem README)."
            )


def run(cmd: list[str], *, description: str = "") -> subprocess.CompletedProcess:
    """Chạy 1 lệnh ffmpeg/ffprobe, log lệnh + raise FFmpegError kèm stderr nếu thất bại."""
    logger.debug("Chạy lệnh: %s", " ".join(cmd))
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-25:])
        raise FFmpegError(f"Lệnh ffmpeg thất bại ({description or cmd[0]}):\n{tail}")
    return result


def probe_duration(path: Path) -> float:
    """Trả về thời lượng (giây) của file media bằng ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = run(cmd, description=f"probe duration của {path}")
    data = json.loads(result.stdout)
    try:
        return float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError) as e:
        raise FFmpegError(f"Không đọc được duration từ ffprobe cho {path}: {e}") from e
