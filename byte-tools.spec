# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ByteTools.

跨平台构建脚本，在 Windows/macOS/Linux 上分别运行：
    pyinstaller byte-tools.spec

产物路径：
    dist/ByteTools/ByteTools.exe       # Windows 目录内可执行文件（onedir，启动零解压）
    dist/ByteTools/ByteTools           # Linux 目录内可执行文件
    dist/ByteTools.app                 # macOS .app bundle

切 onefile（旧版，启动需解压 ~119MB 到 %TEMP%）：
    EXE 的 exclude_binaries=True 改成 False，删掉 COLLECT 段，
    macOS BUNDLE 入参从 coll 改回 exe。

启动画面：应用内 SplashScreen（分帧建卡时显示"正在加载组件 N/87…"）。
⚠ 2026-10-13 实测：PyInstaller 自带 Splash 在本项目**不可用** —— 它需要完整
Tcl/Tk 运行时（_tk_data、tk86t.dll、tcl86t.dll、ttk/utils.tcl…），而我们为减
体积排除了 tkinter；逐个补文件是无底洞（连修 4 轮仍报新缺文件），且与 Qt 主题
冲突。启动画面由应用内 SplashScreen 承担，解压阶段的画面由 onedir 的零解压消除。
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

# 2026-10-13：PyInstaller splash 需要完整 Tcl/Tk 运行时（_tk_data、tk86t.dll、
# tcl86t.dll、ttk/*.tcl…），与本项目排除 tkinter 冲突，实测连修 4 轮仍报新缺文件，
# 放弃。保持 tkinter 排除。
extra_binaries = []
extra_datas = []

# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------
a = Analysis(
    ['main.py'],
    pathex=[str(SPEC_DIR)],
    binaries=extra_binaries,     # 2026-10-13：tkinter 的 tcl86t.dll / tk86t.dll（splash 需要）
    datas=datas + extra_datas,   # tkinter 的 _tk_data（text.tcl 等，splash 需要）
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不需要的大模块
        "tkinter",     # 2026-10-13 复盘：tkinter 必须排除（PyInstaller splash 不可用，
                       # 见文件头注释）。当初为 splash 临时放行，实测连修 4 轮仍报
                       # 缺 Tcl/Tk 文件，已回滚。
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
# EXE（onedir 模式：exclude_binaries=True，二进制由 COLLECT 收集到同一目录）
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,            # UPX 压缩减小体积，减少杀软扫描与磁盘 IO 时间
    upx_exclude=[        # 排除已知与 UPX 不兼容的 DLL（PySide6/Qt 官方建议）
        "Qt6*.dll",
        "Qt6*.pyd",
        "PySide6",
        "shiboken6",
    ],
    runtime_tmpdir=None,
    console=False,       # GUI 应用，不显示黑色控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_WIN) if sys.platform == "win32" and ICON_WIN.exists() else None,
    exclude_binaries=True,   # 二进制不打包进 exe，由 COLLECT 收集到同目录
)

# ---------------------------------------------------------------------------
# COLLECT（onedir 目录：exe + 所有二进制 + 静态资源）
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    # 不指定 icon：COLLECT 不接受 icon 参数
)

# ---------------------------------------------------------------------------
# macOS .app bundle
# ---------------------------------------------------------------------------
if sys.platform == "darwin":
    app = BUNDLE(
        coll,           # onedir 模式下 BUNDLE 入参从 exe 改成 coll
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
