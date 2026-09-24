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

支持 **24 个组件**，按分类组织如下（详见 [DEVELOPMENT.md](./DEVELOPMENT.md) 的 R1 规则）：

| 分类 | 组件 | 内部 key | 环境变量 | 默认版本来源 |
|------|------|---------|---------|-------------|
| 语言运行时 | JDK (Temurin) | `jdk` | `JAVA_HOME` | Adoptium API |
| 语言运行时 | Python | `python` | —（走 PATH） | python.org FTP 索引 |
| 语言运行时 | Node.js | `node` | `NODE_HOME` | Node.js dist/index.json |
| 语言运行时 | Go | `go` | `GOROOT` | go.dev/dl 索引 |
| 语言运行时 | Bun | `bun` | —（走 PATH） | GitHub Releases |
| 构建工具 | Apache Maven | `maven` | `MAVEN_HOME` | Apache 归档目录页 |
| 构建工具 | Gradle | `gradle` | `GRADLE_HOME` | services.gradle.org 索引 |
| 应用服务器 | Apache Tomcat | `tomcat` | `CATALINA_HOME` | Apache 归档目录页 |
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
| 服务发现/事务 | Seata | `seata` | `SEATA_HOME` | GitHub Releases（apache/incubator-seata） |
| 搜索引擎 | Elasticsearch | `elasticsearch` | `ES_HOME` | elastic.co 归档索引 |
| 版本控制 | Git | `git` | — | Git for Windows Releases API |
| Python 发行版 | Miniconda | `conda` | `CONDA_HOME` | Anaconda Repo 索引（安装器模式） |

> 平台支持差异：Docker / RabbitMQ 在 Windows 下不提供自动下载（需用 Docker Desktop / 手动安装 Erlang），macOS 下 PostgreSQL / MongoDB 不提供自动下载。详见各组件 `unsupported_platform_hint` 字段与「十、已知约束与注意事项」。

技术栈速览：

- **语言**：Python 3.9+
- **GUI 框架**：PySide6（Qt 6 官方 Python 绑定，LGPL 授权）
- **HTTP 客户端**：requests
- **压缩解压**：Python 标准库 `zipfile` + `tarfile` + 单二进制 / `.war` 单文件直接重命名
- **多线程**：QThread（后台下载、版本抓取，UI 不阻塞）
- **打包**：PyInstaller（单文件可执行 + macOS `.app`）
- **CI**：GitHub Actions 三平台自动构建发布（README 提及，仓库暂未包含 workflow 文件）
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
│   DOWNLOAD_RETRY_PER_URL / _get_first_working()            │
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
│  DOWNLOAD_RETRY_PER_URL / _get_first_working()            │
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
├── main.py                  # 主程序（含 UI 与全部逻辑，约 2700 行）
├── requirements.txt         # Python 依赖清单（PySide6、requests）
├── byte-tools.spec      # PyInstaller 打包配置
├── start-windows.bat        # Windows 一键启动脚本（检查 Python → 创建 .venv → 装依赖 → 启动 GUI）
├── README.md                # 中文说明（面向最终用户）
├── README_EN.md             # 英文说明
├── DEVELOPMENT.md           # 开发者文档（开发约定、R1 规则等，面向二次开发者）
├── CODE_WIKI.md             # 本文档（代码 Wiki，面向二次开发者）
├── LICENSE                  # MIT 许可证
├── .gitignore               # Git 忽略规则
└── assets/                  # 静态资源（PyInstaller 打包时通过 datas 一并打入）
    ├── byte-tools.png         # 应用窗口图标 + 截图
    ├── wechat.png           # 微信收款码
    ├── alipay.png           # 支付宝收款码
    └── qq.png               # QQ 收款码
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
├── mongodb/                         # Linux/Mac only
├── postgresql/                      # Linux/Mac only
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
| `MIRROR_BASES` | List[tuple] | R1 国内镜像源基址清单，按稳定性排序：huaweicloud / tuna / aliyun / nju / ustc / sjtug |
| `DOWNLOAD_PROBE_TIMEOUT` | int | R1 参数：单 URL 探测超时 5 秒 |
| `DOWNLOAD_TIMEOUT` | int | R1 参数：单 URL 下载连接超时 30 秒 |
| `DOWNLOAD_RETRY_PER_URL` | int | R1 参数：单 URL 内重试次数 2 |
| `human_size(num)` | func | 字节数 → `"1.5 MB"` 可读字符串 |
| `ensure_dir(path)` | func | 确保目录存在（`mkdir -p` 语义） |
| `_get(url, timeout=10)` | func | 带自动重试 + SSL 降级的 HTTP GET（重试 3 次，指数退避） |
| `_probe_version(exe, args)` | func | 调用可执行文件抓取版本号字符串，失败返回空串 |
| `_get_first_working(urls, timeout=10)` | func | R1 公共辅助：按 urls 顺序依次 GET，第一个成功的返回 Response，全失败抛 RuntimeError |

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
| `path_subdir` | str | 需加入 PATH 的子目录，一般为 `"bin"`，Windows 上 Python 是 `"Scripts"` |
| `exec_name` | Optional[str] | 用于探测的可执行文件名（不含扩展名）；jenkins.war 之类非命令行可执行文件设为 None |
| `version_args` | List[str] | 探测版本号的命令行参数，默认 `["--version"]` |
| `versions` | List[ComponentVersion] | 该组件的所有可用版本 |
| `installer_mode` | bool | 是否安装器模式（如 Miniconda 走 `.exe` / `.sh` 静默安装） |
| `installer_args` | Dict[str, List[str]] | 按操作系统键取的安装器静默参数 |
| `unsupported_platform_hint` | Optional[str] | 平台不支持自动下载时的友好提示文本（如 Docker 在 Windows 提示用 Docker Desktop；为 None 表示该平台支持） |

方法：
- `install_dir(version)` → 该版本的解压安装目录 `CONFIG_DIR/<key>/<key>-<version>`
- `exec_path_in_home(home)` → 在指定 `XXX_HOME` 下查找可执行文件，依次尝试 `path_subdir`/`bin`/`Scripts`/`condabin`/根目录
- `detect()` → **核心探测逻辑**，返回 `DetectResult`

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
| `_adoptium_jdk_url(version)` | JDK | 拼接 Adoptium latest binary API，按 `IS_ARM` 切换 mac/linux 架构 |
| `_maven_urls(v)` | Maven | Apache 归档目录多镜像故障转移 |
| `_tomcat_urls(v)` | Tomcat | 按主版本号 `v.split(".", 1)[0]` 拼接 tomcat-<major> 路径 |
| `_mysql_urls(v)` | MySQL | 区分 macOS ARM/x64；Linux 走 `.tar.xz` |
| `_python_urls(v)` | Python | Windows 走 embed-amd64.zip；mac/Linux 走 .tgz |
| `_node_urls(v)` | Node.js | 按 `IS_ARM` 选择 macOS arm64/x64 包 |
| `_git_urls(v)` | Git | Windows 走 MinGit 便携版；mac/Linux 用源码 tar.gz 占位 |
| `_conda_urls(v)` | Miniconda | 按 `IS_ARM` 选择 macOS arm64/x86_64 .sh |
| `_go_urls(v)` | Go | go.dev/dl 多镜像，按 OS/arch 拼接 |
| `_gradle_urls(v)` | Gradle | services.gradle.org 多镜像 |
| `_bun_urls(v)` | Bun | GitHub Releases 多镜像 |
| `_docker_urls(v)` | Docker | 仅 Linux/Mac 返回列表；Windows 返回空（unsupported_platform_hint 引导） |
| `_mongodb_urls(v)` | MongoDB | 仅 Linux/Mac；macOS 无自动下载 |
| `_postgresql_urls(v)` | PostgreSQL | 仅 Linux/Mac；macOS 无自动下载 |
| `_kubectl_urls(v)` | kubectl | dl.k8s.io 多镜像；Windows .exe / Linux-Mac 无扩展名单二进制 |
| `_jenkins_urls(v)` | Jenkins | get.jenkins.io 多镜像；三平台都是 jenkins.war 单文件 |
| `_rabbitmq_urls(v)` | RabbitMQ | GitHub Releases；Windows 无（依赖 Erlang） |
| `_kafka_urls(v)` | Kafka | Apache 归档目录多镜像 |
| `_rocketmq_urls(v)` | RocketMQ | Apache 归档目录多镜像 |
| `_pulsar_urls(v)` | Pulsar | Apache 归档目录多镜像 |
| `_activemq_urls(v)` | ActiveMQ | Apache 归档目录多镜像 |
| `_nacos_urls(v)` | Nacos | GitHub Releases 多镜像 |
| `_seata_urls(v)` | Seata | GitHub Releases 多镜像 |
| `_elasticsearch_urls(v)` | Elasticsearch | elastic.co 多镜像 |

辅助：
- `_STD_ARCHIVE`：标准归档类型表 `{"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"}`
- `_cv(version, url_map)`：快速构造一个用标准归档类型的 `ComponentVersion`

### 4.4 版本抓取器（`FETCHERS` 字典）

每个组件对应一个 `fetch_xxx_versions()` 函数，启动时由后台线程并发调用，向各官网 API / 归档索引拉取真实可用版本列表。**所有抓取请求同样走 R1 镜像优先**（先国内镜像索引页，失败切官网）。

| 函数 | 数据源 | 抓取方式 |
|------|--------|---------|
| `fetch_jdk_versions()` | `api.adoptium.net/v3/info/available_releases` | JSON，合并 `available_releases` 与 `available_lts_releases`，给 LTS 版本打 `display_label` |
| `fetch_maven_versions()` | `archive.apache.org/dist/maven/maven-3/` | HTML，正则 `href="(3\.\d+\.\d+)/"` |
| `fetch_tomcat_versions()` | `archive.apache.org/dist/tomcat/tomcat-{11,10,9}/` | HTML，正则逐主版本扫描 |
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
- `_try_download(url)` 单源下载：`requests.get(stream=True, timeout=DOWNLOAD_TIMEOUT)`，按 `_CHUNK_SIZE=64KB` 写 `.part` 临时文件，成功后 `replace` 为 `dest`
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
| `set_windows_user_env(name, value)` | Windows | 用 `winreg` 写 `HKCU\Environment`（绕过 setx 1024 字符限制），同时 `setx` 通知系统刷新；含 `%` 用 `REG_EXPAND_SZ`，否则 `REG_SZ` |
| `append_windows_path(entry)` | Windows | 读 `HKCU\Environment\Path`，按 `;` 分割去重追加 |
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

状态胶囊三态（`_detect_status` 设置）：
- 🟢 `✓ 已配置（PATH）· <version>` — 系统已能找到，禁用"配置环境变量"按钮
- 🟠 `● 已下载，未配置` — 本地已解压但环境变量未设
- 🔴 `○ 未安装` — 完全没有

关键方法：
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
2. **标题栏**（固定高度 48）：应用名 + GitHub 按钮 + "⟳ 刷新版本"按钮 + 打赏按钮 ♥ + 最小化 — / 最大化 ▢ / 关闭 ×
3. **主体 QSplitter（垂直）**：
   - 上部 `QScrollArea` + 卡片列表 `ComponentCard`
   - 下部日志区 `QTextEdit`（深色主题、等宽字体）
4. **底部状态栏**：显示当前系统信息、工作目录与 `组件总数：N 个`（N=24，方便用户一眼掌握支持范围）

无边框窗口拖动：
- `mousePressEvent` 在标题栏区域按下左键时记录 `_drag_pos`
- `mouseMoveEvent` 持续移动窗口
- `mouseDoubleClickEvent` 双击标题栏切换最大化

关键方法：
- `_start_fetch_versions()` — 从各官网并发拉取版本列表。若仍有 worker 运行则提示；否则清理旧 worker，为每个有 fetcher 的卡片启动一个 `VersionFetchWorker`（24 个并发），计数器 `_fetch_pending` 等所有完成后再恢复按钮
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
| `MainWindow.btn_refresh.clicked` | `MainWindow._start_fetch_versions` | 用户点"刷新版本" |
| `MainWindow.btn_github.clicked` | `QDesktopServices.openUrl(GITHUB_URL)` | 用户点 GitHub |
| `MainWindow.btn_donate.clicked` | `MainWindow._on_donate_clicked` | 用户点打赏 |
| `ComponentCard.btn_install.clicked` | `ComponentCard.on_install_clicked` | 用户点"下载并安装" |
| `ComponentCard.btn_configure.clicked` | `ComponentCard.on_configure_clicked` | 用户点"配置环境变量" |
| `ComponentCard.btn_cancel.clicked` | `ComponentCard.on_cancel_clicked` | 用户点"取消" |
| `ComponentCard.version_combo.currentIndexChanged` | `ComponentCard._on_index_changed` | 下拉框选中变化 |

### 5.4 关键函数索引

| 函数 | 行号附近 | 职责 |
|------|---------|------|
| `human_size(num)` | ~105 | 字节数转可读字符串 |
| `ensure_dir(path)` | ~114 | 确保目录存在 |
| `MIRROR_BASES` | ~326 | R1 国内镜像源基址常量清单（6 个镜像） |
| `DOWNLOAD_PROBE_TIMEOUT / DOWNLOAD_TIMEOUT / DOWNLOAD_RETRY_PER_URL` | ~336 | R1 故障转移参数常量 |
| `_get_first_working(urls, timeout=10)` | ~341 | R1 公共辅助：按 urls 顺序依次 GET，第一个成功的返回 |
| `_probe_version(exe, args)` | ~221 | 调用可执行文件抓版本号 |
| `_get(url, timeout=10)` | ~343 | 带重试 + SSL 降级的 HTTP GET |
| `_sort_semver_desc(vs)` | ~374 | 语义化版本倒序排序 |
| `_fetch_github_releases_versions(repo, prefix)` | ~2043 | R1 公共辅助：抓取 GitHub Releases 版本列表（Nacos/Seata/RabbitMQ 等复用） |
| `_fetch_apache_versions(key)` | ~1934 | R1 公共辅助：抓取 Apache 项目版本列表（Kafka/RocketMQ/Pulsar/ActiveMQ 复用） |
| `build_components()` | ~2214 | 构造 24 个组件的默认（离线）清单，全部用 `url_list_map` 走 R1 多源 |
| `extract_archive(archive, extract_to)` | ~860 | 解压 zip/tar.gz/tar.xz + 单二进制 + .war 单文件 |
| `DownloadWorker(urls, dest)` | ~2624 | R1 多源故障转移下载线程 |
| `main()` | ~末尾 | 程序入口 |

---

## 六、核心流程

### 6.1 启动流程

```
main()
  ├─ QApplication 配置高 DPI
  ├─ ensure_dir(CONFIG_DIR)
  └─ MainWindow()
       ├─ setWindowIcon(assets/byte-tools.png)
       ├─ build_components()           # 构造 24 个组件的默认清单（全部用 url_list_map 走 R1 多源）
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
       │    │    ├─ requests.get(stream=True, timeout=DOWNLOAD_TIMEOUT)
       │    │    ├─ 循环 r.iter_content(chunk_size=64KB)
       │    │    │    ├─ 检查 _cancel 标志
       │    │    │    ├─ 写入 .part 临时文件
       │    │    │    └─ progress.emit(downloaded, total)
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
  └─ for card in cards:                       # 24 张卡片
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
| `subprocess` | 调用可执行文件抓版本号、运行安装器、`setx` |
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

- **网络**：需访问对应组件的官方下载源（Adoptium API、Apache 归档、python.org、nodejs.org、GitHub API、repo.anaconda.com、go.dev、services.gradle.org、dl.k8s.io、get.jenkins.io、elastic.co 等）。`_get` 自带 3 次重试 + 第 3 次关闭 SSL 校验，应对企业代理 MITM 场景；下载流程额外走 R1 国内镜像优先（MIRROR_BASES）
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
- `hidden_imports`：显式声明 PySide6 子模块和 requests 依赖链
- `excludes`：排除 `tkinter` / `test` / `PySide6.QtNetwork` 等不需要的大模块，减小体积
- `console=False`：GUI 应用，不显示控制台
- `upx=False`：UPX 在 macOS 上会导致启动崩溃，统一禁用
- macOS 走 `BUNDLE` 生成 `.app`，`bundle_identifier=com.rgh.byte-tools`

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

直接到 [Releases](https://github.com/vfaner/byte-tools/releases/latest) 下载对应平台的二进制：

| 系统 | 文件 | 说明 |
|------|------|------|
| Windows | `byte-tools.exe` | 双击运行 |
| macOS (Apple Silicon) | `byte-tools-macos-arm64.zip` | 解压后双击 `.app` |
| macOS (通用) | `byte-tools-macos.zip` | 同上 |
| Linux (x64) | `byte-tools-linux-x64` | `chmod +x` 后执行 |

首次启动提示：
- macOS：未签名，需到「系统设置 → 隐私与安全性」点"仍要打开"，或 `xattr -cr byte-tools.app`
- Windows：SmartScreen 弹窗点"更多信息 → 仍要运行"
- Linux：双击无响应时改用终端 `chmod +x ... && ./...`

### 8.2 Windows 一键启动（start-windows.bat）

仓库根目录提供 `start-windows.bat`，双击或在终端执行即可，**无需手动管理虚拟环境和依赖**：

```bat
start-windows.bat
```

脚本流程（详见 [start-windows.bat](./start-windows.bat)）：
1. 定位 Python 解释器（优先 `py launcher`，回退 `python.exe`）
2. 校验 Python 版本 ≥ 3.9（PySide6 6.6+ 要求）
3. 检查 / 创建项目根目录 `.venv`（已存在则跳过）
4. 用清华 TUNA PyPI 镜像（`https://pypi.tuna.tsinghua.edu.cn/simple`）安装 `requirements.txt` 依赖（符合 R1 国内镜像优先原则）
5. 失败时回退到阿里云 PyPI 镜像
6. 用 `.venv` 内的 Python 启动 `main.py`

> 参数化设计：脚本顶部 `PY_MIN_MAJOR` / `PY_MIN_MINOR` / `PIP_INDEX_URL` / `PIP_INDEX_URL_BACKUP` / `VENV_DIR` 为可配置参数，便于按需修改。

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

#### GitHub Actions 三平台自动发布（README 提及）

```bash
git tag v1.0.1
git push origin v1.0.1
```

推 tag 触发 `.github/workflows/build-and-release.yml`（仓库暂未包含此文件），在 Windows / macOS / Linux 三个 runner 上分别打包并上传到对应 Release。

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
                url_list_map=_jdk_urls(v),  # ← R1：用 url_list_map 而非 url_map
                archive_map={"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"},
            )
            for v in ("22", "21", "17", "11", "8")  # ← 在此增减版本
        ],
    )
)
```

> 注意：`versions` 只是**离线默认清单**。启动时后台会自动向官方 API 拉取真实版本覆盖此清单，所以"修改默认清单"主要影响离线场景。

### 9.2 新增一个全新组件（R1 多源故障转移配置）

新增组件**必须**遵守 [DEVELOPMENT.md](./DEVELOPMENT.md) R1 规则：每个组件**至少 2 个国内镜像 + 末位官网**。

1. 写 URL 构造器，返回 `Dict[str, List[str]]`（按 OS 键映射的 URL 列表，镜像在前，官网末位）：

```python
def _foo_urls(v: str) -> Dict[str, List[str]]:
    """
    构造 foo 组件的 R1 多源 URL 列表。

    入参 v: str   版本号
    返回: Dict[str, List[str]]  按 OS 键映射的 URL 列表（国内镜像在前 + 末位官网）
    """
    # 镜像基址从 MIRROR_BASES 取，不要硬编码
    mirrors = MIRROR_BASES  # huaweicloud / tuna / aliyun / nju / ustc / sjtug
    file = f"foo-{v}-bin"
    win, mac, linux = [], [], []
    for _, base in mirrors:
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
6. UI 会自动出现一张新卡片，无需改动

> **R1 硬性要求**（见 [DEVELOPMENT.md](./DEVELOPMENT.md) R1.1）：新增组件未配置 ≥2 个国内镜像地址，不予合入。

### 9.3 更换 / 增减镜像源

镜像源基址**集中维护**在 `MIRROR_BASES` 常量，**严禁**散落在各 URL 构造器里硬编码：

```python
MIRROR_BASES: List[tuple] = [
    ("huaweicloud", "https://repo.huaweicloud.com"),       # M1，覆盖最广
    ("tuna",        "https://mirrors.tuna.tsinghua.edu.cn"),  # M2
    ("aliyun",      "https://mirrors.aliyun.com"),        # M3
    ("nju",         "https://mirrors.nju.edu.cn"),        # M4
    ("ustc",        "https://mirrors.ustc.edu.cn"),      # M5
    ("sjtug",       "https://mirrors.sjtug.org"),         # M6
]
```

调整顺序 / 增删镜像源统一改这一处即可。故障转移参数同理集中在 `DOWNLOAD_PROBE_TIMEOUT` / `DOWNLOAD_TIMEOUT` / `DOWNLOAD_RETRY_PER_URL`。

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
  - **macOS** 下 **PostgreSQL** 不支持自动下载（建议用 Homebrew 或 Postgres.app）
  - **macOS** 下 **MongoDB** 不支持自动下载（建议用 Homebrew 或 Docker）

### 10.2 环境变量写入

- **Windows**：默认写 **用户级** 变量（`HKCU\Environment`），通常不需要管理员权限；若需写系统级需改 `winreg.HKEY_LOCAL_MACHINE`
- **Windows PATH 长度**：`setx` 有 1024 字符限制，本项目用 `winreg` 直写注册表规避；但用户级 PATH 仍受系统限制
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
- 不做下载文件校验（无 checksum 验证），用户对下载内容自行负责

### 10.9 R1 多源故障转移注意事项

- **404 等不可恢复错误不内部重试**：单 URL 返回 4xx 状态码（404 最常见）说明该镜像路径不存在，`_try_download` 立即抛错并切到 `url_list_map` 下一个 URL，不在该 URL 上重试 `DOWNLOAD_RETRY_PER_URL` 次，避免浪费时间（见 [DEVELOPMENT.md](./DEVELOPMENT.md) R1.4）
- 镜像源路径规则差异：不同镜像（华为云 / 清华 / 阿里云）对同一项目的目录结构可能略有差异，URL 构造器需按各镜像实际路径拼接，不能假设所有镜像同构
- 全部源失败时 `DownloadWorker.finished_fail` 携带汇总错误信息（每个源的失败原因列表），用户在日志区可见全部尝试过的源
- 旧 `url_map` 字段仍保留向后兼容：极少数组件若未升级到 R1 多源模式，`urls_for_current()` 会把单 URL 包成单元素列表返回，下载逻辑一致
- 单二进制组件（kubectl 无扩展名）在 Linux/Mac 下 `_on_download_ok` 会 `chmod +x`；Jenkins `.war` 单文件直接重命名落位，不解压

---

## 附录：关键文件快速索引

| 想了解 | 看 |
|--------|----|
| 项目整体说明（用户视角） | [README.md](./README.md) |
| 开发约定与 R1 规则 | [DEVELOPMENT.md](./DEVELOPMENT.md) |
| 代码 Wiki（本文档） | [CODE_WIKI.md](./CODE_WIKI.md) |
| 全部源码 | [main.py](./main.py) |
| 依赖清单 | [requirements.txt](./requirements.txt) |
| Windows 一键启动脚本 | [start-windows.bat](./start-windows.bat) |
| 打包配置 | [byte-tools.spec](./byte-tools.spec) |
| 忽略规则 | [.gitignore](./.gitignore) |
| MIT 许可证 | [LICENSE](./LICENSE) |
| 静态资源（窗口图标 + 收款码） | [assets/](./assets) |
