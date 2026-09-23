# Contributing

Thanks for helping improve ShipMBLang.

## Contributor Agreement

A signed contributor agreement is required before an external contribution can
be merged. The agreement text and signing process are pending maintainer setup;
contact the maintainer before submitting a contribution. Opening a pull request
does not by itself sign an agreement or transfer copyright.

Maintainers: do not merge external contributions until the agreed terms are
available and acceptance has been recorded. See [CLA setup](docs/cla-setup.md).

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
