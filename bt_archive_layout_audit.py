"""逐个组件实测：本工具放进 PATH 的那个目录里，**归档里到底有没有那个可执行文件**。

为什么需要它（2026-10-09 真机踩出来的）：Windows 的 Python 装的是 embeddable 包，
`python.exe` 在解压根目录，而组件声明写的是 `path_subdir="Scripts"` —— PATH 于是指向
一个没有解释器的目录，"切换生效版本"从头到尾都是假话（连提权插到系统 PATH 最前都救不回来）。
这类错**单元测试看不见**（测试不知道归档长什么样），也不能只查本机已装的那三两个组件，
所以直接读归档的文件清单来核对声明。

手法：zip 的清单（中央目录）在文件**尾部**，用 HTTP Range 只取几 KB～几 MB 就能列出全部
条目，不必下载整个包（JDK 一个包 190MB）。tar.gz 是流式的、无法随机读，单二进制/`.war`/
`.exe` 安装器根本没有目录清单 —— 这些一律明确标 `skip` 并说明原因，不假装通过。

跑法：
    .venv/Scripts/python.exe bt_archive_layout_audit.py                 # 只审 Windows
    .venv/Scripts/python.exe bt_archive_layout_audit.py --os Windows,Linux,Darwin
    .venv/Scripts/python.exe bt_archive_layout_audit.py --only python,maven
退出码：有 BAD 时为 1（可以直接挂进 CI / 发版前检查）。
"""
import argparse
import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

import main  # noqa: E402

UA = {"User-Agent": "byte-tools"}
CD_CAP = 12 * 1024 * 1024          # 中央目录最多读 12MB，超过就判"审不了"而不是拖垮网络


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    return s


def _fetch(sess: requests.Session, url: str, start: int, end: int) -> Optional[bytes]:
    """取 [start, end] 这段字节；服务器不支持 Range 或状态不对时返回 None。"""
    r = sess.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=90,
                 stream=True)
    try:
        if r.status_code != 206:
            return None
        return r.content
    finally:
        r.close()


def _total_size(sess: requests.Session, url: str) -> Optional[int]:
    """Range 探第一字节，从 Content-Range 拿总长；顺带确认服务器支持 Range。"""
    r = sess.get(url, headers={"Range": "bytes=0-0"}, timeout=45, stream=True)
    try:
        if r.status_code == 206:
            cr = r.headers.get("Content-Range", "")
            if "/" in cr:
                try:
                    return int(cr.rsplit("/", 1)[1])
                except ValueError:
                    return None
            return None
        return None                     # 200 = 不支持 Range，不能拿来做清单审计
    finally:
        r.close()


def _zip_names(sess: requests.Session, url: str) -> Tuple[Optional[List[str]], str]:
    """只读尾部 + 中央目录，列出 zip 里的全部条目名。"""
    size = _total_size(sess, url)
    if not size:
        return None, "服务器不支持 Range 或拿不到长度"
    tail_len = min(size, 65536)
    tail = _fetch(sess, url, size - tail_len, size - 1)
    if not tail:
        return None, "读尾部失败"
    i = tail.rfind(b"PK\x05\x06")          # End of Central Directory
    if i < 0:
        return None, "尾部找不到 zip 中央目录结尾（不是标准 zip）"
    cd_size = struct.unpack("<I", tail[i + 12:i + 16])[0]
    cd_off = struct.unpack("<I", tail[i + 16:i + 20])[0]
    if cd_off == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:      # Zip64
        j = i - 20
        if j < 0 or tail[j:j + 4] != b"PK\x06\x07":
            return None, "Zip64 定位符缺失"
        z64_off = struct.unpack("<Q", tail[j + 8:j + 16])[0]
        rec = _fetch(sess, url, z64_off, z64_off + 55)
        if not rec:
            return None, "读 Zip64 记录失败"
        cd_size = struct.unpack("<Q", rec[40:48])[0]
        cd_off = struct.unpack("<Q", rec[48:56])[0]
    if cd_size > CD_CAP:
        return None, f"中央目录 {cd_size // 1024}KB 超过上限，不审计"
    blob = _fetch(sess, url, cd_off, cd_off + cd_size - 1)
    if not blob:
        return None, "读中央目录失败"
    names: List[str] = []
    p = 0
    while p + 46 <= len(blob):
        if blob[p:p + 4] != b"PK\x01\x02":
            break
        nlen = struct.unpack("<H", blob[p + 28:p + 30])[0]
        elen = struct.unpack("<H", blob[p + 30:p + 32])[0]
        clen = struct.unpack("<H", blob[p + 32:p + 34])[0]
        names.append(blob[p + 46:p + 46 + nlen].decode("utf-8", "replace"))
        p += 46 + nlen + elen + clen
    return names, ""


def _root_prefix(names: List[str]) -> str:
    """复刻 extract_archive 的判定：解压后**只有一个顶层目录**时，它就是 home。"""
    tops = {n.split("/", 1)[0] for n in names if "/" in n}
    loose = [n for n in names if "/" not in n and not n.endswith("/")]
    if len(tops) != 1:
        return ""
    only = next(iter(tops))
    # tar 会把顶层目录本身也当成一个成员写进来（`kafka_2.13-4.1.2` 不带斜杠），
    # 它不是"散在根目录的文件"。不排掉它就永远算不出根目录，整个归档全被判成 BAD。
    loose = [n for n in loose if n != only]
    return (only + "/") if not loose else ""


TAR_BUDGET_MB = 40             # tar.gz 只能顺着流读，给一个字节预算，超了就如实说"没验到"


def _tar_names_budgeted(sess: requests.Session, url: str) -> Tuple[Optional[List[str]], str]:
    """流式读 tar.gz 的成员名，**读到预算或提前命中就停**。

    tar.gz 没有"目录在尾部"这种结构，无法随机读；但 Apache 系发布包一般把 `bin/`
    排在 `lib/` 那些大 jar 之前，所以几十 MB 的预算足够看到 bin 目录。
    超预算就返回已看到的条目 + 标注 `budget`，让调用方报"未验到"而不是猜。
    """
    import tarfile
    r = sess.get(url, timeout=180, stream=True)
    try:
        if r.status_code not in (200, 206):
            return None, f"HTTP {r.status_code}"
        limit = TAR_BUDGET_MB * 1024 * 1024
        names: List[str] = []
        try:
            tf = tarfile.open(fileobj=r.raw, mode="r|gz")
            for member in tf:
                # tar 的目录成员可能写成不带斜杠的 `docker`，与文件同名形态混在一起
                # 就会被当成"根目录有个叫 docker 的可执行文件"，凭空报一个 BAD。
                names.append(member.name + "/" if member.isdir() else member.name)
                remaining = getattr(r.raw, "length_remaining", None)
                if remaining is not None and remaining > 0:
                    total = int(r.headers.get("Content-Length") or 0)
                    if total and total - remaining > limit:
                        return names, f"budget:{TAR_BUDGET_MB}MB"
                if len(names) > 200000:
                    break
        except Exception as exc:                       # noqa: BLE001
            return (names, f"流读断：{type(exc).__name__}") if names else (None, str(exc))
        return names, ""
    finally:
        r.close()


def _audit_tar(comp, urls: List[str]) -> Dict[str, str]:
    """tar.gz 组件：按同一套判据核对，但明确区分"验到/没验到"。"""
    sess = _session()
    url = next((u for u in urls if u.lower().endswith((".tar.gz", ".tgz"))), "")
    if not url:
        return {"verdict": "SKIP", "note": "没有 tar.gz 源可流读"}
    names, note = _tar_names_budgeted(sess, url)
    if not names:
        return {"verdict": "SKIP", "note": f"流读失败：{note}"}
    return _judge(comp, names, suffix=f"（读了 {len(names)} 条成员，{note or '读到结尾'}）",
                  complete=(note == ""))


def _judge(comp, names: List[str], suffix: str = "",
           complete: bool = False) -> Dict[str, str]:
    """zip 与 tar 共用的判据：**要放进 PATH 的那个目录里必须真有可执行文件**。

    入参 complete: bool  清单是否**完整**。zip 的中央目录是完整的，"哪儿都没有"就是 FAIL；
          tar.gz 是流式带预算读的，超预算时"没看到"只能判 UNKNOWN —— 拿残缺清单判失败
          等于凭空造一个假 bug。
    """
    root = _root_prefix(names)
    sub = comp.path_subdir or ""
    want_dir = ((root + sub).rstrip("/")).lower()
    cands = [n.lower() for n in main._exec_name_variants(comp)]
    if not cands:
        return {"verdict": "SKIP", "note": "组件没有 exec_name，本来就不进 PATH"}
    entries = {n.lower(): n for n in names if not n.endswith("/")}
    hit_here = [orig for key, orig in entries.items()
                if key.rpartition("/")[0] == want_dir
                and key.rpartition("/")[2] in cands]
    if hit_here:
        return {"verdict": "OK",
                "note": f"{want_dir or '(归档根)'} → {hit_here[0].rpartition('/')[2]}{suffix}"}
    else_hit = [orig for key, orig in entries.items() if key.rpartition("/")[2] in cands]
    if else_hit:
        return {"verdict": "BAD",
                "note": f"PATH 指的 {want_dir or '(归档根)'} 里没有可执行文件；"
                        f"实际在 {else_hit[0].rpartition('/')[0] or '(归档根)'}{suffix}"}
    return {"verdict": "FAIL" if complete else "UNKNOWN",
            "note": f"{'整个归档' if complete else '已读的部分'}里都没看到 "
                    f"{'/'.join(cands[:3])}{suffix} —— "
                    + ("该组件的归档源需要复核" if complete
                       else "不能判通过，以装完自检 verify_bin_dir 为准")}


def audit_one(sess: requests.Session, comp, os_name: str) -> Dict[str, str]:
    """返回 {verdict: OK|BAD|SKIP|FAIL|UNKNOWN, note}。"""
    ver = comp.versions[0]
    kind = (ver.archive_map or {}).get(os_name, "")
    urls = [u for u in (ver.url_list_map or {}).get(os_name, [])]
    if not urls:
        return {"verdict": "SKIP", "note": f"{os_name} 没有归档源（本工具在该平台不支持）"}
    zips = [u for u in urls if u.lower().endswith(".zip")]
    if not zips:
        if kind in ("tar.gz", "tgz", "", None):
            return _audit_tar(comp, urls)
        return {"verdict": "SKIP",
                "note": f"{os_name} 归档类型 {kind or '?'}，无法随机读清单"
                        f"（只能靠装完自检 verify_bin_dir）"}
    names = None
    why = ""
    for url in zips:
        try:
            names, why = _zip_names(sess, url)
        except Exception as exc:                           # noqa: BLE001
            names, why = None, f"{type(exc).__name__}: {str(exc)[:60]}"
        if names:
            break
    if not names:
        return {"verdict": "SKIP", "note": f"清单读不到：{why}"}
    return _judge(comp, names, complete=True)


def run(os_names: List[str], only: List[str]) -> int:
    sess = _session()
    rows, counts = [], {k: 0 for k in ("OK", "BAD", "SKIP", "FAIL", "UNKNOWN")}
    host = main.CURRENT_OS
    try:
        for os_name in os_names:
            # path_subdir 与 exec_name 是 build_components() 按**当前平台**定稿的
            # （python / node 的 Windows 分支就写在这里）。换平台必须重建组件，
            # 否则拿 Windows 的目录声明去比 Linux 的归档，只会得到假 BAD。
            main.CURRENT_OS = os_name
            comps = [c for c in main.build_components() if not only or c.key in only]
            for comp in comps:
                try:
                    res = audit_one(sess, comp, os_name)
                except Exception as exc:                   # noqa: BLE001
                    # 一个源抖动（本机对 npmmirror / github 偶发 SSLError）不许把整场审计带走：
                    # 记成 SKIP 并写明原因，剩下的组件继续审。
                    res = {"verdict": "SKIP",
                           "note": f"审计异常：{type(exc).__name__}: {str(exc)[:90]}"}
                counts[res["verdict"]] += 1
                rows.append((os_name, comp.key, (comp.versions[0].version or "?")[:9],
                             repr(comp.path_subdir), res["verdict"], res["note"]))
                print("%-8s %-14s %-10s path=%-16s %-4s %s" % rows[-1], flush=True)
    finally:
        main.CURRENT_OS = host
    print("\n合计：" + "  ".join(f"{k}={v}" for k, v in counts.items()))
    print("说明：SKIP = 归档类型不支持随机读（单二进制 / tar.gz / 安装器），"
          "这类组件的目录声明只能靠装完自检 verify_bin_dir 兜。")
    return 1 if (counts["BAD"] or counts["FAIL"]) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--os", default="Windows",
                    help="逗号分隔：Windows,Linux,Darwin（默认只审 Windows）")
    ap.add_argument("--only", default="", help="只审这些组件 key，逗号分隔")
    a = ap.parse_args()
    sys.exit(run([o.strip() for o in a.os.split(",") if o.strip()],
                 [o.strip() for o in a.only.split(",") if o.strip()]))
