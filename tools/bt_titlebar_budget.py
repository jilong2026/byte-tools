r"""标题栏宽度预算：**必须用真实字体量**，offscreen 平台的度量不可信。

用法（在仓库根目录，不要设 QT_QPA_PLATFORM）：
    .venv/Scripts/python.exe tools/bt_titlebar_budget.py

为什么要这个脚本：offscreen 平台没有系统的中文字体回退，Qt 用的替代字体宽得多，
同一句 `v1.2.0` 的 `minimumSizeHint` 在 offscreen 下是 92 像素、真实渲染只有 54 像素
（约 1.6 倍）。2026-10-12 就是拿 offscreen 的数字当依据，误判「🧹 清理残留 PATH 在裁字」
并把窗口最小宽抬到 1060 —— 真字体下这一行总共只需要 697 像素，1000 那一档余量充足。

所以：**像素裁字这类判断只能在真实渲染环境里下结论**；单元测试跑在 offscreen 下，
只断言与字体度量无关的不变量（控件的文字内容、定宽策略、相对位置）。
"""
import os
import platform as _platform
import sys
import tempfile
from pathlib import Path

_platform._wmi_query = lambda *_a, **_k: (_ for _ in ()).throw(OSError("stub"))
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()
os.environ.pop("QT_QPA_PLATFORM", None)          # 关键：走真实平台，别用 offscreen

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)

import main  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

NAMES = ("titleText", "btn_version", "btn_github", "btn_refresh",
         "btn_cleanup_path", "btn_clean_terminal", "btn_diagnostics",
         "btn_donate", "btn_min", "btn_max", "btn_close")

# chip 按状态变出来的全部文案，最长的一条决定预算
CHIP_TEXTS = [
    ("idle", {}),
    ("checking", {}),
    ("latest", {}),
    ("update", {"new_version": "1.10.0"}),
    ("error", {"reason": "connect failed"}),
    ("downloading", {"new_version": "1.10.0", "pct": 37}),
]


def report(win, app, tag, width):
    win.resize(width, 700)
    for _ in range(40):
        app.processEvents()
    bad, total = [], 0
    for name in NAMES:
        b = getattr(win, name, None)
        if b is None:
            continue
        need = b.minimumSizeHint().width()
        total += need
        if b.width() < need:
            bad.append(f"{name}[{b.text()[:12]}] 实得 {b.width()} < 需要 {need}")
    verdict = "OK" if not bad else "裁字 → " + " | ".join(bad)
    print(f"{tag:14s} 窗口 {width:5d}  整行最小总需 {total:5d}  {verdict}", flush=True)
    return total


def main_run():
    app = QApplication(sys.argv)
    main.ComponentCard._detect_status = lambda self, *a, **k: None
    main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
    tmp = tempfile.mkdtemp()
    main.CONFIG_DIR = Path(tmp)
    main.CONFIG_FILE = main.CONFIG_DIR / "config.json"
    win = main.MainWindow()
    win.show()
    for _ in range(40):
        app.processEvents()

    print(f"窗口最小宽 {win.minimumWidth()}  默认宽 {win.width()}\n", flush=True)
    print("chip 各状态需要的宽度：", flush=True)
    widest = 0
    for state, kw in CHIP_TEXTS:
        win._set_chip_state(state, **kw)
        for _ in range(10):
            app.processEvents()
        need = win.btn_version.minimumSizeHint().width()
        widest = max(widest, need)
        print(f"  {win.btn_version.text():20s} 需要 {need:4d}", flush=True)

    # 摆到最长那条文案上，逐档量整行
    win._set_chip_state("update", new_version="1.10.0")
    print(f"\n按 chip 最长文案（需要 {widest}）逐档量整行：", flush=True)
    for w in (960, win.minimumWidth(), 1120):
        report(win, app, "最长 chip", w)


if __name__ == "__main__":
    main_run()
