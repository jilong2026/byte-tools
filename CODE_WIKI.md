# byte-tools · Code Wiki

> 本文档面向二次开发者与维护者，系统性梳理 `byte-tools` 项目的整体架构、模块职责、关键类与函数、依赖关系和运行方式。
> 若仅想"使用"该工具，请阅读 [README.md](./README.md)。

---

## 目录

- [一、项目概述](#一项目概述)
- [二、整体架构](#二整体架构)
- [三、目录结构](#三目录结构)
- [四、主要模块职责](#四主要模块职责)
- [五、关键类与函数说明](#五关键类与函数说明)
- [六、核心流程](#六核心流程)
- [七、依赖关系](#七依赖关系)
- [八、项目运行方式](#八项目运行方式)
- [九、配置与扩展指南](#九配置与扩展指南)
- [十、已知约束与注意事项](#十已知约束与注意事项)

---

## 一、项目概述

**byte-tools** 是一款基于 **Python 3.10–3.14 + PySide6** 的跨平台桌面 GUI 工具，目标是把开发者最常用的语言运行时、构建工具、中间件的下载与配置全部自动化。

一句话定位：

> 让"新机器 → 一套完整开发环境"这件事变成点几下鼠标就搞定。

支持 **36 个可见组件**（26 个可一键装配 + 10 个只下载的「开发工具」），按分类组织如下（详见 [DEVELOPMENT.md](./DEVELOPMENT.md) 的 R1 规则）：

| 分类 | 组件 | 内部 key | 环境变量 | 默认版本来源 |
|------|------|---------|---------|-------------|
| 语言运行时 | JDK (Temurin) | `jdk` | `JAVA_HOME` | Adoptium API |
| 语言运行时 | Python | `python` | —（走 PATH） | python.org FTP 索引 |
| 语言运行时 | Node.js | `node` | `NODE_HOME` | Node.js dist/index.json |
| 语言运行时 | Go | `go` | `GOROOT` | go.dev/dl 索引 |
| 语言运行时 | Bun | `bun` | —（走 PATH） | GitHub Releases |
| 语言运行时 | PowerShell 7 | `powershell` | —（走 PATH） | GitHub Releases API（PowerShell/PowerShell） |
| 构建工具 | Apache Maven | `maven` | `MAVEN_HOME` | Apache 归档目录页 |
| 构建工具 | Gradle | `gradle` | `GRADLE_HOME` | services.gradle.org 索引 |
| 应用服务器 | Apache Tomcat | `tomcat` | `CATALINA_HOME` | Apache 归档目录页 |
| Web 服务 | Nginx | `nginx` | —（走 PATH） | 华为云镜像目录页（回退 nginx.org/download） |
| 数据库 | MySQL Server | `mysql` | `MYSQL_HOME` | MySQL 归档索引（无公开 API，含保底清单） |
| 数据库 | MongoDB | `mongodb` | `MONGODB_HOME` | MongoDB 下载中心索引 |
| 数据库 | PostgreSQL | `postgresql` | `PG_HOME` | PostgreSQL 源码归档索引 |
| 容器与编排 | Docker | `docker` | —（走 PATH） | Docker 官方 static 版本（仅 Linux/Mac） |
| 容器与编排 | kubectl | `kubectl` | —（走 PATH） | Kubernetes dl.k8s.io 索引 |
| CI/CD | Jenkins | `jenkins` | —（走 PATH） | get.jenkins.io war-stable 索引 |
| 消息队列 | RabbitMQ | `rabbitmq` | `RABBITMQ_HOME` | GitHub Releases（仅 Linux/Mac） |
| 消息队列 | Apache Kafka | `kafka` | `KAFKA_HOME` | Apache 归档目录页 |
| 消息队列 | Apache RocketMQ | `rocketmq` | `ROCKETMQ_HOME` | Apache 归档目录页 |
| 消息队列 | Apache Pulsar | `pulsar` | `PULSAR_HOME` | Apache 归档目录页 |
| 消息队列 | ActiveMQ | `activemq` | `ACTIVEMQ_HOME` | Apache 归档目录页 |
| 服务发现/事务 | Nacos | `nacos` | `NACOS_HOME` | GitHub Releases（alibaba/nacos） |
| 服务发现/事务 | Seata | `seata` | `SEATA_HOME` | Apache 分发目录（`/apache/incubator/seata/`；GitHub Releases 仅用于版本列表抓取） |
| 搜索引擎 | Elasticsearch | `elasticsearch` | `ES_HOME` | elastic.co 归档索引 |
| 版本控制 | Git | `git` | — | Git for Windows Releases API |
| Python 发行版 | Miniconda | `conda` | `CONDA_HOME` | Anaconda Repo 索引（安装器模式） |

> 平台支持差异（2026-09-28 实测）：Docker / RabbitMQ 在 Windows 下不提供自动下载（需用 Docker Desktop / 手动安装 Erlang）；PostgreSQL 仅 Windows 支持（Linux/Darwin 提示用发行版包管理器 / brew）；MongoDB 支持 Windows/Linux（macOS 不提供自动下载）；Git 仅 Windows 提供便携包（Linux/macOS 上游只有源码包，提示用 apt/dnf/yum/brew）。详见各组件 `unsupported_platform_hint` 字段与「十、已知约束与注意事项」。

技术栈速览：

- **语言**：Python 3.10 – 3.14（PySide6 6.11 声明 `requires_python >=3.10,<3.15`）
- **GUI 框架**：PySide6（Qt 6 官方 Python 绑定，LGPL 授权）
- **HTTP 客户端**：requests
- **压缩解压**：Python 标准库 `zipfile` + `tarfile` + 单二进制 / `.war` 单文件直接重命名
- **多线程**：QThread（后台下载、版本抓取，UI 不阻塞）
- **打包**：PyInstaller（单文件可执行 + macOS `.app`）
- **CI**：GitHub Actions 三平台（Windows / macOS / Linux）自动构建发布，并把产物同步到 Gitee Release（见 [.github/workflows/release.yml](./.github/workflows/release.yml)）
- **架构**：单文件应用，`main.py` 内含 UI、数据类、业务逻辑
- **R1 国内镜像优先 + 多源故障转移**：所有组件下载遵循"国内镜像优先 + 多源故障转移 + 末位官网回退"，详见 [DEVELOPMENT.md](./DEVELOPMENT.md) R1 规则

---

## 二、整体架构

项目采用 **单文件扁平架构**，所有逻辑集中在 [main.py](./main.py) 中。从职责维度可划分为 8 个逻辑分层（新增 R1 多源故障转移层）：

```
┌─────────────────────────────────────────────────────────────┐
│                    入口层  main()                            │
│              创建 QApplication + MainWindow                 │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│              UI 层 (PySide6 Widgets)                        │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐  │
│  │ MainWindow   │ │ComponentCard │ │ SearchableComboBox  │  │
│  │ (无边框窗口) │ │ (单组件卡片) │ │ (可搜索下拉框)      │  │
│  │ + 窗口图标   │ │ + 状态胶囊   │ │                      │  │
│  └──────┬───────┘ └──────┬───────┘ └────────────────────┘  │
│         │                 │                                 │
│         │        ┌────────▼─────────┐                       │
│         │        │  DonateDialog    │                       │
│         │        │  (打赏弹窗)      │                       │
│         │        └──────────────────┘                       │
└─────────┼──────────────────────────────────────────────────┘
          │ 信号/槽
┌─────────▼──────────────────────────────────────────────────┐
│              线程层 (QThread 子类)                         │
│  ┌────────────────────┐  ┌────────────────────────────┐    │
│  │ DownloadWorker      │  │ VersionFetchWorker         │    │
│  │ (多源故障转移下载) │  │ (后台抓取官网版本)         │    │
│  └─────────┬──────────┘  └─────────────┬──────────────┘    │
│  ┌─────────▼──────────────────────────┐                    │
│  │ LaunchWorker (启动/停止的耗时动作) │  ← 一键启动新增    │
│  └─────────┬──────────────────────────┘                    │
└────────────┼───────────────────────────┼──────────────────┘
             │                            │
┌────────────▼───────────────────────────▼──────────────────┐
│   R1 多源故障转移层（DownloadWorker 内部）                │
│   构造镜像 URL 列表 → 遍历尝试 → 失败切换 → 末位官网回退  │
│   MIRROR_BASES / DOWNLOAD_PROBE_TIMEOUT / DOWNLOAD_TIMEOUT│
│   DOWNLOAD_RETRY_PER_URL / _mb() / _gh_accelerated()       │
└────────────┬──────────────────────────────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────┐
│   生命周期层（一键启动，见规则 R5）                       │
│   LaunchSpec / LAUNCH_OF 登记表                            │
│   ServiceManager（status/adopt/reconcile/start/stop/       │
│                   force_stop，探针全可注入）               │
│   pick_free_cluster / build_launch_plan / resolve_java_home │
│   load_running_map / save_running_map（~/.env-tools/       │
│                   running.json：端口是真相、PID 是提示）    │
└────────────┬──────────────────────────────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────┐
│              业务逻辑层                                    │
│  ┌─────────────────┐ ┌──────────────────┐                  │
│  │ EnvManager      │ │ extract_archive  │                  │
│  │ (环境变量写入)  │ │ + 单二进制/.war  │                  │
│  └─────────────────┘ └──────────────────┘                  │
└────────────────────────────────────────────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────┐
│              数据/配置层                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐     │
│  │ Component    │ │ComponentVer- │ │ DetectResult   │     │
│  │ (组件抽象)   │ │sion (版本)   │ │ (检测结果)     │     │
│  │ + url_list_  │ │ + url_list_  │ │                │     │
│  │   map        │ │   map        │ │                │     │
│  └──────────────┘ └──────────────┘ └────────────────┘     │
│  ┌──────────────┐ ┌──────────────────────────────────┐     │
│  │ FETCHERS     │ │ URL 构造器（_xxx_urls）           │     │
│  │ (版本抓取表) │ │ 返回 Dict[os, List[str]] 多源列表│     │
│  └──────────────┘ └──────────────────────────────────┘     │
└────────────────────────────────────────────────────────────┘
             │
┌────────────▼──────────────────────────────────────────────┐
│              全局常量与工具函数                            │
│  APP_NAME / GITHUB_URL / CONFIG_DIR / CURRENT_OS / IS_ARM │
│  MIRROR_BASES / DOWNLOAD_PROBE_TIMEOUT / DOWNLOAD_TIMEOUT │
│  DOWNLOAD_RETRY_PER_URL / _mb() / _gh_accelerated()       │
│  human_size() / ensure_dir() / _get() / _probe_version()  │
└────────────────────────────────────────────────────────────┘
```

**架构特点**：

1. **单文件零外部模块**：所有代码集中在 `main.py`，部署/打包极简，适合工具类项目。
2. **UI 与业务通过 Qt 信号槽解耦**：`ComponentCard` 不直接调用业务函数，而是通过 `DownloadWorker` 的信号回调；`MainWindow` 通过 `VersionFetchWorker.done` 信号接收抓取结果。
3. **跨平台抽象集中在 `EnvManager`**：上层逻辑只调用 `set_windows_user_env` / `set_unix_env` 等统一接口，平台差异在内部消化。
4. **数据驱动配置**：组件清单、URL 构造器、版本抓取器全部以 `dataclass` + 函数表（`FETCHERS` 字典）形式声明，新增组件只需添加数据项。
5. **R1 多源故障转移**：`DownloadWorker` 内部遍历 `url_list_map` 提供的 URL 列表，按"国内镜像优先 + 故障转移 + 末位官网回退"顺序尝试，单源失败自动切换下一个，全部失败才向上抛错（详见 [DEVELOPMENT.md](./DEVELOPMENT.md) R1 规则）。
6. **生命周期层（一键启动）**：`ServiceManager` 是本机进程生命周期的唯一入口，探针（`is_listening` / `http_ok` / `process_alive` / `terminate`）全部可注入，测试因此不碰网络也不碰进程；`status/adopt/reconcile` 只读、绝不拉起进程（`bt_launch_tests.py` 的 `NoExecInvariant` 钉死）。当前仅 `LAUNCH_KEYS`（本期 `{jenkins}`）出现启动按钮；能力已实现并有离线护栏，Windows 真机验证待用户在场执行（详见 [DEVELOPMENT.md](./DEVELOPMENT.md) R5）。

---

## 三、目录结构

```
byte-tools/
├── main.py                  # 主程序（含 UI 与全部逻辑，7692 行 / 358401 字节，2026-10-05 实测）
├── requirements.txt         # Python 依赖清单（PySide6、requests）
├── byte-tools.spec      # PyInstaller 打包配置
├── 一键启动项目.bat     # 自举脚本：定位 Python → 建/复用 .venv → 装依赖 → 启动 GUI
├── 一键打包exe.bat      # 自举脚本：同上 + 装 PyInstaller → 产出 dist/ByteTools.exe
├── 同步Gitee产物.sh     # Gitee Release 同步（Linux/macOS/CI；默认只在正文写 GitHub 直链，可观测快速失败 + 幂等 + 收尾校验），由 release.yml 调用
├── 同步Gitee产物.bat    # 本机 Windows 版（双击可运行；它会真的把产物传上 Gitee，国内链路快，与 CI 策略有意不同；内容为纯 ASCII，避免 cmd 按 GBK 解析 UTF-8 出错）
├── README.md                # 中文说明（面向最终用户）
├── README_EN.md             # 英文说明
├── DEVELOPMENT.md           # 开发者文档（开发约定、R1 / R2 / R3 规则等，面向二次开发者）
├── CODE_WIKI.md             # 本文档（代码 Wiki，面向二次开发者）
├── LICENSE                  # MIT 许可证
├── .gitignore               # Git 忽略规则
├── .github/workflows/       # 发布工作流（release.yml：三平台打包 + Gitee 同步）
├── tools/                   # 真机与测量脚本（**不是测试、也不进安装包**）：
│                            #   bt_live_matrix / bt_real_machine_drill / bt_mv_drill(_all) / bt_clean_env_drill
│                            #   bt_bench_sources / bt_probe_newcmp / bt_jdk_mirror_files / bt_render_search
│                            #   bt_archive_layout_audit（归档布局实测，见 R3.22）/ bt_spike_elevated_hklm（一次性验证）
│                            #   都靠 `sys.path` 指向仓库根来 import main，跑法：python tools/<脚本名>
├── bt_multiversion_tests.py       # 离线回归测试：多版本并存与生效版本切换（见 4.9，覆盖清单与用例数以运行输出为准）
├── bt_component_category_tests.py # 离线回归测试：组件分类分组与 Tab（见 R2）
├── bt_download_only_tests.py     # 离线回归测试：「开发工具」只下载那一类（见 R13）
├── bt_search_and_newcmp_tests.py  # 离线回归测试：组件搜索与新组件（26 个用例，见 R2.5）
├── bt_mirror_spec_tests.py        # 离线回归测试：镜像 URL 规范（27 个用例，见 R1.3）
├── bt_refresh_versions_tests.py   # 离线回归测试：刷新版本链路（见 4.9，全量回归 9 套件之一）
├── bt_startup_tests.py            # 离线回归测试：启动期不碰 WMI（见 8.2 与 4.9）
├── bt_gitee_sync_tests.py         # 离线回归测试：Gitee 同步脚本（16 个用例，见 8.4）
├── bt_boot_script_tests.py        # 离线回归测试：两个一键脚本的编码/换行/消息表/Python 自动安装闭环（见 8.2）
├── bt_launch_tests.py             # 离线回归测试：组件一键启动契约（规则 R5；LaunchSpec 表/端口簇/僵尸登记/NoExec 不变量/启停流/卡片与主窗接线）
├── bt_grid_layout_tests.py        # 离线回归测试：卡片网格布局与日志浮层（列数计算/只排可见卡片/顺序不乱/浮层不重排/未读计数与自动收起/视图模式持久化）
└── assets/                  # 静态资源（PyInstaller 打包时通过 datas 一并打入）
    ├── byte-tools-pt.png    # 主界面截图
    ├── byte-tools.png       # 应用窗口图标
    ├── wechat.png           # 微信收款码
    ├── alipay.png           # 支付宝收款码
    └── msg_zh.txt           # 一键脚本的中文文案表（脚本本体必须纯 ASCII，见 8.2）
```

运行时目录（程序首次启动自动创建）：

```
~/.env-tools/                        # CONFIG_DIR，所有组件的家目录
├── config.json                      # 偏好记忆文件（每组件上次选中的版本）
├── jdk/
│   ├── downloads/                   # 原始压缩包缓存
│   │   └── jdk-21.zip
│   └── jdk-21/                      # 解压后的 JDK 根目录
│       └── bin/java
├── maven/
│   ├── downloads/
│   └── maven-3.9.6/
├── tomcat/
├── mysql/
├── python/
├── node/
├── git/
├── go/
├── gradle/
├── bun/
├── docker/                          # Linux/Mac only，Windows 走 Docker Desktop
├── kubectl/                         # 单二进制直接落在 install_dir 根
├── jenkins/                         # jenkins.war 落在根目录，java -jar 启动
├── mongodb/                         # Windows/Linux only（macOS 不支持）
├── postgresql/                      # 仅 Windows（Linux/Darwin 不支持）
├── kafka/
├── rocketmq/
├── pulsar/
├── activemq/
├── nacos/
├── seata/
├── elasticsearch/
└── conda/                          # Miniconda 走静默安装器
    └── conda-py312_24.7.1-0/
```

---

## 四、主要模块职责

### 4.1 全局常量与工具函数（`main.py` 顶部）

| 名称 | 类型 | 职责 |
|------|------|------|
| `APP_NAME` | str | 应用窗口标题，全局唯一展示名 |
| `GITHUB_URL` | str | 标题栏 GitHub 跳转链接 |
| `CONFIG_DIR` | Path | 工作根目录 `~/.env-tools/`，所有组件都装在此 |
| `CONFIG_FILE` | Path | 偏好记忆文件 `~/.env-tools/config.json` |
| `CURRENT_OS` | str | `platform.system()` 结果：`'Windows'` / `'Darwin'` / `'Linux'` |
| `MACHINE` | str | `platform.machine().lower()`，CPU 架构字符串 |
| `IS_ARM` | bool | 是否 ARM 架构（用于挑选 aarch64/arm64 包） |
| `MIRROR_BASES` | List[tuple] | R1 国内镜像源基址清单 `(标识, 基址)`，共 11 项：huaweicloud / huaweicloud-py / tuna / aliyun / nju / ustc / bfsu / tencent（`https://mirrors.cloud.tencent.com`）/ sjtug / npmmirror / daocloud-files（`https://files.m.daocloud.io`） |
| `_MIRROR_BY_NAME` | Dict[str, str] | `MIRROR_BASES` 的标识 → 基址索引，供 `_mb()` 查表 |
| `GH_ACCELERATORS` | List[str] | GitHub Release 反向加速器前缀清单（`ghproxy.net` / `gh-proxy.com` / `ghfast.top`；已停服的 `ghproxy.com`、`gh.idayer.com` 不得再引入） |
| `DOWNLOAD_PROBE_TIMEOUT` | int | R1 参数：单 URL 探测超时 5 秒 |
| `DOWNLOAD_TIMEOUT` | int | R1 参数：单 URL 下载连接超时 30 秒 |
| `DOWNLOAD_RETRY_PER_URL` | int | R1 参数：单 URL 内重试次数 2 |
| `HTTP_UA` | dict | `{"User-Agent": "byte-tools"}`，所有出网请求（`_get()` 与 `DownloadWorker._try_download()`）必须带。实测（2026-09-28）清华 TUNA / BFSU 对 requests 默认 UA 与浏览器 UA 一律回 403，只放行这个自定义 UA |
| `DOWNLOAD_MIN_VALID_BYTES` | int | 4096：下载完成后校验实际字节数，0 字节或短于声明的 `Content-Length` 一律判该源无效并继续故障转移。起因（2026-09-28 实测）：`repo.huaweicloud.com/anaconda/<任意路径>` 301 到软 404 HTML 页、`mirrors.huaweicloud.com/mongodb.org/…` 对缺失文件回空体 200，不加校验会拿到假包、直到解压阶段才炸 |
| `human_size(num)` | func | 字节数 → `"1.5 MB"` 可读字符串 |
| `ensure_dir(path)` | func | 确保目录存在（`mkdir -p` 语义） |
| `_get(url, timeout=10)` | func | 带自动重试 + SSL 降级的 HTTP GET（重试 3 次，指数退避），请求头固定 `HTTP_UA` |
| `_probe_version(exe, args)` | func | 调用可执行文件抓取版本号字符串，失败返回空串；`args` 为空一律不执行（裸跑启动脚本 = 拉起服务），Windows 上带 `CREATE_NO_WINDOW` + `stdin=DEVNULL`，不弹控制台窗口也不被等输入的程序的卡住 |
| `_mb(*names)` | func | 按 `MIRROR_BASES` 标识批量取镜像基址（去尾斜杠），供各 URL 构造器拼接，禁止在表外硬编码镜像域名 |
| `_gh_accelerated(url)` | func | GitHub 裸地址 → `GH_ACCELERATORS` 加速器前缀在前 + 裸地址末位（GitHub 无真镜像，只能走反向代理） |
| `find_dead_tool_path_entries()` | func | 只读预览：列出 PATH 中指向 `CONFIG_DIR` 子树、但目录已不存在的残留条目（供确认弹窗展示） |
| `cleanup_dead_tool_path_entries()` | func | 标题栏「清理残留 PATH」的后端：删掉上一行列出的死条目，工具目录之外的条目一律不动 |

### 4.2 数据模型层

由三个 `@dataclass` 组成，构成项目的数据骨架。

#### `ComponentVersion`

表示某组件的"一个版本"对应的下载元信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | str | 版本号字符串，如 `"21"` / `"3.9.6"` / `"py312_24.7.1-0"` |
| `url_map` | Dict[str, str] | 旧模式：按操作系统键（`Windows`/`Darwin`/`Linux`）映射的**单 URL** |
| `url_list_map` | Dict[str, List[str]] | **R1 模式（推荐）**：按 OS 键映射的 **URL 列表**（国内镜像优先 + 末位官网），与 `url_map` 二选一；非空时 `urls_for_current()` 返回该列表 |
| `archive_map` | Dict[str, str] | 按操作系统键映射的归档类型：`zip` / `tar.gz` / `tar.xz` / `exe` / `sh` / `war` / `""`（空字符串表单二进制） |

方法：
- `urls_for_current()` → 当前系统的下载 URL **列表**：优先 `url_list_map[CURRENT_OS]`，否则退回 `url_map[CURRENT_OS]` 包成单元素列表，无则空列表
- `url_for_current()` → 兼容旧调用方：返回 `urls_for_current()` 的第一项，无则 `None`
- `archive_for_current()` → 当前系统的归档类型；优先 `archive_map`，否则按 URL 列表首项后缀推断

> 动态属性：`fetch_jdk_versions` / `fetch_node_versions` 等抓取器会在返回前给对象挂上 `display_label`（如 `"21 (LTS)"`），用于在下拉框中显示更友好的标签。

#### `Component`

表示一个开发环境组件（如 JDK、Maven）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | str | 内部标识，如 `"jdk"`（用作目录名、配置键、FETCHERS 查找键） |
| `display_name` | str | UI 显示名 |
| `env_var` | Optional[str] | 需要设置的 `XXX_HOME` 变量名；无则只更新 PATH（如 Python、Git） |
| `path_subdir` | str | 需加入 PATH 的子目录，一般为 `"bin"`，Windows 上 Python 是 `"Scripts"`、Kafka 是 `"bin/windows"`（`.bat` 包装器只在 `bin\windows` 下，`bin` 里只有 shell 脚本） |
| `exec_name` | Optional[str] | 用于探测的可执行文件名（不含扩展名）；jenkins.war 之类非命令行可执行文件设为 None |
| `version_args` | List[str] | 探测版本号的命令行参数，默认 `["--version"]`；置为空列表表示不探测版本 |
| `version_probe` | bool | 是否允许在探测阶段真的执行该组件命令取版本。启动脚本型组件（Nacos / Seata / Kafka / RocketMQ / RabbitMQ）必须置 `False`：它们的脚本不认版本参数，一执行就把中间件服务拉起来并弹出控制台窗口 |
| `versions` | List[ComponentVersion] | 该组件的所有可用版本 |
| `installer_mode` | bool | 是否安装器模式（如 Miniconda 走 `.exe` / `.sh` 静默安装） |
| `multi_version` | bool | 是否允许并存多个版本并切换「生效版本」。**只有 7 个组件为 True**：jdk / python / node / go / maven / gradle / bun（真源 `MULTI_VERSION_KEYS`，`main.py:2916`）。**不在 `Component(...)` 构造处手写**：`build_components()` 末尾统一执行 `comp.multi_version = comp.key in MULTI_VERSION_KEYS`（`main.py:3409`），不在白名单就是 False。它是所有多版本分支的唯一门控（状态胶囊、绿勾、按钮启用、卸载范围），非多版本组件的行为与文案必须与改造前逐字一致（见 DEVELOPMENT.md R3.9） |
| `installer_args` | Dict[str, List[str]] | 按操作系统键取的安装器静默参数 |
| `unsupported_platform_hint` | Optional[str] | 平台不支持自动下载时的友好提示文本（如 Docker 在 Windows 提示用 Docker Desktop；为 None 表示该平台支持） |
| `category` | str | 界面 Tab 分组名，取值限于 `COMPONENT_CATEGORIES`（开发环境 / 开发软件 / 开发工具 / 一键启停）。**不在构造处手写**：`build_components()` 末尾统一赋值 —— 可启停组件按 `LAUNCH_KEYS` 派生成「一键启停」，其余按 `COMPONENT_CATEGORY_OF[comp.key]`，漏登记即 KeyError |

方法：
- `install_dir(version)` → 该版本的解压安装目录 `CONFIG_DIR/<key>/<key>-<version>`（`main.py:203`）；**这个 `<key>-<version>` 命名是多版本模型的唯一契约**，反解靠模块函数 `version_from_install_dir()`
- `exec_path_in_home(home)` → 在指定 `XXX_HOME` 下查找可执行文件，依次尝试 `path_subdir`/`bin`/`Scripts`/`condabin`/根目录；Windows 上按 `.exe`/`.bat`/`.cmd`/`.com`/无扩展名依次匹配（Tomcat 的 `catalina` 只有 `.bat`，只找 `.exe` 会漏检）
- `installed_dirs()` → 列出 `CONFIG_DIR/<key>` 下真实存在的安装目录（排除 `downloads` 缓存与 `.` 开头的解压临时目录，按目录名排序）
- `resolve_uninstall_target(version)` → 把下拉框选中的版本校正为磁盘上真正装着的目录，返回 `(目录, 中文说明)`（`main.py:293-338`）。次序：① 选中版本精确命中目录 → ② `XXX_HOME` 落在本组件根内则以它定位（说明"按 JAVA_HOME 定位到实际安装目录 …"）→ ③ 磁盘上只有一个目录就用它 → ④ **多版本组件**装了多个且前两条都没命中：按语义版本降序取最高的，并说明"已装 21、17，改为卸载版本最高的 21"；**非多版本组件**维持罢工（"存在多个已安装版本（…），请先在下拉框中选择具体版本"），目录名反解不出版本号时同样罢工并提示
- `uninstall(version)` → 卸载选中版本，返回中文摘要（各步以中文分号 `；` 连接）。四步：① `shutil.rmtree` 删**该版本**目录（安装器模式跳过）；② 只在 `XXX_HOME` 正指向被删目录时删它，指向同组件其它版本时保留、指向组件根之外时只报告"未删除"，指向组件根内已消失目录的死配置则清掉（`已清理指向不存在目录的环境变量：JAVA_HOME`）；③ PATH **默认只清理本次被删目录之下的条目**，只有本组件已无其它安装目录时才回到按组件根整体清扫（保住"手工删目录留下的死条目也能清掉"的自愈能力）；④ 多版本组件收尾：全删光则 `save_active_version(key, None)` 清登记；删掉的正是生效版本则自动 `apply_active_version` 到剩余里最高的（`生效版本已自动切到 …`）；生效版本还活着、只是被本次卸载带偏则按它重建（`已按生效版本 … 重建环境变量与 PATH`）。**生效版本在一切破坏性动作之前就以 `active_before` 快照取好**（`main.py:375`），因为老配置的生效版本靠 `XXX_HOME` 反推，而第 ② 步可能正好把那个 HOME 删掉
- `detect(probe_version=True)` → **核心探测逻辑**，返回 `DetectResult`；`exec_name` 为 None 的组件（如 Jenkins）走 `_detect_by_home_dir()` 兜底：只要 `XXX_HOME` 指向本工具安装目录即视为已配置。界面构建卡片时传 `probe_version=False`，只判定存在、不执行外部命令
- `exec_name` 在 Windows 上还会被 `shutil.which` 用 PATHEXT 匹配同名异扩展文件，因此 Nacos 必须写成带扩展名的 `startup.cmd`/`startup.sh`——写 `startup` 会命中 Tomcat 的 `startup.bat`，探测就变成了启动 Tomcat

模块级版本清单函数：
- `version_from_install_dir(comp, path)`（`main.py:513`）→ 从目录名反解版本号，不符合 `<key>-<version>` 约定（`downloads`、残缺名）返回 None；用 `comp.key` 做前缀判定，避免把 `python-3.12` 算到 jdk 头上
- `installed_versions(comp)`（`main.py:529`）→ 磁盘上真实装着的版本 `[(版本号, 目录)]`，**按语义版本降序**（走 `_sort_semver_desc`，字典序会得到 `jdk-8 > jdk-21` 的错序）。"已装"绿勾、状态胶囊清单、卸载后自动切最高版本都以它的输出为准

#### `DetectResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `installed` | bool | 是否已可用 |
| `source` | str | `"JAVA_HOME"` / `"PATH"` / `""` |
| `home` | str | 探测到的家目录 |
| `exe_path` | str | 探测到的可执行文件绝对路径 |
| `version_text` | str | 调用 `-version` 抓到的版本号文本（截断到 80 字符） |

### 4.3 URL 构造器（`_xxx_urls` 函数族）

每个组件对应一个 URL 构造函数，输入版本号、输出按操作系统键映射的 **URL 列表字典**（R1 多源故障转移）。

> 返回类型：旧版 `Dict[str, str]`（单 URL）→ R1 新版 `Dict[str, List[str]]`（URL 列表，国内镜像在前 + 末位官网）。`build_components()` 用 `url_list_map=_xxx_urls(v)` 传给 `ComponentVersion`。

| 函数 | 适用组件 | 关键逻辑 |
|------|---------|---------|
| `_adoptium_jdk_url(version, dead, avail)` | JDK | 离线默认清单无镜像，末位 `api.adoptium.net/v3/binary/latest/<major>/ga/…` 单源；点「刷新版本」后由 `_adoptium_mirror_urls()` 列清华 `/Adoptium/<major>/jdk/<arch>/<os>/`、南大 `/adoptium/…` 目录，挑带 build 号的确切文件名（镜像目录只暴露这种命名）；`dead`/`avail` 为本次刷新内的镜像熔断与目录缓存 |
| `_maven_urls(v)` | Maven | 华为 repo / 清华 / 阿里 / 南大 / 北外 / 腾讯 / 中科大 七家 `/apache/maven/maven-3/<v>/binaries/` + 末位 `archive.apache.org`（共 8 源） |
| `_tomcat_urls(v)` | Tomcat | 按主版本号 `v.split(".", 1)[0]` 拼接 tomcat-<major> 路径；华为 / 清华 / 阿里 / 南大 / 北外 / 腾讯 / 中科大 七家镜像 `/apache/tomcat/tomcat-<major>/v<v>/bin/` + 末位归档官网（共 8 源） |
| `_nginx_urls(v)` | Nginx | **只返回 `Windows` 一个键**（共 3 源）：`mirrors.huaweicloud.com/nginx/nginx-<v>.zip` + `repo.huaweicloud.com/nginx/…` + 末位 `nginx.org/download/…`（实测 2026-09-28：清华 / 北外 / 南大 / 阿里 / 腾讯对同一文件名一律 404，它们的 `nginx/` 目录是 apt/yum 包仓库，没有 nginx.org 那套 zip）；Linux/Darwin **不给 URL**——上游只发源码 `.tar.gz`（要自己 configure + make），改由 `unsupported_platform_hint` 引导 apt/dnf/yum/brew |
| `_mysql_urls(v)` | MySQL | Windows/Linux/macOS 三平台都有阿里 `/mysql/MySQL-<maj.min>/` + 华为 `/mysql/Downloads/MySQL-<maj.min>/` 两家镜像，末位 `cdn.mysql.com`（`dev.mysql.com/get` 对任何 UA 都 403，不能用）；Windows `mysql-<v>-winx64.zip`，Linux 走 `.tar.xz`（镜像站文件名是 glibc2.12，官网新包是 glibc2.28），macOS 用 `macos11`/`macos12` 命名走镜像、`macos14` 走 CDN（老版本 CDN 恒 404），按 `IS_ARM` 选 arch |
| `_python_urls(v)` | Python | 华为 `mirrors.huaweicloud.com/python/` + npmmirror `-/binary/python/` + 末位 `python.org/ftp`；Windows 走 embed-amd64.zip，mac/Linux 走 .tgz |
| `_node_urls(v)` | Node.js | 清华 / 南大 / 北外 `/nodejs-release/v<v>/` + 华为 `/nodejs/v<v>/` + npmmirror `-/binary/node/v<v>/` + 末位 `nodejs.org/dist`（共 6 源）；按 `IS_ARM` 选择 macOS arm64/x64 包 |
| `_git_urls(v)` | Git | **只返回 `Windows` 一个键**（共 7 源）：华为 `mirrors.huaweicloud.com/git-for-windows/<v>.windows.1/`、`repo.huaweicloud.com` 同路径 + npmmirror `-/binary/git-for-windows/…` 的 `MinGit-<v>-64-bit.zip`（三家实测 200），加速器只是补充（`_gh_accelerated()`），末位 `github.com/git-for-windows`；Linux/Darwin **不给 URL**——上游只有 `git/git` 源码 tar.gz（解压后无可执行文件，需自行编译），改由 `unsupported_platform_hint` 引导 apt/dnf/yum/brew |
| `_conda_urls(v)` | Miniconda | 清华 / 南大 / 北外 / 中科大 `/anaconda/miniconda/` + 末位 `repo.anaconda.com`（华为 `repo.huaweicloud.com/anaconda/` 对任意路径 301 到软 404 HTML 页，属假成功，已删除）；按 `IS_ARM` 选择 macOS arm64/x86_64 .sh |
| `_pwsh_urls(v)` | PowerShell 7 | 三平台都有官方便携包，上游只在 GitHub Releases 发版、国内无真镜像（清华 / 南大 / npmmirror 的 `powershell` 目录一律 404），故与 RabbitMQ 同策：`_gh_accelerated()` 三个加速器在前、`github.com/PowerShell/PowerShell/releases/download/v<v>/` 末位（每平台 4 源）；资产名大小写不统一——Windows 是 `PowerShell-<v>-win-<arch>.zip`，Linux/macOS 是 `powershell-<v>-linux/osx-<arch>.tar.gz`，按 `IS_ARM` 选 x64/arm64 |
| `_go_urls(v)` | Go | 只剩阿里 `/golang/` + 南大 `/golang/` 两家镜像 + 末位 `go.dev/dl/`（华为/清华对 `go<ver>.linux-amd64.tar.gz` 这类包名恒 404；中科大只是 302 跳回 `dl.google.com`，本机 TLS 失败，同样不算镜像） |
| `_gradle_urls(v)` | Gradle | 华为 repo / 华为 mirrors / 南大 / 腾讯 四家 `/gradle/<v>/gradle-<v>-bin.zip` + 末位 `services.gradle.org/distributions/`（清华/阿里/北外无 gradle 目录，实测 404 已删除） |
| `_bun_urls(v)` | Bun | npmmirror `-/binary/bun/` 在前 + `_gh_accelerated()` 的三个 GitHub 加速器与裸地址末位 |
| `_docker_urls(v)` | Docker | Linux 与 macOS 各八家 docker-ce 镜像（华为 repo / 华为 mirrors / 清华 / 阿里 / 南大 / 北外 / 中科大 / 腾讯）`/docker-ce/linux/static/stable/x86_64/`（或 aarch64）、`/docker-ce/mac/static/stable/<arch>/` + 末位 `download.docker.com`（各 9 源）；Windows 返回空（unsupported_platform_hint 引导装 Docker Desktop） |
| `_mongodb_urls(v)` | MongoDB | 仅 Windows/Linux，macOS 不支持；实测无国内镜像（带 UA 后 `repo.huaweicloud.com/mongodb/` 对二进制包名 404、只有 C++ 源码包，`mirrors.huaweicloud.com/mongodb.org/` 401；清华 `/mongodb/` 是 apt/yum 仓库；阿里只有 `mongodb-upstart/`），官网 `fastdl.mongodb.org` 单源；Linux 文件名必须带发行版段 `mongodb-linux-x86_64-ubuntu2204-<v>.tgz` |
| `_postgresql_urls(v)` | PostgreSQL | 仅 Windows；Linux/Darwin 不支持（提示用发行版包管理器 / brew）。实测无国内镜像（清华 404；华为/阿里/南大 `/postgresql/` 只有 `latest/`、`source/` 源码 tarball，`v17/`、`17.6/` binaries 树 404），官网 `get.enterprisedb.com/postgresql/postgresql-<v>-1-windows-x64-binaries.zip` 单源 |
| `_kubectl_urls(v)` | kubectl | 首位 DaoCloud `files.m.daocloud.io/dl.k8s.io/release/v<v>/bin/<os>/<arch>/kubectl`（实测 200 真二进制；`dl.k8s` 不是可改写前缀，必须走 files 代理）+ 末位 `dl.k8s.io/release/…`（共 2 源，已不是单源例外）；Windows .exe / Linux-Mac 无扩展名单二进制 |
| `_jenkins_urls(v)` | Jenkins | 华为 repo / 华为 mirrors / 清华 / 北外 / 南大 / 阿里 / 腾讯 / 中科大 八家 `/jenkins/war-stable/<v>/jenkins.war` + 末位 `get.jenkins.io`（共 9 源；镜像只保留最近几条 LTS 线）；三平台都是 jenkins.war 单文件 |
| `_rabbitmq_urls(v)` | RabbitMQ | 仅 Linux/Darwin（tar.xz）：华为 repo / 华为 mirrors `/rabbitmq-server/v<v>/rabbitmq-server-generic-unix-<v>.tar.xz` + 三个加速器 + 末位 `github.com/rabbitmq/rabbitmq-server/releases`（共 6 源）；Windows 无（依赖 Erlang，unsupported_platform_hint 引导官网安装器） |
| `_kafka_urls(v)` | Kafka | 华为 / 清华 / 阿里 / 南大 / 北外 / 腾讯 / 中科大 七家 `/apache/kafka/<v>/kafka_2.13-<v>.tgz` + 末位归档官网（共 8 源；Kafka 只发 .tgz，包名带 Scala 版本段 `kafka_2.13-<v>.tgz`，`-bin.zip` 实测 404） |
| `_rocketmq_urls(v)` | RocketMQ | 七家镜像 `/apache/rocketmq/<v>/rocketmq-all-<v>-bin-release.zip` + 末位归档官网（共 8 源） |
| `_pulsar_urls(v)` | Pulsar | 七家镜像 `/apache/pulsar/pulsar-<v>/apache-pulsar-<v>-bin.tar.gz` + 末位归档官网（共 8 源） |
| `_activemq_urls(v)` | ActiveMQ | 七家镜像 + 末位归档官网（共 8 源）；Apache 目录段是裸版本号 `/apache/activemq/<v>/`（不是 `activemq-<major>`），文件名前缀 `apache-activemq-`；Windows zip、Unix tar.gz |
| `_nacos_urls(v)` | Nacos | GitHub Release 无真镜像 → `_gh_accelerated()`（三加速器 + 裸地址末位，共 4 源） |
| `_seata_urls(v)` | Seata | 走 Apache 分发目录：华为 repo / 华为 mirrors / 清华 / 阿里 / 南大 / 北外 / 腾讯 / 中科大 八家 `/apache/incubator/seata/<v>/apache-seata-<v>-incubating-bin.tar.gz` + 末位 `archive.apache.org/dist/incubator/seata/`（共 9 源）；**不再**走 GitHub `_gh_accelerated()`——GitHub release 里的 `seata-server-<v>.jar` 只是 thin jar，不能解压即用；2.x 用 incubating 命名，1.x 用 `seata-server-<v>.zip` |
| `_elasticsearch_urls(v)` | Elasticsearch | 华为 repo + 华为 mirrors 两家镜像 `/elasticsearch/<v>/elasticsearch-<v>-<os>-<arch>.<ext>` + 末位 `artifacts.elastic.co`（共 3 源；清华/阿里无此制品，镜像只同步新版本，老版本 404 由故障转移兜底） |

辅助：
- `_STD_ARCHIVE`：标准归档类型表 `{"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"}`
- `_cv(version, url_map, archive_map=None)`：快速构造 `ComponentVersion`，默认用 `_STD_ARCHIVE` 归档表；第三个参数**覆盖**默认表——包体真实后缀不是 zip/tar.gz 时必须显式传，目前 MySQL Linux=`tar.xz`、RabbitMQ=`tar.xz`、Seata/Kafka=`tar.gz`、PostgreSQL Windows=`zip` 都靠它；**按值类型自动选模式**——值里含列表就填 `url_list_map`（R1 多源），值全是字符串就填旧的单 URL `url_map`
- `_adoptium_dirs()` / `_adoptium_pick()` / `_adoptium_mirror_urls()`：JDK 镜像目录列名与文件名挑选（镜像只暴露带 build 号的确切文件名）

### 4.4 版本抓取器（`FETCHERS` 字典）

每个组件对应一个 `fetch_xxx_versions()` 函数，启动时由后台线程并发调用，向各官网 API / 归档索引拉取真实可用版本列表。**首批 8 个组件的索引页直连官方**：镜像索引页只同步最近几个版本（实测清华的 Apache Maven 索引只返回 1 个版本，官网返回 45 个），镜像优先会把下拉框砍短，详见 [DEVELOPMENT.md](./DEVELOPMENT.md) R1.7 第 4 节。后加的 16 个组件里 `_fetch_apache_versions()` / `fetch_go_versions()` 等仍是「镜像索引 → 官网索引」取第一个非空，属已知偏差。下载 URL 与索引页是两件事：只有下载 URL 走 R1 多源。

| 函数 | 数据源 | 抓取方式 |
|------|--------|---------|
| `fetch_jdk_versions()` | `api.adoptium.net/v3/info/available_releases` | JSON，合并 `available_releases` 与 `available_lts_releases`，给 LTS 版本打 `display_label` |
| `fetch_maven_versions()` | `archive.apache.org/dist/maven/maven-3/` | HTML，正则 `href="(3\.\d+\.\d+)/"` |
| `fetch_tomcat_versions()` | `archive.apache.org/dist/tomcat/tomcat-{11,10,9}/` | HTML，正则逐主版本扫描 |
| `fetch_nginx_versions()` | 华为云 `mirrors.huaweicloud.com/nginx/` → `repo.huaweicloud.com/nginx/` → `nginx.org/download/` | HTML，正则 `nginx-(\d+\.\d+\.\d+)\.zip`（镜像目录页与官网同源同命名），取前 12 个版本；镜像优先只为「取版本号」这一步，实际下载仍按 `_nginx_urls()` 的链走 |
| `fetch_powershell_versions()` | `api.github.com/repos/PowerShell/PowerShell/releases?per_page=60` | JSON，取 `tag_name` 去掉前缀 `v`，只留 `[7-9].x.y` 三段式正式版（自动排除 `-preview` / `-rc` / daily-build），取前 12 个 |
| `fetch_python_versions()` | `python.org/ftp/python/` | HTML，只保留 3.6+ |
| `fetch_node_versions()` | `nodejs.org/dist/index.json` | JSON，每个 minor 保留最新 patch，major 10+，标注 LTS |
| `fetch_mysql_versions()` | `downloads.mysql.com/archives/community/` | HTML（无公开 API）；失败则用硬编码保底清单 |
| `fetch_git_versions()` | `api.github.com/repos/git-for-windows/git/releases` | JSON，解析 tag `v2.45.2.windows.1` 取版本号，仅保留前 15 个 |
| `fetch_conda_versions()` | `repo.anaconda.com/miniconda/` | HTML，正则匹配 `Miniconda3-(py\d+_[\d.\-]+)-` |
| `fetch_go_versions()` | `go.dev/dl/?mode=json` | JSON，按 `version`、`stable` 字段过滤 |
| `fetch_gradle_versions()` | `services.gradle.org/versions/all` | JSON |
| `fetch_bun_versions()` | GitHub Releases `oven-sh/bun` | JSON tag |
| `fetch_docker_versions()` | GitHub Releases `docker/cli` 或 `moby/moby` | JSON tag |
| `fetch_mongodb_versions()` | MongoDB 下载中心索引 | HTML / JSON |
| `fetch_postgresql_versions()` | PostgreSQL 源码归档索引 | HTML |
| `fetch_kubectl_versions()` | `dl.k8s.io/release/stable.txt` + 历史 | 文本/HTML |
| `fetch_jenkins_versions()` | `get.jenkins.io/war-stable/` | HTML |
| `fetch_rabbitmq_versions()` | GitHub Releases `rabbitmq/rabbitmq-server` | 复用 `_fetch_github_releases_versions` |
| `fetch_kafka_versions()` | Apache 归档 | 复用 `_fetch_apache_versions("kafka")` |
| `fetch_rocketmq_versions()` | Apache 归档 | 复用 `_fetch_apache_versions("rocketmq")` |
| `fetch_pulsar_versions()` | Apache 归档 | 复用 `_fetch_apache_versions("pulsar")` |
| `fetch_activemq_versions()` | Apache 归档 | 复用 `_fetch_apache_versions("activemq")` |
| `fetch_nacos_versions()` | GitHub Releases `alibaba/nacos` | 复用 `_fetch_github_releases_versions` |
| `fetch_seata_versions()` | GitHub Releases `apache/incubator-seata` | 复用 `_fetch_github_releases_versions` |
| `fetch_elasticsearch_versions()` | `elastic.co/downloads/elasticsearch` 索引 | HTML/JSON |

通用辅助：
- `_sort_semver_desc(vs)`：按语义化版本倒序排序（解析失败返回 `(0,)` 兜底）
- `_fetch_github_releases_versions(repo, prefix="v")`：**R1 公共辅助**：抓取 GitHub Releases 版本列表（Nacos / Seata / RabbitMQ / Bun / Docker 复用），先走国内镜像索引，失败切 `api.github.com`
- `_fetch_apache_versions(key)`：**R1 公共辅助**：抓取 Apache 项目版本列表（Kafka / RocketMQ / Pulsar / ActiveMQ 复用），先走国内镜像归档目录，失败切 Apache 官网

调度表：
```python
FETCHERS: Dict[str, Callable[[], List[ComponentVersion]]] = {
    "jdk": fetch_jdk_versions,
    "maven": fetch_maven_versions,
    "tomcat": fetch_tomcat_versions,
    "nginx": fetch_nginx_versions,
    "powershell": fetch_powershell_versions,
    "python": fetch_python_versions,
    "node": fetch_node_versions,
    "mysql": fetch_mysql_versions,
    "git": fetch_git_versions,
    "conda": fetch_conda_versions,
    "go": fetch_go_versions,
    "gradle": fetch_gradle_versions,
    "bun": fetch_bun_versions,
    "docker": fetch_docker_versions,
    "mongodb": fetch_mongodb_versions,
    "postgresql": fetch_postgresql_versions,
    "kubectl": fetch_kubectl_versions,
    "jenkins": fetch_jenkins_versions,
    "rabbitmq": fetch_rabbitmq_versions,
    "kafka": fetch_kafka_versions,
    "rocketmq": fetch_rocketmq_versions,
    "pulsar": fetch_pulsar_versions,
    "activemq": fetch_activemq_versions,
    "nacos": fetch_nacos_versions,
    "seata": fetch_seata_versions,
    "elasticsearch": fetch_elasticsearch_versions,
}
```

### 4.5 线程层

#### `VersionFetchWorker(QThread)`

后台执行版本抓取器，避免阻塞 UI。

| 信号 | 类型 | 说明 |
|------|------|------|
| `done` | `(str, object)` | `(component_key, versions or None)`，失败时 versions 为 None |

构造参数：
- `key`：组件标识
- `fetcher`：对应 `FETCHERS[key]` 可调用对象

`run()` 内捕获所有异常，失败时打印日志并发射 `done(key, None)`，让调用方降级到默认列表。

#### `VersionProbeWorker(QThread)`

后台执行一次 `_probe_version(exe, args)`，把「跑外部命令取版本号」从 UI 线程挪走：任何命令卡住（等 stdin、被安全软件拦截）都不会让主窗口打不开。

| 信号 | 类型 | 说明 |
|------|------|------|
| `done` | `(str,)` | 版本号文本，取不到为空串 |

`ComponentCard` 构建时只做 `detect(probe_version=False)`（不执行任何命令），随后用 `QTimer.singleShot(0, ...)` 延后启动本线程，回填后用 `_render_status_label()` 重写状态胶囊；若期间状态已被重新探测成「未安装」，晚到的结果会被丢弃，不会把标签刷回绿色。

#### `DownloadWorker(QThread)`

R1 多源故障转移下载线程（详见 [DEVELOPMENT.md](./DEVELOPMENT.md) R1.4）。按 `urls` 列表顺序依次尝试下载，第一个成功的写入目标文件；单 URL 失败自动切换到下一个，所有源失败才判定为彻底失败。全程中文日志输出。

| 信号 | 类型 | 说明 |
|------|------|------|
| `progress` | `(int, int)` | `(downloaded_bytes, total_bytes)`，total 为 0 表示未知大小 |
| `log` | `(str, str)` | `(level, message)`，level ∈ {info, warn, error, ok}，全部中文 |
| `finished_ok` | `(str,)` | 下载成功，参数为本地文件绝对路径 |
| `finished_fail` | `(str,)` | 下载失败或被取消，参数为错误信息 |

构造参数：
- `urls`：按 R1 优先级排序的 URL **列表**（国内镜像在前，官网末位）
- `dest`：目标文件 `Path`（实际先写到 `.part` 临时文件，成功后 `replace`）

关键行为：
- `run()` 遍历 `self.urls`：`log.emit("info", f"开始下载（第 {idx}/{len(urls)} 个源）：{url}")`
- `_try_download(url)` 单源下载：`requests.get(stream=True, timeout=DOWNLOAD_TIMEOUT, headers=HTTP_UA)`，请求头固定 `HTTP_UA`（实测清华 TUNA / BFSU 对 requests 默认 UA 与浏览器 UA 回 403，只放行自定义 UA），按 `_CHUNK_SIZE=64KB` 写 `.part` 临时文件，成功后 `replace` 为 `dest`
- 下载完成校验实际字节数：小于 `DOWNLOAD_MIN_VALID_BYTES`（4096）或短于声明的 `Content-Length` 判该源无效，删掉 `.part` 换下一个源（起因：华为 `repo.huaweicloud.com/anaconda/` 301 到软 404 HTML 页、`mirrors.huaweicloud.com/mongodb.org/…` 对缺失文件回空体 200，都是假成功）
- 单源失败：`log.emit("warn", f"第 {idx} 个源下载失败：{exc}\n即将切换到下一个源：{urls[idx]}")`，继续下一个
- 所有源失败：汇总失败原因 + `finished_fail.emit("所有下载源均不可用")`
- `cancel()` 设置 `_cancel` 标志，`_try_download` 在每个 chunk 写入前检查并中断，清理 `.part` 临时文件
- 镜像源 404 等不可恢复错误**不内部重试**，直接切下一个 URL（避免浪费时间）

#### `LaunchWorker(QThread)`

一键启动 / 停止的耗时动作（有界探活最长到 `startup_timeout` 秒，绝不能放 UI 线程）。信号风格照 `DownloadWorker`（`main.py:3644`）：

| 信号 | 类型 | 说明 |
|------|------|------|
| `started_ok` | `(str, str)` | `(key, console_url)`，启动成功且端口已在听 |
| `failed` | `(str, str)` | `(key, reason)`，门控/端口/拉起/超时/取消等失败，原因可行动 |
| `stopped` | `(str)` | `key`，已停止并释放端口 |
| `need_force` | `(str, str)` | `(key, reason)`：一次"要不要强制结束"的**询问**，不是错误。刻意做成独立信号，免得控制标记混进给用户看的正文 |

关键行为：
- `run()` 兜 `LaunchCancelled`（取消只是停止"等"，进程在不在没人知道，文案据此说清）与所有 `Exception`（转 `failed`，不发空信号让卡片停在"进行中"）
- `_dispatch()` 认不出的 action 也发 `failed` 出声
- `cancel()` 由 `_sleep` 在 ServiceManager 每轮等待时检查——有界探活是唯一长耗时阶段，sleeper 本就是注入点，无需新参数即可中止
- worker 以 `parent=self` 交卡片 Qt 对象树持有，`need_force` 换岗时两条线程短暂共存也不会把在跑的 worker 就地销毁

### 4.6 业务逻辑层

#### `EnvManager`（静态工具类）

跨平台环境变量管理器，所有方法均为 `@staticmethod`。

| 方法 | 平台 | 说明 |
|------|------|------|
| `get(name)` | 全平台 | 从 `os.environ` 读取，返回 `Optional[str]` |
| `is_valid_home(path, exec_name)` | 全平台 | 校验 `XXX_HOME/bin/<exec>` 是否存在 |
| `set_windows_user_env(name, value)` | Windows | 写 `HKCU\Environment`（含 `%` 用 `REG_EXPAND_SZ`，否则 `REG_SZ`）后广播刷新；`name` 为 `Path` 时只写注册表并直接返回——进程 PATH 是「机器段 + 用户段」合并的结果，整体覆盖会丢掉 `System32` 等机器条目 |
| `append_windows_path(entry)` | Windows | 读用户 PATH 去重追加（比较前展开 `%VAR%`、忽略大小写），并把该条目补进当前进程 PATH |
| `_broadcast_env_change()` | Windows | `PostMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, "Environment")` 异步通知。不用 `setx`（会把超过 1024 字符的 PATH 截断，且它本身要靠 PATH 查找），也不用同步的 `SendMessageTimeout`（遇到不处理消息的顶层窗口会卡住调用方） |
| `_write_registry_env(name, value)` | Windows | 只写注册表 + 广播，不动当前进程环境（PATH 条目增删的底层出口） |
| `remove_windows_user_env(name)` / `remove_unix_env(name)` | 对应平台 | 卸载用：删注册表值 / 删 `export` 标记块，并同步从 `os.environ` 移除 |
| `remove_windows_path_entry(entry)` / `remove_unix_path_entry(entry)` | 对应平台 | 卸载用：按单条目精确移除（注册表 + 当前进程 PATH 同步） |
| `remove_windows_path_entries_under(root)` / `remove_unix_path_entries_under(root)` | 对应平台 | 卸载用：清掉所有落在组件安装目录内的 PATH 条目，包括目录已被手工删除的历史残留 |
| `_norm_path` / `_same_path` / `_under_root` | 全平台 | PATH 条目比较工具：展开变量、归一化分隔符，Windows 下再忽略大小写 |
| `_shell_rc_file()` | UNIX | 按 `SHELL` 环境变量挑选 `.zshrc` / `.bash_profile` / `.bashrc` / `.profile` |
| `set_unix_env(name, value)` | UNIX | 用 `# >>> byte-tools:<name> >>>` / `# <<< ... <<<` 标记包裹 `export` 语句，幂等更新；返回被修改的文件路径 |
| `append_unix_path(entry)` | UNIX | 同上，但用 `entry` 作 key 防止重复追加 |

**平台无关门面（`EnvManager` 类内最后一段，共 8 个 public 方法）**：切换生效版本的代码只调这一组，业务层不再各自判断 `CURRENT_OS`。读接口读的是**持久层**（注册表 / shell rc）而不是 `os.environ`——后者会被本工具自己改脏，不能当"改动前状态"（回滚依据）。

| 门面方法 | Windows 分支 | UNIX 分支 | 说明 |
|---------|-------------|-----------|------|
| `write_user_env(name, value)` | `set_windows_user_env` | `set_unix_env` | 写 `XXX_HOME` |
| `drop_user_env(name)` | `remove_windows_user_env` | `remove_unix_env` | 删 `XXX_HOME` |
| `read_user_env(name)` | `_read_windows_user_env`（读 HKCU） | 解析 rc 里的 marker 块 | 读持久层的变量值，无则 None |
| `add_path_entry(entry)` | `append_windows_path` | `append_unix_path` | 追加一条 PATH |
| `drop_path_entry(entry)` | `remove_windows_path_entry` | `remove_unix_path_entry` | 精确删一条 PATH |
| `remove_path_entries_under(root)` | `remove_windows_path_entries_under` | `remove_unix_path_entries_under` | 清掉落在 `root` 之下的全部 PATH 条目（含目录已不存在的历史残留），**返回被删条目列表**——切换时它就是回滚快照 |
| `read_user_path_entries()` | `_read_windows_user_path` | 扫 rc 里的 PATH marker | 读持久层 PATH 条目；UNIX 侧只能看到本工具用 marker 写过的那些 |
| `restore_path_entries(entries)` | 整表写入 `_write_registry_env("Path", …)` | 逐条 `append_unix_path` | 切换失败回滚专用。**刻意不循环调 `add_path_entry`**：触发回滚时那条码往往正是刚失败的那条路，改用"清表那一步刚验证可用"的整表写入 |

另有两处只为测试留的读写接缝（不是门面，产品逻辑不直接调）：`_read_windows_user_env`（读侧）与 `_delete_windows_user_env`（写侧）——不打桩的话回滚用例会真删用户 `HKCU` 里的值。

#### 多版本与生效版本切换（业务层函数）

| 名称 | 位置 | 职责 |
|------|------|------|
| `MULTI_VERSION_KEYS` | `main.py:2916` | 允许并存多版本的 7 个组件白名单（唯一真源，`build_components()` 末尾据此写 `comp.multi_version`） |
| `SwitchError` | `EnvManager` 之后 | 切换失败的异常（`RuntimeError` 子类），抛出前已尽量回滚，文本里带"已回滚"或"回滚未完全成功"的明细 |
| `apply_active_version(comp, version)` | `SwitchError` 之后 | **生效版本切换的唯一入口**，见下方时序 |
| `load_active_map()` | `apply_active_version` 之后 | 读 `config.json` 的 `active` 段（`{组件 key: 生效版本号}`）；文件缺失 / JSON 损坏 / 结构不对一律当空表，绝不抛错 |
| `save_active_version(key, version)` | `load_active_map` 之后 | 登记 / 清除（传 `None`）某组件的生效版本；**合并写**：先读原文件只改 `active` 里那一项，整体覆盖会抹掉 `selections`；损坏文件重建 |
| `infer_active_from_env(comp)` | `save_active_version` 之后 | 老配置没有 `active` 条目时，从持久层 `XXX_HOME` 反推生效版本。要求 HOME 指向的目录**真实存在**（否则返回 None，避免"目录已删、HOME 没清"的死配置撑起一个幽灵生效版本）、且落在 `CONFIG_DIR/<key>` 之内，再交给 `version_from_install_dir` 反解；推不出就 None，界面写"均未生效" |
| `ComponentCard.active_version()` | `ComponentCard` 内 | 界面上的生效版本：`load_active_map().get(key) or infer_active_from_env(comp)`；非多版本组件直接 None |

> 这一批函数的行号会随改动漂移，以函数名检索为准（同 5.4 的约定）。

`apply_active_version()` 的时序与回滚语义：

```
apply_active_version(comp, version)
  ├─ target = comp.install_dir(version)；不存在则立即抛 SwitchError（此时什么都没改）
  ├─ 快照持久层：prev_home = read_user_env(comp.env_var)          # 不是 os.environ
  ├─ if comp.env_var: write_user_env(env_var, target)             # ① 写 XXX_HOME
  ├─ removed = remove_path_entries_under(CONFIG_DIR/<key>)        # ② 本组件 PATH 全收敛
  ├─ added_entries.append(bin_dir) → add_path_entry(bin_dir)      # ③ 只补生效版本那一条
  │     # 先记账再落盘：add_path_entry 可能"已写进持久层、随后才抛错"，
  │     # 漏记就会在 PATH 里留下两条同时生效的条目
  ├─ 任一步异常 → _rollback()：逆序撤销（删新增 → restore_path_entries(removed) → 恢复/删除 HOME）
  │     ├─ prev_home 为 None 时回滚的正确形态是 drop_user_env（写空值会让 detect 误判"已配置"）
  │     └─ 每步独立 try：宁可"半回滚"也不能让异常炸穿后面几步；
  │        撤不干净的明细拼进 SwitchError 文本，绝不允许只写一句"已回滚"
  └─ 成功：返回中文步骤清单，末行固定提示"当前进程已同步；已开着的终端与 IDE 需重开
     才会读到新值（Windows 若装了 Oracle javapath，个别命令仍可能被它抢先）"
```

调用方只有两处：`ComponentCard._apply_active()`（用户点「切换」，成功后才 `save_active_version`）
与 `Component.uninstall()` 第 ④ 步（删掉生效版本后自动重排 / 按生效版本重建）。

幂等机制：UNIX 系统下用 `marker_begin` / `marker_end` 包裹写入块，再次写入时只替换两标记之间的内容，不会重复堆积。

#### 组件一键启动（业务层，规则 R5）

生命周期层把"点启动 → 真能访问控制台"这件事做成一组**不含 Qt 对象、探针全可注入**的纯逻辑（行号会漂移，以函数名检索为准）：

| 名称 | 位置（约） | 职责 |
|------|-----------|------|
| `LaunchSpec` | `main.py:2985` | 一个组件"怎么被拉起来"的描述符：`commands`（按 OS 的 argv 模板，占位 `{java}/{war}/{home}/{data_dir}/{conf_dir}/{port}/{log_file}`）、`stop_kind`（`pid` / `shutdown_command` / `port_lookup`）、`main_port` / `port_offsets` / `extra_ports` / `port_search_span`、`port_writeback`（`cli_only` / `cli_flag` / `conf_copy`）、`extra_env`、`console_path` / `health_path`、`needs` / `min_java_major`、`data_dir_env`、`startup_timeout`、`risk_note` / `data_note` |
| `LAUNCH_OF` / `LAUNCH_KEYS` | `main.py:3034` / `:3116` | **唯一登记处**；`build_components()` 末尾 `comp.launch = LAUNCH_OF.get(comp.key)` 统一赋值，构造处不手写。当前为 `{jenkins, activemq, nacos}` |
| `pick_free_cluster(base, offsets, span, is_free)` | `main.py:4639` | 端口簇选择：从主端口起在 `[base, base+span]` 内**升序**找"整簇所有端口同时空闲"的最小主端口，找不到返回 `None`（不做跨段随机挑） |
| `parse_netstat_listeners(text)` | `main.py:4665` | 解析 Windows `netstat -ano` 输出 → `{端口: {PID, …}}`。容错：表头/空行/`IPv6`/`(netstat)` 后缀/`Foreign` 状态都跳过；只收 LISTENING |
| `netstat_listener_pids(ports)` | `main.py:4713` | 调一次 netstat 并只保留要的端口 → `{端口: 唯一 PID}`；同口多 PID（归属有歧义）时**不给结果**。**只在 `force_stop` 用**，检测路径绝不调它（`NoExecInvariant` 钉死） |
| `_pick_unique_pids(table, ports)` | `main.py:4706` | 从解析表里取"唯一且存在"的归属；长度 != 1 直接不返回 —— 宁可不杀，也不按进程名乱杀 |
| `prepare_conf_copy(src, dst)` | `main.py:4745` | 把官方 `conf` **整目录**拷到 `~/.env-tools/<key>-data/conf`。已有副本即权威：只回报"副本里缺的相对路径清单"，不自动合并、不覆盖 |
| `set_property_line(path, key, value)` | `main.py:4786` | 幂等改 `.properties` 的一行：首次改动留一次 `.bak`；已是目标值就不写文件。锚不到那一行 → 返回 `(False, 指名文件+行+手工改法)` |
| `set_openwire_port(path, port)` | `main.py:4810` | 只改 `activemq.xml` 里**带 `name="openwire"` 属性**的 `transportConnector`（该属性是锚点）；被注释掉或找不到同样拒改 |
| `conf_targets(data_dir)` | `main.py:4739` | ActiveMQ 的 conf 副本三件套路径：`conf/` 目录、`jetty-spring.properties`、`activemq.xml` |
| `choose_ports(spec, is_free)` | `main.py:4854` | 统一选端口：主口+派生口走 `pick_free_cluster` 整簇平移；独立口（`extra_ports`）各自从**自己的基准**另找。独立口找不到位 → 整次失败并指名是哪个口（半成功比不启动更坏） |
| `prepare_ports(comp, spec, plan, data_dir)` | `main.py:4876` | 端口回写闸门，返回 `(能否继续拉起, 失败原因, 提示行)`。`cli_only`/`cli_flag` 直接放行不碰文件；`conf_copy` 建副本 + 改两处端口。**回写必须在 spawn 之前完成**，失败必须阻止拉起 |
| `vendor_log_tails(data_dir, home, key)` | `main.py:4918` | 启动超时时把厂商自己的日志（`activemq.log` / `start.out`）尾巴并进 `reason`，按 `VENDOR_LOG_CANDIDATES` 表找而不是猜 |
| `resolve_java_home(comps)` | `main.py:5012` | `JAVA_HOME` **优先取本工具装的 JDK**，其次才退到环境变量；退到环境变量的值要校验目录真实存在 |
| `resolve_launch_version(comp)` | `main.py:5038` | 启动该用**哪个已安装版本**：生效版本（active 登记且目录真实存在）→ 已安装目录里版本号最高的。一个都没装返回 `None`（`launch_gate` 据此拦住并给出"先点下载并安装"的可行动提示）。**不看 `comp.versions[0]`** —— 离线候选清单会落后于实际安装版本，真机踩过：候选首位 2.568.3、实装 2.580.1，按候选首位去找会 `[WinError 267] 目录名称无效`，界面只显示"拉起失败" |
| `build_launch_plan(comp, spec, java_home, port, log_file)` | `main.py:5042` | 展开 argv、注入 env（`JAVA_HOME` + `data_dir_env` + `extra_env`，值支持 `{home}/{data_dir}/{conf_dir}/{port}`）、拼 `console_url`；`java_home` 一律是 JDK 安装目录（home），不是 exe |
| `load_running_map()` / `save_running_map()` | `main.py:4578` / `:4623` | `~/.env-tools/running.json`（本机进程事实，与 `config.json` 用户偏好分开）读写；坏 JSON / 缺文件一律当空表，字段畸形只丢该条记录；写盘走"临时文件 + `os.replace`"原子覆盖。`ports` 缺省 `()` 由**加载侧**归一为 `(port,)` —— 新字段没有默认值会让旧记录整批被静默丢弃 |
| `ServiceManager` | `main.py:5084` | 生命周期唯一入口：`status` / `adopt` / `reconcile`（只读 + 清僵尸，**绝不拉进程**）、`start`（门控 → `choose_ports` → `prepare_ports` 回写闸门 → 建 data 目录 → 重定向 stdout/stderr 到 `<data>/logs/byte-tools.out` → 有界轮次**整簇**探活 → 写登记）、`stop`（Windows 或 `port_lookup` 都只请示不自动强杀，超时 `need_force`）、`force_stop`（`pid_role=server` 才按登记 PID，否则按**端口反查**得到的唯一非自有 PID；**只在整簇端口确认释放后才清登记**）。探针 `is_listening`/`http_ok`/`process_alive`/`terminate`/`_lookup_pids` 全可注入 |

> 语义要点：**端口是真相、PID 只是尽力而为地停止**；`pid_role ∈ {server, launcher, none}`。`status/adopt/reconcile` 的
> "运行中"判定走整簇监听（`tuple(rec.ports) or (rec.port,)`）—— Nacos 主口在听、gRPC 9848 掉了是**半死**，
> 显示成运行中会让用户以为客户端连得上。端口反查是一次 netstat 调用，**只允许出现在 `force_stop`**。
> `SERVICE_MANAGER`（`main.py:5369`）是卡片与主窗共用的单实例，避免多张卡片各持一套 `running.json` 读写口径。

#### `extract_archive(archive, extract_to)`

归档解压器，支持多种形态：

- 压缩包：`.zip` / `.tar.gz` / `.tgz` / `.tar.xz`
- 单二进制文件（如 kubectl 无扩展名、`.exe` 单文件）：不解压，直接返回 `extract_to`，调用方负责 `chmod +x`（Linux/Mac）和重命名
- `.war` 文件（Jenkins）：单文件不解压，直接返回 `extract_to`，由后续逻辑重命名为 `jenkins.war`

行为：解压到 `extract_to`；若解压后只有一个子目录（典型场景），返回该子目录路径；否则返回 `extract_to` 自身。调用方据此 `shutil.move` 到 `install_dir`。

### 4.7 UI 层

#### `SearchableComboBox(QComboBox)`

支持关键字过滤的可编辑下拉框，是本项目 UI 的"招牌组件"。

交互设计：
- 点击输入框任意位置 → 弹出下拉列表（默认显示全部）
- 输入关键字 → 实时过滤（`MatchContains`，大小写不敏感）
- 点击某项或回车 → 选中
- 失焦时若输入不精确匹配任何项 → 回滚到上一次选中值（`_restore_if_invalid`）

实现要点：
- 用 `QLabel("▾")` 自定义下拉箭头，避免 CSS border-hack 渲染问题；设置 `WA_TransparentForMouseEvents` 让事件穿透到 QComboBox
- 在 `lineEdit()` 上 `installEventFilter(self)`，`MouseButtonPress` 阶段返回 `True` 吞掉事件，避免 QLineEdit 与 QComboBox 内部 toggle 逻辑打架
- `showPopup()` 展开前先按当前输入过滤
- `repopulate(items, preferred=None)` 清空重灌列表，尽量保留之前选中值

#### `ComponentCard(QFrame)`

单组件卡片，承载一个 `Component` 的完整 UI 与交互。

UI 组成（自上而下，四行 + 进度条；这么切是为了塞进 300px 的网格格子，见 `MainWindow` 的网格一节）：
1. **顶部行**：组件名 `QLabel` + 状态角标
2. **状态行**：状态胶囊 `status_label` + 运行状态胶囊 `launch_label`
3. **版本行**：版本下拉框 `SearchableComboBox`（多版本组件里磁盘已装的条目带 `_installed_icon()` 画的绿色对勾）
4. **按钮行**：「安装」「切换」「卸载」「取消」；**可启动组件（`component.launch is not None`）**再追加「启动」与「控制台」/「访问页」，不在登记表的组件这两颗根本不创建
5. **进度条**：`QProgressBar`

按钮文案是**瘦身过的**：`下载并安装→安装`、`配置环境变量/切换为生效版本→切换`、`打开控制台/打开访问页→控制台/访问页`。
改文案的同时把 `combo` 220→150、按钮高 34→30、QSS padding 18/16→8、卡片 margins 与 spacing 一并收紧，
否则按钮在 271px 的格子内必然换行，卡片高度会从 153 涨回 ~230，一屏反而更少。
**`启动`/`停止` 一个字都不能动**：`_running_per_ui()` 读这颗按钮的文字判断是否在运行。
`btn_console` 补了 `setObjectName("secondaryBtn")`——原先三条按钮 QSS 全都匹配不到它，它拿系统默认样式、
`sizeHint` 恒 80（同长度的「安装」只占 42），观感上比旁边宽一圈。

卡片实测高 153–155px（可启停组件 155，因为按钮行多两颗），同一行内由布局保证等高。

状态胶囊（`_detect_status` 设置，全程不执行外部命令；**多版本组件走另一套文案**）：

- 非多版本组件三态：
  - 🟢 `✓ 已配置（CATALINA_HOME / PATH）· <version>` — 系统已能找到，禁用「切换」按钮、启用"卸载"；版本号先显示 `版本检测中…`，由 `VersionProbeWorker` 异步回填，`version_probe=False` 的组件不显示版本
  - 🟠 `● 已下载，未配置` — 本地已解压但环境变量未设
  - 🔴 `○ 未安装` — 完全没有
- 多版本组件（`component.multi_version`，7 个）：**不**套用上面的 `✓ 已配置（…）`，而是"装了哪几个 + 哪个生效"（`_detect_status` 开头分支，正文存进 `self._mv_capsule`，`_render_status_label()` 只在末尾追加异步探测到的版本号）：
  - 🟢 `● 已装 2 个版本 · 生效 21（21、17）` — 清单分隔符是中文顿号 `、`，版本清单来自 `installed_versions()`（语义降序），生效来自 `active_version()`
  - 🟠 `● 已装 2 个版本 · 均未生效（21、17）` — 一个生效版本都没有
  - 🔴 `○ 未安装` — 磁盘上一个版本都没有
  - 🟢 探测回填后追加尾串：`● 已装 2 个版本 · 生效 21（21、17） · 21.0.4`
  - 同一分支还负责按钮门控：`btn_configure` 仅在"选中的版本 != 生效版本"时启用（tooltip 说明怎么换）；`btn_uninstall` 仅在"选中的版本确实已装"时启用（未装时 tooltip 提示先在下拉框里选带绿勾的）；一个版本都没装时 `btn_configure` 启用、`btn_uninstall` 禁用
  - 只对**生效版本**的目录起 `VersionProbeWorker` 回填版本号，并在重探测前清掉上一轮的 `_status_version` 与 `_version_worker`（否则切完版本胶囊还挂着旧版本号，迟到的旧回包也会污染新胶囊）

> **状态文案是"主文本写结论 + 全量原文进 tooltip"**：格子内部只有 271–309px，而完整状态文本需要
> 448–520px，PySide6 的 `QLabel` **没有** `setElideMode`（超宽是直接 clip，不是省略号），所以长文案只能这么切。
> 唯一写入口是 `_set_status(full, short)` / `_set_launch(full, short)`：**两者每次都要一起设置**，
> 只 `setText` 会把上一轮的详情留在悬停提示里，变成一句已经没有依据的旧话。
> `_mv_capsule` 继续存全量原文（tooltip 源 + 缓存），短串单独存 `_mv_capsule_short`，
> 免得异步版本回填把长文案弹回界面。

关键方法：
- `_set_status(full, short)` / `_set_launch(full, short)` — 状态行与运行状态胶囊的唯一写入口（短串进主文本、全量进 tooltip）
- `_schedule_version_probe(exe_path)` / `_start_version_probe(exe_path)` — `QTimer.singleShot(0, …)` 延后到事件循环空闲，再起 `VersionProbeWorker` 后台跑 `_probe_version`；`version_probe=False` 或 `version_args` 为空直接跳过
- `_on_version_probed(text)` — 回填版本并重绘胶囊；状态已不是"已配置"时丢弃结果，避免晚到的回包把卸载后的标签刷回绿色
- `set_versions(versions)` — 接收抓取线程返回的新版本列表，替换 `component.versions` 并刷新下拉框；保留上次选中版本（按 version 字段匹配）
- `on_install_clicked()` — 取出当前选中版本，决定下载文件后缀（安装器模式按 `archive_map` 取扩展名；普通模式按 `archive_for_current()` 决定 `.zip` / `.tar.gz` / `.war` / `""`单二进制），构造 `urls = cv.urls_for_current()` 启动 `DownloadWorker(urls, dest)`；下载→解压→自动配置环境变量→刷新状态一条龙流程
- `_on_download_ok(path, cv)` — 下载成功回调：安装器模式走 `_run_installer`；普通模式走 `extract_archive` + `shutil.move`；**单二进制 / `.war` 重命名逻辑**（kubectl-1.28.4.exe → kubectl.exe / kubectl-1.28.4 → kubectl / jenkins-2.426.war → jenkins.war）；最后自动调用 `_configure_env`。**只覆盖同版本目录**（`install_dir(cv.version)`），同组件其它版本的目录不动，所以装第二个版本就是多版本并存
- `_run_installer(installer_path, target_dir)` — 静默执行 Miniconda 等：Windows 拼 `/D=<path>`（不能带引号）；mac/Linux 用 `bash installer.sh -b -f -p <path>`
- `on_configure_clicked()` — 「切换」按钮（旧文案「配置环境变量 / 切换为生效版本」）。**多版本组件**：把下拉框选中的版本交给 `_apply_active()` 设为生效版本（选中版本没装、或该组件在磁盘上一个符合命名的目录都没有时，只写一条 warn 日志并返回）；**非多版本组件**：沿用原有行为——从 `installed_versions()` 取语义版本最高的那个目录调 `_configure_env`（改造前这里是"按目录名字典序取最后一个"，会把 `jdk-8` 当成最新，2026-09-29 起统一走 `_sort_semver_desc`）
- `active_version()` — 当前生效版本：`load_active_map().get(key)` 优先，取不到再 `infer_active_from_env(comp)` 从持久层 `XXX_HOME` 反推；非多版本组件恒为 None
- `_apply_active(version)` — 调 `apply_active_version()`，失败只把 `SwitchError` 文本打进日志并返回 False（不改登记表），成功则逐步写日志、`save_active_version(key, version)`、`_refresh_installed_marks()` + `_detect_status()`
- `_refresh_installed_marks()` — 给磁盘上已装的版本挂绿勾：`self.component.versions` 逐项 `setItemData(i, icon, Qt.DecorationRole)`，图标由 `_installed_icon()` 用 `QPainter` 现画（绿色 `#2e7d32`、16px、2 倍分辨率绘制）。**只动 `DecorationRole`，绝不改条目文本**；非多版本组件直接 return，连 `DecorationRole` 都不写（保持"从未挂过"的原始数据）。安装、卸载、切换生效、重灌条目（`_reload_combo_items` 的两条出口）之后都要重挂
- `on_uninstall_clicked()` — 二次确认（`QMessageBox.question`）后调 `component.uninstall(cv.version)`，把中文摘要打进日志，再 `_refresh_installed_marks()` + `_detect_status()`。确认框正文的尾巴按 `multi_version` 分叉：多版本组件是"（只删除选中的这一个版本，其他已装版本不动；若删掉的正是当前生效版本，会自动切到剩余里版本号最高的那个）"，非多版本组件保持原有那句"（若所选版本与实际安装版本不一致，会以实际装着的目录为准）"逐字不变
- `_configure_env(install_path)` — 写 `XXX_HOME` + 追加 PATH；Windows 用 `EnvManager.set_windows_user_env` + `append_windows_path`；UNIX 用 `set_unix_env` + `append_unix_path`
- `on_cancel_clicked()` — 调 `worker.cancel()`
- **一键启动相关**（判定全在 `ServiceManager`，卡片只做"读状态 → 摆按钮 → 把动作丢进线程"）：
  - `_launch_status()` / `_refresh_launch_state()` — 只读地按端口实况刷新按钮与 `launch_label`（运行中→启动置灰、停止/打开控制台启用、**卸载锁死**；zombie→显示残留登记但启动仍可点），全程一次都不拉起进程；`_uninstall_locked_by_launch` 只在"运行"这条边上解冻卸载，不无条件点亮
  - `on_start_clicked()` — 先弹确认（带 `spec.main_port` 与 `risk_note`），确认后起 `LaunchWorker("start", …, parent=self)`
  - `on_stop_clicked()` / `_on_need_force()` — 停止；`need_force` 触发时弹一次"要强制结束吗"，**用户确认才起 `force_stop` worker**（不自动强杀）
  - `on_console_clicked()` — `QDesktopServices.openUrl(登记的 console_url)`（用实际端口）
  - `_on_launch_worker_done()` — 按 `sender()` 身份收尾（老 worker 的 `finished` 晚于新 worker 起跑时不误清刚起的 force_stop worker 引用）+ `deleteLater()`

#### `DonateDialog(QDialog)`

打赏弹窗（代码内实现，不在 README 描述中）。

- `CHANNELS` 类常量声明三渠道：`("微信", "#07C160", "wechat.png")` 等三元组
- 渠道切换按钮 + 二维码展示 `QLabel`
- `_show_qr(channel, color, filename)` 加载 `assets/<filename>`，按 view 宽度等比缩放；加载失败显示占位文字

#### `MainWindow(QMainWindow)`

主窗口，无边框自定义标题栏。

UI 组成：
1. **窗口图标**：`setWindowIcon(QIcon("assets/byte-tools.png"))`，缺失时不报错（继续走默认 Qt 图标）
2. **标题栏**（固定高度 48）：应用名 + GitHub 按钮 + "⟳ 刷新版本"按钮 + "🧹 清理残留 PATH"按钮 + 打赏按钮 ♥ + 最小化 — / 最大化 ▢ / 关闭 ×
3. **搜索条**（标题栏与 Tab 之间，`objectName="searchBar"`）：外壳 `QFrame#searchShell` 里放放大镜 `QLabel#searchIcon` + `QLineEdit#compSearch`（透明无边框、自绘 × 清空按钮），右侧 `QLabel#searchHint` 实时显示"匹配 N / 36 个组件"（0 命中时转警示红）。`textChanged` → `MainWindow._apply_search()`；聚焦时整条外壳描蓝边（`MainWindow.eventFilter()` 转发焦点 → `_set_search_focus()` 改 `focused` 属性并重刷样式，QSS 的 `:focus` 管不到父级），放大镜同步变色。图标由 `_make_search_icon()` / `_make_clear_icon()` 用 QPainter 现画，不引入图片资源。**放在标题栏之外**，因为标题栏整条是窗口拖拽区（`mousePressEvent` 里 `title_bar.underMouse()` 会开始拖动），输入框塞进去就点不动了。
搜索条右侧还挂着「▦ 网格 / ☰ 列表」与「📋 日志」两颗按钮——**它们也不放标题栏**：标题栏已有 5 个按钮 + 3 个窗口控制，实测需要 ~992px，窗口才 1000 宽
4. **主体**：中部卡片区（`QWidget#bodyArea`，吃满中部）按 `COMPONENT_CATEGORIES` 分四个 Tab，Tab 外层
   `QTabWidget`（`objectName="compTabs"`，`setTabPosition(North)` 顶部横向），**标题带组件数量**：
   `开发环境（10）` / `开发软件（6）` / `开发工具（10）` / `一键启停（10）`（数字由 `len(comps)` 现算，不写死）；
   每个 Tab 内一条独立 `QScrollArea` 挂该分类的 `ComponentCard`。卡片在 Tab 里是**网格**：列数只由视口宽度决定
   （见下方「卡片网格」一节），不再是一行一张占满宽
   - **搜索过滤**由 `component_matches(comp, query)` 判定（显示名或 key 的子串，忽略大小写与首尾空白；空查询不过滤）：命中的 `card.setVisible(True)`，其余隐藏。搜索时 `QStackedWidget#topStack` 收起四个 Tab、切到统一结果页 `QScrollArea#resultsArea`，把所有命中组件**按分类归并到同一滚动列表**（每类前有 `QLabel#resultCatHeader` 小标题），清空后切回 Tab 浏览态、卡片各自归位。这是"全组件搜索、而非只搜单个 table"的呈现。过滤**只改可见性与归属**，`MainWindow.cards` 平铺列表始终是全量 36 项
5. **日志浮层**：`QWidget#logOverlay`（内含 `QTextEdit#logView`，深色主题），与卡片区同 parent、靠 `raise_()` 叠在上面，几何随 `resizeEvent` 跟随；默认收起，由搜索条上的「📋 日志」按钮 toggle。展开时**遮住**最下面一行格子，而不是把网格压扁（见下方「日志浮层」一节）
6. **底部状态栏**：显示当前系统信息、可点开的工作目录与 `组件：N`（N=26，界面可见数；只写数字不写句子，版本号在标题栏 chip 上不重复）

> **不变量**：`MainWindow.cards` 仍是**全量平铺**列表（26 张卡片，跨 Tab 收集），
> 刷新版本、读写配置、关窗前等探测线程都遍历它；分组只影响卡片的父布局，不影响这个列表。
> 分类数据由 `COMPONENT_CATEGORY_OF` 单点登记 → `build_components()` 末尾写入 `Component.category`
> → `group_components()` 按 `COMPONENT_CATEGORIES` 顺序出组；未登记的 key 会 KeyError，不会静默漏卡片。

#### 卡片网格（2026-10-08）

组件卡片从「一行一张占满宽」改成**按宽度重排的网格**，目的是让一屏看得见更多组件。

- **列数只由可用宽度算**：`grid_columns_for(available_px, MIN_CARD_WIDTH_PX)`，`MIN_CARD_WIDTH_PX = 300`
  （一张卡片信息不砍的下限），间距 `CARD_ROW_SPACING = 14`。窗口 1000 宽时视口净宽 954，实测出
  **3 列 × 3 行 = 9 个/屏**；窗口拉宽自动变更多列，拉窄回落到 1 列。非法入参（视口尚未生效时宽度为 0）
  一律兜底 1 列，不抛异常——除零或负列数会让整片卡片消失
- **实现是行容器法，不是 `QGridLayout`**：Tab 外层仍是 `QVBoxLayout`，里面装"行"，每行一个 `QHBoxLayout` 装 1..N 张卡
  （`_tab_layouts[i]` 的语义因此从"直接装卡片"改成"装行的外层竖向布局"，`_tab_rows[key]` 存行控件）。
  原因是 `_reparent` / `_restore_browse` / `_build_unified` 三处全靠 `QBoxLayout` 的 `indexOf` / `insertWidget` /
  末尾 stretch 工作，`QGridLayout` 没有这套语义
- **relayout 只排可见卡片**（`chunk_visible`）：`QBoxLayout` 会给隐藏控件留位，
  留着隐藏卡片等于"搜索命中 1 个时网格出现空洞"。判可见用 `isHidden()` 而不是 `isVisible()`——
  后者还要看父级，而卡片所在 Tab 页没被翻到时父级就是不可见的
- **`resizeEvent` 只在列数真的变化时才重建行**：resize 是每变一个像素一次的事件，每次都重建行控件会把拖动窗口卡死
- **视图切换**：搜索条上一颗 `▦ 网格 / ☰ 列表`，持久化到 `config.json` 的 `view_mode`，默认 `grid`；
  列表模式 = 强制 1 列，卡片内部一模一样。**按钮在搜索条上，不在标题栏**：标题栏已有 5 个按钮 + 3 个窗口控制，
  实测需要 ~992px，而窗口才 1000 宽，再加必然把已有按钮压到裁字

#### 日志浮层（2026-10-08）

日志原先和卡片区按 **3:2** 分在同一个 `QSplitter` 里，展开/收起都会挤压网格。现在卡片区独占中部，
日志改成浮在它上面的浮层：

- **为什么不改回挤压式**：浮层不在 `body` 的布局里，`show/hide` 不触发重排 ⇒ 列数与行数只由窗口宽度决定，
  开关日志不会让格子忽大忽小，也省掉"挤压式折叠"带来的二次 relayout。代价是展开时遮住最下面一行格子
- **只有 `warn` / `error` 才自动弹开**：下载/安装这类常规进度在卡片上已有进度条，每来一条都弹会把用户
  正在操作的那张卡盖住。未读条数挂在按钮文字里（`📋 日志 (N)`，不新增控件），
  **只在"弹开前是收起的"时才累加**；手动点开即清零且**不自动收起**（`_log_user_open`）；
  自动弹开的那个静默 `LOG_AUTO_HIDE_MS = 8000` 后自愈收起

无边框窗口拖动：
- `mousePressEvent` 在标题栏区域按下左键时记录 `_drag_pos`
- `mouseMoveEvent` 持续移动窗口
- `mouseDoubleClickEvent` 双击标题栏切换最大化

关键方法：
- `_on_cleanup_path_clicked()` — "清理残留 PATH"入口：先用 `find_dead_tool_path_entries()` 只读预览并弹确认框，确认后 `cleanup_dead_tool_path_entries()` 删除死条目、写日志并逐卡片 `_detect_status()` 刷新
- `_start_fetch_versions()` — 从各官网并发拉取版本列表。若仍有 worker 运行则提示；否则清理旧 worker，为每个有 fetcher 的卡片启动一个 `VersionFetchWorker`（并发，150ms 错峰），计数器 `_fetch_pending` 等所有完成后再恢复按钮
- `_on_versions_fetched(key, versions)` — 单个抓取完成回调，versions 为 None 时日志告警降级，否则调 `card.set_versions`
- `_append_log(level, msg)` — 彩色日志输出：info 灰 / ok 绿 / warn 橙 / error 红，用 `<span style="color:...">` 包裹塞进 `QTextEdit`；**只有 `warn`/`error` 会顺带自动弹开日志浮层并累加未读条数**
- `_card_columns()` — 当前该排几列（列表模式恒 1 列，网格模式按 `QScrollArea` **视口**净宽算，不是窗口宽度）
- `relayout_cards(container_key)` / `_fill_rows(...)` — 把一个容器里的卡片按当前列数重排成"行"；`container_key` 为 Tab 序号或 `RESULTS_KEY`（统一搜索结果面板，固定单列）
- `_set_log_open(open_)` / `_on_log_button_clicked()` / `_close_log_by_user()` — 浮层的开/关；**浮层的 show/hide 不触发 relayout**，这是"展开日志不重排网格"这条承诺的实现基础
- `_on_view_mode_clicked()` — 网格 ⇄ 列表，写完即 `_save_settings()` 落盘
- `_load_settings()` / `_save_settings()` — 启动时从 `CONFIG_FILE` 加载上次选中版本；`closeEvent` 时保存。保存是**合并写**：先读原文件、只替换 `selections` 段，`active`（生效版本登记表，见 4.6）原样保留，整体覆盖会把切换功能写的数据抹掉
- `_apply_qss()` — 应用整张 QSS 样式表（含标题栏、卡片、下拉框、按钮、进度条、滚动条、日志区、状态栏）
- **一键启动接线**（见规则 R5）：
  - `current_components()` — 现取当前组件字典（`MainWindow.cards` → key），供卡片起 `LaunchWorker` 时传 `comps`；结果按进程缓存于 `_COMPONENTS_CACHE`（本期描述符运行时不变，故不失效）
  - `_adopt_running()` — **在入口 `main()` 里调，不在 `__init__`**（`MainWindowAdopt` 用例钉死这条：构造真窗口会读并写用户 `running.json`）。整段 try/except 兜底：`reconcile` 清僵尸要回写 `~/.env-tools/running.json`，目录只读/被锁/磁盘满时只留一条 warn，绝不把工具挡在门外；识别完再遍历卡片 `_refresh_launch_state()` 重读实况。**只读 + 清僵尸，绝不拉进程**
  - `_cancel_launch_workers()` / `closeEvent()` — 关窗前先 `findChildren(LaunchWorker)` 逐个 `cancel` 再统一 `wait`（顺序反了后一个要白等前一个超时），随后才立 `_closing` 旗、走原有的版本抓取线程收尾；关窗途中 `failed` 触发的 `_on_launch_failed` 看 `_closing` 旗早退，不弹会卡住退出的模态框

### 4.8 入口层

```python
def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    ensure_dir(CONFIG_DIR)
    win = MainWindow()
    win.show()
    return app.exec()
```

- 启用高 DPI PassThrough 策略，避免缩放模糊
- 创建 `~/.env-tools/` 工作目录
- 进入 Qt 事件循环

### 4.9 离线回归测试（`bt_*_tests.py`）

根目录下每个 `bt_*_tests.py` 都是一套**离线**回归测试（不联网、不碰真实注册表与用户 shell rc），
统一用 `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u <文件>` 运行，输出末行 `Ran N tests` / `OK` 即通过。

| 文件 | 盯住的东西 |
|------|-----------|
| `bt_multiversion_tests.py` | 组件多版本与生效版本切换（规则 R3，见下文覆盖面） |
| `bt_component_category_tests.py` | 分类分组与 Tab（R2；`EXPECTED_MEMBERSHIP` 是分类基线，另有一条用例把「一键启停」钉成 `LAUNCH_KEYS` 的派生） |
| `bt_search_and_newcmp_tests.py` | 组件搜索匹配与新增组件的自动登记（R2.5） |
| `bt_mirror_spec_tests.py` | R1 镜像规范（镜像基址集中在 `MIRROR_BASES`、官网末位等） |
| `bt_refresh_versions_tests.py` | 刷新版本链路 |
| `bt_startup_tests.py` | 启动期健壮性：`import main` 不许调用 `platform.system/machine/uname/win32_ver`（那些函数会走一次 WMI 查询） |
| `bt_gitee_sync_tests.py` | `同步Gitee产物.sh` 的离线 mock 回归（见 8.4） |
| `bt_boot_script_tests.py` | 两个一键脚本：`.bat` 必须纯 ASCII + CRLF、消息表必须 LF 且 key 与脚本双向对账、Python 自动安装链路完整（winget → 三源镜像 → 体积校验 → 不改 PATH）、外部调用一律带 `call`（见 8.2） |
| `bt_launch_tests.py` | 组件一键启动契约（规则 R5）：`LAUNCH_OF` 表完整性（白名单恰 `{jenkins, activemq, nacos}`、三平台命令非空、`min_java_major` 未实测钉为 `None`）、端口簇整簇同空、派生口跟主口平移与独立口各找自己的基准、conf 副本幂等回写与"官方文件一个字节不动"、**"回写失败 → 拒绝 spawn、不留登记"**、`netstat` 解析与端口归属歧义、僵尸登记矩阵（含旧格式记录缺 `ports` 的加载侧归一）、`NoExecInvariant`（`status`/`adopt`/`reconcile` 路径既不 `Popen` 也不查端口归属表，**且反向钉住 `force_stop` 确实会查**）、启动/停止/强杀流探针、卡片按钮与主窗 `_adopt_running`/`closeEvent` 接线（133 个用例，见 R5.6）。全量回归 9 套件之一 |
| `bt_grid_layout_tests.py` | 卡片网格与日志浮层：`grid_columns_for` 表驱动（含非法入参兜底 1 列）、`chunk_visible` 保序且不含隐藏卡片（= 空洞回归护栏）、`relayout_cards` 行数 == `ceil(N/C)` 且拼接顺序 == `self.cards`、视图模式默认 `grid` 与 `config.json` 缺键取 `grid`、**浮层展开/收起前后行数与每行卡片数完全不变**（浮层方案的核心承诺）、`warn`/`error` 自动弹开与未读条数、搜索命中数 < 列数时只有一行且无空位 |

#### `bt_multiversion_tests.py` 覆盖面

**唯一接缝是 `EnvSandbox` 基类**（它本身就是 `unittest.TestCase`，其余用例类都继承它，具体个数以文件为准）：
替换 `CONFIG_DIR` / `CONFIG_FILE` / `CURRENT_OS`、把 `EnvManager._shell_rc_file()` 指到临时 rc、
Windows 分支打桩持久层读写（`_read_windows_user_env` / `_read_windows_user_path` / `_write_registry_env` /
`_delete_windows_user_env` / `EnvManager.get`）。因此**产品代码里没有为测试留的开关**，
断言只看落盘结果（内存注册表 `win_env` / `win_path`、`CONFIG_FILE` 文本、rc 文本、`status_label.text()`），
**不断言桩被调用了几次**（调用次数是实现的代理指标，换个同样正确的实现就会误报）。
文件顶部必须先 stub WMI 再 `import main`（`platform._wmi_query` 抛 `OSError` + `platform.uname.cache_clear()`），
否则本机 WMI 卡死会让 `platform.system()` 永久阻塞。

按能力划分的覆盖点（括号内是用例类）：

1. **沙箱自身**（`SandboxSelfCheck`）：`CONFIG_DIR` 确实被换到临时目录、`make_component` 真建目录、Windows 读写与删除接缝都已打桩——防止"用例在真删用户注册表"这类事故
2. **组件能力位**（`MultiVersionFlag`）：白名单恰为 7 个（与 `EXPECTED_MULTI_VERSION` 对齐）、服务型与 `installer_mode` 组件必须为 False、每个组件都有该属性
3. **版本目录名 ⇄ 版本号**（`InstalledVersions`）：从 `<key>-<version>` 反解、忽略 `downloads` 与外来目录、按语义版本降序而非字典序、返回的目录对象就是 `install_dir()`
4. **`EnvManager` 平台无关门面**（`EnvFacade`）：UNIX 写读删闭环、PATH 条目增删与列举、Windows 写与列举、读不存在的变量返回 None、`remove_*_under` 只动指定根之下的条目
5. **切换与回滚**（`SwitchActive`）：Windows 切换写 HOME 并把 PATH 收敛成一条、Linux 写 rc、env 先写成功后失败的回滚、切换前没有该变量时回滚要"删掉"而不是写空值、目标目录不存在时抛错且什么都不改、Linux 失败按 rc 真值回滚、回滚本身失败要如实上报、各步失败的分支各自覆盖、"已落盘再抛错"的新条目也必须被撤掉
6. **`active` 读写**（`ActiveConfig` / `SaveSettingsKeepsActive`）：文件缺失 → 空表、JSON 损坏 → 不致命、写 `active` 必须保留 `selections`、损坏文件被重建、清除只删自己那一项、`infer_active_from_env` 从沙箱 rc 反推、指向别处的 HOME 不认、关窗保存不丢 `active`
7. **「配置环境变量」按选中版本生效**（`ConfigureUsesSelectedVersion`）：`_apply_active` 把 HOME 指向选中版本、按下拉框选中而非字典序最后一个、切换失败时登记表原样不动、非多版本组件仍走旧路径
8. **绿勾图标**（`InstalledCheckIcon`）：已装条目挂 `Qt.DecorationRole` 且**条目文本逐字不变**、卡片刚建好就已经挂上、非多版本组件一个图标都不挂、重灌版本列表后标记仍在、未安装的版本失去勾、切换生效后勾跟着刷新
9. **状态胶囊**（`StatusCapsuleForMultiVersion` / `StaleProbeWorkerGuard`）：`已装 N 个版本 · 生效 X（清单）`、`均未生效` 的橙色分支、选中即生效时「配置环境变量」置灰、选另一个时又可用、非多版本组件文案逐字不变、只对生效版本探测、探测到的版本号进胶囊、没有生效版本时丢弃回填、生效版本不是最高版本时胶囊说的是生效那个、上一轮探测线程的迟到回包不得污染新胶囊
10. **卸载范围**（`UninstallScope` / `UninstallTargetResolve` / `UninstallButtonGate` / `UninstallConfirmText`）：只删被删版本的 PATH 条目、卸非生效版本不动生效 HOME、卸生效版本自动切到剩余最高、删掉最后一个版本清登记并删 HOME、选中版本没装时按 `XXX_HOME` 定位（不猜最高）/ 没有 HOME 时取最高 / 非多版本组件仍罢工 / 目录名反解不出版本号时罢工并说明、卸载按钮的启用门控、确认框文案多版本收窄且非多版本逐字不变
11. **卸载修复轮**（`UninstallDeadHomeCleanup` / `UninstallActiveGuardFix2` / `UninstallHomeGuardFix3`）：组件根内的死 HOME 被清理（多版本 / 非多版本、`rmtree` 失败时不得误清、活着的其他版本 HOME 必须保住）、全删光时只清组件根内的 HOME、老配置（无 `active` 条目）在卸掉反推出来的生效版本后仍能自动重排、重建 vs 切换两种措辞的分叉、`python` 这类 `env_var=None` 的组件不被 HOME 守卫误伤、`infer_active_from_env` 拒绝指向已消失目录的死 HOME、重排日志带上"已开终端/IDE 需重开"与 Oracle javapath 提醒、登记表写入失败要按"部分成功"如实上报

> 用例数会随每轮修复增长（例如 Task 9 的三轮修复各追加了若干条），**以运行输出的 `Ran N tests` 为准**；
> 本仓库 2026-09-29 在提交 `6c0ec43` 上实测为 `Ran 84 tests / OK`。上面按"能力"列举覆盖点，不逐条罗列同名用例。

---

## 五、关键类与函数说明

### 5.1 类继承关系

```
QObject
├── QThread
│   ├── DownloadWorker      # 流式下载
│   ├── VersionFetchWorker  # 版本抓取
│   └── LaunchWorker        # 一键启动/停止（见规则 R5）
└── QWidget
    ├── QMainWindow
    │   └── MainWindow      # 主窗口（无边框）
    ├── QFrame
    │   ├── ComponentCard   # 单组件卡片
    │   └── (title_bar)     # 标题栏容器
    ├── QComboBox
    │   └── SearchableComboBox  # 可搜索下拉框
    └── QDialog
        └── DonateDialog    # 打赏弹窗
```

### 5.2 dataclass 关系

```
Component
├── versions: List[ComponentVersion]
└── detect() -> DetectResult
```

### 5.3 信号槽连接图

| 发送方.信号 | 接收方.槽 | 触发时机 |
|------------|----------|---------|
| `DownloadWorker.progress` | `ComponentCard._on_progress` | 每个 chunk 写入后 |
| `DownloadWorker.log` | `ComponentCard._log` | 下载开始/完成/失败/取消 |
| `DownloadWorker.finished_ok` | `ComponentCard._on_download_ok` (lambda 包裹 cv) | 下载成功 |
| `DownloadWorker.finished_fail` | `ComponentCard._on_download_fail` | 下载失败或取消 |
| `VersionFetchWorker.done` | `MainWindow._on_versions_fetched` | 抓取完成（含失败） |
| `VersionProbeWorker.done` | `ComponentCard._on_version_probed` | 后台版本号探测完成（状态已变则丢弃） |
| `MainWindow.btn_refresh.clicked` | `MainWindow._start_fetch_versions` | 用户点"刷新版本" |
| `MainWindow.btn_cleanup_path.clicked` | `MainWindow._on_cleanup_path_clicked` | 用户点"清理残留 PATH" |
| `MainWindow.btn_github.clicked` | `QDesktopServices.openUrl(GITHUB_URL)` | 用户点 GitHub |
| `MainWindow.btn_donate.clicked` | `MainWindow._on_donate_clicked` | 用户点打赏 |
| `ComponentCard.btn_install.clicked` | `ComponentCard.on_install_clicked` | 用户点"安装" |
| `ComponentCard.btn_configure.clicked` | `ComponentCard.on_configure_clicked` | 用户点"切换" |
| `ComponentCard.btn_cancel.clicked` | `ComponentCard.on_cancel_clicked` | 用户点"取消" |
| `ComponentCard.version_combo.currentIndexChanged` | `ComponentCard._on_index_changed` | 下拉框选中变化 |
| `ComponentCard.btn_start.clicked` | `ComponentCard.on_start_clicked` | 用户点"启动"（可启动组件才有，见 R5） |
| `ComponentCard.btn_stop.clicked` | `ComponentCard.on_stop_clicked` | 用户点"停止" |
| `ComponentCard.btn_console.clicked` | `ComponentCard.on_console_clicked` | 用户点"控制台"/"访问页" |
| `LaunchWorker.started_ok` | `ComponentCard._on_launch_ok` | 启动成功且端口已在听（回填 console_url） |
| `LaunchWorker.stopped` | `ComponentCard._on_launch_stopped` | 已停止并释放端口 |
| `LaunchWorker.need_force` | `ComponentCard._on_need_force` | 停不下来，弹一次"要强制结束吗"（force_stop/stop 都接这条线） |
| `LaunchWorker.failed` | `ComponentCard._on_launch_failed` | 门控/端口/拉起/超时/取消失败；`_closing` 时只记日志不弹模态 |
| `LaunchWorker.finished` | `ComponentCard._on_launch_worker_done` | worker 收尾：按 `sender()` 身份交回引用 + `deleteLater` |
| `main()` → `MainWindow._adopt_running()` | —（非信号，入口直接调） | 打开工具时认清本机在跑什么（只读 + 清僵尸） |

### 5.4 关键函数索引

> 行号为 2026-09-28 对当前 `main.py` 实测的「约」值，后续改动会漂移，以函数名检索为准。

| 函数 | 行号附近 | 职责 |
|------|---------|------|
| `human_size(num)` | ~110 | 字节数转可读字符串 |
| `ensure_dir(path)` | ~119 | 确保目录存在 |
| `MIRROR_BASES` / `_MIRROR_BY_NAME` | ~457 | R1 国内镜像源基址常量清单（11 个源，`(标识, 基址)` 形式） |
| `GH_ACCELERATORS` | ~473 | GitHub Release 反向加速器前缀清单（3 个） |
| `DOWNLOAD_PROBE_TIMEOUT / DOWNLOAD_TIMEOUT / DOWNLOAD_RETRY_PER_URL` | ~480 | R1 故障转移参数常量 |
| `HTTP_UA` / `DOWNLOAD_MIN_VALID_BYTES` | ~486 / ~489 | 出网请求固定 UA / 下载体最小有效字节数校验 |
| `_mb(*names)` / `_gh_accelerated(url)` | ~492 / ~502 | R1 公共辅助：按标识取镜像基址 / GitHub 加速器地址列表 |
| `_cv(version, url_map, archive_map)` | ~520 | 构造 ComponentVersion，第三参覆盖默认归档表 `_STD_ARCHIVE` |
| `_probe_version(exe, args)` | ~403 | 静默执行外部命令抓版本号：空 `args` 不执行；Windows 带 `CREATE_NO_WINDOW` + `stdin=DEVNULL`，4 秒超时 |
| `VersionProbeWorker` | ~434 | 后台线程版 `_probe_version`，供卡片异步回填版本号 |
| `find_dead_tool_path_entries()` / `cleanup_dead_tool_path_entries()` | ~3347 / ~3363 | 列出 / 删除 PATH 中指向 `CONFIG_DIR` 子树但目录已不存在的残留条目 |
| `_get(url, timeout=10)` | ~1595 | 带重试 + SSL 降级的 HTTP GET，请求头固定 `HTTP_UA` |
| `_sort_semver_desc(vs)` | ~1626 | 语义化版本倒序排序 |
| `_fetch_github_releases_versions(repo, prefix)` | ~2322 | R1 公共辅助：抓取 GitHub Releases 版本列表（Nacos/Seata/RabbitMQ 等复用） |
| `_fetch_apache_versions(key)` | ~2213 | R1 公共辅助：抓取 Apache 项目版本列表（Kafka/RocketMQ/Pulsar/ActiveMQ 复用） |
| `build_components()` | ~2486 | 构造 36 个组件的默认（离线）清单，全部用 `url_list_map` 走 R1 多源（实测例外：mongodb / postgresql 无国内镜像、官网单源；kubectl 大陆源仅 DaoCloud 一家；powershell 无真镜像走三个 GitHub 加速器；nginx 只有 Windows 有官方 zip，且大陆仅华为云两个子域同步） |
| `extract_archive(archive, extract_to)` | ~3407 | 解压 zip/tar.gz/tar.xz + 单二进制 + .war 单文件 |
| `DownloadWorker(urls, dest)` | ~2909 | R1 多源故障转移下载线程（带 `HTTP_UA` 请求头 + `DOWNLOAD_MIN_VALID_BYTES` 字节校验） |
| `main()` | ~4783（末尾） | 程序入口 |

---

## 六、核心流程

### 6.1 启动流程

```
main()
  ├─ QApplication 配置高 DPI
  ├─ ensure_dir(CONFIG_DIR)
  └─ MainWindow()
       ├─ setWindowIcon(assets/byte-tools.png)
       ├─ build_components()           # 构造 36 个组件的默认清单（可安装的走 R1 多源；「开发工具」按 R13 只给官方直链）
       ├─ _build_ui()                 # 构造标题栏 + 搜索条(含视图切换/日志开关) + 卡片网格 + 日志浮层 + 状态栏(组件总数=26)
       ├─ _apply_qss()                # 应用样式表
       ├─ _load_settings()             # 从 config.json 恢复上次选中版本
       └─ _start_fetch_versions()      # 为 26 张卡片各起一个 VersionFetchWorker 并发抓取
            └─ 每个 worker 完成时发射 done → _on_versions_fetched → card.set_versions
```

### 6.2 下载安装流程（用户点击"下载并安装"，R1 多源故障转移）

```
ComponentCard.on_install_clicked()
  ├─ 取当前选中 ComponentVersion
  ├─ 检查 unsupported_platform_hint：非空则弹友好提示（如 Windows Docker）并返回
  ├─ 决定下载文件后缀（.zip / .tar.gz / .exe / .sh / .war / ""单二进制）
  ├─ urls = cv.urls_for_current()           # 返回 R1 URL 列表：镜像优先 + 末位官网
  ├─ 创建 DownloadWorker(urls, dest)
  └─ worker.start()
       │
       ▼  QThread.run()  遍历 self.urls
       ├─ for idx, url in enumerate(urls, 1):
       │    ├─ log.emit("info", f"开始下载（第 {idx}/{len(urls)} 个源）：{url}")
       │    ├─ _try_download(url)
       │    │    ├─ requests.get(stream=True, timeout=DOWNLOAD_TIMEOUT, headers=HTTP_UA)
       │    │    ├─ 循环 r.iter_content(chunk_size=64KB)
       │    │    │    ├─ 检查 _cancel 标志
       │    │    │    ├─ 写入 .part 临时文件
       │    │    │    └─ progress.emit(downloaded, total)
       │    │    ├─ 校验 downloaded ≥ DOWNLOAD_MIN_VALID_BYTES 且不短于 Content-Length
       │    │    │    └─ 不合格 → 删 .part、判该源无效、换下一个源（假 200 空体防护）
       │    │    ├─ tmp.replace(dest)
       │    │    ├─ log.emit("ok", f"下载完成：{dest}，实际使用源：{url}")
       │    │    └─ finished_ok.emit(dest)   # 成功直接返回
       │    └─ 失败（含 404）→ log.emit("warn", "第 idx 个源失败，切换下一个")
       │         404 等不可恢复错误不内部重试，直接切下一个
       └─ 全部失败 → 汇总失败原因 + finished_fail.emit("所有下载源均不可用")
            │
            ▼  UI 线程
            _on_download_ok(path, cv)
              ├─ if installer_mode: _run_installer (Miniconda 静默安装)
              ├─ else:
              │    ├─ extract_archive(path, tmp_dir)
              │    ├─ 单二进制 / .war 重命名（kubectl.exe / kubectl / jenkins.war）
              │    └─ shutil.move 到 install_dir
              ├─ _configure_env(final)         # 一条龙：自动配置环境变量
              │    ├─ Windows: winreg 写 XXX_HOME + 追加 PATH
              │    └─ UNIX:    写 shell rc + 追加 PATH
              └─ _detect_status()              # 刷新状态胶囊
```

### 6.3 配置环境变量 / 切换生效版本流程

```
ComponentCard.on_configure_clicked()   # main.py:5066
  ├─ 组件根 CONFIG_DIR/<key> 不存在 → 提示"尚未下载，请先执行下载并安装"
  ├─ ordered = installed_versions(component)          # 语义降序的真实已装版本
  ├─ 多版本组件（multi_version=True）：
  │    ├─ chosen = 下拉框选中的版本；不在 ordered 里 → 提示"下拉框选的是 X，磁盘上没有对应目录"
  │    └─ _apply_active(chosen)                        # main.py:5045
  │         ├─ apply_active_version(comp, chosen)      # 唯一入口，失败抛 SwitchError（已回滚）
  │         ├─ 成功才 save_active_version(key, chosen) # 写 config.json 的 active 段
  │         └─ _refresh_installed_marks() + _detect_status()
  └─ 非多版本组件：沿用旧行为，取 ordered[0]（语义版本最高的目录）调 _configure_env()，
        不写 active 表
```

> 「切换」对多版本组件即"把选中版本设为生效版本"。选中版本已经是生效版本时按钮禁用
> （`_detect_status` 里 `btn_configure.setEnabled(selected != active)`），tooltip 提示先在下拉框换版本。

### 6.4 版本抓取流程

```
MainWindow._start_fetch_versions()
  ├─ 检查无 worker 运行中
  ├─ 清理旧 worker
  ├─ btn_refresh 禁用 + 文字 "抓取中…"
  └─ for card in cards:                       # 26 张卡片
       if fetcher := FETCHERS[card.component.key]:
         w = VersionFetchWorker(key, fetcher)   # 内部 _fetch_xxx_versions 也走 R1 镜像优先
         w.done.connect(_on_versions_fetched)
         w.start()
         _fetch_pending += 1

_on_versions_fetched(key, versions)
  ├─ if versions is None: 日志告警降级
  ├─ else: card.set_versions(versions)
  └─ _fetch_pending -= 1
       └─ ==0 时 btn_refresh 恢复 + 日志"获取完成"
```

### 6.5 卸载流程（多版本只动选中版本）

```
on_uninstall_clicked()   # main.py:4995
  ├─ 二次确认框（多版本尾巴："只删除选中的这一个版本，其他已装版本不动；若删掉的正是当前
  │    生效版本，会自动切到剩余里版本号最高的那个"；非多版本尾巴逐字保持原文）
  └─ Component.uninstall(version)   # main.py:340，返回中文摘要（各步以中文分号 `；` 连接）
       ├─ active_before 快照（仅多版本，在任何破坏性动作之前，main.py:375）
       ├─ ① 删该版本目录（installer_mode 跳过）
       ├─ ② 删 XXX_HOME：仅当它正指向被删目录；指向同组件其它版本保留；指向组件根之外只报"未删除"；
       │      指向根内已消失目录的死配置清掉
       ├─ ③ PATH：默认只清本次被删目录之下的条目；本组件已无其它目录时才回到按组件根清扫
       └─ ④ 多版本收尾（只认 active_before 快照）：全删光清登记；删掉的是生效版本→切剩余最高；
              生效版本仍在但被带偏→按它重建（措辞"重建"而非"切"）
```

> 卸载目标定位（`resolve_uninstall_target`）与四步语义见 4.2 的方法说明；
> `bt_multiversion_tests.py` 的覆盖面见 4.9（沙箱原则见 DEVELOPMENT.md R3.8，非多版本零影响护栏见 R3.9）。

### 6.6 一键启动的数据流（规则 R5）

> 落地状态如实描述：**框架与 Jenkins / ActiveMQ / Nacos 三件的一键启动已实现、有离线护栏
> （`bt_launch_tests.py` 133 例）守护**；Windows 真机 `--launch jenkins|nacos|activemq --yes`
> **一次都没跑过**，计划一 spec §2.4 第 3、5 项与计划二 spec §8.2 的 A1–A7 全部仍无结论、
> `min_java_major` 维持 `None`、`console_path`/`health_path` 两个新组件仍为推测值。
> 下述数据流是代码路径的静态描述，**不代表已在真机跑通**。

```
点"启动"（ComponentCard.on_start_clicked）
  ├─ 弹确认框（spec.main_port + spec.risk_note）→ 用户 Yes
  └─ LaunchWorker("start").start()          # 脱离 UI 线程，parent=self 交对象树持有
       │
       ▼  ServiceManager.start(comp, comps)  # 探针全可注入，测试不碰网络也不碰进程
       ├─ 门控 launch_gate：没装 / JDK 不足 → StartResult(False,"gate",可行动原因)
       ├─ choose_ports(spec)：主口+派生口整簇平移（pick_free_cluster）+ 独立口各找自己的基准
       │    └─ 任一口找不到位 → StartResult(False,"port",指名是哪个口)
       ├─ resolve_java_home（优先本工具装的 JDK）+ build_launch_plan（展开 argv、注入 JAVA_HOME/JENKINS_HOME、拼 console_url）
       ├─ prepare_ports(...)：端口回写闸门，必须在 spawn 之前完成
       │    ├─ cli_only / cli_flag → 直接放行，一个文件都不碰
       │    └─ conf_copy → 官方 conf 整目录拷进 ~/.env-tools/<key>-data/conf，只改这份副本
       │         └─ 锚不到官方默认那一行 → StartResult(False,"writeback",指名改哪一行)，不 spawn
       ├─ 建 ~/.env-tools/<key>-data/logs，把 stdout/stderr 重定向到 byte-tools.out
       ├─ subprocess.Popen(argv, DETACHED…)  # 这是"启动"动作，唯一允许拉进程的地方
       ├─ 有界轮次探活（每轮 sleeper(1.0)，最多 startup_timeout 轮）
       │    ├─ **整簇端口都在听** → 写 running.json（RunRecord：ports 整簇、port 是真相、pid_role=server/launcher）
       │    │     → started_ok(key, console_url, notes)   # notes 带"端口写在哪份文件里"
       │    └─ 超时 → proc.terminate() 收尸（不留无主监听者）+ 厂商日志尾巴的 reason → failed
       └─ 卡片收到 started_ok → _refresh_launch_state()：启动置灰、停止/打开控制台启用、卸载锁死

打开工具（main() → MainWindow._adopt_running，不在 __init__）
  └─ ServiceManager.reconcile：只 load_running_map + 整簇端口探活
       ├─ 整簇都在听 → "running"；登记在但簇里任一口没了 → "zombie" → 清该条登记回写
       └─ 全程一次都不 Popen、也不查端口归属表（NoExecInvariant 钉死）；reconcile 失败只留一条 warn，不挡启动

点"停止"（on_stop_clicked → LaunchWorker("stop")）
  └─ ServiceManager.stop：先按**整簇**探活（整簇都空 → 直接清登记算停好）
       ├─ Windows(pid) 或 port_lookup → 只请示不自动强杀 → need_force 信号
       └─ 用户确认 → LaunchWorker("force_stop")
            ├─ **端口反查**（stop_kind=port_lookup 时多出的一步，见下）
            ├─ 三重闸：有我们的登记 + 不是我们自己 + 用户已确认
            │    └─ 归属有歧义（同口多 PID）或指向我们自己 → 一个都不杀，当场说清为什么并返回
            └─ os.kill → 整簇端口确认释放才清登记

点"打开控制台"（on_console_clicked）
  └─ QDesktopServices.openUrl(登记的 console_url)   # 用的是实际端口，不是默认 8080

关窗（MainWindow.closeEvent）
  └─ _cancel_launch_workers()：先全部 cancel 再统一 wait → 才走原有版本线程收尾
```

> **端口反查是停止路径上多出的一步**：`jenkins` 的 PID 就是服务进程，按登记 PID 停即可；
> 但 Nacos / ActiveMQ 的启动脚本会自我后台化，登记的 PID 是包装脚本而不是服务进程
> （`pid_role=launcher`），厂商自带的关闭脚本按进程名强杀又会误伤本机同名实例。
> 因此 `force_stop` 在"登记 PID 不可信"时走 `netstat -ano` 反查端口归属，再经三重闸才动手。
> **反查绝不出现在检测路径**：它是一次进程外调用，出现在 `status/adopt/reconcile` 就等于从后门放掉
> "状态检测绝不执行进程"，由 `NoExecInvariant` 的正反两条用例同时钉住。

> 语义要点：**端口是真相、PID 只是尽力而为地停止**；`status/adopt/reconcile` 只读、绝不拉进程；
> "运行中"必须整簇都在听（只判主口会把半死的 Nacos 报成运行中）；停不下来只问人、未确认不强杀也不清登记；
> 运行中禁止卸载；端口回写只写 `~/.env-tools/<key>-data` 下的副本，厂商官方文件一个字节不动。
> 完整约束见 [DEVELOPMENT.md](./DEVELOPMENT.md) R5。

---

## 七、依赖关系

### 7.1 Python 第三方依赖

来自 [requirements.txt](./requirements.txt)：

| 包 | 版本要求 | 用途 |
|---|---------|------|
| `PySide6` | >=6.6.0 | Qt 6 GUI 框架，提供窗口、控件、信号槽、QThread |
| `requests` | >=2.31.0 | HTTP 下载与官网 API 调用 |

### 7.2 标准库依赖

| 模块 | 用途 |
|------|------|
| `base64` | （导入但当前未实际使用，可清理） |
| `json` | 偏好记忆文件 config.json 读写 |
| `os` | 环境变量读取、文件权限（chmod） |
| `platform` | 系统与 CPU 架构识别 |
| `shutil` | `which` 探测、`rmtree`、`move` |
| `subprocess` | 调用可执行文件抓版本号、运行安装器 |
| `sys` | `sys.argv`、退出码 |
| `tarfile` | `.tar.gz` / `.tar.xz` 解压 |
| `traceback` | 异常栈打印到日志 |
| `zipfile` | `.zip` 解压 |
| `dataclasses` | `@dataclass` 装饰 |
| `pathlib.Path` | 路径处理 |
| `typing` | 类型注解 |
| `re` | 抓取 HTML 页面解析版本号 |
| `time` | `_get` 重试退避 |
| `urllib3` | 关闭 SSL 警告 |
| `winreg` | Windows 注册表读写（条件导入） |

### 7.3 运行时外部依赖

- **网络**：需访问对应组件的官方下载源（Adoptium API、Apache 归档、python.org、nodejs.org、GitHub API、repo.anaconda.com、go.dev、services.gradle.org、dl.k8s.io、get.jenkins.io、elastic.co 等）。`_get` 自带 3 次重试 + 第 3 次关闭 SSL 校验，应对企业代理 MITM 场景；下载流程额外走 R1 国内镜像优先（MIRROR_BASES）；所有出网请求固定携带 `HTTP_UA`（清华 TUNA / BFSU 实测拒绝默认 UA）
- **磁盘**：建议预留 3 GB 以上
- **权限**：Windows 写用户级环境变量通常无需管理员；macOS/Linux 需对 `~/.zshrc` 等文件有写权限；macOS/Linux 上单二进制组件（kubectl 等）需 `chmod +x`

### 7.4 打包依赖（PyInstaller）

`PyInstaller` 不进 `requirements.txt`（仅打包时需要，运行时不依赖）：

```bash
pip install pyinstaller
pyinstaller byte-tools.spec --noconfirm --clean
```

打包配置关键点（见 [byte-tools.spec](./byte-tools.spec)）：
- `datas`：把 `assets/` 目录打进包内（含窗口图标 byte-tools.png、收款码图等）
- `icon`：**仅 Windows**（`sys.platform == "win32"` 且文件存在时）指向 `assets/byte-tools.ico`；macOS/Linux 传 `None`，保持原 CI 行为
- `hidden_imports`：显式声明 PySide6 子模块和 requests 依赖链
- `excludes`：排除 `tkinter` / `test` / `PySide6.QtNetwork` 等不需要的大模块，减小体积
- `console=False`：GUI 应用，不显示控制台
- `upx=False`：UPX 在 macOS 上会导致启动崩溃，统一禁用
- macOS 走 `BUNDLE` 生成 `.app`，`bundle_identifier=com.rgh.byte-tools`

#### 换 exe 图标（assets/byte-tools.ico 怎么来的）

PyInstaller 在 Windows 只接受 `.ico`，直接喂 PNG 会报错，所以 `assets/byte-tools.png`（512×512）要先转成多尺寸 ICO。改了 logo 后重新生成一次（需要 Pillow，项目 `.venv` 里没有，用系统 python 跑即可，不必加进 `requirements.txt`）：

```python
from PIL import Image
im = Image.open("assets/byte-tools.png").convert("RGBA")
s = min(im.size); im = im.crop(((im.size[0]-s)//2, (im.size[1]-s)//2,
                               (im.size[0]-s)//2+s, (im.size[1]-s)//2+s))  # ICO 必须正方形
im.save("assets/byte-tools.ico", format="ICO",
        sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
```

验证图标是否真的进了 exe（别信"文件变小了/变大了"这类间接感觉，直接读 PE 资源）：

```text
RT_GROUP_ICON 里应列出 16/24/32/48/64/128/256 七档，且最大那条 RT_ICON 的字节与 .ico 最大图完全一致
```

> 注意两点：① 窗口/任务栏图标由 `main.py` 里 `setWindowIcon(QIcon("assets/byte-tools.png"))` 控制，与 exe 图标是两回事，换图要同时改；② 原地覆盖 `dist/ByteTools.exe` 后资源管理器可能仍显示旧图，那是 **图标缓存**，换个文件名或 `ie4uinit.exe -show` 即可看到新图标。


### 7.5 模块间依赖图

```
                    ┌────────────┐
                    │  main()    │
                    └─────┬──────┘
                          │
              ┌───────────▼───────────┐
              │      MainWindow       │
              └──┬────────────┬───────┘
                 │            │
       启动 worker            显示卡片
                 │            │
    ┌────────────▼───┐  ┌────▼────────────┐
    │VersionFetch    │  │ ComponentCard    │
    │Worker          │  │  ├─ SearchableComboBox
    │  ├─ FETCHERS   │  │  ├─ DownloadWorker
    │  │  (24个fetch │  │  │   (R1 多源故障转移
    │  │   + R1镜像)│  │  │    遍历 url_list_map)
    │  └─ URL 构造器 │  │  ├─ EnvManager
    │     (R1 列表)  │  │  └─ extract_archive
    └────────────────┘  │     + 单二进制/.war
                        └──────────────────┘
                                  │
                        ┌─────────▼─────────┐
                        │  Component /      │
                        │  ComponentVersion │
                        │  / DetectResult   │
                        │ (url_list_map +   │
                        │  unsupported_     │
                        │  platform_hint)   │
                        └───────────────────┘
```

---

## 八、项目运行方式

### 8.1 终端用户（推荐）

直接到 [Releases](https://github.com/jilong2026/byte-tools/releases/latest) 下载对应平台的二进制：

| 系统 | 文件 | 说明 |
|------|------|------|
| Windows | `ByteTools.exe` | 双击运行 |
| macOS (Apple Silicon) | `ByteTools-macos-arm64.zip` | 解压后双击 `.app` |
| Linux (x64) | `ByteTools-linux-x64` | `chmod +x` 后执行 |

> **macOS (Intel)**：自 v1.0.5 起不再发布 Intel 通用包（GitHub 已下线 Intel runner），Intel 机器请按 8.3 从源码运行。

首次启动提示：
- macOS：未签名，需到「系统设置 → 隐私与安全性」点"仍要打开"，或 `xattr -cr ByteTools.app`
- Windows：SmartScreen 弹窗点"更多信息 → 仍要运行"
- Linux：双击无响应时改用终端 `chmod +x ... && ./...`

### 8.2 Windows 一键脚本（一键启动项目.bat / 一键打包exe.bat）

仓库根目录提供两个中文命名的自举脚本，双击即可，**无需手动管理虚拟环境和依赖**：

```bat
一键启动项目.bat        :: 装配环境后 python main.py
一键打包exe.bat         :: 装配环境 + 装 PyInstaller 后按 spec 打包
一键打包exe.bat nopause :: 供其它脚本调用（结束不等待按键）
```

两者共用同一套流程（打包脚本在 [3/4] 之后多一步 PyInstaller 检查）：

| 步骤 | 行为 | 失败出口 |
| --- | --- | --- |
| `[1/4]` | **先验 `.venv`**：版本落在 3.10–3.14 内就整步跳过，不找也不装解释器（省时间与流量）。否则依次试 `py -3.12/-3.13/-3.11/-3.10/-3.14` → `python`/`python3` → `%LOCALAPPDATA%\Programs\Python\Python<若干命名>\python.exe` → `for /d` 通配扫 `%LOCALAPPDATA%\Programs\Python\*`、`%ProgramFiles%\Python*`、`%ProgramFiles(x86)%\Python*`。**全空才自动安装**：`winget`（`where` 看不见就直接探 `%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe`）→ 不行再按 **华为云 → npmmirror → python.org** 下载官方安装包，拿到的文件 `< 5 MB` 判该源无效并换下一个，装完 30 秒内有界复扫 | 全部试过仍没有 Python 才 `:err_no_python`，文案先说清"脚本自动走过哪些路"，手工安装只作最后一句兜底 |
| `[2/4]` | `.venv\Scripts\python.exe` 存在且版本落在 3.10–3.14 就复用；缺失则新建，损坏或版本越界则 `venv --clear` 重建 | `:err_no_python` / `:err_venv` |
| `[3/4]` | `import PySide6, requests` 失败才 `pip install -r requirements.txt`；镜像顺序 **清华 TUNA → 阿里云 → 官方 PyPI** | `:err_deps` |
| `[3/4] 前置` | **WMI 只做一次 2 秒有界探测**（daemon 线程 + `os._exit`，保证一定返回），只提示不阻塞；以前"等 15 秒再等 120 秒"是让用户白看，已删。打包侧真正的问题由 `pyinstaller_no_wmi.py` 解决 | 无（提示后继续） |
| `[4/4]` | `call "%RUN_PY%" main.py`，或 `call "%RUN_PY%" pyinstaller_no_wmi.py --noconfirm byte-tools.spec` 并校验 `dist\ByteTools.exe` | `:err_main` / `:err_no_dist` |

实现约束（改动时请保持，护栏用例 `bt_boot_script_tests.py`）：
- **`.bat` 本体必须 100% 纯 ASCII**。这不是格式洁癖：cmd.exe 用字节偏移量记录它读批处理的位置，文件里有多字节字符、又在中途 `chcp 65001` 时，偏移会错位，于是从**行的中间**开始解析——`REM` 注释与 `echo` 文案被当成命令执行，整条语句被吞掉。2026-10-05 本机实测：原 UTF-8 版脚本跑出 7 行 `'xxx' is not recognized as an internal or external command`，被吞的正好是 `:bootstrap_python` 的后半段（下载安装包 → 静默安装 → 复扫），于是"机器上没装 Python"就直落到"叫用户自己 winget / 自己去 python.org 下载"。同一份内容转成纯 ASCII（保留 `chcp 65001`）或转成 GBK + `chcp 936`，异常都是 0 行
  > 本节旧文写的是"UTF-8 + 自带 chcp 已验证显示正常"——那只验了**显示**，没验**语句有没有真的执行**，结论是假的
- **中文文案是数据不是代码**：放在 `assets\msg_zh.txt`（`key=value`，UTF-8，**LF 结尾**——`for /f` 会把 CRLF 的 `CR` 留在值里，`echo` 再补一个，每条消息多一次回车），由 `call :say key "英文兜底" "{0}的实参"` 打印。表值里不许有 `!`（延迟展开会吃掉）；英文兜底不许有 cmd 元字符 `&|<>()^"`，它走解析期插入，而表值不走
- **语言选择 fail-open**：`chcp` 之前先抓 OEM 码页，再用 `reg query "HKCU\Control Panel\International" /v Locale` 取 LCID 末 4 位（0804/0404/0C04/1004）判中文；两者都不成立、或消息表文件缺失 → 退回英文。**不许用 `| find` 做过滤**：Git Bash 的 GNU find 会顶掉 `find.exe`，在 `/i` 参数上直接报错（本机踩过）
- **外部调用一律带 `call`**：批处理里不带 `call` 调用另一个批处理，控制权不返回。`python.bat` / `curl.cmd` / `winget.cmd` 这类垫片（Anaconda、scoop 常见）会一模一样把脚本当场掐死——本机用 `stub\winget.bat` 复现过：脚本打印完"正在用 winget 静默安装"就再没有下文
- **版本区间只有一处真源**：3.10–3.14，取自 PySide6 6.11 的 `requires_python >=3.10,<3.15`。收 3.9 或收 3.15 都会让用户走到"依赖装不上"的死路，而那里的旧文案是叫他自己再装一个 3.12
- **自动安装不写 PATH**：`InstallAllUsers=0 PrependPath=0 Include_launcher=0`。发现逻辑读的是安装目录，写 PATH 既不必要，也违背"不修改系统环境"的承诺
- **不用括号块读 errorlevel**：`if %errorlevel% ...` 一律配 `goto`，避免同一括号块内 `%errorlevel%` 在解析期展开导致读到旧值
- **只在项目目录内动作**：不写注册表、不改系统 PATH、不改全局 Python；唯一例外是本机一个可用 Python 都没有时按用户级装一份 3.12（落在 `%LOCALAPPDATA%\Programs\Python`）
- **`main.py` 启动期不得调用 `platform.system()` / `platform.machine()`**：这两个函数内部走 `uname() → win32_ver() → 一次 WMI 查询`，WINMGMT 冷启动时能阻塞几十秒到一两分钟（本机实测：预热后同一调用 0.6 秒），表现就是"双击启动脚本后窗口一直不出来"。系统名用 `sys.platform` 判、架构用 `PROCESSOR_ARCHITEW6432/PROCESSOR_ARCHITECTURE`（POSIX 用 `os.uname().machine`）取，取值与 `platform` 的原答案一致；护栏用例见 `bt_startup_tests.py`
- **PyInstaller 可用性只查落盘文件**（`.venv\Lib\site-packages\PyInstaller\__init__.py`），不要用 `python -c "import PyInstaller"` 探测：那条 import 必问 WMI，冷启动时脚本就卡在那里
- **行尾必须是 CRLF**：LF-only 的批处理会让标签查找失败，本机实测报 `cannot find the batch label specified - try_dir`（用 Python 生成 .bat 时最容易顺手写成 LF）
- 中文文件名走 `CreateProcessW` 双击正常；用 Git Bash 以 UTF-8 argv 调用时会因编码转换失败，需用 Python `subprocess` 传绝对路径

### 8.3 开发者源码运行（跨平台）

```bash
# 1. 克隆
git clone https://github.com/yourname/byte-tools.git
cd byte-tools

# 2. 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动
python main.py
```

### 8.4 打包发布

#### 本地单平台打包

```bash
pip install pyinstaller
pyinstaller byte-tools.spec --noconfirm --clean
```

产物：
- Windows：`dist/ByteTools.exe`
- macOS：`dist/ByteTools.app`
- Linux：`dist/byte-tools`

打包配置关键点（见 [byte-tools.spec](./byte-tools.spec)）：
- `datas`：把 `assets/` 目录打进包内
- `hidden_imports`：显式声明 PySide6 子模块和 requests 依赖链
- `excludes`：排除 `tkinter` / `test` / `PySide6.QtNetwork` 等不需要的大模块，减小体积
- `console=False`：GUI 应用，不显示控制台
- `upx=False`：UPX 在 macOS 上会导致启动崩溃，统一禁用
- macOS走 `BUNDLE` 生成 `.app`，`bundle_identifier=com.rgh.byte-tools`

#### GitHub Actions 三平台自动发布 + Gitee 同步（.github/workflows/release.yml）

```bash
git tag v1.0.1
git push origin v1.0.1
```

推 tag 触发 `.github/workflows/release.yml`：Windows / macOS / Linux 三个 runner 分别打包并上传到 GitHub Release（先以草稿暂存），随后 `sync-to-gitee` job 自动取消草稿完成 GitHub 发布，并调用根目录的 `同步Gitee产物.sh` 在 Gitee 建 Release、写入各平台产物的 GitHub 直链。

发布说明：
- 构建产物共 3 个平台 4 个文件：`ByteTools.exe`、`ByteTools-windows-x64.zip`、`ByteTools-macos-arm64.zip`、`ByteTools-linux-x64`
- **2026-09-29 起 Gitee 侧默认不接收大二进制**：`sync-to-gitee` 只在 Gitee Release 正文写一张「文件 / 大小 / GitHub 直链」表格。原因见 `同步Gitee产物.sh` 顶部——境外 runner 往 gitee.com 推 84MB 会长时间挂死且服务端不落地（v1.0.3 实测挂 70 分钟、零附件、零日志）
- 产物名单只有一个维护点：workflow step 的 `RELEASE_ARTIFACTS`（脚本内同名环境变量），它同时决定正文表格、上传资格与收尾校验；`UPLOAD_ARTIFACTS`（默认空）是要真正推给 Gitee 的子集，需要站内直下时填小包并把 job 改成国内 `self-hosted` runner
- 脚本只在**创建** Release 时写正文：Gitee「更新 Release」接口的方法/路径未能在官方文档核实（swagger 是 JS 页），所以不猜。补同步老 tag 时若正文缺直链，脚本会硬失败并打印「网页端粘正文 / 删 Release 重建」两条路子
- **三道保险**（`同步Gitee产物.sh`）：① 可观测的快速失败——每次请求打 HTTP 码、耗时、已传字节与均速，4xx 立即判死、网络类错误按 `MAX_ATTEMPTS`（默认 3：5s/10s）退避，且 curl 不再叠 `--retry` 以免与脚本重试相乘；② 幂等（Release 已存在复用 ID、同名附件跳过，失败后 Re-run 安全）；③ 收尾回查正文直链与 `UPLOAD_ARTIFACTS` 的附件清单，缺一项即失败
- `sync-to-gitee` job 带 `timeout-minutes: 25`（此前无上限、走 GitHub 默认 360 分钟，是「卡住没人知道」的根子）
- 令牌只走 curl 表单字段，不拼 URL、不用 `curl -v`，避免进日志
- 同步依赖仓库 Secret `GITEE_TOKEN`（Gitee 私人令牌，需 projects 权限），owner / repo 由 workflow 顶层的 `GITEE_OWNER` / `GITEE_REPO` 指定，GitHub 侧仓库标识由 `GITHUB_REPO_SLUG` 传入以生成直链
- **每次发版的固定三步**（2026-09-29 与用户确认的分工）：① `git tag vA.B.C && git push origin vA.B.C` —— 必须先把改动推到 master，因为 workflow 取的是 tag 指向那个 commit 里的 release.yml；② 等 Actions 全绿，此时 GitHub 有 4 个产物且已正式发布，Gitee 只有带 GitHub 直链的正文、附件区为空；③ 本机 `curl`（走 `gh-proxy.com`）取 4 个产物到 `release-assets/`，再跑 `同步Gitee产物.bat <tag>` 把附件传上 Gitee。要省掉第 ③ 步就改用国内 `self-hosted` runner + 填 `UPLOAD_ARTIFACTS`
- **补同步历史 tag**：workflow 支持 `workflow_dispatch`（输入 `tag_name`），在 GitHub → Actions → release → Run workflow 触发，跳过三平台构建。因为 `workflow_dispatch` 读的是默认分支的 workflow，改动合入 master 后即可对任意历史 tag 生效
- **本机手动补同步**：Windows 跑 `同步Gitee产物.bat`（双击或传参；它会真的把产物传上 Gitee，国内链路快，与 CI 的「只写直链」策略有意不同），Linux/macOS/Git Bash 跑 `同步Gitee产物.sh`（默认只写直链，设 `UPLOAD_ARTIFACTS` 才上传）。两个脚本都**先预检产物目录再请求 Gitee**：目录里没有 `ByteTools.exe` 等四个文件时立刻报错并打印取产物的 curl 命令，不会白跑一趟。`.bat` 的默认产物目录是 `release-assets/`（已 gitignore），**不是仓库自带的 `assets/`**——后者是图标目录（`byte-tools.png`/`.ico`/`alipay.png`/`wechat.png`），指过去就会「一个产物都没有」。脚本对 JSON 解释器做握手测试，避开 Windows 上 `python3` 是 Microsoft Store 占位别名的坑
- 同步脚本的离线回归测试：[bt_gitee_sync_tests.py](./bt_gitee_sync_tests.py)（本地 mock Gitee + 产物名一致性守卫，15 个用例，绝不碰真实站点）；覆盖「不传二进制只写直链 / 幂等复用 / 已存在但缺直链→硬失败并给出补救 / 上传子集跳过与补传 / 接口回成功但附件没落地→硬失败 / 5xx 有界重试且可见 / 4xx 不浪费重试 / 产物目录指错时在请求 Gitee 之前就拦下 / Gitee 用 200+null 表示『该 tag 没有 Release』/ 4 处产物名清单一致」
- **全自动发布，无需人工操作**：矩阵各平台先上传到草稿 Release 作暂存区（构建中途失败不会对外暴露半成品），待全部平台成功、`sync-to-gitee` 启动后自动 `gh release edit --draft=false` 取消草稿；因此跑绿即等于 `releases/latest/download/...` 已指向新版本
- 任一平台的构建/上传失败，或 Gitee 侧任一步校验不通过，都会让整个 run 直接变红（不会静默放过）

---

## 九、配置与扩展指南

### 9.1 修改 / 新增组件版本

打开 [main.py](./main.py) 的 `build_components()` 函数，调整 `versions` 列表（离线默认清单）：

```python
components.append(
    Component(
        key="jdk",
        display_name="JDK (Temurin)",
        env_var="JAVA_HOME",
        path_subdir="bin",
        exec_name="java",
        version_args=["-version"],
        versions=[
            ComponentVersion(
                version=v,
                url_list_map=_adoptium_jdk_url(v),  # ← R1：用 url_list_map 而非 url_map
                archive_map={"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"},
            )
            for v in ("21", "17", "11", "8")  # ← 在此增减版本
        ],
    )
)
```

> 注意：`versions` 只是**离线默认清单**。启动时后台会自动向官方 API 拉取真实版本覆盖此清单，所以"修改默认清单"主要影响离线场景。

### 9.2 新增一个全新组件（R1 多源故障转移配置）

新增组件**必须**遵守 [DEVELOPMENT.md](./DEVELOPMENT.md) R1 规则：每个组件的**下载 URL** 至少 2 个国内镜像 + 末位官网（实测凑不出 2 个源时按 R1.1 登记例外，如 MongoDB / PostgreSQL——2026-09-28 实测无国内镜像，官网单源）。

1. 写 URL 构造器，返回 `Dict[str, List[str]]`（按 OS 键映射的 URL 列表，镜像在前，官网末位）：

```python
def _foo_urls(v: str) -> Dict[str, List[str]]:
    """
    构造 foo 组件的 R1 多源 URL 列表。

    入参 v: str   版本号
    返回: Dict[str, List[str]]  按 OS 键映射的 URL 列表（国内镜像在前 + 末位官网）
    """
    # 镜像基址用 _mb(标识) 从 MIRROR_BASES 取，不要硬编码域名
    bases = _mb("huaweicloud", "tuna", "aliyun", "nju")
    file = f"foo-{v}-bin"
    win, mac, linux = [], [], []
    for base in bases:
        # 镜像路径根据实际镜像源拼接（不同镜像路径规则可能不同，按需调整）
        win.append(f"{base}/foo/{v}/{file}.zip")
        mac.append(f"{base}/foo/{v}/{file}.tar.gz")
        linux.append(f"{base}/foo/{v}/{file}.tar.gz")
    # 末位追加官网
    official = f"https://download.foo.org/{v}/{file}"
    win.append(f"{official}.zip")
    mac.append(f"{official}.tar.gz")
    linux.append(f"{official}.tar.gz")
    return {"Windows": win, "Darwin": mac, "Linux": linux}
```

2. 写版本抓取器（同样走 R1 镜像优先；若数据源是 GitHub Releases 或 Apache 归档，直接复用公共辅助）：

```python
def fetch_foo_versions() -> List[ComponentVersion]:
    # GitHub 项目：versions = _fetch_github_releases_versions("foo/bar", prefix="v")
    # Apache 项目：versions = _fetch_apache_versions("foo")
    # 自定义：先走国内镜像索引页，失败切官网
    ...
    return [ComponentVersion(version=v, url_list_map=_foo_urls(v)) for v in versions]
```

3. 注册到 `FETCHERS`：`"foo": fetch_foo_versions`
4. 在 `build_components()` 末尾 `components.append(Component(key="foo", ...))`
5. 若该组件在特定平台不支持自动下载（如 Docker 在 Windows），设 `unsupported_platform_hint="Windows 下请安装 Docker Desktop"`，对应 OS 的 `url_list_map` 返回空列表
6. 在 `COMPONENT_CATEGORY_OF` 里登记分类（`开发环境` / `开发软件` / `开发工具` / `一键启停`；能一键启停的组件会被 `LAUNCH_KEYS` 自动改归「一键启停」，所以这里给它们写的是「退出白名单之后回哪儿」）——**漏登记会直接 KeyError**，界面不会静默少一个 Tab
7. UI 会自动在对应 Tab 下出现一张新卡片，无需改动布局代码

> **R1 硬性要求**（见 [DEVELOPMENT.md](./DEVELOPMENT.md) R1.1）：新增组件的**下载 URL** 未配置 ≥2 个国内镜像地址，不予合入；确实凑不出 2 个源时（实测国内无该制品镜像，如 MongoDB / PostgreSQL 二进制包），必须在 R1.5 登记实测结论并保留官网单源，不得用猜测的镜像路径凑数。版本**索引页**不适用本要求（见 R1.7 第 4 节，镜像索引版本数残缺）。

### 9.3 更换 / 增减镜像源

镜像源基址**集中维护**在 `MIRROR_BASES` 常量，**严禁**散落在各 URL 构造器里硬编码：

```python
MIRROR_BASES: List[tuple] = [
    ("huaweicloud",    "https://repo.huaweicloud.com"),          # M1，覆盖最广
    ("huaweicloud-py", "https://mirrors.huaweicloud.com"),       # M1b，Python 发行包只在此子域
    ("tuna",           "https://mirrors.tuna.tsinghua.edu.cn"),  # M2
    ("aliyun",         "https://mirrors.aliyun.com"),            # M3
    ("nju",            "https://mirrors.nju.edu.cn"),            # M4
    ("ustc",           "https://mirrors.ustc.edu.cn"),           # M5
    ("bfsu",           "https://mirrors.bfsu.edu.cn"),           # M5b
    ("tencent",        "https://mirrors.cloud.tencent.com"),     # M5c
    ("sjtug",          "https://mirrors.sjtug.org"),             # M6
    ("npmmirror",      "https://registry.npmmirror.com"),        # N1，淘宝二进制镜像（python/bun/node 走 `/-/binary/…`）
    ("daocloud-files", "https://files.m.daocloud.io"),           # N2，只对少数白名单域名反代（kubectl 走它）
]
```

构造器里用 `_mb("tuna", "nju")` 按标识取基址，不要写死域名；GitHub Release 类组件用 `_gh_accelerated(url)`（加速器在前、裸地址末位）。
调整顺序 / 增删镜像源统一改这一处即可，同时同步 [DEVELOPMENT.md](./DEVELOPMENT.md) R1.3 表。故障转移参数同理集中在 `DOWNLOAD_PROBE_TIMEOUT` / `DOWNLOAD_TIMEOUT` / `DOWNLOAD_RETRY_PER_URL`，出网 UA 与下载校验阈值集中在 `HTTP_UA` / `DOWNLOAD_MIN_VALID_BYTES`。

### 9.4 修改工作目录

```python
CONFIG_DIR = Path.home() / ".env-tools"  # ← 改这一行
```

---

## 十、已知约束与注意事项

### 10.1 平台与架构

- 当前 `IS_ARM` 仅粗略判断（`"arm" in MACHINE or "aarch64" in MACHINE`），覆盖 Apple Silicon 与 Linux ARM64；Windows ARM 未做特别适配
- macOS 未代码签名，首次打开需手动放行
- Linux x64 为主，Linux ARM 未验证
- **平台不支持自动下载**（通过 `Component.unsupported_platform_hint` 给出友好提示，对应 OS 的 `url_list_map` 返回空列表）：
  - **Windows** 下 **Docker** 不支持自动下载（提示用户安装 Docker Desktop）
  - **Windows** 下 **RabbitMQ** 不支持自动下载（依赖 Erlang，提示用户手动安装）
  - **Linux / macOS** 下 **PostgreSQL** 不支持自动下载（提示用发行版包管理器 / Homebrew，仅 Windows 提供 zip 直连源）
  - **macOS** 下 **MongoDB** 不支持自动下载（建议用 Homebrew 或 Docker）
  - **Linux / macOS** 下 **Git** 不支持自动下载（上游只有 `git/git` 源码 tar.gz，解压后无可执行文件；提示用 `apt` / `dnf` / `yum` / `brew` 安装）

### 10.2 环境变量写入

- **Windows**：默认写 **用户级** 变量（`HKCU\Environment`），通常不需要管理员权限；若需写系统级需改 `winreg.HKEY_LOCAL_MACHINE`
- **Windows PATH 长度**：不再使用 `setx`（它会把超过 1024 字符的 PATH 截断），一律 `winreg` 直写注册表 + 异步广播 `WM_SETTINGCHANGE`；写用户 PATH 时只按单条目增删，绝不用注册表的用户段覆盖进程 PATH；用户级 PATH 仍受系统总长度限制
- **UNIX 幂等**：用 marker 标记包裹的写入块可重复更新；但若用户手工编辑了 marker 之间的内容，会被覆盖
- **UNIX shell 选择**：`_shell_rc_file()` 按 `SHELL` 环境变量选文件，若用户用了 fish / nushell 等非 POSIX shell，需自行扩展

### 10.3 MySQL 特殊性

- MySQL 解压后**不能直接用**，还需执行 `mysqld --initialize` 等初始化步骤。本工具只完成"下载 + 解压 + 环境变量"三步
- MySQL 没有公开 API，抓取器扫 `downloads.mysql.com/archives` 索引；若失败回退到硬编码保底清单（`fetch_mysql_versions` 内联）

### 10.4 Miniconda 安装器模式

- 安装到 `~/.env-tools/conda/conda-<version>/`
- Windows 参数：`/S /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /D=<path>`，注意 `/D=path` 必须放最后且不能带引号
- macOS/Linux：`bash installer.sh -b -f -p <path>`

### 10.5 已下载检测的局限

- `_detect_status` 判定"已下载"的依据是 `CONFIG_DIR/<key>/` 下有非 `.` 开头、非 `downloads` 的子目录，对组件目录命名有隐含约定
- 若用户手工把组件装到别处但设了 `XXX_HOME`，仍能被 `Component.detect` 识别为"已配置"

### 10.6 多 worker 并发

- `_start_fetch_versions` 会同时启动 **24** 个 `VersionFetchWorker`；每个内部 `_get` 重试 3 次 + 退避，最坏情况单组件耗时约 6-10 秒
- 仍在运行时再次点击"刷新版本"会被拒绝并提示

### 10.7 偏好记忆

- `config.json` 只保存每个组件上次选中的**显示文本**（含 LTS 标签），下次启动按 `findText` 恢复；若新拉取的版本列表里没有该文本则回落到 index 0
- 文件损坏时静默忽略（`_load_settings` 用 `try/except` 包裹）

### 10.8 安全性

- `_get` 第 3 次重试关闭 SSL 校验（`verify=False`），应对企业代理 MITM 场景；同时 `urllib3.disable_warnings` 抑制警告
- 不做 checksum 验证：只有 `DOWNLOAD_MIN_VALID_BYTES`（4096）字节数下限 + `Content-Length` 一致性校验，用于挡「200 + 空体」假源，其余下载内容由用户自行负责

### 10.9 R1 多源故障转移注意事项

- **404 等不可恢复错误不内部重试**：单 URL 返回 4xx 状态码（404 最常见）说明该镜像路径不存在，`_try_download` 立即抛错并切到 `url_list_map` 下一个 URL，不在该 URL 上重试 `DOWNLOAD_RETRY_PER_URL` 次，避免浪费时间（见 [DEVELOPMENT.md](./DEVELOPMENT.md) R1.4）
- 镜像源路径规则差异：不同镜像（华为云 / 清华 / 阿里云）对同一项目的目录结构可能略有差异，URL 构造器需按各镜像实际路径拼接，不能假设所有镜像同构
- 全部源失败时 `DownloadWorker.finished_fail` 携带汇总错误信息（每个源的失败原因列表），用户在日志区可见全部尝试过的源
- 旧 `url_map` 字段仍保留向后兼容：极少数组件若未升级到 R1 多源模式，`urls_for_current()` 会把单 URL 包成单元素列表返回，下载逻辑一致
- 单二进制组件（kubectl 无扩展名）在 Linux/Mac 下 `_on_download_ok` 会 `chmod +x`；Jenkins `.war` 单文件直接重命名落位，不解压

### 10.10 探测阶段绝不执行启动脚本

- **教训**：早期 Nacos 的 `exec_name="startup"`，Windows 上被 PATHEXT 匹配到 Tomcat 的 `startup.bat`，而 `startup.bat` 无条件 `call catalina.bat start` —— 打开界面就等于悄悄启动了一台 Tomcat，还要用户关掉那个窗口后主界面才出现
- 现有三重防线：① `exec_name` 带扩展名（`startup.cmd` / `startup.sh`）避免同名异扩展命中；② `Component.version_probe=False`（Nacos / Seata / Kafka / RocketMQ / RabbitMQ）让探测只判定存在；③ `_probe_version` 遇到空 `version_args` 直接返回，不裸跑命令
- 版本探测统一在 `VersionProbeWorker` 后台线程执行，且带 `CREATE_NO_WINDOW` + `stdin=DEVNULL` + 4 秒超时，既不弹控制台也不会卡 UI 线程
- Kafka 在 Windows 上的可执行脚本位于 `bin/windows`（`bin` 下只有无扩展名的 shell 脚本），故其 `path_subdir` 按平台取 `bin/windows` / `bin`

### 10.11 一键启动：状态检测与找回绝不执行启动脚本

- 10.10 的"探测阶段绝不执行启动脚本"不变量，被一键启动扩成：**状态检测与找回（`status` / `adopt` / `reconcile` / `_adopt_running`）也绝不拉起进程**，只允许 `socket` 连端口 + `urllib` 取健康路径。唯一允许 `subprocess.Popen` 的地方是显式的 `start()` 启动动作。`bt_launch_tests.py` 的 `NoExecInvariant` 把 `Popen` / `_probe_version` 桩成"一调用就抛"来钉死这条
- **端口反查也不许进检测路径**：计划二新增的 `netstat_listener_pids`（一次 `netstat -ano`）是进程外调用，
  出现在 `status/adopt/reconcile` 就等于从后门放掉上面那条不变量。两条用例同时钉住：
  正向 `test_detection_paths_never_consult_the_port_owner_table`（检测路径零调用）+
  **反向** `test_force_stop_actually_consults_it`（`force_stop` 必须调一次，且查的是整簇端口）
  —— 没有反向断言，"不许调用"可以靠把调用删干净白赢
- **端口是真相、PID 只是提示**：`running.json` 记录的端口**簇**（`ports`，缺省由加载侧按 `(port,)` 归一）决定是否"运行中"，
  只判主口会把"主口在听、gRPC 9848 掉了"的半死 Nacos 报成运行中；`pid_role ∈ {server, launcher, none}`，
  只有 `server` 且 PID 为正才允许按登记 PID 终止。计划二的 Nacos/ActiveMQ（脚本自我后台化、PID 不可信）
  不走厂商 shutdown 脚本，而是 `stop_kind="port_lookup"` 的端口反查——Nacos 的 `shutdown.cmd` 按进程名
  `taskkill /F` 会误伤本机其它同名实例，ActiveMQ 的 `stop` 经 JAAS/JMX 且受 conf 副本影响；
  反查只允许出现在 `stop` / `force_stop` 路径，动手前必须过三重闸（有我们的登记 + 不是我们自己 +
  用户已确认强制结束），归属有歧义（同口多 PID）时宁可不杀
- **端口回写只写副本**：`port_writeback="conf_copy"` 把官方 `conf` 整目录拷进 `~/.env-tools/<key>-data/conf`，
  端口只写这份副本，**厂商官方文件在任何策略下都不被修改**；锚不到官方默认那一行就**拒改并指名要改哪一行**，
  不许猜用户的改法。回写失败必须**阻止拉起**（改了配置却没起进程比"没启动"更难归因）
- **停不下来只问人**：Windows 上 `os.kill` 任何信号都是 `TerminateProcess`，所以 `stop()` 在 Windows 绝不动手、直接 `need_force` 请示；`force_stop` 也只在**整簇**端口确认释放后才清登记
- **真机验证仍欠**：`--launch jenkins|nacos|activemq --yes` **一次都没跑过**（需用户在场），
  计划一 spec §2.4 第 3、5 项与计划二 spec §8.2 的 A1–A7 全部无结论、`min_java_major` 保持 `None`、
  两个新组件的 `console_path` / `health_path` 仍是推测值。macOS/Linux 分支代码写完但一律标为未验证
- 详见 [DEVELOPMENT.md](./DEVELOPMENT.md) 规则 R5 与设计文档 [docs/superpowers/specs/2026-10-05-launch-activemq-nacos-design.md](./docs/superpowers/specs/2026-10-05-launch-activemq-nacos-design.md)

---

## 附录：关键文件快速索引

| 想了解 | 看 |
|--------|----|
| 项目整体说明（用户视角） | [README.md](./README.md) |
| 开发约定与 R1 规则 | [DEVELOPMENT.md](./DEVELOPMENT.md) |
| 代码 Wiki（本文档） | [CODE_WIKI.md](./CODE_WIKI.md) |
| 全部源码 | [main.py](./main.py) |
| 依赖清单 | [requirements.txt](./requirements.txt) |
| Windows 一键脚本 | [一键启动项目.bat](./一键启动项目.bat) / [一键打包exe.bat](./一键打包exe.bat)（见 8.2） |
| 打包配置 | [byte-tools.spec](./byte-tools.spec) |
| 忽略规则 | [.gitignore](./.gitignore) |
| MIT 许可证 | [LICENSE](./LICENSE) |
| 静态资源（窗口图标 + 收款码） | [assets/](./assets) |
