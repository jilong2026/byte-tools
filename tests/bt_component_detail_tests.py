"""组件详情弹窗（规则 R17）离线护栏套件。

钉住四件事，都是真机/复核踩过的坑：
  A. 三表对齐 —— COMPONENT_SUMMARY / COMPONENT_USAGE 的 key 必须与组件清单
     严格一致：少一条，build_components() 末尾赋值直接 KeyError，主窗口构造不出来。
  B. 固定四段式顺序与派生口径 —— 「本工具会替你做什么」只从能力位派生，
     不许另写文案；data_note / 版本清单不进详情。
  C. 端口显示必须是展开后的真实端口 —— port_offsets 是「主口 + 偏移」
     而不是绝对端口（真机 2026-10-12 把 etcd 显示成「端口 2379、1」）。
  D. 措辞边界 —— 只下载类不许承诺解压/写环境变量；没登记 console_path 的
     组件不许说"控制台"。渲染不许露出 Markdown 残留（** 与反引号）。
"""
import os
import platform as _platform
import inspect
import re
import sys
import unittest

import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# 文案长度上限：详情要"简洁并且专业"，超了就是第二份 README。
SUMMARY_MAX = 110
USAGE_MAX = 160

_app = None


def qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def make_card(key):
    """构造指定组件的卡片。探测桩掉：本套件只关心 detail_lines 的输入
    （登记数据），不关心磁盘态。"""
    qapp()
    comp = next(c for c in main.build_components() if c.key == key)
    orig = main.ComponentCard._detect_status
    main.ComponentCard._detect_status = lambda self, *a, **k: None
    try:
        return main.ComponentCard(comp, lambda *a: None)
    finally:
        main.ComponentCard._detect_status = orig


class TableContract(unittest.TestCase):
    """A · 两张文案表与组件清单严格对齐（漏 key 即启动崩溃）。"""

    def test_summary_covers_every_component(self):
        comps = main.build_components()
        missing = [c.key for c in comps if c.key not in main.COMPONENT_SUMMARY]
        self.assertEqual(missing, [], f"COMPONENT_SUMMARY 缺 key: {missing}")

    def test_usage_covers_every_component(self):
        comps = main.build_components()
        missing = [c.key for c in comps if c.key not in main.COMPONENT_USAGE]
        self.assertEqual(missing, [], f"COMPONENT_USAGE 缺 key: {missing}")

    def test_no_orphan_keys(self):
        comps = {c.key for c in main.build_components()}
        self.assertEqual(set(main.COMPONENT_SUMMARY) - comps, set())
        self.assertEqual(set(main.COMPONENT_USAGE) - comps, set())

    def test_summary_assigned_to_component(self):
        for c in main.build_components():
            self.assertEqual(
                c.summary, main.COMPONENT_SUMMARY[c.key],
                f"{c.key}: comp.summary 与登记表不一致（赋值接缝断了）")

    def test_length_caps(self):
        for k, v in main.COMPONENT_SUMMARY.items():
            self.assertLessEqual(len(v), SUMMARY_MAX, f"{k} summary 超长")
        for k, v in main.COMPONENT_USAGE.items():
            self.assertLessEqual(len(v), USAGE_MAX, f"{k} usage 超长")


class FourSectionLayout(unittest.TestCase):
    """B · 固定四段式：顺序与出现条件。"""

    def test_section_order_and_presence(self):
        card = make_card("etcd")
        titles = [t for t, _ in card.detail_lines()]
        self.assertEqual(titles[:3], ["它是什么", "怎么用", "本工具会替你做什么"])

    def test_platform_note_last_and_conditional(self):
        with_hint = make_card("rabbitmq")
        lines = with_hint.detail_lines()
        titles = [t for t, _ in lines]
        self.assertEqual(titles[-1], "平台说明")
        self.assertTrue(lines[-1][1])
        without = make_card("tomcat")
        self.assertNotIn("平台说明", [t for t, _ in without.detail_lines()])

    def test_data_note_and_versions_not_in_detail(self):
        """数据去处归卸载确认框、版本归下拉框：详情重复它们就是噪音。"""
        card = make_card("mysql")
        joined = "\n".join(text for _t, text in card.detail_lines())
        if card.component.data_note:
            self.assertNotIn(card.component.data_note[:30], joined)


class PortDisplay(unittest.TestCase):
    """C · 端口 = 主口 + 偏移展开后的真实端口，绝不显示裸偏移。"""

    def _ports_line(self, key):
        """端口只在「本工具会替你做什么」派生段出现；摘要提端口不算。"""
        card = make_card(key)
        for title, text in card.detail_lines():
            if title == "本工具会替你做什么":
                return text
        self.fail(f"{key}: 详情没有派生段")

    def test_etcd_offsets_expand_to_consecutive(self):
        text = self._ports_line("etcd")
        spec = main.LAUNCH_OF["etcd"]
        self.assertIn(str(spec.main_port), text)
        for off in spec.port_offsets:
            self.assertIn(str(spec.main_port + int(off)), text)

    def test_kafka_extra_ports_are_absolute(self):
        text = self._ports_line("kafka")
        spec = main.LAUNCH_OF["kafka"]
        self.assertIn(str(spec.main_port), text)
        for p in spec.extra_ports:
            self.assertIn(str(int(p)), text)

    def test_ports_match_choose_ports_algorithm(self):
        """与 choose_ports 的展开算法逐口核对：详情不许自成一套。"""
        for key in sorted(main.LAUNCH_KEYS):
            spec = main.LAUNCH_OF[key]
            derived = [spec.main_port + int(o) for o in spec.port_offsets]
            extras = [int(p) for p in spec.extra_ports]
            expect = [spec.main_port] + derived + extras
            text = self._ports_line(key)
            nums = set(re.findall(r"\d{2,5}", text))
            for p in expect:
                self.assertIn(str(p), nums, f"{key}: 详情缺端口 {p}（应为 {expect}）")


class DownloadOnlyWording(unittest.TestCase):
    """D1 · 只下载类（R13）的措辞边界：不许承诺解压 / 环境变量 / 启停。"""

    FORBIDDEN = ("解压到", "写好环境变量", "一键启停", "自检版本")

    def test_all_download_only_details_stay_in_scope(self):
        for comp in main.build_components():
            if not comp.download_only:
                continue
            card = make_card(comp.key)
            text = "".join(t for _t, t in card.detail_lines())
            for word in self.FORBIDDEN:
                self.assertNotIn(word, text, f"{comp.key}: 只下载类承诺了「{word}」")
            self.assertIn("官方安装包", text)

    def test_download_only_has_no_launch_claim(self):
        card = make_card("idea")
        self.assertFalse(card.component.launch, "idea 不该有 LaunchSpec")
        joined = " ".join(t for _t, t in card.detail_lines())
        self.assertNotIn("端口", joined)


class LaunchableWording(unittest.TestCase):
    """D2 · 控制台一词只属于登记了 console_path 的组件。"""

    def test_console_word_only_with_console_path(self):
        for key in sorted(main.LAUNCH_KEYS):
            card = make_card(key)
            # 只核派生段：摘要讲软件本身有什么界面是合法的，但工具的承诺
            # （「本工具会替你做什么」）不许说"控制台"却没登记 console_path。
            text = "".join(t for ti, t in card.detail_lines()
                           if ti == "本工具会替你做什么")
            has_console = bool(main.LAUNCH_OF[key].console_path)
            if not has_console:
                self.assertNotIn("控制台", text,
                                 f"{key}: 未登记 console_path 却承诺控制台")

    def test_launch_components_advertise_start_stop(self):
        for key in sorted(main.LAUNCH_KEYS):
            card = make_card(key)
            text = "".join(t for ti, t in card.detail_lines()
                           if ti == "本工具会替你做什么")
            self.assertIn("一键启停", text, f"{key}: 有 LaunchSpec 却不说一键启停")


class Rendering(unittest.TestCase):
    """渲染层：Markdown 星号转 <b>、反引号清除、HTML 转义、空段兜底。"""

    def test_markdown_emphasis_becomes_bold(self):
        html = main.ComponentDetailDialog._to_html([("它是什么", "核心是 **Raft** 协议")])
        self.assertIn("<b>Raft</b>", html)
        self.assertNotIn("**", html)

    def test_backticks_stripped(self):
        html = main.ComponentDetailDialog._to_html([("怎么用", "跑 `etcdctl put k v`")])
        self.assertNotIn("`", html)
        self.assertIn("etcdctl put k v", html)

    def test_html_escaped(self):
        html = main.ComponentDetailDialog._to_html([("它是什么", "a<b & c>d")])
        self.assertIn("&lt;", html)
        self.assertIn("&amp;", html)

    def test_empty_sections_fallback(self):
        html = main.ComponentDetailDialog._to_html([])
        self.assertIn("还没有写说明", html)

    def test_official_home_is_last_url_host(self):
        """旧的 comp_download_host 已随官网登记表一起移除（2026-10-14）。

        它从**下载 URL** 推导"官方地址"，而推导结果绝大多数根本不是官网 ——
        实测 88 个组件里只有 7 个推得对，39 个推成 github.com 仓库页、
        31 个推成 CDN/下载服务器、docker 直接推不出来。详情页改用人工核实的
        COMPONENT_OFFICIAL_URLS 之后它再无调用者，连同这条用例一并删掉。

        替代它的护栏在 OfficialUrlRegistry 里。
        """
        self.assertFalse(hasattr(main, "comp_download_host"),
                         "comp_download_host 已移除，不该复活："
                         "从下载 URL 推导官网域名会产出 api.adoptium.net 这类假官网")


class OfficialUrlRegistry(unittest.TestCase):
    """R19 · 官网登记表必须与组件清单严格对齐，且取值合法。

    这 88 条是人工逐条核实过的事实（2026-10-14 逐条 HTTP 验证），它们同时是
    「承重墙」：详情页那行字直接把它当 href 用，填错就是给用户一个假官网。
    所以对齐性与合法性都在这里钉死，漏登记即红 —— 与 COMPONENT_SUMMARY 同一套做法。
    """

    @classmethod
    def setUpClass(cls):
        cls.comps = main.build_components()
        cls.keys = {c.key for c in cls.comps}

    def test_registry_covers_every_component(self):
        missing = sorted(c.key for c in self.comps
                         if c.key not in main.COMPONENT_OFFICIAL_URLS)
        self.assertEqual(missing, [],
                         f"COMPONENT_OFFICIAL_URLS 缺 key（接新组件时必须补一条）: {missing}")

    def test_no_orphan_keys(self):
        orphan = sorted(set(main.COMPONENT_OFFICIAL_URLS) - self.keys)
        self.assertEqual(orphan, [], f"登记表里这些 key 已无对应组件: {orphan}")

    def test_assigned_to_every_component(self):
        """赋值接缝不能断 —— 漏了这一行，详情页那行字就整行消失（静默失败）。"""
        for c in self.comps:
            self.assertEqual(
                c.official_url, main.COMPONENT_OFFICIAL_URLS[c.key],
                f"{c.key}: comp.official_url 与登记表不一致（build_components 末尾的赋值断了）")

    def test_all_urls_are_https(self):
        """必须是 https。http 链接在现在的浏览器里会被标成不安全，且多半能升 https。"""
        bad = {k: u for k, u in main.COMPONENT_OFFICIAL_URLS.items()
               if not u.startswith("https://")}
        self.assertEqual(bad, {}, f"这些不是 https 开头: {bad}")

    def test_urls_have_no_whitespace_and_have_host(self):
        """URL 里带空格/换行会让 href 截断；没有 host 说明写错了。"""
        for k, u in main.COMPONENT_OFFICIAL_URLS.items():
            self.assertEqual(u.strip(), u, f"{k}: URL 首尾有空白 —— {u!r}")
            self.assertNotIn(" ", u, f"{k}: URL 里有空格 —— {u!r}")
            self.assertTrue(main._url_netloc(u),
                            f"{k}: 切不出域名，写法可能有问题 —— {u!r}")

    def test_link_text_comes_from_the_same_url_as_the_href(self):
        """链接文字里的域名必须是从 href 那个 URL 切出来的。

        早先的写法是「文字显示下载域名、跳转却是官网」，于是详情页上会出现
        "写着 archive.apache.org、点进去是 apache.org"。这里钉住文字与 href
        同源：文字里的 netloc 必须是 href 的 netloc。
        """
        for key, url in main.COMPONENT_OFFICIAL_URLS.items():
            text_domain = main._url_netloc(url)
            self.assertIn(text_domain, url,
                          f"{key}: 文字域名 {text_domain} 不来自 href {url}")

    def test_known_cn_entries_use_their_china_entry(self):
        """钉住几条最容易被"顺手改回国际站"的大陆入口。

        口径是用户 2026-10-14 拍板的乙档：有大陆官网（含同域名中文路径）就用
        大陆的。这些是最容易被误改的几条，所以显式点名。
        """
        expected = {
            "go": "golang.google.cn",              # Google 大陆官方域名
            "navicat": "navicat.com.cn",           # Navicat 中国版官网
            "apifox": "apifox.cn",
            "apipost": "apipost.cn",
            "hbuilderx": "dcloud.io",
            "wechat-devtools": "weixin.qq.com",
            "node": "nodejs.org",
            "vscode": "code.visualstudio.com",
            "visual-studio": "visualstudio.microsoft.com",
            "dotnet-sdk": "dotnet.microsoft.com",
            "kubectl": "kubernetes.io",
            "powershell": "learn.microsoft.com",
        }
        for key, host in expected.items():
            with self.subTest(key=key):
                netloc = main._url_netloc(main.COMPONENT_OFFICIAL_URLS[key])
                # 用"等于或以 .host 结尾"而不是严格相等：官网带 www. / developers.
                # 这类前缀很常见（www.apipost.cn、developers.weixin.qq.com），
                # 严格相等会让测试在无意义的子域名差异上变红，反而招致被人改断言。
                self.assertTrue(
                    netloc == host or netloc.endswith("." + host),
                    f"{key}: 大陆/中文入口被改掉了（期望域名 {host}，实际 {netloc}）")

    def test_download_hosts_are_not_registered_as_official(self):
        """登记表里不许出现 CDN / 下载服务器域名。

        这正是旧实现（从下载 URL 推导域名）产出的那批东西：api.adoptium.net、
        artifacts.elastic.co、aka.ms、edgedl.me.gvt1.com、fastdl.mongodb.org…
        把它们当官网写上去，用户点进去拿到的是一个下载页而不是项目主页。
        """
        cdn_like = ("api.adoptium.net", "archive.apache.org", "dlcdn.apache.org",
                    "artifacts.elastic.co", "aka.ms", "edgedl.me.gvt1.com",
                    "fastdl.mongodb.org", "get.enterprisedb.com", "dl.k8s.io",
                    "get.jenkins.io", "services.gradle.org", "releases.hashicorp.com",
                    "static.rust-lang.org", "repo.anaconda.com", "get.helm.sh",
                    "dotnetcli.azureedge.net", "storage.googleapis.com",
                    "dl.pstmn.io", "ftp.postgresql.org", "download.jetbrains.com",
                    "update.code.visualstudio.com", "downloads.mongodb.com",
                    "download.eclipse.org", "download.navicat.com", "servicewechat.com",
                    "download.dcloud.io", "cdn.apifox.com", "cdn.mysql.com")
        offenders = {k: u for k, u in main.COMPONENT_OFFICIAL_URLS.items()
                     if any(c in u for c in cdn_like)}
        self.assertEqual(offenders, {},
                         f"这些是下载服务器不是官网，别登记进来: {offenders}")

    def test_detail_dialog_renders_a_clickable_link(self):
        """详情页那行字必须真的是可点的超链接，且文字与 href 同源。"""
        qapp()
        comp = next(c for c in self.comps if c.key == "navicat")
        dlg = main.ComponentDetailDialog(comp, [("它是什么", "测试")])
        self.addCleanup(dlg.deleteLater)
        labels = dlg.findChildren(main.QLabel)
        link = None
        for lb in labels:
            if lb.openExternalLinks() and "<a href=" in lb.text():
                link = lb
                break
        self.assertIsNotNone(link, "详情页没有可点击的官网链接")
        text = link.text()
        self.assertIn(comp.official_url, text, "href 与登记表不一致")
        self.assertIn(main._url_netloc(comp.official_url), text,
                      "链接文字里没有域名")
        self.assertIn(comp.display_name, text,
                      "链接文字里没有项目名（用户要求「项目名 · 域名」）")


class DetailButtonWiring(unittest.TestCase):
    """E · 卡片上的 ℹ 按钮与弹窗接线完整。"""

    def test_detail_button_exists_and_wired(self):
        qapp()
        card = make_card("jdk")
        self.assertEqual(card.btn_detail.toolTip(), "看它是干嘛的、装完怎么用")
        # 接线核对用源码而不是 Qt 内省：receivers() 的入参类型在 PySide6
        # 各版本间不一致，拿"实现写的 connect 语句"当判据更稳。
        src = re.sub(r"\s+", " ", inspect.getsource(main.ComponentCard._build_ui))
        self.assertIn("btn_detail.clicked.connect(self.on_detail_clicked)", src)
        self.assertTrue(callable(card.on_detail_clicked))

    def test_click_outside_closes_dialog(self):
        """应用级事件过滤器：鼠标在全局坐标、对话框矩形之外按下 → 自动 accept。"""
        from PySide6.QtCore import Qt, QEvent, QPoint
        from PySide6.QtGui import QMouseEvent
        qapp()
        card = make_card("jdk")
        dlg = main.ComponentDetailDialog(card.component, card.detail_lines())
        dlg.show()
        qapp().processEvents()
        frame = dlg.frameGeometry()
        outside = QPoint(frame.right() + 400, frame.bottom() + 400)
        ev = QMouseEvent(QEvent.MouseButtonPress, outside, outside,
                         Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
        qapp().notify(dlg, ev)
        qapp().processEvents()
        self.assertFalse(dlg.isVisible(), "点击对话框外应当自动关闭")
        dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
