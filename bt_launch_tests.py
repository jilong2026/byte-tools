"""一键启动护栏（离线）。设计文档见 docs/superpowers/specs/2026-10-05-one-click-launch-design.md"""
import json
import os
import platform as _platform
import socket
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
