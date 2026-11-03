# 代码改进进度（单一事实来源）

**状态**：全部既定任务已完成；全量离线回归 **24 套件 / 1076 条 / 0 失败**
**日期**：2026-11-03
**约束文档**：[`DEVELOPMENT.md`](DEVELOPMENT.md) 规则 R30

---

## 一、已完成

### 1. 安全删除（路径遍历防护）
- `core/exceptions.py::safe_rmtree(path, verify_deleted=True, allowed_root=...)`：
  `Path.relative_to` 判界（`.env-tools-evil` 前缀伪装不放行）、不吞删除失败、路径不存在幂等。
- `main.py` 5 处删除统一走 `_safe_rmtree()`（`allowed_root=CONFIG_DIR`，测试沙箱自动跟随）。
- 卸载遇到工作目录外路径：拒绝删除、写摘要、继续清理，不中断。
- 命令注入面：`tasklist /FI IMAGENAME` 先校验映像名；`_process_name(pid)` 先 `int()`。

### 2. 结构化日志
- `core/logger.py`：OK/INFO/WARNING/ERROR 四级 + 颜色 + 500 条环形历史 + `export_json()`；
  修复初版无限递归。
- 界面 `_append_log()` 同步写入 logger 历史；「导出诊断」新增
  `结构化日志（最近 50 条）` 一节。

### 3. 异常收窄
- 版本抓取区 52 处 + 模块级尽力而为路径 50 处 → `BEST_EFFORT_ERRORS`。
- 关键路径改为具体类型（requests / OSError+WindowsError / ValueError+UnicodeDecodeError 等）。
- 全仓 `except Exception`：161 → **58**，且全部位于类方法（UI/线程最后兜底），
  符合 R30 的允许范围。

### 4. 配置集中（去重完成）
- 唯一定义处：`core/constants.py`。
- 已删除 main.py 内的重复定义：`HTTP_UA`、`DOWNLOAD_MIN_VALID_BYTES`、
  `DOWNLOAD_PROBE/CONNECT/READ_TIMEOUT`、`DEVTOOL_FETCH_TIMEOUT`、
  `_JAVA_MAJOR_TIMEOUT`、`TK_SUPPRESS_BG_LIMIT`、`UPDATE_CHECK_INTERVAL_SEC`、
  `UPDATE_HTTP_TIMEOUT`（缺失 core 时仍有 fallback）。

### 5. 模块化拆分
| 模块 | 内容 |
|------|------|
| `core/constants.py` | 全部配置常量 |
| `core/logger.py` | 结构化日志 |
| `core/exceptions.py` | 异常层级 + `safe_rmtree` + `BEST_EFFORT_ERRORS` |
| `core/versioning.py` | `Version`、三套口径、`version_is_newer` |
| `core/windows_service.py` | SCM 后端与 `ServiceInfo` |
| `core/download.py` | `DownloadWorker`（`configure()` 注入；lambda 解引用保住 `main.http_session` 桩点） |
| `ui/donate_dialog.py` | `DonateDialog`（资产目录参数注入） |

main.py 由约 24.3k 行降到约 22.4k 行；所有老调用点与测试通过 re-export / 薄壳保持不变。

---

## 二、验证
```text
python tests/run_all_tests.py
合计 1076 条用例 / 24 个文件 / 24 通过 / 0 失败

offscreen: MainWindow()->show()->close()  → SMOKE OK
offscreen: DonateDialog()                 → SMOKE OK
```
新增护栏：`tests/bt_core_tests.py`（27 条）。

---

## 三、有意保留 & 后续建议
1. **58 处 `except Exception`**：均为类方法内的 UI/线程最后兜底（Qt 槽、渲染循环、
   凭据解密、启停线程）。R30 要求保留时必须写明不能外抛的原因。
2. **MainWindow / ComponentCard 未拆包**：与 Qt 信号和窗口状态深度耦合，
   需单独分支 + 真机演练（Windows 服务启停、多版本切换、关窗不变量）。
3. **插件化 / DI 框架**：属于新架构方向，不在本次审计建议范围内；
   当前 `core.download.configure()` 已示范依赖注入的落地方式。
