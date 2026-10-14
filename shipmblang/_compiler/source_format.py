"""Lightweight source detection, independent of Core parsing and rendering."""


def looks_like_core(source: str) -> bool:
    lines = [_strip_hash_comment(line).strip() for line in source.splitlines() if _strip_hash_comment(line).strip()]
    if not lines:
        return False
    return any(
        line.startswith(
            (
                "use ",
                "library ",
                "device_target",
                "device target",
                "remote |>",
                "on error:",
                "run ",
                "install ",
                "interface ",
                "mcp ",
                "architecture |> show",
                "shipmb.",
            )
        )
        for line in lines
    )


def _strip_hash_comment(line: str) -> str:
    in_quote: str | None = None
    for index, char in enumerate(line):
        if char in {'"', "'"}:
            if in_quote == char:
                in_quote = None
            elif in_quote is None:
                in_quote = char
        elif char == "#" and in_quote is None:
            return line[:index]
    return line

