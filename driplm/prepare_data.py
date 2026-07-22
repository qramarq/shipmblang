"""Prepare training data for DripLM."""

import json
import os
import random

random.seed(42)

DATA_DIR = "data"
VOCAB_SIZE = 4096

SPECIAL_TOKENS = [
    "<pad>",         # 0
    "<|im_start|>",  # 1
    "<|im_end|>",    # 2
]


def train_tokenizer(texts, save_path, vocab_size=VOCAB_SIZE):
    from tokenizers import Tokenizer, models, trainers, pre_tokenizers, decoders, processors

    tokenizer = Tokenizer(models.BPE())
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()

    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=SPECIAL_TOKENS,
        show_progress=True,
        min_frequency=2,
    )

    print(f"Training BPE tokenizer (vocab_size={vocab_size}) on {len(texts)} texts...")
    tokenizer.train_from_iterator(texts, trainer)
    tokenizer.post_processor = processors.ByteLevel(trim_offsets=False)

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    tokenizer.save(save_path)
    print(f"Tokenizer saved to {save_path} ({tokenizer.get_vocab_size()} tokens)")
    return tokenizer


def prepare(data_dir=DATA_DIR, n_samples=60000, eval_ratio=0.05):
    os.makedirs(data_dir, exist_ok=True)

    # 1. Generate data
    print(f"Generating {n_samples} samples...")
    from .generate_data import generate_dataset
    generate_dataset(n_samples, eval_ratio)

    # 2. Read back all samples for tokenizer training
    texts = []
    for name in ["data/train.jsonl", "data/eval.jsonl"]:
        if os.path.exists(name):
            with open(name) as f:
                for line in f:
                    texts.append(json.loads(line)["text"])

    # 3. Train tokenizer
    tokenizer_path = os.path.join(data_dir, "tokenizer.json")
    tokenizer = train_tokenizer(texts, tokenizer_path)

    # Quick test
    test = "<|im_start|>user\nhi drip<|im_end|>"
    ids = tokenizer.encode(test).ids
    decoded = tokenizer.decode(ids)
    print(f"\nTokenizer test:")
    print(f"  Input:   {test}")
    print(f"  Tokens:  {len(ids)} ids")
    print(f"  Decoded: {decoded}")


if __name__ == "__main__":
    prepare()
