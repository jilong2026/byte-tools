"""批量跑多版本切换真机测试：每个组件装 2 个版本 → 来回切 → 测完卸载。

按体积从小到大，快的先跑 —— 出问题能早发现，不至于等半小时才看到第一个失败。
已经装着的组件（用户要求保留）只测切换、不卸载。
"""
import io
import subprocess
import sys
import time
from pathlib import Path

PY = ".venv/Scripts/python.exe"
# 已装且用户要求保留的：只加装一个版本、测切换、不卸载
KEEP = {"jenkins", "nacos", "activemq", "python", "powershell"}
ORDER = [
    # (key, 期望的第二个版本；None = 用候选清单前两个)
    ("nginx", None), ("maven", None), ("kubectl", None), ("tomcat", None),
    ("rabbitmq", None), ("node", None), ("bun", None), ("seata", None),
    ("pulsar", None), ("git", None), ("kafka", None), ("rocketmq", None),
    ("docker", None), ("python", None), ("go", None), ("gradle", None),
    ("mysql", None), ("mongodb", None), ("postgresql", None),
    ("elasticsearch", None), ("powershell", None), ("conda", None),
    ("jdk", None), ("jenkins", None), ("nacos", None), ("activemq", None),
]

LOG = Path("bt_mv_results.txt")
results = []


def run(key, v2=None):
    args = [PY, "-u", "bt_mv_drill.py", "install", key]
    if v2:
        args.append(v2)
    t0 = time.time()
    p = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800)
    out = p.stdout or ""
    dt = time.time() - t0
    tail = [l for l in out.splitlines() if l.strip()][-14:]
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n{'='*70}\n### {key}  (exit={p.returncode}, {dt:.0f}s)\n")
        f.write("\n".join(tail))
        if p.returncode != 0 and p.stderr:
            f.write("\n--- stderr ---\n" + p.stderr[-800:])
    passed = ("全部通过" in out)
    skipped = ("[SKIP]" in out) or ("没有可用下载地址" in out) or ("安装阶段有失败" in out)
    results.append((key, "PASS" if passed else ("SKIP" if skipped else "FAIL"),
                    dt, out))
    print(f"  {'✓' if passed else ('-' if skipped else '✗')} {key:14} "
          f"{'PASS' if passed else ('SKIP' if skipped else 'FAIL'):5} {dt:6.0f}s",
          flush=True)
    for l in tail:
        if l.strip().startswith(("切到", "[FAIL]", "[SKIP]", "已装", "===")):
            print(f"      {l.strip()}", flush=True)
    return p.returncode


def cleanup(key):
    if key in KEEP:
        print(f"  · {key} 保留（用户要求），只卸掉多出来的那个版本", flush=True)
        return
    p = subprocess.run([PY, "-u", "bt_mv_drill.py", "uninstall", key],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    print(f"  · 已卸载 {key}：{(p.stdout or '').strip().splitlines()[-1] if p.stdout else '?'}",
          flush=True)


if __name__ == "__main__":
    only = sys.argv[1:] or None
    LOG.write_text("多版本切换真机测试结果\n", encoding="utf-8")
    print(f"开始：共 {len(ORDER)} 个组件\n", flush=True)
    for key, v2 in ORDER:
        if only and key not in only:
            continue
        print(f"\n--- {key} ---", flush=True)
        run(key, v2)
        cleanup(key)
    print("\n" + "=" * 70)
    npass = sum(1 for r in results if r[1] == "PASS")
    nskip = sum(1 for r in results if r[1] == "SKIP")
    nfail = sum(1 for r in results if r[1] == "FAIL")
    print(f"PASS {npass} / SKIP {nskip} / FAIL {nfail}  （共 {len(results)}）")
    for k, s, dt, _ in results:
        print(f"  {s:5} {k:14} {dt:6.0f}s")
