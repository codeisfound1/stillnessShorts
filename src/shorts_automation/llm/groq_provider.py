"""Provider dùng Groq API (mặc định model: openai/gpt-oss-120b) cho title + image prompt."""

from __future__ import annotations

import logging

import requests

from .base import TitleProvider, TitleProviderError

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqTitleProvider(TitleProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, temperature: float = 0.6, timeout: float = 30.0):
        if not api_key:
            raise TitleProviderError("Thiếu GROQ_API_KEY.")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        try:
            resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            raise TitleProviderError(f"Lỗi gọi Groq API: {e}") from e
