# tools/oneoff —— 一次性脚本留档（不维护）

2026-10-14 从仓库根目录扫进来的草稿。它们原先靠 `.gitignore` 的 `/.*.py`
（只匹配**根目录**的点前缀 .py）隐身，所以 `git status` 看不见、资源管理器里却堆了一大片
——根目录"看起来很乱"的主因就是这 31 个文件（26 个 `.py` + 5 个 `.png`）。

移到这里之后**目录整体仍在 `.gitignore` 里**（见 `/tools/oneoff/`），只有本文件被
`!.gitignore` 式的例外保留，用来说明"这是什么东西"。

## 它们是什么

| 前缀 | 用途 | 状态 |
|---|---|---|
| `.collect_*` / `.generate_*` / `.get_official_logos_*` | 图标采集与生成脚本 | **已作废，别再用** —— 见下 |
| `.icon_*_tmp` / `.icon_sheet_*` / `.use_static_icons` | 图标挑选、拼图、格式转换的临时脚本 | 产物已入库，脚本留档 |
| `.accept_*` / `.vis_check*` / `.run1` / `.diag_hide` / `.suppress_test` / `.bench_final` / `.gen_splash3` | 验收、目视检查、启动探针等一次性验证 | 结论已进文档，脚本留档 |

## ⚠ 为什么"图标采集"这一批要特别标出来

它们**产出过错的图**，是 `bt_icon_assets_tests.py` 里两条护栏的直接来因：

- 采集脚本会"画"图标（`<rect width="128" height="128" rx="24">` + 一条粗糙 path），
  产出的 python.svg / node.svg 之类**看着像 Logo 但不是**；
- 也会把 404 / 错误页当图片存下来（deno.svg 曾是 57 KB 的 HTML）；
- 还会把别家的标当成本组件的标（apipost 存成了 Apifox 的标、uv 存成了 Astral 的标）。

现在 88 个组件的图标全部来自各项目官网/官方仓库（或名称兜底图），
来源与方法论写在 `assets/component-icons.md`。**补图标请照那份文档走，不要复活这些脚本。**

## 里面可能还有用的

`.accept_duo.py` / `.vis_check.py` 这类"起 exe 并目视检查"的探针，跑法参考
`tools/bt_close_crash_repro.py`（正式的取证脚本都在 `tools/` 下，不在本目录）。
本目录里的一切都不被任何测试或构建流程引用。
