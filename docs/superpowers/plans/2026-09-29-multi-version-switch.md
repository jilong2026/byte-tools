# 组件多版本安装与生效版本切换 · 第一期实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 7 个 PATH 型组件支持多版本并存，提供显式的"当前生效版本"概念与一键切换（失败整体回滚），并在版本下拉框里用图标标出哪些版本已安装。

**Architecture:** 磁盘布局本来就是 `<配置根>/<key>/<key>-<version>`（天然多版本），本期不动它。新增三层：① 组件能力位 `multi_version`（单一白名单登记处）；② `EnvManager` 上一组平台无关门面，含**持久层读取**（回滚要用注册表/shell rc 的真值，不是已被本工具改脏的 `os.environ`）；③ `apply_active_version()` —— 切换的唯一入口：写 `XXX_HOME`、把该组件在 PATH 里的条目收敛成一条、同步当前进程，任一步失败按快照回滚。UI 侧只加图标（`Qt.DecorationRole`）与状态文案，**不改下拉框条目文本**。

**Tech Stack:** Python 3.12 + PySide6（Qt 6）；测试用标准库 `unittest`（仓库无 pytest / 无 pyyaml / 无 gh CLI）；配置为 JSON 文件。

**Spec:** 本文档「设计决策」一节即规格（用户 2026-09-29 逐条确认，无独立 spec 文件）。

## Global Constraints

- 多版本白名单固定 7 个，**不得自行扩大**：`jdk` / `python` / `node` / `go` / `maven` / `gradle` / `bun`。
- `conda`（`installer_mode=True`）与所有服务型组件（mysql / mongodb / postgresql / tomcat / elasticsearch / nacos / kafka / docker / jenkins 等）本期**不进入多版本模型**。
- 下拉框条目的**显示文本必须与改造前逐字一致**：`ComponentCard._current_version()`（`main.py:4208`）与 `SearchableComboBox.repopulate(preferred=…)`（`main.py:3940`）都按文本反查版本对象，文本一变，选版/安装/卸载/保存配置全链路错位。已装状态只能走图标。
- 切换是**原子操作**：`XXX_HOME`、PATH 条目、当前进程三处要么全成，要么按快照全回滚，禁止留下「`JAVA_HOME` 指 21、PATH 指 17」的中间态。
- 只清理**本组件目录内**的 PATH 条目；其他组件与用户自己的条目一律不动。
- 注释与面向用户的日志一律中文；文件行尾保持 **LF**（`main.py` 现为 `CR=0`，改动后必须仍为 0）。
- 测试文件必须先 stub WMI 再 import：`platform._wmi_query` 抛 `OSError` + `platform.uname.cache_clear()`；碰 Qt 的还要 `QT_QPA_PLATFORM=offscreen`。
- **测试绝不写真注册表、绝不改用户真实 shell rc、绝不留脏 `os.environ`**：Windows 分支打桩 `EnvManager._read_windows_user_path` / `_write_registry_env` / `EnvManager.get`；Unix 分支打桩 `EnvManager._shell_rc_file` 指向临时文件并把 `main.CURRENT_OS` 设为 `"Linux"`；`PATH`/`JAVA_HOME` 等进程环境键在 tearDown 里还原。
- **助手不执行任何 git 命令**（含 `git add` / `git commit` / `git push`），也不执行删除类 shell 命令；commit 步骤一律写成"输出命令，由用户复制执行"。
- 命令统一用仓库虚拟环境：`.venv/Scripts/python.exe`。
- 不为测试在产品代码里加开关；打桩一律在测试侧完成（`EnvSandbox` 是唯一允许的接缝）。

---

## 设计决策（2026-09-29 与用户确认，实施时不得单方面改动）

| # | 决策 | 落地位置 |
|---|---|---|
| D1 | 只有 7 个组件允许多版本；判据是"PATH 型 + 归档解压安装"；不按 key 硬猜 | `MULTI_VERSION_KEYS` + `Component.multi_version`（Task 1） |
| D2 | `selections`（下拉框选中，想装/想操作哪个）与 `active`（当前生效哪个）分成两个字段；不一致时界面标「均未生效」 | `CONFIG_FILE` 顶层 `active`；合并写（Task 5） |
| D3 | 切换必须原子且可回滚，属**设计约束**不是实现细节 | `apply_active_version()` + `SwitchError`（Task 4） |
| D4 | 已装标记用列表项图标（`Qt.DecorationRole`），绝不写进条目文本 | `_installed_icon()` + `_refresh_installed_marks()`（Task 7） |
| D5 | 用户项目侧配置（pom / gradle / IDE）完全不管；不做 shell 钩子、不做 `.java-version` 自动切换 | 非目标，写进 DEVELOPMENT.md R3（Task 10） |
| D6 | 切换成功的日志必须同时说明"已开终端/IDE 不受影响"，并提醒 Windows `javapath` 可能遮蔽 | 日志末行（Task 4）+ 验收清单（Task 8） |

**本期非目标**：服务型组件多实例与端口冲突、按目录自动切换、`toolchains.xml` 生成、卸载残留可视化。

**要一并修掉的两个既有真 bug**（不修则切换功能是假的）：
- `main.py:4448-4454`：「仅配置环境变量」把候选目录 `sort()` 后取最后一个，是**字典序**——`jdk-8` 排在 `jdk-21` 之后。
- `main.py:3499` + `main.py:3554`：PATH 条目按"条目本身"去重，多版本会**同时留多条**，而 `XXX_HOME` 只被覆盖成最后一个 → `java -version` 与 `mvn -v` 能报不同版本。

---

## 文件结构（本期落点）

| 文件 / 位置 | 职责 | 动作 |
|---|---|---|
| `main.py:173-197` `Component` | 数据模型 | 加 `multi_version: bool = False` |
| `main.py:278-288` `installed_dirs()` | 磁盘真相 | 不动（已可用） |
| `main.py` `installed_dirs()` 之后 | 新纯函数 `version_from_install_dir()` / `installed_versions()` | 创建（Task 2） |
| `main.py` `COMPONENT_CATEGORY_OF` 附近 | `MULTI_VERSION_KEYS` | 创建（Task 1） |
| `main.py:3368+` `EnvManager` 末尾 | 7 个平台无关门面方法 | 创建（Task 3） |
| `main.py` `EnvManager` 之后 | `SwitchError` + `apply_active_version()` | 创建（Task 4） |
| `main.py` 模块级 | `load_active_map()` / `save_active_version()` / `infer_active_from_env()` | 创建（Task 5） |
| `main.py:4442-4484` | `on_configure_clicked` / `_configure_env` | 改造 + 新增 `ComponentCard._apply_active()`（Task 6） |
| `main.py:4176-4215` | combo 装载 | 加 `_refresh_installed_marks()`，文本函数不动（Task 7） |
| `main.py:4075-4173` | 状态胶囊 | 多版本组合文案 + 按钮启用条件（Task 8） |
| `main.py:289-388` | `resolve_uninstall_target` / `uninstall` | 定位优先按选中版本；PATH 清理收窄到被删目录；active 重排（Task 9） |
| `main.py:5421-5446` | `_load_settings` / `_save_settings` | `active` 合并读写（Task 5） |
| `main.py:2716+` | `build_components()` 末尾统一赋值 | 与 `category` 同处赋 `multi_version`（Task 1） |
| `bt_multiversion_tests.py` | 本期回归测试 | 创建（Task 1 起逐步追加） |
| `DEVELOPMENT.md` | 新增规则 **R3** | 修改（Task 10） |
| `README.md` / `README_EN.md` / `CODE_WIKI.md` | 用户可见行为 | 修改（Task 10） |

---

## Task 0: 测试沙箱基类（后续所有任务共用）

**Files:**
- Create: `bt_multiversion_tests.py`

**Interfaces:**
- Produces: `EnvSandbox(unittest.TestCase)` —— 属性 `self.root`（假 `CONFIG_DIR`）、`self.rc`（假 shell rc）、`self.win_env: dict`、`self.win_path: list`；方法 `as_windows()` / `as_linux()` / `make_component(key, *versions)`。

- [ ] **Step 1: 写沙箱本身**

创建 `bt_multiversion_tests.py`，内容如下（这份代码是后续任务测试的地基，先建后跑）：

```python
"""组件多版本 + 生效版本切换的规格测试（离线，不联网）。

沙箱原则：落盘的地方全换成临时目录或内存桩——
  · Windows 分支打桩 _read_windows_user_path / _write_registry_env / EnvManager.get，
    绝不碰 HKCU；
  · Unix 分支打桩 _shell_rc_file 指向临时文件，绝不碰用户真实的 ~/.zshrc；
  · 产品代码会顺手改 os.environ（PATH / JAVA_HOME），每个用例结束都还原。
计划文档：docs/superpowers/plans/2026-09-29-multi-version-switch.md
"""
import json
import os
import platform as _platform
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 本机 WMI 卡死会让 platform.system() 永久阻塞，必须在 import main 之前 stub
_platform._wmi_query = lambda *a, **k: (_ for _ in ()).throw(
    OSError("WMI disabled for test process"))
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = r"E:\file\test\byte-tools"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402

ENV_KEYS = ("PATH", "JAVA_HOME", "MAVEN_HOME", "NODE_HOME", "GO_HOME", "GRADLE_HOME", "BUN_HOME")


class EnvSandbox(unittest.TestCase):
    """把 CONFIG_DIR / CONFIG_FILE / shell rc / Windows 注册表读写全部沙箱化。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "env-tools"
        self.root.mkdir(parents=True)

        self._saved = {k: getattr(main, k) for k in ("CONFIG_DIR", "CONFIG_FILE", "CURRENT_OS")}
        main.CONFIG_DIR = self.root
        main.CONFIG_FILE = self.root / "config.json"
        self.addCleanup(lambda: [setattr(main, k, v) for k, v in self._saved.items()])

        # Unix 落点：临时 rc
        self.rc = self.root / "rc"
        self.rc.write_text("# user rc\n", encoding="utf-8")
        self._orig_rc = main.EnvManager._shell_rc_file
        main.EnvManager._shell_rc_file = staticmethod(lambda: self.rc)
        self.addCleanup(setattr, main.EnvManager, "_shell_rc_file", self._orig_rc)

        # Windows 落点：内存
        self.win_env = {}
        self.win_path = []
        self._orig_read = main.EnvManager._read_windows_user_path
        self._orig_write = main.EnvManager._write_registry_env
        self._orig_get = main.EnvManager.get
        self._orig_read_env = getattr(main.EnvManager, "_read_windows_user_env", None)

        def fake_read():
            return list(self.win_path)

        def fake_write(name, value):
            if name.lower() == "path":
                self.win_path[:] = [p for p in str(value).split(";") if p]
            else:
                self.win_env[name] = value

        def fake_get(name):
            return self.win_env.get(name) or os.environ.get(name)

        main.EnvManager._read_windows_user_path = staticmethod(fake_read)
        main.EnvManager._write_registry_env = staticmethod(fake_write)
        main.EnvManager.get = staticmethod(fake_get)
        if self._orig_read_env is not None:      # Task 3 落地后生效：不碰真实 HKCU
            main.EnvManager._read_windows_user_env = staticmethod(
                lambda name: self.win_env.get(name))

        def restore_win():
            main.EnvManager._read_windows_user_path = self._orig_read
            main.EnvManager._write_registry_env = self._orig_write
            main.EnvManager.get = self._orig_get
            if self._orig_read_env is not None:
                main.EnvManager._read_windows_user_env = self._orig_read_env
        self.addCleanup(restore_win)

        # 卡片构造会跑状态探测，这里统一停掉并在结束后还原
        self._orig_detect = main.ComponentCard._detect_status
        main.ComponentCard._detect_status = lambda self, *a, **k: None
        self.addCleanup(setattr, main.ComponentCard, "_detect_status", self._orig_detect)

        # 产品代码会写 os.environ，逐键还原
        self._orig_environ = {k: os.environ.get(k) for k in ENV_KEYS}

        def restore_environ():
            for k, v in self._orig_environ.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore_environ)

    # ---- 便捷方法 ----
    def as_windows(self):
        main.CURRENT_OS = "Windows"

    def as_linux(self):
        main.CURRENT_OS = "Linux"

    def enable_detect(self):
        """放开真实的状态探测（Task 8 的胶囊用例需要它），但绝不允许起真实探测线程。

        `_schedule_version_probe` 会真的执行组件可执行文件去取版本号，在测试里等于
        去跑用户机器上的 java —— 所以这里把它替换成"记录调用但不执行"。
        """
        main.ComponentCard._detect_status = self._orig_detect
        self.addCleanup(setattr, main.ComponentCard, "_detect_status",
                        lambda self, *a, **k: None)
        orig_probe = main.ComponentCard._schedule_version_probe
        self.probe_calls = []
        main.ComponentCard._schedule_version_probe = (
            lambda self, exe_path, *a, **k: self.probe_calls.append(exe_path))
        self.addCleanup(setattr, main.ComponentCard, "_schedule_version_probe", orig_probe)

    def make_component(self, key: str, *versions):
        """取真实组件定义，并在沙箱里造出这些版本的安装目录。"""
        comp = next(c for c in main.build_components() if c.key == key)
        for v in versions:
            (comp.install_dir(v) / "bin").mkdir(parents=True, exist_ok=True)
        return comp


class SandboxSelfCheck(EnvSandbox):
    """沙箱自己也要有断言：它失效时，后面所有用例都会变成假绿灯。"""

    def test_config_dir_is_sandboxed(self):
        self.assertEqual(main.CONFIG_DIR, self.root)
        self.assertEqual(main.CONFIG_FILE, self.root / "config.json")
        self.assertTrue(str(self.rc).startswith(self.tmp.name))
        self.assertNotEqual(main.CONFIG_DIR, Path.home() / ".env-tools")

    def test_make_component_creates_real_dirs(self):
        comp = self.make_component("jdk", "21.0.4", "17.0.12")
        self.assertTrue((comp.install_dir("21.0.4") / "bin").is_dir())
        self.assertEqual(main.CONFIG_DIR, self.root)   # 目录确实落在沙箱里
        self.assertTrue(str(comp.install_dir("21.0.4")).startswith(self.tmp.name))

    def test_windows_stub_is_installed(self):
        # 沙箱必须已经接管 Windows 那两个落地点，否则测试会写真实 HKCU
        self.win_env["JAVA_HOME"] = "stubbed"
        self.assertEqual(main.EnvManager.get("JAVA_HOME"), "stubbed")
        main.EnvManager._write_registry_env("Path", r"C:\a;C:\b")
        self.assertEqual(self.win_path, [r"C:\a", r"C:\b"])
```

- [ ] **Step 2: 跑沙箱自检**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS（3 个自检用例；此时产品代码还没动，`main.py` 里 `Component` 尚无 `multi_version` 不影响本任务）

---

## Task 1: 组件能力位 `multi_version` 与白名单

**Files:**
- Modify: `main.py`（`Component` 数据类 `main.py:173-197`；`COMPONENT_CATEGORY_OF` 附近；`build_components()` 末尾赋值处）
- Test: `bt_multiversion_tests.py`

**Interfaces:**
- Consumes: Task 0 的 `EnvSandbox`
- Produces: `Component.multi_version: bool`；`main.MULTI_VERSION_KEYS: set[str]`

- [ ] **Step 1: 追加失败测试**

```python
EXPECTED_MULTI_VERSION = {"jdk", "python", "node", "go", "maven", "gradle", "bun"}


class MultiVersionFlag(EnvSandbox):
    def setUp(self):
        super().setUp()
        self.components = {c.key: c for c in main.build_components()}

    def test_only_the_seven_agreed_components_are_multi_version(self):
        got = {k for k, c in self.components.items() if c.multi_version}
        self.assertEqual(got, EXPECTED_MULTI_VERSION)

    def test_service_and_installer_mode_components_are_off(self):
        for key in ("conda", "mysql", "tomcat", "nacos", "elasticsearch",
                    "docker", "powershell", "nginx", "kubectl"):
            self.assertFalse(self.components[key].multi_version, key)

    def test_every_component_has_the_attribute(self):
        for key, comp in self.components.items():
            self.assertIsInstance(comp.multi_version, bool, key)
```

- [ ] **Step 2: 跑测试，确认它因为字段不存在而失败**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: FAIL —`AttributeError: 'Component' object has no attribute 'multi_version'`

- [ ] **Step 3: 加字段**

`main.py` 的 `Component` 内，紧跟 `installer_mode: bool = False` 之后：

```python
    # 是否允许并存多个安装版本，并在界面切换"当前生效版本"。
    # 判据：归档解压安装（非 installer_mode）+ 靠 XXX_HOME / PATH 生效的 PATH 型组件。
    # 由 build_components() 末尾按 MULTI_VERSION_KEYS 统一赋值，不要在构造处手写。
    multi_version: bool = False
```

- [ ] **Step 4: 加白名单常量**

在 `COMPONENT_CATEGORY_OF` 字典之后：

```python
# 允许并存多版本、可切换生效版本的组件（2026-09-29 与用户确认，固定 7 个，别自行扩大）。
# 排除 conda：installer_mode 组件装在固定目录、卸载也不删目录，"每版本一目录"的前提不成立。
# 排除服务型组件（mysql/tomcat/nacos/es/…）：多版本的真矛盾是端口与数据目录，不是环境变量。
MULTI_VERSION_KEYS = {"jdk", "python", "node", "go", "maven", "gradle", "bun"}
```

- [ ] **Step 5: 统一赋值（与 category 同一处，改一处全量生效）**

`build_components()` 末尾给 `category` 赋值的那个循环里加一行：

```python
    for comp in components:
        comp.category = COMPONENT_CATEGORY_OF[comp.key]        # 已有：漏登记直接 KeyError
        comp.multi_version = comp.key in MULTI_VERSION_KEYS    # 新增：不在白名单就是 False
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS

- [ ] **Step 7: 交给用户提交（助手不执行 git）**

```bash
cd /e/file/test/byte-tools
git add main.py bt_multiversion_tests.py
git commit -m "feat: 组件多版本能力位 multi_version，白名单固定 7 个 PATH 型组件"
```

---

## Task 2: 版本目录名 ⇄ 版本号，并按语义版本降序

**Files:**
- Modify: `main.py`（模块级函数，紧跟 `Component.installed_dirs()` 之后，即 `main.py:288` 附近）
- Test: `bt_multiversion_tests.py`

**Interfaces:**
- Consumes: `Component.install_dir(version)`（`main.py:199`）、`Component.installed_dirs()`（`main.py:278`）、`_sort_semver_desc(vs)`（模块内已存在；Python 运行时解析，定义位置在后可调用）
- Produces:
  - `version_from_install_dir(comp: Component, path: Path) -> Optional[str]`
  - `installed_versions(comp: Component) -> List[Tuple[str, Path]]`（版本**降序**，最新在前）

- [ ] **Step 1: 追加失败测试**

```python
class InstalledVersions(EnvSandbox):
    def test_parses_version_from_dir_name(self):
        comp = self.make_component("jdk")
        self.assertEqual(main.version_from_install_dir(comp, Path("x/jdk-21.0.4")), "21.0.4")
        self.assertIsNone(main.version_from_install_dir(comp, Path("x/python-3.12.4")))
        self.assertIsNone(main.version_from_install_dir(comp, Path("x/jdk")))
        self.assertIsNone(main.version_from_install_dir(comp, Path("x/jdk-")))

    def test_orders_by_semver_not_lexicographic(self):
        # 这条正是旧 bug 的形状：目录名字典序会把 jdk-8 排在 jdk-21 之后
        comp = self.make_component("jdk", "8", "21.0.4", "17.0.12")
        self.assertEqual([v for v, _p in main.installed_versions(comp)],
                         ["21.0.4", "17.0.12", "8"])

    def test_ignores_downloads_and_foreign_dirs(self):
        comp = self.make_component("jdk", "21.0.4")
        (main.CONFIG_DIR / "jdk" / "downloads").mkdir(parents=True, exist_ok=True)
        (main.CONFIG_DIR / "jdk" / "notajdk").mkdir(parents=True, exist_ok=True)
        self.assertEqual([v for v, _p in main.installed_versions(comp)], ["21.0.4"])

    def test_returns_pair_with_the_exact_install_dir(self):
        comp = self.make_component("python", "3.12.4", "3.11.9")
        pairs = main.installed_versions(comp)
        self.assertEqual(pairs[0], ("3.12.4", comp.install_dir("3.12.4")))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: FAIL —`AttributeError: module 'main' has no attribute 'version_from_install_dir'`

- [ ] **Step 3: 实现两个纯函数**

紧跟 `Component.installed_dirs()` 之后（属组件模型层，不新建文件）：

```python
def version_from_install_dir(comp: "Component", path: Path) -> Optional[str]:
    """从安装目录名反解版本号；目录名必须符合 `<key>-<version>`，否则 None。

    入参 comp: Component  用它的 key 做前缀判定（避免把 python-3.12 算到 jdk 头上）
    入参 path: Path       磁盘上的目录对象
    返回:      Optional[str]  版本号；不符合命名约定（downloads、残缺名）返回 None

    说明: 安装落位时目录被统一重命名为 install_dir(version)，所以这里与写入端共用一套约定。
    """
    prefix = f"{comp.key}-"
    name = path.name
    if not name.startswith(prefix):
        return None
    return name[len(prefix):] or None


def installed_versions(comp: "Component") -> List[Tuple[str, Path]]:
    """该组件在磁盘上真实装着的版本，按语义版本**降序**（最新在前）。

    入参 comp: Component
    返回: List[Tuple[str, Path]]  (版本号, 安装目录)

    说明: 排序必须走 _sort_semver_desc。用 str.sort() 会得到 jdk-8 > jdk-21 的错序，
          "配置环境变量"和"卸载后自动切到剩余最高版本"都会挑错版本。
    """
    pairs: List[Tuple[str, Path]] = []
    for path in comp.installed_dirs():
        ver = version_from_install_dir(comp, path)
        if ver:
            pairs.append((ver, path))
    order = {v: i for i, v in enumerate(_sort_semver_desc([v for v, _p in pairs]))}
    return sorted(pairs, key=lambda p: order[p[0]])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS

---

## Task 3: `EnvManager` 平台无关门面（含持久层读取）

**Files:**
- Modify: `main.py`（`EnvManager` 类末尾，即现有 `remove_unix_path_entries_under`（`main.py:3649`）之后）
- Test: `bt_multiversion_tests.py`

**Interfaces:**
- Consumes: 现有 8 个平台函数（`set_windows_user_env` / `remove_windows_user_env` / `append_windows_path` / `remove_windows_path_entry` / `remove_windows_path_entries_under` / `set_unix_env` / `remove_unix_env` / `append_unix_path` / `remove_unix_path_entry` / `remove_unix_path_entries_under` / `_shell_rc_file` / `_read_windows_user_path`）
- Produces（签名固定，Task 4/5/9 依赖）:
  - `EnvManager.write_user_env(name: str, value: str) -> None`
  - `EnvManager.drop_user_env(name: str) -> None`
  - `EnvManager.read_user_env(name: str) -> Optional[str]`
  - `EnvManager._read_windows_user_env(name: str) -> Optional[str]`（**测试接缝**：`read_user_env` 的 Windows 分支必须走它，否则测试会去读用户真实的 `HKCU\Environment`，"不存在返回 None"这类断言会因为用户机器上真有 `JAVA_HOME` 而随机失真）
  - `EnvManager.add_path_entry(entry: str) -> None`
  - `EnvManager.drop_path_entry(entry: str) -> None`
  - `EnvManager.remove_path_entries_under(root: str) -> List[str]`
  - `EnvManager.read_user_path_entries() -> List[str]`

- [ ] **Step 1: 追加失败测试**

```python
class EnvFacade(EnvSandbox):
    def test_unix_write_read_drop_roundtrip(self):
        self.as_linux()
        Env = main.EnvManager
        Env.write_user_env("JAVA_HOME", "/x/jdk-21.0.4")
        self.assertEqual(Env.read_user_env("JAVA_HOME"), "/x/jdk-21.0.4")
        self.assertIn('export JAVA_HOME="/x/jdk-21.0.4"', self.rc.read_text(encoding="utf-8"))
        Env.drop_user_env("JAVA_HOME")
        self.assertIsNone(Env.read_user_env("JAVA_HOME"))

    def test_unix_path_entry_roundtrip_and_list(self):
        self.as_linux()
        Env = main.EnvManager
        Env.add_path_entry("/x/jdk-21.0.4/bin")
        Env.add_path_entry("/x/jdk-17.0.12/bin")
        self.assertEqual(Env.read_user_path_entries(),
                         ["/x/jdk-21.0.4/bin", "/x/jdk-17.0.12/bin"])
        removed = Env.remove_path_entries_under("/x/jdk-17.0.12")
        self.assertEqual(removed, ["/x/jdk-17.0.12/bin"])
        self.assertEqual(Env.read_user_path_entries(), ["/x/jdk-21.0.4/bin"])

    def test_windows_write_and_list(self):
        self.as_windows()
        Env = main.EnvManager
        Env.write_user_env("JAVA_HOME", r"C:\x\jdk-21.0.4")
        self.assertEqual(self.win_env["JAVA_HOME"], r"C:\x\jdk-21.0.4")
        self.assertEqual(Env.read_user_env("JAVA_HOME"), r"C:\x\jdk-21.0.4")
        Env.add_path_entry(r"C:\x\jdk-21.0.4\bin")
        self.assertIn(r"C:\x\jdk-21.0.4\bin", Env.read_user_path_entries())

    def test_windows_read_absent_env_returns_none(self):
        self.as_windows()
        self.assertIsNone(main.EnvManager.read_user_env("JAVA_HOME"))

    def test_windows_remove_under_root_only_touches_that_root(self):
        self.as_windows()
        self.win_path[:] = [r"C:\x\jdk\jdk-17.0.12\bin",
                            r"C:\x\jdk\jdk-21.0.4\bin",
                            r"C:\Windows\system32"]
        removed = main.EnvManager.remove_path_entries_under(r"C:\x\jdk\jdk-17.0.12")
        self.assertEqual([p.lower() for p in removed], [r"c:\x\jdk\jdk-17.0.12\bin"])
        self.assertIn(r"C:\x\jdk\jdk-21.0.4\bin", self.win_path)
        self.assertIn(r"C:\Windows\system32", self.win_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: FAIL —`AttributeError: type object 'EnvManager' has no attribute 'write_user_env'`

- [ ] **Step 3: 实现门面**

```python
    # ------------------------------------------------------------------
    # 平台无关门面：切换生效版本只调这组方法，业务层不再各自判断 CURRENT_OS。
    # 读接口读的是「持久层」（注册表 / shell rc）而不是 os.environ ——
    # os.environ 会被本工具自己改脏，不能当回滚用的"改动前状态"。
    # ------------------------------------------------------------------

    @staticmethod
    def write_user_env(name: str, value: str) -> None:
        if CURRENT_OS == "Windows":
            EnvManager.set_windows_user_env(name, value)
        else:
            EnvManager.set_unix_env(name, value)

    @staticmethod
    def drop_user_env(name: str) -> None:
        if CURRENT_OS == "Windows":
            EnvManager.remove_windows_user_env(name)
        else:
            EnvManager.remove_unix_env(name)

    @staticmethod
    def _read_windows_user_env(name: str) -> Optional[str]:
        """读 HKCU\\Environment 里某个值。单独抽出来只为给测试一个可打桩的接缝
        （Task 0 的沙箱替换它，避免测试读到用户真实的 JAVA_HOME）。"""
        import winreg  # type: ignore

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                                winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, name)
            return str(value)
        except FileNotFoundError:
            return None

    @staticmethod
    def read_user_env(name: str) -> Optional[str]:
        """读持久层里某环境变量的值，不存在返回 None。"""
        if CURRENT_OS == "Windows":
            return EnvManager._read_windows_user_env(name)
        rc = EnvManager._shell_rc_file()
        if not rc.exists():
            return None
        text = rc.read_text(encoding="utf-8")
        marker_begin = f"# >>> byte-tools:{name} >>>"
        marker_end = f"# <<< byte-tools:{name} <<<"
        if marker_begin not in text or marker_end not in text:
            return None
        block = text.split(marker_begin, 1)[1].split(marker_end, 1)[0]
        m = _re.search(r'export\s+' + _re.escape(name) + r'="([^"]*)"', block)
        return m.group(1) if m else None

    @staticmethod
    def add_path_entry(entry: str) -> None:
        if CURRENT_OS == "Windows":
            EnvManager.append_windows_path(entry)
        else:
            EnvManager.append_unix_path(entry)

    @staticmethod
    def drop_path_entry(entry: str) -> None:
        if CURRENT_OS == "Windows":
            EnvManager.remove_windows_path_entry(entry)
        else:
            EnvManager.remove_unix_path_entry(entry)

    @staticmethod
    def remove_path_entries_under(root: str) -> List[str]:
        """删除 root 目录内（含目录已不存在的残留）的 PATH 条目，返回被删条目列表。"""
        if CURRENT_OS == "Windows":
            return EnvManager.remove_windows_path_entries_under(root)
        return EnvManager.remove_unix_path_entries_under(root)

    @staticmethod
    def read_user_path_entries() -> List[str]:
        """读持久层里的 PATH 条目。Unix 侧只能看到本工具用 marker 写过的那些。"""
        if CURRENT_OS == "Windows":
            return EnvManager._read_windows_user_path()
        rc = EnvManager._shell_rc_file()
        if not rc.exists():
            return []
        text = rc.read_text(encoding="utf-8")
        pattern = _re.compile(
            r"# >>> byte-tools:PATH:(.*?) >>>.*?# <<< byte-tools:PATH:\1 <<<", _re.DOTALL)
        return [m.group(1) for m in pattern.finditer(text)]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS

- [ ] **Step 5: 交给用户提交**

```bash
cd /e/file/test/byte-tools
git add main.py bt_multiversion_tests.py
git commit -m "feat: EnvManager 增加平台无关门面与持久层读取，为生效版本切换做准备"
```

---

## Task 4: `apply_active_version()` —— 切换的唯一入口，失败整体回滚

**Files:**
- Modify: `main.py`（模块级，紧跟 `EnvManager` 类之后）
- Test: `bt_multiversion_tests.py`

**Interfaces:**
- Consumes: Task 2 `installed_versions()`、Task 3 的 7 个门面方法
- Produces: `SwitchError(RuntimeError)`；`apply_active_version(comp: Component, version: str) -> List[str]`（返回中文步骤说明，界面直接逐行打日志）

- [ ] **Step 1: 追加失败测试**

```python
class SwitchActive(EnvSandbox):
    def setUp(self):
        super().setUp()
        self.comp = self.make_component("jdk", "21.0.4", "17.0.12")

    def test_windows_switch_sets_home_and_collapses_path_to_one_entry(self):
        self.as_windows()
        # 先制造旧状态：两个版本各留一条 PATH（就是现在那个病）
        self.win_path[:] = [str(self.comp.install_dir("17.0.12") / "bin"),
                            str(self.comp.install_dir("21.0.4") / "bin"),
                            r"C:\Windows\system32"]
        steps = main.apply_active_version(self.comp, "21.0.4")
        self.assertEqual(self.win_env["JAVA_HOME"], str(self.comp.install_dir("21.0.4")))
        jdk_entries = [p for p in self.win_path if "jdk-" in p.lower()]
        self.assertEqual(len(jdk_entries), 1, self.win_path)
        self.assertIn("jdk-21.0.4", jdk_entries[0])
        self.assertIn(r"C:\Windows\system32", self.win_path)   # 别的条目不许动
        self.assertTrue(any("已开" in s or "重开" in s for s in steps),
                        "日志必须提示已开终端不受影响（决策 D6）")

    def test_linux_switch_writes_rc(self):
        self.as_linux()
        main.apply_active_version(self.comp, "17.0.12")
        rc_text = self.rc.read_text(encoding="utf-8")
        self.assertIn(str(self.comp.install_dir("17.0.12")), rc_text)
        self.assertNotIn("jdk-21.0.4", rc_text)

    def test_failure_after_env_write_rolls_back_env_and_path(self):
        self.as_windows()
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("17.0.12"))
        self.win_path[:] = [str(self.comp.install_dir("17.0.12") / "bin")]
        orig = main.EnvManager.append_windows_path
        main.EnvManager.append_windows_path = staticmethod(
            lambda entry: (_ for _ in ()).throw(OSError("disk full")))
        self.addCleanup(setattr, main.EnvManager, "append_windows_path", orig)

        with self.assertRaises(main.SwitchError):
            main.apply_active_version(self.comp, "21.0.4")
        # 回滚：JAVA_HOME 回到改动前，被清掉的旧条目回来了，新条目没留下
        self.assertEqual(self.win_env["JAVA_HOME"], str(self.comp.install_dir("17.0.12")))
        self.assertIn(str(self.comp.install_dir("17.0.12") / "bin"), self.win_path)
        self.assertNotIn(str(self.comp.install_dir("21.0.4") / "bin"), self.win_path)

    def test_missing_version_dir_raises_without_touching_anything(self):
        self.as_windows()
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("17.0.12"))
        self.win_path[:] = [str(self.comp.install_dir("17.0.12") / "bin")]
        before_env, before_path = dict(self.win_env), list(self.win_path)
        with self.assertRaises(main.SwitchError) as ctx:
            main.apply_active_version(self.comp, "99.9.9")
        self.assertIn("版本目录不存在", str(ctx.exception))
        self.assertEqual(self.win_env, before_env)
        self.assertEqual(self.win_path, before_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: FAIL —`AttributeError: module 'main' has no attribute 'apply_active_version'`

- [ ] **Step 3: 实现切换（快照 → 改动 → 失败回滚）**

```python
class SwitchError(RuntimeError):
    """生效版本切换失败；抛出前已尽量回滚到切换前状态。"""


def apply_active_version(comp: Component, version: str) -> List[str]:
    """把 comp 的生效版本设为 version，并保证三处一致。

    入参 comp:    Component   目标组件
    入参 version: str         必须是磁盘上真实存在的版本（installed_versions 里的项）
    返回: List[str] 中文步骤说明，界面逐行打日志
    异常: SwitchError 目录不存在，或任一步失败（已改动的部分按快照回滚后再抛）

    设计约束（2026-09-29 与用户确认，属规格而非实现细节，决策 D3）：
      1) 同一组件在 PATH 里只允许存在"生效版本"这一条：先清掉本组件目录下的所有条目，
         再写目标版本那一条。其他组件与用户自己的条目不动。
      2) XXX_HOME、PATH、当前进程三处要么全成要么全回滚。只成一半会出现
         「mvn -v 报 21、java -version 报 17」，比改造前更糟。
      3) 回滚依据是持久层快照（read_user_env + remove_path_entries_under 的返回值），
         不是 os.environ —— 后者已被本工具改脏，不能当"改动前"。
    """
    target = comp.install_dir(version)
    if not target.is_dir():
        raise SwitchError(f"版本目录不存在，无法设为生效：{target}")

    steps: List[str] = []
    prev_home = EnvManager.read_user_env(comp.env_var) if comp.env_var else None
    added_entries: List[str] = []
    removed_entries: List[str] = []

    def _rollback() -> None:
        # 逆序撤销：先撤 PATH 新增，再恢复被删条目，最后还原环境变量
        for entry in added_entries:
            try:
                EnvManager.drop_path_entry(entry)
            except Exception as exc:  # noqa: BLE001
                print(f"[rollback] 移除 PATH 条目失败 {entry}: {exc}")
        for entry in removed_entries:
            try:
                EnvManager.add_path_entry(entry)
            except Exception as exc:  # noqa: BLE001
                print(f"[rollback] 恢复 PATH 条目失败 {entry}: {exc}")
        if comp.env_var:
            try:
                if prev_home is None:
                    EnvManager.drop_user_env(comp.env_var)
                else:
                    EnvManager.write_user_env(comp.env_var, prev_home)
            except Exception as exc:  # noqa: BLE001
                print(f"[rollback] 恢复 {comp.env_var} 失败: {exc}")

    try:
        if comp.env_var:
            EnvManager.write_user_env(comp.env_var, str(target))
            steps.append(f"已设置 {comp.env_var}={target}")
        removed_entries = EnvManager.remove_path_entries_under(str(CONFIG_DIR / comp.key))
        bin_dir = str(target / comp.path_subdir) if comp.path_subdir else str(target)
        EnvManager.add_path_entry(bin_dir)
        added_entries.append(bin_dir)
        steps.append(f"PATH 已收敛为生效版本这一条：{bin_dir}")
        if removed_entries:
            steps.append("已移除同组件其他版本的条目：" + "、".join(removed_entries))
    except Exception as exc:
        _rollback()
        steps.append(f"切换失败，已回滚到切换前状态（原 {comp.env_var or '环境变量'}="
                     f"{prev_home if prev_home is not None else '未设置'}）：{exc}")
        raise SwitchError("；".join(steps)) from exc

    steps.append("当前进程已同步；已开着的终端与 IDE 需重开才会读到新值"
                 "（Windows 若装了 Oracle javapath，个别命令仍可能被它抢先）")
    return steps
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS

---

## Task 5: `active` 配置读写（与 `selections` 分开，老配置自动补齐）

**Files:**
- Modify: `main.py`（新增 3 个模块级函数；`MainWindow._load_settings` `main.py:5421`、`_save_settings` `main.py:5437`）
- Test: `bt_multiversion_tests.py`

**Interfaces:**
- Consumes: `CONFIG_FILE`（`main.py:104`）、`installed_versions()`、`version_from_install_dir()`、`EnvManager.read_user_env()`
- Produces:
  - `load_active_map() -> Dict[str, str]`
  - `save_active_version(comp_key: str, version: Optional[str]) -> None`
  - `infer_active_from_env(comp: Component) -> Optional[str]`

- [ ] **Step 1: 追加失败测试**

```python
class ActiveConfig(EnvSandbox):
    def test_missing_file_gives_empty_map(self):
        self.assertEqual(main.load_active_map(), {})

    def test_corrupt_file_is_not_fatal(self):
        main.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(main.load_active_map(), {})

    def test_saving_active_keeps_selections(self):
        main.CONFIG_FILE.write_text(json.dumps(
            {"selections": {"jdk": "17.0.12", "node": "20.15.0"}}, ensure_ascii=False),
            encoding="utf-8")
        main.save_active_version("jdk", "21.0.4")
        data = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data["active"], {"jdk": "21.0.4"})
        self.assertEqual(data["selections"], {"jdk": "17.0.12", "node": "20.15.0"},
                         "写 active 不许丢 selections")

    def test_clearing_active_removes_only_that_key(self):
        main.save_active_version("jdk", "21.0.4")
        main.save_active_version("node", "20.15.0")
        main.save_active_version("jdk", None)
        self.assertEqual(main.load_active_map(), {"node": "20.15.0"})

    def test_infer_active_from_env_reads_sandboxed_rc(self):
        self.as_linux()
        comp = self.make_component("jdk", "21.0.4")
        main.EnvManager.write_user_env("JAVA_HOME", str(comp.install_dir("21.0.4")))
        self.assertEqual(main.infer_active_from_env(comp), "21.0.4")

    def test_infer_active_ignores_homes_pointing_elsewhere(self):
        self.as_linux()
        comp = self.make_component("jdk", "21.0.4")
        main.EnvManager.write_user_env("JAVA_HOME", "/opt/other/jdk-11")
        self.assertIsNone(main.infer_active_from_env(comp))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: FAIL —`AttributeError: module 'main' has no attribute 'load_active_map'`

- [ ] **Step 3: 实现三个函数**

放在 `apply_active_version` 之后（同属"生效版本"这一层）：

```python
def load_active_map() -> Dict[str, str]:
    """读取"每个组件当前生效哪个版本"的登记表；文件缺失或损坏一律当空表。

    返回: Dict[str, str]  {组件 key: 生效版本号}
    """
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    active = data.get("active") if isinstance(data, dict) else None
    return dict(active) if isinstance(active, dict) else {}


def save_active_version(comp_key: str, version: Optional[str]) -> None:
    """登记或清除某组件的生效版本。

    入参 comp_key: str           组件 key
    入参 version: Optional[str]  版本号；None 表示清除（已无生效版本）

    说明: 必须**合并写**——先读原文件，只改 active 里那一项。整体覆盖会把
          selections（下拉框选中版本）一起抹掉，用户下次启动选中的版本全丢。
    """
    data: Dict[str, object] = {}
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    active = data.get("active")
    if not isinstance(active, dict):
        active = {}
    if version:
        active[comp_key] = version
    else:
        active.pop(comp_key, None)
    data["active"] = active
    ensure_dir(CONFIG_FILE.parent)
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def infer_active_from_env(comp: Component) -> Optional[str]:
    """老配置没记 active 时，从持久层的 XXX_HOME 反推当前生效版本。

    返回: Optional[str]  版本号；反推不出（用户自己装的、指向别处、目录名不规范）时 None

    说明: 这一步是为了不把"已经在用系统里那个 JDK 的用户"显示成"一个都没生效"。
          推不出来就返回 None，界面写"均未生效"，不要乱猜。
    """
    if not comp.env_var:
        return None
    home = EnvManager.read_user_env(comp.env_var) or EnvManager.get(comp.env_var)
    if not home:
        return None
    path = Path(os.path.expandvars(str(home)))
    if not EnvManager._under_root(str(path), str(CONFIG_DIR / comp.key)):
        return None
    return version_from_install_dir(comp, path)
```

- [ ] **Step 4: `_save_settings` 改成合并写（`main.py:5437`）**

```python
    def _save_settings(self) -> None:
        """保存下拉框选中版本；active 由切换那侧维护，这里必须原样保留。"""
        try:
            ensure_dir(CONFIG_DIR)
            data: dict = {}
            if CONFIG_FILE.exists():
                try:
                    loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = loaded
                except Exception:
                    data = {}
            data["selections"] = {
                card.component.key: card.version_combo.currentText()
                for card in self.cards
            }
            if not isinstance(data.get("active"), dict):
                data["active"] = {}
            CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        except Exception:
            pass
```

- [ ] **Step 5: 加一条防回归测试（窗口保存不丢 active）**

```python
class SaveSettingsKeepsActive(EnvSandbox):
    def test_window_save_preserves_active(self):
        main.save_active_version("jdk", "21.0.4")
        app = QApplication.instance() or QApplication([])
        orig_fetch = main.MainWindow._start_fetch_versions
        main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
        self.addCleanup(setattr, main.MainWindow, "_start_fetch_versions", orig_fetch)
        win = main.MainWindow()
        self.addCleanup(win.deleteLater)
        win._save_settings()
        data = json.loads(main.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data["active"], {"jdk": "21.0.4"})
        self.assertIn("jdk", data["selections"])
```

文件头补 `from PySide6.QtWidgets import QApplication`。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS

- [ ] **Step 7: 交给用户提交**

```bash
cd /e/file/test/byte-tools
git add main.py bt_multiversion_tests.py
git commit -m "feat: active 生效版本登记表与 selections 分离，写配置改为合并保留"
```

---

## Task 6: 「仅配置环境变量」改为"把选中版本设为生效"

**Files:**
- Modify: `main.py:4442-4484`（`on_configure_clicked`、`_configure_env`）
- Test: `bt_multiversion_tests.py`

**Interfaces:**
- Consumes: `installed_versions()`、`apply_active_version()`、`save_active_version()`、`load_active_map()`、`infer_active_from_env()`
- Produces: `ComponentCard._apply_active(version: str) -> bool`（Task 7/8/9 依赖）、`ComponentCard.active_version() -> Optional[str]`

- [ ] **Step 1: 追加失败测试**

```python
class ConfigureUsesSelectedVersion(EnvSandbox):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card(self, key="jdk", versions=("21.0.4", "17.0.12", "8")):
        comp = self.make_component(key, *versions)
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        return card

    def test_apply_active_sets_home_to_selected_version(self):
        self.as_windows()
        card = self._card()
        self.assertTrue(card._apply_active("17.0.12"))
        self.assertEqual(self.win_env["JAVA_HOME"],
                         str(card.component.install_dir("17.0.12")))
        self.assertEqual(main.load_active_map()["jdk"], "17.0.12")
        self.assertEqual(card.active_version(), "17.0.12")

    def test_configure_click_targets_combo_selection_not_lexicographic_last(self):
        # 旧实现在这里会选中 jdk-8（字典序最后一个）
        self.as_windows()
        card = self._card()
        card.version_combo.setCurrentIndex(card.version_combo.findText("21.0.4"))
        card.on_configure_clicked()
        self.assertEqual(self.win_env["JAVA_HOME"],
                         str(card.component.install_dir("21.0.4")))

    def test_apply_active_failure_leaves_active_untouched(self):
        self.as_windows()
        card = self._card()
        orig = main.EnvManager.append_windows_path
        main.EnvManager.append_windows_path = staticmethod(
            lambda entry: (_ for _ in ()).throw(OSError("boom")))
        self.addCleanup(setattr, main.EnvManager, "append_windows_path", orig)
        self.assertFalse(card._apply_active("17.0.12"))
        self.assertNotIn("jdk", main.load_active_map())

    def test_non_multi_version_component_still_configures(self):
        self.as_windows()
        comp = self.make_component("tomcat", "10.1.60")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        card.on_configure_clicked()
        self.assertEqual(self.win_env["CATALINA_HOME"],
                         str(comp.install_dir("10.1.60")))
        self.assertNotIn("tomcat", main.load_active_map(),
                         "非多版本组件不进 active 表")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: FAIL —`AttributeError: 'ComponentCard' object has no attribute '_apply_active'`

- [ ] **Step 3: 实现卡片侧入口**

`ComponentCard` 内新增（放在 `on_configure_clicked` 之前）：

```python
    # ------------------------------------------------------------------
    def active_version(self) -> Optional[str]:
        """当前生效版本：优先读 active 登记表，其次从持久层环境变量反推。"""
        if not self.component.multi_version:
            return None
        return load_active_map().get(self.component.key) or infer_active_from_env(self.component)

    # ------------------------------------------------------------------
    def _apply_active(self, version: str) -> bool:
        """把指定版本设为生效版本；成功后写登记表并刷新界面。

        返回: bool  成功与否。失败原因已在日志里，界面不再处理异常。

        注意: 本任务先不调用 _refresh_installed_marks()（它是 Task 7 才引入的方法），
              那里会补上这一次刷新，避免任务之间出现前向依赖。
        """
        try:
            steps = apply_active_version(self.component, version)
        except SwitchError as exc:
            self._log("error", str(exc))
            return False
        for step in steps:
            self._log("error" if ("失败" in step) else "ok", step)
        save_active_version(self.component.key, version)
        self._detect_status()
        return True
```

- [ ] **Step 4: 改写 `on_configure_clicked`（去掉字典序那段）**

```python
    def on_configure_clicked(self) -> None:
        """仅配置环境变量。

        多版本组件：把下拉框选中的版本设为"当前生效版本"（PATH 只留它一条）。
        其他组件：沿用原有"取已装目录里语义版本最高的一个"的行为，不写 active 表。
        """
        install_root = CONFIG_DIR / self.component.key
        if not install_root.exists():
            self._log("warn", "尚未下载，请先执行“下载并安装”。")
            return
        ordered = installed_versions(self.component)
        if self.component.multi_version:
            if not ordered:
                self._log("warn", (f"未找到符合 {self.component.key}-<版本号> 命名的安装目录；"
                                   f"可用『清理残留 PATH』自愈后重试"))
                return
            chosen = self._current_version().version
            if chosen not in [v for v, _p in ordered]:
                self._log("warn", (f"下拉框选的是 {chosen}，磁盘上没有对应目录；"
                                   f"已装：{'、'.join(v for v, _p in ordered)}"))
                return
            self._apply_active(chosen)
            return
        if not ordered:
            self._log("warn", "未找到已解压的安装目录。")
            return
        self._configure_env(ordered[0][1])
        self._detect_status()
```

> 说明：非多版本分支也改用 `installed_versions()[0]`（语义版本最高），因此 `_configure_env` 的调用点只剩这一处，字典序取最后一个的老逻辑被彻底替换；`_configure_env` 本体保持不动，继续给非多版本组件使用。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS

- [ ] **Step 6: 交给用户提交**

```bash
cd /e/file/test/byte-tools
git add main.py bt_multiversion_tests.py
git commit -m "fix: 配置环境变量按下拉框选中版本生效，修掉目录名字典序挑错版本"
```

---

## Task 7: 下拉框「已安装」绿勾（只加图标，不动条目文本）

**Files:**
- Modify: `main.py`（`ComponentCard._reload_combo_items` `main.py:4179`；新增 `_installed_icon()` 与 `_refresh_installed_marks()`）
- Test: `bt_multiversion_tests.py`

**Interfaces:**
- Consumes: `installed_versions()`、`Component.multi_version`
- Produces: `_installed_icon(color: str = "#2e7d32", size: int = 16) -> QIcon`（模块级）、`ComponentCard._refresh_installed_marks() -> None`

- [ ] **Step 1: 确认不需要新增 Qt 导入**

Run: `cd /e/file/test/byte-tools && grep -n "QColor\|QPainter\|QPen\|QPixmap\|QIcon" main.py | head -3`
Expected: 五个符号都已在 `main.py` 顶部 `from PySide6.QtGui import (...)` 里（已核实：`QColor`/`QIcon`/`QPainter`/`QPen`/`QPixmap` 均已导入）。画法沿用仓库既有的 `_make_search_icon` 风格（`QPixmap(size*2)` + `setDevicePixelRatio(2.0)` + `drawLine`），**不要用 QPolygon/QPoint**（未导入）。

- [ ] **Step 2: 追加失败测试**

（先在 `bt_multiversion_tests.py` 文件头补一行 `from PySide6.QtCore import Qt` —— 断言里要用 `Qt.DecorationRole`。）

```python
class InstalledCheckIcon(EnvSandbox):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _jdk_card(self):
        comp = self.make_component("jdk", "21.0.4", "17.0.12")
        return main.ComponentCard(comp, lambda lvl, msg: None)

    def test_installed_items_get_icon_and_text_is_untouched(self):
        card = self._jdk_card()
        before = [card.version_combo.itemText(i) for i in range(card.version_combo.count())]
        card._refresh_installed_marks()
        after = [card.version_combo.itemText(i) for i in range(card.version_combo.count())]
        self.assertEqual(after, before,
                         "条目文本必须逐字不变：_current_version() 按文本反查版本对象")
        for i, label in enumerate(before):
            data = card.version_combo.itemData(i, Qt.DecorationRole)
            if label in ("21.0.4", "17.0.12"):
                self.assertIsNotNone(data)
                self.assertFalse(data.isNull(), label)
            else:
                self.assertTrue(data is None or data.isNull(), label)

    def test_non_multi_version_component_gets_no_icons(self):
        comp = self.make_component("mysql", "8.4.0")
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        card._refresh_installed_marks()
        for i in range(card.version_combo.count()):
            data = card.version_combo.itemData(i, Qt.DecorationRole)
            self.assertTrue(data is None or data.isNull())

    def test_marks_refresh_after_reloading_versions(self):
        # 抓取线程回填版本列表会重建条目，勾必须跟着重建
        card = self._jdk_card()
        card._refresh_installed_marks()
        fresh = [cv for cv in card.component.versions if cv.version in ("21.0.4", "17.0.12")]
        card.set_versions(fresh)
        idx = card.version_combo.findText("21.0.4")
        self.assertFalse(card.version_combo.itemData(idx, Qt.DecorationRole).isNull())

    def test_uninstalled_version_loses_its_mark(self):
        card = self._jdk_card()
        card._refresh_installed_marks()
        shutil.rmtree(card.component.install_dir("17.0.12"))   # 沙箱内的临时目录
        card._refresh_installed_marks()
        idx = card.version_combo.findText("17.0.12")
        data = card.version_combo.itemData(idx, Qt.DecorationRole)
        self.assertTrue(data is None or data.isNull())
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: FAIL —`AttributeError: 'ComponentCard' object has no attribute '_refresh_installed_marks'`

- [ ] **Step 4: 实现图标与刷新**

模块级（放在 `class ComponentCard` 之前）：

```python
def _installed_icon(color: str = "#2e7d32", size: int = 16) -> QIcon:
    """现画一个绿色对勾，作为下拉框里"这个版本磁盘上已装"的标记。

    入参 color: str  线色，默认与状态胶囊的成功绿同系
          size:  int 逻辑边长（像素），按 2 倍分辨率绘制以免高分屏发虚
    返回: QIcon

    说明: 刻意用图标而不是在文本里加「✓」——下拉框的显示文本是版本反查的唯一键
          （_current_version / repopulate(preferred=…)），改文本会连锁打错选版、
          安装、卸载与配置保存。画法与 MainWindow._make_search_icon 保持一致。
    """
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(3, 9, 6, 12)      # 短撇
    painter.drawLine(6, 12, 13, 4)     # 长挑
    painter.end()
    return QIcon(pm)
```

`ComponentCard` 内新增：

```python
    # ------------------------------------------------------------------
    def _refresh_installed_marks(self) -> None:
        """给磁盘上已装的版本挂绿勾；只动 DecorationRole，不碰条目文本。"""
        if not self.component.multi_version:
            return
        installed = {v for v, _p in installed_versions(self.component)}
        icon = _installed_icon()
        empty = QIcon()
        for i, cv in enumerate(self.component.versions):
            self.version_combo.setItemData(i, icon if cv.version in installed else empty,
                                           Qt.DecorationRole)
```

- [ ] **Step 5: 在装载条目的出口处挂上刷新**

`_reload_combo_items()`（`main.py:4179`）两条返回路径各补一次调用：

```python
    def _reload_combo_items(self, preferred: Optional[str] = None) -> None:
        """把 self.component.versions 灌进下拉框，并重挂"已装"图标。"""
        labels = [self._display_label(v) for v in self.component.versions]
        if self.version_combo.count() == 0:
            self.version_combo.blockSignals(True)
            self.version_combo.addItems(labels)
            self.version_combo.setCurrentIndex(0)
            self.version_combo.blockSignals(False)
            self.version_combo._committed_text = self.version_combo.currentText()
            self._refresh_installed_marks()          # 新增
            return
        self.version_combo.repopulate(labels, preferred=preferred)
        self._refresh_installed_marks()              # 新增：条目重建后旧图标已失效
```

并在安装成功收尾（下载 worker 完成、日志"安装完成"之后）与卸载成功收尾（`_detect_status()` 之前）各加一行 `self._refresh_installed_marks()`。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS

---

## Task 8: 状态胶囊、按钮启用条件与日志

**Files:**
- Modify: `main.py`（`_detect_status` `main.py:4114-4173`、`_render_status_label` `main.py:4075`、按钮 tooltip 设置处）
- Test: `bt_multiversion_tests.py`

**Interfaces:**
- Consumes: `installed_versions()`、`active_version()`、`Component.multi_version`
- Produces: 多版本组件的状态胶囊文案格式 `● 已装 {n} 个版本 · 生效 {ver}｜{已装清单}`；未生效时 `· 均未生效`

- [ ] **Step 1: 追加失败测试**

```python
class StatusCapsuleForMultiVersion(EnvSandbox):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card(self, active=None):
        comp = self.make_component("jdk", "21.0.4", "17.0.12")
        self.as_windows()
        if active:
            main.save_active_version("jdk", active)
        self.enable_detect()          # 胶囊用例要真实探测；探测线程已被 enable_detect 换成记录调用
        return main.ComponentCard(comp, lambda lvl, msg: None)

    def test_two_installed_one_active(self):
        card = self._card(active="21.0.4")
        text = card.status_label.text()
        self.assertIn("已装 2 个版本", text)
        self.assertIn("生效 21.0.4", text)
        self.assertIn("17.0.12", text)

    def test_installed_but_none_active_says_so(self):
        card = self._card(active=None)
        self.assertIn("均未生效", card.status_label.text())

    def test_configure_button_disabled_when_selection_is_already_active(self):
        card = self._card(active="21.0.4")
        card.version_combo.setCurrentIndex(card.version_combo.findText("21.0.4"))
        card._detect_status()
        self.assertFalse(card.btn_configure.isEnabled())

    def test_configure_button_enabled_for_the_other_version(self):
        card = self._card(active="21.0.4")
        card.version_combo.setCurrentIndex(card.version_combo.findText("17.0.12"))
        card._detect_status()
        self.assertTrue(card.btn_configure.isEnabled())
        self.assertIn("生效", card.btn_configure.toolTip())

    def test_non_multi_version_capsule_text_unchanged(self):
        # 回归护栏：非多版本组件的胶囊必须还是老文案，不能被新逻辑污染
        comp = self.make_component("tomcat", "10.1.60")
        self.as_windows()
        self.win_env["CATALINA_HOME"] = str(comp.install_dir("10.1.60"))
        self.enable_detect()
        card = main.ComponentCard(comp, lambda lvl, msg: None)
        self.assertNotIn("已装", card.status_label.text())
        self.assertTrue(card.status_label.text())     # 而不是空字符串

    def test_only_the_active_version_is_probed(self):
        card = self._card(active="21.0.4")
        self.assertEqual(len(self.probe_calls), 1, self.probe_calls)
        self.assertIn("jdk-21.0.4", self.probe_calls[0])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: FAIL（`已装 2 个版本` 断言不成立；`probe_calls` 为空）

- [ ] **Step 3: 在 `_detect_status` 函数体最前面插入多版本分支**

（位置：紧接 `def _detect_status(self) -> None:` 的 docstring 之后、`result = self.component.detect(probe_version=False)` 之前，让多版本组件完全走新分支，不干扰其余组件的原有判定。）

```python
        # 多版本组件：状态胶囊要表达的是"装了哪几个 + 哪个生效"，
        # 而不是单一的"已配置/未配置"；生效以 active 登记表为准，探测只用于回填版本号。
        if self.component.multi_version:
            ordered = installed_versions(self.component)
            active = self.active_version()
            if not ordered:
                self.status_label.setText("○ 未安装")
                self.status_label.setStyleSheet(
                    "color:#c62828;font-weight:600;padding:2px 8px;"
                    "background:#ffebee;border-radius:10px;")
                self.btn_configure.setEnabled(True)
                self.btn_configure.setToolTip("将已下载的版本写入 XXX_HOME 与 PATH")
                self.btn_uninstall.setEnabled(False)
                self.btn_uninstall.setToolTip("当前组件未安装，无需卸载")
                self._refresh_installed_marks()
                return
            names = "、".join(v for v, _p in ordered)
            tail = f" · 生效 {active}" if active else " · 均未生效"
            self.status_label.setText(f"● 已装 {len(ordered)} 个版本{tail}（{names}）")
            self.status_label.setStyleSheet(
                "color:#2e7d32;font-weight:600;padding:2px 8px;"
                "background:#e8f5e9;border-radius:10px;" if active else
                "color:#ef6c00;font-weight:600;padding:2px 8px;"
                "background:#fff3e0;border-radius:10px;")
            selected = self._current_version().version
            self.btn_configure.setEnabled(selected != active)
            self.btn_configure.setToolTip(
                "把下拉框选中的版本设为生效版本：改 XXX_HOME，并把本组件在 PATH 里的"
                "条目收敛成这一条；已开着的终端需重开才生效" if selected != active else
                f"选中的 {selected} 已是生效版本；要换版本先在下拉框里选中")
            self.btn_uninstall.setEnabled(True)
            self.btn_uninstall.setToolTip(
                f"卸载下拉框选中的 {selected}：只删该版本目录与它的 PATH 条目，"
                "其他已装版本不动")
            for ver, path in ordered:
                if ver == active:
                    # 复用既有寻径（会试 bin/、根目录、.bat/.cmd 等），别自己拼路径
                    exe = self.component.exec_path_in_home(str(path))
                    if exe:
                        self._schedule_version_probe(str(exe))
                    break
            self._refresh_installed_marks()
            return
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS

- [ ] **Step 5: 人工验收（只有用户能做：助手不碰真注册表）**

```bash
cd /e/file/test/byte-tools && .venv/Scripts/python.exe main.py
```

逐项确认：
1. JDK 卡片装 21 → 下拉框该版本出现绿勾，胶囊显示「已装 1 个版本 · 生效 …」；
2. 再装 17 → 两个都有勾；选中 17 后「仅配置环境变量」可点；
3. 点它 → 日志逐条列出 `已设置 JAVA_HOME=…`、`PATH 已收敛为生效版本这一条…`、以及"已开终端需重开"那句；
4. **新开** cmd 里跑三条自检，都应指向 17：
   ```bat
   java -version
   echo %JAVA_HOME%
   where java
   ```
   若 `where java` 第一行是 `C:\Program Files\Common Files\Oracle\Java\javapath\java.exe`，属已知的 Windows 遮蔽（不是本工具写错），按日志末行说明处理；
5. 切回 21，重复第 4 步；
6. 卸载 17 → 勾消失、21 仍生效、`HKCU\Environment\Path` 里只剩 21 那条。

---

## Task 9: 卸载只清被删版本，删掉生效版本时自动重排

**Files:**
- Modify: `main.py:289-317`（`resolve_uninstall_target`）、`main.py:319-388`（`uninstall`）
- Test: `bt_multiversion_tests.py`

**Interfaces:**
- Consumes: `installed_versions()`、`version_from_install_dir()`、`apply_active_version()`、`load_active_map()`、`save_active_version()`、`EnvManager.remove_path_entries_under()`
- Produces: 卸载后的 active 一致性保证；`resolve_uninstall_target` 不再因"装了多个版本"直接罢工

- [ ] **Step 1: 追加失败测试**

```python
class UninstallScope(EnvSandbox):
    def setUp(self):
        super().setUp()
        self.as_windows()
        self.comp = self.make_component("jdk", "21.0.4", "17.0.12")
        self.win_path[:] = [str(self.comp.install_dir("21.0.4") / "bin"),
                            str(self.comp.install_dir("17.0.12") / "bin")]
        self.win_env["JAVA_HOME"] = str(self.comp.install_dir("21.0.4"))
        main.save_active_version("jdk", "21.0.4")

    def test_uninstall_keeps_other_versions_path_entry(self):
        # 现状 bug：PATH 清理按组件根，删 17 会把 21 的条目一起删掉
        self.comp.uninstall("17.0.12")
        self.assertIn(str(self.comp.install_dir("21.0.4") / "bin"), self.win_path)
        self.assertNotIn(str(self.comp.install_dir("17.0.12") / "bin"), self.win_path)

    def test_uninstall_other_version_keeps_active_home(self):
        self.comp.uninstall("17.0.12")
        self.assertEqual(self.win_env["JAVA_HOME"], str(self.comp.install_dir("21.0.4")))
        self.assertEqual(main.load_active_map()["jdk"], "21.0.4")

    def test_uninstalling_active_version_repoints_to_highest_remaining(self):
        summary = self.comp.uninstall("21.0.4")
        self.assertEqual(main.load_active_map()["jdk"], "17.0.12")
        self.assertEqual(self.win_env["JAVA_HOME"], str(self.comp.install_dir("17.0.12")))
        self.assertIn("生效版本已自动切到 17.0.12", summary)

    def test_uninstalling_last_version_clears_active_and_env(self):
        self.comp.uninstall("21.0.4")
        self.comp.uninstall("17.0.12")
        self.assertNotIn("jdk", main.load_active_map())
        self.assertNotIn("JAVA_HOME", self.win_env)
        self.assertEqual([p for p in self.win_path if "jdk-" in p.lower()], [])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: FAIL（第一条最明显：删 17 之后 entries 里连 21 也没了）

- [ ] **Step 3: 卸载目标定位优先按选中版本**

`resolve_uninstall_target`（`main.py:289`）里，把"多版本罢工"那段改成"先精确命中选中版本"：

```python
        # 下拉框选中的版本在磁盘上有对应目录时，必须卸它 —— 多版本并存不算歧义。
        exact = self.install_dir(version)
        if exact.is_dir():
            return exact, ""
        dirs = self.installed_dirs()
        if len(dirs) == 1:
            return dirs[0], (f"所选版本 {self.key}-{version} 未安装，"
                             f"改为卸载实际存在的 {dirs[0].name}")
        if len(dirs) > 1:
            # 选中的版本没装、又装了多个：不能猜。按语义版本降序取最高的那个并说清楚。
            ordered = installed_versions(self)
            if ordered:
                ver, path = ordered[0]
                return path, (f"所选版本 {self.key}-{version} 未安装；"
                              f"已装 {'、'.join(v for v, _p in ordered)}，"
                              f"改为卸载版本最高的 {ver}")
            names = "、".join(d.name for d in dirs)
            return None, f"存在多个已安装版本（{names}）但都无法识别版本号，请在下拉框中选择"
        return None, f"未找到 {self.key}-{version} 的安装目录，也没有其他已安装版本"
```

- [ ] **Step 4: PATH 清理范围从"组件根"收窄到"被删目录"**

`Component.uninstall` 第 3 步（`main.py:377-388`）替换为：

```python
        # 3. 清理 PATH 中属于"本次被删版本"的条目
        #    不能按组件根清理：多版本并存时会把用户没删的那些版本的条目一起删掉
        scope = str(install_path) if install_path is not None else str(component_root)
        try:
            removed = EnvManager.remove_path_entries_under(scope)
            if removed:
                summary_parts.append("已从 PATH 移除：" + "、".join(removed))
            else:
                summary_parts.append("PATH 中没有本版本的条目")
        except Exception as exc:
            summary_parts.append(f"清理 PATH 失败：{exc}")
```

同一步里第 2 段（删 `XXX_HOME`）的判断保持"仅当它落在本组件目录内"不变，但把触发条件收紧成"指向的正是本次被删目录"，其余情形留到第 5 步的自动重排里处理：

```python
        # 2. 删除 XXX_HOME：只有它正指向本次被删的版本才删；指向同组件其他版本时保留，
        #    交给第 4 步的生效重排处理，避免"删了 17，把 21 的 JAVA_HOME 也清了"
        if self.env_var:
            current_home = EnvManager.read_user_env(self.env_var) or EnvManager.get(self.env_var)
            if current_home and install_path is not None and EnvManager._same_path(
                    current_home, str(install_path)):
                try:
                    EnvManager.drop_user_env(self.env_var)
                    summary_parts.append(f"已删除环境变量：{self.env_var}")
                except Exception as exc:
                    summary_parts.append(f"删除环境变量 {self.env_var} 失败：{exc}")
            elif current_home and not EnvManager._under_root(
                    str(current_home), str(component_root)):
                summary_parts.append(
                    f"环境变量 {self.env_var} 指向其他目录（{current_home}），未删除")
```

- [ ] **Step 5: 生效版本重排（卸载收尾）**

在 `uninstall` 返回 summary 之前追加：

```python
        # 4. 多版本组件的生效登记收尾：删掉的正是生效版本时，自动切到剩余里版本号最高的；
        #    全删光就清登记 + 清环境变量，避免界面显示"生效 17"而磁盘上已无 17。
        if self.multi_version:
            remaining = installed_versions(self)
            removed_ver = version_from_install_dir(self, install_path) if install_path else None
            active = load_active_map().get(self.key) or infer_active_from_env(self)
            if not remaining:
                save_active_version(self.key, None)
                if self.env_var and EnvManager.read_user_env(self.env_var):
                    try:
                        EnvManager.drop_user_env(self.env_var)
                    except Exception as exc:
                        summary_parts.append(f"删除 {self.env_var} 失败：{exc}")
                summary_parts.append("已无安装版本，生效登记与环境变量均已清除")
            elif active and removed_ver and active == removed_ver:
                nxt = remaining[0][0]
                try:
                    apply_active_version(self, nxt)
                    save_active_version(self.key, nxt)
                    summary_parts.append(f"生效版本已自动切到 {nxt}")
                except SwitchError as exc:
                    save_active_version(self.key, None)
                    summary_parts.append(
                        f"自动切到 {nxt} 失败，生效登记已清空，请重新点一次"
                        f"「仅配置环境变量」：{exc}")
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd /e/file/test/byte-tools && .venv/Scripts/python.exe -u bt_multiversion_tests.py`
Expected: PASS

- [ ] **Step 7: 全量回归**

```bash
cd /e/file/test/byte-tools
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_multiversion_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_component_category_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_search_and_newcmp_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_mirror_spec_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_refresh_versions_tests.py
.venv/Scripts/python.exe -m py_compile main.py bt_multiversion_tests.py
```
Expected: 全部 `OK`；`py_compile` 无输出

- [ ] **Step 8: 交给用户提交**

```bash
cd /e/file/test/byte-tools
git add main.py bt_multiversion_tests.py
git commit -m "fix: 卸载只清被删版本的 PATH 条目，删掉生效版本时自动切到剩余最高版本"
```

---

## Task 10: 文档与 DEVELOPMENT.md 新增规则 R3

**Files:**
- Modify: `DEVELOPMENT.md`（R2.5 之后、"后续规则占位"之前新增 R3）
- Modify: `README.md` / `README_EN.md` / `CODE_WIKI.md`
- Test: 无新增代码

**Interfaces:**
- Consumes: Task 1~9 的实际实现
- Produces: 无代码接口

- [ ] **Step 1: DEVELOPMENT.md 写 R3，必须含这 6 条**

```markdown
## 规则 R3：组件多版本与生效版本切换

### R3.1 适用范围
允许并存多版本并切换生效版本的组件只有 7 个：jdk / python / node / go / maven / gradle / bun
（真源：main.py 的 MULTI_VERSION_KEYS）。判据是"归档解压安装 + 靠 XXX_HOME/PATH 生效"。
conda 是 installer_mode，装在固定目录；mysql/tomcat/nacos/es 等服务型组件的真矛盾在端口与
数据目录，两者都不进本模型。

### R3.2 两个字段，不许混用
- selections（config.json）：下拉框当前选中，语义是"我想装/我想操作哪个版本"。
- active（config.json）：当前生效版本，语义是"系统的 XXX_HOME 与 PATH 指向哪个"。
写 config.json 一律合并写：_save_settings 只改 selections，save_active_version 只改 active。

### R3.3 切换是原子操作（硬约束）
唯一入口 apply_active_version()：写 XXX_HOME → 把本组件在 PATH 里的条目收敛成生效版本一条
→ 同步当前进程并广播。任一步失败按持久层快照整体回滚，回滚依据必须是注册表/shell rc 的真值，
不是 os.environ（本工具会把它改脏）。禁止留下「JAVA_HOME 指 A、PATH 指 B」的中间态。

### R3.4 下拉框显示文本不可改动
已装/生效状态一律用 Qt.DecorationRole 图标表达。_current_version() 与
SearchableComboBox.repopulate(preferred=…) 都按显示文本反查版本对象，往文本里加符号会
连锁打错选版、安装、卸载与配置保存。

### R3.5 版本目录命名是唯一契约
安装目录必须叫 <key>-<version>（Component.install_dir）。version_from_install_dir() 与
installed_versions() 依赖该约定；排序必须走 _sort_semver_desc，字典序会把 jdk-8 排在 jdk-21
之后（2026-09-29 之前的「仅配置环境变量」正是踩了这个坑）。

### R3.6 非目标
不做 cd 自动切换的 shell 钩子，不写用户项目的 pom/gradle/IDE 配置，不生成 toolchains.xml。
```

- [ ] **Step 2: R3 末尾加"新增组件如何登记多版本"清单**

```markdown
### R3.7 新增/调整多版本组件 checklist
- [ ] 只改 main.py 的 MULTI_VERSION_KEYS 一处
- [ ] 同步 bt_multiversion_tests.py 的 EXPECTED_MULTI_VERSION
- [ ] 确认该组件不是 installer_mode、不是服务型组件
- [ ] 跑：QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_multiversion_tests.py
```

- [ ] **Step 3: README.md 用户可见变化**

在组件下拉框/安装说明处补三点：下拉框绿色对勾 = 磁盘已装；同一组件可装多个版本，「仅配置环境变量」= 把选中版本设为生效；两条 Windows 注意（已开终端与 IDE 不刷新；`where java` 可能先命中 `C:\Program Files\Common Files\Oracle\Java\javapath`，附自检命令）。另在卸载说明处明确：只删选中版本的目录与它的 PATH 条目，其他已装版本不动。

- [ ] **Step 4: README_EN.md 同步英文版**

内容与 Step 3 一致（英文），沿用该文件现有的行文风格。

- [ ] **Step 5: CODE_WIKI.md**

登记 `bt_multiversion_tests.py` 的覆盖面（能力位 / 版本目录解析 / 门面 / 切换与回滚 / active 读写 / 图标 / 状态胶囊 / 卸载范围）；在 `Component` 字段表加 `multi_version`；在环境层小节列出 `EnvManager` 7 个门面方法与 `apply_active_version` 的时序与回滚语义；把 `main.py` 行数与「26 个组件」等既有数字复核一遍。

- [ ] **Step 6: 行尾复核**

```bash
cd /e/file/test/byte-tools && .venv/Scripts/python.exe -c "
import pathlib
for f in ['main.py','DEVELOPMENT.md','README.md','README_EN.md','CODE_WIKI.md','bt_multiversion_tests.py']:
    b = pathlib.Path(f).read_bytes()
    print(f'{f:34s} bytes={len(b):7d} CR={b.count(bytes([13]))}')
"
```
Expected: 每个文件 `CR=0`。**判行尾只能用这种方式**（Git Bash 的 grep/awk 在这个仓库会假报"全是 CRLF"）。

- [ ] **Step 7: 交给用户提交**

```bash
cd /e/file/test/byte-tools
git add DEVELOPMENT.md README.md README_EN.md CODE_WIKI.md docs/superpowers/plans/2026-09-29-multi-version-switch.md
git commit -m "docs: 新增规则 R3 组件多版本与生效版本切换，同步 README/CODE_WIKI 与本计划文档"
git push origin master
```

---

## 完成定义（Definition of Done）

1. `bt_multiversion_tests.py` 全部用例通过，且 5 个既有测试文件（分类 / 搜索新组件 / 镜像规范 / 刷新版本 / 本文件）一起通过。
2. `main.py` 编译通过、`CR=0`；下拉框条目文本与改造前逐字一致（Task 7 的断言即护栏）。
3. 多版本白名单只在 `MULTI_VERSION_KEYS` 一处定义（Task 1 断言 = `EXPECTED_MULTI_VERSION`）。
4. 切换失败不留中间态：Task 4 的回滚用例 + Task 6 的失败用例 + Task 9 的自动重排用例都绿。
5. 非多版本组件的原有行为与文案未被改动（Task 8 的 `test_non_multi_version_capsule_text_unchanged`）。
6. 用户完成 Task 8 Step 5 的 Windows 真机验收清单（6 项）。

---

## 执行期对计划的修正（2026-09-29，落地位于 HEAD `6c0ec43`）

> 本节如实记录实现过程中偏离上文计划草案的地方。**上文各 Task 的原文照留、不作回改**——它们保留了当初的设计意图，
> 下面的偏差条目才是"已经落地的真相"。凡与本节冲突，以本节 + 代码为准。

### 1. 测试夹具的版本串 `21.0.4 / 17.0.12` 不在 jdk 离线清单里
Task 0 / 2 / 3 / 4 / 5 / 6 / 7 / 8 / 9 的夹具大量用 `make_component("jdk", "21.0.4", "17.0.12")`，
而 `build_components()` 里 jdk 的离线 catalog 是 `21 / 17 / 11 / 8`（`main.py:2960`）——**这两个精确小版本串从来不是可选项**。
- 影响面：夹具本身是合法的——多版本模型只认 `<key>-<version>` 目录名，`make_component` 直接按传入串造目录，不查 catalog，
  所以测试仍成立（落地后测试文件里仍保留 21.0.4/17.0.12 作为合成版本串）。
- 真正需要纠正的是**面向用户的示例**：状态胶囊示例文案要用 catalog 里真实存在的主版本号 `生效 21（21、17）`，
  不能拿 21.0.4 当"下拉框里可点的版本"。README / DEVELOPMENT.md 的胶囊例子据此改写为 `21 / 17`；
  卸载摘要的例子保留 21.0.4/17.0.12（那里展示的是"卸载某精确版本"的日志措辞，不是下拉选项）。

### 2. 状态胶囊清单分隔符：计划写 `｜`，代码用中文顿号 `、`
Task 8 原文（`Produces` 一节）把多版本胶囊写成 `● 已装 {n} 个版本 · 生效 {ver}｜{已装清单}`。
落地实现（`main.py:4639`）用的是 `、`：实际产出 `● 已装 2 个版本 · 生效 21（21、17）`。文档一律以 `、` 为准。

### 3. PATH 清理范围：从"一律收窄"细化为"有兄弟版本才收窄，全删光回到按根清扫"
计划与全局约束只说了"只清理本组件目录内的 PATH 条目"。实现（`Component.uninstall` 第 ③ 步，`main.py:420-435`）进一步分叉：
- 磁盘上**还有同组件其它安装目录**时，scope 收窄到**本次被删的那个目录**，绝不按组件根扫（否则会把用户没删的其它版本条目一起删掉）；
- 本组件**已无任何其它安装目录**时，scope 回到组件根 `CONFIG_DIR/<key>` 整体清扫，从而保住"早年手工删目录留下的死条目也能清掉"的自愈能力。
一句话进 R3：**删一个版本不得影响同组件其它版本的目录、HOME 与 PATH 条目。**

### 4. 卸载要快照 `active_before`（计划完全没有这一步）
评审实测复现出一个真 bug：本期上线前装好的组件，`config.json` 里没有 `active` 条目，生效版本靠 `infer_active_from_env()`
从 `XXX_HOME` 反推；而卸载第 ② 步可能正好把那个 HOME 删掉，事后再读永远是 `None`，"删掉生效版本后自动重排"会**静默失效**。
修复：`Component.uninstall` 在**任何破坏性动作之前**先算好 `active_before = load_active_map().get(key) or infer_active_from_env(self)`
（`main.py:375`，仅多版本才算），第 ④ 步只认这份快照。这是第 2 轮修复才补上的，计划里未预见。

### 5. 措辞分叉：「自动切到」 vs 「按生效版本重建」
计划只给了"自动切到剩余最高版本"一种说法。实现（`main.py:491-499`）按语义分成两种：
- 删掉的**正是生效版本** → `生效版本已自动切到 {target}`（确实发生了切换）；
- 生效版本**还活着**、只是环境变量被这次卸载带偏 → `已按生效版本 {target} 重建环境变量与 PATH`（本就在生效，说"切到"是假话）。
失败分支同样分叉。另：`python` 这类 `env_var=None` 的组件没有 HOME 可带偏，第 ④ 步对它不写任何东西（`test_n2b_python_without_env_var_is_untouched`）。

### 6. `resolve_uninstall_target` 为多版本组件放宽了"罢工"
计划沿用旧语义：选了没装、磁盘又装着多个 → 罢工"请先在下拉框中选择具体版本"。实现（`main.py:293-338`）按 `multi_version` 分叉：
- 多版本组件：改为按语义版本降序卸最高的，并说明"已装 …，改为卸载版本最高的 X"（罢工等于卸载失灵）；
- 非多版本组件：**维持罢工原文**（R3.9 零影响，护栏 `test_non_multi_version_with_two_dirs_still_refuses`）。

### 7. R3 规则：计划骨架 6 条（R3.1–R3.6）+ checklist（R3.7）扩到 9 条
评审过程中新增两条约束，DEVELOPMENT.md R3 已落地：
- **R3.8 测试沙箱是唯一接缝**：多版本测试一律走 `EnvSandbox`，产品代码不得为测试加开关；断言只看落盘结果，**不得断言桩调用次数**；
  测试文件必须先 stub WMI 再 `import main`，碰 Qt 的加 `QT_QPA_PLATFORM=offscreen`。
- **R3.9 非多版本组件零影响**：任何多版本分支都必须用 `component.multi_version` 门控，非多版本组件的状态文案 / 按钮 / 卸载结果必须与改造前逐字一致。

### 8. 计划正文里的 `main.py:NNNN` 行号已整体漂移
上文「文件结构」表与各处引用是写计划时对着旧版 `main.py`（约 4800 行）标的，本期落地后 `main.py` 增长到
**6149 行 / 274759 字节**（HEAD `6c0ec43` 实测）。典型漂移：`_current_version()` 计划写 `4208`、实际 `4792`；
combo 装载计划写 `4176-4215`、实际 `_reload_combo_items` 在 `4759`；状态胶囊计划写 `4075-4173`、实际 `_detect_status` 在 `4610`；
`_save_settings` 计划写 `5421-5446`、实际 `6079`；`build_components()` 末尾计划写 `2716+`、实际赋值在 `3409`。
**不要拿计划里的行号当免检结论**——检索以函数名为准。

### 9. 环境层门面方法数量：计划说 7 个，实际 8 个
计划 Task 3 / Task 10 Step 5 都说"`EnvManager` 上 7 个平台无关门面方法"。落地实现是 **8 个** public 门面方法
（`main.py:3857-3958`）：`write_user_env` / `drop_user_env` / `read_user_env` / `add_path_entry` / `drop_path_entry` /
`remove_path_entries_under` / `read_user_path_entries` / `restore_path_entries`（另有两处只给测试打桩用的私有读写接缝
`_read_windows_user_env` / `_delete_windows_user_env`，不计入门面）。CODE_WIKI.md 4.6 已按 8 个登记。

### 10. 用例数量：随每轮修复增长，以运行输出为准
计划 Task 10 Step 5 与文档里出现的"84 个用例"是 HEAD `6c0ec43` 上的一次实测（`Ran 84 tests / OK`），并非固定值：
Task 9 的三轮修复各追加了用例，且 `bt_multiversion_tests.py` 仍在并发演进。文档一律改为描述覆盖面、不钉死数字。
