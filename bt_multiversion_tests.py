"""组件多版本 + 生效版本切换的规格测试（离线，不联网）。

沙箱原则：落盘的地方全换成临时目录或内存桩——
  · Windows 分支打桩 _read_windows_user_path / _write_registry_env / EnvManager.get，
    绝不碰 HKCU；
  · Unix 分支打桩 _shell_rc_file 指向临时文件，绝不碰用户真实的 ~/.zshrc；
  · 产品代码会顺手改 os.environ（PATH / JAVA_HOME），每个用例结束都还原。
计划文档：docs/superpowers/plans/2026-09-29-multi-version-switch.md
"""
import json
import os
import platform as _platform
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 本机 WMI 卡死会让 platform.system() 永久阻塞，必须在 import main 之前 stub
_platform._wmi_query = lambda *a, **k: (_ for _ in ()).throw(
    OSError("WMI disabled for test process"))
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = r"E:\file\test\byte-tools"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

def _restored_env_keys():
    """进程环境快照要跟着组件表长，别手写清单。

    build_components() 里的 env_var（CATALINA_HOME / MYSQL_HOME / KAFKA_HOME …）
    都会被 set_windows_user_env 同步进 os.environ（main.py:3437），漏一个键就是
    跨用例泄漏，所以直接从产品组件表推导。
    """
    keys = {"PATH"}
    for comp in main.build_components():
        if comp.env_var:
            keys.add(comp.env_var)
    return tuple(sorted(keys))


ENV_KEYS = _restored_env_keys()


class EnvSandbox(unittest.TestCase):
    """把 CONFIG_DIR / CONFIG_FILE / shell rc / Windows 注册表读写全部沙箱化。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "env-tools"
        self.root.mkdir(parents=True)

        self._saved = {k: getattr(main, k) for k in ("CONFIG_DIR", "CONFIG_FILE", "CURRENT_OS")}
        main.CONFIG_DIR = self.root
        main.CONFIG_FILE = self.root / "config.json"
        self.addCleanup(lambda: [setattr(main, k, v) for k, v in self._saved.items()])

        # Unix 落点：临时 rc
        self.rc = self.root / "rc"
        self.rc.write_text("# user rc\n", encoding="utf-8")
        self._orig_rc = main.EnvManager._shell_rc_file
        main.EnvManager._shell_rc_file = staticmethod(lambda: self.rc)
        self.addCleanup(setattr, main.EnvManager, "_shell_rc_file", self._orig_rc)

        # Windows 落点：内存
        self.win_env = {}
        self.win_path = []
        self._orig_read = main.EnvManager._read_windows_user_path
        self._orig_write = main.EnvManager._write_registry_env
        self._orig_get = main.EnvManager.get
        self._orig_read_env = getattr(main.EnvManager, "_read_windows_user_env", None)
        # Task 4 写侧接缝（_delete_windows_user_env）：回滚路径经 drop_user_env
        # 走到真实 winreg.DeleteValue，不打桩就是用例在真删用户 HKCU 的值。
        self._orig_delete_env = getattr(main.EnvManager, "_delete_windows_user_env", None)

        def fake_read():
            return list(self.win_path)

        def fake_write(name, value):
            if name.lower() == "path":
                self.win_path[:] = [p for p in str(value).split(";") if p]
            else:
                self.win_env[name] = value

        def fake_get(name):
            # 规则（评审 controller 裁定）：持久化断言必须直读 self.win_env /
            # self.win_path，EnvManager.get 只用于"生效值"读取。os.environ 兜底
            # 正是 get 与 read_user_env 的区分点，别"简化"掉。
            return self.win_env.get(name) or os.environ.get(name)

        main.EnvManager._read_windows_user_path = staticmethod(fake_read)
        main.EnvManager._write_registry_env = staticmethod(fake_write)
        main.EnvManager.get = staticmethod(fake_get)
        if self._orig_read_env is not None:      # Task 3 落地后生效：不碰真实 HKCU
            main.EnvManager._read_windows_user_env = staticmethod(
                lambda name: self.win_env.get(name))
        if self._orig_delete_env is not None:    # Task 4 落地后生效：不真删 HKCU 值
            main.EnvManager._delete_windows_user_env = staticmethod(
                lambda name: self.win_env.pop(name, None))

        def restore_win():
            main.EnvManager._read_windows_user_path = self._orig_read
            main.EnvManager._write_registry_env = self._orig_write
            main.EnvManager.get = self._orig_get
            if self._orig_read_env is not None:
                main.EnvManager._read_windows_user_env = self._orig_read_env
            if self._orig_delete_env is not None:
                main.EnvManager._delete_windows_user_env = self._orig_delete_env
        self.addCleanup(restore_win)

        # 卡片构造会跑状态探测，这里统一停掉并在结束后还原
        self._orig_detect = main.ComponentCard._detect_status
        main.ComponentCard._detect_status = lambda self, *a, **k: None
        self.addCleanup(setattr, main.ComponentCard, "_detect_status", self._orig_detect)

        # 产品代码会写 os.environ，逐键还原
        self._orig_environ = {k: os.environ.get(k) for k in ENV_KEYS}

        def restore_environ():
            for k, v in self._orig_environ.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore_environ)

    # ---- 便捷方法 ----
    def as_windows(self):
        main.CURRENT_OS = "Windows"

    def as_linux(self):
        main.CURRENT_OS = "Linux"

    def enable_detect(self):
        """放开真实的状态探测（Task 8 的胶囊用例需要它），但绝不允许起真实探测线程。

        `_schedule_version_probe` 会真的执行组件可执行文件去取版本号，在测试里等于
        去跑用户机器上的 java —— 所以这里把它替换成"记录调用但不执行"。
        """
        main.ComponentCard._detect_status = self._orig_detect
        self.addCleanup(setattr, main.ComponentCard, "_detect_status",
                        lambda self, *a, **k: None)
        orig_probe = main.ComponentCard._schedule_version_probe
        self.probe_calls = []
        main.ComponentCard._schedule_version_probe = (
            lambda self, exe_path, *a, **k: self.probe_calls.append(exe_path))
        self.addCleanup(setattr, main.ComponentCard, "_schedule_version_probe", orig_probe)

    def make_component(self, key: str, *versions):
        """取真实组件定义，并在沙箱里造出这些版本的安装目录。"""
        comp = next(c for c in main.build_components() if c.key == key)
        for v in versions:
            (comp.install_dir(v) / "bin").mkdir(parents=True, exist_ok=True)
        return comp


class SandboxSelfCheck(EnvSandbox):
    """沙箱自己也要有断言：它失效时，后面所有用例都会变成假绿灯。"""

    def test_config_dir_is_sandboxed(self):
        self.assertEqual(main.CONFIG_DIR, self.root)
        self.assertEqual(main.CONFIG_FILE, self.root / "config.json")
        self.assertTrue(str(self.rc).startswith(self.tmp.name))
        self.assertNotEqual(main.CONFIG_DIR, Path.home() / ".env-tools")
        # rc 桩必须活着：只断言 self.rc 的路径不构成保护——桩一旦失效，
        # Unix 分支用例会把 export 块写进用户真实的 ~/.zshrc 而自检仍全绿。
        self.assertEqual(main.EnvManager._shell_rc_file(), self.rc)

    def test_make_component_creates_real_dirs(self):
        comp = self.make_component("jdk", "21.0.4", "17.0.12")
        self.assertTrue((comp.install_dir("21.0.4") / "bin").is_dir())
        self.assertEqual(main.CONFIG_DIR, self.root)   # 目录确实落在沙箱里
        self.assertTrue(str(comp.install_dir("21.0.4")).startswith(self.tmp.name))

    def test_windows_stub_is_installed(self):
        # 沙箱必须已接管 Windows 的读、写与 get 三个落地点，否则测试会
        # 读到 / 写进真实 HKCU，结果随宿主机环境漂移
        self.win_env["JAVA_HOME"] = "stubbed"
        self.assertEqual(main.EnvManager.get("JAVA_HOME"), "stubbed")
        self.assertEqual(main.EnvManager._read_windows_user_path(), [])
        main.EnvManager._write_registry_env("Path", r"C:\a;C:\b")
        self.assertEqual(self.win_path, [r"C:\a", r"C:\b"])

    def test_windows_delete_env_seam_is_stubbed(self):
        # 写侧接缝自检（Task 4 裁定 R1）：回滚会从 drop_user_env 走到
        # _delete_windows_user_env；桩一旦失联，用例就会真删用户注册表值，
        # 而 win_env 断言仍可能"绿"——所以这里必须主动调用并验证落点。
        delete = getattr(main.EnvManager, "_delete_windows_user_env", None)
        self.assertIsNotNone(delete, "EnvManager 缺少 _delete_windows_user_env 接缝")
        self.win_env["KAFKA_HOME"] = r"C:\should\be\popped"
        delete("KAFKA_HOME")
        self.assertNotIn("KAFKA_HOME", self.win_env)


# 与用户确认过的多版本组件白名单（固定 7 个，别自行扩大）
EXPECTED_MULTI_VERSION = {"jdk", "python", "node", "go", "maven", "gradle", "bun"}


class MultiVersionFlag(EnvSandbox):
    def setUp(self):
        super().setUp()
        self.components = {c.key: c for c in main.build_components()}

    def test_only_the_seven_agreed_components_are_multi_version(self):
        got = {k for k, c in self.components.items() if c.multi_version}
        self.assertEqual(got, EXPECTED_MULTI_VERSION)

    def test_service_and_installer_mode_components_are_off(self):
        for key in ("conda", "mysql", "tomcat", "nacos", "elasticsearch",
                    "docker", "powershell", "nginx", "kubectl"):
            self.assertFalse(self.components[key].multi_version, key)

    def test_every_component_has_the_attribute(self):
        for key, comp in self.components.items():
            self.assertIsInstance(comp.multi_version, bool, key)


class InstalledVersions(EnvSandbox):
    def test_parses_version_from_dir_name(self):
        comp = self.make_component("jdk")
        self.assertEqual(main.version_from_install_dir(comp, Path("x/jdk-21.0.4")), "21.0.4")
        self.assertIsNone(main.version_from_install_dir(comp, Path("x/python-3.12.4")))
        self.assertIsNone(main.version_from_install_dir(comp, Path("x/jdk")))
        self.assertIsNone(main.version_from_install_dir(comp, Path("x/jdk-")))

    def test_orders_by_semver_not_lexicographic(self):
        # 这条正是旧 bug 的形状：目录名字典序会把 jdk-8 排在 jdk-21 之后
        comp = self.make_component("jdk", "8", "21.0.4", "17.0.12")
        self.assertEqual([v for v, _p in main.installed_versions(comp)],
                         ["21.0.4", "17.0.12", "8"])

    def test_ignores_downloads_and_foreign_dirs(self):
        comp = self.make_component("jdk", "21.0.4")
        (main.CONFIG_DIR / "jdk" / "downloads").mkdir(parents=True, exist_ok=True)
        (main.CONFIG_DIR / "jdk" / "notajdk").mkdir(parents=True, exist_ok=True)
        self.assertEqual([v for v, _p in main.installed_versions(comp)], ["21.0.4"])

    def test_returns_pair_with_the_exact_install_dir(self):
        comp = self.make_component("python", "3.12.4", "3.11.9")
        pairs = main.installed_versions(comp)
        self.assertEqual(pairs[0], ("3.12.4", comp.install_dir("3.12.4")))


class EnvFacade(EnvSandbox):
    def test_unix_write_read_drop_roundtrip(self):
        self.as_linux()
        Env = main.EnvManager
        Env.write_user_env("JAVA_HOME", "/x/jdk-21.0.4")
        self.assertEqual(Env.read_user_env("JAVA_HOME"), "/x/jdk-21.0.4")
        self.assertIn('export JAVA_HOME="/x/jdk-21.0.4"', self.rc.read_text(encoding="utf-8"))
        Env.drop_user_env("JAVA_HOME")
        self.assertIsNone(Env.read_user_env("JAVA_HOME"))

    def test_unix_path_entry_roundtrip_and_list(self):
        self.as_linux()
        Env = main.EnvManager
        Env.add_path_entry("/x/jdk-21.0.4/bin")
        Env.add_path_entry("/x/jdk-17.0.12/bin")
        self.assertEqual(Env.read_user_path_entries(),
                         ["/x/jdk-21.0.4/bin", "/x/jdk-17.0.12/bin"])
        removed = Env.remove_path_entries_under("/x/jdk-17.0.12")
        self.assertEqual(removed, ["/x/jdk-17.0.12/bin"])
        self.assertEqual(Env.read_user_path_entries(), ["/x/jdk-21.0.4/bin"])

    def test_windows_write_and_list(self):
        self.as_windows()
        Env = main.EnvManager
        Env.write_user_env("JAVA_HOME", r"C:\x\jdk-21.0.4")
        self.assertEqual(self.win_env["JAVA_HOME"], r"C:\x\jdk-21.0.4")
        self.assertEqual(Env.read_user_env("JAVA_HOME"), r"C:\x\jdk-21.0.4")
        Env.add_path_entry(r"C:\x\jdk-21.0.4\bin")
        self.assertIn(r"C:\x\jdk-21.0.4\bin", Env.read_user_path_entries())

    def test_windows_read_absent_env_returns_none(self):
        self.as_windows()
        self.assertIsNone(main.EnvManager.read_user_env("JAVA_HOME"))

    def test_windows_remove_under_root_only_touches_that_root(self):
        self.as_windows()
        self.win_path[:] = [r"C:\x\jdk\jdk-17.0.12\bin",
                            r"C:\x\jdk\jdk-21.0.4\bin",
                            r"C:\Windows\system32"]
        removed = main.EnvManager.remove_path_entries_under(r"C:\x\jdk\jdk-17.0.12")
        self.assertEqual([p.lower() for p in removed], [r"c:\x\jdk\jdk-17.0.12\bin"])
        self.assertIn(r"C:\x\jdk\jdk-21.0.4\bin", self.win_path)
        self.assertIn(r"C:\Windows\system32", self.win_path)


class SwitchActive(EnvSandbox):
    def setUp(self):
        super().setUp()
        self.comp = self.make_component("jdk", "21.0.4", "17.0.12")

    def test_windows_switch_sets_home_and_collapses_path_to_one_entry(self):
        self.as_windows()
        # 先制造旧状态：两个版本各留一条 PATH（就是现在那个病）
        self.win_path[:] = [str(self.comp.install_dir("17.0.12") / "bin"),
                            str(self.comp.install_dir("21.0.4") / "bin"),
                            r"C:\Windows\system32"]
        steps = main.apply_active_version(self.comp, "21.0.4")
        self.assertEqual(self.win_env["JAVA_HOME"], str(self.comp.install_dir("21.0.4")))
        jdk_entries = [p for p in self.win_path if "jdk-" in p.lower()]
        self.assertEqual(len(jdk_entries), 1, self.win_path)
        self.assertIn("jdk-21.0.4", jdk_entries[0])
        self.assertIn(r"C:\Windows\system32", self.win_path)   # 别的条目不许动
        self.assertTrue(any("已开" in s or "重开" in s for s in steps),
                        "日志必须提示已开终端不受影响（决策 D6）")

    def test_linux_switch_writes_rc(self):
        self.as_linux()
        main.apply_active_version(self.comp, "17.0.12")
        rc_text = self.rc.read_text(encoding="utf-8")
        self.assertIn(str(self.comp.install_dir("17.0.12")), rc_text)
        self.assertNotIn("jdk-21.0.4", rc_text)

    def test_failure_after_env_write_rolls_back_env_and_path(self):
        self.as_windows()
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("17.0.12"))
        self.win_path[:] = [str(self.comp.install_dir("17.0.12") / "bin")]
        orig = main.EnvManager.append_windows_path
        main.EnvManager.append_windows_path = staticmethod(
            lambda entry: (_ for _ in ()).throw(OSError("disk full")))
        self.addCleanup(setattr, main.EnvManager, "append_windows_path", orig)

        with self.assertRaises(main.SwitchError):
            main.apply_active_version(self.comp, "21.0.4")
        # 回滚：JAVA_HOME 回到改动前，被清掉的旧条目回来了，新条目没留下
        self.assertEqual(self.win_env["JAVA_HOME"], str(self.comp.install_dir("17.0.12")))
        self.assertIn(str(self.comp.install_dir("17.0.12") / "bin"), self.win_path)
        self.assertNotIn(str(self.comp.install_dir("21.0.4") / "bin"), self.win_path)

    def test_windows_rollback_drops_env_when_it_did_not_exist(self):
        # 回滚的另一条分支：切换前 XXX_HOME 本不存在，失败后必须把它删掉，
        # 不能留下"半路写上"的新值。这条路径经 drop_user_env →
        # _delete_windows_user_env 写侧接缝（裁定 R1）——桩失联时本用例会
        # 去真删 HKCU 而 win_env 里仍残留 JAVA_HOME，从而变红而不是假绿。
        self.as_windows()
        self.win_path[:] = [r"C:\Windows\system32"]
        orig = main.EnvManager.append_windows_path
        main.EnvManager.append_windows_path = staticmethod(
            lambda entry: (_ for _ in ()).throw(OSError("disk full")))
        self.addCleanup(setattr, main.EnvManager, "append_windows_path", orig)
        with self.assertRaises(main.SwitchError):
            main.apply_active_version(self.comp, "21.0.4")
        self.assertNotIn("JAVA_HOME", self.win_env)
        self.assertIn(r"C:\Windows\system32", self.win_path)

    def test_missing_version_dir_raises_without_touching_anything(self):
        self.as_windows()
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("17.0.12"))
        self.win_path[:] = [str(self.comp.install_dir("17.0.12") / "bin")]
        before_env, before_path = dict(self.win_env), list(self.win_path)
        with self.assertRaises(main.SwitchError) as ctx:
            main.apply_active_version(self.comp, "99.9.9")
        self.assertIn("版本目录不存在", str(ctx.exception))
        self.assertEqual(self.win_env, before_env)
        self.assertEqual(self.win_path, before_path)

    # ---- 回滚分支补测（评审 I2）：Unix 回滚、env 先失败、清表中途失败、记账顺序 ----
    # 共同原则：断言只看"持久层里到底剩下什么"——Unix 读 rc 文本，Windows 读
    # self.win_env / self.win_path。绝不断言 EnvManager.get（它会 os.environ 兜底，
    # 本进程被自己改脏时照样"看着对"），也绝不断言桩的调用次数（改实现不改行为
    # 时次数会变，那是给实现上锁而不是给规格上锁）。

    def _seed_linux_jdk_17(self):
        """在 Unix 沙箱里造出"生效版本是 17"的持久层状态，返回 (home, bin, 无关条目)。"""
        self.as_linux()
        old_home = str(self.comp.install_dir("17.0.12"))
        old_bin = str(self.comp.install_dir("17.0.12") / "bin")
        main.EnvManager.write_user_env("JAVA_HOME", old_home)
        main.EnvManager.add_path_entry(old_bin)
        # 别人（非本组件根目录）的条目：清表与回滚都不许碰它
        main.EnvManager.add_path_entry("/opt/unrelated/bin")
        return old_home, old_bin

    def _stub_append_unix_path(self, fn):
        orig = main.EnvManager.append_unix_path
        main.EnvManager.append_unix_path = staticmethod(fn)
        self.addCleanup(setattr, main.EnvManager, "append_unix_path", orig)

    def test_linux_failure_rolls_back_rc_from_persistence(self):
        # Unix 回滚分支：restore_path_entries 的非 Windows 路径（~main.py:3827-3829）。
        # 此前所有失败用例都是 as_windows，这条码路一行都没跑过。
        old_home, old_bin = self._seed_linux_jdk_17()
        new_bin = str(self.comp.install_dir("21.0.4") / "bin")
        orig_append = main.EnvManager.append_unix_path

        def flaky(entry):
            # 只有"写目标版本那一条"失败（磁盘满/权限），旧条目的恢复仍走得通
            if entry == new_bin:
                raise OSError("disk full")
            return orig_append(entry)

        self._stub_append_unix_path(flaky)
        with self.assertRaises(main.SwitchError) as ctx:
            main.apply_active_version(self.comp, "21.0.4")

        text = self.rc.read_text(encoding="utf-8")
        # rc 回到切换前：JAVA_HOME 指 17，17 的 PATH 条目被补回来了
        self.assertIn(f'export JAVA_HOME="{old_home}"', text)
        self.assertIn(old_bin, text)
        self.assertIn("/opt/unrelated/bin", text)
        self.assertNotIn("jdk-21.0.4", text)
        entries = main.EnvManager.read_user_path_entries()
        self.assertIn(old_bin, entries)
        self.assertNotIn(new_bin, entries)
        # 回滚干净时措辞维持原样，不许出现"未完全成功"
        msg = str(ctx.exception)
        self.assertIn("切换失败，已回滚到切换前状态（原 JAVA_HOME=", msg)
        self.assertNotIn("回滚未完全成功", msg)

    def test_linux_rollback_failure_is_reported_not_swallowed(self):
        # 评审 I1：补救失败只 print 等于没说——pythonw 下 stdout 直接丢弃，
        # 日志却写着"已回滚"。这条造出真实的半回滚（PATH 补不回来、HOME 回来了），
        # 然后要求 SwitchError 文本如实承认，并点名失败的那一条。
        old_home, old_bin = self._seed_linux_jdk_17()
        self._stub_append_unix_path(
            lambda entry: (_ for _ in ()).throw(OSError("disk full")))

        with self.assertRaises(main.SwitchError) as ctx:
            main.apply_active_version(self.comp, "21.0.4")

        text = self.rc.read_text(encoding="utf-8")
        # 半回滚确凿发生（不是测试假设，是被断言的事实）：HOME 回到 17，旧 PATH 没回来
        self.assertIn(f'export JAVA_HOME="{old_home}"', text)
        self.assertNotIn(old_bin, text)
        msg = str(ctx.exception)
        self.assertIn("回滚未完全成功", msg)
        self.assertIn(old_bin, msg)                     # 明细要点名没补回来的条目
        self.assertNotIn("已回滚到切换前状态", msg)       # 不许再谎称已回滚

    def test_windows_env_write_fails_first_and_changes_nothing(self):
        # 顺序即规格：HOME 写入排在最前，它失败时 PATH 一次都没被动过。
        self.as_windows()
        old_home = str(self.comp.install_dir("17.0.12"))
        old_bin = str(self.comp.install_dir("17.0.12") / "bin")
        self.win_env["JAVA_HOME"] = old_home
        self.win_path[:] = [old_bin, r"C:\Windows\system32"]
        before_env, before_path = dict(self.win_env), list(self.win_path)
        target_home = str(self.comp.install_dir("21.0.4"))

        orig_write = main.EnvManager._write_registry_env

        def locked(name, value):
            if value == target_home:
                raise OSError("registry locked")
            return orig_write(name, value)

        main.EnvManager._write_registry_env = staticmethod(locked)
        self.addCleanup(setattr, main.EnvManager, "_write_registry_env", orig_write)

        with self.assertRaises(main.SwitchError) as ctx:
            main.apply_active_version(self.comp, "21.0.4")

        self.assertEqual(self.win_env, before_env)
        self.assertEqual(self.win_path, before_path)    # PATH 一个条目都没少
        msg = str(ctx.exception)
        self.assertIn("切换失败，已回滚到切换前状态", msg)
        self.assertNotIn("回滚未完全成功", msg)

    def test_windows_remove_path_entries_fails_midway_rolls_back_home(self):
        # 清表中途失败：注册表那次写炸了 → removed_entries 仍是空（赋值没完成），
        # PATH 保持原样，但 HOME 已经写进去了，必须靠回滚还原。
        self.as_windows()
        old_home = str(self.comp.install_dir("17.0.12"))
        old_bin = str(self.comp.install_dir("17.0.12") / "bin")
        self.win_env["JAVA_HOME"] = old_home
        self.win_path[:] = [old_bin, r"C:\Windows\system32"]
        before_path = list(self.win_path)

        orig_write = main.EnvManager._write_registry_env

        def path_write_locked(name, value):
            if name.lower() == "path":
                raise OSError("registry locked")
            return orig_write(name, value)

        main.EnvManager._write_registry_env = staticmethod(path_write_locked)
        self.addCleanup(setattr, main.EnvManager, "_write_registry_env", orig_write)

        with self.assertRaises(main.SwitchError) as ctx:
            main.apply_active_version(self.comp, "21.0.4")

        self.assertEqual(self.win_env["JAVA_HOME"], old_home)
        self.assertEqual(self.win_path, before_path)
        self.assertNotIn(str(self.comp.install_dir("21.0.4") / "bin"), self.win_path)
        self.assertNotIn("回滚未完全成功", str(ctx.exception))

    def test_windows_new_entry_persisted_then_raises_still_dropped_on_rollback(self):
        # 评审 I3：primitive"先落盘、后抛错"（进程同步/广播失败）时，新条目必须
        # 已被记账，否则回滚只补旧条目、漏删新条目 → 同组件两条 PATH 同时生效。
        self.as_windows()
        old_home = str(self.comp.install_dir("17.0.12"))
        old_bin = str(self.comp.install_dir("17.0.12") / "bin")
        new_bin = str(self.comp.install_dir("21.0.4") / "bin")
        self.win_env["JAVA_HOME"] = old_home
        self.win_path[:] = [old_bin]

        orig_append = main.EnvManager.append_windows_path

        def persist_then_raise(entry):
            orig_append(entry)                    # 真的写进持久层
            raise OSError("process sync failed")  # 再炸在写入之后

        main.EnvManager.append_windows_path = staticmethod(persist_then_raise)
        self.addCleanup(setattr, main.EnvManager, "append_windows_path", orig_append)

        with self.assertRaises(main.SwitchError) as ctx:
            main.apply_active_version(self.comp, "21.0.4")

        self.assertNotIn(new_bin, self.win_path)
        self.assertEqual(self.win_path, [old_bin])
        self.assertEqual(self.win_env["JAVA_HOME"], old_home)
        self.assertNotIn("回滚未完全成功", str(ctx.exception))


class ActiveConfig(EnvSandbox):
    def test_missing_file_gives_empty_map(self):
        self.assertEqual(main.load_active_map(), {})

    def test_corrupt_file_is_not_fatal(self):
        main.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(main.load_active_map(), {})

    def test_saving_active_keeps_selections(self):
        main.CONFIG_FILE.write_text(json.dumps(
            {"selections": {"jdk": "17.0.12", "node": "20.15.0"}}, ensure_ascii=False),
            encoding="utf-8")
        main.save_active_version("jdk", "21.0.4")
        data = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data["active"], {"jdk": "21.0.4"})
        self.assertEqual(data["selections"], {"jdk": "17.0.12", "node": "20.15.0"},
                         "写 active 不许丢 selections")

    def test_clearing_active_removes_only_that_key(self):
        main.save_active_version("jdk", "21.0.4")
        main.save_active_version("node", "20.15.0")
        main.save_active_version("jdk", None)
        self.assertEqual(main.load_active_map(), {"node": "20.15.0"})

    def test_infer_active_from_env_reads_sandboxed_rc(self):
        self.as_linux()
        comp = self.make_component("jdk", "21.0.4")
        main.EnvManager.write_user_env("JAVA_HOME", str(comp.install_dir("21.0.4")))
        self.assertEqual(main.infer_active_from_env(comp), "21.0.4")

    def test_infer_active_ignores_homes_pointing_elsewhere(self):
        self.as_linux()
        comp = self.make_component("jdk", "21.0.4")
        main.EnvManager.write_user_env("JAVA_HOME", "/opt/other/jdk-11")
        self.assertIsNone(main.infer_active_from_env(comp))


class SaveSettingsKeepsActive(EnvSandbox):
    def test_window_save_preserves_active(self):
        main.save_active_version("jdk", "21.0.4")
        app = QApplication.instance() or QApplication([])
        orig_fetch = main.MainWindow._start_fetch_versions
        main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
        self.addCleanup(setattr, main.MainWindow, "_start_fetch_versions", orig_fetch)
        win = main.MainWindow()
        self.addCleanup(win.deleteLater)
        win._save_settings()
        data = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data["active"], {"jdk": "21.0.4"})
        self.assertIn("jdk", data["selections"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
