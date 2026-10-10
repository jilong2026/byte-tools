"""卡片瘦身 + 网格化的规格测试（离线，不联网、不起子进程）。

权威方案：
  · `docs/superpowers/plans/2026-10-08-card-slim-before-grid.md`（卡片瘦身，本轮先做）
  · `docs/superpowers/plans/2026-10-08-ui-grid-cards-and-overlay-log.md`（网格 + 日志浮层）

写这个文件时实现还不存在，所以**红是预期的**。按组划分：

| 组 | 用例类 | 现在（实现前） |
|---|---|---|
| A 卡片瘦身 | `CardButtonsAreSlim` / `StatusTextMovesDetailToTooltip` | **红**（按钮还叫「下载并安装 / 配置环境变量」、固定高 34、下拉框写死 220、状态文本没有 tooltip） |
| B 纯函数 | `GridColumnsForIsTableDriven` / `ChunkVisibleKeepsOrderAndSkipsHidden` | **红**（`grid_columns_for` / `chunk_visible` 还不存在 → AttributeError） |
| C 网格重排 | `RelayoutCardsKeepsOrderAndRowCount` | **红**（`relayout_cards` / `_tab_rows` 不存在） |
| D 视图模式 | `ViewModeDefaultsToGridAndPersists` | **红**（`view_mode` 不存在） |
| E 日志浮层 | `LogOverlayNeverRelayouts` | **红**（`log_overlay` / `_set_log_open` 不存在） |
| F 搜索 | `SearchGridHasNoHoles` | **红**（网格不存在） |
| G 既有行为 | `ExistingBehaviourStillHolds` | **应为绿**——这一组是护栏，它红说明改动打坏了既有行为 |

A2（`btn_start` 文案恒为「启动」）与 G 组是**护栏**：它们在瘦身/网格化之后也必须继续绿，
一旦变红就是"为瘦身动了不该动的东西"。

契约（实现方照此落地，本文件就是规格）：
  · `main.grid_columns_for(available_px, min_card_px) -> int`          模块级纯函数
  · `main.chunk_visible(cards, columns) -> List[List[card]]`           模块级纯函数
  · `main.MIN_CARD_WIDTH_PX`                                            列宽锚点（~300）
  · `MainWindow.relayout_cards(container_key)`                          重排某个容器
  · `MainWindow._tab_rows`                                              按容器登记的行
  · `MainWindow.view_mode`                                              读 config.json 的 `view_mode` 键
  · `MainWindow.log_overlay` / `MainWindow._set_log_open(bool)`         日志浮层

`container_key` 的取值本文件**不写死**：测试从 `_tab_rows` 自己登记的 key 里取出来再传回去
（dict → 用它的键；list → 用 Tab 序号）。断言（行数、顺序、无空位）一律是硬的。
"""
import json
import math
import os
import platform as _platform
import sys
import tempfile
import unittest
from pathlib import Path


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
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel,  # noqa: E402
                               QWidget)

# 分类基线复用对面那份，不另写一张表（理由见 bt_search_and_newcmp_tests.py 顶部）。
from bt_component_category_tests import EXPECTED_MEMBERSHIP  # noqa: E402

ALL_KEYS = {k for g in EXPECTED_MEMBERSHIP.values() for k in g}
TOTAL = sum(len(g) for g in EXPECTED_MEMBERSHIP.values())

_COMPONENTS = main.build_components()

# 抓取版本列表（联网）与探测已装版本（起子进程）在本文件里一律停掉：
# 本文件要验的是布局与文案，不是网络与探测。
#
# **这两个桩必须在 `setUpModule()` 里替换，绝不能在模块级替换**：
# unittest 会先 import 全部模块、再按模块顺序跑。写在模块级的话，替换在 import
# 那一刻就生效，而 tearDownModule 要等本模块跑完才恢复 —— 这中间排在本文件后面的
# 套件造出来的卡片就再也不会探测状态了。
# 实测：写在模块级时，全量 536 条里 multiversion 红 52、refresh 红 4、launch 多红 1；
# 而这三个套件单独跑全都绿（launch 排在最前面还多红，正是"import 即污染"的铁证）。
_ORIG_FETCH_VERSIONS = None
_ORIG_DETECT_STATUS = None


def setUpModule():  # noqa: N802  unittest 规定的驼峰钩子名
    global _ORIG_FETCH_VERSIONS, _ORIG_DETECT_STATUS
    _ORIG_FETCH_VERSIONS = main.MainWindow._start_fetch_versions
    _ORIG_DETECT_STATUS = main.ComponentCard._detect_status
    main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
    main.ComponentCard._detect_status = lambda self, *a, **k: None

# ----------------------------------------------------------------------
# 全局路径的隔离与恢复
#
# `_UsesRealWindow` 会把 CONFIG_DIR/CONFIG_FILE 重定向到临时目录（为了给 D 组造一份
# 「没有 view_mode 键」的老配置）。unittest 在同一进程里按模块名**字母序**跑，本文件
# 排在 bt_launch_tests / bt_multiversion_tests 之前 —— 不恢复的话，那两个套件会全部
# 继承这个临时目录，它们在 ~/.env-tools 下的 fixture 就找不到了。
# 实测：multiversion 单独跑 156 条全绿，跟本文件一起跑会红 52 条。
#
# tearDownModule 在本模块全部用例跑完后触发，正好赶在下一个模块之前，是这里唯一
# 正确的时机；tearDownClass 会被每个继承 `_UsesRealWindow` 的类各触发一次，会过早恢复。
# ----------------------------------------------------------------------
_ORIG_CONFIG_DIR = main.CONFIG_DIR
_ORIG_CONFIG_FILE = main.CONFIG_FILE


def tearDownModule():  # noqa: N802  unittest 规定的驼峰钩子名
    # 只在 setUpModule 真的替换过时才还原：否则会把方法设成 None，比不还原更糟。
    if _ORIG_FETCH_VERSIONS is not None:
        main.MainWindow._start_fetch_versions = _ORIG_FETCH_VERSIONS
    if _ORIG_DETECT_STATUS is not None:
        main.ComponentCard._detect_status = _ORIG_DETECT_STATUS
    main.CONFIG_DIR = _ORIG_CONFIG_DIR
    main.CONFIG_FILE = _ORIG_CONFIG_FILE


# ----------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------
def _build_card(key):
    """单独造一张卡片（不挂进窗口）：卡片级用例不需要整个 MainWindow。

    要 `show()` 一下：offscreen 下没 show 过的控件 `isVisible()` 恒为 False
    （父级不可见），而 `chunk_visible` 判可见性多半就读它——不 show，`isVisible()`
    与 `isHidden()` 会在测试里给出两套互相矛盾的答案。
    """
    comp = next(c for c in _COMPONENTS if c.key == key)
    card = main.ComponentCard(comp, lambda *_a, **_k: None)
    card.show()
    return card


def _effective_height(widget):
    """控件在布局里实际会拿到的高度：被 clamp 到 [minimum, maximum] 的 sizeHint。

    直接读 `sizeHint()` 会被骗：PySide6 的 `sizeHint()` **不受** `setFixedHeight()`
    影响（实测：固定 34 时 `sizeHint()` 仍是 20），而 `setFixedHeight` 改的是
    min/max。所以高度断言必须把 min/max 一起算进来。
    """
    return max(widget.minimumHeight(),
               min(widget.sizeHint().height(), widget.maximumHeight()))


def _rows_registry(win):
    """`_tab_rows` 本体；没落地就给一句人话，而不是让 None 在迭代处炸。"""
    rows = getattr(win, "_tab_rows", None)
    if rows is None:
        raise AssertionError("MainWindow 还没有 _tab_rows —— 网格重排没落地")
    return rows


def _row_cards(rows):
    """把"行"统一成卡片列表：行可以是 QWidget 行容器，也可以是卡片序列。"""
    out = []
    for row in rows:
        if isinstance(row, QWidget):
            out.append(list(row.findChildren(main.ComponentCard)))
        else:
            out.append(list(row))
    return out


def _container_keys(win):
    """实现自己登记的容器 key（dict → 键；list → Tab 序号）。"""
    rows = _rows_registry(win)
    if isinstance(rows, dict):
        return list(rows)
    return list(range(win.tabs.count()))


def _container_key(win, index=0):
    return _container_keys(win)[index]


def _rows_of(win, key):
    """某个容器的行（list[list[card]]）。"""
    rows = _rows_registry(win)
    if isinstance(rows, dict):
        return _row_cards(rows[key])
    return _row_cards(rows)


def _row_shape(win):
    """行形状快照：每个容器 → (行数, 每行卡片数)。E 组比对的就是这个。"""
    rows = _rows_registry(win)
    if isinstance(rows, dict):
        return {k: (len(v), tuple(len(x) for x in _row_cards(v)))
                for k, v in rows.items()}
    return (len(rows), tuple(len(x) for x in _row_cards(rows)))


def _relayout_all(win):
    """把所有 Tab 容器重排一遍（E/F 组要一个"已排好"的基线）。"""
    for key in _container_keys(win):
        win.relayout_cards(key)


# ----------------------------------------------------------------------
# 共享一个真 MainWindow
# ----------------------------------------------------------------------
_SHARED = {"win": None, "tmp": None}


class _UsesRealWindow:
    """共享一个真 MainWindow：`__init__` 会建 26 张卡片，每个类各建一个太贵。

    构造期只停掉"抓版本"与"探测已装版本"（见上面的全局桩），并把 `CONFIG_DIR` /
    `CONFIG_FILE` 指向临时目录——写一份**没有 `view_mode` 键**的老配置，正覆盖 D 组
    "老配置自动获得新默认"那条。
    """

    @classmethod
    def setUpClass(cls):
        if _SHARED["win"] is None:
            _SHARED["app"] = QApplication.instance() or QApplication([])
            _SHARED["tmp"] = tempfile.TemporaryDirectory()
            main.CONFIG_DIR = Path(_SHARED["tmp"].name)
            main.CONFIG_FILE = main.CONFIG_DIR / "config.json"
            main.CONFIG_FILE.write_text(
                json.dumps({"selections": {}, "active": {}}), encoding="utf-8")
            win = main.MainWindow()
            # 同上：不 show 的话窗口里所有卡片的 isVisible() 都是 False，
            # "可见卡片"这件事在测试里就没法判了。
            win.show()
            _SHARED["win"] = win
        cls.win = _SHARED["win"]

    def _visible_in_tab(self, index):
        """该 Tab 内"可见"的卡片。

        用 `isHidden()` 而不是 `isVisible()`：`isVisible()` 还要看父级，
        而既有的搜索用例（`bt_search_and_newcmp_tests`）也是按 `isHidden()` 判的，
        两边必须一致。
        """
        return [c for c in self.win._tab_cards[index] if not c.isHidden()]

    def _tab_index_of(self, category):
        return list(EXPECTED_MEMBERSHIP).index(category)


# ======================================================================
# A. 卡片瘦身
# ======================================================================
class CardButtonsAreSlim(unittest.TestCase):
    """按钮文案与尺寸（方案第 1、2、3 节）。

    现在红是预期的：按钮还叫「下载并安装 / 配置环境变量」，固定高 34，下拉框写死 220。

    注意：`MULTI_VERSION_KEYS` 是空集、`build_components()` 里 `multi_version` 恒为 True，
    所以"非多版本组件"这个分支现在没有样本——下面对**每一张**卡片断言，两个分支一起钉。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.cards = {k: _build_card(k) for k in ("jdk", "kafka", "docker")}

    def test_install_button_says_install(self):
        """「下载并安装」→「安装」。tooltip 里已有完整说明，按钮不必再重复一遍。"""
        for key, card in self.cards.items():
            self.assertEqual(card.btn_install.text(), "安装", key)

    def test_configure_button_says_switch(self):
        """「配置环境变量 / 切换为生效版本」→「切换」。

        多版本语义靠 tooltip 承载：按钮上省掉的只是那句"改 XXX_HOME 与 PATH"的说明。
        """
        for key, card in self.cards.items():
            self.assertEqual(card.btn_configure.text(), "切换", key)

    def test_uninstall_button_stays_uninstall(self):
        """「卸载」已经是最短形态，不许被瘦身顺手改掉。"""
        for key, card in self.cards.items():
            self.assertEqual(card.btn_uninstall.text(), "卸载", key)

    def test_start_button_text_is_untouched(self):
        """**护栏**：`btn_start` 文案必须是「启动」，一个字都不许动。

        `_running_per_ui()`（main.py:8809）读这个按钮的文字判断是否在运行，
        `_mark_running_tabs` / `_reveal_running_tabs` 都依赖它；它还有「启动中…」
        「停止中…」「准备依赖…」等中间态也走同一处读。给启动按钮改文案 =
        静默弄瞎"是否在运行"的判据。这条在瘦身前后都必须绿。
        """
        for key, card in self.cards.items():
            if not hasattr(card, "btn_start"):
                continue
            self.assertEqual(card.btn_start.text(), "启动", key)
            # 把判据一起钉住：文字改了，判据就跟着改 —— 那正是要防的事
            self.assertFalse(card._running_per_ui(), key)
            card.btn_start.setText("停止")
            self.addCleanup(card.btn_start.setText, "启动")
            self.assertTrue(card._running_per_ui(), key)

    def test_console_button_has_the_secondary_object_name(self):
        """`btn_console` 必须挂 `#secondaryBtn`。

        它现在没有 objectName，于是 `#primaryBtn/#secondaryBtn/#dangerBtn` 三条 QSS
        全都匹配不到它 —— 拿系统默认样式，实测比旁边几颗按钮宽一圈（方案第 3 节
        记的这个真实缺陷）。
        """
        card = self.cards["kafka"]
        self.assertIsNotNone(getattr(card, "btn_console", None),
                             "kafka 是可启停组件，卡片上必须有 btn_console")
        self.assertEqual(card.btn_console.objectName(), "secondaryBtn")

    def test_version_combo_is_no_longer_pinned_to_220(self):
        """下拉框不许再写死 220：313px 的格子里 220 的下拉框会直接顶爆按钮行。

        写死的判据是 min==max==220（`setFixedWidth` 同时改这两者）。
        """
        for key, card in self.cards.items():
            combo = card.version_combo
            self.assertLessEqual(combo.minimumWidth(), 180, key)
            self.assertNotEqual((combo.minimumWidth(), combo.maximumWidth()),
                                (220, 220), f"{key} 的下拉框宽度仍是写死的 220")

    def test_buttons_are_at_most_32_px_tall(self):
        """按钮高度 34 → 30：卡片从 121 涨到 157 的预算里，按钮这 4px 要省下来。

        读 `_effective_height` 而不是 `sizeHint()`：固定高不改 sizeHint（见其 docstring）。
        """
        names = ("btn_install", "btn_configure", "btn_uninstall",
                 "btn_start", "btn_console", "btn_cancel")
        for key, card in self.cards.items():
            for name in names:
                btn = getattr(card, name, None)
                if btn is None:
                    continue
                self.assertLessEqual(_effective_height(btn), 32,
                                     f"{key}.{name} 太高了：{_effective_height(btn)}")


class StatusTextMovesDetailToTooltip(unittest.TestCase):
    """状态行：主文本精简，细节**转移**到 tooltip（方案第 5 节）。

    格子内部只有 271px，而 `QLabel` 没有 `setElideMode`（超宽是直接 clip，不是省略号），
    所以长文案只能靠"主文本写结论、tooltip 写全文"。判据字段
    （`_status_shows_configured` / `_mv_active` / `_mv_warned` 等）一律不动。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.card = _build_card("jdk")

    def _render(self, where, version=""):
        card = self.card
        card._mv_capsule = ""            # 走通用的「✓ 已配置」分支
        card._status_shows_configured = True
        card._status_where = where
        card._status_version = version
        card._render_status_label()
        return card.status_label.text(), card.status_label.toolTip()

    def test_configured_status_drops_the_long_tail(self):
        """「✓ 已配置（JAVA_HOME · 系统安装，不由本工具管理）」→「✓ 已配置 · 系统安装」。

        那句"不由本工具管理"是**结论**（这枚已配置不是本工具装的），不是废话 ——
        它必须从主文本挪进 tooltip，不许丢。
        """
        for where in ("JAVA_HOME · 系统安装，不由本工具管理",
                      "PATH · 系统安装，不由本工具管理"):
            with self.subTest(where=where):
                text, tip = self._render(where)
                self.assertNotIn("不由本工具管理", text,
                                 f"主文本还挂着长尾巴：{text}")
                self.assertTrue(tip, "细节必须转移到 tooltip，不能丢信息")
                self.assertIn("不由本工具管理", tip,
                              "tooltip 里要留着'不由本工具管理'这个结论")

    def test_configured_status_keeps_the_version_in_the_main_text(self):
        """版本号是主文本该留的信息（「✓ 已配置 · 系统安装 · 21.0.5」），别一起精简掉。"""
        text, tip = self._render("系统安装", "21.0.5")
        self.assertIn("21.0.5", text)
        self.assertTrue(tip, "有版本号时 tooltip 也要有全文")

    def test_multi_version_capsule_keeps_its_full_text_in_the_tooltip(self):
        """多版本胶囊：主文本写结论，胶囊全文（含版本列表）留在 tooltip 里。

        版本列表是"到底装了哪几个"的唯一出处，主文本放不下可以，丢掉不行。
        """
        card = self.card
        capsule = "● 已装 3 个版本 · 生效 21.0.5（21.0.5、17.0.13、11.0.25）"
        card._mv_capsule = capsule
        card._mv_orange = False
        card._status_shows_configured = True
        card._status_version = ""
        card._render_status_label()
        self.assertTrue(card.status_label.text(), "主文本不许是空的")
        self.assertTrue(card.status_label.toolTip(), "胶囊全文必须落到 tooltip")
        self.assertIn("17.0.13", card.status_label.toolTip(),
                      "tooltip 里要能查到完整的版本列表")


# ======================================================================
# B. 模块级纯函数
# ======================================================================
class GridColumnsForIsTableDriven(unittest.TestCase):
    """`grid_columns_for(available_px, min_card_px)`：列数只由宽度决定。

    现在红是预期的：函数还不存在。
    """

    def test_table(self):
        """640→2 列、400→1 列、1000→3 列（`MIN_CARD_WIDTH_PX` 取 ~300 时的锚点）。

        （旧设计里「640 视口 2 列」配 `MIN_CARD_WIDTH_PX≈470` 是自相矛盾的 ——
        640÷470 只能出 1 列。方案里已把锚点改成 ~300。）
        """
        self.assertEqual(main.grid_columns_for(640, 300), 2)
        self.assertEqual(main.grid_columns_for(400, 300), 1)
        self.assertEqual(main.grid_columns_for(1000, 300), 3)

    def test_constant_anchor_gives_two_columns_at_640(self):
        """常量与函数必须自洽：视口 640 下用 `MIN_CARD_WIDTH_PX` 要正好 2 列。"""
        self.assertIsInstance(main.MIN_CARD_WIDTH_PX, int)
        self.assertEqual(main.grid_columns_for(640, main.MIN_CARD_WIDTH_PX), 2)

    def test_degenerate_values_fall_back_to_one_column(self):
        """极窄 / 0 / 负数 / None → 1 列。

        视口宽度在窗口最小化、布局未生效时会是 0，`min_card_px` 也可能没取到 ——
        除零或负列数会让整片卡片消失，宁可退化成一列。
        """
        for px in (0, -50, None, 1):
            with self.subTest(available=px):
                self.assertEqual(main.grid_columns_for(px, 300), 1)
        for mpx in (0, -1, None):
            with self.subTest(min_card=mpx):
                self.assertEqual(main.grid_columns_for(640, mpx), 1)

    def test_result_is_never_below_one(self):
        for px in (0, 1, 299, 300, 301, 959, 10000):
            self.assertGreaterEqual(main.grid_columns_for(px, 300), 1)


class ChunkVisibleKeepsOrderAndSkipsHidden(unittest.TestCase):
    """`chunk_visible(cards, columns)`：保序、只排可见卡片。

    现在红是预期的：函数还不存在。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.cards = [_build_card(k) for k in ("jdk", "node", "go", "kafka", "docker")]

    def test_order_is_preserved_and_rows_are_full(self):
        cards = self.cards
        for columns in (1, 2, 3):
            with self.subTest(columns=columns):
                chunks = main.chunk_visible(cards, columns)
                self.assertEqual([c for ch in chunks for c in ch], cards,
                                 "分块不许打乱顺序")
                visible = [c for c in cards if c.isVisible()]
                self.assertEqual(len(chunks), math.ceil(len(visible) / columns))
                for ch in chunks[:-1]:
                    self.assertEqual(len(ch), columns, "除最后一行外每行都要排满")

    def test_hidden_cards_never_appear_in_any_chunk(self):
        """**回归护栏**：搜索命中 1 个时网格出现空洞。

        QBoxLayout 会给隐藏控件留位；只要分块把隐藏卡片也排进来，那一格就是个洞。
        """
        cards = self.cards
        cards[1].setVisible(False)
        self.addCleanup(cards[1].setVisible, True)
        chunks = main.chunk_visible(cards, 2)
        flat = [c for ch in chunks for c in ch]
        self.assertNotIn(cards[1], flat, "隐藏卡片进了分块")
        self.assertEqual(flat, [cards[0], cards[2], cards[3], cards[4]])
        for ch in chunks:
            for c in ch:
                self.assertTrue(c.isVisible(), "分块里出现了不可见的卡片")

    def test_single_card_is_a_single_row(self):
        self.assertEqual(main.chunk_visible([self.cards[0]], 2), [[self.cards[0]]])

    def test_nothing_visible_gives_no_rows(self):
        cards = self.cards[:2]
        for c in cards:
            c.setVisible(False)
            self.addCleanup(c.setVisible, True)
        self.assertEqual(main.chunk_visible(cards, 2), [])


# ======================================================================
# C. 网格重排
# ======================================================================
class RelayoutCardsKeepsOrderAndRowCount(_UsesRealWindow, unittest.TestCase):
    """`relayout_cards(container_key)`：行数 = ceil(N/C)，顺序 = 原顺序。

    现在红是预期的：`relayout_cards` / `_tab_rows` 还不存在。
    """

    # `_visible_in_tab` **沿用基类那份**（按 `isHidden()` 判），这里不覆写。
    # 覆写成 `isVisible()` 是错的：卡片所在 Tab 页没被翻到时父级不可见，
    # isVisible() 恒为 False（offscreen 实测），于是"非当前页"会退化成空列表，
    # 与本文件 F 组「清空搜索后每张卡都要按原顺序回到原 Tab」直接冲突。
    # 隐藏只由搜索触发（`setVisible(False)`），所以判据统一是 isHidden()。

    def test_rows_are_ceil_n_over_c_and_order_is_preserved(self):
        win = self.win
        key = _container_key(win, 0)
        expect = self._visible_in_tab(0)
        self.assertGreater(len(expect), 3, "开发环境页卡片太少，这条用例测不出分块")
        orig = main.grid_columns_for
        self.addCleanup(setattr, main, "grid_columns_for", orig)
        for columns in (1, 2, 3):
            with self.subTest(columns=columns):
                # 列数由 grid_columns_for 决定，这里把它钉成定值，行数才可由用例算出
                main.grid_columns_for = lambda *a, _c=columns, **k: _c
                win.relayout_cards(key)
                rows = _rows_of(win, key)
                self.assertEqual(len(rows), math.ceil(len(expect) / columns))
                for row in rows[:-1]:
                    self.assertEqual(len(row), columns, "除最后一行外每行都要排满")
                self.assertEqual([c for row in rows for c in row], expect,
                                 "切一次视图卡片顺序就乱掉了")

    def test_relayout_does_not_drop_or_duplicate_cards(self):
        win = self.win
        for index in range(win.tabs.count()):
            with self.subTest(tab=win.tabs.tabText(index)):
                key = _container_key(win, index)
                win.relayout_cards(key)
                rows = _rows_of(win, key)
                flat = [c for row in rows for c in row]
                self.assertEqual(len(flat), len(set(map(id, flat))),
                                 "同一张卡片被排进了两行")
                self.assertEqual(flat, self._visible_in_tab(index))


# ======================================================================
# D. 视图模式
# ======================================================================
class ViewModeDefaultsToGridAndPersists(_UsesRealWindow, unittest.TestCase):
    """`view_mode` 读写 `config.json`：缺键 → `grid`；列表模式 = 恒 1 列。

    现在红是预期的：`view_mode` 还不存在。

    三个用例共用那一个真窗口，所以每个用例都要把 `view_mode` **还原成用例开始前
    的形态**（本来不存在就删掉）——不然前一个用例的清理顺手赋上 "grid"，
    下一条"缺键取默认"就被自己人喂成了假绿。
    """

    def setUp(self):
        self._had_view_mode = hasattr(self.win, "view_mode")
        self._orig_view_mode = getattr(self.win, "view_mode", None)

    def _restore_view_mode(self):
        if self._had_view_mode:
            self.win.view_mode = self._orig_view_mode
        elif hasattr(self.win, "view_mode"):
            del self.win.view_mode

    def test_missing_key_reads_as_grid(self):
        """老配置（有 selections/active、没有 view_mode）必须自动获得新默认，且不报错。"""
        self.assertEqual(self.win.view_mode, "grid")

    def test_list_mode_is_always_one_column(self):
        win = self.win
        self.addCleanup(self._restore_view_mode)
        self.addCleanup(win.relayout_cards, _container_key(win, 0))
        win.view_mode = "list"
        win.relayout_cards(_container_key(win, 0))
        rows = _rows_of(win, _container_key(win, 0))
        self.assertTrue(rows, "列表模式也要排出行来")
        for row in rows:
            self.assertEqual(len(row), 1, "列表模式恒 1 列")

    def test_mode_is_written_back_and_read_again(self):
        win = self.win
        self.addCleanup(self._restore_view_mode)
        self.addCleanup(win._save_settings)
        win.view_mode = "list"
        win._save_settings()
        saved = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved.get("view_mode"), "list", "切换没写回 config.json")

        bare = main.MainWindow.__new__(main.MainWindow)
        bare.cards = []
        bare.view_mode = "<未加载>"      # 哨兵：_load_settings 不认这个键就该被覆盖
        bare._load_settings()
        self.assertEqual(bare.view_mode, "list", "重读没拿到写回的 list")

        win.view_mode = "grid"
        win._save_settings()
        saved = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved.get("view_mode"), "grid", "切回网格没写回（写死 list？）")


# ======================================================================
# E. 日志浮层
# ======================================================================
class LogOverlayNeverRelayouts(_UsesRealWindow, unittest.TestCase):
    """**浮层方案的核心承诺**：日志展开/收起不触发重排。

    浮层是"盖在网格上"，不是"把网格挤扁"—— 后者会让列数随日志开关忽大忽小，
    并带来一次二次 relayout。现在红是预期的：`log_overlay` / `_set_log_open` 不存在。
    """

    def test_opening_and_closing_the_overlay_keeps_every_row(self):
        win = self.win
        self.assertTrue(hasattr(win, "log_overlay"), "没有 log_overlay 浮层容器")
        self.assertTrue(hasattr(win, "_set_log_open"), "没有 _set_log_open 开关")
        _relayout_all(win)                       # 先拿一个"已排好"的基线
        before = _row_shape(win)
        self.assertTrue(before, "基线是空的，这条用例等于没钉")

        win._set_log_open(True)
        self.assertFalse(win.log_overlay.isHidden(), "_set_log_open(True) 没把浮层显示出来")
        during = _row_shape(win)

        win._set_log_open(False)
        self.assertTrue(win.log_overlay.isHidden(), "_set_log_open(False) 没把浮层收起来")
        after = _row_shape(win)

        self.assertEqual(before, during, "展开日志把网格重排了")
        self.assertEqual(before, after, "收起日志把网格重排了")


# ======================================================================
# F. 搜索
# ======================================================================
class SearchGridHasNoHoles(_UsesRealWindow, unittest.TestCase):
    """搜索结果面板始终是**网格**：行里没有"消失的卡片"，命中数不足一行时用透明占位格补齐。

    2026-10-10 口径变更：以前定的是"命中 1 个就 1 列、一张卡占满整行"（不想看到
    孤零零一张小卡缩在左上角），用户现在明确要求"只有一个组件也要以网格显示"。
    所以"没有洞"的含义从"不补占位"变成"补了占位、卡片仍只占一格"。
    """

    def _container_holding(self, key_of_card):
        """返回装着这张卡片的那个容器的 key（搜索时应当是统一结果面板）。"""
        win = self.win
        for key in _container_keys(win):
            for row in _rows_of(win, key):
                if any(c.component.key == key_of_card for c in row):
                    return key
        self.fail(f"{key_of_card} 不在任何容器里 —— 搜索结果没有重排")

    def test_single_hit_row_holds_only_that_card(self):
        win = self.win
        win.search_box.setText("kafka")
        self.addCleanup(win.search_box.setText, "")
        hits = [c for c in win.cards if not c.isHidden()]
        self.assertEqual([c.component.key for c in hits], ["kafka"])

        key = self._container_holding("kafka")
        rows = [row for row in _rows_of(win, key) if row]
        self.assertEqual(len(rows), 1, f"命中 1 个却排出了 {len(rows)} 行")
        # 这里数的是**卡片**（_row_cards 只认 ComponentCard），透明占位格不算：
        # 一行里有 1 张卡 + 若干占位格才是网格；1 张卡独占整行是列表。
        self.assertEqual(len(rows[0]), 1, "这一行里混进了别的卡片")
        self.assertEqual(rows[0][0].component.key, "kafka")

    def test_single_hit_keeps_the_same_cell_count_as_browsing(self):
        """命中 1 个也必须按网格排：结果行的**格子数**要等于浏览行的格子数。

        2026-10-10 用户改的口径：以前定的是"命中 1 个就 1 列、一张卡占满整行"
        （不想看到孤零零一张小卡缩在左上角），现在明确要求"只有一个组件也要以网格显示"。
        判据用格子数而不是卡片像素宽：少一个占位格，`addWidget(card, 1)` 就会把
        这张卡拉成整行宽 —— 占位格正是"等宽"的直接原因，而像素宽在 offscreen 下
        还受窗口是否真正 show 影响，不是干净的判据。
        """
        win = self.win
        _relayout_all(win)
        idx = next(i for i in range(win.tabs.count())
                   if any(c.component.key == "kafka" for c in win._tab_cards[i]))
        browse_row = next(r for r in win._tab_rows[idx]
                          if any(c.component.key == "kafka"
                                 for c in r.findChildren(main.ComponentCard)))
        cells = browse_row.layout().count()
        self.assertGreaterEqual(cells, 2, "浏览时 kafka 所在行只有一格，这条用例钉不住东西")

        win.search_box.setText("kafka")
        self.addCleanup(win.search_box.setText, "")
        rows = win._tab_rows.get(main.RESULTS_KEY) or []
        hit_row = next((r for r in rows
                        if any(c.component.key == "kafka"
                               for c in r.findChildren(main.ComponentCard))), None)
        self.assertIsNotNone(hit_row, "搜索后 kafka 不在任何结果行里")
        self.assertEqual(hit_row.layout().count(), cells,
                         "命中 1 个时结果行的格子数与浏览时不等 —— 那张卡被拉成了整行宽")
        self.assertEqual([c.component.key for c in hit_row.findChildren(main.ComponentCard)],
                         ["kafka"], "结果行里混进了别的卡片")

    def test_clearing_search_puts_every_card_back_in_order(self):
        win = self.win
        win.search_box.setText("kafka")
        win.search_box.setText("")
        self.assertEqual(win.top_stack.currentIndex(), 0, "清空后应回到 Tab 浏览")
        self.assertEqual(len([c for c in win.cards if not c.isHidden()]), TOTAL)
        _relayout_all(win)
        for index in range(win.tabs.count()):
            with self.subTest(tab=win.tabs.tabText(index)):
                rows = _rows_of(win, _container_key(win, index))
                self.assertEqual([c for row in rows for c in row],
                                 win._tab_cards[index],
                                 "清空搜索后卡片没按原顺序回到原 Tab")


# ======================================================================
# F2. 带背景的标签不许被竖直拉伸（真机 2026-10-10 用户截图）
# ======================================================================
class BadgeNeverStretchesVertically(unittest.TestCase):
    """同一行的卡片会被拉成等高，内容少的那张多出来的高度不许灌进标题行。

    用户看到的症状：「可多版本」角标在 JDK / Python 卡上是一个**高盒子**，
    在 Maven / Node.js 卡上是一枚紧凑胶囊 —— 字一样大，框不一样高。
    根因不是字号（真机逐张量过：26 张卡的角标全是 66×20、11px）：
    网格会把同一行的卡片拉成等高，而 Maven 那张卡多了「系统里检测到的版本」
    折叠区与「还原」两行，把整行撑高；卡片主布局**末尾没有 stretch**，
    多出来的高度于是被各行分掉，标题行里的角标是带背景色的 QLabel，
    一被拉高就变成一个大框。
    """

    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def _row_with(self, short_key: str, tall_key: str):
        comps = {c.key: c for c in main.build_components()}
        short = main.ComponentCard(comps[short_key], lambda msg, level=None: None)
        tall = main.ComponentCard(comps[tall_key], lambda msg, level=None: None)
        tall._external_frame.setVisible(True)      # 复刻"Maven 卡多了两行内容"
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(short, 1)
        lay.addWidget(tall, 1)
        row.resize(820, 420)
        row.show()
        for _ in range(8):
            self.app.processEvents()
        self.addCleanup(row.deleteLater)
        return short, tall

    def test_badge_height_is_its_size_hint_not_the_leftover_space(self):
        short, tall = self._row_with("jdk", "maven")
        self.assertGreater(tall.height(), short.minimumSizeHint().height(),
                           "对照组失效：两张卡本来就不等高，这条用例钉不住东西")
        self.assertGreater(short.height(), short.sizeHint().height(),
                           "短卡片没被拉高，说明这一行根本没有多余空间")
        badge = short.findChild(QLabel, "multiVersionBadge")
        self.assertEqual(badge.height(), badge.sizeHint().height(),
                         "角标被竖直拉伸了：它的高度必须等于自己的 sizeHint，"
                         "否则同一行里内容少的卡片会显示成一个大盒子")


# ======================================================================
# F3. 底部状态条：组件数、可点的工作目录、版本号（2026-10-10 用户三条要求）
# ======================================================================
class StatusBarFacts(_UsesRealWindow, unittest.TestCase):
    """状态条上那三个数字/链接必须是真话，而且彼此不能打架。"""

    def _plain(self):
        import re
        return re.sub("<[^>]+>", "", self.win.status_bar.text())

    def test_component_count_is_what_the_user_can_actually_see(self):
        """总数按**界面可见**的卡片算，与搜索提示同一个分母。

        erlang 是 hidden 组件（只作 rabbitmq 的前置依赖，不出现在任何 Tab），
        以前状态条写 `len(self.components)` = 27，而搜索框右边写的是 / 26 ——
        同一屏两个数字互相矛盾，用户自然怀疑清单是不是漏了一个。
        """
        win = self.win
        visible = len(win.cards)
        self.assertEqual(visible, 26, "界面可见组件数变了，这条用例的基线要一起核")
        self.assertIn(f"组件总数：{visible} 个", self._plain())
        self.assertNotIn(f"组件总数：{len(win.components)} 个", self._plain())
        # 隐藏组件不许悄悄消失：总数旁边要交代它去哪了
        self.assertIn("前置依赖", self._plain())

    def test_working_directory_is_a_link_pointing_at_the_real_dir(self):
        import re
        hrefs = re.findall(r'href="([^"]+)"', self.win.status_bar.text())
        self.assertTrue(hrefs, "工作目录没做成链接 = 用户只能照着路径手敲")
        target = hrefs[0][len("dir://"):]
        self.assertEqual(Path(target).as_posix(), Path(main.CONFIG_DIR).as_posix())

    def test_clicking_the_link_asks_the_os_to_open_the_folder(self):
        import re
        href = re.findall(r'href="([^"]+)"', self.win.status_bar.text())[0]
        calls = []
        orig = main._open_in_file_manager
        self.addCleanup(setattr, main, "_open_in_file_manager", orig)
        main._open_in_file_manager = lambda p: calls.append(p) or True
        self.win._on_status_link(href)
        self.assertEqual([Path(p).as_posix() for p in calls],
                         [Path(main.CONFIG_DIR).as_posix()])

    def test_version_shows_up_in_ui_and_is_not_behind_the_latest_tag(self):
        self.assertIn(f"v{main.APP_VERSION}", self._plain(),
                      "状态条要显示版本号，用户报问题时第一眼就能对上版本")
        title = self.win.findChild(QLabel, "titleText")
        self.assertIn(main.APP_VERSION, title.toolTip() or title.text())
        import subprocess
        try:
            out = subprocess.run(["git", "describe", "--tags", "--abbrev=0"],
                                 capture_output=True, text=True, timeout=20,
                                 cwd=str(Path(main.__file__).parent))
            tag = (out.stdout or "").strip()
        except Exception:      # noqa: BLE001  没有 git 就不硬失败
            tag = ""
        if not tag:
            self.skipTest("拿不到 git tag，无法核对 APP_VERSION 是否落后于最新发布")
        # 判据是**不许落后**，不是"必须相等"：正常的发版顺序是"先改常量提交 → 再打 tag"，
        # 中间那段时间常量本来就领先一个版本。第一版我写成 assertEqual，
        # 结果把这条正当流程判成红 —— 自己造的护栏反过来挡了发版。
        self.assertFalse(main.version_is_newer(main.APP_VERSION, tag.lstrip("v")),
                         f"APP_VERSION={main.APP_VERSION} 落后于最新发布 {tag}："
                         "发版前把 main.py 的常量一起提，否则发出去的包显示的是旧版本")


# ======================================================================
# G. 既有行为不得回归
# ======================================================================
class ExistingBehaviourStillHolds(_UsesRealWindow, unittest.TestCase):
    """护栏组：既有断言一条都不许为迁就改动而改，这里把等价判据**重新钉一遍**。

    这组现在**应该是绿的**；它变红 = 瘦身/网格化打坏了既有行为。
    """

    def test_every_tab_page_still_holds_exactly_its_own_cards(self):
        """`findChildren(ComponentCard)` 的数量与归属：卡片搬家（进 Tab / 进行容器）后
        仍然要能在对应页里被找到，既有用例 `test_cards_live_in_their_category_tab`
        就是这么查的。"""
        win = self.win
        for index, name in enumerate(EXPECTED_MEMBERSHIP):
            page = win.tabs.widget(index)
            cards = page.findChildren(main.ComponentCard)
            self.assertEqual({c.component.key for c in cards},
                             EXPECTED_MEMBERSHIP[name], name)
            self.assertEqual(len(cards), len(EXPECTED_MEMBERSHIP[name]), name)
        self.assertEqual(len(win.findChildren(main.ComponentCard)), TOTAL)

    def test_uninstall_button_starts_disabled_and_says_why(self):
        """卸载按钮默认禁用 + tooltip 非空。

        禁用是"未安装时不给点不动的按钮"；tooltip 是"为什么点不动"的去处，
        改造不许把这两个一起精简掉。
        """
        card = next(c for c in self.win.cards if c.component.key == "jdk")
        self.assertFalse(card.btn_uninstall.isEnabled(), "未安装时卸载按钮必须禁用")
        self.assertTrue(card.btn_uninstall.toolTip(), "禁用的按钮要说明为什么")

    def test_uninstall_is_locked_while_the_component_is_running(self):
        """运行中必须锁住卸载：边跑边删目录会把正在写的日志和数据留在半删状态。

        这条同时钉住 `btn_uninstall` 的启用语义与 `_running_per_ui` 的读法 ——
        后者靠 `btn_start` 的文字，正是 A2 那条护栏要保的东西。
        """
        win = self.win
        index = self._tab_index_of("一键启停")
        card = next(c for c in win._tab_cards[index] if hasattr(c, "btn_start"))
        rec = main.RunRecord(key=card.component.key, version="x", home="/h",
                             data_dir="/d", port=9876, console_url="", pid=1,
                             pid_role="server", started_at=0.0, launcher_cmd=[])

        class _RunningSM:
            def status(self, key, comp, records=None):
                return main.LaunchStatus("running", record=rec)

        orig_sm = main.SERVICE_MANAGER
        main.SERVICE_MANAGER = _RunningSM()
        self.addCleanup(setattr, main, "SERVICE_MANAGER", orig_sm)
        card.btn_uninstall.setEnabled(True)
        card._refresh_launch_state_impl()

        self.assertEqual(card.btn_start.text(), "停止")
        self.assertTrue(card._running_per_ui())
        self.assertFalse(card.btn_uninstall.isEnabled(), "运行中卸载按钮必须锁住")
        self.assertTrue(card.btn_uninstall.toolTip(), "锁住了要说明为什么")

    def test_running_tab_gets_a_dot_in_its_title(self):
        """`_mark_running_tabs` 能在 Tab 标题上挂 `●`：同时跑着几个组件时，
        这是"哪一页上有活的"的唯一线索。它读的是 `btn_start` 的文字。"""
        win = self.win
        index = self._tab_index_of("一键启停")
        card = next(c for c in win._tab_cards[index] if hasattr(c, "btn_start"))
        self.addCleanup(win._mark_running_tabs)
        self.addCleanup(card.btn_start.setText, "启动")

        card.btn_start.setText("停止")
        win._mark_running_tabs()
        title = win.tabs.tabText(index)
        self.assertIn("一键启停", title)
        self.assertTrue(title.endswith("●"), f"该页有组件在跑，标题上没有 ●：{title!r}")

        card.btn_start.setText("启动")
        win._mark_running_tabs()
        self.assertFalse(win.tabs.tabText(index).endswith("●"),
                         "都停了还在标题上留着 ●")


if __name__ == "__main__":
    unittest.main(verbosity=2)
