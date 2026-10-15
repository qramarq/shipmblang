# ShipLM (milestone 1): verified data and compile-based eval

ShipLM is the planned ShipMBLang-native, task-specific model. This milestone adds
stdlib-only tooling in `shipmblang/shiplm/`; the compiler is the oracle.

```sh
python -m shipmblang.shiplm.dataset --out shiplm.jsonl   # verified JSONL, splits disjoint by template
python -m shipmblang.shiplm.evaluate --split test        # identity baseline
SHIPMB_MODEL_PROVIDER=... python -m shipmblang.shiplm.evaluate --provider   # score any provider
```

Metrics: `compile_success`, `exact_match` (bytecode equals the deterministic
compile of the original prose), and `unsafe_rejection` (file/network/shell
requests must not compile). Exit code is non-zero if release thresholds fail.

Next steps: tokenizer, training CLI, ONNX/safetensors packaging, a `shipmblang`
provider, and a model-version/grammar-version compatibility matrix.
