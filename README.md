# 字节-开发环境与工具自动安装 (byte-tools)

<p align="center">
   <img src="assets/byte-tools.png" alt="byte-tools 软件图标" height="150" width="150"/>
</p>

<p align="center">
  一款基于 <b>Python + PySide6</b> 的跨平台桌面 GUI 工具<br/>
  一键完成 <b>下载 → 解压 → 环境变量配置</b> 全流程，让开发环境搭建不再是重复劳动
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="python"/>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg" alt="platform"/>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="license"/>
  <img src="https://img.shields.io/badge/GUI-PySide6-brightgreen.svg" alt="pyside6"/>
  <a href="https://github.com/jilong2026/byte-tools/releases"><img src="https://img.shields.io/github/v/release/jilong2026/byte-tools?color=orange" alt="release"/></a>
</p>

---

## 📥 下载即用（推荐）

> **不需要 Python 环境，不需要克隆源码，双击即可运行。**

请到 **[Releases 页面](https://github.com/jilong2026/byte-tools/releases/latest)** 下载对应操作系统的最新版本：

| 系统 | 下载文件 | 说明 |
|------|----------|------|
| 🪟 **Windows** | [`byte-tools.exe`](https://github.com/jilong2026/byte-tools/releases/latest/download/byte-tools.exe) | 双击运行，无需安装 |
| 🍎 **macOS (Apple Silicon)** | [`byte-tools-macos-arm64.zip`](https://github.com/jilong2026/byte-tools/releases/latest/download/byte-tools-macos-arm64.zip) | 解压后双击 `byte-tools.app` |
| 🐧 **Linux (x64)** | [`byte-tools-linux-x64`](https://github.com/jilong2026/byte-tools/releases/latest/download/byte-tools-linux-x64) | `chmod +x` 后直接运行 |

> **Intel 芯片 Mac 用户注意**：自 v1.0.5 起不再提供 Intel 通用包（GitHub 已下线 Intel runner），Intel 机器请参考下方[快速开始](#-快速开始)从源码运行。

### 首次启动提示

- **macOS**：由于未做代码签名，首次打开时系统可能提示"无法验证开发者"。请到「系统设置 → 隐私与安全性」下方点击 **"仍要打开"**；或用 `xattr -cr byte-tools.app` 移除隔离属性。
- **Windows**：Defender / SmartScreen 可能弹出"未识别应用"，点击 **"更多信息 → 仍要运行"** 即可。
- **Linux**：如果双击无响应，请在终端执行 `chmod +x byte-tools-linux-x64 && ./byte-tools-linux-x64`。

> 💡 只想看看代码 / 自己二次开发？往下翻到 [开发者指南](#-快速开始)。

---

## 📖 目录

- [下载即用](#-下载即用推荐)
- [开发背景](#-开发背景)
- [项目描述](#-项目描述)
- [功能特性](#-功能特性)
- [支持的组件](#-支持的组件)
- [环境要求](#-环境要求)
- [快速开始](#-快速开始)（源码开发者）
- [使用说明](#-使用说明)
- [截图预览](#-截图预览)
- [配置与自定义](#-配置与自定义)
- [目录结构](#-目录结构)
- [常见问题（FAQ）](#-常见问题faq)
- [技术栈](#-技术栈)
- [支持作者](#-支持作者)
- [许可证](#-许可证)

---

## 🌱 开发背景

每次入职新公司、拿到一台新电脑、或者给同事讲解怎么搭建后端 / 前端开发环境，都要重复一系列繁琐的步骤：

1. **找官网** —— Oracle 现在要登录才能下 JDK？Adoptium Temurin 是哪个包才对？MySQL 官方的 zip 藏在哪个二级页面？
2. **对系统 / 架构** —— macOS 是 Intel 还是 Apple Silicon？Linux 用 glibc 哪个版本？
3. **解压 + 放到"正确"的位置** —— 一堆 `C:\Program Files\...` 还是 `~/tools/...` 的目录规划。
4. **配置环境变量** —— Windows 上要点开"高级系统设置 → 环境变量 → 用户变量 / 系统变量 → 新建"；macOS/Linux 要区分 `.zshrc`、`.bash_profile`、`.bashrc`、`.profile` 里到底写在哪个才生效。
5. **验证** —— 打开新终端 `java -version`、`mvn -v` …… 一个不对就重来。

一台电脑做完至少半小时，多台电脑或者带新人上手时更是重复劳动。**能不能把这些交给一个工具？** 于是有了这个项目：

> 让「新机器 → 一套完整开发环境」这件事变成 **点几下鼠标** 就搞定。

---

## 📌 项目描述

**byte-tools** 是一款开源的桌面小工具，目标是把开发者最常用的语言运行时、构建工具、中间件的下载与配置全部自动化。

它做了这几件事：

- ✅ **智能识别系统**：自动判断 Windows / macOS / Linux + CPU 架构（x64 / arm64），挑选正确的官方分发包
- ✅ **动态版本抓取**：启动时向各官方 API / 归档索引拉取最新可用版本列表（Adoptium、Apache Maven / Tomcat、python.org、Node.js dist、GitHub Releases、Anaconda Repo），不再依赖硬编码
- ✅ **可搜索下拉框**：版本列表长？直接键入 `21` / `3.12` / `LTS` 实时过滤
- ✅ **自动检测已装环境**：如果系统已经有 `java` / `mvn` / `python`，会显示 ✓ 已配置 状态并禁用"配置环境变量"按钮，避免重复写入
- ✅ **一键下载 → 解压 → 配环境变量**：Windows 下走 `winreg`，macOS/Linux 下带 marker 幂等写入 shell 配置文件
- ✅ **安装器模式**：Miniconda 这类 `.exe` / `.sh` 安装器，工具会以静默参数自动执行安装
- ✅ **现代化 UI**：无边框自定义标题栏、卡片式布局、渐变进度条、彩色分级日志、状态胶囊标签

---

## ✨ 功能特性

| 特性 | 说明 |
|------|------|
| 🖥️ **跨平台** | 一份代码同时支持 Windows / macOS / Linux；ARM64 分支自动切换（如 Apple Silicon 下 JDK 走 aarch64、Node 走 arm64） |
| 📦 **一键装配** | 内置 **24 个** 常用开发组件，从下载 → 解压 → 环境变量配置全流程自动化 |
| 🇨🇳 **国内镜像优先** | v2.0 起内置 **11 家大陆镜像基址**（华为云 repo / 华为云 mirrors / 清华 TUNA / 阿里云 / 南大 / 中科大 / 北外 / 腾讯云 / 上交 / npmmirror / DaoCloud files）+ **3 个 GitHub 加速器**（ghproxy.net / gh-proxy.com / ghfast.top），多源故障转移，全部失败后才回退官网，全程中文日志，**无需手动改 URL**。个别组件没有大陆源：mongodb、postgresql 官网单源；nacos、bun 与 git 的 macOS/Linux 源码包走 GitHub 加速器；kubectl 优先 DaoCloud 代理；seata 走 Apache 分发目录（八家大陆镜像）。详见「配置与自定义 → 更换下载镜像」 |
| 🛡️ **下载可靠性** | 所有请求固定携带专用 User-Agent（部分高校镜像站会屏蔽默认 UA 返回 403）；下载完成后校验实际字节数，遇到镜像站"假 200 空文件"自动换下一个源，不会留下坏包 |
| 🌐 **动态版本抓取** | 后台线程并发调用各组件官方 API / 索引，拉取最新可用版本，抓取失败自动降级到内置默认清单 |
| 🔍 **智能检测** | 优先检查 `XXX_HOME` 环境变量，然后回退到 `PATH` 中的可执行文件；探测到即视为已配置 |
| 🎯 **可搜索下拉框** | 版本多？直接键入关键字实时过滤，回车即可选中 |
| 🛠️ **环境变量写入** | Windows：`winreg` 直写注册表 + 异步广播 `WM_SETTINGCHANGE`（不用 `setx`，避免 1024 字符截断）；macOS/Linux：写入带标记的 shell 配置块，幂等更新 |
| 🧹 **卸载与残留清理** | 卸载以磁盘上真正装着的目录为准，同步清理 `XXX_HOME` 与该组件目录内的 PATH 条目；标题栏「清理残留 PATH」可一键删除指向本工具目录但已不存在的死条目 |
| 🚀 **安装器模式** | 支持 `.exe` / `.sh` 静默安装（Miniconda），无弹窗交互 |
| 📊 **实时反馈** | 进度条显示下载速度和大小，可随时取消；日志区彩色分级输出 |
| 🎨 **现代化界面** | 圆角卡片 + 阴影、渐变进度条、状态胶囊标签、无边框自定义窗口、窗口图标（任务栏/Alt+Tab 可见）、底部状态栏显示"组件总数：24 个" |
| 🧠 **偏好记忆** | 记住上一次每个组件选择的版本，下次启动自动恢复 |
| 💰 **打赏支持** | 内置微信 / 支付宝 / QQ 二维码，一键支持作者 |

---

## 📦 支持的组件

> v2.0 起组件数从 8 个扩展至 **24 个**，覆盖语言运行时 / 构建工具 / 应用服务器 / 数据库 / 容器与编排 / CI/CD / 消息队列 / 服务发现 / 搜索引擎 / 版本控制 / Python 发行版等常见开发场景。

界面按 **三个 Tab 页**（顶部横向，标题自带组件数量）分组展示（下方小节仍按技术类别详述）：

| Tab | 数量 | 归类标准 | 组件 |
|-----|------|----------|------|
| **开发环境** | 9 | 装完进 PATH，直接用来写 / 编译 / 打包代码 | JDK、Python、Node.js、Go、Bun、Miniconda、Git、Maven、Gradle |
| **开发软件** | 12 | 本地跑起来给项目当依赖的服务 | Tomcat、MySQL、MongoDB、PostgreSQL、Elasticsearch、Nacos、Seata、Kafka、RocketMQ、Pulsar、ActiveMQ、RabbitMQ |
| **其它软件** | 3 | 不参与写代码的容器 / 编排 / CI 外围 | Docker、kubectl、Jenkins |

> 想调整归类：只改 `main.py` 里的 `COMPONENT_CATEGORY_OF` 一行即可，界面自动跟着变。

### 语言运行时

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **JDK** | JDK (Temurin) | `JAVA_HOME` | `java -version` | 21 / 17 (LTS) / 11 / 8（下载前先点"⟳ 刷新版本"，详见表格下方提示） |
| **Python** | Python | — (走 PATH) | `python --version` | 3.12 / 3.11 / 3.10 / 3.9 |
| **Node.js** | Node.js | `NODE_HOME` | `node --version` | 20 LTS / 18 LTS / 16 |
| **Go** | Go (golang) | `GOPATH` / `GOROOT` | `go version` | 1.24.x / 1.22.x |
| **Bun** | Bun | — (走 PATH) | `bun --version` | 1.x |

### 构建工具

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **Maven** | Apache Maven | `MAVEN_HOME` | `mvn -v` | 3.9.x / 3.8.x |
| **Gradle** | Gradle | `GRADLE_HOME` | `gradle -v` | 8.x / 7.x |

### 应用服务器

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **Tomcat** | Apache Tomcat | `CATALINA_HOME` | `catalina version` | 10.1 / 9.0 / 8.5 |

### 数据库

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **MySQL** | MySQL Server | `MYSQL_HOME` | `mysql --version` | 8.0.x（阿里 / 华为云镜像 + 官网） |
| **MongoDB** | MongoDB | — (走 PATH) | `mongod --version` | 8.0.x / 8.0.0（支持 Windows / Linux；⚠️ macOS 不支持自动下载，请用 `brew install mongodb-community`；实测无国内镜像，官网单源） |
| **PostgreSQL** | PostgreSQL | `PG_HOME` | `psql --version` | 17.x / 16.x（⚠️ 仅 Windows 支持自动下载，Linux 请用发行版包管理器、macOS 请用 `brew install postgresql`；实测无国内镜像，官网单源） |

### 容器与编排

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **Docker** | Docker Desktop | — (走 PATH) | `docker --version` | 27.x / 26.x（⚠️ Windows 不支持自动下载，须用安装器，请去 docker.com 手动下载） |
| **kubectl** | Kubernetes CLI | — (走 PATH) | `kubectl version --client` | 1.31.x / 1.30.x（三平台均支持；优先 DaoCloud 代理源；Linux/macOS 下载的是无扩展名单文件，需 `chmod +x` 后运行） |

### CI/CD

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **Jenkins** | Jenkins | `JENKINS_HOME` | `jenkins --version` | 2.x / LTS |

### 消息队列

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **RabbitMQ** | RabbitMQ | `RABBITMQ_HOME` | `rabbitmqctl version` | 4.0.x / 3.13.x（⚠️ Windows 不支持自动下载，依赖 Erlang，请去 rabbitmq.com 手动下安装器） |
| **Apache Kafka** | Apache Kafka | `KAFKA_HOME` | `kafka-server-start.sh --version` | 4.1.x / 3.9.x |
| **Apache RocketMQ** | Apache RocketMQ | `ROCKETMQ_HOME` | `mqadmin version` | 5.x |
| **Apache Pulsar** | Apache Pulsar | `PULSAR_HOME` | `pulsar version` | 3.x |
| **ActiveMQ** | Apache ActiveMQ | `ACTIVEMQ_HOME` | `activemq --version` | 6.3.x / 5.18.x |

### 服务发现 / 事务

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **Nacos** | Nacos | `NACOS_HOME` | `sh startup.sh -m standalone` | 2.x（发布在 GitHub Releases，无真镜像，走 ghproxy.net / gh-proxy.com / ghfast.top 加速） |
| **Seata** | Seata | `SEATA_HOME` | `sh seata-server.sh -h` | 2.x（走 Apache 分发目录，华为云 / 清华 / 阿里 / 南大 / 北外 / 腾讯 / 中科大等八家大陆镜像） |

### 搜索引擎

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **Elasticsearch** | Elasticsearch | `ES_HOME` | `elasticsearch --version` | 9.x / 8.x（华为云镜像 + 官网；镜像只同步新版本，老版本由故障转移兜底） |

### 版本控制

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **Git** | Git | — | `git --version` | MinGit for Windows（华为云 / npmmirror 国内源优先）/ macOS、Linux 不提供自动下载（上游只有源码包，界面提示用 apt / dnf / yum / brew 安装） |

### Python 发行版

| 组件 | 显示名 | 环境变量 | 检测命令 | 默认版本 |
|------|--------|----------|----------|----------|
| **Miniconda** | Miniconda | `CONDA_HOME` | `conda --version` | py312 / py311 / py310 |

> 💡 启动应用后，点 **"⟳ 刷新版本"** 按钮会从各组件官方源拉取最新版本列表。抓取失败会自动回退到硬编码的内置清单，保证程序在离线环境下也可用。JDK 请特别注意：清华 / 南大镜像上要带 build 号的确切文件名，只有"刷新版本"后才能解析出来——**先点刷新，再下载**。

---

## 💻 环境要求

- **Python**：3.9 及以上
- **操作系统**：Windows 10 / 11、macOS 12+、Ubuntu 20.04+
- **网络**：需要能访问对应组件的下载源（如 Apache 归档、Adoptium API、Node.js dist 等）
- **磁盘**：视安装的组件而定，建议预留 3 GB 以上（JDK+Maven+Node+Python+MySQL 加起来约 1.5-2 GB）

---

## 🚀 快速开始

> 📌 **本节面向开发者 / 想二次开发的用户**。只想使用工具？请回到 [下载即用](#-下载即用推荐)。

### 0. Windows 用户一键启动（推荐）

项目根目录下提供两个中文一键脚本，**双击即可运行**，无需任何命令行操作：

| 脚本 | 作用 |
| --- | --- |
| `一键启动项目.bat` | 准备环境后直接启动 GUI（源码方式，改完代码立刻生效） |
| `一键打包exe.bat` | 准备环境后调用 PyInstaller，产出 `dist/byte-tools.exe` |

两者共用同一套自动装配流程：

1. 查找可用的 Python（要求 ≥ 3.9；优先 `py -3.12/3.13/…`，找不到再退到 `python`）
2. 复用已有的 `.venv`；缺失或损坏时自动创建 / 重建（`--clear`）
3. 依赖缺失时安装 `requirements.txt`，镜像顺序 **清华 TUNA → 阿里云 → 官方 PyPI**；打包脚本额外安装 PyInstaller
4. 启动 `main.py`，或按 `byte-tools.spec` 打包并在结束时显示产物大小与时间

```text
双击 一键启动项目.bat  →  自动配置 + 启动 GUI
双击 一键打包exe.bat   →  自动配置 + 生成 dist/byte-tools.exe
```

> 💡 脚本只读写项目目录内的 `.venv`，不会修改系统 PATH，也不会动系统全局 Python。
> 想脚本化调用可加参数 `nopause`（跑完不等待按键）。

### 手动方式（macOS / Linux 用户或想自定义者）

#### 1. 克隆项目

```bash
git clone https://github.com/yourname/byte-tools.git
cd byte-tools
```

#### 2. 创建虚拟环境（推荐）

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

#### 3. 安装依赖

```bash
pip install -r requirements.txt
```

依赖清单：

- `PySide6` — Qt for Python，提供跨平台 GUI
- `requests` — HTTP 请求，用于下载文件和抓取版本列表

#### 4. 启动应用

```bash
python main.py
```

首次启动会自动创建工作目录：

```
~/.env-tools/          # 所有下载的压缩包 / 解压后的组件都放这里
├── jdk/
│   ├── downloads/     # 原始压缩包
│   └── jdk-17/        # 解压后的 JDK
├── maven/
├── node/
└── ...
```

---

## 📝 使用说明

### 基本流程

1. **打开应用** → 主界面会显示所有支持的组件卡片，每个卡片右上角会显示 **当前系统检测结果**：
   - 🟢 `✓ 已配置（PATH）· openjdk version "17.0.10"` — 系统已能找到，无需再装
   - 🟠 `● 已下载，未配置` — 本地已有安装包，但环境变量未设置
   - 🔴 `○ 未安装` — 完全没有

2. **选择版本** → 点击版本下拉框：
   - 直接从列表点击选择
   - 或者输入关键字（如 `21`、`3.12`、`LTS`）实时过滤

3. **点击"下载并安装"**（一条龙流程） → 工具会自动依次执行：
   - ⬇️ 流式下载到 `~/.env-tools/<组件>/downloads/`（国内镜像优先、失败自动换源，可随时取消）
   - 📂 解压到 `~/.env-tools/<组件>/<组件>-<版本>/`（Miniconda 走静默安装器）
   - 🔧 自动写入 `XXX_HOME` 环境变量 + 把 `bin` 追加到 `PATH`
   - 🔄 自动刷新该卡片状态（无需再手动点"配置环境变量"）

4. **或点击"配置环境变量"** → 仅使用本地已下载的最新版本，执行环境变量配置（适合已手动下载好压缩包的场景）

5. **查看日志** → 底部日志区实时显示每一步的执行情况

### 环境变量生效方式

- **Windows**：新开命令行/PowerShell 窗口即可读到新的用户变量；已打开的窗口需要重启
- **macOS / Linux**：

  ```bash
  source ~/.zshrc        # 或 ~/.bashrc / ~/.bash_profile / ~/.profile
  ```

  或直接重开终端

### 验证方法

```bash
java -version
mvn -v
python --version
node -v
mysql --version
git --version
conda --version
```

---

## 📸 截图预览

<p align="center">
  <img src="assets/byte-tools-pt.png" alt="主界面" width="800"/>
</p>

界面元素说明：

- **顶部**：自定义标题栏，含应用图标（任务栏/Alt+Tab 可见）、GitHub 链接、打赏按钮、窗口控制（最小化 / 最大化 / 关闭）
- **中部**：每个组件一张卡片，展示名称、状态标签、版本下拉框（可搜索）、操作按钮、进度条
- **底部**：运行日志区，四色分级输出（info 灰、ok 绿、warn 橙、error 红），全程中文日志（含镜像切换/故障转移过程）
- **状态栏**：显示当前系统信息、工作目录，以及 **"组件总数：24 个"**（一眼掌握支持范围）

---

## 🔧 配置与自定义

### 修改 / 新增组件版本

打开 `main.py`，找到 `build_components()` 函数。每个组件的默认版本列表都在这里。如需新增或调整：

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
                url_map=_adoptium_jdk_url(v),
                archive_map={"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"},
            )
            for v in ("22", "21", "17", "11", "8")  # 加入 22
        ],
    )
)
```

> ⚠️ 提示：`versions` 只是**离线默认清单**。启动时后台会自动向官方 API 拉取真实版本，覆盖此清单。你也可以通过修改 `FETCHERS` 字典自定义抓取逻辑。

### 更换下载镜像

> **v2.0 起内置国内镜像优先 + 多源故障转移机制，普通用户无需手动改 URL。** 下面说明仅给想理解机制或做二次开发的用户参考。

工具目前内置 **11 家大陆镜像基址**（华为云 repo / 华为云 mirrors / 清华 TUNA / 阿里云 / 南大 / 中科大 / 北外 / 腾讯云 / 上交 / npmmirror / DaoCloud files），另有 **3 个 GitHub 加速器**（ghproxy.net / gh-proxy.com / ghfast.top；GitHub Releases 没有真镜像，只能走反向代理加速）。下载遵循 **"大陆源在前 → 多源故障转移 → 末位官网回退"** 规则：

1. 按顺序尝试各源，遇到 404 / 超时 / 连接失败立即切换到下一个
2. 全部大陆源失败后才回退到官网地址
3. 全程输出中文日志（哪个源失败、切换到哪个、最终用了哪个）
4. 两条可靠性保障：所有请求固定带 `byte-tools` 自定义 User-Agent（部分高校镜像站会屏蔽默认 UA 返回 403）；下载完成后校验实际字节数，遇到镜像站"假 200 空文件"自动换下一个源，不会留下坏包

少数组件的源策略不一样（2026-09-28 实测结论）：

- **mongodb、postgresql**：实测没有任何大陆镜像，官网单源；
- **nacos、bun 与 git 的 macOS/Linux 源码包**：无真镜像，走 3 个 GitHub 加速器，末位回退 GitHub 裸地址；
- **kubectl**：首位是 DaoCloud `files.m.daocloud.io` 代理（`dl.k8s.io` 直连路径不可改写，必须走它的 files 代理），末位才是官方 `dl.k8s.io`；
- **seata**：走 Apache 分发目录，华为云 / 清华 / 阿里 / 南大 / 北外 / 腾讯 / 中科大等八家大陆镜像；
- **jdk**：离线默认清单只有官网一条，清华 / 南大镜像的确切文件名要点"⟳ 刷新版本"后才解析——**先点刷新，再下载**。

效果：**国内用户无需手动修改任何 URL** 即可享受国内镜像加速，相比旧版"手动改 URL 函数"的方式体验大幅提升。

> 💡 下载失败时怎么办？先看底部日志里是哪个源失败、切到了哪个源；点"⟳ 刷新版本"可以让工具重新解析镜像上的最新版本与文件名，再重试下载。

> 📖 想了解镜像机制的完整技术实现（镜像清单配置、故障转移策略、Nacos/Bun 这类无真镜像组件如何用 GitHub 加速器，以及版本索引页为什么直连官网）？请查阅 [`DEVELOPMENT.md`](./DEVELOPMENT.md) 的 **R1 国内镜像优先规则** 章节。

### 修改工作目录

默认工作目录是 `~/.env-tools/`。在 `main.py` 顶部修改：

```python
CONFIG_DIR = Path.home() / ".env-tools"
```

---

## 📦 自行打包 / 发布新版本

项目已经配置好 PyInstaller 与 GitHub Actions，你可以：

### 本地打包（单平台）

Windows 用户直接双击根目录的 `一键打包exe.bat`（自动准备 `.venv` + PyInstaller）。
手动方式：

```bash
pip install pyinstaller
pyinstaller byte-tools.spec --noconfirm --clean
```

产物：
- Windows：`dist/byte-tools.exe`
- macOS：`dist/byte-tools.app`
- Linux：`dist/byte-tools`

> 🎨 Windows 产物已带项目图标（`assets/byte-tools.ico`，由 `assets/byte-tools.png` 转出的 16~256 七档尺寸）。换 logo 后重新生成 ICO 的方法见 [CODE_WIKI.md](./CODE_WIKI.md) 7.4；若覆盖打包后资源管理器仍是旧图标，那是 Windows 图标缓存，改个文件名或执行 `ie4uinit.exe -show` 即可刷新。

### 自动发布三平台版本（推荐）

推一个 tag 到 GitHub，`.github/workflows/release.yml` 会在 Windows / macOS / Linux 三个 runner 上分别打包，自动上传到对应 GitHub Release，并同步产物到 Gitee Release：

```bash
git tag v1.0.1
git push origin v1.0.1
```

几分钟后到 Releases 页面就能看到三个平台的产物（全自动发布，无需手动点 Publish）。

---

## 📁 目录结构

```
byte-tools/
├── main.py                             # 主程序（含 UI 与全部逻辑）
├── 一键启动项目.bat                # 一键脚本：自动装环境（.venv + 依赖）后启动 GUI
├── 一键打包exe.bat                 # 一键脚本：自动装环境后用 PyInstaller 产出 exe
├── requirements.txt                    # Python 依赖清单
├── byte-tools.spec                 # PyInstaller 打包配置
├── README.md                           # 中文说明（本文件）
├── README_EN.md                        # 英文说明
├── DEVELOPMENT.md                      # 开发者文档（含 R1 国内镜像优先规则等实现细节）
├── CODE_WIKI.md                        # 代码百科（类 / 模块 / 函数索引）
├── LICENSE                             # MIT 许可证
├── .gitignore                          # Git 忽略规则
├── .github/
│   └── workflows/
│       └── release.yml                 # 三平台自动构建 + 发布（含 Gitee 同步）
└── assets/                             # 静态资源
    ├── byte-tools-pt.png               # 主界面截图
    ├── byte-tools.png                  # 应用窗口图标
    ├── wechat.png                      # 微信收款码
    └── alipay.png                      # 支付宝收款码
```

---

## ❓ 常见问题（FAQ）

**Q1. 启动后下拉框显示"获取失败"？**
可能是网络原因或访问受限（如 GitHub API 在部分地区不稳定）。工具会自动回退到内置默认版本列表，仍然可以下载安装 —— 只是版本可能不是最新。**默认版本完全可用**。各组件默认就按国内镜像优先下载，源策略见「配置与自定义 → 更换下载镜像」章节。

**Q2. 下载卡在某个百分比不动？**
可能是网络原因或镜像限速。点击 **「取消」** 后重试，工具会自动换下一个源；反复失败时先看底部日志里是哪个源失败、切到了哪个源，也可以点"⟳ 刷新版本"重新解析镜像后再试（无需手动改 URL）。

**Q3. 提示环境变量写入失败？**
- Windows：请以"管理员身份"重新启动本程序（默认写入的是**用户级**变量，通常不需要管理员权限）
- macOS / Linux：确认你有 `~/.zshrc` 等文件的写入权限

**Q4. 已经存在旧的 `JAVA_HOME`，会被覆盖吗？**
会用最新一次安装的路径覆盖原有值；同时把新的 `bin` 目录追加到 `PATH`（不会重复追加）。

**Q5. MySQL 解压完成后能直接用吗？**
不能。MySQL 解压后还需要执行 `mysqld --initialize` 等初始化步骤。本工具只完成"下载 + 解压 + 环境变量"三步，不做数据库初始化。

**Q6. `.tar.xz` 归档能处理吗？**
可以，程序内置了 `tarfile.open("r:xz")` 逻辑（用于 MySQL Linux 版）。

**Q7. Windows 上 PATH 超过 1024 字符怎么办？**
工具不使用 `setx`（它有 1024 字符截断），一律用 `winreg` 直接写入 `HKCU\Environment`，再异步广播 `WM_SETTINGCHANGE` 通知其他进程；PATH 按单条目增删，不会用注册表的用户段覆盖当前进程的 PATH。

**Q8. Miniconda 静默安装到哪里？**
安装到 `~/.env-tools/conda/conda-<版本>/`，并把 `CONDA_HOME` 与 `bin/Scripts` 加入环境变量。

**Q9. 可以只做检测不做安装吗？**
可以。启动时工具就会检测所有组件的状态；如果所有组件都显示 ✓ 已配置，说明你的系统已经就绪，不需要再点任何按钮。

**Q10. 支持自动更新组件版本吗？**
点击卡片的下拉框会先看到内置版本，程序启动后后台自动请求官网并热更新列表。所以理论上"最新版本"是实时的（前提是能访问对应官网）。

**Q11. 为什么 Docker 在 Windows 提示"无可用下载地址"？**
Docker Desktop 必须使用其官方安装器（涉及 WSL2 / Hyper-V 集成、服务注册等系统级配置），不能简单走"下载 zip → 解压"流程。工具不会为 Windows 提供自动下载，会直接提示用户去 [docker.com](https://www.docker.com/products/docker-desktop/) 手动下载安装。Mac / Linux 用户则按各自平台正常下载。

**Q12. 为什么 RabbitMQ 在 Windows 不能自动下载？**
RabbitMQ 运行时依赖 Erlang，Windows 上必须先安装 Erlang 再装 RabbitMQ 服务端，属于典型的"安装器+服务注册"场景，超出本工具"binary 下载 + 解压"的范围。工具会引导用户去 [rabbitmq.com](https://www.rabbitmq.com/download.html) 下载官方安装器。

**Q13. 国内下载会很慢吗？**
不会。v2.0 起内置国内镜像优先规则：**11 家大陆镜像基址**（华为云 / 清华 TUNA / 阿里云 / 南大 / 中科大 / 北外 / 腾讯云 / 上交 / npmmirror / DaoCloud 等）+ **3 个 GitHub 加速器**，下载时按顺序尝试，遇到 404 / 超时自动切换下一个源，全程输出中文日志（哪个源失败、切换到哪个、最终用了哪个）。普通用户无需任何手动配置。少数组件没有大陆源：**mongodb、postgresql** 实测无任何大陆镜像，只能官网单源；**nacos、bun 与 git 的 macOS/Linux 源码包**走 GitHub 加速器。kubectl 以前是直连 `dl.k8s.io`，现已改为首选 DaoCloud `files.m.daocloud.io` 代理。下载失败时先看日志里哪个源失败，点"⟳ 刷新版本"可重新解析镜像。

**Q14. 点击"下载并安装"后还需要手动配置环境变量吗？**
不需要。"下载并安装"按钮是**一条龙流程**：下载 → 解压 → 自动写入 `XXX_HOME` / `PATH` 环境变量 → 刷新该卡片状态。整个流程跑完即视为安装完成，无需再点"配置环境变量"按钮。该按钮仅适合"已手动下载好压缩包、只想配置环境变量"的场景。

**Q15. MongoDB / PostgreSQL 为什么在部分平台不能自动下载？**
MongoDB 支持 Windows / Linux 自动下载；macOS 官方只提供源码或 Homebrew formula，没有可直接解压的二进制包，工具会提示用 `brew install mongodb-community` 安装。PostgreSQL 仅 Windows 支持自动下载（EnterpriseDB 二进制 zip 包），Linux 请用发行版自带包管理器（apt / yum / dnf）、macOS 用 `brew install postgresql`。另外这两个组件实测都没有大陆镜像，下载时只有官网一个源，国内速度偏慢属正常现象。

**Q16. Nacos / Bun 没有国内镜像，下载会不会很慢？**
这类组件发布在 GitHub Releases 上，国内访问 GitHub 速度不稳定。工具通过 [ghproxy.net](https://ghproxy.net/) / [gh-proxy.com](https://gh-proxy.com/) / [ghfast.top](https://ghfast.top/) 做 GitHub releases 加速代理，末位再回退 GitHub 裸地址，对用户透明，日志里会显示当前使用的代理源。git 的 macOS/Linux 源码包也走这条路线。（原先配的 `ghproxy.com` 与 `gh.idayer.com` 实测已停服，v2.0 起已替换。）注意 **Seata 已不走这条路线**：GitHub release 从 2.1.0 起不再带二进制附件，工具已改走 Apache 分发目录，由华为云 / 清华 / 阿里 / 南大 / 北外 / 腾讯 / 中科大等八家大陆镜像加速。

---

## 🛠️ 技术栈

- **Language**：Python 3.9+
- **GUI 框架**：[PySide6](https://doc.qt.io/qtforpython-6/)（Qt 6 官方 Python 绑定，LGPL 授权）
- **HTTP 客户端**：[requests](https://requests.readthedocs.io/)
- **压缩包解压**：Python 标准库 `zipfile` + `tarfile`
- **环境变量**：
  - Windows：`winreg` 直写注册表 + 异步广播 `WM_SETTINGCHANGE`（不用 `setx`）
  - macOS/Linux：写入 shell 配置文件（`.zshrc` / `.bash_profile` / `.bashrc` / `.profile`）
- **多线程**：`QThread` 后台下载与版本抓取，UI 不阻塞
- **架构**：单文件应用，`main.py` 内含 UI、数据类、业务逻辑

---

## 💖 支持作者

如果这个小工具对你有帮助，欢迎请作者喝杯咖啡 ☕：

<table>
  <tr>
    <td align="center">
      <img src="assets/wechat.png" alt="微信" width="200"/><br/>
      <b>微信</b>
    </td>
    <td align="center">
      <img src="assets/alipay.png" alt="支付宝" width="200"/><br/>
      <b>支付宝</b>
    </td>
  </tr>
</table>

也欢迎：

- ⭐ 给本项目点个 Star
- 🐛 提 Issue 反馈问题
- 🔀 提 PR 贡献代码
- 📢 分享给身边的朋友

---

## 📄 许可证

本项目采用 **MIT License** 开源发布，版权归作者 **rgh** 所有。

```
MIT License

Copyright (c) 2026 rgh

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

许可证全文亦可参考 <https://opensource.org/licenses/MIT>。

---

<p align="center">
  Made with ❤️ by <b>rgh</b><br/>
  <sub>如果觉得有用，别忘了给个 ⭐ Star！</sub>
</p>
