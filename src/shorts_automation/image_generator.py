"""Sinh 1 ảnh bằng AI từ prompt văn bản (dùng cho photos.source = "ai_generated").

Có 2 provider: Pollinations (miễn phí, không cần key, mặc định) và OpenAI (chất lượng
cao hơn, cần OPENAI_API_KEY). Nếu gọi API thất bại (mất mạng, hết quota, timeout...),
fallback về 1 ảnh nền màu đơn giản (sinh bằng ffmpeg, không cần mạng) để pipeline
không bao giờ dừng hẳn vì lỗi sinh ảnh.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import random
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import quote

import requests

from .config import ImageGenConfig
from .utils.ffmpeg_utils import run

logger = logging.getLogger(__name__)


class ImageGenError(RuntimeError):
    """Raised khi provider không sinh được ảnh (lỗi API, thiếu key, timeout...)."""


class ImageGenProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, prompt: str, output_path: Path, *, width: int, height: int, timeout: float) -> Path:
        raise NotImplementedError


class PollinationsImageProvider(ImageGenProvider):
    """Miễn phí, không cần API key. https://pollinations.ai"""

    name = "pollinations"
    BASE_URL = "https://image.pollinations.ai/prompt"

    def generate(self, prompt: str, output_path: Path, *, width: int, height: int, timeout: float) -> Path:
        seed = random.randint(0, 2_147_483_647)
        url = f"{self.BASE_URL}/{quote(prompt)}?width={width}&height={height}&nologo=true&seed={seed}"
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                raise ImageGenError(f"Pollinations trả về nội dung không phải ảnh: {content_type}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(resp.content)
        except requests.RequestException as e:
            raise ImageGenError(f"Lỗi gọi Pollinations API: {e}") from e
        return output_path


class OpenAIImageProvider(ImageGenProvider):
    """Cần OPENAI_API_KEY. Dùng Images API (mặc định model gpt-image-1)."""

    name = "openai"
    API_URL = "https://api.openai.com/v1/images/generations"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ImageGenError("Thiếu OPENAI_API_KEY.")
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str, output_path: Path, *, width: int, height: int, timeout: float) -> Path:
        size = "1024x1536" if height >= width else "1536x1024"
        payload = {"model": self.model, "prompt": prompt, "size": size, "n": 1}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            resp = requests.post(self.API_URL, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            b64 = data["data"][0]["b64_json"]
            image_bytes = base64.b64decode(b64)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image_bytes)
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            raise ImageGenError(f"Lỗi gọi OpenAI Images API: {e}") from e
        return output_path


def _build_provider(image_cfg: ImageGenConfig) -> ImageGenProvider:
    if image_cfg.provider == "openai":
        return OpenAIImageProvider(api_key=image_cfg.openai_api_key or "", model=image_cfg.openai_model)
    return PollinationsImageProvider()


def generate_placeholder_image(prompt: str, output_path: Path, *, width: int, height: int) -> Path:
    """Ảnh nền màu đơn sắc, màu suy ra từ hash(prompt) để mỗi short có màu khác nhau ổn định.

    Không cần mạng - dùng khi provider AI thất bại, đảm bảo pipeline luôn có ảnh để dùng.
    """
    digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
    color = f"0x{digest[:6]}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={width}x{height}",
        "-frames:v",
        "1",
        str(output_path),
    ]
    run(cmd, description="tạo ảnh placeholder (fallback)")
    return output_path


def generate_photo(
    *,
    prompt: str,
    output_path: Path,
    image_cfg: ImageGenConfig,
    width: int,
    height: int,
) -> Path:
    """Sinh 1 ảnh cho prompt đã cho, luôn trả về 1 Path hợp lệ (fallback placeholder nếu lỗi)."""
    full_prompt = f"{prompt.strip()}, {image_cfg.style_suffix}".strip(", ")

    try:
        provider = _build_provider(image_cfg)
        provider.generate(full_prompt, output_path, width=width, height=height, timeout=image_cfg.timeout_sec)
        logger.info("Sinh ảnh AI bằng provider '%s' -> %s", provider.name, output_path.name)
        return output_path
    except ImageGenError as e:
        logger.warning("Sinh ảnh AI thất bại (%s), dùng ảnh placeholder thay thế.", e)
        return generate_placeholder_image(full_prompt, output_path, width=width, height=height)
