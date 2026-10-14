"""护栏测试的公共前置（2026-10-14 新增）。

每个 bt_*_tests.py 在 `import main` 之前都必须做同样三件事，以前是各抄一遍：

  1. **打掉 WMI**：本机 WINMGMT 冷启动会让 `platform.system()` 永久阻塞几十秒到
     一两分钟（实测症状是"执行一半卡住不动"，faulthandler 阻塞栈停在
     platform.uname -> win32_ver -> _wmi_query）。不打掉的话，测试不是失败，
     是根本跑不完。
  2. **QT_QPA_PLATFORM=offscreen**：没有显示设备，Qt 需要这个无头平台插件。
  3. **把仓库根塞进 sys.path**：`import main` 才找得到。

漏抄任何一段的故障症状都极其难诊断：
  - 漏 1 → 测试跑几分钟不动，看起来像"这套用例很慢"
  - 漏 2 → Qt 起不来，报 "could not find or load the Qt platform plugin"
  - 漏 3（QApplication）→ **Qt 直接 abort，进程以 127 退出、日志里一行
    traceback 都没有**，极易被误判成"命令没跑起来"。bt_download_only_tests.py
    里那段注释记的就是这件事。

所以现在统一写成一行：

    import _btprelude          # noqa: F401  必须在 import main 之前
    import main                # noqa: E402

QApplication 另由 `ensure_app()` 提供 —— 它是**懒的**，只在真的要造控件时才建，
这样不碰 GUI 的用例（bt_boot_script_tests / bt_gitee_sync_tests，它们连 main
都不 import）可以安心 import 本模块而不付启动代价。

不适用本模块的例外：**bt_startup_tests.py**。
它刻意要操纵 platform 的探测函数来证明"启动期不碰 WMI"，而且它的
`_wmi_warm()` 需要问一次**真实**的 WMI 冷启动状态来决定跳过不跳过 ——
自动打桩会把那个判断变成永远为真。它保留自己的内联前置。
"""
from __future__ import annotations

import os
import platform as _platform
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def _wmi_disabled(*_args, **_kwargs):
    """替代 platform._wmi_query：一调就快速失败，绝不阻塞。"""
    raise OSError("WMI disabled for test process（见 _btprelude 的说明）")


def bootstrap() -> None:
    """打掉 WMI、设好无头平台、把仓库根加进 sys.path。幂等。

    必须在 `import main` 之前调用 —— `import _btprelude` 本身就会调一次，
    所以正常用法下这一行 import 就是全部动作。
    """
    _platform._wmi_query = _wmi_disabled
    # platform.uname 在 3.10+ 上带 lru_cache：桩换掉之后要把旧缓存清掉，
    # 否则本次进程里已经算过的结果会被继续沿用
    if hasattr(_platform.uname, "cache_clear"):
        _platform.uname.cache_clear()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


_APP = None


def ensure_app():
    """返回进程内唯一的 QApplication，没有就建一个。

    必须在造任何 QWidget **之前**调用，否则 Qt 直接 abort()（进程 127 退出、
    无 traceback）。本函数幂等，重复调用返回同一个实例。

    不传参数是有意的：这些护栏用例一律在 offscreen 下跑，不存在"要真窗口"
    的场景，传参数反而会诱导有人写出依赖显示设备的用例。
    """
    global _APP
    from PySide6.QtWidgets import QApplication

    if _APP is None:
        existing = QApplication.instance()
        # QApplication.instance() 可能已被别的路径建好（例如同一进程里别的
        # 套件先跑过），那就不是我们的 _APP，要认下来而不是再建一个
        _APP = existing if existing is not None else QApplication([])
    return _APP


bootstrap()