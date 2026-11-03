"""主窗口（从 main.py 抽出，规则 R30）。

仅本地导入基类 QMainWindow 与 Signal；其余 Qt / 业务名一律 `_main.<name>` 晚绑定。
局部 import（如 `from theme import QSS`）保留在方法内，不做前缀。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow


_main = None


def configure(main_module) -> None:
    global _main
    _main = main_module


class MainWindow(QMainWindow):
    @staticmethod
    def current_components() -> Dict[str, "Component"]:
        """只读的组件表。

        2026-10-14 起这只是 `component_registry()` 的一层薄壳：卡片不再通过
        MainWindow 这个**类**去拿组件表（那是"子组件依赖父容器"的方向倒置），
        而是直接问模块级单例。这里保留是为了不破坏既有调用点与打桩点。
        """
        return _main.component_registry()

    def __init__(self, splash: Optional["SplashScreen"] = None) -> None:
        super().__init__()
        self.setWindowTitle(_main.APP_NAME)
        # 设置窗口图标（任务栏、标题栏、Alt+Tab 切换显示）
        # 使用项目内置的 assets/byte-tools.png，缺失时不报错
        _icon_path = Path(__file__).parent / "assets" / "byte-tools.png"
        if _icon_path.exists():
            self.setWindowIcon(_main.QIcon(str(_icon_path)))
        self.resize(1000, 680)
        # 标题栏的宽度预算必须用**真字体**量（`tools/bt_titlebar_budget.py`）：offscreen 平台的
        # 字体度量大 ~1.6 倍（同一句 `v1.2.0` 的 minimumSizeHint 是 92，真实渲染是 54），
        # 拿它当依据会把最小宽抬到根本不需要的位置。2026-10-12 实测量：chip 最长文案
        # `↓ v1.10.0 待更新`(110) + 标题 + 五个按钮 + 三个窗口控制 = 697 像素，1000 这一档余量充足。
        self.setMinimumSize(1000, 560)
        self.setWindowFlags(_main.Qt.FramelessWindowHint | _main.Qt.Window)
        self.setAttribute(_main.Qt.WA_TranslucentBackground, False)

        self.components = _main.build_components()
        # 灌进进程级登记表。全进程只保留这一份组件对象 —— 此前 __init__ 与
        # _adopt_running → current_components() 各建一份，卡片用的和查前置依赖
        # 用的不是同一批，等于白构造一次 88 个 Component（含全部版本表）。
        _main.register_components(self.components)
        self._drag_pos: Optional[_main.QPoint] = None
        self._fetch_workers: List[_main.VersionFetchWorker] = []
        self._fetch_pending: int = 0
        # 关窗标志：置位后不再派发抓取，也不再把抓取结果写回界面。
        # 同时立模块级的 _CLOSING —— 卡片过去靠 getattr(self.window(), "_closing")
        # 沿 Qt 父指针爬回窗口读私有属性，那等于让卡片知道窗口的内部状态。
        self._closing: bool = False
        _main._CLOSING.clear()
        # 视图模式：grid（按宽度自动分列）/ list（恒 1 列）；_load_settings 会按
        # config.json 覆盖它，老配置没有这个键时留在 grid，即"老用户自动获得新默认"。
        self.view_mode: str = "grid"
        # 2026-10-13 启动优化：卡片改为分帧异步构建（splash 显示进度，用户感知"秒开"）。
        # 这里先记录"待建"列表，真控件由 _build_cards_async() 分帧建。列表里元素是
        # (分类名, Component, 该 Tab 的容器) 三元组；建完后 self.cards / _tab_cards
        # 里的占位 None 会被替换成真 ComponentCard。
        self._pending_cards: List[Tuple[str, "Component", _main.QWidget]] = []
        self._splash: Optional["SplashScreen"] = splash
        # 2026-10-14：这里原先取过 _startup_mono（monotonic 时间戳），供日志浮层的
        # "启动后 N 秒内不自动弹"静默期使用。该静默期随自动弹出一起取消，故删除。
        # 本次会话的日志文件标识（落盘用，见 _log_file_path）。在 __init__ 里定一次，
        # 整条运行期不变 —— 同一次运行的日志必须落在同一个文件里，否则"另存为"
        # 和"复制"会给用户一份东一段西一段的碎片。
        self._session_stamp: str = time.strftime("%Y%m%d-%H%M%S")

        self._build_ui()
        self._apply_qss()
        # 2026-10-13 启动优化：没有 splash（测试 / 复用窗口）时同步建卡；
        # 有 splash（生产 main() 路径）时不建，由调用方在 show 后调 _build_cards_async。
        if self._splash is None:
            self._build_cards_async(synchronous=True)
            self._load_settings()       # 建卡后才恢复配置（需要真卡片上的 version_combo）

    def _build_cards_async(self, on_done: Optional[Callable[[], None]] = None,
                            *, synchronous: bool = False) -> None:
        """分帧建卡片：每帧 8 张，splash 显示进度，全部建完回调 on_done。

        为什么必须分帧而不是一次性建：87 张卡的 ComponentCard 构造实测 ~460ms，
        一次性建会让 splash 卡住 0.5 秒不动，用户以为没响应。分帧后 splash 的进度
        文字每帧都在更新，"正在加载组件 32/88…" 是活的。

        synchronous=True 时同步跑完（测试用：构造 MainWindow 后立刻调用，
        不依赖事件循环）。生产路径必须传 on_done 且 synchronous=False（默认）。

        注意：self.cards / self._tab_cards 在建完前是**空列表**，现有遍历代码
        （刷新版本 / 存配置 / 关窗 / 搜索 / 启动停止）都是 `for card in self.cards:`，
        空列表等于无害的空循环，不用改。建完后一次性填充。
        """
        batch = 8
        total = len(self._pending_cards)
        idx = {"i": 0}

        def _step():
            start = idx["i"]
            end = min(start + batch, total)
            if start >= total:
                if on_done:
                    on_done()
                return
            for i in range(start, end):
                cat_name, comp, wrap = self._pending_cards[i]
                card = _main.ComponentCard(comp, self._append_log)
                # 向导型卡片（WSL）把"打开向导"做成信号：卡片不该沿父指针爬回窗口
                # 去调私有方法（bt_install_safety_tests 的依赖方向断言钉着这条）。
                if comp.ui_action == "wsl":
                    card.wsl_requested.connect(self._on_wsl_clicked)
                card.setParent(wrap)
                # 填充到 cards 与 _tab_cards（建完前它们是空列表）
                self.cards.append(card)
                # _tab_cards 按分类找索引：cat_name 在第几个 Tab
                tab_idx = next(
                    (k for k, t in enumerate(self._tab_base_titles)
                     if t.startswith(cat_name + "（")), None)
                if tab_idx is not None:
                    self._tab_cards[tab_idx].append(card)
                if self._splash is not None:
                    self._splash.set_progress(f"正在加载组件 {i + 1}/{total}…")
            idx["i"] = end
            if end < total:
                if synchronous:
                    _step()          # 测试环境：同步递归跑完
                else:
                    _main.QTimer.singleShot(0, _step)
            else:
                if on_done:
                    on_done()

        _step()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = _main.QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)

        outer = _main.QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ------- 自定义标题栏 -------
        self.title_bar = _main.QFrame()
        self.title_bar.setObjectName("titleBar")
        self.title_bar.setFixedHeight(48)
        tb = _main.QHBoxLayout(self.title_bar)
        tb.setContentsMargins(14, 0, 8, 0)
        tb.setSpacing(6)

        title_label = _main.QLabel(_main.APP_NAME)
        title_label.setObjectName("titleText")
        title_label.setFont(_main.QFont("", 12, _main.QFont.Bold))
        # 版本号只活在标题栏这枚 chip 上（底部状态条那份 2026-10-10 去掉了，重复）。
        # 为什么 chip 在左上角而不是右边那排按钮里：右边已经挤了六个按钮，之前加一个
        # 就把「清理残留 PATH」裁掉过（最小宽 1000 那次教训）；挪到软件名后面，
        # 左边只多占一个 chip 的宽度，右边反而松一格。
        title_label.setToolTip(f"{_main.APP_NAME} v{_main.APP_VERSION}")
        tb.addWidget(title_label)

        # 版本号 chip：常驻显示当前版本，点一下按当前状态分派（规则 R12）。
        # 它同时是这四种状态的唯一指示灯：没查过 / 已是最新 / 有新版可下 / 没查到。
        self.btn_version = _main.QPushButton(f"v{_main.APP_VERSION}")
        self.btn_version.setObjectName("versionChip")
        self.btn_version.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_version.setToolTip(
            f"当前版本 v{_main.APP_VERSION}\n点击检查有没有新版本"
            "（启动后一天最多自动查一次）")
        self.btn_version.clicked.connect(self._on_version_clicked)
        self._chip_state = "idle"
        self._chip_latest = ""
        self._chip_folder: Optional[Path] = None
        self._chip_pct: Optional[int] = None
        self._update_res: dict = {}
        tb.addWidget(self.btn_version)
        tb.addStretch(1)

        # GitHub 图标
        self.btn_github = _main.QPushButton("★ GitHub")
        self.btn_github.setObjectName("iconBtn")
        self.btn_github.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_github.setToolTip("获取最新版本")
        self.btn_github.clicked.connect(
            lambda: _main.QDesktopServices.openUrl(_main.QUrl(_main.GITHUB_URL))
        )
        tb.addWidget(self.btn_github)

        # 刷新版本列表按钮
        self.btn_refresh = _main.QPushButton("⟳ 刷新版本")
        self.btn_refresh.setObjectName("iconBtn")
        self.btn_refresh.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_refresh.setToolTip("重新从官网抓取所有组件的可用版本列表")
        # clicked 会带 checked=False 当第一个实参：裸 connect 到 _start_fetch_versions
        # 就等于 force=False，用户点刷新只会读缓存 —— 必须显式包一层传 force=True。
        self.btn_refresh.clicked.connect(
            lambda _checked=False: self._start_fetch_versions(force=True))
        tb.addWidget(self.btn_refresh)

        # 清理残留 PATH 按钮
        self.btn_cleanup_path = _main.QPushButton("🧹 清理残留 PATH")
        self.btn_cleanup_path.setObjectName("iconBtn")
        self.btn_cleanup_path.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_cleanup_path.setToolTip(
            "删除 PATH 中指向本工具安装目录、但目录已经不存在的死条目\n"
            "（手工删过安装目录时用到；其他程序的 PATH 条目不会改动）"
        )
        self.btn_cleanup_path.clicked.connect(self._on_cleanup_path_clicked)
        tb.addWidget(self.btn_cleanup_path)

        # 2026-10-21：WSL 曾经在标题栏有一个「🐧 WSL」快捷按钮，用户要求删掉 ——
        # 「开发环境」里已经有同名卡片（点「安装向导」），两处入口只重复占宽。
        # `_on_wsl_clicked` 保留：卡片的 wsl_requested 信号仍然接到它。

        # 2026-10-14 按用户要求移除标题栏的两个按钮：
        #   「🖥 开验证终端」「🩺 导出诊断」
        # 原因：标题栏只留"每天都会用"的动作。这两个都属于"出问题时才用"，
        # 常年占着标题栏最宽的两块地方却不点（实测这一行真实字体需 802 像素，
        # 它们占了将近三分之一）。对应的能力没有丢：
        #   · 导出诊断 —— 日志浮层里仍可通过「另存为」产出同样内容
        #     （_save_log_to_file 把本次会话日志写出，配合落盘的 config.json
        #     与日志已经覆盖了诊断报告的主要部分）
        #   · 开验证终端 —— 环境变量是否真的生效，用户用系统自己的"新开一个
        #     PowerShell 窗口"即可验证；本工具里那条 1~2 行的自查提示
        #     （_refresh_logs 里的复制命令）仍然保留
        # 处理函数一并删除，避免留下无人调用的死代码。

        # 标题栏按钮定宽：空间不足时宁可让窗口最小宽去兜（见上面 setMinimumSize），
        # 也不许把按钮压扁裁字。chip 也在名单里：它的文字按状态变
        # （`v1.2.0` → `↓ v1.2.1 待更新`），不定宽的话一旦某档宽度紧张，布局会先压它 ——
        # 那状态字就等于没写。真实字体下这一行共需约 660 像素
        # （tools/bt_titlebar_budget.py 实测），1000 这一档余量充足，
        # 定宽只是兜底。**这个数字只能用真实字体量**：offscreen 没有中文回退字体，
        # 度量虚高约 1.6 倍，拿它判断会误判成"要裁字"然后白抬窗口最小宽。
        #
        # ⚠ 这个循环必须放在**所有**标题栏按钮建完之后（下面 btn_donate 之后）。
        # 它原先在 btn_donate 创建之前，于是捐赠按钮一直是唯一漏网的：空间紧张时
        # 被压扁的比例会先落到它身上。加按钮时务必检查自己在不在这个名单里。
        for _btn in (self.btn_version, self.btn_github, self.btn_refresh,
                     self.btn_cleanup_path):
            _btn.setSizePolicy(_main.QSizePolicy.Fixed, _btn.sizePolicy().verticalPolicy())

        # 捐赠图标（不在 README 中提及）
        self.btn_donate = _main.QPushButton("♥")
        self.btn_donate.setObjectName("donateBtn")
        self.btn_donate.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_donate.setToolTip("支持作者")
        self.btn_donate.clicked.connect(self._on_donate_clicked)
        tb.addWidget(self.btn_donate)
        # 上面那个定宽循环因为位置关系漏了它，在这里补上（见上面那段注释）
        self.btn_donate.setSizePolicy(_main.QSizePolicy.Fixed,
                                      self.btn_donate.sizePolicy().verticalPolicy())

        # 窗口控制按钮
        self.btn_min = _main.QPushButton("—")
        self.btn_min.setObjectName("ctrlBtn")
        self.btn_min.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_min.clicked.connect(self.showMinimized)
        tb.addWidget(self.btn_min)

        self.btn_max = _main.QPushButton("▢")
        self.btn_max.setObjectName("ctrlBtn")
        self.btn_max.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_max.clicked.connect(self._toggle_max)
        tb.addWidget(self.btn_max)

        self.btn_close = _main.QPushButton("×")
        self.btn_close.setObjectName("closeBtn")
        self.btn_close.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_close.clicked.connect(self.close)
        tb.addWidget(self.btn_close)

        outer.addWidget(self.title_bar)

        # ------- 组件搜索条（在 Tab 之上，切 Tab 不会丢输入框） -------
        self.search_bar = _main.QFrame()
        self.search_bar.setObjectName("searchBar")
        sb = _main.QHBoxLayout(self.search_bar)
        sb.setContentsMargins(18, 12, 18, 10)
        sb.setSpacing(10)

        # 胶囊外壳：放大镜与输入框同属一个白色圆角块，聚焦时整条高亮，
        # 而不是只给输入框描一圈边（原先那种细边框小方框显得零碎）。
        self.search_shell = _main.QFrame()
        self.search_shell.setObjectName("searchShell")
        self.search_shell.setProperty("focused", "false")
        shell = _main.QHBoxLayout(self.search_shell)
        shell.setContentsMargins(12, 0, 8, 0)
        shell.setSpacing(8)

        self.search_icon = _main.QLabel()
        self.search_icon.setObjectName("searchIcon")
        self.search_icon.setPixmap(self._make_search_icon().pixmap(16, 16))
        shell.addWidget(self.search_icon)

        self.search_box = _main.QLineEdit()
        self.search_box.setObjectName("compSearch")
        self.search_box.setPlaceholderText("搜索组件名称…")
        # 内置清空按钮在不同平台上图标差异大、颜色偏淡，这里自绘一个统一风格的 ×
        self.search_box.setClearButtonEnabled(False)
        self._clear_action = self.search_box.addAction(
            self._make_clear_icon(), _main.QLineEdit.TrailingPosition
        )
        self._clear_action.setToolTip("清空搜索")
        self._clear_action.setVisible(False)
        self._clear_action.triggered.connect(self.search_box.clear)
        self.search_box.textChanged.connect(self._sync_clear_action)
        self.search_box.textChanged.connect(self._apply_search)
        # 焦点变化要联动外壳高亮，QSS 的 :focus 影响不到父级，用事件过滤器转发
        self.search_box.installEventFilter(self)
        # 占位文字默认偏深，调浅一点更接近现代输入框的观感
        _pal = self.search_box.palette()
        _pal.setColor(_main.QPalette.PlaceholderText, _main.QColor("#9aabbd"))
        self.search_box.setPalette(_pal)
        shell.addWidget(self.search_box, 1)

        sb.addWidget(self.search_shell)

        self.search_hint = _main.QLabel("")
        self.search_hint.setObjectName("searchHint")
        sb.addWidget(self.search_hint)

        # 视图切换与日志开关放在搜索条右侧的空白处，**不放标题栏**：标题栏已有
        # 5 个按钮 + 3 个窗口控制，实测需要 ~992px，窗口才 1000 宽，再加必然
        # 把已有的按钮压到裁字。
        self.btn_view_mode = _main.QPushButton("▦ 网格")
        self.btn_view_mode.setObjectName("toolBtn")
        self.btn_view_mode.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_view_mode.setToolTip(
            "网格：按窗口宽度自动分成 2 列 / 3 列；列表：恒 1 列（卡片内容不变）")
        self.btn_view_mode.clicked.connect(self._on_view_mode_clicked)
        sb.addWidget(self.btn_view_mode)

        self.btn_log = _main.QPushButton("📋 日志")
        self.btn_log.setObjectName("toolBtn")
        self.btn_log.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_log.setToolTip("展开/收起运行日志（浮层，盖在卡片上，不挤压网格）")
        self.btn_log.clicked.connect(self._on_log_button_clicked)
        sb.addWidget(self.btn_log)

        sb.addStretch(1)
        outer.addWidget(self.search_bar)

        # ------- 主体：卡片区（吃满中部）+ 日志浮层 -------
        # 日志原先和卡片区按 3:2 分在同一个 QSplitter 里，展开/收起都会挤压网格。
        # 现在卡片区独占中部，日志改成浮在它上面的浮层：不占布局空间，于是
        # 列数与行数只由窗口宽度决定，开关日志不会让格子忽大忽小。

        # 卡片区域：按 COMPONENT_CATEGORIES 分四个 Tab，每个 Tab 一条独立滚动栏。
        # self.cards 仍是全量平铺列表——刷新版本 / 存取配置 / 关窗等探测都靠它遍历。
        self.cards: List[_main.ComponentCard] = []
        self._tab_cards: List[List[_main.ComponentCard]] = []
        # `_tab_layouts[i]` 的语义从"直接装卡片"改成"装行的外层竖向布局"：
        # 行本身是一个 QWidget，行里的 QHBoxLayout 才装格子。
        # 用行容器而不是 QGridLayout，是因为 _restore_browse /
        # _build_unified / _relayout_results 全靠 QBoxLayout 的 indexOf / insertWidget
        # / 末尾 stretch —— 结果面板的"行"要能插进指定位置，QGridLayout 做不到。
        self._tab_layouts: list = []
        # `_tab_rows[key]`：Tab 用 0..N-1 的序号，统一结果面板用 RESULTS_KEY。
        # 两者存的都是"行控件"（结果面板里一行就是某个分类下的一截卡片）。
        self._tab_rows: dict = {}
        self._tab_wraps: List[_main.QWidget] = []
        # Tab 标题的"干净"形态（分类名 + 组件数）。运行标记 `●` 是叠在它上面的，
        # 搜索/退出搜索会重设标题，所以必须留着底稿，不能靠 tabText() 反推。
        self._tab_base_titles: List[str] = []
        try:
            _main._path_index()      # 建卡前一次性批扫 PATH（R18）
        except Exception:
            pass
        self.tabs = _main.QTabWidget()
        self.tabs.setObjectName("compTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(_main.QTabWidget.North)   # 顶部横向，跨平台显式锁定
        for cat_name, comps in _main.group_components(self.components).items():
            scroll = _main.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setObjectName("cardsScroll")
            cards_wrap = _main.QWidget()
            cards_wrap.setObjectName("cardsWrap")
            cards_layout = _main.CardColumnLayout(cards_wrap)
            cards_layout.setContentsMargins(18, 18, 18, 18)
            cards_layout.setSpacing(_main.CARD_ROW_SPACING)
            tab_cards: List[_main.ComponentCard] = []
            # 2026-10-13 启动优化：不在构造期建卡片控件，只记录占位（comp 引用）。
            # 真卡片由 _build_cards_async() 分帧在 QTimer 回调里建（每帧 8 张，
            # splash 显示进度，用户感知"秒开"）。cards 列表与 _tab_cards 在全部建完前
            # 是**空列表**，建完后一次性填充 —— 现有遍历代码（刷新版本 / 存配置 / 关窗）
            # 都是 `for card in self.cards:`，空列表等于无害的空循环，不用改。
            for comp in comps:
                self._pending_cards.append((cat_name, comp, cards_wrap))
            scroll.setWidget(cards_wrap)
            base_title = f"{cat_name}（{len(comps)}）"
            self.tabs.addTab(scroll, base_title)
            self._tab_base_titles.append(base_title)
            self._tab_cards.append(tab_cards)
            self._tab_layouts.append(cards_layout)
            self._tab_wraps.append(cards_wrap)
            self._tab_rows[len(self._tab_cards) - 1] = []

        # 统一搜索结果面板：搜索时收起四个 Tab，把所有命中的组件按分类归并到
        # 同一个滚动列表里（带分类小标题），一眼看全、不用切页——这就是「全组件搜索」。
        self.results_area = _main.QScrollArea()
        self.results_area.setObjectName("resultsArea")
        self.results_area.setWidgetResizable(True)
        self.results_content = _main.QWidget()
        self.results_content.setObjectName("resultsContent")
        # 结果面板用与 Tab 同一个 CardColumnLayout：命中卡片也住进 cardRow 行控件，
        # 格子宽度就跟浏览时一模一样（不再是"一张卡占满 954px"的宽条）。
        self.results_layout = _main.CardColumnLayout(self.results_content)
        self.results_layout.setContentsMargins(18, 18, 18, 18)
        self.results_layout.setSpacing(6)
        self.results_area.setWidget(self.results_content)
        # 结果面板的结构是「分类小标题（整行）+ 该分类的若干 cardRow 行」。登记进
        # _tab_rows 的是**真实的行控件**，与四个 Tab 同构，"命中数 < 列数时有没有
        # 空洞"因此有统一判据。`_result_sections` 记着「标题 → 该分类命中卡片」，
        # 重排时靠它在各自标题下面重建行（标题本身不重建，否则会丢）。
        self._tab_rows[_main.RESULTS_KEY] = []
        self._result_sections: list = []

        # 浏览模式用 Tab，搜索模式用统一结果面板，二者互斥地放进一个栈
        self.top_stack = _main.QStackedWidget()
        self.top_stack.setObjectName("topStack")
        self.top_stack.addWidget(self.tabs)           # index 0：浏览
        self.top_stack.addWidget(self.results_area)   # index 1：搜索结果

        self.body = _main.QWidget()
        self.body.setObjectName("bodyArea")
        body_lay = _main.QVBoxLayout(self.body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        body_lay.addWidget(self.top_stack)
        outer.addWidget(self.body, stretch=1)

        # 日志浮层：与卡片区同一个父级，靠 raise_() 叠在上面，几何随 resize 跟随。
        # 它不在 body 的布局里，所以 show/hide 都不会让卡片区尺寸变化 ——
        # 这是"展开日志不重排网格"这条承诺的实现基础。
        self.log_overlay = _main.QWidget(self.body)
        self.log_overlay.setObjectName("logOverlay")
        overlay_lay = _main.QVBoxLayout(self.log_overlay)
        overlay_lay.setContentsMargins(18, 8, 18, 14)
        overlay_lay.setSpacing(6)
        overlay_head = _main.QHBoxLayout()
        log_title = _main.QLabel("运行日志")
        log_title.setStyleSheet("color:#e6e9ef;font-weight:600;")
        overlay_head.addWidget(log_title)
        overlay_head.addStretch(1)
        # 「复制日志」：用户报障时最需要的是把原文贴出来。手打上百行中文日志
        # 不现实，截图又看不清时间戳 —— 落盘之后一键复制是闭环的最后一环。
        self.btn_log_copy = _main.QPushButton("复制")
        self.btn_log_copy.setObjectName("overlayCopyBtn")
        self.btn_log_copy.setFixedSize(52, 26)
        self.btn_log_copy.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_log_copy.setToolTip("把本次会话的全部日志复制到剪贴板（便于粘贴到反馈里）")
        self.btn_log_copy.clicked.connect(self._copy_log_to_clipboard)
        overlay_head.addWidget(self.btn_log_copy)
        # 「另存为」：落盘文件按会话切，用户想留档或直接发给别人的时候用。
        self.btn_log_save = _main.QPushButton("导出诊断")
        self.btn_log_save.setObjectName("overlayCopyBtn")
        self.btn_log_save.setFixedSize(70, 26)
        self.btn_log_save.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_log_save.setToolTip(
            "把「诊断报告 + 本次会话日志」另存为一个文本文件\n"
            "（报告说明环境状态，日志说明刚才发生了什么；反馈时附上它）")
        self.btn_log_save.clicked.connect(self._save_log_to_file)
        overlay_head.addWidget(self.btn_log_save)
        self.btn_log_close = _main.QPushButton("×")
        self.btn_log_close.setObjectName("overlayCloseBtn")
        self.btn_log_close.setFixedSize(26, 26)
        self.btn_log_close.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_log_close.setToolTip("收起日志浮层")
        self.btn_log_close.clicked.connect(self._close_log_by_user)
        overlay_head.addWidget(self.btn_log_close)
        overlay_lay.addLayout(overlay_head)
        self.log_view = _main.QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("logView")
        overlay_lay.addWidget(self.log_view)
        self.log_overlay.hide()

        # 底部状态条：系统 / **可点的工作目录** / 组件数。
        # 数按 `self.cards`（界面可见）算，不是 `self.components`：erlang 是 hidden
        # 组件，只当 rabbitmq 的前置依赖，用户在四个 Tab 里都找不到它 —— 以前这里写 27、
        # 搜索框右边写 /26，同一屏两个数字互相矛盾（2026-10-10 用户第一条质疑）。
        # 同一轮用户又嫌句子长："26 就显示 26"，于是去向说明和版本号都从底部拿掉
        # （版本号只剩标题栏 chip 一处，见上面；隐藏组件的去向归文档 R5.3 交代）。
        self.status_bar = _main.QLabel(
            f"系统：{_main.CURRENT_OS} ({_main.MACHINE})   工作目录："
            f'<a href="dir://{_main.html_escape(Path(_main.CONFIG_DIR).as_posix())}" '
            f'style="color:#8fa3b8;text-decoration:underline">'
            f"{_main.html_escape(str(_main.CONFIG_DIR))}</a>   "
            f"组件：{sum(1 for c in self.components if c.key != 'erlang')}"
        )
        self.status_bar.setObjectName("statusBar")
        self.status_bar.setTextFormat(_main.Qt.RichText)
        # 不许开 setOpenExternalLinks(True)：那会把 dir:// 丢给系统的"未知协议"处理，
        # 用户点一下什么也不会发生。链接自己接，见 _on_status_link。
        self.status_bar.setOpenExternalLinks(False)
        self.status_bar.linkActivated.connect(self._on_status_link)
        outer.addWidget(self.status_bar)

        # 日志浮层的未读计数。2026-10-14 起浮层不再自动弹开/自动收起
        # （原 _log_auto_hide 定时器与 _log_user_open 标记已删除），
        # 只剩这一个计数：warn/error 在浮层关着时累加，显示在「📋 日志 (N)」上。
        self._log_unread = 0

        # 列数缓存：resizeEvent 只在它变化时才重建行（见 resizeEvent 里的说明）。
        # 2026-10-13：构造期**不重排** —— 此时 QScrollArea 的 viewport 宽度还没就绪，
        # `grid_columns_for` 会算出 1 列，排完 showEvent 又得拆掉重排（实测 87 卡 × 8 次
        # relayout ≈ 845ms + 794ms）。只记录"当前认为的列数"（可能是错的 1 列），
        # 让 showEvent 按"列数不同才重排"的守卫自然触发那**唯一一次**真重排。
        # 守卫逻辑见 showEvent：构造期记的 1 列 ≠ show 期算的 3 列 ⇒ 强制重排；
        # 若构造期侥幸算对（窗口已显示时构造），则跳过 —— 两种路径都不会漏排。
        self._last_columns = self._card_columns()
        self._refresh_view_button()
        self._refresh_log_button()

    # ------------------------------------------------------------------
    # 卡片网格：分列、重排
    # ------------------------------------------------------------------
    def _card_columns(self) -> int:
        """当前卡片区该排几列：列表模式恒 1 列，网格模式按可用净宽算。

        宽度**不能**取"当前 Tab 的 viewport"——有竖滚动条的页（10 张卡要滚）
        比没有的页窄十几像素，正好骑在列数边界上：切一次 Tab 列数就变，
        再叠加"切 Tab 不触发重排"，同一页就会出现两种列数混排、末行溢出
        （真机 2026-10-08 用户 125% 缩放截图实测）。改用 tabs 本身的宽度
        （四个 Tab 恒相同）减去固定开销：左右边距 36 + 竖滚动条 10 预留。
        切 Tab、滚动条出现消失都不影响列数。
        """
        if getattr(self, "view_mode", "grid") == "list":
            return 1
        tabs = getattr(self, "tabs", None)
        if tabs is None:
            return 1
        return _main.grid_columns_for(tabs.width() - 36 - 10, _main.MIN_CARD_WIDTH_PX)

    def relayout_cards(self, container_key) -> None:
        """把一个容器里的卡片按当前列数重排成"行"。

        入参 container_key: int → 第几个 Tab；RESULTS_KEY → 统一搜索结果面板。

        重排只排"没被隐藏"的卡片（搜索命中的反面），所以命中数少于列数时
        不会留下空洞；隐藏的卡片被收回到容器宿主上，不占任何格子。
        """
        if container_key == _main.RESULTS_KEY:
            self._relayout_results()
            return
        idx = int(container_key)
        layout = self._tab_layouts[idx]
        root = self._tab_wraps[idx]
        cards = self._tab_cards[idx]
        # 只排"此刻真的住在这个 Tab 里"的卡片：搜索时命中的卡片已搬到结果面板，
        # 不判归属就会把它们从结果面板里拽回 Tab，搜索结果当场散架。
        own = [c for c in cards if root.isAncestorOf(c)]
        self._tab_rows[idx] = self._fill_rows(layout, root, own, self._card_columns())

    def _relayout_results(self) -> None:
        """统一结果面板：保留分类小标题，在各自标题下面重建卡片行。

        行用 `_make_layout_rows` 造的**无宿主 QHBoxLayout**（2026-10-15，见 R2.6）——
        网格、等宽、占位格的算法与浏览 Tab 完全一致，只是行不再是控件。
        **列数恒取浏览列数**（2026-10-10 用户改的口径：「搜索组件时如果只有一个组件
        也要以网格显示，现在变成列表了」）：命中 1 个也是 3 个格子里占 1 个，
        另外两格补透明占位控件 —— 少补一格，`addWidget(card, 1)` 就会把那张卡拉成
        整行宽，看上去就从"网格"退化成"列表"。以前这里是 `min(命中数, 浏览列数)`，
        命中 1 个就 1 列，正是用户报的那个现象。
        """
        sections = getattr(self, "_result_sections", None) or []
        cards = [c for _, group in sections for c in group]
        if not cards:
            self._tab_rows[_main.RESULTS_KEY] = []
            self.results_layout.row_widgets = []
            return
        columns = max(1, self._card_columns())
        # 分块必须在搬家**之前**算完：setParent 会把卡片显式隐藏，先搬再算就排空
        chunks_per_group = [_main.chunk_visible(group, columns) for _, group in sections]
        # 卡片先收回到宿主，否则下面销毁旧行会把还住在里面的卡片一起带走。
        # ⚠ **父级已经是宿主时一个字都别动**：`setParent(当前父级)` 实测仍约
        # 5 ms/张（Qt 照样重跑 inheritStyle → QSS polish），115 张就是 ~0.6 s。
        # 行改成无宿主布局之后卡片本来就一直挂在宿主上，这个判断直接省掉那 0.6 s。
        for card in cards:
            if card.parent() is not self.results_content:
                card.setParent(self.results_content)
        # 只摘行、留标题：结果面板是"标题 + 行"交错的结构，全清会把标题一起删掉
        self._drop_rows(self.results_layout, only_rows=True)
        rows: list = []
        for (header, _group), chunks in zip(sections, chunks_per_group):
            pos = self.results_layout.indexOf(header)
            if pos < 0:
                continue
            for k, row in enumerate(self._make_layout_rows(self.results_content, chunks,
                                                           pad_to=columns)):
                self.results_layout.insertLayout(pos + 1 + k, row)
                rows.append(row)
        self.results_layout.row_widgets = rows
        self._tab_rows[_main.RESULTS_KEY] = rows

    def _fill_rows(self, layout, root, cards, columns) -> list:
        """销毁旧行、按 columns 重建行，返回新建的行控件列表。

        两步都不能省：先把这个容器的卡片全部收回到宿主，否则销毁行控件时
        会把还住在里面的卡片一起带走；收回之后 addWidget 的顺序才等于
        子控件顺序（findChildren 读出来的行内顺序才是对的）。
        """
        # 分块必须在搬家**之前**算完：setParent 会把控件显式隐藏（isHidden 变 True），
        # 先搬再算就一张可见卡片都不剩，整页排空。
        chunks = _main.chunk_visible(cards, columns)
        for card in cards:
            if root.isAncestorOf(card):
                card.setParent(root)
        self._drop_rows(layout)
        layout.row_widgets = []
        # pad_to 必须给：半行不补占位的话，QHBoxLayout 的 addWidget(card, 1) 会把
        # 末行的卡片**拉伸占满整行** —— 「其它软件」2 张各半行、「服务端组件」的 Pulsar
        # 独占一行，跟满行格子的 309px 完全不同宽（真机 2026-10-08 用户截图实测）。
        rows = self._make_rows(root, chunks, pad_to=columns)
        for row in rows:
            layout.addWidget(row)
            layout.row_widgets.append(row)
        layout.addStretch(1)
        return rows

    def _drop_rows(self, layout, only_rows: bool = False) -> None:
        """摘掉 layout 里的条目并销毁（`_fill_rows` 与结果面板重排共用）。

        入参 only_rows: bool  True → 只摘「行」：Tab 里是 objectName 为 "cardRow"
             的**行控件**，统一结果面板里是**无宿主的 QHBoxLayout**（见 R2.6）。
             分类小标题与末尾 stretch 原样留下。
        """
        i = 0
        while i < layout.count():
            item = layout.itemAt(i)
            w = item.widget()
            sub = item.layout()
            is_row = (w is not None and w.objectName() == "cardRow") or sub is not None
            if only_rows and not is_row:
                i += 1
                continue
            layout.takeAt(i)
            if sub is not None:
                # 无宿主行布局：把里面的条目逐个摘出来再丢掉空布局。
                # 卡片**留在宿主里不动**（父级不变正是这么省下来的），由调用方
                # 决定是送回 Tab 还是重新排进新行；占位格是临时控件，随行一起销毁。
                while sub.count():
                    inner = sub.takeAt(0)
                    filler = inner.widget()
                    if filler is not None and not any(filler is c for c in self.cards):
                        filler.hide()
                        filler.deleteLater()
                sub.deleteLater()
                continue
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            else:
                sp = item.spacerItem()
                if sp is not None:
                    del sp

    def _make_rows(self, root, chunks, pad_to: int = 0) -> list:
        """按 chunks（每个元素是一行的卡片序列）造出 cardRow 行控件。

        入参 pad_to: int  >0 时，不足该列数的行末尾补一个等比占位控件，让卡片
             仍然只占"一个格子"的宽度。搜索结果靠它保证「命中 5 个 → 3 列」时
             第二行那 2 张卡跟第一行 3 张卡一样宽 —— 否则 addWidget(card, 1) 会把
             半行的卡片拉伸到占满整行，宽度又跟浏览格子对不上了（真机实测踩中）。

        只负责"造行"，**不碰外层布局** —— 行插在哪儿由调用方决定：Tab 是
        顺序追加，结果面板要插在各自的分类小标题后面。
        """
        rows: list = []
        for row_cards in chunks:
            row = _main.QWidget(root)
            row.setObjectName("cardRow")
            row_lay = _main.QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(_main.CARD_ROW_SPACING)
            for card in row_cards:
                row_lay.addWidget(card, 1)      # 同一行的格子等分宽度
                # setParent 会把控件**显式隐藏**（实测 isHidden 变 True），搬一次家
                # 就把卡片弄没了，所以进格子后必须再放出来一次。
                card.show()
            if pad_to and len(row_cards) < pad_to:
                # 占位控件必须**可见**才会参与布局（隐藏的控件会被布局忽略），
                # 但它没有任何内容与背景，画出来是透明的；对鼠标也透明，不挡点击。
                # 一格补一个（而不是一个占位控顶 n 格）：间距数才能与满行一致，
                # 格子宽度才会跟浏览时分毫不差（313 vs 309 的偏差就是这么来的）。
                for _ in range(pad_to - len(row_cards)):
                    filler = _main.QWidget(row)
                    filler.setObjectName("cardRowFiller")
                    filler.setAttribute(_main.Qt.WA_TransparentForMouseEvents)
                    row_lay.addWidget(filler, 1)
                    filler.show()
            # 行控件是新建的，加到布局里不会自动显示（实测 isVisible 仍为 False），
            # 必须显式 show 一次，否则重排之后整页卡片会"消失"；
            # show() 会顺着子控件往下走，把行里的卡片一起带出来。
            row.show()
            rows.append(row)
        return rows

    def _make_layout_rows(self, host, chunks, pad_to: int = 0) -> list:
        """统一结果面板专用：造**无宿主的 QHBoxLayout** 当行（2026-10-15，见 R2.6）。

        为什么不沿用 `_make_rows` 的 `QWidget#cardRow`：`QLayout::addChildWidget`
        是把控件 reparent 到**布局的 `parentWidget()`** —— 行是个 QWidget 时，
        卡片的父级就变成那个新建的行，而父级一变 Qt 就得对该卡**整棵子树**重跑一遍
        样式解析（实测约 5 ms/张，115 张就是 0.6 s）。无宿主布局的 `parentWidget()`
        正好是外层容器本身，于是卡片**父级不变**，整条 QSS polish 路径被跳过。
        实测同一份 115 张卡：行控件 1001 ms → 无宿主布局 **3.5 ms**。

        别把 Tab 也换过来：Tab 的行是 `QWidget`，`_reveal_running_tabs` 那一族逻辑
        与一批像素断言都按 `findChildren` / `objectName()=="cardRow"` 认行，
        而搜索结果面板是唯一"每次按键都要整页重排"的地方 —— 收益只在这里，
        风险也只摊在这里。

        入参 host: QWidget  占位格控件的挂载点（行布局自己没有宿主，子控件得有）。
        """
        rows: list = []
        for row_cards in chunks:
            row_lay = _main.QHBoxLayout()
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(_main.CARD_ROW_SPACING)
            for card in row_cards:
                row_lay.addWidget(card, 1)     # 同一行的格子等分宽度
                # 卡片从 Tab 那边搬过来时 setParent 会把它显式隐藏，进格子后放出来一次；
                # 本来就在结果面板里的卡片（连续改搜索词）这一步是无副作用的。
                card.show()
            if pad_to and len(row_cards) < pad_to:
                for _ in range(pad_to - len(row_cards)):
                    filler = _main.QWidget(host)
                    filler.setObjectName("cardRowFiller")
                    filler.setAttribute(_main.Qt.WA_TransparentForMouseEvents)
                    row_lay.addWidget(filler, 1)
                    filler.show()
            rows.append(row_lay)
        return rows

    def resizeEvent(self, e) -> None:  # noqa: N802  Qt 规定的驼峰签名
        super().resizeEvent(e)
        # resize 是"每变一个像素一次"的事件，每次都重建行控件会把拖动窗口卡死，
        # 所以只在列数真的变化时才重排。
        columns = self._card_columns()
        if columns != self._last_columns:
            self._last_columns = columns
            for idx in range(len(self._tab_cards)):
                self.relayout_cards(idx)
            # 搜索中窗口变宽/变窄，结果面板的格子也要跟着变，否则它的卡片宽度
            # 会跟浏览 Tab 对不上（正是"搜索结果卡更宽"那条反馈的根源）。
            if self.top_stack.currentIndex() == 1:
                self.relayout_cards(_main.RESULTS_KEY)
        self._position_log_overlay()

    def showEvent(self, e) -> None:  # noqa: N802  Qt 规定的驼峰签名
        super().showEvent(e)
        # 首次显示时必须强制重排一次：_build_ui 末尾那次 relayout 跑在窗口 show
        # 之前，QScrollArea 的 viewport 宽度还没就绪，grid_columns_for 会算出 1 列
        # —— 卡片全排成"一行一张"。而窗口尺寸在构造期就已 resize 到 1000×680，
        # show() 不改变尺寸就**不会触发 resizeEvent**，这个错排没有任何机会被纠正，
        # 用户只有手动拖一下窗口大小才能看到网格（真机 2026-10-08 实测踩中）。
        # resizeEvent 那套"列数变了才重排"的防抖在这里反而是障碍，所以直接重排。
        # 2026-10-13 补一条对等防抖：列数与构造期相同就跳过 —— 相等时重排的
        # 结果必然与已排好的行一模一样（列数唯一决定行结构），拆掉重建纯属白烧
        # 87 次 setParent（cProfile 实测一次全量重排 ~0.4s，offscreen 下 show 期
        # 曾连排两次 1 列 + 一次 3 列）。列数不同（构造期错算 1 列、此刻 viewport
        # 就绪算出 3 列）则照旧强制重排，2026-10-08 那条修复不受影响。
        if not getattr(self, "_first_show_done", False):
            self._first_show_done = True
            columns = self._card_columns()
            if columns != self._last_columns:
                self._last_columns = columns
                for idx in range(len(self._tab_cards)):
                    self.relayout_cards(idx)
            self._position_log_overlay()

    # ------------------------------------------------------------------
    # 日志浮层
    # ------------------------------------------------------------------
    def _position_log_overlay(self) -> None:
        """浮层贴在卡片区底部，高度取中部高度的 45%（夹在 160~300px）。"""
        host = getattr(self, "body", None)
        overlay = getattr(self, "log_overlay", None)
        if host is None or overlay is None:
            return
        height = min(300, max(160, int(host.height() * 0.45)))
        overlay.setGeometry(0, host.height() - height, host.width(), height)

    def _start_update_check(self, auto: bool) -> None:
        """查一次更新。auto=True 是启动后的静默检查，False 是用户点了版本号。"""
        worker = getattr(self, "_update_worker", None)
        if _main._qthread_state(worker) == "running":
            if not auto:
                self._append_log("info", "已经在检查更新了，稍等一下。")
            return
        if auto and not _main.update_check_due(time.time(), _main.load_update_state()):
            return                     # 24 小时内查过：一个字都不说
        if not auto:
            self._append_log("info", f"检查更新中…（当前 v{_main.APP_VERSION}）")
            self._set_chip_state("checking")
        self._update_worker = _main.UpdateCheckWorker(parent=self)
        self._update_worker.done.connect(
            lambda res, a=auto: self._apply_update_result(res, auto=a))
        self._update_worker.finished.connect(self._update_worker.deleteLater)
        self._update_worker.start()

    def _apply_update_result(self, res, auto: bool) -> None:
        """把检查结果落到界面与日志。

        **自动检查失败时不写日志**（用户明确要求"连不上别弹窗"），但 chip 仍要变灰带 `?`：
        这颗控件现在兼任状态灯，"没查到"若继续显示成普通版本号，就等于说"没有新版"，
        而它其实什么都不知道。手动点版本号时另外再回答一句，否则像按钮坏了。
        """
        if not isinstance(res, dict):
            res = {}
        if not res.get("ok"):
            reason = str(res.get("error") or "未知原因")
            self._set_chip_state("error", reason=reason)
            if auto and res.get("silent"):
                return
            self._append_log("info",
                      f"没检查成更新：{reason}"
                      "（不影响软件本身使用，稍后可以再点一次版本号）")
            return
        latest = res.get("latest") or {}
        version = str(latest.get("version") or "")
        _main.save_update_check(last_check_ts=time.time())
        if not res.get("newer"):
            self._update_res = {}
            self._set_chip_state("latest")
            if not auto:
                self._append_log("ok", f"已经是最新版本 v{_main.APP_VERSION}。")
            return
        self._update_res = res
        self._set_chip_state("update", new_version=version)
        # 只在这个版本**首次**告知时写一遍（下面 save_update_check 会把 notified 置位，
        # 所以判定必须取一次存起来，不能写完通知再判第二次 —— 那样恒为 False）
        first_time = _main.update_notify_due(_main.load_update_state(), version)
        if first_time:
            _main.save_update_check(notified=version)
            self._append_log("ok", f"发现新版本 v{version}（当前 v{_main.APP_VERSION}）："
                            f"{latest.get('page_url') or _main.GITHUB_URL}"
                            "（点左上角那颗 ↓ 直接下载到默认目录）")
            # 有 release notes 就把要点写进日志。用户决定要不要升级，看的就是"改了什么"，
            # 而不是"有个新版存在"——原先整个 body 被解析层丢掉，这里是它第一次
            # 真正到达用户眼前。
            notes = _main._release_notes_digest(str(latest.get("notes") or ""))
            if notes:
                self._append_log("info", "新版本更新内容：" + notes)
        if not auto and not isinstance(res.get("asset"), dict):
            # 没有本平台可下的产物时才弹窗；有产物的话点 chip 就下，不该多问一句。
            self._notify_update_without_asset(res)

    def _set_chip_state(self, state: str, *, new_version: str = "",
                        pct=None, reason: str = "", dest=None) -> None:
        """版本号 chip 的文字 / 配色 / tooltip 只有这一个出口。

        以前 setText + setProperty + unpolish 三行散在结果处理里，只有"发现新版"
        一种状态有地方表达；现在四种状态都要有确定的样子，收口到一处才改得动。
        配色挂在**动态属性**上（objectName 不许改，改了按名字找它的代码与用例就失效）。
        """
        chip = getattr(self, "btn_version", None)
        if chip is None:
            return
        self._chip_state = state
        # 目录只在"要点下载之前"那次读一次（tooltip 要承诺落点），进度回调按 64 KB 一次，
        # 每次都读 config.json 的话一个 50 MB 的包就是约 800 次磁盘往返，全在 GUI 线程上。
        if dest is not None:
            self._chip_folder = Path(dest)
        elif state == "update" or not getattr(self, "_chip_folder", None):
            self._chip_folder = _main.load_download_dir()
        folder = self._chip_folder
        if isinstance(pct, int) and not isinstance(pct, bool):
            self._chip_pct = max(0, min(int(pct), 99))
        elif state != "downloading":
            self._chip_pct = None        # 下载中不传 pct = 沿用上一次，别把进度打回"…"
        if state == "update":
            text = f"↓ v{new_version} 待更新"
            tip = (f"发现新版本 v{new_version}（当前 v{_main.APP_VERSION}）\n"
                   f"点击直接下载到：{folder}\n"
                   "下载不会改动、也不会替换正在运行的本程序")
        elif state == "downloading":
            # 这一态不加状态字：进度本身就是状态，而标题栏是最窄的一档（见裁字用例）
            text = f"↓ {self._chip_pct}%" if self._chip_pct is not None else "↓ …"
            tip = (f"正在下载 v{new_version or self._chip_latest or '新版本'}"
                   f"（进度只写百分比，速度和字节数在日志里）\n保存到：{folder}")
        elif state == "latest":
            text = f"v{_main.APP_VERSION} 最新"
            tip = (f"当前 v{_main.APP_VERSION} 已是最新版本\n点击可以再查一次"
                   "（启动后一天最多自动查一次）")
        elif state == "error":
            text = f"? v{_main.APP_VERSION} 未查到"
            tip = (f"没查到新版本：{reason}\n"
                   "不影响软件本身使用，点击可以再查一次")
        elif state == "checking":
            text = f"⟳ v{_main.APP_VERSION} 检查中"
            tip = f"正在检查更新…（当前 v{_main.APP_VERSION}）"
        else:                                    # idle
            text = f"v{_main.APP_VERSION}"
            tip = (f"当前版本 v{_main.APP_VERSION}\n点击检查有没有新版本"
                   "（启动后一天最多自动查一次）")
        if chip.text() != text:
            chip.setText(text)
        if chip.property("chipState") != state:
            chip.setProperty("chipState", state)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        chip.setToolTip(tip)

    def _on_version_clicked(self) -> None:
        """点 chip：有新版就直接下，正在下就别开第二路，其余情况都是"再查一次"。"""
        state = getattr(self, "_chip_state", "idle")
        worker = getattr(self, "_update_dl", None)
        if state == "downloading" or _main._qthread_state(worker) == "running":
            self._append_log("info", "新版本正在下载中，进度就在左上角这颗 ↓ 上。")
            self._set_chip_state("downloading")
            return
        if state == "update" and self._begin_app_update_download(self._update_res):
            return
        self._start_update_check(auto=False)

    def _begin_app_update_download(self, res) -> bool:
        """把新包下到**记住的目录**，绝不替换正在运行的自己（规则 R12）。

        为什么不弹"确定要下载吗"、也不弹目录选择框：这是标题栏上的一次点击，
        弹一个模态文件框很突兀，而落点已经有 `download_dir` 这个偏好可用；
        下载本身不改注册表、不碰本程序，误点的代价只是一次网络传输。
        返回 False 表示没有可下的产物，调用方该退回"查一次"。
        """
        res = res if isinstance(res, dict) else {}
        latest = res.get("latest") or {}
        asset = res.get("asset")
        version = str(latest.get("version") or "")
        if not isinstance(asset, dict) or not asset.get("browser_download_url"):
            return False
        folder = _main.load_download_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._append_log("error", f"建不出下载目录 {folder}：{exc}")
            return False
        dest = _main._unique_download_path(folder / _main._safe_download_name(asset.get("name")))
        urls = _main.update_download_urls(asset, str(latest.get("tag") or ""))
        size = int(asset.get("size") or 0)
        magic = _main._MAGIC_BY_EXT.get(dest.suffix.lstrip(".").lower(), b"")
        self._chip_latest = version
        self._set_chip_state("downloading", new_version=version, pct=0, dest=folder)
        self._append_log("info", f"开始下载 v{version}：{dest}（{len(urls)} 个源依次尝试）")
        if not size:
            # 从 Gitee 的 releases API 拿到的清单没有 size 字段 —— 明说核不了字节数，
            # 别等下完悄悄放行，那和"没验"不是一回事。
            self._append_log("info", "（本次的官方清单没给字节数，完成后只核对文件头魔数）")
        self._update_dl = _main.DownloadWorker(urls, dest, parent=self, expect_magic=magic)
        self._update_dl.progress.connect(self._on_update_progress)
        self._update_dl.log.connect(lambda lvl, msg: self._append_log(lvl, f"[更新] {msg}"))
        self._update_dl.finished_ok.connect(
            lambda p: self._on_update_downloaded(p, size, version))
        self._update_dl.finished_fail.connect(
            lambda e: self._on_update_download_failed(e, version))
        self._update_dl.start()
        return True

    def _on_update_progress(self, got: int, total: int) -> None:
        """chip 上只写百分比：标题栏宽度紧（之前多加一个按钮就把「清理残留 PATH」裁过）。

        封顶 99%：字节还没落盘就显示 100% 是撒谎，落盘与核对完成另有回调。
        """
        pct = 0 if total <= 0 else int(got * 100 / total)
        self._set_chip_state("downloading", new_version=self._chip_latest,
                             pct=min(pct, 99))

    def _on_update_download_failed(self, message: str, version: str) -> None:
        self._append_log("error", f"[更新] 下载失败：{message}")
        self._set_chip_state("update", new_version=version)

    def _notify_update_without_asset(self, res) -> None:
        """**这个 Release 里没有本平台可下的产物**时唯一的说法。

        有产物的路径不经过这里：点 chip 直接下（`_begin_app_update_download`），
        弹一次"要下载吗"再弹一次"存到哪"，对标题栏上的一次点击是两道多余的坎。
        """
        res = res if isinstance(res, dict) else {}
        latest = res.get("latest") or {}
        page = str(latest.get("page_url") or _main.GITHUB_URL)
        version = str(latest.get("version") or "")
        _main.QMessageBox.information(
            self, "发现新版本",
            f"v{version} 已发布，但这个 Release 里找不到本平台可用的安装包。\n"
            f"可以到发布页看看：{page}")

    def _on_update_downloaded(self, path: str, expected_size: int, version: str) -> None:
        """下完了先核字节数，再问要不要打开所在文件夹。"""
        self._set_chip_state("update", new_version=version)
        got = 0
        try:
            got = Path(path).stat().st_size
        except OSError as exc:
            self._append_log("error", f"[更新] 下载说成功了，但读不到文件 {path}：{exc}")
            return
        if expected_size and got != expected_size:
            self._append_log("error", f"[更新] 字节数对不上：声明 {expected_size}，实际 {got}"
                               "（别用这个文件，去发布页重新下）")
            return
        self._append_log("ok", f"[更新] v{version} 已下载到 {path}（{_main.human_size(got)}，"
                         + (f"字节数已核对，与官方声明的 {expected_size} 一致）"
                            if expected_size else "未能核对字节数：官方清单没给 size）"))
        reply = _main.QMessageBox.question(
            self, "下载完成",
            f"已下载到：\n{path}\n\n要打开所在文件夹吗？"
            "（把新的 ByteTools 放到你习惯的位置，替换旧文件前先退出本程序）",
            _main.QMessageBox.Yes | _main.QMessageBox.No, _main.QMessageBox.Yes)
        if reply == _main.QMessageBox.Yes and not _main._open_in_file_manager(str(Path(path).parent)):
            self._append_log("warn", f"[更新] 打不开目录 {Path(path).parent}，请自己到该路径取文件")

    def _on_status_link(self, link: str) -> None:
        """状态条里的 `dir://…` → 用系统文件管理器打开那个目录（2026-10-10 用户要求）。

        为什么值得给：工作目录 `~/.env-tools` 是用户排查问题第一眼要看的地方
        （下载包、各组件版本目录、日志、takeover 备份都在里面）。以前那串路径是纯文本，
        照着敲进资源管理器地址栏是个体力活。
        """
        if not link.startswith("dir://"):
            return
        target = link[len("dir://"):]
        if not _main._open_in_file_manager(target):
            self._log("warn", f"打不开工作目录 {target}：目录不存在，或系统不允许从本工具打开")

    def _set_log_open(self, open_: bool) -> None:
        """展开/收起日志浮层。

        浮层不在卡片区的布局里，所以这里**不会**触发 relayout —— 网格的行数
        与每行卡片数在开关前后完全一致（这是浮层相对"挤压式折叠"的关键差别）。
        """
        overlay = getattr(self, "log_overlay", None)
        if overlay is None:
            return
        if open_:
            self._position_log_overlay()
            overlay.show()
            overlay.raise_()
        else:
            overlay.hide()
        self._refresh_log_button()

    def _on_log_button_clicked(self) -> None:
        """点「📋 日志」：toggle 一次；点开即视为已读，未读计数清零。"""
        if self.log_overlay.isHidden():
            self._log_unread = 0
            self._set_log_open(True)
        else:
            self._close_log_by_user()

    def _close_log_by_user(self) -> None:
        self._set_log_open(False)

    def _refresh_log_button(self) -> None:
        btn = getattr(self, "btn_log", None)
        if btn is None:
            return
        unread = getattr(self, "_log_unread", 0)
        # 未读条数直接写在按钮文字里：不新增控件，标题栏也用不着再挤一个位置
        btn.setText(f"📋 日志 ({unread})" if unread else "📋 日志")

    def _on_view_mode_clicked(self) -> None:
        """网格 ⇄ 列表。列表模式就是"强制 1 列"，卡片内容一模一样。"""
        self.view_mode = "list" if self.view_mode == "grid" else "grid"
        self._refresh_view_button()
        for idx in range(len(self._tab_cards)):
            self.relayout_cards(idx)
        self._save_settings()

    def _refresh_view_button(self) -> None:
        btn = getattr(self, "btn_view_mode", None)
        if btn is None:
            return
        grid = getattr(self, "view_mode", "grid") != "list"
        btn.setText("▦ 网格" if grid else "☰ 列表")

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    @staticmethod
    def _make_search_icon(color: str = "#8ba0b6", size: int = 16) -> _main.QIcon:
        """
        用 QPainter 现画一个放大镜图标，省得为一张 16px 小图额外引入资源文件。

        入参 color: str   线条颜色，默认与占位文字同一灰蓝色系
              size:  int  逻辑边长（像素）；内部按 2 倍分辨率绘制，高分屏不糊

        返回: QIcon  可直接 pixmap() 给 QLabel，或 addAction() 给 QLineEdit
        """
        pm = _main.QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(_main.Qt.transparent)
        painter = _main.QPainter(pm)
        painter.setRenderHint(_main.QPainter.Antialiasing, True)
        pen = _main.QPen(_main.QColor(color))
        pen.setWidthF(1.6)
        pen.setCapStyle(_main.Qt.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(2, 2, 9, 9)          # 镜片
        painter.drawLine(11, 11, 14, 14)         # 手柄
        painter.end()
        return _main.QIcon(pm)

    @staticmethod
    def _make_clear_icon(color: str = "#9aabbd", size: int = 16) -> _main.QIcon:
        """
        用 QPainter 画一个统一风格的「×」，作为搜索框的清空按钮图标。

        入参 color: str  线条颜色（默认与放大镜、占位文字同色系）
              size:  int 逻辑边长（像素），同样按 2 倍分辨率绘制

        返回: QIcon
        """
        pm = _main.QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(_main.Qt.transparent)
        painter = _main.QPainter(pm)
        painter.setRenderHint(_main.QPainter.Antialiasing, True)
        pen = _main.QPen(_main.QColor(color))
        pen.setWidthF(1.6)
        pen.setCapStyle(_main.Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(5, 5, 11, 11)
        painter.drawLine(11, 5, 5, 11)
        painter.end()
        return _main.QIcon(pm)

    def _sync_clear_action(self, text: str) -> None:
        """有输入才显示清空按钮，空串时藏起来，免得占着位置显得多余。"""
        action = getattr(self, "_clear_action", None)
        if action is not None:
            action.setVisible(bool(text))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802  Qt 规定的驼峰签名
        """
        把搜索框的焦点变化转发给外壳，做出「整条胶囊一起高亮」的效果。

        说明: QSS 的 :focus 只能命中聚焦控件自身，管不到父级 QFrame，
              所以这里手动改外壳的 focused 属性并触发重新应用样式。
        """
        try:
            if obj is getattr(self, "search_box", None):
                if event.type() == _main.QEvent.FocusIn:
                    self._set_search_focus(True)
                elif event.type() == _main.QEvent.FocusOut:
                    self._set_search_focus(False)
        except RuntimeError:
            # 关窗销毁阶段子控件的 C++ 对象可能已被回收，此时忽略即可
            pass
        return super().eventFilter(obj, event)

    def _set_search_focus(self, focused: bool) -> None:
        """设置搜索外壳的聚焦态样式（改属性后需 unpolish/polish 才会重绘）。"""
        shell = getattr(self, "search_shell", None)
        if shell is None:
            return
        shell.setProperty("focused", "true" if focused else "false")
        shell.style().unpolish(shell)
        shell.style().polish(shell)
        # 放大镜跟着边框一起变色，聚焦反馈更完整
        icon = getattr(self, "search_icon", None)
        if icon is not None:
            color = "#4a7fd0" if focused else "#8ba0b6"
            icon.setPixmap(self._make_search_icon(color).pixmap(16, 16))

    def _apply_search(self, query: str) -> None:
        """
        全组件搜索：命中跨所有分类，结果归并到统一面板。

        入参 query: str  搜索框当前内容；空串（或全空白）表示退出搜索、恢复四个 Tab。

        行为:
        - 退出搜索: 卡片全部回到各自 Tab、恢复可见，显示三个分类 Tab，Tab 标题恢复「总数」。
        - 进入搜索: 收起 Tab，把所有命中的组件按分类归并到统一结果列表（带分类小标题），
          一眼看全，不用切页。过滤只动卡片可见性/归属，**不动 self.cards 平铺列表**——
          刷新版本 / 存配置 / 关窗等探测逻辑都遍历那个列表，隐藏不能让它缺项。
        """
        q = query.strip()

        # 「先无条件复位到浏览基线」这一步 2026-10-12 去掉了：它是卡顿的全部来源。
        # 一次复位 = 把 85 张卡逐个 setVisible(True) + 四个 Tab 各销毁重建一遍行，
        # 而连续输入时紧接着就要把它们再搬进结果面板，等于每敲一个字白做两遍搬家。
        # 基线并不需要一个显式复位：`_build_unified` 开头就 `_clear_results_layout()`
        # （命中的卡回到各自 Tab 容器），随后对**每一张**卡都重设可见性与归属，
        # 所以"重复搜索、清空再搜"拿到的已经是干净状态。
        # 清空输入要回到浏览态时才真复位，而且只在确实处于搜索态时复位一次：
        # 浏览态下按退格把最后一个字符删掉，不该重排 85 张卡。
        # 重建期间关掉重绘（2026-10-15 性能修复）：一次重建要让几十上百张卡搬家、
        # 销毁旧行、再建新行，而本函数是**同步**的 —— 回到事件循环之前根本不会重绘，
        # 开着只让 Qt 在每个中间态白算一遍布局与绘制。实测省掉约 1/3 的总耗时。
        # 必须 try/finally：异常时也要把重绘还回去，否则窗口从此不再刷新
        # （那是比"慢"更难排查的故障）。
        self.setUpdatesEnabled(False)
        try:
            if not q:
                if self._in_search():
                    self._restore_browse()
                self.search_hint.setText("")
                self.search_hint.setProperty("empty", "false")
                self.search_hint.style().unpolish(self.search_hint)
                self.search_hint.style().polish(self.search_hint)
                return

            self._build_unified(q)
        finally:
            self.setUpdatesEnabled(True)

    def _in_search(self) -> bool:
        """结果面板是否正盖着四个 Tab（`top_stack` 第 1 页 = 统一搜索结果）。

        半构造的窗口（测试里造的半成品 MainWindow）可能还没有 `top_stack`，
        按"不在搜索态"处理 —— 调用方据此只会少走一次复位，不会漏做该做的重排。
        """
        stack = getattr(self, "top_stack", None)
        return stack is not None and stack.currentIndex() == 1

    def _restore_browse(self) -> None:
        """把全部卡片放回各自 Tab 并恢复可见，切回浏览模式，然后按列数重排。"""
        # 从统一结果面板卸下所有卡片（卡片先回到自己 Tab 的容器，小标题才销毁）
        self._clear_results_layout()
        # 搜索时被隐藏的卡片要一起放出来，否则重排会因为"看不见"把它们漏掉
        for card in self.cards:
            card.setVisible(True)
        self.top_stack.setCurrentIndex(0)
        for idx in range(len(self._tab_cards)):
            self.relayout_cards(idx)
        # Tab 标题恢复成「分类（总数）」，并重新标出哪些页有组件在运行
        self._mark_running_tabs()
        self._tab_rows[_main.RESULTS_KEY] = []

    def _log_credentials_of(self, key: str, port: int) -> None:
        """主窗侧：把某个正在运行的组件的登录凭据写进全局日志。

        读不到就跳过——凭据只是便利信息，缺了不该让"认清本机运行状态"看起来失败。
        """
        # 走模块级组件表而不是 self 上的什么：这里在测试里可能被一个
        # "半初始化实例"（只绑了几个方法、没跑 __init__）调用，
        # 模块级函数对那种实例一样成立。
        comp = _main.component_registry().get(key)
        if comp is None or getattr(comp, "launch", None) is None:
            return
        try:
            for line in _main.credentials_for(comp, comp.launch, port):
                self._append_log("info", f"[{comp.display_name}] {line}")
        except Exception:
            pass

    def _mark_running_tabs(self) -> None:
        """Tab 标题后标 `●` 表示"这一页有组件在运行"，清空搜索/退出搜索时都要重算。

        2026-10-06 用户反馈"启动了 nacos，没看到停止选项"—— 按钮一直是好的，
        但当时三个启动组件分在两个 Tab（Nacos/ActiveMQ 在「服务端组件」、Jenkins 在「其它软件」），
        界面默认停在「开发环境」。用户在自己的启动页上找不到刚才那个卡片。
        （2026-10-08 起可启停组件已集中到「一键启停」Tab，这一条分散找卡的起因消了；
        `●` 仍然保留 —— 同时跑着两三个组件时，还是要知道哪一页上有活的。）
        标题上挂个 `●`，无论停在哪一页都能一眼看出"有东西在跑，去那页找"。
        """
        tabs = getattr(self, "tabs", None)
        if tabs is None:                      # 构造期/测试用的半成品窗口：没有 Tab 就没什么可标
            return
        base_titles = getattr(self, "_tab_base_titles", [])
        tab_cards = getattr(self, "_tab_cards", [])
        for idx in range(tabs.count()):
            base = base_titles[idx] if idx < len(base_titles) else tabs.tabText(idx)
            cards = tab_cards[idx] if idx < len(tab_cards) else []
            running = any(hasattr(c, "btn_start") and c._running_per_ui()
                          for c in cards)
            tabs.setTabText(idx, f"{base}{'  ●' if running else ''}")

    def _reveal_running_tabs(self) -> None:
        """有组件在运行时，若它不在当前 Tab，就把 Tab 切过去并说清是哪一页。

        2026-10-06 用户反馈"启动了 nacos，没看到停止选项"。查下来按钮一直是好的
        （btn_stop 可见可用、文本"停止"、label 显示"● 运行中 · 端口 8848"），
        真正的原因是**当时三个启动组件分在两个 Tab**：
        Jenkins 在「其它软件」，Nacos/ActiveMQ 在「服务端组件」，
        而界面默认停在 Tab0「开发环境」。用户自然找不到自己刚启动的那个卡片。
        （2026-10-08 起它们都在「一键启停」一页；跳页与这句说明留着，是因为
        同时跑多个组件、或用户停在别的页上时，症状会一模一样地复发。）

        这不是"找不到按钮"，是"服务跑着却看不见"——比按钮缺失更容易让人以为没启动成功。
        所以这里主动跳页+ 点名在日志里说清，不指望用户自己 Tab 翻一遍。
        """
        self._mark_running_tabs()
        tabs = getattr(self, "tabs", None)
        layouts = getattr(self, "_tab_layouts", None)
        tab_cards = getattr(self, "_tab_cards", None)
        if tabs is None or not layouts or not tab_cards:
            return
        for card in self.cards:
            if not hasattr(card, "btn_start"):
                continue
            if not card._running_per_ui():
                continue                     # 没在运行，不用跳
            # 按 _tab_cards 判归属，不按 layout.indexOf：改成行容器后卡片不在
            # 外层布局里（它的父级是行控件），indexOf 恒为 -1，跳页会静默失效。
            idx = next((n for n, cards in enumerate(tab_cards)
                        if any(c is card for c in cards)), -1)
            if idx >= 0 and idx != tabs.currentIndex():
                tabs.setCurrentIndex(idx)
                base = self._tab_base_titles[idx] if idx < len(self._tab_base_titles) \
                    else tabs.tabText(idx)
                self._append_log(
                    "info",
                    f"已切换到「{base.split('（')[0]}」页："
                    f"{card.component.display_name} 正在运行，"
                    f"它的「停止」按钮在这一页（端口 {card._launch_status().record.port}）。")
                return                      # 一次只跳一个，避免连翻多页

    def _build_unified(self, q: str) -> None:
        """把命中的组件按分类归并进统一结果列表（带分类小标题）。

        结构与浏览 Tab 同一套网格：**分类小标题（整行）+ 该分类的若干 cardRow 行**，
        所以搜索结果的卡片宽度与浏览时一致。列数取 min(命中数, 浏览列数)，由
        `_relayout_results` 统一算 —— 命中 1 个就是 1 列，命中 5 个就是 3 列。
        """
        # send_home=False：命中的卡片**留在结果面板宿主上**，别先送回 Tab 再搬回来。
        # 搬两次家 = 每张卡两轮 QSS 重算，而这一次清空本来只是为了把旧行拆掉。
        # 退出搜索（`_restore_browse`）才需要真的送回各自 Tab。
        self._clear_results_layout(send_home=False)
        # 先按分类归好组：列数要按**总命中数**算，而它得等这一轮扫完才知道
        groups: list = []
        order: dict = {}
        hits = 0
        for card in self.cards:
            comp = card.component
            if not _main.component_matches(comp, q):
                # 只隐藏、**不送回 Tab**（2026-10-15）：搜索期间每一次"退出命中"都搬一次家
                # 就是每张卡一轮 QSS 重算，逐字输入时最贵（实测 'c'→'cu' 这一下要 0.7 s）。
                # 这些卡就留在结果面板宿主上藏着，退出搜索时由
                # `_clear_results_layout(send_home=True)` 一次扫干净（见那里）。
                card.setVisible(False)
                continue
            cat = comp.category
            if cat not in order:
                order[cat] = len(groups)
                groups.append([cat, []])
            groups[order[cat]][1].append(card)
            card.setVisible(True)
            hits += 1
        # self.cards 已是分类顺序，遍历一遍即可，标题与卡片的相对顺序天然正确
        sections: list = []
        for cat, cards in groups:
            header = _main.QLabel(cat)
            header.setObjectName("resultCatHeader")
            self.results_layout.addWidget(header)
            for card in cards:
                # 这里**刻意只设可见性、不设父级**（2026-10-15 性能修复）：
                # 下面 `relayout_cards(RESULTS_KEY)` 里 `_relayout_results` 会把
                # 这批卡收回到 `results_content` 再排进行里，在这里先 setParent
                # 一遍等于每张卡多搬一次家。而**搬到同一个父级也不便宜** ——
                # 实测 `card.setParent(同父)` 仍会触发 Qt 对该卡整棵子树重跑一遍
                # QSS 解析，约 5 ms/张；115 张就是 ~0.6 s（真机实测，见
                # DEVELOPMENT.md 的搜索性能一节）。
                card.setVisible(True)
            sections.append((header, cards))
        self.results_layout.addStretch(1)
        self._result_sections = sections
        self.top_stack.setCurrentIndex(1)

        # 四个 Tab 在搜索期间**不重排**（2026-10-12 性能修复，卡顿的另一半）。
        # 原来这里要 relayout 四遍"把被搬走的命中卡片从旧行里摘掉"，但那四页此刻
        # 正被 top_stack 的结果面板盖着，一个字都看不见；卡片 setParent 走时 Qt 已经
        # 把它们从旧 QHBoxLayout 里摘了，留下的只是不可见页上的空位。退出搜索走
        # `_restore_browse()`，它无条件把四个 Tab 各重排一遍 —— 该补的账在那儿补。
        # 中间态的唯一读者是 resizeEvent（列数变了才重排），而 relayout_cards 自己按
        # `root.isAncestorOf(c)` 判归属，搬走的卡片不会被它拽回 Tab，所以跳过是安全的。
        # 省下的是**每次输入 4 次销毁重建**：连打五个字少 20 次整页重排。
        self.relayout_cards(_main.RESULTS_KEY)

        self.search_hint.setText(f"匹配 {hits} / {len(self.cards)} 个组件")
        # 一个都没命中时换个警示色，免得用户以为列表加载坏了
        self.search_hint.setProperty("empty", "true" if hits == 0 else "false")
        self.search_hint.style().unpolish(self.search_hint)
        self.search_hint.style().polish(self.search_hint)

    def _send_card_home(self, card) -> None:
        """把卡片从它当前所在的"行"里摘下、挂回所属 Tab 的容器（不销毁）。

        换父级并不会让旧布局自动放手，所以必须显式 removeWidget：否则销毁行控件
        时 Qt 会把行内的卡片一起带走，下一轮搜索就少卡。
        """
        parent = card.parent()
        lay = parent.layout() if parent is not None else None
        if lay is not None and lay.indexOf(card) != -1:
            lay.removeWidget(card)
        home = self._home_wrap_of(card)
        if home is not None:
            card.setParent(home)      # 卡片稍后由 _restore_browse 重排归位

    def _clear_results_layout(self, send_home: bool = True) -> None:
        """清空统一结果面板里的所有条目（分类小标题、卡片行）。

        卡片**不在这里销毁**：它们只是被摘出布局。去哪由 `send_home` 决定 ——
        退出搜索时回各自 Tab 的容器；**连续搜索时原地留在宿主里**。
        留在原地是这次性能修复的一半：下一次重排把它们放进新行时父级没变，
        Qt 就不必重跑那棵子树的 QSS 解析（见 R2.6 与 `_make_layout_rows`）。

        入参 send_home: bool  True → 卡片回所属 Tab（退出搜索）；
                             False → 卡片留在 `results_content` 上（继续搜索）。
        """
        self._result_sections = []
        self.results_layout.row_widgets = []
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            w = item.widget()
            sub = item.layout()
            if sub is not None:
                # 无宿主行布局：逐个摘出条目，再丢掉空布局。
                # 卡片按 send_home 决定去向；占位格是临时控件，随行一起销毁。
                while sub.count():
                    child = sub.takeAt(0).widget()
                    if child is None:
                        continue
                    if any(child is card for card in self.cards):
                        if send_home:
                            self._send_card_home(child)
                    else:
                        child.hide()
                        child.deleteLater()
                sub.deleteLater()
                continue
            if w is not None:
                if w.objectName() == "cardRow":
                    # Tab 的行控件（结果面板已改用无宿主布局，这里保留兜底）：
                    # 先把卡片送回各自 Tab，再销毁空行 —— 直接 deleteLater
                    # 会把行内的卡片一起带走。
                    lay = w.layout()
                    if lay is not None:
                        while lay.count():
                            child = lay.takeAt(0).widget()
                            if child is not None and send_home:
                                self._send_card_home(child)
                    w.hide()
                    w.deleteLater()
                    continue
                if any(w is card for card in self.cards):
                    if send_home:
                        self._send_card_home(w)
                    continue
                # deleteLater 是**异步**的：takeAt 之后布局不再管它，但 widget 的
                # parent 还挂在 results_content 上、几何也没变，在 deferred delete
                # 真正执行前会以"幽灵"形态残留在原地 —— 用户连续改搜索词时，上一轮
                # 的分类标题会和这一轮的内容叠在一起（真机 2026-10-08 实测踩中）。
                # 先 hide 立即从屏幕上消失，删除交给事件循环。
                w.hide()
                w.deleteLater()           # 分类小标题等临时标签
                continue
            sp = item.spacerItem()
            if sp is not None:
                del sp

        if send_home:
            # 收尾扫一遍"不属于任何一行、但父级还是宿主"的卡片。
            # 搜索期间它们被刻意留在宿主上（只隐藏不搬家，省掉每张一轮 QSS 重算），
            # 于是布局里已经找不到它们 —— 上面那圈"拆行"只会走到"行里的卡"。
            # 漏掉这一步的后果很实在：结果面板是 `top_stack` 的隐藏页，卡挂在那儿
            # 等于浏览态下**凭空少一批卡片**（2026-10-15 自查实测到：清空后仍有 115 张
            # 卡留在 results_content 上）。
            for card in self.cards:
                if card.parent() is self.results_content:
                    self._send_card_home(card)

    def _home_wrap_of(self, card):
        """这张卡片所属 Tab 的容器（搜索结束要按它归位）。"""
        for idx, cards in enumerate(self._tab_cards):
            if any(c is card for c in cards):
                return self._tab_wraps[idx]
        return None

    def _apply_qss(self) -> None:
        """应用全局样式表。

        样式表本体在 `theme.QSS`（2026-10-14 从这里抽出去）——它是一份纯声明
        数据，没有分支也不参与计算，混在 MainWindow 里只会让改配色变成
        "翻 20000 行找一段 CSS"。
        """
        from theme import QSS
        self.setStyleSheet(QSS)

    def mousePressEvent(self, event) -> None:
        if event.button() == _main.Qt.LeftButton and self.title_bar.underMouse():
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & _main.Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self.title_bar.underMouse():
            self._toggle_max()

    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.btn_max.setText("▢")
        else:
            self.showMaximized()
            self.btn_max.setText("❐")

    # ------------------------------------------------------------------
    def _on_wsl_clicked(self) -> None:
        """打开 WSL 安装向导（非模态：下载/提权期间主窗口还能用）。"""
        dlg = getattr(self, "_wsl_dialog", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        self._wsl_dialog = _main.WslDialog(self)
        self._wsl_dialog.setModal(False)
        self._wsl_dialog.show()

    def _on_cleanup_path_clicked(self) -> None:
        """扫描并清理 PATH 中指向本工具目录、但已不存在的残留条目。"""
        dead = _main.find_dead_tool_path_entries()
        if not dead:
            _main.QMessageBox.information(
                self,
                "清理残留 PATH",
                f"PATH 中没有发现本工具（{_main.CONFIG_DIR}）留下的失效条目。",
            )
            return
        detail = "\n".join(f"· {p}" for p in dead[:12])
        if len(dead) > 12:
            detail += f"\n… 等共 {len(dead)} 条"
        reply = _main.QMessageBox.question(
            self,
            "清理残留 PATH",
            f"PATH 中有 {len(dead)} 条指向已不存在的目录：\n\n{detail}\n\n"
            "只删除这些失效条目，其他程序的 PATH 不受影响。确认清理？",
            _main.QMessageBox.Yes | _main.QMessageBox.No,
            _main.QMessageBox.No,
        )
        if reply != _main.QMessageBox.Yes:
            self._append_log("info", "已取消清理残留 PATH。")
            return
        removed = _main.cleanup_dead_tool_path_entries()
        if removed:
            self._append_log(
                "ok", f"已清理 {len(removed)} 条残留 PATH：" + "、".join(removed)
            )
        else:
            self._append_log("warn", "未删除任何条目（可能目录刚被重建）。")
        for card in self.cards:
            card._detect_status()

    # ------------------------------------------------------------------
    def _start_fetch_versions(self, force: bool = False) -> None:
        """从各官网并发拉取版本列表。可反复调用（刷新）。

        force=False（启动那一次）：24 小时内抓过的组件直接用磁盘缓存，不再打网络 ——
        GitHub 匿名额度只有 60 次/小时/IP，一次启动 77 路，一小时内第二次开工具就会
        集体失败（见 R15）。force=True（用户点「⟳ 刷新版本」）：绕过缓存全量重抓。
        """
        if self._closing:
            return
        # 若有 worker 仍在运行、或已排期但尚未启动（错峰未触发），等它跑完再触发新一轮：
        # 未启动的线程 isRunning()=False 但也没跑完，必须一并算"忙"，否则会被下面
        # cleanup 提前 deleteLater，定时器回调再来访问就是已释放对象。
        # 判定走 _qthread_state 而不是裸调 isRunning()：引用可能还留着但 C++ 对象已经被
        # 删掉了，这时裸调抛的是 RuntimeError，会把整条"刷新版本"打断。
        busy = [w for w in self._fetch_workers if _main._qthread_state(w) in ("running", "idle")]
        if busy:
            self._append_log("warn", f"仍有 {len(busy)} 个抓取任务在进行，请稍候…")
            return
        # 清理已完成的 worker
        for w in self._fetch_workers:
            w.deleteLater()
        self._fetch_workers.clear()

        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText("⟳ 抓取中…")
        self._fetch_pending = 0

        cache = {} if force else _main.load_version_cache()
        todo = []
        cached_ok = 0
        for card in self.cards:
            fetcher = _main.FETCHERS.get(card.component.key)
            if not fetcher:
                continue
            if not force:
                vs = _main._cached_versions_from(cache, card.component.key)
                if vs:
                    card.set_versions(vs)
                    cached_ok += 1
                    continue
            todo.append((card, fetcher))

        if cached_ok:
            self._append_log(
                "info", f"沿用 {_main.VERSION_CACHE_TTL_SEC // 3600} 小时内抓到的版本清单"
                        f"（{cached_ok} 个组件），没有再打官网；"
                        "要拿最新版本号请点「⟳ 刷新版本」。")
        if not todo:
            # 全缓存命中：一个 worker 都没起，也就没人来收尾按钮和打完成日志
            self._fetch_finished()
            return
        self._append_log("info", "正在从各官网获取最新版本列表…")
        for i, (card, fetcher) in enumerate(todo):
            w = _main.VersionFetchWorker(card.component.key, fetcher, self)
            w.done.connect(self._on_versions_fetched)
            self._fetch_workers.append(w)
            self._fetch_pending += 1
            # 错峰启动：避免 N 路线程同时打 api.github.com 触发未认证限额（60 次/小时/IP）。
            # 2026-10-12 修复：间隔按 N 归一（min(150, 4000//N)）而不是写死 150ms ——
            # 组件从 26 涨到 80+ 之后，固定 150ms 让末位一路要 12 秒才启动，
            # 刷新按钮要等全部归零才恢复，观感就是"刷新卡 12 秒"。
            # 命中限流由 _github_api_json 立旗快速失败。
            # 走 _launch_fetch_worker 而不是裸 w.start：关窗后残留的定时器不能再起新线程，
            # 否则线程会在窗口析构时还在跑，直接把进程 abort 掉。
            gap_ms = min(150, 4000 // max(len(todo), 1))
            _main.QTimer.singleShot(i * gap_ms, lambda w=w: self._launch_fetch_worker(w))

    def _fetch_finished(self) -> None:
        """一轮抓取的收尾：恢复按钮 + 一句完成日志（缓存全命中时也要走这里）。"""
        # 整轮结束才落盘（原来每个组件抓成功就全量重写一次，一轮 87 次，
        # 全部跑在主线程信号槽里）。放在"恢复按钮"之前：万一写盘慢，
        # 按钮先恢复，用户不至于对着一个灰掉的按钮等。
        _main.flush_version_cache()
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("⟳ 刷新版本")
        self._append_log("info", "版本列表获取完成。")

    def _fetch_failure_reason(self, key: str) -> str:
        worker = next((w for w in self._fetch_workers if w.key == key), None)
        return str(getattr(worker, "error_text", "") or "")

    def _launch_fetch_worker(self, worker: _main.VersionFetchWorker) -> None:
        """错峰定时器到点后的启动入口；关窗途中则放弃启动。"""
        if self._closing or _main._qthread_state(worker) != "idle":
            return
        worker.start()

    def _on_versions_fetched(self, key: str, versions) -> None:
        if self._closing:
            return
        card = next((c for c in self.cards if c.component.key == key), None)
        if card:
            if versions is None:
                name = card.component.display_name
                reason = self._fetch_failure_reason(key)
                if _main._is_rate_limit_text(reason):
                    # 这是额度问题，不是"官网挂了"，也不是软件坏了：说清是谁的额度、
                    # 什么时候恢复，用户才不会去重装或者反复点刷新（越点越糟）。
                    self._append_log(
                        "warn", f"[{name}] GitHub 匿名额度已用完（每个 IP 每小时 60 次），"
                                f"本次用内置默认清单；一小时后再点「⟳ 刷新版本」就行。")
                else:
                    self._append_log("warn", f"[{name}] 官网版本获取失败"
                                             f"（{reason or '未知原因'}），使用内置默认列表")
            else:
                card.set_versions(versions)
                _main.save_version_entry(key, versions)
        self._fetch_pending -= 1
        if self._fetch_pending <= 0:
            self._fetch_finished()

    # ------------------------------------------------------------------
    def _on_donate_clicked(self) -> None:
        _main.DonateDialog(self).exec()

    # ------------------------------------------------------------------
    def _toast(self, text: str, msec: int = 2600) -> None:
        """在状态栏位置闪一条短提示，不弹模态框。

        入参 text: 提示文案
        入参 msec: 停留毫秒数
        用状态栏而不是 QMessageBox：这类提示是"顺带告诉用户一句"，
        弹模态框会打断他正在做的事（例如刚点完复制就去点别的按钮）。
        """
        try:
            bar = getattr(self, "status_bar", None)
            if bar is None:
                return
            original = bar.text()
            bar.setText(_main.html_escape(text))
            _main.QTimer.singleShot(msec, lambda: bar.setText(original))
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _log_file_path(self) -> Path:
        """本次会话的日志文件路径：~/.env-tools/logs/session-<时间戳>.log。

        落盘是这个界面**唯一**的诊断来源出口：日志浮层只活在内存里，
        程序一关，用户这次看到的全部信息（镜像怎么换的、哪个源失败、
        哪条 warn/error）就永久消失了。而"导出诊断信息"与报障都依赖它。
        """
        return Path(_main.CONFIG_DIR) / "logs" / f"session-{self._session_stamp}.log"

    def _log_to_disk(self, level: str, msg: str) -> None:
        """把一条日志追加到本次会话文件。**任何失败都不许影响界面**。

        入参 level: 日志级别（info/ok/warn/error）
        入参 msg:   已经过 html 转义的纯文本
        落盘格式刻意用 `[时间] [级别] 正文` 的纯文本 —— 它要被用户复制出去贴到
        issue 里，不该带 HTML 标签与颜色代码。
        """
        try:
            path = self._log_file_path()
            _main.ensure_dir(path.parent)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"[{self._session_clock()}] [{level:<5}] {msg}\n")
            # 顺手裁掉过老的会话文件：日志目录是长命目录，不裁会一直涨
            self._trim_log_files()
        except Exception:
            # 写不了日志是"诊断能力退化"，不是"用户要知道的故障"，所以静默
            pass

    def _trim_log_files(self) -> None:
        """只保留最近 LOG_KEEP_SESSIONS 个会话日志，按修改时间倒序删多余的。"""
        try:
            log_dir = Path(_main.CONFIG_DIR) / "logs"
            files = sorted(log_dir.glob("session-*.log"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            for old in files[_main.LOG_KEEP_SESSIONS:]:
                old.unlink(missing_ok=True)
        except Exception:
            pass

    def _log_text_all(self) -> str:
        """本次会话日志的纯文本全文（不含 HTML），供复制与另存。"""
        try:
            return self._log_file_path().read_text(encoding="utf-8")
        except Exception:
            # 落盘还没发生过（极少见）：从内存里的日志控件反推
            return self.log_view.toPlainText()

    def _copy_log_to_clipboard(self) -> None:
        """把本次会话日志全文复制到剪贴板。"""
        try:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(self._log_text_all())
            self._toast("日志已复制到剪贴板")
        except Exception as exc:
            self._toast(f"复制失败：{exc}")

    def _save_log_to_file(self) -> None:
        """让用户挑个位置，把「诊断报告 + 本次会话日志」一起另存为文本。

        2026-10-14：标题栏的「导出诊断」按钮按用户要求移除后，导出能力搬到这里
        —— 日志浮层本来就是这些数据的所在地，「另存为」顺手就能产出可贴进
        issue 的完整材料，不必为它单独在标题栏留一个按钮（那两个按钮常年占掉
        标题栏近三分之一宽度却不点）。
        """
        try:
            default = Path(_main.CONFIG_DIR) / "logs" / f"diagnostics-{self._session_stamp}.txt"
            _main.ensure_dir(default.parent)
            target, _ = _main.QFileDialog.getSaveFileName(
                self, "导出诊断信息与日志", str(default),
                "文本文件 (*.txt);;日志文件 (*.log);;全部文件 (*)")
            if not target:
                return
            # 诊断报告说明「环境是什么样」，会话日志说明「刚才发生了什么」，
            # 两段缺一不可：只有报告看不出问题出在哪一步，只有日志看不出环境。
            payload = _main.build_diagnostics()
            payload += "\n\n" + "=" * 60 + "\n本次会话日志\n" + "=" * 60 + "\n"
            payload += self._log_text_all()
            Path(target).write_text(payload, encoding="utf-8")
            self._append_log("ok", f"诊断信息已导出：{target}")
            self._toast("已导出，可直接附到反馈里")
        except Exception as exc:
            self._toast(f"导出失败：{exc}")

    def _session_clock(self) -> str:
        """当前时刻，格式 HH:MM:SS。会话日志只要时分秒，跨天由文件名区分。"""
        return time.strftime("%H:%M:%S")

    def _append_log(self, level: str, msg: str) -> None:
        color = {
            "info": "#dcdcdc",
            "ok": "#7CFC7C",
            "warn": "#FFB347",
            "error": "#FF6B6B",
        }.get(level, "#dcdcdc")
        self.log_view.append(f'<span style="color:{color};">{msg}</span>')
        # 同时落盘（纯文本、不带 HTML）。界面写的是转义后的 msg，直接用同一个
        # 字符串落盘最省事，也保证"用户复制的"与"界面显示的"逐字一致。
        self._log_to_disk(level, msg)
        # 同步进结构化日志历史：导出诊断时按级别汇总，不依赖 HTML 文本
        try:
            if level == "ok":
                _main.logger.ok(msg)
            elif level == "warn":
                _main.logger.warn(msg)
            elif level == "error":
                _main.logger.error(msg)
            else:
                _main.logger.info(msg)
        except Exception:  # noqa: BLE001 - 日志本身绝不能影响界面
            pass
        # 2026-10-14 按用户要求：日志浮层**永远不自动弹开**。
        # 原先这里有一段 warn/error 自动弹开 + 静默自动收起的逻辑，配一个
        # "启动后 10 秒内不弹"的静默期。它看起来能解决"启动那一波告警盖住界面"，
        # 实际却制造了用户抱怨的"偶尔自己弹出来"，原因是那个静默期只挡住**前 10 秒**：
        # 一轮版本抓取要 30~40 秒，第 12 秒、第 25 秒、第 35 秒到达的告警
        # （GitHub 限流、各组件抓取失败）全都晚于 10 秒，于是照弹不误。
        # 表现上像随机 —— 网络快时失败来得早被挡住、看起来正常；网络慢或被限流时
        # 失败来得晚就弹，所以用户觉得"有时候会自己打开"。
        #
        # 现在改成：只累计未读数并挂在「📋 日志 (N)」按钮上，绝不主动弹。
        # 用户想看就点那个按钮 —— 未读数已经把"有事发生了"说清楚了，
        # 没必要用浮层盖住他正在操作的那张卡。自动收起的一整套（_log_auto_hide
        # 定时器、_on_log_auto_hide、_log_user_open）随之删除。
        if level in ("warn", "error"):
            overlay = getattr(self, "log_overlay", None)
            if overlay is not None and overlay.isHidden():
                self._log_unread += 1
            self._refresh_log_button()


    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        """加载上次选择的版本。"""
        data = _main._config_read_raw()      # 读不到就是空表，下面每个键各取各的默认值
        # 视图模式：老配置没有这个键，取新默认 grid（不报错、不回退整个加载）
        mode = data.get("view_mode")
        self.view_mode = mode if mode in ("grid", "list") else "grid"
        try:
            selections = data.get("selections", {}) if isinstance(data, dict) else {}
            for card in self.cards:
                v = selections.get(card.component.key)
                if not v:
                    continue
                idx = card.version_combo.findText(v)
                if idx < 0:
                    continue
                # 存过的版本可能已经不在下拉框里了（在线清单只留近期版本，
                # 而离线默认清单会滞后于实际安装版本）。盲目采纳的话，
                # 界面会停在一个既没装、也点不下来的版本上——jenkins 的
                # 2.568.3 就是这么来的：它已从清单消失，装着的 2.580.1 反而被顶掉。
                # 这种情况下保留 _reload_combo_items 挑的"已安装版本"更符合直觉。
                installed = {v for v, _p in _main.installed_versions(card.component)}
                if v not in installed:
                    continue
                card.version_combo.setCurrentIndex(idx)
        except Exception:
            pass

    def _save_settings(self) -> None:
        """保存下拉框选中版本；active 由切换那侧维护，这里必须原样保留。

        合并写：先读原文件只替换 selections 那一段。整体覆盖会把 active（生效版本
        登记表）抹掉——那是切换功能写的数据，和用户这次选了哪个下拉项无关。
        （负向对照：改回整体覆盖后，测试 SaveSettingsKeepsActive 即报 KeyError: 'active'。）

        2026-10-14：原先这里手搓了整条"读-改-写"，与 _update_config 逐字重复。
        重复的代价不是难读，而是**两份逻辑必须永远保持一致** —— 而这份注释
        记着的 R3.2 事故（整体覆盖清掉 active 登记表）正是这种重复长出来的。
        现在只保留"要改哪几个键"这一段属于本方法的业务，其余全交给统一入口。
        """
        try:
            _main.ensure_dir(_main.CONFIG_DIR)

            def _mut(data: Dict[str, object]) -> None:
                data["selections"] = {
                    card.component.key: card.version_combo.currentText()
                    for card in self.cards
                }
                if not isinstance(data.get("active"), dict):
                    data["active"] = {}
                # 视图模式与 selections 一起合并写回，不整体覆盖（active 是切换那侧的数据）
                data["view_mode"] = getattr(self, "view_mode", "grid")

            _main._update_config(_mut)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _adopt_running(self) -> None:
        """启动后一次性的"认清本机在跑什么"。只读 + 清僵尸，绝不拉起进程。"""
        # 整段兜底：reconcile 清僵尸会回写 running.json（ensure_dir+写+os.replace），
        # ~/.env-tools 被只读/被锁/磁盘满时异常从这儿抛出就是从生产入口抛出、工具直接打不开 ——
        # 和读取侧"让整个界面搞崩代价不成比例"是同一个权衡，识别失败只该留下一条 warn。
        try:
            states = _main.SERVICE_MANAGER.reconcile(self.current_components())
            for key, st in states.items():
                if st.state == "running":
                    self._append_log("info", f"检测到 {key} 正在运行（端口 {st.record.port}）")
                    # 把它的登录凭据一起报出来：这些服务是之前启的，
                    # 用户重开工具时界面上没有任何地方能看到"怎么登进去"，
                    # 逼着他去翻文件或搜官方文档。
                    self._log_credentials_of(key, st.record.port)
            # 访问页服务已经改成独立进程：旧登记里的 console_url 指向的可能是
            # 上一次主进程内的老服务（已随进程退出）。没有自带控制台的组件，
            # 把登记刷新成当前页服务的地址，卡片按钮才不会打开一个死链接。
            try:
                if any(st.state == "running" for st in states.values()):
                    server = _main.get_page_server()
                    records = _main.load_running_map()
                    comps = self.current_components()
                    changed = False
                    if server is not None:
                        for key, rec in records.items():
                            comp = comps.get(key)
                            spec = getattr(comp, "launch", None)
                            if spec is not None and not spec.console_path:
                                url = server.url_for(key)
                                if url and rec.console_url != url:
                                    rec.console_url = url
                                    changed = True
                    if changed:
                        _main.save_running_map(records)
            except Exception as exc:      # noqa: BLE001
                self._append_log("warn", f"刷新访问页地址失败（不影响使用）：{exc}")
            # reconcile 可能刚把僵尸登记删掉：卡片在那之前已经画过一遍了，必须让它们重读，
            # 否则窗口里会留一句已经没有依据的"残留登记"。
            for card in self.cards:
                card._refresh_launch_state()
        except Exception as exc:
            self._append_log("warn", f"认清本机运行状态失败（不影响使用）：{exc}")
        # Tab 上的运行标记与自动跳页放在 try 之外：它们纯属界面便利，
        # 失败也不该让日志里多出一条"认清本机运行状态失败"——
        # 那句话会让用户以为状态识别出了问题，排查方向全错（2026-10-06 踩过）。
        try:
            self._reveal_running_tabs()
        except Exception as exc:
            self._append_log("warn", f"标记运行中的页面失败（不影响使用）：{exc}")

    def _cancel_launch_workers(self) -> int:
        """关窗口前让在跑的启动/停止线程体面收尾：只取消"还在等端口"，不动被管理的进程。
        先全部 cancel 再统一 wait —— 反过来写，后一个 worker 要白等前一个的超时。"""
        workers = self.findChildren(_main.LaunchWorker)
        for w in workers:
            w.cancel()
        for w in workers:
            w.wait(2000)
        return len(workers)

    def _drain_background_workers(self, budget_ms: int = 6000) -> int:
        """关窗前收掉所有还可能在跑的后台线程，返回处理掉几条。

        QThread 运行时被析构 = Windows 进程级 abort（0xC0000409，退出码 127，
        没有 traceback）—— 这仓库为同类问题已经写过 R3.14 / R14.1。要等的成员一共六类：
        应用更新下载（`_update_dl`）、更新检查（`_update_worker`）、卡片的下载
        （`card.worker`，含安装与"只下载"两条）、前置下载（`card.prereq_worker`）、
        外部版本探测（`card._external_worker`）、版本探测（`card._version_worker`
        以及**被它顶替掉的历史** `card._probe_workers`）。用户点完"下载新版本"
        再在 49 MB 中途关窗，就是必现场景。

        状态判定一律走 `_qthread_state`：这些 worker 大多连了 `finished → deleteLater`，
        引用还挂在成员上但 C++ 对象早被删了，裸调 `isRunning()` 抛的 RuntimeError 会把
        整个收尾打断 —— 2026-10-11 那个 127 就是这么来的（closeEvent 后半段没执行，
        18 条抓取线程在窗口析构时还活着）。

        先统一 cancel 再统一 wait：反过来的话第二个 worker 要白等第一个的超时。
        """
        cands: list = []
        for attr in ("_update_dl", "_update_worker"):
            w = getattr(self, attr, None)
            if w is not None:
                cands.append(w)
        for card in getattr(self, "cards", []):
            for attr in ("worker", "prereq_worker", "_external_worker", "_version_worker"):
                w = getattr(card, attr, None)
                if w is not None:
                    cands.append(w)
            cands.extend(getattr(card, "_probe_workers", ()))
        running: list = []
        seen: set = set()
        for w in cands:                      # 当前探测线程同时挂在两个成员上，按 id 去重
            if id(w) in seen or _main._qthread_state(w) != "running":
                continue
            seen.add(id(w))
            running.append(w)
        for w in running:
            cancel = getattr(w, "cancel", None)
            if cancel is not None:
                cancel()
        for w in running:
            _main._qthread_wait(w, budget_ms)
        return len(running)

    def closeEvent(self, event) -> None:
        # 关窗前先让在跑的 LaunchWorker 体面收尾（cancel+wait 的顺序理由见 _cancel_launch_workers）。
        self._cancel_launch_workers()
        # 先立旗：不再派发抓取、不再回写界面，并让在跑的抓取线程尽快从重试边界返回。
        # QThread 在运行时被析构会直接 abort 进程（Windows 退出码 0xC0000409），
        # 而版本抓取是启动即触发的，所以关窗必须等这些线程收尾。
        self._closing = True
        _main._CLOSING.set()          # 卡片通过模块级事件问"是否正在退出"
        _main.FETCH_ABORT.set()
        # 下载/检查/外部探测/版本探测这几类线程统一在这里等（含被顶替的探测历史线程）
        self._drain_background_workers()
        self._save_settings()
        # 抓取线程：_get / _github_api_json 已能协作取消，剩下的是一个在途请求的超时
        # （最长 DOWNLOAD_PROBE_TIMEOUT*2 = 10s），给 FETCH_EXIT_WAIT 秒总预算，逐个等剩余时间。
        import time as _time
        deadline = _time.monotonic() + _main.FETCH_EXIT_WAIT
        for w in self._fetch_workers:
            if _main._qthread_state(w) != "running":
                continue
            remain = max(0.0, deadline - _time.monotonic())
            _main._qthread_wait(w, int(remain * 1000))
        # 抓取线程已收尾，把这轮攒在内存里的版本条目落盘。
        # 放在最后是有意的：关窗时正在抓的那几个组件可能刚好返回了，
        # 它们的成果不该因为"用户关得比网络快"而白丢。
        _main.flush_version_cache()
        super().closeEvent(event)
