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
from bt_component_category_tests import EXPECTED_MEMBERSHIP  # noqa: E402

# 这一批的 key 清单。它是"加一个只下载组件要过一遍评审"的那个点：
# 成员表在对面（bt_component_category_tests.EXPECTED_MEMBERSHIP），这里只挑出下载型的那些。
DOWNLOAD_ONLY_KEYS = set(EXPECTED_MEMBERSHIP["开发工具"])

# 用户点名要、但这一版**没进表**的候选。登记一个没实测过的源违反 R1（200 也可能是
# 拿 HTML 应付的假源），所以宁可少四个也不硬凑；这张表存在的意义是别让人以为"漏了"。
DEFERRED_KEYS = {
    "hbuilderx": "下载页与文档页全 JS 渲染，探到的候选路径 404",
    "apipost": "download.html 里没有任何 .exe/.zip 字面量，拿不到直链",
    "apifox": "同上；官网 /download 直接跳首页",
    "lithe": "官方仓库 1lck/Lithe-IDEA 经 API 已 404，新仓库 0 个 release",
}


class TabStructure(unittest.TestCase):
    def setUp(self):
        self.components = main.build_components()
        self.groups = main.group_components(self.components)

    def test_new_tab_is_the_third_and_holds_the_ten_keys(self):
        self.assertEqual(list(main.COMPONENT_CATEGORIES),
                         ["开发环境", "开发软件", "开发工具", "一键启停"],
                         "「开发工具」放第 3 个，「一键启停」保持最后")
        self.assertEqual({c.key for c in self.groups["开发工具"]}, DOWNLOAD_ONLY_KEYS)

    def test_other_software_tab_is_gone(self):
        """用户要求少一个 Tab：「其它软件」整个取消，不是留一张空白页。

        这条必须单独钉：`group_components` 给每个分类都建空列表、建 Tab 的循环
        **不跳过空组**，所以只要 COMPONENT_CATEGORIES 里还留着这个名字，
        界面上就会多出一个「其它软件（0）」。
        """
        self.assertNotIn("其它软件", main.COMPONENT_CATEGORIES)
        self.assertNotIn("其它软件", {c.category for c in self.components})

    def test_docker_and_kubectl_now_live_in_dev_software(self):
        """原「其它软件」那两张卡并进「开发软件」，不许变成无家可归。"""
        dev_soft = {c.key for c in self.groups["开发软件"]}
        self.assertIn("docker", dev_soft)
        self.assertIn("kubectl", dev_soft)

    def test_deferred_candidates_are_still_absent(self):
        """没实测到官方直链的候选，不许被"顺手补上"。

        补的前提是先按 R1 实测（状态码 + 魔数 + 累计字节/吞吐），然后把 key 加进
        EXPECTED_MEMBERSHIP 与 build_components，最后删掉这条用例里的对应项。
        """
        keys = {c.key for c in self.components}
        for key in DEFERRED_KEYS:
            self.assertNotIn(key, keys, f"{key} 的源没实测过就登记了")

    def test_visible_component_count_is_36(self):
        """**全仓库唯一一处**写死界面可见组件数的地方（26 老 + 10 新）。

        其它套件的数字都改成从成员表派生，只有这里保留绝对值：
        加组件时必须在这里过一次手，逼着人确认"这个数字变了是有意为之"。
        """
        visible = sum(len(v) for v in self.groups.values())
        self.assertEqual(visible, 36)
        self.assertEqual(len(self.components), 37, "36 可见 + 隐藏的 erlang")


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
        """卡片上「下载」要点得动：每个版本至少有一个 Windows 直链。"""
        for comp in self.components:
            if not comp.download_only:
                continue
            self.assertTrue(comp.versions, f"{comp.key} 没有可选版本")
            for cv in comp.versions:
                urls = cv.urls_for_current()   # 方法在 ComponentVersion 上，不在 Component 上
                self.assertTrue(urls, f"{comp.key} {cv.version} 在当前平台没有 URL")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
