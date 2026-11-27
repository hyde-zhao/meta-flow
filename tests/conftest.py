"""测试隔离：cwd 与角色环境变量不得继承运行目录（BUG-0010）。

在工作区子项目内运行 pytest 时，detect_role(Path.cwd()) 会把测试进程
识别成 worker，导致 manager 命令被角色门拒绝。全部测试统一切到独立
临时目录并清空 MF_ROLE/MF_WORKER_ID/MF_ACTOR，保证在任意目录运行结果一致。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_cwd_and_role(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("MF_ROLE", "MF_WORKER_ID", "MF_ACTOR", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)
    yield
