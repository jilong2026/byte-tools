# -*- coding: utf-8 -*-
"""
编程开发环境自动装配小工具 By rgh
==========================

Copyright (c) 2026 rgh
Licensed under the MIT License. See LICENSE file (or the README) for details.

一个基于 PySide6 的跨平台桌面 GUI 工具，用于自动下载、解压并配置常用开发环境组件，
内置 24 个组件：JDK / Maven / Tomcat / MySQL / Python / Node.js / Git / Miniconda /
Go / Gradle / Bun / Docker / MongoDB / PostgreSQL / kubectl / Jenkins /
RabbitMQ / Kafka / RocketMQ / Pulsar / ActiveMQ / Nacos / Seata / Elasticsearch。

下载遵循 R1 规则：国内镜像优先 + 多源故障转移 + 末位官网回退（详见 DEVELOPMENT.md）。

用法：
    python main.py            # 直接启动
    一键启动项目.bat          # Windows 一键启动（自动建虚拟环境+装依赖）
"""

from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import traceback
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# PySide6 依赖
# ---------------------------------------------------------------------------
try:
    from PySide6.QtCore import (
        QEvent,
        QObject,
        QPoint,
        QSize,
        Qt,
        QThread,
        QTimer,
        Signal,
    )
    from PySide6.QtGui import (
        QAction,
        QColor,
        QCursor,
        QFont,
        QIcon,
        QPainter,
        QPalette,
        QPen,
        QPixmap,
        QDesktopServices,
    )
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QCompleter,
        QDialog,
        QFileDialog,
        QFrame,
        QGraphicsDropShadowEffect,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpacerItem,
        QSplitter,
        QStackedWidget,
        QTabWidget,
        QTextEdit,
        QToolTip,
        QVBoxLayout,
        QWidget,
    )
    from PySide6.QtCore import QSortFilterProxyModel
except ImportError:  # pragma: no cover
    print("缺少依赖 PySide6，请先执行:  pip install -r requirements.txt")
    raise


# ---------------------------------------------------------------------------
# 全局常量与工具函数
# ---------------------------------------------------------------------------
APP_NAME = "字节-开发环境与工具自动安装"
GITHUB_URL = "https://github.com/jilong2026/byte-tools"
CONFIG_DIR = Path.home() / ".env-tools"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 当前操作系统标识：'Windows' / 'Darwin' / 'Linux'
CURRENT_OS = platform.system()
# 当前 CPU 架构（大致判断，用于挑选二进制包）
MACHINE = platform.machine().lower()
IS_ARM = ("arm" in MACHINE) or ("aarch64" in MACHINE)


def human_size(num: float) -> str:
    """把字节数转换为可读字符串。"""
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def ensure_dir(path: Path) -> None:
    """确保目录存在。"""
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 组件定义
# ---------------------------------------------------------------------------
@dataclass
class ComponentVersion:
    """描述一个组件版本对应的下载 URL 及归档格式。"""

    version: str
    url_map: Dict[str, str]  # 单 URL 模式：{"Windows": url, "Darwin": url, "Linux": url}
    archive_map: Dict[str, str] = field(default_factory=dict)  # 归档类型：zip / tar.gz
    # 多源故障转移模式（R1）：按操作系统键映射的 URL 列表（镜像优先 + 末位官网）。
    # 与 url_map 二选一：若当前系统的 url_list_map 非空，则 urls_for_current() 返回该列表；
    # 否则回退到 url_map 的单 URL 模式（仅少数无国内镜像的组件，如 kubectl）。
    url_list_map: Dict[str, List[str]] = field(default_factory=dict)

    def url_for_current(self) -> Optional[str]:
        """当前系统的首选下载地址：多源模式取列表首个（优先级最高的镜像），单源模式取该源。"""
        urls = self.urls_for_current()
        return urls[0] if urls else None

    def urls_for_current(self) -> List[str]:
        """
        多源故障转移模式：返回当前系统的下载 URL 列表，按 R1 优先级排序。

        若 url_list_map 配置了当前系统的非空列表，则返回该列表（镜像在前 + 末位官网）；
        否则回退到单 URL 模式，返回 [url_map[CURRENT_OS]] 或空列表。
        """
        if CURRENT_OS in self.url_list_map and self.url_list_map[CURRENT_OS]:
            return list(self.url_list_map[CURRENT_OS])
        url = self.url_map.get(CURRENT_OS)
        return [url] if url else []

    def archive_for_current(self) -> str:
        if CURRENT_OS in self.archive_map:
            return self.archive_map[CURRENT_OS]
        # 兼容多源模式：从 urls_for_current() 的第一个 URL 推断归档类型
        urls = self.urls_for_current()
        url = urls[0] if urls else ""
        if url.endswith(".zip"):
            return "zip"
        if url.endswith(".tar.gz") or url.endswith(".tgz"):
            return "tar.gz"
        return "zip"


@dataclass
class Component:
    """一个开发环境组件的抽象。"""

    key: str  # 内部标识，例如 "jdk"
    display_name: str  # 显示名称
    env_var: Optional[str]  # 需要设置的 XXX_HOME 环境变量名，无则为 None
    path_subdir: str  # 需要加入 PATH 的子目录，一般为 "bin"（Windows 上也可能是 "Scripts"）
    exec_name: Optional[str] = None  # 用于探测的可执行文件名，不含扩展名
    version_args: List[str] = field(default_factory=lambda: ["--version"])  # 获取版本号的参数
    # 是否允许在探测阶段真的执行该组件的命令来取版本号。
    # 启动脚本型组件（Nacos / Seata / Kafka / RocketMQ / RabbitMQ）不认版本参数，
    # 一执行就会把中间件服务拉起来（还会弹窗），必须置 False：只判定存在，不执行。
    version_probe: bool = True
    versions: List[ComponentVersion] = field(default_factory=list)
    # 安装器模式：某些组件（如 Miniconda）下载的是安装器而非归档，需要静默执行安装器
    installer_mode: bool = False
    # 是否允许并存多个安装版本，并在界面切换"当前生效版本"。
    # 判据：归档解压安装（非 installer_mode）+ 靠 XXX_HOME / PATH 生效的 PATH 型组件。
    # 由 build_components() 末尾按 MULTI_VERSION_KEYS 统一赋值，不要在构造处手写。
    multi_version: bool = False
    # 安装器静默安装参数：按 CURRENT_OS 键取。执行时会附加安装目标目录参数
    installer_args: Dict[str, List[str]] = field(default_factory=dict)
    # 当某平台不支持自动下载时，输出给用户的友好提示文本。
    # 例：Docker 在 Windows 上无 static binary，需引导用户去 Docker Desktop 官网下载。
    # 不配置该字段时，回退到通用提示"当前系统 X 无可用下载地址"。
    unsupported_platform_hint: Optional[str] = None
    # 界面 Tab 分组名，取值必须是 COMPONENT_CATEGORIES 之一。
    # 由 build_components() 末尾按 COMPONENT_CATEGORY_OF 统一赋值，不要在构造处手写。
    category: str = ""

    def install_dir(self, version: str) -> Path:
        """返回该版本组件的解压安装目录。"""
        return CONFIG_DIR / self.key / f"{self.key}-{version}"

    def exec_path_in_home(self, home: str) -> Optional[Path]:
        """在给定 XXX_HOME 目录下查找可执行文件。"""
        if not self.exec_name:
            return None
        # Windows 上很多组件只带脚本包装器（catalina.bat / mvn.cmd 等），
        # 只找 .exe 会漏检，故按常见 PATHEXT 扩展名依次尝试。
        suffixes = [".exe", ".bat", ".cmd", ".com", ""] if CURRENT_OS == "Windows" else [""]
        # 依次尝试 path_subdir、bin、Scripts、根目录
        candidates_dir = [self.path_subdir, "bin", "Scripts", "condabin", ""]
        for sub in candidates_dir:
            base = Path(home) / sub if sub else Path(home)
            for suf in suffixes:
                cand = base / (self.exec_name + suf)
                if cand.exists():
                    return cand
        return None

    def _detect_by_home_dir(self) -> "DetectResult":
        """没有可执行文件可探测的组件（如 Jenkins：只有一个 war 包）的兜底探测。

        这类组件的 exec_name 为 None，走不了常规的「XXX_HOME 里找可执行文件」，
        也不能靠 PATH 找到命令；只要本工具写下的 XXX_HOME 指向自己的安装目录，
        就认定「已配置」，否则界面永远显示未安装，与实际情况不符。
        """
        if not self.env_var:
            return DetectResult(False)
        home = EnvManager.get(self.env_var)
        if not home:
            return DetectResult(False)
        home_path = Path(os.path.expandvars(home))
        component_root = CONFIG_DIR / self.key
        if home_path.is_dir() and EnvManager._under_root(str(home_path), str(component_root)):
            return DetectResult(True, source=self.env_var, home=str(home_path))
        return DetectResult(False)

    def detect(self, probe_version: bool = True) -> "DetectResult":
        """探测该组件是否已在系统中可用。

        入参 probe_version: bool  是否真的执行外部命令去取版本号。界面构建卡片时传
        False（先只显示「已配置（来源）」，版本字符串随后异步回填），否则任何一个
        卡住的外部命令都会把主窗口拖到打不开。
        """
        if not self.exec_name:
            return self._detect_by_home_dir()
        allow_probe = probe_version and self.version_probe

        # 1) 优先通过 XXX_HOME 环境变量判断
        if self.env_var:
            home = EnvManager.get(self.env_var)
            if home:
                exe = self.exec_path_in_home(home)
                if exe is not None:
                    return DetectResult(
                        installed=True,
                        source=self.env_var,
                        home=home,
                        exe_path=str(exe),
                        version_text=_probe_version(str(exe), self.version_args) if allow_probe else "",
                    )

        # 2) 通过 PATH 中的可执行文件
        # exec_name 自带扩展名时（Nacos 的 startup.cmd / startup.sh）不再补 .exe
        need_exe = CURRENT_OS == "Windows" and not os.path.splitext(self.exec_name)[1]
        exe_name_final = self.exec_name + (".exe" if need_exe else "")
        which = shutil.which(exe_name_final) or shutil.which(self.exec_name)
        if which:
            return DetectResult(
                installed=True,
                source="PATH",
                exe_path=which,
                version_text=_probe_version(which, self.version_args) if allow_probe else "",
            )

        return DetectResult(False)

    def installed_dirs(self) -> List[Path]:
        """本组件在 CONFIG_DIR/<key> 下真实存在的安装目录（排除下载缓存与隐藏目录）。"""
        root = CONFIG_DIR / self.key
        if not root.is_dir():
            return []
        return sorted(
            p
            for p in root.iterdir()
            if p.is_dir() and p.name != "downloads" and not p.name.startswith(".")
        )

    def resolve_uninstall_target(self, version: str) -> Tuple[Optional[Path], str]:
        """把「下拉框选中的版本」校正为磁盘上真正装着的那个目录。

        离线默认清单可能落后于实际安装的版本（在线版本抓取失败时尤其明显），
        此时按选中版本去删会删一个不存在的目标，而目录、XXX_HOME、PATH 全都留着
        —— 界面因此仍显示「已配置」。返回 (目标目录或 None, 给用户的中文说明)。
        """
        exact = self.install_dir(version)
        if exact.is_dir():
            return exact, ""

        component_root = CONFIG_DIR / self.key
        # XXX_HOME 指向本组件目录时以它为准（它是安装/配置那一步写下的）
        if self.env_var:
            home = EnvManager.get(self.env_var)
            if home:
                home_path = Path(os.path.expandvars(home))
                if home_path.is_dir() and EnvManager._under_root(
                    str(home_path), str(component_root)
                ):
                    return home_path, f"按 {self.env_var} 定位到实际安装目录 {home_path.name}"

        dirs = self.installed_dirs()
        if len(dirs) == 1:
            return dirs[0], f"所选版本 {self.key}-{version} 未安装，改为卸载实际存在的 {dirs[0].name}"
        if len(dirs) > 1:
            names = "、".join(d.name for d in dirs)
            return None, f"存在多个已安装版本（{names}），请先在下拉框中选择具体版本"
        return None, f"未找到 {self.key}-{version} 的安装目录，也没有其他已安装版本"

    def uninstall(self, version: str) -> str:
        """
        卸载指定版本：删除安装目录、移除本工具写入的 XXX_HOME、清理属于本组件的 PATH 条目。

        入参 version: str  下拉框选中的版本号；与实际安装版本不一致时会自动校正目标
        返回: str           卸载结果摘要（中文，多步骤用中文分号分隔）

        说明:
          - XXX_HOME 只有落在本组件目录（CONFIG_DIR/<key>）内才删除，用户自己的安装不动它；
          - PATH 按「本组件目录之内」整体清理，因此 path_subdir 为空的组件（如 bun）
            以及目录已被手工删除的历史条目都能一并清掉；
          - 安装器模式（如 Miniconda）跳过目录删除，仅清理环境变量与 PATH。
        """
        summary_parts: List[str] = []
        install_path, note = self.resolve_uninstall_target(version)
        if install_path is None and len(self.installed_dirs()) > 1:
            # 装了多个版本又定位不到具体是哪一个：整个停手。
            # 此时若继续按组件根清 PATH，会把用户没选中的那些版本的条目一起删掉。
            return note
        if note:
            summary_parts.append(note)
        component_root = CONFIG_DIR / self.key

        # 1. 删除安装目录（安装器模式跳过，由安装器自行管理位置）
        if self.installer_mode:
            summary_parts.append("安装器模式，跳过安装目录删除（如需彻底清理请用对应卸载工具）")
        elif install_path is not None:
            try:
                shutil.rmtree(install_path)
                summary_parts.append(f"已删除安装目录：{install_path}")
            except Exception as exc:
                summary_parts.append(f"删除安装目录失败：{exc}")

        # 2. 删除 XXX_HOME 环境变量（仅当它落在本组件目录内，避免误删用户其他配置）
        if self.env_var:
            current_home = EnvManager.get(self.env_var)
            points_at_component = bool(current_home) and (
                (
                    install_path is not None
                    and EnvManager._same_path(current_home, str(install_path))
                )
                or EnvManager._under_root(current_home, str(component_root))
            )
            if points_at_component:
                try:
                    if CURRENT_OS == "Windows":
                        EnvManager.remove_windows_user_env(self.env_var)
                    else:
                        EnvManager.remove_unix_env(self.env_var)
                    summary_parts.append(f"已删除环境变量：{self.env_var}")
                except Exception as exc:
                    summary_parts.append(f"删除环境变量 {self.env_var} 失败：{exc}")
            elif current_home:
                # XXX_HOME 指向别处，可能是用户系统已有配置，不动它
                summary_parts.append(
                    f"环境变量 {self.env_var} 指向其他目录（{current_home}），未删除"
                )

        # 3. 清理 PATH 中位于本组件目录内的条目（不再依赖 path_subdir 是否配置）
        try:
            if CURRENT_OS == "Windows":
                removed = EnvManager.remove_windows_path_entries_under(str(component_root))
            else:
                removed = EnvManager.remove_unix_path_entries_under(str(component_root))
            if removed:
                summary_parts.append("已从 PATH 移除：" + "、".join(removed))
            else:
                summary_parts.append("PATH 中没有本组件的条目")
        except Exception as exc:
            summary_parts.append(f"清理 PATH 失败：{exc}")

        return "；".join(summary_parts) if summary_parts else "无需卸载"


def version_from_install_dir(comp: "Component", path: Path) -> Optional[str]:
    """从安装目录名反解版本号；目录名必须符合 `<key>-<version>`，否则 None。

    入参 comp: Component  用它的 key 做前缀判定（避免把 python-3.12 算到 jdk 头上）
    入参 path: Path       磁盘上的目录对象
    返回:      Optional[str]  版本号；不符合命名约定（downloads、残缺名）返回 None

    说明: 安装落位时目录被统一重命名为 install_dir(version)，所以这里与写入端共用一套约定。
    """
    prefix = f"{comp.key}-"
    name = path.name
    if not name.startswith(prefix):
        return None
    return name[len(prefix):] or None


def installed_versions(comp: "Component") -> List[Tuple[str, Path]]:
    """该组件在磁盘上真实装着的版本，按语义版本**降序**（最新在前）。

    入参 comp: Component
    返回: List[Tuple[str, Path]]  (版本号, 安装目录)

    说明: 排序必须走 _sort_semver_desc。用 str.sort() 会得到 jdk-8 > jdk-21 的错序，
          "配置环境变量"和"卸载后自动切到剩余最高版本"都会挑错版本。
    """
    pairs: List[Tuple[str, Path]] = []
    for path in comp.installed_dirs():
        ver = version_from_install_dir(comp, path)
        if ver:
            pairs.append((ver, path))
    order = {v: i for i, v in enumerate(_sort_semver_desc([v for v, _p in pairs]))}
    return sorted(pairs, key=lambda p: order[p[0]])


@dataclass
class DetectResult:
    """系统级探测结果。"""

    installed: bool
    source: str = ""  # "JAVA_HOME" / "PATH" / ""
    home: str = ""
    exe_path: str = ""
    version_text: str = ""


# 静默执行外部命令用的常量（提前取好，避免依赖 subprocess 属性被替换的场景）
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
STDIN_DEVNULL = getattr(subprocess, "DEVNULL", -3)


def _probe_version(exe: str, args: List[str]) -> str:
    """调用可执行文件抓取版本号；失败返回空串。

    只该给「确定是版本查询命令」的组件用：启动脚本（kafka-server-start、
    seata-server、startup.cmd 等）不认版本参数，`args` 为空时更是会直接把服务
    拉起来，所以空参数一律不执行。
    Windows 上带 CREATE_NO_WINDOW + stdin=DEVNULL：不弹控制台窗口，也不让被
    探测的程序因为等 stdin 而卡住调用方。
    """
    if not args:
        return ""
    try:
        kwargs: Dict[str, int] = {}
        if CURRENT_OS == "Windows":
            kwargs["creationflags"] = CREATE_NO_WINDOW
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            stdin=STDIN_DEVNULL,
            **kwargs,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        line = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
        return line[:80]
    except Exception:
        return ""


class VersionProbeWorker(QThread):
    """在后台线程跑一次版本探测。

    外部命令可能耗时甚至卡死（等输入、被杀毒拦截），放在 UI 线程里会让主窗口
    打不开，所以卡片的版本号一律异步回填。
    """

    done = Signal(str)  # 版本号文本，取不到为空串

    def __init__(self, exe: str, args: List[str], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.exe = exe
        self.args = args

    def run(self) -> None:
        self.done.emit(_probe_version(self.exe, self.args))


# ---------------------------------------------------------------------------
# R1 镜像源与故障转移参数（详见 DEVELOPMENT.md 规则 R1）
# ---------------------------------------------------------------------------
# 国内镜像源基址表（按稳定性与速度综合排序）：(标识, 基址)
# 所有 URL 构造器必须通过 _mb(标识) 取基址，不要在本表以外硬编码镜像域名。
MIRROR_BASES: List[tuple] = [
    ("huaweicloud",    "https://repo.huaweicloud.com"),
    ("huaweicloud-py", "https://mirrors.huaweicloud.com"),   # Python 发行包在 mirrors 子域
    ("tuna",           "https://mirrors.tuna.tsinghua.edu.cn"),
    ("aliyun",         "https://mirrors.aliyun.com"),
    ("nju",            "https://mirrors.nju.edu.cn"),
    ("ustc",           "https://mirrors.ustc.edu.cn"),
    ("bfsu",           "https://mirrors.bfsu.edu.cn"),
    ("tencent",        "https://mirrors.cloud.tencent.com"),
    ("sjtug",          "https://mirrors.sjtug.org"),
    ("npmmirror",      "https://registry.npmmirror.com"),
    ("daocloud-files", "https://files.m.daocloud.io"),       # 只对少数白名单域名反代
]
_MIRROR_BY_NAME = dict(MIRROR_BASES)

# GitHub Release 加速器（2026-09 实测可用；ghproxy.com 已停服，不要再引入）
GH_ACCELERATORS: List[str] = [
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
    "https://ghfast.top/",
]

# 故障转移参数（避免魔法数字）
DOWNLOAD_PROBE_TIMEOUT = 5     # 单 URL 探测超时（秒）
DOWNLOAD_TIMEOUT = 30         # 单 URL 下载连接超时（秒）
DOWNLOAD_RETRY_PER_URL = 2    # 单 URL 内重试次数
# 关窗时等抓取线程收尾的总预算（秒）。抓取线程最长按一个在途请求的超时返回
# （DOWNLOAD_PROBE_TIMEOUT * 2 = 10s），这里留 2s 余量。
FETCH_EXIT_WAIT = 12

# 实测（2026-09-28）：清华/北外对 requests 默认 UA 与浏览器 UA 一律回 403，
# 只对自定义 UA 放行；列目录（_get）已带，下载（_try_download）也必须带。
HTTP_UA = {"User-Agent": "byte-tools"}
# 实测（2026-09-28 GET + 本 UA）：华为云 anaconda 对任意不存在的路径都回
# 「301 → 200 + 一小段软 404 HTML、无 Content-Length」，会把错误页当下载成功；
# 本工具的归档包最小的也有几 MB，故按字节数判真假。
DOWNLOAD_MIN_VALID_BYTES = 4096


def _mb(*names: str) -> List[str]:
    """
    按标识批量取镜像基址（去掉结尾斜杠），供各 URL 构造器拼接。

    入参 names: str  MIRROR_BASES 里的标识，如 "tuna"、"huaweicloud"
    返回: List[str]  与 names 同序的基址列表
    """
    return [_MIRROR_BY_NAME[n] for n in names]


def _gh_accelerated(url: str) -> List[str]:
    """
    GitHub 裸地址 → 加速器在前、官方地址末位（GitHub 没有真镜像，只能走反向代理）。

    入参 url: str  形如 https://github.com/<owner>/<repo>/... 的原始地址
    返回: List[str]  len(GH_ACCELERATORS) + 1 个 URL；url 为空时返回 []
    """
    if not url:
        return []
    return [p + url for p in GH_ACCELERATORS] + [url]


# ---------------------------------------------------------------------------
# URL 构造器（模块级，便于抓取器与初始默认列表复用）
# ---------------------------------------------------------------------------
_STD_ARCHIVE: Dict[str, str] = {"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"}


def _cv(version: str, url_map: Dict, archive_map: Optional[Dict[str, str]] = None) -> ComponentVersion:
    """
    构造 ComponentVersion，按值类型自动选模式：值含列表 → R1 多源故障转移；值全是字符串 → 旧单源。

    入参 version: str          版本号
    入参 url_map: Dict[str, Union[str, List[str]]]  平台键 → 单 URL 或 URL 列表（镜像在前、官方末位）
    入参 archive_map: Optional[Dict[str, str]]  覆盖默认归档表；包名不是 zip/tar.gz
                 （如 MySQL、RabbitMQ 的 .tar.xz）时必须显式传，否则下载下来的文件
                 后缀与内容不符，extract_archive 会走错分支。
    """
    archives = dict(_STD_ARCHIVE)
    if archive_map:
        archives.update(archive_map)
    if any(isinstance(u, list) for u in url_map.values()):
        listed = {k: (v if isinstance(v, list) else [v]) for k, v in url_map.items() if v}
        return ComponentVersion(version=version, url_map={}, url_list_map=listed,
                                archive_map=archives)
    return ComponentVersion(version=version, url_map=url_map, archive_map=archives)


# --- Adoptium Temurin JDK ---------------------------------------------------
# 官方 latest-binary 地址按 major 重定向到"当前最新构建"，而镜像站目录里只有带
# build 号的确切文件名，所以必须先进目录挑文件，再拼成可直连的镜像地址。
# 布局（2026-09 实测可用）：<镜像基址>/<子路径>/<major>/jdk/<arch>/<os-dir>/
_ADOPTIUM_LAYOUTS: List[tuple] = [("tuna", "/Adoptium"), ("nju", "/adoptium")]


def _adoptium_dirs() -> Dict[str, tuple]:
    """OS 键 → (镜像目录 arch, 镜像目录 os, 归档后缀)，对应 Adoptium 目录命名。"""
    unix_arch = "aarch64" if IS_ARM else "x64"
    return {
        "Windows": ("x64", "windows", "zip"),
        "Darwin":  (unix_arch, "mac", "tar.gz"),
        "Linux":   (unix_arch, "linux", "tar.gz"),
    }


def _adoptium_pick(names: List[str], major: str, arch: str, os_dir: str, ext: str) -> Optional[str]:
    """
    从目录链接里挑出版本号最大的 JDK 归档文件名；没有匹配返回 None。

    入参 names: List[str]  目录页 href 抓出来的文件名
    返回: Optional[str]  形如 OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip

    两种命名都要认：现代版本 21.0.12.1_1，JDK 8 仍是 8u492b09。
    用数字序而不是字典序：21.0.9 按字典序会排到 21.0.10 后面。
    严格 fullmatch 版本段，顺带排掉同名前缀的 .sbom.tar.gz / manifest 等附属文件。
    """
    pat = _re.compile(rf"^OpenJDK{major}U-jdk_{arch}_{os_dir}_hotspot_(\S+)\.{ext}$")
    ver_pat = _re.compile(r"\d[\d.]*_\d+\Z|\d+u\d+b\d+\Z")
    best: Optional[str] = None
    best_key: tuple = ()
    for raw in names:
        name = raw.strip("/")
        m = pat.match(name)
        if not m or not ver_pat.match(m.group(1)):
            continue
        key = tuple(int(x) for x in _re.findall(r"\d+", m.group(1)))
        if key > best_key:
            best, best_key = name, key
    return best


def _adoptium_mirror_urls(major: str, dead: Optional[set] = None,
                          avail: Optional[dict] = None) -> Dict[str, List[str]]:
    """
    在镜像站上解析 major 的确切 JDK 文件地址（R1 多源列表的前半段）。

    入参 major: str           JDK 大版本，如 "21"
    入参 dead: Optional[set]  本次刷新内已判定连不上的镜像基址（熔断，避免逐个版本重复试探）
    入参 avail: Optional[dict] 基址 → 该镜像已同步的大版本集合，同一次刷新内复用
    返回: OS 键 → 镜像文件 URL 列表；镜像缺该版本或目录不可读时对应项缺失

    只解析当前系统的目录：下载地址最终由 urls_for_current() 取用，其它平台的条目在本机不会被读到。
    先列根目录问"这个镜像同步了哪些 major"，再进具体目录：新 major 常常还没同步，
    直接撞 404 会被 _get 重试三次，还可能把还能用的镜像误熔断。
    """
    arch, os_dir, ext = _adoptium_dirs()[CURRENT_OS]
    found: List[str] = []
    for base_name, sub in _ADOPTIUM_LAYOUTS:
        base = f"{_mb(base_name)[0]}{sub}"
        if dead is not None and base in dead:
            continue
        try:
            majors = avail.get(base) if avail is not None else None
            if majors is None:
                majors = set(_re.findall(r'href="(\d+)/"',
                                         _get(f"{base}/", timeout=DOWNLOAD_PROBE_TIMEOUT).text))
                if avail is not None:
                    avail[base] = majors
            if major not in majors:
                continue                       # 该镜像还没同步这个大版本，不是基址故障
            dir_url = f"{base}/{major}/jdk/{arch}/{os_dir}/"
            html = _get(dir_url, timeout=DOWNLOAD_PROBE_TIMEOUT).text
        except requests.exceptions.HTTPError:
            continue
        except Exception:
            if dead is not None:
                dead.add(base)
            continue
        picked = _adoptium_pick(_re.findall(r'href="([^"?]+)"', html), major, arch, os_dir, ext)
        if picked:
            found.append(f"{dir_url}{picked}")
    return {CURRENT_OS: found} if found else {}


def _adoptium_jdk_url(version: str, dead: Optional[set] = None,
                      avail: Optional[dict] = None,
                      resolve_mirrors: bool = True) -> Dict[str, List[str]]:
    """
    Adoptium Temurin JDK 下载地址（R1 多源）：镜像站的确切文件在前，官方 latest-binary 末位兜底。

    入参 version: str           JDK 大版本，如 "21"
    入参 dead / avail           透传给 _adoptium_mirror_urls，一次刷新内共享镜像熔断与同步情况缓存
    入参 resolve_mirrors: bool  False 时跳过镜像目录解析——离线默认清单不允许联网
    """
    api = "https://api.adoptium.net/v3/binary/latest"
    mirrors = _adoptium_mirror_urls(version, dead, avail) if resolve_mirrors else {}
    out: Dict[str, List[str]] = {}
    for os_key, (arch, os_dir, _ext) in _adoptium_dirs().items():
        official = f"{api}/{version}/ga/{os_dir}/{arch}/jdk/hotspot/normal/eclipse"
        out[os_key] = mirrors.get(os_key, []) + [official]
    return out


def _maven_urls(v: str) -> Dict[str, List[str]]:
    """
    Maven 下载 URL 列表（R1 多源）：Apache 布局镜像在前，archive.apache.org 末位。

    入参 v: str  版本号，如 "3.9.16"

    实测（2026-09-28 GET + byte-tools UA）：镜像站的 apache/* 只保留当前版本，3.9.16 七家全通，
    3.9.6 只剩华为云 + archive 两家；旧版本靠故障转移兜底，不裁源。
    """
    name = f"apache-maven-{v}-bin"
    rel = f"/apache/maven/maven-3/{v}/binaries/{name}"
    official = f"https://archive.apache.org/dist/maven/maven-3/{v}/binaries/{name}"
    mirrors = _mb("huaweicloud", "tuna", "aliyun", "nju", "bfsu", "tencent", "ustc")

    def lst(ext: str) -> List[str]:
        return [f"{b}{rel}.{ext}" for b in mirrors] + [f"{official}.{ext}"]

    return {"Windows": lst("zip"), "Darwin": lst("tar.gz"), "Linux": lst("tar.gz")}


def _tomcat_urls(v: str) -> Dict[str, List[str]]:
    """Tomcat 下载 URL 列表（R1 多源）：与 Maven 同为 Apache 布局，官网 archive 末位。"""
    major = v.split(".", 1)[0]
    name = f"apache-tomcat-{v}"
    rel = f"/apache/tomcat/tomcat-{major}/v{v}/bin/{name}"
    official = f"https://archive.apache.org/dist/tomcat/tomcat-{major}/v{v}/bin/{name}"
    # 实测（2026-09-28）：10.1.60 七家镜像全通；9.0.x 少腾讯云，8.5.x 只剩华为云 + archive
    mirrors = _mb("huaweicloud", "tuna", "aliyun", "nju", "bfsu", "tencent", "ustc")

    def lst(ext: str) -> List[str]:
        return [f"{b}{rel}.{ext}" for b in mirrors] + [f"{official}.{ext}"]

    return {"Windows": lst("zip"), "Darwin": lst("tar.gz"), "Linux": lst("tar.gz")}


def _mysql_urls(v: str) -> Dict[str, List[str]]:
    """
    MySQL 下载 URL 列表。

    实测（2026-09）两条硬事实：
      - dev.mysql.com 的 get 跳转入口对任何 UA 都回 403；官方直链只能用它的 CDN
        cdn.mysql.com/Downloads/（并且只保留近期版本，8.0.28 已经 404）。
      - 国内只有阿里云 /mysql/MySQL-<maj.min>/ 与华为云 /mysql/Downloads/MySQL-<maj.min>/
        同步了安装包，且都只到 8.0.28/8.0.29 这一段。

    实测（2026-09-28）Linux 命名：镜像站只有 glibc2.12 那一套（1.2 GB，200 可下），
    glibc2.28 在阿里/华为都是 404；官方 CDN 反之只挂 glibc2.28，所以末位官方单独用
    官方那套文件名。

    实测（2026-09-28）macOS 命名：官方 CDN 只给最新版且用 macos14 段
    （8.0.37-macos14-{x86_64,arm64} 200 / 173 MB、168 MB；8.0.28、8.0.29、8.0.33、
    8.0.34、8.0.35、8.0.36 的 macos14 全 404），镜像站则留着老版本的当年命名
    （阿里 8.0.27/8.0.28-macos11、华为 8.0.24~8.0.28-macos11 与 8.0.29-macos12，
    两种架构都有）。所以 Darwin 按 macos11→12→14 三个候选名 × 三个基址展开，
    靠故障转移选中真实存在的那个。
    """
    major_minor = v.rsplit(".", 1)[0]
    cdn_base = f"https://cdn.mysql.com/Downloads/MySQL-{major_minor}"
    mac_arch = "arm64" if IS_ARM else "x86_64"
    win_name = f"mysql-{v}-winx64.zip"
    linux_mirror_name = f"mysql-{v}-linux-glibc2.12-x86_64.tar.xz"
    linux_official_name = f"mysql-{v}-linux-glibc2.28-x86_64.tar.xz"
    aliyun, huawei = _mb("aliyun", "huaweicloud")

    # macOS 包：官方 CDN 只挂最新版（8.0.28/8.0.29 连 macos11、macos12 命名也 404），
    # 镜像站则留着老版本当年命名的包，所以镜像侧试 macos11/macos12，官方只试 macos14。
    mac_list: List[str] = []
    for base in (f"{aliyun}/mysql/MySQL-{major_minor}",
                 f"{huawei}/mysql/Downloads/MySQL-{major_minor}"):
        mac_list += [f"{base}/mysql-{v}-{tag}-{mac_arch}.tar.gz" for tag in ("macos11", "macos12")]
    mac_list.append(f"{cdn_base}/mysql-{v}-macos14-{mac_arch}.tar.gz")

    return {
        "Windows": [f"{aliyun}/mysql/MySQL-{major_minor}/{win_name}",
                    f"{huawei}/mysql/Downloads/MySQL-{major_minor}/{win_name}",
                    f"{cdn_base}/{win_name}"],
        "Darwin":  mac_list,
        "Linux":   [f"{aliyun}/mysql/MySQL-{major_minor}/{linux_mirror_name}",
                    f"{huawei}/mysql/Downloads/MySQL-{major_minor}/{linux_mirror_name}",
                    f"{cdn_base}/{linux_official_name}"],
    }


def _python_urls(v: str) -> Dict[str, List[str]]:
    """
    Python 下载 URL 列表：Windows 用 embed zip，其它平台用源码 tgz（与官方 ftp 同名）。

    华为云的 Python 发行包在 mirrors 子域（不是 repo 子域），故用 huaweicloud-py 基址。
    """
    win_name = f"python-{v}-embed-amd64.zip"
    src_name = f"Python-{v}.tgz"
    hwpy = _mb("huaweicloud-py")[0]
    npmm = _mb("npmmirror")[0]
    official = "https://www.python.org/ftp/python"
    return {
        "Windows": [f"{hwpy}/python/{v}/{win_name}",
                    f"{npmm}/-/binary/python/{v}/{win_name}",
                    f"{official}/{v}/{win_name}"],
        "Darwin":  [f"{npmm}/-/binary/python/{v}/{src_name}",
                    f"{hwpy}/python/{v}/{src_name}",
                    f"{official}/{v}/{src_name}"],
        "Linux":   [f"{npmm}/-/binary/python/{v}/{src_name}",
                    f"{hwpy}/python/{v}/{src_name}",
                    f"{official}/{v}/{src_name}"],
    }


def _node_urls(v: str) -> Dict[str, List[str]]:
    """Node.js 下载 URL 列表：nodejs-release 布局镜像在前，nodejs.org 末位。"""
    mac_arch = "arm64" if IS_ARM else "x64"

    def lst(name: str) -> List[str]:
        mirrors = [f"{b}/nodejs-release/v{v}/{name}" for b in _mb("tuna", "nju", "bfsu")]
        mirrors += [f"{_mb('huaweicloud')[0]}/nodejs/v{v}/{name}",
                    f"{_mb('npmmirror')[0]}/-/binary/node/v{v}/{name}"]
        return mirrors + [f"https://nodejs.org/dist/v{v}/{name}"]

    return {
        "Windows": lst(f"node-v{v}-win-x64.zip"),
        "Darwin":  lst(f"node-v{v}-darwin-{mac_arch}.tar.gz"),
        "Linux":   lst(f"node-v{v}-linux-x64.tar.gz"),
    }


def _git_urls(v: str) -> Dict[str, List[str]]:
    """
    Git 下载：Windows 用 MinGit（便携版，解压即用）。

    实测（2026-09-28）Windows 有真镜像：华为云 repo/mirrors 两个子域都同步了
    git-for-windows，npmmirror 的 registry 布局也有同名目录；所以镜像在前、
    GitHub 加速器居中、裸地址末位。

    macOS/Linux **不给任何 URL**：GitHub 上只有 git/git 的源码 tar.gz，解压后
    没有可执行的 git（要自己 configure + make），列出来只会让用户下一个用不了
    的东西。这两个平台改由 Component.unsupported_platform_hint 引导用系统包管理器。
    """
    hwm, hw = _mb("huaweicloud-py", "huaweicloud")
    npmm = _mb("npmmirror")[0]
    win_tag = f"v{v}.windows.1"
    win_name = f"MinGit-{v}-64-bit.zip"
    win = (f"https://github.com/git-for-windows/git/releases/download/"
           f"{win_tag}/{win_name}")
    win_list = [f"{hwm}/git-for-windows/{win_tag}/{win_name}",
                f"{hw}/git-for-windows/{win_tag}/{win_name}",
                f"{npmm}/-/binary/git-for-windows/{win_tag}/{win_name}"]
    win_list += _gh_accelerated(win)
    return {"Windows": win_list}


def _nginx_urls(v: str) -> Dict[str, List[str]]:
    """
    Nginx 下载 URL 列表（R1 多源故障转移模式）。

    入参 v: str   Nginx 版本号字符串，如 "1.28.0"
    返回: 只有 Windows 一个键的 URL 列表字典

    说明（2026-09-28 实测）：
      - Nginx 官方只对 Windows 发可直接运行的 zip（解压后根目录就是 nginx.exe），
        Linux/macOS 的 .tar.gz 全是源码包，需要自己 ./configure && make，
        解压后没有可执行文件，所以**不给这两个平台任何 URL**，
        改由 Component.unsupported_platform_hint 引导用系统包管理器；
      - 大陆镜像只有华为云两个子域真的同步了 zip 文件，
        清华 / 北外 / 南大 / 阿里 / 腾讯 / 中科大 一律 404（它们的 nginx/ 目录
        是给 apt/yum 用的包仓库，没有 nginx.org/download 那套 zip）；
      - 华为云两个子域同源不同域名，故障转移仍值得都列上，末位是 nginx.org 官网。
    """
    hwm, hw = _mb("huaweicloud-py", "huaweicloud")
    name = f"nginx-{v}.zip"
    return {
        "Windows": [f"{hwm}/nginx/{name}", f"{hw}/nginx/{name}",
                    f"https://nginx.org/download/{name}"],
    }


def _nginx_cv(v: str) -> ComponentVersion:
    """
    构造 Nginx 的 ComponentVersion（Windows 走 R1 多源，其余平台无源）。

    入参 v: str   Nginx 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_nginx_urls(v),
        archive_map={"Windows": "zip"},   # 只有 Windows 有包，其余平台不填
    )


def fetch_nginx_versions() -> List[ComponentVersion]:
    """
    抓取 Nginx 版本列表：先读华为云镜像目录，读不到再回退官网目录。

    返回: ComponentVersion 列表，按版本号倒序，最多 12 个。

    异常: 镜像与官网目录页都拿不到时抛 RuntimeError。

    说明: 两处目录页都以 nginx-<版本>.zip 形式列出 Windows 包，版本号正则一致；
          只取三段式版本（1.28.0 这种），跳过 1.27 之类的两段历史目录名。
    """
    rx = _re.compile(r'nginx-(\d+\.\d+\.\d+)\.zip')
    hwm, hw = _mb("huaweicloud-py", "huaweicloud")
    indexes = [
        f"{hwm}/nginx/",
        f"{hw}/nginx/",
        "https://nginx.org/download/",
    ]
    versions: List[str] = []
    for idx in indexes:
        try:
            found = set(rx.findall(_get(idx, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text))
        except Exception:
            continue
        if found:
            versions = found
            break
    if not versions:
        raise RuntimeError("Nginx 版本列表抓取失败：华为云镜像与 nginx.org 均不可用")
    return [_nginx_cv(v) for v in _sort_semver_desc(versions)[:12]]


def _pwsh_urls(v: str) -> Dict[str, List[str]]:
    """
    PowerShell 7 下载 URL 列表（R1 多源故障转移模式）。

    入参 v: str   PowerShell 版本号字符串，如 "7.5.4"
    返回: 三平台 → URL 列表字典，加速器在前、GitHub 官方末位

    说明（2026-09-28 实测）：
      - PowerShell 只在 GitHub Releases 发版，国内没有真镜像
        （清华 / 南大 / npmmirror 的 powershell 目录一律 404），
        与 RabbitMQ 一样只能走 _gh_accelerated 的反向代理；
      - 三平台都有可直接运行的便携包：Windows 是 zip，Linux/macOS 是 tar.gz；
      - 资产命名有大小写差异：Windows 用 PowerShell-<v>-win-<arch>.zip（大写 P），
        Linux/macOS 用 powershell-<v>-linux/osx-<arch>.tar.gz（小写 p）；
      - win/linux/osx 的 x64 与 arm64 六种资产都验证过 200 + 真包魔数。
    """
    unix_arch = "arm64" if IS_ARM else "x64"
    win_arch = "arm64" if IS_ARM else "x64"
    base = "https://github.com/PowerShell/PowerShell/releases/download"

    def lst(name: str) -> List[str]:
        return _gh_accelerated(f"{base}/v{v}/{name}")

    return {
        "Windows": lst(f"PowerShell-{v}-win-{win_arch}.zip"),
        "Darwin":  lst(f"powershell-{v}-osx-{unix_arch}.tar.gz"),
        "Linux":   lst(f"powershell-{v}-linux-{unix_arch}.tar.gz"),
    }


def _pwsh_cv(v: str) -> ComponentVersion:
    """
    构造 PowerShell 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   PowerShell 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_pwsh_urls(v),
        # Windows 是 zip，Linux/macOS 是 tar.gz（与默认 _STD_ARCHIVE 一致）
        archive_map=dict(_STD_ARCHIVE),
    )


def fetch_powershell_versions() -> List[ComponentVersion]:
    """
    抓取 PowerShell 7 版本列表：从 GitHub Releases API 取 tag。

    返回: ComponentVersion 列表，按版本号倒序，最多 12 个。

    异常: GitHub API 不可用时抛 RuntimeError。

    说明: 只要三段式的正式 tag（v7.5.4），带 -preview / -rc / daily-build 的跳过；
          6.x 已停止支持，因此要求主版本号 ≥7。
    """
    github_api = "https://api.github.com/repos/PowerShell/PowerShell/releases?per_page=60"
    try:
        data = _github_api_json(github_api)
    except Exception as exc:
        raise RuntimeError(
            f"PowerShell 版本列表抓取失败：GitHub API 不可用：{exc}"
        ) from exc

    versions: List[str] = []
    for rel in data:
        tag = rel.get("tag_name", "")
        if not tag.startswith("v"):
            continue
        v = tag[1:]
        if _re.match(r"^[7-9]\.\d+\.\d+$", v):
            versions.append(v)
    stable = _sort_semver_desc(versions)
    if not stable:
        raise RuntimeError("PowerShell 版本列表为空（GitHub API 未返回 7.x 正式版）")
    return [_pwsh_cv(v) for v in stable[:12]]


def _conda_urls(v: str) -> Dict[str, List[str]]:
    """
    Miniconda 安装器（与官方同名文件）：镜像在前，repo.anaconda.com 末位。

      - Windows: .exe
      - macOS:   .sh (根据架构挑 arm64 / x86_64)
      - Linux:   .sh
    版本号如 "py312_24.7.1-0"。
    """
    mac_arch = "arm64" if IS_ARM else "x86_64"

    def lst(name: str) -> List[str]:
        mirrors = [f"{b}/anaconda/miniconda/{name}"
                   for b in _mb("tuna", "nju", "bfsu", "ustc")]
        return mirrors + [f"https://repo.anaconda.com/miniconda/{name}"]

    return {
        "Windows": lst(f"Miniconda3-{v}-Windows-x86_64.exe"),
        "Darwin":  lst(f"Miniconda3-{v}-MacOSX-{mac_arch}.sh"),
        "Linux":   lst(f"Miniconda3-{v}-Linux-x86_64.sh"),
    }


def _go_urls(v: str) -> Dict[str, List[str]]:
    """
    Go 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Go 版本号字符串，如 "1.22.5"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（阿里云→南京大学），官网末位。

    实测（2026-09-28 GET + byte-tools UA）纠正：Go 的二进制树只有少数镜像同步。
    阿里云 /golang/ 与南大 /golang/ 是 200 且有完整 Content-Length；华为云 repo 与
    mirrors 两个子域一律 401，清华没有 golang 目录（404），腾讯云同样 404，
    中科大只是 302 跳回 dl.google.com（本机对 dl.google.com TLS 握手失败，
    等于没有镜像）。所以这里只保留真正可用的两家。
    """
    # 国内镜像基址（按 R1.3 优先级），官网末位
    mirror_bases = [f"{b}/golang" for b in _mb("aliyun", "nju")]
    official = "https://go.dev/dl"

    # 按 CPU 架构挑选文件名（Go 官方命名约定）
    mac_arch = "arm64" if IS_ARM else "amd64"
    linux_arch = "arm64" if IS_ARM else "amd64"

    def build_list(filename: str) -> List[str]:
        """构造镜像在前 + 官网末位的 URL 列表。"""
        return [f"{base}/{filename}" for base in mirror_bases] + [f"{official}/{filename}"]

    return {
        "Windows": build_list(f"go{v}.windows-amd64.zip"),
        "Darwin":  build_list(f"go{v}.darwin-{mac_arch}.tar.gz"),
        "Linux":   build_list(f"go{v}.linux-{linux_arch}.tar.gz"),
    }


def _go_cv(v: str) -> ComponentVersion:
    """
    构造 Go 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Go 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},  # 不使用单 URL 模式
        url_list_map=_go_urls(v),  # 走 R1 多源故障转移
        archive_map={"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"},
    )


def _gradle_urls(v: str) -> Dict[str, List[str]]:
    """
    Gradle 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Gradle 版本号字符串，如 "8.10"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（华为云 repo→华为云 mirrors→南京大学→腾讯云），官网末位。
    说明: Gradle 官方对三平台都发布同一 zip 包（gradle-<v>-bin.zip），
          解压后根目录为 gradle-<v>/，内部含 bin/gradle / bin/gradle.bat。

    实测（2026-09-28 GET + byte-tools UA）：清华没有 gradle 目录（404），阿里云 404，
    中科大同样 404；能真正下到 137 MB 的是华为云两个子域、南大与腾讯云。
    """
    # 国内镜像基址（按实测可用性排序），末位为官网
    mirror_bases = [f"{b}/gradle" for b in
                    _mb("huaweicloud", "huaweicloud-py", "nju", "tencent")]
    official = "https://services.gradle.org/distributions"
    # Gradle 对三平台发布同一个 -bin.zip 包
    filename = f"gradle-{v}-bin.zip"
    urls = [f"{base}/{filename}" for base in mirror_bases] + [f"{official}/{filename}"]
    # 三平台 URL 完全一致
    return {"Windows": list(urls), "Darwin": list(urls), "Linux": list(urls)}


def _gradle_cv(v: str) -> ComponentVersion:
    """
    构造 Gradle 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Gradle 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},  # 不使用单 URL 模式
        url_list_map=_gradle_urls(v),  # 走 R1 多源故障转移
        archive_map={"Windows": "zip", "Darwin": "zip", "Linux": "zip"},
    )


def _bun_urls(v: str) -> Dict[str, List[str]]:
    """
    Bun 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Bun 版本号字符串，如 "1.1.0"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（npmmirror→GitHub 加速器），末位为 GitHub releases 官网。

    说明:
      - Bun 官方发布在 GitHub Releases（oven-sh/bun 仓库），tag 名为 bun-v<version>；
      - 资源命名约定：bun-<platform>-<arch>.zip，平台标识为 windows / darwin / linux，
        架构标识为 x64 / arm64；
      - 国内最稳的镜像是淘宝 npmmirror（R1.3 表外特殊源），
        GitHub 直链没有真镜像，只能再走 _gh_accelerated 的反向代理。
    """
    # 国内镜像基址（Bun 在国内仅此两源稳定）
    npmmirror_base = "https://registry.npmmirror.com/-/binary/bun"
    official_base = "https://github.com/oven-sh/bun/releases/download"

    # 按 CPU 架构挑选文件名（Bun 官方命名约定）
    mac_arch = "arm64" if IS_ARM else "x64"
    linux_arch = "arm64" if IS_ARM else "x64"

    # tag 名带 bun-v 前缀；npmmirror 目录名亦为 bun-v<version>
    tag = f"bun-v{v}"

    def build_list(platform: str, arch: str) -> List[str]:
        """构造镜像在前 + 官网末位的 URL 列表。"""
        filename = f"bun-{platform}-{arch}.zip"
        return [f"{npmmirror_base}/{tag}/{filename}"] + \
               _gh_accelerated(f"{official_base}/{tag}/{filename}")

    return {
        "Windows": build_list("windows", "x64"),  # Bun 暂无 Windows arm64 包
        "Darwin":  build_list("darwin",  mac_arch),
        "Linux":   build_list("linux",   linux_arch),
    }


def _bun_cv(v: str) -> ComponentVersion:
    """
    构造 Bun 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Bun 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_bun_urls(v),  # 走 R1 多源故障转移
        archive_map={"Windows": "zip", "Darwin": "zip", "Linux": "zip"},
    )


def _docker_urls(v: str) -> Dict[str, List[str]]:
    """
    Docker 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Docker 版本号字符串，如 "27.3.1"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（华为云两个子域 + 清华 + 阿里 + 南大 + 北外 + 中科大 + 腾讯云
          共 8 家，实测全部同步了 docker-ce 静态包），官网末位。

    说明:
      - Docker 官方在 download.docker.com 提供 static binaries（单 tgz 包），
        Linux / Mac 平台均有，跨架构 x86_64 / aarch64；
      - Windows 平台不发布 static binary（必须用 Docker Desktop GUI 安装器），
        本函数不返回 Windows 键，urls_for_current() 在 Windows 上返回空列表，
        ComponentCard 会显示"当前系统 Windows 无可用下载地址"。
      - tgz 解压后根目录为 docker/，内部含 docker / dockerd 等二进制（无 bin 子目录）。
    """
    # 国内镜像基址（按实测可用性排序，2026-09-28 八家全部 200 + 75 MB Content-Length）
    # docker-ce 路径：linux/static/stable/<arch>/docker-<v>.tgz 或 mac/static/stable/<arch>/docker-<v>.tgz
    cn_bases = _mb("huaweicloud", "huaweicloud-py", "tuna", "aliyun", "nju",
                   "bfsu", "ustc", "tencent")
    mirror_bases_linux = [f"{b}/docker-ce/linux/static/stable" for b in cn_bases]
    mirror_bases_mac = [f"{b}/docker-ce/mac/static/stable" for b in cn_bases]
    official_linux = "https://download.docker.com/linux/static/stable"
    official_mac = "https://download.docker.com/mac/static/stable"

    # 按 CPU 架构挑选路径段（Docker 官方命名约定：x86_64 / aarch64）
    arch = "aarch64" if IS_ARM else "x86_64"

    # Linux URL 列表：3 个国内镜像 + 1 个官网末位
    linux_filename = f"docker-{v}.tgz"
    linux_urls = [f"{base}/{arch}/{linux_filename}" for base in mirror_bases_linux]
    linux_urls.append(f"{official_linux}/{arch}/{linux_filename}")

    # Mac URL 列表：3 个国内镜像 + 1 个官网末位
    mac_urls = [f"{base}/{arch}/{linux_filename}" for base in mirror_bases_mac]
    mac_urls.append(f"{official_mac}/{arch}/{linux_filename}")

    # Windows 不返回（Docker 必须 Docker Desktop）
    return {
        "Linux":  linux_urls,
        "Darwin": mac_urls,
    }


def _docker_cv(v: str) -> ComponentVersion:
    """
    构造 Docker 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Docker 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_docker_urls(v),  # 走 R1 多源故障转移
        archive_map={"Linux": "tar.gz", "Darwin": "tar.gz"},  # Windows 不支持
    )


def _mongodb_urls(v: str) -> Dict[str, List[str]]:
    """
    MongoDB 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   MongoDB 版本号字符串，如 "8.0.12"
    返回: 按操作系统键映射的 URL 列表字典。

    说明:
      - MongoDB 官方在 fastdl.mongodb.org 提供 community 二进制包，
        Windows 是 zip，Linux 是 tgz；
      - Mac 平台 MongoDB 官方不发布 community binary（用户应使用 brew），
        本函数不返回 Darwin 键；
      - 解压后根目录为 mongodb-<platform>-<arch>-<version>/，内部含 bin/ 子目录。

    实测（2026-09-28 GET + byte-tools UA）两条纠正，所以本组件按 R1.1 登记为
    「无大陆镜像」例外：
      - 华为云 /mongodb/ 只有 C++ 源码包，清华/阿里/中科大没有 fastdl 的二进制树
        （目录与文件一律 404），四家全部不可用；
      - Linux 包名必须带发行版段（ubuntu2204 等），裸 mongodb-linux-x86_64-<v>.tgz
        是 403，这正是改造前恒失败的原因。
    """
    official_base = "https://fastdl.mongodb.org"

    # Windows：只有 x64，无 arm64 社区版
    win_filename = f"mongodb-windows-x86_64-{v}.zip"

    # Linux：官方按 glibc/发行版分档，ubuntu2204 是当前 8.0.x 都能命中的那一档
    arch_linux = "aarch64" if IS_ARM else "x86_64"
    distro = "" if IS_ARM else "-ubuntu2204"
    linux_filename = f"mongodb-linux-{arch_linux}{distro}-{v}.tgz"

    return {
        "Windows": [f"{official_base}/windows/{win_filename}"],
        "Linux":   [f"{official_base}/linux/{linux_filename}"],
        # Mac 不支持（用户用 brew install mongodb-community）
    }


def _mongodb_cv(v: str) -> ComponentVersion:
    """
    构造 MongoDB 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   MongoDB 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_mongodb_urls(v),  # 走 R1 多源故障转移
        archive_map={"Windows": "zip", "Linux": "tar.gz"},
    )


def _postgresql_urls(v: str) -> Dict[str, List[str]]:
    """
    PostgreSQL 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   PostgreSQL 版本号字符串，如 "16.4"
    返回: 按操作系统键映射的 URL 列表字典（Windows 只有官方一源，见下方说明）。

    说明:
      - PostgreSQL 官方 binaries 由 EnterpriseDB（EDB）发布在 get.enterprisedb.com；
      - 解压后根目录为 pgsql/，内部含 bin/ 子目录。

    实测（2026-09-28 GET + byte-tools UA）三条纠正，所以本组件按 R1.1 登记为
    「无大陆镜像」例外：
      - 清华没有 /postgresql/ 目录（404）；华为云/阿里/南大的 /postgresql/ 只有
        `latest/`、`source/` 源码 tarball，`v17/`、`17.6/` 这类 binaries 树一律 404，
        国内无人同步 EDB 的 windows-x64-binaries.zip。
      - 早前记的「华为云 /postgresql/binaries/ 回 200 + 空响应体」是不带 UA 时的误判：
        带 UA 后同一目录回 401/404。
      - EDB 根本不发布 Linux 版 binaries（postgresql-<v>-1-linux-x64-binaries.tar.gz
        恒 403），改造前那条 Linux 源是必然失败的，现在直接不给出该平台的键。
    """
    official_base = "https://get.enterprisedb.com/postgresql"

    # Windows：x64
    win_filename = f"postgresql-{v}-1-windows-x64-binaries.zip"

    return {
        "Windows": [f"{official_base}/{win_filename}"],
        # Linux：EDB 无 binaries 发布，改用发行版包管理器（apt/yum/dnf）
        # Mac 不支持（用户用 brew install postgresql）
    }


def _postgresql_cv(v: str) -> ComponentVersion:
    """
    构造 PostgreSQL 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   PostgreSQL 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_postgresql_urls(v),  # 走 R1 多源故障转移
        archive_map={"Windows": "zip"},
    )


def _kubectl_urls(v: str) -> Dict[str, List[str]]:
    """
    kubectl 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   kubectl 版本号字符串，如 "1.31.0"
    返回: 按操作系统键映射的 URL 列表字典（当前只有官方一个源，见下方说明）

    说明:
      - kubectl 是 Kubernetes 官方 CLI 单二进制，三平台都发布；
      - 官方下载 URL 形如 https://dl.k8s.io/release/v<v>/bin/<os>/<arch>/kubectl<.exe>；
      - Windows 是 .exe，Linux/Mac 无扩展名（需 chmod +x）；
      - 实测（2026-09）国内传统镜像站的 kubernetes/ 目录只 rsync 了 apt、yum 包仓库
        （…/release/v…/bin/… 一律 404），GitHub Release 也不发这个二进制，所以通用
        镜像站和 GitHub 加速器都用不上；
      - 能用的是 DaoCloud 的 files.m.daocloud.io 反向代理（实测 windows/linux 都
        200 + 完整 Content-Length），按 <代理前缀>/<原域名>/<原路径> 拼接；
      - dl.k8s.io 本机也能直连，作为末位官方源。
    """
    # 按 CPU 架构挑选路径段
    arch = "arm64" if IS_ARM else "amd64"
    rel = f"dl.k8s.io/release/v{v}/bin"
    dao = _mb("daocloud-files")[0]
    official = "https://dl.k8s.io"

    def lst(os_dir: str, name: str) -> List[str]:
        return [f"{dao}/{rel}/{os_dir}/{arch}/{name}",
                f"{official}/release/v{v}/bin/{os_dir}/{arch}/{name}"]

    return {
        "Windows": lst("windows", "kubectl.exe"),
        "Linux":   lst("linux", "kubectl"),
        "Darwin":  lst("darwin", "kubectl"),
    }


def _kubectl_cv(v: str) -> ComponentVersion:
    """
    构造 kubectl 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   kubectl 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_kubectl_urls(v),  # 走 R1 多源故障转移
        # Windows 走 .exe 单二进制，Linux/Mac 走无扩展名单二进制
        archive_map={"Windows": "exe", "Linux": "", "Darwin": ""},
    )


def _jenkins_urls(v: str) -> Dict[str, List[str]]:
    """
    Jenkins 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Jenkins LTS 版本号字符串，如 "2.568.3"
    返回: 三平台同 URL 列表（jenkins.war 跨平台），列表顺序即故障转移顺序：
          国内镜像在前（华为云两个子域 + 清华 + 北外 + 南大 + 阿里 + 腾讯云），官网末位。

    说明:
      - Jenkins LTS war 包是跨平台单文件，下载后用 `java -jar jenkins.war` 启动；
      - 官方下载 URL 形如 https://get.jenkins.io/war-stable/<v>/jenkins.war；
      - 国内镜像路径结构与官网一致，但 war-stable 只保留最近几条 LTS 线
        （实测 2.568.3 八家全通，2.426.3 只剩华为云）。
    """
    filename = "jenkins.war"
    mirror_bases = [f"{b}/jenkins/war-stable/{v}" for b in
                    _mb("huaweicloud", "huaweicloud-py", "tuna", "bfsu", "nju",
                        "aliyun", "tencent", "ustc")]
    official_base = f"https://get.jenkins.io/war-stable/{v}"

    urls = [f"{base}/{filename}" for base in mirror_bases]
    urls.append(f"{official_base}/{filename}")

    # Jenkins war 包三平台通用
    return {
        "Windows": urls,
        "Linux":   urls,
        "Darwin":  urls,
    }


def _jenkins_cv(v: str) -> ComponentVersion:
    """
    构造 Jenkins 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Jenkins LTS 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_jenkins_urls(v),  # 走 R1 多源故障转移
        # Jenkins war 文件，三平台都是 .war 单文件
        archive_map={"Windows": "war", "Linux": "war", "Darwin": "war"},
    )


def _rabbitmq_urls(v: str) -> Dict[str, List[str]]:
    """
    RabbitMQ 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   RabbitMQ 版本号字符串，如 "4.0.0"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（华为云→清华→阿里云），官网末位 GitHub releases。

    说明:
      - RabbitMQ 官方在 github.com/rabbitmq/rabbitmq-server/releases 提供 generic binary；
      - Linux/Mac 走 generic_<unix>_xxx tar.xz 解压即用；
      - Windows 需 Erlang 依赖，不提供自动下载，由 unsupported_platform_hint 引导。
    """
    # 按 CPU 架构挑选路径段（RabbitMQ 用 aarch64 / x86_64）
    arch = "aarch64" if IS_ARM else "x86_64"
    # 实测（2026-09-28）：华为云的目录是 /rabbitmq-server/v<ver>/，不是 /rabbitmq/；
    # 清华与阿里根本没有 rabbitmq 的二进制镜像（404），所以大陆只有华为云两个子域。
    mirror_bases = [f"{b}/rabbitmq-server/v{v}" for b in
                    _mb("huaweicloud", "huaweicloud-py")]
    # GitHub releases 是末位官网，中间夹一层加速器（GitHub 没有真镜像）
    github = (f"https://github.com/rabbitmq/rabbitmq-server/releases/download/"
              f"v{v}/rabbitmq-server-generic-unix-{v}.tar.xz")

    # generic-unix 包三平台（除 Windows）通用：rabbitmq-server-generic-unix-<v>.tar.xz
    urls = [f"{base}/rabbitmq-server-generic-unix-{v}.tar.xz" for base in mirror_bases]
    urls += _gh_accelerated(github)

    return {
        "Linux":   urls,
        "Darwin":  urls,
        # Windows 不支持自动下载（依赖 Erlang）
    }


def _rabbitmq_cv(v: str) -> ComponentVersion:
    """
    构造 RabbitMQ 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   RabbitMQ 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_rabbitmq_urls(v),  # 走 R1 多源故障转移
        # 包名是 .tar.xz，extract_archive 按后缀分派，这里必须写 tar.xz 而不是 tar.gz
        archive_map={"Linux": "tar.xz", "Darwin": "tar.xz"},
    )


def _kafka_urls(v: str) -> Dict[str, List[str]]:
    """
    Apache Kafka 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Kafka 版本号字符串，如 "4.1.2"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序。

    说明:
      - Kafka 是 Scala 项目，跨平台单 tgz，需 JDK 运行；
      - 官方下载 URL 形如 https://archive.apache.org/dist/kafka/<v>/kafka_2.13-<v>.tgz；
      - Scala 版本固定 2.13（Kafka 3.x 起唯一支持版本）。

    实测（2026-09-28 GET + byte-tools UA）两处纠正：
      - Kafka 从来不发 .zip，原来的 Windows 分支拼 `kafka_2.13-<v>.zip` 六个源全部
        404，改成与其它平台同一个 .tgz；
      - 镜像站的 apache/kafka 只保留最新版（4.1.2 七家全通，3.9.1 只剩华为云 + archive）。
        之前记录的「中科大在 apache/* 回 200 + 空响应体」是不带 UA 时的误判：带上
        byte-tools UA 后 ustc 的 kafka 4.1.2 回 200 + gzip 魔数，不存在的版本回 404。
    """
    scala_version = "2.13"
    filename = f"kafka_{scala_version}-{v}.tgz"

    mirror_bases = [f"{b}/apache/kafka" for b in
                    _mb("huaweicloud", "tuna", "aliyun", "nju", "bfsu", "tencent", "ustc")]
    official_base = "https://archive.apache.org/dist/kafka"

    urls = [f"{base}/{v}/{filename}" for base in mirror_bases]
    urls.append(f"{official_base}/{v}/{filename}")

    return {
        "Windows": list(urls),
        "Linux":   list(urls),
        "Darwin":  list(urls),  # 三平台同一个 tgz
    }


def _kafka_cv(v: str) -> ComponentVersion:
    """
    构造 Apache Kafka 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Kafka 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_kafka_urls(v),
        # Kafka 三平台同一个 tgz，Windows 也是 tar.gz（原来写 zip 是恒 404 的根因）
        archive_map={"Windows": "tar.gz", "Linux": "tar.gz", "Darwin": "tar.gz"},
    )


def _rocketmq_urls(v: str) -> Dict[str, List[str]]:
    """
    Apache RocketMQ 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   RocketMQ 版本号字符串，如 "5.3.1"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序。

    说明:
      - RocketMQ 是 Java 项目，跨平台 zip，需 JDK 运行；
      - 官方下载 URL 形如 https://archive.apache.org/dist/rocketmq/<v>/rocketmq-all-<v>-bin-release.zip。
    """
    filename = f"rocketmq-all-{v}-bin-release.zip"

    # 实测（2026-09-28 GET + byte-tools UA）：apache/rocketmq 七家镜像 + archive 全部
    # 200（90 MB 真包，ustc 回 gzip 魔数）；不带 UA 时 ustc 会 403，曾被误判为假镜像。
    mirror_bases = [f"{b}/apache/rocketmq" for b in
                    _mb("huaweicloud", "tuna", "aliyun", "nju", "bfsu", "tencent", "ustc")]
    official_base = "https://archive.apache.org/dist/rocketmq"

    urls = [f"{base}/{v}/{filename}" for base in mirror_bases]
    urls.append(f"{official_base}/{v}/{filename}")

    # RocketMQ zip 跨平台通用
    return {
        "Windows": urls,
        "Linux":   urls,
        "Darwin":  urls,
    }


def _rocketmq_cv(v: str) -> ComponentVersion:
    """
    构造 Apache RocketMQ 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   RocketMQ 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_rocketmq_urls(v),
        archive_map={"Windows": "zip", "Linux": "zip", "Darwin": "zip"},
    )


def _pulsar_urls(v: str) -> Dict[str, List[str]]:
    """
    Apache Pulsar 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Pulsar 版本号字符串，如 "3.3.1"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序。

    说明:
      - Pulsar 是 Java 项目，跨平台 tar.gz，需 JDK 运行；
      - 官方下载 URL 形如 https://archive.apache.org/dist/pulsar/pulsar-<v>/apache-pulsar-<v>-bin.tar.gz。
    """
    filename = f"apache-pulsar-{v}-bin.tar.gz"

    mirror_bases = [f"{b}/apache/pulsar" for b in
                    _mb("huaweicloud", "tuna", "aliyun", "nju", "bfsu", "tencent", "ustc")]
    official_base = "https://archive.apache.org/dist/pulsar"

    urls = [f"{base}/pulsar-{v}/{filename}" for base in mirror_bases]
    urls.append(f"{official_base}/pulsar-{v}/{filename}")

    return {
        "Windows": urls,
        "Linux":   urls,
        "Darwin":  urls,
    }


def _pulsar_cv(v: str) -> ComponentVersion:
    """
    构造 Apache Pulsar 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Pulsar 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_pulsar_urls(v),
        archive_map={"Windows": "tar.gz", "Linux": "tar.gz", "Darwin": "tar.gz"},
    )


def _activemq_urls(v: str) -> Dict[str, List[str]]:
    """
    ActiveMQ 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   ActiveMQ 版本号字符串，如 "6.3.2"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序。

    说明:
      - ActiveMQ 是 Java 项目，跨平台 tar.gz/zip，需 JDK 运行。

    实测（2026-09-28）纠正：包名从 5.x 到 6.x 都是 apache-activemq-<v>-bin.*，
    原代码给 6.x 拼出的 activemq-apache-<v>-bin.* 六个源全部 404。
    另外镜像站的 apache/activemq 只保留最新版：6.3.2 七家全通，5.18.4 只剩华为云 + archive。
    """
    linux_filename = f"apache-activemq-{v}-bin.tar.gz"
    win_filename = f"apache-activemq-{v}-bin.zip"

    mirror_bases = [f"{b}/apache/activemq" for b in
                    _mb("huaweicloud", "tuna", "aliyun", "nju", "bfsu", "tencent", "ustc")]
    official_base = "https://archive.apache.org/dist/activemq"

    linux_urls = [f"{base}/{v}/{linux_filename}" for base in mirror_bases]
    linux_urls.append(f"{official_base}/{v}/{linux_filename}")
    win_urls = [f"{base}/{v}/{win_filename}" for base in mirror_bases]
    win_urls.append(f"{official_base}/{v}/{win_filename}")

    return {
        "Windows": win_urls,
        "Linux":   linux_urls,
        "Darwin":  linux_urls,
    }


def _activemq_cv(v: str) -> ComponentVersion:
    """
    构造 ActiveMQ 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   ActiveMQ 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_activemq_urls(v),
        archive_map={"Windows": "zip", "Linux": "tar.gz", "Darwin": "tar.gz"},
    )


def _nacos_urls(v: str) -> Dict[str, List[str]]:
    """
    Nacos 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Nacos 版本号字符串，如 "2.3.2"
    返回: 三平台同 URL 列表（Nacos 跨平台通用 zip/tar.gz），列表顺序即故障转移顺序：
          国内 GitHub 加速器在前（GH_ACCELERATORS），GitHub releases 末位。

    说明:
      - Nacos 在 GitHub releases 发布，国内无官方镜像；
      - 文件名形如 nacos-server-<v>.zip（三平台通用，部分版本也发 .tar.gz）；
      - GitHub Release 没有真镜像，统一走 _gh_accelerated 加前缀（ghproxy.com 已停服，勿再引入）。
    """
    # Nacos 2.x 起 zip 是主发布格式（Linux 也能用 zip 解压即用）
    filename = f"nacos-server-{v}.zip"

    # GitHub releases 末位官网，前面是加速器前缀
    urls = _gh_accelerated(f"https://github.com/alibaba/nacos/releases/download/{v}/{filename}")

    # Nacos zip 跨平台通用
    return {
        "Windows": urls,
        "Linux":   urls,
        "Darwin":  urls,
    }


def _nacos_cv(v: str) -> ComponentVersion:
    """
    构造 Nacos 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Nacos 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_nacos_urls(v),
        archive_map={"Windows": "zip", "Linux": "zip", "Darwin": "zip"},
    )


def _seata_urls(v: str) -> Dict[str, List[str]]:
    """
    Seata 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Seata 版本号字符串，如 "2.2.0"
    返回: 三平台同 URL 列表（Seata 跨平台通用 zip），列表顺序即故障转移顺序：
          国内 GitHub 加速器在前（GH_ACCELERATORS），GitHub releases 末位。

    说明:
      - Seata 是 Apache 孵化项目（apache/incubator-seata），在 GitHub releases 发布；
      - 文件名形如 apache-seata-<v>-incubating-bin.zip（2.x）或 seata-server-<v>.zip（1.x）；
      - GitHub Release 没有真镜像，统一走 _gh_accelerated 加前缀（ghproxy.com 已停服，勿再引入）。
    """
    # 实测（2026-09-28）：GitHub 的 apache/incubator-seata release 从 v2.1.0 起资产数为 0
    # （官网改版后二进制只发在 Apache dist），所以原来的 GitHub 直链与三个加速器全部 404。
    # Apache dist 布局：<镜像>/apache/incubator/seata/<v>/apache-seata-<v>-incubating-bin.tar.gz
    # 2.6.0 八家镜像 + archive 全通；2.2.0 只剩华为云两个子域 + archive。
    filename = f"apache-seata-{v}-incubating-bin.tar.gz"
    mirror_bases = [f"{b}/apache/incubator/seata/{v}" for b in
                    _mb("huaweicloud", "huaweicloud-py", "tuna", "aliyun", "nju",
                        "bfsu", "tencent", "ustc")]
    urls = [f"{base}/{filename}" for base in mirror_bases]
    urls.append(f"https://archive.apache.org/dist/incubator/seata/{v}/{filename}")

    # Seata 的 tar.gz 跨平台通用
    return {
        "Windows": list(urls),
        "Linux":   list(urls),
        "Darwin":  list(urls),
    }


def _seata_cv(v: str) -> ComponentVersion:
    """
    构造 Seata 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Seata 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_seata_urls(v),
        archive_map={"Windows": "tar.gz", "Linux": "tar.gz", "Darwin": "tar.gz"},
    )


def _elasticsearch_urls(v: str) -> Dict[str, List[str]]:
    """
    Elasticsearch 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Elasticsearch 版本号字符串，如 "8.15.0"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（华为云 repo→华为云 mirrors），elastic.co 官网末位。

    说明:
      - Elasticsearch 官方在 artifacts.elastic.co 发布跨平台归档包；
      - 版本 8.x 起 URL 含 -<platform>-<arch> 后缀（如 -linux-x86_64.tar.gz）；
      - Windows 是 zip，Linux/Mac 是 tar.gz。
    """
    # 按 CPU 架构挑选路径段（Elasticsearch 用 x86_64 / aarch64）
    arch = "aarch64" if IS_ARM else "x86_64"

    # 实测（2026-09-28）：华为云的 ES 布局多一层版本目录 —— /elasticsearch/<v>/<file>，
    # 原来的平铺拼接恒 404；清华只有 apt/yum 仓库、阿里云没有 elasticsearch 目录，
    # 两家都不是二进制镜像，故大陆只保留华为云 repo 与 mirrors 两个子域。
    # 同步深度也有限：9.2.3 / 8.9.2 全通，8.15.0 与 8.17.10 在华为云都是 404。
    mirror_bases = [f"{b}/elasticsearch/{v}" for b in _mb("huaweicloud", "huaweicloud-py")]
    official_base = "https://artifacts.elastic.co/downloads/elasticsearch"

    # 文件名：elasticsearch-<v>-<platform>-<arch>.<ext>
    #   Windows: elasticsearch-<v>-windows-x86_64.zip
    #   Linux:   elasticsearch-<v>-linux-x86_64.tar.gz / elasticsearch-<v>-linux-aarch64.tar.gz
    #   Mac:     elasticsearch-<v>-darwin-x86_64.tar.gz / elasticsearch-<v>-darwin-aarch64.tar.gz
    win_filename = f"elasticsearch-{v}-windows-{arch}.zip"
    linux_filename = f"elasticsearch-{v}-linux-{arch}.tar.gz"
    mac_filename = f"elasticsearch-{v}-darwin-{arch}.tar.gz"

    win_urls = [f"{base}/{win_filename}" for base in mirror_bases]
    win_urls.append(f"{official_base}/{win_filename}")

    linux_urls = [f"{base}/{linux_filename}" for base in mirror_bases]
    linux_urls.append(f"{official_base}/{linux_filename}")

    mac_urls = [f"{base}/{mac_filename}" for base in mirror_bases]
    mac_urls.append(f"{official_base}/{mac_filename}")

    return {
        "Windows": win_urls,
        "Linux":   linux_urls,
        "Darwin":  mac_urls,
    }


def _elasticsearch_cv(v: str) -> ComponentVersion:
    """
    构造 Elasticsearch 的 ComponentVersion（使用 R1 多源故障转移模式）。

    入参 v: str   Elasticsearch 版本号字符串
    """
    return ComponentVersion(
        version=v,
        url_map={},
        url_list_map=_elasticsearch_urls(v),
        archive_map={"Windows": "zip", "Linux": "tar.gz", "Darwin": "tar.gz"},
    )


# ---------------------------------------------------------------------------
# 官网版本抓取器
# 每个函数负责通过官网 API / 目录列表拿到该组件所有可下载版本。
# 抓取失败会抛异常，调用方需要回退到硬编码默认列表。
# ---------------------------------------------------------------------------
import re as _re
import threading as _threading


class FetchAborted(RuntimeError):
    """应用正在退出，版本抓取被协作式取消。

    与「官网抓不到」区分开：这是主动收尾，不该打印失败日志、也不该走降级提示。
    """


# 版本抓取的协作式取消标志，由 MainWindow.closeEvent 置位。
# 抓取线程大多阻塞在 requests 里，Qt 侧没有「安全杀线程」的接口——QThread 在运行时被
# 析构会直接 abort 进程（Windows 上表现为退出码 0xC0000409），所以只能让线程自己尽快返回：
# 每个重试边界查一次标志，退避等待改用 Event.wait（置位即醒）。
FETCH_ABORT = _threading.Event()


def _get(url: str, timeout: int = 10) -> requests.Response:
    """带自动重试与 SSL 降级的 GET 请求。

    - 网络抖动/临时错误：最多重试 3 次，指数退避（1s, 2s）
    - SSL 错误（企业代理 MITM / 系统证书缺失等）：最后一次尝试关闭 SSL 校验
    - 关窗取消：FETCH_ABORT 置位后在下一次尝试或退避处抛 FetchAborted
    """
    headers = HTTP_UA
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        if FETCH_ABORT.is_set():
            raise FetchAborted("应用正在退出，已取消版本抓取")
        try:
            if attempt < 2:
                r = requests.get(url, timeout=timeout, headers=headers)
            else:
                # 最后一次：关闭 SSL 校验，让企业代理/自签证书场景也能工作
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                r = requests.get(url, timeout=timeout, headers=headers, verify=False)
            r.raise_for_status()
            return r
        except requests.exceptions.SSLError as e:
            last_exc = e
            # SSL 错误直接进入下一次尝试
        except Exception as e:
            last_exc = e
        if attempt < 2:
            if FETCH_ABORT.wait(1 << attempt):  # 原本睡 1s、2s；取消时立刻醒
                raise FetchAborted("应用正在退出，已取消版本抓取")
    assert last_exc is not None
    raise last_exc


def _github_api_json(url: str, timeout: Optional[int] = None) -> dict:
    """从 api.github.com 取 JSON，带 token 与限流感知重试。

    设计定位：作为各组件版本抓取器的「末位官网」兜底来源。

    - 若环境变量 GITHUB_TOKEN / GH_TOKEN 存在，则带 ``Authorization`` 头，
      未认证限额（60 次/小时/IP）提升到 5000 次/小时，能显著降低限流失败。
    - 命中 403 限流（X-RateLimit-Remaining=0）或网络抖动时，按 5s / 10s 退避重试 3 次，
      尽量自愈；仍失败则向上抛，由 VersionFetchWorker 捕获后降级到内置默认清单。

    入参 url:    完整 GitHub API 地址
    入参 timeout: 单请求超时（秒），缺省取 DOWNLOAD_PROBE_TIMEOUT * 2
    返回:       解析后的 JSON（dict / list）
    异常:       所有重试均失败则抛出最后一个异常；关窗取消则抛 FetchAborted
    """
    import os as _os

    headers = dict(HTTP_UA)
    headers["Accept"] = "application/vnd.github+json"
    token = _os.environ.get("GITHUB_TOKEN") or _os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = timeout or (DOWNLOAD_PROBE_TIMEOUT * 2)
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        if FETCH_ABORT.is_set():
            raise FetchAborted("应用正在退出，已取消版本抓取")
        try:
            r = requests.get(url, timeout=timeout, headers=headers)
            # 限流：GitHub 在 remaining=0 时返回 403，此时立即重试无意义，
            # 但短退避可覆盖「突发被临时拒绝」场景，长期限流仍靠 token / 错峰缓解。
            if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
                wait = 5 * (attempt + 1)
                if FETCH_ABORT.wait(wait):
                    raise FetchAborted("应用正在退出，已取消版本抓取")
                last_exc = RuntimeError(
                    f"GitHub API 触发限流（remaining=0），已退避 {wait}s 后重试"
                )
                continue
            r.raise_for_status()
            return r.json()
        except FetchAborted:
            raise
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt < 2 and FETCH_ABORT.wait(5 * (attempt + 1)):
                raise FetchAborted("应用正在退出，已取消版本抓取")
    assert last_exc is not None
    raise last_exc


def _sort_semver_desc(vs) -> list:
    def key(v: str):
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)
    return sorted(set(vs), key=key, reverse=True)


def fetch_jdk_versions() -> List[ComponentVersion]:
    """Adoptium Temurin 官方 API；每个版本再进镜像站目录解析确切文件名。"""
    data = _get("https://api.adoptium.net/v3/info/available_releases").json()
    releases = data.get("available_releases", [])
    lts = data.get("available_lts_releases", [])
    # releases 有时会遗漏最新 LTS —— 合并去重
    vs = sorted({int(v) for v in list(releases) + list(lts)}, reverse=True)
    result = []
    dead: set = set()   # 本次刷新内连不上的镜像基址，避免逐版本重复试探
    avail: dict = {}    # 基址 → 该镜像已同步的 JDK 大版本集合（只列一次根目录）
    for v in vs:
        cv = _cv(str(v), _adoptium_jdk_url(str(v), dead, avail))
        if v in lts:
            cv.display_label = f"{v}  (LTS)"  # type: ignore[attr-defined]
        result.append(cv)
    return result


def fetch_maven_versions() -> List[ComponentVersion]:
    """扫 Apache 归档目录页。"""
    html = _get("https://archive.apache.org/dist/maven/maven-3/").text
    vs = _re.findall(r'href="(3\.\d+\.\d+)/"', html)
    return [_cv(v, _maven_urls(v)) for v in _sort_semver_desc(vs)]


def fetch_tomcat_versions() -> List[ComponentVersion]:
    """扫 tomcat-11 / 10 / 9 三个大版本。"""
    versions: List[str] = []
    for major in ("11", "10", "9"):
        try:
            html = _get(f"https://archive.apache.org/dist/tomcat/tomcat-{major}/").text
            versions.extend(_re.findall(rf'href="v({major}\.\d+\.\d+)/"', html))
        except Exception:
            continue
    if not versions:
        raise RuntimeError("Tomcat 版本列表为空")
    return [_cv(v, _tomcat_urls(v)) for v in _sort_semver_desc(versions)]


def fetch_python_versions() -> List[ComponentVersion]:
    """扫 python.org FTP 索引。"""
    html = _get("https://www.python.org/ftp/python/").text
    vs = _re.findall(r'href="(3\.\d+\.\d+)/"', html)
    # 只保留 3.6+
    vs = [v for v in vs if int(v.split(".")[1]) >= 6]
    return [_cv(v, _python_urls(v)) for v in _sort_semver_desc(vs)]


def fetch_node_versions() -> List[ComponentVersion]:
    """Node.js 官方 dist/index.json。"""
    data = _get("https://nodejs.org/dist/index.json").json()
    # 每个 minor 保留最新 patch，major 10+
    by_key: Dict[tuple, str] = {}
    lts_of_major: Dict[int, str] = {}
    for entry in data:
        v = entry["version"].lstrip("v")
        try:
            parts = tuple(int(x) for x in v.split("."))
        except ValueError:
            continue
        if parts[0] < 10:
            continue
        k = (parts[0], parts[1])
        if k not in by_key or parts > tuple(int(x) for x in by_key[k].split(".")):
            by_key[k] = v
        if entry.get("lts"):
            lts_of_major[parts[0]] = entry["lts"] if isinstance(entry["lts"], str) else "LTS"
    ordered = sorted(by_key.values(),
                     key=lambda v: tuple(int(x) for x in v.split(".")),
                     reverse=True)
    result: List[ComponentVersion] = []
    for v in ordered:
        cv = _cv(v, _node_urls(v))
        major = int(v.split(".")[0])
        if major in lts_of_major:
            cv.display_label = f"{v}  (LTS {lts_of_major[major]})"  # type: ignore[attr-defined]
        result.append(cv)
    return result


def fetch_mysql_versions() -> List[ComponentVersion]:
    """MySQL 没有公开 API，抓 downloads.mysql.com 的归档索引。失败则用一个较新的固定清单。"""
    versions: List[str] = []
    try:
        # dev.mysql.com/downloads/mysql/ 有 CSRF 保护；用归档目录作为最佳可及来源
        for prefix in ("mysql-8.4", "mysql-8.0", "mysql-5.7"):
            try:
                html = _get(f"https://downloads.mysql.com/archives/community/?tpl=version&os=src&version={prefix}",
                            timeout=6).text
                versions.extend(_re.findall(rf'({prefix}\.\d+)', html))
            except Exception:
                continue
    except Exception:
        pass
    if not versions:
        # 保底：一份手工维护的近期列表
        versions = [
            "8.4.2", "8.4.1", "8.4.0",
            "8.0.39", "8.0.38", "8.0.37", "8.0.36", "8.0.35", "8.0.34",
            "5.7.44", "5.7.43", "5.7.42",
        ]
    return [_cv(v, _mysql_urls(v)) for v in _sort_semver_desc(versions)]


def fetch_git_versions() -> List[ComponentVersion]:
    """Git for Windows Releases API。"""
    data = _github_api_json("https://api.github.com/repos/git-for-windows/git/releases?per_page=20")
    versions: List[str] = []
    for rel in data:
        tag = rel.get("tag_name", "")
        # tag 形如 "v2.45.2.windows.1"
        m = _re.match(r"^v(\d+\.\d+\.\d+)(?:\.\w+)?", tag)
        if m:
            versions.append(m.group(1))
    versions = _sort_semver_desc(versions)
    if not versions:
        raise RuntimeError("Git 版本列表为空")
    return [_cv(v, _git_urls(v)) for v in versions[:15]]


def fetch_conda_versions() -> List[ComponentVersion]:
    """Miniconda 归档索引。抓 index 页解析文件名。"""
    html = _get("https://repo.anaconda.com/miniconda/").text
    # 匹配形如 Miniconda3-py312_24.7.1-0-Windows-x86_64.exe
    matches = _re.findall(r"Miniconda3-(py\d+_[\d.\-]+)-(?:Windows|MacOSX|Linux)", html)
    versions = _sort_semver_desc(set(matches))
    # 保底：如果解析失败或列表太少
    if len(versions) < 3:
        versions = [
            "py312_24.7.1-0",
            "py311_24.7.1-0",
            "py310_24.5.0-0",
            "py39_24.5.0-0",
            "latest",
        ]

    def make_cv(v: str) -> ComponentVersion:
        cv = _cv(v, _conda_urls(v))
        # 安装器文件后缀：Windows .exe / mac & linux .sh
        cv.archive_map = {"Windows": "exe", "Darwin": "sh", "Linux": "sh"}
        return cv

    return [make_cv(v) for v in versions[:12]]


def fetch_go_versions() -> List[ComponentVersion]:
    """
    从国内镜像索引页优先抓取 Go 版本列表；镜像均失败回退 go.dev 官方 JSON API。

    返回: ComponentVersion 列表，按版本号倒序，仅保留稳定版（剔除 beta/rc），
          最多 20 个。

    异常: 所有镜像与官网均不可用时抛 RuntimeError，
          由 VersionFetchWorker 捕获并降级到 build_components() 的默认清单。
    """
    # 国内镜像索引页（HTML 目录列表），按 R1 优先级排序
    mirror_index_urls = [
        "https://repo.huaweicloud.com/golang/",
        "https://mirrors.tuna.tsinghua.edu.cn/golang/",
        "https://mirrors.aliyun.com/golang/",
        "https://mirrors.ustc.edu.cn/golang/",
    ]
    versions: List[str] = []
    # 第一阶段：依次尝试镜像索引页，扫 HTML 拿版本号
    for idx, idx_url in enumerate(mirror_index_urls, 1):
        try:
            html = _get(idx_url, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            # 匹配形如 go1.22.5.windows-amd64.zip / go1.21.12.linux-arm64.tar.gz 中的版本号
            vs = _re.findall(r'go(\d+\.\d+\.\d+)\.', html)
            if vs:
                versions = list(set(vs))
                break
        except Exception:
            continue

    # 第二阶段：镜像都失败 → 回退 go.dev 官方 JSON API
    if not versions:
        try:
            data = _get(
                "https://go.dev/dl/?mode=json&include=all",
                timeout=DOWNLOAD_PROBE_TIMEOUT * 2,
            ).json()
            for rel in data:
                v = rel.get("version", "").lstrip("go")
                if v:
                    versions.append(v)
        except Exception as exc:
            raise RuntimeError(
                f"Go 版本列表抓取失败：所有国内镜像与官网均不可用：{exc}"
            ) from exc

    # 过滤掉 beta/rc，按语义版本倒序，取前 20 个
    stable = [
        v for v in _sort_semver_desc(versions)
        if "beta" not in v and "rc" not in v
    ]
    if not stable:
        raise RuntimeError("Go 版本列表为空（镜像与官网均未返回有效版本）")
    return [_go_cv(v) for v in stable[:20]]


def fetch_gradle_versions() -> List[ComponentVersion]:
    """
    从国内镜像索引页优先抓取 Gradle 版本列表；镜像均失败回退官网索引页。

    返回: ComponentVersion 列表，按版本号倒序，仅保留稳定版（剔除 -rc / -milestone），
          最多 20 个。

    异常: 所有镜像与官网均不可用时抛 RuntimeError，
          由 VersionFetchWorker 捕获并降级到 build_components() 的默认清单。
    """
    # 国内镜像索引页（HTML 目录列表），按 R1 优先级排序
    mirror_index_urls = [
        "https://repo.huaweicloud.com/gradle/",
        "https://mirrors.tuna.tsinghua.edu.cn/gradle/",
        "https://mirrors.aliyun.com/gradle/",
        "https://mirrors.ustc.edu.cn/gradle/",
    ]
    # 官网索引页（末位回退）
    official_index = "https://services.gradle.org/distributions/"
    # Gradle 版本号格式：X.Y 或 X.Y.Z（如 8.10、8.9.1、7.6.4）
    pattern = _re.compile(r'gradle-(\d+\.\d+(?:\.\d+)?)-bin\.zip')

    versions: List[str] = []
    # 第一阶段：依次尝试国内镜像索引页
    for idx_url in mirror_index_urls:
        try:
            html = _get(idx_url, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            vs = pattern.findall(html)
            if vs:
                versions = list(set(vs))
                break
        except Exception:
            continue

    # 第二阶段：镜像都失败 → 回退官网索引页
    if not versions:
        try:
            html = _get(official_index, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            versions = list(set(pattern.findall(html)))
        except Exception as exc:
            raise RuntimeError(
                f"Gradle 版本列表抓取失败：所有国内镜像与官网均不可用：{exc}"
            ) from exc

    # 过滤掉预发布版本（-rc、-milestone 等），按版本号倒序，取前 20
    stable = [
        v for v in _sort_semver_desc(versions)
        if "-" not in v  # 任何带 - 的预发布版本都跳过
    ]
    if not stable:
        raise RuntimeError("Gradle 版本列表为空（镜像与官网均未返回有效版本）")
    return [_gradle_cv(v) for v in stable[:20]]


def fetch_bun_versions() -> List[ComponentVersion]:
    """
    从国内镜像（npmmirror）优先抓取 Bun 版本列表；镜像失败回退 GitHub Releases API。

    返回: ComponentVersion 列表，按版本号倒序，仅保留稳定版（剔除 canary），
          最多 20 个。

    异常: 镜像与 GitHub API 均不可用时抛 RuntimeError，
          由 VersionFetchWorker 捕获并降级到 build_components() 的默认清单。
    """
    # 国内镜像索引页（npmmirror，HTML/JSON 列表）
    npmmirror_index = "https://registry.npmmirror.com/-/binary/bun/"
    # 官方 API（末位回退）：GitHub Releases API（未认证限速 60 次/小时，对工具够用）
    github_api = "https://api.github.com/repos/oven-sh/bun/releases?per_page=50"

    versions: List[str] = []
    # 第一阶段：npmmirror 镜像索引（返回 JSON 或 HTML 列表，扫 bun-v<version> 标识）
    try:
        text = _get(npmmirror_index, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
        # npmmirror 列表里目录名格式：bun-v1.1.0 或 1.1.0
        vs = _re.findall(r'bun-v?(\d+\.\d+\.\d+)', text)
        if vs:
            versions = list(set(vs))
    except Exception:
        pass

    # 第二阶段：镜像失败 → 回退 GitHub Releases API（JSON）
    if not versions:
        try:
            data = _github_api_json(github_api)
            for rel in data:
                tag = rel.get("tag_name", "")
                # Bun tag 格式为 bun-v<version>；canary 版本含 -canary 后缀，剔除
                if tag.startswith("bun-v") and "canary" not in tag and "-" not in tag[len("bun-v"):]:
                    versions.append(tag[len("bun-v"):])
        except Exception as exc:
            raise RuntimeError(
                f"Bun 版本列表抓取失败：npmmirror 与 GitHub API 均不可用：{exc}"
            ) from exc

    # 过滤 + 倒序，取前 20
    stable = [v for v in _sort_semver_desc(versions) if "canary" not in v and "-" not in v]
    if not stable:
        raise RuntimeError("Bun 版本列表为空（npmmirror 与 GitHub API 均未返回有效版本）")
    return [_bun_cv(v) for v in stable[:20]]


def fetch_docker_versions() -> List[ComponentVersion]:
    """
    从国内镜像索引页优先抓取 Docker static binary 版本列表；镜像均失败回退官网索引页。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。

    异常: 所有镜像与官网均不可用时抛 RuntimeError，
          由 VersionFetchWorker 捕获并降级到 build_components() 的默认清单。
    """
    # 国内镜像索引页（HTML 目录列表），按 R1 优先级排序
    # docker-ce 镜像的 static binaries 索引页：linux/static/stable/<arch>/
    arch = "aarch64" if IS_ARM else "x86_64"
    mirror_index_urls = [
        f"https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/static/stable/{arch}/",
        f"https://mirrors.aliyun.com/docker-ce/linux/static/stable/{arch}/",
        f"https://mirrors.ustc.edu.cn/docker-ce/linux/static/stable/{arch}/",
    ]
    official_index = f"https://download.docker.com/linux/static/stable/{arch}/"
    # Docker static binary 命名：docker-<v>.tgz，v 含 build 号如 27.3.1 或 27.3.1.tgz
    pattern = _re.compile(r'docker-(\d+\.\d+\.\d+(?:\.\d+)?)\.tgz')

    versions: List[str] = []
    for idx_url in mirror_index_urls:
        try:
            html = _get(idx_url, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            vs = pattern.findall(html)
            if vs:
                versions = list(set(vs))
                break
        except Exception:
            continue

    if not versions:
        try:
            html = _get(official_index, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            versions = list(set(pattern.findall(html)))
        except Exception as exc:
            raise RuntimeError(
                f"Docker 版本列表抓取失败：所有国内镜像与官网均不可用：{exc}"
            ) from exc

    stable = _sort_semver_desc(versions)
    if not stable:
        raise RuntimeError("Docker 版本列表为空（镜像与官网均未返回有效版本）")
    return [_docker_cv(v) for v in stable[:20]]


def fetch_mongodb_versions() -> List[ComponentVersion]:
    """
    从国内镜像（清华）优先抓取 MongoDB 版本列表；镜像失败回退官网 API。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。

    异常: 镜像与官网 API 均不可用时抛 RuntimeError，
          由 VersionFetchWorker 捕获并降级到 build_components() 的默认清单。
    """
    # 国内镜像索引页（HTML 目录列表），按 R1 优先级排序
    mirror_index_urls = [
        "https://mirrors.tuna.tsinghua.edu.cn/mongodb/linux/",
        "https://mirrors.aliyun.com/mongodb/linux/",
        "https://mirrors.ustc.edu.cn/mongodb/linux/",
        "https://repo.huaweicloud.com/mongodb/linux/",
    ]
    # MongoDB 官方下载中心（无目录索引页，走 GitHub releases API 作为末位 fallback）
    # MongoDB 的 mongo 仓库在 GitHub 上有 tags，可用于反推版本号
    github_api = "https://api.github.com/repos/mongodb/mongo/tags?per_page=50"
    # MongoDB 命名：mongodb-linux-x86_64-<v>.tgz（v 形如 8.0.0、7.0.5）
    arch = "aarch64" if IS_ARM else "x86_64"
    pattern = _re.compile(
        rf'mongodb-linux-{arch}-(\d+\.\d+\.\d+(?:\.\d+)?)\.tgz'
    )

    versions: List[str] = []
    for idx_url in mirror_index_urls:
        try:
            html = _get(idx_url, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            vs = pattern.findall(html)
            if vs:
                versions = list(set(vs))
                break
        except Exception:
            continue

    if not versions:
        try:
            # GitHub tags API：tag_name 形如 r8.0.0 / r7.0.5
            data = _github_api_json(github_api)
            for tag in data:
                name = tag.get("name", "")
                # MongoDB 的 tag 是 r<version> 格式
                if name.startswith("r") and name[1:2].isdigit():
                    v = name[1:]
                    if _re.match(r'^\d+\.\d+\.\d+$', v):
                        versions.append(v)
        except Exception as exc:
            raise RuntimeError(
                f"MongoDB 版本列表抓取失败：镜像与 GitHub API 均不可用：{exc}"
            ) from exc

    stable = _sort_semver_desc(versions)
    if not stable:
        raise RuntimeError("MongoDB 版本列表为空（镜像与 GitHub API 均未返回有效版本）")
    return [_mongodb_cv(v) for v in stable[:20]]


def fetch_postgresql_versions() -> List[ComponentVersion]:
    """
    抓取 PostgreSQL 版本列表：先扫官网 ftp/source 镜像索引页，失败回退 GitHub tags。

    返回: ComponentVersion 列表，按版本号倒序，仅保留稳定版，最多 20 个。

    异常: 镜像与 GitHub API 均不可用时抛 RuntimeError，
          由 VersionFetchWorker 捕获并降级到 build_components() 的默认清单。

    说明: PostgreSQL binaries 在 EDB 官网，没有索引页，无法直接扫版本；
          通过镜像的 source 目录或 GitHub tags 反推版本号。
    """
    # 国内镜像的 source 目录（HTML 列表，路径 v<version>/）
    mirror_source_urls = [
        "https://mirrors.tuna.tsinghua.edu.cn/postgresql/source/",
        "https://mirrors.ustc.edu.cn/postgresql/source/",
        "https://mirrors.aliyun.com/postgresql/source/",
        "https://repo.huaweicloud.com/postgresql/source/",
    ]
    # PostgreSQL 官方 GitHub 仓库 tags（postgres/postgres）
    github_api = "https://api.github.com/repos/postgres/postgres/tags?per_page=50"
    # source 目录里版本格式：v<X.Y.Z>/
    pattern = _re.compile(r'v(\d+\.\d+(?:\.\d+)?)')

    versions: List[str] = []
    for idx_url in mirror_source_urls:
        try:
            html = _get(idx_url, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            vs = pattern.findall(html)
            if vs:
                versions = list(set(vs))
                break
        except Exception:
            continue

    if not versions:
        try:
            data = _github_api_json(github_api)
            for tag in data:
                name = tag.get("name", "")
                # PostgreSQL 的 tag 是 REL_<X>_<Y>_<Z> 格式
                m = _re.match(r'^REL_(\d+)_(\d+)_(\d+)$', name)
                if m:
                    versions.append(f"{m.group(1)}.{m.group(2)}.{m.group(3)}")
        except Exception as exc:
            raise RuntimeError(
                f"PostgreSQL 版本列表抓取失败：镜像与 GitHub API 均不可用：{exc}"
            ) from exc

    # 过滤掉 beta/rc（PostgreSQL 用 beta1 / rc1 后缀）
    stable = [
        v for v in _sort_semver_desc(versions)
        if "beta" not in v and "rc" not in v
    ]
    if not stable:
        raise RuntimeError("PostgreSQL 版本列表为空（镜像与 GitHub API 均未返回有效版本）")
    return [_postgresql_cv(v) for v in stable[:20]]


def fetch_kubectl_versions() -> List[ComponentVersion]:
    """
    抓取 kubectl 版本列表：优先从国内镜像（阿里云）索引页，失败回退 GitHub API。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。

    异常: 镜像与 GitHub API 均不可用时抛 RuntimeError，
          由 VersionFetchWorker 捕获并降级到 build_components() 的默认清单。
    """
    # 阿里云镜像索引页（HTML 目录列表）
    mirror_index = "https://mirrors.aliyun.com/kubernetes-release/release/"
    # GitHub API（末位官网）
    github_api = "https://api.github.com/repos/kubernetes/kubernetes/tags?per_page=50"
    pattern = _re.compile(r'v(\d+\.\d+\.\d+)')

    versions: List[str] = []
    try:
        html = _get(mirror_index, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
        versions = list(set(pattern.findall(html)))
    except Exception:
        pass

    if not versions:
        try:
            data = _github_api_json(github_api)
            for tag in data:
                name = tag.get("name", "")
                if name.startswith("v"):
                    v = name[1:]
                    if _re.match(r'^\d+\.\d+\.\d+$', v):
                        versions.append(v)
        except Exception as exc:
            raise RuntimeError(
                f"kubectl 版本列表抓取失败：镜像与 GitHub API 均不可用：{exc}"
            ) from exc

    stable = _sort_semver_desc(versions)
    if not stable:
        raise RuntimeError("kubectl 版本列表为空（镜像与 GitHub API 均未返回有效版本）")
    return [_kubectl_cv(v) for v in stable[:20]]


def fetch_jenkins_versions() -> List[ComponentVersion]:
    """
    抓取 Jenkins LTS 版本列表：优先从国内镜像（清华）索引页，失败回退官网索引页。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。

    异常: 镜像与官网均不可用时抛 RuntimeError。
    """
    mirror_index = "https://mirrors.tuna.tsinghua.edu.cn/jenkins/war-stable/"
    official_index = "https://get.jenkins.io/war-stable/"
    pattern = _re.compile(r'(\d+\.\d+(?:\.\d+)?)')

    versions: List[str] = []
    try:
        html = _get(mirror_index, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
        versions = list(set(pattern.findall(html)))
    except Exception:
        pass

    if not versions:
        try:
            html = _get(official_index, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            versions = list(set(pattern.findall(html)))
        except Exception as exc:
            raise RuntimeError(
                f"Jenkins 版本列表抓取失败：镜像与官网均不可用：{exc}"
            ) from exc

    # Jenkins LTS 形如 2.426.3，过滤掉过短或非 X.Y.Z 格式
    stable = [
        v for v in _sort_semver_desc(versions)
        if _re.match(r'^\d+\.\d+\.\d+$', v)
    ]
    if not stable:
        raise RuntimeError("Jenkins 版本列表为空（镜像与官网均未返回有效版本）")
    return [_jenkins_cv(v) for v in stable[:20]]


def fetch_rabbitmq_versions() -> List[ComponentVersion]:
    """
    抓取 RabbitMQ 版本列表：从 GitHub releases API 反推版本号。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。

    异常: GitHub API 不可用时抛 RuntimeError。
    """
    github_api = "https://api.github.com/repos/rabbitmq/rabbitmq-server/releases?per_page=50"

    try:
        data = _github_api_json(github_api)
    except Exception as exc:
        raise RuntimeError(
            f"RabbitMQ 版本列表抓取失败：GitHub API 不可用：{exc}"
        ) from exc

    versions: List[str] = []
    for rel in data:
        tag = rel.get("tag_name", "")
        # RabbitMQ tag 形如 v4.0.0
        if tag.startswith("v"):
            v = tag[1:]
            if _re.match(r'^\d+\.\d+\.\d+$', v):
                versions.append(v)

    stable = _sort_semver_desc(versions)
    if not stable:
        raise RuntimeError("RabbitMQ 版本列表为空（GitHub API 未返回有效版本）")
    return [_rabbitmq_cv(v) for v in stable[:20]]


def _fetch_apache_versions(key: str) -> List[str]:
    """
    从国内镜像（华为云）抓取 Apache 项目版本目录列表。

    入参 key: str  Apache 项目 key（如 "kafka" / "rocketmq" / "pulsar" / "activemq"）
    返回:     版本号字符串列表（未排序）。

    异常:     镜像索引页不可用时抛 RuntimeError。

    说明: Apache 项目在 archive.apache.org/dist/<key>/ 下有版本目录，
          国内镜像路径结构与官网一致（如华为云 /apache/<key>/）。
    """
    mirror_indexes = [
        f"https://repo.huaweicloud.com/apache/{key}/",
        f"https://mirrors.tuna.tsinghua.edu.cn/apache/{key}/",
        f"https://mirrors.aliyun.com/apache/{key}/",
        f"https://mirrors.ustc.edu.cn/apache/{key}/",
    ]
    official_index = f"https://archive.apache.org/dist/{key}/"
    pattern = _re.compile(r'(\d+\.\d+\.\d+(?:[\.-]\d+)?)')

    versions: List[str] = []
    for idx_url in mirror_indexes:
        try:
            html = _get(idx_url, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            vs = pattern.findall(html)
            if vs:
                versions = list(set(vs))
                break
        except Exception:
            continue

    if not versions:
        try:
            html = _get(official_index, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            versions = list(set(pattern.findall(html)))
        except Exception as exc:
            raise RuntimeError(
                f"Apache {key} 版本列表抓取失败：镜像与官网均不可用：{exc}"
            ) from exc

    return versions


def fetch_kafka_versions() -> List[ComponentVersion]:
    """
    从国内镜像（华为云）抓取 Apache Kafka 版本列表。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。
    """
    versions = _fetch_apache_versions("kafka")
    # 过滤掉 incubating / beta 等不稳定版本
    stable = [
        v for v in _sort_semver_desc(versions)
        if "incubating" not in v and "beta" not in v and "rc" not in v
    ]
    if not stable:
        raise RuntimeError("Kafka 版本列表为空（镜像与官网均未返回有效版本）")
    return [_kafka_cv(v) for v in stable[:20]]


def fetch_rocketmq_versions() -> List[ComponentVersion]:
    """
    从国内镜像（华为云）抓取 Apache RocketMQ 版本列表。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。
    """
    versions = _fetch_apache_versions("rocketmq")
    stable = [
        v for v in _sort_semver_desc(versions)
        if "incubating" not in v and "beta" not in v
    ]
    if not stable:
        raise RuntimeError("RocketMQ 版本列表为空（镜像与官网均未返回有效版本）")
    return [_rocketmq_cv(v) for v in stable[:20]]


def fetch_pulsar_versions() -> List[ComponentVersion]:
    """
    从国内镜像（华为云）抓取 Apache Pulsar 版本列表。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。
    """
    versions = _fetch_apache_versions("pulsar")
    stable = [
        v for v in _sort_semver_desc(versions)
        if "incubating" not in v and "beta" not in v and "rc" not in v
    ]
    if not stable:
        raise RuntimeError("Pulsar 版本列表为空（镜像与官网均未返回有效版本）")
    return [_pulsar_cv(v) for v in stable[:20]]


def fetch_activemq_versions() -> List[ComponentVersion]:
    """
    从国内镜像（华为云）抓取 ActiveMQ 版本列表。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。
    """
    versions = _fetch_apache_versions("activemq")
    stable = [
        v for v in _sort_semver_desc(versions)
        if "incubating" not in v and "beta" not in v and "rc" not in v
    ]
    if not stable:
        raise RuntimeError("ActiveMQ 版本列表为空（镜像与官网均未返回有效版本）")
    return [_activemq_cv(v) for v in stable[:20]]


def _fetch_github_releases_versions(repo: str, prefix: str = "v") -> List[str]:
    """
    从 GitHub releases API 反推版本号（供 Nacos / Seata 等 GitHub 发布的组件用）。

    入参 repo: str    GitHub 仓库全名，如 "alibaba/nacos"
    入参 prefix: str  tag 前缀，Nacos 用空字符串，Seata 用 "v" 前缀，默认 "v"
    返回:             版本号字符串列表（未排序）。

    异常: GitHub API 不可用时抛 RuntimeError。

    说明: 走 GitHub releases?per_page=50 端点，过滤掉 prerelease / draft，
          提取 tag_name 去掉前缀后的版本号；GitHub API 在国内访问较慢，
          调用方应将本函数作为末位 fallback，首选国内镜像索引页。
    """
    api = f"https://api.github.com/repos/{repo}/releases?per_page=50"

    try:
        data = _github_api_json(api)
    except Exception as exc:
        raise RuntimeError(
            f"GitHub releases 抓取失败（{repo}）：{exc}"
        ) from exc

    versions: List[str] = []
    for rel in data:
        # 跳过 prerelease / draft
        if rel.get("prerelease") or rel.get("draft"):
            continue
        tag = rel.get("tag_name", "")
        # 去掉前缀（Nacos tag 无前缀，Seata 用 v 前缀）
        v = tag[len(prefix):] if prefix and tag.startswith(prefix) else tag
        if _re.match(r'^\d+\.\d+\.\d+$', v):
            versions.append(v)

    return versions


def fetch_nacos_versions() -> List[ComponentVersion]:
    """
    从 GitHub releases API 抓取 Nacos 版本列表（Nacos 在国内无镜像索引页，主走 GitHub API）。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。
    """
    versions = _fetch_github_releases_versions("alibaba/nacos", prefix="")
    stable = _sort_semver_desc(versions)
    if not stable:
        raise RuntimeError("Nacos 版本列表为空（GitHub API 未返回有效版本）")
    return [_nacos_cv(v) for v in stable[:20]]


def fetch_seata_versions() -> List[ComponentVersion]:
    """
    抓取 Seata 版本列表：Seata 已毕业为 Apache 项目，优先走国内 Apache 镜像目录
    （华为云/清华/阿里云/USTC + archive.apache.org），镜像全失败再回退 GitHub API。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。

    异常: 镜像与 GitHub API 均不可用时抛 RuntimeError，由 VersionFetchWorker 降级到内置清单。
    """
    # 第一阶段：国内 Apache 镜像目录优先（不触碰 api.github.com）
    try:
        vs = _fetch_apache_versions("seata")
        stable = [
            v for v in _sort_semver_desc(vs)
            if not any(x in v for x in ("incubating", "beta", "rc"))
        ]
        if stable:
            return [_seata_cv(v) for v in stable[:20]]
    except Exception:
        pass
    # 第二阶段：镜像都失败 → 回退 GitHub API（末位官网）
    versions = _fetch_github_releases_versions("apache/incubator-seata", prefix="v")
    stable = _sort_semver_desc(versions)
    if not stable:
        raise RuntimeError("Seata 版本列表为空（镜像与 GitHub API 均未返回有效版本）")
    return [_seata_cv(v) for v in stable[:20]]


def fetch_elasticsearch_versions() -> List[ComponentVersion]:
    """
    抓取 Elasticsearch 版本列表：优先从国内镜像（清华）索引页，失败回退 elastic.co 官网索引页。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。
    """
    # 国内镜像索引页
    mirror_indexes = [
        "https://mirrors.tuna.tsinghua.edu.cn/elasticsearch/",
        "https://mirrors.aliyun.com/elasticsearch/",
        "https://repo.huaweicloud.com/elasticsearch/",
    ]
    # 官网索引页（HTML 目录列表，但 elastic.co 实际无目录列表页，
    # 这里通过 GitHub tags API 作为末位 fallback 更稳）
    github_api = "https://api.github.com/repos/elastic/elasticsearch/tags?per_page=50"
    pattern = _re.compile(r'v(\d+\.\d+\.\d+)')

    versions: List[str] = []
    for idx_url in mirror_indexes:
        try:
            html = _get(idx_url, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).text
            vs = pattern.findall(html)
            if vs:
                versions = list(set(vs))
                break
        except Exception:
            continue

    if not versions:
        try:
            data = _github_api_json(github_api)
            for tag in data:
                name = tag.get("name", "")
                if name.startswith("v"):
                    v = name[1:]
                    if _re.match(r'^\d+\.\d+\.\d+$', v):
                        versions.append(v)
        except Exception as exc:
            raise RuntimeError(
                f"Elasticsearch 版本列表抓取失败：镜像与 GitHub API 均不可用：{exc}"
            ) from exc

    # 过滤掉 alpha/beta/rc 等不稳定版本（ES 8.x 有大量 alpha 版本）
    stable = [
        v for v in _sort_semver_desc(versions)
        if "alpha" not in v and "beta" not in v and "rc" not in v
        and "SNAPSHOT" not in v
    ]
    if not stable:
        raise RuntimeError("Elasticsearch 版本列表为空（镜像与 GitHub API 均未返回有效版本）")
    return [_elasticsearch_cv(v) for v in stable[:20]]


FETCHERS: Dict[str, Callable[[], List[ComponentVersion]]] = {
    "jdk": fetch_jdk_versions,
    "maven": fetch_maven_versions,
    "tomcat": fetch_tomcat_versions,
    "python": fetch_python_versions,
    "node": fetch_node_versions,
    "mysql": fetch_mysql_versions,
    "git": fetch_git_versions,
    "conda": fetch_conda_versions,
    "go": fetch_go_versions,
    "gradle": fetch_gradle_versions,
    "bun": fetch_bun_versions,
    "docker": fetch_docker_versions,
    "mongodb": fetch_mongodb_versions,
    "postgresql": fetch_postgresql_versions,
    "kubectl": fetch_kubectl_versions,
    "jenkins": fetch_jenkins_versions,
    "rabbitmq": fetch_rabbitmq_versions,
    "kafka": fetch_kafka_versions,
    "rocketmq": fetch_rocketmq_versions,
    "pulsar": fetch_pulsar_versions,
    "activemq": fetch_activemq_versions,
    "nacos": fetch_nacos_versions,
    "seata": fetch_seata_versions,
    "elasticsearch": fetch_elasticsearch_versions,
    "powershell": fetch_powershell_versions,
    "nginx": fetch_nginx_versions,
}


class VersionFetchWorker(QThread):
    """在后台线程里跑抓取器，避免阻塞 UI。"""

    done = Signal(str, object)  # (component_key, versions or None)

    def __init__(self, key: str, fetcher: Callable[[], List[ComponentVersion]],
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.key = key
        self.fetcher = fetcher

    def run(self) -> None:  # noqa: D401
        try:
            vs = self.fetcher()
        except FetchAborted:
            self.done.emit(self.key, None)  # 关窗取消：静默收尾，不打失败日志
        except Exception as exc:  # pragma: no cover
            # 抓取器内部普遍用 except Exception 兜底重抛 RuntimeError，
            # 取消异常可能被包装成普通失败；已在退出中就保持安静，别刷 26 行噪声。
            if not FETCH_ABORT.is_set():
                print(f"[fetch:{self.key}] {exc}")
            self.done.emit(self.key, None)
        else:
            self.done.emit(self.key, vs)


# 界面 Tab 分组：三个分类的显示顺序（Tab 顺序即此顺序）
COMPONENT_CATEGORIES = ("开发环境", "开发软件", "其它软件")

# 组件 → 分类。**这是唯一一处**分类登记表：新增组件只在这里加一行，
# build_components() 末尾统一赋值到 Component.category，界面自动出现在对应 Tab。
#   开发环境：装完进 PATH、直接用来写 / 编译 / 打包代码
#   开发软件：本地跑起来给项目当依赖的服务（数据库 / 消息队列 / 注册中心 / 搜索）
#   其它软件：不参与写代码的容器、编排与 CI 外围
COMPONENT_CATEGORY_OF = {
    "jdk": "开发环境", "python": "开发环境", "node": "开发环境", "go": "开发环境",
    "bun": "开发环境", "conda": "开发环境", "git": "开发环境",
    "maven": "开发环境", "gradle": "开发环境", "powershell": "开发环境",
    "tomcat": "开发软件", "mysql": "开发软件", "mongodb": "开发软件",
    "postgresql": "开发软件", "elasticsearch": "开发软件", "nacos": "开发软件",
    "seata": "开发软件", "kafka": "开发软件", "rocketmq": "开发软件",
    "pulsar": "开发软件", "activemq": "开发软件", "rabbitmq": "开发软件",
    "nginx": "开发软件",
    "docker": "其它软件", "kubectl": "其它软件", "jenkins": "其它软件",
}

# 允许并存多版本、可切换生效版本的组件（2026-09-29 与用户确认，固定 7 个，别自行扩大）。
# 排除 conda：installer_mode 组件装在固定目录、卸载也不删目录，"每版本一目录"的前提不成立。
# 排除服务型组件（mysql/tomcat/nacos/es/…）：多版本的真矛盾是端口与数据目录，不是环境变量。
MULTI_VERSION_KEYS = {"jdk", "python", "node", "go", "maven", "gradle", "bun"}


def group_components(components: List[Component]) -> Dict[str, List[Component]]:
    """按 COMPONENT_CATEGORIES 的顺序分组，供界面建 Tab。"""
    grouped: Dict[str, List[Component]] = {name: [] for name in COMPONENT_CATEGORIES}
    for comp in components:
        grouped[comp.category].append(comp)   # 未登记的分类直接 KeyError
    return grouped


def component_matches(comp: Component, query: str) -> bool:
    """
    界面搜索框用的模糊匹配：查询词是否命中该组件。

    入参 comp:  Component  待判定的组件
    入参 query: str        用户输入的查询词
    返回:      bool  空查询恒为 True（等于不过滤）；否则要求查询词是
                     显示名或内部 key 的子串（忽略大小写与首尾空白）

    说明: 只匹配「显示名 + key」这两个用户看得见的标识，不匹配分类名——
          分类已经由 Tab 页表达，再混进来会让搜「开发」跳出全部卡片。
    """
    q = query.strip().lower()
    if not q:
        return True
    return q in comp.display_name.lower() or q in comp.key.lower()


def build_components() -> List[Component]:
    """构造预置的组件与版本信息（作为抓取完成前的默认列表）。"""

    components: List[Component] = []
    # ------------------ JDK ------------------
    components.append(
        Component(
            key="jdk",
            display_name="JDK (Temurin)",
            env_var="JAVA_HOME",
            path_subdir="bin",
            exec_name="java",
            version_args=["-version"],
            versions=[
                _cv(v, _adoptium_jdk_url(v, resolve_mirrors=False))
                for v in ("21", "17", "11", "8")
            ],
        )
    )

    # ------------------ Maven ------------------
    components.append(
        Component(
            key="maven",
            display_name="Apache Maven",
            env_var="MAVEN_HOME",
            path_subdir="bin",
            exec_name="mvn",
            version_args=["-v"],
            versions=[_cv(v, _maven_urls(v)) for v in ("3.9.16", "3.9.6", "3.8.8", "3.6.3")],
        )
    )

    # ------------------ Tomcat ------------------
    components.append(
        Component(
            key="tomcat",
            display_name="Apache Tomcat",
            env_var="CATALINA_HOME",
            path_subdir="bin",
            exec_name="catalina",
            version_args=["version"],
            versions=[_cv(v, _tomcat_urls(v)) for v in ("10.1.60", "9.0.122", "8.5.100")],
        )
    )

    # ------------------ Nginx ------------------
    # Windows 有官方预编译 zip（解压后根目录就是 nginx.exe）；
    # Linux/macOS 上游只发源码 .tar.gz（要自己 configure + make），
    # 与 Git 同理：不给这两个平台 URL，改由 unsupported_platform_hint 引导包管理器
    components.append(
        Component(
            key="nginx",
            display_name="Nginx",
            env_var=None,        # nginx 没有 NGINX_HOME 概念，只进 PATH
            path_subdir="",      # nginx.exe 直接在解压根目录
            exec_name="nginx",
            version_args=["-v"],  # nginx -v 只打印版本就退出，可以安全探测
            unsupported_platform_hint=(
                "Nginx 在 Linux/macOS 上游只发布源码包（解压后没有可执行文件，需自行编译），"
                "本工具不提供该平台的自动下载。请用系统包管理器安装："
                "Debian/Ubuntu 执行 sudo apt install nginx；"
                "RHEL/CentOS/Anolis 执行 sudo dnf install nginx 或 sudo yum install nginx；"
                "macOS 执行 brew install nginx。"
            ),
            versions=[_nginx_cv(v) for v in ("1.31.6", "1.28.0", "1.26.3")],
        )
    )

    # ------------------ MySQL ------------------
    components.append(
        Component(
            key="mysql",
            display_name="MySQL Server",
            env_var="MYSQL_HOME",
            path_subdir="bin",
            exec_name="mysql",
            version_args=["--version"],
            versions=[_cv(v, _mysql_urls(v), {"Linux": "tar.xz"})
                      for v in ("8.0.28", "8.0.29", "8.0.37")],
        )
    )

    # ------------------ Python ------------------
    components.append(
        Component(
            key="python",
            display_name="Python",
            env_var=None,
            path_subdir="Scripts" if CURRENT_OS == "Windows" else "bin",
            exec_name="python3" if CURRENT_OS != "Windows" else "python",
            version_args=["--version"],
            versions=[_cv(v, _python_urls(v)) for v in ("3.12.4", "3.11.9", "3.10.11", "3.9.13")],
        )
    )

    # ------------------ Node.js ------------------
    components.append(
        Component(
            key="node",
            display_name="Node.js",
            env_var="NODE_HOME",
            path_subdir="bin",
            exec_name="node",
            version_args=["--version"],
            versions=[_cv(v, _node_urls(v)) for v in ("20.15.0", "18.20.3", "16.20.2")],
        )
    )

    # ------------------ Git ------------------
    # Windows 用 MinGit 便携版；macOS/Linux 上游只有源码包（解压不能用），
    # 所以不提供自动下载，改由 unsupported_platform_hint 引导用系统包管理器
    components.append(
        Component(
            key="git",
            display_name="Git",
            env_var=None,
            path_subdir="cmd" if CURRENT_OS == "Windows" else "bin",
            exec_name="git",
            version_args=["--version"],
            unsupported_platform_hint=(
                "Git 在 Linux/macOS 上游只发布源码包（解压后没有可执行文件，需自行编译），"
                "本工具不提供该平台的自动下载。请用系统包管理器安装："
                "Debian/Ubuntu 执行 sudo apt install git；"
                "RHEL/CentOS/Anolis 执行 sudo dnf install git 或 sudo yum install git；"
                "macOS 执行 brew install git（或先装 Xcode Command Line Tools）。"
            ),
            versions=[_cv(v, _git_urls(v)) for v in ("2.47.1", "2.45.2", "2.44.0")],
        )
    )

    # ------------------ PowerShell 7 ------------------
    # 三平台都有官方便携包（Windows zip / Linux·macOS tar.gz），解压根目录就是 pwsh；
    # 上游只在 GitHub Releases 发版、国内没有真镜像，按 R1 走 GitHub 加速器在前
    components.append(
        Component(
            key="powershell",
            display_name="PowerShell 7",
            env_var=None,        # pwsh 没有 PS_HOME 概念，只进 PATH
            path_subdir="",      # 可执行文件在解压根目录，无 bin 子目录
            exec_name="pwsh",
            version_args=["--version"],
            versions=[_pwsh_cv(v) for v in ("7.6.6", "7.5.11", "7.4.20")],
        )
    )

    # ------------------ Miniconda ------------------
    # 安装器模式：exe/sh 静默安装到 install_dir
    conda_versions = []
    for v in ("py312_24.7.1-0", "py311_24.7.1-0", "py310_24.5.0-0"):
        cv = _cv(v, _conda_urls(v))
        cv.archive_map = {"Windows": "exe", "Darwin": "sh", "Linux": "sh"}
        conda_versions.append(cv)
    components.append(
        Component(
            key="conda",
            display_name="Miniconda",
            env_var="CONDA_HOME",
            path_subdir="Scripts" if CURRENT_OS == "Windows" else "bin",
            exec_name="conda",
            version_args=["--version"],
            versions=conda_versions,
            installer_mode=True,
            installer_args={
                # /S = silent, /D=path 必须放最后
                "Windows": ["/S", "/InstallationType=JustMe", "/RegisterPython=0", "/AddToPath=0"],
                # -b batch, -f force overwrite, -p prefix
                "Darwin": ["-b", "-f", "-p"],
                "Linux": ["-b", "-f", "-p"],
            },
        )
    )

    # ------------------ Go ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位官网回退（共 4 个镜像 + 1 个官网）
    # 离线默认清单（抓取失败时降级使用）
    components.append(
        Component(
            key="go",
            display_name="Go",
            env_var="GOROOT",
            path_subdir="bin",
            exec_name="go",
            version_args=["version"],
            versions=[_go_cv(v) for v in ("1.24.6", "1.22.5", "1.22.4", "1.21.12")],
        )
    )

    # ------------------ Gradle ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位官网回退（共 4 个镜像 + 1 个官网）
    # Gradle 解压后目录为 gradle-<version>/，内部含 bin/gradle(.bat)
    components.append(
        Component(
            key="gradle",
            display_name="Gradle",
            env_var="GRADLE_HOME",
            path_subdir="bin",
            exec_name="gradle",
            version_args=["-v"],
            versions=[_gradle_cv(v) for v in ("8.10", "8.9", "8.8", "7.6.4")],
        )
    )

    # ------------------ Bun ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位官网回退
    # 国内用 npmmirror + ghproxy 加速（R1.3 表外特殊源，详见 DEVELOPMENT.md R1.5 表）
    # Bun zip 解压后就是 bun 二进制（无子目录），path_subdir 用空字符串指向根目录
    components.append(
        Component(
            key="bun",
            display_name="Bun",
            env_var="BUN_HOME",
            path_subdir="",  # Bun 二进制直接在 install_dir 根目录，无 bin 子目录
            exec_name="bun",
            version_args=["--version"],
            versions=[_bun_cv(v) for v in ("1.4.2", "1.3.14", "1.2.16", "1.1.0")],
        )
    )

    # ------------------ Docker ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位官网回退（共 3 镜像 + 1 官网）
    # Docker static binaries：Linux/Mac 都有 tgz 解压即用，Windows 不支持（用 Docker Desktop）
    # 解压后根目录为 docker/，含 docker / dockerd 等二进制（无 bin 子目录）
    components.append(
        Component(
            key="docker",
            display_name="Docker",
            env_var=None,  # Docker 没有 DOCKER_HOME 概念，只走 PATH
            path_subdir="",  # 解压后二进制直接在根目录
            exec_name="docker",
            version_args=["--version"],
            # Windows 平台不支持 Docker static binary 自动下载，给用户友好引导
            unsupported_platform_hint=(
                "Docker 在 Windows 上需使用 Docker Desktop GUI 安装器，本工具暂不提供自动下载。"
                "请前往官网下载安装：https://www.docker.com/products/docker-desktop/"
            ),
            versions=[_docker_cv(v) for v in ("27.3.1", "27.3.0", "27.2.1", "26.1.4")],
        )
    )

    # ------------------ MongoDB ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位官网回退（共 4 镜像 + 1 官网）
    # MongoDB community 包：Windows zip + Linux tgz，Mac 不支持（用 brew）
    # 解压后根目录为 mongodb-<platform>-<arch>-<version>/，内部含 bin/ 子目录
    components.append(
        Component(
            key="mongodb",
            display_name="MongoDB",
            env_var="MONGODB_HOME",
            path_subdir="bin",
            exec_name="mongod",  # 用服务端二进制 mongod 检测版本（client shell 是 mongosh，社区版不含）
            version_args=["--version"],
            versions=[_mongodb_cv(v) for v in ("8.0.12", "8.0.0")],
        )
    )

    # ------------------ PostgreSQL ------------------
    # 按 R1 规则：URL 走国内镜像占位 + 末位 EDB 官网 fallback
    # 国内镜像未同步 binaries，会 404 自动切到 EDB 官网（符合 R1.7 改造指引）
    # Mac 不支持（用户用 brew install postgresql）
    # 解压后根目录为 pgsql/，内部含 bin/ 子目录
    components.append(
        Component(
            key="postgresql",
            display_name="PostgreSQL",
            env_var="PGHOME",
            path_subdir="bin",
            exec_name="psql",
            version_args=["--version"],
            versions=[_postgresql_cv(v) for v in ("17.6", "16.4", "15.8", "14.12")],
        )
    )

    # ------------------ kubectl ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位官网回退（共 3 镜像 + 1 官网）
    # kubectl 是 Kubernetes 官方 CLI 单二进制，三平台都发布
    # Windows 走 .exe 单二进制，Linux/Mac 走无扩展名单二进制（需 chmod +x）
    # 解压后二进制直接在根目录，path_subdir 用空字符串
    components.append(
        Component(
            key="kubectl",
            display_name="kubectl",
            env_var=None,  # kubectl 没有 KUBECTL_HOME 概念，只走 PATH
            path_subdir="",  # 单二进制直接在 install_dir 根目录
            exec_name="kubectl",
            version_args=["version", "--client"],
            versions=[_kubectl_cv(v) for v in ("1.31.0", "1.30.2", "1.29.5", "1.28.10")],
        )
    )

    # ------------------ Jenkins ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位官网回退（共 3 镜像 + 1 官网）
    # Jenkins LTS 提供 jenkins.war 跨平台单文件，下载后用 `java -jar jenkins.war` 启动
    # exec_name=None：jenkins.war 不是命令行可执行文件，detect 只能通过 PATH 找 jenkins 命令
    # 本工具只做下载+配置环境变量，用户需自行用 java -jar 启动
    components.append(
        Component(
            key="jenkins",
            display_name="Jenkins",
            env_var="JENKINS_HOME",
            path_subdir="",  # jenkins.war 直接在 install_dir 根目录
            exec_name=None,  # jenkins.war 不是可执行二进制，不通过 exec_name 检测
            version_args=["--version"],
            # 用户运行 Jenkins 需先装 JDK，这里通过 hint 提示
            unsupported_platform_hint=(
                "Jenkins 通过 jenkins.war 单文件分发，运行需要先安装 JDK（本工具已支持 JDK 自动装配）。"
                "下载完成后请用 `java -jar jenkins.war` 启动 Jenkins。"
            ),
            versions=[_jenkins_cv(v) for v in ("2.568.3", "2.555.3", "2.541.3")],
        )
    )

    # ------------------ RabbitMQ ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位 GitHub releases 回退（共 3 镜像 + 1 官网）
    # RabbitMQ 官方在 GitHub releases 提供 generic binary（Linux/Mac tar.xz）
    # Windows 需 Erlang 依赖，不提供自动下载，由 unsupported_platform_hint 引导
    # 解压后根目录为 rabbitmq_server-<v>/，内部含 sbin/ 子目录
    components.append(
        Component(
            key="rabbitmq",
            display_name="RabbitMQ",
            env_var="RABBITMQ_HOME",
            path_subdir="sbin",
            exec_name="rabbitmq-server",  # Linux/Mac 上是 rabbitmq-server 启动脚本
            version_args=["--version"],
            # rabbitmq-server 脚本会忽略参数直接启动 broker，探测阶段绝不执行
            version_probe=False,
            # Windows 不支持自动下载（依赖 Erlang，且 RabbitMQ Windows 是安装器模式）
            unsupported_platform_hint=(
                "RabbitMQ 在 Windows 上需先安装 Erlang/OTP 再用 RabbitMQ Windows 安装器，"
                "本工具暂不提供自动下载。请前往官网下载安装："
                "https://www.rabbitmq.com/install-windows.html"
            ),
            versions=[_rabbitmq_cv(v) for v in ("4.0.9", "3.13.7")],
        )
    )

    # ------------------ Apache Kafka ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位 Apache 官网回退（共 4 镜像 + 1 官网）
    # Kafka 是 Scala 项目，跨平台 tgz/zip，需 JDK 运行
    # 解压后根目录为 kafka_2.13-<v>/，内部含 bin/ 子目录
    # Windows 上的 .bat 包装器在 bin/windows/ 里，bin/ 下只有无扩展名的 shell 脚本
    components.append(
        Component(
            key="kafka",
            display_name="Apache Kafka",
            env_var="KAFKA_HOME",
            path_subdir="bin/windows" if CURRENT_OS == "Windows" else "bin",
            exec_name="kafka-server-start",  # Kafka 启动脚本（Linux/Mac 带 .sh 后缀）
            version_args=[],
            # 启动脚本：执行即拉起 broker，探测阶段只判定存在
            version_probe=False,
            versions=[_kafka_cv(v) for v in ("4.1.2", "3.9.1", "3.8.1")],
        )
    )

    # ------------------ Apache RocketMQ ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位 Apache 官网回退（共 4 镜像 + 1 官网）
    # RocketMQ 是 Java 项目，跨平台 zip，需 JDK 运行
    # 解压后根目录为 rocketmq-all-<v>-bin-release/，内部含 bin/ 子目录
    components.append(
        Component(
            key="rocketmq",
            display_name="Apache RocketMQ",
            env_var="ROCKETMQ_HOME",
            path_subdir="bin",
            exec_name="mqnamesrv",  # RocketMQ NameServer 启动脚本
            version_args=[],
            # 启动脚本：执行即拉起 NameServer，探测阶段只判定存在
            version_probe=False,
            versions=[_rocketmq_cv(v) for v in ("5.3.1", "5.3.0", "5.2.0", "5.1.4")],
        )
    )

    # ------------------ Apache Pulsar ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位 Apache 官网回退（共 4 镜像 + 1 官网）
    # Pulsar 是 Java 项目，跨平台 tar.gz，需 JDK 运行
    # 解压后根目录为 apache-pulsar-<v>-bin/，内部含 bin/ 子目录
    components.append(
        Component(
            key="pulsar",
            display_name="Apache Pulsar",
            env_var="PULSAR_HOME",
            path_subdir="bin",
            exec_name="pulsar",  # Pulsar 主命令（无 .sh 后缀）
            version_args=["--version"],
            versions=[_pulsar_cv(v) for v in ("3.3.9", "3.3.1")],
        )
    )

    # ------------------ ActiveMQ ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位 Apache 官网回退（共 4 镜像 + 1 官网）
    # ActiveMQ 是 Java 项目，跨平台 tar.gz/zip，需 JDK 运行
    # 解压后根目录为 activemq-apache-<v>-bin/ 或 apache-activemq-<v>-bin/，内部含 bin/ 子目录
    components.append(
        Component(
            key="activemq",
            display_name="ActiveMQ",
            env_var="ACTIVEMQ_HOME",
            path_subdir="bin",
            exec_name="activemq",  # ActiveMQ 主命令（无 .sh 后缀）
            version_args=["--version"],
            versions=[_activemq_cv(v) for v in ("6.3.2", "5.18.4")],
        )
    )

    # ------------------ Nacos ------------------
    # 按 R1 规则：URL 走国内 GitHub 加速优先 + 末位 GitHub releases 回退（共 2 加速 + 1 官网）
    # Nacos 是阿里开源服务发现组件，在 GitHub releases 发布，国内无官方镜像；
    # 解压后根目录为 nacos/，内部含 bin/ 子目录（startup.sh / startup.cmd）
    # exec_name 带扩展名（startup.cmd / startup.sh）：不带扩展名时 Windows 上会被
    # PATHEXT 匹配到同名异扩展的脚本，例如 Tomcat 的 startup.bat —— 探测就变成了启动 Tomcat。
    components.append(
        Component(
            key="nacos",
            display_name="Nacos",
            env_var="NACOS_HOME",
            path_subdir="bin",
            exec_name="startup.cmd" if CURRENT_OS == "Windows" else "startup.sh",
            version_args=["--version"],
            # startup 脚本一执行就会拉起 Nacos 服务，探测阶段绝不执行
            version_probe=False,
            versions=[_nacos_cv(v) for v in ("2.3.2", "2.3.0", "2.2.3", "2.1.2")],
        )
    )

    # ------------------ Seata ------------------
    # 按 R1 规则：URL 走国内 GitHub 加速优先 + 末位 GitHub releases 回退（共 2 加速 + 1 官网）
    # Seata 是 Apache 孵化项目（分布式事务），在 GitHub releases 发布，国内无官方镜像；
    # 解压后根目录为 apache-seata-<v>-incubating-bin/（2.x），内部含 bin/ 子目录
    # exec_name="seata-server"：对应 seata-server.sh / seata-server.bat
    components.append(
        Component(
            key="seata",
            display_name="Seata",
            env_var="SEATA_HOME",
            path_subdir="bin",
            exec_name="seata-server",  # Seata 启动脚本（seata-server.sh / seata-server.bat）
            version_args=["--version"],
            # seata-server 脚本一执行就会拉起 Seata 服务，探测阶段绝不执行
            version_probe=False,
            versions=[_seata_cv(v) for v in ("2.6.0", "2.2.0")],
        )
    )

    # ------------------ Elasticsearch ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位 elastic.co 官网回退（共 3 镜像 + 1 官网）
    # Elasticsearch 官方在 artifacts.elastic.co 发布跨平台归档包；
    # 国内镜像（清华/华为云/阿里云）路径可能与官网不完全一致，部分版本 404 会自动 fallback 到官网
    # 解压后根目录为 elasticsearch-<v>/，内部含 bin/ 子目录（elasticsearch / elasticsearch.bat）
    components.append(
        Component(
            key="elasticsearch",
            display_name="Elasticsearch",
            env_var="ES_HOME",
            path_subdir="bin",
            exec_name="elasticsearch",  # Elasticsearch 主命令（elasticsearch / elasticsearch.bat）
            version_args=["--version"],  # elasticsearch --version 输出版本信息
            versions=[_elasticsearch_cv(v) for v in ("9.2.3", "8.9.2", "8.15.0")],
        )
    )

    for comp in components:
        comp.category = COMPONENT_CATEGORY_OF[comp.key]        # 已有：漏登记直接 KeyError
        comp.multi_version = comp.key in MULTI_VERSION_KEYS    # 新增：不在白名单就是 False
    return components


# ---------------------------------------------------------------------------
# 下载线程
# ---------------------------------------------------------------------------
class DownloadWorker(QThread):
    """
    多源故障转移下载线程（详见 DEVELOPMENT.md R1.4）。

    按 urls 列表顺序依次尝试下载，第一个成功的写入目标文件；
    单 URL 失败自动切换到下一个，所有源失败才判定为彻底失败。
    """

    progress = Signal(int, int)  # (downloaded_bytes, total_bytes)
    log = Signal(str, str)  # (level, message)  level in {"info","warn","error","ok"}
    finished_ok = Signal(str)  # 保存的本地文件绝对路径
    finished_fail = Signal(str)  # 错误信息

    # 下载分片大小：64 KB，平衡内存与回调频率（避免魔法数字）
    _CHUNK_SIZE = 64 * 1024

    def __init__(self, urls: List[str], dest: Path,
                 parent: Optional[QObject] = None) -> None:
        """
        构造下载任务。

        入参 urls: List[str]     按 R1 优先级排序的 URL 列表（镜像在前，官网末位）
        入参 dest: Path         目标文件路径（先写 .part 临时文件，成功后 replace）
        入参 parent: QObject    Qt 父对象
        """
        super().__init__(parent)
        self.urls = list(urls)
        self.dest = dest
        self._cancel = False
        # 记录每个源的失败原因，最终汇总输出
        self._failures: List[str] = []

    def cancel(self) -> None:
        """取消下载；run() 内每个 chunk 写入前检查 _cancel 标志。"""
        self._cancel = True

    def run(self) -> None:  # noqa: D401
        """QThread 入口：按 urls 顺序尝试下载。"""
        ensure_dir(self.dest.parent)
        for idx, url in enumerate(self.urls, 1):
            if self._cancel:
                self._emit_cancel()
                return
            try:
                self.log.emit("info",
                    f"开始下载（第 {idx}/{len(self.urls)} 个源）：{url}")
                if self._try_download(url):
                    return  # 下载成功，直接返回
            except Exception as exc:
                # 中文日志：哪个源失败 + 错误原因 + 是否继续尝试下一个
                self._failures.append(f"{url} -> {exc}")
                if idx < len(self.urls):
                    self.log.emit("warn",
                        f"第 {idx} 个源下载失败：{exc}\n"
                        f"即将切换到下一个源：{self.urls[idx]}")
                else:
                    self.log.emit("error",
                        f"第 {idx} 个源（最后一个）下载失败：{exc}")
        # 所有源都失败 → 汇总中文日志 + 抛错
        summary = "所有镜像与官网地址均下载失败，已尝试：\n" + "\n".join(self._failures)
        self.log.emit("error", summary)
        self.finished_fail.emit("所有下载源均不可用")

    def _try_download(self, url: str) -> bool:
        """
        尝试从单个 URL 流式下载；下载完成且校验通过返回 True，否则 False 换下一个源。

        入参 url: str   待下载的 URL
        返回: bool      是否成功；响应体小于 DOWNLOAD_MIN_VALID_BYTES
                        或短于声明的 Content-Length 时判定该源失败，换下一个源
        """
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT,
                          allow_redirects=True, headers=HTTP_UA) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            tmp = self.dest.with_suffix(self.dest.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=self._CHUNK_SIZE):
                    if self._cancel:
                        self.log.emit("warn", "已取消下载。")
                        f.close()
                        tmp.unlink(missing_ok=True)
                        self._emit_cancel()
                        return False
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total)
            # 实测：镜像站会用「200 + 空体/软 404 页」冒充存在的文件，
            # 这种 0 字节的"成功"必须退回故障转移，否则解压阶段才炸。
            if downloaded < DOWNLOAD_MIN_VALID_BYTES or (total and downloaded < total):
                self.log.emit("warn",
                    f"第 {url} 只返回 {downloaded} 字节"
                    f"（声明 {total}），判定该源无效，换下一个源。")
                tmp.unlink(missing_ok=True)
                return False
            tmp.replace(self.dest)
        self.log.emit("ok",
            f"下载完成：{self.dest} ({human_size(self.dest.stat().st_size)})，"
            f"实际使用源：{url}")
        self.finished_ok.emit(str(self.dest))
        return True

    def _emit_cancel(self) -> None:
        """用户取消时统一发射 finished_fail 信号（沿用约定消息，便于上层判断不弹窗）。"""
        self.finished_fail.emit("用户取消")


# ---------------------------------------------------------------------------
# 环境变量处理
# ---------------------------------------------------------------------------
class EnvManager:
    """跨平台环境变量管理器。"""

    @staticmethod
    def get(name: str) -> Optional[str]:
        return os.environ.get(name)

    @staticmethod
    def is_valid_home(path: str, exec_name: str) -> bool:
        """判断 XXX_HOME 是否有效——检查 bin 目录下是否存在可执行文件。"""
        if not path:
            return False
        p = Path(path)
        bin_dir = p / "bin"
        exe = bin_dir / (exec_name + (".exe" if CURRENT_OS == "Windows" else ""))
        return exe.exists()

    @staticmethod
    def _broadcast_env_change() -> None:
        """异步广播 WM_SETTINGCHANGE("Environment")，让已运行的程序知道环境变了。

        取代原先的 setx：setx 会把超过 1024 字符的 PATH 直接截断，而且它自身要靠
        PATH 查找（PATH 一旦被写坏就彻底失效），而持久化本来就由写注册表完成。
        这里用 PostMessageW（异步）而不是 SendMessageTimeoutW（同步）：同步广播要等
        所有顶层窗口应答，只要有一个窗口不处理消息就会把调用方卡住。
        """
        if CURRENT_OS != "Windows":
            return
        try:
            import ctypes

            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x1A
            user32 = ctypes.windll.user32
            user32.PostMessageW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_wchar_p,
            ]
            user32.PostMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment")
        except Exception:
            pass  # 广播失败只影响其他进程的即时刷新，注册表已经写入

    @staticmethod
    def _write_registry_env(name: str, value: str) -> None:
        """写入 HKCU\\Environment 并广播，不改动当前进程的环境变量。"""
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
        ) as key:
            reg_type = winreg.REG_EXPAND_SZ if "%" in value else winreg.REG_SZ
            winreg.SetValueEx(key, name, 0, reg_type, value)
        EnvManager._broadcast_env_change()

    @staticmethod
    def set_windows_user_env(name: str, value: str) -> None:
        """写入 Windows 用户环境变量，并同步当前进程（Path 例外，见下）。"""
        try:
            EnvManager._write_registry_env(name, value)
            if name.lower() == "path":
                # 进程 PATH 是「机器 PATH + 用户 PATH」在登录时合并的结果，
                # 拿注册表里的用户段整体覆盖会丢掉 System32 等机器条目，
                # 之后任何外部命令都找不到，界面却仍显示"已配置"。
                # PATH 一律按单条目增删，见 append/remove_windows_path_entry。
                return
            # 同步当前进程的环境变量，避免后续 detect() 读到旧值
            # （os.environ 不会自动跟随注册表刷新，必须手动更新）
            os.environ[name] = value
        except Exception as exc:
            raise RuntimeError(f"写入 Windows 环境变量失败：{exc}")

    @staticmethod
    def _norm_path(raw: str) -> str:
        """归一化 PATH 条目用于比较：展开 %VAR%、去尾部分隔符（Windows 还忽略大小写）。"""
        expanded = os.path.expandvars(str(raw)).strip()
        if not expanded:
            return ""
        normed = os.path.normpath(expanded).rstrip("\\/")
        return normed.lower() if CURRENT_OS == "Windows" else normed

    @staticmethod
    def _same_path(a: str, b: str) -> bool:
        na = EnvManager._norm_path(a)
        return bool(na) and na == EnvManager._norm_path(b)

    @staticmethod
    def _under_root(entry: str, root: str) -> bool:
        ne = EnvManager._norm_path(entry)
        nr = EnvManager._norm_path(root)
        return bool(ne) and bool(nr) and (ne == nr or ne.startswith(nr + os.sep.lower()))

    @staticmethod
    def _read_windows_user_path() -> List[str]:
        """读取 HKCU 用户 PATH 的条目列表（原样保留，未展开变量）。"""
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
        ) as key:
            try:
                current, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current = ""
        return [p for p in str(current).split(";") if p]

    @staticmethod
    def _add_process_path_entry(entry: str) -> None:
        """把条目补进当前进程 PATH（不动其他条目）。"""
        parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
        if not any(EnvManager._same_path(p, entry) for p in parts):
            parts.append(entry)
            os.environ["PATH"] = os.pathsep.join(parts)

    @staticmethod
    def _filter_path_entries(pred) -> List[str]:
        """按谓词同时过滤注册表用户 PATH 与当前进程 PATH，返回被移除的条目。"""
        parts = EnvManager._read_windows_user_path()
        removed = [p for p in parts if pred(p)]
        if removed:
            EnvManager._write_registry_env(
                "Path", ";".join(p for p in parts if not pred(p))
            )
        proc = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
        kept = [p for p in proc if not pred(p)]
        if len(kept) != len(proc):
            os.environ["PATH"] = os.pathsep.join(kept)
        return removed

    @staticmethod
    def append_windows_path(entry: str) -> None:
        """把 entry 追加到 Windows 用户 PATH，并同步到当前进程 PATH。"""
        parts = EnvManager._read_windows_user_path()
        if not any(EnvManager._same_path(p, entry) for p in parts):
            parts.append(entry)
            EnvManager._write_registry_env("Path", ";".join(parts))
        EnvManager._add_process_path_entry(entry)

    @staticmethod
    def remove_windows_path_entry(entry: str) -> None:
        """从用户 PATH 与当前进程 PATH 移除指定条目（其他条目原样保留）。"""
        EnvManager._filter_path_entries(lambda p: EnvManager._same_path(p, entry))

    @staticmethod
    def remove_windows_path_entries_under(root: str) -> List[str]:
        """清理位于 root 目录内（含目录已不存在的历史残留）的 PATH 条目。"""
        return EnvManager._filter_path_entries(
            lambda p: EnvManager._under_root(p, root)
        )

    @staticmethod
    def _shell_rc_file() -> Path:
        """选择 macOS / Linux 上要写入的 shell 配置文件。"""
        home = Path.home()
        shell = os.environ.get("SHELL", "")
        if shell.endswith("zsh"):
            return home / ".zshrc"
        if shell.endswith("bash"):
            # macOS 上 bash 更常读 ~/.bash_profile
            return home / (".bash_profile" if CURRENT_OS == "Darwin" else ".bashrc")
        return home / ".profile"

    @staticmethod
    def set_unix_env(name: str, value: str) -> Path:
        """在 UNIX 系统上，把 export 语句写入 shell 配置文件；返回被修改的文件路径。"""
        rc = EnvManager._shell_rc_file()
        marker_begin = f"# >>> byte-tools:{name} >>>"
        marker_end = f"# <<< byte-tools:{name} <<<"
        new_block = f'{marker_begin}\nexport {name}="{value}"\n{marker_end}\n'

        text = rc.read_text(encoding="utf-8") if rc.exists() else ""
        if marker_begin in text and marker_end in text:
            pre, rest = text.split(marker_begin, 1)
            _, post = rest.split(marker_end, 1)
            new_text = pre + new_block + post
        else:
            sep = "" if text.endswith("\n") or text == "" else "\n"
            new_text = text + sep + "\n" + new_block
        rc.write_text(new_text, encoding="utf-8")
        # 同步当前进程的环境变量，避免后续 detect() 读到旧值
        # （shell 配置文件需要重开终端才 source，当前进程必须手动更新）
        os.environ[name] = value
        return rc

    @staticmethod
    def append_unix_path(entry: str) -> Path:
        """把 entry 追加到 PATH。"""
        rc = EnvManager._shell_rc_file()
        marker_begin = f"# >>> byte-tools:PATH:{entry} >>>"
        marker_end = f"# <<< byte-tools:PATH:{entry} <<<"
        line = f'{marker_begin}\nexport PATH="{entry}:$PATH"\n{marker_end}\n'
        text = rc.read_text(encoding="utf-8") if rc.exists() else ""
        if marker_begin in text:
            return rc
        sep = "" if text.endswith("\n") or text == "" else "\n"
        rc.write_text(text + sep + "\n" + line, encoding="utf-8")
        # 同步当前进程的 PATH（与 rc 里 export PATH="<entry>:$PATH" 一致，新条目置前）
        os.environ["PATH"] = f"{entry}:{os.environ.get('PATH', '')}"
        return rc

    # ------------------------------------------------------------------
    # 卸载相关：删除环境变量与 PATH 条目（与 set_/append_ 对称的逆操作）
    # ------------------------------------------------------------------
    @staticmethod
    def remove_windows_user_env(name: str) -> None:
        """
        删除 Windows 用户环境变量（如 XXX_HOME）。

        入参 name: str  环境变量名，如 "JAVA_HOME"
        """
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
            ) as key:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass  # 本来就不存在，幂等
            EnvManager._broadcast_env_change()
            # 同步删除当前进程的环境变量，避免后续 detect() 仍读到旧值
            os.environ.pop(name, None)
        except Exception as exc:
            raise RuntimeError(f"删除 Windows 环境变量 {name} 失败：{exc}")

    @staticmethod
    def remove_unix_env(name: str) -> Path:
        """
        从 shell 配置文件移除指定环境变量块（marker 之间的内容）。

        入参 name: str  环境变量名，如 "JAVA_HOME"
        返回: Path     被修改的 shell 配置文件路径
        """
        rc = EnvManager._shell_rc_file()
        if not rc.exists():
            return rc
        marker_begin = f"# >>> byte-tools:{name} >>>"
        marker_end = f"# <<< byte-tools:{name} <<<"
        text = rc.read_text(encoding="utf-8")
        # 正则匹配 marker_begin 到 marker_end（含）之间的所有内容（含尾随换行）
        # 使用非贪婪 .*? + DOTALL 跨行匹配；末尾 \n? 用于顺带清理换行
        pattern = _re.compile(
            _re.escape(marker_begin) + r".*?" + _re.escape(marker_end) + r"\n?",
            _re.DOTALL,
        )
        new_text = pattern.sub("", text)
        if new_text != text:
            rc.write_text(new_text, encoding="utf-8")
        # 同步删除当前进程的环境变量，避免后续 detect() 仍读到旧值
        os.environ.pop(name, None)
        return rc

    @staticmethod
    def remove_unix_path_entry(entry: str) -> Path:
        """
        从 shell 配置文件移除指定 PATH 条目块。

        入参 entry: str  要移除的 PATH 条目（绝对路径字符串）
        返回: Path     被修改的 shell 配置文件路径
        """
        rc = EnvManager._shell_rc_file()
        if not rc.exists():
            return rc
        marker_begin = f"# >>> byte-tools:PATH:{entry} >>>"
        marker_end = f"# <<< byte-tools:PATH:{entry} <<<"
        text = rc.read_text(encoding="utf-8")
        pattern = _re.compile(
            _re.escape(marker_begin) + r".*?" + _re.escape(marker_end) + r"\n?",
            _re.DOTALL,
        )
        new_text = pattern.sub("", text)
        if new_text != text:
            rc.write_text(new_text, encoding="utf-8")
        # 同步从当前进程的 PATH 移除该条目（按 : 切分后过滤）
        path_parts = [p for p in os.environ.get("PATH", "").split(":") if p and p != entry]
        os.environ["PATH"] = ":".join(path_parts)
        return rc

    @staticmethod
    def remove_unix_path_entries_under(root: str) -> List[str]:
        """
        移除 shell 配置文件中指向 root 目录内的 PATH 条目块（含目录已不存在的历史残留）。

        入参 root: str  组件安装根目录（如 ~/.env-tools/tomcat）
        返回: List[str] 被移除的条目
        """
        rc = EnvManager._shell_rc_file()
        removed: List[str] = []
        if rc.exists():
            text = rc.read_text(encoding="utf-8")
            pattern = _re.compile(
                r"# >>> byte-tools:PATH:(.*?) >>>.*?# <<< byte-tools:PATH:\1 <<<\n?",
                _re.DOTALL,
            )

            def _drop(match):
                entry = match.group(1)
                if EnvManager._under_root(entry, root):
                    removed.append(entry)
                    return ""
                return match.group(0)

            new_text = pattern.sub(_drop, text)
            if new_text != text:
                rc.write_text(new_text, encoding="utf-8")
        parts = [p for p in os.environ.get("PATH", "").split(":") if p]
        kept = [p for p in parts if not EnvManager._under_root(p, root)]
        if len(kept) != len(parts):
            os.environ["PATH"] = ":".join(kept)
        return removed


def _dead_tool_path_predicate():
    """返回「PATH 条目是否属于本工具且目录已不存在」的判定函数。"""
    root = str(CONFIG_DIR)

    def is_dead(entry: str) -> bool:
        if not EnvManager._under_root(entry, root):
            return False
        return not os.path.isdir(os.path.expandvars(entry))

    return is_dead


def find_dead_tool_path_entries() -> List[str]:
    """列出 PATH 里指向本工具安装目录、但目录已不存在的残留条目（不改动任何东西）。"""
    is_dead = _dead_tool_path_predicate()
    if CURRENT_OS == "Windows":
        return [p for p in EnvManager._read_windows_user_path() if is_dead(p)]
    rc = EnvManager._shell_rc_file()
    if not rc.exists():
        return []
    text = rc.read_text(encoding="utf-8")
    pattern = _re.compile(
        r"# >>> byte-tools:PATH:(.*?) >>>.*?# <<< byte-tools:PATH:\1 <<<",
        _re.DOTALL,
    )
    return [m.group(1) for m in pattern.finditer(text) if is_dead(m.group(1))]


def cleanup_dead_tool_path_entries() -> List[str]:
    """清理 PATH 中指向 CONFIG_DIR 之下、但目录已被删掉的残留条目。

    卸载只清理当次组件自己的目录；手工删过安装目录、或换过版本目录命名，
    都会留下既不存在、界面上又再也点不到的死条目（组件此时显示"未安装"，
    卸载按钮是灰的）。这里按整棵 .env-tools 子树扫一遍，只删目录已不存在的条目，
    有效条目与工具目录之外的一律不动。

    返回: List[str] 被移除的 PATH 条目
    """
    is_dead = _dead_tool_path_predicate()
    if CURRENT_OS == "Windows":
        return EnvManager._filter_path_entries(is_dead)

    removed: List[str] = []
    rc = EnvManager._shell_rc_file()
    if rc.exists():
        text = rc.read_text(encoding="utf-8")
        pattern = _re.compile(
            r"# >>> byte-tools:PATH:(.*?) >>>.*?# <<< byte-tools:PATH:\1 <<<\n?",
            _re.DOTALL,
        )

        def _drop(match):
            entry = match.group(1)
            if is_dead(entry):
                removed.append(entry)
                return ""
            return match.group(0)

        new_text = pattern.sub(_drop, text)
        if new_text != text:
            rc.write_text(new_text, encoding="utf-8")

    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    kept = [p for p in parts if not is_dead(p)]
    if len(kept) != len(parts):
        os.environ["PATH"] = os.pathsep.join(kept)
    return removed


# ---------------------------------------------------------------------------
# 归档解压
# ---------------------------------------------------------------------------
def extract_archive(archive: Path, extract_to: Path) -> Path:
    """解压归档，返回解压后（通常包含一个根目录）的根路径。

    入参 archive:    下载的归档文件路径
    入参 extract_to:  解压目标目录
    返回:            解压后根路径（单二进制 / .war 文件直接返回 extract_to 本身）

    支持：
      - .zip：标准 zip 归档（Python / Node / Bun / RocketMQ 等）
      - .tar.gz / .tgz：gzip 压缩 tar（JDK / Go / Docker / Kafka 等）
      - .tar.xz：xz 压缩 tar（Python 部分版本）
      - .exe / .war / 无扩展名：单二进制 / 单文件（kubectl.exe / kubectl / jenkins.war），
        直接拷贝到 extract_to 根目录；Linux/Mac 上无扩展名单二进制赋予 0o755 执行权限
    """
    ensure_dir(extract_to)
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(extract_to)
    elif name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(extract_to)
    elif name.endswith(".tar.xz"):
        with tarfile.open(archive, "r:xz") as tf:
            tf.extractall(extract_to)
    elif name.endswith(".exe") or name.endswith(".war") or "." not in archive.name:
        # 单二进制 / 单文件（kubectl.exe / kubectl / jenkins.war 等），
        # 直接拷贝到目标目录根目录；这类文件没有"解压后根目录"概念，
        # 直接返回 extract_to 本身作为 root
        target = extract_to / archive.name
        shutil.copy2(archive, target)
        # Linux/Mac 上无扩展名的单二进制（如 kubectl）赋予执行权限
        if not name.endswith((".exe", ".war")):
            target.chmod(0o755)
        return extract_to
    else:
        raise RuntimeError(f"未知的归档类型：{archive.name}")

    entries = [p for p in extract_to.iterdir() if p.is_dir()]
    if len(entries) == 1:
        return entries[0]
    return extract_to


# ---------------------------------------------------------------------------
# UI 组件：可搜索下拉框
# ---------------------------------------------------------------------------
class SearchableComboBox(QComboBox):
    """支持关键字过滤的下拉框。

    交互设计：
    - 点击输入框任意位置 → 弹出下拉列表（默认显示全部）
    - 输入关键字 → 实时过滤下拉列表中的项
    - 点击某项即选中（也可按回车 / 上下键选择）
    - 无效输入 → 失焦时回滚到上一次选中的值
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)  # 用户输入不添加到列表
        self.lineEdit().setPlaceholderText("点击选择或输入关键字…")

        # 自定义下拉箭头 —— 用 QLabel 显示 unicode 字符，避免 CSS border-hack 渲染问题
        # WA_TransparentForMouseEvents 使鼠标事件穿透到底层 QComboBox drop-down 区域，
        # 让 Qt 自己处理 toggle（点击展开、再次点击关闭），我们不干预。
        self._arrow_label = QLabel("▾", self)
        self._arrow_label.setObjectName("comboArrow")
        self._arrow_label.setAlignment(Qt.AlignCenter)
        self._arrow_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._arrow_label.setFixedWidth(28)

        # 在 lineEdit 上安装 event filter：点击文本区时也弹出下拉
        self.lineEdit().installEventFilter(self)

        # completer：让 QCompleter 也做 contains 匹配（无所谓，主要靠 view 过滤）
        completer = QCompleter(self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        completer.setModel(self.model())
        # 不使用 completer 的独立 popup，直接使用 combo 自带 view，避免视觉重叠
        self.setCompleter(None)

        # 记录当前有效选中项
        self._committed_text: str = ""

        # 连接信号
        self.currentIndexChanged.connect(self._on_index_changed)
        self.lineEdit().textEdited.connect(self._on_text_edited)
        self.lineEdit().editingFinished.connect(self._restore_if_invalid)

    # ------------------------------------------------------------------
    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        # 让箭头 label 始终贴在右侧
        w = self._arrow_label.width()
        self._arrow_label.setGeometry(self.width() - w - 2, 0, w, self.height())

    # ------------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:
        """点击输入框任何位置 → 弹出下拉。

        直接在 MousePress 阶段接管事件（return True），不让 QLineEdit 后续
        的 press/release 处理进入 QComboBox 内部的 toggle 逻辑 —— 那会导致
        我们刚弹出的 popup 被立即隐藏。
        """
        if obj is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            self.lineEdit().setFocus()
            if self.view().isVisible():
                self.hidePopup()
            else:
                self.showPopup()
            return True  # 吞掉事件，QLineEdit 不再处理
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        # 全选文本，方便直接输入替换
        self.lineEdit().selectAll()

    # ------------------------------------------------------------------
    def showPopup(self) -> None:  # noqa: D401
        """展开前先按当前输入过滤，空输入则展示全部。"""
        text = self.lineEdit().text().strip()
        if not text or text == self._committed_text:
            self._set_all_items_visible()
        else:
            self._filter_items(text)
        self._arrow_label.setText("▴")
        super().showPopup()

    # ------------------------------------------------------------------
    def hidePopup(self) -> None:  # noqa: D401
        self._arrow_label.setText("▾")
        super().hidePopup()

    # ------------------------------------------------------------------
    def _on_text_edited(self, text: str) -> None:
        """用户在输入框中键入时：实时过滤 + 展开下拉。"""
        # 展开下拉（若尚未展开）
        if not self.view().isVisible():
            super().showPopup()
        # 过滤
        keyword = text.strip()
        if not keyword:
            self._set_all_items_visible()
        else:
            self._filter_items(keyword)

    # ------------------------------------------------------------------
    def _filter_items(self, keyword: str) -> None:
        keyword = keyword.lower()
        view = self.view()
        first_visible = -1
        for i in range(self.count()):
            visible = keyword in self.itemText(i).lower()
            view.setRowHidden(i, not visible)
            if visible and first_visible < 0:
                first_visible = i
        # 把第一条匹配项高亮，方便回车直接选中
        if first_visible >= 0:
            view.setCurrentIndex(self.model().index(first_visible, 0))

    def _set_all_items_visible(self) -> None:
        view = self.view()
        for i in range(self.count()):
            view.setRowHidden(i, False)

    # ------------------------------------------------------------------
    def _on_index_changed(self, idx: int) -> None:
        if idx >= 0:
            self._committed_text = self.itemText(idx)

    def _restore_if_invalid(self) -> None:
        """失焦时若输入内容并不精确匹配某项，则回滚到上一次选中值。"""
        text = self.lineEdit().text().strip()
        for i in range(self.count()):
            if self.itemText(i).lower() == text.lower():
                self.setCurrentIndex(i)
                return
        if self._committed_text:
            self.lineEdit().setText(self._committed_text)

    # ------------------------------------------------------------------
    def repopulate(self, items: List[str], preferred: Optional[str] = None) -> None:
        """清空后重新加载列表；尽量保持之前选中值。"""
        prev = preferred or self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems(items)
        idx = self.findText(prev) if prev else -1
        self.setCurrentIndex(idx if idx >= 0 else 0)
        self.blockSignals(False)
        if self.count():
            self._committed_text = self.currentText()
        self._set_all_items_visible()


# ---------------------------------------------------------------------------
# UI 组件：卡片
# ---------------------------------------------------------------------------
class ComponentCard(QFrame):
    """展示一个组件的卡片。"""

    request_log = Signal(str, str)

    def __init__(self, component: Component, log_cb: Callable[[str, str], None], parent=None) -> None:
        super().__init__(parent)
        self.component = component
        self.log_cb = log_cb
        self.worker: Optional[DownloadWorker] = None
        self._extracted_path: Optional[Path] = None
        # 「已配置」标签的异步版本号回填状态
        self._status_where = ""
        self._status_version = ""
        self._status_shows_configured = False
        self._version_worker: Optional["VersionProbeWorker"] = None

        self.setObjectName("card")
        self.setFrameShape(QFrame.NoFrame)

        # 阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 40))
        self.setGraphicsEffect(shadow)

        self._build_ui()
        self._detect_status()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # 顶部：名称 & 状态
        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel(self.component.display_name)
        title.setObjectName("cardTitle")
        title.setFont(QFont("", 14, QFont.Bold))
        top.addWidget(title)

        self.status_label = QLabel("检测中…")
        self.status_label.setObjectName("statusLabel")
        top.addWidget(self.status_label)
        top.addStretch(1)
        root.addLayout(top)

        # 中部：版本选择 + 按钮
        mid = QHBoxLayout()
        mid.setSpacing(10)
        version_label = QLabel("版本")
        version_label.setObjectName("fieldLabel")
        version_label.setFixedWidth(36)
        mid.addWidget(version_label)

        self.version_combo = SearchableComboBox()
        self.version_combo.setObjectName("versionCombo")
        self.version_combo.setCursor(QCursor(Qt.PointingHandCursor))
        self._reload_combo_items()
        # 固定宽度，避免抢占按钮空间
        self.version_combo.setFixedWidth(220)
        self.version_combo.setFixedHeight(34)
        self.version_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        mid.addWidget(self.version_combo)

        mid.addSpacing(8)

        self.btn_install = QPushButton("下载并安装")
        self.btn_install.setObjectName("primaryBtn")
        self.btn_install.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_install.setFixedHeight(34)
        self.btn_install.clicked.connect(self.on_install_clicked)
        mid.addWidget(self.btn_install)

        self.btn_configure = QPushButton("配置环境变量")
        self.btn_configure.setObjectName("secondaryBtn")
        self.btn_configure.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_configure.setFixedHeight(34)
        self.btn_configure.clicked.connect(self.on_configure_clicked)
        mid.addWidget(self.btn_configure)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("dangerBtn")
        self.btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)  # 默认隐藏；开始下载时才显示
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        mid.addWidget(self.btn_cancel)

        self.btn_uninstall = QPushButton("卸载")
        self.btn_uninstall.setObjectName("dangerBtn")
        self.btn_uninstall.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_uninstall.setFixedHeight(34)
        # 默认禁用，待 _detect_status 检测到已安装或有本地下载时才启用
        self.btn_uninstall.setEnabled(False)
        self.btn_uninstall.setToolTip("删除已安装的版本、清理 XXX_HOME 与 PATH")
        self.btn_uninstall.clicked.connect(self.on_uninstall_clicked)
        mid.addWidget(self.btn_uninstall)

        mid.addStretch(1)  # 右侧留空，避免下拉框被拉伸
        root.addLayout(mid)

        # 底部：进度条
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        self.progress.setValue(0)
        root.addWidget(self.progress)

    # ------------------------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        self.log_cb(level, f"[{self.component.display_name}] {msg}")

    # ------------------------------------------------------------------
    def _render_status_label(self) -> None:
        text = f"✓ 已配置（{self._status_where}）"
        if self._status_version:
            text += f" · {self._status_version}"
        elif self.component.version_probe:
            text += " · 版本检测中…"
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            "color:#2e7d32;font-weight:600;padding:2px 8px;"
            "background:#e8f5e9;border-radius:10px;"
        )

    def _schedule_version_probe(self, exe_path: str) -> None:
        """把「执行组件命令取版本号」推迟到事件循环空闲时，且放到后台线程。

        version_probe=False 的启动脚本型组件（Nacos/Kafka/RocketMQ/Seata/RabbitMQ）
        在这里直接跳过——一执行就会把中间件服务拉起来。
        """
        if not (exe_path and self.component.version_probe and self.component.version_args):
            return
        QTimer.singleShot(0, lambda: self._start_version_probe(exe_path))

    def _start_version_probe(self, exe_path: str) -> None:
        worker = VersionProbeWorker(exe_path, list(self.component.version_args), self)
        worker.done.connect(lambda text, w=worker: self._on_version_probed(text, w))
        worker.finished.connect(worker.deleteLater)
        self._version_worker = worker
        worker.start()

    def _on_version_probed(self, text: str, worker: Optional["VersionProbeWorker"] = None) -> None:
        # 回包可能晚到：状态已不「已配置」或已被更新一轮探测取代时丢弃
        if not self._status_shows_configured:
            return
        if worker is not None and worker is not self._version_worker:
            return
        self._status_version = text or "未知版本"
        self._render_status_label()

    # ------------------------------------------------------------------
    def _detect_status(self) -> None:
        """检测该组件当前是否已安装、已配置。

        - 若系统 PATH 或 XXX_HOME 已能找到可执行文件，则视为「已配置」，禁用
          「仅配置环境变量」按钮，避免重复写入。
        - 若本地已解压但未配置，则允许点击「仅配置环境变量」。
        - 若未安装，两个按钮均可用。

        本方法在窗口构建卡片时就会被调用，因此绝不同步执行组件命令：detect 只判定
        存在（probe_version=False），版本号交给 VersionProbeWorker 异步回填。
        """
        result = self.component.detect(probe_version=False)
        self._status_shows_configured = bool(result.installed)
        if result.installed:
            where = result.source or "系统"
            self._status_where = where
            self._status_version = ""
            self._render_status_label()
            # 已可用 —— 禁用「仅配置环境变量」按钮
            self.btn_configure.setEnabled(False)
            self.btn_configure.setToolTip(
                f"系统已能检测到 {self.component.display_name}"
                f"（{result.exe_path or where}），无需再次配置。"
            )
            # 已配置状态下允许卸载（仅能清理由本工具写入的 XXX_HOME/PATH marker）
            self.btn_uninstall.setEnabled(True)
            self.btn_uninstall.setToolTip(
                "卸载将删除本地安装目录，并清理由本工具写入的环境变量"
            )
            self._schedule_version_probe(result.exe_path)
            return

        # 尝试查找本地已解压目录
        install_root = CONFIG_DIR / self.component.key
        if install_root.exists() and any(
            p for p in install_root.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name != "downloads"
        ):
            self.status_label.setText("● 已下载，未配置")
            self.status_label.setStyleSheet(
                "color:#ef6c00;font-weight:600;padding:2px 8px;"
                "background:#fff3e0;border-radius:10px;"
            )
            self.btn_configure.setEnabled(True)
            self.btn_configure.setToolTip("将已下载的版本写入 XXX_HOME 与 PATH")
            # 已下载但未配置：允许卸载（删除本地解压目录）
            self.btn_uninstall.setEnabled(True)
            self.btn_uninstall.setToolTip("删除已下载但尚未配置的安装目录")
            return

        self.status_label.setText("○ 未安装")
        self.status_label.setStyleSheet(
            "color:#c62828;font-weight:600;padding:2px 8px;"
            "background:#ffebee;border-radius:10px;"
        )
        self.btn_configure.setEnabled(True)
        self.btn_configure.setToolTip("将已下载的版本写入 XXX_HOME 与 PATH")
        # 未安装：禁用卸载
        self.btn_uninstall.setEnabled(False)
        self.btn_uninstall.setToolTip("当前组件未安装，无需卸载")

    # ------------------------------------------------------------------
    def _display_label(self, cv: ComponentVersion) -> str:
        return getattr(cv, "display_label", None) or cv.version

    def _reload_combo_items(self, preferred: Optional[str] = None) -> None:
        """把 self.component.versions 灌进下拉框。"""
        labels = [self._display_label(v) for v in self.component.versions]
        # 若首次调用（combo 里还没内容），走普通 addItems 路径
        if self.version_combo.count() == 0:
            self.version_combo.blockSignals(True)
            self.version_combo.addItems(labels)
            self.version_combo.setCurrentIndex(0)
            self.version_combo.blockSignals(False)
            self.version_combo._committed_text = self.version_combo.currentText()
            return
        self.version_combo.repopulate(labels, preferred=preferred)

    def set_versions(self, versions: List[ComponentVersion]) -> None:
        """外部（抓取线程）用新版本列表替换现有列表。"""
        if not versions:
            return
        prev_ver = self._current_version().version if self.component.versions else None
        self.component.versions = versions
        preferred_label = None
        if prev_ver:
            for cv in versions:
                if cv.version == prev_ver:
                    preferred_label = self._display_label(cv)
                    break
        self._reload_combo_items(preferred=preferred_label)
        self._log("ok", f"已从官网获取 {len(versions)} 个版本")

    # ------------------------------------------------------------------
    def _current_version(self) -> ComponentVersion:
        """按显示 label 反查真实版本，兼容 SearchableComboBox 的可编辑文本。"""
        text = self.version_combo.currentText().strip()
        for cv in self.component.versions:
            if self._display_label(cv) == text or cv.version == text:
                return cv
        idx = max(0, self.version_combo.currentIndex())
        return self.component.versions[min(idx, len(self.component.versions) - 1)]

    # ------------------------------------------------------------------
    def on_install_clicked(self) -> None:
        cv = self._current_version()
        # 多源故障转移：urls_for_current() 返回按 R1 优先级排序的 URL 列表
        urls = cv.urls_for_current()
        if not urls:
            # 优先使用组件配置的 unsupported_platform_hint（如 Docker 引导去 Docker Desktop 官网）
            # 未配置时回退到通用提示
            hint = self.component.unsupported_platform_hint
            if hint:
                self._log("error", hint)
            else:
                self._log("error", f"当前系统 {CURRENT_OS} 无可用下载地址。")
            return

        # 决定下载文件后缀
        if self.component.installer_mode:
            # 从 archive_map 取扩展名（exe / sh），其次从 URL 推断
            ext = cv.archive_map.get(CURRENT_OS, "")
            if not ext:
                first_url = urls[0] if urls else ""
                if first_url.endswith(".exe"):
                    ext = "exe"
                elif first_url.endswith(".sh"):
                    ext = "sh"
                else:
                    ext = "bin"
            suffix = f".{ext}"
        else:
            archive_ext = cv.archive_for_current()
            # 按 archive_ext 计算下载文件后缀：
            #   zip      → .zip
            #   tar.gz   → .tar.gz
            #   exe      → .exe        (单二进制 Windows，如 kubectl.exe)
            #   war      → .war        (单文件，如 jenkins.war)
            #   "" / bin → 空后缀       (单二进制 Linux/Mac，如 kubectl)
            #   其它     → .<archive_ext>
            if archive_ext == "zip":
                suffix = ".zip"
            elif archive_ext in ("tar.gz", "tgz"):
                suffix = ".tar.gz"
            elif archive_ext == "exe":
                suffix = ".exe"
            elif archive_ext == "war":
                suffix = ".war"
            elif archive_ext in ("", "bin"):
                suffix = ""
            else:
                suffix = "." + archive_ext

        download_dir = CONFIG_DIR / self.component.key / "downloads"
        ensure_dir(download_dir)
        dest = download_dir / f"{self.component.key}-{cv.version}{suffix}"

        self.progress.setValue(0)
        self.btn_install.setEnabled(False)
        self.btn_configure.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)

        self.worker = DownloadWorker(urls, dest)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._log)
        self.worker.finished_ok.connect(lambda p: self._on_download_ok(Path(p), cv))
        self.worker.finished_fail.connect(self._on_download_fail)
        self.worker.start()

    # ------------------------------------------------------------------
    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            self.progress.setValue(int(downloaded * 100 / total))
            self.progress.setFormat(f"{human_size(downloaded)} / {human_size(total)}")
        else:
            # 未知总长度
            self.progress.setRange(0, 0)
            self.progress.setFormat(f"{human_size(downloaded)}")

    # ------------------------------------------------------------------
    def _on_download_ok(self, path: Path, cv: ComponentVersion) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)

        try:
            target_root = CONFIG_DIR / self.component.key
            ensure_dir(target_root)
            final = self.component.install_dir(cv.version)

            if self.component.installer_mode:
                # 安装器模式：静默执行安装
                self._log("info", "开始运行安装器（静默安装）…")
                if final.exists():
                    shutil.rmtree(final, ignore_errors=True)
                self._run_installer(path, final)
                self._log("ok", f"安装完成：{final}")
            else:
                self._log("info", "开始解压…")
                # 解压到临时目录
                tmp_dir = target_root / f".extract-{cv.version}"
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                ensure_dir(tmp_dir)
                root = extract_archive(path, tmp_dir)

                # 单二进制 / 单文件模式：把下载下来的文件重命名为 exec_name + 平台扩展名
                # 例：kubectl-1.28.4.exe → kubectl.exe；kubectl-1.28.4 → kubectl；jenkins-2.426.war → jenkins.war
                # 这样后续 detect() 才能在 install_dir 里通过 exec_path_in_home 找到文件
                archive_ext = cv.archive_for_current()
                is_single_binary = archive_ext in ("exe", "war", "", "bin")
                if is_single_binary and self.component.exec_name:
                    if archive_ext == "war":
                        # Jenkins 的 jenkins.war
                        target_name = (
                            self.component.exec_name
                            if self.component.exec_name.endswith(".war")
                            else self.component.exec_name + ".war"
                        )
                    elif archive_ext == "exe" or CURRENT_OS == "Windows":
                        target_name = self.component.exec_name + ".exe"
                    else:
                        # Linux/Mac 无扩展名单二进制
                        target_name = self.component.exec_name
                    # 在 root 目录下查找下载下来的单文件并重命名
                    for f in root.iterdir():
                        if f.is_file():
                            new_path = root / target_name
                            if new_path != f and not new_path.exists():
                                f.rename(new_path)
                            break

                if final.exists():
                    shutil.rmtree(final, ignore_errors=True)
                shutil.move(str(root), str(final))
                shutil.rmtree(tmp_dir, ignore_errors=True)
                self._log("ok", f"解压完成：{final}")

            self._extracted_path = final
            # 自动尝试配置环境变量
            self._configure_env(final)
        except Exception as exc:
            self._log("error", f"安装/配置失败：{exc}\n{traceback.format_exc()}")
        finally:
            self.btn_install.setEnabled(True)
            self.btn_configure.setEnabled(True)
            # _detect_status 会根据探测结果再决定 btn_configure 是否禁用
            self._detect_status()

    # ------------------------------------------------------------------
    def _run_installer(self, installer_path: Path, target_dir: Path) -> None:
        """静默运行安装器（用于 Miniconda 之类）。"""
        comp = self.component
        args = list(comp.installer_args.get(CURRENT_OS, []))
        ensure_dir(target_dir.parent)

        if CURRENT_OS == "Windows":
            # Windows Miniconda: 参数末尾 /D=path 不允许带引号
            cmd = [str(installer_path)] + args + [f"/D={target_dir}"]
            self._log("info", f"运行：{' '.join(cmd)}")
            proc = subprocess.run(cmd, check=False)
        else:
            # macOS / Linux: bash installer.sh -b -f -p <path>
            os.chmod(installer_path, 0o755)
            cmd = ["bash", str(installer_path)] + args + [str(target_dir)]
            self._log("info", f"运行：{' '.join(cmd)}")
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if proc.stdout:
                self._log("info", proc.stdout.strip()[:500])
            if proc.stderr:
                self._log("warn", proc.stderr.strip()[:500])

        if proc.returncode != 0:
            raise RuntimeError(f"安装器返回非零退出码：{proc.returncode}")

    # ------------------------------------------------------------------
    def _on_download_fail(self, msg: str) -> None:
        self.btn_install.setEnabled(True)
        self.btn_configure.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        if msg and msg != "用户取消":
            QMessageBox.warning(self, "下载失败", f"{self.component.display_name} 下载失败：\n{msg}")

    # ------------------------------------------------------------------
    def on_cancel_clicked(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()

    # ------------------------------------------------------------------
    def on_uninstall_clicked(self) -> None:
        """
        点击卸载按钮：弹二次确认 → 调 component.uninstall(version) → 输出日志 → 刷新状态。

        卸载是不可逆操作，所以先弹 QMessageBox.question 确认；用户点 Yes 才执行。
        """
        cv = self._current_version()
        # 二次确认：卸载会删除本地目录、清理环境变量与 PATH，不可逆
        reply = QMessageBox.question(
            self,
            "确认卸载",
            f"确定要卸载 {self.component.display_name} {cv.version} 吗？\n\n"
            f"将执行以下操作：\n"
            f"  · 删除安装目录\n"
            f"  · 清理环境变量 {self.component.env_var or '（无）'}\n"
            f"  · 清理 PATH 中属于本组件安装目录的条目\n\n"
            f"（若所选版本与实际安装版本不一致，会以实际装着的目录为准）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._log("info", f"已取消卸载 {self.component.display_name} {cv.version}")
            return
        try:
            self._log("info", f"开始卸载 {self.component.display_name} {cv.version}")
            # 调用 Component.uninstall 执行实际卸载，返回中文摘要
            summary = self.component.uninstall(cv.version)
            self._log("ok", f"卸载完成：{summary}")
            # 卸载后重新检测状态，刷新状态胶囊与按钮启用状态
            self._detect_status()
        except Exception as exc:
            self._log("error", f"卸载失败：{exc}")

    # ------------------------------------------------------------------
    def on_configure_clicked(self) -> None:
        """仅配置环境变量：从本地已存在的安装目录中选择最新一个。"""
        install_root = CONFIG_DIR / self.component.key
        if not install_root.exists():
            self._log("warn", "尚未下载，请先执行“下载并安装”。")
            return
        candidates = [p for p in install_root.iterdir() if p.is_dir() and not p.name.startswith(".")
                      and p.name != "downloads"]
        if not candidates:
            self._log("warn", "未找到已解压的安装目录。")
            return
        candidates.sort()
        self._configure_env(candidates[-1])
        self._detect_status()

    # ------------------------------------------------------------------
    def _configure_env(self, install_path: Path) -> None:
        """根据组件类型写入 XXX_HOME 与 PATH。"""
        try:
            comp = self.component
            bin_dir = install_path / comp.path_subdir
            if comp.env_var:
                if CURRENT_OS == "Windows":
                    EnvManager.set_windows_user_env(comp.env_var, str(install_path))
                    EnvManager.append_windows_path(str(bin_dir))
                else:
                    rc = EnvManager.set_unix_env(comp.env_var, str(install_path))
                    EnvManager.append_unix_path(str(bin_dir))
                    self._log("info", f"已写入 {rc}")
                self._log("ok", f"设置 {comp.env_var}={install_path}")
                self._log("ok", f"追加 PATH：{bin_dir}")
            else:
                if CURRENT_OS == "Windows":
                    EnvManager.append_windows_path(str(bin_dir))
                else:
                    rc = EnvManager.append_unix_path(str(bin_dir))
                    self._log("info", f"已写入 {rc}")
                self._log("ok", f"追加 PATH：{bin_dir}")

            if CURRENT_OS != "Windows":
                self._log("warn", "请打开新的终端或执行 `source ~/.zshrc` 让环境变量生效。")
        except Exception as exc:
            self._log("error", f"环境变量配置失败：{exc}")


# ---------------------------------------------------------------------------
# 捐赠弹窗（不出现在文档中；仅代码内实现）
# ---------------------------------------------------------------------------
class DonateDialog(QDialog):
    """支持作者：微信 / 支付宝 / QQ，各渠道展示对应二维码。"""

    # 每个渠道对应的品牌色、二维码文件名
    CHANNELS = [
        ("微信", "#07C160", "wechat.png"),
        ("支付宝", "#1677FF", "alipay.png"),
        # ("QQ", "#EB1923", "qq.png"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("支持作者")
        self.setMinimumSize(460, 460)
        self.setObjectName("donateDialog")
        self._assets_dir = Path(__file__).parent / "assets"
        self._build_ui()
        # 默认展示第一个渠道
        self._show_qr(*self.CHANNELS[0])

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(14)

        tip = QLabel("如果本工具对你有所帮助，欢迎请作者一杯咖啡 ☕")
        tip.setAlignment(Qt.AlignCenter)
        tip.setStyleSheet("font-size:14px;color:#444;")
        v.addWidget(tip)

        # 渠道切换按钮行
        row = QHBoxLayout()
        row.setSpacing(14)
        self._buttons: List[QPushButton] = []
        for name, color, filename in self.CHANNELS:
            btn = QPushButton(name)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setCheckable(True)
            btn.setStyleSheet(
                f"QPushButton{{background:{color};color:white;border:none;border-radius:8px;padding:10px 20px;font-weight:600;}}"
                f"QPushButton:checked{{background:{color};border:2px solid #333;}}"
                f"QPushButton:hover{{background:{color};}}"
            )
            btn.clicked.connect(lambda _=False, n=name, c=color, f=filename: self._show_qr(n, c, f))
            row.addWidget(btn)
            self._buttons.append(btn)
        v.addLayout(row)

        # 当前渠道标签
        self._channel_label = QLabel("")
        self._channel_label.setAlignment(Qt.AlignCenter)
        self._channel_label.setStyleSheet("font-size:15px;font-weight:600;color:#333;")
        v.addWidget(self._channel_label)

        # 二维码展示区
        self.qr_view = QLabel("请选择下方渠道")
        self.qr_view.setAlignment(Qt.AlignCenter)
        self.qr_view.setMinimumHeight(260)
        self.qr_view.setStyleSheet(
            "background:#fafafa;border:1px solid #e0e0e0;border-radius:10px;color:#888;padding:10px;"
        )
        v.addWidget(self.qr_view, stretch=1)

        # 底部备注
        note = QLabel("扫码打赏，感谢您的支持！")
        note.setAlignment(Qt.AlignCenter)
        note.setStyleSheet("font-size:12px;color:#999;")
        v.addWidget(note)

    def _show_qr(self, channel: str, color: str = "", filename: str = "") -> None:
        # 更新按钮 checked 状态
        for btn in self._buttons:
            btn.setChecked(btn.text() == channel)

        self._channel_label.setText(f"【{channel}】收款码")
        if color:
            self._channel_label.setStyleSheet(
                f"font-size:15px;font-weight:600;color:{color};"
            )

        if not filename:
            # 兼容旧调用：仅传 channel 时按 CHANNELS 查
            for n, c, f in self.CHANNELS:
                if n == channel:
                    filename = f
                    break

        # 尝试加载二维码图片
        qr_path = self._assets_dir / filename
        if qr_path.exists():
            pixmap = QPixmap(str(qr_path))
            if not pixmap.isNull():
                # 按 view 宽度等比缩放
                scaled = pixmap.scaled(
                    self.qr_view.width() - 20,
                    self.qr_view.height() - 20,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.qr_view.setPixmap(scaled)
                return

        # 加载失败：显示占位文字
        self.qr_view.clear()
        self.qr_view.setText(
            f"未找到二维码文件：\n\n{qr_path}\n\n请将 {filename} 放入 assets 目录后重启。"
        )


# ---------------------------------------------------------------------------
# 主窗口（无边框自定义标题栏）
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        # 设置窗口图标（任务栏、标题栏、Alt+Tab 切换显示）
        # 使用项目内置的 assets/byte-tools.png，缺失时不报错
        _icon_path = Path(__file__).parent / "assets" / "byte-tools.png"
        if _icon_path.exists():
            self.setWindowIcon(QIcon(str(_icon_path)))
        self.resize(1000, 680)
        self.setMinimumSize(880, 560)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self.components = build_components()
        self._drag_pos: Optional[QPoint] = None
        self._fetch_workers: List[VersionFetchWorker] = []
        self._fetch_pending: int = 0
        # 关窗标志：置位后不再派发抓取，也不再把抓取结果写回界面
        self._closing: bool = False

        self._build_ui()
        self._apply_qss()
        self._load_settings()
        self._start_fetch_versions()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ------- 自定义标题栏 -------
        self.title_bar = QFrame()
        self.title_bar.setObjectName("titleBar")
        self.title_bar.setFixedHeight(48)
        tb = QHBoxLayout(self.title_bar)
        tb.setContentsMargins(14, 0, 8, 0)
        tb.setSpacing(6)

        title_label = QLabel(APP_NAME)
        title_label.setObjectName("titleText")
        title_label.setFont(QFont("", 12, QFont.Bold))
        tb.addWidget(title_label)
        tb.addStretch(1)

        # GitHub 图标
        self.btn_github = QPushButton("★ GitHub")
        self.btn_github.setObjectName("iconBtn")
        self.btn_github.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_github.setToolTip("获取最新版本")
        self.btn_github.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL))
        )
        tb.addWidget(self.btn_github)

        # 刷新版本列表按钮
        self.btn_refresh = QPushButton("⟳ 刷新版本")
        self.btn_refresh.setObjectName("iconBtn")
        self.btn_refresh.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_refresh.setToolTip("重新从官网抓取所有组件的可用版本列表")
        self.btn_refresh.clicked.connect(self._start_fetch_versions)
        tb.addWidget(self.btn_refresh)

        # 清理残留 PATH 按钮
        self.btn_cleanup_path = QPushButton("🧹 清理残留 PATH")
        self.btn_cleanup_path.setObjectName("iconBtn")
        self.btn_cleanup_path.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_cleanup_path.setToolTip(
            "删除 PATH 中指向本工具安装目录、但目录已经不存在的死条目\n"
            "（手工删过安装目录时用到；其他程序的 PATH 条目不会改动）"
        )
        self.btn_cleanup_path.clicked.connect(self._on_cleanup_path_clicked)
        tb.addWidget(self.btn_cleanup_path)

        # 捐赠图标（不在 README 中提及）
        self.btn_donate = QPushButton("♥")
        self.btn_donate.setObjectName("donateBtn")
        self.btn_donate.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_donate.setToolTip("支持作者")
        self.btn_donate.clicked.connect(self._on_donate_clicked)
        tb.addWidget(self.btn_donate)

        # 窗口控制按钮
        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("ctrlBtn")
        self.btn_min.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_min.clicked.connect(self.showMinimized)
        tb.addWidget(self.btn_min)

        self.btn_max = QPushButton("▢")
        self.btn_max.setObjectName("ctrlBtn")
        self.btn_max.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_max.clicked.connect(self._toggle_max)
        tb.addWidget(self.btn_max)

        self.btn_close = QPushButton("×")
        self.btn_close.setObjectName("closeBtn")
        self.btn_close.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_close.clicked.connect(self.close)
        tb.addWidget(self.btn_close)

        outer.addWidget(self.title_bar)

        # ------- 组件搜索条（在 Tab 之上，切 Tab 不会丢输入框） -------
        self.search_bar = QFrame()
        self.search_bar.setObjectName("searchBar")
        sb = QHBoxLayout(self.search_bar)
        sb.setContentsMargins(18, 12, 18, 10)
        sb.setSpacing(10)

        # 胶囊外壳：放大镜与输入框同属一个白色圆角块，聚焦时整条高亮，
        # 而不是只给输入框描一圈边（原先那种细边框小方框显得零碎）。
        self.search_shell = QFrame()
        self.search_shell.setObjectName("searchShell")
        self.search_shell.setProperty("focused", "false")
        shell = QHBoxLayout(self.search_shell)
        shell.setContentsMargins(12, 0, 8, 0)
        shell.setSpacing(8)

        self.search_icon = QLabel()
        self.search_icon.setObjectName("searchIcon")
        self.search_icon.setPixmap(self._make_search_icon().pixmap(16, 16))
        shell.addWidget(self.search_icon)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("compSearch")
        self.search_box.setPlaceholderText("搜索组件名称…")
        # 内置清空按钮在不同平台上图标差异大、颜色偏淡，这里自绘一个统一风格的 ×
        self.search_box.setClearButtonEnabled(False)
        self._clear_action = self.search_box.addAction(
            self._make_clear_icon(), QLineEdit.TrailingPosition
        )
        self._clear_action.setToolTip("清空搜索")
        self._clear_action.setVisible(False)
        self._clear_action.triggered.connect(self.search_box.clear)
        self.search_box.textChanged.connect(self._sync_clear_action)
        self.search_box.textChanged.connect(self._apply_search)
        # 焦点变化要联动外壳高亮，QSS 的 :focus 影响不到父级，用事件过滤器转发
        self.search_box.installEventFilter(self)
        # 占位文字默认偏深，调浅一点更接近现代输入框的观感
        _pal = self.search_box.palette()
        _pal.setColor(QPalette.PlaceholderText, QColor("#9aabbd"))
        self.search_box.setPalette(_pal)
        shell.addWidget(self.search_box, 1)

        sb.addWidget(self.search_shell)

        self.search_hint = QLabel("")
        self.search_hint.setObjectName("searchHint")
        sb.addWidget(self.search_hint)
        sb.addStretch(1)
        outer.addWidget(self.search_bar)

        # ------- 主体：卡片列表 + 日志区 -------
        body = QSplitter(Qt.Vertical)
        body.setObjectName("bodySplitter")

        # 卡片区域：按 COMPONENT_CATEGORIES 分三个 Tab，每个 Tab 一条独立滚动栏。
        # self.cards 仍是全量平铺列表——刷新版本 / 存取配置 / 关窗等探测都靠它遍历。
        self.cards: List[ComponentCard] = []
        self._tab_cards: List[List[ComponentCard]] = []
        self._tab_layouts: list = []
        self.tabs = QTabWidget()
        self.tabs.setObjectName("compTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)   # 顶部横向，跨平台显式锁定
        for cat_name, comps in group_components(self.components).items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setObjectName("cardsScroll")
            cards_wrap = QWidget()
            cards_wrap.setObjectName("cardsWrap")
            cards_layout = QVBoxLayout(cards_wrap)
            cards_layout.setContentsMargins(18, 18, 18, 18)
            cards_layout.setSpacing(14)
            tab_cards: List[ComponentCard] = []
            for comp in comps:
                card = ComponentCard(comp, self._append_log)
                cards_layout.addWidget(card)
                self.cards.append(card)
                tab_cards.append(card)
            cards_layout.addStretch(1)
            scroll.setWidget(cards_wrap)
            self.tabs.addTab(scroll, f"{cat_name}（{len(comps)}）")
            self._tab_cards.append(tab_cards)
            self._tab_layouts.append(cards_layout)

        # 统一搜索结果面板：搜索时收起三个 Tab，把所有命中的组件按分类归并到
        # 同一个滚动列表里（带分类小标题），一眼看全、不用切页——这就是「全组件搜索」。
        self.results_area = QScrollArea()
        self.results_area.setObjectName("resultsArea")
        self.results_area.setWidgetResizable(True)
        self.results_content = QWidget()
        self.results_content.setObjectName("resultsContent")
        self.results_layout = QVBoxLayout(self.results_content)
        self.results_layout.setContentsMargins(18, 18, 18, 18)
        self.results_layout.setSpacing(6)
        self.results_area.setWidget(self.results_content)

        # 浏览模式用 Tab，搜索模式用统一结果面板，二者互斥地放进一个栈
        self.top_stack = QStackedWidget()
        self.top_stack.setObjectName("topStack")
        self.top_stack.addWidget(self.tabs)           # index 0：浏览
        self.top_stack.addWidget(self.results_area)   # index 1：搜索结果
        body.addWidget(self.top_stack)

        # 日志
        log_wrap = QWidget()
        log_wrap.setObjectName("logWrap")
        log_layout = QVBoxLayout(log_wrap)
        log_layout.setContentsMargins(18, 6, 18, 18)
        log_layout.setSpacing(6)
        log_title = QLabel("运行日志")
        log_title.setStyleSheet("font-weight:600;color:#333;")
        log_layout.addWidget(log_title)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("logView")
        log_layout.addWidget(self.log_view)
        body.addWidget(log_wrap)

        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        outer.addWidget(body, stretch=1)

        # 底部状态条（含组件总数，方便用户一眼掌握支持范围）
        self.status_bar = QLabel(
            f"系统：{CURRENT_OS} ({MACHINE})   工作目录：{CONFIG_DIR}   "
            f"组件总数：{len(self.components)} 个"
        )
        self.status_bar.setObjectName("statusBar")
        outer.addWidget(self.status_bar)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    @staticmethod
    def _make_search_icon(color: str = "#8ba0b6", size: int = 16) -> QIcon:
        """
        用 QPainter 现画一个放大镜图标，省得为一张 16px 小图额外引入资源文件。

        入参 color: str   线条颜色，默认与占位文字同一灰蓝色系
              size:  int  逻辑边长（像素）；内部按 2 倍分辨率绘制，高分屏不糊

        返回: QIcon  可直接 pixmap() 给 QLabel，或 addAction() 给 QLineEdit
        """
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(2, 2, 9, 9)          # 镜片
        painter.drawLine(11, 11, 14, 14)         # 手柄
        painter.end()
        return QIcon(pm)

    @staticmethod
    def _make_clear_icon(color: str = "#9aabbd", size: int = 16) -> QIcon:
        """
        用 QPainter 画一个统一风格的「×」，作为搜索框的清空按钮图标。

        入参 color: str  线条颜色（默认与放大镜、占位文字同色系）
              size:  int 逻辑边长（像素），同样按 2 倍分辨率绘制

        返回: QIcon
        """
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(5, 5, 11, 11)
        painter.drawLine(11, 5, 5, 11)
        painter.end()
        return QIcon(pm)

    def _sync_clear_action(self, text: str) -> None:
        """有输入才显示清空按钮，空串时藏起来，免得占着位置显得多余。"""
        action = getattr(self, "_clear_action", None)
        if action is not None:
            action.setVisible(bool(text))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802  Qt 规定的驼峰签名
        """
        把搜索框的焦点变化转发给外壳，做出「整条胶囊一起高亮」的效果。

        说明: QSS 的 :focus 只能命中聚焦控件自身，管不到父级 QFrame，
              所以这里手动改外壳的 focused 属性并触发重新应用样式。
        """
        try:
            if obj is getattr(self, "search_box", None):
                if event.type() == QEvent.FocusIn:
                    self._set_search_focus(True)
                elif event.type() == QEvent.FocusOut:
                    self._set_search_focus(False)
        except RuntimeError:
            # 关窗销毁阶段子控件的 C++ 对象可能已被回收，此时忽略即可
            pass
        return super().eventFilter(obj, event)

    def _set_search_focus(self, focused: bool) -> None:
        """设置搜索外壳的聚焦态样式（改属性后需 unpolish/polish 才会重绘）。"""
        shell = getattr(self, "search_shell", None)
        if shell is None:
            return
        shell.setProperty("focused", "true" if focused else "false")
        shell.style().unpolish(shell)
        shell.style().polish(shell)
        # 放大镜跟着边框一起变色，聚焦反馈更完整
        icon = getattr(self, "search_icon", None)
        if icon is not None:
            color = "#4a7fd0" if focused else "#8ba0b6"
            icon.setPixmap(self._make_search_icon(color).pixmap(16, 16))

    def _apply_search(self, query: str) -> None:
        """
        全组件搜索：命中跨所有分类，结果归并到统一面板。

        入参 query: str  搜索框当前内容；空串（或全空白）表示退出搜索、恢复三个 Tab。

        行为:
        - 退出搜索: 卡片全部回到各自 Tab、恢复可见，显示三个分类 Tab，Tab 标题恢复「总数」。
        - 进入搜索: 收起 Tab，把所有命中的组件按分类归并到统一结果列表（带分类小标题），
          一眼看全，不用切页。过滤只动卡片可见性/归属，**不动 self.cards 平铺列表**——
          刷新版本 / 存配置 / 关窗等探测逻辑都遍历那个列表，隐藏不能让它缺项。
        """
        q = query.strip()
        # 先无条件复位到「浏览基线」，保证重复搜索、清空再搜都从干净状态出发
        self._restore_browse()

        if not q:
            self.search_hint.setText("")
            self.search_hint.setProperty("empty", "false")
            self.search_hint.style().unpolish(self.search_hint)
            self.search_hint.style().polish(self.search_hint)
            return

        self._build_unified(q)

    def _restore_browse(self) -> None:
        """把全部卡片放回各自 Tab 并恢复可见，切回浏览模式。"""
        # 从统一结果面板卸下所有卡片
        for card in self.cards:
            if self.results_layout.indexOf(card) != -1:
                self.results_layout.removeWidget(card)
        # 切回 Tab 浏览
        self.top_stack.setCurrentIndex(0)
        # 把每个 Tab 的卡片按原顺序插回（layout 末尾有一个 stretch，插到它前面）
        for i, layout in enumerate(self._tab_layouts):
            for j, card in enumerate(self._tab_cards[i]):
                if layout.indexOf(card) == -1:
                    layout.insertWidget(j, card)
                card.setVisible(True)
        # Tab 标题恢复成「分类（总数）」
        for idx, cat_name in enumerate(COMPONENT_CATEGORIES):
            self.tabs.setTabText(idx, f"{cat_name}（{len(self._tab_cards[idx])}）")
        # 清掉结果面板里残留的分类小标题
        self._clear_results_layout()

    def _build_unified(self, q: str) -> None:
        """把命中的组件按分类归并进统一结果列表（带分类小标题）。"""
        self._clear_results_layout()
        cur_cat = None
        hits = 0
        # self.cards 已是分类顺序，便于在切换分类时插入分类小标题
        for card in self.cards:
            comp = card.component
            if component_matches(comp, q):
                cat = comp.category
                if cat != cur_cat:
                    header = QLabel(cat)
                    header.setObjectName("resultCatHeader")
                    self.results_layout.addWidget(header)
                    cur_cat = cat
                self._reparent(card, self.results_layout, self.results_layout.count())
                card.setVisible(True)
                hits += 1
            else:
                card.setVisible(False)
        self.results_layout.addStretch(1)
        self.top_stack.setCurrentIndex(1)

        self.search_hint.setText(f"匹配 {hits} / {len(self.cards)} 个组件")
        # 一个都没命中时换个警示色，免得用户以为列表加载坏了
        self.search_hint.setProperty("empty", "true" if hits == 0 else "false")
        self.search_hint.style().unpolish(self.search_hint)
        self.search_hint.style().polish(self.search_hint)

    def _reparent(self, card, target_layout, index) -> None:
        """把卡片从任何已知 layout 摘下，再插入目标 layout 的指定位置。"""
        for li in (self.results_layout, *self._tab_layouts):
            if li.indexOf(card) != -1:
                li.removeWidget(card)
        target_layout.insertWidget(index, card)

    def _clear_results_layout(self) -> None:
        """清空统一结果面板里的所有条目（分类小标题等临时控件）。"""
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                if w in self.cards:
                    w.setParent(None)        # 卡片稍后由 _restore_browse 归位
                else:
                    w.deleteLater()          # 分类小标题等临时标签
                continue
            sp = item.spacerItem()
            if sp is not None:
                del sp

    def _apply_qss(self) -> None:
        """应用 QSS 样式表。"""
        self.setStyleSheet(
            """
            #centralRoot {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #eef2f7, stop:1 #dee5ee);
            }
            #titleBar {
                background: #2c3e50;
                color: white;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            #titleText { color: white; padding-left: 4px; }
            #iconBtn, #donateBtn, #ctrlBtn, #closeBtn {
                background: transparent;
                color: white;
                border: none;
                padding: 6px 12px;
                font-size: 14px;
                border-radius: 6px;
            }
            #iconBtn:hover, #ctrlBtn:hover, #donateBtn:hover {
                background: rgba(255,255,255,0.15);
            }
            #donateBtn { color: #ff8181; font-size: 18px; }
            #closeBtn:hover { background: #e74c3c; }

            #searchBar { background: transparent; }

            /* 搜索框：外壳统一承载放大镜与输入框，聚焦时整条胶囊高亮，
               比原先「细边框小方框」更有整体感，也和卡片/下拉框的圆角语言一致 */
            #searchShell {
                background: #ffffff;
                border: 1px solid #d5dfea;
                border-radius: 10px;
                min-width: 340px;
                max-width: 460px;
            }
            #searchShell:hover { border: 1px solid #b9c9dc; }
            #searchShell[focused="true"] { border: 1px solid #4a7fd0; }
            #searchIcon { background: transparent; border: none; }
            #compSearch {
                background: transparent;
                border: none;
                padding: 8px 0;
                font-size: 13px;
                color: #17253b;
            }
            #compSearch:focus { border: none; }
            #compSearch QToolButton { background: transparent; border: none; }
            #searchHint { color: #66788c; font-size: 12px; padding-left: 2px; }
            #searchHint[empty="true"] { color: #c0392b; }

            #compTabs { background: transparent; border: none; }

            #compTabs::pane { border: none; background: transparent; }
            #compTabs > QTabBar::tab {
                background: #cfd8e3;
                color: #33465c;
                padding: 7px 18px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: 600;
            }
            #compTabs > QTabBar::tab:selected {
                background: #ffffff;
                color: #17253b;
            }
            #cardsScroll { border: none; background: transparent; }
            #cardsWrap { background: transparent; }

            #topStack { background: transparent; }
            #resultsArea { border: none; background: transparent; }
            #resultsContent { background: transparent; }
            #resultCatHeader {
                font-weight: 600;
                color: #33465c;
                font-size: 13px;
                padding: 8px 2px 2px 10px;
                margin-top: 4px;
                border-left: 3px solid #4a7fd0;
            }
            #card {
                background: white;
                border-radius: 12px;
                border: 1px solid #e6ebf1;
            }
            #cardTitle { color: #263238; }
            #statusLabel { font-size: 12px; }
            #fieldLabel { color:#546e7a; font-size:13px; }

            /* ----------------- 下拉框 ----------------- */
            QComboBox {
                padding: 0 34px 0 12px;
                border: 1px solid #cfd8dc;
                border-radius: 8px;
                background: white;
                color: #263238;
                font-size: 13px;
                min-height: 32px;
                selection-background-color: #1976d2;
            }
            QComboBox:hover  { border-color: #90caf9; }
            QComboBox:focus  { border-color: #1976d2; }
            QComboBox:on     { border-color: #1976d2; }
            QComboBox QLineEdit {
                border: none;
                background: transparent;
                padding: 0;
                margin: 0;
                color: #263238;
                font-size: 13px;
                selection-background-color: #1976d2;
                selection-color: white;
            }
            QComboBox QLineEdit:focus { outline: none; }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 30px;
                border: none;
                background: transparent;
            }
            QComboBox::down-arrow {
                image: none;
                width: 0;
                height: 0;
            }
            #comboArrow {
                color: #78909c;
                font-size: 14px;
                background: transparent;
                border: none;
                padding-right: 6px;
            }
            QComboBox:hover #comboArrow { color: #1976d2; }
            QComboBox:focus #comboArrow { color: #1976d2; }
            QComboBox QAbstractItemView {
                border: 1px solid #cfd8dc;
                border-radius: 8px;
                background: white;
                padding: 6px;
                outline: 0;
                selection-background-color: #1976d2;
                selection-color: white;
            }
            QComboBox QAbstractItemView::item {
                padding: 8px 14px;
                border-radius: 6px;
                min-height: 24px;
                color: #263238;
            }
            QComboBox QAbstractItemView::item:hover {
                background: #e3f2fd;
                color: #0d47a1;
            }
            QComboBox QAbstractItemView::item:selected {
                background: #1976d2;
                color: white;
            }

            QPushButton#primaryBtn {
                background: #1976d2;
                color: white;
                border: none;
                padding: 6px 18px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton#primaryBtn:hover { background: #1e88e5; }
            QPushButton#primaryBtn:pressed { background: #1565c0; }
            QPushButton#primaryBtn:disabled { background: #b0bec5; color:#eceff1; }

            QPushButton#secondaryBtn {
                background: #ffffff;
                color: #1976d2;
                border: 1px solid #1976d2;
                padding: 6px 16px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton#secondaryBtn:hover { background: #e3f2fd; }
            QPushButton#secondaryBtn:pressed { background: #bbdefb; }
            QPushButton#secondaryBtn:disabled {
                color: #b0bec5;
                border-color: #cfd8dc;
                background: #f5f7fa;
            }

            QPushButton#dangerBtn {
                background: #ffffff;
                color: #c62828;
                border: 1px solid #c62828;
                padding: 6px 16px;
                border-radius: 8px;
                font-size: 13px;
            }
            QPushButton#dangerBtn:hover { background: #ffebee; }
            QPushButton#dangerBtn:disabled { color:#e0a4a4; border-color:#e0a4a4; }

            QProgressBar {
                background: #eceff1;
                border: none;
                border-radius: 6px;
                height: 14px;
                text-align: center;
                color: #263238;
                font-size: 11px;
            }
            QProgressBar::chunk {
                border-radius: 6px;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #26c6da, stop:1 #1976d2);
            }

            #logWrap { background: transparent; }
            #logView {
                background: #1e1e2e;
                color: #dcdcdc;
                border-radius: 8px;
                padding: 6px;
                font-family: Menlo, Consolas, "Courier New", monospace;
                font-size: 12px;
            }
            #statusBar {
                background: #eceff1;
                color: #455a64;
                padding: 6px 14px;
                font-size: 12px;
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }

            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 4px 0;
            }
            QScrollBar::handle:vertical {
                background: #b0bec5;
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #90a4ae; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

            QToolTip {
                background: #37474f;
                color: white;
                border: 1px solid #263238;
                padding: 6px 10px;
                border-radius: 6px;
            }
            """
        )

    # ------------------------------------------------------------------
    # 无边框窗口拖动
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.title_bar.underMouse():
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self.title_bar.underMouse():
            self._toggle_max()

    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.btn_max.setText("▢")
        else:
            self.showMaximized()
            self.btn_max.setText("❐")

    # ------------------------------------------------------------------
    def _on_cleanup_path_clicked(self) -> None:
        """扫描并清理 PATH 中指向本工具目录、但已不存在的残留条目。"""
        dead = find_dead_tool_path_entries()
        if not dead:
            QMessageBox.information(
                self,
                "清理残留 PATH",
                f"PATH 中没有发现本工具（{CONFIG_DIR}）留下的失效条目。",
            )
            return
        detail = "\n".join(f"· {p}" for p in dead[:12])
        if len(dead) > 12:
            detail += f"\n… 等共 {len(dead)} 条"
        reply = QMessageBox.question(
            self,
            "清理残留 PATH",
            f"PATH 中有 {len(dead)} 条指向已不存在的目录：\n\n{detail}\n\n"
            "只删除这些失效条目，其他程序的 PATH 不受影响。确认清理？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._append_log("info", "已取消清理残留 PATH。")
            return
        removed = cleanup_dead_tool_path_entries()
        if removed:
            self._append_log(
                "ok", f"已清理 {len(removed)} 条残留 PATH：" + "、".join(removed)
            )
        else:
            self._append_log("warn", "未删除任何条目（可能目录刚被重建）。")
        for card in self.cards:
            card._detect_status()

    # ------------------------------------------------------------------
    def _start_fetch_versions(self) -> None:
        """从各官网并发拉取版本列表。可反复调用（刷新）。"""
        if self._closing:
            return
        # 若有 worker 仍在运行、或已排期但尚未启动（错峰未触发），等它跑完再触发新一轮。
        # 注意：错峰未启动的线程 isRunning()=False 但 isFinished()=False，必须用 isFinished() 判定，
        # 否则会被下面 cleanup 提前 deleteLater 导致定时器回调访问已释放对象。
        busy = [w for w in self._fetch_workers if w.isRunning() or not w.isFinished()]
        if busy:
            self._append_log("warn", f"仍有 {len(busy)} 个抓取任务在进行，请稍候…")
            return
        # 清理已完成的 worker
        for w in self._fetch_workers:
            w.deleteLater()
        self._fetch_workers.clear()

        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText("⟳ 抓取中…")
        self._fetch_pending = 0
        self._append_log("info", "正在从各官网获取最新版本列表…")
        for i, card in enumerate(self.cards):
            fetcher = FETCHERS.get(card.component.key)
            if not fetcher:
                continue
            w = VersionFetchWorker(card.component.key, fetcher, self)
            w.done.connect(self._on_versions_fetched)
            self._fetch_workers.append(w)
            self._fetch_pending += 1
            # 错峰启动：避免 26 路线程同时打 api.github.com 触发未认证限额（60 次/小时/IP）。
            # 间隔 150ms，最晚一个约在 3.9s 后启动；单发失败由 _github_api_json 退避重试兜底。
            # 走 _launch_fetch_worker 而不是裸 w.start：关窗后残留的定时器不能再起新线程，
            # 否则线程会在窗口析构时还在跑，直接把进程 abort 掉。
            QTimer.singleShot(i * 150, lambda w=w: self._launch_fetch_worker(w))

    def _launch_fetch_worker(self, worker: VersionFetchWorker) -> None:
        """错峰定时器到点后的启动入口；关窗途中则放弃启动。"""
        if self._closing or worker.isRunning() or worker.isFinished():
            return
        worker.start()

    def _on_versions_fetched(self, key: str, versions) -> None:
        if self._closing:
            return
        card = next((c for c in self.cards if c.component.key == key), None)
        if card:
            if versions is None:
                self._append_log("warn", f"[{card.component.display_name}] 官网版本获取失败，使用内置默认列表")
            else:
                card.set_versions(versions)
        self._fetch_pending -= 1
        if self._fetch_pending <= 0 and hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("⟳ 刷新版本")
            self._append_log("info", "版本列表获取完成。")

    # ------------------------------------------------------------------
    def _on_donate_clicked(self) -> None:
        DonateDialog(self).exec()

    # ------------------------------------------------------------------
    def _append_log(self, level: str, msg: str) -> None:
        color = {
            "info": "#dcdcdc",
            "ok": "#7CFC7C",
            "warn": "#FFB347",
            "error": "#FF6B6B",
        }.get(level, "#dcdcdc")
        self.log_view.append(f'<span style="color:{color};">{msg}</span>')

    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        """加载上次选择的版本。"""
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            selections = data.get("selections", {})
            for card in self.cards:
                v = selections.get(card.component.key)
                if v:
                    idx = card.version_combo.findText(v)
                    if idx >= 0:
                        card.version_combo.setCurrentIndex(idx)
        except Exception:
            pass

    def _save_settings(self) -> None:
        try:
            ensure_dir(CONFIG_DIR)
            data = {
                "selections": {
                    card.component.key: card.version_combo.currentText()
                    for card in self.cards
                }
            }
            CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        # 先立旗：不再派发抓取、不再回写界面，并让在跑的抓取线程尽快从重试边界返回。
        # QThread 在运行时被析构会直接 abort 进程（Windows 退出码 0xC0000409），
        # 而版本抓取是启动即触发的，所以关窗必须等这些线程收尾。
        self._closing = True
        FETCH_ABORT.set()
        self._save_settings()
        # 版本探测线程还在跑就退出会触发 "QThread destroyed while running"，
        # 探测本身有 4 秒超时，这里等它收尾再关窗。
        for card in self.cards:
            worker = card._version_worker
            if worker is not None and worker.isRunning():
                worker.wait(5000)
        # 抓取线程：_get / _github_api_json 已能协作取消，剩下的是一个在途请求的超时
        # （最长 DOWNLOAD_PROBE_TIMEOUT*2 = 10s），给 FETCH_EXIT_WAIT 秒总预算，逐个等剩余时间。
        import time as _time
        deadline = _time.monotonic() + FETCH_EXIT_WAIT
        for w in self._fetch_workers:
            if not w.isRunning():
                continue
            remain = max(0.0, deadline - _time.monotonic())
            w.wait(int(remain * 1000))
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    ensure_dir(CONFIG_DIR)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
