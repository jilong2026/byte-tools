"""组件「版本 / 产物」数据模型（从 main.py 抽出，规则 R30）。

为什么只有这两个类：`Component` 带行为（install_dir 等，依赖 CONFIG_DIR 与
EnvManager），留在 main.py；这里收的是**纯数据 + 纯派生**的部分。

运行期依赖注入：
- 当前系统：`configure(os_provider=...)`，main 传 `lambda: CURRENT_OS`。
  这样测试 `main.CURRENT_OS = "Linux"` 之后，本模块的派生结果同样跟着变
  （直接 import CURRENT_OS 会拿到 import 时的快照，桩就失效了）。
- 体积文案：`human_size`，同样延迟解引用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


ARTIFACT_LABELS: Dict[str, str] = {
    "exe": "exe 安装器（走安装向导）",
    "zip": "zip 便携包（解压即用）",
    "cli": "命令行版（解压后把可执行文件放进 PATH）",
    "portable": "免安装便携版（exe，双击即用）",
    "msi": "msi 安装包（走 Windows 安装向导）",
}

_OS_PROVIDER: Optional[Callable[[], str]] = None
_HUMAN_SIZE: Optional[Callable[[float], str]] = None


def configure(os_provider: Callable[[], str],
              human_size_fn: Callable[[float], str]) -> None:
    """注入运行期依赖（main 启动时调用一次）。"""
    global _OS_PROVIDER, _HUMAN_SIZE
    _OS_PROVIDER = os_provider
    _HUMAN_SIZE = human_size_fn


def _os() -> str:
    return _OS_PROVIDER() if _OS_PROVIDER is not None else ""


def _human(n: float) -> str:
    return _HUMAN_SIZE(n) if _HUMAN_SIZE is not None else str(n)


@dataclass
class DownloadArtifact:
    """一个版本的**一种**产物（安装器 vs 便携包是两个不同文件）。"""

    fmt: str                        # "exe" / "zip" —— 同时决定落盘后缀与魔数
    label: str                      # 界面上怎么称呼它
    urls: List[str]                 # 已按 R1 排好序的源列表（当前平台）
    size: int = 0                   # 官方声明的字节数，0 = 未知

    def menu_text(self) -> str:
        return f"{self.label} · {_human(self.size)}" if self.size else self.label


@dataclass
class ComponentVersion:
    """描述一个组件版本对应的下载 URL 及归档格式。"""

    version: str
    url_map: Dict[str, str]
    archive_map: Dict[str, str] = field(default_factory=dict)
    url_list_map: Dict[str, List[str]] = field(default_factory=dict)
    artifacts: List[DownloadArtifact] = field(default_factory=list)

    def download_artifacts(self) -> List[DownloadArtifact]:
        """「下载 ▾」要列的产物清单。"""
        if self.artifacts:
            return list(self.artifacts)
        ext = self.archive_for_current() or "bin"
        return [DownloadArtifact(fmt=ext,
                                 label=ARTIFACT_LABELS.get(ext, ext),
                                 urls=self.urls_for_current())]

    def url_for_current(self) -> Optional[str]:
        """当前系统的首选下载地址（多源取首个镜像）。"""
        urls = self.urls_for_current()
        return urls[0] if urls else None

    def urls_for_current(self) -> List[str]:
        """当前系统的下载 URL 列表（多源优先，回退单 URL 模式）。"""
        os_name = _os()
        if os_name in self.url_list_map and self.url_list_map[os_name]:
            return list(self.url_list_map[os_name])
        url = self.url_map.get(os_name)
        return [url] if url else []

    def archive_for_current(self) -> str:
        os_name = _os()
        if os_name in self.archive_map:
            return self.archive_map[os_name]
        urls = self.urls_for_current()
        url = urls[0] if urls else ""
        if url.endswith(".zip"):
            return "zip"
        if url.endswith(".tar.gz") or url.endswith(".tgz"):
            return "tar.gz"
        return "zip"
