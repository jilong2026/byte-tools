# 一键启动 计划二（ActiveMQ + Nacos）设计

**日期：** 2026-10-05　**前置：** `2026-10-05-one-click-launch-design.md`（计划一，已落地于 `dev`，提交 `9d1ba00`）
**目标：** 把计划一的启动框架从"只有 Jenkins"扩到 ActiveMQ 与 Nacos，并在此过程中兑现计划一刻意留下的两个难点：
**端口需要回写配置文件**（§5 的"有边界退回"）与**脚本自我后台化导致 PID 不可信**（§4 的取舍）。

> **对执行者的要求：** 本文所有"事实"都带抓取方式与出处，改代码前请重新核对一遍——计划一有过两次
> "口述事实被实测推翻"的记录（8080→实际 8848、`jetty.xml`→实际 `jetty-spring.properties`），
> 本文自己又添了两处（见 §2.5）。凡是只能靠真机才能定下来的条目，一律写在 §9 的验收判据里，
> **不许当成已知事实拿来用**。

---

## 0. 已确认的决策（本文的地基，不再重开）

| # | 决策 | 理由来源 |
|---|---|---|
| D1 | 开工前先实测：下载两个真包、只解包读文件，不起任何服务 | 计划一的两次"口述事实"被实测推翻 |
| D2 | 范围：ActiveMQ + Nacos 一起做（原计划二不拆） | 用户选择 |
| D3 | 端口优先用**厂商覆盖机制**，回写官方文件退为备选 | 用户选择；探针证实厂商确实提供外部机制 |
| D4 | 拉起方式：**跑厂商脚本**，登记的 PID 按 launcher 处理；不复制厂商 java argv | 避免把厂商 JVM 参数/插件路径焊进我们代码 |
| D5 | ActiveMQ 端口：首次启动把官方 `conf` **整目录拷进 data 目录**，回写只改这份副本 | 厂商官方外部配置机制（`ACTIVEMQ_CONF`） |
| D6 | ActiveMQ 的 61616 走新增的 `extra_ports` 独立基准，**不再**沿用计划一"不平移"的决定 | 实测找到一个可锚定单行（§2.4） |
| D7 | 停止不用厂商脚本，改用**端口反查 PID + 三重闸**（只允许出现在 stop/force 路径） | 厂商 `shutdown.cmd` 按进程名 `taskkill /F`，会杀到用户自己起的实例 |

---

## 1. 目标与非目标

**目标**
- ActiveMQ / Nacos 在卡片上做到：点启动→端口在听→打开控制台可进→停止→**整簇端口都释放**。
- 端口被占时能自动换到可用位置，且界面与登记跟着实际端口走（补齐计划一未收口的 spec §8 第 3 项）。
- 全程不修改厂商官方文件、不写注册表、不注册系统服务、不改用户 shell rc。

**非目标（本期明确不做）**
- 崩溃自动重启、开机自启、集群模式、多实例编排。
- ActiveMQ 的 `bin/win64/activemq.bat`（`wrapper.exe -c wrapper.conf`，属服务包装器）——与"不注册系统服务"冲突，不接。
- Nacos 鉴权开启（`nacos.core.auth.enabled=false` 是包内默认），只做风险提示，不替用户改安全配置。
- 运行中改端口：端口只在未运行时决定，不做隐式重启。

---

## 2. 实测事实（2026-10-05，本机探针抓取）

抓取方式：用产品自身的 `_activemq_urls()` / `_nacos_urls()` 取 Windows 源，流式下载并用产品自己的
`extract_archive()` 解压到 `D:\tmp\btdiag\probe2`，只读文件、不执行任何 vendor 脚本。
产物：`facts.md`（ActiveMQ）、`facts-nacos.md`（Nacos）。

### 2.1 ActiveMQ 6.3.2（`apache-activemq-6.3.2-bin.zip`，57,282,451 B）

- **端口是"两处独立配置"，不是"一个基准 + 派生偏移"**：
  - `conf/jetty-spring.properties:35` → `jetty.http.port=8161`（控制台）
  - `conf/activemq.xml:178` → `<transportConnector name="openwire" uri="tcp://0.0.0.0:61616?maximumConnections=1000&amp;wireFormat.maxFrameSize=10485760"/>`（broker 客户端口）
  - `activemq.xml:184-187` 的 amqp/stomp/mqtt/ws 四行**官方默认是注释掉的**，所以只有 61616 一个 broker 口在听。
- 控制台口经 `conf/jetty/jetty-http.xml:53` 解析：`<Set name="port"><Property name="jetty.http.port" default="8080" /></Set>`。
  注意 6.3.2 的 jetty XML 全在 **`conf/jetty/` 子目录**下（计划一按 `conf/jetty.xml` 找过，路径已变）。
- **厂商外部配置机制存在**：`bin/activemq.bat:74/76` 是 `if "%ACTIVEMQ_CONF%" == "" set ACTIVEMQ_CONF=%ACTIVEMQ_HOME%\conf`
  与 `if "%ACTIVEMQ_DATA%" == "" set ACTIVEMQ_DATA=%ACTIVEMQ_HOME%\data`（**未设才回落安装目录**），
  并在 `:99` 显式传给 JVM：`-Dactivemq.conf="%ACTIVEMQ_CONF%" -Dactivemq.data="%ACTIVEMQ_DATA%"`。
- **conf 必须整目录拷贝**：`conf/login.config` 里 JAAS 用的是**相对文件名**（`org.apache.activemq.jaas.properties.user="users.properties"`），
  由 `activemq.conf` 解析。只拷单文件会让控制台鉴权静默失效。
- **不能靠设 `ACTIVEMQ_OPTS` 注入 `-D`**：`:80` 同样是"未设才给默认"，而默认值里带着
  `-Djava.util.logging.config.file=logging.properties` 与 `-Djava.security.auth.login.config=...`；
  自己重建这条变量等于把厂商内部细节焊进我们代码，漏一项就静默丢日志/鉴权配置。
- JDK 门槛：**`bin/activemq.jar` 字节码 class major = 61 → Java 17**（"哪个 JVM 能加载它"的下界证据）。
- 下载：华为云源 1 秒完成 57MB。

### 2.2 Nacos 2.3.2（`nacos-server-2.3.2.zip`，153,580,883 B）

- **Windows 是前台直跑 java，不自我后台化**：`bin/startup.cmd:92` 拼
  `set COMMAND="%JAVA%" %NACOS_JVM_OPTS% %NACOS_OPTS% %NACOS_CONFIG_OPTS% %NACOS_LOG4J_OPTS% nacos.nacos %*`，
  `:95` 就一行 `%COMMAND%` 执行——没有 `start /b`，没有后台化。自我后台化只发生在 `startup.sh`
  （`:149/:151` 的 `nohup ... &`），那是 POSIX 路径。
- **命令行参数会透传给 java**（`%*`），因此 `--server.port=<port>` 可用（Spring Boot 命令行参数优先级高于配置文件）。
  **Nacos 由此完全不需要回写任何文件。**
- `conf/application.properties:23` 是 `server.port=8848`；**该文件里没有任何 gRPC 端口属性**，
  即 9848/9849 由 `server.port` 代码派生 → 改主口自动跟（与 `port_offsets=(1000,1001)` 模型一致，仍需 §9 的 A4 实测确认）。
- `standalone` 必须显式给：`:26` 默认 `set MODE="cluster"`，`:68` cluster 分支是 `-Xms2g -Xmx2g -Xmn1g`，
  而 cluster 还要 `cluster.conf`（包内只有 `cluster.conf.example`）；`-m` 由 `:41-43` 的位置式解析取值。
- **`-p` 不是端口**：`:33-36` 显示 `-m`/`-f`/`-s`/`-p` 分别是 mode / functionMode / server / **embedded storage**。
  按 `startup.sh` 的习惯写 `-p 8848` 会错。
- `JAVA_HOME` 硬要求：`:15` `if not exist "%JAVA_HOME%\bin\java.exe"` 即打印提示并退出；`shutdown.cmd:2` 额外要
  `%JAVA_HOME%\bin\jps.exe`（JDK 而非 JRE）。
- **厂商 `shutdown.cmd` 不可用作我们的停止手段**：`:11-14` 是
  `for /f "tokens=1" %%i in ('jps -m ^| find "nacos.nacos"') do ( taskkill /F /PID %%i )`
  —— 按**进程名**匹配后 `/F` 强杀，会命中这台机器上任何一个 nacos JVM（包括用户自己在 IDE 里起的），
  且它本身就是强杀，没有优雅阶段。
- JDK 门槛：**`target/nacos-server.jar` 内 `BOOT-INF/classes/com/alibaba/nacos/Nacos.class` class major = 52 → Java 8**，
  与 `startup.cmd` / `shutdown.cmd` 里那句 "JDK8 or later is recommended" 互证。
- 数据目录：`NACOS_OPTS` 含 `-Dnacos.home=%BASE_DIR%`，derby 数据落在**安装目录内**，厂商未提供外移开关
  （`CUSTOM_SEARCH_LOCATIONS=file:%BASE_DIR%/conf/` 是写死的）。

### 2.3 对 R1 下载路径的附带观察（不改代码，仅记录）

Nacos 的 GitHub 加速器第一发**停滞**（整包读入内存的写法下表现为"卡住不动"），改成流式 + 每源硬截止 +
停滞即换源后才成功。这是下载侧的信号，不属本期范围，记此备查。

### 2.4 计划一 §2.4 待验证项：本期状态

| 计划一 §2.4 项 | 状态 | 依据 |
|---|---|---|
| 1 Nacos `startup.cmd` 的 `%COMMAND%` 拉起方式 | **已定**（文件级） | §2.2：Windows 前台 java，带 `%*` 透传 |
| 2 Nacos 控制台路径 / gRPC 属性名 | **半定**：确认无 gRPC 属性可回写（派生）；控制台是 `/` 还是 `/nacos` **仍未证** | §2.2；`application.properties:139` 白名单里有 `/` 与 `/console-ui/public/**`，无 `/nacos` 前缀 → 倾向 `/`，但以 §9 A3 实测为准 |
| 4 Windows `activemq.bat` 能否不装服务正常起 / 弹不弹独立窗口 | **未证** | 文件层只见 `:99` 前台 java 行；以 §9 A3/A5 实测为准 |
| 6 ActiveMQ 61616 的正规回写点 | **已定**：`conf/activemq.xml:178` 单行可锚定 → 本期做平移（D6 推翻计划一的"不平移"） | §2.1 |

### 2.5 本文推翻的两条计划一结论（按 §2 更正格式记录）

1. 计划一 §2.1 只把 ActiveMQ 的"控制台端口"当端口对象。**不完整**：真正决定客户端能不能连上的是 61616，
   而它与 8161 **没有固定偏移关系**，`pick_free_cluster` 的"一个基准 + 派生偏移"模型对它天然不成立 → 由 §3.2 的
   `extra_ports` 承接。
2. 计划一 §2.4 第 6 项据此决定"ActiveMQ 本期不自动平移 61616"。**该决定作废**（D6）：既然找到了可锚定的单行，
   "能改却只改一半"会造出"控制台起了、客户端连不上、界面却显示运行中"的半成功状态，比"两个都不动"更坏。

---

## 3. 框架增量

### 3.1 `LaunchSpec` 新增 `port_writeback`（端口策略）

```
port_writeback ∈ { "cli_flag", "conf_copy", "cli_only" }
  cli_flag   —— 端口只作为命令行参数注入，不碰任何文件        （Nacos）
  conf_copy  —— 端口写进 data 目录下的官方 conf 副本，并注入   （ActiveMQ）
                 <key>-data/conf 与 <key>-data 两个环境变量
  cli_only   —— 只有命令行 flag                                （Jenkins，现状不变）
```

配套：`LaunchSpec` 增加"要注入的额外环境变量"表（ActiveMQ 需要 `ACTIVEMQ_CONF`/`ACTIVEMQ_DATA`，
值要用**选完端口之后**才知道，所以必须是计划阶段拼，不能登记时写死）。

### 3.2 `LaunchSpec` 新增 `extra_ports`（独立基准）

- `port_offsets`：**派生口**，跟着主口一起平移（Nacos 的 9848/9849 = 主口 + 1000/+1001）。
- `extra_ports`：**独立口**，各自有基准与 span（ActiveMQ 的 61616）。规则与主口一致：从自己的基准起，
  在同一 span 内**升序**找第一个空闲口；找不到即失败，原因里指名是哪个口。**不做跨段随机挑选。**
- 簇的空闲判定 = 主口 ∪ 派生口 ∪ 所有独立口都空闲；但独立口的**取值**独立于主口，不随主口位移。

### 3.3 `RunRecord` 从单端口变成端口簇（含迁移硬约束）

新增 `ports: tuple = ()`。字段默认值取 `()`（"旧文件没写这个字段"），
**归一化发生在加载侧**：`load_running_map()` 见到 `ports == ()` 就按 `(port,)` 补上。
为什么必须这样：`load_running_map()` 对畸形记录是丢弃处理，若新字段无默认值，旧 `running.json` 里的记录会
**被全部静默清掉**，用户重开工具后运行中的 Jenkins 直接认不出来。
→ §8.1 的 T-迁移用例专门钉这一条；写侧则始终显式写全（不把归一化留给出盘）。

配套改动：僵尸判定、`force_stop` 的"端口确实释放"复查、端口反查，全部改成"按簇"而非"按单口"。
**本文所称"簇"= 主口 ∪ 派生口(`port_offsets`) ∪ 独立口(`extra_ports`)**，下文不再重复定义。

### 3.4 停止：端口反查 PID + 三重闸（D7）

`netstat -ano` 解析出"正在听簇内某一口"的 PID。选它而不是 PowerShell `Get-NetTCPConnection`：
不依赖外部组件、不碰 WMI（`bt_startup_tests.py` 那条"不碰 WMI"护栏继续有效）。

**位置约束（不变量）**：端口反查**只允许出现在 `stop()` / `force_stop()`**。
一旦出现在 `status()` / `adopt()` / `reconcile()` 即视为回归——那等于从后门放掉"状态检测绝不执行进程"。

动手前三重闸，缺一不可：
1. 该 key 在 `running.json` 里有我们自己的登记（外来占用者一律不动，并明确告知"这口不是本工具起的"）；
2. 反查到的 PID 不等于我们自己的进程；
3. 用户已在 `need_force` 询问中明确点"是"。

**已知残余风险（写进 spec，不藏）**：不加"进程创建时间必须晚于登记时间"这第四闸。取创建时间要么引 psutil（新依赖）、
要么走 WMI（禁用）、要么再发一次子进程调用；为一个 PID 复用窗口付这个代价不值。
残余情形是"我们登记的子进程已退出、其 PID 被复用、而我们恰好按端口查到它"，兜住它的是第 1、3 闸，不是时间戳。

---

## 4. 组件登记（具体取值）

### 4.1 Nacos 2.3.2

```
commands(Windows)   = ["{home}/bin/startup.cmd", "-m", "standalone", "--server.port={port}"]
env 注入            = JAVA_HOME（startup.cmd:15 硬要求）
main_port           = 8848
port_offsets        = (1000, 1001)        # 9848/9849 派生（待 §9 A4 实测确认）
extra_ports         = ()
port_writeback      = cli_flag
stop_kind           = shutdown_command    # 但按 D7 不执行厂商脚本，见 §6
pid_role            = launcher            # 我们的直接子进程是 cmd.exe
console_path        = "/"                 # 待 §9 A3 确认（"/" vs "/nacos"）
health_path         = None                # 待 A3 回填；判活按簇做 TCP（三口全听才算运行中）
needs               = ("jdk",)
min_java_major      = 8                   # 证据：§2.2 class major 52 + 包内脚本文字
data_dir_env        = None                # 厂商未提供外移开关，见 §2.2 末条
startup_timeout     = 90                  # derby 首启慢于 Jenkins
risk_note           = 默认监听 0.0.0.0、默认无鉴权（nacos.core.auth.enabled=false）、
                      控制台默认账号 nacos/nacos、derby 数据落在安装目录内（卸载会连带删除）
```

`commands(Linux/Darwin)` 同形（`startup.sh -m standalone --server.port=`），但按 §10 标未验证；
且 POSIX 侧是 `nohup ... &` 自我后台化，`pid_role` 与停止语义都不同 → 验证前不许当作已支持。

### 4.2 ActiveMQ 6.3.2

```
commands(Windows)   = ["{home}/bin/activemq.bat", "console"]
env 注入            = JAVA_HOME + ACTIVEMQ_CONF={data_dir}/conf + ACTIVEMQ_DATA={data_dir}
main_port           = 8161
port_offsets        = ()
extra_ports         = (61616,)            # 独立基准，同 span 内升序找空
port_writeback      = conf_copy
stop_kind           = shutdown_command    # 同上，不执行厂商脚本
pid_role            = launcher
console_path        = "/admin"            # 待 §9 A3 实测确认
health_path         = None
needs               = ("jdk",)
min_java_major      = 17                  # 证据：§2.1 class major 61
data_dir_env        = None                # 走 env 注入表而非单一 *_HOME
startup_timeout     = 60
risk_note           = 控制台默认账号 admin/admin（conf/users.properties 实测）；默认监听 0.0.0.0；
                      首次启动会在 data 目录生成 conf 副本，此后该副本是权威（换版本不会自动合并厂商新增默认项）
```

`console` 而非 `start`：`start` 在 POSIX 侧靠 `start-stop-daemon` 后台化，Windows 无对应机制，
而 `:99` 那行本来就是前台 java；真机若证否（§9 A5），改法只在登记处，不动框架。

**两处 `startup_timeout`（90 / 60）是估计值，不是实测结论**——它们只是"有界等待多久判失败"的调优参数，
不是关于厂商包的事实，所以允许先给值；但 §9 A5 之后必须按实测耗时回头校准（判据：实测启动耗时的 2 倍向上取整到 10 秒），
不许反过来拿它当证据说"ActiveMQ 60 秒起得来"。

---

## 5. 启动时序与回写事务边界

```
门控 → 选端口（主口 + 派生口走簇算法；独立口按自己基准另找）
     → 端口准备（按 port_writeback 分派）
          cli_flag   ：只算参数，不碰文件
          conf_copy  ：确保副本 → 幂等回写两行（各留一次备份）
          cli_only   ：无操作
     → 建数据目录 → 生成计划（含 env 注入）→ 脱离拉起 → 有界探活（整簇）→ 写登记 → 刷新卡片
```

三条硬边界：

1. **回写在拉起之前，且回写失败必须阻止拉起。** 失败返回 `StartResult(False, "writeback", reason)`，
   reason 必带"哪个文件、哪一行、期望改成什么"（R4 第 6 条：任何"你自己去做"都算缺陷）。
2. **幂等靠读出来判断，不靠"写过就算"。** 当前值已是目标值 → 不动文件、不留新备份、不改 mtime；
   不是目标值才改，且只在首次改动时留 `.bak`。锚不到那一行、或那一行被用户改成我们不认的格式 → **拒改**，
   并明确告知要改哪一行（§5 的"有边界退回"）。
3. **副本一旦存在就是权威，绝不用官方 conf 覆盖它。** 副本是用户配置的家，不是缓存。

---

## 6. 停止与卸载

- `stop()`：先探簇。**只要簇内任一口还在听，就不算停止**，一律进入 `need_force` 请示路径
  （不允许"部分在听"被当成已停从而清掉登记——那会把剩下的孤儿口变成没人认领的监听）。
  整簇都不在听 → 按已停止清登记（计划一裁定 6 的形状，端口是真相）。
  仍在听 → Windows 上 pid 路线无优雅手段（`os.kill` 任意信号都是 `TerminateProcess`），
  因此返回 `need_force` 并说明代价（计划一裁定 1 的直接延续）。
- `force_stop()`：三重闸过 → 端口反查 PID → 终止 → **有界复查整簇是否都释放**
  （复查窗口沿用 `force_stop` 现有的 `rounds` 默认值，不重定义一套新的），全释放才清登记。
- 运行中禁止卸载（沿用计划一）；卸载确认里按组件分别讲清数据去处：
  - ActiveMQ：版本目录被删，但 `~/.env-tools/activemq-data/`（conf 副本 + 数据）**保留**，须告知位置与删除方式。
  - Nacos：derby 数据在**版本目录内**，卸载即连带删除——不能沿用"数据会保留"的旧承诺，必须说清。

---

## 7. 失败语义（补齐计划一 §5 的具体化）

| 情形 | 处理 |
|---|---|
| 没装 JDK / JDK 版本不足 | 按钮禁用 + tooltip 指名缺什么，并给可点的"先装 JDK / 换到 17"，复用 `DownloadWorker`。自动处理 |
| 8848 簇被占（Nacos） | 找整簇空闲的新主口；`--server.port` 注入，不碰文件。自动处理 |
| 8161 或 61616 被占（ActiveMQ） | 各自基准各自平移（副本内改），**两个口一起解决**；任一找不到可用口即失败并指名是哪个口 |
| 锚点找不到 / 那行被用户改成不认识的格式 | 放弃自动改端口，用默认端口起（默认口空着时本就不需回写）；默认口也被占才失败，失败原因带"改哪一行" |
| 副本目录存在但缺文件（换版本带来新默认项） | 日志点名缺失文件，不自动覆盖、不自动补 |
| 起了但超时未监听 | 抓厂商日志尾巴 + 我们自己的重定向文件。**注意日志来源按 OS 不同**：Windows 上 java 是我们的子进程，报错先进我们的 `byte-tools.out`；`logs/start.out`（Nacos）与 `data/activemq.log`（ActiveMQ）要一并去翻，但别指望 Windows 下 Nacos 有 `start.out`（那是 `startup.sh` 的产物）。归因常见原因：堆内存、`JAVA_HOME` 不对、配置语法、权限 |
| 主口在听、派生/独立口不在听（半死） | 按簇判定：不满足整簇即视为僵尸，清登记并显示上次异常退出。不自动重启 |
| 停止无响应 | 有界等待后**询问**是否强制结束；确认后才端口反查 + 三重闸 |
| 运行中卸载 | 禁止 |

---

## 8. 测试策略

### 8.1 离线（`bt_launch_tests.py`，全离线、不真起中间件、不弹窗）

- **T-表完整性**：`LAUNCH_KEYS == {jenkins, activemq, nacos}`；每 spec 三平台命令非空；
  主口在簇内唯一；`min_java_major` 只允许带证据的值（8/17 的证据写在注释里，Jenkins 继续 `None`）。
- **T-迁移**：旧格式 `running.json`（无 `ports` 字段）必须能加载且 `ports == (port,)`；
  并且"往 `RunRecord` 加新字段必须带默认值"这条要有防回退断言。
- **T-回写（纯函数 + 真包原文 fixture）**：
  - ActiveMQ：`jetty-spring.properties` 与 `activemq.xml` 用 §2.1 抓下的真原文。
    断言：只动目标行、其余字节逐字节相同、锚不到即拒改且原因可行动、幂等（改两次等于一次、只有一个 `.bak`）、
    两个端口口分别落位。
  - 副本建立：整目录拷贝（含 `conf/jetty/` 子目录与 `users/groups.properties`）；副本已存在时**不重新拷贝、不覆盖**。
  - Nacos：对照用例——断言整条启动路径**不产生任何文件写入**（这是 D3 的兑现证据）。
- **T-端口选择**：派生口跟主口位移；独立口用自己的基准；任一组成员被占整簇弃用；span 耗尽失败且原因指名。
- **T-按簇僵尸判定**：主口在、9848 不在 → 僵尸；61616 单独被占 → 换 61616 而不换 8161。
- **T-停止（D7）**：`netstat -ano` 真机原文喂解析（IPv4/IPv6 双行、`0.0.0.0` 与 `[::]`、同口多行取哪个）；
  三重闸各一条否定用例（外来占用不动、自己不动、未确认不动）；
  **`_terminate_by_pid` 对 `pid_role != "server"` 仍必须拒不动手**（计划一守卫不许被绕过）。
- **T-不变量**：`NoExecInvariant` 扩到两个新组件 + 端口簇；并加**反向**用例：`force_stop` 确实会调用反查
  （证明我们没有把这条路径写成不可测的死代码）。

### 8.2 真机演练（`--launch <key>`，Windows；需用户在场）

三层判据后加第四层，且新增两条本期专属判据：

- **A1** 启动 → 控制台可达 → 停止 → **整簇端口都不再监听**（不止主口）。
- **A2** 端口被占时：实际监听端口集合 == 我们登记的簇（证明厂商的派生规则真按 +1000/+1001 走）。
- **A3** 控制台路径确认（Nacos `/` vs `/nacos`；ActiveMQ `/admin`），据此回填 `console_path`。
  同时给 `health_path` 定值：计划二的 `health_path` 取"A3 实测能拿到可达响应的那个路径"，
  由 `bt_real_machine_drill.py` 的可达判据消费（计划一已把该脚本的硬编码 `"/login"` 改成读 `spec.health_path`）。
  **`health_path=None` 不是"不测"，是"尚未实测"**：A3 出结论前两个组件都填 `None`，出结论后必须回填真实值，
  否则 §0 D3 的"控制台可达"这条判据对它们形同虚设。
- **A4** `--server.port=` 是否真的压过 `application.properties:23`（若否，Nacos 退到 `conf_copy`，需回补设计）。
- **A5** `activemq.bat console` 在 Windows 是否前台不弹独立窗、是否真起 broker（61616 在听）。
- **A6** `-Djetty.http.port=` 能否压过 conf（候选优化；证不成立就永久放弃该路径）。
- **A7** §2.4 第 2、4 项结论回填计划一 spec，并据此回填 `console_path` / 组件登记。

**A4/A5/A6 在证否之前的状态是"未验证"**，不得据推测改代码行为；尤其 A4 不成立时 Nacos 也要走回写，
届时 §4.1 的 `port_writeback` 需改并回补设计。

### 8.3 基线

现有 9 套件 / 347 用例必须继续全绿（`bt_multiversion_tests.py` 需 `PYTHONIOENCODING=utf-8`，既有债）。
CI 与发布流程一律不跑真启动。

---

## 9. 验收标准（计划二）

1. Windows 上 ActiveMQ、Nacos 各完成一次：点启动 → 卡片"运行中 · 实际端口簇" → 打开控制台拿到登录页 →
   停止 → **整簇端口释放** → 数据/副本位置被告知。
2. 关掉工具再打开，三件组件（含 Jenkins）的运行状态识别正确，不重复拉起、不误报。
3. 默认端口被人为占用时：Nacos 整簇平移成功、ActiveMQ 两口各自解决、界面链接与实际端口一致（补齐计划一 §8 第 3 项）。
4. §2.4 与 §8.2 A1-A7 全部有结论并回写两份 spec；`console_path` 等以实测值回填，不保留推测值。
5. 离线套件全绿且新增守卫逐条经变异自检确认非空；原 9 套件不回归。
6. 全程无官方文件被修改：ActiveMQ 的回写只发生在 `~/.env-tools/activemq-data/conf`，Nacos 不写任何文件。

---

## 10. 残余风险与本期不做（明示，不留暗坑）

- **三平台建模 ≠ 已验证**：本期只在 Windows 真机验收；macOS/Linux 代码就绪但标未验证，
  且 Nacos 在 POSIX 是 `nohup` 自我后台化，`pid_role` 与停止语义都不同。
- **`conf_copy` 的升级陈旧**：换 ActiveMQ 版本后，新版自带的 conf 默认项不会出现在旧副本里；
  本期只做"日志点名缺失文件"，不做自动合并（自动合并 = 猜厂商意图）。
- **batch 参数分词**：`%*` 按空格分词，含空格的路径/参数值会碎；本期命令均不含空格值，改这里要重新验证。
- **Nacos 没有优雅停止手段**：`/F` 是唯一手段，强杀可能丢未落盘配置（写入风险说明，由用户决定）。
- **PID 复用的残余窗口**：见 §3.4，靠"有我们登记 + 用户当面确认"两闸兜，不靠时间戳。
- **不引入新依赖**（psutil 等），**不碰 WMI**，不为测试在产品代码加开关。
