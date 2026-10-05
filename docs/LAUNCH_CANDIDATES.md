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
| **mysql** | 3306 | 首次要初始化数据目录（`--initialize-insecure`）、Windows 服务 vs 前台进程 | 要（端口写进 our.cnf 副本） |
| **postgresql** | 5432 | `initdb` 初始化、密码写在 `.pgpass` | 要 |
| **mongodb** | 27017 | 需要 `--dbpath`，数据目录结构简单 | 要 |
| **elasticsearch** | 9200 | 必须设 `discovery.type: single-node` 否则起不来；ES8+ 默认开安全认证 | 要（改副本） |
| **rabbitmq** | 5672/15672 | 依赖 Erlang，Windows 版还要装 Erlang 运行时 | 要 |

**共同点**：都需要 `port_writeback` + conf 副本 + 首次初始化流程。
按 `docs/HOW-TO-REQUEST-COMPONENT-LAUNCH.md` 的模板提需求时把这几条写清。

## C 档：能做但要特别小心端口与依赖顺序

| 组件 | 端口 | 风险 |
|------|------|------|
| **kafka** | 9092(+ 派生) | 强依赖 ZooKeeper（**新版本已废弃 KRaft 模式**，需确认版本）；端口写进 `server.properties` |
| **rocketmq** | 9876/10911/10909 | 三个端口都是对外协议，不能平移；要设 `brokerIP1` |
| **pulsar** | 8080/6650/6651 | 端口与Tomcat 撞；standalone 模式启动慢（实测过） |
| **seata** | 8091/9848/9849 | 依赖注册中心（ nacos/eureka），**单独起stop 没有意义** |

## D 档：不适合做「启动/停止」—— 建议跳过

| 组件 | 为什么不适合 |
|------|-------------|
| **jdk / maven / node / go / gradle / bun / python / git / powershell / conda** | **是工具链不是服务**。`java -version` 跑完就退出，没有"常驻进程"也没有"停止"。做「启动」等于假装它是个服务 |
| **kubectl** | 只是 CLI 客户端，服务器在集群那边 |
| **docker** | **需要 Docker Desktop 守护进程**，不是解压即用。它能「装」，不能「起停」 |

> 这一档共 11 个。如果你看到「26 个里只有 13 个能做」的答案就是这么来的 ——
> **剩下的 11 个不该做，做了也是假的**。

---

## 我的建议：分三批做

1. **第一批**：nginx（**已实测通过，只差写代码**）→ tomcat。
   nginx 这轮已经把启动/停止/pid_role/端口探活全部实测清楚了，
   剩下的是套 `LAUNCH_OF` 登记 + 护栏。
   这一批的价值是**验证我这套起停框架对"非 Java 中间件"也成立**
   —— 现在三个已接入组件全是 Java 系。
2. **第二批**：mysql、elasticsearch —— 覆盖面最广（几乎人人要），
   能顺带把「首次初始化」和「conf 副本」这两个模式跑通。
3. **第三批（看你需要）**：postgresql、mongodb、rabbitmq、kafka。

---

## 必须说清的诚实边界

**已实测的只有 nginx（2026-10-06）**；已接入并实测过的是 Nacos / ActiveMQ / Jenkins。
**B / C 档的端口、配置键名、启动命令全是按厂商惯例推的，本机没装过、没跑过。**

按本项目铁律「不这样就真的出过问题」，这些必须**打开包 grep + 跑一次厂商命令**核实：
历史上我凭白名单推断过 Nacos 的控制台路径，实测是 `/nacos` 而不是我"推"的那个；
ActiveMQ 的 `activemq.bat console` 里`console` 根本不是 task，传错会**以退出码 0 静默退出**。

**所以下一批接入的第一步永远是实测**，本文档随实测进展更新。
已知会踩的具体坑（`discovery.type` 的键名、`--initialize-insecure` 的参数、
Kafka 是否已切KRaft）都标在对应行的「关键难点」里。