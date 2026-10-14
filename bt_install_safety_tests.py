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
        # 造任何 QWidget 之前必须先有 QApplication，否则 Qt 直接 abort()
        # （症状是进程以 127 退出、日志里一行 traceback 都没有）。
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])
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
        from PySide6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])
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
# 归档解压安全护栏
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


if __name__ == "__main__":
    unittest.main(verbosity=2)