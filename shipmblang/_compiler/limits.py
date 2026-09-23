from __future__ import annotations

from pathlib import Path


# These limits protect the compiler and its optional local data loaders from
# accidental or hostile resource exhaustion.  They can be raised deliberately
# in a future version only alongside streaming parsers.
MAX_SOURCE_CHARS = 1_000_000
MAX_THESAURUS_FILE_BYTES = 1_000_000
MAX_WORDNET_FILE_BYTES = 8_000_000


def read_text_limited(path: Path, max_bytes: int, *, errors: str = "strict", newline: str | None = None) -> str:
    """Read a regular UTF-8 file only after enforcing a byte-size limit."""
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ValueError(f"Cannot read {path}: {error}") from error
    if not path.is_file():
        raise ValueError(f"Expected a regular file, got {path}.")
    if size > max_bytes:
        raise ValueError(f"Refusing to read {path}: {size} bytes exceeds the {max_bytes}-byte limit.")
    try:
        with path.open(encoding="utf-8", errors=errors, newline=newline) as stream:
            return stream.read()
    except OSError as error:
        raise ValueError(f"Cannot read {path}: {error}") from error
