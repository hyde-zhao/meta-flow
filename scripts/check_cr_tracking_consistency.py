#!/usr/bin/env python3
"""兼容入口：实际逻辑位于可打包的 meta_flow.checks.cr_tracking。"""

from __future__ import annotations

from meta_flow.checks.cr_tracking import main

if __name__ == "__main__":
    raise SystemExit(main())
