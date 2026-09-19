"""Entry point for ShipMBLang CLI aliases."""

import os
import sys

CHECKPOINT_PATH = "checkpoints/best_model.pt"
TOKENIZER_PATH = "data/tokenizer.json"
HF_REPO = "arman-bd/driplm-9M"
HF_BASE = f"https://huggingface.co/{HF_REPO}/resolve/main"


def download_model():
    """Download pre-trained model assets from HuggingFace."""
    import urllib.request

    files = [
        (f"{HF_BASE}/pytorch_model.bin", CHECKPOINT_PATH),
        (f"{HF_BASE}/tokenizer.json", TOKENIZER_PATH),
        (f"{HF_BASE}/config.json", "checkpoints/config.json"),
    ]

    print(f"Downloading ShipMBLang model assets from {HF_REPO}...\n")
    for url, dest in files:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        name = os.path.basename(dest)
        print(f"  {name}...", end=" ", flush=True)
        urllib.request.urlretrieve(url, dest)
        size_mb = os.path.getsize(dest) / 1e6
        print(f"{size_mb:.1f} MB")

    print("\nDone! Run: python -m shipmblang chat")


def main():
    if len(sys.argv) < 2:
        print("ShipMBLang - natural language programming for ShipMB")
        print()
        print("Usage:")
        print("  python -m shipmblang compile     Compile natural ShipMBLang sentences")
        print("  python -m shipmblang run         Run natural ShipMBLang sentences")
        print("  python -m shipmblang printurf    Explain a raw code error")
        print("  python -m shipmblang mcp         Run the ShipMBLang MCP server")
        print("  python -m shipmblang onboarding  Print/validate ShipMB onboarding contract")
        print("  python -m shipmblang train       Train the local model")
        print("  python -m shipmblang prepare     Generate data & train tokenizer")
        print("  python -m shipmblang chat        Chat with the local model")
        print("  python -m shipmblang download    Download pre-trained model from HuggingFace")
        print()
        print("Short alias:")
        print('  python -m shipmb run "Use ShipMB..."')
        return

    cmd = sys.argv[1]
    sys.argv = sys.argv[1:]

    if cmd == "prepare":
        from .prepare_data import prepare

        prepare()

    elif cmd == "train":
        from .train import train

        train()

    elif cmd == "download":
        download_model()

    elif cmd == "chat":
        if not os.path.exists(CHECKPOINT_PATH):
            print("Model not found. Download the pre-trained model first:\n")
            print("  python -m shipmblang download\n")
            print("Or train your own:\n")
            print("  python -m shipmblang prepare")
            print("  python -m shipmblang train")
            return

        from .inference import main as inference_main

        inference_main()

    elif cmd in ("explain-error", "drip", "printurf"):
        from .error_explainer import main as error_explainer_main

        error_explainer_main()

    elif cmd in ("compile", "ship"):
        from shipmblang.pipelines import main as natural_syntax_main

        natural_syntax_main()

    elif cmd in ("run", "ship-run"):
        from shipmblang.pipelines import run_main as natural_syntax_run_main

        natural_syntax_run_main()

    elif cmd == "mcp":
        from .mcp_server import main as mcp_main

        mcp_main()

    elif cmd in ("onboarding", "onboard"):
        from .onboarding import main as onboarding_main

        raise SystemExit(onboarding_main())

    else:
        print(f"Unknown command: {cmd}")
        print("Run 'python -m shipmblang' for usage.")


if __name__ == "__main__":
    main()
