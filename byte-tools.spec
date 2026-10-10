# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ByteTools.

跨平台构建脚本，在 Windows/macOS/Linux 上分别运行：
    pyinstaller byte-tools.spec

产物路径：
    dist/ByteTools            # Linux 单可执行文件
    dist/ByteTools.exe       # Windows 单可执行文件
    dist/ByteTools.app       # macOS .app bundle
"""
import sys
from pathlib import Path

APP_NAME = "ByteTools"
SPEC_DIR = Path(SPECPATH).resolve() if 'SPECPATH' in globals() else Path.cwd()

# Windows 的 exe 图标必须是 .ico（PyInstaller 不接受 PNG），由 assets/byte-tools.png 生成，
# 重新生成方式见 CODE_WIKI.md 7.4。macOS/Linux 暂不设图标，保持原有 CI 行为。
ICON_WIN = SPEC_DIR / "assets" / "byte-tools.ico"


def _app_version() -> str:
    """从 main.py 读 APP_VERSION —— 打包产物与界面显示必须是同一个版本号。

    不 import main：那是个要拉 PySide6 的 GUI 模块，spec 里只想要一串常量，
    用正则取比 import 便宜也不会被它的导入期副作用带崩。
    读不到时返回 0.0.0（宁可显示一个明显的假版本，也不要在打包阶段炸）。
    """
    import re

    src = (SPEC_DIR / "main.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.M)
    return m.group(1) if m else "0.0.0"


APP_VERSION = _app_version()

# 打进包里的静态资源（打赏二维码、应用截图等）
datas = [
    (str(SPEC_DIR / "assets"), "assets"),
]

hidden_imports = [
    # PySide6 相关子模块
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    # requests 依赖
    "requests",
    "urllib3",
    "charset_normalizer",
    "certifi",
    "idna",
]

# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------
a = Analysis(
    ['main.py'],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不需要的大模块
        "tkinter",
        "test",
        "unittest",
        "PySide6.QtNetwork",
        "PySide6.QtOpenGL",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtSql",
        "PySide6.QtMultimedia",
        "PySide6.Qt3DCore",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

# ---------------------------------------------------------------------------
# EXE / 单文件产物
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX 在 mac 上会导致启动崩溃，禁用
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # GUI 应用，不显示黑色控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_WIN) if sys.platform == "win32" and ICON_WIN.exists() else None,
)

# ---------------------------------------------------------------------------
# macOS .app bundle
# ---------------------------------------------------------------------------
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name=f"{APP_NAME}.app",
        # icon=str(SPEC_DIR / "assets" / "icon.icns"),
        bundle_identifier="com.rgh.byte-tools",
        info_plist={
            # 中文名与界面标题栏一致（以前这里写的是第三个名字，
            # 且版本号常年停在 1.0.0 —— macOS「关于」面板会显示一个从没发布过的版本）。
            "CFBundleName": "字节工具箱",
            "CFBundleDisplayName": "字节工具箱",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.13.0",
        },
    )
