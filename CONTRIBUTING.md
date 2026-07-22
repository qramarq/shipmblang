# Contributing

Thanks for helping improve ShipMBLang.

## Local Setup

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover -s tests
```

Install optional extras only when you are working on model or training code:

```bash
python -m pip install -e ".[model]"
python -m pip install -e ".[train]"
```

## Development Notes

- Keep the core compiler deterministic and dependency-light.
- Add or update tests for compiler behavior, bytecode behavior, and public CLI entry points.
- Do not commit local model checkpoints, virtual environments, generated datasets, or packaged VS Code extension builds.
- Keep compatibility imports working unless the change is intentionally breaking and documented.

## Pull Requests

Before opening a pull request, run:

```bash
python -m unittest discover -s tests
python -m pip install build
python -m build
```
