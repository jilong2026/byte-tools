# 代码改进进度（单一事实来源）

**状态**：本轮改进已完成并通过全量离线回归（24 套件 / 1071 条 / 0 失败）
**日期**：2026-11-03
**约束文档**：[`DEVELOPMENT.md`](DEVELOPMENT.md) 规则 R30

---

## 一、已完成（有证据）

### 1. 安全删除（路径遍历防护）

- 新增 `core/exceptions.py::safe_rmtree(path, verify_deleted=True, allowed_root=...)`
  - 用 `Path.relative_to` 判界，`.env-tools-evil` 这类前缀伪装不会被误放行；
  - 不使用 `ignore_errors=True` 吞掉用户路径的删除失败；
  - 路径不存在时幂等返回（重复卸载安全）。
- `main.py` 5 处删除全部改为 `_safe_rmtree()`（它把 `allowed_root=CONFIG_DIR` 传下去，
  测试改写 `main.CONFIG_DIR` 时自动跟随）。
- 卸载遇到"不在工作目录内"的路径：**拒绝删除、写摘要、继续清理环境变量**，
  不再中途抛异常（原行为是中断，属于行为改进）。
- 命令注入面收窄：`tasklist /FI IMAGENAME eq <name>` 先用
  `_TASKLIST_NAME_RE` 校验映像名；`_process_name(pid)` 先 `int()` 收敛。

护栏：`tests/bt_core_tests.py::SafeRmtreeTests`（5 条，含越界与前缀伪装）。

### 2. 结构化日志（已接入 UI 与诊断导出）

- `core/logger.py::StructuredLogger`：OK / INFO / WARNING / ERROR 四级，
  与界面颜色一一对应（绿/灰/橙/红），保留最近 500 条，支持 `export_json()`。
- `AppWindow._append_log()` 写入界面/落盘的同时同步进 logger 历史。
- 「导出诊断」新增一节 `结构化日志（最近 50 条）`，用户贴 issue 即可看到分级事实。
- 修掉了初版实现的**无限递归**（`info()` 与内部 `_emit()` 互相调用）；
  现在内部一律走 `logging.Logger` 的方法。

护栏：`StructuredLoggerTests`（5 条，含递归回归、`%s` 参数渲染、回调异常隔离）。

### 3. 异常处理收窄

- 版本抓取/探测区域 **52 处** `except Exception` → `except BEST_EFFORT_ERRORS`
  （`requests.RequestException | OSError | ValueError | KeyError | TypeError |
  AttributeError | RuntimeError`）。
- 关键路径替换为具体类型：文件管理（`OSError/FileNotFoundError`）、
  HTTP（`requests.RequestException`）、注册表（`OSError/WindowsError`）、
  JSON（`ValueError/UnicodeDecodeError`）。
- 仍保留的 `except Exception` 只剩 109 处，集中在：
  - 版本抓取里"任何意外都只让这一个组件回退内置清单"的兜底；
  - UI 线程最后一道防线（QThread.run 二次 catch、页面渲染循环、凭据解密）。
  R30 规定：这类保留必须写明"为什么不能外抛"。

### 4. 配置集中

- `core/constants.py` 现在是超时 / 缓存 TTL / 镜像基址 / 安全阈值的唯一定义处。
- `main.py` 只保留导入（缺失 `core/` 时走 fallback 常量），
  已迁移：`DOWNLOAD_*_TIMEOUT`、`DEVTOOL_FETCH_TIMEOUT`、`_JAVA_MAJOR_TIMEOUT`、
  `TK_SUPPRESS_BG_LIMIT`、`UPDATE_CHECK_INTERVAL_SEC`、`UPDATE_HTTP_TIMEOUT`。

### 5. 模块化拆分（main.py → core/）

| 模块 | 内容 | main.py 侧 |
|------|------|-----------|
| `core/constants.py` | 全部配置常量 | 导入 + fallback |
| `core/logger.py` | 结构化日志 | `logger` 单例 + UI 接线 |
| `core/exceptions.py` | 异常层级 + `safe_rmtree` + `BEST_EFFORT_ERRORS` | 导入 |
| `core/versioning.py` | `Version`、三套口径、`version_is_newer` | 导入 + 兼容薄壳 |
| `core/windows_service.py` | SCM 查询/启停后端、`ServiceInfo` | re-export，保证老调用点与测试不变 |

`main.py` 从 ~24.3k 行降到约 23.2k 行；被抽出的能力都有独立护栏。

---

## 二、验证记录

```text
python tests/run_all_tests.py
合计 1071 条用例 / 24 个文件 / 24 通过 / 0 失败

python -c "... MainWindow() → show() → close() ..."
SMOKE OK     （offscreen，退出无异常）
```

新增护栏套件：`tests/bt_core_tests.py`（22 条）。

---

## 三、后续可选（未在本轮实施）

1. **DownloadWorker 抽到 `core/download.py`**：它依赖 `main.http_session` 的桩点
   （测试大量 `mock.patch.object(main, "http_session")`）。抽取需要注入一个
   "延迟解引用 main 的函数"，已在 R30 记录约束，但本轮未动，避免打断 261 条启动护栏。
2. **UI 组件拆包**：`MainWindow` / `ComponentCard` 与大量 Qt 信号耦合，属于大手术，
   建议单独开分支并配真机演练。
3. **剩余 109 处泛化捕获继续收窄**：按文件分组、每组改完跑全量，勿一次性批量替换。
