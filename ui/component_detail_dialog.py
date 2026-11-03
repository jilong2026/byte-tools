"""组件详情对话框（从 main.py 抽出，规则 R30）。

自包含：只依赖组件对象的 `display_name` / `official_url` 与传入的 sections，
不读全局配置。点击外部关闭的过滤器摘除逻辑保持原样（见类内注释）。
"""
import html as _html
import re

from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


def url_netloc(url: str) -> str:
    """从 URL 里切出域名（netloc）；切不出来返回空串。"""
    try:
        import urllib.parse as _up
        return _up.urlsplit(url).netloc
    except (ValueError, TypeError, AttributeError):
        return ""


def escape_html(text: str) -> str:
    """转义要插进 QLabel 富文本的片段（组件名里可能有 & 之类）。"""
    return _html.escape(str(text or ""))


def event_global_pos(ev):
    """取鼠标事件的全局坐标（PySide6 版本差异兜底）。"""
    gp = getattr(ev, "globalPosition", None)
    if gp is not None:
        p = gp()
        return p.toPoint() if hasattr(p, "toPoint") else p
    g = getattr(ev, "globalPos", None)
    return g() if g is not None else None


class ComponentDetailDialog(QDialog):
    """组件详情：一屏说清"它是干嘛的、装完怎么用、数据在哪、平台有什么坑"。

    **点击对话框之外的任何地方自动关闭**（2026-10-12 用户要求）：给
    QApplication 挂全局事件过滤器，鼠标按下位置落在 frameGeometry 之外就 accept()。
    正文用 QTextEdit 而不是 QLabel —— 用户要能**选中复制**里面的命令与变量名。
    """

    def __init__(self, comp, sections, parent=None):
        super().__init__(parent)
        self.comp = comp
        self.setObjectName("componentDetailDialog")
        self.setWindowTitle(f"{comp.display_name} · 详情")
        self.resize(560, 520)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 12)
        v.setSpacing(10)

        head = QLabel(comp.display_name)
        head.setObjectName("detailTitle")
        head.setFont(QFont("", 14, QFont.Bold))
        v.addWidget(head)

        # 官网链接：文字里的域名从 href 现切，结构上不可能"写着 A 点进去是 B"
        official = comp.official_url
        if official:
            domain = url_netloc(official)
            addr = QLabel(
                f'官网：<a href="{official}">{escape_html(comp.display_name)} · '
                f'{escape_html(domain)}</a>')
            addr.setOpenExternalLinks(True)
            addr.setObjectName("detailHome")
            addr.setStyleSheet("color:#7a8ea3;font-size:11px;")
            addr.setToolTip(f"{official}\n点击用系统浏览器打开官方网站；"
                            f"组件本体请用卡片上的「安装 / 下载」按钮。")
            v.addWidget(addr)

        body = QTextEdit(self)
        body.setObjectName("detailBody")
        body.setReadOnly(True)
        body.setMinimumHeight(300)
        body.setHtml(self._to_html(sections))
        body.setStyleSheet(
            "background:#fbfcfe;border:1px solid #e3e8ef;border-radius:8px;"
            "padding:12px;color:#2b3640;font-size:13px;")
        v.addWidget(body, stretch=1)

        close = QPushButton("知道了")
        close.setObjectName("secondaryBtn")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)

        self._app = QApplication.instance()
        if self._app is not None:
            self._app.installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.MouseButtonPress:
            pos = event_global_pos(ev)
            if pos is not None and not self.frameGeometry().contains(pos):
                # 先摘过滤器再关窗：accept() 不走 closeEvent，只靠 closeEvent 摘除
                # 会在 QApplication 上泄漏活跃过滤器，之后所有外部点击都被吞掉。
                self._detach_app_filter()
                self.accept()
                return True
        return super().eventFilter(obj, ev)

    def _detach_app_filter(self) -> None:
        if self._app is not None:
            try:
                self._app.removeEventFilter(self)
            except RuntimeError:
                pass  # app 已析构（关窗收尾竞态）
            self._app = None

    def hideEvent(self, ev) -> None:       # noqa: N802
        self._detach_app_filter()
        super().hideEvent(ev)

    def closeEvent(self, ev) -> None:       # noqa: N802
        self._detach_app_filter()
        super().closeEvent(ev)

    @staticmethod
    def _to_html(sections) -> str:
        """[(小标题, 正文)] → HTML；Markdown 星号在此统一处理。"""
        parts = []
        for title, text in sections:
            t = _html.escape(str(text or ""))
            t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.S)
            t = t.replace("`", "")
            parts.append(f"<div style='margin-bottom:12px'>"
                         f"<div style='color:#4a7fd0;font-weight:600;"
                         f"margin-bottom:3px'>{_html.escape(str(title))}</div>"
                         f"<div style='line-height:150%'>{t}</div></div>")
        return "".join(parts) or "<div>这个组件还没有写说明。</div>"
