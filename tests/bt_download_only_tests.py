"""「开发工具」Tab（只下载型组件）的规格测试（离线，不联网）。

设计出处：docs/superpowers/plans 与 .qoder/plans 里的「开发工具 Tab」方案，规则 R13。

这批组件与其余 26 个的**根本差别**是它只干两件事：列版本、把官方安装包下到用户挑的目录。
因此它必须**不**做下面每一件事，而每一件都有对应用例钉住 ——
不是"顺手没实现"，而是"实现了就是错"：

  - 不解压、不落 ~/.env-tools/<key>/ 目录（磁盘上根本不该出现这个 key）
  - 不写 XXX_HOME / PATH，不碰注册表与 shell rc
  - 建卡时不扫盘、不跑 `<exec> --version`
  - 下拉框不挂"已装"绿勾、卡片不显示「可多版本」角标
  - 没有「切换」「卸载」「启动」「停止」「控制台」按钮
  - **绝不代跑安装器**：静默跑安装器等于替用户点了授权协议

URL 一律按 R1 实测过才登记（状态码 + 魔数 + 吞吐），实测矩阵见 DEVELOPMENT.md R1.5。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import platform as _platform


import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402
from bt_component_category_tests import EXPECTED_MEMBERSHIP  # noqa: E402
# 复用对面那套沙箱：它把 CONFIG_DIR / CONFIG_FILE / shell rc / 注册表读写全重定向到临时目录。
# 本文件的用例要真建卡片，不沙箱化就会去扫用户真实的 ~/.env-tools（甚至写他的 config.json）。
from bt_multiversion_tests import EnvSandbox as _EnvSandbox  # noqa: E402

# 造任何 QWidget 之前必须先有 QApplication，否则 Qt 直接 abort() —— 症状是进程以
# 127 退出、日志里一行 traceback 都没有，极易被误判成"命令没跑起来"。
#
# 注：原注释写的是"整套 discover 时对面 bt_grid_layout_tests 会先把 app 建好，
# 所以这条只在单独跑本文件时才暴露"。那句话是**错的**：bt_*_tests.py 不匹配任何
# 默认 discover pattern（unittest 要 test*.py、pytest 要 test_*.py / *_test.py），
# `unittest discover` 与 pytest 都是**收集到 0 条**，"整套 discover"从来没发生过。
# 现在统一由 run_all_tests.py 逐文件起子进程来跑（每个进程自建 app）。
# 前置三段（WMI 桩 / offscreen / sys.path）已收敛到 _btprelude。
from PySide6.QtWidgets import QApplication  # noqa: E402
_APP = QApplication.instance() or QApplication([])

# 这一批的 key 清单。它是"加一个只下载组件要过一遍评审"的那个点：
# 成员表在对面（bt_component_category_tests.EXPECTED_MEMBERSHIP），这里只挑出下载型的那些。
# 「只下载」型的**全部**成员 = 「开发工具」∪「Agent客户端」（2026-10-15 起）。
# 两个 Tab 的能力位语义完全相同（download_only=True、不落盘、不配环境变量），
# 所以基线必须是**并集**：只写"开发工具"会让新 Tab 的 5 个组件被下面
# `test_flag_defaults_to_false_for_the_established_twenty_six` 误判成"不该标只下载"。
DOWNLOAD_ONLY_KEYS = (set(EXPECTED_MEMBERSHIP["开发工具"])
                      | set(EXPECTED_MEMBERSHIP["Agent客户端"]))

# 用户点名要、但这一版**没进表**的候选。登记一个没实测过的源违反 R1（200 也可能是
# 拿 HTML 应付的假源），所以宁可少几个也不硬凑；这张表存在的意义是别让人以为"漏了"。
# 2026-10-10 第二批：Apipost / Apifox / HBuilderX 已从本表移出并进了 Tab ——
# 当初"拿不到直链"的判定是错的（我只搜了 `.exe`/`.zip` 字面量就收工），
# 真源分别是 dl.php 分发器、cdn 上的 electron-updater latest.yml、release.json。
DEFERRED_KEYS = {
    "xshell": "netsarang.com / cdn.netsarang.net 本机全域 http=000，取不到任何证据",
    "xftp": "同上（同一家厂商、同一组域名）",
    "fleet": "JetBrains 官方产品目录 82 个产品里没有 Fleet，?code=FLEET 回空对象 —— 独立版已停",
    "xcode": "macOS 独占且只走 Mac App Store / Apple 开发者账号，Windows 侧无可下直链",
    "lithe": "官方仓库 1lck/Lithe-IDEA 经 API 已 404，新仓库 0 个 release",
}


class TabStructure(unittest.TestCase):
    def setUp(self):
        self.components = main.build_components()
        self.groups = main.group_components(self.components)

    def test_dev_tools_tab_is_the_fourth_and_holds_the_eleven_keys(self):
        """Tab 顺序钉死（2026-10-14~15 用户三次调整过）。

        变更史：「一键启停」从最后提到第一；「开发软件」改名「服务端组件」并提到第二位；
        2026-10-15 新增第五个 Tab「Agent客户端」并**明确放最后**。
        本用例原名 test_new_tab_is_the_third_and_holds_the_eleven_keys —— 那是在
        「开发工具」刚是第三个 Tab 时写的，名字里的 "third" 早就不成立，已改成按名字断言
        （按位置断言的用例每次改顺序都必然失效，得跟着改）。
        """
        self.assertEqual(list(main.COMPONENT_CATEGORIES),
                         [main.CAT_LAUNCH, main.CAT_SERVER, main.CAT_ENV,
                          main.CAT_TOOL, main.CAT_AGENT],
                         "Tab 顺序必须是「一键启停 → 服务端组件 → 开发环境 → "
                         "开发工具 → Agent客户端」")
        self.assertEqual({c.key for c in self.groups[main.CAT_TOOL]},
                         set(EXPECTED_MEMBERSHIP["开发工具"]))

    def test_agent_client_tab_is_the_fifth_and_holds_its_keys(self):
        """第五个 Tab 是「Agent客户端」且**必须排在最后**（2026-10-15 用户指定）。

        与「开发工具」同类：只下载不配置。这里同时钉住"它是最末一个"——
        用户要的是"末尾新增"，插到中间就不是他要的东西了。
        """
        self.assertEqual(list(main.COMPONENT_CATEGORIES)[-1], main.CAT_AGENT,
                         "「Agent客户端」必须是最后一个 Tab")
        self.assertEqual({c.key for c in self.groups[main.CAT_AGENT]},
                         set(EXPECTED_MEMBERSHIP["Agent客户端"]))
        for c in self.groups[main.CAT_AGENT]:
            self.assertTrue(c.download_only,
                            f"{c.key} 在「Agent客户端」里却不是只下载型")

    def test_other_software_tab_is_gone(self):
        """用户要求少一个 Tab：「其它软件」整个取消，不是留一张空白页。

        这条必须单独钉：`group_components` 给每个分类都建空列表、建 Tab 的循环
        **不跳过空组**，所以只要 COMPONENT_CATEGORIES 里还留着这个名字，
        界面上就会多出一个「其它软件（0）」。
        """
        self.assertNotIn("其它软件", main.COMPONENT_CATEGORIES)
        self.assertNotIn("其它软件", {c.category for c in self.components})

    def test_docker_and_kubectl_now_live_in_server_components(self):
        """原「其它软件」那两张卡并进「服务端组件」，不许变成无家可归。"""
        server = {c.key for c in self.groups[main.CAT_SERVER]}
        self.assertIn("docker", server)
        self.assertIn("kubectl", server)

    def test_eclipse_is_the_one_batch_member_with_real_mainland_mirrors(self):
        """Eclipse 官方 CDN 本机实测只有 25 KB/s（378MB 等于下不动），而清华 2.7–3.9 MB/s。

        四个源都回**同一个字节数** 377,592,420 且魔数 `PK`，所以镜像是真镜像不是软 404。
        顺序按 R1：清华 → 阿里 → 华为 → 官方末位。
        """
        comp = next(c for c in self.components if c.key == "eclipse")
        urls = comp.versions[0].urls_for_current()
        self.assertGreaterEqual(len(urls), 4, f"Eclipse 源不够：{urls}")
        self.assertIn("mirrors.tuna.tsinghua.edu.cn", urls[0])
        self.assertIn("download.eclipse.org", urls[-1], "末位必须是官方")
        for u in urls[:-1]:
            self.assertIn("mirrors.", u, f"排在官方前面的必须是大陆镜像：{u}")

    def test_deferred_candidates_are_still_absent(self):
        """没实测到官方直链的候选，不许被"顺手补上"。

        补的前提是先按 R1 实测（状态码 + 魔数 + 累计字节/吞吐），然后把 key 加进
        EXPECTED_MEMBERSHIP 与 build_components，最后删掉这条用例里的对应项。
        """
        keys = {c.key for c in self.components}
        for key in DEFERRED_KEYS:
            self.assertNotIn(key, keys, f"{key} 的源没实测过就登记了")

    def test_visible_component_count_is_127(self):
        """**全仓库唯一一处**写死界面可见组件数的地方（80 全流程 + 36 只下载 + 64 Agent客户端）。

        其它套件的数字都改成从成员表派生，只有这里保留绝对值：
        加组件时必须在这里过一次手，逼着人确认"这个数字变了是有意为之"。
        2026-10-12 一路累加：47 → 49（protoc/uv）→ 58（B6a 九个只下载）→ 75（+pnpm/helm）
        → 83（B3/B5 与并发那批）→ 85（B7 的 ant / jmeter）→ 86（B4 补的 minio）
        → 87（Dart）→ 92（2026-10-15 新增「Agent客户端」首批 5 个）
        → 120（2026-10-15 第二批 28 个 Agent 客户端，含 5 个只有「官网下载」的）
        → 127（2026-10-15 第三批大厂助手 7 个，含 1 个只有「官网下载」的）
        → 128（同日补 opencode，它有实测直链，不是「官网下载」那一档）
        → 139（同日第四批 11 个：9 个有实测直链 + gemini-cli / aider 两个只有官网入口）
        → 161（同日第五批 22 个：12 个 Agent + 10 个开发工具，全部有实测直链）
        → **180（同日第六批 19 个：9 个服务端/运维 + 10 个语言与开发 CLI，
        全部"解压即用"、归档布局已用 bt_archive_layout_audit 逐个验过）**。
        方法名里的 127 是历史名，不改 —— 改名的收益抵不上一次全仓库检索。
        """
        visible = sum(len(v) for v in self.groups.values())
        self.assertEqual(visible, 180)
        self.assertEqual(len(self.components), 181, "180 可见 + 隐藏的 erlang")


class CapabilityFlag(unittest.TestCase):
    def setUp(self):
        self.components = main.build_components()

    def _by_key(self):
        return {c.key: c for c in self.components}

    def test_flag_defaults_to_false_for_the_established_twenty_six(self):
        """默认值必须是 False：老组件一行没改就得保持原样，这是整期的安全前提。"""
        for comp in self.components:
            if comp.key not in DOWNLOAD_ONLY_KEYS:
                self.assertFalse(comp.download_only,
                                 f"{comp.key} 被误标成只下载")

    def test_flag_marks_exactly_the_new_batch(self):
        got = {c.key for c in self.components if c.download_only}
        self.assertEqual(got, DOWNLOAD_ONLY_KEYS)

    def test_download_only_implies_not_multi_version_and_no_side_effects(self):
        """能力位一置上，那几样"会碰系统"的配件必须同时为空 —— 不靠调用方自觉。"""
        for comp in self.components:
            if not comp.download_only:
                continue
            self.assertFalse(comp.multi_version,
                             f"{comp.key} 只下载却还标着可多版本，界面会长出角标")
            self.assertIsNone(comp.launch, f"{comp.key} 只下载却挂了启停规格")
            self.assertIsNone(comp.env_var, f"{comp.key} 只下载还想写 XXX_HOME")
            self.assertIsNone(comp.exec_name,
                              f"{comp.key} 只下载却配了可执行名，探测会去跑它")
            self.assertFalse(comp.installer_mode,
                             f"{comp.key} 只下载却走安装器模式 = 代用户跑安装程序")

    def test_every_download_only_component_has_windows_urls_to_download(self):
        """卡片上「下载」要点得动：每个版本至少有一个 Windows 直链。

        ⚠ 「官网下载」那一档（`official_page_only`）**没有版本表**，本文用不上它
        —— 它的两条约束由下面 `WebFallback` 单独钉（必须登记了官网、且不挂版本表）。
        """
        for comp in self.components:
            if not comp.download_only:
                continue
            if comp.official_page_only:
                continue          # 见 docstring：走「官网下载」，没有版本可数
            self.assertTrue(comp.versions, f"{comp.key} 没有可选版本")
            for cv in comp.versions:
                urls = cv.urls_for_current()   # 方法在 ComponentVersion 上，不在 Component 上
                self.assertTrue(urls, f"{comp.key} {cv.version} 在当前平台没有 URL")


class WebFallback(unittest.TestCase):
    """「官网下载」那一档的硬约束（2026-10-15 新增，对应 R21）。

    用户 2026-10-15 的要求：拿不到官方直链的组件**也要收进来**，卡片主按钮给一颗
    「官网下载」，点了用 `QDesktopServices.openUrl()` 打开官网让用户自己下。
    这条路径没有下载 URL 可校验，所以护栏改钉三件更基本的事 —— 少任何一件，
    用户点下去要么打开空白页、要么看到一张自相矛盾的卡。
    """

    def setUp(self):
        self.components = main.build_components()

    def test_web_only_components_have_a_registered_official_url(self):
        """按钮点开必须有个**真**地址 —— 没登记的话 on_open_official_page_clicked 只会报错。"""
        for comp in self.components:
            if not comp.official_page_only:
                continue
            self.assertTrue(
                comp.official_url,
                f"{comp.key} 标了官网下载却没登记官网地址（COMPONENT_OFFICIAL_URLS 漏了），"
                f"按钮点开是空的")
            self.assertTrue(
                comp.official_url.startswith("https://"),
                f"{comp.key} 的官网地址不是 https：{comp.official_url}")

    def test_web_only_components_have_no_version_table(self):
        """自相矛盾的两件事不许同时成立：既然有可直接下载的版本，就不该走官网下载。"""
        for comp in self.components:
            if not comp.official_page_only:
                continue
            self.assertEqual(
                comp.versions, [],
                f"{comp.key} 标了官网下载，却还挂着版本表 "
                f"{[cv.version for cv in comp.versions]} —— 要么给直链、要么走官网，别两头占")

    def test_web_only_implies_download_only(self):
        """官网下载是**只下载**的弱化档，不许出现在会写环境变量的组件上。"""
        for comp in self.components:
            if comp.official_page_only:
                self.assertTrue(
                    comp.download_only,
                    f"{comp.key} 标了官网下载却不是只下载型 —— official_page_only 只对只下载型有意义")

    def test_github_assets_put_the_accelerator_first_and_the_bare_url_last(self):
        """GitHub 产物（DBX / WindTerm）本机实测裸地址连不上，加速器必须排在前面。"""
        for key in ("dbx", "windterm"):
            comp = next(c for c in self.components if c.key == key)
            urls = comp.versions[0].urls_for_current()
            self.assertGreaterEqual(len(urls), 2, f"{key} 没配加速器源")
            self.assertTrue(urls[-1].startswith("https://github.com/"),
                            f"{key} 末位必须是 GitHub 裸地址：{urls[-1]}")
            self.assertTrue(any("gh-proxy" in u for u in urls[:-1]),
                            f"{key} 前面要有加速器")

    def test_jetbrains_batch_claims_no_mainland_mirror(self):
        """实测过：华为云那个 jetbrains 目录回 200 但只有 12KB HTML（假源），南大 404。

        所以这六个只能官网直链 —— 与 R1「镜像优先」相反，是实测例外，
        不许以后为了过某个"每组件都要两个大陆源"的用例去硬凑假源。
        """
        for key in ("idea", "pycharm", "clion", "webstorm", "goland", "datagrip"):
            comp = next(c for c in self.components if c.key == key)
            urls = comp.versions[0].urls_for_current()
            self.assertTrue(urls, f"{key} 没有 URL")
            for u in urls:
                self.assertIn("jetbrains.com", u, f"{key} 混进了未实测的源：{u}")


class CardShape(_EnvSandbox):
    """卡片形态：只该有「版本下拉 + 下载」，别的一律不创建。

    判据统一是**不创建节点**而不是创建后隐藏 —— 与「可多版本」角标同一条纪律：
    隐藏着的按钮会被 findChild 查到、被布局算进格子宽度、被以后的代码误用。
    """

    def setUp(self):
        super().setUp()
        # EnvSandbox 为了让自己那些用例不碰磁盘，把 _detect_status 停成了空函数。
        # 本类要验的**恰恰就是**建卡时到底扫没扫盘、胶囊写了什么，所以把真实现接回来
        # （沙箱的 addCleanup 仍会在用例结束时还原，不影响别的类）。
        main.ComponentCard._detect_status = self._orig_detect

    def _card(self, key):
        comp = next(c for c in main.build_components() if c.key == key)
        return main.ComponentCard(comp, lambda lvl, msg: None)

    def test_card_creates_no_switch_uninstall_or_launch_button(self):
        for key in sorted(DOWNLOAD_ONLY_KEYS):
            card = self._card(key)
            with self.subTest(key=key):
                for attr in ("btn_configure", "btn_uninstall", "btn_start", "btn_console"):
                    self.assertFalse(hasattr(card, attr),
                                     f"{key} 长出了 {attr}：它只该能下载")
                self.assertTrue(hasattr(card, "btn_install"),
                                f"{key} 连主按钮都没有")

    def test_building_a_card_does_not_touch_the_disk(self):
        """建卡不许扫盘、不许执行组件命令 —— 只下载的东西磁盘上根本没有。"""
        calls = []
        orig_dirs = main.Component.installed_dirs
        orig_detect = main.Component.detect
        self.addCleanup(setattr, main.Component, "installed_dirs", orig_dirs)
        self.addCleanup(setattr, main.Component, "detect", orig_detect)

        def spy_dirs(self, *a, **k):
            calls.append(self.key)
            return orig_dirs(self, *a, **k)

        def spy_detect(self, *a, **k):
            calls.append("detect:" + self.key)
            return orig_detect(self, *a, **k)

        main.Component.installed_dirs = spy_dirs
        main.Component.detect = spy_detect

        self._card("idea")
        self.assertEqual(calls, [], "只下载型组件建卡时扫了盘或探测了可执行文件")
        # 反向对照：老组件确实会走这条路，说明上面那个探针不是空转
        self._card("jdk")
        self.assertTrue(calls, "探针没生效：连 jdk 建卡都没调用 installed_dirs/detect")

    def test_combo_lists_exactly_the_registered_versions_with_no_checkmarks(self):
        """下拉框只列官方版本，不合成"磁盘上已装"的项，也不挂绿勾。

        绿勾的判据是磁盘上有没有那个版本目录 —— 只下载型永远没有，
        但一旦有人以后给它加了"装到本工具目录"的能力，勾会悄悄长出来，所以这里直接断图标。
        """
        from PySide6.QtCore import Qt
        for key in ("idea", "vscode", "dbx"):
            comp = next(c for c in main.build_components() if c.key == key)
            card = self._card(key)
            with self.subTest(key=key):
                texts = [card.version_combo.itemText(i)
                         for i in range(card.version_combo.count())]
                self.assertEqual(texts, [v.version for v in comp.versions],
                                 "下拉框被合成了磁盘项，或版本没列全")
                for i in range(card.version_combo.count()):
                    self.assertFalse(card.version_combo.itemData(i, Qt.DecorationRole),
                                     f"{key} 第 {i} 项挂了图标（绿勾）")

    def test_status_capsule_never_claims_installed_or_unconfigured(self):
        """胶囊不许说"✓ 已配置"或"● 未安装"—— 这两个结论对只下载的东西都是假的。"""
        card = self._card("clion")
        text = card.status_label.text()
        self.assertNotIn("已配置", text)
        self.assertNotIn("未安装", text)
        self.assertIn("下载", text, f"胶囊要如实说明它只提供下载：{text!r}")


class RealWindowTabs(unittest.TestCase):
    """真构造一次窗口：Tab 标题、卡片归属、状态条与搜索分母都要跟着变。"""

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

    def test_tab_titles_carry_the_new_counts(self):
        self.assertEqual([self.win.tabs.tabText(i)
                          for i in range(self.win.tabs.count())],
                         [f"{name}（{len(EXPECTED_MEMBERSHIP[name])}）"
                          for name in EXPECTED_MEMBERSHIP])

    def test_status_bar_and_search_denominator_include_new_cards(self):
        """底部只写"组件：N"，搜索框右边也是同一个分母 —— 两处都得跟着涨。

        命中数用 `search_hint` 上的文字判，不用 `isVisible()`：窗口在这个用例里
        没有 show，Qt 对未显示的父窗口下的子控件一律报不可见，量出来永远是 0。
        """
        import re
        plain = re.sub("<[^>]+>", "", self.win.status_bar.text())
        self.assertIn(f"组件：{len(self.win.cards)}", plain)
        self.assertNotIn("其它软件", plain)
        self.win._apply_search("idea")
        try:
            hint = self.win.search_hint.text()
            self.assertIn(f"/ {len(self.win.cards)} 个组件", hint,
                          "搜索分母没跟着新 Tab 一起涨")
            m = re.search(r"匹配 (\d+)", hint)
            self.assertTrue(m and int(m.group(1)) >= 1,
                            f"搜 idea 命中不了新 Tab 里的组件：{hint!r}")
            hits = [c.component.key for c in self.win.cards
                    if main.component_matches(c.component, "idea")]
            self.assertIn("idea", hits)
        finally:
            self.win._apply_search("")


class _Sig:
    """最小信号替身：connect 存槽、emit 直接同步调。"""

    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in self.slots:
            fn(*a)


class _FakeWorker:
    """替掉真 DownloadWorker：记录构造参数，start() 后由测试决定发哪个信号。"""

    last = None

    def __init__(self, urls, dest, parent=None, expect_magic=b""):
        self.urls = list(urls)
        self.dest = Path(dest)
        self.expect_magic = expect_magic
        self.progress = _Sig()
        self.log = _Sig()
        self.finished_ok = _Sig()
        self.finished_fail = _Sig()
        self._running = False
        self.cancelled = False
        _FakeWorker.last = self

    def start(self):
        self._running = True

    def isRunning(self):
        return self._running

    def cancel(self):
        self.cancelled = True
        self._running = False

    # 测试用：模拟下载结束
    def _finish(self, ok=True, payload=""):
        self._running = False
        (self.finished_ok if ok else self.finished_fail).emit(payload)


class _Resp:
    """requests.get 的假响应：可控状态码、声明长度与正文。"""

    def __init__(self, body: bytes, declared=None):
        self._body = body
        self.headers = {"Content-Length": str(len(body) if declared is None else declared)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


class DownloadFlow(_EnvSandbox):
    """点「下载」之后：下到用户挑的目录、核对魔数、不解压、不写环境、记住目录。"""

    def setUp(self):
        super().setUp()
        main.ComponentCard._detect_status = self._orig_detect
        self._orig_worker = main.DownloadWorker
        self._orig_dialog = main.QFileDialog.getExistingDirectory
        self._orig_open = main._open_in_file_manager
        self._orig_install = main.install_downloaded
        self._orig_extract = main.extract_archive
        self._orig_msg = main.QMessageBox
        self.addCleanup(setattr, main, "DownloadWorker", self._orig_worker)
        self.addCleanup(setattr, main.QFileDialog, "getExistingDirectory", self._orig_dialog)
        self.addCleanup(setattr, main, "_open_in_file_manager", self._orig_open)
        self.addCleanup(setattr, main, "install_downloaded", self._orig_install)
        self.addCleanup(setattr, main, "extract_archive", self._orig_extract)
        main.DownloadWorker = _FakeWorker
        # 安装链路上的两个入口一旦被子类误用就是"给只下载组件写了注册表"，直接炸给测试看
        main.install_downloaded = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("只下载组件不许走 install_downloaded"))
        main.extract_archive = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("只下载组件不许解压"))
        # 默认「用户挑了第一项」。不桩掉的话真 QMenu.exec 会**阻塞**整个测试进程
        # （offscreen 也不会自己返回），现象是套件卡死而不是报错 —— 这条踩过一次。
        self._orig_pick = main.pick_download_artifact
        self.addCleanup(setattr, main, "pick_download_artifact", self._orig_pick)
        main.pick_download_artifact = lambda arts, parent=None, at=None: arts[0]

    def _card(self, key="idea"):
        comp = next(c for c in main.build_components() if c.key == key)
        return main.ComponentCard(comp, lambda lvl, msg: None)

    def test_button_is_labeled_download_and_starts_the_download_slot(self):
        picked = self.root / "somewhere"
        picked.mkdir()
        main.QFileDialog.getExistingDirectory = classmethod(
            lambda cls, *a, **k: str(picked))
        card = self._card("idea")
        # idea 有两种产物 → 标 ▾；只有一种的（windterm / eclipse / 微信）不标。
        self.assertEqual(card.btn_install.text(), "下载 ▾",
                         "只下载型组件的主按钮不能还叫「安装」，有第二种产物要标出可展开")
        card.on_download_clicked()
        w = _FakeWorker.last
        self.assertIsNotNone(w, "点下载没起 worker")
        cv = card.component.versions[0]
        self.assertEqual(w.urls, cv.urls_for_current(),
                         "worker 要拿到该版本按 R1 排好的源列表")
        self.assertEqual(w.dest.parent, picked, "文件必须落在用户挑的目录里")
        self.assertEqual(w.dest.name, f"idea-{cv.version}.exe",
                         "落盘名要带组件与版本，否则同名包会互相覆盖")
        self.assertEqual(w.expect_magic, b"MZ", "exe 安装包必须校验 MZ 魔数")

    def test_download_writes_neither_env_nor_active(self):
        picked = self.root / "dl"
        picked.mkdir()
        main.QFileDialog.getExistingDirectory = classmethod(
            lambda cls, *a, **k: str(picked))
        card = self._card("vscode")
        card.on_download_clicked()
        w = _FakeWorker.last
        w.dest.write_bytes(b"PK\x03\x04" + b"x" * 8)
        main.QMessageBox = _QuietBox(open_folder=False)
        w._finish(True, str(w.dest))
        self.assertEqual(self.win_env, {}, "只下载组件往注册表写了环境变量")
        self.assertEqual(self.win_path, [])
        cfg = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8")) \
            if main.CONFIG_FILE.exists() else {}
        self.assertLessEqual(set(cfg), {"download_dir"},
                             f"配置文件里多写了别的东西：{sorted(cfg)}")
        self.assertFalse((self.root / "vscode").exists(),
                         "只下载组件不许在 ~/.env-tools 下建目录")

    def test_download_dir_is_remembered_and_used_as_the_next_default(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir(); second.mkdir()
        seen = []

        def dialog(cls, parent=None, caption="", start="", *a, **k):
            seen.append(start)
            return str(second)

        main.QFileDialog.getExistingDirectory = classmethod(dialog)
        card = self._card("dbx")
        card.on_download_clicked()
        w = _FakeWorker.last
        w.dest.write_bytes(b"PK\x03\x04")
        main.QMessageBox = _QuietBox(open_folder=False)
        w._finish(True, str(w.dest))
        self.assertEqual(main.load_download_dir(), second, "没记住这次选的目录")
        card.on_download_clicked()
        self.assertEqual(Path(seen[-1]), second, "下次弹框的初值不是上次的目录")

    def test_missing_or_deleted_download_dir_falls_back_to_user_downloads(self):
        self.assertEqual(main.load_download_dir(), Path.home() / "Downloads")
        gone = self.root / "already-deleted"
        main.save_download_dir(gone)
        self.assertEqual(main.load_download_dir(), Path.home() / "Downloads",
                         "记录的目录被删了要回落默认，而不是把不存在的目录交回界面")

    def test_save_download_dir_merges_and_never_drops_other_keys(self):
        main.CONFIG_FILE.write_text(json.dumps({"view_mode": "list",
                                                "selections": {"jdk": "21"}}),
                                    encoding="utf-8")
        target = self.root / "keep"
        target.mkdir()
        main.save_download_dir(target)
        cfg = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("view_mode"), "list")
        self.assertEqual(cfg.get("selections"), {"jdk": "21"})
        self.assertEqual(cfg.get("download_dir"), str(target))

    def test_completion_offers_to_open_the_folder_and_never_runs_the_installer(self):
        picked = self.root / "done"
        picked.mkdir()
        main.QFileDialog.getExistingDirectory = classmethod(
            lambda cls, *a, **k: str(picked))
        opened = []
        main._open_in_file_manager = lambda p: opened.append(Path(p)) or True
        card = self._card("windterm")
        card.on_download_clicked()
        w = _FakeWorker.last
        w.dest.write_bytes(b"PK\x03\x04")
        box = _QuietBox(open_folder=True)
        main.QMessageBox = box
        w._finish(True, str(w.dest))
        self.assertTrue(box.asked, "下完没问用户要不要打开所在文件夹")
        self.assertEqual(opened, [picked], "「打开所在文件夹」要开目录本身")
        self.assertFalse(w.cancelled)
        self.assertTrue(card.btn_install.isEnabled(),
                        "下载结束后主按钮必须恢复可点")

    def test_magic_check_rejects_a_200_html_fake_source(self):
        """实测过的场景：华为云 jetbrains 目录回 200 + 12KB HTML。

        只比字节数的老校验会放它过关（12KB > 4096 下限），然后用户拿到一个
        后缀是 .exe、内容是网页的文件。魔数校验就是堵这个。
        """
        main.DownloadWorker = self._orig_worker
        dest = self.root / "idea-2026.2.3.exe"
        body = b"<html>" + b" " * 20000
        calls = []
        # 2026-10-14：桩点从 main.requests.get 移到 main.http_session。
        # 下载改走线程本地的 Session 复用连接（全文件原先零 Session，
        # 每次请求都要重做 TCP+TLS 握手）。桩要挂在**代码实际调用的那个对象**上，
        # 否则它会静默失效 —— 用例照样跑完，只是网络真出去了。
        orig_session = main.http_session

        class _Sess:
            def get(self, url, *a, **k):
                calls.append(url)
                return _Resp(body)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        self.addCleanup(setattr, main, "http_session", orig_session)
        main.http_session = lambda: _Sess()
        w = main.DownloadWorker(["https://mirrors.huaweicloud.com/jetbrains/x.exe"],
                                dest, None, b"MZ")
        results = []
        w.finished_ok.connect(results.append)
        w.finished_fail.connect(lambda m: results.append(("fail", m)))
        w.run()
        self.assertTrue(any(isinstance(r, tuple) for r in results),
                        "假源被判成功了 —— 魔数校验没生效")
        self.assertFalse(dest.exists(), "失败后必须把文件删掉，不许留半截")
        self.assertFalse(list(self.root.glob("*.part")), "临时文件也要清")

    def test_magic_check_stays_off_for_the_established_components(self):
        """默认不校验魔数：26 个老组件的行为必须逐字不变。"""
        main.DownloadWorker = self._orig_worker
        dest = self.root / "jdk-21.zip"
        # 桩点见上面那条用例的说明：下载走 main.http_session()
        orig_session = main.http_session

        class _Sess:
            def get(self, url, *a, **k):
                return _Resp(b"PK\x03\x04" + b"z" * 20000)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        self.addCleanup(setattr, main, "http_session", orig_session)
        main.http_session = lambda: _Sess()
        w = main.DownloadWorker(["https://example.invalid/jdk.zip"], dest)
        got = []
        w.finished_ok.connect(got.append)
        w.run()
        self.assertEqual(got, [str(dest)], "没传 expect_magic 时不该改变旧行为")


class _QuietBox:
    """替掉 QMessageBox：记录问没问过，回答由测试指定（open_folder=False 表示用户点「不了」）。

    产品码是以 `QMessageBox.question(parent, ...)` 这种类调用形式用的，所以这里给一个
    **实例**顶替类：实例属性 Yes/No 与实例方法 question 都能被那样调到。
    """

    Yes, No = 1, 0
    asked = False

    def __init__(self, open_folder: bool = True):
        self._open = open_folder

    def question(self, *a, **k):
        type(self).asked = True
        return self.Yes if self._open else self.No


class VersionFetchers(unittest.TestCase):
    """「刷新版本」按钮背后：接口给的链接要逐字用，不许按文件名规律拼。

    全部走注入的假 `_get` / 假 `_github_api_json`，用例不联网。
    """

    def _fake_get(self, payload, record):
        class _R:
            def json(self_inner):
                return payload

        def fake(url, *a, **k):
            record.append((url, k.get("timeout")))
            return _R()

        return fake

    def test_jetbrains_fetcher_uses_the_link_the_api_gives(self):
        rec = []
        payload = {"IIU": [
            {"version": "2099.1.0",
             "downloads": {"windows": {"link": "https://download.jetbrains.com/zzz/odd.exe",
                                       "size": 123}}},
            {"version": "2098.9.9",
             "downloads": {"windows": {"link": "https://download.jetbrains.com/aaa/older.exe",
                                       "size": 456}}},
        ]}
        orig = main._get
        self.addCleanup(setattr, main, "_get", orig)
        main._get = self._fake_get(payload, rec)
        got = main.FETCHERS["idea"]()
        self.assertEqual([v.version for v in got], ["2099.1.0", "2098.9.9"],
                         "接口顺序或版本排序不对")
        self.assertEqual(got[0].urls_for_current(),
                         ["https://download.jetbrains.com/zzz/odd.exe"],
                         "必须逐字用接口给的 link：JetBrains 2026 年起主线文件名不再带 IC，"
                         "按 `ideaIC-<ver>.exe` 拼必 404")
        self.assertEqual(got[0].archive_for_current(), "exe")

    def test_six_jetbrains_keys_are_registered_with_their_own_product_code(self):
        expected = {"idea": "IIU", "pycharm": "PCP", "clion": "CL",
                    "webstorm": "WS", "goland": "GO", "datagrip": "DG"}
        for key, code in expected.items():
            self.assertIn(key, main.FETCHERS, f"{key} 没注册 fetcher，「刷新版本」对它无效")
            rec = []
            orig = main._get
            self.addCleanup(setattr, main, "_get", orig)
            main._get = self._fake_get({code: [{"version": "1.0",
                                                "downloads": {"windows": {"link": "https://x/y.exe"}}}]},
                                       rec)
            main.FETCHERS[key]()
            self.assertIn(f"code={code}", rec[0][0],
                          f"{key} 请求的产品码不对：{rec[0][0]}")

    def test_jetbrains_fetcher_passes_an_explicit_timeout(self):
        """接口响应实测 2.0–4.8 秒（gzip 后），但 `_get` 会退避重试三次，
        不显式收紧超时的话最坏能拖到一分钟，「刷新版本」看起来像卡死。"""
        rec = []
        payload = {"IIU": [{"version": "1.0",
                            "downloads": {"windows": {"link": "https://x/y.exe"}}}]}
        orig = main._get
        self.addCleanup(setattr, main, "_get", orig)
        main._get = self._fake_get(payload, rec)
        main.FETCHERS["idea"]()
        self.assertIsNotNone(rec[0][1], "没给 JetBrains 显式超时")
        self.assertLessEqual(rec[0][1], 20, f"超时太宽：{rec[0][1]}")

    def test_fetchers_raise_instead_of_returning_an_empty_list(self):
        """失败必须抛，不能返回 []。

        返回空表会让 `_on_versions_fetched` 把下拉框灌成空的 —— 用户看到的是
        "点了刷新之后版本没了"，而正确行为是保留内置清单并记一条降级日志。
        """
        def boom(*a, **k):
            raise OSError("网络不通")

        orig = main._get
        orig_gh = main._github_api_json
        self.addCleanup(setattr, main, "_get", orig)
        self.addCleanup(setattr, main, "_github_api_json", orig_gh)
        main._get = boom
        main._github_api_json = boom
        for key in ("idea", "vscode", "dbx", "windterm"):
            with self.subTest(key=key):
                with self.assertRaises(Exception):
                    main.FETCHERS[key]()

    def test_vscode_fetcher_maps_the_releases_array(self):
        rec = []
        orig = main._get
        self.addCleanup(setattr, main, "_get", orig)
        main._get = self._fake_get(["1.141.0", "1.140.0", "not-a-version"], rec)
        got = main.FETCHERS["vscode"]()
        self.assertEqual([v.version for v in got], ["1.141.0", "1.140.0"],
                         "非版本号的条目要丢掉")
        self.assertEqual(
            got[0].urls_for_current(),
            ["https://update.code.visualstudio.com/1.141.0/win32-x64-archive/stable"])
        self.assertEqual(got[0].archive_for_current(), "zip",
                         "VS Code 走的是便携 zip，不是 exe 安装器")

    def test_github_asset_fetchers_pick_the_windows_portable_and_accelerate(self):
        """两个 GitHub 产物各自挑对自己那个 x64 便携包，且加速器排在裸地址前面。

        诱饵是真实存在的坑：同一次 release 里还有 arm 包、`.sha256` / `.sig` 旁证文件，
        按"第一个 .zip"挑会拿到 arm，按名字前缀匹配会拿到校验文件当安装包。
        """
        names = {"dbx": "DBX_9.9.9_x64-portable.zip",
                 "windterm": "WindTerm_9.9.9_Windows_Portable_x86_64.zip"}
        orig = main._github_api_json
        self.addCleanup(setattr, main, "_github_api_json", orig)
        for key, want in names.items():
            payload = [{"tag_name": "v9.9.9", "prerelease": False, "draft": False,
                        "assets": [
                            {"name": want.replace("x64", "arm64").replace("x86_64", "arm64"),
                             "size": 1,
                             "browser_download_url": "https://github.com/o/r/releases/"
                                                     "download/v9.9.9/arm.zip"},
                            {"name": want + ".sha256", "size": 2,
                             "browser_download_url": "https://github.com/o/r/releases/"
                                                     "download/v9.9.9/check.sha256"},
                            {"name": want, "size": 3,
                             "browser_download_url": "https://github.com/o/r/releases/"
                                                     "download/v9.9.9/" + want},
                        ]}]
            main._github_api_json = lambda url, *a, **k: payload
            with self.subTest(key=key):
                got = main.FETCHERS[key]()
                urls = got[0].urls_for_current()
                self.assertEqual(got[0].version, "9.9.9", "tag 上的 v 前缀要剥掉")
                self.assertEqual(urls[-1], "https://github.com/o/r/releases/download/"
                                           "v9.9.9/" + want,
                                 "末位必须是 GitHub 裸地址，且挑中的是 x64 便携包")
                self.assertGreater(len(urls), 1, "GitHub 产物必须把加速器排在前面")
                self.assertTrue(all(u.endswith(want) or want in u for u in urls),
                                f"加速器只是前缀，不能改变挑中的产物：{urls}")


class SecondBatchSources(unittest.TestCase):
    """第二批六个 key 的取数路径（2026-10-10 从 DEFERRED_KEYS 翻案进来）。

    当初判 Apipost / Apifox / HBuilderX "拿不到直链"是**我的误判**：只搜了
    `.exe`/`.zip` 字面量就收工。真源分别是 dl.php 分发器、electron-updater 的
    latest.yml、官网 Vue 背后那个 release.json。全部走注入的假 `_get`，用例不联网。
    """

    def _fake(self, by_marker):
        """by_marker: 请求 URL 里的匹配串 → 响应体（dict 走 .json()，str 走 .text）。"""
        calls = []

        class _R:
            def __init__(self, body):
                self._body = body

            def json(self_inner):
                return self_inner._body

            @property
            def text(self_inner):
                return self_inner._body

        def fake(url, *a, **k):
            calls.append((url, k.get("timeout")))
            for marker, body in by_marker.items():
                if marker in url:
                    return _R(body)
            raise AssertionError(f"用例没准备这个 URL 的响应：{url}")

        return fake, calls

    def _patch(self, by_marker):
        fake, calls = self._fake(by_marker)
        orig = main._get
        self.addCleanup(setattr, main, "_get", orig)
        main._get = fake
        return calls

    # --- HBuilderX：官方 release.json ---------------------------------------
    HBX_JSON = {
        "version": "5.24.2026081301", "displayVersion": "5.24",
        "files": [
            {"code": "win_simple", "size": "87.09M",
             "path": "https://download1.dcloud.net.cn/download/"
                     "HBuilderX.5.24.2026081301.zip"},
            {"code": "mac_simple", "size": "268.99M",
             "path": "https://download1.dcloud.net.cn/download/"
                     "HBuilderX.5.24.2026081301.dmg"},
        ],
    }

    def test_hbuilderx_takes_the_windows_zip_from_release_json(self):
        self._patch({"release.json": self.HBX_JSON})
        got = main.FETCHERS["hbuilderx"]()
        self.assertEqual(got[0].version, "5.24.2026081301",
                         "用 version 不用 displayVersion：5.24 这个号会连着发好几个构建")
        urls = got[0].urls_for_current()
        self.assertEqual(urls[0], self.HBX_JSON["files"][0]["path"],
                         "路径照抄接口给的，不按文件名规律拼")
        self.assertIn("download.dcloud.io", urls[-1],
                      "备用域名排在末位（实测同一文件同字节数 91,325,223）")
        self.assertEqual(got[0].archive_for_current(), "zip")
        self.assertNotIn(".dmg", " ".join(urls), "mac 档不许混进 Windows 的源列表")

    # --- Apipost：dl.php 分发器 ---------------------------------------------
    APIPOST_HTML = (
        '<a href="https://www.apipost.cn/dl.php?client=Win&amp;arch=x64&version=8.2.7">下载</a>'
        '<a href="https://www.apipost.cn/dl.php?client=Mac&arch=arm64&version=8.2.7">mac</a>'
    )

    def test_apipost_version_and_url_come_from_the_page_itself(self):
        self._patch({"download.html": self.APIPOST_HTML})
        got = main.FETCHERS["apipost"]()
        self.assertEqual(got[0].version, "8.2.7")
        self.assertEqual(
            got[0].urls_for_current(),
            ["https://www.apipost.cn/dl.php?client=Win&arch=x64&version=8.2.7"],
            "登记分发器那条：跟 302 之后的 dlcdn 地址带 auth_key 时效，硬编必失效")
        self.assertNotIn("Mac", got[0].urls_for_current()[0])

    def test_apipost_page_without_a_version_link_fails_instead_of_guessing(self):
        """页面上找不到 dl.php 时宁可抛错保留内置清单，也不拼一个 version= 出来。"""
        self._patch({"download.html": "<html>没有链接</html>"})
        with self.assertRaises(RuntimeError):
            main.FETCHERS["apipost"]()

    # --- Apifox：electron-updater latest.yml --------------------------------
    APIFOX_YML = ("version: 2.5.19\nfiles:\n"
                  "  - url: http://cdn.apifox.com/download/2.5.19/Apifox-2.5.19.exe\n"
                  "    size: 139586536\npath: nope\n")

    def test_apifox_manifest_is_parsed_and_upgraded_to_https(self):
        self._patch({"latest.yml": self.APIFOX_YML})
        got = main.FETCHERS["apifox"]()
        self.assertEqual(got[0].version, "2.5.19")
        url = got[0].urls_for_current()[0]
        self.assertTrue(url.startswith("https://"),
                        "清单里写的是 http://，登记前必须升 https（R13.2 第 6 条）")
        self.assertEqual(got[0].download_artifacts()[0].size, 139586536,
                         "体积取清单声明的 size，菜单才敢显示它")

    # --- Android Studio：winget 清单索引 ------------------------------------
    WINGET_DIR = [
        {"name": "2026.2.1.8", "type": "dir",
         "download_url": "https://api.github.com/repos/microsoft/winget-pkgs/"
                         "contents/manifests/g/Google/AndroidStudio/2026.2.1.8"},
        {"name": "Beta", "type": "dir",
         "download_url": "https://api.github.com/repos/microsoft/winget-pkgs/"
                         "contents/manifests/g/Google/AndroidStudio/Beta"},
    ]
    WINGET_VER_DIR = [
        {"name": "Google.AndroidStudio.installer.yaml", "type": "file",
         "download_url": "https://raw.githubusercontent.com/microsoft/winget-pkgs/master/"
                         "manifests/g/Google/AndroidStudio/2026.2.1.8/"
                         "Google.AndroidStudio.installer.yaml"},
    ]
    WINGET_YAML = ("- Architecture: x64\n"
                   "  InstallerUrl: https://edgedl.me.gvt1.com/android/studio/install/"
                   "2026.2.1.8/android-studio-rabbit1-windows.exe\n")

    def test_android_studio_url_is_read_out_of_the_winget_manifest(self):
        """文件名带列车代号（rabbit1），按版本号拼必 404 —— 只能照抄清单。"""
        orig_api = main._github_api_json
        self.addCleanup(setattr, main, "_github_api_json", orig_api)

        def fake_api(url, *a, **k):
            return self.WINGET_VER_DIR if url.endswith("/2026.2.1.8") else self.WINGET_DIR

        main._github_api_json = fake_api
        self._patch({"installer.yaml": self.WINGET_YAML})
        got = main.FETCHERS["android-studio"]()
        self.assertEqual(got[0].version, "2026.2.1.8",
                         "要按语义版本挑最大，不能取目录列表的最后一项（那是 Beta）")
        urls = got[0].urls_for_current()
        self.assertEqual(
            urls[0],
            "https://dl.google.com/dl/android/studio/install/2026.2.1.8/"
            "android-studio-rabbit1-windows.exe",
            f"首选实测 6.15 MB/s 的那个 CDN：{urls}")
        self.assertTrue(any("edgedl.me.gvt1.com" in u for u in urls[1:]),
                        f"两个 Google CDN 都要给（edgedl 实测只有 72 KB/s，故排后面）：{urls}")
        self.assertEqual(got[0].archive_for_current(), "exe")

    def test_android_studio_falls_back_when_github_is_unreachable(self):
        """GitHub 未认证限额/被墙时抛错，让上层保留内置清单而不是把下拉框灌空。"""
        def boom(*a, **k):
            raise OSError("connection refused")

        orig = main._get
        orig_api = main._github_api_json
        self.addCleanup(setattr, main, "_get", orig)
        self.addCleanup(setattr, main, "_github_api_json", orig_api)
        main._get = boom
        main._github_api_json = boom
        with self.assertRaises(RuntimeError):
            main.FETCHERS["android-studio"]()

    # --- 离线两行：Visual Studio / Navicat ----------------------------------
    def test_visual_studio_row_says_the_file_is_an_online_bootstrapper(self):
        """4.4 MB 不是完整安装包，双击后才从 CDN 拉内容 —— 不写清就是骗用户。"""
        comp = next(c for c in main.build_components() if c.key == "visual-studio")
        self.assertIn("在线安装器", comp.data_note)
        self.assertEqual(comp.versions[0].urls_for_current(),
                         ["https://aka.ms/vs/17/release/vs_Community.exe"],
                         "aka.ms 是微软给的稳定别名，背后的 GUID 路径每次发版都变")
        self.assertEqual(comp.versions[0].download_artifacts()[0].size, 4474136)

    def test_navicat_row_is_a_measured_official_url_with_license_note(self):
        comp = next(c for c in main.build_components() if c.key == "navicat")
        self.assertIn("不含授权", comp.data_note)
        art = comp.versions[0].download_artifacts()[0]
        self.assertEqual(art.urls,
                         ["https://download.navicat.com/download/navicat17_premium_cs_x64.exe"])
        self.assertEqual(art.size, 153253568)


class LicenseLabeling(_EnvSandbox):
    """商业档必须把"不含授权"写在用户看得见的地方，而不是只写在注释里。

    只下载型卡片没有卸载确认框，而 `data_note` 平时恰恰是靠那个框露出来的
    —— 所以这批的说明只能挂在按钮 tooltip 上。这条用例存在的意义就是防住
    "改了文案却没地方显示"。
    """

    def setUp(self):
        super().setUp()
        main.ComponentCard._detect_status = self._orig_detect

    def _card(self, key):
        comp = next(c for c in main.build_components() if c.key == key)
        return main.ComponentCard(comp, lambda lvl, msg: None)

    def test_commercial_products_are_labeled_no_license(self):
        commercial = {"idea", "pycharm", "clion", "webstorm", "goland", "datagrip",
                      "navicat"}
        for key in sorted(commercial):
            card = self._card(key)
            visible = " ".join(filter(None, (card.btn_install.toolTip(),
                                             card.status_label.toolTip())))
            with self.subTest(key=key):
                self.assertIn("不含授权", visible,
                              f"{key} 的授权说明没出现在任何悬停可见的文案里")
                self.assertNotIn("免费", visible,
                                 f"{key} 是商业订阅软件，界面里不许出现「免费」")

    def test_open_source_batch_says_what_the_file_is(self):
        for key in ("vscode", "dbx", "windterm"):
            card = self._card(key)
            tip = card.btn_install.toolTip() or ""
            with self.subTest(key=key):
                self.assertTrue(tip.strip(), f"{key} 主按钮没有悬停说明")
                self.assertNotIn("不含授权", tip,
                                 f"{key} 是开源软件，不该挂商业授权的措辞")

    def test_wechat_version_label_says_it_is_not_a_version_number(self):
        """微信开发者工具没有可机读版本号，界面必须自己讲清楚这点。"""
        card = self._card("wechat-devtools")
        visible = " ".join(filter(None, (card.btn_install.toolTip(),
                                         card.version_combo.toolTip(),
                                         card.status_label.toolTip())))
        self.assertIn("不是软件版本号", visible.replace(" ", ""),
                      f"版本位其实是日期，不说明就是骗人：{visible!r}")


class ArtifactMenu(_EnvSandbox):
    """厂商同时发 exe 安装器与 zip 便携包时，让用户点一下再选，并把体积摆在眼前。

    为什么不画两颗主按钮：卡片格子只有 271px，按钮行历史上多一颗就裁过字；
    而 11 个里有 3 个只有一种产物，两颗按钮会让界面不齐。菜单一行一个，
    顺手把"这是安装器还是便携包 + 多大"说清楚，这些塞进窄按钮放不下。
    """

    def setUp(self):
        super().setUp()
        main.ComponentCard._detect_status = self._orig_detect
        self._orig_worker = main.DownloadWorker
        self._orig_dialog = main.QFileDialog.getExistingDirectory
        self._orig_pick = main.pick_download_artifact
        self._orig_install = main.install_downloaded
        self.addCleanup(setattr, main, "DownloadWorker", self._orig_worker)
        self.addCleanup(setattr, main.QFileDialog, "getExistingDirectory", self._orig_dialog)
        self.addCleanup(setattr, main, "pick_download_artifact", self._orig_pick)
        self.addCleanup(setattr, main, "install_downloaded", self._orig_install)
        main.DownloadWorker = _FakeWorker
        main.install_downloaded = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("只下载组件不许走 install_downloaded"))
        picked = self.root / "dl"
        picked.mkdir()
        main.QFileDialog.getExistingDirectory = classmethod(
            lambda cls, *a, **k: str(picked))
        self.picked = picked

    def _card(self, key):
        comp = next(c for c in main.build_components() if c.key == key)
        return main.ComponentCard(comp, lambda lvl, msg: None)

    def test_jetbrains_versions_carry_both_artifacts_with_sizes(self):
        comp = next(c for c in main.build_components() if c.key == "idea")
        arts = comp.versions[0].download_artifacts()
        self.assertEqual([a.fmt for a in arts], ["exe", "zip"],
                         "顺序就是菜单顺序：默认那个排第一")
        self.assertTrue(all(a.size > 10 ** 9 for a in arts),
                        f"JetBrains 两种产物都是 GB 级，体积必须登记：{[a.size for a in arts]}")
        self.assertTrue(any(a.urls[0].endswith(".win.zip") for a in arts),
                        "zip 那条必须是 windowsZip 的链接，不是把 .exe 改了个后缀")

    def test_single_artifact_components_need_no_extra_registration(self):
        """只有一种产物的（WindTerm / 微信 / Eclipse）不用重复登记，菜单也不出现。"""
        for key in ("windterm", "wechat-devtools", "eclipse"):
            comp = next(c for c in main.build_components() if c.key == key)
            cv = comp.versions[0]
            arts = cv.download_artifacts()
            with self.subTest(key=key):
                self.assertEqual(len(arts), 1)
                self.assertEqual(arts[0].urls, cv.urls_for_current(),
                                 "单项产物必须直接复用主 URL，别养出第二份数据")

    def test_menu_text_shows_the_size_next_to_the_kind(self):
        comp = next(c for c in main.build_components() if c.key == "clion")
        texts = [a.menu_text() for a in comp.versions[0].download_artifacts()]
        self.assertEqual(len(texts), 2)
        for t in texts:
            self.assertRegex(t, r"(GB|MB)", f"菜单文字要带体积：{t!r}")
            self.assertTrue(("安装器" in t) or ("便携" in t), f"要说清是什么：{t!r}")

    def test_two_artifacts_ask_before_downloading(self):
        seen = {}

        def fake_pick(arts, parent=None, at=None):
            seen["arts"] = [a.fmt for a in arts]
            return arts[1]                      # 用户选了第二项（zip）

        main.pick_download_artifact = fake_pick
        card = self._card("idea")
        card.on_download_clicked()
        self.assertEqual(seen.get("arts"), ["exe", "zip"], "两种产物却没问用户")
        w = _FakeWorker.last
        self.assertTrue(w.dest.name.endswith(".zip"), f"选了 zip 却下成 {w.dest.name}")
        self.assertEqual(w.urls, card.component.versions[0].download_artifacts()[1].urls)
        self.assertEqual(w.expect_magic, b"PK", "zip 要按 PK 校验")

    def test_declining_the_menu_starts_nothing(self):
        main.pick_download_artifact = lambda arts, parent=None, at=None: None
        card = self._card("pycharm")
        _FakeWorker.last = None
        card.on_download_clicked()
        self.assertIsNone(_FakeWorker.last, "用户没选，就不该起下载线程")
        self.assertTrue(card.btn_install.isEnabled(), "取消后按钮要能再点")
        self.assertFalse(list(self.picked.iterdir()), "取消后目录里不该留文件")

    def test_one_artifact_needs_no_extra_click(self):
        """只有一种产物时不弹菜单 —— 而且这条必须由**真函数**来答，不能靠桩去看。

        上一版把 pick_download_artifact 整个替掉再断"没被调用"，等于把要验的东西
        先拆了：卡片是无条件调它的，弹不弹由函数内部按数量决定，桩一上就观测不到了。
        """
        main.pick_download_artifact = self._orig_pick
        comp = next(c for c in main.build_components() if c.key == "windterm")
        arts = comp.versions[0].download_artifacts()
        self.assertEqual(len(arts), 1, "WindTerm 官方只发便携包，别哪天多登记一种")
        chosen = main.pick_download_artifact(arts)
        self.assertIsNotNone(chosen, "单产物时真函数不该返回空")
        self.assertEqual(chosen.fmt, "zip")
        card = self._card("windterm")
        card.on_download_clicked()
        self.assertTrue(_FakeWorker.last.dest.name.endswith(".zip"))

    def test_every_artifact_url_is_a_measured_host(self):
        """产物列表里的每个域名都必须是实测过的 —— 包括"另一种产物"那条。

        镜像测试只看主 URL，alt 产物是它看不见的第二扇门；这扇门不设白名单，
        以后往 alt 里塞个没测过的源就绕过了 R1。
        """
        allowed = ("download.jetbrains.com", "update.code.visualstudio.com",
                   "github.com", "gh-proxy.com", "ghfast.top", "ghproxy.net",
                   "servicewechat.com", "download.eclipse.org",
                   "mirrors.tuna.tsinghua.edu.cn", "mirrors.aliyun.com",
                   "mirrors.huaweicloud.com",
                   # 2026-10-10 第二批，逐个 range + 5MB 吞吐实测过（台账在 _DEVTOOLS 上方）：
                   "www.apipost.cn",              # dl.php 分发器，302 后 206 / `MZ`
                   "download1.dcloud.net.cn", "download.dcloud.io",   # 同字节数互为源
                   "cdn.apifox.com",
                   "dl.google.com", "edgedl.me.gvt1.com",             # 同一文件，6.15 MB/s 排前
                   "aka.ms",                      # 微软给的稳定别名，跟到 download.visualstudio…
                   "download.navicat.com",
                   # 2026-10-12 B6a：九个客户端，域名逐个实测过（含 alt 产物）
                   "github.com",                 # dbeaver / heidisql / bruno / ardm
                   "downloads.mongodb.com",      # compass：msi / exe / zip 三形态
                   "mirror.nju.edu.cn", "ftp.postgresql.org",   # pgadmin4：南大 + 官方
                   "cdn.mysql.com",              # workbench：msi / zip
                   "dl.pstmn.io",                # postman：按版本取的那条地址
                   # 2026-10-15 「Agent客户端」首批五个，域名逐个 range 实测过
                   # （拿 HTTP 206 + Content-Range 确认总字节数，见各行的实测数字）：
                   "api2.cursor.sh",             # cursor：golden 链，按主.次版本号取
                   "cdn-zcode.z.ai",             # zcode：按版本号分目录的官方 CDN
                   "download.qoder.com",         # qoderwork-cn / qoder：滚动 latest
                   # 2026-10-15 第二批「Agent客户端」，域名逐个 range 实测过
                   # （全部拿 HTTP 200/206 + 前四字节 `MZ` 确认是可执行的 PE）：
                   "lf-cdn.trae.ai",             # trae：按构建号分目录
                   "lf-cdn.trae.com.cn",         # trae-cn：大陆独立构建
                   "down.marvis.qq.com",         # marvis：腾讯自有 CDN
                   "dtapp-pub.dingtalk.com",     # wukong：URL 必须带渠道号后缀
                   "ydschool-video.nosdn.127.net",   # lobsterai：网易 NOS
                   "autoglm.aminer.cn",          # autoclaw：智谱国内发版站
                   "dumate-app-public.bj.bcebos.com",  # dumate：百度 BOS
                   "get.microsoft.com",          # chatgpt：微软商店引导安装器
                   "appsupport.moonshot.cn",     # kimi：滚动端点，302 到带版本号的文件
                   "code.kimi.com",              # kimi-code：302 到 cdn.kimi.com
                   "filecdn.minimax.chat",       # minimax：直链带空格（%20）
                   "chat.stepfun.com",           # stepfun：滚动端点，307 到当天有效的签名链
                   "sedown.qihucdn.com",         # nano-ai：360 自有 CDN
                   "static-us-img.skywork.ai",   # tiangong：昆仑万维
                   "download.codebuddy.cn",      # codebuddy / workbuddy：同站两个包
                   "download.deepseek.com",      # deepseek-harness：滚动 dsh-latest
                   # 2026-10-15 第三批（大厂中文助手），同样 range + `MZ`/`PK` 实测过：
                   "lf-flow-web-cdn.doubao.com", # doubao：官方签名 zip（`PK`）
                   "cdn-hybrid-prod.hunyuan.tencent.com",  # yuanbao：腾讯混元 CDN
                   "qianwen-portal-cdn.tongyi.com",        # tongyi-qianwen：按版本号分目录
                   "lingma-ide.oss-rg-china-mainland.aliyuncs.com",  # lingma：阿里 OSS
                   "xiaoyan-desktop.cdn.bcebos.com",       # ernie：百度 BOS
                   "sfile.chatglm.cn",           # chatglm：智谱文件站
                   # 2026-10-15 第四批「Agent客户端」，域名逐个 range + 前四字节实测过
                   # （前 7 个都是 GitHub 产物，走已成名的加速器域名；这两个是厂商自有 CDN）：
                   "prod.download.desktop.kiro.dev",  # kiro：按版本号分目录、带签名（实测 1.3.0）
                   "hermes-assets.nousresearch.com",  # hermes：滚动直链，无版本号（取 Last-Modified 年月）
                   # 2026-10-15 第五批（12 个 Agent + 10 个开发工具）：同样逐个实测过。
                   # 其中 13 个是 GitHub 产物（走已成名的加速器域名），下面是 9 个厂商自有域名：
                   "ollama.com",                 # ollama：官方站直链（滚动，不带版本号）
                   "lmstudio.ai",                # lm-studio：/download/latest/ 302 到版本化安装器
                   "ima-app.image.myqcloud.com",  # ima（腾讯）：按版本目录直发
                   "autoupdate.desktop.anaconda.com",  # kilo-code：滚动 latest 路径
                   "next-assets.msty.studio",    # msty：滚动 latest 直链
                   "appsupport.kimi.ai",         # kimi-work：滚动下载端点，302 到版本化文件
                   "1.as.dl.wireshark.org",      # wireshark：官方按平台分目录（win64/）
                   "release.gitkraken.com",      # gitkraken：稳定别名 GitKrakenSetup.exe
                   "product-downloads.atlassian.com")  # sourcetree：Atlassian GA 目录
        for comp in main.build_components():
            if not comp.download_only:
                continue
            for cv in comp.versions:
                for art in cv.download_artifacts():
                    for u in art.urls:
                        with self.subTest(key=comp.key, url=u[:70]):
                            host = u.split("/", 3)[2]
                            self.assertIn(host, allowed,
                                          f"{comp.key} 的产物源 {host} 没实测过")


class WorkerRobustness(unittest.TestCase):
    """DownloadWorker 的两条健壮性缺口（2026-10-10 全面审计查出来，逐条回磁盘核实过）。"""

    def _dir(self):
        d = Path(tempfile.mkdtemp())
        return d

    def test_safe_download_name_strips_any_path_from_the_remote_name(self):
        """产物名来自公开的 release API，不能当可信文件名用。

        `Path(目录) / 名字` 在名字是绝对路径或含 `..` 时会**直接跳出目录**：
        实测 `Path('C:/Users/x/Downloads') / 'C:\\\\Windows\\\\a.exe'` → `C:\\Windows\\a.exe`，
        `'/etc/passwd'` → `C:\\etc\\passwd`，`'../../escape.exe'` 也一样逃出去。
        """
        cases = {
            "C:\\Windows\\System32\\evil.exe": "evil.exe",
            "/etc/passwd": "passwd",
            "../../escape.exe": "escape.exe",
            "sub/dir/real.zip": "real.zip",
            "ByteTools.exe": "ByteTools.exe",
            "带 空格 和-中文.zip": "带 空格 和-中文.zip",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(main._safe_download_name(raw, fallback="x.bin"), want)

    def test_safe_download_name_falls_back_on_names_that_are_not_files(self):
        for raw in ("", "   ", ".", "..", "/", "\\", "a/b/"):
            with self.subTest(raw=raw):
                self.assertEqual(main._safe_download_name(raw, fallback="fb.exe"), "fb.exe")

    def test_run_reports_an_unusable_destination_instead_of_raising(self):
        """dest 的父目录建不出来时（同名文件挡路、只读盘、OneDrive 占位）必须发 finished_fail。

        `ensure_dir` 原先在 `run()` 的 try 外面：OSError 逃出 QThread.run 在 Windows 上是
        进程级 abort（0xC0000409 / 退出码 127，一行 traceback 都没有），
        而且上层收不到任何信号，界面永远停在"下载中"。
        """
        root = self._dir()
        blocker = root / "afile"
        blocker.write_text("x")
        w = main.DownloadWorker(["https://example.invalid/x.bin"], blocker / "sub" / "out.bin")
        got = []
        w.finished_fail.connect(lambda m: got.append(m))
        w.finished_ok.connect(lambda p: got.append(("ok", p)))
        w.log.connect(lambda lvl, msg: None)
        w.run()                      # run() 是普通方法，同步跑不起线程
        self.assertEqual(len(got), 1, f"应当恰好一个终态信号：{got}")
        self.assertIsInstance(got[0], str, f"不该报成功：{got}")
        self.assertIn("目录", got[0], f"要说清是目录建不出来：{got[0]}")

    def test_cancel_emits_finished_fail_exactly_once(self):
        """取消时 `_try_download` 和 `run()` 各发一次 finished_fail。

        后果不是多一行日志：上层弹两次"下载失败"，而且第二次文案是
        "所有下载源均不可用" —— 把用户主动取消说成了网络故障。
        """
        root = self._dir()
        w = main.DownloadWorker(["https://a.invalid/x.bin", "https://b.invalid/x.bin"],
                                root / "out.bin")
        hits = []
        w.finished_fail.connect(lambda m: hits.append(m))
        w.finished_ok.connect(lambda p: hits.append(("ok", p)))
        w.log.connect(lambda lvl, msg: None)

        class FakeResp:
            headers = {"Content-Length": "99999999"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=0):
                w._cancel = True              # 第一个 chunk 之后用户点了取消
                yield b"x" * 64

        # 桩点见 DownloadFlow 里那两条用例的说明：下载走 main.http_session()
        orig_session = main.http_session

        class _Sess:
            def get(self, *a, **k):
                return FakeResp()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        self.addCleanup(setattr, main, "http_session", orig_session)
        main.http_session = lambda: _Sess()
        w.run()
        self.assertEqual(len(hits), 1, f"取消只该发一次终态：{hits}")
        self.assertIn("取消", hits[0], f"取消不该被说成源不可用：{hits}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
