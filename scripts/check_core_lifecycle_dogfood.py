#!/usr/bin/env python3
"""运行 Meta Flow 多 Work 核心生命周期自举硬门。"""

import runpy
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/core_lifecycle_dogfood.py"

if __name__ == "__main__":
    namespace = runpy.run_path(str(FIXTURE), run_name="__core_lifecycle_dogfood__")
    raise SystemExit(namespace["main"](sys.argv[1:]))
