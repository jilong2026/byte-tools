"""Qt 界面组件包（规则 R30）。

目前收纳已经从 main.py 抽出的自包含对话框；MainWindow / ComponentCard
仍留在 main.py，拆分需单独分支 + 真机演练。
"""
from .donate_dialog import DonateDialog, default_assets_dir

__all__ = ["DonateDialog", "default_assets_dir"]
