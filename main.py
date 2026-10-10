# -*- coding: utf-8 -*-
"""
字节工具箱 By jilong2026
==========================

Copyright (c) 2026 jilong2026
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
import shutil
import socket
import subprocess
import sys
import tarfile
import uuid
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

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
APP_NAME = "字节工具箱"
# 界面与 macOS bundle 都显示它；**发版前必须和要打的 tag 一起改**。
# release.yml 第一步会拿 tag 比对，不一致就直接红 —— 因为发出去的 exe 上写的版本
# 骗人，比没有版本号更糟（用户报问题时给的是 v1.1.1，实际装的是 v1.2.0 的修复）。
APP_VERSION = "1.1.1"
GITHUB_URL = "https://github.com/jilong2026/byte-tools"
CONFIG_DIR = Path.home() / ".env-tools"
CONFIG_FILE = CONFIG_DIR / "config.json"
RUNNING_FILE = CONFIG_DIR / "running.json"      # 本机进程事实，与用户偏好分开（设计 §3）


def _open_in_file_manager(path: str) -> bool:
    """用系统自带的文件管理器打开一个目录（状态条上那个工作目录链接）。

    单独抽出来是为了可测：用例把 `_open_in_file_manager` 换成记录调用的桩，
    就不会真在用户桌面上弹一个资源管理器窗口（那是测试不该有的副作用）。
    返回是否成功发起，失败由调用方写进日志，不弹窗打断。
    """
    target = str(path)
    try:
        if not target or not Path(target).is_dir():
            return False
        if CURRENT_OS == "Windows":
            os.startfile(target)          # noqa: S606 - 系统自带命令，路径来自我们自己
        elif CURRENT_OS == "Darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return True
    except Exception:                     # noqa: BLE001
        return False


# 当前操作系统标识与 CPU 架构：刻意不用 platform.system() / platform.machine()。
# 那两个函数内部会走 platform.uname() -> win32_ver() -> 一次 WMI 查询，而 WINMGMT
# 冷启动时这条查询能阻塞几十秒到一两分钟（本机实测），表现就是"双击启动脚本之后
# 窗口一直没出来"。一个"挑哪个架构的包"的判断不该把整个程序锁在系统服务上：
# sys.platform 是解释器自带的常量，架构在 Windows 上取自环境变量，都不作系统调用。
def _os_name() -> str:
    """返回 'Windows' / 'Darwin' / 'Linux'，与 platform.system() 的取值一致。"""
    if sys.platform == "win32":
        return "Windows"
    if sys.platform == "darwin":
        return "Darwin"
    return "Linux"


def _machine_name() -> str:
    """返回小写 CPU 架构（amd64 / arm64 / x86_64 / aarch64 …），与 platform.machine().lower() 一致。"""
    if sys.platform == "win32":
        # 32 位进程跑在 64 位系统上时，PROCESSOR_ARCHITECTURE 只报 x86，
        # 真实架构记在 PROCESSOR_ARCHITEW6432 里，所以它优先。
        arch = (os.environ.get("PROCESSOR_ARCHITEW6432")
                or os.environ.get("PROCESSOR_ARCHITECTURE") or "AMD64")
    else:
        arch = os.uname().machine
    return arch.lower()


CURRENT_OS = _os_name()
MACHINE = _machine_name()
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
    # 启动描述符（见 docs/superpowers/specs/2026-10-05-one-click-launch-design.md §3）。
    # 由 build_components() 末尾按 LAUNCH_OF 统一赋值，不要在构造处手写 ——
    # 与 MULTI_VERSION_KEYS 同一套"单一真源"做法。
    launch: Optional["LaunchSpec"] = None
    # 界面 Tab 分组名，取值必须是 COMPONENT_CATEGORIES 之一。
    # 由 build_components() 末尾按 COMPONENT_CATEGORY_OF 统一赋值，不要在构造处手写。
    category: str = ""
    # 数据在磁盘上的位置 + 删目录时数据会不会没（卸载确认框里显示）。
    # 全组件多版本之后这条更重要了：用户会同时看到好几个版本目录，
    # 不讲清"数据在哪个目录、删它会不会丢数据"就会误删（2026-06-06 用户要求）。
    #
    # 写法纪律：**只写实测过的事实**。没在本机装过的组件不许凭印象写具体路径 ——
    # 写错会让用户以为数据在别处、真需要时找不到，或者反过来误以为会丢而不敢删。
    # 确实没实测的写「未实测」并说明该组件的数据一般由什么机制管理。
    data_note: str = ""
    # **不在界面上出现的组件**（2026-10-08 为 Erlang 加的）。
    # 它不是给用户装的东西，而是 rabbitmq 的前置运行时：用户要的是"点启动就能起"，
    # 而不是"先自己去找 Erlang 装好"。界面据此跳过它（见 MainWindow._build_tabs），
    # 但它仍然走同一套下载/解压/版本解析机制 —— 少一套平行实现就少一处会坏的地方。
    hidden: bool = False

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

        多版本组件的新语义: 选中版本没装、磁盘上又装着多个版本时不再罢工，
        改为按语义版本降序取最高的那个并说明；XXX_HOME 定位仍排在它之前——
        HOME 指的是当前生效的那个版本，按它定位比"猜最高"更准。
        非多版本组件维持原行为（定位不到具体哪个就罢工）。
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
            if self.multi_version:
                # 选中的版本没装、又装了多个：不能罢工（罢工等于卸载失灵）。
                # 按语义版本降序取最高的那个，并把清单说清楚。
                ordered = installed_versions(self)
                if ordered:
                    ver, path = ordered[0]
                    return path, (f"所选版本 {self.key}-{version} 未安装；"
                                  f"已装 {'、'.join(v for v, _p in ordered)}，"
                                  f"改为卸载版本最高的 {ver}")
                names = "、".join(d.name for d in dirs)
                return None, f"存在多个已安装版本（{names}）但都无法识别版本号，请在下拉框中选择"
            # 非多版本组件维持原行为：装了多个版本又定位不到具体是哪一个时罢工。
            names = "、".join(d.name for d in dirs)
            return None, f"存在多个已安装版本（{names}），请先在下拉框中选择具体版本"
        return None, f"未找到 {self.key}-{version} 的安装目录，也没有其他已安装版本"

    def uninstall(self, version: str) -> str:
        """
        卸载指定版本：删除安装目录、移除正指向被删目录的 XXX_HOME、只清理被删版本的
        PATH 条目；多版本组件在任何破坏性动作之前先快照生效版本，删掉生效版本时自动
        切到剩余里版本号最高的那个（但 XXX_HOME 落在组件根外 = 用户自己的安装时，
        只在摘要里提示、不自动改写，见 F12 守卫）。

        入参 version: str  下拉框选中的版本号；与实际安装版本不一致时会自动校正目标
        返回: str           卸载结果摘要（中文，多步骤用中文分号分隔）

        说明:
          - 生效版本快照（active_before）必须在删目录/删 HOME 之前取：老配置没有
            active 登记表，生效版本靠 XXX_HOME 反推，而第 2 步可能正好把那个 HOME
            删掉，事后再读永远是 None，"自动重排"会静默失效；
          - XXX_HOME 只有正指向本次被删目录才删除；指向同组件其他版本时保留，
            交给生效版本重排那一步处理；指向本组件根下已消失目录的残留 HOME
            （早年手工删目录留下的死配置）会被清掉；指向组件目录之外（用户自己的安装）绝不动；
          - PATH 默认只清理"本次被删目录"之内的条目——多版本并存时按组件根扫会把
            用户没删的那些版本的条目一起删掉；只有本组件已无其它安装目录时，才回到
            按组件根整体清扫，此时目录已被手工删除的历史死条目也能一并清掉；
            path_subdir 为空的组件（如 bun）条目就在被删目录本身之下，同样覆盖；
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

        # 生效版本快照：必须在删目录/删 HOME 之前取。
        # 老配置没有 active 登记表，生效版本靠 XXX_HOME 反推，而第 2 步可能正好把那个 HOME 删掉——
        # 事后再读就永远是 None，"自动重排"会静默失效。多版本组件才算，非多版本白读一次配置。
        active_before = (load_active_map().get(self.key) or infer_active_from_env(self)) \
            if self.multi_version else None

        # 1. 删除安装目录（安装器模式跳过，由安装器自行管理位置）
        if self.installer_mode:
            summary_parts.append("安装器模式，跳过安装目录删除（如需彻底清理请用对应卸载工具）")
        elif install_path is not None:
            try:
                shutil.rmtree(install_path)
                summary_parts.append(f"已删除安装目录：{install_path}")
            except Exception as exc:
                # 目录删不掉多半是有进程占着它（真机 2026-10-07 rabbitmq：内容全删光、
                # 顶层目录删不掉，而当时还在跑的只有 epmd.exe）。这里必须把三件事说清：
                # 内容已经没了、环境变量与 PATH 照旧往下清、空壳目录等占用结束后再删一次。
                # 绝不能因为它就中断后续清理 —— 那正是"永久卸载不了"的起点。
                summary_parts.append(
                    f"安装目录没删干净（内容已删除，顶层目录疑似被别的进程占用）：{exc}；"
                    f"环境变量与 PATH 仍照常清理，残留的空目录 {install_path} "
                    f"请结束占用它的进程（或重启）后再点一次卸载清掉")

        # 2. 删除 XXX_HOME：只有它正指向本次被删的版本才删；指向同组件其他版本时保留，
        #    交给第 4 步的生效重排处理，避免"删了 17，把 21 的 JAVA_HOME 也清了"。
        #    读持久层而不是 os.environ：本进程可能早已被安装/切换写脏。
        if self.env_var:
            current_home = EnvManager.read_user_env(self.env_var) or EnvManager.get(self.env_var)
            if current_home and install_path is not None and EnvManager._same_path(
                    current_home, str(install_path)):
                try:
                    EnvManager.drop_user_env(self.env_var)
                    summary_parts.append(f"已删除环境变量：{self.env_var}")
                except Exception as exc:
                    summary_parts.append(f"删除环境变量 {self.env_var} 失败：{exc}")
            elif current_home and not EnvManager._under_root(
                    str(current_home), str(component_root)):
                summary_parts.append(
                    f"环境变量 {self.env_var} 指向其他目录（{current_home}），未删除")
            elif current_home and EnvManager._under_root(
                    str(current_home), str(component_root)) and not Path(
                    os.path.expandvars(str(current_home))).is_dir():
                # HOME 落在本组件根内却指向一个已经不存在的目录 = 早年手工删目录留下的死配置，
                # 留着它只会让界面无缘无故"检测不到"，这里清掉。
                # 判据是"目录不存在"而不是"本次没删到东西"：rmtree 失败时目录还在，绝不该清 HOME。
                try:
                    EnvManager.drop_user_env(self.env_var)
                    summary_parts.append(f"已清理指向不存在目录的环境变量：{self.env_var}")
                except Exception as exc:
                    summary_parts.append(f"清理环境变量 {self.env_var} 失败：{exc}")
            # 沉默分支说明：current_home 落在本组件目录内、又没指向被删目录时，上一条
            # 分支已把"指向同组件已消失目录"的死配置 HOME 清掉；真正沉默的只剩
            # "HOME 指着同组件另一个还在的目录"这一种——绝不能删（删了生效版本就没了），
            # 交给第 4 步按 active 登记表重排。

        # 3. 清理 PATH 中属于"本次被删版本"的条目。
        #    多版本并存时绝不能按组件根清——会把用户没删的那些版本的条目一起删掉；
        #    只有本组件已无其它安装目录时，才回到"按组件根扫一遍"，顺带清掉早年手工删目录留下的死条目。
        #    （第 1 步已把被删目录 rmtree 掉，所以 remaining_dirs 里不含它本身。）
        remaining_dirs = [p for p in component_root.iterdir()
                          if p.is_dir() and p.name != "downloads" and not p.name.startswith(".")] \
                         if component_root.is_dir() else []
        scope = str(component_root) if not remaining_dirs else str(install_path)
        if install_path is None:
            scope = str(component_root)
        try:
            removed = EnvManager.remove_path_entries_under(scope)
            summary_parts.append("已从 PATH 移除：" + "、".join(removed) if removed
                                 else "PATH 中没有本次卸载范围的条目")
        except Exception as exc:
            summary_parts.append(f"清理 PATH 失败：{exc}")

        # 4. 多版本组件的生效登记收尾。active 一律取开头的快照 active_before，不再事后
        #    读登记表/反推：老配置的生效版本靠 XXX_HOME 反推，而第 2 步可能已把那个 HOME
        #    删掉，事后再读永远是 None，"自动重排"会静默失效。
        #    全删光：清登记；HOME 只在指向本组件目录时才清，用户指到别处的绝不动。
        #    还有剩余：删掉的正是生效版本时，判据同样是 HOME 的位置（F12）——落在组件
        #    根外（用户自己的安装）只提示不改写；落在根内或已被第 2 步删掉才切到剩余里
        #    版本号最高的；只有"我们自己的 HOME"（落在组件根内）被这次卸载带偏/删掉，
        #    才按生效版本重建。
        if self.multi_version:
            remaining = installed_versions(self)
            removed_ver = version_from_install_dir(self, install_path) if install_path else None
            active = active_before
            if not remaining:
                try:
                    save_active_version(self.key, None)
                except Exception as exc:
                    summary_parts.append(f"清除生效登记失败：{exc}")
                home_now = EnvManager.read_user_env(self.env_var) if self.env_var else None
                if home_now and EnvManager._under_root(str(home_now), str(component_root)):
                    try:
                        EnvManager.drop_user_env(self.env_var)
                        summary_parts.append(f"已删除环境变量：{self.env_var}")
                    except Exception as exc:
                        summary_parts.append(f"删除 {self.env_var} 失败：{exc}")
                elif home_now:
                    summary_parts.append(
                        f"环境变量 {self.env_var} 指向组件目录之外（{home_now}），未删除")
                summary_parts.append("已无安装版本，生效登记已清除")
            else:
                remaining_map = dict(remaining)
                target = None
                if active and active in remaining_map:
                    # 只在"我们自己的 HOME 被这次卸载带偏"时重建：
                    #   · 该组件根本没有 HOME 变量（如 python，env_var=None）→ 没有 HOME 可带偏，不动 PATH 也不动；
                    #   · HOME 在我们组件根之外 = 用户自己的安装，绝不覆盖（第 2 步已说过"未删除"，这里不能反悔）。
                    home_now = EnvManager.read_user_env(self.env_var) if self.env_var else None
                    if self.env_var and (
                            not home_now
                            or (EnvManager._under_root(str(home_now), str(component_root))
                                and not EnvManager._same_path(
                                    str(home_now), str(remaining_map[active])))):
                        target = active
                elif active and removed_ver == active:
                    # 删掉的正是生效版本：切到剩余里版本号最高的（installed_versions 已降序）。
                    # F12：动手前先看当前 HOME 的**位置**——落在组件根外 = 用户自己的安装
                    # （IDE 或系统装指过去的），绝不覆成我们的目录：本期只做"我们写过的
                    # 东西自己收尾"，摘要里提示用户点按钮重设即可。落在根内、或已被第 2 步
                    # 删掉、或压根没设 = 我们写的（含老配置从根内 HOME 反推的生效版本，
                    # 修复轮 2 的 I-1），照旧自动重排。判据用位置而不是登记表有没有 key：
                    # 与上面重建分支同源，也只有位置解释得了"谁写的"。
                    home_now = EnvManager.read_user_env(self.env_var) if self.env_var else None
                    if home_now and not EnvManager._under_root(
                            str(home_now), str(component_root)):
                        summary_parts.append(
                            f"生效版本 {active} 已卸载，但 {self.env_var} 指向组件目录之外"
                            f"（{home_now}，是你自己的选择），不自动改写；"
                            f"如需由本工具接管，可选中剩余版本后点「切换」重设")
                    else:
                        target = remaining[0][0]
                # 登记表里那个版本本来就不在磁盘上、这次又没删到它 → 不猜，交给用户重点按钮
                if target:
                    try:
                        steps = apply_active_version(self, target)
                    except SwitchError as exc:
                        try:
                            save_active_version(self.key, None)
                        except Exception as save_exc:
                            summary_parts.append(f"清空生效登记也失败：{save_exc}")
                        # N-2：target == active 是"按生效版本重建"，不是"切"——
                        # 它本来就在生效，说"自动切到"是假话。失败分支同理分叉。
                        summary_parts.append(
                            (f"自动切到 {target} 失败，生效登记已清空，请重新点一次"
                             f"「切换」：{exc}") if target != active else
                            (f"按生效版本 {target} 重建环境变量与 PATH 失败，生效登记已清空，"
                             f"请重新点一次「切换」：{exc}"))
                    else:
                        summary_parts.append(
                            f"生效版本已自动切到 {target}" if target != active
                            else f"已按生效版本 {target} 重建环境变量与 PATH")
                        # D6：切换步骤日志（含"已开着的终端/IDE 需重开"与 Oracle
                        # javapath 抢先提醒）必须进摘要，与切换路径 _apply_active 同一套话。
                        summary_parts.extend(steps)
                        try:
                            save_active_version(self.key, target)
                        except Exception as exc:
                            summary_parts.append(
                                f"生效登记表写入失败：{exc}（环境变量已切到 {target}，"
                                "重开界面可能显示旧生效版本，再点一次「切换」可修正）")

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


def install_dir_is_hollow(path: Path) -> bool:
    """安装目录里一个条目都没有 = 卸载被"目录正被别的进程占用"打断后留下的**空壳**。

    真机 2026-10-07 rabbitmq：`shutil.rmtree` 把内容全删光了，顶层目录删不掉，于是
    `installed_versions()` 仍然报"已装 4.0.9"、下拉框给它挂着绿勾，而 `uninstall()`
    第 4 步看到生效版本还在"剩余版本"里，就把 RABBITMQ_HOME 与 PATH **重建**回这个空壳
    —— 每次卸载都是白清一遍环境再写回去，用户看到的是永久"卸载不了"。
    判据只用"目录空"这一条：更严的判据（比如要求可执行文件在场）会把 jenkins/war
    这类落地形状特殊的真安装误判成没装，代价比收益大。
    """
    try:
        return path.is_dir() and not any(path.iterdir())
    except OSError:
        return False


def residue_install_dirs(comp: "Component") -> List[Tuple[str, Path]]:
    """磁盘上还留着、内容已被删空的残留目录，按版本降序。

    它们**不算已装**：不进 `installed_versions()`，因此不进绿勾、状态胶囊，
    也不会成为生效版本重排的目标。之所以要单独列出来，是因为界面必须还能
    选中并卸载它 —— 否则那个删不掉的目录就成了谁都不碰的死角。
    """
    pairs = []
    for path in comp.installed_dirs():
        ver = version_from_install_dir(comp, path)
        if ver and install_dir_is_hollow(path):
            pairs.append((ver, path))
    order = {v: i for i, v in enumerate(_sort_semver_desc([v for v, _p in pairs]))}
    return sorted(pairs, key=lambda p: order[p[0]])


def installed_versions(comp: "Component") -> List[Tuple[str, Path]]:
    """该组件在磁盘上真实装着的版本，按语义版本**降序**（最新在前）。

    入参 comp: Component
    返回: List[Tuple[str, Path]]  (版本号, 安装目录)

    说明: 排序必须走 _sort_semver_desc。用 str.sort() 会得到 jdk-8 > jdk-21 的错序，
          "配置环境变量"和"卸载后自动切到剩余最高版本"都会挑错版本。
          空壳目录（install_dir_is_hollow）不算已装，走 residue_install_dirs 那条通道：
          把它们算进来会让卸载永远无法收敛（见那两个函数各自的注释）。
    """
    pairs: List[Tuple[str, Path]] = []
    for path in comp.installed_dirs():
        ver = version_from_install_dir(comp, path)
        if ver and not install_dir_is_hollow(path):
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
# DETACHED_PROCESS 在部分 Python 上缺失，按 0x00000008 兜底（Task 7 裁决：
# 统一用这个常量，别在表达式里混两种写法）。
DETACH_FLAGS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
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


class ExternalDiscoveryWorker(QThread):
    """后台扫一遍"系统里还有哪些这个组件的安装"（§5.1）。

    为什么必须是线程、而且必须**按需**触发：这一步要对每个外部候选真跑一次版本命令
    （java -version / mvn -v …）。7 个白名单组件 × 每个 2~4 个候选，启动时全量扫一遍
    就是同时在用户机器上起十几个进程 —— 所以只在该卡片的折叠区被展开时才起。
    """

    done = Signal(list)      # List[DiscoveredVersion]（含工作区那份）

    def __init__(self, component: Component,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.component = component

    def run(self) -> None:
        try:
            cands = discover_version_candidates(self.component)
            self.done.emit(probe_discovered_versions(self.component, cands))
        except Exception:      # noqa: BLE001  发现失败不该把界面拖垮
            self.done.emit([])


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

# GitHub Release 加速器。**顺序 = 速度顺序**，第一位是实测最快的那条链路。
#
# 2026-10-08 本机实测重排（原来 ghproxy.net 在前，那是 2026-09 的结论，已经反转）：
#   对同一个 PowerShell-7.6.6-win-x64.zip（101MB）与 Erlang otp_win64_27.3.4.1.zip（155MB）
#   各取 10-13 秒的实际字节数（带 UA=byte-tools）：
#       ghfast.top      751 KB/s (pwsh) / 401 KB/s (erlang)
#       gh-proxy.com    133 KB/s        / 117 KB/s
#       ghproxy.net      14 KB/s        /  28 KB/s
#   两个仓库的结论一致，所以这不是单个包的现象。
#   代价说明：旧的顺序下 erlang 的 155MB 只有 6 KB/s（≈7 小时），
#   而这条链路本来就是给"国内没镜像、只能走 GitHub"的组件用的 ——
#   顺序错了等于那些组件全都下不下来。
GH_ACCELERATORS: List[str] = [
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
]

# 故障转移参数（避免魔法数字）
DOWNLOAD_PROBE_TIMEOUT = 5     # 单 URL 探测超时（秒）
# 下载超时用 (连接, 读取) 二元组，不能用单值。
# 真机 2026-10-06 实测踩过：requests 的 timeout 传单值时它**同时**是连接超时和读超时，
# 30 秒的读上限会把大包打死 —— jdk(190MB) / gradle(130MB) / postgresql(110MB) /
# elasticsearch(600MB) 这些全都"所有下载源均不可用"，而实测那些源 curl 探测全是HTTP 200。
# 源没问题，是读超时太短：慢速下载时两次读之间很容易超过 30 秒。
# 读取超时给足（单次读 60 秒），连接仍保持短（10 秒，探测到不通就快速切下一个源）。
DOWNLOAD_CONNECT_TIMEOUT = 10
DOWNLOAD_READ_TIMEOUT = 60
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


# 离线兜底用的镜像文件名（2026-10-06 实测采集，_collect_jdk_files.py）。
# 键是大版本，值是 {镜像标识: 文件名}。文件名含具体补丁号 —— 镜像同步哪个就用哪个，
# 不猜：猜错了会 404，而 404 在离线清单里没有任何补救机会（没有"再刷新一次"的时机）。
_JDK_OFFLINE_FILES: Dict[str, Dict[str, str]] = {
    "21": {"nju":   "OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip",
           "tuna":  "OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip"},
    "17": {"nju":   "OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip",
           "tuna":  "OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip"},
    "11": {"nju":   "OpenJDK11U-jdk_x64_windows_hotspot_11.0.32.1_1.zip",
           "tuna":  "OpenJDK11U-jdk_x64_windows_hotspot_11.0.32.1_1.zip"},
    "8":  {"nju":   "OpenJDK8U-jdk_x64_windows_hotspot_8u504b01.zip",
           "tuna":  "OpenJDK8U-jdk_x64_windows_hotspot_8u504b01.zip"},
}


def _adoptium_offline_urls(version: str,
                           files: Dict[str, str]) -> Dict[str, List[str]]:
    """离线清单用的 JDK 地址：镜像在前（实测速度排序），官方 API 末位兜底。

    入参 version: str大版本号，如 "21"
    入参 files:   Dict[镜像标识, 文件名]，来自 _JDK_OFFLINE_FILES

    与 _adoptium_jdk_url 的区别：那个要联网解析镜像目录（启动时不做，卡 UI），
    这个只用写死的文件名 —— build_components() 在程序启动时调用，绝不能联网。
    代价是补丁号会过期（镜像同步了更新的版本时仍下这个）；换来的是**离线能下**，
    而 JDK 21 走官方 API 在国内根本连不上 —— 没有镜像就完全装不了。
    """
    api = "https://api.adoptium.net/v3/binary/latest"
    mirrors: List[str] = []
    # 按 2026-10-06 实测速度排（nju 14.6 / tuna 13.5 MB/s；17 上 nju 14.6 vs
    # tuna 4.9，差距更明显）。**不调整 _ADOPTIUM_LAYOUTS 本身** —— 那个还被
    # 联网刷新路径（_adoptium_mirror_urls）共用，动它会改刷新行为，超出本次范围。
    for base_name, sub in sorted(_ADOPTIUM_LAYOUTS, key=lambda x: x[0] != "nju"):
        fname = files.get(base_name)
        if not fname:
            continue
        arch, os_dir, _ext = _adoptium_dirs()[CURRENT_OS]
        mirrors.append(f"{_mb(base_name)[0]}{sub}/{version}/jdk/{arch}/{os_dir}/{fname}")

    out: Dict[str, List[str]] = {}
    for os_key, (arch, os_dir, _ext) in _adoptium_dirs().items():
        #镜像文件名是按本机平台实测的，只对本机成立；其它平台退回官方 API。
        # 猜别的平台的文件名等于给一个必然 404 的 URL，没有意义。
        official = f"{api}/{version}/ga/{os_dir}/{arch}/jdk/hotspot/normal/eclipse"
        out[os_key] = (mirrors if os_key == CURRENT_OS else []) + [official]
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
    mirrors = _mb("huaweicloud", "bfsu", "tuna", "tencent", "ustc", "nju", "aliyun")

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
    mirrors = _mb("huaweicloud", "tencent", "tuna", "bfsu", "nju", "ustc", "aliyun")

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
    实测（2026-10-06 取样 2MB 测速，Range 请求）纠正：
      - 华为云 `mirrors.huaweicloud.com/mysql/Downloads/` **30.8 MB/s**，阿里云只有 0.4 MB/s ——
        差 70 倍，所以华为云排首位（原来阿里云在前）。
      - 官方 `cdn.mysql.com/Downloads/MySQL-8.0/mysql-8.0.28-winx64.zip` **实测 404**：
        旧版本归档已从主 CDN 下线（dev.mysql.com 与 downloads.mysql.com/archives 返 403 反爬）。
        官网对 8.0.28 这个版本不再兜底，但 8.0.37 等新版仍挂着，所以保留在末位不删 ——
        删掉等于放弃"镜像全挂时还有最后一次机会"。
    """
    major_minor = v.rsplit(".", 1)[0]
    cdn_base = f"https://cdn.mysql.com/Downloads/MySQL-{major_minor}"
    mac_arch = "arm64" if IS_ARM else "x86_64"
    win_name = f"mysql-{v}-winx64.zip"
    linux_mirror_name = f"mysql-{v}-linux-glibc2.12-x86_64.tar.xz"
    linux_official_name = f"mysql-{v}-linux-glibc2.28-x86_64.tar.xz"
    # 按实测速度排：华为云 30.8 MB/s 在前，阿里云 0.4 MB/s 退到末位（仍留着，它能通）。
    huawei, aliyun = _mb("huaweicloud", "aliyun")

    # macOS 包：官方 CDN 只挂最新版（8.0.28/8.0.29 连 macos11、macos12 命名也 404），
    # 镜像站则留着老版本当年命名的包，所以镜像侧试 macos11/macos12，官方只试 macos14。
    mac_list: List[str] = []
    for base in (f"{huawei}/mysql/Downloads/MySQL-{major_minor}",
                 f"{aliyun}/mysql/MySQL-{major_minor}"):
        mac_list += [f"{base}/mysql-{v}-{tag}-{mac_arch}.tar.gz" for tag in ("macos11", "macos12")]
    mac_list.append(f"{cdn_base}/mysql-{v}-macos14-{mac_arch}.tar.gz")

    return {
        "Windows": [f"{huawei}/mysql/Downloads/MySQL-{major_minor}/{win_name}",
                    f"{aliyun}/mysql/MySQL-{major_minor}/{win_name}",
                    f"{cdn_base}/{win_name}"],
        "Darwin":  mac_list,
        "Linux":   [f"{huawei}/mysql/Downloads/MySQL-{major_minor}/{linux_mirror_name}",
                    f"{aliyun}/mysql/MySQL-{major_minor}/{linux_mirror_name}",
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
        mirrors = [f"{b}/nodejs-release/v{v}/{name}" for b in _mb("tuna", "bfsu", "nju")]
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
    hwm, hw = _mb("huaweicloud", "huaweicloud-py")
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
    hwm, hw = _mb("huaweicloud", "huaweicloud-py")
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
    hwm, hw = _mb("huaweicloud", "huaweicloud-py")
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


def _erlang_urls(v: str) -> Dict[str, List[str]]:
    """
    Erlang/OTP Windows 便携包下载 URL 列表（R1 多源故障转移模式）。

    入参 v: str   OTP 版本号，如 "27.3.4.1"
    返回: {"Windows": [加速器…, GitHub 官方]}；非 Windows 返回 {}

    说明（2026-10-08 实测）：
      - 只有 GitHub Releases 发 otp_win64_<v>.zip 这种**免安装便携包**，
        解压后就是一个 OTP 根目录（bin/erl.exe）—— 不需要跑安装器、不改注册表；
      - 国内镜像没有它：`repo.huaweicloud.com/erlang/` 只有源码 tarball，
        `mirrors.tuna.tsinghua.edu.cn/erlang/` 直接 404（带 UA 实测）；
      - 所以只能 _gh_accelerated（加速器在前、末位裸 GitHub）。
      - Windows 之外（官方包是 .tar.gz 源码）本工具不由它承担，返回空。
    """
    if CURRENT_OS != "Windows":
        return {}
    return {"Windows": _gh_accelerated(
        f"https://github.com/erlang/otp/releases/download/OTP-{v}/otp_win64_{v}.zip")}


def _erlang_cv(v: str) -> ComponentVersion:
    return ComponentVersion(version=v, url_map={}, url_list_map=_erlang_urls(v),
                            archive_map={"Windows": "zip"})


def fetch_erlang_versions() -> List[ComponentVersion]:
    """
    抓取 Erlang/OTP 版本列表（GitHub Releases，只取带 otp_win64_<v>.zip 的 tag）。

    返回: ComponentVersion 列表，按版本号倒序，最多 8 个。

    异常: GitHub API 不可用时抛 RuntimeError，调用方降级到离线默认清单。

    说明: OTP 的 tag 形如 OTP-27.3.4.1，资产名 otp_win64_27.3.4.1.zip。
          只认**有 Windows 便携包**的 tag —— 没有资产的 tag 列出来就是让用户白点一次。
    """
    data = _github_api_json(
        "https://api.github.com/repos/erlang/otp/releases?per_page=30", timeout=20)
    if not isinstance(data, list):
        raise RuntimeError("Erlang 版本列表抓取失败：GitHub Releases 返回异常")
    rx = _re.compile(r"^otp_win64_(\d+(?:\.\d+)*)\.zip$")
    found: List[str] = []
    for rel in data:
        if not isinstance(rel, dict) or rel.get("prerelease"):
            continue
        for asset in (rel.get("assets") or []):
            name = (asset or {}).get("name") or ""
            m = rx.match(name)
            if m:
                found.append(m.group(1))
    if not found:
        raise RuntimeError("Erlang 版本列表抓取失败：最近的 release 里没有 Windows 便携包")
    return [_erlang_cv(v) for v in _sort_semver_desc(set(found))[:8]]


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
                   for b in _mb("ustc", "nju", "tuna", "bfsu")]
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
    中科大当时只是 302 跳回 dl.google.com（本机对 dl.google.com TLS 握手失败）。

    2026-10-06 复测推翻了"中科大只是 302"这条：`mirrors.ustc.edu.cn/golang/go1.24.6.windows-amd64.zip`
    直接回 206 且速度 3.9 MB/s，是真正可用的镜像 —— 2026-09 那次多半是探测没带 Range
    或撞上它跳转的时机。所以现在三家：南大 5.3 > 中科大 3.9 > 阿里 0.4 MB/s。
    阿里虽然最慢但保留 —— 0.4 MB/s 也比官网在 TLS 上握手失败强。
    """
    # 按实测速度排（2026-10-06 取样 3MB）：nju 5.3 > ustc 3.9 > aliyun 0.4 MB/s
    mirror_bases = [f"{b}/golang" for b in _mb("nju", "ustc", "aliyun")]
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
                    _mb("huaweicloud", "tencent", "nju", "huaweicloud-py")]
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
    # 按 2026-10-06 实测速度排：huawei 26.7 > ustc 11.4 > tuna 8.0 > tencent 5.9
    # ≈ bfsu 5.6 > nju 3.6 > huawei-py 1.8 > aliyun 0.3 MB/s
    mirror_bases = [f"{b}/jenkins/war-stable/{v}" for b in
                    _mb("huaweicloud", "ustc", "tuna", "tencent", "bfsu", "nju",
                        "huaweicloud-py", "aliyun")]
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

    # **Windows 有官方 zip，不要再装generic-unix**（2026-10-06 真机踩出来的）：
    # 原来 Windows 键根本不配URL，于是 urls_for_current() 在 Windows 上返回空
    # ——而子代理装包时回退到 url_list_map 里的 generic-unix，
    # 那个包的 sbin/ 下**全是无扩展名的脚本**（rabbitmq-server 而不是 .bat），
    # Windows 上根本跑不起来。产品登记的 commands 写的是 .bat，与包内容不符。
    # 实测华为云两个子域的 rabbitmq-server-windows-<v>.zip 都是 200。
    win_urls = [f"{base}/rabbitmq-server-windows-{v}.zip" for base in mirror_bases]
    win_github = (f"https://github.com/rabbitmq/rabbitmq-server/releases/download/"
                  f"v{v}/rabbitmq-server-windows-{v}.zip")
    win_urls += _gh_accelerated(win_github)
    return {
        "Windows": win_urls,
        "Linux":   urls,
        "Darwin":  urls,
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
                    _mb("huaweicloud", "tuna", "tencent", "bfsu", "nju", "ustc", "aliyun")]
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
                    _mb("huaweicloud", "tencent", "ustc", "bfsu", "tuna", "nju", "aliyun")]
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
                    _mb("huaweicloud", "nju", "tuna", "tencent", "ustc", "bfsu", "aliyun")]
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
                    _mb("huaweicloud", "tencent", "bfsu", "nju", "tuna", "ustc", "aliyun")]
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
    # 按 2026-10-06 实测速度排：huawei 28.6 > nju 9.8 > huawei-py 7.4 ≈ tuna 7.3
    #≈ bfsu 7.3 > tencent 6.7 > ustc 3.4 > aliyun 0.3 MB/s（阿里云垫底，挪到最后）
    mirror_bases = [f"{b}/apache/incubator/seata/{v}" for b in
                    _mb("huaweicloud", "nju", "huaweicloud-py", "tuna",
                        "bfsu", "tencent", "ustc", "aliyun")]
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


def _semver_key(v: str):
    """语义版本排序键：逐段转 int，转不了的（如 "21.0.4-beta"）退到最小档。"""
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def _sort_semver_desc(vs) -> list:
    return sorted(set(vs), key=_semver_key, reverse=True)


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
    "erlang": fetch_erlang_versions,
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
COMPONENT_CATEGORIES = ("开发环境", "开发软件", "一键启停", "其它软件")

# 组件 → 分类。**这是唯一一处**分类登记表：新增组件只在这里加一行，
# build_components() 末尾统一赋值到 Component.category，界面自动出现在对应 Tab。
#   开发环境：装完进 PATH、直接用来写 / 编译 / 打包代码
#   开发软件：本地跑起来给项目当依赖的服务（数据库 / 消息队列 / 注册中心 / 搜索）
#   一键启停：卡片上有「启动/停止」按钮的组件 —— 成员由 LAUNCH_KEYS 派生，不写在这里
#   其它软件：不参与写代码的容器、编排外围
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
    # erlang 是隐藏组件（不出现在界面），但分类表是"每个 key 都要有"的硬约束，
    # 漏登记会在 build_components() 末尾直接 KeyError —— 所以它也得在这一行。
    "erlang": "开发环境",
}

# 允许并存多版本、可切换生效版本的组件（2026-09-29 与用户确认，固定 7 个，别自行扩大）。
# 排除 conda：installer_mode 组件装在固定目录、卸载也不删目录，"每版本一目录"的前提不成立。
# 排除服务型组件（mysql/tomcat/nacos/es/…）：多版本的真矛盾是端口与数据目录，不是环境变量。
# 2026-06-06 起：**全部组件都是多版本**（用户要求，26/26）。
# 原先只有 7 个（jdk/python/node/go/maven/gradle/bun），靠这个白名单把其余 19 个挡在
# 多版本逻辑之外。挡的理由是 R3.9「非多版本组件零影响」—— 那条规则是**改造期**的保护措施：
# 担心一次改 19 个组件的状态胶囊 / 卸载目标 / 绿勾逻辑会连带出事。
# 现在改造已完成、护栏也补齐，白名单没有存在意义了，保留它只会让 19 个组件的用户
# 拿不到"多装几个版本、随时切回去"的能力。
#
# 改成全量的前提（都已满足）：
# · 26 个组件**本来就有 2-4 个版本的候选清单**，能装多个版本这件事不需要额外工作；
# · 切换语义统一为"改 XXX_HOME + 收敛 PATH"，**不动已装目录**，随时能切回去；
# · 带数据的中间件（mysql/kafka/postgresql/elasticsearch 等）的数据目录在 data_note 里
#   写清了，切换与卸载都不会动它。
# 真正的"多版本"能力与"厂商是否支持同机多实例"无关 —— 我们只是管理各版本的安装目录
# 与生效版本指针，不负责让它们同时跑。
MULTI_VERSION_KEYS = set()          # 空集 = 全部组件都走多版本逻辑（Component.multi_version 恒为 True）


# 端口策略取值域。写成一个常量而不是靠文档列举，是因为取值写错不会报错、
# 只会静默走"不改端口"分支——那正是 §5 要避免的"假装安全地改了配置"。
PORT_WRITEBACKS = ("cli_only", "cli_flag", "conf_copy")

# 停止手段取值域。port_lookup 是计划二新增：厂商自带停止手段不可用
# （Nacos 的 shutdown.cmd 按进程名 taskkill /F，会杀到用户自己起的实例；
#  ActiveMQ 的 stop 经 JAAS/JMX 且受 conf 副本影响），所以停止 = 端口反查 PID。
# 取值写错同样不会报错、只会走错分支，所以和 PORT_WRITEBACKS 一样钉成常量。
STOP_KINDS = ("pid", "shutdown_command", "port_lookup")


@dataclass
class LaunchSpec:
    """一个组件"怎么被拉起来"的描述符。端口策略见 port_writeback 三种取值；
    厂商官方文件在任何策略下都不被修改（conf_copy 写的是 data 目录里的副本）。"""

    # 按 OS 键的启动 argv 模板。允许这些占位符：
    #   {java} {war} {home} {data_dir} {port} {log_file}
    commands: Dict[str, List[str]]
    # **第二个要拉起的进程**，用于"一个组件由两个进程组成"的情况。
    #
    # 2026-10-06 为 rocketmq 加的：实测它有**两个**必须都在跑的进程 ——
    #   namesrv（`bin\mqnamesrv.cmd`，端口 9876）与 broker（`bin\mqbroker.cmd`，
    #   端口 10909/10911）。只起 namesrv 的话 extra_ports 里的 10909/10911
    #   **永远不监听** → start() 会卡在"整簇都在听才算起来"直到超时，
    #   表现为"点启动没反应"。
    #
    # 顺序：先起 commands，再起这个（broker 要向 namesrv 注册）。
    # 停止：走 port_lookup 的三重闸，一个端口簇覆盖两个进程。
    extra_processes: List[Dict[str, List[str]]] = field(default_factory=list)
    # **启动脚本会留下、而停止手段管不到的辅助进程**的映像名（与 extra_processes 不同：
    # 那个是"我们要多起的进程"，这个是"厂商脚本自己留下、我们停不掉也不该停的进程"）。
    # 真机 2026-10-07 rabbitmq：`rabbitmqctl stop` 只停 server，Erlang 的 epmd.exe 一直活着。
    # 它不监听业务端口 → 按簇判定会正常报"已停止"；但它的工作目录还留在版本目录里，
    # Windows 上让后续 `rmdir` 失败，用户于是看到永久"卸载不了"。
    # 这个清单**只用于停止后提示**：绝不自动结束别人的进程（要结束由用户决定）。
    leftover_processes: tuple = ()
    # 停止手段："pid" = 我们就是服务进程（Jenkins）；
    #           "shutdown_command" = 有可用的正规关闭脚本（本期无人使用，留作计划三位置）；
    #           "port_lookup" = 没有可靠厂商手段，停止走端口反查（Nacos / ActiveMQ）
    stop_kind: str = "pid"
    shutdown_commands: Dict[str, List[str]] = field(default_factory=dict)
    # 端口簇：主端口 + 派生偏移。本期 jenkins 只有主端口，offsets 为空。
    main_port: int = 0
    port_offsets: tuple = ()
    port_search_span: int = 99
    # 界面打开控制台用：http://127.0.0.1:{port}{console_path}
    console_path: str = "/"
    # 探活路径。None 表示只做 TCP 判活，不发 HTTP。
    health_path: Optional[str] = None
    # 前置组件 key。Jenkins 需要 JDK。
    needs: tuple = ()
    # JDK 最低大版本。spec §2.4 第 5 项实测前必须留 None，
    # 非 None 才能启用版本门控；填数字前请先拿到实测结论。
    min_java_major: Optional[int] = None
    # 要注入的数据目录环境变量名（Jenkins: JENKINS_HOME）。None 表示不注入。
    data_dir_env: Optional[str] = None
    # 拉起后多久内必须开始监听，超时判启动失败。
    startup_timeout: int = 120
    # 端口策略（spec 计划二 §3.1）：
    #   cli_only  —— 只有命令行 flag 能改端口（Jenkins），不碰任何文件
    #   cli_flag  —— 端口作为命令行参数透传给厂商脚本（Nacos --server.port），不碰任何文件
    #   conf_copy —— 把官方 conf 整目录拷进 data 目录，端口只写这份副本（ActiveMQ）
    # 取值域见 PORT_WRITEBACKS；写错不会报错，只会静默不改端口，所以有 §Task1 的取值域用例。
    port_writeback: str = "cli_only"
    # 独立基准端口：与主口没有固定偏移、需要各自找空的口（ActiveMQ 的 61616）。
    # 派生口（Nacos 的 9848/9849）不放这里，走 port_offsets。
    extra_ports: tuple = ()
    # 额外注入的环境变量。值支持 {home} {data_dir} {conf_dir} {port} 占位，
    # 因为 ActiveMQ 的 ACTIVEMQ_CONF/DATA 要等端口定了、副本建好了才写得出最终值。
    extra_env: Dict[str, str] = field(default_factory=dict)
    # 启动确认弹窗里的风险说明文本（监听地址、默认凭据一类）。
    risk_note: str = ""
    # 启动成功后打进组件日志的**登录凭据**（2026-10-06 用户要求）。
    # 与risk_note 分开：risk_note 是"启动前该知道的风险"，这个是"启动完要拿去登录的东西"——
    # 两者时机不同、读者也不同，混在一起会让用户在确认框里翻找登录信息。
    #
    # 语义是**厂商出厂默认值**，不是本机实际值。厂商在首次启动时随机生成密码的
    # （Jenkins 的 initialAdminPassword）不在这里写死，由 credentials_for() 读出来。
    credentials_hint: str = ""
    # 卸载确认里必须显示的数据去处。Nacos 的 derby 在版本目录内（卸载即连带删除），
    # ActiveMQ 的数据与 conf 副本在 ~/.env-tools 下（卸载后保留）——
    # 一句"数据会被清理"含混带过就是拿计划一的承诺说假话。
    data_note: str = ""
    # 启动前的**前置准备**命令（如 kafka 的 KRaft `format`）。
    # {java}/{home}/{data_dir}/{port} 会被替换；要在 spawn 之前跑完。
    #
    # 为什么需要这个字段：Kafka 4.x 是纯 KRaft，不 format 就直接起不来
    # （实测 `No readable meta.properties files found.`）。而 format 必须先有
    # 一个持久化的 cluster.id —— 换 uuid 会 `rc=1 Invalid cluster.id`，
    # 所以这个命令的产物要落在 data_dir 里由我们管。
    pre_start: List[str] = field(default_factory=list)
    # 前置依赖（rabbitmq → Erlang）。为空表示不需要外部运行时。
    prereq: Optional["PrereqSpec"] = None
    # **协议级服务探活**（不是 HTTP）。
    #
    # 为什么需要（2026-10-06 真机实测）：有些组件的端口说的是二进制协议，
    # 用 HTTP 探必然失败 —— kafka 的 9092 是 Kafka 协议，
    # 请求它会得到 `RemoteDisconnected`（实测），HTTP 判据对它完全无效。
    # 而 kafka 恰恰是最需要「端口在听 ≠ broker 可服务」这个验证的组件。
    #
    # 语义：argv 前缀 + {port} 占位符；退出码 0 = 服务真的可服务。
    # 演练层（bt_real_machine_drill.py）在 HTTP 判据不适用时改用它。
    service_probe: List[str] = field(default_factory=list)


@dataclass
class PrereqSpec:
    """组件启动前必须先就位的前置依赖（目前只有 rabbitmq 需要 Erlang）。

    2026-10-06 实测：rabbitmq 的 Windows zip（31MB，华为云已同步）**不含 Erlang**，
    `rabbitmq-server.bat` 开头就 `if not exist "!ERLANG_HOME!\\bin\\erl.exe" exit /B 1`。
    官方没有免Erlang 的 Windows 产物（Linux 有 zero-dependency RPM，Windows 无对应）。
    版本必须联动：rabbitmq 4.0.9 要Erlang 26.2~27.x，但26 已 EOL ⇒ 实际必须 27.x；
    3.13.7 只能配 26.x —— **两个 rabbitmq 版本不能共用一个 Erlang**。
    """
    # 前置依赖自身的组件 key（复用我们已有的下载/版本清单，Erlang 以此登记）
    key: str
    # 满足条件：宿主上的可执行文件存在（用于快速判定"已装"）
    probe: str = ""
    # 不满足时给用户看的一句话（说清为什么需要它、装在哪）
    install_hint: str = ""


# kafka 的启动类与探活类都在 jar 里，路径写 libs/*（通配符由 JVM 展开）。
# **不能用厂商 .bat** —— 实测 `kafka-run-class.bat:188` 把 109 个 jar 拼成一行，
# 我们框架的真实安装路径下整行 8650 字符，**超过 cmd.exe 的 8191 上限**，
# 直接 `rc=255 输入行太长`。而且 `kafka-server-start.bat:28` 调 `wmic os get osarchitecture`，
# wmic 在 Win11 已弃用（本机沙箱直接拦截）。
KAFKA_MAIN_CLASS = "kafka.Kafka"
# 类名**以真机实测为准**（2026-10-06）：我第一版按探针报告写成
# `org.apache.kafka.tools.StorageTool`，实测直接
# `ClassNotFoundException: org.apache.kafka.tools.StorageTool`——
# jar 里的真实路径是 `kafka/tools/StorageTool.class`（扫 jar tf 确认的）。
KAFKA_STORAGE_TOOL = "kafka.tools.StorageTool"
KAFKA_API_VERSIONS = "org.apache.kafka.tools.BrokerApiVersionsCommand"
# rocketmq 的 CLI 入口（扫 jar tf 确认：rocketmq-tools-5.3.1.jar 里
# org/apache/rocketmq/tools/command/MQAdminStartup.class）。
# 用它跑 `clusterList -n <namesrv>` 就能问namesrv「集群里有谁」——
# 答得上来说明 namesrv 与 broker 都真的在服务，而不只是端口在听。
ROCKETMQ_ADMIN = "org.apache.rocketmq.tools.command.MQAdminStartup"


LAUNCH_OF: Dict[str, LaunchSpec] = {
    "jenkins": LaunchSpec(
        commands={os_name: ["{java}", "-jar", "{war}", "--httpPort={port}"]
                  for os_name in ("Windows", "Linux", "Darwin")},
        stop_kind="pid",
        main_port=8080,
        console_path="/",
        health_path="/login",
        needs=("jdk",),
        # 2026-10-08 实测后填 11（原来是 None = 不查版本，只查"有没有 JDK"）。
        # 实测证据（对装在本机的 jenkins 2.580.1 拆包读的，不是按惯例推的）：
        #   META-INF/MANIFEST.MF 里写着 `Java-Version: 11`，
        #   包内唯一那个顶层 .class 的 major version = 55（= Java 11）。
        # 填 11 的效果：宿主上只有 JDK 8 时会触发自动装一个够用的 JDK，
        # 而不是让 Jenkins 用旧 JVM 起不来（那时报的是 UnsupportedClassVersionError，
        # 用户完全看不出是 JDK 版本问题）。本机的 17/21 都不会被误伤。
        min_java_major=11,
        data_dir_env="JENKINS_HOME",
        startup_timeout=180,
        risk_note=(
            "Jenkins 会监听本机 8080（默认对局域网开放），首次启动是解锁向导；"
            "初始管理员密码在 JENKINS_HOME 的 secrets 目录下。"
            "只想本机访问的话，把命令里的监听地址改成 127.0.0.1 再启动。"
        ),
        credentials_hint=(
            "控制台：http://127.0.0.1:8080/　用户名：admin　"
            "密码：首次启动时随机生成，写在 "
            "~/.env-tools/jenkins-data/secrets/initialAdminPassword"
            "（启动日志里会打印出来）。首次登录后请立刻在「管理 Jenkins → 安全」里改掉。"
        ),
        data_note=("任务、插件与配置都在 ~/.env-tools/jenkins-data 下，卸载只删版本目录、"
                   "这份数据会保留；要彻底清理请手动删除该目录。"),
    ),
    "nacos": LaunchSpec(
        # 实测（2026-10-05，nacos-server-2.3.2）：startup.cmd 的 %COMMAND% 是前台 java，
        # 末尾带 %* → --server.port 直接透传给 Spring Boot，优先级高于 application.properties，
        # 所以 Nacos 一个文件都不改。-p 是 embedded storage，不是端口，别写错。
        commands={"Windows": ["{home}/bin/startup.cmd", "-m", "standalone",
                              "--server.port={port}"],
                  "Linux": ["{home}/bin/startup.sh", "-m", "standalone",
                            "--server.port={port}"],
                  "Darwin": ["{home}/bin/startup.sh", "-m", "standalone",
                             "--server.port={port}"]},
        stop_kind="port_lookup",
        main_port=8848,
        port_offsets=(1000, 1001),      # gRPC 口由 server.port 派生（包内无对应属性可回写）
        port_search_span=99,
        port_writeback="cli_flag",      # 计划二的代码片段漏了这行：--server.port 就是 cli_flag
        console_path="/nacos",           # A3 真机实测：conf/application.properties:19
                                          # server.servlet.contextPath=/nacos —— 不在根路径
        # A3 真机实测（2026-10-05）：控制台在 /nacos，该路径返回可达响应。
        # health_path 从 None 填成实测值——spec §9 写明"None 不是不测，是尚未实测"。
        # health_path 保持 None：探活路径与 console_path 相同（都是 /nacos）。
        # 2026-10-06 教训：曾把它填成 "/nacos"，而 console_url 已经含 /nacos，
        # 上层再拼一次就成了 /nacos/nacos → 稳定 404 → 演练误报"控制台不可达"。
        # 这个字段只在"探活路径 ≠ 控制台路径"（Jenkins 那种 /login）时才有意义。
        health_path=None,
        needs=("jdk",),
        min_java_major=8,
        data_dir_env=None,               # 厂商无外移开关：-Dnacos.home 固定在安装目录内
        startup_timeout=90,
        risk_note=(
            "Nacos 默认监听 0.0.0.0（对局域网开放），默认未开启鉴权，"
            "控制台默认账号 nacos/nacos。"
            "运行数据（derby）落在安装目录内的 data/ 下：卸载组件会连带删除它，"
            "这一点与 Jenkins 不同（Jenkins 的数据在 ~/.env-tools 下，卸载后保留）。"
        ),
        credentials_hint=(
            "控制台：http://127.0.0.1:8848/nacos　用户名：nacos　密码：nacos"
            "（2.3.2 出厂默认，standalone 模式默认不开鉴权）。"
            "改密码：Nacos 控制台右上角「修改密码」，或改 conf/application.properties 里的 "
            "nacos.core.auth.default.token.secret（改了要重启生效）。"
        ),
        data_note=("运行数据（derby）在安装目录内的 data/ 下，卸载会连带删除；"
                   "要保留数据请先把它复制到 ~/.env-tools 之外。"),
    ),
    "activemq": LaunchSpec(
        # 实测（2026-10-05，apache-activemq-6.3.2）：
        #   控制台口 conf/jetty-spring.properties:35 jetty.http.port=8161
        #   broker 口  conf/activemq.xml:178        name="openwire" tcp://0.0.0.0:61616
        #   bin/activemq.bat:74/76 "未设才默认" + :99 传 -Dactivemq.conf/-Dactivemq.data
        # 所以端口只写 data 目录里的 conf 副本，官方目录零改动。
        # A5/A6 真机实测（2026-10-05, apache-activemq-6.3.2）：`activemq.bat` 把 %* 透传给
        # activemq.jar 的主类，它只认自己的一组 task（backup/browse/create/start/stop/…），
        # **没有 console** —— 传 console 会打印 Usage 然后自己退出，两个口都不监听。
        # `start` = "Creates and starts a broker using a configuration file"，正是我们要的。
        # （计划初稿写的是 console，是没核实包内 task 表的猜测；真机一跑就露馅。）
        commands={"Windows": ["{home}/bin/activemq.bat", "start"],
                  "Linux": ["{home}/bin/activemq", "start"],
                  "Darwin": ["{home}/bin/activemq", "start"]},
        stop_kind="port_lookup",
        main_port=8161,
        port_offsets=(),
        extra_ports=(61616,),
        port_search_span=99,
        port_writeback="conf_copy",     # 计划给的片段漏了这行，缺了会退回 cli_only（端口根本改不动）
        extra_env={"ACTIVEMQ_CONF": "{conf_dir}", "ACTIVEMQ_DATA": "{data_dir}"},
        console_path="/admin",           # A3 真机实测：控制台在 /admin 且返回可达响应
        health_path=None,                # 同上：探活路径 = console_path（/admin），不重复填
        needs=("jdk",),
        min_java_major=17,
        data_dir_env=None,
        startup_timeout=60,
        risk_note=(
            "ActiveMQ 默认监听 0.0.0.0，Web 控制台默认账号 admin/admin"
            "（conf/users.properties 实测）。首次启动会在 ~/.env-tools/activemq-data/conf"
            "建立配置副本，此后副本是权威：换版本不会自动合并厂商新增默认项。"
        ),
        credentials_hint=(
            "控制台：http://127.0.0.1:8161/admin　用户名：admin　密码：admin"
            "（6.3.2 出厂默认，见 conf/users.properties）。"
            "改密码：编辑 ~/.env-tools/activemq-data/conf/users.properties 里的 admin 行"
            "（注意冒号后面是**明文密码**，厂商为兼容旧版本不做哈希），改完重启生效。"
        ),
        data_note=("数据与配置副本在 ~/.env-tools/activemq-data（含 conf 副本、broker 存储与日志），"
                   "卸载只删版本目录，这份会保留；要彻底清理请手动删除该目录。"),
    ),

    # ================= 2026-10-06 新接入的 6 个 =================
    # 每一处的值都来自当天的真机实测（探针报告见 .workbuddy/verify_*.md），
    # 不是按厂商惯例推的。已实测踩过的坑写在注释里，改之前先读。

    "rocketmq": LaunchSpec(
        # 实测（2026-10-06）：入口**必须**用 bin\mq*.cmd（一级入口，开头检查
        # ROCKETMQ_HOME，没设就 EXIT /B 1），不能用 bin\run*.cmd ——后者是
        # 纯 %* 透传、不设环境变量，而 BrokerStartup 靠它找 conf/broker.conf，
        # 直接跑会 FileNotFoundException。**厂商脚本分两级，用错必炸。**
        commands={"Windows": ["{home}/bin/mqnamesrv.cmd"],
                  "Linux":   ["{home}/bin/runserver.sh"],
                  "Darwin":  ["{home}/bin/runserver.sh"]},
        # **ROCKETMQ_HOME 必设**（2026-10-06 用户报"显示启动成功实际起不来"后定位）：
        # bin\mqnamesrv.cmd 开头就 `if not exist "%ROCKETMQ_HOME%..." EXIT /B 1`，
        # 缺它时脚本直接退出，端口永远不监听 → 表现为
        #     「120 秒内端口 9876/10909/10911 未监听」+ 日志里一句
        #     「Please set the ROCKETMQ_HOME variable in your environment!」
        #
        # **为什么之前的真机演练没暴露这个**（这是验证方法的漏洞，记下来）：
        # 演练时我的 shell 里恰好有 ROCKETMQ_HOME（早期多版本真机测试写进去的），
        # `dict(os.environ)` 把它带上了 → 演练通过。
        # 而用户跑 **exe** 时那个进程没有这个变量 → 立刻失败。
        # → **凡是靠环境变量定位自己的厂商脚本，都必须由我们显式注入**，
        #    绝不能假设"用户环境里恰好有"（同ES 的 ES_HOME/ES_PATH_CONF、
        #    rabbitmq 的 ERLANG_HOME）。
        extra_env={"ROCKETMQ_HOME": "{home}"},
        # broker 是**第二个进程**（实测broker 要向 namesrv 注册才能起，
        # 不起它的话 extra_ports 里的 10909/10911 永远不监听，
        # start() 会卡到超时 → 表现为"点启动没反应"）。
        # 端口全走官方默认（broker.conf 里 **0 处** listenPort，实测），
        # 要改端口得改 conf/container/*.conf 那些模板 —— 不在本期范围。
        extra_processes=[
            {"Windows": ["{home}/bin/mqbroker.cmd"],
             "Linux":   ["{home}/bin/runbroker.sh"],
             "Darwin":  ["{home}/bin/runbroker.sh"]},
        ],
        # 两个角色（namesrv + broker）共用同一个 commands 入口不行 ——
        # broker 要单独一条命令，见下方 broker_commands 的说明。
        stop_kind="port_lookup",
        main_port=9876,
        # 实测 broker 起来后 **10909/ 10911 / 10912 三个端口同时监听**。
        # extra_ports 只列对外协议那两个（10912 是 HA，standlone 单机不需要）。
        extra_ports=(10909, 10911),
        port_search_span=99,
        # 实测 conf/broker.conf 里 **0 处 listenPort**（端口是代码默认值，
        # 只有 conf/container/*.conf 那些容器模板才写）→ 不需要改配置。
        port_writeback="cli_only",
        console_path=None,
        health_path=None,
        # 9876 说 RocketMQ 二进制协议，HTTP 请求它不会得到 HTTP 响应。
        # 用自带 CLI 问 namesrv「集群里有谁」—— 它答得上来才说明
        # **namesrv 与 broker 都真的注册好了**（只探 9876 会漏掉 broker 没起来）。
        service_probe=["{java}", "-cp", "{home}/lib/*",
                       ROCKETMQ_ADMIN, "clusterList", "-n", "localhost:{port}"],
        needs=("jdk",),
        # 实测 bin/mqbroker.cmd:14 有 `if%JAVA_MAJOR_VERSION% lss 17` 分叉
        min_java_major=17,
        data_dir_env=None,
        # 实测 broker 就绪约 25-30 秒（namesrv 约 10 秒）
        startup_timeout=120,
        risk_note=(
            "RocketMQ 默认监听 0.0.0.0（对局域网开放）。**消息数据落在 ~/store，"
            "不在安装目录里** —— 卸载不会删它，要彻底清理请手动删除该目录。"
            "多版本并存时务必给每个版本分开设 storePathRoot，否则两个 broker 抢同一个目录。"
        ),
        data_note=("消息与 commitlog 默认在 **storePathRoot 配置项**指向的位置"
                   "（实测落在 ~/store，不在安装目录内），卸载不会删它。"
                   "多版本并存时务必给每个版本分开设 storePathRoot。"),
        credentials_hint=(
            "**RocketMQ 没有网页控制台** —— 9876 是 namesrv 的二进制协议口，"
            "浏览器打开会连接失败（正常）。"
            "用它自带的命令行工具查看集群，例如："
            "  bin" + chr(92) + "mqadmin.cmd clusterList -n 127.0.0.1:9876"
            "消息数据落在 ~/store（storePathRoot），**卸载不会删它**。"
        ),
    ),

    "nginx": LaunchSpec(
        # 实测：nginx.exe **无参数、前台阻塞** —— 必须后台化否则终端卡死。
        # 停止用 -s stop，**但它的报错不能当失败判据**（见下方 data_note）。
        # **必须显式 -c 指向我们的配置副本**（2026-10-06 真机实测踩出来的）：
        # nginx 找配置的规则是「编译时前缀 + conf/nginx.conf」，
        # 它**不看环境变量、也不看 cwd** —— 我们把端口写进副本之后，
        # 它照样去读安装目录下那份原版（listen 80），于是：
        #     [emerg] bind() to 0.0.0.0:80 failed (10013: ...forbidden...)
        # 端口被占时它报的 10013 就是这个原因（不是权限问题，是那个口真的绑不了）。
        # -c 会**同时影响停止**（nginx -s stop 也要读到 pid 路径），
        # 所以 stop_kind 那侧同样要带上 —— 见 stop 侧的处理。
        # **-p (prefix) 与 -c 都要给**（2026-10-06 真机实测踩出来的）：
        # -c 只决定读哪个配置文件，而**日志与 pid 文件的路径是相对 prefix 算的**
        # （不是相对 cwd、也不是相对 -c 那个文件）。不指prefix 时实测报：
        #     could not open error log file: CreateFile() "logs/error.log" failed
        #     CreateFile() "D:/.../byte-tools/logs/nginx.pid" failed
        #  —— pid 找不到就意味着 **-s stop 根本停不掉**，只剩强杀一条路，
        # 而强杀 master 之后 worker 还活着（多进程结构），会留下占端口的孤儿。
        # prefix 指向 data_dir，日志与 pid 都落在 ~/.env-tools/nginx-data 下。
        commands={"Windows": ["{home}/nginx.exe", "-p", "{data_dir}",
                              "-c", "{conf}"],
                  "Linux":   ["{home}/sbin/nginx", "-p", "{data_dir}",
                              "-c", "{conf}"],
                  "Darwin":  ["{home}/sbin/nginx", "-p", "{data_dir}",
                              "-c", "{conf}"]},
        # **用官方的 nginx -s quit，不用端口反查强杀**（2026-10-06 真机实测）：
        # nginx 是 **master + worker 多进程**结构 —— 强杀 master（= 我们登记的 PID）
        # 之后 **worker 仍然持有 8080**（实测：taskkill 之后端口仍在听、登记删不掉）。
        # `-s quit` 是**优雅停**（vs `stop` 是快停），实测有效。
        # 之前实测它会打 `OpenEvent(...) failed` 却**真的停掉了**、退出码 0——
        # 那条 stderr 是 Windows 版的正常噪音，判「是否停掉」一律看端口。
        # -c 也要带上：pid 文件路径是从配置算出来的，不带就找不到 pid。
        stop_kind="shutdown_command",
        shutdown_commands={"Windows": ["{home}/nginx.exe", "-p", "{data_dir}",
                                       "-c", "{conf}", "-s", "quit"],
                           "Linux":   ["{home}/sbin/nginx", "-p", "{data_dir}",
                                       "-c", "{conf}", "-s", "quit"],
                           "Darwin":  ["{home}/sbin/nginx", "-p", "{data_dir}",
                                       "-c", "{conf}", "-s", "quit"]},
        # **主端口用 8888，而不是官方的 80，也不用 8080**（2026-10-06 用户拍板 + 演练修正）。
        #
        # 不用 80：Windows 上 80 几乎总被 **System（PID 4，http.sys 内核服务）**占着
        # ——那是 IIS / WinRM 的公共绑定，绑不了也杀不掉（WinError 5）。
        # 按「不平移 + 结束占用者」规则，nginx 在很多 Windows 机器上必然启动失败。
        #
        # 不用 8080（**这个坑是我自己踩的**）：8080 在本项目里已经被
        # **jenkins / tomcat / activemq** 三个组件占着。我第一版改到 8080 等于给
        # 它们埋雷 —— 演练时 jenkins 被 nginx 抢走 8080，探到的是 nginx 而不是
        # Jenkins，症状是"Jenkins 显示起来了但打不开"。端口冲突不是"谁后启动谁赢"，
        # 是**两个都坏**。
        # 8888 是 nginx 生态的惯例（Apache 时代就用它），与本项目其它组件不冲突。
        #
        # 这不违反「不平移」原则：那个原则的原因是"外部客户端配置里写死了端口，
        # 平移会造成连不上"；nginx 的 80 没有这种绑定（它是我们自己声明的默认端口）。
        main_port=8888,   # 见上：80 被 http.sys 占、8080 被 jenkins/tomcat/activemq 占
        port_search_span=99,
        port_writeback="conf_copy",
        # **nginx 是有可点控制台的**（2026-10-08 用户报「启动后访问不了页面」后改正）：
        # 它的根路径就是站点首页（`root html` + 默认 index.html），
        # 写成 None 会走 _has_console() 的"没有网页控制台"分支 —— 卡片上不给
        # 「打开控制台」按钮，用户只能自己猜端口（他猜的是 8080，而这里是 8888）。
        # 控制台路径就是根路径，所以填 "/"。
        console_path="/",
        health_path=None,
        needs=(),
        min_java_major=None,
        data_dir_env=None,
        # 实测起后 2-3 秒 HTTP 200
        startup_timeout=30,
        risk_note=(
            "**本工具把 nginx 放在 8888**（官方默认 80，而 80 在 Windows 上被系统"
            "内核服务 System/http.sys 占着绑不了也杀不掉；8080 则归 Jenkins 与 Tomcat） —— 因为 Windows 上 80 端口"
            "几乎总被系统内核服务 System（http.sys，IIS/WinRM 共用）占着，"
            "那个进程绑不了也杀不掉。实际端口以启动日志里那行为准。"
            "nginx **对局域网开放**（0.0.0.0）；只想本机访问的话，"
            "把 ~/.env-tools/nginx-data/conf/nginx.conf 里的 listen 改成 127.0.0.1。"
        ),
        data_note=("配置副本与日志都在 ~/.env-tools/nginx-data 下（conf/ 与 logs/），"
                   "卸载只删版本目录，这份会保留。"
                   "实测坑：logs/nginx.pid 里是 **worker PID**，与真正监听端口的 master "
                   "不是同一个 —— 所以停止只能走端口反查，不能按 pid 文件里的 PID 杀。"),
        credentials_hint=(
            "**nginx 没有管理控制台** —— 8080 是它提供网站服务的端口，"
            "根路径返回的是默认欢迎页（html/index.html）。"
            "站点内容在配置副本 ~/.env-tools/nginx-data/html/，"
            "改完执行 `nginx -s reload` 生效。"
        ),
    ),

    "kafka": LaunchSpec(
        # **不能用厂商 .bat**（实测两条硬理由）：
        #   ① kafka-run-class.bat:188 把 109 个 jar 拼成一行，我们真实安装路径下
        #      整行 8650 字符 > **cmd.exe 的 8191 上限** → rc=255「输入行太长」；
        #   ② kafka-server-start.bat:28 调 `wmic os get osarchitecture`，
        #      wmic 在 Win11 已弃用（本机沙箱直接拦截）。
        # 直接 spawn java：-cp 的 `libs/*` 通配符由 JVM 展开，不受 8191 限制。
        # 实测这样跑 Popen.pid 就是监听 9092 的 java 进程 → pid_role=server。
        commands={"Windows": ["{java}", "-Xmx1G", "-Xms512M",
                              "-Dlog4j2.configurationFile={home}/config/log4j2.yaml",
                              "-Dkafka.logs.dir={data_dir}/logs",
                              "-cp", "{home}/libs/*", KAFKA_MAIN_CLASS, "{conf}"],
                  "Linux":   ["{java}", "-Xmx1G", "-Xms512M",
                              "-Dlog4j2.configurationFile={home}/config/log4j2.yaml",
                              "-Dkafka.logs.dir={data_dir}/logs",
                              "-cp", "{home}/libs/*", KAFKA_MAIN_CLASS, "{conf}"],
                  "Darwin":  ["{java}", "-Xmx1G", "-Xms512M",
                              "-Dlog4j2.configurationFile={home}/config/log4j2.yaml",
                              "-Dkafka.logs.dir={data_dir}/logs",
                              "-cp", "{home}/libs/*", KAFKA_MAIN_CLASS, "{conf}"]},
        # KRaft 必须先 format，否则直接 `No readable meta.properties files found.`
        # （实测 kafka.Kafka 自己不建目录，只有 format 建）
        pre_start=["{java}", "-cp", "{home}/libs/*", KAFKA_STORAGE_TOOL,
                   "format", "--standalone", "-t", "{cluster_id}", "-c", "{conf}",
                   "--ignore-formatted"],
        stop_kind="pid",
        main_port=9092,
        # 实测 9093 是 KRaft controller 的监听口，与 9092 同时起。
        # **只探主口会把「controller 没起来」显示成运行中**。
        extra_ports=(9093,),
        port_search_span=99,
        # conf_copy：端口全走命令行默认值（实测 --override 改端口会半死），
        # 但 log.dirs 必须改 —— 官方默认 /tmp/... 在 Windows 落 C:////tmp////，
        # 不在安装目录也不在数据目录，卸载删不掉、多版本会抢目录。
        port_writeback="conf_copy",
        console_path=None,
        health_path=None,
        # 9092 说 Kafka 二进制协议，HTTP 请求得到 RemoteDisconnected（实测），
        # 所以只能用 kafka 自带的 API 工具做判据。
        # 它真的在问 broker"你支持哪些 API 版本"——答得上来才算真的可服务。
        service_probe=["{java}", "-cp", "{home}/libs/*",
                       KAFKA_API_VERSIONS, "--bootstrap-server", "localhost:{port}"],
        needs=("jdk",),
        # 实测 jar 内 469 个 class 的 major version 全部 = 61（即 Java 17）
        min_java_major=17,
        data_dir_env=None,
        # 实测端口就绪 4.3-6.2 秒（9093 恒先于 9092）；给 60s 余量
        startup_timeout=60,
        risk_note=(
            "Kafka 4.x 是 **KRaft 模式，不需要 ZooKeeper**（实测全包 0 处 zookeeper 引用）。"
            "默认监听 0.0.0.0:9092 与 controller 的 9093，**对局域网开放**，"
            "且**没有认证** —— 生产环境务必加 SASL/ACL 或用防火墙挡住。"
            "数据目录（log.dirs）会被我们改到 ~/.env-tools/kafka-data 下，"
            "不在安装目录内。"
        ),
        data_note=("消息数据在 ~/.env-tools/kafka-data/kraft-logs（log.dirs 指向处），"
                   "**不在安装目录里**，卸载不会删它；要彻底清理请手动删除。"
                   "cluster.id 也存在这份数据目录里 —— 换 uuid 会被拒"
                   "（Invalid cluster.id），所以必须复用。"),
        credentials_hint=(
            "**Kafka 没有网页控制台** —— 9092 说 Kafka 二进制协议，"
            "浏览器打开会得到连接失败（正常，不是服务坏了）。"
            "9093 是集群内部通信口，更不对外。"
            "用它自带的命令行工具操作，例如："
            "  bin" + chr(92) + "windows" + chr(92) + "kafka-topics.bat --bootstrap-server localhost:9092 --list"
        ),
    ),

    "tomcat": LaunchSpec(
        # 实测 30 次启停：startup.bat 是薄壳（:56 call catalina.bat start），
        # 内部 `start "Tomcat"` 另开控制台窗口后 cmd.exe 立即退出 → pid_role=server
        # （登记的 cmd 进程 0.18s 就死了，java 是孙进程，要靠 netstat 反查）。
        commands={"Windows": ["cmd", "/c", "{home}/bin/startup.bat"],
                  "Linux":   ["{home}/bin/startup.sh"],
                  "Darwin":  ["{home}/bin/startup.sh"]},
        # 实测 shutdown 是**真发信号**：连 8005 发 SHUTDOWN（catalina.bat:322→352）。
        # 比 port_lookup 可靠 —— 但 8005 不通时 rc=1（响亮失败），仍要回查端口。
        stop_kind="shutdown_command",
        shutdown_commands={"Windows": ["cmd", "/c", "{home}/bin/shutdown.bat"],
                           "Linux":   ["{home}/bin/shutdown.sh"],
                           "Darwin":  ["{home}/bin/shutdown.sh"]},
        # **8081 而不是 8080**（2026-10-06 干净环境演练发现）：
        # 8080 已经被 **jenkins** 占着（它先接入）。端口冲突不是"谁后启动谁赢"，
        # 是**两个都坏** —— 演练时 jenkins 被顶掉、探到的是 tomcat，
        # 症状是"Jenkins 显示起来了但打不开"，而 tomcat 自己看起来也正常。
        # Tomcat 官方默认是 8080，这里改成 8081 并在 risk_note 里说明。
        main_port=8081,
        # 8005 是 shutdown 端口。**必须一起改**（实测：只改主端口时若另一实例
        # 占着 8005，新实例 bind 失败自杀，而 shutdown.bat 会杀掉 8005 的真正
        # 持有者并返回 rc=0 —— 看起来完全成功）。
        extra_ports=(8005,),
        port_search_span=99,
        # 端口只在 conf/server.xml 里，**没有 CLI flag**
        port_writeback="conf_copy",
        console_path=None,
        health_path=None,
        needs=("jdk",),
        # 实测 10.1.60 需 11+（RUNNING.txt:22）
        min_java_major=11,
        # CATALINA_HOME 必须显式设：startup.bat:24 用 %cd% 而非脚本路径推，
        # cwd 不对会**静默失败**（rc=0、0.13s、零进程零端口）
        data_dir_env="CATALINA_BASE",
        startup_timeout=30,
        risk_note=(
            "Tomcat 监听 0.0.0.0:**8081** 与 shutdown 口 8005，**对局域网开放**。"
            "（官方默认是 8080，但本工具里 8080 归Jenkins —— 端口冲突不是谁后启动谁赢，"
            "是两个都坏，所以这里分开。）"
            "**启动会弹出一个黑色控制台窗口**（catalina.bat:315 硬编码 start \"Tomcat\"，"
            "无参数可压制）—— 这是厂商行为，不是出故障。"
            "两个端口冲突时本工具会结束占用者；shutdown 端口 8005 被占时，"
            "新实例会起不来（HTTP 502），属正常拦截。"
        ),
        data_note=("**部署的 web 应用在 ~/.env-tools/tomcat-data/webapps/ 下（生效的那份）**："
                   "启动时 CATALINA_BASE 指向 tomcat-data，Tomcat 的 apphost 就是 "
                   "tomcat-data/webapps —— 安装目录里那份 webapps/ 只在首次启动时被同步过来"
                   "（只补缺、不覆盖你改过的文件）。卸载组件不删 tomcat-data，"
                   "要彻底清理请手动删除该目录。"
                   "配置副本在 ~/.env-tools/tomcat-data/conf（server.xml 副本，端口改动只写它）。"),
        credentials_hint=(
            "**Tomcat 没有管理控制台** —— 8081 用来跑你部署的 web 应用，"
            "根路径返回 404 是正常的（没放任何应用）。"
            "把 WAR 放进 ~/.env-tools/tomcat-data/webapps/ 后访问 "
            "http://127.0.0.1:8081/应用名/（放安装目录那份不生效 —— CATALINA_BASE 不在那）。"
            "部署后别忘了解压产物也在 webapps/ 下。"
        ),
    ),

    "elasticsearch": LaunchSpec(
        # 实测：-E 命令行覆盖可用（ServerCli extends EnvironmentAwareCommand），
        # **一个配置文件都不用改**。
        commands={"Windows": ["{home}/bin/elasticsearch.bat",
                              "-Ediscovery.type=single-node",
                              "-Expack.security.enabled=false",
                              # **必须关掉 ML**（2026-10-06 干净环境演练定位）：
                              # ES 9 在 Windows 上加载机器学习的原生库会失败：
                              #     Failure running machine-learning native code.
                              #     This could be due to running on an unsupported OS or
                              #     distribution, missing OS libraries...
                              # → 整个节点起不来、端口永不监听，表现为启动超时。
                              # 开发场景本来也用不上 ML（它是给异常检测/forecast 的）。
                              # 注意这与 CLASSPATH 那条是**两个独立的问题**：
                              # 修了 CLASSPATH 才走得��这一步，才暴露出 ML。
                              "-Expack.ml.enabled=false",
                              "-Ehttp.port={port}",
                              "-Epath.data={data_dir}/data",
                              "-Epath.logs={data_dir}/logs"],
                  "Linux":   ["{home}/bin/elasticsearch",
                              "-Ediscovery.type=single-node",
                              "-Expack.security.enabled=false",
                              # **必须关掉 ML**（2026-10-06 干净环境演练定位）：
                              # ES 9 在 Windows 上加载机器学习的原生库会失败：
                              #     Failure running machine-learning native code.
                              #     This could be due to running on an unsupported OS or
                              #     distribution, missing OS libraries...
                              # → 整个节点起不来、端口永不监听，表现为启动超时。
                              # 开发场景本来也用不上 ML（它是给异常检测/forecast 的）。
                              # 注意这与 CLASSPATH 那条是**两个独立的问题**：
                              # 修了 CLASSPATH 才走得��这一步，才暴露出 ML。
                              "-Expack.ml.enabled=false",
                              "-Ehttp.port={port}",
                              "-Epath.data={data_dir}/data",
                              "-Epath.logs={data_dir}/logs"],
                  "Darwin":  ["{home}/bin/elasticsearch",
                              "-Ediscovery.type=single-node",
                              "-Expack.security.enabled=false",
                              # **必须关掉 ML**（2026-10-06 干净环境演练定位）：
                              # ES 9 在 Windows 上加载机器学习的原生库会失败：
                              #     Failure running machine-learning native code.
                              #     This could be due to running on an unsupported OS or
                              #     distribution, missing OS libraries...
                              # → 整个节点起不来、端口永不监听，表现为启动超时。
                              # 开发场景本来也用不上 ML（它是给异常检测/forecast 的）。
                              # 注意这与 CLASSPATH 那条是**两个独立的问题**：
                              # 修了 CLASSPATH 才走得��这一步，才暴露出 ML。
                              "-Expack.ml.enabled=false",
                              "-Ehttp.port={port}",
                              "-Epath.data={data_dir}/data",
                              "-Epath.logs={data_dir}/logs"]},
        # 实测**没有 stop 脚本、没有 .ps1**
        stop_kind="port_lookup",
        main_port=9200,
        # 9300 是 transport 口（节点间通信），实测与 9200 一起监听
        extra_ports=(9300,),
        port_search_span=99,
        # 建副本但不改任何值：ES 9 的 yml 里 0 条有效配置，全靠 -E 覆盖；
        # 建副本是为了用户想手工微调时有地方改（官方文件会被卸载删掉）。
        port_writeback="conf_copy",
        console_path=None,
        health_path=None,
        # **ES_HOME 与 ES_PATH_CONF 必设**（2026-10-06 真机实测踩出来的）：
        # bin/elasticsearch.bat 只是壳，它 call 的 elasticsearch-cli.bat 里是
        #     set LAUNCHER_CLASSPATH=%ES_HOME%/lib/*;%ES_HOME%/lib/cli-launcher/*
        #     -Des.path.home="%ES_HOME%" -Des.path.conf="%ES_PATH_CONF%"
        # 两个都不设 → classpath 变成字面量 "%ES_HOME%/lib/*" →
        # JVM 找不到 jar，报出来的是一条**看不出原因**的错：
        #     NoSuchFileException: ...\logs\%JAVA_HOME%\lib\dt.jar
        # （那个 %JAVA_HOME% 是它的兜底分支，不是我们的问题；
        #   真因是 ES_HOME 没设，排查时被这条误导过一次。）
        extra_env={"ES_HOME": "{home}", "ES_PATH_CONF": "{conf_dir}",
                   # **CLASSPATH 必须清空**（2026-10-06 真机实测定位）：
                   # 这台机器的系统级 CLASSPATH 是 JDK 8 时代的遗留值
                   #     .;%JAVA_HOME%\lib\dt.jar;%JAVA_HOME%\lib	ools.jar
                   # （%JAVA_HOME% 字面量未展开，而 dt.jar/tools.jar 在现代 JDK 早没了）。
                   # JVM 不做 %VAR% 替换，会把它原样进 java.class.path；
                   # ES 9 启动时的 JarHell 校验逐个 new JarFile(classpath 里的项)
                   # → fatal，报出来的是一条**指向错误文件**的错：
                   #     NoSuchFileException: ...\logs\%JAVA_HOME%\lib\dt.jar
                   # 2x2 对照实验证实唯一自变量就是 CLASSPATH（清空即起得来）。
                   # 这不是 ES 的 bug 也不是本工具的 bug，但**本工具要能起来**，
                   # 所以 spawn 前把它清掉（子进程 env，不改用户的系统设置）。
                   "CLASSPATH": ""},
        needs=(),
        # **ES 自带 JDK 25 且强制使用、忽略 JAVA_HOME** → 不依赖外部 JDK
        min_java_major=None,
        data_dir_env=None,
        startup_timeout=120,
        risk_note=(
            "Elasticsearch 默认监听 9200（HTTP）与 9300（节点间 transport），**对局域网开放**。"
            "**本工具关闭了 xpack.security**（-Expack.security.enabled=false）—— "
            "因为一键启动是后台无终端进程，ES 官方明说此时它无法生成随机密码，"
            "我们既拿不到也没地方展示。**所以启动后没有任何认证，只适合本机开发用**。"
            "要带认证请手动启动并改 ES_SETTING_XPACK_SECURITY_ENABLED 与密码配置。"
            "堆内存默认是**自动**的（约为机器内存的一半，上限 16GB），"
            "资源紧张时用 -E-Xmx/-Xms 限制（当前版本未强行限制，按 GB 级预留）。"
        ),
        data_note=("数据与日志通过 -Epath.data / -Epath.logs 落在 ~/.env-tools/"
                   "elasticsearch-data 下，卸载只删版本目录，这份会保留。"),
        credentials_hint=(
            "**Elasticsearch 没有网页控制台** —— 9200 说 HTTP+JSON 协议，"
            "浏览器直接访问会看到 JSON 响应（正常），但没有可点的页面。"
            "本工具**已关闭 xpack.security**（一键启动是无终端后台进程，"
            "ES 官方明说此时不生成随机密码，我们拿不到也没地方展示），"
            "所以 9200 **无认证、只适合本机开发用**。"
            "图形界面请另装 Kibana。"
        ),
    ),

    "rabbitmq": LaunchSpec(        # 实测：zip 不含 Erlang，rabbitmq-server.bat 开头硬校验 erl.exe。
        # prereq=erlang 让框架在启动前检查/引导安装。
        # **RABBITMQ_NODENAME 必须是 ASCII 且固定**（2026-10-06 真机实测踩出来的，
        # 踩得很隐蔽）：节点名默认取 rabbit@<主机名>，而中文主机名（本机就是
        # 「鹅城剑仙」）会让 epmd 注册时把名字截断 —— 后果是
        # **服务器起来、5672/25672 都在听、日志一切正常，但所有 rabbitmqctl
        # 子命令全挂**（:badarg / rc=70）：看着启动成功，实际查不了状态也停不掉。
        # 固定成 rabbit@localhost 就绕开了主机名，且三处（start/stop/status）一致。
        commands={"Windows": ["cmd", "/c", "{home}/sbin/rabbitmq-server.bat"],
                  "Linux":   ["{home}/sbin/rabbitmq-server"],
                  "Darwin":  ["{home}/sbin/rabbitmq-server"]},
        extra_env={"RABBITMQ_NODENAME": "rabbit@localhost",
                   # 数据只落 RABBITMQ_BASE，%APPDATA%\RabbitMQ 不会被创建（实测）
                   "RABBITMQ_BASE": "{data_dir}"},
        # **用官方的 rabbitmqctl 优雅停止**，不用端口反查强杀：
        # 子代理实测 `rabbitmqctl.bat stop` rc=0、端口 1~4s 释放。
        # 强杀（port_lookup）会丢未落盘的消息 —— 能优雅停就别强杀。
        # 注意 ctl 与 server 必须**用同一个 RABBITMQ_NODENAME**（见 extra_env 注释）：
        # 不一致时 ctl 找不到节点、报 :badarg / rc=70。
        stop_kind="shutdown_command",
        shutdown_commands={"Windows": ["cmd", "/c", "{home}/sbin/rabbitmqctl.bat", "stop"],
                           "Linux":   ["{home}/sbin/rabbitmqctl", "stop"],
                           "Darwin":  ["{home}/sbin/rabbitmqctl", "stop"]},
        main_port=5672,
        # 15672 管理界面要开 rabbitmq_management 插件才有；这里只登记 AMQP 与 cluster
        extra_ports=(25672,),
        # rabbitmqctl stop 只停 server，**Erlang 的 epmd.exe 会一直活着**（真机 2026-10-07）。
        # 它不监听业务端口，所以按簇判定会正常报"已停止"，但它的工作目录还在版本目录里，
        # Windows 上会让之后的卸载删不掉那个目录 → 停止成功后必须提示，由用户决定要不要结束。
        leftover_processes=("epmd.exe",),
        port_search_span=99,
        port_writeback="cli_only",
        console_path=None,
        health_path=None,
        # 5672 说 AMQP 二进制协议，HTTP 探不到。用 rabbitmqctl status问它自己：
        # 它答得上来才说明节点名/Erlang/端口都对（中文主机名那个坑就靠它暴露）。
        service_probe=["cmd", "/c", "{home}/sbin/rabbitmqctl.bat", "status"],
        needs=(),
        min_java_major=None,
        data_dir_env=None,
        startup_timeout=120,
        prereq=PrereqSpec(
            key="erlang",
            probe="erl.exe",
            install_hint=(
                "本工具会在点「启动」时**自动下载并安装**配套的 Erlang/OTP"
                "（4.x 配 27.x、3.13 配 26.x，版本是绑死的），你不需要自己装。"
                "这条提示只在你看到自动安装失败时才需要读：Erlang 27 约 139MB、"
                "**国内镜像站没有**，只能走 GitHub 加速器，网络差时可能失败。"
                "另注：**安装路径不能含中文或空格** —— 官方明文非 ASCII 路径会报 "
                "`Erlang machine stopped instantly` 直接失败。"
            ),
        ),
        risk_note=(
            "RabbitMQ 默认监听 5672（AMQP）与 25672（集群），**对局域网开放**，"
            "**默认账号 guest/guest 只允许本机登录**。"
            "**必须先装 Erlang/OTP 27**（4.0.9 要求 26.2~27.x，而 26 已 EOL）。"
            "管理界面（15672）需要额外开 rabbitmq_management 插件，本工具暂不启用。"
        ),
        data_note=("Mnesia 数据与日志落在 ~/.env-tools/rabbitmq-data（RABBITMQ_BASE，"
                   "我们显式指定的）；**官方默认是 %APPDATA%\\RabbitMQ，"
                   "而实测那个目录根本不会被创建**。卸载不会删这份数据，"
                   "要彻底清理请手动删除。"),
        # **它没有网页控制台**（2026-10-06 用户报「显示启动成功实际无法访问」）：
        # 5672 是 AMQP 二进制协议，浏览器打开只会失败；管理界面 15672 要另外开
        # rabbitmq_management 插件才有。所以启动后必须说清"怎么用"——
        # 否则用户只看到"启动成功"却不知道怎么连，以为是服务坏了。
        credentials_hint=(
            "**RabbitMQ 没有网页控制台** —— 5672 说 AMQP 协议（给客户端连的），"
            "用浏览器打开会失败或空白，这是正常的、不是服务坏了。\n"
            "三种正常用法：\n"
            "① 客户端连接：amqp://guest:guest@127.0.0.1:5672/\n"
            "   （guest 默认只允许本机连接；对局域网开放时需要另建账号）\n"
            "② 命令行查状态：安装目录下 sbin\\rabbitmqctl.bat status\n"
            "③ 网页管理界面（15672）：要先执行一次 "
            "sbin\\rabbitmq-plugins.bat enable rabbitmq_management 才会出现，"
            "本工具暂未启用。"
        ),
    ),

    # ================= 2026-10-06 seata（双进程：控制台 + TC）=================
    # 每一处的值都来自当天的拆包与真机实测，不是按厂商惯例推的。
    "seata": LaunchSpec(
        # ============================================================
        # 实测（2026-10-06，apache-seata-2.2.0 真机装起来跑通）：
        # **2.2.0 是单进程**，进程自己带控制台 —— 与 Nacos 同构，不需要第二个进程。
        #   seata-server（一个进程）= HTTP 控制台 7091 + Netty RPC 8091
        # 实测证据：
        #   Tomcat started on port(s): 7091 (http)
        #   Server started, service listen port: 8091
        #   GET /            → 200（static/index.html 在 server/lib/seata-console-2.2.0.jar）
        #   GET /health      → "ok" 200（免鉴权，ignore-urls 里写着它）
        #   POST /api/v1/auth/login (seata/seata) → 200 + Bearer token
        #
        # ⚠️ **2.6.0 不是这个架构**（实测拆包确认）：2.6.0 把控制台拆进了
        # 独立的 seata-namingserver（8081），server 自己变成 web-application-type: none
        # （不启 HTTP）。同一份 LaunchSpec 描述不了两种布局，
        # 所以版本清单里现在只有 2.2.0 —— 见 _seata_cv 那处的注释。
        # ============================================================
        commands={"Windows": ["{home}/seata-server/bin/seata-server.bat"],
                  "Linux":   ["{home}/seata-server/bin/seata-server.sh"],
                  "Darwin":  ["{home}/seata-server/bin/seata-server.sh"]},
        # **端口靠环境变量注入，不是命令行 flag**（这是实测逼出来的，别改回去）：
        # 1. `--server.port=7091` **不行** —— seata-server 有自己的 joptsimple CLI，
        #    只认 `-p`/`--port`/`--host`/`--storeMode`/…；传 --server.port 会打
        #      Option error Was passed main parameter '--server.port=7091'
        #      but no main parameter was defined in your arg class
        #    然后**进程退出、端口不监听**（和 ActiveMQ 的 task 坑同类）。
        # 2. 什么都不传也**不行** —— 它有个硬编码兜底口 **7056**
        #    （conf/application.yml 明明写的 7091，实测照样起在 7056；
        #     `-p 7091` 也压不住它，改的是 netty 侧）。
        # 3. `SERVER_PORT=7091` **实测有效**：Spring Boot 的 relaxed binding 认它，
        #    且优先级压得住那个硬编码兜底（实测 Tomcat initialized with port 7091）。
        # → 这是本项目第一个"靠 extra_env 传端口"的组件，port_writeback 仍是
        #   cli_only（我们不碰任何厂商文件）。
        extra_env={"SERVER_PORT": "{port}"},
        # 脚本**没有 stop 子命令**（实测 bin 下只有启动入口），走端口反查 + 三重闸。
        stop_kind="port_lookup",
        main_port=7091,              # HTTP 控制台口
        # RPC 口 = server.port + 1000（实测 8091，与 Nacos 的 gRPC 派生同构）。
        # 整簇探活会等 7091 与 8091 都在听才认定启动成功。
        port_offsets=(1000,),
        port_search_span=99,
        port_writeback="cli_only",   # 不碰厂商文件；端口由上面的 SERVER_PORT 注入
        console_path="/",            # 实测 GET / 返回 200
        # 实测 GET /health 返回 "ok"（200，免鉴权）。与 console_path（/）不同，
        # 所以这里要填 —— 两者相同时填了会被拼成双份（/nacos/nacos 那个坑）。
        health_path="/health",
        needs=("jdk",),
        # 实测 2.2.0 用 **JDK 8 与 JDK 21 都能起来**（class 52，两个版本都跑通了）。
        min_java_major=8,
        data_dir_env=None,
        # 实测启动耗时约 10 秒（Tomcat 就绪 7s + netty 1s），90 秒宽裕。
        startup_timeout=90,
        risk_note=(
            "Seata 监听 0.0.0.0 的 **7091（控制台）与 8091（事务 RPC）**，"
            "对局域网开放；脚本写死 -Xmx2048m，约占 2GB 内存。"
            "控制台出厂账号 **seata/seata**（实测 conf/application.yml 的 console.user，"
            "且实测登录能拿到 token）—— 请尽快改掉。"
            "事务数据默认走 file 存储（seata.store.mode），卸载组件会**连带删除版本目录**。"
        ),
        credentials_hint=(
            "控制台：http://127.0.0.1:7091/　用户名：seata　密码：seata"
            "（2.2.0 出厂默认，实测登录成功）。"
            "改密码：编辑安装目录下 seata-server/conf/application.yml 的 "
            "console.user.username / password，改完重启生效。\n"
            "另有一个端口 8091 是事务 RPC（Netty 二进制协议），给微服务客户端连的，"
            "浏览器打不开属正常。"
        ),
        data_note=("事务会话与全局锁默认走 file 存储（conf/application.yml 的 "
                   "seata.store.mode: file），落点由该配置项决定；"
                   "日志默认在 ~/logs/seata（实测启动日志里写明了这个路径）。"
                   "**卸载只删版本目录** —— 若你把 store 配到了安装目录内，"
                   "那份数据会跟着没；配在外面则不受影响。"),
    ),
}

LAUNCH_KEYS = set(LAUNCH_OF)


def group_components(components: List[Component]) -> Dict[str, List[Component]]:
    """按 COMPONENT_CATEGORIES 的顺序分组，供界面建 Tab。

    **隐藏组件不进界面**（Component.hidden，目前只有 Erlang）：它是 rabbitmq
    的前置运行时，由「启动 rabbitmq」自动装好，不该出现在用户的组件列表里 ——
    列出来用户就会以为"我也该单独装一个 Erlang"，而版本还必须是配套的那个。
    """
    grouped: Dict[str, List[Component]] = {name: [] for name in COMPONENT_CATEGORIES}
    for comp in components:
        if getattr(comp, "hidden", False):
            continue
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
            #离线清单必须给**确定路径**，不能只留 api.adoptium.net。
            #
            # 2026-10-06 实测：那个 API 会 302 到 github.com，本机 21/17 两个大版本
            # 直接 ConnectTimeout，只有 8 能通 —— 也就是说离线状态下装 JDK 21 必然失败，
            # 而 JDK 21 恰恰是最主流的版本。真实用户会栽在这，不是测试环境问题。
            #
            # 清华/南大的 Adoptium 目录结构是固定的（/<major>/jdk/<arch>/<os>/），
            # 文件名实测采集（_collect_jdk_files.py），两个站四个版本全都有、
            # 速度 4.9~14.6 MB/s。所以离线直接写镜像路径，官方 API 退到末位兜底。
            #
            # 版本刷新（fetch_jdk_versions）走 _adoptium_jdk_url 的联网解析，
            # 会拿到更新的补丁号 —— 这里的文件名只是离线兜底，不是最新。
            versions=[
                _cv(v, _adoptium_offline_urls(v, _JDK_OFFLINE_FILES.get(v, {})))
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
            data_note=("已部署的 web 应用（war 展开目录）与 logs 日志都在**安装目录内**，"
                       "所以**卸载会连同已部署的应用一起删**——多版本并存时切回旧版本还能看到"
                       "旧应用，但卸载那个版本时应用就没了。CATALINA_BASE 未改时指回安装目录。"),
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
            data_note=("配置与日志默认在**安装目录内**的 conf/ 与 logs/ 下，"
                       "卸载会连它们一起删；本工具未实测 Windows 版的确切子目录名，"
                       "以你实际安装的目录结构为准。"),
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
            data_note=("数据（数据库文件、binlog）默认在**安装目录内**的 data/ 下，"
                       "卸载会连同这个版本目录一起删——**多版本并存时只卸载你不再用的那个版本**，"
                       "否则连库文件一起没了。若已把 datadir 指到别处，以那个配置为准。"),
        )
    )

    # ------------------ Python ------------------
    components.append(
        Component(
            key="python",
            display_name="Python",
            env_var=None,
            # **Windows 必须用安装根目录，不能写 "Scripts"**（2026-10-09 真机踩到）：
            # Windows 下装的是 embeddable 包（python-3.x.x-embed-amd64.zip），
            # python.exe 就在解压根目录，包里**压根没有 Scripts 目录**。写成 "Scripts"
            # 会让 PATH 指向一个不含解释器的目录 —— 于是 `python` 永远命中机器上自己装
            # 的那份（本机 C:\Program Files\python），切换、乃至提权插到系统 PATH 最前
            # 都白做：复验只会一直报"仍会先命中 …"，然后自动回滚。
            # Unix 的官方包解释器在 bin/，保持原样。
            path_subdir="" if CURRENT_OS == "Windows" else "bin",
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
            # **Windows 用解压根目录**（2026-10-10 用 bt_archive_layout_audit.py 读官方
            # node-v20.15.0-win-x64.zip 的中央目录实测）：`node.exe`、`npm`、`npx.cmd`
            # 全在 `node-vX.Y.Z-win-x64/` 这一层，包里**没有 bin 子目录**。
            # 写 "bin" 会让 PATH 指到一个不存在的目录 —— 与 Python 那次（"Scripts"）
            # 是同一类错：界面上只表现为"切了但没生效"，命令行永远命中机器上原有的 node。
            # Unix 官方 tar.gz 里解释器确实在 bin/，保持原样。
            path_subdir="" if CURRENT_OS == "Windows" else "bin",
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
            # Windows 平台不支持 Docker static binary 自动下载，给用户友好引导。
            # 2026-10-08 本机实测确认这不是"暂时不提供"而是**平台形态不同**：
            # Docker 官方的 static binary（docker/dockerd 两个裸可执行文件）只发
            # Linux/macOS；Windows 上要的是 Docker Desktop（需要 WSL2 或 Hyper-V
            # 后端 + 安装期管理员授权，装完还得重启），本工具"解压即用"的模型
            # 装不出一个能跑的 Windows Docker。
            unsupported_platform_hint=(
                "Docker 在 Windows 上没有「解压即用」的形态 —— "
                "官方 static binary 只发 Linux/macOS，Windows 侧必须装 Docker Desktop"
                "（它依赖 WSL2 或 Hyper-V，安装时需要管理员授权、通常还要重启）。"
                "本工具不代装它。请到官网下载 Docker Desktop："
                "https://www.docker.com/products/docker-desktop/\n"
                "如果你要的只是「在本机跑 Linux 容器」：也可以装 WSL2 "
                "（管理员 PowerShell 执行 wsl --install）再在发行版里 apt install docker.io。"
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
            data_note=("数据库文件默认在**安装目录内**的 data/db 下，卸载会连它一起删；"
                       "若已用 --dbpath 指到别处，以那个路径为准。"),
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
            data_note=("数据库数据默认在**安装目录内**的 data/ 下，卸载会连它一起删；"
                       "多版本并存时卸载任一版本只影响该版本目录内的数据。"
                       "若已用 initdb 把数据放到别处，以那个目录为准。"),
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
    # Jenkins LTS 提供 jenkins.war 跨平台单文件，可用 `java -jar jenkins.war` 启动
    # exec_name=None：jenkins.war 不是命令行可执行文件，detect 只能通过 PATH 找 jenkins 命令
    # 本工具不止下载+配置环境变量：已登记进 LAUNCH_OF（规则 R5），卡片上有「启动 / 停止 / 打开控制台」
    # 一键启动能力已实现且有离线护栏守护；Windows 真机验证尚未执行（本机无 JDK/Jenkins，需用户在场跑 --launch jenkins --yes）
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
                "下载完成后点卡片上的「启动」按钮即可一键拉起、并从「控制台」进入 Jenkins 页面"
                "（能力已实现且有离线回归守护；Windows 真机验证待用户在场执行，见 DEVELOPMENT.md 规则 R5）。"
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
            data_note=("队列数据在 RabbitMQ 自己的数据目录（由配置里的数据目录项决定，"
                       "Linux/macOS 常见是 ~/.erlang.io/… 或 /var/lib/rabbitmq），"
                       "**不在安装目录里**，卸载不会删它。"),
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
            data_note=("消息数据默认在 **log.dirs 配置项**指向的位置（未改时通常是 "
                       "/tmp/kafka-logs），**不在安装目录里**，卸载不会自动删它。"
                       "注意：多版本并存时若几个版本共用同一个 log.dirs，数据是共享的，"
                       "不要同时跑多份 broker。"),
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
            data_note=("消息与 commitlog 默认在 **storePathRoot 配置项**指向的位置"
                       "（常见 ~/store），**不在安装目录里**，卸载不会删它。"
                       "多版本并存时务必给每个版本分开设 storePathRoot，否则会互相踩。"),
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
            # **不许执行版本探测**（2026-10-08 本机实测）：
            #   - 解压出来的 bin/pulsar 是 **bash 脚本**（首行 #!/usr/bin/env bash），
            #     Windows 上直接 spawn 它只会得到 `WinError 193 不是有效的 Win32 应用程序`；
            #   - 而且 `bin/pulsar --version` 在这个版本上**根本不是有效子命令**
            #     （实测回 `-- Invalid command '--version'`）——
            #     也就是说这个探测命令两个平台上都拿不到版本号，探了只会白花一次调用。
            version_probe=False,
            # Windows 上只有 pulsar-admin/pulsar-client/pulsar-perf/pulsar-shell 的
            # .cmd 包装器，**没有主命令 pulsar.cmd**（实测 3.3.9 的 bin 下就这些文件）。
            # 主 CLI（local/standalone/daemon）只有 POSIX shell 脚本，官方 Windows
            # 起步文档也是让用 Docker 或 WSL。与其装完给用户一个跑不起来的命令，
            # 不如把这件事说清楚。
            unsupported_platform_hint=(
                "Apache Pulsar 官方在 Windows 上只提供 bin/*.cmd 的部分工具"
                "（pulsar-admin / pulsar-client / pulsar-perf / pulsar-shell），"
                "**主命令 pulsar 只有 POSIX shell 脚本**（bin/pulsar 是 bash），"
                "Windows 原生跑不起来 —— 官方起步文档也要求 Docker 或 WSL。\n"
                "两种可用做法：\n"
                "① 在 WSL2 里用（把上面的 tar.gz 下到 Linux 侧解压，再 ./bin/pulsar standalone）；\n"
                "② 用 Docker：docker run -it -p 6650:6650 -p 8080:8080 "
                "apachepulsar/pulsar:3.3.9 bin/pulsar standalone"
            ),
            versions=[_pulsar_cv(v) for v in ("3.3.9", "3.3.1")],
            data_note=("bookie 数据落在 broker 配置指定的目录下（standalone.conf 里的 "
                       "bookkeeperMetadataServiceUri 等），**不在安装目录里**，卸载不会删它。"
                       "本工具只装 broker 端，未实测具体落点，以你的配置为准。"),
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
    # Seata 是 Apache 孵化项目（分布式事务），在 GitHub releases 发布，国内无官方镜像。
    #
    # **包结构（2026-10-06 实测，两个版本都拆开看过）**：
    #   2.6.0：tar 里有一个统一顶层目录 apache-seata-2.6.0-incubating-bin/；
    #   2.2.0：tar 里**没有**统一顶层目录，直接是 seata-server/ + seata-namingserver/。
    #   两种情况下最终 install_dir 内都是 `seata-server/` 与 `seata-namingserver/`
    #   两个子目录 —— **顶层没有 bin/**。
    #
    # 所以 path_subdir 必须是 "seata-server/bin"。原来写 "bin" 是从 1.x 的布局
    # 凭印象推的，实测后 seata-server.bat 根本不在那个位置：装完 seata 会被判成
    # 未安装（绿勾不显示），启停门控也直接拦住。
    components.append(
        Component(
            key="seata",
            display_name="Seata",
            env_var="SEATA_HOME",
            path_subdir="seata-server/bin",
            exec_name="seata-server",  # Seata 启动脚本（seata-server.sh / seata-server.bat）
            version_args=["--version"],
            # seata-server 脚本一执行就会拉起 Seata 服务，探测阶段绝不执行
            version_probe=False,
            # **版本清单只有 2.2.0**（2026-10-06 决定）：
            # 实测发现 **2.6.0 与 2.2.0 是两个不同的架构** ——
            #   2.2.0：单进程，server 自己带 HTTP 控制台（7091）+ RPC（8091）；
            #   2.6.0：控制台被拆进独立的 seata-namingserver（8081），
            #          server 变成 web-application-type: none，自己不启 HTTP。
            # 一个 LaunchSpec 只能描述一种布局，登记 2.6.0 会让启动探活
            # 等一个根本不存在的 7091，表现为"启动超时、控制台打不开"。
            # 要加回 2.6.0 就得先让 spec 支持**按版本分叉**，在那之前不放进来 ——
            # 宁可少一个版本，也不给用户一个装了就起不来的选项。
            versions=[_seata_cv("2.2.0")],
            data_note=("事务日志（undo_log）与 server 存储落在各实例配置指定的存储里；"
                       "**服务端日志实测落在安装目录内的 seata-server/logs/ 下**"
                       "（2026-10-08 真机复核：那个目录里只有 seata_gc.log，"
                       "logback 的 seata-server.log 没有生成 —— 排障时先看"
                       " ~/.env-tools/seata-data/logs/byte-tools.out 里捕获的控制台输出，"
                       "它在启动阶段会打印 Tomcat 端口与 Server started）。"
                       "切换生效版本不会动它，多版本并存时各版本的配置互不覆盖。"),
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
            data_note=("索引数据默认在**安装目录内**的 data/ 下（path.data 配置项），"
                       "卸载会连它一起删。多版本并存时每个版本各有自己的 data/、互不影响，"
                       "但它们不能同时监听同一端口与同一集群名。"),
        )
    )

    # ------------------ Erlang/OTP（隐藏组件：rabbitmq 的前置运行时）------------------
    # 用户要的是"点启动 RabbitMQ 就能起"，而不是"先自己去找 Erlang 装好"。
    # 所以 Erlang 在这里登记成一个**隐藏组件**（不出现在界面），复用同一套
    # 下载多源故障转移 / 解压落位 / 版本解析；rabbitmq 的门控查不到 Erlang 时
    # 就自动把它装上（见 ensure_launch_prereqs）。
    components.append(
        Component(
            key="erlang",
            display_name="Erlang/OTP（RabbitMQ 前置运行时）",
            env_var=None,        # 刻意不设：实测免安装版不需要任何 *_HOME，
                                 # rabbitmq 的 rabbitmq-env.bat 自己 Get-Command erl.exe
            path_subdir="bin",
            exec_name="erl",
            version_args=["-noshell", "-eval",
                          "io:format(\"~s~n\",[erlang:system_info(otp_release)]),halt()."],
            versions=[_erlang_cv(v) for v in ("27.3.4.1", "27.2", "26.2.5.11")],
            hidden=True,
            data_note="Erlang 是 RabbitMQ 的前置运行时，由本工具随 RabbitMQ 自动安装。",
        )
    )

    for comp in components:
        # 可一键启停的组件全部集中到「一键启停」Tab（2026-10-08 用户要求），
        # 成员**由 LAUNCH_KEYS 派生**而不是再写一张表：那张表的准入条件本来就是
        # "卡片上有启动/停止按钮"，两处各写一份迟早会出现"能启动、卡片却在别的 Tab"。
        # COMPONENT_CATEGORY_OF 里的旧分类保留作 fallback —— 组件哪天从白名单退下来，
        # 它会自动回到原来那一组，不用改两处。
        comp.category = ("一键启停" if comp.key in LAUNCH_KEYS
                         else COMPONENT_CATEGORY_OF[comp.key])   # 漏登记直接 KeyError
        # 多版本一律为 True（2026-06-06 起全量开放）。MULTI_VERSION_KEYS 为空集时
        # 全部组件都算多版本；白名单里再写 key 也不会被排除——它现在只作为
        # "历史上哪些组件是原生多版本"的记录留着，护栏用例靠它标注哪些是新增覆盖的。
        comp.multi_version = True
        comp.launch = LAUNCH_OF.get(comp.key)                     # 新增：不在登记表就是 None
    return components


def uninstall_confirm_text(comp: Component) -> str:
    """卸载确认的正文。数据去处必须写明且按组件区分：
    Jenkins 的数据在 ~/.env-tools/jenkins-data、卸载后保留；
    Nacos 的 derby 在版本目录里、会跟着一起删；ActiveMQ 两者都有（副本 + 存储在 ~/.env-tools 下）。
    一句含混的"数据会被清理"对其中任何一个都是假话。

    data_note 有两个来源，都要读（2026-06-06 全组件多版本之后）：
    · `comp.data_note` —— 组件级，覆盖 11 个带数据的中间件（mysql/kafka/tomcat/…）。
      这批组件**没有 launch 描述符**（还不在一键启动白名单里），data_note 挂在组件上。
    · `comp.launch.data_note` —— 启动级，三个已接入一键启动的组件
      （jenkins/nacos/activemq）写在这里。
    组件级优先：它描述的是"删这个目录会连带删掉什么"，对未接入启动的组件更有意义。
    """
    # 环境变量名要点名：卸载不可逆，确认框里写"它的环境变量"等于让用户自己回忆是哪个。
    # 计划初稿写的是泛指的"环境变量与 PATH 条目"，相对计划一的三条 bullet 少了一个变量名 ——
    # 那条 bullet 里的 `{comp.env_var or '（无）'}` 是实打实的信息，不许在重写时丢掉。
    var = comp.env_var or "（无）"
    text = f"删除 {comp.display_name} 已安装的版本，"
    text += f"并清理环境变量 {var} 与 PATH 中属于它的条目。"
    note = getattr(comp, "data_note", "")
    if not note and getattr(comp, "launch", None) is not None:
        note = getattr(comp.launch, "data_note", "")
    if not note:
        # 既没有 data_note 也没有 launch：说清我们只删自己管的目录，别让用户以为会动别处。
        note = "本工具只会删除它自己管理的安装目录，不会碰你手工放到别处的文件。"
    return text + "\n\n数据去向：" + note


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
        # (连接, 读取) 二元组：连接 10 秒（不通就快速换源）、读取 60 秒
        # （大包慢速下载时两次读之间可能超过 30 秒，单值超时会把 jdk/gradle 这类打死）。
        timeout = (DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT)
        with requests.get(url, stream=True, timeout=timeout,
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
# 安装（下载完成 → 落位）的**唯一实现**
#
# 为什么抽成模块级函数（2026-10-08）：这段逻辑原本只存在于
# ComponentCard._on_download_ok 里，于是每一次真机演练都只能自己再抄一遍
# （bt_mv_drill.py 就抄了 60 行），抄出来的副本与产品代码必然越走越远 ——
# 演练绿灯不代表用户点下去会成功。抽出来之后，演练调的就是用户点的那条路径。
# ---------------------------------------------------------------------------
def _null_log(level: str, message: str) -> None:  # pragma: no cover - 默认值
    """默认日志出口：什么都不做。"""
    return None


def install_downloaded(comp: Component, version: str, archive: Path,
                       log: Optional[Callable[[str, str], None]] = None) -> Path:
    """把下载好的归档/安装器落位成 comp 的 install_dir(version)，返回该目录。

    入参 comp:    Component                目标组件
    入参 version: str                      版本号（目录名契约：<key>-<version>）
    入参 archive: Path                     已下载完成的文件
    入参 log:     Callable[[str,str],None] 日志出口 (level, message)
    返回:         Path                     落位后的安装目录

    行为与原来内联在 _on_download_ok 里的逐字一致：
      - installer_mode（conda）：静默跑安装器，目标目录由安装器参数决定
      - 单文件（exe / war / 无扩展名）：拷进目标目录根 + 按 exec_name 改名，
        否则 exec_path_in_home 找不到可执行文件，状态会被判成"没装"
      - 归档（zip / tar.gz / tar.xz）：解压到 .extract-<version> 再 move 归位
    """
    emit = log or _null_log
    target_root = CONFIG_DIR / comp.key
    ensure_dir(target_root)
    final = comp.install_dir(version)

    if comp.installer_mode:
        emit("info", "开始运行安装器（静默安装）…")
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        _run_installer_for(comp, archive, final, emit)
        emit("ok", f"安装完成：{final}")
        return final

    emit("info", "开始解压…")
    tmp_dir = target_root / f".extract-{version}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    ensure_dir(tmp_dir)
    root = extract_archive(archive, tmp_dir)

    archive_ext = archive_ext_for(comp, version)
    is_single_binary = archive_ext in ("exe", "war", "", "bin")
    # **单文件也要改名，即使 exec_name 是 None**（2026-10-08 真机实测定位的缺陷）：
    # 原来这里是 `if is_single_binary and comp.exec_name:`，于是 **jenkins 落位后
    # 文件仍叫 `jenkins-2.568.3.war`** —— 而 jenkins 的 LaunchSpec 里写死了
    # `{java} -jar {war}`，war 的路径由 build_launch_plan 硬拼成
    # `<home>/jenkins.war`。两者对不上，点启动必然
    # `[WinError 267] 目录名称无效`（用户装完就起不来）。
    # 现在 war 有兜底名 jenkins.war；exe/无扩展名的单文件仍然必须靠 exec_name，
    # 没有 exec_name 时不动它（改名成什么都是猜）。
    if is_single_binary:
        renamed_by_fallback = False
        if comp.exec_name:
            if archive_ext == "war":
                target_name = (comp.exec_name if comp.exec_name.endswith(".war")
                               else comp.exec_name + ".war")
                renamed_by_fallback = True
            elif archive_ext == "exe" or CURRENT_OS == "Windows":
                target_name = comp.exec_name + ".exe"
                renamed_by_fallback = True
            else:
                target_name = comp.exec_name
                renamed_by_fallback = True
        elif archive_ext == "war":
            # 唯一有"通用文件名"的单文件形态：war 包在 Servlet 容器里就叫
            # <app>.war（启动命令也按这个名找它）。名字从下载文件名里取，
            # 不写死组件 key：`jenkins-2.568.3.war` → `jenkins.war`。
            stem = archive.name.rsplit(".", 1)[0]
            target_name = (stem.split("-", 1)[0] or "app") + ".war"
            renamed_by_fallback = True
        else:
            target_name = ""
        if renamed_by_fallback:
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
    emit("ok", f"解压完成：{final}")
    return final


def archive_ext_for(comp: Component, version: str) -> str:
    """取该版本在当前平台的归档类型（查不到版本时返回空串 → 走单文件分支的旧语义）。"""
    for cv in comp.versions:
        if cv.version == version:
            return cv.archive_for_current()
    return ""


def _run_installer_for(comp: Component, installer_path: Path, target_dir: Path,
                       emit: Callable[[str, str], None] = _null_log) -> None:
    """静默运行安装器（Miniconda 这类）。与 ComponentCard._run_installer 逐字一致。"""
    args = list(comp.installer_args.get(CURRENT_OS, []))
    ensure_dir(target_dir.parent)

    if CURRENT_OS == "Windows":
        # Windows Miniconda: 参数末尾 /D=path 不允许带引号
        cmd = [str(installer_path)] + args + [f"/D={target_dir}"]
        emit("info", f"运行：{' '.join(cmd)}")
        proc = subprocess.run(cmd, check=False)
    else:
        # macOS / Linux: bash installer.sh -b -f -p <path>
        os.chmod(installer_path, 0o755)
        cmd = ["bash", str(installer_path)] + args + [str(target_dir)]
        emit("info", f"运行：{' '.join(cmd)}")
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.stdout:
            emit("info", proc.stdout.strip()[:500])
        if proc.stderr:
            emit("warn", proc.stderr.strip()[:500])

    if proc.returncode != 0:
        raise RuntimeError(f"安装器返回非零退出码：{proc.returncode}")


class _LoggerAdapter:
    """把组件卡片实例上的 _log 方法适配成 install_downloaded 需要的两参可调用对象。"""

    def __init__(self, bound_log) -> None:
        self._bound = bound_log

    def __call__(self, level: str, message: str) -> None:
        self._bound(level, message)


# ---------------------------------------------------------------------------
# 启动/停止线程层（详见设计文档 §3 线程层）
# ---------------------------------------------------------------------------
class LaunchCancelled(Exception):
    """用户取消等待。不是故障，只是"别再替我盯着端口了"。"""


class LaunchWorker(QThread):
    """启动/停止的耗时动作。有界探活最长能到 startup_timeout 秒，
    绝不能放在 UI 线程里 —— 这正是 DownloadWorker 走线程的同一个理由。"""

    started_ok = Signal(str, str)   # (key, console_url)
    failed = Signal(str, str)       # (key, reason)
    stopped = Signal(str)           # key
    need_force = Signal(str, str)   # (key, reason)：一次"要不要强制结束"的询问，不是错误
    # (key, [提示行…])：端口准备阶段的告警，成功与失败都有话要说。
    # 单独一条信号而不是塞进 reason：reason 是给人看的报错文案，
    # 而"已在 data 建立配置副本、此后端口只写这份副本"是成功时也得知道的事实。
    notes = Signal(str, list)

    def __init__(self, action: str, comp: Component,
                 comps: Dict[str, Component], mgr: "ServiceManager", parent=None):
        super().__init__(parent)
        self.action = action
        self.comp = comp
        self.comps = comps
        self.mgr = mgr
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _sleep(self, seconds: float) -> None:
        """取消检查挂在 ServiceManager 的每轮等待上 —— 有界探活是唯一长耗时阶段，
        而它的 sleeper 本来就是注入点，所以不用给它加新参数就能中止。"""
        if self._cancelled:
            raise LaunchCancelled()
        time.sleep(seconds)

    def _dispatch(self) -> None:
        if self.action == "start":
            res = self.mgr.start(self.comp, self.comps, sleeper=self._sleep)
            if res.notes:
                self.notes.emit(self.comp.key, list(res.notes))
            if res.ok:
                self.started_ok.emit(self.comp.key, res.console_url)
            else:
                self.failed.emit(self.comp.key, res.reason)
        elif self.action == "stop":
            res = self.mgr.stop(self.comp, self.comps, sleeper=self._sleep)
            self._emit_stop(res)
        elif self.action == "force_stop":
            self._emit_stop(self.mgr.force_stop(self.comp.key, sleeper=self._sleep))
        else:
            # 认不出的 action 必须出声：静默返回就是"线程跑完了却什么信号都没发"，
            # 卡片会永远停在"进行中"，正是 run() 兜底要防的那类故障。
            self.failed.emit(self.comp.key, f"{self.comp.display_name} 不支持的操作：{self.action}")

    def _emit_stop(self, res: "StopResult") -> None:
        if res.ok:
            self.stopped.emit(self.comp.key)
        elif res.need_force:
            # 询问走独立信号：混在 failed 的正文里，卡片一时忘了拆前缀，
            # 就会把"__need_force__"这种控制标记直接显示给用户。
            self.need_force.emit(self.comp.key, res.reason)
        else:
            self.failed.emit(self.comp.key, res.reason)

    def run(self) -> None:
        try:
            self._dispatch()
        except LaunchCancelled:
            # 取消只是停止"等"，进程还在不在没人知道 —— 这话必须说清，
            # 否则用户以为取消等于停住了。
            self.failed.emit(self.comp.key,
                             "已取消等待。进程可能仍在启动中，稍后看状态或再点停止。")
        except Exception as exc:
            self.failed.emit(self.comp.key, f"{self.comp.display_name} 操作过程出错：{exc}")


# ---------------------------------------------------------------------------
# 环境变量处理
# ---------------------------------------------------------------------------
# WM_SETTINGCHANGE 与 SendMessageTimeout 的常量（Windows 外壳通知）
WM_SETTINGCHANGE = 0x1A
SMTO_ABORTIFHUNG = 0x0002
SMTO_NOTIMEOUTIFNOTHUNG = 0x0004
HWND_BROADCAST = 0xFFFF


def notify_shell_environment(user32=None, timeout_ms: int = 3000) -> bool:
    """点名通知 Windows 外壳"环境变量变了"，让它重建自己那份环境块。

    为什么不能用 PostMessageW(HWND_BROADCAST, ...)（旧写法，已被真机否掉）：
    2026-09-30 实测——注册表已经改成 bun-1.4.2，explorer 的环境块 6 秒后仍是 1.4.1，
    于是用户从开始栏/任务栏开的**每一个**新终端都继承那份旧环境，"重开终端"永远无效。
    换成同步 SendMessageTimeoutW(Shell_TrayWnd, ...) 后 explorer 1 秒内就翻成新值，
    单次调用只花 0.02 秒。

    老注释担心"同步广播会被僵死窗口拖住"——那是没带 SMTO_ABORTIFHUNG 的同步发送；
    带上它 + 超时上限，僵死窗口会被直接跳过。

    参数: user32 传 None 时用真实 user32；测试里传一个假对象即可断言"发给谁、
    带什么标志、lParam 指向哪个字符串"。返回是否至少有一个外壳窗口确认收到。
    """
    if CURRENT_OS != "Windows":
        return False
    import ctypes
    from ctypes import wintypes

    if user32 is None:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ssize_t),
        ]

    # 同步调用期间这块内存必须活着 —— 异步 PostMessage 正是死在这里：
    # 消息排队到 explorer 处理时，发送方的缓冲区早没了，它读到的不是 "Environment" 就直接忽略。
    label = ctypes.create_unicode_buffer("Environment")
    lparam = ctypes.cast(label, ctypes.c_void_p).value
    out = ctypes.c_ssize_t(0)
    acked = False
    for window_class in ("Shell_TrayWnd", "Progman"):
        try:
            hwnd = user32.FindWindowW(window_class, None)
            if not hwnd:
                continue
            if user32.SendMessageTimeoutW(hwnd, WM_SETTINGCHANGE, 0, lparam,
                                          SMTO_ABORTIFHUNG | SMTO_NOTIMEOUTIFNOTHUNG,
                                          timeout_ms, ctypes.byref(out)):
                acked = True
        except Exception:
            continue
    return acked


def _notify_other_top_level_windows(timeout_ms: int = 1000) -> None:
    """再给所有顶层窗口发一遍，让 IDE 这类自己监听环境变化的应用也能刷新。

    放在后台线程里做：这条走的是 HWND_BROADCAST，窗口数量不可控，
    虽然带 SMTO_ABORTIFHUNG 仍可能耗上一阵，不该拖住点按钮的人。
    """
    if CURRENT_OS != "Windows":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ssize_t),
        ]
        label = ctypes.create_unicode_buffer("Environment")
        out = ctypes.c_ssize_t(0)
        user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0,
                                   ctypes.cast(label, ctypes.c_void_p).value,
                                   SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(out))
    except Exception:
        pass


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
        """通知外壳与其它程序"环境变量变了"。

        取代原先的 setx：setx 会把超过 1024 字符的 PATH 直接截断，而且它自身要靠
        PATH 查找（PATH 一旦被写坏就彻底失效），而持久化本来就由写注册表完成。

        外壳那一路必须**同步**发（见 notify_shell_environment 的真机数据）；
        给其它顶层窗口那一路放后台线程，发不出去也不影响已经写好的注册表。
        """
        if CURRENT_OS != "Windows":
            return
        try:
            notify_shell_environment()
        except Exception:
            pass
        try:
            _threading.Thread(target=_notify_other_top_level_windows,
                              daemon=True).start()
        except Exception:
            pass

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
            EnvManager._delete_windows_user_env(name)
            EnvManager._broadcast_env_change()
            # 同步删除当前进程的环境变量，避免后续 detect() 仍读到旧值
            os.environ.pop(name, None)
        except Exception as exc:
            raise RuntimeError(f"删除 Windows 环境变量 {name} 失败：{exc}")

    @staticmethod
    def _delete_windows_user_env(name: str) -> None:
        """删除 HKCU\\Environment 里的单个值。

        单独抽出只为给测试一个可打桩的写侧接缝（与读侧接缝
        _read_windows_user_env 对称）：生效版本切换失败的回滚会经
        drop_user_env 走到这里，不打桩的话测试会真删用户注册表里的值。
        """
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
        ) as key:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass  # 本来就不存在，幂等

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

    # ------------------------------------------------------------------
    # 平台无关门面：切换生效版本只调这组方法，业务层不再各自判断 CURRENT_OS。
    # 读接口读的是「持久层」（注册表 / shell rc）而不是 os.environ ——
    # os.environ 会被本工具自己改脏，不能当回滚用的"改动前状态"。
    # ------------------------------------------------------------------

    @staticmethod
    def write_user_env(name: str, value: str) -> None:
        if CURRENT_OS == "Windows":
            EnvManager.set_windows_user_env(name, value)
        else:
            EnvManager.set_unix_env(name, value)

    @staticmethod
    def drop_user_env(name: str) -> None:
        if CURRENT_OS == "Windows":
            EnvManager.remove_windows_user_env(name)
        else:
            EnvManager.remove_unix_env(name)

    @staticmethod
    def _read_windows_user_env(name: str) -> Optional[str]:
        """读 HKCU\\Environment 里某个值。单独抽出来只为给测试一个可打桩的接缝
        （Task 0 的沙箱替换它，避免测试读到用户真实的 JAVA_HOME）。"""
        import winreg  # type: ignore

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                                winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, name)
            return str(value)
        except FileNotFoundError:
            return None

    @staticmethod
    def read_user_env(name: str) -> Optional[str]:
        """读持久层里某环境变量的值，不存在返回 None。"""
        if CURRENT_OS == "Windows":
            return EnvManager._read_windows_user_env(name)
        rc = EnvManager._shell_rc_file()
        if not rc.exists():
            return None
        text = rc.read_text(encoding="utf-8")
        marker_begin = f"# >>> byte-tools:{name} >>>"
        marker_end = f"# <<< byte-tools:{name} <<<"
        if marker_begin not in text or marker_end not in text:
            return None
        block = text.split(marker_begin, 1)[1].split(marker_end, 1)[0]
        # F6：值里含引号（如 /opt/jd"k）时非贪婪 [^"]* 会在第一个引号处截断。
        # 贪婪 .* 配行末引号（. 不跨行）取同一行最后一个引号之前的全部内容，
        # 与写入端 `export NAME="value"` 的"末引号收尾"约定对得上。
        m = _re.search(r'export\s+' + _re.escape(name) + r'="(.*)"', block)
        return m.group(1) if m else None

    @staticmethod
    def add_path_entry(entry: str) -> None:
        if CURRENT_OS == "Windows":
            EnvManager.append_windows_path(entry)
        else:
            EnvManager.append_unix_path(entry)

    @staticmethod
    def drop_path_entry(entry: str) -> None:
        if CURRENT_OS == "Windows":
            EnvManager.remove_windows_path_entry(entry)
        else:
            EnvManager.remove_unix_path_entry(entry)

    @staticmethod
    def remove_path_entries_under(root: str) -> List[str]:
        """删除 root 目录内（含目录已不存在的残留）的 PATH 条目，返回被删条目列表。"""
        if CURRENT_OS == "Windows":
            return EnvManager.remove_windows_path_entries_under(root)
        return EnvManager.remove_unix_path_entries_under(root)

    @staticmethod
    def restore_path_entries(entries: List[str]) -> None:
        """把一批条目补回持久层 PATH 与当前进程 PATH（切换失败回滚专用）。

        为什么不循环调 add_path_entry：触发回滚的那一刻，add_path_entry 的
        Windows 分支（append_windows_path）往往正是刚刚失败的那条路——磁盘满、
        注册表不可写这类故障是系统性的，用同一条码路径去"补救"几乎必然再失败。
        这里改用与 remove_path_entries_under 相同的整表写入：清表那一步刚成功，
        证明这条写路径在当前故障下仍可用。
        """
        if not entries:
            return
        if CURRENT_OS == "Windows":
            current = EnvManager._read_windows_user_path()
            missing = [e for e in entries
                       if not any(EnvManager._same_path(c, e) for c in current)]
            if missing:
                EnvManager._write_registry_env("Path", ";".join(current + missing))
            for e in entries:
                EnvManager._add_process_path_entry(e)
        else:
            for e in entries:
                EnvManager.append_unix_path(e)
                # F5：append_unix_path 命中 rc 里已有 marker 时会提前 return，
                # 连进程 PATH 的同步一起跳过 → 回滚后当前进程与持久层不一致
                # （Windows 分支对每条都补 _add_process_path_entry，从不受影响）。
                # 这里按同样的原语补一次：条目已在进程 PATH 里则是无害 no-op。
                EnvManager._add_process_path_entry(e)

    @staticmethod
    def read_user_path_entries() -> List[str]:
        """读持久层里的 PATH 条目。

        ⚠ 跨平台调用者注意：两平台的语义范围**不同**——
          · Windows 返回整段用户 PATH（含用户自己写的所有条目）；
          · Unix 只返回本工具用 marker 写过的条目（rc 里用户/第三方工具的
            export PATH 行看不见）。
        想拿它做"全量备份→整表恢复"或"与进程 PATH 逐条对比"的调用方，
        必须先想清楚这个差异，否则 Unix 侧会漏掉不属于本工具的那一大截。
        """
        if CURRENT_OS == "Windows":
            return EnvManager._read_windows_user_path()
        rc = EnvManager._shell_rc_file()
        if not rc.exists():
            return []
        text = rc.read_text(encoding="utf-8")
        pattern = _re.compile(
            r"# >>> byte-tools:PATH:(.*?) >>>.*?# <<< byte-tools:PATH:\1 <<<", _re.DOTALL)
        return [m.group(1) for m in pattern.finditer(text)]

    @staticmethod
    def composed_env() -> Dict[str, str]:
        """读「Windows 为新建进程合成的环境变量块」，用于复验改完到底生效没有。

        为什么不能用现成的两处：
          · os.environ 是本进程启动时的快照，我们改完注册表它也不会重算；
          · 直接读注册表要自己复刻合成规则（系统段 + 用户段、同名谁覆盖谁、
            REG_EXPAND_SZ 什么时候展开），而实测证明这里头有非直觉的行为
            （系统 PATH 里的 %JAVA_HOME% 是按**系统**表展开定死的，用户级覆盖不影响它）。
        CreateEnvironmentBlock 就是系统自己那套合成逻辑，直接问它最准。

        返回: Dict[str, str]  键统一大写；拿不到时返回**空 dict**（非 Windows、令牌被拒、
        API 失败都算），调用方必须按"未能复验"处理，不许把空结果当成"复验通过"。
        """
        if CURRENT_OS != "Windows":
            return {}
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            advapi32 = ctypes.windll.advapi32
            userenv = ctypes.windll.userenv
            # 不设 restype/argtypes 会被 ctypes 按 32 位 int 截断句柄，
            # OpenProcessToken 就报 error 6（句柄无效）——实测踩过。
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            advapi32.OpenProcessToken.restype = wintypes.BOOL
            advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                  ctypes.POINTER(wintypes.HANDLE)]
            userenv.CreateEnvironmentBlock.restype = ctypes.c_bool
            userenv.CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                                                       wintypes.HANDLE, wintypes.BOOL]
            userenv.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]

            token = wintypes.HANDLE()
            # 只要 TOKEN_QUERY(0x0008)。用 PROCESS_QUERY_INFORMATION / _LIMITED 在受限环境里
            # 会被拒（error 5），实测过；拿进程令牌本来也不需要那两个权限。
            if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008,
                                             ctypes.byref(token)):
                return {}
            try:
                block = ctypes.c_void_p()
                if not userenv.CreateEnvironmentBlock(ctypes.byref(block), token, False):
                    return {}
                if not block.value:
                    return {}
                out: Dict[str, str] = {}
                offset = 0
                while True:
                    entry = ctypes.wstring_at(block.value + offset * 2)
                    if not entry:
                        break
                    if "=" in entry:
                        key, _, value = entry.partition("=")
                        out[key.upper()] = value
                    offset += len(entry) + 1
                return out
            finally:
                userenv.DestroyEnvironmentBlock(block)
                kernel32.CloseHandle(token)
        except Exception:
            return {}


class SwitchError(RuntimeError):
    """生效版本切换失败；抛出前已尽量回滚到切换前状态。"""


def apply_active_version(comp: Component, version: str) -> List[str]:
    """把 comp 的生效版本设为 version，并保证三处一致。

    入参 comp:    Component   目标组件
    入参 version: str         必须是磁盘上真实存在的版本（installed_versions 里的项）
    返回: List[str] 中文步骤说明，界面逐行打日志
    异常: SwitchError 目录不存在，或任一步失败（已改动的部分按快照回滚后再抛）

    设计约束（2026-09-29 与用户确认，属规格而非实现细节，决策 D3）：
      1) 同一组件在 PATH 里只允许存在"生效版本"这一条：先清掉本组件目录下的所有条目，
         再写目标版本那一条。其他组件与用户自己的条目不动。
      2) XXX_HOME、PATH、当前进程三处要么全成要么全回滚。只成一半会出现
         「mvn -v 报 21、java -version 报 17」，比改造前更糟。
      3) 回滚依据是持久层快照（read_user_env + remove_path_entries_under 的返回值），
         不是 os.environ —— 后者已被本工具改脏，不能当"改动前"。

    红线（F7，最终加固轮裁定）：**任何失败必须抛 SwitchError，不得以返回值表达失败**。
    调用方（ComponentCard._apply_active 与卸载第 4 步重排）把"正常返回"当作"全部成功"
    ——写 active 登记表、报 ok 日志。哪天有人让失败混进返回的 steps 而不抛，界面就会
    既写登记表又报成功。现网不存在这种路径（try 内任何异常都会回滚后 raise），所以
    不加运行时检查，契约以本 docstring 为准。
    """
    target = comp.install_dir(version)
    if not target.is_dir():
        raise SwitchError(f"版本目录不存在，无法设为生效：{target}")

    steps: List[str] = []
    # 读持久层而不是 os.environ：本进程可能早已被旧的切换改脏，
    # 只有注册表 / shell rc 里的值才是"切换前"的真相（约束 3）。
    prev_home = EnvManager.read_user_env(comp.env_var) if comp.env_var else None
    added_entries: List[str] = []
    removed_entries: List[str] = []

    def _rollback() -> List[str]:
        """按快照逆序撤销已落盘的改动，返回"撤不掉"的明细清单（空=回滚干净）。

        每步独立 try：一步补救失败不能拖累其余步——留下"半回滚"至少比
        异常炸穿、后面几步完全没机会执行要好。
        但失败绝不能再只 print：打包成 pythonw 跑时 stdout 被丢弃，界面上一个字
        都看不见，而日志紧接着就写"已回滚"——那是谎报。半回滚（JAVA_HOME 指 21、
        PATH 指 17）恰恰是计划红线里要求显式暴露给用户的情形，宁可吵也不能沉默，
        所以明细交回调用方拼进 SwitchError，让 UI 日志如实显示。
        """
        problems: List[str] = []
        for entry in added_entries:
            try:
                EnvManager.drop_path_entry(entry)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"PATH 新增条目没能撤掉：{entry}（{exc}）")
        if removed_entries:
            try:
                EnvManager.restore_path_entries(removed_entries)
            except Exception as exc:  # noqa: BLE001
                problems.append("切换前的 PATH 条目没能补回去："
                                + "、".join(removed_entries) + f"（{exc}）")
        if comp.env_var:
            try:
                if prev_home is None:
                    # 切换前本就没有这个变量：回滚的正确形态是删掉，
                    # 而不是写个空值——空值会让 detect() 误判"已配置"。
                    EnvManager.drop_user_env(comp.env_var)
                else:
                    EnvManager.write_user_env(comp.env_var, prev_home)
            except Exception as exc:  # noqa: BLE001
                problems.append(
                    f"{comp.env_var} 没能恢复为切换前的值"
                    f"（应为 {prev_home if prev_home is not None else '未设置'}）：{exc}")
        return problems

    try:
        if comp.env_var:
            EnvManager.write_user_env(comp.env_var, str(target))
            steps.append(f"已设置 {comp.env_var}={target}")
        removed_entries = EnvManager.remove_path_entries_under(str(CONFIG_DIR / comp.key))
        bin_dir = str(target / comp.path_subdir) if comp.path_subdir else str(target)
        # 先记账、再落盘：add_path_entry 可能"已经写进持久层、随后才抛错"
        # （注册表写成功但进程同步/广播失败，或 rc 只写了一半）。这种条目若没进
        # added_entries，回滚就只把旧条目补回来、却漏删它 → 本组件在 PATH 里留下
        # 两条同时生效的条目，比改造前更糟。反过来先记后写没有代价：
        # drop_path_entry 是幂等的，最坏是多一次无害的 no-op。
        added_entries.append(bin_dir)
        EnvManager.add_path_entry(bin_dir)
        steps.append(f"PATH 已收敛为生效版本这一条：{bin_dir}")
        if removed_entries:
            # remove_path_entries_under 是按"本组件根目录下"整片清扫的，生效版本自己
            # 那条（切换前就在 PATH 里时）也会被摘掉再重加 —— 它是"换了个位置"，
            # 不是"被移除"。写进日志就等于告诉用户"刚生效的那条被删了"（真机演练时
            # 抓到过这句自相矛盾的话），所以点名前要把它排除掉。
            others = [e for e in removed_entries if not EnvManager._same_path(e, bin_dir)]
            if others:
                steps.append("已移除同组件其他版本的条目：" + "、".join(others))
    except Exception as exc:
        problems = _rollback()
        # 回滚全成时措辞与原来完全一致；只要有一步没撤干净，就不能再说"已回滚"，
        # 并紧跟一行明细告诉用户该手动检查什么（放在成功日志末行之前）。
        state = ("已回滚到切换前状态" if not problems
                 else "已按切换前快照尝试回滚，但未完全成功")
        steps.append(f"切换失败，{state}（原 {comp.env_var or '环境变量'}="
                     f"{prev_home if prev_home is not None else '未设置'}）：{exc}")
        if problems:
            steps.append("注意：回滚未完全成功，请手动检查 "
                         f"{comp.env_var or '环境变量'} 与 PATH：" + "；".join(problems))
        raise SwitchError("；".join(steps)) from exc

    steps.append("当前进程已同步；已开着的终端与 IDE 需重开才会读到新值"
                 "（Windows 若装了 Oracle javapath，个别命令仍可能被它抢先）")
    return steps


def _atomic_write_config(data: Dict[str, object]) -> None:
    """config.json 的唯一落盘出口：先写同目录临时文件，再 os.replace 原子覆盖。

    直接对目标文件 write_text 崩在中途会留下半截 JSON，而读侧（load_active_map /
    _save_settings）把损坏文件回落成空表——用户所有"生效版本"登记就静默消失了。
    replace 在同目录内是原子覆盖：要么新内容完整就位，要么旧文件原样不动，
    最坏只残留一个 .tmp，不影响读侧。
    """
    ensure_dir(CONFIG_FILE.parent)
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)


# ---------------------------------------------------------------------------
# 「启动成功访问页」：**每个可启停组件都要有一个打开就能看的页面**
#
# 用户要求（2026-10-08）："每个可启动停止的组件启动后…不管有没有控制台，都要有个
# 访问页面能够让用户访问，让他知道确实已经启动成功了。"
#
# 两类组件分别满足：
#   ① 自带 Web 界面的（jenkins / nacos / activemq / seata / tomcat / nginx）：
#      页面就是它自己的界面或首页，直接用 `console_path` —— 不做任何转发，
#      用户看到的是真东西。
#   ② 没有 Web 界面的（elasticsearch / rabbitmq / kafka / rocketmq）：
#      ES 的根路径本来就回一段人可读的 JSON 状态，直接指它；
#      其余三个（协议端口，浏览器打开只会失败）由本工具**自己起一个小 HTTP 服务**，
#      在 127.0.0.1 的随机空闲端口上回一个「启动成功」页：组件名、运行状态、
#      各端口、控制台地址、登录凭据、日志路径、当前时间。
#
# 为什么由工具自己起服务而不是写一个静态 HTML 文件：静态文件没有"现在还在跑吗"
# 这层信息 —— 本服务的 /status 与页面每次都现算端口监听状态，
# 服务已停时页面会明说"已停止"，不会变成一张永久说"成功"的假告示。
# 只监听 127.0.0.1，不对外网暴露；端口取 OS 分配的空闲口（绝不撞用户端口）。
# ---------------------------------------------------------------------------
PAGE_SERVER_PORT: int = 0            # 0 = 让 OS 分配；运行期不改
_PAGE_SERVER: Optional["ComponentPageServer"] = None


class ComponentPageServer:
    """工具自带的"启动成功"页服务（仅 127.0.0.1，随机空闲端口）。

    用法：`show_launch_page(...)` 拿 URL；URL 形如
    `http://127.0.0.1:<port>/page/<key>`，`/page/<key>.html` 是同一个页面，
    `/<key>.html` 也能打开（把"HTML 文件"这个习惯也兼容掉）。
    """

    def __init__(self, host: str = "127.0.0.1") -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.host = host
        self._lock = threading.Lock()
        self._pages: Dict[str, object] = {}   # key → 渲染回调（每次请求现渲染）
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "byte-tools-page/1.0"
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
                path = self.path.split("?", 1)[0]
                name = ""
                if path.startswith("/page/"):
                    name = path[len("/page/"):]
                elif path in ("/", "/index.html", "/index.htm"):
                    name = "index"
                else:
                    name = path.lstrip("/")
                if name.endswith(".html"):
                    name = name[:-len(".html")]
                if name == "index":
                    return self._send(200, outer._index_html())
                body, code = outer._page_and_code(name)
                if body is None:
                    body = error_page("没有这个组件的访问页",
                                      f"路径 {path} 不对。当前有内容可看的组件页："
                                      f"{'、'.join(sorted(outer._live_keys())) or '（还没有）'}。")
                    return self._send(404, body)
                return self._send(code, body)

            def _send(self, code: int, body: str) -> None:
                raw = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, fmt: str, *args) -> None:  # noqa: A002
                return None          # 别把访问日志刷到用户终端

        try:
            self._httpd = ThreadingHTTPServer((host, PAGE_SERVER_PORT), Handler)
        except OSError:
            # 起不来也不该拖累启动流程：调用方拿不到 URL 会退化成"只打日志"
            self._httpd = None
            return
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever,
                         name="byte-tools-page-server", daemon=True).start()

    # -- 对外 ---------------------------------------------------------------
    def register(self, key: str, render) -> Optional[str]:
        """登记一个组件页的**渲染回调**，返回可访问 URL；服务没起来返回 None。

        存回调而不是存启动那一刻渲染好的 HTML（2026-10-10 改）：这一页由本工具进程内
        的小服务提供，成品 HTML 会一直挂着 —— 组件停了、端口换了、甚至重启成另一个版本，
        页面上还写着"正在运行 · 端口 N"。用户报的现象就是这么来的：
        「停止组件后浏览器还能访问，直到关掉软件才真停」。
        现在每次请求现渲染，没有运行记录就返回"已停止"，页面不再撒谎。
        """
        if self._httpd is None:
            return None
        with self._lock:
            self._pages[key] = render
        return f"http://{self.host}:{self.port}/page/{key}"

    def shutdown(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()

    # -- 页面渲染 -----------------------------------------------------------
    def _live_keys(self) -> List[str]:
        """此刻真的能出内容的组件页（停了的那些不算）。"""
        with self._lock:
            items = list(self._pages.items())
        out: List[str] = []
        for key, render in items:
            try:
                if render():
                    out.append(key)
            except Exception:      # noqa: BLE001  首页不许被一个坏页面带崩
                continue
        return out

    def _index_html(self) -> str:
        keys = sorted(self._live_keys())
        if not keys:
            return error_page("还没有正在运行的组件",
                              "启动一个组件后，这里会列出它的访问页。")
        cards = "".join(
            f'<li><a href="/page/{k}">{html_escape(k)}</a></li>' for k in keys)
        return page_shell("正在运行的组件", f"<ul class='links'>{cards}</ul>")

    def _page_and_code(self, key: str) -> Tuple[Optional[str], int]:
        """(正文, HTTP 状态)。从未登记 → (None, 404)；登记了但已停 → 说明页 + 404。"""
        with self._lock:
            render = self._pages.get(key)
        if render is None:
            return None, 404
        try:
            body = render()
        except Exception as exc:   # noqa: BLE001
            return error_page("页面生成失败",
                              f"这一页在生成时出错：{type(exc).__name__}: {exc}"), 500
        if body is None:
            return error_page(
                "这个组件已经停止",
                f"{key} 已经没有运行记录了，这一页不再有意义。"
                "要再看它，请回工具里点「启动」。"), 404
        return body, 200


def launch_success_lines(comp: "Component", spec: "LaunchSpec", rec: "RunRecord",
                         page_url: Optional[str] = None) -> List[str]:
    """启动成功后要打进组件日志的**访问指引**（用户要求：每件都要有能打开的页面）。

    对自带 Web 界面的组件，这一页就是它自己的界面；对协议端口型组件（kafka/rocketmq/
    rabbitmq），是工具自带的那张"启动成功"页 —— 无论哪种，用户都能**点一个地址就看到
    "确实起来了"**，不用自己去翻端口、猜工具。

    返回多行文本，由调用方逐行写进日志（保持既有日志渲染方式不变）。
    """
    ports = tuple(rec.ports) or (rec.port,)
    port_text = "、".join(str(p) for p in ports)
    url = page_url or rec.console_url
    lines = [
        "──────── 启动成功，访问地址 ────────",
        f"  {comp.display_name} 已在端口 {port_text} 上运行",
    ]
    if spec.console_path and page_url is None:
        lines.append(f"  控制台/首页：{url}")
    elif url:
        lines.append(f"  访问页（能看到运行状态）：{url}")
        if spec.console_path:
            lines.append(f"  它自己的控制台：{rec.console_url}")
    else:
        lines.append(f"  访问方式：{_access_hint_for(comp, spec, rec.port)}")
    if not spec.console_path and not url:
        lines.append(f"  {_access_hint_for(comp, spec, rec.port)}")
    lines.append(f"  启动日志：{Path(rec.data_dir or (CONFIG_DIR / f'{rec.key}-data')) / 'logs' / 'byte-tools.out'}")
    lines.append("────────────────────────────────────")
    return lines


def page_shell(title: str, body: str) -> str:
    """所有自带页面共用的外壳（内联样式：不依赖任何外部资源，离线可用）。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(title)}</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font-family: "Microsoft YaHei", system-ui, sans-serif; margin: 0;
        padding: 28px; line-height: 1.7; background: #f6f7f9; color: #1f2328; }}
 .card {{ max-width: 760px; margin: 0 auto; background: #fff; border-radius: 10px;
         padding: 26px 30px; box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
 h1 {{ font-size: 21px; margin: 0 0 6px; }}
 .ok {{ color: #1a7f37; font-weight: 700; }}
 .stopped {{ color: #b3261e; font-weight: 700; }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 14px; }}
 th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid #e6e8eb;
           font-size: 14px; vertical-align: top; }}
 th {{ width: 132px; color: #57606a; font-weight: 600; }}
 code {{ background: #f0f1f3; padding: 1px 6px; border-radius: 4px; font-size: 13px; }}
 a {{ color: #0969da; }}
 .links li {{ margin: 4px 0; }}
 .note {{ margin-top: 16px; font-size: 13px; color: #57606a; }}
</style></head><body><div class="card">{body}
<p class="note">这一页由 ByteTools 自带的小服务生成，只监听 127.0.0.1。
刷新可以看到最新的运行状态。</p></div></body></html>"""


def html_escape(text: object) -> str:
    """最小 HTML 转义（不引入第三方依赖）。"""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def plain_text(text: str) -> str:
    """去掉给界面日志用的 Markdown 装饰（**粗体**、`代码`），再 HTML 转义。

    卡片日志是纯文本，写 `**KRaft 模式**` 是为了醒目；但同一段文案进网页后
    星号会原样露出来（"**Kafka 没有网页控制台** —— …"），读起来像坏了。
    只处理这两个最常用的标记，不做通用 Markdown 解析。
    """
    out = str(text).replace("**", "")
    return html_escape(out.replace("`", ""))


def error_page(title: str, detail: str) -> str:
    return page_shell(title, f"<h1>{html_escape(title)}</h1><p>{html_escape(detail)}</p>")


def _is_listening_any(ports: Sequence[int]) -> bool:
    return any(port_is_listening(p) for p in ports)


def launch_page_html(comp: "Component", spec: "LaunchSpec", rec: "RunRecord",
                     checked_at: Optional[float] = None) -> str:
    """渲染某个可启停组件的「启动成功访问页」正文。

    状态是**现算**的：每次请求都重新探端口，所以服务停掉之后这张页会自己变成
    「已停止」—— 不会留下一张永远说"成功"的假告示。
    """
    ports = tuple(rec.ports) or (rec.port,)
    running = _is_listening_any(ports)
    status = ("<span class='ok'>✔ 正在运行</span>" if running
              else "<span class='stopped'>✘ 已停止（端口已释放）</span>")
    native = spec.console_path
    rows: List[Tuple[str, str]] = [
        ("组件", html_escape(comp.display_name)),
        ("状态", status),
        ("版本", html_escape(rec.version)),
        ("端口", "、".join(str(p) for p in ports)),
        ("安装目录", f"<code>{html_escape(rec.home)}</code>"),
    ]
    if native:
        rows.append(("控制台", f'<a href="{html_escape(rec.console_url)}">'
                               f'{html_escape(rec.console_url)}</a>'))
    else:
        rows.append(("访问方式", html_escape(_access_hint_for(comp, spec, rec.port))))
    if spec.data_dir_env and rec.data_dir:
        rows.append(("数据目录", f"<code>{html_escape(rec.data_dir)}</code>"))
    log_file = Path(rec.data_dir or (CONFIG_DIR / f"{rec.key}-data")) / "logs" / "byte-tools.out"
    rows.append(("启动日志", f"<code>{html_escape(log_file)}</code>"))
    if spec.risk_note:
        rows.append(("留意", plain_text(spec.risk_note.split("。")[0]) + "。"))
    try:
        creds = credentials_for(comp, spec, rec.port)
        if creds:
            rows.append(("登录信息", "<br>".join(plain_text(c) for c in creds)))
    except Exception:
        pass
    when = time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(checked_at or time.time()))
    rows.append(("本页刷新时间", html_escape(when)))
    table = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    head = (f"<h1>{html_escape(comp.display_name)} 启动成功</h1>" if running
            else f"<h1>{html_escape(comp.display_name)} 已停止</h1>")
    return page_shell(f"{comp.display_name} 访问页",
                      head + f"<table>{table}</table>")


def _access_hint_for(comp: "Component", spec: "LaunchSpec", port: int) -> str:
    """没有 Web 界面的组件"该怎么访问"的实话（按组件给，不写死端口）。"""
    return {
        "elasticsearch":
            f"http://127.0.0.1:{port}/ 用浏览器或 curl 打开会返回集群 JSON 状态"
            f"（这是 ES 的正常形态，它没有图形界面）；图形界面请另装 Kibana。",
        "kafka":
            f"Kafka 的 {port} 说 Kafka 二进制协议，浏览器打不开是正常的。"
            f"用安装目录 bin/windows/kafka-topics.bat --bootstrap-server "
            f"localhost:{port} --list 验证。",
        "rocketmq":
            f"RocketMQ 的 {port} 说 RocketMQ 二进制协议，浏览器打不开是正常的。"
            f"用安装目录 bin/mqadmin clusterList -n localhost:{port} 验证"
            f"（能列出 broker 才算真的起来了）。",
        "rabbitmq":
            f"RabbitMQ 的 {port} 说 AMQP 协议，浏览器打不开是正常的。"
            f"客户端连接串：amqp://guest:guest@127.0.0.1:{port}/"
            f"（guest 默认只允许本机）；查状态用 sbin/rabbitmqctl.bat status。",
    }.get(comp.key, f"该组件在端口 {port} 上服务，请用对应的客户端工具访问。")


def get_page_server() -> Optional["ComponentPageServer"]:
    """惰性取页服务：失败返回 None（调用方要能接受"没有页面"这条路）。"""
    global _PAGE_SERVER
    if _PAGE_SERVER is None:
        try:
            _PAGE_SERVER = ComponentPageServer()
        except Exception:
            return None
        if _PAGE_SERVER._httpd is None:      # 端口被占/权限问题：不重试、不报错
            return None
    return _PAGE_SERVER


def show_launch_page(comp: "Component", spec: "LaunchSpec", rec: "RunRecord") -> Optional[str]:
    """登记该组件的访问页并返回 URL；服务起不来返回 None。

    **每个可启停组件都会拿到一个 URL**：
      - 自带 Web 界面（含 ES 的 JSON 根路径）：URL 就是该组件自己的地址；
      - 没有 Web 界面：URL 指向本工具自带的"启动成功"页。
    所以"启动后一定有个能打开的页面"这件事对 10 个组件都成立。
    """
    if spec.console_path:
        return rec.console_url
    server = get_page_server()
    if server is None:
        return None

    def _render() -> Optional[str]:
        # 每次请求现查运行记录：停了就没了，端口换了就跟着换。
        rec_now = load_running_map().get(comp.key)
        if rec_now is None:
            return None
        return launch_page_html(comp, spec, rec_now)

    return server.register(comp.key, _render)


@dataclass
class RunRecord:
    """一条运行登记。

    pid_role 是显式字段而不是省略约定：spec §2 实测到 Nacos / ActiveMQ 的启动脚本
    会自己后台化，脚本返回的 PID 几秒后就不是服务进程了。把"这个 PID 是什么身份"
    写下来，才不至于以后有人拿 launcher 的 PID 判生死。
    """
    key: str
    version: str
    home: str
    data_dir: str
    port: int
    console_url: str
    pid: int
    pid_role: str            # "server" | "launcher" | "none"
    started_at: float
    launcher_cmd: List[str]
    # 端口簇：主口 ∪ 派生口 ∪ 独立口。"运行中"与"停干净"都按这一组判，
    # 因为 Nacos 主口掉了而 gRPC 还在听时，按单口判会清登记、留下两个没人认领的监听口。
    # 默认 () 只表示"计划一写的旧文件里没这个字段"，加载侧会归一成 (port,)——
    # 默认值不是可选性，它决定旧记录会不会被整批静默丢弃。
    ports: tuple = ()

    def to_dict(self) -> Dict[str, object]:
        return dict(self.__dict__)


def load_running_map() -> Dict[str, RunRecord]:
    """读取运行登记表。文件缺失、JSON 坏了、记录缺字段，一律当空表。

    这里"宽容"是有意的：running.json 删了只是重新发现一遍本机进程，
    而让它把整个界面搞崩、或者据此去动进程，代价完全不成比例。"""
    if not RUNNING_FILE.exists():
        return {}
    try:
        data = json.loads(RUNNING_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, RunRecord] = {}
    for item in data.values():
        if not isinstance(item, dict):
            continue
        try:
            rec = RunRecord(**item)
        except (TypeError, KeyError):
            continue
        if rec.pid_role not in ("server", "launcher", "none"):
            continue
        # Task 2 复盘裁决：手改的 running.json 常把端口存成 "80480" 这类字符串，
        # 不在这儿归一就会让字符串一路流进后续每一次端口探测。数字字段读侧归一成
        # int/float；转不动的（如 port="http"）与坏 pid_role 同一政策——整条丢弃。
        try:
            rec.port = int(rec.port)
            rec.pid = int(rec.pid)
            rec.started_at = float(rec.started_at)
        except (TypeError, ValueError):
            continue
        # ports 是计划二新加的字段。旧文件没有它 → 从 port 归一，绝不因为"缺字段"丢记录。
        raw_ports = item.get("ports", ())
        if isinstance(raw_ports, (int, str)):          # 手改成标量时按单口理解
            raw_ports = (raw_ports,)
        try:
            ports = tuple(int(p) for p in raw_ports)
        except (TypeError, ValueError):
            continue                                    # 转不动的按既有政策丢整条
        rec.ports = ports or (rec.port,)
        out[rec.key] = rec
    return out


def save_running_map(records: Dict[str, RunRecord]) -> None:
    """running.json 的唯一落盘出口，照 _atomic_write_config 的临时文件 + os.replace。"""
    ensure_dir(RUNNING_FILE.parent)
    payload = {rec.key: rec.to_dict() for rec in records.values()}
    tmp = RUNNING_FILE.with_name(RUNNING_FILE.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, RUNNING_FILE)


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """本机这个口是否空闲。**判据是"能不能自己绑上"，不是"能不能连上"。**

    原来是 `connect_ex != 0`（能不能连上）。那只能证明"没人接受连接"，
    证不了"没人占着这个口"：真机 2026-10-06 实测到只绑在 `[::]:8848`
    （IPv6 通配）时，`connect_ex(("127.0.0.1", 8848))` 照样返回非 0 →
    判定"空闲" → 于是选了 8848 → 厂商脚本按 0.0.0.0 绑端口时撞上
    `Port 8848 was already in use`，用户看到的是"启动失败"。

    改成亲自 bind 一次：绑不上（OSError）就是有人占着。这与"我们要做的事"
    完全同构 —— 我们也是要 bind 这个口起服务，问它"能不能绑"才是对的问法。
    SO_REUSEADDR 不给：Windows 上它允许抢占 TIME_WAIT 状态的端口，
    那正是我们要避开的"刚停完还没释放干净"的场景。
    """
    for family, addr in ((socket.AF_INET, (host, port)),
                         (socket.AF_INET6, ("::1", port))):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.bind(addr)
        except OSError:
            return False
    return True


def pick_free_cluster(base_port: int, offsets: tuple = (), span: int = 99,
                      is_free=port_is_free) -> Optional[int]:
    """在 [base_port, base_port + span] 内升序找“整簇同时空闲”的最小主端口；找不到返回 None。

    规则写死成“最小 + 整簇”，是为了让界面显示的端口可复现：随机挑会让同一个环境
    两次启动落在不同口上，故障归因和文档都没法写（设计 §4）。"""
    all_offsets = tuple(dict.fromkeys((0,) + tuple(offsets)))
    for candidate in range(base_port, base_port + span + 1):
        if all(is_free(candidate + off) for off in all_offsets):
            return candidate
    return None


def port_is_listening(port: int, host: str = "127.0.0.1") -> bool:
    """端口是否有人在听。connect_ex == 0 才算有人。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


# 监听态在两个平台上拼写不同：Windows 是 LISTENING，POSIX（Linux/macOS/BSD）是 LISTEN。
# 只认一个的话，端口反查在另一个平台上恒返回 {}，而失败方向是安全的（宁可不杀），
# 代价是强制结束功能在那儿静默失灵。
_NETSTAT_LISTEN_STATES = ("LISTENING", "LISTEN")


def parse_netstat_listeners(text: str) -> Dict[int, Set[int]]:
    """把 `netstat -ano` 的文本解析成 {端口: {PID, …}}，只认监听态的行。

    按列形状定位、不按表头：中文 Windows 的表头是本地化的
    （"协议 本地地址 外部地址 状态 PID"），而状态值不翻译（仍是 LISTENING）。
    任何依赖表头文字的写法在中文系统上会整体失灵。

    状态值必须收全 Windows 的 LISTENING 与 POSIX 的 LISTEN：
    BSD 系的行形如 "tcp4 0 0 127.0.0.1.8848 *.* LISTEN 12345"，状态在倒数第一列、
    PID 在倒数第二列，与 Windows 正好相反 —— 所以下面按尾部的形状选列序。
    只认LISTENING 的话，本解析器在 Linux/macOS 上恒返回 {}，
    端口反查在那两个平台上会静默变成"找不到对象"，功能哑掉而不是报错。"""
    out: Dict[int, Set[int]] = {}
    for line in text.splitlines():
        parts = line.split()
        # 协议列：Windows 是 TCP/TCPv6，POSIX 是 tcp4/tcp6（udp4 会被这里挡掉）。
        if not parts or not parts[0].lower().startswith("tcp") or len(parts) < 5:
            continue
        if parts[-2].upper() in _NETSTAT_LISTEN_STATES:
            local_i, pid_i = -4, -1              # Windows 列序
        elif parts[-1].upper() in _NETSTAT_LISTEN_STATES:
            local_i, pid_i = -4, -2              # POSIX 列序
        else:
            continue
        try:
            # 列序（split 后）：Windows [-1]=PID、[-2]=状态、[-3]=**外部地址**、[-4]=本地地址。
            # 端口在**本地地址**上，也就是 parts[-4]。写成 -3 会取到外部地址的 0
            # （"0.0.0.0:0" / "[::]:0"），于是所有监听行都归到端口 0 —— 这是计划初稿的 off-by-one，
            # 由 Task 4 的实现者按自家用例暴露出来并改对；改错的写法过不了下面任何一条用例。
            # 本地地址的分隔符两个平台不同：Windows 是 "0.0.0.0:8848" / "[::]:8848"（冒号），
            # POSIX 是 "127.0.0.1.8848" / "*.8848"（点）。只认一种分隔符，
            # 就会在另一个平台上恒取不到端口 —— 所以两种都切一次。
            local = parts[local_i].rsplit(":", 1)[-1].rsplit(".", 1)[-1]
            port = int(local)
            pid = int(parts[pid_i])
        except ValueError:
            continue
        out.setdefault(port, set()).add(pid)
    return out


def _pick_unique_pids(table: Dict[int, Set[int]],
                      ports: Sequence[int]) -> Dict[int, int]:
    """只保留"归属唯一"的端口。两个 PID 同听一口时宁可不动手——
    误杀的代价远大于这次停不掉。"""
    return {p: next(iter(table[p])) for p in ports if len(table.get(p, ())) == 1}


def netstat_listener_pids(ports: Sequence[int]) -> Dict[int, int]:
    """端口 → 唯一监听 PID。**这是子进程调用，只许出现在 stop/force_stop 路径**；
    出现在 status/adopt/reconcile 里就等于从后门放掉"状态检测绝不执行进程"。"""
    try:
        kw = dict(capture_output=True, timeout=10,
                  text=True, encoding="utf-8", errors="replace")
        if CURRENT_OS == "Windows":
            # 静默外部命令（与 main.py 里其它外部命令同一惯例）：
            # 从 GUI 点"强制结束"时，不带这个标志会闪一个黑框。
            kw["creationflags"] = CREATE_NO_WINDOW
        done = subprocess.run(["netstat", "-ano"], **kw)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return _pick_unique_pids(parse_netstat_listeners(done.stdout or ""), ports)


def running_process_images(image_names: Sequence[str]) -> List[str]:
    """这些映像名里，哪些此刻正在本机跑着（返回命中的名字，顺序同入参）。

    用 `tasklist /FO CSV /NH` 而不是默认的表格输出：CSV 第一列恒为映像名，
    而中文系统上那句"没有运行的任务匹配指定标准"是本地化的散文，按形状就进不了判定。
    只按名字**精确**比对（大小写不敏感）—— "erl.exe" 不该匹配上 "erlsrv.exe"。

    **这又是一次子进程调用，与端口反查同一类**：只允许出现在停止路径的收尾提示里，
    出现在 status / adopt / reconcile 就等于放掉"状态检测绝不执行进程"。
    非 Windows 上没有 tasklist → OSError → 空表：提示自然消失，绝不无中生有。
    """
    hits: List[str] = []
    for name in image_names or ():
        try:
            kw = dict(capture_output=True, timeout=10,
                      text=True, encoding="utf-8", errors="replace")
            if CURRENT_OS == "Windows":
                kw["creationflags"] = CREATE_NO_WINDOW
            done = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}",
                                   "/FO", "CSV", "/NH"], **kw)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in (done.stdout or "").splitlines():
            first = line.split('","')[0].strip('"').lower()
            if first == name.lower():
                hits.append(name)
                break
    return hits


def _leftover_process_note(found: Sequence[str]) -> str:
    """停止成功后的残留辅助进程提示；没查到东西就返回空串（不许每次都念一遍）。"""
    if not found:
        return ""
    return (f"注意：{'、'.join(found)} 还在运行 —— 它是该组件启动脚本留下的辅助进程，"
            f"本工具不会去结束它。"
            f"它的工作目录一般仍在版本目录里，Windows 上会让随后的卸载删不掉那个目录；"
            f"要彻底卸载请先结束该进程（或重启机器）再点卸载。")


# ActiveMQ 回写的两个锚点，全部来自 2026-10-05 真包实测（spec 计划二 §2.1）。
# 写成常量是为了"锚不上"时的报错能指名道姓，而不是泛泛一句"配置不认识"。
AMQ_CONSOLE_FILE = "jetty-spring.properties"
AMQ_CONSOLE_KEY = "jetty.http.port"
AMQ_BROKER_FILE = "activemq.xml"
# 注意用的是 _re 而不是 re：main.py 里正則只在 1959 行以 `import re as _re` 引入过，
# 模块里没有裸 `re` 这个名字 —— 写 re.compile 会在 import 阶段就 NameError。
_PORT_TAIL_RE = _re.compile(r"(uri=\"[a-z]+://[^\":]+:)(\d+)(\?)")


def conf_targets(data_dir: Path) -> Tuple[Path, Path, Path]:
    """副本根目录、控制台端口文件、broker 传输口文件。三处共用一份定义。"""
    conf = data_dir / "conf"
    return conf, conf / AMQ_CONSOLE_FILE, conf / AMQ_BROKER_FILE


def prepare_conf_copy(src: Path, dst: Path) -> Tuple[str, List[str]]:
    """建立/核对 ActiveMQ 的配置副本，返回 ("created"|"exists", 差异文件列表)。

    整目录拷贝而不是只拷两个端口文件：实测 conf/login.config 里的 JAAS 用的是
    相对文件名（users.properties / groups.properties，由 activemq.conf 解析），
    拷不全的话控制台鉴权会静默失效。
    副本一旦存在就是权威：不覆盖、不自动补，只把"官方有、副本没有"的文件名报出来——
    补哪些、用什么内容补，等于猜厂商的升级意图。"""
    if not dst.exists():
        ensure_dir(dst)
    else:
        present = {p.relative_to(dst).as_posix()
                   for p in dst.rglob("*") if p.is_file()}
        missing = sorted(p.relative_to(src).as_posix()
                         for p in src.rglob("*") if p.is_file()
                         and p.relative_to(src).as_posix() not in present)
        return "exists", missing
    created: List[str] = []
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = f.relative_to(src)
        target = dst / rel
        ensure_dir(target.parent)
        shutil.copy2(f, target)
        created.append(rel.as_posix())
    return "created", created


def _atomic_write(path: Path, text: str) -> None:
    """照 running.json 那套临时文件 + os.replace：写一半崩了不留半截配置。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _backup_once(path: Path) -> None:
    """只在首次改动前留一份 .bak；第二次改不留 .bak.bak，那是噪音。"""
    bak = path.with_name(path.name + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)


def set_kafka_log_dirs(conf: Path, log_dirs: str) -> Tuple[bool, str]:
    """把 KRaft server.properties 的 log.dirs 写成**绝对路径**。

    为什么必须改：官方默认是 `/tmp/kraft-combined-logs`（正斜杠），
    Windows 解析成 `C:\\tmp\\...` —— 落在盘符根、**不在安装目录也不在数据目录**。
    后果有两条（都是实测）：
      - 卸载删不掉它，多版本并存会抢同一个目录；
      - 目录不存在时 `kafka.Kafka` 直接 `rc=1 / No readable meta.properties files found.`
        —— **`kafka.Kafka` 不会自己建目录，只有 format 会建**。

    用正斜杠：Windows 的 Java 对 `C:/x/y` 与 `C:\\x\\y` 都认，
    但反斜杠在 properties 里是转义符，写 `C:\tmp` 会被吃掉一段。
    """
    return set_property_line(conf, "log.dirs", log_dirs)


def kafka_cluster_id_file(data_dir: Path) -> Path:
    """KRaft 的 cluster.id 存这 —— 必须复用同一个，否则每次 format 都会被拒。

    实测：同 uuid + `--ignore-formatted` ⇒ rc=0 幂等；
    换 uuid ⇒ `rc=1 Invalid cluster.id`。
    所以 uuid 只生成一次，之后读回来用。
    """
    return data_dir / "cluster.id"


def read_or_create_cluster_id(data_dir: Path) -> str:
    """读回上次的 cluster.id，没有就生成一个新的并落盘。"""
    path = kafka_cluster_id_file(data_dir)
    try:
        got = path.read_text(encoding="utf-8").strip()
        if got:
            return got
    except OSError:
        pass
    new_id = str(uuid.uuid4())
    ensure_dir(data_dir)
    path.write_text(new_id, encoding="utf-8")
    return new_id




def set_nginx_listen(nginx_conf: Path, port: int) -> Tuple[bool, str]:
    """把 nginx.conf 里 server 块的 `listen <端口>` 改成指定端口。

    实测坑（2026-10-06）：nginx.conf 里除了真正生效的 `listen 80;`，
    还有**十几行被注释掉的示例**（`#listen 8080;`、`#listen 443 ssl;` …）。
    裸字符串替换会打到注释行 —— 文件显示改了，运行时仍是 80，**静默失效**。
    所以要先抹掉注释块再匹配，跟 set_tomcat_ports 同一个套路。
    """
    try:
        raw = nginx_conf.read_bytes()
    except OSError as exc:
        return False, f"读不到 {nginx_conf.name}：{exc}"
    text = raw.decode("utf-8", errors="replace")
    clean = _re.sub(r"<!--.*?-->", lambda m: _re.sub(r"[^\r\n]", " ", m.group(0)),
                    text, flags=_re.S)
    # 只改行首缩进后紧跟 listen 的（server 块里那一条），不带 ssl/默认值后缀
    m = _re.search(r"^(\s*)listen\s+(\d+)([^;\r\n]*;)", clean, _re.M)
    if not m:
        return False, (f"{nginx_conf.name} 里找不到未注释的 listen 指令"
                       f"（官方默认写法被改过）。请手工把 HTTP 端口改成 {port} 后再启动。")
    if m.group(2) != str(port):
        clean = clean[:m.start(2)] + str(port) + clean[m.end(2):]
    if clean == text:
        return True, ""
    _backup_once(nginx_conf)
    try:
        nginx_conf.write_bytes(clean.encode("utf-8", errors="replace"))
    except OSError as exc:
        return False, f"写不回 {nginx_conf.name}：{exc}"
    return True, ""


def set_tomcat_ports(server_xml: Path, http_port: int,
                     shutdown_port: int) -> Tuple[bool, str]:
    """改 tomcat conf/server.xml 里的 HTTP 端口与 shutdown 端口。

    **这个函数存在的原因是被坑逼出来的**（2026-10-06 真机30 次启停实测）：

    server.xml 里有 **4 处 `port=`**，但只有 2 处生效（其余被 `<!-- -->` 注释）：
      :22  shutdown=8005    ✅ 生效
      :70  Connector HTTP  ✅ 生效   ← 主端口
      :78  第二个 8080        ❌ 在注释块里
      :92/:1088443 / 8009   ❌ 在注释块里

    三个 naive 写法的实测后果：
      - 按出现顺序改第 1 处 `port=` →改到的是 :22 的 **shutdown 端口**，
        结果**主端口没变、停止能力被破坏**；
      - 用 `re.sub` 带 `count=1` 只换第一处 `port=` → 同样命中 :22；
      - 直接改 :78 那处（注释行）→ 文件显示18081，**运行时仍是 8080（静默失效）**。

    做法：先把注释块内容用等长空格替换（保持行号与字节偏移不变），
    再在"干净文本"上找 `protocol="HTTP/1.1"` 的 Connector 改它的 port，
    最后按原编码写回。shutdown 端口单独按注释外的 `port=` 第一个改。
    全程保持 CRLF，不重排文件。
    """
    try:
        raw = server_xml.read_bytes()
    except OSError as exc:
        return False, f"读不到 {server_xml.name}：{exc}"
    text = raw.decode("utf-8", errors="replace")

    # 1) 记下注释块的区间，**但原文本一个字节都不动**。
    #    第一版这里把 <!--...--> 整块替换成等长空格再整体写回——
    #    端口是改对了，可**注释内容全被抹掉**（8 个注释块变 0 个）。
    #    字节数不变不等于没破坏：用户打开配置看到的是一片空白。
    spans = [m.span() for m in _re.finditer(r"<!--.*?-->", text, flags=_re.S)]

    def in_comment(pos: int) -> bool:
        """该偏移是否落在注释块内。注释里的候选一律跳过 —— 改它不生效还污染文件。"""
        return any(a <= pos < b for a, b in spans)

    # 2) 找 HTTP Connector 的 port（取**第一个未被注释的** <Connector>）。
    #    先摘出整个标签再在标签内找 port：厂商原文是
    #    `<Connector port="8080" protocol="HTTP/1.1"`（**port 在 protocol 之前**），
    #    写成 `protocol=...port=` 那种顺序依赖的正则会一个都匹配不上、
    #    返回"找不到 Connector"，端口永远改不动。属性顺序不是厂商承诺。
    out = text
    conn = next((cm for cm in _re.finditer(r"<Connector\b[^>]*>", text, _re.S)
                 if not in_comment(cm.start())), None)
    if conn is None:
        # 措辞要指名要找的锚（protocol="HTTP/1.1"）：说"找不到 Connector"，
        # 用户不知道该去改哪一行。护栏 test_tomcat_refuses_and_writes_nothing_
        # when_no_live_http_connector 钉的就是这一句。
        return False, (f"{server_xml.name} 里找不到**未被注释的** "
                       f"<Connector port=... protocol=\"HTTP/1.1\"> 标签"
                       f"（官方默认写法被改过，或整段被注释掉了）。"
                       f"请手工把生效的那个 HTTP Connector 端口改成 {http_port} 后再启动。")
    tag = conn.group(0)
    if 'protocol="HTTP/1.1"' not in tag:
        return False, (f"{server_xml.name} 里第一个生效的 <Connector> 不是 "
                       f"protocol=\"HTTP/1.1\"（实际是 {tag[:80]}）。"
                       f"本工具不猜该改哪个，请手工把 HTTP 端口改成 {http_port} 后再启动。")
    pm = _re.search(r'\bport="(\d+)"', tag)
    if not pm:
        return False, (f"{server_xml.name} 的 HTTP Connector 里没有 port 属性"
                       f"（官方默认写法被改过）。请手工改成 {http_port} 后再启动。")
    if pm.group(1) != str(http_port):
        at = conn.start() + pm.start(1)
        out = out[:at] + str(http_port) + out[at + len(pm.group(1)):]

    # 3) shutdown 端口：未被注释的 <Server ...> 里的 port（实测是第22 行那一处）。
    #    **必须一起改** —— 只改主端口时，若另一实例占着 8005，
    #    新实例 bind 失败自杀，而 shutdown.bat 会去杀掉 8005 的真正持有者
    #    并返回 rc=0，看起来完全成功。
    for sm in _re.finditer(r"<Server\b[^>]*>", text, _re.S):
        if in_comment(sm.start()):
            continue
        sp = _re.search(r'\bport="(\d+)"', sm.group(0))
        if sp and sp.group(1) != str(shutdown_port):
            at = sm.start() + sp.start(1)
            out = out[:at] + str(shutdown_port) + out[at + len(sp.group(1)):]
        break

    clean = out
    if clean == text:
        return True, ""                        # 已经是目标值：一个字节都不写
    _backup_once(server_xml)
    try:
        # 按原编码写回：官方 server.xml 是 UTF-8，但保持 len 一致更安全
        server_xml.write_bytes(clean.encode("utf-8", errors="replace"))
    except OSError as exc:
        return False, f"写不回 {server_xml.name}：{exc}"
    return True, ""


def set_property_line(path: Path, key: str, value: str) -> Tuple[bool, str]:
    """把 properties 文件里的 `key=<旧值>` 改成 `key=<新值>`，锚不到就拒改。

    幂等靠读出来判断：已经是目标值就一个字都不写（不改 mtime、不多备份），
    这样反复点启动不会刷出一堆 .bak。只认"行首正好是 key="的形状——
    用户手加空格或行尾注释时我们不猜他的写法，明确拒绝并告诉他改哪一行。"""
    want = f"{key}={value}"
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        return False, f"读不到 {path.name}：{exc}"
    if any(line.rstrip("\r\n") == want for line in lines):
        return True, ""
    hits = [n for n, line in enumerate(lines) if line.startswith(f"{key}=")]
    if not hits:
        return False, (f"{path.name} 里找不到 {key}= 这一行（官方默认写法被改过）。"
                       f"请手工把该文件里的 {key} 改成 {value} 后再启动。")
    n = hits[0]
    lines[n] = want + "\n"
    _backup_once(path)
    _atomic_write(path, "".join(lines))
    return True, ""


def set_openwire_port(path: Path, port: int) -> Tuple[bool, str]:
    """改 activemq.xml 里 name="openwire" 那一行的端口，只动 uri 里的数字。"""
    target = f"uri=\"tcp://0.0.0.0:{port}?"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"读不到 {path.name}：{exc}"
    lines = text.splitlines(keepends=True)
    hits = [n for n, line in enumerate(lines) if "name=\"openwire\"" in line
            and "<!--" not in line]
    if not hits:
        return False, (f"{path.name} 里找不到可改的 openwire transportConnector 行"
                       f"（被注释掉或写法不是默认那样）。请手工把 broker 端口改成 {port}。")
    n = hits[0]
    if target in lines[n]:
        return True, ""                                   # 已经是目标值
    new, cnt = _PORT_TAIL_RE.subn(lambda m: f"{m.group(1)}{port}{m.group(3)}", lines[n], count=1)
    if cnt != 1:
        return False, (f"{path.name} 第 {n + 1} 行的 uri 写法不认识，不敢改。"
                       f"请手工把 openwire 端口改成 {port}。")
    lines[n] = new
    _backup_once(path)
    _atomic_write(path, "".join(lines))
    return True, ""


@dataclass
class PortPlan:
    """一次启动最终要用的端口。三种角色分开存，是因为它们的来源不同：
    派生口由主口按厂商规则算出来，独立口有自己的基准。合成一个 tuple 存就不区分得开了。"""
    main: int = 0
    derived: Tuple[int, ...] = ()
    extras: Tuple[int, ...] = ()

    @property
    def all_ports(self) -> Tuple[int, ...]:
        # main 为 0 表示"没规划成功"，这时必须返回空簇，不能返回 (0,)：
        # 失败路径返回的 PortPlan() 会被start() 拿去做登记与探活，
        # 把端口 0 登记进去等于凭空造一个"占用中的端口 0"。
        if not self.main:
            return ()
        return (self.main,) + tuple(self.derived) + tuple(self.extras)


def occupant_of(port: int) -> Tuple[Optional[int], str]:
    """占着这个端口的 (PID, 进程名)。查不到就返回 (None, "")。

    拿进程名是为了让"端口被占"这句话能指名道姓：用户看到"被 jenkins.jar(pid 1234) 占用"
    才知道该关哪个，而不必自己去翻任务管理器。
    """
    try:
        table = parse_netstat_listeners(_netstat_text())
    except Exception:
        return None, ""
    pids = sorted(table.get(port, ()))
    if not pids:
        return None, ""
    pid = pids[0]
    return pid, _process_name(pid)


def _netstat_text() -> str:
    try:
        kw = dict(capture_output=True, timeout=10,
                  text=True, encoding="utf-8", errors="replace")
        if CURRENT_OS == "Windows":
            kw["creationflags"] = CREATE_NO_WINDOW
        return subprocess.run(["netstat", "-ano"], **kw).stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _process_name(pid: int) -> str:
    """进程名（可执行文件名）。查不到就回空串，不影响主流程。"""
    try:
        if CURRENT_OS == "Windows":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, timeout=10, text=True,
                encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW)
            parts = (out.stdout or "").strip().split('","')
            if len(parts) >= 2 and parts[0]:
                return parts[0].strip('" ') or f"PID {pid}"
            return f"PID {pid}"
        out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                             capture_output=True, timeout=10, text=True)
        return (out.stdout or "").strip() or f"PID {pid}"
    except (OSError, subprocess.TimeoutExpired):
        return f"PID {pid}"


def credentials_for(comp: Component, spec: LaunchSpec, port: int) -> List[str]:
    """启动成功后要把登录凭据打进组件日志的行列表（可能为空）。

    `spec.credentials_hint` 是**厂商出厂默认值**；这里会在能拿到真实值时把它替换/补全：

    · Jenkins 的初始管理员密码是**首次启动随机生成**的，登记里写不了死。
      真值在 `<JENKINS_HOME>/secrets/initialAdminPassword`，读出来才是有用的 ——
      用户要的就是能直接复制去登录的那个串。
    · 端口在 hint 里是写死的默认值，但端口被占用时我们不换端口（2026-06起不平移），
      所以端口直接用本次实际监听的，hint 里的端口文本照样成立；万一将来又允许换端口，
      这里用 f-string 重新拼就不会说错。
    · 读不到就说读不到，**不许编一个看起来像密码的串**给用户。
    """
    if not spec.credentials_hint:
        return []
    # hint 里的端口是厂商默认值。当前策略是不平移（端口被占就结束占用者），
    # 所以实际端口恒等于默认值，hint 文本可以直接用；
    # 万一将来允许换端口，这里检测到不一致就该说清"实际是哪个"，不能让人照着
    # 默认端口去连一个不存在的地址。
    if port != spec.main_port:
        lines = [spec.credentials_hint.replace(
            f"127.0.0.1:{spec.main_port}", f"127.0.0.1:{port}")]
    else:
        lines = [spec.credentials_hint]

    if comp.key == "jenkins":
        # 随机密码只能从文件读。JENKINS_HOME 优先取登记里的 data_dir_env 值，
        # 回落到 CONFIG_DIR/<key>-data（与 build_launch_plan 的算法一致）。
        home = (plan_data_dir(comp, spec) or (CONFIG_DIR / f"{comp.key}-data"))
        pwd_file = home / "secrets" / "initialAdminPassword"
        try:
            pwd = pwd_file.read_text(encoding="utf-8").strip()
        except OSError:
            pwd = ""
        if pwd:
            lines.append(f"初始管理员密码（本机实际值）：{pwd}")
        else:
            lines.append(f"初始管理员密码：读不到 {pwd_file}；"
                         f"若已完成解锁向导，用你自己设置的密码登录。")
    return lines


def plan_data_dir(comp: Component, spec: LaunchSpec) -> Optional[Path]:
    """按 build_launch_plan 的同一规则算出 data_dir（拿不到就返回 None）。"""
    if not spec.data_dir_env:
        return None
    return CONFIG_DIR / f"{comp.key}-data"


def evict_port_occupant(port: int, label: str,
                        evicted: Optional[List[str]] = None) -> Optional[str]:
    """把占着 `port` 的进程结束掉。成功返回 None；失败返回一句中文原因。

    **无条件结束占用者**（用户 2026-10-06 明确要求）：端口被占就杀掉再启动，
    不做端口平移。理由见 choose_ports 的说明——平移会让"服务起来了但外部客户端
    连不上"，因为 Nacos/ActiveMQ 的默认端口是被外部配置硬编码的。

    两条硬守卫，删掉任何一条都会造成不可逆的误伤：
    ① 绝不结束我们自己（pid == os.getpid()）—— 否则本工具会把自己刚起的进程杀掉；
    ② 归属不唯一（同口多个 PID）时不结束任何一个 —— 宁可启动失败也不赌。
    """
    if CURRENT_OS != "Windows":
        return f"端口 {port}（{label}）被占用；当前只支持在 Windows 上自动结束占用者"
    pid, name = occupant_of(port)
    if pid is None:
        # netstat 说有、却反查不到唯一归属（比如进程刚好退了）：不能猜，只当没查到。
        return None
    if pid == os.getpid():
        return f"端口 {port}（{label}）被本工具自己的其他进程占用（PID {pid}），不能结束自己"
    if not pid_alive(pid):
        return None          # 占用者已经退了，当作清场成功
    try:
        os.kill(pid, 9)
    except OSError as exc:
        return f"端口 {port}（{label}）被 {name}（PID {pid}）占用，结束它失败：{exc}"
    if evicted is not None:
        evicted.append(f"{port} ← {name}（PID {pid}）已结束")
    return None


def _tasklist_pid_exists(pid: int) -> bool:
    """用 tasklist 精确判断 PID 是否存在（**不做子串匹配**）。

    为什么不能用 `str(pid) in stdout`（2026-10-08 真机实测定位）：
    tasklist 的 CSV 里除了 PID 还有**内存用量**那一列，而它是「912,560 K」这种
    带千分位的数字 —— `pid=91256` 会命中 `912,560 K`，于是**一个早就退出的 PID
    被判成活着**。后果很具体：jenkins 的 java 启动器退出后，running.json 里那行
    PID 已经不存在，`force_stop` 却以为它还在，os.kill 打在一个不存在的 PID 上，
    真正监听端口的子进程毫发无伤 —— 用户点"停止"永远停不掉，只能去任务管理器。
    解析成字段再比，才是"这个 PID 存在吗"这个问题的答案。
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=10, text=True,
            encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        # 查不到就当活着（宁可多等，不可误杀）—— 与旧行为一致
        return True
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        fields = [f.strip().strip('"') for f in line.split('","')]
        if len(fields) >= 2 and fields[0] and fields[1].isdigit():
            if int(fields[1]) == int(pid):
                return True
    return False


def process_alive(pid: int) -> bool:
    """PID 是否还活着。查不到就当活着（宁可多等，不可误杀）。"""
    try:
        if CURRENT_OS == "Windows":
            return _tasklist_pid_exists(pid)
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


# 别名：force_stop 那侧沿用旧名，这里保持 module 内的统一叫法
pid_alive = process_alive


def choose_ports(spec: LaunchSpec, is_free=port_is_free, evict: bool = True,
                 evicted: Optional[List[str]] = None) -> Tuple[PortPlan, str]:
    """**只用官方默认端口，不平移。** 端口被占就结束占用者（用户 2026-10-06 决定）。

    为什么不平移（这是对原设计的推翻，理由成立）：
    Nacos 的 gRPC 口由 `server.port + 1000/1001` 派生，而SDK 与各类客户端配置里
    写死的是 8848；ActiveMQ 的 61616 更是被大量中间件硬编码。平移到 8849 之后，
    **服务起来了但外部客户端一个都连不上**，界面还显示"运行中·端口 8849"——
    这是比"起不来"更难归因的隐蔽故障。宁可把占了端口的东西杀掉，或者干脆报失败。

    端口角色仍然是三种（派生口 / 独立口 / 主口），只是"怎么落到具体数字"不同了：
    派生口按厂商规则由主口算，独立口用它自己的基准。

    evicted（可选出参）：把"结束了谁"写进这个列表，供 start() 转成给用户看的提示行。
    """
    base = spec.main_port
    if not base:
        return PortPlan(), "该组件没有登记主端口，无法启动"
    derived = tuple(base + int(o) for o in spec.port_offsets)
    extras = tuple(int(e) for e in spec.extra_ports)
    plan = PortPlan(main=base, derived=derived, extras=extras)

    busy = [p for p in plan.all_ports if not is_free(p)]
    if busy and not evict:
        return PortPlan(), _occupied_reason(busy, plan)
    if busy:
        for port in busy:
            label = "主端口" if port == base else "端口"
            why = evict_port_occupant(port, label, evicted)
            if why:
                return PortPlan(), why
        # 结束完等一下再验：进程被杀到真正释放 socket 有几十到几百毫秒的窗口。
        for _ in range(20):
            if all(is_free(p) for p in plan.all_ports):
                break
            time.sleep(0.25)
        still = [p for p in plan.all_ports if not is_free(p)]
        if still:
            return PortPlan(), _occupied_reason(still, plan)
    return plan, ""


def _occupied_reason(busy: List[int], plan: PortPlan) -> str:
    """端口被占的失败原因，必须指名道姓说清是哪个口、被谁占着。

    只说"端口被占用"等于把排查成本推给用户——他还得自己去翻任务管理器才知道该关什么。
    """
    details = []
    for port in busy:
        pid, name = occupant_of(port)
        who = f"{name}（PID {pid}）" if pid else "某个进程"
        role = "主端口" if port == plan.main else (
            "派生端口" if port in plan.derived else "独立端口")
        details.append(f"  · {port}（{role}）被 {who} 占用")
    return ("端口被占用，已停止启动（不会再自动换端口）：\n"
            + "\n".join(details)
            + "\n请先关掉上面这些进程再启动。若那个进程正是你要用的东西，"
              "停掉它之后本工具会重新拉起。")



def prepare_ports(comp: Component, spec: LaunchSpec, plan: PortPlan,
                  data_dir: Path) -> Tuple[bool, str, List[str]]:
    """端口准备。返回 (能否继续拉起, 失败原因, 要转成日志告知用户的提示行)。

    回写一定发生在拉起之前：改了配置却没起进程、或起进程时配置没生效，
    两边状态对不上时比"没启动"更难归因 —— 所以失败必须阻止 spawn。

    **2026-10-06：从写死ActiveMQ 改成按组件分派**。
    原来这里只认AMQ_CONSOLE_KEY / set_openwire_port，六个新组件全都用不了。
    分派点单独提成 `conf_writer_of` 是为了让护栏能逐个组件钉住 ——
    之前那条"ActiveMQ 写对了"的护栏对别的组件毫无约束力。"""
    if spec.port_writeback in ("cli_only", "cli_flag"):
        # cli_flag的端口靠命令行透传（Nacos：startup.cmd 的 %* 会把它交给 java），
        # 不碰文件。两种策略都在这里直接返回，不该留下任何文件。
        return True, "", []
    if spec.port_writeback != "conf_copy":
        return False, (f"{comp.display_name} 的端口策略 {spec.port_writeback!r} 不认识，"
                       f"已放弃启动（不会去猜该怎么改配置）。"), []

    version = resolve_launch_version(comp) or comp.versions[0].version
    # 配置目录名按组件定：多数是 conf，但 kafka/elasticsearch 是 **config**
    # （2026-10-06 实测包结构）。写死 conf 会让这两个的副本源目录不存在、
    # prepare_conf_copy 拿不到东西 —— 而"拿不到"在R1 里等于该拒改而不是静默通过。
    src = comp.install_dir(version) / conf_dir_name(comp.key)
    writer = conf_writer_of(comp.key)
    if writer is None:
        return False, (f"{comp.display_name} 没有登记端口回写方式，"
                       f"已放弃启动（不会去猜它的配置该怎么改）。"), []
    ok, why, notes = writer(src, data_dir, plan)
    if not ok:
        return False, why, notes
    return True, "", notes


# 组件的官方配置目录名。多数厂商包是 conf，实测 kafka 与 elasticsearch 是 config
# （2026-10-06 打开包核实）。写死 conf 会让这两个组件的副本源目录不存在。
_CONF_DIR_NAMES = {"kafka": "config", "elasticsearch": "config"}


def conf_dir_name(key: str) -> str:
    return _CONF_DIR_NAMES.get(key, "conf")


def conf_writer_of(key: str):
    """组件 key → 端口回写函数。返回 None 表示这个组件没登记。

    单独提成函数是为了让测试能逐个组件断言"该组件的坑被钉住了"，
    而不是只验ActiveMQ 一个（那六个新组件的坑就全放过了）。
    """
    return _CONF_WRITERS.get(key)


def _write_activemq_ports(src: Path, data_dir: Path,
                           plan: PortPlan) -> Tuple[bool, str, List[str]]:
    """ActiveMQ：整份 conf 拷成副本，再改副本里那两个端口。"""
    conf, console_file, broker_file = conf_targets(data_dir)
    notes: List[str] = []
    state, diff = prepare_conf_copy(src, conf)
    if state == "created":
        notes.append(f"已在 {conf} 建立 ActiveMQ 配置副本，"
                     f"此后端口改动只写这份副本（官方文件不受影响）。")
    elif diff:
        notes.append(f"官方 conf 里有 {len(diff)} 个文件是副本没有的（多半是版本升级带来的）："
                     f"{', '.join(diff[:5])}。本工具不自动合并，需要时删掉副本目录让它重建。")
    ok, why = set_property_line(console_file, AMQ_CONSOLE_KEY, str(plan.main))
    if not ok:
        return False, why, notes
    for port in plan.extras:
        ok, why = set_openwire_port(broker_file, port)
        if not ok:
            return False, why, notes
    return True, "", notes


def sync_runtime_assets(src_dir: Path, dst_dir: Path) -> List[str]:
    """把安装目录里的**静态内容**补进数据目录（只补缺的，绝不覆盖已有的）。

    为什么需要它（2026-10-08 真机实测定位的两个缺陷）：
      - nginx 的 `nginx.conf` 里是 `root html;`，而 root 是**相对 -p prefix** 解析的，
        我们给的 prefix 是 data_dir → 它去找 `~/.env-tools/nginx-data/html/`，
        而那个目录从来不存在 → 首页 404（用户点了控制台却打不开）。
        credentials_hint 里早就写着"站点内容在 nginx-data/html/"，只是没人真的去建它。
      - tomcat 的 CATALINA_BASE 指向 data 目录 → 它的 `apphost` 是
        `data_dir/webapps`，而那份是空的（webapps 目录建了、里面什么都没拷）
        → ROOT 上下文不存在 → 首页 404。

    只补缺、不覆盖：用户改过的 index.html / 自己部署的 WAR 不会被我们冲掉。
    返回补进来的条目名（给日志用）。
    """
    added: List[str] = []
    if not src_dir.is_dir():
        return added
    ensure_dir(dst_dir)
    for item in sorted(src_dir.iterdir()):
        target = dst_dir / item.name
        if target.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
        added.append(item.name)
    return added


def _write_tomcat_ports(src: Path, data_dir: Path,
                        plan: PortPlan) -> Tuple[bool, str, List[str]]:
    """Tomcat：server.xml 副本 + 两个端口一起改（8080 与 shutdown 的 8005）。

    另外把安装目录的 webapps/ 同步进 CATALINA_BASE（见 sync_runtime_assets）——
    不同步的话 CATALINA_BASE 下的 webapps 是空目录，ROOT 上下文不存在，
    点控制台拿到 404（2026-10-08 真机实测）。"""
    conf = data_dir / "conf"
    notes: List[str] = []
    state, diff = prepare_conf_copy(src, conf)
    if state == "created":
        notes.append(f"已在 {conf} 建立 Tomcat 配置副本，端口改动只写这份副本。")
    elif diff:
        notes.append(f"官方 conf 里有 {len(diff)} 个文件是副本没有的："
                     f"{', '.join(diff[:5])}。需要时删掉副本目录让它重建。")
    server_xml = conf / "server.xml"
    # 8005 是 shutdown 端口，登记在 extra_ports 的第一位（若没登记就用 main+1）
    shutdown_port = plan.extras[0] if plan.extras else plan.main + 1000
    ok, why = set_tomcat_ports(server_xml, plan.main, shutdown_port)
    if not ok:
        return False, why, notes
    notes.append(f"端口已写入副本：HTTP {plan.main}、shutdown {shutdown_port}"
                 f"（两个必须一起改，否则 shutdown 会打到别的实例上）。")
    # webapps 源目录在安装目录根的 webapps/（厂商包布局），不是 conf 那层
    home = src.parent
    added = sync_runtime_assets(home / "webapps", data_dir / "webapps")
    if added:
        notes.append(f"已把安装目录的 webapps/ 同步进 {data_dir / 'webapps'}"
                     f"（补 {len(added)} 项：{', '.join(added[:5])}）；"
                     f"CATALINA_BASE 指向这里，不同步首页会 404。")
    return True, "", notes


def _write_nginx_ports(src: Path, data_dir: Path,
                       plan: PortPlan) -> Tuple[bool, str, List[str]]:
    """nginx：整份 conf 拷贝 + 改 listen 那一行（注释行里的 listen 不能碰）。

    另外把安装目录的 html/ 同步进 prefix（= data_dir）——
    `root html;` 是相对 prefix 解析的，而 prefix 是我们给的 data_dir，
    不同步的话首页 404（2026-10-08 真机实测）。"""
    conf = data_dir / "conf"
    notes: List[str] = []
    state, diff = prepare_conf_copy(src, conf)
    if state == "created":
        notes.append(f"已在 {conf} 建立 nginx 配置副本，端口改动只写这份副本。")
    elif diff:
        notes.append(f"官方 conf 里有 {len(diff)} 个文件是副本没有的："
                     f"{', '.join(diff[:5])}。需要时删掉副本目录让它重建。")
    ok, why = set_nginx_listen(conf / "nginx.conf", plan.main)
    if not ok:
        return False, why, notes
    added = sync_runtime_assets(src.parent / "html", data_dir / "html")
    if added:
        notes.append(f"已把安装目录的 html/ 同步进 {data_dir / 'html'}"
                     f"（补 {len(added)} 项），否则 root html 解析不到、首页 404。")
    return True, "", notes


def _write_kafka_props(src: Path, data_dir: Path,
                       plan: PortPlan) -> Tuple[bool, str, List[str]]:
    """Kafka：把 server.properties 拷成副本，只改 log.dirs（端口全走命令行默认值）。

    **为什么必须改 log.dirs**（实测）：官方默认 `/tmp/kraft-combined-logs`，
    Windows 解析成 `C:\\tmp\\` —— 不在安装目录也不在我们的数据目录。后果两条：
      - 卸载删不掉，多版本并存会抢同一个目录；
      - `risk_note`/`data_note` 里"数据在 ~/.env-tools/kafka-data 下"就是**空话**。

    **为什么端口不改**：实测 `--override` 改端口会半死（只改 listeners 不改
    advertised.listeners → 19092不开、19093 开了，然后 channel manager 超时）。
    我们不动端口，端口冲突按既定规则"结束占用者"。
    """
    conf = data_dir / "conf"
    notes: List[str] = []
    state, diff = prepare_conf_copy(src, conf)
    if state == "created":
        notes.append(f"已在 {conf} 建立 Kafka 配置副本，此后数据目录改动只写这份副本。")
    elif diff:
        notes.append(f"官方 conf 里有 {len(diff)} 个文件是副本没有的："
                     f"{', '.join(diff[:5])}。需要时删掉副本目录让它重建。")
    log_dirs = (data_dir / "kraft-logs").as_posix()      # 正斜杠：反斜杠在 properties 里是转义符
    ok, why = set_kafka_log_dirs(conf / "server.properties", log_dirs)
    if not ok:
        return False, why, notes
    notes.append(f"数据目录（log.dirs）已指向 {log_dirs}（原默认在 C:\\tmp\\ 下）。")
    return True, "", notes


def _write_elasticsearch_props(src: Path, data_dir: Path,
                               plan: PortPlan) -> Tuple[bool, str, List[str]]:
    """Elasticsearch：什么都不改（全部靠 -E 命令行覆盖），但要把副本建出来。

    实测 ES 9 的 yml 里**没有任何有效配置项**（82 行全注释），端口/路径/安全开关
    都能用 `-E` 覆盖 —— 所以这里只建副本、不写任何值，
    免得用户想手工微调时还要自己去官方文件里改（那份会被卸载删掉）。
    """
    conf = data_dir / "conf"
    notes: List[str] = []
    state, diff = prepare_conf_copy(src, conf)
    if state == "created":
        notes.append(f"已在 {conf} 建立 ES 配置副本（供你手工微调；"
                     f"端口与数据目录由启动命令的 -E 参数决定，不改这个文件）。")
    return True, "", notes


def _write_none(src: Path, data_dir: Path,
                plan: PortPlan) -> Tuple[bool, str, List[str]]:
    """CLI 覆盖型组件：配置由命令行参数决定，不建副本。"""
    return True, "", []


_CONF_WRITERS = {
    "activemq": _write_activemq_ports,
    "tomcat": _write_tomcat_ports,
    "nginx": _write_nginx_ports,
    "kafka": _write_kafka_props,
    "elasticsearch": _write_elasticsearch_props,
}


# 厂商日志的候选位置（spec 计划二 §7 实测清单）。写成表而不是猜：
# 找不到文件是常态（首次启动、Windows 下 Nacos 就没有 start.out），
# 那种情况要明说"还没生成"，让用户知道去哪儿看，而不是给一句空报错。
VENDOR_LOG_CANDIDATES = {
    "activemq": ("data/activemq.log", "data/activemq.dump"),
    "nacos": ("logs/start.out",),
}


def vendor_log_tails(data_dir: Path, home: Path, key: str, lines: int = 8) -> str:
    """把该组件厂商日志的尾巴拼成一句可读文本。没有文件就回"（厂商日志尚未生成）"。"""
    chunks = []
    for rel in VENDOR_LOG_CANDIDATES.get(key, ()):
        for base in (data_dir, home):
            p = base / rel
            if p.exists():
                chunks.append(f"{rel}: {ServiceManager._tail(p, lines)}")
                break
    return " / ".join(chunks) or "（厂商日志尚未生成）"


def _http_status_with(fetch, url: str) -> bool:
    """把"发请求"抽成注入点，测试才能完全不碰网络。2xx/3xx/401 都算服务活着：
    Jenkins 的 /login 在未初始化时会给 200，而根路径可能 403，401 说明服务在、只是要认证。"""
    try:
        return fetch(url) in (200, 201, 202, 204, 301, 302, 303, 307, 401)
    except Exception:
        return False


def _http_fetch_status(url: str, timeout: float = 2.0) -> int:
    req = urllib.request.Request(url, headers=dict(HTTP_UA))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        return exc.code


def http_ok(url: str, timeout: float = 2.0) -> bool:
    return _http_status_with(lambda u: _http_fetch_status(u, timeout), url)


def http_responds(url: str, timeout: float = 2.0) -> bool:
    """只要 HTTP 有响应就算活着（**404 / 403 / 5xx 都算**）。

    与 `http_ok` 的区别：`http_ok` 只认 2xx/3xx/401（"这个页面能用"），
    而这个只认"服务端在应答"。

    2026-10-06 真机实测逼出来的差别：Tomcat 10.1.60 启动后
    `http://127.0.0.1:8080/` 返回 **404**（没挂任何 web 应用，ROOT 也没解包）
    —— 但 tomcat **完全正常地在服务**。用 `http_ok` 判会稳定误报"启动失败"，
    而用户看到的是一个工作正常的 Tomcat。

    这类"有端口但不提供 Web 控制台"的组件（tomcat / nginx / elasticsearch）
    就该用这个判据；有控制台的（nacos / jenkins / activemq）仍用 `http_ok`
    —— 那里"页面能用"才是真的能用。
    """
    try:
        _http_fetch_status(url, timeout)
        return True
    except urllib.error.HTTPError:
        return True               # 有 HTTP 响应 = 服务端在应答
    except Exception:
        return False


def process_is_alive(pid: int) -> bool:
    """PID 是否还在。**注意这是提示不是真相**：spec §4 定的是端口在听才算运行中。"""
    if not pid or pid <= 0:
        return False
    if CURRENT_OS == "Windows":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        still_alive = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return True          # 打不开句柄：权限不足，不能断定它死了
        try:
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == still_alive
            return True
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class LaunchStatus:
    """组件当前运行状态。state 取值：
    not_installed_or_stopped / running / zombie（登记在但端口不在听了）

    注意别和 StartResult.state 混：后者的枚举是
    gate / port / writeback / **prestart** / running / timeout / spawn，
    其中 prestart（前置准备失败，如 kafka 的 KRaft format 没过）是 2026-10-06 加的。"""
    state: str
    record: Optional[RunRecord] = None
    reason: str = ""


@dataclass
class LaunchPlan:
    """一次拉起所需的全部信息，纯数据 —— 决策都在这里做完，ServiceManager 只负责执行。"""
    argv: List[str]
    env: Dict[str, str]
    cwd: Path
    log_file: Path
    console_url: str
    # 实际用的端口。2026-10-06 加：pre_start（如 kafka 的 format）要与命令
    # 共享同一份 mapping，端口从 argv 里反解不可靠（有的命令根本不传端口），
    # 所以由 build_launch_plan 显式记下来。
    port: int = 0
    # 实际使用的 JAVA_HOME。2026-10-06 加：pre_start 与命令必须用**同一个** java，
    # 各解析一次可能拿到不同结果（JAVA_HOME 环境变量可能在两秒内被改）。
    java_home: str = ""


@dataclass
class StartResult:
    ok: bool
    state: str            # "running" / "gate" / "port" / "writeback" / "timeout" / "spawn"
    reason: str = ""
    record: Optional[RunRecord] = None
    console_url: str = ""
    # 端口准备阶段要转告用户的提示行（如"已在 data 建立配置副本"）。
    # 之所以不塞进 reason：reason 是失败原因，成功时也要让用户知道端口写去了哪份文件；
    # 带默认值是为了让计划一既有构造处零改动。
    notes: List[str] = field(default_factory=list)


def resolve_java_home(comps: Dict[str, Component]) -> Optional[str]:
    """按三级找 JDK：**本工具装的生效版本 → 本工具装的已安装最高版本 → JAVA_HOME**。

    EnvManager.get 就是 os.environ.get，拿它当"用户装的 JDK"会读到
    被本工具改脏的进程环境，与 R3 里"回滚要读持久层的真值"是同一个坑。

    **第二级是 2026-10-06 补的**（用户报 rocketmq 起不来查出来的）：
    原来只有「active 登记」与「JAVA_HOME 环境变量」两级，而
    **exe 启动的进程既没有 JAVA_HOME，用户也未必点过"切换生效版本"**
    （刚下载安装完JDK 就去点其它组件的启动是最常见的路径）→
    两级都落空→ 门控报"启动需要先有 JDK"，而磁盘上明明有。
    这与 `resolve_launch_version` 的「已安装最高版本」兜底是同一个道理。
    """
    jdk = comps.get("jdk")
    if jdk is not None:
        active = load_active_map().get("jdk")
        if active:
            home = jdk.install_dir(active)
            if jdk.exec_path_in_home(str(home)) is not None:
                return str(home)
        # 第二级：本工具装过、但没登记生效版本 → 取已安装里版本号最高的。
        # 不走"候选清单首位"—— 那可能压根没装（resolve_launch_version 的注释详述）。
        for d in sorted(jdk.installed_dirs(),
                        key=lambda p: _version_key(p.name),
                        reverse=True):
            if jdk.exec_path_in_home(str(d)) is not None:
                return str(d)
    env_home = os.environ.get("JAVA_HOME")
    if env_home and (Path(env_home) / "bin").is_dir():
        return env_home
    return None


def _version_key(dir_name: str) -> Tuple[int, ...]:
    """`jdk-21.0.5` → (21, 0, 5)。用于挑"已安装的最高版本"。

    按数值分段比而不是字符串比：`2.10.0 > 2.9.0`，字符串比会反过来。
    """
    tail = dir_name.split("-", 1)[1] if "-" in dir_name else dir_name
    out: List[int] = []
    for chunk in tail.split("."):
        out.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(out)


def resolve_launch_version(comp: Component) -> Optional[str]:
    """启动该用哪个已安装版本。**只认磁盘上真装着的**，不看候选列表首位。

    离线默认清单（build_components 的 versions）会落后于实际安装的版本：
    在线抓取失败时尤其明显——清单首位是 2.568.3，用户装的是 2.580.1，
    于是点启动会去找一个根本没装的目录，spawn 报 [WinError 267] 目录名称无效，
    而界面上只显示"拉起失败"，用户完全无从下手（真机演练 2026-10-05 实测）。

    优先级：生效版本（active 登记，用户明确选过的）→ 已安装目录里版本号最高的。
    返回 None 表示磁盘上一个都没装。"""
    active = load_active_map().get(comp.key)
    if active and comp.install_dir(active).is_dir():
        return active
    installed = [p.name for p in comp.installed_dirs()]
    if not installed:
        return None
    # 目录名形如<key>-<version>；取版本号那半段按数值排，"2.9.0" < "2.10.0" 才成立。
    def _ver(name: str) -> Tuple[int, ...]:
        tail = name.split("-", 1)[1] if "-" in name else name
        parts = []
        for chunk in tail.split("."):
            parts.append(int(chunk) if chunk.isdigit() else 0)
        return tuple(parts)
    # **返回版本号，不是目录名**（2026-10-06 修的真缺陷）。
    # 上面 active 分支返回 `active`（裸版本号），这里原来返回 `p.name`（完整目录名），
    # 两个分支语义不一致 —— 而所有调用方都按裸版本号用
    # `comp.install_dir(version)`，于是 fallback 分支会二次拼前缀：
    #     install_dir("rocketmq-5.3.1") → ~/.env-tools/rocketmq/rocketmq-rocketmq-5.3.1
    # 启动时直接 `[WinError 267] 目录名称无效`。
    # 触发条件：**没登记生效版本**（active 表为空）——
    # 也就是"刚下载安装完、还没点过切换生效版本"的组件，一键启动必然失败。
    return max(installed, key=_ver).split("-", 1)[-1]


def launch_gate(comp: Component, spec: LaunchSpec,
                java_home: Optional[str]) -> Tuple[bool, str]:
    """启动前门控。失败原因必须可行动（spec §5）：说清缺什么、点这里能补什么。

    2026-10-08 起，缺前置运行时不再由这里"劝用户去装"：界面在拉起 launch_worker
    之前会先调 prereq_components() 把它们自动装好（见 ensure/prereq_* 那一段）。
    这段文案保留为**兜底**（自动安装被打断、或用户直接调 ServiceManager 时）。"""
    if getattr(comp, "launch", None) is None:
        return False, "本工具暂不支持启动该组件"
    if java_home is None and "jdk" in (spec.needs or ()):
        return False, "启动需要先有 JDK：本工具会在点「启动」时自动装一个，请重试或手动装一个 JDK。"
    if not comp.versions:
        return False, "该组件还没有可启动的版本"
    # 前置依赖（2026-10-06 新增，目前只有 rabbitmq → Erlang）。
    # 必须在门控就拦：rabbitmq-server.bat 开头 `if not exist erl.exe exit /B 1`，
    # 缺依赖时它会**一闪就退**，用户只看到"启动了但没反应"。
    # 与"起不来"不同，这类必须在按启动之前就说清要装什么。
    if spec.prereq is not None:
        ok_prereq, why_prereq = check_prereq(spec.prereq)
        if not ok_prereq:
            return False, why_prereq
    if resolve_launch_version(comp) is None:
        # 这条以前不存在，于是"候选清单里有、磁盘上没装"会一路走到 spawn 才炸。
        # 现在在门控就说清是"没装"，并直接给出可点的下一步。
        shown = "、".join(v.version for v in comp.versions[:3])
        return False, (f"磁盘上还没有 {comp.display_name} 的任何已安装版本，"
                       f"没法启动（可选版本：{shown}）。"
                       f"请先在本工具里点「安装」装一个版本，再回来点启动。")
    return True, ""


def installed_erlang_erl() -> str:
    """找一个可用的 erl.exe：**先看本工具自己装的**，再看宿主上的约定落点。

    为什么顺序是本工具优先（2026-10-08）：Erlang 现在是本工具的隐藏组件，
    装在 ~/.env-tools/erlang/erlang-<v>/bin/erl.exe —— 那个位置不在原来的搜索
    glob（C:\\erlang* / Program Files）里，于是"我们刚替用户装好的 Erlang"
    会被门控判成"没装"，rabbitmq 永远启动不了（自动安装白做）。
    """
    for path in erlang_installed_dirs():
        for cand in (path / "bin" / "erl.exe",):
            if cand.is_file():
                return str(cand)
    return find_erlang_home_erl()


def erlang_installed_dirs() -> List[Path]:
    """本工具装的 Erlang 版本目录，按版本号**降序**（最新的先用）。"""
    root = CONFIG_DIR / "erlang"
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir()
            if p.is_dir() and p.name.startswith("erlang-") and not p.name.startswith(".")]
    return sorted(dirs, key=lambda p: _version_key(p.name), reverse=True)


def check_prereq(prereq: PrereqSpec) -> Tuple[bool, str]:
    """前置依赖是否就位。

    判据是"宿主上能不能找到那个可执行文件"（`shutil.which`）——
    官方脚本自己也是这么查的（rabbitmq 的 `rabbitmq-env.bat` 会用 PowerShell
    探测 PATH 里的 erl.exe），所以我们与它的判断口径一致。

    实测背景：Erlang **国内镜像站没有**（阿里云 /erlang/ 是源码镜像、清华 404），
    只能走 GitHub 的 139MB 安装包 —— 慢是已知的honest，不能假装它不存在。
    """
    probe = prereq.probe or ""
    if not probe:
        return True, ""
    found = shutil.which(probe) or installed_erlang_erl()
    if found:
        return True, ""
    # 文案坑（2026-10-06 护栏抓出来的）：我第一版写的是
    #     where = f"已装（{probe}）"     ← 走到这里必然是"没找到"
    # 于是渲染成「找不到 erl.exe。…当前状态：已装（erl.exe）」——
    # **同一句话里既说找不到又说已装**。三目也写反了，且 `if probe else ""` 是死条件
    # （上面已 return 掉空 probe）。
    # 另外 hint 末尾没跟分隔符，渲染成「去装 Erlang当前状态：…」。
    return False, (f"{prereq.key} 还没就位：找不到 {probe}（当前状态：未找到）。\n\n"
                   f"{prereq.install_hint}")


# 免安装版 Erlang 的常见落点（2026-10-06 实测装到了 C:\erlang27）。
# 官方 zip 版解压后就是这形态，**不需要设任何环境变量** ——
# rabbitmq 的 rabbitmq-env.bat:25-33 会自己 Get-Command erl.exe 去 PATH 里找，
# 所以我们只要在拉子进程时把它加进 PATH 就行，不污染用户的系统设置。
_ERLANG_GLOBS = (r"C:\erlang*", r"C:\Program Files\Erlang OTP\*")


def find_erlang_home_erl() -> str:
    """在免安装 Erlang 的常见落点里找 erl.exe。找不到返回空串。

    不搜全盘（慢且会撞权限），只搜这两个约定位置 ——
    找���到就让门控说「没装」，用户装到别处时可用 install_hint 指路。
    """
    import glob
    for pattern in _ERLANG_GLOBS:
        for base in sorted(glob.glob(pattern), reverse=True):
            for rel in ("bin/erl.exe", "bin" + os.sep + "erl.exe",
                        "erts-*/bin/erl.exe"):
                for cand in glob.glob(os.path.join(base, rel)):
                    if os.path.isfile(cand):
                        return cand
    return ""


def check_prereq_for(comp: Component, spec: LaunchSpec) -> Tuple[bool, str]:
    """按组件查前置依赖，没有就返回 (True, "")。给 UI 层复用。"""
    if spec.prereq is None:
        return True, ""
    return check_prereq(spec.prereq)


# ---------------------------------------------------------------------------
# 「开机就能用」：启动前置依赖的**自动就位**
#
# 用户的要求是"缺失的前置依赖（JDK / Erlang）由软件自己装好配好"，
# 而原来的实现只会在门控里说一句"请先装一个 JDK"就停下 —— 那是把活儿交回给用户。
# 下面这组函数把"缺什么"变成"我们去装什么"：
#   prereq_components()     → 列出还缺的组件 key（界面据此先装后启）
#   java_major_of()         → 顺便补上 min_java_major 的版本门控（原来那个字段没人读）
#   prereq_install_versions → rabbitmq 4.x/3.x 各自配套的 Erlang major
# ---------------------------------------------------------------------------
_JAVA_MAJOR_TIMEOUT = 20


def java_major_of(home: Optional[str]) -> Optional[int]:
    """读某个 JDK 目录的 major 版本；读不到返回 None。

    两个格式都要认（2026-10-08 实测两边都存在）：
      - `java version "1.8.0_392"` → 8（JDK 8 及以前用 1.x 记法）
      - `java version "21.0.5"`    → 21
    不认的话 JDK 8 会被读成 1：结论恰好也是"太旧"，但那个错数字会一路进日志和文案。
    """
    if not home:
        return None
    exe = Path(home) / "bin" / ("java.exe" if CURRENT_OS == "Windows" else "java")
    if not exe.is_file():
        return None
    kwargs: Dict[str, object] = {"stdin": STDIN_DEVNULL}
    if CURRENT_OS == "Windows":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = subprocess.run([str(exe), "-version"], capture_output=True, text=True,
                              timeout=_JAVA_MAJOR_TIMEOUT, check=False, **kwargs)
    except Exception:
        return None
    text = (proc.stdout or "") + (proc.stderr or "")   # java -version 只写 stderr
    m = _re.search(r'version\s+"1\.(\d+)', text)
    if m:
        return int(m.group(1))
    m = _re.search(r'version\s+"(\d+)', text)
    return int(m.group(1)) if m else None


def jdk_home_version(comps: Dict[str, "Component"]) -> Tuple[Optional[str], Optional[int]]:
    """返回 (JAVA_HOME, major)。找不到 JDK 时 (None, None)。"""
    home = resolve_java_home(comps)
    return home, java_major_of(home)


def prereq_components(comp: "Component", comps: Dict[str, "Component"]) -> List[str]:
    """该组件的启动还缺哪些**可自动安装的**组件 key。

    判据与 launch_gate 同一套（resolve_java_home / check_prereq），只是把"缺"
    翻译成"要装谁"：
      - 需要 JDK 而宿主上一个都找不到 → "jdk"
      - 有 JDK 但低于 spec.min_java_major → 也返回 "jdk"（装一个新的来顶）
      - prereq 声明的运行时（Erlang）找不到 → prereq.key
    """
    spec = getattr(comp, "launch", None)
    if spec is None:
        return []
    missing: List[str] = []
    if "jdk" in (spec.needs or ()):
        _home, major = jdk_home_version(comps)
        need = spec.min_java_major
        if major is None or (need is not None and major < need):
            missing.append("jdk")
    if spec.prereq is not None:
        ok, _why = check_prereq(spec.prereq)
        if not ok:
            missing.append(spec.prereq.key)
    return [k for k in missing if k in comps]


def prereq_install_versions(comp: "Component") -> List[str]:
    """该组件**实际会用到**的前置运行时版本前缀，用于匹配"装哪个版本才配套"。

    RabbitMQ 与 Erlang 的版本是绑死的（4.x 要 Erlang 26.2~27.x，3.13 只能配 26.x），
    两个 rabbitmq 版本不能共用一个 Erlang —— 见 PrereqSpec 的说明。
    返回空列表表示"不挑，装清单里最新那个即可"。
    """
    versions = [cv.version for cv in getattr(comp, "versions", [])]
    table: Dict[str, List[Tuple[str, List[str]]]] = {
        "rabbitmq": [("4.", ["27."]), ("3.", ["26."])],
    }
    out: List[str] = []
    for cv_version in versions:
        for prefix, erl_prefixes in table.get(getattr(comp, "key", ""), []):
            if cv_version.startswith(prefix):
                out.extend(erl_prefixes)
                break
    return out


def pick_prereq_version(prereq_comp: "Component", wanted_prefixes: List[str]) -> Optional[str]:
    """在前置组件清单里挑版本：优先匹配 wanted_prefixes，否则取第一个**能下载的**。

    只在"当前平台有下载地址"的版本里挑：离线清单里可能带着别的平台的版本
    （Erlang 的 Windows 便携包在 Linux/macOS 上是空列表），
    挑中一个下不了的版本，用户看到的就是"点启动 → 立刻失败"。
    """
    downloadable = [cv for cv in prereq_comp.versions if cv.urls_for_current()]
    for cv in downloadable:
        if any(cv.version.startswith(p) for p in wanted_prefixes):
            return cv.version
    return downloadable[0].version if downloadable else None


def prereq_already_installed(prereq_comp: "Component", version: str) -> bool:
    """该前置组件的这个版本是否已经落位成一个能用的目录。"""
    home = prereq_comp.install_dir(version)
    if not home.is_dir():
        return False
    if prereq_comp.exec_name is None:
        return True
    return prereq_comp.exec_path_in_home(str(home)) is not None


def run_pre_start(comp: Component, spec: LaunchSpec, plan: LaunchPlan,
                  timeout: int = 300) -> Tuple[bool, str, List[str]]:
    """跑 LaunchSpec.pre_start 里的前置命令（如 kafka 的 KRaft format）。

    返回 (是否成功, 失败原因, 提示行)。

    为什么必须在这里、且必须在 spawn 之前：
      - kafka 不 format 直接起不来（实测 `No readable meta.properties files found.`）；
      - 配了 `--ignore-formatted` 所以**重复 format 是幂等的**（实测 rc=0），
        不必担心"点两次启动会不会搞坏"；
      - cluster.id 存在 data_dir 里、复用同一个 uuid
        （换 uuid 会被拒：`Invalid cluster.id`）。

    失败时**不 spawn**：宁可明确告诉用户"format 失败"，也不要拉起一个必然起不来的进程。
    """
    notes: List[str] = []
    if not spec.pre_start:
        return True, "", notes
    mapping = _plan_mapping(comp, spec, plan)
    argv = [t.format(**mapping) for t in spec.pre_start]
    try:
        proc = subprocess.run(argv, cwd=plan.cwd, env=plan.env,
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"前置准备超过 {timeout} 秒没结束，已放弃启动。", notes
    except OSError as exc:
        return False, f"跑前置准备失败：{exc}", notes
    if proc.returncode != 0:
        tail = ((proc.stdout or b"").decode("utf-8", "replace")
                + (proc.stderr or b"").decode("utf-8", "replace")).strip()
        return False, (f"前置准备失败（退出码 {proc.returncode}），已放弃启动。"
                       f"命令：{' '.join(argv[:3])} …"
                       f"输出末尾：{tail[-400:]}"), notes
    notes.append("已完成存储/存储目录初始化（前置准备）。")
    return True, "", notes


def _plan_mapping(comp: Component, spec: LaunchSpec, plan: LaunchPlan) -> dict:
    """重建 build_launch_plan 用的 mapping，让 pre_start 与命令共享同一份替换表。

    单独抽出来是因为两处必须给出一致的值 —— 尤其 {cluster_id}：
    format 用了uuid A 而 kafka.Kafka 用 uuid B 的话，broker 认自己的 meta.properties，
    format 白做（实测会 `Invalid cluster.id`）。
    """
    version = resolve_launch_version(comp) or comp.versions[0].version
    home = comp.install_dir(version)
    data_dir = CONFIG_DIR / f"{comp.key}-data"
    # java_home 必须复用 plan 上的（2026-10-06 护栏抓出来的）：start() 已经算好并
    # 传给 build_launch_plan 了，我若再解析一次，① {java} 可能与实际 spawn 的
    # java 不是同一个；② 每个组件每点一次启动就多构建一次全量组件表。
    java_home = plan.java_home or resolve_java_home({c.key: c for c in build_components()}) or ""
    return {
        "java": str(Path(java_home) / "bin" / ("java.exe" if CURRENT_OS == "Windows" else "java")),
        "war": str(home / "jenkins.war"),
        "home": str(home),
        "data_dir": str(data_dir),
        "conf_dir": str(data_dir / "conf"),
        "conf": str(config_file_for(comp, data_dir)),
        "port": str(plan.port),
        "log_file": str(plan.log_file),
        "cluster_id": read_or_create_cluster_id(data_dir),
    }


def build_launch_plan(comp: Component, spec: LaunchSpec, java_home: str,
                      port: int, log_file: Path) -> LaunchPlan:
    """按 OS 展开模板，注入 env，定好 data_dir 与重定向文件。

    重定向不是可选项：Windows 用 DETACHED_PROCESS 拉起后没有有效控制台句柄，
    不重定向就等于把启动报错扔掉，事后只能猜（设计 §4）。"""
    version = resolve_launch_version(comp) or comp.versions[0].version
    home = comp.install_dir(version)
    war = home / "jenkins.war"
    # 数据与版本目录分离（spec §0 决策 3）：JENKINS_HOME 指向 CONFIG_DIR/<key>-data，
    # 这样换版本、重装、卸载都不碰任务与插件。
    data_dir = CONFIG_DIR / f"{comp.key}-data"
    env = dict(os.environ)
    env["JAVA_HOME"] = str(Path(java_home))
    if spec.data_dir_env:
        env[spec.data_dir_env] = str(data_dir)
    ensure_dir(data_dir)
    mapping = {
        "java": str(Path(java_home) / "bin" / ("java.exe" if CURRENT_OS == "Windows" else "java")),
        "war": str(war),
        "home": str(home),
        "data_dir": str(data_dir),
        "conf_dir": str(data_dir / "conf"),
        "conf": str(config_file_for(comp, data_dir)),
        "port": str(port),
        "log_file": str(log_file),
        # kafka 的 KRaft format 需要一个**持久化**的 cluster.id：换 uuid 会被拒
        # （Invalid cluster.id）。所以它进 mapping 而不是每次现生成。
        "cluster_id": read_or_create_cluster_id(data_dir),
    }
    # 计划二的额外 env（ActiveMQ 的 ACTIVEMQ_CONF/DATA 走这条路；
    # 它两个值都要等端口定了、副本建好了才写得出最终值，所以在计划阶段拼）。
    for name, template in (spec.extra_env or {}).items():
        env[name] = template.format(**mapping)
    # 前置依赖的可执行文件要能被子进程找到（2026-10-06 真机实测）。
    # Erlang 的免安装版**不设任何环境变量**（实测装到 C:\erlang27 即可用），
    # 而 rabbitmq 的 rabbitmq-env.bat 会自己 Get-Command erl.exe 去 PATH 里找
    # ——所以只要把它加进**这个子进程的** PATH 就行，
    # **不动用户的系统/用户环境变量**（那是别人机器上的既定配置，不该由我们改）。
    if spec.prereq is not None:
        erl = installed_erlang_erl()
        if erl:
            erl_bin = str(Path(erl).parent)
            env["PATH"] = erl_bin + os.pathsep + env.get("PATH", "")
            env["ERLANG_HOME"] = str(Path(erl_bin).parent)
    argv = [t.format(**mapping) for t in spec.commands[CURRENT_OS]]
    return LaunchPlan(argv=argv, env=env, cwd=home, log_file=log_file,
                      console_url=f"http://127.0.0.1:{port}{spec.console_path or ''}",
                      port=port, java_home=java_home)


def config_file_for(comp: Component, data_dir: Path) -> Path:
    """该组件启动命令要读的那份配置文件。

    **必须指向副本**，不能指官方文件：
      - kafka 的 `pre_start`（StorageTool format）与 `kafka.Kafka` 要读同一个文件，
        而我们把 log.dirs 写进副本里；读官方文件的话 format 格式化的是 `/tmp` 那个目录，
        broker 却去副本里找 meta.properties → `No readable meta.properties files found.`。
      - 官方文件卸载就会被删，下次启动读不到。
    """
    # 每个组件的配置文件名不同（2026-10-06：nginx 又踩了一次 ——
    # 之前这个函数只认 kafka/es，其它组件一律返回 elasticsearch.yml）。
    names = {"kafka": "server.properties", "elasticsearch": "elasticsearch.yml",
             "nginx": "nginx.conf", "tomcat": "server.xml",
             "activemq": "jetty-spring.properties"}
    return data_dir / "conf" / names.get(comp.key, "application.yml")


@dataclass
class StopResult:
    ok: bool
    need_force: bool = False
    reason: str = ""


class ServiceManager:
    """本机进程生命周期的唯一入口。探针全部可注入，测试因此不碰网络也不碰进程。"""

    def __init__(self, is_listening=port_is_listening, http_ok=http_ok,
                 process_alive=process_is_alive, terminate=None, lookup_pids=None,
                 process_images=None):
        self._is_listening = is_listening
        self._http_ok = http_ok
        self._process_alive = process_alive
        self._terminate = terminate or self._terminate_by_pid
        # 端口反查的注入点。用 lambda 包一层而不是把函数当默认值绑死：
        # 默认参数在 def 时求值，测试 patch main.netstat_listener_pids 就会失效
        # （这个坑计划一的 start() 已经踩过并写进注释）。
        self._lookup_pids = lookup_pids or (lambda ports: netstat_listener_pids(ports))
        # 同上：残留辅助进程的查询也是子进程调用，只给停止路径收尾用（见 LaunchSpec.leftover_processes）。
        self._process_images = process_images or (
            lambda names: running_process_images(names))

    @staticmethod
    def _terminate_by_pid(rec: RunRecord) -> None:
        """只结束我们自己登记过的 PID。

        spec §2 说明 Nacos / ActiveMQ 的 PID 不可信，所以计划二必须走正规
        shutdown 脚本；本期 Jenkins 我们就是服务进程，terminate 才成立。
        非 server 角色一律不动手 —— 这条守卫是"绝不误杀别人进程"的最后防线。"""
        if rec.pid_role != "server" or rec.pid is None or rec.pid <= 0:
            return
        try:
            os.kill(rec.pid, 15)
        except OSError:
            pass

    def status(self, key: str, comp: Component,
               records: Optional[Dict[str, RunRecord]] = None) -> LaunchStatus:
        if getattr(comp, "launch", None) is None:
            return LaunchStatus("not_installed_or_stopped")
        rec = (records if records is not None else load_running_map()).get(key)
        if rec is None:
            return LaunchStatus("not_installed_or_stopped")
        # 按整簇判，不按单口：Nacos 主口在听、gRPC 9848 掉了是"半死"，
        # 显示成运行中会让用户以为客户端连得上（spec 计划二 §7）。
        # 老记录没有 ports 字段（加载侧才做归一），进程内现构造的也得能判，故按 port 兜底。
        silent = [p for p in (tuple(rec.ports) or (rec.port,))
                  if not self._is_listening(p)]
        if silent:
            return LaunchStatus("zombie", rec,
                                f"登记的进程已不在监听 {'/'.join(str(p) for p in silent)}")
        return LaunchStatus("running", rec)

    def adopt(self, comps: Dict[str, Component]) -> List[LaunchStatus]:
        """打开工具时对每个可启动组件做一次只读认定。绝不拉起进程。

        返回**所有**可启动组件的状态，按 key 升序。2026-10-06 改的：
        原来它返回 `[self.status(k, c) for k, c in comps.items() if launch]`
        的全部元素，但调用方（与护栏）习惯取 `[0]` ——只有一个组件时看不出问题，
        扩到 9 个之后 `[0]` 拿到的是字母序第一个（activemq）而不是被测组件，
        护栏于是红在"断言 not_installed != running"这种看不懂的地方。
        语义含糊的返回值是缺陷本身，不是测试的错。"""
        records = load_running_map()
        return [self.status(k, c, records) for k, c in sorted(comps.items())
                if getattr(c, "launch", None) is not None]

    def reconcile(self, comps: Dict[str, Component]) -> Dict[str, LaunchStatus]:
        """一次性认定 + 清僵尸：只处理 LAUNCH_KEYS 里的组件。

        计划二会往登记表加组件，届时旧登记不该被本期代码删掉，
        所以这里按"认得的 key"过滤，而不是清全部文件。"""
        records = load_running_map()
        out: Dict[str, LaunchStatus] = {}
        dirty = False
        for key in LAUNCH_KEYS:
            comp = comps.get(key)
            if comp is None or getattr(comp, "launch", None) is None:
                continue
            if key not in records:
                continue          # 没有登记的 key 不是"待认定"的东西：卡片自己的
                                  # status() 会答"未运行"，reconcile 只负责把有过登记的
                                  # 一条条判完，返回集因此可以为空（用例钉的就是这个）
            st = self.status(key, comp, records)
            if st.state == "zombie":
                records.pop(key, None)
                dirty = True
                st = LaunchStatus("not_installed_or_stopped")
            out[key] = st
        if dirty:
            save_running_map(records)
        return out

    def start(self, comp: Component, comps: Dict[str, Component],
              sleeper=time.sleep) -> StartResult:
        spec = getattr(comp, "launch", None)
        if spec is None:
            return StartResult(False, "gate", "本工具暂不支持启动该组件")
        existing = load_running_map().get(comp.key)
        if existing and self._is_listening(existing.port):
            return StartResult(False, "gate",
                               f"{comp.display_name} 已在运行（端口 {existing.port}）",
                               record=existing, console_url=existing.console_url)

        java_home = resolve_java_home(comps)
        ok, reason = launch_gate(comp, spec, java_home)
        if not ok:
            return StartResult(False, "gate", reason)

        base = spec.main_port
        # is_free 显式按名字传，不靠默认值绑定：默认参数在 def 时就把函数绑死了，
        # 测试 patch main.port_is_free 会失效。
        # 端口策略（2026-10-06 起）：只用官方默认端口，不平移；被占就结束占用者。
        # 结束掉了谁要告诉用户 —— "我杀了某个进程"这种事不说出来是不道德的。
        evicted: List[str] = []
        port_plan, why = choose_ports(spec, is_free=port_is_free, evicted=evicted)
        if not port_plan.main:
            return StartResult(False, "port", why)
        port_notes = [f"端口被占用，已结束占用者：{x}" for x in evicted]

        data_dir = CONFIG_DIR / f"{comp.key}-data"
        log_file = data_dir / "logs" / "byte-tools.out"
        ensure_dir(log_file.parent)
        # 端口回写必须在 spawn 之前做完：改了配置却没起进程、或起进程时配置没生效，
        # 两边状态对不上时比"没启动"更难归因。
        ok, why, notes = prepare_ports(comp, spec, port_plan, data_dir)
        # "我结束了哪个进程"必须跟着结果回到卡片：静默杀进程却不说是谁，
        # 用户事后发现某程序被杀会完全不知道是哪一步干的。
        notes = list(port_notes) + list(notes)
        if not ok:
            return StartResult(False, "writeback", why, notes=notes)
        plan = build_launch_plan(comp, spec, java_home, port_plan.main, log_file)
        # 前置准备（kafka 的 KRaft format 等）。必须在 spawn 之前：
        # 配了 --ignore-formatted 所以重复跑幂等（实测 rc=0），
        # 而漏了它 kafka 会直接 `No readable meta.properties files found.`。
        ok_pre, why_pre, pre_notes = run_pre_start(comp, spec, plan)
        notes = notes + list(pre_notes)
        if not ok_pre:
            return StartResult(False, "prestart", why_pre, notes=notes)

        # 重定向句柄在 Popen 把它交给子进程后立刻由父进程关掉（with 退出）：
        # Windows 上父进程留着一个打开的日志句柄，既漏句柄又会让临时目录删不掉；
        # 子进程拿到的是 CreateProcess 复制过去的一份，关自己这份不影响它。
        with open(plan.log_file, "ab", buffering=0) as log_fh:
            popen_kw = dict(cwd=str(plan.cwd), env=plan.env,
                            stdout=log_fh,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            if CURRENT_OS == "Windows":
                popen_kw["creationflags"] = DETACH_FLAGS | subprocess.CREATE_NEW_PROCESS_GROUP
                if CREATE_NO_WINDOW:
                    popen_kw["creationflags"] |= CREATE_NO_WINDOW
            else:
                popen_kw["start_new_session"] = True

            try:
                proc = subprocess.Popen(plan.argv, **popen_kw)
            except OSError as exc:
                return StartResult(False, "spawn", f"拉起失败：{exc}")

            # 第二个进程（rocketmq 的 broker）。顺序在主进程之后 ——
            # broker 要向 namesrv 注册，namesrv 没起来它会反复重试。
            #
            # 拉起失败要**连主进程一起收掉**：留下一个"namesrv 在跑、broker 没起来"
            # 的半死状态，比直接失败更难归因（用户看到 9876 在听就以为服务可用）。
            for extra in (spec.extra_processes or []):
                try:
                    argv_extra = [t.format(**_plan_mapping(comp, spec, plan))
                                  for t in extra[CURRENT_OS]]
                except (KeyError, IndexError):
                    return StartResult(False, "spawn", f"启动命令里的占位符无法替换：{extra}")
                try:
                    subprocess.Popen(argv_extra, **popen_kw)
                except OSError as exc:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    return StartResult(False, "spawn",
                                       f"第二个进程拉起失败：{exc}"
                                       f"（命令：{argv_extra[0]}）")

        # 有界探活：按"每轮 sleeper(1.0) 至多 startup_timeout 轮"计数而不是纯墙钟
        # deadline —— deadline 写法在 sleeper 被替换成 no-op 时会退化成烧 CPU 的
        # 忙等（提交信息钉的就是"有界探活后才登记"）。真实运行里每轮睡 1 秒，
        # 语义等价于 startup_timeout 秒内未监听即放弃。
        for _ in range(max(1, int(spec.startup_timeout))):
            # 整簇都要在听才算起来：Nacos 的 gRPC 9848/9849 与 ActiveMQ 的 broker 口
            # 没起来时控制台能开、客户端连不上，只探主口会登记成一个"半死"的运行中。
            if all(self._is_listening(p) for p in port_plan.all_ports):
                rec = RunRecord(key=comp.key,
                                version=resolve_launch_version(comp)
                                or comp.versions[0].version,
                                home=str(plan.cwd), data_dir=plan.env.get(spec.data_dir_env, ""),
                                port=port_plan.main, console_url=plan.console_url,
                                pid=proc.pid,
                                pid_role="server" if spec.stop_kind == "pid" else "launcher",
                                started_at=time.time(), launcher_cmd=list(plan.argv),
                                ports=port_plan.all_ports)
                records = load_running_map()
                records[comp.key] = rec
                save_running_map(records)
                # 端口全在听 ≠ 控制台能用。这里再探一次控制台（**不改判定**：
                # 服务进程已在监听、登记已落盘，就仍然是"启动成功"），
                # 把"控制台还没就绪"作为一条提示行交给界面，好让用户看到
                # "再等一会儿"而不是点开一个 503 页面以为坏了（Jenkins 实测就是这样）。
                note = self._console_readiness_note(spec, port_plan.main)
                if note:
                    notes = list(notes) + [note]
                return StartResult(True, "running", record=rec,
                                   console_url=plan.console_url, notes=notes)
            sleeper(1.0)

        # 超时：把刚拉起的进程收掉，不留一个"没人登记的监听者"
        reason = (f"{spec.startup_timeout} 秒内端口 "
                  f"{'/'.join(str(p) for p in port_plan.all_ports)} 未监听"
                  f"（需要全部端口都在听）。启动输出见 {plan.log_file}，"
                  f"末尾内容：{self._tail(plan.log_file)}"
                  f"；{comp.display_name} 自身日志："
                  f"{vendor_log_tails(data_dir, plan.cwd, comp.key)}")
        try:
            proc.terminate()
        except OSError as exc:
            # 收尸失败必须出声：这个进程恰恰不在 running.json 里（spec §5）
            reason += f"；进程可能仍在监听（PID {proc.pid}，收尸失败：{exc}）"
        return StartResult(False, "timeout", reason, notes=notes)

    @staticmethod
    def _tail(path: Path, lines: int = 8) -> str:
        """失败归因要能直接看见（spec §5）：读日志末尾几行，读不到就说读不到。"""
        try:
            data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return "（日志还读不到）"
        return " / ".join(data[-lines:]) if data else "（日志为空）"

    def stop(self, comp: Component, comps: Dict[str, Component],
             deadline: float = 30.0, sleeper=time.sleep) -> StopResult:
        rec = load_running_map().get(comp.key)
        if rec is None:
            return StopResult(False, reason=f"{comp.display_name} 没有本工具的启动登记，无法确定该停哪个进程。")
        spec = comp.launch
        if spec.stop_kind == "shutdown_command" and spec.shutdown_commands.get(CURRENT_OS):
            # 占位符契约：这里喂得出 RunRecord 上的键（port/home/data_dir）。
            #
            # **env 必须与启动时一致**（2026-10-06 真机实测踩出来的）：
            # 之前这里 `subprocess.run(argv, cwd=rec.home)` 不传 env，
            # 于是 rabbitmqctl.bat 找不到 erl.exe（免安装 Erlang 不设系统变量）、
            # 拿不到 RABBITMQ_NODENAME —— 它**静默失败**（输出被 DEVNULL 吞掉），
            # 表现是「点了停止，30 秒后弹窗问要不要强杀」。
            # 能优雅停的组件必须真的优雅停下，否则这条路径等于没接。
            data_dir = rec.data_dir or str(CONFIG_DIR / f"{comp.key}-data")
            #占位符要凑齐：stop 侧除了 port/home/data_dir，nginx 还要 {conf}
            #（它靠 -c 定位配置、不靠 cwd）—— 少一个就 KeyError 崩在停止流程里。
            argv = [t.format(port=rec.port, home=rec.home, data_dir=data_dir,
                             conf_dir=str(Path(data_dir) / "conf"),
                             conf=config_file_for(comp, Path(data_dir)),
                             java="", war="",
                             log_file=str(Path(data_dir) / "logs" / "byte-tools.out"))
                    for t in spec.shutdown_commands[CURRENT_OS]]
            env = dict(os.environ)
            if spec.extra_env:
                for name, template in spec.extra_env.items():
                    try:
                        env[name] = template.format(
                            port=rec.port, home=rec.home, data_dir=data_dir,
                            conf_dir=str(Path(data_dir) / "conf"), war="",
                            log_file=str(Path(data_dir) / "logs" / "byte-tools.out"))
                    except (KeyError, IndexError):
                        pass
            if spec.prereq is not None:
                erl = find_erlang_home_erl()
                if erl:
                    env["PATH"] = str(Path(erl).parent) + os.pathsep + env.get("PATH", "")
                    env["ERLANG_HOME"] = str(Path(erl).parent.parent)
            try:
                # 45 秒：子代理实测 rabbitmqctl stop 1~4s 就返回，
                # 但它要先等 broker 把未落盘消息写完；给足余量，
                # 否则会误判成「停不掉」并弹强杀确认框（能优雅停就别强杀）。
                subprocess.run(argv, cwd=rec.home, env=env, timeout=45,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired):
                pass
        elif spec.stop_kind == "port_lookup" or CURRENT_OS == "Windows":
            # 端口是真相：整簇都空了就当已停（下面的等待循环会清登记），别吓用户。
            ports = tuple(rec.ports) or (rec.port,)
            if not any(self._is_listening(p) for p in ports):
                records = load_running_map()
                records.pop(comp.key, None)
                save_running_map(records)
                return StopResult(True,
                                  reason=f"{comp.display_name} 已经不在监听 "
                                         f"{'/'.join(str(p) for p in ports)}，登记已清。"
                                         f"{self._leftover_note(spec)}")
            if spec.stop_kind != "port_lookup":
                # **登记的 PID 已经死了、端口却还在听**（2026-10-08 真机实测定位）：
                # java -jar 在 Windows 上由 java.exe 先起一个子 JVM（或启动器先退），
                # 于是 running.json 里那一行 pid 可能已经不存在，真正监听的是它的子进程。
                # 旧代码在这里直接回 need_force，而 force_stop 又只认"活着的登记 PID"
                # （`if self._process_alive(rec.pid)`）→ 两边都推给对方的死角：
                # 用户点停止 → 弹"要强制结束吗" → 点确定 → 回"我什么都没杀"，
                # 最后只能自己去任务管理器里杀 java.exe。
                # 现在在这里按端口反查唯一归属，把"该杀谁"查清楚再交给 force_stop。
                live = [p for p in (tuple(rec.ports) or (rec.port,)) if self._is_listening(p)]
                owner = ""
                owners = self._lookup_pids(tuple(live)) if live else {}
                mine = {p: pid for p, pid in owners.items() if pid != os.getpid()}
                # **判据用"登记 PID 是不是持有端口的那个"，而不是"登记 PID 还活着吗"**
                # （2026-10-08 实测教训）：PID 存活查询会误判 —— 一个早已退出的 PID
                # 在 Windows 上可能被 OpenProcess 判成"还在"（PID 被系统回收或
                # 句柄语义差异），于是"死者"被当成"凶手"，真正的监听进程毫发无伤。
                # 端口归属是我们**刚查出来的事实**，没有这种不确定性。
                if mine and len(set(mine.values())) == 1 and rec.pid not in set(mine.values()):
                    real_pid = next(iter(set(mine.values())))
                    owner = (f"登记的 PID {rec.pid} 已经不持有该端口，"
                             f"实际监听的是 PID {real_pid}（java 启动器先退出、子 JVM 在听）。")
                return StopResult(False, need_force=True,
                                  reason=(f"{comp.display_name}（端口 {rec.port}）"
                                          f"{owner + ' ' if owner else ''}"
                                          f"在 Windows 上只能直接终止进程，"
                                          f"这会打断正在进行的任务、可能丢未落盘的配置。要强制结束吗？"))
            # port_lookup 没有优雅手段：厂商的关闭脚本按进程名强杀会误伤本机同名实例，
            # 而登记的 PID 是包装脚本不是服务进程。所以第一步只请示，一个进程都不碰。
            return StopResult(False, need_force=True,
                              reason=(f"{comp.display_name}（端口 "
                                      f"{'/'.join(str(p) for p in ports)}）没有可用的优雅停止手段："
                                      f"它的启动脚本是包装器，登记的 PID 不是服务进程，"
                                      f"而厂商自带的关闭脚本按进程名强杀、会误伤本机其它同名实例。"
                                      f"要按端口找到那个进程并强制结束吗？"))
        else:
            self._terminate(rec)

        # 与 start() 同一套"有界轮次"约定（main.py 里 start 的注释钉过）：按轮计数、
        # 每轮 sleeper(1.0)、至少探一次。用 deadline 递减做墙钟会在 sleeper 被注入成
        # 短睡时把宽限期静默缩短，no-op 时退化成忙等。
        ports = tuple(rec.ports) or (rec.port,)
        for _ in range(max(1, int(deadline))):
            if not any(self._is_listening(p) for p in ports):
                records = load_running_map()
                records.pop(comp.key, None)
                save_running_map(records)
                return StopResult(True, reason=f"{comp.display_name} 已停止，端口 "
                                               f"{'/'.join(str(p) for p in ports)} 已释放。"
                                               f"{self._leftover_note(spec)}")
            sleeper(1.0)
        return StopResult(False, need_force=True,
                          reason=(f"{comp.display_name} 在 {int(deadline)} 秒内没停下来（端口 "
                                  f"{'/'.join(str(p) for p in ports)} 仍在听）。"
                                  f"要强制结束这个进程吗？强制结束可能丢未落盘的数据。"))

    def _leftover_note(self, spec: Optional[LaunchSpec]) -> str:
        """停止成功后附在 reason 里的残留辅助进程提示；没登记或没查到就是空串。"""
        names = tuple(getattr(spec, "leftover_processes", ()) or ())
        if not names:
            return ""
        return _leftover_process_note(self._process_images(names))

    def _console_readiness_note(self, spec: LaunchSpec, port: int) -> str:
        """启动成功后探一次控制台，返回给用户的提示行（没问题时返回空串）。

        为什么值得多花一次 HTTP（2026-10-08 真机实测定位）：
        Jenkins 的 8080 一开始监听就回 `503 Please wait while Jenkins is getting
        ready to work` —— "已启动"是真的，但用户点控制台会看到一个等待页。
        与其让他怀疑没启动成功，不如在日志里点明"控制台还在初始化"。

        判据只用于**提示**，不参与"启动成功/失败"：服务进程确实在监听、
        登记也确实落盘了，那就是启动成功（把 5xx 当失败会让 Jenkins 启动永远判失败）。
        """
        if not spec.console_path:
            return ""
        url = f"http://127.0.0.1:{port}{spec.console_path}"
        try:
            r = requests.get(url, timeout=8, allow_redirects=True, headers=HTTP_UA)
            code = r.status_code
        except Exception:
            return ""
        if code >= 500:
            return (f"已启动，但控制台 {url} 现在返回 {code}（服务还在初始化），"
                    f"稍等一会儿再点控制台；端口已经在正常服务。")
        return ""

    def force_stop(self, key: str, sleeper=time.sleep, rounds: int = 5) -> StopResult:
        """用户明确同意后的强制结束。仍然只在"端口确实释放"时才清登记。"""
        rec = load_running_map().get(key)
        if rec is None:
            return StopResult(False, reason="没有登记记录")
        ports = tuple(rec.ports) or (rec.port,)
        # 记录"动手前就在听的口"。判失败时要说清是"我们杀完它还在听"还是
        # "本来就在听且我们没动手"——两者的归因完全不同，不能混成一句
        # "可能是别的进程占着"（真机2026-10-06实测就踩过这个坑，见下）。
        live_before = [p for p in ports if self._is_listening(p)]
        killed: List[int] = []
        if live_before:
            owners = self._lookup_pids(tuple(live_before))
            mine = {p: pid for p, pid in owners.items() if pid != os.getpid()}
            if rec.pid_role == "server":
                if self._process_alive(rec.pid):
                    try:
                        os.kill(rec.pid, 9)
                        killed.append(rec.pid)
                    except OSError:
                        pass
                if mine and not killed:
                    # 登记 PID 说"还活着"、但它**并不是**持有端口的那一个
                    # （java 启动器先退、子 JVM 在听；或 PID 被系统回收后判活有误）：
                    # 只杀登记 PID 的话端口永远不会释放，用户点停止永远停不掉。
                    # 归属唯一才动手（mine 的构造保证），且只杀端口真正的主人。
                    for pid in sorted(set(mine.values())):
                        try:
                            os.kill(pid, 9)
                            killed.append(pid)
                        except OSError:
                            pass
            elif mine:
                # 三重闸：① 有我们自己的登记（上面 rec is not None 已保证）
                #      ② 不是我们自己（pid != os.getpid()）
                #      ③ 用户已确认 —— 走到 force_stop 本身就是确认
                # 归属有歧义（同口多 PID）时 _pick_unique_pids 不给结果，宁可不杀。
                for pid in sorted(set(mine.values())):
                    try:
                        os.kill(pid, 9)
                        killed.append(pid)
                    except OSError:
                        pass
            else:
                # 端口反查没给出"唯一、且不是我们自己"的对象 → 一个都不许杀。
                # 这里必须当场把"为什么没动手"说清并返回：只往下走复查循环，
                # 用户拿到的就是"端口还在听，可能是别人占着"——把我们的不作为说成别人的错。
                return StopResult(False, need_force=True,
                                  reason=(f"没有找到可以安全强制结束的进程：端口 "
                                          f"{'/'.join(str(p) for p in live_before)} 仍在听，"
                                          f"但端口反查没有给出唯一归属（或给出的就是我们自己）。"
                                          f"已放弃强制结束，登记保留，不动任何进程。"))
        # 终止调用返回 ≠ 监听 socket 已关闭。**必须先给进程一个退出窗口再开始复查**——
        # 真机 2026-10-06 实测：JVM 收到 TerminateProcess 后要几百毫秒到几秒才真正松开
        # 监听 socket。原来"杀完立刻进复查循环"，rounds=1 时循环体只跑一次就判"还在听"，
        # 于是一次成功的强杀被报成"可能是别的进程占着端口"——而端口其实随后就释放了，
        # 登记却被留了下来（用户看到的就是"停止按钮点了没用"）。
        # 与 start() 同一套"有界轮次"约定：每轮 sleeper(1.0) 后复查，最少探一次。
        for _ in range(max(1, int(rounds))):
            if not any(self._is_listening(p) for p in ports):
                records = load_running_map()
                records.pop(key, None)
                save_running_map(records)
                return StopResult(True, reason="已强制结束并释放端口。"
                                               f"{self._leftover_note(LAUNCH_OF.get(key))}")
            sleeper(1.0)
        left = [p for p in ports if self._is_listening(p)]
        # 归因要分清两种"还在听"：我们杀过 → 大概率是进程还没退出完；
        # 没杀过（kill 抛了 OSError 或 pid 本就不活）→ 才可能是别人占着。
        if killed and set(left) & set(live_before):
            return StopResult(False, need_force=True,
                              reason=(f"已向进程 {'/'.join(str(p) for p in killed)} 发出强制结束，"
                                      f"但端口 {'/'.join(str(p) for p in left)} 在 "
                                      f"{max(1, int(rounds))} 秒内仍未释放。"
                                      f"该进程可能在做长耗时收尾；再点一次强制结束，"
                                      f"或先确认它是否还占着资源。"))
        return StopResult(False, need_force=True,
                          reason=f"端口 {'/'.join(str(p) for p in left)} 仍在监听，"
                                 f"本次没有成功结束任何进程，可能是别的程序占着这个端口。")


# 卡片按钮要的是同一个登记/探针视图：多张卡片各持一个 ServiceManager 会把
# per-key 门与 running.json 的读写拆成两套口径。
SERVICE_MANAGER = ServiceManager()


# ---------------------------------------------------------------------------
# 「接管用户自装版本」的数据层
# 设计：docs/superpowers/specs/2026-09-30-external-version-discovery-switching-design.md §4
#
# 背景（v2 的核心让步）：Windows 把进程 PATH 合成成「系统段在前 + 用户段在后」，
# 所以只往 HKCU 写用户级条目，**永远压不住** HKLM 里那条更靠前的老版本 ——
# 实测 E6 显示 jdk / maven / bun / node 四个组件当前全被压住。要"真切换"就必须
# 动 HKLM，而那是需要提权、且可能把整机 PATH 改坏的高危操作，所以：
#   · 任何一次接管都先留**原文快照**（未展开、含类型），并存一份独立备份文件；
#   · 还原按快照逐 hive 写回原文，existed=false 的键要**删除**而不是写空串；
#   · active（工作区登记）与 takeover（外部接管）**两条键互斥**，不允许同时存在。
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredVersion:
    """一处「可用的组件安装」：本工具工作区里的，或系统里用户自己装的。

    home 是**安装根目录**（不是 bin 目录）；source 记录发现来源，界面据此标注。
    外部候选的 version 必须来自真跑一次版本命令（§5.1 第 6 步）——探测不出来就
    不列入，宁可不显示，也不显示一个"认错了的目录"。
    """

    home: Path
    source: str          # "workspace" | "env:<变量名>" | "path:<HKCU|HKLM>" | "registry:py"
    version: str = ""


@dataclass
class ActiveTarget:
    """当前生效目标（单一真源）：可能落在工作区版本，也可能落在被接管的外部版本。

    kind 决定界面上那句"生效 X"该怎么写，也决定卸载/切换时要清哪一侧的登记。
    """

    kind: str            # "workspace" | "external"
    version: str
    home: Path
    level: str = ""      # "user" | "machine"；工作区固定 user，外部取决于是否动过 HKLM


def _update_config(mutate) -> None:
    """config.json 的合并写通用入口：读出 → 交给 mutate 就地改 → 原子写回。

    必须是"读-改-写"而不是整体覆盖：active / takeover / selections / view_mode
    是四个互不相干的写入方，任何一方整体覆盖都会把别人的数据抹掉
    （R3.2 的教训：_save_settings 曾经整体覆盖，把 active 登记表清了）。
    """
    data: Dict[str, object] = {}
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    mutate(data)
    _atomic_write_config(data)


def load_takeover_map() -> Dict[str, dict]:
    """读「接管登记表」；形状不合法的条目一律跳过，绝不把脏数据往下传。

    返回: Dict[str, dict]  {组件 key: {home, version, level, snapshot, backup_file}}

    读侧要挑剔的理由：还原整条链路都靠它，读进来一个半截快照比"没有这条"
    更危险——那会让还原拿一份错的原值去写 HKLM。
    """
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    raw = data.get("takeover") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, dict] = {}
    for key, entry in raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        home, version = entry.get("home"), entry.get("version")
        if not isinstance(home, str) or not home:
            continue
        if not isinstance(version, str) or not version:
            continue
        if not isinstance(entry.get("snapshot"), dict) or not entry["snapshot"]:
            continue
        if entry.get("level") not in ("user", "machine"):
            continue
        out[key] = entry
    return out


def save_takeover_entry(comp_key: str, entry: dict) -> None:
    """登记一次「接管外部版本」，并**清掉同一组件的 active 登记**。

    合并写：不动 selections / view_mode / 其他组件的条目。
    active 与 takeover 是互斥的两条键（§4.3）：接管生效期间必须没有 active[key]，
    否则界面按 active 显示"生效 3.10.0（工作区）"、而实际命令行跑的是外部版本 ——
    正是设计里点名要避免的"两边都不认的孤儿态"。
    """
    def _mutate(data: Dict[str, object]) -> None:
        takeover = data.get("takeover")
        if not isinstance(takeover, dict):
            takeover = {}
        takeover[comp_key] = entry
        data["takeover"] = takeover
        active = data.get("active")
        if isinstance(active, dict) and comp_key in active:
            active.pop(comp_key, None)
            data["active"] = active

    _update_config(_mutate)


def has_external_takeover(comp: Component) -> bool:
    """该组件当前是否处在"接管了外部版本"的状态（界面据此显示还原按钮）。"""
    return comp.key in load_takeover_map()


def drop_takeover_entry(comp_key: str) -> Optional[dict]:
    """删除 takeover[comp_key] 并返回被删的那一条（不存在则 None）。

    切回工作区版本时必须调它（§4.3 两条键互斥）：不允许出现"登记表说工作区 17、
    快照还挂着外部 home"这种两边都不认的孤儿态。
    """
    removed: Optional[dict] = None

    def _mutate(data: Dict[str, object]) -> None:
        nonlocal removed
        takeover = data.get("takeover")
        if isinstance(takeover, dict) and comp_key in takeover:
            removed = takeover.pop(comp_key)
            data["takeover"] = takeover

    _update_config(_mutate)
    return removed


def load_machine_fix_map() -> Dict[str, dict]:
    """读「为工作区版本提权改过系统变量」的登记表（R3.19）；形状不合法一律跳过。

    返回: Dict[str, dict]  {组件 key: {home, version, level, snapshot, added, backup_file}}

    为什么需要**另一张**表、而不复用 takeover：这两件事的语义完全不同。
    takeover 记的是"把用户在别处装的那一份设为生效版本"，所以它必须与 active 互斥
    （否则界面按 active 说工作区版本生效、命令行跑的却是外部版本）。而这里记的是
    "为了让**工作区版本**赢过系统级同名条目，我们动过 HKLM"—— 生效版本仍是工作区
    那一个，active[key] 照常存在，两条键**并存才是正确状态**。

    读侧同样挑剔：还原整条链路都靠它，半截快照比"没有这条"更危险。
    """
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    raw = data.get("machine_fix") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, dict] = {}
    for key, entry in raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        home, version = entry.get("home"), entry.get("version")
        if not isinstance(home, str) or not home:
            continue
        if not isinstance(version, str) or not version:
            continue
        snapshot = entry.get("snapshot")
        # 只要 HKLM 那一半：用户级的改动由 apply_active_version / 还原链路自己管，
        # 这里混进 HKCU 会在还原时把用户变量也写回一遍（越权改动）。
        if not isinstance(snapshot, dict) or not snapshot.get("HKLM"):
            continue
        out[key] = entry
    return out


def save_machine_fix_entry(comp_key: str, entry: dict) -> None:
    """登记一次「为工作区版本改过系统变量」；**刻意不动 active**（两条键可以并存）。"""
    def _mutate(data: Dict[str, object]) -> None:
        table = data.get("machine_fix")
        if not isinstance(table, dict):
            table = {}
        table[comp_key] = entry
        data["machine_fix"] = table

    _update_config(_mutate)


def drop_machine_fix_entry(comp_key: str) -> Optional[dict]:
    """删除 machine_fix[comp_key] 并返回被删的那一条（不存在则 None）。"""
    removed: Optional[dict] = None

    def _mutate(data: Dict[str, object]) -> None:
        nonlocal removed
        table = data.get("machine_fix")
        if isinstance(table, dict) and comp_key in table:
            removed = table.pop(comp_key)
            data["machine_fix"] = table

    _update_config(_mutate)
    return removed


def has_machine_fix(comp: Component) -> bool:
    """该组件是否有"为工作区版本提权改过系统变量"的欠账（界面据此显示还原按钮）。"""
    return comp.key in load_machine_fix_map()


def write_takeover_backup(comp_key: str, snapshot: dict) -> str:
    """把同一份快照另存为一个独立文件，返回相对 CONFIG_DIR 的路径。

    这是 §4.2 要求 backup_file 的全部理由：config.json 万一被写坏、或被用户手改成
    非法形状，读侧会跳过该条 —— 那时只有这个文件还能把原值找回来。
    """
    stamp = time.strftime("%Y%m%dT%H%M%S")
    rel = f"takeover-backups/{comp_key}-{stamp}.json"
    target = CONFIG_DIR / rel
    ensure_dir(target.parent)
    target.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False),
                      encoding="utf-8")
    return rel


def resolve_active_target(comp: Component) -> Optional[ActiveTarget]:
    """解析生效目标（不含"PATH 实际命中"那一级，那一级要卡片上下文）。

    顺序（§4.3）：takeover（外部）→ active 登记（工作区）→ 持久层 HOME 反推。
    为什么 takeover 排最前：接管生效期间 active[key] 必须已被删掉（互斥），
    真出现两条并存时，以"用户最后一次动作"为准——接管是更晚、更显式的动作。
    """
    if not comp.multi_version:
        return None
    takeover = load_takeover_map().get(comp.key)
    if takeover:
        return ActiveTarget(kind="external", version=takeover["version"],
                            home=Path(takeover["home"]),
                            level=str(takeover.get("level") or ""))
    ver = load_active_map().get(comp.key) or infer_active_from_env(comp)
    if ver:
        return ActiveTarget(kind="workspace", version=ver,
                            home=comp.install_dir(ver), level="user")
    return None


# ---------------------------------------------------------------------------
# §5.1 外部版本发现：把"用户自己装的版本"找出来
#
# 只对 7 个 multi_version 组件运行。四类来源：
#   ① 工作区（installed_versions，版本号现成）
#   ② 环境变量：枚举两 hive 全部值（**排除 Path 本身**），值指向的目录里有该组件
#      可执行文件即为候选。本机的 jdk8/jdk17/jdk21 三个变量靠这条被发现。
#   ③ PATH 条目：条目下直接有可执行文件即命中；若条目名是 bin/Scripts/cmd 之类，
#      说明它指的是 bin 目录，要退一级才是 home。
#   ④ Python 专属登记处：py -0p（拿不到就退回读注册表 InstallPath）。
#      **只有这条能发现"既不在 PATH、也没有 PYTHON_HOME"的版本**（本机 uv 那份）。
#
# 外部候选必须**真跑一次版本命令**才算数（probe_discovered_versions）：探测不出、
# 超时、解析不出的候选一律丢弃并记一行 warn —— 宁可不显示，也不显示一个认错了的目录。
# ---------------------------------------------------------------------------

# PATH 条目若以这些名字结尾，它指的是"可执行文件所在目录"而不是安装根目录。
_BIN_DIR_NAMES = {"bin", "scripts", "cmd", "condabin"}

# 外部版本发现 / 接管的**适用组件白名单**（设计 §5.1 第 1 句、§9 的 R-5）。
#
# 为什么不能直接用 comp.multi_version 当条件：自 2026-06-06 起 multi_version 恒为
# True（MULTI_VERSION_KEYS 已成空集），拿它当门槛等于对全部 27 个组件都开外部接管；
# 而这里每打开一个组件，就多一个"用户点一下我们就要改他系统 PATH"的入口。
# 用户要的是"语言/构建工具装了好几个版本时能切"，也就是下面这 7 个 —— 与
# bt_multiversion_tests.EXPECTED_MULTI_VERSION 是同一份名单（第二处登记处，
# 改这里必须同步改那里，否则测试会红）。
EXTERNAL_TAKEOVER_KEYS = {"jdk", "python", "node", "go", "maven", "gradle", "bun"}


def supports_external_takeover(comp: Component) -> bool:
    """该组件是否支持"识别并切换用户自己装的版本"。"""
    return comp.key in EXTERNAL_TAKEOVER_KEYS


def _extract_version_text(text: str) -> str:
    """从版本命令输出里抽出第一个像版本号的片段；抽不到返回原文截断。"""
    m = _re.search(r"\d+(?:\.\d+)+(?:[-._a-zA-Z]\w*)?", text or "")
    return m.group(0) if m else (text or "").strip()[:40]


def _enum_registry_values(root, subkey: str, extra_flags: int = 0) -> Dict[str, str]:
    """枚举注册表某个键下的全部字符串值；键不存在/读不到一律返回空表。"""
    import winreg  # type: ignore

    out: Dict[str, str] = {}
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | extra_flags) as key:
            index = 0
            while True:
                try:
                    name, value, _type = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if isinstance(value, str):
                    out[name] = value
    except Exception:
        return {}
    return out


def _windows_registry_env_values() -> List[Tuple[str, str, str]]:
    """列出两 hive 里除 Path 之外的全部环境变量：(hive 名, 变量名, 原文值)。

    Path 被排除是因为它由 _windows_registry_path_entries 单独按条目处理 ——
    当作"一个值"去看会得到一长串，命中与否毫无意义。
    """
    if CURRENT_OS != "Windows":
        return []
    import winreg  # type: ignore

    specs = (
        ("HKCU", winreg.HKEY_CURRENT_USER, "Environment", 0),
        ("HKLM", winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
         winreg.KEY_WOW64_64KEY),
    )
    result: List[Tuple[str, str, str]] = []
    for hive, root, subkey, flags in specs:
        for name, value in _enum_registry_values(root, subkey, flags).items():
            if name.lower() == "path":
                continue
            result.append((hive, name, value))
    return result


def _windows_registry_path_entries() -> List[Tuple[str, str]]:
    """两 hive 的 Path 条目：(hive 名, 条目原文)。未展开的 %VAR% 原样返回。"""
    if CURRENT_OS != "Windows":
        return []
    import winreg  # type: ignore

    specs = (
        ("HKCU", winreg.HKEY_CURRENT_USER, "Environment", 0),
        ("HKLM", winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
         winreg.KEY_WOW64_64KEY),
    )
    entries: List[Tuple[str, str]] = []
    for hive, root, subkey, flags in specs:
        values = _enum_registry_values(root, subkey, flags)
        raw = values.get("Path") or values.get("PATH") or ""
        for part in str(raw).split(";"):
            if part.strip():
                entries.append((hive, part.strip()))
    return entries


def _python_homes_from_py_launcher() -> List[str]:
    """跑 `py -0p` 拿 Python 安装根目录；拿不到返回空表。

    本机真实输出长这样（2026-10-08 实测，测试里就喂这两行）：
         -V:3.14 *        C:\\...\\Python314\\python.exe
         -V:Astral/CPython3.12.12 C:\\...\\cpython-3.12.12-windows-x86_64-none\\python.exe
    第二行那种"不在 PATH、也没有 PYTHON_HOME"的解释器，只有这条源看得见。
    """
    if CURRENT_OS != "Windows":
        return []
    try:
        proc = subprocess.run(["py", "-0p"], capture_output=True, text=True,
                              timeout=5, check=False, stdin=STDIN_DEVNULL,
                              creationflags=CREATE_NO_WINDOW)
    except Exception:
        return []
    homes: List[str] = []
    for line in (proc.stdout or "").splitlines():
        m = _re.search(r"([A-Za-z]:\\[^\s]+\.exe)\s*$", line.strip())
        if m:
            homes.append(str(Path(os.path.expandvars(m.group(1))).parent))
    return homes


def _python_homes_from_registry() -> List[str]:
    """退回读注册表 `Software\\Python\\<公司>\\<版本>\\InstallPath` 的默认值。

    公司键不限于 PythonCore —— Astral（uv 装的那份）也在这里。
    """
    if CURRENT_OS != "Windows":
        return []
    import winreg  # type: ignore

    homes: List[str] = []
    for root, flags in ((winreg.HKEY_CURRENT_USER, 0),
                        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY)):
        base = r"Software\Python"
        try:
            with winreg.OpenKey(root, base, 0, winreg.KEY_READ | flags) as k:
                companies = []
                i = 0
                while True:
                    try:
                        companies.append(winreg.EnumKey(k, i))
                    except OSError:
                        break
                    i += 1
        except Exception:
            continue
        for company in companies:
            sub = f"{base}\\{company}"
            try:
                with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | flags) as ck:
                    versions = []
                    j = 0
                    while True:
                        try:
                            versions.append(winreg.EnumKey(ck, j))
                        except OSError:
                            break
                        j += 1
            except Exception:
                continue
            for ver in versions:
                try:
                    with winreg.OpenKey(root, f"{sub}\\{ver}\\InstallPath", 0,
                                        winreg.KEY_READ | flags) as ik:
                        value, _t = winreg.QueryValueEx(ik, "")
                    if isinstance(value, str) and value:
                        homes.append(value)
                except Exception:
                    continue
    return homes


def discover_version_candidates(comp: Component) -> List[DiscoveredVersion]:
    """列出该组件的全部「可用安装」候选（尚未探测版本号）。

    返回: List[DiscoveredVersion]  工作区在前（版本号已填），外部候选在后（version 为空）

    只对 EXTERNAL_TAKEOVER_KEYS 里的 7 个组件有意义（§8 第 16 条测试守着这一点）：
    别的组件没有"装多个版本、切着用"的诉求，给它们列外部候选只会给界面添乱，
    而且每多一个组件就多一条"改用户系统 PATH"的路径。
    """
    if not supports_external_takeover(comp):
        return []

    cands: List[DiscoveredVersion] = []
    seen: List[str] = []

    def _add(home: str, source: str, version: str = "") -> None:
        raw = os.path.expandvars(str(home)).strip()
        if not raw:
            return
        if any(EnvManager._same_path(raw, s) for s in seen):
            return
        seen.append(raw)
        cands.append(DiscoveredVersion(home=Path(raw), source=source, version=version))

    for ver, path in installed_versions(comp):
        _add(str(path), "workspace", ver)

    if CURRENT_OS != "Windows":
        # 非 Windows 暂不做外部发现：接管路径（§5.4）本身就是 Windows 专有
        # （HKLM/HKCU + UAC），而设计文档里的实测数据也全部来自 Windows。
        # 宁可不列，也不给一个点了没用的按钮。
        return cands

    for _hive, _name, value in _windows_registry_env_values():
        if comp.exec_path_in_home(value):
            _add(value, f"env:{_name}")

    for hive, entry in _windows_registry_path_entries():
        if not comp.exec_path_in_home(entry):
            continue
        p = Path(os.path.expandvars(entry))
        home = p.parent if p.name.lower() in _BIN_DIR_NAMES else p
        _add(str(home), f"path:{hive}")

    if comp.key == "python":
        for home in (_python_homes_from_py_launcher() or []) + _python_homes_from_registry():
            _add(home, "registry:py")

    return cands


def probe_discovered_versions(comp: Component, cands: List[DiscoveredVersion],
                              log=None) -> List[DiscoveredVersion]:
    """对每个外部候选真跑一次版本命令，只留下探测成功的。

    入参 log: Optional[Callable[[str], None]]  记账用（拿不到就静默）

    §5.1 第 6 步的理由：折叠区里摆一行"E:\\soft\\jdk\\jdk17  17.0.12"，用户就会
    照着它做决定；这个版本号必须是**真跑出来的**，不能靠目录名猜。探测不出来的
    候选一律丢弃 —— 显示一个认错了的目录，比少显示一个更糟。
    """
    out: List[DiscoveredVersion] = []
    for cand in cands:
        if cand.source == "workspace":
            out.append(cand)
            continue
        exe = comp.exec_path_in_home(str(cand.home))
        if not exe:
            if log:
                log(f"{cand.home} 下找不到 {comp.exec_name}，不作为候选")
            continue
        text = _probe_version(str(exe), list(comp.version_args or ["--version"]))
        if not text:
            if log:
                log(f"{cand.home} 的版本命令没有回结果，不作为候选")
            continue
        out.append(DiscoveredVersion(home=cand.home, source=cand.source,
                                     version=_extract_version_text(text)))
    return out


# ---------------------------------------------------------------------------
# §5.2 复验（模块级）＋ §5.4 的「最小文本编辑」与校验（纯函数，可离线测）
#
# 这一组是整个功能最高风险面的核心：**把系统 PATH 写坏的后果是整机命令找不到**。
# 规则在这里写死，提权助手只是执行者：
#   · 一律读写**未展开原文**（%JAVA_HOME% 这类占位符原样保留）。绝不能拿
#     os.environ["PATH"] 或 expandvars 之后的值参与写入 —— 那会把占位符固化成
#     死路径，这是"把系统 PATH 改坏"的头号方式（设计 §5.4 R-保真）。
#   · 只做「整条删除 / 整条插入」，分隔符固定 ;，不重排、不去重、不改大小写、
#     不合并重复项（R-最小编辑）。
#   · 写完立刻自检：原有条目（除被删的）必须逐字仍在，含 system32 / \Windows 的
#     条目少一条就回滚（R-关键条目校验）。
# ---------------------------------------------------------------------------

_MACHINE_ENV_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
_MACHINE_KEY_SUBSTRINGS = ("system32", "\\windows")
_REG_TYPE_NAMES = {1: "REG_SZ", 2: "REG_EXPAND_SZ", 3: "REG_BINARY", 4: "REG_DWORD"}


def _exec_name_variants(comp: Component) -> List[str]:
    """某个组件命令在磁盘上的几种可能落盘名（Windows 按 PATHEXT 展开）。"""
    name = comp.exec_name or ""
    if not name:
        return []
    if os.path.splitext(name)[1]:
        return [name]
    if CURRENT_OS != "Windows":
        # POSIX 要带上 `.sh`：2026-10-10 读 apache-tomcat-10.1.60.tar.gz 实测，
        # `bin/` 里**没有**不带扩展名的 `catalina`，只有 `catalina.sh` / `catalina.bat`。
        # 只认裸名的话，Linux/macOS 上装完 tomcat 会连入口都找不到（状态与版本探测全落空）。
        # 裸名仍排第一：python3 / gradle 这类有裸名的，别被 .sh 挤到后面。
        return [name, name + ".sh"]
    return [name + suffix for suffix in (".exe", ".cmd", ".bat", "")]


def path_effective_check(comp: Component,
                         expected_bin: Optional[str]) -> Tuple[str, Optional[str]]:
    """复验：按系统合成的 PATH 顺序，命令行第一个命中的目录是不是 expected_bin。

    返回: ("ok", None) | ("shadowed", 抢走命令的目录) | ("unknown", None)
    unknown 含"拿不到合成环境"和"PATH 里根本没有这个命令"两种，**都不许当成通过**：
    前者是没测，后者说明命令压根不在 PATH 上。

    为什么必须有这一步（2026-09-30 真机实测）：用户 PATH 整体排在系统 PATH 之后，
    且系统 PATH 里的 %JAVA_HOME%\\bin 是按**系统**表展开定死的 —— 我们把变量与
    自己的 PATH 条目都写对了，命令行仍可能命中用户自装的那个版本。只报"已切到 X"
    就是假话。
    """
    if not expected_bin:
        return "unknown", None
    composed = EnvManager.composed_env()
    path_value = composed.get("PATH")
    if not path_value:
        return "unknown", None
    names = _exec_name_variants(comp)
    if not names:
        return "unknown", None
    for entry in path_value.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        try:
            hit = any(os.path.exists(os.path.join(entry, n)) for n in names)
        except (OSError, ValueError):
            continue
        if hit:
            if EnvManager._same_path(entry, expected_bin):
                return "ok", None
            return "shadowed", entry
    return "unknown", None


_MACHINE_VAR_RE = _re.compile(r"%([^%]+)%")


def expand_machine_value(raw: Optional[str], depth: int = 4) -> str:
    """把 %VAR% 按**系统（HKLM）自己**的变量值展开；不套用当前进程的环境块。

    为什么不能直接用 os.path.expandvars：那用的是本进程环境（含用户变量与进程启动时
    的快照），而系统 PATH 里那条 `%JAVA_HOME%\\bin` 是 Windows 按**系统**表展开的。
    两者不一致时，"这条到底算不算系统级条目"就会判错 —— 而这个判定决定要不要提权，
    判错的代价是多余地弹一次 UAC，或者该提权时没提、用户继续被压住。
    本机就是嵌套的：HKLM Path 有 `%JAVA_HOME%\\bin`，而 HKLM JAVA_HOME = `%jdk21%`，
    所以要递归展开（depth 兜住环状引用）。
    """
    if not raw:
        return ""
    if depth <= 0:
        return str(raw)

    def _sub(match) -> str:
        name = match.group(1)
        value, _type_name = read_machine_env_raw(name)
        if not value:
            return match.group(0)          # 展开不了就原样留着，不猜
        return expand_machine_value(value, depth - 1)

    return _MACHINE_VAR_RE.sub(_sub, str(raw))


def machine_path_entries() -> List[str]:
    """系统级（HKLM）Path 的条目，已按系统变量展开；读不到返回空表。"""
    raw, _type_name = read_machine_env_raw("Path")
    if not raw:
        return []
    return [expand_machine_value(p).strip() for p in str(raw).split(";")]


def shadow_location(shadow: Optional[str]) -> str:
    """抢走命令的那个目录写在哪一段：'machine' | 'user' | 'outside'。

    这个判定决定"还能不能自己救"（R3.19），三态各有各的正确处置，不许混：
      · machine —— 写在**系统级** Path 里。Windows 合成进程 PATH 的规则是
        「系统段整体在前 + 用户段整体在后」，所以往用户级怎么写都压不住它，
        只有提权改系统 Path 才可能生效。
      · user —— 就在用户段里、只是排在我们那条前面；把它让位即可，**零提权**。
      · outside —— 两段都找不到（PATH 由别的机制注入，或注册表刚被改过尚未反映）。
        这种情况**不提权**：拿不准病灶在哪就动系统变量是无据升级，先如实报告。
    """
    if not shadow:
        return "outside"
    for entry in machine_path_entries():
        if entry and EnvManager._same_path(entry, shadow):
            return "machine"
    try:
        user_entries = EnvManager.read_user_path_entries()
    except Exception:  # noqa: BLE001
        user_entries = []
    for entry in user_entries or []:
        if entry and EnvManager._same_path(entry, shadow):
            return "user"
    return "outside"


def edit_path_raw(raw: str, remove: List[str], add: str = "") -> str:
    """在未展开原文上做「整条删除 +（可选）整条插入到最前」。

    入参 raw:    str        注册表里的 Path 原文（可能含 %VAR%）
    入参 remove: List[str]  要删掉的条目（按展开后比较，Windows 忽略大小写）
    入参 add:    str        要插到最前面的条目；空串 = 只删不插
    返回: str               新原文，除被删/新增的那几条外**逐字不变**
    """
    parts = list(str(raw or "").split(";"))
    kept = [p for p in parts
            if not any(EnvManager._same_path(p, r) for r in (remove or []))]
    if add:
        kept = [add] + kept
    return ";".join(kept)


def validate_path_raw(before: str, after: str, remove: List[str],
                      add: str = "") -> List[str]:
    """改完的自检：返回问题列表，空列表 = 通过。

    刻意**不**用"再跑一遍 edit_path_raw 对比"来判定（那是自证），而是独立逐条核对：
    原有条目（除被删的）在 after 里逐字找得到、新增条目确实在最前、条目总数对得上，
    最后单独确认含 system32 / \\Windows 的关键条目没丢。
    """
    problems: List[str] = []
    # 关键条目先查，且**不受后面"条目数不对就提前返回"的影响**：条目数不对是最常见的
    # 损坏形态，若此时直接返回，报出来的就只有一句"数目不对"，看不出是不是把
    # system32 弄丢了 —— 而后者才是必须让用户一眼看见的要命信息。两个都要报。
    low_before, low_after = str(before or "").lower(), str(after or "").lower()
    for needle in _MACHINE_KEY_SUBSTRINGS:
        if needle in low_before and needle not in low_after:
            problems.append(f"关键条目丢失：原来是含 {needle!r} 的那一条不见了")

    before_parts = list(str(before or "").split(";"))
    after_parts = list(str(after or "").split(";"))
    removed = [p for p in before_parts
               if any(EnvManager._same_path(p, r) for r in (remove or []))]
    expected_count = len(before_parts) - len(removed) + (1 if add else 0)
    if len(after_parts) != expected_count:
        problems.append(f"条目数不对：改前 {len(before_parts)} 条、删 {len(removed)} 条、"
                        f"增 {1 if add else 0} 条，应为 {expected_count} 条，"
                        f"实际 {len(after_parts)} 条")
        return problems          # 条目数都不对，后面的逐条核对没有意义

    rest = list(after_parts)
    if add:
        if not rest or not EnvManager._same_path(rest[0], add):
            problems.append("新增条目没在最前面：实际第一条是 "
                            f"{rest[0] if rest else '(空)'!r}")
        else:
            rest.pop(0)
    for part in before_parts:
        if any(EnvManager._same_path(part, r) for r in removed):
            continue
        try:
            index = rest.index(part)
        except ValueError:
            problems.append(f"原条目丢失或被改动：{part!r}")
        else:
            rest.pop(index)
    return problems


def read_machine_env_raw(name: str) -> Tuple[Optional[str], str]:
    """读 HKLM 系统环境变量某个值的**未展开原文**与类型名。

    返回: (原文, 类型名)；该值不存在时 (None, "")。类型名必须拿回来，写回时要保持
          原来的 REG_EXPAND_SZ —— 写成 REG_SZ 会让 %VAR% 变成字面量，等于改坏了
          别人的变量。
    """
    if CURRENT_OS != "Windows":
        return None, ""
    import winreg  # type: ignore

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, reg_type = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None, ""
    return str(value), _REG_TYPE_NAMES.get(int(reg_type), str(reg_type))


def snapshot_machine_keys(names: List[str]) -> Dict[str, dict]:
    """对若干 HKLM 变量做原文快照，供还原使用。

    返回: {名: {"hive": "HKLM", "raw": 原文, "type": 类型名, "existed": bool}}

    existed=False 表示"改之前这个值根本不存在"，还原时必须**删除**该键，而不是写空串
    —— 空串会被别的程序当成"值为空"而不是"未设置"（设计 §4.2）。
    """
    snap: Dict[str, dict] = {}
    for name in names:
        if not name:
            continue
        raw, type_name = read_machine_env_raw(name)
        snap[name] = {"hive": "HKLM", "raw": raw, "type": type_name,
                      "existed": raw is not None}
    return snap


def read_user_env_raw(name: str) -> Tuple[Optional[str], str, str]:
    """读 HKCU 用户环境变量某个值的原文、类型名与 hive 名。

    返回: (原文, 类型名, "HKCU")；不存在时 (None, "", "HKCU")
    """
    if CURRENT_OS != "Windows":
        return None, "", "HKCU"
    import winreg  # type: ignore

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ) as key:
            value, reg_type = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None, "", "HKCU"
    return str(value), _REG_TYPE_NAMES.get(int(reg_type), str(reg_type)), "HKCU"


def snapshot_user_keys(names: List[str]) -> Dict[str, dict]:
    """对若干 HKCU 用户变量做原文快照（结构与 snapshot_machine_keys 一致）。"""
    snap: Dict[str, dict] = {}
    for name in names:
        if not name:
            continue
        raw, type_name, hive = read_user_env_raw(name)
        snap[name] = {"hive": hive, "raw": raw, "type": type_name,
                      "existed": raw is not None}
    return snap


# ---------------------------------------------------------------------------
# §5.3 用户级接管 / §5.4 提权接管 HKLM —— 让命令行真的用上用户选的那个版本
#
# 为什么非要动 HKLM 不可（2026-09-30 真机实测）：进程 PATH 的合成规则是
# 「系统段整体在前 + 用户段整体在后」，所以只写用户级**永远压不住**系统级同名条目。
# 本机 Maven 就是活例：HKLM Path 第 7 条是 E:\soft\maven\apache-maven-3.9.2\bin，
# HKCU Path 第 7 条是我们写的 .env-tools\maven\maven-3.10.0\bin；用户级写得再对，
# mvn -v 仍然是 3.9.2。只报「已切换」就是假话（用户已因此质疑过一次）。
#
# 因此流程是：先做**不需要提权**的用户级接管 → 复验；只有复验结论是 shadowed
# （被更靠前的目录压住）才征求提权改 HKLM。复验结论是 unknown（拿不到合成环境 /
# PATH 里根本没有这个命令）时**不升级** —— 拿不到结论不等于失败，为它弹 UAC 改系统
# 变量是无据升级，如实报「未能复验，请重开终端确认」即可（§5.3 第 4 步）。
# ---------------------------------------------------------------------------

ELEVATE_FLAG = "--bt-elevate"
ELEVATE_TIMEOUT_SEC = 90.0


def _external_bin_dir(comp: Component, home: Path) -> str:
    """外部版本该出现在 PATH 里的那个目录（写变量、复验、还原三处共用一套算法）。"""
    return str(home / comp.path_subdir) if comp.path_subdir else str(home)


def _remove_quietly(*paths: Path) -> None:
    """删临时文件；删不掉（被占用 / 已不存在）不是错误，不打断主流程。"""
    for p in paths:
        try:
            p.unlink()
        except OSError:
            pass


# --- HKCU 侧的原文保真写 -----------------------------------------------------

def write_user_env_raw(name: str, value: str, type_name: str = "") -> None:
    """把原文按**指定类型**写回 HKCU\\Environment，并广播环境变更。

    为什么不能直接用 EnvManager.write_user_env：那个函数按"值里有没有 %"猜类型
    （REG_EXPAND_SZ / REG_SZ）。还原时我们要的是"原来是什么类型就写回什么类型"，
    猜错等于把别人的 `%USERPROFILE%` 变成字面量（设计 §5.4 R-保真，同一条规则
    对用户级同样成立）。
    """
    import winreg  # type: ignore

    type_id = winreg.REG_EXPAND_SZ if (type_name == "REG_EXPAND_SZ"
                                       or (not type_name and "%" in value)) \
        else winreg.REG_SZ
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, type_id, value)
    try:
        EnvManager._broadcast_env_change()
    except Exception:
        pass


def delete_user_env_raw(name: str) -> None:
    """删除 HKCU 里的某个值；本来不存在则幂等返回。

    还原一条 `existed=False` 的快照必须走这里（删键），不能写空串 ——
    空串会让 detect() 之类的读侧误判成"已配置"（设计 §4.2）。
    """
    import winreg  # type: ignore

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass
    try:
        EnvManager._broadcast_env_change()
    except Exception:
        pass


def prepend_user_path_entry(entry: str) -> bool:
    """把 entry 挪到 HKCU Path 的**最前面**（其余条目逐字不动）。

    返回: bool  是否真的写入（已是最前一条且无重复时返回 False，幂等）

    走 _read_windows_user_path 拿到的条目是**未展开原文**，正好满足 R-保真；
    用「整条删除 + 整条插入到最前」而不是"直接 append"：用户级 PATH 内部也有顺序，
    追加到末尾时同组件更早的那条仍会先命中（本机 Maven 切换踩过）。
    """
    raw, type_name, _hive = read_user_env_raw("Path")
    old = raw or ""
    new = edit_path_raw(old, [entry], entry)
    if new == old:
        return False
    write_user_env_raw("Path", new, type_name or "REG_EXPAND_SZ")
    return True


def drop_user_path_entry(entry: str) -> bool:
    """从 HKCU Path 里整条摘掉 entry（原文保真）；返回是否真的改动。"""
    raw, type_name, _hive = read_user_env_raw("Path")
    old = raw or ""
    new = edit_path_raw(old, [entry])
    if new == old:
        return False
    write_user_env_raw("Path", new, type_name or "REG_EXPAND_SZ")
    return True


# --- HKLM 侧的原文保真写（提权助手用）----------------------------------------

def write_machine_env_raw(name: str, value: str, type_name: str) -> None:
    """写 HKLM 系统环境变量，保持调用方指定的类型（R-保真）。"""
    import winreg  # type: ignore

    type_id = winreg.REG_EXPAND_SZ if type_name == "REG_EXPAND_SZ" else winreg.REG_SZ
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
        winreg.SetValueEx(key, name, 0, type_id, value)


def delete_machine_env_raw(name: str) -> None:
    """删除 HKLM 系统环境变量某个值（不存在则幂等）。"""
    import winreg  # type: ignore

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


class MachineRegistryBackend:
    """提权助手读写 HKLM 的接缝。

    真实实现就是上面两个函数；测试把它换成内存字典，就能离线覆盖最危险的三条规则
    ——R-保真、R-关键条目校验、失败回滚（§8 第 7、8、10 条），完全不需要弹 UAC。
    """

    def read(self, name: str) -> Tuple[Optional[str], str]:
        return read_machine_env_raw(name)

    def write(self, name: str, value: str, type_name: str) -> None:
        write_machine_env_raw(name, value, type_name)

    def delete(self, name: str) -> None:
        delete_machine_env_raw(name)


def _machine_restore(before: Dict[str, dict], backend) -> List[str]:
    """按快照把 HKLM 键写回原文；返回"没还原成功"的明细（空 = 干净）。

    每条独立 try：一步失败不能拖累其余步 —— 留下"半回滚"至少比异常炸穿、
    后面几条完全没机会执行要好；明细交给调用方显示。
    """
    problems: List[str] = []
    for name, item in (before or {}).items():
        try:
            if item.get("existed") and isinstance(item.get("raw"), str):
                backend.write(name, item["raw"], str(item.get("type") or "REG_SZ"))
            else:
                backend.delete(name)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name} 没能还原：{exc}")
    return problems


def helper_verify_hit(path_value: str, exec_names: List[str],
                      verify_dir: str) -> Tuple[str, Optional[str]]:
    """复验：按 PATH 顺序第一个含该命令的目录，是不是我们期望的那个。

    返回: ("ok", None) | ("shadowed", 抢走命令的目录) | ("unknown", None)
    """
    names = [n for n in (exec_names or []) if n]
    if not names:
        return "unknown", None
    for entry in str(path_value or "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        try:
            if any(os.path.exists(os.path.join(entry, n)) for n in names):
                if EnvManager._same_path(entry, verify_dir):
                    return "ok", None
                return "shadowed", entry
        except (OSError, ValueError):
            continue
    return "unknown", None


# --- 助手侧核心：一次"接管"写 --------------------------------------------------

def elevate_helper_apply(request: Dict[str, object], backend) -> Dict[str, object]:
    """执行一次接管写。落盘顺序与硬规则（§5.4）：

      R-保真 → R-最小编辑 → （落盘前先自检一次，不合格就一个字都不写）
      → R-先备份 → 写 env_var / 写 Path（后者失败回滚前者，R-原子性）
      → 重读原文逐条核对（R-关键条目校验，不合格立即回滚）→ 自己复验一次（R-复验）

    入参 backend  读写 HKLM 的接缝（真实实现 MachineRegistryBackend）
    返回 dict {ok, stage, error, before, after, verdict}
      stage ∈ read|write|verify|rollback|done
    """
    env_var = str(request.get("env_var") or "")
    home = str(request.get("home") or "")
    remove_entries = [str(x) for x in (request.get("remove_entries") or [])]
    add_entry = str(request.get("add_entry") or "")
    verify_dir = str(request.get("verify_dir") or add_entry)
    exec_names = [str(x) for x in (request.get("exec_names") or [])]
    names = [n for n in (env_var, "Path") if n]

    result: Dict[str, object] = {"ok": False, "stage": "read", "error": "",
                                 "before": {}, "after": {}, "verdict": "unknown"}

    # ① 读原文（未展开，含类型）
    before: Dict[str, dict] = {}
    try:
        for name in names:
            raw, type_name = backend.read(name)
            before[name] = {"raw": raw, "type": type_name, "existed": raw is not None}
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"读系统变量失败，未做任何改动：{exc}"
        return result
    result["before"] = before

    # ② 算出新原文并在**落盘前**自检：与其写完再回滚，不如发现不对劲就不写
    path_before = before.get("Path", {}).get("raw") or ""
    new_path = edit_path_raw(str(path_before), remove_entries, add_entry)
    problems = validate_path_raw(str(path_before), new_path, remove_entries, add_entry)
    if problems:
        result["stage"] = "verify"
        result["error"] = "改前自检未通过，未写入任何内容：" + "；".join(problems)
        return result

    # ③ R-先备份：写入前把原文快照落一份独立文件
    backup_file = str(request.get("backup_file") or "")
    if backup_file:
        try:
            ensure_dir(Path(backup_file).parent)
            Path(backup_file).write_text(
                json.dumps(before, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            result["error"] = f"备份文件写不出去，已放弃（系统变量未被改动）：{exc}"
            return result

    # ④ 落盘（原子性：第二步失败要把第一步回滚掉）
    try:
        result["stage"] = "write"
        if env_var and home:
            var_before = before.get(env_var) or {}
            # 原来是什么类型就写什么类型；原来没有这个变量 → REG_SZ（值是绝对路径）
            if var_before.get("existed"):
                var_type = str(var_before.get("type") or "REG_SZ")
            else:
                var_type = "REG_SZ"
            backend.write(env_var, home, var_type)
        path_before_info = before.get("Path") or {}
        # 系统 Path 恒存在且恒为 REG_EXPAND_SZ；取不到类型时按 REG_EXPAND_SZ 写，
        # 因为写 REG_SZ 会把原值里的 %SystemRoot% 之类固化成死路径（R-保真）。
        path_type = str(path_before_info.get("type") or "REG_EXPAND_SZ")
        backend.write("Path", new_path, path_type)
    except Exception as exc:  # noqa: BLE001
        rollback = _machine_restore(before, backend)
        result["stage"] = "rollback"
        result["error"] = f"写入系统变量失败：{exc}"
        if rollback:
            result["error"] += "；回滚未完全成功，请手动检查：" + "；".join(rollback)
        return result

    # ⑤ R-关键条目校验：重读原文逐条核对（不信自己刚落盘的返回值）
    problems: List[str] = []
    after: Dict[str, dict] = {}
    try:
        for name in names:
            raw, type_name = backend.read(name)
            after[name] = {"raw": raw, "type": type_name, "existed": raw is not None}
        problems += validate_path_raw(str(path_before),
                                      str(after.get("Path", {}).get("raw") or ""),
                                      remove_entries, add_entry)
        if env_var and home:
            got = str(after.get(env_var, {}).get("raw") or "")
            if got != home:
                problems.append(f"{env_var} 写回去的值不是 {home}（实际 {got or '未设置'}）")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"写完复核时读不回来：{exc}")
    result["after"] = after

    if problems:
        rollback = _machine_restore(before, backend)
        result["stage"] = "rollback"
        result["error"] = ("写入后自检未通过，已" + ("回滚" if not rollback else "尝试回滚")
                           + "：" + "；".join(problems))
        if rollback:
            result["error"] += "；回滚未完全成功，请手动检查：" + "；".join(rollback)
        return result

    # ⑥ R-复验：助手自己跑一次合成环境判断命中谁（主程序还会独立复验一次）
    try:
        composed = EnvManager.composed_env()
        result["verdict"] = helper_verify_hit(composed.get("PATH") or "",
                                              exec_names, verify_dir)[0]
    except Exception:  # noqa: BLE001
        result["verdict"] = "unknown"

    result["ok"] = True
    result["stage"] = "done"
    return result


def elevate_helper_restore(request: Dict[str, object], backend) -> Dict[str, object]:
    """助手侧「还原」：把 HKLM 的键按快照写回原文（existed=false ⇒ 删除）。"""
    spec = request.get("restore") or {}
    result: Dict[str, object] = {"ok": False, "stage": "read", "error": "",
                                 "before": {}, "after": {}}
    if not isinstance(spec, dict) or not spec:
        result["error"] = "还原请求里没有可用的快照，未做任何改动"
        return result

    try:
        for name in spec:
            raw, type_name = backend.read(name)
            result["before"][name] = {"raw": raw, "type": type_name,
                                      "existed": raw is not None}
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"读系统变量失败，未做任何改动：{exc}"
        return result

    problems: List[str] = []
    try:
        result["stage"] = "write"
        for name, item in spec.items():
            if not isinstance(item, dict):
                problems.append(f"{name} 的快照形状不合法，已跳过")
                continue
            raw = item.get("raw")
            if item.get("existed") and isinstance(raw, str):
                backend.write(name, raw, str(item.get("type") or "REG_SZ"))
            else:
                backend.delete(name)
    except Exception as exc:  # noqa: BLE001
        result["stage"] = "rollback"
        result["error"] = f"还原时写入失败：{exc}"
        if problems:
            result["error"] += "；" + "；".join(problems)
        return result

    # 还原后的校验：原来含 system32 / \Windows 的关键条目必须还在
    try:
        for name in spec:
            raw, type_name = backend.read(name)
            result["after"][name] = {"raw": raw, "type": type_name,
                                     "existed": raw is not None}
        want = str((spec.get("Path") or {}).get("raw") or "")
        got = str((result["after"].get("Path") or {}).get("raw") or "")
        if want and got != want:
            problems.append("Path 没能逐字还原")
        low_want, low_got = want.lower(), got.lower()
        for needle in _MACHINE_KEY_SUBSTRINGS:
            if needle in low_want and needle not in low_got:
                problems.append(f"关键条目丢失：含 {needle!r} 的那一条不见了")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"还原后复核失败：{exc}")

    if problems:
        result["stage"] = "verify"
        result["error"] = "还原后自检未通过：" + "；".join(problems)
        return result

    result["ok"] = True
    result["stage"] = "done"
    return result


def elevate_helper_main(request_path: str) -> int:
    """提权助手入口：`<自身> --bt-elevate <请求文件>`。一次性进程，用完即退。

    绝不抛异常 —— 它是被 ShellExecuteW 拉起的、没有控制台可看，唯一能把
    "为什么没成"带给主程序的通道就是结果文件。所以顶层全兜住。
    """
    req_file = Path(request_path)
    result: Dict[str, object] = {"ok": False, "stage": "read", "error": ""}
    result_file: Optional[Path] = None
    try:
        request = json.loads(req_file.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise ValueError("请求文件不是 JSON 对象")
        rf = request.get("result_file")
        result_file = Path(str(rf)) if rf else None
        mode = str(request.get("mode") or "apply")
        backend = MachineRegistryBackend()
        if mode == "restore":
            result = elevate_helper_restore(request, backend)
        else:
            result = elevate_helper_apply(request, backend)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "stage": "read",
                  "error": f"助手内部错误：{exc}"}
    finally:
        if result_file is not None:
            try:
                result_file.write_text(
                    json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        _remove_quietly(req_file)
    return 0 if result.get("ok") else 1


# --- 主程序侧：提权助手调用点（可替换的进程边界）--------------------------------

def _elevate_file_pair() -> Tuple[Path, Path]:
    """生成一对临时文件名（请求 / 结果），放系统临时目录、带 pid 与随机后缀。"""
    import tempfile

    stem = f"bt-elevate-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    base = Path(tempfile.gettempdir()) / stem
    return base.with_name(stem + ".req.json"), base.with_name(stem + ".res.json")


def _run_elevated_helper(request: Dict[str, object],
                         timeout: float = ELEVATE_TIMEOUT_SEC) -> Dict[str, object]:
    """用 ShellExecuteW("runas") 拉起一次性助手，有界等待它回报。

    入参 request: dict  见 §5.4 请求协议；本函数会自动补 result_file
    入参 timeout: float 有界等待秒数（默认 90）
    返回: dict  {ok, stage, error, ...}
        stage="ok"        助手回报成功
        stage="denied"    助手回报失败（含它自己的回滚结果）
        stage="cancelled" 用户在 UAC 上点了"否"（ShellExecuteW 返回 1223）
        stage="launch"    连助手都没起来（返回值 ≤32），或写不出请求文件
        stage="timeout"   等到点也没见到结果文件

    ⚠ **timeout 不等于失败**：助手可能已经写了注册表却没来得及回报。调用方必须
    自己重读两 hive 原文判定实际状态，绝不允许凭超时直接下结论（§5.4 明写）。

    这是**可替换的进程边界**（与既有 _read_windows_user_env 同构），不是功能开关：
    测试把本模块的 _run_elevated_helper 换成假助手，即可离线覆盖全部分支（§8）。
    """
    if CURRENT_OS != "Windows":
        return {"ok": False, "stage": "launch", "error": "提权接管仅支持 Windows"}

    import ctypes

    req_path, res_path = _elevate_file_pair()
    payload = dict(request)
    payload["result_file"] = str(res_path)
    try:
        req_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "stage": "launch", "error": f"请求文件写不出去：{exc}"}

    # 两条路都要能跑：打包后 sys.executable 就是 ByteTools.exe（--bt-elevate 直接生效）；
    # 源码运行时 sys.executable 是 python，要把 main.py 自己作为脚本参数传进去。
    if getattr(sys, "frozen", False):
        params = subprocess.list2cmdline([ELEVATE_FLAG, str(req_path)])
    else:
        params = subprocess.list2cmdline(
            [str(Path(__file__).resolve()), ELEVATE_FLAG, str(req_path)])
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(sys.executable), params, str(Path.cwd()), 1)
    except Exception as exc:  # noqa: BLE001
        _remove_quietly(req_path, res_path)
        return {"ok": False, "stage": "launch", "error": f"无法请求管理员权限：{exc}"}

    code = int(ret or 0)
    if code == 1223:                       # ERROR_CANCELLED
        _remove_quietly(req_path, res_path)
        return {"ok": False, "stage": "cancelled",
                "error": "用户取消了管理员权限请求，未做任何改动"}
    if code <= 32:                          # ShellExecuteW 的失败返回值上限
        _remove_quietly(req_path, res_path)
        return {"ok": False, "stage": "launch",
                "error": f"没能启动提权助手（ShellExecuteW 返回 {code}）"}

    deadline = time.monotonic() + max(1.0, float(timeout))
    while time.monotonic() < deadline:
        if res_path.exists():
            try:
                data = json.loads(res_path.read_text(encoding="utf-8"))
            except Exception:               # noqa: BLE001
                data = None                 # 助手正写到一半，下一轮再读
            if isinstance(data, dict):
                _remove_quietly(req_path, res_path)
                data.setdefault("stage", "ok" if data.get("ok") else "denied")
                return data
        time.sleep(0.25)

    # 超时：**不删文件** —— 助手可能还在跑，删了它就没法回报。调用方先重读注册表
    # 判定实际状态，再决定是补写快照还是补回滚；这对文件交给系统临时目录回收。
    return {"ok": False, "stage": "timeout",
            "error": f"等待提权助手超过 {int(timeout)} 秒仍未收到结果"}


# --- §5.3 用户级接管 ----------------------------------------------------------

def apply_external_version_user(comp: Component, dv: "DiscoveredVersion",
                                log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """§5.3 用户级接管：不弹 UAC 的那一步，能成就不提权。

    返回: dict {ok, verdict, shadow, steps, snapshot, added}
      ok       bool   用户级这一步是否已让命令行命中目标目录
      verdict  str    "ok" | "shadowed" | "unknown" | "failed"
      shadow   str    被哪个目录压住（仅 verdict="shadowed" 时有值）
      steps    List[str]  中文步骤说明，界面逐行打日志
      snapshot dict  接管前的 HKCU 原文快照（还原的唯一依据）
      added    List[str]  我们插进 HKCU Path 的条目（还原时要摘掉）
    """
    def _log(level: str, text: str) -> None:
        if log:
            log(text)

    home = Path(dv.home)
    bin_dir = _external_bin_dir(comp, home)
    names = [n for n in (comp.env_var or "", "Path") if n]
    snapshot = snapshot_user_keys(names)
    steps: List[str] = []
    added: List[str] = []
    result: Dict[str, object] = {"ok": False, "verdict": "failed", "shadow": None,
                                 "steps": steps, "snapshot": snapshot, "added": added}

    try:
        if comp.env_var:
            write_user_env_raw(comp.env_var, str(home))
            steps.append(f"已把 {comp.env_var} 设为 {home}（用户级）")
    except Exception as exc:  # noqa: BLE001
        steps.append(f"写用户环境变量失败：{exc}")
        _log("error", steps[-1])
        return result

    verdict, shadow = path_effective_check(comp, bin_dir)
    if verdict == "shadowed":
        # 用户级 PATH 内部也有先后：把目标目录挪到用户段最前，再复验一次。
        try:
            if prepend_user_path_entry(bin_dir):
                added.append(bin_dir)
                steps.append(f"已把 {bin_dir} 提到用户 PATH 最前")
                verdict, shadow = path_effective_check(comp, bin_dir)
        except Exception as exc:  # noqa: BLE001
            steps.append(f"调整用户 PATH 顺序失败：{exc}")
            _log("error", steps[-1])

    if verdict == "ok":
        steps.append("复验通过：新开的终端会用到这个版本（用户级）")
        _log("ok", steps[-1])
    elif verdict == "shadowed":
        steps.append(f"用户级已改，命令行仍被更靠前的目录压住：{shadow}")
        _log("warn", steps[-1])
    else:
        steps.append("未能复验（拿不到系统合成的环境变量或 PATH 里找不到该命令），"
                     "请重开终端确认")
        _log("warn", steps[-1])

    result["ok"] = verdict == "ok"
    result["verdict"] = verdict
    result["shadow"] = shadow
    return result


# --- §5.4 提权接管 HKLM -------------------------------------------------------

def build_machine_request(comp: Component, dv: "DiscoveredVersion",
                          backup_file: str = "",
                          restore: Optional[Dict[str, dict]] = None,
                          mode: str = "apply") -> Dict[str, object]:
    """组装一次提权请求（也用于确认框里逐条列出"要改什么"）。

    默认只做**整条插入**（把目标 bin 目录插到系统 Path 最前），不删任何原有条目 ——
    这是 R-最小编辑下改动面最小的做法：插到最前就足以让命令行命中目标，
    顺带避开"删了用户自己的目录导致他别的工具坏掉"这类不可逆伤害。
    """
    home = Path(dv.home)
    bin_dir = _external_bin_dir(comp, home)
    return {
        "mode": mode,
        "env_var": comp.env_var or "",
        "home": str(home),
        # 默认只做整条插入、不删任何原有条目（R-最小编辑下改动面最小）；
        # 插到最前就足以让命令行命中目标，顺带避开"删了用户自己的目录、
        # 把他别的工具也搞坏"这类不可逆伤害。
        "remove_entries": [],
        "add_entry": bin_dir,
        "verify_dir": bin_dir,
        "exec_names": _exec_name_variants(comp),
        "backup_file": backup_file,
        "restore": restore or {},
    }


def _announce_env_change() -> None:
    """改完**系统级**（HKLM）环境变量后通知外壳。

    为什么用户级不用管、系统级必须单独喊一声：用户级的写入口
    （`write_user_env_raw`）自己就带广播；系统级是提权助手子进程写的，主进程这边
    一声不出，explorer 记的那份环境块就还是旧的，而 Windows 是**把环境块复制给
    每个新进程**的——于是他"切换之后新开的 cmd"依旧命中旧版本（本机 Maven 3.9.2
    vs 3.10.0 踩过：注册表已经对，软件内「开验证终端」也对，用户自己的 cmd 还是旧的）。
    通知失败不影响已写好的注册表，所以这里只静默尝试。
    """
    try:
        EnvManager._broadcast_env_change()
    except Exception:  # noqa: BLE001
        pass


def apply_external_version_machine(comp: Component, dv: "DiscoveredVersion",
                                   user_snapshot: Optional[Dict[str, dict]] = None,
                                   user_added: Optional[List[str]] = None,
                                   log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """§5.4 提权接管：改 HKLM，让命令行真的命中这个外部版本。

    入参 user_snapshot / user_added: §5.3 那一步的 HKCU 快照与新增条目（并入接管登记，
          还原时一并写回，避免只还原一半）。
    返回: dict {ok, verdict, steps, error, cancelled}

    主程序侧的兜底逻辑（§5.4 明文要求）：
      · 用户取消 UAC（1223）→ 零改动、零快照，如实报"已取消"。
      · 助手回报失败 → 自己重读两 hive 原文判定实际状态，绝不信助手的一面之词。
      · 超时 → **不等于失败**：重读注册表，若目标已生效则按成功补写快照，
        否则按失败处理（必要时再发一次还原请求）。
      · 写完复验不通过 → 自动还原 + 明确说明原因，**不报成功**。
    """
    def _log(level: str, text: str) -> None:
        if log:
            log(text)

    steps: List[str] = []
    result: Dict[str, object] = {"ok": False, "verdict": "failed", "error": "",
                                 "cancelled": False, "steps": steps,
                                 "entry": None}

    home = Path(dv.home)
    bin_dir = _external_bin_dir(comp, home)
    names = [n for n in (comp.env_var or "", "Path") if n]
    machine_before = snapshot_machine_keys(names)

    stamp = time.strftime("%Y%m%dT%H%M%S")
    backup_rel = f"takeover-backups/{comp.key}-{stamp}.json"
    backup_abs = str(CONFIG_DIR / backup_rel)

    request = build_machine_request(comp, dv, backup_file=backup_abs)
    steps.append(f"需要管理员权限：把 {bin_dir} 插入系统 PATH 最前"
                 + (f"、把 {comp.env_var} 设为 {home}" if comp.env_var else ""))
    _log("info", "正在请求管理员权限……")
    outcome = _run_elevated_helper(request)
    stage = str(outcome.get("stage") or "")

    if stage == "cancelled":
        result["cancelled"] = True
        result["verdict"] = "cancelled"
        result["error"] = str(outcome.get("error") or "已取消")
        steps.append("已取消管理员权限请求，未做任何改动")
        _log("warn", steps[-1])
        return result

    # 无论助手怎么说，都用**自己读到的注册表真值**复核一遍
    current_path, _pt = read_machine_env_raw("Path")
    current_var, _vt = read_machine_env_raw(comp.env_var) if comp.env_var else (None, "")
    applied = (bin_dir in str(current_path or "").split(";")
               or any(EnvManager._same_path(p, bin_dir)
                      for p in str(current_path or "").split(";") if p.strip()))
    if comp.env_var:
        applied = applied and str(current_var or "") == str(home)

    if not outcome.get("ok") and not applied:
        result["verdict"] = "failed"
        result["error"] = str(outcome.get("error") or f"提权助手未成功（{stage}）")
        steps.append(f"切换失败：{result['error']}")
        _log("error", steps[-1])
        if stage == "timeout":
            steps.append("提示：助手可能仍在运行，已重读系统变量确认过——目前没有生效")
            _log("warn", steps[-1])
        return result

    # 到这里写盘已生效（助手回报成功，或超时但注册表确实变了）
    verdict, shadow = path_effective_check(comp, bin_dir)
    if verdict != "ok":
        reason = (f"命令行仍会先命中 {shadow}" if verdict == "shadowed"
                  else "拿不到系统合成的环境变量，无法确认是否生效")
        steps.append(f"系统变量已改，但复验未通过（{reason}），正在还原…")
        _log("warn", steps[-1])
        revert = revert_machine_only(comp, machine_before, log=log)
        if revert.get("ok"):
            steps.append("已按改动前的原文还原，系统 PATH 未被改动")
        else:
            steps.append("还原未完全成功，请手动检查系统环境变量："
                         + str(revert.get("error") or ""))
        result["verdict"] = "failed"
        result["error"] = f"复验未通过（{reason}）"
        _log("error", steps[-1])
        return result

    entry = {
        "home": str(home),
        "version": dv.version,
        "level": "machine",
        "snapshot": {"HKCU": dict(user_snapshot or {}), "HKLM": machine_before},
        "added": {"HKCU": list(user_added or []), "HKLM": [bin_dir]},
        "backup_file": backup_rel,
    }
    save_takeover_entry(comp.key, entry)
    result["ok"] = True
    result["verdict"] = "ok"
    result["entry"] = entry
    _announce_env_change()
    steps.append("复验通过：新开的终端会用到这个版本（系统级）")
    _log("ok", steps[-1])
    return result


def revert_machine_only(comp: Component, machine_before: Dict[str, dict],
                        log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """只把 HKLM 写回指定快照（自动还原用；不碰 takeover 登记表）。"""
    def _log(level: str, text: str) -> None:
        if log:
            log(text)

    outcome = _run_elevated_helper({"mode": "restore", "restore": machine_before})
    if outcome.get("ok"):
        # 还原同样是系统级改动：不喊一声的话，"还原之后新开的终端"还会命中
        # 被还原掉的那个版本（和切换方向犯的是同一个错）。
        _announce_env_change()
        return {"ok": True, "error": ""}
    # 助手失败/超时也要自己复核：也许它其实已经改回去了
    problems: List[str] = []
    for name, item in (machine_before or {}).items():
        raw, _t = read_machine_env_raw(name)
        if item.get("existed"):
            if raw != item.get("raw"):
                problems.append(f"{name} 与改动前不一致")
        elif raw is not None:
            problems.append(f"{name} 应当不存在，实际还在")
    if not problems:
        return {"ok": True, "error": ""}
    detail = str(outcome.get("error") or "")
    _log("error", "还原系统变量未完成：" + "；".join(problems)
         + (f"（{detail}）" if detail else ""))
    return {"ok": False, "error": "；".join(problems) + (f"（{detail}）" if detail else "")}


# --- R3.19 让**工作区版本**在系统级也生效 ---------------------------------------

def verify_bin_dir(comp: Component, home: Path) -> Tuple[bool, str]:
    """装完之后核对：**我们准备放进 PATH 的那个目录里，到底有没有可执行文件**。

    为什么必须有这一步（Python 踩出来的坑，见 R3.22）：Windows 的 Python 是 embeddable 包，
    python.exe 在**安装根目录**而不是 `Scripts`；`path_subdir` 一错，PATH 就指向一个没有
    解释器的目录，于是「切换生效版本」永远是假话 —— 连 R3.19 提权插到系统 PATH 最前都救不回来
    （复验必然命中机器上原有的那个，然后自动回滚）。而这种错在界面上只表现为"切了但没生效"，
    用户根本无从自查。所以装完立刻核对一次，不对就在日志里点名说清实际在哪个目录。

    返回: (是否就在我们说的那个目录, 实际找到的位置；找不到时为空串)
    """
    names = _exec_name_variants(comp)
    if not names:
        return True, ""
    bin_dir = Path(_external_bin_dir(comp, home))
    for n in names:
        if (bin_dir / n).exists():
            return True, str(bin_dir / n)
    # 不在我们说的那个目录 → 换几个常见布局找一遍，好在日志里说出"实际在哪"
    for sub in ("", "bin", "Scripts", "cmd", "sbin", "condabin"):
        d = home / sub if sub else home
        for n in names:
            if (d / n).exists():
                return False, str(d / n)
    return False, ""


def build_workspace_machine_request(comp: Component, version: str,
                                    backup_file: str = "",
                                    restore: Optional[Dict[str, dict]] = None,
                                    mode: str = "apply") -> Dict[str, object]:
    """组装"让**工作区版本**在系统级也生效"的提权请求（R3.19）。

    与 build_machine_request（外部接管）唯一的**结构**区别是 home 的来源：这里是本工具
    工作区里的 <CONFIG_DIR>/<key>/<key>-<version>，不是用户在别处装的那一份。
    改动内容与硬规则完全一致：只在系统 Path 最前**插入**自己那条，原有条目一条不删
    —— 用户自己装的 3.9.2 仍留在系统变量里，只是排到了后面，随时可按原文还原。
    """
    home = comp.install_dir(version)
    bin_dir = _external_bin_dir(comp, home)
    return {
        "mode": mode,
        "env_var": comp.env_var or "",
        "home": str(home),
        "remove_entries": [],
        "add_entry": bin_dir,
        "verify_dir": bin_dir,
        "exec_names": _exec_name_variants(comp),
        "backup_file": backup_file,
        "restore": restore or {},
    }


def apply_workspace_machine(comp: Component, version: str,
                            confirm_machine: Optional[Callable[[dict], bool]] = None,
                            log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """工作区版本被**系统级**条目压住时，提权把它的 bin 目录插到系统 Path 最前。

    返回: dict {ok, verdict, level, error, cancelled, steps}

    与 apply_external_version_machine 共用同一套助手协议与五条硬规则，差别只在登记：
    这个版本本来就是工作区版本，active[key] 仍然有效（两条键不互斥），所以不写
    takeover，改记 machine_fix，供「↩ 还原到我之前的设置」按原文写回。
    """
    def _log(level: str, text: str) -> None:
        if log:
            log(text)

    steps: List[str] = []
    result: Dict[str, object] = {"ok": False, "verdict": "failed", "error": "",
                                 "cancelled": False, "level": "", "steps": steps}

    home = comp.install_dir(version)
    bin_dir = _external_bin_dir(comp, home)
    names = [n for n in (comp.env_var or "", "Path") if n]
    machine_before = snapshot_machine_keys(names)

    stamp = time.strftime("%Y%m%dT%H%M%S")
    backup_rel = f"takeover-backups/{comp.key}-{stamp}.json"
    request = build_workspace_machine_request(
        comp, version, backup_file=str(CONFIG_DIR / backup_rel))

    # 提权前的确认框：改的是整机所有程序看到的环境，必须用户点了确定才动
    if confirm_machine is None or not confirm_machine(request):
        steps.append("已取消：未修改任何系统变量")
        _log("warn", steps[-1])
        result["verdict"] = "cancelled"
        result["error"] = "用户未同意修改系统变量"
        return result

    steps.append(f"需要管理员权限：把 {bin_dir} 插入系统 PATH 最前"
                 + (f"、把 {comp.env_var} 设为 {home}" if comp.env_var else ""))
    _log("info", "正在请求管理员权限……")
    outcome = _run_elevated_helper(request)
    stage = str(outcome.get("stage") or "")

    if stage == "cancelled":
        result["cancelled"] = True
        result["verdict"] = "cancelled"
        result["error"] = str(outcome.get("error") or "已取消")
        steps.append("已取消管理员权限请求，未做任何改动")
        _log("warn", steps[-1])
        return result

    # 无论助手怎么说，都用**自己读到的注册表真值**复核一遍（与外部接管同一条纪律）
    current_path, _pt = read_machine_env_raw("Path")
    current_var, _vt = read_machine_env_raw(comp.env_var) if comp.env_var else (None, "")
    applied = any(EnvManager._same_path(p, bin_dir)
                  for p in str(current_path or "").split(";") if p.strip())
    if comp.env_var:
        applied = applied and str(current_var or "") == str(home)

    if not outcome.get("ok") and not applied:
        result["error"] = str(outcome.get("error") or f"提权助手未成功（{stage}）")
        steps.append(f"未能改到系统变量：{result['error']}")
        _log("error", steps[-1])
        if stage == "timeout":
            steps.append("提示：助手可能仍在运行，已重读系统变量确认过——目前没有生效")
            _log("warn", steps[-1])
        return result

    verdict, shadow = path_effective_check(comp, bin_dir)
    if verdict != "ok":
        reason = (f"命令行仍会先命中 {shadow}" if verdict == "shadowed"
                  else "拿不到系统合成的环境变量，无法确认是否生效")
        steps.append(f"系统变量已改，但复验未通过（{reason}），正在还原…")
        _log("warn", steps[-1])
        revert = revert_machine_only(comp, machine_before, log=log)
        steps.append("已按改动前的原文还原，系统 PATH 未被改动" if revert.get("ok")
                     else "还原未完全成功，请手动检查系统环境变量："
                          + str(revert.get("error") or ""))
        _log("info" if revert.get("ok") else "error", steps[-1])
        result["error"] = f"复验未通过（{reason}）"
        return result

    entry = {
        "home": str(home),
        "version": version,
        "level": "machine",
        "snapshot": {"HKLM": machine_before},
        "added": {"HKLM": [bin_dir]},
        "backup_file": backup_rel,
    }
    save_machine_fix_entry(comp.key, entry)
    result["ok"] = True
    result["verdict"] = "ok"
    result["level"] = "machine"
    _announce_env_change()
    steps.append(f"复验通过：新开的终端会用到 {bin_dir}（已插到系统 PATH 最前）")
    _log("ok", steps[-1])
    return result


def revert_machine_fix(comp: Component,
                       log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """把「为工作区版本而改的系统变量」按原文写回，并清掉登记（R3.19）。

    没登记过时是零成本的 no-op。
    """
    entry = load_machine_fix_map().get(comp.key)
    if not entry:
        return {"ok": True, "error": "", "steps": [], "cancelled": False}
    before = (entry.get("snapshot") or {}).get("HKLM") or {}
    steps = [f"按改动前的原文把系统变量写回（{entry.get('version')} 那次提权改动）……"]
    res = revert_machine_only(comp, before, log=log)
    if not res.get("ok"):
        steps.append("还原未完成：" + str(res.get("error") or ""))
        return {"ok": False, "error": str(res.get("error") or ""),
                "steps": steps, "cancelled": False}
    drop_machine_fix_entry(comp.key)
    steps.append("系统变量已按原文写回")
    return {"ok": True, "error": "", "steps": steps, "cancelled": False}


def release_machine_state(comp: Component,
                         log: Optional[Callable[[str], None]] = None,
                         reason: str = "切换版本") -> Dict[str, object]:
    """把两笔"动过系统环境"的账都还掉，顺序固定、任一失败即中止：

      1. 接管过的外部版本（§4.3 两条键互斥的另一半）；
      2. 为工作区版本提权改过的系统变量（R3.19）。

    **两个入口共用**，这是它必须是"公共前置步骤"而不是某条路径私有逻辑的原因：
      · 切回/切到工作区版本之前（`_apply_active`）；
      · **接管另一个外部版本之前**（`switch_to_external_version`）。
    不还原的话，系统 Path 最前还插着上一次改的目录，接下来无论做什么，复验都会命中那条旧目录 ——
    界面说成功、命令行却是旧版本，正是用户质疑过的那类假话。而且两笔账会互相覆盖快照：
    machine_fix 记的是"插入我们的 3.10.0 之前"的原文，若此时又叠一次接管，
    按 machine_fix 还原会把接管插的那条一起抹掉，注册表回不到任何一次改动前的状态。
    先还原再动，稳态里系统 Path 永远没有本工具留下的条目；新版本若仍被压住，会重新征求一次提权。
    没欠账时是零成本的 no-op。
    """
    steps: List[str] = []

    if load_takeover_map().get(comp.key):
        if log:
            log(f"检测到已接管过这个组件，先把系统变量还原到之前的设置再{reason}……")
        back = revert_external_version(comp, log=log)
        steps += list(back.get("steps") or [])
        if not back.get("ok"):
            return {"ok": False, "error": str(back.get("error") or ""), "steps": steps}

    if load_machine_fix_map().get(comp.key):
        if log:
            log(f"检测到为系统变量做过的提权改动，先按原文还原再{reason}……")
        fix = revert_machine_fix(comp, log=log)
        steps += list(fix.get("steps") or [])
        if not fix.get("ok"):
            return {"ok": False, "error": str(fix.get("error") or ""), "steps": steps}

    return {"ok": True, "error": "", "steps": steps}


# --- 还原 ---------------------------------------------------------------------

def revert_external_version(comp: Component,
                            log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """把接管过的外部版本**原样退回**（§5.4 末段）。

    读 takeover[key].snapshot，按 level 决定是否再弹一次 UAC；逐 hive 写回原文
    （existed=false ⇒ 删除该键），移除我们插过的 PATH 条目，广播，删登记表。
    用户追加的需求「装完别的版本还能切回本地那个」就是靠这条落地的。
    """
    def _log(level: str, text: str) -> None:
        if log:
            log(text)

    steps: List[str] = []
    result: Dict[str, object] = {"ok": False, "error": "", "cancelled": False,
                                 "steps": steps}
    entry = load_takeover_map().get(comp.key)
    if not entry:
        result["error"] = "没有登记在案的接管，无需还原"
        steps.append(result["error"])
        _log("warn", steps[-1])
        return result

    snapshot = entry.get("snapshot") or {}
    user_snap = snapshot.get("HKCU") or {}
    machine_snap = snapshot.get("HKLM") or {}
    added = entry.get("added") or {}
    level = str(entry.get("level") or "user")

    # ① HKLM 先还原：它需要提权，最可能出岔子，放在最前面处理
    if level == "machine" and machine_snap:
        outcome = _run_elevated_helper({"mode": "restore", "restore": machine_snap})
        if str(outcome.get("stage") or "") == "cancelled":
            result["cancelled"] = True
            result["error"] = "已取消管理员权限请求，环境变量未做改动"
            steps.append(result["error"])
            _log("warn", steps[-1])
            return result
        if not outcome.get("ok"):
            check = revert_machine_only(comp, machine_snap, log=log)
            if not check.get("ok"):
                result["error"] = ("还原系统变量失败：" + str(check.get("error") or "")
                                   + "；接管登记仍保留，可稍后重试")
                steps.append(result["error"])
                _log("error", steps[-1])
                return result
        steps.append("系统环境变量已按接管前的原文还原")
        _log("ok", steps[-1])
        _announce_env_change()

    # ② HKCU 还原：不需要提权
    try:
        for name, item in user_snap.items():
            if not isinstance(item, dict):
                continue
            raw = item.get("raw")
            if item.get("existed") and isinstance(raw, str):
                write_user_env_raw(name, raw, str(item.get("type") or ""))
            else:
                delete_user_env_raw(name)
        for extra in (added.get("HKCU") or []):
            drop_user_path_entry(str(extra))
        steps.append("用户环境变量已按接管前的原文还原")
        _log("ok", steps[-1])
    except Exception as exc:  # noqa: BLE001
        result["error"] = (f"还原用户环境变量失败：{exc}"
                           "；接管登记仍保留，可稍后重试")
        steps.append(result["error"])
        _log("error", steps[-1])
        return result

    try:
        EnvManager._broadcast_env_change()
    except Exception:
        pass
    drop_takeover_entry(comp.key)
    result["ok"] = True
    steps.append("已还原到我之前的设置")
    _log("ok", steps[-1])
    return result


# --- 编排：一次完整的「切到外部版本」------------------------------------------

def switch_to_external_version(comp: Component, dv: "DiscoveredVersion",
                               confirm_machine: Optional[Callable[[Dict[str, object]], bool]] = None,
                               log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """切到外部版本：用户级先行，被压住且用户同意才提权改 HKLM（§5.3 → §5.4）。

    入参 confirm_machine: 提权前的确认回调，入参是请求 dict（要改什么一目了然），
          返回 False 表示用户不同意。为 None 时**不提权**（只做用户级）——
          这样任何调用方都不会在没问过用户的情况下动系统变量。
    返回: dict {ok, verdict, level, error, steps}
    """
    def _log(level: str, text: str) -> None:
        if log:
            log(text)

    # 接管另一个外部版本之前，先把两笔账都还掉（已接管的、以及为工作区版本提权改过的）：
    # 不还的话系统 PATH 里会叠出第二条本工具的条目，两边快照互相覆盖，还原回不到原样。
    back = release_machine_state(comp, log=log, reason="接管这个版本")
    if not back.get("ok"):
        return {"ok": False, "verdict": "failed", "level": "",
                "error": "先还原上一次的系统变量改动失败：" + str(back.get("error") or ""),
                "steps": list(back.get("steps") or [])}

    user = apply_external_version_user(comp, dv, log=log)
    steps = list(user.get("steps") or [])
    verdict = str(user.get("verdict") or "failed")

    if user.get("ok"):
        entry = {
            "home": str(dv.home),
            "version": dv.version,
            "level": "user",
            "snapshot": {"HKCU": user.get("snapshot") or {}, "HKLM": {}},
            "added": {"HKCU": list(user.get("added") or []), "HKLM": []},
            "backup_file": "",
        }
        save_takeover_entry(comp.key, entry)
        return {"ok": True, "verdict": "ok", "level": "user", "error": "", "steps": steps}

    if verdict != "shadowed":
        # unknown / failed：不升级。拿不到复验结论不等于失败，为它弹 UAC 是无据升级。
        return {"ok": False, "verdict": verdict, "level": "user",
                "error": "用户级已改，但未能确认命令行是否真的切过去，请重开终端验证；"
                         "如需强制生效可在确认后用管理员权限改系统变量",
                "steps": steps}

    if confirm_machine is None:
        return {"ok": False, "verdict": "shadowed", "level": "user",
                "error": f"命令行仍被 {user.get('shadow')} 压住，需要管理员权限才能改系统变量",
                "steps": steps}

    plan = build_machine_request(comp, dv)
    if not confirm_machine(plan):
        steps.append("已取消：未修改任何系统变量")
        _log("warn", steps[-1])
        return {"ok": False, "verdict": "cancelled", "level": "user",
                "error": "用户未同意修改系统变量", "steps": steps}

    machine = apply_external_version_machine(
        comp, dv, user_snapshot=user.get("snapshot") or {},
        user_added=list(user.get("added") or []), log=log)
    steps += list(machine.get("steps") or [])
    return {"ok": bool(machine.get("ok")),
            "verdict": str(machine.get("verdict") or "failed"),
            "level": "machine" if machine.get("ok") else "user",
            "error": str(machine.get("error") or ""),
            "steps": steps}


def release_external_before_workspace_switch(comp: Component,
                                             log: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """切回工作区版本**之前**必须做的事：把接管过的外部版本还原掉。

    这是 §4.3「两条键互斥」的另一半：active 与 takeover 不允许并存，而 apply_active_version
    只会写自己的工作区条目、并不知道系统变量已被接管改过 —— 不先还原就会出现
    「登记表说工作区 21、系统 PATH 最前还插着外部 17」这种两边都不认的孤儿态，
    用户切完发现命令行还是旧版本，正是他最开始质疑的那类问题。
    没接管过时是零成本的 no-op。
    """
    if not load_takeover_map().get(comp.key):
        return {"ok": True, "error": "", "steps": []}
    if log:
        log(f"已接管过外部版本，先还原到之前的设置再切回工作区版本……")
    return revert_external_version(comp, log=log)


def load_active_map() -> Dict[str, str]:
    """读取"每个组件当前生效哪个版本"的登记表；文件缺失或损坏一律当空表。

    返回: Dict[str, str]  {组件 key: 生效版本号}

    说明: 值只接受非空字符串——磁盘上手改成 {"jdk": 21} 或 {"jdk": {...}} 时
          跳过该键（其余键照常返回，不整体抛），绝不把非字符串当版本号往下传。
    """
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    active = data.get("active") if isinstance(data, dict) else None
    if not isinstance(active, dict):
        return {}
    return {k: v for k, v in active.items()
            if isinstance(k, str) and isinstance(v, str) and v}


def save_active_version(comp_key: str, version: Optional[str]) -> None:
    """登记或清除某组件的生效版本。

    入参 comp_key: str           组件 key
    入参 version: Optional[str]  版本号；None 表示清除（已无生效版本）

    说明: 必须**合并写**——先读原文件，只改 active 里那一项。整体覆盖会把
          selections（下拉框选中版本）一起抹掉，用户下次启动选中的版本全丢。
          清除只认 None：空串不是"清除"而是脏值（写进登记表后会被读侧
          的非空字符串校验静默丢掉），显式 raise ValueError 报出来。
    """
    if version is not None and (not isinstance(version, str) or not version):
        raise ValueError(
            f"生效版本号必须是非空字符串或 None（None=清除），收到 {version!r}")
    data: Dict[str, object] = {}
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    active = data.get("active")
    if not isinstance(active, dict):
        active = {}
    if version is None:
        active.pop(comp_key, None)
    else:
        active[comp_key] = version
    data["active"] = active
    _atomic_write_config(data)


def infer_active_from_env(comp: Component) -> Optional[str]:
    """老配置没记 active 时，从持久层的 XXX_HOME 反推当前生效版本。

    返回: Optional[str]  版本号；反推不出（用户自己装的、指向别处、目录名不规范）时 None

    说明: 这一步是为了不把"已经在用系统里那个 JDK 的用户"显示成"一个都没生效"。
          推不出来就返回 None，界面写"均未生效"，不要乱猜。
          N-3：反推出来的版本目录必须真实存在——双写失败（目录删了、HOME 没清掉）
          或早年手工删目录后，HOME 只是死配置，不能让它把胶囊撑成"生效 X"。
    """
    if not comp.env_var:
        return None
    home = EnvManager.read_user_env(comp.env_var) or EnvManager.get(comp.env_var)
    if not home:
        return None
    path = Path(os.path.expandvars(str(home)))
    if not path.is_dir():
        # 存在性判据：HOME 指向的目录已不在磁盘上，反推出来的是幽灵版本
        return None
    if not EnvManager._under_root(str(path), str(CONFIG_DIR / comp.key)):
        return None
    return version_from_install_dir(comp, path)


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
    - **点击版本框内任何位置（含右侧箭头、内边距）都只负责"弹出"，不再做开/关切换**
      —— 2026-10-09 用户明确要求："只要是在那个版本框内发生的点击，都弹出版本列表"。
      切换本身也是偶发点不开的根源：原生 QComboBox 在箭头区域有自己的 toggle，
      与我们的记账容易失同步，表现就是"点了没反应、多点几次才好"。去掉切换后
      弹出这件事变成幂等的：按了就一定弹，没有任何状态可失同步。
      列表的收起交给 Qt 原生行为：选中某项、点到外面、按 Esc。
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

        # 过滤器装三处，缺一个就会漏掉一种点击位置：
        #   · lineEdit：文本区（覆盖大部分框面）
        #   · self：右侧箭头那 28px 与内边距（箭头 label 是鼠标穿透的，事件落到 combo 上）
        #   · view：看 Show/Hide 兜住 Qt 自己的收起路径
        # 只装在 lineEdit 上时，点箭头会走 QComboBox **原生的 toggle**，与这里的记账
        # 互相打架 —— 那就是"点了没反应、多点几次才好"的来源。
        self.lineEdit().installEventFilter(self)
        self.installEventFilter(self)

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

        # 展开状态**由控件自己记账**（R3.21）：绝不能去问 self.view().isVisible()。
        # 实测那个值不可靠——Qt 的 popup 容器与它内部的 view 可见性不同步，两个平台
        # 给出互相矛盾的结论：offscreen 里选中之后**卡在 True**（于是再点一次走的是
        # hidePopup 分支 → 用户看到"选中过之后再点就弹不出来"）；真实 windows 里
        # 明明展开着却报 False。展开与否只有 showPopup/hidePopup 这两个入口说了算。
        self._popup_open: bool = False

        # 光在 showPopup/hidePopup 里记账还不够：点到别处、窗口失焦、容器自己 hide 时，
        # Qt 不一定经过我们覆写的那两个入口，记账会失同步 —— 用户看到的就是"偶尔弹不出来、
        # 多点了几次又好了"。所以在 view 上再装一个事件过滤器，用 Show/Hide 兜住。
        self.view().installEventFilter(self)

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
        # ① view 自己的 Show/Hide：兜住 Qt 不经过我们覆写的那几条收起路径
        if obj is self.view():
            if event.type() == QEvent.Show:
                self._popup_open = True
            elif event.type() == QEvent.Hide:
                self._popup_open = False
            return False   # 不吞，照常交给 Qt

        # 版本框内**任何位置**的按下（文本区 / 箭头 / 内边距）一律弹出，不做开/关切换。
        if event.type() == QEvent.MouseButtonPress and \
                (obj is self or obj is self.lineEdit()):
            self.lineEdit().setFocus()
            if not self._popup_is_really_open():
                QTimer.singleShot(0, self._deferred_show_popup)
            return True  # 吞掉事件：不让 Qt 走它自己那套 toggle
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    def _deferred_show_popup(self) -> None:
        """singleShot(0) 到点后的展开入口；控件可能已被销毁，故静默兜住。

        为什么要绕这一个事件循环：在 MousePress 里当场 showPopup，主窗口很可能
        **还没被激活**（窗口系统的激活发生在 press 之后），native popup 会被紧接着的
        "窗口被激活"这一下立刻关掉 —— 现象就是偶尔点了没反应、多点几次才好。
        放到下一个事件循环，激活已完成，弹出就稳定了。
        """
        try:
            if not self._popup_is_really_open():
                self.showPopup()
        except RuntimeError:
            pass   # 卡片/窗口已经析构，没必要再弹

    # ------------------------------------------------------------------
    def _popup_is_really_open(self) -> bool:
        """记账说开着**且**容器确实可见，才算真的开着（偶发"点几次才弹出"的最后一道保险）。

        两个条件缺一不可：
          · 只信记账 → Qt 走别的路径收起时失同步，下一次点击变成"再收一次"，弹不出来；
          · 只信可见性 → 又碰到 R3.21 那个 view().isVisible() 报脏值的老问题。
        """
        if not self._popup_open:
            return False
        view = self.view()
        container = view.window() if view is not None else None
        return bool(view.isVisible()) or (container is not None and container.isVisible())

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
        # 记账放在 super() 之后：Qt 那一步真把 popup 建起来了，才算展开。
        # 放在之前会把"没弹成功"也记成展开，下一次点击就变成收起 —— 正是要修的那个现象。
        self._popup_open = True

    # ------------------------------------------------------------------
    def hidePopup(self) -> None:  # noqa: D401
        self._arrow_label.setText("▾")
        super().hidePopup()
        self._popup_open = False

    # ------------------------------------------------------------------
    def _on_text_edited(self, text: str) -> None:
        """用户在输入框中键入时：实时过滤 + 展开下拉。"""
        # 展开下拉（若尚未展开）；同样看 _popup_is_really_open()，不看 view().isVisible()
        if not self._popup_is_really_open():
            self.showPopup()
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
# UI 图标：版本下拉框的"磁盘上已装"标记
# ---------------------------------------------------------------------------
def _installed_icon(color: str = "#2e7d32", size: int = 16) -> QIcon:
    """现画一个绿色对勾，作为下拉框里"这个版本磁盘上已装"的标记。

    入参 color: str  线色，默认与状态胶囊的成功绿同系
          size:  int 逻辑边长（像素），按 2 倍分辨率绘制以免高分屏发虚
    返回: QIcon

    说明: 刻意用图标而不是在文本里加「✓」——下拉框的显示文本是版本反查的唯一键
          （_current_version / repopulate(preferred=…)），改文本会连锁打错选版、
          安装、卸载与配置保存。画法与 MainWindow._make_search_icon 保持一致。
    """
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(3, 9, 6, 12)      # 短撇
    painter.drawLine(6, 12, 13, 4)     # 长挑
    painter.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# 旧终端点名：切换之后，哪些还开着的窗口拿的是旧环境
# ---------------------------------------------------------------------------

# 不含 conhost.exe：一台机器上常年挂着几十个，全列出来等于没列
SHELL_PROCESS_NAMES = ("powershell.exe", "pwsh.exe", "cmd.exe",
                       "windowsterminal.exe", "wt.exe")


def list_shell_processes() -> List[Tuple[int, str, float, bool]]:
    """当前活着的终端类进程，返回 [(pid, 名字, 创建时间 epoch, 本进程能否打开它)]。

    拿不到就返回空表，调用方按"没测到"处理，不许据此断言"没有旧终端"。

    最后一项为 False 基本等于那个窗口是「以管理员身份运行」的：OpenProcess 直接
    error 5。这类窗口既拿不到我们的 WM_SETTINGCHANGE 广播（UIPI 挡在中间），
    环境块又是登录时那一份，只有整窗关掉重开才会更新。
    """
    if CURRENT_OS != "Windows":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class _PE(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]

        class _FT(ctypes.Structure):
            _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

        class _ST(ctypes.Structure):
            _fields_ = [(n, wintypes.WORD) for n in
                        ("wYear", "wMonth", "wDayOfWeek", "wDay",
                         "wHour", "wMinute", "wSecond", "wMilliseconds")]

        def _epoch(st: "_ST") -> float:
            return time.mktime((st.wYear, st.wMonth, st.wDay, st.wHour,
                                st.wMinute, st.wSecond, 0, 0, -1))

        snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
        if not snap or snap == -1:
            return []
        out: List[Tuple[int, str, float, bool]] = []
        try:
            entry = _PE()
            entry.dwSize = ctypes.sizeof(_PE)
            got = kernel32.Process32First(ctypes.c_void_p(snap), ctypes.byref(entry))
            while got:
                name = entry.szExeFile.decode("mbcs", "replace").lower()
                pid = int(entry.th32ProcessID)
                if name in SHELL_PROCESS_NAMES:
                    start = 0.0
                    h = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED
                    if h:
                        ft, zero = _FT(), _FT()
                        if kernel32.GetProcessTimes(h, ctypes.byref(ft), ctypes.byref(zero),
                                                    ctypes.byref(zero), ctypes.byref(zero)):
                            st, lst = _ST(), _ST()
                            kernel32.FileTimeToSystemTime(ctypes.byref(ft), ctypes.byref(st))
                            kernel32.SystemTimeToTzSpecificLocalTime(None, ctypes.byref(st),
                                                                     ctypes.byref(lst))
                            start = _epoch(lst)
                        kernel32.CloseHandle(h)
                    probe = kernel32.OpenProcess(0x0410, False, pid)  # VM_READ|QUERY_INFO
                    openable = bool(probe)
                    if probe:
                        kernel32.CloseHandle(probe)
                    out.append((pid, name, start, openable))
                got = kernel32.Process32Next(ctypes.c_void_p(snap), ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
        return out
    except Exception:
        return []


def stale_shell_lines(procs: List[Tuple[int, str, float, bool]],
                      since_epoch: float, self_pid: int,
                      limit: int = 6) -> List[str]:
    """把比 since_epoch 更早、还活着的终端进程写成可点名的日志行（纯函数，便于测）。"""
    old = [p for p in procs if p[0] != self_pid and p[2] and p[2] < since_epoch]
    if not old:
        return []
    old.sort(key=lambda p: p[2])
    lines = [f"另有 {len(old)} 个终端窗口比这次切换更早，它们揣的还是切换前那份环境"
             "（关掉标签页不算新终端，要关掉整个窗口）："]
    for pid, name, start, openable in old[:limit]:
        tail = ("" if openable
                else "  ← 管理员窗口：本工具的通知进不去，只能整窗关掉重开")
        lines.append(f"    {name}  pid={pid}  起于 "
                     f"{time.strftime('%H:%M:%S', time.localtime(start))}{tail}")
    if len(old) > limit:
        lines.append(f"    …另有 {len(old) - limit} 个更早的窗口未列出")
    return lines


def open_clean_console(env: Dict[str, str]) -> Optional[int]:
    """用给定的环境块开一个独立的 cmd 窗口，返回 pid；开不了返回 None。

    这是顶栏「开验证终端」唯一的副作用接缝，也是它唯一的测试接缝 ——
    参数名（env / creationflags）写错的话界面要点下去才炸，所以有一条用例专门钉它。
    """
    try:
        proc = subprocess.Popen(["cmd.exe"], env=env,
                                creationflags=subprocess.CREATE_NEW_CONSOLE)
        return proc.pid
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 卡片网格：列宽锚点与分块（纯函数，不碰几何，可离线测）
#
# 卡片原来是"一行一张占满宽"，640px 视口下只能露 3 个半。改成网格后列数只由
# 视口宽度决定：宽了自动 3 列，窄了退回 1 列。日志做成浮层就是为了不参与这场
# 计算——它不占布局空间，展开/收起都不会让列数忽大忽小。
# ---------------------------------------------------------------------------
MIN_CARD_WIDTH_PX = 300          # 格子最小宽度：一张卡片信息不砍的下限
CARD_ROW_SPACING = 14            # 同行两格的间距（与卡片区原 spacing 一致）

# 统一搜索结果面板在 `_tab_rows` 里的键；四个 Tab 用 0..N-1 的序号。
RESULTS_KEY = "results"

# 告警把日志浮层自动弹开后，静默多久自动收起（毫秒）。用户手动点开的不自动收。
LOG_AUTO_HIDE_MS = 8000


def grid_columns_for(available_px, min_card_px) -> int:
    """给定可用宽度与格子最小宽度，返回列数（恒 ≥ 1）。

    入参 available_px: int|None  卡片区视口去掉左右边距后的净宽
          min_card_px: int|None  单格最小宽度；取不到（None/0/负）时退化成 1 列

    说明: 视口宽度在窗口最小化、布局尚未生效时会是 0，除零或负列数会让整片
          卡片消失，所以所有非法入参一律兜底成 1 列而不是抛异常。
    """
    try:
        available = int(available_px)
        minimum = int(min_card_px)
    except (TypeError, ValueError):
        return 1
    if available <= 0 or minimum <= 0:
        return 1
    # n 列要占 n 个格子 + (n-1) 个间距，所以可用宽度先"补"一个间距再整除
    return max(1, (available + CARD_ROW_SPACING) // (minimum + CARD_ROW_SPACING))


def chunk_visible(cards, columns) -> list:
    """把卡片按 columns 列切成若干"行"，只排得进"没被隐藏"的卡片。

    入参 cards:   可迭代的卡片序列（顺序即界面顺序）
          columns: int 列数；<1 或非数字时按 1 列处理

    返回: List[List[card]]  除最后一行外每行都排满；没有可见卡片时返回 []

    说明: 判可见用 `isHidden()` 而不是 `isVisible()`——后者还要看父级是否可见，
          而卡片所在 Tab 页没被翻到时父级就是不可见的（实测：非当前页的卡片
          isVisible() 恒为 False）。用 isVisible() 会让"切到第二页"变成"整页
          卡片排不出来"。搜索隐藏走的正是 `setVisible(False)`，isHidden() 判得准。
    """
    try:
        cols = max(1, int(columns))
    except (TypeError, ValueError):
        cols = 1
    visible = [c for c in cards if not c.isHidden()]
    return [visible[i:i + cols] for i in range(0, len(visible), cols)]


# ---------------------------------------------------------------------------
# UI 组件：卡片
# ---------------------------------------------------------------------------
class CardColumnLayout(QVBoxLayout):
    """Tab 里装"行"的外层竖向布局。

    为什么不让裸 QVBoxLayout 直接干这事：改成行容器后，卡片的直接父级是行控件，
    而 QLayout.indexOf **不会**钻进子控件自己的布局里找（实测恒为 -1）。于是
    "这张卡片属于哪个 Tab"这类按 indexOf 判归属的既有代码会静默失效 ——
    `_reveal_running_tabs`（"有组件在跑就自动跳到那一页"）就是这么哑掉的。
    这里把 indexOf 补成"先查自己、再逐行查"，归属判断继续成立。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.row_widgets: list = []

    def indexOf(self, widget) -> int:  # noqa: N802  Qt 规定的驼峰签名
        idx = super().indexOf(widget)
        if idx != -1:
            return idx
        for n, row in enumerate(self.row_widgets):
            lay = row.layout() if row is not None else None
            if lay is not None and lay.indexOf(widget) != -1:
                return n
        return -1


class ComponentCard(QFrame):
    """展示一个组件的卡片。"""

    request_log = Signal(str, str)

    def __init__(self, component: Component, log_cb: Callable[[str, str], None], parent=None) -> None:
        super().__init__(parent)
        self.component = component
        self.log_cb = log_cb
        self.worker: Optional[DownloadWorker] = None
        self._extracted_path: Optional[Path] = None
        # 前置运行时（JDK / Erlang）的自动安装队列与下载线程。
        # 队列非空时「启动」按钮显示"准备依赖…"，装完自动继续启动。
        self._prereq_queue: List[Tuple[Component, str]] = []
        self.prereq_worker: Optional[DownloadWorker] = None
        # 「已配置」标签的异步版本号回填状态
        self._status_where = ""
        self._status_version = ""
        self._status_shows_configured = False
        # 多版本胶囊的基础文案：异步版本号回填时要在它后面续（" · <版本>"），
        # 不能落到非多版本那条 "✓ 已配置（…）" 旧文案。
        # **存的是全量原文**（tooltip 源 + 缓存）：短串单独存在 _mv_capsule_short，
        # 两者由 _detect_status_impl 的同一个分支产出。把缓存改成短串会让 tooltip
        # 丢掉版本列表；只改显示不改缓存，异步回填时全量原文又会弹回主文本。
        self._mv_capsule: str = ""
        self._mv_capsule_short: str = ""
        # 多版本胶囊是否用橙色告警态（未对齐 / 被 PATH 更靠前的条目遮蔽）
        self._mv_orange: bool = False
        # 多版本按钮状态：切换/卸载两个按钮要按"当前选中的版本"重算，
        # 而重算有两个触发点（探测之后、下拉框换选中），故把输入缓存在这里。
        self._mv_active: Optional[str] = None
        self._mv_warned: bool = False
        self._mv_installed_set: set = set()
        self._mv_buttons_ready: bool = False
        self._version_worker: Optional["VersionProbeWorker"] = None
        # 卸载按钮是否被"运行中"锁过：只有锁过才允许在停止后解冻。
        # 未运行时把 btn_uninstall 一律设成可用会顶掉 _detect_status 按"选中版本
        # 装没装"算出的状态，给出一张未安装也能点卸载的卡片（做不到的承诺）。
        self._uninstall_locked_by_launch: bool = False
        # 最近一次启动生成的「启动成功访问页」URL（没有自带控制台的组件用它，
        # 供「打开访问页」按钮与状态栏使用；进程内缓存，登记表里也写了一份）。
        self._launch_page_url: Optional[str] = None

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
        # 四行结构：顶部（标题+角标）/ 状态行 / 版本行 / 按钮行 / 进度条。
        # 原先版本下拉与按钮混在同一行（mid），塞进 271px 宽的格子必然换行，
        # 卡片高度从 121 涨到 230；拆开 + 缩短文案与 padding 后按钮一行放得下。
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        # 顶部：名称 & 角标
        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel(self.component.display_name)
        title.setObjectName("cardTitle")
        title.setFont(QFont("", 13, QFont.Bold))
        # 标题不许把卡片撑爆：QLabel 的 minimumSizeHint 是**整串文本**的宽度，
        # "Apache RocketMQ" 一渲染就要 255px，加上「可多版本」角标 71px 早就超过
        # 309px 的格子 → 网格里出现横向滚动条（真机 2026-10-08 实测踩中）。
        # 显式把最小宽压到 1，布局才允许压缩它；超宽的部分被裁掉，全名进 tooltip。
        title.setMinimumWidth(1)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title.setToolTip(self.component.display_name)
        top.addWidget(title)

        # 多版本能力角标：一个版本都没装时，这张卡片跟其它组件长得一样，
        # 用户看不出"它支持同时装几个版本"。做成独立 QLabel 而不是拼进标题文本——
        # display_name 同时是搜索匹配（component_matches）与日志前缀（_log）的真源。
        # 非多版本组件不创建这个节点（不是创建后隐藏），那 19 张卡片保持原样。
        if self.component.multi_version:
            badge = QLabel("可多版本")
            badge.setObjectName("multiVersionBadge")
            # 竖直方向必须 Fixed：同一行里标题的 sizeHint 比它高一点（13pt 粗体），
            # 默认 Preferred 会让角标被拉到与标题等高 —— 带背景的标签一被拉高，
            # 就从紧凑胶囊变成一个大盒子（真机 2026-10-10 用户截图：JDK / Python 卡）。
            badge.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            badge.setStyleSheet(
                "color:#5c6f82;background:#eef2f6;border-radius:9px;"
                "padding:2px 8px;font-size:11px;font-weight:600;"
            )
            badge.setToolTip(
                "这个组件可以同时安装多个版本。在下拉框里选中某个版本后点"
                "「切换」，就把它设为生效版本（改写 XXX_HOME 与 PATH）；"
                "带绿色对勾的版本表示磁盘上已安装。"
            )
            top.addWidget(badge)
        top.addStretch(1)
        root.addLayout(top)

        self.status_label = QLabel("检测中…")
        self.status_label.setObjectName("statusLabel")
        # 同标题的道理：QLabel 的 minimumSizeHint 是整串文本的宽度，状态一长
        # （"✓ 已配置 · 系统安装 · 版本检测中…"）就会把格子撑开，哪怕主文本已经
        # 精简过 —— 不同机器字体/缩放不同，撑到什么程度不一样。显式压掉最小宽，
        # 让布局允许压缩它；超宽的部分裁掉，全量原文本来就在 tooltip 里。
        self.status_label.setMinimumWidth(1)
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 角标与胶囊都靠左挤在一起会互相裁字，胶囊单独一行（格子内部只有 271px）
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(self.status_label)
        if self.component.launch is not None:
            # 运行状态自己一个小 label：status_label 已有 5 处写点，挤进去会把
            # 多版本胶囊 / 系统安装 那套判定搅浑（R3.9 要求非目标组件零影响）。
            # 原先挂在按钮行尾巴上，按钮行在 271px 里已经排满，故提到状态行。
            self.launch_label = QLabel("")
            self.launch_label.setObjectName("launchLabel")
            # 同上：僵尸登记的原文很长，别让它把格子撑开
            self.launch_label.setMinimumWidth(1)
            self.launch_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            status_row.addWidget(self.launch_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

        # 版本行：版本标签 + 下拉框
        ver = QHBoxLayout()
        ver.setSpacing(8)
        version_label = QLabel("版本")
        version_label.setObjectName("fieldLabel")
        version_label.setFixedWidth(36)
        ver.addWidget(version_label)

        self.version_combo = SearchableComboBox()
        self.version_combo.setObjectName("versionCombo")
        self.version_combo.setCursor(QCursor(Qt.PointingHandCursor))
        self._reload_combo_items()
        # 固定宽度，避免抢占按钮空间。150 是"版本串还能看全"与"按钮行放得下"的折中：
        # 原来的 220 会把按钮行顶出格子。
        self.version_combo.setFixedWidth(150)
        self.version_combo.setFixedHeight(30)
        self.version_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # 换选中就要重算切换/卸载按钮：不连这条，切一次生效版本后按钮会一直灰着
        # （2026-09-30 真机反馈）。只做按钮同步，不重跑探测、不起版本探测子进程。
        self.version_combo.currentIndexChanged.connect(
            lambda *_: self._sync_action_buttons())
        ver.addWidget(self.version_combo)
        ver.addStretch(1)
        root.addLayout(ver)

        # 按钮行：一行放完，不换行
        actions = QHBoxLayout()
        actions.setSpacing(6)

        self.btn_install = QPushButton("安装")
        self.btn_install.setObjectName("primaryBtn")
        self.btn_install.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_install.setFixedHeight(30)
        self.btn_install.clicked.connect(self.on_install_clicked)
        actions.addWidget(self.btn_install)

        # 「配置环境变量 / 切换为生效版本」→「切换」：格子只有 271px，
        # 两种旧叫法都太长；多版本语义由 tooltip 承载（下面 _sync_action_buttons 里）。
        self.btn_configure = QPushButton("切换")
        self.btn_configure.setObjectName("secondaryBtn")
        self.btn_configure.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_configure.setFixedHeight(30)
        self.btn_configure.clicked.connect(self.on_configure_clicked)
        actions.addWidget(self.btn_configure)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("dangerBtn")
        self.btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_cancel.setFixedHeight(30)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)  # 默认隐藏；开始下载时才显示
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        actions.addWidget(self.btn_cancel)

        self.btn_uninstall = QPushButton("卸载")
        self.btn_uninstall.setObjectName("dangerBtn")
        self.btn_uninstall.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_uninstall.setFixedHeight(30)
        # 默认禁用，待 _detect_status 检测到已安装或有本地下载时才启用
        self.btn_uninstall.setEnabled(False)
        self.btn_uninstall.setToolTip("删除已安装的版本、清理 XXX_HOME 与 PATH")
        self.btn_uninstall.clicked.connect(self.on_uninstall_clicked)
        actions.addWidget(self.btn_uninstall)

        # 启动相关按钮：只有登记了启动描述符的组件才有（LAUNCH_KEYS，本期只有 Jenkins）
        self.launch_worker: Optional[LaunchWorker] = None
        if self.component.launch is not None:
            # 启动/停止合并成**一个**按钮（2026-10-06 用户要求）：
            # 未运行时显示「启动」，运行中变成「停止」，点了就做对应的事。
            #
            # 为什么不用两个按钮切换显隐：按钮的位置会变，用户的眼睛要重新找一遍。
            # 2026-10-06 用户连续三次反馈"没有停止按钮"—— 按钮其实一直好着
            # （可见可用、文本"停止"），问题在于它与「启动」并排、
            # 运行状态时那一格才亮起来，看起来就像"多出来的按钮没出现"。
            # 合成一个之后：按钮永远在那儿，状态直接写在按钮文字上，
            # 不用找、不用猜。
            #
            # 文案**不许瘦身**：_running_per_ui() 读它判断是否在运行。
            self.btn_start = QPushButton("启动")
            self.btn_start.setObjectName("primaryBtn")
            self.btn_start.setCursor(QCursor(Qt.PointingHandCursor))
            self.btn_start.setFixedHeight(30)
            self.btn_start.clicked.connect(self.on_start_stop_clicked)
            actions.addWidget(self.btn_start)
            # 刻意**不保留** `self.btn_stop`：合并按钮后没有第二个 widget，
            # 留一个同名别名会让读代码的人以为界面上有两个按钮。
            # 旧代码里 `btn_stop.isEnabled()` 那个"是否在运行"的判据，
            # 改为读按钮文字——见 _running_per_ui()。
            self.btn_console = QPushButton("控制台")
            # 原先没有 objectName → 三条 QSS 全部匹配不到它，拿系统默认样式，
            # 实测比旁边几颗按钮宽一圈（sizeHint 恒 80，同长度的「安装」只占 42）。
            self.btn_console.setObjectName("secondaryBtn")
            self.btn_console.setFixedHeight(30)
            self.btn_console.clicked.connect(self.on_console_clicked)
            self.btn_console.setEnabled(False)
            actions.addWidget(self.btn_console)

        actions.addStretch(1)  # 右侧留空，避免按钮被拉伸
        root.addLayout(actions)

        # 底部：进度条
        # 高度保持 14：setTextVisible(True) 的百分比在 8px 下必然被裁切，
        # 且圆角 6px 会大于半高 4px。
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        # ---- 「系统里检测到的版本」折叠区＋还原按钮（设计 §6）----
        # 只给白名单里的 7 个组件建（不是建了再隐藏）：其余 19 张卡片保持原样，
        # R3.9 那句"非目标组件文案与按钮零变化"才守得住。
        self._external_candidates: List["DiscoveredVersion"] = []
        self._external_scanned = False
        self._external_expanded = False
        self._external_worker: Optional["ExternalDiscoveryWorker"] = None
        self._external_rows: List[QWidget] = []
        self._restore_btn: Optional[QPushButton] = None
        self._external_frame: Optional[QFrame] = None
        self._external_toggle: Optional[QPushButton] = None
        self._external_body: Optional[QWidget] = None
        if supports_external_takeover(self.component):
            self._build_external_section(root)

    # ------------------------------------------------------------------
    # 「系统里检测到的版本」折叠区（§6）
    # ------------------------------------------------------------------
    def _build_external_section(self, root: QVBoxLayout) -> None:
        """卡片底部的折叠区 + 常驻的「还原到我之前的设置」。

        默认收起且整块隐藏：格子内部只有 271px，展开就是好几行；绝大多数机器上
        这里本来就是空的，不该白占地方。首次展开时才去扫（要真跑版本命令）。
        """
        self._external_frame = QFrame()
        self._external_frame.setObjectName("externalBox")
        box = QVBoxLayout(self._external_frame)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)

        self._external_toggle = QPushButton("▸ 系统里检测到的版本")
        self._external_toggle.setObjectName("externalToggle")
        self._external_toggle.setCursor(QCursor(Qt.PointingHandCursor))
        self._external_toggle.setFixedHeight(24)
        # 同卡片里所有 QLabel/QPushButton 的道理：不压掉最小宽，长路径会把格子撑开
        self._external_toggle.setMinimumWidth(1)
        self._external_toggle.setSizePolicy(QSizePolicy.Expanding,
                                            QSizePolicy.Fixed)
        self._external_toggle.setToolTip(
            "扫描本机已安装的这个组件的其它版本（环境变量、PATH、注册表里的登记）。\n"
            "扫描只读，不会改动任何设置；点开后才开始扫描。")
        self._external_toggle.clicked.connect(self._toggle_external_section)
        box.addWidget(self._external_toggle)

        self._external_body = QWidget()
        self._external_body_layout = QVBoxLayout(self._external_body)
        self._external_body_layout.setContentsMargins(2, 0, 2, 0)
        self._external_body_layout.setSpacing(3)
        self._external_body.setVisible(False)
        box.addWidget(self._external_body)

        self._restore_btn = QPushButton("↩ 还原到我之前的设置")
        self._restore_btn.setObjectName("restoreBtn")
        self._restore_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._restore_btn.setFixedHeight(26)
        self._restore_btn.setMinimumWidth(1)
        self._restore_btn.setVisible(False)
        self._restore_btn.clicked.connect(self.on_restore_external_clicked)
        box.addWidget(self._restore_btn)

        self._external_frame.setVisible(False)
        root.addWidget(self._external_frame)

        # 末尾必须有一个 stretch：网格会把同一行的卡片拉成等高，内容少的卡片
        # 就多出一段高度。没有这个占位的话，那段高度会被各行按策略分掉 ——
        # 带背景色的标签首当其冲：真机 2026-10-10 用户截图里，JDK / Python 卡的
        # 「可多版本」角标被拉成一个大盒子，而同一行内容更多的 Maven 卡是紧凑胶囊。
        root.addStretch(1)

    def _toggle_external_section(self) -> None:
        self._external_expanded = not self._external_expanded
        self._external_body.setVisible(self._external_expanded)
        self._external_toggle.setText(
            ("▾ " if self._external_expanded else "▸ ") + self._external_toggle_text())
        if self._external_expanded and not self._external_scanned:
            self._start_external_discovery()

    def _external_toggle_text(self) -> str:
        n = len(self._external_candidates)
        return f"系统里检测到的版本（{n}）" if self._external_scanned \
            else "系统里检测到的版本"

    def _start_external_discovery(self) -> None:
        self._external_toggle.setText("▾ 正在扫描…")
        self._external_toggle.setEnabled(False)
        self._external_worker = ExternalDiscoveryWorker(self.component, self)
        self._external_worker.done.connect(self._on_external_discovered)
        self._external_worker.start()

    def _on_external_discovered(self, cands) -> None:
        self._external_worker = None
        self._external_scanned = True
        self._external_candidates = [c for c in cands if c.source != "workspace"]
        self._external_toggle.setEnabled(True)
        self._external_toggle.setText(
            ("▾ " if self._external_expanded else "▸ ") + self._external_toggle_text())
        self._refresh_external_section()

    def _refresh_external_section(self) -> None:
        """按当前状态重画折叠区与还原按钮。"""
        if self._external_frame is None:
            return
        takeover = (load_takeover_map().get(self.component.key)
                    if supports_external_takeover(self.component) else None)
        # R3.19：为工作区版本提权改过系统变量时，还原按钮同样要常驻 —— 用户点「切换」
        # 被系统级条目压住、同意了那次提权，之后就必须有个一键回到原样的出口。
        machine_fix = (load_machine_fix_map().get(self.component.key)
                       if supports_external_takeover(self.component) else None)

        # 还原按钮：只在"确实动过"时常驻（§6）。重启后仍然出现 —— 依据是
        # config.json 里的登记，不是本次运行的内存状态。
        if self._restore_btn is not None:
            self._restore_btn.setVisible(bool(takeover or machine_fix))
            if takeover:
                snap = takeover.get("snapshot") or {}
                hives = []
                if snap.get("HKCU"):
                    hives.append("HKCU\\Environment")
                if snap.get("HKLM"):
                    hives.append("HKLM\\SYSTEM\\...\\Environment")
                keys = sorted({k for h in snap.values() if isinstance(h, dict)
                               for k in h})
                self._restore_btn.setToolTip(
                    f"当前生效的是系统里那个 {takeover.get('version')}"
                    f"（{takeover.get('home')}）。\n"
                    f"点这里按接管前的原文写回：{'、'.join(hives) or '（无）'}"
                    f"，键：{'、'.join(keys) or '（无）'}。\n"
                    "需要管理员权限时会再弹一次授权。")
            elif machine_fix:
                snap = machine_fix.get("snapshot") or {}
                keys = sorted(k for k in (snap.get("HKLM") or {}))
                self._restore_btn.setToolTip(
                    f"为了让工作区里的 {machine_fix.get('version')} 生效，"
                    "本工具在系统 PATH 最前插了一条。\n"
                    f"点这里按改动前的原文写回：HKLM\\SYSTEM\\...\\Environment，"
                    f"键：{'、'.join(keys) or '（无）'}。\n"
                    "还原后命令行会回到改动前的那一份（也就是你自己装的那个），"
                    "本工具装的版本仍在，可用下拉框再切回来。\n"
                    "需要管理员权限时会再弹一次授权。")

        # 折叠区整块：有外部候选 or 有接管/提权登记的残留时才出现
        show = bool(self._external_candidates) or bool(takeover or machine_fix)
        self._external_frame.setVisible(show)
        if not show:
            return

        # 清空上一轮：takeAt 之后布局就不管它了，但 widget 的 parent 与几何都还在，
        # 延迟删除执行前它会一直渲染在原地（项目记忆里踩过的"幽灵"）→ 先 hide、
        # 再摘 parent、最后 deleteLater。
        while self._external_body_layout.count():
            item = self._external_body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._external_rows = []

        if not self._external_candidates:
            hint = QLabel("没有扫描到外部安装的版本")
            hint.setObjectName("externalHint")
            hint.setMinimumWidth(1)
            self._external_body_layout.addWidget(hint)
            self._external_rows.append(hint)
            return

        for dv in self._external_candidates:
            row = self._make_external_row(dv, takeover)
            self._external_body_layout.addWidget(row)
            self._external_rows.append(row)

    def _make_external_row(self, dv: "DiscoveredVersion",
                           takeover: Optional[dict]) -> QWidget:
        """一行外部版本：版本号 / 完整路径 / 「当前在用」标记 + 「切过去」。

        路径**换行显示**而不是省略号：格子只有 271px，而用户就是靠这段路径
        认出"这是我装在 D 盘那个"。裁掉一半等于把这一行的全部信息量丢掉一半，
        所以宁可让卡片高一点（折叠区本来就是用户主动展开的）。
        """
        row = QFrame()
        row.setObjectName("externalRow")
        outer = QVBoxLayout(row)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(0)

        in_use = bool(takeover) and EnvManager._same_path(
            str(dv.home), str(takeover.get("home") or ""))
        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel(f"{dv.version}" + ("　← 当前在用" if in_use else ""))
        title.setObjectName("externalVersion")
        title.setMinimumWidth(1)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        head.addWidget(title)

        btn = QPushButton("已生效" if in_use else "切过去")
        btn.setObjectName("secondaryBtn")
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setFixedHeight(24)
        btn.setEnabled(not in_use)
        btn.setToolTip("已生效" if in_use else
                       f"把这个版本设为生效版本（会改写 "
                       f"{self.component.env_var or 'PATH'}，必要时需要管理员权限）")
        btn.clicked.connect(lambda _=False, d=dv: self.on_switch_external(d))
        head.addWidget(btn)
        outer.addLayout(head)

        # 路径单独一行、占满整行宽：271px 的格子里它本来就放不下，
        # 挤在按钮旁边只会两败俱伤（实测按钮会压在路径文字上）。
        path_label = QLabel(str(dv.home))
        path_label.setObjectName("externalPath")
        path_label.setMinimumWidth(1)
        path_label.setWordWrap(True)
        path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        path_label.setToolTip(f"{dv.version}\n{dv.home}\n发现来源：{dv.source}")
        outer.addWidget(path_label)
        return row

    def on_switch_external(self, dv: "DiscoveredVersion") -> None:
        """把生效版本切到这个外部安装（§5.3 → 需要时 §5.4 提权）。"""
        def _sink(text: str) -> None:
            low = str(text)
            level = ("error" if ("失败" in low or "未通过" in low or "未完成" in low)
                     else "warn" if ("取消" in low or "未能" in low or "仍" in low)
                     else "info")
            self._log(level, low)

        self._log("info", f"准备切换到系统里那个 {dv.version}（{dv.home}）…")
        res = switch_to_external_version(
            self.component, dv,
            confirm_machine=self._confirm_machine_takeover, log=_sink)
        for step in res.get("steps") or []:
            _sink(step)
        if res.get("ok"):
            self._log("ok", f"已切换到系统里的 {dv.version}；"
                            "新开的终端/IDE 才会读到新值")
            self._log_verification_hint(time.time())
        elif res.get("verdict") == "cancelled":
            self._log("warn", "已取消，未做任何改动")
        else:
            self._log("error", str(res.get("error") or "切换未成功"))
        self._refresh_external_section()
        self._detect_status()
        self._sync_action_buttons()

    def _confirm_machine_takeover(self, plan: dict) -> bool:
        """提权前的确认框：逐条列出要改什么、改成什么、原来是什么（§5.4 明文要求）。

        这里必须是"用户点了确定才动系统变量"—— 它改的是整机所有程序看到的环境。
        """
        env_var = str(plan.get("env_var") or "")
        add_entry = str(plan.get("add_entry") or "")
        before_path, before_type = read_machine_env_raw("Path")
        before_var, _vt = read_machine_env_raw(env_var) if env_var else (None, "")
        lines = [
            f"要让命令行真正用上这个版本，需要修改「系统变量」（需要管理员权限）：",
            "",
            f"· 系统 PATH 最前面插入：",
            f"    {add_entry}",
        ]
        if env_var:
            lines += ["", f"· 系统变量 {env_var}：",
                      f"    现在：{before_var or '（未设置）'}",
                      f"    改为：{plan.get('home')}"]
        lines += [
            "",
            f"· 其余原有条目（含 {before_type or 'REG_EXPAND_SZ'} 里的 %VAR% 占位符）"
            f"逐字保留，不删不改；",
            "· 改动前的原文会先存一份快照，卡片上随时可以「还原到我之前的设置」。",
            "",
            "继续吗？（会弹出 Windows 的权限确认窗口）",
        ]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("需要管理员权限")
        box.setText("\n".join(lines))
        yes = box.addButton("继续（修改系统变量）", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def on_restore_external_clicked(self) -> None:
        """「还原到我之前的设置」：按快照把动过的变量写回原文。

        R3.19 之后这里要能收两笔账，顺序固定：先还「为工作区版本提权改的系统变量」，
        再还「接管的外部版本」。两者在稳态里不会并存（切工作区版本前已先还原），
        真碰到并存时全还掉才是"回到我之前的样子"。
        """
        def _sink(text: str) -> None:
            level = ("error" if ("失败" in str(text) or "未完成" in str(text))
                     else "info")
            self._log(level, str(text))

        did = False
        if has_machine_fix(self.component):
            fix = revert_machine_fix(self.component, log=_sink)
            for step in fix.get("steps") or []:
                _sink(step)
            if fix.get("ok"):
                did = True
            else:
                self._log("error", "系统变量还原未完成："
                          + str(fix.get("error") or ""))

        if has_external_takeover(self.component):
            res = revert_external_version(self.component, log=_sink)
            for step in res.get("steps") or []:
                _sink(step)
            if res.get("ok"):
                did = True
            elif res.get("cancelled"):
                self._log("warn", "已取消还原，设置未改动")
            else:
                self._log("error", str(res.get("error") or "还原未完成"))

        if did:
            self._log("ok", "已还原到我之前的设置，新开的终端才会读到")
        self._refresh_external_section()
        self._detect_status()

    # ------------------------------------------------------------------
    # 状态文案：主文本给短串，全量详情进 tooltip
    # ------------------------------------------------------------------
    def _set_status(self, full: str, short: str) -> None:
        """状态行的唯一写入口：主文本用短串，全量原文进 tooltip。

        格子内部只有 271px，而 PySide6 的 QLabel 没有 setElideMode（超宽是直接
        clip，不是省略号），所以长文案只能"主文本写结论、tooltip 写全文"。
        两者**每次都要一起设置**：状态切换时只 setText 会把上一轮的详情留在
        悬停提示里，变成一句已经没有依据的旧话。
        """
        self.status_label.setText(short)
        self.status_label.setToolTip(full)

    def _set_launch(self, full: str, short: str) -> None:
        """运行状态 label 的唯一写入口，同 _set_status()。"""
        self.launch_label.setText(short)
        self.launch_label.setToolTip(full)

    # ------------------------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        self.log_cb(level, f"[{self.component.display_name}] {msg}")

    # ------------------------------------------------------------------
    # 一键启动：卡片只负责"读状态 → 摆按钮 → 把动作丢进线程"，判定全在 ServiceManager。
    def _launch_status(self):
        return SERVICE_MANAGER.status(self.component.key, self.component)

    def _refresh_launch_state(self) -> None:
        """按端口实况刷新按钮与运行状态 label（不碰 status_label 那枚状态胶囊）。
        本方法只读，一次都不许拉起进程。"""
        if self.component.launch is None:
            return
        try:
            self._refresh_launch_state_impl()
        finally:
            # 状态一变就通知主窗重算 Tab 上的运行标记 `●`。放在 finally 里：
            # 刷新过程中抛异常时标记也不该留在旧值上。
            self._notify_tabs_running_changed()

    def _notify_tabs_running_changed(self) -> None:
        """告诉主窗"本卡片是否在运行"变了，好去刷新 Tab 标题上的 `●`。

        用 getattr 逐层探：卡片可能在窗口还没建完时就被刷新（构造期测试），
        那时主窗上还没有 _mark_running_tabs，直接跳过而不是炸掉整个刷新。
        """
        try:
            win = self.window()
        except Exception:       # 顶层 C++ 对象已销毁（关窗途中）
            return
        mark = getattr(win, "_mark_running_tabs", None)
        if mark is None:
            return
        try:
            mark()
        except Exception:       # 主窗可能正处在关窗流程里，标记刷不上不影响功能
            pass

    def _running_per_ui(self) -> bool:
        """**界面上**认定的"在运行"：按钮文字是不是「停止」。

        为什么读文字而不读 enabled：合并按钮后按钮在运行中也要可点（它就是停止按钮），
        enabled 已经不能区分状态了。而按钮文字就是用户看到的状态本身 ——
        读它等于"用户以为的"与"程序认为的"永远一致。
        Tab 上的运行标记、跳页逻辑都用它。
        """
        return self.btn_start.text().rstrip("… ") == "停止"

    def _refresh_launch_state_impl(self) -> None:
        st = self._launch_status()
        running = st.state == "running"
        # 磁盘上没有任何已安装版本时，「启动」就**该是灰的**（2026-10-10 用户给的
        # 两个方案里选这个）：与"选中版本已装则置灰「安装」"是同一条设计语言 ——
        # 做不到的事不给点。另一个方案（点了再弹"没装"提示）被否掉的实测理由：
        # 以前点下去会先弹一个**端口与风险确认框**，用户确认完才在日志里看到"没装"，
        # 等于先骗他做一次决定。
        launchable = resolve_launch_version(self.component) is not None
        self.btn_start.setEnabled(self.launch_worker is None and (running or launchable))
        # **每个可启停组件都有一个能打开的地址**（2026-10-08 用户要求）：
        #   自带 Web 界面 → 按钮文字「控制台」，指向它自己的页面；
        #   协议端口型（kafka/rocketmq/rabbitmq）→ 文字「访问页」，
        #   指向工具自带的「启动成功」页（卡片销毁前若还留着上次的 URL 就用它，
        #   否则由 _has_console() 从登记表里读）。
        spec = getattr(self.component, "launch", None)
        own_page = spec is not None and bool(spec.console_path)
        self.btn_console.setText("控制台" if own_page else "访问页")
        # 按钮**常驻**（2026-10-10 用户报「有些怎么没有控制台按钮」）：以前停止状态下
        # `console_path` 为 None 的组件（kafka / rocketmq / rabbitmq）会被整个藏掉 ——
        # 它们只有运行期间由本工具生成的那一页"启动成功 / 该怎么访问"，于是没在跑的时候
        # 按钮消失，用户读成"这个组件少了一个功能"。现在只要可启停就留着，
        # 点不动的原因写进 tooltip（禁用态不解释，就是让用户猜）。
        self.btn_console.setVisible(spec is not None)
        self.btn_console.setEnabled(running)
        self.btn_console.setToolTip(
            "" if running else
            f"启动 {self.component.display_name} 之后才能打开"
            + ("它自己的页面" if own_page else "本工具为它生成的访问说明页"))
        # 按钮文字就是状态本身：运行中显示「停止」，否则显示「启动」。
        # 正在起/停的过渡态（"启动中…"/"停止中…"）不能被这一行盖掉——
        # 那是用户点下去之后的即时反馈，被立刻改回「启动」会让人以为没点上。
        if self.launch_worker is None:
            if running:
                self.btn_start.setText("停止")
                self.btn_start.setObjectName("dangerBtn")
                self.btn_start.setToolTip(
                    f"停止 {self.component.display_name}（端口 {st.record.port}）")
            else:
                self.btn_start.setText("启动")
                self.btn_start.setObjectName("primaryBtn")
                self.btn_start.setToolTip(
                    f"启动 {self.component.display_name}（端口 {self.component.launch.main_port}）"
                    if launchable else
                    f"磁盘上还没有 {self.component.display_name} 的已安装版本，"
                    "先点「安装」装一个，或把版本切到已装的那个，才能启动")
            # 换objectName 后要重刷 QSS，否则配色停留在上一个状态。
            self.btn_start.style().unpolish(self.btn_start)
            self.btn_start.style().polish(self.btn_start)
        if running:
            # 「无网页控制台」写在标签里（2026-10-06 用户报「显示启动成功实际无法访问」）：
            # 服务是好的，只是没有页面可点。把这句话摆在这儿，用户就不会去找
            # 那个不存在的控制台入口、也不会以为服务坏了。
            tail = "" if self._has_console() else " · 无网页控制台"
            self._set_launch(f"● 运行中 · 端口 {st.record.port}{tail}",
                             f"● 运行中 {st.record.port}")
            # 运行中禁止卸载：边跑边删目录会把正在写的日志和数据留在半删状态
            self.btn_uninstall.setEnabled(False)
            self.btn_uninstall.setToolTip("请先停止运行中的 %s 再卸载" % self.component.display_name)
            self._uninstall_locked_by_launch = True
        else:
            if st.state == "zombie":
                # 僵尸登记要看得见：否则"上次崩了、登记还留着"和"干净地停过"长得一模一样。
                # 文案只承诺 start() 真会做的事：它不看旧 PID，直接起一个新进程并覆盖这条登记
                # —— 万一是"卡住但还活着"的旧进程，那个进程归 adopt/手工处理，别说成"接管"。
                self._set_launch(
                    f"⚠ 上次运行的残留登记（端口 {st.record.port} 没在听），"
                    f"再点启动会重新起一个并覆盖这条登记",
                    f"⚠ 残留登记 · 端口 {st.record.port}")
            else:
                self._set_launch("", "")
            # 只解冻自己被锁过的那次：卸载按钮的可用性本来由 _detect_status /
            # _sync_action_buttons 按"选中版本装没装"判定，无条件点亮会给出
            # 一张未安装也能点卸载的卡片。
            if self._uninstall_locked_by_launch:
                self._uninstall_locked_by_launch = False
                self.btn_uninstall.setEnabled(True)
                self.btn_uninstall.setToolTip("删除已安装的版本、清理 XXX_HOME 与 PATH")

    def on_start_clicked(self) -> None:
        spec = self.component.launch
        # 按钮平时就是灰的（见 _refresh_launch_state_impl 的 launchable 判据），
        # 这一道是兜底：状态是异步刷的，磁盘可能在两次刷新之间被外部删掉。
        # **必须排在自动装前置依赖之前** —— 否则一个没装的组件会先被拉去装一个 JDK，
        # 装完再告诉他"没装"，白折腾一遍网络。
        if resolve_launch_version(self.component) is None:
            self._log("warn",
                      f"磁盘上还没有 {self.component.display_name} 的已安装版本，"
                      "先点「安装」装一个，或把版本切到已装的那个，再点启动。")
            return
        # 「开机就能用」：缺前置运行时（JDK / Erlang）时**先自动装好再启动**，
        # 而不是弹一句"请先装一个 JDK"把活儿交回给用户。
        missing = prereq_components(self.component, MainWindow.current_components())
        if missing:
            self._install_missing_prereqs(missing)
            return
        self._do_start()

    def _do_start(self) -> None:
        """真正开始启动（前置依赖已就位时走这里）。"""
        spec = self.component.launch
        # 端口提示必须与实际行为一致。2026-10-06 起策略是"不平移、被占就结束占用者"，
        # 这里原来还写着"被占用时会自动往后找空闲口"—— 确认框里说假话比不说更糟：
        # 用户以为端口会变，于是按自己的预期去连那个并不存在的端口。
        port_line = f"端口：{spec.main_port}"
        if spec.port_offsets:
            port_line += f"（派生口 {', '.join(str(spec.main_port + int(o)) for o in spec.port_offsets)}）"
        if spec.extra_ports:
            port_line += f"；独立口 {', '.join(str(p) for p in spec.extra_ports)}"
        port_line += "\n（端口被占用时会结束占用它的进程，不会自动换端口）"
        reply = QMessageBox.question(
            self, "确认启动 %s" % self.component.display_name,
            "%s\n%s\n\n确认启动？" % (port_line, spec.risk_note),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return
        self.btn_start.setEnabled(False)
        self.btn_start.setText("启动中…")
        # parent=self：worker 归卡片的 Qt 对象树持有，run() 还没回来时不依赖
        # launch_worker 这一个引用吊命；结束后由 _on_launch_worker_done deleteLater 收回。
        self.launch_worker = LaunchWorker("start", self.component,
                                          MainWindow.current_components(), SERVICE_MANAGER,
                                          parent=self)
        self.launch_worker.started_ok.connect(self._on_launch_ok)
        self.launch_worker.failed.connect(self._on_launch_failed)
        self.launch_worker.notes.connect(self._on_launch_notes)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    # ------------------------------------------------------------------
    # 前置运行时的自动安装（JDK / Erlang）
    # ------------------------------------------------------------------
    def _install_missing_prereqs(self, keys: List[str]) -> None:
        """把缺失的前置运行时排队装好，装完自动重跑启动。

        为什么不弹"要不要装"的问询：用户点了「启动」就是"我要它跑起来"，
        再问一次等于把决定权丢回去；而这里要装的都是**明确的、可复现的**东西
        （JDK / Erlang 的官方包），装错了也只是多一个版本目录。
        """
        comps = MainWindow.current_components()
        queue: List[Tuple[Component, str]] = []
        for key in keys:
            pre = comps.get(key)
            if pre is None:
                continue
            version = pick_prereq_version(pre, prereq_install_versions(self.component))
            if version is None:
                QMessageBox.warning(
                    self, "缺少前置运行时",
                    f"{self.component.display_name} 需要 {pre.display_name}，"
                    f"但当前平台没有它的可下载版本。")
                return
            if prereq_already_installed(pre, version):
                continue
            queue.append((pre, version))
        if not queue:
            # 需求已经满足（比如别的卡片刚装上）→ 直接继续
            self._do_start()
            return
        names = "、".join(f"{c.display_name} {v}" for c, v in queue)
        self._log("info", f"{self.component.display_name} 启动前需要 {names}，"
                          f"正在自动下载安装（装一次，以后不再重复）…")
        self.btn_start.setEnabled(False)
        self.btn_start.setText("准备依赖…")
        self._prereq_queue = queue
        self._install_next_prereq()

    def _install_next_prereq(self) -> None:
        """装队列里的下一个前置组件；装完继续下一个，全装完则重跑启动。"""
        if not self._prereq_queue:
            self.btn_start.setEnabled(True)
            self.btn_start.setText("启动")
            self._log("ok", "前置运行时已就位，继续启动。")
            self._do_start()
            return
        pre, version = self._prereq_queue.pop(0)
        cv = next((c for c in pre.versions if c.version == version), None)
        urls = cv.urls_for_current() if cv else []
        if cv is None or not urls:
            self._on_prereq_failed(f"{pre.display_name} {version} 没有可用下载地址")
            return
        suffix = self._download_suffix(pre, cv, urls)
        dest = CONFIG_DIR / pre.key / "downloads" / f"{pre.key}-{version}{suffix}"
        ensure_dir(dest.parent)
        self._log("info", f"下载 {pre.display_name} {version}（源：{urls[0]}）")
        self.prereq_worker = DownloadWorker(urls, dest, parent=self)
        self.prereq_worker.progress.connect(self._on_prereq_progress)
        self.prereq_worker.log.connect(self._log)
        self.prereq_worker.finished_ok.connect(
            lambda p, c=pre, v=version: self._on_prereq_downloaded(c, v, Path(p)))
        self.prereq_worker.finished_fail.connect(self._on_prereq_failed)
        self.prereq_worker.start()

    @staticmethod
    def _download_suffix(comp: "Component", cv: "ComponentVersion", urls: List[str]) -> str:
        """下载文件名的后缀必须与包体真实形态一致（extract_archive 按后缀选分支）。"""
        if comp.installer_mode:
            ext = cv.archive_map.get(CURRENT_OS, "")
            if not ext:
                first = urls[0] if urls else ""
                ext = "exe" if first.endswith(".exe") else ("sh" if first.endswith(".sh") else "bin")
            return f".{ext}"
        ext = cv.archive_for_current()
        return {"zip": ".zip", "tar.gz": ".tar.gz", "tgz": ".tar.gz", "exe": ".exe",
                "war": ".war", "": "", "bin": ""}.get(ext, f".{ext}")

    def _on_prereq_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._log("info", f"依赖下载中：{human_size(done)} / {human_size(total)}"
                              f"（{int(done * 100 / total)}%）")

    def _on_prereq_downloaded(self, pre: "Component", version: str, path: Path) -> None:
        try:
            final = install_downloaded(pre, version, path, _LoggerAdapter(self._log))
        except Exception as exc:
            self._on_prereq_failed(f"{pre.display_name} 安装失败：{exc}")
            return
        if not prereq_already_installed(pre, version):
            self._on_prereq_failed(f"{pre.display_name} 装完了但在 {final} 里找不到可执行文件")
            return
        self._log("ok", f"{pre.display_name} {version} 已装好：{final}")
        ok_env = self._configure_prereq_env(pre, final)
        if not ok_env:
            # java 系组件没有 JAVA_HOME 就是起不来，这里不许再写成"不影响启动"
            self._on_prereq_failed(
                f"{pre.display_name} 装好了，但写 {pre.env_var or 'PATH'} 失败，"
                f"{self.component.display_name} 依然启动不了")
            return
        self._install_next_prereq()

    def _configure_prereq_env(self, pre: "Component", final: Path) -> bool:
        """让刚装好的前置运行时**真的能用**：HOME 变量 + PATH 都要写，且跨平台。

        以前这里只调 Windows 专用的 `set_windows_user_env` 写一个 HOME，**不写 PATH**，
        Linux/macOS 上更是连 HOME 都不写；失败时日志还写着"不影响启动" —— 对 java 系
        组件来说恰恰相反：JAVA_HOME 没配上，nacos 的 startup.cmd / jenkins 的 `java -jar`
        根本起不来，用户看到的就是"依赖明明装好了，启动还是失败"。
        所以改成与正常安装同一套写入（HOME + PATH + 装完核对），失败如实上报。
        """
        bin_dir = final / pre.path_subdir if pre.path_subdir else final
        try:
            if pre.env_var:
                if CURRENT_OS == "Windows":
                    EnvManager.set_windows_user_env(pre.env_var, str(final))
                    EnvManager.append_windows_path(str(bin_dir))
                else:
                    rc = EnvManager.set_unix_env(pre.env_var, str(final))
                    EnvManager.append_unix_path(str(bin_dir))
                    self._log("info", f"已写入 {rc}")
                self._log("ok", f"设置 {pre.env_var}={final}")
            else:
                if CURRENT_OS == "Windows":
                    EnvManager.append_windows_path(str(bin_dir))
                else:
                    EnvManager.append_unix_path(str(bin_dir))
            self._log("ok", f"追加 PATH：{bin_dir}")
            ok_dir, _where = verify_bin_dir(pre, final)
            if not ok_dir:
                self._log("warn", f"{pre.display_name} 装完了，但 {bin_dir} 里没有它的可执行文件")
            return True
        except Exception as exc:  # noqa: BLE001
            self._log("error", f"写 {pre.env_var or 'PATH'} 失败：{exc}")
            return False

    def _on_prereq_failed(self, reason: str) -> None:
        self._prereq_queue = []
        self.btn_start.setEnabled(True)
        self.btn_start.setText("启动")
        self._log("error", f"前置运行时准备失败：{reason}")
        QMessageBox.warning(self, "前置运行时准备失败",
                            f"{reason}\n\n装好之后可以再点一次「启动」。")

    def _on_launch_ok(self, key: str, console_url: str) -> None:
        """启动成功后的统一收尾：**给用户一个能打开的地址** + 说清停止按钮在哪。

        2026-10-08 用户要求：不管组件有没有自带控制台，启动后都要有个能访问的页面，
        让用户确认"确实起来了"。所以这里分两路：
          - 自带 Web 界面（含 ES 的 JSON 根路径）：地址就是它自己的；
          - 协议端口型（kafka / rocketmq / rabbitmq）：用工具自带的
            「启动成功」页（见 ComponentPageServer），并把 URL 写回登记，
            这样卡片上的「打开访问页」按钮也能直接打开它。
        """
        st = self._launch_status()
        rec = st.record
        spec = self.component.launch
        page_url: Optional[str] = None
        if rec is not None and spec is not None:
            try:
                page_url = show_launch_page(self.component, spec, rec)
            except Exception as exc:      # 页面服务不该影响"启动成功"这件事
                self._log("warn", f"生成访问页失败（不影响服务运行）：{exc}")
            if page_url and page_url != rec.console_url:
                # 把访问页写回登记：刷新界面/重开工具后「打开访问页」按钮仍可用
                try:
                    records = load_running_map()
                    if self.component.key in records:
                        records[self.component.key].console_url = page_url
                        save_running_map(records)
                except Exception:
                    pass
                self._launch_page_url = page_url
        if spec is not None and rec is not None:
            for line in launch_success_lines(self.component, spec, rec, page_url):
                self._log("ok", line)
        self._refresh_launch_state()
        # 明说停止按钮在哪：2026-10-06 用户反馈"启动了 nacos，没看到停止选项"。
        # 查下来按钮一直好着（可见可用、文本"停止"、旁边 label 显示"● 运行中 · 端口 8848"），
        # 但启动成功后只写一句"已启动，控制台：…"，用户不确定"停止"这个按钮出现了没有
        # ——尤其卡片上同时有"卸载"按钮，两者挨在一起，容易看成没变。
        # 所以直接点名：停止按钮就在这张卡片上、按钮文字是什么。
        self._log("info", f"「停止」按钮已出现在这张卡片上（现在可用），"
                          f"再点一次可结束运行中的 {self.component.display_name}。")
        self._log_credentials()

    def _log_credentials(self) -> None:
        """把登录凭据打进组件日志（2026-10-06 用户要求）。

        凭据不算秘密了：这些是**厂商出厂默认**（nacos/nacos、admin/admin），
        任何装了同一个版本的人都是同一份。而 Jenkins 那种随机密码本来就在
        本机文件里、只有本机用户能读。它解决的是"服务起来了却登不进去，
        还要自己去翻文件/翻官方文档"——那才是真折腾。

        用 info 级而不是 warn 级：这不是风险提示，是用户现在就需要的信息。
        """
        spec = self.component.launch
        if spec is None:
            return
        try:
            port = self._launch_status().record.port \
                if self._launch_status().state == "running" else spec.main_port
        except Exception:
            port = spec.main_port
        try:
            for line in credentials_for(self.component, spec, port):
                self._log("info", line)
        except Exception as exc:            # 凭据读不出来不该影响启动结果
            self._log("warn", f"读取登录凭据失败（不影响使用）：{exc}")

    def _on_launch_notes(self, key: str, notes: list) -> None:
        """端口准备的告警逐条进组件日志。吞掉的话，用户之后想找"端口改在哪份文件里"
        只能自己猜 —— R4 第 6 条禁止的写法。"""
        for line in notes:
            self._log("warn", line)

    def _on_launch_failed(self, key: str, reason: str) -> None:
        # 关窗链路里 cancel 触发的 failed 可能在退出途中投递进来；模态框自己转事件循环，
        # 会把关窗卡住。只看顶层窗口（closeEvent 已立的 _closing 旗）是不是正在关。
        # try 包的是 self.window() 这次 Qt 调用本身：顶层 C++ 对象先没了它会抛 RuntimeError，
        # 而那时候连"记一条日志"的机会都没有 —— 那正是本方法要避免的静默失败。
        try:
            closing = getattr(self.window(), "_closing", False)
        except Exception:
            closing = True
        if closing:
            self._log("warn", f"操作未完成（窗口正在关闭）：{reason}")
            return
        self._log("error", f"操作失败：{reason}")
        QMessageBox.warning(self, "操作失败", reason)
        self._refresh_launch_state()

    def _on_need_force(self, key: str, reason: str) -> None:
        """停止超时/无法优雅结束：问一次，不自己决定强杀（spec §5）。"""
        if QMessageBox.question(self, "需要强制结束", reason,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            self._log("warn", "未强制结束，进程仍在运行。")
            return
        # need_force 是从 worker 线程里发的：这个槽跑的时候老 worker 的 run()
        # 可能还没返回，丢掉它最后一个引用会被 PySide 就地销毁还在跑的 QThread。
        # parent=self 把引用交给对象树持有，这条窗口才关得掉。
        self.launch_worker = LaunchWorker("force_stop", self.component,
                                          MainWindow.current_components(), SERVICE_MANAGER,
                                          parent=self)
        self.launch_worker.stopped.connect(self._on_launch_stopped)
        self.launch_worker.failed.connect(self._on_launch_failed)
        self.launch_worker.need_force.connect(self._on_need_force)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    def _on_launch_stopped(self, key: str) -> None:
        self._log("info", "已停止。")
        # 停止后也报一次凭据：用户常常是"启动→看一眼配置→再停止"这个顺序，
        # 停止这一刻他正要打开控制台，此刻给凭据最省事（日志滚动到底就能看到）。
        if self.component.launch is not None:
            self._log_credentials()
        self._refresh_launch_state()

    def _on_launch_worker_done(self) -> None:
        # 按身份收尾：老 worker 的 finished 可能晚于新 worker 起跑
        # （need_force 那条路上两条线程会短暂共存），无条件置 None 会把刚启动的
        # force_stop worker 的引用抹掉，强杀正在跑时反而没人持有它。
        worker = self.sender()
        if worker is self.launch_worker:
            self.launch_worker = None
        if worker is not None:
            worker.deleteLater()   # finished 之后删除是安全的：run() 已经返回
        self._refresh_launch_state()

    def on_start_stop_clicked(self) -> None:
        """启动/停止合并按钮的唯一入口：按当前实况决定做哪件事。

        判据用 `_launch_status()`（直接读端口实况），不用按钮上次的文字或启用态——
        那两个都可能被异步结果改过，用它们当依据就会出现"按钮写着启动、其实在跑"
        或者反过来，点一下做了错的事。
        """
        st = self._launch_status()
        if st.state == "running":
            self.on_stop_clicked()
        elif st.state == "zombie":
            # 僵尸登记（登记还在、端口没在听）：点按钮的意图是"清掉它重新起一个"，
            # 而不是"再停一次已经没在跑的东西"——那会让用户以为按钮坏了。
            self.on_start_clicked()
        else:
            self.on_start_clicked()

    def on_stop_clicked(self) -> None:
        self.btn_start.setEnabled(False)
        self.btn_start.setText("停止中…")
        self.launch_worker = LaunchWorker("stop", self.component,
                                          MainWindow.current_components(), SERVICE_MANAGER,
                                          parent=self)
        self.launch_worker.stopped.connect(self._on_launch_stopped)
        self.launch_worker.failed.connect(self._on_launch_failed)
        # 这条线不能省：停不下来时 need_force 就是"问一次"的唯一入口，
        # 漏接了按钮会直接停在"停止中"结束、用户既没被问也没结果。
        self.launch_worker.need_force.connect(self._on_need_force)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    def on_console_clicked(self) -> None:
        """打开访问页。

        **每个可启停组件都有一个能打开的地址**（2026-10-08 用户要求）：
          - 自带 Web 界面：它自己的控制台/首页（nginx 是 8888、tomcat 是 8081，
            都由登记表里的实际端口给出，不再写死 8080）；
          - 协议端口型（kafka / rocketmq / rabbitmq / ES）：工具自带的
            「启动成功」页，上面写着运行状态、端口、日志路径与访问方式。

        历史坑（2026-10-06）：nginx/tomcat 的 console_path 曾是 None，
        console_url 被拼成 `http://127.0.0.1:8080` → 点开必然 404，
        用户以为"启动成功是假的"。现在这两件都有真实首页，且对没有界面的组件
        改指自带页，不会再指到一扇不存在的门。
        """
        st = self._launch_status()
        if st.record is None:
            return
        target = st.record.console_url
        if not self._has_console():
            QMessageBox.information(
                self,
                f"{self.component.display_name} 没有网页控制台",
                f"{self.component.display_name} 不提供网页界面，"
                f"它的服务在端口 {st.record.port} 上（对局域网开放）。\n\n"
                f"要访问它请用对应的客户端工具，例如：\n"
                f"{self._no_console_hint()}")
            return
        QDesktopServices.openUrl(QUrl(target))

    def _has_console(self) -> bool:
        """该组件是否有可点的访问页。

        判据有两条（任一成立即可点）：
          ① 登记表里有 `console_path` —— 组件自带的 Web 界面/首页；
          ② 登记里的 `console_url` 指向本工具自带的「启动成功」页
             （协议端口型组件走这条，见 show_launch_page）。
        2026-10-08 之前只认①，于是 kafka/rocketmq/rabbitmq 的卡片上
        根本没有这个按钮 —— 而用户现在**要求**每件都有能打开的页面。
        """
        spec = getattr(self.component, "launch", None)
        if spec is None:
            return False
        if spec.console_path:
            return True
        try:
            st = self._launch_status()
        except Exception:
            return False
        return bool(st.record is not None and st.record.console_url)

    def _no_console_hint(self) -> str:
        """没有控制台时，给一句"这个组件该怎么用"的实话。

        **端口不能写死**（2026-10-08 改正）：原来这里写着 8080，而 tomcat 实际是
        8081、nginx 是 8888 —— 一句写错端口的指引比不给指引更坏，用户会照它去连
        一个根本没人听的端口。现在按登记表里的 main_port 现算。
        """
        spec = getattr(self.component, "launch", None)
        port = getattr(spec, "main_port", None) or "?"
        return {
            "tomcat": f"把 WAR 放进 ~/.env-tools/tomcat-data/webapps/ 后访问 "
                      f"http://127.0.0.1:{port}/应用名/（放安装目录那份不生效）",
            "nginx": f"默认站点在 ~/.env-tools/nginx-data/html/ 下，"
                     f"访问 http://127.0.0.1:{port}/",
            "elasticsearch": f"用 curl 访问 http://127.0.0.1:{port}/（图形界面 Kibana 不在本工具里）",
            "kafka": "用 kafka-topics.bat（安装目录 bin/windows/ 下）之类的命令行工具操作",
            "rocketmq": "用 mqadmin（安装目录 bin/ 下）命令行工具操作",
            "rabbitmq": "管理界面需要额外开 rabbitmq_management 插件，本工具暂未启用",
        }.get(self.component.key, "请用对应的客户端工具访问")

    # ------------------------------------------------------------------
    def _render_status_label(self) -> None:
        if self.component.multi_version and self._mv_capsule:
            # 多版本胶囊正文取 _detect_status 已算好的基础文案（逐字不变），异步版本号
            # 只在其后追加；绿=有生效版本（_status_shows_configured），橙=均未生效/未对齐。
            # _mv_capsule 为空串表示这次走的是"本工具没装过、探测到系统安装"的通用分支，
            # 那时必须落到下面的 ✓ 已配置 文案，不能渲染一个空胶囊。
            # 短串与全量原文同步续上版本号：主文本只放得下结论，版本列表在 tooltip 里。
            text = self._mv_capsule
            # 外部只塞了胶囊全文（没算过短串）时退回全量，主文本不许是空的
            short = self._mv_capsule_short or self._mv_capsule
            if self._status_version:
                text += f" · {self._status_version}"
                short += f" · {self._status_version}"
            self._set_status(text, short)
            self.status_label.setStyleSheet(
                "color:#ef6c00;font-weight:600;padding:2px 8px;"
                "background:#fff3e0;border-radius:10px;"
                if self._mv_orange or not self._status_shows_configured else
                "color:#2e7d32;font-weight:600;padding:2px 8px;"
                "background:#e8f5e9;border-radius:10px;")
            return

        text = f"✓ 已配置（{self._status_where}）"
        short = f"✓ 已配置 · {self._short_where()}"
        if self._status_version:
            text += f" · {self._status_version}"
            short += f" · {self._status_version}"
        elif self.component.version_probe:
            text += " · 版本检测中…"
            short += " · 检测中…"
        self._set_status(text, short)
        self.status_label.setStyleSheet(
            "color:#2e7d32;font-weight:600;padding:2px 8px;"
            "background:#e8f5e9;border-radius:10px;"
        )

    def _short_where(self) -> str:
        """主文本里那截"来源"要短（格子只有 271px），完整出处留给 tooltip。

        多版本组件走到通用分支 = 本工具一个版本都没装、探测到的是用户自己装的，
        主文本只说「系统安装」；"不由本工具管理"这个结论在 tooltip 的全量原文里。
        """
        if self.component.multi_version:
            return "系统安装"
        return self._status_where or "系统"

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
    def _installed_here(self, version: str) -> Optional[Path]:
        """该版本是否真的装好了：装好返回安装目录，否则 None。

        只看目录存在不够 —— 解压一半失败也会留下目录，那时按钮灰掉、
        卸载又删不出东西，用户就被卡死了。所以还要在里面找得到该组件的可执行文件；
        没有 exec_name 的组件（Jenkins 只有一个 war 包）退化成"目录非空"。
        """
        home = self.component.install_dir(version)
        if not home.is_dir():
            return None
        if self.component.exec_name:
            return home if self.component.exec_path_in_home(str(home)) else None
        return home if any(home.iterdir()) else None

    # ------------------------------------------------------------------
    def _sync_action_buttons(self) -> None:
        """按「当前选中的版本」重算三个按钮：下载并安装 / 切换生效 / 卸载。

        三个触发点：① _detect_status 之后；② 下拉框换选中之后；
        ③ 下载结束或失败之后。只挂 ① 会出真机 bug —— 切一次生效版本后按钮置灰，
        用户换选另一个版本没人重算，按钮一直灰着点不动（2026-09-30 反馈）。
        """
        # 下载途中按钮归下载流程管：否则换个选中就能并发触发第二次下载
        if not (self.worker and self.worker.isRunning()):
            selected = self._current_version().version
            home = self._installed_here(selected)
            self.btn_install.setEnabled(home is None)
            self.btn_install.setToolTip(
                f"该版本已安装在 {home}；要重新安装请先点「卸载」" if home else
                "下载该版本并解压安装到本工具工作目录")
        if not self._mv_buttons_ready:
            return
        # 未对齐/被遮蔽时切换按钮必须可用：哪怕 selected 恰好等于 active，
        # 也得让用户能再点一次去收敛 PATH 与登记表
        selected = self._current_version().version
        can_switch = selected != self._mv_active or self._mv_warned
        self.btn_configure.setEnabled(can_switch)
        self.btn_configure.setToolTip(
            "把下拉框选中的版本设为生效版本：改 XXX_HOME，并把本组件在 PATH 里的"
            "条目收敛成这一条；已开着的终端需重开才生效"
            "（Windows Terminal 的新标签页、IDE 里的新终端都还是旧环境，要整个关掉重开）"
            if can_switch else
            f"选中的 {selected} 已是生效版本；要换版本先在下拉框里选中")
        # 卸载按钮只对"已装的选中版本"启用：tooltip 承诺卸载选中的那个，
        # 而 selected 完全可能没装——放行会走 resolve 兜底删掉用户没选中的版本。
        if selected in self._mv_installed_set:
            # 运行中（被启动锁过）不许重新点亮卸载：切换版本下拉框也会走到这里，
            # 无条件启用会让按钮和"● 运行中"的文案在同一张卡上自相矛盾。
            self.btn_uninstall.setEnabled(not self._uninstall_locked_by_launch)
            self.btn_uninstall.setToolTip(
                f"卸载下拉框选中的 {selected}：只删该版本目录与它的 PATH 条目，"
                "其他已装版本不动")
        else:
            self.btn_uninstall.setEnabled(False)
            self.btn_uninstall.setToolTip(
                f"选中的 {selected} 未安装；要卸载其他版本先在下拉框里选中"
                "（下拉框里有绿勾的就是已装）")

    # ------------------------------------------------------------------
    def _show_external_capsule(self, takeover: dict, ordered, residue) -> bool:
        """接管外部版本时的状态胶囊（设计 §6 第三档）。返回 True = 已接管显示。

        为什么必须单独一档：接管生效期间 active 登记按 §4.3 已被删除，走原来那条
        "本工具装了哪个版本生效"的分支只会报成"均未生效"，与实际情况正好相反。
        """
        home = Path(str(takeover.get("home") or ""))
        ver = str(takeover.get("version") or "?")
        names = "、".join(v for v, _p in ordered)
        green = ("color:#2e7d32;font-weight:600;padding:2px 8px;"
                 "background:#e8f5e9;border-radius:10px;")
        orange = ("color:#ef6c00;font-weight:600;padding:2px 8px;"
                  "background:#fff3e0;border-radius:10px;")

        if not home.is_dir():
            # §7：快照指向的目录被用户删了 —— 如实说，**不自动改环境**，
            # 只提示可以点还原或另选一个。
            capsule = (f"● 之前接管的外部版本已不存在（{home}）· 请点「还原到我之前的设置」"
                       "或改选别的版本")
            short = "● 接管的外部版本已不存在"
            warned = True
        else:
            tail = (f" · 工作区 {len(ordered)} 个版本（{names}）" if ordered
                    else " · 工作区没有装版本")
            level = "系统" if str(takeover.get("level")) == "machine" else "用户"
            capsule = f"● 生效 {ver}（{level} {home}）{tail}"
            short = f"● 生效 {ver}（{level}级）"
            warned = False
        if residue:
            capsule += f" · 另有 {len(residue)} 个残留空目录待清理"
            short += f" · {len(residue)} 个残留待清理"
            warned = True

        self._mv_capsule = capsule
        self._mv_capsule_short = short
        self._mv_orange = warned
        self._set_status(capsule, short)
        self.status_label.setStyleSheet(orange if warned else green)
        # active 置空：切换按钮据此恒为可用（用户要能切回工作区版本，
        # _apply_active 会先走 release_external_before_workspace_switch 还原）。
        self._mv_active = None
        self._mv_warned = warned
        self._mv_installed_set = ({v for v, _p in ordered}
                                  | {v for v, _p in residue})
        self._mv_buttons_ready = True
        self._sync_action_buttons()
        self._status_shows_configured = False
        self._status_version = ""
        self._version_worker = None
        self._refresh_installed_marks()
        return True

    def _detect_status(self) -> None:
        """检测组件状态，并在每条出口后刷新一遍运行态。

        _detect_status_impl 有四条出口（多版本胶囊 / 已配置 / 已下载 / 未安装），把
        `_refresh_launch_state()` 写在物理末尾只会覆盖最后那条；包一层才能保证
        "每次重探状态都顺带把启动/停止/卸载按钮对齐端口实况"。
        """
        self._detect_status_impl()
        self._refresh_launch_state()

    def _detect_status_impl(self) -> None:
        """检测该组件当前是否已安装、已配置。

        - 若系统 PATH 或 XXX_HOME 已能找到可执行文件，则视为「已配置」，禁用
          「仅配置环境变量」按钮，避免重复写入。
        - 若本地已解压但未配置，则允许点击「仅配置环境变量」。
        - 若未安装，两个按钮均可用。

        本方法在窗口构建卡片时就会被调用，因此绝不同步执行组件命令：detect 只判定
        存在（probe_version=False），版本号交给 VersionProbeWorker 异步回填。
        """
        # 「下载并安装」的启用状态只取决于选中的版本装没装好，与后面走哪条探测分支无关，
        # 所以在分支之前先同步一次；多版本那两个按钮要等本方法算出 active 之后再同步。
        self._sync_action_buttons()
        # 多版本组件：状态胶囊要表达的是"装了哪几个 + 哪个生效"，
        # 而不是单一的"已配置/未配置"；生效以 active 登记表为准，探测只用于回填版本号。
        if self.component.multi_version:
            ordered = installed_versions(self.component)
            residue = residue_install_dirs(self.component)
            # 磁盘上的已装集合刚变过（装完/卸完），"已装但清单里没有"的合成项要跟着增减。
            # 必须放在 `if ordered` 之前：最后一个额外版本被卸掉时 ordered 为空，
            # 会直接落到下面的通用探测分支，放里面就永远摘不掉那一行。
            if self.version_combo.count() != len(self._combo_version_list()):
                self._reload_combo_items(preferred=self.version_combo.currentText())
            # 接管了外部版本的一档（§6）：这个时候 active 登记已被删除，不能按
            # "本工具装了哪个版本生效"去显示，否则会报成"均未生效"。
            if supports_external_takeover(self.component):
                self._refresh_external_section()
                takeover = load_takeover_map().get(self.component.key)
                if takeover:
                    if self._show_external_capsule(takeover, ordered, residue):
                        return
            # 只有"本工具目录下确实装着版本"时才走多版本胶囊。一个都没有时不许就此断言
            # "未安装"——用户很可能自己装了 JDK/Maven（JAVA_HOME 或 PATH 里就有），
            # 那要交给下面的通用探测识别成"已配置（系统安装）"。
            if ordered:
                home_ver = (load_active_map().get(self.component.key)
                            or infer_active_from_env(self.component))
                path_ver = self._path_hit_version()
                active = home_ver or path_ver
                # HOME 与 PATH 指向不同版本时，命令行实际用的是 PATH 那个；只报 HOME 里的
                # 就是骗人（2026-09-30 真机：bun 1.4.2 与 1.4.1 同时留在 PATH 里）。
                mismatch = bool(home_ver and path_ver and home_ver != path_ver)
                # 复验"新终端实际会命中谁"：被 PATH 里更靠前的条目（系统级变量、用户自装的
                # 版本）压住时，不许只写"生效 X"——那正是本机 jdk 的处境。
                verdict, shadow = self._path_effective_check(active)
                warned = mismatch or verdict == "shadowed"
                names = "、".join(v for v, _p in ordered)
                short = ""
                if mismatch:
                    capsule = (f"● 已装 {len(ordered)} 个版本 · 未对齐：PATH 用的是 {path_ver}，"
                               f"{self.component.env_var or '环境变量'} 指 {home_ver}（{names}）")
                    short = "● 未对齐（PATH≠HOME）"
                elif verdict == "shadowed":
                    capsule = (f"● 已装 {len(ordered)} 个版本 · 生效 {active}（{names}）"
                               f" · 但 PATH 先命中 {shadow}")
                    short = (f"● 已装 {len(ordered)} 个 · 生效 {active}"
                             f" · 被 PATH 抢先")
                else:
                    tail = f" · 生效 {active}" if active else " · 均未生效"
                    capsule = f"● 已装 {len(ordered)} 个版本{tail}（{names}）"
                    short = f"● 已装 {len(ordered)} 个{tail}"
                if residue:
                    # 磁盘上还有内容被删空的目录：必须报出来，否则它既不算已装、
                    # 又没人知道要清理，就成了永久死角（胶囊是用户唯一的入口线索）。
                    warned = True
                    capsule += f" · 另有 {len(residue)} 个残留空目录待清理"
                    short += f" · {len(residue)} 个残留待清理"
                self._mv_capsule = capsule
                self._mv_capsule_short = short
                self._mv_orange = warned
                self._set_status(capsule, short)
                self.status_label.setStyleSheet(
                    "color:#ef6c00;font-weight:600;padding:2px 8px;"
                    "background:#fff3e0;border-radius:10px;" if warned or not active else
                    "color:#2e7d32;font-weight:600;padding:2px 8px;"
                    "background:#e8f5e9;border-radius:10px;")
                selected = self._current_version().version
                # 按钮启用状态交给 _sync_action_buttons()：它还有第二个触发时机 ——
                # 下拉框换选中。只挂在这里会出真机 bug（2026-09-30）：切一次之后按钮置灰，
                # 用户换选另一个版本，没人重算，按钮一直灰着点不动。
                self._mv_active = active
                self._mv_warned = warned
                self._mv_installed_set = ({v for v, _p in ordered}
                                          | {v for v, _p in residue})
                self._mv_buttons_ready = True
                self._sync_action_buttons()
                # 探测回填只在确有生效版本、且没有未对齐时开放闸门，并把上一轮
                # 生效版本回填过的旧版本号清掉——否则切完版本胶囊还挂着 21.0.4。
                self._status_shows_configured = bool(active) and not mismatch
                self._status_version = ""
                # 作废上一轮探测线程的迟到回调：_on_version_probed 靠 worker 身份挡旧回包，
                # 不清旧 _version_worker 的话，旧 worker 回来会把上一轮生效版本的旧版本号
                # 贴进这一轮的新胶囊里，永久错标。
                self._version_worker = None
                if not mismatch:
                    for ver, path in ordered:
                        if ver == active:
                            # 复用既有寻径（会试 bin/、根目录、.bat/.cmd 等），别自己拼路径
                            exe = self.component.exec_path_in_home(str(path))
                            if exe:
                                self._schedule_version_probe(str(exe))
                            break
                self._refresh_installed_marks()
                return
            elif residue:
                # 只剩空壳目录（真机 2026-10-07 rabbitmq 的收尾状态）：说"未安装"是假话
                # ——磁盘上确实有个删不掉的目录；说"已装"也是假话 —— 里面一个文件都没有。
                # 所以这一支单独说清"残留待清理"，并且**不能**落到下面的通用探测分支：
                # 那一支会按 PATH/HOME 判定，而空壳的 HOME 刚被这次卸载清掉，
                # 结果是卡片显示"未安装"、卸载按钮置灰，那个目录就永远清不掉了。
                vers = "、".join(v for v, _p in residue)
                capsule = (f"● {len(residue)} 个残留空目录待清理（{vers}）"
                           f" · 内容已删除、不算已装")
                self._mv_capsule = capsule
                self._mv_capsule_short = f"● {len(residue)} 个残留待清理"
                self._mv_orange = True
                self._set_status(capsule, self._mv_capsule_short)
                self.status_label.setStyleSheet(
                    "color:#ef6c00;font-weight:600;padding:2px 8px;"
                    "background:#fff3e0;border-radius:10px;")
                self._mv_active = None
                self._mv_warned = True
                self._mv_installed_set = {v for v, _p in residue}
                self._mv_buttons_ready = True
                self._sync_action_buttons()
                self._status_shows_configured = False
                self._status_version = ""
                self._version_worker = None
                self._refresh_installed_marks()
                return

        result = self.component.detect(probe_version=False)
        # 通用分支（非多版本组件、或多版本组件但本工具没装过）自己管按钮状态，
        # 必须关掉多版本按钮同步，否则下拉框一换选中就把这里设好的状态改回去。
        self._mv_buttons_ready = False
        self._status_shows_configured = bool(result.installed)
        if result.installed:
            where = result.source or "系统"
            if self.component.multi_version:
                # 多版本组件走到这里 = 本工具没装过任何版本，探测到的是用户自己装的。
                # 不写清楚的话，用户会以为这枚"已配置"是本工具装的，找不到切换入口。
                where = f"{where} · 系统安装，不由本工具管理"
            self._status_where = where
            self._status_version = ""
            # 走通用分支 = 本工具没装过这个组件，多版本胶囊不适用；清空它，
            # 否则 _render_status_label 会渲染上一轮留下的旧胶囊。
            self._mv_capsule = ""
            self._mv_capsule_short = ""
            self._render_status_label()
            # 已可用 —— 禁用「仅配置环境变量」按钮
            self.btn_configure.setEnabled(False)
            self.btn_configure.setToolTip(
                f"系统已能检测到 {self.component.display_name}"
                f"（{result.exe_path or where}），无需再次配置。"
            )
            # 已配置状态下允许卸载（仅能清理由本工具写入的 XXX_HOME/PATH marker）
            if self.component.multi_version:
                # 走到这里 = 本工具一个版本都没装，探测到的是用户自己装的。
                # 放开卸载按钮只会给出一个做不到的承诺（真点下去也只会回"未找到安装目录"）。
                self.btn_uninstall.setEnabled(False)
                self.btn_uninstall.setToolTip(
                    "系统里这个是你自己装的，本工具不代为卸载。想交给本工具管理并在多个"
                    "版本间切换，先在下拉框选一个版本点「安装」。")
            else:
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
            # 主文本已经够短，不需要 tooltip 复述；显式清空，免得留下上一轮胶囊的详情
            self._set_status("", "● 已下载，未配置")
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

        self._set_status("", "○ 未安装")
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

    def _combo_version_list(self) -> List[ComponentVersion]:
        """下拉框真正要显示的清单：内置/在线清单 + 磁盘已装但清单里没有的版本。

        必须合成是因为在线清单只保留近期版本（2026-09-30 真机：bun 清单里已无 1.4.1，
        磁盘上却装着），否则会出现"胶囊说已装 2 个版本、下拉框里只有 1 个能选"——
        那个版本切不了也卸不掉。合成项没有下载 URL，但"已装即置灰安装按钮"正好兜住。

        **所有组件都合成，不再只对多版本组件**（2026-10-06 改）。原先非多版本组件
        直接 return 候选清单，但它们的清单同样会落后于实际安装版本：jenkins 候选是
        2.568.3/2.555.3/2.541.3，磁盘上装的是 2.580.1—— 不合成的话那个已装版本
        在下拉框里根本不存在，用户看到的是"装了东西但下拉框里没有它、也没有绿勾"，
        而启动走 `resolve_launch_version()` 会去找已装的那个，两边对不上。
        R3.9 那句"非多版本组件清单逐字不变"约束的是**不能凭空造版本**，
        不是"不许把真装了的版本显示出来"—— 后者正是本条要修的。
        """
        result = list(self.component.versions)
        known = {cv.version for cv in result}
        # 已装的 + 只剩空壳的都合成进来：空壳必须还能被选中并卸载，
        # 否则它既不算已装、又不在下拉框里，就没人能清掉它（residue_install_dirs 的用途）。
        on_disk = [v for v, _p in installed_versions(self.component)]
        on_disk += [v for v, _p in residue_install_dirs(self.component)]
        extras = [v for v in dict.fromkeys(on_disk) if v not in known]
        for ver in extras:
            cv = ComponentVersion(version=ver, url_map={}, archive_map={})
            key = _semver_key(ver)
            pos = len(result)
            for i, existing in enumerate(result):
                if _semver_key(existing.version) < key:
                    pos = i
                    break
            result.insert(pos, cv)
        return result

    def _refresh_installed_marks(self) -> None:
        """给磁盘上已装的版本挂绿勾；只动 DecorationRole，不碰条目文本。

        为什么不写成文本前缀：下拉框条目文本是版本反查的唯一键（_current_version /
        repopulate(preferred=…) 都按 currentText 匹配），加「✓」会让选版、安装、
        卸载与配置保存全部错位。图标是纯装饰数据，不参与任何反查。

        **所有组件都挂，不分multi_version**（2026-10-06 改）。原先这里对
        `multi_version=False` 的组件直接 return，理由是"它们没有版本并存的概念"——
        但下拉框里照样列了具体版本（如 tomcat 9 / nginx 1.26），用户装完一个版本后
        那个版本就该被标出来，否则"我装的是哪个"只能靠记忆。实测：python 有勾而
        jenkins / nacos / activemq / powershell 全都没有，正是这个 return 造成的。
        `multi_version` 只管"能不能多版本并存"（R3 语义），不该管"要不要显示已装"。
        """
        versions = self._combo_version_list()
        # F4 护栏：下面的循环按 enumerate(versions) 的行号往 combo 写数据，前提是
        # 行数与下拉框清单 1:1。哪天有调用点在改清单的同时没重灌 combo（搜索过滤、
        # repopulate 时机变化），按位写会写歪或直接 IndexError——宁可这一轮不刷勾，
        # 也不写歪：行数不齐就整轮跳过。
        if self.version_combo.count() != len(versions):
            return
        installed = {v for v, _p in installed_versions(self.component)}
        icon = _installed_icon()
        empty = QIcon()
        for i, cv in enumerate(versions):
            self.version_combo.setItemData(i, icon if cv.version in installed else empty,
                                           Qt.DecorationRole)

    # ------------------------------------------------------------------
    def _reload_combo_items(self, preferred: Optional[str] = None) -> None:
        """把下拉框清单（含"已装但清单里没有"的合成项）灌进 combo，并重挂"已装"图标。"""
        versions = self._combo_version_list()
        labels = [self._display_label(v) for v in versions]
        # 若首次调用（combo 里还没内容），走普通 addItems 路径
        if self.version_combo.count() == 0:
            self.version_combo.blockSignals(True)
            self.version_combo.addItems(labels)
            # 默认选中**已安装的那个**，不是清单第一项（真机 2026-10-06 查出来的）。
            # 离线候选清单会落后于实际安装版本：jenkins 候选首位 2.568.3、实装 2.580.1，
            # 无条件选第一项会让下拉框停在一个没装的版本上——绿勾全是空的、
            # 点"配置环境变量"或"卸载"会对着不存在的目录动手。
            # 找不到任何已装版本时才退回第一项（首装场景就该选清单首位）。
            idx = 0
            installed = {v for v, _p in installed_versions(self.component)}
            for i, cv in enumerate(self._combo_version_list()):
                if cv.version in installed:
                    idx = i
                    break
            self.version_combo.setCurrentIndex(idx)
            self.version_combo.blockSignals(False)
            self.version_combo._committed_text = self.version_combo.currentText()
            self._refresh_installed_marks()
            return
        self.version_combo.repopulate(labels, preferred=preferred)
        # repopulate 内部 clear() 会连带销毁旧条目的 DecorationRole 数据，
        # 所以装载出口的两条路径都得重挂一次，否则抓取线程回填版本后标记全丢。
        self._refresh_installed_marks()

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
        """按显示 label 反查真实版本，兼容 SearchableComboBox 的可编辑文本。

        必须与 `_reload_combo_items` 用同一份清单（含"已装但清单里没有"的合成项）：
        两处不一致时，下拉框里明明显示着某个版本，反查却落回第一项，
        用户以为在切 1.4.1、实际配出去的是 1.4.2。
        """
        text = self.version_combo.currentText().strip()
        versions = self._combo_version_list()
        for cv in versions:
            if self._display_label(cv) == text or cv.version == text:
                return cv
        idx = max(0, self.version_combo.currentIndex())
        return versions[min(idx, len(versions) - 1)]

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
            # 落位实现只有一处（模块级 install_downloaded）：界面与真机演练走同一条路径，
            # 演练绿灯才等价于"用户点下去会成功"。
            final = install_downloaded(self.component, cv.version, path,
                                       _LoggerAdapter(self._log))
            self._extracted_path = final
            # 自动尝试配置环境变量
            self._configure_after_extract(final)
        except Exception as exc:
            self._log("error", f"安装/配置失败：{exc}\n{traceback.format_exc()}")
        finally:
            # 按钮状态统一交给 _sync_action_buttons（已装的版本不许被重新点亮）
            self.btn_configure.setEnabled(True)
            self._sync_action_buttons()
            # 装成功与否都会在磁盘上留下（或不留）目录，勾的有无正由磁盘决定，
            # 这里统一刷新一次，省得在两个分支各写一遍。
            self._refresh_installed_marks()
            # _detect_status 会根据探测结果再决定 btn_configure 是否禁用
            self._detect_status()

    # ------------------------------------------------------------------
    def _run_installer(self, installer_path: Path, target_dir: Path) -> None:
        """静默运行安装器（用于 Miniconda 之类）。实现见模块级 _run_installer_for。"""
        _run_installer_for(self.component, installer_path, target_dir, self._log)

    # ------------------------------------------------------------------
    def _on_download_fail(self, msg: str) -> None:
        self.btn_configure.setEnabled(True)
        self._sync_action_buttons()
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
        # spec §5 运行中禁止卸载。按钮置灰是第一道，这里是第二道：置灰状态可能被
        # 其它同步路径顶掉，而"边跑边删目录"删掉的正是服务进程正在写的日志与数据。
        if self.component.launch is not None and \
                SERVICE_MANAGER.status(self.component.key, self.component).state == "running":
            reason = "请先停止运行中的 %s 再卸载" % self.component.display_name
            self._log("warn", reason)
            QMessageBox.warning(self, "无法卸载", reason)
            self._refresh_launch_state()
            return
        cv = self._current_version()
        # 二次确认：卸载会删除本地目录、清理环境变量与 PATH，不可逆。
        # 正文（"删哪些" + "数据去哪儿"）由纯函数 uninstall_confirm_text 统一拼，
        # 后者按组件区分数据去处 —— 计划一那句对 Nacos 是半句真话。
        # 确认框尾巴按组件是否多版本分叉：多版本现在只动选中的那个版本，
        # 旧的"以实际装着的目录为准"在多选并存场景下会变成假话；
        # 非多版本组件的原文逐字保持不变。
        tail = ("（只删除选中的这一个版本，其他已装版本不动；"
                "若删掉的正是当前生效版本，会自动切到剩余里版本号最高的那个）"
                if self.component.multi_version else
                "（若所选版本与实际安装版本不一致，会以实际装着的目录为准）")
        reply = QMessageBox.question(
            self,
            "确认卸载",
            f"确定要卸载 {self.component.display_name} {cv.version} 吗？\n\n"
            f"将执行以下操作：\n"
            f"{uninstall_confirm_text(self.component)}\n\n"
            f"{tail}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._log("info", f"已取消卸载 {self.component.display_name} {cv.version}")
            return
        try:
            # R3.19：若之前为了让**这个版本**生效而提权改过系统变量，先按原文还原再删目录。
            # 不还原的话，系统 PATH 最前会留下一条指向即将消失的目录的死条目 ——
            # 那比"没生效"更糟：全机所有程序的 PATH 里都多一条失效路径。
            fix_entry = load_machine_fix_map().get(self.component.key)
            if fix_entry and EnvManager._same_path(
                    str(fix_entry.get("home") or ""),
                    str(self.component.install_dir(cv.version))):
                back = revert_machine_fix(
                    self.component,
                    log=lambda m: self._log("error" if ("失败" in m or "未完成" in m)
                                            else "info", m))
                for step in back.get("steps") or []:
                    self._log("info", step)
                if not back.get("ok"):
                    self._log("error", "系统变量还原未完成，已中止卸载以免留下失效条目："
                              + str(back.get("error") or ""))
                    return
                self._refresh_external_section()
            self._log("info", f"开始卸载 {self.component.display_name} {cv.version}")
            # 调用 Component.uninstall 执行实际卸载，返回中文摘要
            summary = self.component.uninstall(cv.version)
            self._log("ok", f"卸载完成：{summary}")
            # 磁盘上少了一个版本目录，下拉框里它的勾必须同时消失
            self._refresh_installed_marks()
            # 卸载后重新检测状态，刷新状态胶囊与按钮启用状态
            self._detect_status()
        except Exception as exc:
            self._log("error", f"卸载失败：{exc}")

    # ------------------------------------------------------------------
    def _path_hit_version(self) -> Optional[str]:
        """按 PATH 顺序找出命令行**实际**会命中的"本工具装的那个版本"。

        读的是持久层 PATH（新开终端真正会用到的那份），不是 os.environ —— 后者只是本进程
        启动时的快照，可能被之前的安装/切换改脏。找不到属于本组件的条目时返回 None。
        """
        comp = self.component
        if not comp.exec_name:
            return None
        root = str(CONFIG_DIR / comp.key)
        names = [comp.exec_name]
        if CURRENT_OS == "Windows" and not os.path.splitext(comp.exec_name)[1]:
            names = [comp.exec_name + s for s in (".exe", ".cmd", ".bat", "")]
        for entry in EnvManager.read_user_path_entries():
            if not EnvManager._under_root(entry, root):
                continue
            for ver, path in installed_versions(comp):
                bin_dir = (path / comp.path_subdir) if comp.path_subdir else path
                if not EnvManager._same_path(str(bin_dir), entry):
                    continue
                for name in names:
                    if (bin_dir / name).exists():
                        return ver
        return None

    def _expected_bin_dir(self, version: str) -> Path:
        """生效版本"应当"出现在 PATH 里的那个目录（写变量与复验共用一套算法）。"""
        home = self.component.install_dir(version)
        return home / self.component.path_subdir if self.component.path_subdir else home

    def _path_effective_check(self, active: Optional[str]) -> Tuple[str, Optional[str]]:
        """复验：按系统合成的 PATH 顺序，命令行第一个命中的目录是不是生效版本该在的那个。

        返回 ("ok", None) | ("shadowed", 抢走命令的目录) | ("unknown", None)。
        unknown 含"拿不到合成环境"和"PATH 里根本没有这个命令"两种，都不许当成通过：
        前者是没测，后者说明命令压根不在 PATH 上。

        为什么必须有这一步（2026-09-30 真机实测）：用户 PATH 整体排在系统 PATH 之后，
        且系统 PATH 里的 %JAVA_HOME%\\bin 是按**系统**表展开定死的 —— 我们把
        JAVA_HOME 与自己的 PATH 条目都写对了，命令行仍可能命中用户自装的那个版本。
        只报"已切到 X"就是假话。
        """
        if not active or not self.component.exec_name:
            return "unknown", None
        composed = EnvManager.composed_env()
        path_value = composed.get("PATH")
        if not path_value:
            return "unknown", None
        exec_name = self.component.exec_name
        names = ([exec_name] if CURRENT_OS != "Windows"
                 else ([exec_name + s for s in (".exe", ".cmd", ".bat", "")]
                       if not os.path.splitext(exec_name)[1] else [exec_name]))
        expected = str(self._expected_bin_dir(active))
        for entry in path_value.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            try:
                hit = any(os.path.exists(os.path.join(entry, n)) for n in names)
            except (OSError, ValueError):
                continue
            if hit:
                return ("ok", None) if EnvManager._same_path(entry, expected) else ("shadowed", entry)
        return "unknown", None

    def active_version(self) -> Optional[str]:
        """当前生效版本：active 登记表 → 持久层 XXX_HOME 反推 → PATH 实际命中。

        第三级兜底是必要的：老配置既没登记表、HOME 又被手工清过时，PATH 里那条
        本工具写入的条目就是唯一的事实来源。
        """
        if not self.component.multi_version:
            return None
        return (load_active_map().get(self.component.key)
                or infer_active_from_env(self.component)
                or self._path_hit_version())

    def _log_verification_hint(self, since_epoch: Optional[float] = None) -> None:
        """切换后给出可直接复制的校验命令，并点名"比这次切换更早、还开着的终端"。

        写这么细是因为真实踩过的坑：Windows 是把环境块**复制**给新进程的，
        Windows Terminal 的新标签页、IDE 里新开的终端都还继承着宿主进程那份旧环境。
        用户按"重开终端"的字面意思操作，看到的仍然是切换前的版本，
        于是以为切换没生效（2026-09-30 真机反馈）。
        只讲道理没用——同一天实测：注册表与新进程都是 1.4.1，用户屏幕上那个
        PowerShell 进程创建于切换前 12 分钟。所以这里直接把 pid 和起始时间摆出来。
        """
        exe = self.component.exec_name or ""
        args = " ".join(self.component.version_args or ["--version"])
        lines = ["校验是否真生效（必须在切换之后新启动的终端里跑）："]
        if exe:
            lines.append(f"    where {exe}      ← 应当指向上面那个目录")
            lines.append(f"    {exe} {args}")
        if self.component.env_var:
            lines.append(f"    echo %{self.component.env_var}%      ← cmd 里看变量值")
        lines.append("不想重开，可以在当前 PowerShell 里先刷新再验：")
        lines.append("    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')"
                     " + ';' + [Environment]::GetEnvironmentVariable('Path','User')")
        lines.append("注意：Windows Terminal 的新标签页、IDE 里新开的终端都还是旧环境，"
                     "要把整个 Windows Terminal / IDE 关掉重开。")
        if since_epoch:
            try:
                procs = list_shell_processes()
            except Exception:
                procs = []
            lines.extend(stale_shell_lines(procs, since_epoch, os.getpid()))
        self._log("info", "\n".join(lines))

    # ------------------------------------------------------------------
    def _apply_active(self, version: str) -> bool:
        """把指定版本设为生效版本；成功后写登记表并刷新界面。

        返回: bool  成功与否。失败原因已在日志里，界面不再处理异常。

        刷新已装勾是必要的：apply_active_version 中途失败会回滚磁盘/环境状态，
        生效版本变了也可能连带影响状态探测读到的目录，图标得跟磁盘重新对齐。
        """
        t_switch = time.time()
        # §4.3 两条键互斥 + R3.19：接管过外部版本、或为系统变量做过提权改动时，
        # 都要先原样还原再切工作区版本，否则系统 PATH 最前还插着旧那条，
        # 切完命令行仍是旧版本。
        release = release_machine_state(
            self.component, log=lambda m: self._log("info", m),
            reason="切回工作区版本")
        for step in release.get("steps") or []:
            self._log("error" if ("失败" in step or "未完成" in step) else "info", step)
        if not release.get("ok"):
            self._log("error", "接管/系统变量还原未完成，已中止本次切换以免留下半截状态："
                      + str(release.get("error") or ""))
            return False
        try:
            steps = apply_active_version(self.component, version)
        except SwitchError as exc:
            self._log("error", str(exc))
            return False
        for step in steps:
            self._log("error" if ("失败" in step) else "ok", step)
        save_active_version(self.component.key, version)
        # 写完必须复验"新终端实际会命中谁"：PATH 是系统段 + 用户段拼出来的，
        # 我们写的是用户段，完全可能被前面那条（用户自装的版本）压住。
        verdict, shadow = self._path_effective_check(version)
        if verdict == "ok":
            self._log("ok", f"复验通过：新开的终端会用到 {self._expected_bin_dir(version)}")
            self._log_verification_hint(t_switch)
        elif verdict == "shadowed":
            self._handle_shadowed_after_switch(version, shadow, t_switch)
        else:
            self._log("warn", "未能复验新终端会用到哪个目录（拿不到系统合成后的环境），"
                              "请重开一个终端手动确认一次。")
            self._log_verification_hint(t_switch)
        self._refresh_installed_marks()
        self._detect_status()
        return True

    def _handle_shadowed_after_switch(self, version: str, shadow: Optional[str],
                                      since_epoch: float) -> None:
        """切换后仍被更靠前的目录压住时，**能自己解决的就自己解决**（R3.19）。

        判据是"抢命令的那条写在哪一段"（shadow_location），不是猜：
          · 写在用户段 → 把我们那条让到用户段最前即可，**零提权**；
          · 写在系统段 → 用户级永远压不住，问一次是否用管理员权限插到系统段最前；
          · 两段都找不到 → 只如实报告，不提权（改系统变量也未必对症）。
        前两步只在白名单组件上做：那是"要不要动用户机器 PATH"的显式白名单，
        非白名单组件维持"只报告"的老行为（R3.17 的同一道闸）。
        """
        exec_name = self.component.exec_name or ""
        expected = str(self._expected_bin_dir(version))
        head = (f"环境变量已切到 {version}，但复验发现新终端里 {exec_name} 仍会先命中 "
                f"{shadow} —— 它排在 PATH 更前面（多半是系统级变量或你自己装的版本）。")
        where = shadow_location(str(shadow or "")) if shadow else "outside"
        whitelisted = supports_external_takeover(self.component)

        # ① 用户段内部还有救：把我们那条让到用户段最前，再复验一次（零提权）
        if whitelisted and where == "user":
            try:
                if prepend_user_path_entry(expected):
                    self._log("info", f"已把本工具那条提到用户 PATH 最前：{expected}")
            except Exception as exc:  # noqa: BLE001
                self._log("warn", f"调整用户 PATH 顺序失败：{exc}")
            verdict2, shadow2 = self._path_effective_check(version)
            if verdict2 == "ok":
                self._log("ok", f"复验通过：新开的终端会用到 {expected}")
                self._log_verification_hint(since_epoch)
                return
            if shadow2:
                shadow = shadow2
                where = shadow_location(str(shadow))

        # ② 系统段压着：只有改系统 Path 才有用，问一次（确认框 + UAC）
        if whitelisted and where == "machine":
            self._log("warn", head + "它在**系统变量**里，用户级写入压不住；"
                                    "本工具可以帮你把这个版本插到系统 PATH 最前"
                                    "（原有条目一条不删，随时可还原）。")
            res = apply_workspace_machine(
                self.component, version,
                confirm_machine=self._confirm_machine_takeover,
                log=lambda m: self._log("info", m))
            for step in res.get("steps") or []:
                self._log("error" if ("失败" in step or "未通过" in step) else "info", step)
            if res.get("ok"):
                self._log("ok", "已在系统级生效；新开的终端/IDE 才会读到新值")
                self._log_verification_hint(since_epoch)
                self._refresh_external_section()
            elif res.get("verdict") == "cancelled":
                self._log("warn", "已取消，系统变量未改动；命令行仍会用上面那个版本")
            else:
                self._log("error", str(res.get("error") or "改系统变量未成功"))
            return

        # ③ 两段都不是 / 不在白名单：如实报告，并说清为什么本工具不接手
        self._log("warn", head + "它不在本工具的工作目录里，也不在本工具能改的"
                                "「用户变量」里；需要你自己在「系统变量」的 PATH 里"
                                "删掉/后移那条，再重开终端。")

    # ------------------------------------------------------------------
    def on_configure_clicked(self) -> None:
        """仅配置环境变量。

        多版本组件：把下拉框选中的版本设为"当前生效版本"（PATH 只留它一条）。
        其他组件：沿用原有"取已装目录里语义版本最高的一个"的行为，不写 active 表。

        为什么必须按下拉框选中的版本生效，而不是照旧取"目录名字典序最后一个"：
        jdk 的下拉清单是内置大版本串 21/17/11/8，装了 21、17、8 时，
        字符串排序会把 jdk-8 排到最后，
        于是用户明明选的是 21，配出来的却是 8 —— 生效版本与所选版本必须一致。
        """
        install_root = CONFIG_DIR / self.component.key
        if not install_root.exists():
            self._log("warn", "尚未下载，请先执行“安装”。")
            return
        ordered = installed_versions(self.component)
        if self.component.multi_version:
            if not ordered:
                self._log("warn", (f"未找到符合 {self.component.key}-<版本号> 命名的安装目录；"
                                   f"可用『清理残留 PATH』自愈后重试"))
                return
            chosen = self._current_version().version
            if chosen not in [v for v, _p in ordered]:
                self._log("warn", (f"下拉框选的是 {chosen}，磁盘上没有对应目录；"
                                   f"已装：{'、'.join(v for v, _p in ordered)}"))
                return
            self._apply_active(chosen)
            return
        if not ordered:
            self._log("warn", "未找到已解压的安装目录。")
            return
        self._configure_env(ordered[0][1])
        self._detect_status()

    # ------------------------------------------------------------------
    def _configure_after_extract(self, install_path: Path) -> None:
        """安装/解压收尾时配置环境变量。

        多版本组件走**原子切换**（写 XXX_HOME + 把本组件在 PATH 里的条目收敛成这一条
        + 记 active 表），不能再走 _configure_env 的"追加一条"：装两个版本就会在 PATH 里
        留下两条，命令行按顺序只认第一条，界面上说的"生效版本"就成了假话
        （2026-09-30 用户真机反馈：bun 1.4.2 与 1.4.1 同时在 PATH）。
        非多版本组件保持原有行为逐字不变。
        """
        comp = self.component
        # 装完先核对"要放进 PATH 的目录里有没有可执行文件"（R3.22 的教训）：
        # 指错目录只会表现为"切了但没生效"，用户无从自查，必须当场点名。
        ok_dir, where = verify_bin_dir(comp, install_path)
        if not ok_dir:
            self._log("warn",
                      f"装完核对：本工具准备放进 PATH 的目录里没有 {comp.exec_name}"
                      + (f"，实际它在 {where}" if where else "（整个安装目录里都没找到）")
                      + "。这会让「切换生效版本」失效 —— 命令行仍会命中机器上原有的那个。"
                        "请把这段日志发给开发者，需要修正该组件的 path_subdir。")
        if not comp.multi_version:
            self._configure_env(install_path)
            return
        version = version_from_install_dir(comp, install_path)
        if not version:
            # 目录名不符合 <key>-<version> 约定（历史安装），无法登记生效版本，
            # 退回老路径配置，至少让组件可用
            self._configure_env(install_path)
            return
        self._log("info", f"多版本组件：把新装的 {version} 设为生效版本并收敛 PATH")
        self._apply_active(version)

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
    _COMPONENTS_CACHE: Dict[str, "Component"] = {}

    @staticmethod
    def current_components() -> Dict[str, "Component"]:
        """只读的组件表：卡片的启动/停止要用别的组件（needs 判定），
        但不该每张卡片自己再 build_components() 一次。"""
        if not MainWindow._COMPONENTS_CACHE:
            MainWindow._COMPONENTS_CACHE = {c.key: c for c in build_components()}
        return MainWindow._COMPONENTS_CACHE

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        # 设置窗口图标（任务栏、标题栏、Alt+Tab 切换显示）
        # 使用项目内置的 assets/byte-tools.png，缺失时不报错
        _icon_path = Path(__file__).parent / "assets" / "byte-tools.png"
        if _icon_path.exists():
            self.setWindowIcon(QIcon(str(_icon_path)))
        self.resize(1000, 680)
        # 标题栏（标题 + 5 个按钮 + 窗口控制）实测需要 ~992 像素；原来 880 时布局已经
        # 在挤压，多一个「开验证终端」后开始把「清理残留 PATH」压到裁字（178→144）。
        self.setMinimumSize(1000, 560)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self.components = build_components()
        self._drag_pos: Optional[QPoint] = None
        self._fetch_workers: List[VersionFetchWorker] = []
        self._fetch_pending: int = 0
        # 关窗标志：置位后不再派发抓取，也不再把抓取结果写回界面
        self._closing: bool = False
        # 视图模式：grid（按宽度自动分列）/ list（恒 1 列）；_load_settings 会按
        # config.json 覆盖它，老配置没有这个键时留在 grid，即"老用户自动获得新默认"。
        self.view_mode: str = "grid"

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
        # 版本号放在标题的 tooltip 里（状态条上也有一份）：标题栏那 48px 已经挤了
        # 五个按钮，再塞一串 v1.1.1 会在小窗口下把按钮裁掉（本项目栽过两次）。
        title_label.setToolTip(f"{APP_NAME} v{APP_VERSION}")
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

        # 开验证终端按钮
        self.btn_clean_terminal = QPushButton("🖥 开验证终端")
        self.btn_clean_terminal.setObjectName("iconBtn")
        self.btn_clean_terminal.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_clean_terminal.setToolTip(
            "用「系统为新进程合成的环境」开一个命令行窗口\n"
            "在这里查版本号，等价于在一个全新打开的终端里查——"
            "已开着的终端/IDE 标签页拿的仍是旧环境，那里对不上不代表切换失败"
        )
        self.btn_clean_terminal.clicked.connect(self._on_clean_terminal_clicked)
        tb.addWidget(self.btn_clean_terminal)

        # 标题栏按钮定宽：空间不足时宁可让窗口最小宽去兜（见上面 setMinimumSize），
        # 也不许把按钮压扁裁字。
        for _btn in (self.btn_github, self.btn_refresh, self.btn_cleanup_path,
                     self.btn_clean_terminal):
            _btn.setSizePolicy(QSizePolicy.Fixed, _btn.sizePolicy().verticalPolicy())

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

        # 视图切换与日志开关放在搜索条右侧的空白处，**不放标题栏**：标题栏已有
        # 5 个按钮 + 3 个窗口控制，实测需要 ~992px，窗口才 1000 宽，再加必然
        # 把已有的按钮压到裁字。
        self.btn_view_mode = QPushButton("▦ 网格")
        self.btn_view_mode.setObjectName("toolBtn")
        self.btn_view_mode.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_view_mode.setToolTip(
            "网格：按窗口宽度自动分成 2 列 / 3 列；列表：恒 1 列（卡片内容不变）")
        self.btn_view_mode.clicked.connect(self._on_view_mode_clicked)
        sb.addWidget(self.btn_view_mode)

        self.btn_log = QPushButton("📋 日志")
        self.btn_log.setObjectName("toolBtn")
        self.btn_log.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_log.setToolTip("展开/收起运行日志（浮层，盖在卡片上，不挤压网格）")
        self.btn_log.clicked.connect(self._on_log_button_clicked)
        sb.addWidget(self.btn_log)

        sb.addStretch(1)
        outer.addWidget(self.search_bar)

        # ------- 主体：卡片区（吃满中部）+ 日志浮层 -------
        # 日志原先和卡片区按 3:2 分在同一个 QSplitter 里，展开/收起都会挤压网格。
        # 现在卡片区独占中部，日志改成浮在它上面的浮层：不占布局空间，于是
        # 列数与行数只由窗口宽度决定，开关日志不会让格子忽大忽小。

        # 卡片区域：按 COMPONENT_CATEGORIES 分四个 Tab，每个 Tab 一条独立滚动栏。
        # self.cards 仍是全量平铺列表——刷新版本 / 存取配置 / 关窗等探测都靠它遍历。
        self.cards: List[ComponentCard] = []
        self._tab_cards: List[List[ComponentCard]] = []
        # `_tab_layouts[i]` 的语义从"直接装卡片"改成"装行的外层竖向布局"：
        # 行本身是一个 QWidget，行里的 QHBoxLayout 才装格子。
        # 用行容器而不是 QGridLayout，是因为 _restore_browse /
        # _build_unified / _relayout_results 全靠 QBoxLayout 的 indexOf / insertWidget
        # / 末尾 stretch —— 结果面板的"行"要能插进指定位置，QGridLayout 做不到。
        self._tab_layouts: list = []
        # `_tab_rows[key]`：Tab 用 0..N-1 的序号，统一结果面板用 RESULTS_KEY。
        # 两者存的都是"行控件"（结果面板里一行就是某个分类下的一截卡片）。
        self._tab_rows: dict = {}
        self._tab_wraps: List[QWidget] = []
        # Tab 标题的"干净"形态（分类名 + 组件数）。运行标记 `●` 是叠在它上面的，
        # 搜索/退出搜索会重设标题，所以必须留着底稿，不能靠 tabText() 反推。
        self._tab_base_titles: List[str] = []
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
            cards_layout = CardColumnLayout(cards_wrap)
            cards_layout.setContentsMargins(18, 18, 18, 18)
            cards_layout.setSpacing(CARD_ROW_SPACING)
            tab_cards: List[ComponentCard] = []
            for comp in comps:
                card = ComponentCard(comp, self._append_log)
                # 先挂进容器，具体排在哪个格子里由 relayout_cards 决定
                card.setParent(cards_wrap)
                self.cards.append(card)
                tab_cards.append(card)
            scroll.setWidget(cards_wrap)
            base_title = f"{cat_name}（{len(comps)}）"
            self.tabs.addTab(scroll, base_title)
            self._tab_base_titles.append(base_title)
            self._tab_cards.append(tab_cards)
            self._tab_layouts.append(cards_layout)
            self._tab_wraps.append(cards_wrap)
            self._tab_rows[len(self._tab_cards) - 1] = []

        # 统一搜索结果面板：搜索时收起四个 Tab，把所有命中的组件按分类归并到
        # 同一个滚动列表里（带分类小标题），一眼看全、不用切页——这就是「全组件搜索」。
        self.results_area = QScrollArea()
        self.results_area.setObjectName("resultsArea")
        self.results_area.setWidgetResizable(True)
        self.results_content = QWidget()
        self.results_content.setObjectName("resultsContent")
        # 结果面板用与 Tab 同一个 CardColumnLayout：命中卡片也住进 cardRow 行控件，
        # 格子宽度就跟浏览时一模一样（不再是"一张卡占满 954px"的宽条）。
        self.results_layout = CardColumnLayout(self.results_content)
        self.results_layout.setContentsMargins(18, 18, 18, 18)
        self.results_layout.setSpacing(6)
        self.results_area.setWidget(self.results_content)
        # 结果面板的结构是「分类小标题（整行）+ 该分类的若干 cardRow 行」。登记进
        # _tab_rows 的是**真实的行控件**，与四个 Tab 同构，"命中数 < 列数时有没有
        # 空洞"因此有统一判据。`_result_sections` 记着「标题 → 该分类命中卡片」，
        # 重排时靠它在各自标题下面重建行（标题本身不重建，否则会丢）。
        self._tab_rows[RESULTS_KEY] = []
        self._result_sections: list = []

        # 浏览模式用 Tab，搜索模式用统一结果面板，二者互斥地放进一个栈
        self.top_stack = QStackedWidget()
        self.top_stack.setObjectName("topStack")
        self.top_stack.addWidget(self.tabs)           # index 0：浏览
        self.top_stack.addWidget(self.results_area)   # index 1：搜索结果

        self.body = QWidget()
        self.body.setObjectName("bodyArea")
        body_lay = QVBoxLayout(self.body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        body_lay.addWidget(self.top_stack)
        outer.addWidget(self.body, stretch=1)

        # 日志浮层：与卡片区同一个父级，靠 raise_() 叠在上面，几何随 resize 跟随。
        # 它不在 body 的布局里，所以 show/hide 都不会让卡片区尺寸变化 ——
        # 这是"展开日志不重排网格"这条承诺的实现基础。
        self.log_overlay = QWidget(self.body)
        self.log_overlay.setObjectName("logOverlay")
        overlay_lay = QVBoxLayout(self.log_overlay)
        overlay_lay.setContentsMargins(18, 8, 18, 14)
        overlay_lay.setSpacing(6)
        overlay_head = QHBoxLayout()
        log_title = QLabel("运行日志")
        log_title.setStyleSheet("color:#e6e9ef;font-weight:600;")
        overlay_head.addWidget(log_title)
        overlay_head.addStretch(1)
        self.btn_log_close = QPushButton("×")
        self.btn_log_close.setObjectName("overlayCloseBtn")
        self.btn_log_close.setFixedSize(26, 26)
        self.btn_log_close.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_log_close.setToolTip("收起日志浮层")
        self.btn_log_close.clicked.connect(self._close_log_by_user)
        overlay_head.addWidget(self.btn_log_close)
        overlay_lay.addLayout(overlay_head)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("logView")
        overlay_lay.addWidget(self.log_view)
        self.log_overlay.hide()

        # 底部状态条：系统 / **可点的工作目录** / 组件总数 / 版本号。
        # 总数按 `self.cards`（界面可见）算，不是 `self.components`：erlang 是 hidden
        # 组件，只当 rabbitmq 的前置依赖，用户在四个 Tab 里都找不到它 —— 以前这里写 27、
        # 搜索框右边写 /26，同一屏两个数字互相矛盾（2026-10-10 用户第一条质疑）。
        hidden = len(self.components) - len(self.cards)
        self.status_bar = QLabel(
            f"系统：{CURRENT_OS} ({MACHINE})   工作目录："
            f'<a href="dir://{html_escape(Path(CONFIG_DIR).as_posix())}" '
            f'style="color:#8fa3b8;text-decoration:underline">'
            f"{html_escape(str(CONFIG_DIR))}</a>   "
            f"组件总数：{len(self.cards)} 个"
            + (f"（另有 {hidden} 个仅作前置依赖，不在界面显示）" if hidden > 0 else "")
            + f"   版本：v{APP_VERSION}"
        )
        self.status_bar.setObjectName("statusBar")
        self.status_bar.setTextFormat(Qt.RichText)
        # 不许开 setOpenExternalLinks(True)：那会把 dir:// 丢给系统的"未知协议"处理，
        # 用户点一下什么也不会发生。链接自己接，见 _on_status_link。
        self.status_bar.setOpenExternalLinks(False)
        self.status_bar.linkActivated.connect(self._on_status_link)
        outer.addWidget(self.status_bar)

        # 日志浮层的未读计数与自动收起定时器（QTimer 挂在窗口上，测试可注入时钟）
        self._log_unread = 0
        self._log_user_open = False
        self._log_auto_hide = QTimer(self)
        self._log_auto_hide.setSingleShot(True)
        self._log_auto_hide.setInterval(LOG_AUTO_HIDE_MS)
        self._log_auto_hide.timeout.connect(self._on_log_auto_hide)

        # 列数缓存：resizeEvent 只在它变化时才重建行（见 resizeEvent 里的说明）
        self._last_columns = 0
        for idx in range(len(self._tab_cards)):
            self.relayout_cards(idx)
        self._refresh_view_button()
        self._refresh_log_button()

    # ------------------------------------------------------------------
    # 卡片网格：分列、重排
    # ------------------------------------------------------------------
    def _card_columns(self) -> int:
        """当前卡片区该排几列：列表模式恒 1 列，网格模式按可用净宽算。

        宽度**不能**取"当前 Tab 的 viewport"——有竖滚动条的页（10 张卡要滚）
        比没有的页窄十几像素，正好骑在列数边界上：切一次 Tab 列数就变，
        再叠加"切 Tab 不触发重排"，同一页就会出现两种列数混排、末行溢出
        （真机 2026-10-08 用户 125% 缩放截图实测）。改用 tabs 本身的宽度
        （四个 Tab 恒相同）减去固定开销：左右边距 36 + 竖滚动条 10 预留。
        切 Tab、滚动条出现消失都不影响列数。
        """
        if getattr(self, "view_mode", "grid") == "list":
            return 1
        tabs = getattr(self, "tabs", None)
        if tabs is None:
            return 1
        return grid_columns_for(tabs.width() - 36 - 10, MIN_CARD_WIDTH_PX)

    def relayout_cards(self, container_key) -> None:
        """把一个容器里的卡片按当前列数重排成"行"。

        入参 container_key: int → 第几个 Tab；RESULTS_KEY → 统一搜索结果面板。

        重排只排"没被隐藏"的卡片（搜索命中的反面），所以命中数少于列数时
        不会留下空洞；隐藏的卡片被收回到容器宿主上，不占任何格子。
        """
        if container_key == RESULTS_KEY:
            self._relayout_results()
            return
        idx = int(container_key)
        layout = self._tab_layouts[idx]
        root = self._tab_wraps[idx]
        cards = self._tab_cards[idx]
        # 只排"此刻真的住在这个 Tab 里"的卡片：搜索时命中的卡片已搬到结果面板，
        # 不判归属就会把它们从结果面板里拽回 Tab，搜索结果当场散架。
        own = [c for c in cards if root.isAncestorOf(c)]
        self._tab_rows[idx] = self._fill_rows(layout, root, own, self._card_columns())

    def _relayout_results(self) -> None:
        """统一结果面板：保留分类小标题，在各自标题下面重建卡片行。

        行与浏览 Tab 是同一套 cardRow（`_make_rows` 造的），所以格子等宽。
        **列数恒取浏览列数**（2026-10-10 用户改的口径：「搜索组件时如果只有一个组件
        也要以网格显示，现在变成列表了」）：命中 1 个也是 3 个格子里占 1 个，
        另外两格补透明占位控件 —— 少补一格，`addWidget(card, 1)` 就会把那张卡拉成
        整行宽，看上去就从"网格"退化成"列表"。以前这里是 `min(命中数, 浏览列数)`，
        命中 1 个就 1 列，正是用户报的那个现象。
        """
        sections = getattr(self, "_result_sections", None) or []
        cards = [c for _, group in sections for c in group]
        if not cards:
            self._tab_rows[RESULTS_KEY] = []
            self.results_layout.row_widgets = []
            return
        columns = max(1, self._card_columns())
        # 分块必须在搬家**之前**算完：setParent 会把卡片显式隐藏，先搬再算就排空
        chunks_per_group = [chunk_visible(group, columns) for _, group in sections]
        # 卡片先收回到宿主，否则下面销毁旧行会把还住在里面的卡片一起带走
        for card in cards:
            if self.results_content.isAncestorOf(card):
                card.setParent(self.results_content)
        # 只摘行、留标题：结果面板是"标题 + 行"交错的结构，全清会把标题一起删掉
        self._drop_rows(self.results_layout, only_rows=True)
        rows: list = []
        for (header, _group), chunks in zip(sections, chunks_per_group):
            pos = self.results_layout.indexOf(header)
            if pos < 0:
                continue
            for k, row in enumerate(self._make_rows(self.results_content, chunks,
                                                    pad_to=columns)):
                self.results_layout.insertWidget(pos + 1 + k, row)
                rows.append(row)
        self.results_layout.row_widgets = rows
        self._tab_rows[RESULTS_KEY] = rows

    def _fill_rows(self, layout, root, cards, columns) -> list:
        """销毁旧行、按 columns 重建行，返回新建的行控件列表。

        两步都不能省：先把这个容器的卡片全部收回到宿主，否则销毁行控件时
        会把还住在里面的卡片一起带走；收回之后 addWidget 的顺序才等于
        子控件顺序（findChildren 读出来的行内顺序才是对的）。
        """
        # 分块必须在搬家**之前**算完：setParent 会把控件显式隐藏（isHidden 变 True），
        # 先搬再算就一张可见卡片都不剩，整页排空。
        chunks = chunk_visible(cards, columns)
        for card in cards:
            if root.isAncestorOf(card):
                card.setParent(root)
        self._drop_rows(layout)
        layout.row_widgets = []
        # pad_to 必须给：半行不补占位的话，QHBoxLayout 的 addWidget(card, 1) 会把
        # 末行的卡片**拉伸占满整行** —— 「其它软件」2 张各半行、「开发软件」的 Pulsar
        # 独占一行，跟满行格子的 309px 完全不同宽（真机 2026-10-08 用户截图实测）。
        rows = self._make_rows(root, chunks, pad_to=columns)
        for row in rows:
            layout.addWidget(row)
            layout.row_widgets.append(row)
        layout.addStretch(1)
        return rows

    def _drop_rows(self, layout, only_rows: bool = False) -> None:
        """摘掉 layout 里的条目并销毁（`_fill_rows` 与结果面板重排共用）。

        入参 only_rows: bool  True → 只摘 objectName 为 "cardRow" 的行控件，
             分类小标题与末尾 stretch 原样留下。结果面板是「标题 + 行 + 标题 + 行」
             的交错结构，整清一次会把分类标题一起 deleteLater。
        """
        i = 0
        while i < layout.count():
            item = layout.itemAt(i)
            w = item.widget()
            if only_rows and (w is None or w.objectName() != "cardRow"):
                i += 1
                continue
            layout.takeAt(i)
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            else:
                sp = item.spacerItem()
                if sp is not None:
                    del sp

    def _make_rows(self, root, chunks, pad_to: int = 0) -> list:
        """按 chunks（每个元素是一行的卡片序列）造出 cardRow 行控件。

        入参 pad_to: int  >0 时，不足该列数的行末尾补一个等比占位控件，让卡片
             仍然只占"一个格子"的宽度。搜索结果靠它保证「命中 5 个 → 3 列」时
             第二行那 2 张卡跟第一行 3 张卡一样宽 —— 否则 addWidget(card, 1) 会把
             半行的卡片拉伸到占满整行，宽度又跟浏览格子对不上了（真机实测踩中）。

        只负责"造行"，**不碰外层布局** —— 行插在哪儿由调用方决定：Tab 是
        顺序追加，结果面板要插在各自的分类小标题后面。
        """
        rows: list = []
        for row_cards in chunks:
            row = QWidget(root)
            row.setObjectName("cardRow")
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(CARD_ROW_SPACING)
            for card in row_cards:
                row_lay.addWidget(card, 1)      # 同一行的格子等分宽度
                # setParent 会把控件**显式隐藏**（实测 isHidden 变 True），搬一次家
                # 就把卡片弄没了，所以进格子后必须再放出来一次。
                card.show()
            if pad_to and len(row_cards) < pad_to:
                # 占位控件必须**可见**才会参与布局（隐藏的控件会被布局忽略），
                # 但它没有任何内容与背景，画出来是透明的；对鼠标也透明，不挡点击。
                # 一格补一个（而不是一个占位控顶 n 格）：间距数才能与满行一致，
                # 格子宽度才会跟浏览时分毫不差（313 vs 309 的偏差就是这么来的）。
                for _ in range(pad_to - len(row_cards)):
                    filler = QWidget(row)
                    filler.setObjectName("cardRowFiller")
                    filler.setAttribute(Qt.WA_TransparentForMouseEvents)
                    row_lay.addWidget(filler, 1)
                    filler.show()
            # 行控件是新建的，加到布局里不会自动显示（实测 isVisible 仍为 False），
            # 必须显式 show 一次，否则重排之后整页卡片会"消失"；
            # show() 会顺着子控件往下走，把行里的卡片一起带出来。
            row.show()
            rows.append(row)
        return rows

    def resizeEvent(self, e) -> None:  # noqa: N802  Qt 规定的驼峰签名
        super().resizeEvent(e)
        # resize 是"每变一个像素一次"的事件，每次都重建行控件会把拖动窗口卡死，
        # 所以只在列数真的变化时才重排。
        columns = self._card_columns()
        if columns != self._last_columns:
            self._last_columns = columns
            for idx in range(len(self._tab_cards)):
                self.relayout_cards(idx)
            # 搜索中窗口变宽/变窄，结果面板的格子也要跟着变，否则它的卡片宽度
            # 会跟浏览 Tab 对不上（正是"搜索结果卡更宽"那条反馈的根源）。
            if self.top_stack.currentIndex() == 1:
                self.relayout_cards(RESULTS_KEY)
        self._position_log_overlay()

    def showEvent(self, e) -> None:  # noqa: N802  Qt 规定的驼峰签名
        super().showEvent(e)
        # 首次显示时必须强制重排一次：_build_ui 末尾那次 relayout 跑在窗口 show
        # 之前，QScrollArea 的 viewport 宽度还没就绪，grid_columns_for 会算出 1 列
        # —— 卡片全排成"一行一张"。而窗口尺寸在构造期就已 resize 到 1000×680，
        # show() 不改变尺寸就**不会触发 resizeEvent**，这个错排没有任何机会被纠正，
        # 用户只有手动拖一下窗口大小才能看到网格（真机 2026-10-08 实测踩中）。
        # resizeEvent 那套"列数变了才重排"的防抖在这里反而是障碍，所以直接重排。
        if not getattr(self, "_first_show_done", False):
            self._first_show_done = True
            self._last_columns = self._card_columns()
            for idx in range(len(self._tab_cards)):
                self.relayout_cards(idx)
            self._position_log_overlay()

    # ------------------------------------------------------------------
    # 日志浮层
    # ------------------------------------------------------------------
    def _position_log_overlay(self) -> None:
        """浮层贴在卡片区底部，高度取中部高度的 45%（夹在 160~300px）。"""
        host = getattr(self, "body", None)
        overlay = getattr(self, "log_overlay", None)
        if host is None or overlay is None:
            return
        height = min(300, max(160, int(host.height() * 0.45)))
        overlay.setGeometry(0, host.height() - height, host.width(), height)

    def _on_status_link(self, link: str) -> None:
        """状态条里的 `dir://…` → 用系统文件管理器打开那个目录（2026-10-10 用户要求）。

        为什么值得给：工作目录 `~/.env-tools` 是用户排查问题第一眼要看的地方
        （下载包、各组件版本目录、日志、takeover 备份都在里面）。以前那串路径是纯文本，
        照着敲进资源管理器地址栏是个体力活。
        """
        if not link.startswith("dir://"):
            return
        target = link[len("dir://"):]
        if not _open_in_file_manager(target):
            self._log("warn", f"打不开工作目录 {target}：目录不存在，或系统不允许从本工具打开")

    def _set_log_open(self, open_: bool) -> None:
        """展开/收起日志浮层。

        浮层不在卡片区的布局里，所以这里**不会**触发 relayout —— 网格的行数
        与每行卡片数在开关前后完全一致（这是浮层相对"挤压式折叠"的关键差别）。
        """
        overlay = getattr(self, "log_overlay", None)
        if overlay is None:
            return
        if open_:
            self._position_log_overlay()
            overlay.show()
            overlay.raise_()
        else:
            overlay.hide()
        self._refresh_log_button()

    def _on_log_button_clicked(self) -> None:
        """点「📋 日志」：toggle 一次；点开即视为已读，未读计数清零。"""
        if self.log_overlay.isHidden():
            self._log_unread = 0
            self._log_user_open = True
            self._log_auto_hide.stop()
            self._set_log_open(True)
        else:
            self._close_log_by_user()

    def _close_log_by_user(self) -> None:
        self._log_user_open = False
        self._log_auto_hide.stop()
        self._set_log_open(False)

    def _on_log_auto_hide(self) -> None:
        """告警自动弹开的浮层，静默 LOG_AUTO_HIDE_MS 后自己收起。

        用户手动点开的那一侧不做自动收起（_log_user_open），免得看着日志
        正看到一半被关掉。
        """
        if getattr(self, "_log_user_open", False):
            return
        self._set_log_open(False)

    def _refresh_log_button(self) -> None:
        btn = getattr(self, "btn_log", None)
        if btn is None:
            return
        unread = getattr(self, "_log_unread", 0)
        # 未读条数直接写在按钮文字里：不新增控件，标题栏也用不着再挤一个位置
        btn.setText(f"📋 日志 ({unread})" if unread else "📋 日志")

    def _on_view_mode_clicked(self) -> None:
        """网格 ⇄ 列表。列表模式就是"强制 1 列"，卡片内容一模一样。"""
        self.view_mode = "list" if self.view_mode == "grid" else "grid"
        self._refresh_view_button()
        for idx in range(len(self._tab_cards)):
            self.relayout_cards(idx)
        self._save_settings()

    def _refresh_view_button(self) -> None:
        btn = getattr(self, "btn_view_mode", None)
        if btn is None:
            return
        grid = getattr(self, "view_mode", "grid") != "list"
        btn.setText("▦ 网格" if grid else "☰ 列表")

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

        入参 query: str  搜索框当前内容；空串（或全空白）表示退出搜索、恢复四个 Tab。

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
        """把全部卡片放回各自 Tab 并恢复可见，切回浏览模式，然后按列数重排。"""
        # 从统一结果面板卸下所有卡片（卡片先回到自己 Tab 的容器，小标题才销毁）
        self._clear_results_layout()
        # 搜索时被隐藏的卡片要一起放出来，否则重排会因为"看不见"把它们漏掉
        for card in self.cards:
            card.setVisible(True)
        self.top_stack.setCurrentIndex(0)
        for idx in range(len(self._tab_cards)):
            self.relayout_cards(idx)
        # Tab 标题恢复成「分类（总数）」，并重新标出哪些页有组件在运行
        self._mark_running_tabs()
        self._tab_rows[RESULTS_KEY] = []

    def _log_credentials_of(self, key: str, port: int) -> None:
        """主窗侧：把某个正在运行的组件的登录凭据写进全局日志。

        读不到就跳过——凭据只是便利信息，缺了不该让"认清本机运行状态"看起来失败。
        """
        # 走类名而不是 self：_COMPONENTS_CACHE 是类属性，用 MainWindow.xxx
        # 在测试的"半初始化实例"上也能跑通（那类实例的 self 上没有绑定 staticmethod）。
        comp = MainWindow.current_components().get(key)
        if comp is None or getattr(comp, "launch", None) is None:
            return
        try:
            for line in credentials_for(comp, comp.launch, port):
                self._append_log("info", f"[{comp.display_name}] {line}")
        except Exception:
            pass

    def _mark_running_tabs(self) -> None:
        """Tab 标题后标 `●` 表示"这一页有组件在运行"，清空搜索/退出搜索时都要重算。

        2026-10-06 用户反馈"启动了 nacos，没看到停止选项"—— 按钮一直是好的，
        但当时三个启动组件分在两个 Tab（Nacos/ActiveMQ 在「开发软件」、Jenkins 在「其它软件」），
        界面默认停在「开发环境」。用户在自己的启动页上找不到刚才那个卡片。
        （2026-10-08 起可启停组件已集中到「一键启停」Tab，这一条分散找卡的起因消了；
        `●` 仍然保留 —— 同时跑着两三个组件时，还是要知道哪一页上有活的。）
        标题上挂个 `●`，无论停在哪一页都能一眼看出"有东西在跑，去那页找"。
        """
        tabs = getattr(self, "tabs", None)
        if tabs is None:                      # 构造期/测试用的半成品窗口：没有 Tab 就没什么可标
            return
        base_titles = getattr(self, "_tab_base_titles", [])
        tab_cards = getattr(self, "_tab_cards", [])
        for idx in range(tabs.count()):
            base = base_titles[idx] if idx < len(base_titles) else tabs.tabText(idx)
            cards = tab_cards[idx] if idx < len(tab_cards) else []
            running = any(hasattr(c, "btn_start") and c._running_per_ui()
                          for c in cards)
            tabs.setTabText(idx, f"{base}{'  ●' if running else ''}")

    def _reveal_running_tabs(self) -> None:
        """有组件在运行时，若它不在当前 Tab，就把 Tab 切过去并说清是哪一页。

        2026-10-06 用户反馈"启动了 nacos，没看到停止选项"。查下来按钮一直是好的
        （btn_stop 可见可用、文本"停止"、label 显示"● 运行中 · 端口 8848"），
        真正的原因是**当时三个启动组件分在两个 Tab**：
        Jenkins 在「其它软件」，Nacos/ActiveMQ 在「开发软件」，
        而界面默认停在 Tab0「开发环境」。用户自然找不到自己刚启动的那个卡片。
        （2026-10-08 起它们都在「一键启停」一页；跳页与这句说明留着，是因为
        同时跑多个组件、或用户停在别的页上时，症状会一模一样地复发。）

        这不是"找不到按钮"，是"服务跑着却看不见"——比按钮缺失更容易让人以为没启动成功。
        所以这里主动跳页+ 点名在日志里说清，不指望用户自己 Tab 翻一遍。
        """
        self._mark_running_tabs()
        tabs = getattr(self, "tabs", None)
        layouts = getattr(self, "_tab_layouts", None)
        tab_cards = getattr(self, "_tab_cards", None)
        if tabs is None or not layouts or not tab_cards:
            return
        for card in self.cards:
            if not hasattr(card, "btn_start"):
                continue
            if not card._running_per_ui():
                continue                     # 没在运行，不用跳
            # 按 _tab_cards 判归属，不按 layout.indexOf：改成行容器后卡片不在
            # 外层布局里（它的父级是行控件），indexOf 恒为 -1，跳页会静默失效。
            idx = next((n for n, cards in enumerate(tab_cards)
                        if any(c is card for c in cards)), -1)
            if idx >= 0 and idx != tabs.currentIndex():
                tabs.setCurrentIndex(idx)
                base = self._tab_base_titles[idx] if idx < len(self._tab_base_titles) \
                    else tabs.tabText(idx)
                self._append_log(
                    "info",
                    f"已切换到「{base.split('（')[0]}」页："
                    f"{card.component.display_name} 正在运行，"
                    f"它的「停止」按钮在这一页（端口 {card._launch_status().record.port}）。")
                return                      # 一次只跳一个，避免连翻多页

    def _build_unified(self, q: str) -> None:
        """把命中的组件按分类归并进统一结果列表（带分类小标题）。

        结构与浏览 Tab 同一套网格：**分类小标题（整行）+ 该分类的若干 cardRow 行**，
        所以搜索结果的卡片宽度与浏览时一致。列数取 min(命中数, 浏览列数)，由
        `_relayout_results` 统一算 —— 命中 1 个就是 1 列，命中 5 个就是 3 列。
        """
        self._clear_results_layout()
        # 先按分类归好组：列数要按**总命中数**算，而它得等这一轮扫完才知道
        groups: list = []
        order: dict = {}
        hits = 0
        for card in self.cards:
            comp = card.component
            if not component_matches(comp, q):
                card.setVisible(False)
                continue
            cat = comp.category
            if cat not in order:
                order[cat] = len(groups)
                groups.append([cat, []])
            groups[order[cat]][1].append(card)
            card.setVisible(True)
            hits += 1
        # self.cards 已是分类顺序，遍历一遍即可，标题与卡片的相对顺序天然正确
        sections: list = []
        for cat, cards in groups:
            header = QLabel(cat)
            header.setObjectName("resultCatHeader")
            self.results_layout.addWidget(header)
            for card in cards:
                # 先挂到结果面板宿主上（不进外层布局），具体排进哪个格子由
                # _relayout_results 决定；setParent 会显式隐藏，随后要放出来
                card.setParent(self.results_content)
                card.setVisible(True)
            sections.append((header, cards))
        self.results_layout.addStretch(1)
        self._result_sections = sections
        self.top_stack.setCurrentIndex(1)

        # 四个 Tab 也要跟着重排一次，把被搬走的命中卡片从旧行里摘掉
        # （不然归属判断还认旧行）；结果面板的行在 relayout_cards 里造。
        for idx in range(len(self._tab_cards)):
            self.relayout_cards(idx)
        self.relayout_cards(RESULTS_KEY)

        self.search_hint.setText(f"匹配 {hits} / {len(self.cards)} 个组件")
        # 一个都没命中时换个警示色，免得用户以为列表加载坏了
        self.search_hint.setProperty("empty", "true" if hits == 0 else "false")
        self.search_hint.style().unpolish(self.search_hint)
        self.search_hint.style().polish(self.search_hint)

    def _send_card_home(self, card) -> None:
        """把卡片从它当前所在的"行"里摘下、挂回所属 Tab 的容器（不销毁）。

        换父级并不会让旧布局自动放手，所以必须显式 removeWidget：否则销毁行控件
        时 Qt 会把行内的卡片一起带走，下一轮搜索就少卡。
        """
        parent = card.parent()
        lay = parent.layout() if parent is not None else None
        if lay is not None and lay.indexOf(card) != -1:
            lay.removeWidget(card)
        home = self._home_wrap_of(card)
        if home is not None:
            card.setParent(home)      # 卡片稍后由 _restore_browse 重排归位

    def _clear_results_layout(self) -> None:
        """清空统一结果面板里的所有条目（分类小标题、卡片行）。

        卡片不在这里销毁：它们只是被摘出布局并回到自己 Tab 的容器，
        随后由 _restore_browse 统一重排。
        """
        self._result_sections = []
        self.results_layout.row_widgets = []
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                if w.objectName() == "cardRow":
                    # 行里住着卡片：先把它们送回各自 Tab 的容器，再销毁空行 ——
                    # 直接 deleteLater 会把行内的卡片一起带走。
                    lay = w.layout()
                    if lay is not None:
                        while lay.count():
                            child = lay.takeAt(0).widget()
                            if child is not None:
                                self._send_card_home(child)
                    w.hide()
                    w.deleteLater()
                    continue
                if any(w is card for card in self.cards):
                    self._send_card_home(w)
                    continue
                # deleteLater 是**异步**的：takeAt 之后布局不再管它，但 widget 的
                # parent 还挂在 results_content 上、几何也没变，在 deferred delete
                # 真正执行前会以"幽灵"形态残留在原地 —— 用户连续改搜索词时，上一轮
                # 的分类标题会和这一轮的内容叠在一起（真机 2026-10-08 实测踩中）。
                # 先 hide 立即从屏幕上消失，删除交给事件循环。
                w.hide()
                w.deleteLater()           # 分类小标题等临时标签
                continue
            sp = item.spacerItem()
            if sp is not None:
                del sp

    def _home_wrap_of(self, card):
        """这张卡片所属 Tab 的容器（搜索结束要按它归位）。"""
        for idx, cards in enumerate(self._tab_cards):
            if any(c is card for c in cards):
                return self._tab_wraps[idx]
        return None

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

            /* 搜索条右侧的两个工具按钮（视图切换 / 日志开关） */
            #toolBtn {
                background: #ffffff;
                color: #33465c;
                border: 1px solid #d5dfea;
                border-radius: 8px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: 600;
            }
            #toolBtn:hover { border-color: #90caf9; color: #1976d2; }

            #compTabs { background: transparent; border: none; }

            #compTabs::pane { border: none; background: transparent; }
            #compTabs > QTabBar { background: transparent; }
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

            /* ---- 「系统里检测到的版本」折叠区（设计 §6）----
               格子内部只有 271px，所以这里是"一行一件事"的紧凑排版：
               标题是一条扁按钮，展开后每行是「版本·路径 + 切过去」。 */
            #externalToggle {
                text-align: left;
                padding: 0 6px;
                border: 1px dashed #cfd8dc;
                border-radius: 7px;
                background: #f7f9fc;
                color: #455a64;
                font-size: 12px;
            }
            #externalToggle:hover { border-color: #90caf9; color: #1565c0; }
            #externalRow { background: transparent; }
            #externalVersion { color:#263238; font-size:12px; font-weight:600; }
            #externalPath { color:#78909c; font-size:11px; }
            #externalLabel { color:#37474f; font-size:12px; }
            #externalHint { color:#90a4ae; font-size:12px; }
            #restoreBtn {
                border: 1px solid #ffb74d;
                border-radius: 7px;
                background: #fff8e1;
                color: #e65100;
                font-size: 12px;
                font-weight: 600;
            }
            #restoreBtn:hover { background: #ffecb3; border-color: #ffa726; }

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
                padding: 6px 8px;
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
                padding: 6px 8px;
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
                padding: 6px 8px;
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

            /* 日志浮层：盖在卡片区上面，不占布局空间（展开不会挤压网格） */
            #logOverlay {
                background: #26303f;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-top: 1px solid #3d4a5d;
            }
            #logOverlay QLabel { color: #e6e9ef; }
            #overlayCloseBtn {
                background: transparent;
                color: #9fb0c4;
                border: none;
                font-size: 16px;
                border-radius: 6px;
            }
            #overlayCloseBtn:hover { background: rgba(255,255,255,0.12); color: #ffffff; }
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
    def _on_clean_terminal_clicked(self) -> None:
        """开一个"新进程环境"的命令行窗口，用来判定切换到底生效没有。

        为什么非做不可：Windows 是把环境块**复制**给新进程的，旧宿主（Windows Terminal、
        IDE）开出来的新标签页拿的还是宿主那份旧环境。2026-09-30 真机就是这个局面 ——
        注册表与 explorer 现场启动的进程都是 1.4.1，用户"新开的"窗口里仍是 1.4.2。
        跟用户解释机制没用，给一个必然干净的窗口才有结论。
        """
        composed = EnvManager.composed_env()
        if not composed:
            self._append_log(
                "warn", "拿不到系统为新进程合成的环境（非 Windows 或 API 被拒），"
                        "无法开验证终端。可以在当前 PowerShell 里原地刷新再验："
                        "$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')"
                        " + ';' + [Environment]::GetEnvironmentVariable('Path','User')")
            return
        pid = open_clean_console(composed)
        if pid is None:
            self._append_log("error", "验证终端开不了（cmd.exe 启动失败）。")
            return
        self._append_log(
            "ok", f"已开一个干净环境的命令行窗口（pid={pid}）。在里面跑 bun -v / java -version，"
                  "得到的版本就是任何**全新**终端应当看到的版本；"
                  "若这里正确、你原来那个窗口不对，说明那个窗口比本次切换更早"
                  "（见日志里点名的旧终端清单）。")

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
        # 只有 warn/error 才自动弹开浮层：下载/安装这类常规进度在卡片上已有进度条，
        # 每来一条都弹会把用户正在操作的那张卡盖住。弹开同时在按钮上挂未读条数，
        # 点开一次即清零。
        if level in ("warn", "error"):
            overlay = getattr(self, "log_overlay", None)
            if overlay is not None and overlay.isHidden():
                self._log_unread += 1
                self._set_log_open(True)
                self._log_auto_hide.start()
            self._refresh_log_button()

    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        """加载上次选择的版本。"""
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        # 视图模式：老配置没有这个键，取新默认 grid（不报错、不回退整个加载）
        mode = data.get("view_mode") if isinstance(data, dict) else None
        self.view_mode = mode if mode in ("grid", "list") else "grid"
        try:
            selections = data.get("selections", {}) if isinstance(data, dict) else {}
            for card in self.cards:
                v = selections.get(card.component.key)
                if not v:
                    continue
                idx = card.version_combo.findText(v)
                if idx < 0:
                    continue
                # 存过的版本可能已经不在下拉框里了（在线清单只留近期版本，
                # 而离线默认清单会滞后于实际安装版本）。盲目采纳的话，
                # 界面会停在一个既没装、也点不下来的版本上——jenkins 的
                # 2.568.3 就是这么来的：它已从清单消失，装着的 2.580.1 反而被顶掉。
                # 这种情况下保留 _reload_combo_items 挑的"已安装版本"更符合直觉。
                installed = {v for v, _p in installed_versions(card.component)}
                if v not in installed:
                    continue
                card.version_combo.setCurrentIndex(idx)
        except Exception:
            pass

    def _save_settings(self) -> None:
        """保存下拉框选中版本；active 由切换那侧维护，这里必须原样保留。

        合并写：先读原文件只替换 selections 那一段。整体覆盖会把 active（生效版本
        登记表）抹掉——那是切换功能写的数据，和用户这次选了哪个下拉项无关。
        （负向对照：改回整体覆盖后，测试 SaveSettingsKeepsActive 即报 KeyError: 'active'。）
        """
        try:
            ensure_dir(CONFIG_DIR)
            data: dict = {}
            if CONFIG_FILE.exists():
                try:
                    loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = loaded
                except Exception:
                    data = {}
            data["selections"] = {
                card.component.key: card.version_combo.currentText()
                for card in self.cards
            }
            if not isinstance(data.get("active"), dict):
                data["active"] = {}
            # 视图模式与 selections 一起合并写回，不整体覆盖（active 是切换那侧的数据）
            data["view_mode"] = getattr(self, "view_mode", "grid")
            _atomic_write_config(data)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _adopt_running(self) -> None:
        """启动后一次性的"认清本机在跑什么"。只读 + 清僵尸，绝不拉起进程。"""
        # 整段兜底：reconcile 清僵尸会回写 running.json（ensure_dir+写+os.replace），
        # ~/.env-tools 被只读/被锁/磁盘满时异常从这儿抛出就是从生产入口抛出、工具直接打不开 ——
        # 和读取侧"让整个界面搞崩代价不成比例"是同一个权衡，识别失败只该留下一条 warn。
        try:
            states = SERVICE_MANAGER.reconcile(self.current_components())
            for key, st in states.items():
                if st.state == "running":
                    self._append_log("info", f"检测到 {key} 正在运行（端口 {st.record.port}）")
                    # 把它的登录凭据一起报出来：这些服务是之前启的，
                    # 用户重开工具时界面上没有任何地方能看到"怎么登进去"，
                    # 逼着他去翻文件或搜官方文档。
                    self._log_credentials_of(key, st.record.port)
            # reconcile 可能刚把僵尸登记删掉：卡片在那之前已经画过一遍了，必须让它们重读，
            # 否则窗口里会留一句已经没有依据的"残留登记"。
            for card in self.cards:
                card._refresh_launch_state()
        except Exception as exc:
            self._append_log("warn", f"认清本机运行状态失败（不影响使用）：{exc}")
        # Tab 上的运行标记与自动跳页放在 try 之外：它们纯属界面便利，
        # 失败也不该让日志里多出一条"认清本机运行状态失败"——
        # 那句话会让用户以为状态识别出了问题，排查方向全错（2026-10-06 踩过）。
        try:
            self._reveal_running_tabs()
        except Exception as exc:
            self._append_log("warn", f"标记运行中的页面失败（不影响使用）：{exc}")

    def _cancel_launch_workers(self) -> int:
        """关窗口前让在跑的启动/停止线程体面收尾：只取消"还在等端口"，不动被管理的进程。
        先全部 cancel 再统一 wait —— 反过来写，后一个 worker 要白等前一个的超时。"""
        workers = self.findChildren(LaunchWorker)
        for w in workers:
            w.cancel()
        for w in workers:
            w.wait(2000)
        return len(workers)

    def closeEvent(self, event) -> None:
        # 关窗前先让在跑的 LaunchWorker 体面收尾（cancel+wait 的顺序理由见 _cancel_launch_workers）。
        self._cancel_launch_workers()
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
    # 提权助手分支必须排在 QApplication 之前：它是被 runas 拉起的一次性无界面进程
    # （打包后没有任何参数解析器，源码运行时形如 `python main.py --bt-elevate <请求文件>`），
    # 建 QApplication / 探测运行中服务既没必要，也可能因会话隔离弹不出界面而白等。
    argv = sys.argv[1:]
    if argv and argv[0] == ELEVATE_FLAG:
        if len(argv) < 2:
            return 2
        return elevate_helper_main(argv[1])

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    ensure_dir(CONFIG_DIR)
    win = MainWindow()
    win._adopt_running()      # 认清本机在跑什么；不放 __init__——它会读写用户 running.json、探测真端口，构造窗口的测试会跟着遭殃
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
