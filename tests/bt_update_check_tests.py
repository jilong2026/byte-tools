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
from pathlib import Path

import platform as _platform


import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

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
        self.assertTrue(hasattr(self.win, "_begin_app_update_download"),
                        "发现新版要能走下载（B 方案）")


class GiteeAsFirstSource(unittest.TestCase):
    """下载与查询都要先试 Gitee —— 2026-10-10 实测出来的排序，不是猜的。

    实测：`gitee.com/<owner>/<repo>/releases/download/<tag>/<name>` 匿名可下
    （302 → 302 → foruda 签名地址），200 / 49,963,621 B / `MZ`，**2 MB/s**；
    同一天 `gh-proxy.com` 只有 116–225 KB/s，而 `github.com:443` 在这台机器上经常整天不通。
    另外 main.py 原来那句"Gitee 不能当更新源（API 回 404）"是**拿 GitHub 的 owner 去问 Gitee**
    —— Gitee 那边是 `jack_liujilong`，用对 owner 之后 API 免鉴权 200。
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls.app = main.QApplication.instance() or main.QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls._tmpdir = cls._tmp.name
        cls._orig_dir, cls._orig_file = main.CONFIG_DIR, main.CONFIG_FILE
        main.CONFIG_DIR = Path(cls._tmp.name)
        main.CONFIG_FILE = main.CONFIG_DIR / "config.json"
        cls._orig_fetch = main.check_for_update
        # staticmethod 包一层：类属性直接放函数会在 self._real_check 时变成绑定方法，
        # 调用时把 self 当第一个位置参传进去 → "multiple values for argument 'fetch'"
        cls._real_check = staticmethod(main.check_for_update)
        main.check_for_update = lambda *a, **k: {"ok": False, "silent": True,
                                                 "newer": False, "latest": None,
                                                 "asset": None, "error": "测试里不联网"}
        cls._win = main.MainWindow()
        cls._win.show()
        for _ in range(10):
            cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        main.check_for_update = cls._orig_fetch
        main.CONFIG_DIR, main.CONFIG_FILE = cls._orig_dir, cls._orig_file
        cls._win.deleteLater()
        cls._tmp.cleanup()

    def _gh_release(self, tag="v9.9.9"):
        return {"tag_name": tag, "html_url": "https://github.com/x/releases/latest",
                "assets": [{"name": "ByteTools.exe", "size": 49963621,
                            "browser_download_url":
                                f"https://github.com/x/releases/download/{tag}/ByteTools.exe"}]}

    def _gitee_releases(self):
        # Gitee 回的是**数组**，而且实测按 tag 升序（v1.1.2 在 v1.2.0 前面）——
        # 所以"取第一条"会拿到旧版，必须按版本号挑最大。
        def one(tag):
            return {"tag_name": tag, "prerelease": False,
                    "assets": [{"name": "ByteTools.exe",
                                "browser_download_url":
                                    f"https://gitee.com/jack_liujilong/byte-tools/"
                                    f"releases/download/{tag}/ByteTools.exe"}]}
        return [one("v1.1.2"), one("v9.9.9")]

    def test_gitee_is_only_tried_after_both_github_sources_fail(self):
        seen = []

        def fetch(url, timeout):
            seen.append(url)
            if "gitee.com" in url:
                return 200, self._gitee_releases()
            return 502, {}

        # 类级把 check_for_update 换成假的了（建窗口时不许联网），这条用例要跑真函数
        main.check_for_update = self._real_check
        self.addCleanup(setattr, main, "check_for_update", self._real_check)
        res = main.check_for_update(fetch=fetch, current="1.1.1")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["latest"]["version"], "9.9.9",
                         "Gitee 的列表要按版本号挑最大，不能取第一条")
        self.assertLess(seen.index(main.UPDATE_SOURCES[0]),
                        seen.index(main.GITEE_RELEASES_API),
                        f"Gitee 只该在 GitHub 两源都失败后登场：{seen}")
        self.assertNotIn("?", main.GITEE_RELEASES_API,
                         "隐私线：更新源的 URL 不许带查询参数（连 per_page 都不加）")

    def test_gitee_payload_fills_the_same_shape_and_marks_size_unknown(self):
        parsed = main.parse_gitee_releases(self._gitee_releases())
        self.assertEqual(parsed["version"], "9.9.9")
        self.assertEqual(parsed["assets"][0]["size"], 0,
                         "Gitee 的 assets 没有 size 字段 —— 只能标成 0，不许瞎估")
        self.assertIn("gitee.com", parsed["page_url"])
        self.assertIsNone(main.parse_gitee_releases([]), "空列表要判失败，好让上层继续兜底")
        self.assertIsNone(main.parse_gitee_releases(
            [{"tag_name": "v1.0", "prerelease": True, "assets": []}]))

    def test_download_urls_put_gitee_first_and_never_accelerate_it(self):
        urls = main.update_download_urls(self._gh_release()["assets"][0], "v9.9.9")
        self.assertEqual(urls[0],
                         "https://gitee.com/jack_liujilong/byte-tools/releases/download/"
                         "v9.9.9/ByteTools.exe", f"第一源该是 Gitee：{urls}")
        for u in urls:
            if "gitee.com" in u:
                self.assertNotIn("gh-proxy", u, f"Gitee 不许套 GitHub 加速器：{u}")
                self.assertNotIn("ghfast", u)
                self.assertNotIn("ghproxy", u)
        self.assertIn("github.com/x/releases/download/v9.9.9/ByteTools.exe", urls[-1],
                      f"末位该是 GitHub 裸地址：{urls}")

    def test_gitee_only_asset_still_reports_size_as_unverified(self):
        asset = {"name": "ByteTools.exe", "size": 0,
                 "browser_download_url":
                     "https://gitee.com/jack_liujilong/byte-tools/releases/download/"
                     "v9.9.9/ByteTools.exe"}
        urls = main.update_download_urls(asset, "v9.9.9")
        self.assertEqual(urls[0], asset["browser_download_url"],
                         "接口已经给了 Gitee 直链，就别再拼一遍")

    def test_asset_from_the_gitee_api_still_keeps_a_github_fallback(self):
        """检查是从 Gitee 拿的时候，asset 里根本没有 GitHub 地址。

        首轮真机实测抓到的：那种情况下把 `browser_download_url` 直接丢给
        `_gh_accelerated`，会得到 `ghfast.top/https://gitee.com/...` 这种没人代理过的地址，
        四个源全废、GitHub 兜底反而消失了。
        """
        asset = {"name": "ByteTools.exe", "size": 0,
                 "browser_download_url":
                     "https://gitee.com/jack_liujilong/byte-tools/releases/download/"
                     "v9.9.9/ByteTools.exe"}
        urls = main.update_download_urls(asset, "v9.9.9")
        self.assertEqual(urls[0], asset["browser_download_url"])
        for u in urls:
            if "gitee.com" in u:
                host = u.split("://", 1)[1].split("/")[0]
                self.assertFalse(host.startswith("gh"),
                                 f"Gitee 那条被套了 GitHub 加速器：{u}")
        self.assertTrue(any("github.com/jilong2026/byte-tools/releases/download/v9.9.9" in u
                            for u in urls),
                        f"Gitee 附件没同步时得有 GitHub 兜底：{urls}")

    def test_exe_download_carries_a_magic_check(self):
        """Gitee 那条不通时会退到镜像/加速器 —— 正是"200 + 小 HTML"能骗过的地方。"""
        seen = {}
        orig_w, orig_dir = main.DownloadWorker, main.load_download_dir
        self.addCleanup(setattr, main, "DownloadWorker", orig_w)
        self.addCleanup(setattr, main, "load_download_dir", orig_dir)
        main.load_download_dir = lambda: Path(self._tmpdir)

        class FakeWorker:
            def __init__(self, urls, dest, parent=None, expect_magic=b""):
                seen["magic"] = expect_magic
                seen["dest"] = str(dest)

            def __getattr__(self, name):
                class _S:
                    def connect(_s, fn):
                        pass
                return _S()

            def start(self):
                seen["started"] = True

        main.DownloadWorker = FakeWorker
        win = self._win
        win._update_res = {"latest": {"version": "9.9.9"},
                           "asset": {"name": "ByteTools.exe", "size": 0,
                                     "browser_download_url":
                                         "https://gitee.com/jack_liujilong/byte-tools/"
                                         "releases/download/v9.9.9/ByteTools.exe"}}
        win._set_chip_state("update", new_version="9.9.9")
        self.assertTrue(win._begin_app_update_download(win._update_res))
        self.assertEqual(seen.get("magic"), b"MZ", "下 .exe 必须带 MZ 魔数校验")
        self.assertTrue(seen.get("started"))


    def test_remote_asset_name_cannot_escape_the_download_folder(self):
        """release API 给的 `name` 是外部数据：绝对路径或 `..` 会让 `目录 / 名字` 跳出目录。

        实测 `Path('C:/Users/x/Downloads') / 'C:\\\\Windows\\\\a.exe'` 直接得到
        `C:\\Windows\\a.exe` —— 下载完 `tmp.replace(dest)` 就是往那个位置写。
        """
        seen = {}
        orig_w, orig_dir = main.DownloadWorker, main.load_download_dir
        self.addCleanup(setattr, main, "DownloadWorker", orig_w)
        self.addCleanup(setattr, main, "load_download_dir", orig_dir)
        folder = Path(self._tmpdir) / "dl"
        folder.mkdir(exist_ok=True)
        main.load_download_dir = lambda: folder

        class FakeWorker:
            def __init__(self, urls, dest, parent=None, expect_magic=b""):
                seen["dest"] = Path(dest)

            def __getattr__(self, name):
                class _S:
                    def connect(_s, fn):
                        pass
                return _S()

            def start(self):
                pass

        main.DownloadWorker = FakeWorker
        win = self._win
        win._update_res = {"latest": {"version": "9.9.9", "tag": "v9.9.9"},
                           "asset": {"name": "C:\\Windows\\System32\\evil.exe", "size": 0,
                                     "browser_download_url":
                                         "https://gitee.com/x/releases/download/v9.9.9/evil.exe"}}
        win._set_chip_state("update", new_version="9.9.9")
        self.assertTrue(win._begin_app_update_download(win._update_res))
        self.assertEqual(seen["dest"].parent, folder)
        self.assertEqual(seen["dest"].name, "evil.exe",
                         f"只该取远端名的最后一段：{seen['dest']}")

    def test_progress_tick_does_not_read_the_config_file(self):
        """`load_download_dir()` 每次要读 config.json 并 json.loads —— 进度回调按 64KB 一次，
        50 MB 的包就是约 800 次磁盘往返，全在 GUI 线程上。"""
        win = self._win
        calls = []
        orig = main.load_download_dir
        self.addCleanup(setattr, main, "load_download_dir", orig)
        main.load_download_dir = lambda: (calls.append(1) or Path(self._tmpdir))
        win._set_chip_state("downloading", new_version="9.9.9", pct=0)
        before = len(calls)
        for i in range(6):
            win._on_update_progress(i * 1000, 10000)
        self.assertEqual(len(calls), before,
                         f"进度回调里又读了 {len(calls) - before} 次配置")

    def test_clicking_mid_download_keeps_the_percentage_on_the_chip(self):
        win = self._win
        chip = win.findChild(main.QPushButton, "versionChip")
        win._set_chip_state("downloading", new_version="9.9.9", pct=43)
        self.assertEqual(chip.text(), "↓ 43%")
        win._on_version_clicked()
        self.assertEqual(chip.text(), "↓ 43%",
                         "下载中点一下不该把进度打回 `↓ …`（下一次回调之前它就是空的）")


class ChipStateMachine(unittest.TestCase):
    """chip 从"点一下=检查更新"变成一个**按状态分派**的控件（2026-10-10 用户提的方案）。

    四条硬约束，每条一个用例钉住：
      1. 版本号任何时刻都在（它是全 app 唯一的版本落点，报问题要对上版本）；
         只有下载中那一分钟换成 `↓ 37%`。
      2. "已是最新"和"没查到"必须是两个态 —— 静默失败在这个控件上等于说谎。
      3. 有新版时点击 = 直接下到记住的 `download_dir`，不弹确认、不弹目录框。
      4. 下载中再点不许开第二路（49 MB 不是免费的）。
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        import tempfile
        cls.app = main.QApplication.instance() or main.QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()
        cls._orig_dir, cls._orig_file = main.CONFIG_DIR, main.CONFIG_FILE
        main.CONFIG_DIR = Path(cls._tmp.name)
        main.CONFIG_FILE = main.CONFIG_DIR / "config.json"
        cls._orig_fetch = main.check_for_update
        main.check_for_update = lambda *a, **k: {"ok": False, "silent": True,
                                                 "newer": False, "latest": None,
                                                 "asset": None, "error": "测试里不联网"}
        cls.win = main.MainWindow()
        cls.win.show()
        for _ in range(10):
            cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        main.check_for_update = cls._orig_fetch
        main.CONFIG_DIR, main.CONFIG_FILE = cls._orig_dir, cls._orig_file
        cls._tmp.cleanup()
        cls.win.deleteLater()

    def setUp(self):
        # 每条用例自己把状态摆到位，不依赖类内顺序（上一版共用窗口就被顺序咬过）
        self.win._update_dl = None
        self.win._chip_state = "idle"

    def _chip(self):
        return self.win.findChild(main.QPushButton, "versionChip")

    def _newer(self, auto=True):
        self.win._apply_update_result(
            {"ok": True, "silent": False, "newer": True,
             "latest": {"version": "9.9.9", "tag": "v9.9.9", "page_url": "u"},
             "asset": {"name": "ByteTools-9.9.9.exe", "size": 4200,
                       "browser_download_url": "https://x/ByteTools-9.9.9.exe"},
             "error": ""}, auto=auto)

    def test_update_available_state_points_down_at_the_new_version(self):
        self._newer()
        chip = self._chip()
        self.assertTrue(chip.text().startswith("↓"),
                        f"可下载要用向下的箭头（↑ 是升级的意思，动作其实是下载）：{chip.text()}")
        self.assertIn("9.9.9", chip.text())
        self.assertEqual(chip.property("chipState"), "update")
        self.assertIn(str(main.APP_VERSION), chip.toolTip(),
                      "tooltip 要同时给出当前版本，用户才知道自己在从哪版升")
        self.assertIn("下载", chip.toolTip())

    def test_up_to_date_and_check_failed_are_two_different_states(self):
        """断网显示成"已是最新"比不显示更糟 —— 这两态必须能从文字和属性上分开。"""
        self.win._apply_update_result({"ok": True, "silent": False, "newer": False,
                                       "latest": {"version": main.APP_VERSION},
                                       "asset": None, "error": ""}, auto=True)
        chip = self._chip()
        self.assertEqual(chip.property("chipState"), "latest")
        self.assertIn("最新", chip.toolTip())
        self.assertIn(f"v{main.APP_VERSION}", chip.text(),
                      "没有新版时版本号必须还写在 chip 上")

        self.win._apply_update_result({"ok": False, "silent": True, "newer": False,
                                       "latest": None, "asset": None,
                                       "error": "URLError: 连不上"}, auto=True)
        self.assertEqual(chip.property("chipState"), "error")
        self.assertIn("?", chip.text())
        self.assertNotIn("最新", chip.toolTip())
        self.assertIn("连不上", chip.toolTip(), "失败原因要进 tooltip，否则用户无从判断")
        self.assertIn("不影响", chip.toolTip())

    def test_click_with_an_update_downloads_without_any_dialog(self):
        """点一下就开始下：不弹"确定要下载吗"，也不弹目录选择框（标题栏上弹文件框很突兀）。"""
        self._newer()
        called = []

        def no_dialog(*a, **k):
            called.append("QFileDialog 被调用了")
            return ""

        started = {}

        class FakeWorker:
            def __init__(self, urls, dest, parent=None, expect_magic=b""):
                started["urls"] = urls
                started["dest"] = str(dest)

            def __getattr__(self, name):
                class _Sig:
                    def connect(_s, fn):
                        pass
                return _Sig()

            def start(self):
                started["started"] = True

        orig_dlg = main.QFileDialog.getExistingDirectory
        orig_w = main.DownloadWorker
        orig_dir = main.load_download_dir
        self.addCleanup(setattr, main.QFileDialog, "getExistingDirectory", orig_dlg)
        self.addCleanup(setattr, main, "DownloadWorker", orig_w)
        self.addCleanup(setattr, main, "load_download_dir", orig_dir)
        main.QFileDialog.getExistingDirectory = staticmethod(no_dialog)
        main.DownloadWorker = FakeWorker
        main.load_download_dir = lambda: Path(self._tmp.name) / "dl"
        (Path(self._tmp.name) / "dl").mkdir(exist_ok=True)

        self.win._on_version_clicked()

        self.assertEqual(called, [], "点击下载时不该弹目录选择框")
        self.assertTrue(started.get("started"), f"没真的开始下载：{started}")
        self.assertIn("9.9.9", started["dest"])
        self.assertEqual(Path(started["dest"]).parent,
                         (Path(self._tmp.name) / "dl").resolve(),
                         "要落在用户上次记住的目录里")

    def test_click_while_downloading_does_not_start_a_second_one(self):
        self._newer()

        class Running:
            def isRunning(self):
                return True

        self.win._update_dl = Running()
        hits = []
        orig = main.DownloadWorker
        self.addCleanup(setattr, main, "DownloadWorker", orig)

        def boom(*a, **k):
            hits.append(1)
            return orig(*a, **k)

        main.DownloadWorker = boom
        self.win._on_version_clicked()
        self.assertEqual(hits, [], "下载中再点 = 开第二路 49 MB 下载")
        self.assertEqual(self._chip().property("chipState"), "downloading",
                         "chip 要还停在下载态，不能被这次点击打回可下载")

    def test_progress_line_shows_only_a_percentage(self):
        """标题栏宽度紧（之前多加一个按钮就把「清理残留 PATH」裁掉过），速度留给日志。"""
        self.win._begin_app_update_download(
            {"latest": {"version": "9.9.9", "page_url": "u"},
             "asset": {"name": "ByteTools-9.9.9.exe", "size": 10000,
                       "browser_download_url": "https://x/ByteTools-9.9.9.exe"}})
        self.win._on_update_progress(2500, 10000)
        text = self._chip().text()
        self.assertEqual(text, "↓ 25%", f"chip 上只要百分比：{text}")
        self.assertNotIn("KB/s", text)
        self.win._on_update_progress(10000, 10000)
        self.assertEqual(self._chip().text(), "↓ 99%",
                         "100% 之前先停在 99%：字节还没落盘就说满了是撒谎")


    def test_second_click_after_a_finished_check_still_checks(self):
        """第一轮检查跑完之后，`_update_worker` 是个已经被 `deleteLater` 析构的死引用：
        裸调 `isRunning()` 抛的是 RuntimeError，于是第二下点击死在门口 —— 用户看到的就是
        "这颗版本号点一次有用，之后再点就没反应了"。
        2026-10-11 真机抓到的关窗崩溃（0xC0000409）是同一颗雷在 closeEvent 里炸。
        """
        import shiboken6
        self.win._update_worker = None
        before = self.win.log_view.toPlainText()
        self.win._start_update_check(auto=False)
        worker = self.win._update_worker
        self.assertTrue(worker is not None and worker.wait(3000),
                        "前提不成立：第一轮检查线程没跑完")
        shiboken6.delete(worker)        # 等价于事件循环把 deleteLater 处理完
        with self.assertRaises(RuntimeError):
            worker.isRunning()          # 前提：这时裸调确实抛，不是返回 False
        self.win._start_update_check(auto=False)
        self.assertNotEqual(self.win.log_view.toPlainText(), before,
                            "第二次点版本号要照样回答，否则像按钮坏了")


    def test_chip_shows_the_state_in_words_not_only_in_the_tooltip(self):
        """用户看不到 tooltip 就等于没提示：查到结果后 chip 上要直接写「最新」/「待更新」。

        2026-10-11 用户明确否掉了"弹窗"这条路子，改成"版本号 + 小字状态"，
        所以文字状态就是这次交互的唯一交付物 —— 只改颜色不算做到。
        """
        chip = self._chip()
        self.win._apply_update_result({"ok": True, "silent": False, "newer": False,
                                       "latest": {"version": main.APP_VERSION},
                                       "asset": None, "error": ""}, auto=True)
        self.assertIn("最新", chip.text(), f"已是最新要写在 chip 上：{chip.text()}")
        self.assertIn(str(main.APP_VERSION), chip.text(),
                      "加了状态字也不许把版本号挤掉（R12.5：报问题第一眼要对上版本）")

        self.win._apply_update_result({"ok": False, "silent": True, "newer": False,
                                       "latest": None, "asset": None,
                                       "error": "connect failed"}, auto=True)
        self.assertIn("未查到", chip.text(), f"没查到要如实写：{chip.text()}")
        self.assertIn(str(main.APP_VERSION), chip.text())

    def test_checking_state_puts_a_refresh_glyph_on_the_chip(self):
        """点下去到出结果之间有几秒，那几秒必须有个"在办事"的图标，
        否则用户以为没响应会连着点好几下。"""
        self.win._set_chip_state("checking")
        chip = self._chip()
        self.assertIn("⟳", chip.text(), f"检查中要有刷新图标：{chip.text()}")
        self.assertIn(str(main.APP_VERSION), chip.text())

    def test_pending_update_shows_both_versions_and_the_label(self):
        self._newer()
        chip = self._chip()
        self.assertIn("待更新", chip.text(), f"有新版要写明「待更新」：{chip.text()}")
        self.assertIn("9.9.9", chip.text())

    def test_chip_is_fixed_width_so_its_state_text_survives(self):
        """chip 必须定宽：宽度一紧张，不定宽的控件会先被布局压扁，状态字等于没写。"

        这里**不量像素**：offscreen 平台的字体度量大 ~1.6 倍（同一句 `v1.2.0` 的
        minimumSizeHint 是 92，真实渲染 54），拿它判"裁没裁字"会把产品改错方向 ——
        2026-10-12 就据此误把窗口最小宽抬到 1060。真字体下的宽度预算用
        `tools/bt_titlebar_budget.py` 量（实测这一行总共 697 像素，1000 一档余量充足）。
        """
        from PySide6.QtWidgets import QSizePolicy
        self.win._set_chip_state("update", new_version="1.10.0")
        for _ in range(20):
            self.app.processEvents()
        chip = self._chip()
        self.assertEqual(chip.text(), "↓ v1.10.0 待更新")
        self.assertEqual(chip.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed,
                         "chip 不在定宽名单里：宽度一紧就被压扁，状态字白加")
        self.assertLess(chip.geometry().x(), self.win.btn_github.geometry().x(),
                        "chip 不在 GitHub 按钮左边，标题栏顺序被改了")

if __name__ == "__main__":
    unittest.main()
