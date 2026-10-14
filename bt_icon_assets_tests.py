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
    """每个组件都必须有图标；「没有官方标识」的那几个用**组件名文字图**兜底。

    历史（2026-10-14 一天之内演进了三轮，值得留档）：
      · 最初分两本账：NO_OFFICIAL_LOGO（确实没有图形标识）与
        PENDING_SOURCE（有标识但没采到），最后查剩 6 个。
      · 用户连着两轮对着界面截图指出"还是有组件没图标"，逼出 **6 个里 4 个其实是漏了**：
        protoc / fzf / navicat / pgadmin4（详见 assets/component-icons.md 的取图方法论）。
        教训一句话：**报"找不到"之前先怀疑自己的检索面太窄。**
      · 剩下 3 个（ninja / ripgrep / yq）经穷举确认**项目自己就没有图形标识**，
        最硬的证据是官方 Windows 二进制的 PE 资源段里没有任何 ICON
        （rg.exe / ninja.exe 只有 MANIFEST；yq.exe 连 .rsrc 都没有）。
      · 用户裁定：这三个**用组件名做白底黑字的图标**兜底，不再空着。

    所以现在没有"缺图标登记"这回事了 —— 88 个组件每个都必须有资产文件。
    NAME_TEXT_FALLBACK 记的是"哪几个用的是名称文字图 + 为什么"，供后人追溯。
    """

    # 没有官方图形标识、经用户同意改用「白底黑字组件名」兜底的组件。
    # 生成方式：Arial Bold 居中，自动缩字号让文字占满画布 84% 宽，256×256 PNG，
    # 底色 #FFFFFF、字色 #000000（见 assets/component-icons.md）。
    NAME_TEXT_FALLBACK = {
        "ninja": "官网 ninja-build.org 是纯文字页（HTML 里除一个 canonical 外没有任何 "
                 "<link>/<img>/<svg>/url() 引用，manual.html 同样 0 张图）；"
                 "源码仓 ninja-build/ninja、官网仓 ninja-build.github.io、"
                 "组织下第三个仓库 ninja-emacs 全都 0 个图片文件；GitHub wiki 首页 0 张图。"
                 "ninja-build 组织的头像是 GitHub **自动生成的 identicon**（未上传头像），不是标识。"
                 "**最硬的一条：官方发布的 ninja.exe 的 .rsrc 里只有 MANIFEST，"
                 "没有任何 ICON 资源** —— 项目自己都不带图形标识。"
                 "其视觉形象只有终端里的 ASCII 忍者脸与字标。",
        "ripgrep": "BurntSushi/ripgrep 仓库 0 个图片文件；README 内 0 个 <img>；"
                   "作者发布页 burntsushi.net/ripgrep/ 上只有 1 张图，而它是**终端运行截图**"
                   "（alt 原文 \"A screenshot of a sample search\"），不是标识。"
                   "**最硬的一条：官方发布的 rg.exe 的 .rsrc 里只有 MANIFEST，无任何 ICON 资源**。"
                   "另核：Simple Icons 当前 3307 条索引里 0 条，"
                   "历史版本 v9~v13 的 `icons/ripgrep.svg` 也全是 404 —— "
                   "即它**从未**进过 Simple Icons（早前记的「已下架」不准确）。",
        "yq": "mikefarah/yq 仓库 0 个图片文件，README 内 0 个 <img>；"
              "最新 release（v4.54.1）的附件只有各平台二进制与 checksum，没有图；"
              "**官方发布的 yq.exe 连 .rsrc 段都没有（没有版本信息、没有图标）**；"
              "Simple Icons 索引 0 条、历史版本 v9~v13 也全 404（从未收录）。"
              "GitBook 文档站（mikefarah.gitbook.io/yq）能取到一个字母 \"Y\" 的图标，"
              "但 GitBook 对未设自定义图标的空间会**自动生成字母头像**，"
              "无法确认它是作者设定的标识，故不采用（宁缺勿错）。",
    }

    # 已查遍以下来源（每条都实际试过，不是没试）：
    #   · Simple Icons CDN（当前全量索引 3307 条 + 历史版本 v9~v13 都核过）
    #   · 项目官方 GitHub 仓库（API 检索全量图片清单）
    #   · 项目官网 HTML（提取 <img>/<link>/<svg>/url() 里的 logo/icon 资源）
    #   · 官方 README 的图片引用（**含指向别的仓库的跨仓引用**）
    #   · 官网 favicon / apple-touch-icon、GitHub 组织头像、GitHub wiki
    #   · 包管理器渠道（Apple Mac App Store 搜索 API）
    #   · 官方发布二进制里的 PE 资源段（RT_ICON / RT_GROUP_ICON）
    #
    # 2026-10-14 各轮补进来的（来源如下，均已肉眼复核 32px 观感）：
    #   · nacos           alibaba/nacos  develop  console-ui-next/public/img/nacos-icon.png
    #   · seata           apache/incubator-seata  2.x  console-fe/public/img/seata_logo_small.jpeg
    #                     （200×200 蓝底白 S，原为 JPEG，入库时转成真 PNG）
    #   · k9s             derailed/k9s  master  assets/imhotep_logo.png（官网 k9scli.io 同款）
    #   · docker-compose  docker/compose  main  logo.png
    #                     （README 第 17 行自己标注 "Docker Compose Logo"，是官方章鱼标识）
    #   · windterm        kingToolbox/WindTerm  master  images/WindTerm_icon_1024x1024.png
    #   · visual-studio   visualstudio.microsoft.com 官方品牌资源
    #                     wp-content/uploads/2019/02/BrandVisualStudioWin2019-2.svg（viewBox 70×70）
    #   · apipost         apipost.cn 官方 favicon 内嵌的 256×256 PNG
    #                     （原 apipost.svg 装的其实是 Apifox 的标 —— 两家竞品，见 NoDuplicatedAssets）
    #   · uv              Simple Icons 的 `uv` 条目
    #                     （原来装的是 Astral 母公司标识；该库同时收录 uv 与 astral）
    #   · protoc          protobuf.dev 的 favicon（/favicons/favicon.ico，48×48）
    #                     —— Protocol Buffers 那个软盘标识。此前只查了仓库，没查官网 favicon。
    #   · fzf             **junegunn/i 仓库**里的 fzf-color.png（4000×2200，缩到 512 宽入库）
    #                     —— 官方 README 顶部就是它。此前只扫 junegunn/fzf，
    #                     漏了 README 指向**另一个仓库**的跨仓引用。
    #   · navicat         Apple Mac App Store（itunes.apple.com/search → artworkUrl512），
    #                     发行方标注 PremiumSoft CyberTech Ltd.（即 Navicat 厂商本身）。
    #                     navicat.com 本机始终连不上，这是唯一可用的官方渠道。
    #   · pgadmin4        pgadmin-org/pgadmin4  docs/en_US/images/logo-128.png（官方大象线稿）。
    #                     它此前**有**图标，但那份是手绘占位图（圆角蓝底 + 文字 "Pg"）；
    #                     为此新增 PlaceholdersAreNotIcons 这条护栏。

    @classmethod
    def setUpClass(cls):
        _btprelude.ensure_app()
        cls.comps = main.build_components()
        main._ICON_PIXMAP_CACHE.clear()

    def _missing(self):
        return [c.key for c in self.comps
                if main.load_component_icon_pixmap(
                    c.key, main.ICON_BOX_PX * main.ICON_RENDER_SCALE) is None]

    def test_no_component_is_missing_an_icon(self):
        """88 个组件一个都不许缺 —— 没有官方标识的也要有名称文字图兜底。"""
        missing = self._missing()
        self.assertEqual(
            missing, [],
            f"这些组件没有图标：{missing}。没有官方标识的请按 NAME_TEXT_FALLBACK "
            f"的做法补一张白底黑字的组件名图，并在那里登记原因",
        )

    def test_name_text_fallbacks_are_real_and_look_right(self):
        """登记为"名称文字图兜底"的必须真有一张白底黑字的名字图。

        只查"文件在不在"是不够的 —— 那三个的 PNG 是脚本生成的，
        哪天生成参数被改坏（比如底色变成透明、字号小到看不见），
        文件仍在、也能渲染，但卡片上会是一片空白。
        """
        from PySide6.QtGui import QImage
        for key, _why in self.NAME_TEXT_FALLBACK.items():
            with self.subTest(组件=key):
                p = main.icon_asset_dir() / f"{key}.png"
                self.assertTrue(p.is_file(), f"{key} 的兜底图不见了：{p}")
                img = QImage(str(p))
                self.assertFalse(img.isNull(), f"{key} 的兜底图读不出来")
                for x, y in ((2, 2), (img.width()-3, 2), (2, img.height()-3),
                             (img.width()-3, img.height()-3)):
                    self.assertGreater(
                        img.pixelColor(x, y).lightness(), 240,
                        f"{key} 的兜底图不是白底（四角应当接近纯白）")
                # 逐像素查黑色文字。**不要用带步长的采样网格**：字体栅格化会把竖笔画
                # 落在非整除数上，step=4 的网格实测能在整条笔画之间穿过去（假报"没有字"）。
                dark = sum(
                    1
                    for yy in range(img.height())
                    for xx in range(img.width())
                    if img.pixelColor(xx, yy).lightness() < 60
                )
                self.assertGreater(
                    dark, 50,
                    f"{key} 的兜底图上几乎没有黑色文字（暗像素 {dark} 个）—— "
                    f"生成参数被改坏了？")


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


class PlaceholdersAreNotIcons(unittest.TestCase):
    """资产不许是"圆角方块 + 文字"这种手绘占位图。

    2026-10-14 用户对着界面截图指出 pgAdmin 4 的图标是一个蓝方块。查下去发现
    `pgadmin4.svg` 的内容是：

        <rect width="32" height="32" rx="6" fill="#336791"/>
        <text ... font-size="16" font-weight="bold" fill="#ffffff">Pg</text>

    —— 采集脚本临时画的占位符，**它躲过了原有的伪造签名**：那条只认
    `width="128" height="128" rx="24"` 的底板，而这个是 viewBox 0 0 32 32 / rx=6。

    判据取"有 `<text>` 却没有 `<path>`"：真实品牌 SVG 里的文字几乎总是被转成
    路径（转曲）以脱离字体依赖，会把 `Pg` 这类字留成活的 `<text>` 元素的，
    基本都是脚本生成的占位图。注意 `activemq.svg` / `fd.svg` 也含 `<text>`，
    但它们同时有 `<path>`，是正规标识 —— 所以判据必须是**两者同时成立**。
    """

    def test_no_rect_plus_text_placeholders(self):
        offenders = []
        for f in sorted(main.icon_asset_dir().glob("*.svg")):
            src = f.read_text(encoding="utf-8", errors="replace")
            if "<text" in src and "<path" not in src:
                offenders.append(f.name)
        self.assertEqual(
            offenders, [],
            f"这些 svg 像是手绘占位图（有 <text> 却没有 <path>，即圆角方块上写字）："
            f"{offenders}。请换成该项目官网/官方仓库的真实标识",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)