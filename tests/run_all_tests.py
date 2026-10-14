"""全量护栏测试 runner：一条命令跑完所有 bt_*_tests.py。

跑法：
    .venv/Scripts/python.exe -u run_all_tests.py              # 跑全部
    .venv/Scripts/python.exe -u run_all_tests.py bt_launch_tests bt_grid_layout_tests
    .venv/Scripts/python.exe -u run_all_tests.py --list

为什么需要它（2026-10-14 新增）：

1. **这些文件不会被任何默认发现机制识别**。unittest 默认 pattern 是 `test*.py`、
   pytest 是 `test_*.py` / `*_test.py`，而本项目的命名是 `bt_*_tests.py` ——
   三条都不匹配。`python -m unittest discover` 与 `pytest` 都是**收集到 0 条**。
   也就是说 834 条用例在自动化流程里等于不存在。

2. **CI 完全不跑测试**。release.yml 原本只有 build 与 sync 两个 job。

3. **每个文件各自复制三段前置代码**（WMI 桩 / QT_QPA_PLATFORM=offscreen /
   QApplication）。漏抄其中一段的故障症状是"进程以 127 退出、日志里一行
   traceback 都没有"（Qt 在没有 QApplication 时直接 abort），极难定位。

本 runner 逐个文件用**子进程**跑（不是 import）——这是刻意的：
   - 各文件互不污染对方 monkey patch 的模块级状态（`main.setattr` 有 168 处）
   - 某个文件里 Qt 直接 abort 不会带走整批
   - 跨文件 import（如 bt_download_only_tests 引用 bt_multiversion_tests 的
     EnvSandbox）仍按原样工作

退出码：有任何一个文件失败就返回 1，可以直接当 CI 门禁用。
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]   # 本文件在 tests/ 下
TEST_DIR = Path(__file__).resolve().parent
TEST_GLOB = "bt_*_tests.py"

# 绕开 PySide6 弹窗的关键环境变量：Qt 需要一个"无显示"的平台插件。
# 各测试文件自己也会 setdefault 一份，这里统一给是为了让**本 runner 的子进程**
# 在文件还没跑到那行之前就是安全的。
CHILD_ENV = {
    "QT_QPA_PLATFORM": "offscreen",
    # 避免 Qt 把警告打到 stderr 干扰我们自己的输出
    "QT_LOGGING_RULES": "*.debug=false;qt.qpa.*=false",
}

# 默认解释器优先级：先用项目自己的 .venv（与一键脚本一致），再退 PATH。
VENV_PYTHON_CANDIDATES = (
    REPO_ROOT / ".venv" / "Scripts" / "python.exe",
    REPO_ROOT / ".venv" / "bin" / "python",
)


def _quote_flag() -> str:
    """Windows 控制台是 GBK，测试里可能有 UnicodeDecodeError。

    加了 PYTHONIOENCODING 与 PYTHONUTF8=1，让子进程无论落在哪个解释器上
    都能用 UTF-8 输出中文，不会因为一个用例里的中文断言就整体崩在解码上。
    """
    return "utf-8"


def resolve_python() -> str:
    """挑一个可用的解释器：优先项目 .venv，其次 PATH 上的 python。"""
    for cand in VENV_PYTHON_CANDIDATES:
        if cand.is_file():
            return str(cand)
    return sys.executable or "python"


def discover(selected: list[str] | None) -> list[Path]:
    """列出要跑的文件。

    入参 selected: 显式指定的文件名（可不含 .py）；为空则按 glob 全量。
    返回:          排序后的 Path 列表。
    """
    if selected:
        out = []
        for name in selected:
            p = Path(name if name.endswith(".py") else f"{name}.py")
            if not p.is_absolute():
                # 先当"tests/ 下的文件名"找，找不到再按仓库根的相对路径找 ——
                # 显式指定时两种写法都常见（`bt_launch_tests` 与 `tests/bt_launch_tests.py`）。
                cand = TEST_DIR / p
                p = cand if cand.is_file() else REPO_ROOT / p
            if not p.is_file():
                raise SystemExit(f"找不到测试文件：{p}")
            out.append(p)
        return out
    return sorted(Path(f) for f in glob.glob(str(TEST_DIR / TEST_GLOB)))


def run_one(path: Path, python: str, verbose: bool) -> tuple[bool, str, float, int]:
    """跑单个测试文件。

    入参 path:    测试文件路径
    入参 python:  解释器
    入参 verbose:  True 时把子进程输出原样透出
    返回:         (是否通过, 判定依据摘要, 耗时秒, 解析到的用例数)
    """
    env = dict(os.environ)
    env.update(CHILD_ENV)
    env["PYTHONIOENCODING"] = _quote_flag()
    env["PYTHONUTF8"] = "1"

    started = time.monotonic()
    proc = subprocess.run(
        [python, "-u", str(path)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    elapsed = time.monotonic() - started
    out = (proc.stdout or "") + (proc.stderr or "")

    # "OK" 收尾即通过；unittest 的失败摘要一定带 FAILED 或一条 ERROR/FAIL: 头
    passed = proc.returncode == 0 and ("\nOK" in f"\n{out}" or out.rstrip().endswith("OK"))

    import re
    m = re.search(r"Ran (\d+) test", out)
    count = int(m.group(1)) if m else 0

    if verbose or not passed:
        tail = out.strip().splitlines()[-25:]
        detail = "\n".join(tail)
    else:
        detail = ""

    if not passed and not detail:
        detail = f"退出码 {proc.returncode}，且没有可解析的 unittest 摘要（疑似进程崩溃/退出）"

    return passed, detail, elapsed, count


def main() -> int:
    ap = argparse.ArgumentParser(
        description="跑全部 bt_*_tests.py 护栏用例（退出码非 0 表示有失败）")
    ap.add_argument("names", nargs="*", help="只跑指定文件（可省略 .py）")
    ap.add_argument("--list", action="store_true", help="只列出文件，不执行")
    ap.add_argument("-v", "--verbose", action="store_true", help="透出每个文件的完整输出")
    args = ap.parse_args()

    files = discover(args.names)
    if not files:
        print("没有找到任何 bt_*_tests.py")
        return 1

    if args.list:
        for f in files:
            print(f.name)
        return 0

    python = resolve_python()
    print(f"解释器：{python}")
    print(f"待跑文件：{len(files)} 个\n")

    results = []
    total_tests = 0
    failed = 0

    for f in files:
        sys.stdout.write(f"  {f.name:<38} ")
        sys.stdout.flush()
        ok, detail, elapsed, count = run_one(f, python, args.verbose)
        total_tests += count
        results.append((f.name, ok, elapsed, count))
        if ok:
            print(f"通过  {count:>4} 用例  {elapsed:6.2f}s")
        else:
            failed += 1
            print(f"失败  {count:>4} 用例  {elapsed:6.2f}s")

    print("\n" + "=" * 72)
    for name, ok, elapsed, count in results:
        print(f"  {'OK  ' if ok else 'FAIL'}  {name:<38} {count:>4} 用例  {elapsed:6.2f}s")
    print("=" * 72)
    print(f"合计 {total_tests} 条用例，{len(files)} 个文件，"
          f"{len(files) - failed} 通过 / {failed} 失败")

    if failed:
        print("\n以下文件失败，重跑单个文件看详情：")
        for name, ok, _, _ in results:
            if not ok:
                print(f"  .venv\\Scripts\\python.exe -u tests/{name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())