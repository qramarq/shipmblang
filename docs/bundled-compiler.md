# One installation, separate development

Users install only ShipMBLang (Python 3.11+). Every language wheel contains its
compiler and runtime under `shipmblang._compiler`. There is no dependency on the
separate compiler distribution, top-level `shipmbcompiler` package, or `shipmbc`
command. The internal namespace is an implementation detail, not a supported
public API. Python source remains inspectable.

Develop and push compiler changes in the compiler repository. Develop and push
language changes in the language repository. Do not edit the bundled snapshot as
the source of truth. When a compiler change is ready for language integration,
run these commands from the language project (the folder with pyproject.toml):

```powershell
python tools/bundle_compiler.py C:/path/to/shipmbcompiler
python -m unittest discover -s tests
python tools/check_bundled_install.py
```

The packaging check needs setuptools, wheel, and pip in the development Python.
It builds a wheel in a temporary folder, installs only that wheel into a clean
environment without network access, and checks public API and CLI execution.
It also checks that no public compiler package or compiler launcher is installed.

The update tool copies compiler modules without changing their relative imports
or bytecode formats. `shipmblang/_compiler/BUNDLED.json` records the upstream
version and SHA-256 of each source file. Review the snapshot and manifest diff,
then commit them with the language release. Language and compiler versions can
advance independently; a language release keeps its selected snapshot until the
next explicit update. Runtime never downloads or upgrades the compiler.

Build and distribute the language wheel from this project after verification.
Older `output/*publish` directories are historical staging copies; they do not
automatically receive changes made here.
