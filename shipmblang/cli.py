"""ShipMBLang CLI preserving legacy commands with lazy compiler dispatch."""

import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "notebook":
        from .notebook import main as notebook_main

        previous = sys.argv
        sys.argv = [previous[0], *previous[2:]]
        try:
            return notebook_main()
        finally:
            sys.argv = previous
    if len(sys.argv) > 1 and sys.argv[1] in {"compile", "ship", "run", "ship-run"}:
        from . import pipelines

        command = sys.argv[1]
        previous = sys.argv
        sys.argv = previous[1:]
        try:
            return (pipelines.run_main if command in {"run", "ship-run"} else pipelines.main)()
        finally:
            sys.argv = previous
    from driplm.__main__ import main as legacy_main

    return legacy_main()


__all__ = ["main"]
