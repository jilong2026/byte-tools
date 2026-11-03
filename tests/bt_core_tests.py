"""core/ 新模块护栏：安全删除、结构化日志、版本口径抽取。

这一套钉的是 2026-11 重构引入的三件事：
  · safe_rmtree 只允许在给定根目录内删除，越界必须抛 UnsafePathError；
  · StructuredLogger 四个级别都能记录、不递归、能导出 JSON；
  · Version / _version_parts / _semver_key / _version_key 抽到 core.versioning
    之后，main 里的薄壳行为与历史完全一致（口径分歧是承重设计，不许抹平）。
"""
import json
import tempfile
import unittest
from pathlib import Path

import _btprelude  # noqa: F401  必须早于 import main

import main  # noqa: E402
from core import versioning  # noqa: E402
from core.exceptions import InstallationError, UnsafePathError, safe_rmtree  # noqa: E402
from core.logger import LogLevel, StructuredLogger  # noqa: E402


class SafeRmtreeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / ".env-tools"
        self.root.mkdir()

    def test_deletes_directory_inside_allowed_root(self):
        target = self.root / "jdk" / "jdk-21"
        target.mkdir(parents=True)
        (target / "bin").mkdir()
        (target / "bin" / "java.exe").write_bytes(b"MZ")

        safe_rmtree(target, allowed_root=self.root)

        self.assertFalse(target.exists())

    def test_missing_path_is_a_noop(self):
        safe_rmtree(self.root / "not-there", allowed_root=self.root)

    def test_path_outside_root_is_rejected(self):
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        with self.assertRaises(UnsafePathError):
            safe_rmtree(outside, allowed_root=self.root)
        self.assertTrue(outside.exists(), "越界路径绝不能被删掉")

    def test_sibling_prefix_is_not_treated_as_inside(self):
        # 前缀字符串匹配会把 .env-tools-evil 误判成在 .env-tools 里
        evil = Path(str(self.root) + "-evil")
        evil.mkdir()
        with self.assertRaises(UnsafePathError):
            safe_rmtree(evil, allowed_root=self.root)
        self.assertTrue(evil.exists())

    def test_main_wrapper_follows_config_dir_override(self):
        # 测试沙箱会改写 main.CONFIG_DIR；删除校验必须跟着走
        old = main.CONFIG_DIR
        main.CONFIG_DIR = self.root
        self.addCleanup(setattr, main, "CONFIG_DIR", old)
        target = self.root / "maven" / "maven-3.9.9"
        target.mkdir(parents=True)
        main._safe_rmtree(target)
        self.assertFalse(target.exists())


class StructuredLoggerTests(unittest.TestCase):
    def test_each_level_is_recorded_with_color(self):
        log = StructuredLogger("test-colors")
        log.ok("done")
        log.info("note")
        log.warn("careful")
        log.error("broken")
        entries = log.recent(10)
        self.assertEqual([e["level"] for e in entries],
                         ["OK", "INFO", "WARNING", "ERROR"])
        self.assertEqual([e["color"] for e in entries],
                         ["green", "gray", "orange", "red"])

    def test_no_recursion_and_percent_args_are_rendered(self):
        log = StructuredLogger("test-args")
        log.warning("port %s busy on %s", 8080, "127.0.0.1")  # 旧实现这里会无限递归
        self.assertIn("port 8080 busy on 127.0.0.1", log.recent(1)[0]["message"])

    def test_export_json_roundtrip(self):
        log = StructuredLogger("test-export")
        log.ok("installed jdk 21")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "diag.json"
            log.export_json(out)
            data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["logger_name"], "test-export")
        self.assertEqual(data["messages"][0]["message"], "installed jdk 21")

    def test_emit_callback_failure_is_swallowed(self):
        log = StructuredLogger("test-callback")

        def boom(_entry):
            raise RuntimeError("ui gone")

        log.set_emit_callback(boom)
        log.error("still logged")  # 不允许把异常抛回调用点
        self.assertEqual(log.recent(1)[0]["message"], "still logged")

    def test_level_mapping_matches_ui_strings(self):
        self.assertIs(LogLevel.from_level_str("warn"), LogLevel.WARNING)
        self.assertIs(LogLevel.from_level_str("ok"), LogLevel.OK)


class VersioningModuleTests(unittest.TestCase):
    def test_loose_parse_keeps_prerelease_parts(self):
        self.assertEqual(versioning.Version.legacy_parts("21.0.4-beta"), (21, 0, 4))
        self.assertEqual(versioning.Version.legacy_parts("v1.10.2"), (1, 10, 2))
        self.assertIsNone(versioning.Version.legacy_parts("jdk-21.0.5"))

    def test_strict_key_sinks_prereleases(self):
        self.assertEqual(versioning.Version.legacy_semver_key("21.0.4-beta"), (0,))
        self.assertEqual(versioning.Version.legacy_semver_key("21.0.4"), (21, 0, 4))

    def test_dir_key_strips_component_prefix(self):
        self.assertEqual(versioning.Version.legacy_version_key("jdk-21.0.5"), (21, 0, 5))
        self.assertEqual(versioning.Version.legacy_version_key("maven-3.9.9"), (3, 9, 9))

    def test_numeric_not_lexical_comparison(self):
        self.assertTrue(versioning.version_is_newer("1.9.0", "1.10.0"))
        self.assertFalse(versioning.version_is_newer("1.10.0", "1.9.0"))

    def test_main_shells_delegate_to_core(self):
        self.assertEqual(main._version_parts("1.2.3"), (1, 2, 3))
        self.assertEqual(main._semver_key("1.2.3-rc1"), (0,))
        self.assertEqual(main._version_key("jdk-17.0.12"), (17, 0, 12))
        self.assertTrue(main.version_is_newer("2.9.0", "2.10.0"))

    def test_main_version_is_core_version(self):
        self.assertIs(main.Version, versioning.Version)


class WindowsServiceModuleTests(unittest.TestCase):
    def test_image_path_parsing_handles_quotes_and_flags(self):
        from core.windows_service import _image_exe_path

        self.assertEqual(_image_exe_path('"C:\\a b\\mysql.exe" --defaults-file="x.ini"'),
                         "C:\\a b\\mysql.exe")
        self.assertEqual(_image_exe_path("C:\\redis\\redis-server.exe --service-run"),
                         "C:\\redis\\redis-server.exe")
        self.assertEqual(_image_exe_path(""), "")

    def test_service_name_guard(self):
        from core.windows_service import SERVICE_NAME_RE

        self.assertTrue(SERVICE_NAME_RE.match("ByteTools-MySQL-8.0.37"))
        self.assertTrue(SERVICE_NAME_RE.match("ByteTools-Redis-8.10.0"))
        self.assertFalse(SERVICE_NAME_RE.match("MySQL"))
        self.assertFalse(SERVICE_NAME_RE.match("ByteTools-MySQL-../evil"))

    def test_backend_is_inert_off_windows(self):
        from core.windows_service import (
            ERROR_ACCESS_DENIED,
            SERVICE_MISSING,
            WindowsServiceBackend,
        )

        backend = WindowsServiceBackend("Linux")
        self.assertFalse(backend.supported())
        self.assertEqual(backend.start("ByteTools-MySQL-8.0.37"), ERROR_ACCESS_DENIED)
        info = backend.query("ByteTools-MySQL-8.0.37")
        self.assertEqual(info.state, SERVICE_MISSING)
        self.assertFalse(info.exists)

    def test_main_reexports_identical_objects(self):
        from core import windows_service as core_ws

        self.assertIs(main.ServiceInfo, core_ws.ServiceInfo)
        self.assertIs(main.WindowsServiceBackend, core_ws.WindowsServiceBackend)
        self.assertIs(main.SERVICE_NAME_RE, core_ws.SERVICE_NAME_RE)


class DownloadWorkerCoreTests(unittest.TestCase):
    """core/download.py：故障转移、魔数校验、以及 main.http_session 桩点仍然有效。"""

    def setUp(self):
        from core import download as core_download

        self.core_download = core_download
        self._orig_cfg = (core_download._DEP_SESSION,
                          core_download._DEP_ENSURE_DIR,
                          core_download._DEP_HUMAN_SIZE)
        self.addCleanup(self._restore_cfg)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = Path(self._tmp.name) / "pkg.zip"

    def _restore_cfg(self):
        (self.core_download._DEP_SESSION,
         self.core_download._DEP_ENSURE_DIR,
         self.core_download._DEP_HUMAN_SIZE) = self._orig_cfg

    class _Resp:
        def __init__(self, body: bytes, total: int = None):
            self._body = body
            self.headers = {"Content-Length": str(len(body) if total is None else total)}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield self._body

    def _configure(self, session_factory):
        self.core_download.configure(
            session_factory=session_factory,
            ensure_dir_fn=lambda p: Path(p).mkdir(parents=True, exist_ok=True),
            human_size_fn=lambda n: f"{n}B",
        )

    def test_failover_skips_fake_200_and_finishes(self):
        good = b"PK" + b"\0" * 5000          # 真 zip 魔数 + 足够字节
        bad = b"<html>mirror error</html>"   # 假 200 软 404

        class _Sess:
            def __init__(self):
                self.seen = []

            def get(self, url, **kw):
                self.seen.append(url)
                return DownloadWorkerCoreTests._Resp(bad if url.endswith("/bad") else good)

        sess = _Sess()
        self._configure(lambda: sess)
        worker = self.core_download.DownloadWorker(
            ["https://x/bad", "https://x/good"], self.dest, expect_magic=b"PK")
        logs, ok, fail = [], [], []
        worker.log.connect(lambda lvl, msg: logs.append((lvl, msg)))
        worker.finished_ok.connect(ok.append)
        worker.finished_fail.connect(fail.append)

        worker.run()

        self.assertEqual(sess.seen, ["https://x/bad", "https://x/good"])
        self.assertEqual(ok, [str(self.dest)])
        self.assertEqual(fail, [])
        self.assertEqual(self.dest.read_bytes(), good)
        self.assertTrue(any("判定该源无效" in m for _l, m in logs))

    def test_magic_mismatch_fails_all_sources_without_leaving_file(self):
        fake = b"<!doctype html>" + b" " * 5000

        class _Sess:
            def get(self, url, **kw):
                return DownloadWorkerCoreTests._Resp(fake)

        self._configure(lambda: _Sess())
        worker = self.core_download.DownloadWorker(
            ["https://x/a"], self.dest, expect_magic=b"PK")
        ok, fail = [], []
        worker.finished_ok.connect(ok.append)
        worker.finished_fail.connect(fail.append)

        worker.run()

        self.assertEqual(ok, [])
        self.assertEqual(fail, ["所有下载源均不可用"])
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_suffix(".zip.part").exists())

    def test_main_reexport_and_http_session_stub_point(self):
        import core.download as core_download

        self.assertIs(main.DownloadWorker, core_download.DownloadWorker)

        calls = []

        class _Sess:
            def get(self, url, **kw):
                calls.append(url)
                return DownloadWorkerCoreTests._Resp(b"MZ" + b"\0" * 5000)

        old = main.http_session
        main.http_session = lambda: _Sess()
        self.addCleanup(setattr, main, "http_session", old)

        worker = main.DownloadWorker(["https://stub/one"], self.dest, expect_magic=b"MZ")
        worker.run()
        self.assertEqual(calls, ["https://stub/one"], "必须走 main.http_session 这个桩点")
        self.assertTrue(self.dest.exists())


class DonateDialogUiTests(unittest.TestCase):
    """ui/donate_dialog.py：资产目录可注入，缺图时给出明确占位文字。"""

    @classmethod
    def setUpClass(cls):
        cls._app = _btprelude.ensure_app()

    def test_assets_dir_is_injected_and_missing_qr_explained(self):
        from ui.donate_dialog import DonateDialog

        self.assertIs(main.DonateDialog, DonateDialog)
        with tempfile.TemporaryDirectory() as tmp:
            dlg = DonateDialog(assets_dir=Path(tmp))
            self.addCleanup(dlg.deleteLater)
            text = dlg.qr_view.text()
            self.assertIn("未找到二维码文件", text)
            self.assertIn(str(Path(tmp) / "wechat.png"), text)

    def test_bundled_assets_are_found_from_source_tree(self):
        from ui.donate_dialog import default_assets_dir

        assets = default_assets_dir()
        self.assertTrue(assets.is_dir(), assets)
        self.assertTrue((assets / "wechat.png").is_file())


class PerfSnapshotTests(unittest.TestCase):
    def setUp(self):
        from core import perf
        self.perf = perf
        perf.reset()
        self.addCleanup(perf.reset)

    def test_timed_accumulates_count_total_and_max(self):
        for _ in range(3):
            with self.perf.timed("unit_op"):
                pass
        snap = self.perf.snapshot()
        slot = snap["timers"]["unit_op"]
        self.assertEqual(slot["count"], 3)
        self.assertGreaterEqual(slot["total_ms"], 0.0)
        self.assertGreaterEqual(slot["max_ms"], 0.0)

    def test_timed_records_even_when_body_raises(self):
        with self.assertRaises(RuntimeError):
            with self.perf.timed("boom_op"):
                raise RuntimeError("x")
        self.assertEqual(self.perf.snapshot()["timers"]["boom_op"]["count"], 1)

    def test_format_section_lists_timers(self):
        with self.perf.timed("listed_op"):
            pass
        text = "\n".join(self.perf.format_section())
        self.assertIn("listed_op", text)
        self.assertIn("进程运行时长", text)

    def test_memory_off_by_default_until_enabled(self):
        self.assertIsNone(self.perf.snapshot()["memory"])
        self.perf.start_memory_tracking()
        self.assertIsNotNone(self.perf.snapshot()["memory"])

    def test_diagnostics_contains_perf_section(self):
        with self.perf.timed("diag_op"):
            pass
        text = main.build_diagnostics()
        self.assertIn("性能快照", text)
        self.assertIn("diag_op", text)


class I18nTests(unittest.TestCase):
    def setUp(self):
        from core import i18n
        self.i18n = i18n
        self._old = i18n.current_language()
        self.addCleanup(i18n.set_language, self._old)

    def test_default_chinese_returns_source(self):
        self.i18n.set_language("zh")
        self.assertEqual(self.i18n.tr("支持作者"), "支持作者")

    def test_english_lookup_and_placeholder(self):
        self.i18n.set_language("en")
        self.assertEqual(self.i18n.tr("支持作者"), "Support the author")
        self.assertEqual(self.i18n.tr("【{channel}】收款码", channel="WeChat"),
                         "WeChat payment QR code")

    def test_unknown_string_falls_back_to_source(self):
        self.i18n.set_language("en")
        self.assertEqual(self.i18n.tr("没有翻译的句子"), "没有翻译的句子")

    def test_assets_root_prefers_meipass_when_frozen(self):
        import sys as _sys
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(_sys, "_MEIPASS", tmp, create=True):
                self.assertEqual(self.i18n.assets_root(), Path(tmp))
        self.assertNotEqual(self.i18n.assets_root(), Path("/nonexistent"))


class ComponentDetailDialogUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = _btprelude.ensure_app()

    class _Comp:
        display_name = "JDK (Temurin)"
        official_url = "https://adoptium.net/"

    def test_renders_sections_and_official_link(self):
        from ui.component_detail_dialog import ComponentDetailDialog

        self.assertIs(main.ComponentDetailDialog, ComponentDetailDialog)
        dlg = ComponentDetailDialog(self._Comp(), [("说明", "**加粗**正文")])
        self.addCleanup(dlg.deleteLater)
        self.assertIn("JDK (Temurin)", dlg.windowTitle())
        self.assertIn('<b>加粗</b>', dlg._to_html([("说明", "**加粗**正文")]))
        self.assertIsNotNone(dlg._app, "必须挂上应用级过滤器以便点击外部关闭")

    def test_close_detaches_app_filter(self):
        from ui.component_detail_dialog import ComponentDetailDialog

        dlg = ComponentDetailDialog(self._Comp(), [("说明", "x")])
        dlg.close()
        self.assertIsNone(dlg._app)

    def test_url_netloc_reexport_and_behavior(self):
        self.assertEqual(main._url_netloc("https://www.navicat.com.cn/x"), "www.navicat.com.cn")
        self.assertEqual(main._url_netloc("not a url"), "")

    def test_default_assets_dir_prefers_meipass_when_frozen(self):
        import sys as _sys
        from unittest import mock
        from ui.donate_dialog import default_assets_dir

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(_sys, "_MEIPASS", tmp, create=True):
                self.assertEqual(default_assets_dir(), Path(tmp) / "assets")


class BuildPreflightTests(unittest.TestCase):
    """打包前置检查：运行中的 exe 会让 PyInstaller 最后一步 WinError 5。"""

    def test_distpath_parsing(self):
        import pyinstaller_no_wmi as no_wmi

        self.assertEqual(no_wmi._target_distpath([]), "dist")
        self.assertEqual(no_wmi._target_distpath(["--distpath", "out"]), "out")
        self.assertEqual(no_wmi._target_distpath(["--distpath=out2"]), "out2")

    def test_missing_output_is_not_blocking(self):
        import pyinstaller_no_wmi as no_wmi

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(no_wmi.check_output_lock(["--distpath", tmp]), "")

    def test_writable_output_is_not_blocking(self):
        import pyinstaller_no_wmi as no_wmi

        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "ByteTools.exe"
            exe.write_bytes(b"MZ")
            self.assertEqual(no_wmi.check_output_lock(["--distpath", tmp]), "")

    def test_only_page_servers_are_selected_for_auto_stop(self):
        import pyinstaller_no_wmi as no_wmi

        with tempfile.TemporaryDirectory() as tmp:
            exe = str(Path(tmp) / "ByteTools.exe")
            other = str(Path(tmp) / "other" / "ByteTools.exe")
            procs = [(111, f'"{exe}" --bt-page-server C:\\x'),
                     (222, exe),
                     (333, other),
                     (444, "")]
            self.assertEqual(no_wmi.locking_pids(procs, exe), [111, 222])

    def test_first_arg_handles_quotes(self):
        import pyinstaller_no_wmi as no_wmi

        self.assertEqual(no_wmi._first_arg('"C:\\a b\\x.exe" --flag'), "C:\\a b\\x.exe")
        self.assertEqual(no_wmi._first_arg("C:\\x.exe --flag"), "C:\\x.exe")
        self.assertEqual(no_wmi._first_arg(""), "")


class DiagnosticsIntegrationTests(unittest.TestCase):
    def test_diagnostics_contains_structured_log_section(self):
        main.logger.ok("diagnostics-marker-ok")
        text = main.build_diagnostics()
        self.assertIn("结构化日志（最近 50 条）", text)
        self.assertIn("diagnostics-marker-ok", text)

    def test_unsafe_rmtree_does_not_abort_uninstall_flow(self):
        # 卸载遇到"不在工作目录内"的路径时：跳过删除、写摘要，不许抛出去
        old = main.CONFIG_DIR
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, main, "CONFIG_DIR", old)
        main.CONFIG_DIR = Path(self._tmp.name) / ".env-tools"
        main.CONFIG_DIR.mkdir()

        outside = Path(self._tmp.name) / "user-owned-jdk"
        outside.mkdir()
        with self.assertRaises(UnsafePathError):
            main._safe_rmtree(outside)
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
