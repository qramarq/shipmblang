"""Optional chat-provider boundary for ShipMB Lang.

No provider is selected by default.  The legacy DripLM adapter is available
only when explicitly requested with ``SHIPMB_MODEL_PROVIDER=drip``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
import json
from urllib import request

from .multimodal import render_text_fallback, scnd_context_to_messages


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
    if provider != "drip":
        raise ValueError(f"unsupported ShipMB model provider {provider!r}; configure a compatible provider adapter")

    checkpoint = Path(os.environ.get("SHIPMB_MODEL_CHECKPOINT", ""))
    tokenizer = Path(os.environ.get("SHIPMB_MODEL_TOKENIZER", ""))
    device = os.environ.get("SHIPMB_MODEL_DEVICE", "cpu")
    if not checkpoint.is_file() or not tokenizer.is_file():
        return None
    from driplm.inference import DripInference

    return DripInference(str(checkpoint), str(tokenizer), device)


def chat_messages_from_scnd(context, *, system_prompt: str | None = None, native_media: bool = True):
    """Build provider input from SCND while retaining a text-only fallback.

    Native-media providers receive their typed SCND parts.  Text-only providers
    receive the same content as labelled untrusted text, including descriptions,
    transcripts, and references.
    """
    if native_media:
        messages = scnd_context_to_messages(context)
    else:
        messages = [{"role": "user", "content": render_text_fallback(context)}]
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})
    return messages
