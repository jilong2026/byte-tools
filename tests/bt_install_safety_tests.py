"""卡片初始化 + 官方图标渲染 + 归档解压安全 的护栏测试（离线，不联网）。

跑法：`.venv/Scripts/python.exe -u bt_install_safety_tests.py`

这一套钉死的是 2026-10-13 那次启动崩溃，以及它牵出来的三处防线。

**崩溃本体**：`ComponentCard.__init__` 的执行顺序是
`_build_ui()` → `_detect_status()`。原先「外部版本接管」那组属性的初始化
被塞在 `_load_icon()` 末尾的 fallback 分支里，而该分支上方有一条
「图标加载成功就 return」的早退。于是 jdk（外部接管白名单成员，且
assets/component-icons/jdk.png 确实存在，QPixmap 能读）一进卡片就跳过
初始化，紧接着 `_detect_status()` → `_refresh_external_section()` 读
`self._external_frame` → AttributeError，主窗口起不来，
traceback 停在"正在加载组件 1/87"。

教训有两条，各自对应下面两组用例：
  1. **属性初始化不许写在带早退分支的函数里** → `CardInitRegression`
  2. **下载侧与解压侧面对同一个外部输入，防御标准必须对称** →
     下载侧早有 `_safe_download_name` 且有护栏，解压侧原先是裸
     `extractall` 且无护栏 → `ArchiveTraversalGuard`

顺带钉住图标渲染（`IconRendering`）：旧实现有两处静默失效 ——
拼路径时算出了映射表的值却丢掉了、`QPixmap` 根本读不了 `.svg`。
124 个官方图标于是全部退化成 `key[:3]` 色块，而界面上看不出任何异常。
"""
import io
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402


class _TempConfig:
    """把 CONFIG_DIR / CONFIG_FILE 指到临时目录，用例结束后还原。

    为什么必须包一层：`MainWindow()` 关闭时会走 `closeEvent` → `_save_settings()`，
    而这两个是**模块级全局**。不重定向就等于直接往用户真实的
    `~/.env-tools/config.json` 里写 —— 2026-10-14 实测本文件确实在写
    （跑一遍 `bt_install_safety_tests.py`，真实 config 的 mtime 就变），
    验收四步里的第 4 条「真实配置不许被污染」因此不过。

    ⚠ 清理顺序是**承重的**（同 bt_feedback_tests 的 `_TempConfigDir` 踩过的坑）：
    必须"先关窗 → 再删临时目录 → 最后还原 CONFIG_DIR"。用 cleanup 的**后进先出**
    保证这一点：先注册"删目录 + 还原"（最后执行），后注册窗口清理（最先执行）。
    顺序反了会在 closeEvent 里往一个已消失的目录写，进程撞 0xC0000409。
    """

    def __init__(self, owner, class_level: bool = False):
        self.owner = owner
        self.class_level = class_level
        self.tmp = None
        self._dir = None
        self._file = None

    def _add(self, fn) -> None:
        if self.class_level:
            self.owner.addClassCleanup(fn)
        else:
            self.owner.addCleanup(fn)

    def start(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bt_install_safety_")
        self._add(self.tmp.cleanup)          # 最后执行
        self._dir = main.CONFIG_DIR
        self._file = main.CONFIG_FILE
        self._add(self._restore)             # 倒数第二
        main.CONFIG_DIR = Path(self.tmp.name)
        main.CONFIG_FILE = main.CONFIG_DIR / "config.json"
        return main.CONFIG_DIR

    def _restore(self) -> None:
        main.CONFIG_DIR = self._dir
        main.CONFIG_FILE = self._file


# ---------------------------------------------------------------------------
# 卡片初始化护栏（崩溃回归）
# ---------------------------------------------------------------------------
class CardInitRegression(unittest.TestCase):
    """ComponentCard 构造完就必须具备外部接管那组属性。

    这组用例的存在理由是那条崩溃：它不测行为，只测「属性在不在」——
    恰恰因为那次崩溃是纯 AttributeError，没有别的症状可测。
    """

    # 崩溃现场涉及的那组属性。少任何一个都会在 _refresh_external_section 炸。
    EXTERNAL_ATTRS = (
        "_external_candidates",
        "_external_scanned",
        "_external_expanded",
        "_external_worker",
        "_external_rows",
        "_restore_btn",
        "_external_frame",
        "_external_toggle",
        "_external_body",
    )

    @classmethod
    def setUpClass(cls):
        # 造任何 QWidget 之前必须先有 QApplication，否则 Qt 直接 abort()（症状是
        # 进程以 127 退出、日志里一行 traceback 都没有）。见 _btprelude.ensure_app。
        cls._app = _btprelude.ensure_app()
        cls._components = main.build_components()

    def _make_card(self, comp):
        return main.ComponentCard(comp, lambda lvl, msg: None)

    def test_every_component_card_has_external_attrs(self):
        """**全部**组件建卡后都必须有那组属性 —— 不只是白名单里的 7 个。

        崩溃只发生在白名单成员身上（只有它们会建折叠区并调
        _refresh_external_section），但白名单是会变的；把断言放在全量
        组件上，是为了让"下一个被加进白名单的组件"自动继承这条护栏，
        而不用谁记得再改一遍用例。
        """
        missing = {}
        for comp in self._components:
            card = self._make_card(comp)
            gaps = [a for a in self.EXTERNAL_ATTRS if not hasattr(card, a)]
            if gaps:
                missing[comp.key] = gaps
            card.deleteLater()
        self.assertEqual(
            missing, {},
            "以下组件的卡片缺少外部接管属性（构造顺序被破坏）："
            f"{missing}",
        )

    def test_jdk_card_specifically_is_intact(self):
        """点名 jdk：崩溃现场的那一张卡（白名单成员 + 有同名 png 资产）。

        这条是对上面那条的定点复现：即使将来有人把别处的 bug 修掉、
        让全量用例因为别的原因提前短路，这条仍会单独把 jdk 钉住。
        """
        jdk = next(c for c in self._components if c.key == "jdk")
        self.assertTrue(
            main.supports_external_takeover(jdk),
            "jdk 必须仍在外部接管白名单里（它就是崩溃现场那张卡）；"
            "若这是有意改动，请同步改掉本用例与 __init__ 里那段注释",
        )
        card = self._make_card(jdk)
        for attr in self.EXTERNAL_ATTRS:
            self.assertTrue(hasattr(card, attr), f"jdk 卡片缺少 {attr}")
        # 折叠区控件本身也必须已经建出来（不是 None）
        self.assertIsNotNone(card._external_frame)
        self.assertIsNotNone(card._external_toggle)
        self.assertIsNotNone(card._external_body)
        self.assertIsNotNone(card._restore_btn)
        card.deleteLater()

    def test_state_init_is_not_inside_the_render_method(self):
        """源码级护栏：属性初始化不许再被塞回渲染函数。

        用 inspect.getsource 做这条是有意的：它挡的是"有人又把初始化
        挪回 _render_icon / _load_icon 里"这种**结构性**回归，纯行为断言
        看不见它（两个分支都恰好走到时才不炸）。
        """
        import inspect
        src = inspect.getsource(main.ComponentCard._render_icon)
        for attr in self.EXTERNAL_ATTRS:
            self.assertNotIn(
                f"self.{attr} =", src,
                f"_render_icon() 里出现了 {attr} 的初始化：渲染函数带早退分支，"
                "属性初始化写在里面会被跳过（2026-10-13 启动崩溃的根因）",
            )

    def test_non_whitelist_components_have_no_collapsed_box(self):
        """白名单外的组件不建折叠区控件，但属性仍存在（值为 None）。

        这是 R3.9「非目标组件文案与按钮零变化」的落点，也是
        _refresh_external_section 能安全空转的前提。
        """
        for comp in self._components:
            card = self._make_card(comp)
            if main.supports_external_takeover(comp):
                self.assertIsNotNone(card._external_frame, f"{comp.key} 应有折叠区")
            else:
                self.assertIsNone(card._external_frame, f"{comp.key} 不该有折叠区")
            card.deleteLater()


# ---------------------------------------------------------------------------
# 图标渲染护栏
# ---------------------------------------------------------------------------
class IconRendering(unittest.TestCase):
    """官方图标要真的画得出来，而不是静默退化成色块。"""

    @classmethod
    def setUpClass(cls):
        cls._app = _btprelude.ensure_app()
        cls._components = main.build_components()
        # 渲染要 QtGui/QtSvg，起应用实例就够了，但先按 key 把缓存清掉，
        # 免得本文件与其它套件在同一进程里互相污染缓存结果
        main._ICON_PIXMAP_CACHE.clear()

    def test_assets_dir_is_discoverable(self):
        """图标资产目录必须找得到，否则后面所有用例都是空转。

        打包侧依赖 byte-tools.spec 的 datas 里有 `(assets, "assets")`；
        源码侧依赖 main.py 与 assets/ 同目录。任一条断了都会让 124 个图标
        全部消失，而界面表现只是"卡片左上角空着" —— 不报错、不变红。
        """
        d = main.icon_asset_dir()
        self.assertTrue(
            d.is_dir(),
            f"图标资产目录不存在：{d}（打包侧检查 byte-tools.spec 的 datas）",
        )
        self.assertTrue(
            any(d.iterdir()),
            f"图标资产目录是空的：{d}",
        )

    def test_most_components_get_a_real_icon(self):
        """绝大多数组件要能拿到一张**非空**的 pixmap。

        阈值给到 70% 而不是 100%：有些组件官方确实没有现成图标文件
        （bun / dart / ninja 这类），回色块是预期行为，不该因此判红。
        但如果哪天 SVG 渲染又坏了，这个比例会塌到只剩 png 那批，直接判红。
        """
        ok = 0
        rendered = []
        for comp in self._components:
            pm = main.load_component_icon_pixmap(
                comp.key, main.ICON_BOX_PX * main.ICON_RENDER_SCALE)
            if pm is not None and not pm.isNull():
                ok += 1
                rendered.append(comp.key)
        ratio = ok / max(len(self._components), 1)
        self.assertGreater(
            ratio, 0.70,
            f"只有 {ok}/{len(self._components)} 个组件渲染出图标"
            f"（{ratio:.0%}）。SVG 走的是 QSvgRenderer；若这个比例塌了，"
            f"先查 PySide6.QtSvg 是否可导入、以及 spec 的 hidden_imports。",
        )
        # 抽一个已知同时有两种格式的组件做定点断言
        for key in ("jdk", "python", "node", "git", "docker"):
            if any(c.key == key for c in self._components):
                self.assertIn(key, rendered, f"{key} 的图标没有渲染出来")

    def test_svg_path_is_not_given_to_qpixmap(self):
        """护栏：SVG 必须走 QSvgRenderer，不能直接喂给 QPixmap。

        QPixmap 读 .svg 会得到一张 isNull() 的空图，于是所有图标静默退化。
        这里断言渲染器能吃下真实 svg 文件 —— 顺带证明 QtSvg 真的可用
        （打包漏 hiddenimports 时这里会红，而不是等发版后才发现）。
        """
        from PySide6.QtSvg import QSvgRenderer
        svg = next((main.icon_asset_dir() / f"{c.key}.svg"
                    for c in self._components
                    if (main.icon_asset_dir() / f"{c.key}.svg").is_file()), None)
        if svg is None:
            self.skipTest("资产目录里没有 .svg 图标，跳过 QtSvg 可用性检查")
        self.assertTrue(QSvgRenderer(str(svg)).isValid(),
                        f"QtSvg 读不了 {svg.name}：PySide6.QtSvg 不可用？")

    def test_missing_component_returns_none_not_raise(self):
        """没有图标的组件返回 None（调用方回色块），不许抛异常。"""
        self.assertIsNone(
            main.load_component_icon_pixmap(
                "definitely-not-a-real-component-key", 64),
        )

    def test_lookup_is_by_key_not_by_a_hand_kept_table(self):
        """找图标靠按 key 探测磁盘，不靠那张曾经 0/27 命中的映射表。

        保留这条是为了防止有人"好心"把映射表加回来 —— 它需要人工与
        批量生成的资产目录保持同步，实测已经漂到全部对不上的程度。
        """
        self.assertFalse(
            hasattr(main, "_COMPONENT_ICON_MAP"),
            "_COMPONENT_ICON_MAP 已废止：按 key 探测资产目录才是真源",
        )
        self.assertFalse(
            hasattr(main, "get_component_icon_filename"),
            "get_component_icon_filename 已随映射表一并废止",
        )

    def test_search_box_covers_summary_and_usage(self):
        """搜索必须能命中 summary / usage —— 那两段文案是照着它们生成的。

        修这条之前搜「java」「数据库」「缓存」「消息队列」全部 0 命中，
        而这些词就写在 COMPONENT_SUMMARY 里：文案写了、搜索读不到。
        """
        cases = {
            "java": "jdk",          # 官方叫 Temurin，用户叫 java
            "golang": "go",
            "nodejs": "node",
            "数据库": "mysql",
            "缓存": "redis",
        }
        by_key = {c.key: c for c in self._components}
        for query, expect_key in cases.items():
            if expect_key not in by_key:
                continue
            self.assertTrue(
                main.component_matches(by_key[expect_key], query),
                f"搜 {query!r} 应当命中 {expect_key}",
            )

    def test_search_still_does_not_match_category_names(self):
        """反过来也钉一条：搜分类名不该把整个 Tab 的卡片全捞出来（R2）。"""
        for comp in self._components:
            if main.COMPONENT_CATEGORY_OF.get(comp.key) == "一键启停":
                self.assertFalse(
                    main.component_matches(comp, "一键启停"),
                    f"{comp.key} 不该因分类名被命中",
                )
                break


# ---------------------------------------------------------------------------
# 启动路径顺序护栏
# ---------------------------------------------------------------------------
class StartupOrdering(unittest.TestCase):
    """R18 分帧建卡之后，几个"建卡后才能做"的调用不许留在建卡之前。

    背景：R18 把建卡改成 `QTimer.singleShot(0, ...)` 分帧（每帧 8 张），
    建卡完成前 `self.cards` / `_tab_cards` 都是**空列表**。于是任何放在
    `_build_cards_async` 之前、且遍历这两张列表的调用，都会静默遍历空列表 ——
    不报错、不变红、界面少一个功能。

    2026-10-14 真机上就是这样丢掉了 Tab 上的 `●` 运行标记与"自动跳到运行页"：
    `_adopt_running()` 挂在 `MainWindow()` 之后、`_build_cards_async` 之前，
    它内部的 `for card in self.cards` 与 `_mark_running_tabs()` 全都空跑。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _btprelude.ensure_app()

    def test_adopt_running_marks_tabs_when_cards_exist(self):
        """卡片建好后跑一次标记逻辑，Tab 标题上必须出现 `●`。"""
        # 本用例会 win.close()，而 closeEvent 里会 _save_settings() 写 config.json
        # ⇒ 不隔离就等于写用户的真实配置。见 _TempConfig 的说明。
        _TempConfig(self).start()
        orig_detect = main.ComponentCard._detect_status
        orig_start = main.MainWindow._start_fetch_versions
        main.ComponentCard._detect_status = lambda self, *a, **k: None
        main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
        try:
            win = main.MainWindow()          # 无 splash → 同步建卡
        finally:
            main.ComponentCard._detect_status = orig_detect
            main.MainWindow._start_fetch_versions = orig_start
        try:
            self.assertTrue(win.cards, "窗口建好后 cards 仍为空 —— 本用例的前提不成立")

            # 伪造"一键启停"那一页上有组件在跑。
            # _mark_running_tabs 的判据是 `hasattr(c, "btn_start") and c._running_per_ui()`，
            # 所以只桩后者即可，不动被测函数本身。
            stubbed = []
            for c in win.cards:
                if hasattr(c, "btn_start"):
                    c._running_per_ui = lambda _c=c: True
                    stubbed.append(c)
            self.assertTrue(stubbed, "窗口里没有任何可启停卡片")

            win._mark_running_tabs()
            marked = [win.tabs.tabText(i) for i in range(win.tabs.count())]
            self.assertTrue(
                any("●" in t for t in marked),
                f"没有任何 Tab 标题带 `●` 运行标记：{marked}",
            )

            # 反向校验：都停了就该清掉标记，否则这是"只加不减"的死标记
            for c in stubbed:
                c._running_per_ui = lambda _c=c: False
            win._mark_running_tabs()
            cleared = [win.tabs.tabText(i) for i in range(win.tabs.count())]
            self.assertFalse(
                any("●" in t for t in cleared),
                f"组件都停了 Tab 上还留着 `●`：{cleared}",
            )
        finally:
            try:
                win._closing = True
                win._drain_background_workers()
                win.close()
            except Exception:
                pass
            win.deleteLater()

    def test_adopt_running_is_not_called_before_cards_are_built(self):
        """源码顺序护栏：main() 里 _adopt_running 必须在 _on_cards_ready 内。

        纯行为断言看不见这个 —— 遍历空列表不抛异常。用 inspect.getsource
        是有意的：它挡的正是"有人又把调用挪回建卡之前"这种**结构性**回归。
        """
        import inspect
        src = inspect.getsource(main.main)
        self.assertIn("_on_cards_ready", src, "main() 里找不到 _on_cards_ready")

        # 定位 _adopt_running 在源码里的位置，以及 on_done=_on_cards_ready 的位置。
        # 正确形态：_adopt_running 出现在 _on_cards_ready 的函数体内部，
        # 也就是它的缩进比 def _on_cards_ready 更深。
        lines = src.splitlines()
        def_idx = next((i for i, l in enumerate(lines)
                        if l.strip().startswith("def _on_cards_ready")), None)
        self.assertIsNotNone(def_idx, "main() 里没有 def _on_cards_ready")
        adopt_idx = next((i for i, l in enumerate(lines)
                          if "win._adopt_running()" in l), None)
        self.assertIsNotNone(adopt_idx, "main() 里没有调用 _adopt_running")
        self.assertGreater(
            adopt_idx, def_idx,
            "_adopt_running 又被挪到 _on_cards_ready 之前了 —— 那时卡片还没建完，"
            "Tab 上的运行标记与自动跳页会静默失效（2026-10-14 的真实回归）",
        )
        # 缩进更深 = 在函数体内，而不是模块层
        adopt_indent = len(lines[adopt_idx]) - len(lines[adopt_idx].lstrip())
        def_indent = len(lines[def_idx]) - len(lines[def_idx].lstrip())
        self.assertGreater(
            adopt_indent, def_indent,
            "_adopt_running 与 def _on_cards_ready 同缩进 —— 说明它不在回调体内，"
            "建卡完成前就跑了",
        )


def _set_running(card, value: bool) -> bool:
    """把某张卡的 _running_per_ui 打桩成"恒为 True/False"。

    单独提成函数是为了能被 lambda 闭包安全引用（默认参数在 lambda 里会晚绑定）。
    """
    card._fake_running = value
    return value


# ---------------------------------------------------------------------------
# 依赖方向护栏
# ---------------------------------------------------------------------------
class DependencyDirection(unittest.TestCase):
    """卡片不许反过来依赖顶层窗口 —— 那是方向倒置。

    2026-10-14 之前，ComponentCard 里有 5 处 `MainWindow.current_components()`
    与 3 处 `getattr(self.window(), "_closing", False)`：
    前者让**子组件依赖父容器的类**（MainWindow 一改名这 5 处跟着炸，
    而且卡片无法脱离窗口单测）；后者是绕过构造注入、沿 Qt 父指针爬回去读
    私有属性。两条都在这里钉死。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _btprelude.ensure_app()

    def test_card_does_not_reference_mainwindow_class(self):
        import inspect
        src = inspect.getsource(main.ComponentCard)
        self.assertNotIn(
            "MainWindow.", src,
            "ComponentCard 里不该出现 MainWindow.<...>：卡片是子组件，"
            "不该依赖顶层窗口的类。要组件表请用 main.component_registry()，"
            "要服务管理器请用 main.SERVICE_MANAGER。",
        )

    def test_card_does_not_reach_up_to_the_window_for_state(self):
        import inspect
        src = inspect.getsource(main.ComponentCard)
        self.assertNotIn(
            'getattr(self.window()', src,
            "卡片不该靠 self.window() 读窗口的私有属性（绕过构造注入取全局态）。"
            "退出意图请用 main.is_closing()。",
        )

    def test_component_registry_is_a_single_shared_instance(self):
        """全进程只有一份组件对象。

        此前 __init__ 与 _adopt_running → current_components() 各建一份，
        卡片用的和查前置依赖用的不是同一批对象 —— 等于白构造一次
        88 个 Component（含全部版本表），且两份对象天然会漂移。
        """
        reg_a = main.component_registry()
        main.register_components(main.build_components())
        reg_b = main.component_registry()
        jdk_a, jdk_b = reg_a.get("jdk"), reg_b.get("jdk")
        self.assertIsNotNone(jdk_a)
        self.assertIs(jdk_a, jdk_b,
                      "同一批组件在进程里存在两份对象 —— 必须只有一份真源")

    def test_closing_flag_is_a_module_level_event(self):
        """退出意图是模块级事件，可查可清，且不依赖某个具体窗口实例。"""
        main.reset_closing()
        self.assertFalse(main.is_closing())
        main._CLOSING.set()
        self.assertTrue(main.is_closing())
        main.reset_closing()
        self.assertFalse(main.is_closing(), "reset 后必须真的清掉（它是粘性的）")

    def test_theme_module_holds_the_stylesheet_not_the_window(self):
        """样式表搬去了 theme.py —— 它是纯声明数据，不是逻辑。"""
        from theme import QSS
        self.assertIsInstance(QSS, str)
        self.assertGreater(len(QSS), 1000, "QSS 内容异常短，抽取时可能截断了")
        for selector in ("#centralRoot", "#titleBar", "#logView", "#statusBar"):
            self.assertIn(selector, QSS, f"QSS 里少了 {selector}")
        import inspect
        src = inspect.getsource(main.MainWindow._apply_qss)
        self.assertIn("from theme import QSS", src,
                      "_apply_qss 应该只剩一行 setStyleSheet(QSS)")
        self.assertNotIn("#centralRoot", src,
                         "样式表又写回 _apply_qss 里了")


# ---------------------------------------------------------------------------
# 归档解压安全护栏（zip-slip / tar-slip）
# ---------------------------------------------------------------------------
class ArchiveTraversalGuard(unittest.TestCase):
    """zip-slip / tar-slip 必须被拦住，且正常包照常解开。

    与下载侧 `_safe_download_name` 的护栏（bt_download_only_tests.py）
    是同一套威胁模型的两半：产物名与归档成员名来自同一批公开 release API，
    下载侧早就防了穿越，解压侧原先是裸 extractall 且没有护栏。
    """

    # (成员名, 说明)。Windows 侧 `..\\win\\evil.txt` 也算 —— 归档里反斜杠
    # 作分隔符是有的，判据按两种分隔符一起归一。
    EVIL_MEMBERS = [
        ("../../evil.txt", "POSIX 相对穿越"),
        ("..\\win\\evil.txt", "Windows 反斜杠穿越"),
        ("a/../../evil.txt", "中途绕行再穿越"),
        ("/abs/evil.txt", "POSIX 绝对路径"),
        ("C:/abs/evil.txt", "Windows 盘符绝对路径"),
        ("//srv/share/evil.txt", "UNC 路径"),
        ("\\\\srv\\share\\evil.txt", "UNC 路径（反斜杠）"),
    ]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bt_archive_"))

    def _make_zip(self, name, entries):
        p = self.tmp / name
        with zipfile.ZipFile(p, "w") as z:
            for member, data in entries:
                z.writestr(member, data)
        return p

    def _make_tar(self, name, entries, mode="w:gz"):
        p = self.tmp / name
        with tarfile.open(p, mode) as t:
            for member, data in entries:
                raw = data.encode()
                info = tarfile.TarInfo(member)
                info.size = len(raw)
                t.addfile(info, io.BytesIO(raw))
        return p

    def _out(self, tag):
        d = self.tmp / ("out_" + tag)
        return d

    def test_zip_traversal_members_are_rejected(self):
        for member, why in self.EVIL_MEMBERS:
            with self.subTest(成员=member, 原因=why):
                arc = self._make_zip("evil.zip", [(member, "x")])
                with self.assertRaises(ValueError, msg=f"{member} 未被拦截"):
                    main.extract_archive(arc, self._out("zip"))

    def test_tar_traversal_members_are_rejected(self):
        # 只覆盖 extract_archive 真正支持的 tar 形态：.tar.gz 与 .tar.xz。
        # 未压缩的 .tar 本来就不在支持列表里（会抛"未知的归档类型"），
        # 那是既有行为，不是这里的防线要管的事。
        for member, why in self.EVIL_MEMBERS:
            for ext, mode in ((".tar.gz", "w:gz"), (".tar.xz", "w:xz")):
                with self.subTest(成员=member, 格式=ext):
                    arc = self._make_tar("evil" + ext, [(member, "x")], mode)
                    with self.assertRaises(ValueError, msg=f"{member} 未被拦截"):
                        main.extract_archive(arc, self._out("tar" + ext))

    def test_tar_symlink_member_is_rejected(self):
        """名字老实的符号链接也要拒 —— 它能在解压后把写入引到目标目录外。"""
        p = self.tmp / "link.tar.gz"
        with tarfile.open(p, "w:gz") as t:
            info = tarfile.TarInfo("app/evil-link")
            info.type = tarfile.SYMTYPE
            info.linkname = "C:/Windows/System32"
            t.addfile(info)
        with self.assertRaises(ValueError):
            main.extract_archive(p, self._out("link"))

    def test_nothing_escapes_the_output_dir(self):
        """被拒的包**一个字节都不许落地**（不许部分解压）。

        半解压的目录比不解压更难判断 —— 用户看到的是一个"装了但少了点
        东西"的组件，比明确失败糟糕得多。
        """
        out = self._out("escape")
        arc = self._make_zip("mixed.zip", [("ok.txt", "fine"), ("../evil.txt", "bad")])
        with self.assertRaises(ValueError):
            main.extract_archive(arc, out)
        self.assertFalse(
            (out / "ok.txt").exists(),
            "越界包被拒后，同包里的正常条目不该已经落盘（半解压）",
        )
        self.assertFalse(
            (self.tmp.parent / "evil.txt").exists()
            and not (self.tmp / "evil.txt").exists(),
            "归档里的 ../evil.txt 逃到了目标目录之外",
        )

    def test_normal_archive_still_extracts_and_collapses(self):
        """防住了越界，不许把正常包也一起拦住（单顶层收根规则照旧）。"""
        out = self._out("good")
        arc = self._make_zip(
            "good.zip",
            [("app/bin/tool.exe", "bin"), ("app/README.md", "hi"), ("app/lib/a.so", "lib")],
        )
        root = main.extract_archive(arc, out)
        self.assertTrue((root / "bin" / "tool.exe").exists(),
                        f"单顶层目录没有被收成根：{root}")
        self.assertTrue((root / "README.md").exists())

    def test_normal_tar_still_extracts(self):
        out = self._out("goodtar")
        arc = self._make_tar("good.tar.gz", [("app/bin/tool", "bin")], "w:gz")
        root = main.extract_archive(arc, out)
        self.assertTrue((root / "bin" / "tool").exists(), f"tar 解压后根不对：{root}")

    def test_7z_sfx_is_extracted_not_copied_as_a_binary(self):
        """PortableGit 是 `.7z.exe` 自解压包：必须走 `-o<dir> -y` 展开。

        分支顺序是承重的：`.7z.exe` 也以 `.exe` 结尾，若排在通用 `.exe` 分支之后，
        会被当成"单文件"原样拷进安装目录 —— PATH 里永远找不到 git.exe，界面判成没装。
        这里不真跑 63 MB 的包，用桩确认"调对了展开器、且没有把它当二进制拷走"。
        """
        out = self._out("sfx")
        archive = self.tmp / "git-2.47.1.7z.exe"
        archive.write_bytes(b"MZfake")
        calls = []
        orig_run = main.subprocess.run

        def fake_run(cmd, check=False, **kw):
            calls.append(list(cmd))
            target = Path(str(cmd[1])[2:])      # 去掉 -o 前缀
            (target / "cmd").mkdir(parents=True, exist_ok=True)
            (target / "cmd" / "git.exe").write_bytes(b"MZ")

            class _R:
                returncode = 0
            return _R()

        main.subprocess.run = fake_run
        self.addCleanup(setattr, main.subprocess, "run", orig_run)

        root = main.extract_archive(archive, out)
        self.assertEqual(root, out, "自解压包应直接展开到目标目录，不该有额外的顶层目录")
        self.assertTrue((out / "cmd" / "git.exe").exists(), "桩展开的 git.exe 没落地")
        self.assertEqual(len(calls), 1, f"应只调用一次展开器：{calls}")
        self.assertTrue(str(calls[0][0]).endswith(".7z.exe"), calls)
        self.assertEqual(calls[0][1], f"-o{out}", calls)
        self.assertEqual(calls[0][2], "-y", calls)
        self.assertFalse((out / archive.name).exists(),
                         "自解压包被当成单文件原样拷进了安装目录")


# ---------------------------------------------------------------------------
# 日志浮层：绝不自动弹开（2026-10-14 用户要求"默认不打开"且"偶尔自己弹"要修掉）
# ---------------------------------------------------------------------------
class LogOverlayNeverAutoPops(unittest.TestCase):
    """告警不许把日志浮层顶到用户脸上，只允许在按钮上留未读数。

    这条护栏存在的理由是**曾经真出过这个 bug**：原先的策略是"启动后 10 秒内不自动
    弹，静默 8 秒后自动收起"。那个 10 秒静默期只挡住启动头一段，而一轮版本抓取要
    30~40 秒，于是第 12/25/35 秒到达的告警（GitHub 限流、各组件抓取失败）全都照弹。
    表现上像随机 —— 网络快时失败来得早被挡住，网络慢或撞限流时来得晚就弹，
    用户于是报告"偶尔还是会打开"。所以这里不测"启动后第几秒弹"，只测终局语义：
    **无论过多久、无论多少条告警，浮层都不会自己打开。**
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _btprelude.ensure_app()
        # 关窗路径会写 config.json，不隔离就会写进用户的真实配置（见 _TempConfig）
        _TempConfig(cls, class_level=True).start()
        _orig_fetch = main.MainWindow._start_fetch_versions
        _orig_detect = main.ComponentCard._detect_status
        main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
        main.ComponentCard._detect_status = lambda self, *a, **k: None
        cls._orig_fetch, cls._orig_detect = _orig_fetch, _orig_detect
        cls.win = main.MainWindow()

    @classmethod
    def tearDownClass(cls):
        main.MainWindow._start_fetch_versions = cls._orig_fetch
        main.ComponentCard._detect_status = cls._orig_detect
        cls.win.deleteLater()

    def setUp(self):
        # 每个用例都从"浮层关着"这个初始态开始
        self.win._set_log_open(False)
        self.win._log_unread = 0

    def test_a_warn_does_not_pop_the_overlay(self):
        self.win._append_log("warn", "GitHub API 限流")
        self.assertTrue(self.win.log_overlay.isHidden(),
                        "一条 warn 就把日志浮层弹出来了 —— 用户要的是默认不打开")

    def test_an_error_does_not_pop_the_overlay_either(self):
        self.win._append_log("error", "安装失败：磁盘空间不足")
        self.assertTrue(self.win.log_overlay.isHidden(), "error 也不许自动弹")

    def test_a_burst_of_alerts_never_pops_it(self):
        """模拟真实情形：一轮抓取几十秒内陆续到达几十条告警。"""
        for i in range(50):
            self.win._append_log("warn" if i % 2 else "error", f"第 {i} 条告警")
        self.assertTrue(
            self.win.log_overlay.isHidden(),
            "连续 50 条告警之后浮层自己打开了 —— 自动弹开的逻辑没删干净")

    def test_the_auto_pop_helpers_are_gone(self):
        """连同自动弹开/自动收起的那一整套基础设施一起消失，别留半截。

        只要 _log_autopop_allowed 这类函数还在，就迟早有人再把它接回去 ——
        那个 bug 的成因正是"一个听起来合理的静默期其实盖不住真正的时长"。
        """
        for gone in ("_log_autopop_allowed", "_on_log_auto_hide",
                     "_log_auto_hide", "_log_user_open", "_startup_mono"):
            self.assertFalse(
                hasattr(self.win, gone),
                f"{gone} 还在：日志浮层的自动弹开/自动收起应当整套移除")
        for gone in ("LOG_AUTO_POP_DELAY_MS", "LOG_AUTO_HIDE_MS"):
            self.assertFalse(
                hasattr(main, gone),
                f"模块级常量 {gone} 还在，自动弹开可能被别人再接回去")

    def test_alerts_still_raise_the_unread_badge(self):
        """取消自动弹**不等于**取消提示：未读数必须照旧累加。

        否则用户就完全不知道出事了 —— 浮层不弹是因为"有未读角标可点"，
        不是因为"出事了没人管"。
        """
        self.win._append_log("warn", "第一条")
        self.win._append_log("error", "第二条")
        self.assertGreaterEqual(
            self.win._log_unread, 2,
            "未读数没有累加 —— 用户将完全无从得知发生过告警")
        self.assertIn("日志", self.win.btn_log.text(),
                      "日志按钮上的未读提示不见了")

    def test_clicking_the_button_still_opens_it(self):
        """不自动弹 ≠ 不能手动开。这条钉住取消的是"自动"而不是"功能"。"""
        self.win._on_log_button_clicked()
        self.assertFalse(self.win.log_overlay.isHidden(),
                         "手动点「📋 日志」打不开浮层了 —— 能力被误伤")
        self.win._on_log_button_clicked()
        self.assertTrue(self.win.log_overlay.isHidden(), "再点一次没有收起")


if __name__ == "__main__":
    unittest.main(verbosity=2)

