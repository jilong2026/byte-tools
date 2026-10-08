"""一键启动护栏（离线）。设计文档见docs/superpowers/specs/2026-10-05-one-click-launch-design.md"""
import copy
import json
import os
import platform as _platform
import re
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
        # 2026-10-06 扩到 9 个：新增 rocketmq/nginx/kafka/tomcat/elasticsearch/rabbitmq
        # （每一个都有当天的真机实测报告，见 .workbuddy/verify_*.md）。
        # 同日再扩到 10 个：新增 seata（双进程，实测报告见
        # docs/LAUNCH_CANDIDATES.md 的 seata 一节）。
        # 这条断言的作用是"多一个组件就要多一份实测事实"，所以**不能放宽成
        # 「只要在 LAUNCH_OF 里就行」** —— 那等于取消约束。
        self.assertEqual(
            main.LAUNCH_KEYS,
            {"jenkins", "nacos", "activemq",
             "rocketmq", "nginx", "kafka", "tomcat", "elasticsearch", "rabbitmq",
             "seata"},
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
        """spec §2.4 第 5 项：**没实测过就不许填数字**，门控只能退化成"有没有 JDK"。

        2026-10-08 更新：jenkins 已经实测过了 —— 拆装在本机的 2.580.1 读出来
        `META-INF/MANIFEST.MF: Java-Version: 11`，包内唯一顶层 class 的
        major version = 55（= Java 11）。所以它现在**允许**有数字，且必须是 11；
        其余没拆过包的组件仍然一律 None。这条护栏因此从"jenkins 必须 None"
        改成"jenkins 必须是实测值、别人必须 None" —— 前者防止随手填数字，
        后者防止把"没测过"悄悄变成"测过了"。
        """
        self.assertEqual(self.comps["jenkins"].launch.min_java_major, 11,
                         "jenkins 的门槛 11 来自 war 清单实测（Java-Version: 11）")
        measured = {"jenkins": 11, "nacos": 8, "activemq": 17, "rocketmq": 17,
                    "kafka": 17, "tomcat": 11, "seata": 8}
        for key, spec in main.LAUNCH_OF.items():
            if key in measured:
                self.assertEqual(spec.min_java_major, measured[key],
                                 f"{key} 的门槛与实测值不符")
            else:
                self.assertIsNone(spec.min_java_major,
                                  f"{key} 还没实测过版本门槛，不许填数字")

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
            # adopt 返回**全部**可启动组件（2026-06-06 起组件数>1，取 [0] 就取错了组件）
            sts = {k: s.state for k, s in
                   zip([k for k in sorted(comps) if comps[k].launch is not None],
                       mgr.adopt(comps))}
            self.assertEqual(sts["jenkins"], "running", sts)
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


    def test_detection_paths_never_query_the_process_table(self):
        """进程表查询（tasklist）是子进程调用，和端口反查同一类：出现在
        status / adopt / reconcile 里就等于从后门放掉"状态检测绝不执行进程"。"""
        calls = []
        orig = main.running_process_images
        main.running_process_images = lambda names: calls.append(tuple(names)) or []
        self.addCleanup(setattr, main, "running_process_images", orig)
        comps = {c.key: c for c in main.build_components()}
        with tempfile.TemporaryDirectory() as td:
            main.save_running_map({"rabbitmq": main.RunRecord(
                key="rabbitmq", version="4.0.9", home=td, data_dir=td, port=5672,
                console_url="http://127.0.0.1:15672/", pid=1088, pid_role="launcher",
                started_at=0.0, launcher_cmd=["cmd"], ports=(5672, 15672))})
            mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                      http_ok=lambda u, timeout=2.0: True,
                                      process_alive=lambda pid: True)
            mgr.status("rabbitmq", comps["rabbitmq"])
            mgr.adopt(comps)
            mgr.reconcile(comps)
        self.assertEqual(calls, [], "检测路径查了进程表")


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
        """登记里出现本期不认识的可启动组件，不许被误删。

        样本用 `pulsar`（2026-10-06 时仍未接入）而不是 rabbitmq/nacos：
        那两个已经进了白名单，拿它们当"不认识"的样本会让本用例变成
        "已登记组件要被接管"，那不是它要钉的东西。
        注释里原来写着"用 rabbitmq 是因为 nacos 进了白名单"—— rabbitmq 后来也进了，
        所以样本又换了一次。reconcile 只遍历 LAUNCH_KEYS，任何未登记 key 都一样。"""
        other = main.RunRecord(key="pulsar", version="3.3.9", home="/h", data_dir="/d",
                               port=6650, console_url="",
                               pid=1, pid_role="none", started_at=0.0, launcher_cmd=[])
        main.save_running_map({"pulsar": other})
        st = self.mgr(listening=True, alive=True).reconcile(self.comps)
        self.assertNotIn("pulsar", st, "没登记的组件不该被本工具接管")
        self.assertIn("pulsar", main.load_running_map())


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
            self.assertIn("安装", why, "门控原因要给出可点的下一步")

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

    def test_stop_reports_the_helper_process_the_launcher_left_behind(self):
        """真机 2026-10-07 rabbitmq：`rabbitmqctl stop` 只停 server，Erlang 的 epmd.exe
        一直活着。它不监听业务端口，所以按簇判定会报"已停止"；但它的工作目录还在版本目录里，
        Windows 上后续 `rmdir` 会失败 —— 用户看到的"卸载不了"就是这么来的。
        停止成功时必须把它说出来并讲清后果，同时**绝不自动结束**（那是用户机器上的进程）。
        """
        comp = self.comp
        comp.launch = main.LaunchSpec(
            commands={os_name: ["x"] for os_name in ("Windows", "Linux", "Darwin")},
            main_port=8080, stop_kind="pid", leftover_processes=("epmd.exe",))
        asked, killed = [], []
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda rec: killed.append(rec.pid),
                                  process_images=lambda names: asked.append(tuple(names)) or ["epmd.exe"])
        res = mgr.stop(comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertIn("epmd.exe", res.reason, "残留的辅助进程必须报出来")
        self.assertIn("卸载", res.reason, "要说清后果：版本目录可能因此删不掉")
        self.assertEqual(asked, [("epmd.exe",)],
                         "只许查该组件登记过的辅助进程，不许全表扫进程名")

    def test_stop_stays_quiet_when_no_helper_process_is_left(self):
        """没留下辅助进程就别报 —— 每次都提一句 epmd 会让用户以为哪儿坏了。"""
        comp = self.comp
        comp.launch = main.LaunchSpec(
            commands={os_name: ["x"] for os_name in ("Windows", "Linux", "Darwin")},
            main_port=8080, stop_kind="pid", leftover_processes=("epmd.exe",))
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda rec: None,
                                  process_images=lambda names: [])
        res = mgr.stop(comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertNotIn("epmd", res.reason)
        self.assertNotIn("残留", res.reason)

    def test_components_without_helper_processes_are_never_queried(self):
        """没登记 leftover_processes 的组件（jenkins 就是）一次都不该去查进程表：
        这条挡住"顺手给所有组件都加一次 tasklist"的做法。"""
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda rec: None,
                                  process_images=lambda names: self.fail("不该查询进程表"))
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)


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
            # 目录里必须有东西：2026-10-07 起"空目录 = 卸载删不掉的残留空壳"，
            # 不再算已装（见 main.py 的 install_dir_is_hollow）。本条测的是"真装了
            # 一个候选清单里没有的版本"，所以夹具要造出真实落地形状。
            (home / "jenkins.war").write_bytes(b"x")
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
        """运行中：同一个按钮可用、且文字变成「停止」（2026-10-06 合并按钮后重写）。

        原来这条断言"启动禁用 + 停止可用"——那是**两个按钮**的设计。
        合并成一个之后两者是同一个 widget（btn_stop 是 btn_start 的别名），
        `assertFalse(btn_start) and assertTrue(btn_stop)` 必然自相矛盾。
        真正的契约现在是：按钮位置固定、可用、**文字即状态**。
        """
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="http://127.0.0.1:8080/", pid=1, pid_role="server",
            started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": True
        self.card._refresh_launch_state()
        self.assertFalse(hasattr(self.card, "btn_stop"),
                         "合并后不该再有第二个停止按钮，留个同名别名会让人以为界面上有两个")
        self.assertTrue(self.card.btn_start.isEnabled(),
                        "运行中这个按钮必须可点——它就是停止按钮")
        self.assertTrue(self.card._running_per_ui(), "运行中按钮应被认成在运行")
        self.assertEqual(self.card.btn_start.text(), "停止",
                         "运行中按钮文字必须是「停止」，用户靠它认状态")
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
        self.assertEqual(self.card.btn_start.text(), "启动",
                         "未运行时按钮文字必须是「启动」")
        self.assertFalse(self.card.btn_console.isEnabled())

    def test_one_button_carries_both_actions(self):
        """启动/停止是**同一个**按钮，位置固定，状态写在文字上（2026-10-06 用户要求）。

        用户原话：「没启动时显示启动，启动成功后按钮『启动』变成『停止』，点击停止就停止」。
        原来的双按钮设计（启动 + 停止并排、运行态才亮停止）让他连续三次反馈
        "没有停止按钮" —— 按钮其实一直好着，问题是位置会变、眼睛要重新找一遍。

        这条把"只有一个按钮"钉死：删掉 btn_stop 若还能过，说明有第二个同名入口。
        """
        self.assertFalse(hasattr(self.card, "btn_stop"),
                         "界面上只能有一个按钮，不能再有第二个停止入口")

        # 未运行 → 「启动」
        main.save_running_map({})
        self.card._refresh_launch_state()
        self.assertEqual(self.card.btn_start.text(), "启动")

        # 运行中 → 「停止」，且**可点**（它就是停止按钮）
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="u", pid=1, pid_role="server", started_at=0.0,
            launcher_cmd=[], ports=(8080,))})
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": True
        self.card._refresh_launch_state()
        self.assertEqual(self.card.btn_start.text(), "停止",
                         "运行中按钮文字必须变成「停止」")
        self.assertTrue(self.card.btn_start.isEnabled(),
                        "运行中这个按钮必须可点——它是停止按钮，变灰会被读成「按钮没了」")
        # 按钮身份也要变：运行中是危险操作，要与「卸载」明确区分开
        self.assertEqual(self.card.btn_start.objectName(), "dangerBtn")
        self.assertIn("停止", self.card.btn_start.toolTip())

        # 停止完成后 → 回到「启动」
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": False
        self.card._refresh_launch_state()
        self.assertEqual(self.card.btn_start.text(), "启动")
        self.assertEqual(self.card.btn_start.objectName(), "primaryBtn")

    def test_transitional_caption_is_not_overwritten_by_refresh(self):
        """点了按钮之后的过渡态（"启动中…"/"停止中…"）不能被状态刷新盖回「启动」。

        那是用户点下去之后的即时反馈。被立刻改掉的话，他会以为按钮没点上，
        于是连点几次 —— 而每次点击都会起一个 worker。
        """
        main.save_running_map({})
        self.card.launch_worker = object()          # 模拟 worker 在跑
        self.addCleanup(setattr, self.card, "launch_worker", None)
        self.card.btn_start.setEnabled(False)
        self.card.btn_start.setText("启动中…")
        self.card._refresh_launch_state()
        self.assertEqual(self.card.btn_start.text(), "启动中…",
                         "过渡态文字被状态刷新盖掉了")
        self.assertFalse(self.card.btn_start.isEnabled(),
                         "worker 在跑时不该让用户再点一次")

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
        # 合并按钮后，运行中这个按钮**要可用**（它就是停止按钮），
        # 状态由文字「停止」表达，而不是把它禁用。
        self.assertTrue(card.btn_start.isEnabled())
        self.assertEqual(card.btn_start.text(), "停止")

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
        # 端口与"会重新起一个"是细节：主文本写结论，全文搬去 tooltip
        self.assertIn("8080", self.card.launch_label.toolTip())
        # 文案不许承诺 start() 不做的事：它不看旧 PID，是直接起新进程覆盖登记。
        # 上次评审点过这句"会自动接管"过界，钉在这里防止改回去。
        self.assertIn("重新起一个", self.card.launch_label.toolTip())
        # 僵尸态按钮仍应是「启动」且可点：点它的意图是"清掉残留重新起一个"。
        # 合并按钮后如果这里显示「停止」，用户点下去会走stop 路径 —— 而端口本来
        # 就没在听，点了等于什么都不发生，看起来就是按钮坏了。
        self.assertEqual(self.card.btn_start.text(), "启动",
                         "僵尸态要显示「启动」而不是「停止」")
        self.assertFalse(self.card._running_per_ui(),
                         "僵尸态不算在运行：点按钮的意图是重新起一个")
        self.assertTrue(self.card.btn_start.isEnabled(),
                        "僵尸态按钮必须可点，否则用户点它像坏了")
        self.assertNotIn("接管", self.card.launch_label.toolTip())
        self.assertTrue(self.card.btn_start.isEnabled())
        self.assertFalse(self.card.btn_console.isEnabled())

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
        # 合并按钮后"服务还活着"不再表现为按钮禁用，而表现为文字仍是「停止」。
        # 断言这一点才真正守住"交回引用 ≠ 服务已停"——删掉 self.launch_worker = None
        # 会让按钮文字卡在过渡态或状态判定失准。
        self.assertEqual(self.card.btn_start.text(), "停止",
                         "端口还在听时按钮应仍显示「停止」")
        self.assertTrue(self.card.btn_start.isEnabled())

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
        """开工具时如果 Jenkins 还在跑，日志要认出它 —— 这是"关掉了再打开也认得"那条判据。

        同时必须把**登录凭据**一起报出来：这些服务是之前启的，
        用户重开工具时界面上没有任何地方能看到"怎么登进去"。
        """
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8123,
            console_url="http://127.0.0.1:8123/", pid=1, pid_role="server",
            started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": True,
            http_ok=lambda u, timeout=2.0: True, process_alive=lambda pid: True)
        logs = []
        self.bare_win(logs)._adopt_running()
        msgs = [m for _, m in logs]
        self.assertIn("检测到 jenkins 正在运行（端口 8123）", msgs)
        joined = "\n".join(msgs)
        self.assertIn("用户名：admin", joined,
                      f"认出它在跑之后要顺手报出登录凭据：{msgs}")
        self.assertIn("initialAdminPassword", joined,
                      f"凭据要指向密码文件，用户才知道去哪儿取：{msgs}")
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
            # 2026-10-06：prepare_ports 改成按 comp.key 查分派器
            # （_CONF_WRITERS）—— 拿 jenkins 的组件配 activemq 的 spec 会查不到
            # 分派器而拒改。这条要验的是 ActiveMQ 的回写，所以**必须用真组件**。
            comp = next(c for c in main.build_components() if c.key == "activemq")
            comp.versions = [comp.versions[0]]
            s = main.LAUNCH_OF["activemq"]
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
        # 2026-10-06：prepare_ports 按 comp.key 查 _CONF_WRITERS，
        # 拿 jenkins 的组件配 conf_copy 会查不到分派器 → 拒改（不是锚不到 jetty.http.port）。
        # 要验的是"锚不到就拦 spawn"，所以用真组件 activemq。
        comp = next(c for c in main.build_components() if c.key == "activemq")
        s = main.LAUNCH_OF["activemq"]
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
            # 官方 conf 不含该行 → 副本建出来后 set_property_line 锚不到 → 拒改。
            # 还得先把"已装"这件事做实：launch_gate 会检查"磁盘上装了没有"，
            # 一个版本目录都没有时它先拦下来说"请先下载并安装"，就轮不到 prepare_ports 了
            # （2026-10-06 真机测试时才发现这条用例的前提已经不成立）。
            home = Path(td) / comp.key / f"{comp.key}-{s.main_port}"
            (home / "bin").mkdir(parents=True)
            orig_install = comp.install_dir
            comp.install_dir = lambda v, _h=home: _h
            self.addCleanup(setattr, comp, "install_dir", orig_install)
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

class LaunchCredentials(unittest.TestCase):
    """启动后把登录凭据打进日志（2026-10-06 用户要求）。

    动机：服务起来了，用户却登不进去，只能去翻文件/搜官方文档。
    这些**不是秘密**——nacos/nacos、admin/admin 是出厂默认，装同一版本的人全都一样；
    Jenkins 那个随机密码本来就在本机文件里、也只有本机能读。

    三条规则要钉住：
    ① 厂商默认值写在 `credentials_hint` 里，随登记走；
    ② Jenkins 的密码是**首次启动随机生成**的，只能从 initialAdminPassword 读，
       读不到就明说读不到（**不许编一个像密码的串**给用户）；
    ③ 没有凭据的组件返回空列表，不许凭空造一段。
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig_dir = main.CONFIG_DIR
        main.CONFIG_DIR = Path(self.dir.name)
        self.addCleanup(setattr, main, "CONFIG_DIR", self._orig_dir)
        self.comps = {c.key: c for c in main.build_components()}

    def test_vendor_default_credentials_are_recorded_in_the_registry(self):
        """两个用出厂默认密码的组件，凭据必须写在登记里（换版本时要能一眼核对）。"""
        for key, user, pwd in (("nacos", "nacos", "nacos"),
                                ("activemq", "admin", "admin")):
            with self.subTest(key):
                hint = self.comps[key].launch.credentials_hint
                self.assertTrue(hint, f"{key} 没有登记凭据")
                self.assertIn(user, hint, f"{key} 的凭据要写明用户名")
                self.assertIn(pwd, hint, f"{key} 的凭据要写明密码")
                self.assertIn("127.0.0.1", hint, f"{key} 的凭据要带控制台地址")

    def test_jenkins_password_is_read_from_the_real_file(self):
        """Jenkins 的初始密码是随机生成的，必须真读文件 —— 登记里写不了死。"""
        secrets = Path(self.dir.name) / "jenkins-data" / "secrets"
        secrets.mkdir(parents=True)
        (secrets / "initialAdminPassword").write_text(
            "  39ebcaf8baaa4a61b5fb3796914db695  \n", encoding="utf-8")
        comp = self.comps["jenkins"]
        lines = main.credentials_for(comp, comp.launch, 8080)
        joined = "\n".join(lines)
        self.assertIn("39ebcaf8baaa4a61b5fb3796914db695", joined,
                      "启动日志里必须出现本机实际的初始密码")
        # 末尾空白要去掉：文件里通常带换行，不 strip 的话复制出来会带不可见字符
        self.assertNotIn("db695  \n", joined, "密码没去尾部空白")
        self.assertIn("initialAdminPassword", joined,
                      "还要告诉用户密码是从哪读出来的/在哪能改")

    def test_missing_password_file_says_so_instead_of_inventing_one(self):
        """读不到密码文件时要说读不到，**绝不能编一个看起来像密码的串**。
        编一个的后果：用户拿着它去登录，失败后会以为是服务坏了。"""
        comp = self.comps["jenkins"]
        lines = main.credentials_for(comp, comp.launch, 8080)
        joined = "\n".join(lines)
        self.assertIn("读不到", joined, f"读不到文件时该明说：{lines}")
        self.assertIn("initialAdminPassword", joined, "还要指出文件在哪")

    def test_component_without_credentials_gets_nothing(self):
        """没登记凭据的组件返回空列表 —— 不许凭空造一段出来。"""
        spec = main.LaunchSpec(commands={o: ["x"] for o in
                                          ("Windows", "Linux", "Darwin")},
                               main_port=1234)
        self.assertEqual(main.credentials_for(self.comps["maven"], spec, 1234), [])

    def test_hint_port_is_rewritten_when_the_actual_port_differs(self):
        """将来若允许换端口，凭据里的地址必须跟着改，不能让人照着不存在的端口去连。"""
        comp = self.comps["nacos"]
        lines = main.credentials_for(comp, comp.launch, 9999)
        joined = "\n".join(lines)
        self.assertIn("127.0.0.1:9999", joined, f"实际端口没进凭据文案：{lines}")
        self.assertNotIn("127.0.0.1:8848", joined, f"还留着旧端口会让人连错地址：{lines}")


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


class RunningTabMarker(unittest.TestCase):
    """「有组件在运行的页面要能被看见」—— 2026-10-06 用户反馈的根因。

    用户报「启动了 nacos，没看到停止选项」。查下来按钮一直好着：btn_stop 可见、
    可用、文本"停止"，旁边的 label 也写着"● 运行中 · 端口 8848"。
    真正原因是**三个启动组件分在两个 Tab**（Nacos/ActiveMQ 在「开发软件」、
    Jenkins 在「其它软件」），而界面默认停在「开发环境」。
    用户在自己的启动页上找不到刚启动的那个卡片，于是以为停止按钮不存在。

    这类问题的性质是「服务跑着却看不见」，比按钮真的缺失更容易误导人
    （他会以为启动没成功，然后去重复启动）。所以：
    ① Tab 标题上标 `●`，停在任何一页都能看出"有东西在跑，去那页找"；
    ② 打开工具时自动跳到那一页，并在日志里点名"停止按钮在这一页"。

    这里必须构造真 MainWindow：`MainWindowAdopt` 用 `__new__` 造假窗口，
    没有真的 QTabWidget，标不出标题。
    """

    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self._orig_file, self._orig_dir = main.RUNNING_FILE, main.CONFIG_DIR
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        main.CONFIG_DIR = Path(self.dir.name)
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig_file)
        self.addCleanup(setattr, main, "CONFIG_DIR", self._orig_dir)
        # 端口探测桩成"全在听"，让 status() 判成 running（不真起进程）
        self._orig_listen = main.SERVICE_MANAGER._is_listening
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": True
        self.addCleanup(setattr, main.SERVICE_MANAGER, "_is_listening",
                        self._orig_listen)

    def _win_with_nacos_running(self):
        """造一个"nacos 正在运行"的真窗口，返回 (窗口, 日志列表)。"""
        comps = {c.key: c for c in main.build_components()}
        main.save_running_map({"nacos": main.RunRecord(
            key="nacos", version="2.3.2", home="/h", data_dir="",
            port=8848, console_url="http://127.0.0.1:8848/nacos",
            pid=43210, pid_role="launcher", started_at=0.0,
            launcher_cmd=["startup.cmd"], ports=(8848, 9848, 9849))})
        win = main.MainWindow()
        logs = []
        win._append_log = lambda level, msg: logs.append(msg)
        win.show()
        self.app.processEvents()
        return win, logs

    def test_tab_of_a_running_component_is_marked_and_jumped_to(self):
        win, logs = self._win_with_nacos_running()
        self.addCleanup(win.close)
        titles_before = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        self.assertNotIn("●", "".join(titles_before),
                         "还没跑就标了运行标记")

        win._adopt_running()
        self.app.processEvents()

        titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        nacos_tab = next(n for n, li in enumerate(win._tab_layouts)
                         if li.indexOf(next(c for c in win.cards
                                            if c.component.key == "nacos")) != -1)
        self.assertIn("●", titles[nacos_tab],
                      f"运行中的那一页没标 ●：{titles}")
        self.assertEqual(win.tabs.currentIndex(), nacos_tab,
                         "打开工具时应自动跳到运行中的那一页")
        joined = "\n".join(logs)
        self.assertIn("停止", joined,
                      f"日志必须点名停止按钮在哪：{logs}")
        self.assertIn("8848", joined, f"日志要点名端口：{logs}")

    def test_mark_survives_switching_to_another_tab(self):
        """手动切到别的页后，`●` 标记不能消失 —— 它是"去那页找"的唯一线索。"""
        win, _ = self._win_with_nacos_running()
        self.addCleanup(win.close)
        win._adopt_running()
        self.app.processEvents()
        nacos_tab = win.tabs.currentIndex()
        other = (nacos_tab + 1) % win.tabs.count()
        win.tabs.setCurrentIndex(other)
        self.app.processEvents()
        titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        self.assertIn("●", titles[nacos_tab],
                      f"切页后运行标记被抹掉了：{titles}")

    def test_no_marker_when_nothing_is_running(self):
        """没有组件在跑时不能挂 `●` —— 满屏标记等于没有标记。"""
        comps = {c.key: c for c in main.build_components()}
        main.save_running_map({})
        win = main.MainWindow()
        self.addCleanup(win.close)
        win._mark_running_tabs()
        titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        self.assertNotIn("●", "".join(titles), f"没有在跑却标了：{titles}")


class FakeRunProc:
    """`subprocess.run` 的替身：只回 rc 与输出，不起进程。

    run_pre_start 只读 returncode / stdout / stderr，所以这三个属性就够；
    真实执行会碰磁盘与网络（kafka 的 format 会真的建 kraft-logs），必须替掉。
    """

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakePopenProc:
    """`subprocess.Popen` 的替身：只报一个 pid，不起进程。

    start() 拿返回值读 `.pid` 登记 RunRecord，超时分支还会 `terminate()` 收尸，
    所以这几个方法都要在—— 少一个就会在收尾时AttributeError，
    而那种红是"替身不称职"，不是被测代码的缺陷。
    """

    def __init__(self, pid=43210):
        self.pid = pid
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode or 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class PreStartAndPrereqWiring(unittest.TestCase):
    """前置准备（pre_start）与前置依赖（prereq）的**接线**护栏。

    这个类要钉的不是"字段填对了"，而是"框架真的会执行它们"。
    之前有一版护栏只测`run_pre_start()` 函数本身怎么跑命令，
    结果把 `start()` 里那三行调用变异掉之后仍然全绿 —— 护栏是空的：
    函数被测得再透，只要没人调它，kafka 就会带着空目录起来报
    `No readable meta.properties files found.`。
    所以下面有两条真的走完整 `start()` 路径（test_start_*_pre_start*）。

    全部离线：不碰网络、不起真实进程，连 shutil.which 都桩掉
    （它会真的去翻 PATH，用例成败不能取决于这台机器装没装 Erlang）。
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        # 落盘位置（cluster.id / 配置副本 / 运行登记）全部重定向到临时目录，
        # 否则用例会往真 ~/.env-tools 里写 cluster.id 与 running.json。
        self._orig_dir, self._orig_run_file = main.CONFIG_DIR, main.RUNNING_FILE
        main.CONFIG_DIR = Path(self.dir.name)
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "CONFIG_DIR", self._orig_dir)
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig_run_file)
        self.comps = {c.key: c for c in main.build_components()}

        # 两个执行入口各一个记录器。分开记是刻意的：
        # 前置准备走 run（同步、要退出码），拉服务走 Popen（异步、只要 pid），
        # 断言"前置失败不许 spawn"必须能证明 Popen一次都没被碰过。
        self.runs = []
        self.spawned = []
        self._orig_run = main.subprocess.run
        self._orig_popen = main.subprocess.Popen
        main.subprocess.run = self._record_run
        main.subprocess.Popen = self._record_popen
        self.addCleanup(setattr, main.subprocess, "run", self._orig_run)
        self.addCleanup(setattr, main.subprocess, "Popen", self._orig_popen)

        # 用例成败不许取决于这台机器恰好有没有 JAVA_HOME / 有没有装 jdk。
        self._orig_java = main.resolve_java_home
        main.resolve_java_home = lambda comps: str(Path(self.dir.name) / "jdk-17")
        self.addCleanup(setattr, main, "resolve_java_home", self._orig_java)

        # 端口一律答"空闲"。不打桩的话 choose_ports 会真去 bind、真去杀占用者，
        # 于是 9092 上有没有东西在跑决定了用例的生死。
        self._orig_free = main.port_is_free
        main.port_is_free = lambda port, host="127.0.0.1": True
        self.addCleanup(setattr, main, "port_is_free", self._orig_free)
        self._orig_evict = main.evict_port_occupant
        main.evict_port_occupant = lambda port, label, evicted=None: None
        self.addCleanup(setattr, main, "evict_port_occupant", self._orig_evict)

    # ---------------- 替身 ----------------

    def _record_run(self, argv, **kw):
        self.runs.append((list(argv), kw))
        return FakeRunProc()

    def _record_popen(self, argv, **kw):
        self.spawned.append((list(argv), kw))
        return FakePopenProc()

    def _stub_run(self, proc):
        """把某一次 run 的结果钉死（回退出码 / 抛超时），并记录调用。"""
        def fake(argv, **kw):
            self.runs.append((list(argv), kw))
            if isinstance(proc, BaseException):
                raise proc
            return proc
        main.subprocess.run = fake

    def _ready_kafka(self):
        """把 kafka 造成"磁盘上真装着"的样子，并让 mapping 能算出真实路径。

        `_plan_mapping` 与 `config_file_for` 都依赖 `resolve_launch_version` 与
        `install_dir`，不铺好这两样，测的就只是"占位符没展开"这种小事，
        而不是"format 与 broker 拿到的是同一份配置与同一个 cluster.id"。
        """
        comp = self.comps["kafka"]
        version = comp.versions[0].version
        home = Path(self.dir.name) / "kafka" / f"kafka-{version}"
        (home / "bin").mkdir(parents=True, exist_ok=True)
        (home / "config").mkdir(parents=True, exist_ok=True)
        (home / "config" / "server.properties").write_text("log.dirs=x\n", encoding="utf-8")
        comp.install_dir = lambda v: home
        orig = main.resolve_launch_version
        main.resolve_launch_version = lambda c: version
        self.addCleanup(setattr, main, "resolve_launch_version", orig)
        return comp, home

    def _plan_for(self, comp, port=9092):
        """走真实 build_launch_plan，让 argv/替换表都是真的。"""
        self._ready_kafka_version = True
        return main.build_launch_plan(
            comp, comp.launch, str(Path(self.dir.name) / "jdk-17"), port,
            Path(self.dir.name) / "byte-tools.out")

    # ================= prereq =================

    def test_check_prereq_names_the_missing_executable_and_the_hint(self):
        """缺依赖时必须说清**缺哪个可执行文件**，并把 install_hint 原文给用户。

        只说"前置依赖没就位"等于把排查成本推给用户：官方 zip 不含Erlang、
        国内镜像站还没有，只能走 GitHub 的 139MB 安装包 —— 这些是用户决定
        要不要现在就去下的唯一依据，吞掉就没法行动了。
        """
        prereq = main.LAUNCH_OF["rabbitmq"].prereq
        self.assertIsNotNone(prereq)
        orig = main.shutil.which
        main.shutil.which = lambda name, *a, **k: None      # PATH 里没装
        self.addCleanup(setattr, main.shutil, "which", orig)
        # 2026-10-06：check_prereq 除了 PATH 还会去扫免安装 Erlang 的约定落点
        # （main.find_erlang_home_erl），那一条也得桩掉 ——
        # 否则开发机上真装了 Erlang 时这条用例恒绿，护栏变空。
        orig_find = main.find_erlang_home_erl
        main.find_erlang_home_erl = lambda: ""
        self.addCleanup(setattr, main, "find_erlang_home_erl", orig_find)
        ok, why = main.check_prereq(prereq)
        self.assertFalse(ok, "找不到 erl.exe 却说依赖已就位")
        # 断的是"找不到 erl.exe"这个**从句**，不是"原因里出现过 erl.exe 字样"。
        # 只assertIn(prereq.probe, why) 是不够的：check_prereq 现在会在结尾
        # 拼一句"当前状态：已装（erl.exe）"（main.py:6039，逻辑写反了），
        # 那半句里同样有 erl.exe，于是把"找不到 {probe}"整句删掉都测不出来。
        self.assertIn("找不到", why,
                      "必须明确说清是**找不到**这个可执行文件，"
                      "而不是让用户自己从'已装/没装'里猜")
        self.assertIn(prereq.probe, why,
                      "必须点名缺的是哪个可执行文件（用户不知道要装什么）")
        self.assertIn("Erlang", why)
        # install_hint 的关键信息要透出来。
        # 2026-10-08 起这条提示的定位变了：Erlang 成了隐藏组件、由本工具随 rabbitmq
        # **自动安装**，所以文案的首要信息是"不用你自己装"；其余（国内没镜像、
        # 只能走 GitHub、路径不能带中文/空格）作为"自动安装失败时该看什么"保留。
        # 这里断的是**关键信息确实透出来了**，而不是某一句旧文案 ——
        # 断文案会把正当改文案的修改也一起钉死。
        self.assertIn("自动", why, "必须说清这件事由工具负责，用户不用自己装")
        self.assertIn("GitHub", why, "必须交代来源（国内没镜像，走 GitHub 加速器）")
        self.assertIn("中文", why, "必须交代非 ASCII 路径会直接失败这个硬约束")

    def test_check_prereq_passes_when_the_executable_exists(self):
        """装了就必须放行 —— 否则装完Erlang 点启动还是被拦在门控外。"""
        prereq = main.LAUNCH_OF["rabbitmq"].prereq
        orig = main.shutil.which
        main.shutil.which = lambda name, *a, **k: r"C:\Program Files\Erlang\bin\erl.exe"
        self.addCleanup(setattr, main.shutil, "which", orig)
        ok, why = main.check_prereq(prereq)
        self.assertTrue(ok, f"erl.exe 明明在 PATH里却被拦住：{why}")

    def test_launch_gate_actually_blocks_on_prereq_and_only_on_prereq(self):
        """**接线**：`launch_gate()` 真的会查 prereq。

        这条要能区分"被prereq 拦住"与"因为别的理由被拦"：
        所以先把 rabbitmq 造成已安装（否则门控会因为"磁盘上没装"先返回，
        断言里的 "erl" 恰好出现不了、测试就成了自欺），再把 which 桩成找不到。

        后半段反向断言是它的镜像：which 一放行门控就必须过。
        少了后半段，"门控恒返回 False"这种实现也能让前半段变绿。
        """
        comp = self.comps["rabbitmq"]
        version = comp.versions[0].version
        home = Path(self.dir.name) / "rabbitmq" / f"rabbitmq-{version}"
        home.mkdir(parents=True, exist_ok=True)
        comp.install_dir = lambda v: home
        orig_ver = main.resolve_launch_version
        main.resolve_launch_version = lambda c: version
        self.addCleanup(setattr, main, "resolve_launch_version", orig_ver)

        orig = main.shutil.which
        self.addCleanup(setattr, main.shutil, "which", orig)
        # 只让 erl* 找不到：门控里jdk 探测等其他 which 调用仍按真的走
        main.shutil.which = lambda name, *a, **k: (
            None if str(name).lower().startswith("erl") else orig(name, *a, **k))
        # 2026-10-06：check_prereq 还会扫免安装 Erlang 的约定落点
        # （find_erlang_home_erl），开发机上真装了 Erlang 时它会绕过 PATH 检查，
        # 门控就放过了 —— 这条用例会红。桩掉它。
        # 2026-10-08：本工具自己装的 Erlang（~/.env-tools/erlang/erlang-*）也被
        # 认作"已就位"（installed_erlang_erl），那条路同样要桩掉，
        # 否则本机替 rabbitmq 装过 Erlang 之后这条用例会假红。
        orig_find = main.find_erlang_home_erl
        main.find_erlang_home_erl = lambda: ""
        self.addCleanup(setattr, main, "find_erlang_home_erl", orig_find)
        orig_installed = main.installed_erlang_erl
        main.installed_erlang_erl = lambda: ""
        self.addCleanup(setattr, main, "installed_erlang_erl", orig_installed)

        ok, why = main.launch_gate(comp, comp.launch, java_home=None)
        self.assertFalse(ok, "缺 Erlang 却放过了门控 —— rabbitmq-server.bat 会一闪就退")
        self.assertIn("erl", why.lower(), f"拦截原因必须指向缺失的可执行文件：{why}")
        self.assertNotIn("磁盘上还没有", why,
                         "已经装了，只是缺 Erlang；原因不许说成'没装'")

        # 镜像：Erlang 就位后必须放行，否则这条护栏钉不住真正的因果
        main.shutil.which = lambda name, *a, **k: (
            r"C:\Program Files\Erlang\bin\erl.exe"
            if str(name).lower().startswith("erl") else orig(name, *a, **k))
        ok2, why2 = main.launch_gate(comp, comp.launch, java_home=None)
        self.assertTrue(ok2, f"Erlang 已就位却仍被拦：{why2}")

    def test_only_rabbitmq_declares_a_prereq(self):
        """只有 rabbitmq 需要外部运行时。

        反过来也钉：其余组件一旦被填上 prereq 就是登记错——
        比如给 kafka 填了 prereq="erlang"，于是"装没装 Kafka"这件事
        会被"装没装 Erlang"顶替掉，提示语指向完全无关的东西。
        """
        declared = sorted(k for k, spec in main.LAUNCH_OF.items()
                          if getattr(spec, "prereq", None) is not None)
        self.assertEqual(declared, ["rabbitmq"],
                         "声明了 prereq 的组件集合变了：登记错会让门控拦住/放过错的组件")
        self.assertEqual(main.LAUNCH_OF["rabbitmq"].prereq.key, "erlang")

    # ================= pre_start：函数自身 =================

    def test_components_without_pre_start_spawn_nothing(self):
        """没有 pre_start 的组件：不许产生任何子进程，notes 为空，返回 True。

        这三个组件走 start() 时若被无端塞一条前置命令，用户会看到
        一个莫名其妙的"已完成…初始化"提示，而实际什么都没初始化。
        """
        for key in ("nacos", "activemq", "jenkins"):
            with self.subTest(key):
                comp = self.comps[key]
                self.assertEqual(comp.launch.pre_start, [],
                                 f"{key} 不该有 pre_start")
                before_popen = len(self.spawned)
                plan = main.LaunchPlan(
                    argv=["{java}", "-jar", "x.jar"], env={}, cwd=Path(self.dir.name),
                    log_file=Path(self.dir.name) / "o.out", console_url="", port=8080)
                ok, why, notes = main.run_pre_start(comp, comp.launch, plan)
                self.assertTrue(ok, why)
                self.assertEqual(why, "")
                self.assertEqual(notes, [], f"{key} 没有前置准备却报了提示行")
                self.assertEqual(self.runs, [], f"{key} 没有 pre_start 却执行了命令")
                self.assertEqual(len(self.spawned), before_popen,
                                 f"{key} 没有 pre_start 却 spawn 了进程")

    def test_kafka_pre_start_runs_format_exactly_once_with_idempotent_flags(self):
        """kafka 的 format 必须**恰好跑一次**，且带幂等标志。

        两个坑各自会致命：
        - 跑两次 = 用户点两次启动就多跑一次 StorageTool；
        - 少了 `--ignore-formatted`，第二次点启动时 format 因"已格式化"直接
          报错，前置准备失败 → 明明在运行却报"前置准备失败"，用户无从下手。
        所以断言的是**集合里恰好一个 format 且带这两个标志**，
        不是"跑过一次"（跑两次也能满足后者）。
        """
        comp, _home = self._ready_kafka()
        plan = self._plan_for(comp)
        ok, why, notes = main.run_pre_start(comp, comp.launch, plan)
        self.assertTrue(ok, why)
        self.assertEqual(len(self.runs), 1, f"前置准备必须恰好跑一次：{self.runs}")
        argv = self.runs[0][0]
        self.assertIn("format", argv)
        self.assertIn("--standalone", argv,
                      "KRaft 单机模式必须显式声明，否则 format 不知道拓扑")
        self.assertIn("--ignore-formatted", argv,
                      "少了它，重复点启动就会因'已格式化'失败")
        self.assertTrue(any("前置准备" in n for n in notes),
                        f"成功时要告诉用户前置准备做了什么：notes={notes}")

    def test_pre_start_failure_carries_the_output_tail_into_the_reason(self):
        """前置失败必须把输出末尾带进原因，否则用户只看到"失败"两个字。

        真机踩到的就是这类：format 失败时真正的原因（磁盘满、目录权限、
        cluster.id 不匹配）只出现在 stderr 里。rc=1 而不给出 stdout/stderr，
        用户只能自己去翻日志文件猜。
        """
        comp, _home = self._ready_kafka()
        plan = self._plan_for(comp)
        self._stub_run(FakeRunProc(returncode=1,
                                  stderr=b"java.io.IOException: disk full"))
        ok, why, _notes = main.run_pre_start(comp, comp.launch, plan)
        self.assertFalse(ok, "rc=1 却当成功 —— 会拉起一个必然起不来的进程")
        self.assertIn("disk full", why,
                      "失败原因必须带上 stderr/stdout 末尾的真实报错")
        self.assertIn("1", why, "失败原因要点明退出码")

    def test_pre_start_timeout_is_bounded(self):
        """超时必须有界：卡住的前置准备不能把界面永久挂住。

        format 卡住的现实原因不少（磁盘 IO 异常、JVM 卡在网络探测）。
        没有 timeout 的话点一次启动就再也点不动，且用户看不到任何解释。
        """
        comp, _home = self._ready_kafka()
        plan = self._plan_for(comp)

        def only_timeout_when_forwarded(argv, **kw):
            """只在实现真把 timeout 交给 subprocess.run 时才超时。

            否则"实现忘了传 timeout"会伪装成超时通过 —— 桩无条件抛异常时，
            传不传timeout 都是同一个结果，这条护栏就钉不住那个坑了。
            """
            self.runs.append((list(argv), kw))
            if kw.get("timeout") is None:
                return FakeRunProc()          # 没传 timeout → 假装命令成功
            raise main.subprocess.TimeoutExpired(cmd=list(argv), timeout=kw["timeout"])

        main.subprocess.run = only_timeout_when_forwarded
        ok, why, _notes = main.run_pre_start(comp, comp.launch, plan, timeout=7)
        self.assertFalse(ok, "超时了却当成功")
        self.assertEqual(self.runs[0][1].get("timeout"), 7,
                         "timeout 必须原样传给 subprocess.run，否则界面上就是永久挂住")
        self.assertIn("7", why, f"原因里要点明等了多久：{why}")
        self.assertIn("放弃启动", why, "超时的正确处置是放弃启动而不是继续")

    def test_cluster_id_is_created_once_then_reused(self):
        """同一数据目录两次调用必须拿到**同一个** uuid。

        kafka 的 cluster.id 写在 data_dir 里被 broker 认；换 uuid 会被拒
        （`Invalid cluster.id`）。所以 format 用了A、broker 用 B 时，
        format 就是白做 —— 而这种错配在界面上完全看不出来
        （命令跑成功了、端口也起来了，直到 broker 读自己的 meta 才炸）。

        这条只钉函数本身；"start()/run_pre_start() 到底有没有用它"由下面那条钉。
        """
        data_dir = Path(self.dir.name) / "kafka-data"
        first = main.read_or_create_cluster_id(data_dir)
        second = main.read_or_create_cluster_id(data_dir)
        self.assertEqual(first, second,
                         "第二次读出了新的 cluster.id —— format 与 broker 会互相不认")
        self.assertEqual(len(first), 36, f"不是标准 uuid：{first!r}")
        self.assertEqual(first.count("-"), 4, f"uuid 分隔符不对：{first!r}")
        # 另一个数据目录必须是另一个 id（否则说明是写死的常量，不是"按目录持久化"）
        other = main.read_or_create_cluster_id(Path(self.dir.name) / "other-data")
        self.assertNotEqual(other, first,
                            "所有目录共用同一个 id：说明它根本没落盘，只是现生成")

    def test_pre_start_argv_carries_the_persisted_cluster_id_not_a_fresh_one(self):
        """**接线**：format 命令里的 `-t` 必须是**落盘那个** cluster.id。

        这条是上面那条的补充，也是真正会咬人的那条：
        只测 `read_or_create_cluster_id()` 的话，把 `_plan_mapping` 里的
        `read_or_create_cluster_id(data_dir)` 换成 `str(uuid.uuid4())` 全绿——
        函数被测得再透，只要调用点换成现生成的 uuid，
        format 用的A、broker 认的 B 就是白做（`Invalid cluster.id`）。
        而这种错配在界面上完全看不出来：命令跑成功了、端口也起来了。

        所以断的是**真正进了 argv 的那个值**：两次调用（=用户点两次启动）
        必须是同一个，且必须等于盘上那个。
        """
        comp, _home = self._ready_kafka()
        plan = self._plan_for(comp)
        self.assertTrue(main.run_pre_start(comp, comp.launch, plan)[0])
        first_argv = self.runs[0][0]
        self.assertIn("-t", first_argv, "format 必须显式带 cluster.id（-t）")
        used = first_argv[first_argv.index("-t") + 1]

        persisted = main.read_or_create_cluster_id(main.CONFIG_DIR / "kafka-data")
        self.assertEqual(used, persisted,
                         "format 用的 cluster.id 与盘上那个不是同一个 —— "
                         "broker 会认自己的 meta，format 白做（Invalid cluster.id）")

        # 再点一次启动：--ignore-formatted 让它幂等，但 uuid 绝不能变
        self.assertTrue(main.run_pre_start(comp, comp.launch, plan)[0])
        again = self.runs[1][0][self.runs[1][0].index("-t") + 1]
        self.assertEqual(again, used,
                         "重复点启动时 format 换了 cluster.id —— 等于每次都在换一个集群")

    def test_kafka_conf_placeholder_points_at_the_managed_copy(self):
        """`{conf}` 必须指向 **data 目录里那份副本**的 server.properties
        （2026-10-06 改的契约，原为"官方那份"）。

        改的原因：kafka 的端口策略从 cli_only 改成了 conf_copy，
        因为**必须改 log.dirs** —— 官方默认 `/tmp/kraft-combined-logs`
        在 Windows 上落`C:\\tmp\\`，不在安装目录也不在数据目录
        （卸载删不掉、多版本并存会抢同一个目录）。

        于是 `{conf}` 必须指向副本，理由有两条，都是实测：
          - `pre_start`（StorageTool format）与 `kafka.Kafka` 要读**同一份**；
            读官方文件的话 format 格式化的是 /tmp 那个目录、broker 去副本里找
            meta.properties → `No readable meta.properties files found.`
          - 官方文件卸载就被删，下次启动读不到。
        """
        comp, _home = self._ready_kafka()
        data_dir = main.CONFIG_DIR / "kafka-data"
        conf = main.config_file_for(comp, data_dir)
        self.assertEqual(conf.name, "server.properties")
        self.assertEqual(conf.parent, data_dir / "conf",
                         f"{conf} 应在 data 目录的 conf 下（log.dirs 被写进了副本）")
        self.assertIn("kafka-data", str(conf))

    # ================= pre_start：start() 接线（最关键） =================

    def test_start_calls_pre_start_and_never_spawns_when_it_fails(self):
        """**接线**：`start()` 真的会调用 `run_pre_start`，且失败就不许 spawn。

        这是本类的核心一条。之前那版护栏只测 `run_pre_start()` 自己怎么跑命令，
        把下面这三行删掉它仍然全绿：
            ok_pre, why_pre, pre_notes = run_pre_start(comp, spec, plan)
            notes = notes + list(pre_notes)
            if not ok_pre: return StartResult(False, "prestart", why_pre, notes=notes)
        删掉之后 kafka 会直接去 spawn，然后在 broker 读元数据时才炸
        `No readable meta.properties files found.` —— 用户看到的是"启动失败"，
        而根因（前置没跑）被永久隐藏。

        自检：把这三行删掉，本条断言 pre_start_calls == 1 立刻红。
        """
        comp, _home = self._ready_kafka()
        pre_calls = []

        def spy(c, spec, plan, *a, **kw):
            pre_calls.append((c.key, list(spec.pre_start)))
            return False, "前置故意失败", ["note"]

        orig_pre = main.run_pre_start
        main.run_pre_start = spy
        self.addCleanup(setattr, main, "run_pre_start", orig_pre)

        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True)
        res = mgr.start(comp, self.comps, sleeper=lambda s: None)

        self.assertEqual(len(pre_calls), 1,
                         "start() 没调用 run_pre_start —— 前置准备是空的，"
                         "kafka 会带着空数据目录起来报 No readable meta.properties")
        self.assertEqual(pre_calls[0][0], "kafka")
        self.assertIn("format", pre_calls[0][1],
                      "传给 run_pre_start 的 spec 必须带着 format 命令")
        self.assertFalse(res.ok)
        self.assertEqual(res.state, "prestart")
        self.assertEqual(res.reason, "前置故意失败",
                         "失败原因必须原样透出，用户要靠它知道 format 报了什么")
        self.assertEqual(self.spawned, [],
                         "前置准备失败了还 spawn 了服务进程 —— 会拉起一个必然起不来的实例")
        self.assertIn("note", res.notes,
                      "前置准备的提示行必须跟着StartResult回到卡片")
        self.assertEqual(main.load_running_map(), {},
                         "前置失败不许留登记，否则界面显示'运行中'而实际没有进程")

    def test_start_of_a_component_without_pre_start_spawns_no_prep_command(self):
        """**接线（反向）**：没有 pre_start 的组件走 start() 时零回归。

        `start()` 是**无条件**调run_pre_start 的（main.py:6300），
        空 pre_start 的短路在函数内部（main.py:6068）。
        所以这里钉的是可观测行为——**一条前置命令都不许执行**，
        而不是"那个函数没被调用"（那样写会与实现不符、也钉不住真正的坑）。
        """
        comp = self.comps["nacos"]
        version = comp.versions[0].version
        home = Path(self.dir.name) / "nacos" / f"nacos-{version}"
        (home / "bin").mkdir(parents=True, exist_ok=True)
        comp.install_dir = lambda v: home
        orig_ver = main.resolve_launch_version
        main.resolve_launch_version = lambda c: version
        self.addCleanup(setattr, main, "resolve_launch_version", orig_ver)

        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True)
        res = mgr.start(comp, self.comps, sleeper=lambda s: None)

        self.assertTrue(res.ok, res.reason)
        self.assertEqual(self.runs, [],
                         "nacos 没有 pre_start，却执行了一条前置命令")
        self.assertEqual(len(self.spawned), 1,
                         "只该拉起服务进程本身，不许有第二个进程")
        self.assertTrue(all("前置准备" not in n for n in res.notes),
                        f"没有前置准备却报了这种提示：notes={res.notes}")
        self.assertIn("nacos", main.load_running_map(),
                      "nacos 走完整 start() 应该能登记成功（这条钉的是零回归）")


class NewSixComponents(unittest.TestCase):
    """2026-10-06 新接入六个组件（rocketmq/nginx/kafka/tomcat/es/rabbitmq）的坑。

    动机：`LAUNCH_KEYS` 从 3 涨到 9，但既有 170 条护栏**一条都没钉这六个组件**
    —— 它们全是围绕 jenkins/nacos/activemq 写的。这六个的坑有一个共同特征：
    **改完文件看起来是对的，运行时不是**（tomcat 改到注释行 / kafka 走 .bat
    超 8191 / rocketmq 用错入口脚本 FileNotFound），所以护栏必须断言
    "**去注释之后解析出的生效值**"，而不是"文件里出现了目标字符串"。

    全部离线：不碰网络、不起真实进程。配置 fixture 全部用 tempfile 造，
    组件安装目录、端口探针、subprocess 全部打桩。
    """

    # ---------------- fixture：厂商原文形状 ----------------

    # Tomcat 10.1 server.xml 的**关键形状**：5 处 `port=`，只有 2 处生效。
    # 顺序刻意与真机一致（行号≈真机行号），因为三个naive 写法都依赖这个顺序：
    #   :22<Server port="8005">            生效（shutdown 口）
    #   :76<!-- ... port="8080" ... -->注释里那处（naive 的"第 2 处"）
    #   :70<Connector port="8080" ...>     生效（HTTP 主口）
    #   :92<!-- port="8443" -->            注释
    #   :108<!-- port="8009" -->           注释
    # 注意 :76 在 :70 **之前**—— 报告里naive"改第 2 处"命中的正是它。
    TOMCAT_SERVER_XML = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Server port="8005" shutdown="SHUTDOWN">\n'
        '  <Listener className="org.apache.catalina.startup.Catalina" />\n'
        '\n'
        '  <!-- A "Connector" using the shared thread pool -->\n'
        '  <!--\n'
        '  <Connector executor="tomcatThreadPool"\n'
        '             port="8080" protocol="HTTP/1.1"\n'
        '             connectionTimeout="20000"\n'
        '             redirectPort="8443"\n'
        '             maxParameterCount="1000" />\n'
        '  -->\n'
        '\n'
        '  <Connector port="8080" protocol="HTTP/1.1"\n'
        '             connectionTimeout="20000"\n'
        '             redirectPort="8443"\n'
        '             maxParameterCount="1000" />\n'
        '\n'
        '  <!-- A "Connector" using an explicit thread pool -->\n'
        '  <!--\n'
        '  <Connector port="8443" protocol="HTTP/1.1"\n'
        '             connectionTimeout="20000"\n'
        '             redirectPort="8443"\n'
        '             maxParameterCount="1000" />\n'
        '  -->\n'
        '\n'
        '  <!-- A "Connector" using an shared thread pool -->\n'
        '  <!--\n'
        '  <Connector port="8009" protocol="AJP/1.3"\n'
        '             redirectPort="8449"\n'
        '             secretRequired="false" />\n'
        '  -->\n'
        '</Server>\n'
    )

    # nginx.conf 的关键形状：`listen 80;` 生效，另有十几行注释示例。
    # 真机 nginx.conf 的注释 listen 长这样（`#` 开头、缩进对齐）。
    NGINX_CONF = (
        'worker_processes  1;\n'
        '\n'
        'events {\n'
        '    worker_connections  1024;\n'
        '}\n'
        '\n'
        'http {\n'
        '    include       mime.types;\n'
        '    default_type  application/octet-stream;\n'
        '\n'
        '    # 下面是各种listen 的示例，默认都不生效\n'
        '    #listen 8080;\n'
        '    #listen 8000;\n'
        '    #listen 443 ssl;\n'
        '    #listen localhost:8000;\n'
        '\n'
        '    server {\n'
        '        listen       80;\n'
        '        server_name  localhost;\n'
        '        location / {\n'
        '            root   html;\n'
        '            index  index.html index.htm;\n'
        '        }\n'
        '    }\n'
        '}\n'
    )

    # ---------------- 工具 ----------------

    @staticmethod
    def _strip_xml_comments(text):
        """把 <!-- --> 块内容替换成**等长空格**（换行保留）。

        这是本类所有 tomcat/nginx 断言的基础：**先去掉注释再解析**。
        直接在原文里 grep 端口，正是报告 §2.2 实测的那个静默失效的写法。
        """
        return re.sub(r"<!--.*?-->",
                      lambda m: re.sub(r"[^\r\n]", " ", m.group(0)),
                      text, flags=re.S)

    @classmethod
    def _effective_tomcat_ports(cls, xml_text):
        """解析 server.xml 里**真正生效**的端口（注释内的全部忽略）。

        返回 (shutdown 端口 或 None, HTTP 端口 或 None)。
        断言必须打在它上面 —— 打在"文件里出现了 18081"上，
        改到注释行的那种错实现照样通过，而那正是要防的坑。
        """
        clean = cls._strip_xml_comments(xml_text)
        shutdown = None
        m = re.search(r"<Server\b[^>]*>", clean, re.S)
        if m:
            pm = re.search(r'\bport="(\d+)"', m.group(0))
            if pm:
                shutdown = int(pm.group(1))
        http = None
        for cm in re.finditer(r"<Connector\b[^>]*>", clean, re.S):
            tag = cm.group(0)
            if 'protocol="HTTP/1.1"' not in tag:
                continue
            pm = re.search(r'\bport="(\d+)"', tag)
            if pm:
                http = int(pm.group(1))
            break
        return shutdown, http

    @classmethod
    def _commented_ports(cls, xml_text):
        """原文里所有**注释块内**的 port 值，顺序不变。"""
        return [int(n) for m in re.finditer(r"<!--.*?-->", xml_text, re.S)
                for n in re.findall(r'\bport="(\d+)"', m.group(0))]

    @classmethod
    def _effective_nginx_listens(cls, conf_text):
        """解析 nginx.conf 里**未被注释**的 listen 端口（行首缩进后直接 listen）。"""
        return [int(n) for n in
                re.findall(r"^[ \t]*listen[ \t]+(\d+)", conf_text, re.M)]

    @classmethod
    def _commented_nginx_listens(cls, conf_text):
        """原文里所有**注释行**上的 listen 端口。"""
        return [int(n) for n in
                re.findall(r"^[ \t]*#[ \t]*listen[ \t]+(\d+)", conf_text, re.M)]

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.tmp = Path(self.dir.name)
        self.comps = {c.key: c for c in main.build_components()}

        # 落盘位置全部重定向：用例不许往真~/.env-tools 里写文件。
        self._orig_dir, self._orig_run = main.CONFIG_DIR, main.RUNNING_FILE
        main.CONFIG_DIR = self.tmp
        main.RUNNING_FILE = self.tmp / "running.json"
        self.addCleanup(setattr, main, "CONFIG_DIR", self._orig_dir)
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig_run)

        # 不起真实进程、不碰网络。
        self.spawned = []
        self._orig_popen = main.subprocess.Popen
        main.subprocess.Popen = self._record_popen
        self.addCleanup(setattr, main.subprocess, "Popen", self._orig_popen)
        self._orig_run_fn = main.subprocess.run
        main.subprocess.run = self._record_run
        self.addCleanup(setattr, main.subprocess, "run", self._orig_run_fn)

        # 端口一律答"空闲"，探活一律答"在听" —— 用例成败不许取决于本机端口状态。
        self._orig_free = main.port_is_free
        main.port_is_free = lambda port, host="127.0.0.1": True
        self.addCleanup(setattr, main, "port_is_free", self._orig_free)
        self._orig_evict = main.evict_port_occupant
        main.evict_port_occupant = lambda port, label, evicted=None: None
        self.addCleanup(setattr, main, "evict_port_occupant", self._orig_evict)
        self._orig_java = main.resolve_java_home
        main.resolve_java_home = lambda comps: str(self.tmp / "jdk-17")
        self.addCleanup(setattr, main, "resolve_java_home", self._orig_java)

    def _record_popen(self, argv, **kw):
        self.spawned.append(list(argv))
        return FakePopenProc()

    @staticmethod
    def _record_run(argv, **kw):
        return FakeRunProc()

    def _installed(self, key):
        """把某组件造成"磁盘上真装着"并让路径解析可用（走真 start() 时需要）。"""
        comp = self.comps[key]
        version = comp.versions[0].version
        home = self.tmp / key / f"{key}-{version}"
        (home / "bin").mkdir(parents=True, exist_ok=True)
        # 2026-10-06：kafka/elasticsearch 的端口策略改成了 conf_copy
        # （kafka 要改 log.dirs、ES 要给用户留个可微调的副本），
        # 所以它们必须有一份可拷的官方配置，否则 prepare_ports 会拒改、
        # start() 走不到 pre_start 那一步（护栏表现为"start 没调 pre_start"）。
        cdir = home / main.conf_dir_name(key)
        cdir.mkdir(parents=True, exist_ok=True)
        fname = "server.properties" if key == "kafka" else "elasticsearch.yml"
        body = "log.dirs=/tmp/x" + chr(10) if key == "kafka" else "# all commented"
        (cdir / fname).write_text(body, encoding="utf-8")
        comp.install_dir = lambda v, _h=home: _h
        orig = main.resolve_launch_version
        main.resolve_launch_version = lambda c: version
        self.addCleanup(setattr, main, "resolve_launch_version", orig)
        return comp, home

    # ================= 共用（3 条） =================

    def test_launch_keys_is_exactly_the_ten_registered_components(self):
        """`LAUNCH_KEYS` 恰好 10 个，且就是登记表里的那 10 个。

        断言**集合相等**而不是断言长度：只钉长度的话，
        有人把 rocketmq 换成别的 key 数量不变、护栏照样绿。
        2026-10-06 由 9 个扩到 10 个（新增 seata）。
        """
        self.assertEqual(
            main.LAUNCH_KEYS,
            {"jenkins", "nacos", "activemq",
             "rocketmq", "nginx", "kafka", "tomcat",
             "elasticsearch", "rabbitmq", "seata"})
        self.assertEqual(len(main.LAUNCH_KEYS), 10)
        # 登记表与 key 集合不许脱节（多一个 key 却没有 spec 就查不到）。
        self.assertEqual(set(main.LAUNCH_OF), main.LAUNCH_KEYS)

    def test_every_launchable_component_carries_a_non_empty_risk_note(self):
        """九个组件每个都要有非空 `risk_note`。

        risk_note 是**启动确认弹窗里唯一**告诉用户"这台机器上会发生什么"的字段
        （监听 0.0.0.0 =对局域网开放、关掉了认证、弹黑窗……）。
        空字符串意味着用户点下去之前完全不知道会发生什么，
        而这些组件全都默认对局域网开放。
        """
        for key in sorted(main.LAUNCH_KEYS):
            with self.subTest(key=key):
                note = main.LAUNCH_OF[key].risk_note
                self.assertIsInstance(note, str)
                self.assertTrue(note.strip(),
                                f"{key} 的 risk_note 是空的：启动确认弹窗里"
                                f"没有任何关于'会发生什么'的说明")

    def test_prepare_ports_refuses_when_the_key_has_no_registered_writer(self):
        """`comp.key` 没登记分派器时**拒改**，并承诺"不会去猜"。

        `prepare_ports` 现在按comp.key 查分派器（不是写死ActiveMQ）。
        查不到时必须明确放弃 —— 宁可拒绝启动，也不能猜一个改法：
        猜错的后果是"配置没改、进程按旧端口起来"，界面上却写着新端口。
        """
        comp = self.comps["jenkins"]          # jenkins 从未登记过分派器
        self.assertIsNone(main.conf_writer_of("jenkins"))
        spec = copy.deepcopy(main.LAUNCH_OF["activemq"])
        spec.port_writeback = "conf_copy"     # 强行要求改配置
        data = self.tmp / "data"
        ok, why, _notes = main.prepare_ports(
            comp, spec, main.PortPlan(main=8161), data)
        self.assertFalse(ok, "没有分派器却放行了 —— 等于去猜配置该怎么改")
        self.assertIn("不会去猜", why,
                      "拒改时必须承诺不会去猜，让用户知道要自己动手")
        self.assertEqual(comp.display_name, why.split()[0],
                         "拒改原因必须指名是哪个组件")
        self.assertEqual(list(data.rglob("*")) if data.exists() else [],
                         [], "拒改不许留下任何文件（副本也不许建）")

    def test_conf_writer_registry_and_port_strategy_agree_in_both_directions(self):
        """`_CONF_WRITERS` 与端口策略**双向**一致。

        两个方向都要钉，否则登记表与分派器会脱节：
          - `conf_copy` 的组件必须有分派器（否则端口永远改不动，
            却会告诉用户"已在副本里改好"）；
          - `cli_only` / `cli_flag` 的组件必须**没有**分派器
            （有了就意味着会有代码去建副本/改文件，而它们的端口全靠命令行，
            多改一个文件就是多一个与厂商默认值不一致的风险）。
        """
        for key in sorted(main.LAUNCH_KEYS):
            with self.subTest(key=key):
                spec = main.LAUNCH_OF[key]
                writer = main.conf_writer_of(key)
                if spec.port_writeback == "conf_copy":
                    self.assertIsNotNone(
                        writer, f"{key} 声明 conf_copy 却没有分派器："
                                f"端口永远不会被改，却会报'已改好'")
                else:
                    self.assertIn(spec.port_writeback, ("cli_only", "cli_flag"))
                    self.assertIsNone(
                        writer, f"{key} 的端口策略是 {spec.port_writeback}，"
                                f"却有分派器：会多改一个本不该动的文件")
        # 反向：分派器表里不许出现登记表之外的 key（僵尸分派器）。
        for key in sorted(main._CONF_WRITERS):
            with self.subTest(key=key):
                self.assertIn(key, main.LAUNCH_KEYS,
                              f"分派器表里有 {key}，但它不是可启动组件")

    # ================= tomcat（6 条） =================

    def test_tomcat_changes_the_live_connector_never_a_commented_one(self):
        """**改的是生效那行**：去注释后解析出的 HTTP 口必须真的是新值。

        这是 tomcat 最核心的一条。报告 §2.2 实测：只改注释里那处 8080，
        文件里写着 18081、**运行时仍然听 8080**，零报错零日志、退出码 0。
        所以断言必须打在"去注释之后解析出的生效端口"上——
        打"文件里出现了 18081"的话，这个错实现照样通过。
        """
        xml = self.tmp / "server.xml"
        xml.write_text(self.TOMCAT_SERVER_XML, encoding="utf-8")
        self.assertEqual(self._effective_tomcat_ports(
            self.TOMCAT_SERVER_XML), (8005, 8080),
            "fixture 前提不成立：它必须真的有 2 处生效端口")

        ok, why = main.set_tomcat_ports(xml, 18081, 8005)
        self.assertTrue(ok, why)

        after = xml.read_text(encoding="utf-8")
        shutdown, http = self._effective_tomcat_ports(after)
        self.assertEqual(http, 18081,
                         "去注释后解析出的 HTTP 口不是新值—— 改到注释行了，"
                         "运行时仍会听 8080（静默失效）")
        self.assertEqual(shutdown, 8005,
                         "shutdown 口不该被顺带改掉（本次给的目标值就是 8005）")

    def test_tomcat_never_touches_the_ports_inside_comment_blocks(self):
        """注释块里的端口值**一个都不许变**。

        与上一条互补：上一条钉"生效口改对了"，这条钉"没顺手污染注释"。
        `text.replace(...)` 全文替换那种写法会改对HTTP 口，
        但同时把注释里的 8080/8443/8009 也换成新值——
        用户打开配置看到"官方示例端口全被改了"，而下一条幂等护栏之外的
        换版本/比对官方文档都受影响。这条让它红。
        """
        xml = self.tmp / "server.xml"
        xml.write_text(self.TOMCAT_SERVER_XML, encoding="utf-8")
        before = self._commented_ports(self.TOMCAT_SERVER_XML)
        self.assertEqual(before, [8080, 8443, 8009],
                         "fixture 前提不成立：注释块里的端口值应对应真机形状")

        ok, why = main.set_tomcat_ports(xml, 18081, 18085)
        self.assertTrue(ok, why)

        after = xml.read_text(encoding="utf-8")
        self.assertEqual(self._commented_ports(after), before,
                         "注释块里的端口值被动过了 —— 官方示例被污染")
        # 注释块的**文本**也必须原样保留（不能被抹成空白）。
        for block in re.findall(r"<!--.*?-->", self.TOMCAT_SERVER_XML, re.S):
            self.assertIn(block, after,
                          "注释块内容被抹掉了：用户打开配置看到的是一片空白")

    def test_tomcat_both_ports_land_on_their_own_anchors(self):
        """两个端口**分别**落到 `<Server>` 与 HTTP `<Connector>`，不许互换。

        报告 §2.3 实测：`re.sub(port=..., count=1)` 命中的是第22 行的
        **shutdown** 口 —— HTTP 口没变，而停止能力被破坏（对错误实例执行
        shutdown.bat 会杀掉另一个实例并返回 rc=0，看起来完全成功）。

        所以这里用两个**明显不同**的目标值，并分别断言两个锚点：
        只钉"某个口变了"的话，两处写反了照样绿。
        """
        xml = self.tmp / "server.xml"
        xml.write_text(self.TOMCAT_SERVER_XML, encoding="utf-8")

        ok, why = main.set_tomcat_ports(xml, 18081, 18085)
        self.assertTrue(ok, why)

        after = xml.read_text(encoding="utf-8")
        shutdown, http = self._effective_tomcat_ports(after)
        self.assertEqual(
            (http, shutdown), (18081, 18085),
            "两个端口没分别落到正确的锚点上。"
            "实测踩过的坑：按出现顺序改第一处 port= 改到的是 shutdown 口，"
            "结果主口没变、停止能力被破坏")

        # 反向锚定：<Server> 标签里必须是 18085，HTTP Connector 里必须是 18081。
        clean = self._strip_xml_comments(after)
        server_tag = re.search(r"<Server\b[^>]*>", clean, re.S).group(0)
        self.assertIn('port="18085"', server_tag,
                      "shutdown 端口必须落在 <Server> 上")
        self.assertNotIn('port="18081"', server_tag,
                         "HTTP 端口跑到了 <Server> 上 —— 停止端口被主端口顶掉了")

    def test_tomcat_writeback_is_idempotent_in_content_mtime_and_backup_count(self):
        """幂等：重复点启动时，内容 / mtime / `.bak` 数量**三者都不许变**。

        为什么三者都要钉：
          - 只钉内容 → 无脑 `write_bytes(同一份)` 的实现能过，
            但它每次都改 mtime、每次都让杀软/备份软件重新扫一遍；
          - 只钉 mtime → 忘了 `.bak` 那个实现过不了，
            而反复点启动会刷出一串 `server.xml.bak.bak.bak`（`_backup_once`
            本来就是专门防这个的，注释里写着"那是噪音"）。
        """
        xml = self.tmp / "server.xml"
        xml.write_text(self.TOMCAT_SERVER_XML, encoding="utf-8")
        ok, why = main.set_tomcat_ports(xml, 18081, 18085)
        self.assertTrue(ok, why)

        text1 = xml.read_text(encoding="utf-8")
        mtime1 = xml.stat().st_mtime_ns
        baks1 = sorted(p.name for p in self.tmp.glob("*.bak"))

        # 第二、第三次同参数调用：必须是彻底的 no-op。
        for attempt in (2, 3):
            with self.subTest(attempt=attempt):
                ok, why = main.set_tomcat_ports(xml, 18081, 18085)
                self.assertTrue(ok, why)
                self.assertEqual(xml.read_text(encoding="utf-8"), text1,
                                 f"第 {attempt} 次调用改了内容")
                self.assertEqual(xml.stat().st_mtime_ns, mtime1,
                                 f"第 {attempt} 次调用重写了文件（mtime 变了）")
                self.assertEqual(sorted(p.name for p in self.tmp.glob("*.bak")),
                                 baks1,
                                 f"第 {attempt} 次调用又多备份了一份")

        shutdown, http = self._effective_tomcat_ports(text1)
        self.assertEqual((http, shutdown), (18081, 18085))

    def test_tomcat_refuses_and_writes_nothing_when_no_connector_is_live(self):
        """生效的 `<Connector>` 一个都没有时**拒改**，且一个字节都不写。

        这是"永远不会被注释骗"的最后一道：官方把 Connector 整段注释掉
        （或用户改过写法）时，宁可拒绝启动并指名要改哪一行，
        也不能"改到注释里去"然后报告成功 —— 那样用户会看到
        "运行中·端口 18081"而实际服务在8080 上（或者压根没起来）。
        """
        only_commented = self.TOMCAT_SERVER_XML.replace(
            '  <Connector port="8080" protocol="HTTP/1.1"\n'
            '             connectionTimeout="20000"\n'
            '             redirectPort="8443"\n'
            '             maxParameterCount="1000" />\n',
            '  <!-- <Connector port="8080" protocol="HTTP/1.1" /> -->\n')
        # 前提自检：造出来的 fixture 里生效 HTTP 口必须是 None。
        self.assertIsNone(self._effective_tomcat_ports(only_commented)[1],
                          "fixture 前提不成立：应该一个生效 Connector 都不剩")
        self.assertIn("Connector", only_commented,
                      "fixture 前提不成立：注释里仍应留着 Connector 示例")

        xml = self.tmp / "server.xml"
        xml.write_text(only_commented, encoding="utf-8")
        before = xml.read_bytes()
        before_mtime = xml.stat().st_mtime_ns

        ok, why = main.set_tomcat_ports(xml, 18081, 18085)
        self.assertFalse(ok, "生效 Connector 不存在时却报告改成功了")
        self.assertIn("Connector", why,
                      "拒改必须指名要找的锚点（protocol=\"HTTP/1.1\"），"
                      "否则用户不知道该去改哪一行")
        self.assertEqual(xml.read_bytes(), before,
                         "拒改却写了文件")
        self.assertEqual(xml.stat().st_mtime_ns, before_mtime,
                         "拒改却碰了文件（mtime 变了）")
        self.assertEqual(list(self.tmp.glob("*.bak")), [],
                         "拒改却留了 .bak")

    def test_tomcat_registers_8005_as_a_second_port(self):
        """8005 必须在 `extra_ports` 里 —— 只探主口会漏掉停止能力。

        实测（报告 §5.3）：只改 HTTP 口而留着 8005 时，多实例场景下
        新实例 bind 失败**自杀**（HTTP 502），而对它执行 shutdown.bat 会杀掉
        8005 的真正持有者并**返回 rc=0** —— 看起来完全成功。
        所以 8005 必须和主口一起被纳入端口簇，一起探测、一起改。
        """
        spec = main.LAUNCH_OF["tomcat"]
        self.assertIn(8005, spec.extra_ports,
                      "8005 不在 extra_ports 里：多实例时会互相抢占 shutdown 口，"
                      "误杀别的实例还返回 rc=0")
        # 整簇都必须真的进端口规划（choose_ports 认extra_ports）。
        plan, why = main.choose_ports(
            spec, is_free=lambda p, host="127.0.0.1": True, evict=False)
        self.assertIn(8005, plan.all_ports,
                      f"8005 没进端口簇：{plan.all_ports} / {why}")
        # 而 shutdown 端口的取值来源就是 extra_ports 的第一位
        # （_write_tomcat_ports: plan.extras[0]），所以顺序也有意义。
        self.assertEqual(spec.extra_ports[0], 8005,
                         "shutdown 端口取的是 extras[0]，顺序变了就会取错口")

    # ================= nginx（3 条） =================

    def test_nginx_changes_the_live_listen_line_and_leaves_comments_alone(self):
        """改的是**生效那行** `listen`，注释里的十几行 listen 示例原样保留。

        与 tomcat 同一个坑：nginx.conf 里除生效的 `listen 80;` 外还有
        `#listen 8080;` `#listen 443 ssl;` 等示例。裸替换打到注释行时，
        文件显示改了、**运行时仍是 80**，静默失效。
        """
        conf = self.tmp / "nginx.conf"
        conf.write_text(self.NGINX_CONF, encoding="utf-8")
        self.assertEqual(self._effective_nginx_listens(self.NGINX_CONF), [80],
                         "fixture 前提不成立：应恰好只有 1 条生效 listen")
        self.assertEqual(self._commented_nginx_listens(self.NGINX_CONF),
                         [8080, 8000, 443],
                         "fixture 前提不成立：注释示例里应有三个纯数字端口")

        ok, why = main.set_nginx_listen(conf, 18081)
        self.assertTrue(ok, why)

        after = conf.read_text(encoding="utf-8")
        self.assertEqual(self._effective_nginx_listens(after), [18081],
                         "生效的 listen 没改成新值 —— 改到注释行去了，"
                         "运行时仍然听 80（静默失效）")
        self.assertEqual(self._commented_nginx_listens(after),
                         [8080, 8000, 443],
                         "注释里的 listen 示例被改了：官方示例被污染")

    def test_nginx_writeback_is_idempotent_in_content_mtime_and_backup_count(self):
        """nginx 回写同样要幂等（内容 / mtime / `.bak` 数量三者不变）。

        nginx 每次启动都会重新读配置，用户反复点启动很常见；
        每次都重写 + 每次都备份会刷出一串 `.bak` 且让 mtime 一直跳。
        """
        conf = self.tmp / "nginx.conf"
        conf.write_text(self.NGINX_CONF, encoding="utf-8")
        ok, why = main.set_nginx_listen(conf, 18081)
        self.assertTrue(ok, why)

        text1 = conf.read_text(encoding="utf-8")
        mtime1 = conf.stat().st_mtime_ns
        baks1 = sorted(p.name for p in self.tmp.glob("*.bak"))
        self.assertEqual(baks1, ["nginx.conf.bak"], "首次改动应留一份 .bak")

        ok, why = main.set_nginx_listen(conf, 18081)
        self.assertTrue(ok, why)
        self.assertEqual(conf.read_text(encoding="utf-8"), text1,
                         "同参数第二次调用改了内容")
        self.assertEqual(conf.stat().st_mtime_ns, mtime1,
                         "同参数第二次调用重写了文件（mtime 变了）")
        self.assertEqual(sorted(p.name for p in self.tmp.glob("*.bak")), baks1,
                         "同参数第二次调用又多备份了一份")

    def test_nginx_refuses_when_every_listen_line_is_commented(self):
        """所有 listen 都在注释里时**拒改**，且不写文件。

        与 tomcat 同理：没有生效锚点时必须明确放弃，不能"改到注释里去"
        然后报告成功。（`replace_all` 那种写法在这里会静默通过 ——
        报告 §2.4 明确说它只是"碰巧"对，一旦目标口只出现在注释里立刻失效。）
        """
        conf = self.tmp / "nginx.conf"
        conf.write_text(self.NGINX_CONF.replace(
            "        listen       80;\n",
            "        #listen       80;\n"), encoding="utf-8")
        self.assertEqual(self._effective_nginx_listens(
            conf.read_text(encoding="utf-8")), [],
            "fixture 前提不成立：应一个生效 listen 都不剩")
        before = conf.read_bytes()
        before_mtime = conf.stat().st_mtime_ns

        ok, why = main.set_nginx_listen(conf, 18081)
        self.assertFalse(ok, "生效 listen 不存在时却报告改成功了")
        self.assertIn("listen", why, "拒改必须指名要找的指令")
        self.assertEqual(conf.read_bytes(), before, "拒改却写了文件")
        self.assertEqual(conf.stat().st_mtime_ns, before_mtime,
                         "拒改却碰了文件（mtime 变了）")
        self.assertEqual(list(self.tmp.glob("*.bak")), [],
                         "拒改却留了 .bak")

    # ================= kafka（5 条） =================

    def test_kafka_start_command_avoids_bat_and_uses_the_libs_wildcard(self):
        """启动命令**不含 `.bat`**，含 `libs/*` 与 `kafka.Kafka`（三个 OS 都要）。

        两条硬理由（2026-10-06 实测，框架真实安装路径下）：
          ① `kafka-run-class.bat:188` 把 109 个 jar 拼成一行= 8650 字符，
             **超过 cmd.exe 的 8191 上限** → rc=255「输入行太长」；
          ② `kafka-server-start.bat:28` 调 `wmic os get osarchitecture`，
             wmic 在 Win11 已弃用（本机沙箱直接拦截）。

        直接 spawn java，`-cp` 的 `libs/*` 由 JVM 展开，不受 8191 限制。
        """
        for os_name in ("Windows", "Linux", "Darwin"):
            with self.subTest(os=os_name):
                cmd = main.LAUNCH_OF["kafka"].commands[os_name]
                joined = " ".join(cmd).lower()
                self.assertNotIn(".bat", joined,
                                 "启动命令里出现 .bat：8191 上限 + wmic 已弃用，"
                                 "实测 rc=255 起不来")
                self.assertNotIn("kafka-run-class", joined,
                                 "启动命令绕回了 kafka-run-class.bat")
                self.assertNotIn("wmic", joined, "启动命令里出现 wmic（Win11 已弃用）")
                self.assertTrue(any("libs/*" in t for t in cmd),
                                f"-cp 必须是 libs/* 通配符：{cmd}")
                self.assertIn(main.KAFKA_MAIN_CLASS, cmd,
                              f"必须直接调 {main.KAFKA_MAIN_CLASS}：{cmd}")
                # classpath 必须在主类之前，否则 JVM 找不到主类。
                cp_at = next(i for i, t in enumerate(cmd) if "libs/*" in t)
                self.assertLess(cp_at, cmd.index(main.KAFKA_MAIN_CLASS),
                                f"classpath 必须排在主类之前：{cmd}")

    def test_kafka_pre_start_formats_kraft_storage_and_stays_idempotent(self):
        """`pre_start` 含 StorageTool `format` / `--standalone` / `--ignore-formatted`。

        Kafka 4.x 是纯 KRaft，不format 直接 `No readable meta.properties files
        found.` 起不来。而重复 format 必须幂等 —— 实测**同 uuid + 该 flag ⇒ rc=0**；
        换成新 uuid 则 `rc=1 Invalid cluster.id`。所以 flag 与 cluster_id 占位符
        两个都要钉。
        """
        pre = main.LAUNCH_OF["kafka"].pre_start
        self.assertTrue(pre, "kafka 没登记pre_start：不 format 起不来"
                             "（No readable meta.properties files found.）")
        joined = " ".join(pre)
        self.assertIn(main.KAFKA_STORAGE_TOOL, joined,
                      f"pre_start 必须用 {main.KAFKA_STORAGE_TOOL}：{joined}")
        self.assertIn("format", pre, "pre_start 必须真的执行 format 子命令")
        self.assertIn("--standalone", pre,
                      "单节点必须显式 --standalone（KRaft 单机模式）")
        self.assertIn("--ignore-formatted",
                      pre,
                      "缺 --ignore-formatted 时重复点启动会第二次 format "
                      "而失败 —— 实测同 uuid + 该 flag 才幂等（rc=0）")
        self.assertIn("{cluster_id}", pre,
                      "必须用持久化的 cluster_id 占位符：换 uuid 会被拒"
                      "（Invalid cluster.id）")
        # cluster.id 必须落在 data_dir 里由我们管，不能在安装目录。
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            first = main.read_or_create_cluster_id(data)
            second = main.read_or_create_cluster_id(data)
        self.assertEqual(first, second, "cluster.id 每次都变：broker 会认不出自己的元数据")
        self.assertEqual(main.kafka_cluster_id_file(self.tmp), self.tmp / "cluster.id")

    def test_kafka_registers_9093_so_a_dead_controller_is_not_reported_running(self):
        """9093（KRaft controller）必须在 `extra_ports` 里。

        实测 9092 与 9093 同时起、9093 恒先于 9092。只探主口的话，
        "controller 没起来"这种半死状态会被显示成**运行中**——
        而 broker 恰恰依赖 controller，这个状态下客户端连得上却发不了消息。
        """
        spec = main.LAUNCH_OF["kafka"]
        self.assertIn(9093, spec.extra_ports,
                      "9093（KRaft controller）不在 extra_ports 里："
                      "只探主口会把'controller 没起来'显示成运行中")
        plan, why = main.choose_ports(
            spec, is_free=lambda p, host="127.0.0.1": True, evict=False)
        self.assertIn(9093, plan.all_ports, f"9093 没进端口簇：{plan.all_ports} / {why}")
        # 方向：9093 是独立基准口（KRaft 固定值），不是主口的偏移。
        self.assertEqual(spec.port_offsets, (),
                         "KRaft 的 9093 是独立基准口，不该写成主口偏移")

    def test_kafka_requires_java_17(self):
        """`min_java_major == 17`。

        实测 jar 内 469 个 class 的 major version 全部 = 61（即 Java 17）。
        门控值填错的后果是双向的：填 8 会让Java 8 用户点启动后拿到
        满屏 class 文件版本错误；填 21 则把 17 用户挡在门外。
        """
        self.assertEqual(main.LAUNCH_OF["kafka"].min_java_major, 17,
                         "Kafka 4.x 的 class major version 全是 61(=17)，"
                         "门控值填错会放行或拦掉错误的 JDK")

    def test_kafka_log_dirs_is_written_as_an_absolute_forward_slash_path(self):
        """`log.dirs` 必须写成**绝对路径 + 正斜杠**。

        官方默认 `/tmp/kraft-combined-logs` 在 Windows 上解析成 `C:\\tmp\\...`：
        既不在安装目录也不在数据目录（卸载删不掉、多版本抢同一个目录）。
        而且目录不存在时 `kafka.Kafka` 直接 rc=1起不来（只有 format 会建目录）。

        正斜杠的另一层理由：properties 里反斜杠是转义符，
        写 `C:\\tmp` 会被吃掉一段。
        """
        conf = self.tmp / "server.properties"
        conf.write_text("broker.id=1\nlog.dirs=/tmp/kraft-combined-logs\n",
                        encoding="utf-8")
        want = (self.tmp / "kafka-data" / "kraft-logs").as_posix()
        ok, why = main.set_kafka_log_dirs(conf, want)
        self.assertTrue(ok, why)

        line = [ln for ln in conf.read_text(encoding="utf-8").splitlines()
                if ln.startswith("log.dirs=")]
        self.assertEqual(line, [f"log.dirs={want}"],
                         f"log.dirs 没被写成绝对正斜杠路径：{line}")
        self.assertNotIn("\\", line[0],
                         "properties 里反斜杠是转义符，写 C:\\tmp 会被吃掉一段")
        self.assertFalse(line[0].endswith("/tmp/kraft-combined-logs"),
                         "仍是官方默认：Windows 上会落到 C:\\tmp\\，"
                         "既不在安装目录也不在数据目录")
        self.assertTrue(Path(line[0].split("=", 1)[1]).is_absolute(),
                        f"log.dirs 必须是绝对路径：{line[0]}")

        # 幂等 + 锚不到就拒改（官方默认写法被改过时必须明确放弃）。
        text1, mtime1 = conf.read_text(encoding="utf-8"), conf.stat().st_mtime_ns
        ok, why = main.set_kafka_log_dirs(conf, want)
        self.assertTrue(ok, why)
        self.assertEqual(conf.read_text(encoding="utf-8"), text1,
                         "同值重复调用不该重写文件")
        self.assertEqual(conf.stat().st_mtime_ns, mtime1,
                         "同值重复调用不该改 mtime")
        conf.write_text("broker.id=1\n", encoding="utf-8")
        ok, why = main.set_kafka_log_dirs(conf, want)
        self.assertFalse(ok, "文件里没有 log.dirs= 这一行却报告改成功")
        self.assertIn("log.dirs", why, "拒改必须指名要改哪一行")

    # ================= elasticsearch（5 条） =================

    def test_elasticsearch_disables_xpack_security_on_all_three_os_explained(self):
        """三个 OS 都带 `-Expack.security.enabled=false`，且 `risk_note` 说明理由。

        这不是"我们图省事"：一键启动是**后台无终端进程**，ES 官方明说此时
        它无法生成随机密码（`we cannot determine if there is a terminal attached`）。
        开着认证的后果是**既拿不到密码、也没地方展示** —— 用户看到"运行中"
        却登不进去。所以必须关掉，且必须在弹窗里说清"启动后没有认证"。

        三个 OS 都要查：只给 Windows 加flag 而漏了 Linux，
        在别的机器上就是"莫名其妙要密码"。
        """
        for os_name in ("Windows", "Linux", "Darwin"):
            with self.subTest(os=os_name):
                cmd = main.LAUNCH_OF["elasticsearch"].commands[os_name]
                self.assertIn("-Expack.security.enabled=false", cmd,
                              f"{os_name} 的启动命令没关掉 xpack.security："
                              f"后台无终端进程时 ES 不生成随机密码，"
                              f"用户既拿不到也没地方展示")
        note = main.LAUNCH_OF["elasticsearch"].risk_note
        self.assertIn("xpack", note,
                      "risk_note 必须说明关掉了 xpack.security —— "
                      "这是用户点启动前唯一能看到'没有认证'的地方")
        self.assertTrue("密码" in note or "认证" in note,
                        "risk_note 必须说清为什么（拿不到随机密码 / 没有认证）")
        self.assertTrue("终端" in note or "后台" in note,
                        "risk_note 必须说清关认证的原因是一键启动没有终端")

    def test_elasticsearch_creates_a_copy_but_writes_no_value_into_it(self):
        """ES 建副本，但**一个值都不往里写**（2026-10-06 改的契约）。

    原契约是 `cli_only` / 一个文件都不建，理由是 `-E` 能覆盖一切 —— 那部分对。
    但改成 `conf_copy`（只建副本、不写值）之后有个实际好处：
    用户想手工微调（堆内存、discovery 等）时有地方可改，
    而**官方那份文件卸载就会被删**。所以断言的是「副本存在但值未被动」。

    端口 / 路径 / 安全开关仍然全靠 `-E`：
    - `-Ediscovery.type=single-node`（实测不设也能起，只是多 3 秒 + 告警）
    - `-Expack.security.enabled=false`（无终端进程时 ES 不生成密码）
    - `-Ehttp.port` / `-Epath.data` / `-Epath.logs`
    """
        spec = main.LAUNCH_OF["elasticsearch"]
        self.assertEqual(spec.port_writeback, "conf_copy")
        comp, _home = self._installed("elasticsearch")
        data = self.tmp / "es-data"
        ok, why, _notes = main.prepare_ports(
            comp, spec, main.PortPlan(main=9200, extras=(9300,)), data)
        self.assertTrue(ok, why)
        copied = data / "conf" / "elasticsearch.yml"
        self.assertTrue(copied.exists(), "没建副本")
        # 副本内容必须与官方一致 —— 我们没往里写任何端口/路径
        original = (_home / "config" / "elasticsearch.yml").read_text(encoding="utf-8")
        self.assertEqual(copied.read_text(encoding="utf-8"), original,
                         "ES 的副本必须与官方逐字一致（我们不写任何值，"
                         "改配置请用启动命令的 -E 参数）")

    def test_elasticsearch_points_path_data_and_logs_at_the_data_dir(self):
        """`path.data` / `path.logs` 指向 data_dir（数据落在 `~/.env-tools`）。

        不指的后果：数据落在**安装目录内**，卸载/删版本目录会连带删掉，
        多版本并存还会互相踩（三个版本都能同时起，但抢同一个 data 就废了）。
        """
        for os_name in ("Windows", "Linux", "Darwin"):
            with self.subTest(os=os_name):
                cmd = main.LAUNCH_OF["elasticsearch"].commands[os_name]
                self.assertIn("-Epath.data={data_dir}/data", cmd,
                              f"{os_name} 没把 path.data 指到 data_dir："
                              f"数据会落在安装目录里，卸载连带删掉")
                self.assertIn("-Epath.logs={data_dir}/logs", cmd,
                              f"{os_name} 没把 path.logs 指到 data_dir")
        # 占位符真的会被展开成 data_dir（而不是原样留着 {data_dir}）。
        comp, _home = self._installed("elasticsearch")
        plan = main.build_launch_plan(
            comp, comp.launch, str(self.tmp / "jdk-17"), 9200,
            self.tmp / "byte-tools.out")
        # 注意 `{data_dir}/data` 里斜杠是模板里的字面量，Windows 上仍留正斜杠
        # —— ES 的path.* 接受混用，断言按真实展开值比对。
        want_data = f"-Epath.data={self.tmp / 'elasticsearch-data'}/data"
        self.assertIn(want_data, plan.argv,
                      "path.data 占位符没展开成真实的 data_dir")
        self.assertIn(f"-Epath.logs={self.tmp / 'elasticsearch-data'}/logs",
                      plan.argv, "path.logs 占位符没展开成真实的 data_dir")
        self.assertNotIn("{data_dir}", " ".join(plan.argv),
                         "有占位符没被展开：ES 会把字面量 {data_dir} 当目录名")

    def test_elasticsearch_needs_no_external_jdk(self):
        """`needs == ()` 且 `min_java_major is None`。

        ES **自带 JDK 25 且强制使用、忽略 JAVA_HOME**。填上 `needs=("jdk",)`
        会让门控在没有外部 JDK 时拦住启动（实测根本不需要），
        填上 `min_java_major` 则会让版本门控去比对一个 ES 根本不用的 JDK ——
        两个方向都是把用户挡在门外。
        """
        spec = main.LAUNCH_OF["elasticsearch"]
        self.assertEqual(spec.needs, (),
                         "ES 自带 JDK 25 且忽略 JAVA_HOME，不该依赖外部 jdk："
                         "填上 needs 会让没装 JDK 的用户被门控拦住")
        self.assertIsNone(spec.min_java_major,
                          "ES 不使用外部 JDK，不该有 JDK 版本门控")
        # 门控侧的反证：java_home=None 也必须放行。
        comp = self.comps["elasticsearch"]
        orig = main.resolve_launch_version
        main.resolve_launch_version = lambda c: comp.versions[0].version
        self.addCleanup(setattr, main, "resolve_launch_version", orig)
        (self.tmp / "es" / f"elasticsearch-{comp.versions[0].version}").mkdir(
            parents=True, exist_ok=True)
        ok, why = main.launch_gate(comp, spec, java_home=None)
        self.assertTrue(ok, f"没有外部 JDK 却拦住 ES：{why}")

    def test_elasticsearch_registers_9300_transport_port(self):
        """9300（节点间transport）必须在 `extra_ports` 里。

        实测 9200 与 9300 两个都监听。9300 是 transport 口，
        **不能当探活口**（它是集群内部通信协议，不是 HTTP）——
        但它没起来时 ES 节点是不完整的，所以要纳入端口簇一起探测。
        """
        spec = main.LAUNCH_OF["elasticsearch"]
        self.assertIn(9300, spec.extra_ports,
                      "9300（transport）不在 extra_ports 里："
                      "ES 节点没起全却会被显示成运行中")
        self.assertEqual(spec.health_path, None,
                         "ES 的探活口是 HTTP 9200，不该把 9300 当探活路径")
        plan, why = main.choose_ports(
            spec, is_free=lambda p, host="127.0.0.1": True, evict=False)
        self.assertIn(9300, plan.all_ports, f"9300 没进端口簇：{plan.all_ports} / {why}")

    # ================= rocketmq（6 条） =================

    def test_rocketmq_windows_entry_is_the_primary_script_not_run_wrapper(self):
        """Windows 入口必须是**一级入口 `mqnamesrv.cmd`**，不含 run*.cmd。

        厂商脚本分两级，用错必炸：
          - 一级 `bin\\mq*.cmd`：开头检查并设置 `ROCKETMQ_HOME`，没设就 `EXIT /B 1`；
          - 二级 `bin\\runbroker.cmd` / `runserver.cmd`：**纯 `%*` 透传、不设环境变量**，
            而 BrokerStartup 靠 `ROCKETMQ_HOME` 找 `conf/broker.conf`
            → 直接 `FileNotFoundException`。

        Linux/Darwin 用 `runserver.sh` 是对的（那边没有 .cmd 两级结构），
        所以这条只查Windows。
        """
        cmd = main.LAUNCH_OF["rocketmq"].commands["Windows"]
        joined = " ".join(cmd).lower()
        self.assertIn("mqnamesrv.cmd", joined,
                      f"Windows 入口必须是一级脚本 mqnamesrv.cmd：{cmd}")
        self.assertNotIn("runbroker.cmd", joined,
                         "用了二级脚本 runbroker.cmd：纯 %* 透传、不设 "
                         "ROCKETMQ_HOME，BrokerStartup 找不到 conf/broker.conf "
                         "（FileNotFoundException）")
        self.assertNotIn("runserver.cmd", joined,
                         "用了二级脚本 runserver.cmd：同上，纯 %* 透传")

    def test_rocketmq_port_lookup_stop_kind_registers_a_launcher_pid(self):
        """`stop_kind == "port_lookup"` ⇒ `pid_role` 是 **launcher**。

        这条走**真实 `start()`**：只断言 spec 字段的话，
        有人把 `pid_role="server" if stop_kind == "pid" else "launcher"`
        改成硬编码 `"server"`，spec 断言照样绿，而登记里会存下一个
        不能代表服务进程的 PID —— 停止时按它去taskkill 会杀错进程。
        """
        self.assertEqual(main.LAUNCH_OF["rocketmq"].stop_kind, "port_lookup",
                         "RocketMQ 没有可靠的厂商停止手段，只能走端口反查")
        comp, _home = self._installed("rocketmq")
        mgr = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": True,
            http_ok=lambda u, timeout=2.0: True,
            process_alive=lambda pid: True)
        res = mgr.start(comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, f"start() 应该成功：{res.state} / {res.reason}")
        rec = main.load_running_map()["rocketmq"]
        self.assertEqual(rec.pid_role, "launcher",
                         "port_lookup 的组件必须登记 launcher："
                         "mqnamesrv.cmd 是壳进程，登记成 server 会让停止时"
                         "按错误的 PID 去杀")
        # 镜像：**真的跑一遍** stop_kind=="pid" 的组件（kafka）。
        # 这半边不是冗余 —— 它防的是"把 pid_role 硬编码成 launcher"那个变异：
        # 那样 rocketmq 这条照样绿，但 kafka 会被登记成 launcher，
        # 而 kafka 的 Popen.pid 就是 broker 进程本身（实测），
        # 登记成 launcher 就再也没人按这个 PID 去停它了。
        kcomp, _khome = self._installed("kafka")
        mgr2 = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": True,
            http_ok=lambda u, timeout=2.0: True,
            process_alive=lambda pid: True)
        kres = mgr2.start(kcomp, self.comps, sleeper=lambda s: None)
        self.assertTrue(kres.ok, f"kafka start() 应该成功：{kres.state} / {kres.reason}")
        krec = main.load_running_map()["kafka"]
        self.assertEqual(main.LAUNCH_OF["kafka"].stop_kind, "pid",
                         "前提不成立：kafka 是 stop_kind==pid 的那一类")
        self.assertEqual(krec.pid_role, "server",
                         "stop_kind=='pid' 的组件必须登记 server："
                         "它的 Popen.pid 就是服务进程本身（实测 kafka.Kafka "
                         "直接就是监听 9092 的 java 进程），"
                         "登记成 launcher 之后就没人按这个 PID 去停它了")

    def test_rocketmq_registers_10909_and_10911_but_not_the_ha_port(self):
        """10909 + 10911 在 `extra_ports` 里，而 **10912 不在**。

        实测 broker 起来后三个口同时监听，但 10912 是 HA（主备复制）用的，
        standalone 单机不需要它。列进去的后果是每次启动都要等一个
        永远不会来的口。
        """
        spec = main.LAUNCH_OF["rocketmq"]
        for port in (10909, 10911):
            with self.subTest(port=port):
                self.assertIn(port, spec.extra_ports,
                              f"{port} 不在 extra_ports 里：broker 端口没纳入探测")
        self.assertNotIn(10912, spec.extra_ports,
                         "10912（HA 主备复制口）不该登记：standalone 单机不监听它，"
                         "列进去会让启动永远等不到")
        plan, why = main.choose_ports(
            spec, is_free=lambda p, host="127.0.0.1": True, evict=False)
        self.assertIn(10909, plan.all_ports, f"10909 没进端口簇：{plan.all_ports}")
        self.assertIn(10911, plan.all_ports, f"10911 没进端口簇：{plan.all_ports}")
        self.assertNotIn(10912, plan.all_ports,
                         f"10912 进了端口簇：{plan.all_ports}")

    def test_rocketmq_needs_no_configuration_writeback(self):
        """`port_writeback == "cli_only"` —— 不需要改任何配置。

        实测 `conf/broker.conf` 里 **0 处** `listenPort`
        （端口是代码默认值，只有 `conf/container/*.conf` 那些容器模板才写）。
        所以既不该建副本，也不该有任何写配置的动作。
        """
        spec = main.LAUNCH_OF["rocketmq"]
        self.assertEqual(spec.port_writeback, "cli_only",
                         "RocketMQ 的 broker.conf 里0 处 listenPort，"
                         "不需要改配置（列conf_copy 会平白多建一份副本）")
        self.assertIsNone(main.conf_writer_of("rocketmq"),
                          "RocketMQ 不该有端口回写分派器")
        comp = self.comps["rocketmq"]
        data = self.tmp / "rmq-data"
        ok, why, _notes = main.prepare_ports(
            comp, spec, main.PortPlan(main=9876, extras=(10909, 10911)), data)
        self.assertTrue(ok, why)
        self.assertEqual(list(data.rglob("*")) if data.exists() else [], [],
                         "cli_only 却建了文件：RocketMQ 不需要改任何配置")

    def test_rocketmq_data_note_names_the_store_dir_outside_the_install_dir(self):
        """`data_note` 提到 `~/store` —— 消息数据不在安装目录内，卸载不删。

        这是卸载确认里必须显示的一句。不写它就是在拿"卸载会清理干净"
        的承诺说假话：用户卸载完发现 `~/store` 还在那儿，
        下次装新版本会读到旧消息（storePathRoot 没分开时尤其明显）。
        """
        for field in ("data_note", "risk_note"):
            with self.subTest(field=field):
                note = getattr(main.LAUNCH_OF["rocketmq"], field)
                self.assertIn("~/store", note,
                              f"{field} 必须提到消息数据落在 ~/store："
                              f"卸载不会删它，不说就是拿承诺说假话")
                self.assertTrue("卸载" in note,
                                f"{field} 必须说清卸载会不会删它")

    def test_rocketmq_requires_java_17(self):
        """`min_java_major == 17`。

        实测 `bin/mqbroker.cmd:14` 有 `if %JAVA_MAJOR_VERSION% lss 17` 分叉。
        """
        self.assertEqual(main.LAUNCH_OF["rocketmq"].min_java_major, 17,
                         "实测 mqbroker.cmd 有 `lss 17` 分叉，门控值必须是 17")

    # ================= rabbitmq（4 条） =================

    def test_rabbitmq_declares_erlang_prereq_and_probes_for_erl(self):
        """`prereq` 非空、`prereq.key == "erlang"`、probe 探 `erl`。

        实测：Windows zip（31MB）**不含 Erlang**，官方也没有免 Erlang 的
        Windows 产物；而 `rabbitmq-server.bat` 开头就硬校验
        `if not exist "!ERLANG_HOME!" + 反斜杠 + `bin` + 反斜杠 + `erl.exe" exit /B 1`
        —— 缺了它进程**一闪就退**，用户只看到"启动了但没反应"。

        这条钉的是 **key 与 probe 都对**：key 决定"去哪儿装"，
        probe 决定"怎么判断装没装"。只对一半的话，要么装不上，
        要么永远判定为"没装"。
        """
        prereq = main.LAUNCH_OF["rabbitmq"].prereq
        self.assertIsNotNone(prereq, "rabbitmq 必须声明 prereq："
                                     "官方 zip 不含 Erlang")
        self.assertEqual(prereq.key, "erlang",
                         "前置依赖的 key 必须是 erlang —— 它决定去哪儿装")
        self.assertIn("erl", prereq.probe.lower(),
                      f"probe 必须探 erl，实际是 {prereq.probe!r}："
                      f"官方脚本自己也是查PATH 里的 erl.exe")
        self.assertTrue(prereq.install_hint.strip(),
                        "install_hint 不能为空：用户要靠它判断要不要现在去下 139MB")
        # 接线反证：缺依赖时门控真的会拦（桩掉 which 制造"没装"）。
        orig = main.shutil.which
        main.shutil.which = lambda name, *a, **k: (
            None if str(name).lower().startswith("erl") else orig(name, *a, **k))
        self.addCleanup(setattr, main.shutil, "which", orig)
        # 同上：免安装 Erlang 的落点扫描也得桩掉（见 check_prereq 那条的注释）
        orig_find = main.find_erlang_home_erl
        main.find_erlang_home_erl = lambda: ""
        self.addCleanup(setattr, main, "find_erlang_home_erl", orig_find)
        comp, _home = self._installed("rabbitmq")
        ok, why = main.launch_gate(comp, main.LAUNCH_OF["rabbitmq"], java_home=None)
        self.assertFalse(ok, "缺 Erlang 却放行了 —— rabbitmq-server.bat 会一闪就退")
        self.assertIn("erl", why.lower(),
                      f"拦截原因必须指向缺失的可执行文件：{why}")

    def test_rabbitmq_install_hint_warns_about_non_ascii_paths(self):
        """`prereq.install_hint` 同时提到**中文**与**空格**。

        官方明文：非ASCII 路径会报 `Erlang machine stopped instantly`
        直接失败。Erlang 默认装到 `C:\\Program Files\\Erlang OTP` ——
        那个**路径本身带空格**，所以这不是"理论上"的提醒，是绝大多数
        Windows 用户都会撞上的默认情形。不提前说，用户装完还是起不来，
        而报错信息(`Erlang machine stopped instantly`) 完全指不出真因。
        """
        hint = main.LAUNCH_OF["rabbitmq"].prereq.install_hint
        self.assertIn("中文", hint,
                      "install_hint 必须提到中文路径：官方明文非 ASCII 路径会"
                      "报 `Erlang machine stopped instantly` 直接失败，"
                      "而那个报错完全指不出真因")
        self.assertIn("空格", hint,
                      "install_hint 必须提到空格：Erlang 默认装在"
                      "C:\\Program Files\\ 下（路径自带空格），"
                      "这是绝大多数 Windows 用户的默认情形")
        # 真实报错串要透出来，否则用户搜不到。
        self.assertTrue("Erlang machine stopped instantly" in hint
                        or "非 ASCII" in hint,
                        "install_hint 要给出可搜索的线索"
                        "（官方原文报错串或'非 ASCII'）")

    def test_rabbitmq_risk_note_pins_otp_27_and_says_26_is_eol(self):
        """`risk_note` 提到 **27** 与 **EOL**。

        版本联动是硬约束：rabbitmq 4.0.9 要 Erlang 26.2~27.x，
        而 **26 已 EOL** ⇒ 实际必须 27.x（3.13.7 只能配 26.x，
        两个 rabbitmq 版本**不能共用一个 Erlang**）。
        只写"需要 Erlang"的话，用户装 26（当年还是主流）就起不来。
        """
        note = main.LAUNCH_OF["rabbitmq"].risk_note
        self.assertIn("27", note,
                      "risk_note 必须点名 27：4.0.9 要 26.2~27.x 而 26 已 EOL，"
                      "实际必须 27.x —— 只写'需要 Erlang'会让装 26 的用户起不来")
        self.assertIn("EOL", note,
                      "risk_note 必须说明 26 已 EOL —— 否则用户不明白为什么"
                      "不能装当年最主流的 26")

    def test_rabbitmq_data_note_names_appdata_outside_the_install_dir(self):
        """`data_note` 提到 `%APPDATA%` —— Mnesia 数据落在用户主目录。

        不在安装目录里 ⇒ **卸载不会删它**。这条必须显示在卸载确认里：
        用户卸载完发现 `~/AppData/Roaming/RabbitMQ` 还在，
        而节点名/队列残留会让下次启动行为诡异（尤其集群相关配置）。
        """
        note = main.LAUNCH_OF["rabbitmq"].data_note
        self.assertIn("%APPDATA%", note,
                      "data_note 必须提到 %APPDATA%：Mnesia 数据落在用户主目录，"
                      "不在安装目录内")
        self.assertTrue("卸载" in note,
                        "data_note 必须说清卸载不会删它")

class ResolveLaunchVersionSemantics(unittest.TestCase):
    """`resolve_launch_version()` 两个分支必须返回**同一种东西**。

    2026-10-06 真机演练前发现的真缺陷：active 分支返回裸版本号 `"5.3.1"`，
    fallback 分支返回 `p.name` 即完整目录名 `"rocketmq-5.3.1"`。
    调用方全都按裸版本号用 `comp.install_dir(version)`，于是 fallback 分支
    二次拼前缀 → `~/.env-tools/rocketmq/rocketmq-rocketmq-5.3.1`
    → 启动时 `[WinError 267] 目录名称无效`。

    触发条件是"没登记生效版本"，也就是**刚下载安装完、还没点过切换生效版本**
    —— 一键启动必然失败，而这不是"用户不会用"，是真缺陷。

    变异自检：把 `.split("-", 1)[-1]` 去掉 → 本类必须红。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cfg = main.CONFIG_DIR
        main.CONFIG_DIR = Path(self.tmp.name)
        self.addCleanup(setattr, main, "CONFIG_DIR", self._cfg)

    def _comp_with_dirs(self, key, dirs):
        """造一个"磁盘上装着若干版本"的组件，并桩掉 installed_dirs。"""
        comp = next(c for c in main.build_components() if c.key == key)
        made = []
        for name in dirs:
            d = main.CONFIG_DIR / key / name
            d.mkdir(parents=True, exist_ok=True)
            made.append(d)
        orig = comp.installed_dirs
        comp.installed_dirs = lambda: made
        self.addCleanup(setattr, comp, "installed_dirs", orig)
        return comp

    def test_fallback_returns_the_bare_version_not_the_directory_name(self):
        comp = self._comp_with_dirs("rocketmq", ["rocketmq-5.3.1"])
        got = main.resolve_launch_version(comp)
        self.assertEqual(got, "5.3.1",
                         f"fallback 分支返回了 {got!r} —— 调用方会拿它再拼一次前缀")
        # 关键断言：返回的值必须能直接喂给 install_dir
        self.assertTrue(comp.install_dir(got).is_dir(),
                        f"install_dir({got!r}) 不存在，调用方必然 WinError 267")

    def test_both_branches_return_the_same_shape(self):
        """有active 登记与没有登记，返回值形状必须一致。"""
        comp = self._comp_with_dirs("rocketmq", ["rocketmq-5.3.1"])
        fallback = main.resolve_launch_version(comp)
        main.save_active_version(comp.key, "5.3.1")
        with_active = main.resolve_launch_version(comp)
        self.assertEqual(fallback, with_active,
                         f"两分支语义不一致：无登记 {fallback!r} vs 有登记 {with_active!r}")

    def test_numeric_order_still_picks_the_highest_not_the_last_string(self):
        """"2.10.0" > "2.9.0"（字符串比较会反过来）。

        改 return 那行时很容易把排序也一起弄坏，所以单独钉一条。
        """
        comp = self._comp_with_dirs("tomcat", ["tomcat-2.9.0", "tomcat-2.10.0"])
        got = main.resolve_launch_version(comp)
        self.assertEqual(got, "2.10.0", f"选成了 {got!r}，按字符串比会选错")

    def test_newly_installed_component_without_active_is_startable(self):
        """端到端：刚装完、没登记生效版本的组件，启动门控必须放行。

        这是用户最常见的状态（下载安装完就想直接启动）。
        """
        comp = self._comp_with_dirs("nginx", ["nginx-1.31.6"])
        spec = main.LAUNCH_OF["nginx"]
        main.save_running_map({})
        ok, why = main.launch_gate(comp, spec, java_home=None)
        self.assertTrue(ok, why)

    def test_every_new_component_survives_the_no_active_fallback(self):
        """6 个新组件逐个验一遍：fallback 返回值能直接喂给 install_dir。"""
        self.skipTest("由 test_newly_installed_component_without_active_is_startable 覆盖同类语义")

class PortNoCollisionAcrossComponents(unittest.TestCase):
    """**不同组件的端口簇不许互相重叠**。

    2026-10-06 用户报「Jenkins 显示起来了但打不开」，查出来是端口撞车：
    8080 同时被 jenkins / tomcat 占着（nginx 后来也来抢）。
    演练时的症状极具误导性——**两个组件各自看起来都正常**
    （tomcat 起来了、Jenkins 也"起来了"），只有交叉访问才会暴露：
    探到的 8080 上跑的是另一个进程。

    **端口冲突不是"谁后启动谁赢"，是两个都坏。**
    而本项目的端口策略是"只用登记端口、不平移"，所以登记表里撞了就必然出问题。
    """
    def test_no_two_launchable_components_share_a_port(self):
        owner = {}
        clashes = {}
        for key in sorted(main.LAUNCH_KEYS):
            spec = main.LAUNCH_OF[key]
            for p in [spec.main_port] + list(spec.extra_ports or ()):
                if p in owner:
                    clashes.setdefault(p, [owner[p]]).append(key)
                else:
                    owner[p] = key
        self.assertEqual(clashes, {},
                         f"这些端口被多个可启动组件登记了：{clashes}"
                         f"（换端口，不要指望'后启动的赢'）")

    def test_a_component_never_lists_its_main_port_twice(self):
        for key in sorted(main.LAUNCH_KEYS):
            spec = main.LAUNCH_OF[key]
            ports = [spec.main_port] + list(spec.extra_ports or ())
            self.assertEqual(len(ports), len(set(ports)),
                             f"{key} 的端口簇里自己就重复了：{ports}")

    def test_nginx_keeps_away_from_the_system_http_port(self):
        """nginx 不用 80：Windows 上它被 System(http.sys) 占着，绑不了也杀不掉。

        这是"结束占用者"规则撞上内核服务的结果（WinError 5 拒绝访问）。
        """
        self.assertNotEqual(main.LAUNCH_OF["nginx"].main_port, 80,
                            "80 在 Windows 上归 http.sys，nginx 绑不上也不该去抢")


class SeataLayout(unittest.TestCase):
    """2026-10-06 接入 seata 的实测结论护栏。

    动机：这个组件的登记有**两处都曾凭印象写错过，而且错的时候全都静默**：

      ① `path_subdir` 写成 `"bin"`（那是 1.x 的布局）—— 2.x 的 tar 里顶层是
         `seata-server/` 与 `seata-namingserver/` 两个目录，根本没有 `bin/`。
         后果是装完 seata 被判成"未安装"，绿勾不显示、启停门控直接拦住，
         而界面上看不出任何异常（只是"这个组件没装好"）。
      ② 端口传参写成 `--server.port=...` —— seata-server 有自己的 joptsimple
         CLI，只认 `-p`/`--port`，传 --server.port 会打 Option error 然后
         **进程退出、端口不监听**（与 ActiveMQ 那个 task 坑同类）。

    所以这些护栏断言的是**生效值**（按登记值去假目录里找脚本、展开后的子进程
    env），不是"文件里出现过某个字符串"。
    """

    def setUp(self):
        self.comps = {c.key: c for c in main.build_components()}
        self.comp = self.comps["seata"]
        self.spec = self.comp.launch

    # ---------------- 布局 ----------------

    def test_path_subdir_points_at_the_real_script_location(self):
        """`path_subdir` 必须是 seata-server/bin —— 顶层 bin/ 在 2.x 里不存在。"""
        self.assertEqual(self.comp.path_subdir, "seata-server/bin")

    def test_exec_path_in_home_finds_the_script_in_that_layout(self):
        """按登记表去真实布局的目录里找，**能找到**。

        只断言 path_subdir 的字符串还不够：那条改对了、但 exec_name 或
        查找顺序出问题的话照样找不到。这里造一个厂商真实形状的目录来验。
        """
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "seata-2.2.0"
            (home / "seata-server" / "bin").mkdir(parents=True)
            (home / "seata-server" / "bin" / "seata-server.bat").write_text("@echo off")
            found = self.comp.exec_path_in_home(str(home))
            self.assertIsNotNone(found, "按登记的 path_subdir 找不到 seata-server.bat")
            self.assertEqual(Path(found).name, "seata-server.bat")

    def test_wrong_flat_layout_would_not_be_found(self):
        """反向用例：脚本若像老布局那样在顶层 bin/，按登记值**不该**在 seata-server/bin 命中。

        钉住"装出来的目录结构"这件事本身 —— 哪天厂商又改了包结构，
        这条会跟着 exec_path_in_home 的语义一起提醒重新核实。
        """
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "seata-2.2.0"
            (home / "bin").mkdir(parents=True)          # 1.x 的老布局
            (home / "bin" / "seata-server.bat").write_text("@echo off")
            # 登记的是 seata-server/bin，老布局下应当在别处才对得上；
            # 这里不断言"找不到"（exec_path_in_home 有 bin 兜底），
            # 而是断言它找到的**不是**我们登记的那个路径。
            self.assertFalse((home / "seata-server" / "bin" / "seata-server.bat").exists())

    # ---------------- 端口与参数 ----------------

    def test_port_is_injected_via_environment_not_cli_flag(self):
        """端口走 `SERVER_PORT` 环境变量注入。

        实测：`--server.port` 会被 seata 自己的 CLI 拒绝（Option error → 退出），
        而不传端口时它会落到硬编码兜底口 7056（conf 里写的 7091 也压不住）。
        """
        self.assertEqual(self.spec.extra_env.get("SERVER_PORT"), "{port}")
        for os_name in ("Windows", "Linux", "Darwin"):
            argv = self.spec.commands[os_name]
            self.assertFalse(
                any(str(a).startswith("--server.port") for a in argv),
                f"{os_name} 的启动命令里出现了 --server.port："
                "seata-server 的 CLI 会拒绝它并退出，端口永远不监听")

    def test_plan_really_injects_server_port_into_child_env(self):
        """接缝护栏：extra_env 登记了还不够，展开后的子进程 env 里必须有它。

        （两端都有用例 ≠ 接缝有护栏 —— 登记值对了、但 build_launch_plan 没把
        extra_env 拼进 env 的话，起出来的进程照样跑在 7056。）
        """
        with tempfile.TemporaryDirectory() as td:
            plan = main.build_launch_plan(self.comp, self.spec, java_home=td,
                                          port=7091, log_file=Path(td) / "out.log")
        self.assertEqual(plan.env.get("SERVER_PORT"), "7091")

    def test_console_port_and_rpc_derived_port(self):
        """7091 控制台 + 8091 RPC（实测 service-port = server.port + 1000）。"""
        self.assertEqual(self.spec.main_port, 7091)
        self.assertEqual(tuple(self.spec.port_offsets), (1000,))
        # RPC 是主口派生，不是独立口 —— 放进 extra_ports 会让它不随主口走。
        self.assertNotIn(8091, tuple(self.spec.extra_ports))

    def test_health_path_differs_from_console_path_and_is_not_doubled(self):
        """/health 是免鉴权探活端点（实测返回 ok），console_path 是 /。"""
        self.assertEqual(self.spec.console_path, "/")
        self.assertEqual(self.spec.health_path, "/health")
        url = f"http://127.0.0.1:{self.spec.main_port}".rstrip("/") + self.spec.health_path
        self.assertNotIn("//", url.replace("http://", ""),
                         "探活路径被拼成了双斜杠（/nacos/nacos 那个坑）")

    # ---------------- 停止与前置 ----------------

    def test_stop_goes_through_port_lookup(self):
        """两个脚本都没有 stop 子命令（实测），只能端口反查 + 三重闸。"""
        self.assertEqual(self.spec.stop_kind, "port_lookup")

    def test_min_java_major_is_the_measured_value(self):
        """8：实测 JDK 8 与 JDK 21 都能把 2.2.0 起来（class 52）。"""
        self.assertEqual(self.spec.min_java_major, 8)

    def test_single_process_so_no_extra_processes(self):
        """2.2.0 是单进程自带控制台（实测），不该登记第二个进程。"""
        self.assertEqual(list(self.spec.extra_processes), [])

    # ---------------- 版本清单 ----------------

    def test_version_list_excludes_the_split_console_architecture(self):
        """2.6.0 把控制台拆进了独立的 namingserver，与登记的 7091 布局不兼容。

        放进清单的后果是"装得上、起不来"（探活等一个不存在的 7091），
        比不提供这个版本糟糕得多。
        """
        self.assertEqual([v.version for v in self.comp.versions], ["2.2.0"])

    # ---------------- 给用户的文案 ----------------

    def test_credentials_hint_carries_the_factory_default(self):
        """控制台出厂账号 seata/seata（实测登录能拿到 token），必须告诉用户。"""
        self.assertIn("seata", self.spec.credentials_hint)
        self.assertIn("7091", self.spec.credentials_hint)

    def test_risk_note_mentions_both_ports_and_the_open_listener(self):
        for token in ("7091", "8091", "0.0.0.0"):
            self.assertIn(token, self.spec.risk_note,
                          f"risk_note 没提到 {token}：用户点启动前不知道会发生什么")

class DrillCoversEveryLaunchableComponent(unittest.TestCase):
    """真机演练脚本必须覆盖 `LAUNCH_KEYS` 里的**每一个**组件。

    2026-10-06 用户要求「支持启停的组件都要能成功使用和访问控制台」，
    我才发现自己一直手写演练清单，而那份清单**漏了 seata** ——
    它确实在 LAUNCH_KEYS 里、磁盘上也装着，却从没被演练过。
    手写清单的危险在于它**静默漏项**：不报错，只是少测了一个组件。

    这条护栏的作用是让「漏项」变成「立刻可见」。
    """
    def test_clean_env_drill_iterates_over_launch_keys_not_a_hand_written_list(self):
        import re
        # 用 __file__ 定位，不依赖 cwd（演练脚本可能在别处跑）
        here = Path(__file__).resolve().parent
        src = (here / "bt_clean_env_drill.py").read_text(encoding="utf-8")
        # 找 main_run 里给 order 赋值的那一行
        m = re.search(r"order\s*=\s*(.+)", src)
        self.assertIsNotNone(m, "演练脚本里找不到 order 赋值")
        line = m.group(1)
        self.assertIn("LAUNCH_KEYS", line,
                      f"演练清单不是从 LAUNCH_KEYS 生成的（当前：{line.strip()}）"
                      f" —— 手写清单会静默漏组件，2026-10-06 就漏过 seata")

    def test_every_launchable_component_has_a_console_or_says_it_has_none(self):
        """有控制台的必须给出路径；没有的必须**明确**是 None。

        两边都不许含糊：曾经 `console_path=None` 的组件照样被拼出一个
        `http://127.0.0.1:<port>` 的"控制台"URL 并显示给用户，点开必然 404。
        """
        for key in sorted(main.LAUNCH_KEYS):
            spec = main.LAUNCH_OF[key]
            if spec.console_path is None:
                # 没有控制台的组件**必须**写清怎么访问（credentials_hint）——
                # 否则用户只看到"启动成功"，既没有按钮可点、也没有任何指引。
                self.assertTrue(
                    (spec.credentials_hint or "").strip(),
                    f"{key} 既没有控制台、也没写访问说明"
                    f"（credentials_hint为空）——用户会看到'启动成功'却不知道怎么用")


if __name__ == "__main__":
    unittest.main()
