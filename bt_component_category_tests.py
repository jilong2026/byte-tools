"""组件三类分组 + Tab 页布局的规格测试（离线，不联网）。

分类标准（2026-09-28 与用户确认）：
  开发环境 = 装完进 PATH、直接用来写/编译/打包代码（语言运行时 + 构建与版本工具）
  开发软件 = 本地跑起来给项目当依赖的服务（数据库 / 消息队列 / 注册中心 / 搜索 / 容器运行时宿主）
  其它软件 = 不参与写代码的运维与交付外围（容器 / 编排 / CI）
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
REPO_ROOT = r"E:\file\test\byte-tools"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402

EXPECTED_MEMBERSHIP = {
    "开发环境": {"jdk", "python", "node", "go", "bun", "conda", "git", "maven", "gradle"},
    "开发软件": {"tomcat", "mysql", "mongodb", "postgresql", "elasticsearch", "nacos",
               "seata", "kafka", "rocketmq", "pulsar", "activemq", "rabbitmq"},
    "其它软件": {"docker", "kubectl", "jenkins"},
}

ALL_KEYS = {k for group in EXPECTED_MEMBERSHIP.values() for k in group}


class CategoryOnComponent(unittest.TestCase):
    def setUp(self):
        self.components = main.build_components()

    def test_every_component_has_a_known_category(self):
        allowed = set(EXPECTED_MEMBERSHIP)
        for comp in self.components:
            self.assertIn(comp.category, allowed,
                          f"{comp.key} 的分类没登记：{comp.category!r}")

    def test_membership_matches_the_agreed_split(self):
        got = {name: set() for name in EXPECTED_MEMBERSHIP}
        for comp in self.components:
            got[comp.category].add(comp.key)
        self.assertEqual(got, EXPECTED_MEMBERSHIP)

    def test_no_component_is_left_unclassified(self):
        self.assertEqual({c.key for c in self.components}, ALL_KEYS)
        self.assertEqual(len(self.components), 24)


class GroupComponentsHelper(unittest.TestCase):
    def test_grouping_preserves_order_and_covers_every_tab(self):
        groups = main.group_components(main.build_components())
        self.assertEqual(list(groups), list(EXPECTED_MEMBERSHIP),
                         "Tab 顺序必须与 COMPONENT_CATEGORIES 一致")
        self.assertEqual(sum(len(v) for v in groups.values()), 24)
        for name, keys in groups.items():
            self.assertEqual({c.key for c in keys}, EXPECTED_MEMBERSHIP[name], name)

    def test_every_category_is_nonempty(self):
        groups = main.group_components(main.build_components())
        for name, keys in groups.items():
            self.assertTrue(keys, f"分类 {name} 是空的，Tab 会是空白页")


class MainWindowUsesTabs(unittest.TestCase):
    """真实构造 MainWindow，只把「联网抓版本」和「探测已装版本」两件事停下——
    本用例要验的是卡片挂在哪个 Tab 上，不是网络与探测。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication, QTabWidget
        cls.app = QApplication.instance() or QApplication([])
        cls.QTabWidget = QTabWidget
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

    def _tab_labels(self):
        return [self.win.tabs.tabText(i) for i in range(self.win.tabs.count())]

    def test_tabs_are_horizontal_at_the_top(self):
        from PySide6.QtWidgets import QTabWidget
        self.assertEqual(self.win.tabs.tabPosition(), QTabWidget.North)

    def test_three_tabs_in_the_agreed_order_with_counts(self):
        self.assertIsInstance(self.win.tabs, self.QTabWidget)
        self.assertEqual(self._tab_labels(), [
            f"{name}（{len(EXPECTED_MEMBERSHIP[name])}）"
            for name in EXPECTED_MEMBERSHIP
        ])

    def test_cards_live_in_their_category_tab(self):
        groups = main.group_components(self.win.components)
        for idx, name in enumerate(EXPECTED_MEMBERSHIP):
            page = self.win.tabs.widget(idx)
            keys_in_page = {c.component.key
                            for c in page.findChildren(main.ComponentCard)}
            self.assertEqual(keys_in_page, EXPECTED_MEMBERSHIP[name], name)
            self.assertEqual(len(keys_in_page), len(groups[name]))
            # Tab 标题上的数字必须等于该页真实卡片数，不能是写死的
            self.assertIn(str(len(keys_in_page)), self.win.tabs.tabText(idx))

    def test_flat_card_list_is_still_complete(self):
        # 刷新版本 / 存配置 / 关窗等待都靠这个平铺列表，分组不能把它弄缺
        self.assertEqual({c.component.key for c in self.win.cards}, ALL_KEYS)
        self.assertEqual(len(self.win.cards), 24)


if __name__ == "__main__":
    unittest.main(verbosity=2)
