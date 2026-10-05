# 一键启动 计划二（ActiveMQ + Nacos）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 ActiveMQ 与 Nacos 在组件卡片上做到"点启动→整簇端口在听→打开控制台可进→停止→整簇端口释放"，并在不修改任何厂商官方文件的前提下解决端口占用。

**Architecture:** 沿用计划一的三层结构。决策层 `LaunchSpec` 增三个字段（端口策略 `port_writeback`、独立端口 `extra_ports`、额外环境变量 `extra_env`）；生命周期层新增两个不依赖 Qt 的纯函数模块（`netstat` 端口归属解析、ActiveMQ conf 副本幂等回写），`ServiceManager` 把"按单口"改成"按端口簇"；UI 与线程层不变，仅卡片文案与登记结构跟进。持久层 `RunRecord` 增加带默认值的 `ports` 字段，归一化发生在加载侧。

**Tech Stack:** Python 3.10–3.14、PySide6 6.11（仅 UI 层）、标准库 `socket`/`subprocess`/`shutil`/`re`/`json`/`pathlib`；测试为仓库既有的离线 `unittest` 脚本风格（`bt_launch_tests.py`）。

**Spec:** `docs/superpowers/specs/2026-10-05-launch-activemq-nacos-design.md`（本文 args 的依据；两份文件一起交给执行者，冲突时以 spec 为准）
**前置计划：** `docs/superpowers/plans/2026-10-05-launch-jenkins-framework.md`（计划一，已落地于 `dev`@`9d1ba00`）

## Global Constraints

- 启动白名单本期扩为 **三个**：`LAUNCH_KEYS == {"jenkins", "activemq", "nacos"}`，**不得再多**。RocketMQ / Kafka / Pulsar / ActiveMQ 之外的 MQ、以及 Seata/Nacos 以外的服务发现组件，都不在本期。
- **端口是真相，PID 只是提示**：任何"运行中"判定必须满足"登记的簇内每个口都在听"；`pid_role` 只用于选择停止手段。
- **状态检测与找回绝不执行任何进程**：`status()` / `adopt()` / `reconcile()` 只允许 `socket`（+ 现有 `urllib`）。**端口反查（`netstat -ano`）只允许出现在 `stop()` / `force_stop()`**——它是一次子进程调用，出现在检测路径即视为回归。
- **绝不结束我们没登记过的进程**：`_terminate_by_pid` 对 `pid_role != "server"` 的拒绝守卫不得绕过；端口反查动手前必须过三重闸（有我们登记 + 不是我们自己 + 用户已在 `need_force` 上确认）。
- **不修改厂商官方文件**：Nacos 走 `--server.port` 命令行透传；ActiveMQ 的回写只发生在 `~/.env-tools/activemq-data/conf` 副本内。
- **不新增第三方依赖**（禁 psutil 等）；**不碰 WMI / `platform.*`**（`bt_startup_tests.py` 护栏继续有效）；**不为测试在产品代码里加开关**。
- `min_java_major` 只能填有证据的值：本期 `activemq=17`（`bin/activemq.jar` 字节码 class major 61）、`nacos=8`（`nacos-server.jar` 内 `Nacos.class` class major 52），**Jenkins 继续 `None`**（未实测）。
- `RunRecord` **新增字段必须带默认值**，且默认值能从已有字段推出（`ports` 缺省 `()`，加载侧归一为 `(port,)`）。违反即会让旧 `running.json` 整批静默清空。
- 注释、docstring、面向用户的文案一律中文。`main.py` 索引内是 LF、工作区因 `core.autocrlf=true` 显示 CRLF，属正常，不要为行尾改文件。
- 测试绝不真起中间件、不写真注册表、不改用户 shell rc、不弹真对话框；拉起进程一律打桩，探针通过参数注入，**测试不得依赖宿主机环境**（`JAVA_HOME`、已装 JDK、真实监听端口、真实进程、宿主 `CURRENT_OS`）。
- 运行测试统一：`QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py [ClassName]`（Windows / Git Bash；Python 不在 PATH 上，用 `.venv/Scripts/python.exe`）。
- **行号会漂**：本文给出的 `main.py:NNNN` 是 2026-10-05 写计划时的实测位置，只当起点用，**按符号名定位**。前九个任务曾把文件推高约 500 行。
- **git 约定（与计划一账本一致，覆盖仓库旧约定）**：每个 Task 的实现者**自己 commit 到 `dev`**（任务评审要靠 `BASE..HEAD` 的 diff，不逐 Task 提交就没有可评审的东西）；**一律不 push、不 merge、不打 tag**——那三步由用户在会话层面单独授权。不执行删除类 shell 命令。

---

## 文件结构（本期改动面）

| 文件 | 责任 | 本期动作 |
|---|---|---|
| `main.py` | 唯一产品文件 | 改：`LaunchSpec`（+3 字段）、`LAUNCH_OF`（+2 登记）、`RunRecord`/`load_running_map`（`ports` 与归一化）、新增 `parse_netstat_listeners` / `pids_listening_on`、新增 conf 副本与回写三函数、`ServiceManager.status/reconcile/start/stop/force_stop` 改按簇、`build_launch_plan` 按 `port_writeback` 分派、卡片簇文案与卸载告知 |
| `bt_launch_tests.py` | 一键启动离线护栏（现 80 用例） | 追加 6 个测试类，本期结束约 118 用例（数字按实际数出来写报告，不许凑） |
| `bt_real_machine_drill.py` | 真机演练 | 扩 `launch_drill`：按簇判据 + A1–A7 记录 |
| `DEVELOPMENT.md` | 规则 R5 | 更新 R5.2/R5.3/R5.6（本期把多条"待办"变成"已做"） |
| `CODE_WIKI.md` / `README*.md` | 文档 | 补两个组件、簇语义、端口释放判据 |

**新增纯函数一律放在 `main.py` 既有启动层内**（`LaunchSpec` 之后、`ServiceManager` 之前），保持"决策纯函数 → ServiceManager 执行 → Qt 只粘合"的分层，不新开文件（单文件形态是仓库既有约定）。

---

### Task 1: `LaunchSpec` 扩三字段（带默认值，旧登记零改动）

**Files:**
- Modify: `main.py:2975-3005`（`class LaunchSpec`，按符号定位）
- Test: `bt_launch_tests.py`（在 `LaunchSpecTable` 类内追加方法；该类现 5 用例）

**Interfaces:**
- Consumes: 既有 `LaunchSpec` 字段
- Produces: `LaunchSpec.port_writeback: str = "cli_only"`（`"cli_only" | "cli_flag" | "conf_copy"`）、`LaunchSpec.extra_ports: tuple = ()`、`LaunchSpec.extra_env: Dict[str, str] = field(default_factory=dict)`。后续 Task 4/6/7 依赖这三个名字，**不得改名**。

- [ ] **Step 1: 写失败测试**

在 `bt_launch_tests.py` 的 `LaunchSpecTable` 类内追加（保持在 `if __name__ == "__main__": unittest.main()` 之前）：

```python
    def test_plan_two_fields_default_to_plan_one_behaviour(self):
        """新字段必须带默认值且默认就是计划一 Jenkins 的既有行为，
        这样 Jenkins 的登记不用改一个字——本期不该动它。"""
        spec = main.LAUNCH_OF["jenkins"]
        self.assertEqual(spec.port_writeback, "cli_only")
        self.assertEqual(tuple(spec.extra_ports), ())
        self.assertEqual(spec.extra_env, {})

    def test_port_writeback_values_are_the_three_the_code_handles(self):
        # 拼错一个值就会在运行时走"未知策略"分支静默不改端口，所以取值域要在表层钉住。
        # 本期实际用到 cli_only / cli_flag / conf_copy 三个；shutdown_command 之类不属于本字段。
        allowed = {"cli_only", "cli_flag", "conf_copy"}
        self.assertTrue(set(main.PORT_WRITEBACKS) == allowed,
                        f"策略取值域漂移：{main.PORT_WRITEBACKS}")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py LaunchSpecTable`
Expected: FAIL，`AttributeError: 'LaunchSpec' object has no attribute 'port_writeback'`，以及 `NAME 'PORT_WRITEBACKS' is not defined`

- [ ] **Step 3: 写最小实现**

在 `main.py` 的 `class LaunchSpec` 之前加模块级常量（放在 `LaunchSpec` 定义正上方，便于对照）：

```python
# 端口策略取值域。写成一个常量而不是靠文档列举，是因为取值写错不会报错、
# 只会静默走"不改端口"分支——那正是 §5 要避免的"假装安全地改了配置"。
PORT_WRITEBACKS = ("cli_only", "cli_flag", "conf_copy")
```

在 `LaunchSpec` 内 `risk_note: str = ""` 之前追加三个字段（顺序重要：**带默认值的字段不能排在无默认值字段之前**，本期全部有默认，放末尾安全）：

```python
    # 端口策略（spec 计划二 §3.1）：
    #   cli_only  —— 只有命令行 flag 能改端口（Jenkins），不碰任何文件
    #   cli_flag  —— 端口作为命令行参数透传给厂商脚本（Nacos --server.port），不碰任何文件
    #   conf_copy —— 把官方 conf 整目录拷进 data 目录，端口只写这份副本（ActiveMQ）
    # 取值域见 PORT_WRITEBACKS；写错不会报错，只会静默不改端口，所以有 §Task1 的取值域用例。
    port_writeback: str = "cli_only"
    # 独立基准端口：与主口没有固定偏移、需要各自找空的口（ActiveMQ 的 61616）。
    # 派生口（Nacos 的 9848/9849）不放这里，走 port_offsets。
    extra_ports: tuple = ()
    # 额外注入的环境变量。值支持 {home} {data_dir} {conf_dir} {port} 占位，
    # 因为 ActiveMQ 的 ACTIVEMQ_CONF/DATA 要等端口定了、副本建好了才写得出最终值。
    extra_env: Dict[str, str] = field(default_factory=dict)
```

同时把 `LaunchSpec` docstring 第一句里那句"本期只有 cli 改端口一种端口策略，配置回写（property_file）留给计划二，故此处不提供该字段"**改掉**——它现在是假的，留着会误导下一个人。改成：

```python
    """一个组件"怎么被拉起来"的描述符。端口策略见 port_writeback 三种取值；
    厂商官方文件在任何策略下都不被修改（conf_copy 写的是 data 目录里的副本）。"""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 82 tests ... OK`（现 80 + 本任务 2；若你数出别的数，按实际写进报告，别改测试凑数）

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): LaunchSpec 增端口策略、独立端口与额外环境变量三个字段"
```

---

### Task 2: `stop_kind` 增 `port_lookup` 值并钉住语义

**Files:**
- Modify: `main.py:2982-2985`（`LaunchSpec` 的 `stop_kind` 注释与取值域）
- Test: `bt_launch_tests.py`（`LaunchSpecTable` 内追加）

**Interfaces:**
- Consumes: Task 1 的 `LaunchSpec`
- Produces: `STOP_KINDS = ("pid", "shutdown_command", "port_lookup")`；`port_lookup` 的含义是"没有可靠的厂商停止手段，停止 = 端口反查 PID"。Task 5、8 依赖这个值。

- [ ] **Step 1: 写失败测试**

```python
    def test_stop_kind_values_are_declared(self):
        self.assertEqual(set(main.STOP_KINDS), {"pid", "shutdown_command", "port_lookup"})

    def test_port_lookup_is_not_a_pid_kill_route_and_pid_role_is_derived(self):
        """pid_role 由 stop_kind 推导（计划一 start() 的既有写法），
        port_lookup 必须落到 launcher —— 别再给 LaunchSpec 加 pid_role 字段，
        两个来源迟早会漂。"""
        spec = main.LaunchSpec(commands={"Windows": []}, stop_kind="port_lookup",
                               main_port=8161)
        self.assertNotEqual(spec.stop_kind, "pid")
        self.assertEqual(
            "server" if spec.stop_kind == "pid" else "launcher", "launcher")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py LaunchSpecTable`
Expected: FAIL，`NAME 'STOP_KINDS' is not defined`

- [ ] **Step 3: 写最小实现**

在 `main.py` 的 `PORT_WRITEBACKS` 常量旁加：

```python
# 停止手段取值域。port_lookup 是计划二新增：厂商自带停止手段不可用
# （Nacos 的 shutdown.cmd 按进程名 taskkill /F，会杀到用户自己起的实例；
#  ActiveMQ 的 stop 经 JAAS/JMX 且受 conf 副本影响），所以停止 = 端口反查 PID。
# 取值写错同样不会报错、只会走错分支，所以和 PORT_WRITEBACKS 一样钉成常量。
STOP_KINDS = ("pid", "shutdown_command", "port_lookup")
```

把 `LaunchSpec` 里 `stop_kind` 的注释改为（保留 `shutdown_command` 那行不动，它是将来的位置）：

```python
    # 停止手段："pid" = 我们就是服务进程（Jenkins）；
    #           "shutdown_command" = 有可用的正规关闭脚本（本期无人使用，留作计划三位置）；
    #           "port_lookup" = 没有可靠厂商手段，停止走端口反查（Nacos / ActiveMQ）
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 84 tests ... OK`

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): stop_kind 立 port_lookup，把"没有厂商停止手段"写成显式取值"
```
---

### Task 3: `RunRecord.ports` —— 从单端口变成端口簇（含旧格式迁移）

**Files:**
- Modify: `main.py:4437-4457`（`RunRecord`）、`main.py:4460-4493`（`load_running_map`）
- Test: `bt_launch_tests.py`（`RunningMap` 类内追加）

**Interfaces:**
- Consumes: 既有 `RunRecord`、`load_running_map()`、`save_running_map()`
- Produces: `RunRecord.ports: tuple = ()`（写侧总是显式写全；`()` 只表示"旧文件没这个字段"），加载后**保证非空**。后续 Task 6/7 读 `rec.ports`。

- [ ] **Step 1: 写失败测试**

在 `RunningMap` 类内追加（该类已有 tempdir/`RUNNING_FILE` 桩，沿用它的 `setUp`）：

```python
    def test_old_format_record_without_ports_field_still_loads(self):
        """计划一写下的 running.json 根本没有 ports 字段。
        若新字段没默认值，RunRecord(**item) 会 TypeError → 整条被丢弃 →
        用户重开工具时正在跑的 Jenkins 直接认不出来。这条用例就是拦这个的。"""
        main.save_running_map({"jenkins": main.RunRecord(
            key="jenkins", version="2.568.3", home="/h", data_dir="/d", port=8080,
            console_url="http://127.0.0.1:8080/", pid=4321, pid_role="server",
            started_at=1.0, launcher_cmd=["java"], ports=())})
        raw = json.loads(main.RUNNING_FILE.read_text(encoding="utf-8"))
        raw["jenkins"].pop("ports")                      # 回到计划一的磁盘形状
        main.RUNNING_FILE.write_text(json.dumps(raw), encoding="utf-8")

        rec = main.load_running_map()["jenkins"]
        self.assertEqual(rec.ports, (8080,), "旧记录要从 port 归一，而不是被丢掉")

    def test_ports_round_trip_is_a_tuple_of_ints(self):
        """JSON 把 tuple 写成 list、把数字原样存；手改成字符串要能归一，改不动才丢。"""
        main.save_running_map({"nacos": main.RunRecord(
            key="nacos", version="2.3.2", home="/h", data_dir="/d", port=8848,
            console_url="http://127.0.0.1:8848/", pid=7, pid_role="launcher",
            started_at=1.0, launcher_cmd=["startup.cmd"], ports=(8848, 9848, 9849))})
        got = main.load_running_map()["nacos"]
        self.assertIsInstance(got.ports, tuple)
        self.assertEqual(got.ports, (8848, 9848, 9849))

    def test_scalar_ports_and_garbage_entries_are_not_fatal(self):
        # ports 被手改成标量 8848 时按单口理解；改成 "http" 这类转不动的才丢整条
        # （与既有坏 pid_role / port="http" 的政策一致）。
        main.save_running_map({"nacos": main.RunRecord(
            key="nacos", version="x", home="/h", data_dir="/d", port=8848,
            console_url="u", pid=7, pid_role="launcher", started_at=1.0,
            launcher_cmd=[], ports=(8848,))})
        raw = json.loads(main.RUNNING_FILE.read_text(encoding="utf-8"))
        raw["nacos"]["ports"] = 8848
        main.RUNNING_FILE.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(main.load_running_map()["nacos"].ports, (8848,))

        raw["nacos"]["ports"] = ["http"]
        main.RUNNING_FILE.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(main.load_running_map(), {}, "转不动的 ports 与坏 port 同一政策")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py RunningMap`
Expected: FAIL，`TypeError: RunRecord.__init__() got an unexpected keyword argument 'ports'`

- [ ] **Step 3: 写最小实现**

`RunRecord` 末尾（`launcher_cmd` 之后）加字段。**必须放最后**：dataclass 中带默认值的字段不能排在无默认值字段之前。

```python
    launcher_cmd: List[str]
    # 端口簇：主口 ∪ 派生口 ∪ 独立口。"运行中"与"停干净"都按这一组判，
    # 因为 Nacos 主口掉了而 gRPC 还在听时，按单口判会清登记、留下两个没人认领的监听口。
    # 默认 () 只表示"计划一写的旧文件里没这个字段"，加载侧会归一成 (port,)——
    # 默认值不是可选性，它决定旧记录会不会被整批静默丢弃。
    ports: tuple = ()
```

`load_running_map()` 里，在既有 int 归一那段 `try` 之后、`out[rec.key] = rec` 之前插入：

```python
        # ports 是计划二新加的字段。旧文件没有它 → 从 port 归一，绝不因为"缺字段"丢记录。
        raw_ports = item.get("ports", ())
        if isinstance(raw_ports, (int, str)):          # 手改成标量时按单口理解
            raw_ports = (raw_ports,)
        try:
            ports = tuple(int(p) for p in raw_ports)
        except (TypeError, ValueError):
            continue                                    # 转不动的按既有政策丢整条
        rec.ports = ports or (rec.port,)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 87 tests ... OK`

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): RunRecord 带端口簇 ports，旧 running.json 从 port 归一不丢记录"
```

---

### Task 4: `netstat -ano` 端口归属解析（纯函数 + 中文系统实测事实）

**Files:**
- Modify: `main.py`（`port_is_listening` 之后，`main.py:4525-4530` 附近，按符号定位）
- Test: `bt_launch_tests.py`（新类 `NetstatParse`）

**Interfaces:**
- Consumes: 无
- Produces: `parse_netstat_listeners(text: str) -> Dict[int, Set[int]]`、`netstat_listener_pids(ports: Sequence[int]) -> Dict[int, int]`。Task 7 依赖第二个的"歧义即不返回"语义。

- [ ] **Step 1: 写失败测试**

```python
class NetstatParse(unittest.TestCase):
    """fixture 是 2026-10-05 在本机（中文 Windows）实抓的 netstat -ano 文本形状。
    两个必须记住的实测事实：表头是本地化的（协议/本地地址/外部地址/状态），
    而状态值不翻译（LISTENING 仍是英文）—— 所以解析只认列形状，
    任何"按表头找列"的写法都会在中文系统上整个失效。"""

    HEAD = (
        "活动连接\n"
        "\n"
        "  协议  本地地址          外部地址        状态           PID\n"
    )
    BODY = (
        "  TCP    0.0.0.0:8848           0.0.0.0:0              LISTENING       12345\n"
        "  TCP    [::]:8848              [::]:0                 LISTENING       12345\n"
        "  TCP    0.0.0.0:9848           0.0.0.0:0              LISTENING       12345\n"
        "  TCP    0.0.0.0:9849           0.0.0.0:0              LISTENING       12345\n"
        "  TCP    127.0.0.1:54321        127.0.0.1:8848         ESTABLISHED     999\n"
        "  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1212\n"
        "  UDP    0.0.0.0:5353           *:*                                    4242\n"
    )

    def test_localized_header_and_ipv6_lines_are_handled(self):
        table = main.parse_netstat_listeners(self.HEAD + self.BODY)
        self.assertEqual(table.get(8848), {12345}, "IPv4/IPv6 两行都要归到同一个 PID")
        self.assertEqual(table.get(9848), {12345})
        self.assertEqual(table.get(135), {1212})

    def test_only_listening_rows_count(self):
        # ESTABLISHED 那行里有 8848，但它是客户端连接，不能当成"谁在监听这个口"
        table = main.parse_netstat_listeners(self.HEAD + self.BODY)
        self.assertNotIn(54321, table)
        self.assertEqual(table[8848], {12345})
        self.assertNotIn(5353, table, "UDP 没有监听语义，不许进来")

    def test_garbage_lines_are_skipped_not_fatal(self):
        table = main.parse_netstat_listeners(
            "  TCP    bogus    LISTENING\n"
            "  TCP    0.0.0.0:80    0.0.0.0:0    LISTENING   not-a-pid\n"
            + self.BODY)
        self.assertEqual(table.get(8848), {12345})

    def test_ambiguous_owner_is_reported_as_no_candidate(self):
        """同一个口被两个 PID 听着（端口复用/容器网络栈都可能）→ 宁可不认。
        认了就等于我们可能去杀一个不是我们的进程。"""
        both = (self.BODY
                + "  TCP    0.0.0.0:61616          0.0.0.0:0              LISTENING       777\n"
                  "  TCP    0.0.0.0:61616          0.0.0.0:0              LISTENING       888\n")
        table = main.parse_netstat_listeners(both)
        self.assertEqual(table[61616], {777, 888})
        self.assertNotIn(61616, main._pick_unique_pids(table, (61616,)),
                         "归属有歧义时不许给出动手对象")
        self.assertEqual(main._pick_unique_pids(table, (8848,)), {8848: 12345})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py NetstatParse`
Expected: FAIL，`module 'main' has no attribute 'parse_netstat_listeners'`

- [ ] **Step 3: 写最小实现**

紧跟 `port_is_listening` 之后加：

```python
def parse_netstat_listeners(text: str) -> Dict[int, Set[int]]:
    """把 `netstat -ano` 的文本解析成 {端口: {PID, …}}，只认 LISTENING 行。

    按列形状定位、不按表头：中文 Windows 的表头是本地化的
    （"协议 本地地址 外部地址 状态 PID"），而状态值不翻译（仍是 LISTENING）。
    任何依赖表头文字的写法在中文系统上会整体失灵。"""
    out: Dict[int, Set[int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[0].upper().startswith("TCP"):
            continue
        if parts[-2].upper() != "LISTENING":
            continue
        try:
            port = int(parts[-3].rsplit(":", 1)[-1])   # [::]:8848 取最后一段
            pid = int(parts[-1])
        except ValueError:
            continue
        out.setdefault(port, set()).add(pid)
    return out


def _pick_unique_pids(table: Dict[int, Set[int]],
                      ports: Sequence[int]) -> Dict[int, int]:
    """只保留"归属唯一"的端口。两个 PID 同听一口时宁可不动手——
    误杀的代价远大于这次停不掉。"""
    return {p: next(iter(table[p])) for p in ports if len(table.get(p, ())) == 1}


def netstat_listener_pids(ports: Sequence[int]) -> Dict[int, int]:
    """端口 → 唯一监听 PID。**这是子进程调用，只许出现在 stop/force_stop 路径**；
    出现在 status/adopt/reconcile 里就等于从后门放掉"状态检测绝不执行进程"。"""
    try:
        done = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=10,
                              text=True, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return _pick_unique_pids(parse_netstat_listeners(done.stdout or ""), ports)
```

`main.py` 顶部若尚未导入 `Sequence`，从 `typing` 补进既有的 `from typing import …` 一行（`Dict`, `List`, `Optional`, `Sequence`, `Tuple` 一并核对）。**不要新开 import 行。**

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 91 tests ... OK`

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): netstat 端口归属解析，按列形状适配中文 Windows 表头"
```

---

### Task 5: ActiveMQ 配置副本与端口回写（整目录拷贝 + 幂等 + 拒改）

**Files:**
- Modify: `main.py`（`netstat_listener_pids` 之后新增三个函数）
- Test: `bt_launch_tests.py`（新类 `ConfCopyWriteback`）

**Interfaces:**
- Consumes: `ensure_dir`（既有）、`CONFIG_DIR`
- Produces:
  - `prepare_conf_copy(src: Path, dst: Path) -> Tuple[str, List[str]]`，状态 `"created" | "exists"`
  - `set_property_line(path: Path, key: str, value: str) -> Tuple[bool, str]`
  - `set_openwire_port(path: Path, port: int) -> Tuple[bool, str]`
  - `conf_targets(data_dir: Path) -> Tuple[Path, Path, Path]`（副本根、`jetty-spring.properties`、`activemq.xml`）
  Task 6/7 依赖这些名字与"已改成功要返回 `(True, \"\")` 且不动文件"的幂等语义。

- [ ] **Step 1: 写失败测试**

fixture 用 2026-10-05 从真包抓下的原文（`apache-activemq-6.3.2`）：

```python
class ConfCopyWriteback(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.src = Path(self.dir.name) / "official-conf"
        self.dst = Path(self.dir.name) / "data" / "conf"
        (self.src / "jetty").mkdir(parents=True)
        # ↓ 三行是 6.3.2 真包原文（conf/jetty-spring.properties:35、conf/activemq.xml:178、
        #   conf/login.config 的 JAAS 相对文件名）。改这三行等于改结论，要先去重新实测。
        (self.src / "jetty-spring.properties").write_text(
            "# some header\njetty.http.port=8161\njetty.ssl.port=8443\n", encoding="utf-8")
        (self.src / "activemq.xml").write_text(
            '      <transportConnectors>\n'
            '        <transportConnector name="openwire" '
            'uri="tcp://0.0.0.0:61616?maximumConnections=1000&amp;'
            'wireFormat.maxFrameSize=10485760"/>\n'
            '      </transportConnectors>\n', encoding="utf-8")
        (self.src / "login.config").write_text(
            'org.apache.activemq.jaas.PropertiesLoginModule required\n'
            '    org.apache.activemq.jaas.properties.user="users.properties"\n'
            '    org.apache.activemq.jaas.properties.group="groups.properties";\n',
            encoding="utf-8")
        (self.src / "jetty" / "jetty-http.xml").write_text(
            '    <Set name="port"><Property name="jetty.http.port" default="8080" /></Set>\n',
            encoding="utf-8")
        (self.src / "users.properties").write_text("admin=admin\n", encoding="utf-8")
        # 副本在这里就建好：下面除了"建立副本"本身那条用例，其余都是拿"已有副本"做前提。
        # （漏了这一步的用例不会红在断言上，而红在"读不到文件"上——那是假失败。）
        main.prepare_conf_copy(self.src, self.dst)

    def test_whole_directory_is_copied_not_single_files(self):
        """必须整目录：实测 conf/login.config 里 JAAS 用的是相对文件名
        （users.properties / groups.properties，由 activemq.conf 解析），
        只拷两个端口文件会让控制台鉴权静默失效——报"起来了但登不进去"。"""
        fresh = Path(self.dir.name) / "fresh-copy"      # 用没建过的目标，才看得到 created 分支
        state, new = main.prepare_conf_copy(self.src, fresh)
        self.assertEqual(state, "created")
        self.assertTrue(new, "首次拷贝要报出建了哪些文件")
        for rel in ("jetty-spring.properties", "activemq.xml", "login.config",
                    "users.properties", "jetty/jetty-http.xml"):
            self.assertTrue((fresh / rel).exists(), f"副本缺 {rel}")
        self.assertIn("jetty/jetty-http.xml", new, "子目录没被算进相对路径清单里")

    def test_existing_copy_is_authoritative_and_only_reported(self):
        """副本一旦建立就是权威：换版本带来的新文件只点名、不自动补、不覆盖。
        补哪几个、用什么内容补，等于猜厂商升级意图。"""
        main.prepare_conf_copy(self.src, self.dst)
        (self.dst / "jetty-spring.properties").write_text(
            "jetty.http.port=9999\n", encoding="utf-8")        # 用户/我们改过
        (self.src / "brand-new-defaults.properties").write_text("x=1\n", encoding="utf-8")
        before = (self.dst / "jetty-spring.properties").read_text(encoding="utf-8")

        state, missing = main.prepare_conf_copy(self.src, self.dst)
        self.assertEqual(state, "exists")
        self.assertEqual(missing, ["brand-new-defaults.properties"])
        self.assertEqual((self.dst / "jetty-spring.properties").read_text(encoding="utf-8"),
                         before, "已存在的副本文件被覆盖了")

    def test_property_line_moves_only_the_target_line(self):
        ok, why = main.set_property_line(self.dst / "jetty-spring.properties",
                                         "jetty.http.port", "8261")
        self.assertTrue(ok, why)
        txt = (self.dst / "jetty-spring.properties").read_text(encoding="utf-8")
        self.assertIn("jetty.http.port=8261", txt)
        self.assertIn("jetty.ssl.port=8443", txt, "无关行被顺手改了")
        self.assertIn("# some header", txt)

    def test_writeback_is_idempotent_and_backs_up_only_on_first_change(self):
        target = self.dst / "jetty-spring.properties"
        main.prepare_conf_copy(self.src, self.dst)
        self.assertTrue(main.set_property_line(target, "jetty.http.port", "8261")[0])
        bak = target.with_name(target.name + ".bak")
        self.assertTrue(bak.exists(), "首次改动必须留一次备份")
        stamp = target.stat().st_mtime_ns
        content = target.read_text(encoding="utf-8")

        self.assertTrue(main.set_property_line(target, "jetty.http.port", "8261")[0])
        self.assertEqual(target.read_text(encoding="utf-8"), content, "第二次改动了文件")
        self.assertEqual(target.stat().st_mtime_ns, stamp,
                         "已是目标值还写文件：反复点启动会刷出一堆备份、白改 mtime")

    def test_unanchorable_line_is_refused_with_actionable_reason(self):
        """锚不到那行就拒改（§5 的有边界退回），且原因必须说清改哪个文件哪一行——
        只报"配置有问题"就是 R4 第 6 条禁止的"你自己去弄"。"""
        target = self.dst / "jetty-spring.properties"
        target.write_text("jetty.http.port =  8161   # 用户手加了空格和行尾注释\n",
                          encoding="utf-8")
        ok, why = main.set_property_line(target, "jetty.http.port", "8261")
        self.assertFalse(ok)
        self.assertIn("jetty-spring.properties", why)
        self.assertIn("jetty.http.port", why)
        self.assertIn("手工", why)

    def test_openwire_port_line_is_the_one_with_the_name_attribute(self):
        ok, why = main.set_openwire_port(self.dst / "activemq.xml", 61716)
        self.assertTrue(ok, why)
        txt = (self.dst / "activemq.xml").read_text(encoding="utf-8")
        self.assertIn("tcp://0.0.0.0:61716?", txt)
        self.assertIn("maximumConnections=1000", txt, "&amp; 之后的部分被吃掉了")
        self.assertNotIn("61616", txt)

    def test_openwire_refuses_when_amq_default_is_commented_or_absent(self):
        target = self.dst / "activemq.xml"
        target.write_text('      <transportConnectors>\n'
                          '        <!-- <transportConnector name="openwire" uri="tcp://0.0.0.0:61616?"/ -->\n'
                          '      </transportConnectors>\n', encoding="utf-8")
        ok, why = main.set_openwire_port(target, 61716)
        self.assertFalse(ok)
        self.assertIn("activemq.xml", why)
        self.assertIn("openwire", why)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py ConfCopyWriteback`
Expected: FAIL，`module 'main' has no attribute 'prepare_conf_copy'`

- [ ] **Step 3: 写最小实现**

```python
# ActiveMQ 回写的两个锚点，全部来自 2026-10-05 真包实测（spec 计划二 §2.1）。
# 写成常量是为了"锚不上"时的报错能指名道姓，而不是泛泛一句"配置不认识"。
AMQ_CONSOLE_FILE = "jetty-spring.properties"
AMQ_CONSOLE_KEY = "jetty.http.port"
AMQ_BROKER_FILE = "activemq.xml"
_PORT_TAIL_RE = re.compile(r"(uri=\"[a-z]+://[^\":]+:)(\d+)(\?)")


def conf_targets(data_dir: Path) -> Tuple[Path, Path, Path]:
    """副本根目录、控制台端口文件、broker 传输口文件。三处共用一份定义。"""
    conf = data_dir / "conf"
    return conf, conf / AMQ_CONSOLE_FILE, conf / AMQ_BROKER_FILE


def prepare_conf_copy(src: Path, dst: Path) -> Tuple[str, List[str]]:
    """建立/核对 ActiveMQ 的配置副本，返回 ("created"|"exists", 差异文件列表)。

    整目录拷贝而不是只拷两个端口文件：实测 conf/login.config 里的 JAAS 用的是
    相对文件名（users.properties / groups.properties，由 activemq.conf 解析），
    拷不全的话控制台鉴权会静默失效。
    副本一旦存在就是权威：不覆盖、不自动补，只把"官方有、副本没有"的文件名报出来——
    补哪些、用什么内容补，等于猜厂商的升级意图。"""
    if not dst.exists():
        ensure_dir(dst)
    else:
        present = {p.relative_to(dst).as_posix()
                   for p in dst.rglob("*") if p.is_file()}
        missing = sorted(p.relative_to(src).as_posix()
                         for p in src.rglob("*") if p.is_file()
                         and p.relative_to(src).as_posix() not in present)
        return "exists", missing
    created: List[str] = []
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = f.relative_to(src)
        target = dst / rel
        ensure_dir(target.parent)
        shutil.copy2(f, target)
        created.append(rel.as_posix())
    return "created", created


def _atomic_write(path: Path, text: str) -> None:
    """照 running.json 那套临时文件 + os.replace：写一半崩了不留半截配置。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _backup_once(path: Path) -> None:
    """只在首次改动前留一份 .bak；第二次改不留 .bak.bak，那是噪音。"""
    bak = path.with_name(path.name + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)


def set_property_line(path: Path, key: str, value: str) -> Tuple[bool, str]:
    """把 properties 文件里的 `key=<旧值>` 改成 `key=<新值>`，锚不到就拒改。

    幂等靠读出来判断：已经是目标值就一个字都不写（不改 mtime、不多备份），
    这样反复点启动不会刷出一堆 .bak。只认"行首正好是 key="的形状——
    用户手加空格或行尾注释时我们不猜他的写法，明确拒绝并告诉他改哪一行。"""
    want = f"{key}={value}"
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        return False, f"读不到 {path.name}：{exc}"
    if any(line.rstrip("\r\n") == want for line in lines):
        return True, ""
    hits = [n for n, line in enumerate(lines) if line.startswith(f"{key}=")]
    if not hits:
        return False, (f"{path.name} 里找不到 {key}= 这一行（官方默认写法被改过）。"
                       f"请手工把该文件里的 {key} 改成 {value} 后再启动。")
    n = hits[0]
    lines[n] = want + "\n"
    _backup_once(path)
    _atomic_write(path, "".join(lines))
    return True, ""


def set_openwire_port(path: Path, port: int) -> Tuple[bool, str]:
    """改 activemq.xml 里 name="openwire" 那一行的端口，只动 uri 里的数字。"""
    target = f"uri=\"tcp://0.0.0.0:{port}?"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"读不到 {path.name}：{exc}"
    lines = text.splitlines(keepends=True)
    hits = [n for n, line in enumerate(lines) if "name=\"openwire\"" in line
            and "<!--" not in line]
    if not hits:
        return False, (f"{path.name} 里找不到可改的 openwire transportConnector 行"
                       f"（被注释掉或写法不是默认那样）。请手工把 broker 端口改成 {port}。")
    n = hits[0]
    if target in lines[n]:
        return True, ""                                   # 已经是目标值
    new, cnt = _PORT_TAIL_RE.subn(lambda m: f"{m.group(1)}{port}{m.group(3)}", lines[n], count=1)
    if cnt != 1:
        return False, (f"{path.name} 第 {n + 1} 行的 uri 写法不认识，不敢改。"
                       f"请手工把 openwire 端口改成 {port}。")
    lines[n] = new
    _backup_once(path)
    _atomic_write(path, "".join(lines))
    return True, ""
```

`main.py` 若未导入 `shutil`，补进既有 import 区（按字母序就近插入，不要新开分散的多行）。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 98 tests ... OK`

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): ActiveMQ 配置副本与端口幂等回写，锚不上就拒改并指出改哪行"
```
---

### Task 6: 端口规划与"拉起之前"的端口准备

**Files:**
- Modify: `main.py`（新增 `PortPlan` / `choose_ports` / `prepare_ports`；`build_launch_plan` 内加 `conf_dir` 占位与 `extra_env` 注入；`ServiceManager.start` 按新流程接上）
- Test: `bt_launch_tests.py`（新类 `PortPlanning`）

**Interfaces:**
- Consumes: `pick_free_cluster`、`spec.port_offsets` / `spec.extra_ports` / `spec.port_writeback` / `spec.extra_env`（Task 1）、`prepare_conf_copy` / `set_property_line` / `set_openwire_port`（Task 5）、`conf_targets`
- Produces:
  - `@dataclass PortPlan(main: int, derived: Tuple[int, ...] = (), extras: Tuple[int, ...] = ())`，属性 `all_ports -> Tuple[int, ...]`（主口 + 派生 + 独立，顺序固定成这样）
  - `choose_ports(spec: LaunchSpec, is_free=port_is_free) -> Tuple[PortPlan, str]` —— 成功 `(plan, "")`，失败 `(PortPlan(), "指名原因")`
  - `prepare_ports(comp, spec, plan: PortPlan, data_dir: Path) -> Tuple[bool, str, List[str]]` —— `(ok, 失败原因, 提示给用户的告警行)`
  - `start()` 写入的 `RunRecord.ports` = `plan.all_ports`

- [ ] **Step 1: 写失败测试**

```python
class PortPlanning(unittest.TestCase):
    def spec(self, **kw):
        base = dict(commands={os_name: ["x"] for os_name in ("Windows", "Linux", "Darwin")},
                    main_port=8848, port_offsets=(1000, 1001))
        base.update(kw)
        return main.LaunchSpec(**base)
    # ↑ commands 三个 OS 都给齐：build_launch_plan 取的是 commands[CURRENT_OS]，
    #   只写 Windows 会让这套用例变成"只在 Windows 上绿"的宿主机依赖（计划一返工过两次）。

    def test_all_free_takes_the_declared_defaults(self):
        plan, why = main.choose_ports(self.spec(), is_free=lambda p, host="127.0.0.1": True)
        self.assertEqual(why, "")
        self.assertEqual(plan.all_ports, (8848, 9848, 9849))

    def test_derived_ports_move_with_the_main_port(self):
        """派生口（Nacos gRPC）跟着主口走：主口平移到 8850，9848 系也要变成 9850 系。
        这条是"整簇一起可用"规则的另一半，写错就会起来一个半死的 Nacos。

        占用集 {8848, 9848, 9849} 之下正确答案是 8850 而不是 8849：8849 这一簇是
        {8849, 9849, 9850}，而 9849 已被占 —— 主口自己空着不算数。
        （计划一 Task 3 就栽过这类"占用集算错"的夹具上，这次把推导写在这里。）"""
        taken = {8848, 9848, 9849}
        plan, why = main.choose_ports(self.spec(),
                                      is_free=lambda p, host="127.0.0.1": p not in taken)
        self.assertEqual((plan.main, plan.all_ports), (8850, (8850, 9850, 9851)), why)

    def test_extra_ports_search_their_own_base(self):
        """独立口（ActiveMQ 61616）与 8161 没有固定偏移关系：控制台口平移到 8162 时，
        broker 口仍应从 61616 自己的基准起找，不是 61617。"""
        s = self.spec(main_port=8161, port_offsets=(), extra_ports=(61616,))
        taken = {8161}
        plan, why = main.choose_ports(s, is_free=lambda p, host="127.0.0.1": p not in taken)
        self.assertEqual((plan.main, plan.extras, plan.all_ports),
                         (8162, (61616,), (8162, 61616)), why)

    def test_failure_names_the_port_that_had_no_room(self):
        """失败原因里必须指名是哪个口找不到位置；只说"端口不够"等于把用户打发去自己查。"""
        s = self.spec(main_port=8161, port_offsets=(), extra_ports=(61616,),
                      port_search_span=3)
        taken = {61616, 61617, 61618, 61619}
        plan, why = main.choose_ports(s, is_free=lambda p, host="127.0.0.1": p not in taken)
        self.assertEqual(plan.all_ports, ())
        self.assertIn("61616", why)

    def test_build_plan_injects_conf_dir_and_extra_env(self):
        """extra_env 的占位符必须能拿到 conf_dir/data_dir：ActiveMQ 的 ACTIVEMQ_CONF
        指向副本、ACTIVEMQ_DATA 指向 data，两者都是端口定了、副本建好之后才写得出的值。"""
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        s = self.spec(extra_env={"ACTIVEMQ_CONF": "{conf_dir}", "ACTIVEMQ_DATA": "{data_dir}"})
        with tempfile.TemporaryDirectory() as td:
            orig, main.CONFIG_DIR = main.CONFIG_DIR, Path(td)
            self.addCleanup(setattr, main, "CONFIG_DIR", orig)
            plan = main.build_launch_plan(comp, s, r"C:\jdk", 8848,
                                          Path(td) / "logs" / "byte-tools.out")
            self.assertEqual(plan.env["ACTIVEMQ_CONF"], str(Path(td) / "jenkins-data" / "conf"))
            self.assertEqual(plan.env["ACTIVEMQ_DATA"], str(Path(td) / "jenkins-data"))

    def test_conf_copy_prepare_touches_no_file_for_cli_strategies(self):
        for strategy in ("cli_only", "cli_flag"):
            with self.subTest(strategy=strategy):
                with tempfile.TemporaryDirectory() as td:
                    ok, why, notes = main.prepare_ports(
                        self.comp(), self.spec(port_writeback=strategy),
                        main.PortPlan(main=8848, derived=(9848, 9849)), Path(td))
                    self.assertTrue(ok, why)
                    self.assertEqual(list(Path(td).rglob("*")), [],
                                     f"{strategy} 不该写任何文件：Nacos 的端口走命令行透传")

    def test_conf_copy_writes_only_into_the_copy(self):
        """conf_copy 的回写只发生在 data/conf 里，官方目录一个字节不动。
        fixture 是 6.3.2 真包原文的两行（spec 计划二 §2.1）。"""
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            (home / "conf").mkdir(parents=True)
            (home / "conf" / "jetty-spring.properties").write_text(
                "jetty.http.port=8161\n", encoding="utf-8")
            (home / "conf" / "activemq.xml").write_text(
                '  <transportConnector name="openwire" '
                'uri="tcp://0.0.0.0:61616?maximumConnections=1000"/>\n', encoding="utf-8")
            data = Path(td) / "data"
            comp = self.comp()
            comp.versions = [comp.versions[0]]
            s = self.spec(main_port=8161, port_offsets=(), extra_ports=(61616,),
                          port_writeback="conf_copy")
            orig_install, comp.install_dir = comp.install_dir, (lambda v: home)
            self.addCleanup(setattr, comp, "install_dir", orig_install)

            ok, why, notes = main.prepare_ports(
                comp, s, main.PortPlan(main=8162, extras=(61716,)), data)
            self.assertTrue(ok, why)
            copy = (data / "conf")
            self.assertIn("jetty.http.port=8162",
                          (copy / "jetty-spring.properties").read_text(encoding="utf-8"))
            self.assertIn("0.0.0.0:61716",
                          (copy / "activemq.xml").read_text(encoding="utf-8"))
            self.assertEqual((home / "conf" / "jetty-spring.properties").read_text(encoding="utf-8"),
                             "jetty.http.port=8161\n", "官方文件被动了")

    def comp(self):
        return next(c for c in main.build_components() if c.key == "jenkins")
```

> 执行说明：上面 `PortPlanning` 里两个方法用到 `self.comp()`，它定义在最后 —— Python 不关心方法定义顺序，**别为了"看起来顺"把它挪到类外**（挪出去就变成模块级函数，`self.comp()` 会 `TypeError`）。

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py PortPlanning`
Expected: FAIL，`module 'main' has no attribute 'PortPlan'`

- [ ] **Step 3: 写最小实现**

```python
@dataclass
class PortPlan:
    """一次启动最终要用的端口。三种角色分开存，是因为它们的平移规则根本不同：
    派生口跟着主口走，独立口有自己的基准。合成一个 tuple 存就不区分得开了。"""
    main: int = 0
    derived: Tuple[int, ...] = ()
    extras: Tuple[int, ...] = ()

    @property
    def all_ports(self) -> Tuple[int, ...]:
        return (self.main,) + tuple(self.derived) + tuple(self.extras)


def choose_ports(spec: LaunchSpec, is_free=port_is_free) -> Tuple[PortPlan, str]:
    """选端口：主口+派生口整簇同空（平移规则沿用计划一定死的"最小 + 整簇"），
    独立口（extra_ports）各自按自己的基准另找——它们与主口没有固定偏移，
    塞进 port_offsets 会静默写错端口。"""
    base = pick_free_cluster(spec.main_port, spec.port_offsets, spec.port_search_span,
                             is_free=is_free)
    if base is None:
        return PortPlan(), (f"{spec.main_port} 起 {spec.port_search_span + 1} 个端口内"
                            f"都找不到整簇空闲的位置（含派生口 "
                            f"{[spec.main_port + o for o in spec.port_offsets]}）。")
    derived = tuple(base + int(o) for o in spec.port_offsets)
    extras: List[int] = []
    for extra_base in spec.extra_ports:
        hit = pick_free_cluster(int(extra_base), (), spec.port_search_span, is_free=is_free)
        if hit is None:
            # 半成功比不启动更坏：控制台起来了、客户端连不上，界面还显示"运行中"。
            return PortPlan(), (f"端口 {extra_base}（组件的另一个必要端口）在 "
                                f"{spec.port_search_span + 1} 个端口内也找不到空闲位置。")
        extras.append(hit)
    return PortPlan(main=base, derived=derived, extras=tuple(extras)), ""


def prepare_ports(comp: Component, spec: LaunchSpec, plan: PortPlan,
                  data_dir: Path) -> Tuple[bool, str, List[str]]:
    """端口准备。返回 (能否继续拉起, 失败原因, 要转成日志告知用户的提示行)。

    回写一定发生在拉起之前：改了配置却没起进程、或起进程时配置没生效，
    两边状态对不上时比"没启动"更难归因 —— 所以失败必须阻止 spawn。"""
    if spec.port_writeback == "cli_only":
        return True, "", []
    if spec.port_writeback == "cli_flag":
        # 端口靠命令行透传（Nacos：startup.cmd 的 %* 会把它交给 java），不碰文件。
        return True, "", []
    if spec.port_writeback != "conf_copy":
        return False, (f"{comp.display_name} 的端口策略 {spec.port_writeback!r} 不认识，"
                       f"已放弃启动（不会去猜该怎么改配置）。"), []
    src = comp.install_dir(comp.versions[0].version) / "conf"
    conf, console_file, broker_file = conf_targets(data_dir)
    notes: List[str] = []
    state, diff = prepare_conf_copy(src, conf)
    if state == "created":
        notes.append(f"已在 {conf} 建立 {comp.display_name} 配置副本，"
                     f"此后端口改动只写这份副本（官方文件不受影响）。")
    elif diff:
        notes.append(f"官方 conf 里有 {len(diff)} 个文件是副本没有的（多半是版本升级带来的）："
                     f"{', '.join(diff[:5])}。本工具不自动合并，需要时删掉副本目录让它重建。")
    ok, why = set_property_line(console_file, AMQ_CONSOLE_KEY, str(plan.main))
    if not ok:
        return False, why, notes
    for extra_base, port in zip(spec.extra_ports, plan.extras):
        ok, why = set_openwire_port(broker_file, port)
        if not ok:
            return False, why, notes
    return True, "", notes
```

`build_launch_plan` 内：在 `mapping` 里加 `"conf_dir": str(data_dir / "conf")`，并在 `if spec.data_dir_env:` 之后追加：

```python
    # 计划二的额外 env（ActiveMQ 的 ACTIVEMQ_CONF/DATA 走这条路；
    # 它两个值都要等端口定了、副本建好了才写得出最终值，所以在计划阶段拼）。
    for name, template in (spec.extra_env or {}).items():
        env[name] = template.format(**mapping)
```

`ServiceManager.start()` 里把"选端口"那一段换成 `choose_ports`，并在 `build_launch_plan` **之前**插一步 `prepare_ports`；失败时返回 `StartResult(False, "writeback", why)`。`RunRecord(...)` 的构造处加 `ports=plan.all_ports`。`state` 字段注释同步补上 `"writeback"`。

**Step 3b：超时归因要能翻厂商自己的日志（spec 计划二 §7 那一行）**

计划一的超时原因只带我们自己的重定向文件尾巴。对本期两个组件不够：ActiveMQ 的 broker 报错写在
`data/activemq.log`，Nacos 在 `logs/start.out`（POSIX）——厂商脚本把问题写在自己的文件里。
在 `ServiceManager` 加一个纯函数，并在超时 reason 里追一句（**读不到就照实说读不到**，不许静默省略）：

```python
# 厂商日志的候选位置（spec 计划二 §7 实测清单）。写成表而不是猜：
# 找不到文件是常态（首次启动、Windows 下 Nacos 就没有 start.out），
# 那种情况要明说"还没生成"，让用户知道去哪儿看，而不是给一句空报错。
VENDOR_LOG_CANDIDATES = {
    "activemq": ("data/activemq.log", "data/activemq.dump"),
    "nacos": ("logs/start.out",),
}


def vendor_log_tails(data_dir: Path, home: Path, key: str, lines: int = 8) -> str:
    """把该组件厂商日志的尾巴拼成一句可读文本。没有文件就回"（厂商日志尚未生成）"。"""
    chunks = []
    for rel in VENDOR_LOG_CANDIDATES.get(key, ()):
        for base in (data_dir, home):
            p = base / rel
            if p.exists():
                chunks.append(f"{rel}: {ServiceManager._tail(p, lines)}")
                break
    return " / ".join(chunks) or "（厂商日志尚未生成）"
```

超时那段改成：

```python
        reason = (f"{spec.startup_timeout} 秒内 {'/'.join(str(p) for p in plan.all_ports)} "
                  f"未全部监听。启动输出见 {plan.log_file}，末尾内容：{self._tail(plan.log_file)}"
                  f"；{comp.display_name} 自身日志：{vendor_log_tails(data_dir, plan.cwd, comp.key)}")
```

对应加一条用例（放在 `PortPlanning` 里）：

```python
    def test_timeout_reason_reaches_for_the_vendor_log(self):
        """厂商把报错写在自家文件里，只给我们自己那份重定向文件的尾巴，
        用户就看到"起不来"三个字而不知道去看哪。"""
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "data").mkdir()
            (data / "data" / "activemq.log").write_text(
                "Caused by: java.lang.OutOfMemoryError\n", encoding="utf-8")
            out = main.vendor_log_tails(data, data, "activemq")
            self.assertIn("OutOfMemoryError", out)
            self.assertIn("activemq.log", out)
            self.assertIn("尚未生成", main.vendor_log_tails(data, data, "nacos"))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 106 tests ... OK`，且 `StartFlow` 既有用例（端口平移、超时不留登记）仍全绿

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): 端口规划区分派生口与独立口，配置回写失败阻止拉起"
```

---

### Task 7: 按簇判定 + `port_lookup` 停止路径（三重闸）

**Files:**
- Modify: `main.py`（`ServiceManager.__init__` / `status` / `stop` / `force_stop`）
- Test: `bt_launch_tests.py`（`StatusProbe`、`StopFlow` 内追加；`NoExecInvariant` 扩展）

**Interfaces:**
- Consumes: `rec.ports`（Task 3）、`netstat_listener_pids` / `_pick_unique_pids`（Task 4）、`PortPlan.all_ports`
- Produces: `ServiceManager.__init__(..., lookup_pids=None)`、`_listener_pids(ports)`（call-time 解析，见下注释）、`force_stop(key, sleeper, rounds)` 签名不变

- [ ] **Step 1: 写失败测试**

```python
    def test_running_requires_the_whole_cluster_to_be_listening(self):
        """Nacos 主口在听、9848 掉了，是"半死"，不是运行中：按单口判会显示运行中，
        而客户端连不上；下一个任务把它判成僵尸又会清掉登记，两个没人认领的监听口留下。"""
        rec = self.rec(ports=(8848, 9848, 9849))
        st = main.ServiceManager(
            is_listening=lambda p, host="127.0.0.1": p != 9848).status("nacos", self.comp, {
                "nacos": rec})
        self.assertEqual(st.state, "zombie")
        self.assertIn("9848", st.reason)

    def test_force_stop_kills_the_port_owner_found_by_lookup(self):
        """登记的 PID 是 cmd.exe（launcher），杀它 java 还活着。所以动手对象是
        "端口反查出来的那个 PID"，不是登记里那个。打桩 os.kill —— 真杀进程违反离线约束。"""
        killed = []
        orig_kill = main.os.kill
        main.os.kill = lambda pid, sig: killed.append((pid, sig))
        self.addCleanup(setattr, main.os, "kill", orig_kill)
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  process_alive=lambda pid: True,
                                  terminate=lambda rec: killed.append(("rec", rec.pid)),
                                  lookup_pids=lambda ports: {8848: 55555})
        res = mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1)
        self.assertFalse(res.ok, "端口还在听就不许算停成功")
        self.assertIn((55555, 9), killed, "该杀的是端口反查出来的 PID")
        self.assertNotIn(("rec", 43210), killed,
                         "不许退回杀登记里那个 launcher PID")

    def test_zombie_detection_copes_with_records_lacking_ports(self):
        # 计划一写的记录没有 ports；按 port 兜底，不许 TypeError 冒出来
        # （加载侧归一化只覆盖"从磁盘读"，进程内刚构造出来的记录也得能判）
        rec = main.RunRecord(key="jenkins", version="x", home="/h", data_dir="/d",
                             port=8080, console_url="u", pid=1, pid_role="server",
                             started_at=0.0, launcher_cmd=[], ports=())
        st = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True).status(
            "jenkins", self.comp, {"jenkins": rec})
        self.assertEqual(st.state, "running")

    def test_port_lookup_role_asks_before_any_kill(self):
        """launcher 角色的停止没有优雅手段：第一步只请示，一个进程都不许碰。"""
        killed, looked = [], []
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  process_alive=lambda pid: True,
                                  terminate=lambda rec: killed.append(rec.pid),
                                  lookup_pids=lambda ports: looked.append(tuple(ports)) or {})
        res = mgr.stop(self.comp_nacos, self.comps, deadline=1.0, sleeper=lambda s: None)
        self.assertFalse(res.ok)
        self.assertTrue(res.need_force)
        self.assertEqual(killed, [], "launcher 角色不许走 PID 终止")
        self.assertIn("强制", res.reason)

    def test_force_stop_refuses_ambiguous_and_self_targets(self):
        # 同口两个 PID（端口复用/容器网络栈都可能）→ 宁可不认，认了就可能杀错
        for table, why in (({}, "空表"), ({8848: os.getpid()}, "是我们自己")):
            with self.subTest(why):
                mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                          process_alive=lambda pid: True,
                                          lookup_pids=lambda ports, t=table: dict(t))
                res = mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1)
                self.assertFalse(res.ok)
                self.assertIn("强制", res.reason)
                self.assertIn("nacos", main.load_running_map(), "停不掉就不许清登记")

    def test_force_stop_releases_only_after_the_whole_cluster_goes_quiet(self):
        """复查必须按簇：主口掉了、gRPC 还在听，不能算"已停止"并清登记。"""
        listening = {8848: False, 9848: True, 9849: False}
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": listening.get(p, False),
                                  process_alive=lambda pid: False,
                                  lookup_pids=lambda ports: {})
        res = mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1)
        self.assertFalse(res.ok)
        self.assertIn("9848", res.reason)
        self.assertIn("nacos", main.load_running_map())
        listening[9848] = False
        self.assertTrue(mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1).ok)
        self.assertEqual(main.load_running_map(), {})
```

在 `NoExecInvariant` 内追加两条（正向 + 反向都要有——只钉"检测不出子进程"，会把 force 路径写成测不到的死代码）：

```python
    def test_detection_paths_never_consult_the_port_owner_table(self):
        """端口反查是一次 netstat 调用。它出现在 status/adopt/reconcile 里，
        就等于从后门放掉"状态检测绝不执行进程"。"""
        calls = []
        orig = main.netstat_listener_pids
        main.netstat_listener_pids = lambda ports: calls.append(tuple(ports)) or {}
        self.addCleanup(setattr, main, "netstat_listener_pids", orig)
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": False)
        comps = {c.key: c for c in main.build_components()}
        main.save_running_map({"nacos": self.nacos_rec()})
        mgr.status("nacos", comps["nacos"])
        mgr.adopt(comps)
        mgr.reconcile(comps)
        self.assertEqual(calls, [], "检测路径调用了端口反查")

    def test_force_stop_actually_consults_it(self):
        """反向：force 路径确实会去查。否则上面那条"不许调用"可以靠删掉调用白赢。"""
        calls = []
        orig = main.netstat_listener_pids
        main.netstat_listener_pids = lambda ports: calls.append(tuple(ports)) or {}
        self.addCleanup(setattr, main, "netstat_listener_pids", orig)
        mgr = main.ServiceManager(is_listening=lambda p, host="127.0.0.1": True,
                                  process_alive=lambda pid: False)
        main.save_running_map({"nacos": self.nacos_rec()})
        mgr.force_stop("nacos", sleeper=lambda s: None, rounds=1)
        self.assertEqual(len(calls), 1, "force_stop 没调用端口反查")
        self.assertEqual(set(calls[0]), {8848, 9848, 9849})
```

> **夹具补齐（写在 `bt_launch_tests.py`，照计划一 `StopFlow` 的既有风格）：**
>
> ```python
>     # 追加在 StopFlow.setUp 末尾。key 仍用 jenkins、spec 本地造 ——
>     # 本任务不能引用 Task 8 才登记的 nacos，否则用例是跑在未来任务的代码上。
>     self.lookup_spec = main.LaunchSpec(
>         commands={os_name: ["{home}/bin/startup.cmd"] for os_name in ("Windows", "Linux", "Darwin")},
>         stop_kind="port_lookup", main_port=8848, port_offsets=(1000, 1001))
>     self.lookup_comp = next(c for c in main.build_components() if c.key == "jenkins")
>     self.lookup_comp.key = "nacos"                  # 只用于本地夹具：登记 key 与 spec 对齐
>     self.lookup_comp.launch = self.lookup_spec
>     self.comps["nacos"] = self.lookup_comp
>
>     def nacos_rec(self, ports=(8848, 9848, 9849)):
>         """launcher 角色的三口簇登记：登记的 PID 是包装脚本，不是服务进程。"""
>         return main.RunRecord(key="nacos", version="2.3.2", home="/h", data_dir="/d",
>                               port=ports[0], console_url="http://127.0.0.1:8848/",
>                               pid=43210, pid_role="launcher", started_at=0.0,
>                               launcher_cmd=["startup.cmd"], ports=ports)
>
>     def rec(self, ports=()):
>         return main.RunRecord(key="jenkins", version="x", home="/h", data_dir="/d",
>                               port=8080, console_url="http://127.0.0.1:8080/", pid=1,
>                               pid_role="server", started_at=0.0, launcher_cmd=[],
>                               ports=ports)
> ```
>
> 上面用例里的 `self.comp_nacos` / `self.comp` 分别就是 `self.lookup_comp` 与 `StopFlow` 已有的
> `self.comp`；`self.comp` 那两处 `status()` 用例走的是显式传入的 records，不落盘，因此不受
> 新登记的 key 影响。**不要改动计划一已有断言**（Jenkins 的 `pid` 路线必须仍然原样绿）。

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py StopFlow`
Expected: FAIL，`ServiceManager.__init__() got unexpected keyword 'lookup_pids'` / 按单口判定导致簇用例红

- [ ] **Step 3: 写最小实现**

`__init__` 增加 `lookup_pids=None`：

```python
    def __init__(self, is_listening=port_is_listening, http_ok=http_ok,
                 process_alive=process_is_alive, terminate=None, lookup_pids=None):
        self._is_listening = is_listening
        self._http_ok = http_ok
        self._process_alive = process_alive
        self._terminate = terminate or self._terminate_by_pid
        # 端口反查的注入点。用 lambda 包一层而不是把函数当默认值绑死：
        # 默认参数在 def 时求值，测试 patch main.netstat_listener_pids 就会失效
        # （这个坑计划一的 start() 已经踩过并写进注释）。
        self._lookup_pids = lookup_pids or (lambda ports: netstat_listener_pids(ports))
```

`status()` 的端口判定改按簇：

```python
        ports = tuple(rec.ports) or (rec.port,)
        silent = [p for p in ports if not self._is_listening(p)]
        if silent:
            return LaunchStatus("zombie", rec,
                                f"登记的进程已不在监听 {'/'.join(str(p) for p in silent)}")
        return LaunchStatus("running", rec)
```

`stop()` 的 Windows 分支之前插一条 `port_lookup` 分支（顺序：`shutdown_command` → `port_lookup`/Windows 请示 → 优雅 terminate），文案按簇说明代价：

```python
        elif spec.stop_kind == "port_lookup" or CURRENT_OS == "Windows":
            # 端口是真相：整簇都空了就当已停（下面的等待循环会清登记），别吓用户。
            ports = tuple(rec.ports) or (rec.port,)
            if not any(self._is_listening(p) for p in ports):
                records = load_running_map()
                records.pop(comp.key, None)
                save_running_map(records)
                return StopResult(True, reason=f"{comp.display_name} 已经不在监听 "
                                              f"{'/'.join(str(p) for p in ports)}，登记已清。")
            if spec.stop_kind != "port_lookup":
                return StopResult(False, need_force=True, reason=(... 计划一原文 ...))
            return StopResult(False, need_force=True,
                              reason=(f"{comp.display_name}（端口 "
                                      f"{'/'.join(str(p) for p in ports)}）没有可用的优雅停止手段："
                                      f"它的启动脚本是包装器，登记的 PID 不是服务进程，"
                                      f"而厂商自带的关闭脚本按进程名强杀、会误伤本机其它同名实例。"
                                      f"要按端口找到那个进程并强制结束吗？"))
```

`force_stop()` 在原有 server 路径之外补 launcher 路径：

```python
        ports = tuple(rec.ports) or (rec.port,)
        still = [p for p in ports if self._is_listening(p)]
        if still:
            owners = self._lookup_pids(tuple(still))
            mine = {p: pid for p, pid in owners.items() if pid != os.getpid()}
            if rec.pid_role == "server":
                if self._process_alive(rec.pid):
                    try:
                        os.kill(rec.pid, 9)
                    except OSError:
                        pass
            elif mine:
                # 三重闸：① 有我们自己的登记（上面 rec is not None 已保证）
                #      ② 不是我们自己（pid != os.getpid()）
                #      ③ 用户已确认 —— 走到 force_stop 本身就是确认
                # 归属有歧义（同口多 PID）时 _pick_unique_pids 不给结果，宁可不杀。
                for pid in sorted(set(mine.values())):
                    try:
                        os.kill(pid, 9)
                    except OSError:
                        pass
```

并把复查从"单口"改成"整簇"（现有有界轮次保留）：

```python
        for _ in range(max(1, int(rounds))):
            if not any(self._is_listening(p) for p in ports):
                ...清登记、返回 ok...
            sleeper(1.0)
        return StopResult(False, need_force=True,
                          reason=f"端口 {'/'.join(str(p) for p in ports)} 里还有 "
                                 f"{[p for p in ports if self._is_listening(p)]} 在听，"
                                 f"可能是别的进程占着，不是本工具启动的那个。")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 114 tests ... OK`；计划一的 `StopFlow` 既有用例仍全绿（Jenkins 走 `pid`，不受新分支影响）

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): 运行/僵尸判定改按端口簇，launcher 角色按端口反查停止"
```

---

### Task 8: Nacos 接入登记

**Files:**
- Modify: `main.py:3007-3027`（`LAUNCH_OF` 加 `"nacos"` 条目）
- Test: `bt_launch_tests.py`（`LaunchSpecTable` 内追加 + **同步修改两个既有断言**，见 Step 3 末尾）

**Interfaces:**
- Consumes: Task 1–7 全部
- Produces: `LAUNCH_OF["nacos"]`、`LAUNCH_KEYS == {"jenkins", "nacos", "activemq"}`（`activemq` 由 Task 9 加）

- [ ] **Step 1: 写失败测试**

```python
    def test_nacos_registered_as_the_plan_two_shape(self):
        s = main.LAUNCH_OF["nacos"]
        self.assertEqual(s.main_port, 8848)
        self.assertEqual(tuple(s.port_offsets), (1000, 1001))
        self.assertEqual(tuple(s.extra_ports), (), "Nacos 的 gRPC 口是派生的，不是独立基准")
        self.assertEqual(s.port_writeback, "cli_flag")
        self.assertEqual(s.stop_kind, "port_lookup")
        self.assertEqual(s.needs, ("jdk",))
        self.assertEqual(s.min_java_major, 8)     # 证据：nacos-server.jar 内 Nacos.class class major 52
        self.assertEqual(s.startup_timeout, 90)
        self.assertTrue(s.risk_note, "默认无鉴权 + 账号 nacos/nacos 必须写在风险说明里")

    def test_nacos_command_carries_mode_and_port_as_separate_argv_items(self):
        """-m standalone 必须是独立的两段，--server.port 必须带选中端口：
        startup.cmd 用 `for %%a in (%*)` 按空格分词，拼成一个字符串就全碎。"""
        argv = main.LAUNCH_OF["nacos"].commands["Windows"]
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "standalone",
                         "默认是 cluster（-Xms2g 且要 cluster.conf），不强制 standalone 起不来")
        self.assertTrue(any(a.startswith("--server.port={port}") for a in argv),
                        "端口要靠命令行透传，这是 Nacos 不回写任何文件的依据")

    def test_nacos_registration_does_not_need_java_home_on_the_command_line(self):
        """startup.cmd 硬要 %JAVA_HOME%\\bin\\java.exe，所以 JAVA_HOME 必须是环境变量注入
        而不是把 java 路径拼进 argv —— 我们跑的是厂商脚本，脚本自己找 java。"""
        argv = main.LAUNCH_OF["nacos"].commands["Windows"]
        self.assertFalse(any("{java}" in a for a in argv))
        self.assertTrue(argv[0].endswith("startup.cmd") or argv[0].endswith("startup.sh"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py LaunchSpecTable`
Expected: FAIL，`KeyError: 'nacos'`

- [ ] **Step 3: 写最小实现**

```python
    "nacos": LaunchSpec(
        # 实测（2026-10-05，nacos-server-2.3.2）：startup.cmd 的 %COMMAND% 是前台 java，
        # 末尾带 %* → --server.port 直接透传给 Spring Boot，优先级高于 application.properties，
        # 所以 Nacos 一个文件都不改。-p 是 embedded storage，不是端口，别写错。
        commands={"Windows": ["{home}/bin/startup.cmd", "-m", "standalone",
                              "--server.port={port}"],
                  "Linux": ["{home}/bin/startup.sh", "-m", "standalone",
                            "--server.port={port}"],
                  "Darwin": ["{home}/bin/startup.sh", "-m", "standalone",
                             "--server.port={port}"]},
        stop_kind="port_lookup",
        main_port=8848,
        port_offsets=(1000, 1001),      # gRPC 口由 server.port 派生（包内无对应属性可回写）
        port_search_span=99,
        console_path="/",                # 待真机 A3 确认；先按包内白名单形状（含 / 无 /nacos）取根
        health_path=None,
        needs=("jdk",),
        min_java_major=8,
        data_dir_env=None,               # 厂商无外移开关：-Dnacos.home 固定在安装目录内
        startup_timeout=90,
        risk_note=(
            "Nacos 默认监听 0.0.0.0（对局域网开放），默认未开启鉴权，"
            "控制台默认账号 nacos/nacos。"
            "运行数据（derby）落在安装目录内的 data/ 下：卸载组件会连带删除它，"
            "这一点与 Jenkins 不同（Jenkins 的数据在 ~/.env-tools 下，卸载后保留）。"
        ),
    ),
```

**同步修改一处既有断言（本期把白名单从 1 扩到 2，不改它必然红）：**

`bt_launch_tests.py:29` 的 `test_launch_keys_are_exactly_jenkins` → 改名
`test_launch_keys_are_exactly_this_batch`，断言右侧写成**显式相等**：

```python
    def test_launch_keys_are_exactly_this_batch(self):
        self.assertEqual(main.LAUNCH_KEYS, {"jenkins", "nacos"},
                         "白名单只能按批次扩：多一个组件就要多一份实测事实与一份风险说明")
        self.assertEqual(main.LAUNCH_KEYS, set(main.LAUNCH_OF))
```

**右侧不许改成 `>=` 或 `issubset`**——"不得再多"正是这条用例唯一的价值。
（Task 9 会把期望值扩成三个，那时同样只改字面量。）

另一条 `test_min_java_major_is_none_until_measured`（`bt_launch_tests.py:50`）**已确认本来就是 jenkins 专属断言，本任务不动它**——
它不会被 Nacos 的 `8` 弄红，也绝不允许顺手放宽成"全部为 None"。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 117 tests ... OK`；`StatusProbe`/`ZombieMatrix`/`StartFlow` 等既有用例不得被改动来迁就新组件

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): Nacos 接入启动登记（端口走命令行透传，不回写任何文件）"
```
---

### Task 9: ActiveMQ 接入登记 + 卸载时把数据去处说清

**Files:**
- Modify: `main.py`（`LaunchSpec` 加 `data_note`；`LAUNCH_OF` 加 `"activemq"`；卸载确认文案接 `data_note`）
- Test: `bt_launch_tests.py`（`LaunchSpecTable`、`CardLaunchUi` 各追加）

**Interfaces:**
- Consumes: Task 5（conf 副本函数）、Task 6（`conf_targets` 与 `extra_ports` 回写）、Task 7（`port_lookup` 停止）
- Produces: `LaunchSpec.data_note: str = ""`（卸载确认里显示）、`LAUNCH_OF["activemq"]`、`LAUNCH_KEYS == {"jenkins","nacos","activemq"}`

- [ ] **Step 1: 写失败测试**

```python
    def test_activemq_registered_with_two_independent_ports(self):
        s = main.LAUNCH_OF["activemq"]
        self.assertEqual(s.main_port, 8161)
        self.assertEqual(tuple(s.port_offsets), ())
        self.assertEqual(tuple(s.extra_ports), (61616,),
                         "61616 与 8161 没有固定偏移，必须走独立基准（spec 计划二 D6）")
        self.assertEqual(s.port_writeback, "conf_copy")
        self.assertEqual(s.stop_kind, "port_lookup")
        self.assertEqual(s.min_java_major, 17)   # 证据：bin/activemq.jar class major 61
        self.assertEqual(s.startup_timeout, 60)

    def test_activemq_env_points_at_the_copy_and_the_data_dir(self):
        """厂商机制实测：bin/activemq.bat 显式传 -Dactivemq.conf / -Dactivemq.data，
        且这俩变量"未设才回落到安装目录"——所以注入 env 就够，不必碰官方文件。"""
        env = main.LAUNCH_OF["activemq"].extra_env
        self.assertEqual(env.get("ACTIVEMQ_CONF"), "{conf_dir}")
        self.assertEqual(env.get("ACTIVEMQ_DATA"), "{data_dir}")

    def test_activemq_uses_the_bat_not_the_service_wrapper(self):
        """win64/activemq.bat 是 wrapper.exe -c wrapper.conf（服务包装器），
        与"不注册系统服务"冲突，不许出现在登记里。"""
        argv = main.LAUNCH_OF["activemq"].commands["Windows"]
        self.assertIn("bin/activemq.bat", argv[0])
        self.assertNotIn("win64", argv[0])
        self.assertEqual(argv[1], "console")

    def test_data_note_is_required_for_plan_two_components(self):
        """计划一的"停止后数据保留"承诺对 Nacos 不成立（derby 在版本目录里）。
        不写 data_note 就等于在卸载确认里说假话。"""
        for key in ("nacos", "activemq"):
            self.assertTrue(main.LAUNCH_OF[key].data_note, f"{key} 必须说明数据去处")

    def test_uninstall_confirm_text_carries_the_data_note(self):
        """卸载确认必须把"数据去哪儿了"写进去。计划一只说了"删除已安装版本 + 清环境变量"，
        那句话对 Nacos 是半句真话（它的 derby 在版本目录里，会跟着一起没）。
        抽成纯函数是为了这条断言真能跑到文案，而不是只检查字段有没有填。"""
        for key, needle in (("nacos", "安装目录"), ("activemq", "activemq-data")):
            comp = next(c for c in main.build_components() if c.key == key)
            text = main.uninstall_confirm_text(comp)
            self.assertIn(needle, text, f"{key} 的卸载确认没讲清数据去处")
            self.assertIn(comp.display_name, text)

    def test_uninstall_confirm_text_keeps_plan_one_wording_for_jenkins(self):
        comp = next(c for c in main.build_components() if c.key == "jenkins")
        text = main.uninstall_confirm_text(comp)
        self.assertIn("jenkins-data", text,
                      "Jenkins 的数据在 ~/.env-tools 下、卸载后保留——这句话不能因为本期改动而丢")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py LaunchSpecTable`
Expected: FAIL，`TypeError: LaunchSpec() got an unexpected keyword argument 'data_note'` / `KeyError: 'activemq'`

- [ ] **Step 3: 写最小实现**

`LaunchSpec` 末尾加字段（仍是有默认值区段）：

```python
    # 卸载确认里必须显示的数据去处。Nacos 的 derby 在版本目录内（卸载即连带删除），
    # ActiveMQ 的数据与 conf 副本在 ~/.env-tools 下（卸载后保留）——
    # 一句"数据会被清理"含混带过就是拿计划一的承诺说假话。
    data_note: str = ""
```

`LAUNCH_OF` 加：

```python
    "activemq": LaunchSpec(
        # 实测（2026-10-05，apache-activemq-6.3.2）：
        #   控制台口 conf/jetty-spring.properties:35 jetty.http.port=8161
        #   broker 口  conf/activemq.xml:178        name="openwire" tcp://0.0.0.0:61616
        #   bin/activemq.bat:74/76 "未设才默认" + :99 传 -Dactivemq.conf/-Dactivemq.data
        # 所以端口只写 data 目录里的 conf 副本，官方目录零改动。
        commands={"Windows": ["{home}/bin/activemq.bat", "console"],
                  "Linux": ["{home}/bin/activemq", "console"],
                  "Darwin": ["{home}/bin/activemq", "console"]},
        stop_kind="port_lookup",
        main_port=8161,
        port_offsets=(),
        extra_ports=(61616,),
        port_search_span=99,
        port_writeback="conf_copy",
        extra_env={"ACTIVEMQ_CONF": "{conf_dir}", "ACTIVEMQ_DATA": "{data_dir}"},
        console_path="/admin",           # 待真机 A3 确认
        health_path=None,
        needs=("jdk",),
        min_java_major=17,
        data_dir_env=None,
        startup_timeout=60,
        risk_note=(
            "ActiveMQ 默认监听 0.0.0.0，Web 控制台默认账号 admin/admin"
            "（conf/users.properties 实测）。首次启动会在 ~/.env-tools/activemq-data/conf"
            "建立配置副本，此后副本是权威：换版本不会自动合并厂商新增默认项。"
        ),
        data_note=("数据与配置副本在 ~/.env-tools/activemq-data（含 conf 副本、broker 存储与日志），"
                   "卸载只删版本目录，这份会保留；要彻底清理请手动删除该目录。"),
    ),
```

`nacos` 条目补 `data_note`：

```python
        data_note=("运行数据（derby）在安装目录内的 data/ 下，卸载会连带删除；"
                   "要保留数据请先把它复制到 ~/.env-tools 之外。"),
```

把 `on_uninstall_clicked` 里那段确认文案的**拼装**抽成模块级纯函数（按钮槽继续负责弹窗与守卫）：

```python
def uninstall_confirm_text(comp: Component) -> str:
    """卸载确认的正文。数据去处必须写明且按组件区分：
    Jenkins 的数据在 ~/.env-tools/jenkins-data、卸载后保留；
    Nacos 的 derby 在版本目录里、会跟着一起删；ActiveMQ 两者都有（副本 + 存储在 ~/.env-tools 下）。
    一句含混的"数据会被清理"对其中任何一个都是假话。"""
    text = f"删除 {comp.display_name} 已安装的版本，并清理它的环境变量与 PATH 条目。"
    note = getattr(comp.launch, "data_note", "") if getattr(comp, "launch", None) else ""
    if not note:
        # 不可启动的组件没有 launch 描述符，退回计划一那句既有说法（保留原措辞，别改口径）
        note = "本工具只会删除它自己管理的安装目录，不会碰你手工放到别处的文件。"
    return text + note
```

Jenkins 也要有 `data_note`（否则新用例断言的 `jenkins-data` 无处来）——在 `"jenkins"` 条目里补：

```python
        data_note=("任务、插件与配置都在 ~/.env-tools/jenkins-data 下，卸载只删版本目录、"
                   "这份数据会保留；要彻底清理请手动删除该目录。"),
```

槽函数改为用这个函数取正文（其余逻辑与守卫原样不动）。执行时**先读现有实现**：
如果计划一的卸载确认里已经把 `<key>-data` 的去处讲清了，就把那句原文并进 `uninstall_confirm_text`
并保持字面不变（新用例只加不断），**不要**留两份"数据在哪里"的说明。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_launch_tests.py`
Expected: `Ran 123 tests ... OK`

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add main.py bt_launch_tests.py
git commit -m "feat(launch): ActiveMQ 接入启动登记，卸载确认按组件说明数据去处"
```

---

### Task 10: 真机演练扩到两个组件（A1–A7 判据）

**Files:**
- Modify: `bt_real_machine_drill.py`（`launch_drill`，现 `:240`；参数解析不动）
- Test: 无新增离线用例（本任务只改脚本；离线护栏已在 Task 1–9 建完）

**Interfaces:**
- Consumes: `SERVICE_MANAGER.start/stop/force_stop`、`main.load_running_map`、`main.RunRecord.ports`、`main.port_is_listening`、`main.http_ok`
- Produces: `bt_real_machine_drill.py --launch nacos|activemq|jenkins [--yes]`，输出四行判据 + 一份 A1–A7 结论

- [ ] **Step 1: 先看清当前判据形状**

打开 `bt_real_machine_drill.py`，读 `launch_drill()` 全文（现 `:240-283`）与入口分派（现 `:278-283`）。
**不要照抄本计划下面的代码就开始改**——计划一的演练里有"Windows 上 `stop` 只请示、脚本替用户点是"
的既有处理，改动要保住它。

- [ ] **Step 2: 把三层判据扩成四条，并按簇复查**

```python
    def cluster_state(ports, label):
        """端口簇逐个体检。计划一只看 rec.port 一个口，本期两个组件是三口/两口，
        只看主口会得出"停干净了"的假结论——主口掉了 gRPC 还在听也算没停。"""
        live = [p for p in ports if main.port_is_listening(p)]
        print(f"      {label}: {list(ports)} 在听={live or '无'}")
        return live

    rec_ports = tuple(rec.ports) or (rec.port,)
    live_before = cluster_state(rec_ports, "停止前")
    ...
    live_after = cluster_state(rec_ports, "停止后")
    left = main.load_running_map()
    print(f"[4/4] 登记残留={list(left)}")
    if not stop.ok or rec.key in left or live_after:
        return 1
    if not got:
        print("演练失败：控制台不可达 —— 端口在听不等于服务可用")
        return 1
    return 0
```

- [ ] **Step 3: 加 A1–A7 结论记录**

`--yes` 分支跑完后逐条打印待验证项，**未跑的那半不许写成通过**：

```python
    print("\n--- 计划二待验证项（只有 --yes 真跑才有结论）---")
    print("A1 整簇端口是否随停止一起释放：", "PASS" if not live_after else "FAIL")
    print("A2 实际监听集合是否等于登记的簇：", list(live_before or []), "登记为", list(rec_ports))
    print("A3 控制台路径：", console_url, "可达=", got)
    print("A4 Nacos --server.port 是否压过 application.properties：",
          "若主口实测端口 == 我们指定的端口 → PASS（否则 Nacos 要改走 conf_copy，回补设计）")
    print("A5 ActiveMQ console 是否前台不弹独立窗："
          "（人工确认任务管理器里 java.exe 数量与窗口）")
    print("A6 -Djetty.http.port 能否压过 conf：本期未尝试，保持"未验证"")
    print("A7 结论请回写两份 spec：计划一 §2.4 第 2、4 项；计划二 §8.2")
```

- [ ] **Step 4: 干跑验证（这是本任务的通过判据）**

Run: `.venv/Scripts/python.exe bt_real_machine_drill.py --launch nacos`
Expected: 只打印 `[dry-run]` 一行（含"程序目录 + 数据目录"），退出码 0；`tasklist` 里没有 java 进程新增；`~/.env-tools/running.json` 不存在（本机现状）；**不产生 `activemq-data`/`nacos-data` 目录**。
Run: `.venv/Scripts/python.exe bt_real_machine_drill.py --launch activemq` → 同上，且 dry-run 打印的数据目录是 `~/.env-tools/activemq-data`。
Run: `.venv/Scripts/python.exe bt_real_machine_drill.py --launch jenkins` → 计划一行为不变（回归确认）。
Run: 不带参数 → 原 bun 多版本演练路径行为不变。

**`--yes` 不在本任务的验收里**：它需要用户在场并下载组件（Nacos 153MB / ActiveMQ 57MB），属真机动作。
如实报告"未执行"，不许把没跑过的记成通过。

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add bt_real_machine_drill.py
git commit -m "test(drill): 启动演练判据扩到端口簇，并记录计划二 A1-A7 待验证项"
```

---

### Task 11: 文档、规则 R5 更新与全量回归

**Files:**
- Modify: `DEVELOPMENT.md`（R5.2 / R5.3 / R5.6）
- Modify: `CODE_WIKI.md`（§4.5、§4.6、§6 数据流、§4.9 套件计数）
- Modify: `README.md` / `README_EN.md`（一句话：支持组件从"Jenkins"扩到三个）
- Modify: `docs/superpowers/specs/2026-10-05-one-click-launch-design.md`（§8 验收按两期分别收口的措辞）

- [ ] **Step 1: 更新 R5，把本期兑现的从"待办"里划掉**

`DEVELOPMENT.md` 的 R5.2「计划一遗留 / 计划二待办」清单里，**本期真正做完的只有下面这两条**，
把它们改成"已做，见 §x"；其余**一条都不许划掉**——它们仍是下一个组件要回看的清单：
- `RunRecord` 新增字段必须带默认值（Task 3 兑现，并留了旧格式迁移用例）；
- 端口簇/独立口的表达（Task 1、6 的 `port_offsets` + `extra_ports`）。

**没做、必须原样留在待办里的**：
- 畸形外来记录被 `save_running_map` 抹掉（本期只处理了"旧格式缺字段"，没处理"外来记录形状不对"）；
- `force_stop` 在 Windows 发 9 而非 15（同 API，仅退出码误导）；
- 跨进程 advisory lock —— 并把"现在三个组件、Nacos 还多两个 gRPC 口，GUI 与演练脚本并跑更容易撞"写进去；
- 卡片销毁等待在跑 worker、`_COMPONENTS_CACHE` 不失效、`launch_label` 无 QSS、测试里 `"8080"` 字面量泛化。
- `force_stop` 在 Windows 发 9 而非 15 → 本期仍不改（同 API，仅退出码误导），保留待办；
- 跨进程 advisory lock → 本期仍不做，保留待办，并把"Nacos + ActiveMQ + Jenkins 三口并跑时更容易撞"写进去；
- 卡片销毁等待 worker、`_COMPONENTS_CACHE` 不失效、`launch_label` 样式 → 保留。
新增 R5.3 第 8、9 条：

```markdown
8. 端口簇的三种角色分开表达：派生口走 `port_offsets`（跟主口位移），独立口走 `extra_ports`
   （自己的基准），"运行中"必须整簇都在听；只判主口会把半死的 Nacos 报成运行中。
9. 端口回写只允许写 `~/.env-tools/<key>-data` 下的副本；厂商官方文件在任何策略下都不被修改。
   锚不到官方默认那一行时**拒改并指名要改哪一行**，不许猜用户的改法。
```

R5.6 的用例清单补上本期新增类名（`NetstatParse`、`ConfCopyWriteback`、`PortPlanning`），并把
"检测路径绝不执行进程"那条改写成含**反向断言**（`force_stop` 确实会调用端口反查）。

- [ ] **Step 2: CODE_WIKI 与 README 同步**

- §4.6 业务逻辑层表格加 `choose_ports` / `prepare_ports` / `parse_netstat_listeners` / `prepare_conf_copy`。
- §6 数据流那节（计划一加的）把"单端口"改成"端口簇"，并写明停止路径多了一步端口反查。
- §4.9 套件表把 `bt_launch_tests.py` 的用例数改成本期实测值（**跑出来多少写多少**，别沿用 80）。
- `README.md` / `README_EN.md`：把"当前支持 Jenkins"改成支持 Jenkins + ActiveMQ + Nacos，
  并**保留真机验证状态那句话**——`--yes` 仍未执行时，三层表述（已实现 / 离线护栏 / 真机待验证）不许降级成"已验证"。

- [ ] **Step 3: 全量回归（9 套件，按 `ls bt_*_tests.py` 数出来）**

```bash
for t in launch boot_script startup gitee_sync component_category mirror_spec search_and_newcmp refresh_versions multiversion; do
  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u bt_${t}_tests.py
done
```
Expected: 全部 `OK`。`bt_multiversion_tests` 需 `PYTHONIOENCODING=utf-8`（既有 GBK 控制台债，不修）。

- [ ] **Step 4: 变异自检——护栏是不是空的（四处，逐条恢复）**

1. `ServiceManager.status` 改回"只看 `rec.port`" → Task 7 的簇用例必须红；
2. `_pick_unique_pids` 改成"取 `next(iter(...))` 不判长度" → 歧义用例必须红；
3. `prepare_ports` 的 `conf_copy` 分支改成"回写失败也继续拉起"（忽略返回值） → Task 6 的阻止拉起用例必须红；
4. 把 `netstat_listener_pids` 调用挪进 `status()` → `NoExecInvariant` 的正向那条必须红。
全部恢复后重跑 Step 3。

- [ ] **Step 5: 提交（实现者自己执行；不 push、不 merge、不打 tag）**

```bash
git add DEVELOPMENT.md CODE_WIKI.md README.md README_EN.md docs/superpowers/specs
git commit -m "docs: R5 兑现条目与两条新硬约束、CODE_WIKI/README 同步计划二"
```

---

## 完成定义（计划二）

1. Windows 上 ActiveMQ、Nacos 各完成一次真机演练（§8.2 A1–A7 有结论并回写两份 spec）；
   在此之前，文档与文案一律保持"已实现 / 离线护栏守护 / 真机待用户在场验证"三层，**不得写成已端到端验证**。
2. 离线：`bt_launch_tests.py` 全绿（约 123 用例，按实际数出来写进文档），四处变异自检各自红过。
3. 原 9 套件无回归。
4. 演练干跑判据通过：`--launch nacos|activemq|jenkins` 只打印将做什么、退出 0、无新进程、无新目录、无 `running.json`。
5. 全程未修改任何厂商官方文件（Task 6/9 的"官方文件一个字节不动"用例是这条的证据）。
6. `--yes` 真机执行**必须用户在场**才做；未做就不算验收完成，也不允许在文档里当作做过。
