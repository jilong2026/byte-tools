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
- [规则 R2：组件三类分组与界面 Tab](#规则-r2组件三类分组与界面-tab)
- [规则 R3：组件多版本与生效版本切换](#规则-r3组件多版本与生效版本切换)

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
（`ghproxy.net` / `gh-proxy.com` / `ghfast.top` + 裸地址末位），统一走 `_gh_accelerated()`。
`ghproxy.com` 与 `gh.idayer.com` 实测已停服，不得再引入。
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

## 规则 R2：组件三类分组与界面 Tab

### R2.1 规则描述

26 个组件在界面上归入且仅归入三个 Tab，分类标准必须**机械可判**，不允许按感觉塞组件：

| 分类 | 判定标准 | 组件（10 / 13 / 3） |
|------|----------|--------------------|
| **开发环境** | 装完进 PATH，直接用来写 / 编译 / 打包代码 | jdk、python、node、go、bun、conda、git、maven、gradle、powershell |
| **开发软件** | 本地跑起来给项目当依赖的服务 | tomcat、nginx、mysql、mongodb、postgresql、elasticsearch、nacos、seata、kafka、rocketmq、pulsar、activemq、rabbitmq |
| **其它软件** | 不参与写代码的容器 / 编排 / CI 外围 | docker、kubectl、jenkins |

边界争议按此顺序裁决：**要不要设 `XXX_HOME` 进 PATH 才能开工** → 是则开发环境；否则看**是否作为常驻服务被项目依赖** → 是则开发软件；都不是则其它软件。
（例：Maven / Gradle 是命令行构建工具，进 PATH 才能开工，属开发环境而非"服务"；Tomcat 需要跑起来给项目用，属开发软件；PowerShell 是进 PATH 的 Shell / 脚本运行时，属开发环境；Nginx 与 Tomcat 同理，本地跑起来当 Web / 反向代理依赖，属开发软件。）

### R2.2 适用范围

- `Component.category` 字段与 `COMPONENT_CATEGORY_OF` 登记表
- `group_components()` 与 `MainWindow._build_ui()` 的 Tab 构建
- 新增 / 改名 / 删除组件时的分类登记

### R2.3 实施指引

分类**只有一个真源**：`COMPONENT_CATEGORY_OF`（`main.py`，`build_components()` 之前）。

```python
COMPONENT_CATEGORIES = ("开发环境", "开发软件", "其它软件")   # Tab 顺序即此顺序
COMPONENT_CATEGORY_OF = {
    ...
    "foo": "开发软件",          # 新增组件在这里加一行
}
```

`build_components()` 末尾统一执行 `comp.category = COMPONENT_CATEGORY_OF[comp.key]`——
**不要**在各 `Component(...)` 构造处手写 `category=`，也**不要**给 `.get(key, 默认值)` 兜底：
漏登记必须 KeyError 炸出来，静默归到某个分类会让新组件"消失"在错误的 Tab 里。

`MainWindow.cards` 必须保持**全量平铺**（26 项，跨 Tab 收集）：刷新版本、读写配置、关窗前等探测线程都遍历它，分组只改变卡片的父布局。

Tab 条固定在**顶部横向**（`setTabPosition(QTabWidget.North)`），标题格式为 `f"{分类名}（{数量}）"`，
数量由 `group_components()` 的结果现算——**不要写死数字**，否则增删组件后标题会与真实卡片数不符。

### R2.4 新增 / 调整组件分类 checklist

- [ ] `COMPONENT_CATEGORY_OF` 里登记了该 key，且值取自 `COMPONENT_CATEGORIES`
- [ ] 按 R2.1 的判定顺序核对归类理由，有争议的在 PR 说明里写清
- [ ] `bt_component_category_tests.py` 通过（其中 `EXPECTED_MEMBERSHIP` 是分类基线，改归类要同步改它）
- [ ] 未新增 `if category == ...` 之类的界面特判——分组渲染只走 `group_components()`
- [ ] README / README_EN 的三 Tab 表格与 `CODE_WIKI.md` 的 `category` 字段说明同步

### R2.5 组件搜索框

组件数上到 26 个后逐页翻不现实，Tab 上方有一条搜索框做名称模糊过滤。约束：

- **位置在标题栏之外**、Tab 之上（`#searchBar` 内的 `QLineEdit#compSearch`）。标题栏整条是窗口拖拽区
  （`mousePressEvent` 里判 `title_bar.underMouse()` 就开始拖动），输入框塞进标题栏会点不动、一按就拖窗
- 匹配内核是纯函数 `component_matches(comp, query)`：只比 `display_name` 与 `key`，忽略大小写与首尾空白，
  空查询（或全空白）返回 `True` 表示不过滤。**不要**把分类名纳入匹配——分类已由 Tab 表达，
  搜"开发"会命中全部卡片，等于没搜
- 过滤**只改 `card.setVisible()` 与卡片在布局里的归属**，绝不从 `MainWindow.cards` 里摘项（原因见 R2.3 的全量平铺不变量）
- **全组件搜索的呈现方式**：搜索时收起三个 Tab（`QStackedWidget#topStack` 切到统一结果页 `QScrollArea#resultsArea`），
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

### R3.9 非多版本组件零影响

任何多版本相关的分支都必须用 `component.multi_version` 门控（状态胶囊 `_render_status_label` /
`_detect_status`、卸载目标 `resolve_uninstall_target`、卸载摘要 `Component.uninstall` 第 4 步、
绿勾 `_refresh_installed_marks`、确认框尾巴 `on_uninstall_clicked`）。非多版本组件的状态文案、按钮逻辑与
卸载结果必须与改造前**逐字一致**。护栏用例：`test_non_multi_version_capsule_text_unchanged`、
`test_non_multi_version_with_two_dirs_still_refuses`、`test_non_multiversion_confirm_text_byte_identical`。
典型陷阱：`resolve_uninstall_target`（`main.py:293-338`）里"选了没装的版本、磁盘上又装着多个"这种情形，
多版本组件改为按语义降序卸最高的并说明（罢工等于卸载失灵），非多版本组件必须继续罢工、不得跟着放宽。

**一条明确豁免**：「下载并安装」的"选中版本已装则置灰"是**面向全部 26 个组件**的新规则
（`ComponentCard._installed_here()` + `_sync_action_buttons()`），**不受本条约束**，
也不许为了本条去把它门控回"只多版本组件"。判据是"目录存在且里面找得到该组件的可执行文件"，
半截安装不算已装（否则按钮灰掉、卸载又无事可做，用户会被困死）。
护栏用例：`InstallButtonBlockedWhenInstalled`。

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

### R3.11 选中版本已装则置灰「下载并安装」

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

### R3.14 启动脚本不得为 WMI 阻塞用户

`一键启动项目.bat` 里那段 WMI 自检已从"15 秒 + 再等 120 秒"改成**只探 2 秒、超时也只提示不等待**。
理由：`main.py` 已改用 `sys.platform` / `PROCESSOR_ARCHITEW6432` 判断系统与架构（R3 之前的启动卡死修复），
启动路径上没有任何一步会问 WMI；等 WMI 只对 `一键打包exe.bat` 有意义（PyInstaller 导入期必调
`platform.win32_ver()`），那边的有界自检保留。实测本机 WMI 冷启动时：改前白等最多 135 秒，改后 2.3 秒继续。

---

## 后续规则占位

> 后续新增的开发规则以「规则 R4 / R5 / ...」形式追加到本文件，并在「规则索引」中登记。
> 每条规则必须包含：规则描述、适用范围、实施指引、checklist 四节。

- R4: _待定_
