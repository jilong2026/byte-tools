"""轻量性能快照（规则 R30）。

不引第三方依赖：计时用 time.perf_counter，内存用标准库 tracemalloc。
默认**不**开启 tracemalloc（它有持续开销），仅当 `BYTE_TOOLS_PROFILE=1`
或显式调用 `start_memory_tracking()` 时采集。

用途：把"启动多久、版本抓取耗时、下载耗时"这类事实写进导出诊断，
排查"刷新版本看起来卡死"时有据可查，而不是靠感觉。
"""
from __future__ import annotations

import os
import time
import tracemalloc
from contextlib import contextmanager
from typing import Dict, List, Optional

_STARTED_AT = time.monotonic()
_TIMERS: Dict[str, Dict[str, float]] = {}
_MEMORY_ON = False


def start_memory_tracking() -> bool:
    """开启 tracemalloc（幂等）。返回当前是否处于开启状态。"""
    global _MEMORY_ON
    if not _MEMORY_ON:
        tracemalloc.start()
        _MEMORY_ON = True
    return _MEMORY_ON


def maybe_start_from_env() -> None:
    """按环境变量决定是否开启内存采样（main 启动时调用）。"""
    if os.environ.get("BYTE_TOOLS_PROFILE") == "1":
        start_memory_tracking()


@contextmanager
def timed(name: str):
    """记录一段代码的耗时；异常也照样记账后再抛出。"""
    begin = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - begin) * 1000.0
        slot = _TIMERS.setdefault(name, {"count": 0.0, "total_ms": 0.0, "max_ms": 0.0})
        slot["count"] += 1
        slot["total_ms"] += elapsed_ms
        slot["max_ms"] = max(slot["max_ms"], elapsed_ms)


def reset() -> None:
    """清空计时（测试用）。"""
    _TIMERS.clear()


def snapshot() -> Dict[str, object]:
    """返回当前快照：运行时长、计时汇总、可选内存峰/当前。"""
    data: Dict[str, object] = {
        "uptime_sec": round(time.monotonic() - _STARTED_AT, 1),
        "timers": {
            name: {
                "count": int(v["count"]),
                "total_ms": round(v["total_ms"], 1),
                "avg_ms": round(v["total_ms"] / v["count"], 1) if v["count"] else 0.0,
                "max_ms": round(v["max_ms"], 1),
            }
            for name, v in sorted(_TIMERS.items())
        },
        "memory": None,
    }
    if _MEMORY_ON:
        current, peak = tracemalloc.get_traced_memory()
        data["memory"] = {"current_kb": round(current / 1024, 1),
                          "peak_kb": round(peak / 1024, 1)}
    return data


def format_section(limit: int = 15) -> List[str]:
    """把快照渲染成诊断报告里的若干行（按总耗时降序取前 limit 项）。"""
    snap = snapshot()
    lines = [f"进程运行时长: {snap['uptime_sec']} s"]
    mem: Optional[dict] = snap["memory"]  # type: ignore[assignment]
    if mem:
        lines.append(f"内存（tracemalloc）: 当前 {mem['current_kb']} KB / 峰值 {mem['peak_kb']} KB")
    else:
        lines.append("内存采样: 未开启（设 BYTE_TOOLS_PROFILE=1 可开启）")
    timers = snap["timers"]  # type: ignore[assignment]
    if not timers:
        lines.append("计时: （尚无记录）")
        return lines
    lines.append(f"{'阶段':<28}{'次数':>6}{'总耗时ms':>12}{'均耗时ms':>12}{'最大ms':>10}")
    ranked = sorted(timers.items(), key=lambda kv: kv[1]["total_ms"], reverse=True)[:limit]
    for name, v in ranked:
        lines.append(f"{name:<28}{v['count']:>6}{v['total_ms']:>12}{v['avg_ms']:>12}{v['max_ms']:>10}")
    return lines
