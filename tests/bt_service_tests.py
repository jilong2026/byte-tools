"""MySQL / Redis 的 Windows 服务模式护栏（离线，全部走 FakeServiceBackend）。

这一套钉的是"服务模式下最容易把人坑死"的几条：
  · 状态认定只读 SCM，绝不执行、绝不启停；
  · running.json 里没有登记时也要能认出"服务在跑"；
  · 同端口只能跑一个版本；端口被外部占用就拒绝，不替用户杀进程；
  · 卸载必须"先删服务、校验注册表键没了，才删目录"，1072 不许谎报成功；
  · 密码不进 argv；
  · Redis 资产必须是 -with-Service 变体。
"""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _btprelude  # noqa: F401  必须早于 import main

import main  # noqa: E402


class FakeServiceBackend:
    """内存版 SCM：query 只读，control 是唯一的写入口。"""

    def __init__(self):
        self.services = {}
        self.calls = []
        self.control_should_raise = False

    def supported(self):
        return True

    def query(self, name):
        self.calls.append(("query", name))
        return copy.deepcopy(self.services.get(name, main.ServiceInfo(name=name)))

    def registry_key_exists(self, name):
        self.calls.append(("registry", name))
        return name in self.services

    def control(self, name, code):
        if self.control_should_raise:
            raise AssertionError("状态认定路径不许碰 control()")
        self.calls.append(("control", name, code))
        info = self.services.get(name)
        if info is None:
            return main.ERROR_SERVICE_DOES_NOT_EXIST
        if code == main.SERVICE_CONTROL_STOP:
            info.state = main.SERVICE_STOPPED
        return 0

    def start(self, name):
        if self.control_should_raise:
            raise AssertionError("状态认定路径不许碰 start()")
        self.calls.append(("start", name))
        info = self.services.get(name)
        if info is None:
            return main.ERROR_SERVICE_DOES_NOT_EXIST
        info.state = main.SERVICE_RUNNING
        return 0


class ServiceTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comps = {c.key: c for c in main.build_components()}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._old_conf = main.CONFIG_DIR
        self._old_running = main.RUNNING_FILE
        self._old_backend = main.SERVICE_BACKEND
        self._old_listening = main.port_is_listening
        self._old_page = main.get_page_server
        main.CONFIG_DIR = root / ".env-tools"
        main.RUNNING_FILE = main.CONFIG_DIR / "running.json"
        self.backend = FakeServiceBackend()
        main.SERVICE_BACKEND = self.backend
        self.listening = set()
        main.port_is_listening = lambda port, host="127.0.0.1": port in self.listening
        main.get_page_server = lambda: None

    def tearDown(self):
        main.CONFIG_DIR = self._old_conf
        main.RUNNING_FILE = self._old_running
        main.SERVICE_BACKEND = self._old_backend
        main.port_is_listening = self._old_listening
        main.get_page_server = self._old_page

    # --- 造数据 ---------------------------------------------------------
    def ready(self, key, version):
        comp = self.comps[key]
        home = comp.install_dir(version)
        for rel in main.service_spec_for(comp).required_files:
            target = home / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"MZ")
        return comp

    def add_service(self, comp, version, state=main.SERVICE_STOPPED, image=None):
        spec = main.service_spec_for(comp)
        name = main.service_name_for(spec, version)
        self.backend.services[name] = main.ServiceInfo(
            name=name, exists=True, state=state,
            image_path=image if image is not None else str(
                comp.install_dir(version) / spec.required_files[0]),
            start_type="demand")
        return name


class ServiceSpecTable(ServiceTestBase):
    def test_only_mysql_and_redis_have_a_service_spec(self):
        keys = {k for k, c in self.comps.items() if main.service_spec_for(c) is not None}
        self.assertEqual(keys, {"mysql", "redis"})

    def test_service_names_are_valid_and_deterministic(self):
        for key in ("mysql", "redis"):
            spec = main.service_spec_for(self.comps[key])
            name = main.service_name_for(spec, "8.0.37")
            self.assertRegex(name, main.SERVICE_NAME_RE.pattern)
            self.assertEqual(name, main.service_name_for(spec, "8.0.37"))
            self.assertIn("8.0.37", name)

    def test_service_names_are_per_version(self):
        spec = main.service_spec_for(self.comps["mysql"])
        self.assertNotEqual(main.service_name_for(spec, "8.0.37"),
                            main.service_name_for(spec, "8.0.36"))

    def test_redis_requires_the_service_exe(self):
        spec = main.service_spec_for(self.comps["redis"])
        self.assertIn("RedisService.exe", spec.required_files)


class ServiceStatusReadOnly(ServiceTestBase):
    def test_status_and_adopt_never_execute_anything(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_RUNNING)
        self.listening.add(3306)
        self.backend.control_should_raise = True
        mgr = main.ServiceManager(is_listening=lambda p: p in self.listening)
        with mock.patch.object(main.subprocess, "run",
                               side_effect=AssertionError("状态认定不许跑子进程")), \
                mock.patch.object(main.subprocess, "Popen",
                                  side_effect=AssertionError("状态认定不许起进程")):
            st = mgr.status("mysql", comp)
            adopted = mgr.adopt(self.comps)
            mgr.reconcile(self.comps)
        self.assertEqual(st.state, "running")
        self.assertEqual(st.record.service_name, "ByteTools-MySQL-8.0.37")
        self.assertTrue(all(s.state != "running" or s.record is not None
                            for s in adopted if s.record is not None))
        self.assertFalse([c for c in self.backend.calls if c[0] == "control"])

    def test_running_service_with_silent_port_is_zombie(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_RUNNING)
        mgr = main.ServiceManager(is_listening=lambda p: False)
        self.assertEqual(mgr.status("mysql", comp).state, "zombie")


class ServiceRecordBackfill(ServiceTestBase):
    def test_running_service_is_backfilled_without_running_json(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_RUNNING)
        self.listening.add(3306)
        mgr = main.ServiceManager(is_listening=lambda p: p in self.listening)
        self.assertFalse(main.RUNNING_FILE.exists())
        mgr.backfill_service_records(self.comps)
        rec = main.load_running_map()["mysql"]
        self.assertEqual(rec.pid_role, "service")
        self.assertEqual(rec.service_name, "ByteTools-MySQL-8.0.37")
        self.assertEqual(rec.version, "8.0.37")
        self.assertEqual(rec.pid, 0)

    def test_stopped_service_produces_no_record(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED)
        mgr = main.ServiceManager(is_listening=lambda p: False)
        mgr.backfill_service_records(self.comps)
        self.assertNotIn("mysql", main.load_running_map())

    def test_stale_service_record_is_dropped(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED)
        main.save_running_map({"mysql": main.RunRecord(
            key="mysql", version="8.0.37", home=str(comp.install_dir("8.0.37")),
            data_dir="", port=3306, console_url="", pid=0, pid_role="service",
            started_at=0.0, launcher_cmd=[], ports=(3306,),
            service_name="ByteTools-MySQL-8.0.37")})
        mgr = main.ServiceManager(is_listening=lambda p: False)
        mgr.backfill_service_records(self.comps)
        self.assertNotIn("mysql", main.load_running_map())


class ServiceStartRefusesPeerService(ServiceTestBase):
    def test_another_version_running_blocks_start(self):
        self.ready("mysql", "8.0.36")
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.36", main.SERVICE_RUNNING)
        mgr = main.ServiceManager(is_listening=lambda p: False)
        res = mgr.start(comp, self.comps, version="8.0.37", sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("8.0.36", res.reason)
        self.assertFalse([c for c in self.backend.calls if c[0] == "control"])


class ServiceStartUsesStartServiceApi(ServiceTestBase):
    def test_start_goes_through_start_service_api_not_control(self):
        """真机 2026-10-29：启动误走 ControlService(SERVICE_START) 回 87。"""
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED)
        started = {"v": False}
        orig_start = self.backend.start

        def start_and_flag(name):
            started["v"] = True
            self.listening.add(3306)
            return orig_start(name)

        self.backend.start = start_and_flag
        mgr = main.ServiceManager(is_listening=lambda p: p in self.listening)
        res = mgr.start(comp, self.comps, version="8.0.37", sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertIn(("start", "ByteTools-MySQL-8.0.37"), self.backend.calls)
        self.assertFalse([c for c in self.backend.calls if c[0] == "control"])
        self.assertEqual(main.load_running_map()["mysql"].pid_role, "service")

    def test_backend_control_refuses_the_start_code(self):
        with self.assertRaises(ValueError):
            main.WindowsServiceBackend().control("ByteTools-MySQL-8.0.37", 0x0010)


class ServicePortConflictPolicy(ServiceTestBase):
    def test_foreign_listener_blocks_start_and_is_not_evicted(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED)
        self.listening.add(3306)
        mgr = main.ServiceManager(is_listening=lambda p: p in self.listening)
        with mock.patch.object(main, "netstat_listener_pids", return_value={3306: 4242}), \
                mock.patch.object(main.os, "kill",
                                  side_effect=AssertionError("不许杀别人的进程")):
            res = mgr.start(comp, self.comps, version="8.0.37", sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("3306", res.reason)
        self.assertIn("4242", res.reason)


class ServiceInstallFlow(ServiceTestBase):
    def test_uac_cancelled_changes_nothing(self):
        comp = self.ready("mysql", "8.0.37")
        (main.CONFIG_DIR / "mysql-data" / "mysql").mkdir(parents=True)
        with mock.patch.object(main, "_run_service_script",
                               return_value={"ok": False, "cancelled": True,
                                             "error": "已取消", "steps": [],
                                             "marked_for_delete": False}):
            res = main.install_service(comp, "8.0.37")
        self.assertFalse(res.ok)
        self.assertTrue(res.cancelled)
        self.assertEqual(self.backend.services, {})
        self.assertTrue(comp.install_dir("8.0.37").is_dir())

    def test_install_registers_the_service_with_the_expected_script(self):
        comp = self.ready("mysql", "8.0.37")
        (main.CONFIG_DIR / "mysql-data" / "mysql").mkdir(parents=True)
        seen = {}

        def fake_script(body, timeout=300.0):
            seen["body"] = body
            self.add_service(comp, "8.0.37", main.SERVICE_STOPPED)
            return {"ok": True, "cancelled": False, "error": "", "steps": [],
                    "marked_for_delete": False}

        with mock.patch.object(main, "_run_service_script", side_effect=fake_script):
            res = main.install_service(comp, "8.0.37")
        self.assertTrue(res.ok, res.message)
        self.assertIn("--install", seen["body"])
        self.assertIn("ByteTools-MySQL-8.0.37", seen["body"])
        self.assertIn("'start=' 'demand'", seen["body"])
        ini = main.service_config_path(comp, "8.0.37")
        self.assertTrue(ini.is_file())
        self.assertIn("datadir=", ini.read_text(encoding="utf-8"))


class ServiceUninstallSafety(ServiceTestBase):
    def test_service_is_stopped_before_it_is_deleted(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_RUNNING)
        order = []

        def fake_stop(*_a, **_k):
            order.append("stop")
            return main.ServiceActionResult(True, message="stopped")

        def fake_script(body, timeout=300.0):
            order.append("delete")
            self.backend.services.pop("ByteTools-MySQL-8.0.37", None)
            return {"ok": True, "cancelled": False, "error": "", "steps": [],
                    "marked_for_delete": False}

        with mock.patch.object(main, "stop_service", side_effect=fake_stop), \
                mock.patch.object(main, "_run_service_script", side_effect=fake_script):
            res = main.uninstall_service(comp, "8.0.37")
        self.assertTrue(res.ok, res.message)
        self.assertEqual(order, ["stop", "delete"])

    def test_service_failure_blocks_directory_deletion(self):
        comp = self.ready("mysql", "8.0.37")
        with mock.patch.object(main, "uninstall_service",
                               return_value=main.ServiceActionResult(
                                   False, message="服务删不掉，需要重启")), \
                mock.patch.object(main.shutil, "rmtree",
                                  side_effect=AssertionError("服务没删掉就不许删目录")):
            summary = comp.uninstall("8.0.37")
        self.assertIn("卸载中止", summary)
        self.assertIn("需要重启", summary)

    def test_missing_service_is_idempotent(self):
        comp = self.ready("mysql", "8.0.37")
        res = main.uninstall_service(comp, "8.0.37")
        self.assertTrue(res.ok)
        res2 = main.uninstall_service(comp, "8.0.37")
        self.assertTrue(res2.ok)

    def test_registry_key_left_behind_is_not_reported_as_success(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED)
        with mock.patch.object(main, "_run_service_script",
                               return_value={"ok": False, "cancelled": False,
                                             "error": "1072", "steps": [],
                                             "marked_for_delete": True}):
            res = main.uninstall_service(comp, "8.0.37")
        self.assertFalse(res.ok)
        self.assertIn("重启", res.message)
        self.assertTrue(comp.install_dir("8.0.37").is_dir())

    def test_service_uninstall_never_deletes_directories(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED)
        with mock.patch.object(main, "_run_service_script",
                               return_value={"ok": True, "cancelled": False,
                                             "error": "", "steps": [],
                                             "marked_for_delete": False}), \
                mock.patch.object(main.shutil, "rmtree",
                                  side_effect=AssertionError("删目录不是这一层的事")):
            self.backend.services.pop("ByteTools-MySQL-8.0.37")
            res = main.uninstall_service(comp, "8.0.37")
        self.assertTrue(res.ok)
        self.assertTrue(comp.install_dir("8.0.37").is_dir())


class PreinstallChecks(ServiceTestBase):
    def test_foreign_service_with_our_name_is_refused(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED,
                         image=r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe")
        res = main.install_service(comp, "8.0.37")
        self.assertFalse(res.ok)
        self.assertIn("不是本工具安装的", res.message)

    def test_stale_own_service_is_treated_as_already_installed(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED)
        res = main.install_service(comp, "8.0.37")
        self.assertTrue(res.ok)
        self.assertIn("已经存在", res.message)

    def test_image_ownership_never_matches_foreign_installs(self):
        comp = self.comps["mysql"]
        ours = str(comp.install_dir("8.0.37") / "bin" / "mysqld.exe")
        self.assertTrue(main.service_image_is_ours(f'"{ours}" --defaults-file=x', comp))
        self.assertFalse(main.service_image_is_ours(
            r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe", comp))

    def test_image_ownership_accepts_the_raw_root_when_resolve_differs(self):
        """CI（GitHub Runner）的 TEMP 是 junction：ImagePath 是原始路径，
        `resolve()` 却会换成另一端的前缀。两种形式都必须认，否则我们自己的服务
        会被判成"别人的 MySQL"，安装/卸载直接被拒。"""
        import subprocess

        base = Path(self._tmp.name)
        real = base / "real"
        real.mkdir()
        link = base / "link"
        try:
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(real)],
                           check=True, capture_output=True)
        except Exception:  # noqa: BLE001
            self.skipTest("当前环境不允许创建 junction，跳过")
        old = main.CONFIG_DIR
        main.CONFIG_DIR = link / ".env-tools"
        self.addCleanup(setattr, main, "CONFIG_DIR", old)
        ours = str(link / ".env-tools" / "mysql" / "mysql-8.0.37" / "bin" / "mysqld.exe")
        self.assertNotEqual(str((main.CONFIG_DIR / "mysql").resolve()),
                            str(main.CONFIG_DIR / "mysql"),
                            "前提：resolve 必须真的跳到了另一端")
        self.assertTrue(main.service_image_is_ours(ours, self.comps["mysql"]))


class PasswordNeverInArgv(ServiceTestBase):
    def test_password_only_travels_on_stdin_and_the_option_file(self):
        comp = self.ready("mysql", "8.0.37")
        exe = comp.install_dir("8.0.37") / "bin" / "mysql.exe"
        exe.write_bytes(b"MZ")
        sentinel = "Sentinel!p@ss-2026"
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((list(argv), kwargs.get("input") or b""))
            return mock.Mock(returncode=0, stdout=b"1\n")

        with mock.patch.object(main.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(main, "_harden_file_acl", lambda _p: None):
            ok, why = main.mysql_set_root_password(comp, "8.0.37", 3306, sentinel)
        self.assertTrue(ok, why)
        self.assertEqual(len(calls), 2, "改密码 + 用新密码复核，缺一不可")
        for argv, payload in calls:
            self.assertNotIn(sentinel, " ".join(argv))
            # MySQL 只在参数扫描最开头认 --defaults-extra-file，放到后面就是 87/7
            self.assertTrue(argv[1].startswith("--defaults-extra-file="), argv)
        self.assertIn(sentinel.encode("utf-8"), calls[0][1])
        self.assertIn(b"SELECT 1", calls[1][1])

    def test_failed_verification_is_not_reported_as_success(self):
        comp = self.ready("mysql", "8.0.37")
        (comp.install_dir("8.0.37") / "bin" / "mysql.exe").write_bytes(b"MZ")
        results = [mock.Mock(returncode=0, stdout=b""),
                   mock.Mock(returncode=1, stdout=b"ERROR 1045 (28000): Access denied")]

        with mock.patch.object(main.subprocess, "run", side_effect=results), \
                mock.patch.object(main, "_harden_file_acl", lambda _p: None):
            ok, why = main.mysql_set_root_password(comp, "8.0.37", 3306, "pw")
        self.assertFalse(ok)
        self.assertIn("复核失败", why)
        self.assertIn("1045", why)

    def test_newline_in_password_is_rejected_before_running_anything(self):
        comp = self.ready("mysql", "8.0.37")
        with mock.patch.object(main.subprocess, "run",
                               side_effect=AssertionError("不许执行")):
            ok, why = main.mysql_set_root_password(comp, "8.0.37", 3306, "a\nb")
        self.assertFalse(ok)
        self.assertIn("换行", why)


class RedisPasswordVerification(ServiceTestBase):
    """Redis 的 requirepass 必须"设完真验"，且密码不进 argv（走 REDISCLI_AUTH）。"""

    def test_password_goes_in_env_not_argv_and_noauth_must_be_enforced(self):
        comp = self.ready("redis", "8.10.2")
        sentinel = "Sentinel!p@ss-2026"
        outputs = [b"PONG", b"(error) NOAUTH Authentication required."]
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((list(argv), dict(kwargs.get("env") or {})))
            return mock.Mock(returncode=0, stdout=outputs[len(calls) - 1])

        with mock.patch.object(main.subprocess, "run", side_effect=fake_run):
            ok, why = main.redis_verify_auth(comp, "8.10.2", 6379, sentinel)
        self.assertTrue(ok, why)
        self.assertEqual(calls[0][1].get("REDISCLI_AUTH"), sentinel)
        for argv, _env in calls:
            self.assertNotIn(sentinel, " ".join(argv))
        self.assertNotIn("REDISCLI_AUTH", calls[1][1], "匿名复核必须显式去掉环境变量")

    def test_password_not_enforced_is_reported_as_failure(self):
        comp = self.ready("redis", "8.10.2")
        with mock.patch.object(main.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout=b"PONG")):
            ok, why = main.redis_verify_auth(comp, "8.10.2", 6379, "pw")
        self.assertFalse(ok)
        self.assertIn("requirepass 没有生效", why)

    def test_wrong_password_is_reported(self):
        comp = self.ready("redis", "8.10.2")
        with mock.patch.object(main.subprocess, "run",
                               return_value=mock.Mock(
                                   returncode=0,
                                   stdout=b"WRONGPASS invalid username-password pair")):
            ok, why = main.redis_verify_auth(comp, "8.10.2", 6379, "pw")
        self.assertFalse(ok)
        self.assertIn("WRONGPASS", why)

    def test_unauthenticated_ping_needs_a_password(self):
        comp = self.ready("redis", "8.10.2")
        with mock.patch.object(main.subprocess, "run",
                               return_value=mock.Mock(
                                   returncode=0,
                                   stdout=b"(error) NOAUTH Authentication required.")):
            ok, why = main.redis_verify_auth(comp, "8.10.2", 6379, "")
        self.assertFalse(ok)
        self.assertIn("要求密码", why)


class RedisConfQuoting(ServiceTestBase):
    def test_password_with_spaces_and_quotes_is_quoted(self):
        comp = self.ready("redis", "8.10.2")
        path = main.write_redis_conf(comp, "8.10.2", 6379, 'a b"c\\d')
        text = path.read_text(encoding="utf-8")
        self.assertIn('requirepass "a b\\"c\\\\d"', text)
        self.assertIn('dir "', text, "路径要加引号，带空格时才不会读错")

    def test_newline_in_password_is_refused(self):
        comp = self.ready("redis", "8.10.2")
        with self.assertRaises(ValueError):
            main.write_redis_conf(comp, "8.10.2", 6379, "a\nb")


class ServiceScriptShape(ServiceTestBase):
    def test_sddl_grant_is_idempotent_and_has_a_rollback(self):
        body = main._grant_user_control_ps("ByteTools-MySQL-8.0.37")
        self.assertIn("sdshow", body)
        self.assertIn("sdset", body)
        self.assertIn("acl_rollback", body)
        self.assertIn("-notlike", body, "已有 SID 时必须跳过，避免重复追加 ACE")

    def test_uninstall_script_checks_the_registry_key(self):
        comp = self.ready("mysql", "8.0.37")
        body = main._uninstall_service_body(comp, "8.0.37")
        self.assertIn("--remove", body)
        self.assertIn("$sc delete", body)
        self.assertIn("marked_for_delete", body)

    def test_redis_install_uses_the_documented_cli(self):
        """RedisService.exe --help 实测：install / uninstall / run，没有 --service-run。"""
        comp = self.ready("redis", "8.10.2")
        body = main._install_service_body(comp, "8.10.2")
        self.assertIn("install -c $conf", body)
        self.assertIn("--start-mode manual", body)
        self.assertIn("run -c", body)
        self.assertNotIn("--service-run", body)
        self.assertIn("--display-name", body)


class CredentialsHintRendering(ServiceTestBase):
    def test_mysql_hint_carries_the_real_port_and_no_html_tags(self):
        """日志是富文本：`<端口>` 会被当标签吞掉，真机上就是这么少了一段。"""
        comp = self.comps["mysql"]
        text = "\n".join(main.credentials_for(comp, comp.launch, 3306))
        self.assertIn("-P 3306", text)
        self.assertNotIn("<端口>", text)
        self.assertIn("-u root", text)

    def test_redis_hint_carries_the_real_port(self):
        comp = self.comps["redis"]
        text = "\n".join(main.credentials_for(comp, comp.launch, 6379))
        self.assertIn("-p 6379", text)
        self.assertNotIn("<端口>", text)


class MysqlVersionProbe(ServiceTestBase):
    """版本列表里不许出现"三个源全 404"的幽灵版本（真机 8.0.38/8.0.39）。"""

    class _Resp:
        def __init__(self, code):
            self.status_code = code

    def test_only_versions_with_a_real_windows_zip_are_reported(self):
        with mock.patch.object(main, "http_session") as sess:
            sess.return_value.head.return_value = self._Resp(404)
            self.assertIs(main._mysql_zip_exists("8.0.38"), False)
            sess.return_value.head.return_value = self._Resp(200)
            self.assertIs(main._mysql_zip_exists("8.0.37"), True)
            sess.return_value.head.side_effect = OSError("offline")
            self.assertIsNone(main._mysql_zip_exists("8.0.36"))


class RedisAssetShape(ServiceTestBase):
    def test_redis_urls_point_to_the_with_service_zip(self):
        urls = main._redis_urls("8.10.2")["Windows"]
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(url.endswith("Redis-8.10.2-Windows-x64-msys2-with-Service.zip"),
                            url)


class ServiceBrokenDetection(ServiceTestBase):
    def test_service_pointing_at_a_deleted_exe_is_broken(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED,
                         image=str(comp.install_dir("8.0.37") / "bin" / "gone.exe"))
        info = main.service_info(comp, "8.0.37")
        self.assertEqual(info.state, main.SERVICE_BROKEN)
        mgr = main.ServiceManager(is_listening=lambda p: False)
        self.assertEqual(mgr.status("mysql", comp).state, "broken")
        res = mgr.start(comp, self.comps, version="8.0.37", sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("服务损坏", res.reason)

    def test_missing_required_file_marks_the_service_broken(self):
        comp = self.ready("redis", "8.10.2")
        self.add_service(comp, "8.10.2", main.SERVICE_STOPPED)
        (comp.install_dir("8.10.2") / "RedisService.exe").unlink()
        self.assertEqual(main.service_info(comp, "8.10.2").state, main.SERVICE_BROKEN)


class ServiceCardState(ServiceTestBase):
    def _card(self, comp):
        _btprelude.ensure_app()
        card = main.ComponentCard(comp, lambda level, msg: None)
        self.addCleanup(card.deleteLater)
        return card

    def test_running_service_is_named_on_the_card(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_RUNNING)
        self.listening.add(3306)
        card = self._card(comp)
        mgr = main.ServiceManager(is_listening=lambda p: p in self.listening)
        with mock.patch.object(main, "SERVICE_MANAGER", mgr):
            card._refresh_launch_state()
        self.assertEqual(card.btn_start.text(), "停止")
        self.assertIn("ByteTools-MySQL-8.0.37", card.launch_label.toolTip())
        self.assertIn("3306", card.launch_label.toolTip())

    def test_broken_service_is_visible_on_the_card(self):
        comp = self.ready("mysql", "8.0.37")
        self.add_service(comp, "8.0.37", main.SERVICE_STOPPED,
                         image=str(comp.install_dir("8.0.37") / "bin" / "gone.exe"))
        card = self._card(comp)
        mgr = main.ServiceManager(is_listening=lambda p: False)
        with mock.patch.object(main, "SERVICE_MANAGER", mgr):
            card._refresh_launch_state()
        self.assertIn("服务损坏", card.launch_label.toolTip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
