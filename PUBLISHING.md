# Publishing

ShipMBLang is prepared to publish from this directory:

```bash
cd C:/Users/admin/Documents/printu/shipmblang
```

## Verify

```bash
python -m unittest discover -s tests
python -m build
```

## Create the GitHub Repository

Create an empty GitHub repository named `shipmblang`, then connect it:

```bash
git remote add origin https://github.com/<owner>/shipmblang.git
git push -u origin main
```

If you use the GitHub CLI:

```bash
gh repo create <owner>/shipmblang --source . --public --push
```

Use `--private` instead of `--public` if the repository should not be public yet.

## Notes

- The old `guppylm` remote has been removed to avoid accidental pushes to the wrong repository.
- Generated assets, local environments, model checkpoints, and packaged extension builds are ignored.
- Core ShipMBLang installs without third-party runtime dependencies; model and training tools are available through extras.
