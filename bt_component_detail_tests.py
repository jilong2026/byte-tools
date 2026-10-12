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

_platform._wmi_query = lambda *a, **k: (_ for _ in ()).throw(
    OSError("WMI disabled for test process"))
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

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
        """官方地址取**末位** URL 的域名：首位是镜像，写成"官方地址"就是误导。"""
        jdk = next(c for c in main.build_components() if c.key == "jdk")
        self.assertEqual(main.comp_download_host(jdk), "api.adoptium.net")
        py = next(c for c in main.build_components() if c.key == "python")
        self.assertEqual(main.comp_download_host(py), "www.python.org")


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
