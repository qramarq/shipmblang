"""
Export DripLM to HuggingFace standard format.

Standard layout:
    pytorch_model.bin    — state_dict only
    config.json          — model architecture config
    tokenizer.json       — BPE tokenizer
    README.md            — model card
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


def export_and_push(checkpoint_path, tokenizer_path, repo_id, token, local_dir="hf_export"):
    import torch
    from huggingface_hub import HfApi

    # Load checkpoint
    ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    config = ckpt["config"]
    state_dict = ckpt["model_state_dict"]

    print(f"Model: {sum(p.numel() for p in state_dict.values()):,} params")

    # Save to local dir in HF standard format
    os.makedirs(local_dir, exist_ok=True)

    # 1. pytorch_model.bin — state_dict only
    model_path = os.path.join(local_dir, "pytorch_model.bin")
    torch.save(state_dict, model_path)
    print(f"  Saved {model_path} ({os.path.getsize(model_path)/1e6:.1f} MB)")

    # 2. config.json — model architecture only
    config_path = os.path.join(local_dir, "config.json")
    hf_config = {
        "model_type": "driplm",
        "architectures": ["DripLM"],
        "vocab_size": config["vocab_size"],
        "max_position_embeddings": config["max_seq_len"],
        "hidden_size": config["d_model"],
        "num_hidden_layers": config["n_layers"],
        "num_attention_heads": config["n_heads"],
        "intermediate_size": config["ffn_hidden"],
        "hidden_dropout_prob": config.get("dropout", 0.1),
        "pad_token_id": config["pad_id"],
        "bos_token_id": config["bos_id"],
        "eos_token_id": config["eos_id"],
    }
    with open(config_path, "w") as f:
        json.dump(hf_config, f, indent=2)
    print(f"  Saved {config_path}")

    # 3. tokenizer.json — copy as-is
    tokenizer_dest = os.path.join(local_dir, "tokenizer.json")
    with open(tokenizer_path) as f:
        tok_data = f.read()
    with open(tokenizer_dest, "w") as f:
        f.write(tok_data)
    print(f"  Saved {tokenizer_dest}")

    # 4. README.md — model card
    card_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_card.md")
    readme_dest = os.path.join(local_dir, "README.md")
    if os.path.exists(card_path):
        with open(card_path) as f:
            card = f.read()
        with open(readme_dest, "w") as f:
            f.write(card)
        print(f"  Saved {readme_dest}")

    # 5. drip.png — asset
    asset_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "drip.png")
    if os.path.exists(asset_path):
        asset_dir = os.path.join(local_dir, "assets")
        os.makedirs(asset_dir, exist_ok=True)
        import shutil
        shutil.copy2(asset_path, os.path.join(asset_dir, "drip.png"))
        print(f"  Saved assets/drip.png")

    # Push to HF
    if token and repo_id:
        api = HfApi(token=token)
        api.create_repo(repo_id, exist_ok=True)

        # Delete old non-standard files
        try:
            for old_file in ["checkpoints/best_model.pt", "checkpoints/config.json",
                             "data/tokenizer.json", "config.py", "model.py", "inference.py"]:
                api.delete_file(old_file, repo_id=repo_id, repo_type="model")
        except Exception:
            pass

        # Upload new standard files
        api.upload_folder(folder_path=local_dir, repo_id=repo_id, repo_type="model")
        print(f"\nPushed to https://huggingface.co/{repo_id}")
    else:
        print(f"\nExported to {local_dir}/ (no HF push — set token and repo)")


def main():
    parser = argparse.ArgumentParser(description="Export DripLM to HuggingFace format")
    parser.add_argument("--checkpoint", default="checkpoints/best_model.pt")
    parser.add_argument("--tokenizer", default="data/tokenizer.json")
    parser.add_argument("--repo", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--output-dir", default="hf_export")
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()

    load_env()

    token = args.token or os.environ.get("HF_TOKEN")
    repo = args.repo or os.environ.get("HF_REPO")

    if args.local_only:
        token = None
        repo = None

    export_and_push(args.checkpoint, args.tokenizer, repo, token, args.output_dir)


if __name__ == "__main__":
    main()
