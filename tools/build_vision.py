#!/usr/bin/env python3
"""Build libshipmb_vision from native/shipmb_vision and install it for vision.py.

``/usr/bin/c++`` is left unused. The script passes gcc/g++ to CMake when they
are installed, because a Clang ``c++`` on PATH can fail to link libstdc++.
Override that with ``--cc`` and ``--cxx``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shipmblang.vision_build import main


if __name__ == "__main__":
    raise SystemExit(main())
