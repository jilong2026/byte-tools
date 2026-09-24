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
    start-windows.bat         # Windows 一键启动（自动建虚拟环境+装依赖）
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
from typing import Callable, Dict, List, Optional

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
    # 否则回退到 url_map 的单 URL 模式（向后兼容现有 8 个组件）。
    url_list_map: Dict[str, List[str]] = field(default_factory=dict)

    def url_for_current(self) -> Optional[str]:
        """单 URL 模式：返回当前系统的下载 URL。"""
        return self.url_map.get(CURRENT_OS)

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
    versions: List[ComponentVersion] = field(default_factory=list)
    # 安装器模式：某些组件（如 Miniconda）下载的是安装器而非归档，需要静默执行安装器
    installer_mode: bool = False
    # 安装器静默安装参数：按 CURRENT_OS 键取。执行时会附加安装目标目录参数
    installer_args: Dict[str, List[str]] = field(default_factory=dict)
    # 当某平台不支持自动下载时，输出给用户的友好提示文本。
    # 例：Docker 在 Windows 上无 static binary，需引导用户去 Docker Desktop 官网下载。
    # 不配置该字段时，回退到通用提示"当前系统 X 无可用下载地址"。
    unsupported_platform_hint: Optional[str] = None

    def install_dir(self, version: str) -> Path:
        """返回该版本组件的解压安装目录。"""
        return CONFIG_DIR / self.key / f"{self.key}-{version}"

    def exec_path_in_home(self, home: str) -> Optional[Path]:
        """在给定 XXX_HOME 目录下查找可执行文件。"""
        if not self.exec_name:
            return None
        exe = self.exec_name + (".exe" if CURRENT_OS == "Windows" else "")
        # 依次尝试 path_subdir、bin、Scripts、根目录
        candidates_dir = [self.path_subdir, "bin", "Scripts", "condabin", ""]
        for sub in candidates_dir:
            cand = Path(home) / sub / exe if sub else Path(home) / exe
            if cand.exists():
                return cand
        return None

    def detect(self) -> "DetectResult":
        """探测该组件是否已在系统中可用。"""
        if not self.exec_name:
            return DetectResult(False)

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
                        version_text=_probe_version(str(exe), self.version_args),
                    )

        # 2) 通过 PATH 中的可执行文件
        exe_name_final = self.exec_name + (".exe" if CURRENT_OS == "Windows" else "")
        which = shutil.which(exe_name_final) or shutil.which(self.exec_name)
        if which:
            return DetectResult(
                installed=True,
                source="PATH",
                exe_path=which,
                version_text=_probe_version(which, self.version_args),
            )

        return DetectResult(False)

    def uninstall(self, version: str) -> str:
        """
        卸载指定版本：删除安装目录、移除 XXX_HOME 环境变量、从 PATH 移除 bin 目录。

        入参 version: str  要卸载的版本号字符串（与 install_dir 计算一致）
        返回: str           卸载结果摘要（中文，多步骤用中文分号分隔）

        说明:
          - 仅当 XXX_HOME 指向被卸载版本目录时才删除 XXX_HOME，避免误删用户其他配置；
          - PATH 条目按 install_dir/path_subdir 精确匹配删除；
          - 安装器模式（如 Miniconda）跳过目录删除，仅清理环境变量与 PATH。
        """
        import shutil
        summary_parts: List[str] = []
        install_path = self.install_dir(version)

        # 1. 删除安装目录（安装器模式跳过，由安装器自行管理位置）
        if self.installer_mode:
            summary_parts.append("安装器模式，跳过安装目录删除（如需彻底清理请用对应卸载工具）")
        else:
            if install_path.exists() and install_path.is_dir():
                try:
                    shutil.rmtree(install_path)
                    summary_parts.append(f"已删除安装目录：{install_path}")
                except Exception as exc:
                    summary_parts.append(f"删除安装目录失败：{exc}")
            else:
                summary_parts.append(f"安装目录不存在：{install_path}")

        # 2. 删除 XXX_HOME 环境变量（仅当它指向被卸载的目录，避免误删用户其他配置）
        if self.env_var:
            current_home = EnvManager.get(self.env_var)
            if current_home and Path(current_home) == install_path:
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

        # 3. 从 PATH 中移除 bin 目录（按 install_dir/path_subdir 精确匹配）
        if self.path_subdir:
            bin_path = str(install_path / self.path_subdir)
            try:
                if CURRENT_OS == "Windows":
                    EnvManager.remove_windows_path_entry(bin_path)
                else:
                    EnvManager.remove_unix_path_entry(bin_path)
                summary_parts.append(f"已从 PATH 移除：{bin_path}")
            except Exception as exc:
                summary_parts.append(f"从 PATH 移除 {bin_path} 失败：{exc}")

        return "；".join(summary_parts) if summary_parts else "无需卸载"


@dataclass
class DetectResult:
    """系统级探测结果。"""

    installed: bool
    source: str = ""  # "JAVA_HOME" / "PATH" / ""
    home: str = ""
    exe_path: str = ""
    version_text: str = ""


def _probe_version(exe: str, args: List[str]) -> str:
    """调用可执行文件抓取版本号；失败返回空串。"""
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        line = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
        return line[:80]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# R1 镜像源与故障转移参数（详见 DEVELOPMENT.md 规则 R1）
# ---------------------------------------------------------------------------
# 国内镜像源基址表（按稳定性与速度综合排序）：(标识, 基址)
MIRROR_BASES: List[tuple] = [
    ("huaweicloud", "https://repo.huaweicloud.com"),
    ("tuna",        "https://mirrors.tuna.tsinghua.edu.cn"),
    ("aliyun",      "https://mirrors.aliyun.com"),
    ("nju",         "https://mirrors.nju.edu.cn"),
    ("ustc",        "https://mirrors.ustc.edu.cn"),
    ("sjtug",       "https://mirrors.sjtug.org"),
]

# 故障转移参数（避免魔法数字）
DOWNLOAD_PROBE_TIMEOUT = 5     # 单 URL 探测超时（秒）
DOWNLOAD_TIMEOUT = 30         # 单 URL 下载连接超时（秒）
DOWNLOAD_RETRY_PER_URL = 2    # 单 URL 内重试次数


def _get_first_working(urls: List[str], timeout: int = 10) -> requests.Response:
    """
    按 urls 顺序依次尝试 GET，第一个成功的返回；全部失败抛异常。

    入参 urls: List[str]  待尝试的 URL 列表，按优先级排序（镜像在前，官网末位）
    入参 timeout: int     单 URL 超时秒数
    """
    last_exc: Optional[Exception] = None
    for idx, url in enumerate(urls, 1):
        try:
            return _get(url, timeout=timeout)
        except Exception as exc:
            last_exc = exc
            continue
    assert last_exc is not None
    raise RuntimeError(
        f"所有源均不可用，已尝试 {len(urls)} 个 URL"
    ) from last_exc


def _adoptium_jdk_url(version: str) -> Dict[str, str]:
    """
    Adoptium Temurin JDK 下载地址生成。

    注意：Adoptium 的实际最新构建 URL 会带 build 号，这里使用 latest release API 拼接的
    通用镜像地址；如果链接失效可自行替换为其他镜像（如华为云、清华镜像）。
    """
    # 使用 Adoptium API 提供的“latest binary redirect”地址：一次性重定向到最新构建
    base = "https://api.adoptium.net/v3/binary/latest"
    # 参数：feature_version/release_type/os/arch/image_type/jvm_impl/heap_size/vendor
    win = f"{base}/{version}/ga/windows/x64/jdk/hotspot/normal/eclipse"
    mac_arch = "aarch64" if IS_ARM else "x64"
    mac = f"{base}/{version}/ga/mac/{mac_arch}/jdk/hotspot/normal/eclipse"
    linux_arch = "aarch64" if IS_ARM else "x64"
    linux = f"{base}/{version}/ga/linux/{linux_arch}/jdk/hotspot/normal/eclipse"
    return {"Windows": win, "Darwin": mac, "Linux": linux}


# ---------------------------------------------------------------------------
# URL 构造器（模块级，便于抓取器与初始默认列表复用）
# ---------------------------------------------------------------------------
_STD_ARCHIVE: Dict[str, str] = {"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"}


def _cv(version: str, url_map: Dict[str, str]) -> ComponentVersion:
    return ComponentVersion(version=version, url_map=url_map, archive_map=dict(_STD_ARCHIVE))


def _maven_urls(v: str) -> Dict[str, str]:
    base = f"https://archive.apache.org/dist/maven/maven-3/{v}/binaries/apache-maven-{v}-bin"
    return {"Windows": f"{base}.zip", "Darwin": f"{base}.tar.gz", "Linux": f"{base}.tar.gz"}


def _tomcat_urls(v: str) -> Dict[str, str]:
    major = v.split(".", 1)[0]
    base = f"https://archive.apache.org/dist/tomcat/tomcat-{major}/v{v}/bin/apache-tomcat-{v}"
    return {"Windows": f"{base}.zip", "Darwin": f"{base}.tar.gz", "Linux": f"{base}.tar.gz"}


def _mysql_urls(v: str) -> Dict[str, str]:
    major_minor = v.rsplit(".", 1)[0]
    win = f"https://dev.mysql.com/get/Downloads/MySQL-{major_minor}/mysql-{v}-winx64.zip"
    if IS_ARM and CURRENT_OS == "Darwin":
        mac = f"https://dev.mysql.com/get/Downloads/MySQL-{major_minor}/mysql-{v}-macos14-arm64.tar.gz"
    else:
        mac = f"https://dev.mysql.com/get/Downloads/MySQL-{major_minor}/mysql-{v}-macos14-x86_64.tar.gz"
    linux = f"https://dev.mysql.com/get/Downloads/MySQL-{major_minor}/mysql-{v}-linux-glibc2.28-x86_64.tar.xz"
    return {"Windows": win, "Darwin": mac, "Linux": linux}


def _python_urls(v: str) -> Dict[str, str]:
    win = f"https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
    mac = f"https://www.python.org/ftp/python/{v}/Python-{v}.tgz"
    linux = f"https://www.python.org/ftp/python/{v}/Python-{v}.tgz"
    return {"Windows": win, "Darwin": mac, "Linux": linux}


def _node_urls(v: str) -> Dict[str, str]:
    base = f"https://nodejs.org/dist/v{v}/node-v{v}"
    win = f"{base}-win-x64.zip"
    mac_arch = "arm64" if IS_ARM else "x64"
    mac = f"{base}-darwin-{mac_arch}.tar.gz"
    linux = f"{base}-linux-x64.tar.gz"
    return {"Windows": win, "Darwin": mac, "Linux": linux}


def _git_urls(v: str) -> Dict[str, str]:
    """
    Git 下载：
      - Windows: MinGit（便携版，解压即用）
      - macOS/Linux: 通常系统自带 git，或用户自己 brew install / apt-get 安装。
        这里提供源码 tar.gz 作为占位下载（不做编译，仅作展示）。
    """
    win = (
        f"https://github.com/git-for-windows/git/releases/download/"
        f"v{v}.windows.1/MinGit-{v}-64-bit.zip"
    )
    src = f"https://github.com/git/git/archive/refs/tags/v{v}.tar.gz"
    return {"Windows": win, "Darwin": src, "Linux": src}


def _conda_urls(v: str) -> Dict[str, str]:
    """
    Miniconda 安装器：
      - Windows: .exe
      - macOS:   .sh (根据架构挑 arm64 / x86_64)
      - Linux:   .sh
    版本号如 "py312_24.7.1-0"。
    """
    base = "https://repo.anaconda.com/miniconda"
    win = f"{base}/Miniconda3-{v}-Windows-x86_64.exe"
    mac_arch = "arm64" if IS_ARM else "x86_64"
    mac = f"{base}/Miniconda3-{v}-MacOSX-{mac_arch}.sh"
    linux = f"{base}/Miniconda3-{v}-Linux-x86_64.sh"
    return {"Windows": win, "Darwin": mac, "Linux": linux}


def _go_urls(v: str) -> Dict[str, List[str]]:
    """
    Go 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Go 版本号字符串，如 "1.22.5"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（华为云→清华→阿里云→中科大），官网末位。
    """
    # 国内镜像基址（按 R1.3 优先级），官网末位
    mirror_bases = [
        "https://repo.huaweicloud.com/golang",
        "https://mirrors.tuna.tsinghua.edu.cn/golang",
        "https://mirrors.aliyun.com/golang",
        "https://mirrors.ustc.edu.cn/golang",
    ]
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
          国内镜像在前（华为云→清华→阿里云→中科大），官网末位。
    说明: Gradle 官方对三平台都发布同一 zip 包（gradle-<v>-bin.zip），
          解压后根目录为 gradle-<v>/，内部含 bin/gradle / bin/gradle.bat。
    """
    # 国内镜像基址（按 R1.3 优先级），末位为官网
    mirror_bases = [
        "https://repo.huaweicloud.com/gradle",
        "https://mirrors.tuna.tsinghua.edu.cn/gradle",
        "https://mirrors.aliyun.com/gradle",
        "https://mirrors.ustc.edu.cn/gradle",
    ]
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
          国内镜像在前（npmmirror→ghproxy 加速 GitHub），末位为 GitHub releases 官网。

    说明:
      - Bun 官方发布在 GitHub Releases（oven-sh/bun 仓库），tag 名为 bun-v<version>；
      - 资源命名约定：bun-<platform>-<arch>.zip，平台标识为 windows / darwin / linux，
        架构标识为 x64 / arm64；
      - 国内最稳的镜像是淘宝 npmmirror（R1.3 表外特殊源），
        ghproxy.com 用于加速 GitHub releases 直链。
    """
    # 国内镜像基址（Bun 在国内仅此两源稳定）
    npmmirror_base = "https://registry.npmmirror.com/-/binary/bun"
    ghproxy_base = "https://ghproxy.com/https://github.com/oven-sh/bun/releases/download"
    official_base = "https://github.com/oven-sh/bun/releases/download"

    # 按 CPU 架构挑选文件名（Bun 官方命名约定）
    mac_arch = "arm64" if IS_ARM else "x64"
    linux_arch = "arm64" if IS_ARM else "x64"

    # tag 名带 bun-v 前缀；npmmirror 目录名亦为 bun-v<version>
    tag = f"bun-v{v}"

    def build_list(platform: str, arch: str) -> List[str]:
        """构造镜像在前 + 官网末位的 URL 列表。"""
        filename = f"bun-{platform}-{arch}.zip"
        return [
            f"{npmmirror_base}/{tag}/{filename}",
            f"{ghproxy_base}/{tag}/{filename}",
            f"{official_base}/{tag}/{filename}",
        ]

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
          国内镜像在前（清华→阿里云→中科大），官网末位。

    说明:
      - Docker 官方在 download.docker.com 提供 static binaries（单 tgz 包），
        Linux / Mac 平台均有，跨架构 x86_64 / aarch64；
      - Windows 平台不发布 static binary（必须用 Docker Desktop GUI 安装器），
        本函数不返回 Windows 键，urls_for_current() 在 Windows 上返回空列表，
        ComponentCard 会显示"当前系统 Windows 无可用下载地址"。
      - tgz 解压后根目录为 docker/，内部含 docker / dockerd 等二进制（无 bin 子目录）。
    """
    # 国内镜像基址（按 R1.3 优先级排序）
    # docker-ce 路径：linux/static/stable/<arch>/docker-<v>.tgz 或 mac/static/stable/<arch>/docker-<v>.tgz
    mirror_bases_linux = [
        "https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/static/stable",
        "https://mirrors.aliyun.com/docker-ce/linux/static/stable",
        "https://mirrors.ustc.edu.cn/docker-ce/linux/static/stable",
    ]
    mirror_bases_mac = [
        "https://mirrors.tuna.tsinghua.edu.cn/docker-ce/mac/static/stable",
        "https://mirrors.aliyun.com/docker-ce/mac/static/stable",
        "https://mirrors.ustc.edu.cn/docker-ce/mac/static/stable",
    ]
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

    入参 v: str   MongoDB 版本号字符串，如 "8.0.0"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（华为云→清华→阿里云→中科大），官网末位。

    说明:
      - MongoDB 官方在 fastdl.mongodb.org 提供 community 二进制包，
        Windows 是 zip，Linux 是 tgz；
      - 官方命名约定：mongodb-<platform>-<arch>-<version>.<ext>
        例：mongodb-windows-x86_64-8.0.0.zip、mongodb-linux-x86_64-8.0.0.tgz；
      - Mac 平台 MongoDB 官方不发布 community binary（用户应使用 brew），
        本函数不返回 Darwin 键；
      - 解压后根目录为 mongodb-<platform>-<arch>-<version>/，内部含 bin/ 子目录。
    """
    # 国内镜像基址（按 R1.3 优先级排序），fastdl.mongodb.org 的 URL 路径结构为 /<platform>/<filename>
    mirror_bases = [
        "https://repo.huaweicloud.com/mongodb",
        "https://mirrors.tuna.tsinghua.edu.cn/mongodb",
        "https://mirrors.aliyun.com/mongodb",
        "https://mirrors.ustc.edu.cn/mongodb",
    ]
    official_base = "https://fastdl.mongodb.org"

    # 按 CPU 架构挑选路径段（MongoDB 官方命名：x86_64 / arm64）
    # 注意：MongoDB Linux 用 aarch64，Windows 没有 arm64 社区版
    arch_linux = "aarch64" if IS_ARM else "x86_64"

    # Windows：只有 x64，无 arm64 社区版
    win_filename = f"mongodb-windows-x86_64-{v}.zip"
    win_urls = [f"{base}/windows/{win_filename}" for base in mirror_bases]
    win_urls.append(f"{official_base}/windows/{win_filename}")

    # Linux：区分 x86_64 / aarch64
    linux_filename = f"mongodb-linux-{arch_linux}-{v}.tgz"
    linux_urls = [f"{base}/linux/{linux_filename}" for base in mirror_bases]
    linux_urls.append(f"{official_base}/linux/{linux_filename}")

    return {
        "Windows": win_urls,
        "Linux":   linux_urls,
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
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（清华→华为云，binaries 路径占位 fallback），官网末位。

    说明:
      - PostgreSQL 官方 binaries 由 EnterpriseDB（EDB）发布在 get.enterprisedb.com；
      - 国内镜像（清华 / 华为云等）只镜像源码不镜像 binaries，本函数仍按 binaries
        路径占位写入，若镜像返回 404 会自动 fallback 到下一个源（符合 R1.7 改造指引）；
      - Mac 平台 EDB 不发布 binaries，本函数不返回 Darwin 键，提示用户用 brew；
      - 解压后根目录为 pgsql/，内部含 bin/ 子目录。
    """
    # 国内镜像基址（按 R1.3 优先级排序），占位 binaries 路径（实际可能 404，自动 fallback）
    # EDB 官网路径：postgresql/postgresql-<v>-1-<platform>-<arch>-binaries.<ext>
    mirror_bases = [
        "https://mirrors.tuna.tsinghua.edu.cn/postgresql/binaries",
        "https://repo.huaweicloud.com/postgresql/binaries",
    ]
    official_base = "https://get.enterprisedb.com/postgresql"

    # Windows：x64
    win_filename = f"postgresql-{v}-1-windows-x64-binaries.zip"
    win_urls = [f"{base}/windows/{win_filename}" for base in mirror_bases]
    win_urls.append(f"{official_base}/{win_filename}")

    # Linux：x86_64（PostgreSQL EDB binaries 只发布 x86_64，无 aarch64 binaries）
    linux_filename = f"postgresql-{v}-1-linux-x64-binaries.tar.gz"
    linux_urls = [f"{base}/linux/{linux_filename}" for base in mirror_bases]
    linux_urls.append(f"{official_base}/{linux_filename}")

    return {
        "Windows": win_urls,
        "Linux":   linux_urls,
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
        archive_map={"Windows": "zip", "Linux": "tar.gz"},
    )


def _kubectl_urls(v: str) -> Dict[str, List[str]]:
    """
    kubectl 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   kubectl 版本号字符串，如 "1.31.0"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（阿里云→清华→ghproxy 加速 GitHub），官网末位。

    说明:
      - kubectl 是 Kubernetes 官方 CLI 单二进制，三平台都发布；
      - 官方下载 URL 形如 https://dl.k8s.io/release/v<v>/bin/<os>/<arch>/kubectl<.exe>；
      - Windows 是 .exe，Linux/Mac 无扩展名（需 chmod +x）；
      - 阿里云镜像 kubernetes/ 路径结构与官网一致。
    """
    # 按 CPU 架构挑选路径段
    arch = "arm64" if IS_ARM else "amd64"
    # 国内镜像基址（按 R1.3 优先级排序）
    mirror_bases = [
        f"https://mirrors.aliyun.com/kubernetes-release/release/v{v}/bin",
        f"https://mirrors.tuna.tsinghua.edu.cn/kubernetes-release/release/v{v}/bin",
        f"https://ghproxy.com/https://dl.k8s.io/release/v{v}/bin",
    ]
    official_base = f"https://dl.k8s.io/release/v{v}/bin"

    # Windows：.exe
    win_filename = f"kubectl.exe"
    win_urls = [f"{base}/windows/{arch}/{win_filename}" for base in mirror_bases]
    win_urls.append(f"{official_base}/windows/{arch}/{win_filename}")

    # Linux：无扩展名
    linux_filename = "kubectl"
    linux_urls = [f"{base}/linux/{arch}/{linux_filename}" for base in mirror_bases]
    linux_urls.append(f"{official_base}/linux/{arch}/{linux_filename}")

    # Mac：无扩展名（Mac arm64 用 arm64，x64 用 amd64）
    mac_urls = [f"{base}/darwin/{arch}/{linux_filename}" for base in mirror_bases]
    mac_urls.append(f"{official_base}/darwin/{arch}/{linux_filename}")

    return {
        "Windows": win_urls,
        "Linux":   linux_urls,
        "Darwin":  mac_urls,
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

    入参 v: str   Jenkins LTS 版本号字符串，如 "2.426.3"
    返回: 三平台同 URL 列表（jenkins.war 跨平台），列表顺序即故障转移顺序：
          国内镜像在前（华为云→清华→阿里云），官网末位。

    说明:
      - Jenkins LTS war 包是跨平台单文件，下载后用 `java -jar jenkins.war` 启动；
      - 官方下载 URL 形如 https://get.jenkins.io/war-stable/<v>/jenkins.war；
      - 国内镜像路径结构与官网一致。
    """
    filename = "jenkins.war"
    mirror_bases = [
        f"https://repo.huaweicloud.com/jenkins/war-stable/{v}",
        f"https://mirrors.tuna.tsinghua.edu.cn/jenkins/war-stable/{v}",
        f"https://mirrors.aliyun.com/jenkins/war-stable/{v}",
    ]
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
    # 国内镜像基址
    mirror_bases = [
        "https://repo.huaweicloud.com/rabbitmq",
        "https://mirrors.tuna.tsinghua.edu.cn/rabbitmq",
        "https://mirrors.aliyun.com/rabbitmq",
    ]
    # GitHub releases 是末位官网
    github_base = "https://github.com/rabbitmq/rabbitmq-server/releases/download/v{v}"

    # Linux / Mac：generic_<platform>_<arch>-<v>.tar.xz
    # 实际 GitHub release 资产名形如 rabbitmq-server-generic-unix-<v>.tar.xz
    filename = f"rabbitmq-server-generic-unix-{v}.tar.xz"
    urls = [f"{base}/rabbitmq-server-generic-unix-{v}.tar.xz" for base in mirror_bases]
    urls.append(f"https://github.com/rabbitmq/rabbitmq-server/releases/download/v{v}/{filename}")

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
        # Linux/Mac 走 tar.xz（extract_archive 已支持）
        archive_map={"Linux": "tar.gz", "Darwin": "tar.gz"},
    )


def _kafka_urls(v: str) -> Dict[str, List[str]]:
    """
    Apache Kafka 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Kafka 版本号字符串，如 "3.8.1"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序。

    说明:
      - Kafka 是 Scala 项目，跨平台 tgz/zip，需 JDK 运行；
      - 官方下载 URL 形如 https://archive.apache.org/dist/kafka/<v>/kafka_2.13-<v>.tgz；
      - Scala 版本固定 2.13（Kafka 3.x 起唯一支持版本）。
    """
    scala_version = "2.13"
    linux_filename = f"kafka_{scala_version}-{v}.tgz"
    win_filename = f"kafka_{scala_version}-{v}.zip"

    mirror_bases = [
        "https://repo.huaweicloud.com/apache/kafka",
        "https://mirrors.tuna.tsinghua.edu.cn/apache/kafka",
        "https://mirrors.aliyun.com/apache/kafka",
        "https://mirrors.ustc.edu.cn/apache/kafka",
    ]
    official_base = "https://archive.apache.org/dist/kafka"

    linux_urls = [f"{base}/{v}/{linux_filename}" for base in mirror_bases]
    linux_urls.append(f"{official_base}/{v}/{linux_filename}")

    win_urls = [f"{base}/{v}/{win_filename}" for base in mirror_bases]
    win_urls.append(f"{official_base}/{v}/{win_filename}")

    return {
        "Windows": win_urls,
        "Linux":   linux_urls,
        "Darwin":  linux_urls,  # Mac 用 Linux 的 tgz
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
        archive_map={"Windows": "zip", "Linux": "tar.gz", "Darwin": "tar.gz"},
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

    mirror_bases = [
        "https://repo.huaweicloud.com/apache/rocketmq",
        "https://mirrors.tuna.tsinghua.edu.cn/apache/rocketmq",
        "https://mirrors.aliyun.com/apache/rocketmq",
        "https://mirrors.ustc.edu.cn/apache/rocketmq",
    ]
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

    mirror_bases = [
        "https://repo.huaweicloud.com/apache/pulsar",
        "https://mirrors.tuna.tsinghua.edu.cn/apache/pulsar",
        "https://mirrors.aliyun.com/apache/pulsar",
        "https://mirrors.ustc.edu.cn/apache/pulsar",
    ]
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

    入参 v: str   ActiveMQ 版本号字符串，如 "6.1.2"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序。

    说明:
      - ActiveMQ 是 Java 项目，跨平台 tar.gz/zip，需 JDK 运行；
      - 官方下载 URL 形如 https://archive.apache.org/dist/activemq/<v>/activemq-apache-<v>-bin.tar.gz；
      - ActiveMQ 5.x 用 apache-activemq-<v>-bin.tar.gz，5.18+ 改名 activemq-apache-<v>-bin.tar.gz。
    """
    # ActiveMQ 5.x 和 6.x 文件名不同：5.x 是 apache-activemq-<v>-bin.tar.gz，6.x 是 activemq-apache-<v>-bin.tar.gz
    major = int(v.split(".")[0]) if v else 5
    if major >= 6:
        linux_filename = f"activemq-apache-{v}-bin.tar.gz"
        win_filename = f"activemq-apache-{v}-bin.zip"
    else:
        linux_filename = f"apache-activemq-{v}-bin.tar.gz"
        win_filename = f"apache-activemq-{v}-bin.zip"

    mirror_bases = [
        "https://repo.huaweicloud.com/apache/activemq",
        "https://mirrors.tuna.tsinghua.edu.cn/apache/activemq",
        "https://mirrors.aliyun.com/apache/activemq",
        "https://mirrors.ustc.edu.cn/apache/activemq",
    ]
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
          国内加速在前（ghproxy / gh.idayer.com），GitHub releases 末位。

    说明:
      - Nacos 在 GitHub releases 发布，国内无官方镜像；
      - 文件名形如 nacos-server-<v>.zip（三平台通用，部分版本也发 .tar.gz）；
      - 走 ghproxy 加速 GitHub downloads URL，gh.idayer.com 作为备用加速源。
    """
    # Nacos 2.x 起 zip 是主发布格式（Linux 也能用 zip 解压即用）
    filename = f"nacos-server-{v}.zip"

    # 国内 GitHub 加速基址（按 R1.3 优先级，Nacos 在国内仅 ghproxy 类源稳定）
    accelerator_bases = [
        "https://ghproxy.com/https://github.com/alibaba/nacos/releases/download",
        "https://gh.idayer.com/https://github.com/alibaba/nacos/releases/download",
    ]
    # GitHub releases 末位官网
    github_base = "https://github.com/alibaba/nacos/releases/download"

    urls = [f"{base}/{v}/{filename}" for base in accelerator_bases]
    urls.append(f"{github_base}/{v}/{filename}")

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
          国内加速在前（ghproxy / gh.idayer.com），GitHub releases 末位。

    说明:
      - Seata 是 Apache 孵化项目（apache/incubator-seata），在 GitHub releases 发布；
      - 文件名形如 apache-seata-<v>-incubating-bin.zip（2.x）或 seata-server-<v>.zip（1.x）；
      - 走 ghproxy 加速 GitHub downloads URL，gh.idayer.com 作为备用加速源。
    """
    # Seata 2.x 改名 apache-seata-<v>-incubating-bin.zip，1.x 是 seata-server-<v>.zip
    major = int(v.split(".")[0]) if v else 2
    if major >= 2:
        filename = f"apache-seata-{v}-incubating-bin.zip"
    else:
        filename = f"seata-server-{v}.zip"

    # 国内 GitHub 加速基址
    accelerator_bases = [
        "https://ghproxy.com/https://github.com/apache/incubator-seata/releases/download",
        "https://gh.idayer.com/https://github.com/apache/incubator-seata/releases/download",
    ]
    # GitHub releases 末位官网
    github_base = "https://github.com/apache/incubator-seata/releases/download"

    urls = [f"{base}/v{v}/{filename}" for base in accelerator_bases]
    urls.append(f"{github_base}/v{v}/{filename}")

    # Seata zip 跨平台通用
    return {
        "Windows": urls,
        "Linux":   urls,
        "Darwin":  urls,
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
        archive_map={"Windows": "zip", "Linux": "zip", "Darwin": "zip"},
    )


def _elasticsearch_urls(v: str) -> Dict[str, List[str]]:
    """
    Elasticsearch 下载 URL 列表构造（R1 多源故障转移模式）。

    入参 v: str   Elasticsearch 版本号字符串，如 "8.15.0"
    返回: 按操作系统键映射的 URL 列表字典，列表顺序即故障转移顺序：
          国内镜像在前（清华→华为云→阿里云占位），elastic.co 官网末位。

    说明:
      - Elasticsearch 官方在 artifacts.elastic.co 发布跨平台归档包；
      - 版本 8.x 起 URL 含 -<platform>-<arch> 后缀（如 -linux-x86_64.tar.gz）；
      - 国内镜像路径可能与官网不完全一致，部分版本 404 会自动 fallback 到官网
        （符合 R1.7 改造指引"镜像返回 404 直接切下一个"）；
      - Windows 是 zip，Linux/Mac 是 tar.gz。
    """
    # 按 CPU 架构挑选路径段（Elasticsearch 用 x86_64 / aarch64）
    arch = "aarch64" if IS_ARM else "x86_64"

    # 国内镜像基址（按 R1.3 优先级排序）
    # 实际上国内镜像（清华/华为云/阿里云）对 Elasticsearch 同步情况不一，
    # 这里按官网路径占位写入，404 会自动 fallback 到 elastic.co
    mirror_bases = [
        "https://mirrors.tuna.tsinghua.edu.cn/elasticsearch",
        "https://repo.huaweicloud.com/elasticsearch",
        "https://mirrors.aliyun.com/elasticsearch",
    ]
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


def _get(url: str, timeout: int = 10) -> requests.Response:
    """带自动重试与 SSL 降级的 GET 请求。

    - 网络抖动/临时错误：最多重试 3 次，指数退避（1s, 2s）
    - SSL 错误（企业代理 MITM / 系统证书缺失等）：最后一次尝试关闭 SSL 校验
    """
    import time as _time
    headers = {"User-Agent": "byte-tools"}
    last_exc: Optional[Exception] = None
    for attempt in range(3):
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
            _time.sleep(1 << attempt)  # 1s, 2s
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
    """Adoptium Temurin 官方 API。"""
    data = _get("https://api.adoptium.net/v3/info/available_releases").json()
    releases = data.get("available_releases", [])
    lts = data.get("available_lts_releases", [])
    # releases 有时会遗漏最新 LTS —— 合并去重
    vs = sorted({int(v) for v in list(releases) + list(lts)}, reverse=True)
    result = []
    for v in vs:
        cv = ComponentVersion(
            version=str(v),
            url_map=_adoptium_jdk_url(str(v)),
            archive_map={"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"},
        )
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
    data = _get("https://api.github.com/repos/git-for-windows/git/releases?per_page=20").json()
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
        # 安装器文件后缀：Windows .exe / mac & linux .sh
        ext_map = {"Windows": "exe", "Darwin": "sh", "Linux": "sh"}
        return ComponentVersion(
            version=v,
            url_map=_conda_urls(v),
            archive_map=ext_map,  # 复用字段承载扩展名
        )

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
            data = _get(github_api, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).json()
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
            data = _get(github_api, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).json()
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
            data = _get(github_api, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).json()
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
            data = _get(github_api, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).json()
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
        data = _get(github_api, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).json()
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
        data = _get(api, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).json()
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
    从 GitHub releases API 抓取 Seata 版本列表（Seata 在国内无镜像索引页，主走 GitHub API）。

    返回: ComponentVersion 列表，按版本号倒序，最多 20 个。
    """
    versions = _fetch_github_releases_versions("apache/incubator-seata", prefix="v")
    stable = _sort_semver_desc(versions)
    if not stable:
        raise RuntimeError("Seata 版本列表为空（GitHub API 未返回有效版本）")
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
            data = _get(github_api, timeout=DOWNLOAD_PROBE_TIMEOUT * 2).json()
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
            self.done.emit(self.key, vs)
        except Exception as exc:  # pragma: no cover
            print(f"[fetch:{self.key}] {exc}")
            self.done.emit(self.key, None)


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
                ComponentVersion(
                    version=v,
                    url_map=_adoptium_jdk_url(v),
                    archive_map={"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"},
                )
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
            versions=[_cv(v, _maven_urls(v)) for v in ("3.9.6", "3.9.5", "3.8.8", "3.6.3")],
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
            versions=[_cv(v, _tomcat_urls(v)) for v in ("10.1.24", "9.0.89", "8.5.100")],
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
            versions=[_cv(v, _mysql_urls(v)) for v in ("8.0.37", "8.0.36", "5.7.44")],
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
            versions=[_cv(v, _python_urls(v)) for v in ("3.12.4", "3.11.9", "3.10.14", "3.9.19")],
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
    # macOS/Linux 一般依赖系统自带 git；Windows 用 MinGit 便携版
    components.append(
        Component(
            key="git",
            display_name="Git",
            env_var=None,
            path_subdir="cmd" if CURRENT_OS == "Windows" else "bin",
            exec_name="git",
            version_args=["--version"],
            versions=[_cv(v, _git_urls(v)) for v in ("2.45.2", "2.44.0", "2.43.0")],
        )
    )

    # ------------------ Miniconda ------------------
    # 安装器模式：exe/sh 静默安装到 install_dir
    conda_versions = []
    for v in ("py312_24.7.1-0", "py311_24.7.1-0", "py310_24.5.0-0"):
        cv = ComponentVersion(
            version=v,
            url_map=_conda_urls(v),
            archive_map={"Windows": "exe", "Darwin": "sh", "Linux": "sh"},
        )
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
            versions=[_go_cv(v) for v in ("1.22.5", "1.22.4", "1.21.12", "1.21.11")],
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
            versions=[_bun_cv(v) for v in ("1.1.0", "1.0.30", "1.0.29", "1.0.20")],
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
            versions=[_mongodb_cv(v) for v in ("8.0.0", "7.0.5", "6.0.20", "5.0.30")],
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
            versions=[_postgresql_cv(v) for v in ("16.4", "16.3", "15.8", "14.12")],
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
            versions=[_jenkins_cv(v) for v in ("2.426.3", "2.426.2", "2.426.1", "2.425.1")],
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
            # Windows 不支持自动下载（依赖 Erlang，且 RabbitMQ Windows 是安装器模式）
            unsupported_platform_hint=(
                "RabbitMQ 在 Windows 上需先安装 Erlang/OTP 再用 RabbitMQ Windows 安装器，"
                "本工具暂不提供自动下载。请前往官网下载安装："
                "https://www.rabbitmq.com/install-windows.html"
            ),
            versions=[_rabbitmq_cv(v) for v in ("4.0.0", "3.13.7", "3.13.6", "3.12.14")],
        )
    )

    # ------------------ Apache Kafka ------------------
    # 按 R1 规则：URL 走国内镜像优先 + 末位 Apache 官网回退（共 4 镜像 + 1 官网）
    # Kafka 是 Scala 项目，跨平台 tgz/zip，需 JDK 运行
    # 解压后根目录为 kafka_2.13-<v>/，内部含 bin/ 子目录
    components.append(
        Component(
            key="kafka",
            display_name="Apache Kafka",
            env_var="KAFKA_HOME",
            path_subdir="bin",
            exec_name="kafka-server-start",  # Kafka 启动脚本（Linux/Mac 带 .sh 后缀）
            version_args=[],
            versions=[_kafka_cv(v) for v in ("3.8.1", "3.8.0", "3.7.2", "3.6.2")],
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
            versions=[_pulsar_cv(v) for v in ("3.3.1", "3.3.0", "3.2.4", "3.1.3")],
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
            versions=[_activemq_cv(v) for v in ("6.1.2", "6.1.1", "5.18.4", "5.17.6")],
        )
    )

    # ------------------ Nacos ------------------
    # 按 R1 规则：URL 走国内 GitHub 加速优先 + 末位 GitHub releases 回退（共 2 加速 + 1 官网）
    # Nacos 是阿里开源服务发现组件，在 GitHub releases 发布，国内无官方镜像；
    # 解压后根目录为 nacos/，内部含 bin/ 子目录（startup.sh / startup.cmd）
    # exec_name="startup"：Windows 下 startup.cmd、Linux 下 startup.sh 均能被 shutil.which 通过 PATHEXT 命中
    components.append(
        Component(
            key="nacos",
            display_name="Nacos",
            env_var="NACOS_HOME",
            path_subdir="bin",
            exec_name="startup",  # Nacos 启动脚本（startup.sh / startup.cmd，无后缀写法以兼容 PATHEXT）
            version_args=["--version"],  # Nacos 启动脚本不支持 --version，失败不影响 detect 判定已安装
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
            version_args=["--version"],  # Seata 启动脚本不支持 --version，失败不影响 detect 判定已安装
            versions=[_seata_cv(v) for v in ("2.2.0", "2.1.0", "2.0.0", "1.8.0")],
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
            versions=[_elasticsearch_cv(v) for v in ("8.15.0", "8.14.3", "8.13.4", "7.17.18")],
        )
    )

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
        尝试从单个 URL 流式下载；成功返回 True，失败抛异常。

        入参 url: str   待下载的 URL
        返回: bool      是否成功
        """
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT,
                          allow_redirects=True) as r:
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
    def set_windows_user_env(name: str, value: str) -> None:
        """在 Windows 上使用 setx 永久写入用户环境变量。"""
        # setx 会截断超过 1024 字符的 PATH，这里额外用 winreg 直接写注册表
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
            ) as key:
                reg_type = winreg.REG_EXPAND_SZ if "%" in value else winreg.REG_SZ
                winreg.SetValueEx(key, name, 0, reg_type, value)
            # 通知系统刷新
            subprocess.run(
                ["setx", name, value],
                check=False,
                shell=False,
                capture_output=True,
            )
            # 同步当前进程的环境变量，避免后续 detect() 读到旧值
            # （os.environ 不会自动跟随注册表刷新，必须手动更新）
            os.environ[name] = value
        except Exception as exc:
            raise RuntimeError(f"写入 Windows 环境变量失败：{exc}")

    @staticmethod
    def append_windows_path(entry: str) -> None:
        """把 entry 追加到 Windows 用户 PATH。"""
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
        ) as key:
            try:
                current, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current = ""
        parts = [p for p in current.split(";") if p]
        if entry in parts:
            return
        parts.append(entry)
        EnvManager.set_windows_user_env("Path", ";".join(parts))

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
            # 同步删除当前进程的环境变量，避免后续 detect() 仍读到旧值
            os.environ.pop(name, None)
        except Exception as exc:
            raise RuntimeError(f"删除 Windows 环境变量 {name} 失败：{exc}")

    @staticmethod
    def remove_windows_path_entry(entry: str) -> None:
        """
        从 Windows 用户 PATH 中移除指定条目（保持其他条目不变）。

        入参 entry: str  要移除的 PATH 条目（绝对路径字符串）
        """
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
        ) as key:
            try:
                current, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current = ""
        # 按 ; 切分后过滤掉与 entry 相同的条目，保留其他
        parts = [p for p in current.split(";") if p and p != entry]
        EnvManager.set_windows_user_env("Path", ";".join(parts))

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
    def _detect_status(self) -> None:
        """检测该组件当前是否已安装、已配置。

        - 若系统 PATH 或 XXX_HOME 已能找到可执行文件，则视为「已配置」，禁用
          「仅配置环境变量」按钮，避免重复写入。
        - 若本地已解压但未配置，则允许点击「仅配置环境变量」。
        - 若未安装，两个按钮均可用。
        """
        result = self.component.detect()
        if result.installed:
            ver = result.version_text or "未知版本"
            where = result.source or "系统"
            self.status_label.setText(f"✓ 已配置（{where}） · {ver}")
            self.status_label.setStyleSheet(
                "color:#2e7d32;font-weight:600;padding:2px 8px;"
                "background:#e8f5e9;border-radius:10px;"
            )
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
            f"  · 从 PATH 移除 bin 目录",
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

        # ------- 主体：卡片列表 + 日志区 -------
        body = QSplitter(Qt.Vertical)
        body.setObjectName("bodySplitter")

        # 卡片滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("cardsScroll")
        cards_wrap = QWidget()
        cards_wrap.setObjectName("cardsWrap")
        cards_layout = QVBoxLayout(cards_wrap)
        cards_layout.setContentsMargins(18, 18, 18, 18)
        cards_layout.setSpacing(14)

        self.cards: List[ComponentCard] = []
        for comp in self.components:
            card = ComponentCard(comp, self._append_log)
            cards_layout.addWidget(card)
            self.cards.append(card)
        cards_layout.addStretch(1)
        scroll.setWidget(cards_wrap)
        body.addWidget(scroll)

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

            #cardsScroll { border: none; background: transparent; }
            #cardsWrap { background: transparent; }
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
    def _start_fetch_versions(self) -> None:
        """从各官网并发拉取版本列表。可反复调用（刷新）。"""
        # 若有 worker 仍在运行，等它跑完再触发新一轮
        alive = [w for w in self._fetch_workers if w.isRunning()]
        if alive:
            self._append_log("warn", f"仍有 {len(alive)} 个抓取任务在进行，请稍候…")
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
        for card in self.cards:
            fetcher = FETCHERS.get(card.component.key)
            if not fetcher:
                continue
            w = VersionFetchWorker(card.component.key, fetcher, self)
            w.done.connect(self._on_versions_fetched)
            self._fetch_workers.append(w)
            self._fetch_pending += 1
            w.start()

    def _on_versions_fetched(self, key: str, versions) -> None:
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
        self._save_settings()
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
