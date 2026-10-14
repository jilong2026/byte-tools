r"""给"没有官方图形标识"的组件生成「白底黑字组件名」兜底图标。

用法（在仓库根目录，**不要**设 QT_QPA_PLATFORM）：
    .venv/Scripts/python.exe tools/bt_make_name_icons.py

为什么必须是真实平台：`QT_QPA_PLATFORM=offscreen` 下 Qt 换了一套不含系统字体的
字体库，`QFont("Arial")` 解析不到，drawText 会把每个字符画成 **一个空心方块（豆腐块）**。
2026-10-14 就是先在 offscreen 里生成的，产出的 5 个方块能通过任何"有没有画上东西"
的检查，肉眼一看才知道是豆腐。同一个坑见 DEVELOPMENT.md 规则 R16。

所以：**这个脚本必须走真实平台**，生成完必须肉眼看一眼（不是看像素统计）。

背景：ninja / ripgrep / yq 三个组件经穷举确认项目自己就没有图形标识
（最硬的证据是官方 Windows 二进制的 PE 资源段里没有任何 ICON，
见 bt_icon_assets_tests.py 的 IconCoverage.NAME_TEXT_FALLBACK）。
用户裁定用组件名做白底黑字的图标兜底。

产物规格：256×256 PNG，底色 #FFFFFF、字色 #000000、Arial Bold 居中，
自动缩字号让文字宽度占满画布 84%。文件名就是组件 key（`<key>.png`）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_platform_ok = os.environ.pop("QT_QPA_PLATFORM", None)
if _platform_ok is not None:
    print(f"警告：已移除 QT_QPA_PLATFORM={_platform_ok}，本脚本必须在真实平台下跑")

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)

from PySide6.QtCore import Qt                       # noqa: E402
from PySide6.QtGui import (QColor, QFont,           # noqa: E402
                           QFontMetricsF, QImage, QPainter)
from PySide6.QtWidgets import QApplication          # noqa: E402

import main                                          # noqa: E402

SIZE = 256
INK = QColor("#000000")
PAPER = QColor("#FFFFFF")
# 画布上的文字宽度占比。0.84 是"填得满"与"别顶到边"之间的折中。
FILL = 0.84
# 组件的显示名里可能带括号补充（如 `ripgrep (rg)`）；图标只要名字本体。
def label_of(display_name: str) -> str:
    return display_name.split("(")[0].strip()


def render(text: str) -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32)
    img.fill(PAPER)
    target = SIZE * FILL
    px = 40.0
    for _ in range(80):                     # 迭代逼近：让文字宽度落在 target 的 93%~100%
        font = QFont("Arial")
        font.setBold(True)
        font.setPixelSize(max(6, int(round(px))))
        width = QFontMetricsF(font).horizontalAdvance(text)
        if width <= target and width >= target * 0.93:
            break
        px = max(6.0, min(220.0, px * (target / width if width else 1.0)))
    font = QFont("Arial")
    font.setBold(True)
    font.setPixelSize(max(6, int(round(px))))
    painter = QPainter(img)
    painter.setFont(font)
    painter.setPen(INK)
    painter.drawText(img.rect(), Qt.AlignCenter, text)
    painter.end()
    return img


def main_run() -> int:
    app = QApplication(sys.argv)            # noqa: F841  必须存在才能建 QPainter

    # 登记表只有一份，就在护栏文件里 —— 这里读它，避免两处各写一份而漂移。
    # ⚠ 必须在上面的 QApplication 之后 import：bt_icon_assets_tests 会 import
    # _btprelude，而 _btprelude 用 setdefault 把 QT_QPA_PLATFORM 设成 offscreen。
    # QApplication 已经建好之后再改这个变量就不起作用了。
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bt_icon_assets_tests", Path(REPO) / "tests" / "bt_icon_assets_tests.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)            # type: ignore[union-attr]
    keys = sorted(mod.IconCoverage.NAME_TEXT_FALLBACK)

    comps = {c.key: c for c in main.build_components()}
    out_dir = main.icon_asset_dir()
    for key in keys:
        comp = comps.get(key)
        if comp is None:
            print(f"跳过 {key}：不是组件 key")
            continue
        text = label_of(comp.display_name)
        img = render(text)
        path = out_dir / f"{key}.png"
        img.save(str(path), "PNG")
        print(f"{key:10s} 文字={text!r:12s}  -> {path.name} {path.stat().st_size}B")
    print("\n⚠ 生成完请**肉眼**打开这几张图确认是正常字形、不是空心方块（豆腐块）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_run())
