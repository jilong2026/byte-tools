"""平台判定收拢（规则 R30）。

main.py 负责**探测**（免 WMI 的 CURRENT_OS / MACHINE / IS_ARM），本模块只提供
判定函数。值通过 provider 延迟解引用，因此测试改写 `main.CURRENT_OS` 后，
`is_windows()` 等立刻反映新值（直接 import 常量会拿到 import 时快照）。
"""
from __future__ import annotations

from typing import Callable, Optional

_OS: Optional[Callable[[], str]] = None
_MACHINE: Optional[Callable[[], str]] = None
_IS_ARM: Optional[Callable[[], bool]] = None


def configure(os_provider: Callable[[], str],
              machine_provider: Optional[Callable[[], str]] = None,
              is_arm_provider: Optional[Callable[[], bool]] = None) -> None:
    global _OS, _MACHINE, _IS_ARM
    _OS = os_provider
    _MACHINE = machine_provider
    _IS_ARM = is_arm_provider


def current_os() -> str:
    return _OS() if _OS else ""


def machine() -> str:
    return _MACHINE() if _MACHINE else ""


def on_arm() -> bool:
    return bool(_IS_ARM()) if _IS_ARM else False


def is_windows() -> bool:
    return current_os() == "Windows"


def is_macos() -> bool:
    return current_os() == "Darwin"


def is_linux() -> bool:
    return current_os() == "Linux"
