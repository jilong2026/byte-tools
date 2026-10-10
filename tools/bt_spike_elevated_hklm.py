"""技术验证（spike）：提权改系统环境变量这条路到底走不走得通。

要回答的问题只有一个：能不能做到「提权 → 最小编辑 HKLM 的 Path → 校验 → 让新进程真的
看到 → 逐字节还原」，任何一环做不到，"切换用户自装版本"这个功能就应当降级为
"只写用户级 + 明确告诉用户去系统变量里改哪一条"，而不是硬上。

安全设计（这个脚本刻意做到）：
  · 只往系统 Path **最前面插一条空目录**（里面没有任何可执行文件）——即使还原失败，
    也不会让任何命令指错地方，最坏是多一条无害条目。
  · 动手前把原始**未展开**字符串连同 sha256 备份到 %TEMP%，还原后比对 sha256。
  · 助手进程写完自己校验：关键条目（system32 / Windows）还在、条目数没少、
    类型仍是 REG_EXPAND_SZ；任一不满足就**立刻自己回滚**。
  · 全程不碰 WMI（这台机器 WINMGMT 冷启动会无限阻塞）。

用法：
    .venv/Scripts/python.exe bt_spike_elevated_hklm.py --dry      # 只跑纯函数校验，不弹窗不写盘
    .venv/Scripts/python.exe bt_spike_elevated_hklm.py            # 真验证：会弹 2 次 UAC
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

# 本脚本住在 tools/ 下：把仓库根加进 sys.path，函数里的 `import main` 才找得到
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REG_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
SPIKE_DIR_NAME = "bt_spike_empty_dir"
KEY_SUBSTRINGS = ("system32", os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), ""))


# ----------------------------------------------------------- 纯函数（可离线验）


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-16-le")).hexdigest()


def build_new_raw(original_raw: str, insert_dir: str) -> str:
    """在原文最前面加一条，其余**逐字保留**（含 %VAR% 这种未展开写法）。"""
    parts = [p for p in original_raw.split(";")]
    return ";".join([insert_dir] + parts)


def validate_raw(before: str, after: str, insert_dir: str) -> list:
    """改完的自检：返回问题列表，空列表 = 通过。"""
    problems = []
    b, a = before.split(";"), after.split(";")
    if len(a) != len(b) + 1:
        problems.append(f"条目数不对：改前 {len(b)} 条，改后 {len(a)} 条（应当只多 1 条）")
    if a[1:] != b:
        problems.append("原有条目没有逐字保留（顺序或文本被改动了）")
    if a[0] != insert_dir:
        problems.append(f"新条目没在最前面：实际第一条是 {a[0]!r}")
    low = after.lower()
    for needle in KEY_SUBSTRINGS:
        if needle and needle.lower() not in low:
            problems.append(f"关键条目丢失：{needle}")
    return problems


# ----------------------------------------------------------- 注册表读写


def read_raw() -> tuple:
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY, 0,
                        winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
        value, reg_type = winreg.QueryValueEx(k, "Path")
    return value, reg_type


def write_raw(value: str) -> None:
    """写回系统 Path。必须显式 REG_EXPAND_SZ，否则 %JAVA_HOME% 这类会被写死成展开值。"""
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY, 0,
                        winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, value)


# ----------------------------------------------------------- 助手进程（提权侧）


def helper(mode: str, payload: str, result_path: str) -> int:
    """以管理员身份被拉起时跑的那一半：写 / 还原，并自带校验与自动回滚。"""
    report: dict = {"mode": mode, "ok": False, "steps": []}
    try:
        before, rtype = read_raw()
        report["type_before"] = rtype
        if mode == "apply":
            intended = build_new_raw(before, payload)
            write_raw(intended)
            report["steps"].append("写入完成")
            after, rtype_after = read_raw()
            report["type_after"] = rtype_after
            problems = validate_raw(before, after, payload)
            if rtype_after != 2:      # REG_EXPAND_SZ
                problems.append(f"类型被改掉了：应为 REG_EXPAND_SZ(2)，实际 {rtype_after}")
            if problems:
                write_raw(before)     # 立刻自己回滚
                report["steps"].append("自检未过，已自动回滚：" + "；".join(problems))
                report["problems"] = problems
            else:
                report["ok"] = True
        else:                          # restore
            write_raw(payload)
            after, _ = read_raw()
            report["ok"] = (after == payload)
            report["steps"].append("还原" + ("成功" if report["ok"] else "后读回不一致"))
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False)
        return 0 if report["ok"] else 2
    except Exception as exc:           # noqa: BLE001
        report["error"] = repr(exc)
        try:
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False)
        except Exception:              # noqa: BLE001
            pass
        return 3


def run_elevated(mode: str, payload: str) -> dict:
    """用 runas 拉起自己当助手，等它写结果文件。返回它的报告；取消/失败返回 ok=False。"""
    u32 = ctypes.windll.shell32
    py = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(py):
        py = sys.executable
    result_path = os.path.join(tempfile.gettempdir(), f"bt_spike_result_{int(time.time())}.json")
    params = f'"{os.path.abspath(__file__)}" --helper {mode} "{payload}" "{result_path}"'
    SE_ERR_NO_HKEY = 2
    rc = u32.ShellExecuteW(0, "runas", py, params, None, 0)   # 0 = SW_HIDE
    if int(rc) <= 32:
        why = {1223: "用户在 UAC 里点了「否」（取消）", 5: "被拒绝访问",
               SE_ERR_NO_HKEY: "没有关联程序"}.get(int(rc), f"ShellExecute 返回 {rc}")
        return {"ok": False, "steps": [], "error": why}
    for _ in range(240):                                       # 最多等 2 分钟
        if os.path.exists(result_path):
            time.sleep(0.4)                                    # 等它写完整
            try:
                return json.load(open(result_path, encoding="utf-8"))
            except Exception:                                   # noqa: BLE001
                pass
        time.sleep(0.5)
    return {"ok": False, "error": "助手进程 2 分钟内没交回结果（可能 UAC 没点）"}


# ----------------------------------------------------------- 观测手段


def composed_path_first_entry() -> str:
    import main
    env = main.EnvManager.composed_env()
    return (env.get("PATH") or "").split(";")[0]


def shell_probe_first_entry() -> str:
    """让 explorer 现场开一个进程，问它 PATH 的第一条 —— 用户新开终端的真实视角。"""
    d = os.path.join(tempfile.gettempdir(), "bt_spike_probe")
    os.makedirs(d, exist_ok=True)
    bat, out = os.path.join(d, "p.bat"), os.path.join(d, "o.txt")
    if os.path.exists(out):
        os.remove(out)
    q = '"' + out + '"'
    open(bat, "wb").write(("\r\n".join(
        ["@echo off", "echo FIRST=%PATH:~0,80%> " + q, "echo __END__>> " + q]
    ) + "\r\n").encode("utf-8"))
    subprocess.run(["explorer.exe", bat])
    for _ in range(30):
        if os.path.exists(out) and "__END__" in open(out, encoding="mbcs", errors="replace").read():
            txt = open(out, encoding="mbcs", errors="replace").read()
            return txt.split("FIRST=")[1].split("\r\n")[0][:80]
        time.sleep(0.5)
    return "(探针没跑起来)"


def notify_shell() -> bool:
    import main
    return main.notify_shell_environment()


# ----------------------------------------------------------- 主流程


def dry_run() -> int:
    raw, rtype = read_raw()
    print(f"系统 Path 原文（未展开）共 {len(raw)} 字符、{len(raw.split(';'))} 条，类型 = {rtype}")
    print("含未展开变量引用：", [p for p in raw.split(";") if "%" in p])
    spike = os.path.join(tempfile.gettempdir(), SPIKE_DIR_NAME)
    new = build_new_raw(raw, spike)
    print("build_new_raw 后条目数 =", len(new.split(";")), "（应比原来多 1）")
    print("自检（正常情形）问题 =", validate_raw(raw, new, spike) or "无")
    broken = new.replace("system32", "XXXXXX")
    print("自检（故意破坏 system32）问题 =", validate_raw(raw, broken, spike) or "无 ← 这就是 FAIL")
    untouched = validate_raw(raw, raw, spike)
    print("自检（什么都没改）问题 =", untouched or "无")
    ok = (not validate_raw(raw, new, spike)) and validate_raw(raw, broken, spike) and untouched
    print("\n纯函数部分：", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def full_run() -> int:
    spike = os.path.join(tempfile.gettempdir(), SPIKE_DIR_NAME)
    os.makedirs(spike, exist_ok=True)          # 空目录：不放任何可执行文件
    raw0, type0 = read_raw()
    backup = os.path.join(tempfile.gettempdir(), "bt_spike_backup_path.txt")
    open(backup, "wb").write(raw0.encode("utf-8"))
    print(f"[0] 基线：{len(raw0.split(';'))} 条，类型={type0}，sha256={sha256(raw0)[:16]}")
    print(f"    备份已写到 {backup}")
    print(f"    要插入的空目录 = {spike}")

    print("\n[1] 提权写入（会弹第 1 次 UAC，请点「是」）…")
    rep = run_elevated("apply", spike)
    print("    助手报告：", rep.get("steps") or rep.get("error"))
    if not rep.get("ok"):
        print("\n结论：提权写入这一环做不到 —— 功能必须降级。")
        return 1

    first_composed = composed_path_first_entry()
    print(f"[2] 新进程合成环境里 PATH 第一条 = {first_composed}")
    print(f"    → {'PASS' if first_composed.strip().lower() == spike.lower() else 'FAIL（没排在最前）'}")
    notify_shell()
    probe = shell_probe_first_entry()
    print(f"[3] explorer 现场探针看到的 PATH 开头 = {probe}")

    print("\n[4] 提权还原（会弹第 2 次 UAC，请点「是」）…")
    rep2 = run_elevated("restore", raw0)
    print("    助手报告：", rep2.get("steps") or rep2.get("error"))
    raw1, type1 = read_raw()
    same = (raw1 == raw0) and (type1 == type0) and (sha256(raw1) == sha256(raw0))
    print(f"[5] 还原后 sha256={sha256(raw1)[:16]} 类型={type1} → {'PASS 逐字节一致' if same else 'FAIL 与基线不一致！'}")
    if not same:
        print("    立刻手工还原：管理员 CMD 执行  "
              f'setx /M Path 见备份 {backup}（或把该文件内容粘回系统变量的 Path）')

    ok = same and first_composed.strip().lower() == spike.lower()
    print("\n" + "=" * 70)
    print("技术验证结论：", "提权接管这条路可行（写入生效 + 逐字节还原）" if ok
          else "有问题，见上面 FAIL 项")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    if "--helper" in sys.argv:
        i = sys.argv.index("--helper")
        raise SystemExit(helper(sys.argv[i + 1], sys.argv[i + 2], sys.argv[i + 3]))
    raise SystemExit(dry_run() if "--dry" in sys.argv else full_run())
