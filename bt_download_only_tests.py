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
import unittest
from pathlib import Path

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
# 复用对面那套沙箱：它把 CONFIG_DIR / CONFIG_FILE / shell rc / 注册表读写全重定向到临时目录。
# 本文件的用例要真建卡片，不沙箱化就会去扫用户真实的 ~/.env-tools（甚至写他的 config.json）。
from bt_multiversion_tests import EnvSandbox as _EnvSandbox  # noqa: E402

# 造任何 QWidget 之前必须先有 QApplication，否则 Qt 直接 abort() —— 症状是进程以
# 127 退出、日志里一行 traceback 都没有，极易被误判成"命令没跑起来"。
# 整套 discover 时对面 bt_grid_layout_tests 会先把 app 建好，所以这条只在**单独跑本文件**时才暴露。
from PySide6.QtWidgets import QApplication  # noqa: E402
_APP = QApplication.instance() or QApplication([])

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

    def test_new_tab_is_the_third_and_holds_the_eleven_keys(self):
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

    def test_visible_component_count_is_37(self):
        """**全仓库唯一一处**写死界面可见组件数的地方（26 老 + 11 新）。

        其它套件的数字都改成从成员表派生，只有这里保留绝对值：
        加组件时必须在这里过一次手，逼着人确认"这个数字变了是有意为之"。
        """
        visible = sum(len(v) for v in self.groups.values())
        self.assertEqual(visible, 37)
        self.assertEqual(len(self.components), 38, "37 可见 + 隐藏的 erlang")


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
        orig_get = main.requests.get
        self.addCleanup(setattr, main.requests, "get", orig_get)

        def fake_get(url, *a, **k):
            calls.append(url)
            return _Resp(body)

        main.requests.get = fake_get
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
        orig_get = main.requests.get
        self.addCleanup(setattr, main.requests, "get", orig_get)
        main.requests.get = lambda url, *a, **k: _Resp(b"PK\x03\x04" + b"z" * 20000)
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
        commercial = {"idea", "pycharm", "clion", "webstorm", "goland", "datagrip"}
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
                   "mirrors.huaweicloud.com")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
