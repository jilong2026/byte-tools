"""组件四类分组 + Tab 页布局的规格测试（离线，不联网）。

分类标准（2026-09-28 与用户确认；2026-10-08 增加「一键启停」）：
  开发环境 = 装完进 PATH、直接用来写/编译/打包代码（语言运行时 + 构建与版本工具）
  开发软件 = 本地跑起来给项目当依赖、但本工具**还不能一键启停**的服务（数据库 / 消息队列）
  一键启停 = 卡片上有「启动 / 停止」按钮的组件，成员由 LAUNCH_KEYS 派生，不是第二张表
  其它软件 = 不参与写代码的运维与交付外围（容器 / 编排）

「一键启停」排在「其它软件」之前（2026-10-08 用户要求）：它是本工具最能干活的一组长，
埋在倒数第二个 Tab 里等于藏起来。
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

EXPECTED_MEMBERSHIP = {
    "开发环境": {"jdk", "python", "node", "go", "bun", "conda", "git", "maven",
               "gradle", "powershell"},
    # 剩下的服务型组件还不能一键启停（数据目录/端口/前置运行时的收尾还没做），
    # 留在「开发软件」里 —— 它们接进框架后会自动挪到「一键启停」。
    "开发软件": {"mysql", "mongodb", "postgresql", "pulsar"},
    # 「一键启停」这一组的成员就是卡片上有启动/停止按钮的那些（LAUNCH_KEYS），
    # 位置固定在「其它软件」之前（2026-10-08 用户要求）。这里手写一份清单是为了让
    # "扩白名单 = 必须同时改这张表"变成一次可见的改动：
    # 下面 test_launch_tab_membership_is_derived_from_the_whitelist 会把两边钉在一起。
    "一键启停": {"jenkins", "nacos", "activemq", "rocketmq", "nginx", "kafka",
               "tomcat", "elasticsearch", "rabbitmq", "seata"},
    "其它软件": {"docker", "kubectl"},
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
            if getattr(comp, "hidden", False):
                continue        # 隐藏的前置组件（erlang）不进任何 Tab
            got[comp.category].add(comp.key)
        self.assertEqual(got, EXPECTED_MEMBERSHIP)

    def test_no_component_is_left_unclassified(self):
        # 2026-10-08 起多了 erlang —— 它是 rabbitmq 的前置运行时，
        # **隐藏组件**（不出现在界面），所以它在 build_components() 里、
        # 不在分类成员表里。这里把两件事都钉住：
        self.assertEqual({c.key for c in self.components}, ALL_KEYS | {"erlang"})
        self.assertEqual(len(self.components), 27)
        visible = sum(len(v) for v in main.group_components(self.components).values())
        self.assertEqual(visible, 26, "隐藏组件不许出现在任何 Tab 里")


class GroupComponentsHelper(unittest.TestCase):
    def test_grouping_preserves_order_and_covers_every_tab(self):
        groups = main.group_components(main.build_components())
        self.assertEqual(list(groups), list(EXPECTED_MEMBERSHIP),
                         "Tab 顺序必须与 COMPONENT_CATEGORIES 一致")
        self.assertEqual(sum(len(v) for v in groups.values()), 26)
        for name, keys in groups.items():
            self.assertEqual({c.key for c in keys}, EXPECTED_MEMBERSHIP[name], name)

    def test_every_category_is_nonempty(self):
        groups = main.group_components(main.build_components())
        for name, keys in groups.items():
            self.assertTrue(keys, f"分类 {name} 是空的，Tab 会是空白页")

    def test_launch_tab_membership_is_derived_from_the_whitelist(self):
        """「一键启停」的成员**必须**等于 LAUNCH_KEYS，而不是第二张手写表。

        这张 Tab 的准入条件是"卡片上有启动/停止按钮"，那个条件由 LAUNCH_OF 决定；
        再维护一份分类清单的话，接进第 11 个组件时就会出现"能启动、但人在别的 Tab 里"
        —— 那正是本次要消灭的现象（计划二的账本里记着同一件事）。
        """
        groups = main.group_components(main.build_components())
        self.assertEqual({c.key for c in groups["一键启停"]}, set(main.LAUNCH_KEYS))

    def test_launch_tab_sits_right_before_the_other_software_tab(self):
        names = list(main.COMPONENT_CATEGORIES)
        self.assertEqual(names.index("一键启停") + 1, names.index("其它软件"),
                         "「一键启停」必须紧贴在「其它软件」前面")


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

    def test_four_tabs_in_the_agreed_order_with_counts(self):
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
        self.assertEqual(len(self.win.cards), 26)


if __name__ == "__main__":
    unittest.main(verbosity=2)
