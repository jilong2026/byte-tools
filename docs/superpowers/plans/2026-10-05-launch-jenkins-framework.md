# 组件一键启动 · 计划一（框架 + Jenkins）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 byte-tools 加一层"一键启动 / 停止 / 状态 / 打开控制台"能力，本期只覆盖 `jenkins` 一个组件，但把 `LaunchSpec` + `ServiceManager` + `running.json` 这套框架建成立、可扩到后续组件。

**Architecture:** 三层。① 数据层：新增 `LaunchSpec` dataclass，`Component.launch` 字段，由 `LAUNCH_OF` 这张登记表在 `build_components()` 末尾统一赋值（沿用 `MULTI_VERSION_KEYS` 的先例，构造处不手写）。② 生命周期层：`ServiceManager` + 若干**不依赖 Qt、可注入探针**的纯函数（端口簇选择、探活、僵尸判定、启动计划组装），运行事实落在 `~/.env-tools/running.json`。③ UI 层：`LaunchWorker(QThread)` 只做粘合，`ComponentCard` 多一排按钮与状态文本。

核心取舍（spec §4）：**端口是真相，PID 只是提示** —— 登记结构里显式记 `pid_role`，判"运行中"必须"端口在听"成立。

**Tech Stack:** Python 3.10–3.14 + PySide6（Qt 6）；测试用标准库 `unittest`（仓库无 pytest / 无 pyyaml / 无 gh CLI）；配置为 JSON 文件；命令一律 `.venv/Scripts/python.exe`。

**Spec:** `docs/superpowers/specs/2026-10-05-one-click-launch-design.md`（§0 六个已确认决策、§2 实测事实与 §2.4 待验证清单、§3–§7 设计；本计划实现其 §9 的"计划一"）

## Global Constraints

- 本期启动白名单固定为一个：`LAUNCH_KEYS == {"jenkins"}`，**不得自行扩大**。ActiveMQ / Nacos 属计划二。
- **权威真相是端口，不是 PID**：任何"运行中"判定必须有"登记的端口在听"这一条；`pid_role` 只用于选择停止手段。
- **状态检测与找回过程绝不执行任何进程**：`status()` / `adopt()` 只允许 `socket` + `urllib`。这条有专门回归用例守着（Task 4、Task 5）。
- 本期**不做**：开机自启、崩溃自动重启、注册系统服务、集群编排、配置文件的端口回写（Jenkins 用命令行 `--httpPort`，无需回写）。
- `min_java_major` **不许凭印象填数字**。Jenkins 的 manifest 只证明 `Build-Jdk-Spec: 21` / `Java-Version: 11`，真正门槛是 spec §2.4 第 5 项，实测前保持 `None`（门控退化为"有没有 JDK"）。
- 注释、docstring 与面向用户的日志/文案一律中文；`main.py` 行尾以**索引内形态（LF）**为准，工作区因 `core.autocrlf=true` 呈现 CRLF 属正常，不要为行尾去改文件、也不要把这当回归。
- 测试**绝不真起中间件、绝不写真注册表、绝不改用户 shell rc**：拉起进程一律打桩 `subprocess.Popen`；探针函数通过参数注入。真启动只出现在 Task 12 的演练脚本里。
- 不为测试在产品代码里加开关（feature flag）；打桩在测试侧完成。唯一新增的外部入口是演练脚本的 `--launch` 参数。
- **助手不执行任何 git 命令**（含 `git add` / `git commit` / `git push`），也不执行删除类 shell 命令；每个 Task 的 commit 步骤一律写成"输出下面命令，由用户复制执行"。
- 运行测试统一：`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`；全量回归见 Task 13。

---

### Task 1: LaunchSpec 数据层与启动登记表

**Files:**
- Modify: `main.py:216-225`（`Component` 字段区，`category` 之前插入）
- Modify: `main.py:2960` 之后（`MULTI_VERSION_KEYS` 附近，新增 `LAUNCH_OF` / `LAUNCH_KEYS`）
- Modify: `main.py:3452-3454`（`build_components()` 末尾统一赋值处）
- Test: `bt_launch_tests.py`（新建，本 Task 起）

**Interfaces:**
- Consumes: 无（本 Task 是地基）
- Produces:
  - `class LaunchSpec` —— 字段见下方实现，全部有默认值
  - `LAUNCH_OF: Dict[str, LaunchSpec]`、`LAUNCH_KEYS: set`
  - `Component.launch: Optional[LaunchSpec]`（默认 `None`）

- [ ] **Step 1: 写失败测试**

新建 `bt_launch_tests.py`：

```python
"""一键启动护栏（离线）。设计文档见 docs/superpowers/specs/2026-10-05-one-click-launch-design.md"""
import os
import platform as _platform
import sys
import unittest

_platform._wmi_query = lambda *_a, **_k: (_ for _ in ()).throw(OSError("stub: 不许走 WMI"))
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402


class LaunchSpecTable(unittest.TestCase):
    def setUp(self):
        self.comps = {c.key: c for c in main.build_components()}

    def test_launch_keys_are_exactly_jenkins(self):
        self.assertEqual(main.LAUNCH_KEYS, {"jenkins"},
                         "计划一启动白名单只有 jenkins，扩白名单属计划二")

    def test_every_launch_key_is_a_known_category_component(self):
        for key in main.LAUNCH_KEYS:
            self.assertIn(key, self.comps, f"{key} 登记了启动描述符但组件不存在")

    def test_jenkins_spec_has_all_three_os_commands(self):
        spec = self.comps["jenkins"].launch
        self.assertIsNotNone(spec, "jenkins 必须有 launch")
        for os_name in ("Windows", "Linux", "Darwin"):
            argv = spec.commands.get(os_name)
            self.assertTrue(argv, f"{os_name} 的启动命令为空")
            self.assertIn("{java}", argv[0], "启动命令必须以 java 可执行打头")

    def test_components_outside_whitelist_have_no_launch(self):
        for key, comp in self.comps.items():
            if key not in main.LAUNCH_KEYS:
                self.assertIsNone(comp.launch, f"{key} 不该有启动描述符")

    def test_min_java_major_is_none_until_measured(self):
        """spec §2.4 第 5 项实测前禁止填数字，门控只能退化成"有没有 JDK"。"""
        self.assertIsNone(self.comps["jenkins"].launch.min_java_major)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL / ERROR，报 `AttributeError: module 'main' has no attribute 'LAUNCH_OF'` 或 `No attribute 'launch'`

- [ ] **Step 3: 写最小实现**

在 `main.py` 的 `Component` 字段区（`category: str = ""` 之前）加：

```python
    # 启动描述符（见 docs/superpowers/specs/2026-10-05-one-click-launch-design.md §3）。
    # 由 build_components() 末尾按 LAUNCH_OF 统一赋值，不要在构造处手写 ——
    # 与 MULTI_VERSION_KEYS 同一套"单一真源"做法。
    launch: Optional["LaunchSpec"] = None
```

在 `MULTI_VERSION_KEYS`（`main.py:2960`）之后加：

```python
@dataclass
class LaunchSpec:
    """一个组件"怎么被拉起来"的描述符。本期只有 cli 改端口一种端口策略，
    配置回写（property_file）留给计划二，故此处不提供该字段。"""

    # 按 OS 键的启动 argv 模板。允许这些占位符：
    #   {java} {war} {home} {data_dir} {port} {log_file}
    commands: Dict[str, List[str]]
    # 停止手段："pid" = 只能结束进程（Jenkins 无 shutdown 脚本）；
    #           "shutdown_command" = 有正规关闭脚本（计划二的 ActiveMQ / Nacos）
    stop_kind: str = "pid"
    shutdown_commands: Dict[str, List[str]] = field(default_factory=dict)
    # 端口簇：主端口 + 派生偏移。本期 jenkins 只有主端口，offsets 为空。
    main_port: int = 0
    port_offsets: tuple = ()
    port_search_span: int = 99
    # 界面打开控制台用：http://127.0.0.1:{port}{console_path}
    console_path: str = "/"
    # 探活路径。None 表示只做 TCP 判活，不发 HTTP。
    health_path: Optional[str] = None
    # 前置组件 key。Jenkins 需要 JDK。
    needs: tuple = ()
    # JDK 最低大版本。spec §2.4 第 5 项实测前必须留 None，
    # 非 None 才能启用版本门控；填数字前请先拿到实测结论。
    min_java_major: Optional[int] = None
    # 要注入的数据目录环境变量名（Jenkins: JENKINS_HOME）。None 表示不注入。
    data_dir_env: Optional[str] = None
    # 拉起后多久内必须开始监听，超时判启动失败。
    startup_timeout: int = 120
    # 启动确认弹窗里的风险说明文本（监听地址、默认凭据一类）。
    risk_note: str = ""


LAUNCH_OF: Dict[str, LaunchSpec] = {
    "jenkins": LaunchSpec(
        commands={os_name: ["{java}", "-jar", "{war}", "--httpPort={port}"]
                  for os_name in ("Windows", "Linux", "Darwin")},
        stop_kind="pid",
        main_port=8080,
        console_path="/",
        health_path="/login",
        needs=("jdk",),
        min_java_major=None,
        data_dir_env="JENKINS_HOME",
        startup_timeout=180,
        risk_note=(
            "Jenkins 会监听本机 8080（默认对局域网开放），首次启动是解锁向导；"
            "初始管理员密码在 JENKINS_HOME 的 secrets 目录下。"
            "只想本机访问的话，把命令里的监听地址改成 127.0.0.1 再启动。"
        ),
    ),
}

LAUNCH_KEYS = set(LAUNCH_OF)
```

在 `build_components()` 末尾（`main.py:3452-3454` 那个循环里）加一行：

```python
        comp.launch = LAUNCH_OF.get(comp.key)                     # 新增：不在登记表就是 None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 5 tests ... OK`

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): 新增 LaunchSpec 数据层与 jenkins 启动登记表"
```

---

### Task 2: `running.json` 运行登记（读写 + 损坏自愈）

**Files:**
- Modify: `main.py:104` 之后（`CONFIG_FILE` 旁新增 `RUNNING_FILE`）
- Modify: `main.py:4278` 附近（照 `_atomic_write_config` 的写法新增两个函数）
- Test: `bt_launch_tests.py`（追加 `RunningMap` 类）

**Interfaces:**
- Consumes: `CONFIG_DIR`（`main.py:103`）、`ensure_dir`（`main.py:146`）
- Produces:
  - `RUNNING_FILE: Path`
  - `@dataclass RunRecord`，含 `key version home data_dir port console_url pid pid_role started_at launcher_cmd`
  - `load_running_map() -> Dict[str, RunRecord]`
  - `save_running_map(records: Dict[str, RunRecord]) -> None`

- [ ] **Step 1: 写失败测试**

```python
class RunningMap(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig)

    def make(self, **kw):
        base = dict(key="jenkins", version="2.568.3", home="/h", data_dir="/d",
                    port=8080, console_url="http://127.0.0.1:8080/",
                    pid=1234, pid_role="server", started_at=1.0, launcher_cmd=["java"])
        base.update(kw)
        return main.RunRecord(**base)

    def test_missing_file_is_empty_table(self):
        self.assertEqual(main.load_running_map(), {})

    def test_broken_json_is_empty_table_and_is_not_fatal(self):
        main.RUNNING_FILE.write_text("{ not json", encoding="utf-8")
        self.assertEqual(main.load_running_map(), {})

    def test_round_trip(self):
        rec = {"jenkins": self.make()}
        main.save_running_map(rec)
        got = main.load_running_map()
        self.assertEqual(got["jenkins"].port, 8080)
        self.assertEqual(got["jenkins"].pid_role, "server")

    def test_save_is_atomic_leaving_no_tmp(self):
        main.save_running_map({"jenkins": self.make()})
        leftovers = list(Path(self.dir.name).glob("running.json.tmp*"))
        self.assertEqual(leftovers, [], "原子写没把临时文件收干净")

    def test_record_without_pid_role_is_rejected_not_guessed(self):
        """pid_role 必须显式写：拿它做判断是本设计的雷区，缺字段就当不可信记录丢掉。"""
        main.save_running_map({"jenkins": self.make()})
        data = json.loads(main.RUNNING_FILE.read_text(encoding="utf-8"))
        data["jenkins"].pop("pid_role")
        main.RUNNING_FILE.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(main.load_running_map(), {})
```

顶部补 `import json, tempfile` 与 `from pathlib import Path`（本 Task 起测试文件要用到）。

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`module 'main' has no attribute 'RunRecord'`

- [ ] **Step 3: 写最小实现**

`main.py:104` 后加：

```python
RUNNING_FILE = CONFIG_DIR / "running.json"      # 本机进程事实，与用户偏好分开（设计 §3）
```

在 `_atomic_write_config` 附近加：

```python
@dataclass
class RunRecord:
    """一条运行登记。

    pid_role 是显式字段而不是省略约定：spec §2 实测到 Nacos / ActiveMQ 的启动脚本
    会自己后台化，脚本返回的 PID 几秒后就不是服务进程了。把"这个 PID 是什么身份"
    写下来，才不至于以后有人拿 launcher 的 PID 判生死。
    """

    key: str
    version: str
    home: str
    data_dir: str
    port: int
    console_url: str
    pid: int
    pid_role: str            # "server" | "launcher" | "none"
    started_at: float
    launcher_cmd: List[str]

    def to_dict(self) -> Dict[str, object]:
        return dict(self.__dict__)


def load_running_map() -> Dict[str, RunRecord]:
    """读取运行登记表。文件缺失、JSON 坏了、记录缺字段，一律当空表。

    这里"宽容"是有意的：running.json 删了只是重新发现一遍本机进程，
    而让它把整个界面搞崩、或者据此去动进程，代价完全不成比例。"""
    if not RUNNING_FILE.exists():
        return {}
    try:
        data = json.loads(RUNNING_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, RunRecord] = {}
    for item in data.values():
        if not isinstance(item, dict):
            continue
        try:
            rec = RunRecord(**item)
        except (TypeError, KeyError):
            continue
        if rec.pid_role not in ("server", "launcher", "none"):
            continue
        out[rec.key] = rec
    return out


def save_running_map(records: Dict[str, RunRecord]) -> None:
    """running.json 的唯一落盘出口，照 _atomic_write_config 的临时文件 + os.replace。"""
    ensure_dir(RUNNING_FILE.parent)
    payload = {rec.key: rec.to_dict() for rec in records.values()}
    tmp = RUNNING_FILE.with_name(RUNNING_FILE.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, RUNNING_FILE)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 10 tests ... OK`

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): running.json 运行登记，坏文件自愈当空表"
```

---

### Task 3: 端口簇选择（纯函数，规则定死）

**Files:**
- Modify: `main.py`（`load_running_map` 之后新增一节工具函数）
- Test: `bt_launch_tests.py`（追加 `PortCluster` 类）

**Interfaces:**
- Consumes: `LaunchSpec.main_port / port_offsets / port_search_span`（Task 1）
- Produces: `port_is_free(port: int, host: str = "127.0.0.1") -> bool`、`pick_free_cluster(base_port: int, offsets: tuple, span: int = 99, is_free=port_is_free) -> Optional[int]`

- [ ] **Step 1: 写失败测试**

```python
class PortCluster(unittest.TestCase):
    def probe(self, taken):
        """造一个假探针：只有不在 taken 里的口算空。"""
        return lambda port, host="127.0.0.1": port not in taken

    def test_default_when_everything_free(self):
        self.assertEqual(main.pick_free_cluster(8080, (), 99, self.probe(set())), 8080)

    def test_shifts_up_one_by_one_within_span(self):
        got = main.pick_free_cluster(8080, (), 99, self.probe({8080, 8081}))
        self.assertEqual(got, 8082, "应从主端口起升序找第一个空闲口，不是随机挑")

    def test_cluster_must_be_free_together(self):
        """派生端口（Nacos 的 gRPC offset 那类）任一被占，整簇都算不可用。"""
        # 主端口 8848-8853 全空，但每个候选的派生端口里都被占一个：
        # 整簇必须一起可用，所以一个都不能选出来。
        taken = set(range(9848, 9854))
        got = main.pick_free_cluster(8848, (0, 1000, 1001), 5, self.probe(taken))
        self.assertEqual(got, None, "整簇平移后仍撞车时不许硬选，返回 None 走失败语义")

    def test_cluster_finds_next_clean_base(self):
        # 8848 本身被占，且 9849-9857 把候选 8849..8857 的派生端口逐个堵死，
        # 第一个整簇干净的只能是 8858。
        taken = {8848, *range(9849, 9858)}
        got = main.pick_free_cluster(8848, (0, 1000, 1001), 10, self.probe(taken))
        self.assertEqual(got, 8858, f"应找到整簇都空的 8858，实际 {got}")

    def test_span_exhausted_returns_none(self):
        self.assertEqual(main.pick_free_cluster(8080, (), 3, lambda p, host="127.0.0.1": False), None)

    def test_offsets_include_base_itself(self):
        seen = []
        main.pick_free_cluster(9000, (1000,), 2, lambda p, host="127.0.0.1": (seen.append(p) or True))
        self.assertIn(9000, seen)
        self.assertIn(10000, seen)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`no attribute 'pick_free_cluster'`

- [ ] **Step 3: 写最小实现**

```python
def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """本机这个口是否空闲。connect_ex != 0 即没人连得上 = 空闲。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) != 0


def pick_free_cluster(base_port: int, offsets: tuple = (), span: int = 99,
                      is_free=port_is_free) -> Optional[int]:
    """在 [base_port, base_port + span] 内升序找"整簇同时空闲"的最小主端口；找不到返回 None。

    规则写死成"最小 + 整簇"，是为了让界面显示的端口可复现：随机挑会让同一个环境
    两次启动落在不同口上，故障归因和文档都没法写（设计 §4）。"""
    all_offsets = tuple(dict.fromkeys((0,) + tuple(offsets)))
    for candidate in range(base_port, base_port + span + 1):
        if all(is_free(candidate + off) for off in all_offsets):
            return candidate
    return None
```

`main.py` 顶部补 `import socket`（若尚未导入）。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 16 tests ... OK`

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): 端口簇选择算法（整簇空闲、区间内取最小）"
```

---

### Task 4: 探活与"绝不执行进程"不变量

**Files:**
- Modify: `main.py`（紧接 Task 3 的函数）
- Test: `bt_launch_tests.py`（追加 `HealthProbe` 与 `NoExecInvariant`）

**Interfaces:**
- Consumes: `socket`、`urllib.request`
- Produces: `port_is_listening(port: int, host: str = "127.0.0.1") -> bool`、`http_ok(url: str, timeout: float = 2.0) -> bool`、`process_is_alive(pid: int) -> bool`

- [ ] **Step 1: 写失败测试**

```python
class HealthProbe(unittest.TestCase):
    def test_port_is_listening_sees_a_real_listener(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        self.addCleanup(srv.close)
        port = srv.getsockname()[1]
        self.assertTrue(main.port_is_listening(port, "127.0.0.1"))
        srv.close()
        self.assertFalse(main.port_is_listening(port, "127.0.0.1"),
                         "关掉监听后必须认成没在听，否则僵尸判定形同虚设")

    def test_http_ok_accepts_2xx_and_3xx_only(self):
        for code, want in ((200, True), (302, True), (401, True), (404, False), (500, False)):
            with self.subTest(code=code):
                fake = lambda url, timeout=2.0: code
                self.assertEqual(main._http_status_with(fake, "http://x"), want)

    def test_http_ok_is_false_on_any_error(self):
        def boom(url, timeout=2.0):
            raise OSError("connection refused")
        self.assertFalse(main._http_status_with(boom, "http://x"))

    def test_process_alive_rejects_non_positive_pid(self):
        self.assertFalse(main.process_is_alive(0))
        self.assertFalse(main.process_is_alive(-1))


class NoExecInvariant(unittest.TestCase):
    """spec §6：状态检测与找回过程一次都不许拉起进程。

    手法照 bt_startup_tests.py 的 PROBE_CHILD：把"起进程"的入口全部换成一调用就炸，
    然后跑完只读路径。这条用例是整套设计最需要长期守住的东西。"""

    def setUp(self):
        self._popen = main.subprocess.Popen
        self._probe = main._probe_version
        def _boom(*_a, **_k):
            raise AssertionError("状态检测路径里不得调用 Popen / _probe_version")
        main.subprocess.Popen = _boom
        main._probe_version = _boom
        self.addCleanup(setattr, main.subprocess, "Popen", self._popen)
        self.addCleanup(setattr, main, "_probe_version", self._probe)

    def test_status_and_adopt_never_spawn(self):
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda url, timeout=2.0: True,
                                  process_alive=lambda pid: True)
        comps = {c.key: c for c in main.build_components()}
        with tempfile.TemporaryDirectory() as td:
            rec = main.RunRecord(key="jenkins", version="2.568.3", home=td, data_dir=td,
                                 port=8080, console_url="http://127.0.0.1:8080/",
                                 pid=4242, pid_role="server", started_at=0.0,
                                 launcher_cmd=["java"])
            main.save_running_map({"jenkins": rec})
            self.assertEqual(mgr.status("jenkins", comps["jenkins"]).state, "running")
            self.assertEqual(list(mgr.adopt(comps))[0].state, "running")
            main.save_running_map({})
            self.assertEqual(mgr.status("jenkins", comps["jenkins"]).state, "not_installed_or_stopped")
```

测试文件顶部补 `import socket`（`HealthProbe` 要自己造一个真监听套接字来判活）。

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`no attribute 'port_is_listening'` / `no attribute 'ServiceManager'`

- [ ] **Step 3: 写最小实现**

```python
def port_is_listening(port: int, host: str = "127.0.0.1") -> bool:
    """端口是否有人在听。connect_ex == 0 才算有人。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _http_status_with(fetch, url: str) -> bool:
    """把"发请求"抽成注入点，测试才能完全不碰网络。2xx/3xx/401 都算服务活着：
    Jenkins 的 /login 在未初始化时会给 200，而根路径可能 403，401 说明服务在、只是要认证。"""
    try:
        return fetch(url) in (200, 201, 202, 204, 301, 302, 303, 307, 401)
    except Exception:
        return False


def _http_fetch_status(url: str, timeout: float = 2.0) -> int:
    req = urllib.request.Request(url, headers=dict(HTTP_UA))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        return exc.code


def http_ok(url: str, timeout: float = 2.0) -> bool:
    return _http_status_with(lambda u: _http_fetch_status(u, timeout), url)


def process_is_alive(pid: int) -> bool:
    """PID 是否还在。**注意这是提示不是真相**：spec §4 定的是端口在听才算运行中。"""
    if not pid or pid <= 0:
        return False
    if CURRENT_OS == "Windows":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        still_alive = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return True          # 打不开句柄：权限不足，不能断定它死了
        try:
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == still_alive
            return True
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
```

并在文件顶部确认已导入 `urllib.request`、`urllib.error`（缺则补），以及 `import socket`。

本 Task 同时新建 `ServiceManager` 的**只读**部分（`start` / `stop` 在 Task 7、8 填）：

```python
@dataclass
class LaunchStatus:
    """组件当前运行状态。state 取值：
    not_installed_or_stopped / running / zombie（登记在但端口不在听了）"""
    state: str
    record: Optional[RunRecord] = None
    reason: str = ""


class ServiceManager:
    """本机进程生命周期的唯一入口。探针全部可注入，测试因此不碰网络也不碰进程。"""

    def __init__(self, is_listening=port_is_listening, http_ok=http_ok,
                 process_alive=process_is_alive):
        self._is_listening = is_listening
        self._http_ok = http_ok
        self._process_alive = process_alive

    def status(self, key: str, comp: Component,
               records: Optional[Dict[str, RunRecord]] = None) -> LaunchStatus:
        if getattr(comp, "launch", None) is None:
            return LaunchStatus("not_installed_or_stopped")
        rec = (records if records is not None else load_running_map()).get(key)
        if rec is None:
            return LaunchStatus("not_installed_or_stopped")
        if not self._is_listening(rec.port):
            return LaunchStatus("zombie", rec,
                                f"登记的进程已不在监听 {rec.port}")
        return LaunchStatus("running", rec)

    def adopt(self, comps: Dict[str, Component]) -> List[LaunchStatus]:
        """打开工具时对每个可启动组件做一次只读认定。绝不拉起进程。"""
        records = load_running_map()
        return [self.status(k, c, records) for k, c in comps.items()
                if getattr(c, "launch", None) is not None]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 23 tests ... OK`。若 `NoExecInvariant` 里 `adopt()` 断言与实现返回顺序不一致，按实现的组件顺序修正测试，**不要反过来放宽护栏**。

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): 端口/HTTP 探活 + 状态认定，并钉死检测路径不执行进程"
```

---

### Task 5: 僵尸登记矩阵与清理

**Files:**
- Modify: `main.py`（`ServiceManager`）
- Test: `bt_launch_tests.py`（追加 `ZombieMatrix`）

**Interfaces:**
- Consumes: `load_running_map` / `save_running_map`（Task 2）、`LaunchStatus`（Task 4）
- Produces: `ServiceManager.reconcile(comps) -> Dict[str, LaunchStatus]`（把僵尸登记清掉并返回认定结果，返回集合与写盘必须一致）

- [ ] **Step 1: 写失败测试**

```python
class ZombieMatrix(unittest.TestCase):
    """spec §5：PID 死 / PID 活端口不在 / 端口在听但 PID 不符 / 坏 JSON，
    四种情形都不许触发任何进程动作。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig)
        self.comps = {c.key: c for c in main.build_components()}
        self.rec = main.RunRecord(key="jenkins", version="2.568.3", home="/h",
                                  data_dir="/d", port=8080,
                                  console_url="http://127.0.0.1:8080/",
                                  pid=4242, pid_role="server", started_at=0.0,
                                  launcher_cmd=["java"])

    def mgr(self, listening, alive):
        return main.ServiceManager(is_listening=lambda p, host="127.0.0.1": listening,
                                   http_ok=lambda u, timeout=2.0: listening,
                                   process_alive=lambda pid: alive)

    def test_pid_dead_but_port_listening_is_still_running(self):
        """端口是真相。PID 判不出来（权限不足）时不该误报停止。"""
        main.save_running_map({"jenkins": self.rec})
        st = self.mgr(listening=True, alive=False).reconcile(self.comps)
        self.assertEqual(st["jenkins"].state, "running")
        self.assertEqual(main.load_running_map().get("jenkins").port, 8080)

    def test_pid_alive_but_port_free_is_zombie_and_record_dropped(self):
        main.save_running_map({"jenkins": self.rec})
        st = self.mgr(listening=False, alive=True).reconcile(self.comps)
        self.assertEqual(st["jenkins"].state, "not_installed_or_stopped")
        self.assertEqual(main.load_running_map(), {}, "僵尸登记必须清掉")

    def test_broken_json_yields_empty_and_touches_nothing(self):
        main.RUNNING_FILE.write_text("{", encoding="utf-8")
        calls = []
        mgr = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": calls.append(p) or True,
            http_ok=lambda u, timeout=2.0: True, process_alive=lambda pid: calls.append(pid) or True)
        self.assertEqual(mgr.reconcile(self.comps), {})
        self.assertEqual(calls, [], "空表不该去探任何端口")

    def test_foreign_key_record_survives_reconcile(self):
        """登记里出现本期不认识的可启动组件（计划二加的），不许被误删。"""
        other = main.RunRecord(key="nacos", version="2.3.2", home="/h", data_dir="/d",
                               port=8848, console_url="http://127.0.0.1:8848/",
                               pid=1, pid_role="none", started_at=0.0, launcher_cmd=[])
        main.save_running_map({"nacos": other})
        st = self.mgr(listening=True, alive=True).reconcile(self.comps)
        self.assertNotIn("nacos", st, "没登记的组件不该被本工具接管")
        self.assertIn("nacos", main.load_running_map())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`'ServiceManager' object has no attribute 'reconcile'`

- [ ] **Step 3: 写最小实现**

在 `ServiceManager` 里加：

```python
    def reconcile(self, comps: Dict[str, Component]) -> Dict[str, LaunchStatus]:
        """一次性认定 + 清僵尸：只处理 LAUNCH_KEYS 里的组件。

        计划二会往登记表加组件，届时旧登记不该被本期代码删掉，
        所以这里按"认得的 key"过滤，而不是清全部文件。"""
        records = load_running_map()
        out: Dict[str, LaunchStatus] = {}
        dirty = False
        for key in LAUNCH_KEYS:
            comp = comps.get(key)
            if comp is None or getattr(comp, "launch", None) is None:
                continue
            if key not in records:
                continue          # 没有登记的 key 不是"待认定"的东西：卡片自己的
                                  # status() 会答"未运行"，reconcile 只负责把有过登记的
                                  # 一条条判完，返回集因此可以为空（用例钉的就是这个）
            st = self.status(key, comp, records)
            if st.state == "zombie":
                records.pop(key, None)
                dirty = True
                st = LaunchStatus("not_installed_or_stopped")
            out[key] = st
        if dirty:
            save_running_map(records)
        return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 27 tests ... OK`

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): 僵尸登记清理（端口为真相，PID 判不死就不误停）"
```

---

### Task 6: 启动计划组装（纯函数）

**Files:**
- Modify: `main.py`（`ServiceManager` 上方新增模块级函数）
- Test: `bt_launch_tests.py`（追加 `LaunchPlan`）

**Interfaces:**
- Consumes: `Component.install_dir`（`main.py:227`）、`load_active_map`（`main.py:4292`）、`EnvManager`（`main.py:3656`）、`ensure_dir`
- Produces: `resolve_java_home(comps: Dict[str, Component]) -> Optional[str]`、`build_launch_plan(comp, spec, java_home, port, log_file) -> LaunchPlan`；`@dataclass LaunchPlan(argv: List[str], env: Dict[str, str], cwd: Path, log_file: Path, console_url: str)`

- [ ] **Step 1: 写失败测试**

```python
class LaunchPlan(unittest.TestCase):
    def setUp(self):
        # build_launch_plan 会 ensure_dir(data_dir)，不patch CONFIG_DIR 就会在真
        # ~/.env-tools 下留下 jenkins-data 目录。
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig_dir = main.CONFIG_DIR
        main.CONFIG_DIR = Path(self.dir.name)
        self.addCleanup(setattr, main, "CONFIG_DIR", self._orig_dir)
        self.comps = {c.key: c for c in main.build_components()}
        self.comp = self.comps["jenkins"]
        self.spec = self.comp.launch

    def test_java_home_prefers_our_own_installed_jdk(self):
        """EnvManager.get 只是 os.environ.get（main.py:3660），
        所以 JAVA_HOME 必须按"本工具装了哪个 JDK"来定，不能信进程环境。"""
        with tempfile.TemporaryDirectory() as td:
            # Component.install_dir() 的形状是 <CONFIG_DIR>/<key>/<key>-<version>（main.py:227）
            home = Path(td) / "jdk" / "jdk-21"
            (home / "bin").mkdir(parents=True)
            (home / "bin" / ("java.exe" if main.CURRENT_OS == "Windows" else "java")).write_bytes(b"x")
            orig_dir, orig_map = main.CONFIG_DIR, main.load_active_map
            self.addCleanup(setattr, main, "CONFIG_DIR", orig_dir)
            self.addCleanup(setattr, main, "load_active_map", orig_map)
            main.CONFIG_DIR = Path(td)
            main.load_active_map = lambda: {"jdk": "21"}
            self.assertEqual(main.resolve_java_home(self.comps), str(home))

    def test_java_home_falls_back_to_env_var_but_validates_it(self):
        """本工具没装 JDK 时退到用户的 JAVA_HOME，但必须确认它真是个 JDK 目录：
        指到一个不存在的路径就当没有，否则启动报错无从解释。"""
        orig_map = main.load_active_map
        orig_env = os.environ.get("JAVA_HOME")
        self.addCleanup(setattr, main, "load_active_map", orig_map)
        with tempfile.TemporaryDirectory() as td:
            real_home = Path(td) / "external-jdk"
            (real_home / "bin").mkdir(parents=True)
            main.load_active_map = lambda: {}
            os.environ["JAVA_HOME"] = str(real_home)
            self.assertEqual(main.resolve_java_home(self.comps), str(real_home))
            os.environ["JAVA_HOME"] = str(Path(td) / "does-not-exist")
            self.assertIsNone(main.resolve_java_home(self.comps))
        if orig_env is None:
            os.environ.pop("JAVA_HOME", None)
        else:
            os.environ["JAVA_HOME"] = orig_env

    def test_gate_reports_missing_jdk_as_actionable(self):
        ok, reason = main.launch_gate(self.comp, self.spec, java_home=None)
        self.assertFalse(ok)
        self.assertIn("JDK", reason)

    def test_argv_expands_all_placeholders(self):
        plan = main.build_launch_plan(self.comp, self.spec, self.jdk_home,
                                      8123, Path(self.dir.name) / "byte-tools.out")
        java_exe = Path(self.jdk_home) / "bin" / ("java.exe" if main.CURRENT_OS == "Windows" else "java")
        self.assertEqual(str(plan.argv[0]), str(java_exe),
                         "build_launch_plan 收的是 JDK home，java 可执行文件由它自己拼")
        self.assertEqual(plan.argv[1], "-jar")
        self.assertTrue(str(plan.argv[2]).endswith("jenkins.war"))
        self.assertIn("--httpPort=8123", plan.argv)
        self.assertNotIn("{", " ".join(str(a) for a in plan.argv), "占位符没展开干净")

    def test_env_injects_jenkins_home_and_java_home(self):
        plan = main.build_launch_plan(self.comp, self.spec, self.jdk_home,
                                      8080, Path(self.dir.name) / "byte-tools.out")
        self.assertEqual(plan.env["JENKINS_HOME"], str(Path(main.CONFIG_DIR) / "jenkins-data"))
        self.assertEqual(plan.env["JAVA_HOME"], self.jdk_home)
        self.assertTrue(Path(plan.env["JENKINS_HOME"]).is_dir(), "数据目录必须在这一步就建好")
        self.assertTrue(str(plan.cwd).endswith("jenkins-2.568.3"), "工作目录是组件安装目录")

    def test_console_url_uses_actual_port(self):
        plan = main.build_launch_plan(self.comp, self.spec, self.jdk_home, 8123,
                                      Path(self.dir.name) / "o.out")
        self.assertEqual(plan.console_url, "http://127.0.0.1:8123/")
```

`setUp` 里再加一行 `self.jdk_home = str(Path(self.dir.name) / "jdkhome")`（本任务的
`build_launch_plan` 不校验 JDK 目录是否存在，校验是 `resolve_java_home` 的职责，已单独覆盖）。

约定 **`java_home` 参数一律是 JDK 安装目录（home），不是 java 可执行文件路径** ——
`resolve_java_home` 返回 home、`launch_gate` 判断 home 是否为 None、Task 7 的
`start()` 把 home 原样传进来，三者必须是同一语义，否则 JAVA_HOME 会被写成 exe 路径。

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`no attribute 'build_launch_plan'`

- [ ] **Step 3: 写最小实现**

```python
@dataclass
class LaunchPlan:
    """一次拉起所需的全部信息，纯数据 —— 决策都在这里做完，ServiceManager 只负责执行。"""
    argv: List[str]
    env: Dict[str, str]
    cwd: Path
    log_file: Path
    console_url: str


def resolve_java_home(comps: Dict[str, Component]) -> Optional[str]:
    """优先用本工具装的 JDK；没有再退到 JAVA_HOME 环境变量。

    EnvManager.get 就是 os.environ.get，拿它当"用户装的 JDK"会读到
    被本工具改脏的进程环境，与 R3 里"回滚要读持久层的真值"是同一个坑。"""
    jdk = comps.get("jdk")
    if jdk is not None:
        active = load_active_map().get("jdk")
        if active:
            home = jdk.install_dir(active)
            if jdk.exec_path_in_home(str(home)) is not None:
                return str(home)
    env_home = os.environ.get("JAVA_HOME")
    if env_home and (Path(env_home) / "bin").is_dir():
        return env_home
    return None


def launch_gate(comp: Component, spec: LaunchSpec,
                java_home: Optional[str]) -> Tuple[bool, str]:
    """启动前门控。失败原因必须可行动（spec §5）：说清缺什么、点这里能补什么。"""
    if getattr(comp, "launch", None) is None:
        return False, "本工具暂不支持启动该组件"
    if java_home is None and "jdk" in (spec.needs or ()):
        return False, "启动需要先有 JDK：在本工具里装一个 JDK（推荐 17），再回来点启动。"
    if not comp.versions:
        return False, "该组件还没有可启动的版本"
    return True, ""


def build_launch_plan(comp: Component, spec: LaunchSpec, java_home: str,
                      port: int, log_file: Path) -> LaunchPlan:
    """按 OS 展开模板，注入 env，定好 data_dir 与重定向文件。

    重定向不是可选项：Windows 用 DETACHED_PROCESS 拉起后没有有效控制台句柄，
    不重定向就等于把启动报错扔掉，事后只能猜（设计 §4）。"""
    version = comp.versions[0].version
    home = comp.install_dir(version)
    war = home / "jenkins.war"
    # 数据与版本目录分离（spec §0 决策 3）：JENKINS_HOME 指向 CONFIG_DIR/<key>-data，
    # 这样换版本、重装、卸载都不碰任务与插件。
    data_dir = CONFIG_DIR / f"{comp.key}-data"
    env = dict(os.environ)
    env["JAVA_HOME"] = str(Path(java_home))
    if spec.data_dir_env:
        env[spec.data_dir_env] = str(data_dir)
    ensure_dir(data_dir)
    mapping = {
        "java": str(Path(java_home) / "bin" / ("java.exe" if CURRENT_OS == "Windows" else "java")),
        "war": str(war),
        "home": str(home),
        "data_dir": str(data_dir),
        "port": str(port),
        "log_file": str(log_file),
    }
    argv = [t.format(**mapping) for t in spec.commands[CURRENT_OS]]
    return LaunchPlan(argv=argv, env=env, cwd=home, log_file=log_file,
                      console_url=f"http://127.0.0.1:{port}{spec.console_path}")
```

说明两点：`jenkins.war` 落在 `install_dir` 根（组件登记里 `path_subdir=""`，见 `main.py:3287` 附近注释）；数据在 `CONFIG_DIR/<key>-data`，与版本目录无关，所以**卸载某个版本不会带走 Jenkins 的任务与插件**——Task 10 因此要在卸载完成日志里显式报出这个目录的位置。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 33 tests ... OK`

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): 启动计划组装（JAVA_HOME 取自家装的 JDK + 输出重定向）"
```

---

### Task 7: `ServiceManager.start()`

**Files:**
- Modify: `main.py`（`ServiceManager`）
- Test: `bt_launch_tests.py`（追加 `StartFlow`）

**Interfaces:**
- Consumes: `build_launch_plan` / `launch_gate` / `pick_free_cluster`（Task 3、6）、`RunRecord` / `save_running_map`（Task 2）、`CREATE_NO_WINDOW`（`main.py:600`）
- Produces: `ServiceManager.start(comp, comps, sleeper=time.sleep) -> StartResult`；`@dataclass StartResult(ok: bool, state: str, reason: str, record: Optional[RunRecord], console_url: str)`

- [ ] **Step 1: 写失败测试**

```python
class StartFlow(unittest.TestCase):
    """真进程一律打桩：拉起 Popen 的调用参数是本期最容易出错的地方。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig_file, self._orig_dir = main.RUNNING_FILE, main.CONFIG_DIR
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        main.CONFIG_DIR = Path(self.dir.name)
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig_file)
        self.addCleanup(setattr, main, "CONFIG_DIR", self._orig_dir)
        self.comps = {c.key: c for c in main.build_components()}
        self.comp = self.comps["jenkins"]
        # 造一个"已安装"的样子
        home = self.comp.install_dir(self.comp.versions[0].version)
        (home / "data").mkdir(parents=True, exist_ok=True)
        (home / "jenkins.war").write_bytes(b"x")
        self.spawned = []

        class FakePopen:
            def __init__(self, argv, **kw):
                pass
        self._popen = main.subprocess.Popen

        def fake_popen(argv, **kw):
            self.spawned.append((list(argv), kw))
            class P:
                pid = 43210
                returncode = None
                def poll(self):
                    return None
            return P()
        main.subprocess.Popen = fake_popen
        self.addCleanup(setattr, main.subprocess, "Popen", self._popen)

    def mgr(self, listening_after=1):
        """第 listening_after 次探活开始说"在听了"，模拟服务起来要几秒。"""
        box = {"n": 0}
        def is_listening(port, host="127.0.0.1"):
            box["n"] += 1
            return box["n"] > listening_after
        return main.ServiceManager(is_listening=is_listening,
                                   http_ok=lambda u, timeout=2.0: True,
                                   process_alive=lambda pid: True)

    def test_gate_blocks_without_jdk(self):
        orig = main.resolve_java_home
        main.resolve_java_home = lambda comps: None
        self.addCleanup(setattr, main, "resolve_java_home", orig)
        res = self.mgr().start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("JDK", res.reason)
        self.assertEqual(self.spawned, [], "门控没过就不该拉起任何进程")

    def test_happy_path_writes_record_and_detaches(self):
        res = self.mgr(listening_after=1).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        argv, kw = self.spawned[0]
        rec = main.load_running_map()["jenkins"]
        self.assertIn(f"--httpPort={rec.port}", argv, "端口必须真的传进命令行")
        self.assertTrue(rec.console_url.endswith(f":{rec.port}/"))
        self.assertTrue(kw.get("start_new_session") or kw.get("creationflags"),
                        "必须按脱离进程拉起（DETACHED_PROCESS / start_new_session）")
        self.assertIn("stdout", kw)
        self.assertEqual(rec.pid, 43210)
        self.assertEqual(rec.pid_role, "server", "Jenkins 我们就是服务进程（spec §4）")

    def test_times_out_without_listening_and_leaves_no_record(self):
        res = self.mgr(listening_after=10 ** 6).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("未监听", res.reason)
        self.assertEqual(main.load_running_map(), {}, "启动失败不许留登记")

    def test_second_start_is_refused_while_running(self):
        self.mgr(listening_after=1).start(self.comp, self.comps, sleeper=lambda s: None)
        res = self.mgr(listening_after=0).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("已在运行", res.reason)
        self.assertEqual(len(self.spawned), 1, "重复启动必须被拒")

    def test_frees_port_by_shifting_cluster_when_8080_taken(self):
        orig = main.port_is_free
        main.port_is_free = lambda port, host="127.0.0.1": port != 8080
        self.addCleanup(setattr, main, "port_is_free", orig)
        res = self.mgr(listening_after=1).start(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(main.load_running_map()["jenkins"].port, 8081)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`'ServiceManager' object has no attribute 'start'`

- [ ] **Step 3: 写最小实现**

```python
@dataclass
class StartResult:
    ok: bool
    state: str            # "running" / "gate" / "port" / "timeout" / "spawn"
    reason: str = ""
    record: Optional[RunRecord] = None
    console_url: str = ""


class ServiceManager:
    # …Task 4/5 的方法之后追加：

    def start(self, comp: Component, comps: Dict[str, Component],
              sleeper=time.sleep) -> StartResult:
        spec = getattr(comp, "launch", None)
        if spec is None:
            return StartResult(False, "gate", "本工具暂不支持启动该组件")
        existing = load_running_map().get(comp.key)
        if existing and self._is_listening(existing.port):
            return StartResult(False, "gate",
                               f"{comp.display_name} 已在运行（端口 {existing.port}）",
                               record=existing, console_url=existing.console_url)

        java_home = resolve_java_home(comps)
        ok, reason = launch_gate(comp, spec, java_home)
        if not ok:
            return StartResult(False, "gate", reason)

        base = spec.main_port
        # is_free 显式按名字传，不靠默认值绑定：默认参数在 def 时就把函数绑死了，
        # 测试 patch main.port_is_free 会失效（Task 7 的端口平移用例正是靠它）。
        port = pick_free_cluster(base, spec.port_offsets, spec.port_search_span,
                                 is_free=port_is_free)
        if port is None:
            return StartResult(False, "port",
                               f"{base} 起 {spec.port_search_span + 1} 个端口内都没找到"
                               f"能整簇空闲的位置，先关掉占用 {base} 的程序再试。")

        data_dir = CONFIG_DIR / f"{comp.key}-data"
        log_file = data_dir / "logs" / "byte-tools.out"
        ensure_dir(log_file.parent)
        plan = build_launch_plan(comp, spec, java_home, port, log_file)

        popen_kw = dict(cwd=str(plan.cwd), env=plan.env,
                        stdout=open(plan.log_file, "ab", buffering=0),
                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        if CURRENT_OS == "Windows":
            popen_kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            if CREATE_NO_WINDOW:
                popen_kw["creationflags"] |= CREATE_NO_WINDOW
        else:
            popen_kw["start_new_session"] = True

        try:
            proc = subprocess.Popen(plan.argv, **popen_kw)
        except OSError as exc:
            return StartResult(False, "spawn", f"拉起失败：{exc}")

        deadline = time.time() + spec.startup_timeout
        while time.time() < deadline:
            if self._is_listening(port):
                rec = RunRecord(key=comp.key, version=comp.versions[0].version,
                                home=str(plan.cwd), data_dir=plan.env.get(spec.data_dir_env, ""),
                                port=port, console_url=plan.console_url,
                                pid=proc.pid,
                                pid_role="server" if spec.stop_kind == "pid" else "launcher",
                                started_at=time.time(), launcher_cmd=list(plan.argv))
                records = load_running_map()
                records[comp.key] = rec
                save_running_map(records)
                return StartResult(True, "running", record=rec, console_url=plan.console_url)
            sleeper(1.0)

        # 超时：把刚拉起的进程收掉，不留一个"没人登记的监听者"
        try:
            proc.terminate()
        except Exception:
            pass
        return StartResult(False, "timeout",
                           f"{spec.startup_timeout} 秒内 {port} 未监听。"
                           f"启动输出见 {plan.log_file}，末尾内容：{self._tail(plan.log_file)}")

    @staticmethod
    def _tail(path: Path, lines: int = 8) -> str:
        """失败归因要能直接看见（spec §5）：读日志末尾几行，读不到就说读不到。"""
        try:
            data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return "（日志还读不到）"
        return " / ".join(data[-lines:]) if data else "（日志为空）"
```

`subprocess.DETACHED_PROCESS` 在部分 Python 上存在、缺失时按 `0x00000008` 兜底：在本 Task 顶部定义 `DETACH_FLAGS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)` 并在 `popen_kw` 里用它，别在表达式里混两种写法。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 38 tests ... OK`

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): ServiceManager.start —— 门控、选端口、脱离拉起、有界探活后才登记"
```

---

### Task 8: `ServiceManager.stop()`（超时只询问，不强杀）

**Files:**
- Modify: `main.py`（`ServiceManager`）
- Test: `bt_launch_tests.py`（追加 `StopFlow`）

**Interfaces:**
- Consumes: `load_running_map` / `save_running_map`、`LaunchSpec.stop_kind` / `shutdown_commands`
- Produces: `ServiceManager.stop(comp, comps, deadline=30.0, sleeper=time.sleep) -> StopResult`；`@dataclass StopResult(ok: bool, need_force: bool, reason: str)`；`ServiceManager.force_stop(key, sleeper=time.sleep, rounds=5) -> StopResult`

- [ ] **Step 1: 写失败测试**

```python
class StopFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig)
        self.comps = {c.key: c for c in main.build_components()}
        self.comp = self.comps["jenkins"]
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="2.568.3", home="/h", data_dir="/d", port=8080,
            console_url="http://127.0.0.1:8080/", pid=43210, pid_role="server",
            started_at=0.0, launcher_cmd=["java"])})

    def test_jenkins_stop_uses_pid_terminate_and_drops_record(self):
        killed = []
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda rec: killed.append(rec.pid))
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(killed, [43210])
        self.assertEqual(main.load_running_map(), {})

    def test_stuck_process_asks_forced_and_keeps_record(self):
        """超时不许自动强杀：必须返回 need_force，由界面问人（spec §5）。"""
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True,
                                  terminate=lambda rec: None)
        res = mgr.stop(self.comp, self.comps, deadline=0.0, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertTrue(res.need_force)
        self.assertIn("强制", res.reason)
        self.assertIn("jenkins", main.load_running_map(), "没停成就保留登记，别把进程变孤儿")

    def test_force_stop_clears_record_when_port_releases(self):
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda rec: None)
        self.assertTrue(mgr.force_stop("jenkins").ok)
        self.assertEqual(main.load_running_map(), {})

    def test_stop_without_record_is_harmless(self):
        main.save_running_map({})
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False, terminate=lambda rec: None)
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertIn("没有本工具的启动登记", res.reason)

    def test_stop_defaults_to_killing_the_registered_server_pid(self):
        """不注入 terminate 时，stop() 必须真的落到 _terminate_by_pid —— 那是生产默认路径。"""
        killed = []
        orig = main.os.kill
        main.os.kill = lambda pid, sig: killed.append((pid, sig))
        self.addCleanup(setattr, main.os, "kill", orig)
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(killed, [(43210, 15)])

    def test_windows_pid_stop_asks_before_killing(self):
        """Windows 路线专用：os.kill 的任何信号值在 Windows 上都是 TerminateProcess，
        也就是"强杀"本身。spec §5 要求超时只询问、不自动强杀，所以停止的第一步不许动手。"""
        main.CURRENT_OS = "Windows"
        killed = []
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True,
                                  terminate=lambda rec: killed.append(rec.pid))
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertTrue(res.need_force)
        self.assertEqual(killed, [], "Windows 上停止第一步不许杀进程")
        self.assertIn("jenkins", main.load_running_map())

    def test_windows_stop_cleans_stale_record_without_scaring(self):
        """登记还在、端口其实早空了（进程自己死掉过）：Windows 路线要按"已经停了"处理，
        不许回一句"这会打断正在进行的任务，要强制结束吗" —— 端口才是真相（spec §4）。"""
        main.CURRENT_OS = "Windows"
        killed = []
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False,
                                  terminate=lambda rec: killed.append(rec.pid))
        res = mgr.stop(self.comp, self.comps, sleeper=lambda s: None)
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(killed, [], "没在监听就不该走到强杀")
        self.assertEqual(main.load_running_map(), {})
```

`StopFlow.setUp` 还要把 `CURRENT_OS` 钉成 POSIX 值（并在 cleanup 里还原），否则同一份用例在
Windows 与 Linux 上走的是两条不同分支，结果取决于跑测试的机器：

```python
        self._orig_os = main.CURRENT_OS
        main.CURRENT_OS = "Linux"
        self.addCleanup(setattr, main, "CURRENT_OS", self._orig_os)
```

再加一个类，直接钉死默认收尸器的守卫条件（StopFlow 的用例全部注入了 `terminate`，
所以 `_terminate_by_pid` 本体在计划原文里是**零覆盖** —— 把"launcher 就不许动手"整行删掉
测试也不会红。spec §2 说 Nacos/ActiveMQ 的 PID 不可信，这条守卫是"绝不误杀别人进程"的最后防线，
必须有独立用例；这是控制器在派发前的补充裁定。加上评审后按裁定补的 Windows 停止用例与
负 PID 用例，本任务预期用例数为 50（后续 Task 9/10/11 的预期数已同步 +8）：

```python
class TerminateByPidGuard(unittest.TestCase):
    """默认收尸器：只杀我们登记为 server 的 PID，别的一律不动。"""

    def setUp(self):
        self.kills = []
        self._kill = main.os.kill
        self.addCleanup(setattr, main.os, "kill", self._kill)
        main.os.kill = lambda pid, sig: self.kills.append((pid, sig))

    def rec(self, role, pid=43210):
        return main.RunRecord(key="jenkins", version="2.568.3", home="/h", data_dir="/d",
                              port=8080, console_url="http://127.0.0.1:8080/",
                              pid=pid, pid_role=role, started_at=0.0, launcher_cmd=["java"])

    def test_server_pid_gets_sigterm(self):
        main.ServiceManager._terminate_by_pid(self.rec("server"))
        self.assertEqual(self.kills, [(43210, 15)])

    def test_launcher_pid_is_never_killed(self):
        main.ServiceManager._terminate_by_pid(self.rec("launcher"))
        self.assertEqual(self.kills, [], "PID 不可信时不许动手（spec §2）")

    def test_zero_pid_is_never_killed(self):
        main.ServiceManager._terminate_by_pid(self.rec("server", pid=0))
        self.assertEqual(self.kills, [])

    def test_negative_pid_is_never_killed(self):
        """os.kill(-1, …) 在 POSIX 上是"发给所有进程"，登记被手改成负数时绝不能往下传。"""
        main.ServiceManager._terminate_by_pid(self.rec("server", pid=-1))
        main.ServiceManager._terminate_by_pid(self.rec("server", pid=None))
        self.assertEqual(self.kills, [])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`no attribute 'stop'` / `__init__() got unexpected keyword 'terminate'`

- [ ] **Step 3: 写最小实现**

给 `ServiceManager.__init__` 增加注入点 `terminate=None`，默认实现走 PID：

```python
    def __init__(self, is_listening=port_is_listening, http_ok=http_ok,
                 process_alive=process_is_alive, terminate=None):
        self._is_listening = is_listening
        self._http_ok = http_ok
        self._process_alive = process_alive
        self._terminate = terminate or self._terminate_by_pid

    @staticmethod
    def _terminate_by_pid(rec: RunRecord) -> None:
        """只结束我们自己登记过的 PID。

        spec §2 说明 Nacos / ActiveMQ 的 PID 不可信，所以计划二必须走正规
        shutdown 脚本；本期 Jenkins 我们就是服务进程，terminate 才成立。
        非 server 角色一律不动手 —— 这条守卫是"绝不误杀别人进程"的最后防线。"""
        if rec.pid_role != "server" or rec.pid is None or rec.pid <= 0:
            return
        try:
            os.kill(rec.pid, 15)
        except OSError:
            pass
```

再加：

```python
@dataclass
class StopResult:
    ok: bool
    need_force: bool = False
    reason: str = ""


class ServiceManager:
    def stop(self, comp: Component, comps: Dict[str, Component],
             deadline: float = 30.0, sleeper=time.sleep) -> StopResult:
        rec = load_running_map().get(comp.key)
        if rec is None:
            return StopResult(False, reason=f"{comp.display_name} 没有本工具的启动登记，无法确定该停哪个进程。")
        spec = comp.launch
        if spec.stop_kind == "shutdown_command" and spec.shutdown_commands.get(CURRENT_OS):
            # 占位符契约（本期不可达分支，计划二才接线）：这里只喂得出处在 RunRecord 上的三个键，
            # {java}/{war} 这类要另外补来源，否则 format 直接 KeyError。
            argv = [t.format(port=rec.port, home=rec.home, data_dir=rec.data_dir)
                    for t in spec.shutdown_commands[CURRENT_OS]]
            try:
                subprocess.run(argv, cwd=rec.home, timeout=20,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired):
                pass
        elif CURRENT_OS == "Windows":
            # 端口是真相：进程早就没了，就别拿"会打断任务"去吓用户，清登记算它停好了。
            if not self._is_listening(rec.port):
                records = load_running_map()
                records.pop(comp.key, None)
                save_running_map(records)
                return StopResult(True,
                                  reason=f"{comp.display_name} 已经不在监听端口 {rec.port}，登记已清。")
            # Windows 上 os.kill 的任何信号值都是 TerminateProcess —— 那就是强杀本身，
            # 没有"先礼貌停一下"这一步。spec §5 定的是"超时只询问、不自动强杀"，
            # 所以这里绝不动手，直接把决定交给用户（确认后走 force_stop）。
            return StopResult(False, need_force=True,
                              reason=(f"{comp.display_name}（端口 {rec.port}）在 Windows 上只能直接终止进程，"
                                      f"这会打断正在进行的任务、可能丢未落盘的配置。要强制结束吗？"))
        else:
            self._terminate(rec)

        # 与 start() 同一套"有界轮次"约定（main.py 里 start 的注释钉过）：按轮计数、
        # 每轮 sleeper(1.0)、至少探一次。用 deadline 递减做墙钟会在 sleeper 被注入成
        # 短睡时把宽限期静默缩短，no-op 时退化成忙等。
        for _ in range(max(1, int(deadline))):
            if not self._is_listening(rec.port):
                records = load_running_map()
                records.pop(comp.key, None)
                save_running_map(records)
                return StopResult(True, reason=f"{comp.display_name} 已停止，端口 {rec.port} 已释放。")
            sleeper(1.0)
        return StopResult(False, need_force=True,
                          reason=(f"{comp.display_name} 在 {int(deadline)} 秒内没停下来（端口 {rec.port} 仍在听）。"
                                  f"要强制结束这个进程吗？强制结束可能丢未落盘的数据。"))

    def force_stop(self, key: str, sleeper=time.sleep, rounds: int = 5) -> StopResult:
        """用户明确同意后的强制结束。仍然只在"端口确实释放"时才清登记。"""
        rec = load_running_map().get(key)
        if rec is None:
            return StopResult(False, reason="没有登记记录")
        if self._process_alive(rec.pid) and rec.pid_role == "server":
            try:
                os.kill(rec.pid, 9)
            except OSError:
                pass
        # 终止调用返回 ≠ 监听 socket 已关闭：给一个有界复查窗口，
        # 否则刚被我们杀掉的进程会被误报成"别的进程占着端口"。
        for _ in range(max(1, int(rounds))):
            if not self._is_listening(rec.port):
                records = load_running_map()
                records.pop(key, None)
                save_running_map(records)
                return StopResult(True, reason="已强制结束并释放端口。")
            sleeper(1.0)
        return StopResult(False, need_force=True,
                          reason=f"端口 {rec.port} 仍在监听，可能是别的进程占着，不是本工具启动的那个。")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 50 tests ... OK`

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): stop/force_stop —— 超时只询问强制结束，停不成保留登记"
```

**控制器留给后续任务的已知项（本任务不处理，勿静默丢弃）：**
- `force_stop` 在 Windows 上发的是 9：`os.kill` 非 CTRL_* 分支走 `TerminateProcess(handle, code)`，
  9 只成为子进程退出码，语义上该发 15。行为不变，属误导。→ 计划二引入第二个可停组件时一并改，
  并在 `StopFlow` 里补一条 `CURRENT_OS=="Windows"` 的 force 路线用例。
- `stop()` 的 `shutdown_command` 分支本期不可达，占位符契约只给了 `port/home/data_dir` 三键；
  计划二接 Nacos/ActiveMQ 的 `shutdown.cmd` 时若需要 `{java}`/`{war}`，得先在该分支补来源，否则 `format` KeyError。
- `sleeper(1.0)` 与 `deadline/rounds` 轮数绑死：Task 9 的 Worker 若要更细的取消粒度，
  需要在 `stop/force_stop` 里传节拍而不是加参数默认值。

---

### Task 9: `LaunchWorker(QThread)`

**Files:**
- Modify: `main.py`（`DownloadWorker` 附近，`main.py:3460` 之后）
- Test: `bt_launch_tests.py`（追加 `LaunchWorkerSignals`）

**Interfaces:**
- Consumes: `ServiceManager.start/stop/force_stop`、`Component`
- Produces: `class LaunchWorker(QThread)`，信号 `started_ok(str, str)`（key, console_url）、`failed(str, str)`（key, reason）、`stopped(str)`、`need_force(str, str)`（key, reason，"要不要强制结束"的一次询问）；构造参数 `(action, comp, comps, mgr)`，`action ∈ {"start","stop","force_stop"}`；`cancel()` 经 `_sleep` 注入点真能中止等待（Task 11 的 `closeEvent` 要用）；模块级 `LaunchCancelled`

- [ ] **Step 1: 写失败测试**

```python
class LaunchWorkerSignals(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_start_action_emits_started_ok(self):
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        comps = {c.key: c for c in [comp]}
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  http_ok=lambda u, timeout=2.0: True,
                                  process_alive=lambda pid: True)
        rec = main.RunRecord(key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
                             console_url="http://127.0.0.1:8080/", pid=1,
                             pid_role="server", started_at=0.0, launcher_cmd=[])
        mgr.start = lambda c, cs, sleeper=time.sleep: main.StartResult(
            True, "running", record=rec, console_url=rec.console_url)
        w = main.LaunchWorker("start", comp, comps, mgr)
        got = []
        w.started_ok.connect(lambda k, u: got.append((k, u)))
        w._dispatch()      # 不起线程，直接跑分派逻辑：线程本身不是本用例要验的东西
        self.assertEqual(got, [("jenkins", "http://127.0.0.1:8080/")])

    def test_failed_reason_is_emitted_not_swallowed(self):
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)
        mgr.start = lambda c, cs, sleeper=time.sleep: main.StartResult(False, "gate", "需要先装 JDK")
        w = main.LaunchWorker("start", comp, {comp.key: comp}, mgr)
        got = []
        w.failed.connect(lambda k, r: got.append(r))
        w._dispatch()
        self.assertEqual(got, ["需要先装 JDK"])

    def test_unexpected_exception_becomes_failed_not_a_silent_thread(self):
        """start() 会真的动文件系统（建日志目录、开文件、写 running.json），
        这些抛出来说明环境不对。run() 若不接住，线程静默死掉，卡片上的按钮就永远
        停在"进行中"，用户什么也看不见 —— spec §5 要求失败必须可归因。"""
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)

        def boom(c, cs, sleeper=time.sleep):
            raise OSError("磁盘只读")
        mgr.start = boom
        w = main.LaunchWorker("start", comp, {comp.key: comp}, mgr)
        got = []
        w.failed.connect(lambda k, r: got.append(r))
        w.run()                     # 走 run()，验的正是线程入口包不包异常
        self.assertEqual(len(got), 1, "异常必须转成一次 failed，不许静默")
        self.assertIn("磁盘只读", got[0])

    def test_cancel_stops_waiting_without_pretending_the_process_stopped(self):
        """取消只是"别再盯着端口了"，进程可能还在起来 —— 这句话必须原样传给界面。"""
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False,
                                  http_ok=lambda u, timeout=2.0: False,
                                  process_alive=lambda pid: False)

        def slow_start(c, cs, sleeper=time.sleep):
            while True:              # 模拟"一直没监听"：每轮把控制权交给 sleeper
                sleeper(1.0)
        mgr.start = slow_start
        w = main.LaunchWorker("start", comp, {comp.key: comp}, mgr)
        w.cancel()                   # 先取消再跑，第一轮 sleeper 就走取消分支，不会真死循环
        got = []
        w.failed.connect(lambda k, r: got.append(r))
        w.run()
        self.assertEqual(len(got), 1, "取消同样要给一条说明，不许静默结束线程")
        self.assertIn("已取消", got[0])
        self.assertIn("可能仍在启动", got[0])
```

测试文件顶部本 Task 起要补两行：`import time`（上面用例里的 `sleeper=time.sleep` 默认值要用）和
`from PySide6.QtWidgets import QApplication`（要构造 `QThread` 子类，得有 QApplication）。

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`no attribute 'LaunchWorker'`

- [ ] **Step 3: 写最小实现**

```python
class LaunchCancelled(Exception):
    """用户取消等待。不是故障，只是"别再替我盯着端口了"。"""


class LaunchWorker(QThread):
    """启动/停止的耗时动作。有界探活最长能到 startup_timeout 秒，
    绝不能放在 UI 线程里 —— 这正是 DownloadWorker 走线程的同一个理由。"""

    started_ok = Signal(str, str)
    failed = Signal(str, str)
    stopped = Signal(str)
    need_force = Signal(str, str)   # (key, reason)：一次"要不要强制结束"的询问，不是错误

    def __init__(self, action: str, comp: Component,
                 comps: Dict[str, Component], mgr: "ServiceManager", parent=None):
        super().__init__(parent)
        self.action = action
        self.comp = comp
        self.comps = comps
        self.mgr = mgr
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _sleep(self, seconds: float) -> None:
        """取消检查挂在 ServiceManager 的每轮等待上 —— 有界探活是唯一长耗时阶段，
        而它的 sleeper 本来就是注入点，所以不用给它加新参数就能中止。"""
        if self._cancelled:
            raise LaunchCancelled()
        time.sleep(seconds)

    def _dispatch(self) -> None:
        if self.action == "start":
            res = self.mgr.start(self.comp, self.comps, sleeper=self._sleep)
            if res.ok:
                self.started_ok.emit(self.comp.key, res.console_url)
            else:
                self.failed.emit(self.comp.key, res.reason)
        elif self.action == "stop":
            res = self.mgr.stop(self.comp, self.comps, sleeper=self._sleep)
            self._emit_stop(res)
        elif self.action == "force_stop":
            self._emit_stop(self.mgr.force_stop(self.comp.key, sleeper=self._sleep))
        else:
            # 认不出的 action 必须出声：静默返回就是"线程跑完却一个信号都没发"，
            # 卡片会永远停在"进行中" —— 正是下面 run() 兜底要防的那类故障。
            self.failed.emit(self.comp.key, f"{self.comp.display_name} 不支持的操作：{self.action}")

    def _emit_stop(self, res: "StopResult") -> None:
        if res.ok:
            self.stopped.emit(self.comp.key)
        elif res.need_force:
            # 询问走独立信号：混在 failed 的正文里，卡片一时忘了拆前缀，
            # 就会把控制标记当错误正文显示给用户。
            self.need_force.emit(self.comp.key, res.reason)
        else:
            self.failed.emit(self.comp.key, res.reason)

    def run(self) -> None:
        try:
            self._dispatch()
        except LaunchCancelled:
            # 取消只是停止"等"，进程还在不在没人知道 —— 这话必须说清，
            # 否则用户以为取消等于停住了。
            self.failed.emit(self.comp.key,
                             "已取消等待。进程可能仍在启动中，稍后看状态或再点停止。")
        except Exception as exc:
            self.failed.emit(self.comp.key, f"{self.comp.display_name} 操作过程出错：{exc}")
```

`need_force` 是独立信号，不是 `failed` 正文里的前缀标记（计划初稿用的是 `__need_force__\t` 前缀，
Task 9 评审后由控制器改判）：那条约定要求卡片必须记得先拆前缀，忘了就把控制标记当错误显示出来；
多一条要接的线换来的正是"忘了接也不会显示错东西"。Task 10 连 `need_force` 弹询问框。

`cancel()` 必须真的有用（计划初稿里 `_cancelled` 没人读，是死字段）：Task 11 的 `MainWindow.closeEvent`
要对在跑的 worker 先 `cancel()` 再 `wait()`，否则窗口关了线程还在探端口。上面那条 `_sleep` 就是这条链的落点。


- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 57 tests ... OK`

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): LaunchWorker 线程层，失败原因与强制结束询问都走信号"
```

---

### Task 10: `ComponentCard` 按钮排与状态文本

**Files:**
- Modify: `main.py`（按钮区，`btn_uninstall` 之后 —— 现 `main.py:5531`）
- Modify: `main.py`（`_detect_status` 现 `main.py:5669`；状态胶囊写点现 `5565/5579/5719/5798/5810`）
- Modify: `main.py`（`on_uninstall_clicked` 现 `main.py:6119`，加互斥）
- Modify: `main.py`（`ServiceManager` 类之后加模块级单例；`MainWindow` 现 `main.py:6511`）
- Test: `bt_launch_tests.py`（追加 `CardLaunchUi`）

> 行号会随任务推进漂移（计划起草时这批锚点还都在 4900-5500 段）。**按符号名定位，行号只当起点。**

**Interfaces:**
- Consumes: `ServiceManager`、`LaunchWorker`、`main.SERVICE_MANAGER`（本 Task 新增模块级单例）
- Produces: `ComponentCard.btn_start / btn_stop / btn_console`、`ComponentCard._refresh_launch_state()`、`ComponentCard.on_start_clicked()`、`on_stop_clicked()`、`on_console_clicked()`

- [ ] **Step 1: 写失败测试**

```python
class CardLaunchUi(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig)
        # 下面两条用例会直接改模块单例的探针。不还原的话，"_is_listening 永远真"
        # 会漏给同一进程里后跑的任何类 —— 别的用例就在猜这台机器有没有在听了。
        self._orig_listen = main.SERVICE_MANAGER._is_listening
        self.addCleanup(setattr, main.SERVICE_MANAGER, "_is_listening", self._orig_listen)
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        self.card = main.ComponentCard(comp, lambda msg, level: None)

    def test_launch_buttons_exist_only_for_launchable_components(self):
        self.assertTrue(hasattr(self.card, "btn_start"))
        other = next(c for c in main.build_components() if c.key == "maven")
        card2 = main.ComponentCard(other, lambda msg, level: None)
        self.assertFalse(hasattr(card2, "btn_start"), "非白名单组件不许长出启动按钮")

    def test_running_state_disables_start_and_enables_stop_and_console(self):
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="http://127.0.0.1:8080/", pid=1, pid_role="server",
            started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": True
        self.card._refresh_launch_state()
        self.assertFalse(self.card.btn_start.isEnabled())
        self.assertTrue(self.card.btn_stop.isEnabled())
        self.assertTrue(self.card.btn_console.isEnabled())
        self.assertIn("运行中", self.card.launch_label.text())
        self.assertIn("8080", self.card.launch_label.text())

    def test_launch_state_does_not_touch_the_existing_capsule(self):
        """状态胶囊有 5 处写点（现 main.py:5565/5579/5719/5798/5810），
        把运行状态挤进去会把既有胶囊逻辑搅浑，所以它只写自己那个 label。"""
        before = self.card.status_label.text()
        self.card._refresh_launch_state()
        self.assertEqual(self.card.status_label.text(), before)

    def test_stopped_state_enables_start_and_disables_console(self):
        main.save_running_map({})
        self.card._refresh_launch_state()
        self.assertTrue(self.card.btn_start.isEnabled())
        self.assertFalse(self.card.btn_console.isEnabled())

    def test_uninstall_is_blocked_while_running(self):
        """spec §5：运行中禁止卸载，避免"边跑边删目录"。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="u", pid=1, pid_role="server", started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER._is_listening = lambda p, host="127.0.0.1": True
        self.card._refresh_launch_state()
        self.assertFalse(self.card.btn_uninstall.isEnabled())
        self.assertIn("先停止", self.card.btn_uninstall.toolTip())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`'ComponentCard' object has no attribute 'btn_start'`

- [ ] **Step 3: 写最小实现**

模块级单例（放 `ServiceManager` 定义之后）：

```python
SERVICE_MANAGER = ServiceManager()
```

卡片要点停止就得能拿到别的组件（Jenkins 要看 JDK 装了没），所以下面这段**原属 Task 11，
按裁定 F1 提前到本任务**，否则 Task 10 引用一个还不存在的 `staticmethod`：

```python
class MainWindow(QMainWindow):
    ...
    _COMPONENTS_CACHE: Dict[str, "Component"] = {}

    @staticmethod
    def current_components() -> Dict[str, "Component"]:
        """只读的组件表：卡片的启动/停止要用别的组件（needs 判定），
        但不该每张卡片自己再 build_components() 一次。"""
        if not MainWindow._COMPONENTS_CACHE:
            MainWindow._COMPONENTS_CACHE = {c.key: c for c in build_components()}
        return MainWindow._COMPONENTS_CACHE
```

Task 11 因此只剩 `_adopt_running()` 与 `__init__` 接线，不再定义这个方法。

`ComponentCard._build_ui` 里 `mid.addWidget(self.btn_uninstall)` 之后追加：

```python
        # 启动相关按钮：只有登记了启动描述符的组件才有（LAUNCH_KEYS，本期只有 Jenkins）
        self.launch_worker: Optional[LaunchWorker] = None
        if self.component.launch is not None:
            self.btn_start = QPushButton("启动")
            self.btn_start.setObjectName("primaryBtn")
            self.btn_start.setCursor(QCursor(Qt.PointingHandCursor))
            self.btn_start.setFixedHeight(34)
            self.btn_start.clicked.connect(self.on_start_clicked)
            mid.addWidget(self.btn_start)

            self.btn_stop = QPushButton("停止")
            self.btn_stop.setFixedHeight(34)
            self.btn_stop.clicked.connect(self.on_stop_clicked)
            self.btn_stop.setEnabled(False)
            mid.addWidget(self.btn_stop)

            self.btn_console = QPushButton("打开控制台")
            self.btn_console.setFixedHeight(34)
            self.btn_console.clicked.connect(self.on_console_clicked)
            self.btn_console.setEnabled(False)
            mid.addWidget(self.btn_console)

            # 运行状态自己一个小 label：status_label 已有 5 处写点，挤进去会把
            # 多版本胶囊 / 系统安装 那套判定搅浑（R3.9 要求非目标组件零影响）。
            self.launch_label = QLabel("")
            self.launch_label.setObjectName("launchLabel")
            mid.addWidget(self.launch_label)
```

新增三个槽函数与状态刷新：

```python
    def _launch_status(self):
        return SERVICE_MANAGER.status(self.component.key, self.component)

    def _refresh_launch_state(self) -> None:
        """按端口实况刷新按钮与胶囊。本方法只读，一次都不许拉起进程。"""
        if self.component.launch is None:
            return
        st = self._launch_status()
        running = st.state == "running"
        self.btn_start.setEnabled(not running and self.launch_worker is None)
        self.btn_stop.setEnabled(running)
        self.btn_console.setEnabled(running)
        if running:
            self.launch_label.setText(f"● 运行中 · 端口 {st.record.port}")
            # 运行中禁止卸载：边跑边删目录会把正在写的日志和数据留在半删状态
            self.btn_uninstall.setEnabled(False)
            self.btn_uninstall.setToolTip("请先停止运行中的 %s 再卸载" % self.component.display_name)
        else:
            self.launch_label.setText("")
            self.btn_uninstall.setEnabled(True)
            self.btn_uninstall.setToolTip("删除已安装的版本、清理 XXX_HOME 与 PATH")

    def on_start_clicked(self) -> None:
        spec = self.component.launch
        reply = QMessageBox.question(
            self, "确认启动 %s" % self.component.display_name,
            "端口：%d（被占用时会自动往后找空闲口）\n%s\n\n确认启动？"
            % (spec.main_port, spec.risk_note),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return
        self.btn_start.setEnabled(False)
        self.launch_worker = LaunchWorker("start", self.component,
                                          MainWindow.current_components(), SERVICE_MANAGER)
        self.launch_worker.started_ok.connect(self._on_launch_ok)
        self.launch_worker.failed.connect(self._on_launch_failed)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    def _on_launch_ok(self, key: str, console_url: str) -> None:
        self._log("info", f"已启动，控制台：{console_url}")
        self._refresh_launch_state()

    def _on_launch_failed(self, key: str, reason: str) -> None:
        self._log("error", f"操作失败：{reason}")
        QMessageBox.warning(self, "操作失败", reason)
        self._refresh_launch_state()

    def _on_need_force(self, key: str, reason: str) -> None:
        """停止超时/无法优雅结束：问一次，不自己决定强杀（spec §5）。"""
        if QMessageBox.question(self, "需要强制结束", reason,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            self._log("warn", "未强制结束，进程仍在运行。")
            return
        self.launch_worker = LaunchWorker("force_stop", self.component,
                                          MainWindow.current_components(), SERVICE_MANAGER)
        self.launch_worker.stopped.connect(self._on_launch_stopped)
        self.launch_worker.failed.connect(self._on_launch_failed)
        self.launch_worker.need_force.connect(self._on_need_force)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    def _on_launch_stopped(self, key: str) -> None:
        self._log("info", "已停止。")
        self._refresh_launch_state()

    def _on_launch_worker_done(self) -> None:
        self.launch_worker = None
        self._refresh_launch_state()

    def on_stop_clicked(self) -> None:
        self.btn_stop.setEnabled(False)
        self.launch_worker = LaunchWorker("stop", self.component,
                                          MainWindow.current_components(), SERVICE_MANAGER)
        self.launch_worker.stopped.connect(self._on_launch_stopped)
        self.launch_worker.failed.connect(self._on_launch_failed)
        # 这条线不能省：停不下来时 need_force 就是"问一次"的唯一入口，
        # 漏接了按钮会直接停在"停止中"结束、用户既没被问也没结果。
        self.launch_worker.need_force.connect(self._on_need_force)
        self.launch_worker.finished.connect(self._on_launch_worker_done)
        self.launch_worker.start()

    def on_console_clicked(self) -> None:
        st = self._launch_status()
        if st.record is not None:
            QDesktopServices.openUrl(QUrl(st.record.console_url))
```

`_detect_status()` 末尾加一行 `self._refresh_launch_state()`。日志入口用卡片已有的 `self._log(level, msg)`（现 `main.py:5552`，内部再转 `log_cb`），级别只用现有那三种：`info` / `warn` / `error`（`MainWindow._append_log` 在现 `main.py:7366`，全仓库现用的就是这三个值）。

spec §5 里"端口是被本工具自己起的进程占着 → 提供停掉它再重试"这一条，由这里自然成立：`_refresh_launch_state()` 认出运行中后，「启动」变灰而「停止」可点，用户点停止即释放端口，再点启动。不需要额外弹窗，也不需要在 `start()` 里偷偷停别人。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 71 tests ... OK`
（不是本任务正文里那 5 条：初稿的 62 与"未测的接线要补用例"这条要求不能同时成立。
实现者补 5 条守护用例到 67，评审轮又补 4 条（QThread 两条删除窗口 ×2、`_sync_action_buttons` 锁、
zombie 可见性）到 71。后续任务的预期数已按 71 起算。）

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(ui): 组件卡片启动/停止/打开控制台按钮，运行中锁卸载"
```

---

### Task 11: `MainWindow` 接运行状态与组件表访问

**Files:**
- Modify: `main.py:5903` 附近（`MainWindow`）
- Test: `bt_launch_tests.py`（追加 `MainWindowAdopt`）

**Interfaces:**
- Consumes: `SERVICE_MANAGER.reconcile`、`build_components`
- Produces: `MainWindow._adopt_running()`；`MainWindow.current_components()` 由 Task 10 交付（裁定 F1 提前），本任务只消费

- [ ] **Step 1: 写失败测试**

```python
class MainWindowAdopt(unittest.TestCase):
    """这一层的用例一律不构造真 MainWindow：`MainWindow.__init__` 会建 26 张卡片、
    起版本探测线程，把宿主机网络和 Qt 生命周期都拖进来。用 `__new__` 拿到一个未初始化的实例、
    只补这个方法真正用到的成员，才是本任务这一层的可测形状。

    控制器已在 offscreen 下实测过这个形状：`MainWindow.__new__` 出来的对象可以正常赋 Python 属性
    （`_append_log`、`cards`、甚至**遮蔽** `findChildren`），`current_components()` 这种 staticmethod
    也能通过它调用；但凡碰真的 Qt 方法（如未遮蔽的 `findChildren`）就抛
    `RuntimeError: '__init__' method of object's base class not called`。
    所以 `_cancel_launch_workers` 用注入的 findChildren 测；`closeEvent` 本身测不了（要调 super），
    它只有"调一次 _cancel_launch_workers 再交给 Qt"这一行，如实说明即可，不要为了测它去构造真窗口。"""

    def bare_win(self, logs):
        win = main.MainWindow.__new__(main.MainWindow)
        win._append_log = lambda level, msg: logs.append((level, msg))
        win.cards = []          # _adopt_running 收尾要遍历卡片重读实况；没卡片也得有个空表
        return win

    def setUp(self):
        self.calls = []
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self._orig_file = main.RUNNING_FILE
        main.RUNNING_FILE = Path(self.dir.name) / "running.json"
        self.addCleanup(setattr, main, "RUNNING_FILE", self._orig_file)
        self._orig_mgr = main.SERVICE_MANAGER
        self.addCleanup(setattr, main, "SERVICE_MANAGER", self._orig_mgr)
        # 找回路径"绝不执行进程"要有牙齿：任何 Popen 都要留下证据
        self._orig_popen = main.subprocess.Popen
        main.subprocess.Popen = lambda *a, **k: self.calls.append(a)
        self.addCleanup(setattr, main.subprocess, "Popen", self._orig_popen)

    def test_current_components_covers_whitelist(self):
        got = main.MainWindow.current_components()
        self.assertTrue(main.LAUNCH_KEYS.issubset(set(got)), "启动白名单组件必须能在卡片间互相看见（needs 判定要用）")

    def test_adopt_running_drops_zombies_without_touching_processes(self):
        """僵尸（登记在、端口没在听）必须被清掉，而且整个过程一次进程都不许起。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8080,
            console_url="u", pid=1, pid_role="server", started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": False,
            http_ok=lambda u, timeout=2.0: False, process_alive=lambda pid: True)
        logs = []
        self.bare_win(logs)._adopt_running()
        self.assertEqual(main.load_running_map(), {})
        self.assertEqual(self.calls, [], "找回过程拉起了进程")
        self.assertEqual(logs, [], "僵尸不该被报成"检测到正在运行"")

    def test_adopt_running_reports_what_it_found_running(self):
        """开工具时如果 Jenkins 还在跑，日志要认出它 —— 这是"关掉了再打开也认得"那条判据。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="x", home="/h", data_dir="/d", port=8123,
            console_url="http://127.0.0.1:8123/", pid=1, pid_role="server",
            started_at=0.0, launcher_cmd=[])})
        main.SERVICE_MANAGER = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": True,
            http_ok=lambda u, timeout=2.0: True, process_alive=lambda pid: True)
        logs = []
        self.bare_win(logs)._adopt_running()
        self.assertEqual([m for _, m in logs], ["检测到 jenkins 正在运行（端口 8123）"])
        self.assertIn("jenkins", main.load_running_map(), "在跑的登记不许被清掉")

    def test_adopt_running_re_syncs_every_card_after_cleaning(self):
        """_adopt_running 会把僵尸登记删掉，而卡片可能在它跑之前就已经把"残留登记"画出来了。
        不清一遍卡片就会在窗口里留一句假警告，直到用户碰别的什么东西才刷新。"""
        refreshed = []

        class FakeCard:
            def _refresh_launch_state(self):
                refreshed.append(True)

        main.SERVICE_MANAGER = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": False,
            http_ok=lambda u, timeout=2.0: False, process_alive=lambda pid: False)
        win = self.bare_win([])
        win.cards = [FakeCard(), FakeCard(), FakeCard()]
        win._adopt_running()
        self.assertEqual(len(refreshed), 3, "认清本机之后每张卡片都要重读一次实况")

    def test_close_cancels_then_waits_every_in_flight_worker(self):
        """Task 9 的 cancel 落点：关窗口时先给每个在跑的 worker 一次体面退出，
        不是把线程连同 QThread 一起扔了（cancel 只停止"等端口"，不动别人的进程）。"""
        done = []

        class FakeWorker:
            def cancel(self):
                done.append("cancel")
            def wait(self, ms):
                done.append(("wait", ms))

        win = self.bare_win([])
        win.findChildren = lambda cls: [FakeWorker(), FakeWorker()]
        self.assertEqual(win._cancel_launch_workers(), 2)
        self.assertEqual(done, ["cancel", "cancel", ("wait", 2000), ("wait", 2000)],
                         "必须先全部 cancel 再 wait，否则第二个 worker 要白等第一个的超时")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: FAIL，`'MainWindow' object has no attribute '_adopt_running'`（第二条用例）。
（`test_current_components_covers_whitelist` 这时应当**已经通过** —— 那个方法按裁定 F1 在 Task 10 就落地了，
本任务只是它的第一次跨卡片回归断言。若它红，说明 Task 10 漏交付，回去补 Task 10，不要在这里重定义。）

- [ ] **Step 3: 写最小实现**

`MainWindow` 内加（`current_components()` 已在 Task 10 交付，这里**不要重复定义**）：

```python
    def _adopt_running(self) -> None:
        """启动后一次性的"认清本机在跑什么"。只读 + 清僵尸，绝不拉起进程。"""
        states = SERVICE_MANAGER.reconcile(self.current_components())
        for key, st in states.items():
            if st.state == "running":
                self._append_log("info", f"检测到 {key} 正在运行（端口 {st.record.port}）")
        # reconcile 可能刚把僵尸登记删掉：卡片在那之前已经画过一遍了，必须让它们重读，
        # 否则窗口里会留一句已经没有依据的"残留登记"。
        for card in self.cards:
            card._refresh_launch_state()

    def _cancel_launch_workers(self) -> int:
        """关窗口前让在跑的启动/停止线程体面收尾：只取消"还在等端口"，不动被管理的进程。
        先全部 cancel 再统一 wait —— 反过来写，后一个 worker 要白等前一个的超时。"""
        workers = self.findChildren(LaunchWorker)
        for w in workers:
            w.cancel()
        for w in workers:
            w.wait(2000)
        return len(workers)

    def closeEvent(self, event) -> None:
        self._cancel_launch_workers()
        super().closeEvent(event)
```

在 `MainWindow.__init__` 建完卡片之后调用一次 `self._adopt_running()`，并把每个卡口的 `_refresh_launch_state()` 接进去（卡片在 `__init__` 末尾自己会调，`_detect_status` 已含）。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 76 tests ... OK`

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(ui): 打开工具时认清本机运行中的组件（只读找回 + 清僵尸）"
```

---

### Task 12: 真机演练 `--launch`（Windows 验收）

**Files:**
- Modify: `bt_real_machine_drill.py`（`main_drill` 现在 `:178`；参数解析在 `:26-27` ——
  `APPLY_FLAG = "--yes" in sys.argv` 之后立刻 `sys.argv = [sys.argv[0]]` 把参数清掉，
  所以 `--launch <key>` 必须和 `APPLY_FLAG` 一样在清 argv **之前**取走，否则永远读不到）
- Modify: 脚本开头的用法说明（`:3-5`）
- Create: 演练结果记录小节追加到 spec 的 §2.4

**Interfaces:**
- Consumes: `SERVICE_MANAGER.start/stop/force_stop`、`ComponentCard` 之外的无 UI 路径
- Produces: `bt_real_machine_drill.py --launch <key> [--yes]` —— **沿用本脚本既有的 `--yes` 表示"真动手"**，
  不要再造一个 `--apply`：一个脚本两套"要不要真做"的开关，迟早有人只传对一个。

- [ ] **Step 1: 加失败判据（脚本内断言，不是单测）**

在 `bt_real_machine_drill.py` 里新增：

```python
def launch_drill(comp_key: str, apply: bool) -> int:
    """三层判据（沿用本脚本既有风格）：拉得起 → 端口在听且控制台给 2xx → 停得干净。

    单元测试证明的是逻辑对，这一层证明真机器上真能跑（R3.16 的教训）。
    """
    comps = {c.key: c for c in main.build_components()}
    comp = comps[comp_key]
    if not apply:
        print(f"[dry-run] 将启动 {comp.display_name}，随后停止；数据留在 {comp.install_dir(comp.versions[0].version)}")
        return 0
    res = main.SERVICE_MANAGER.start(comp, comps)
    if not res.ok:
        print("启动失败：", res.reason)
        return 1
    rec = res.record
    got = main.http_ok(rec.console_url.rstrip("/") + "/login")
    print(f"[1/3] 已启动 pid={rec.pid}({rec.pid_role}) port={rec.port} 控制台可达={got}")
    stop = main.SERVICE_MANAGER.stop(comp, comps)
    if not stop.ok and stop.need_force:
        # Windows 上 stop 第一步只请示、不动手（Task 8 裁定 1）。演练里这一票由脚本替
        # 用户点"是"，否则一条按设计走通的路径会被判成失败。
        print("[2/3] 停止需要确认，演练按「是」继续：", stop.reason)
        stop = main.SERVICE_MANAGER.force_stop(rec.key)
    left = main.load_running_map()
    print(f"[2/3] 停止 ok={stop.ok} 需强制={stop.need_force} reason={stop.reason}")
    print(f"[3/3] 登记残留={list(left)}")
    if not stop.ok or rec.key in left:
        return 1
    return 0
```

参数解析照 `APPLY_FLAG` 的现成写法，在清 argv 之前取（`:26` 之后、`:27` 之前）：

```python
APPLY_FLAG = "--yes" in sys.argv   # 必须在清 argv 之前取，否则演练模式永远进不去
LAUNCH_KEY = sys.argv[sys.argv.index("--launch") + 1] if "--launch" in sys.argv else None
sys.argv = [sys.argv[0]]           # 别让 main.py 的 argparse/入口看到本脚本的参数
```

入口相应改成：`LAUNCH_KEY` 非空时走 `launch_drill(LAUNCH_KEY, APPLY_FLAG)`，
为空时保持现有 `main_drill(APPLY_FLAG)` 不变；`--launch` 跟一个不认识的 key 要直接报错退出，
不要静默走回原路径。脚本开头的用法说明补一行。

- [ ] **Step 2: 干跑一次，确认脚本不碰进程（这一条是本任务的**通过判据**）**

Run: `.venv/Scripts/python.exe bt_real_machine_drill.py --launch jenkins`
Expected: 只打印 `[dry-run]`，`tasklist` 里没有 java 进程新增。
**dry-run 必须真跑通并作为验收**；`--yes` 那一层要求本机已装 JDK + Jenkins 两个组件（会走下载解压），
还要面对 Jenkins 首次解锁向导 —— 组件没装齐就如实报"需要用户在场验证"，**绝不把没跑的东西记成通过**。

- [ ] **Step 3: 真机执行（Windows，需用户在旁边）**

Run: `.venv/Scripts/python.exe bt_real_machine_drill.py --launch jenkins --yes`
Expected: 三行判据全过，末行 `登记残留=[]`。同时记录 spec §2.4 的三项结论：
Jenkins `--httpPort` 是否生效、初始管理员密码文件的确切路径、Jenkins 要求的 JDK 最低大版本。

- [ ] **Step 4: 把实测结论回写文档**

用实测值替换 spec 的 §2.4 第 3、5 项，并把 `LAUNCH_OF["jenkins"].min_java_major` 从 `None` 改成实测到的数字（**只有拿到实测结论才改**），同步补一条 `bt_launch_tests.py` 断言。

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add bt_real_machine_drill.py main.py docs/superpowers/specs/2026-10-05-one-click-launch-design.md bt_launch_tests.py
git commit -m "test(drill): 新增 --launch 三层判据演练；按 Windows 实测回填 Jenkins JDK 门槛"
```

---

### Task 13: 文档与规则同步

**Files:**
- Modify: `CODE_WIKI.md`（§2 架构图、§3 目录结构、§4.6 业务逻辑层、§4.7 UI 层、§5.4 信号槽图、§8.2 后新增一节启动能力、§10 约束）
- Modify: `DEVELOPMENT.md`（新增规则 R5：组件一键启动契约；规则索引补一行；把"后续规则占位"的 R5 去掉）
- Modify: `README.md` / `README_EN.md`（功能特性加一条。Jenkins 那句"用户需自行 java -jar 启动"的旧说明要改掉 ——
  实测位置是 `main.py:3346-3363` 那段注释与 `unsupported_platform_hint`（计划起草时在 3283，前面的任务把它推下去了），
  改文案时**按 `jenkins` 这个 Component 找，别按行号**；README 侧同步）

**Interfaces:**
- Consumes: 前 12 个 Task 的成果
- Produces: 文档与代码一致

- [ ] **Step 1: 写 R5 规则**

`DEVELOPMENT.md` 新增（结构照 R4：描述/适用范围/硬约束/失败处理/checklist/护栏用例）：

```markdown
## 规则 R5：组件一键启动契约

### R5.1 规则描述
可启动组件（登记表 LAUNCH_OF）必须做到：点启动就真的能访问控制台；端口是真相、PID 是提示；
状态检测与找回绝不执行启动脚本；停止超时只询问强制结束；运行中禁止卸载。

### R5.2 适用范围
- LAUNCH_KEYS 里的组件。当前为 {"jenkins"}，计划二再加 activemq / nacos。
- 不在白名单的组件不得出现启动按钮，也不得被 ServiceManager 写入登记。

### R5.3 硬约束
1. `LAUNCH_OF` 是唯一登记处；`build_components()` 末尾统一赋值，构造处不手写。
2. `min_java_major` 只能填实测结论；未实测保持 None，门控退化为"有没有 JDK"。
3. 端口选择走 `pick_free_cluster`：区间内升序、整簇同时空闲。
4. `status/adopt/reconcile` 只允许 socket + urllib；出现 Popen/_probe_version 调用即视为回归。
5. 脱离进程必须重定向 stdout/stderr 到组件 data 下，失败原因要带日志尾巴。
6. 停不下来时返回 need_force，由界面问人；未确认不得强杀，也不得清登记。
7. `JAVA_HOME` 优先取本工具装的 JDK，其次才退到环境变量。

### R5.4 checklist（新增一个可启动组件）
- [ ] 在 LAUNCH_OF 登记；三平台 commands 都非空（未在真机验证的分支要写明）
- [ ] 决定端口策略：只命令行 flag（本期）还是要回写配置文件（回写必须锚定官方默认那一行 + 备份 + 幂等）
- [ ] 决定 stop_kind：优先正规 shutdown 脚本；只有我们自己是服务进程时才用 pid
- [ ] 补 risk_note（监听地址、默认凭据、首次向导）
- [ ] 加表完整性用例 + 真机演练 --launch <key>
```

- [ ] **Step 2: 同步 CODE_WIKI 与 README**

CODE_WIKI：在架构图里加一层"生命周期层（ServiceManager / LaunchSpec / running.json）"；目录结构里 `bt_launch_tests.py` 补一行；§4.6 表格加 `ServiceManager` / `build_launch_plan` / `pick_free_cluster` 三个条目；新增一节讲"一键启动的数据流"。README 功能特性加"中间件一键启动 + 打开控制台（当前支持 Jenkins）"，并把 `main.py:3283` 与 Jenkins 卡片里"用户需自行用 java -jar 启动"的旧说法改成"已可一键启动"。

- [ ] **Step 3: 全量回归**

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_launch_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_boot_script_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_startup_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_gitee_sync_tests.py
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_multiversion_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_component_category_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_mirror_spec_tests.py
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_search_and_newcmp_tests.py
```

Expected: 全部 `OK`（`bt_multiversion` 那条需 `PYTHONIOENCODING=utf-8`，是既有债，不修）。

- [ ] **Step 4: 变异测试护栏自检**

临时把 `NoExecInvariant` 里的 `adopt` 路径改成调用一次 `subprocess.Popen`，确认用例变红；再临时把 `min_java_major` 填成 `17`，确认表完整性用例变红（因为 spec §2.4 尚未实测）。两处都恢复。

- [ ] **Step 5: 输出提交命令（由用户执行）**

```bash
git add CODE_WIKI.md DEVELOPMENT.md README.md README_EN.md main.py
git commit -m "docs: 规则 R5（组件一键启动契约）与 README/CODE_WIKI 同步"
```

---

## 完成定义（计划一）

spec §8 的第 1、2、4、5 项在 Jenkins 上全部达成：点启动 → 卡片显示"运行中 · 实际端口" → 打开控制台拿到 Jenkins 页面 → 停止 → 端口释放；关掉 byte-tools 再打开能正确识别运行状态且不重复拉起；8080 被占时自动落到空闲口且界面链接跟着实际端口；§2.4 相关实测项有结论并回写；`bt_launch_tests.py` 全绿且经变异测试确认非空护栏；其余 7 套件仍全绿。
