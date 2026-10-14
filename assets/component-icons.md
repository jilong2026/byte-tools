# 组件图标资产说明

> 本文件 2026-10-14 重写。**旧版是一份假清单** —— 它列了 `rider.svg`、`jetty.svg`、
> `github.svg`、`java.svg`、`kubernetes.svg`、`app-code.svg`、`bron.svg` 七个文件，
> 而这七个文件**一个都不存在**（当时的采集脚本产物，后来清理时全删了）。
> 谁按那份清单去找图标都会被带偏，所以这里不再手抄文件列表。

## 唯一的真源

**资产目录本身**：`assets/component-icons/`。
文件名必须**正好等于**组件 key（`main.py` 的 `build_components()` 里的 `Component.key`），
扩展名 `.svg` 优先于 `.png`（`main.py` 的 `ICON_EXTS = (".svg", ".png")`）。
加载走 `load_component_icon_pixmap(key, px)`，**按 key 探测、不维护映射表**。

查看当前实况，别读文档：

```bash
.venv/Scripts/python.exe -c "import _btprelude,main; cs=main.build_components(); d=main.icon_asset_dir(); \
have={f.stem for f in d.iterdir()}; print('有图标', sum(c.key in have for c in cs), '/', len(cs)); \
print('缺:', [c.key for c in cs if c.key not in have])"
```

## 覆盖率（2026-10-14 实测：88 / 88）

88 = 87 个界面可见组件 + 隐藏的 `erlang`，**现在每一个都有图标**。

其中 **85 个是各项目官网/官方仓库的真实标识**；剩下 **3 个用「白底黑字组件名」兜底** ——
因为穷举确认**项目自己就没有图形标识**：

| 组件 | 兜底文字 | 为什么判定"确实没有" |
|---|---|---|
| `ninja` | `Ninja` | 官网两页 HTML 零图形引用；三个仓库 + wiki 都 0 图；**官方的 `ninja.exe` 里只有 MANIFEST、无 ICON 资源**；组织头像是 GitHub 自动生成的 identicon |
| `ripgrep` | `ripgrep` | 仓库 0 图、README 0 个 `<img>`；作者发布页上唯一的图是**终端截图**；**官方的 `rg.exe` 里无 ICON 资源** |
| `yq` | `yq` | 仓库 0 图、README 0 个 `<img>`；release 附件只有二进制与 checksum；**官方的 `yq.exe` 连 `.rsrc` 段都没有**；GitBook 文档站那个字母 "Y" 是平台自动生成的字母头像，不采用 |

**判"确实没有"的依据不只是"我搜不到"**：这三个项目的**官方 Windows 二进制自己都不带图标资源**
（用 PE 资源目录遍历确认：`rg.exe` / `ninja.exe` 的 `.rsrc` 只有 MANIFEST，`yq.exe` 无 `.rsrc`）。
维护者从未给它们做过图形标识。另外核过 Simple Icons 当前 3307 条索引与历史版本 v9~v13，
这三个 slug **从未被收录**。

> **兜底图不是"敷衍"，也不是错的标识** —— 它是中性的：白底黑字写着组件名，
> 不会让人误以为是哪个品牌的标。这与"宁缺勿错"并不冲突：缺的是"官方标识"，
> 而这里提供的是"没有标识时的名称标签"。

### 三张兜底图怎么生成

`tools/bt_make_name_icons.py`（**必须在真实平台下跑**，不要设 `QT_QPA_PLATFORM`）：

```bash
.venv/Scripts/python.exe tools/bt_make_name_icons.py
```

规格：256×256 PNG、底 `#FFFFFF`、字 `#000000`、Arial Bold 居中、自动缩字号让文字占满画布 84%。
登记表只有一份，在 `bt_icon_assets_tests.py` 的 `IconCoverage.NAME_TEXT_FALLBACK`
（脚本从那里读，避免两处各写一份而漂移）。

> ⚠ **别在 offscreen 下生成**：offscreen 的字体库里没有 Arial，`drawText` 会把每个字符画成
> 一个空心方块（豆腐块）—— 2026-10-14 第一次生成就是这样，5 个方块照样"有暗像素"，
> 任何像素统计都查不出来，只能肉眼发现。同一条坑见 `DEVELOPMENT.md` 规则 R16。

## 来源约定

绝大多数取自 **Simple Icons**（官方品牌标识策展库），特征是可识别的
`viewBox="0 0 24 24"` 且路径来自该库。少数几个 Simple Icons 未收录
（或因商标原因下架），改为**各项目官方仓库 / 官网直取**：

| 组件 | 来源 | 备注 |
|---|---|---|
| `nacos` | `alibaba/nacos` → `console-ui-next/public/img/nacos-icon.png` | 64×64 |
| `seata` | `apache/incubator-seata` → `console-fe/public/img/seata_logo_small.jpeg` | 200×200，入库时 JPEG→PNG |
| `k9s` | `derailed/k9s` → `assets/imhotep_logo.png` | 官网 k9scli.io 同款 |
| `docker-compose` | `docker/compose` → `logo.png` | README 自己标注 "Docker Compose Logo" |
| `windterm` | `kingToolbox/WindTerm` → `images/WindTerm_icon_1024x1024.png` | |
| `visual-studio` | visualstudio.microsoft.com → `BrandVisualStudioWin2019-2.svg` | viewBox 70×70 |
| `apipost` | `https://www.apipost.cn/favicon.ico` 内嵌的 256×256 PNG | 见下"曾经错过的" |
| `pgadmin4` | `pgadmin-org/pgadmin4` → `docs/en_US/images/logo-128.png` | 官方蓝色大象线稿；见下"曾经错过的" |
| `protoc` | `https://protobuf.dev/favicons/favicon.ico` | 48×48，即 Protocol Buffers 的软盘标识 |
| `fzf` | `junegunn/i` → `fzf-color.png`（官方 README 顶部那张） | 4000×2200，缩到 512 宽入库 |
| `navicat` | Apple Mac App Store 搜索 API → `artworkUrl512` | 发行方 PremiumSoft CyberTech Ltd.，即 Navicat 厂商本身 |

## 曾经错过、已修的三个（同类错误别再犯）

1. **`apipost.svg` 里是 Apifox 的图标**（2026-10-14 发现）。Apifox 与 Apipost 是**两家不同
   公司**的竞品，标不可能相同 —— 当初从 Simple Icons 拿 Apifox 后复制成了 apipost。
   已换成 apipost.cn 官方 favicon 里的 256×256 方标，旧文件挪到工作区外备份。
2. **`uv.svg` 里是 Astral 的标识**（2026-10-14 发现）。uv 由 Astral 开发，但 Simple Icons
   **同时收录了 `uv` 与 `astral` 两个条目**，当初取错成了母公司的标。已换成 `uv` 条目。
3. **`pgadmin4.svg` 是手绘占位图**（2026-10-14 用户对着界面截图指出"这个图标是个蓝方块"）。
   内容是 `<rect rx="6" fill="#336791"/>` + `<text>Pg</text>` —— 采集脚本临时画的。
   它**躲过了原有的伪造签名**（那条只认 `128×128 / rx=24` 的底板）。
   已换成官方大象线稿，并新增护栏 `PlaceholdersAreNotIcons` 钉住这一类。

**判别手法**：
- Simple Icons 的 SVG 自带 `<title>`，与组件 key 对账即可 —— 第 1、2 条就是这么抓出来的。
- 第 3 条靠"有 `<text>` 却没有 `<path>`"这个签名：真实品牌里的文字几乎都转成了路径。

## 已知的"两个组件同一个标"（均属正常，别当成重复文件清理）

| 文件组 | 说明 |
|---|---|
| `mysql.svg` = `mysql-workbench.svg` | MySQL Workbench 的官方应用图标本身就是 MySQL 的标识 |
| `mongodb.svg` = `mongodb-compass.svg` | MongoDB Compass 同上 |
| `redis.svg` = `redisinsight.svg` | RedisInsight 同上 |

这三个是 GUI 客户端沿用母产品标识的设计，不是采集错误。
（除以上三组外，资产目录内**不应再有内容完全相同的两个文件**。）

## 护栏

`bt_icon_assets_tests.py`（16 条）钉住：不是手绘伪造图、不是"圆角方块+文字"的占位图、
不是 HTML 网页、SVG 能被 `QSvgRenderer` 解析、PNG 是真 PNG 且 ≥48px、
文件名对应真实组件 key、渲染尺寸不超过 32px 槽位、宽高比不极端（横幅会在 32px 下糊成
一条线）、DPR 必须排在 `painter.end()` 之后、任意两个组件的图标不得内容完全相同
（除上面三对白名单）、**88 个组件一个都不许缺图标**，且三张名称兜底图必须确实是
白底、且带上足够多的黑色文字（防生成参数被改坏成一片空白）。

## 取图与复核流程（下次补图标照此走）

1. **先查 Simple Icons 全量索引**，别逐个猜 slug（猜出来的 404 会被误读成"这个品牌没有标识"）：
   `https://cdn.jsdelivr.net/npm/simple-icons@latest/_data/simple-icons.json`
2. **`raw.githubusercontent.com` 会间歇性连接超时**，别把它当"文件不存在"。
   可靠通道是 `api.github.com/repos/<owner>/<repo>/contents/<path>?ref=<branch>`
   加 `Accept: application/vnd.github.raw`（列举仓库图片用 `git/trees/<branch>?recursive=1`）。
   ⚠ 未认证额度只有 60 次/小时。
3. **别只看项目自己的仓库** —— 三轮实战证明"漏了"远多于"真没有"。按这个顺序找：
   - **官方 README 里的 `<img>`**：logo 常常放在**另一个仓库**（例如 fzf 的
     `junegunn/i`、另一张 `fzf-color.png`）。读 README 的原始文本再解析，别只扫仓库树。
   - **官网 favicon / apple-touch-icon**：`/favicon.ico` 常常 404，但页面里
     `<link rel="icon">` 会指向真实路径（protobuf.dev 的是 `/favicons/favicon.ico`）。
   - **官方网站仓库**（如 `ninja-build/ninja-build.github.io`）。
   - **包管理器渠道**：Apple App Store 的 `itunes.apple.com/search?term=<名>&entity=macSoftware`
     会返回 `artworkUrl512`（带 `is1-ssl.mzstatic.com` 直链），且发行方字段能确认是厂商本人。
4. 核对**宽高比**（>3 的横幅在 32px 下不可用）与**透明通道**（卡片底色是纯白）。
5. **入库前肉眼复核**：用 `load_component_icon_pixmap()` 渲染成真实 32px 槽位看观感，
   或直接 `ComponentCard.grab()` 看真卡片（offscreen 下中文字形是方框，图标本身正常）。
