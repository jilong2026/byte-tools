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
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]   # 本文件在 tests/ 下
TEST_DIR = Path(__file__).resolve().parent


def _gh_esc(text: str, *, prop: bool = False) -> str:
    """按 GitHub Actions workflow command 的转义规则处理文本。"""
    out = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if prop:                       # 属性值还要转义 `:` 与 `,`
        out = out.replace(":", "%3A").replace(",", "%2C")
    return out


def _gh_annotate(level: str, message: str, *, file: str | None = None) -> None:
    """在 GitHub Actions 里把失败写成**注解**（本地跑时是空操作）。

    为什么值得单独做这一步：Actions 的 job 日志要带 token 才读得到，匿名请求
    `/actions/runs/<id>/jobs` 只能拿到一句 "Process completed with exit code 1"
    —— 2026-10-15 对着一条红的 dev 推送，本地 946 条全绿、却完全看不出 CI 是哪套件红。
    注解反过来**匿名就能读**（`GET /check-runs/<id>/annotations`），把套件名与输出
    尾巴塞进注解，等于给"手上没有 token 的人"留一条定位路径。
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    props = f" file={_gh_esc(file, prop=True)}" if file else ""
    print(f"::{level}{props}::{_gh_esc(message)}", flush=True)

TEST_GLOB = "bt_*_tests.py"

# ---------------------------------------------------------------------------
# 「真实配置不许被测试写」护栏
# ---------------------------------------------------------------------------
# 每个 bt_*_tests.py 都在 setUp 里把 main.CONFIG_DIR / CONFIG_FILE /
# RUNNING_FILE 指向临时目录。漏掉其中任何一个**不会报错** —— 只会安静地往用户
# 真实的 ~/.env-tools 里写。本项目已经栽过两次：
#   · 2026-10-12 新增四个组件后，真实 config.json 里凭空多出
#     kotlin / graalvm / rust / redis 四条下拉框选中项（见 bt_launch_tests.py
#     里那段"只挪 CONFIG_DIR 不生效"的注释）
#   · 2026-10-15 复查发现 ResolveLaunchVersionSemantics 至今只改 CONFIG_DIR，
#     真实 config.json / running.json 仍在被写 —— 真实 config 的 active 表里
#     `rocketmq: "5.3.1"` 就是它写的（磁盘上根本没有 rocketmq 的安装目录，
#     而这个值与用例里硬编码的版本号逐字相同）
#
# 为什么护栏放在 runner 而不是 _btprelude：这是**跨进程**断言。子进程自己看不到
# "我改了什么"，而 runner 在子进程之外，能对**每一个**套件生效 —— 包括刻意不用
# _btprelude 的 bt_startup_tests；也不必用 atexit 改退出码那套把戏，run_one 的
# 返回值天然就是门禁。
#
# 快照口径（刻意不是递归）：
#   · 顶层**所有条目名** —— 漏了 CONFIG_DIR 的用例会在真目录下拉出
#     jenkins-data 一类数据目录，条目名集合一变就咬住
#   · 只对**普通文件**记 mtime + 大小 —— 目录的 mtime 会因为服务往 data 目录里
#     写日志而变，而你完全可能在跑测试的同时开着 APP/服务，那种变化不是泄漏，
#     记进护栏只会变成假红
HOME_DIR_RE = r'^CONFIG_DIR\s*=\s*Path\.home\(\)\s*/\s*"([^"]+)"'

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


def resolve_home_dir() -> Path:
    """从 main.py 解析 CONFIG_DIR，不 import main（那要拉 PySide6）。

    与 byte-tools.spec 的 `_app_version()` 同一套做法：spec 里只想要一串常量，
    不 import 那个 GUI 模块。解析不到**必须直接炸**，不能静默返回一个猜的路径 ——
    指向错误目录的护栏等于没有护栏，而"绿着的真空护栏"是本项目明确反对的
    （见 DEVELOPMENT.md 里变异自检那几段）。
    """
    src = (REPO_ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(HOME_DIR_RE, src, re.M)
    if not m:
        raise SystemExit(
            "护栏解析不出 main.py 的 CONFIG_DIR（期望 `CONFIG_DIR = Path.home() / \"...\"`）——"
            " 改了那行就同步 tests/run_all_tests.py 的 HOME_DIR_RE")
    return Path.home() / m.group(1)


def snapshot_home(d: Path) -> dict[str, tuple[str, int, int]]:
    """快照顶层条目：{名字: (类型, mtime_ns, 大小)}。目录只记类型（见上方口径说明）。"""
    snap: dict[str, tuple[str, int, int]] = {}
    if not d.is_dir():
        return snap
    with os.scandir(d) as it:
        for entry in it:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            snap[entry.name] = ("d", 0, 0) if is_dir else ("f", st.st_mtime_ns, st.st_size)
    return snap


def home_delta(before: dict, after: dict) -> list[str]:
    """列出两次快照的差异，供护栏报错。空列表表示没被碰过。"""
    out = []
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name), after.get(name)
        if b == a:
            continue
        if b is None:
            out.append(f"新增 {name}")
        elif a is None:
            out.append(f"删除 {name}")
        else:
            why = []
            if b[0] != a[0]:
                why.append("类型变了")
            if b[1] != a[1]:
                why.append("mtime 变了")
            if b[2] != a[2]:
                why.append("大小变了")
            out.append(f"改写 {name}（{'/'.join(why)}）")
    return out


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
    home_dir = resolve_home_dir()
    print(f"解释器：{python}")
    print(f"真实配置目录：{home_dir}（每个套件跑完都比一次，被改即判红）")
    print(f"待跑文件：{len(files)} 个\n")

    results = []
    total_tests = 0
    failed = 0
    # 失败详情要**打印出来**（2026-10-15 修）：此前 run_one 明明算了 detail，
    # main 却只打一行"失败 N 用例"，于是 CI 日志里只有总结、没有 traceback ——
    # 2026-10-14 那次 CI 红就是这样，只能看到"9 个套件失败"却不知道为什么。
    failures_detail: list[tuple[str, str]] = []

    for f in files:
        sys.stdout.write(f"  {f.name:<38} ")
        sys.stdout.flush()
        before = snapshot_home(home_dir)
        ok, detail, elapsed, count = run_one(f, python, args.verbose)
        delta = home_delta(before, snapshot_home(home_dir))
        if delta:
            ok = False
            leaked = "\n".join(f"  {line}" for line in delta[:12])
            detail = (
                f"真实配置目录被这个套件改写了（{home_dir}）：\n{leaked}\n"
                "  某个 setUp 的沙箱漏了 CONFIG_DIR / CONFIG_FILE / RUNNING_FILE 之一 ——"
                " 后两个是 import 期从 CONFIG_DIR 拼出来的**模块常量**，只挪 CONFIG_DIR 不生效。\n"
                "  如果你同时在跑 APP 或某个组件服务，先关掉再重跑一次确认。\n\n"
                + detail
            )
        total_tests += count
        results.append((f.name, ok, elapsed, count))
        if ok:
            print(f"通过  {count:>4} 用例  {elapsed:6.2f}s")
        else:
            failed += 1
            failures_detail.append((f.name, detail))
            print(f"失败  {count:>4} 用例  {elapsed:6.2f}s")

    print("\n" + "=" * 72)
    for name, ok, elapsed, count in results:
        print(f"  {'OK  ' if ok else 'FAIL'}  {name:<38} {count:>4} 用例  {elapsed:6.2f}s")
    print("=" * 72)
    print(f"合计 {total_tests} 条用例，{len(files)} 个文件，"
          f"{len(files) - failed} 通过 / {failed} 失败")

    if failed:
        # 先把每套件的失败输出原样贴出来（这是 CI 日志里唯一能定位问题的东西），
        # 再给"怎么单跑重看"的提示。
        for name, detail in failures_detail:
            print("\n" + "-" * 72)
            print(f"▼ {name} 的失败输出（末尾若干行）")
            print("-" * 72)
            print(detail)
            # 日志要 token 才读得到，注解匿名就能读 —— 两处都写，别只写一处。
            tail = "\n".join(l for l in detail.splitlines() if l.strip())[-1200:]
            _gh_annotate("error",
                         f"{name} 失败（{len(files) - failed}/{len(files)} 个文件通过）。"
                         f"输出尾部：\n{tail}",
                         file=f"tests/{name}")
        _gh_annotate("notice",
                     f"护栏结果：{total_tests} 条用例 / {len(files)} 个文件，"
                     f"{len(files) - failed} 通过 / {failed} 失败")
        print("\n以下文件失败，重跑单个文件看详情：")
        for name, ok, _, _ in results:
            if not ok:
                print(f"  .venv\\Scripts\\python.exe -u tests/{name}")
        return 1
    _gh_annotate("notice", f"护栏全绿：{total_tests} 条用例 / {len(files)} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())