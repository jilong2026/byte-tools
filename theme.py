# -*- coding: utf-8 -*-
"""界面主题：全局 QSS 样式表。

2026-10-14 从 main.py 抽出来的。此前这 387 行样式表是一个 `_apply_qss` 方法里
的三引号字符串，和 MainWindow 的建卡/搜索/日志/更新逻辑混在同一个类里 ——
纯声明代码没有任何行为，却占了 MainWindow 方法体的一半篇幅，改布局时要在
20000 行里翻半天。

抽出来的理由只有一个：**它不是逻辑**。样式表没有分支、没有状态、不参与
计算，纯数据。放在这里可以直接被编辑器语法高亮、被 diff 工具单独比较
（改配色不该让 main.py 的 diff 变成 400 行），也不会在重构时被误当成
"顺手改改"的对象。

⚠ 改这个文件**不需要**重新跑组件相关的护栏 —— 样式表不参与任何逻辑判断；
受影响的只有 bt_grid_layout_tests.py 里的控件存在性与尺寸断言。
"""
QSS = """\
#centralRoot {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #eef2f7, stop:1 #dee5ee);
}
#titleBar {
    background: #2c3e50;
    color: white;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
#titleText { color: white; padding-left: 4px; }
#versionChip {
    background: rgba(255, 255, 255, 0.14);
    color: #dfe7ee;
    border: 1px solid rgba(255, 255, 255, 0.28);
    padding: 4px 9px;
    font-size: 12px;
    border-radius: 10px;
}
#versionChip:hover {
    background: rgba(255, 255, 255, 0.26);
    color: white;
}
/* chip 的四种状态配色，全挂在**动态属性**上（objectName 不许改，
   改了按名字找它的代码与用例就失效）。琥珀色=有新版可点，
   灰色带问号=没查到（跟"已是最新"必须一眼能分）。 */
#versionChip[chipState="update"],
#versionChip[chipState="downloading"] {
    background: #f9a825;
    color: #3e2723;
    border: none;
    padding: 4px 9px;
    font-size: 12px;
    font-weight: 700;
    border-radius: 10px;
}
#versionChip[chipState="update"]:hover,
#versionChip[chipState="downloading"]:hover {
    background: #ffb74d;
}
#versionChip[chipState="error"] {
    background: rgba(255, 255, 255, 0.08);
    color: #9aa7b3;
    border: 1px dashed rgba(255, 255, 255, 0.34);
    padding: 4px 9px;
    font-size: 12px;
    border-radius: 10px;
}
#versionChip[chipState="error"]:hover {
    color: #dfe7ee;
    border-color: rgba(255, 255, 255, 0.5);
}
#iconBtn, #donateBtn, #ctrlBtn, #closeBtn {
    background: transparent;
    color: white;
    border: none;
    padding: 6px 12px;
    font-size: 14px;
    border-radius: 6px;
}
#iconBtn:hover, #ctrlBtn:hover, #donateBtn:hover {
    background: rgba(255,255,255,0.15);
}
#donateBtn { color: #ff8181; font-size: 18px; }
#closeBtn:hover { background: #e74c3c; }

#searchBar { background: transparent; }

/* 搜索框：外壳统一承载放大镜与输入框，聚焦时整条胶囊高亮，
   比原先「细边框小方框」更有整体感，也和卡片/下拉框的圆角语言一致 */
#searchShell {
    background: #ffffff;
    border: 1px solid #d5dfea;
    border-radius: 10px;
    min-width: 340px;
    max-width: 460px;
}
#searchShell:hover { border: 1px solid #b9c9dc; }
#searchShell[focused="true"] { border: 1px solid #4a7fd0; }
#searchIcon { background: transparent; border: none; }
#compSearch {
    background: transparent;
    border: none;
    padding: 8px 0;
    font-size: 13px;
    color: #17253b;
}
#compSearch:focus { border: none; }
#compSearch QToolButton { background: transparent; border: none; }
#searchHint { color: #66788c; font-size: 12px; padding-left: 2px; }
#searchHint[empty="true"] { color: #c0392b; }

/* 搜索条右侧的两个工具按钮（视图切换 / 日志开关） */
#toolBtn {
    background: #ffffff;
    color: #33465c;
    border: 1px solid #d5dfea;
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 12px;
    font-weight: 600;
}
#toolBtn:hover { border-color: #90caf9; color: #1976d2; }

/* 卡片名称后的详情入口：一枚 20px 圆点，视觉上必须"轻"，
   不能与「可多版本」角标争注意力（同在一行）。 */
#detailBtn {
    background: #eef2f6;
    color: #5c6f82;
    border: 1px solid #d5dfea;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 700;
    padding: 0px;
}
#detailBtn:hover { background: #e3f2fd; color: #1976d2;
                   border-color: #90caf9; }
#detailTitle { color: #263238; }

#compTabs { background: transparent; border: none; }

#compTabs::pane { border: none; background: transparent; }
#compTabs > QTabBar { background: transparent; }
#compTabs > QTabBar::tab {
    background: #cfd8e3;
    color: #33465c;
    padding: 7px 18px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 600;
}
#compTabs > QTabBar::tab:selected {
    background: #ffffff;
    color: #17253b;
}
#cardsScroll { border: none; background: transparent; }
#cardsWrap { background: transparent; }

#topStack { background: transparent; }
#resultsArea { border: none; background: transparent; }
#resultsContent { background: transparent; }
#resultCatHeader {
    font-weight: 600;
    color: #33465c;
    font-size: 13px;
    padding: 8px 2px 2px 10px;
    margin-top: 4px;
    border-left: 3px solid #4a7fd0;
}
#card {
    background: white;
    border-radius: 12px;
    border: 1px solid #e6ebf1;
}
#cardTitle { color: #263238; }
#statusLabel { font-size: 12px; }
#fieldLabel { color:#546e7a; font-size:13px; }

/* ---- 「系统里检测到的版本」折叠区（设计 §6）----
   格子内部只有 271px，所以这里是"一行一件事"的紧凑排版：
   标题是一条扁按钮，展开后每行是「版本·路径 + 切过去」。 */
#externalToggle {
    text-align: left;
    padding: 0 6px;
    border: 1px dashed #cfd8dc;
    border-radius: 7px;
    background: #f7f9fc;
    color: #455a64;
    font-size: 12px;
}
#externalToggle:hover { border-color: #90caf9; color: #1565c0; }
#externalRow { background: transparent; }
#externalVersion { color:#263238; font-size:12px; font-weight:600; }
#externalPath { color:#78909c; font-size:11px; }
#externalLabel { color:#37474f; font-size:12px; }
#externalHint { color:#90a4ae; font-size:12px; }
#restoreBtn {
    border: 1px solid #ffb74d;
    border-radius: 7px;
    background: #fff8e1;
    color: #e65100;
    font-size: 12px;
    font-weight: 600;
}
#restoreBtn:hover { background: #ffecb3; border-color: #ffa726; }

/* ----------------- 下拉框 ----------------- */
QComboBox {
    padding: 0 34px 0 12px;
    border: 1px solid #cfd8dc;
    border-radius: 8px;
    background: white;
    color: #263238;
    font-size: 13px;
    min-height: 32px;
    selection-background-color: #1976d2;
}
QComboBox:hover  { border-color: #90caf9; }
QComboBox:focus  { border-color: #1976d2; }
QComboBox:on     { border-color: #1976d2; }
QComboBox QLineEdit {
    border: none;
    background: transparent;
    padding: 0;
    margin: 0;
    color: #263238;
    font-size: 13px;
    selection-background-color: #1976d2;
    selection-color: white;
}
QComboBox QLineEdit:focus { outline: none; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 30px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
}
#comboArrow {
    color: #78909c;
    font-size: 14px;
    background: transparent;
    border: none;
    padding-right: 6px;
}
QComboBox:hover #comboArrow { color: #1976d2; }
QComboBox:focus #comboArrow { color: #1976d2; }
QComboBox QAbstractItemView {
    border: 1px solid #cfd8dc;
    border-radius: 8px;
    background: white;
    padding: 6px;
    outline: 0;
    selection-background-color: #1976d2;
    selection-color: white;
}
QComboBox QAbstractItemView::item {
    padding: 8px 14px;
    border-radius: 6px;
    min-height: 24px;
    color: #263238;
}
QComboBox QAbstractItemView::item:hover {
    background: #e3f2fd;
    color: #0d47a1;
}
QComboBox QAbstractItemView::item:selected {
    background: #1976d2;
    color: white;
}

QPushButton#primaryBtn {
    background: #1976d2;
    color: white;
    border: none;
    padding: 6px 8px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton#primaryBtn:hover { background: #1e88e5; }
QPushButton#primaryBtn:pressed { background: #1565c0; }
QPushButton#primaryBtn:disabled { background: #b0bec5; color:#eceff1; }

QPushButton#secondaryBtn {
    background: #ffffff;
    color: #1976d2;
    border: 1px solid #1976d2;
    padding: 6px 8px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton#secondaryBtn:hover { background: #e3f2fd; }
QPushButton#secondaryBtn:pressed { background: #bbdefb; }
QPushButton#secondaryBtn:disabled {
    color: #b0bec5;
    border-color: #cfd8dc;
    background: #f5f7fa;
}

QPushButton#dangerBtn {
    background: #ffffff;
    color: #c62828;
    border: 1px solid #c62828;
    padding: 6px 8px;
    border-radius: 8px;
    font-size: 13px;
}
QPushButton#dangerBtn:hover { background: #ffebee; }
QPushButton#dangerBtn:disabled { color:#e0a4a4; border-color:#e0a4a4; }

QProgressBar {
    background: #eceff1;
    border: none;
    border-radius: 6px;
    height: 14px;
    text-align: center;
    color: #263238;
    font-size: 11px;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #26c6da, stop:1 #1976d2);
}

/* 日志浮层：盖在卡片区上面，不占布局空间（展开不会挤压网格） */
#logOverlay {
    background: #26303f;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    border-top: 1px solid #3d4a5d;
}
#logOverlay QLabel { color: #e6e9ef; }
#overlayCloseBtn {
    background: transparent;
    color: #9fb0c4;
    border: none;
    font-size: 16px;
    border-radius: 6px;
}
#overlayCloseBtn:hover { background: rgba(255,255,255,0.12); color: #ffffff; }
/* 日志浮层头部的「复制」「另存为」（2026-10-14）：比关闭按钮稍重，
   因为它们是用户报障时会主动去点的两个动作。 */
#overlayCopyBtn {
    background: rgba(255,255,255,0.08);
    color: #cfd8e3;
    border: 1px solid rgba(255,255,255,0.14);
    font-size: 12px;
    border-radius: 5px;
}
#overlayCopyBtn:hover { background: rgba(255,255,255,0.18); color: #ffffff; }
#overlayCopyBtn:pressed { background: rgba(255,255,255,0.06); }
#logView {
    background: #1e1e2e;
    color: #dcdcdc;
    border-radius: 8px;
    padding: 6px;
    font-family: Menlo, Consolas, "Courier New", monospace;
    font-size: 12px;
}
#statusBar {
    background: #eceff1;
    color: #455a64;
    padding: 6px 14px;
    font-size: 12px;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 0;
}
QScrollBar::handle:vertical {
    background: #b0bec5;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #90a4ae; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QToolTip {
    background: #37474f;
    color: white;
    border: 1px solid #263238;
    padding: 6px 10px;
    border-radius: 6px;
}
"""
