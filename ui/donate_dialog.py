"""「支持作者」对话框（从 main.py 抽出，规则 R30）。

资产目录由构造参数注入；默认优先取 ``sys._MEIPASS``（onefile 数据根），
源码运行回落到仓库根下的 assets/。
"""
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QPixmap
from core.i18n import tr
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


def default_assets_dir() -> Path:
    """数据资源根下的 assets/。

    onefile 打包后模块在 PYZ 里，``__file__`` 的父目录不一定是数据根；
    ``sys._MEIPASS`` 才是 PyInstaller 声明的解包目录，优先用它。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


class DonateDialog(QDialog):
    """支持作者：微信 / 支付宝，各渠道展示对应二维码。"""

    CHANNELS = [
        ("微信", "#07C160", "wechat.png"),
        ("支付宝", "#1677FF", "alipay.png"),
        # ("QQ", "#EB1923", "qq.png"),
    ]

    def __init__(self, parent=None, assets_dir: Path = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("支持作者"))
        self.setMinimumSize(460, 460)
        self.setObjectName("donateDialog")
        self._assets_dir = Path(assets_dir) if assets_dir else default_assets_dir()
        self._build_ui()
        self._show_qr(*self.CHANNELS[0])

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(14)

        tip = QLabel(tr("如果本工具对你有所帮助，欢迎请作者一杯咖啡 ☕"))
        tip.setAlignment(Qt.AlignCenter)
        tip.setStyleSheet("font-size:14px;color:#444;")
        v.addWidget(tip)

        row = QHBoxLayout()
        row.setSpacing(14)
        self._buttons = []  # type: list[QPushButton]
        for name, color, filename in self.CHANNELS:
            btn = QPushButton(tr(name))
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setCheckable(True)
            btn.setStyleSheet(
                f"QPushButton{{background:{color};color:white;border:none;border-radius:8px;padding:10px 20px;font-weight:600;}}"
                f"QPushButton:checked{{background:{color};border:2px solid #333;}}"
                f"QPushButton:hover{{background:{color};}}"
            )
            btn.clicked.connect(
                lambda _=False, n=name, c=color, f=filename: self._show_qr(n, c, f))
            row.addWidget(btn)
            self._buttons.append(btn)
        v.addLayout(row)

        self._channel_label = QLabel("")
        self._channel_label.setAlignment(Qt.AlignCenter)
        self._channel_label.setStyleSheet("font-size:15px;font-weight:600;color:#333;")
        v.addWidget(self._channel_label)

        self.qr_view = QLabel(tr("请选择下方渠道"))
        self.qr_view.setAlignment(Qt.AlignCenter)
        self.qr_view.setMinimumHeight(260)
        self.qr_view.setStyleSheet(
            "background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;color:#888;padding:10px;"
        )
        v.addWidget(self.qr_view, stretch=1)

        note = QLabel(tr("扫码打赏，感谢您的支持！"))
        note.setAlignment(Qt.AlignCenter)
        note.setStyleSheet("font-size:12px;color:#999;")
        v.addWidget(note)

    def _show_qr(self, channel: str, color: str = "", filename: str = "") -> None:
        for btn in self._buttons:
            btn.setChecked(btn.text() == tr(channel))
        self._channel_label.setText(tr("【{channel}】收款码", channel=tr(channel)))
        if color:
            self._channel_label.setStyleSheet(
                f"font-size:15px;font-weight:600;color:{color};")

        if not filename:
            for n, c, f in self.CHANNELS:
                if n == channel:
                    filename = f
                    break

        qr_path = self._assets_dir / filename
        if qr_path.exists():
            pixmap = QPixmap(str(qr_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.qr_view.width() - 20,
                    self.qr_view.height() - 20,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.qr_view.setPixmap(scaled)
                return

        self.qr_view.clear()
        self.qr_view.setText(
            f"未找到二维码文件：\n\n{qr_path}\n\n请将 {filename} 放入 assets 目录后重启。"
        )
