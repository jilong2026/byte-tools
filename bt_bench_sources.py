"""实测每个组件的下载源：连通性 + 下载速度。

为什么要实测而不是照抄 2026-09 的报告：
  1. 那份报告只判「通不通」，没有速度数据 —— 而用户要的是"按速度优先级排序"；
  2. 镜像站的速度随时会变（不同地区、不同运营商、不同时段差异很大）。

测速方法：Range 请求取样。用Range: bytes=0-N 而不是把整个包装下来 ——
  elasticsearch 有 600MB，全下要 10 分钟；只取前 4MB 就能算出真实吞吐。
  坑：不少镜像站**忽略 Range**，会回 200 + 整个流。所以读满 N 字节就 break，
  连接靠 close 关掉 —— 不读完的话测出来的是"首包延迟"而不是吞吐。

判定「源可用」= 状态码 200 且实收字节 >= 512K（太小可能是错误页）。
判魔数：zip=PK\\x03\\x04、gzip=\\x1f\\x8b、exe/war 另有 MZ/PK。只看状态码不算数，
这是 2026-09 那轮就踩过的坑（软 404 回 200 + HTML）。

输出 bt_source_bench.json，供 _reorder_sources.py 消费。
"""
import concurrent.futures as cf
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import requests

import main

SAMPLE_BYTES = 4 * 1024 * 1024      # 取样 4MB 算吞吐
MIN_OK_BYTES = 512 * 1024            # 实收低于此判为不可用（多半是错误页）
UA = {"User-Agent": "byte-tools"}
PROBE_TIMEOUT = (6, 25)              # (连接, 读取)——读取要给够，大件首包可能慢
PARALLEL = 8                         # 并发线程数


def probe(url: str) -> dict:
    """探一个 URL：连通性 + 取样下载速度。返回一条结果记录。"""
    rec = {"url": url, "ok": False, "status": None, "bytes": 0,
           "mbps": 0.0, "note": "", "host": requests.utils.urlparse(url).netloc}
    t0 = time.time()
    got = bytearray()
    try:
        with requests.get(url, stream=True, timeout=PROBE_TIMEOUT,
                          allow_redirects=True, headers={**UA, "Range": f"bytes=0-{SAMPLE_BYTES - 1}"}) as r:
            rec["status"] = r.status_code
            # 206=认了 Range，200=忽略 Range 整个流（也要能测）
            for chunk in r.iter_content(64 * 1024):
                if not chunk:
                    continue
                got.extend(chunk)
                if len(got) >= SAMPLE_BYTES:
                    break
    except Exception as exc:                      # 任何异常都算这个源不通
        rec["note"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        rec["secs"] = round(time.time() - t0, 2)
        return rec

    rec["bytes"] = len(got)
    rec["secs"] = round(max(time.time() - t0, 0.001), 2)
    # 200 / 206 都算成功：206=镜像认了我们的 Range 只给这一段（正是我们想要的），
    # 200=忽略 Range 整个流。2026-10-06 第一次跑时我只接受 200，
    # 结果所有"守规矩"的镜像全被判成不可通 —— 判据写错，不是源坏了。
    if rec["status"] not in (200, 206):
        rec["note"] = f"HTTP {rec['status']}"
        return rec
    if len(got) < MIN_OK_BYTES:
        rec["note"] = f"实收仅 {len(got)} 字节（多半是错误页/软 404）"
        return rec
    head = bytes(got[:4])
    if head[:2] == b"PK" or head[:2] == b"MZ" or head[:2] == b"\x1f\x8b":
        rec["ok"] = True
        rec["mbps"] = round(len(got) / 1048576 / rec["secs"], 2)
    else:
        rec["note"] = f"魔数异常 {head!r}"
    return rec


def all_targets() -> list:
    """列出全部待测 URL：(key, version, url)。按组件的首个版本取样。"""
    out = []
    comps = main.build_components()
    for c in comps:
        fn = getattr(main, f"_{c.key}_urls", None)
        if fn is None:
            # jdk / powershell / conda 的地址是运行时从厂商 API 抓的，
            # 但 build_components 时已经带着抓好的 url_map，直接取它。
            for cv in c.versions[:1]:
                u = cv.url_map.get(main.CURRENT_OS) or (next(iter(cv.url_map.values())) if cv.url_map else None)
                if u:
                    out.append((c.key, cv.version, u))
            continue
        try:
            got = fn(c.versions[0].version)
        except Exception as exc:
            print(f"[SKIP] {c.key}: 构造器抛异常 {exc}")
            continue
        urls = got.get(main.CURRENT_OS) if isinstance(got, dict) else got
        for u in urls or []:
            out.append((c.key, c.versions[0].version, u))
    return out


def main_run() -> None:
    targets = all_targets()
    print(f"待测 {len(targets)} 个 URL（{len({t[0] for t in targets})} 个组件），"
          f"每个取样 {SAMPLE_BYTES // 1048574}MB，并发 {PARALLEL}\n")
    results = {}
    done = 0
    with cf.ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        futs = {ex.submit(probe, url): (key, url) for key, _, url in targets}
        for fut in cf.as_completed(futs):
            key, url = futs[fut]
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {"url": url, "ok": False, "status": None, "bytes": 0, "mbps": 0.0,
                       "note": f"探测线程崩了 {exc}", "host": url}
            results.setdefault(key, []).append(rec)
            done += 1
            flag = "ok  " if rec["ok"] else "FAIL"
            print(f"  [{done:3d}/{len(targets)}] {flag} {key:14} "
                  f"{rec.get('mbps', 0):6.2f} MB/s  {rec['note'][:38]:38} {rec['host'][:34]}")

    Path("bt_source_bench.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    ok = sum(1 for k in results for r in results[k] if r["ok"])
    total = sum(len(v) for v in results.values())
    print(f"\n=== 通 {ok}/{total}；结果写入 bt_source_bench.json ===")
    for key in sorted(results):
        rs = results[key]
        good = sum(1 for r in rs if r["ok"])
        if good != len(rs):
            print(f"  {key:14} {good}/{len(rs)} 通"
                  + ("   全挂!" if good == 0 else ""))


if __name__ == "__main__":
    main_run()