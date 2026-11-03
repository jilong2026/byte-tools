"""Windows 服务（SCM）只读查询与提权写操作（从 main.py 抽出）。

设计约束（与抽取前逐字一致，见 DEVELOPMENT.md R5）：
- 状态识别只读 SCM / 注册表，绝不执行、绝不启停；
- 启停是唯一写入口，且启动必须走 StartServiceW（ControlService 传
  SERVICE_START 会回 87，2026-10-29 真机踩过）；
- 整个对象可被测试替换成内存实现，所以 main 只持有 SERVICE_BACKEND 变量。

``current_os`` 显式注入（main 传自己的 CURRENT_OS），避免本模块引入
platform/WMI 探测 —— 那在冷启动时会阻塞。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

SERVICE_NAME_RE = re.compile(r"^ByteTools-(?:MySQL|Redis)-[0-9A-Za-z][0-9A-Za-z._-]*$")

SERVICE_MISSING = "not_installed"
SERVICE_STOPPED = "stopped"
SERVICE_RUNNING = "running"
SERVICE_PENDING = "pending"       # 起停过渡态；error=1060 时表示"标记为删除中"
SERVICE_BROKEN = "broken"         # 服务还在，但它指的可执行文件已经不在了

# SCM 的 dwCurrentState → 四态。暂停按运行中算：它确实还在占着资源，
# 再点一次「启动」只会被 SCM 拒绝（1056 服务已在运行）。
_SCM_STATE_NAMES = {
    1: SERVICE_STOPPED, 2: SERVICE_PENDING, 3: SERVICE_PENDING, 4: SERVICE_RUNNING,
    5: SERVICE_PENDING, 6: SERVICE_PENDING, 7: SERVICE_RUNNING,
}

ERROR_SERVICE_DOES_NOT_EXIST = 1060
ERROR_SERVICE_MARKED_FOR_DELETE = 1072
ERROR_ACCESS_DENIED = 5
ERROR_SERVICE_ALREADY_RUNNING = 1056

SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONTROL_CONTINUE = 0x00000003


@dataclass
class ServiceInfo:
    """一次 SCM 查询的结论（只读，不含任何动作）。"""

    name: str = ""
    exists: bool = False
    state: str = SERVICE_MISSING
    image_path: str = ""
    start_type: str = ""          # auto / demand / disabled
    error: int = 0

    @property
    def running(self) -> bool:
        return self.state == SERVICE_RUNNING


def _image_exe_path(image: str) -> str:
    """从服务的 ImagePath 里取出可执行文件路径。

    写法有两种：`"C:\\a b\\x.exe" --flag` 与 `C:\\a\\x.exe --flag`。
    取不出来就返回空串（调用方据此跳过"exe 还在不在"的检查，而不是误判损坏）。
    """
    text = (image or "").strip()
    if not text:
        return ""
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end > 0 else text[1:]
    low = text.lower()
    for marker in (" --", " /"):
        pos = low.find(marker)
        if pos > 0:
            return text[:pos]
    return text


def _scm_api():
    """打开 advapi32 并配好 argtypes。

    **argtypes 不能省**：HANDLE 在 64 位上是指针宽度，不声明时 ctypes 会按 C int
    传，句柄被截断成 32 位，OpenService 于是随机失败。
    """
    import ctypes
    from ctypes import wintypes

    class _Status(ctypes.Structure):
        _fields_ = [("dwServiceType", wintypes.DWORD),
                    ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD),
                    ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD),
                    ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD),
                    ("dwProcessId", wintypes.DWORD),
                    ("dwServiceFlags", wintypes.DWORD)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.OpenSCManagerW.restype = wintypes.HANDLE
    advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    advapi32.OpenServiceW.restype = wintypes.HANDLE
    advapi32.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    advapi32.CloseServiceHandle.restype = wintypes.BOOL
    advapi32.QueryServiceStatusEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    advapi32.QueryServiceStatusEx.restype = wintypes.BOOL
    advapi32.ControlService.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    advapi32.ControlService.restype = wintypes.BOOL
    # 启动**不能**走 ControlService：SERVICE_START(0x10) 不是控制码。
    advapi32.StartServiceW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.LPCWSTR)]
    advapi32.StartServiceW.restype = wintypes.BOOL
    return advapi32, _Status, ctypes, wintypes


def _reg_scalar(key, name: str):
    import winreg

    try:
        value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, int) else str(value)


class WindowsServiceBackend:
    """SCM 只读查询 + 提权写操作。整个对象可被测试替换成内存实现。"""

    def __init__(self, current_os: Optional[str] = None) -> None:
        # 不写死 platform.system()：main 那边已经有免 WMI 的 CURRENT_OS
        self._current_os = current_os

    def supported(self) -> bool:
        if self._current_os is not None:
            return self._current_os == "Windows"
        return os.name == "nt"

    @staticmethod
    def _validate(name: str) -> None:
        if not SERVICE_NAME_RE.match(name or ""):
            raise ValueError(f"非法的服务名：{name!r}")

    def query(self, name: str) -> ServiceInfo:
        info = ServiceInfo(name=name)
        if not self.supported():
            return info
        self._validate(name)
        image, start_type = self._read_config(name)
        if image is None and start_type is None:
            return info
        info.exists = True
        info.image_path = image or ""
        info.start_type = start_type or ""
        exe = os.path.expandvars(_image_exe_path(image or ""))
        if exe and not Path(exe).exists():
            info.state = SERVICE_BROKEN
            return info
        state, err = self._scm_state(name)
        info.error = err
        # 1060：注册表键还在、SCM 已经不认它了 —— 正是"标记为删除"的样子。
        info.state = (SERVICE_PENDING if err in (ERROR_SERVICE_DOES_NOT_EXIST,
                                                 ERROR_SERVICE_MARKED_FOR_DELETE)
                      else _SCM_STATE_NAMES.get(state, SERVICE_PENDING))
        return info

    def registry_key_exists(self, name: str) -> bool:
        image, start_type = self._read_config(name)
        return image is not None or start_type is not None

    def start(self, name: str) -> int:
        """启动服务，返回 win32 错误码（0 = 成功）。"""
        if not self.supported():
            return ERROR_ACCESS_DENIED
        self._validate(name)
        advapi32, _Status, ctypes, wintypes = _scm_api()
        scm = advapi32.OpenSCManagerW(None, None, 0x0001)      # SC_MANAGER_CONNECT
        if not scm:
            return ctypes.get_last_error()
        try:
            svc = advapi32.OpenServiceW(scm, name, 0x0010 | 0x0004)   # START | QUERY_STATUS
            if not svc:
                return ctypes.get_last_error()
            try:
                if not advapi32.StartServiceW(svc, 0, None):
                    return ctypes.get_last_error()
                return 0
            finally:
                advapi32.CloseServiceHandle(svc)
        finally:
            advapi32.CloseServiceHandle(scm)

    def control(self, name: str, code: int) -> int:
        """向 SCM 发**控制码**（停/暂停/继续），返回 win32 错误码（0 = 成功）。

        只接受控制码；`SERVICE_START` 这类启动请求必须走 start()。
        """
        if not self.supported():
            return ERROR_ACCESS_DENIED
        self._validate(name)
        if code == 0x0010:
            raise ValueError("启动服务请调用 start()，ControlService 不接受 SERVICE_START")
        advapi32, _Status, ctypes, wintypes = _scm_api()
        scm = advapi32.OpenSCManagerW(None, None, 0x0001)      # SC_MANAGER_CONNECT
        if not scm:
            return ctypes.get_last_error()
        try:
            access = 0x0020 | 0x0004 | 0x0001                  # START | QUERY_STATUS | STOP
            svc = advapi32.OpenServiceW(scm, name, access)
            if not svc:
                return ctypes.get_last_error()
            try:
                status = _Status()
                if not advapi32.ControlService(svc, code, ctypes.byref(status)):
                    return ctypes.get_last_error()
                return 0
            finally:
                advapi32.CloseServiceHandle(svc)
        finally:
            advapi32.CloseServiceHandle(scm)

    # --- 只读底层 -------------------------------------------------------
    @staticmethod
    def _read_config(name: str) -> Tuple[Optional[str], object]:
        import winreg

        path = rf"SYSTEM\CurrentControlSet\Services\{name}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                image = _reg_scalar(key, "ImagePath")
                start = _reg_scalar(key, "Start")
                start_type = {2: "auto", 3: "demand", 4: "disabled"}.get(start, "")
                return image, start_type
        except OSError:
            return None, None

    @staticmethod
    def _scm_state(name: str) -> Tuple[int, int]:
        if os.name != "nt":
            return -1, ERROR_ACCESS_DENIED
        advapi32, _Status, ctypes, wintypes = _scm_api()
        scm = advapi32.OpenSCManagerW(None, None, 0x0001)
        if not scm:
            return -1, ctypes.get_last_error()
        try:
            svc = advapi32.OpenServiceW(scm, name, 0x0004)     # SERVICE_QUERY_STATUS
            if not svc:
                return -1, ctypes.get_last_error()
            try:
                buf = _Status()
                needed = wintypes.DWORD(0)
                if not advapi32.QueryServiceStatusEx(
                        svc, 0, ctypes.byref(buf), ctypes.sizeof(buf), ctypes.byref(needed)):
                    return -1, ctypes.get_last_error()
                return int(buf.dwCurrentState), 0
            finally:
                advapi32.CloseServiceHandle(svc)
        finally:
            advapi32.CloseServiceHandle(scm)
