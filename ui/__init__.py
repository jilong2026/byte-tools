"""Qt 界面组件包（规则 R30）。

目前收纳已经从 main.py 抽出的自包含对话框；MainWindow / ComponentCard
仍留在 main.py，拆分需单独分支 + 真机演练。
"""
from .component_detail_dialog import ComponentDetailDialog, escape_html, event_global_pos, url_netloc
from .donate_dialog import DonateDialog, default_assets_dir

__all__ = [
    "ComponentDetailDialog",
    "DonateDialog",
    "default_assets_dir",
    "escape_html",
    "event_global_pos",
    "url_netloc",
]
