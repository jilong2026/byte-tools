"""一键启动护栏（离线）。设计文档见docs/superpowers/specs/2026-10-05-one-click-launch-design.md"""
import copy
import json
import os
import platform as _platform
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

_platform._wmi_query = lambda *_a, **_k: (_ for _ in ()).throw(OSError("stub: 不许走 WMI"))
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402  读下拉框的 DecorationRole（绿勾）要用
from PySide6.QtWidgets import QApplication  # noqa: E402  要构造 QThread 子类得有 QApplication


class LaunchSpecTable(unittest.TestCase):
    def setUp(self):
        self.comps = {c.key: c for c in main.build_components()}

    def test_launch_keys_are_exactly_this_batch(self):
        self.assertEqual(main.LAUNCH_KEYS, {"jenkins", "nacos", "activemq"},
                         "白名单只能按批次扩：多一个组件就要多一份实测事实与一份风险说明")
        self.assertEqual(main.LAUNCH_KEYS, set(main.LAUNCH_OF))

    def test_every_launch_key_is_a_known_category_component(self):
        for key in main.LAUNCH_KEYS:
            self.assertIn(key, self.comps, f"{key} 登记了启动描述符但组件不存在")

    def test_jenkins_spec_has_all_three_os_commands(self):
        spec = self.comps["jenkins"].launch
        self.assertIsNotNone(spec, "jenkins 必须有 launch")
        for os_name in ("Windows", "Linux", "Darwin"):
            argv = spec.commands.get(os_name)
            self.assertTrue(argv, f"{os_name} 的启动命令为空")
            self.assertIn("{java}", argv[0], "启动命令必须以 java 可执行打头")

    def test_components_outside_whitelist_have_no_launch(self):
        for key, comp in self.comps.items():
            if key not in main.LAUNCH_KEYS:
                self.assertIsNone(comp.launch, f"{key} 不该有启动描述符")

    def test_min_java_major_is_none_until_measured(self):
        """spec §2.4 第 5 项实测前禁止填数字，门控只能退化成"有没有 JDK"。"""
        self.assertIsNone(self.comps["jenkins"].launch.min_java_major)

    def test_plan_two_fields_default_to_plan_one_behaviour(self):
        """新字段必须带默认值且默认就是计划一 Jenkins 的既有行为，
        这样 Jenkins 的登记不用改一个字——本期不该动它。"""
        spec = main.LAUNCH_OF["jenkins"]
        self.assertEqual(spec.port_writeback, "cli_only")
        self.assertEqual(tuple(spec.extra_ports), ())
        self.assertEqual(spec.extra_env, {})

    def test_port_writeback_values_are_the_three_the_code_handles(self):
        # 拼错一个值就会在运行时走"未知策略"分支静默不改端口，所以取值域要在表层钉住。
        # 本期实际用到 cli_only / cli_flag / conf_copy 三个；shutdown_command 之类不属于本字段。
        allowed = {"cli_only", "cli_flag", "conf_copy"}
        self.assertTrue(set(main.PORT_WRITEBACKS) == allowed,
                        f"策略取值域漂移：{main.PORT_WRITEBACKS}")

    def test_stop_kind_values_are_declared(self):
        self.assertEqual(set(main.STOP_KINDS), {"pid", "shutdown_command", "port_lookup"})

    def test_port_lookup_is_not_a_pid_kill_route(self):
        """port_lookup 不是 pid：登记的 PID 是包装脚本，杀它服务照常在听。
        同时钉住"别给 LaunchSpec 加 pid_role 字段"—— 那个身份只能由 stop_kind
        在 start() 里推导，两处来源迟早会漂。"""
        spec = main.LaunchSpec(commands={"Windows": []}, stop_kind="port_lookup",
                               main_port=8161)
        self.assertEqual(spec.stop_kind, "port_lookup")
        self.assertNotIn("pid_role", spec.__dataclass_fields__,
                         "pid_role 只能由 stop_kind 推导，不许在描述符上再存一份")

    def test_nacos_registered_as_the_plan_two_shape(self):
        s = main.LAUNCH_OF["nacos"]
        self.assertEqual(s.main_port, 8848)
        self.assertEqual(tuple(s.port_offsets), (1000, 1001))
        self.assertEqual(tuple(s.extra_ports), (), "Nacos 的 gRPC 口是派生的，不是独立基准")
        self.assertEqual(s.port_writeback, "cli_flag")
        self.assertEqual(s.stop_kind, "port_lookup")
        self.assertEqual(s.needs, ("jdk",))
        self.assertEqual(s.min_java_major, 8)     # 证据：nacos-server.jar 内 Nacos.class class major 52
        self.assertEqual(s.startup_timeout, 90)
        self.assertTrue(s.risk_note, "默认无鉴权 + 账号 nacos/nacos 必须写在风险说明里")

    def test_nacos_command_carries_mode_and_port_as_separate_argv_items(self):
        """-m standalone 必须是独立的两段，--server.port 必须带选中端口：
        startup.cmd 用 `for %%a in (%*)` 按空格分词，拼成一个字符串就全碎。"""
        argv = main.LAUNCH_OF["nacos"].commands["Windows"]
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "standalone",
                         "默认是 cluster（-Xms2g 且要 cluster.conf），不强制 standalone 起不来")
        self.assertTrue(any(a.startswith("--server.port={port}") for a in argv),
                        "端口要靠命令行透传，这是 Nacos 不回写任何文件的依据")

    def test_nacos_registration_does_not_need_java_home_on_the_command_line(self):
        """startup.cmd 硬要 %JAVA_HOME%\\bin\\java.exe，所以 JAVA_HOME 必须是环境变量注入
        而不是把 java 路径拼进 argv —— 我们跑的是厂商脚本，脚本自己找 java。"""
        argv = main.LAUNCH_OF["nacos"].commands["Windows"]
        self.assertFalse(any("{java}" in a for a in argv))
        self.assertTrue(argv[0].endswith("startup.cmd") or argv[0].endswith("startup.sh"))

    def test_activemq_registered_with_two_independent_ports(self):
        s = main.LAUNCH_OF["activemq"]
        self.assertEqual(s.main_port, 8161)
        self.assertEqual(tuple(s.port_offsets), ())
        self.assertEqual(tuple(s.extra_ports), (61616,),
                         "61616 与 8161 没有固定偏移，必须走独立基准（spec 计划二 D6）")
        self.assertEqual(s.port_writeback, "conf_copy")
        self.assertEqual(s.stop_kind, "port_lookup")
        self.assertEqual(s.min_java_major, 17)   # 证据：bin/activemq.jar class major 61
        self.assertEqual(s.startup_timeout, 60)

    def test_activemq_env_points_at_the_copy_and_the_data_dir(self):
        """厂商机制实测：bin/activemq.bat 显式传 -Dactivemq.conf / -Dactivemq.data，
        且这俩变量"未设才回落到安装目录"——所以注入 env 就够，不必碰官方文件。"""
        env = main.LAUNCH_OF["activemq"].extra_env
        self.assertEqual(env.get("ACTIVEMQ_CONF"), "{conf_dir}")
        self.assertEqual(env.get("ACTIVEMQ_DATA"), "{data_dir}")

    def test_activemq_uses_the_bat_not_the_service_wrapper(self):
        """win64/activemq.bat 是 wrapper.exe -c wrapper.conf（服务包装器），
        与"不注册系统服务"冲突，不许出现在登记里。"""
        argv = main.LAUNCH_OF["activemq"].commands["Windows"]
        self.assertIn("bin/activemq.bat", argv[0])
        self.assertNotIn("win64", argv[0])
        # task 名必须是 start 而不是 console —— 真机实测（2026-10-05, 6.3.2）：
        # activemq.bat 把 %* 透传给 activemq.jar 的主类，它只认 backup/browse/create/
        # start/stop/… 这一组 task，**没有 console**；传 console 会打印 Usage 后自己退出，
        # 结果两个口都不监听、日志也是空的（连"厂商日志"都读不到）。
        # 这条断言原来写的是 "console"，是计划初稿没核实包内 task 表的猜测。
        self.assertEqual(argv[1], "start")
        for os_name in ("Linux", "Darwin"):
            with self.subTest(os_name):
                self.assertEqual(main.LAUNCH_OF["activemq"].commands[os_name][1], "start")

    def test_activemq_task_must_be_one_the_jar_actually_understands(self):
        """ActiveMQ 的 task 名不能凭印象写：activemq.bat 只是把 %* 转发给 activemq.jar
        的主类，不认识的 task 会打印一份 Usage 然后正常退出——**退出码是 0**，
        于是 start() 那边看到的是"拉起了进程但端口一直不监听"，日志还空空如也。

        真机踩过这个坑：初稿写 console，而 6.3.2 的 jar 根本没有 console task。
        这里把 jar 自报的 task 表钉下来（表来自真机 `activemq.bat start` 的 Usage 输出），
        换版本时若 task 表变了，这条会提醒重新核实而不是静默启动失败。"""
        # 6.3.2 activemq.jar 主类自报的任务（真机实测，Usage 原文摘录）
        known = {"backup", "browse", "bstat", "consumer", "create", "decrypt", "dstat",
                 "encrypt", "export", "list", "producer", "purge", "query", "start", "stop"}
        for os_name in ("Windows", "Linux", "Darwin"):
            with self.subTest(os_name):
                argv = main.LAUNCH_OF["activemq"].commands[os_name]
                self.assertEqual(len(argv), 2, "只应传task 一个参数，多余参数会被 jar 当数据")
                task = argv[1]
                self.assertIn(task, known,
                              f"{os_name}: activemq.jar 不认这个 task（会打 Usage 后静默退出）")
                self.assertNotEqual(task, "console", "console 不是 ActiveMQ 的 task")

    def test_data_note_is_required_for_plan_two_components(self):
        """计划一的"停止后数据保留"承诺对 Nacos 不成立（derby 在版本目录里）。
        不写 data_note 就等于在卸载确认里说假话。"""
        for key in ("nacos", "activemq"):
            self.assertTrue(main.LAUNCH_OF[key].data_note, f"{key} 必须说明数据去处")


class RunningMap(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig)

    def make(self, **kw):
        base = dict(key="jenkins", version="2.568.3", home="/h", data_dir="/d",
                    port=8080, console_url="http://127.0.0.1:8080/",
                    pid=1234, pid_role="server", started_at=1.0, launcher_cmd=["java"])
        base.update(kw)
        return main.RunRecord(**base)

    def test_missing_file_is_empty_table(self):
        self.assertEqual(main.load_running_map(), {})

    def test_broken_json_is_empty_table_and_is_not_fatal(self):
        main.RUNNING_FILE.write_text("{ not json", encoding="utf-8")
        self.assertEqual(main.load_running_map(), {})

    def test_round_trip(self):
        rec = {"jenkins": self.make()}
        main.save_running_map(rec)
        got = main.load_running_map()
        self.assertEqual(got["jenkins"].port, 8080)
        self.assertEqual(got["jenkins"].pid_role, "server")

    def test_save_is_atomic_leaving_no_tmp(self):
        main.save_running_map({"jenkins": self.make()})
        leftovers = list(Path(self.dir.name).glob("running.json.tmp*"))
        self.assertEqual(leftovers, [], "原子写没把临时文件收干净")

    def test_record_without_pid_role_is_rejected_not_guessed(self):
        """pid_role 必须显式写：拿它做判断是本设计的雷区，缺字段就当不可信记录丢掉。"""
        main.save_running_map({"jenkins": self.make()})
        data = json.loads(main.RUNNING_FILE.read_text(encoding="utf-8"))
        data["jenkins"].pop("pid_role")
        main.RUNNING_FILE.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(main.load_running_map(), {})

    def test_int_like_numeric_fields_are_coerced_at_load(self):
        """Task 2 复盘裁决：手改的 running.json 会把端口存成 "80480" 这类字符串，
        不归一就会让字符串流进后续每一次端口探测——状态判定整条失效。"""
        main.save_running_map({"jenkins": self.make(port=80480)})
        data = json.loads(main.RUNNING_FILE.read_text(encoding="utf-8"))
        data["jenkins"].update(port="80480", pid="4242", started_at="1.5")
        main.RUNNING_FILE.write_text(json.dumps(data), encoding="utf-8")
        got = main.load_running_map()
        self.assertEqual(got["jenkins"].port, 80480)
        self.assertIsInstance(got["jenkins"].port, int)
        self.assertIsInstance(got["jenkins"].pid, int)
        self.assertEqual(got["jenkins"].started_at, 1.5)

    def test_unconvertible_port_drops_record_like_bad_pid_role(self):
        """转不动的 port 与坏 pid_role 同一政策：整条按不可信记录丢弃。"""
        main.save_running_map({"jenkins": self.make()})
        data = json.loads(main.RUNNING_FILE.read_text(encoding="utf-8"))
        data["jenkins"]["port"] = "http"
        main.RUNNING_FILE.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(main.load_running_map(), {})

    def test_old_format_record_without_ports_field_still_loads(self):
        """计划一写下的 running.json 根本没有 ports 字段。
        若新字段没默认值，RunRecord(**item) 会 TypeError → 整条被丢弃 →
        用户重开工具时正在跑的 Jenkins 直接认不出来。这条用例就是拦这个的。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="2.568.3", home="/h", data_dir="/d", port=8080,
            console_url="http://127.0.0.1:8080/", pid=4321, pid_role="server",
            started_at=1.0, launcher_cmd=["java"], ports=())})
        raw = json.loads(main.RUNNING_FILE.read_text(encoding="utf-8"))
        raw["jenkins"].pop("ports")                      # 回到计划一的磁盘形状
        main.RUNNING_FILE.write_text(json.dumps(raw), encoding="utf-8")

        rec = main.load_running_map()["jenkins"]
        self.assertEqual(rec.ports, (8080,), "旧记录要从 port 归一，而不是被丢掉")

    def test_ports_round_trip_is_a_tuple_of_ints(self):
        """JSON 把 tuple 写成 list、把数字原样存；手改成字符串要能归一，改不动才丢。"""
        main.save_running_map({"nacos": main.RunRecord(
            key="nacos", version="2.3.2", home="/h", data_dir="/d", port=8848,
            console_url="http://127.0.0.1:8848/", pid=7, pid_role="launcher",
            started_at=1.0, launcher_cmd=["startup.cmd"], ports=(8848, 9848, 9849))})
        got = main.load_running_map()["nacos"]
        self.assertIsInstance(got.ports, tuple)
        self.assertEqual(got.ports, (8848, 9848, 9849))

    def test_scalar_ports_and_garbage_entries_are_not_fatal(self):
        # ports 被手改成标量 8848 时按单口理解；改成 "http" 这类转不动的才丢整条
        # （与既有坏 pid_role / port="http" 的政策一致）。
        main.save_running_map({"nacos": main.RunRecord(
            key="nacos", version="x", home="/h", data_dir="/d", port=8848,
            console_url="u", pid=7, pid_role="launcher", started_at=1.0,
            launcher_cmd=[], ports=(8848,))})
        raw = json.loads(main.RUNNING_FILE.read_text(encoding="utf-8"))
        raw["nacos"]["ports"] = 8848
        main.RUNNING_FILE.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(main.load_running_map()["nacos"].ports, (8848,))

        raw["nacos"]["ports"] = ["http"]
        main.RUNNING_FILE.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(main.load_running_map(), {}, "转不动的 ports 与坏 port 同一政策")


class PortCluster(unittest.TestCase):
    def probe(self, taken):
        """造一个假探针：只有不在 taken 里的口算空。"""
        return lambda port, host="127.0.0.1": port not in taken

    def test_default_when_everything_free(self):
        self.assertEqual(main.pick_free_cluster(8080, (), 99, self.probe(set())), 8080)

    def test_shifts_up_one_by_one_within_span(self):
        got = main.pick_free_cluster(8080, (), 99, self.probe({8080, 8081}))
        self.assertEqual(got, 8082, "应从主端口起升序找第一个空闲口，不是随机挑")

    def test_cluster_must_be_free_together(self):
        """派生端口（Nacos 的 gRPC offset 那类）任一被占，整簇都算不可用。"""
        # 主端口 8848-8853 全空，但每个候选的派生端口里都被占一个：
        # 整簇必须一起可用，所以一个都不能选出来。
        taken = set(range(9848, 9854))
        got = main.pick_free_cluster(8848, (0, 1000, 1001), 5, self.probe(taken))
        self.assertEqual(got, None, "整簇平移后仍撞车时不许硬选，返回 None 走失败语义")

    def test_cluster_finds_next_clean_base(self):
        # 8848 本身被占，且 9849-9857 把候选 8849..8857 的派生端口逐个堵死，
        # 第一个整簇干净的只能是 8858。
        taken = {8848, *range(9849, 9858)}
        got = main.pick_free_cluster(8848, (0, 1000, 1001), 10, self.probe(taken))
        self.assertEqual(got, 8858, f"应找到整簇都空的 8858，实际 {got}")

    def test_span_exhausted_returns_none(self):
        self.assertEqual(main.pick_free_cluster(8080, (), 3, lambda p, host="127.0.0.1": False), None)

    def test_offsets_include_base_itself(self):
        seen = []
        main.pick_free_cluster(9000, (1000,), 2, lambda p, host="127.0.0.1": (seen.append(p) or True))
        self.assertIn(9000, seen)
        self.assertIn(10000, seen)

    def test_port_is_free_asks_whether_we_can_bind_not_whether_we_can_connect(self):
        """端口空闲的判据必须是"能不能自己绑上"，不能是"能不能连上"。

        真机 2026-10-06 查出来的：原实现是 `connect_ex != 0`（能不能连上），
        那只能证明"没人接受连接"，证不了"没人占着这个口"。只绑在 `[::]:8848`
        （IPv6 通配）时，`connect_ex(("127.0.0.1", 8848))` 照样返回非 0 →
        判定"空闲" → 于是选了 8848 → 厂商脚本按 0.0.0.0 绑端口时撞上
        `Port 8848 was already in use`，用户看到的是"启动失败"。

        问"能不能绑"才与"我们要做的事"同构 —— 我们也是要 bind 这个口起服务。
        """
        # 找一个当前空闲的高位口
        port = 45999
        while not main.port_is_free(port) and port < 46050:
            port += 1
        self.assertTrue(main.port_is_free(port), f"{port} 应当是空闲的")

        # IPv4 监听占住 → 必须判占用
        v4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            v4.bind(("127.0.0.1", port))
            v4.listen(1)
            self.assertFalse(main.port_is_free(port), "IPv4 已在监听，却判成空闲")
        finally:
            v4.close()

        # IPv6 独占（不设双栈）占住 → 也必须判占用。
        # 这条是原实现漏掉的那一半：connect_ex 走 IPv4，连不上 IPv6 独占的口。
        v6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            v6.bind(("::1", port))
            v6.listen(1)
            self.assertFalse(main.port_is_free(port),
                             "IPv6 独占监听时IPv4 连不上，被误判成空闲")
        except OSError:
            self.skipTest("本机 IPv6 不可用，跳过")     # 禁了 IPv6 的机器
        finally:
            v6.close()


class HealthProbe(unittest.TestCase):
    def test_port_is_listening_sees_a_real_listener(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        self.addCleanup(srv.close)
        port = srv.getsockname()[1]
        self.assertTrue(main.port_is_listening(port, "127.0.0.1"))
        srv.close()
        self.assertFalse(main.port_is_listening(port, "127.0.0.1"),
                         "关掉监听后必须认成没在听，否则僵尸判定形同虚设")

    def test_http_ok_accepts_2xx_and_3xx_only(self):
        for code, want in ((200, True), (302, True), (401, True), (404, False), (500, False)):
            with self.subTest(code=code):
                fake = lambda url, timeout=2.0: code
                self.assertEqual(main._http_status_with(fake, "http://x"), want)

    def test_http_ok_is_false_on_any_error(self):
        def boom(url, timeout=2.0):
            raise OSError("connection refused")
        self.assertFalse(main._http_status_with(boom, "http://x"))

    def test_process_alive_rejects_non_positive_pid(self):
        self.assertFalse(main.process_is_alive(0))
        self.assertFalse(main.process_is_alive(-1))


class NoExecInvariant(unittest.TestCase):
    """spec §6：状态检测与找回过程一次都不许拉起进程。

    手法照 bt_startup_tests.py 的 PROBE_CHILD：把"起进程"的入口全部换成一调用就炸，
    然后跑完只读路径。这条用例是整套设计最需要长期守住的东西。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig)
        self._popen = main.subprocess.Popen
        self._probe = main._probe_version
        def _boom(*_a, **_k):
            raise AssertionError("状态检测路径里不得调用 Popen / _probe_version")
        main.subprocess.Popen = _boom
        main._probe_version = _boom
        self.addCleanup(setattr, main.subprocess, "Popen", self._popen)
        self.addCleanup(setattr, main, "_probe_version", self._probe)

    def test_status_and_adopt_never_spawn(self):
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda url, timeout=2.0: True,
                                  process_alive=lambda pid: True)
        comps = {c.key: c for c in main.build_components()}
        with tempfile.TemporaryDirectory() as td:
            rec = main.RunRecord(key="jenkins", version="2.568.3", home=td, data_dir=td,
                                 port=8080, console_url="http://127.0.0.1:8080/",
                                 pid=4242, pid_role="server", started_at=0.0,
                                 launcher_cmd=["java"])
            main.save_running_map({"jenkins": rec})
            self.assertEqual(mgr.status("jenkins", comps["jenkins"]).state, "running")
            self.assertEqual(list(mgr.adopt(comps))[0].state, "running")
            main.save_running_map({})
            self.assertEqual(mgr.status("jenkins", comps["jenkins"]).state, "not_installed_or_stopped")

    def nacos_comps(self):
        """本任务跑在 Task 8 登记 nacos 之前，build_components() 里没有 nacos，
        所以照 StopFlow 的办法用 jenkins 的组件本地造一个 key=nacos、launch=port_lookup 的描述符。"""
        comps = {c.key: c for c in main.build_components()}
        comp = comps["jenkins"]
        comp.key = "nacos"
        comp.launch = main.LaunchSpec(
            commands={os_name: ["{home}/bin/startup.cmd"]
                      for os_name in ("Windows", "Linux", "Darwin")},
            stop_kind="port_lookup", main_port=8848, port_offsets=(1000, 1001))
        comps["nacos"] = comp
        return comps

    def nacos_rec(self):
        """launcher 角色的三口簇登记，与 StopFlow 的同名夹具同形（不能跨类复用）。"""
        return main.RunRecord(key="nacos", version="2.3.2", home="/h", data_dir="/d",
                              port=8848, console_url="http://127.0.0.1:8848/",
                              pid=43210, pid_role="launcher", started_at=0.0,
                              launcher_cmd=["startup.cmd"], ports=(8848, 9848, 9849))

    def test_detection_paths_never_consult_the_port_owner_table(self):
        """端口反查是一次 netstat 调用。它出现在 status/adopt/reconcile 里，
        就等于从后门放掉"状态检测绝不执行进程"。"""
        calls = []
        orig = main.netstat_listener_pids
        main.netstat_listener_pids = lambda ports: calls.append(tuple(ports)) or {}
        self.addCleanup(setattr, main, "netstat_listener_pids", orig)
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False)
        comps = self.nacos_comps()
        main.save_running_map({"nacos": self.nacos_rec()})
        mgr.status("nacos", comps["nacos"])
        mgr.adopt(comps)
        mgr.reconcile(comps)
        self.assertEqual(calls, [], "检测路径调用了端口反查")

    def test_force_stop_actually_consults_it(self):
        """反向：force 路径确实会去查。否则上面那条"不许调用"可以靠删掉调用白赢。"""
        calls = []
        orig = main.netstat_listener_pids
        main.netstat_listener_pids = lambda ports: calls.append(tuple(ports)) or {}
        self.addCleanup(setattr, main, "netstat_listener_pids", orig)
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  process_alive=lambda pid: False)
        main.save_running_map({"nacos": self.nacos_rec()})
        mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1)
        self.assertEqual(len(calls), 1, "force_stop 没调用端口反查")
        self.assertEqual(set(calls[0]), {8848, 9848, 9849})


class ZombieMatrix(unittest.TestCase):
    """spec §5：PID 死 / PID 活端口不在 / 端口在听但 PID 不符 / 坏 JSON，
    四种情形都不许触发任何进程动作。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig)
        self.comps = {c.key: c for c in main.build_components()}
        self.rec = main.RunRecord(key="jenkins", version="2.568.3", home="/h",
                                  data_dir="/d", port=8080,
                                  console_url="http://127.0.0.1:8080/",
                                  pid=4242, pid_role="server", started_at=0.0,
                                  launcher_cmd=["java"])

    def mgr(self, listening, alive):
        return main.ServiceManager(is_listening=lambda p, host="127.0.0.1": listening,
                                   http_ok=lambda u, timeout=2.0: listening,
                                   process_alive=lambda pid: alive)

    def test_pid_dead_but_port_listening_is_still_running(self):
        """端口是真相。PID 判不出来（权限不足）时不该误报停止。"""
        main.save_running_map({"jenkins": self.rec})
        st = self.mgr(listening=True, alive=False).reconcile(self.comps)
        self.assertEqual(st["jenkins"].state, "running")
        self.assertEqual(main.load_running_map().get("jenkins").port, 8080)

    def test_pid_alive_but_port_free_is_zombie_and_record_dropped(self):
        main.save_running_map({"jenkins": self.rec})
        st = self.mgr(listening=False, alive=True).reconcile(self.comps)
        self.assertEqual(st["jenkins"].state, "not_installed_or_stopped")
        self.assertEqual(main.load_running_map(), {}, "僵尸登记必须清掉")

    def test_broken_json_yields_empty_and_touches_nothing(self):
        main.RUNNING_FILE.write_text("{", encoding="utf-8")
        calls = []
        mgr = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": calls.append(p) or True,
            http_ok=lambda u, timeout=2.0: True, process_alive=lambda pid: calls.append(pid) or True)
        self.assertEqual(mgr.reconcile(self.comps), {})
        self.assertEqual(calls, [], "空表不该去探任何端口")

    def test_foreign_key_record_survives_reconcile(self):
        """登记里出现本期不认识的可启动组件（计划三才会加的），不许被误删。

        样本用 rabbitmq 而不是 nacos：nacos 在计划二 Task 8 进了白名单，
        拿它当"不认识"的样本会让本用例在 Task 8 之后就变成"已登记组件要被接管"，
        那不是它要钉的东西。reconcile 只遍历 LAUNCH_KEYS，所以任何未登记 key 都一样。"""
        other = main.RunRecord(key="rabbitmq", version="3.12.0", home="/h", data_dir="/d",
                               port=5672, console_url="",
                               pid=1, pid_role="none", started_at=0.0, launcher_cmd=[])
        main.save_running_map({"rabbitmq": other})
        st = self.mgr(listening=True, alive=True).reconcile(self.comps)
        self.assertNotIn("rabbitmq", st, "没登记的组件不该被本工具接管")
        self.assertIn("rabbitmq", main.load_running_map())


class LaunchPlan(unittest.TestCase):
    def setUp(self):
        # build_launch_plan 会 ensure_dir(data_dir)，不patch CONFIG_DIR 就会在真
        # ~/.env-tools 下留下 jenkins-data 目录。
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig_dir = main.CONFIG_DIR
        main.CONFIG_DIR = Path(self.dir.name)
        self.addCleanup(setattr, main, "CONFIG_DIR", self._orig_dir)
        # 本任务的 build_launch_plan 不校验 JDK 目录是否存在，校验是 resolve_java_home
        # 的职责，已单独覆盖；这里只需一个稳定的 home 字符串。
        self.jdk_home = str(Path(self.dir.name) / "jdkhome")
        self.comps = {c.key: c for c in main.build_components()}
        self.comp = self.comps["jenkins"]
        self.spec = self.comp.launch

    def test_health_path_must_not_duplicate_the_console_path(self):
        """`health_path` 只有在"探活路径 ≠ 控制台路径"时才有值，否则必须是 None。

        这条原来是 `test_plan_two_health_paths_are_the_measured_ones`，断言
        `health_path` 必须等于实测的 console_path（"/nacos" / "/admin"），
        理由是 spec 那句「`health_path=None` 不是不测，是尚未实测」——
        **但我按字面执行反而造出了bug**：`console_url` 本身已经含 `console_path`
        （形如 `http://127.0.0.1:8848/nacos`），上层再拼一次 `health_path`
        就成了 `/nacos/nacos` → 稳定 404 → 真机演练连续两次误报"控制台不可达"，
        而厂商日志明明写着 `Nacos started successfully`。排查花掉的时间比 bug 本身多。

        真正的规则：`console_url` 是给用户点"打开控制台"用的完整地址，
        探活只要测它就行；只有当探活要打**另一个**路径（Jenkins 的 `/login`）时
        才需要 `health_path`。两者相同时填一遍就是给自己埋一个双拼的坑。
        """
        for key, path in (("nacos", "/nacos"), ("activemq", "/admin")):
            with self.subTest(key):
                s = main.LAUNCH_OF[key]
                self.assertEqual(s.console_path, path, f"{key} 的控制台路径是实测值")
                self.assertIsNone(s.health_path,
                                  f"{key}: health_path 与 console_path 相同就该留 None——"
                                  f"上层会把 console_url 与 health_path 拼起来，"
                                  f"填成 {path!r} 会变成 {path}{path} → 404")

    def test_health_path_is_used_when_it_differs_from_console_path(self):
        """反向：Jenkins 探活路径确实不同于控制台路径时，该填还得填，且拼接结果正确。"""
        s = main.LAUNCH_OF["jenkins"]
        self.assertEqual(s.console_path, "/")
        self.assertEqual(s.health_path, "/login",
                         "Jenkins 的探活打在 /login，与控制台根路径不同，必须填")
        plan = main.build_launch_plan(
            next(c for c in main.build_components() if c.key == "jenkins"),
            s, r"C:\jdk", 8080, Path("out.log"))
        base = plan.console_url.rstrip("/")
        self.assertEqual(base + s.health_path, "http://127.0.0.1:8080/login")

    def test_launch_uses_the_installed_version_not_the_first_candidate(self):
        """启动必须用**磁盘上真装着的**版本，不是候选清单首位。

        真机踩到的坑（2026-10-05）：build_components 的候选首位是 2.568.3，
        用户实际装的是 2.580.1，于是点启动去找一个不存在的目录，
        spawn 报 [WinError 267]，界面只显示"拉起失败"，用户完全无从下手。
        离线用例全绿是因为它们自己造 install_dir，看不出这个错配。

        这条钉住"生效版本 → 已安装最高版本"的优先级，
        以及"一个都没装时 launch_gate 要拦住并说清怎么装"。
        """
        with tempfile.TemporaryDirectory() as td:
            comp = self.comp
            # 造出"装了 2.580.1、但候选首位是 2.568.3"的错配现场
            home = Path(td) / "jenkins" / "jenkins-2.580.1"
            home.mkdir(parents=True)
            (home / "jenkins.war").write_bytes(b"x")
            orig_dir, main.CONFIG_DIR = main.CONFIG_DIR, Path(td)
            self.addCleanup(setattr, main, "CONFIG_DIR", orig_dir)
            orig_active = main.load_active_map
            main.load_active_map = lambda: {comp.key: "2.580.1"}
            self.addCleanup(setattr, main, "load_active_map", orig_active)

            self.assertEqual(main.resolve_launch_version(comp), "2.580.1",
                             "生效版本装了就要用它，哪怕候选首位是别的版本")
            plan = main.build_launch_plan(comp, self.spec, self.jdk_home, 8080,
                                          Path(td) / "out.log")
            self.assertIn("jenkins-2.580.1", " ".join(plan.argv),
                          "拉起命令指向了没装的版本目录")
            self.assertTrue(Path(plan.argv[2]).is_file(), "war 路径不存在，spawn 必失败")

            # 生效版本没装时退回"已安装里版本号最高的"，而不是候选首位
            main.load_active_map = lambda: {comp.key: "2.555.3"}
            home2 = Path(td) / "jenkins" / "jenkins-2.555.3"
            home2.mkdir(parents=True)
            (home2 / "jenkins.war").write_bytes(b"x")
            self.assertEqual(main.resolve_launch_version(comp), "2.555.3",
                             "生效版本没装就该退回实际装着的那个")

            # 一个都没装 → 必须拦住并说清怎么装，不能让人点了没反应
            empty = Path(td) / "empty"
            (empty / "jenkins").mkdir(parents=True)
            main.CONFIG_DIR = empty
            self.assertIsNone(main.resolve_launch_version(comp))
            ok, why = main.launch_gate(comp, self.spec, self.jdk_home)
            self.assertFalse(ok, "一个版本都没装却放过了门控")
            self.assertIn("下载并安装", why, "门控原因要给出可点的下一步")

    def test_java_home_prefers_our_own_installed_jdk(self):
        """EnvManager.get 只是 os.environ.get（main.py:3660），
        所以 JAVA_HOME 必须按"本工具装了哪个 JDK"来定，不能信进程环境。"""
        with tempfile.TemporaryDirectory() as td:
            # Component.install_dir() 的形状是 <CONFIG_DIR>/<key>/<key>-<version>（main.py:227）
            home = Path(td) / "jdk" / "jdk-21"
            (home / "bin").mkdir(parents=True)
            (home / "bin" / ("java.exe" if main.CURRENT_OS == "Windows" else "java")).write_bytes(b"x")
            orig_dir, orig_map = main.CONFIG_DIR, main.load_active_map
            self.addCleanup(setattr, main, "CONFIG_DIR", orig_dir)
            self.addCleanup(setattr, main, "load_active_map", orig_map)
            main.CONFIG_DIR = Path(td)
            main.load_active_map = lambda: {"jdk": "21"}
            self.assertEqual(main.resolve_java_home(self.comps), str(home))

    def test_java_home_falls_back_to_env_var_but_validates_it(self):
        """本工具没装 JDK 时退到用户的 JAVA_HOME，但必须确认它真是个 JDK 目录：
        指到一个不存在的路径就当没有，否则启动报错无从解释。"""
        orig_map = main.load_active_map
        orig_env = os.environ.get("JAVA_HOME")
        self.addCleanup(setattr, main, "load_active_map", orig_map)
        with tempfile.TemporaryDirectory() as td:
            real_home = Path(td) / "external-jdk"
            (real_home / "bin").mkdir(parents=True)
            main.load_active_map = lambda: {}
            os.environ["JAVA_HOME"] = str(real_home)
            self.assertEqual(main.resolve_java_home(self.comps), str(real_home))
            os.environ["JAVA_HOME"] = str(Path(td) / "does-not-exist")
            self.assertIsNone(main.resolve_java_home(self.comps))
        if orig_env is None:
            os.environ.pop("JAVA_HOME", None)
        else:
            os.environ["JAVA_HOME"] = orig_env

    def test_gate_reports_missing_jdk_as_actionable(self):
        ok, reason = main.launch_gate(self.comp, self.spec, java_home=None)
        self.assertFalse(ok)
        self.assertIn("JDK", reason)

    def test_argv_expands_all_placeholders(self):
        plan = main.build_launch_plan(self.comp, self.spec, self.jdk_home,
                                      8123, Path(self.dir.name) / "byte-tools.out")
        java_exe = Path(self.jdk_home) / "bin" / ("java.exe" if main.CURRENT_OS == "Windows" else "java")
        self.assertEqual(str(plan.argv[0]), str(java_exe),
                         "build_launch_plan 收的是 JDK home，java 可执行文件由它自己拼")
        self.assertEqual(plan.argv[1], "-jar")
        self.assertTrue(str(plan.argv[2]).endswith("jenkins.war"))
        self.assertIn("--httpPort=8123", plan.argv)
        self.assertNotIn("{", " ".join(str(a) for a in plan.argv), "占位符没展开干净")

    def test_env_injects_jenkins_home_and_java_home(self):
        plan = main.build_launch_plan(self.comp, self.spec, self.jdk_home,
                                      8080, Path(self.dir.name) / "byte-tools.out")
        self.assertEqual(plan.env["JENKINS_HOME"], str(Path(main.CONFIG_DIR) / "jenkins-data"))
        self.assertEqual(plan.env["JAVA_HOME"], self.jdk_home)
        self.assertTrue(Path(plan.env["JENKINS_HOME"]).is_dir(), "数据目录必须在这一步就建好")
        self.assertTrue(str(plan.cwd).endswith("jenkins-2.568.3"), "工作目录是组件安装目录")

    def test_console_url_uses_actual_port(self):
        plan = main.build_launch_plan(self.comp, self.spec, self.jdk_home, 8123,
                                      Path(self.dir.name) / "o.out")
        self.assertEqual(plan.console_url, "http://127.0.0.1:8123/")


class StartFlow(unittest.TestCase):
    """真进程一律打桩：拉起 Popen 的调用参数是本期最容易出错的地方。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig_file, self._orig_dir = main.RUNNING_FILE, main.CONFIG_DIR
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        main.CONFIG_DIR = Path(self.dir.name)
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig_file)
        self.addCleanup(setattr, main, "CONFIG_DIR", self._orig_dir)
        self.comps = {c.key: c for c in main.build_components()}
        self.comp = self.comps["jenkins"]
        # 造一个"已安装"的样子
        home = self.comp.install_dir(self.comp.versions[0].version)
        (home / "data").mkdir(parents=True, exist_ok=True)
        (home / "jenkins.war").write_bytes(b"x")
        self.spawned = []
        self.procs = []
        # 桩掉 JDK 解析：用例成败不许取决于这台机器恰好有没有 JAVA_HOME 或已装 JDK
        self._orig_jdk = main.resolve_java_home
        main.resolve_java_home = lambda comps: str(Path(self.dir.name) / "jdk" / "jdk-17")
        self.addCleanup(setattr, main, "resolve_java_home", self._orig_jdk)

        class FakePopen:
            def __init__(self, argv, **kw):
                pass
        self._popen = main.subprocess.Popen

        def fake_popen(argv, **kw):
            self.spawned.append((list(argv), kw))
            class P:
                pid = 43210
                returncode = None
                terminated = False
                def poll(self):
                    return None
                def terminate(self):
                    self.terminated = True
            proc = P()
            self.procs.append(proc)
            return proc
        main.subprocess.Popen = fake_popen
        self.addCleanup(setattr, main.subprocess, "Popen", self._popen)
        # 端口探测一律打桩成"全空闲"，并在需要时单独覆盖。
        # 2026-10-06：端口策略改成"不平移、被占就杀占用者"之后，choose_ports
        # 会真的去 bind/杀进程 —— 不打桩的话，用例成败就取决于这台机器 8080 上有没有
        # 东西在跑（我这儿常年跑着 Jenkins，于是 happy_path 全红）。
        # 离线用例的成败必须只由桩决定。
        self._orig_free = main.port_is_free
        main.port_is_free = lambda port, host="127.0.0.1": True
        self.addCleanup(setattr, main, "port_is_free", self._orig_free)
        # 结束占用者同样要桩掉：真去 os.kill 会连累别的进程。
        self._orig_evict = main.evict_port_occupant
        main.evict_port_occupant = lambda port, label, evicted=None: None
        self.addCleanup(setattr, main, "evict_port_occupant", self._orig_evict)
        # _occupied_reason 会调 occupant_of→netstat 去问"是谁占着"。
        # 离线用例不许真跑外部命令（既慢、结果又依赖这台机器当时在跑什么）。
        self._orig_netstat = main._netstat_text
        main._netstat_text = lambda: ""
        self.addCleanup(setattr, main, "_netstat_text", self._orig_netstat)

    def mgr(self, listening_after=1):
        """第 listening_after 次探活开始说"在听了"，模拟服务起来要几秒。"""
        box = {"n": 0}
        def is_listening(port, host="127.0.0.1"):
            box["n"] += 1
            return box["n"] > listening_after
        return main.ServiceManager(is_listening=is_listening,
                                   http_ok=lambda u, timeout=2.0: True,
                                   process_alive=lambda pid: True)

    def test_gate_blocks_without_jdk(self):
        orig = main.resolve_java_home
        main.resolve_java_home = lambda comps: None
        self.addCleanup(setattr, main, "resolve_java_home", orig)
        res = self.mgr().start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("JDK", res.reason)
        self.assertEqual(self.spawned, [], "门控没过就不该拉起任何进程")

    def test_happy_path_writes_record_and_detaches(self):
        res = self.mgr(listening_after=1).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        argv, kw = self.spawned[0]
        rec = main.load_running_map()["jenkins"]
        self.assertIn(f"--httpPort={rec.port}", argv, "端口必须真的传进命令行")
        self.assertTrue(rec.console_url.endswith(f":{rec.port}/"))
        self.assertTrue(kw.get("start_new_session") or kw.get("creationflags"),
                        "必须按脱离进程拉起（DETACHED_PROCESS / start_new_session）")
        self.assertIn("stdout", kw)
        self.assertEqual(rec.pid, 43210)
        self.assertEqual(rec.pid_role, "server", "Jenkins 我们就是服务进程（spec §4）")

    def test_times_out_without_listening_and_leaves_no_record(self):
        res = self.mgr(listening_after=10 ** 6).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("未监听", res.reason)
        self.assertTrue(self.procs[0].terminated)
        self.assertEqual(main.load_running_map(), {}, "启动失败不许留登记")

    def test_second_start_is_refused_while_running(self):
        self.mgr(listening_after=1).start(self.comp, self.comps, sleeper=lambda s: None)
        res = self.mgr(listening_after=0).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("已在运行", res.reason)
        self.assertEqual(len(self.spawned), 1, "重复启动必须被拒")

    def test_taken_port_is_evicted_never_shifted(self):
        """端口被占时**结束占用者并原地启动**，绝不平移到 8081。

        这条原来是 `test_frees_port_by_shifting_cluster_when_8080_taken`
        （断言"平移到 8081"）。2026-10-06 起契约反转为"不平移"，
        理由：Nacos 的 gRPC 口由 `server.port + 1000` 派生、各类客户端配置里
        写死 8848，ActiveMQ 的 61616 被大量中间件硬编码 —— 平移会造成
        "服务起来了但外部客户端一个都连不上"，比起不来更难归因。

        桩要连"结束之后端口已释放"一起模拟：真实实现杀掉占用者后会轮询复查，
        端口若一直报占用，复查必然失败 —— 那正是"结束不掉"分支，不是这里要测的。
        """
        box = {"killed": False}

        def free_after_kill(port, host="127.0.0.1"):
            if port == 8080 and not box["killed"]:
                return False
            return True

        def fake_evict(port, label, ev=None):
            box["killed"] = True
            if ev is not None:
                ev.append(f"{port} ← fake.exe（PID 999）已结束")
            return None

        main.port_is_free = free_after_kill
        main.evict_port_occupant = fake_evict
        res = self.mgr(listening_after=1).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(main.load_running_map()["jenkins"].port, 8080,
                         "端口被占不许平移，必须还是官方默认端口")
        self.assertTrue(any("已结束" in n for n in res.notes),
                        f"结束了占用者却没告诉用户：notes={res.notes}")

    def test_occupied_port_names_the_culprit_when_eviction_fails(self):
        """结束占用者失败时，报错必须指名是哪个口、被谁占着。

        只说"端口被占用"等于把排查成本推给用户——他还得自己去翻任务管理器。
        """
        main.port_is_free = lambda port, host="127.0.0.1": port != 8080
        main.evict_port_occupant = lambda port, label, ev=None: (
            f"端口 {port}（{label}）被 foo.exe（PID 4242）占用，结束它失败：拒绝访问")
        res = self.mgr(listening_after=1).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertEqual(res.state, "port")
        self.assertIn("4242", res.reason, "报错要点名占用者的 PID")
        self.assertIn("foo.exe", res.reason, "报错要点名占用者的程序名")
        self.assertEqual(self.spawned, [], "没拿到端口就不许拉起进程")
        self.assertEqual(main.load_running_map(), {}, "启动失败不许留登记")

    def test_occupied_port_names_the_process_that_refused_to_die(self):
        """结束占用者成功、但端口复查仍不释放（进程赖着不走）→ 也要指名道姓。

        这条覆盖"结束掉了却没释放"这条路径：它必须跟"结束失败"一样把占用者
        的程序名与PID 说清，不能只说"端口被占用"。
        """
        main.port_is_free = lambda port, host="127.0.0.1": port != 8080
        box = {"evicted": False}

        def stubborn(port, label, ev=None):
            box["evicted"] = True
            if ev is not None:
                ev.append(f"{port} ← stubborn.exe（PID 777）已结束")
            return None                     # 报告"结束成功"，但端口复查仍不释放

        main.evict_port_occupant = stubborn
        res = self.mgr(listening_after=1).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertEqual(res.state, "port")
        self.assertIn("8080", res.reason)
        self.assertEqual(self.spawned, [], "没拿到端口就不许拉起进程")

    def test_occupied_port_never_shifts_even_when_nothing_can_be_evicted(self):
        """evict=False 时（不杀）也必须原地失败，不许退回平移。"""
        main.port_is_free = lambda port, host="127.0.0.1": port != 8080
        orig = main.evict_port_occupant
        plan, why = main.choose_ports(self.comp.launch, is_free=main.port_is_free,
                                      evict=False)
        self.assertEqual(plan.all_ports, (), "拿不到端口就不该给出计划")
        self.assertIn("8080", why, "失败原因要指名是哪个口")
        self.assertIs(plan.main, 0)
        del orig

    def test_start_carries_the_conf_copy_notice_to_the_card(self):
        """副本建立/差异文件这两句必须跟着 StartResult 回到卡片，由卡片写进组件日志。
        吞掉的话，用户之后想找"端口改在哪份文件里"就只能自己猜——R4 第 6 条禁止的写法。"""
        orig = main.prepare_ports
        main.prepare_ports = lambda *a, **k: (True, "", ["已在 data 目录建立配置副本"])
        self.addCleanup(setattr, main, "prepare_ports", orig)
        mgr = self.mgr(listening_after=1)     # StartFlow 既有工厂：第 1 次探活后"在听"
        res = mgr.start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(res.notes, ["已在 data 目录建立配置副本"],
                         "start() 没把 prepare_ports 的告警行带出来")

    def test_start_probes_the_whole_port_cluster_not_just_the_main_port(self):
        """派生口（Nacos gRPC 9848/9849）没在听时必须判超时，不能登记成"运行中"。

        Jenkins 没有派生口，所以这条用一个临时挂上 port_offsets 的 spec 走同一条 start()：
        探针只对主口说"在听"、对派生口说"没在听"。写成只探主口的话这条会绿，
        而Nacos 会起来一个"控制台能开、客户端连不上"的半死进程（spec §7）。"""
        spec = copy.copy(self.comp.launch)
        spec.port_offsets = (1000, 1001)
        orig_launch, self.comp.launch = self.comp.launch, spec
        self.addCleanup(setattr, self.comp, "launch", orig_launch)
        # 主口 8080 之外的所有口都答"没在听"：主口在听、两个派生口不在
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": p == 8080,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True)
        res = mgr.start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok, "派生口没监听却判成功 = 登记了一个半死的运行中")
        self.assertEqual(res.state, "timeout")
        self.assertEqual(main.load_running_map(), {}, "启动失败不许留登记")


class StopFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig)
        # 钉住 OS：不钉的话同一批用例会因宿主是 Windows 还是 Linux 走两条不同分支，
        # 结果取决于跑测试的机器（和 Task 7 的 JAVA_HOME 问题同类）。
        self._orig_os = main.CURRENT_OS
        main.CURRENT_OS = "Linux"
        self.addCleanup(setattr, main, "CURRENT_OS", self._orig_os)
        self.comps = {c.key: c for c in main.build_components()}
        self.comp = self.comps["jenkins"]
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="2.568.3", home="/h", data_dir="/d", port=8080,
            console_url="http://127.0.0.1:8080/", pid=43210, pid_role="server",
            started_at=0.0, launcher_cmd=["java"])})
        # key 仍用 jenkins、spec 本地造 —— Task 8 才把 nacos 登记进 build_components，
        # 这里引用它就等于让用例跑在未来任务的代码上。
        self.lookup_spec = main.LaunchSpec(
            commands={os_name: ["{home}/bin/startup.cmd"]
                      for os_name in ("Windows", "Linux", "Darwin")},
            stop_kind="port_lookup", main_port=8848, port_offsets=(1000, 1001))
        self.lookup_comp = next(c for c in main.build_components() if c.key == "jenkins")
        self.lookup_comp.key = "nacos"      # 只用于本地夹具：登记 key 与 spec 对齐
        self.lookup_comp.launch = self.lookup_spec
        self.comps["nacos"] = self.lookup_comp
        self.comp_nacos = self.lookup_comp

    def nacos_rec(self, ports=(8848, 9848, 9849)):
        """launcher 角色的三口簇登记：登记的 PID 是包装脚本，不是服务进程。"""
        return main.RunRecord(key="nacos", version="2.3.2", home="/h", data_dir="/d",
                              port=ports[0], console_url="http://127.0.0.1:8848/",
                              pid=43210, pid_role="launcher", started_at=0.0,
                              launcher_cmd=["startup.cmd"], ports=ports)

    def rec(self, ports=()):
        return main.RunRecord(key="jenkins", version="x", home="/h", data_dir="/d",
                              port=8080, console_url="http://127.0.0.1:8080/", pid=1,
                              pid_role="server", started_at=0.0, launcher_cmd=[],
                              ports=ports)

    def test_jenkins_stop_uses_pid_terminate_and_drops_record(self):
        killed = []
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda rec: killed.append(rec.pid))
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(killed, [43210])
        self.assertEqual(main.load_running_map(), {})

    def test_stuck_process_asks_forced_and_keeps_record(self):
        """超时不许自动强杀：必须返回 need_force，由界面问人（spec §5）。"""
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True,
                                  terminate=lambda rec: None)
        res = mgr.stop(self.comp, self.comps, deadline=0.0, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertTrue(res.need_force)
        self.assertIn("强制", res.reason)
        self.assertIn("jenkins", main.load_running_map(), "没停成就保留登记，别把进程变孤儿")

    def test_force_stop_clears_record_when_port_releases(self):
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda rec: None)
        self.assertTrue(mgr.force_stop("jenkins").ok)
        self.assertEqual(main.load_running_map(), {})

    def test_force_stop_rechecks_before_blaming_other_process(self):
        """终止调用返回 ≠ 监听 socket 已关闭：复查窗口里端口才释放要判成功并清登记，
        rounds 耗尽仍在听才归因"别的进程占着"并保留登记（评审 Important #3）。"""
        rec = main.load_running_map()["jenkins"]
        seq = [True, True, False]

        def releases_late(port, host="127.0.0.1"):
            return seq.pop(0) if seq else False

        mgr = main.ServiceManager(is_listening=releases_late,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda r: None)
        res = mgr.force_stop("jenkins", sleeper=lambda s: None, rounds=3)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(main.load_running_map(), {}, "复查窗口里端口释放就该判成功并清登记")

        # 全程仍监听：杀完探一次会把"我们刚杀的"误报成别人占着；有界复查耗尽后才归因，且不清登记
        main.save_running_map({"jenkins": rec})
        mgr2 = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                   http_ok=lambda u, timeout=2.0: False,
                                   process_alive=lambda pid: False,
                                   terminate=lambda r: None)
        res2 = mgr2.force_stop("jenkins", sleeper=lambda s: None, rounds=3)
        self.assertFalse(res2.ok)
        # 这个夹具 process_alive 恒假 → 一个进程都没杀成 → 归因是"可能是别人占着"。
        # （真实场景里杀成了却还在听走的是另一条分支，见
        #test_force_stop_blames_its_own_kill_when_the_port_does_not_release）
        self.assertIn("别的程序占着", res2.reason)
        self.assertIn("jenkins", main.load_running_map(), "rounds 耗尽仍监听时不许清登记")

    def test_force_stop_blames_its_own_kill_when_the_port_does_not_release(self):
        """杀成了但端口没在复查窗口内释放 → 归因必须说"我们已经动过手了"。

        真机2026-10-06 查出来的缺陷：原来 force_stop 杀完**立刻**进复查循环，
        rounds 小时循环体只跑一次就判"还在听"，把一次成功的强杀报成
        "可能是别的进程占着"——而端口随后就释放了。于是用户看到的是
        "停止按钮点了没用、进程也没了、登记还留着"。

        这条钉住两件事：
        ①杀过 → 归因里必须出现被杀的 PID，不能说成"别的进程占着"；
        ② 复查必须在"杀"之后留出窗口 —— 由 test_force_stop_waits_for_the_port_after_killing
           单独钉住时序。
        """
        rec = self.rec(ports=(8080,))
        main.save_running_map({"jenkins": rec})
        killed = []
        orig_kill = main.os.kill
        main.os.kill = lambda pid, sig: killed.append(pid)
        self.addCleanup(setattr, main.os, "kill", orig_kill)
        # 进程"活着"所以我们确实动手了，但端口永远不释放
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: True,
                                  terminate=lambda r: None)
        res = mgr.force_stop("jenkins", sleeper=lambda s: None, rounds=2)
        self.assertFalse(res.ok)
        self.assertEqual(killed, [rec.pid], "进程活着就该按登记 PID 强杀")
        self.assertIn(str(rec.pid), res.reason,
                      "归因里必须点名我们杀过的 PID，不能推给'别的进程'")
        self.assertNotIn("别的程序占着", res.reason,
                         "我们确实动过手，不该说成是别人的锅")
        self.assertIn("jenkins", main.load_running_map(), "端口没释放就不许清登记")

    def test_force_stop_waits_for_the_port_after_killing(self):
        """杀完必须给进程一个退出窗口：JVM 收到信号后要几百毫秒才松开监听 socket。

        这条用"先杀、隔一轮才松口"的探针把时序钉死：杀之前的那一次探活必然是"在听"，
        所以只要实现是"杀完立刻探一次"，rounds=2 也必然判失败。
        """
        rec = self.rec(ports=(8080,))
        main.save_running_map({"jenkins": rec})
        box = {"n": 0}

        def releases_after_kill(port, host="127.0.0.1"):
            box["n"] += 1
            return box["n"] <= 2          # 杀之后前两次探活都还在听，第三次才释放

        orig_kill = main.os.kill
        main.os.kill = lambda pid, sig: None
        self.addCleanup(setattr, main.os, "kill", orig_kill)
        mgr = main.ServiceManager(is_listening=releases_after_kill,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: True,
                                  terminate=lambda r: None)
        res = mgr.force_stop("jenkins", sleeper=lambda s: None, rounds=5)
        self.assertTrue(res.ok, f"端口在复查窗口内释放了却判失败：{res.reason}")
        self.assertNotIn("jenkins", main.load_running_map(),
                         "端口释放了就要清登记")

    def test_stop_without_record_is_harmless(self):
        main.save_running_map({})
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False, terminate=lambda rec: None)
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("没有本工具的启动登记", res.reason)

    def test_stop_defaults_to_killing_the_registered_server_pid(self):
        """不注入 terminate 时，stop() 必须真的落到 _terminate_by_pid —— 那是生产默认路径。"""
        killed = []
        orig = main.os.kill
        main.os.kill = lambda pid, sig: killed.append((pid, sig))
        self.addCleanup(setattr, main.os, "kill", orig)
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(killed, [(43210, 15)])

    def test_windows_pid_stop_asks_before_killing(self):
        """Windows 路线专用：os.kill 的任何信号值在 Windows 上都是 TerminateProcess，
        也就是"强杀"本身。spec §5 要求超时只询问、不自动强杀，所以停止的第一步不许动手。"""
        main.CURRENT_OS = "Windows"
        killed = []
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True,
                                  terminate=lambda rec: killed.append(rec.pid))
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertTrue(res.need_force)
        self.assertEqual(killed, [], "Windows 上停止第一步不许杀进程")
        self.assertIn("jenkins", main.load_running_map())

    def test_windows_stop_cleans_stale_record_without_scaring(self):
        """登记还在、端口其实早空了（进程自己死掉过）：Windows 路线要按"已经停了"处理，
        不许回一句"这会打断正在进行的任务，要强制结束吗" —— 端口才是真相（spec §4）。"""
        main.CURRENT_OS = "Windows"
        killed = []
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda rec: killed.append(rec.pid))
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(killed, [], "没在监听就不该走到强杀")
        self.assertEqual(main.load_running_map(), {})

    def test_running_requires_the_whole_cluster_to_be_listening(self):
        """Nacos 主口在听、9848 掉了，是"半死"，不是运行中：按单口判会显示运行中，
        而客户端连不上；下一个任务把它判成僵尸又会清掉登记，两个没人认领的监听口留下。"""
        rec = self.rec(ports=(8848, 9848, 9849))
        st = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": p != 9848).status("nacos", self.comp, {
                "nacos": rec})
        self.assertEqual(st.state, "zombie")
        self.assertIn("9848", st.reason)

    def test_zombie_detection_copes_with_records_lacking_ports(self):
        # 计划一写的记录没有 ports；按 port 兜底，不许 TypeError冒出来
        # （加载侧归一化只覆盖"从磁盘读"，进程内刚构造出来的记录也得能判）
        st = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True).status(
            "jenkins", self.comp, {"jenkins": self.rec(ports=())})
        self.assertEqual(st.state, "running")

    def test_force_stop_kills_the_port_owner_found_by_lookup(self):
        """登记的 PID 是 cmd.exe（launcher），杀它 java 还活着。所以动手对象是
        "端口反查出来的那个 PID"，不是登记里那个。打桩 os.kill —— 真杀进程违反离线约束。"""
        main.save_running_map({"nacos": self.nacos_rec()})
        killed = []
        orig_kill = main.os.kill
        main.os.kill = lambda pid, sig: killed.append((pid, sig))
        self.addCleanup(setattr, main.os, "kill", orig_kill)
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  process_alive=lambda pid: True,
                                  terminate=lambda rec: killed.append(("rec", rec.pid)),
                                  lookup_pids=lambda ports: {8848: 55555})
        res = mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1)
        self.assertFalse(res.ok, "端口还在听就不许算停成功")
        self.assertIn((55555, 9), killed, "该杀的是端口反查出来的 PID")
        self.assertNotIn(("rec", 43210), killed,
                         "不许退回杀登记里那个 launcher PID")

    def test_port_lookup_role_asks_before_any_kill(self):
        """launcher 角色的停止没有优雅手段：第一步只请示，一个进程都不许碰。"""
        main.save_running_map({"nacos": self.nacos_rec()})
        killed, looked = [], []
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  process_alive=lambda pid: True,
                                  terminate=lambda rec: killed.append(rec.pid),
                                  lookup_pids=lambda ports: looked.append(tuple(ports)) or {})
        res = mgr.stop(self.comp_nacos, self.comps, deadline=1.0, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertTrue(res.need_force)
        self.assertEqual(killed, [], "launcher 角色不许走 PID 终止")
        self.assertEqual(looked, [], "请示阶段连端口反查都不该跑，还没得到用户的确认")
        self.assertIn("强制", res.reason)

    def test_force_stop_refuses_ambiguous_and_self_targets(self):
        main.save_running_map({"nacos": self.nacos_rec()})
        # 必须打桩 os.kill：这条用例的正中间就是"别杀我们自己"。
        # 不打桩的话，一旦自我保护闸写坏，os.kill(os.getpid(), 9) 会把测试进程自己带走，
        # 症状是 exit=9 的静默消失而不是一条断言失败 —— 比红更难查。
        killed = []
        orig_kill = main.os.kill
        main.os.kill = lambda pid, sig: killed.append((pid, sig))
        self.addCleanup(setattr, main.os, "kill", orig_kill)
        # 同口两个 PID（端口复用/容器网络栈都可能）→ 宁可不认，认了就可能杀错
        for table, why in (({}, "空表"), ({8848: os.getpid()}, "是我们自己")):
            with self.subTest(why):
                main.save_running_map({"nacos": self.nacos_rec()})
                del killed[:]
                mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                          process_alive=lambda pid: True,
                                          lookup_pids=lambda ports, t=table: dict(t))
                res = mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1)
                self.assertFalse(res.ok)
                self.assertIn("强制", res.reason)
                self.assertEqual(killed, [], f"{why}：一个进程都不许动")
                self.assertIn("nacos", main.load_running_map(), "停不掉就不许清登记")

    def test_force_stop_releases_only_after_the_whole_cluster_goes_quiet(self):
        """复查必须按簇：主口掉了、gRPC 还在听，不能算"已停止"并清登记。"""
        main.save_running_map({"nacos": self.nacos_rec()})
        listening = {8848: False, 9848: True, 9849: False}
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": listening.get(p, False),
                                  process_alive=lambda pid: False,
                                  lookup_pids=lambda ports: {})
        res = mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1)
        self.assertFalse(res.ok)
        self.assertIn("9848", res.reason)
        self.assertIn("nacos", main.load_running_map())
        listening[9848] = False
        self.assertTrue(mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1).ok)
        self.assertEqual(main.load_running_map(), {})


class TerminateByPidGuard(unittest.TestCase):
    """默认收尸器：只杀我们登记为 server 的 PID，别的一律不动。"""

    def setUp(self):
        self.kills = []
        self._kill = main.os.kill
        self.addCleanup(setattr, main.os, "kill", self._kill)
        main.os.kill = lambda pid, sig: self.kills.append((pid, sig))

    def rec(self, role, pid=43210):
        return main.RunRecord(key="jenkins", version="2.568.3", home="/h", data_dir="/d",
                              port=8080, console_url="http://127.0.0.1:8080/",
                              pid=pid, pid_role=role, started_at=0.0, launcher_cmd=["java"])

    def test_server_pid_gets_sigterm(self):
        main.ServiceManager._terminate_by_pid(self.rec("server"))
        self.assertEqual(self.kills, [(43210, 15)])

    def test_launcher_pid_is_never_killed(self):
        main.ServiceManager._terminate_by_pid(self.rec("launcher"))
        self.assertEqual(self.kills, [], "PID 不可信时不许动手（spec §2）")

    def test_zero_pid_is_never_killed(self):
        main.ServiceManager._terminate_by_pid(self.rec("server", pid=0))
        self.assertEqual(self.kills, [])

    def test_negative_pid_is_never_killed(self):
        """os.kill(-1, …) 在 POSIX 上是"发给所有进程"，登记被手改成负数时绝不能往下传。"""
        main.ServiceManager._terminate_by_pid(self.rec("server", pid=-1))
        main.ServiceManager._terminate_by_pid(self.rec("server", pid=None))
        self.assertEqual(self.kills, [])


class LaunchWorkerSignals(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_start_action_emits_started_ok(self):
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        comps = {c.key: c for c in [comp]}
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True)
        rec = main.RunRecord(key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
                             console_url="http://127.0.0.1:8080/", pid=1,
                             pid_role="server", started_at=0.0, launcher_cmd=[])
        mgr.start = lambda c, cs, sleeper=time.sleep: main.StartResult(
            True, "running", record=rec, console_url=rec.console_url)
        w = main.LaunchWorker("start", comp, comps, mgr)
        got = []
        w.started_ok.connect(lambda k, u: got.append((k, u)))
        w._dispatch()      # 不起线程，直接跑分派逻辑：线程本身不是本用例要验的东西
        self.assertEqual(got, [("jenkins", "http://127.0.0.1:8080/")])

    def test_failed_reason_is_emitted_not_swallowed(self):
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)
        mgr.start = lambda c, cs, sleeper=time.sleep: main.StartResult(False, "gate", "需要先装 JDK")
        w = main.LaunchWorker("start", comp, {comp.key: comp}, mgr)
        got = []
        w.failed.connect(lambda k, r: got.append(r))
        w._dispatch()
        self.assertEqual(got, ["需要先装 JDK"])

    def test_unexpected_exception_becomes_failed_not_a_silent_thread(self):
        """start() 会真的动文件系统（建日志目录、开文件、写 running.json），
        这些抛出来说明环境不对。run() 若不接住，线程静默死掉，卡片上的按钮就永远
        停在"进行中"，用户什么也看不见 —— spec §5 要求失败必须可归因。"""
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)

        def boom(c, cs, sleeper=time.sleep):
            raise OSError("磁盘只读")
        mgr.start = boom
        w = main.LaunchWorker("start", comp, {comp.key: comp}, mgr)
        got = []
        w.failed.connect(lambda k, r: got.append(r))
        w.run()                     # 走 run()，验的正是线程入口包不包异常
        self.assertEqual(len(got), 1, "异常必须转成一次 failed，不许静默")
        self.assertIn("磁盘只读", got[0])

    def test_cancel_stops_waiting_without_pretending_the_process_stopped(self):
        """取消只是"别再盯着端口了"，进程可能还在起来 —— 这句话必须原样传给界面。"""
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)

        def slow_start(c, cs, sleeper=time.sleep):
            while True:              # 模拟"一直没监听"：每轮把控制权交给 sleeper
                sleeper(1.0)
        mgr.start = slow_start
        w = main.LaunchWorker("start", comp, {comp.key: comp}, mgr)
        w.cancel()                   # 先取消再跑，第一轮 sleeper 就走取消分支，不会真死循环
        got = []
        w.failed.connect(lambda k, r: got.append(r))
        w.run()
        self.assertEqual(len(got), 1, "取消同样要给一条说明，不许静默结束线程")
        self.assertIn("已取消", got[0])
        self.assertIn("可能仍在启动", got[0])

    def test_stop_action_emits_stopped_on_success(self):
        """Task 10 的按钮态全靠这三个信号驱动，stop 走通时必须发 stopped，
        不能只靠"没有 failed"来推断。"""
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)
        mgr.stop = lambda c, cs, deadline=30.0, sleeper=time.sleep: main.StopResult(True, reason="停了")
        w = main.LaunchWorker("stop", comp, {comp.key: comp}, mgr)
        got, bad = [], []
        w.stopped.connect(lambda k: got.append(k))
        w.failed.connect(lambda k, r: bad.append(r))
        w._dispatch()
        self.assertEqual(got, ["jenkins"])
        self.assertEqual(bad, [], "停成功不该顺带发一条 failed")

    def test_need_force_is_handed_to_the_card_as_a_separate_signal(self):
        """"要不要强制结束"是一次询问，不是一条错误信息。混在 failed 里，
        卡片忘判前缀就会把控制标记当正文显示给用户 —— 所以单独一条信号。"""
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True)
        mgr.stop = lambda c, cs, deadline=30.0, sleeper=time.sleep: main.StopResult(
            False, need_force=True, reason="在 Windows 上只能直接终止进程。要强制结束吗？")
        w = main.LaunchWorker("stop", comp, {comp.key: comp}, mgr)
        asks, bad = [], []
        w.need_force.connect(lambda k, r: asks.append((k, r)))
        w.failed.connect(lambda k, r: bad.append(r))
        w._dispatch()
        self.assertEqual(asks, [("jenkins", "在 Windows 上只能直接终止进程。要强制结束吗？")])
        self.assertEqual(bad, [], "询问不许同时当成失败")

    def test_unknown_action_reports_failure_instead_of_going_silent(self):
        """认不出的 action 以前直接不发信号：线程跑完、卡片停在"进行中"，
        正是兜底要防的那类故障。Task 11 接三个字符串值，写错就要能立刻看见。"""
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)
        w = main.LaunchWorker("reboot", comp, {comp.key: comp}, mgr)
        got = []
        w.failed.connect(lambda k, r: got.append(r))
        w.run()
        self.assertEqual(len(got), 1, "未知动作必须出声")
        self.assertIn("reboot", got[0])


class CardLaunchUi(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig)
        # 下面两条用例会直接改模块单例的探针。不还原的话，"_is_listening 永远真"
        # 会漏给同一进程里后跑的任何类 —— 别的用例就在猜这台机器有没有在听了。
        self._orig_listen = main.SERVICE_MANAGER._is_listening
        self.addCleanup(setattr, main.SERVICE_MANAGER, "_is_listening", self._orig_listen)
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        self.card = main.ComponentCard(comp, lambda msg, level: None)

    def test_launch_buttons_exist_only_for_launchable_components(self):
        self.assertTrue(hasattr(self.card, "btn_start"))
        other = next(c for c in main.build_components() if c.key == "maven")
        card2 = main.ComponentCard(other, lambda msg, level: None)
        self.assertFalse(hasattr(card2, "btn_start"), "非白名单组件不许长出启动按钮")

    def _installed_icon_state(self, card):
        """把 combo 每一项的DecorationRole 读成"有没有勾"的布尔列表。"""
        out = []
        for i in range(card.version_combo.count()):
            data = card.version_combo.itemData(i, Qt.DecorationRole)
            out.append(data is not None and not data.isNull())
        return out

    def test_green_check_marks_every_installed_version_not_just_multi_version(self):
        """下拉框里的绿勾要标出"这个版本装在磁盘上"，**不分组件是否多版本**。

        真机 2026-10-06 查出来的：`_refresh_installed_marks` 开头对
        `multi_version=False` 直接 return，理由是"它们没有版本并存的概念"——
        但下拉框里照样列了具体版本（tomcat 9 / nginx 1.26），用户装完一个版本后
        那个版本就该被标出来。实测结果是 python 有勾、jenkins / nacos / activemq /
        powershell 全都没有，恰好是 multi_version 的分界线。
        """
        with tempfile.TemporaryDirectory() as td:
            # 造一个"装了 6.3.2、候选还有 5.18.4"的非多版本组件
            comp = next(c for c in main.build_components() if c.key == "activemq")
            comp.multi_version = False
            home = Path(td) / "activemq" / "activemq-6.3.2"
            home.mkdir(parents=True)
            (home / "bin").mkdir()
            orig_cfg, main.CONFIG_DIR = main.CONFIG_DIR, Path(td)
            self.addCleanup(setattr, main, "CONFIG_DIR", orig_cfg)
            card = main.ComponentCard(comp, lambda msg, level: None)
            card._refresh_installed_marks()
            marks = self._installed_icon_state(card)
            labels = [card.version_combo.itemText(i) for i in range(card.version_combo.count())]
            self.assertTrue(any(marks), f"已装版本没有绿勾：{list(zip(labels, marks))}")
            idx = labels.index("6.3.2")
            self.assertTrue(marks[idx], "装了的 6.3.2 反而没有绿勾")
            for i, lab in enumerate(labels):
                if lab != "6.3.2":
                    self.assertFalse(marks[i], f"没装的 {lab} 不该有绿勾")

    def test_combo_defaults_to_an_installed_version_not_the_first_candidate(self):
        """下拉框默认选中**已安装的版本**，不是候选清单第一项。

        真机 2026-10-06：jenkins 候选是 2.568.3/2.555.3/2.541.3，磁盘上装的是 2.580.1
        （不在候选里）。无条件选第一项会让界面停在一个没装的版本上——绿勾看着是空的、
        点"配置环境变量"/"卸载"会对着不存在的目录动手，而启动走
        `resolve_launch_version()` 找的是另一个版本，两边对不上。
        """
        with tempfile.TemporaryDirectory() as td:
            comp = next(c for c in main.build_components() if c.key == "activemq")
            home = Path(td) / "activemq" / "activemq-6.3.2"
            home.mkdir(parents=True)
            orig_cfg, main.CONFIG_DIR = main.CONFIG_DIR, Path(td)
            self.addCleanup(setattr, main, "CONFIG_DIR", orig_cfg)
            card = main.ComponentCard(comp, lambda msg, level: None)
            labels = [card.version_combo.itemText(i) for i in range(card.version_combo.count())]
            self.assertIn("6.3.2", labels, "已装版本没被合成进下拉框（该有的绿勾标不出来）")
            self.assertEqual(card.version_combo.currentText(), "6.3.2",
                             f"默认选中的不是已装版本，而是 {card.version_combo.currentText()!r}")

    def test_combo_synthesises_installed_version_missing_from_candidates(self):
        """已装但不在候选清单里的版本必须被合成进下拉框（否则无处标绿勾）。"""
        with tempfile.TemporaryDirectory() as td:
            comp = next(c for c in main.build_components() if c.key == "jenkins")
            home = Path(td) / "jenkins" / "jenkins-9.9.9"
            home.mkdir(parents=True)
            orig_cfg, main.CONFIG_DIR = main.CONFIG_DIR, Path(td)
            self.addCleanup(setattr, main, "CONFIG_DIR", orig_cfg)
            card = main.ComponentCard(comp, lambda msg, level: None)
            labels = [card.version_combo.itemText(i) for i in range(card.version_combo.count())]
            self.assertIn("9.9.9", labels,
                          "装了 9.9.9 却在候选清单里找不到 —— 用户会以为没装成功")
            marks = self._installed_icon_state(card)
            self.assertTrue(marks[labels.index("9.9.9")], "合成进来的已装版本没有绿勾")

    def test_settings_restore_will_not_select_a_version_that_is_not_installed(self):
        """config.json 里存的旧选择若已不可用，不许盲目采纳。

        真机2026-10-06：jenkins 的 selections 里存着 2.568.3（已从候选清单消失、
        也没装），恢复它会把界面按在一个死版本上，盖掉真正装着的 2.580.1。
        """
        win = None
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "jenkins" / "jenkins-2.580.1"
            home.mkdir(parents=True)
            orig_cfg_dir, orig_cfg_file = main.CONFIG_DIR, main.CONFIG_FILE
            main.CONFIG_DIR = Path(td)
            main.CONFIG_FILE = Path(td) / "config.json"
            self.addCleanup(setattr, main, "CONFIG_DIR", orig_cfg_dir)
            self.addCleanup(setattr, main, "CONFIG_FILE", orig_cfg_file)
            main.CONFIG_FILE.write_text(
                '{"selections": {"jenkins": "2.568.3"}}', encoding="utf-8")
            try:
                win = main.MainWindow()
                card = next(c for c in win.cards if c.component.key == "jenkins")
                self.assertEqual(card.version_combo.currentText(), "2.580.1",
                                 "恢复了一个没装的旧选择，盖掉了已装版本")
            finally:
                if win is not None:
                    win.close()
                    win.deleteLater()
                    del win

    def test_green_check_survives_a_version_switch(self):
        """挂勾不许改条目文本 —— 文本是版本反查的唯一键，加「✓」会让选版/卸载/配置全错位。"""
        before = [self.card.version_combo.itemText(i)
                  for i in range(self.card.version_combo.count())]
        self.card._refresh_installed_marks()
        after = [self.card.version_combo.itemText(i)
                 for i in range(self.card.version_combo.count())]
        self.assertEqual(before, after, "挂勾动了条目文本")

    def test_running_state_disables_start_and_enables_stop_and_console(self):
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="http://127.0.0.1:8080/", pid=1, pid_role="server",
            started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": True
        self.card._refresh_launch_state()
        self.assertFalse(self.card.btn_start.isEnabled())
        self.assertTrue(self.card.btn_stop.isEnabled())
        self.assertTrue(self.card.btn_console.isEnabled())
        self.assertIn("运行中", self.card.launch_label.text())
        self.assertIn("8080", self.card.launch_label.text())

    def test_launch_state_does_not_touch_the_existing_capsule(self):
        """状态胶囊有 5 处写点（现 main.py:5565/5579/5719/5798/5810），
        把运行状态挤进去会把既有胶囊逻辑搅浑，所以它只写自己那个 label。"""
        before = self.card.status_label.text()
        self.card._refresh_launch_state()
        self.assertEqual(self.card.status_label.text(), before)
        # 未运行那条只往 label 写空串，"挤没挤进胶囊"根本看不出来（变异自检发现的：
        # 把两处 setText 都改成 status_label，这条用例照旧全绿）。运行态才是有力的一次。
        self._mark_running()
        before = self.card.status_label.text()
        self.card._refresh_launch_state()
        self.assertEqual(self.card.status_label.text(), before)
        self.assertIn("运行中", self.card.launch_label.text())

    def test_stopped_state_enables_start_and_disables_console(self):
        main.save_running_map({})
        self.card._refresh_launch_state()
        self.assertTrue(self.card.btn_start.isEnabled())
        self.assertFalse(self.card.btn_console.isEnabled())

    def test_uninstall_is_blocked_while_running(self):
        """spec §5：运行中禁止卸载，避免"边跑边删目录"。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="u", pid=1, pid_role="server", started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": True
        self.card._refresh_launch_state()
        self.assertFalse(self.card.btn_uninstall.isEnabled())
        self.assertIn("先停止", self.card.btn_uninstall.toolTip())

    # -- 以下用例是变异自检补的：按钮连线与互斥的第二道闸门在上面那些用例里不会暴露。

    def _mark_running(self) -> None:
        """把卡片摆成"运行中"：临时登记表里写一条 + 探针桩成恒听。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="http://127.0.0.1:8080/", pid=1, pid_role="server",
            started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": True

    def _stub_dialogs(self, answers):
        """把 QMessageBox 换成只记录的替身：用例既不弹真窗，也不会误走删除动作。"""
        yes, no = main.QMessageBox.Yes, main.QMessageBox.No
        calls = []
        pending = list(answers)

        class SpyBox:
            Yes, No = yes, no

            @staticmethod
            def question(*a, **k):
                calls.append(("question", " ".join(str(x) for x in a[1:])))
                return pending.pop(0) if pending else no

            @staticmethod
            def warning(*a, **k):
                calls.append(("warning", " ".join(str(x) for x in a[1:])))

        real = main.QMessageBox
        main.QMessageBox = SpyBox
        self.addCleanup(setattr, main, "QMessageBox", real)
        return calls

    def _stub_workers(self):
        """LaunchWorker 换成不起线程的替身：只记录被创建的实例，信号由用例自己发。"""
        created = []
        real = main.LaunchWorker

        class SpyWorker(main.LaunchWorker):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.delete_later_calls = 0

            def start(self):
                created.append(self)

            def deleteLater(self):
                # 只计数不真删：断言"按身份收尾"到底动的是哪条 worker。
                self.delete_later_calls += 1

        main.LaunchWorker = SpyWorker
        self.addCleanup(setattr, main, "LaunchWorker", real)
        return created

    def test_stop_and_force_stop_both_connect_need_force(self):
        """need_force 是"停不下来只询问"的唯一入口（spec §5）。stop 与 force_stop
        两条 worker 都要接上：漏一条，按钮就在"停止中"结束、用户既没被问也没结果。"""
        self._mark_running()
        created = self._stub_workers()
        calls = self._stub_dialogs([main.QMessageBox.Yes, main.QMessageBox.No])
        logs = []
        self.card.log_cb = lambda level, msg: logs.append((level, msg))

        self.card.on_stop_clicked()
        self.assertEqual([w.action for w in created], ["stop"])
        created[0].need_force.emit("jenkins", "端口 8080 仍在听，要强制结束吗？")
        self.assertEqual([w.action for w in created], ["stop", "force_stop"],
                         "stop 的 need_force 没接上就永远问不出这一步")
        self.assertEqual([c[0] for c in calls], ["question"], "询问只该问一次")

        # 同意强杀后起来的第二条 worker 同样要能再问：端口可能被别的进程占着。
        created[1].need_force.emit("jenkins", "端口 8080 仍在监听，可能是别的进程占着。")
        self.assertEqual([w.action for w in created], ["stop", "force_stop"],
                         "force_stop 的 need_force 没接上就会静默结束")
        self.assertEqual([c[0] for c in calls], ["question", "question"])
        self.assertIn("未强制结束", " ".join(m for _l, m in logs))

    def test_uninstall_slot_refuses_while_running(self):
        """置灰可能被别的同步路径顶掉，所以 on_uninstall_clicked 里还要有一道闸门：
        运行中连"确认卸载"的弹窗都不该出现。"""
        self._mark_running()
        calls = self._stub_dialogs([])
        self.card.on_uninstall_clicked()
        self.assertEqual([c for c in calls if c[0] == "question"], [],
                         "运行中不许走到卸载二次确认")
        warnings = [c for c in calls if c[0] == "warning"]
        self.assertEqual(len(warnings), 1, "拒绝必须说清为什么")
        self.assertIn("先停止", warnings[0][1])

    def test_uninstall_lock_only_toggles_on_the_running_edge(self):
        """刷新只在"运行中/刚停止"这条边上动卸载按钮。
        未运行且从未锁过时一律设成可用，会顶掉 _detect_status 按"选中版本装没装"
        算出的判定，给出一张未安装也能点卸载的卡片（承诺做不到的事）。"""
        main.save_running_map({})
        # 绕开 _detect_status 的包装器：判定按钮的从来就是 impl 那套逻辑。
        self.card._detect_status_impl()
        untouched_enabled = self.card.btn_uninstall.isEnabled()
        untouched_tip = self.card.btn_uninstall.toolTip()
        self.card._refresh_launch_state()
        self.assertEqual(self.card.btn_uninstall.isEnabled(), untouched_enabled)
        self.assertEqual(self.card.btn_uninstall.toolTip(), untouched_tip)

        # 运行中 → 锁；停止后 → 解冻（spec §7 演练：运行中禁卸 → 停止后可卸）
        self._mark_running()
        self.card._refresh_launch_state()
        self.assertFalse(self.card.btn_uninstall.isEnabled())
        main.save_running_map({})
        self.card._refresh_launch_state()
        self.assertTrue(self.card.btn_uninstall.isEnabled())

    def test_fresh_card_shows_running_state_without_a_manual_refresh(self):
        """卡片建出来就得带运行态：_detect_status 有四条出口，刷新要挂在每条出口之后，
        漏掉的话端口在听、卡片却显示"停着"，用户只能靠重启工具看出来。"""
        self._mark_running()
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        card = main.ComponentCard(comp, lambda msg, level: None)
        self.assertIn("运行中", card.launch_label.text())
        self.assertTrue(card.btn_console.isEnabled())
        self.assertFalse(card.btn_start.isEnabled())

    def test_worker_signals_drive_the_card(self):
        """started_ok / failed / stopped 三条连线是卡片唯一的"结果"入口：掉一条，
        用户点完按钮只剩按钮自己变灰，日志里一句结果与归因都没有。"""
        created = self._stub_workers()
        calls = self._stub_dialogs([main.QMessageBox.Yes])
        logs = []
        self.card.log_cb = lambda level, msg: logs.append((level, msg))
        spoken = lambda: " ".join(m for _l, m in logs)
        dialogs = lambda kind: " ".join(c[1] for c in calls if c[0] == kind)

        self.card.on_start_clicked()
        self.assertEqual([w.action for w in created], ["start"], "确认启动后必须起线程")
        created[0].started_ok.emit("jenkins", "http://127.0.0.1:8080/")
        self.assertIn("http://127.0.0.1:8080/", spoken(), "started_ok 掉了就没有控制台地址")

        created[0].failed.emit("jenkins", "8080 起 100 个端口内都没找到能整簇空闲的位置")
        self.assertIn("100 个端口内都没找到", dialogs("warning"),
                      "failed 掉了失败归因就看不见")

        self.card.on_stop_clicked()
        self.assertEqual([w.action for w in created], ["start", "stop"])
        created[1].stopped.emit("jenkins")
        self.assertIn("已停止", spoken(), "stopped 掉了卡片不会报告结果")

    # -- 以下用例是 fix round 1 补的：QThread 生命周期的两条删除窗口、
    #    _sync_action_buttons 的运行中锁、僵尸登记的可见性。

    def test_old_worker_finished_does_not_clear_the_force_stop_worker(self):
        """窗口二：need_force 从 worker 线程里发出，_on_need_force 起跑第二条
        force_stop 时老 worker 还没走完；它随后的 finished 会触发共用的
        _on_launch_worker_done —— 那里无条件清属性就把新 worker 的引用抹掉了，
        强杀真正在跑时没人持有它。替身 worker 平时不发 finished，所以这条路
        此前零覆盖，必须手搓一次真发射。"""
        self._mark_running()
        created = self._stub_workers()
        self._stub_dialogs([main.QMessageBox.Yes])

        self.card.on_stop_clicked()          # 第一条：stop worker
        old = created[0]
        old.need_force.emit("jenkins", "端口 8080 仍在听，要强制结束吗？")
        self.assertEqual([w.action for w in created], ["stop", "force_stop"])
        new = created[1]
        self.assertIs(self.card.launch_worker, new)

        old.finished.emit()                  # 老 worker 收尾，共享同一个 done 槽
        self.assertIs(self.card.launch_worker, new,
                      "老 worker 的 finished 不许清掉新 worker 的引用")
        self.assertEqual(new.delete_later_calls, 0,
                         "新 worker 还在跑，谁都不许把它 deleteLater")
        self.assertEqual(old.delete_later_calls, 1,
                         "老 worker finished 后应 deleteLater 收回，不留孤儿")

    def test_every_launch_worker_is_parented_to_the_card(self):
        """窗口一：槽跑到 self.launch_worker = 新 worker 那一步时，老 worker 的
        run() 可能还没返回；丢掉它最后一个 Python 引用，PySide 可以把还在跑的
        QThread 就地销毁（Destroyed while thread is still running → abort）。
        parent=self 让引用归 Qt 对象树持有，三条 worker 都要挂上。"""
        self._mark_running()
        created = self._stub_workers()
        self._stub_dialogs([main.QMessageBox.Yes, main.QMessageBox.Yes])

        self.card.on_stop_clicked()
        self.assertIs(created[0].parent(), self.card, "stop worker 必须挂在卡片对象树下")

        created[0].need_force.emit("jenkins", "端口 8080 仍在听，要强制结束吗？")
        self.assertIs(created[1].parent(), self.card, "force_stop worker 必须挂在卡片对象树下")

        self.card.on_start_clicked()
        self.assertEqual([w.action for w in created], ["stop", "force_stop", "start"])
        self.assertIs(created[2].parent(), self.card, "start worker 必须挂在卡片对象树下")

    def test_sync_action_buttons_keeps_uninstall_locked_while_running(self):
        """切换版本下拉框会走 _sync_action_buttons：它无条件重新启用卸载，
        运行中切一下下拉框，按钮就和"● 运行中"的文案在同一张卡上自相矛盾。"""
        self._mark_running()
        self.card._refresh_launch_state()
        self.assertFalse(self.card.btn_uninstall.isEnabled())
        # Jenkins 非多版本，_mv_buttons_ready 平时恒 False，走不到点亮那一步；
        # 这里造出"选中版本已安装"的态把点亮分支激活，否则用例咬不到要防的东西。
        self.card._mv_buttons_ready = True
        self.card._mv_installed_set = {self.card._current_version().version}

        self.card._sync_action_buttons()
        self.assertFalse(self.card.btn_uninstall.isEnabled(),
                         "运行中（被启动锁过）时按钮同步不许重新点亮卸载")

    def test_zombie_record_shows_residual_and_start_stays_clickable(self):
        """"上次崩了、登记还留着、端口没在听"不该和"干净地停过"长得一模一样：
        label 要说清残留，按钮仍按未运行摆（start() 会覆盖旧登记）。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="http://127.0.0.1:8080/", pid=1, pid_role="server",
            started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": False
        self.card._refresh_launch_state()
        self.assertIn("残留", self.card.launch_label.text())
        self.assertIn("8080", self.card.launch_label.text())
        # 文案不许承诺 start() 不做的事：它不看旧 PID，是直接起新进程覆盖登记。
        # 上次评审点过这句"会自动接管"过界，钉在这里防止改回去。
        self.assertIn("重新起一个", self.card.launch_label.text())
        self.assertNotIn("接管", self.card.launch_label.text())
        self.assertTrue(self.card.btn_start.isEnabled())
        self.assertFalse(self.card.btn_console.isEnabled())
        self.assertFalse(self.card.btn_stop.isEnabled())

    def test_current_worker_finished_hands_the_reference_back(self):
        """上一条测的是"老 worker 的 finished 不许清掉新 worker"；这是同一处代码的另一半：
        **当前** worker 结束时必须把属性交回，否则 `launch_worker is None` 永不成立，
        启动按钮卡在禁用态。把 `self.launch_worker = None` 整行删掉，其余用例仍会全绿。"""
        self._mark_running()
        created = self._stub_workers()
        self.card.on_stop_clicked()
        self.assertIs(self.card.launch_worker, created[0])

        created[0].finished.emit()
        self.assertIsNone(self.card.launch_worker, "当前 worker 结束要交回引用")
        self.assertEqual(created[0].delete_later_calls, 1)
        # 交回引用不等于服务停了：端口还在听时启动仍旧不可点
        self.card._refresh_launch_state()
        self.assertFalse(self.card.btn_start.isEnabled())

    def test_launch_failed_stays_quiet_while_the_window_is_closing(self):
        """关窗链路 closeEvent→cancel→worker 的 failed.emit→这里。模态框自己转事件循环，
        在退出途中弹起来能把关窗卡住；"queued 投递赶不上关窗"只是推测、离线也证实不了，
        所以用 closeEvent 已立的 _closing 旗做便宜的确定性防护，不加新产品状态。"""
        calls = self._stub_dialogs([])
        logs = []
        self.card.log_cb = lambda level, msg: logs.append((level, msg))

        class FakeWin:
            _closing = True

        self.card.window = lambda: FakeWin()   # 遮蔽 Qt 的 window()，只影响 Python 侧调用
        self.card._on_launch_failed("jenkins", "已取消等待")
        self.assertEqual(calls, [], "窗口正在关闭时不许弹模态\"操作失败\"")

        # 另一半：顶层 C++ 对象先没了的话，`self.window()` 这次调用自己就抛 RuntimeError。
        # 必须兜住 —— 否则退出的最后一条线索变成槽函数里的未捕获异常。
        logs.clear()

        def _boom():
            raise RuntimeError("__init__ method of object's base class not called")
        self.card.window = _boom
        self.card._on_launch_failed("jenkins", "已取消等待")   # 不许抛出来
        self.assertEqual(calls, [], "window() 都读不到时更不许弹框")
        self.assertEqual([lvl for lvl, _ in logs], ["warn"],
                         "读不到窗口要按\"正在关闭\"处理并留下日志，而不是静默或崩")
        self.assertEqual(logs, [("warn", "[Jenkins] 操作未完成（窗口正在关闭）：已取消等待")],
                         "不弹框也要在日志里留一句去向")

    def test_uninstall_confirm_text_carries_the_data_note(self):
        """卸载确认必须把"数据去哪儿了"写进去。计划一只说了"删除已安装版本 + 清环境变量"，
        那句话对 Nacos 是半句真话（它的 derby 在版本目录里，会跟着一起没）。
        抽成纯函数是为了这条断言真能跑到文案，而不是只检查字段有没有填。"""
        for key, needle in (("nacos", "安装目录"), ("activemq", "activemq-data")):
            comp = next(c for c in main.build_components() if c.key == key)
            text = main.uninstall_confirm_text(comp)
            self.assertIn(needle, text, f"{key} 的卸载确认没讲清数据去处")
            self.assertIn(comp.display_name, text)

    def test_uninstall_confirm_text_keeps_plan_one_wording_for_jenkins(self):
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        text = main.uninstall_confirm_text(comp)
        self.assertIn("jenkins-data", text,
                      "Jenkins 的数据在 ~/.env-tools 下、卸载后保留——这句话不能因为本期改动而丢")

    def test_uninstall_confirm_text_names_the_env_var_being_removed(self):
        """确认框里必须点名要清哪个环境变量。

        计划初稿把它写成泛指的"清理它的环境变量"，而计划一的三条 bullet 里
        `清理环境变量 {comp.env_var}` 是实打实的信息。卸载不可逆，
        让用户在确认框里看不到变量名，只能自己去翻 PATH 才能确认删的是什么。
        """
        for key, var in (("jenkins", "JENKINS_HOME"), ("activemq", "ACTIVEMQ_HOME"),
                         ("nacos", "NACOS_HOME")):
            with self.subTest(key):
                comp = next(c for c in main.build_components() if c.key == key)
                self.assertEqual(comp.env_var, var, "组件的 env_var 变了，先查组件定义")
                self.assertIn(var, main.uninstall_confirm_text(comp),
                              f"{key} 的卸载确认没点名要清的环境变量")

    def test_uninstall_confirm_text_falls_back_for_components_without_launch(self):
        """26 个组件里绝大多数不可启动（launch 为 None），它们照样能点卸载。
        那条兜底文案现在没有任何用例锁住：把 `if not note:` 改成永假，
        上面两条 data_note 用例照样全绿，而所有非启动组件的确认框会丢掉整段说明。"""
        comp = next(c for c in main.build_components() if c.key == "maven")
        self.assertIsNone(comp.launch, "maven 本期不可启动，这条用例的前提是它没有 launch")
        text = main.uninstall_confirm_text(comp)
        self.assertIn(comp.display_name, text)
        self.assertIn("不会碰你手工放到别处的文件", text,
                      "不可启动组件必须落到兜底文案，而不是 data_note 为空就把说明丢掉")


class MainWindowAdopt(unittest.TestCase):
    """这一层的用例一律不构造真 MainWindow：`MainWindow.__init__` 会建 26 张卡片、
    起版本探测线程，把宿主机网络和 Qt 生命周期都拖进来。用 `__new__` 拿到一个未初始化的实例、
    只补这个方法真正用到的成员，才是本任务这一层的可测形状。

    控制器已在 offscreen 下实测过这个形状：`MainWindow.__new__` 出来的对象可以正常赋 Python 属性
    （`_append_log`、`cards`、甚至**遮蔽** `findChildren`），`current_components()` 这种 staticmethod
    也能通过它调用；但凡碰真的 Qt 方法（如未遮蔽的 `findChildren`）就抛
    `RuntimeError: '__init__' method of object's base class not called`。
    所以 `_cancel_launch_workers` 用注入的 findChildren 测；`closeEvent` 本身测不了（要调 super），
    它除了关窗取消启动线程那一行委派外，还负责立 `_closing`/FETCH_ABORT 旗、存设置、
    等版本探测与在途抓取线程收尾 —— 委派那行由源码守护用例钉接线，不要为了测它去构造真窗口。"""

    def bare_win(self, logs):
        win = main.MainWindow.__new__(main.MainWindow)
        win._append_log = lambda level, msg: logs.append((level, msg))
        win.cards = []          # _adopt_running 收尾要遍历卡片重读实况；没卡片也得有个空表
        return win

    def setUp(self):
        self.calls = []
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig_file = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig_file)
        self._orig_mgr = main.SERVICE_MANAGER
        self.addCleanup(setattr, main, "SERVICE_MANAGER", self._orig_mgr)
        # 找回路径"绝不执行进程"要有牙齿：任何拉进程的口都要留下证据
        self._orig_popen = main.subprocess.Popen
        main.subprocess.Popen = lambda *a, **k: self.calls.append(a)
        self.addCleanup(setattr, main.subprocess, "Popen", self._orig_popen)
        self._orig_run = main.subprocess.run
        main.subprocess.run = lambda *a, **k: self.calls.append(a)
        self.addCleanup(setattr, main.subprocess, "run", self._orig_run)
        self._orig_system = main.os.system
        main.os.system = lambda *a, **k: self.calls.append(a)
        self.addCleanup(setattr, main.os, "system", self._orig_system)

    def test_current_components_covers_whitelist(self):
        got = main.MainWindow.current_components()
        self.assertTrue(main.LAUNCH_KEYS.issubset(set(got)), "启动白名单组件必须能在卡片间互相看见（needs 判定要用）")

    def test_adopt_running_drops_zombies_without_touching_processes(self):
        """僵尸（登记在、端口没在听）必须被清掉，而且整个过程一次进程都不许起。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="u", pid=1, pid_role="server", started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": False,
            http_ok=lambda u, timeout=2.0: False, process_alive=lambda pid: True)
        logs = []
        self.bare_win(logs)._adopt_running()
        self.assertEqual(main.load_running_map(), {})
        self.assertEqual(self.calls, [], "找回过程拉起了进程")
        self.assertEqual(logs, [], '僵尸不该被报成"检测到正在运行"')

    def test_adopt_running_reports_what_it_found_running(self):
        """开工具时如果 Jenkins 还在跑，日志要认出它 —— 这是"关掉了再打开也认得"那条判据。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8123,
            console_url="http://127.0.0.1:8123/", pid=1, pid_role="server",
            started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": True,
            http_ok=lambda u, timeout=2.0: True, process_alive=lambda pid: True)
        logs = []
        self.bare_win(logs)._adopt_running()
        self.assertEqual([m for _, m in logs], ["检测到 jenkins 正在运行（端口 8123）"])
        self.assertIn("jenkins", main.load_running_map(), "在跑的登记不许被清掉")

    def test_adopt_running_re_syncs_every_card_after_cleaning(self):
        """_adopt_running 会把僵尸登记删掉，而卡片可能在它跑之前就已经把"残留登记"画出来了。
        不清一遍卡片就会在窗口里留一句假警告，直到用户碰别的什么东西才刷新。"""
        refreshed = []

        class FakeCard:
            def _refresh_launch_state(self):
                refreshed.append(True)

        main.SERVICE_MANAGER = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": False,
            http_ok=lambda u, timeout=2.0: False, process_alive=lambda pid: False)
        win = self.bare_win([])
        win.cards = [FakeCard(), FakeCard(), FakeCard()]
        win._adopt_running()
        self.assertEqual(len(refreshed), 3, "认清本机之后每张卡片都要重读一次实况")

    def test_close_cancels_then_waits_every_in_flight_worker(self):
        """Task 9 的 cancel 落点：关窗口时先给每个在跑的 worker 一次体面退出，
        不是把线程连同 QThread 一起扔了（cancel 只停止"等端口"，不动别人的进程）。"""
        done = []

        class FakeWorker:
            def cancel(self):
                done.append("cancel")
            def wait(self, ms):
                done.append(("wait", ms))

        win = self.bare_win([])
        win.findChildren = lambda cls: [FakeWorker(), FakeWorker()]
        self.assertEqual(win._cancel_launch_workers(), 2)
        self.assertEqual(done, ["cancel", "cancel", ("wait", 2000), ("wait", 2000)],
                         "必须先全部 cancel 再 wait，否则第二个 worker 要白等第一个的超时")

    def test_adopt_runs_at_the_entry_point_not_in_the_constructor(self):
        """接线位置的守护：`bt_component_category_tests.py:90` 与 `bt_multiversion_tests.py:820`
        会直接构造真 MainWindow（只停掉联网抓版本）。而 `_adopt_running` 要读并写用户的
        `running.json`、还要对真实端口发探测 —— 挂进 `__init__` 就是让两个不相干的单元测试
        去改用户机器上的运行登记。Task 4 的 NoExecInvariant 已经漏写过一次（6a80c84 才收掉）。
        closeEvent→_cancel_launch_workers 的委派同用源码守护：它防的是 QThread 运行时被析构
        （Windows 退出码 0xC0000409），将来谁删了那行，行为用别的用例看不出来。"""
        import inspect
        # 断言一律匹配"调用形状"而不是光函数名：closeEvent 顶上的注释里就写着
        # _cancel_launch_workers 这个名字，只匹配名字的守护删掉调用也会假绿。
        self.assertIn("win._adopt_running()", inspect.getsource(main.main),
                      "生产入口没接认清运行状态的步骤")
        self.assertNotIn("._adopt_running()", inspect.getsource(main.MainWindow.__init__),
                         "__init__ 里做这件事会被所有构造窗口的测试继承")
        self.assertIn("self._cancel_launch_workers()", inspect.getsource(main.MainWindow.closeEvent),
                      "closeEvent 没接关窗取消在跑 worker 的步骤")

    def test_adopt_running_never_blocks_startup_when_reconcile_fails(self):
        """reconcile 清僵尸会回写 running.json：目录只读/被锁/磁盘满时，异常若从
        _adopt_running 抛出就是从入口抛出，工具直接打不开。识别失败只该留下一条 warn。"""
        class BoomManager:
            def reconcile(self, _components):
                raise OSError("权限不足")

        main.SERVICE_MANAGER = BoomManager()
        logs = []
        self.bare_win(logs)._adopt_running()   # 兜底没生效时异常会在这儿把用例打红
        self.assertEqual([lvl for lvl, _m in logs], ["warn"], "失败只该记一条中文 warn")
        self.assertIn("权限不足", logs[0][1])


class NetstatParse(unittest.TestCase):
    """fixture 是 2026-10-05 在本机（中文 Windows）实抓的 netstat -ano 文本形状。
    两个必须记住的实测事实：表头是本地化的（协议/本地地址/外部地址/状态），
    而状态值不翻译（LISTENING 仍是英文）—— 所以解析只认列形状，
    任何"按表头找列"的写法都会在中文系统上整个失效。"""

    HEAD = (
        "活动连接\n"
        "\n"
        "  协议  本地地址          外部地址        状态           PID\n"
    )
    BODY = (
        "  TCP    0.0.0.0:8848           0.0.0.0:0              LISTENING       12345\n"
        "  TCP    [::]:8848              [::]:0                 LISTENING       12345\n"
        "  TCP    0.0.0.0:9848           0.0.0.0:0              LISTENING       12345\n"
        "  TCP    0.0.0.0:9849           0.0.0.0:0              LISTENING       12345\n"
        "  TCP    127.0.0.1:54321        127.0.0.1:8848         ESTABLISHED     999\n"
        "  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1212\n"
        "  UDP    0.0.0.0:5353           *:*                                    4242\n"
    )

    def test_localized_header_and_ipv6_lines_are_handled(self):
        table = main.parse_netstat_listeners(self.HEAD + self.BODY)
        self.assertEqual(table.get(8848), {12345}, "IPv4/IPv6 两行都要归到同一个 PID")
        self.assertEqual(table.get(9848), {12345})
        self.assertEqual(table.get(135), {1212})
        # 只有 IPv6 行时也必须认得出归属：真实世界里"只绑 [::]"的服务很常见，
        # 少了这一步，删掉 IPv6 处理只会让上面三条"顺带"绿着（变异自检实测过）。
        v6_only = ("  TCP    [::]:61616             [::]:0                 LISTENING       4444\n")
        only = main.parse_netstat_listeners(self.HEAD + v6_only)
        self.assertEqual(only.get(61616), {4444}, "IPv6-only 监听行不许被丢掉")

    def test_only_listening_rows_count(self):
        # ESTABLISHED 那行里有 8848，但它是客户端连接，不能当成"谁在监听这个口"
        table = main.parse_netstat_listeners(self.HEAD + self.BODY)
        self.assertNotIn(54321, table)
        self.assertEqual(table[8848], {12345})
        self.assertNotIn(5353, table, "UDP 没有监听语义，不许进来")

    def test_garbage_lines_are_skipped_not_fatal(self):
        table = main.parse_netstat_listeners(
            "  TCP    bogus    LISTENING\n"
            "  TCP    0.0.0.0:80    0.0.0.0:0    LISTENING   not-a-pid\n"
            + self.BODY)
        self.assertEqual(table.get(8848), {12345})

    def test_ambiguous_owner_is_reported_as_no_candidate(self):
        """同一个口被两个 PID 听着（端口复用/容器网络栈都可能）→ 宁可不认。
        认了就等于我们可能去杀一个不是我们的进程。"""
        both = (self.BODY
                + "  TCP    0.0.0.0:61616          0.0.0.0:0              LISTENING       777\n"
                  "  TCP    0.0.0.0:61616          0.0.0.0:0              LISTENING       888\n")
        table = main.parse_netstat_listeners(both)
        self.assertEqual(table[61616], {777, 888})
        self.assertNotIn(61616, main._pick_unique_pids(table, (61616,)),
                         "归属有歧义时不许给出动手对象")
        self.assertEqual(main._pick_unique_pids(table, (8848,)), {8848: 12345})

    def test_posix_listen_state_is_recognised_too(self):
        """Linux/macOS 的 netstat 状态串是 LISTEN，不是 LISTENING。

        只认LISTENING 的话，本解析器在非Windows 上恒返回 {}，
        端口反查在那两个平台上会静默变成"找不到对象"——功能哑掉而不是报错。
        """
        table = main.parse_netstat_listeners(
            "tcp4  0  0  127.0.0.1.8848  *.*  LISTEN  12345\n")
        self.assertEqual(table.get(8848), {12345})

    def test_netstat_subprocess_runs_without_a_console_window(self):
        """netstat 会被真实调用（Task 7 起它在force 路径上可达）。
        不带 CREATE_NO_WINDOW，从GUI 点"强制结束"就会闪一个黑框。"""
        seen = {}

        class Done:
            stdout = "  TCP    0.0.0.0:8848    0.0.0.0:0    LISTENING   12345\n"

        def fake_run(argv, **kw):
            seen.update(kw)
            seen["argv"] = argv
            return Done()

        orig = main.subprocess.run
        main.subprocess.run = fake_run
        self.addCleanup(setattr, main.subprocess, "run", orig)
        main.CURRENT_OS = "Windows"
        main.netstat_listener_pids([8848])
        self.assertEqual(seen.get("creationflags", 0) & main.CREATE_NO_WINDOW,
                         main.CREATE_NO_WINDOW, "netstat 子进程没带静默标志")


class ConfCopyWriteback(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.src = Path(self.dir.name) / "official-conf"
        self.dst = Path(self.dir.name) / "data" / "conf"
        (self.src / "jetty").mkdir(parents=True)
        # ↓ 三行是 6.3.2 真包原文（conf/jetty-spring.properties:35、conf/activemq.xml:178、
        #   conf/login.config 的 JAAS 相对文件名）。改这三行等于改结论，要先去重新实测。
        (self.src / "jetty-spring.properties").write_text(
            "# some header\njetty.http.port=8161\njetty.ssl.port=8443\n", encoding="utf-8")
        (self.src / "activemq.xml").write_text(
            '      <transportConnectors>\n'
            '        <transportConnector name="openwire" '
            'uri="tcp://0.0.0.0:61616?maximumConnections=1000&amp;'
            'wireFormat.maxFrameSize=10485760"/>\n'
            '      </transportConnectors>\n', encoding="utf-8")
        (self.src / "login.config").write_text(
            'org.apache.activemq.jaas.PropertiesLoginModule required\n'
            '    org.apache.activemq.jaas.properties.user="users.properties"\n'
            '    org.apache.activemq.jaas.properties.group="groups.properties";\n',
            encoding="utf-8")
        (self.src / "jetty" / "jetty-http.xml").write_text(
            '    <Set name="port"><Property name="jetty.http.port" default="8080" /></Set>\n',
            encoding="utf-8")
        (self.src / "users.properties").write_text("admin=admin\n", encoding="utf-8")
        # 副本在这里就建好：下面除了"建立副本"本身那条用例，其余都是拿"已有副本"做前提。
        # （漏了这一步的用例不会红在断言上，而红在"读不到文件"上——那是假失败。）
        main.prepare_conf_copy(self.src, self.dst)

    def test_whole_directory_is_copied_not_single_files(self):
        """必须整目录：实测 conf/login.config 里 JAAS 用的是相对文件名
        （users.properties / groups.properties，由 activemq.conf 解析），
        只拷两个端口文件会让控制台鉴权静默失效——报"起来了但登不进去"。"""
        fresh = Path(self.dir.name) / "fresh-copy"      # 用没建过的目标，才看得到 created 分支
        state, new = main.prepare_conf_copy(self.src, fresh)
        self.assertEqual(state, "created")
        self.assertTrue(new, "首次拷贝要报出建了哪些文件")
        for rel in ("jetty-spring.properties", "activemq.xml", "login.config",
                    "users.properties", "jetty/jetty-http.xml"):
            self.assertTrue((fresh / rel).exists(), f"副本缺 {rel}")
        self.assertIn("jetty/jetty-http.xml", new, "子目录没被算进相对路径清单里")

    def test_existing_copy_is_authoritative_and_only_reported(self):
        """副本一旦建立就是权威：换版本带来的新文件只点名、不自动补、不覆盖。
        补哪几个、用什么内容补，等于猜厂商升级意图。"""
        main.prepare_conf_copy(self.src, self.dst)
        (self.dst / "jetty-spring.properties").write_text(
            "jetty.http.port=9999\n", encoding="utf-8")        # 用户/我们改过
        (self.src / "brand-new-defaults.properties").write_text("x=1\n", encoding="utf-8")
        before = (self.dst / "jetty-spring.properties").read_text(encoding="utf-8")

        state, missing = main.prepare_conf_copy(self.src, self.dst)
        self.assertEqual(state, "exists")
        self.assertEqual(missing, ["brand-new-defaults.properties"])
        self.assertEqual((self.dst / "jetty-spring.properties").read_text(encoding="utf-8"),
                         before, "已存在的副本文件被覆盖了")

    def test_property_line_moves_only_the_target_line(self):
        ok, why = main.set_property_line(self.dst / "jetty-spring.properties",
                                         "jetty.http.port", "8261")
        self.assertTrue(ok, why)
        txt = (self.dst / "jetty-spring.properties").read_text(encoding="utf-8")
        self.assertIn("jetty.http.port=8261", txt)
        self.assertIn("jetty.ssl.port=8443", txt, "无关行被顺手改了")
        self.assertIn("# some header", txt)

    def test_writeback_is_idempotent_and_backs_up_only_on_first_change(self):
        target = self.dst / "jetty-spring.properties"
        main.prepare_conf_copy(self.src, self.dst)
        self.assertTrue(main.set_property_line(target, "jetty.http.port", "8261")[0])
        bak = target.with_name(target.name + ".bak")
        self.assertTrue(bak.exists(), "首次改动必须留一次备份")
        stamp = target.stat().st_mtime_ns
        content = target.read_text(encoding="utf-8")

        self.assertTrue(main.set_property_line(target, "jetty.http.port", "8261")[0])
        self.assertEqual(target.read_text(encoding="utf-8"), content, "第二次改动了文件")
        self.assertEqual(target.stat().st_mtime_ns, stamp,
                         "已是目标值还写文件：反复点启动会刷出一堆备份、白改 mtime")

    def test_unanchorable_line_is_refused_with_actionable_reason(self):
        """锚不到那行就拒改（§5 的有边界退回），且原因必须说清改哪个文件哪一行——
        只报"配置有问题"就是 R4 第 6 条禁止的"你自己去弄"。"""
        target = self.dst / "jetty-spring.properties"
        target.write_text("jetty.http.port =  8161   # 用户手加了空格和行尾注释\n",
                          encoding="utf-8")
        ok, why = main.set_property_line(target, "jetty.http.port", "8261")
        self.assertFalse(ok)
        self.assertIn("jetty-spring.properties", why)
        self.assertIn("jetty.http.port", why)
        self.assertIn("手工", why)

    def test_openwire_port_line_is_the_one_with_the_name_attribute(self):
        ok, why = main.set_openwire_port(self.dst / "activemq.xml", 61716)
        self.assertTrue(ok, why)
        txt = (self.dst / "activemq.xml").read_text(encoding="utf-8")
        self.assertIn("tcp://0.0.0.0:61716?", txt)
        self.assertIn("maximumConnections=1000", txt, "&amp; 之后的部分被吃掉了")
        self.assertNotIn("61616", txt)

    def test_openwire_refuses_when_amq_default_is_commented_or_absent(self):
        target = self.dst / "activemq.xml"
        target.write_text('      <transportConnectors>\n'
                          '        <!-- <transportConnector name="openwire" uri="tcp://0.0.0.0:61616?"/ -->\n'
                          '      </transportConnectors>\n', encoding="utf-8")
        ok, why = main.set_openwire_port(target, 61716)
        self.assertFalse(ok)
        self.assertIn("activemq.xml", why)
        self.assertIn("openwire", why)


class PortPlanning(unittest.TestCase):
    def spec(self, **kw):
        base = dict(commands={os_name: ["x"] for os_name in ("Windows", "Linux", "Darwin")},
                    main_port=8848, port_offsets=(1000, 1001))
        base.update(kw)
        return main.LaunchSpec(**base)

    def comp(self):
        return next(c for c in main.build_components() if c.key == "jenkins")

    def test_all_free_takes_the_declared_defaults(self):
        plan, why = main.choose_ports(self.spec(), is_free=lambda p, host="127.0.0.1": True)
        self.assertEqual(why, "")
        self.assertEqual(plan.all_ports, (8848, 9848, 9849))

    def test_derived_ports_are_the_offsets_of_the_fixed_main_port(self):
        """派生口（Nacos gRPC）= 主口 + offset，且**主口永远是官方默认的那个**。

        这条原来叫 `test_derived_ports_move_with_the_main_port`，断言"主口平移到 8850
        时派生口变成 9850/9851"。2026-10-06 起契约反转为**不平移**：
        Nacos 的 gRPC 口由 `server.port + 1000/1001` 派生，而 SDK 与各类客户端
        配置里写死 8848 —— 平移会造成"服务起来了但外部客户端一个都连不上"，
        比起不来更难归因。所以主口恒为 8848，派生口恒为 9848/9849。
        """
        plan, why = main.choose_ports(
            self.spec(), is_free=lambda p, host="127.0.0.1": True, evict=False)
        self.assertEqual((plan.main, plan.derived, plan.all_ports),
                         (8848, (9848, 9849), (8848, 9848, 9849)), why)

    def test_extra_ports_keep_their_own_declared_value(self):
        """独立口（ActiveMQ 61616）用它自己登记的值，不跟着主口动。

        这条原来断言"控制台口平移到 8162 时 broker 口仍从 61616 起找" ——
        现在连主口都不平移了，所以两个口都必须是登记时的原值。
        """
        s = self.spec(main_port=8161, port_offsets=(), extra_ports=(61616,))
        plan, why = main.choose_ports(
            s, is_free=lambda p, host="127.0.0.1": True, evict=False)
        self.assertEqual((plan.main, plan.extras, plan.all_ports),
                         (8161, (61616,), (8161, 61616)), why)

    def test_busy_port_fails_instead_of_shifting_and_names_every_busy_port(self):
        """端口被占 → 原地失败（evict=False 时），且失败原因把**每一个**被占的口都列出来。

        这条原来叫 `test_failure_names_the_port_that_had_no_room`，断言"8848 起 100 个
        端口内都找不到整簇位置"。现在是"不平移"，所以失败原因必须列出到底哪几个口
        被占着——派生口被占也要点名，否则用户只知道 8848 被占、不知道 gRPC 也有问题。
        """
        taken = {8848, 9848, 9849}
        plan, why = main.choose_ports(
            self.spec(), is_free=lambda p, host="127.0.0.1": p not in taken, evict=False)
        self.assertEqual(plan.all_ports, (), "拿不到端口就不该给出计划")
        for port in (8848, 9848, 9849):
            self.assertIn(str(port), why, f"失败原因漏了被占的 {port}")
        self.assertIn("不会再自动换端口", why, "要说清这次不会去别处找口")

    def test_independent_port_taken_is_named_too(self):
        """独立口（61616）被占时，失败原因要点名它，且不许连主口一起报成"都找不到"。

        ActiveMQ 的两个口角色不同：8161 是控制台、61616 是 broker 传输口。
        用户看到"8161 被占"去关控制台，结果broker 起不来 —— 两个口必须各自点名。
        """
        s = self.spec(main_port=8161, port_offsets=(), extra_ports=(61616,))
        taken = {61616}
        plan, why = main.choose_ports(
            s, is_free=lambda p, host="127.0.0.1": p not in taken, evict=False)
        self.assertEqual(plan.all_ports, ())
        self.assertIn("61616", why, "被占的独立口要点名")
        self.assertIn("独立端口", why, "要点明它的角色是独立端口，不是派生口")

    def test_build_plan_injects_conf_dir_and_extra_env(self):
        """extra_env 的占位符必须能拿到 conf_dir/data_dir：ActiveMQ 的 ACTIVEMQ_CONF
        指向副本、ACTIVEMQ_DATA 指向 data，两者都是端口定了、副本建好之后才写得出的值。"""
        comp = self.comp()
        s = self.spec(extra_env={"ACTIVEMQ_CONF": "{conf_dir}", "ACTIVEMQ_DATA": "{data_dir}"})
        with tempfile.TemporaryDirectory() as td:
            orig, main.CONFIG_DIR = main.CONFIG_DIR, Path(td)
            self.addCleanup(setattr, main, "CONFIG_DIR", orig)
            plan = main.build_launch_plan(comp, s, r"C:\jdk", 8848,
                                          Path(td) / "logs" / "byte-tools.out")
        self.assertEqual(plan.env["ACTIVEMQ_CONF"], str(Path(td) / "jenkins-data" / "conf"))
        self.assertEqual(plan.env["ACTIVEMQ_DATA"], str(Path(td) / "jenkins-data"))

    def test_conf_copy_prepare_touches_no_file_for_cli_strategies(self):
        for strategy in ("cli_only", "cli_flag"):
            with self.subTest(strategy=strategy):
                with tempfile.TemporaryDirectory() as td:
                    ok, why, notes = main.prepare_ports(
                        self.comp(), self.spec(port_writeback=strategy),
                        main.PortPlan(main=8848, derived=(9848, 9849)), Path(td))
                self.assertTrue(ok, why)
                self.assertEqual(list(Path(td).rglob("*")), [],
                                 f"{strategy} 不该写任何文件：Nacos 的端口走命令行透传")

    def test_conf_copy_writes_only_into_the_copy(self):
        """conf_copy 的回写只发生在 data/conf 里，官方目录一个字节不动。
        fixture 是 6.3.2 真包原文的两行（spec 计划二 §2.1）。"""
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            (home / "conf").mkdir(parents=True)
            (home / "conf" / "jetty-spring.properties").write_text(
                "jetty.http.port=8161\n", encoding="utf-8")
            (home / "conf" / "activemq.xml").write_text(
                '  <transportConnector name="openwire" '
                'uri="tcp://0.0.0.0:61616?maximumConnections=1000"/>\n', encoding="utf-8")
            data = Path(td) / "data"
            comp = self.comp()
            comp.versions = [comp.versions[0]]
            s = self.spec(main_port=8161, port_offsets=(), extra_ports=(61616,),
                          port_writeback="conf_copy")
            orig_install, comp.install_dir = comp.install_dir, (lambda v: home)
            self.addCleanup(setattr, comp, "install_dir", orig_install)

            ok, why, notes = main.prepare_ports(
                comp, s, main.PortPlan(main=8162, extras=(61716,)), data)
            self.assertTrue(ok, why)
            copy = (data / "conf")
            self.assertIn("jetty.http.port=8162",
                      (copy / "jetty-spring.properties").read_text(encoding="utf-8"))
            self.assertIn("0.0.0.0:61716",
                          (copy / "activemq.xml").read_text(encoding="utf-8"))
            self.assertEqual((home / "conf" / "jetty-spring.properties").read_text(encoding="utf-8"),
                             "jetty.http.port=8161\n", "官方文件被动了")

    def test_start_refuses_to_spawn_when_writeback_fails(self):
        """回写失败必须拦住 spawn：配置没改成新端口就把进程拉起来，用户会看到一个
        "运行中"却连在旧端口上的服务，而界面上写的是刚选的新端口 —— 两边状态对不上
        比"没启动"更难归因。

        这条钉的是 R5.3 第 9 条（回写只写副本、锚不到就拒改）的**后果**那一半：
        之前 prepare_ports 的失败分支各自有用例（Task 6 的 cli/锚不上），
        但"start() 拿到 False 之后怎么办"没有任何用例。
        变异自检把`if not ok: return StartResult(False, "writeback", why, notes=notes)`
        整个删掉时，全套 129 条依然全绿 —— 护栏是空的。"""
        comp = self.comp()
        s = self.spec(port_writeback="conf_copy", extra_ports=())
        s.main_port, s.port_offsets = 8161, ()
        home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(home, ignore_errors=True))
        (home / "conf").mkdir(parents=True)
        # 官方 conf 故意不含 jetty.http.port 这一行 → set_property_line 锚不到 → 拒改
        (home / "conf" / "jetty-spring.properties").write_text(
            "# 端口被用户注释掉了\n", encoding="utf-8")
        comp.versions = [comp.versions[0]]
        orig_install, comp.install_dir = comp.install_dir, (lambda v: home)
        self.addCleanup(setattr, comp, "install_dir", orig_install)

        ok, why, notes = main.prepare_ports(
            comp, s, main.PortPlan(main=8161), Path(tempfile.mkdtemp()))
        self.assertFalse(ok, "锚不到就该拒改")
        self.assertIn("jetty.http.port", why, "拒改必须指名要改哪一行")

        # 同一失败经 start() 落地：不许 spawn、不许留登记、状态叫 writeback。
        # 注意 data_dir 由 start() 自己推导成 CONFIG_DIR/<key>-data，所以必须先把
        # CONFIG_DIR 指到 temp 里，再造出"副本里锚不到 jetty.http.port"的状态。
        with tempfile.TemporaryDirectory() as td:
            orig_cfg, orig_run = main.CONFIG_DIR, main.RUNNING_FILE
            main.CONFIG_DIR = Path(td)
            main.RUNNING_FILE = Path(td) / "running.json"
            self.addCleanup(setattr, main, "CONFIG_DIR", orig_cfg)
            self.addCleanup(setattr, main, "RUNNING_FILE", orig_run)
            # 官方 conf 不含该行 → 副本建出来后 set_property_line 锚不到 → 拒改
            data = Path(td) / f"{comp.key}-data"
            (data / "conf").mkdir(parents=True)
            (data / "conf" / "jetty-spring.properties").write_text(
                "# 端口那行被注释掉了\n", encoding="utf-8")
            spawned = []
            orig_popen = main.subprocess.Popen
            main.subprocess.Popen = lambda argv, **kw: spawned.append(argv)
            self.addCleanup(setattr, main.subprocess, "Popen", orig_popen)
            mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                      http_ok=lambda u, timeout=2.0: True,
                                      process_alive=lambda pid: True)
            # start() 读的是 comp.launch，不是我们手搓的 spec —— 必须挂上去，
            # 否则它拿 jenkins 原有的 cli_only 走早退分支，这条用例会静默测不到东西。
            orig_launch, comp.launch = comp.launch, s
            self.addCleanup(setattr, comp, "launch", orig_launch)
            res = mgr.start(comp, {comp.key: comp}, sleeper=lambda s: None)
        self.assertFalse(res.ok, "回写失败却判启动成功 = 运行中但连在旧端口上")
        self.assertEqual(res.state, "writeback", f"实际 state={res.state}，reason={res.reason}")
        self.assertIn("jetty.http.port", res.reason, "失败原因必须指名要改哪一行")
        self.assertEqual(spawned, [], "回写失败仍拉起了进程：配置与实际端口必然对不上")
        self.assertEqual(main.load_running_map(), {}, "启动失败不许留登记")

    def test_timeout_reason_reaches_for_the_vendor_log(self):
        """厂商把报错写在自家文件里，只给我们自己那份重定向文件的尾巴，
        用户就看到"起不来"三个字而不知道去看哪。"""
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "data").mkdir()
            (data / "data" / "activemq.log").write_text(
                "Caused by: java.lang.OutOfMemoryError\n", encoding="utf-8")
            out = main.vendor_log_tails(data, data, "activemq")
            self.assertIn("OutOfMemoryError", out)
            self.assertIn("activemq.log", out)
            self.assertIn("尚未生成", main.vendor_log_tails(data, data, "nacos"))

class EvictGuard(unittest.TestCase):
    """端口被占时「结束占用者」这条能力自己的护栏。

    独立成类而不是挂在 StartFlow 里：StartFlow.setUp 为了隔离会把
    evict_port_occupant 整个桩掉，挂在那边就永远测不到真函数。
    """

    def test_evict_never_kills_our_own_process(self):
        """**绝不结束自己** —— 这条守卫删掉会造成不可逆的误伤。

        场景：本工具刚给某个组件拉起进程（登记 PID = 本工具自己，因为
        `startup.cmd` 之类包装器在某些配置下会让子进程等于 launcher），
        用户又点了一次启动 → 端口反查回来的 PID 就是 `os.getpid()`。
        此时若无条件 os.kill(getpid(), 9)，**本工具会把正在运行中的自己杀掉**，
        用户看到的是界面突然消失、没有报错。

        这条钉住"排除自己"这道闸：即使 PID 反查结果是自己，也只能报错不许动手。
        """
        import os as _os
        with tempfile.TemporaryDirectory() as td:
            # 结束占用者是 Windows-only 能力（用的是 tasklist + os.kill 语义），
            # 非 Windows 上直接拒绝动手。所以这条用例先把 OS 钉成 Windows。
            orig_os = main.CURRENT_OS
            main.CURRENT_OS = "Windows"
            self.addCleanup(setattr, main, "CURRENT_OS", orig_os)
            # 让 occupant_of 报出"占用者就是我自己"
            orig = main.occupant_of
            main.occupant_of = lambda port: (_os.getpid(), "byte-tools.exe")
            self.addCleanup(setattr, main, "occupant_of", orig)
            killed = []
            orig_kill = main.os.kill
            main.os.kill = lambda pid, sig: killed.append(pid)
            self.addCleanup(setattr, main.os, "kill", orig_kill)
            orig_alive = main.pid_alive
            main.pid_alive = lambda pid: True
            self.addCleanup(setattr, main, "pid_alive", orig_alive)

            why = main.evict_port_occupant(8080, "主端口")
        self.assertIsNotNone(why, "占用者是自己时必须拒绝动手，而不是返回成功")
        self.assertIn("自己", why, f"拒绝理由要说清是「自己」：{why}")
        self.assertEqual(killed, [], "绝不能对自己 os.kill")

if __name__ == "__main__":
    unittest.main()
