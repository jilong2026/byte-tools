r"""重新生成 README 里的主界面预览图（assets/byte-tools-pt.png）。

用法（在仓库根目录，**不要**设 QT_QPA_PLATFORM）：
    .venv/Scripts/python.exe tools/bt_shot_readme.py

为什么必须有这个脚本：这张图是 README 的门面，而**它很容易过期** ——
2026-10-16 更新前用的那张还是 v1.2.1 时代的（四个 Tab、83 个组件、
连已取消的「开发软件」Tab 都还在）。手截一张再手动替换的做法没有留下任何配方，
下一个人只会看到"图不对了、但不知道怎么重做"。这里把做法钉下来。

⚠ **必须走真实平台**（与 `bt_make_name_icons.py` 同一条坑）：
`QT_QPA_PLATFORM=offscreen` 下 Qt 换了一套不含系统字体的字体库，
中文会画成一个个空心方块（豆腐块），而像素护栏查不出（图上确实有东西）。
所以本脚本第一件事是把该变量**丢掉**，并且要在建 `QApplication` **之前**丢 ——
`_btprelude` 会 `setdefault` 一个 offscreen 进去，晚丢就不起作用了。

另一件必须做的事：**把网络与磁盘探测打桩**。
`MainWindow` 一 show 就会 `_start_fetch_versions` 去抓 182 个组件的版本，
还会逐卡 `_detect_status` 探盘 —— 不打桩的话截一张图要等好几分钟网络。
打桩还有个附带好处：卡片上的状态栏是空的，**不会把维护者本机装了哪些版本
（jdk 21.0.6 / git 2.52.0 之类）拍进一张要发布到 GitHub 的图里**。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# ---- 必须排在建 QApplication 之前：抢在 _btprelude 的 setdefault 之前把 offscreen 丢掉
_dropped = os.environ.pop("QT_QPA_PLATFORM", None)
if _dropped is not None:
    print(f"已移除 QT_QPA_PLATFORM={_dropped}（本脚本必须走真实平台，否则中文是豆腐块）")

from PySide6.QtCore import QPoint                        # noqa: E402
from PySide6.QtGui import QImage, QPainter                # noqa: E402
from PySide6.QtWidgets import QApplication                # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

app = QApplication(sys.argv)
print("Qt 平台 =", app.platformName())

import _btprelude  # noqa: E402  必须在 QApplication 之后 import（见模块 docstring）
import main        # noqa: E402

# 打桩：不联网抓版本、不探盘（见 docstring 里的两条理由）
main.ComponentCard._detect_status = lambda self, *a, **k: None
main.MainWindow._start_fetch_versions = lambda self, *a, **k: None

WIDTH, HEIGHT = 1563, 1038          # 与上一版预览图同尺寸，README 里按 width=860 展示
win = main.MainWindow()
win.resize(WIDTH, HEIGHT)
win.show()
for _ in range(12):                 # 等分帧建卡（启动画面那套）跑完
    app.processEvents()
    time.sleep(0.12)
app.processEvents()

img = QImage(WIDTH, HEIGHT, QImage.Format_ARGB32)
img.fill(0)
painter = QPainter(img)
win.render(painter, QPoint(0, 0))
painter.end()

out = REPO_ROOT / "assets" / "byte-tools-pt.png"
img.save(str(out))
print(f"已写出 {out}（{out.stat().st_size} 字节，{img.width()}x{img.height()}）")
print("页签：", [win.tabs.tabText(i) for i in range(win.tabs.count())])
print("核对：图上的页签计数与状态栏组件数应当与 `build_components()` 现算值一致")
