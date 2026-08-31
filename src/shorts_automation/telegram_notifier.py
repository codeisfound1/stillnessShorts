"""Gửi thông báo qua Telegram Bot API khi upload xong 1 short (hoặc báo lỗi)."""

from __future__ import annotations

import logging

import requests

from .config import TelegramConfig

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _send(message: str, telegram_cfg: TelegramConfig) -> bool:
    if not telegram_cfg.enabled:
        logger.debug("Telegram notification bị tắt trong config, bỏ qua.")
        return False
    if not (telegram_cfg.bot_token and telegram_cfg.chat_id):
        logger.warning("Thiếu TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID, không gửi được thông báo Telegram.")
        return False

    url = TELEGRAM_API_URL.format(token=telegram_cfg.bot_token)
    payload = {
        "chat_id": telegram_cfg.chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.warning("Gửi Telegram thất bại: %s", e)
        return False


def notify_short_uploaded(*, title: str, youtube_url: str, index: int, telegram_cfg: TelegramConfig) -> None:
    message = f"✅ <b>Short #{index}</b> đã đăng lên YouTube!\n\n<b>{title}</b>\n{youtube_url}"
    _send(message, telegram_cfg)


def notify_short_failed(*, index: int, error: str, telegram_cfg: TelegramConfig) -> None:
    message = f"❌ <b>Short #{index}</b> gặp lỗi:\n{error}"
    _send(message, telegram_cfg)


def notify_run_summary(*, total: int, succeeded: int, failed: int, telegram_cfg: TelegramConfig) -> None:
    message = (
        f"📦 <b>Tổng kết đợt chạy</b>\n"
        f"Tổng số short dự kiến: {total}\n"
        f"Thành công: {succeeded}\n"
        f"Thất bại: {failed}"
    )
    _send(message, telegram_cfg)
