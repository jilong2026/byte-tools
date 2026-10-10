"""为离线 jdk 清单采集确切文件名（4 个大版本 x 2 个镜像站）。

背景：离线清单里`resolve_mirrors=False` 不许联网，所以 jdk 只有
api.adoptium.net 一个源 —— 而它 302 到 github.com，本机 21/17 都连不上，
真实用户装 JDK 21 必然失败。

修法：离线清单直接写镜像站的确定路径（目录结构固定，文件名实测采集），
api.adoptium.net 退到末位兜底。本脚本采集那份文件名。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # 仓库根（本脚本在 tools/ 下）
import requests

import main

UA = {"User-Agent": "byte-tools"}
MAJORS = ("21", "17", "11", "8")
OUT = Path("bt_jdk_files.json")


def main_run() -> None:
    arch, os_dir, ext = main._adoptium_dirs()[main.CURRENT_OS]
    print(f"arch={arch} os_dir={os_dir} ext={ext}\n")
    found = {}
    for base_name, sub in main._ADOPTIUM_LAYOUTS:
        base = main._mb(base_name)[0] + sub
        for m in MAJORS:
            try:
                d = requests.get(f"{base}/{m}/jdk/{arch}/{os_dir}/",
                                 timeout=15, headers=UA)
                names = main._re.findall(r'href="([^"?]+)"', d.text)
                picked = main._adoptium_pick(names, m, arch, os_dir, ext)
            except Exception as exc:
                print(f"  {base_name}/{m}: 失败 {type(exc).__name__}")
                continue
            if picked:
                found.setdefault(m, {})[base_name] = f"{base}/{m}/jdk/{arch}/{os_dir}/{picked}"
                print(f"  {base_name:6}/{m:3}: {picked}")
            else:
                print(f"  {base_name:6}/{m:3}: 没挑出合适包")

    OUT.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完整: {sorted(found)}  → {OUT}")
    print("\n=== 抽样验速（各镜像 8MB）===")
    for m, mirrors in found.items():
        for name, url in mirrors.items():
            t0 = main.time.time()
            got = 0
            try:
                with requests.get(url, stream=True, timeout=(10, 60), headers=UA) as r:
                    for c in r.iter_content(64 * 1024):
                        got += len(c)
                        if got >= 8 * 1024 * 1024:
                            break
            except Exception as exc:
                print(f"  {name}/{m}: {type(exc).__name__}")
                continue
            s = main.time.time() - t0
            print(f"  {name}/{m}: {got / 1048576 / max(s, 0.01):.2f} MB/s")


if __name__ == "__main__":
    main_run()