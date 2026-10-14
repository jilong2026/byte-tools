"""反馈闭环的护栏测试：日志落盘 / 导出诊断 / changelog / config 备份（离线）。

跑法：`.venv/Scripts/python.exe -u bt_feedback_tests.py`

这一套钉的是 2026-10-14 补上的"用户能把问题说清楚"的四条通道。
在它们之前：日志只活在内存 QTextEdit 里（关窗即丢）、没有任何一键导出、
release body 被解析层整个丢弃、config.json 落盘不留副本 ——
而作者的文档里反复记着"用户连续三次反馈"这类记录，全靠手打截图传回来。

**落盘不许伤到主流程**是这一组最重要的纪律：诊断能力是"锦上添花"，
它失败绝不许把一次本来能跑完的安装搞挂。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402


def setUpModule():
    """模块级打桩：建 MainWindow 的过程中不许起任何后台线程。

    为什么必须打桩（不是"为了跑得快"）：MainWindow._load_settings 与建卡
    会派发 VersionProbeWorker。测试里 `win.deleteLater()` 之后这些 QThread
    仍在跑，析构就撞上 Windows 的 0xC0000409 —— 进程**直接死掉，没有
    traceback**，报告停在用例名后就没了。项目的注释里早就记着这条
    （"QThread 运行时被析构 = Windows abort 0xC0000409"、"退出码 127 事故"）。

    所以这里把三个入口都换成空实现，让窗口成为一个纯 UI 壳。
    """
    # **必须**在这里建 QApplication：unittest 按类名字母序跑
    # （ConfigBackup → DiagnosticsExport → LogToDisk → ReleaseNotes），
    # 而 ensure_app() 原先写在 LogToDisk.setUpClass 里 —— 排在后面的
    # DiagnosticsExport 先跑，那会儿还没有 QApplication，于是它建 MainWindow
    # 时 Qt 直接 abort（0xC0000409，无 traceback，报告停在用例名后）。
    # 在 setUpModule 建一次，全文件都能用，且与类顺序无关。
    _btprelude.ensure_app()

    main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
    main.ComponentCard._detect_status = lambda self, *a, **k: None
    main.ComponentCard._schedule_version_probe = lambda self, *a, **k: None


def _close_window(win):
    """正经关一次窗口再释放，确保没有线程活着。

    比 deleteLater 多了三步：立 _closing（阻止新的派发）、drain（取消并等
    在途 worker）、closeEvent（关窗回收路径）。少任何一步都可能让仍在跑的
    QThread 被析构。
    """
    try:
        win._closing = True
        win._cancel_launch_workers()
        win._drain_background_workers()
        win.close()
    except Exception:
        pass
    win.deleteLater()


class _TempConfigDir:
    """把 CONFIG_DIR / CONFIG_FILE 指到临时目录，并还原。

    ⚠ 这里**刻意不用 `with`**（2026-10-14 踩过）：`with` 在离开块时就删掉临时
    目录，而窗口的清理发生在之后 —— 于是 `win.close()` 去写一个已经消失的
    目录，进程直接撞 0xC0000409。更糟的是：一旦 `with` 已退出，
    CONFIG_DIR 已被还原成**用户真实的 ~/.env-tools**，那条 close 路径就会
    往用户的 config.json 里写东西。测试替用户改配置是不能接受的。

    现在改成注册式：临时目录的清理先注册（最后才执行），窗口的清理后注册
    （最先执行）—— cleanup 是后进先出，顺序正好是"先关窗、后删目录、
    最后还原 CONFIG_DIR"。
    """

    def __init__(self, case: unittest.TestCase):
        self.case = case
        self.tmp = None
        self._dir = None
        self._file = None

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bt_feedback_")
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
        # 不在这里清理：交给 addCleanup，保证它排在关窗之后
        return False


# ---------------------------------------------------------------------------
# 日志落盘
# ---------------------------------------------------------------------------
class LogToDisk(unittest.TestCase):
    """每次运行一个 session-<时间戳>.log，纯文本、带时间与级别。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _btprelude.ensure_app()
        main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
        main.ComponentCard._detect_status = lambda self, *a, **k: None

    def _make_window(self):
        with _TempConfigDir(self) as cfg:
            win = main.MainWindow()
            win._session_stamp = "TESTSTAMP"
            yield_win = (win, cfg)
        return yield_win

    def test_log_is_written_to_disk_and_readable(self):
        win, cfg = self._make_window()
        # 窗口清理先注册 => LIFO 下最先执行（先关窗，再删临时目录）
        self.addCleanup(_close_window, win)
        win._append_log("info", "第一条消息")
        win._append_log("error", "第二条是错误")

        path = cfg / "logs" / "session-TESTSTAMP.log"
        self.assertTrue(path.is_file(), f"日志没有落盘：{path}")
        text = path.read_text(encoding="utf-8")
        self.assertIn("第一条消息", text)
        self.assertIn("第二条是错误", text)
        # 必须带级别，否则用户贴出来我们分不清哪行是要紧的
        self.assertIn("error", text)

    def test_log_file_is_plain_text_not_html(self):
        """落盘格式是纯文本 —— 它要被用户复制出去贴到 issue 里。

        界面写的是 `<span style="color:...">`，那是给 QTextEdit 用的；
        直接把同一串落盘的话，用户复制出来全是标签。
        """
        win, cfg = self._make_window()
        # 窗口清理先注册 => LIFO 下最先执行（先关窗，再删临时目录）
        self.addCleanup(_close_window, win)
        win._append_log("warn", "带 <尖括号> 与 & 符号的一行")
        text = (cfg / "logs" / "session-TESTSTAMP.log").read_text(encoding="utf-8")
        self.assertNotIn("<span", text, "落盘日志里混进了 HTML 标签")
        self.assertNotIn("style=", text, "落盘日志里混进了内联样式")

    def test_same_run_always_writes_one_file(self):
        """同一次运行的多条日志必须落在**同一个**文件里。

        否则"复制日志"和"另存为"会给用户一份东一段西一段的碎片。
        """
        win, cfg = self._make_window()
        # 窗口清理先注册 => LIFO 下最先执行（先关窗，再删临时目录）
        self.addCleanup(_close_window, win)
        for i in range(5):
            win._append_log("info", f"消息{i}")
        files = sorted((cfg / "logs").glob("session-*.log"))
        self.assertEqual(len(files), 1, f"一次运行写出了 {len(files)} 个日志文件")
        text = files[0].read_text(encoding="utf-8")
        for i in range(5):
            self.assertIn(f"消息{i}", text)

    def test_write_failure_does_not_break_the_ui(self):
        """落盘失败绝不许冒到界面上。

        诊断能力是锦上添花：磁盘满、目录被锁、防火弹拦截时它该失效，
        而不是把一次本来能跑完的安装搞挂。
        """
        win, cfg = self._make_window()
        # 窗口清理先注册 => LIFO 下最先执行（先关窗，再删临时目录）
        self.addCleanup(_close_window, win)
        original = win._log_file_path
        win._log_file_path = lambda: (_ for _ in ()).throw(PermissionError("目录被锁"))
        try:
            win._append_log("error", "这条不该把界面搞崩")
        finally:
            win._log_file_path = original
        # 追加一条正常的，确认写盘通道本身还活着
        win._append_log("info", "通道仍然可用")
        text = (cfg / "logs" / "session-TESTSTAMP.log").read_text(encoding="utf-8")
        self.assertIn("通道仍然可用", text)

    def test_old_session_logs_are_trimmed(self):
        """只保留最近 LOG_KEEP_SESSIONS 个会话文件。

        日志目录是长命目录，不裁会一直涨（一次装 JDK 就能写几百 KB）。
        """
        with _TempConfigDir(self) as cfg:
            log_dir = cfg / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            # 造 20 个"旧"会话，mtime 递增，保证排序稳定可预期
            import time as _t
            stale = []
            for i in range(main.LOG_KEEP_SESSIONS + 10):
                p = log_dir / f"session-stale{i:02d}.log"
                p.write_text("x", encoding="utf-8")
                os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
                stale.append(p)
            newest = log_dir / "session-newest.log"
            newest.write_text("keep me", encoding="utf-8")
            os.utime(newest, (1_800_000_000, 1_800_000_000))

            win = main.MainWindow()
            win._session_stamp = "TESTSTAMP"
            # 窗口清理先注册 => LIFO 下最先执行（先关窗，再删临时目录）
            self.addCleanup(_close_window, win)
            win._append_log("info", "触发裁剪")

            left = sorted(log_dir.glob("session-*.log"))
            self.assertTrue(newest.is_file(), "最新的会话日志被裁掉了")
            # 旧的应被裁到 LOG_KEEP_SESSIONS 个以内（加上本次这个）
            stale_left = [p for p in left if "stale" in p.name]
            self.assertLessEqual(
                len(stale_left), main.LOG_KEEP_SESSIONS,
                f"旧会话日志还剩 {len(stale_left)} 个，没裁到 "
                f"{main.LOG_KEEP_SESSIONS} 个以内",
            )

    def test_copy_and_save_buttons_exist(self):
        """日志浮层上要有「复制」和「另存为」两个按钮。

        落盘解决了"数据在"，但用户要能主动取出来 —— 没有按钮的话，
        落盘文件对普通用户等于不存在（他们不知道 logs/ 在哪）。
        """
        with _TempConfigDir(self):
            win = main.MainWindow()
            # 窗口清理先注册 => LIFO 下最先执行（先关窗，再删临时目录）
            self.addCleanup(_close_window, win)
            for attr in ("btn_log_copy", "btn_log_save"):
                self.assertTrue(hasattr(win, attr), f"缺 {attr}")
                btn = getattr(win, attr)
                self.assertTrue(btn.text(), f"{attr} 没有文字")
                # 点了不许直接抛 —— 用 _log_text_all 这个纯读取口验证
                self.assertIsInstance(win._log_text_all(), str)


# ---------------------------------------------------------------------------
# 导出诊断信息
# ---------------------------------------------------------------------------
class DiagnosticsExport(unittest.TestCase):
    """build_diagnostics 必须总能产出一份可用的文本。"""

    def test_report_is_produced_and_has_expected_sections(self):
        with _TempConfigDir(self) as cfg:
            (cfg / "config.json").write_text(
                '{"active": {"maven": "3.10.0"}}', encoding="utf-8")
            report = main.build_diagnostics()
        self.assertGreater(len(report), 200, "诊断报告过短，几乎等于没采到东西")
        for section in ("版本与运行环境", "组件与生效版本", "环境变量与 PATH",
                        "一键启停登记", "外部版本接管", "config.json"):
            self.assertIn(section, report, f"诊断报告缺「{section}」这一节")

    def test_report_survives_a_missing_or_broken_config(self):
        """配置坏了也要出得来一份报告，并且要**说清坏了**。

        一份少一节的报告仍然有用；一份空白的报告等于没做。而"用户手改坏
        配置"是真实故障：读侧把解析失败回落成空表，等于所有生效版本登记
        静默消失 —— 光把坏内容原样贴出来，用户根本看不出问题在哪。
        """
        with _TempConfigDir(self) as cfg:
            # 一个语法就坏的 config.json
            (cfg / "config.json").write_text("{ this is not json", encoding="utf-8")
            report = main.build_diagnostics()
        self.assertIn("版本与运行环境", report, "配置坏了连最基本的节都没了")
        self.assertIn(
            "不是合法 JSON", report,
            "配置读失败/格式坏掉这件事必须如实写出来 —— 读侧会把它回落成空表，"
            "也就是所有生效版本登记静默消失，光贴坏内容用户看不出问题在哪",
        )
        self.assertIn(".bak", report, "应提示旁边有 .bak 可供回退")

    def test_report_does_not_leak_secret_env_values(self):
        """不许把疑似密钥的环境变量值写进报告。

        报告会被人直接贴到公开 issue 上。
        """
        marker = "SENTINEL-SHOULD-NOT-APPEAR"
        os.environ["GITHUB_TOKEN"] = marker
        os.environ["MY_SECRET_TEST"] = marker
        try:
            report = main.build_diagnostics()
        finally:
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("MY_SECRET_TEST", None)
        self.assertNotIn(
            marker, report,
            "诊断报告里出现了环境变量值 —— 报告会贴到公开 issue 上，"
            "疑似密钥类变量必须脱敏",
        )

    def test_export_button_is_wired(self):
        """标题栏上要有「导出诊断」按钮且接线完整。"""
        with _TempConfigDir(self):
            win = main.MainWindow()
            # 窗口清理先注册 => LIFO 下最先执行（先关窗，再删临时目录）
            self.addCleanup(_close_window, win)
            self.assertTrue(hasattr(win, "btn_diagnostics"))
            btn = win.btn_diagnostics
            self.assertIn("诊断", btn.text())
            # 处理器存在且可调用（真跑会弹文件对话框，只查存在性与可调用性）
            self.assertTrue(callable(getattr(win, "_on_export_diagnostics_clicked", None)))


# ---------------------------------------------------------------------------
# changelog
# ---------------------------------------------------------------------------
class ReleaseNotes(unittest.TestCase):
    """release body 不许再被解析层丢掉，且展示前要压干净。"""

    def test_parser_keeps_the_body(self):
        payload = {
            "tag_name": "v9.9.9", "html_url": "https://example/r",
            "body": "## v9.9.9\n\n- 修好了 A\n- 修好了 B",
            "assets": [],
        }
        parsed = main.parse_latest_release(payload)
        self.assertIsNotNone(parsed)
        self.assertIn("修好了 A", parsed["notes"],
                      "release body 又被丢掉了：用户点版本号仍看不到改了什么")

    def test_gitee_parser_also_keeps_the_body(self):
        """Gitee 那条解析路径复用同一函数，notes 必须一起流通。"""
        payload = [{"tag_name": "v1.2.0", "body": "Gitee 侧的更新说明",
                    "assets": [{"name": "a.zip", "browser_download_url": "u"}]}]
        parsed = main.parse_gitee_releases(payload)
        self.assertIsNotNone(parsed)
        self.assertIn("Gitee 侧的更新说明", parsed["notes"])

    def test_digest_strips_noise_and_keeps_content(self):
        raw = ("## v1.3.0\n\n<img src=badge>\n\n"
               "- 修复启动崩溃\n- 图标现在能显示了\n\n---\n\n**更早的变更**")
        out = main._release_notes_digest(raw)
        self.assertIn("修复启动崩溃", out)
        self.assertIn("图标现在能显示了", out)
        self.assertNotIn("<img", out, "HTML 标签没被剥掉")
        self.assertNotIn("---", out, "纯标点分隔行没被剔掉")
        self.assertNotIn("v1.3.0；", out, "版本标题行没被剔掉（它已在版本号 chip 上）")

    def test_digest_of_empty_is_empty(self):
        for raw in ("", "   ", "\n\n\n", "---", "***"):
            with self.subTest(raw=raw):
                self.assertEqual(main._release_notes_digest(raw), "",
                                 f"{raw!r} 应被压成空串（没有内容可展示）")

    def test_digest_is_bounded_by_line_count(self):
        """条目很多时按**行数**截断 —— 整段塞进日志会把别的东西顶走。"""
        raw = "\n".join(f"- 第{i}条变更说明" for i in range(200))
        out = main._release_notes_digest(raw)
        self.assertLessEqual(
            out.count("；") + 1, main.RELEASE_NOTES_MAX_LINES,
            f"取了 {out.count('；') + 1} 条，超过 {main.RELEASE_NOTES_MAX_LINES} 条上限",
        )
        self.assertIn("第0条变更说明", out, "第一条不该被截掉")

    def test_digest_is_bounded_by_char_count(self):
        """单条很长时按**字符数**截断（行数没超，但内容能撑爆一行）。"""
        raw = "\n".join(f"- {'很长的一句话' * 40}" for i in range(3))
        out = main._release_notes_digest(raw)
        self.assertLessEqual(len(out), main.RELEASE_NOTES_MAX_CHARS + 1,
                             f"长度 {len(out)} 超过字符上限 {main.RELEASE_NOTES_MAX_CHARS}")
        self.assertTrue(out.endswith("…"), "超长截断后应带省略号")


# ---------------------------------------------------------------------------
# config.json 备份
# ---------------------------------------------------------------------------
class ConfigBackup(unittest.TestCase):
    """原子写只防"写崩"不防"写错"，必须另留一份上一版。"""

    def test_write_leaves_a_backup_of_the_previous_content(self):
        with _TempConfigDir(self) as cfg:
            cfg.mkdir(parents=True, exist_ok=True)
            first = {"active": {"maven": "3.10.0"}}
            main._atomic_write_config(first)
            self.assertFalse(
                (cfg / "config.json.bak").exists(),
                "首次写入前不该产生 .bak（还没有上一版可备份）",
            )

            second = {"active": {"maven": "3.9.0"}}
            main._atomic_write_config(second)

            bak = cfg / "config.json.bak"
            self.assertTrue(bak.is_file(), "写盘后没有留下 .bak")
            self.assertEqual(
                main.json.loads(bak.read_text(encoding="utf-8")), first,
                ".bak 里不是上一版内容，恢复回去等于没恢复",
            )

    def test_backup_protects_the_takeover_snapshot(self):
        """最该被保护的是 takeover 快照 —— 它是唯一能还原 HKLM 的依据。

        这个键在 config.json 里只有一份，没有第二处副本（接管备份
        takeover-backups/ 是另一条路径）。一旦被一次错误的写覆盖，
        用户就再也回不到接管前的系统环境。
        """
        snapshot = {"JAVA_HOME": {"value": "%JAVA_HOME%", "type": "REG_EXPAND_SZ"}}
        with _TempConfigDir(self) as cfg:
            cfg.mkdir(parents=True, exist_ok=True)
            main._atomic_write_config({"takeover": {"jdk": {"snapshot": snapshot}}})
            main._atomic_write_config({"takeover": {}})   # 模拟一次误写
            bak = main.json.loads((cfg / "config.json.bak").read_text(encoding="utf-8"))
            self.assertIn("jdk", bak.get("takeover", {}),
                          ".bak 里丢了接管快照 —— 那正是最需要它的时候")
            self.assertEqual(
                bak["takeover"]["jdk"]["snapshot"], snapshot,
                "接管快照的内容被改动了",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)