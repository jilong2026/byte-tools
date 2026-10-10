"""组件分类分组 + Tab 页布局的规格测试（离线，不联网）。

分类标准（2026-09-28 与用户确认；2026-10-08 增加「一键启停」；2026-10-10 增加「开发工具」并取消「其它软件」）：
  开发环境 = 装完进 PATH、直接用来写/编译/打包代码（语言运行时 + 构建与版本工具）
  开发软件 = 本地跑起来给项目当依赖的服务（数据库 / 消息队列 / 注册中心 / 搜索）+ 容器与编排外围
             （docker / kubectl 从原「其它软件」并进来 —— 用户要求少一个 Tab）
  开发工具 = **只下载**的 GUI 软件（IDE / 数据库客户端 / API 工具）：卡片只有「版本下拉 + 下载」，
             不解压、不配环境变量、不扫盘、不代跑安装器（见 Component.download_only 与 R13）
  一键启停 = 卡片上有「启动 / 停止」按钮的组件，成员由 LAUNCH_KEYS 派生，不是第二张表

「一键启停」固定是**最后一个** Tab：它是本工具最能干活的一组长，埋在中间等于藏起来
（原来那条"紧贴「其它软件」"的护栏因为「其它软件」被取消而改写成这条）。
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
    # docker / kubectl 是 2026-10-10 从「其它软件」并进来的：那个 Tab 只剩 2 张卡，
    # 用户要求取消它，于是"容器与编排外围"归到同为大件服务的这一组。
    "开发软件": {"mysql", "mongodb", "postgresql", "pulsar", "docker", "kubectl"},
    # 「开发工具」= 只下载、不配置的 GUI 软件（Component.download_only）。
    # 这 11 个 key 的准入条件与别的 Tab 不同：**不进 LAUNCH_KEYS、不写环境变量、
    # 磁盘上不落 ~/.env-tools/<key>/ 目录**，所以遍历全组件的老断言都要按能力位豁免。
    # 少掉的 Apipost / Apifox / HBuilderX / Lithe 不是"忘了加"，而是**拿不到可实测的
    # 官方直链**（前三家下载页全 JS 渲染、Lithe 官方仓库 404），按 R1 不许登记未实测的源。
    "开发工具": {"idea", "pycharm", "clion", "webstorm", "goland", "datagrip",
               "vscode", "dbx", "windterm", "wechat-devtools", "eclipse"},
    # 「一键启停」这一组的成员就是卡片上有启动/停止按钮的那些（LAUNCH_KEYS），
    # 固定排在最后。这里手写一份清单是为了让
    # "扩白名单 = 必须同时改这张表"变成一次可见的改动：
    # 下面 test_launch_tab_membership_is_derived_from_the_whitelist 会把两边钉在一起。
    "一键启停": {"jenkins", "nacos", "activemq", "rocketmq", "nginx", "kafka",
               "tomcat", "elasticsearch", "rabbitmq", "seata"},
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
        # 数量**从成员表派生**而不是写死：加组件时这里不该红，红的是
        # bt_download_only_tests.test_visible_component_count_is_38 那唯一一处评审点。
        # 这条仍然要留：上面比的是"键的集合"，重复登记同一个 key 它看不出来，
        # 只有比长度才会（清单里出现过两次 jenkins 就是这么被抓到的）。
        self.assertEqual(len(self.components), len(ALL_KEYS) + 1,
                         "组件清单里有重复 key，或有成员表外的组件混进来")
        visible = sum(len(v) for v in main.group_components(self.components).values())
        self.assertEqual(visible, len(ALL_KEYS), "隐藏组件不许出现在任何 Tab 里")


class GroupComponentsHelper(unittest.TestCase):
    def test_grouping_preserves_order_and_covers_every_tab(self):
        groups = main.group_components(main.build_components())
        self.assertEqual(list(groups), list(EXPECTED_MEMBERSHIP),
                         "Tab 顺序必须与 COMPONENT_CATEGORIES 一致")
        self.assertEqual(sum(len(v) for v in groups.values()), len(ALL_KEYS))
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

    def test_launch_tab_is_the_last_one(self):
        """「一键启停」固定是最后一个 Tab。

        原来这条断的是"紧贴「其它软件」前面"，2026-10-10「其它软件」被取消后失去
        指涉对象，但护栏的意图没变：最能干活的一组长不许埋在中间。
        """
        names = list(main.COMPONENT_CATEGORIES)
        self.assertEqual(names[-1], "一键启停",
                         "「一键启停」必须是最后一个 Tab，不许被新分类挤到中间")


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
        self.assertEqual(len(self.win.cards), len(ALL_KEYS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
