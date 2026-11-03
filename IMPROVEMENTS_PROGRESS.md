# 代码改进进度（单一事实来源）

**状态**：计划内项目全部完成；全量离线回归 **24 套件 / 1087 条 / 0 失败**
**日期**：2026-11-03
**约束文档**：[`DEVELOPMENT.md`](DEVELOPMENT.md) 规则 R30

---

## 一、已完成（按计划顺序）

### 1. `data/` 数据模型
- `data/components.py`：`ComponentVersion`、`DownloadArtifact`、`ARTIFACT_LABELS`。
- 通过 `configure(os_provider, human_size_fn)` 注入，`main.CURRENT_OS` 被测试改写后派生结果同步变化。

### 2. `services/` 服务层
- `services/service_manager.py`（约 700 行）整体搬出，`ServiceManager` 的行为逐字未改。
- 依赖统一以 `_main.<name>` **晚绑定**，因此 `mock.patch.object(main, "save_running_map")` 等桩点全部继续生效。
- main.py 保留 `SERVICE_MANAGER` / `SERVICE_BACKEND` 的实例化与 re-export。

### 3. 平台差异收拢
- 新增 `core/platform.py`：`is_windows / is_macos / is_linux / current_os / machine / on_arm`。
- main.py 内 78 处 `CURRENT_OS ==/!= "..."` 比较替换为判定函数；剩余 24 处是字典键/展示/ provider，属正常用法。
- provider 仍指向 `main.CURRENT_OS`，测试改写立即生效。

### 4. 剩余超时常量
- `core/constants.py` 新增 `FETCH_TIMEOUT_QUICK/WEB/HEAD/API` 与 `EXEC_PROBE_TIMEOUT`，替换 4 处调用点。
- 组件级 `startup_timeout` 属各服务运行参数，保留在 LaunchSpec（不是"魔法数字"）。

### 5. UI 拆包（含主窗口与卡片）
- `ui/component_detail_dialog.py`、`ui/donate_dialog.py`、`ui/component_card.py`（约 2.6k 行）、`ui/main_window.py`（约 2k 行）。
- 规则：**只本地导入基类与 `Signal`**，其余 Qt / 业务名走 `_main.<name>`。
  这样 `main.QMessageBox = <桩>` 这类替换名字的写法仍生效（真实对话框会让测试挂死，已踩过）。
- main.py 从约 23.2k 行降到 **18.4k 行**。

### 6. 性能监控 / i18n
- `core/perf.py`：`timed()` 计时、`snapshot()`、可选 tracemalloc（`BYTE_TOOLS_PROFILE=1`）；
  「导出诊断」新增「性能快照」一节。
- `core/i18n.py`：中文原文为键的最小翻译表、`BYTE_TOOLS_LANG` 切换、可选加载 `.qm`；
  已迁移支持作者对话框（zh 默认回落，en 有对照）。

### 7. 此前各轮（摘要）
- `safe_rmtree` 路径校验；5 处删除收口；`tasklist` 映像名/pid 校验。
- 结构化日志接入 UI 与诊断导出。
- 泛化 `except Exception` 161 → 58（现分布：main 27、卡片 15、窗口 14、服务 2），全部为类方法兜底，符合 R30。
- 常量唯一定义处；重复定义已删。

---

## 二、验证
```text
python tests/run_all_tests.py
合计 1089 条用例 / 24 个文件 / 24 通过 / 0 失败

offscreen 冒烟：MainWindow()/show/close、DonateDialog() → SMOKE OK
打包验证：pyinstaller_no_wmi.py --noconfirm --clean byte-tools.spec → dist/ByteTools.exe (50 MB)
          后再以 QT_QPA_PLATFORM=offscreen 启动 15 秒，进程保持存活（事件循环正常）
```
新增护栏：`tests/bt_core_tests.py`（40 条）。

## 二·补：入口脚本与打包配置的同步改动（2026-11-03）
- `ui/donate_dialog.py` / `core/i18n.py`：资产与 `.qm` 路径优先取 `sys._MEIPASS`，
  源码运行回落仓库根（onefile 下不再依赖 `__file__` 布局）。
- `byte-tools.spec`：`hiddenimports` 显式列出 `core/data/services/ui/theme`
  （`_main.` 晚绑定不产生静态 import，漏收只在打包后暴露）。
- `同步Gitee产物.sh`：默认产物目录 `./assets` → `./release-assets`，与 `.bat`
  和文档一致，避免把图标目录当产物目录、并让"清空暂存目录"逻辑真正生效。
- `.github/workflows/release.yml`：Gitee 同步 job 的下载目录改为 `./release-assets`。
- `一键启动项目.bat` / `一键打包exe.bat` 无需改动：均用 `%~dp0` 定位仓库根，
  只校验 `main.py` / `byte-tools.spec` / `requirements.txt`；新包由 PyInstaller
  静态分析与显式 hiddenimports 收齐。
- `pyinstaller_no_wmi.py` 增加**打包前预检**（2026-11-03 用户实测报
  `PermissionError: [WinError 5] dist\ByteTools.exe`）：
  · 目标 exe 不可写时，先自动停止遗留的「访问页服务」进程（命令行含 `--bt-page-server`，
    它们是设计上脱离主程序存活的独立进程）；
  · 主窗口仍在运行时**不擅自结束**，打印 PID 与 `taskkill` 命令；
  · 用 `--distpath` 独立目录完整构建并以 offscreen 启动 12 秒验证。

---

## 三、明确不做 / 仍缺的
1. **插件架构 / DI 框架**：属新产品方向，非本次审计建议；当前以 `configure()` + `_main` 晚绑定
   提供了够用的注入手段。
2. **pytest 默认发现**：`bt_*_tests.py` + 自研 runner 有意保留（改命名会牵动 24 套件）。
3. **极端网络 / 多组件并行安装专项用例**：仍未补。磁盘满已有模拟；
   限速/丢包、多组件同时安装的互不影响尚无专测，建议后续单独补。
