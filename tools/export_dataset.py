"""
Export DripLM training data to HuggingFace.

Usage:
    # Set up .env with HF_TOKEN and HF_REPO
    python tools/export_dataset.py

    # Or pass directly
    python tools/export_dataset.py --repo your-username/driplm-60k-generic --token hf_xxx
"""

import argparse
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env():
    """Load .env file if it exists."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


def generate_data(n_samples=60000, eval_ratio=0.05):
    """Generate the dataset as train/test lists of dicts."""
    import random
    random.seed(42)

    from driplm.generate_data import (
        gen_greeting, gen_feeling, gen_temp_hot, gen_temp_cold, gen_food,
        gen_light, gen_water, gen_about, gen_confused, gen_tank, gen_noise,
        gen_night, gen_lonely, gen_misc, gen_bye,
        gen_bubbles, gen_glass, gen_reflection, gen_breathing, gen_swimming,
        gen_colors, gen_taste, gen_plants, gen_filter, gen_algae, gen_snail,
        gen_glass_tap, gen_scared, gen_excited, gen_bored, gen_curious,
        gen_happy, gen_tired, gen_outside, gen_cat, gen_rain, gen_seasons,
        gen_music, gen_visitors, gen_children, gen_meaning, gen_time,
        gen_memory, gen_dreams, gen_size, gen_future, gen_past, gen_name,
        gen_weather, gen_sleep, gen_friends, gen_joke, gen_fear, gen_love,
        gen_age, gen_smart, gen_poop, gen_doctor, gen_singing, gen_tv,
    )

    topics = [
        gen_greeting, gen_feeling, gen_temp_hot, gen_temp_cold, gen_food,
        gen_light, gen_water, gen_about, gen_confused, gen_tank, gen_noise,
        gen_night, gen_lonely, gen_misc, gen_bye,
        gen_bubbles, gen_glass, gen_reflection, gen_breathing, gen_swimming,
        gen_colors, gen_taste, gen_plants, gen_filter, gen_algae, gen_snail,
        gen_glass_tap, gen_scared, gen_excited, gen_bored, gen_curious,
        gen_happy, gen_tired, gen_outside, gen_cat, gen_rain, gen_seasons,
        gen_music, gen_visitors, gen_children, gen_meaning, gen_time,
        gen_memory, gen_dreams, gen_size, gen_future, gen_past, gen_name,
        gen_weather, gen_sleep, gen_friends, gen_joke, gen_fear, gen_love,
        gen_age, gen_smart, gen_poop, gen_doctor, gen_singing, gen_tv,
    ]

    per_topic = max(1, n_samples // len(topics))
    samples = []
    for gen in topics:
        for _ in range(per_topic):
            try:
                s = gen()
                samples.append({
                    "input": s["input"],
                    "output": s["output"],
                    "category": s["category"],
                })
            except Exception:
                pass

    random.shuffle(samples)
    n_eval = int(len(samples) * eval_ratio)
    return samples[n_eval:], samples[:n_eval]


def push_to_hub(train_data, test_data, repo_id, token):
    """Push dataset + README to HuggingFace Hub."""
    from datasets import Dataset, DatasetDict
    from huggingface_hub import HfApi

    ds = DatasetDict({
        "train": Dataset.from_list(train_data),
        "test": Dataset.from_list(test_data),
    })

    print(f"\nDataset:")
    print(f"  Train: {len(train_data):,} samples")
    print(f"  Test:  {len(test_data):,} samples")
    print(f"  Columns: {list(ds['train'].column_names)}")
    print(f"  Categories: {len(set(r['category'] for r in train_data))}")
    print()

    print(f"Pushing to {repo_id}...")
    ds.push_to_hub(repo_id, token=token)

    # Push dataset card (README.md)
    card_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset_card.md")
    if os.path.exists(card_path):
        api = HfApi(token=token)
        api.upload_file(
            path_or_fileobj=card_path,
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="dataset",
        )
        print("Pushed README.md")

    print(f"Done! https://huggingface.co/datasets/{repo_id}")


def save_local(train_data, test_data, output_dir="dataset"):
    """Save dataset locally as JSONL."""
    os.makedirs(output_dir, exist_ok=True)

    for name, data in [("train.jsonl", train_data), ("test.jsonl", test_data)]:
        path = os.path.join(output_dir, name)
        with open(path, "w") as f:
            for row in data:
                f.write(json.dumps(row) + "\n")
        print(f"Saved {path} ({len(data):,} samples)")


def main():
    parser = argparse.ArgumentParser(description="Export DripLM dataset to HuggingFace")
    parser.add_argument("--repo", default=None, help="HuggingFace repo (e.g. your-username/driplm-60k-generic)")
    parser.add_argument("--token", default=None, help="HuggingFace token")
    parser.add_argument("--samples", type=int, default=60000, help="Number of samples to generate")
    parser.add_argument("--local-only", action="store_true", help="Save locally without pushing to HF")
    parser.add_argument("--output-dir", default="dataset", help="Local output directory")
    args = parser.parse_args()

    load_env()

    token = args.token or os.environ.get("HF_TOKEN")
    repo = args.repo or os.environ.get("HF_DATASET")

    if not args.local_only and not token:
        print("Error: No HF token. Set HF_TOKEN in .env or pass --token")
        sys.exit(1)
    if not args.local_only and not repo:
        print("Error: No HF repo. Set HF_DATASET in .env or pass --repo")
        sys.exit(1)

    print(f"Generating {args.samples:,} samples...")
    train_data, test_data = generate_data(args.samples)

    # Always save locally
    save_local(train_data, test_data, args.output_dir)

    # Push to HF if not local-only
    if not args.local_only:
        push_to_hub(train_data, test_data, repo, token)


if __name__ == "__main__":
    main()
