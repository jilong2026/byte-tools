# -*- coding: utf-8 -*-
"""「识别并切换用户自己装的版本」（接管 / 还原）的规格测试（离线，不联网、不碰注册表、不弹 UAC）。

设计依据：docs/superpowers/specs/2026-09-30-external-version-discovery-switching-design.md
  §5.1 发现 / §5.2 复验 / §5.3 用户级接管 / §5.4 提权接管与还原 / §8 十七条必测。

沙箱原则：
  · HKCU / HKLM 的读写全部换成内存字典（read/write/delete_*_env_raw 四个接缝），
    绝不碰用户真实的注册表；
  · 提权助手调用点（main._run_elevated_helper）换成假助手，绝不弹 UAC；
  · 系统合成的环境（composed_env）用"系统段在前 + 用户段在后"的**迷你模拟**，
    这样"用户级压不住系统级"这条真机结论能在离线用例里被复现出来。

测试隔离铁律（见 DEVELOPMENT.md / 项目记忆）：本文件不替换任何模块级全局；
所有打桩都在 setUp 里做、addCleanup 还原。绝不写 `main.X = ...` 在模块顶层。
"""
import ctypes
import json
import os
import platform as _platform
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional, Tuple

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


# 一段**真实形态**的系统 PATH 原文（照 2026-09-30 本机 HKLM Path 抄的）：
# 含 Oracle javapath、system32、%JAVA_HOME%\bin 这类占位符，以及用户自装的 Maven。
MACHINE_PATH = (
    r"C:\Program Files\Common Files\Oracle\Java\javapath;"
    r"C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem;"
    r"C:\Windows\System32\WindowsPowerShell\v1.0\;"
    r"%JAVA_HOME%\bin;E:\soft\maven\apache-maven-3.9.2\bin"
)

MULTI_VERSION_KEYS = {"jdk", "python", "node", "go", "maven", "gradle", "bun"}


def _touch_exe(home: Path, name: str, subdir: str = "bin") -> Path:
    """在 home/subdir 下造一个可执行文件（探测与复验都要看真实文件）。"""
    d = home / subdir if subdir else home
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text("", encoding="utf-8")
    return f


class ExternalSandbox(unittest.TestCase):
    """把 CONFIG_DIR、两 hive 的注册表读写、提权助手调用点全部沙箱化。

    不继承 bt_multiversion_tests.EnvSandbox：那套沙箱换的是 EnvManager 的
    `_read_windows_user_path / _write_registry_env`，而本功能走的是**另一组**
    更底层的接缝（*_env_raw），两者混用会互相掩盖，不如各管一段、边界清楚。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "env-tools"
        self.cfg.mkdir(parents=True)

        self._saved = {k: getattr(main, k)
                       for k in ("CONFIG_DIR", "CONFIG_FILE", "CURRENT_OS")}
        main.CONFIG_DIR = self.cfg
        main.CONFIG_FILE = self.cfg / "config.json"
        main.CURRENT_OS = "Windows"
        self.addCleanup(lambda: [setattr(main, k, v) for k, v in self._saved.items()])

        # ---- 注册表四个接缝（内存字典）----
        self.hklm: Dict[str, Tuple[Optional[str], str]] = {
            "Path": (MACHINE_PATH, "REG_EXPAND_SZ"),
        }
        self.hkcu: Dict[str, Tuple[Optional[str], str]] = {}

        self._patch(main, "read_machine_env_raw",
                    lambda name: self.hklm.get(name, (None, "")))
        self._patch(main, "write_machine_env_raw",
                    lambda name, value, type_name: self.hklm.__setitem__(
                        name, (value, type_name)))
        self._patch(main, "delete_machine_env_raw",
                    lambda name: (self.hklm.pop(name, None), None)[1])
        self._patch(main, "read_user_env_raw",
                    lambda name: (self.hkcu.get(name, (None, ""))[0],
                                  self.hkcu.get(name, (None, ""))[1], "HKCU"))
        self._patch(main, "write_user_env_raw",
                    lambda name, value, type_name="": self.hkcu.__setitem__(
                        name, (value, type_name
                               or ("REG_EXPAND_SZ" if "%" in value else "REG_SZ"))))
        self._patch(main, "delete_user_env_raw",
                    lambda name: (self.hkcu.pop(name, None), None)[1])

        # ---- 广播：绝不给真实桌面发消息 ----
        self.broadcasts = []
        self._patch(main.EnvManager, "_broadcast_env_change",
                    staticmethod(lambda: self.broadcasts.append("WM_SETTINGCHANGE")))

        # ---- EnvManager 的持久层读侧也接进来（否则卡片的 _path_hit_version /
        #      infer_active_from_env 会去读**真实** HKCU，用例随宿主机状态飘）----
        self._patch(main.EnvManager, "read_user_env",
                    staticmethod(lambda name: (self.hkcu.get(name) or (None, ""))[0]))
        self._patch(main.EnvManager, "read_user_path_entries",
                    staticmethod(lambda: [
                        p for p in (self.hkcu.get("Path") or ("", ""))[0].split(";")
                        if p]))

        # ---- 合成环境：复现真机规则「系统段整体在前 + 用户段整体在后」----
        self._patch(main.EnvManager, "composed_env",
                    staticmethod(self._compose))
        self._composed_override = None

        # ---- 提权助手：默认"没人接"，需要提权的用例自己装假助手 ----
        self.helper_calls = []
        self._patch(main, "_run_elevated_helper", self._no_helper)

        # ---- 卡片与窗口的重东西一律停掉（本文件只测纯逻辑 + 薄封装）----
        self._patch(main.ComponentCard, "_detect_status", lambda self, *a, **k: None)
        self._patch(main, "list_shell_processes", lambda: [])

    # ------------------------------------------------------------------
    def _patch(self, obj, name, value):
        """打桩并登记还原，且**先断言属性存在**——拼错名字只会静默不生效，
        那是最难查的一类假绿灯（本项目已经踩过三次）。"""
        self.assertTrue(hasattr(obj, name), f"要打桩的 {name} 不存在")
        original = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)

    def _compose(self) -> Dict[str, str]:
        """迷你模拟 CreateEnvironmentBlock：机器段 + 用户段，展开 %VAR% 后返回。"""
        if self._composed_override is not None:
            return dict(self._composed_override)
        parts = []
        for name in ("Path",):
            raw = (self.hklm.get(name) or (None, ""))[0] or ""
            parts += [os.path.expandvars(p) for p in raw.split(";") if p.strip()]
        raw_u = (self.hkcu.get("Path") or (None, ""))[0] or ""
        parts += [os.path.expandvars(p) for p in raw_u.split(";") if p.strip()]
        out = {"PATH": ";".join(parts)}
        for key in ("JAVA_HOME", "MAVEN_HOME", "PYTHON_HOME"):
            v = (self.hkcu.get(key) or (None, ""))[0]
            if v:
                out[key] = os.path.expandvars(v)
        return out

    def composed_is(self, value):
        self._composed_override = {} if value is None else dict(value)

    def _no_helper(self, request, timeout=None):
        self.helper_calls.append(dict(request))
        return {"ok": False, "stage": "launch", "error": "测试未安装提权助手"}

    def install_fake_helper(self, behaviour: str = "ok"):
        """装一个假助手。

        behaviour:
          "ok"       真实跑一遍助手核心（含全部硬规则）后回报成功
          "cancel"   模拟用户在 UAC 上点"否"
          "timeout"  模拟有界等待超时（**什么都没写**）
          "silent"   模拟"写了但没回报"（注册表已变、结果文件没等到 → 超时）
          "drop_key" 模拟写入后 system32 那条丢了（助手侧必须自己回滚）
        """
        def fake(request, timeout=None):
            self.helper_calls.append(dict(request))
            backend = main.MachineRegistryBackend()
            mode = str(request.get("mode") or "apply")
            if behaviour == "cancel":
                return {"ok": False, "stage": "cancelled",
                        "error": "用户取消了管理员权限请求"}
            if mode == "restore":
                res = main.elevate_helper_restore(request, backend)
                return res if res.get("ok") else {
                    "ok": False, "stage": "denied",
                    "error": str(res.get("error") or "助手还原失败")}
            if behaviour == "timeout":
                return {"ok": False, "stage": "timeout", "error": "等待超时"}
            if behaviour == "silent":
                # 先真写成功，再假装没来得及回报
                main.elevate_helper_apply(request, backend)
                return {"ok": False, "stage": "timeout", "error": "等待超时"}
            if behaviour == "drop_key":
                res = main.elevate_helper_apply(request, _KeyDroppingBackend())
                return {"ok": False, "stage": "denied",
                        "error": str(res.get("error") or "助手失败")}
            res = main.elevate_helper_apply(request, backend)
            if res.get("ok"):
                return {"ok": True, "stage": "ok", "error": "",
                        "before": res["before"], "after": res["after"]}
            return {"ok": False, "stage": "denied",
                    "error": str(res.get("error") or "助手失败")}

        main._run_elevated_helper = fake
        return fake

    # ---- 便捷构造 ----
    def comp(self, key: str):
        return next(c for c in main.build_components() if c.key == key)

    def make_home(self, label: str, exe: str, subdir: str = "bin") -> Path:
        home = self.root / "homes" / label
        _touch_exe(home, exe, subdir)
        return home

    def candidates(self, comp, extra_env=None, extra_path=None, probe=None):
        """跑一次发现：把假的环境变量 / PATH 条目 / 探测结果喂进去。"""
        env_rows = [("HKCU", k, v) for k, v in (extra_env or {}).items()]
        path_rows = [("HKLM", p) for p in (extra_path or [])]
        with _patch_ctx(self, main, "_windows_registry_env_values", lambda: env_rows), \
                _patch_ctx(self, main, "_windows_registry_path_entries", lambda: path_rows), \
                _patch_ctx(self, main, "_python_homes_from_py_launcher", lambda: []), \
                _patch_ctx(self, main, "_python_homes_from_registry", lambda: []):
            cands = main.discover_version_candidates(comp)
            if probe is None:
                return cands
            with _patch_ctx(self, main, "_probe_version", probe):
                return main.probe_discovered_versions(comp, cands)

    def dv(self, home: Path, version: str = "17.0.12",
           source: str = "env:JAVA_HOME") -> main.DiscoveredVersion:
        return main.DiscoveredVersion(home=home, source=source, version=version)


class _patch_ctx:
    """with 里打桩、退出还原（给一次性的发现接缝用）。"""

    def __init__(self, case, obj, name, value):
        self.case = case
        self.obj = obj
        self.name = name
        self.value = value

    def __enter__(self):
        self.orig = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.orig)
        return False


class _KeyDroppingBackend:
    """模拟"写完之后 system32 那条不见了"（磁盘满 / 杀软拦写 / 半截写入）。

    只脏第一次 Path 写：麻烦出在"写"这一步，回滚时写的仍是我们自己算出来的正确原文，
    必须能成功 —— 否则这条用例验证的就变成"坏后端连回滚也做不了"，跑偏了。
    """

    def __init__(self):
        self.real = main.MachineRegistryBackend()
        self.dropped_once = False

    def read(self, name):
        return self.real.read(name)

    def write(self, name, value, type_name):
        if name == "Path" and not self.dropped_once:
            self.dropped_once = True
            value = ";".join(p for p in str(value).split(";")
                             if "system32" not in p.lower())
        self.real.write(name, value, type_name)

    def delete(self, name):
        self.real.delete(name)


# ===========================================================================
# §8.1 发现
# ===========================================================================
class DiscoveryTests(ExternalSandbox):

    def test_three_env_vars_become_three_candidates_with_correct_source(self):
        """§8.1：jdk8 / jdk17 / jdk21 三个假变量 → 三条候选，source 各自正确。"""
        comp = self.comp("jdk")
        h8 = self.make_home("jdk8", "java.exe")
        h17 = self.make_home("jdk17", "java.exe")
        h21 = self.make_home("jdk21", "java.exe")
        cands = self.candidates(comp, extra_env={
            "JDK8_HOME": str(h8), "JDK17_HOME": str(h17), "JDK21_HOME": str(h21)})
        external = [c for c in cands if c.source != "workspace"]
        self.assertEqual(len(external), 3, f"应发现 3 条外部候选，实际 {external}")
        self.assertEqual({c.source for c in external},
                         {"env:JDK8_HOME", "env:JDK17_HOME", "env:JDK21_HOME"})
        self.assertEqual({c.home for c in external}, {h8, h17, h21})

    def test_dir_without_executable_is_not_a_candidate(self):
        """§8.1：没有可执行文件的目录不入选。"""
        comp = self.comp("jdk")
        empty = self.root / "homes" / "empty-jdk"
        empty.mkdir(parents=True)
        good = self.make_home("jdk17", "java.exe")
        cands = self.candidates(comp, extra_env={"A": str(empty), "B": str(good)})
        homes = {c.home for c in cands if c.source != "workspace"}
        self.assertIn(good, homes)
        self.assertNotIn(empty, homes)

    def test_probe_failure_drops_candidate_and_logs_warning(self):
        """§8.1：探测失败的候选被丢弃且日志有 warn。"""
        comp = self.comp("jdk")
        bad = self.make_home("jdk-broken", "java.exe")
        good = self.make_home("jdk17", "java.exe")

        def probe(exe, args):
            return "" if "jdk-broken" in exe else "openjdk version \"17.0.12\" 2024-07-16"

        logs = []
        with _patch_ctx(self, main, "_windows_registry_env_values",
                        lambda: [("HKCU", "BAD", str(bad)), ("HKCU", "GOOD", str(good))]), \
                _patch_ctx(self, main, "_windows_registry_path_entries", lambda: []), \
                _patch_ctx(self, main, "_python_homes_from_py_launcher", lambda: []), \
                _patch_ctx(self, main, "_python_homes_from_registry", lambda: []), \
                _patch_ctx(self, main, "_probe_version", probe):
            cands = main.discover_version_candidates(comp)
            kept = main.probe_discovered_versions(comp, cands, log=logs.append)
        kept_homes = {c.home for c in kept if c.source != "workspace"}
        self.assertIn(good, kept_homes)
        self.assertNotIn(bad, kept_homes)
        self.assertTrue(any("jdk-broken" in line or "版本命令" in line for line in logs),
                        f"应有一行 warn 记账，实际 {logs}")
        # 版本号必须来自真跑的探测输出，不能靠目录名猜
        for c in kept:
            if c.home == good:
                self.assertEqual(c.version, "17.0.12")

    def test_path_entry_pointing_at_bin_dir_rolls_back_one_level(self):
        """§8.2：PATH 里的 E:\\x\\bin 反推出的 home 是 E:\\x。"""
        comp = self.comp("jdk")
        home = self.make_home("jdk17", "java.exe")
        bin_dir = home / "bin"
        cands = self.candidates(comp, extra_path=[str(bin_dir)])
        homes = {c.home for c in cands if c.source != "workspace"}
        self.assertIn(home, homes, "bin 目录要退一级才是 home")
        self.assertNotIn(bin_dir, homes)
        src = next(c.source for c in cands if c.home == home)
        self.assertEqual(src, "path:HKLM")

    def test_same_path_in_var_and_path_is_deduped_preferring_env(self):
        """§8.3：同一路径既在变量又在 PATH → 只一条，优先 env:。"""
        comp = self.comp("jdk")
        home = self.make_home("jdk17", "java.exe")
        cands = self.candidates(comp, extra_env={"JAVA_HOME": str(home)},
                                extra_path=[str(home / "bin")])
        hits = [c for c in cands if c.home == home]
        self.assertEqual(len(hits), 1, f"应去重成一条，实际 {hits}")
        self.assertTrue(hits[0].source.startswith("env:"), hits[0].source)

    def test_only_whitelisted_components_get_external_candidates(self):
        """§8.16：只对白名单 7 个组件运行发现。"""
        comp = self.comp("jdk")
        home = self.make_home("jdk17", "java.exe")
        self.assertEqual(main.EXTERNAL_TAKEOVER_KEYS, MULTI_VERSION_KEYS,
                         "白名单必须与 bt_multiversion_tests 的第二处登记一致")
        self.assertTrue(main.supports_external_takeover(comp))
        # 非白名单组件：即使环境变量指着一个合法 home，也不产生外部候选
        others = [c for c in main.build_components()
                  if c.key not in MULTI_VERSION_KEYS]
        self.assertTrue(others, "组件表不该只有这 7 个")
        for other in others:
            self.assertFalse(main.supports_external_takeover(other), other.key)
            self.assertEqual(main.discover_version_candidates(other), [])

    def test_workspace_versions_always_listed_first_and_deduped(self):
        comp = self.comp("jdk")
        (comp.install_dir("21") / "bin").mkdir(parents=True, exist_ok=True)
        _touch_exe(comp.install_dir("21"), "java.exe")
        cands = self.candidates(comp, extra_env={
            "OUT": str(comp.install_dir("21"))})
        works = [c for c in cands if c.source == "workspace"]
        self.assertEqual([c.version for c in works], ["21"])
        hits = [c for c in cands if c.home == comp.install_dir("21")]
        self.assertEqual(len(hits), 1, "同一个目录算工作区就不该再算外部")
        self.assertEqual(hits[0].source, "workspace")


# ===========================================================================
# §8.17 Python 专属登记处
# ===========================================================================
class PythonRegistryTests(ExternalSandbox):

    PY_LAUNCHER_OUTPUT = (
        " -V:3.14 *        C:\\Users\\E5430\\AppData\\Local\\Programs\\Python"
        "\\Python314\\python.exe\n"
        " -V:Astral/CPython3.12.12 C:\\Users\\E5430\\AppData\\Roaming\\uv\\python"
        "\\cpython-3.12.12-windows-x86_64-none\\python.exe\n"
    )

    def test_py_launcher_lines_are_parsed_into_homes(self):
        """§8.17：喂本机真实 `py -0p` 输出两行 → 两条 home（取 python.exe 的父目录）。"""
        class _Proc:
            stdout = self.PY_LAUNCHER_OUTPUT
            returncode = 0

        with _patch_ctx(self, main.subprocess, "run",
                        staticmethod(lambda *a, **k: _Proc)):
            homes = main._python_homes_from_py_launcher()
        self.assertEqual(homes, [
            r"C:\Users\E5430\AppData\Local\Programs\Python\Python314",
            r"C:\Users\E5430\AppData\Roaming\uv\python"
            r"\cpython-3.12.12-windows-x86_64-none",
        ])

    def test_version_not_on_path_and_without_home_var_is_still_found(self):
        """§8.17 的核心断言：既不在 PATH、也没有 PYTHON_HOME 的那条仍能入选。

        本机 uv 装的那份 Python 就是这样 —— 去掉第 4 步（登记处）它必须变红。
        """
        comp = self.comp("python")
        home = self.make_home("uv-python", "python.exe", subdir="")
        with _patch_ctx(self, main, "_windows_registry_env_values", lambda: []), \
                _patch_ctx(self, main, "_windows_registry_path_entries", lambda: []), \
                _patch_ctx(self, main, "_python_homes_from_py_launcher",
                           lambda: [str(home)]), \
                _patch_ctx(self, main, "_python_homes_from_registry", lambda: []):
            cands = main.discover_version_candidates(comp)
        hits = [c for c in cands if c.source == "registry:py"]
        self.assertEqual([c.home for c in hits], [home])

    def test_registry_fallback_includes_non_pythoncore_company_keys(self):
        """§8.17：`py` 不存在时退回读注册表，含 Astral 这类非 PythonCore 公司键。"""
        comp = self.comp("python")
        home = self.make_home("astral", "python.exe", subdir="")
        with _patch_ctx(self, main, "_windows_registry_env_values", lambda: []), \
                _patch_ctx(self, main, "_windows_registry_path_entries", lambda: []), \
                _patch_ctx(self, main, "_python_homes_from_py_launcher", lambda: []), \
                _patch_ctx(self, main, "_python_homes_from_registry",
                           lambda: [str(home)]):
            cands = main.discover_version_candidates(comp)
        self.assertIn(home, {c.home for c in cands})

    def test_registry_source_never_runs_for_non_python_components(self):
        """§8.17：非 Python 组件**绝不**调用这条源。"""
        comp = self.comp("jdk")
        called = []
        with _patch_ctx(self, main, "_windows_registry_env_values",
                        lambda: (called.append("env"), [])[1]), \
                _patch_ctx(self, main, "_windows_registry_path_entries",
                           lambda: (called.append("path"), [])[1]), \
                _patch_ctx(self, main, "_python_homes_from_py_launcher",
                           lambda: (called.append("py"), [])[1]), \
                _patch_ctx(self, main, "_python_homes_from_registry",
                           lambda: (called.append("reg"), [])[1]):
            main.discover_version_candidates(comp)
        self.assertNotIn("py", called)
        self.assertNotIn("reg", called)

    def test_no_registry_and_no_launcher_is_not_an_error(self):
        """§8.17：注册表也没有时不报错、只是没有额外候选。"""
        comp = self.comp("python")
        with _patch_ctx(self, main, "_windows_registry_env_values", lambda: []), \
                _patch_ctx(self, main, "_windows_registry_path_entries", lambda: []), \
                _patch_ctx(self, main, "_python_homes_from_py_launcher", lambda: []), \
                _patch_ctx(self, main, "_python_homes_from_registry", lambda: []):
            self.assertEqual(main.discover_version_candidates(comp), [])


# ===========================================================================
# §8.4 复验三态
# ===========================================================================
class PathVerificationTests(ExternalSandbox):

    def setUp(self):
        super().setUp()
        self.comp_ = self.comp("jdk")
        self.home = self.make_home("jdk21", "java.exe")
        self.bin = str(self.home / "bin")

    def test_ok_when_first_hit_is_the_expected_dir(self):
        self.composed_is({"PATH": self.bin + r";C:\Windows\system32"})
        self.assertEqual(main.path_effective_check(self.comp_, self.bin), ("ok", None))

    def test_shadowed_names_the_directory_that_steals_the_command(self):
        other = self.make_home("jdk8", "java.exe")
        self.composed_is({"PATH": str(other / "bin") + ";" + self.bin})
        verdict, shadow = main.path_effective_check(self.comp_, self.bin)
        self.assertEqual(verdict, "shadowed")
        self.assertEqual(shadow, str(other / "bin"))

    def test_unknown_when_composed_env_unavailable(self):
        self.composed_is(None)
        self.assertEqual(main.path_effective_check(self.comp_, self.bin),
                         ("unknown", None))
        # 拿不到结果**不许**当成通过
        self.assertNotEqual(main.path_effective_check(self.comp_, self.bin)[0], "ok")

    def test_unknown_when_command_not_on_path_at_all(self):
        self.composed_is({"PATH": r"C:\Windows\system32"})
        self.assertEqual(main.path_effective_check(self.comp_, self.bin),
                         ("unknown", None))


# ===========================================================================
# §8.7 保真 / 最小编辑（助手核心，纯离线）
# ===========================================================================
class HelperFidelityTests(ExternalSandbox):

    def _request(self, home: Path, **kw):
        req = {"env_var": "JAVA_HOME", "home": str(home),
               "remove_entries": [], "add_entry": str(home / "bin"),
               "verify_dir": str(home / "bin"),
               "exec_names": ["java.exe", "java"], "backup_file": ""}
        req.update(kw)
        return req

    def test_placeholders_and_key_entries_survive_verbatim(self):
        """§8.7：含 %JAVA_HOME%\\bin 与 system32 的原文，写出的新原文里这些条目
        逐字仍在原位，只有我们那一条被插到最前，且类型仍是 REG_EXPAND_SZ。"""
        home = self.make_home("jdk17", "java.exe")
        self.hklm["JAVA_HOME"] = (r"C:\Program Files\Java\jdk1.8.0_202", "REG_SZ")
        before = MACHINE_PATH
        res = main.elevate_helper_apply(self._request(home),
                                        main.MachineRegistryBackend())
        self.assertTrue(res["ok"], res)
        after, after_type = self.hklm["Path"]
        self.assertEqual(after_type, "REG_EXPAND_SZ", "类型不能从 EXPAND_SZ 掉成 SZ")
        self.assertTrue(after.startswith(str(home / "bin") + ";"))
        # 除首条外，其余条目**逐字、按原顺序**保留
        self.assertEqual(after.split(";")[1:], before.split(";"))
        self.assertIn(r"%JAVA_HOME%\bin", after)
        self.assertIn(r"C:\Windows\system32", after)
        self.assertIn(r"C:\Windows", after)
        # 绝不允许把占位符展开成死路径
        self.assertNotIn(r"C:\Program Files\Java\jdk1.8.0_202\bin", after)

    def test_helper_never_reorders_or_dedupes_or_recases(self):
        """R-最小编辑：不重排、不去重、不改大小写、不合并重复项。"""
        home = self.make_home("jdk17", "java.exe")
        self.hklm["Path"] = (r"C:\Windows;c:\windows;C:\Windows;%JAVA_HOME%\bin",
                             "REG_EXPAND_SZ")
        before = self.hklm["Path"][0]
        main.elevate_helper_apply(self._request(home), main.MachineRegistryBackend())
        after = self.hklm["Path"][0]
        self.assertEqual(after.split(";")[1:], before.split(";"),
                         "重复项与大小写都必须原样保留")

    def test_remove_entries_only_removes_whole_entries(self):
        home = self.make_home("jdk17", "java.exe")
        target = r"E:\soft\maven\apache-maven-3.9.2\bin"
        req = self._request(home, remove_entries=[target])
        res = main.elevate_helper_apply(req, main.MachineRegistryBackend())
        self.assertTrue(res["ok"], res)
        after = self.hklm["Path"][0]
        self.assertNotIn(target, after)
        for part in MACHINE_PATH.split(";"):
            if part == target:
                continue
            self.assertIn(part, after, f"{part} 不该被动")

    def test_helper_writes_backup_file_before_touching_registry(self):
        """R-先备份：备份文件必须在写注册表之前落盘。"""
        home = self.make_home("jdk17", "java.exe")
        backup = self.cfg / "takeover-backups" / "jdk-x.json"
        seen = {}

        class _WatchingBackend(main.MachineRegistryBackend):
            def write(self, name, value, type_name):
                seen.setdefault("backup_exists_at_first_write", backup.exists())
                return super().write(name, value, type_name)

        main.elevate_helper_apply(self._request(home, backup_file=str(backup)),
                                  _WatchingBackend())
        self.assertTrue(seen.get("backup_exists_at_first_write"),
                        "第一次写注册表时备份文件就该已经存在")
        saved = json.loads(backup.read_text(encoding="utf-8"))
        self.assertEqual(saved["Path"]["raw"], MACHINE_PATH)

    def test_helper_reports_read_failure_without_writing(self):
        home = self.make_home("jdk17", "java.exe")

        class _DeadRead(main.MachineRegistryBackend):
            def read(self, name):
                raise OSError("拒绝访问")

        res = main.elevate_helper_apply(self._request(home), _DeadRead())
        self.assertFalse(res["ok"])
        self.assertEqual(self.hklm["Path"][0], MACHINE_PATH, "读都读不了就不该写")


# ===========================================================================
# §8.8 / §8.10 防呆回滚（助手侧）
# ===========================================================================
class HelperRollbackTests(ExternalSandbox):

    def _request(self, home: Path, **kw):
        req = {"env_var": "JAVA_HOME", "home": str(home),
               "remove_entries": [], "add_entry": str(home / "bin"),
               "verify_dir": str(home / "bin"),
               "exec_names": ["java.exe"], "backup_file": ""}
        req.update(kw)
        return req

    def test_lost_system32_triggers_rollback_and_reports_failure(self):
        """§8.8：写入后 system32 那条没了 → 助手自己回滚、报失败、注册表回到原样。"""
        home = self.make_home("jdk17", "java.exe")
        self.hklm["JAVA_HOME"] = (r"C:\Program Files\Java\jdk1.8.0_202", "REG_SZ")
        before_var = self.hklm["JAVA_HOME"]
        res = main.elevate_helper_apply(self._request(home), _KeyDroppingBackend())
        self.assertFalse(res["ok"], "关键条目丢了还敢报成功？")
        self.assertEqual(res["stage"], "rollback")
        self.assertIn("system32", res["error"].lower() + res["error"])
        self.assertEqual(self.hklm["Path"][0], MACHINE_PATH, "必须逐字回到改动前")
        self.assertEqual(self.hklm["JAVA_HOME"], before_var, "变量也要一起回滚")

    def test_atomicity_second_write_failure_rolls_back_the_first(self):
        """§8.10：JAVA_HOME 写成功、Path 写失败 → 回滚 JAVA_HOME。"""
        home = self.make_home("jdk17", "java.exe")

        class _PathWriteFails(main.MachineRegistryBackend):
            def write(self, name, value, type_name):
                if name == "Path":
                    raise OSError("磁盘满了")
                return super().write(name, value, type_name)

        res = main.elevate_helper_apply(self._request(home), _PathWriteFails())
        self.assertFalse(res["ok"])
        self.assertEqual(res["stage"], "rollback")
        self.assertNotIn("JAVA_HOME", self.hklm,
                         "Path 没写成，JAVA_HOME 必须一起撤掉（不能只成一半）")
        self.assertEqual(self.hklm["Path"][0], MACHINE_PATH)

    def test_var_write_failure_leaves_path_untouched(self):
        home = self.make_home("jdk17", "java.exe")

        class _VarWriteFails(main.MachineRegistryBackend):
            def write(self, name, value, type_name):
                if name != "Path":
                    raise OSError("拒绝访问")
                return super().write(name, value, type_name)

        res = main.elevate_helper_apply(self._request(home), _VarWriteFails())
        self.assertFalse(res["ok"])
        self.assertEqual(self.hklm["Path"][0], MACHINE_PATH)

    def test_preflight_validation_blocks_write_entirely(self):
        """改前自检不通过时，一个字都不该写。

        这里故意用"把 Path 清空"这种必然丢失 svchost/system32 的编辑：
        `_MACHINE_KEY_SUBSTRINGS` 是子串启发式，只删 system32 那一条时
        后面的 `...\\System32\\Wbem` 仍含 "system32"，启发式会漏 —— 所以用例
        用更彻底的形态触发它，而不是去赌启发式的边界。
        """
        home = self.make_home("jdk17", "java.exe")
        req = self._request(home, add_entry="", remove_entries=MACHINE_PATH.split(";"))
        res = main.elevate_helper_apply(req, _KeyDroppingBackend())
        self.assertFalse(res["ok"])
        self.assertIn("system32", res["error"])
        self.assertEqual(self.hklm["Path"][0], MACHINE_PATH,
                         "改前自检没过就一个字都不该写")


# ===========================================================================
# §8.5 / §8.6 / §8.9 用户级接管 → 提权 → 取消
# ===========================================================================
class TakeoverFlowTests(ExternalSandbox):

    def setUp(self):
        super().setUp()
        self.comp_ = self.comp("jdk")
        self.home = self.make_home("jdk17", "java.exe")
        self.dv_ = self.dv(self.home)
        self.ws_home = self.comp_.install_dir("21")
        _touch_exe(self.ws_home, "java.exe")
        self.logs = []

    def _log(self, text):
        self.logs.append(text)

    def test_user_level_takeover_succeeds_without_elevation(self):
        """§8.5：HKCU 写了 home、user PATH 没被压住、takeover 落快照。"""
        # 系统段里没有 java（把样例里的无关条目留下但不含 java）
        self.hklm["Path"] = (r"C:\Windows\system32;C:\Windows", "REG_EXPAND_SZ")
        self.hkcu["Path"] = (str(self.comp_.install_dir("21") / "bin"), "REG_EXPAND_SZ")
        # 切到外部 17 后，用户段最前一条变成 17 的 bin
        res = main.apply_external_version_user(self.comp_, self.dv_, log=self._log)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["verdict"], "ok")
        self.assertEqual(self.hkcu["JAVA_HOME"][0], str(self.home))
        self.assertIn(str(self.home / "bin"),
                      [p for p in self.hkcu["Path"][0].split(";") if p])
        self.assertEqual(self.helper_calls, [], "用户级能成就不该弹 UAC")
        self.assertTrue(res["snapshot"]["JAVA_HOME"]["existed"] is False
                        or res["snapshot"]["JAVA_HOME"]["raw"] is not None)

    def test_user_level_unknown_never_escalates_to_elevation(self):
        """§8.4/§5.3 第 4 步：unknown 不升级，如实报"未能复验"。"""
        self.composed_is(None)
        asked = []
        res = main.switch_to_external_version(
            self.comp_, self.dv_,
            confirm_machine=lambda plan: asked.append(plan) or True,
            log=self._log)
        self.assertFalse(res["ok"])
        self.assertEqual(res["verdict"], "unknown")
        self.assertEqual(asked, [], "拿不到复验结论时不许弹 UAC")
        self.assertEqual(self.helper_calls, [], "更不许去改系统变量")
        self.assertTrue(any("未能复验" in line for line in self.logs), self.logs)

    def test_shadowed_then_machine_takeover_level_is_machine(self):
        """§8.6：用户级不够 → 假助手 ok → 主程序复验通过 → level == machine。"""
        self.hklm["Path"] = (r"C:\Windows\system32;E:\soft\jdk\jdk8\bin",
                             "REG_EXPAND_SZ")
        _touch_exe(Path(r"E:\soft\jdk\jdk8") if False else
                   self.make_home("jdk8", "java.exe"), "java.exe")
        shadow_home = self.root / "homes" / "jdk8"
        self.hklm["Path"] = (r"C:\Windows\system32;" + str(shadow_home / "bin"),
                             "REG_EXPAND_SZ")
        self.install_fake_helper("ok")
        asked = []
        res = main.switch_to_external_version(
            self.comp_, self.dv_,
            confirm_machine=lambda plan: asked.append(plan) or True,
            log=self._log)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["level"], "machine")
        self.assertEqual(len(asked), 1, "提权前必须先弹确认")
        self.assertEqual(len(self.helper_calls), 1)
        self.assertIn(str(self.home / "bin"), self.hklm["Path"][0])
        entry = main.load_takeover_map()["jdk"]
        self.assertEqual(entry["level"], "machine")
        self.assertEqual(entry["home"], str(self.home))
        self.assertIn("HKLM", entry["snapshot"])

    def test_user_declining_the_confirmation_changes_nothing(self):
        shadow_home = self.make_home("jdk8", "java.exe")
        self.hklm["Path"] = (r"C:\Windows\system32;" + str(shadow_home / "bin"),
                             "REG_EXPAND_SZ")
        self.install_fake_helper("ok")
        res = main.switch_to_external_version(
            self.comp_, self.dv_, confirm_machine=lambda plan: False, log=self._log)
        self.assertFalse(res["ok"])
        self.assertEqual(res["verdict"], "cancelled")
        self.assertEqual(self.helper_calls, [], "没同意就不许调助手")
        self.assertNotIn("jdk", main.load_takeover_map())
        self.assertNotIn(str(self.home / "bin"), self.hklm["Path"][0])

    def test_cancelled_uac_leaves_zero_trace(self):
        """§8.9：取消 UAC（1223）→ 零改动、零快照。"""
        shadow_home = self.make_home("jdk8", "java.exe")
        self.hklm["Path"] = (r"C:\Windows\system32;" + str(shadow_home / "bin"),
                             "REG_EXPAND_SZ")
        before_machine = dict(self.hklm)
        self.install_fake_helper("cancel")
        res = main.switch_to_external_version(
            self.comp_, self.dv_, confirm_machine=lambda plan: True, log=self._log)
        self.assertFalse(res["ok"])
        self.assertEqual(res["verdict"], "cancelled")
        self.assertNotIn("jdk", main.load_takeover_map(), "取消后不许留下接管登记")
        self.assertEqual(self.hklm["Path"][0], before_machine["Path"][0])
        self.assertEqual(self.hklm["Path"][1], before_machine["Path"][1])
        self.assertNotIn("JAVA_HOME", self.hklm)

    def test_timeout_is_not_treated_as_failure_when_registry_actually_changed(self):
        """§5.4：超时 ≠ 失败。助手其实写成功了 → 必须报成功并补写快照。"""
        shadow_home = self.make_home("jdk8", "java.exe")
        self.hklm["Path"] = (r"C:\Windows\system32;" + str(shadow_home / "bin"),
                             "REG_EXPAND_SZ")
        self.install_fake_helper("silent")
        res = main.switch_to_external_version(
            self.comp_, self.dv_, confirm_machine=lambda plan: True, log=self._log)
        self.assertTrue(res["ok"], f"注册表确实改了，就不能报失败：{res}")
        self.assertEqual(res["level"], "machine")
        self.assertIn("jdk", main.load_takeover_map())

    def test_timeout_with_no_change_reports_failure_and_no_snapshot(self):
        shadow_home = self.make_home("jdk8", "java.exe")
        self.hklm["Path"] = (r"C:\Windows\system32;" + str(shadow_home / "bin"),
                             "REG_EXPAND_SZ")
        self.install_fake_helper("timeout")
        res = main.switch_to_external_version(
            self.comp_, self.dv_, confirm_machine=lambda plan: True, log=self._log)
        self.assertFalse(res["ok"])
        self.assertNotIn("jdk", main.load_takeover_map())

    def test_lost_key_simulation_rolls_back_and_leaves_no_takeover(self):
        """§8.8 主程序侧：假助手模拟丢条目 → 自动回滚、config 里没有 takeover 残留。"""
        shadow_home = self.make_home("jdk8", "java.exe")
        self.hklm["Path"] = (r"C:\Windows\system32;" + str(shadow_home / "bin"),
                             "REG_EXPAND_SZ")
        before = dict(self.hklm)
        self.install_fake_helper("drop_key")
        res = main.switch_to_external_version(
            self.comp_, self.dv_, confirm_machine=lambda plan: True, log=self._log)
        self.assertFalse(res["ok"])
        self.assertNotIn("jdk", main.load_takeover_map())
        self.assertEqual(self.hklm["Path"], before["Path"], "注册表必须回到原样")

    def test_post_write_verification_failure_triggers_automatic_revert(self):
        """§7：写完但复验不过 → 自动还原 + 不报成功。

        模拟"无论怎么改都被抢"：合成环境里 java 永远先命中 Oracle javapath，
        于是用户级 shadowed（该提权）→ 提权写成功后复验仍 shadowed → 必须自动还原。
        """
        shadow_home = self.make_home("jdk8", "java.exe")
        self.hklm["Path"] = (r"C:\Windows\system32;" + str(shadow_home / "bin"),
                             "REG_EXPAND_SZ")
        before = dict(self.hklm)
        # 一个"永远抢在前面"的目录（模拟 Oracle javapath 里有 java.exe）
        keep = self.make_home("javapath", "java.exe")
        self.composed_is({"PATH": str(keep / "bin") + ";" + str(self.home / "bin")})
        self.install_fake_helper("ok")

        res = main.switch_to_external_version(
            self.comp_, self.dv_, confirm_machine=lambda plan: True, log=self._log)
        self.assertFalse(res["ok"], "复验不过绝不能报成功")
        self.assertNotIn("jdk", main.load_takeover_map())
        self.assertEqual(self.hklm["Path"], before["Path"],
                         "自动还原必须把系统 PATH 写回原文")
        self.assertTrue(any("还原" in line for line in self.logs), self.logs)


# ===========================================================================
# §8.11 / §8.12 还原与互斥
# ===========================================================================
class RevertTests(ExternalSandbox):

    def setUp(self):
        super().setUp()
        self.comp_ = self.comp("jdk")
        self.home = self.make_home("jdk17", "java.exe")
        self.logs = []

    def _log(self, text):
        self.logs.append(text)

    def test_revert_restores_user_keys_and_deletes_keys_that_did_not_exist(self):
        """§8.11：existed=false 的键必须被**删除**（不是写空串）。"""
        self.hklm["Path"] = (r"C:\Windows\system32;C:\Windows", "REG_EXPAND_SZ")
        self.hkcu["Path"] = (str(self.root / "mine" / "bin"), "REG_EXPAND_SZ")
        before_path = self.hkcu["Path"][0]
        main.apply_external_version_user(self.comp_, self.dv(self.home), log=self._log)
        entry = {"home": str(self.home), "version": "17.0.12", "level": "user",
                 "snapshot": {"HKCU": main.snapshot_user_keys(["JAVA_HOME", "Path"]),
                              "HKLM": {}},
                 "added": {"HKCU": [], "HKLM": []}, "backup_file": ""}
        # 手工把"改动前"的快照换回去（模拟真实流程里 §5.3 先快照再改）
        entry["snapshot"]["HKCU"] = {
            "JAVA_HOME": {"hive": "HKCU", "raw": None, "type": "", "existed": False},
            "Path": {"hive": "HKCU", "raw": before_path, "type": "REG_EXPAND_SZ",
                     "existed": True},
        }
        entry["added"]["HKCU"] = [str(self.home / "bin")]
        self.hkcu["Path"] = (str(self.home / "bin") + ";" + before_path,
                             "REG_EXPAND_SZ")
        main.save_takeover_entry("jdk", entry)

        res = main.revert_external_version(self.comp_, log=self._log)
        self.assertTrue(res["ok"], res)
        self.assertNotIn("JAVA_HOME", self.hkcu, "原来没有这个变量 → 还原时要删掉")
        self.assertEqual(self.hkcu["Path"][0], before_path)
        self.assertNotIn("jdk", main.load_takeover_map())

    def test_revert_of_machine_takeover_requires_elevation_again(self):
        """§8.11：改过 HKLM 的还原要求再提权；取消就把登记留着。"""
        self.hklm["Path"] = (r"C:\Windows\system32", "REG_EXPAND_SZ")
        entry = {"home": str(self.home), "version": "17.0.12", "level": "machine",
                 "snapshot": {"HKCU": {}, "HKLM": {
                     "Path": {"hive": "HKLM", "raw": r"C:\Windows\system32",
                              "type": "REG_EXPAND_SZ", "existed": True}}},
                 "added": {"HKCU": [], "HKLM": [str(self.home / "bin")]},
                 "backup_file": ""}
        self.hklm["Path"] = (str(self.home / "bin") + r";C:\Windows\system32",
                             "REG_EXPAND_SZ")
        main.save_takeover_entry("jdk", entry)

        self.install_fake_helper("cancel")
        res = main.revert_external_version(self.comp_, log=self._log)
        self.assertFalse(res["ok"])
        self.assertTrue(res["cancelled"])
        self.assertIn("jdk", main.load_takeover_map(), "取消还原就保留登记，可稍后重试")
        self.assertIn(str(self.home / "bin"), self.hklm["Path"][0])

    def test_revert_of_machine_takeover_succeeds_with_fake_helper(self):
        self.install_fake_helper("ok")
        entry = {"home": str(self.home), "version": "17.0.12", "level": "machine",
                 "snapshot": {"HKCU": {}, "HKLM": {
                     "Path": {"hive": "HKLM", "raw": r"C:\Windows\system32",
                              "type": "REG_EXPAND_SZ", "existed": True}}},
                 "added": {"HKCU": [], "HKLM": [str(self.home / "bin")]},
                 "backup_file": ""}
        self.hklm["Path"] = (str(self.home / "bin") + r";C:\Windows\system32",
                             "REG_EXPAND_SZ")
        main.save_takeover_entry("jdk", entry)
        res = main.revert_external_version(self.comp_, log=self._log)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.hklm["Path"][0], r"C:\Windows\system32")
        self.assertNotIn("jdk", main.load_takeover_map())

    def test_no_takeover_revert_is_a_clean_noop(self):
        res = main.revert_external_version(self.comp_, log=self._log)
        self.assertFalse(res["ok"])
        self.assertIn("没有登记在案的接管", res["error"])

    def test_takeover_and_active_are_mutually_exclusive(self):
        """§8.12：切外部 ⇒ 删 active；切工作区 ⇒ 删 takeover 并还原。"""
        self.hkcu["Path"] = (r"C:\Windows\system32", "REG_EXPAND_SZ")
        main.save_active_version("jdk", "21")
        self.assertEqual(main.load_active_map().get("jdk"), "21")

        self.hklm["Path"] = (r"C:\Windows\system32", "REG_EXPAND_SZ")
        # 真实流程里 §5.3 是"先快照、后改动"，这里照做
        pre_user = main.snapshot_user_keys(["JAVA_HOME", "Path"])
        main.apply_external_version_user(self.comp_, self.dv(self.home), log=self._log)
        entry = {"home": str(self.home), "version": "17.0.12", "level": "user",
                 "snapshot": {"HKCU": pre_user, "HKLM": {}},
                 "added": {"HKCU": [str(self.home / "bin")], "HKLM": []},
                 "backup_file": ""}
        main.save_takeover_entry("jdk", entry)
        self.assertNotIn("jdk", main.load_active_map(),
                         "接管生效期间不许还留着 active 登记（孤儿态）")

        # 切回工作区版本：先还原外部接管
        release = main.release_external_before_workspace_switch(self.comp_,
                                                                log=self._log)
        self.assertTrue(release["ok"], release)
        self.assertNotIn("jdk", main.load_takeover_map())
        self.assertNotIn("JAVA_HOME", self.hkcu, "接管前没有这个变量，还原时要删掉")
        self.assertEqual(self.hkcu["Path"][0], r"C:\Windows\system32")

    def test_release_is_noop_when_no_takeover(self):
        res = main.release_external_before_workspace_switch(self.comp_)
        self.assertTrue(res["ok"])
        self.assertEqual(res["steps"], [])


# ===========================================================================
# §8.14 / §8.15 回归护栏
# ===========================================================================
class RegressionGuardTests(ExternalSandbox):

    def test_legacy_config_without_takeover_key_reads_fine(self):
        """§8.14：老 config.json（无 takeover）能直接读。"""
        main.save_active_version("jdk", "21")
        data = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("takeover", data)
        self.assertEqual(main.load_active_map().get("jdk"), "21")
        self.assertEqual(main.load_takeover_map(), {})

    def test_corrupt_takeover_entries_are_skipped_not_propagated(self):
        """§7：takeover 损坏 → 忽略该条（不把半截快照往下传）。"""
        main.CONFIG_FILE.write_text(json.dumps({
            "active": {"jdk": "21"},
            "takeover": {
                "jdk": {"home": "", "version": "17", "level": "user", "snapshot": {}},
                "maven": {"home": r"E:\soft\maven", "version": "", "level": "user",
                          "snapshot": {"a": 1}},
                "node": {"home": r"C:\node", "version": "20", "level": "user",
                         "snapshot": {"a": 1}},
                "go": "not-a-dict",
            },
        }, ensure_ascii=False), encoding="utf-8")
        got = main.load_takeover_map()
        self.assertEqual(list(got), ["node"])
        self.assertEqual(got["node"]["home"], r"C:\node")

    def test_external_homes_never_enter_install_or_uninstall_candidates(self):
        """§8.15：外部 home 永不出现在卸载候选；卸载不删外部目录。"""
        comp = self.comp("jdk")
        (comp.install_dir("21") / "bin").mkdir(parents=True, exist_ok=True)
        external = self.make_home("jdk17", "java.exe")
        cands = self.candidates(comp, extra_env={"JDK17_HOME": str(external)})
        self.assertIn(external, {c.home for c in cands}, "发现层要看得见它")

        installed = {p for _v, p in main.installed_versions(comp)}
        self.assertNotIn(external, installed, "外部目录不算本工具装的版本")
        for _v, p in main.installed_versions(comp):
            self.assertTrue(main.EnvManager._under_root(str(p), str(main.CONFIG_DIR)),
                            f"卸载候选必须全在配置目录内：{p}")

    def test_discover_does_not_mutate_any_state(self):
        """发现必须**只读**：跑一遍发现，注册表与 config.json 都不得变动。"""
        comp = self.comp("jdk")
        home = self.make_home("jdk17", "java.exe")
        before_machine = {k: tuple(v) for k, v in self.hklm.items()}
        before_user = {k: tuple(v) for k, v in self.hkcu.items()}
        cfg_before = main.CONFIG_FILE.read_text(encoding="utf-8") \
            if main.CONFIG_FILE.exists() else None
        self.candidates(comp, extra_env={"JAVA_HOME": str(home)})
        self.assertEqual({k: tuple(v) for k, v in self.hklm.items()}, before_machine)
        self.assertEqual({k: tuple(v) for k, v in self.hkcu.items()}, before_user)
        cfg_after = main.CONFIG_FILE.read_text(encoding="utf-8") \
            if main.CONFIG_FILE.exists() else None
        self.assertEqual(cfg_before, cfg_after)


# ===========================================================================
# 助手进程协议
# ===========================================================================
class HelperProtocolTests(ExternalSandbox):

    def test_request_and_result_round_trip_through_files(self):
        """助手入口：读请求文件 → 干活 → 写结果文件 → 删请求文件。"""
        home = self.make_home("jdk17", "java.exe")
        req_file = self.root / "req.json"
        res_file = self.root / "res.json"
        req_file.write_text(json.dumps({
            "mode": "apply", "env_var": "JAVA_HOME", "home": str(home),
            "remove_entries": [], "add_entry": str(home / "bin"),
            "verify_dir": str(home / "bin"),
            "exec_names": ["java.exe"], "backup_file": "",
            "result_file": str(res_file),
        }), encoding="utf-8")
        code = main.elevate_helper_main(str(req_file))
        self.assertEqual(code, 0)
        self.assertTrue(res_file.exists(), "结果文件是助手唯一的回报通道")
        data = json.loads(res_file.read_text(encoding="utf-8"))
        self.assertTrue(data["ok"], data)
        self.assertEqual(self.hklm["JAVA_HOME"][0], str(home))
        self.assertFalse(req_file.exists(), "请求文件用完要删")

    def test_broken_request_file_does_not_raise(self):
        req_file = self.root / "junk.json"
        req_file.write_text("{ 这不是 json", encoding="utf-8")
        self.assertEqual(main.elevate_helper_main(str(req_file)), 1)

    def test_restore_mode_writes_snapshot_back(self):
        home = self.make_home("jdk17", "java.exe")
        self.hklm["Path"] = (str(home / "bin") + r";C:\Windows\system32",
                             "REG_EXPAND_SZ")
        req_file = self.root / "req.json"
        res_file = self.root / "res.json"
        req_file.write_text(json.dumps({
            "mode": "restore", "result_file": str(res_file),
            "restore": {"Path": {"raw": r"C:\Windows\system32",
                                 "type": "REG_EXPAND_SZ", "existed": True}},
        }), encoding="utf-8")
        self.assertEqual(main.elevate_helper_main(str(req_file)), 0)
        self.assertEqual(self.hklm["Path"][0], r"C:\Windows\system32")
        self.assertEqual(self.hklm["Path"][1], "REG_EXPAND_SZ")

    def test_restore_deletes_key_that_did_not_exist(self):
        self.hklm["JAVA_HOME"] = (r"C:\jdk17", "REG_SZ")
        req_file = self.root / "req.json"
        res_file = self.root / "res.json"
        req_file.write_text(json.dumps({
            "mode": "restore", "result_file": str(res_file),
            "restore": {"JAVA_HOME": {"raw": None, "type": "", "existed": False}},
        }), encoding="utf-8")
        self.assertEqual(main.elevate_helper_main(str(req_file)), 0)
        self.assertNotIn("JAVA_HOME", self.hklm)

    def test_cli_flag_is_wired(self):
        """`--bt-elevate <请求文件>` 必须在建 QApplication 之前被识别。"""
        home = self.make_home("jdk17", "java.exe")
        req_file = self.root / "req.json"
        res_file = self.root / "res.json"
        req_file.write_text(json.dumps({
            "mode": "apply", "env_var": "JAVA_HOME", "home": str(home),
            "remove_entries": [], "add_entry": str(home / "bin"),
            "verify_dir": str(home / "bin"),
            "exec_names": ["java.exe"], "backup_file": "",
            "result_file": str(res_file),
        }), encoding="utf-8")
        argv = sys.argv[:]
        sys.argv = ["main.py", main.ELEVATE_FLAG, str(req_file)]
        try:
            self.assertEqual(main.main(), 0)
        finally:
            sys.argv = argv
        self.assertTrue(res_file.exists())

    def test_elevate_flag_without_path_is_rejected(self):
        argv = sys.argv[:]
        sys.argv = ["main.py", main.ELEVATE_FLAG]
        try:
            self.assertEqual(main.main(), 2)
        finally:
            sys.argv = argv


# ===========================================================================
# 沙箱自检
# ===========================================================================
class SandboxSelfCheck(ExternalSandbox):
    """沙箱自己也要有断言：它失效时，上面所有用例都会变成假绿灯。"""

    def test_registry_seams_are_actually_installed(self):
        self.assertIsNot(main.read_machine_env_raw.__name__, "_read_machine_env_raw")
        main.write_machine_env_raw("ZZZ_TEST", "1", "REG_SZ")
        self.assertEqual(self.hklm["ZZZ_TEST"], ("1", "REG_SZ"))
        main.delete_machine_env_raw("ZZZ_TEST")
        self.assertNotIn("ZZZ_TEST", self.hklm)
        self.assertEqual(main.read_machine_env_raw("ZZZ_TEST"), (None, ""))

    def test_helper_seam_is_actually_installed(self):
        main._run_elevated_helper({"anything": 1})
        self.assertEqual(len(self.helper_calls), 1)

    def test_no_windows_api_was_touched(self):
        """强断言：整轮跑完，真实 winreg 一次都没被调用过。"""
        calls = []
        real = main.write_machine_env_raw

        def spy(name, value, type_name):
            calls.append(name)
            return real(name, value, type_name)

        main.write_machine_env_raw = spy
        try:
            main.write_machine_env_raw("SPY", "x", "REG_SZ")
        finally:
            main.write_machine_env_raw = real
        self.assertEqual(calls, ["SPY"])
        self.assertEqual(self.hklm["SPY"], ("x", "REG_SZ"))


# ===========================================================================
# §8.13 胶囊四档文案 + §8.14 非目标组件零变化
# ===========================================================================
_QAPP = None


def _ensure_app():
    """卡片要 QApplication 才能构造；discover 模式下一个进程只建一个。"""
    global _QAPP
    from PySide6.QtWidgets import QApplication

    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


class CapsuleVariantTests(ExternalSandbox):
    """§6 的四档胶囊文案逐字断言。

    直接调 `_detect_status_impl()`（沙箱把外层的 `_detect_status` 包了一层，
    那层只额外刷新运行态，与本条无关），并桩掉版本探测线程 —— 它真会去跑
    java -version，测试里不能起。
    """

    def _card(self, key: str = "jdk"):
        _ensure_app()
        self._patch(main.ComponentCard, "_schedule_version_probe",
                    lambda self, exe_path, *a, **k: None)
        return main.ComponentCard(self.comp(key), lambda lvl, msg: None)

    def _names(self, key: str = "jdk") -> str:
        return "、".join(v for v, _p in main.installed_versions(self.comp(key)))

    def test_variant1_workspace_active_and_verified(self):
        comp = self.comp("jdk")
        for v in ("21", "17"):
            _touch_exe(comp.install_dir(v), "java.exe")
        main.save_active_version("jdk", "21")
        self.composed_is({"PATH": str(comp.install_dir("21") / "bin")})
        card = self._card()
        card._detect_status_impl()
        names = self._names()
        self.assertEqual(card._mv_capsule, f"● 已装 2 个版本 · 生效 21（{names}）")
        self.assertEqual(card._mv_capsule_short, "● 已装 2 个 · 生效 21")
        self.assertFalse(card._mv_orange, "复验通过不该是橙色")

    def test_variant2_shadowed_says_who_steals_the_command(self):
        comp = self.comp("jdk")
        for v in ("21", "17"):
            _touch_exe(comp.install_dir(v), "java.exe")
        main.save_active_version("jdk", "21")
        other = self.make_home("jdk8", "java.exe")
        self.composed_is({"PATH": str(other / "bin") + ";"
                          + str(comp.install_dir("21") / "bin")})
        card = self._card()
        card._detect_status_impl()
        names = self._names()
        self.assertEqual(
            card._mv_capsule,
            f"● 已装 2 个版本 · 生效 21（{names}） · 但 PATH 先命中 {other / 'bin'}")
        self.assertEqual(card._mv_capsule_short,
                         "● 已装 2 个 · 生效 21 · 被 PATH 抢先")
        self.assertTrue(card._mv_orange, "被压住必须是橙色告警")
        self.assertTrue(card.btn_configure.isEnabled(),
                        "被压住时切换按钮仍要可用（用户要能再点一次收敛）")

    def test_variant3_external_active(self):
        comp = self.comp("jdk")
        for v in ("21", "17"):
            _touch_exe(comp.install_dir(v), "java.exe")
        ext = self.make_home("jdk-ext", "java.exe")
        main.save_takeover_entry("jdk", {
            "home": str(ext), "version": "17.0.12", "level": "machine",
            "snapshot": {"HKCU": {"Path": {"hive": "HKCU", "raw": None,
                                           "type": "", "existed": False}},
                         "HKLM": {"Path": {"hive": "HKLM", "raw": "x",
                                           "type": "REG_EXPAND_SZ",
                                           "existed": True}}},
            "added": {"HKCU": [], "HKLM": [str(ext / "bin")]}, "backup_file": ""})
        card = self._card()
        card._detect_status_impl()
        names = self._names()
        self.assertEqual(
            card._mv_capsule,
            f"● 生效 17.0.12（系统 {ext}） · 工作区 2 个版本（{names}）")
        self.assertEqual(card._mv_capsule_short, "● 生效 17.0.12（系统级）")
        self.assertFalse(card._mv_orange, "接管生效是正常态，绿色")
        # 用 isHidden 而不是 isVisible：卡片本身没 show() 过，isVisible 恒为 False，
        # 那测的就变成"父窗口可不可见"而不是"这个按钮有没有被显式藏起来"。
        self.assertFalse(card._restore_btn.isHidden(),
                         "接管生效后卡片上要常驻「还原到我之前的设置」")

    def test_variant3b_external_version_disappeared(self):
        """§7：快照指向的目录被删了 → 如实说、不自动改环境。"""
        ext = self.root / "gone" / "jdk17"
        main.save_takeover_entry("jdk", {
            "home": str(ext), "version": "17.0.12", "level": "user",
            "snapshot": {"HKCU": {"Path": {"hive": "HKCU", "raw": None,
                                           "type": "", "existed": False}},
                         "HKLM": {}},
            "added": {"HKCU": [], "HKLM": []}, "backup_file": ""})
        card = self._card()
        card._detect_status_impl()
        self.assertTrue(card._mv_orange)
        self.assertIn("已不存在", card._mv_capsule)
        self.assertIn("还原", card._mv_capsule)

    def test_variant4_home_path_mismatch(self):
        comp = self.comp("jdk")
        for v in ("21", "17"):
            _touch_exe(comp.install_dir(v), "java.exe")
        # 登记表说生效 21，但 PATH 里那条指向 17 —— 命令行实际用的是 PATH 那个
        main.save_active_version("jdk", "21")
        self.hkcu["Path"] = (str(comp.install_dir("17") / "bin"), "REG_EXPAND_SZ")
        self.composed_is({"PATH": str(comp.install_dir("21") / "bin")})
        card = self._card()
        card._detect_status_impl()
        self.assertTrue(card._mv_orange)
        self.assertIn("未对齐", card._mv_capsule)

    def test_non_whitelisted_component_gets_no_external_ui(self):
        """§8.14 护栏：非白名单组件不建折叠区、不建还原按钮。"""
        card = self._card("tomcat")
        self.assertIsNone(card._external_frame)
        self.assertIsNone(card._restore_btn)
        self.assertIsNone(card._external_toggle)

    def test_external_candidates_never_enter_the_version_combo(self):
        """§6：外部版本**绝不进下拉框**（条目文本是版本反查的唯一键）。

        下拉框只认本工具工作区 + 内置清单；把 `E:\\soft\\jdk\\jdk17` 塞进去会
        让 `_current_version()` 反查错位，切版本/卸载全部跟着错。
        """
        comp = self.comp("jdk")
        _touch_exe(comp.install_dir("21"), "java.exe")
        ext = self.make_home("jdk-ext", "java.exe")
        card = self._card()
        card._external_candidates = [
            main.DiscoveredVersion(home=ext, source="env:JDK_HOME",
                                   version="17.0.12")]
        card._external_scanned = True
        card._refresh_external_section()
        texts = [card.version_combo.itemText(i)
                 for i in range(card.version_combo.count())]
        self.assertNotIn("17.0.12", texts, f"外部版本号不许进下拉框：{texts}")
        for t in texts:
            self.assertNotIn(str(ext), t)


class WorkspaceMachineFixTests(ExternalSandbox):
    """R3.19：工作区版本被**系统级**条目压住时，本工具要能自己解决，且必然可还原。

    真机场景（2026-10-08 实测本机 HKLM Path 第 6 条）：
      HKLM Path = ...;E:\\soft\\maven\\apache-maven-3.9.2\\bin;...
      HKCU Path = ...;C:\\Users\\...\\.env-tools\\maven\\maven-3.10.0\\bin
    合成规则是「系统段整体在前 + 用户段整体在后」，所以用户级怎么写都命中 3.9.2。
    卡片当时只打印「本工具不改系统级环境变量，你自己去改」—— 用户明确不接受；
    功能的目的就是"以用户的操作为准"，所以这里把它升级成"问一次就自己改、并且能还原"。

    本类守的三条不变量：
      1. 用户没点确认 / 在 UAC 上点否 → 系统变量**逐字节不动**，也不留登记；
      2. 改完必须记 machine_fix（还原依据），但**不许清掉 active**（与 takeover 不同，
         生效版本仍是工作区那个）；
      3. 复验不过 → 自动按原文还原 + 不留登记，绝不报成功。
    """

    MAVEN_EXT = r"E:\soft\maven\apache-maven-3.9.2\bin"

    def _maven(self):
        comp = self.comp("maven")
        _touch_exe(comp.install_dir("3.10.0"), "mvn.cmd")
        return comp

    def _card(self, comp, logs: list):
        _ensure_app()
        self._patch(main.ComponentCard, "_schedule_version_probe",
                    lambda self, exe_path, *a, **k: None)
        return main.ComponentCard(comp, lambda lvl, msg: logs.append((lvl, msg)))

    # ---- 判定层：抢命令的那条写在哪一段 ----

    def test_shadow_location_says_machine_for_the_real_maven_case(self):
        self.assertEqual(main.shadow_location(self.MAVEN_EXT), "machine")

    def test_shadow_location_says_user_for_a_user_segment_entry(self):
        comp = self._maven()
        mine = str(comp.install_dir("3.10.0") / "bin")
        self.hkcu["Path"] = (r"C:\other\bin;" + mine, "REG_EXPAND_SZ")
        self.assertEqual(main.shadow_location(r"C:\other\bin"), "user")

    def test_shadow_location_says_outside_when_it_is_in_neither(self):
        self.assertEqual(main.shadow_location(r"Z:\nowhere\bin"), "outside")

    def test_expand_machine_value_follows_nested_placeholders(self):
        """HKLM 那条常写成 %JAVA_HOME%\\bin，而 JAVA_HOME 自己又是 %jdk21%。"""
        self.hklm["JAVA_HOME"] = ("%jdk21%", "REG_EXPAND_SZ")
        self.hklm["jdk21"] = (r"E:\soft\jdk\jdk21", "REG_SZ")
        self.assertEqual(main.expand_machine_value(r"%JAVA_HOME%\bin"),
                         r"E:\soft\jdk\jdk21\bin")
        self.assertIn(r"E:\soft\jdk\jdk21\bin", main.machine_path_entries())

    # ---- 登记表：挑剔的读侧 ----

    def test_machine_fix_map_skips_half_written_entries(self):
        main.CONFIG_FILE.write_text(json.dumps({"machine_fix": {
            "maven": {"home": r"C:\x", "version": "3.10.0", "snapshot": {}},
            "jdk": {"home": r"C:\y", "version": "21",
                    "snapshot": {"HKLM": {"Path": {"raw": "a", "existed": True}}}},
        }}), encoding="utf-8")
        table = main.load_machine_fix_map()
        self.assertNotIn("maven", table,
                         "空 snapshot 的条目必须跳过（半截快照比没有更危险）")
        self.assertIn("jdk", table)

    # ---- 提权生效 ----

    def test_confirm_is_required_before_the_system_path_is_touched(self):
        comp = self._maven()
        before = dict(self.hklm)
        self.install_fake_helper("ok")
        res = main.apply_workspace_machine(comp, "3.10.0",
                                           confirm_machine=lambda plan: False)
        self.assertEqual(res["verdict"], "cancelled")
        self.assertEqual(self.hklm, before, "用户没点确定就不许动系统变量")
        self.assertEqual(self.helper_calls, [], "连助手都不该调用")
        self.assertEqual(main.load_machine_fix_map(), {})

    def test_uac_cancel_leaves_the_system_path_untouched(self):
        comp = self._maven()
        before = dict(self.hklm)
        self.install_fake_helper("cancel")
        res = main.apply_workspace_machine(comp, "3.10.0",
                                           confirm_machine=lambda plan: True)
        self.assertEqual(res["verdict"], "cancelled")
        self.assertEqual(self.hklm, before)
        self.assertEqual(main.load_machine_fix_map(), {})

    def test_machine_fix_coexists_with_active_instead_of_replacing_it(self):
        """与 takeover 的关键区别：生效版本仍是工作区那个，active 不许被清掉。"""
        comp = self._maven()
        main.save_active_version("maven", "3.10.0")
        self.install_fake_helper("ok")
        res = main.apply_workspace_machine(comp, "3.10.0",
                                           confirm_machine=lambda plan: True)
        self.assertTrue(res["ok"], res)
        entry = main.load_machine_fix_map().get("maven")
        self.assertIsNotNone(entry, "要记一笔 machine_fix 作为还原依据")
        self.assertEqual(entry["version"], "3.10.0")
        self.assertIn("HKLM", entry["snapshot"])
        self.assertEqual(main.load_active_map().get("maven"), "3.10.0",
                         "active 必须留着 —— 两条键在这里是并存的")
        self.assertEqual(main.load_takeover_map(), {},
                         "这不是外部接管，不该写 takeover 表")

    def test_failed_verification_rolls_back_and_records_nothing(self):
        comp = self._maven()
        before_path, before_type = self.hklm["Path"]
        self.install_fake_helper("ok")
        # 合成环境里永远有个更靠前的目录抢走 mvn → 复验必然不是 ok
        keep = self.make_home("maven-keep", "mvn.cmd")
        self.composed_is({"PATH": str(keep / "bin") + ";" + self.MAVEN_EXT
                          + ";" + str(comp.install_dir("3.10.0") / "bin")})
        res = main.apply_workspace_machine(comp, "3.10.0",
                                           confirm_machine=lambda plan: True)
        self.assertFalse(res["ok"])
        self.assertEqual(self.hklm["Path"], (before_path, before_type),
                         "复验没过就必须把系统变量还原，绝不报成功")
        self.assertEqual(main.load_machine_fix_map(), {})

    # ---- 还原 ----

    def test_revert_writes_the_original_text_back_and_clears_the_record(self):
        comp = self._maven()
        before_path, before_type = self.hklm["Path"]
        self.install_fake_helper("ok")
        self.assertTrue(main.apply_workspace_machine(
            comp, "3.10.0", confirm_machine=lambda plan: True)["ok"])
        self.assertNotEqual(self.hklm["Path"][0], before_path, "前提：确实改过")
        back = main.revert_machine_fix(comp)
        self.assertTrue(back["ok"], back)
        self.assertEqual(self.hklm["Path"], (before_path, before_type),
                         "还原必须逐字节写回原文（含值类型）")
        self.assertEqual(main.load_machine_fix_map(), {})

    def test_release_before_switch_removes_the_stale_entry(self):
        """切工作区版本前必须先还原，否则系统 PATH 最前留着上一个版本。"""
        comp = self._maven()
        before_path, before_type = self.hklm["Path"]
        self.install_fake_helper("ok")
        main.apply_workspace_machine(comp, "3.10.0",
                                    confirm_machine=lambda plan: True)
        rel = main.release_machine_state(comp, reason="切回工作区版本")
        self.assertTrue(rel["ok"], rel)
        self.assertEqual(self.hklm["Path"], (before_path, before_type))
        self.assertEqual(main.load_machine_fix_map(), {})

    def test_release_before_switch_is_a_noop_without_any_record(self):
        comp = self._maven()
        before = dict(self.hklm)
        rel = main.release_machine_state(comp, reason="切回工作区版本")
        self.assertTrue(rel["ok"])
        self.assertEqual(self.hklm, before)
        self.assertEqual(self.helper_calls, [], "没有欠账就不该有任何提权调用")

    def test_taking_over_another_external_version_releases_the_machine_fix_first(self):
        """两笔账会互相覆盖快照：接管前不还原 machine_fix，注册表就回不到任何一次改动前。"""
        comp = self._maven()
        before_path, before_type = self.hklm["Path"]
        self.install_fake_helper("ok")
        self.assertTrue(main.apply_workspace_machine(
            comp, "3.10.0", confirm_machine=lambda plan: True)["ok"])
        self.assertTrue(main.load_machine_fix_map(), "前提：先有一笔 machine_fix")

        ext = self.make_home("maven-3.9.2-ext", "mvn.cmd")
        main.switch_to_external_version(
            comp, self.dv(ext, "3.9.2", "path:HKLM"),
            confirm_machine=lambda plan: True, log=lambda m: None)
        self.assertEqual(main.load_machine_fix_map(), {},
                         "接管前必须把 machine_fix 还掉，否则两次快照叠加、还原回不到原样")
        self.assertEqual(main.load_takeover_map().get("maven", {}).get("version"),
                         "3.9.2")
        # 反向：把这个接管也还掉，系统 Path 必须逐字节回到最初
        main.revert_external_version(comp, log=lambda m: None)
        self.assertEqual(self.hklm["Path"], (before_path, before_type),
                         "两笔账都还清后，系统 Path 必须与最初逐字节相同")

    # ---- 卡片接线：能自己解决时就别再叫用户自己去改 ----

    def test_card_escalates_when_the_shadow_lives_in_the_system_segment(self):
        comp = self._maven()
        logs: list = []
        _ensure_app()
        self._patch(main.ComponentCard, "_schedule_version_probe",
                    lambda self, exe_path, *a, **k: None)
        self._patch(main.ComponentCard, "_confirm_machine_takeover",
                    lambda self, plan: True)
        self.install_fake_helper("ok")
        card = main.ComponentCard(comp, lambda lvl, msg: logs.append((lvl, msg)))
        card._handle_shadowed_after_switch("3.10.0", self.MAVEN_EXT, 0.0)
        joined = " | ".join(m for _l, m in logs)
        self.assertTrue(any("复验通过" in m for _l, m in logs), joined)
        self.assertEqual(main.load_machine_fix_map().get("maven", {}).get("version"),
                         "3.10.0")
        self.assertNotIn("你自己在「系统变量」", joined,
                         "能自己解决时不许再叫用户自己去改（这是本轮要消灭的那句话）")

    def test_card_does_not_escalate_when_the_user_declines(self):
        comp = self._maven()
        logs: list = []
        _ensure_app()
        self._patch(main.ComponentCard, "_schedule_version_probe",
                    lambda self, exe_path, *a, **k: None)
        self._patch(main.ComponentCard, "_confirm_machine_takeover",
                    lambda self, plan: False)
        self.install_fake_helper("ok")
        before = dict(self.hklm)
        card = main.ComponentCard(comp, lambda lvl, msg: logs.append((lvl, msg)))
        card._handle_shadowed_after_switch("3.10.0", self.MAVEN_EXT, 0.0)
        self.assertEqual(self.hklm, before, "用户拒绝后系统变量必须一字未改")
        self.assertEqual(main.load_machine_fix_map(), {})
        self.assertTrue(any("已取消" in m for _l, m in logs), logs)

    def test_user_segment_shadow_is_fixed_without_elevation(self):
        """用户段内部的先后问题，让位即可 —— 零提权，也不该留提权登记。"""
        comp = self._maven()
        mine = str(comp.install_dir("3.10.0") / "bin")
        other = self.make_home("maven-other", "mvn.cmd")
        self.hkcu["Path"] = (str(other / "bin") + ";" + mine, "REG_EXPAND_SZ")
        self.hklm["Path"] = (r"C:\Windows\system32;C:\Windows", "REG_EXPAND_SZ")
        logs: list = []
        card = self._card(comp, logs)
        card._handle_shadowed_after_switch("3.10.0", str(other / "bin"), 0.0)
        self.assertEqual(self.helper_calls, [], "用户段内部的问题不该提权")
        self.assertEqual(main.load_machine_fix_map(), {})
        self.assertEqual(self.hkcu["Path"][0].split(";")[0], mine,
                         "应把我们那条让到用户段最前")
        self.assertTrue(any("复验通过" in m for _l, m in logs), logs)

    def test_non_whitelisted_component_never_escalates(self):
        """R3.17 的同一道闸：白名单外的组件绝不许弹 UAC 改系统 PATH。"""
        logs: list = []
        card = self._card(self.comp("tomcat"), logs)
        card._handle_shadowed_after_switch("9.0", self.MAVEN_EXT, 0.0)
        self.assertEqual(self.helper_calls, [], "非白名单组件绝不许弹 UAC")
        self.assertEqual(main.load_machine_fix_map(), {})
        self.assertTrue(any(lvl == "warn" for lvl, _m in logs), logs)

    def test_restore_button_shows_up_for_a_machine_fix(self):
        comp = self._maven()
        self.install_fake_helper("ok")
        main.apply_workspace_machine(comp, "3.10.0",
                                    confirm_machine=lambda plan: True)
        card = self._card(comp, [])
        card._refresh_external_section()
        self.assertIsNotNone(card._restore_btn)
        self.assertFalse(card._restore_btn.isHidden(),
                         "动过系统变量就必须常驻还原入口")
        self.assertIn("系统 PATH 最前", card._restore_btn.toolTip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
