"""真机全组件功能矩阵：下载 → 安装 → 环境变量/PATH → 干净环境可用 → 切版本 → 启停。

与既有 *_tests.py 的区别：这些用例**全部走产品真实代码路径**，不 mock、不联网假数据。
落位调的是 main.install_downloaded（ComponentCard._on_download_ok 自己也在调它），
环境变量读的是 HKCU\\Environment 的持久层真值，启停走 main.ServiceManager。

用法：
    python bt_live_matrix.py --keys maven,go --phase install
    python bt_live_matrix.py --phase launch --keys tomcat,nginx
    python bt_live_matrix.py --keys all --phase all --report live_report.json

设计纪律：
  - 每一步都留证据（HTTP 码、文件路径、注册表值、stderr 尾巴），没有证据不算通过。
  - 失败不抛栈中断整轮：记进结果表，继续跑下一个组件（一轮跑完再统一修）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # 仓库根（本脚本在 tools/ 下）

from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main  # noqa: E402

# ---------------------------------------------------------------------------
# 全局结果表
# ---------------------------------------------------------------------------
RESULTS: List[Dict[str, object]] = []
VERBOSE = False


def log(msg: str) -> None:
    print(msg, flush=True)


def vlog(msg: str) -> None:
    if VERBOSE:
        print(f"      · {msg}", flush=True)


def record(key: str, phase: str, check: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append({"key": key, "phase": phase, "check": check,
                    "ok": bool(ok), "detail": detail})
    flag = "PASS" if ok else "FAIL"
    line = f"  [{flag}] {key}/{phase}/{check}"
    if detail and (not ok or VERBOSE):
        line += f" — {detail}"
    log(line)
    return ok


# ---------------------------------------------------------------------------
# Qt 事件循环驱动（DownloadWorker 是 QThread，必须有事件循环才收得到信号）
# ---------------------------------------------------------------------------
_APP: Optional[QApplication] = None


def qt_app() -> QApplication:
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication(sys.argv[:1])
    return _APP


# ---------------------------------------------------------------------------
# 环境与注册表读取（持久层真值）
# ---------------------------------------------------------------------------
def read_registry_env(name: str) -> Optional[str]:
    """读 HKCU\\Environment 里的持久层值（进程内 os.environ 可能是旧的）。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as k:
            value, _ = winreg.QueryValueEx(k, name)
            return value
    except Exception:
        return None


def registry_path_entries() -> List[str]:
    raw = read_registry_env("Path") or ""
    return [p for p in raw.split(";") if p.strip()]


def minimal_env() -> Dict[str, str]:
    """模拟"什么都没配过的新机器"：不继承当前进程 PATH / 各家 *_HOME。

    只留 Windows 起进程所必需的东西；这个环境里如果组件的命令还能找到并跑出版本号，
    说明本工具写下的配置**自己就够用**，不靠机器上原有的环境。
    """
    keep = ("SystemRoot", "SystemDrive", "SystemDirectory", "WINDIR", "COMSPEC",
            "PATHEXT", "TEMP", "TMP", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
            "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "OS",
            "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "USERNAME", "USERDOMAIN",
            "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
            "PROGRAMDATA", "ALLUSERSPROFILE", "COMPUTERNAME", "PUBLIC", "LANG")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    # 只留系统段（用户段全部剥掉）——这正是"从没配过环境变量"的机器形态
    machine_path = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                            0, winreg.KEY_READ) as k:
            machine_path = [p for p in (winreg.QueryValueEx(k, "Path")[0] or "").split(";") if p]
    except Exception:
        machine_path = []
    env["PATH"] = ";".join(machine_path) or os.environ.get("PATH", "")
    env.pop("pythonhome", None)
    return env


def run_in_env(cmd: List[str], env: Dict[str, str], timeout: int = 20):
    """在给定环境里跑命令，返回 (returncode, 合并输出的第一行)。"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env=env, check=False,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        first = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
        return proc.returncode, first, out
    except Exception as exc:
        return -1, f"<{type(exc).__name__}: {exc}>", ""


def which_in_env(name: str, env: Dict[str, str]) -> str:
    """在给定环境的 PATH 里找可执行文件（不依赖宿主进程的 shutil.which）。"""
    exts = [""] + (env.get("PATHEXT") or ".EXE;.CMD;.BAT").split(";")
    for d in (env.get("PATH") or "").split(";"):
        d = d.strip()
        if not d:
            continue
        for ext in exts:
            cand = Path(d) / (name + ext.lower())
            if cand.is_file():
                return str(cand)
            cand2 = Path(d) / (name + ext)
            if cand2.is_file():
                return str(cand2)
    return ""


# ---------------------------------------------------------------------------
# 下载（走产品 DownloadWorker）
# ---------------------------------------------------------------------------
def download_file(urls: List[str], dest: Path, label: str = "") -> Path:
    ensure = main.ensure_dir(dest.parent)
    qt_app()
    worker = main.DownloadWorker(urls, dest)
    loop = QEventLoop()
    state = {"ok": False, "err": ""}
    seen = {"pct": -1}

    def on_prog(done: int, total: int) -> None:
        pct = int(done * 100 / total) if total else 0
        if pct // 20 != seen["pct"] // 20:
            seen["pct"] = pct
            vlog(f"{label} 下载 {pct}%")

    worker.progress.connect(on_prog)
    worker.finished_ok.connect(lambda p: (state.update(ok=True), loop.quit()))
    worker.finished_fail.connect(lambda m: (state.update(err=m), loop.quit()))
    worker.finished.connect(loop.quit)
    worker.start()
    loop.exec()
    # QThread 必须显式等它真结束：loop.quit() 由 finished 信号触发，但对象此时
    # 若被 GC，Qt 会打 "QThread: Destroyed while thread is still running" 并 abort。
    worker.wait(10000)
    if not state["ok"]:
        raise RuntimeError(f"下载失败：{state['err']}")
    return dest


def suffix_for(comp: main.Component, cv: main.ComponentVersion, urls: List[str]) -> str:
    """下载文件的后缀必须与**真实的包体形态**一致（extract_archive 按后缀选分支）。

    这段刻意与 ComponentCard.on_install_clicked 的算法保持一致，因为它是
    "文件名契约"而不是可复用逻辑；两边不一致会让演练绿灯但用户点下去失败。
    """
    if comp.installer_mode:
        ext = cv.archive_map.get(main.CURRENT_OS, "")
        if not ext:
            first = urls[0] if urls else ""
            ext = "exe" if first.endswith(".exe") else ("sh" if first.endswith(".sh") else "bin")
        return f".{ext}"
    ext = cv.archive_for_current()
    return {"zip": ".zip", "tar.gz": ".tar.gz", "tgz": ".tar.gz",
            "exe": ".exe", "war": ".war", "": "", "bin": ""}.get(ext, f".{ext}")


def download_to_cache(comp: main.Component, cv: main.ComponentVersion) -> Path:
    """下载到组件的 downloads 目录，已存在且非空则直接复用。"""
    urls = cv.urls_for_current()
    if not urls:
        raise RuntimeError("该版本在当前平台没有可用下载地址")
    dest = main.CONFIG_DIR / comp.key / "downloads" / f"{comp.key}-{cv.version}{suffix_for(comp, cv, urls)}"
    if dest.is_file() and dest.stat().st_size > main.DOWNLOAD_MIN_VALID_BYTES:
        vlog(f"复用已下载：{dest.name} ({main.human_size(dest.stat().st_size)})")
        return dest
    return download_file(urls, dest, label=f"{comp.key}-{cv.version}")


# ---------------------------------------------------------------------------
# 各阶段
# ---------------------------------------------------------------------------
def phase_audit(comp: main.Component) -> None:
    key = comp.key
    inst = main.installed_versions(comp)
    detail = ", ".join(f"{v}({p.name})" for v, p in inst) or "磁盘上未安装"
    record(key, "audit", "installed_versions", True, detail)

    urls = comp.versions[0].urls_for_current() if comp.versions else []
    record(key, "audit", "has_download_url", bool(urls),
           f"{len(urls)} 个源，首选 {urls[0][:90]}" if urls else
           (comp.unsupported_platform_hint or "无 URL 且没有 unsupported_platform_hint"))

    if comp.env_var:
        real = read_registry_env(comp.env_var)
        entries = registry_path_entries()
        target_bin = None
        for v, p in inst:
            cand = str(p / comp.path_subdir) if comp.path_subdir else str(p)
            if any(main.EnvManager._same_path(e, cand) for e in entries):
                target_bin = cand
                break
        ok = bool(real) and real.lower().startswith(str(main.CONFIG_DIR / comp.key).lower())
        record(key, "audit", "registry_home", ok,
               f"{comp.env_var}={real}" + ("" if ok else "（未指向本工具安装目录）"))
        record(key, "audit", "registry_path", bool(target_bin),
               target_bin or "已装版本的 bin 目录不在 HKCU Path 里")


def phase_install(comp: main.Component, version: str) -> Optional[Path]:
    """下载 + 落位（走 install_downloaded）+ 环境配置，返回安装目录或 None。"""
    key = comp.key
    cv = next((c for c in comp.versions if c.version == version), None)
    if cv is None:
        record(key, "install", "version_in_catalog", False, f"清单里没有 {version}")
        return None

    t0 = time.time()
    try:
        archive = download_to_cache(comp, cv)
    except Exception as exc:
        record(key, "install", "download", False, str(exc)[:300])
        return None
    record(key, "install", "download", True,
           f"{archive.name} {main.human_size(archive.stat().st_size)} "
           f"{time.time() - t0:.1f}s")

    logs: List[str] = []

    def emit(level: str, message: str) -> None:
        logs.append(f"{level}: {message}")
        vlog(f"[{level}] {message}")

    t1 = time.time()
    try:
        final = main.install_downloaded(comp, version, archive, emit)
    except Exception as exc:
        record(key, "install", "install_downloaded", False,
               f"{exc} | {' / '.join(logs[-3:])}"[:400])
        return None
    record(key, "install", "install_downloaded", final.is_dir(),
           f"{final} {time.time() - t1:.1f}s")

    exe = comp.exec_path_in_home(str(final))
    record(key, "install", "exec_path_in_home", exe is not None,
           str(exe) if exe else f"在 {final} 下找不到 {comp.exec_name}")

    # 环境配置：产品在解压成功后调 _configure_after_extract（多版本走原子切换）
    try:
        if comp.multi_version:
            version_from_dir = main.version_from_install_dir(comp, final)
            steps = main.apply_active_version(comp, version_from_dir or version)
            main.save_active_version(key, version_from_dir or version)
        else:
            steps = []
        record(key, "install", "apply_active_version", True, "；".join(steps)[:200])
    except Exception as exc:
        record(key, "install", "apply_active_version", False, str(exc)[:300])

    if comp.env_var:
        real = read_registry_env(comp.env_var)
        ok = bool(real) and Path(real).resolve() == final.resolve()
        record(key, "install", "env_var_points_here", ok,
               f"{comp.env_var}={real}" if not ok else f"{comp.env_var}={real}")
    else:
        record(key, "install", "env_var_points_here", True, "该组件无 *_HOME（只进 PATH）")

    bin_dir = str(final / comp.path_subdir) if comp.path_subdir else str(final)
    entries = registry_path_entries()
    ok = any(main.EnvManager._same_path(e, bin_dir) for e in entries)
    record(key, "install", "path_entry_persisted", ok,
           bin_dir if not ok else f"已在 HKCU Path 中：{bin_dir}")

    # 组件的 bin 目录是否真的在**系统级合成路径**里可见
    composed = main.EnvManager.composed_env()
    composed_entries = {main.EnvManager._norm_path(e)
                        for e in (composed.get("PATH") or "").split(";") if e}
    record(key, "install", "path_visible_in_composed_env",
           (not composed_entries) or
           main.EnvManager._norm_path(bin_dir) in composed_entries,
           f"合成 PATH 命中={bin_dir}")
    return final


def _probe_command(comp: main.Component, exe: str) -> List[str]:
    """版本探测命令。nginx 的 -v 输出走 stderr 且需要 cwd，另行处理。"""
    if comp.key == "nginx":
        return [exe, "-v"]
    if not comp.version_probe:
        return []
    return [exe, *comp.version_args]


def phase_verify(comp: main.Component, final: Path) -> None:
    """装完能不能用：本进程环境 + 干净（无用户环境变量）环境各验一次。"""
    key = comp.key
    exe = comp.exec_path_in_home(str(final))
    if exe is None:
        record(key, "verify", "usable", False, "没有可执行文件，跳过可用性验证")
        return

    cmd = _probe_command(comp, str(exe))
    if cmd:
        env_host = dict(os.environ)
        # 只补本工具自己写的那几项，其余用宿主进程的：这验证"装完立刻能用"
        if comp.env_var:
            env_host[comp.env_var] = str(final)
        env_host["PATH"] = os.pathsep.join(
            [str(final / comp.path_subdir) if comp.path_subdir else str(final),
             os.environ.get("PATH", "")])
        rc, first, _ = run_in_env(cmd, env_host)
        record(key, "verify", "runs_in_host_env", rc == 0 and bool(first),
               f"rc={rc} out={first[:90]}")

        env_clean = minimal_env()
        if comp.env_var:
            home_val = read_registry_env(comp.env_var)
            if home_val:
                env_clean[comp.env_var] = home_val
        entries = registry_path_entries()
        clean_path = ";".join(entries + [env_clean.get("PATH", "")])
        env_clean["PATH"] = clean_path
        found = which_in_env(comp.exec_name + ".exe", env_clean) or \
            which_in_env(comp.exec_name, env_clean)
        record(key, "verify", "found_in_clean_env_path", bool(found),
               found or f"剥离用户环境后 PATH 里找不到 {comp.exec_name}")
        if found:
            cmd2 = _probe_command(comp, found)
            if cmd2:
                rc2, first2, _ = run_in_env(cmd2, env_clean)
                record(key, "verify", "runs_in_clean_env", rc2 == 0 and bool(first2),
                       f"rc={rc2} out={first2[:90]}")
    else:
        # 不可执行探测的组件（jenkins 的 war；nacos/seata/kafka 启动脚本型）
        if comp.key == "jenkins":
            war = final / (comp.exec_name or "jenkins.war")
            ok = war.is_file() or any(final.glob("*.war"))
            record(key, "verify", "runs_in_host_env", ok,
                   f"war 文件存在={ok}（启动验证在 launch 阶段）")
        else:
            record(key, "verify", "runs_in_host_env", True,
                   "该组件不执行版本探测（启动脚本型，交给 launch 阶段）")

    # 探测状态机（界面"已配置"图标依赖它）
    try:
        det = comp.detect(probe_version=False)
        record(key, "verify", "detect_says_installed", bool(det.installed),
               f"installed={det.installed} source={det.source} home={det.home} version={det.version_text}")
    except Exception as exc:
        record(key, "verify", "detect_says_installed", False, f"{type(exc).__name__}: {exc}")


def phase_switch(comp: main.Component, version_a: str, version_b: str) -> None:
    """装第二个版本 → 来回切 → 每一步都读持久层复验。"""
    key = comp.key
    home_b = comp.install_dir(version_b)
    if not home_b.is_dir():
        try:
            archive = download_to_cache(comp, next(c for c in comp.versions
                                                   if c.version == version_b))
            main.install_downloaded(comp, version_b, archive, lambda l, m: vlog(f"[{l}] {m}"))
        except Exception as exc:
            record(key, "switch", f"install_{version_b}", False, str(exc)[:250])
            return
    record(key, "switch", f"install_{version_b}", home_b.is_dir(), str(home_b))

    for target in (version_b, version_a):
        home = comp.install_dir(target)
        try:
            steps = main.apply_active_version(comp, target)
            main.save_active_version(key, target)
            err = [s for s in steps if "失败" in s]
            record(key, "switch", f"apply_{target}", not err, "；".join(steps)[:180])
        except main.SwitchError as exc:
            record(key, "switch", f"apply_{target}", False, str(exc)[:250])
            continue
        if comp.env_var:
            real = read_registry_env(comp.env_var)
            record(key, "switch", f"{comp.env_var}_{target}",
                   bool(real) and Path(real).resolve() == home.resolve(),
                   f"{comp.env_var}={real}")
        entries = registry_path_entries()
        mine = [e for e in entries
                if main.EnvManager._under_root(e, str(main.CONFIG_DIR / key))]
        bin_dir = str(home / comp.path_subdir) if comp.path_subdir else str(home)
        record(key, "switch", f"path_collapsed_{target}",
               len(mine) == 1 and main.EnvManager._same_path(mine[0], bin_dir),
               f"本组件 PATH 条目={mine}")


# --- 启停 -------------------------------------------------------------------
TOOL_DEFAULT_PASSWORD = {
    "nacos": ("nacos", "nacos"),
}


def phase_launch(comp: main.Component, comps: Dict[str, main.Component]) -> None:
    key = comp.key
    spec = comp.launch
    mgr = main.ServiceManager()

    # 「开机就能用」：前置运行时（JDK / Erlang）缺失时先自动装好再启动。
    # 这一段走的就是界面 on_start_clicked → _install_missing_prereqs 的同一条逻辑。
    missing = main.prereq_components(comp, comps)
    if missing:
        record(key, "launch", "prereq_missing_detected", True, "缺：" + ",".join(missing))
        installed: List[str] = []
        ok_pre = True
        for pre_key in missing:
            pre = comps.get(pre_key)
            if pre is None:
                ok_pre = False
                break
            version = main.pick_prereq_version(pre, main.prereq_install_versions(comp))
            home = pre.install_dir(version) if version else None
            if home is None or not main.prereq_already_installed(pre, version):
                try:
                    archive = download_to_cache(
                        pre, next(c for c in pre.versions if c.version == version))
                    main.install_downloaded(pre, version, archive,
                                            lambda l, m: vlog(f"[{l}] {m}"))
                except Exception as exc:
                    record(key, "launch", f"prereq_install_{pre_key}", False, str(exc)[:250])
                    ok_pre = False
                    continue
            ok_pre = ok_pre and main.prereq_already_installed(pre, version)
            installed.append(f"{pre_key} {version} → {home}")
        record(key, "launch", "prereq_auto_installed", ok_pre, "；".join(installed))
        missing_after = main.prereq_components(comp, comps)
        record(key, "launch", "prereq_resolved", not missing_after,
               "仍缺：" + ",".join(missing_after) if missing_after else "前置已就位")
        if missing_after:
            return

    st = mgr.status(key, comp)
    if st.state == "running":
        # 上一轮中途失败（或用户自己留着）会让组件还开着。**先把它干净地停掉再测**，
        # 而不是把"启动前就登记为运行中"当成失败：那是上一轮的残留，不是产品的错。
        record(key, "launch", "pre_state_cleaned", True, f"启动前已是运行中，先停止：{st.reason}")
        re_stop = mgr.stop(comp, comps)
        if not re_stop.ok and re_stop.need_force:
            re_stop = mgr.force_stop(key)
        if not re_stop.ok:
            record(key, "launch", "not_already_running", False,
                   f"残留实例停不掉，无法测启动：{re_stop.reason}")
            return
        time.sleep(2)

    res = mgr.start(comp, comps)
    if not res.ok:
        tail = ""
        try:
            logf = main.CONFIG_DIR / f"{key}-data" / "logs" / "byte-tools.out"
            if logf.is_file():
                tail = " | 日志尾巴：" + " / ".join(
                    logf.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-4:])
        except Exception:
            pass
        record(key, "launch", "start", False, f"[{res.stage}] {res.reason}{tail}"[:600])
        return
    record(key, "launch", "start", True, f"console={res.console_url}（{res.reason}）")

    ports = tuple(res.record.ports) or (res.record.port,)
    listening = [p for p in ports if main.port_is_listening(p)]
    record(key, "launch", "all_ports_listening", len(listening) == len(ports),
           f"监听中={listening} 期望={list(ports)}")

    if res.console_url and spec.console_path:
        # 控制台要**等到真的能开**再说它好：Jenkins 的 8080 一监听就返回 503
        # 「Please wait while Jenkins is getting ready to work」（实测启动初期
        # 846 字节的临时页），此时判失败是误报；用户此刻点控制台也确实打不开，
        # 所以两边都要说清：给 240 秒轮询窗口，并把最后一次的状态码记下来。
        code = 0
        auth_header = ""
        body_len = 0
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                r = requests.get(res.console_url, timeout=8, headers=main.HTTP_UA,
                                 allow_redirects=True)
                code = r.status_code
                auth_header = r.headers.get("WWW-Authenticate", "")
                body_len = len(r.content or b"")
            except requests.exceptions.ConnectionError:
                code = 0                      # 还没起来，继续等
            except requests.exceptions.RequestException as exc:
                # 连接是通的、只是响应体解码/分块出错（Jenkins 无 Content-Type 时
                # requests 猜编码会抛 UnicodeDecodeError 包成的 ContentDecodingError）。
                # 服务本身是活的，别判成"控制台不可用"。
                code = 200
                vlog(f"console GET 返回但解析失败（服务在响应）：{type(exc).__name__}")
            # 401 也算"控制台服务正常"：ActiveMQ 的 /admin 就是带 Basic 鉴权的入口，
            # 拿不到凭据时 401 + WWW-Authenticate 是**正确响应**，不是坏。
            if (200 <= code < 400) or (code == 401 and auth_header):
                break
            time.sleep(3)
        ok = (200 <= code < 400) or (code == 401 and bool(auth_header)) or code == 403
        record(key, "launch", "console_http_ok", ok,
               f"GET {res.console_url} → {code}（{body_len} 字节"
               + (f"，WWW-Authenticate: {auth_header}" if auth_header else "") + "）")

    # 「每个可启停组件都要有一个打开就能看的页面」（2026-10-08 用户要求）：
    # 自带 Web 界面的取它自己的地址；协议端口型（kafka/rocketmq/rabbitmq）由工具
    # 自带的页服务给一张「启动成功」页。两条路都必须真的能 200 打开。
    try:
        page_url = main.show_launch_page(comp, spec, res.record)
    except Exception as exc:
        page_url = None
        record(key, "launch", "access_page_url", False, f"生成访问页异常：{exc}")
    if page_url:
        try:
            pr = requests.get(page_url, timeout=10, headers=main.HTTP_UA)
            # 与上面控制台同一口径：401 + WWW-Authenticate（ActiveMQ 的 /admin 就是
            # 带 Basic 鉴权的入口）与 403（Jenkins 初始化完成后自身返回的"要登录"）
            # 都说明**服务在正常响应**。只有 404 / 5xx 才算"页面打不开"。
            pr_ok = (200 <= pr.status_code < 400
                     or (pr.status_code == 401 and pr.headers.get("WWW-Authenticate"))
                     or pr.status_code == 403)
            record(key, "launch", "access_page_opens", bool(pr_ok),
                   f"GET {page_url} → {pr.status_code}（{len(pr.content)} 字节）")
            if not spec.console_path:
                # 自带页必须能反映"正在运行"这个状态（停掉之后会自动变「已停止」）
                record(key, "launch", "access_page_says_running",
                       "正在运行" in pr.text,
                       f"{page_url} 的正文里没有「正在运行」")
        except Exception as exc:
            record(key, "launch", "access_page_opens", False, f"{page_url} → {exc}")
    else:
        record(key, "launch", "access_page_url", False,
               "既没有 console_path 也没拿到自带页 URL —— 用户启动后无页面可看")

    if spec.service_probe:
        # 探针命令里带 {java}/{home}/{port} 占位符，必须按 plan 的映射展开，
        # 否则 subprocess 会拿字面量 "{java}" 去执行 → FileNotFoundError（假失败）。
        # 环境也必须用**产品真正会注入的那一份**（extra_env：rabbitmq 的
        # RABBITMQ_NODENAME/RABBITMQ_BASE、ES 的 CLASSPATH="" 等）：
        # 少一个变量就会把"产品能跑"误判成"探针失败"（2026-10-08 实测：
        # 不带 RABBITMQ_NODENAME 时 rabbitmqctl 在中文主机名机器上 rc=70）。
        version = main.resolve_launch_version(comp) or comp.versions[0].version
        java_home = main.resolve_java_home(comps) or ""
        plan = main.build_launch_plan(comp, spec, java_home, ports[0],
                                      main.CONFIG_DIR / f"{key}-data" / "logs" / "byte-tools.out")
        mapping = main._plan_mapping(comp, spec, plan)
        argv = [a.format(**mapping) for a in spec.service_probe]
        rc, first, _ = run_in_env(argv, plan.env, timeout=120)
        record(key, "launch", "service_probe", rc == 0, f"rc={rc} out={first[:120]}")

    stop = mgr.stop(comp, comps)
    if not stop.ok and stop.need_force:
        stop = mgr.force_stop(key)
    record(key, "launch", "stop", stop.ok, (stop.reason or "")[:200])
    time.sleep(1.0)
    left = [p for p in ports if main.port_is_listening(p)]
    record(key, "launch", "ports_released", not left, f"仍在听={left}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
LAUNCH_ORDER = ["nginx", "tomcat", "activemq", "rocketmq", "kafka",
                "elasticsearch", "seata", "nacos", "rabbitmq", "jenkins"]


def parse_keys(raw: str) -> List[str]:
    # `all` 可以出现在逗号列表里（`--keys all,erlang`）：这时它展开成全部可见组件，
    # 其余项照原样处理。原来只认"整个字符串等于 all"，`all,erlang` 会被当成两个
    # 不存在的 key 直接跳过 —— 看着跑完了，其实一项没测（本机踩过）。
    out: List[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "all":
            out.extend(c.key for c in main.build_components() if not c.hidden)
        else:
            out.append(part)
    return out or [c.key for c in main.build_components() if not c.hidden]


def phase_autoprereq(comps: Dict[str, main.Component]) -> None:
    """「缺前置就自动装好」的真机验证（不依赖机器上恰好缺 JDK）。

    做法是把 JAVA_HOME 与 PATH 里的 java 都摘掉、并屏蔽已装的 JDK 目录，
    让 prereq_components() 真的报"缺 jdk"；再走一遍界面点「启动」时会走的
    那条自动安装路径（下载 → install_downloaded → 复验），最后确认门控放行。
    全程不改注册表、不动用户已有的 JDK（进程内环境变量用完即弃）。
    """
    key = "autoprereq"
    target = comps["kafka"]          # 需要 JDK 且带 min_java_major=17 的组件
    saved_env = {k: os.environ.get(k) for k in ("PATH", "JAVA_HOME")}
    saved_resolve = main.resolve_java_home
    jdk_comp = comps["jdk"]
    # 屏蔽"本工具装过的 JDK"：patched 到实例上（不是类上），用完还原，
    # 免得后面的用例看到被改过的类。
    real_installed_dirs = jdk_comp.installed_dirs

    try:
        os.environ.pop("JAVA_HOME", None)
        os.environ["PATH"] = ";".join(
            p for p in (saved_env.get("PATH") or "").split(";")
            if "jdk" not in p.lower() and "java" not in p.lower())
        main.resolve_java_home = lambda c: None      # 装作一个 JDK 都没有
        jdk_comp.installed_dirs = lambda: []
        missing = main.prereq_components(target, comps)
        record(key, "prereq", "detects_missing_jdk", missing == ["jdk"],
               f"缺={missing}")

        pre = jdk_comp
        version = main.pick_prereq_version(pre, main.prereq_install_versions(target))
        record(key, "prereq", "picked_version", bool(version), f"jdk {version}")
        if not version:
            return
        if not main.prereq_already_installed(pre, version):
            archive = download_to_cache(pre, next(c for c in pre.versions
                                                  if c.version == version))
            main.install_downloaded(pre, version, archive, lambda l, m: vlog(f"[{l}] {m}"))
        home = pre.install_dir(version)
        record(key, "prereq", "jdk_installed", main.prereq_already_installed(pre, version),
               str(home))
        record(key, "prereq", "jdk_major_readable", main.java_major_of(str(home)) == 21,
               f"major={main.java_major_of(str(home))}")
    finally:
        main.resolve_java_home = saved_resolve
        jdk_comp.installed_dirs = real_installed_dirs
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # 把生效版本切到刚装的 JDK，再验门控真的放行（这一步会写注册表，是真实行为）
    try:
        steps = main.apply_active_version(comps["jdk"], version)
        main.save_active_version("jdk", version)
        record(key, "prereq", "apply_jdk_active", True, "；".join(steps)[:180])
    except Exception as exc:
        record(key, "prereq", "apply_jdk_active", False, str(exc)[:250])
    ok, why = main.launch_gate(target, target.launch,
                               main.resolve_java_home(comps))
    record(key, "prereq", "launch_gate_passes", ok,
           why or f"JAVA_HOME={main.resolve_java_home(comps)}")


def main_flow() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="all")
    ap.add_argument("--phase", default="all",
                    choices=["audit", "install", "verify", "switch", "launch", "all"])
    ap.add_argument("--switch-to", default="",
                    help="逗号分隔的 key：对这些组件额外装第二个版本并来回切换")
    ap.add_argument("--report", default="live_report.json")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    global VERBOSE
    VERBOSE = args.verbose

    # 注意：CONFIG_DIR 在 import main 时就已经定好了，重定向必须在外层进程里设
    # （用 --config-dir 环境变量做不到，所以这里只做事实记录，不假装能改）
    log(f"CONFIG_DIR = {main.CONFIG_DIR}")
    log(f"CURRENT_OS = {main.CURRENT_OS}  MACHINE = {main.MACHINE}")
    comps = {c.key: c for c in main.build_components()}
    keys = parse_keys(args.keys)
    unknown = [k for k in keys if k not in comps and k != "autoprereq"]
    if unknown:
        log(f"[WARN] 未知组件 key：{unknown}")
    keys = [k for k in keys if k in comps or k == "autoprereq"]
    switch_keys = {k.strip() for k in args.switch_to.split(",") if k.strip()}

    if "autoprereq" in keys:
        log("\n=== autoprereq（缺 JDK → 自动装好 → 门控放行）===")
        phase_autoprereq(comps)
        keys = [k for k in keys if k != "autoprereq"]

    for key in keys:
        comp = comps[key]
        log(f"\n=== {key} ({comp.display_name}) ===")
        try:
            if args.phase in ("audit", "all"):
                phase_audit(comp)
            if args.phase in ("install", "verify", "switch", "all"):
                # 优先测"产品离线清单里用户点得到的第一个版本"；该版本已在磁盘上就直接复验，
                # 免得为了一个同版本重下几百 MB。清单首位没装时才真的下它 ——
                # 这也是"用户拿到最新版软件、清单里那个版本还能不能下"的实测。
                installed = [v for v, _ in main.installed_versions(comp)]
                pick = None
                for cv in comp.versions:
                    if cv.urls_for_current():
                        pick = cv.version
                        break
                if pick is None and installed:
                    pick = installed[0]
                if pick is None:
                    record(key, "install", "pick_version", False, "清单里没有任何可下载版本")
                    continue
                log(f"  目标版本：{pick}（磁盘上已装：{installed or '无'}）")
                home = comp.install_dir(pick)
                if not home.is_dir():
                    home = phase_install(comp, pick)
                else:
                    record(key, "install", "already_installed", True, str(home))
                    # 环境可能是旧的，仍然走一遍切换以验证幂等
                    try:
                        steps = main.apply_active_version(comp, pick)
                        main.save_active_version(key, pick)
                        record(key, "install", "reapply_active", True, "；".join(steps)[:160])
                    except Exception as exc:
                        record(key, "install", "reapply_active", False, str(exc)[:200])
                if home and home.is_dir() and args.phase in ("verify", "switch", "all"):
                    phase_verify(comp, home)
                    # 装完就删掉 >50MB 的下载缓存：本机只剩几 GB 空闲，
                    # 26 个组件的归档攒起来要 3GB+（产品自己也会一直留着它们，
                    # 这一点写进了报告，但演练本身不能被磁盘卡住）。
                    try:
                        for leftover in (main.CONFIG_DIR / comp.key / "downloads").glob("*"):
                            if leftover.is_file() and leftover.stat().st_size > 50 * 1024 * 1024:
                                leftover.unlink()
                                vlog(f"清理归档缓存 {leftover.name}")
                    except Exception:
                        pass
                if key in switch_keys and home and home.is_dir():
                    other = next((cv.version for cv in comp.versions
                                  if cv.version != pick and cv.urls_for_current()), None)
                    if other:
                        phase_switch(comp, pick, other)
                    else:
                        record(key, "switch", "second_version_available", False,
                               "清单里没有第二个可下载版本")
            if args.phase in ("launch", "all") and comp.launch is not None:
                phase_launch(comp, comps)
        except Exception:
            record(key, "harness", "no_exception", False, traceback.format_exc()[-500:])

    # ---- 汇总 ----
    total = len(RESULTS)
    failed = [r for r in RESULTS if not r["ok"]]
    log("\n" + "=" * 78)
    log(f"总计 {total} 项检查，失败 {len(failed)} 项")
    for r in failed:
        log(f"  FAIL {r['key']}/{r['phase']}/{r['check']} — {str(r['detail'])[:220]}")
    Path(args.report).write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    log(f"明细已写入 {args.report}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main_flow())
