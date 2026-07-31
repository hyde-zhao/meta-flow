#!/usr/bin/env python3
"""从源码 checkout 启动 Linux CLI lifecycle 的安全 bootstrap。"""

from __future__ import annotations

from meta_flow.installation.cli_executor import bootstrap_main

if __name__ == "__main__":
    raise SystemExit(bootstrap_main())
