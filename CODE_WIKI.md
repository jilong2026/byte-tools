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

**byte-tools** 是一款基于 **Python 3.9 + PySide6** 的跨平台桌面 GUI 工具，目标是把开发者最常用的语言运行时、构建工具、中间件的下载与配置全部自动化。

一句话定位：

> 让"新机器 → 一套完整开发环境"这件事变成点几下鼠标就搞定。

支持 **26 个组件**，按分类组织如下（详见 [DEVELOPMENT.md](./DEVELOPMENT.md) 的 R1 规则）：

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

- **语言**：Python 3.9+
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

---

## 三、目录结构

```
byte-tools/
├── main.py                  # 主程序（含 UI 与全部逻辑，约 4800 行）
├── requirements.txt         # Python 依赖清单（PySide6、requests）
├── byte-tools.spec      # PyInstaller 打包配置
├── 一键启动项目.bat     # 自举脚本：定位 Python → 建/复用 .venv → 装依赖 → 启动 GUI
├── 一键打包exe.bat      # 自举脚本：同上 + 装 PyInstaller → 产出 dist/byte-tools.exe
├── 同步Gitee产物.sh     # Gitee Release 同步（Linux/macOS/CI；默认只在正文写 GitHub 直链，可观测快速失败 + 幂等 + 收尾校验），由 release.yml 调用
├── 同步Gitee产物.bat    # 本机 Windows 版（双击可运行；它会真的把产物传上 Gitee，国内链路快，与 CI 策略有意不同；内容为纯 ASCII，避免 cmd 按 GBK 解析 UTF-8 出错）
├── README.md                # 中文说明（面向最终用户）
├── README_EN.md             # 英文说明
├── DEVELOPMENT.md           # 开发者文档（开发约定、R1 规则等，面向二次开发者）
├── CODE_WIKI.md             # 本文档（代码 Wiki，面向二次开发者）
├── LICENSE                  # MIT 许可证
├── .gitignore               # Git 忽略规则
├── .github/workflows/       # 发布工作流（release.yml：三平台打包 + Gitee 同步）
└── assets/                  # 静态资源（PyInstaller 打包时通过 datas 一并打入）
    ├── byte-tools-pt.png    # 主界面截图
    ├── byte-tools.png       # 应用窗口图标
    ├── wechat.png           # 微信收款码
    └── alipay.png           # 支付宝收款码
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
| `installer_args` | Dict[str, List[str]] | 按操作系统键取的安装器静默参数 |
| `unsupported_platform_hint` | Optional[str] | 平台不支持自动下载时的友好提示文本（如 Docker 在 Windows 提示用 Docker Desktop；为 None 表示该平台支持） |
| `category` | str | 界面 Tab 分组名，取值限于 `COMPONENT_CATEGORIES`（开发环境 / 开发软件 / 其它软件）。**不在构造处手写**：`build_components()` 末尾统一按 `COMPONENT_CATEGORY_OF[comp.key]` 赋值，漏登记即 KeyError |

方法：
- `install_dir(version)` → 该版本的解压安装目录 `CONFIG_DIR/<key>/<key>-<version>`
- `exec_path_in_home(home)` → 在指定 `XXX_HOME` 下查找可执行文件，依次尝试 `path_subdir`/`bin`/`Scripts`/`condabin`/根目录；Windows 上按 `.exe`/`.bat`/`.cmd`/`.com`/无扩展名依次匹配（Tomcat 的 `catalina` 只有 `.bat`，只找 `.exe` 会漏检）
- `installed_dirs()` → 列出 `CONFIG_DIR/<key>` 下真实存在的安装目录（排除 `downloads` 缓存）
- `resolve_uninstall_target(version)` → 把下拉框选中的版本校正为磁盘上真正装着的目录，返回 `(目录, 中文说明)`
- `uninstall(version)` → 删除安装目录、清理落在本组件目录内的 `XXX_HOME` 与 PATH 条目（不再依赖 `path_subdir` 是否配置）
- `detect(probe_version=True)` → **核心探测逻辑**，返回 `DetectResult`；`exec_name` 为 None 的组件（如 Jenkins）走 `_detect_by_home_dir()` 兜底：只要 `XXX_HOME` 指向本工具安装目录即视为已配置。界面构建卡片时传 `probe_version=False`，只判定存在、不执行外部命令
- `exec_name` 在 Windows 上还会被 `shutil.which` 用 PATHEXT 匹配同名异扩展文件，因此 Nacos 必须写成带扩展名的 `startup.cmd`/`startup.sh`——写 `startup` 会命中 Tomcat 的 `startup.bat`，探测就变成了启动 Tomcat

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

幂等机制：UNIX 系统下用 `marker_begin` / `marker_end` 包裹写入块，再次写入时只替换两标记之间的内容，不会重复堆积。

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

UI 组成（自上而下）：
1. **顶部行**：组件名 `QLabel` + 状态胶囊 `QLabel`
2. **中部行**：版本下拉框 `SearchableComboBox` + "下载并安装" + "配置环境变量" + "取消"按钮
3. **底部**：进度条 `QProgressBar`

状态胶囊三态（`_detect_status` 设置，全程不执行外部命令）：
- 🟢 `✓ 已配置（CATALINA_HOME / PATH）· <version>` — 系统已能找到，禁用"配置环境变量"按钮、启用"卸载"；版本号先显示 `版本检测中…`，由 `VersionProbeWorker` 异步回填，`version_probe=False` 的组件不显示版本
- 🟠 `● 已下载，未配置` — 本地已解压但环境变量未设
- 🔴 `○ 未安装` — 完全没有

关键方法：
- `_schedule_version_probe(exe_path)` / `_start_version_probe(exe_path)` — `QTimer.singleShot(0, …)` 延后到事件循环空闲，再起 `VersionProbeWorker` 后台跑 `_probe_version`；`version_probe=False` 或 `version_args` 为空直接跳过
- `_on_version_probed(text)` — 回填版本并重绘胶囊；状态已不是"已配置"时丢弃结果，避免晚到的回包把卸载后的标签刷回绿色
- `set_versions(versions)` — 接收抓取线程返回的新版本列表，替换 `component.versions` 并刷新下拉框；保留上次选中版本（按 version 字段匹配）
- `on_install_clicked()` — 取出当前选中版本，决定下载文件后缀（安装器模式按 `archive_map` 取扩展名；普通模式按 `archive_for_current()` 决定 `.zip` / `.tar.gz` / `.war` / `""`单二进制），构造 `urls = cv.urls_for_current()` 启动 `DownloadWorker(urls, dest)`；下载→解压→自动配置环境变量→刷新状态一条龙流程
- `_on_download_ok(path, cv)` — 下载成功回调：安装器模式走 `_run_installer`；普通模式走 `extract_archive` + `shutil.move`；**单二进制 / `.war` 重命名逻辑**（kubectl-1.28.4.exe → kubectl.exe / kubectl-1.28.4 → kubectl / jenkins-2.426.war → jenkins.war）；最后自动调用 `_configure_env`
- `_run_installer(installer_path, target_dir)` — 静默执行 Miniconda 等：Windows 拼 `/D=<path>`（不能带引号）；mac/Linux 用 `bash installer.sh -b -f -p <path>`
- `on_configure_clicked()` — 仅配置环境变量：从本地已解压目录里按字典序选最新一个，调 `_configure_env`
- `_configure_env(install_path)` — 写 `XXX_HOME` + 追加 PATH；Windows 用 `EnvManager.set_windows_user_env` + `append_windows_path`；UNIX 用 `set_unix_env` + `append_unix_path`
- `on_cancel_clicked()` — 调 `worker.cancel()`

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
3. **搜索条**（标题栏与 Tab 之间，`objectName="searchBar"`）：外壳 `QFrame#searchShell` 里放放大镜 `QLabel#searchIcon` + `QLineEdit#compSearch`（透明无边框、自绘 × 清空按钮），右侧 `QLabel#searchHint` 实时显示"匹配 N / 26 个组件"（0 命中时转警示红）。`textChanged` → `MainWindow._apply_search()`；聚焦时整条外壳描蓝边（`MainWindow.eventFilter()` 转发焦点 → `_set_search_focus()` 改 `focused` 属性并重刷样式，QSS 的 `:focus` 管不到父级），放大镜同步变色。图标由 `_make_search_icon()` / `_make_clear_icon()` 用 QPainter 现画，不引入图片资源。**放在标题栏之外**，因为标题栏整条是窗口拖拽区（`mousePressEvent` 里 `title_bar.underMouse()` 会开始拖动），输入框塞进去就点不动了
4. **主体 QSplitter（垂直）**：   - 上部 `QTabWidget`（`objectName="compTabs"`，`setTabPosition(North)` 顶部横向）按 `COMPONENT_CATEGORIES` 分三个 Tab，**标题带组件数量**：`开发环境（10）` / `开发软件（13）` / `其它软件（3）`（数字由 `len(comps)` 现算，不写死）；每个 Tab 内一条独立 `QScrollArea` 挂该分类的 `ComponentCard`
   - **搜索过滤**由 `component_matches(comp, query)` 判定（显示名或 key 的子串，忽略大小写与首尾空白；空查询不过滤）：命中的 `card.setVisible(True)`，其余隐藏。搜索时 `QStackedWidget#topStack` 收起三个 Tab、切到统一结果页 `QScrollArea#resultsArea`，把所有命中组件**按分类归并到同一滚动列表**（每类前有 `QLabel#resultCatHeader` 小标题），清空后切回 Tab 浏览态、卡片各自归位。这是"全组件搜索、而非只搜单个 table"的呈现。过滤**只改可见性与归属**，`MainWindow.cards` 平铺列表始终是全量 26 项
   - 下部日志区 `QTextEdit`（深色主题、等宽字体）
5. **底部状态栏**：显示当前系统信息、工作目录与 `组件总数：N 个`（N=26，方便用户一眼掌握支持范围）

> **不变量**：`MainWindow.cards` 仍是**全量平铺**列表（26 张卡片，跨 Tab 收集），
> 刷新版本、读写配置、关窗前等探测线程都遍历它；分组只影响卡片的父布局，不影响这个列表。
> 分类数据由 `COMPONENT_CATEGORY_OF` 单点登记 → `build_components()` 末尾写入 `Component.category`
> → `group_components()` 按 `COMPONENT_CATEGORIES` 顺序出组；未登记的 key 会 KeyError，不会静默漏卡片。

无边框窗口拖动：
- `mousePressEvent` 在标题栏区域按下左键时记录 `_drag_pos`
- `mouseMoveEvent` 持续移动窗口
- `mouseDoubleClickEvent` 双击标题栏切换最大化

关键方法：
- `_on_cleanup_path_clicked()` — "清理残留 PATH"入口：先用 `find_dead_tool_path_entries()` 只读预览并弹确认框，确认后 `cleanup_dead_tool_path_entries()` 删除死条目、写日志并逐卡片 `_detect_status()` 刷新
- `_start_fetch_versions()` — 从各官网并发拉取版本列表。若仍有 worker 运行则提示；否则清理旧 worker，为每个有 fetcher 的卡片启动一个 `VersionFetchWorker`（26 个并发），计数器 `_fetch_pending` 等所有完成后再恢复按钮
- `_on_versions_fetched(key, versions)` — 单个抓取完成回调，versions 为 None 时日志告警降级，否则调 `card.set_versions`
- `_append_log(level, msg)` — 彩色日志输出：info 灰 / ok 绿 / warn 橙 / error 红，用 `<span style="color:...">` 包裹塞进 `QTextEdit`
- `_load_settings()` / `_save_settings()` — 启动时从 `CONFIG_FILE` 加载上次选中版本；`closeEvent` 时保存
- `_apply_qss()` — 应用整张 QSS 样式表（含标题栏、卡片、下拉框、按钮、进度条、滚动条、日志区、状态栏）

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

---

## 五、关键类与函数说明

### 5.1 类继承关系

```
QObject
├── QThread
│   ├── DownloadWorker      # 流式下载
│   └── VersionFetchWorker  # 版本抓取
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
| `ComponentCard.btn_install.clicked` | `ComponentCard.on_install_clicked` | 用户点"下载并安装" |
| `ComponentCard.btn_configure.clicked` | `ComponentCard.on_configure_clicked` | 用户点"配置环境变量" |
| `ComponentCard.btn_cancel.clicked` | `ComponentCard.on_cancel_clicked` | 用户点"取消" |
| `ComponentCard.version_combo.currentIndexChanged` | `ComponentCard._on_index_changed` | 下拉框选中变化 |

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
| `build_components()` | ~2486 | 构造 26 个组件的默认（离线）清单，全部用 `url_list_map` 走 R1 多源（实测例外：mongodb / postgresql 无国内镜像、官网单源；kubectl 大陆源仅 DaoCloud 一家；powershell 无真镜像走三个 GitHub 加速器；nginx 只有 Windows 有官方 zip，且大陆仅华为云两个子域同步） |
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
       ├─ build_components()           # 构造 26 个组件的默认清单（全部用 url_list_map 走 R1 多源）
       ├─ _build_ui()                 # 构造标题栏 + 卡片 + 日志区 + 状态栏(组件总数=24)
       ├─ _apply_qss()                # 应用样式表
       ├─ _load_settings()             # 从 config.json 恢复上次选中版本
       └─ _start_fetch_versions()      # 启动 24 个 VersionFetchWorker 并发抓取
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

### 6.3 仅配置环境变量流程

```
ComponentCard.on_configure_clicked()
  ├─ 在 CONFIG_DIR/<key>/ 下找已解压目录
  ├─ 字典序排序取最后一个（最新版本）
  └─ _configure_env(latest_dir)
       └─ _detect_status()
```

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

> 注意两点：① 窗口/任务栏图标由 `main.py` 里 `setWindowIcon(QIcon("assets/byte-tools.png"))` 控制，与 exe 图标是两回事，换图要同时改；② 原地覆盖 `dist/byte-tools.exe` 后资源管理器可能仍显示旧图，那是 **图标缓存**，换个文件名或 `ie4uinit.exe -show` 即可看到新图标。


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
| Windows | `byte-tools.exe` | 双击运行 |
| macOS (Apple Silicon) | `byte-tools-macos-arm64.zip` | 解压后双击 `.app` |
| Linux (x64) | `byte-tools-linux-x64` | `chmod +x` 后执行 |

> **macOS (Intel)**：自 v1.0.5 起不再发布 Intel 通用包（GitHub 已下线 Intel runner），Intel 机器请按 8.3 从源码运行。

首次启动提示：
- macOS：未签名，需到「系统设置 → 隐私与安全性」点"仍要打开"，或 `xattr -cr byte-tools.app`
- Windows：SmartScreen 弹窗点"更多信息 → 仍要运行"
- Linux：双击无响应时改用终端 `chmod +x ... && ./...`

### 8.2 Windows 一键脚本（一键启动项目.bat / 一键打包exe.bat）

仓库根目录提供两个中文命名的自举脚本，双击即可，**无需手动管理虚拟环境和依赖**：

```bat
一键启动项目.bat        :: 装配环境后 python main.py
一键打包exe.bat         :: 装配环境 + 装 PyInstaller 后按 spec 打包
一键打包exe.bat nopause :: 供其它脚本调用（结束不等待按键）
```

两者共用同一套四步流程（打包脚本在 [3/4] 之后多一步 PyInstaller 检查）：

| 步骤 | 行为 | 失败出口 |
| --- | --- | --- |
| `[1/4]` | 定位解释器：`where py` 命中则依次试 `py -3.12 / -3.13 / -3.11 / -3.10 / -3.9 / -3`，再退到 `python`；用 `-c "sys.exit(0 if version_info >= (3,9) else 1)"` 判定可用性 | 仅记 `BASE_PY` 为空，不中断（有可用 `.venv` 时不需要它） |
| `[2/4]` | `.venv\Scripts\python.exe` 存在且能 `import sys` 就复用；损坏则 `venv --clear` 重建；缺失则新建 | `:err_no_python` / `:err_venv` |
| `[3/4]` | `import PySide6, requests` 失败才 `pip install -r requirements.txt`；镜像顺序 **清华 TUNA → 阿里云 → 官方 PyPI** | `:err_deps` |
| `[4/4]` | `python main.py`，或 `python -m PyInstaller --noconfirm byte-tools.spec` 并校验 `dist\byte-tools.exe` | `:err_main` / `:err_no_dist` |

实现约束（改动时请保持）：
- **编码**：UTF-8（无 BOM）+ CRLF，脚本第 2 行 `chcp 65001 >nul`。本机 `GetACP/GetOEMCP` 实测为 65001，GBK 版脚本双击必乱码；UTF-8 + 自带 `chcp` 在 65001 与强制 936 两种控制台下都验证过显示正常
- **不用括号块读 errorlevel**：`if %errorlevel% ...` 一律配 `goto`，避免同一括号块内 `%errorlevel%` 在解析期展开导致读到旧值
- **只在项目目录内动作**：不写注册表、不改系统 PATH、不改全局 Python
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
- Windows：`dist/byte-tools.exe`
- macOS：`dist/byte-tools.app`
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
- 构建产物共 3 个平台 4 个文件：`byte-tools.exe`、`byte-tools-windows-x64.zip`、`byte-tools-macos-arm64.zip`、`byte-tools-linux-x64`
- **2026-09-29 起 Gitee 侧默认不接收大二进制**：`sync-to-gitee` 只在 Gitee Release 正文写一张「文件 / 大小 / GitHub 直链」表格。原因见 `同步Gitee产物.sh` 顶部——境外 runner 往 gitee.com 推 84MB 会长时间挂死且服务端不落地（v1.0.3 实测挂 70 分钟、零附件、零日志）
- 产物名单只有一个维护点：workflow step 的 `RELEASE_ARTIFACTS`（脚本内同名环境变量），它同时决定正文表格、上传资格与收尾校验；`UPLOAD_ARTIFACTS`（默认空）是要真正推给 Gitee 的子集，需要站内直下时填小包并把 job 改成国内 `self-hosted` runner
- 脚本只在**创建** Release 时写正文：Gitee「更新 Release」接口的方法/路径未能在官方文档核实（swagger 是 JS 页），所以不猜。补同步老 tag 时若正文缺直链，脚本会硬失败并打印「网页端粘正文 / 删 Release 重建」两条路子
- **三道保险**（`同步Gitee产物.sh`）：① 可观测的快速失败——每次请求打 HTTP 码、耗时、已传字节与均速，4xx 立即判死、网络类错误按 `MAX_ATTEMPTS`（默认 3：5s/10s）退避，且 curl 不再叠 `--retry` 以免与脚本重试相乘；② 幂等（Release 已存在复用 ID、同名附件跳过，失败后 Re-run 安全）；③ 收尾回查正文直链与 `UPLOAD_ARTIFACTS` 的附件清单，缺一项即失败
- `sync-to-gitee` job 带 `timeout-minutes: 25`（此前无上限、走 GitHub 默认 360 分钟，是「卡住没人知道」的根子）
- 令牌只走 curl 表单字段，不拼 URL、不用 `curl -v`，避免进日志
- 同步依赖仓库 Secret `GITEE_TOKEN`（Gitee 私人令牌，需 projects 权限），owner / repo 由 workflow 顶层的 `GITEE_OWNER` / `GITEE_REPO` 指定，GitHub 侧仓库标识由 `GITHUB_REPO_SLUG` 传入以生成直链
- **每次发版的固定三步**（2026-09-29 与用户确认的分工）：① `git tag vA.B.C && git push origin vA.B.C` —— 必须先把改动推到 master，因为 workflow 取的是 tag 指向那个 commit 里的 release.yml；② 等 Actions 全绿，此时 GitHub 有 4 个产物且已正式发布，Gitee 只有带 GitHub 直链的正文、附件区为空；③ 本机 `curl`（走 `gh-proxy.com`）取 4 个产物到 `release-assets/`，再跑 `同步Gitee产物.bat <tag>` 把附件传上 Gitee。要省掉第 ③ 步就改用国内 `self-hosted` runner + 填 `UPLOAD_ARTIFACTS`
- **补同步历史 tag**：workflow 支持 `workflow_dispatch`（输入 `tag_name`），在 GitHub → Actions → release → Run workflow 触发，跳过三平台构建。因为 `workflow_dispatch` 读的是默认分支的 workflow，改动合入 master 后即可对任意历史 tag 生效
- **本机手动补同步**：Windows 跑 `同步Gitee产物.bat`（双击或传参；它会真的把产物传上 Gitee，国内链路快，与 CI 的「只写直链」策略有意不同），Linux/macOS/Git Bash 跑 `同步Gitee产物.sh`（默认只写直链，设 `UPLOAD_ARTIFACTS` 才上传）。两个脚本都**先预检产物目录再请求 Gitee**：目录里没有 `byte-tools.exe` 等四个文件时立刻报错并打印取产物的 curl 命令，不会白跑一趟。`.bat` 的默认产物目录是 `release-assets/`（已 gitignore），**不是仓库自带的 `assets/`**——后者是图标目录（`byte-tools.png`/`.ico`/`alipay.png`/`wechat.png`），指过去就会「一个产物都没有」。脚本对 JSON 解释器做握手测试，避开 Windows 上 `python3` 是 Microsoft Store 占位别名的坑
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
6. 在 `COMPONENT_CATEGORY_OF` 里登记分类（`开发环境` / `开发软件` / `其它软件`）——**漏登记会直接 KeyError**，界面不会静默少一个 Tab
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
