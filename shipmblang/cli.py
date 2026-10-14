"""ShipMB Lang public CLI, independent of any default language model."""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("ShipMB Lang - model-neutral programming and orchestration layer for ShipMB")
        print("Commands: context, chat")
        return

    command = sys.argv[1]
    if command == "context":
        from .runtime_context import build_system_prompt

        task = " ".join(sys.argv[2:]).strip()
        print(build_system_prompt(task=task))
        return
    if command == "chat":
        from .providers import load_chat_provider
        from .runtime_context import build_system_prompt

        provider = load_chat_provider()
        if provider is None:
            print("No model provider is configured. ShipMB Lang remains available without a model default.")
            print("Configure SHIPMB_MODEL_PROVIDER=openai_compatible with SHIPMB_MODEL_BASE_URL and SHIPMB_MODEL_NAME to enable optional chat.")
            return
        prompt = " ".join(sys.argv[2:]).strip() or input("You> ").strip()
        response = provider.chat_completion([
            {"role": "system", "content": build_system_prompt(task=prompt)},
            {"role": "user", "content": prompt},
        ])
        print(response["choices"][0]["message"]["content"].strip())
        return
    print(f"Unknown command: {command}")