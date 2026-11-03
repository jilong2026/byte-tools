"""组件卡片（从 main.py 抽出，规则 R30）。

仅本地导入基类 QFrame 与 Signal；其余 Qt / 业务名一律 `_main.<name>` 晚绑定。
方法内的嵌套函数、lambda 参数、局部 import 均视为本地名。
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
from PySide6.QtWidgets import QFrame


_main = None


def configure(main_module) -> None:
    global _main
    _main = main_module


class ComponentCard(QFrame):
    """展示一个组件的卡片。"""

    request_log = Signal(str, str)
    # 向导型卡片（ui_action="wsl"）请求打开安装向导：由 MainWindow 建卡时接线。
    wsl_requested = Signal()

    def __init__(self, component: _main.Component, log_cb: Callable[[str, str], None], parent=None) -> None:
        super().__init__(parent)
        self.component = component
        self.log_cb = log_cb
        self.worker: Optional[_main.DownloadWorker] = None
        self._extracted_path: Optional[Path] = None
        # 前置运行时（JDK / Erlang）的自动安装队列与下载线程。
        # 队列非空时「启动」按钮显示"准备依赖…"，装完自动继续启动。
        self._prereq_queue: List[Tuple[_main.Component, str]] = []
        self.prereq_worker: Optional[_main.DownloadWorker] = None
        # 「已配置」标签的异步版本号回填状态
        self._status_where = ""
        self._status_version = ""
        self._status_shows_configured = False
        # 多版本胶囊的基础文案：异步版本号回填时要在它后面续（" · <版本>"），
        # 不能落到非多版本那条 "✓ 已配置（…）" 旧文案。
        # **存的是全量原文**（tooltip 源 + 缓存）：短串单独存在 _mv_capsule_short，
        # 两者由 _detect_status_impl 的同一个分支产出。把缓存改成短串会让 tooltip
        # 丢掉版本列表；只改显示不改缓存，异步回填时全量原文又会弹回主文本。
        self._mv_capsule: str = ""
        self._mv_capsule_short: str = ""
        # 多版本胶囊是否用橙色告警态（未对齐 / 被 PATH 更靠前的条目遮蔽）
        self._mv_orange: bool = False
        # 多版本按钮状态：切换/卸载两个按钮要按"当前选中的版本"重算，
        # 而重算有两个触发点（探测之后、下拉框换选中），故把输入缓存在这里。
        self._mv_active: Optional[str] = None
        self._mv_warned: bool = False
        self._mv_installed_set: set = set()
        self._mv_buttons_ready: bool = False
        self._version_worker: Optional["VersionProbeWorker"] = None
        # 本卡片起过的、还没跑完的探测线程（含被顶替掉的那些）。closeEvent 只认得
        # _version_worker 那一条，被顶替的旧线程没人等就是进程级 abort。
        self._probe_workers: List["VersionProbeWorker"] = []
        # 卸载按钮是否被"运行中"锁过：只有锁过才允许在停止后解冻。
        # 未运行时把 btn_uninstall 一律设成可用会顶掉 _detect_status 按"选中版本
        # 装没装"算出的状态，给出一张未安装也能点卸载的卡片（做不到的承诺）。
        self._uninstall_locked_by_launch: bool = False
        # 最近一次启动生成的「启动成功访问页」URL（没有自带控制台的组件用它，
        # 供「打开访问页」按钮与状态栏使用；进程内缓存，登记表里也写了一份）。
        self._launch_page_url: Optional[str] = None

        self.setObjectName("card")
        self.setFrameShape(QFrame.NoFrame)

        # 阴影
        shadow = _main.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(_main.QColor(0, 0, 0, 40))
        self.setGraphicsEffect(shadow)

        # 外部版本接管那组属性**必须**在任何可能提前 return 的渲染代码之前就位。
        # 2026-10-13 的崩溃就是这么来的：这段初始化原先被塞在 _load_icon() 末尾的
        # fallback 分支里，而该分支上方有一条「图标加载成功就 return」的早退；
        # 于是 jdk（外部接管白名单成员，且 assets/component-icons/jdk.png 存在）
        # 一进卡片就跳过初始化，紧接着 __init__ 里的 _detect_status() 调
        # _refresh_external_section() 读 self._external_frame → AttributeError，
        # 主窗口起不来（traceback 停在"正在加载组件 1/87"）。
        # 规矩：**属性初始化不许挂在任何带早退分支的函数里**。
        self._init_external_state()

        self._build_ui()
        self._detect_status()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # 四行结构：顶部（标题+角标）/ 状态行 / 版本行 / 按钮行 / 进度条。
        # 原先版本下拉与按钮混在同一行（mid），塞进 271px 宽的格子必然换行，
        # 卡片高度从 121 涨到 230；拆开 + 缩短文案与 padding 后按钮一行放得下。
        root = _main.QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        # 顶部：图标 + 名称 & 角标
        top = _main.QHBoxLayout()
        top.setSpacing(8)

        # 左侧图标（ICON_BOX_PX 见组件图标一节；渲染尺度 ICON_RENDER_SCALE）
        self.icon_label = _main.QLabel()
        self.icon_label.setFixedSize(_main.ICON_BOX_PX, _main.ICON_BOX_PX)
        self.icon_label.setStyleSheet("""
            background: linear-gradient(135deg, #f5f7fa 0%, #e3e8ef 100%);
            border-radius: 6px;
            border: 1px solid #d8dde6;
        """)
        self.icon_label.setAlignment(_main.Qt.AlignCenter)
        self.icon_label.setPixmap(_main.QPixmap(":/icons/default-icon.svg").scaled(
            28, 28, _main.Qt.KeepAspectRatio, _main.Qt.SmoothTransformation))
        top.addWidget(self.icon_label)

        # 标题 & 角标
        title = _main.QLabel(self.component.display_name)
        title.setObjectName("cardTitle")
        title.setFont(_main.QFont("", 13, _main.QFont.Bold))
        # 标题不许把卡片撑爆：QLabel 的 minimumSizeHint 是**整串文本**的宽度，
        # "Apache RocketMQ" 一渲染就要 255px，加上「可多版本」角标 71px 早就超过
        # 309px 的格子 → 网格里出现横向滚动条（真机 2026-10-08 实测踩中）。
        # 显式把最小宽压到 1，布局才允许压缩它；超宽的部分被裁掉，全名进 tooltip。
        title.setMinimumWidth(1)
        title.setSizePolicy(_main.QSizePolicy.Expanding, _main.QSizePolicy.Preferred)
        title.setToolTip(self.component.display_name)
        top.addWidget(title)
        # 「它是干嘛的」入口（2026-10-12 用户要求）。做成名称后一枚 20px 图标按钮，
        # 不是「详情」文字按钮：格子内部只有 271–309px，按钮行已有 2–5 颗，
        # 再加一颗必然换行、卡片高度会从实测 153px 涨回 ~230px（见卡片瘦身一节）。
        # 也不用悬停 tooltip：详情里有下载地址要能选中复制，tooltip 撑不住。
        self.btn_detail = _main.QPushButton("ℹ")
        self.btn_detail.setObjectName("detailBtn")
        self.btn_detail.setFixedSize(20, 20)
        self.btn_detail.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_detail.setToolTip("看它是干嘛的、装完怎么用")
        self.btn_detail.clicked.connect(self.on_detail_clicked)
        top.addWidget(self.btn_detail)

        # 多版本能力角标：一个版本都没装时，这张卡片跟其它组件长得一样，
        # 用户看不出"它支持同时装几个版本"。做成独立 QLabel 而不是拼进标题文本——
        # display_name 同时是搜索匹配（component_matches）与日志前缀（_log）的真源。
        # 非多版本组件不创建这个节点（不是创建后隐藏），那 19 张卡片保持原样。
        if self.component.multi_version:
            badge = _main.QLabel("可多版本")
            badge.setObjectName("multiVersionBadge")
            # 竖直方向必须 Fixed：同一行里标题的 sizeHint 比它高一点（13pt 粗体），
            # 默认 Preferred 会让角标被拉到与标题等高 —— 带背景的标签一被拉高，
            # 就从紧凑胶囊变成一个大盒子（真机 2026-10-10 用户截图：JDK / Python 卡）。
            badge.setSizePolicy(_main.QSizePolicy.Preferred, _main.QSizePolicy.Fixed)
            badge.setStyleSheet(
                "color:#5c6f82;background:#eef2f6;border-radius:9px;"
                "padding:2px 8px;font-size:11px;font-weight:600;"
            )
            badge.setToolTip(
                "这个组件可以同时安装多个版本。在下拉框里选中某个版本后点"
                "「切换」，就把它设为生效版本（改写 XXX_HOME 与 PATH）；"
                "带绿色对勾的版本表示磁盘上已安装。"
            )
            top.addWidget(badge)
        top.addStretch(1)
        root.addLayout(top)

        # 图标在 _build_ui 末尾统一渲染（_render_icon），这里不再画一次 ——
        # 原先这里和末尾各调了一次，等于每张卡白渲染两遍。

        self.status_label = _main.QLabel("检测中…")
        self.status_label.setObjectName("statusLabel")
        # 同标题的道理：QLabel 的 minimumSizeHint 是整串文本的宽度，状态一长
        # （"✓ 已配置 · 系统安装 · 版本检测中…"）就会把格子撑开，哪怕主文本已经
        # 精简过 —— 不同机器字体/缩放不同，撑到什么程度不一样。显式压掉最小宽，
        # 让布局允许压缩它；超宽的部分裁掉，全量原文本来就在 tooltip 里。
        self.status_label.setMinimumWidth(1)
        self.status_label.setSizePolicy(_main.QSizePolicy.Expanding, _main.QSizePolicy.Preferred)
        # 角标与胶囊都靠左挤在一起会互相裁字，胶囊单独一行（格子内部只有 271px）
        status_row = _main.QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(self.status_label)
        if self.component.launch is not None:
            # 运行状态自己一个小 label：status_label 已有 5 处写点，挤进去会把
            # 多版本胶囊 / 系统安装 那套判定搅浑（R3.9 要求非目标组件零影响）。
            # 原先挂在按钮行尾巴上，按钮行在 271px 里已经排满，故提到状态行。
            self.launch_label = _main.QLabel("")
            self.launch_label.setObjectName("launchLabel")
            # 同上：僵尸登记的原文很长，别让它把格子撑开
            self.launch_label.setMinimumWidth(1)
            self.launch_label.setSizePolicy(_main.QSizePolicy.Expanding, _main.QSizePolicy.Preferred)
            status_row.addWidget(self.launch_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

        # 版本行：版本标签 + 下拉框
        ver = _main.QHBoxLayout()
        ver.setSpacing(8)
        version_label = _main.QLabel("版本")
        version_label.setObjectName("fieldLabel")
        version_label.setFixedWidth(36)
        ver.addWidget(version_label)

        self.version_combo = _main.SearchableComboBox()
        self.version_combo.setObjectName("versionCombo")
        self.version_combo.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self._reload_combo_items()
        # 固定宽度，避免抢占按钮空间。150 是"版本串还能看全"与"按钮行放得下"的折中：
        # 原来的 220 会把按钮行顶出格子。
        self.version_combo.setFixedWidth(150)
        self.version_combo.setFixedHeight(30)
        self.version_combo.setSizePolicy(_main.QSizePolicy.Fixed, _main.QSizePolicy.Fixed)
        # 向导型卡片（ui_action）没有"可选版本"：留一个不可点的占位，
        # 免得用户看到一个空下拉框以为是加载失败。
        if self.component.ui_action:
            self.version_combo.blockSignals(True)
            self.version_combo.clear()
            self.version_combo.addItem("内置安装器")
            self.version_combo.setEnabled(False)
            self.version_combo.blockSignals(False)
        # 换选中就要重算切换/卸载按钮：不连这条，切一次生效版本后按钮会一直灰着
        # （2026-09-30 真机反馈）。只做按钮同步，不重跑探测、不起版本探测子进程。
        self.version_combo.currentIndexChanged.connect(
            lambda *_: self._sync_action_buttons())
        ver.addWidget(self.version_combo)
        ver.addStretch(1)
        root.addLayout(ver)

        # 按钮行：一行放完，不换行
        actions = _main.QHBoxLayout()
        actions.setSpacing(6)

        self.btn_install = _main.QPushButton("安装")
        self.btn_install.setObjectName("primaryBtn")
        self.btn_install.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_install.setFixedHeight(30)
        # 只下载型组件：同一颗主按钮、同一个属性名，但文案是「下载」、槽位是
        # on_download_clicked。不改属性名是因为 _sync_action_buttons、布局与一批用例
        # 都按 btn_install 找它 —— 改名零收益、风险面却是整个卡片。
        if self.component.ui_action == "wsl":
            # 向导型卡片：主按钮既不是下载也不是安装包，而是打开 WslDialog。
            self.btn_install.setText("安装向导")
            self.btn_install.setToolTip(
                "打开 WSL 安装向导：启用 WSL 与虚拟机平台、安装官方运行时、"
                "导入 Ubuntu 24.04。系统功能装完会提示你手动重启 —— 本工具不会替你重启。")
            self.btn_install.clicked.connect(self._open_wsl_wizard)
        elif self.component.download_only:
            if self.component.official_page_only:
                # 更弱的一档：没有可直链的安装包 → 给「官网下载」，点开浏览器自己去下。
                # 文案要说清"本工具不代下不代装"，否则用户会以为点了就开始下。
                self.btn_install.setText("官网下载")
                tip = ("这个组件官方没有可直接下载的安装包链接（只给网页入口 / 需要用包管理器装）——"
                       "点一下会在浏览器里打开它的官网，请在那里自行下载安装。"
                       "本工具不代下、不代装、不代跑安装程序")
                if self.component.data_note:
                    tip += "\n" + self.component.data_note
                self.btn_install.setToolTip(tip)
                self.btn_install.clicked.connect(self.on_open_official_page_clicked)
            else:
                # 有两种产物可选时按钮写成「下载 ▾」：不点就不知道有得挑，而选错一次
                # 是重下 1.5 GB。▾ 只是提示"这里会弹菜单"，真正的挑选在 on_download_clicked 里。
                multi = any(len(cv.artifacts) > 1 for cv in self.component.versions)
                self.btn_install.setText("下载 ▾" if multi else "下载")
                tip = "下载官方安装包到你选的目录。本工具不解压、不安装、不配置环境变量"
                if multi:
                    tip += "\n这个版本官方同时提供 exe 安装器与 zip 便携包，点了会让你选（带体积）"
                if self.component.data_note:
                    # data_note 平时是靠**卸载确认框**露出来的，而这批组件根本没有卸载按钮 ——
                    # 不另找地方挂上去，"不含授权"那句就只存在于源码注释里了。
                    tip += "\n" + self.component.data_note
                self.btn_install.setToolTip(tip)
                self.btn_install.clicked.connect(self.on_download_clicked)
        else:
            self.btn_install.clicked.connect(self.on_install_clicked)
        actions.addWidget(self.btn_install)

        # 「配置环境变量 / 切换为生效版本」→「切换」：格子只有 271px，
        # 两种旧叫法都太长；多版本语义由 tooltip 承载（下面 _sync_action_buttons 里）。
        # 只下载型组件**不创建**这个节点（不是创建后隐藏，同「可多版本」角标的纪律）：
        # 它没有"生效版本"可切，留着按钮等于给用户一个点了会写注册表的入口。
        if not self.component.download_only:
            self.btn_configure = _main.QPushButton("切换")
            self.btn_configure.setObjectName("secondaryBtn")
            self.btn_configure.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
            self.btn_configure.setFixedHeight(30)
            self.btn_configure.clicked.connect(self.on_configure_clicked)
            actions.addWidget(self.btn_configure)

        self.btn_cancel = _main.QPushButton("取消")
        self.btn_cancel.setObjectName("dangerBtn")
        self.btn_cancel.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self.btn_cancel.setFixedHeight(30)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)  # 默认隐藏；开始下载时才显示
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        actions.addWidget(self.btn_cancel)

        # 只下载型组件**不创建**卸载节点（不是创建后置 None/隐藏）：
        # 属性压根不存在，任何误用它的代码都会当场 AttributeError 而不是静默跳过。
        if not self.component.download_only:
            self.btn_uninstall = _main.QPushButton("卸载")
            self.btn_uninstall.setObjectName("dangerBtn")
            self.btn_uninstall.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
            self.btn_uninstall.setFixedHeight(30)
            # 默认禁用，待 _detect_status 检测到已安装或有本地下载时才启用
            self.btn_uninstall.setEnabled(False)
            self.btn_uninstall.setToolTip("删除已安装的版本、清理 XXX_HOME 与 PATH")
            self.btn_uninstall.clicked.connect(self.on_uninstall_clicked)
            actions.addWidget(self.btn_uninstall)

        # 启动相关按钮：只有登记了启动描述符的组件才有（LAUNCH_KEYS，本期只有 Jenkins）
        self.launch_worker: Optional[_main.LaunchWorker] = None
        if self.component.launch is not None:
            # 启动/停止合并成**一个**按钮（2026-10-06 用户要求）：
            # 未运行时显示「启动」，运行中变成「停止」，点了就做对应的事。
            #
            # 为什么不用两个按钮切换显隐：按钮的位置会变，用户的眼睛要重新找一遍。
            # 2026-10-06 用户连续三次反馈"没有停止按钮"—— 按钮其实一直好着
            # （可见可用、文本"停止"），问题在于它与「启动」并排、
            # 运行状态时那一格才亮起来，看起来就像"多出来的按钮没出现"。
            # 合成一个之后：按钮永远在那儿，状态直接写在按钮文字上，
            # 不用找、不用猜。
            #
            # 文案**不许瘦身**：_running_per_ui() 读它判断是否在运行。
            self.btn_start = _main.QPushButton("启动")
            self.btn_start.setObjectName("primaryBtn")
            self.btn_start.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
            self.btn_start.setFixedHeight(30)
            self.btn_start.clicked.connect(self.on_start_stop_clicked)
            actions.addWidget(self.btn_start)
            # 刻意**不保留** `self.btn_stop`：合并按钮后没有第二个 widget，
            # 留一个同名别名会让读代码的人以为界面上有两个按钮。
            # 旧代码里 `btn_stop.isEnabled()` 那个"是否在运行"的判据，
            # 改为读按钮文字——见 _running_per_ui()。
            self.btn_console = _main.QPushButton("控制台")
            # 原先没有 objectName → 三条 QSS 全部匹配不到它，拿系统默认样式，
            # 实测比旁边几颗按钮宽一圈（sizeHint 恒 80，同长度的「安装」只占 42）。
            self.btn_console.setObjectName("secondaryBtn")
            self.btn_console.setFixedHeight(30)
            self.btn_console.clicked.connect(self.on_console_clicked)
            self.btn_console.setEnabled(False)
            actions.addWidget(self.btn_console)

        actions.addStretch(1)  # 右侧留空，避免按钮被拉伸
        root.addLayout(actions)

        # 底部：进度条
        # 高度保持 14：setTextVisible(True) 的百分比在 8px 下必然被裁切，
        # 且圆角 6px 会大于半高 4px。
        self.progress = _main.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        # 卡片左上角的官方图标（2026-10-13 新增）。纯渲染，无副作用、无早退。
        self._render_icon()

        # ---- 「系统里检测到的版本」折叠区＋还原按钮（设计 §6）----
        # 只给白名单里的 7 个组件建（不是建了再隐藏）：其余卡片保持原样，
        # R3.9 那句"非目标组件文案与按钮零变化"才守得住。
        # 必须排在 _build_ui 末尾：_build_external_section 会往布局尾部塞一个
        # 撑高的 stretch，放在进度条之前会被后面的控件顶到折叠区上面去。
        if _main.supports_external_takeover(self.component):
            self._build_external_section(root)

        # 末尾必须有一个 stretch：网格会把同一行的卡片拉成等高，内容少的卡片就
        # 多出一段高度。没有这个占位的话，那段高度会被**能长大的控件**吃掉 ——
        # statusLabel 的纵向策略是 Preferred，首当其冲被拉成一个空白大色块
        # （真机截图：Ant / bat 卡的「未安装」「已装 …」被撑成大方块，
        #  而同一行内容更多的 Maven 卡是紧凑一行）。
        #
        # ⚠ 2026-10-15 修：这一行原先写在 `_build_external_section()` 里，也就是
        # **只有那 7 个外部接管组件**（jdk / python / node / go / maven / gradle / bun）
        # 才有，其余 125 张卡一张都没有。旧顺序下恰好没排出"高矮混排"的一行，
        # 所以一直没露出来；当天给 Tab 加了 a→z 排序（R22）后，高卡（Maven 238px）
        # 与矮卡（Ant / bat 178px）排进同一行，立刻变成肉眼可见的大色块。
        # **排序只是触发器，缺陷本身一直都在。**
        #
        # 无条件加在 `_build_ui` 末尾，位置与那 7 张卡原来完全一致（它们也是
        # external 区之后才加），所以对既有卡片零行为变化。
        root.addStretch(1)

    def _init_external_state(self) -> None:
        """初始化外部版本接管那组实例属性（状态，不碰任何控件）。

        由 __init__ 在 _build_ui() **之前**调用。控件本身在 _build_ui 末尾
        通过 _build_external_section() 创建；这里只把"还没建"这件事记成
        None，好让 _refresh_external_section() 在折叠区尚未存在的组件上
        也能安全空转。

        单独拆出来是为了守住一条规矩：**属性初始化不许写在带早退分支的
        函数里**。2026-10-13 的启动崩溃就是这么来的（详见 __init__ 里那段注释）。
        """
        self._external_candidates: List["DiscoveredVersion"] = []
        self._external_scanned = False
        self._external_expanded = False
        self._external_worker: Optional["ExternalDiscoveryWorker"] = None
        self._external_rows: List[_main.QWidget] = []
        self._restore_btn: Optional[_main.QPushButton] = None
        self._external_frame: Optional[QFrame] = None
        self._external_toggle: Optional[_main.QPushButton] = None
        self._external_body: Optional[_main.QWidget] = None

    def _render_icon(self) -> None:
        """在卡片左上角渲染该组件的官网图标，取不到就退回分类色块。

        纯渲染：这个方法不建任何后续逻辑依赖的属性，也不提前 return 后还要
        有人接着干活 —— 渲染成功与否对卡片的其余部分没有任何影响。
        职责拆分：
          · `load_component_icon_pixmap()` 负责"找到并栅格化"，全部防错都在那边
          · 本方法只负责"贴上去，贴不上就画色块"
        """
        key = self.component.key
        pixmap = _main.load_component_icon_pixmap(key, _main.ICON_BOX_PX * _main.ICON_RENDER_SCALE)
        if pixmap is not None:
            # 不要再 scaled()：load_component_icon_pixmap 返回的已经是
            # ICON_BOX_PX 逻辑尺寸、ICON_RENDER_SCALE 倍密度的成品。
            # 二次缩放会把它压成 64 逻辑像素 = 逻辑尺寸的 2 倍，
            # QLabel 32x32 的槽位放不下就被裁掉一角 —— 界面看到的是
            # "图标缺了一块"（2026-10-14 用户截图就是这个现象）。
            self.icon_label.setPixmap(pixmap)
            return

        # fallback: 使用默认色块（按分类显示不同颜色）
        # ⚠ 这个字典的**键是分类名字符串**，2026-10-14 分类改名时它必须跟着改 ——
        # 键对不上不会报错，只会安静地落到下面的兜底灰色 (#757575)，那个 Tab 的
        # 所有无图标组件会一起变成灰块。所以这里用 CAT_* 常量而不是裸字符串。
        category_map = {
            _main.CAT_ENV: ("#4CAF50", "#43A047"),       # 绿色系（编程语言、SDK 等）
            _main.CAT_SERVER: ("#2196F3", "#1976D2"),     # 蓝色系（数据库、服务器等）
            _main.CAT_LAUNCH: ("#FF9800", "#F57C00"),     # 橙色系（服务组件）
            _main.CAT_TOOL: ("#9C27B0", "#7B1FA2"),       # 紫色系（IDE、客户端等）
        }
        cat = _main.COMPONENT_CATEGORY_OF.get(key, _main.CAT_TOOL)
        grad_from, grad_to = category_map.get(cat, ("#757575", "#424242"))

        self.icon_label.setStyleSheet(f"""
            background: linear-gradient(135deg, {grad_from} 0%, {grad_to} 100%);
            border-radius: 6px;
            border: 1px solid #d8dde6;
        """)
        self.icon_label.setText(key[:3].upper())
        self.icon_label.setAlignment(_main.Qt.AlignCenter)
        self.icon_label.setFont(_main.QFont("", 10, _main.QFont.Bold))
        self.icon_label.setForegroundRole(_main.QPalette.Text)

    # ------------------------------------------------------------------
    # 「系统里检测到的版本」折叠区（§6）
    # ------------------------------------------------------------------
    def _build_external_section(self, root: _main.QVBoxLayout) -> None:
        """卡片底部的折叠区 + 常驻的「还原到我之前的设置」。

        默认收起且整块隐藏：格子内部只有 271px，展开就是好几行；绝大多数机器上
        这里本来就是空的，不该白占地方。首次展开时才去扫（要真跑版本命令）。
        """
        self._external_frame = QFrame()
        self._external_frame.setObjectName("externalBox")
        box = _main.QVBoxLayout(self._external_frame)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)

        self._external_toggle = _main.QPushButton("▸ 系统里检测到的版本")
        self._external_toggle.setObjectName("externalToggle")
        self._external_toggle.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self._external_toggle.setFixedHeight(24)
        # 同卡片里所有 QLabel/QPushButton 的道理：不压掉最小宽，长路径会把格子撑开
        self._external_toggle.setMinimumWidth(1)
        self._external_toggle.setSizePolicy(_main.QSizePolicy.Expanding,
                                            _main.QSizePolicy.Fixed)
        self._external_toggle.setToolTip(
            "扫描本机已安装的这个组件的其它版本（环境变量、PATH、注册表里的登记）。\n"
            "扫描只读，不会改动任何设置；点开后才开始扫描。")
        self._external_toggle.clicked.connect(self._toggle_external_section)
        box.addWidget(self._external_toggle)

        self._external_body = _main.QWidget()
        self._external_body_layout = _main.QVBoxLayout(self._external_body)
        self._external_body_layout.setContentsMargins(2, 0, 2, 0)
        self._external_body_layout.setSpacing(3)
        self._external_body.setVisible(False)
        box.addWidget(self._external_body)

        self._restore_btn = _main.QPushButton("↩ 还原到我之前的设置")
        self._restore_btn.setObjectName("restoreBtn")
        self._restore_btn.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        self._restore_btn.setFixedHeight(26)
        self._restore_btn.setMinimumWidth(1)
        self._restore_btn.setVisible(False)
        self._restore_btn.clicked.connect(self.on_restore_external_clicked)
        box.addWidget(self._restore_btn)

        self._external_frame.setVisible(False)
        root.addWidget(self._external_frame)

    def _toggle_external_section(self) -> None:
        self._external_expanded = not self._external_expanded
        self._external_body.setVisible(self._external_expanded)
        self._external_toggle.setText(
            ("▾ " if self._external_expanded else "▸ ") + self._external_toggle_text())
        if self._external_expanded and not self._external_scanned:
            self._start_external_discovery()

    def _external_toggle_text(self) -> str:
        n = len(self._external_candidates)
        return f"系统里检测到的版本（{n}）" if self._external_scanned \
            else "系统里检测到的版本"

    def _start_external_discovery(self) -> None:
        self._external_toggle.setText("▾ 正在扫描…")
        self._external_toggle.setEnabled(False)
        self._external_worker = _main.ExternalDiscoveryWorker(self.component, self)
        self._external_worker.done.connect(self._on_external_discovered)
        self._external_worker.start()

    def _on_external_discovered(self, cands) -> None:
        self._external_worker = None
        self._external_scanned = True
        self._external_candidates = [c for c in cands if c.source != "workspace"]
        self._external_toggle.setEnabled(True)
        self._external_toggle.setText(
            ("▾ " if self._external_expanded else "▸ ") + self._external_toggle_text())
        self._refresh_external_section()

    def _refresh_external_section(self) -> None:
        """按当前状态重画折叠区与还原按钮。"""
        if self._external_frame is None:
            return
        takeover = (_main.load_takeover_map().get(self.component.key)
                    if _main.supports_external_takeover(self.component) else None)
        # R3.19：为工作区版本提权改过系统变量时，还原按钮同样要常驻 —— 用户点「切换」
        # 被系统级条目压住、同意了那次提权，之后就必须有个一键回到原样的出口。
        machine_fix = (_main.load_machine_fix_map().get(self.component.key)
                       if _main.supports_external_takeover(self.component) else None)

        # 还原按钮：只在"确实动过"时常驻（§6）。重启后仍然出现 —— 依据是
        # config.json 里的登记，不是本次运行的内存状态。
        if self._restore_btn is not None:
            self._restore_btn.setVisible(bool(takeover or machine_fix))
            if takeover:
                snap = takeover.get("snapshot") or {}
                hives = []
                if snap.get("HKCU"):
                    hives.append("HKCU\\Environment")
                if snap.get("HKLM"):
                    hives.append("HKLM\\SYSTEM\\...\\Environment")
                keys = sorted({k for h in snap.values() if isinstance(h, dict)
                               for k in h})
                self._restore_btn.setToolTip(
                    f"当前生效的是系统里那个 {takeover.get('version')}"
                    f"（{takeover.get('home')}）。\n"
                    f"点这里按接管前的原文写回：{'、'.join(hives) or '（无）'}"
                    f"，键：{'、'.join(keys) or '（无）'}。\n"
                    "需要管理员权限时会再弹一次授权。")
            elif machine_fix:
                snap = machine_fix.get("snapshot") or {}
                keys = sorted(k for k in (snap.get("HKLM") or {}))
                self._restore_btn.setToolTip(
                    f"为了让工作区里的 {machine_fix.get('version')} 生效，"
                    "本工具在系统 PATH 最前插了一条。\n"
                    f"点这里按改动前的原文写回：HKLM\\SYSTEM\\...\\Environment，"
                    f"键：{'、'.join(keys) or '（无）'}。\n"
                    "还原后命令行会回到改动前的那一份（也就是你自己装的那个），"
                    "本工具装的版本仍在，可用下拉框再切回来。\n"
                    "需要管理员权限时会再弹一次授权。")

        # 折叠区整块：有外部候选 or 有接管/提权登记的残留时才出现
        show = bool(self._external_candidates) or bool(takeover or machine_fix)
        self._external_frame.setVisible(show)
        if not show:
            return

        # 清空上一轮：takeAt 之后布局就不管它了，但 widget 的 parent 与几何都还在，
        # 延迟删除执行前它会一直渲染在原地（项目记忆里踩过的"幽灵"）→ 先 hide、
        # 再摘 parent、最后 deleteLater。
        while self._external_body_layout.count():
            item = self._external_body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._external_rows = []

        if not self._external_candidates:
            hint = _main.QLabel("没有扫描到外部安装的版本")
            hint.setObjectName("externalHint")
            hint.setMinimumWidth(1)
            self._external_body_layout.addWidget(hint)
            self._external_rows.append(hint)
            return

        for dv in self._external_candidates:
            row = self._make_external_row(dv, takeover)
            self._external_body_layout.addWidget(row)
            self._external_rows.append(row)

    def _make_external_row(self, dv: "DiscoveredVersion",
                           takeover: Optional[dict]) -> _main.QWidget:
        """一行外部版本：版本号 / 完整路径 / 「当前在用」标记 + 「切过去」。

        路径**换行显示**而不是省略号：格子只有 271px，而用户就是靠这段路径
        认出"这是我装在 D 盘那个"。裁掉一半等于把这一行的全部信息量丢掉一半，
        所以宁可让卡片高一点（折叠区本来就是用户主动展开的）。
        """
        row = QFrame()
        row.setObjectName("externalRow")
        outer = _main.QVBoxLayout(row)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(0)

        in_use = bool(takeover) and _main.EnvManager._same_path(
            str(dv.home), str(takeover.get("home") or ""))
        head = _main.QHBoxLayout()
        head.setSpacing(6)
        title = _main.QLabel(f"{dv.version}" + ("　← 当前在用" if in_use else ""))
        title.setObjectName("externalVersion")
        title.setMinimumWidth(1)
        title.setSizePolicy(_main.QSizePolicy.Expanding, _main.QSizePolicy.Preferred)
        head.addWidget(title)

        btn = _main.QPushButton("已生效" if in_use else "切过去")
        btn.setObjectName("secondaryBtn")
        btn.setCursor(_main.QCursor(_main.Qt.PointingHandCursor))
        btn.setFixedHeight(24)
        btn.setEnabled(not in_use)
        btn.setToolTip("已生效" if in_use else
                       f"把这个版本设为生效版本（会改写 "
                       f"{self.component.env_var or 'PATH'}，必要时需要管理员权限）")
        btn.clicked.connect(lambda _=False, d=dv: self.on_switch_external(d))
        head.addWidget(btn)
        outer.addLayout(head)

        # 路径单独一行、占满整行宽：271px 的格子里它本来就放不下，
        # 挤在按钮旁边只会两败俱伤（实测按钮会压在路径文字上）。
        path_label = _main.QLabel(str(dv.home))
        path_label.setObjectName("externalPath")
        path_label.setMinimumWidth(1)
        path_label.setWordWrap(True)
        path_label.setSizePolicy(_main.QSizePolicy.Expanding, _main.QSizePolicy.Minimum)
        path_label.setToolTip(f"{dv.version}\n{dv.home}\n发现来源：{dv.source}")
        outer.addWidget(path_label)
        return row

    def on_switch_external(self, dv: "DiscoveredVersion") -> None:
        """把生效版本切到这个外部安装（§5.3 → 需要时 §5.4 提权）。"""
        def _sink(text: str) -> None:
            low = str(text)
            level = ("error" if ("失败" in low or "未通过" in low or "未完成" in low)
                     else "warn" if ("取消" in low or "未能" in low or "仍" in low)
                     else "info")
            self._log(level, low)

        self._log("info", f"准备切换到系统里那个 {dv.version}（{dv.home}）…")
        res = _main.switch_to_external_version(
            self.component, dv,
            confirm_machine=self._confirm_machine_takeover, log=_sink)
        # 步骤已由 _sink 逐条实时打出，不再回放 res["steps"]（否则每条日志两遍）。
        if res.get("ok"):
            self._log("ok", f"已切换到系统里的 {dv.version}；"
                            "新开的终端/IDE 才会读到新值")
            self._log_verification_hint(time.time())
        elif res.get("verdict") == "cancelled":
            self._log("warn", "已取消，未做任何改动")
        else:
            self._log("error", str(res.get("error") or "切换未成功"))
        self._refresh_external_section()
        self._detect_status()
        self._sync_action_buttons()

    def _confirm_machine_takeover(self, plan: dict) -> bool:
        """提权前的确认框：逐条列出要改什么、改成什么、原来是什么（§5.4 明文要求）。

        这里必须是"用户点了确定才动系统变量"—— 它改的是整机所有程序看到的环境。
        """
        env_var = str(plan.get("env_var") or "")
        add_entry = str(plan.get("add_entry") or "")
        before_path, before_type = _main.read_machine_env_raw("Path")
        before_var, _vt = _main.read_machine_env_raw(env_var) if env_var else (None, "")
        lines = [
            f"要让命令行真正用上这个版本，需要修改「系统变量」（需要管理员权限）：",
            "",
            f"· 系统 PATH 最前面插入：",
            f"    {add_entry}",
        ]
        if env_var:
            lines += ["", f"· 系统变量 {env_var}：",
                      f"    现在：{before_var or '（未设置）'}",
                      f"    改为：{plan.get('home')}"]
        lines += [
            "",
            f"· 其余原有条目（含 {before_type or 'REG_EXPAND_SZ'} 里的 %VAR% 占位符）"
            f"逐字保留，不删不改；",
            "· 改动前的原文会先存一份快照，卡片上随时可以「还原到我之前的设置」。",
            "",
            "继续吗？（会弹出 Windows 的权限确认窗口）",
        ]
        box = _main.QMessageBox(self)
        box.setIcon(_main.QMessageBox.Warning)
        box.setWindowTitle("需要管理员权限")
        box.setText("\n".join(lines))
        yes = box.addButton("继续（修改系统变量）", _main.QMessageBox.AcceptRole)
        box.addButton("取消", _main.QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def on_restore_external_clicked(self) -> None:
        """「还原到我之前的设置」：按快照把动过的变量写回原文。

        R3.19 之后这里要能收两笔账，顺序固定：先还「为工作区版本提权改的系统变量」，
        再还「接管的外部版本」。两者在稳态里不会并存（切工作区版本前已先还原），
        真碰到并存时全还掉才是"回到我之前的样子"。
        """
        def _sink(text: str) -> None:
            level = ("error" if ("失败" in str(text) or "未完成" in str(text))
                     else "info")
            self._log(level, str(text))

        did = False
        if _main.has_machine_fix(self.component):
            fix = _main.revert_machine_fix(self.component, log=_sink)
            if fix.get("ok"):
                did = True
            else:
                self._log("error", "系统变量还原未完成："
                          + str(fix.get("error") or ""))

        if _main.has_external_takeover(self.component):
            res = _main.revert_external_version(self.component, log=_sink)
            if res.get("ok"):
                did = True
            elif res.get("cancelled"):
                self._log("warn", "已取消还原，设置未改动")
            else:
                self._log("error", str(res.get("error") or "还原未完成"))

        if did:
            self._log("ok", "已还原到我之前的设置，新开的终端才会读到")
        self._refresh_external_section()
        self._detect_status()

    # ------------------------------------------------------------------
    # 状态文案：主文本给短串，全量详情进 tooltip
    # ------------------------------------------------------------------
    def _set_status(self, full: str, short: str) -> None:
        """状态行的唯一写入口：主文本用短串，全量原文进 tooltip。

        格子内部只有 271px，而 PySide6 的 QLabel 没有 setElideMode（超宽是直接
        clip，不是省略号），所以长文案只能"主文本写结论、tooltip 写全文"。
        两者**每次都要一起设置**：状态切换时只 setText 会把上一轮的详情留在
        悬停提示里，变成一句已经没有依据的旧话。
        """
        self.status_label.setText(short)
        self.status_label.setToolTip(full)

    def _set_launch(self, full: str, short: str) -> None:
        """运行状态 label 的唯一写入口，同 _set_status()。"""
        self.launch_label.setText(short)
        self.launch_label.setToolTip(full)

    # ------------------------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        self.log_cb(level, f"[{self.component.display_name}] {msg}")

    # ------------------------------------------------------------------
    # 一键启动：卡片只负责"读状态 → 摆按钮 → 把动作丢进线程"，判定全在 ServiceManager。
    def _launch_status(self):
        return _main.SERVICE_MANAGER.status(self.component.key, self.component)

    def _refresh_launch_state(self) -> None:
        """按端口实况刷新按钮与运行状态 label（不碰 status_label 那枚状态胶囊）。
        本方法只读，一次都不许拉起进程。"""
        if self.component.launch is None:
            return
        try:
            self._refresh_launch_state_impl()
        finally:
            # 状态一变就通知主窗重算 Tab 上的运行标记 `●`。放在 finally 里：
            # 刷新过程中抛异常时标记也不该留在旧值上。
            self._notify_tabs_running_changed()

    def _notify_tabs_running_changed(self) -> None:
        """告诉主窗"本卡片是否在运行"变了，好去刷新 Tab 标题上的 `●`。

        用 getattr 逐层探：卡片可能在窗口还没建完时就被刷新（构造期测试），
        那时主窗上还没有 _mark_running_tabs，直接跳过而不是炸掉整个刷新。
        """
        try:
            win = self.window()
        except Exception:       # 顶层 C++ 对象已销毁（关窗途中）
            return
        mark = getattr(win, "_mark_running_tabs", None)
        if mark is None:
            return
        try:
            mark()
        except Exception:       # 主窗可能正处在关窗流程里，标记刷不上不影响功能
            pass

    def _running_per_ui(self) -> bool:
        """**界面上**认定的"在运行"：按钮文字是不是「停止」。

        为什么读文字而不读 enabled：合并按钮后按钮在运行中也要可点（它就是停止按钮），
        enabled 已经不能区分状态了。而按钮文字就是用户看到的状态本身 ——
        读它等于"用户以为的"与"程序认为的"永远一致。
        Tab 上的运行标记、跳页逻辑都用它。
        """
        return self.btn_start.text().rstrip("… ") == "停止"

    def _refresh_launch_state_impl(self) -> None:
        st = self._launch_status()
        running = st.state == "running"
        # 磁盘上没有任何已安装版本时，「启动」就**该是灰的**（2026-10-10 用户给的
        # 两个方案里选这个）：与"选中版本已装则置灰「安装」"是同一条设计语言 ——
        # 做不到的事不给点。另一个方案（点了再弹"没装"提示）被否掉的实测理由：
        # 以前点下去会先弹一个**端口与风险确认框**，用户确认完才在日志里看到"没装"，
        # 等于先骗他做一次决定。
        launchable = _main.resolve_launch_version(self.component) is not None
        self.btn_start.setEnabled(self.launch_worker is None and (running or launchable))
        # **每个可启停组件都有一个能打开的地址**（2026-10-08 用户要求）：
        #   自带 Web 界面 → 按钮文字「控制台」，指向它自己的页面；
        #   协议端口型（kafka/rocketmq/rabbitmq）→ 文字「访问页」，
        #   指向工具自带的「启动成功」页（卡片销毁前若还留着上次的 URL 就用它，
        #   否则由 _has_console() 从登记表里读）。
        spec = getattr(self.component, "launch", None)
        own_page = spec is not None and bool(spec.console_path)
        self.btn_console.setText("控制台" if own_page else "访问页")
        # 按钮**常驻**（2026-10-10 用户报「有些怎么没有控制台按钮」）：以前停止状态下
        # `console_path` 为 None 的组件（kafka / rocketmq / rabbitmq）会被整个藏掉 ——
        # 它们只有运行期间由本工具生成的那一页"启动成功 / 该怎么访问"，于是没在跑的时候
        # 按钮消失，用户读成"这个组件少了一个功能"。现在只要可启停就留着，
        # 点不动的原因写进 tooltip（禁用态不解释，就是让用户猜）。
        self.btn_console.setVisible(spec is not None)
        self.btn_console.setEnabled(running)
        self.btn_console.setToolTip(
            "" if running else
            f"启动 {self.component.display_name} 之后才能打开"
            + ("它自己的页面" if own_page else "本工具为它生成的访问说明页"))
        # 按钮文字就是状态本身：运行中显示「停止」，否则显示「启动」。
        # 正在起/停的过渡态（"启动中…"/"停止中…"）不能被这一行盖掉——
        # 那是用户点下去之后的即时反馈，被立刻改回「启动」会让人以为没点上。
        if self.launch_worker is None:
            if running:
                self.btn_start.setText("停止")
                self.btn_start.setObjectName("dangerBtn")
                self.btn_start.setToolTip(
                    f"停止 {self.component.display_name}（端口 {st.record.port}）")
            else:
                self.btn_start.setText("启动")
                self.btn_start.setObjectName("primaryBtn")
                self.btn_start.setToolTip(
                    f"启动 {self.component.display_name}（端口 {self.component.launch.main_port}）"
                    if launchable else
                    f"磁盘上还没有 {self.component.display_name} 的已安装版本，"
                    "先点「安装」装一个，或把版本切到已装的那个，才能启动")
            # 换objectName 后要重刷 QSS，否则配色停留在上一个状态。
            self.btn_start.style().unpolish(self.btn_start)
            self.btn_start.style().polish(self.btn_start)
        if running:
            # 「无网页控制台」写在标签里（2026-10-06 用户报「显示启动成功实际无法访问」）：
            # 服务是好的，只是没有页面可点。把这句话摆在这儿，用户就不会去找
            # 那个不存在的控制台入口、也不会以为服务坏了。
            tail = "" if self._has_console() else " · 无网页控制台"
            svc_tail = ""
            if getattr(st.record, "service_name", ""):
                svc_tail = f" · 服务 {st.record.service_name}"
            self._set_launch(f"● 运行中{svc_tail} · 端口 {st.record.port}{tail}",
                             f"● 运行中 {st.record.port}")
            # 运行中禁止卸载：边跑边删目录会把正在写的日志和数据留在半删状态
            self.btn_uninstall.setEnabled(False)
            self.btn_uninstall.setToolTip("请先停止运行中的 %s 再卸载" % self.component.display_name)
            self._uninstall_locked_by_launch = True
        else:
            if st.state == "broken":
                self._set_launch(
                    "⚠ 服务损坏：服务还在，但它指向的文件已被删除。"
                    "点「卸载」可先删掉这个服务，再重装这个版本。",
                    "⚠ 服务损坏")
            elif st.state == "zombie":
                # 僵尸登记要看得见：否则"上次崩了、登记还留着"和"干净地停过"长得一模一样。
                # 文案只承诺 start() 真会做的事：它不看旧 PID，直接起一个新进程并覆盖这条登记
                # —— 万一是"卡住但还活着"的旧进程，那个进程归 adopt/手工处理，别说成"接管"。
                self._set_launch(
                    f"⚠ 上次运行的残留登记（端口 {st.record.port} 没在听），"
                    f"再点启动会重新起一个并覆盖这条登记",
                    f"⚠ 残留登记 · 端口 {st.record.port}")
            else:
                self._set_launch("", "")
            # 只解冻自己被锁过的那次：卸载按钮的可用性本来由 _detect_status /
            # _sync_action_buttons 按"选中版本装没装"判定，无条件点亮会给出
            # 一张未安装也能点卸载的卡片。
            if self._uninstall_locked_by_launch:
                self._uninstall_locked_by_launch = False
                self.btn_uninstall.setEnabled(True)
                self.btn_uninstall.setToolTip("删除已安装的版本、清理 XXX_HOME 与 PATH")

    def on_start_clicked(self) -> None:
        spec = self.component.launch
        # 按钮平时就是灰的（见 _refresh_launch_state_impl 的 launchable 判据），
        # 这一道是兜底：状态是异步刷的，磁盘可能在两次刷新之间被外部删掉。
        # **必须排在自动装前置依赖之前** —— 否则一个没装的组件会先被拉去装一个 JDK，
        # 装完再告诉他"没装"，白折腾一遍网络。
        if _main.resolve_launch_version(self.component) is None:
            self._log("warn",
                      f"磁盘上还没有 {self.component.display_name} 的已安装版本，"
                      "先点「安装」装一个，或把版本切到已装的那个，再点启动。")
            return
        # 「开机就能用」：缺前置运行时（JDK / Erlang）时**先自动装好再启动**，
        # 而不是弹一句"请先装一个 JDK"把活儿交回给用户。
        missing = _main.prereq_components(self.component, _main.component_registry())
        if missing:
            self._install_missing_prereqs(missing)
            return
        self._do_start()

    def _do_start(self) -> None:
        """真正开始启动（前置依赖已就位时走这里）。"""
        spec = self.component.launch
        if _main.service_spec_for(self.component) is not None:
            self._do_service_start()
            return
        # 端口提示必须与实际行为一致。2026-10-06 起策略是"不平移、被占就结束占用者"，
        # 这里原来还写着"被占用时会自动往后找空闲口"—— 确认框里说假话比不说更糟：
        # 用户以为端口会变，于是按自己的预期去连那个并不存在的端口。
        port_line = f"端口：{spec.main_port}"
        if spec.port_offsets:
            port_line += f"（派生口 {', '.join(str(spec.main_port + int(o)) for o in spec.port_offsets)}）"
        if spec.extra_ports:
            port_line += f"；独立口 {', '.join(str(p) for p in spec.extra_ports)}"
        port_line += "\n（端口被占用时会结束占用它的进程，不会自动换端口）"
        reply = _main.QMessageBox.question(
            self, "确认启动 %s" % self.component.display_name,
            "%s\n%s\n\n确认启动？" % (port_line, spec.risk_note),
            _main.QMessageBox.Yes | _main.QMessageBox.No, _main.QMessageBox.Yes)
        if reply != _main.QMessageBox.Yes:
            return
        self.btn_start.setEnabled(False)
        self.btn_start.setText("启动中…")
        # parent=self：worker 归卡片的 Qt 对象树持有，run() 还没回来时不依赖
        # launch_worker 这一个引用吊命；结束后由 _on_launch_worker_done deleteLater 收回。
        self.launch_worker = _main.LaunchWorker("start", self.component,
                                          _main.component_registry(), _main.SERVICE_MANAGER,
                                          parent=self)
        self.launch_worker.started_ok.connect(self._on_launch_ok)
        self.launch_worker.failed.connect(self._on_launch_failed)
        self.launch_worker.notes.connect(self._on_launch_notes)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    def _do_service_start(self) -> None:
        """服务模式的启动确认：先讲清"注册成服务、手动启动、要一次 UAC"，再收密码。"""
        comp = self.component
        spec = _main.service_spec_for(comp)
        version = self._current_version().version
        name = _main.service_name_for(spec, version)
        missing = _main.service_required_missing(comp, version)
        if missing:
            _main.QMessageBox.warning(
                self, "缺少服务组件",
                f"{comp.display_name} {version} 缺少服务组件所需的文件：\n{'、'.join(missing)}\n\n"
                f"这个包不是带服务组件的完整版。请先卸载这个版本，重新安装正确的包。")
            return
        info = _main.service_info(comp, version)
        if info.state == _main.SERVICE_BROKEN:
            _main.QMessageBox.warning(
                self, "服务损坏",
                f"服务 {name} 还在，但它指向的可执行文件已经不存在了。\n\n"
                f"请点「卸载」先删掉这个服务（版本目录也会一起清理），再重新安装 {version}。")
            return
        peers = _main.peer_running_services(comp, exclude_version=version)
        if peers and not info.running:
            names = "、".join(p.name for p in peers)
            _main.QMessageBox.warning(
                self, "另一个版本的服务在运行",
                f"{names} 正在运行。同一端口同一时间只能跑一个版本：\n"
                f"先在下拉框切到那个版本并点「停止」，再启动 {version}。")
            return
        mode = ("服务已注册，直接启动。" if info.exists else
                "服务还没注册：会先请求一次管理员权限把它注册成 Windows 服务。")
        reply = _main.QMessageBox.question(
            self, f"启动 {comp.display_name} {version}",
            f"服务名：{name}\n启动类型：手动（不会开机自启）\n"
            f"端口：{_main.service_port(comp)}\n{mode}\n\n"
            f"注册服务需要一次管理员权限（UAC）。启动后关掉本工具、关掉控制台，"
            f"服务都会继续运行，也可以在 services.msc 里看到它。\n\n确认启动？",
            _main.QMessageBox.Yes | _main.QMessageBox.No, _main.QMessageBox.Yes)
        if reply != _main.QMessageBox.Yes:
            return
        password = ""
        if spec.password_kind and not info.exists:
            # 只在"第一次注册成服务"时问密码：之后每次启动再问一遍是骚扰，
            # 而且 MySQL 的 root 密码已经生效、Redis 的 requirepass 已落在 conf 里。
            dlg = _main.ServicePasswordDialog(comp.display_name, spec.password_kind, self)
            if dlg.exec() != _main.QDialog.Accepted:
                return
            password = dlg.password()
        self.btn_start.setEnabled(False)
        self.btn_start.setText("启动中…")
        self.launch_worker = _main.LaunchWorker("start", comp, _main.component_registry(),
                                          _main.SERVICE_MANAGER, parent=self,
                                          version=version, password=password)
        self.launch_worker.started_ok.connect(self._on_launch_ok)
        self.launch_worker.failed.connect(self._on_launch_failed)
        self.launch_worker.notes.connect(self._on_launch_notes)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    # ------------------------------------------------------------------
    # 前置运行时的自动安装（JDK / Erlang）
    # ------------------------------------------------------------------
    def _install_missing_prereqs(self, keys: List[str]) -> None:
        """把缺失的前置运行时排队装好，装完自动重跑启动。

        为什么不弹"要不要装"的问询：用户点了「启动」就是"我要它跑起来"，
        再问一次等于把决定权丢回去；而这里要装的都是**明确的、可复现的**东西
        （JDK / Erlang 的官方包），装错了也只是多一个版本目录。
        """
        comps = _main.component_registry()
        queue: List[Tuple[_main.Component, str]] = []
        for key in keys:
            pre = comps.get(key)
            if pre is None:
                continue
            version = _main.pick_prereq_version(pre, _main.prereq_install_versions(self.component))
            if version is None:
                _main.QMessageBox.warning(
                    self, "缺少前置运行时",
                    f"{self.component.display_name} 需要 {pre.display_name}，"
                    f"但当前平台没有它的可下载版本。")
                return
            if _main.prereq_already_installed(pre, version):
                continue
            queue.append((pre, version))
        if not queue:
            # 需求已经满足（比如别的卡片刚装上）→ 直接继续
            self._do_start()
            return
        names = "、".join(f"{c.display_name} {v}" for c, v in queue)
        self._log("info", f"{self.component.display_name} 启动前需要 {names}，"
                          f"正在自动下载安装（装一次，以后不再重复）…")
        self.btn_start.setEnabled(False)
        self.btn_start.setText("准备依赖…")
        self._prereq_queue = queue
        self._install_next_prereq()

    def _install_next_prereq(self) -> None:
        """装队列里的下一个前置组件；装完继续下一个，全装完则重跑启动。"""
        if not self._prereq_queue:
            self.btn_start.setEnabled(True)
            self.btn_start.setText("启动")
            self._log("ok", "前置运行时已就位，继续启动。")
            self._do_start()
            return
        pre, version = self._prereq_queue.pop(0)
        cv = next((c for c in pre.versions if c.version == version), None)
        urls = cv.urls_for_current() if cv else []
        if cv is None or not urls:
            self._on_prereq_failed(f"{pre.display_name} {version} 没有可用下载地址")
            return
        suffix = self._download_suffix(pre, cv, urls)
        dest = _main.CONFIG_DIR / pre.key / "downloads" / f"{pre.key}-{version}{suffix}"
        _main.ensure_dir(dest.parent)
        self._log("info", f"下载 {pre.display_name} {version}（源：{urls[0]}）")
        self.prereq_worker = _main.DownloadWorker(urls, dest, parent=self)
        self.prereq_worker.progress.connect(self._on_prereq_progress)
        self.prereq_worker.log.connect(self._log)
        self.prereq_worker.finished_ok.connect(
            lambda p, c=pre, v=version: self._on_prereq_downloaded(c, v, Path(p)))
        self.prereq_worker.finished_fail.connect(self._on_prereq_failed)
        self.prereq_worker.start()

    @staticmethod
    def _download_suffix(comp: "Component", cv: "ComponentVersion", urls: List[str]) -> str:
        """下载文件名的后缀必须与包体真实形态一致（extract_archive 按后缀选分支）。"""
        if comp.installer_mode:
            ext = cv.archive_map.get(_main.CURRENT_OS, "")
            if not ext:
                first = urls[0] if urls else ""
                ext = "exe" if first.endswith(".exe") else ("sh" if first.endswith(".sh") else "bin")
            return f".{ext}"
        ext = cv.archive_for_current()
        return {"zip": ".zip", "tar.gz": ".tar.gz", "tgz": ".tar.gz", "exe": ".exe",
                "war": ".war", "": "", "bin": "", "cli": ".zip"}.get(ext, f".{ext}")

    def _on_prereq_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._log("info", f"依赖下载中：{_main.human_size(done)} / {_main.human_size(total)}"
                              f"（{int(done * 100 / total)}%）")

    def _on_prereq_downloaded(self, pre: "Component", version: str, path: Path) -> None:
        try:
            final = _main.install_downloaded(pre, version, path, _main._LoggerAdapter(self._log))
        except Exception as exc:
            self._on_prereq_failed(f"{pre.display_name} 安装失败：{exc}")
            return
        if not _main.prereq_already_installed(pre, version):
            self._on_prereq_failed(f"{pre.display_name} 装完了但在 {final} 里找不到可执行文件")
            return
        self._log("ok", f"{pre.display_name} {version} 已装好：{final}")
        ok_env = self._configure_prereq_env(pre, final)
        if not ok_env:
            # java 系组件没有 JAVA_HOME 就是起不来，这里不许再写成"不影响启动"
            self._on_prereq_failed(
                f"{pre.display_name} 装好了，但写 {pre.env_var or 'PATH'} 失败，"
                f"{self.component.display_name} 依然启动不了")
            return
        self._install_next_prereq()

    def _configure_prereq_env(self, pre: "Component", final: Path) -> bool:
        """让刚装好的前置运行时**真的能用**：HOME 变量 + PATH 都要写，且跨平台。

        以前这里只调 Windows 专用的 `set_windows_user_env` 写一个 HOME，**不写 PATH**，
        Linux/macOS 上更是连 HOME 都不写；失败时日志还写着"不影响启动" —— 对 java 系
        组件来说恰恰相反：JAVA_HOME 没配上，nacos 的 startup.cmd / jenkins 的 `java -jar`
        根本起不来，用户看到的就是"依赖明明装好了，启动还是失败"。
        所以改成与正常安装同一套写入（HOME + PATH + 装完核对），失败如实上报。
        """
        bin_dir = final / pre.path_subdir if pre.path_subdir else final
        try:
            if pre.env_var:
                if _main.CURRENT_OS == "Windows":
                    _main.EnvManager.set_windows_user_env(pre.env_var, str(final))
                    _main.EnvManager.append_windows_path(str(bin_dir))
                else:
                    rc = _main.EnvManager.set_unix_env(pre.env_var, str(final))
                    _main.EnvManager.append_unix_path(str(bin_dir))
                    self._log("info", f"已写入 {rc}")
                self._log("ok", f"设置 {pre.env_var}={final}")
            else:
                if _main.CURRENT_OS == "Windows":
                    _main.EnvManager.append_windows_path(str(bin_dir))
                else:
                    _main.EnvManager.append_unix_path(str(bin_dir))
            self._log("ok", f"追加 PATH：{bin_dir}")
            ok_dir, _where = _main.verify_bin_dir(pre, final)
            if not ok_dir:
                self._log("warn", f"{pre.display_name} 装完了，但 {bin_dir} 里没有它的可执行文件")
            return True
        except Exception as exc:  # noqa: BLE001
            self._log("error", f"写 {pre.env_var or 'PATH'} 失败：{exc}")
            return False

    def _on_prereq_failed(self, reason: str) -> None:
        self._prereq_queue = []
        self.btn_start.setEnabled(True)
        self.btn_start.setText("启动")
        self._log("error", f"前置运行时准备失败：{reason}")
        _main.QMessageBox.warning(self, "前置运行时准备失败",
                            f"{reason}\n\n装好之后可以再点一次「启动」。")

    def _on_launch_ok(self, key: str, console_url: str) -> None:
        """启动成功后的统一收尾：**给用户一个能打开的地址** + 说清停止按钮在哪。

        2026-10-08 用户要求：不管组件有没有自带控制台，启动后都要有个能访问的页面，
        让用户确认"确实起来了"。所以这里分两路：
          - 自带 Web 界面（含 ES 的 JSON 根路径）：地址就是它自己的；
          - 协议端口型（kafka / rocketmq / rabbitmq）：用工具自带的
            「启动成功」页（见 ComponentPageServer），并把 URL 写回登记，
            这样卡片上的「打开访问页」按钮也能直接打开它。
        """
        st = self._launch_status()
        rec = st.record
        spec = self.component.launch
        page_url: Optional[str] = None
        if rec is not None and spec is not None:
            try:
                page_url = _main.show_launch_page(self.component, spec, rec)
            except Exception as exc:      # 页面服务不该影响"启动成功"这件事
                self._log("warn", f"生成访问页失败（不影响服务运行）：{exc}")
            if page_url and page_url != rec.console_url:
                # 把访问页写回登记：刷新界面/重开工具后「打开访问页」按钮仍可用
                try:
                    records = _main.load_running_map()
                    if self.component.key in records:
                        records[self.component.key].console_url = page_url
                        _main.save_running_map(records)
                except Exception:
                    pass
                self._launch_page_url = page_url
        if spec is not None and rec is not None:
            for line in _main.launch_success_lines(self.component, spec, rec, page_url):
                self._log("ok", line)
        self._refresh_launch_state()
        # 明说停止按钮在哪：2026-10-06 用户反馈"启动了 nacos，没看到停止选项"。
        # 查下来按钮一直好着（可见可用、文本"停止"、旁边 label 显示"● 运行中 · 端口 8848"），
        # 但启动成功后只写一句"已启动，控制台：…"，用户不确定"停止"这个按钮出现了没有
        # ——尤其卡片上同时有"卸载"按钮，两者挨在一起，容易看成没变。
        # 所以直接点名：停止按钮就在这张卡片上、按钮文字是什么。
        self._log("info", f"「停止」按钮已出现在这张卡片上（现在可用），"
                          f"再点一次可结束运行中的 {self.component.display_name}。")
        self._log_credentials()

    def _log_credentials(self) -> None:
        """把登录凭据打进组件日志（2026-10-06 用户要求）。

        凭据不算秘密了：这些是**厂商出厂默认**（nacos/nacos、admin/admin），
        任何装了同一个版本的人都是同一份。而 Jenkins 那种随机密码本来就在
        本机文件里、只有本机用户能读。它解决的是"服务起来了却登不进去，
        还要自己去翻文件/翻官方文档"——那才是真折腾。

        用 info 级而不是 warn 级：这不是风险提示，是用户现在就需要的信息。
        """
        spec = self.component.launch
        if spec is None:
            return
        try:
            port = self._launch_status().record.port \
                if self._launch_status().state == "running" else spec.main_port
        except Exception:
            port = spec.main_port
        try:
            for line in _main.credentials_for(self.component, spec, port):
                self._log("info", line)
        except Exception as exc:            # 凭据读不出来不该影响启动结果
            self._log("warn", f"读取登录凭据失败（不影响使用）：{exc}")

    def _on_launch_notes(self, key: str, notes: list) -> None:
        """端口准备的告警逐条进组件日志。吞掉的话，用户之后想找"端口改在哪份文件里"
        只能自己猜 —— R4 第 6 条禁止的写法。"""
        for line in notes:
            self._log("warn", line)

    def _on_launch_failed(self, key: str, reason: str) -> None:
        # 关窗链路里 cancel 触发的 failed 可能在退出途中投递进来；模态框自己转事件循环，
        # 会把关窗卡住。只看顶层窗口（closeEvent 已立的 _closing 旗）是不是正在关。
        # try 包的是 self.window() 这次 Qt 调用本身：顶层 C++ 对象先没了它会抛 RuntimeError，
        # 而那时候连"记一条日志"的机会都没有 —— 那正是本方法要避免的静默失败。
        try:
            closing = _main.is_closing()
        except Exception:
            closing = True
        if closing:
            self._log("warn", f"操作未完成（窗口正在关闭）：{reason}")
            return
        self._log("error", f"操作失败：{reason}")
        _main.QMessageBox.warning(self, "操作失败", reason)
        self._refresh_launch_state()

    def _on_need_force(self, key: str, reason: str) -> None:
        """停止超时/无法优雅结束：问一次，不自己决定强杀（spec §5）。"""
        if _main.QMessageBox.question(self, "需要强制结束", reason,
                                _main.QMessageBox.Yes | _main.QMessageBox.No,
                                _main.QMessageBox.No) != _main.QMessageBox.Yes:
            self._log("warn", "未强制结束，进程仍在运行。")
            return
        # need_force 是从 worker 线程里发的：这个槽跑的时候老 worker 的 run()
        # 可能还没返回，丢掉它最后一个引用会被 PySide 就地销毁还在跑的 QThread。
        # parent=self 把引用交给对象树持有，这条窗口才关得掉。
        self.launch_worker = _main.LaunchWorker("force_stop", self.component,
                                          _main.component_registry(), _main.SERVICE_MANAGER,
                                          parent=self)
        self.launch_worker.stopped.connect(self._on_launch_stopped)
        self.launch_worker.failed.connect(self._on_launch_failed)
        self.launch_worker.need_force.connect(self._on_need_force)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    def _on_launch_stopped(self, key: str) -> None:
        self._log("info", "已停止。")
        # 停止后也报一次凭据：用户常常是"启动→看一眼配置→再停止"这个顺序，
        # 停止这一刻他正要打开控制台，此刻给凭据最省事（日志滚动到底就能看到）。
        if self.component.launch is not None:
            self._log_credentials()
        self._refresh_launch_state()

    def _on_launch_worker_done(self) -> None:
        # 按身份收尾：老 worker 的 finished 可能晚于新 worker 起跑
        # （need_force 那条路上两条线程会短暂共存），无条件置 None 会把刚启动的
        # force_stop worker 的引用抹掉，强杀正在跑时反而没人持有它。
        worker = self.sender()
        if worker is self.launch_worker:
            self.launch_worker = None
        if worker is not None:
            worker.deleteLater()   # finished 之后删除是安全的：run() 已经返回
        self._refresh_launch_state()

    def on_start_stop_clicked(self) -> None:
        """启动/停止合并按钮的唯一入口：按当前实况决定做哪件事。

        判据用 `_launch_status()`（直接读端口实况），不用按钮上次的文字或启用态——
        那两个都可能被异步结果改过，用它们当依据就会出现"按钮写着启动、其实在跑"
        或者反过来，点一下做了错的事。
        """
        st = self._launch_status()
        if st.state == "running":
            self.on_stop_clicked()
        elif st.state == "zombie":
            # 僵尸登记（登记还在、端口没在听）：点按钮的意图是"清掉它重新起一个"，
            # 而不是"再停一次已经没在跑的东西"——那会让用户以为按钮坏了。
            self.on_start_clicked()
        else:
            self.on_start_clicked()

    def on_stop_clicked(self) -> None:
        self.btn_start.setEnabled(False)
        self.btn_start.setText("停止中…")
        self.launch_worker = _main.LaunchWorker("stop", self.component,
                                          _main.component_registry(), _main.SERVICE_MANAGER,
                                          parent=self)
        self.launch_worker.stopped.connect(self._on_launch_stopped)
        self.launch_worker.failed.connect(self._on_launch_failed)
        # 这条线不能省：停不下来时 need_force 就是"问一次"的唯一入口，
        # 漏接了按钮会直接停在"停止中"结束、用户既没被问也没结果。
        self.launch_worker.need_force.connect(self._on_need_force)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    def on_console_clicked(self) -> None:
        """打开访问页。

        **每个可启停组件都有一个能打开的地址**（2026-10-08 用户要求）：
          - 自带 Web 界面：它自己的控制台/首页（nginx 是 8888、tomcat 是 8081，
            都由登记表里的实际端口给出，不再写死 8080）；
          - 协议端口型（kafka / rocketmq / rabbitmq / ES）：工具自带的
            「启动成功」页，上面写着运行状态、端口、日志路径与访问方式。

        历史坑（2026-10-06）：nginx/tomcat 的 console_path 曾是 None，
        console_url 被拼成 `http://127.0.0.1:8080` → 点开必然 404，
        用户以为"启动成功是假的"。现在这两件都有真实首页，且对没有界面的组件
        改指自带页，不会再指到一扇不存在的门。
        """
        st = self._launch_status()
        if st.record is None:
            return
        target = st.record.console_url
        spec = getattr(self.component, "launch", None)
        if spec is not None and not spec.console_path:
            # 协议端口型：页服务可能因重启换了端口（或刚从旧版本升级上来），
            # 登记里那条 URL 不一定还能用。点开的这一刻取一次当前端口。
            server = _main.get_page_server()
            fresh = server.url_for(self.component.key) if server is not None else None
            if fresh:
                target = fresh
        if not self._has_console():
            _main.QMessageBox.information(
                self,
                f"{self.component.display_name} 没有网页控制台",
                f"{self.component.display_name} 不提供网页界面，"
                f"它的服务在端口 {st.record.port} 上（对局域网开放）。\n\n"
                f"要访问它请用对应的客户端工具，例如：\n"
                f"{self._no_console_hint()}")
            return
        _main.QDesktopServices.openUrl(_main.QUrl(target))

    def _has_console(self) -> bool:
        """该组件是否有可点的访问页。

        判据有两条（任一成立即可点）：
          ① 登记表里有 `console_path` —— 组件自带的 Web 界面/首页；
          ② 登记里的 `console_url` 指向本工具自带的「启动成功」页
             （协议端口型组件走这条，见 show_launch_page）。
        2026-10-08 之前只认①，于是 kafka/rocketmq/rabbitmq 的卡片上
        根本没有这个按钮 —— 而用户现在**要求**每件都有能打开的页面。
        """
        spec = getattr(self.component, "launch", None)
        if spec is None:
            return False
        if spec.console_path:
            return True
        try:
            st = self._launch_status()
        except Exception:
            return False
        return bool(st.record is not None and st.record.console_url)

    def _no_console_hint(self) -> str:
        """没有控制台时，给一句"这个组件该怎么用"的实话。

        **端口不能写死**（2026-10-08 改正）：原来这里写着 8080，而 tomcat 实际是
        8081、nginx 是 8888 —— 一句写错端口的指引比不给指引更坏，用户会照它去连
        一个根本没人听的端口。现在按登记表里的 main_port 现算。
        """
        spec = getattr(self.component, "launch", None)
        port = getattr(spec, "main_port", None) or "?"
        return {
            "tomcat": f"把 WAR 放进 ~/.env-tools/tomcat-data/webapps/ 后访问 "
                      f"http://127.0.0.1:{port}/应用名/（放安装目录那份不生效）",
            "nginx": f"默认站点在 ~/.env-tools/nginx-data/html/ 下，"
                     f"访问 http://127.0.0.1:{port}/",
            "elasticsearch": f"用 curl 访问 http://127.0.0.1:{port}/（图形界面 Kibana 不在本工具里）",
            "kafka": "用 kafka-topics.bat（安装目录 bin/windows/ 下）之类的命令行工具操作",
            "rocketmq": "用 mqadmin（安装目录 bin/ 下）命令行工具操作",
            "rabbitmq": "管理界面需要额外开 rabbitmq_management 插件，本工具暂未启用",
        }.get(self.component.key, "请用对应的客户端工具访问")

    # ------------------------------------------------------------------
    def _render_status_label(self) -> None:
        if self.component.multi_version and self._mv_capsule:
            # 多版本胶囊正文取 _detect_status 已算好的基础文案（逐字不变），异步版本号
            # 只在其后追加；绿=有生效版本（_status_shows_configured），橙=均未生效/未对齐。
            # _mv_capsule 为空串表示这次走的是"本工具没装过、探测到系统安装"的通用分支，
            # 那时必须落到下面的 ✓ 已配置 文案，不能渲染一个空胶囊。
            # 短串与全量原文同步续上版本号：主文本只放得下结论，版本列表在 tooltip 里。
            text = self._mv_capsule
            # 外部只塞了胶囊全文（没算过短串）时退回全量，主文本不许是空的
            short = self._mv_capsule_short or self._mv_capsule
            if self._status_version:
                text += f" · {self._status_version}"
                short += f" · {self._status_version}"
            self._set_status(text, short)
            self.status_label.setStyleSheet(
                "color:#ef6c00;font-weight:600;padding:2px 8px;"
                "background:#fff3e0;border-radius:10px;"
                if self._mv_orange or not self._status_shows_configured else
                "color:#2e7d32;font-weight:600;padding:2px 8px;"
                "background:#e8f5e9;border-radius:10px;")
            return

        text = f"✓ 已配置（{self._status_where}）"
        short = f"✓ 已配置 · {self._short_where()}"
        if self._status_version:
            text += f" · {self._status_version}"
            short += f" · {self._status_version}"
        elif self.component.version_probe:
            text += " · 版本检测中…"
            short += " · 检测中…"
        self._set_status(text, short)
        self.status_label.setStyleSheet(
            "color:#2e7d32;font-weight:600;padding:2px 8px;"
            "background:#e8f5e9;border-radius:10px;"
        )

    def _short_where(self) -> str:
        """主文本里那截"来源"要短（格子只有 271px），完整出处留给 tooltip。

        多版本组件走到通用分支 = 本工具一个版本都没装、探测到的是用户自己装的，
        主文本只说「系统安装」；"不由本工具管理"这个结论在 tooltip 的全量原文里。
        """
        if self.component.multi_version:
            return "系统安装"
        return self._status_where or "系统"

    def _schedule_version_probe(self, exe_path: str) -> None:
        """把「执行组件命令取版本号」推迟到事件循环空闲时，且放到后台线程。

        version_probe=False 的启动脚本型组件（Nacos/Kafka/RocketMQ/Seata/RabbitMQ）
        在这里直接跳过——一执行就会把中间件服务拉起来。
        """
        if not (exe_path and self.component.version_probe and self.component.version_args):
            return
        _main.QTimer.singleShot(0, lambda: self._start_version_probe(exe_path))

    def _start_version_probe(self, exe_path: str) -> None:
        # 关窗途中事件循环还会转（closeEvent 里那些 wait 就是机会），残留的 singleShot
        # 这时再起一条线程 = 窗口析构时它还在跑 = 进程 abort。_launch_fetch_worker 早有这道闸。
        if _main.is_closing():
            return
        worker = _main.VersionProbeWorker(exe_path, list(self.component.version_args), self)
        worker.done.connect(lambda text, w=worker: self._on_version_probed(text, w))
        worker.finished.connect(worker.deleteLater)
        # 顶替掉的旧线程不能没人等：`_version_worker` 只代表最新那一条，
        # 而三处 `_version_worker = None` 和这里的重赋值都会把在跑的旧线程变成孤儿。
        self._probe_workers = [w for w in self._probe_workers
                               if _main._qthread_state(w) == "running"]
        self._probe_workers.append(worker)
        self._version_worker = worker
        worker.start()

    def _on_version_probed(self, text: str, worker: Optional["VersionProbeWorker"] = None) -> None:
        # 回包可能晚到：状态已不「已配置」或已被更新一轮探测取代时丢弃
        if not self._status_shows_configured:
            return
        if worker is not None and worker is not self._version_worker:
            return
        self._status_version = text or "未知版本"
        self._render_status_label()

    # ------------------------------------------------------------------
    def _installed_here(self, version: str) -> Optional[Path]:
        """该版本是否真的装好了：装好返回安装目录，否则 None。

        只看目录存在不够 —— 解压一半失败也会留下目录，那时按钮灰掉、
        卸载又删不出东西，用户就被卡死了。所以还要在里面找得到该组件的可执行文件；
        没有 exec_name 的组件（Jenkins 只有一个 war 包）退化成"目录非空"。
        """
        home = self.component.install_dir(version)
        if not home.is_dir():
            return None
        if self.component.exec_name:
            return home if self.component.exec_path_in_home(str(home)) else None
        return home if any(home.iterdir()) else None

    # ------------------------------------------------------------------
    def _sync_action_buttons(self) -> None:
        """按「当前选中的版本」重算三个按钮：下载并安装 / 切换生效 / 卸载。

        三个触发点：① _detect_status 之后；② 下拉框换选中之后；
        ③ 下载结束或失败之后。只挂 ① 会出真机 bug —— 切一次生效版本后按钮置灰，
        用户换选另一个版本没人重算，按钮一直灰着点不动（2026-09-30 反馈）。
        """
        # 只下载型组件没有「切换 / 卸载」节点，下面每一行都会踩空；
        # 而且它按"选中版本装没装"算启用条件，那要去扫盘 —— 一开始就该短路掉。
        if self.component.download_only:
            return
        # 下载途中按钮归下载流程管：否则换个选中就能并发触发第二次下载
        if not (self.worker and self.worker.isRunning()):
            selected = self._current_version().version
            home = self._installed_here(selected)
            self.btn_install.setEnabled(home is None)
            self.btn_install.setToolTip(
                f"该版本已安装在 {home}；要重新安装请先点「卸载」" if home else
                "下载该版本并解压安装到本工具工作目录")
        if not self._mv_buttons_ready:
            return
        # 未对齐/被遮蔽时切换按钮必须可用：哪怕 selected 恰好等于 active，
        # 也得让用户能再点一次去收敛 PATH 与登记表
        selected = self._current_version().version
        can_switch = selected != self._mv_active or self._mv_warned
        self.btn_configure.setEnabled(can_switch)
        self.btn_configure.setToolTip(
            "把下拉框选中的版本设为生效版本：改 XXX_HOME，并把本组件在 PATH 里的"
            "条目收敛成这一条；已开着的终端需重开才生效"
            "（Windows Terminal 的新标签页、IDE 里的新终端都还是旧环境，要整个关掉重开）"
            if can_switch else
            f"选中的 {selected} 已是生效版本；要换版本先在下拉框里选中")
        # 卸载按钮只对"已装的选中版本"启用：tooltip 承诺卸载选中的那个，
        # 而 selected 完全可能没装——放行会走 resolve 兜底删掉用户没选中的版本。
        if selected in self._mv_installed_set:
            # 运行中（被启动锁过）不许重新点亮卸载：切换版本下拉框也会走到这里，
            # 无条件启用会让按钮和"● 运行中"的文案在同一张卡上自相矛盾。
            self.btn_uninstall.setEnabled(not self._uninstall_locked_by_launch)
            self.btn_uninstall.setToolTip(
                f"卸载下拉框选中的 {selected}：只删该版本目录与它的 PATH 条目，"
                "其他已装版本不动")
        else:
            self.btn_uninstall.setEnabled(False)
            self.btn_uninstall.setToolTip(
                f"选中的 {selected} 未安装；要卸载其他版本先在下拉框里选中"
                "（下拉框里有绿勾的就是已装）")

    # ------------------------------------------------------------------
    def _show_external_capsule(self, takeover: dict, ordered, residue) -> bool:
        """接管外部版本时的状态胶囊（设计 §6 第三档）。返回 True = 已接管显示。

        为什么必须单独一档：接管生效期间 active 登记按 §4.3 已被删除，走原来那条
        "本工具装了哪个版本生效"的分支只会报成"均未生效"，与实际情况正好相反。
        """
        home = Path(str(takeover.get("home") or ""))
        ver = str(takeover.get("version") or "?")
        names = "、".join(v for v, _p in ordered)
        green = ("color:#2e7d32;font-weight:600;padding:2px 8px;"
                 "background:#e8f5e9;border-radius:10px;")
        orange = ("color:#ef6c00;font-weight:600;padding:2px 8px;"
                  "background:#fff3e0;border-radius:10px;")

        if not home.is_dir():
            # §7：快照指向的目录被用户删了 —— 如实说，**不自动改环境**，
            # 只提示可以点还原或另选一个。
            capsule = (f"● 之前接管的外部版本已不存在（{home}）· 请点「还原到我之前的设置」"
                       "或改选别的版本")
            short = "● 接管的外部版本已不存在"
            warned = True
        else:
            tail = (f" · 工作区 {len(ordered)} 个版本（{names}）" if ordered
                    else " · 工作区没有装版本")
            level = "系统" if str(takeover.get("level")) == "machine" else "用户"
            capsule = f"● 生效 {ver}（{level} {home}）{tail}"
            short = f"● 生效 {ver}（{level}级）"
            warned = False
        if residue:
            capsule += f" · 另有 {len(residue)} 个残留空目录待清理"
            short += f" · {len(residue)} 个残留待清理"
            warned = True

        self._mv_capsule = capsule
        self._mv_capsule_short = short
        self._mv_orange = warned
        self._set_status(capsule, short)
        self.status_label.setStyleSheet(orange if warned else green)
        # active 置空：切换按钮据此恒为可用（用户要能切回工作区版本，
        # _apply_active 会先走 release_external_before_workspace_switch 还原）。
        self._mv_active = None
        self._mv_warned = warned
        self._mv_installed_set = ({v for v, _p in ordered}
                                  | {v for v, _p in residue})
        self._mv_buttons_ready = True
        self._sync_action_buttons()
        self._status_shows_configured = False
        self._status_version = ""
        self._version_worker = None
        self._refresh_installed_marks()
        return True

    def _detect_status(self) -> None:
        """检测组件状态，并在每条出口后刷新一遍运行态。

        _detect_status_impl 有四条出口（多版本胶囊 / 已配置 / 已下载 / 未安装），把
        `_refresh_launch_state()` 写在物理末尾只会覆盖最后那条；包一层才能保证
        "每次重探状态都顺带把启动/停止/卸载按钮对齐端口实况"。
        """
        self._detect_status_impl()
        self._refresh_launch_state()

    def _detect_status_impl(self) -> None:
        """检测该组件当前是否已安装、已配置。

        - 若系统 PATH 或 XXX_HOME 已能找到可执行文件，则视为「已配置」，禁用
          「仅配置环境变量」按钮，避免重复写入。
        - 若本地已解压但未配置，则允许点击「仅配置环境变量」。
        - 若未安装，两个按钮均可用。

        本方法在窗口构建卡片时就会被调用，因此绝不同步执行组件命令：detect 只判定
        存在（probe_version=False），版本号交给 VersionProbeWorker 异步回填。
        """
        # 向导型卡片（WSL）：只报"装没装"，不启动任何提权/探测子进程。
        # 判据用目录存在性而不是 `wsl --version`：建卡发生在启动期，186 张卡里
        # 这一张不该额外拉两个子进程。
        if self.component.ui_action == "wsl":
            imported = (_main.wsl_work_dir() / _main.WSL_DISTRO).is_dir()
            if imported:
                full = (f"WSL2 已就绪：Ubuntu {_main.WSL_UBUNTU_SERIES} 已导入到 "
                        f"{_main.wsl_work_dir() / _main.WSL_DISTRO}。点「安装向导」可查看详情或重新导入。")
                short = "● WSL 已就绪"
                style = ("color:#2e7d32;font-weight:600;padding:2px 8px;"
                         "background:#e8f5e9;border-radius:10px;")
            else:
                full = ("点「安装向导」：启用 WSL 与虚拟机平台 → 安装官方运行时 → "
                        "导入 Ubuntu 24.04。系统功能装完必须重启才生效，"
                        "本工具只提示、不会替你重启。")
                short = "● 未安装 · 点「安装向导」"
                style = ("color:#5b6b7a;font-weight:600;padding:2px 8px;"
                         "background:#eef2f6;border-radius:10px;")
            self._set_status(full, short)
            self.status_label.setStyleSheet(style)
            return
        # 只下载型组件（「开发工具」）磁盘上根本不会有它，任何"已配置 / 未安装"的结论
        # 都是假的，而且算这些结论要扫盘。胶囊只说清它能干什么，中性灰 —— 不用绿色
        # （绿色在本界面里等于"已配置"）也不用橙色（等于"出问题了"）。
        if self.component.download_only:
            note = "仅提供官方安装包下载 · 不解压、不配置环境变量"
            self._set_status(note, "仅提供官方安装包下载")
            self.status_label.setStyleSheet(
                "color:#5b6b7a;font-weight:600;padding:2px 8px;"
                "background:#eef2f6;border-radius:10px;")
            return
        # 「下载并安装」的启用状态只取决于选中的版本装没装好，与后面走哪条探测分支无关，
        # 所以在分支之前先同步一次；多版本那两个按钮要等本方法算出 active 之后再同步。
        self._sync_action_buttons()
        # 多版本组件：状态胶囊要表达的是"装了哪几个 + 哪个生效"，
        # 而不是单一的"已配置/未配置"；生效以 active 登记表为准，探测只用于回填版本号。
        if self.component.multi_version:
            ordered = _main.installed_versions(self.component)
            residue = _main.residue_install_dirs(self.component)
            # 磁盘上的已装集合刚变过（装完/卸完），"已装但清单里没有"的合成项要跟着增减。
            # 必须放在 `if ordered` 之前：最后一个额外版本被卸掉时 ordered 为空，
            # 会直接落到下面的通用探测分支，放里面就永远摘不掉那一行。
            if self.version_combo.count() != len(self._combo_version_list()):
                self._reload_combo_items(preferred=self.version_combo.currentText())
            # 接管了外部版本的一档（§6）：这个时候 active 登记已被删除，不能按
            # "本工具装了哪个版本生效"去显示，否则会报成"均未生效"。
            if _main.supports_external_takeover(self.component):
                self._refresh_external_section()
                takeover = _main.load_takeover_map().get(self.component.key)
                if takeover:
                    if self._show_external_capsule(takeover, ordered, residue):
                        return
            # 只有"本工具目录下确实装着版本"时才走多版本胶囊。一个都没有时不许就此断言
            # "未安装"——用户很可能自己装了 JDK/Maven（JAVA_HOME 或 PATH 里就有），
            # 那要交给下面的通用探测识别成"已配置（系统安装）"。
            if ordered:
                home_ver = (_main.load_active_map().get(self.component.key)
                            or _main.infer_active_from_env(self.component))
                path_ver = self._path_hit_version()
                active = home_ver or path_ver
                # HOME 与 PATH 指向不同版本时，命令行实际用的是 PATH 那个；只报 HOME 里的
                # 就是骗人（2026-09-30 真机：bun 1.4.2 与 1.4.1 同时留在 PATH 里）。
                mismatch = bool(home_ver and path_ver and home_ver != path_ver)
                # 复验"新终端实际会命中谁"：被 PATH 里更靠前的条目（系统级变量、用户自装的
                # 版本）压住时，不许只写"生效 X"——那正是本机 jdk 的处境。
                verdict, shadow = self._path_effective_check(active)
                warned = mismatch or verdict == "shadowed"
                names = "、".join(v for v, _p in ordered)
                short = ""
                if mismatch:
                    capsule = (f"● 已装 {len(ordered)} 个版本 · 未对齐：PATH 用的是 {path_ver}，"
                               f"{self.component.env_var or '环境变量'} 指 {home_ver}（{names}）")
                    short = "● 未对齐（PATH≠HOME）"
                elif verdict == "shadowed":
                    capsule = (f"● 已装 {len(ordered)} 个版本 · 生效 {active}（{names}）"
                               f" · 但 PATH 先命中 {shadow}")
                    short = (f"● 已装 {len(ordered)} 个 · 生效 {active}"
                             f" · 被 PATH 抢先")
                else:
                    tail = f" · 生效 {active}" if active else " · 均未生效"
                    capsule = f"● 已装 {len(ordered)} 个版本{tail}（{names}）"
                    short = f"● 已装 {len(ordered)} 个{tail}"
                if residue:
                    # 磁盘上还有内容被删空的目录：必须报出来，否则它既不算已装、
                    # 又没人知道要清理，就成了永久死角（胶囊是用户唯一的入口线索）。
                    warned = True
                    capsule += f" · 另有 {len(residue)} 个残留空目录待清理"
                    short += f" · {len(residue)} 个残留待清理"
                self._mv_capsule = capsule
                self._mv_capsule_short = short
                self._mv_orange = warned
                self._set_status(capsule, short)
                self.status_label.setStyleSheet(
                    "color:#ef6c00;font-weight:600;padding:2px 8px;"
                    "background:#fff3e0;border-radius:10px;" if warned or not active else
                    "color:#2e7d32;font-weight:600;padding:2px 8px;"
                    "background:#e8f5e9;border-radius:10px;")
                selected = self._current_version().version
                # 按钮启用状态交给 _sync_action_buttons()：它还有第二个触发时机 ——
                # 下拉框换选中。只挂在这里会出真机 bug（2026-09-30）：切一次之后按钮置灰，
                # 用户换选另一个版本，没人重算，按钮一直灰着点不动。
                self._mv_active = active
                self._mv_warned = warned
                self._mv_installed_set = ({v for v, _p in ordered}
                                          | {v for v, _p in residue})
                self._mv_buttons_ready = True
                self._sync_action_buttons()
                # 探测回填只在确有生效版本、且没有未对齐时开放闸门，并把上一轮
                # 生效版本回填过的旧版本号清掉——否则切完版本胶囊还挂着 21.0.4。
                self._status_shows_configured = bool(active) and not mismatch
                self._status_version = ""
                # 作废上一轮探测线程的迟到回调：_on_version_probed 靠 worker 身份挡旧回包，
                # 不清旧 _version_worker 的话，旧 worker 回来会把上一轮生效版本的旧版本号
                # 贴进这一轮的新胶囊里，永久错标。
                self._version_worker = None
                if not mismatch:
                    for ver, path in ordered:
                        if ver == active:
                            # 复用既有寻径（会试 bin/、根目录、.bat/.cmd 等），别自己拼路径
                            exe = self.component.exec_path_in_home(str(path))
                            if exe:
                                self._schedule_version_probe(str(exe))
                            break
                self._refresh_installed_marks()
                return
            elif residue:
                # 只剩空壳目录（真机 2026-10-07 rabbitmq 的收尾状态）：说"未安装"是假话
                # ——磁盘上确实有个删不掉的目录；说"已装"也是假话 —— 里面一个文件都没有。
                # 所以这一支单独说清"残留待清理"，并且**不能**落到下面的通用探测分支：
                # 那一支会按 PATH/HOME 判定，而空壳的 HOME 刚被这次卸载清掉，
                # 结果是卡片显示"未安装"、卸载按钮置灰，那个目录就永远清不掉了。
                vers = "、".join(v for v, _p in residue)
                capsule = (f"● {len(residue)} 个残留空目录待清理（{vers}）"
                           f" · 内容已删除、不算已装")
                self._mv_capsule = capsule
                self._mv_capsule_short = f"● {len(residue)} 个残留待清理"
                self._mv_orange = True
                self._set_status(capsule, self._mv_capsule_short)
                self.status_label.setStyleSheet(
                    "color:#ef6c00;font-weight:600;padding:2px 8px;"
                    "background:#fff3e0;border-radius:10px;")
                self._mv_active = None
                self._mv_warned = True
                self._mv_installed_set = {v for v, _p in residue}
                self._mv_buttons_ready = True
                self._sync_action_buttons()
                self._status_shows_configured = False
                self._status_version = ""
                self._version_worker = None
                self._refresh_installed_marks()
                return

        result = self.component.detect(probe_version=False)
        # 通用分支（非多版本组件、或多版本组件但本工具没装过）自己管按钮状态，
        # 必须关掉多版本按钮同步，否则下拉框一换选中就把这里设好的状态改回去。
        self._mv_buttons_ready = False
        self._status_shows_configured = bool(result.installed)
        if result.installed:
            where = result.source or "系统"
            if self.component.multi_version:
                # 多版本组件走到这里 = 本工具没装过任何版本，探测到的是用户自己装的。
                # 不写清楚的话，用户会以为这枚"已配置"是本工具装的，找不到切换入口。
                where = f"{where} · 系统安装，不由本工具管理"
            self._status_where = where
            self._status_version = ""
            # 走通用分支 = 本工具没装过这个组件，多版本胶囊不适用；清空它，
            # 否则 _render_status_label 会渲染上一轮留下的旧胶囊。
            self._mv_capsule = ""
            self._mv_capsule_short = ""
            self._render_status_label()
            # 已可用 —— 禁用「仅配置环境变量」按钮
            self.btn_configure.setEnabled(False)
            self.btn_configure.setToolTip(
                f"系统已能检测到 {self.component.display_name}"
                f"（{result.exe_path or where}），无需再次配置。"
            )
            # 已配置状态下允许卸载（仅能清理由本工具写入的 XXX_HOME/PATH marker）
            if self.component.multi_version:
                # 走到这里 = 本工具一个版本都没装，探测到的是用户自己装的。
                # 放开卸载按钮只会给出一个做不到的承诺（真点下去也只会回"未找到安装目录"）。
                self.btn_uninstall.setEnabled(False)
                self.btn_uninstall.setToolTip(
                    "系统里这个是你自己装的，本工具不代为卸载。想交给本工具管理并在多个"
                    "版本间切换，先在下拉框选一个版本点「安装」。")
            else:
                self.btn_uninstall.setEnabled(True)
                self.btn_uninstall.setToolTip(
                    "卸载将删除本地安装目录，并清理由本工具写入的环境变量"
            )
            self._schedule_version_probe(result.exe_path)
            return

        # 尝试查找本地已解压目录
        install_root = _main.CONFIG_DIR / self.component.key
        if install_root.exists() and any(
            p for p in install_root.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name != "downloads"
        ):
            # 主文本已经够短，不需要 tooltip 复述；显式清空，免得留下上一轮胶囊的详情
            self._set_status("", "● 已下载，未配置")
            self.status_label.setStyleSheet(
                "color:#ef6c00;font-weight:600;padding:2px 8px;"
                "background:#fff3e0;border-radius:10px;"
            )
            self.btn_configure.setEnabled(True)
            self.btn_configure.setToolTip("将已下载的版本写入 XXX_HOME 与 PATH")
            # 已下载但未配置：允许卸载（删除本地解压目录）
            self.btn_uninstall.setEnabled(True)
            self.btn_uninstall.setToolTip("删除已下载但尚未配置的安装目录")
            return

        self._set_status("", "○ 未安装")
        self.status_label.setStyleSheet(
            "color:#c62828;font-weight:600;padding:2px 8px;"
            "background:#ffebee;border-radius:10px;"
        )
        self.btn_configure.setEnabled(True)
        self.btn_configure.setToolTip("将已下载的版本写入 XXX_HOME 与 PATH")
        # 未安装：禁用卸载
        self.btn_uninstall.setEnabled(False)
        self.btn_uninstall.setToolTip("当前组件未安装，无需卸载")

    # ------------------------------------------------------------------
    def _display_label(self, cv: _main.ComponentVersion) -> str:
        return getattr(cv, "display_label", None) or cv.version

    def _combo_version_list(self) -> List[_main.ComponentVersion]:
        """下拉框真正要显示的清单：内置/在线清单 + 磁盘已装但清单里没有的版本。

        必须合成是因为在线清单只保留近期版本（2026-09-30 真机：bun 清单里已无 1.4.1，
        磁盘上却装着），否则会出现"胶囊说已装 2 个版本、下拉框里只有 1 个能选"——
        那个版本切不了也卸不掉。合成项没有下载 URL，但"已装即置灰安装按钮"正好兜住。

        **所有组件都合成，不再只对多版本组件**（2026-10-06 改）。原先非多版本组件
        直接 return 候选清单，但它们的清单同样会落后于实际安装版本：jenkins 候选是
        2.568.3/2.555.3/2.541.3，磁盘上装的是 2.580.1—— 不合成的话那个已装版本
        在下拉框里根本不存在，用户看到的是"装了东西但下拉框里没有它、也没有绿勾"，
        而启动走 `resolve_launch_version()` 会去找已装的那个，两边对不上。
        R3.9 那句"非多版本组件清单逐字不变"约束的是**不能凭空造版本**，
        不是"不许把真装了的版本显示出来"—— 后者正是本条要修的。
        """
        # 只下载型组件：磁盘上不会有它，合成本来就没有对象；直接返回官方清单，
        # 顺带保证"下拉框里出现的每一版都能下载"这条判据不被合成项污染。
        if self.component.download_only:
            return list(self.component.versions)
        result = list(self.component.versions)
        known = {cv.version for cv in result}
        # 已装的 + 只剩空壳的都合成进来：空壳必须还能被选中并卸载，
        # 否则它既不算已装、又不在下拉框里，就没人能清掉它（residue_install_dirs 的用途）。
        on_disk = [v for v, _p in _main.installed_versions(self.component)]
        on_disk += [v for v, _p in _main.residue_install_dirs(self.component)]
        extras = [v for v in dict.fromkeys(on_disk) if v not in known]
        for ver in extras:
            cv = _main.ComponentVersion(version=ver, url_map={}, archive_map={})
            key = _main._semver_key(ver)
            pos = len(result)
            for i, existing in enumerate(result):
                if _main._semver_key(existing.version) < key:
                    pos = i
                    break
            result.insert(pos, cv)
        return result

    def _refresh_installed_marks(self) -> None:
        """给磁盘上已装的版本挂绿勾；只动 DecorationRole，不碰条目文本。

        为什么不写成文本前缀：下拉框条目文本是版本反查的唯一键（_current_version /
        repopulate(preferred=…) 都按 currentText 匹配），加「✓」会让选版、安装、
        卸载与配置保存全部错位。图标是纯装饰数据，不参与任何反查。

        **所有组件都挂，不分multi_version**（2026-10-06 改）。原先这里对
        `multi_version=False` 的组件直接 return，理由是"它们没有版本并存的概念"——
        但下拉框里照样列了具体版本（如 tomcat 9 / nginx 1.26），用户装完一个版本后
        那个版本就该被标出来，否则"我装的是哪个"只能靠记忆。实测：python 有勾而
        jenkins / nacos / activemq / powershell 全都没有，正是这个 return 造成的。
        `multi_version` 只管"能不能多版本并存"（R3 语义），不该管"要不要显示已装"。
        """
        # 只下载型组件永远没"已装"这回事：勾的判据是磁盘目录，它一个字节都不往
        # ~/.env-tools 下写。这里短路，免得以后有人给它加了落盘就把勾带出来。
        if self.component.download_only:
            return
        versions = self._combo_version_list()
        # F4 护栏：下面的循环按 enumerate(versions) 的行号往 combo 写数据，前提是
        # 行数与下拉框清单 1:1。哪天有调用点在改清单的同时没重灌 combo（搜索过滤、
        # repopulate 时机变化），按位写会写歪或直接 IndexError——宁可这一轮不刷勾，
        # 也不写歪：行数不齐就整轮跳过。
        if self.version_combo.count() != len(versions):
            return
        installed = {v for v, _p in _main.installed_versions(self.component)}
        icon = _main._installed_icon()
        empty = _main.QIcon()
        for i, cv in enumerate(versions):
            self.version_combo.setItemData(i, icon if cv.version in installed else empty,
                                           _main.Qt.DecorationRole)

    # ------------------------------------------------------------------
    def _reload_combo_items(self, preferred: Optional[str] = None) -> None:
        """把下拉框清单（含"已装但清单里没有"的合成项）灌进 combo，并重挂"已装"图标。"""
        versions = self._combo_version_list()
        labels = [self._display_label(v) for v in versions]
        # 若首次调用（combo 里还没内容），走普通 addItems 路径
        if self.version_combo.count() == 0:
            self.version_combo.blockSignals(True)
            self.version_combo.addItems(labels)
            # 默认选中**已安装的那个**，不是清单第一项（真机 2026-10-06 查出来的）。
            # 离线候选清单会落后于实际安装版本：jenkins 候选首位 2.568.3、实装 2.580.1，
            # 无条件选第一项会让下拉框停在一个没装的版本上——绿勾全是空的、
            # 点"配置环境变量"或"卸载"会对着不存在的目录动手。
            # 找不到任何已装版本时才退回第一项（首装场景就该选清单首位）。
            idx = 0
            # 只下载型组件磁盘上永远不会有它，这次扫描纯属白跑 —— 而且"建卡时不碰磁盘"
            # 是这类组件的契约之一，留着它以后就没法证明"它真的不落盘"。
            if not self.component.download_only:
                installed = {v for v, _p in _main.installed_versions(self.component)}
                for i, cv in enumerate(self._combo_version_list()):
                    if cv.version in installed:
                        idx = i
                        break
            self.version_combo.setCurrentIndex(idx)
            self.version_combo.blockSignals(False)
            self.version_combo._committed_text = self.version_combo.currentText()
            self._refresh_installed_marks()
            return
        self.version_combo.repopulate(labels, preferred=preferred)
        # repopulate 内部 clear() 会连带销毁旧条目的 DecorationRole 数据，
        # 所以装载出口的两条路径都得重挂一次，否则抓取线程回填版本后标记全丢。
        self._refresh_installed_marks()

    def set_versions(self, versions: List[_main.ComponentVersion]) -> None:
        """外部（抓取线程）用新版本列表替换现有列表。"""
        if not versions:
            return
        prev_ver = self._current_version().version if self.component.versions else None
        self.component.versions = versions
        preferred_label = None
        if prev_ver:
            for cv in versions:
                if cv.version == prev_ver:
                    preferred_label = self._display_label(cv)
                    break
        self._reload_combo_items(preferred=preferred_label)
        self._log("ok", f"已获取 {len(versions)} 个版本")

    # ------------------------------------------------------------------
    def _current_version(self) -> _main.ComponentVersion:
        """按显示 label 反查真实版本，兼容 SearchableComboBox 的可编辑文本。

        必须与 `_reload_combo_items` 用同一份清单（含"已装但清单里没有"的合成项）：
        两处不一致时，下拉框里明明显示着某个版本，反查却落回第一项，
        用户以为在切 1.4.1、实际配出去的是 1.4.2。
        """
        text = self.version_combo.currentText().strip()
        versions = self._combo_version_list()
        for cv in versions:
            if self._display_label(cv) == text or cv.version == text:
                return cv
        idx = max(0, self.version_combo.currentIndex())
        return versions[min(idx, len(versions) - 1)]

    # ------------------------------------------------------------------
    def on_install_clicked(self) -> None:
        cv = self._current_version()
        # 多源故障转移：urls_for_current() 返回按 R1 优先级排序的 URL 列表
        urls = cv.urls_for_current()
        if not urls:
            # 优先使用组件配置的 unsupported_platform_hint（如 Docker 引导去 Docker Desktop 官网）
            # 未配置时回退到通用提示
            hint = self.component.unsupported_platform_hint
            if hint:
                self._log("error", hint)
            else:
                self._log("error", f"当前系统 {_main.CURRENT_OS} 无可用下载地址。")
            return

        # 决定下载文件后缀
        if self.component.installer_mode:
            # 从 archive_map 取扩展名（exe / sh），其次从 URL 推断
            ext = cv.archive_map.get(_main.CURRENT_OS, "")
            if not ext:
                first_url = urls[0] if urls else ""
                if first_url.endswith(".exe"):
                    ext = "exe"
                elif first_url.endswith(".sh"):
                    ext = "sh"
                else:
                    ext = "bin"
            suffix = f".{ext}"
        else:
            archive_ext = cv.archive_for_current()
            # 按 archive_ext 计算下载文件后缀：
            #   zip      → .zip
            #   tar.gz   → .tar.gz
            #   exe      → .exe        (单二进制 Windows，如 kubectl.exe)
            #   war      → .war        (单文件，如 jenkins.war)
            #   "" / bin → 空后缀       (单二进制 Linux/Mac，如 kubectl)
            #   其它     → .<archive_ext>
            if archive_ext == "zip":
                suffix = ".zip"
            elif archive_ext in ("tar.gz", "tgz"):
                suffix = ".tar.gz"
            elif archive_ext == "exe":
                suffix = ".exe"
            elif archive_ext == "war":
                suffix = ".war"
            elif archive_ext in ("", "bin"):
                suffix = ""
            else:
                suffix = "." + archive_ext

        download_dir = _main.CONFIG_DIR / self.component.key / "downloads"
        _main.ensure_dir(download_dir)
        dest = download_dir / f"{self.component.key}-{cv.version}{suffix}"

        self.progress.setValue(0)
        self.btn_install.setEnabled(False)
        self.btn_configure.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)

        self.worker = _main.DownloadWorker(urls, dest)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._log)
        self.worker.finished_ok.connect(lambda p: self._on_download_ok(Path(p), cv))
        self.worker.finished_fail.connect(self._on_download_fail)
        self.worker.start()

    # ------------------------------------------------------------------
    def on_open_official_page_clicked(self) -> None:
        """「官网下载」那颗按钮：打开组件官网，由用户自己在那里下载。

        适用于 `official_page_only` 的组件 —— 官方没有可直接下载的安装包地址
        （只给网页入口 / 要真机抓包 / 只能用 npm・pip・插件装）。用户 2026-10-15 的要求：
        与其因为"拿不到直链"就不放这张卡，不如给一颗「官网下载」，点开浏览器自己去下。

        URL 取 `official_url`（R19 那张**人工登记**的表），不从下载地址推导 ——
        与 R19 同一条纪律。没登记就报错而不是打开空页面（护栏已保证这类组件必有登记）。
        """
        url = self.component.official_url
        if not url:
            self._log("error", f"{self.component.display_name} 没有登记官网地址，打不开。")
            return
        _main.QDesktopServices.openUrl(_main.QUrl(url))
        self._log("info", f"已在浏览器打开 {self.component.display_name} 的官网：{url}"
                          "（本工具不代下、不代装，去官网自己下）")

    def on_download_clicked(self) -> None:
        """「开发工具」那颗「下载」：把官方安装包下到用户挑的目录，到此为止。

        为什么不复用 on_install_clicked：那条链的收尾是
        `install_downloaded` → `_configure_after_extract` → `apply_active_version`
        → `_configure_env`，**每一步都在写注册表 / shell rc**（且 `_configure_env`
        连 env_var 为空都会往 PATH 里塞一条）。共用一个槽位，等于给以后
        "顺手在这里加一行配置"留门 —— 分开写才是把"这类组件不碰环境"钉死。
        """
        cv = self._current_version()
        arts = cv.download_artifacts()
        if not any(a.urls for a in arts):
            self._log("error", self.component.unsupported_platform_hint
                      or f"当前系统 {_main.CURRENT_OS} 无可用下载地址。")
            return
        # 先问要哪一种产物，再问下到哪儿：反过来会让用户"选了半天目录又弹一次"。
        art = _main.pick_download_artifact(arts, self,
                                     self.btn_install.mapToGlobal(
                                         _main.QPoint(0, self.btn_install.height())))
        if art is None:
            return          # 菜单上按了 Esc：什么都不该发生
        start = _main.load_download_dir()
        chosen = _main.QFileDialog.getExistingDirectory(self, "选择安装包保存位置", str(start))
        if not chosen:
            return          # 用户点了取消：什么都不该发生
        dest_dir = Path(chosen)
        suffix = (".zip" if art.fmt == "cli"
                  else f".{art.fmt}" if art.fmt and art.fmt != "bin" else "")
        dest = _main._unique_download_path(dest_dir / f"{self.component.key}-{cv.version}{suffix}")
        _main.save_download_dir(dest_dir)

        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.btn_install.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)

        self.worker = _main.DownloadWorker(art.urls, dest, None,
                                     _main._MAGIC_BY_EXT.get(art.fmt, b""))
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._log)
        self.worker.finished_ok.connect(lambda p: self._on_download_only_ok(Path(p), art))
        self.worker.finished_fail.connect(self._on_download_only_fail)
        self.worker.start()

    def _on_download_only_ok(self, path: Path, art: _main.DownloadArtifact) -> None:
        self.progress.setValue(100)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setEnabled(False)
        hint = ("双击这个文件自己装，安装目录由你在安装向导里选。" if art.fmt == "exe"
                else "解压到任意目录即可使用，不需要安装。")
        try:
            size_txt = _main.human_size(path.stat().st_size)
        except OSError as exc:
            # 下载线程说成功了却读不到文件（被杀软秒删、目录被移动）：
            # 记一条错误就返回，别在 Qt 槽里抛出去，也别弹一个指向空气的对话框。
            self._log("error", f"下载报告成功，但读不到文件 {path}：{exc}")
            self._sync_action_buttons()
            return
        self._log("ok", f"已下载到 {path}（{size_txt}，"
                        f"{art.label}）。本工具**不解压、不安装、不配置环境变量** —— {hint}")
        answer = _main.QMessageBox.question(
            self, "下载完成",
            f"{path.name}\n已保存到：\n{path.parent}\n\n要打开所在文件夹吗？",
            _main.QMessageBox.Yes | _main.QMessageBox.No, _main.QMessageBox.Yes)
        if answer == _main.QMessageBox.Yes and not _main._open_in_file_manager(path.parent):
            self._log("warn", f"打不开文件夹，请自己到 {path.parent} 找它")
        self.btn_install.setEnabled(True)

    def _on_download_only_fail(self, message: str) -> None:
        # 取消走的是同一个 finished_fail（沿用 DownloadWorker 的既有约定），
        # 那种情况不该报"失败"，只记一句就好。
        level = "warn" if "取消" in message else "error"
        self._log(level, f"下载未完成：{message}")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setEnabled(False)
        self.btn_install.setEnabled(True)

    # ------------------------------------------------------------------
    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            self.progress.setValue(int(downloaded * 100 / total))
            self.progress.setFormat(f"{_main.human_size(downloaded)} / {_main.human_size(total)}")
        else:
            # 未知总长度
            self.progress.setRange(0, 0)
            self.progress.setFormat(f"{_main.human_size(downloaded)}")

    # ------------------------------------------------------------------
    def _on_download_ok(self, path: Path, cv: _main.ComponentVersion) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)

        try:
            # 落位实现只有一处（模块级 install_downloaded）：界面与真机演练走同一条路径，
            # 演练绿灯才等价于"用户点下去会成功"。
            final = _main.install_downloaded(self.component, cv.version, path,
                                       _main._LoggerAdapter(self._log))
            self._extracted_path = final
            # 自动尝试配置环境变量
            self._configure_after_extract(final)
        except Exception as exc:
            self._log("error", f"安装/配置失败：{exc}\n{_main.traceback.format_exc()}")
        finally:
            # 按钮状态统一交给 _sync_action_buttons（已装的版本不许被重新点亮）
            self.btn_configure.setEnabled(True)
            self._sync_action_buttons()
            # 装成功与否都会在磁盘上留下（或不留）目录，勾的有无正由磁盘决定，
            # 这里统一刷新一次，省得在两个分支各写一遍。
            self._refresh_installed_marks()
            # _detect_status 会根据探测结果再决定 btn_configure 是否禁用
            self._detect_status()

    # ------------------------------------------------------------------
    def _run_installer(self, installer_path: Path, target_dir: Path) -> None:
        """静默运行安装器（用于 Miniconda 之类）。实现见模块级 _run_installer_for。"""
        _main._run_installer_for(self.component, installer_path, target_dir, self._log)

    # ------------------------------------------------------------------
    def _on_download_fail(self, msg: str) -> None:
        self.btn_configure.setEnabled(True)
        self._sync_action_buttons()
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        if msg and msg != "用户取消":
            _main.QMessageBox.warning(self, "下载失败", f"{self.component.display_name} 下载失败：\n{msg}")

    # ------------------------------------------------------------------
    def on_cancel_clicked(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()

    # ------------------------------------------------------------------
    def on_uninstall_clicked(self) -> None:
        """
        点击卸载按钮：弹二次确认 → 调 component.uninstall(version) → 输出日志 → 刷新状态。

        卸载是不可逆操作，所以先弹 QMessageBox.question 确认；用户点 Yes 才执行。
        """
        # spec §5 运行中禁止卸载。按钮置灰是第一道，这里是第二道：置灰状态可能被
        # 其它同步路径顶掉，而"边跑边删目录"删掉的正是服务进程正在写的日志与数据。
        if self.component.launch is not None and \
                _main.SERVICE_MANAGER.status(self.component.key, self.component).state == "running":
            reason = "请先停止运行中的 %s 再卸载" % self.component.display_name
            self._log("warn", reason)
            _main.QMessageBox.warning(self, "无法卸载", reason)
            self._refresh_launch_state()
            return
        cv = self._current_version()
        # 二次确认：卸载会删除本地目录、清理环境变量与 PATH，不可逆。
        # 正文（"删哪些" + "数据去哪儿"）由纯函数 uninstall_confirm_text 统一拼，
        # 后者按组件区分数据去处 —— 计划一那句对 Nacos 是半句真话。
        # 确认框尾巴按组件是否多版本分叉：多版本现在只动选中的那个版本，
        # 旧的"以实际装着的目录为准"在多选并存场景下会变成假话；
        # 非多版本组件的原文逐字保持不变。
        tail = ("（只删除选中的这一个版本，其他已装版本不动；"
                "若删掉的正是当前生效版本，会自动切到剩余里版本号最高的那个）"
                if self.component.multi_version else
                "（若所选版本与实际安装版本不一致，会以实际装着的目录为准）")
        reply = _main.QMessageBox.question(
            self,
            "确认卸载",
            f"确定要卸载 {self.component.display_name} {cv.version} 吗？\n\n"
            f"将执行以下操作：\n"
            f"{_main.uninstall_confirm_text(self.component)}\n\n"
            f"{tail}",
            _main.QMessageBox.Yes | _main.QMessageBox.No,
            _main.QMessageBox.No,
        )
        if reply != _main.QMessageBox.Yes:
            self._log("info", f"已取消卸载 {self.component.display_name} {cv.version}")
            return
        try:
            # R3.19：若之前为了让**这个版本**生效而提权改过系统变量，先按原文还原再删目录。
            # 不还原的话，系统 PATH 最前会留下一条指向即将消失的目录的死条目 ——
            # 那比"没生效"更糟：全机所有程序的 PATH 里都多一条失效路径。
            fix_entry = _main.load_machine_fix_map().get(self.component.key)
            if fix_entry and _main.EnvManager._same_path(
                    str(fix_entry.get("home") or ""),
                    str(self.component.install_dir(cv.version))):
                back = _main.revert_machine_fix(
                    self.component,
                    log=lambda m: self._log("error" if ("失败" in m or "未完成" in m)
                                            else "info", m))
                if not back.get("ok"):
                    self._log("error", "系统变量还原未完成，已中止卸载以免留下失效条目："
                              + str(back.get("error") or ""))
                    return
                self._refresh_external_section()
            self._log("info", f"开始卸载 {self.component.display_name} {cv.version}")
            # 调用 Component.uninstall 执行实际卸载，返回中文摘要
            summary = self.component.uninstall(cv.version)
            self._log("ok", f"卸载完成：{summary}")
            # 磁盘上少了一个版本目录，下拉框里它的勾必须同时消失
            self._refresh_installed_marks()
            # 卸载后重新检测状态，刷新状态胶囊与按钮启用状态
            self._detect_status()
        except Exception as exc:
            self._log("error", f"卸载失败：{exc}")

    # ------------------------------------------------------------------
    def _path_hit_version(self) -> Optional[str]:
        """按 PATH 顺序找出命令行**实际**会命中的"本工具装的那个版本"。

        读的是持久层 PATH（新开终端真正会用到的那份），不是 os.environ —— 后者只是本进程
        启动时的快照，可能被之前的安装/切换改脏。找不到属于本组件的条目时返回 None。
        """
        comp = self.component
        if not comp.exec_name:
            return None
        root = str(_main.CONFIG_DIR / comp.key)
        names = [comp.exec_name]
        if _main.CURRENT_OS == "Windows" and not os.path.splitext(comp.exec_name)[1]:
            names = [comp.exec_name + s for s in (".exe", ".cmd", ".bat", "")]
        for entry in _main.EnvManager.read_user_path_entries():
            if not _main.EnvManager._under_root(entry, root):
                continue
            for ver, path in _main.installed_versions(comp):
                bin_dir = (path / comp.path_subdir) if comp.path_subdir else path
                if not _main.EnvManager._same_path(str(bin_dir), entry):
                    continue
                for name in names:
                    if (bin_dir / name).exists():
                        return ver
        return None

    def _expected_bin_dir(self, version: str) -> Path:
        """生效版本"应当"出现在 PATH 里的那个目录（写变量与复验共用一套算法）。"""
        home = self.component.install_dir(version)
        return home / self.component.path_subdir if self.component.path_subdir else home

    def _path_effective_check(self, active: Optional[str]) -> Tuple[str, Optional[str]]:
        """复验：按系统合成的 PATH 顺序，命令行第一个命中的目录是不是生效版本该在的那个。

        返回 ("ok", None) | ("shadowed", 抢走命令的目录) | ("unknown", None)。
        unknown 含"拿不到合成环境"和"PATH 里根本没有这个命令"两种，都不许当成通过：
        前者是没测，后者说明命令压根不在 PATH 上。

        为什么必须有这一步（2026-09-30 真机实测）：用户 PATH 整体排在系统 PATH 之后，
        且系统 PATH 里的 %JAVA_HOME%\\bin 是按**系统**表展开定死的 —— 我们把
        JAVA_HOME 与自己的 PATH 条目都写对了，命令行仍可能命中用户自装的那个版本。
        只报"已切到 X"就是假话。
        """
        if not active or not self.component.exec_name:
            return "unknown", None
        composed = _main.EnvManager.composed_env()
        path_value = composed.get("PATH")
        if not path_value:
            return "unknown", None
        exec_name = self.component.exec_name
        names = ([exec_name] if _main.CURRENT_OS != "Windows"
                 else ([exec_name + s for s in (".exe", ".cmd", ".bat", "")]
                       if not os.path.splitext(exec_name)[1] else [exec_name]))
        expected = str(self._expected_bin_dir(active))
        # 走目录清单缓存，而不是逐条 os.path.exists：合成 PATH 上有几十个条目，
        # 每个条目 × 4 个后缀，而这张表在 88 张卡建卡时会被重复问同一批目录
        # 两万次上下（详见 _path_dir_listing 的说明）。
        upper = (lambda s: s.upper()) if sys.platform == "win32" else (lambda s: s)
        for entry in path_value.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            try:
                listing = _main._path_dir_listing(entry)
            except (OSError, ValueError):
                continue
            if any(upper(n) in listing for n in names):
                return ("ok", None) if _main.EnvManager._same_path(entry, expected) else ("shadowed", entry)
        return "unknown", None

    def detail_lines(self) -> list:
        """组装详情正文，返回 [(小标题, 段落), ...] —— 固定四段式。

        「它是什么」与「怎么用」来自两张登记表；「本工具会替你做什么」由能力位
        现场派生（不新写文案，避免第二份真相）；「平台说明」登记了才显示。
        data_note（数据去处）与版本清单**不进详情**：前者归卸载确认框，
        后者下拉框里就在 —— 详情只回答"这是什么、怎么用"两个问题。
        """
        comp = self.component
        out: list = []
        if getattr(comp, "summary", ""):
            out.append(("它是什么", comp.summary))
        usage = _main.COMPONENT_USAGE.get(comp.key, "")
        if usage:
            out.append(("怎么用", usage))

        # 本工具替你做的事：全部从既有登记派生，措辞统一用分号分隔的短句。
        if comp.download_only:
            todo = ["官方安装包下到你在弹窗里选的目录（记住上次位置）",
                    "不解压、不写环境变量、不代跑安装程序：安装由你自己确认"]
        else:
            todo = ["镜像优先下载，失败自动换源",
                    "解压到本工具目录并写好环境变量与 PATH",
                    "装完后台自检版本号回填到卡片"]
            spec = comp.launch
            if spec is not None:
                # 派生口是「主口 + 偏移」，不是绝对端口（真机 2026-10-12 我自己把
                # etcd 显示成「端口 2379、1」过一次）。算法与 choose_ports() 一致。
                ports = [spec.main_port] + [spec.main_port + int(o)
                                            for o in spec.port_offsets]
                ports += [int(p) for p in spec.extra_ports]
                stop = "一键启停"
                if spec.console_path:
                    stop += f"，控制台在 {spec.main_port}{spec.console_path}"
                todo.append(f"{stop}（端口 {'、'.join(str(p) for p in ports)}，"
                            f"整簇都在听才算运行中）")
            if _main.supports_external_takeover(comp):
                todo.append("可接管你本机已装的那一份，并可一键还原")
        out.append(("本工具会替你做什么", "；".join(todo) + "。"))

        if comp.unsupported_platform_hint:
            out.append(("平台说明", comp.unsupported_platform_hint))
        return out

    def _open_wsl_wizard(self) -> None:
        """打开主窗的 WSL 向导（卡片与标题栏共用同一个对话框实例）。"""
        self.wsl_requested.emit()

    def on_detail_clicked(self) -> None:
        """打开详情对话框。无副作用：只读地展示登记表里已有的事实。"""
        dlg = _main.ComponentDetailDialog(self.component, self.detail_lines(), self)
        # 2026-10-13 修：用 show() 而不是 exec()，modal=False 让 eventFilter 能捕获
        # "点击外部"的动作（exec() 会变成真正模态，把鼠标事件全吞掉）。show() 后
        # 对话框虽然还带"知道了"按钮，但用户习惯外点即关，体验更好。
        dlg.setModal(False)
        dlg.show()

    def active_version(self) -> Optional[str]:
        """当前生效版本：active 登记表 → 持久层 XXX_HOME 反推 → PATH 实际命中。

        第三级兜底是必要的：老配置既没登记表、HOME 又被手工清过时，PATH 里那条
        本工具写入的条目就是唯一的事实来源。
        """
        if not self.component.multi_version:
            return None
        return (_main.load_active_map().get(self.component.key)
                or _main.infer_active_from_env(self.component)
                or self._path_hit_version())

    def _log_verification_hint(self, since_epoch: Optional[float] = None) -> None:
        """切换后给出可直接复制的校验命令，并点名"比这次切换更早、还开着的终端"。

        写这么细是因为真实踩过的坑：Windows 是把环境块**复制**给新进程的，
        Windows Terminal 的新标签页、IDE 里新开的终端都还继承着宿主进程那份旧环境。
        用户按"重开终端"的字面意思操作，看到的仍然是切换前的版本，
        于是以为切换没生效（2026-09-30 真机反馈）。
        只讲道理没用——同一天实测：注册表与新进程都是 1.4.1，用户屏幕上那个
        PowerShell 进程创建于切换前 12 分钟。所以这里直接把 pid 和起始时间摆出来。
        """
        exe = self.component.exec_name or ""
        args = " ".join(self.component.version_args or ["--version"])
        lines = ["校验是否真生效（必须在切换之后新启动的终端里跑）："]
        if exe:
            lines.append(f"    where {exe}      ← 应当指向上面那个目录")
            lines.append(f"    {exe} {args}")
        if self.component.env_var:
            lines.append(f"    echo %{self.component.env_var}%      ← cmd 里看变量值")
        lines.append("不想重开，可以在当前 PowerShell 里先刷新再验：")
        lines.append("    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')"
                     " + ';' + [Environment]::GetEnvironmentVariable('Path','User')")
        lines.append("注意：Windows Terminal 的新标签页、IDE 里新开的终端都还是旧环境，"
                     "要把整个 Windows Terminal / IDE 关掉重开。")
        if since_epoch:
            try:
                procs = _main.list_shell_processes()
            except Exception:
                procs = []
            lines.extend(_main.stale_shell_lines(procs, since_epoch, os.getpid()))
        self._log("info", "\n".join(lines))

    # ------------------------------------------------------------------
    def _apply_active(self, version: str) -> bool:
        """把指定版本设为生效版本；成功后写登记表并刷新界面。

        返回: bool  成功与否。失败原因已在日志里，界面不再处理异常。

        刷新已装勾是必要的：apply_active_version 中途失败会回滚磁盘/环境状态，
        生效版本变了也可能连带影响状态探测读到的目录，图标得跟磁盘重新对齐。
        """
        t_switch = time.time()
        # §4.3 两条键互斥 + R3.19：接管过外部版本、或为系统变量做过提权改动时，
        # 都要先原样还原再切工作区版本，否则系统 PATH 最前还插着旧那条，
        # 切完命令行仍是旧版本。
        def _release_sink(text: str) -> None:
            low = str(text)
            level = ("error" if ("失败" in low or "未完成" in low or "未通过" in low)
                     else "warn" if ("取消" in low or "未能" in low or "仍" in low)
                     else "info")
            self._log(level, low)

        release = _main.release_machine_state(
            self.component, log=_release_sink,
            reason="切回工作区版本")
        # 不再回放 release["steps"]：底层各函数已把每一步打进 log（2026-10-21 修
        # "同一步打印两遍"）。这里只处理终态。
        if not release.get("ok"):
            self._log("error", "接管/系统变量还原未完成，已中止本次切换以免留下半截状态："
                      + str(release.get("error") or ""))
            return False
        try:
            steps = _main.apply_active_version(self.component, version)
        except _main.SwitchError as exc:
            self._log("error", str(exc))
            return False
        for step in steps:
            self._log("error" if ("失败" in step) else "ok", step)
        _main.save_active_version(self.component.key, version)
        # 写完必须复验"新终端实际会命中谁"：PATH 是系统段 + 用户段拼出来的，
        # 我们写的是用户段，完全可能被前面那条（用户自装的版本）压住。
        verdict, shadow = self._path_effective_check(version)
        if verdict == "ok":
            self._log("ok", f"复验通过：新开的终端会用到 {self._expected_bin_dir(version)}")
            self._log_verification_hint(t_switch)
        elif verdict == "shadowed":
            self._handle_shadowed_after_switch(version, shadow, t_switch)
        else:
            self._log("warn", "未能复验新终端会用到哪个目录（拿不到系统合成后的环境），"
                              "请重开一个终端手动确认一次。")
            self._log_verification_hint(t_switch)
        self._refresh_installed_marks()
        self._detect_status()
        return True

    def _handle_shadowed_after_switch(self, version: str, shadow: Optional[str],
                                      since_epoch: float) -> None:
        """切换后仍被更靠前的目录压住时，**能自己解决的就自己解决**（R3.19）。

        判据是"抢命令的那条写在哪一段"（shadow_location），不是猜：
          · 写在用户段 → 把我们那条让到用户段最前即可，**零提权**；
          · 写在系统段 → 用户级永远压不住，问一次是否用管理员权限插到系统段最前；
          · 两段都找不到 → 只如实报告，不提权（改系统变量也未必对症）。
        前两步只在白名单组件上做：那是"要不要动用户机器 PATH"的显式白名单，
        非白名单组件维持"只报告"的老行为（R3.17 的同一道闸）。
        """
        exec_name = self.component.exec_name or ""
        expected = str(self._expected_bin_dir(version))
        head = (f"环境变量已切到 {version}，但复验发现新终端里 {exec_name} 仍会先命中 "
                f"{shadow} —— 它排在 PATH 更前面（多半是系统级变量或你自己装的版本）。")
        where = _main.shadow_location(str(shadow or "")) if shadow else "outside"
        whitelisted = _main.supports_external_takeover(self.component)

        # ① 用户段内部还有救：把我们那条让到用户段最前，再复验一次（零提权）
        if whitelisted and where == "user":
            try:
                if _main.prepend_user_path_entry(expected):
                    self._log("info", f"已把本工具那条提到用户 PATH 最前：{expected}")
            except Exception as exc:  # noqa: BLE001
                self._log("warn", f"调整用户 PATH 顺序失败：{exc}")
            verdict2, shadow2 = self._path_effective_check(version)
            if verdict2 == "ok":
                self._log("ok", f"复验通过：新开的终端会用到 {expected}")
                self._log_verification_hint(since_epoch)
                return
            if shadow2:
                shadow = shadow2
                where = _main.shadow_location(str(shadow))

        # ② 系统段压着：只有改系统 Path 才有用，问一次（确认框 + UAC）
        if whitelisted and where == "machine":
            self._log("warn", head + "它在**系统变量**里，用户级写入压不住；"
                                    "本工具可以帮你把这个版本插到系统 PATH 最前"
                                    "（原有条目一条不删，随时可还原）。")
            res = _main.apply_workspace_machine(
                self.component, version,
                confirm_machine=self._confirm_machine_takeover,
                log=lambda m: self._log(
                    "error" if ("失败" in str(m) or "未通过" in str(m)
                                or "未完成" in str(m))
                    else "warn" if ("取消" in str(m) or "未能" in str(m))
                    else "info", m))
            if res.get("ok"):
                self._log("ok", "已在系统级生效；新开的终端/IDE 才会读到新值")
                self._log_verification_hint(since_epoch)
                self._refresh_external_section()
            elif res.get("verdict") == "cancelled":
                self._log("warn", "已取消，系统变量未改动；命令行仍会用上面那个版本")
            else:
                self._log("error", str(res.get("error") or "改系统变量未成功"))
            return

        # ③ 两段都不是 / 不在白名单：如实报告，并说清为什么本工具不接手
        self._log("warn", head + "它不在本工具的工作目录里，也不在本工具能改的"
                                "「用户变量」里；需要你自己在「系统变量」的 PATH 里"
                                "删掉/后移那条，再重开终端。")

    # ------------------------------------------------------------------
    def on_configure_clicked(self) -> None:
        """仅配置环境变量。

        多版本组件：把下拉框选中的版本设为"当前生效版本"（PATH 只留它一条）。
        其他组件：沿用原有"取已装目录里语义版本最高的一个"的行为，不写 active 表。

        为什么必须按下拉框选中的版本生效，而不是照旧取"目录名字典序最后一个"：
        jdk 的下拉清单是内置大版本串 21/17/11/8，装了 21、17、8 时，
        字符串排序会把 jdk-8 排到最后，
        于是用户明明选的是 21，配出来的却是 8 —— 生效版本与所选版本必须一致。
        """
        install_root = _main.CONFIG_DIR / self.component.key
        if not install_root.exists():
            self._log("warn", "尚未下载，请先执行“安装”。")
            return
        ordered = _main.installed_versions(self.component)
        if self.component.multi_version:
            if not ordered:
                self._log("warn", (f"未找到符合 {self.component.key}-<版本号> 命名的安装目录；"
                                   f"可用『清理残留 PATH』自愈后重试"))
                return
            chosen = self._current_version().version
            if chosen not in [v for v, _p in ordered]:
                self._log("warn", (f"下拉框选的是 {chosen}，磁盘上没有对应目录；"
                                   f"已装：{'、'.join(v for v, _p in ordered)}"))
                return
            self._apply_active(chosen)
            return
        if not ordered:
            self._log("warn", "未找到已解压的安装目录。")
            return
        self._configure_env(ordered[0][1])
        self._detect_status()

    # ------------------------------------------------------------------
    def _configure_after_extract(self, install_path: Path) -> None:
        """安装/解压收尾时配置环境变量。

        多版本组件走**原子切换**（写 XXX_HOME + 把本组件在 PATH 里的条目收敛成这一条
        + 记 active 表），不能再走 _configure_env 的"追加一条"：装两个版本就会在 PATH 里
        留下两条，命令行按顺序只认第一条，界面上说的"生效版本"就成了假话
        （2026-09-30 用户真机反馈：bun 1.4.2 与 1.4.1 同时在 PATH）。
        非多版本组件保持原有行为逐字不变。
        """
        comp = self.component
        # 装完先核对"要放进 PATH 的目录里有没有可执行文件"（R3.22 的教训）：
        # 指错目录只会表现为"切了但没生效"，用户无从自查，必须当场点名。
        ok_dir, where = _main.verify_bin_dir(comp, install_path)
        if not ok_dir:
            self._log("warn",
                      f"装完核对：本工具准备放进 PATH 的目录里没有 {comp.exec_name}"
                      + (f"，实际它在 {where}" if where else "（整个安装目录里都没找到）")
                      + "。这会让「切换生效版本」失效 —— 命令行仍会命中机器上原有的那个。"
                        "请把这段日志发给开发者，需要修正该组件的 path_subdir。")
        if not comp.multi_version:
            self._configure_env(install_path)
            return
        version = _main.version_from_install_dir(comp, install_path)
        if not version:
            # 目录名不符合 <key>-<version> 约定（历史安装），无法登记生效版本，
            # 退回老路径配置，至少让组件可用
            self._configure_env(install_path)
            return
        self._log("info", f"多版本组件：把新装的 {version} 设为生效版本并收敛 PATH")
        self._apply_active(version)

    # ------------------------------------------------------------------
    def _configure_env(self, install_path: Path) -> None:
        """根据组件类型写入 XXX_HOME 与 PATH。"""
        try:
            comp = self.component
            bin_dir = install_path / comp.path_subdir
            if comp.env_var:
                if _main.CURRENT_OS == "Windows":
                    _main.EnvManager.set_windows_user_env(comp.env_var, str(install_path))
                    _main.EnvManager.append_windows_path(str(bin_dir))
                else:
                    rc = _main.EnvManager.set_unix_env(comp.env_var, str(install_path))
                    _main.EnvManager.append_unix_path(str(bin_dir))
                    self._log("info", f"已写入 {rc}")
                self._log("ok", f"设置 {comp.env_var}={install_path}")
                self._log("ok", f"追加 PATH：{bin_dir}")
            else:
                if _main.CURRENT_OS == "Windows":
                    _main.EnvManager.append_windows_path(str(bin_dir))
                else:
                    rc = _main.EnvManager.append_unix_path(str(bin_dir))
                    self._log("info", f"已写入 {rc}")
                self._log("ok", f"追加 PATH：{bin_dir}")

            if _main.CURRENT_OS != "Windows":
                self._log("warn", "请打开新的终端或执行 `source ~/.zshrc` 让环境变量生效。")
        except Exception as exc:
            self._log("error", f"环境变量配置失败：{exc}")
