"""真机演练：验证「切换生效版本 → 外壳刷新 → 新开终端拿到新值」这条全链路。

用法（在项目根目录）：
    .venv/Scripts/python.exe bt_real_machine_drill.py            # 只体检，不改动任何东西
    .venv/Scripts/python.exe bt_real_machine_drill.py --yes      # 真演练：切到另一个已装版本，再切回来
    .venv/Scripts/python.exe bt_real_machine_drill.py --launch <key>            # 组件启动演练：只打印将做什么
    .venv/Scripts/python.exe bt_real_machine_drill.py --launch <key> --yes      # 真启动→查控制台→真停止

为什么要有这个脚本：单元测试能证明逻辑自洽，证明不了 Windows 真的照办。
2026-09-30 那次就是教训——注册表写对了、`composed_env()` 复验也通过了，
但 explorer 揣的还是旧环境块，用户从开始栏开的每个终端都是旧值，
"复验通过"就成了假话。只有**让 explorer 现场开一个进程去查**才算端到端。

安全边界：
  · 只碰本工具工作区里已装的版本，切换用产品自己的 apply_active_version（含原子回滚）。
  · 结束时一定切回演练前的生效版本；中途异常也会尽力还原并如实报告。
  · 不写系统级（HKLM）变量，不碰工作区之外的任何安装。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APPLY_FLAG = "--yes" in sys.argv   # 必须在清 argv 之前取，否则演练模式永远进不去
if "--launch" in sys.argv:
    _i = sys.argv.index("--launch") + 1
    # 敲了 --launch 却忘了给 key：给空串，让它落到下面"不认识的 key"那条中文报错，
    # 而不是在这里抛 IndexError 糊用户一脸堆栈。
    LAUNCH_KEY = sys.argv[_i] if _i < len(sys.argv) else ""
else:
    LAUNCH_KEY = None
sys.argv = [sys.argv[0]]           # 别让 main.py 的 argparse/入口看到本脚本的参数
import main                        # noqa: E402


# ---------------------------------------------------------------- 读数


def registry_snapshot(comp) -> dict:
    """读持久层真值（注册表 + active 登记表），不经过任何进程环境。"""
    env = main.EnvManager
    home = env.read_user_env(comp.env_var) if comp.env_var else None
    path_entries = [p for p in env.read_user_path_entries() if comp.key in p.lower()]
    return {"home": home, "path": path_entries,
            "active": main.load_active_map().get(comp.key)}


def explorer_snapshots() -> dict:
    """{explorer_pid: 它环境块里的 BUN_HOME 末段}；读不到的记 "读不到"。

    读法：PEB+0x20 → ProcessParameters，+0x80 是指针、+0x88 是长度。
    长度字段实测可能是 0（explorer 就是），此时分块读到双空为止；
    一次读太大块会跨越未映射内存导致整次失败，那样会把"有"误报成"没有"。
    """
    import ctypes
    import struct
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntd = ctypes.WinDLL("ntdll", use_last_error=True)

    class PBI(ctypes.Structure):
        _fields_ = [("a", ctypes.c_void_p), ("Peb", ctypes.c_void_p),
                    ("b", ctypes.c_void_p), ("c", ctypes.c_void_p),
                    ("pid", ctypes.c_void_p), ("ppid", ctypes.c_void_p)]

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    def rpm(h, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got))
        return buf.raw[:got.value]

    def one(pid):
        h = k32.OpenProcess(0x0410, False, pid)
        if not h:
            return "读不到"
        try:
            i = PBI()
            r = ctypes.c_size_t(0)
            if ntd.NtQueryInformationProcess(ctypes.c_void_p(h), 0, ctypes.byref(i),
                                             ctypes.sizeof(i), ctypes.byref(r)) != 0:
                return "查询失败"
            pp = struct.unpack("<Q", rpm(h, i.Peb + 0x20, 8))[0]
            envp = struct.unpack("<Q", rpm(h, pp + 0x80, 8))[0]
            size = struct.unpack("<Q", rpm(h, pp + 0x88, 8))[0]
            if not envp:
                return "无环境块"
            if not 0 < size < 4_000_000:
                size = 0
                while size < 4_000_000:
                    part = rpm(h, envp + size, 4096)
                    if not part:
                        break
                    size += len(part)
                    if b"\x00\x00" in part:
                        break
            for kv in rpm(h, envp, size).decode("utf-16-le", "replace").split("\x00"):
                if kv.upper().startswith("BUN_HOME="):
                    return kv.split("=", 1)[1].split(os.sep)[-1]
            return "(没有 BUN_HOME)"
        finally:
            k32.CloseHandle(h)

    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    e = PE()
    e.dwSize = ctypes.sizeof(PE)
    out = {}
    got = k32.Process32First(ctypes.c_void_p(snap), ctypes.byref(e))
    while got:
        if e.szExeFile.decode("mbcs", "replace").lower() == "explorer.exe":
            out[e.th32ProcessID] = one(e.th32ProcessID)
        got = k32.Process32Next(ctypes.c_void_p(snap), ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def shell_probe(comp) -> str:
    """让 **explorer 自己**去开一个探针进程，问它 `bun -v`。

    这是"用户从开始栏/任务栏新开终端会看到什么"的直接判据：
    它继承的是外壳那份环境块，不是本脚本改过的进程快照，也不是注册表原文。
    """
    exe = comp.exec_name
    args = comp.version_args or ["--version"]
    d = os.path.join(tempfile.gettempdir(), "bt_drill_probe")
    os.makedirs(d, exist_ok=True)
    bat, out = os.path.join(d, "p.bat"), os.path.join(d, "o.txt")
    if os.path.exists(out):
        os.remove(out)
    q = '"' + out + '"'
    with open(bat, "wb") as f:      # .bat 必须 CRLF；UTF-8 中文 + chcp
        f.write(("\r\n".join(["@echo off", "chcp 65001 >nul",
                              f'"{exe}" {" ".join(args)}> ' + q + " 2>nul",
                              "echo __END__>> " + q]) + "\r\n").encode("utf-8"))
    subprocess.run(["explorer.exe", bat])
    for _ in range(30):
        if os.path.exists(out):
            break
        time.sleep(0.5)
    else:
        return "(explorer 没把探针跑起来)"
    for _ in range(20):
        txt = open(out, encoding="utf-8", errors="replace").read()
        if "__END__" in txt:
            return txt.split("__END__")[0].strip().splitlines()[-1] if txt.strip() else "(空)"
        time.sleep(0.5)
    return "(探针超时无输出)"


# ---------------------------------------------------------------- 演练


def switch_to(comp, version: str) -> None:
    """走产品自己的切换路径（和界面上那个按钮背后同一段码）。"""
    steps = main.apply_active_version(comp, version)
    main.save_active_version(comp.key, version)
    for s in steps:
        print("      ·", s)


def wait_for_shell(comp, want: str, seconds: float = 8.0):
    """等 explorer 那份环境块翻过来，返回 (耗时秒, 最后一个非空读数)。"""
    t0 = time.time()
    seen = None
    while time.time() - t0 < seconds:
        vals = {p: v for p, v in explorer_snapshots().items() if v and "读不到" not in v}
        seen = vals
        if any(v == want for v in vals.values()):
            return time.time() - t0, vals
        time.sleep(0.5)
    return None, seen


def main_drill(apply: bool) -> int:
    comp = next(c for c in main.build_components() if c.key == "bun")
    installed = [v for v, _p in main.installed_versions(comp)]
    if len(installed) < 2:
        print(f"未装够两个版本（现在 {installed}），演练需要至少两个可切换版本。")
        return 1

    base = registry_snapshot(comp)
    want = base["home"].split(os.sep)[-1] if base["home"] else None
    print("=" * 78)
    print("真机演练 · 组件 bun · 已装版本", installed)
    print("基线：注册表 BUN_HOME 末段 =", want, "| active 登记 =", base["active"])
    print("      explorer 环境块读数 =", explorer_snapshots())
    print("      explorer 现场开的探针 bun -v =", shell_probe(comp))
    print("=" * 78)
    if not apply:
        print("（只体检模式：加 --yes 才会真的切换。未改动任何东西。）")
        return 0

    other = next(v for v in installed if v != want.split("-")[-1])
    ok = True
    try:
        for target in (other, want.split("-")[-1]):
            print(f"\n--- 切换到 {target}（走产品真实路径 apply_active_version）---")
            switch_to(comp, target)
            reg = registry_snapshot(comp)
            hit_home = (reg["home"] or "").split(os.sep)[-1]
            print(f"  [1] 注册表 BUN_HOME 末段 = {hit_home}  →",
                  "PASS" if hit_home.endswith(target) else "FAIL")
            ok &= hit_home.endswith(target)
            spent, vals = wait_for_shell(comp, f"bun-{target}")
            print(f"  [2] explorer 环境块 = {vals}  →",
                  "PASS" if spent is not None else "FAIL",
                  f"(等待 {spent:.1f}s)" if spent is not None else "(8 秒内没翻过来)")
            ok &= spent is not None
            got = shell_probe(comp)
            print(f"  [3] explorer 现场开的探针 bun -v = {got!r}  →",
                  "PASS" if got.strip().startswith(target) else "FAIL")
            ok &= got.strip().startswith(target)
    finally:
        print(f"\n--- 还原到演练前的生效版本 {want.split('-')[-1]} ---")
        switch_to(comp, want.split("-")[-1])
        back = registry_snapshot(comp)
        same = ((back["home"] or "") == (base["home"] or "")
                and back["active"] == base["active"]
                and sorted(back["path"]) == sorted(base["path"]))
        print("  还原后与基线逐字一致 →", "PASS" if same else f"FAIL：{back} != {base}")
        ok &= same
    print("\n" + "=" * 78)
    print("演练结论：", "全链路 PASS" if ok else "有 FAIL 项，看上面哪一步")
    return 0 if ok else 1


def _probe_service(main_mod, comp, rec, url: str, rounds: int = 6,
                   gap: float = 3.0) -> bool:
    """判据一：这个服务**真的可用**，而不只是端口在听。

    三档判据按LaunchSpec 的登记来选（2026-10-06 真机实测逼出来的）：

    1. **`service_probe`**（协议级，kafka）：它的端口说二进制协议，
       HTTP 请求会得到 `RemoteDisconnected`。用它自带的 API 工具问一句
       "你支持哪些 API 版本"，答得上来才算真的可服务。
    2. **`console_path` 非空**（有 Web 控制台）→ `http_ok`：要求 2xx/3xx。
       这里"页面能用"才是真的能用（Nacos/jenkins/activemq）。
    3. **`console_path` 为空**（tomcat/nginx/ES）→ `http_responds`：
       404/403 也算活着。实测 Tomcat 10.1.60 启动后 `/` 就是 404
       （没挂 web 应用），它完全正常地在服务。
    """
    spec = comp.launch
    if spec.service_probe:
        # **直接复用 build_launch_plan 产出的 env**（2026-10-06 真机实测踩出来的）：
        # rabbitmq 的探活是 `rabbitmqctl.bat status`，它需要
        #   ① PATH 里有 erl.exe（免安装 Erlang，不设系统变量）
        #   ② RABBITMQ_NODENAME 与 server 端一致（中文主机名那个坑）
        # 少任何一条都过不了。之前这里自己拼最小 env，只带 {java}/{home}/{port}，
        # 于是探活 rc≠0、被误判成"服务不可用"，而其实服务是好的。
        version = main_mod.resolve_launch_version(comp) or comp.versions[0].version
        home = comp.install_dir(version)
        data_dir = main_mod.CONFIG_DIR / f"{comp.key}-data"
        jh = main_mod.resolve_java_home({c.key: c for c in main_mod.build_components()}) or ""
        plan = main_mod.build_launch_plan(comp, spec, jh, rec.port,
                                           data_dir / "logs" / "probe.out")
        argv = [t.format(**_probe_mapping(comp, rec, plan)) for t in spec.service_probe]
        for i in range(max(1, int(rounds))):
            try:
                p = subprocess.run(argv, cwd=plan.cwd, env=plan.env,
                                   capture_output=True, timeout=90)
                if p.returncode == 0:
                    return True
                tail = ((p.stdout or b"").decode("utf-8", "replace")
                        + (p.stderr or b"").decode("utf-8", "replace")).strip()
                print(f"      协议探活未通过（rc={p.returncode}）：{tail[-200:]}")
            except (subprocess.TimeoutExpired, OSError) as exc:
                print(f"      协议探活异常：{type(exc).__name__}")
            if i == 0:
                print(f"      协议探活有界重试（最多 {rounds} 轮）…")
            time.sleep(gap)
        return False
    probe = main_mod.http_ok if spec.console_path else main_mod.http_responds
    return _wait_console(main_mod, url, probe=probe)


def _probe_mapping(comp, rec, plan) -> dict:
    """探活命令的占位符替换表。与 build_launch_plan 的 mapping 对齐。"""
    version = main.resolve_launch_version(comp) or comp.versions[0].version
    data_dir = main.CONFIG_DIR / f"{comp.key}-data"
    return {
        "java": str(Path(plan.java_home or "") / "bin" /
                    ("java.exe" if main.CURRENT_OS == "Windows" else "java")),
        "home": str(comp.install_dir(version)),
        "data_dir": str(data_dir),
        "conf": str(main.config_file_for(comp, data_dir)),
        "port": str(rec.port),
    }


def _wait_console(main_mod, url: str, rounds: int = 20, gap: float = 1.5,
                  probe=None) -> bool:
    """控制台可达性要有界重试，不能只探一次。

    端口在听≠ 服务可用：Jenkins 2.580.1 实测（2026-10-05 真机）里 Jetty 在
    T+0s 就 bind 了 8080，而 Jenkins 还在 "Started initialization"，直到 T+1s 才
    初始化完。判据一若在端口通的瞬间查一次 HTTP 会稳定误报"控制台不可达"。

    轮数是量过的，不是猜的：2026-10-06 实测 Nacos 2.3.2，start() 返回后第一次探
    就通（T+13.7s，`Tomcat started on port(s): 8848 with context path '/nacos'`
    与 start() 返回几乎同时）。30 秒窗口有30 倍余量，够用。

    这里用与 start() 相同的有界轮次约定（固定轮数 + 每轮 sleep），不用墙钟 deadline：
    deadline 在 sleep 被注入时会静默缩短宽限期。

    **probe 参数**（2026-10-06 真机实测逼出来的）：默认判据是 `http_ok`（要求 2xx/3xx），
    但 Tomcat 10.1.60 启动后 `/` 返回的是 **404**（没挂 web 应用，ROOT 也没解包）——
    服务完全正常地在服务。用 http_ok 判会稳定误报"控制台不可达"
    （实测第一次演练就是这样被判 FAIL 的，而 tomcat 启停其实都正常）。
    所以"有端口但不提供 Web 控制台"的组件要传 `main.http_responds`。"""
    import time
    check = probe or main_mod.http_ok
    for i in range(max(1, int(rounds))):
        if check(url):
            return True
        if i == 0:
            print(f"      控制台暂未就绪，有界重试（最多 {rounds} 轮）…")
        time.sleep(gap)
    return False


def launch_drill(comp_key: str, apply: bool) -> int:
    """四层判据（沿用本脚本既有风格）：拉得起 → 停止按整个端口簇体检 → 强制确认 →
    停得干净（登记无残留）。

    单元测试证明的是逻辑对，这一层证明真机器上真能跑（R3.16 的教训）。
    """
    comps = {c.key: c for c in main.build_components()}
    if comp_key not in comps:
        # 传错 key 要当场死，绝不静默走回原来的 bun 演练路径。
        print(f"演练失败：--launch 收到不认识的 key：{comp_key}，"
              f"可选：{sorted(comps)}")
        return 1
    comp = comps[comp_key]
    if comp.launch is None:
        # 白名单外的组件（本期只有 jenkins 在内）不许拿一个看起来会成功的 dry-run 糊人：
        # 真跑会被 launch_gate 拒，dry-run 却只打印"将启动"。
        print(f"演练失败：{comp.display_name} 不在本期启动白名单 "
              f"LAUNCH_KEYS={sorted(main.LAUNCH_KEYS)}，演练只能接登记过的组件")
        return 1
    if not apply:
        # 数据目录要说准：spec §0 决策 3 定的是"数据与版本目录分离"，
        # JENKINS_HOME 在 CONFIG_DIR/<key>-data，不在版本目录里。
        data = main.CONFIG_DIR / f"{comp.key}-data"
        print(f"[dry-run] 将启动 {comp.display_name}，随后停止；"
              f"程序目录 {comp.install_dir(comp.versions[0].version)}，数据目录 {data}")
        return 0
    res = main.SERVICE_MANAGER.start(comp, comps)
    if not res.ok:
        print("启动失败：", res.reason)
        return 1
    rec = res.record
    # 健康路径取自 LaunchSpec.health_path，不在这里硬编码 "/login"：
    # 账本裁定 F3 说这个字段留着就是给演练层当判据用的，写死就等于计划二一换组件即错。
    # console_url 已经含 console_path（形如 http://127.0.0.1:8848/nacos），
    # 不要再拼 health_path —— 2026-10-06 实测：Nacos 两者都是 /nacos，
    # 拼起来变成 /nacos/nacos → 404，判据一稳定误报"控制台不可达"。
    # health_path 存在的意义是「探活路径与控制台路径不同时」才追加（Jenkins 那种
    # console_path="/" 而 health_path="/login" 的组合），这里只在真的不同才拼。
    base = rec.console_url.rstrip("/")
    health = comp.launch.health_path or ""
    url = base if not health or health == comp.launch.console_path else base + health
    # 判据分三档（2026-10-06 真机实测逼出来的）：
    #  1) 登记了 service_probe → 用它（协议级）。kafka 的 9092 说二进制协议，
    #     HTTP 请求得到 RemoteDisconnected，HTTP 判据对它完全无效；
    #  2) 有 console_path（有 Web 控制台）→ http_ok（要求 2xx/3xx，"页面能用"才算能用）
    #  3) 无 console_path（tomcat/nginx/ES）→ http_responds（404/403 也算活着）。
    #     实测 Tomcat 启动后 `/` 就是 404 —— 它在正常服务，
    #     用 http_ok 判会误报"控制台不可达"，第一次演练就是这样被判 FAIL 的。
    got = _probe_service(main, comp, rec, url)
    probe_kind = ("service_probe" if comp.launch.service_probe
                  else ("http_ok" if comp.launch.console_path else "http_responds"))
    print(f"[1/4] 已启动 pid={rec.pid}({rec.pid_role}) port={rec.port} "
          f"服务可用={got}（判据 {probe_kind}）")

    def cluster_state(ports, label):
        """端口簇逐个体检。计划一只看 rec.port 一个口，本期两个组件是三口/两口，
        只看主口会得出"停干净了"的假结论——主口掉了 gRPC 还在听也算没停。"""
        live = [p for p in ports if main.port_is_listening(p)]
        print(f"      {label}: {list(ports)} 在听={live or '无'}")
        return live

    # 老记录没有 ports 字段（计划一的 running.json），按主口兜底，别让读侧 KeyError。
    rec_ports = tuple(rec.ports) or (rec.port,)
    live_before = cluster_state(rec_ports, "停止前")

    print("[2/4] 停止：")
    stop = main.SERVICE_MANAGER.stop(comp, comps)
    if not stop.ok and stop.need_force:
        # Windows 上 stop 第一步只请示、不动手（Task 8 裁定 1）。演练里这一票由脚本替
        # 用户点"是"，否则一条按设计走通的路径会被判成失败。
        print("[3/4] 停止需要确认，演练按「是」继续：", stop.reason)
        stop = main.SERVICE_MANAGER.force_stop(rec.key)
    print(f"      停止 ok={stop.ok} 需强制={stop.need_force} reason={stop.reason}")
    # 按簇复查，而不是只看主口：主口掉了但派生口还在听，同样是"没停干净"。
    live_after = cluster_state(rec_ports, "停止后")

    left = main.load_running_map()
    print(f"[4/4] 登记残留={list(left)}")
    if not stop.ok or rec.key in left or live_after:
        return 1
    if not got:
        # 判据一不能只被"打印"架空：端口在听不代表服务可用（Jenkins 启动中会 503，
        # 首次解锁向导前 /login 也可能拿不到可达响应）。既然写了四层，就得四层都能否决。
        print("演练失败：控制台不可达（判据一）—— 端口在听不等于服务可用")
        return 1

    print("\n--- 计划二待验证项（只有 --yes 真跑才有结论）---")
    print("A1 整簇端口是否随停止一起释放：", "PASS" if not live_after else "FAIL")
    print("A2 实际监听集合是否等于登记的簇：", list(live_before or []), "登记为", list(rec_ports))
    print("A3 控制台路径：", rec.console_url, "可达=", got)
    print("A4 Nacos --server.port 是否压过 application.properties：",
          "若主口实测端口 == 我们指定的端口 → PASS（否则 Nacos 要改走 conf_copy，回补设计）")
    print("A5 ActiveMQ console 是否前台不弹独立窗："
          "（人工确认任务管理器里 java.exe 数量与窗口）")
    print("A6 -Djetty.http.port 能否压过 conf：本期未尝试，保持「未验证」")
    print("A7 结论请回写两份 spec：计划一 §2.4 第 2、4 项；计划二 §8.2")
    return 0


if __name__ == "__main__":
    if LAUNCH_KEY is not None:
        raise SystemExit(launch_drill(LAUNCH_KEY, APPLY_FLAG))
    raise SystemExit(main_drill(APPLY_FLAG))
