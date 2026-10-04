r"""一键脚本护栏：编码、换行、消息表、Python 自动安装闭环。

起因（2026-10-05 本机实测）：`一键启动项目.bat` / `一键打包exe.bat` 是 UTF-8 无 BOM
且含中文，脚本第 2 行又 `chcp 65001`。cmd.exe 用字节偏移量记录它读批处理的位置，
码页中途一变、行内又有多字节字符时，这个偏移会错位，于是从**行的中间**开始解析：
REM 注释和 echo 文案被当成命令执行，整条语句被吞掉。同一份内容转成纯 ASCII（保留
chcp 65001）或转成 GBK+chcp 936，异常都是 0 行；原文件跑出 7 行
「'xxx' is not recognized as an internal or external command」。

被吞掉的正好是 `:bootstrap_python` 后半段（下载官方安装包 -> 静默安装 -> 重扫），
所以"没装 Python 的机器双击脚本"直接掉到 `:err_no_python`，而那段文案写的是
"方式一 winget install / 方式二 去 python.org 下载" —— 用户看到的"让我自己配环境"
就是这么来的。修法：脚本本体永远纯 ASCII，中文当数据放在 assets\msg_zh.txt。

跑法：.venv/Scripts/python.exe -u bt_boot_script_tests.py
"""
import io
import os
import re
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

BATS = ("一键启动项目.bat", "一键打包exe.bat")
MSG_FILE = os.path.join(REPO_ROOT, "assets", "msg_zh.txt")

# 可能被 PATH 上的 .bat/.cmd 垫片顶替的外部命令：Anaconda / scoop 一类发行版真的会
# 放 python.bat。批处理里不带 call 调用另一个批处理，控制权不再返回调用方，整个脚本
# 就地终止（本机用 stub/winget.bat 复现过：脚本打印完"正在用 winget 静默安装"就没了）。
SHIM_PRONE = (
    '"%WINGET_EXE%" ',
    '"%PY_SETUP%" ',
    "%BASE_PY% ",
    "%~1 -c ",
    '"%~1" -c ',
    '"%VENV_PY%" -c ',
    '"%RUN_PY%" ',
    "curl -fL ",
    "powershell -NoProfile ",
)

SAY_RE = re.compile(r'call :say (\w+) "([^"]*)"(?: "([^"]*)")?')


def read_bat(name):
    with io.open(os.path.join(REPO_ROOT, name), "rb") as fh:
        raw = fh.read()
    return raw.decode("ascii").split("\r\n")


def say_calls():
    """yield (脚本名, 行号, 匹配)。注意匹配要搜整行：
    `if defined BASE_PY call :say ...` 这类行开头不是 call。"""
    for name in BATS:
        for i, line in enumerate(read_bat(name)):
            m = SAY_RE.search(line)
            if m:
                yield name, i + 1, m


class BatMustStayAscii(unittest.TestCase):
    """解析错位的根因是非 ASCII 字节进了 .bat，这一条是整套修法的地板。"""

    def test_no_non_ascii_bytes(self):
        for name in BATS:
            with io.open(os.path.join(REPO_ROOT, name), "rb") as fh:
                raw = fh.read()
            offenders = sorted({b for b in raw if b > 0x7F})
            self.assertEqual(offenders, [], f"{name} 含非 ASCII 字节 {offenders[:8]}，"
                                            "cmd 会按字节偏移错位解析，语句会被整段吞掉")

    def test_crlf_and_no_bom(self):
        for name in BATS:
            with io.open(os.path.join(REPO_ROOT, name), "rb") as fh:
                raw = fh.read()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{name} 不许有 BOM")
            self.assertEqual(raw.count(b"\n") - raw.count(b"\r\n"), 0,
                             f"{name} 有裸 LF：LF -only 的批处理会让标签查找失败"
                             "（本机实测报 cannot find the batch label specified）")


class MessageTable(unittest.TestCase):
    def setUp(self):
        with io.open(MSG_FILE, "rb") as fh:
            self.raw = fh.read()
        self.text = self.raw.decode("utf-8")
        self.entries = {}
        for line in self.text.split("\n"):
            line = line.strip("\r")
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            self.entries[key.strip()] = value

    def test_lf_only(self):
        """for /f 会把 CRLF 的 CR 留在值里，echo 再补一个，每条消息多出一次回车。"""
        self.assertNotIn(b"\r", self.raw, "assets/msg_zh.txt 必须是 LF 结尾")

    def test_values_have_no_bang(self):
        bad = [k for k, v in self.entries.items() if "!" in v]
        self.assertEqual(bad, [], f"{bad} 含 '!'：延迟展开会吃掉它")

    def test_every_referenced_key_exists(self):
        used = {m.group(1) for _, _, m in say_calls()}
        self.assertTrue(used, "一个 :say 调用都没解析到，本用例是空的")
        self.assertEqual(sorted(used - set(self.entries)), [],
                         "脚本引用了消息表里没有的 key")

    def test_no_dead_message(self):
        used = {m.group(1) for _, _, m in say_calls()}
        dead = sorted(set(self.entries) - used)
        self.assertEqual(dead, [], "消息表里有脚本没用的条目，要么接上要么删掉")

    def test_english_fallback_free_of_metacharacters(self):
        """英文兜底是在解析期插进命令行的 %~2，含 cmd 元字符会改变语句结构。"""
        for name, n, m in say_calls():
            bad = sorted(set(c for c in m.group(2) if c in '&|<>()^"'))
            self.assertEqual(bad, [], f"{name}:{n} 英文兜底含元字符 {bad}：{m.group(2)!r}")

    def test_placeholder_count_matches(self):
        for name, n, m in say_calls():
            has_arg = m.group(3) is not None
            in_en = "{0}" in m.group(2)
            in_cn = "{0}" in self.entries.get(m.group(1), "")
            self.assertEqual(in_en, has_arg,
                             f"{name}:{n} {m.group(1)} 英文文案与实参不匹配")
            self.assertEqual(in_cn, has_arg,
                             f"消息表里 {m.group(1)} 的 {{0}} 与脚本传参不匹配")


class BootstrapChainPresent(unittest.TestCase):
    """一键契约：机器上没有 Python 时，脚本自己装，不许把手动步骤当成方案。"""

    def setUp(self):
        self.lines = {name: read_bat(name) for name in BATS}

    def _body(self, name):
        return "\r\n".join(self.lines[name])

    def test_both_scripts_have_the_same_chain(self):
        for name in BATS:
            body = self._body(name)
            for label in (":detect_lang", ":say", ":discover_python", ":try_cmd",
                          ":try_exe", ":bootstrap_python", ":fetch_installer",
                          ":wait_for_python", ":create_venv", ":pip_install"):
                self.assertIn("\n" + label + "\r\n", body, f"{name} 缺子过程 {label}")

    def test_winget_then_three_sources_in_mirror_order(self):
        for name in BATS:
            body = self._body(name)
            self.assertIn("Python.Python.3.12", body, f"{name} 不再走 winget")
            order = [b for b in re.findall(
                r"call :fetch_installer (\S+)", body)]
            self.assertEqual(len(order), 3, f"{name} 只配了 {len(order)} 个下载地址")
            self.assertIn("huaweicloud", order[0], "R1：国内镜像必须排前面")
            self.assertIn("npmmirror", order[1], "R1：第二个镜像源")
            self.assertIn("python.org", order[2], "R1：官网回退必须末位")

    def test_installer_size_is_validated(self):
        """镜像会用 200 + 小 HTML 应付缺失文件，不校验体积就装出一个坏解释器。"""
        for name in BATS:
            self.assertRegex(self._body(name), r"if %SZ% GEQ \d{7} goto :fetch_ok",
                             f"{name} 没有安装包体积校验")

    def test_version_band_is_310_to_314(self):
        """PySide6 6.11 的 requires_python 是 >=3.10,<3.15；3.9 装不上，3.15 也不行。"""
        for name in BATS:
            body = self._body(name)
            self.assertIn("(3,10)<=sys.version_info[:2]<=(3,14)", body)
            self.assertNotIn("sys.version_info >= (3, 9)", body, f"{name} 还在收 3.9")

    def test_install_does_not_touch_path(self):
        """PrependPath=1 会改用户 PATH，与脚本开头"不修改系统环境"的承诺冲突；
        发现逻辑本来就读安装目录，不需要 PATH。"""
        for name in BATS:
            body = self._body(name)
            self.assertIn("PrependPath=0", body, f"{name} 的安装参数缺 PrependPath=0")
            self.assertNotIn("PrependPath=1", body, f"{name} 仍在往 PATH 里写")

    def test_discovery_sweeps_directories_not_only_fixed_names(self):
        for name in BATS:
            body = self._body(name)
            self.assertIn('for /d %%D in ("%LOCALAPPDATA%\\Programs\\Python\\?*")', body,
                          f"{name} 只猜固定目录名，装到别处的 Python 会漏")
            self.assertIn('for /d %%D in ("%ProgramFiles%\\Python*")', body)

    def test_no_bare_shim_prone_invocation(self):
        for name in BATS:
            for i, line in enumerate(read_bat(name)):
                stripped = line.lstrip()
                if stripped.startswith(("REM ", "call ", "for ", "if ", "echo")):
                    continue
                for prefix in SHIM_PRONE:
                    self.assertFalse(stripped.startswith(prefix),
                                     f"{name}:{i + 1} 少了 call，遇到 .bat 垫片会当场终止："
                                     f"{stripped[:70]!r}")

    def test_manual_install_is_not_the_first_answer(self):
        """旧文案在自动安装之前就叫用户 winget/去官网，正是这次投诉的症状。"""
        for name in BATS:
            lines = read_bat(name)
            err_at = [i for i, l in enumerate(lines) if l.startswith(":err_no_python")]
            boot_at = [i for i, l in enumerate(lines) if l.startswith(":bootstrap_python")]
            self.assertTrue(err_at and boot_at, f"{name} 的自动安装/错误出口结构变了")
            self.assertLess(max(boot_at), min(err_at),
                            f"{name} 的自动安装在错误出口之后，等于没装")
            tail = "\r\n".join(lines[min(err_at):min(err_at) + 6])
            self.assertNotIn("winget install", tail,
                             f"{name} 的 :err_no_python 还在指挥用户手工 winget")


class ChcpOrdering(unittest.TestCase):
    def test_oem_codepage_captured_before_chcp(self):
        for name in BATS:
            lines = read_bat(name)
            cap = [i for i, ln in enumerate(lines) if "tokens=2 delims" in ln and "chcp" in ln]
            switch = [i for i, l in enumerate(lines) if l.startswith("chcp 65001")]
            self.assertTrue(cap and switch, f"{name} 没有捕获 OEM 码页或没有 chcp")
            self.assertLess(max(cap), min(switch),
                            f"{name} 在 chcp 之后才读码页，读到的是 65001，中文检测会失效")


if __name__ == "__main__":
    unittest.main(verbosity=2)
