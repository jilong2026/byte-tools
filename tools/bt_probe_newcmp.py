"""新组件全源实测：PowerShell / Nginx 的「抓取到的每个版本 × 每个平台 × 每条 URL」全跑一遍。

判据沿用项目 R1 规矩：status==200 且累计字节 >= DOWNLOAD_MIN_VALID_BYTES。
大陆源单独计数（华为云两子域 / 三个 gh 加速器）。
"""
import concurrent.futures as cf
import importlib.util
import os
import platform
import sys
import warnings

warnings.filterwarnings("ignore")
platform._wmi_query = lambda *_a, **_k: (_ for _ in ()).throw(OSError("stub"))

spec = importlib.util.spec_from_file_location(
    "btmain", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"))
main = importlib.util.module_from_spec(spec)
sys.modules["btmain"] = main
spec.loader.exec_module(main)

import requests  # noqa: E402

CONT = ("ghproxy.net", "gh-proxy.com", "ghfast.top", "huaweicloud")


def probe(u):
    try:
        with requests.get(u, stream=True, timeout=45, headers=main.HTTP_UA,
                          allow_redirects=True, verify=False) as r:
            magic, total = b"", 0
            for chunk in r.iter_content(65536):
                if len(magic) < 2:
                    magic = (magic + chunk)[:2]
                total += len(chunk)
                if total > 1024 * 1024:
                    break
            kind = "zip" if magic[:2] == b"PK" else "gzip" if magic[:2] == b"\x1f\x8b" else "other"
            return r.status_code, total, kind
    except Exception as e:  # noqa: BLE001
        return type(e).__name__, 0, "err"


rows = []
for key in ("powershell", "nginx"):
    for cv in main.FETCHERS[key]():
        for os_key, urls in (cv.url_list_map or {}).items():
            rows.append((key, os_key, cv.version, urls))

tasks = [(k, o, v, i, u) for (k, o, v, urls) in rows for i, u in enumerate(urls, 1)]
print(f"组合数：{len(rows)}   URL 总数：{len(tasks)}", flush=True)

res = {}
with cf.ThreadPoolExecutor(max_workers=12) as ex:
    fut = {ex.submit(probe, t[4]): t for t in tasks}
    for f in cf.as_completed(fut, timeout=2400):
        res[fut[f]] = f.result()

print(f"{'key':12} {'os':8} {'version':10} {'全ok':7} {'大陆ok':7} detail")
print("-" * 120)
bad = []
for (k, o, v, urls) in rows:
    oks, cont, cells = 0, 0, []
    for i, u in enumerate(urls, 1):
        code, total, kind = res[(k, o, v, i, u)]
        good = code == 200 and total >= main.DOWNLOAD_MIN_VALID_BYTES and kind != "other"
        if good:
            oks += 1
            if any(c in u for c in CONT):
                cont += 1
        cells.append(f"{i}:{'OK' if good else f'{code}/{kind}'}")
    if oks != len(urls) or cont < 2:
        bad.append((k, o, v, oks, len(urls), cont))
    print(f"{k:12} {o:8} {v:10} {oks}/{len(urls):5} {cont:7} {' '.join(cells)}")

print()
print("=" * 120)
print(f"结果：{len(rows)} 组合，异常 {len(bad)} 条")
for b in bad:
    print("  BAD", b)
