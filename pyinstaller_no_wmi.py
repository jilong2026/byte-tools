"""不带 WMI 的 PyInstaller 入口，供「一键打包exe.bat」调用。

PyInstaller 一 `import` 就读 `platform.win32_ver()[0]` 来定 `is_win_10 / is_win_11`，
而 `win32_ver()` 首选 WMI。WINMGMT 冷启动时这条调用**不返回也不报错**
（本机实测：25 秒没回来，热的时候 0.1 秒），现象就是打包脚本跑到
"检查 PyInstaller"之后再无输出。

标准库其实自带不查 WMI 的退路（`sys.getwindowsversion()` + 注册表 CurrentVersion），
只是 `_wmi_query` 卡住而不抛 `OSError`，退路永远走不到。所以这里做两件事：
1. `disable_wmi_lookup()` —— 父进程里把 `_wmi_query` 换成"立刻抛 OSError"；
2. `install_child_bootstrap()` —— 生成一个带 sitecustomize 的目录塞进 PYTHONPATH，
   让**每个子进程**启动时自己装上同一个桩。

第 2 步是必须的：PyInstaller 6.x 的分析跑在 `PyInstaller/isolated/_child.py`
（另起的 python），只桩父进程时实测打包要 2394 秒（子进程排队等冷 WMI），
桩传下去之后是 60 秒级。

两处都**不自己编版本号**：仍由标准库算。本机实测 `win32_ver()`
→ `('11', '10.0.26200', 'SP0', 'Multiprocessor Free')`，与走 WMI 的判据一致。

用法：python pyinstaller_no_wmi.py --noconfirm byte-tools.spec
"""

import os
import platform
import shutil
import sys


def disable_wmi_lookup() -> bool:
    """让 platform 的 WMI 查询立刻失败。返回是否真的换掉了。"""
    if not hasattr(platform, "_wmi_query"):
        return False            # 非 Windows，或该版本 stdlib 不走 WMI
    platform._wmi_query = lambda *args, **kwargs: (_ for _ in ()).throw(
        OSError("打包路径不查 WMI（WINMGMT 冷启动会无限阻塞）"))
    return True


_BOOTSTRAP_SOURCE = '''"""由 pyinstaller_no_wmi.py 生成的启动钩子：每个 python 子进程都会自动执行它。

PyInstaller 6.x 的分析跑在 isolated 子进程里（PyInstaller/isolated/_child.py），
那是另起的一个 python —— 父进程改过的 platform 它看不见，于是子进程又去问冷 WMI，
实测打包耗时从 63 秒涨到 2394 秒。所以桩必须靠 sitecustomize 传下去。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

try:
    import platform
    if hasattr(platform, "_wmi_query"):
        platform._wmi_query = lambda *a, **k: (_ for _ in ()).throw(
            OSError("打包路径不查 WMI（WINMGMT 冷启动会无限阻塞）"))
except Exception:
    pass

# 本目录排在 PYTHONPATH 最前，会盖掉别处已有的 sitecustomize；把那份接着执行掉，
# 不靠它做打包，但也不许悄悄抢掉别人的位置。
try:
    import importlib.util
    for _entry in sys.path:
        if os.path.normcase(_entry) == os.path.normcase(_HERE):
            continue
        _other = os.path.join(_entry, "sitecustomize.py")
        if os.path.isfile(_other):
            _spec = importlib.util.spec_from_file_location("_sitecustomize_chained", _other)
            if _spec and _spec.loader:
                _mod = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
            break
except Exception:
    pass
'''


def install_child_bootstrap(extra_dirs=()) -> str:
    """生成 sitecustomize 注入目录并放进 PYTHONPATH 最前，返回该目录。

    子进程（PyInstaller 的 isolated/_child.py）启动时会自动 import sitecustomize，
    于是桩在**每个**子进程里都生效 —— 这是把打包从 38 分钟拉回 1 分钟的关键一步。
    extra_dirs 只给测试用（验证不会抢掉别人已有的 sitecustomize）。
    """
    import tempfile
    d = os.path.join(tempfile.mkdtemp(prefix="bt_no_wmi_"), "_bootstrap")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "sitecustomize.py"), "w", encoding="utf-8") as f:
        f.write(_BOOTSTRAP_SOURCE)
    parts = [d] + [p for p in extra_dirs if p]
    old = os.environ.get("PYTHONPATH")
    if old:
        parts.append(old)
    os.environ["PYTHONPATH"] = os.pathsep.join(parts)
    return d


def main(argv) -> int:
    disable_wmi_lookup()
    bootstrap_dir = install_child_bootstrap()
    try:
        from PyInstaller.__main__ import run
        run(list(argv))
    finally:
        # 注入目录只在这次构建期间有用，留着会在 %TEMP% 里堆垃圾
        shutil.rmtree(os.path.dirname(bootstrap_dir), ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
