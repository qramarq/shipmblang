"""Entry point for the self-contained shipmblang executable."""

import multiprocessing
import sys


if __name__ == "__main__":
    multiprocessing.freeze_support()
    from shipmblang.cli import main

    try:
        status = main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    raise SystemExit(status if isinstance(status, int) else 0)
