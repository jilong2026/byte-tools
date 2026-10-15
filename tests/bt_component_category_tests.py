"""组件分类分组 + Tab 页布局的规格测试（离线，不联网）。

分类标准（2026-09-28 与用户确认；2026-10-08 增加「一键启停」；2026-10-10 增加「开发工具」并取消「其它软件」；
2026-10-14 「开发软件」改名「服务端组件」并提到第二位）：
  开发环境 = 装完进 PATH、直接用来写/编译/打包代码（语言运行时 + 构建与版本工具），跑在**本机**上
  服务端组件 = 装在**服务器/集群**上、命令行操作的后台服务与运维组件
             （数据库 / 消息队列 / 网关 / 容器与编排 / K8s 运维）
             原名「开发软件」—— 那个名字太空，且和隔壁「开发工具」在中文里近乎同义词，
             用户分不清两个 Tab 的界线；新名字只说一件确凿的事：这 14 个全是后台组件，没有 GUI。
  开发工具 = **只下载**的 GUI 软件（IDE / 数据库客户端 / API 工具）：卡片只有「版本下拉 + 下载」，
             不解压、不配环境变量、不扫盘、不代跑安装器（见 Component.download_only 与 R13）
  一键启停 = 卡片上有「启动 / 停止」按钮的组件，成员由 LAUNCH_KEYS 派生，不是第二张表

Tab 顺序（2026-10-14 用户要求）：

    一键启停 → 服务端组件 → 开发环境 → 开发工具

前一位是**能力**维度（能不能一键起停），后三位是**位置/形态**维度。
「一键启停」固定是**第一个** Tab：它是本工具最能干活的一组长，原先压在最右边。
这条护栏经历过三次改写 —— 2026-10-08 原为"紧贴「其它软件」"，2026-10-10「其它软件」
取消后改成"必须是最后一个"，2026-10-14 用户要求提到最前。护栏的意图始终没变：
**这一组不许被埋没在中间**。

「服务端组件」排第二位（原先是第三）：用户装东西时先问的是"装服务器上还是装本机"，
这个顺序直接对应那个问题。
"""
import os
import sys
import unittest

import platform as _platform


import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402

# 分类名一律走 CAT_* 常量，不写裸字符串 —— 改名时只改 main.py 一处，
# 这里漏改会表现为"断言拿不到那个 key"而不是静默通过。
CAT_LAUNCH, CAT_SERVER, CAT_ENV, CAT_TOOL, CAT_AGENT = (
    main.CAT_LAUNCH, main.CAT_SERVER, main.CAT_ENV, main.CAT_TOOL, main.CAT_AGENT,
)

EXPECTED_MEMBERSHIP = {
    # 「一键启停」这一组的成员就是卡片上有启动/停止按钮的那些（LAUNCH_KEYS）。
    # 2026-10-14 用户要求把它排到**第一个** Tab（原先固定最后）。
    # 这里手写一份清单是为了让"扩白名单 = 必须同时改这张表"变成一次可见的改动：
    # 下面 test_launch_tab_membership_is_derived_from_the_whitelist 会把两边钉在一起。
    CAT_LAUNCH: {"jenkins", "nacos", "activemq", "rocketmq", "nginx", "kafka",
                "tomcat", "elasticsearch", "rabbitmq", "seata", "redis",
                # 2026-10-12 并发那批接进启停白名单的服务
                "etcd", "consul", "zookeeper",
                # 2026-10-12 B4 补：minio（对象存储，API 9000 + 控制台 9001，
                # 真机实测过起停与端口释放）
                "minio"},
    CAT_SERVER: {"mysql", "mongodb", "postgresql", "pulsar", "docker", "kubectl",
               # 2026-10-12 B3/B5：nats-server / caddy / traefik 是服务型，
               # 先落这里，接进 LAUNCH_OF 后会自动挪到「一键启停」。
               # （etcd 已经接进去了，所以它不在这张表里 —— 它和 consul / zookeeper
               #   一起出现在「一键启停」，两边同时登记会让本表比出差异。）
               "nats-server", "caddy", "traefik", "helm",
               # 2026-10-12 并发那批补的服务型 CLI
               "k9s", "trivy", "docker-compose",
               # 2026-10-12 B7：JMeter（压测服务型，需 JDK 前置）
               "jmeter"},
    # 「开发工具」= 只下载、不配置的 GUI 软件（Component.download_only）。
    # 这 17 个 key 的准入条件与别的 Tab 不同：**不进 LAUNCH_KEYS、不写环境变量、
    # 磁盘上不落 ~/.env-tools/<key>/ 目录**，所以遍历全组件的老断言都要按能力位豁免。
    # 2026-10-10 第二批补进 6 个：apipost / hbuilderx / apifox / android-studio /
    # visual-studio / navicat。前三个当初被我判成"拿不到直链"是**误判**（只搜了
    # `.exe`/`.zip` 字面量就收工，漏了 dl.php 分发器与 release.json），订正见 R13.4。
    # 仍然没进表的是"取不到证"的那几个（Xshell / Xftp 全域 http=000、Fleet 官方目录
    CAT_ENV: {"jdk", "python", "node", "go", "bun", "conda", "git", "maven",
               "gradle", "powershell",
               # 2026-10-12 新增：语言/编译器工具链（kotlin 的 zip、rust 的 MSI 提取、
               # graalvm 自带 JDK，三者都是解压/提取进 PATH 即用）
               "kotlin", "graalvm", "rust",
               # 2026-10-12 B1：单二进制、无 XXX_HOME（protoc 的 zip 顶层是 bin/+include/，
               # uv 的 zip 顶层 0 个目录 —— 这条路径的两个变体）
               "protoc", "uv",
               # 2026-10-12 B3/B5：GitHub Releases 单二进制批（CLI 全家桶 + 构建工具）
               "deno", "ninja", "duckdb", "cmake", "ripgrep", "fd", "bat",
               "eza", "zoxide", "fzf", "yq", "pnpm",
               # 2026-10-12 并发那批补的运行时与 CLI
               "dotnet-sdk", "sqlite", "jq",
               # 2026-10-12 B7：Ant（构建工具）
               "ant",
               # 2026-10-12 Dart（语言运行时；zip 顶层单目录 dart-sdk/ ⇒ bin）
               "dart"},
    # 剩下的服务型组件还不能一键启停（数据目录/端口/前置运行时的收尾还没做），
    # 留在「服务端组件」里 —— 它们接进框架后会自动挪到「一键启停」。
    # docker / kubectl 是 2026-10-10 从「其它软件」并进来的：那个 Tab 只剩 2 张卡，
    # 用户要求取消它，于是"容器与编排外围"归到同为大件服务的这一组。
    # 已无此产品、Xcode 只走 Mac App Store），清单在 bt_download_only_tests.DEFERRED_KEYS。
    CAT_TOOL: {"idea", "pycharm", "clion", "webstorm", "goland", "datagrip",
               "vscode", "dbx", "windterm", "wechat-devtools", "eclipse",
               "apipost", "apifox", "hbuilderx", "android-studio",
               "visual-studio", "navicat",
               # 2026-10-12 B6a：与 MySQL / Mongo / PG / Redis 一一配套的客户端
               # （成本最低的一批：只加 URL，不碰解压/环境变量任何一条逻辑）
               "dbeaver", "heidisql", "bruno", "redisinsight", "ardm",
               "mongodb-compass", "pgadmin4", "mysql-workbench", "postman"},
    # 「Agent客户端」：2026-10-15 用户要求新增的第五个 Tab，**放在最后**。
    # 形态与「开发工具」同类 —— 只下载、不配置，登记表在 main.py 的 `_AGENT_CLIENTS`
    # （表驱动，key 从那里来；这里手写一份是为了让"扩表 = 必须同时改这张基线"可见）。
    CAT_AGENT: {"cursor", "zcode", "claude-code", "codex-cli", "qoderwork-cn"},
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
        self.assertEqual({c.key for c in groups[CAT_LAUNCH]}, set(main.LAUNCH_KEYS))

    def test_launch_tab_is_the_first_one(self):
        """「一键启停」固定是第一个 Tab。

        这条断言换过三次方向，但意图一直没变：**这一组不许被埋在中间**。
        2026-10-08 原为"紧贴「其它软件」前面"；2026-10-10「其它软件」取消后
        改成"必须是最后一个"；2026-10-14 用户要求提到最前，于是断第一个。
        """
        names = list(main.COMPONENT_CATEGORIES)
        self.assertEqual(names[0], CAT_LAUNCH,
                         "「一键启停」必须是第一个 Tab，不许被别的分类挤到后面")

    def test_tab_order_is_exactly_launch_server_env_tool_agent(self):
        """整个 Tab 顺序钉死：一键启停 → 服务端组件 → 开发环境 → 开发工具 → Agent客户端。

        2026-10-14 用户要求「开发软件」改名「服务端组件」并提到第二位。
        2026-10-15 用户要求新增「Agent客户端」并明确**放最后**。
        只断"第一个是一键启停"是不够的 —— 那样"服务端组件"被谁挤到第三、
        或者新增的 Tab 插到中间，测试都不会红，而用户看到的是完全不同的信息架构。
        """
        self.assertEqual(
            list(main.COMPONENT_CATEGORIES),
            [CAT_LAUNCH, CAT_SERVER, CAT_ENV, CAT_TOOL, CAT_AGENT],
            "Tab 顺序必须是「一键启停 → 服务端组件 → 开发环境 → 开发工具 → Agent客户端」")

    def test_server_tab_is_the_second_one(self):
        """单独再断一次第二位。

        上一条已经断了整个顺序，这里单拎出来是为了**失败信息能说人话**：
        出问题时不用在一长串列表里比对，就能直接看到是"服务端组件"跑错位置。
        """
        names = list(main.COMPONENT_CATEGORIES)
        self.assertEqual(
            names.index(CAT_SERVER), 1,
            "「服务端组件」必须是第二个 Tab（用户装东西先问的是装服务器还是装本机）")

    def test_no_category_keeps_the_old_name(self):
        """旧名「开发软件」不许以任何形式留在分类里。

        改名这种事最容易出的事故不是"忘了改"，而是"改了一半"：某个组件还指着
        旧分类名，于是它既不在任何 Tab 里、也不在任何断言的眼里 —— 界面上
        就是**凭空少一张卡片**，而测试全绿。这条专门钉这个。
        """
        old = "开发软件"
        self.assertNotIn(old, main.COMPONENT_CATEGORIES,
                         f"COMPONENT_CATEGORIES 里还留着旧名 {old}")
        strays = {c.key: c.category for c in main.build_components()
                  if c.category == old}
        self.assertEqual(strays, {},
                         f"这些组件还挂在旧分类 {old} 上（会从界面上消失）: {strays}")

    def test_color_map_keys_still_match_the_categories(self):
        """卡片无图标时的**分类色块**必须还能对上分类名。

        这处颜色映射（ComponentCard._render_icon 的 fallback）历史上就是按分类名
        取色的，键对不上不会报错 —— 只会安静地落进兜底灰色，整个 Tab 的无图标
        组件一起变灰块。改名时它最容易漏，因为漏了不产生任何异常。
        """
        import inspect
        src = inspect.getsource(main.ComponentCard._render_icon)
        self.assertIn("CAT_SERVER", src,
                      "分类颜色映射里没有服务端组件 —— 无图标组件会掉进兜底灰色")
        self.assertNotIn('"开发软件"', src, "颜色映射里还留着旧分类名")


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
