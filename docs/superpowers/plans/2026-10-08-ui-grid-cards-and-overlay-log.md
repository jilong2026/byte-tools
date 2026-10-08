# 组件卡片网格化（2 列 × 4 行）+ 日志改浮层

> 状态：**设计已确认，尚未实现**。窗口尺寸保持 1000×680 不变；实现要另行开工。
> ⚠️ **开工前先读 `2026-10-08-card-slim-before-grid.md`**：本文件的「4 行 × 2 列 = 8 个」
> 是用单行布局的卡片高度 121 推的，实测把按钮塞进 313px 格子必然换行 → 卡片涨到 ~230 →
> 实际只有 4 个/屏。必须先做卡片瘦身（按钮不换行、高度停在 157），再上网格，
> 一屏才是 6 个。另：`MIN_CARD_WIDTH_PX` 应取 ~300 而非 470（640÷470 只能 1 列）。
> 数字是 2026-10-08 在本机 offscreen 强制走一次布局后量出来的，不是估的。

## Goal

四个 Tab 里的组件卡片从"一行一张占满宽"改成**按宽度重排的 2 列网格**，并把底部日志面板改成**浮层**（展开时盖在网格上，不挤压网格），使卡片区在一屏内可见 **2 列 × 4 行 = 8 个**组件。卡片**信息一条不砍**（不做磁贴、不做折叠态）。

## 实测数字（强制走过一次布局，offscreen）

| 项 | 值 |
|---|---|
| 窗口 / 标题栏 | 1000×680 ／ 固定 48px（`main.py` 的 `title_bar.setFixedHeight(48)`） |
| 卡片区视口（现状） | **640 × 480** |
| 日志区高度（现状） | **138**，与卡片区按 `body` 的 **3:2** 分配 |
| 一张完整卡片 | sizeHint **624 × 117**；可启停组件按钮更多但同一量级 |
| 列数上限（640 宽） | 2 列 → 每格 **313**；3 列 → 204（220px 的下拉框直接超宽）；5 列 → 118（必须砍内容，本轮不做） |
| 行数上限 | 3 行 379px ✓ ／ 4 行 510px ✓（日志收起后卡片区 ~628） ／ 5 行 641px ✗（要压行距且零余量，本轮不做） |

## 为什么不是"一屏 10 个"

`10 个/屏` 与 `每格完整` 在 1000px 窗口下物理冲突：5 列时每格只有 118px，而一张完整卡片首选 624px —— 只能砍成磁贴。用户明确要求"格子必须完整展示、不接受展示一半"，故本轮取 **2 列 × 4 行 = 8 个**（对比现状一屏约 3.5 个）。

## 决策

| 项 | 取法 | 理由 |
|---|---|---|
| 布局实现 | **行容器法**：Tab 外层仍是 `QVBoxLayout`，里面装"行"（每行一个 `QHBoxLayout`，1..N 张卡） | `QGridLayout` 没有 `addStretch`／按 index 插入语义，而 `_reparent`、`_build_unified`、`_restore_browse` 三处全靠 `indexOf`/`insertWidget`/末尾 stretch 工作 |
| 日志 | 改成**浮层**：卡片区独占中部，日志作为覆盖在底部的一块（同 parent + `raise_()`，几何随 resize 跟随），展开时**遮住**最下面一行格子而不是把网格压扁 | 浮层不触发重排 ⇒ 列数/行数只由窗口宽度决定，日志开关不会让格子忽大忽小；省掉"挤压式折叠"带来的二次 relayout 与相应用例 |
| 浮层的实时反馈 | ①有活动任务（下载/安装/启停/卸载）时**自动弹开**，任务结束后延时自动收起；②新产生 `warn`/`error` 时在 `[📋 日志]` 按钮上挂**未读条数**（写在按钮文字里，不新增控件）；③点按钮即 toggle | 日志现在是唯一能看到"哪个镜像失败、凭据、哪些终端还是旧环境"的地方；做成浮层后若不自动弹，就是"进度条走完但不知道出没出错" |
| 视图切换 | 工具条一个 `▦ 网格 / ☰ 列表` 按钮，持久化到 `config.json`，**默认网格**；列表模式 = 强制 1 列，卡片内部一模一样 | 要求可切换且默认网格；列表 = 1 列就不需要维护两套卡片形态 |
| 隐藏卡片 | relayout **只排可见卡片**，绝不"留格子靠隐藏" | QBoxLayout 会给隐藏控件留位 → 搜索命中 1 个时网格出现空洞 |
| 卡片内部 | "版本行 / 动作行"拆两行；`version_combo` 去掉 `setFixedWidth(220)` 改 `setMinimumWidth(180)`+可扩；按钮行自动换行（2 个/行）；`status_label`、`launch_label` 允许省略号 | 每格 313px，一行塞 6 个按钮会被挤扁；这是"信息不砍"的前提下唯一能成立的重排 |
| 同格等高 | 同一行等高（布局天然保证）；信息放不下就整格改用短文案 + tooltip，**不做半截显示** | 不接受"有些格子展示一半" |

## 改动清单（都在 `main.py`）

1. 模块级纯函数 + 常量（可离线测，不碰几何）：`MIN_CARD_WIDTH_PX`（锚点：640 视口下正好 2 列，取 ~470 一档，实现时目测定值）、`CARD_ROW_SPACING = 14`、`grid_columns_for(available_px, min_card_px) -> int`（≥1）、`chunk_visible(cards, columns) -> List[List[card]]`（保序、只含可见）。
2. `MainWindow`：
   - `_tab_layouts` 语义改为"外层 QVBoxLayout（装行）"，新增 `_tab_rows`；新增 `relayout_cards(container_key)`：销毁行容器 → `chunk_visible` 分块 → 建行 → 用现有 `_reparent` 塞格子；**列表模式 = columns 1**。
   - `resizeEvent`：只在 `grid_columns_for()` 结果变化时 relayout（避免每像素重建）。
   - `_restore_browse` / `_build_unified` / `_reparent` 末尾统一走 `relayout_cards`；`_build_unified` 的分类小标题作为"跨整行的行"处理。
   - 中部 `body` 的 3:2 分配改掉：卡片区吃满中部，日志 `logView` 移入浮层容器；新增 `self.log_overlay`（show/hide + 跟随 resize）与 `self._log_unread` 计数、`_set_log_open(bool)`、任务开始/结束的自动弹开与延时收起（`QTimer`，测试注入）。
   - `view_mode` 读写 `config.json`：无该键 → `grid`（老配置自动获得新默认，不报错）。
3. `ComponentCard`：版本行/动作行两行化、combo 宽度策略、按钮行换行、`status_label`/`launch_label` 省略号。**行为逻辑、信号、真值来源一律不动**：`_running_per_ui()` 仍读 `btn_start` 文字，`btn_start`/`btn_install` 在网格里仍是同一批控件（只是排成两行）。
4. 文档：`DEVELOPMENT.md` R2（界面 Tab）与 `CODE_WIKI.md` 里"每个 Tab 一条独立滚动栏挂该分类卡片""3:2 分配""日志面板"三处描述同步。

## 测试方案（全离线，`QT_QPA_PLATFORM=offscreen`；不断言真实像素/字号）

1. `grid_columns_for` 表驱动：640/470→1 列、940/470→2、极窄或非法值→兜底 1。
2. `chunk_visible`：保序；隐藏卡片不出现在任何行（= 空洞回归护栏）。
3. `relayout_cards`：给定 N 张卡 + C 列 → 行数 == `ceil(N/C)`、拼接后顺序 == `self.cards` 顺序（防"切一次视图卡片顺序乱掉"）。
4. 视图模式：默认 `grid`；点切换 → `list`（列数 1）→ 再点回；`config.json` 缺键时取 `grid`；写入后重读正确。
5. **浮层不重排**：日志展开/收起前后，`_tab_rows` 行数与每行卡片数**完全不变**（这条是浮层方案的核心承诺，必须单独钉）。
6. 自动弹开：注入任务开始 → 浮层 `isVisible()` True；任务结束 + 注入时钟推进 → False；`warn`/`error` 计数出现在按钮文字里，读一次后清零。
7. 搜索：命中数 < 列数时只有一行且无空位；清空搜索后卡片全部回到各自 Tab 且重排正确（既有 `test_cards_live_in_their_category_tab` 与 `findChildren(ComponentCard)` 必须继续绿）。
8. 卡片两行化后，既有用例（`btn_uninstall.isEnabled()`、tooltip、`status_label` 文本、绿勾、Tab 上 `●`）不得改动断言来迁就。
9. **变异自检**：(a) `chunk_visible` 改成"全取" → 第 2、7 条红；(b) `grid_columns_for` 改成恒 1 → 第 1 条红；(c) 浮层改成"挤压式折叠"（把日志放回 body 布局）→ 第 5 条红；(d) relayout 按容器添加顺序 → 第 3 条红。四条各自红过再还原。
10. 全量回归 9 套件（2026-10-08 实测）：`launch 230 / multiversion 156 / component_category 11 / search_and_newcmp 26 / mirror_spec 30 / startup 9 / boot_script 17 / refresh_versions 4 / gitee_sync 23`。其中 `gitee_sync` 有 **1 条先前就红**的用例（`test_bat_uploads_all_four_and_verifies`），不算本轮失败——该用例、`同步Gitee产物.sh` 的 `ASSETS_DIR` 默认值、`bundle_identifier=com.rgh.byte-tools` 三项已由用户明确**跳过不处理**。

## 目测项（离线用例替代不了，实现时要如实报告）

`MIN_CARD_WIDTH_PX`、行距、以及"每格 313px 下 6 个按钮两行是否真的不挤"必须真跑一次窗口目测（100% / 125% / 150% 缩放各看一次）。**DPI 变大时卡片高度会涨到 ~140，卡片区可能只露 3 行半 —— 这是网格布局的正常滚动行为，不是 bug**，本设计不试图消除它。

## 不做

- 磁贴态、5 列、折叠卡片、右侧详情抽屉（理由见上面「为什么不是一屏 10 个」一节）。
- 窗口宽高（保持 1000×680 与最小 1000×560）。
- 启停编排、`LAUNCH_KEYS`、`running.json` 结构一律不动。
- 不引入第三方依赖（不装 FlowLayout 补丁包）。
- Linux 真机验证：本轮不改变"macOS/Linux 尚未真机验证"这条事实。

## 实现时的提交划分

1. `feat(ui): 卡片改 2 列网格、日志改浮层（展开时遮住网格不挤压）` —— `main.py` + 新用例。
2. `docs: R2 与 CODE_WIKI 同步网格布局、浮层日志与视图切换`。
