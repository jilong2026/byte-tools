"""界面搜索框 + 新增 PowerShell 7 / Nginx 两组件的规格测试（离线，不联网）。

写这个文件时功能还不存在，所以首轮必须全红：
  A. component_matches / MainWindow.search_box / _apply_search 的过滤契约
  B. powershell 与 nginx 两个组件的注册、分类、多源与平台限制
"""
import os
import platform as _platform
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _no_wmi(*_a, **_k):
    raise OSError("WMI disabled for test process")


_platform._wmi_query = _no_wmi
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402

# 26 个组件的完整归属（24 个存量 + powershell + nginx）
EXPECTED_MEMBERSHIP = {
    "开发环境": {"jdk", "python", "node", "go", "bun", "conda", "git", "maven",
               "gradle", "powershell"},
    "开发软件": {"tomcat", "mysql", "mongodb", "postgresql", "elasticsearch", "nacos",
               "seata", "kafka", "rocketmq", "pulsar", "activemq", "rabbitmq", "nginx"},
    "其它软件": {"docker", "kubectl", "jenkins"},
}
ALL_KEYS = {k for g in EXPECTED_MEMBERSHIP.values() for k in g}
TOTAL = sum(len(g) for g in EXPECTED_MEMBERSHIP.values())


def cv_urls(cv, os_key):
    """取某版本在某平台故障转移链上的全部 URL。"""
    bucket = cv.url_list_map or {k: [v] for k, v in (cv.url_map or {}).items() if v}
    return bucket.get(os_key, [])


class ComponentMatches(unittest.TestCase):
    """component_matches：搜索的纯函数内核，不碰界面。"""

    def setUp(self):
        self.by_key = {c.key: c for c in main.build_components()}

    def test_empty_or_blank_query_matches_everything(self):
        for query in ("", "   ", "\t"):
            self.assertTrue(main.component_matches(self.by_key["jdk"], query), query)

    def test_matches_key_case_insensitively(self):
        comp = self.by_key["elasticsearch"]
        self.assertTrue(main.component_matches(comp, "elastic"))
        self.assertTrue(main.component_matches(comp, "ELASTIC"))
        self.assertTrue(main.component_matches(comp, "SeArC"))

    def test_matches_display_name_not_only_key(self):
        # JDK 的 key 是 jdk，但显示名里还有 Temurin
        comp = self.by_key["jdk"]
        self.assertTrue(main.component_matches(comp, "temurin"))

    def test_non_matching_query_returns_false(self):
        self.assertFalse(main.component_matches(self.by_key["nginx"], "kafka"))

    def test_spaces_around_query_are_ignored(self):
        self.assertTrue(main.component_matches(self.by_key["mysql"], "  my  "))


class NewComponentsRegistered(unittest.TestCase):
    def setUp(self):
        self.by_key = {c.key: c for c in main.build_components()}

    def test_both_new_keys_exist(self):
        for key in ("powershell", "nginx"):
            self.assertIn(key, self.by_key, f"{key} 没进 build_components()")
        # +1 是隐藏组件 erlang（rabbitmq 的前置运行时，不进界面）
        self.assertEqual(len(self.by_key), TOTAL + 1)
        self.assertTrue(self.by_key["erlang"].hidden)

    def test_membership_still_matches_the_agreed_split(self):
        got = {name: set() for name in EXPECTED_MEMBERSHIP}
        for comp in self.by_key.values():
            if getattr(comp, "hidden", False):
                continue
            got[comp.category].add(comp.key)
        self.assertEqual(got, EXPECTED_MEMBERSHIP)

    def test_both_are_fetchable(self):
        for key in ("powershell", "nginx"):
            self.assertIn(key, main.FETCHERS, f"{key} 没注册到 FETCHERS")
            self.assertTrue(callable(main.FETCHERS[key]))


class PowerShellSources(unittest.TestCase):
    """PowerShell 7：三平台都有官方便携包，GitHub 直链 + 加速器（实测 2026-09-28）。"""

    @classmethod
    def setUpClass(cls):
        cls.comp = next(c for c in main.build_components() if c.key == "powershell")
        cls.cv = cls.comp.versions[0]
        cls.v = cls.cv.version

    def test_exec_probe_shape(self):
        self.assertEqual(self.comp.exec_name, "pwsh")
        self.assertEqual(self.comp.env_var, None, "pwsh 没有 PS_HOME 概念，只进 PATH")
        self.assertEqual(self.comp.path_subdir, "", "pwsh 可执行文件在解压根目录")
        self.assertEqual(self.comp.version_args, ["--version"])
        self.assertTrue(self.comp.version_probe, "pwsh --version 不会拉起服务，允许探测")

    def test_all_three_platforms_have_urls(self):
        for os_key in ("Windows", "Darwin", "Linux"):
            self.assertTrue(cv_urls(self.cv, os_key), f"{os_key} 一个源都没有")

    def test_official_github_is_the_last_source(self):
        for os_key in ("Windows", "Darwin", "Linux"):
            urls = cv_urls(self.cv, os_key)
            self.assertIn("github.com/PowerShell/PowerShell/releases/download/", urls[-1])

    def test_at_least_two_accelerated_sources_before_official(self):
        for os_key in ("Windows", "Darwin", "Linux"):
            urls = cv_urls(self.cv, os_key)
            ahead = [u for u in urls[:-1] if any(a in u for a in main.GH_ACCELERATORS)]
            self.assertGreaterEqual(len(ahead), 2,
                                    f"{os_key} 的加速源不足 2 个：{urls}")

    def test_archive_type_per_platform(self):
        # Windows 是 zip，Unix 是 tar.gz（与 _STD_ARCHIVE 一致）
        self.assertEqual(self.cv.archive_map.get("Windows"), "zip")
        self.assertEqual(self.cv.archive_map.get("Linux"), "tar.gz")
        self.assertEqual(self.cv.archive_map.get("Darwin"), "tar.gz")

    def test_win_asset_name_pattern_matches_measurement(self):
        url = cv_urls(self.cv, "Windows")[-1]
        self.assertIn(f"PowerShell-{self.v}-win-x64.zip", url)

    def test_unix_asset_names_use_lowercase_prefix(self):
        self.assertIn(f"powershell-{self.v}-linux-x64.tar.gz", cv_urls(self.cv, "Linux")[-1])
        self.assertIn(f"powershell-{self.v}-osx-x64.tar.gz", cv_urls(self.cv, "Darwin")[-1])


class NginxSources(unittest.TestCase):
    """Nginx：Windows 有官方 zip（华为云两子域实测有包），Unix 只有源码包。"""

    @classmethod
    def setUpClass(cls):
        cls.comp = next(c for c in main.build_components() if c.key == "nginx")
        cls.cv = cls.comp.versions[0]
        cls.v = cls.cv.version

    def test_exec_probe_shape(self):
        self.assertEqual(self.comp.exec_name, "nginx")
        self.assertEqual(self.comp.env_var, None, "nginx 没有 NGINX_HOME 概念")
        self.assertEqual(self.comp.path_subdir, "", "nginx.exe 在解压根目录，无 bin")
        self.assertEqual(self.comp.version_args, ["-v"])
        self.assertTrue(self.comp.version_probe, "nginx -v 只打印版本就退出")

    def test_windows_chain_is_mainland_first_official_last(self):
        urls = cv_urls(self.cv, "Windows")
        self.assertGreaterEqual(len(urls), 3, f"Windows 源太少：{urls}")
        self.assertEqual(urls[-1], f"https://nginx.org/download/nginx-{self.v}.zip")
        mainland = [u for u in urls[:-1] if "nginx.org" not in u]
        self.assertGreaterEqual(len(mainland), 2, f"大陆镜像不足 2 个：{urls}")

    def test_unix_platforms_offer_no_download_because_only_source_exists(self):
        # 实测：nginx.org 对 Linux/macOS 只发 .tar.gz 源码包，解压后没有可执行文件
        for os_key in ("Darwin", "Linux"):
            self.assertEqual(cv_urls(self.cv, os_key), [],
                             f"nginx {os_key} 不该给源码包当下载源")

    def test_unix_hint_points_to_package_manager(self):
        hint = self.comp.unsupported_platform_hint or ""
        self.assertTrue(hint, "nginx 在 Linux/macOS 无包，必须有引导文案")
        self.assertTrue(any(w in hint for w in ("apt", "dnf", "yum", "brew", "源码")),
                        f"引导文案没落到具体安装方式：{hint}")


class MainWindowSearchBox(unittest.TestCase):
    """界面侧：搜索框存在、按分类过滤卡片、Tab 标题跟随匹配数量。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls._orig_fetch = main.MainWindow._start_fetch_versions
        cls._orig_detect = main.ComponentCard._detect_status
        main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
        main.ComponentCard._detect_status = lambda self, *a, **k: None
        cls.win = main.MainWindow()

    @classmethod
    def tearDownClass(cls):
        main.MainWindow._start_fetch_versions = cls._orig_fetch
        main.ComponentCard._detect_status = cls._orig_detect
        cls.win.deleteLater()

    def test_search_box_exists_above_the_tabs(self):
        from PySide6.QtWidgets import QLineEdit, QTabWidget
        box = self.win.search_box
        self.assertIsInstance(box, QLineEdit)
        # 搜索框不能挂在某个 Tab 页里，否则切页就找不到它了
        node = box.parent()
        while node is not None:
            self.assertNotIsInstance(node, QTabWidget, "搜索框被塞进 Tab 页里了")
            node = node.parent()

    def test_search_box_is_wired_to_the_filter(self):
        self.win.search_box.setText("kafka")
        visible = {c.component.key for c in self.win.cards if not c.isHidden()}
        self.assertEqual(visible, {"kafka"}, "输入 kafka 后应该只剩 Kafka 一张卡片")

    def test_empty_query_shows_every_card_again(self):
        self.win.search_box.setText("zazaza")
        self.assertEqual([c for c in self.win.cards if not c.isHidden()], [])
        self.win.search_box.setText("")
        self.assertEqual(len([c for c in self.win.cards if not c.isHidden()]), TOTAL)

    def _result_widgets(self):
        lay = self.win.results_layout
        return [lay.itemAt(i).widget() for i in range(lay.count())
                if lay.itemAt(i).widget() is not None]

    def test_search_switches_to_unified_results_panel(self):
        # sql 命中 mysql + postgresql，二者都在「开发软件」分类
        self.win.search_box.setText("sql")
        self.assertEqual(self.win.top_stack.currentIndex(), 1, "应切到统一结果面板")
        self.assertIs(self.win.top_stack.currentWidget(), self.win.results_area)
        visible = {c.component.key for c in self.win.cards if not c.isHidden()}
        self.assertEqual(visible, {"mysql", "postgresql"})
        # 结果面板里应出现「开发软件」分类小标题
        headers = [w.text() for w in self._result_widgets()
                   if w.objectName() == "resultCatHeader"]
        self.assertIn("开发软件", headers)
        # 命中卡片里确实包含 mysql / postgresql
        shown = {w.component.key for w in self._result_widgets()
                 if w in self.win.cards}
        self.assertTrue({"mysql", "postgresql"} <= shown)
        self.win.search_box.setText("")

    def test_search_is_global_across_all_categories(self):
        # 搜 jdk（在「开发环境」分类）也能在统一面板里找到——不是只搜某个 Tab 内
        self.win.search_box.setText("jdk")
        self.assertEqual(self.win.top_stack.currentIndex(), 1)
        visible = {c.component.key for c in self.win.cards if not c.isHidden()}
        self.assertEqual(visible, {"jdk"})
        self.win.search_box.setText("")

    def test_clearing_search_restores_tabs(self):
        self.win.search_box.setText("kafka")
        self.win.search_box.setText("")
        self.assertEqual(self.win.top_stack.currentIndex(), 0, "清空后应回到 Tab 浏览")
        self.assertEqual(
            [self.win.tabs.tabText(i) for i in range(self.win.tabs.count())],
            [f"{name}（{len(EXPECTED_MEMBERSHIP[name])}）" for name in EXPECTED_MEMBERSHIP],
        )

    def test_filtering_does_not_break_the_flat_card_list(self):
        self.win.search_box.setText("redis-not-here")
        self.assertEqual(len(self.win.cards), TOTAL)
        self.assertEqual({c.component.key for c in self.win.cards}, ALL_KEYS)
        self.win.search_box.setText("")


if __name__ == "__main__":
    unittest.main(verbosity=2)
