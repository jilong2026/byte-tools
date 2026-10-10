# byte-tools 开发文档

> 本文档面向本项目的二次开发者与维护者，记录开发约定、规则与设计指引。
> 新功能、新组件、新规则的引入必须先落入本文件，再写代码落地。

---

## 文档说明

- **适用范围**：本仓库所有 Python 源码改动、新增组件、URL 与下载逻辑改造
- **更新原则**：规则变化或新增规则必须先改本文档再改代码；代码与文档不一致时以本文档为准
- **与 README 的关系**：README.md 面向最终用户，本文档面向开发者
- **实测口径**：本文所有镜像路径都来自 2026-09-28 的在线 GET 实测（`User-Agent: byte-tools`，
  流式取响应头，判定标准 = 状态码 200 且 `Content-Length` 是真实包体）。**未经实测的地址一律视为假镜像**。

---

## 规则索引

- [规则 R1：国内镜像优先 + 多源故障转移](#规则-r1国内镜像优先--多源故障转移)
- [规则 R2：组件四类分组与界面 Tab](#规则-r2组件四类分组与界面-tab)
- [规则 R3：组件多版本与生效版本切换](#规则-r3组件多版本与生效版本切换)
- [规则 R4：一键脚本自举契约](#规则-r4一键脚本自举契约)
- [规则 R5：组件一键启动契约](#规则-r5组件一键启动契约)
- [规则 R6：前置运行时自举契约（缺 JDK / Erlang 由本工具装好）](#规则-r6前置运行时自举契约缺-jdk--erlang-由本工具装好)
- [规则 R7：单文件组件的落位文件名契约](#规则-r7单文件组件的落位文件名契约)
- [规则 R8：动态内容目录要同步进 prefix / BASE](#规则-r8动态内容目录要同步进-prefix--base)
- [规则 R9：非 ASCII 主机名下的服务节点名](#规则-r9非-ascii-主机名下的服务节点名)
- [规则 R10：启动后必须有可访问页面 + 启动日志必须给出地址](#规则-r10启动后必须有可访问页面--启动日志必须给出地址)

<!-- 后续新增规则在此追加索引 -->

---

## 规则 R1：国内镜像优先 + 多源故障转移

### R1.1 规则描述

所有组件的下载必须遵循以下优先级，**不得直接使用官网地址作为首选**：

1. **第一优先级**：中国大陆境内镜像加速地址
2. **故障转移**：第一个镜像不可用时按顺序切换到下一个国内镜像
3. **末位回退**：所有配置的国内镜像均失败后，才回退到组件官方下载地址

每个新组件**必须**配置 **≥2 个**国内镜像地址，否则不予合入。
确实凑不出 2 个源时，必须在 R1.5 表登记实测结论并保留官网单源，
**不得**用猜测的镜像路径凑数——假镜像地址只会让每次下载先白撞两轮 404。

**已登记的例外（2026-09-28 实测确认，不得再为其编造镜像）**：

| 组件 | 例外形态 | 实测依据 |
|------|----------|----------|
| `mongodb` | 大陆源 0 个，只有 `fastdl.mongodb.org` 官网单源 | 带 UA 复测：`repo.huaweicloud.com/mongodb/` 对二进制包名一律 404（只有 `mongo-cxx-driver` 这类 C++ 源码包）、`mirrors.huaweicloud.com/mongodb.org/` 直接 401；清华 `/mongodb/` 是 apt/yum 仓库；阿里云只有 `mongodb-upstart/` |
| `postgresql` | 大陆源 0 个，只有 `get.enterprisedb.com` 官网单源 | 清华没有 `/postgresql/` 目录（404）；华为云、阿里、南大的 `/postgresql/` 只有 `latest/`、`source/` 这类**源码 tarball**（`postgresql-18.2.tar.gz`），没有 EDB 的 `-windows-x64.exe` binaries 树（`v17/`、`17.6/` 一律 404）；`ftp.postgresql.org` 同样只有源码 |
| `kubectl` | 大陆源 1 个（DaoCloud 文件代理 `files.m.daocloud.io/dl.k8s.io/…`），末位 `dl.k8s.io` | 阿里/清华/华为云的 `kubernetes/` 只同步 apt、yum 仓库，`…/release/v…/bin/…` 一律 404；GitHub Release 不发这个二进制，所以 `GH_ACCELERATORS` 对它无效 |
| `jdk` | **离线默认清单**只有官网 `api.adoptium.net` 一条；点「刷新版本」后才会解析出清华 `/Adoptium/<major>/jdk/<arch>/<os>/` 与南大 `/adoptium/…` 的确切文件名并补成多源 | 镜像目录里只有带 build 号的确切文件名，而官方 `latest-binary` 是按月滚动的重定向，离线状态无法确定文件名 |
| `git`（Linux/macOS） | **不给任何下载 URL**，改由 `unsupported_platform_hint` 引导用 apt / dnf / yum / brew | 官方与各镜像都不发布 Linux/macOS 可移植二进制，GitHub 上只有 `git/git` **源码 tar.gz**（解压后没有可执行文件，需自行 configure + make）；列出来只会让用户下一个用不了的东西。Windows 侧不受影响，仍有 3 家真镜像 |
| `nginx`（Linux/macOS） | **不给任何下载 URL**，改由 `unsupported_platform_hint` 引导用 apt / dnf / yum / brew | `nginx.org/download/` 对这两个平台只有 `nginx-<v>.tar.gz` **源码包**（要自己 configure + make），预编译 zip 只给 Windows；Windows 侧不受影响，有华为云两个子域 + 官网共 3 源 |
| `powershell` | 大陆真镜像 0 个，三平台一律 `GH_ACCELERATORS` 三个加速器在前、GitHub 裸地址末位 | 清华 / 南大 / 阿里 / npmmirror 的 `powershell` 目录全 404；`mirrors.huaweicloud.com/powershell/` 返回 200 但那是镜像站自己的门户壳页（HTML 里只有导航链接，没有任何 pwsh 资产），属假可用 |

### R1.2 适用范围

- **全部 26 个组件**（语言运行时：jdk / python / node / go / bun；Shell：powershell；构建工具：maven / gradle；应用服务器与 Web 服务：tomcat / nginx；数据库：mysql / mongodb / postgresql；容器与编排：docker / kubectl；CI/CD：jenkins；消息队列：rabbitmq / kafka / rocketmq / pulsar / activemq；服务发现与事务：nacos / seata；搜索引擎：elasticsearch；版本控制：git；Python 发行版：conda）
- `build_components()` 的默认（离线）清单
- `DownloadWorker` 的实际下载请求（按 `url_list_map` 顺序遍历，失败自动切换）
- `ComponentVersion.url_list_map` 多源故障转移 URL 列表（向后兼容旧的 `url_map` 单 URL 模式）
- 平台不支持场景的 `unsupported_platform_hint` 友好提示（如 Docker 在 Windows、RabbitMQ 在 Windows、PostgreSQL 在 Linux/macOS、MongoDB 在 macOS、Git 在 Linux/macOS、Nginx 在 Linux/macOS）

> **不适用于版本索引页**：`fetch_xxx_versions()` 抓「有哪些版本可选」的索引页 / API 直连官方，理由见 R1.7 第 4 节的实测（镜像索引页版本数残缺，会把下拉框砍短）。

### R1.3 镜像源优先级表

下表为可用的国内镜像源，**按稳定性与速度综合排序**。新增组件的镜像清单必须从下表挑选，不得引入表中未列出的源（保证可维护性）。集中维护在源码常量 `MIRROR_BASES`（11 项）。

| 序号 | 镜像源 | 标识 | 域名 | 备注（2026-09-28 实测） |
|------|--------|------|------|--------------------------|
| M1 | 华为云 | `huaweicloud` | `repo.huaweicloud.com` | 覆盖最广且**保留全量历史版本**，几乎都排第一优先级 |
| M1b | 华为云（另一子域） | `huaweicloud-py` | `mirrors.huaweicloud.com` | Python 发行包、`git-for-windows`、docker-ce、jenkins、rabbitmq、seata 只在这个子域有 |
| M2 | 清华 TUNA | `tuna` | `mirrors.tuna.tsinghua.edu.cn` | apache/*、nodejs-release、anaconda、docker-ce、jenkins、Adoptium 可用；**对默认 UA 回 403**（见 R1.4） |
| M3 | 阿里云 | `aliyun` | `mirrors.aliyun.com` | apache/*、mysql、golang、docker-ce、jenkins 可用；无 gradle / mongodb / elasticsearch |
| M4 | 南京大学 | `nju` | `mirrors.nju.edu.cn` | apache/*、nodejs-release、golang、gradle、anaconda、docker-ce、jenkins、adoptium 可用 |
| M5 | 中科大 | `ustc` | `mirrors.ustc.edu.cn` | anaconda / docker-ce / apache/*（maven、tomcat、kafka、rocketmq、pulsar、activemq、incubator-seata）/ jenkins 实测 200 + 真包魔数；**同样屏蔽默认 UA（403）**，早前因此被误判为「假 200」。`golang/` 只是 302 跳回 `dl.google.com`（本机 TLS 失败，等于没有镜像），`gradle/`、`nodejs-release/`、`mysql/`、`mongodb/`、`elasticsearch/`、`Adoptium/` 一律 404 |
| M6 | 北外 BFSU | `bfsu` | `mirrors.bfsu.edu.cn` | apache/*、nodejs-release、anaconda、docker-ce、jenkins、seata 可用；同样屏蔽默认 UA |
| M7 | 腾讯云 | `tencent` | `mirrors.cloud.tencent.com` | 2026-09-28 新增：apache/*、gradle、docker-ce、jenkins 实测 200 |
| M8 | 上海交大 | `sjtug` | `mirrors.sjtug.org` | 实测经代理不可达，**当前未使用**，仅保留在常量表备查 |
| N1 | 淘宝 npmmirror | `npmmirror` | `registry.npmmirror.com` | 二进制聚合站，路径为 `/-/binary/<项目>/`；python / node / bun / git-for-windows 可用，gradle 404 |
| D1 | DaoCloud 文件代理 | `daocloud-files` | `files.m.daocloud.io` | 2026-09-28 新增：把 `dl.k8s.io/…` 作为路径后缀代理，kubectl 唯一可用大陆源（实测 200/58 MB） |

GitHub Release 没有真镜像，只能用反向代理前缀加速，集中维护在 `GH_ACCELERATORS`
（`ghfast.top` / `gh-proxy.com` / `ghproxy.net` + 裸地址末位），统一走 `_gh_accelerated()`。
`ghproxy.com` 与 `gh.idayer.com` 实测已停服，不得再引入。

> **加速器顺序 = 实测速度顺序**（2026-10-08 本机复测后重排，原顺序把 `ghproxy.net` 放在首位）。
> 口径：对同一份资产取 10-13 秒的实际字节数，带 `HTTP_UA`：
>
> | 加速器 | PowerShell-7.6.6-win-x64.zip | otp_win64_27.3.4.1.zip |
> |---|---|---|
> | `ghfast.top` | **751 KB/s** | **401 KB/s** |
> | `gh-proxy.com` | 133 KB/s | 117 KB/s |
> | `ghproxy.net` | 14 KB/s | 28 KB/s |
> | 裸 `github.com` | 请求超时 | 请求超时 |
>
> 两个仓库结论一致，所以这不是单个包的现象。顺序错的代价很具体：Erlang 的 155MB
> 在旧顺序下只有 6 KB/s（≈7 小时，等于下不下来）。
> 换顺序后同一台机器实测 1020 KB/s（约 3 分钟）。

**加速器只代理 GitHub**：`dl.k8s.io`、`artifact.elastic.co` 之类非 GitHub 地址加前缀无效，
kubectl 要走 DaoCloud 的 `files.m.daocloud.io/dl.k8s.io/…` 写法。

> 镜像源清单本身视为配置常量，集中维护在源码的 `MIRROR_BASES` 常量里，URL 构造器只能经
> `_mb(标识)` 取基址，**严禁**散落在各 URL 构造器函数里硬编码域名（有仓库级测试把这条钉死）。

> **已实测证伪、禁止再写入代码的地址**（历史上它们被当成镜像写进过 R1 表）：
> `mirrors.ustc.edu.cn/golang/`（302 跳回 `dl.google.com`，不是镜像）、`mirrors.ustc.edu.cn/mongodb/`（404）、
> `repo.huaweicloud.com/{anaconda,golang,mongodb}`、
> `mirrors.tuna.tsinghua.edu.cn/{gradle,golang,mongodb,postgresql,elasticsearch}`、
> `mirrors.aliyun.com/{mongodb,elasticsearch,gradle}`、`registry.npmmirror.com/-/binary/gradle/`。
>
> 反面教训：判定镜像可用性**必须带 `HTTP_UA` 且校验响应体魔数/字节数**。2026-09-28 首轮探测用默认
> UA，把清华/北外/中科大的 403 当成「不存在」，又把 `ustc` 的 apache/* 误判成「200 + 空体」假源；
> 带 UA 复测后这些路径全部回真包，`ustc` 已重新纳入 maven/tomcat/kafka/rocketmq/pulsar/activemq/
> seata/jenkins 这八个构造器的列表末位（仍在官网之前）。

### R1.4 故障转移流程

下载一个组件版本时，按以下流程依次尝试：

```
┌─────────────────────────────────────────┐
│  构造镜像 URL 列表（按 M1→M2→M3→...顺序） │
│  + 末位追加官方 URL                       │
└──────────────────┬──────────────────────┘
                   │
                   ▼
        ┌────────────────────┐
        │ 取下一个 URL        │
        └──────────┬─────────┘
                   │
            ┌──────▼──────────┐
            │ 带 HTTP_UA 直接 │
            │ GET 流式下载    │
            │（无独立探测请求）│
            └──────┬──────────┘
                   │
        ┌──────────┴──────────┐
        收完                    失败
        │                       │
        ▼                       │
┌───────────────────────┐       │
│ 校验：实际字节 ≥ 4096 │       │
│ 且不短于 Content-Length│      │
└──────┬────────┬───────┘       │
     通过      不通过（假 200）  │
       │        │               │
       ▼        ▼               ▼
   replace   删 .part ──→ 记日志，切下一个 URL
   为 dest
                            │
                            ▼
                  遍历完所有 URL 仍失败
                            │
                            ▼
                  ┌───────────────────┐
                  │ 抛出下载失败异常   │
                  │ 日志输出所有尝试   │
                  └───────────────────┘
```

**关键参数**（集中定义在 `main.py` 的常量区，不得在调用点硬编码）：

| 参数 | 默认值 | 实际用途 |
|------|--------|----------|
| `HTTP_UA` | `{"User-Agent": "byte-tools"}` | **所有出网请求**（`_get()` 与 `DownloadWorker._try_download()`）必须携带。实测：清华 TUNA 与 BFSU 对 requests 默认 UA 和浏览器 UA 一律 403，只放行自定义 UA |
| `DOWNLOAD_MIN_VALID_BYTES` | 4096 | 下载结束后校验实际写入字节数。实测：`repo.huaweicloud.com/anaconda/<任意路径>` 会 301 到软 404 页并回「200 + 无 Content-Length + 一小段 HTML」，不校验就会留下 HTML 假包，直到解压阶段才炸 |
| `DOWNLOAD_PROBE_TIMEOUT` | 5 秒 | **列目录 / 索引页探测**超时（如 JDK 镜像列目录、各组件版本索引页）。下载流程不做独立探测，直接按 `DOWNLOAD_TIMEOUT` 建连 |
| `DOWNLOAD_TIMEOUT` | 30 秒 | 流式下载的连接/读超时 |
| `DOWNLOAD_RETRY_PER_URL` | 2 | 同一 URL 的重试次数（指数退避）；404/403 等不可恢复错误**不重试**，直接切下一个源 |
| 故障转移最大尝试数 | 镜像数 + 1 | 超过则判定为彻底失败 |

**归档后缀必须与包体一致**：`extract_archive()` 按文件后缀分派，所以 `_STD_ARCHIVE`
（`Windows=zip / Darwin=tar.gz / Linux=tar.gz`）不成立的组件必须用 `_cv(v, urls, archive_map=…)` 显式覆盖。
当前有四处：MySQL Linux=`tar.xz`、RabbitMQ=`tar.xz`、Seata/Kafka=`tar.gz`（跨平台同一包）、PostgreSQL Windows=`zip`。

### R1.5 各组件镜像清单

下表 26 个组件的镜像路径**全部逐条实测**（2026-09-28，GET + `User-Agent: byte-tools`）。
"默认清单实测"一栏给的是默认版本行里**可用大陆源的数量 / 配置的候选数量**。

#### 首批 8 个组件（2026-09 由单源补齐为多源）

| key | 组件 | 国内镜像（按优先级，实测可用性） | 末位官网 | 默认清单实测 |
|-----|------|--------------------------------|---------|--------------|
| `jdk` | JDK (Temurin) | 清华 `…/Adoptium/<major>/jdk/<arch>/<os>/`、南大 `…/adoptium/…`（两家目录大小写不同）。镜像里只有带 build 号的确切文件名，须先列目录挑最新版本，故有 `_adoptium_mirror_urls()`；镜像未同步的 major（如 22/23/24/26/27）自动只剩官网 | `api.adoptium.net/v3/binary/latest/<major>/ga/…` | 离线默认 0/0（见 R1.1 例外）；「刷新版本」后为 2 家镜像 + 官网。21/17/11 三档 × 三平台官网直连实测 200（190~207 MB） |
| `maven` | Apache Maven | M1 `repo.huaweicloud.com/apache/maven/maven-3/`、M2 清华、M3 阿里、M4 南大、M6 北外、M7 腾讯、M5 中科大（高校站只留最新版本，旧版 404 由故障转移兜住） | `archive.apache.org/dist/maven/maven-3/` | 3.9.16：7/7 家 200（9 MB）；3.9.6 只剩华为云 + archive |
| `tomcat` | Apache Tomcat | 同上七家 `apache/tomcat/tomcat-<major>/v<v>/bin/` | `archive.apache.org/dist/tomcat/` | 10.1.60：7/7 家 200（14~15 MB） |
| `mysql` | MySQL Server | Windows/Linux：M3 `mirrors.aliyun.com/mysql/MySQL-<maj.min>/`、M1 `repo.huaweicloud.com/mysql/Downloads/MySQL-<maj.min>/`。macOS 也有这两家镜像，但文件名用**当年命名**：8.0.28→`macos11-<arch>.tar.gz`（阿里+华为都 200/177 MB）、8.0.29→`macos12-<arch>`（华为 200/176 MB） | `cdn.mysql.com/Downloads/`（**不是** `dev.mysql.com` 的 get 跳转入口，后者对任何 UA 都回 403）；macOS 用 `macos14-<arch>` | Windows 2/2、Linux 2/2、macOS 2/4（8.0.37 这一档镜像站还没同步，只有 CDN 200/173 MB） |
| `python` | Python | M1b `mirrors.huaweicloud.com/python/`、N1 `registry.npmmirror.com/-/binary/python/` | `www.python.org/ftp/python/` | 2/2 家 200（Windows embed 11 MB、Unix 27 MB） |
| `node` | Node.js | M2/M4/M6 `…/nodejs-release/v<v>/`、M1 `repo.huaweicloud.com/nodejs/v<v>/`、N1 `registry.npmmirror.com/-/binary/node/v<v>/` | `nodejs.org/dist/` | 5/5 家 200（29~47 MB） |
| `git` | Git for Windows | **Windows 有真镜像**：M1b `mirrors.huaweicloud.com/git-for-windows/<v>.windows.1/MinGit-<v>-64-bit.zip`、M1 `repo.huaweicloud.com/…`、N1 `registry.npmmirror.com/-/binary/git-for-windows/…`（三家实测 200/47 MB），再补 `GH_ACCELERATORS` | `github.com/git-for-windows/git/releases/download/` | Windows 3 家镜像 + 3 加速器全 200；Linux/macOS **不再给 URL**，`_git_urls()` 只返回 `Windows` 键，由 `unsupported_platform_hint` 引导 apt/dnf/yum/brew（R1.1 例外） |
| `conda` | Miniconda | M2 清华、M4 南大、M6 北外、M5 中科大 `…/anaconda/miniconda/`（文件名与官方一致）。华为 `repo.huaweicloud.com/anaconda/` 对任意路径都 301 到软 404 HTML 页（假成功），已删除 | `repo.anaconda.com/miniconda/` | 4/4 家 200（90~149 MB） |

#### 新增 18 个组件镜像清单（2026-09-28 全部按实测重写）

| key | 组件 | 国内镜像（按优先级） | 末位官网 | 默认清单实测 |
|------|------|-----------------------|---------|--------------|
| `go` | Go | M3 `mirrors.aliyun.com/golang/`、M4 `mirrors.nju.edu.cn/golang/`（华为、清华对 `go<ver>.linux-amd64.tar.gz` 这类包名恒 404，已删除；M5 中科大只是 302 跳回 `dl.google.com`，本机 TLS 握手失败，同样不算镜像） | `go.dev/dl/` | 2/2 家 200（79~87 MB） |
| `gradle` | Gradle | M1 `repo.huaweicloud.com/gradle/`、M1b `mirrors.huaweicloud.com/gradle/`、M4 南大、M7 腾讯（清华/阿里/北外/npmmirror 无 gradle 目录，已删除） | `services.gradle.org/distributions/` | 4/4 家 200（137 MB） |
| `bun` | Bun | N1 `registry.npmmirror.com/-/binary/bun/` + `GH_ACCELERATORS` 三个加速器 | `github.com/oven-sh/bun/releases` | 1 家真镜像 + 3 加速器全 200（28~40 MB） |
| `docker` | Docker | Linux：M1/M1b/M2/M3/M4/M5/M6/M7 八家 `/docker-ce/linux/static/stable/<arch>/`；macOS：同八家 `/docker-ce/mac/static/stable/<arch>/` | `download.docker.com/{linux,mac}/static/` | 8/8 家 200（18~75 MB）；**Windows 不提供**，`unsupported_platform_hint` 引导装 Docker Desktop |
| `mongodb` | MongoDB | **无**（见 R1.1 例外表） | `fastdl.mongodb.org`，Linux 包名必须带发行版段 `mongodb-linux-x86_64-ubuntu2204-<v>.tgz`，否则 403 | 0/0；Windows 785 MB、Linux 100 MB 官网 200；macOS 不提供 |
| `postgresql` | PostgreSQL | **无**（清华 404；华为/阿里/南大只有 `latest/`、`source/` 源码 tarball，`ftp.postgresql.org/pub/source/` 同样只有源码，都没有 EDB 的 Windows binaries 树） | `get.enterprisedb.com/postgresql/postgresql-<v>-1-windows-x64-binaries.zip` | 0/0；四个版本 Windows 全 200（330~350 MB）；Linux/macOS 不提供 |
| `kubectl` | kubectl | D1 `files.m.daocloud.io/dl.k8s.io/release/v<v>/bin/<os>/<arch>/kubectl`（实测 200/58 MB，真 Mach-O/PE/ELF） | `dl.k8s.io/release/…` | 1/1 家 200；**单源例外**已升级为「1 家大陆源 + 官网」 |
| `jenkins` | Jenkins | M1、M1b、M2、M6、M4、M3、M7、M5 八家 `/jenkins/war-stable/<v>/jenkins.war`（镜像只保留最近几条 LTS 线） | `get.jenkins.io/war-stable/` | 8/8 家 200（101 MB）。单 war 文件，需 `java -jar jenkins.war` 启动，本工具只做下载 + 配环境变量 |
| `rabbitmq` | RabbitMQ | M1、M1b `/rabbitmq-server/v<v>/rabbitmq-server-generic-unix-<v>.tar.xz`，再 `GH_ACCELERATORS` | `github.com/rabbitmq/rabbitmq-server/releases` | 2 家镜像 + 3 加速器全 200（16 MB），**归档类型是 tar.xz**；Windows 不提供（依赖 Erlang，引导官网安装器） |
| `kafka` | Apache Kafka | 华为、清华、阿里、南大、北外、腾讯、中科大七家 `/apache/kafka/<v>/kafka_2.13-<v>.tgz`（Kafka 只发 `.tgz`，包名带 Scala 版本段 `2.13`，`-bin.zip` 实测 404） | `archive.apache.org/dist/kafka/` | 7/7 家 200（134 MB），tar.gz 跨平台 |
| `rocketmq` | Apache RocketMQ | 七家 `/apache/rocketmq/<v>/rocketmq-all-<v>-bin-release.zip` | `archive.apache.org/dist/rocketmq/` | 7/7 家 200（90 MB） |
| `pulsar` | Apache Pulsar | 七家 `/apache/pulsar/pulsar-<v>/apache-pulsar-<v>-bin.tar.gz` | `archive.apache.org/dist/pulsar/` | 7/7 家 200（219 MB） |
| `activemq` | ActiveMQ | 七家 `/apache/activemq/<v>/apache-activemq-<v>-bin.<ext>`（目录段是**裸版本号**，不是 `activemq-<major>`；Windows zip、Unix tar.gz） | `archive.apache.org/dist/activemq/` | 7/7 家 200（57 MB） |
| `nacos` | Nacos | 无真镜像，`GH_ACCELERATORS` 三个加速器（实测全 200） | `github.com/alibaba/nacos/releases/download/<v>/nacos-server-<v>.zip` | 3 加速器 + 裸地址全 200（154 MB） |
| `seata` | Seata | **改走 Apache 分发目录**：M1、M1b、M2、M3、M4、M6、M7、M5 八家 `/apache/incubator/seata/<v>/apache-seata-<v>-incubating-bin.tar.gz`（GitHub release 里的 `seata-server-<v>.jar` 只是 thin jar，不能解压即用） | `archive.apache.org/dist/incubator/seata/` | 8/8 家 200（191 MB），tar.gz 跨平台。2.x 文件名带 `-incubating`，1.x 是 `seata-server-<v>.zip` |
| `elasticsearch` | Elasticsearch | M1、M1b `/elasticsearch/<v>/elasticsearch-<v>-<os>-<arch>.<ext>`（清华/阿里无此制品；镜像只同步新版本，8.15.0 一类旧版本 404 由故障转移兜到官网） | `artifacts.elastic.co/downloads/elasticsearch/` | 9.2.3：2/2 家 200（471~687 MB）；8.15.0/8.9.2 只有官网 |
| `powershell` | PowerShell 7 | **无真镜像**（清华 / 南大 / 阿里 / npmmirror 的 `powershell` 目录一律 404；华为 `mirrors.huaweicloud.com/powershell/` 只是镜像站门户壳页），走 `GH_ACCELERATORS` 三个加速器 | `github.com/PowerShell/PowerShell/releases/download/v<v>/…`；资产名大小写不统一：Windows 是 `PowerShell-<v>-win-<arch>.zip`，Linux/macOS 是 `powershell-<v>-{linux,osx}-<arch>.tar.gz` | 12 版本 × 三平台 × 4 源全 200（zip / gzip 魔数已验）；`ghproxy.net` 偶发 503，重试即通且故障转移会自动换下一个加速器 |
| `nginx` | Nginx | M1b `mirrors.huaweicloud.com/nginx/nginx-<v>.zip`、M1 `repo.huaweicloud.com/nginx/nginx-<v>.zip`（实测两家都同步了 zip；清华 / 北外 / 南大 / 阿里 / 腾讯对同一文件名一律 404——它们的 `nginx/` 目录是给 apt/yum 用的包仓库，没有 nginx.org 那套 Windows zip） | `nginx.org/download/nginx-<v>.zip` | Windows 3/3 全 200（约 2.1 MB，解压根目录即 `nginx.exe`）；Linux/macOS **不给 URL**——上游只发源码 `.tar.gz`（需自行 configure + make），由 `unsupported_platform_hint` 引导 apt/dnf/yum/brew（R1.1 例外） |

> 注：部分镜像只同步最新版本，故障转移时若镜像返回 404，直接切到下一个，**不要**对该 URL 内部反复重试。

### R1.6 新增组件的镜像配置 checklist

新增一个组件 PR 之前，必须依次确认：

- [ ] **先用 GET 实测**候选镜像的确切 URL（带 `User-Agent: byte-tools`，看状态码 + `Content-Length` + 首 4 字节的魔数），把结论写进 R1.5 表；**没有实测证据的地址一律不得写入代码**
- [ ] 已从 R1.3 镜像源优先级表中挑选 ≥2 个镜像源；凑不出 2 个的，在 R1.1 例外表登记实测依据
- [ ] 在 R1.5「各组件镜像清单」表中登记该组件的镜像清单与默认清单实测结果
- [ ] URL 构造器返回 `Dict[str, List[str]]`（镜像在前、官网末位），且**官网必须是最后一项**
- [ ] 包体后缀与 `_STD_ARCHIVE` 不一致时，用 `_cv(v, urls, archive_map=…)` 显式覆盖
- [ ] 出网请求走 `_get()` / `DownloadWorker`，从而自动带上 `HTTP_UA` 并受 `DOWNLOAD_MIN_VALID_BYTES` 保护
- [ ] 版本抓取器 `fetch_xxx_versions()` 直连官方索引页（见 R1.7 第 4 节，镜像索引会把版本列表砍短）
- [ ] 故障转移全程输出中文日志（哪个镜像失败、原因、切换到哪个、最终用了哪个）
- [ ] 平台不支持的组合（如 Docker 在 Windows）不给 URL，只写 `unsupported_platform_hint`
- [ ] 测试覆盖：模拟前 N 个镜像失败、验证能切到第 N+1 个；模拟全部失败、验证抛出中文异常；模拟「200 + 空体」，验证不会当成成功

### R1.7 实施改造指引

> ✅ **改造已完成**：当前 `main.py` 的实现已是「R1 多源故障转移」模式，本节所述的 URL 列表签名、镜像源常量集中管理、DownloadWorker 多源遍历、版本抓取器镜像优先等改造均已落地。以下内容保留作为设计参考与新增组件的实施模板，新增组件时按此模板实现即可。
>
> 历史背景：改造前 `main.py` 是「单 URL 直连官网」模式，URL 构造器返回 `Dict[str, str]`（单 URL），DownloadWorker 只尝试一个 URL，失败即抛异常。改造后 URL 构造器返回 `Dict[str, List[str]]`（多 URL 列表），DownloadWorker 按列表顺序遍历，失败自动切换，全失败才抛异常。

#### 1. URL 构造器签名调整

由：
```python
def _maven_urls(v: str) -> Dict[str, str]:
    # {"Windows": url, "Darwin": url, "Linux": url}
    ...
```

改为：
```python
def _maven_urls(v: str) -> Dict[str, List[str]]:
    """
    返回按操作系统键映射的「镜像 URL 列表」。
    列表顺序即尝试顺序：国内镜像在前，官网末位。
    """
    name = f"apache-maven-{v}-bin"
    rel = f"/apache/maven/maven-3/{v}/binaries/{name}"
    return {
        "Windows": [f"{b}{rel}.zip" for b in _mb("huaweicloud", "tuna", "aliyun", "nju", "bfsu", "tencent")]
                   + [f"https://archive.apache.org/dist{rel}.zip"],   # 末位官网
        "Darwin":  [...同 rel.tar.gz...],
        "Linux":   [...同 rel.tar.gz...],
    }
```

#### 2. 镜像源常量集中管理

```python
# 镜像源基址（R1.3 表的常量化表达，共 11 项）
MIRROR_BASES: List[Tuple[str, str]] = [
    ("huaweicloud",    "https://repo.huaweicloud.com"),
    ("huaweicloud-py", "https://mirrors.huaweicloud.com"),
    ("tuna",           "https://mirrors.tuna.tsinghua.edu.cn"),
    ("aliyun",         "https://mirrors.aliyun.com"),
    ("nju",            "https://mirrors.nju.edu.cn"),
    ("ustc",           "https://mirrors.ustc.edu.cn"),
    ("bfsu",           "https://mirrors.bfsu.edu.cn"),
    ("tencent",        "https://mirrors.cloud.tencent.com"),
    ("sjtug",          "https://mirrors.sjtug.org"),
    ("npmmirror",      "https://registry.npmmirror.com"),
    ("daocloud-files", "https://files.m.daocloud.io"),
]

# GitHub Release 反向加速器（无真镜像，只能代理）
GH_ACCELERATORS = ["https://ghproxy.net/", "https://gh-proxy.com/", "https://ghfast.top/"]

# 下载参数与出网身份
HTTP_UA                   = {"User-Agent": "byte-tools"}   # 高校镜像会 403 默认 UA
DOWNLOAD_MIN_VALID_BYTES  = 4096                           # 拒绝「200 + 空体」假成功
DOWNLOAD_PROBE_TIMEOUT    = 5      # 列目录 / 索引页探测超时（秒）
DOWNLOAD_TIMEOUT          = 30     # 流式下载连接/读超时（秒）
DOWNLOAD_RETRY_PER_URL    = 2      # 单 URL 内重试次数（404/403 不重试）
```

#### 3. DownloadWorker 改造

```python
class DownloadWorker(QThread):
    """
    多源故障转移下载线程。

    入参 urls: List[str]  按 R1.4 顺序的下载 URL 列表（镜像优先，官网末位）
    入参 dest: Path       目标文件路径（先写 .part 临时文件，成功后 replace）
    """
    def run(self) -> None:
        tried_failures: List[str] = []
        for idx, url in enumerate(self.urls, 1):
            try:
                self._download_from(url)
                return
            except Exception as exc:
                # 中文日志：哪个镜像失败 + 错误原因 + 即将切换
                self.log.emit("warn",
                    f"第 {idx} 个源下载失败：{url}\n原因：{exc}")
                tried_failures.append(f"{url} -> {exc}")
        # 所有源都失败
        self.log.emit("error",
            "所有镜像与官网地址均下载失败，已尝试：\n" + "\n".join(tried_failures))
        self.finished_fail.emit("所有下载源均不可用")
```

单个 URL 内部（`_try_download`）必须完成两件事，否则该源视为无效并继续故障转移：

```python
resp = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT,
                    verify=False, headers=HTTP_UA)        # 1) 带自定义 UA
...逐块写 .part...
total = int(resp.headers.get("Content-Length") or 0)
if downloaded < DOWNLOAD_MIN_VALID_BYTES or (total and downloaded < total):
    tmp.unlink(missing_ok=True)                           # 2) 空体/短体不是成功
    return False
tmp.replace(self.dest)
```

#### 4. 版本抓取器（索引页）——实测结论：保持官网单源

`fetch_xxx_versions()` 抓版本列表时请求的是**索引页 / API**，与下载压缩包不同，这里「镜像优先」反而有害：国内镜像普遍只同步最新几个版本，列表会残缺。2026-09-28 实测同一索引页的版本数量：

| 索引页 | 官网 | 国内镜像 |
|--------|------|----------|
| Maven `maven-3/` | `archive.apache.org` **45** 个版本 | 华为云 37 个、清华 **1** 个（只有 3.9.16） |
| Node.js | `nodejs.org/dist/` 868 个目录 | 清华 `nodejs-release/` 792 个 |
| Python | `python.org/ftp/python/` 255 | 华为云 255（一致） |

因此规则是：**下载 URL 走 R1 多源故障转移（镜像在前），版本索引页以官方为先**。首批 8 个组件的 `fetch_jdk/maven/tomcat/mysql/python/node/git/conda_versions()` 全部直连官方索引；曾为此准备的公共辅助 `_get_first_working()` 因没有合法调用点已删除。新增组件写索引抓取时同样**不要**把镜像排在官方之前——那只会让下拉框少一批可选版本。

> 既有实现差异（非本次改造引入）：后加的 16 个组件里 `_fetch_apache_versions()` / `fetch_go_versions()` / `fetch_mongodb_versions()` 等共享辅助仍按「镜像索引 → 官网索引」顺序取第一个非空结果，镜像先返回时版本列表可能偏短（如清华 Apache 索引只给 1 个版本）。若要彻底统一，应改成「并集去重」或「取版本数最多的一家」，而不是按顺序取第一个非空。

### R1.8 镜像失效处理

- 镜像源突然下线、目录结构变更属常态，故障转移机制保证最终能从官网拿到包
- 若发现某个镜像源长期失效（连续 N 个版本都 404），应在 R1.3 表中标注并讨论是否替换
- 严禁为绕过故障转移而直接把镜像 URL 改成官网——这违反 R1.1
- **两类"看起来成功"的失效必须在下载层拦掉**（2026-09-28 实测的两起真实事故）：
  1. **403 屏蔽 UA**：清华 TUNA、北外 BFSU 对 requests 默认 UA 与浏览器 UA 回 403，只放行自定义 UA。
     所有出网请求因此固定携带 `HTTP_UA`；新增请求点时不得省略 `headers`。
  2. **假 200 软 404**：`repo.huaweicloud.com/anaconda/<任意不存在的路径>` 301 跳到软 404 页，
     回「200 + 无 `Content-Length` + 一小段 HTML」；`mirrors.huaweicloud.com/mongodb.org/<ver>/...`
     对缺失文件同样回 0 字节 200。`DOWNLOAD_MIN_VALID_BYTES` + 声明长度比对负责把它们退回故障转移。
     注意：**不带 UA 时的 403 与带 UA 后的空体是两回事**——2026-09-28 首轮探测把清华/北外/中科大的
     UA 屏蔽误判成「假源」，复测证明 `ustc` 的 apache/*、jenkins、docker-ce 都是真包。
- 判定"某镜像可用"的最低证据 = 状态码 200 **且** `Content-Length` 是真实包体大小 **且** 首块魔数与归档类型相符
  （zip→`PK\x03\x04`，tar.gz→`\x1f\x8b`，tar.xz→`\xfd7zXZ`，exe→`MZ`）。只测状态码会把假 200 当成可用源。

---

## 规则 R2：组件四类分组与界面 Tab

### R2.1 规则描述

26 个可见组件在界面上归入且仅归入四个 Tab，分类标准必须**机械可判**，不允许按感觉塞组件：

| 分类 | 判定标准 | 组件（10 / 4 / 10 / 2） |
|------|----------|--------------------|
| **开发环境** | 装完进 PATH，直接用来写 / 编译 / 打包代码 | jdk、python、node、go、bun、conda、git、maven、gradle、powershell |
| **开发软件** | 本地跑起来给项目当依赖、但本工具**还不能一键启停**的服务 | mysql、mongodb、postgresql、pulsar |
| **一键启停** | 卡片上有「启动 / 停止」按钮 —— **成员由 `LAUNCH_KEYS` 派生，不另立清单** | jenkins、nacos、activemq、rocketmq、nginx、kafka、tomcat、elasticsearch、rabbitmq、seata |
| **其它软件** | 不参与写代码的容器 / 编排外围 | docker、kubectl |

边界争议按此顺序裁决：**能不能在本工具里一键启停** → 是则一键启停（这一条优先，不看性质）；否则**要不要设 `XXX_HOME` 进 PATH 才能开工** → 是则开发环境；否则看**是否作为常驻服务被项目依赖** → 是则开发软件；都不是则其它软件。
（「一键启停」放在「其它软件」之前：它是本工具最能干活的一组，埋在倒数第二页等于藏起来。2026-10-08 用户要求。）
（例：Maven / Gradle 是命令行构建工具，进 PATH 才能开工，属开发环境而非"服务"；Tomcat 需要跑起来给项目用，属开发软件；PowerShell 是进 PATH 的 Shell / 脚本运行时，属开发环境；Nginx 与 Tomcat 同理，本地跑起来当 Web / 反向代理依赖，属开发软件。）

### R2.2 适用范围

- `Component.category` 字段与 `COMPONENT_CATEGORY_OF` 登记表
- `group_components()` 与 `MainWindow._build_ui()` 的 Tab 构建
- 新增 / 改名 / 删除组件时的分类登记

### R2.3 实施指引

分类**只有一个真源**：`COMPONENT_CATEGORY_OF`（`main.py`，`build_components()` 之前）；
可启停那一组**由 `LAUNCH_KEYS` 派生**，不在分类表里重复登记。

```python
COMPONENT_CATEGORIES = ("开发环境", "开发软件", "一键启停", "其它软件")   # Tab 顺序即此顺序
COMPONENT_CATEGORY_OF = {
    ...
    "foo": "开发软件",          # 新增组件在这里加一行（它接进 LAUNCH_OF 后会自动进「一键启停」）
}
```

`build_components()` 末尾统一执行
`comp.category = "一键启停" if comp.key in LAUNCH_KEYS else COMPONENT_CATEGORY_OF[comp.key]`——
写成第二张表的话，接入第 11 个可启停组件时会出现"能启动、卡片却在别的 Tab"；
而分类表里的旧归属保留作 fallback，组件从白名单退下来时会自动回到原来那一组。
**不要**在各 `Component(...)` 构造处手写 `category=`，也**不要**给 `.get(key, 默认值)` 兜底：
**不要**在各 `Component(...)` 构造处手写 `category=`，也**不要**给 `.get(key, 默认值)` 兜底：
（上一段已写明不许 `.get` 兜底）漏登记必须 KeyError 炸出来，静默归到某个分类会让新组件"消失"在错误的 Tab 里。

`MainWindow.cards` 必须保持**全量平铺**（26 项，跨 Tab 收集）：刷新版本、读写配置、关窗前等探测线程都遍历它，分组只改变卡片的父布局。

Tab 条固定在**顶部横向**（`setTabPosition(QTabWidget.North)`），标题格式为 `f"{分类名}（{数量}）"`，
数量由 `group_components()` 的结果现算——**不要写死数字**，否则增删组件后标题会与真实卡片数不符。

Tab 内的卡片排成**按宽度重排的网格**（2026-10-08），不再是一行一张占满宽：

- **列数只由可用宽度算**：`grid_columns_for(available_px, MIN_CARD_WIDTH_PX)`，`MIN_CARD_WIDTH_PX = 300`
  （一张卡片信息不砍的下限）。窗口 1000 宽时视口净宽 954，实测 **3 列 × 3 行 = 9 个/屏**；
  窗口拉宽自动变更多列，拉窄回落到 1 列。视口宽度在布局生效前会是 0，非法入参一律兜底 1 列
  ——除零或负列数会让整片卡片消失
- **实现是行容器法，不是 `QGridLayout`**：Tab 外层仍是一个 `QVBoxLayout`，里面装"行"，
  每行一个 `QHBoxLayout` 装 1..N 张卡（`_tab_layouts[i]` 的语义因此从"直接装卡片"改成"装行的外层竖向布局"）。
  **不要换成 `QGridLayout`**：`_reparent` / `_restore_browse` / `_build_unified` 三处全靠 `QBoxLayout`
  的 `indexOf` / `insertWidget` / 末尾 stretch 工作，`QGridLayout` 没有这套语义
- **relayout 只排可见卡片**（`chunk_visible`）：`QBoxLayout` 会给隐藏控件留位，
  留着隐藏卡片等于"搜索命中 1 个时网格出现空洞"
- **视图切换**是搜索条上一颗 `▦ 网格 / ☰ 列表`，持久化到 `config.json` 的 `view_mode`，默认 `grid`；
  列表模式 = 强制 1 列，卡片内部一模一样。**按钮在搜索条上，不在标题栏**：标题栏已有 5 个按钮 + 3 个窗口控制，
  实测需要 ~992px，窗口才 1000 宽，再加必然把已有按钮压到裁字

底部日志区已**移出 `QSplitter` 的 3:2 分配**，改成浮层（同 parent + `raise_()`，几何随 resize 跟随），
展开时**遮住**最下面一行格子而不是把网格压扁。选浮层的理由：它不在 `body` 的布局里，`show/hide` 不触发
重排 ⇒ 列数与行数只由窗口宽度决定，开关日志不会让格子忽大忽小，也省掉"挤压式折叠"的二次 relayout。
触发规则：**只有 `warn` / `error` 才自动弹开**并挂未读条数（写在 `📋 日志 (N)` 按钮文字里，不新增控件）；
下载/安装这类常规进度不弹（进度条已在卡片上，每来一条都弹会把用户正在操作的那张卡盖住）。
未读数只在"弹开前是收起的"时才累加；手动打开即清零且**不自动收起**；自动弹开的那个静默 8 秒后自愈收起。

### R2.4 新增 / 调整组件分类 checklist

- [ ] `COMPONENT_CATEGORY_OF` 里登记了该 key，且值取自 `COMPONENT_CATEGORIES`
- [ ] 按 R2.1 的判定顺序核对归类理由，有争议的在 PR 说明里写清
- [ ] `bt_component_category_tests.py` 通过（其中 `EXPECTED_MEMBERSHIP` 是分类基线，改归类要同步改它）
- [ ] 未新增 `if category == ...` 之类的界面特判——分组渲染只走 `group_components()`
- [ ] README / README_EN 的四 Tab 表格与 `CODE_WIKI.md` 的 `category` 字段说明同步

### R2.5 组件搜索框

组件数上到 26 个后逐页翻不现实，Tab 上方有一条搜索框做名称模糊过滤。约束：

- **位置在标题栏之外**、Tab 之上（`#searchBar` 内的 `QLineEdit#compSearch`）。标题栏整条是窗口拖拽区
  （`mousePressEvent` 里判 `title_bar.underMouse()` 就开始拖动），输入框塞进标题栏会点不动、一按就拖窗
- 匹配内核是纯函数 `component_matches(comp, query)`：只比 `display_name` 与 `key`，忽略大小写与首尾空白，
  空查询（或全空白）返回 `True` 表示不过滤。**不要**把分类名纳入匹配——分类已由 Tab 表达，
  搜"开发"会命中全部卡片，等于没搜
- 过滤**只改 `card.setVisible()` 与卡片在布局里的归属**，绝不从 `MainWindow.cards` 里摘项（原因见 R2.3 的全量平铺不变量）
- 网格布局下这条更关键：Tab 里的 relayout **只排可见卡片**，不足一行时在行尾补
  `cardRowFiller` 透明占位格 —— **一格补一个**（不是一个占位控顶 n 格），
  这样间距数与满行一致，格子宽度才不会漂（313 vs 309 就是这么来的）
- **搜索结果面板与浏览用同一列数**（2026-10-10 用户改的口径：「搜索组件时如果只有一个组件
  也要以网格显示，现在变成列表了」）。这里先后改过两次：最早是"结果面板固定单列"，
  后来变成 `min(命中数, 浏览列数)`（命中 1 个就 1 列、一张卡占满整行）—— 那正是用户这次
  报"变成列表了"的现象。现在恒取 `_card_columns()`，命中 1 个也是"3 个格子里占 1 个 + 2 个占位格"。
  判据钉在 `SearchGridHasNoHoles.test_single_hit_keeps_the_same_cell_count_as_browsing`
  （数的是**格子数**，不是卡片像素宽：少补一格，`addWidget(card, 1)` 就会把那张卡拉成整行宽）
- **全组件搜索的呈现方式**：搜索时收起四个 Tab（`QStackedWidget#topStack` 切到统一结果页 `QScrollArea#resultsArea`），
  把所有命中的组件**按分类归并到同一个滚动列表**（每个分类前插一个 `QLabel#resultCatHeader` 小标题），一眼看全、不用切页；
  清空搜索词后 `QStackedWidget` 切回 Tab 浏览态、卡片各自归位、Tab 标题恢复 `分类（总数）`。
  右侧 `#searchHint` 仍显示"匹配 N / 26 个组件"（0 命中转警示红）。数字一律现算
- 这正是"全组件搜索、而不是只搜某个 table 内"的要求：结果跨三个分类，统一归并展示
- 新增组件**不需要**为搜索做任何登记：卡片建好就自动可搜。改匹配规则要同步 `bt_search_and_newcmp_tests.py`
- 外观约定：输入框不直接描边，而是套一层胶囊外壳 `#searchShell`（放大镜 + 输入框同属一块白底圆角），
  聚焦时**整条外壳**描蓝边 —— 为此 `MainWindow.eventFilter()` 监听输入框焦点、经 `_set_search_focus()`
  改外壳的 `focused` 属性并 `unpolish/polish` 重刷样式（QSS 的 `:focus` 选不到父级控件）。
  放大镜与清空按钮图标都用 `QPainter` 现画，不加图片资源；清空按钮用 `QLineEdit.TrailingPosition`
  的 QAction 代替内置清除按钮，以保证跨平台观感一致、颜色可控

---

## 规则 R3：组件多版本与生效版本切换

七个 PATH 型组件（jdk / python / node / go / maven / gradle / bun）允许在同一台机器上**并存多个版本**，
并在界面上显式指定其中一个为「生效版本」。本规则的核心不变量只有一句：

> **删一个版本、切一个版本，都不得影响同一组件其它版本的目录、`XXX_HOME` 与 PATH 条目。**

版本目录统一落在 `<配置根>/<key>/<key>-<version>`（`CONFIG_DIR = Path.home() / ".env-tools"`，`main.py:103`；
目录名由 `Component.install_dir()` 生成，`main.py:203`）。

### R3.1 适用范围

允许并存多版本并切换生效版本的组件只有 7 个：jdk / python / node / go / maven / gradle / bun
（真源：`main.py` 的 `MULTI_VERSION_KEYS`，`main.py:2916`；由 `build_components()` 末尾统一写入
`comp.multi_version = comp.key in MULTI_VERSION_KEYS`，`main.py:3409`，**不要在 `Component(...)` 构造处手写**）。
判据是"归档解压安装 + 靠 `XXX_HOME`/PATH 生效"。
conda 是 `installer_mode`，装在固定目录、卸载也不删目录，"每版本一目录"的前提不成立；
mysql/tomcat/nacos/es 等服务型组件的真矛盾在端口与数据目录。两者都不进本模型。
白名单一扩大，`bt_multiversion_tests.py` 的 `EXPECTED_MULTI_VERSION`（`main.py` 之外唯一的第二处登记）即报不符。
界面上这 7 个组件的标题后带一枚灰色「可多版本」角标（`QLabel`，`objectName="multiVersionBadge"`），
让"能不能多装几个版本"在一个版本都没装时也看得出来；非多版本组件**不创建**该节点。
角标是独立装饰节点，**不许拼进 `display_name` 或标题文本**——后者同时是搜索匹配（`component_matches`）
与日志前缀（`ComponentCard._log`）的真源。护栏用例：`bt_multiversion_tests.py` 的 `MultiVersionBadge`。

### R3.2 两个字段，不许混用

- `selections`（`config.json`）：下拉框当前选中，语义是"我想装 / 我想操作哪个版本"。
- `active`（`config.json`）：当前生效版本，语义是"系统的 `XXX_HOME` 与 PATH 指向哪个"。

写 `config.json` 一律**合并写**：`MainWindow._save_settings` 只替换 `selections` 段并原样保留 `active`；
`save_active_version` 只改 `active` 里那一项。任何一方整体覆盖都会把对方的数据抹掉。
`active` 缺失或 `config.json` 损坏时按空表处理（`load_active_map()`），不报错、不重置用户配置。

### R3.3 切换是原子操作（硬约束）

唯一入口 `apply_active_version(comp, version)`（异常类型 `SwitchError`）：
写 `XXX_HOME`（`EnvManager.write_user_env`）→ 用 `remove_path_entries_under(CONFIG_DIR/<key>)` 把本组件在
PATH 里的条目全部收敛掉 → 只补回生效版本那一条（`target/<path_subdir>`；`path_subdir` 为空的组件如 bun 就用目录本身）
→ 同步当前进程并广播 `WM_SETTINGCHANGE`。任一步失败按**持久层快照**整体回滚
（`read_user_env` 的读值 + `remove_path_entries_under` 的返回值，补救走 `restore_path_entries`），
回滚依据必须是注册表 / shell rc 的真值，不是 `os.environ`（本工具会把它改脏）。
禁止留下「JAVA_HOME 指 A、PATH 指 B」的中间态；回滚未完全成功时**不得**在日志里写"已回滚"，
必须把撤不干净的明细拼进 `SwitchError` 文本（半回滚恰恰是要用户手工介入的情形）。

卸载路径同一条约束：**生效版本必须在任何破坏性动作之前快照**（`Component.uninstall` 里的 `active_before`，
`main.py:375`）。原因是本期上线前装的用户 `config.json` 里没有 `active` 条目，生效版本靠 `infer_active_from_env()`
从 `XXX_HOME` 反推，而卸载第 2 步可能正好把那个 HOME 删掉——事后再读永远是 `None`，"自动重排"会静默失效。
同函数第 4 步（`main.py:443-508`）因此只认这份快照：删掉的正是生效版本→自动 `apply_active_version` 到剩余里版本号最高的；
生效版本还活着、只是环境被这次卸载带偏→按生效版本**重建**（措辞分叉，不把"重建"说成"自动切到"）。

### R3.4 下拉框显示文本不可改动

已装 / 生效状态一律用 `Qt.DecorationRole` 图标表达（绿勾由 `_installed_icon()` 用 `QPainter`
现画，不引入图片资源；挂 / 刷新的唯一出口是 `ComponentCard._refresh_installed_marks()`，装载下拉框的两条出口
`_reload_combo_items()` 都会调它）。`_current_version()` 与 `SearchableComboBox.repopulate(preferred=…)`
都按**显示文本**反查版本对象，往文本里加「✓」会连锁打错选版、安装、卸载与配置保存；
`repopulate` 内部 `clear()` 会连带销毁旧条目的 `DecorationRole` 数据，所以重灌后必须重挂一次。

### R3.5 版本目录命名是唯一契约

安装目录必须叫 `<key>-<version>`（`Component.install_dir`）。`version_from_install_dir()`（`main.py:513`）与
`installed_versions()`（`main.py:529`）依赖该约定；排序必须走 `_sort_semver_desc`（`main.py:2010`），
字典序会把 jdk-8 排在 jdk-21 之后（2026-09-29 之前的「配置环境变量」正是踩了这个坑：用户选 21、配的却是 8）。
`installed_dirs()`（`main.py:282`）排除 `downloads` 缓存与 `.` 开头的解压临时目录，`installed_versions()`
再排除反解不出版本号的残缺目录名——所有"已装"判定（绿勾、状态胶囊、卸载范围）都只认这条链路的输出。

### R3.6 非目标

不做 cd 自动切换的 shell 钩子，不写用户项目的 pom/gradle/IDE 配置，不生成 `toolchains.xml`。

### R3.7 新增 / 调整多版本组件 checklist

- [ ] 只改 `main.py` 的 `MULTI_VERSION_KEYS` 一处（`main.py:2916`）
- [ ] 同步 `bt_multiversion_tests.py` 的 `EXPECTED_MULTI_VERSION`（`main.py` 之外的第二处白名单登记）
- [ ] 确认该组件不是 `installer_mode`、不是服务型组件
- [ ] 跑：`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -u bt_multiversion_tests.py`（全部用例须全绿；用例数随功能演进增长，以磁盘为准）
- [ ] 同步 README.md / README_EN.md 的多版本小节与 `CODE_WIKI.md` 的 `multi_version` 字段、环境层小节

### R3.8 测试沙箱是唯一接缝

多版本相关测试一律走 `bt_multiversion_tests.py` 的 `EnvSandbox`（基类即 `unittest.TestCase`）：
替换 `CONFIG_DIR` / `CONFIG_FILE` / `CURRENT_OS`、把 `EnvManager._shell_rc_file()` 指到临时 rc、
Windows 分支打桩持久层读写（`_read_windows_user_env` / `_read_windows_user_path` / `_write_registry_env` /
`_delete_windows_user_env` / `EnvManager.get`），产品代码里**不得**为测试加开关。
断言只看落盘结果（`win_env` / `win_path` / `CONFIG_FILE` / rc 文本 / `status_label.text()`），
**不得断言桩调用次数**——调用次数是实现的代理指标，改成"另一种同样正确的实现"就会误报失败。
测试文件必须先 stub WMI 再 `import main`（`platform._wmi_query` 抛 `OSError` + `platform.uname.cache_clear()`，
`bt_multiversion_tests.py:19-30`），碰 Qt 的还要 `QT_QPA_PLATFORM=offscreen`。

### R3.9 全部组件都是多版本（2026-06-06 起，取代原「非多版本组件零影响」）

**原规则**：任何多版本分支都要用 `component.multi_version` 门控，非多版本组件的状态文案、
按钮逻辑与卸载结果必须与改造前逐字一致。那是**多版本改造期间**的保护措施——
当时只改 7 个（jdk/python/node/go/maven/gradle/bun），担心一次改 26 个会连带出事。
典型陷阱曾写死为"非多版本组件卸载时选中未装版本必须罢工"。

**现在作废**：26 个组件**全部**支持多版本（用户 2026-06-06 要求）。理由与前提：
- 26 个组件本来就有 2-4 个版本的候选清单，能装多个版本不需要额外能力；
- 切换语义统一为"改 XXX_HOME + 收敛 PATH"，**不动已装目录**，随时能切回去；
- 带数据的中间件（mysql/kafka/postgresql/elasticsearch/tomcat…）在 `Component.data_note`
  里写清了数据在哪、删目录会不会丢，卸载确认框里逐字展示。
- 真正的"多版本"能力与"厂商是否支持同机多实例"无关：我们只管理各版本的安装目录与
  生效版本指针，不负责让它们同时跑。

`MULTI_VERSION_KEYS` 退化成"历史上哪些组件是原生多版本"的记录（空集），`multi_version`
恒为 True。护栏：`test_all_components_are_multi_version`、`test_every_component_has_the_attribute`。
**R3.9 里的 `multi_version` 门控代码仍保留**（7 处）—— 它们不再是"保护非多版本"，
而是"组件级 vs 启动级"两套路径的分工，删掉会让 jenkins/nacos 走错分支。

**卸载目标解析**（`Component.resolve_uninstall_target`）：全部组件统一为
"选了没装的版本、磁盘上又装着多个 → 按语义降序卸最高的并把换了什么说清"。
不再有罢工分支——多版本的前提就是"装着好几个"，罢工等于卸载失灵。
护栏：`test_uninstall_target_picks_the_highest_when_selection_is_not_installed`。

**新增：`Component.data_note`（组件级，11 个带数据的中间件）**。与 `LaunchSpec.data_note`
（启动级，jenkins/nacos/activemq 三个一键启动组件）并存，`uninstall_confirm_text()`
两处都读、组件级优先。**只写实测过的事实**，没在本机装过的组件写"未实测"，
不许凭印象编数据目录 —— 写错会让用户以为数据在别处、真需要时找不到，
或反过来误以为会丢而不敢删。护栏：`test_data_bearing_components_all_have_a_data_note`、
`test_uninstall_confirm_text_shows_the_data_note`。

**一条仍然有效的豁免**：「安装」的"选中版本已装则置灰"对全部 26 个组件生效，
### R3.10 下拉框清单必须包含"已装但清单里没有"的版本

在线版本清单只保留近期版本（实测：bun 清单里已无 1.4.1，磁盘上却装着 `bun-1.4.1`）。
下拉框清单由 `ComponentCard._combo_version_list()` 统一生成 = 内置/在线清单 +
`installed_versions()` 里清单外的版本（按语义版本插入，文本就是版本号），
`_reload_combo_items`、`_current_version`、`_refresh_installed_marks` **三处必须共用它**——
不一致就会出现"下拉框显示着 1.4.1、反查却落回 1.4.2"，用户以为在切 A 实际配出去的是 B。
`_detect_status` 在增减已装集合后按行数比对重灌一次（放在 `if ordered` **之前**，
否则最后一个额外版本被卸掉时那一行永远摘不掉）。合成项没有下载 URL，靠 R3.11 的
"已装置灰安装按钮"兜住；非多版本组件不合成（R3.9）。
护栏用例：`InstalledVersionNotInCatalog`（7 条）。

### R3.11 选中版本已装则置灰「安装」

面向**全部 26 个组件**：`_installed_here(version)` 判"目录存在 **且** 里面找得见该组件可执行文件"
（半截安装不算，否则按钮灰掉、卸载又无事可做，用户会被困死），已装时禁用安装按钮，
tooltip 写清装在哪、并指路「要重新安装请先点卸载」。
状态由 `_sync_action_buttons()` 统一计算，三个触发点：`_detect_status` 之后、
下拉框换选中之后（`currentIndexChanged`）、下载结束/失败之后。
下载进行中一律不碰该按钮，否则换个选中就能并发触发第二次下载。
**本条不受 R3.9 约束**（是全局新规则，不得门控回"只多版本组件"）。
护栏用例：`InstallButtonBlockedWhenInstalled`、`SelectionReenablesSwitch`。

### R3.12 切换成功后必须点名"比这次切换更早、还开着的终端"

Windows 把环境块**复制**给新进程，所以"复验通过"和"用户屏幕上还是旧版本"可以同时为真——
2026-09-30 真机实测就是这样：注册表与新进程都是 1.4.1（由 explorer 现场启动的探针 `bun -v` → 1.4.1），
用户那个 PowerShell 进程却创建于切换前 12 分钟，而且 `OpenProcess` 返回 error 5（管理员窗口，
UIPI 挡着我们的 `WM_SETTINGCHANGE`，环境块还是登录时那一份）。光在日志里讲"要重开终端"没用，
用户已经"重开"过了。

所以 `_log_verification_hint(since_epoch)` 必须把 `list_shell_processes()` 的结果按"创建时间早于本次切换"
过滤后**点名到 pid 与起始时间**，管理员窗口单独标注"本工具的通知进不去"。两个函数分工：
`list_shell_processes()` 是唯一的外部接缝（失败返回 `[]`，调用方按"没测到"处理，**不许**当成"没有旧终端"），
`stale_shell_lines()` 是纯函数（过滤、排序、限 6 条、排除自己），逻辑都堆在纯函数这边便于断言。
这条信息只能以 **info** 级输出——它是附加说明，写成 warn 会让"复验通过"的用例凭空多一条告警。
扫描失败绝不影响切换本身（`_apply_active` 仍返回 True）。护栏用例：`StaleTerminalNotice`（7 条）。

### R3.13 必须提供"必然干净的环境"验证入口

R3.12 只能告诉用户"哪些窗口是旧的"，回答不了"那到底切对了没有"。顶栏 `btn_clean_terminal`
（「🖥 开验证终端」）用 `EnvManager.composed_env()` 现算的那份环境块起一个 `cmd.exe`
（`open_clean_console(env)`，`CREATE_NEW_CONSOLE`），这个窗口里的版本号就是任何全新终端应当看到的版本。

三条硬约束：
- **拿不到合成环境就不许开**（`composed_env()` 返回空 ⇒ 只写 warn 并给出原地刷新的 PowerShell 命令）。
  退化成用本进程 `os.environ` 开出来的窗口，验证价值为零，还会给出错误结论。
- 开不了（`Popen` 抛异常）要 `error` 级说明，不许静默。
- `open_clean_console()` 是唯一副作用接缝；有一条用例真桩 `subprocess.Popen` 钉住
  `env` 与 `creationflags` 两个参数名——写错了只有用户点下去才会炸。

护栏用例：`CleanTerminalWindow`（8 条）。

**加标题栏按钮要重量最窄窗口**：标题栏（标题 + 按钮 + 窗口控制）实测需要 ~992 像素，
而窗口最小宽原本只有 880 —— 布局早就在挤压标题文字，多一个按钮后开始把
「清理残留 PATH」压到裁字（178→144）。已把 `setMinimumSize` 抬到 1000（正好等于默认宽），
并给四个文字按钮设 `QSizePolicy.Fixed`。`test_title_bar_buttons_are_not_clipped_at_minimum_width`
钉住这条；注意 `QLabel.setMinimumWidth(0)` 和 `QSizePolicy.Fixed` **都挡不住**总宽不足时
布局的挤压（实测仍裁字），唯一有效的是把窗口最小宽抬到实际需要的值。

### R3.14 两个一键脚本都不许为 WMI 阻塞用户

`main.py` 已改用 `sys.platform` / `PROCESSOR_ARCHITEW6432` 判断系统与架构（R3 之前的启动卡死修复），
启动路径上没有任何一步会问 WMI。

- **`一键启动项目.bat`**：WMI 自检从"15 秒 + 再等 120 秒"改成**只探 2 秒、超时也只提示不等待**。
  实测本机 WMI 冷启动时：改前白等最多 135 秒，改后 2.3 秒继续；把探针换成必然返回 0 的对照组
  只要 0.4 秒且一行提示都不打（不制造假告警）。
- **`一键打包exe.bat`**：那段等待**整块删掉**，改为走 `pyinstaller_no_wmi.py`。
  这里曾是真依赖（PyInstaller 导入期读 `platform.win32_ver()[0]` 来定 `is_win_10 / is_win_11`），
  但正确解法不是等 WMI，而是让标准库自己那条**不查 WMI 的退路**走通：把 `platform._wmi_query`
  换成"立刻抛 OSError"就行，版本号仍由标准库算
  （本机实测 `('11', '10.0.26200', 'SP0', 'Multiprocessor Free')`，与走 WMI 的判据一致）。

**关键陷阱（踩过一次，代价 38.7 分钟）**：PyInstaller 6.x 的分析跑在
`PyInstaller/isolated/_child.py` 这个**独立子进程**里，父进程改过的 `platform` 它看不见。
只桩父进程实测打包耗时 **2394 秒**（子进程排队等冷 WMI，不是永久卡死，但等于不可用）；
桩传到位后 **127 秒**跑完，产物 exe 6.9 秒起窗、正常退出。
所以桩必须由 `install_child_bootstrap()` 生成一个带 `sitecustomize.py` 的目录塞进 `PYTHONPATH`
最前，让**每个子进程启动时自己装上**；该 sitecustomize 还要链式执行别处原有的
`sitecustomize.py`（我们排在最前，不许悄悄抢位）。
护栏用例：`PackagingEntryNoWmi`（3 条）+ `PackagingChildProcessesNoWmi`（3 条，含"不注入时
子进程确实会去问 WMI"的对照组，以及对冷 WMI 的**确定性模拟**——子进程里 `_wmi_query` 必须立刻抛、
`win32_ver()` 必须 5 秒内算出结果，不用赌机器上 WINMGMT 的状态）。
注入目录用完由 `main()` 的 `finally` 删除，测试里也要 `addCleanup`，否则 `%TEMP%` 会堆垃圾
（实测漏过 4 个）。

### R3.15 环境写完必须**点名**通知外壳，`HWND_BROADCAST` 那条路是无效的

`_broadcast_env_change()` 过去只发 `PostMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment")`。
2026-09-30 真机实测证明它**对 explorer 完全不起作用**：注册表已改成 `bun-1.4.2`，
explorer 的环境块 1/3/6 秒后仍是 `bun-1.4.1` —— 于是用户从开始栏、任务栏、桌面开的
**每一个**新终端都继承 explorer 那份旧环境，"重开终端"永远无效（这就是第 3、4 轮真机反馈的总根因）。
改成 `SendMessageTimeoutW(FindWindowW("Shell_TrayWnd"), …, SMTO_ABORTIFHUNG|SMTO_NOTIMEOUTIFNOTHUNG, 3000)`
后，explorer **1 秒内**翻成新值，单次调用只花 0.02 秒。

三条不许回退的点：
- **同步、点名**（`Shell_TrayWnd` + `Progman`）。老注释说"同步会卡住"，那是没带
  `SMTO_ABORTIFHUNG`；带上僵死窗口会被直接跳过。
- `"Environment"` 必须是**同步调用期间活着**的宽字符串缓冲区（`create_unicode_buffer`）。
  异步 PostMessage 正是死在这里：消息排队到 explorer 处理时发送方缓冲区已回收，
  它读到的不是 `Environment` 就直接忽略。
- 给其它顶层窗口（IDE 这类自己监听环境变化的）那一路走 `HWND_BROADCAST`，
  放**后台线程**、超时 1 秒，不许拖住点按钮的人。

`notify_shell_environment(user32=None)` 的 `user32` 参数是注入接缝（不是运行时开关）：
测试传假对象即可断言"发给谁、带什么标志、lParam 指向哪个字符串"，并钉住**不再使用 PostMessageW**。
护栏用例：`ShellRefreshNotification`（4 条）。

**本规则的盲区（2026-10-09 补，见 R3.20）**：广播当时只挂在用户级写入口 `write_user_env_raw()`
里，**提权改 HKLM 的那几条路径一声都没出**，于是"切换成功 + 复验通过 + 用户新终端仍是旧版本"
这种事照样发生。判断"有没有通知到"要看**每一条改动路径**是不是都喊了，不能只看有没有这个函数。

### R3.16 端到端验收要跑真机演练脚本，单元测试不算数

`tools/bt_real_machine_drill.py` 是唯一允许碰真注册表的验收手段（默认只读体检，加 `--yes` 才切换，
且结束时必然还原回演练前的生效版本并逐字比对基线）。它验的是三层，缺一层都不算通过：

1. **注册表真值** —— 产品写完后的持久层；
2. **explorer 自己的环境块** —— 直接读它的 PEB（读法见脚本注释：`EnvironmentSize` 可能为 0，
   要分块读；一次读太大块会整次失败并把"有"误报成"没有"）；
3. **由 explorer 现场启动的探针进程** —— 这才是"用户从开始栏/任务栏新开终端会看到什么"。

为什么第 2、3 层不可省：2026-09-30 那次，第 1 层全对、`composed_env()` 复验也"通过"，
而 explorer 揣的还是旧环境块，用户重开终端永远是旧值 —— 只看注册表的验收当场失效。
反过来，只看"我这边新开进程对不对"也不够：本机同时挂着 9~12 个 explorer 实例，
只有当前主 shell 会响应通知，其它实例是死的（演练输出里那些 `(没有 BUN_HOME)` 就是它们）。

同轮真机演练还抓出一条假日志：`remove_path_entries_under` 按"本组件根目录下"整片清扫，
生效版本自己那条也会被摘掉再重加，旧文案却一律写成"已移除同组件其他版本的条目"，
于是出现过"目标是 1.4.2、日志说移除了 1.4.2"这种自相矛盾的话。
现在点名前先用 `_same_path` 排除生效版本自己，全被排除就整行不打
（护栏用例：`SwitchActive.test_switch_to_the_version_already_on_path_does_not_claim_a_removal`、
`test_removal_line_names_only_the_versions_that_really_left`）。

### R3.17 外部版本只读发现：永不进下拉框、永不参与卸载

用户自己装的版本（`E:\soft\jdk\jdk17` 这种，不在本工具工作目录里）只允许被**只读地发现**：

1. **发现只读**：`discover_version_candidates()` 只枚举环境变量、两 hive 的 PATH 条目、
   以及 Python 的 `py -0p` / 注册表 `InstallPath`。跑一遍发现，注册表与 `config.json`
   都必须**一个字节不变**（护栏用例 `RegressionGuardTests.test_discover_does_not_mutate_any_state`）。
   外部候选还必须**真跑一次版本命令**才算数 —— 探测不出来的直接丢弃并记一行 warn，
   宁可少显示一个，也不显示一个"认错了的目录"。
2. **永不进下拉框**：版本下拉框的条目文本是版本反查的唯一键（`_current_version()` /
   `repopulate(preferred=…)`），把 `17.0.12` 这种外部版本塞进去会让选中、安装、卸载、
   保存配置全部错位（R3.4）。外部版本只在卡片底部那个折叠区里出现。
3. **永不参与卸载**：`installed_versions()` 只看 `CONFIG_DIR/<key>/<key>-<version>`，
   卸载候选永远不含外部目录，卸载也**绝不删**外部目录。用户自己装的东西，本工具不碰。
4. **适用范围是白名单**：`EXTERNAL_TAKEOVER_KEYS` 只登记 7 个（jdk / python / node / go /
   maven / gradle / bun），且与 `bt_multiversion_tests.EXPECTED_MULTI_VERSION` 是同一份名单。
   不要拿 `comp.multi_version` 当门槛 —— 它自 2026-06-06 起恒为 True，等于对全部 27 个组件
   都开了"改用户系统 PATH"的入口。加一个 key 就要同步改两处，护栏用例会拦。

### R3.18 改系统环境变量必须五件齐全，缺一不许调用

进程 PATH 的合成规则是「系统段整体在前 + 用户段整体在后」（2026-09-30 真机实测），
所以**只写用户级永远压不住系统级同名条目** —— 本机 Maven 就是活例：HKCU 那条写得再对，
`mvn -v` 仍是系统 PATH 里那条。要真切换就必须动 HKLM，而**把系统 PATH 改坏的后果是整机
命令找不到**。因此任何一次动系统变量的代码路径都必须五件齐全：

1. **原文快照**：一律 `winreg.QueryValueEx` 读**未展开原文**并记下类型；还原时
   `existed=false` 的键要**删除**而不是写空串。快照另存一份独立备份文件
   （`takeover-backups/<key>-<stamp>.json`）—— `config.json` 被写坏时它是唯一的退路。
2. **最小编辑**：只在原文上做「整条删除 / 整条插入」，分隔符固定 `;`，
   **不重排、不去重、不改大小写、不合并重复项**。默认只做**插入**（插到最前就足以让命令行
   命中目标），不删任何原有条目。
3. **关键条目校验**：改前先自检一次（不合格就一个字都不写），改后重读原文再自检一次：
   条目数对得上、新增条目在最前、原有条目（除被删的）逐字找得到、含 `system32` / `\Windows`
   的关键条目还在。少任何一条 → 立即用快照回滚 → 报"已放弃，系统 PATH 未被改动"。
4. **复验**：靠 `EnvManager.composed_env()`（`CreateEnvironmentBlock`）看命令行**实际**
   会命中谁，三态 `ok` / `shadowed(点名抢命令的目录)` / `unknown`。`unknown` 一律按
   "未能复验"处理，**不许当成通过，也不许为它升级去弹 UAC** —— 拿不到结论不等于失败。
5. **可还原**：`takeover[key]` 里存着两 hive 的原文快照，卡片上常驻「还原到我之前的设置」，
   重启后仍在。`active`（工作区登记）与 `takeover`（外部接管）**两条键互斥**：
   切外部 ⇒ 删 `active`；切回工作区 ⇒ 先 `revert_external_version()` 再写 `active`。
   不允许出现"登记表说工作区 21、系统 PATH 最前还插着外部 17"这种两边都不认的孤儿态。
   （另一条键 `machine_fix` 与 `active` **并存**，语义完全不同，见 R3.19。）

两条配套约束：

- **绝不用 `os.environ["PATH"]` 或任何展开后的值参与写入**。那会把 `%JAVA_HOME%` 这类
  占位符固化成死路径，是"把系统 PATH 改坏"的头号方式；写回也必须保持原 `REG_EXPAND_SZ` 类型。
- **UAC 取消（`ShellExecuteW` 返回 1223）≠ 失败，超时也 ≠ 失败**。取消要报"已取消、未做任何
  改动"并零留存；超时后主程序必须**自己重读注册表**判定实际状态，再决定"报成功并补写快照"
  还是"报失败并回滚"。
- 提权助手的调用点抽成可替换函数 `_run_elevated_helper(request)`，测试换成假助手即可离线
  覆盖 ok / 取消 / 超时 / 丢条目全部分支，**产品代码里不加任何运行时开关**。
  护栏用例见 `bt_external_version_tests.py`（79 条 = R3.17/R3.18 的 60 条 + R3.19 的 19 条，
  后者含 R3.20 要求的外壳通知断言），真机验收仍走 R3.16 的演练脚本。

### R3.19 切换被系统段压住时，本工具必须自己解决（能救就救，救不了才开口）

**触发这件事的真机证据（2026-10-08 实测本机）**：

```
HKLM Path  [6] = E:\soft\maven\apache-maven-3.9.2\bin      ← 用户自己装的
HKLM MAVEN_HOME = E:\soft\maven\apache-maven-3.9.2
HKCU Path  [6] = C:\Users\E5430\.env-tools\maven\maven-3.10.0\bin   ← 本工具写的
```

用户在卡片上把 Maven 切到 3.10.0，本工具只写用户级，命令行命中的仍是 3.9.2。那时卡片打印的是
「**本工具不改系统级环境变量**：要让所选版本真正生效，需要在「系统变量」的 PATH 里删掉/后移那条」
—— 用户当场反问："做这个软件的目的就是以用户的操作为准，为什么还提示让用户自己去改"。**这句话是错的**：
本工具**已经具备**改系统变量的能力（R3.18 的提权助手），只是当时没有接进"普通切换"这条路径。

所以本规则要求：`_apply_active` 复验得到 `shadowed` 时，必须按**抢命令的那条写在哪一段**分三种情形处置，
**不许一律把活退回给用户**。判据是纯函数 `shadow_location(shadow)`：

| 抢命令的那条写在 | 结论 | 本工具该做什么 |
|---|---|---|
| 用户段（HKCU） | 用户段内部先后问题 | `prepend_user_path_entry()` 把我们那条让到用户段最前，再复验。**零提权** |
| 系统段（HKLM） | 用户级永远压不住 | 弹确认框 → UAC → 把工作区的 bin 目录插到**系统 Path 最前**，再复验 |
| 两段都找不到 | 病灶不在 PATH 两段里 | **不提权**，如实报告并说明为什么本工具不接手 |

硬约束：

1. **只在白名单组件上做前两步**（`EXTERNAL_TAKEOVER_KEYS`，R3.17 的同一道闸）。非白名单组件维持
   "只报告"的老行为 —— 否则等于给全部 27 个组件开了"弹 UAC 改系统 PATH"的入口。
2. **`shadow_location` 展开系统变量时必须用 HKLM 自己的值**（`expand_machine_value()` 递归展开），
   **不许用 `os.path.expandvars`**：那用的是本进程环境块，而系统 PATH 里那条 `%JAVA_HOME%\bin` 是
   Windows 按**系统**表展开的（本机还是嵌套的：`%JAVA_HOME%` → `%jdk21%`）。判错的代价是白白弹一次
   UAC，或者该提权时没提、用户继续被压住。
3. **改动内容与 R3.18 逐条一致**：仍然只做"整条插入到最前"，**一条原有条目都不删**。用户自己装的
   3.9.2 仍留在系统变量里，只是排到后面 —— 这既是最小改动，也让"还原"永远有意义。
4. **登记表另起一条键 `machine_fix`，与 `takeover` 是两回事**：
   - `takeover` = "把**用户在别处装的那份**设为生效版本"，因此**与 `active` 互斥**；
   - `machine_fix` = "为了让**工作区版本**赢过系统级同名条目而改过 HKLM"，生效版本仍是工作区那个，
     **`active[key]` 必须留着，两条键并存才是正确状态**。
   把两者混用会立刻产生假状态：界面上说工作区 3.10.0 生效、还原按钮却说"当前生效的是系统里那个 3.10.0"。
5. **两笔账必须"先还原再动"，且是公共前置步骤**：`release_machine_state(comp, log, reason)`
   统一还原 `takeover` 与 `machine_fix`，**两个入口都要调**：
   - 切回/切到工作区版本之前（`_apply_active`）；
   - **接管另一个外部版本之前**（`switch_to_external_version`）。
   不还原的话系统 Path 最前还插着上一次改的目录，复验必然命中它（"报成功、命令行却是旧版本"）；
   更糟的是**两次快照会互相覆盖**：`machine_fix` 记的是"插入我们的 3.10.0 之前"的原文，
   此时再叠一次接管，按 `machine_fix` 还原会把接管插的那条一起抹掉，注册表回不到**任何**一次改动前的状态。
   先还原再动，稳态里系统 Path 永远没有本工具留下的条目；新版本若仍被压住，会重新征求一次提权。
6. **卸载前必须收尾**：若 `machine_fix.home` 正好是要卸载的那个版本，先按原文还原再删目录。
   否则系统 PATH 最前会留下一条指向已删目录的**死条目**，比"没生效"更糟。
7. **取消/拒绝一律零改动**：用户没点确认框、或在 UAC 上点了否 → 系统变量逐字节不动、不留登记、
   连助手都不许调用；复验不通过 → 自动按原文还原 + 不留登记，**绝不报成功**。
8. 还原入口复用卡片上常驻的「↩ 还原到我之前的设置」（`machine_fix` 存在时同样常驻），
   按原文逐字节写回（含值类型）。用例见 `bt_external_version_tests.WorkspaceMachineFixTests`。

### R3.20 提权改完系统变量后，主进程必须补一声通知（R3.15 的那条规则有个盲区）

**真机证据（2026-10-09 本机 Maven）**：用户把 Maven 从自己装的 3.9.2 切到工作区的 3.10.0，
R3.19 的提权路径确实把 `C:\Users\…\.env-tools\maven\maven-3.10.0\bin` 插到了 HKLM Path 最前，
注册表回读、`composed_env()` 复验、软件内「开验证终端」全都是 3.10.0 —— 但用户**切换之后新开的
cmd** 里 `mvn -v` 仍是 3.9.2。逐进程读环境块（R3.16 那套 `ReadProcessMemory` 手法）量到：
当时**每一个活着的进程**、包括全部 explorer 实例，PATH 顺序都还是 `[3.9.2, 3.10.0]`。
也就是说"改动写进了注册表"和"新进程拿得到改动"之间那一环没人负责。

根因是 R3.15 的通知只挂在**用户级写入口**上：`write_user_env_raw()` 内部自己调
`EnvManager._broadcast_env_change()`，所以用户级改完必然通知；系统级是**提权助手子进程**直接写
HKLM 的，主进程拿到回报后只做了复验和登记，**一声没出**。于是代码里 `_broadcast_env_change()`
当时只出现在还原路径上，四条系统级改动路径（接管、工作区提权、自动回滚、还原）全是静默的。

硬约束：**凡系统级（HKLM）改动成功，主进程必须走 `_announce_env_change()`**，四个点一个都不能少：

| 位置 | 为什么这里必须喊 |
|---|---|
| `apply_external_version_machine()` 成功尾 | 接管生效，否则用户新终端还是旧版本 |
| `apply_workspace_machine()` 成功尾 | R3.19 的提权切换，就是本次踩到的那条 |
| `revert_machine_only()` 回报 ok 时 | 自动回滚与「还原到我之前的设置」也改过 HKLM —— 还原方向不喊，用户会看到"明明还原了，终端里还是新版本" |
| `revert_external_version()` 系统段还原成功后 | 用户段还原若在这之后抛异常会提前返回，不能指望函数尾部那次 |

两条边界：

1. **没改动就不许喊**（UAC 取消、超时且复验未生效、确认框被拒）：护栏用例
   `test_uac_cancel_leaves_the_system_path_untouched` 断言 `broadcasts == []`。乱喊会让外壳
   重建环境块，白白给全机进程做一次无意义的刷新。
2. **通知失败绝不改变结论**：注册表已经写对，`_announce_env_change()` 内部 try/except 静默，
   不许因为广播异常把一次成功的切换报成失败。广播本身按 R3.15 走"同步点名 + 后台扫其余窗口"。

沙箱接缝：`bt_external_version_tests` 把 `EnvManager._broadcast_env_change` 换成记录桩
（`self.broadcasts`），所以断言的是"有没有请求通知"这个副作用，真机不会收到任何消息。
提权助手在测试里被换成假助手（`install_fake_helper`），**接缝位于助手层而非调用点**，
因此通知必须由调用方发起才算被覆盖到 —— 把广播塞进 `_run_elevated_helper()` 会让全部用例绕过它。

### R3.21 版本下拉框的展开状态必须由控件自己记账，`view().isVisible()` 不可信

**真机反馈（2026-10-09 用户）**：「版本下拉如果没被鼠标选中，点第一次能弹出来列表，
点击一次选中之后，再点一次就弹不出来了」，随后又补「偶尔还是有些弹不出来，点几次后又好了」。
两层原因叠在一起，任何一层单独修都不够：

1. **`self.view().isVisible()` 这个判据本身就是脏的**。Qt 的 popup 容器与它内部的 view
   可见性不同步，两个平台给出**互相矛盾**的结论：offscreen 里选中之后卡在 `True`
   （于是再点一次走 `hidePopup()` 分支 → 把已经收起的 popup 又收一次 = 用户看到"弹不出来"）；
   真实 Windows 里明明展开着却报 `False`。
2. **记账会失同步**。只在覆写的 `showPopup()` / `hidePopup()` 里记，但点到别处、窗口失焦、
   容器自己 hide 时 Qt **不走**这两个入口 → 记账停在"开着" → 下次点击又变成"再收一次"。
   这就是"多点几次才好"：第一次点收起（假动作），第二次才弹。

四条不许回退的实现约束：

- 判据是 `_popup_is_really_open()` = **记账说开着 且 容器确实可见**，两个条件缺一不可。
  只信记账会失同步，只信可见性就退回第 1 条那个脏值。
- 记账必须在 `super().showPopup()` **之后**、`super().hidePopup()` **之后**：放前面会把
  "没弹成功"也记成展开，下一次点击就成了收起。
- 事件过滤器装**三处**，少一处就漏一种点击位置：`lineEdit()`（文本区）、`self`
  （右侧箭头那 28px 与内边距 —— 箭头 label 是鼠标穿透的，事件落到 combo 上）、
  `view()`（用 `Show`/`Hide` 兜住 Qt 自己的收起路径）。只装 `lineEdit()` 时点箭头会走
  QComboBox **原生 toggle**，和记账打架。
- 在 `MouseButtonPress` 里**不许当场** `showPopup()`：主窗口很可能还没被激活（窗口系统的激活
  发生在 press 之后），native popup 会被紧接着的"窗口被激活"立刻关掉 —— 同样是"点了没反应"。
  要 `QTimer.singleShot(0, …)` 推到下一个事件循环，并且控件可能已析构，得静默兜住 `RuntimeError`。

产品口径（用户明确要求，写进注释）：**框内任何位置的点击只负责"弹出"，不做开/关切换**；
收起交给 Qt 原生行为（选中某项 / 点到外面 / Esc）。去掉切换之后这件事变成幂等的，
没有任何状态可失同步。护栏用例：`VersionComboPopupReopens`（9 条，含"记账停在 True 但容器
已收起时点击必须展开""连着几轮点开→选中→再点开每轮都必须弹开"）。

### R3.22 `path_subdir` 必须由**归档实测**背书，并且每次装完自检

**真机证据（两连击）**：

- 2026-10-09 Python：Windows 装的是 embeddable 包（`python-3.x-embed-amd64.zip`），
  `python.exe` 就在解压根目录、包里**压根没有 `Scripts`**，而组件声明写的是 `path_subdir="Scripts"`。
  后果不是"显示不好看"，是**整条切换链白做**：PATH 指向一个没有解释器的目录 →
  `python` 永远命中机器上自己装的那份 → R3.19 提权把这条没用的目录插到系统 PATH 最前，
  复验照样命中机器上原有那个 → 自动回滚，用户连着看到两次"系统变量已改，但复验未通过"。
- 2026-10-10 全量实测又抓一个同类的 **Node**：官方 `node-v20.15.0-win-x64.zip` 里
  `node.exe` 同样在 `node-vX.Y.Z-win-x64/` 这一层，**没有 `bin` 子目录**，而声明写的是 `"bin"`。

所以硬约束是三条：

1. **新增或改动组件时，`path_subdir` 要跑 `tools/bt_archive_layout_audit.py` 实测**，不许按惯例猜。
   手法：zip 的中央目录在文件**尾部**，用 HTTP Range 只取几 KB～几 MB 就能列出全部条目
   （JDK 一个包 190MB，不必下载）；tar.gz 是流式、无法随机读，就按预算（40MB）顺着读，
   超预算只能判 `UNKNOWN` —— **拿残缺清单判失败等于凭空造一个假 bug**。
   单二进制 / `.war` / `.exe` 安装器没有目录清单，明确标 `SKIP`。
   判据与产品一致：`_exec_name_variants()` 里那些名字，**在 `_external_bin_dir()` 说的那个目录里**存在才算过。
2. **每次安装解压完立刻自检**：`verify_bin_dir(comp, home)` 返回 `(是否在声明目录, 实际位置)`，
   指错时日志当场点名"实际它在 …\python-3.15.0\python.exe"，并说明"这会让切换生效版本失效、
   请把这段日志发给开发者"。这类错在界面上只表现为"切了但没生效"，用户无从自查，
   所以必须让**下一次反馈自带根因**，而不是我们再去猜。
3. **期望表钉进测试**：`bt_multiversion_tests.WindowsPathDirsMatchTheRealArchives` 里
   `EXPECTED_WIN_SUBDIR`（2026-10-10 实测）+ `NOT_AUDITABLE`（归档类型审不了的 4 个：
   kafka / pulsar / seata 是 tar.gz、docker 在 Windows 无免安装形态）。
   `test_every_windows_component_is_accounted_for` 保证**新组件不会悄悄漏在表外**；
   Unix 的 node / python 仍在 `bin/`，有专项用例挡住"Windows 的改动顺手带到别的平台"。
4. **可执行文件的名字同样要实测**。同一轮审计在 Linux/macOS 上抓到：
   apache-tomcat 的 `bin/` 里**没有**不带扩展名的 `catalina`，只有 `catalina.sh` 与 `catalina.bat`，
   而 `_exec_name_variants()` 在非 Windows 只返回裸名 —— 于是 Linux/macOS 装完 tomcat 后
   连入口都找不到（卡片状态与版本探测全落空）。现在 POSIX 的候选是 `[裸名, 裸名 + ".sh"]`，
   **裸名仍排第一**（`python3` / `gradle` 这类有裸名的别被挤到后面）。
   用例：`PosixExecNamesCoverTheShellScript`（3 条，含"Windows 那套 PATHEXT 展开不许被带偏"）。

### R3.23 自动装的前置运行时，装完必须**当场能用**（HOME + PATH 都要写，失败不许说"不影响启动"）

`needs=("jdk",)` 的 java 系组件（nacos / jenkins / kafka / rocketmq / seata / activemq）与
`prereq=PrereqSpec` 的 rabbitmq（Erlang），在缺依赖时会**自动排队先装**。以前装完只做一件事：
调 Windows 专用的 `set_windows_user_env(pre.env_var, …)` 写一个 HOME 变量 ——
**不写 PATH**，Linux/macOS 上连 HOME 都不写，而失败时日志写的是"不影响启动"。
对 java 系恰恰相反：`startup.cmd` / `seata-server.bat` / `catalina.bat` 都自己读 `%JAVA_HOME%`，
写不上就是起不来，用户看到的就是"依赖明明装好了，启动还是失败"。

改成 `_configure_prereq_env(pre, final)`，四条：

1. **HOME 与 PATH 都写**，且按平台走各自的写入入口（Windows 写 HKCU，Unix 写 rc 文件）。
2. **写完核对**：复用 R3.22 的 `verify_bin_dir`，声明目录里没有可执行文件就点名报出来。
3. **失败如实上报并中止启动流程**（`_on_prereq_failed`），**不许**再打"不影响启动"。
4. 启动侧那一份 env 注入**保留不动**：`build_launch_plan()` 会把 `JAVA_HOME`
   （以及 Erlang 的 `ERLANG_HOME` + 把 erl 的 bin 前插进**这个子进程的** PATH）注进子进程环境。
   两条路各有各的用处：注入保证"本工具点启动一定起得来"，写注册表保证"用户自己的终端里 java 也能用"。
   少任何一条都是半截子（2026-10-06 的 rocketmq 与 rabbitmq 停止失败各查过一次）。

护栏用例：`PrereqRuntimeIsReallyUsable`（Windows / Unix 各一条，断言 HOME 与 PATH 都写过）。

---

## 规则 R4：一键脚本自举契约

### R4.1 规则描述

`一键启动项目.bat` 与 `一键打包exe.bat` 对用户的承诺是：**下载本项目 → 双击脚本 → 什么都不必手工做**。
"什么都不必手工做"包含最前面那一环：机器上一个可用的 Python 都没有时，脚本自己装一个，
而不是打印"请去 python.org 下载"。任何把环境准备退回给用户的文案与分支都算违约。

### R4.2 适用范围

- 根目录两个 `.bat` 与它们的 `assets\msg_zh.txt` 消息表
- `同步Gitee产物.bat` / `同步Gitee产物.sh` 只借用本规则的第 1、4 条（纯 ASCII、外部调用加 `call`）
  与"别把手工步骤退回给用户"这条精神：产物目录不存在要自己建，缺产物要自己去下载
  （加速器优先、github.com 末位，见规则 R1），不再打印 `mkdir` + 四条 `curl` 让维护者手跑。
  用户自举部分（找/装 Python）不适用——那是维护者本机脚本，普通用户不碰
- 不适用于 macOS / Linux（那两个平台的脚本自举不在本规则内）

### R4.3 硬约束

1. **`.bat` 全文 100% 纯 ASCII**。cmd.exe 用字节偏移记录它读批处理的位置；多字节内容 + 中途 `chcp 65001` 会让偏移错位，于是从行的中间开始解析，`REM`/`echo` 被当命令执行，整条语句被吞。这不是显示问题，是**语句有没有跑**的问题
2. **中文文案是数据**：放 `assets\msg_zh.txt`（UTF-8、LF、`key=value`、值里不含 `!`），用 `call :say key "英文兜底" "{0}实参"` 打印。英文兜底里不得出现 `& | < > ( ) ^ "`——它走解析期插入，表值不走
3. **语言判定 fail-open**：抓 OEM 码页要在 `chcp` 之前；再用 `reg query "HKCU\Control Panel\International" /v Locale` 取 LCID 末 4 位判中文；任一环节不成立或消息表缺失 → 英文
4. **外部调用一律 `call`**：不带 `call` 调用另一个批处理，控制权不返回。`python.bat`/`curl.cmd`/`winget.cmd` 这类垫片会当场终止脚本
5. **解释器版本区间只有一处真源**：3.10–3.14，来自 PySide6 的 `requires_python`。越界版本一律不选，选了就等于把"依赖装不上"丢回给用户
6. **自动安装链不许有短路出口**：`py` 显式版本 → `python`/`python3` → 固定目录 → `for /d` 通配扫 `%LOCALAPPDATA%\Programs\Python\*` 与 `%ProgramFiles%\Python*` → 全空才 `winget`（`where` 探不到就直接查 `WindowsApps\winget.exe`）→ 再下载官方安装包，顺序 **华为云 → npmmirror → python.org**（R1 的镜像优先 + 官网末位同样适用于这里），装完 30 秒内有界复扫
7. **下载结果必须校验体积**：`< 5 MB` 判该源无效并换下一个。镜像会用 200 + 小 HTML 应付缺失文件，不校验就装出一个坏解释器，比失败更难查
8. **自动安装不写 PATH**：`InstallAllUsers=0 PrependPath=0 Include_launcher=0`。发现逻辑读安装目录，写 PATH 既不必要也违背"不修改系统环境"
9. **`.bat` 必须 CRLF**：LF-only 会让标签查找失败（实测 `cannot find the batch label specified`）

### R4.4 失败处理

`:err_no_python` 只允许在第 6 条整条链走完仍然没有解释器时到达，且文案顺序必须是：① 脚本已经自动试过什么 ② 最常见原因（网络/安全软件）③ 恢复后重新双击 ④ 最后才是手工兜底，且不得引导"winget install"当主方案。

### R4.5 新增 / 调整一键脚本 checklist

- [ ] 新增的每一行都是 ASCII；要加中文提示 → 在 `assets\msg_zh.txt` 加 key，脚本里 `call :say`
- [ ] 新调用的外部命令：会不会被 `.bat`/`.cmd` 垫片顶替？会 → 加 `call`
- [ ] 新增的下载：是否排在镜像之后、官网末位，是否有体积/结果校验
- [ ] `bt_boot_script_tests.py` 全绿；改动消息表后确认没有死 key、没有 `!`、仍是 LF
- [ ] 真机验证至少覆盖：本机有可用 Python、模拟"完全没有 Python"（用桩 winget/curl + 假的 `LOCALAPPDATA`）

### R4.6 护栏用例

`bt_boot_script_tests.py`（离线，不执行 .bat，只做静态对账）盯住：纯 ASCII、CRLF、消息表 LF 与 key 双向对账、`{0}` 与实参数量一致、英文兜底无元字符、`chcp` 前抓码页、自动安装在 `:err_no_python` 之前、三源顺序、体积校验存在、`PrependPath=0`、外部调用无裸调用。

---

## 规则 R5：组件一键启动契约

### R5.1 规则描述

可启动组件（登记表 `LAUNCH_OF`）必须做到：**点启动就真的能访问控制台**；**端口是真相、PID 只是提示**；
状态检测与找回**绝不执行启动脚本**；停止超时**只询问强制结束、不自动强杀**；运行中**禁止卸载**。

本规则的落地状态要如实分层描述：框架与 Jenkins / ActiveMQ / Nacos 三件的一键启动**已实现、有离线护栏守护，
且已于 2026-10-05 在 Windows 真机验证**（JDK 21 / Jenkins 2.580.1 / ActiveMQ 6.3.2 / Nacos 2.3.2，
三件各跑完一次 `--launch <key> --yes` 的四层判据：A1 整簇释放 / A2 监听集合等于登记簇 /
A3 控制台路径 / A4 `--server.port` 生效 / A5 前台不弹窗，**全部 PASS**）。
但**macOS 与 Linux 尚未真机验证**，且 A6（`-Djetty.http.port` 能否压过 conf）**仍未尝试**。
文档、README、卡片文案对已验证的平台写"已在 Windows 真机验证"，对未验证的平台仍写
"macOS/Linux 待验证"，**绝不得把三平台一概写成已验证**。

### R5.2 适用范围

- `LAUNCH_KEYS` 里的组件。当前为 `{"jenkins", "activemq", "nacos"}`。
- 不在白名单的组件不得出现启动按钮，也不得被 `ServiceManager` 写入登记
  （`build_components()` 末尾 `comp.launch = LAUNCH_OF.get(comp.key)`，不在登记表就是 `None`）。

**本期已兑现**（这两条不再是回看项）：

- `RunRecord` 新增字段必须带默认值 —— **已做**，见 R5.3 第 8 条与 R5.6 的 `NetstatParse`。
  `ports` 缺省 `()`、归一化放在加载侧（`load_running_map()` 见到 `()` 就按 `(port,)` 补），
  留了旧格式迁移用例；默认值不是可选性，它决定旧 `running.json` 会不会被整批静默清空。
- 端口簇/独立口的表达 —— **已做**，见 R5.3 第 8 条。派生口 `port_offsets`、独立口 `extra_ports`，
  由 `choose_ports` 统一选、`prepare_ports` 统一回写。

**计划一遗留 / 计划二待办**（此处是加下一个可启动组件时唯一要回看的清单，别再散落到别处。
下面这份就是全集）：

- `force_stop` 在 Windows 上发的是信号 `9`，但 Windows 任何非 CTRL 信号都是 `TerminateProcess`，
  诚实值应是 `15`（同一 API，只是退出码误导）——计划二接 shutdown 脚本后这条路径基本不再走。
- 外来记录的存活**只覆盖了一半**：`ZombieMatrix.test_foreign_key_record_survives_reconcile`
  已钉住"形状完好的外来记录（如计划二的 nacos）在 `reconcile` 后仍在文件里"；
  **没测到**的是两种边界 —— ① 外来记录字段畸形（缺字段 / 类型归一失败）时，`load_running_map` 会丢掉它，
  随后任何一次"有僵尸要清"的写盘就把它**永久抹掉**；② "jenkins 是僵尸 + 同时存在外来记录"
  这一交汇下写盘是否保住外来记录（按代码构造是对的，但没有用例）。计划二加组件前先补这两条。
- `running.json` 读写**没有跨进程 advisory lock**，GUI 与演练脚本并跑时最后写的那一方会覆盖前一方。
  计划二把登记面从 1 个组件扩到 3 个、Nacos 还多两个 gRPC 派生口，并发撞上的概率明显上升
  —— 下一个组件接入前必须回看这一条。
- 卡片被销毁时若 `LaunchWorker` 还在跑，没有等待其收尾的用例（worker 现为卡片的 Qt 子对象，
  这是 `closeEvent` 所防的那类 abort 的第二条入口）。当前正常流程不销毁卡片（卡片只在 `__init__` 建一次，
  搜索只做 `setParent` 搬移且 `self.cards` 持有 Python 引用），所以本期不可达 —— 但计划二若加"重建卡片"就要补。
- `_COMPONENTS_CACHE` 为进程级常驻、从不失效（本期描述符运行时不变，可接受）。
- `shutdown_command` 分支本期不可达、零覆盖；其占位符契约只喂 `port/home/data_dir`，
  `{java}/{war}` 一类要计划二接线时补来源，否则 `format` 直接 `KeyError`。
- `launch_label` 的样式没有 QSS 规则，主题切换后可能与卡片底色撞色（显示层问题，不影响判定）。
- 测试里仍有 `"8080"` 字面量散落（夹具与断言中），加新组件时要逐处泛化，否则换端口即假失败。
- 真机 `--yes` 演练，以及由此悬着的计划一 spec §2.4 第 3、5 项、计划二 spec §8.2 的 A1–A7
  与 `min_java_major` 回填。

### R5.3 硬约束

1. `LAUNCH_OF` 是唯一登记处；`build_components()` 末尾统一赋值，构造处不手写。
2. `min_java_major` 只能填实测结论；未实测保持 `None`，门控退化为"有没有 JDK"（当前即为 `None`）。
3. 端口选择走 `pick_free_cluster`：区间内升序、整簇端口同时空闲。
4. `status/adopt/reconcile` 只允许 `socket` + `urllib`；出现 `Popen` / `_probe_version` 调用即视为回归。
5. 脱离进程必须重定向 stdout/stderr 到组件 data 下（`~/.env-tools/<key>-data/logs/byte-tools.out`），
   失败原因要带日志尾巴。
6. 停不下来时返回 `need_force`，由界面问人；未确认不得强杀，也不得清登记
   （`force_stop` 只在"端口确实释放"后才清登记）。
7. `JAVA_HOME` 优先取本工具装的 JDK，其次才退到环境变量。
8. 端口簇的三种角色分开表达：派生口走 `port_offsets`（跟主口位移），独立口走 `extra_ports`
   （自己的基准），"运行中"必须整簇都在听；只判主口会把半死的 Nacos 报成运行中。
9. 端口回写只允许写 `~/.env-tools/<key>-data` 下的副本；厂商官方文件在任何策略下都不被修改。
   锚不到官方默认那一行时**拒改并指名要改哪一行**，不许猜用户的改法。
10. **磁盘上没有已安装版本时「启动」必须置灰**（2026-10-10 用户在"提示 vs 置灰"两案里选的），
    判据就是 `resolve_launch_version(comp) is not None`，禁用原因写进 tooltip
    （"先点「安装」，或把版本切到已装的那个"）。为什么不是"点了再提示"：
    未安装时点启动会先弹一个**端口与风险确认框**，用户做完决定才在日志里看到"没装"——
    那是骗他做一次无用的决定。`on_start_clicked()` 里还留一道同判据的兜底，
    且**必须排在自动装前置依赖（JDK / Erlang）之前**，否则一个没装的组件会先白装一个 JDK。
    用例：`CardLaunchUi.test_start_is_disabled_when_nothing_is_installed`、
    `test_clicking_start_never_auto_installs_a_prereq_for_an_uninstalled_component`。

### R5.4 失败处理

- 没装 / JDK 不足：启动按钮禁用 + tooltip 说明缺什么，不做静默失败。
- 端口簇被占且 `[默认端口, 默认端口+99]` 内找不到整簇空闲位：失败并点名"哪个口被谁占"；
  独立口（`extra_ports`）找不到位时要单独点名是哪个口，不许混进"端口不够"这种含混话。
- 端口回写（`conf_copy`）锚不到官方默认那一行、或改写失败：**拒绝拉起**并在 `reason` 里指名改哪个文件哪一行 ——
  改了配置却没起进程、或起进程时配置没生效，两边状态对不上比"没启动"更难归因。
- 起了但 `startup_timeout` 内**整簇端口**未监听：判启动失败，先 `proc.terminate()` 收尸不留无主监听者；
  收尸失败把"进程可能仍在监听（PID …）"并进 `reason`。
- 停止无响应：Windows 只请示不自动动手（`os.kill` 的任何信号在 Windows 都是强杀），POSIX 先 `terminate`、
  超时才 `need_force` 交界面问人。
- `port_lookup` 停止时端口反查给出的是"同口多 PID"（归属有歧义）或"就是我们自己"：
  **一个进程都不许杀**，当场把"为什么没动手"说清并返回，登记保留 —— 把我们的不作为说成别人的错是不允许的。
- `_adopt_running` 整段 try/except 兜底：`~/.env-tools` 只读 / 被锁 / 磁盘满时只留一条 warn，绝不把工具打不开。

### R5.5 新增一个可启动组件 checklist

- [ ] 在 `LAUNCH_OF` 登记；三平台 `commands` 都非空（未在真机验证的分支要写明）
- [ ] 决定端口策略（`port_writeback`）：`cli_only`（只有命令行 flag）/ `cli_flag`（命令行透传，不碰文件）/
      `conf_copy`（回写 `~/.env-tools/<key>-data` 下的副本 —— 必须锚定官方默认那一行 + 备份 + 幂等，
      **官方文件一个字节不动**；锚不到就拒改并指名要改哪一行）
- [x] 决定端口角色：哪些口走 `port_offsets`（由主口按厂商规则派生）、哪些走 `extra_ports`（自己的基准）。
      **2026-10-06 定：不自动平移端口** —— Nacos 的 gRPC 口由 `server.port + 1000` 派生、
      客户端配置里写死 8848，ActiveMQ 的 61616 被大量中间件硬编码；平移会造成
      「服务起来了但外部客户端一个都连不上」，比起不来更难归因。
      端口被占时**结束占用者**再原地启动，并在日志里指名道姓说杀了谁。
- [ ] 决定 `stop_kind`：`pid`（只有我们自己是服务进程时）/ `port_lookup`（PID 不可信、走端口反查，
      只请示不强杀）/ `shutdown_command`（有正规关闭脚本）
- [ ] 补 `risk_note`（监听地址、默认凭据、首次向导）与 `data_note`（卸载时数据去哪儿，必须点名）
- [ ] 补表完整性用例 + 真机演练 `--launch <key>`（未跑真机前不得把 `min_java_major` 填成数字）

### R5.6 护栏用例

`bt_launch_tests.py`（133 条，全离线，不真起中间件）盯住：
`LaunchSpecTable`（白名单恰为 `{jenkins, activemq, nacos}`、三平台命令非空、白名单外无 launch、
`test_min_java_major_is_none_until_measured` 钉住"未实测不许填数字"、`test_plan_two_fields_default_to_plan_one_behaviour`
钉住"计划二新字段的默认值就是计划一既有行为"）、`RunningMap`（含旧格式记录缺 `ports` 的加载侧归一）、
`PortCluster`（整簇同空才可用）、`NoExecInvariant`（把 `subprocess.Popen` / `_probe_version` 桩成
"一调用就抛"，跑完 `status` + `adopt` 全流程，钉死 R5.3 第 4 条；**并含反向断言**：
`test_detection_paths_never_consult_the_port_owner_table` 钉住端口反查（一次 netstat 调用）
不许出现在检测路径，而 `test_force_stop_actually_consults_it` 反过来钉住 `force_stop` **确实**会调用它 ——
没有这条反向断言，"不许调用"可以靠把调用删干净白赢）、`ZombieMatrix`、`LaunchPlan`
（`JAVA_HOME` 优先自家、回退需校验、门控可行动）、`StartFlow`（重定向、端口被占时结束占用者、超时不留登记）、
`StopFlow` / `TerminateByPidGuard`（非 server 角色 / 负 / None PID 绝不动手、Windows 先请示、
归属歧义时报"无候选"而不是乱杀）、`LaunchWorkerSignals`（`need_force` 独立信号）、`CardLaunchUi`
（运行中禁卸、worker 以 `parent=self` 交对象树、`stop`/`force_stop` 都接 `need_force`）、`MainWindowAdopt`
（`_adopt_running` 在入口不在构造、closeEvent 先 `_cancel_launch_workers`、reconcile 失败不阻断启动）、
`NetstatParse`（netstat 文本解析，含中文表头与 IPv6）、`ConfCopyWriteback`（conf 整目录副本幂等、
只动目标行、锚不到就拒改并指名）、`PortPlanning`（端口固定用官方默认值、被占时结束占用者且指名道姓、`port_offsets`/`extra_ports` 各口角色与失败文案点名每个被占的端口、
失败原因指名是哪个口）。

护栏非空性经变异自检确认（三处已验红，一处**查出是空的**）：
把 `ServiceManager.status` 改回只看 `rec.port` → `test_running_requires_the_whole_cluster_to_be_listening` 变红；
把 `_pick_unique_pids` 改成取 `next(iter(...))` 不判长度 → `test_ambiguous_owner_is_reported_as_no_candidate` 变红；
把 `netstat_listener_pids` 调用挪进 `status()` → `test_detection_paths_never_consult_the_port_owner_table` 变红；
把 `start()` 里的 `if not ok: return StartResult(False, "writeback", ...)` 整段删掉 →
`test_start_refuses_to_spawn_when_writeback_fails` 变红。
全部恢复后 133 条回绿。

> 这条护栏是 Task 11 变异自检第 3 项查出来并当场补上的（补之前是空护栏：把 `prepare_ports`
> 的 `conf_copy` 分支改成"忽略回写失败、照样返回 True"时 129 条全绿）。原因是原有用例只分别钉住两端 ——
> `ConfCopyWriteback` 钉 `set_property_line` / `set_openwire_port` 单独调用时会拒改，
> `StartFlow.test_start_carries_the_conf_copy_notice_to_the_card` 把 `prepare_ports` 整个桩成成功，
> **"回写失败 → `start()` 拒绝 spawn、不留登记" 这条接缝谁也没钉**。
> 现由 `PortPlanning.test_start_refuses_to_spawn_when_writeback_fails` 守住，它走真实 `start()`：
> 官方 conf 缺 `jetty.http.port` 行 → 副本锚不到 → 断言 `state == "writeback"`、
> 原因里指名要改哪一行、`Popen` 一次都没被调用、`running.json` 无残留。
> 写这条用例时踩到的坑：`start()` 读的是 `comp.launch` 而非传入的 spec，
> 忘把 spec 挂到 `comp.launch` 上就会走 jenkins 原有的 `cli_only` 早退分支、用例静默测不到东西。

**保留（本期未实现）**：R5.2 记的两条边界 —— 畸形外来记录被写盘抹掉、卡片销毁等待 worker。
（"形状完好的外来记录能在 `reconcile` 后存活"**已经有用例**了：`test_foreign_key_record_survives_reconcile`，
整枝评审指出本节原先把它误列成待办 —— 这份清单是加下一个组件时唯一要回看的地方，写错比不写更贵。）

---

## 后续规则占位

> 后续新增的开发规则以「规则 R6 / R7 / ...」形式追加到本文件，并在「规则索引」中登记。
> 每条规则必须包含：规则描述、适用范围、实施指引、checklist 四节。

## 规则 R6：前置运行时自举契约（缺 JDK / Erlang 由本工具装好）

### R6.1 规则描述

「用户点一次启动」必须足够。组件声明的启动前置（`LaunchSpec.needs` 里的 JDK、
`LaunchSpec.prereq` 里的 Erlang）**在宿主上缺失时，由本工具自动下载并安装**，
不许以"请先自己装一个 JDK / Erlang"结束流程。

三条硬约束：

1. **判据只有一处**：缺什么由 `prereq_components()` 回答，它复用 `launch_gate` 的
   同一套判据（`resolve_java_home` / `check_prereq`）—— 两处各写一遍必然漂移。
2. **版本要配套**：RabbitMQ 4.x 配 Erlang 27.x、3.13 配 26.x（绑死，不能共用一个）；
   由 `prereq_install_versions()` 给出前缀、`pick_prereq_version()` 在**可下载**的
   版本里挑（离线清单里可能带着别的平台的版本，挑中一个下不了的等于点一次错一次）。
3. **自动装完必须能被找到**：Erlang 装在 `~/.env-tools/erlang/erlang-<v>/bin/erl.exe` ——
   原来的查找 glob（`C:\erlang*` / Program Files）看不到它，于是"刚替用户装好的 Erlang"
   会被门控判成"没装"，自动安装白做。统一走 `installed_erlang_erl()`（先自家目录、再 glob）。

### R6.2 适用范围

- 所有 `LaunchSpec.needs` 含 `"jdk"` 的组件（jenkins / nacos / activemq / rocketmq / kafka / tomcat / seata）
- 所有 `LaunchSpec.prereq` 非 None 的组件（目前只有 rabbitmq → erlang）
- 新增组件时如果它需要任何外部运行时，**必须**在 `LAUNCH_OF` 里声明 `needs` / `prereq`，
  否则这条规则覆盖不到它。

### R6.3 硬约束

1. `min_java_major` **填数字必须来自实测**（拆包读 `META-INF/MANIFEST.MF` 的
   `Java-Version:` 或 class 的 major version），没实测就留 `None` —— 留 None 只是
   退化成"有没有 JDK"，填一个猜的数字会让"版本不够"被静默放过。
   实测值现状：jenkins 11（war 清单）、nacos 8、tomcat 11、seata 8、activemq/rocketmq/kafka 17。
2. 宿主上已有 JDK 但**版本低于门槛**时，也要判定为"缺"并装一个够用的；
   `resolve_java_home()` 的优先级（本工具生效版本 → 本工具已装最高 → 环境变量 `JAVA_HOME`）
   会保证新装的那个胜出。
3. 前置组件的下载/落位**复用同一套机制**（`DownloadWorker` + `install_downloaded`），
   不许为它写平行的下载/解压代码。
4. 隐藏组件（`Component.hidden=True`，目前只有 erlang）**不进任何界面 Tab**，
   但仍要登记分类（`COMPONENT_CATEGORY_OF` 漏登记会 `KeyError`）。

### R6.4 失败处理

自动安装失败（网络、磁盘、安装器返回非零）时必须**明确说出失败对象与原因**，
并把"再点一次启动"作为下一步；不许静默回退到"请自己装"。

### R6.5 真机验证入口

`tools/bt_live_matrix.py --keys autoprereq`：把 `JAVA_HOME` 与 PATH 里的 java 摘掉、
屏蔽自家 JDK 目录，让判据真的报"缺 jdk"，然后走一遍下载 → 落位 → 读回 major →
切换生效 → 确认 `launch_gate` 放行。六项全绿才算这条规则立住。

### R6.6 checklist

- [ ] 新组件的前置运行时在 `LAUNCH_OF` 里声明了（`needs` / `prereq`）
- [ ] 该前置在 `build_components()` 里有可下载版本（或已有宿主依赖兜底）
- [ ] `min_java_major` 只填实测值，并在注释里写清证据（哪个文件、哪个字段）
- [ ] 隐藏组件在 `group_components()` 后被排除（新增隐藏组件时验证界面数量没变）
- [ ] 真机跑过 `--keys autoprereq`，六项全绿

---

## 规则 R7：单文件组件的落位文件名契约

### R7.1 规则描述

单文件形态（`archive_for_current()` 为 `exe` / `war` / `""` / `bin`）的组件，
**落位时必须改成启动命令会去找的那个文件名**。文件名对不上时症状是
`[WinError 267] 目录名称无效` —— 用户看到"装好了"，点启动却起不来。

### R7.2 适用范围

- 所有 `exec_name` 非空且归档是单文件形态的组件（kubectl 的 `kubectl.exe` 等）
- **`exec_name` 为空的单文件组件**（jenkins 的 war）：这类必须靠"通用文件名"兜底 ——
  `jenkins-2.568.3.war` → `jenkins.war`（名字从下载文件名取，不写死组件 key）

### R7.3 硬约束

1. 改名只在**落位那一刻**做一次，且只在目标名不存在时改（幂等，不覆盖）。
2. 兜底名只给"确实有通用名"的形态（war）；`exe` / 无扩展名的单文件没有通用名，
   没有 `exec_name` 就**不许猜**（猜错就是把用户的二进制改成别的名字）。
3. 落位后必须有一步"启动命令要的文件在不在"的自检（`exec_path_in_home` 对
   `exec_name=None` 的组件返回 None，所以 jenkins 走 `_detect_by_home_dir` +
   `JENKINS_HOME` 判定；这条接缝必须真机验一次）。

### R7.4 真机验证入口

`tools/bt_live_matrix.py --keys jenkins --phase all`：装完断言
`<home>/jenkins.war` 存在、`detect()` 说已配置、然后 `--phase launch` 能起来。

---

## 规则 R8：动态内容目录要同步进 prefix / BASE

### R8.1 规则描述

当组件的**静态内容**（nginx 的 `html/`、tomcat 的 `webapps/`）留在安装目录、
而运行时根目录被本工具改到 `~/.env-tools/<key>-data` 时，
**启动前必须把这份内容补进去**，否则：
- nginx：`root html;` 相对 `-p` 前缀解析 → `nginx-data/html` 不存在 → 首页 404
- tomcat：`CATALINA_BASE` 指向 data → `apphost` 是空的 `tomcat-data/webapps` → 首页 404

用户看到的是"启动成功了，控制台打不开"，而这两件事在日志里都没有痕迹。

### R8.2 硬约束

1. 同步**只补缺、绝不覆盖**（用户改过的 `index.html`、自己部署的 WAR 不许被冲掉）。
2. 同步发生在端口准备阶段（`prepare_ports` → conf writer），与"副本已建"的提示同一批 `notes` 里
   告诉用户，别静默做事。
3. 任何"运行时根目录 ≠ 安装目录"的组件都要检查这条（新增组件 checklist 里加一项）。

### R8.3 真机验证入口

`tools/bt_live_matrix.py --keys nginx,tomcat --phase launch`：`console_http_ok` 必须 2xx/3xx。

---

## 规则 R9：非 ASCII 主机名下的服务节点名

### R9.1 规则描述

中文（或任何非 ASCII）主机名的机器上，Erlang 分布式节点名会被截断：
RabbitMQ **服务器起得来、5672/25672 都在听、日志一切正常**，但
`rabbitmqctl` 的每个子命令都失败（`:badarg` / `rc=70`）——看着成功，实际查不了也停不了。

### R9.2 硬约束

1. `rabbitmq` 的 `extra_env` 必须**固定** `RABBITMQ_NODENAME=rabbit@localhost`
   （start / stop / status 三处一致）。
2. 判活要用 `rabbitmqctl status` 这类**真的问服务**的命令（`service_probe`），
   不能只看端口在听 —— 本条缺陷恰恰是"端口在听但 CLI 全挂"。
3. 新增组件时若它的 CLI 会连本机节点/守护进程，同样要检查节点名与主机名的关系。

### R9.3 真机验证入口

`tools/bt_live_matrix.py --keys rabbitmq --phase launch`：`service_probe` 必须 rc=0，
且探针要用**产品注入的那份环境**（`build_launch_plan(...).env`），
否则会把"产品能跑"误判成"探针失败"。

---

## 规则 R10：启动后必须有可访问页面 + 启动日志必须给出地址

### R10.1 规则描述

**每个可一键启停的组件，启动成功后都必须有一个用户点开就能确认"确实起来了"的页面**，
并且这个地址必须写进组件日志（不能只在界面里显示）。

分三类满足，不允许出现"启动成功但没有任何页面可看"的组件：

| 类型 | 组件 | 页面是什么 |
|---|---|---|
| 自带 Web 界面 | jenkins / nacos / activemq / seata / tomcat / nginx | 它自己的控制台或首页（`console_path`），**不做任何转发**——用户看到的是真东西 |
| 状态即页面 | elasticsearch | 根路径本来就回人可读的 JSON 状态，直接指它 |
| 协议端口型（浏览器打开必然失败） | kafka / rocketmq / rabbitmq | 本工具自带的「启动成功」页（`ComponentPageServer`）：组件名、运行状态、端口、安装/数据目录、登录信息、日志路径、刷新时间 |

### R10.2 硬约束

1. **页面状态必须现算**：每次请求重新探端口，所以服务停掉后再刷新那张页会显示
   「已停止」——静态 HTML 文件做不到这一点，会变成一张永远说"成功"的假告示。
   **这条以前只是写在规则里，代码没做到**（2026-10-10 用户报"停止组件后浏览器还能访问，
   关掉软件才真停"才暴露）：`show_launch_page()` 把 `launch_page_html(...)` **渲染一次**
   就把成品塞进 `_pages`，而页面服务跑在本工具进程里、又没有 `unregister` ——
   于是那张"正在运行 · 端口 N"永久挂着，只有进程退出才消失。
   现在 `register(key, render)` 收的是**渲染回调**，每次请求现查
   `load_running_map()`：记录没了就 404 并明说「这个组件已经停止」，
   首页也只列当前真出得了内容的组件。判据见
   `bt_launch_tests.AccessPageStopsAnsweringAfterStop`（3 条，其中两条对着
   "渲染一次"的旧写法会红）。
2. **只监听 127.0.0.1，端口由 OS 分配**（`PAGE_SERVER_PORT = 0`）：不占用户端口、不对外网暴露。
3. **页服务起不来不许影响启动**：`get_page_server()` 失败返回 None，调用方退化成
   "只在日志里写访问方式"，绝不能因为一个展示页把服务启动搞失败。
4. **日志里必须同时给三样**：访问地址、**实际端口**（可能是 8888/8081，不是默认 80/8080）、
   启动日志文件路径 —— 见 `launch_success_lines()`。
5. **`console_path` 的取值纪律**：写 `None` 意味着"这张卡片没有可点的页面"。`nginx` 与
   `tomcat` 曾经被写成 `None`，后果是卡片上不给按钮、用户自己猜端口（猜 8080，
   而实际是 8888/8081）→ 现在填真实路径；tomcat 的 webapps 与 nginx 的 html 还必须
   同步进运行时目录（见 R8），否则点开就是 404。
6. **不许把协议端口当控制台**：`console_url` 指到 5672/9092/9876 只会让浏览器报连接失败 ——
   那正是 2026-10-06「RabbitMQ 显示启动成功实际无法访问」的成因。

### R10.3 真机验证入口

```
python tools/bt_live_matrix.py --keys nginx,tomcat,activemq,rocketmq,kafka,elasticsearch,seata,nacos,rabbitmq,jenkins --phase launch
```

10 个组件、**63 项检查必须全绿**（2026-10-08 实测：58 → 63 项，全绿）。每个组件都有：

- `access_page_opens` —— URL 真的能打开且返回 2xx/3xx（401+`WWW-Authenticate` 与 403
  也算"服务在正常响应"：ActiveMQ 的 `/admin` 与 Jenkins 初始化后的登录页就是这两种）；
- `access_page_says_running` —— 对自带页（没有 Web 界面的四个）额外断言正文里写着「正在运行」。

---

## 规则 R11：产品名是 ByteTools / 字节工具箱，但四处旧名 `byte-tools` 是承重墙，不许顺手改

2026-10-10 把**产物名与文档里的产品名**从 `byte-tools` 改成 `ByteTools`：
`byte-tools.spec` 的 `APP_NAME` → 产出 `ByteTools.exe` / `ByteTools.app` / `ByteTools`，
`release.yml` 的四个 `artifact_name`、`同步Gitee产物.sh/.bat` 的期望清单、
`bt_gitee_sync_tests.py` 的夹具、两个一键脚本的标题与 `assets/msg_zh.txt` 文案、
README / README_EN / CODE_WIKI 里的产物名同步改掉。**改名是跨文件的一次性对齐**：
任何一处漏改，下一次发版就会出现"CI 造出 `ByteTools.exe`，Gitee 同步脚本却去找
`byte-tools.exe`"这种半截状态（`RELEASE_ARTIFACTS` 与 `DEFAULT_ARTIFACTS` 必须逐字相同）。

同日第二轮：中文产品名统一成 **字节工具箱**（`main.APP_NAME`、README 标题、
一键脚本的中文横幅、macOS 的 `CFBundleName` / `CFBundleDisplayName`）。
改名前界面上同时存在三个名字（`字节-开发环境与工具自动安装` / `编程开发环境自动装配小工具` /
`byte-tools`），macOS「关于」面板的版本号还常年写着 `1.0.0`。

**版本号只有一个真源：`main.APP_VERSION`。** 界面唯一可见落点是标题栏软件名后面那枚
`#versionChip`（点它 = 手动检查更新，见 R12），另有标题 tooltip、macOS bundle 的
`CFBundleShortVersionString` / `CFBundleVersion`（spec 用正则从
`main.py` 读，不 import —— 那是个要拉 PySide6 的 GUI 模块）全部取自它；
`release.yml` 在**任何构建之前**有一步闸门比对 `APP_VERSION` 与被推送的 tag，
不一致就直接红。发版动作因此是两步：改常量 → 打同名 tag。
底部状态条以前也写一份 `版本：v1.1.2`，2026-10-10 用户要求去掉（同一屏两处重复）；
同一条要求还包括状态条的组件数只写 `组件：26`，不要"总数…个（另有 N 个仅作前置依赖…）"这种句子
—— **隐藏组件的去向归文档（R5.3）交代，不归状态条**。
用例 `StatusBarFacts.test_version_shows_up_in_ui_and_is_not_behind_the_latest_tag`
会在本地拿 `git describe --tags --abbrev=0` 对一遍（没有 git 时 skip，不硬失败）。
这条用例有两个坑，都踩过：

1. **断言写成"不落后"，不能写成"相等"**。上面那个两步流程的中间态（常量已改、tag 未打）
   用 `assertEqual` 会被自己判红，而它其实是正当提交。相等性由 `release.yml` 在打 tag 那一步兜。
2. **`--abbrev=0` 不能和 `-n1` 同时给**。两个选项都以 `-n` 开头，git 把 `-n1` 解析成
   `--abbrev=1`，于是同一依赖给了两次 → `fatal: Cannot deal with the same dependencies more than once`，
   而 **stdout 是空的**。用 `subprocess` 包 git 时只看 `stdout` 会把"命令失败"读成"没有 tag"，
   必须把 `stderr` 一起当证据。

以下四处**保留 `byte-tools` 原样**，各自都有具体后果，不是"没改完"：

| 保留项 | 位置 | 改了会怎样 |
|---|---|---|
| 仓库标识 | `jilong2026/byte-tools`、`GITEE_REPO=byte-tools`、README 里 `cd byte-tools` | 远端仓库没改名，改了 clone/下载链接全断 |
| 下载 UA | `HTTP_UA = {"User-Agent": "byte-tools"}` 与各处"实测 + byte-tools UA"注释 | 大陆高校镜像是**按这个 UA 实测放行**的（默认 UA 回 403，见 R1）；改 UA 等于把 24 个组件 × 3 平台的源全部重测一遍 |
| shell rc 标记 | `# >>> byte-tools:NAME >>>` / `# >>> byte-tools:PATH:<entry> >>>` | 老用户 `.zshrc` / `.bash_profile` 里已写入的块**再也匹配不上**，清理与幂等更新双双失效，留下永久残块 |
| 文件与内部名 | `byte-tools.spec`、`assets/byte-tools.png/.ico/byte-tools-pt.png`、日志 `byte-tools.out`、`com.rgh.byte-tools` | 都是既有路径/标识：换名要连着搬用户数据、重生成图标引用，macOS 上换 bundle id 还会丢已授予的权限 |

新增文档里提到"这个软件"时用 **ByteTools**；提到上面四类时按原样写。

## 规则 R12：检查更新只读、后台、自动路径失败完全静默，且绝不替换自己

2026-10-10 加的功能，范围是用户拍定的 **A + B**：查版本 + 提示 + 应用内把新包下到
**用户挑的目录**；**不做"一键升级替换自己"**（要做必须单独出 spec）。

### R12.1 端点是实测出来的，不是想当然

| 端点 | 2026-10-10 本机实测 | 用法 |
|---|---|---|
| `https://api.github.com/repos/jilong2026/byte-tools/releases/latest` | **200 / 1.2s / 8.6KB / 免鉴权** | 主源 |
| `https://gh-proxy.com/<上面这个 URL>` | **200，代理回来的也是真 JSON** | 兜底源 |
| `gitee.com/api/v5/repos/.../releases/latest` | **404 "Not Found Project"**（仓库不公开） | **不能当更新源** |
| `github.com:443` | 本机偶发**整天**连不上 | 只出现在下载 URL 里，所以下载一律加速器优先 |

`latest` 天然只给非 draft 的最新正式版，正好和"各平台先传草稿、Gitee 同步核对齐全后
才自动取消草稿"的发布流程对上 —— 半成品不会被提示成"有新版本"。

### R12.2 硬约束

1. **自动检查只挂在程序入口，不挂 `MainWindow.__init__`**。第一版就犯过：测试直接构造
   窗口，4 秒定时器一响就真发了一次 HTTP 请求，并把 `last_check_ts` 写进用户真实的
   `config.json`。这与 `_adopt_running` 不进 `__init__` 是同一条理由（见那里的注释）。
2. **必须在子线程里查**，`UpdateCheckWorker.run()` 连异常都要吞成结果 ——
   QThread 里抛异常在这个项目上崩过 `0xC0000409`（界面直接没了）。超时 8 秒硬闸。
   启动路径上任何同步网络请求都可能把界面锁死，这条是 R3.14（WMI 卡 135 秒）换来的。
3. **自动检查失败完全静默**：一个字的日志都不写。本机对 github.com 偶发连不上是常态，
   弹一句"检查失败"对普通用户等于凭空多一个故障。**手动点版本号 chip 时才必须回答**，
   否则像按钮坏了 —— 两条路径的差别就这一条。
4. **不携带任何用户信息**：URL 只有那两个端点，不拼查询参数、不记 IP。
   这是"检查更新"和"遥测"的分界，用例 `test_requests_carry_no_user_data` 钉着。
5. **产物按平台 + 后缀挑**，不许写死文件名：v1.1.1 及更早的产物叫 `byte-tools.*`，
   v1.1.2 起叫 `ByteTools.*`（R11），写死任何一个都会在另一个时代选不到包。
6. **`draft` / `prerelease` / 读不出版本号一律不算有新版本**；没有产物的 Release
   仍然算"有新版可告知"（能打开发布页），只是不给应用内下载 —— 两者混成一个
   "读不懂"，用户就再也收不到任何升级消息。
7. **频控**：`config.json` 的 `update_check` 存 `last_check_ts` 与 `notified`；
   自动检查 24 小时最多一次、**同一个新版本只提示一次**。写这个键必须走
   `_update_config()` 的读-改-写（整体覆盖会清掉 active / takeover / selections）。
8. **绝不改名或覆盖正在运行的自己**。下载只写到用户选的目录、下完核对字节数，
   然后提示"自己放到习惯的位置，替换前先退出本程序"。
9. 提示形态是标题栏那颗版本号 chip 变琥珀色（`#versionChip[hasUpdate="true"]`）。
   **换色用动态属性，不许改 `objectName`** —— 改完按名字找它的代码与用例就失效了（踩过）。
   chip 文字只写新版本号，标题栏宽度紧，最窄窗口下不许裁字
   （`bt_multiversion_tests.CleanTerminalWindow.test_title_bar_buttons_are_not_clipped_at_minimum_width`
   现在把 `btn_version` 一起数进去了）。

### R12.3 版本号真源

只有 `main.APP_VERSION` 一个（见 R11）：界面 chip、macOS bundle、CI 的 tag 闸门都读它。
比较用 `version_is_newer()`，**按数值分段**比（`1.10.0 > 1.9.0`）；
任何一边读不出来都返回 False —— 拿不到结论时不许打扰用户。

### R12.4 用例

`bt_update_check_tests.py`（18 条，全离线：`check_for_update(fetch=...)` 是可注入接缝，
测试不联网）：响应解析与拒绝形状、无产物 Release、数值版本比较、两时代产物挑选、
24 小时频控、同版本只提示一次、失败静默位、加速器兜底、隐私线、
chip 初始文字、自动失败不写日志 / 手动失败要回答。

---

## 接新组件的流程与经验

**要写需求时看 `docs/HOW-TO-REQUEST-COMPONENT-LAUNCH.md`** —— 那是需求说明书模板 +
关键名词对照表（`LaunchSpec` / `端口簇` / `结束占用者` / `pid_role` / `三重闸` 等），
照着它说能省掉一轮返工。

实现前**必读** `docs/ONBOARDING_NEW_COMPONENT.md`——
它记录了 Jenkins / Nacos / ActiveMQ 三次实战里「不这样就真的出过问题」的每一条，
附本机可复现的证据。核心一句话：

> **先把"我以为的"换成"我实测的"，再写代码。**
> 端口、控制台路径、厂商 task 名、停止方式这四样，没有一样能靠推理得出。

四个必须先回答的维度（不回答就动手，返工概率极高）：

| 维度 | 决定什么 |
|---|---|
| 端口能不能改（flag / 透传 / 改配置） | `port_writeback` 三选一；是否要动厂商文件 |
| 数据能不能外移 | `data_dir_env`；卸载时数据会不会跟着没 |
| 我们是不是服务进程 | `pid_role`；停止能否按登记 PID 杀 |
| 厂商停止手段 | `stop_kind`（pid / shutdown_command / port_lookup） |

最容易踩的一条：厂商启动脚本几乎都是**包装器**（`cmd.exe` / `bat`），
登记的 PID 是包装器，真正在监听端口的是它拉起的 java.exe →
`pid_role` 必须是 `launcher`，停止只能靠端口反查 + 三重闸。
