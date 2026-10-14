"""Optional chat-provider boundary for ShipMB Lang.

No model provider is selected by default. ShipMB identity and capabilities are
runtime-owned, then supplied to any explicitly configured provider.
"""

from __future__ import annotations

import json
import os
from typing import Protocol
from urllib import request


class ChatProvider(Protocol):
    def chat_completion(self, messages, temperature=0.7, max_tokens=64, top_k=50, **kwargs):
        """Return an OpenAI-style completion."""


class OpenAICompatibleProvider:
    """Minimal local or self-hosted OpenAI-compatible chat adapter."""

    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def chat_completion(self, messages, temperature=0.7, max_tokens=64, top_k=50, **kwargs):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        endpoint = self.base_url if self.base_url.endswith("/chat/completions") else self.base_url + "/chat/completions"
        with request.urlopen(request.Request(endpoint, data=body, headers=headers, method="POST"), timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))


def load_chat_provider() -> ChatProvider | None:
    provider = os.environ.get("SHIPMB_MODEL_PROVIDER", "none").strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider in {"openai_compatible", "ollama"}:
        base_url = os.environ.get("SHIPMB_MODEL_BASE_URL", "").strip()
        model = os.environ.get("SHIPMB_MODEL_NAME", "").strip()
        if provider == "ollama" and not base_url:
            base_url = "http://127.0.0.1:11434/v1"
        if not base_url or not model:
            return None
        return OpenAICompatibleProvider(base_url, model, os.environ.get("SHIPMB_MODEL_API_KEY", ""))
    raise ValueError(
        f"unsupported ShipMB model provider {provider!r}; "
        "set SHIPMB_MODEL_PROVIDER=openai_compatible, ollama, none, or disabled"
    )