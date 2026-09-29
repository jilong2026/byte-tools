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
import subprocess
import sys
import unittest

REPO_ROOT = r"E:\file\test\byte-tools"
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
        if platform.system() != "Windows":
            self.skipTest("只在 Windows 上有 PROCESSOR_ARCHITECTURE 可验")
        self.assertEqual(main.CURRENT_OS, "Windows")
        self.assertEqual(main._machine_name(),
                         os.environ["PROCESSOR_ARCHITECTURE"].lower())
        self.assertIn(main.MACHINE, {"amd64", "arm64", "x86"})


if __name__ == "__main__":
    unittest.main()
