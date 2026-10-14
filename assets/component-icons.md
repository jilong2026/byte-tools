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

## 覆盖率（2026-10-14 实测：82 / 88）

88 = 87 个界面可见组件 + 隐藏的 `erlang`。仍缺 6 个，**原因逐条登记在代码里**
（`bt_icon_assets_tests.py` 的 `NO_OFFICIAL_LOGO` 与 `PENDING_SOURCE` 两个字典），
不在本文重复 —— 那两个字典由护栏强制与实况一致，写在文档里必然过期：

| 组件 | 归类 | 一句话原因 |
|---|---|---|
| `ninja` | 确实没有图形标识 | 官网纯文字页、仓库 0 图；视觉形象只有终端里的 ASCII 忍者脸 |
| `protoc` | 有但取不到 | Simple Icons 下架；protobuf 仓库全量树里只有 3 张文档配图 |
| `ripgrep` | 有但取不到 | 仓库 0 图；作者官网只有 769×295 横幅，32px 下不可读 |
| `fzf` | 有但取不到 | 仓库 0 图；README 只有功能截图与徽章 |
| `yq` | 有但取不到 | 仓库 0 图；README 全是 CI 徽章 |
| `navicat` | 有但取不到 | navicat.com / .com.cn / Wikipedia 本机全部连接超时 |

**缺图标时不显示错的标识**，回退成分类色块 —— 这是用户明确的质量红线。

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

## 曾经错过、已修的两个（同类错误别再犯）

1. **`apipost.svg` 里是 Apifox 的图标**（2026-10-14 发现）。Apifox 与 Apipost 是**两家不同
   公司**的竞品，标不可能相同 —— 当初从 Simple Icons 拿 Apifox 后复制成了 apipost。
   已换成 apipost.cn 官方 favicon 里的 256×256 方标，旧文件挪到工作区外备份。
2. **`uv.svg` 里是 Astral 的标识**（2026-10-14 发现）。uv 由 Astral 开发，但 Simple Icons
   **同时收录了 `uv` 与 `astral` 两个条目**，当初取错成了母公司的标。已换成 `uv` 条目。

**判别手法**：Simple Icons 的 SVG 自带 `<title>`，可以拿来与组件 key 对账 ——
`<title>Apifox</title>` 挂在 `apipost.svg` 上就是这么抓出来的。

## 已知的"两个组件同一个标"（均属正常，别当成重复文件清理）

| 文件组 | 说明 |
|---|---|
| `mysql.svg` = `mysql-workbench.svg` | MySQL Workbench 的官方应用图标本身就是 MySQL 的标识 |
| `mongodb.svg` = `mongodb-compass.svg` | MongoDB Compass 同上 |
| `redis.svg` = `redisinsight.svg` | RedisInsight 同上 |

这三个是 GUI 客户端沿用母产品标识的设计，不是采集错误。
（除以上三组外，资产目录内**不应再有内容完全相同的两个文件**。）

## 护栏

`bt_icon_assets_tests.py`（14 条）钉住：不是手绘伪造图、不是 HTML 网页、SVG 能被
`QSvgRenderer` 解析、PNG 是真 PNG 且 ≥48px、文件名对应真实组件 key、
渲染尺寸不超过 32px 槽位、宽高比不极端（横幅会在 32px 下糊成一条线）、
DPR 必须排在 `painter.end()` 之后、缺图标的组件必须逐一登记原因。

## 取图与复核流程（下次补图标照此走）

1. **先查 Simple Icons 全量索引**，别逐个猜 slug（猜出来的 404 会被误读成"这个品牌没有标识"）：
   `https://cdn.jsdelivr.net/npm/simple-icons@latest/_data/simple-icons.json`
2. **`raw.githubusercontent.com` 会间歇性连接超时**，别把它当"文件不存在"。
   可靠通道是 `api.github.com/repos/<owner>/<repo>/contents/<path>?ref=<branch>`
   加 `Accept: application/vnd.github.raw`（列举仓库图片用 `git/trees/<branch>?recursive=1`）。
   ⚠ 未认证额度只有 60 次/小时。
3. 核对**宽高比**（>3 的横幅在 32px 下不可用）与**透明通道**（卡片底色是纯白）。
4. **入库前肉眼复核**：用 `load_component_icon_pixmap()` 渲染成真实 32px 槽位看观感，
   或直接 `ComponentCard.grab()` 看真卡片（offscreen 下中文字形是方框，图标本身正常）。
