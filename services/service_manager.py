"""服务生命周期管理（从 main.py 抽出，规则 R30）。

依赖以 ``_main.<name>`` 晚绑定：main import 本模块后调用
``configure(sys.modules[__name__])``，每次调用都取 main 的当前属性。
测试 patch main.* 仍然生效，也不形成 services → main 的循环 import。
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


_main = None


def configure(main_module) -> None:
    global _main
    _main = main_module


class ServiceManager:
    """本机进程生命周期的唯一入口。探针全部可注入，测试因此不碰网络也不碰进程。"""

    def __init__(self, is_listening=None, http_ok=None,
                 process_alive=None, terminate=None, lookup_pids=None,
                 process_images=None):
        # 默认值晚绑定：本模块 import 时 main 尚未初始化完成，默认参数在 def 时求值。
        is_listening = is_listening or _main.port_is_listening
        http_ok = http_ok or _main.http_ok
        process_alive = process_alive or _main.process_is_alive
        self._is_listening = is_listening
        self._http_ok = http_ok
        self._process_alive = process_alive
        self._terminate = terminate or self._terminate_by_pid
        # 端口反查的注入点。用 lambda 包一层而不是把函数当默认值绑死：
        # 默认参数在 def 时求值，测试 patch main.netstat_listener_pids 就会失效
        # （这个坑计划一的 start() 已经踩过并写进注释）。
        self._lookup_pids = lookup_pids or (lambda ports: _main.netstat_listener_pids(ports))
        # 同上：残留辅助进程的查询也是子进程调用，只给停止路径收尾用（见 LaunchSpec.leftover_processes）。
        self._process_images = process_images or (
            lambda names: _main.running_process_images(names))

    @staticmethod
    def _terminate_by_pid(rec: _main.RunRecord) -> None:
        """只结束我们自己登记过的 PID。

        spec §2 说明 Nacos / ActiveMQ 的 PID 不可信，所以计划二必须走正规
        shutdown 脚本；本期 Jenkins 我们就是服务进程，terminate 才成立。
        非 server 角色一律不动手 —— 这条守卫是"绝不误杀别人进程"的最后防线。"""
        if rec.pid_role != "server" or rec.pid is None or rec.pid <= 0:
            return
        try:
            os.kill(rec.pid, 15)
        except OSError:
            pass

    def status(self, key: str, comp: _main.Component,
               records: Optional[Dict[str, _main.RunRecord]] = None) -> _main.LaunchStatus:
        if getattr(comp, "launch", None) is None:
            return _main.LaunchStatus("not_installed_or_stopped")
        if _main.service_spec_for(comp) is not None:
            return self._service_status(comp, records)
        rec = (records if records is not None else _main.load_running_map()).get(key)
        if rec is None:
            return _main.LaunchStatus("not_installed_or_stopped")
        # 按整簇判，不按单口：Nacos 主口在听、gRPC 9848 掉了是"半死"，
        # 显示成运行中会让用户以为客户端连得上（spec 计划二 §7）。
        # 老记录没有 ports 字段（加载侧才做归一），进程内现构造的也得能判，故按 port 兜底。
        silent = [p for p in (tuple(rec.ports) or (rec.port,))
                  if not self._is_listening(p)]
        if silent:
            return _main.LaunchStatus("zombie", rec,
                                f"登记的进程已不在监听 {'/'.join(str(p) for p in silent)}")
        return _main.LaunchStatus("running", rec)

    def adopt(self, comps: Dict[str, _main.Component]) -> List[_main.LaunchStatus]:
        """打开工具时对每个可启动组件做一次只读认定。绝不拉起进程。"""
        records = _main.load_running_map()
        self.backfill_service_records(comps, records)
        return [self.status(k, c, records) for k, c in sorted(comps.items())
                if getattr(c, "launch", None) is not None]

    def backfill_service_records(self, comps: Dict[str, _main.Component],
                                 records: Optional[Dict[str, _main.RunRecord]] = None) -> None:
        """把"服务在跑、但 running.json 里没有/已过期"的情况补登记。

        用户完全可能在 services.msc 里启动服务，或者上次关工具时服务还在跑；
        不补这一条，访问页与卡片就看不到它。全程只读 SCM，不启停任何东西。
        """
        recs = records if records is not None else _main.load_running_map()
        dirty = False
        for key, comp in comps.items():
            if _main.service_spec_for(comp) is None:
                continue
            rec = recs.get(key)
            if rec is not None and rec.pid_role != "service":
                continue                       # 便携模式的旧登记，不归这里管
            if rec is not None and rec.version:
                info = _main.service_info(comp, rec.version)
                if info.state == _main.SERVICE_RUNNING:
                    fresh = _main.service_run_record(comp, rec.version)
                    if fresh.to_dict() != rec.to_dict():
                        recs[key] = fresh
                        dirty = True
                    continue
                recs.pop(key, None)
                dirty = True
                continue
            for version, _path in _main.installed_service_versions(comp):
                if _main.service_info(comp, version).state == _main.SERVICE_RUNNING:
                    recs[key] = _main.service_run_record(comp, version)
                    dirty = True
                    break
        if dirty:
            _main.save_running_map(recs)

    def _service_status(self, comp: _main.Component,
                        records: Optional[Dict[str, _main.RunRecord]] = None) -> _main.LaunchStatus:
        recs = records if records is not None else _main.load_running_map()
        rec = recs.get(comp.key)
        version = (rec.version if rec is not None else "") or _main.resolve_launch_version(comp)
        if not version:
            return _main.LaunchStatus("not_installed_or_stopped")
        info = _main.service_info(comp, version)
        if info.state == _main.SERVICE_BROKEN:
            return _main.LaunchStatus("broken", rec,
                                f"服务 {info.name} 指向的文件已不存在（服务损坏）")
        if not info.exists and rec is not None and rec.pid_role != "service":
            # 还没切成服务的旧便携进程：先按它自己的登记报告运行状态，
            # 用户点「停止」时走 _portable_stop 收掉，之后就能正常装服务。
            legacy_ports = tuple(rec.ports) or (rec.port,)
            if any(self._is_listening(p) for p in legacy_ports):
                return _main.LaunchStatus("running", rec)
        if info.state != _main.SERVICE_RUNNING:
            return _main.LaunchStatus("not_installed_or_stopped")
        if rec is None or rec.service_name != info.name or rec.version != version:
            rec = _main.service_run_record(comp, version)
        ports = tuple(rec.ports) or (rec.port,)
        silent = [p for p in ports if not self._is_listening(p)]
        if silent:
            return _main.LaunchStatus("zombie", rec,
                                f"服务 {info.name} 在运行，但端口 "
                                f"{'/'.join(str(p) for p in silent)} 未监听")
        return _main.LaunchStatus("running", rec)

    def reconcile(self, comps: Dict[str, _main.Component]) -> Dict[str, _main.LaunchStatus]:
        """一次性认定 + 清僵尸：只处理 LAUNCH_KEYS 里的组件。

        计划二会往登记表加组件，届时旧登记不该被本期代码删掉，
        所以这里按"认得的 key"过滤，而不是清全部文件。"""
        records = _main.load_running_map()
        self.backfill_service_records(comps, records)
        out: Dict[str, _main.LaunchStatus] = {}
        dirty = False
        for key in _main.LAUNCH_KEYS:
            comp = comps.get(key)
            if comp is None or getattr(comp, "launch", None) is None:
                continue
            if key not in records:
                continue          # 没有登记的 key 不是"待认定"的东西：卡片自己的
                                  # status() 会答"未运行"，reconcile 只负责把有过登记的
                                  # 一条条判完，返回集因此可以为空（用例钉的就是这个）
            st = self.status(key, comp, records)
            if st.state == "zombie":
                records.pop(key, None)
                dirty = True
                st = _main.LaunchStatus("not_installed_or_stopped")
            out[key] = st
        if dirty:
            _main.save_running_map(records)
        return out

    def start(self, comp: _main.Component, comps: Dict[str, _main.Component],
              sleeper=time.sleep, version: Optional[str] = None,
              password: str = "", log: Optional[Callable[[str], None]] = None) -> _main.StartResult:
        spec = getattr(comp, "launch", None)
        if spec is None:
            return _main.StartResult(False, "gate", "本工具暂不支持启动该组件")
        if _main.service_spec_for(comp) is not None:
            return self._service_start(comp, version, password, sleeper, log)
        existing = _main.load_running_map().get(comp.key)
        if existing and self._is_listening(existing.port):
            return _main.StartResult(False, "gate",
                               f"{comp.display_name} 已在运行（端口 {existing.port}）",
                               record=existing, console_url=existing.console_url)

        java_home = _main.resolve_java_home(comps)
        ok, reason = _main.launch_gate(comp, spec, java_home)
        if not ok:
            return _main.StartResult(False, "gate", reason)

        base = spec.main_port
        # is_free 显式按名字传，不靠默认值绑定：默认参数在 def 时就把函数绑死了，
        # 测试 patch main.port_is_free 会失效。
        # 端口策略（2026-10-06 起）：只用官方默认端口，不平移；被占就结束占用者。
        # 结束掉了谁要告诉用户 —— "我杀了某个进程"这种事不说出来是不道德的。
        evicted: List[str] = []
        port_plan, why = _main.choose_ports(spec, is_free=_main.port_is_free, evicted=evicted)
        if not port_plan.main:
            return _main.StartResult(False, "port", why)
        port_notes = [f"端口被占用，已结束占用者：{x}" for x in evicted]

        data_dir = _main.CONFIG_DIR / f"{comp.key}-data"
        log_file = data_dir / "logs" / "byte-tools.out"
        # 只建数据目录本身，**不在 pre_start 之前建 logs/**：MySQL 的
        # --initialize-insecure 要求数据目录为空，多一个 logs/ 就报 "directory is unusable"。
        # 日志目录等前置准备跑完、真正 open 日志之前再建（见下面 with open 之前）。
        _main.ensure_dir(data_dir)
        # 端口回写必须在 spawn 之前做完：改了配置却没起进程、或起进程时配置没生效，
        # 两边状态对不上时比"没启动"更难归因。
        ok, why, notes = _main.prepare_ports(comp, spec, port_plan, data_dir)
        # "我结束了哪个进程"必须跟着结果回到卡片：静默杀进程却不说是谁，
        # 用户事后发现某程序被杀会完全不知道是哪一步干的。
        notes = list(port_notes) + list(notes)
        if not ok:
            return _main.StartResult(False, "writeback", why, notes=notes)
        plan = _main.build_launch_plan(comp, spec, java_home, port_plan.main, log_file)
        # 前置准备（kafka 的 KRaft format 等）。必须在 spawn 之前：
        # 配了 --ignore-formatted 所以重复跑幂等（实测 rc=0），
        # 而漏了它 kafka 会直接 `No readable meta.properties files found.`。
        ok_pre, why_pre, pre_notes = _main.run_pre_start(comp, spec, plan)
        notes = notes + list(pre_notes)
        if not ok_pre:
            return _main.StartResult(False, "prestart", why_pre, notes=notes)

        # 重定向句柄在 Popen 把它交给子进程后立刻由父进程关掉（with 退出）：
        # Windows 上父进程留着一个打开的日志句柄，既漏句柄又会让临时目录删不掉；
        # 子进程拿到的是 CreateProcess 复制过去的一份，关自己这份不影响它。
        _main.ensure_dir(log_file.parent)
        with open(plan.log_file, "ab", buffering=0) as log_fh:
            popen_kw = dict(cwd=str(plan.cwd), env=plan.env,
                            stdout=log_fh,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            if _main.CURRENT_OS == "Windows":
                popen_kw["creationflags"] = _main.DETACH_FLAGS | subprocess.CREATE_NEW_PROCESS_GROUP
                if _main.CREATE_NO_WINDOW:
                    popen_kw["creationflags"] |= _main.CREATE_NO_WINDOW
            else:
                popen_kw["start_new_session"] = True

            try:
                proc = subprocess.Popen(plan.argv, **popen_kw)
            except OSError as exc:
                return _main.StartResult(False, "spawn", f"拉起失败：{exc}")

            # 第二个进程（rocketmq 的 broker）。顺序在主进程之后 ——
            # broker 要向 namesrv 注册，namesrv 没起来它会反复重试。
            #
            # 拉起失败要**连主进程一起收掉**：留下一个"namesrv 在跑、broker 没起来"
            # 的半死状态，比直接失败更难归因（用户看到 9876 在听就以为服务可用）。
            for extra in (spec.extra_processes or []):
                try:
                    argv_extra = [t.format(**_main._plan_mapping(comp, spec, plan))
                                  for t in extra[_main.CURRENT_OS]]
                except (KeyError, IndexError):
                    return _main.StartResult(False, "spawn", f"启动命令里的占位符无法替换：{extra}")
                try:
                    subprocess.Popen(argv_extra, **popen_kw)
                except OSError as exc:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    return _main.StartResult(False, "spawn",
                                       f"第二个进程拉起失败：{exc}"
                                       f"（命令：{argv_extra[0]}）")

        # 有界探活：按"每轮 sleeper(1.0) 至多 startup_timeout 轮"计数而不是纯墙钟
        # deadline —— deadline 写法在 sleeper 被替换成 no-op 时会退化成烧 CPU 的
        # 忙等（提交信息钉的就是"有界探活后才登记"）。真实运行里每轮睡 1 秒，
        # 语义等价于 startup_timeout 秒内未监听即放弃。
        for _ in range(max(1, int(spec.startup_timeout))):
            # 整簇都要在听才算起来：Nacos 的 gRPC 9848/9849 与 ActiveMQ 的 broker 口
            # 没起来时控制台能开、客户端连不上，只探主口会登记成一个"半死"的运行中。
            if all(self._is_listening(p) for p in port_plan.all_ports):
                rec = _main.RunRecord(key=comp.key,
                                version=_main.resolve_launch_version(comp)
                                or comp.versions[0].version,
                                home=str(plan.cwd), data_dir=plan.env.get(spec.data_dir_env, ""),
                                port=port_plan.main, console_url=plan.console_url,
                                pid=proc.pid,
                                pid_role="server" if spec.stop_kind == "pid" else "launcher",
                                started_at=time.time(), launcher_cmd=list(plan.argv),
                                ports=port_plan.all_ports)
                records = _main.load_running_map()
                records[comp.key] = rec
                _main.save_running_map(records)
                # 端口全在听 ≠ 控制台能用。这里再探一次控制台（**不改判定**：
                # 服务进程已在监听、登记已落盘，就仍然是"启动成功"），
                # 把"控制台还没就绪"作为一条提示行交给界面，好让用户看到
                # "再等一会儿"而不是点开一个 503 页面以为坏了（Jenkins 实测就是这样）。
                note = self._console_readiness_note(spec, port_plan.main)
                if note:
                    notes = list(notes) + [note]
                return _main.StartResult(True, "running", record=rec,
                                   console_url=plan.console_url, notes=notes)
            sleeper(1.0)

        # 超时：把刚拉起的进程收掉，不留一个"没人登记的监听者"
        reason = (f"{spec.startup_timeout} 秒内端口 "
                  f"{'/'.join(str(p) for p in port_plan.all_ports)} 未监听"
                  f"（需要全部端口都在听）。启动输出见 {plan.log_file}，"
                  f"末尾内容：{self._tail(plan.log_file)}"
                  f"；{comp.display_name} 自身日志："
                  f"{_main.vendor_log_tails(data_dir, plan.cwd, comp.key)}")
        try:
            proc.terminate()
        except OSError as exc:
            # 收尸失败必须出声：这个进程恰恰不在 running.json 里（spec §5）
            reason += f"；进程可能仍在监听（PID {proc.pid}，收尸失败：{exc}）"
        return _main.StartResult(False, "timeout", reason, notes=notes)

    @staticmethod
    def _tail(path: Path, lines: int = 8) -> str:
        """失败归因要能直接看见（spec §5）：读日志末尾几行，读不到就说读不到。"""
        try:
            data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return "（日志还读不到）"
        return " / ".join(data[-lines:]) if data else "（日志为空）"

    def stop(self, comp: _main.Component, comps: Dict[str, _main.Component],
             deadline: float = 30.0, sleeper=time.sleep,
             version: Optional[str] = None,
             log: Optional[Callable[[str], None]] = None) -> _main.StopResult:
        if _main.service_spec_for(comp) is not None:
            return self._service_stop(comp, version, deadline, sleeper, log)
        return self._portable_stop(comp, deadline, sleeper)

    def _portable_stop(self, comp: _main.Component, deadline: float,
                       sleeper) -> _main.StopResult:
        rec = _main.load_running_map().get(comp.key)
        if rec is None:
            return _main.StopResult(False, reason=f"{comp.display_name} 没有本工具的启动登记，无法确定该停哪个进程。")
        spec = comp.launch
        if spec.stop_kind == "shutdown_command" and spec.shutdown_commands.get(_main.CURRENT_OS):
            # 占位符契约：这里喂得出 RunRecord 上的键（port/home/data_dir）。
            #
            # **env 必须与启动时一致**（2026-10-06 真机实测踩出来的）：
            # 之前这里 `subprocess.run(argv, cwd=rec.home)` 不传 env，
            # 于是 rabbitmqctl.bat 找不到 erl.exe（免安装 Erlang 不设系统变量）、
            # 拿不到 RABBITMQ_NODENAME —— 它**静默失败**（输出被 DEVNULL 吞掉），
            # 表现是「点了停止，30 秒后弹窗问要不要强杀」。
            # 能优雅停的组件必须真的优雅停下，否则这条路径等于没接。
            data_dir = rec.data_dir or str(_main.CONFIG_DIR / f"{comp.key}-data")
            #占位符要凑齐：stop 侧除了 port/home/data_dir，nginx 还要 {conf}
            #（它靠 -c 定位配置、不靠 cwd）—— 少一个就 KeyError 崩在停止流程里。
            argv = [t.format(port=rec.port, home=rec.home, data_dir=data_dir,
                             conf_dir=str(Path(data_dir) / "conf"),
                             conf=_main.config_file_for(comp, Path(data_dir)),
                             java="", war="",
                             log_file=str(Path(data_dir) / "logs" / "byte-tools.out"))
                    for t in spec.shutdown_commands[_main.CURRENT_OS]]
            env = dict(os.environ)
            if spec.extra_env:
                for name, template in spec.extra_env.items():
                    try:
                        env[name] = template.format(
                            port=rec.port, home=rec.home, data_dir=data_dir,
                            conf_dir=str(Path(data_dir) / "conf"), war="",
                            log_file=str(Path(data_dir) / "logs" / "byte-tools.out"))
                    except (KeyError, IndexError):
                        pass
            if spec.prereq is not None:
                erl = _main.find_erlang_home_erl()
                if erl:
                    env["PATH"] = str(Path(erl).parent) + os.pathsep + env.get("PATH", "")
                    env["ERLANG_HOME"] = str(Path(erl).parent.parent)
            try:
                # 45 秒：子代理实测 rabbitmqctl stop 1~4s 就返回，
                # 但它要先等 broker 把未落盘消息写完；给足余量，
                # 否则会误判成「停不掉」并弹强杀确认框（能优雅停就别强杀）。
                kw = dict(cwd=rec.home, env=env, timeout=45,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL)
                if _main.CURRENT_OS == "Windows":
                    kw["creationflags"] = _main.CREATE_NO_WINDOW
                subprocess.run(argv, **kw)
            except (OSError, subprocess.TimeoutExpired):
                pass
        elif spec.stop_kind == "port_lookup" or _main.CURRENT_OS == "Windows":
            # 端口是真相：整簇都空了就当已停（下面的等待循环会清登记），别吓用户。
            ports = tuple(rec.ports) or (rec.port,)
            if not any(self._is_listening(p) for p in ports):
                records = _main.load_running_map()
                records.pop(comp.key, None)
                _main.save_running_map(records)
                return _main.StopResult(True,
                                  reason=f"{comp.display_name} 已经不在监听 "
                                         f"{'/'.join(str(p) for p in ports)}，登记已清。"
                                         f"{self._leftover_note(spec)}")
            if spec.stop_kind != "port_lookup":
                # **登记的 PID 已经死了、端口却还在听**（2026-10-08 真机实测定位）：
                # java -jar 在 Windows 上由 java.exe 先起一个子 JVM（或启动器先退），
                # 于是 running.json 里那一行 pid 可能已经不存在，真正监听的是它的子进程。
                # 旧代码在这里直接回 need_force，而 force_stop 又只认"活着的登记 PID"
                # （`if self._process_alive(rec.pid)`）→ 两边都推给对方的死角：
                # 用户点停止 → 弹"要强制结束吗" → 点确定 → 回"我什么都没杀"，
                # 最后只能自己去任务管理器里杀 java.exe。
                # 现在在这里按端口反查唯一归属，把"该杀谁"查清楚再交给 force_stop。
                live = [p for p in (tuple(rec.ports) or (rec.port,)) if self._is_listening(p)]
                owner = ""
                owners = self._lookup_pids(tuple(live)) if live else {}
                mine = {p: pid for p, pid in owners.items() if pid != os.getpid()}
                # **判据用"登记 PID 是不是持有端口的那个"，而不是"登记 PID 还活着吗"**
                # （2026-10-08 实测教训）：PID 存活查询会误判 —— 一个早已退出的 PID
                # 在 Windows 上可能被 OpenProcess 判成"还在"（PID 被系统回收或
                # 句柄语义差异），于是"死者"被当成"凶手"，真正的监听进程毫发无伤。
                # 端口归属是我们**刚查出来的事实**，没有这种不确定性。
                if mine and len(set(mine.values())) == 1 and rec.pid not in set(mine.values()):
                    real_pid = next(iter(set(mine.values())))
                    owner = (f"登记的 PID {rec.pid} 已经不持有该端口，"
                             f"实际监听的是 PID {real_pid}（java 启动器先退出、子 JVM 在听）。")
                return _main.StopResult(False, need_force=True,
                                  reason=(f"{comp.display_name}（端口 {rec.port}）"
                                          f"{owner + ' ' if owner else ''}"
                                          f"在 Windows 上只能直接终止进程，"
                                          f"这会打断正在进行的任务、可能丢未落盘的配置。要强制结束吗？"))
            # port_lookup 没有优雅手段：厂商的关闭脚本按进程名强杀会误伤本机同名实例，
            # 而登记的 PID 是包装脚本不是服务进程。所以第一步只请示，一个进程都不碰。
            return _main.StopResult(False, need_force=True,
                              reason=(f"{comp.display_name}（端口 "
                                      f"{'/'.join(str(p) for p in ports)}）没有可用的优雅停止手段："
                                      f"它的启动脚本是包装器，登记的 PID 不是服务进程，"
                                      f"而厂商自带的关闭脚本按进程名强杀、会误伤本机其它同名实例。"
                                      f"要按端口找到那个进程并强制结束吗？"))
        else:
            self._terminate(rec)

        # 与 start() 同一套"有界轮次"约定（main.py 里 start 的注释钉过）：按轮计数、
        # 每轮 sleeper(1.0)、至少探一次。用 deadline 递减做墙钟会在 sleeper 被注入成
        # 短睡时把宽限期静默缩短，no-op 时退化成忙等。
        ports = tuple(rec.ports) or (rec.port,)
        for _ in range(max(1, int(deadline))):
            if not any(self._is_listening(p) for p in ports):
                records = _main.load_running_map()
                records.pop(comp.key, None)
                _main.save_running_map(records)
                return _main.StopResult(True, reason=f"{comp.display_name} 已停止，端口 "
                                               f"{'/'.join(str(p) for p in ports)} 已释放。"
                                               f"{self._leftover_note(spec)}")
            sleeper(1.0)
        return _main.StopResult(False, need_force=True,
                          reason=(f"{comp.display_name} 在 {int(deadline)} 秒内没停下来（端口 "
                                  f"{'/'.join(str(p) for p in ports)} 仍在听）。"
                                  f"要强制结束这个进程吗？强制结束可能丢未落盘的数据。"))

    # --- 服务模式（MySQL / Redis）----------------------------------------
    def _service_start(self, comp: _main.Component, version: Optional[str], password: str,
                       sleeper, log=None) -> _main.StartResult:
        """服务模式的启动：没注册就先注册（一次 UAC），然后交给 SCM 起。

        多版本必须用**下拉框选中的那个版本**，不能走 resolve_launch_version()：
        它挑的是"生效版本"，而服务要起的是用户眼睛正看着的那一个。
        """
        spec = _main.service_spec_for(comp)
        target = version or _main.resolve_launch_version(comp)
        if not target:
            return _main.StartResult(False, "gate",
                               f"磁盘上还没有 {comp.display_name} 的已安装版本，先点「安装」。")
        missing = _main.service_required_missing(comp, target)
        if missing:
            return _main.StartResult(
                False, "gate",
                f"{comp.display_name} {target} 缺少服务组件所需的文件：{'、'.join(missing)}。"
                f"这个包不是带服务组件的完整版，请卸载后重新安装。")
        peers = _main.peer_running_services(comp, exclude_version=target)
        if peers:
            names = "、".join(p.name for p in peers)
            return _main.StartResult(
                False, "gate",
                f"另一个版本的服务 {names} 正在运行。同一端口同一时间只能跑一个版本："
                f"先停止它，再启动 {target}。")
        port = _main.service_port(comp)
        secret_key = f"{comp.key}:{target}"
        stored = _main.load_service_secret(secret_key)
        notes: List[str] = []
        if password and any(ch in password for ch in "\r\n\x00"):
            return _main.StartResult(False, "gate", "密码里不能有换行或 NUL 字符")

        info = _main.service_info(comp, target)
        if not info.exists:
            if password and spec.password_kind == "redis_requirepass":
                # Redis 的密码必须落在服务启动前读的那份 conf 里
                _main.save_service_secret(secret_key, password)
            res = _main.install_service(comp, target, log=log)
            if not res.ok:
                return _main.StartResult(False, "gate" if res.cancelled else "service_install",
                                   res.message)
            notes.append(res.message)
            info = res.info or _main.SERVICE_BACKEND.query(_main.service_name_for(spec, target))

        if not info.running and _main.port_is_listening(port):
            owners = _main.netstat_listener_pids((port,))
            pid = owners.get(port)
            return _main.StartResult(
                False, "port",
                f"端口 {port} 已被别的进程占用" + (f"（PID {pid}）" if pid else "")
                + "。服务模式不替你结束别人的进程：请先停掉占用它的程序再重试。")

        # Redis 的密码必须落在**服务启动前**读到的那份 conf 里；已注册过的服务
        # 也要在这里补写，否则本次输入的密码下一次重启前都不会生效。
        if password and spec.password_kind == "redis_requirepass":
            _main.save_service_secret(secret_key, password)
            _main.write_redis_conf(comp, target, port, password)

        res = _main.start_service(comp, target, sleeper=sleeper, log=log)
        if not res.ok:
            return _main.StartResult(False, "gate" if res.cancelled else "service_start",
                               res.message, notes=notes)

        if password:
            if spec.password_kind == "mysql_root":
                ok, why = _main.mysql_set_root_password(comp, target, port, password, stored)
                if ok:
                    _main.save_service_secret(secret_key, password)
                    notes.append("root 密码已设置，并已用新密码连一次复核通过"
                                 "（只保存 DPAPI 加密副本）。")
                else:
                    notes.append(f"root 密码没设置成功：{why}。"
                                 f"root 仍是空密码或原密码，本次输入的密码**没有生效**。")
            elif spec.password_kind == "redis_requirepass":
                ok, why = _main.redis_verify_auth(comp, target, port, password)
                if ok:
                    notes.append("requirepass 已生效：带密码 PING 返回 PONG，"
                                 "无密码请求被 NOAUTH 拒绝。")
                else:
                    _main.drop_service_secret(secret_key)
                    notes.append(f"requirepass 没生效：{why}。"
                                 f"本次输入的密码**没有生效**，Redis 仍是无密码状态。")

        rec = _main.service_run_record(comp, target)
        records = _main.load_running_map()
        records[comp.key] = rec
        _main.save_running_map(records)
        if spec.password_kind == "mysql_root" and not password and not stored:
            # 没设过密码就别让用户猜：真连一次，把"能不能免密登录"讲清楚。
            ok_free, _ = _main.mysql_verify_login(comp, target, port, "")
            if ok_free:
                notes.append("root 当前**没有密码**，可以直接用 `mysql -u root` 登录；"
                             "要设置密码请先卸载这个版本再重装（重装时会弹密码框）。")
        if spec.password_kind == "redis_requirepass" and not password and not stored:
            ok_free, _ = _main.redis_verify_auth(comp, target, port, "")
            if ok_free:
                notes.append(f"Redis 当前**没有 requirepass**：`redis-cli -p {port} ping` 直接可用；"
                             f"要设置密码请先卸载这个版本再重装（重装时会弹密码框）。")
        return _main.StartResult(True, "running", record=rec,
                           console_url=rec.console_url, notes=notes)

    def _service_stop(self, comp: _main.Component, version: Optional[str], deadline: float,
                      sleeper, log=None) -> _main.StopResult:
        rec = _main.load_running_map().get(comp.key)
        target = version or (rec.version if rec is not None else "") or \
            _main.resolve_launch_version(comp)
        if not target:
            return _main.StopResult(False, reason="没有可识别的已安装版本，无法确定要停哪个服务。")
        if not _main.SERVICE_BACKEND.query(_main.service_name_for(_main.service_spec_for(comp), target)).exists \
                and not _main.SERVICE_BACKEND.registry_key_exists(
                    _main.service_name_for(_main.service_spec_for(comp), target)):
            # 迁移路径：服务还没注册过，但 running.json 里有一条**旧便携进程**登记。
            # 不接这一条，用户升级后就会卡在"卡片说在运行、点停止说服务不存在"。
            if rec is not None and rec.pid_role != "service":
                return self._portable_stop(comp, deadline, sleeper)
        res = _main.stop_service(comp, target, sleeper=sleeper, deadline=deadline, log=log)
        if res.ok:
            records = _main.load_running_map()
            if records.pop(comp.key, None) is not None:
                _main.save_running_map(records)
            return _main.StopResult(True, reason=res.message)
        if res.cancelled:
            return _main.StopResult(False, reason=res.message)
        return _main.StopResult(
            False,
            reason=(res.message + " 服务模式不会强杀进程：卡住时可以打开 services.msc，"
                                   "或执行 `sc.exe stop <服务名>` 再停一次。"))

    def _leftover_note(self, spec: Optional[_main.LaunchSpec]) -> str:
        """停止成功后附在 reason 里的残留辅助进程提示；没登记或没查到就是空串。"""
        names = tuple(getattr(spec, "leftover_processes", ()) or ())
        if not names:
            return ""
        return _main._leftover_process_note(self._process_images(names))

    def _console_readiness_note(self, spec: _main.LaunchSpec, port: int) -> str:
        """启动成功后探一次控制台，返回给用户的提示行（没问题时返回空串）。

        为什么值得多花一次 HTTP（2026-10-08 真机实测定位）：
        Jenkins 的 8080 一开始监听就回 `503 Please wait while Jenkins is getting
        ready to work` —— "已启动"是真的，但用户点控制台会看到一个等待页。
        与其让他怀疑没启动成功，不如在日志里点明"控制台还在初始化"。

        判据只用于**提示**，不参与"启动成功/失败"：服务进程确实在监听、
        登记也确实落盘了，那就是启动成功（把 5xx 当失败会让 Jenkins 启动永远判失败）。
        """
        if not spec.console_path:
            return ""
        url = f"http://127.0.0.1:{port}{spec.console_path}"
        try:
            r = _main.http_session().get(url, timeout=8, allow_redirects=True)
            code = r.status_code
        except Exception:
            return ""
        if code >= 500:
            return (f"已启动，但控制台 {url} 现在返回 {code}（服务还在初始化），"
                    f"稍等一会儿再点控制台；端口已经在正常服务。")
        return ""

    def force_stop(self, key: str, sleeper=time.sleep, rounds: int = 5) -> _main.StopResult:
        """用户明确同意后的强制结束。仍然只在"端口确实释放"时才清登记。"""
        spec = _main.LAUNCH_OF.get(key)
        if spec is not None and getattr(spec, "service", None) is not None:
            return _main.StopResult(
                False,
                reason=("服务模式不会强杀进程：强制结束会把服务留在"
                        "“停止中/崩溃”的半死状态，系统重启后仍可能残留。"
                        "请用 services.msc，或管理员执行 `sc.exe stop <服务名>`。"))
        rec = _main.load_running_map().get(key)
        if rec is None:
            return _main.StopResult(False, reason="没有登记记录")
        ports = tuple(rec.ports) or (rec.port,)
        # 记录"动手前就在听的口"。判失败时要说清是"我们杀完它还在听"还是
        # "本来就在听且我们没动手"——两者的归因完全不同，不能混成一句
        # "可能是别的进程占着"（真机2026-10-06实测就踩过这个坑，见下）。
        live_before = [p for p in ports if self._is_listening(p)]
        killed: List[int] = []
        if live_before:
            owners = self._lookup_pids(tuple(live_before))
            mine = {p: pid for p, pid in owners.items() if pid != os.getpid()}
            if rec.pid_role == "server":
                if self._process_alive(rec.pid):
                    try:
                        os.kill(rec.pid, 9)
                        killed.append(rec.pid)
                    except OSError:
                        pass
                if mine and not killed:
                    # 登记 PID 说"还活着"、但它**并不是**持有端口的那一个
                    # （java 启动器先退、子 JVM 在听；或 PID 被系统回收后判活有误）：
                    # 只杀登记 PID 的话端口永远不会释放，用户点停止永远停不掉。
                    # 归属唯一才动手（mine 的构造保证），且只杀端口真正的主人。
                    for pid in sorted(set(mine.values())):
                        try:
                            os.kill(pid, 9)
                            killed.append(pid)
                        except OSError:
                            pass
            elif mine:
                # 三重闸：① 有我们自己的登记（上面 rec is not None 已保证）
                #      ② 不是我们自己（pid != os.getpid()）
                #      ③ 用户已确认 —— 走到 force_stop 本身就是确认
                # 归属有歧义（同口多 PID）时 _pick_unique_pids 不给结果，宁可不杀。
                for pid in sorted(set(mine.values())):
                    try:
                        os.kill(pid, 9)
                        killed.append(pid)
                    except OSError:
                        pass
            else:
                # 端口反查没给出"唯一、且不是我们自己"的对象 → 一个都不许杀。
                # 这里必须当场把"为什么没动手"说清并返回：只往下走复查循环，
                # 用户拿到的就是"端口还在听，可能是别人占着"——把我们的不作为说成别人的错。
                return _main.StopResult(False, need_force=True,
                                  reason=(f"没有找到可以安全强制结束的进程：端口 "
                                          f"{'/'.join(str(p) for p in live_before)} 仍在听，"
                                          f"但端口反查没有给出唯一归属（或给出的就是我们自己）。"
                                          f"已放弃强制结束，登记保留，不动任何进程。"))
        # 终止调用返回 ≠ 监听 socket 已关闭。**必须先给进程一个退出窗口再开始复查**——
        # 真机 2026-10-06 实测：JVM 收到 TerminateProcess 后要几百毫秒到几秒才真正松开
        # 监听 socket。原来"杀完立刻进复查循环"，rounds=1 时循环体只跑一次就判"还在听"，
        # 于是一次成功的强杀被报成"可能是别的进程占着端口"——而端口其实随后就释放了，
        # 登记却被留了下来（用户看到的就是"停止按钮点了没用"）。
        # 与 start() 同一套"有界轮次"约定：每轮 sleeper(1.0) 后复查，最少探一次。
        for _ in range(max(1, int(rounds))):
            if not any(self._is_listening(p) for p in ports):
                records = _main.load_running_map()
                records.pop(key, None)
                _main.save_running_map(records)
                return _main.StopResult(True, reason="已强制结束并释放端口。"
                                               f"{self._leftover_note(_main.LAUNCH_OF.get(key))}")
            sleeper(1.0)
        left = [p for p in ports if self._is_listening(p)]
        # 归因要分清两种"还在听"：我们杀过 → 大概率是进程还没退出完；
        # 没杀过（kill 抛了 OSError 或 pid 本就不活）→ 才可能是别人占着。
        if killed and set(left) & set(live_before):
            return _main.StopResult(False, need_force=True,
                              reason=(f"已向进程 {'/'.join(str(p) for p in killed)} 发出强制结束，"
                                      f"但端口 {'/'.join(str(p) for p in left)} 在 "
                                      f"{max(1, int(rounds))} 秒内仍未释放。"
                                      f"该进程可能在做长耗时收尾；再点一次强制结束，"
                                      f"或先确认它是否还占着资源。"))
        return _main.StopResult(False, need_force=True,
                          reason=f"端口 {'/'.join(str(p) for p in left)} 仍在监听，"
                                 f"本次没有成功结束任何进程，可能是别的程序占着这个端口。")
