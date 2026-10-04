"""启动期健壮性：import main 不许碰 WMI。

起因（2026-09-30 实测）：`一键启动项目.bat` 与 `一键打包exe.bat` "执行一半卡住不动"，
faulthandler 打出的阻塞栈是
    main.py:107 platform.system()
      -> platform.uname() -> win32_ver() -> _wmi_query()   # 永久阻塞
WINMGMT 冷启动时这条 WMI 查询能卡几十秒到一两分钟（预热后同一调用 0.6 秒）。
一个"挑下载包用哪个架构"的判断不该把整个程序锁在系统服务上。

跑法：.venv/Scripts/python.exe -u bt_startup_tests.py
"""
import os
import platform
import shutil
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# 子进程里用：把 platform 的探测函数全部换成"一调就炸"，再 import main
PROBE_CHILD = """
import sys, platform

def _make(name):
    def _boom(*a, **k):
        raise AssertionError("启动期调用了 " + name)
    return _boom

for _n in ("system", "machine", "uname", "win32_ver", "freedesktop_linux"):
    if hasattr(platform, _n):
        setattr(platform, _n, _make("platform." + _n))

sys.path.insert(0, r"{repo}")
import main
print("CHILD_OK", main.CURRENT_OS, main.MACHINE, main.IS_ARM)
""".format(repo=REPO_ROOT)


def _wmi_warm(timeout_sec: int = 10) -> bool:
    """有界判断本机 WMI 现在能不能答话（daemon 线程 + 超时，绝不把测试拖挂）。"""
    import threading
    box = {}

    def _run():
        try:
            box["ok"] = bool(platform.win32_ver()[0])
        except Exception:
            box["ok"] = True        # 报错也算"能答话"：快速失败远好过卡死

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_sec)
    return bool(box.get("ok")) if not t.is_alive() else False


class StartupNoWmi(unittest.TestCase):
    def test_import_main_never_calls_platform_probe(self):
        """RED 的判据：只要 import main 期间调了 platform.system/machine/uname 就炸。"""
        env = dict(os.environ)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        proc = subprocess.run([sys.executable, "-c", PROBE_CHILD],
                              capture_output=True, text=True, timeout=120, env=env,
                              cwd=REPO_ROOT)
        tail = (proc.stdout + proc.stderr)[-800:]
        self.assertEqual(proc.returncode, 0, f"import main 仍需 platform 探测：\n{tail}")
        self.assertIn("CHILD_OK", proc.stdout)

    def test_derived_os_and_machine_equal_platform_answers(self):
        """不依赖 WMI 的推导结果，必须和 platform 的原答案一致（换汤不换药）。

        platform.system()/machine() 自己要走 WMI，WINMGMT 冷启动时它会卡几十秒，
        所以这里先有界探一次：探不通就跳过对照，不让整个套件挂在系统服务上。
        """
        if not _wmi_warm(timeout_sec=10):
            self.skipTest("本机 WMI 冷启动未响应，platform.* 的对照值取不到")
        import main
        self.assertEqual(main.CURRENT_OS, platform.system())
        self.assertEqual(main.MACHINE, platform.machine().lower())
        self.assertEqual(main.IS_ARM,
                         ("arm" in main.MACHINE) or ("aarch64" in main.MACHINE))

    def test_windows_derivation_uses_env_not_wmi(self):
        """Windows 分支：架构取自环境变量，且不受 platform 影响。"""
        import main
        # 这里绝不能用 platform.system() 判平台：它内部就是 WMI，冷启动时本用例会
        # 永久挂住（正是本文件要防的那件事，我自己先踩了一遍）
        if sys.platform != "win32":
            self.skipTest("只在 Windows 上有 PROCESSOR_ARCHITECTURE 可验")
        self.assertEqual(main.CURRENT_OS, "Windows")
        self.assertEqual(main._machine_name(),
                         os.environ["PROCESSOR_ARCHITECTURE"].lower())
        self.assertIn(main.MACHINE, {"amd64", "arm64", "x86"})


class PackagingEntryNoWmi(unittest.TestCase):
    """打包入口必须不碰 WMI：PyInstaller 一 import 就读 win32_ver()[0]。

    2026-09-30 本机实测 `platform._wmi_query` 25 秒不返回（预热后 0.6 秒），
    打包脚本因此"跑到检查 PyInstaller 之后再无输出"。修法不是等它，而是让
    `_wmi_query` 立刻抛 OSError，走标准库自带的非 WMI 退路。
    """

    def setUp(self):
        import pyinstaller_no_wmi
        self.mod = pyinstaller_no_wmi
        self._orig = getattr(platform, "_wmi_query", None)

    def tearDown(self):
        if self._orig is not None:
            platform._wmi_query = self._orig

    def _win32_ver_bounded(self, seconds: float = 3.0):
        import threading
        box = {}

        def _run():
            try:
                box["v"] = platform.win32_ver()
            except Exception as exc:            # noqa: BLE001
                box["e"] = exc

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(seconds)
        self.assertFalse(t.is_alive(),
                         f"换掉 _wmi_query 后 win32_ver() 仍然阻塞 >{seconds}s")
        return box.get("v")

    def test_disable_actually_replaces_the_wmi_probe(self):
        if sys.platform != "win32":
            self.skipTest("_wmi_query 只在 Windows 上存在")
        self.assertTrue(self.mod.disable_wmi_lookup(), "没换掉任何函数 = 这个护栏是空的")
        self.assertIsNot(platform._wmi_query, self._orig)
        with self.assertRaises(OSError):
            platform._wmi_query("OS", "Version")

    def test_win32_ver_answers_fast_and_non_empty_after_the_swap(self):
        if sys.platform != "win32":
            self.skipTest("win32_ver 只在 Windows 上有意义")
        self.mod.disable_wmi_lookup()
        got = self._win32_ver_bounded()
        self.assertIsNotNone(got, "标准库退路没走通")
        self.assertIn(got[0], {"10", "11", "post11"}, f"PyInstaller 的判据要的是大版本，实际 {got}")

    def test_release_is_the_same_the_stdlib_table_gives(self):
        """不许自己编版本号：换掉 WMI 后的答案必须与标准库那张表算出来的一致。"""
        if sys.platform != "win32":
            self.skipTest("只在 Windows 上验")
        self.mod.disable_wmi_lookup()
        got = self._win32_ver_bounded()
        v = sys.getwindowsversion()
        intversion = (v.major, v.minor, v.build)
        is_client = getattr(v, "product_type", 1) == 1
        table = platform._WIN32_CLIENT_RELEASES if is_client else platform._WIN32_SERVER_RELEASES
        want = next((r for ver, r in table if ver <= intversion), "")
        self.assertEqual(got[0], want,
                         f"应当由标准库的表判版本，实际 got={got[0]!r} want={want!r}")


class PackagingChildProcessesNoWmi(unittest.TestCase):
    """桩必须传进 PyInstaller 的 isolated 子进程，只桩父进程等于没做。

    2026-09-30 真机实测：只桩父进程时打包耗时 2394 秒（38.7 分钟）才跑完，
    而 WMI 已热的情况下原版只要 63 秒 —— 差距全在子进程排队等冷 WMI 上。
    子进程是 `PyInstaller/isolated/_child.py`，另起的一个 python，
    父进程里改过的 platform 它看不见。
    """

    CHILD = (
        "import platform, time\n"
        "try:\n"
        "    platform._wmi_query('OS', 'Version')\n"
        "    print('WMI_NOT_STUBBED')\n"
        "except OSError:\n"
        "    print('WMI_FAILS_FAST')\n"
        "t0 = time.time()\n"
        "rel = platform.win32_ver()[0]\n"
        "print('RELEASE', rel, round(time.time() - t0, 2))\n"
        "import os\n"
        "print('CHAINED', os.environ.get('BT_CHAIN_MARKER', 'no'))\n"
    )

    def setUp(self):
        import pyinstaller_no_wmi
        self.mod = pyinstaller_no_wmi
        self._orig_pp = os.environ.get("PYTHONPATH")

    def tearDown(self):
        if self._orig_pp is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = self._orig_pp

    def _run_child(self):
        return subprocess.run([sys.executable, "-c", self.CHILD],
                              capture_output=True, text=True, timeout=60,
                              env=os.environ.copy(), cwd=REPO_ROOT)

    def _bootstrap(self, extra_dirs=()):
        d = self.mod.install_child_bootstrap(extra_dirs=extra_dirs)
        # 不收拾的话每跑一次测试就在 %TEMP% 留一个注入目录
        self.addCleanup(shutil.rmtree, os.path.dirname(d), True)
        return d

    def test_without_the_bootstrap_a_child_still_asks_wmi(self):
        """对照组：不注入时子进程拿到的是标准库原函数（会真去问 WMI）。"""
        if sys.platform != "win32":
            self.skipTest("只在 Windows 上验")
        out = self._run_child().stdout
        self.assertIn("WMI_NOT_STUBBED", out,
                      f"对照组应当是「没桩」，实际输出：{out!r}")

    def test_bootstrap_makes_childs_wmi_probe_fail_fast(self):
        if sys.platform != "win32":
            self.skipTest("只在 Windows 上验")
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self._bootstrap(extra_dirs=[td])
            out = self._run_child().stdout
        self.assertIn("WMI_FAILS_FAST", out,
                      f"子进程里 WMI 查询必须立刻失败，实际：{out!r}")
        line = [l for l in out.splitlines() if l.startswith("RELEASE")]
        self.assertTrue(line and line[0].split()[1] in {"10", "11", "post11"},
                        f"版本号仍要算得出来，实际：{out!r}")
        self.assertLess(float(line[0].split()[2]), 5.0,
                        "子进程算版本号不该等 WMI")

    def test_bootstrap_does_not_shadow_an_existing_sitecustomize(self):
        """注入目录排最前，必须把别人原有的 sitecustomize 接着执行掉。"""
        if sys.platform != "win32":
            self.skipTest("只在 Windows 上验")
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "sitecustomize.py"), "w", encoding="utf-8") as f:
                f.write("import os\nos.environ['BT_CHAIN_MARKER'] = 'yes'\n")
            self._bootstrap(extra_dirs=[td])
            out = self._run_child().stdout
        self.assertIn("CHAINED yes", out,
                      f"别人的 sitecustomize 被我们抢掉了，实际：{out!r}")


if __name__ == "__main__":
    unittest.main()
