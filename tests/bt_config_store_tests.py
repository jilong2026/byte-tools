"""config.json 持久化层的护栏测试（离线）。

跑法：`.venv/Scripts/python.exe -u bt_config_store_tests.py`

`config.json` 里有四张互不相干的表，由四个写入方各自维护：

| 表| 写入方 |
|---|-------|
| `selections`（下拉框选中版本） | `MainWindow._save_settings` |
| `active`（生效版本登记） | `save_active_version` |
| `takeover`（外部版本接管 + **原文快照**） | `save_takeover_entry` / `drop_takeover_entry` |
| `machine_fix`（系统 PATH 插队记录） | `save_machine_fix_entry` |
| 外加 `view_mode` / `update_check` / 下载目录 |

任何一方**整体覆盖**都会把别人的数据抹掉。R3.2 那次事故就是这么发生的：
`_save_settings` 曾经整体覆盖，把 `active` 登记表清了。

2026-10-14 的收敛：原先全文件有 9 处 `json.loads(CONFIG_FILE.read_text())`，
每处各自写一遍"存在吗 → 读 → 解析 → 是不是 dict → 异常回落空表"。
样板重复本身不致命，致命的是**回落策略分散**与**写入路径重复**。
现在读侧统一走 `_config_read_raw()`，写侧统一走 `_update_config(mutate)`。
本文件把这个收敛钉死。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402


class TempConfig:
    """把 CONFIG_DIR / CONFIG_FILE 指到临时目录，用完还原。

    ⚠ 刻意不用 `with` 立即删目录：窗口的清理发生在之后，而 CONFIG_DIR 一旦
    先被还原成用户真实的 ~/.env-tools，那条关窗路径就会往**用户的
    config.json** 里写东西。这里返回的对象自己管生命周期。
    """

    def __init__(self, case: unittest.TestCase):
        self.case = case
        self.tmp = None
        self._dir = None
        self._file = None

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bt_cfg_")
        self.case.addCleanup(self.tmp.cleanup)          # 最后执行
        self._dir = main.CONFIG_DIR
        self._file = main.CONFIG_FILE
        self.case.addCleanup(self._restore)              # 倒数第二
        main.CONFIG_DIR = Path(self.tmp.name)
        main.CONFIG_FILE = main.CONFIG_DIR / "config.json"
        return main.CONFIG_DIR

    def _restore(self):
        main.CONFIG_DIR = self._dir
        main.CONFIG_FILE = self._file

    def __exit__(self, *exc):
        return False


def setUpModule():
    _btprelude.ensure_app()


# ---------------------------------------------------------------------------
# 读侧：_config_read_raw 是唯一入口
# ---------------------------------------------------------------------------
class ConfigRead(unittest.TestCase):
    def test_missing_file_yields_empty_dict(self):
        with TempConfig(self) as cfg:
            self.assertFalse((cfg / "config.json").exists())
            self.assertEqual(main._config_read_raw(), {})

    def test_broken_json_yields_empty_dict(self):
        """坏配置不该让工具打不开 —— 用户手改坏是真实场景。

        读侧回落成空表意味着用户多点一次、重新选一次；抛异常意味着打不开。
        """
        with TempConfig(self) as cfg:
            (cfg / "config.json").write_text("{ 这不是 JSON", encoding="utf-8")
            self.assertEqual(main._config_read_raw(), {})

    def test_non_dict_top_level_yields_empty_dict(self):
        """顶层是数组/字符串/数字时也要回落。

        这里是最容易漏的一处：漏了 isinstance 检查，磁盘上写个 `[]` 就会让
        后面某个 `data.get(...)` 抛 AttributeError。
        """
        for raw in ("[]", '"字符串"', "123", "null", "true"):
            with self.subTest(内容=raw):
                with TempConfig(self) as cfg:
                    (cfg / "config.json").write_text(raw, encoding="utf-8")
                    self.assertEqual(main._config_read_raw(), {})

    def test_valid_dict_passes_through(self):
        with TempConfig(self) as cfg:
            payload = {"active": {"maven": "3.10.0"}, "view_mode": "list"}
            (cfg / "config.json").write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(main._config_read_raw(), payload)

    def test_no_module_level_reads_config_directly(self):
        """源码级护栏：函数里不该再出现裸的 CONFIG_FILE.read_text。

        收敛的价值全在这一条上。九处各自解析的代码能跑，但它意味着
        "新增一条读路径"这件事不需要改任何别的地方 —— 于是迟早有人这么写，
        而那处的异常回落策略可能与别处不同。
        """
        import inspect
        # 唯一允许自己读原文的：build_diagnostics。
        # 它要把 config.json **原文**贴进诊断报告，好让用户能自己看/修；
        # 而且它还要判断格式是否合法（读侧会把坏配置回落成空表，也就是
        # 所有生效版本登记静默消失）—— 这两件事都需要字节级的原文，
        # _config_read_raw 那种"回落成空表"的语义在这里反而是有害的。
        ALLOWED = {"_config_read_raw", "build_diagnostics"}
        offenders = []
        for name, obj in vars(main).items():
            if name.startswith("__"):
                continue
            if inspect.isfunction(obj) and getattr(obj, "__module__", None) == main.__name__:
                try:
                    src = inspect.getsource(obj)
                except (OSError, TypeError):
                    continue
                if "CONFIG_FILE.read_text" in src and name not in ALLOWED:
                    offenders.append(name)
        self.assertEqual(
            offenders, [],
            f"这些函数还在自己读 config.json，请改走 _config_read_raw()：{offenders}",
        )


# ---------------------------------------------------------------------------
# 写侧：四个写入方互不覆盖
# ---------------------------------------------------------------------------
class ConfigWritesDoNotClobber(unittest.TestCase):
    """这张表里任何一张被抹掉，用户都要重新配置一遍。

    具体后果：
      · `active` 被抹 → 所有组件的"生效版本"变成"均未生效"
      · `takeover` 被抹 → **再也还原不回接管前的系统环境**（它含唯一快照）
      · `selections` 被抹 → 下拉框回到默认选择
      · `machine_fix` 被抹 → 系统 PATH 插队记录丢失
    """

    def test_four_writers_coexist(self):
        with TempConfig(self):
            main.save_active_version("maven", "3.10.0")
            main.save_takeover_entry("jdk", {"home": "C:/x", "snapshot": {"JAVA_HOME": {}}})
            main.save_machine_fix_entry("jdk", {"inserted": "C:/y"})
            main._update_config(lambda d: d.__setitem__("selections", {"maven": "3.10.0"}))

            data = main._config_read_raw()
            self.assertEqual(data.get("active"), {"maven": "3.10.0"})
            self.assertIn("jdk", data.get("takeover", {}))
            self.assertIn("jdk", data.get("machine_fix", {}))
            self.assertEqual(data.get("selections"), {"maven": "3.10.0"})

    def test_save_active_version_keeps_other_tables(self):
        with TempConfig(self):
            main.save_takeover_entry("jdk", {"home": "C:/x", "snapshot": {"JAVA_HOME": {}}})
            main.save_active_version("maven", "3.10.0")
            data = main._config_read_raw()
            self.assertIn("takeover", data, "写 active 把接管登记抹掉了")

    def test_save_settings_keeps_active(self):
        """R3.2 那条事故的负向对照。

        `_save_settings` 曾经整体覆盖，把 active 登记表清了 ——
        用户表现是"刚切好的生效版本重启后又没了"。
        """
        with TempConfig(self):
            main.save_active_version("jdk", "21")

            # 构造一个最小窗口：只需要 cards 有若干张卡、每张卡有下拉框
            class _Card:
                def __init__(self, key, text):
                    self.component = type("C", (), {"key": key})()
                    self.version_combo = type("V", (), {"currentText": lambda s: text})()

            win = main.MainWindow.__new__(main.MainWindow)
            win.cards = [_Card("jdk", "21"), _Card("maven", "3.10.0")]
            win.view_mode = "grid"
            win._save_settings()

            data = main._config_read_raw()
            self.assertEqual(data.get("active"), {"jdk": "21"},
                             "_save_settings 把 active 登记表覆盖了（R3.2 事故重现）")
            self.assertEqual(data.get("selections"), {"jdk": "21", "maven": "3.10.0"})
            self.assertEqual(data.get("view_mode"), "grid")

    def test_invalid_active_version_is_rejected(self):
        """空串不是"清除"而是脏值，显式报错。

        写进登记表后它会被读侧的非空字符串校验静默丢掉 —— 用户以为自己
        清了生效版本，实际上什么都没发生。
        """
        with TempConfig(self):
            for bad in ("", 21, {}, []):
                with self.subTest(值=bad):
                    with self.assertRaises(ValueError):
                        main.save_active_version("jdk", bad)

    def test_clearing_active_version_removes_only_that_key(self):
        with TempConfig(self):
            main.save_active_version("jdk", "21")
            main.save_active_version("maven", "3.10.0")
            main.save_active_version("jdk", None)
            data = main._config_read_raw()
            self.assertEqual(data.get("active"), {"maven": "3.10.0"},
                             "清除一个组件的生效版本时把别的也清了")

    def test_load_settings_tolerates_broken_config(self):
        """坏配置不许让界面停在半初始化状态。"""
        with TempConfig(self) as cfg:
            (cfg / "config.json").write_text("{ 坏", encoding="utf-8")
            win = main.MainWindow.__new__(main.MainWindow)
            win.cards = []
            win.view_mode = "grid"
            win._load_settings()
            self.assertEqual(win.view_mode, "grid", "坏配置应回落成默认视图模式")

    def test_load_settings_keeps_unknown_view_mode_out(self):
        with TempConfig(self) as cfg:
            (cfg / "config.json").write_text('{"view_mode": "乱写"}', encoding="utf-8")
            win = main.MainWindow.__new__(main.MainWindow)
            win.cards = []
            win._load_settings()
            self.assertEqual(win.view_mode, "grid",
                             "非法 view_mode 应回默认，而不是让界面进入未知状态")


# ---------------------------------------------------------------------------
# 备份
# ---------------------------------------------------------------------------
class ConfigBackup(unittest.TestCase):
    def test_backup_holds_the_previous_version(self):
        with TempConfig(self) as cfg:
            first = {"active": {"maven": "3.10.0"}}
            main._atomic_write_config(first)
            second = {"active": {"maven": "3.9.0"}}
            main._atomic_write_config(second)
            bak = json.loads((cfg / "config.json.bak").read_text(encoding="utf-8"))
            self.assertEqual(bak, first, ".bak 里不是上一版 —— 恢复回去等于没恢复")


if __name__ == "__main__":
    unittest.main(verbosity=2)