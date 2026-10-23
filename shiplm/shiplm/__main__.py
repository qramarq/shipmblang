"""shiplm command line: dataset, eval, prepare, train, chat, download."""
from __future__ import annotations

import os
import sys

CHECKPOINT_PATH = "checkpoints/best_model.pt"
TOKENIZER_PATH = "data/tokenizer.json"
HF_REPO = "arman-bd/driplm-9M"
HF_BASE = f"https://huggingface.co/{HF_REPO}/resolve/main"

USAGE = """shiplm - ShipMBLang-native model tooling
  shiplm dataset   Generate compiler-verified JSONL examples
  shiplm eval      Score a model with the compile-based eval
  shiplm prepare   Generate data and train the tokenizer (needs [train])
  shiplm train     Train the model (needs [train])
  shiplm chat      Chat with the local model (needs [train])
  shiplm download  Download pre-trained model assets"""


def download_model():
    import urllib.request

    files = [
        (f"{HF_BASE}/pytorch_model.bin", CHECKPOINT_PATH),
        (f"{HF_BASE}/tokenizer.json", TOKENIZER_PATH),
        (f"{HF_BASE}/config.json", "checkpoints/config.json"),
    ]
    print(f"Downloading model assets from {HF_REPO}...\n")
    for url, dest in files:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        print(f"  {os.path.basename(dest)}...", end=" ", flush=True)
        urllib.request.urlretrieve(url, dest)
        print(f"{os.path.getsize(dest) / 1e6:.1f} MB")
    print("\nDone! Run: shiplm chat")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0
    cmd, rest = argv[0], argv[1:]
    sys.argv = [f"shiplm {cmd}"] + rest
    if cmd == "dataset":
        from .verified_data import main as run
        return run(rest)
    if cmd == "eval":
        from .evaluate import main as run
        return run(rest)
    if cmd == "prepare":
        from .prepare_data import prepare
        return prepare()
    if cmd == "train":
        from .train import train
        return train()
    if cmd == "chat":
        if not os.path.exists(CHECKPOINT_PATH):
            print("Model not found. Run 'shiplm download' or 'shiplm prepare' then 'shiplm train'.")
            return 1
        from .inference import main as run
        return run()
    if cmd == "download":
        return download_model()
    print(f"Unknown command: {cmd}\n{USAGE}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
