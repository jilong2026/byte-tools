"""多源故障转移下载线程（从 main.py 抽出，行为逐字不变，规则 R1.4 / R30）。

依赖注入是刻意的：main 里测试大量用 `mock.patch.object(main, "http_session")`
做离线桩。若本模块在 import 时直接抓取 session，桩点就失效了。因此
`configure()` 接收的是**延迟解引用的函数**（main 传 lambda），每次下载时才解析。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from .constants import (
    DOWNLOAD_CONNECT_TIMEOUT,
    DOWNLOAD_MIN_VALID_BYTES,
    DOWNLOAD_READ_TIMEOUT,
)


_DEP_SESSION: Optional[Callable[[], object]] = None
_DEP_ENSURE_DIR: Optional[Callable[[Path], None]] = None
_DEP_HUMAN_SIZE: Optional[Callable[[float], str]] = None


def configure(
    session_factory: Callable[[], object],
    ensure_dir_fn: Callable[[Path], None],
    human_size_fn: Callable[[float], str],
) -> None:
    """注入运行期依赖（main 启动时调用一次）。

    三个入参都必须是**函数**而不是已经取好的对象：session 需要每次调用重新解析，
    这样 `main.http_session` 被测试替换后立刻生效。
    """
    global _DEP_SESSION, _DEP_ENSURE_DIR, _DEP_HUMAN_SIZE
    _DEP_SESSION = session_factory
    _DEP_ENSURE_DIR = ensure_dir_fn
    _DEP_HUMAN_SIZE = human_size_fn


def _session():
    if _DEP_SESSION is None:
        raise RuntimeError("core.download.configure() 尚未调用")
    return _DEP_SESSION()


def _ensure_dir(path: Path) -> None:
    if _DEP_ENSURE_DIR is None:
        raise RuntimeError("core.download.configure() 尚未调用")
    _DEP_ENSURE_DIR(path)


def _human_size(num: float) -> str:
    if _DEP_HUMAN_SIZE is None:
        raise RuntimeError("core.download.configure() 尚未调用")
    return _DEP_HUMAN_SIZE(num)


class DownloadWorker(QThread):
    """多源故障转移下载线程（详见 DEVELOPMENT.md R1.4）。

    按 urls 列表顺序依次尝试下载，第一个成功的写入目标文件；
    单 URL 失败自动切换到下一个，所有源失败才判定为彻底失败。
    """

    progress = Signal(int, int)  # (downloaded_bytes, total_bytes)
    log = Signal(str, str)  # (level, message)  level in {"info","warn","error","ok"}
    finished_ok = Signal(str)  # 保存的本地文件绝对路径
    finished_fail = Signal(str)  # 错误信息

    _CHUNK_SIZE = 64 * 1024

    def __init__(self, urls: List[str], dest: Path,
                 parent: Optional[QObject] = None,
                 expect_magic: bytes = b"") -> None:
        super().__init__(parent)
        self.urls = list(urls)
        self.dest = dest
        self.expect_magic = bytes(expect_magic or b"")
        self._cancel = False
        self._cancelled = False
        self._failures: List[str] = []

    def cancel(self) -> None:
        """取消下载；run() 内每个 chunk 写入前检查 _cancel 标志。"""
        self._cancel = True

    def run(self) -> None:  # noqa: D401
        """QThread 入口：按 urls 顺序尝试下载。

        两个约定：**终态信号恰好发一次**，且**任何异常都不许逃出 run()**。
        QThread 里抛异常在 Windows 上是进程级 abort（0xC0000409 / 退出码 127，
        一行 traceback 都没有），而且上层收不到 finished_fail 会永远停在"下载中"。
        """
        try:
            _ensure_dir(self.dest.parent)
        except OSError as exc:
            self.log.emit("error", f"建不出下载目录 {self.dest.parent}：{exc}")
            self.finished_fail.emit(f"下载目录不可用：{exc}")
            return
        for idx, url in enumerate(self.urls, 1):
            if self._cancel:
                break
            try:
                self.log.emit("info", f"开始下载（第 {idx}/{len(self.urls)} 个源）：{url}")
                if self._try_download(url):
                    return
            except Exception as exc:  # noqa: BLE001 - 任一源失败都只切下一个
                self._failures.append(f"{url} -> {exc}")
                if idx < len(self.urls):
                    self.log.emit("warn",
                        f"第 {idx} 个源下载失败：{exc}\n"
                        f"即将切换到下一个源：{self.urls[idx]}")
                else:
                    self.log.emit("error",
                        f"第 {idx} 个源（最后一个）下载失败：{exc}")
        if self._cancelled:
            self._emit_cancel()
            return
        summary = "所有镜像与官网地址均下载失败，已尝试：\n" + "\n".join(self._failures)
        self.log.emit("error", summary)
        self.finished_fail.emit("所有下载源均不可用")

    def _try_download(self, url: str) -> bool:
        """尝试从单个 URL 流式下载；成功 True，否则 False 换下一个源。"""
        timeout = (DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT)
        with _session().get(url, stream=True, timeout=timeout,
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
                        self._cancelled = True
                        return False
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total)
            # 镜像站会用「200 + 空体/软 404 页」冒充存在的文件
            if downloaded < DOWNLOAD_MIN_VALID_BYTES or (total and downloaded < total):
                self.log.emit("warn",
                    f"第 {url} 只返回 {downloaded} 字节"
                    f"（声明 {total}），判定该源无效，换下一个源。")
                tmp.unlink(missing_ok=True)
                return False
            # 魔数校验：字节数够不代表内容对（200 + 12KB HTML 的假源就够）
            if self.expect_magic:
                with open(tmp, "rb") as probe:
                    head = probe.read(len(self.expect_magic))
                if head != self.expect_magic:
                    self.log.emit("warn",
                        f"第 {url} 的内容开头是 {head!r}，不是预期的 {self.expect_magic!r}"
                        "（多半是镜像站拿一个网页应付了这个文件），换下一个源。")
                    tmp.unlink(missing_ok=True)
                    return False
            tmp.replace(self.dest)
        self.log.emit("ok",
            f"下载完成：{self.dest} ({_human_size(self.dest.stat().st_size)})，"
            f"实际使用源：{url}")
        self.finished_ok.emit(str(self.dest))
        return True

    def _emit_cancel(self) -> None:
        """用户取消时统一发射 finished_fail（沿用约定消息，便于上层判断不弹窗）。"""
        self.finished_fail.emit("用户取消")
