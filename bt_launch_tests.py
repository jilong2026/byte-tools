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


if __name__ == "__main__":
    unittest.main()
