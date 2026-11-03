"""最小国际化基建（规则 R30）。

范围与边界（2026-11-03）：
- 以**中文原文为键**做查表，默认语言 zh（未命中时原样返回中文），
  因此未翻译的字符串永远有兜底，不会出现空文案；
- 语言由 `BYTE_TOOLS_LANG` 决定（en / zh），也可 `set_language()` 显式切换；
- 已迁移：`ui/donate_dialog.py`。main.py 里尚有大量中文文案，
  按"改到哪个模块就顺手迁移"的方式增量推进，不做一次性全量替换。

Qt .qm 翻译文件若存在（assets/i18n/byte-tools_<lang>.qm），
`install_translator(app)` 会加载它，为后续全面迁移留好接口。
"""
from __future__ import annotations

import os
from typing import Dict, Optional

_STRINGS: Dict[str, Dict[str, str]] = {
    "en": {
        "支持作者": "Support the author",
        "如果本工具对你有所帮助，欢迎请作者一杯咖啡 ☕":
            "If this tool saves you time, you are welcome to buy the author a coffee ☕",
        "微信": "WeChat",
        "支付宝": "Alipay",
        "【{channel}】收款码": "{channel} payment QR code",
        "请选择下方渠道": "Choose a channel below",
        "扫码打赏，感谢您的支持！": "Scan to tip. Thanks for your support!",
        "未找到二维码文件：\n\n{qr_path}\n\n请将 {filename} 放入 assets 目录后重启。":
            "QR image not found:\n\n{qr_path}\n\nPut {filename} into the assets directory and restart.",
        "知道了": "Got it",
    },
}

_LANG: Optional[str] = None


def current_language() -> str:
    global _LANG
    if _LANG is None:
        _LANG = (os.environ.get("BYTE_TOOLS_LANG") or "zh").lower()
    return _LANG


def set_language(lang: str) -> None:
    global _LANG
    _LANG = (lang or "zh").lower()


def tr(text: str, **kwargs) -> str:
    """按当前语言翻译；未命中返回原文（中文），并支持 `{name}` 占位。"""
    lang = current_language()
    template = _STRINGS.get(lang, {}).get(text, text) if lang != "zh" else text
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


def install_translator(app) -> bool:
    """若存在 .qm 文件则加载（可选）。返回是否加载成功。"""
    try:
        from pathlib import Path
        from PySide6.QtCore import QTranslator

        qm = Path(__file__).resolve().parents[1] / "assets" / "i18n" / f"byte-tools_{current_language()}.qm"
        if not qm.is_file():
            return False
        translator = QTranslator(app)
        if translator.load(str(qm)):
            app.installTranslator(translator)
            app._bt_translator = translator  # 防止被 GC
            return True
    except Exception:  # noqa: BLE001 - 翻译失败必须不影响启动
        pass
    return False
