# ShipLM

A small, task-specific, ShipMBLang-native model that turns prose into programs the
[ShipMBLang](https://github.com/qramarq/shipmblang) compiler accepts. The compiler
is the oracle and always validates model output.

```sh
pip install shiplm            # dataset + eval (stdlib + shipmblang)
pip install "shiplm[train]"   # training / inference (torch)
shiplm dataset --out shiplm.jsonl
shiplm eval --split test
```

`shiplm` depends on `shipmblang`, never the reverse. See [docs/shiplm.md](docs/shiplm.md),
`tools/model_card.md` and `tools/dataset_card.md`.

`docs/model.onnx` should be published as a release asset rather than committed.
