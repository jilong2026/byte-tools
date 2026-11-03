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
