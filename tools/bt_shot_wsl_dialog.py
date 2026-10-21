# -*- coding: utf-8 -*-
"""出 WSL 对话框的排版截图（必须真实平台：offscreen 下中文是豆腐块）。

用法（仓库根目录，不设 QT_QPA_PLATFORM）：
    .venv/Scripts/python.exe tools/bt_shot_wsl_dialog.py

产物：%TEMP%\\wsl_dialog.png。状态文案取自本机真实探测（没装 WSL 就是"未启用"）。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
import _btprelude  # noqa: E402,F401
os.environ.pop("QT_QPA_PLATFORM", None)   # _btprelude 会设 offscreen，取图必须去掉
import main  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
dlg = main.WslDialog()
dlg.resize(640, 470)
dlg.show()
for _ in range(3):
    app.processEvents()
pm = QPixmap(dlg.size())
pm.fill(QColor("#f5f7fa"))
painter = QPainter(pm)
dlg.render(painter, QPoint(0, 0))
painter.end()
out = Path(os.environ.get("TEMP", ".")) / "wsl_dialog.png"
pm.save(str(out))
print("saved", out, pm.width(), pm.height())
dlg.close()
