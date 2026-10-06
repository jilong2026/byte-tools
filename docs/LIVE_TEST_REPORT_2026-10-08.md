# byte-tools 全组件真机功能测试与修复报告

- **测试日期**：2026-10-08（本机时钟显示为 2026-10-06/08 混合，以文件时间戳为准）
- **被测对象**：工作区 `D:\file\idea_project\byte-tools`（`main.py` 单文件核心，改动前 10164 行 → 改动后约 10780 行）
- **验收标准（用户原话）**：用户下载了这个软件后，对软件内**所有组件**进行**任何操作都要成功**；环境变量等配置或基础配置软件没装，就**默认帮用户安装和配置好**；让用户**开机就能用**，不需要用户自己修改任何文件。
- **测试机**：Windows 11 专业版（22631）、AMD64、非管理员会话（`Life`）、主机名 `鹅城剑仙`（**非 ASCII**）、C: 剩余空间测试期间从 10.2GB 降到 3.0GB（见"环境约束"）
- **测试方式**：真机端到端，走产品真实代码路径（不 mock），装置为本次新增的 `bt_live_matrix.py`

---

## 一、结论摘要

| 项 | 结果 |
|---|---|
| 组件总数 | **27**（26 个用户可见 + 1 个隐藏的前置运行时 Erlang） |
| 真机下载 → 落位 → 配置 → 可用性验证 | 26/26 通过（Docker 见下） |
| 真机一键启停（10 个可启动组件） | **10/10 通过**（start → 全端口监听 → 控制台/协议探活 → stop → 端口释放） |
| 多版本切换（装两个版本、来回切、PATH 收敛、进程环境复验） | 通过（kubectl / maven / node / go 真机，26 组件离线护栏全覆盖） |
| 前置依赖自举（缺 JDK / Erlang → 自动装好） | **通过**（本轮新增能力，见缺陷 6/7） |
| 本轮修复缺陷 | **12 个**（其中 6 个属"用户点了必然失败"级） |
| 无法在本机完成 | 2 项平台限制（Windows 上的 Docker、Pulsar），2 项未做（全新机器空目录演练、MySQL/PG 库初始化） |
| 离线护栏回归 | 9 个 `bt_*tests.py` 共 **497 条**全 `OK`（修改过程中同步更新了 5 个用例的期望值） |

一句话：**原来"看着装好了、点下去失败"的那批问题已全部修掉**；剩下两处是 Windows 平台本身没有那个东西（Docker/Pulsar），软件现在会明确说清并给出替代做法，而不是装作支持。

---

## 二、测试装置（新增文件）

`bt_live_matrix.py` —— 真机功能矩阵演练器，与既有离线护栏的分工是"不 mock、真下载、真起进程"：

```
python bt_live_matrix.py --keys all,erlang --phase install      # 下载+落位+配置+可用性
python bt_live_matrix.py --keys nginx,tomcat --phase launch     # 启停+探活
python bt_live_matrix.py --keys kubectl --phase switch \
       --switch-to kubectl                                     # 多版本切换
python bt_live_matrix.py --keys autoprereq --phase all          # 缺 JDK→自动装好→门控放行
```

装置的设计纪律（也是这次能查出问题的原因）：

1. **落位走产品函数**：本次把 `ComponentCard._on_download_ok` 里的落位逻辑抽成模块级
   `install_downloaded()`（`main.py`），界面与演练调用**同一份实现**。之前演练自己抄了一份
   60 行的副本 —— 那意味着"演练绿灯"跟"用户点下去会成功"是两件事。
2. **环境读持久层真值**：环境变量从 `HKCU\Environment` 读，不看进程内 `os.environ`。
3. **另跑一份"干净环境"**：把用户级 PATH 与所有 `*_HOME` 全部剥掉、只留系统段，
   再验组件命令能不能找到并跑出版本号 —— 这直接对应"新机器上开机就能用"。
4. **启停探针用产品注入的那份 env**：`build_launch_plan(...).env`（含 `extra_env`），
   否则会把"产品能跑"误判成"探针失败"（rabbitmq 踩过，见缺陷 9）。
5. **每一步都留证据**：HTTP 状态码、文件路径、注册表值、厂商日志尾巴，没有证据不算通过。

---

## 三、逐组件验收结果

### 3.1 全量总览（`--phase install`，最后一轮）

27 个组件 53 项检查，唯一"失败"是 docker 的 `pick_version`（**平台事实**，见 3.3）：

| 组件 | 下载 | 落位 | 环境变量 | PATH | host 环境可用 | 干净环境可用 | 检测判定 |
|---|---|---|---|---|---|---|---|
| jdk | ✅归位 | ✅ | ✅ `JAVA_HOME` | ✅ | ✅ 21 | ✅ | ✅ |
| maven | ✅真下载 | ✅ `mvn.cmd` | ✅ `MAVEN_HOME` | ✅ | ✅ 3.9.16 | ✅ | ✅ |
| tomcat | ✅ | ✅ | ✅ `CATALINA_HOME` | ✅ | ✅ | ✅ | ✅ |
| nginx | ✅ | ✅ | （无 HOME） | ✅ | ✅ 1.31.6 | ✅ | ✅ |
| mysql | ✅真下载 | ✅ | ✅ `MYSQL_HOME` | ✅ | ✅ 8.0.28 | ✅ | ✅ |
| python | ✅ | ✅ | （无 HOME） | ✅ | ✅ 3.12.4 | ✅ | ✅ |
| node | ✅真下载 | ✅ | ✅ `NODE_HOME` | ✅ | ✅ 20.15.0 | ✅ | ✅ |
| git | ✅真下载 | ✅ `MinGit` | （无 HOME） | ✅ | ✅ 2.47.1 | ✅ | ✅ |
| powershell | ✅ | ✅ | （无 HOME） | ✅ | ✅ 7.6.6 | ✅ | ✅ |
| conda | ✅真下载 | ✅ 安装器模式 | ✅ `CONDA_HOME` | ✅ | ✅ | ✅ | ✅ |
| go | ✅真下载 | ✅ | ✅ `GOROOT` | ✅ | ✅ 1.24.6 | ✅ | ✅ |
| gradle | ✅真下载 | ✅ | ✅ `GRADLE_HOME` | ✅ | ✅ 8.10 | ✅ | ✅ |
| bun | ✅真下载 | ✅ | ✅ `BUN_HOME` | ✅ | ✅ 1.4.2 | ✅ | ✅ |
| **docker** | ❌ **Windows 无包** | — | — | — | — | — | 平台限制，已给明确指引 |
| mongodb | ✅真下载 | ✅ | ✅ `MONGODB_HOME` | ✅ | ✅ 8.0.12 | ✅ | ✅ |
| postgresql | ✅真下载 | ✅ | ✅ `PGHOME` | ✅ | ✅ 17.6 | ✅ | ✅ |
| kubectl | ✅真下载 | ✅ 单文件改名 | （无 HOME） | ✅ | ✅ 1.31.0 | ✅ | ✅ |
| jenkins | ✅真下载 | ✅ **war 改名（本轮修）** | ✅ `JENKINS_HOME` | ✅ | ✅（war） | ✅ | ✅ |
| rabbitmq | ✅ | ✅ | ✅ `RABBITMQ_HOME` | ✅ | ✅ | ✅ | ✅ |
| kafka | ✅ | ✅ | ✅ `KAFKA_HOME` | ✅ | ✅ | ✅ | ✅ |
| rocketmq | ✅ | ✅ | ✅ `ROCKETMQ_HOME` | ✅ | ✅ | ✅ | ✅ |
| pulsar | ✅ | ✅ | ✅ `PULSAR_HOME` | ✅ | ✅（**仅辅助命令**，见 3.3） | ✅ | ✅ |
| activemq | ✅ | ✅ | ✅ `ACTIVEMQ_HOME` | ✅ | ✅ 6.3.2 | ✅ | ✅ |
| nacos | ✅ | ✅ | ✅ `NACOS_HOME` | ✅ | ✅ | ✅ | ✅ |
| seata | ✅ | ✅ | ✅ `SEATA_HOME` | ✅ | ✅ | ✅ | ✅ |
| elasticsearch | ✅ | ✅ | ✅ `ES_HOME` | ✅ | ✅ 9.2.3 | ✅ | ✅ |
| erlang（隐藏） | ✅真下载 155MB | ✅ | （刻意不设） | ✅ | ✅ | ✅ | ✅ |

"干净环境可用"指：把用户级 PATH 与所有 `*_HOME` 剥掉后，用**只有系统段的 PATH + 本工具写进注册表的那几条**，
仍能找到该组件的命令并跑出版本号。这是"新机器开机就能用"的直接证据。

### 3.2 一键启停（10/10 通过）

判据按 `DEVELOPMENT.md` R5：整簇端口全在听 → 控制台 HTTP（或协议级探针）→ 停止 → 端口释放。

| 组件 | start | 端口全在听 | 控制台/协议 | stop | 端口释放 | 备注 |
|---|---|---|---|---|---|---|
| nginx | ✅ | ✅ 8888 | ✅ 200 | ✅ | ✅ | **本轮修**首页 404 |
| tomcat | ✅ | ✅ 8081+8005 | ✅ 200 | ✅ | ✅ | **本轮修**首页 404 |
| activemq | ✅ | ✅ 8161+61616 | ✅ 401+`WWW-Authenticate` | ✅ | ✅ | 401 是**正确**响应（Basic 鉴权入口） |
| rocketmq | ✅ | ✅ 9876+10909+10911 | ✅ `mqadmin clusterList` | ✅ | ✅ | 双进程（namesrv+broker） |
| kafka | ✅ | ✅ 9092+9093 | ✅ `BrokerApiVersionsCommand` | ✅ | ✅ | KRaft，先 format 后起 |
| elasticsearch | ✅ | ✅ 9200+9300 | ✅ 200 | ✅ | ✅ | 关 xpack.security、关 ML |
| seata | ✅ | ✅ 7091+8091 | ✅ 200 | ✅ | ✅ | 端口靠 `SERVER_PORT` 注入 |
| nacos | ✅ | ✅ 8848+9848+9849 | ✅ 200 | ✅ | ✅ | 控制台在 `/nacos` |
| rabbitmq | ✅ | ✅ 5672+25672 | ✅ `rabbitmqctl status` rc=0 | ✅ | ✅ | **本轮修**节点名（中文主机名） |
| jenkins | ✅ | ✅ 8080 | ✅ 初始化完成后 200 | ⚠️ **两段式** | ✅ | 见下 |

jenkins 的停止需要点两次（先"停止"→ 弹"要强制结束吗"→ 确认），这是**既有安全设计**
（Windows 上没有优雅停止手段，且它可能正在跑构建任务）。本轮修掉了"确认之后仍然停不掉"的死角（缺陷 10）。
jenkins 起后约 30-60 秒内控制台返回 `503 Please wait while Jenkins is getting ready to work`，
本轮起**会在日志里点明**"控制台正在初始化、稍等再点"，不再让用户以为是坏的（缺陷 11）。

### 3.3 明确"不能做"的两项（平台事实，不是缺陷）

| 组件 | 事实 | 软件现在的行为 |
|---|---|---|
| **docker** | Docker 官方 portable static binary **只发 Linux/macOS**；Windows 必须装 Docker Desktop（依赖 WSL2/Hyper-V + 管理员授权 + 通常重启）。本工具"解压即用"的模型在 Windows 上装不出能跑的 docker | 缓存卡片会明确说明原因，并给两条可行路径（Docker Desktop 官网 / `wsl --install` 后 `apt install docker.io`） |
| **pulsar** | 实测 3.3.9 的 `bin/` 里**只有** `pulsar-admin/pulsar-client/pulsar-perf/pulsar-shell` 的 `.cmd`，**主命令 `pulsar` 只有 POSIX shell 脚本**（首行 `#!/usr/bin/env bash`），Windows 原生跑不起来；官方起步文档也要求 Docker 或 WSL | 关闭了它的版本探测（`--version` 在该版本上还不是有效子命令），并给出 WSL2 / Docker 两条做法 |

同时跨平台事实（本次一并记录）：`git`/`nginx` 在 Linux/macOS 上游只发源码包；`mongodb` 无 Darwin 二进制；
`postgresql` 官方只发 Windows binaries —— 这些在软件里都已经走 `unsupported_platform_hint` 或已有说明。

---

## 四、本轮修复的缺陷清单

按"严重度 = 用户点下去会怎样"排序。全部有真机复现证据。

### 缺陷 1（严重）：一装完 Jenkins 就起不来 —— war 文件没改名

- **现象**：Jenkins 下载完成后目录里是 `jenkins-2.568.3.war`，而启动命令写死找 `<home>/jenkins.war`。
  用户点启动 → `[WinError 267] 目录名称无效`；界面检测也判不出"已安装"。
- **根因**：`install_downloaded()`（原 `_on_download_ok`）里那条改名守卫是
  `if is_single_binary and comp.exec_name:` —— jenkins 的 `exec_name` 是 `None`（它只有 war），
  于是**改名整段被跳过**。
- **修复**：war 形态补一条"通用文件名"兜底（`jenkins-2.568.3.war` → `jenkins.war`，
  名字从下载文件名取，不写死组件 key）。exe/无扩展名的单文件仍然必须有 `exec_name` 才改名（不猜）。
- **验证**：落位后目录为 `['jenkins.war']`，`detect()` 判"已配置"，真机启动到
  `Jenkins is fully up and running`（日志实测）。

### 缺陷 2（严重）：nginx 启动成功但首页 404

- **现象**：start 成功、8888 在听，`GET http://127.0.0.1:8888/` → **404**。用户点"控制台"看到 404。
- **根因**：`nginx.conf` 里是 `root html;`，而 root 相对 **`-p` prefix** 解析，我们给的 prefix 是
  `~/.env-tools/nginx-data` —— 那个目录下从来没有 `html/`（`credentials_hint` 里却早就写着
  "站点内容在 nginx-data/html/"，只是没人去建）。
- **修复**：新增 `sync_runtime_assets()`，在端口准备阶段把安装目录的 `html/` **补缺不覆盖**地同步进 prefix。
- **验证**：`GET /` → **200**（153 字节 → 欢迎页）。

### 缺陷 3（严重）：Tomcat 启动成功但首页 404

- **现象**：同 2，8081 在听、`GET /` → 404，而 Tomcat 官方包自带默认 ROOT 欢迎页。
- **根因**：`CATALINA_BASE` 被本工具指到 `~/.env-tools/tomcat-data`，Tomcat 的 apphost 就是
  `tomcat-data/webapps` —— 那个目录**已建但是空的**（安装目录里的 `webapps/` 从没被同步过去）。
- **修复**：同一处同步逻辑把安装目录的 `webapps/` 补进 `CATALINA_BASE/webapps`；
  同时把 `data_note`/`credentials_hint` 里"war 放进安装目录的 webapps"这句**假话**改成生效目录
  （`~/.env-tools/tomcat-data/webapps/`）。
- **验证**：`GET /` → **200**。

### 缺陷 4（严重）：中文主机名的机器上 RabbitMQ 起来了却"什么都干不了"

- **现象**：start 成功、5672/25672 都在听、厂商日志一切正常，但 `rabbitmqctl status`
  返回 `** (exit) :badarg` / `rc=70`、`was unable to perform an operation on node
  'rabbit@鹅城剑仙'` —— 状态查不了、服务也停不掉（只有强杀一条路）。
- **根因**：Erlang 分布式节点名默认取 `rabbit@<主机名>`，**非 ASCII 主机名**下节点名被破坏。
- **修复**：`rabbitmq` 的 `extra_env` 固定 `RABBITMQ_NODENAME=rabbit@localhost`
  （start/stop/status 三处一致），并把这条写进 `DEVELOPMENT.md` R9 与 spec 注释。
  实际上 harness 侧还需要用产品注入的 env 才能验（见缺陷 9）。
- **验证**：`rabbitmqctl status` → `rc=0`，输出 `Status of node rabbit@localhost ...`、
  `RabbitMQ version: 4.0.9`、`Erlang configuration: Erlang/OTP 27`。

### 缺陷 5（严重）：GitHub 加速器顺序是错的 —— 有些组件根本下不下来

- **现象**：安装 Erlang 的 155MB 便携包时只有 **6.4 KB/s**（≈7 小时），
  而同一个包换个前缀是 1 MB/s。
- **根因**：`GH_ACCELERATORS` 把 `ghproxy.net` 放在首位（那是 2026-09 的结论，已经反转）。
- **修复**：带 `HTTP_UA` 实测两个仓库（PowerShell 101MB 与 Erlang 155MB），按实测速度重排为
  `ghfast.top` → `gh-proxy.com` → `ghproxy.net` → 裸 GitHub，并把实测表格写进 `DEVELOPMENT.md` R1.3。
- **验证**：同机同包 6.4 KB/s → **1020 KB/s**（约 3 分钟装完）。这条影响所有走 GitHub 的组件
  （powershell / bun / nacos / rabbitmq / git / erlang）。

### 缺陷 6（严重，"开机就能用"的核心）：缺 JDK 只会拦人，不会自己装

- **现象**：刚拿到软件的用户点 Jenkins/Nacos/Kafka 的"启动" → 弹一句
  "启动需要先有 JDK：在本工具里装一个 JDK（推荐 17），再回来点启动"。**活交回给了用户**。
- **根因**：`launch_gate()` 只做判定，没有任何自动补装；`min_java_major` 字段**声明了 10 处却零处被读**，
  等于版本门槛形同虚设（机器上只有 JDK 8 也会放行，然后在 JVM 层炸出 `UnsupportedClassVersionError`）。
- **修复**：新增 `prereq_components()` / `java_major_of()` / `pick_prereq_version()` /
  `prereq_already_installed()`，界面在拉起启动线程**之前**先调 `_install_missing_prereqs()`：
  下载 → `install_downloaded()` 落位 → 复验 → 自动继续原启动流程。用户只点一次「启动」。
- **验证**：`--keys autoprereq` 六项全绿（把 `JAVA_HOME` 与 PATH 里的 java 摘掉、屏蔽自家 JDK 目录，
  让判据真的报"缺 jdk"，再走完下载→落位→读回 major=21→切换生效→`launch_gate` 放行）。

### 缺陷 7（严重）：缺 Erlang 只会拦人，且"自己装的 Erlang"它认不出来

- **现象 A**：rabbitmq 缺 Erlang 时只提示"去装 Erlang"（139MB，国内没镜像）。
- **现象 B**：把 Erlang 装进本工具目录后，门控**仍然**说没装 —— 因为
  `find_erlang_home_erl()` 只搜 `C:\erlang*` 与 `Program Files\Erlang OTP\*`。
- **修复**：Erlang 登记为**隐藏组件**（`Component.hidden=True`，复用同一套下载/解压/版本解析，
  不进任何界面 Tab），新增 `installed_erlang_erl()` 统一查找（先自家 `~/.env-tools/erlang/`，再 glob），
  `check_prereq()` 与 `build_launch_plan()` 都改走它；缺失时由缺陷 6 的同一套机制自动装上。
  版本是**配套**的：rabbitmq 4.x → Erlang 27.x、3.13 → 26.x。
- **验证**：`--keys erlang --phase all` 13 项全绿；rabbitmq 起停 + `rabbitmqctl status` 全通过。

### 缺陷 8（中）：`process_alive()` 会把"早退出的 PID"判成活着

- **现象**：jenkins 的 java 启动器退出后，`running.json` 里那行 PID 已经不存在，
  但 `process_alive()` 回 **True**。
- **根因**：`tasklist` 输出用 `str(pid) in stdout` 判存在，而 CSV 里**内存列**是
  `912,560 K` 这种带千分位的数字 —— `pid=91256` 命中了它。
- **修复**：新增 `_tasklist_pid_exists()`，按 CSV 字段解析后**精确比 PID**，不做子串匹配。

### 缺陷 9（中）：启停探针环境与产品不一致（演练误报，已修在装置侧）

- **现象**：rabbitmq 的 `service_probe`（`rabbitmqctl status`）在演练里稳定 rc=70，
  而手工带上产品的 env 后 rc=0。
- **根因**：演练自己拼 env，漏了 `RABBITMQ_NODENAME` / `ERLANG_HOME` / PATH。
- **修复**：演练改用 `main.build_launch_plan(...).env`（与产品 spawn 时同一份环境）。

### 缺陷 10（中）："点停止 → 确认强杀 → 还是没停掉"的死角

- **现象**：登记 PID 已退出、真正监听端口的是它的子进程时：
  `stop()` 说"要强制结束吗" → 用户点确定 → `force_stop()` 见登记 PID 不活着，**什么都不杀** →
  用户只能自己去任务管理器杀 java.exe。
- **根因**：两个函数都把责任推给对方；判据又是不可靠的"PID 是否活着"。
- **修复**：判据改成**端口归属事实**（"登记 PID 是不是持有端口的那个"），
  并在 `force_stop` 的 server 分支补上"登记 PID 不持有端口时按唯一归属结束真正的监听进程"。
  三重闸（有登记 / 不是自己 / 用户已确认）一条不动。
- **验证**：真机 jenkins 起→停→force_stop，`8080` 释放、`running.json` 清登记。

### 缺陷 11（轻）：Jenkins 起来后控制台 503，用户会以为坏了

- **现象**：8080 一开始监听就回 `503 Please wait while Jenkins is getting ready to work`。
- **修复**：启动成功后多探一次控制台，5xx 时在组件日志里写明"服务还在初始化，稍等再点"，
  **不改变"启动成功"的判定**（服务进程确实在监听、登记已落盘）。

### 缺陷 12（轻）：两处会误导用户的说明文字

1. `rabbitmq` 的卡片上挂着 `unsupported_platform_hint` 说"Windows 上不提供自动下载"，
   而它**早就有 Windows URL**（会误导用户以为装不了）。已删除该字段。
2. `seata` 的 `data_note` 说"日志落点未实测"，实测发现 `seata-server/logs/` 下**只有**
   `seata_gc.log`（logback 的 server 日志没生成）—— 已改成实测结论并指出排障该看
   `~/.env-tools/seata-data/logs/byte-tools.out`。

### 顺带的结构性改动

- 落位逻辑抽成模块级 `install_downloaded()` / `archive_ext_for()` / `_run_installer_for()`：
  界面与演练**共用唯一实现**（R7）。这是"演练绿灯 = 用户点下去会成功"的前提。

---

## 五、验收口径与"未做/做不到"的诚实清单

### 5.1 已做到

- 26 个可见组件的**下载、落位、`*_HOME`、PATH、检测判定、真实可执行**全部真机通过；
- 10 个可启动组件的**启动、整簇端口、控制台/协议探活、停止、端口释放**全部真机通过；
- 多版本并存与来回切换（kubectl/maven/node/go 真机 + 26 组件离线护栏）；
- 缺 JDK / 缺 Erlang 时**自动安装并继续启动**（含"宿主 JDK 版本低于门槛"的情形）；
- 环境变量写在 `HKCU\Environment`，**不需要管理员权限**；`TEST` 机全程非管理员会话。

### 5.2 未做（本轮没验，建议后续补）

| 项 | 为什么没做 | 风险 |
|---|---|---|
| **全新机器空目录演练**（删掉 `~/.env-tools` 从零点一遍） | 本机 C: 只剩 3-4GB，重下 26 个组件需要 10GB+ 与数小时带宽 | 中：部件级已逐个真装过，但"从零到全绿"的整链没连跑过 |
| **MySQL / PostgreSQL 的库初始化** | 两者官方 Windows 包都是 zip，**要跑 `mysqld --initialize-insecure` / `initdb` 才有数据目录**，软件目前只装二进制 | 高：用户装完直接 `mysql -u root` 会连不上。见"六、建议"第 1 条 |
| **jenkins / seata / nacos 的版本清单刷新后新版本** | 只验了清单内版本；`_fetch_*` 的在线清单未逐个真跑 | 低：`bt_refresh_versions_tests.py` 离线覆盖，且本次真下载用的就是清单版本 |
| **`docker` / `pulsar` 在 Windows 的可用性** | 平台事实不支持（见 3.3） | 已在界面明确说明并给替代路径 |

### 5.3 环境约束（影响可测范围，不是产品缺陷）

1. **磁盘**：测试前 C: 剩 10.2GB，测试后剩 **3.0GB**。组件归档与解压目录合计已占 ~11GB
   （`~/.env-tools` 11.7GB）。为完成测试清理了 1.36GB 陈旧归档（过期的 `.part`、
   重复版本包如 `nacos-2.3.0.zip`）。**产品本身会把每个下载包永久留在
   `~/.env-tools/<key>/downloads/`**（最重的 MongoDB 单包 748MB）—— 建议后续加"安装成功后清理归档"。
2. **沙箱超时打断**：若干命令因沙箱超时收到终止信号（表现为 `[exit code: 1]`），
   已重跑确认；最终结论不依赖任何被中断的那一轮。
3. **管理台口令**：`HKCU` 用户级写入，无需提权；HKLM 不在本工具职责内。

---

## 六、建议（按优先级）

1. **补数据库初始化**（最高优先，直接对应"开机就能用"）：
   `mysql` 需要 `mysqld --initialize-insecure --datadir=...` + 一份 `my.ini`；
   `postgresql` 需要 `initdb -D <data>`。目前用户装完拿到的是"能跑 `--version` 的二进制"，
   不是"能连的数据库"。建议做成 `LaunchSpec.post_install` 或组件的 `post_install` 步骤，
   并在 `data_note` 里写明初始账号（mysql 的 root 空密码、PG 的当前用户）。
2. **加"清理归档"选项**：安装成功后删除 `downloads/` 里的归档（可配置开关），
   或在卸载时一并清理。当前 26 个组件的归档会长期占 2-3GB。
3. **补一次真正的空目录全量演练**（需要一台空机器或先扩磁盘），
   作为"发布前"的门禁，而不是靠本报告的部件级结论。
4. **把 `bt_live_matrix.py` 纳入发布前手工门禁清单**（它与 9 个离线护栏互补：
   护栏防回归，矩阵防"代码对但环境不通"）。
5. **`jenkins` 的停止**可评估改成 `stop_kind="port_lookup"`（与 nacos/activemq 一致，
   一次确认即可），代价是要同步调整 `bt_launch_tests.py` 里钉住"Windows 上 pid 型要先请示"的用例。
6. **`docker` 平台形态**：如果确实想在 Windows 上给用户一些东西，
   可以做"WSL2 检测 + 一条 `wsl --install` 指引"，或在卡片上直接给 Docker Desktop 的下载链接
   （现在给的正是这个）。

---

## 七、改动清单（本轮）

| 文件 | 类型 | 内容 |
|---|---|---|
| `main.py` | 代码 | 12 个缺陷的修复；新增 `install_downloaded()` 等模块级落位函数；新增 Erlang 隐藏组件与 4 个抓取/URL 函数；新增 6 个前置自举函数（`prereq_components` / `java_major_of` / `jdk_home_version` / `prereq_install_versions` / `pick_prereq_version` / `prereq_already_installed` / `installed_erlang_erl`）；新增 `sync_runtime_assets()`；`process_alive` 精确化；`stop`/`force_stop` 端口归属兜底；启动后控制台就绪提示；加速器顺序重排；docker/pulsar 平台说明重写 |
| `bt_live_matrix.py` | 新增 | 真机功能矩阵演练器（install / verify / switch / launch / autoprereq 五个阶段） |
| `DEVELOPMENT.md` | 文档 | 新增 **R6 前置运行时自举**、**R7 单文件落位文件名**、**R8 动态内容目录同步**、**R9 非 ASCII 主机名节点名**；R1.3 加速器速度表更新 |
| `bt_launch_tests.py` | 测试 | `min_java_major` 用例从"jenkins 必须 None"改为"jenkins 必须 11（实测），其余必须 None"；prereq 文案断言改为关键信息断言；桩掉自家 Erlang 查找 |
| `bt_component_category_tests.py` / `bt_search_and_newcmp_tests.py` / `bt_multiversion_tests.py` | 测试 | 组件数 26 → 27（+隐藏 erlang），并新增"界面可见数仍是 26"的反向断言 |

---

## 八、附：本次真机跑出来的证据样本

```
# 1) nginx 首页（缺陷 2 修复前 → 修复后）
修复前: GET http://127.0.0.1:8888 → 404（153 字节）
修复后: GET http://127.0.0.1:8888 → 200

# 2) tomcat 首页（缺陷 3）
修复前: GET http://127.0.0.1:8081 → 404（649 字节）
修复后: GET http://127.0.0.1:8081 → 200

# 3) rabbitmq 节点名（缺陷 4）
修复前: rabbit_nodes_common.erl:254 :gen_tcp.connect/4 → ** (exit) :badarg  (rc=70)
        Error: unable to perform an operation on node 'rabbit@鹅城剑仙'
修复后: Status of node rabbit@localhost ...
        RabbitMQ version: 4.0.9
        Erlang configuration: Erlang/OTP 27 [erts-15.2.7] [64-bit] [smp:8:8]

# 4) GitHub 加速器（缺陷 5）
ghproxy.net   14 KB/s (pwsh) / 28 KB/s (erlang)   ← 原首位
gh-proxy.com 133 KB/s        / 117 KB/s
ghfast.top   751 KB/s        / 401 KB/s           ← 现首位
裸 github.com 请求超时
实测同一台机器同一份 Erlang 包：6.4 KB/s → 1020 KB/s

# 5) 缺 JDK 自举（缺陷 6）
[PASS] autoprereq/prereq/detects_missing_jdk     缺=['jdk']
[PASS] autoprereq/prereq/picked_version          jdk 21
[PASS] autoprereq/prereq/jdk_installed           C:\Users\life\.env-tools\jdk\jdk-21
[PASS] autoprereq/prereq/jdk_major_readable      major=21
[PASS] autoprereq/prereq/apply_jdk_active
[PASS] autoprereq/prereq/launch_gate_passes

# 6) jenkins 起停（缺陷 1/8/10/11）
落位后目录: ['jenkins.war']
detect -> installed=True source=JENKINS_HOME
start notes: 已启动，但控制台 http://127.0.0.1:8080/ 现在返回 503（服务还在初始化），稍等一会儿再点控制台；端口已经在正常服务。
登记 pid 持有端口? True
厂商日志: Jenkins is fully up and running
```

---

**报告结束。** 所有编号缺陷均已在工作区代码里修复。证据由两部分构成：

- **真机矩阵**：本轮累计执行 **631 项**检查（audit 258 / install 166 / verify 73 / launch 102 /
  switch 26 / prereq 6），其中 94 项是"修复前的红灯"或"平台限制的预期红灯"，
  最终一轮干净复跑只剩 1 项平台限制红（docker 无 Windows 包）；
- **离线护栏**：9 个套件共 **497 条**（226+153+30+9+26+4+9+17+23）全 `OK`。

明细数据留在工作区：`live_*.json`（每次运行的逐项结果）+ `logs/g*.log`、`logs/launch_*.log`（原始输出）。
