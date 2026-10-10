"""「检查更新 / 下载新包」的离线规格测试（不联网，不起真线程）。

契约（2026-10-10 与用户确认的范围：A 查+提示、B 应用内下载新包；**不做自动替换**）：

1. 更新信息只从 `api.github.com/repos/<owner>/<repo>/releases/latest` 取（实测免鉴权、
   1.2 秒、8.6KB），第一源失败退到 GitHub 加速器（实测代理回来的也是真 JSON）。
   **Gitee 不能当更新源**：它的开放 API 对这个仓库回 404「Not Found Project」（私有）。
2. 自动检查失败必须**完全静默** —— 这台机器对 github.com 偶发连不上是常态，
   弹一句"检查失败"对普通用户等于凭空多一个故障。手动点 chip 时才许回答。
3. 请求里**不许带任何用户信息**（不拼查询参数、不记 IP）：这是"检查更新"和"遥测"的分界。
4. 产物名在 v1.1.1 之前是 `byte-tools.*`、之后是 `ByteTools.*` —— 挑包必须按
   **平台 + 后缀**匹配，写死文件名会在下一个 tag 上直接选不到包。
"""
import os
import sys
import unittest

import platform as _platform


def _no_wmi(*_a, **_k):
    raise OSError("WMI disabled for test process")


_platform._wmi_query = _no_wmi
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402


def release(tag="v1.2.0", draft=False, prerelease=False, assets=None):
    """按 2026-10-10 实测到的真实形状造一份 releases/latest 响应。"""
    if assets is None:
        assets = [
            {"name": "ByteTools-linux-x64", "size": 84921616,
             "browser_download_url": "https://github.com/x/ByteTools-linux-x64"},
            {"name": "ByteTools-macos-arm64.zip", "size": 39615879,
             "browser_download_url": "https://github.com/x/ByteTools-macos-arm64.zip"},
            {"name": "ByteTools-windows-x64.zip", "size": 49591703,
             "browser_download_url": "https://github.com/x/ByteTools-windows-x64.zip"},
            {"name": "ByteTools.exe", "size": 49927339,
             "browser_download_url": "https://github.com/x/ByteTools.exe"},
        ]
    return {"tag_name": tag, "name": tag, "draft": draft, "prerelease": prerelease,
            "html_url": "https://github.com/jilong2026/byte-tools/releases/tag/" + tag,
            "published_at": "2026-10-10T00:00:00Z", "assets": assets}


class ParseAndCompare(unittest.TestCase):
    def test_parses_a_real_payload(self):
        got = main.parse_latest_release(release())
        self.assertIsNotNone(got)
        self.assertEqual(got["version"], "1.2.0", "tag 的 v 前缀要剥掉")
        self.assertEqual(got["tag"], "v1.2.0")
        self.assertIn("releases/tag/v1.2.0", got["page_url"])
        self.assertEqual(len(got["assets"]), 4)

    def test_rejects_shapes_that_cannot_be_trusted(self):
        for bad in (None, "x", {}, {"tag_name": ""}, {"tag_name": "nightly-2026"},
                    release(draft=True), release(prerelease=True),
                    release(tag="")):
            self.assertIsNone(main.parse_latest_release(bad),
                              f"这种响应不能当成「有新版本」：{bad}")

    def test_release_without_assets_still_parses(self):
        """没有产物的 Release 是 GitHub 的正常形态，版本号照样成立。

        只是**不能给应用内下载**（`pick_update_asset` 返回 None），
        提示与"打开发布页"仍然有效 —— 把这两种情况混成一个"读不懂"，
        用户就再也收不到任何新版本消息了。
        """
        got = main.parse_latest_release({"tag_name": "v9.9.9",
                                         "html_url": "https://x/releases/tag/v9.9.9",
                                         "draft": False, "prerelease": False})
        self.assertIsNotNone(got)
        self.assertEqual(got["version"], "9.9.9")
        self.assertIsNone(main.pick_update_asset(got["assets"], "Windows"))

    def test_numeric_segment_compare_not_string(self):
        self.assertTrue(main.version_is_newer("1.1.1", "1.1.2"))
        self.assertTrue(main.version_is_newer("1.9.0", "1.10.0"),
                        "按字符串比会得出 1.9 > 1.10，用户就永远收不到升级提示")
        self.assertFalse(main.version_is_newer("1.2.0", "1.2.0"))
        self.assertFalse(main.version_is_newer("1.2.0", "1.1.9"))
        self.assertFalse(main.version_is_newer("v1.2.0", "v1.2"), "等价的两个写法不算新")
        self.assertFalse(main.version_is_newer("1.2.0", ""), "拿不到版本号就不许提示")
        self.assertFalse(main.version_is_newer("", "1.0.0"), "当前版本读不出来也不许提示")


class AssetPick(unittest.TestCase):
    def test_windows_takes_the_single_exe_across_both_naming_eras(self):
        new = main.pick_update_asset(release()["assets"], "Windows")
        self.assertEqual(new["name"], "ByteTools.exe")
        old_assets = [{"name": "byte-tools.exe", "size": 1,
                       "browser_download_url": "u1"},
                      {"name": "byte-tools-windows-x64.zip", "size": 1,
                       "browser_download_url": "u2"}]
        self.assertEqual(main.pick_update_asset(old_assets, "Windows")["name"],
                         "byte-tools.exe",
                         "v1.1.1 及更早的产物叫 byte-tools.*，写死 ByteTools 会选不到包")

    def test_macos_and_linux(self):
        assets = release()["assets"]
        self.assertEqual(main.pick_update_asset(assets, "Darwin")["name"],
                         "ByteTools-macos-arm64.zip")
        self.assertEqual(main.pick_update_asset(assets, "Linux")["name"],
                         "ByteTools-linux-x64")

    def test_no_match_is_reported_not_guessed(self):
        self.assertIsNone(main.pick_update_asset([], "Windows"))
        self.assertIsNone(main.pick_update_asset([{"name": "notes.txt", "size": 1,
                                                   "browser_download_url": "u"}], "Windows"))


class Throttle(unittest.TestCase):
    def test_first_run_checks_then_24h_gate(self):
        self.assertTrue(main.update_check_due(1000.0, {}))
        self.assertFalse(main.update_check_due(1000.0 + 3600,
                                               {"last_check_ts": 1000.0}))
        self.assertTrue(main.update_check_due(1000.0 + 86400 * 2,
                                              {"last_check_ts": 1000.0}))

    def test_same_version_notified_only_once(self):
        state = {"last_check_ts": 0.0, "notified": "1.2.0"}
        self.assertFalse(main.update_notify_due(state, "1.2.0"))
        self.assertTrue(main.update_notify_due(state, "1.3.0"))
        self.assertTrue(main.update_notify_due({}, "1.2.0"))


class CheckForUpdate(unittest.TestCase):
    """check_for_update 的 fetch 是可注入接缝：测试绝不真发请求。"""

    def test_newer_release_comes_back_actionable(self):
        seen = []

        def fetch(url, timeout):
            seen.append(url)
            return 200, release()
        res = main.check_for_update(fetch=fetch, current="1.1.1")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["latest"]["version"], "1.2.0")
        self.assertTrue(main.version_is_newer("1.1.1", res["latest"]["version"]))
        self.assertEqual(res["asset"]["name"], "ByteTools.exe")
        self.assertEqual(res["error"], "")

    def test_same_version_is_ok_but_not_newer(self):
        res = main.check_for_update(fetch=lambda u, t: (200, release(tag="v1.1.1")),
                                    current="1.1.1")
        self.assertTrue(res["ok"])
        self.assertFalse(res["newer"])

    def test_connection_failure_is_reported_as_silent(self):
        def boom(url, timeout):
            raise OSError("getaddrinfo failed")
        res = main.check_for_update(fetch=boom, current="1.1.1")
        self.assertFalse(res["ok"])
        self.assertTrue(res["silent"],
                        "连不上 github 是常态：自动检查这条路上必须完全静默")
        self.assertIsNone(res["latest"])

    def test_falls_back_to_the_accelerator(self):
        calls = []

        def fetch(url, timeout):
            calls.append(url)
            if "api.github.com" in url and not url.startswith("https://gh-"):
                raise OSError("connection reset")
            return 200, release()
        res = main.check_for_update(fetch=fetch, current="1.1.1")
        self.assertTrue(res["ok"], res)
        self.assertGreaterEqual(len(calls), 2, "第一源失败应当退到加速器再试一次")

    def test_requests_carry_no_user_data(self):
        """隐私线：URL 就是那两个已知端点，不拼任何查询参数。"""
        seen = []
        main.check_for_update(fetch=lambda u, t: seen.append(u) or (200, release()),
                              current="1.1.1")
        self.assertEqual(main.UPDATE_SOURCES[0],
                         "https://api.github.com/repos/jilong2026/byte-tools/releases/latest",
                         "端点必须逐字钉住 —— 少一个 /repos/ 段就是 404，"
                         "而「以 /releases/latest 结尾」这种宽断言拦不住（真漏过一次）")
        for url in seen:
            self.assertNotIn("?", url, f"检查更新的请求不许带查询参数：{url}")
            self.assertIn(url, main.UPDATE_SOURCES,
                          f"只许打这两个端点（第二个是加速器前缀）：{url}")


class UiWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        import tempfile
        cls.app = main.QApplication.instance() or main.QApplication([])
        # 真配置必须挪走：_apply_update_result 会写 last_check_ts / notified，
        # 落在用户真实的 ~/.env-tools/config.json 上就是测试污染真机状态。
        cls._tmp = tempfile.TemporaryDirectory()
        cls._orig_dir = main.CONFIG_DIR
        cls._orig_file = main.CONFIG_FILE
        main.CONFIG_DIR = Path(cls._tmp.name)
        main.CONFIG_FILE = main.CONFIG_DIR / "config.json"
        cls._orig_fetch = main.check_for_update
        main.check_for_update = lambda *a, **k: {"ok": False, "silent": True,
                                                 "newer": False, "latest": None,
                                                 "asset": None, "error": "测试里不联网"}
        cls.win = main.MainWindow()
        cls.win.resize(1180, 780)
        cls.win.show()
        for _ in range(10):
            cls.app.processEvents()
        # 本类共用一个窗口，而"发现新版"那条用例会改 chip 的文字 —— 初始文字
        # 必须在这里先记下来，否则按字母序跑在它后面的用例会读到被改过的值。
        chip = cls.win.findChild(main.QPushButton, "versionChip")
        cls.chip_text_at_start = chip.text() if chip is not None else None

    @classmethod
    def tearDownClass(cls):
        main.check_for_update = cls._orig_fetch
        main.CONFIG_DIR = cls._orig_dir
        main.CONFIG_FILE = cls._orig_file
        cls._tmp.cleanup()
        cls.win.deleteLater()

    def test_version_chip_shows_the_running_version(self):
        chip = self.win.findChild(main.QPushButton, "versionChip")
        self.assertIsNotNone(chip, "标题栏要有可点的版本号")
        self.assertEqual(self.chip_text_at_start, f"v{main.APP_VERSION}",
                         "chip 初始文字必须是当前版本号（用户报问题第一眼要看的就是它）")

    def test_silent_failure_writes_nothing_to_the_log(self):
        """自动检查失败时一个字都不许写进日志（用户明确要求"完全静默"）。"""
        before = self.win.log_view.toPlainText()
        self.win._apply_update_result({"ok": False, "silent": True, "newer": False,
                                       "latest": None, "asset": None,
                                       "error": "connect failed"}, auto=True)
        self.assertEqual(self.win.log_view.toPlainText(), before,
                         "自动检查失败写了日志 = 凭空给用户多一个故障")

    def test_manual_check_does_answer(self):
        """手动点 chip 时必须回答，否则用户以为按钮坏了。"""
        before = self.win.log_view.toPlainText()
        self.win._apply_update_result({"ok": False, "silent": True, "newer": False,
                                       "latest": None, "asset": None,
                                       "error": "connect failed"}, auto=False)
        self.assertNotEqual(self.win.log_view.toPlainText(), before)

    def test_newer_version_lights_the_chip_and_offers_download(self):
        res = {"ok": True, "silent": False, "newer": True,
               "latest": {"version": "9.9.9", "tag": "v9.9.9", "page_url": "u"},
               "asset": {"name": "ByteTools.exe", "size": 123,
                         "browser_download_url": "https://x/ByteTools.exe"},
               "error": ""}
        self.win._apply_update_result(res, auto=True)
        chip = self.win.findChild(main.QPushButton, "versionChip")
        self.assertIn("9.9.9", chip.text() + chip.toolTip())
        self.assertTrue(hasattr(self.win, "_offer_update_download"),
                        "发现新版要能走下载（B 方案）")


if __name__ == "__main__":
    unittest.main()
