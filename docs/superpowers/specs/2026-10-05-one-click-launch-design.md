# 组件一键启动与部署（ActiveMQ / Nacos / Jenkins）· 设计文档 v1

日期：2026-10-05　状态：**待用户复核**　前置：规则 R1（镜像故障转移）、R2（三类分组）、R3（多版本与生效版本）、R4（一键脚本自举契约）均已落地

## 0. 已确认的六个决策（本轮逐条问答定下，不再重开）

| # | 议题 | 结论 |
|---|---|---|
| 1 | 启动语义 | **B：脱离进程**。拉起后中间件不随 byte-tools 退出而死；下次打开能认出"运行中"并停止它 |
| 2 | 端口冲突 | **自动改用空闲端口并按组件的正规方式回写配置**，界面里的控制台链接用实际端口 |
| 3 | 运行期数据 | 与版本目录分离：`~/.env-tools/<key>-data`，换版本/重装不丢数据 |
| 4 | 监听与凭据 | **保持组件官方默认**（多为 `0.0.0.0` + 公开默认口令），但在启动确认里把风险说清并告知如何改成仅本机 |
| 5 | 界面形态 | **卡片内加按钮**，不开新 Tab；沿用 `ComponentCard` 现有的按钮 enable/tooltip 一套做法 |
| 6 | 平台范围 | **三平台建模，Windows 先验收**；macOS/Linux 分支代码写完但在本文档中明确标为未验证 |

第一批组件：`activemq` / `nacos` / `jenkins`。选型依据是三者都自带可访问的网页、唯一前置都是 JDK、且三平台都有下载地址；三者恰好覆盖三种启动形态（自带包装器 / 启动脚本带模式参数 / `java -jar` 单文件），能把抽象一次磨对。

## 1. 范围与非目标

**范围内**：单个组件的启动、停止、运行状态显示、打开控制台、端口选择与配置回写、运行期数据目录管理、启动失败的可读归因。

**非目标（本期一律不做）**：

- 开机自启、崩溃自动重启、注册系统服务。ActiveMQ 的 `bin/win64/InstallService.bat` 与 Java Service Wrapper 属于这条路线，**本期不碰**，只在文档里说明它存在。
- 集群/多节点编排（Nacos cluster、ActiveMQ 网络拓扑、Kafka/RocketMQ 多 broker）。
- 容器化与 compose 生成：与"直接装官方二进制、不引第三方运行时"的项目定位冲突，且 `docker` 组件在 Windows 上本就只提示不装。
- 第二批组件（RocketMQ / Kafka / Seata / Elasticsearch / RabbitMQ）——其中 RocketMQ、Kafka **不含界面**，控制台是独立项目，属于另一件事。

## 2. 实测事实（2026-10-05，本机抓取）

抓取方式：用项目自身的 URL 构造器（`_activemq_urls` / `_nacos_urls` / jenkins 的 `url_list_map`）取 Windows 源，走 `main._get()` 下载到 `D:\tmp\btdiag\probe`，再从包内直接读取配置原文。三个包：`apache-activemq-6.3.2-bin.zip` 57,282,451 B；`nacos-server-2.3.2.zip` 153,580,883 B；`jenkins.war`(2.568.3) 101,130,898 B。

### 2.1 ActiveMQ 6.3.2

- 根目录 `apache-activemq-6.3.2/`；可执行有 `bin/activemq`（POSIX）、`bin/activemq.bat`、`bin/win64/activemq.bat`。
- **控制台端口写在 `conf/jetty-spring.properties` 的 `jetty.http.port=8161`**，不在 `jetty.xml` 里（本设计早期口述的 `jetty.xml` 是错的，已按实测更正）。
- 控制台凭据来源实测为 `conf/users.properties`（`admin=admin`）与 `conf/groups.properties`（`admins=admin`）。
- `bin/activemq` 自带 `start-stop-daemon` 与 `$ACTIVEMQ_PIDFILE` 语义，即 POSIX 侧 `start` 会自己后台化。

### 2.2 Nacos 2.3.2

- 根目录 `nacos/`；`bin/startup.cmd`、`bin/shutdown.cmd`、`bin/startup.sh`、`bin/shutdown.sh`。
- **`startup.cmd` 硬性要求 `%JAVA_HOME%\bin\java.exe`**，不存在则打印提示并 `EXIT /B 1` → 启动时必须给子进程显式注入 `JAVA_HOME`，不能依赖用户 PATH。
- `startup.cmd` 里 standalone 分支 JVM 参数为 `-Xms512m -Xmx512m -Xmn256m`，cluster 分支为 `-Xms2g -Xmx2g -Xmn1g` 且需要 `cluster.conf`（包内只有 `cluster.conf.example`）→ **必须强制 `-m standalone`**。
- `startup.sh` 的拉起方式是 `nohup "$JAVA" ... nacos.nacos >> ${BASE_DIR}/logs/start.out 2>&1 &`：脚本返回后真正的 Java 进程还在，**我们拿不到可信的服务 PID**。
- **`conf/application.properties` 里是 `server.port=8848`**（本设计早期口述的 8080 是错的，已按实测更正）。附带后果：gRPC 端口按 offset 派生（9848/9849），改主端口必须**一组一起改**。

### 2.3 Jenkins 2.568.3

- war 的 `META-INF/MANIFEST.MF`：`Main-Class: executable.Main`、`Jenkins-Version: 2.568.3`、`Build-Jdk-Spec: 21`、`Java-Version: 11`。
- 三平台同一个 URL（war 单文件），启动形态统一为 `java -jar jenkins.war`，与现有 `main.py:3283` 那句"用户需自行用 java -jar 启动"正好对上——本期就是把这句话变成按钮。
- 由 `Build-Jdk-Spec: 21` 推断 JDK 有最低版本要求，**具体门槛以真机为准**（见 §2.4）。

### 2.4 待真机验证清单（Windows 验收时必须有结论，不许写成事实）

1. `nacos/bin/startup.cmd` 里 `%COMMAND%` 展开后的实际拉起方式（是否 `start /b javaw`、是否留窗口）。
2. Nacos 2.3.2 控制台路径是 `/nacos` 还是根路径；gRPC offset 的确切属性名。
3. Jenkins `--httpPort` / `--httpListenAddress` 的实际生效性，以及初始管理员密码文件的确切落点。
4. Windows 下 `bin/activemq.bat` 能否在不装服务的前提下正常起，以及它是否会弹独立窗口。
5. Jenkins 要求的 JDK 最低大版本。
6. ActiveMQ broker 传输端口 61616 的正规回写点在哪（`conf/activemq.xml` 的 `transportConnectors`？本期未实测，因此**第一批不自动平移该端口**，只在它被占时按 §5 的失败语义报告）。

#### 2.4.1 演练记录（2026-10-05，Task 12）

- 已完成：`bt_real_machine_drill.py` 新增 `--launch <key> [--yes]` 三层判据入口（拉得起 → 控制台可达 → `登记残留=[]`）。
  dry-run 已在本机真跑通：只打印将做什么，退出码 0，无 java 进程、无 `~/.env-tools/running.json`、无任何目录新增。
- 第 3、5 项：**仍无结论**。判据要靠 `--yes` 真机执行，而本机未装 JDK 与 Jenkins（`~/.env-tools` 仅有
  config.json / powershell / python），真跑会走镜像下载 ~200MB、写用户环境变量与 PATH、创建 `jenkins-data`
  并在 8080 起活服务——需用户在场授权后执行。故 `LAUNCH_OF["jenkins"].min_java_major` 维持 `None`，
  等实测结论回填，不许先写数字。
- 第 1、2、4、6 项：属 Nacos / ActiveMQ（计划二范围），本次演练入口只接了白名单内的 jenkins，未触及，状态不变。

## 3. 架构与分层

全部落在 `main.py` 内（保持单文件形态），按现有约定分四层：

**① 数据层 `LaunchSpec`**，`Component.launch: Optional[LaunchSpec] = None`：

| 字段 | 含义 |
|---|---|
| `commands` | `Dict[str, List[str]]`，按 OS 键存启动 argv 模板，允许 `{port} {cluster_ports} {home} {data_dir} {java} {log_file}` 占位 |
| `stop` | 停止方式：`shutdown_command`（有正规脚本，如 `activemq stop` / `shutdown.cmd`）或 `pid`（Jenkins） |
| `port_cluster` | **端口簇**而非单端口：主端口 + 派生端口及联动规则。Nacos 为 8848 与按 offset 派生的 gRPC 两口（§2.2 实测 + 待验证）；ActiveMQ 本期**只管控制台 8161**，broker 的 61616 不做自动平移（其回写点未实测，见 §2.4 第 6 项） |
| `port_writeback` | 改端口的正规做法：`cli_flag` / `property_file`（含目标文件、正则锚定的"官方默认那一行"） |
| `console_path` / `health_path` | 拼成 `http://127.0.0.1:{port}{path}`；`health_path` 为 `None` 时只做 TCP 判活 |
| `needs` / `min_java_major` | 前置组件 key 与 JDK 最低大版本。取值以证据为准，不凭印象：Nacos 的 `startup.cmd` 原文写着 "jdk8 or later is better!"（§2.2）→ 取 8；Jenkins 的 manifest 是 `Build-Jdk-Spec: 21` / `Java-Version: 11`（§2.3），**真正门槛待 §2.4 第 5 项实测**，实测前不得先写死一个数字 |
| `data_dir_env` | 要注入的环境变量名（`JENKINS_HOME` 等），指向 `~/.env-tools/<key>-data` |
| `startup_timeout` | 有界探活秒数，超时判启动失败 |

登记方式沿用 `MULTI_VERSION_KEYS` 的先例：`LAUNCH_KEYS = ("activemq", "nacos", "jenkins")`，由 `build_components()` 末尾统一赋值，**构造处不手写**。

**② 生命周期层 `ServiceManager`**（纯逻辑，不含 Qt 对象）：`status()` / `start()` / `stop()` / `adopt_running()`。可测的四块（端口簇选择、配置回写、登记判定、门控）都写成不依赖 Qt 的纯函数或纯类，`LaunchWorker` 与 `ComponentCard` 只做粘合。

**③ 线程层 `LaunchWorker(QThread)`**：只承担启动/停止这类耗时动作，信号风格照 `DownloadWorker`。**状态检测完全不起子进程**，只用 `socket` 连端口 + `urllib` 取健康路径。

**④ UI 层**：`ComponentCard` 在 `launch is not None` 且"已装 + 前置满足"时多一排「启动 / 停止 / 打开控制台」；状态胶囊新增"运行中 · 8161"；打开控制台复用 `QDesktopServices.openUrl`（先例见 main.py:5961）。

**⑤ 两个持久文件**：`config.json` 存用户偏好（现有）；`~/.env-tools/running.json` 存"这台机器上的进程事实"，写盘复用 4279 的"临时文件 + `os.replace`"原子覆盖。分开的理由：语义与损坏后果不同——前者删了丢记忆，后者删了只是重新发现一遍，合在一个文件里一次坏 JSON 会把两者一起带走。

## 4. 状态机与数据流

**核心取舍：放弃"PID 是唯一真相"。** §2 已证明 `java -jar` 的 PID 就是服务进程，而 Nacos/ActiveMQ 的脚本自己后台化，返回的 PID 几秒后就没意义。于是定：

> **权威真相 = 登记的端口确实在听；PID 只用于尽力而为地停止。**

登记结构：`{key, version, home, data_dir, port, console_url, pid, pid_role, started_at, launcher_cmd}`，`pid_role ∈ {"server","launcher","none"}`（Jenkins 记 `server`，Nacos/ActiveMQ 记 `none` 或 launcher）。老实写下角色，免得以后有人拿它做错误判断。

状态机：`未安装 → 已装未运行 → 启动中 → 运行中(port) → 停止中 → 已停止`，外加 `启动失败(原因)` 与 `异常退出`（登记在、端口没了 → 显示"上次异常退出"并可看日志尾巴）。

启动时序：门控检查 → 选端口簇（**平移规则定死**：从主端口开始，在 `[默认端口, 默认端口+99]` 内升序找"整簇所有端口同时空闲"的最小主端口；找不到则失败，不做跨段随机挑选）→ 回写端口 → 建 `~/.env-tools/<key>-data` 并注入 env（`JAVA_HOME`、数据目录变量）→ **把 stdout/stderr 重定向到 `<data>/logs/byte-tools.out`**（Windows `DETACHED_PROCESS` 下没有有效控制台句柄，不重定向等于把错误扔了）→ 有界轮询探活 → 写登记 → 刷新卡片。

打开工具时：`MainWindow` 对每个 `launch` 组件做一次 `adopt`——只读登记 + 探活，**绝不拉起进程**。

停止：有正规 shutdown 的先走它，有界等待（默认 30s），超时只**询问**是否强制结束，不自动强杀；Jenkins 用登记的 server PID。

## 5. 失败语义（区分"自动处理"与"有边界的退回"）

| 情形 | 处理 |
|---|---|
| 没装 / JDK 版本不足 | 按钮禁用 + tooltip 说明缺什么，并提供可点的"先装 JDK / 换到 17"，直接复用 `DownloadWorker`。自动处理 |
| 端口簇被占 | 能从 `running.json` 认出是自家起的 → 提供"停止它再重试"；认不出 → 说清哪个口被占并自动换可用簇。**绝不静默杀别人的进程** |
| 配置回写不安全（找不到那行官方默认 / 用户已手改 / 格式不认识） | 先放弃自动改端口，用默认端口起（默认口空着时根本不需要回写）；只有"默认口被占 **且** 回写不安全"才失败，失败时明确告知要改哪一行。**这是有边界的退回**：工具不能假装安全地改一个它读不懂的文件 |
| 起了但超时未监听 | 判启动失败；抓组件自身日志（`data/activemq.log`、`logs/start.out`、`<data>/logs/`）与重定向文件的尾巴，归类常见原因：堆内存要太多、`JAVA_HOME` 不对、配置语法、权限 |
| PID 活着但端口易主 / 端口在听但 PID 不符 | 判"登记的进程已不在"，清登记并显示上次异常退出。不自动重启 |
| 停止无响应 | 超时后询问是否强制结束，不自动强杀 |
| 重复启动 | 同一 key 串行化（per-key 锁）；已运行时按钮变"打开控制台" |
| 运行中卸载 | **禁止**（按钮禁用，提示先停止）；停止后 `<key>-data` 保留，卸载完成时明确告知数据位置与删除方式 |

## 6. 与既有规则和不变量的关系

- **R4 的第 6 条同样约束本功能**：任何"你自己去做"的分支都算缺陷。§5 里唯一保留的退回（回写不安全）必须携带"改哪一行"的可执行信息，而不是空报错。
- **`version_probe=False` 不变量升级**：现状是"探测阶段绝不执行启动脚本"（CODE_WIKI §10.10）。本期把它扩成"**状态检测与找回过程也绝不执行启动脚本**"，只允许 TCP/HTTP。这条有专门的回归用例守（§7.6）。
- **R3 卸载契约补一条**：运行中的组件不许卸载；"卸载只删版本目录"从此不再等于清理干净，`<key>-data` 的去处必须显式告知。
- **不碰 WMI**：新增的探活/状态逻辑不得使用 `platform.*`，沿用 `sys.platform` 与 `PROCESSOR_ARCHITECTURE`（`bt_startup_tests.py` 的护栏继续有效）。
- **行尾以索引为准**：`autocrlf=true` 会让工作区呈现 CRLF，而索引里是 LF（`git show :main.py` 可见）。改 `main.py` 时不要为"行尾"去动文件，也不要把这当成回归。
- 新增的三平台建模不等于已验证：`LAUNCH_KEYS` 之外组件的 `launch` 一律为 `None`，界面不出现启动按钮。

## 7. 测试策略

**`bt_launch_tests.py`（全离线，不真起中间件）**：

1. **Spec 表完整性**：`LAUNCH_KEYS` 与 spec 一一对应；每 spec 三平台命令非空；主端口在簇内唯一；`console_path` 与 `health_path` 前缀一致；`min_java_major` 必填。
2. **端口簇算法**：全空用默认；主口被占整簇平移；平移后仍撞走逐个候选；候选耗尽失败且原因带"哪个口被谁占"。
3. **配置回写**：fixture 用 §2 从真包抓出的原文（`jetty-spring.properties` / `application.properties`）。断言只动目标行、其余字节逐字节相同、找不到那行就拒改、幂等（改两次等于一次）、改前留备份。
4. **僵尸登记矩阵**：PID 死 / PID 活端口不在 / 端口在听 PID 不符 / 文件是坏 JSON。前三种清登记，坏 JSON 视为空表重建，**四种都不允许触发任何进程动作**。
5. **门控**：未装或 JDK 不足时 `start()` 拒绝且原因可行动。
6. **不变量护栏**：把 `subprocess.Popen` 与 `_probe_version` 桩成"一调用就抛"，跑完 `status()` / `adopt_running()` 全流程（手法照 `bt_startup_tests.py` 的 `PROBE_CHILD`）。

**真机验证**：扩展 `bt_real_machine_drill.py` 加 `--launch <key>`，复用它已有的"三层判据 + 自动还原"结构：启动 → 探活 → 控制台 URL 拿 200 → 停止 → 端口释放 → `<key>-data` 仍在 → 运行中禁卸 → 停止后可卸 → 环境还原。Windows 执行；macOS/Linux 标未验证。

**CI**：不跑真启动（runner 要装 JDK + 三件，太重）。发布流程只跑离线套件。

**基线**：现有 7 个套件必须继续全绿。已知债：`bt_multiversion_tests` 有用例 `print` 勾号，GBK 控制台下需 `PYTHONIOENCODING=utf-8`，本期不动。

## 8. 验收标准（第一批）

1. Windows 上对 ActiveMQ、Nacos、Jenkins 各完成一次：点启动 → 卡片显示"运行中 · 实际端口" → 打开控制台拿到登录页/向导 → 点停止 → 端口释放。
2. 关掉 byte-tools 再打开，三个组件的运行状态被正确识别（不重复拉起、不误报运行中）。
3. 默认端口被人为占用时，能自动换到可用端口、正确回写配置、且界面链接跟着实际端口。
4. §2.4 的五个待验证项全部有结论并回写进本文档与 `LaunchSpec`。
5. `bt_launch_tests.py` 全绿且经变异测试确认非空护栏；其余 7 套件仍全绿。

## 9. 实施分期（自检时判定：单份计划过大，拆两份）

**计划一：框架 + Jenkins。** Jenkins 是三者里唯一"我们的进程就是服务进程"（`pid_role=server`）、且改端口只需命令行 flag（`--httpPort`）、不需要回写配置文件的组件。用它把 `LaunchSpec` / `ServiceManager` / `running.json` / 卡片按钮 / 离线回归 / `--launch` 演练一次跑通，出问题定位面最小。

**计划二：ActiveMQ + Nacos。** 这一期才引入两个真正的难点：脚本自我后台化导致 PID 不可信（§4 的取舍在这里兑现），以及端口要靠**回写配置文件**（§5 的"有边界退回"在这里兑现），外加 Nacos 的强制 standalone 与 `JAVA_HOME` 注入。

§8 的验收标准按两期分别收口：计划一完成第 1、2、4、5 项的 Jenkins 部分，计划二补齐另外两个组件与第 3 项（端口冲突）。
