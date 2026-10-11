r"""关窗崩溃的最小复现：证明"还有线程在跑就关窗"这条路是否被管住。

用法（在仓库根目录）：
    .venv/Scripts/python.exe tools/bt_close_crash_repro.py [orphan|tracked]

    orphan  —— 连起两条版本探测，第二条把第一条从 card._version_worker 上顶掉
               （真实代码形状：`_start_version_probe` 重探时就会顶替）
    tracked —— 只起一条，即 closeEvent 原先等得到的那一种

判定看**退出码**：0 = 干净退出；-1073740791（0xC0000409）= 命中 Qt 的
`QThread: Destroyed while thread is still running` fail-fast，也就是用户报的"关窗闪退"。
注意 bash 会把这个码显示成 127，所以要么用 PowerShell 的 Start-Process 取 ExitCode，
要么直接看 PowerShell 打印的 -1073740791：

    powershell -NoProfile -Command '$env:BT_STUB_FETCH="0";
      $p=(Start-Process -FilePath ".venv\Scripts\python.exe"
          -ArgumentList "tools\bt_close_crash_repro.py","orphan"
          -NoNewWindow -Wait -PassThru).ExitCode; Write-Host "rc=$p"'

环境变量：
    BT_STUB_FETCH=1（默认）—— 把 FETCHERS 清空，不测 VersionFetchWorker 那一类
    BT_STUB_FETCH=0         —— 保留启动即触发的真实版本抓取（这才是 R14.4 那个
                               closeEvent 异常的真正后果：后半段没跑，十几条抓取线程
                               在窗口析构时还活着）
脚本自己的 card / first 引用在最后一起 del 掉：留着的话窗口对象被它们吊着，
"窗口已析构"就变成假象，abort 也不会发生。
"""
import gc
import itertools
import os
import platform as _platform
import sys
import tempfile
import time
from pathlib import Path

_platform._wmi_query = lambda *_a, **_k: (_ for _ in ()).throw(OSError("stub"))
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ[_k] = ""

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)

import main  # noqa: E402
from PySide6.QtCore import QThread, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_MODE = sys.argv[1] if len(sys.argv) > 1 else "orphan"
_calls = itertools.count(1)


def _slow_probe(_exe, _args):
    # 第一条探测 3 秒（关窗时一定还在跑），后面的 0.5 秒
    time.sleep(3.0 if next(_calls) == 1 else 0.5)
    return "9.9.9"


main._probe_version = _slow_probe
if os.environ.get("BT_STUB_FETCH", "1") == "1":
    main.FETCHERS = {}          # 默认不测抓取那一类；BT_STUB_FETCH=0 保留真实抓取

_tmp = tempfile.mkdtemp()
main.CONFIG_DIR = Path(_tmp)
main.CONFIG_FILE = main.CONFIG_DIR / "config.json"


def _running(w):
    """对已被 deleteLater 的 worker 调 isRunning() 抛 RuntimeError（见 R14.4），
    这里不用 main._qthread_state：本脚本也要能跑在**没有那个助手**的旧代码上做 A/B。"""
    try:
        return bool(w.isRunning())
    except RuntimeError:
        return False


app = QApplication(sys.argv)
win = main.MainWindow()
win.show()

card = next(c for c in win.cards
            if c.component.version_probe and c.component.version_args)
first = None


def _stage():
    global first
    for w in list(getattr(card, "_probe_workers", ())):
        w.wait(6000)            # 卡片启动时自己排的那条先跑完，别混进本轮
    card._start_version_probe("fake.exe")          # worker A（3 秒）
    first = card._version_worker
    if _MODE == "orphan":
        card._start_version_probe("fake.exe")      # worker B（0.5 秒）顶掉 A
    print(f"[repro] mode={_MODE} A_running={_running(first)} "
          f"A_is_current={first is card._version_worker} "
          f"tracked={len(getattr(card, '_probe_workers', ()))}", flush=True)
    QTimer.singleShot(1500, win.close)             # A 还在跑时关窗


QTimer.singleShot(3000, _stage)
rc = app.exec()
print(f"[repro] app.exec rc={rc}", flush=True)

dangling = [type(w).__name__ for w in win.findChildren(QThread) if _running(w)]
print(f"[repro] still-running threads at teardown: {dangling or '无'}", flush=True)
del card, first, win
gc.collect()
print("[repro] survived teardown", flush=True)
# 这里不能用 os._exit(0)：Qt 的 fail-fast 发生在解释器收尾阶段，
# 提前退出会把崩溃码掩盖成 0，A/B 就白做了。
