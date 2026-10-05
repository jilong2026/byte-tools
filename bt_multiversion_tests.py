"""组件多版本 + 生效版本切换的规格测试（离线，不联网）。

沙箱原则：落盘的地方全换成临时目录或内存桩——
  · Windows 分支打桩 _read_windows_user_path / _write_registry_env / EnvManager.get，
    绝不碰 HKCU；
  · Unix 分支打桩 _shell_rc_file 指向临时文件，绝不碰用户真实的 ~/.zshrc；
  · 产品代码会顺手改 os.environ（PATH / JAVA_HOME），每个用例结束都还原。
计划文档：docs/superpowers/plans/2026-09-29-multi-version-switch.md
"""
import ctypes
import json
import os
import platform as _platform
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

# 本机 WMI 卡死会让 platform.system() 永久阻塞，必须在 import main 之前 stub
_platform._wmi_query = lambda *a, **k: (_ for _ in ()).throw(
    OSError("WMI disabled for test process"))
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402  断言里要用 Qt.DecorationRole
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

        # F10：_write_registry_env 的真实实现写完注册表值后会调
        # EnvManager._broadcast_env_change()（现改为同步 SendMessageTimeoutW 点名
        # Shell_TrayWnd —— 旧的 PostMessageW(HWND_BROADCAST) 实测根本刷不动 explorer）。
        # 把广播原语打桩成"记录请求"（产品码不动）：fake_write 沿用同一调用点
        # 契约，remove_windows_user_env 那条**产品代码里的**直接调用也走这里。
        # 断言广播被请求过 = 断言"持久层写确实发生"这一可观察副作用；广播本身
        # 绝不真发给系统（不打扰用户桌面）。
        self.broadcast_calls = []
        self._orig_broadcast = main.EnvManager._broadcast_env_change
        main.EnvManager._broadcast_env_change = staticmethod(
            lambda: self.broadcast_calls.append("WM_SETTINGCHANGE"))
        self.addCleanup(setattr, main.EnvManager, "_broadcast_env_change",
                        self._orig_broadcast)

        def fake_write(name, value):
            if name.lower() == "path":
                self.win_path[:] = [p for p in str(value).split(";") if p]
            else:
                self.win_env[name] = value
            main.EnvManager._broadcast_env_change()   # 镜像真实 _write_registry_env 的收尾

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

        # 复验要读"系统为新进程合成的环境"，那是宿主机真实状态：不桩住的话，
        # 同一套用例在装了 JDK 的机器上会多出"被 PATH 遮蔽"的橙色态而误红。
        # 默认给"拿不到"（unknown = 不告警），需要具体态的用例自己覆盖。
        self._orig_composed = main.EnvManager.composed_env
        main.EnvManager.composed_env = staticmethod(lambda: {})
        self.addCleanup(setattr, main.EnvManager, "composed_env", self._orig_composed)

        # 同理：切换后会扫"还开着的旧终端"，真机扫描结果随机器状态变化，
        # 默认打桩成"扫不到"，需要内容的用例自己覆盖（见 StaleTerminalNotice）。
        self._orig_shells = main.list_shell_processes
        main.list_shell_processes = lambda: []
        self.addCleanup(setattr, main, "list_shell_processes", self._orig_shells)

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
        # 记录清单挂在**类**上：桩里的 self 是卡片实例而不是 TestCase，
        # 写成 self.probe_calls 会让卡片下次访问时 AttributeError（历史上踩了三次）。
        self.probe_calls = []
        main.ComponentCard.probe_calls = self.probe_calls
        main.ComponentCard._schedule_version_probe = (
            lambda self, exe_path, *a, **k: main.ComponentCard.probe_calls.append(exe_path))
        self.addCleanup(setattr, main.ComponentCard, "_schedule_version_probe", orig_probe)
        self.addCleanup(lambda: setattr(main.ComponentCard, "probe_calls", []))

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

    def test_broadcast_primitive_is_stubbed(self):
        # F10 沙箱自检：广播桩失联时，用例会把 WM_SETTINGCHANGE 真广播到用户
        # 桌面，而所有 win_env/win_path 断言照样全绿——所以必须主动调一次，
        # 确认调用被记录、而不是落向真实的外壳广播。
        before = len(self.broadcast_calls)
        main.EnvManager._broadcast_env_change()
        self.assertEqual(len(self.broadcast_calls), before + 1)


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
        # F3：原来是 isinstance(comp.multi_version, bool)——dataclass 默认值保证了
        # 类型，永远为真，近似同义反复。改成逐组件核对"标志 == 在白名单里"，
        # 把 multi_version 与 MULTI_VERSION_KEYS 的对应关系真钉住。
        for key, comp in self.components.items():
            self.assertEqual(comp.multi_version, key in EXPECTED_MULTI_VERSION, key)

    def test_no_dead_keys_in_multi_version_whitelist(self):
        # F3：MULTI_VERSION_KEYS 里打错一个字母（"jd k"/"python3"）在产品码里
        # 静默无效果——白名单必须是组件 key 全集的子集，这条断言负责报错。
        # 校验放测试侧而不是产品码：运行时检查拖慢启动，且线上不会有第三种人。
        self.assertTrue(main.MULTI_VERSION_KEYS <= {c.key for c in main.build_components()},
                        f"白名单存在死键：{main.MULTI_VERSION_KEYS - {c.key for c in main.build_components()}}")


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


class UnixEnvParsing(EnvSandbox):
    """F6（最终加固轮）：Unix read_user_env 的 `export NAME="…"` 解析回归测试。

    沙箱用 CURRENT_OS="Linux" + 临时 rc，绝不碰真实 ~/.zshrc。值里含引号的
    场景在改造前会被非贪婪解析截断（/opt/jd"k → /opt/jd），读侧改成同行
    贪婪取末引号后修复；含空格与"混有别的工具的相似块"是负向护栏。
    """

    def setUp(self):
        super().setUp()
        self.as_linux()

    def test_value_with_spaces_roundtrips(self):
        main.EnvManager.write_user_env("JAVA_HOME", "/opt/My JDK 21")
        self.assertEqual(main.EnvManager.read_user_env("JAVA_HOME"), "/opt/My JDK 21")

    def test_value_with_quote_roundtrips(self):
        # 修复前红：`"([^"]*)"` 在值内部第一个引号处截断，返回 /opt/jd。
        main.EnvManager.write_user_env("JAVA_HOME", '/opt/jd"k')
        self.assertEqual(main.EnvManager.read_user_env("JAVA_HOME"), '/opt/jd"k')

    def test_foreign_similar_blocks_are_not_parsed(self):
        # rc 里混着别的工具写的相似块（marker 不同）与裸 export 行：
        # ① 没有 byte-tools marker 时绝不把别人的 export 当我们的值；
        # ② 我们写入后，只认自己 marker 块里的值。
        self.rc.write_text(
            '# other tool\n'
            '# >>> other-tool:JAVA_HOME >>>\nexport JAVA_HOME="/opt/foreign"\n'
            '# <<< other-tool <<<\n'
            'export JAVA_HOME="/opt/bare"\n',
            encoding="utf-8")
        self.assertIsNone(main.EnvManager.read_user_env("JAVA_HOME"))
        main.EnvManager.write_user_env("JAVA_HOME", "/opt/ours")
        self.assertEqual(main.EnvManager.read_user_env("JAVA_HOME"), "/opt/ours")
        # 别人的块原样还在（写入端只动自己的 marker 区间）
        self.assertIn('export JAVA_HOME="/opt/foreign"',
                      self.rc.read_text(encoding="utf-8"))


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
        # F8：D6 提示（"已开着的终端/IDE 需重开"）是成功路径的**末行**——
        # apply_active_version 只在一切成功后才追加它。收紧到 steps[-1] 是对
        # 这个顺序承诺的规格锁定，不是给实现上锁（产品码没为测试改过排序）。
        self.assertTrue("已开" in steps[-1] or "重开" in steps[-1],
                        f"决策 D6 的提示必须是末行，实际末行={steps[-1]!r}")
        # F10：切换成功必须请求过"设置变更"广播（断言的是副作用是否发生，
        # 由沙箱广播桩记录；真实的 WM_SETTINGCHANGE 绝不发给用户桌面）。
        self.assertTrue(self.broadcast_calls,
                        "切换成功时应当请求过一次环境变更广播")

    def test_switch_to_the_version_already_on_path_does_not_claim_a_removal(self):
        self.as_windows()
        mine = str(self.comp.install_dir("21.0.4") / "bin")
        self.win_path[:] = [mine, r"C:\Windows\system32"]
        steps = main.apply_active_version(self.comp, "21.0.4")
        self.assertFalse([s for s in steps if "已移除" in s],
                         f"生效版本自己那条只是被重加，日志不许说「已移除其他版本」：{steps}")
        self.assertEqual([p for p in self.win_path if "jdk-" in p.lower()], [mine],
                         "PATH 里本组件必须仍然只有一条")

    def test_removal_line_names_only_the_versions_that_really_left(self):
        self.as_windows()
        self.win_path[:] = [str(self.comp.install_dir("21.0.4") / "bin"),
                            str(self.comp.install_dir("17.0.12") / "bin")]
        steps = main.apply_active_version(self.comp, "17.0.12")
        line = [s for s in steps if "已移除" in s]
        self.assertEqual(len(line), 1, steps)
        self.assertIn("jdk-21.0.4", line[0], "要点名真正被去掉的那条")
        self.assertNotIn("jdk-17.0.12", line[0], "生效版本自己不许出现在「已移除」里")

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

    # ---- F9（最终加固轮）：同版本重复切换必须幂等 ----
    def test_windows_switch_same_version_twice_is_idempotent(self):
        # 连续两次把生效版本设为 21.0.4：第二次跑完，持久层必须与第一次逐条目
        # 相同——PATH 里该组件仍只有一条、JAVA_HOME 不变、登记表不多出一条。
        # 不幂等（比如每次追加一条 PATH）就是真 bug，按最小改动修。
        self.as_windows()
        main.apply_active_version(self.comp, "21.0.4")
        main.save_active_version("jdk", "21.0.4")
        home1, path1 = self.win_env["JAVA_HOME"], list(self.win_path)
        main.apply_active_version(self.comp, "21.0.4")
        main.save_active_version("jdk", "21.0.4")
        self.assertEqual(self.win_env["JAVA_HOME"], home1)
        self.assertEqual(self.win_path, path1)
        self.assertEqual(len([p for p in self.win_path if "jdk-" in p.lower()]), 1)
        self.assertEqual(main.load_active_map(), {"jdk": "21.0.4"})

    def test_linux_switch_same_version_twice_adds_no_extra_rc_block(self):
        # Unix 侧幂等看 rc 文本：第二次切换不许追加第二个 PATH marker 块，
        # 也不许多出一条 export JAVA_HOME（append_unix_path 命中已有 marker
        # 会提前 return，这里把"重复切换不堆块"钉成可观察断言）。
        self.as_linux()
        main.apply_active_version(self.comp, "21.0.4")
        first = self.rc.read_text(encoding="utf-8")
        main.apply_active_version(self.comp, "21.0.4")
        second = self.rc.read_text(encoding="utf-8")
        self.assertEqual(second.count("# >>> byte-tools:PATH:"),
                         first.count("# >>> byte-tools:PATH:"))
        self.assertEqual(second.count("export JAVA_HOME"),
                         first.count("export JAVA_HOME"))
        jdk_bins = [p for p in main.EnvManager.read_user_path_entries()
                    if "jdk-" in p]
        self.assertEqual(len(jdk_bins), 1, main.EnvManager.read_user_path_entries())


class RestoreProcessPathSync(EnvSandbox):
    """F5（最终加固轮）：Unix 回滚后当前进程 PATH 必须与持久层同步。

    旧 Unix 分支全靠 append_unix_path 顺带同步——命中 rc 里已有 marker 时它
    提前 return，进程 PATH 就漏掉了；Windows 分支则对每条都补
    _add_process_path_entry。断言落在第三处 os.environ["PATH"]（此前三条切换
    失败用例只断言了持久层两处，漏了这一处）。EnvSandbox 结束会还原 PATH。
    """

    def setUp(self):
        super().setUp()
        self.comp = self.make_component("jdk", "21.0.4", "17.0.12")

    def _stub_flaky_unix_append(self, fail_entry):
        orig = main.EnvManager.append_unix_path

        def flaky(entry):
            if entry == fail_entry:
                raise OSError("disk full")
            return orig(entry)
        main.EnvManager.append_unix_path = staticmethod(flaky)
        self.addCleanup(setattr, main.EnvManager, "append_unix_path", orig)

    def test_linux_rollback_after_failed_switch_syncs_process_path(self):
        # 完整回滚现场：切 21 失败 → 17 的条目在 rc、read_user_path_entries、
        # os.environ["PATH"] 三处都要同时在场才算"三处一致"（决策 D3 约束 2）。
        self.as_linux()
        old_bin = str(self.comp.install_dir("17.0.12") / "bin")
        main.EnvManager.write_user_env("JAVA_HOME", str(self.comp.install_dir("17.0.12")))
        main.EnvManager.add_path_entry(old_bin)
        self._stub_flaky_unix_append(str(self.comp.install_dir("21.0.4") / "bin"))
        with self.assertRaises(main.SwitchError):
            main.apply_active_version(self.comp, "21.0.4")
        self.assertIn(old_bin, main.EnvManager.read_user_path_entries())
        self.assertIn(old_bin, os.environ.get("PATH", ""))

    def test_restore_syncs_process_path_when_rc_marker_already_exists(self):
        # 不对称本体：持久层已有该条目（marker 命中，append_unix_path 提前 return）
        # 而当前进程 PATH 里没有 → restore_path_entries 仍必须把它补回进程 PATH。
        # 修复前红：Unix 分支跟着提前 return 一起跳过了同步。
        self.as_linux()
        entry = str(self.comp.install_dir("21.0.4") / "bin")
        base = os.environ.get("PATH", "")
        main.EnvManager.add_path_entry(entry)          # rc 落下 marker 块
        os.environ["PATH"] = base                      # 造"持久层有、进程没有"的分叉
        self.assertNotIn(entry, os.environ["PATH"])    # 夹具自查
        main.EnvManager.restore_path_entries([entry])
        self.assertEqual(
            main.EnvManager.read_user_path_entries().count(entry), 1,
            "rc 里命中已有 marker 就不许再追加第二块（幂等）")
        self.assertIn(entry, os.environ["PATH"])


class ActiveConfig(EnvSandbox):
    def test_missing_file_gives_empty_map(self):
        self.assertEqual(main.load_active_map(), {})

    def test_corrupt_file_is_not_fatal(self):
        main.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(main.load_active_map(), {})

    def test_saving_active_keeps_selections(self):
        # theme 代表"未来任务可能新增的其它顶层字段"：合并写必须连它一起保住，
        # 只锚定 selections 会漏掉"保留两键但丢其它键"这类回归。
        main.CONFIG_FILE.write_text(json.dumps(
            {"selections": {"jdk": "17.0.12", "node": "20.15.0"}, "theme": "keep-me"},
            ensure_ascii=False), encoding="utf-8")
        main.save_active_version("jdk", "21.0.4")
        data = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data["active"], {"jdk": "21.0.4"})
        self.assertEqual(data["selections"], {"jdk": "17.0.12", "node": "20.15.0"},
                         "写 active 不许丢 selections")
        self.assertEqual(data["theme"], "keep-me", "写 active 不许丢其它顶层键")

    def test_saving_active_over_corrupt_file_rebuilds_it(self):
        # 文件损坏时 save 的回落：不许抛，且要写出仅含新 active 的可读文件。
        main.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        main.save_active_version("jdk", "21.0.4")  # 不应抛出
        data = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data["active"], {"jdk": "21.0.4"})

    def test_clearing_active_removes_only_that_key(self):
        main.save_active_version("jdk", "21.0.4")
        main.save_active_version("node", "20.15.0")
        main.save_active_version("jdk", None)
        self.assertEqual(main.load_active_map(), {"node": "20.15.0"})

    # ---- F2（最终加固轮）：原子写 + 空串语义 + 值类型校验 ----
    def test_failed_replace_leaves_previous_file_intact(self):
        # 写入走"临时文件 + os.replace"。桩 os.replace 抛错（模拟崩在写中途/
        # 目标被占用）→ 旧文件必须原样可读、load_active_map() 仍返回旧表。
        # 改造前是 CONFIG_FILE.write_text 直写：同样的中断会留下半截 JSON，
        # 读侧回落成空表，所有生效登记静默消失。
        main.save_active_version("jdk", "17.0.12")
        before = main.CONFIG_FILE.read_text(encoding="utf-8")
        orig_replace = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk died"))
        self.addCleanup(setattr, os, "replace", orig_replace)
        with self.assertRaises(OSError):
            main.save_active_version("jdk", "21.0.4")
        self.assertEqual(main.CONFIG_FILE.read_text(encoding="utf-8"), before)
        self.assertEqual(main.load_active_map(), {"jdk": "17.0.12"})

    def test_empty_string_version_is_rejected_not_treated_as_clear(self):
        # 旧语义 `if version:` 把 "" 当"清除"；新语义清除只认 None，空串显式拒绝。
        # 拒绝=不落盘：登记表与文件都保持原样。
        main.save_active_version("jdk", "21.0.4")
        with self.assertRaises(ValueError):
            main.save_active_version("jdk", "")
        self.assertEqual(main.load_active_map(), {"jdk": "21.0.4"})
        # None 仍是唯一的清除语义（护栏：改坏成"None 也 raise"会红）
        main.save_active_version("jdk", None)
        self.assertEqual(main.load_active_map(), {})

    def test_load_skips_non_string_and_empty_values(self):
        # 磁盘上手改的脏值：非字符串/空串值逐键跳过，不整体抛、也不往下传。
        main.CONFIG_FILE.write_text(json.dumps({"active": {
            "jdk": 21, "node": "20.15.0", "go": {"v": 1},
            "maven": "", "gradle": "8.10"}}), encoding="utf-8")
        self.assertEqual(main.load_active_map(),
                         {"node": "20.15.0", "gradle": "8.10"})

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
        # theme 同 ActiveConfig：_save_settings 也只许改 selections，其它顶层键原样保留。
        main.CONFIG_FILE.write_text(json.dumps({"theme": "keep-me"}), encoding="utf-8")
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
        self.assertEqual(data["theme"], "keep-me", "_save_settings 不许丢其它顶层键")


class ConfigureUsesSelectedVersion(EnvSandbox):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card(self, key="jdk", versions=("21", "17", "8")):
        # jdk 的下拉框由组件内置清单（Adoptium 特性大版本 "21"/"17"/"11"/"8"）填充，
        # on_configure_clicked 通过 _current_version() 按下拉文本反查版本，所以这里造的
        # 安装目录必须用同样的大版本串，findText 才能命中；否则选不中、也就测不到"按下拉框生效"。
        comp = self.make_component(key, *versions)
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        return card

    def test_apply_active_sets_home_to_selected_version(self):
        self.as_windows()
        card = self._card()
        self.assertTrue(card._apply_active("17"))
        self.assertEqual(self.win_env["JAVA_HOME"],
                         str(card.component.install_dir("17")))
        self.assertEqual(main.load_active_map()["jdk"], "17")
        self.assertEqual(card.active_version(), "17")

    def test_configure_click_targets_combo_selection_not_lexicographic_last(self):
        # 旧实现在这里会选中 jdk-8（字典序最后一个）
        self.as_windows()
        card = self._card()
        card.version_combo.setCurrentIndex(card.version_combo.findText("21"))
        card.on_configure_clicked()
        self.assertEqual(self.win_env["JAVA_HOME"],
                         str(card.component.install_dir("21")))

    def test_apply_active_failure_leaves_active_untouched(self):
        self.as_windows()
        card = self._card()
        orig = main.EnvManager.append_windows_path
        main.EnvManager.append_windows_path = staticmethod(
            lambda entry: (_ for _ in ()).throw(OSError("boom")))
        self.addCleanup(setattr, main.EnvManager, "append_windows_path", orig)
        self.assertFalse(card._apply_active("17"))
        self.assertNotIn("jdk", main.load_active_map())

    def test_non_multi_version_component_still_configures(self):
        self.as_windows()
        comp = self.make_component("tomcat", "10.1.60")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        card.on_configure_clicked()
        self.assertEqual(self.win_env["CATALINA_HOME"],
                         str(comp.install_dir("10.1.60")))
        self.assertNotIn("tomcat", main.load_active_map(),
                         "非多版本组件不进 active 表")


class InstalledCheckIcon(EnvSandbox):
    """下拉框里的"这个版本磁盘上已装"绿勾。

    规格核心：标记只能挂在 Qt.DecorationRole 上，条目文本一个字都不许动 ——
    _current_version() 与 SearchableComboBox.repopulate(preferred=…) 都是按显示
    文本反查版本对象的，往文本里塞「✓」会连锁打错选版、安装、卸载与配置保存。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    # jdk 的内置清单是大版本串 "21"/"17"/"11"/"8"（main.py:2842-2845），
    # 目录名 jdk-21 与下拉框文本同源。夹具若写 "21.0.4"，findText 永远落空、
    # 断言的分支一行都不会执行 —— Task 6 踩过的假绿灯，这里用 JDK_ALL 自查挡住。
    JDK_ALL = ("21", "17", "11", "8")
    JDK_INSTALLED = ("21", "17")
    # mysql 取它清单里真实存在的三个版本当"已装目录"：一旦 multi_version 的提前返回
    # 被删掉，这三个条目就会挂上图标，本用例立刻变红（回归护栏要有牙）。
    MYSQL_ALL = ("8.0.28", "8.0.29", "8.0.37")

    def _jdk_card(self):
        comp = self.make_component("jdk", *self.JDK_INSTALLED)
        return main.ComponentCard(comp, lambda lvl, msg: None)

    @staticmethod
    def _labels(combo):
        return [combo.itemText(i) for i in range(combo.count())]

    @staticmethod
    def _mark(combo, index):
        """该条目的 DecorationRole 状态：True=有图 / False=挂了空图 / None=压根没挂。"""
        data = combo.itemData(index, Qt.DecorationRole)
        if data is None:
            return None
        return not data.isNull()

    def test_installed_items_get_icon_and_text_is_untouched(self):
        card = self._jdk_card()
        combo = card.version_combo
        self.assertEqual(tuple(self._labels(combo)), self.JDK_ALL)
        before = self._labels(combo)
        idx_before = combo.currentIndex()
        text_before = combo.currentText()
        committed_before = combo._committed_text
        signals = []
        combo.currentTextChanged.connect(lambda t: signals.append(("currentTextChanged", t)))
        combo.activated.connect(lambda i: signals.append(("activated", i)))

        card._refresh_installed_marks()

        after = self._labels(combo)
        self.assertEqual(after, before,
                         "条目文本必须逐字不变：_current_version() 按文本反查版本对象")
        # 挂图标是纯数据写入，不许惊动选择相关的一切状态与信号
        self.assertEqual(combo.currentIndex(), idx_before)
        self.assertEqual(combo.currentText(), text_before)
        self.assertEqual(combo._committed_text, committed_before)
        self.assertEqual(signals, [], "刷新触发 currentTextChanged/activated 会连锁改选中项")
        self.assertEqual(card._current_version().version, self.JDK_ALL[idx_before])

        marked = [i for i, v in enumerate(card.component.versions)
                  if v.version in self.JDK_INSTALLED]
        unmarked = [i for i, v in enumerate(card.component.versions)
                    if v.version not in self.JDK_INSTALLED]
        self.assertTrue(marked and unmarked, "夹具必须同时覆盖已装与未装，否则本用例形同没跑")
        for i in marked:
            self.assertEqual(self._mark(combo, i), True, after[i])
        for i in unmarked:
            self.assertEqual(self._mark(combo, i), False, after[i])

    def test_marks_are_already_there_right_after_the_card_is_built(self):
        # 建卡走 _reload_combo_items 的 count()==0 分支，勾要在同一次装载里挂上，
        # 不能等外部再补一次调用（否则首屏永远没有标记）。
        card = self._jdk_card()
        combo = card.version_combo
        for label in self.JDK_INSTALLED:
            self.assertEqual(self._mark(combo, combo.findText(label)), True, label)
        for label in ("11", "8"):
            self.assertEqual(self._mark(combo, combo.findText(label)), False, label)

    def test_non_multi_version_component_also_gets_icons(self):
        """非多版本组件**也要**挂已装图标（2026-10-06 改）。

        原来是 `test_non_multi_version_component_gets_no_icons`，断言"提前返回、
        压根不写 DecorationRole"。那守的是**实现手段**（靠 `if not multi_version:
        return` 提前返回），不是目的 —— 目的是"已装的版本要标出来"。
        真机 2026-10-06 的表现：python 有勾，jenkins / nacos / activemq / powershell
        全都没有，恰好是 `multi_version` 的分界线；用户报"很多组件装完不显示绿勾"。

        `multi_version` 管的是"能不能多版本并存"（R3 语义），不该管"要不要显示已装"。
        注意 `make_component` 会把传入的每个版本都在磁盘上造出来，所以这里 MYSQL_ALL
        全是"已装"、全该有勾；另有一个没传的版本用来验"没装的必须是没有勾"。
        逐项都必须是明确的布尔值而不是 None —— None 是"没查过"，False 是"查了，没装"。
        """
        comp = self.make_component("mysql", *self.MYSQL_ALL)
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        combo = card.version_combo
        self.assertEqual(combo.count(), len(self.MYSQL_ALL))
        card._refresh_installed_marks()
        for i in range(combo.count()):
            label = combo.itemText(i)
            # make_component 已为 MYSQL_ALL 的每个版本造了 bin 目录 → 都算已装
            self.assertIsNotNone(self._mark(combo, i), label + "：没有查过装没装")
            self.assertIs(self._mark(combo, i), True, label + "：磁盘上有目录，该有勾")

    def test_marks_refresh_after_reloading_versions(self):
        # 抓取线程回填版本列表会 clear()+addItems() 重建条目，勾必须跟着重建
        card = self._jdk_card()
        combo = card.version_combo
        combo.setCurrentIndex(combo.findText("17"))
        fresh = [cv for cv in card.component.versions if cv.version in self.JDK_INSTALLED]
        self.assertEqual(len(fresh), len(self.JDK_INSTALLED),
                         "夹具版本必须在组件清单里，否则 set_versions 之后什么都测不到")

        card.set_versions(fresh)

        self.assertEqual(self._labels(combo), list(self.JDK_INSTALLED))
        for label in self.JDK_INSTALLED:
            self.assertEqual(self._mark(combo, combo.findText(label)), True, label)
        # 重建条目不许把用户当前选中项换掉
        self.assertEqual(combo.currentText(), "17")

    def test_uninstalled_version_loses_its_mark(self):
        card = self._jdk_card()
        combo = card.version_combo
        self.assertEqual(self._mark(combo, combo.findText("17")), True)
        shutil.rmtree(card.component.install_dir("17"))   # 沙箱内的临时目录
        card._refresh_installed_marks()
        self.assertEqual(self._mark(combo, combo.findText("17")), False)
        # 别的已装版本的勾不受影响
        self.assertEqual(self._mark(combo, combo.findText("21")), True)

    def test_row_count_mismatch_skips_refresh_instead_of_miswriting(self):
        # F4 护栏用例：手动把 combo 删成 2 行，与 component.versions（4 项）错位。
        # 改造前按 enumerate 行号写：留下的 "11"/"8" 没装，却会收到清单前两项
        # （21/17 已装）的勾——写歪；行号越界时还会 IndexError。
        # 规格：行数不齐就整轮跳过——不抛异常、既有条目数据一个都不许被改写。
        card = self._jdk_card()
        combo = card.version_combo
        self.assertEqual(combo.count(), len(self.JDK_ALL))     # 夹具自查：先要齐
        combo.removeItem(combo.findText("21"))
        combo.removeItem(combo.findText("17"))
        self.assertEqual(tuple(self._labels(combo)), ("11", "8"))
        self.assertNotEqual(combo.count(), len(card.component.versions))
        before = [self._mark(combo, i) for i in range(combo.count())]
        card._refresh_installed_marks()                        # 不应抛任何异常
        self.assertEqual([self._mark(combo, i) for i in range(combo.count())], before,
                         "行数不齐的一轮不许写歪任何图标（宁可这轮不刷勾）")

    def test_apply_active_refreshes_the_marks(self):
        # Task 6 刻意留白、本任务补上的接线：_apply_active 成功后要重挂一次勾。
        # 断言只落在可观察状态（条目的 DecorationRole 图标）上，不看任何桩的调用
        # 次数：先让 "11" 在磁盘上不存在（勾为 False），造出目录后走真实的
        # _apply_active —— 勾变 True 的唯一途径就是它内部重扫了一次磁盘。
        # 把那一行接线弄丢，本用例必红。
        self.as_windows()
        card = self._jdk_card()
        combo = card.version_combo
        self.assertEqual(tuple(self._labels(combo)), self.JDK_ALL)
        self.assertEqual(self._mark(combo, combo.findText("11")), False,
                         '夹具前提：11 此刻还没有安装目录，勾不该存在')

        # 唯一的状态变化：磁盘上多出 jdk-11/bin。不打桩、不手动刷新、不动下拉框。
        (card.component.install_dir("11") / "bin").mkdir(parents=True, exist_ok=True)

        self.assertTrue(card._apply_active("11"))

        self.assertEqual(self._mark(combo, combo.findText("11")), True,
                         "_apply_active 成功后未重扫磁盘：新装的版本没挂上勾")
        # 无附带损害：其余版本的勾各归各位（21/17 仍挂着，8 仍未装）
        for label, expected in (("21", True), ("17", True), ("8", False)):
            self.assertEqual(self._mark(combo, combo.findText(label)), expected, label)
        # 刷新只许改图标数据，条目文本依旧逐字不变
        self.assertEqual(tuple(self._labels(combo)), self.JDK_ALL)


class StatusCapsuleForMultiVersion(EnvSandbox):
    """多版本组件的状态胶囊：已装清单 + 生效版本 + 按钮启用逻辑 + 只探测生效版本。

    夹具纠偏（Task 6/7 都踩过的坑）：jdk 的下拉框由内置大版本清单 "21/17/11/8"
    填充（main.py:2842-2845）。胶囊里的 selected 走 _current_version()（按下拉文本
    反查清单）、active 走 active_version()，两者都与清单同源。若把安装目录名写成
    "21.0.4"，findText 永远返回 -1、selected 反查落回清单首项 "21"，与
    active="21.0.4" 永不相等 —— 想断言的分支一行都不会执行，是假绿灯。
    所以这里全用清单里真实存在的大版本串，并自查它们确实进了下拉框。
    另外 make_component 只造 bin/ 目录，探测分支要能被记录必须让 exec_path_in_home
    命中：这里为每个已装版本补一个空的 java 桩文件。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    JDK_ACTIVE = "21"
    JDK_OTHER = "17"
    JDK_THIRD = "11"

    def _wire_probe_recorder(self):
        # enable_detect 的记录桩写成 self.probe_calls，而那个 self 是卡片实例（bound
        # method 的首参），不是 TestCase。卡片构造时就会触发一次探测，早于我们能拿到
        # 卡片引用，所以只能把记录目标先挂到类属性上，让它与 TestCase 的列表同一对象。
        main.ComponentCard.probe_calls = self.probe_calls
        self.addCleanup(delattr, main.ComponentCard, "probe_calls")

    def _card(self, active=None):
        comp = self.make_component("jdk", self.JDK_ACTIVE, self.JDK_OTHER)
        # 补可执行文件桩：胶囊分支对"生效版本"排一次探测，前提是能找到 exe
        for v in (self.JDK_ACTIVE, self.JDK_OTHER):
            (comp.install_dir(v) / "bin" / "java").write_text("", encoding="utf-8")
        self.as_windows()
        if active:
            main.save_active_version("jdk", active)
        self.enable_detect()          # 胶囊用例要真实探测；探测线程已被 enable_detect 换成记录调用
        self._wire_probe_recorder()
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        # 夹具自查：断言用到的版本标签必须真在下拉框里（Task 7 同款护栏）
        for label in (self.JDK_ACTIVE, self.JDK_OTHER):
            self.assertNotEqual(card.version_combo.findText(label), -1,
                                f"夹具版本 {label} 不在 jdk 下拉清单里，分支测不到")
        return card

    def _card3(self, active=None):
        # 装三个版本 21/17/11（installed_versions 语义降序 = 21、17、11），
        # 让"生效版本"与"最高已装版本"可区分：active 是中间的 17 或最低的 11 时，
        # 任何"从清单首项推断生效"的实现都会露馅。
        comp = self.make_component("jdk", self.JDK_ACTIVE, self.JDK_OTHER, self.JDK_THIRD)
        for v in (self.JDK_ACTIVE, self.JDK_OTHER, self.JDK_THIRD):
            (comp.install_dir(v) / "bin" / "java").write_text("", encoding="utf-8")
        self.as_windows()
        if active:
            main.save_active_version("jdk", active)
        self.enable_detect()
        self._wire_probe_recorder()
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        for label in (self.JDK_ACTIVE, self.JDK_OTHER, self.JDK_THIRD):
            self.assertNotEqual(card.version_combo.findText(label), -1,
                                f"夹具版本 {label} 不在 jdk 下拉清单里，分支测不到")
        return card

    def test_two_installed_one_active(self):
        card = self._card(active=self.JDK_ACTIVE)
        text = card.status_label.text()
        self.assertIn("已装 2 个版本", text)
        self.assertIn(f"生效 {self.JDK_ACTIVE}", text)
        self.assertIn(self.JDK_OTHER, text)

    def test_installed_but_none_active_says_so(self):
        card = self._card(active=None)
        self.assertIn("均未生效", card.status_label.text())

    def test_configure_button_disabled_when_selection_is_already_active(self):
        card = self._card(active=self.JDK_ACTIVE)
        card.version_combo.setCurrentIndex(card.version_combo.findText(self.JDK_ACTIVE))
        card._detect_status()
        self.assertFalse(card.btn_configure.isEnabled())

    def test_configure_button_enabled_for_the_other_version(self):
        card = self._card(active=self.JDK_ACTIVE)
        card.version_combo.setCurrentIndex(card.version_combo.findText(self.JDK_OTHER))
        card._detect_status()
        self.assertTrue(card.btn_configure.isEnabled())
        self.assertIn("生效", card.btn_configure.toolTip())

    def test_non_multi_version_capsule_text_unchanged(self):
        # 回归护栏：非多版本组件的胶囊必须还是老文案，不能被新逻辑污染
        comp = self.make_component("tomcat", "10.1.60")
        self.as_windows()
        self.win_env["CATALINA_HOME"] = str(comp.install_dir("10.1.60"))
        self.enable_detect()
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        text = card.status_label.text()
        self.assertNotIn("已装", text)
        self.assertTrue(text)                          # 而不是空字符串
        # 缺陷 C：把"逐字一致"真钉住——本 fixture 只造了空的 bin/ 目录、没有
        # catalina 可执行文件，detect() 判不到「已配置」，落回「已下载未配置」这条
        # 老文案（不是 ✓ 已配置、也不是 ○ 未安装）。断言实际产出的旧文案前缀。
        self.assertEqual(text, "● 已下载，未配置")

    def test_only_the_active_version_is_probed(self):
        card = self._card(active=self.JDK_ACTIVE)
        self.assertEqual(len(self.probe_calls), 1, self.probe_calls)
        self.assertIn(f"jdk-{self.JDK_ACTIVE}", self.probe_calls[0])

    # ---- 缺陷 A：异步版本探测回填必须进多版本胶囊 ----
    def test_probed_version_lands_in_multiversion_capsule(self):
        # _on_version_probed 的闸门读 _status_shows_configured，该标志此前只在
        # 非多版本分支赋值 → 多版本卡片恒 False → 分支末尾排出去的 VersionProbeWorker
        # 回来后（java --version 的精确串，如 21.0.4）被直接丢弃。改造前 jdk 能显示
        # 精确版本，现在丢了。可观察结果 = status_label.text()：回填后既要有版本号，
        # 又要基础胶囊文案逐字保留，且绝不落到旧的「✓ 已配置」文案。
        card = self._card(active=self.JDK_ACTIVE)
        base = card.status_label.text()
        self.assertIn("已装 2 个版本", base)
        self.assertIn(f"生效 {self.JDK_ACTIVE}", base)
        self.assertNotIn("21.0.4", base)               # 回填前没有版本号
        # 模拟探测线程 done 信号回来（worker 传默认 None，跳过"是否被新一轮取代"那道闸）
        card._on_version_probed("21.0.4")
        text = card.status_label.text()
        self.assertIn("21.0.4", text)                  # 版本号进胶囊
        self.assertIn("已装 2 个版本", text)            # 正文逐字不变
        self.assertIn(f"生效 {self.JDK_ACTIVE}", text)
        self.assertNotIn("已配置", text)               # 不许掉回旧的 ✓ 已配置文案
        self.assertNotIn("版本检测中", text)           # 回填后不再是"检测中"占位

    def test_probed_version_discarded_when_none_active(self):
        # 均未生效（active 为空）时既没排探测、_status_shows_configured 也应为 False，
        # 迟到的探测结果必须被丢掉，胶囊正文保持"均未生效"基础文案不被追加版本号。
        card = self._card(active=None)
        base = card.status_label.text()
        self.assertIn("均未生效", base)
        card._status_version = ""
        card._on_version_probed("21.0.4")
        self.assertEqual(card.status_label.text(), base)

    # ---- 缺陷 B：生效版本一律以 active_version()（登记表）为准，不得推断为最高版本 ----
    def test_active_is_not_the_highest_installed_version(self):
        # 装 21/17/11，把生效登记成中间的 17、下拉框选中最高的 21。
        # 若把 active 误写成 ordered[0][0]（最高版本），胶囊会说"生效 21"、且按钮被禁用，
        # 这两处断言同时红——正是 reviewer 注入 ordered[0] 后现有用例抓不到的原因。
        card = self._card3(active=self.JDK_OTHER)      # 生效 17
        text = card.status_label.text()
        self.assertIn("已装 3 个版本", text)
        self.assertIn(f"生效 {self.JDK_OTHER}", text)
        self.assertNotIn(f"生效 {self.JDK_ACTIVE}", text)   # 生效的不是最高版本 21
        card.version_combo.setCurrentIndex(card.version_combo.findText(self.JDK_ACTIVE))
        card._detect_status()
        self.assertTrue(card.btn_configure.isEnabled())     # 选中 21 ≠ 生效 17 → 可点
        self.assertIn("生效", card.btn_configure.toolTip())

    def test_active_lowest_installed_version_is_the_active_one(self):
        # 生效登记成最低的 11，同理必须显示"生效 11"而非最高版本 21。
        card = self._card3(active=self.JDK_THIRD)      # 生效 11
        text = card.status_label.text()
        self.assertIn(f"生效 {self.JDK_THIRD}", text)
        self.assertNotIn(f"生效 {self.JDK_ACTIVE}", text)
        card.version_combo.setCurrentIndex(card.version_combo.findText(self.JDK_ACTIVE))
        card._detect_status()
        self.assertTrue(card.btn_configure.isEnabled())


class UninstallScope(EnvSandbox):
    """Task 9：卸载只清被删版本的 PATH 条目，删掉生效版本时自动重排。

    现状 bug：Component.uninstall 按「组件根」扫 PATH（main.py:381-392），
    装了 21 和 17 时删 17 会把 21 的条目一起删掉 —— 多版本功能直接漏底。
    C:\\Windows\\system32 是"用户自己的条目"锚点：任何卸载都不许碰它。
    """

    def setUp(self):
        super().setUp()
        self.as_windows()
        self.comp = self.make_component("jdk", "21.0.4", "17.0.12")
        self.win_path[:] = [str(self.comp.install_dir("21.0.4") / "bin"),
                            str(self.comp.install_dir("17.0.12") / "bin"),
                            r"C:\Windows\system32"]
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("21.0.4"))
        main.save_active_version("jdk", "21.0.4")

    def test_uninstall_keeps_other_versions_path_entry(self):
        # 现状 bug：PATH 清理按组件根，删 17 会把 21 的条目一起删掉
        self.comp.uninstall("17.0.12")
        self.assertIn(str(self.comp.install_dir("21.0.4") / "bin"), self.win_path)
        self.assertNotIn(str(self.comp.install_dir("17.0.12") / "bin"), self.win_path)
        self.assertIn(r"C:\Windows\system32", self.win_path, "用户自己的条目不许被捎带删掉")

    def test_uninstall_other_version_keeps_active_home(self):
        # 删的非生效版本：JAVA_HOME 与 active 登记都必须原样保留
        # （改造前第 2 步按 _under_root 判删，"删了 17 把 21 的 JAVA_HOME 也清了"）
        self.comp.uninstall("17.0.12")
        self.assertEqual(self.win_env["JAVA_HOME"], str(self.comp.install_dir("21.0.4")))
        self.assertEqual(main.load_active_map()["jdk"], "21.0.4")

    def test_uninstalling_active_version_repoints_to_highest_remaining(self):
        summary = self.comp.uninstall("21.0.4")
        self.assertEqual(main.load_active_map()["jdk"], "17.0.12")
        self.assertEqual(self.win_env["JAVA_HOME"], str(self.comp.install_dir("17.0.12")))
        self.assertIn("生效版本已自动切到 17.0.12", summary)

    def test_uninstalling_last_version_clears_active_and_env(self):
        self.comp.uninstall("21.0.4")
        self.comp.uninstall("17.0.12")
        self.assertNotIn("jdk", main.load_active_map())
        self.assertNotIn("JAVA_HOME", self.win_env)
        self.assertEqual([p for p in self.win_path if "jdk-" in p.lower()], [])
        self.assertIn(r"C:\Windows\system32", self.win_path)


class UninstallDeadHomeCleanup(EnvSandbox):
    """裁决 2（task-9-fix-1）：HOME 落在本组件根内、却指向一个已经不存在的目录 =
    早年手工删目录留下的死配置，uninstall 第 2 步必须清掉它。判据是"目录不存在"
    而不是"本次没删到东西"——rmtree 失败（目录还在）时不得误清活的 HOME。

    夹具沿用 UninstallScope 的形状：as_windows + jdk 21.0.4/17.0.12 + 两条版本
    PATH 条目 + C:\\Windows\\system32 锚点。断言只看 win_env / win_path / active
    登记表 / 摘要文本，绝不断言桩的调用次数。
    """

    def setUp(self):
        super().setUp()
        self.as_windows()
        self.comp = self.make_component("jdk", "21.0.4", "17.0.12")
        self.win_path[:] = [str(self.comp.install_dir("21.0.4") / "bin"),
                            str(self.comp.install_dir("17.0.12") / "bin"),
                            r"C:\Windows\system32"]
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("21.0.4"))
        main.save_active_version("jdk", "21.0.4")

    def test_non_multi_version_dead_home_is_cleaned(self):
        # 裁决 2 的复现路径（本条是必须修的那条）：用户手工删掉了安装目录，
        # CATALINA_HOME 还指着 tomcat 根下那个已消失的目录，磁盘上没有任何已装目录。
        # 改造前靠 _under_root 那一支顺手清掉；Task 9 把条件收紧成
        # "install_path is not None" 后沉默了——非多版本组件没有第 4 步兜底，
        # 死配置会永久留在注册表里。红点：CATALINA_HOME 仍在 win_env 里。
        comp = self.make_component("tomcat")            # 不造任何安装目录
        self.win_env["CATALINA_HOME"] = str(comp.install_dir("9.0.122"))  # 只造路径不造目录
        summary = comp.uninstall("9.0.122")
        self.assertNotIn("CATALINA_HOME", self.win_env)
        self.assertIn("已清理指向不存在目录的环境变量：CATALINA_HOME", summary)

    def test_multi_version_dead_home_cleared_with_last_version(self):
        # 多版本侧：只装着 21，JAVA_HOME 指向 jdk-11（磁盘上不存在），卸载 21 之后
        # JAVA_HOME 必须没了。改造前第 4 步"全删光"分支会兜底，这条可能上来就绿
        # ——按裁决保留为回归护栏（裁决原文见 task-9-fix-1.md 必须补的测试 2）。
        shutil.rmtree(self.comp.install_dir("17.0.12"))   # 场景是"只装着 21"
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("11"))   # jdk-11 从未安装
        main.save_active_version("jdk", "21.0.4")
        self.comp.uninstall("21.0.4")
        self.assertNotIn("JAVA_HOME", self.win_env)

    def test_rmtree_failure_does_not_trigger_dead_home_cleanup(self):
        # 护栏 4（裁决原文形状：HOME 指向被删目录、rmtree 抛异常、目录仍在）：
        # 新分支的判据是"目录不存在"，绝不能顺着"这次没删掉"把 HOME 当死配置清掉。
        # shutil.rmtree 测试侧打桩（不在产品代码里加开关），addCleanup 还原。
        orig_rmtree = shutil.rmtree
        shutil.rmtree = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        self.addCleanup(setattr, shutil, "rmtree", orig_rmtree)
        # setUp 夹具：JAVA_HOME 正指着要删的 21.0.4，active=21.0.4
        summary = self.comp.uninstall("21.0.4")
        self.assertTrue(self.comp.install_dir("21.0.4").is_dir())   # 目录确实还在磁盘
        self.assertIn("删除安装目录失败", summary)
        self.assertNotIn("已清理指向不存在目录的环境变量", summary)
        # 目录还在 → HOME 不许被清成死值/指空：持久层里它必须仍指向一个存在的目录。
        self.assertTrue(Path(self.win_env["JAVA_HOME"]).is_dir(),
                        self.win_env)

    def test_rmtree_failure_keeps_live_home_of_other_version(self):
        # 同一条护栏的 win_env 直断言版：rmtree 失败没删掉的目录（21）还在磁盘上，
        # 而 JAVA_HOME 指着另一个还在的版本（17）→ HOME 必须原样保留。
        # 谁把新判据写成"删不到就清"，这条立刻红。
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("17.0.12"))
        main.save_active_version("jdk", "17.0.12")
        orig_rmtree = shutil.rmtree
        shutil.rmtree = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        self.addCleanup(setattr, shutil, "rmtree", orig_rmtree)
        summary = self.comp.uninstall("21.0.4")
        self.assertEqual(self.win_env["JAVA_HOME"], str(self.comp.install_dir("17.0.12")))
        self.assertNotIn("已清理指向不存在目录的环境变量", summary)


class UninstallActiveGuardFix2(EnvSandbox):
    """Task 9 修复轮 2（评审 1 Blocker + 2 Important，裁决见 task-9-fix-2.md）。

    B   ：第 4 步"全删光"分支没有 HOME 守卫，会把用户指到组件根之外的 XXX_HOME 一起删掉；
    I-1 ：老配置没有 active 登记表，生效版本全靠 XXX_HOME 反推，而第 4 步排在第 2 步
          删 HOME 之后 → 反推永远是 None → "自动重排"静默失效。修法是在任何破坏性
          动作之前做 active_before 快照；
    I-2 ：重排把 apply_active_version 的 steps 整个扔了（D6 的"已开着的终端/IDE 不受
          影响"与 Oracle javapath 提醒丢失），且 save_active_version 裸调用，
          OSError 会穿透 uninstall。

    夹具沿用 UninstallScope 的形状：as_windows + jdk 21.0.4/17.0.12 + 两条版本
    PATH 条目 + C:\\Windows\\system32 锚点。断言只看 win_env / win_path /
    CONFIG_FILE / 摘要文本，绝不断言桩的调用次数。
    """

    def _seed_jdk_two_versions(self, active, home_on):
        """造 UninstallScope 同款现场：装 21.0.4+17.0.12，各留一条 PATH 条目。

        active=None 时不写登记表（模拟只有 selections 的老 config.json）。
        """
        self.as_windows()
        comp = self.make_component("jdk", "21.0.4", "17.0.12")
        self.win_path[:] = [str(comp.install_dir("21.0.4") / "bin"),
                            str(comp.install_dir("17.0.12") / "bin"),
                            r"C:\Windows\system32"]
        self.win_env["JAVA_HOME"] = str(comp.install_dir(home_on))
        if active:
            main.save_active_version("jdk", active)
        else:
            # 老配置：文件存在但没有任何 active 登记条目
            main.CONFIG_FILE.write_text(
                json.dumps({"selections": {"jdk": "21.0.4"}}, ensure_ascii=False),
                encoding="utf-8")
        return comp

    # ---- B：Blocker 的真实复现（多版本组件走得到第 4 步，非多版本走不到，见下两条） ----
    def test_b_full_uninstall_keeps_out_of_root_home(self):
        # jdk 只剩最后一个版本，JAVA_HOME 是用户自己指到组件根之外的 JDK。
        # 现网第 4 步 `if not remaining:` 读到一个值就删，没有 _under_root 守卫。
        # 红点：卸载后 JAVA_HOME 不在 win_env 里（用户自己的 JDK 入口被顺带删了）。
        self.as_windows()
        comp = self.make_component("jdk", "21.0.4")
        foreign = r"C:\Program Files\Java\jdk1.8.0_202"
        self.win_env["JAVA_HOME"] = foreign
        self.win_path[:] = [str(comp.install_dir("21.0.4") / "bin"), r"C:\Windows\system32"]
        main.save_active_version("jdk", "21.0.4")
        summary = comp.uninstall("21.0.4")
        self.assertEqual(self.win_env.get("JAVA_HOME"), foreign,
                         "用户指到组件目录之外的 JAVA_HOME 绝不许被卸载顺带删掉")
        self.assertIn("指向组件目录之外", summary)
        self.assertIn(r"C:\Windows\system32", self.win_path)

    def test_b_non_mv_full_uninstall_keeps_out_of_root_home(self):
        # brief 用例 1 的场景（非多版本 tomcat + 组件根外的 CATALINA_HOME）。
        # 如实说明：现网第 4 步整体在 `if self.multi_version:` 之下，非多版本组件根本
        # 走不到 Blocker 那段代码，且第 2 步的 _under_root 守卫改造前就有——所以这条
        # 在修复前就是绿的（与 brief"这条现在必红"的预判不符，见报告）。
        # 措辞只断言修复前后都不变的"未删除"：新句子"指向组件目录之外"仅由第 4 步
        # （多版本）产出，为非多版本组件改第 2 步措辞超出本轮 scope。
        self.as_windows()
        comp = self.make_component("tomcat", "10.1.60")
        foreign = r"C:\somewhere\apache-tomcat"
        self.win_env["CATALINA_HOME"] = foreign
        self.win_path[:] = [str(comp.install_dir("10.1.60") / "bin"), r"C:\Windows\system32"]
        summary = comp.uninstall("10.1.60")
        self.assertEqual(self.win_env.get("CATALINA_HOME"), foreign)
        self.assertIn("CATALINA_HOME", summary)
        self.assertIn("未删除", summary)

    def test_b2_inside_root_home_cleared_with_last_version(self):
        # brief 用例 2（B 的另一面，原有行为护栏）：JAVA_HOME 指着本组件目录内的
        # 最后一个版本，卸完 HOME 必须被清。摘要句子按本轮改名后的措辞断言——
        # 旧句"生效登记与环境变量均已清除"在外指 HOME 被保留时是假话。
        self.as_windows()
        comp = self.make_component("jdk", "21.0.4")
        self.win_env["JAVA_HOME"] = str(comp.install_dir("21.0.4"))
        self.win_path[:] = [str(comp.install_dir("21.0.4") / "bin"), r"C:\Windows\system32"]
        main.save_active_version("jdk", "21.0.4")
        summary = comp.uninstall("21.0.4")
        self.assertNotIn("JAVA_HOME", self.win_env)
        self.assertNotIn("jdk", main.load_active_map())
        self.assertIn("已无安装版本，生效登记已清除", summary)

    # ---- I-1：老配置（无 active 登记表）的自动重排 ----
    def test_i1_old_config_repoints_after_uninstalling_inferred_active(self):
        # 评审复现的 PROBE-B：登记表没有 jdk 条目，生效全靠 JAVA_HOME=21 反推；
        # 现网第 4 步在第 2 步删掉那个 HOME 之后才读 → active=None → 不重排不提示。
        # 红点：load_active_map() 里没有 jdk，JAVA_HOME 被清空而 17.0.12 明明还装着。
        comp = self._seed_jdk_two_versions(active=None, home_on="21.0.4")
        self.assertNotIn("jdk", main.load_active_map())      # 夹具自查：确无登记表
        summary = comp.uninstall("21.0.4")
        self.assertEqual(main.load_active_map().get("jdk"), "17.0.12")
        self.assertEqual(self.win_env.get("JAVA_HOME"), str(comp.install_dir("17.0.12")))
        self.assertIn("生效版本已自动切到 17.0.12", summary)

    def test_i1b_live_active_rebuilt_when_uninstalling_the_other_version(self):
        # I-1 姊妹：登记表 active=17 且 17 还在装，但 JAVA_HOME 脏指 21 →
        # 卸 21 把 HOME 一起删了（第 2 步）。修好后第 4 步必须按活着的 active 重建：
        # HOME 指回 17、17 的 bin 在 PATH、21 的条目没了。
        comp = self._seed_jdk_two_versions(active="17.0.12", home_on="21.0.4")
        summary = comp.uninstall("21.0.4")
        self.assertEqual(self.win_env.get("JAVA_HOME"), str(comp.install_dir("17.0.12")))
        self.assertIn(str(comp.install_dir("17.0.12") / "bin"), self.win_path)
        self.assertNotIn(str(comp.install_dir("21.0.4") / "bin"), self.win_path)
        self.assertIn(r"C:\Windows\system32", self.win_path)
        # N-2 措辞分叉（task-9-fix-3.md）：target == active（17 本来就在生效）是
        # "重建"不是"切"，旧句"生效版本已自动切到 17.0.12"在本场景是假话。
        self.assertIn("已按生效版本 17.0.12 重建环境变量与 PATH", summary)

    # ---- I-2：D6 提醒进摘要 + 登记表写失败如实报告 ----
    def test_i2_repoint_summary_carries_d6_notice(self):
        # D6 要求告知"已开着的终端/IDE 不受影响"与 Oracle javapath 抢先，
        # 那句话是 apply_active_version steps 的末行（main.py:4000-4001）。
        # 现网 `apply_active_version(self, nxt)` 把返回值整个扔了 → 红点：摘要没这两句。
        comp = self._seed_jdk_two_versions(active="21.0.4", home_on="21.0.4")
        summary = comp.uninstall("21.0.4")
        self.assertIn("已开着的终端", summary)
        self.assertIn("javapath", summary)

    def test_i2b_active_map_write_failure_is_reported_as_partial_success(self):
        # 登记表写失败（CONFIG_FILE.write_text 抛 OSError）不许把整个卸载炸成
        # "卸载失败"——此刻环境已经真切到 17 了。测试侧打桩 main.save_active_version
        # （产品里不加开关），addCleanup 还原。
        # 现网红点：裸调用 main.py:445 的 OSError 直接穿透 comp.uninstall。
        comp = self._seed_jdk_two_versions(active="21.0.4", home_on="21.0.4")
        orig = main.save_active_version
        main.save_active_version = lambda key, version: (_ for _ in ()).throw(
            OSError("disk full"))
        self.addCleanup(setattr, main, "save_active_version", orig)
        summary = comp.uninstall("21.0.4")                    # 不应抛出
        self.assertIn("登记表写入失败", summary)
        self.assertIn("生效版本已自动切到 17.0.12", summary)
        # 环境侧确已成功切到 17 —— 摘要必须如实说"环境切了、登记没写"
        self.assertEqual(self.win_env.get("JAVA_HOME"), str(comp.install_dir("17.0.12")))


class UninstallTargetResolve(EnvSandbox):
    """修正 1：resolve_uninstall_target 只做最小改动。

    保留 exact → XXX_HOME → 单目录这条链（XXX_HOME 指的是当前生效版本，
    比"猜最高"更准），只把 len(dirs) > 1 的"罢工"分支换成按 installed_versions()
    降序取最高并说明；非多版本组件的罢工行为必须与改造前逐字一致。
    """

    def setUp(self):
        super().setUp()
        self.as_windows()
        self.comp = self.make_component("jdk", "21.0.4", "17.0.12")

    def test_missing_selection_resolves_to_env_home_not_guessed_highest(self):
        # JAVA_HOME 指着生效中的 17：按它定位才对，按语义最高猜 21 会切错版本
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("17.0.12"))
        path, note = self.comp.resolve_uninstall_target("99.9.9")
        self.assertEqual(path, self.comp.install_dir("17.0.12"))
        self.assertIn("JAVA_HOME", note)

    def test_missing_selection_without_env_home_takes_highest(self):
        # 改造前这条会罢工返回 None（卸载整条链路失灵）；现在降序取最高并说明
        path, note = self.comp.resolve_uninstall_target("99.9.9")
        self.assertEqual(path, self.comp.install_dir("21.0.4"))
        self.assertIn("改为卸载版本最高的 21.0.4", note)

    def test_unparseable_dirs_refuse_with_version_note(self):
        # 多个目录但版本号都反解不出来：仍罢工，但说明原因换了（能识别时不走到这）
        shutil.rmtree(self.comp.install_dir("21.0.4"))
        shutil.rmtree(self.comp.install_dir("17.0.12"))
        for name in ("weird-a", "weird-b"):
            (main.CONFIG_DIR / "jdk" / name).mkdir(parents=True)
        path, note = self.comp.resolve_uninstall_target("99.9.9")
        self.assertIsNone(path)
        self.assertIn("无法识别版本号", note)

    def test_non_multi_version_with_two_dirs_still_refuses(self):
        # 硬约束：非多版本组件行为与改造前逐字一致——装俩又定位不到就罢工
        comp = self.make_component("tomcat", "10.1.60", "9.0.100")
        path, note = comp.resolve_uninstall_target("8.8.8")
        self.assertIsNone(path)
        self.assertIn("请先在下拉框中选择具体版本", note)


class StaleProbeWorkerGuard(EnvSandbox):
    """并入项 A（Task 8 评审留）：重跑 _detect_status 后旧探测线程的迟到回调作废。

    _on_version_probed 用 worker 身份（worker is self._version_worker）挡旧回包；
    多版本分支重新排探测时没把 _version_worker 清掉，上一轮卡片里遗留的旧 worker
    回来照样能贴上版本号——切完版本胶囊还挂着旧精确串，永久错标。
    夹具沿用 Task 8 的 _card 形状（下拉清单真实大版本串 + java 桩 + enable_detect）。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card_active21(self):
        comp = self.make_component("jdk", "21", "17")
        for v in ("21", "17"):
            (comp.install_dir(v) / "bin" / "java").write_text("", encoding="utf-8")
        self.as_windows()
        main.save_active_version("jdk", "21")
        self.enable_detect()
        # 同 Task 8：记录桩的 self 是卡片实例，把列表挂到类属性上让两边同一对象
        main.ComponentCard.probe_calls = self.probe_calls
        self.addCleanup(delattr, main.ComponentCard, "probe_calls")
        return main.ComponentCard(comp, lambda lvl, msg: None)

    def test_stale_probe_callback_cannot_backfill_after_redetect(self):
        # 红→绿必须真做：改造前 _detect_status 不清 _version_worker，哨兵存活，
        # _on_version_probed("21.0.4", 哨兵) 会通过身份闸门把旧版本号贴进新胶囊。
        card = self._card_active21()
        stale = object()
        card._version_worker = stale
        card._detect_status()
        card._on_version_probed("21.0.4", stale)
        self.assertNotIn("21.0.4", card.status_label.text(),
                         "旧轮次 worker 的回包不得再写进新一轮胶囊")

    def test_negative_control_fresh_backfill_still_lands(self):
        # 反向对照：胶囊回填链路本身是通的——worker=None 的常规回填照常进胶囊。
        # 没有这条对照，上一条的"绿"可能只是闸门整个关了，而不是修好了。
        card = self._card_active21()
        card._version_worker = object()
        card._detect_status()
        card._on_version_probed("21.0.4")
        self.assertIn("21.0.4", card.status_label.text())
        self.assertIn("已装 2 个版本", card.status_label.text())


class UninstallButtonGate(EnvSandbox):
    """并入项 B：多版本卡片里卸载按钮只对"已装的选中版本"启用。

    改造前 setEnabled(True) 是无条件的，而 tooltip 承诺"卸载下拉框选中的 {selected}"，
    selected 完全可能没装——点下去会走 resolve 兜底，删掉用户没选中的版本。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card(self):
        comp = self.make_component("jdk", "21", "17")
        for v in ("21", "17"):
            (comp.install_dir(v) / "bin" / "java").write_text("", encoding="utf-8")
        self.as_windows()
        main.save_active_version("jdk", "21")
        self.enable_detect()
        main.ComponentCard.probe_calls = self.probe_calls
        self.addCleanup(delattr, main.ComponentCard, "probe_calls")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        # 夹具自查（Task 7/8 同款护栏）："8" 是未装版本，必须在下拉清单里
        self.assertNotEqual(card.version_combo.findText("8"), -1)
        self.assertNotEqual(card.version_combo.findText("17"), -1)
        return card

    def _select(self, card, label):
        card.version_combo.setCurrentIndex(card.version_combo.findText(label))
        card._detect_status()

    def test_uninstall_enabled_for_installed_selection(self):
        # 对照组（改造前后都绿）：选中的版本已装 → 按钮可点，tooltip 承诺不变
        card = self._card()
        self._select(card, "17")
        self.assertTrue(card.btn_uninstall.isEnabled())
        self.assertIn("卸载下拉框选中的 17", card.btn_uninstall.toolTip())

    def test_uninstall_disabled_for_uninstalled_selection(self):
        # 改造前红：setEnabled(True) 无条件
        card = self._card()
        self._select(card, "8")
        self.assertFalse(card.btn_uninstall.isEnabled(),
                         "选中的 8 没装，卸载按钮不该可点")
        tip = card.btn_uninstall.toolTip()
        self.assertIn("未安装", tip)
        self.assertIn("绿勾", tip, "禁用 tooltip 要告诉用户怎么选中已装版本")


class UninstallHomeGuardFix3(EnvSandbox):
    """Task 9 修复轮 3（裁决见 task-9-fix-3.md）：N-1 重建只针对"我们自己的 HOME 漂移"、
    N-2 重建分支措辞分叉、N-3 infer_active_from_env 加目录存在性判据。

    夹具沿用 UninstallScope / UninstallActiveGuardFix2 的形状：as_windows + jdk
    21.0.4/17.0.12 + 两条版本 PATH 条目 + C:\\Windows\\system32 锚点。断言只看
    win_env / win_path / CONFIG_FILE / 摘要文本与 status_label.text()，绝不断言桩的调用次数。
    """

    def _seed_jdk(self, home=None, active="21.0.4", versions=("21.0.4", "17.0.12")):
        """装 versions 两个版本并各留一条 PATH 条目；home=None 表示根本不设 JAVA_HOME。

        active=None 时不写登记表（模拟只有 selections 的老 config.json）。
        """
        self.as_windows()
        comp = self.make_component("jdk", *versions)
        self.win_path[:] = [str(comp.install_dir(v) / "bin") for v in versions] \
                            + [r"C:\Windows\system32"]
        if home:
            self.win_env["JAVA_HOME"] = home
        else:
            # 宿主机可能自带 JAVA_HOME：第 2 步的 `read_user_env or get` 会兜底到
            # os.environ，把用户真机的值混进摘要。EnvSandbox 结束时会还原 ENV_KEYS，
            # 这里先弹出，保证"根本没设 JAVA_HOME"是干净的现场。
            os.environ.pop("JAVA_HOME", None)
        if active:
            main.save_active_version("jdk", active)
        else:
            main.CONFIG_FILE.write_text(
                json.dumps({"selections": {"jdk": "21.0.4"}}, ensure_ascii=False),
                encoding="utf-8")
        return comp

    # ---- N-1（Important）：用户自己的 HOME 指在我们根外时绝不覆盖 ----
    def test_n1_out_of_root_home_is_never_rebuilt(self):
        # 评审实测的复现现场：登记表 active=我们的 21.0.4，但 JAVA_HOME 是用户自己
        # 指到组件根之外的 JDK1.8。现网第 4 步只看"HOME 与 active 目录不同路径"就
        # 重建，把用户自己的入口覆盖成我们的 jdk-21.0.4，和第 2 步的"未删除"自相矛盾。
        # 红点：win_env["JAVA_HOME"] 变成了我们的 21.0.4 目录。
        foreign = r"C:\Program Files\Java\jdk1.8.0_202"
        comp = self._seed_jdk(home=foreign)
        summary = comp.uninstall("17.0.12")
        self.assertEqual(self.win_env.get("JAVA_HOME"), foreign,
                         "用户指到组件目录之外的 JAVA_HOME 绝不允许被卸载覆盖成我们的路径")
        self.assertNotIn("重建环境变量与 PATH", summary)
        self.assertNotIn("自动切到", summary)
        # 第 2 步的如实陈述不能被第 4 步反悔
        self.assertIn("指向其他目录", summary)
        self.assertEqual(main.load_active_map()["jdk"], "21.0.4")
        self.assertIn(str(comp.install_dir("21.0.4") / "bin"), self.win_path)
        self.assertIn(r"C:\Windows\system32", self.win_path)

    def test_n1b_missing_home_still_rebuilds_active(self):
        # N-1 必须保留 `not home_now` 那一支：登记表说 21 生效、HOME 却被第 2 步删了
        # （或根本没设），正是"我们自己的 HOME 被这次卸载带偏"，第 4 步仍要按 active 重建。
        comp = self._seed_jdk(home=None)
        summary = comp.uninstall("17.0.12")
        self.assertEqual(self.win_env.get("JAVA_HOME"), str(comp.install_dir("21.0.4")))
        self.assertIn("已按生效版本 21.0.4 重建环境变量与 PATH", summary)
        self.assertIn(str(comp.install_dir("21.0.4") / "bin"), self.win_path)
        self.assertIn(r"C:\Windows\system32", self.win_path)

    # ---- N-2（Minor）：target == active 是"重建"不是"切" ----
    def test_n2_rebuild_summary_does_not_say_switched(self):
        # 同一场景：active=21 本来就活着，"生效版本已自动切到 21.0.4"是假话——
        # 它没被切过。措辞要按 target 与 active 是否相同分叉。
        comp = self._seed_jdk(home=None)
        summary = comp.uninstall("17.0.12")
        self.assertNotIn("自动切到 21.0.4", summary)
        self.assertIn("已按生效版本 21.0.4 重建环境变量与 PATH", summary)

    def test_n2b_python_without_env_var_is_untouched(self):
        # python 是 7 个白名单里唯一 env_var=None 的（main.py:3020-3022）：
        # 没有 HOME 可被带偏，第 4 步既不该动 PATH 也不该在摘要里写"重建/自动切到"。
        self.as_windows()
        comp = self.make_component("python", "3.12.4", "3.11.9")
        self.win_path[:] = [str(comp.install_dir("3.12.4") / "Scripts"),
                            str(comp.install_dir("3.11.9") / "Scripts"),
                            r"C:\Windows\system32"]
        main.save_active_version("python", "3.12.4")
        summary = comp.uninstall("3.11.9")
        self.assertIn(str(comp.install_dir("3.12.4") / "Scripts"), self.win_path)
        self.assertNotIn(str(comp.install_dir("3.11.9") / "Scripts"), self.win_path)
        self.assertIn(r"C:\Windows\system32", self.win_path)
        self.assertNotIn("重建", summary)
        self.assertNotIn("自动切到", summary)
        self.assertEqual(main.load_active_map()["python"], "3.12.4")

    # ---- N-3（Minor）：infer_active_from_env 要校验目录真实存在 ----
    def test_n3_infer_rejects_dead_home(self):
        # 双写失败（目录删了、HOME 没清掉）后胶囊能一直显示"生效 11"而盘上已无 11。
        # 登记表为空 + JAVA_HOME 指我们根下不存在的 jdk-11 → 反推必须是 None，
        # 胶囊必须走"均未生效"。红点：infer 返回 '11'（现网只看值、不看目录）。
        comp = self._seed_jdk(home=None, active=None, versions=("21",))
        dead = str(comp.install_dir("11"))            # jdk-11 只造路径、从不造目录
        self.assertFalse(Path(dead).is_dir())
        self.win_env["JAVA_HOME"] = dead
        self.assertIsNone(main.infer_active_from_env(comp))
        self.enable_detect()
        main.ComponentCard.probe_calls = self.probe_calls   # 同 Task 8：记录桩的 self 是卡片实例
        self.addCleanup(delattr, main.ComponentCard, "probe_calls")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        self.assertIsNone(card.active_version())
        self.assertIn("均未生效", card.status_label.text())
        self.assertNotIn("生效 11", card.status_label.text())


class UninstallRepointHomeGuardF12(EnvSandbox):
    """F12（最终加固轮，Important）：删掉的正是生效版本时，自动重排前先看 HOME 的位置。

    现网第 4 步的 `elif active and removed_ver == active:` 一支没有 HOME 守卫：
    JAVA_HOME 是组件根之外、用户自己的安装（IDE/系统装指过去）时，
    apply_active_version 会把用户的入口无条件覆成我们的目录——违反绑定约束
    「用户自己的条目一律不动」，也推翻第 2 步刚说过的"未删除"。
    判据用 HOME 的**位置**（与修复轮 3 的重建分支一致，位置才解释得了"谁写的"）：
      · 落在组件根内 / 已被第 2 步删掉 / 没设 → 这是我们写的（或老配置反推的），
        照旧自动重排——修复轮 2 的 I-1 必须保住；
      · 落在组件根外 → 用户自己的选择，只提示，不写回。
    """

    def setUp(self):
        super().setUp()
        self.as_windows()
        self.comp = self.make_component("jdk", "21.0.4", "17.0.12")
        self.win_path[:] = [str(self.comp.install_dir("21.0.4") / "bin"),
                            r"C:\Windows\system32"]

    def test_external_home_is_hinted_not_overwritten_when_active_removed(self):
        # 评审给的 6 行真值表缺的那一行：登记表 active=21.0.4，JAVA_HOME 是根外的
        # 用户 JDK。卸载生效的 21.0.4 → 修复前红：JAVA_HOME 被覆成我们的
        # jdk-17.0.12 目录，摘要写"生效版本已自动切到 17.0.12"。
        foreign = r"C:\Program Files\Java\jdk1.8.0_202"
        self.win_env["JAVA_HOME"] = foreign
        main.save_active_version("jdk", "21.0.4")
        summary = self.comp.uninstall("21.0.4")
        self.assertEqual(self.win_env.get("JAVA_HOME"), foreign,
                         "用户指到组件根外的 JAVA_HOME 不得被卸载的自动重排覆成我们的目录")
        self.assertIn("仅配置环境变量", summary, "不出手可以，但要在摘要里提示用户怎么重设")
        self.assertNotIn("已自动切到", summary)
        self.assertEqual(main.load_active_map().get("jdk"), "21.0.4",
                         "不重排就不写 active：留旧登记交给用户点按钮收尾")
        self.assertIn(r"C:\Windows\system32", self.win_path)

    def test_in_root_legacy_home_still_repoints_when_active_removed(self):
        # 反向用例（护 I-1，别把 F12 修成"老用户卸载生效版本后什么都不做"）：
        # 登记表为空的旧配置，JAVA_HOME 落在我们根内、正指着被删的 21.0.4，
        # 第 2 步把 HOME 删掉后第 4 步仍必须自动重排到剩余最高的 17.0.12。
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("21.0.4"))
        main.CONFIG_FILE.write_text(
            json.dumps({"selections": {"jdk": "21.0.4"}}, ensure_ascii=False),
            encoding="utf-8")
        self.assertNotIn("jdk", main.load_active_map())     # 夹具自查：登记表为空
        summary = self.comp.uninstall("21.0.4")
        self.assertEqual(self.win_env.get("JAVA_HOME"), str(self.comp.install_dir("17.0.12")))
        self.assertEqual(main.load_active_map().get("jdk"), "17.0.12")
        self.assertIn("生效版本已自动切到 17.0.12", summary)


class UninstallConfirmText(EnvSandbox):
    """并入项 C：卸载确认框尾巴按 multi_version 分叉。

    非多版本组件的原文必须逐字不变；多版本组件现在只动选中的那个版本，
    旧句子「若所选版本与实际安装版本不一致，会以实际装着的目录为准」会变成假话。
    整块替换 main.QMessageBox（不弹真框），断言只看用户能看到的文本本身。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    NON_MV_TAIL = "（若所选版本与实际安装版本不一致，会以实际装着的目录为准）"

    def _capture_question(self):
        captured = {}

        class FakeBox:
            Yes = 1
            No = 2

            @staticmethod
            def question(parent, title, text, *a, **k):
                captured["text"] = text
                return FakeBox.No   # 一律答"否"：确认框文案用例不许真的卸载

        orig = main.QMessageBox
        main.QMessageBox = FakeBox
        self.addCleanup(setattr, main, "QMessageBox", orig)
        return captured

    def test_multiversion_confirm_text_scopes_to_selected_version(self):
        self.as_windows()
        comp = self.make_component("jdk", "21", "17")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        card.version_combo.setCurrentIndex(card.version_combo.findText("17"))
        captured = self._capture_question()
        card.on_uninstall_clicked()
        text = captured["text"]
        self.assertIn("只删除选中的这一个版本", text)
        self.assertIn("其他已装版本不动", text)
        self.assertIn("自动切到剩余里版本号最高的", text)
        self.assertNotIn("以实际装着的目录为准", text, "多版本组件这句话现在是假话")
        # 用户点了"否"：磁盘上什么都不许被删
        self.assertTrue(comp.install_dir("17").is_dir())
        self.assertTrue(comp.install_dir("21").is_dir())

    def test_non_multiversion_confirm_text_byte_identical(self):
        self.as_windows()
        comp = self.make_component("tomcat", "10.1.60")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        captured = self._capture_question()
        card.on_uninstall_clicked()
        self.assertIn(self.NON_MV_TAIL, captured["text"])


class MultiVersionBadge(EnvSandbox):
    """卡片标题后的「可多版本」角标：让 7 个支持多版本的组件在**一个版本都没装时**也认得出来。

    两条硬要求：
      · 非多版本组件不创建这个 QLabel（不是隐藏），那 19 张卡片与改造前逐字一致；
      · 角标是独立节点，绝不拼进标题文本或组件名 —— display_name 是搜索匹配
        （component_matches_query）与日志前缀（ComponentCard._log）的共用真源。
    """

    BADGE_TEXT = "可多版本"
    MV_KEYS = ("jdk", "python", "node", "go", "maven", "gradle", "bun")

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card(self, key):
        comp = self.make_component(key, "1.2.3")
        return main.ComponentCard(comp, lambda lvl, msg: None)

    def _badges(self, card):
        from PySide6.QtWidgets import QLabel
        return [w for w in card.findChildren(QLabel)
                if w.objectName() == "multiVersionBadge"]

    def test_badge_on_every_multi_version_card(self):
        self.as_windows()
        for key in self.MV_KEYS:
            with self.subTest(key=key):
                card = self._card(key)
                badges = self._badges(card)
                self.assertEqual(len(badges), 1)
                self.assertEqual(badges[0].text(), self.BADGE_TEXT)
                self.assertTrue(badges[0].toolTip().strip(), "角标必须有悬停说明")
                self.assertIn("生效", badges[0].toolTip())

    def test_no_badge_widget_on_other_components(self):
        self.as_windows()
        others = [c.key for c in main.build_components() if not c.multi_version]
        self.assertTrue(others)
        for key in others:
            with self.subTest(key=key):
                card = self._card(key)
                self.assertEqual(self._badges(card), [],
                                 "非多版本组件不该创建角标节点（不是创建后隐藏）")

    def test_title_text_stays_exactly_display_name(self):
        self.as_windows()
        from PySide6.QtWidgets import QLabel
        for key in ("jdk", "tomcat"):
            comp = next(c for c in main.build_components() if c.key == key)
            card = self._card(key)
            titles = [w.text() for w in card.findChildren(QLabel)
                      if w.objectName() == "cardTitle"]
            self.assertEqual(titles, [comp.display_name],
                              "角标必须是独立 QLabel，不许拼进标题文本")

    def test_badge_text_is_not_searchable(self):
        """角标只是装饰：搜「可多版本」不该命中任何组件。"""
        self.as_windows()
        comp = next(c for c in main.build_components() if c.key == "jdk")
        self.assertFalse(main.component_matches(comp, self.BADGE_TEXT))


class RealMachineRegressions(EnvSandbox):
    """2026-09-30 用户真机反馈的两个问题的回归护栏。

    ① 装了 bun 1.4.2 + 1.4.1：安装收尾对每个版本各追加一条 PATH，两条都在 PATH 里，
       命令行按顺序命中 1.4.2，而 BUN_HOME 指 1.4.1 —— 胶囊说"生效 1.4.1"是假的。
    ② 用户自己装的 JDK / Maven：_detect_status 的多版本分支在"本工具目录下一个都没有"时
       直接 return「○ 未安装」，压根没调 detect() —— 7 个白名单组件丢了"系统里已装"的识别。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card(self, key="jdk", versions=("21", "17")):
        comp = self.make_component(key, *versions)
        for v in versions:
            (comp.install_dir(v) / "bin" / "java.exe").write_bytes(b"\x00")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        self.enable_detect()
        card._detect_status()
        return card

    # ---- ① 安装收尾必须收敛，不能每装一个版本就多一条 PATH ----
    def test_second_install_collapses_path_and_registers_active(self):
        self.as_windows()
        comp = self.make_component("jdk", "21", "17")
        for v in ("21", "17"):
            (comp.install_dir(v) / "bin" / "java.exe").write_bytes(b"\x00")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        # 先让 17 生效，再装 21：装完之后 PATH 里只该有 21 这一条
        card._apply_active("17")
        card._configure_after_extract(comp.install_dir("21"))
        mine = [p for p in self.win_path if "jdk" in p.lower()]
        self.assertEqual(mine, [str(comp.install_dir("21") / "bin")],
                         "安装收尾必须把本组件的 PATH 条目收敛成新版本这一条")
        self.assertEqual(main.load_active_map().get("jdk"), "21")
        self.assertEqual(self.win_env["JAVA_HOME"], str(comp.install_dir("21")))

    def test_non_multi_version_install_still_appends(self):
        """非多版本组件的安装路径不许被顺手改掉。"""
        self.as_windows()
        comp = self.make_component("tomcat", "10.1.60")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        card._configure_after_extract(comp.install_dir("10.1.60"))
        self.assertEqual(self.win_env["CATALINA_HOME"], str(comp.install_dir("10.1.60")))
        self.assertIn(str(comp.install_dir("10.1.60") / "bin"), self.win_path)
        self.assertNotIn("tomcat", main.load_active_map())

    # ---- ① 的显示面：HOME 与 PATH 命中不一致时不许只报一个 ----
    def test_home_and_path_mismatch_is_disclosed_not_hidden(self):
        self.as_windows()
        comp = self.make_component("jdk", "21", "17")
        for v in ("21", "17"):
            (comp.install_dir(v) / "bin" / "java.exe").write_bytes(b"\x00")
        # 老配置：登记表为空，JAVA_HOME 指 17，但 PATH 里 21 排在前面
        self.win_env["JAVA_HOME"] = str(comp.install_dir("17"))
        self.win_path[:] = [str(comp.install_dir("21") / "bin"),
                            str(comp.install_dir("17") / "bin")]
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        self.enable_detect()
        card._detect_status()
        text = card.status_label.text()
        print("不一致胶囊:", text)
        self.assertIn("未对齐", text)
        self.assertIn("21", text)
        self.assertIn("17", text)
        self.assertNotIn("● 已装 2 个版本 · 生效 17（21、17）", text,
                         "不能再只报 HOME 里那个版本当作生效版本")
        self.assertIn("#ef6c00", card.status_label.styleSheet(), "不一致必须是橙色告警态")
        self.assertTrue(card.btn_configure.isEnabled(),
                        "不一致时切换按钮必须可用，让用户能自己校正")

    # ---- ② 我们一个都没装时，回落到 detect 认系统里的安装 ----
    def test_external_install_is_detected_when_we_have_none(self):
        self.as_windows()
        external = main.CONFIG_DIR.parent / "own-jdk"
        (external / "bin").mkdir(parents=True, exist_ok=True)
        (external / "bin" / "java.exe").write_bytes(b"\x00")
        self.win_env["JAVA_HOME"] = str(external)
        comp = next(c for c in main.build_components() if c.key == "jdk")
        self.assertEqual(comp.installed_dirs(), [], "本工具目录下必须一个都没有")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        self.enable_detect()
        card._detect_status()
        text = card.status_label.text()
        print("外部安装胶囊:", text)
        self.assertIn("已配置", text)
        self.assertIn("JAVA_HOME", text)
        self.assertIn("系统", text, "要说清这是系统里的安装，不是本工具装的")
        self.assertNotIn("未安装", text)
        # 本工具没装过 = 没有可卸的东西，按钮不许给出做不到的承诺
        self.assertFalse(card.btn_uninstall.isEnabled())
        self.assertIn("你自己装的", card.btn_uninstall.toolTip())

    def test_non_multi_version_external_detection_text_unchanged(self):
        """非多版本组件的这条回落文案逐字不变。"""
        self.as_windows()
        external = main.CONFIG_DIR.parent / "own-tomcat"
        (external / "bin").mkdir(parents=True, exist_ok=True)
        (external / "bin" / "catalina.bat").write_bytes(b"@echo off\r\n")
        self.win_env["CATALINA_HOME"] = str(external)
        comp = next(c for c in main.build_components() if c.key == "tomcat")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        self.enable_detect()
        card._detect_status()
        # tomcat 的 version_probe 为真，异步版本号还没回来时旧文案就带这个尾巴，
        # 逐字照抄改造前的产物 —— 这条断言的意义就是"非多版本一个字符都没变"
        self.assertEqual(card.status_label.text(), "✓ 已配置（CATALINA_HOME） · 版本检测中…")
        self.assertTrue(card.btn_uninstall.isEnabled())
        self.assertEqual(card.btn_uninstall.toolTip(),
                         "卸载将删除本地安装目录，并清理由本工具写入的环境变量")

    # ---- ① 的操作面：多版本组件的按钮要叫「切换为生效版本」----
    def test_switch_button_label_only_for_multi_version(self):
        self.as_windows()
        mv = self._card("jdk")
        self.assertEqual(mv.btn_configure.text(), "切换为生效版本")
        comp = self.make_component("tomcat", "10.1.60")
        ordinary = main.ComponentCard(comp, lambda lvl, msg: None)
        self.assertEqual(ordinary.btn_configure.text(), "配置环境变量")


class SwitchVerification(EnvSandbox):
    """切换生效版本后必须复验"新终端到底会用到谁"，不许报了成功实际没生效。

    实测依据（2026-09-30 真机）：系统 PATH 里的 %JAVA_HOME%\\bin 在合并用户变量之前
    就按系统表展开定死了，而用户 PATH 整体排在系统之后 —— 于是本工具把
    JAVA_HOME 改对、把自己的 bin 写进用户 PATH 之后，命令行仍会命中系统那个 JDK。
    复验走 CreateEnvironmentBlock 拿"系统为新进程合成的环境"。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.as_windows()
        self.logs = []
        self.comp = self.make_component("jdk", "21", "17")
        for v in ("21", "17"):
            (self.comp.install_dir(v) / "bin" / "java.exe").write_bytes(b"\x00")
        # 模拟"用户自己装的、排在 PATH 更前面的那份"。必须落在沙箱里：
        # 拿真实机器上的 JDK 目录当夹具会往用户安装里写文件。
        self.FOREIGN = str(self.root / "own-jdk" / "bin")
        main.Path(self.FOREIGN).mkdir(parents=True, exist_ok=True)
        (main.Path(self.FOREIGN) / "java.exe").write_bytes(b"\x00")
        self.card = main.ComponentCard(self.comp, lambda lvl, msg: self.logs.append((lvl, msg)))
        # 不调 enable_detect 的话 _detect_status 还是沙箱默认的 no-op，
        # 胶囊永远是初始的"检测中…"，那两条 assertNotIn 就成了假绿
        self.enable_detect()

    def _stub_composed(self, path_value):
        """把"系统合成后的环境"打桩成可控值（复验唯一依赖的外部事实）。"""
        orig = main.EnvManager.composed_env
        main.EnvManager.composed_env = staticmethod(
            lambda: ({"PATH": path_value, "JAVA_HOME": ""} if path_value is not None else {}))
        self.addCleanup(setattr, main.EnvManager, "composed_env", orig)

    def _warns(self):
        return [m for lvl, m in self.logs if lvl in ("warn", "error")]

    def test_switch_logs_success_when_our_entry_wins(self):
        mine = str(self.comp.install_dir("17") / "bin")
        self._stub_composed(mine + ";" + self.FOREIGN)
        self.assertTrue(self.card._apply_active("17"))
        joined = " | ".join(m for _l, m in self.logs)
        self.assertIn("复验通过", joined)
        self.assertEqual(self._warns(), [], f"不该有告警：{self._warns()}")
        self.card._detect_status()
        self.assertNotIn("先命中", self.card.status_label.text())

    def test_shadowed_by_foreign_path_entry_is_reported_not_success(self):
        self._stub_composed(self.FOREIGN + ";" + str(self.comp.install_dir("17") / "bin"))
        self.card._apply_active("17")
        joined = " | ".join(m for _l, m in self.logs)
        self.assertNotIn("复验通过", joined)
        self.assertTrue(any("复验" in m for m in self._warns()),
                        f"必须有一条复验告警，实际日志：{joined}")
        self.assertIn(self.FOREIGN, joined, "告警要点名是谁把命令抢走的")
        self.card._detect_status()
        text = self.card.status_label.text()
        self.assertIn("先命中", text, "胶囊要常驻显示这个不一致，不能只闪一行日志")
        self.assertIn("#ef6c00", self.card.status_label.styleSheet())

    def test_unverifiable_is_admitted_not_assumed_ok(self):
        """拿不到合成环境（非 Windows / API 失败）时不许说"复验通过"。"""
        self._stub_composed(None)
        self.card._apply_active("17")
        joined = " | ".join(m for _l, m in self.logs)
        self.assertNotIn("复验通过", joined)
        self.assertTrue(any("未能复验" in m for m in self._warns()), joined)
        # 也无法判定遮蔽 → 胶囊保持正常绿色，不制造假告警
        self.card._detect_status()
        self.assertNotIn("先命中", self.card.status_label.text())

    # ---- 切换成功后必须给出"怎么自己校验"的可复制指引 ----
    def test_success_logs_copy_ready_verification_hint(self):
        """用户按字面"重开终端"却只开了个新标签页 → 仍看到旧版本。必须写清怎么验。"""
        mine = str(self.comp.install_dir("17") / "bin")
        self._stub_composed(mine + ";" + self.FOREIGN)
        self.card._apply_active("17")
        joined = " | ".join(m for _l, m in self.logs)
        self.assertIn("where java", joined, "要给可直接粘贴的校验命令")
        self.assertIn("GetEnvironmentVariable", joined,
                      "要给不想重开时的当前会话刷新命令")
        self.assertIn("关掉重开", joined, "必须点破：新标签页/IDE 内终端不算新终端")

    def test_unknown_verdict_still_gives_the_hint(self):
        """没能复验时更要把校验方法交给用户。"""
        self._stub_composed(None)
        self.card._apply_active("17")
        joined = " | ".join(m for _l, m in self.logs)
        self.assertIn("where java", joined)
        self.assertIn("关掉重开", joined)

    def test_shadowed_case_does_not_blame_the_terminal(self):
        """被系统级 PATH 压住时，问题不在旧终端，不许塞"重开终端"指引误导用户。"""
        self._stub_composed(self.FOREIGN + ";" + str(self.comp.install_dir("17") / "bin"))
        self.card._apply_active("17")
        joined = " | ".join(m for _l, m in self.logs)
        self.assertIn("系统", joined, "要说明是系统级条目抢在前面")
        self.assertNotIn("GetEnvironmentVariable", joined)


class SelectionReenablesSwitch(EnvSandbox):
    """改下拉框选中必须让「切换为生效版本」重新可点。

    2026-09-30 真机反馈：切一次之后按钮变灰，换选另一个版本仍然灰、无法再切。
    根因是启用判定只写在 _detect_status 里，而卡片从没连接下拉框的变更信号。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.as_windows()
        self.comp = self.make_component("jdk", "21", "17", "11")
        for v in ("21", "17", "11"):
            (self.comp.install_dir(v) / "bin" / "java.exe").write_bytes(b"\x00")
        self.card = main.ComponentCard(self.comp, lambda lvl, msg: None)
        self.enable_detect()
        self.card._detect_status()

    def _select(self, version):
        idx = self.card.version_combo.findText(version)
        self.assertGreaterEqual(idx, 0, f"下拉框里没有 {version}")
        self.card.version_combo.setCurrentIndex(idx)
        self.card._detect_status()   # 显式重算一次，证明"重算后确实该亮"

    def test_selection_change_reenables_switch_button(self):
        # 先把 17 设为生效：此时若仍选中 17，按钮该灰
        self._select("17")
        self.assertTrue(self.card._apply_active("17"))
        self.assertFalse(self.card.btn_configure.isEnabled(),
                         "选中的就是生效版本时该禁用")
        # 只改选中，不做任何其它操作 —— 按钮必须自己亮回来
        idx = self.card.version_combo.findText("21")
        self.card.version_combo.setCurrentIndex(idx)
        self.assertEqual(self.card.version_combo.currentText(), "21")
        self.assertTrue(self.card.btn_configure.isEnabled(),
                        "换选成 21 后必须能再次切换（当前仍灰 = 回归）")

    def test_selection_change_also_reenables_uninstall(self):
        self._select("11")
        self.assertTrue(self.card.btn_uninstall.isEnabled())
        idx = self.card.version_combo.findText("8")     # 8 没装
        self.card.version_combo.setCurrentIndex(idx)
        self.assertFalse(self.card.btn_uninstall.isEnabled(),
                         "换选成没装的版本后卸载该禁用")

    def test_switch_button_state_survives_repeated_selection(self):
        # 反复在两个已装版本之间挑，状态必须跟着走，不能卡在第一次的结果
        self._select("21")
        self.assertTrue(self.card._apply_active("21"))
        for version, expect in (("17", True), ("21", False), ("11", True)):
            with self.subTest(version=version):
                self.card.version_combo.setCurrentIndex(
                    self.card.version_combo.findText(version))
                self.assertEqual(self.card.btn_configure.isEnabled(), expect)


class InstallButtonBlockedWhenInstalled(EnvSandbox):
    """选中的版本磁盘上已经装好 → 「下载并安装」置灰，避免重复下载并静默覆盖。

    规则（2026-09-30 与用户确认）：全部 26 个组件都管；已装时只灰不改名，
    tooltip 指路「要重装先卸载」。目录在但里面找不到可执行文件的不算已装 ——
    否则半截安装会把按钮灰掉、卸载又无事可做，用户就被困死了。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card_with_install(self, key, version="1.2.3", *, with_exe=True):
        # 沙箱默认把 _detect_status 换成 no-op；本类要跑真实探测路径，必须放开，
        # 否则只有"换选中触发信号"的用例会同步按钮，其余用例是假绿/假红。
        self.enable_detect()
        main.ComponentCard.probe_calls = []
        comp = next(c for c in main.build_components() if c.key == key)
        home = comp.install_dir(version)
        (home / "bin").mkdir(parents=True, exist_ok=True)
        if with_exe:
            name = comp.exec_name or f"{key}.war"
            target = home / "bin" if comp.exec_name else home
            target.mkdir(parents=True, exist_ok=True)
            (target / name).write_bytes(b"\x00")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        card._reload_combo_items(preferred=version)
        card._detect_status()
        return card, comp


    def test_installed_version_greys_out_install_button(self):
        self.as_windows()
        card, comp = self._card_with_install("jdk", "21")
        idx = card.version_combo.findText("21")
        self.assertGreaterEqual(idx, 0)
        card.version_combo.setCurrentIndex(idx)
        card._detect_status()
        self.assertFalse(card.btn_install.isEnabled(), "已装的 21 不该再点下载并安装")
        self.assertIn("卸载", card.btn_install.toolTip(), "必须告诉用户想重装先卸载")
        self.assertIn(str(comp.install_dir("21")), card.btn_install.toolTip(),
                      "tooltip 要带上装在哪，便于用户核对")

    def test_uninstalled_version_stays_clickable(self):
        self.as_windows()
        card, _comp = self._card_with_install("jdk", "21")
        idx = card.version_combo.findText("8")
        card.version_combo.setCurrentIndex(idx)
        self.assertTrue(card.btn_install.isEnabled(), "换选成没装的 8 必须能点")

    def test_half_installed_dir_is_not_treated_as_installed(self):
        """目录在、里面没有可执行文件 → 不算已装，不许把用户困住。"""
        self.as_windows()
        card, _comp = self._card_with_install("jdk", "21", with_exe=False)
        idx = card.version_combo.findText("21")
        card.version_combo.setCurrentIndex(idx)
        card._detect_status()
        self.assertTrue(card.btn_install.isEnabled(),
                        "空目录/半截安装不该灰掉安装按钮")

    def test_every_component_respects_the_rule(self):
        """26 个组件逐个走一遍：装了就该灰，且换选未装版本能亮回来。"""
        self.as_windows()
        self.enable_detect()
        main.ComponentCard.probe_calls = []
        checked = 0
        for comp in main.build_components():
            version = comp.versions[0].version
            card = main.ComponentCard(comp, lambda lvl, msg: None)
            home = comp.install_dir(version)
            (home / "bin").mkdir(parents=True, exist_ok=True)
            name = comp.exec_name or f"{comp.key}.war"
            target = home / "bin" if comp.exec_name else home
            target.mkdir(parents=True, exist_ok=True)
            (target / name).write_bytes(b"\x00")
            card._reload_combo_items(preferred=version)
            card._detect_status()
            with self.subTest(key=comp.key):
                self.assertFalse(card.btn_install.isEnabled(),
                                 f"{comp.key} 已装 {version} 时安装按钮必须置灰")
            checked += 1
        self.assertEqual(checked, len(main.build_components()))

    def test_download_in_progress_is_never_re_enabled(self):
        """下载途中换选中，不许把按钮点亮。"""
        self.as_windows()
        card, _comp = self._card_with_install("tomcat", "10.1.60")

        class FakeWorker:
            def isRunning(self):
                return True

        card.worker = FakeWorker()
        card.btn_install.setEnabled(False)
        card._sync_action_buttons()
        self.assertFalse(card.btn_install.isEnabled(),
                         "下载进行中必须保持禁用，否则能并发触发第二次下载")

    def test_uninstall_reenables_install_button(self):
        self.as_windows()
        import shutil
        card, comp = self._card_with_install("jdk", "21")
        self.assertFalse(card.btn_install.isEnabled())
        shutil.rmtree(comp.install_dir("21"))
        card._detect_status()
        self.assertTrue(card.btn_install.isEnabled(), "卸掉之后必须能重新安装")


class InstalledVersionNotInCatalog(EnvSandbox):
    """磁盘上装着、但在线清单里已经没有的版本，必须出现在下拉框里。

    2026-09-30 真机：bun 装着 1.4.1 与 1.4.2，在线清单只剩 1.4.2/1.3.14/1.2.16/1.1.0，
    于是胶囊写着"已装 2 个版本（1.4.2、1.4.1）"，下拉框里却根本没有 1.4.1 ——
    那个版本切不了、卸不掉，用户反复点「切换」只能在别的版本之间打转。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _bun_card(self, *installed):
        comp = self.make_component("bun", *installed)
        for v in installed:
            (comp.install_dir(v) / "bun.exe").write_bytes(b"\x00")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        self.enable_detect()
        main.ComponentCard.probe_calls = []
        card._detect_status()
        return card, comp

    def _items(self, card):
        return [card.version_combo.itemText(i) for i in range(card.version_combo.count())]

    def test_installed_extras_are_listed_in_semver_order_with_mark(self):
        self.as_windows()
        card, comp = self._bun_card("1.4.1")
        items = self._items(card)
        catalog = [v.version for v in comp.versions]
        self.assertNotIn("1.4.1", catalog, "这条用例的前提就是清单里没有 1.4.1")
        self.assertIn("1.4.1", items, "磁盘装着的版本必须能选")
        self.assertEqual(items[:3], [catalog[0], "1.4.1", catalog[1]],
                         f"要按语义版本插在正确位置，实际 {items}")
        from PySide6.QtCore import Qt
        idx = card.version_combo.findText("1.4.1")
        data = card.version_combo.itemData(idx, Qt.DecorationRole)
        self.assertTrue(data and not data.isNull(), "合成项同样要挂绿勾")

    def test_extras_are_selectable_and_switchable(self):
        self.as_windows()
        card, comp = self._bun_card("1.4.1")
        card.version_combo.setCurrentIndex(card.version_combo.findText("1.4.1"))
        self.assertEqual(card._current_version().version, "1.4.1",
                         "反查必须落到合成项，不能悄悄回落到第一项")
        self.assertTrue(card.btn_configure.isEnabled())
        self.assertTrue(card._apply_active("1.4.1"))
        self.assertEqual(main.load_active_map().get("bun"), "1.4.1")
        self.assertEqual([p for p in self.win_path if "bun" in p.lower()],
                         [str(comp.install_dir("1.4.1"))])

    def test_extras_are_uninstallable_and_disappear_afterwards(self):
        self.as_windows()
        import shutil
        card, comp = self._bun_card("1.4.1")
        card.version_combo.setCurrentIndex(card.version_combo.findText("1.4.1"))
        self.assertTrue(card.btn_uninstall.isEnabled(), "选中的是已装版本，卸载该可用")
        shutil.rmtree(comp.install_dir("1.4.1"))
        card._refresh_installed_marks()
        card._detect_status()
        self.assertNotIn("1.4.1", self._items(card), "目录没了，这一项也该从下拉框消失")

    def test_online_refresh_keeps_installed_extras(self):
        self.as_windows()
        card, comp = self._bun_card("1.4.1")
        fresh = [main.ComponentVersion(version=v, url_map={}) for v in ("1.5.0", "1.4.2")]
        card.set_versions(fresh)
        items = self._items(card)
        self.assertIn("1.5.0", items)
        self.assertIn("1.4.1", items, "在线刷新不许把磁盘上已装、清单里没有的版本冲掉")
        self.assertEqual(items[0], "1.5.0")

    def test_extra_item_cannot_be_installed_but_does_not_crash(self):
        self.as_windows()
        card, _comp = self._bun_card("1.4.1")
        card.version_combo.setCurrentIndex(card.version_combo.findText("1.4.1"))
        card._sync_action_buttons()
        self.assertFalse(card.btn_install.isEnabled(), "已装的版本不该再点下载并安装")
        # 万一有别的入口调到安装：没有 URL 时只能友好报错，不许抛异常
        card.on_install_clicked()

    def test_no_duplicates_when_catalog_already_lists_it(self):
        self.as_windows()
        card, comp = self._bun_card("1.4.2")
        items = self._items(card)
        self.assertEqual(len(items), len(set(items)), f"不该出现重复条目：{items}")
        self.assertEqual(items, [v.version for v in comp.versions],
                         "清单里本来就有的版本，顺序与内容都不该变")

    def test_synthesised_entries_only_come_from_disk_not_invented(self):
        """合成项只允许来自**磁盘上真装了**的版本，不许凭空造。

        本测试类的主旨（见类 docstring）就是"磁盘上装着但清单里没有的版本必须出现在
        下拉框里"。原先末尾还有一条 `test_non_multi_version_components_are_not_synthesised`
        断言非多版本组件压根不合成 —— 那是用"实现手段"（`if not multi_version: return`）
        表达"不许凭空造版本"，两者被绑在了一起。

        2026-10-06 放开后，jenkins 候选是 2.568.3 而实装 2.580.1：不合成的话那个已装版本
        在下拉框里根本不存在，用户看到的是"装了东西但列表里没有它、也没有绿勾"，
        而启动走 `resolve_launch_version()` 找的是另一个版本，两边对不上。

        现在这条用例把两半都守住：
        ① 已装但不在候选里的 → **必须**出现在下拉框（R3.9 真正的目的没丢）；
        ② 只声明、磁盘上没装的 → **不许**出现（"不许凭空造"这半个约束也没丢）。
        """
        self.as_windows()
        # 候选清单里只有 9.9.9，磁盘上什么都没有 → 下拉框就只有 9.9.9，不许多出别的
        comp = self.make_component("tomcat")   # 不传版本 = 先造出空的候选清单
        comp.versions = [main.ComponentVersion(version="9.9.9", url_map={}, archive_map={})]
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        self.enable_detect()
        main.ComponentCard.probe_calls = []
        card._detect_status()
        self.assertEqual(self._items(card), ["9.9.9"],
                         "候选清单里有、磁盘上没装的版本照常显示，但不许凭空多出别的")

        # 磁盘上装了一个候选清单里没有的 8.0.28 → 必须被合成进下拉框（否则无处标绿勾）
        (comp.install_dir("8.0.28") / "bin").mkdir(parents=True, exist_ok=True)
        card2 = main.ComponentCard(comp, lambda lvl, msg: None)
        self.enable_detect()
        main.ComponentCard.probe_calls = []
        card2._detect_status()
        self.assertIn("8.0.28", self._items(card2),
                      "磁盘上装了的版本必须出现在下拉框里，否则无处标绿勾")


class StaleTerminalNotice(EnvSandbox):
    """切换成功后必须点名"比这次切换更早、还活着的终端窗口"。

    真机依据（2026-09-30）：用户报"重开终端了还是旧版本"，实测注册表与新进程都是
    新版本（由 explorer 现场启动的探针 `bun -v` → 1.4.1），屏幕上那个 PowerShell
    进程创建于切换之前 12 分钟。"重开标签页"不产生新进程，光讲道理没用，得把
    pid 与起始时间摆出来让用户能核对。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.as_windows()
        self.logs = []
        self.comp = self.make_component("jdk", "21", "17")
        for v in ("21", "17"):
            (self.comp.install_dir(v) / "bin" / "java.exe").write_bytes(b"\x00")
        self.card = main.ComponentCard(self.comp, lambda lvl, msg: self.logs.append((lvl, msg)))
        self.enable_detect()
        mine = str(self.comp.install_dir("17") / "bin")
        orig = main.EnvManager.composed_env
        main.EnvManager.composed_env = staticmethod(lambda: {"PATH": mine, "JAVA_HOME": ""})
        self.addCleanup(setattr, main.EnvManager, "composed_env", orig)

    def _stub_scan(self, procs):
        orig = main.list_shell_processes
        main.list_shell_processes = lambda: procs
        self.addCleanup(setattr, main, "list_shell_processes", orig)

    # ---- 纯格式化：谁该被点名 ----

    def test_only_shells_older_than_the_switch_are_listed(self):
        procs = [(111, "powershell.exe", 1000.0, True),   # 早于切换 → 该点名
                 (222, "cmd.exe", 2000.0, True)]          # 晚于切换 → 环境是新的，不许点名
        lines = main.stale_shell_lines(procs, since_epoch=1500.0, self_pid=999)
        joined = "\n".join(lines)
        self.assertIn("111", joined)
        self.assertNotIn("222", joined, "比切换更晚的进程本来就是新环境，点名是误导")

    def test_admin_window_is_called_out_as_unreachable(self):
        # openable=False 实测就是 OpenProcess 返回 error 5 —— 管理员窗口的特征
        lines = main.stale_shell_lines([(333, "powershell.exe", 1000.0, False)],
                                       since_epoch=1500.0, self_pid=999)
        self.assertIn("管理员", "\n".join(lines))

    def test_our_own_process_is_not_listed(self):
        lines = main.stale_shell_lines([(999, "cmd.exe", 1000.0, True)],
                                       since_epoch=1500.0, self_pid=999)
        self.assertEqual([x for x in lines if "999" in x], [],
                         "把工具自己写进「还开着的旧终端」里，用户会去关错窗口")

    def test_list_is_capped(self):
        procs = [(1000 + i, "cmd.exe", 1000.0 - i, True) for i in range(20)]
        lines = main.stale_shell_lines(procs, since_epoch=9000.0, self_pid=999)
        self.assertLessEqual(len([x for x in lines if re.search(r"pid=\d+", x)]), 6,
                             "刷屏式列举等于没列举")

    # ---- 接线：切换成功后要真的把这些行写进日志 ----

    def test_switch_log_names_the_stale_windows(self):
        self._stub_scan([(7984, "powershell.exe", time.time() - 3600, False)])
        self.assertTrue(self.card._apply_active("17"))
        joined = " | ".join(m for _l, m in self.logs)
        self.assertIn("7984", joined, "日志要点名旧终端的 pid，否则用户不知道该关哪个")
        self.assertIn("比这次切换更早", joined)

    def test_no_stale_window_adds_no_such_line(self):
        self._stub_scan([])
        self.card._apply_active("17")
        joined = " | ".join(m for _l, m in self.logs)
        self.assertNotIn("比这次切换更早", joined,
                         "没有旧终端却报这一行，是在制造假问题")

    def test_scan_failure_never_breaks_the_switch(self):
        orig = main.list_shell_processes
        def boom():
            raise OSError("Toolhelp 挂了")
        main.list_shell_processes = boom
        self.addCleanup(setattr, main, "list_shell_processes", orig)
        self.assertTrue(self.card._apply_active("17"),
                        "点名旧终端只是附加信息，它失败时不许把切换本身拖成失败")


class CleanTerminalWindow(EnvSandbox):
    """顶栏「开验证终端」：用系统为新进程合成的环境开一个 cmd，让"生效没"一眼可见。

    真机背景（2026-09-30）：注册表与 explorer 现场启动的进程都是 1.4.1，用户新开
    标签页看到的仍是 1.4.2 —— 因为那个标签页继承的是旧宿主进程的环境块。
    跟用户解释"Windows 复制环境块"没用，直接给一个肯定干净的窗口才有结论。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._orig_fetch = main.MainWindow._start_fetch_versions
        cls._orig_detect = main.ComponentCard._detect_status
        main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
        main.ComponentCard._detect_status = lambda self, *a, **k: None
        cls.win = main.MainWindow()

    @classmethod
    def tearDownClass(cls):
        main.MainWindow._start_fetch_versions = cls._orig_fetch
        main.ComponentCard._detect_status = cls._orig_detect
        cls.win.deleteLater()

    def setUp(self):
        super().setUp()
        self.as_windows()
        self.log_view_text = lambda: self.win.log_view.toPlainText()

    def _stub_composed(self, value):
        orig = main.EnvManager.composed_env
        main.EnvManager.composed_env = staticmethod(lambda: value)
        self.addCleanup(setattr, main.EnvManager, "composed_env", orig)

    def _stub_opener(self, result=4321):
        calls = []
        orig = main.open_clean_console
        main.open_clean_console = lambda env: (calls.append(env) or result)
        self.addCleanup(setattr, main, "open_clean_console", orig)
        return calls

    def test_top_bar_has_the_clean_terminal_button(self):
        self.assertIn("验证终端", self.win.btn_clean_terminal.text())

    def test_click_passes_the_composed_environment(self):
        composed = {"PATH": "C:\\x", "BUN_HOME": "C:\\x\\bun-1.4.1"}
        self._stub_composed(composed)
        calls = self._stub_opener()
        self.win._on_clean_terminal_clicked()
        self.assertEqual(calls, [composed], "必须把「新进程会拿到的那份环境」原样传进去")

    def test_unavailable_composed_env_opens_nothing_and_says_so(self):
        self._stub_composed({})
        calls = self._stub_opener()
        self.win._on_clean_terminal_clicked()
        self.assertEqual(calls, [], "拿不到合成环境时不许凭当前进程那份旧快照开窗口")
        self.assertIn("拿不到", self.log_view_text())

    def test_launch_failure_is_reported_not_swallowed(self):
        self._stub_composed({"PATH": "C:\\x"})
        self._stub_opener(result=None)
        self.win._on_clean_terminal_clicked()
        self.assertIn("开不了", self.log_view_text())

    def test_success_logs_the_pid_so_the_user_knows_which_window(self):
        self._stub_composed({"PATH": "C:\\x"})
        self._stub_opener(result=4321)
        self.win._on_clean_terminal_clicked()
        self.assertIn("4321", self.log_view_text())

    def test_real_opener_passes_env_and_new_console_flag(self):
        # 只测这一处真 Popen 调用：桩掉 Popen 本身，钉住"env 与 creationflags 传对了"，
        # 否则参数名写错要等用户点下去才炸。
        seen = {}

        class FakeProc:
            pid = 99

        def fake_popen(argv, **kw):
            seen["argv"] = argv
            seen.update(kw)
            return FakeProc()

        orig = main.subprocess.Popen
        main.subprocess.Popen = fake_popen
        self.addCleanup(setattr, main.subprocess, "Popen", orig)
        pid = main.open_clean_console({"PATH": "C:\\x"})
        self.assertEqual(pid, 99)
        self.assertEqual(seen["argv"], ["cmd.exe"])
        self.assertEqual(seen["env"], {"PATH": "C:\\x"})
        self.assertEqual(seen["creationflags"], main.subprocess.CREATE_NEW_CONSOLE)

    def test_real_opener_returns_none_when_launch_fails(self):
        def boom(argv, **kw):
            raise OSError("没这个 shell")
        orig = main.subprocess.Popen
        main.subprocess.Popen = boom
        self.addCleanup(setattr, main.subprocess, "Popen", orig)
        self.assertIsNone(main.open_clean_console({"PATH": "C:\\x"}),
                          "开不了要返回 None 让界面如实说，不许把异常抛给 Qt 槽")

    def test_title_bar_buttons_are_not_clipped_at_minimum_width(self):
        """多一个按钮不许把标题栏挤裁字（实测最窄窗口下「清理残留 PATH」曾裁字）。"""
        win = self.win
        win.show()
        win.resize(win.minimumWidth(), 700)
        for _ in range(30):
            self.app.processEvents()
        clipped, right = [], 0
        for name in ("btn_github", "btn_refresh", "btn_cleanup_path",
                     "btn_clean_terminal", "btn_donate"):
            b = getattr(win, name)
            need = b.fontMetrics().horizontalAdvance(b.text())
            right = max(right, b.geometry().x() + b.geometry().width())
            if b.geometry().width() < need:
                clipped.append(f"{name} 宽{b.geometry().width()} < 文字{need}")
        self.assertEqual(clipped, [], "标题栏按钮在最窄窗口里被压扁裁字")
        self.assertLessEqual(right, win.width(), "按钮排到了窗口外面，最后一个点不到")


class ShellRefreshNotification(EnvSandbox):
    """广播必须真的让 explorer 重建环境块 —— 旧写法根本没做到。

    2026-09-30 真机实测：注册表已改成 bun-1.4.2，explorer 的环境块 6 秒后仍是 1.4.1，
    于是用户从开始栏/任务栏开的每个新终端都继承旧环境，"重开终端"永远无效。
    换成同步 SendMessageTimeoutW(Shell_TrayWnd, WM_SETTINGCHANGE, "Environment",
    SMTO_ABORTIFHUNG) 后 1 秒内 explorer 就翻成新值，单次只花 0.02 秒。
    """

    class FakeUser32:
        def __init__(self, find_ok=0x1234, send_ok=1):
            self.find_ok = find_ok
            self.send_ok = send_ok
            self.found = []
            self.sent = []
            self.posted = []

        def FindWindowW(self, cls, title):
            self.found.append(cls)
            return self.find_ok

        def SendMessageTimeoutW(self, hwnd, msg, wp, lp, flags, ms, out):
            self.sent.append((hwnd, msg, lp, flags, ms))
            return self.send_ok

        def PostMessageW(self, *a):
            self.posted.append(a)
            return 1

    def test_sends_settingchange_to_the_shell_window_with_a_live_wide_string(self):
        fake = self.FakeUser32()
        self.assertTrue(main.notify_shell_environment(user32=fake))
        self.assertIn("Shell_TrayWnd", fake.found, "必须点名外壳窗口，HWND_BROADCAST 对 explorer 无效")
        self.assertTrue(fake.sent, "一条都没发")
        for _hwnd, msg, lp, _flags, _ms in fake.sent:
            self.assertEqual(msg, 0x1A, "WM_SETTINGCHANGE")
            self.assertEqual(ctypes.string_at(lp, 24).decode("utf-16-le").rstrip("\x00"),
                             "Environment",
                             "lParam 必须指向一个还活着的双字节字符串；指错了 explorer 会直接忽略")
        self.assertFalse(fake.posted, "PostMessageW 那条老路已被实测证明无效，不许再用")

    def test_flags_must_abort_hung_windows_so_the_ui_cannot_be_frozen(self):
        fake = self.FakeUser32()
        main.notify_shell_environment(user32=fake)
        for _h, _m, _lp, flags, ms in fake.sent:
            self.assertTrue(flags & 0x0002, "SMTO_ABORTIFHUNG：没有它，一个僵死窗口就能把界面卡住")
            self.assertGreater(ms, 0, "必须有超时上限")

    def test_reports_failure_when_the_shell_never_acked(self):
        self.assertFalse(main.notify_shell_environment(user32=self.FakeUser32(find_ok=0)))
        self.assertFalse(main.notify_shell_environment(user32=self.FakeUser32(send_ok=0)))

    def test_registry_write_path_still_notifies_the_shell(self):
        # 沙箱已经把 _broadcast_env_change 换成记录桩（见 setUp 里的 broadcast_calls），
        # 这里要证的是"写注册表这条路仍然会去通知外壳"，不是通知的实现。
        self.as_windows()
        main.EnvManager._broadcast_env_change()
        self.assertTrue(self.broadcast_calls, "写完成后再也不通知外壳 = 用户重开终端永远拿旧环境")


if __name__ == "__main__":
    unittest.main(verbosity=2)
