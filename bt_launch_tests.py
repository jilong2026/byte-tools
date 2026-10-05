"""一键启动护栏（离线）。设计文档见 docs/superpowers/specs/2026-10-05-one-click-launch-design.md"""
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
from PySide6.QtWidgets import QApplication  # noqa: E402  要构造 QThread 子类得有 QApplication


class LaunchSpecTable(unittest.TestCase):
    def setUp(self):
        self.comps = {c.key: c for c in main.build_components()}

    def test_launch_keys_are_exactly_jenkins(self):
        self.assertEqual(main.LAUNCH_KEYS, {"jenkins"},
                         "计划一启动白名单只有 jenkins，扩白名单属计划二")

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
        """登记里出现本期不认识的可启动组件（计划二加的），不许被误删。"""
        other = main.RunRecord(key="nacos", version="2.3.2", home="/h", data_dir="/d",
                               port=8848, console_url="http://127.0.0.1:8848/",
                               pid=1, pid_role="none", started_at=0.0, launcher_cmd=[])
        main.save_running_map({"nacos": other})
        st = self.mgr(listening=True, alive=True).reconcile(self.comps)
        self.assertNotIn("nacos", st, "没登记的组件不该被本工具接管")
        self.assertIn("nacos", main.load_running_map())


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

    def test_frees_port_by_shifting_cluster_when_8080_taken(self):
        orig = main.port_is_free
        main.port_is_free = lambda port, host="127.0.0.1": port != 8080
        self.addCleanup(setattr, main, "port_is_free", orig)
        res = self.mgr(listening_after=1).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(main.load_running_map()["jenkins"].port, 8081)


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
        self.assertIn("别的进程", res2.reason)
        self.assertIn("jenkins", main.load_running_map(), "rounds 耗尽仍监听时不许清登记")

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
        self.assertEqual(logs, [("warn", "[Jenkins] 操作未完成（窗口正在关闭）：已取消等待")],
                         "不弹框也要在日志里留一句去向")


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


if __name__ == "__main__":
    unittest.main()
