"""组件图标资产的护栏测试（离线，不联网）。

跑法：`.venv/Scripts/python.exe -u bt_icon_assets_tests.py`

**这一套钉的是"图标必须是真的官网标识"**，钉死 2026-10-14 之前的两类事故：

  ① 手绘伪造图
     原来的 assets/component-icons/ 里 87 个"图标"全是采集脚本**画**出来的：
     `<rect width="128" height="128" rx="24">` 加一条粗糙的 `<path>`。
     python.svg 是黄方块 + 蓝波浪线，node.svg 是黄方块 + 绿团 —— 都不是官方 Logo。
     它们能正常渲染，所以界面看不出问题，只是"看着像但不是"。

  ② 静默裁切
     `setDevicePixelRatio()` 设在了 `QPainter` **之前**，导致 QPainter 的逻辑视口
     被 DPR 缩小，QSvgRenderer 按 SVG 的 defaultSize（本项目多为 128×128）适配该
     视口，渲染结果比画布大一截 —— **每个图标都被放大裁掉一大块**。表现极像资产
     损坏，极难定位。正确顺序是"先画、后设 DPR"。

所以这里不只测"能不能渲染出图"，还测：
  · 资产**不是**手绘伪造图（特征签名 + 逐个覆盖）
  · 渲染结果的**逻辑尺寸**正好等于槽位尺寸（多了就会被 QLabel 裁掉）
  · 资产内容**不是 HTML 网页**（采集脚本把 404/错误页存成了 .svg）
"""
import os
import re
import struct
import sys
import unittest
from pathlib import Path

import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = Path(_btprelude.REPO_ROOT)

import main  # noqa: E402


# 采集脚本手绘图共有的特征签名：一张 128×128 圆角底板 + 若干简单 path。
# 这不是"风格不像官方"，而是**确凿的伪造证据**：全项目没有一个真 Logo
# 是长这样的（官方标识要么是纯路径字形，要么是带真实笔触的复杂图形）。
FAKE_DRAWN = re.compile(r'width="128"\s+height="128"\s+rx="24"', re.S)
# 常见品牌标识的规范化特征：Simple Icons 一律是 viewBox="0 0 24 24"；
# 其余来源（官方仓库里的 SVG）用别的 viewBox，但绝不会是上面那个 128 圆角底板。
SI_VIEWBOX = re.compile(r'viewBox="0 0 24 24"', re.I)


def setUpModule():
    _btprelude.ensure_app()


class IconAssetsAreReal(unittest.TestCase):
    """资产必须是真实品牌标识，不能是手绘伪造图。"""

    @classmethod
    def setUpClass(cls):
        cls.comps = main.build_components()
        cls.dir = main.icon_asset_dir()

    def test_asset_dir_exists(self):
        self.assertTrue(self.dir.is_dir(), f"图标资产目录不存在：{self.dir}")
        self.assertTrue(any(self.dir.iterdir()), f"图标资产目录是空的：{self.dir}")

    def test_no_hand_drawn_fake_icons(self):
        """**任何**资产都不得带手绘伪造特征签名。

        用资产目录全量扫而不是逐组件找：伪造图可能挂在没人用的文件名下，
        哪天有人误改名就会被卡片捡起来显示。
        """
        fakes = []
        for f in sorted(self.dir.iterdir()):
            if f.suffix.lower() not in (".svg",):
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            if FAKE_DRAWN.search(text):
                fakes.append(f.name)
        self.assertEqual(
            fakes, [],
            f"这些是手绘伪造图（128×128 圆角底板特征），不是官网标识：{fakes}",
        )

    def test_no_html_page_saved_as_image(self):
        """资产不得是 HTML 网页。

        2026-10-14 实测：采集脚本把 7 个错误页/网页存成了 .svg/.png
        （deno.svg 竟是 57KB 的 HTML）。渲染器能挡下（SVG 解析失败 → 回色块），
        但文件留在仓库里，下一个人会以为"图标已经有了"。
        """
        bad = []
        for f in sorted(self.dir.iterdir()):
            if f.suffix.lower() not in (".svg", ".png"):
                continue
            head = f.read_bytes()[:200].lstrip().lower()
            if head.startswith(b"<!doctype") or head.startswith(b"<html"):
                bad.append(f.name)
        self.assertEqual(bad, [], f"这些文件其实是 HTML 网页：{bad}")

    def test_svg_assets_all_parse(self):
        """SVG 必须真的能被 QSvgRenderer 解析。"""
        from PySide6.QtSvg import QSvgRenderer
        broken = []
        for f in sorted(self.dir.glob("*.svg")):
            try:
                if not QSvgRenderer(str(f)).isValid():
                    broken.append(f.name)
            except Exception:
                broken.append(f.name)
        self.assertEqual(broken, [], f"这些 SVG 解析失败（会静默退化成色块）：{broken}")

    def test_png_assets_are_real_pngs_and_big_enough(self):
        """PNG 必须是真 PNG，且尺寸不小于 48px（小图放大只会糊）。"""
        tiny = []
        for f in sorted(self.dir.glob("*.png")):
            b = f.read_bytes()
            if len(b) < 24 or b[:8] != b"\x89PNG\r\n\x1a\n":
                tiny.append(f"{f.name}(不是PNG)")
                continue
            w, h = struct.unpack(">II", b[16:24])
            if min(w, h) < 48:
                tiny.append(f"{f.name}({w}x{h} 太小)")
        self.assertEqual(tiny, [], f"这些 PNG 不合格：{tiny}")

    def test_asset_filename_matches_a_real_component_key(self):
        """资产文件名必须就是某个组件的 key。

        按 key 探测是刻意设计（不维护映射表），代价是文件名必须与 key 一致。
        对不上就等于这个图标永远不会被显示出来 —— 一份躺着没人用的资产。
        """
        keys = {c.key for c in self.comps}
        orphans = [f.name for f in sorted(self.dir.iterdir())
                   if f.stem not in keys]
        self.assertEqual(
            orphans, [],
            f"这些资产名不对应任何组件 key（永远不会被显示，建议删除）：{orphans}",
        )


class IconRendersUncropped(unittest.TestCase):
    """渲染结果的逻辑尺寸必须正好等于槽位 —— 多了会被 QLabel 裁掉。

    这是 2026-10-14 用户截图里"图标缺了一块"的直接护栏。
    """

    @classmethod
    def setUpClass(cls):
        _btprelude.ensure_app()
        cls.comps = main.build_components()
        main._ICON_PIXMAP_CACHE.clear()

    def test_rendered_pixmap_never_exceeds_the_slot(self):
        """逻辑尺寸**不许超过**槽位 —— 超过就被 QLabel 裁掉一块。

        这就是 2026-10-14 用户截图里"图标缺了一块"的直接护栏。

        允许小于：非正方形的 SVG 按比例缩放后短边会小于槽位，QLabel 居中显示，
        那是正常表现（官方标识本来就有方的也有横的）。
        """
        wrong = []
        for c in self.comps:
            pm = main.load_component_icon_pixmap(
                c.key, main.ICON_BOX_PX * main.ICON_RENDER_SCALE)
            if pm is None:
                continue
            dpr = pm.devicePixelRatio() or 1.0
            w, h = pm.width() / dpr, pm.height() / dpr
            if w > main.ICON_BOX_PX + 1 or h > main.ICON_BOX_PX + 1:
                wrong.append(f"{c.key}: 逻辑 {w:.0f}x{h:.0f} > {main.ICON_BOX_PX}")
        self.assertEqual(wrong, [], f"这些图标会被槽位裁掉：{wrong}")

    def test_rendered_pixmap_is_not_a_banner_strip(self):
        """宽高比不许极端 —— 横幅/字标缩到 32px 会糊成一团线。

        实测踩过：采到的 ActiveMQ/seata/k9s 是带文字的横幅，
        在 32px 方格里只剩一条色带。那不是"官方标识"，是没选对素材。
        """
        stripes = []
        for c in self.comps:
            pm = main.load_component_icon_pixmap(
                c.key, main.ICON_BOX_PX * main.ICON_RENDER_SCALE)
            if pm is None:
                continue
            w, h = pm.width(), pm.height()
            if min(w, h) <= 0:
                continue
            ratio = max(w, h) / min(w, h)
            if ratio > 3.0:
                stripes.append(f"{c.key}: {w}x{h} (宽高比 {ratio:.1f})")
        self.assertEqual(
            stripes, [],
            f"这些是横幅/字标而不是标识（32px 下会糊成一条线）：{stripes}",
        )

    def test_render_never_raises_for_any_component(self):
        """渲染不许抛异常 —— 图标是装饰，不能把主窗口带崩。"""
        for c in self.comps:
            with self.subTest(组件=c.key):
                pm = main.load_component_icon_pixmap(
                    c.key, main.ICON_BOX_PX * main.ICON_RENDER_SCALE)
                self.assertTrue(pm is None or not pm.isNull(),
                                f"{c.key} 渲染出了空图")

    def test_device_pixel_ratio_is_set_after_painting(self):
        """源码级护栏：DPR 必须在 QPainter 结束**之后**设置。

        设在前面的后果：QPainter 的逻辑视口被 DPR 缩小，QSvgRenderer 按 SVG 的
        defaultSize 去适配它，渲染结果比画布大一截 —— 每个图标都被裁掉一块。
        这条挡的是"有人为了顺手把两行调换一下"这种看不出后果的改动。
        """
        import inspect
        src = inspect.getsource(main._render_icon_file)
        painter_end = src.find("painter.end()")
        dpr_set = src.find("setDevicePixelRatio")
        self.assertNotEqual(painter_end, -1, "_render_icon_file 里没找到 painter.end()")
        self.assertNotEqual(dpr_set, -1, "_render_icon_file 里没找到 setDevicePixelRatio")
        self.assertLess(
            painter_end, dpr_set,
            "setDevicePixelRatio 必须排在 painter.end() 之后：设之前会让 QPainter "
            "的逻辑视口被 DPR 缩小，SVG 按 defaultSize 适配后比画布大，图标被裁掉一块",
        )


class IconCoverage(unittest.TestCase):
    """没有图标的组件必须**逐一登记原因**，而不是默默回色块。

    分两类，原因完全不同：
      · NO_OFFICIAL_LOGO —— 项目**确实没有**可用的官方图形标识（查过官网与仓库）
      · PENDING_SOURCE    —— 项目**有**官方标识，但本轮没采到
    两类混在一起会导致"少一个"与"忘了采"在报告上完全一样。
    """

    NO_OFFICIAL_LOGO = {
        "ninja": "官网 ninja-build.org 是纯文字页（全文无任何图片引用），"
                 "官方仓库 ninja-build/ninja 内 0 个图片文件，"
                 "ninja-build.github.io 也没有图片资源。"
                 "其视觉形象只有终端里的 ASCII 忍者脸与字标，没有可用的图形标识。",
    }

    # 已查遍以下来源仍未取到合格素材（每条都实际试过，不是没试）：
    #   · Simple Icons CDN（slug 存在性已逐一探测，多个为 404 —— 该库已因商标原因下架）
    #   · 项目官方 GitHub 仓库（API 检索全量图片清单）
    #   · 项目官网 HTML（提取 <img>/<link> 里的 logo/icon 资源）
    #   · 官方 README 的图片引用
    # 2026-10-14 第二轮：Simple Icons 确认全部没有（全量索引 3307 条逐一查过），
    # 改从**各项目官方仓库/官网**直取，又补上 6 个（来源如下，均已肉眼复核 32px 观感）：
    #   · nacos           alibaba/nacos  develop  console-ui-next/public/img/nacos-icon.png
    #   · seata           apache/incubator-seata  2.x  console-fe/public/img/seata_logo_small.jpeg
    #                     （200×200 蓝底白 S，原为 JPEG，入库时转成真 PNG）
    #   · k9s             derailed/k9s  master  assets/imhotep_logo.png（官网 k9scli.io 同款）
    #   · docker-compose  docker/compose  main  logo.png
    #                     （README 第 17 行自己标注 "Docker Compose Logo"，是官方章鱼标识）
    #   · windterm        kingToolbox/WindTerm  master  images/WindTerm_icon_1024x1024.png
    #   · visual-studio   visualstudio.microsoft.com 官方品牌资源
    #                     wp-content/uploads/2019/02/BrandVisualStudioWin2019-2.svg（viewBox 70×70）
    PENDING_SOURCE = {
        "protoc": "Simple Icons 的 protocolbuffers 已下架（探测 404）；"
                  "protocolbuffers/protobuf 仓库全量树里只有 3 张文档配图"
                  "（docs/design/editions/images/*），无标识文件；"
                  "protobuf.dev 页面内 0 个图片引用；protocolbuffers/protobuf.dev 仓库不存在。",
        "ripgrep": "Simple Icons 的 ripgrep 已下架（探测 404）；"
                   "BurntSushi/ripgrep 仓库内 **0 个图片文件**；"
                   "作者官网只有横幅 ripgrep1.png（769×295，宽高比 2.6 边缘、32px 下不可读）。",
        "fzf": "Simple Icons 的 fzf 已下架（探测 404）；junegunn/fzf 仓库内 **0 个图片文件**；"
               "README 引用的是功能截图（imgur）与徽章，不是标识。",
        "yq": "Simple Icons 的 mikefarahyq 已下架（探测 404）；mikefarah/yq 仓库内 **0 个图片文件**；"
              "README 引用全是 CI 徽章。",
        "navicat": "Simple Icons 的 navicat 已下架（探测 404）；"
                   "navicat.com 与 navicat.com.cn 本机均不可达（curl 连接超时，非 404）；"
                   "en.wikipedia.org 与 upload.wikimedia.org 同样不通，取不到词条配图；"
                   "navicat 组织下未找到公开仓库。",
    }

    @classmethod
    def setUpClass(cls):
        _btprelude.ensure_app()
        cls.comps = main.build_components()
        main._ICON_PIXMAP_CACHE.clear()

    def _missing(self):
        return [c.key for c in self.comps
                if main.load_component_icon_pixmap(
                    c.key, main.ICON_BOX_PX * main.ICON_RENDER_SCALE) is None]

    def test_missing_icons_are_all_explained(self):
        explained = set(self.NO_OFFICIAL_LOGO) | set(self.PENDING_SOURCE)
        unexplained = [k for k in self._missing() if k not in explained]
        self.assertEqual(
            unexplained, [],
            f"这些组件没有图标也没有登记原因：{unexplained}。"
            f"要么补上官网标识，要么在 NO_OFFICIAL_LOGO / PENDING_SOURCE 里写清理由",
        )

    def test_registrations_actually_match_reality(self):
        """登记为"没有标识"的必须确实没有；反过来也成立。

        防止两种漂移：补了真图标却忘了删登记（清单永久少报），
        或者登记了却其实已经有图标（清单多报，掩盖真实缺失）。
        """
        missing = set(self._missing())
        for key in set(self.NO_OFFICIAL_LOGO) | set(self.PENDING_SOURCE):
            with self.subTest(组件=key):
                self.assertIn(
                    key, missing,
                    f"{key} 现在有图标了，请把它从登记里移除并写清来源，"
                    f"否则「缺图标」清单会永久少报这一项",
                )

    def test_every_component_has_an_asset_file(self):
        """登记之外的所有组件都必须有资产文件。"""
        missing_file = []
        for c in self.comps:
            if c.key in self.NO_OFFICIAL_LOGO or c.key in self.PENDING_SOURCE:
                continue
            if not (main.icon_asset_dir() / f"{c.key}.svg").is_file() \
                    and not (main.icon_asset_dir() / f"{c.key}.png").is_file():
                missing_file.append(c.key)
        self.assertEqual(missing_file, [], f"这些组件既没资产文件也没登记：{missing_file}")


class SimpleIconsConvention(unittest.TestCase):
    """绝大多数图标取自 Simple Icons（官方品牌标识策展库）。

    统一来源的价值：品牌色与路径都由该库维护，且每条都能追到品牌官方出处。
    这里只做**习惯检查**（viewBox 规范），不做覆盖率断言 —— 少数项目
    Simple Icons 已因商标原因下架，改为从官方仓库直接取（见各资产文件旁注）。
    """

    def test_most_assets_use_the_standard_24x24_viewbox(self):
        si = 0
        total = 0
        for f in sorted(main.icon_asset_dir().glob("*.svg")):
            total += 1
            if SI_VIEWBOX.search(f.read_text(encoding="utf-8", errors="replace")[:400]):
                si += 1
        self.assertGreater(
            si, total * 0.5,
            f"只有 {si}/{total} 个资产用 Simple Icons 的规范 viewBox。"
            f"如果这不是预期的（大量资产改成了别的来源），请在这里登记来源，"
            f"否则说明采集过程出了偏差",
        )


class NoDuplicatedAssets(unittest.TestCase):
    """两个组件的图标不许是同一个文件 —— 除非那本来就是同一家的标识。

    2026-10-14 实测：`apipost.svg` 里装的其实是 **Apifox 的图标**（当初从 Simple Icons
    取了 apifox，之后被复制成了 apipost）。Apifox 与 Apipost 是两家不同公司的竞品，
    标不可能相同。但这一类错标**躲得过上面所有护栏**：文件能正常渲染、尺寸合法、
    宽高比正常、文件名也对应真实组件 key。只有内容哈希能把"复制粘贴装错了标"钉出来。

    同理 `uv.svg` 曾是 Astral（母公司）的标识 —— Simple Icons 同时收录了两者，
    取错了条目。那条靠 `<title>` 对账发现，本条哈希护栏是它的补充（同一文件复制两遍）。
    """

    # 母产品与它的 GUI 客户端共用同一个标识 —— 官方设计如此，不是错误
    ALLOWED_SHARED = {
        frozenset({"mysql", "mysql-workbench"}): "MySQL Workbench 的官方图标就是 MySQL 标识",
        frozenset({"mongodb", "mongodb-compass"}): "MongoDB Compass 同上",
        frozenset({"redis", "redisinsight"}): "RedisInsight 同上",
    }

    def test_no_two_components_share_the_same_icon_bytes(self):
        import hashlib
        by_hash = {}
        for f in sorted(main.icon_asset_dir().iterdir()):
            if f.suffix.lower() not in (".svg", ".png"):
                continue
            by_hash.setdefault(hashlib.sha256(f.read_bytes()).hexdigest(), []).append(f.stem)
        offenders = [
            keys for keys in by_hash.values()
            if len(keys) > 1 and frozenset(keys) not in self.ALLOWED_SHARED
        ]
        self.assertEqual(
            offenders, [],
            f"这些组件的图标文件内容完全相同（多半是复制粘贴时装错了标）：{offenders}。"
            f"若确属同一家的标识，请加进 ALLOWED_SHARED 并写明理由",
        )

    def test_the_allowed_shared_pairs_still_exist(self):
        """白名单只许缩小不许悬空 —— 某对不再共用时要把它从名单里删掉。"""
        import hashlib
        by_hash = {}
        for f in sorted(main.icon_asset_dir().iterdir()):
            if f.suffix.lower() not in (".svg", ".png"):
                continue
            by_hash.setdefault(hashlib.sha256(f.read_bytes()).hexdigest(), []).append(f.stem)
        shared = {frozenset(v) for v in by_hash.values() if len(v) > 1}
        for pair in self.ALLOWED_SHARED:
            self.assertIn(
                pair, shared,
                f"{sorted(pair)} 已经不再共用同一个图标了，请从 ALLOWED_SHARED 里移除它",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)