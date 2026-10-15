"""官网登记表连通性体检（COMPONENT_OFFICIAL_URLS 的 88 条）。

为什么需要这个工具：`COMPONENT_OFFICIAL_URLS` 里那 88 条是**人工核实的事实**
（见 DEVELOPMENT.md 规则 R19），而项目改域名、官网改路径是会悄悄发生的 ——
单元测试只能保证"每个组件都登记了"，保证不了"登记的值今天还能打开"。
这个脚本补的就是后半句。

⚠ 它**不进 CI**：官网偶发抽风不该让构建红，护栏在 tests/ 里就够了。
   需要时手动跑，结论自己判断。

用法：
    .venv/Scripts/python.exe -u tools/bt_check_official_urls.py

输出三类结果，各自含义不同，别混为一谈：
    OK           —— 直接拿到 200，这条没问题
    反爬(BLOCK)  —— 403/429。**站点多半是好的**，是它按 User-Agent 拦自动化。
                    换 curl/8.0 再试一次能区分（下面自动做）
    不可达       —— DNS 解析不出来，或 TCP 连不上。这才可能是"域名没了"，
                    也可能只是本机网络到不了那个站点 —— 所以同时打印 DNS 结果。

退出码：全部 OK 或仅反爬 → 0；存在不可达 → 1。
"""

from __future__ import annotations

import socket
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import _btprelude  # noqa: E402,F401  置 offscreen 与 sys.path
import main  # noqa: E402

# 两个 UA 各试一次：不少站点（如 mysql.com）按 UA 拦自动化，Chrome UA 拿 403、
# curl UA 拿 200。只用一个 UA 就会把"站点活着"误判成"链接坏了"。
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
PLAIN_UA = "curl/8.0"

CONNECT_TIMEOUT = 12
RETRIES = 2
WORKERS = 8


def _fetch(url: str, ua: str) -> tuple[str, str]:
    """请求一次 URL，返回 (分类, 详情)。

    分类取值：OK / HTTP<code> / <异常类名>
    """
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT) as r:
            return "OK", f"200 -> {r.geturl()}"
    except urllib.error.HTTPError as e:
        return f"HTTP{e.code}", ""
    except Exception as e:  # 超时 / TLS / DNS / 连接重置等都归这里
        return type(e).__name__, ""


def classify(url: str) -> tuple[str, str]:
    """把一条 URL 归类为 OK / BLOCK / UNREACHABLE，并带上判断依据。

    **两个 UA 必须都试完**才能下结论。这段逻辑第一版写错了：在浏览器 UA 拿到
    403 时就跳出了循环，于是 curl UA 根本没被请求到，把 mysql.com 那两条
    误判成"两种 UA 都被拒"。而实际上 curl/8.0 请求 mysql.com 直接 200 ——
    不试第二个 UA 就分不清"站点拦自动化"和"链接坏了"。

    所以这里刻意**不在拿到 HTTP 错误时提前返回**：HTTP 错误只记录、不终止，
    必须把 PLAIN_UA 也试过，才知道这个 403 是不是 UA 造成的。
    """
    last_status, last_detail = "", ""
    saw_http_error = False

    for ua in (BROWSER_UA, PLAIN_UA):
        for _ in range(RETRIES):
            status, detail = _fetch(url, ua)
            if status == "OK":
                return "OK", detail
            if status.startswith("HTTP"):
                # 换 UA 前把这个错误记住，继续试下一个 UA（关键：不要提前返回）
                saw_http_error = True
                last_status, last_detail = status, detail
                break
            last_status, last_detail = status, detail
            time.sleep(1.0)

    if saw_http_error:
        # 两个 UA 都拿到了 HTTP 错误 —— 说明不是 UA 造成的，是站点/路径本身的事
        if last_status in ("HTTP403", "HTTP429"):
            return "BLOCK", f"{last_status}（两种 UA 都被拒；域名有效，只是拦自动化）"
        return last_status, last_detail

    # 两个 UA 都连不到 HTTP 层。补一个 DNS 判断，区分"域名没了"和"本机到不了"。
    host = urlsplit(url).hostname or ""
    try:
        ip = socket.gethostbyname(host)
    except Exception as e:
        return "UNREACHABLE", f"{last_status}；且 DNS 解析失败（{type(e).__name__}）—— 域名可能真没了"
    return "UNREACHABLE", f"{last_status}；DNS 正常（{ip}）—— 多半是本机网络到不了该站点"


def main_entry() -> int:
    registry = main.COMPONENT_OFFICIAL_URLS
    keys = {c.key for c in main.build_components()}

    missing = sorted(keys - set(registry))
    if missing:
        print(f"登记表缺 key（先补表再体检）：{missing}\n")

    items = sorted(registry.items())
    results: list[tuple[str, str, str, str]] = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for key, url, (state, detail) in pool.map(
                lambda kv: (kv[0], kv[1], classify(kv[1])), items):
            results.append((state, key, url, detail))

    results.sort(key=lambda r: (r[0] == "OK", r[1]))

    buckets: dict[str, list] = {}
    for state, key, url, detail in results:
        buckets.setdefault(state, []).append((key, url, detail))

    print(f"共体检 {len(results)} 条：")
    for state in ("OK", "BLOCK", "UNREACHABLE"):
        n = len(buckets.get(state, []))
        print(f"  {state:12} {n}")

    for state in ("UNREACHABLE", "BLOCK"):
        rows = buckets.get(state, [])
        if not rows:
            continue
        print(f"\n===== {state} =====")
        for key, url, detail in rows:
            print(f"  {key:18} {url}")
            print(f"  {'':18} {detail}")

    bad = len(buckets.get("UNREACHABLE", []))
    print("\n结论："
          + ("全部可达" if not bad
             else f"有 {bad} 条需要人工确认（改路径 / 换域名 / 只是本机网络问题）"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main_entry())