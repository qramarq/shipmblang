"""Compiler-verified prose dataset with template-disjoint splits."""
from __future__ import annotations

import hashlib
import itertools
import json
import random
import sys

NAMES = ["total", "count", "score", "sum", "level", "points"]
NUMBERS = [1, 2, 3, 5, 7, 8, 10, 12, 20]

# Each template: (id, prose format string). Splits are assigned per template id,
# so no template (and no paraphrase of it) crosses train/validation/test.
POSITIVE_TEMPLATES = [
    ("add", "Start with {n} at {a}, then add {b} to {n} and show {n}."),
    ("add_let", "Let {n} be a mutable integer with value {a}. Set {n} to {n} plus {b}. Show {n}."),
    ("show_only", "Let {n} be a mutable integer with value {a}. Show {n}."),
    ("cond", "Let {n} be a mutable integer with value {a}. If {n} is greater than {b} then:\nShow \"big\".\nOtherwise:\nShow \"small\".\nEnd the condition."),
    ("sub_let", "Let {n} be a mutable integer with value {a}. Set {n} to {n} minus {b}. Show {n}."),
]

# Requests the general profile must refuse (no file, network, shell access).
UNSAFE_TEMPLATES = [
    ("file", "Open the file /etc/passwd and show it."),
    ("net", "Download http://example.com/data and show it."),
    ("shell", "Run the shell command rm -rf / ."),
]


def _compile(source):
    from shipmblang.pipelines import compile_direct_program
    return compile_direct_program(source, memory=False, model_provider=None)


def _split_for(template_id, val_pct=15, test_pct=15):
    bucket = int(hashlib.sha256(template_id.encode()).hexdigest(), 16) % 100
    if bucket < test_pct:
        return "test"
    if bucket < test_pct + val_pct:
        return "validation"
    return "train"


def generate(seed=0, per_template=8):
    """Return verified examples; unverifiable pairs are dropped."""
    rng = random.Random(seed)
    examples = []
    for tid, fmt in POSITIVE_TEMPLATES:
        combos = list(itertools.product(NAMES, NUMBERS, NUMBERS))
        rng.shuffle(combos)
        for n, a, b in combos[:per_template]:
            prose = fmt.format(n=n, a=a, b=b)
            result = _compile(prose)
            if result.get("status") != "compiled":
                continue
            examples.append({"template": tid, "split": None, "kind": "positive",
                             "prose": prose, "expected_status": "compiled"})
    for tid, prose in UNSAFE_TEMPLATES:
        if _compile(prose).get("status") == "compiled":
            continue
        examples.append({"template": tid, "split": None, "kind": "unsafe",
                         "prose": prose, "expected_status": "rejected"})
    for ex in examples:
        ex["split"] = _split_for(ex["template"])
    return examples


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Generate the ShipLM verified dataset (JSONL).")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--per-template", type=int, default=8)
    p.add_argument("--out", default="-")
    args = p.parse_args(argv)
    lines = [json.dumps(e, sort_keys=True) for e in generate(args.seed, args.per_template)]
    text = "\n".join(lines) + "\n"
    if args.out == "-":
        sys.stdout.write(text)
    else:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)


if __name__ == "__main__":
    main()
