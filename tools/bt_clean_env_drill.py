"""在**干净环境**里逐个真机验证 9 个可启动组件。

2026-10-06 用户从 exe 界面报了一堆"显示启动成功但实际不可用"，根查下去是：
我之前的演练 shell 里带着 4 个 `*_HOME` 变量（早期多版本真机测试写进去的），
`dict(os.environ)` 把它们带给了子进程 → 演练全过；
**而 exe 启动的进程没有这些变量** → 立刻失败。
**演练环境必须等于（或严于）真实使用环境**，否则验出来的是假绿灯。

这个脚本主动把这些变量从自己的 env 里剔掉，模拟 exe 的干净环境。
"""
import os
import sys
import time
from pathlib import Path

# --- 1) 先剔干净：组件类 *_HOME 与 CLASSPATH 会让演练变成假绿灯 ------------
# **但保留 JAVA_HOME**：产品里压根没装 jdk（~/.env-tools/jdk 是空的），
# java 系组件（tomcat/kafka/rocketmq）靠的是用户系统自带的 JDK
# （本机 D:/soft/jdk/openjdk-21，是机器上本来就有的，不是本工具装的）。
# 剔掉它就等于在测一台"机器上没装 JDK"的电脑，那是另一个场景。
DIRTY = [k for k in os.environ
         if (k.endswith("_HOME") and k != "JAVA_HOME")
         or k in ("CLASSPATH", "RABBITMQ_NODENAME")]
for k in DIRTY:
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # 仓库根（本脚本在 tools/ 下）
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import main  # noqa: E402  必须在剔变量之后 import

# 二次确认：build_components 内部可能会自己写环境变量
for k in [k for k in os.environ if (k.endswith("_HOME") and k != "JAVA_HOME") or k == "CLASSPATH"]:
    os.environ.pop(k, None)


def comps():
    return {c.key: c for c in main.build_components()}


def run_one(key: str) -> tuple:
    """启→探活→停。返回 (结论, 详情)。"""
    cs = comps()
    comp = cs.get(key)
    if comp is None:
        return "跳过", "组件不存在"
    spec = getattr(comp, "launch", None)
    if spec is None:
        return "跳过", "未登记一键启停"

    # 端口预检
    busy = [p for p in (spec.main_port,) + tuple(spec.extra_ports or ())
            if main.port_is_listening(p)]
    if busy:
        return "跳过", f"端口被占：{busy}"

    t0 = time.time()
    res = main.SERVICE_MANAGER.start(comp, cs)
    if not res.ok:
        # 「磁盘上没装」不是组件的毛病，是这台机器上还没装它——
        # 归到跳过，否则每次跑都挂在那儿，看着像回归。
        if "还没有" in res.reason and "已安装版本" in res.reason:
            return "跳过", "本机未安装该组件（不是缺陷）"
        return "FAIL", f"start 失败 [{res.state}] {res.reason[:220]}"
    up = time.time() - t0
    rec = res.record
    detail = [f"起 {up:.0f}s pid={rec.pid}({rec.pid_role})",
              f"端口簇={list(rec.ports or (rec.port,))}"]

    # 探活：用与服务端同一套判据。
    # **必须有界重试**（2026-10-06 用户报"显示启动成功实际不可用"后加的）：
    # 端口在听 ≠ 服务就绪 —— Jenkins 实测 Jetty 在 T+0s 就 bind 8080，
    # 而它还在"Started initialization"，要 T+1~2 分钟才真的能响应。
    # 一次性探活会把"服务还在初始化"误判成"打不开"，那正是用户看到的现象。
    if spec.service_probe:
        ok = _probe_cmd(spec, comp, rec)
        detail.append(f"协议探活={ok}")
    else:
        url = _probe_url(rec.port, spec)
        ok = _wait_http(rec.port, spec)
        detail.append(f"{url} = {ok}")

    # 停止
    st = main.SERVICE_MANAGER.stop(comp, cs)
    time.sleep(1.5)
    still = [p for p in (rec.ports or (rec.port,)) if main.port_is_listening(p)]
    if not st.ok:
        #优雅停止失败 → 兜底强杀，别留孤儿占端口
        main.SERVICE_MANAGER.force_stop(key)
        time.sleep(1.5)
        still = [p for p in (rec.ports or (rec.port,)) if main.port_is_listening(p)]
        detail.append(f"优雅停止失败(已强杀): {st.reason[:120]}")
    else:
        detail.append("优雅停止成功")
    detail.append(f"残留端口={still or '无'}")

    verdict = "PASS" if (ok and not still) else "FAIL"
    return verdict, " | ".join(detail)


def _probe_url(rec_port: int, spec) -> str:
    """探活 URL：探活路径与控制台路径**不同时**要拼上 health_path。

    2026-10-06 用户报「Jenkins 显示起来了但打不开」后定位：
    Jenkins 未初始化时根路径 `/` 返回 **403**（要引导去解锁向导），
    而 `/login` 返回 200 —— 产品登记表里 `health_path="/login"` 就是为此存在的
    （LaunchSpec.health_path 的字段说明：「探活路径与控制台路径不同时才填」）。
    我这个演练脚本一开始直接探 `/`，于是把一个**完全正常的 Jenkins**
    判成"打不开"。产品侧 `ServiceManager.status()` 走的是对的（它会用 health_path），
    是演练脚本没照做。
    """
    base = f"http://127.0.0.1:{rec_port}{spec.console_path or ''}"
    health = spec.health_path or ""
    if health and health != spec.console_path:
        return base.rstrip("/") + health
    return base


def _wait_http(port: int, spec, rounds: int = 45, gap: float = 4.0) -> bool:
    """有界重试 HTTP 探活。

    轮数按**实测最慢的组件**定：Jenkins 要 1-2 分钟（Jetty 先 bind、
    后端还在初始化）。45 轮 x 4 秒 = 180 秒，够用。
    有控制台的用 http_ok（页面能用），没控制台的用 http_responds（404 也算活）。
    """
    url = _probe_url(port, spec)
    check = main.http_ok if spec.console_path else main.http_responds
    for _ in range(rounds):
        try:
            if check(url):
                return True
        except Exception:
            pass
        time.sleep(gap)
    return False


def _probe_cmd(spec, comp, rec) -> bool:
    """跑 service_probe（协议级判据）。"""
    import subprocess
    version = main.resolve_launch_version(comp) or comp.versions[0].version
    data_dir = main.CONFIG_DIR / f"{comp.key}-data"
    jh = main.resolve_java_home(comps()) or ""
    plan = main.build_launch_plan(comp, spec, jh, rec.port,
                                  data_dir / "logs" / "probe.out")
    mapping = {
        "java": str(Path(plan.java_home or jh) / "bin" /
                    ("java.exe" if main.CURRENT_OS == "Windows" else "java")),
        "home": str(comp.install_dir(version)),
        "data_dir": str(data_dir),
        "conf": str(main.config_file_for(comp, data_dir)),
        "port": str(rec.port),
    }
    argv = [t.format(**mapping) for t in spec.service_probe]
    for _ in range(6):
        try:
            p = subprocess.run(argv, cwd=plan.cwd, env=plan.env,
                               capture_output=True, timeout=90)
            if p.returncode == 0:
                return True
            last = ((p.stdout or b"").decode("utf-8", "replace")
                    + (p.stderr or b"").decode("utf-8", "replace")).strip()
        except (subprocess.TimeoutExpired, OSError) as exc:
            last = f"{type(exc).__name__}"
        time.sleep(3)
    print(f"      探活输出末尾：{last[-260:]}")
    return False


def main_run() -> int:
    # **以 LAUNCH_KEYS 为准，不要手写清单**（2026-10-06 用户要求
    # 「支持启停的组件都要能成功使用」时发现的）：我手写的清单漏了 seata，
    # 而它确实在 LAUNCH_KEYS 里、磁盘上也装着 —— 手写清单会静默漏掉组件。
    # 排序只为输出好看一点，不影响覆盖。
    order = sorted(main.LAUNCH_KEYS)
    if len(sys.argv) > 1:
        order = [k for k in sys.argv[1:] if k in order]
    print(f"干净环境：已剔除 {len(DIRTY)} 个 *_HOME/CLASSPATH 变量")
    print(f"逐一验证：{len(order)} 个组件\n")
    results = {}
    for key in order:
        print(f"─── {key} " + "─" * 46)
        try:
            verdict, detail = run_one(key)
        except Exception as exc:              # 演练脚本自己别崩
            verdict, detail = "FAIL", f"演练脚本报错：{type(exc).__name__}: {exc}"
        results[key] = verdict
        print(f"  {verdict}  {detail}\n")
    npass = sum(1 for v in results.values() if v == "PASS")
    nfail = sum(1 for v in results.values() if v == "FAIL")
    print("=" * 60)
    for k, v in results.items():
        print(f"  {v:5} {k}")
    print(f"\nPASS {npass} / FAIL {nfail} / 跳过 {len(results) - npass - nfail}")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main_run())