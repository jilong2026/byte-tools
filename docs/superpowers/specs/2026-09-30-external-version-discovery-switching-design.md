# 识别并切换「用户自己安装的版本」· 设计文档 v2

日期：2026-09-30　状态：**v2.1 评审通过**（发现源范围 ① 与真机演练完成标准 ② 均已确认），可转实施计划
前置：规则 R3（组件多版本与生效版本切换）已落地；本文档为 v2（v1 未提交，已被本版整体替换）

## 0. v2 相对 v1 的变化（为什么重写）

v1 把"不改系统级（HKLM）变量"列为非目标。随后真机实测证明：**只改用户级根本切不动命令行**，
于是那条非目标会让整个功能变成"只能看不能用"。用户已明确选择"要能真切换，接受提权改系统变量"，
提权方式为**每次切换弹一次 UAC、由程序拉起一次性助手进程**。

v2 因此新增 §5.4（提权接管 HKLM）并把"绝不把系统 PATH 改坏"提升为与功能同等级的硬约束（§7、§9）。

### v2.1 增补（2026-09-30 用户评审通过）

用户批准**为 Python 单独加一条权威登记处发现源**（§5.1 第 4 步），其余组件维持"工作区 + 环境变量"。
依据是同一天在本机的两组实测，结论对两个组件正好相反：

- **JDK 不需要**：`HKLM\SOFTWARE\JavaSoft\JDK`、`WOW6432Node\JavaSoft\JDK`、`HKCU\SOFTWARE\JavaSoft\JDK`
  三处**全为空**（本机 JDK 是解压装到 `E:\soft\jdk\` 的，不是 MSI 装的）。加这条源等于加一条
  在这类装法下永不命中的代码路径；本机真正能发现它的是 `JAVA_HOME`（值 `%jdk21%`，见 §3）。
- **Python 确实漏**：`py -0p` 在本机报两个解释器，
  `-V:3.14 → …\Programs\Python\Python314\python.exe`（PATH 里有，现有逻辑能发现）与
  `-V:Astral/CPython3.12.12 → …\AppData\Roaming\uv\python\cpython-3.12.12-…\python.exe`
  （**不在 PATH、也没有 `PYTHON_HOME`**，现有逻辑完全看不见）。即"工作区 + 环境变量"对 Python 是**少报**的。
- **nvm / Go 不加**：本机无 nvm 目录、无 `C:\Program Files\Go`；Maven / Gradle 只是目录、
  Go 官方 MSI 只装一份、Bun 固定在 `~\.bun\bin`，PATH + HOME 扫描对它们是完备的。
  将来若真机出现漏报，按同样标准（"权威登记处一定知道、PATH 不一定知道"）再逐个加，不预先建框架。

## 1. 目标

1. **识别**：列出本工具工作区版本 + 从环境变量能发现的外部版本，并标出命令行实际用的是哪个。
2. **切换**：允许把生效版本切到外部版本（含用户自装的多个 JDK），必要时提权改系统变量。
3. **可还原**：任何一次接管都留下完整快照，界面上常驻「还原到我之前的设置」，重启后仍然可还原。
4. **不撒谎、不砖化**：改完必须复验"新进程真的用到它"，不过就回滚并说明；
   改系统 PATH 前后必须校验，绝不允许把 `system32` 这类关键条目弄丢。

## 2. 非目标

- 除 **Python 一条**权威登记处（§5.1 第 4 步，v2.1 增补）外，不做其它组件的登记处特例
  （JavaSoft 注册表、nvm-windows 的 settings.txt、Golang 列表都不做——理由见 §0 v2.1）。
  除此之外发现源仍是"工作区 + 环境变量"。
- 不删、不移、不改名外部安装目录；外部版本不参与卸载，也不参与"清理残留 PATH"。
- 不做"进入某目录自动切换"的 shell 钩子，不写用户项目的 pom/gradle/IDE 配置（沿用 R3.6）。
- 不把主程序设为常驻管理员运行（提权只发生在用户点那一次「切换」上）。
- 外部版本不进版本下拉框（§6、R3.4）。

## 3. 已实测的前提（全部来自本机真机测量，非推断）

| # | 结论 | 实测方式 |
|---|---|---|
| E1 | 同名变量 HKCU 覆盖 HKLM | `TEMP`/`TMP` 两 hive 都有，进程取到 HKCU 的值 |
| E2 | 用户 PATH 整体排在系统 PATH **之后**，抢不过系统级同名命令 | 进程 45 条 PATH：系统条目占 17–34，用户条目占 38–42 |
| E3 | 本机 `HKLM JAVA_HOME = %jdk21%`，另有 `jdk8/jdk17/jdk21` 三个变量各指一个 JDK；系统 PATH 含 `%JAVA_HOME%\bin` | 读注册表 |
| E4 | **改 HKCU `JAVA_HOME` 能覆盖成功，但系统 PATH 里那条 `%JAVA_HOME%\bin` 不会跟着变**（在合并用户变量前就按系统表展开定死） | 可逆实测 + `CreateEnvironmentBlock` 三次读数 |
| E5 | `CreateEnvironmentBlock` 可用，但拿令牌只要 `TOKEN_QUERY(0x0008)`；用 `PROCESS_QUERY*` 在受限环境会被拒（error 5） | 实测；单次调用 2.5 ms |
| E6 | 本机 jdk/maven/bun/node 四个组件，工作区版本**全部**被更靠前的条目压住（`shadowed`） | 只读跑 `_path_effective_check` |

E4 + E2 ⇒ **要真切换必须动 HKLM**。E5 ⇒ 复验手段可用。E6 ⇒ 这不是理论问题，是当前的既成事实。

## 4. 数据模型

### 4.1 发现结果

```python
@dataclass
class DiscoveredVersion:
    home: Path          # 安装根目录（不是 bin）
    source: str         # "workspace" | "env:<变量名>" | "path:<HKCU|HKLM>"
    version: str = ""   # 工作区来自目录名；外部来自真实探测（探测失败不列入，§5.1 第 5 步）
```

### 4.2 配置（`config.json` 新增顶层键 `takeover`）

`active` 的现有格式**不变**（仍只登记工作区版本号）。新增：

```json
{
  "takeover": {
    "jdk": {
      "home": "E:\\soft\\jdk\\jdk17",
      "version": "17.0.12",
      "level": "machine",
      "snapshot": {
        "JAVA_HOME": {"hive": "HKLM", "raw": "%jdk21%", "type": "REG_EXPAND_SZ", "existed": true},
        "Path":      {"hive": "HKLM", "raw": "C:\\Windows\\system32;...%JAVA_HOME%\\bin...",
                       "type": "REG_EXPAND_SZ", "existed": true}
      },
      "backup_file": "takeover-backups/jdk-20260930T1015.json"
    }
  }
}
```

- `raw` 存的是**注册表里未展开的原文**（见 §5.4 的"最小文本编辑"），还原时按原 `type` 写回。
- `existed=false` 表示"改之前这个 hive 里根本没有这个值"，还原时必须**删除**而不是写空串。
- `backup_file` 是同一份快照落盘的独立文件（config.json 万一写坏，还原仍然可用）。
- `level` 取 `user`（只改了 HKCU）或 `machine`（改过 HKLM），决定还原要不要再弹一次 UAC。
- 写入沿用已有的原子写（临时文件 + `os.replace`）与合并写规则（R3.2），`takeover` 不得覆盖 `active`。
- 读侧只接受形状合法的条目（`home`/`version` 非空字符串、`snapshot` 为 dict），其余跳过。

### 4.3 生效目标（单一真源）

```python
@dataclass
class ActiveTarget:
    kind: str        # "workspace" | "external"
    version: str
    home: Path
    level: str       # "user" | "machine" | ""（工作区固定 user）
```

`active_target(comp)` 解析顺序：`active[key]`（工作区）→ `takeover[key]`（外部）→
`infer_active_from_env` → PATH 实际命中（后两者只认工作区目录内）。

**两条键互斥**：`apply_active_version()`（切回工作区）成功后必须删除 `takeover[key]`
并按快照还原它写过的变量；`apply_external_version()` 成功后必须删除 `active[key]`。
不允许出现"登记表说工作区 17、快照还挂着外部 home"这种两边都不认的孤儿态。

`ComponentCard.active_version()` 改为 `active_target()` 的薄封装，仍返回版本号字符串，
既有调用方（按钮启用、胶囊、卸载重排）不需要各自再判一次来源。

## 5. 发现与切换

### 5.1 发现 `discover_versions(comp) -> List[DiscoveredVersion]`

只对 `multi_version` 的 7 个组件运行。

1. 工作区：`installed_versions(comp)` → `source="workspace"`。
2. 环境变量：枚举 HKCU `Environment` 与 HKLM `Session Manager\Environment` 的**全部值**
   （**排除 `Path` 本身**，它由第 3 步处理），对每个展开后的值 `V`：
   `comp.exec_path_in_home(V)` 命中 → 候选 `home=V`，`source="env:<名>"`。
   （本机 `jdk8/jdk17/jdk21` 三个变量因此各自被发现 —— 这正是用户要的"多个自装版本"。）
3. PATH：枚举两 hive 的 `Path` 条目 `P`，若 `P` 下直接有该组件可执行文件，
   则 `home = P.parent if P.name ∈ {bin, Scripts, cmd} else P`，`source="path:<hive>"`。
4. **Python 专属登记处**（仅 `comp.key == "python"` 且 Windows）：
   首选 `py -0p`（子进程、超时 5 秒、只读），按行解析出 `路径` 与 `-V:` 标签；
   拿不到 `py`（未安装 py 启动器）时退回读注册表
   `HKCU|HKLM\Software\Python\<公司>\<版本>\InstallPath` 的默认值（含 `Astral` 这类非 `PythonCore` 的公司键）。
   `source="registry:py"`。**这一步是唯一能发现"不在 PATH 也不在任何变量里"的版本的**（本机 uv 那份就是）。
   登记处结果同样要过第 6 步的真跑校验，且**只列不接管**：不写它的目录、不替它删。
5. 归一化去重（`EnvManager._same_path`），同一路径同时是工作区与外部时保留 `workspace`；按版本降序。
6. **外部候选必须真跑一次版本命令才列入**（复用 `VersionProbeWorker`，异步、有超时）。
   探测失败/超时/解析不出的候选**丢弃**并在运行日志写一行 warn —— 宁可不显示，
   也不显示一个"认错了的目录"。工作区候选不需要这一步。

结果缓存在卡片实例，胶囊与折叠区共用同一份，避免重复起探测线程。

### 5.2 复验（已实现，本期沿用并扩展）

`EnvManager.composed_env()`（E5）→ `_path_effective_check(active)` 返回三态：
`ok` / `shadowed(抢命令的目录)` / `unknown(拿不到或 PATH 里没有该命令)`。
`unknown` 一律按"未能复验"处理，**不许当成通过**。当前已上线的切换已在用这套（见 git 历史）。

### 5.3 用户级接管 `apply_external_version_user(comp, dv)`

先走不需要提权的那一步，能成就不弹 UAC：

1. 快照 HKCU 的 `comp.env_var` 与 `Path` 原文（`existed` 标志照 §4.2）。
2. 写 HKCU `env_var = str(dv.home)`（REG_SZ 存展开后的绝对路径）；
   若复验显示命令被别处抢走，把 `dv.home/<path_subdir>`（无 subdir 则 home）**前置**进 HKCU `Path`。
3. 同步本进程 + 广播 `WM_SETTINGCHANGE`（`PostMessageW`，不用 `SendMessage*`）。
4. 复验（§5.2）。三种结论分别处理，**只有 `shadowed` 才允许升级到提权**：
   - `ok` → 写 `takeover[key]`（`level="user"`），结束。
   - `shadowed` → 用户级确实压不住，转 §5.4 征求提权。**不回滚用户级这一层**（它本身没写错，
     只是不够），但要在日志里说明"用户级已改，命令行仍被 X 压住，需要提权"。
   - `unknown` → **不升级**。拿不到复验结果不等于"失败了"，为它去弹 UAC 改系统变量是无据升级；
     如实报"未能复验，请重开终端确认"，并保留用户级快照。

### 5.4 提权接管 HKLM `apply_external_version_machine(comp, dv)`（本期最高风险面）

**触发**：只有用户在折叠区点了「切过去」且 §5.3 复验没通过时才走到这里，
且必须先弹一个确认框，逐条列出"要改什么、改成什么、原来是什么"，写明"需要管理员权限"。

**助手进程**：主程序用 `ShellExecuteW("runas", <自身>, "--bt-elevate <请求文件>")` 拉起一次性助手
（同一个 exe，dev 下是 `python main.py`，打包后是 `byte-tools.exe`，两条路都要能跑）。
返回值 ≤32 视为失败；`1223(ERROR_CANCELLED)` 单独识别为"用户取消了 UAC"。
主程序轮询请求文件里指定的结果文件（有界等待，超时 90 秒）。**超时不等于失败**：
助手可能已经写了注册表却没来得及回报，所以超时后主程序必须自己重读两 hive 原文判定实际状态，
再决定"报成功并补写快照 / 报失败并按快照回滚"，绝不允许凭超时直接下结论。全程不阻塞界面线程。

**请求/结果协议**（JSON，写在系统临时目录，助手用完删除）：
请求 = `{env_var, home, remove_entries:[...], add_entry:"...", result_file}`；
结果 = `{ok:bool, stage:"read|write|verify|rollback", error:"...", before:{...}, after:{...}}`。

**助手侧的硬规则**（每条都要有测试或防呆对应）：

- **R-保真**：HKLM 的 `Path`/`JAVA_HOME` 一律用 `winreg.QueryValueEx` 读**未展开原文**，
  写回也写原文，并保持原 `REG_EXPAND_SZ` 类型。
  **禁止**用 `os.environ["PATH"]` 或任何展开后的值参与写入 —— 那会把 `%JAVA_HOME%` 这类
  占位符固化成死路径，破坏其他软件（这是把系统 PATH 改坏的头号方式）。
- **R-最小编辑**：只在原文上做"整条删除 / 整条插入"，分隔符固定 `;`，不重排、不去重、不改大小写、
  不合并重复项；插入位置为最前。除目标条目外，其余字符必须逐字不变。
- **R-先备份**：写入前把两 hive 的原文快照写进 `backup_file`（§4.2），写成功才写 `config.json`。
- **R-关键条目校验**：写完后立刻重读原文，断言 `C:\Windows\system32`、`C:\Windows`
  以及原值里所有"非本组件的条目"仍然逐条存在；少任何一条 → 立即用快照回滚 → 报"已放弃，系统 PATH 未被改动"。
- **R-原子性**：`JAVA_HOME` 与 `Path` 两次写，第二次失败必须回滚第一次。
- **R-复验**：助手退出前自己跑一次 `composed_env()` 判断是否命中目标 home，把结论写进结果文件；
  主程序再独立复验一次（不信任助手的话）。任一不过 → 自动还原（还原同样需要 UAC）。

**还原** `revert_external_version(comp)`：读 `takeover[key].snapshot`，按 `level` 决定
是否再弹一次 UAC；逐 hive 写回原文（`existed=false` ⇒ 删除该键），移除我们插过的那条 PATH，
广播，删 `takeover[key]`，重新探测。还原按钮只在存在 `takeover[key]` 时出现，重启后仍在。

## 6. 界面

- 版本下拉框**不变**：只放工作区版本 + 内置可下载版本，绿勾语义不变。外部版本绝不进下拉框
  （条目文本是 `_current_version()` 与 `repopulate(preferred=…)` 的反查键，R3.4）。
- 卡片上新增折叠区「系统里检测到的版本」（仅多版本组件、且存在外部候选时出现）：
  每行 = 版本号 + 完整路径 + 「当前在用」标记 + 一个「切过去」按钮；标题带数量，默认收起。
- 状态胶囊按来源与复验结果分档：
  - 工作区生效且复验通过：`● 已装 2 个版本 · 生效 17（21、17）`（绿）
  - 被更靠前的条目压住：`… · 但 PATH 先命中 <目录>`（橙，已实现）
  - 外部生效：`● 生效 17.0.12（系统 E:\soft\jdk\jdk17）· 工作区 2 个版本（21、17）`（绿）
  - HOME 与 PATH 不一致：`… · 未对齐：PATH 用的是 X，JAVA_HOME 指 Y（…）`（橙，已实现）
- 接管生效后，卡片上常驻「还原到我之前的设置」，tooltip 里写明改过哪些 hive 的哪些键。
- 非多版本组件的文案与按钮**逐字不变**（R3.9 护栏继续生效）。

## 7. 错误处理

| 情况 | 行为 |
|---|---|
| 外部候选探测失败/超时 | 不显示该候选；日志一行 warn |
| 用户取消 UAC（1223） | 报"已取消，未做任何改动"，不写快照、不改 config |
| 助手写入中途失败 | 助手按快照回滚 + 结果文件写失败原因；主程序再校验一次系统 PATH 完整性 |
| 写完但复验不过 | 自动还原（含再弹 UAC）+ 明确说明原因，**不报成功** |
| 关键条目校验发现 `system32` 等丢失 | 立即回滚，报"已放弃，系统 PATH 未被改动"，并把原文打进日志供人工粘贴恢复 |
| 快照指向的目录被用户删了 | 胶囊显示"之前接管的外部版本已不存在"，提示点还原或另选；不自动改环境 |
| 还原时原值已被用户手改 | 仍按快照写回，日志告知"这会覆盖你期间的手动修改" |
| `config.json` 里 `takeover` 损坏 | 忽略该条并保留 `backup_file` 指向的快照，界面上提示"从备份文件还原" |

## 8. 测试策略（TDD，先红后绿；提权路径全部可离线测）

沙箱扩展：`EnvSandbox` 增加伪造两 hive 变量清单的只读接缝（`EnvManager._list_env_values()` 之类），
以及**假助手**接缝 —— 助手的调用点抽成一个可替换函数（`_run_elevated_helper(request) -> result`），
测试里换成"按脚本返回 ok/失败/取消/丢条目"的假实现。**产品代码里不加运行时开关**：
这是可替换的进程边界（与既有 `_read_windows_user_env` 同构），不是功能开关。
`composed_env()` 在测试里桩成可控返回值（已这么用）。

必测清单：

1. 发现：塞 `jdk8/jdk17/jdk21` 三个假变量 + 假 exe → 三条候选且 `source` 正确；无 exe 的目录不入选；
   探测失败的候选被丢弃且日志有 warn。
2. PATH 归位：`E:\x\bin` 反推出的 home 是 `E:\x`。
3. 去重：同一路径既在变量又在 PATH → 只一条，优先 `env:`。
4. 复验三态：`ok` / `shadowed`（点名目录、胶囊橙色常驻、按钮仍可用）/ `unknown`（说"未能复验"，不报通过）。
5. 用户级接管成功：HKCU 写了 home、必要时前置了 PATH、`takeover` 落了快照、日志含 D6 那句。
6. 用户级不够 → 走提权：假助手返回 ok 后主程序复验通过，`takeover.level == "machine"`。
7. **保真**：给助手喂一个含 `%JAVA_HOME%\bin` 与 `C:\Windows\system32` 的原文 Path，
   断言写出的新原文里这些条目**逐字仍在原位**，只有我们那一条被插到最前，类型仍是 `REG_EXPAND_SZ`。
8. **防呆回滚**：假助手模拟"写入后 system32 那条没了" → 断言自动回滚、结果报失败、config 里没有 `takeover` 残留。
9. 取消 UAC（1223）→ 零改动、零快照、日志一句"已取消"。
10. 助手写入中途失败 → 回滚第一次写。
11. 还原：`existed=false` 的键必须被删除（不是写空串）；改过 HKLM 的还原要求再提权。
12. 两条键互斥：切工作区 ⇒ 删 `takeover` 并还原；切外部 ⇒ 删 `active`。
13. 胶囊四档文案逐字断言。
14. 回归护栏：非多版本组件文案与按钮零变化；下拉框条目文本零变化；老 `config.json`（无 `takeover`）能直接读。
15. 卸载：外部 home 永不出现在卸载候选；卸载不删外部目录。
16. 只对 7 个多版本组件运行发现（非多版本组件调 `discover_versions` 不产生外部候选）。
17. **Python 登记处**（v2.1）：桩掉 `py -0p` 的子进程边界，喂本机真实输出两行 →
    断言两条候选、home 取 `…\python.exe` 的父目录、`source == "registry:py"`；
    再断言"既不在 PATH 也没有 `PYTHON_HOME` 的那条"仍能入选（这条是本步骤存在的全部理由，
    去掉第 4 步它必须变红）；`py` 不存在时退回注册表桩（含 `Astral` 公司键）；
    注册表也没有时不报错、只是没有额外候选；非 Python 组件**绝不**调用这条源。

## 9. 风险（按危害排序）

- **R-1 把系统 PATH 改坏（最严重）**：后果是整机命令找不到。缓解 = §5.4 的 R-保真 / R-最小最小编辑 /
  R-先备份 / R-关键条目校验 / 自动回滚，以及 §8 的 7、8 两条测试。任何一条缓解缺失都不许上线。
- **R-2 提权路径不可自动化验证**：UAC 弹窗与真写 HKLM 无法在离线测试里跑。
  缓解 = 助手调用点做成可替换进程边界（假助手覆盖全部分支）+ 一次**用户在场时的真机演练**作为验收项（§10.3）。
- **R-3 复验依赖 `CreateEnvironmentBlock`**：受限环境可能失败 → 一律按"未能复验"处理，宁可不说成功。
- **R-4 外部版本号格式与工作区不一致**（`17.0.12` vs `17`）：胶囊按探测值原样显示，不做归一化猜测。
- **R-5 误伤用户自己的变量**：只对白名单 7 个组件、且只在显式点击后改；改前确认框列出全部将要变更的键值。

## 10. 完成定义

1. §8 十七条测试全绿，既有 7 套无回归（当前基线 152 + 9 + 26 + 27 + 3 + 4 + 16 = 237）。
2. `main.py` 与测试文件保持 LF；`DEVELOPMENT.md` 新增两条规则（当前到 R3.9，新规则从 R3.10 起，
   编号若被占用则顺延）：**外部版本只读发现、永不进下拉框、永不参与卸载**；
   **改系统变量必须"原文快照 + 最小编辑 + 关键条目校验 + 复验 + 可还原"五件齐全，缺一不许调用**。
   README 中英同步。
3. **真机演练（用户在场，2026-09-30 已接受为完成标准）**：本机三个 JDK 都出现在折叠区；
   把生效版本切到 `E:\soft\jdk\jdk17`，新开终端 `java -version` 与界面一致；点「还原」后
   `HKLM JAVA_HOME` 与 `Path` 原文与改动前**逐字节相同**（用导出的原文 diff 证明）。
   演练手段已固化在 `bt_real_machine_drill.py`（默认只读体检，`--yes` 才切换并保证还原），
   验收必须同时看三层：注册表真值、explorer 自己的环境块、由 explorer 现场启动的探针进程
   —— 判据与理由见 `DEVELOPMENT.md` R3.16。**本期这条已在 bun 上跑通**（双向切换三关全 PASS、
   还原与基线逐字一致），jdk / uv-Python 那份要在本功能交付时再跑一次。
4. 若第 3 条任一步做不到（例如关键条目校验挡下），界面必须给出明确原因与手工恢复步骤，
   不允许出现"报成功但实际没生效"。
