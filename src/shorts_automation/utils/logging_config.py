"""Cấu hình logging dùng chung cho toàn bộ ứng dụng."""

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Khởi tạo logging ra stdout với format có timestamp + tên module.

    Gọi một lần duy nhất ở entrypoint (main.py).
    """
    root = logging.getLogger()
    if root.handlers:
        # Đã setup rồi (ví dụ khi chạy trong test), tránh add handler trùng.
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Hạ bớt độ ồn của các thư viện bên thứ ba.
    for noisy in ("urllib3", "google", "googleapiclient", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
