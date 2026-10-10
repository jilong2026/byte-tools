# 哪些组件还能做成「一键启动/停止」—— 分档判断

> 判断日期：2026-10-06。已接入 3 个（jenkins / nacos / activemq）。
> **本文档区分「已核实」与「待真机确认」** —— 没跑过的组件不下结论。

## 一个前提：起停能力与「多版本/ 有 XXX_HOME」无关

盘点的 23 个未接入组件里，有 17 个带 `XXX_HOME`（jdk/maven/tomcat/mysql/…）。
**这不代表它们适合做起停** —— 恰恰相反：`XXX_HOME` 是给「别的程序调用」用的，
说明它是**库/工具链**（用完就退出，不是有生命周期的服务）。
带 XXX_HOME 且真正常驻的是中间件，那是另一类。

真正的判据是三个问题：
1. 它有没有**自己的常驻进程**（不是一个跑完就退的 CLI）？
2. 它有没有**端口**能证明它在跑？
3. 它有没有**官方的停止手段**（而不是只能 kill）？

---

## A 档：结构上完全具备，接入成本最低

这三个的共同点：**解压即用、自带 start/stop 命令、端口固定、无状态**
—— 和 activemq 的形态一模一样，不需要 `port_writeback`、不需要 conf 副本。

### nginx 1.31.6 —— 已实测通过（2026-10-06）

包解开只有 `nginx.exe`（2.8MB），全在 `conf/` 与 `logs/` 里。实测结论：

| 事项 | 实测值 |
|------|--------|
| 启动命令 | `nginx.exe`（**无参数，前台阻塞** —— 必须后台化，否则终端卡死） |
| 停止命令 | `nginx.exe -s stop` ✅ 有效 |
| 端口 | 改 `conf/nginx.conf` 的 `listen`，实测 8899 可用 |
| 探活 | HTTP 200（起后约 2-3 秒） |
| pid | `logs/nginx.pid` 里是 **worker PID**，与监听端口的 PID **不同** |

**两个坑（接入时必须处理）**：

1. **`-s stop` 的报错不能当失败判据**。第一次实测它打
   `OpenEvent("Global\ngx_stop_71444") failed (2: 文件不存在)`，
   **但退出码是 0、且端口确实释放了**。重复两次都是这样 ——
   那是Windows 版 nginx 的正常噪音，不是失败。
   **判"是否停掉"必须看端口，不能看它的 stderr 或退出码。**
   这与 ActiveMQ 那个坑同类：**厂商脚本用退出码表达"我执行了"，
   不是"我成功了"。**
2. **`pid_role` 必须是 `launcher`**：`nginx.pid` 里是 worker PID，
   真正 bind 端口的是 master。照 `pid_role=launcher` 走端口反查停止即可。

**还需确认**（本轮没测）：端口 80 被占时的行为、按我们的规则该"结束占用者"
还是让用户改 —— 建议接入时把主口定在 80 但允许改副本。

### tomcat 10.1.60 —— 结构已知，脚本名待核实

标准 Tomcat 布局（`bin/startup.bat`、`bin/shutdown.bat`、端口 8080）。
**需先核实**：`shutdown.bat` 在 Windows 上是真的发 shutdown 端口信号还是只打日志；
`CATALINA_HOME` 改端口要不要连带 `server.xml`（端口写在 `conf/server.xml` 的
`Connector port=` 那一行）。

---

## B 档：能做，但要处理数据/初始化（收益高，坑也明确）

| 组件 | 端口 | 关键难点 | 是否要写配置 |
|------|------|---------|-------------|
| **rocketmq** | 9876/10909/10911 | **已实测通过**（见下）；停止必须走端口反查；`~/store` 数据目录 | 不用改（端口不在主 conf 里） |
| **mysql** | 3306 | 首次要初始化数据目录（`--initialize-insecure`）、Windows 服务 vs 前台进程 | 要（端口写进 our.cnf 副本） |
| **postgresql** | 5432 | `initdb` 初始化、密码写在 `.pgpass` | 要 |
| **mongodb** | 27017 | 需要 `--dbpath`，数据目录结构简单 | 要 |
| **elasticsearch** | 9200 | 必须设 `discovery.type: single-node` 否则起不来；ES8+ 默认开安全认证 | 要（改副本） |
| **rabbitmq** | 5672/15672 | 依赖 Erlang，Windows 版还要装 Erlang 运行时 | 要 |

**共同点**：都需要处理首次初始化/ 数据目录，且大多要 conf 副本。
按 `docs/HOW-TO-REQUEST-COMPONENT-LAUNCH.md` 的模板提需求时把这几条写清。
**rocketmq 是其中最省事的一个**（不需要 ZooKeeper，5.x 自带 namesrv）。

## rocketmq 5.3.1 —— 已实测通过（2026-10-06），**但实测推翻了我原来的两条判断**

包 86MB（解包后目录名 `rocketmq-all-5.3.1-bin-release`）。实测结论：

| 事项 | 实测值 |
|------|--------|
| 启动 namesrv | `bin\mqnamesrv.cmd` → **9876 监听** |
| 启动 broker | `bin\mqbroker.cmd` → **10909/ 10911 / 10912 三个端口同时监听** |
| broker 注册 | `bin\mqadmin.cmd clusterList -n 127.0.0.1:9876` 退出码 0，日志确认 `boot success` |
| 停止 | `bin\mqshutdown.cmd broker` / `namesrv` |
| 依赖 | **JDK 17+**（脚本里 `if %JAVA_MAJOR_VERSION% lss 17` 分叉）、硬编码 `-Xms2g -Xmx2g` |
| `pid_role` | `server`（PID 93748/ 75312 直接就是监听进程） |

### 坑一：**入口脚本分两级，用错必炸**

-❌ `bin\runbroker.cmd` —— **不能用**。它末尾是 `%*` 纯透传，**不设 `ROCKETMQ_HOME`**，
  而 `BrokerStartup` 靠 `ROCKETMQ_HOME` 找 `conf/broker.conf`
  → `SystemConfigFileHelper.loadConfig` 抛 `FileNotFoundException`，broker 起不来。
- ✅ `bin\mqbroker.cmd` —— **正确入口**。它开头检查 `ROCKETMQ_HOME`
  （没设就 `EXIT /B 1`），再调 `runbroker.cmd` 并补上 `-Drmq.logback...`。

**通用教训**：厂商目录里 `mq*.cmd`（一级入口，做环境检查）与 `run*.cmd`
（二级脚本，假设环境已就绪）**不是一回事**。要选**带环境变量检查的那个**。
（同ActiveMQ：`activemq.bat console` 里的 `console` 根本不是 task。）

### 坑二：`mqshutdown.cmd` **报"Done!"但根本没停掉** ⚠️

实测输出：

```
killing broker
Done!
find:鈥楤rokerStartup鈥: No such file or directory   ← stderr 里有这行
```

**退出码 0、打印 `Done!`，但 10909/10911 仍在监听，进程还活着** ——
最后是我自己 `kill` 掉的。原因：**它按进程名 `find`，找不到**（我的 broker 是
用 `cmd /c mqbroker.cmd` 起的，进程名对不上它的预期）。

→ 结论：**RocketMQ 的停止不能信 `mqshutdown.cmd`，必须走端口反查 + 结束进程**
（我们框架里的 `stop_kind=port_lookup` + `evict_port_occupant`，正好覆盖）。

### 坑三：**端口根本不在 `broker.conf` 里**

`conf/broker.conf` **0 处`listenPort`**（我实测grep 过），只有集群/角色/刷盘策略。
端口是**代码里的默认值**（只有 `conf/container/*.conf` 那些容器模板里才出现 `listenPort`）。

→ **我原先在分档表里写「端口写进 broker.conf」是错的**。
实际要么用默认端口、要么改容器模板那种 conf，**不是主 conf**。
好消息是端口不改就不需要 `port_writeback`。

###坑四：消息数据落在 **`~/store`**，不在安装目录

实测 broker boot 后 `~/store` 生成 37MB（`commitlog/ consumequeue/ checkpoint/ timerwheel/`）。
与 `data_note` 写的一致。**多版本并存时必须给每个版本分开设 `storePathRoot`**，
否则两个 broker 抢同一个目录 —— 这点要写进 `data_note`。

### 启动耗时与内存

broker 起来约 **25-30 秒**（比 nacos/activemq 慢），`startup_timeout` 要给够。
脚本里默认 `-Xms2g -Xmx2g`，机器内存小的话得能覆盖。

### 结论

**能做，且值得做**（比 kafka 省事得多 —— **不需要 ZooKeeper**，
5.x 已是自带 namesrv 的架构，kafka 还要单独管 zk）。
建议从 C 档提到 **B 档偏上**：实测已通，剩下的是套 `LAUNCH_OF` 登记 + 护栏，
主要工作量在「停止走端口反查」和 `data_note` 讲清 `~/store`。

## C 档：能做，端口/依赖有坑（**未实测**，按厂商惯例推的）

| 组件 | 端口 | 待核实的风险 |
|------|------|-------------|
| **kafka** | 9092 | **强依赖 ZooKeeper**（5.x 已切KRaft，要确认本项目那几个版本用哪种模式）；端口在 `server.properties` |
| **pulsar** | 8080/6650/6651 | 8080 撞 Tomcat；standalone 启动慢（之前实测过就绪耗时）；数据在 `pulsar/standalone/data` |
| ~~**seata**~~ | — | **已于 2026-10-06 实测**（见下节）。原表填的 `9848/9849` 是 Nacos 的 gRPC 口，与 Seata 无关 |

**注意 kafka 的复杂度被低估了**：要管 zookeeper + broker 两个进程、两套端口。
rocketmq 对应的是「一个 namesrv + 一个 broker」，少一半。

## seata —— **已接入**（2026-10-06 真机演练 PASS）

**本次最关键的发现：两个大版本的架构根本不是一回事**，所以"seata 有没有控制台"
这个问题在 2.2.0 和 2.6.0 上的答案是相反的。

| | **2.2.0（已接入）** | **2.6.0（未接入）** |
|---|---|---|
| 进程数 | **单进程**：server 自己带控制台 | **双进程**：控制台被拆进 namingserver |
| 控制台 | server 自己，**7091** | seata-namingserver，**8081** |
| RPC 口 | **8091**（= server.port + 1000） | 8091 |
| server 启 HTTP？ | **是**（日志 `Adding welcome page: static/index.html`） | **否**（`web-application-type: none`） |
| 控制台出厂账号 | **seata / seata**（实测登录拿到 token） | 留空，要自己配 |
| JDK 门槛 | class 52 → **JDK 8 起得来**（8 与 21 都实测通过） | class 69 → **要 JDK 25**（本机 21 直接 `UnsupportedClassVersionError`） |

### 接入形态：单进程，控制台 7091 + RPC 8091（与 Nacos 同构）

实测证据：

```
Tomcat started on port(s): 7091 (http)
Server started, service listen port: 8091
GET /                 → 200（前端在 seata-server/lib/seata-console-2.2.0.jar）
GET /health           → "ok"（200，免鉴权，ignore-urls 里写着它）
POST /api/v1/auth/login 用 seata/seata → 200 + Bearer token
```

### 端口**必须**用环境变量注入（四条实测，别改回去）

1. `--server.port=7091` **不行** —— seata-server 有自己的 joptsimple CLI，只认
   `-p` / `--port` / `--host` / `--storeMode` / …；传 `--server.port` 会打
   `Option error … but no main parameter was defined in your arg class` 然后**退出、端口不监听**。
2. `-p 7091` 也不行（它改的是 netty 侧，压不住 HTTP 口）。
3. **什么都不传更不行** —— 它有个硬编码兜底口 **7056**，`conf/application.yml`
   里写的 7091 压不住它（2.6.0 的 namingserver 同样落到 7056，写 8081 也没用）。
4. ✅ **`SERVER_PORT=7091` 实测有效**（Spring Boot 的 relaxed binding，优先级压得住硬编码）。
   → 登记为 `extra_env={"SERVER_PORT": "{port}"}` + `port_writeback="cli_only"`。
   **这是本项目第一个靠环境变量传端口的组件。**

### 目录结构（顺带修掉的既有缺陷）

产品原来登记 `path_subdir="bin"`（那是 1.x 的布局），而 2.x 包顶层是
`seata-server/` + `seata-namingserver/` 两个目录 —— 装完 seata 被判成"未安装"，
`SEATA_HOME` 与 PATH 条目指向不存在的目录（本机当时就是这种空壳状态）。
已改为 `seata-server/bin`，装完实测 `exec_path_in_home` 能找到脚本。

### 版本清单为什么只有 2.2.0

同一份 `LaunchSpec` 描述不了两种布局。登记 2.6.0 会让探活去等一个根本不存在的 7091
→ **"装得上、起不来"**，比不提供这个版本糟糕得多。
要加回 2.6.0，得先让 spec 支持**按版本分叉**。

### 演练结果

`tools/bt_real_machine_drill.py --launch seata --yes` ——
启动后 7091/8091 全簇在听、控制台可达、停止后端口全释放、无登记残留。
护栏 13 条（含 5 组变异自检，全部 CAUGHT）。

---

## D 档：不适合做「启动/停止」—— 建议跳过

| 组件 | 为什么不适合 |
|------|-------------|
| **jdk / maven / node / go / gradle / bun / python / git / powershell / conda** | **是工具链不是服务**。`java -version` 跑完就退出，没有"常驻进程"也没有"停止"。做「启动」等于假装它是个服务 |
| **kubectl** | 只是 CLI 客户端，服务器在集群那边 |
| **docker** | **需要 Docker Desktop 守护进程**，不是解压即用。它能「装」，不能「起停」 |

> 这一档共 11 个。如果你看到「26 个里只有 13 个能做」的答案就是这么来的 ——
> **剩下的 11 个不该做，做了也是假的**。

---

## ✅ 2026-10-06：六个组件全部真机验证通过

| 组件 | 端口 | 停止方式 | 真机结论 |
|------|------|---------|---------|
| **tomcat** | 8080 + 8005 | `shutdown.bat`（官方） | PASS |
| **kafka** | 9092 + 9093 | 按登记 PID | PASS（KRaft 4.x **不需要 ZooKeeper**） |
| **rocketmq** | 9876 + 10909 + 10911 | 端口反查（三重闸） | PASS（**两个进程**，已支持双进程） |
| **elasticsearch** | 9200 + 9300 | 端口反查 | PASS（自带 JDK 25，**不需要外部 JDK**） |
| **rabbitmq** | 5672 + 25672 | `rabbitmqctl stop`（官方） | PASS（**需前置 Erlang 27**） |
| **nginx** | **8080** | `nginx -s quit`（官方） | PASS（**主端口由 80 改成 8080**） |

演练命令：`tools/bt_real_machine_drill.py --launch <key> --yes`。
9 套护栏全绿（含 33 条新组件护栏 + 13 条接线护栏），真机 6/6 PASS。

### 演练逼出来的 6 个真缺陷（都已修，且都有护栏钉住）

1. **`resolve_launch_version()` 两个分支语义不一致**
   active 分支返回裸版本号、fallback 返回完整目录名 → 调用方二次拼前缀 →
   `[WinError 267]`。**触发条件是「刚下载安装完、还没点过切换生效版本」**
   —— 也就是最常见的那个状态，一键启动必然失败。
2. **ES 起不来：系统级 `CLASSPATH` 是 JDK 8 遗留**
   （`.;%JAVA_HOME%\lib\dt.jar;...`，`%JAVA_HOME%` 是字面量、`dt.jar` 早已不存在）。
   JVM 不做 `%VAR%` 替换，ES 9 的 JarHell 校验会逐个 `new JarFile(classpath 里的项)` → fatal。
   报出来的错指向 `%JAVA_HOME%\lib\dt.jar`，**极具误导性**（我被它带偏查过一次）。
   已在 spawn 前清空子进程的 CLASSPATH（**不动用户的系统设置**）。
3. **中文主机名 → rabbitmq 节点名非 ASCII** → epmd 注册截断 →
   **服务器起来、端口在听、日志一切正常，但所有 `rabbitmqctl` 子命令全挂**
   （`:badarg` / rc=70）：UI 上看着启动成功，实际停不掉也查不了状态。
   已固定 `RABBITMQ_NODENAME=rabbit@localhost`（本机主机名是「鹅城剑仙」）。
4. **nginx 必须给 `-p`（prefix）**
   `-c` 只决定读哪个配置文件，而**日志与 pid 文件路径是相对 prefix 算的**
   （不是 cwd、也不是 -c 那个文件的位置）。不给 prefix 时 pid 找不到 →
   `-s stop` 彻底停不掉；退到强杀则 master 死、**worker 还活着** → 孤儿占端口。
5. **产品装的是 rabbitmq 的 Linux 包**
   `url_list_map` 里只有 `generic-unix`，而它 `sbin/` 下全是**无扩展名脚本**，
   Windows 上跑不起来（与产品登记的 `rabbitmq-server.bat` 对不上）。
   Windows 官方 zip（`rabbitmq-server-windows-<v>.zip`）华为云实测 200，已配。
6. **stop侧的 `subprocess.run` 不传 env**
   → `rabbitmqctl` 找不到 `erl.exe`、拿不到 NODENAME → **静默失败**
   （输出被 DEVNULL 吞掉），表现是「点了停止，30 秒后弹强杀确认框」。

### 三个「厂商脚本」类别的通用教训

- **不是所有组件都能用 HTTP 探活**：kafka（Kafka 协议）、rocketmq、rabbitmq（AMQP）
  都不能，要用它们自带的 CLI（`BrokerApiVersionsCommand` / `clusterList` /
  `rabbitmqctl status`）。为此加了 `LaunchSpec.service_probe` 字段。
  反过来，**有端口但没有控制台**的（tomcat/nginx/ES）要用「有响应就算活」
  （`http_responds`，404 也算）—— tomcat 启动后 `/` 就是 404，它在正常服务。
- **`-c`/`-p` 这类参数不是可选的**：nginx 与 ES 都靠环境变量或命令行参数定位
  自己的文件，`extra_env`（ES_HOME / ES_PATH_CONF）与 `-p`（nginx prefix）缺一不可。
- **多进程组件不能只登记一个 PID**：nginx（master+worker）、
  rocketmq（namesrv+broker）都是。nginx 用官方 `-s quit`；
  rocketmq 走了新的 `extra_processes` 双进程机制。

---

## ✅ 2026-10-06：十个组件全部在「干净环境」真机验证通过

演练命令：`tools/bt_clean_env_drill.py`（**主动剔掉组件类 `*_HOME` 与 `CLASSPATH`** 再跑，
模拟 exe 的干净环境 —— 详见下面「为什么必须剔干净」）。
结果 **10/10 PASS**，护栏 226 条全绿。

| 组件 | 端口簇 | 有网页控制台 | 停止方式 |
|------|--------|-------------|---------|
| **jenkins** | 8080 | ✅ `/login` | 按登记 PID |
| **nacos** | 8848 + 9848 + 9849 | ✅ `/nacos` | 端口反查 |
| **activemq** | 8161 + 61616 | ✅ `/admin` | 端口反查 |
| **seata** | 7091 + 8091 | ✅ `/` | 按登记 PID |
| **tomcat** | **8081** + 8005 | ❌ | `shutdown.bat`（官方） |
| **kafka** | 9092 + 9093 | ❌ | 按登记 PID |
| **rocketmq** | 9876 + 10909 + 10911 | ❌ | 端口反查（**两个进程**） |
| **elasticsearch** | 9200 + 9300 | ❌ | 端口反查 |
| **rabbitmq** | 5672 + 25672 | ❌ | `rabbitmqctl stop`（官方） |
| **nginx** | **8888** | ❌ | `nginx -s quit`（官方） |

**只有 4 个组件有网页控制台**（jenkins / nacos / activemq / seata）。
另外 6 个的卡片上**不显示「打开控制台」按钮**，状态标签写
「● 运行中 · 端口 N · 无网页控制台」，启动日志与 `credentials_hint`
说清各自的实际用法 —— 因为给一个不存在的控制台指路，用户点开只会看到 404，
然后以为服务坏了。

### ⚠️ 端口分配（改过两轮，最终版）

| 组件 | 端口 | 为什么不是别的 |
|------|------|--------------|
| jenkins | 8080 | 官方默认 |
| tomcat | **8081** | 8080 归 jenkins —— 端口冲突不是"谁后启动谁赢"，是**两个都坏** |
| nginx | **8888** | 官方 80 在 Windows 上被 `System`（http.sys，IIS/WinRM 共用）占着，绑不了也杀不掉（WinError 5）；8080 已被占 |
| 其余 | 见上表 | 官方默认 |

护栏 `PortNoCollisionAcrossComponents` 遍历 `LAUNCH_KEYS` 两两比对端口簇。

### 演练逼出来的 8 个真缺陷（都已修+ 钉护栏）

1. **`ROCKETMQ_HOME` 没注入** → RocketMQ 拒绝启动
2. **无控制台的组件照样显示「控制台：URL」** → 浏览器打开必然 404
3. **端口撞车**（jenkins/tomcat/nginx 都想用 8080）→ 两个组件各自看起来都正常，
   只有交叉访问才暴露
4. **ES 的 `Failure running machine-learning native code`** → ES 9 在 Windows 上
   加载 ML 原生库失败，节点起不来、端口永不监听 → 加 `-Expack.ml.enabled=false`
   （这与之前修的 `CLASSPATH` 污染是**两个独立问题**，修一个才看得见下一个）
5. **`resolve_java_home()` 只认 active 登记或 `JAVA_HOME`** → 用户装完 JDK
   但没点过「切换生效版本」时，java 系组件一律报"需要先有 JDK"
6. **rabbitmq 的 `data_note` 说错了**：官方默认落 `%APPDATA%\RabbitMQ`，
   而实测**那个目录根本不会被创建**（我们指定了 `RABBITMQ_BASE`）
7. **`shutdown_commands` 不传 env** → `rabbitmqctl` 找不到 erl.exe、
   静默失败 →「点了停止 30 秒后弹强杀框」
8. **rabbitmq 装的是 Linux 包**（`url_list_map` 里只有 `generic-unix`）

### ⭐ 验证方法本身的三条坑（本轮最重要的产出）

这三条会让你的验证结果全是**假绿灯**：

1. **演练环境必须等于（或严于）真实使用环境。**
   我做源码演练时 shell 里带着 4 个 `*_HOME`（早期多版本测试写进去的），
   `dict(os.environ)` 顺手带给了子进程 → **演练全过**；
   而 **exe 启动的进程没有这些变量** → 用户那边立刻失败。
   → `tools/bt_clean_env_drill.py` 主动剔掉组件类 `*_HOME` 与 `CLASSPATH`。
   **但保留 `JAVA_HOME`**：产品里压根没装 jdk（`~/.env-tools/jdk` 是空的），
   java 系组件靠用户系统自带的 JDK，剔掉它等于在测另一台机器。
2. **探活必须用 `health_path`，不能直接探 `console_path`。**
   Jenkins 未初始化时根路径 `/` 返回 **403**（要引导去解锁向导），`/login` 才是 200。
   演练脚本直接探 `/` → 把一个**完全正常的 Jenkins** 判成"打不开"。
3. **演练清单不要手写。**
   我手写的清单**漏了 seata** —— 它确实在 `LAUNCH_KEYS` 里、磁盘上也装着，
   却从没被演练过。手写清单**静默漏项**：不报错，只是少测一个。
   → 改为 `sorted(main.LAUNCH_KEYS)`，并加护栏钉住这一点。

---

## 我的建议：分批做（按「已实测程度」排）

1. **第一批（最省事，实测已通）**：**rocketmq**、**nginx**
   - rocketmq 实测已通，剩 `LAUNCH_OF` 登记 + 护栏；且它**不需要 ZooKeeper**
   - nginx 实测已通，且能验证框架对**非 Java 中间件**也成立
     （现在三个已接入组件全是 Java 系）
2. **第二批（覆盖面最广）**：tomcat、mysql、elasticsearch ——
   能顺带把「首次初始化」和「conf 副本」这两个模式跑通。
3. **第三批（看你需要）**：postgresql、mongodb、rabbitmq、kafka。

---

## 必须说清的诚实边界

**已实测的：nginx、rocketmq、seata**（2026-10-06 本机跑通）；
已接入并实测过的是 Nacos / ActiveMQ / Jenkins / tomcat / kafka / elasticsearch / rabbitmq。
**B档剩余（mysql/postgresql/mongodb）与 C 档剩余（pulsar）的端口、配置键名、启动命令
全是按厂商惯例推的，本机没装过、没跑过。**

按本项目铁律「不这样就真的出过问题」，这些必须**打开包 grep + 跑一次厂商命令**核实：

- 凭白名单推断过 Nacos 控制台路径，实测是 `/nacos` 而非推断的那个；
- ActiveMQ 的 `activemq.bat console` 里`console` 不是 task，传错会**以退出码 0 静默退出**；
- **rocketmq 实测又推翻了我两条判断**：端口根本不在 `broker.conf` 里；
  `mqshutdown.cmd` 打印 `Done!` 但**根本没停掉**。
  ——**「按惯例推」的错误率比我以为的高，而且错得理直气壮。**

**所以下一批接入的第一步永远是实测**，本文档随实测进展更新。