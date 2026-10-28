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
- [规则 R2：组件分类分组与界面 Tab](#规则-r2组件分类分组与界面-tab)
- [规则 R13：「开发工具」是只下载的一类，八个短路点少一个就污染用户机器](#规则-r13开发工具是只下载的一类八个短路点少一个就污染用户机器)
- [规则 R3：组件多版本与生效版本切换](#规则-r3组件多版本与生效版本切换)
- [规则 R4：一键脚本自举契约](#规则-r4一键脚本自举契约)
- [规则 R5：组件一键启动契约](#规则-r5组件一键启动契约)
- [规则 R6：前置运行时自举契约（缺 JDK / Erlang 由本工具装好）](#规则-r6前置运行时自举契约缺-jdk--erlang-由本工具装好)
- [规则 R7：单文件组件的落位文件名契约](#规则-r7单文件组件的落位文件名契约)
- [规则 R8：动态内容目录要同步进 prefix / BASE](#规则-r8动态内容目录要同步进-prefix--base)
- [规则 R9：非 ASCII 主机名下的服务节点名](#规则-r9非-ascii-主机名下的服务节点名)
- [规则 R10：启动后必须有可访问页面 + 启动日志必须给出地址](#规则-r10启动后必须有可访问页面--启动日志必须给出地址)
- [规则 R11：产品名是 ByteTools / 字节工具箱，四处旧名 byte-tools 是承重墙](#规则-r11产品名是-bytetools--字节工具箱但四处旧名-byte-tools-是承重墙不许顺手改)
- [规则 R12：检查更新只读、后台、失败完全静默，且绝不替换自己](#规则-r12检查更新只读后台自动路径失败完全静默且绝不替换自己)
- [规则 R14：四条通用不变量](#规则-r14四条通用不变量2026-10-10-全面审计--2026-10-11-关窗崩溃查出来的)
- [规则 R15：GitHub 匿名额度是硬预算，抓到的清单必须落盘](#规则-r15github-匿名额度是硬预算抓到的清单必须落盘2026-10-12)
- [规则 R16：像素裁字只能在真实渲染下判](#规则-r16像素裁字只能在真实渲染下判offscreen-的度量会把你带偏)
- [规则 R17：组件详情弹窗](#规则-r17组件详情弹窗2026-10-12)
- [规则 R18：冷启动预算——建卡不许逐个扫 PATH](#规则-r18冷启动预算建卡不许逐个扫-path2026-10-13)
- [规则 R19：官网地址必须人工登记，不许从下载 URL 推导](#规则-r19官网地址必须人工登记不许从下载-url-推导2026-10-14)
- [规则 R20：「Agent客户端」是第五个只下载的 Tab](#规则-r20agent客户端是第五个只下载的-tab2026-10-15)
- [规则 R21：「官网下载」是只下载里更弱的一档，为的是"先把组件都收进来"](#规则-r21官网下载是只下载里更弱的一档为的是先把组件都收进来2026-10-15)
- [规则 R22：每个 Tab 内的卡片按显示名 a→z 排](#规则-r22每个-tab-内的卡片按显示名-az-排2026-10-15)
- [规则 R23：网格多余的**行高**必须落到布局末尾的 stretch 上](#规则-r23网格多余的行高必须落到布局末尾的-stretch-上2026-10-15)
- [规则 R24：Windows 上中文**不许走命令行 argv**](#规则-r24windows-上中文不许走命令行-argv2026-10-15)
- [规则 R25：可装配组件必须是官方**完整发行版**，不许用 embeddable / Mini 精简包](#规则-r25可装配组件必须是官方完整发行版不许用-embeddable--mini-精简包2026-10-28)

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

- **全部可装配组件**（语言运行时：jdk / python / node / go / bun / kotlin / graalvm / rust / dart；Shell：powershell；构建工具：maven / gradle / protoc / ant / cmake / ninja；应用服务器与 Web 服务：tomcat / nginx / caddy / traefik；数据库：mysql / mongodb / postgresql / sqlite / duckdb；键值缓存：redis；容器与编排：docker / kubectl / docker-compose / helm / k9s / trivy / jmeter；CI/CD：jenkins；消息队列：rabbitmq / kafka / rocketmq / pulsar / activemq / nats-server；服务发现与事务：nacos / seata / etcd / consul / zookeeper；搜索引擎：elasticsearch；版本控制：git；Python 发行版：conda；Python 工具链：uv；命令行小工具：jq / yq / ripgrep / fd / fzf / bat / eza / zoxide；单二进制运行时：deno / bun / dotnet-sdk / pnpm；对象存储：minio）
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

下表 57 个**可装配**组件的镜像路径**全部逐条实测**（2026-09-28 主体，2026-10-12 分四批补齐，GET + `User-Agent: byte-tools`）。
2026-10-10 起另有 26 个「开发工具」是**只下载**的，它们的实测矩阵记在 R13.3（那批绝大多数没有可用大陆镜像，属 R1 例外）。
"默认清单实测"一栏给的是默认版本行里**可用大陆源的数量 / 配置的候选数量**。

#### 首批 8 个组件（2026-09 由单源补齐为多源）

| key | 组件 | 国内镜像（按优先级，实测可用性） | 末位官网 | 默认清单实测 |
|-----|------|--------------------------------|---------|--------------|
| `jdk` | JDK (Temurin) | 清华 `…/Adoptium/<major>/jdk/<arch>/<os>/`、南大 `…/adoptium/…`（两家目录大小写不同）。镜像里只有带 build 号的确切文件名，须先列目录挑最新版本，故有 `_adoptium_mirror_urls()`；镜像未同步的 major（如 22/23/24/26/27）自动只剩官网 | `api.adoptium.net/v3/binary/latest/<major>/ga/…` | 离线默认 0/0（见 R1.1 例外）；「刷新版本」后为 2 家镜像 + 官网。21/17/11 三档 × 三平台官网直连实测 200（190~207 MB） |
| `maven` | Apache Maven | M1 `repo.huaweicloud.com/apache/maven/maven-3/`、M2 清华、M3 阿里、M4 南大、M6 北外、M7 腾讯、M5 中科大（高校站只留最新版本，旧版 404 由故障转移兜住） | `archive.apache.org/dist/maven/maven-3/` | 3.9.16：7/7 家 200（9 MB）；3.9.6 只剩华为云 + archive |
| `tomcat` | Apache Tomcat | 同上七家 `apache/tomcat/tomcat-<major>/v<v>/bin/` | `archive.apache.org/dist/tomcat/` | 10.1.60：7/7 家 200（14~15 MB） |
| `mysql` | MySQL Server | Windows/Linux：M3 `mirrors.aliyun.com/mysql/MySQL-<maj.min>/`、M1 `repo.huaweicloud.com/mysql/Downloads/MySQL-<maj.min>/`。macOS 也有这两家镜像，但文件名用**当年命名**：8.0.28→`macos11-<arch>.tar.gz`（阿里+华为都 200/177 MB）、8.0.29→`macos12-<arch>`（华为 200/176 MB） | `cdn.mysql.com/Downloads/`（**不是** `dev.mysql.com` 的 get 跳转入口，后者对任何 UA 都回 403）；macOS 用 `macos14-<arch>` | Windows 2/2、Linux 2/2、macOS 2/4（8.0.37 这一档镜像站还没同步，只有 CDN 200/173 MB） |
| `python` | Python | **Windows 完整版**：M1 `repo.huaweicloud.com/artifactory/api/nuget/v3/nuget-remote/python/<v>/python.<v>.nupkg`、M1b `mirrors.huaweicloud.com` 同路径；macOS/Linux 仍 M1b `/python/`、N1 `registry.npmmirror.com/-/binary/python/` | Windows `api.nuget.org`；Unix `www.python.org/ftp/python/` | 2026-10-28 实测：华为双域 200 + `PK`（NuGet 完整包 14.6 MB）；Unix 2/2 家 200（源码 27 MB）。**Windows 不再用 embeddable**，见 R25 |
| `node` | Node.js | M2/M4/M6 `…/nodejs-release/v<v>/`、M1 `repo.huaweicloud.com/nodejs/v<v>/`、N1 `registry.npmmirror.com/-/binary/node/v<v>/` | `nodejs.org/dist/` | 5/5 家 200（29~47 MB） |
| `git` | Git for Windows | **Windows 有真镜像**：M1b `mirrors.huaweicloud.com/git-for-windows/<v>.windows.1/PortableGit-<v>-64-bit.7z.exe`、M1 `repo.huaweicloud.com/…`、N1 `registry.npmmirror.com/-/binary/git-for-windows/…`（三家实测 200 / 63 MB），再补 `GH_ACCELERATORS` | `github.com/git-for-windows/git/releases/download/` | 2026-10-28 起用 **PortableGit 完整版**（含 Git Bash / Perl / OpenSSH），不再用 MinGit；Linux/macOS **不再给 URL**，`_git_urls()` 只返回 `Windows` 键，由 `unsupported_platform_hint` 引导 apt/dnf/yum/brew（R1.1 例外） |
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

#### 2026-10-12 新增四个组件（Kotlin / GraalVM / Rust / Redis）

| key | 组件 | 国内镜像（按优先级） | 末位官网 | 默认清单实测 |
|------|------|-----------------------|---------|--------------|
| `kotlin` | Kotlin 编译器 | 无真镜像，走 `GH_ACCELERATORS`：`ghfast.top` → `gh-proxy.com` → `ghproxy.net` | `github.com/JetBrains/kotlin/releases/download/v<v>/kotlin-compiler-<v>.zip` | 三平台同一个 zip（89 MB，编译器是 JVM 产物）。Range 取样实测 206 + `PK`：**gh-proxy.com 18.4 Mbps、ghfast.top 7.2、gh-proxy.org 6.5**；裸 `github.com` 本机 SSLError。包顶层只有 `kotlinc/`（133 条），`bin/kotlinc.bat` 在里面 ⇒ `path_subdir="bin"` |
| `graalvm` | GraalVM CE | 同上三个加速器 | `github.com/graalvm/graalvm-ce-builds/releases/download/graal-<tag>/graalvm-community-jdk-<stem>_<os>-<arch>_bin.<ext>` | 206 + `zip`：gh-proxy.com 14.7、ghfast.top 7.3、gh-proxy.org 7.3 Mbps；裸地址 SSLError。**版本号在资产名里**（tag 是 `graal-25.4.4.1.1`，版本是 `25.0.4.1.1`），fetcher 用 `-(\d+(?:\.\d+)+)_(?:windows\|macos\|linux)-` 从资产名读，**不许从 tag 切**。`env_var` 必须是 `GRAALVM_HOME`——写 `JAVA_HOME` 会和 `jdk`(Temurin) 抢同一个变量，两个组件互相覆盖对方的生效版本 |
| `rust` | Rust | `rsproxy.cn/dist/<日期>/rust-<v>-x86_64-pc-windows-msvc.msi`（Rust 中文社区维护） | `static.rust-lang.org/dist/<日期>/…msi` | **1/1 家：16.9 MB/s（官方 15.5），206 + `\xd0\xcf`**（OLE）。**只有 1 个大陆源**，已登记 `SINGLE_SOURCE_EXCEPTION["rust"]=1`。踩过的坑：清华 `rustup/dist/<日期>/…msi` 404（它只镜像 tar.xz）、中科大整个 `rustup` 目录 404、腾讯云 `ChunkedEncodingError`。**日期目录不能省**（`/dist/<YYYY-MM-DD>/`）<br>**归档类型是 `msi`，走 `extract_archive` 里的 `msiexec /a` 管理性提取，不是 `msiexec /i` 真装机** —— 三条理由都是实测出来的：① 官方 `.exe`(NSIS) 已停发（带日期目录与不带的一律 404）；② 合并 `tar.xz` 内部是 `rustc/` + `cargo/` + `clippy-preview/` 等**组件目录，没有统一 `bin/`**，直接解压出来的 `rustc` 找不到标准库；③ `/a` 免提权、不写注册表，产出统一 prefix（`Rust/{bin,lib,share}`），且提取出来的 `rustc 1.99.0` / `cargo 1.99.0` / `rustfmt 1.10.0-stable` 真能跑 —— 而 `/i` 会留一个我们删不掉的注册表项、且大概率弹 UAC。清单里 **没有 `msi_url`**，只能把官方 `xz_url` 的后缀换成 `.msi`（1.99.0 / 1.98.0 / 1.97.1 三版换完都是 206 + OLE）<br>⚠ **装完仍需要一个链接器**：本机没装 VS Build Tools 时 `rustc` 能编译、**链接不过**，而且 Git for Windows 自带的 coreutils `link.exe` 会冒充 MSVC 链接器，报出莫名其妙的 `link: extra operand`。gnu 变体也不解决：实测合并包里**不含** `mingw-version/`（rust-mingw 是独立组件） |
| `redis` | Redis | 无真镜像，走 `GH_ACCELERATORS` | `github.com/redis-windows/redis-windows/releases/download/<v>/Redis-<v>-Windows-x64-msys2.zip` | 206 + `zip`：gh-proxy.com 17.9、ghfast.top 8.0、gh-proxy.org 7.2 Mbps；裸地址 SSLError。**⚠ 非官方构建**（社区 `redis-windows`）——官方只发源码，`download.redis.io` 的 tar.gz 装不出 Windows 可执行文件，卡片 `data_note` 已写明。不选 `with-Service` 变体：那个 `RedisService.exe` 会把自己注册成 Windows 服务，进程就不归本工具管了 |

#### 2026-10-12 B1：protoc / uv —— 「zip 形态的单二进制 / 无 XXX_HOME」的两个变体

| key | 组件 | 国内镜像（按优先级） | 末位官网 | 默认清单实测 |
|------|------|-----------------------|---------|--------------|
| `protoc` | protoc（Protobuf 编译器） | `registry.npmmirror.com/-/binary/protobuf/v<v>/protoc-<v>-win64.zip`（**目录名必须带 v 前缀**：不带 v 实测 404），再 `GH_ACCELERATORS` | `github.com/protocolbuffers/protobuf/releases/download/v<v>/protoc-<v>-win64.zip` | npmmirror 206 + `PK`：**3.5 / 2.7 Mbps**（两轮一致）；gh-proxy.com 3.3 / 3.5。裸 `github.com` 本机 ConnectionError。中科大与清华的 `github-release` 代理对 protobuf **恒 404**；华为云回 200 但只有 12 KB HTML（软 404）。整包 3,565,086 B / 27 条，顶层是 `bin/` + `include/` 两个并列目录 + `readme.txt` ⇒ **顶层目录 ≥2，`extract_archive` 返回 install_dir，`path_subdir="bin"`**；`protoc --version` → `libprotoc 36.2` |
| `uv` | uv（Python 包/环境管理） | `mirrors.ustc.edu.cn/github-release/astral-sh/uv/<tag>/uv-x86_64-pc-windows-msvc.zip`，再 `GH_ACCELERATORS` | `github.com/astral-sh/uv/releases/download/<tag>/uv-x86_64-pc-windows-msvc.zip` | 中科大 206 + `PK`：**2.0 / 1.9 Mbps**（两轮；慢于 gh-proxy.com 的 3.7 / 3.6，但"真镜像优先于加速器"是既有惯例，bun 那行同）。⚠ **中科大只同步最新版**：0.12.24 实测 404，旧版本靠故障转移兜到加速器。npmmirror 没有 uv 目录（`{"error":…}`）。整包 15,722,003 B / 3 条，顶层**一个目录都没有**（直接 `uv.exe` / `uvw.exe` / `uvx.exe`）⇒ **`path_subdir=""`**；`uv --version` → `uv 0.13.0 (…msvc)` |

#### 2026-10-12 B3/B5：GitHub Releases 单二进制批（15 个，表驱动 `GH_BIN_COMPONENTS`）

统一形态：**Windows 一个 zip（yq 是裸 exe）+ 官方只在 GitHub 发版 + 无 XXX_HOME**。全部只登记 Windows；裸 `github.com` 本机 ConnectionError，按 R1 放末位兜底，前面三个加速器都在 `MAINLAND_MARKERS` 里。

| key | 资产名（严格匹配） | tag 前缀 | 整包实测 | 顶层布局 ⇒ `path_subdir` |
|-----|--------------------|---------|---------|--------------------------|
| `deno` | `deno-x86_64-pc-windows-msvc.zip` | `v` | 42,630,221 B / 1 条 | 顶层 0 目录（`deno.exe`）⇒ `""` |
| `ninja` | `ninja-win.zip` | `v` | 291,570 B / 1 条 | 0 目录 ⇒ `""` |
| `duckdb` | `duckdb_cli-windows-amd64.zip` | `v` | 12,910,895 B / 1 条 | 0 目录 ⇒ `""` |
| `cmake` | `cmake-<v>-windows-x86_64.zip` | `v` | 54,400,562 B / 8979 条 | **1 个目录**（`cmake-<v>-windows-x86_64/`），⚠ `cmake.exe` 在那层的 **`bin/`** 里 ⇒ `"bin"`。这一格先前抄成了 `""`（"顶层 1 目录的 exe 都在根"是想当然），2026-10-12 由 `bt_archive_layout_audit` 判 BAD 后改回；同批的 ripgrep/fd/bat 才是"exe 在根" |
| `ripgrep` | `ripgrep-<v>-x86_64-pc-windows-msvc.zip` | **无 v** | 1,789,611 B / 16 条 | 1 个目录，`rg.exe` 在根 ⇒ `""` |
| `fd` | `fd-v<v>-x86_64-pc-windows-msvc.zip` | `v` | 1,535,063 B / 14 条 | 1 个目录 ⇒ `""` |
| `bat` | `bat-v<v>-x86_64-pc-windows-msvc.zip` | `v` | 3,613,318 B / 11 条 | 1 个目录 ⇒ `""` |
| `eza` | `eza.exe_x86_64-pc-windows-gnu.zip` | `v` | 1,491,797 B / 1 条 | 0 目录 ⇒ `""` |
| `zoxide` | `zoxide-<v>-x86_64-pc-windows-msvc.zip` | `v` | 545,663 B / 21 条 | **3 个顶层项**（`CHANGELOG.md` / `LICENSE` / `README.md` / `completions` / `man` + 根上 `zoxide.exe`）⇒ `""` |
| `fzf` | `fzf-<v>-windows_amd64.zip` | `v` | 2,544,236 B / 1 条 | 0 目录 ⇒ `""` |
| `yq` | `yq_windows_amd64.exe`（**裸 exe**） | `v` | 5,829,372 B | 单文件 ⇒ 走"拷贝 + 改名"分支，`exec_name` 才能是干净的 `yq` |
| `etcd` | `etcd-v<v>-windows-amd64.zip` | `v` | 24,508,798 B / 48 条 | 1 个目录，`etcd.exe` 在根 ⇒ `""` |
| `nats-server` | `nats-server-v<v>-windows-amd64.zip` | `v` | 7,484,670 B / 3 条 | 1 个目录 ⇒ `""` |
| `caddy` | `caddy_<v>_windows_amd64.zip` | `v` | 18,479,498 B / 3 条 | **0 个目录**但有 `LICENSE` / `README.md` ⇒ `""` |
| `traefik` | `traefik_v<v>_windows_amd64.zip` | `v` | 51,581,650 B / 3 条 | 同 caddy ⇒ `""` |

> **tag 前缀必须逐个钉**：ripgrep 的 tag 是 `15.2.0`（不带 v），其余 14 个都带。拼错就是 404，而用户看到的是"下载失败"而不是"清单写错了"——护栏 `test_tag_template_matches_the_measured_upstream_convention` 就是为这条加的（变异自检逼出来的）。
>
> **两个同批组件刻意不进这张表**：① `pnpm` 的 zip 顶层是 `dist/` 目录 + `pnpm.exe` 两个并列项，`extract_archive` 底部"顶层恰好一个目录就返回它"会把 `pnpm.exe` 丢掉（只剩 dist/）—— 2026-10-12 真机装机演练果然在这上面翻过车（同根因还带走了 trivy），规则已按 R3.22 第 5 条改成"根上有散文件就不算单顶层"；现在 pnpm 由 `_CLI_TOOLS` 单独登记（npmmirror **没有** pnpm 目录，实测 404，所以走三个加速器）；② `helm` 的 GitHub release 里只有 `.asc` / `.sha256sum` 签名，真正的二进制在 `get.helm.sh`，要用另一套源（同样由 `_CLI_TOOLS` 登记）。

> **为什么这两个值得单独记账**：现有走 `path_subdir=""` 的组件（kubectl / jenkins）都是**单文件拷贝早退分支**，压根没走到 `extract_archive` 底部那个"单顶层即根"判定；protoc / uv 是 zip，会走到底，而它们恰好是这条路径的两个相反变体 —— **≥2 个顶层目录**（protoc，`path_subdir="bin"`）与 **0 个顶层目录**（uv，`path_subdir=""`）。以后照抄这两个之前，先确认你的包属于哪一种。
>
> **一处真空护栏的教训**（变异自检抓出来的）：最初只为 protoc / uv 写了"内置清单的 URL 长什么样"，把 fetcher 的资产名匹配从 `protoc-<v>-win64.zip` 改成 `protobuf-<v>.zip` 之后测试**依然是绿的** —— 内置清单是手写的，fetcher 压根没跑到。真正能咬住的是打桩 `_github_release_assets` 直接测筛选行为：**只发源码包的 tag 不许被收进版本清单**。护栏绿了要问它"真走了那条路"，这句不是口号。

> **同批探过、没进代码的三个**（2026-10-12 实测，判据同上：状态码 + 魔数 + 字节数 + 吞吐）：
>
> - **`minio` 已实测可用（2026-10-12 修正早先结论）**：早先这里写过"`dl.min.io` 全线 410、最新 release assets 数为 0，所以"拿不到直链"。**实测修正**：官方收掉的是分发口，最后一个有产物的 release（`RELEASE.2025-09-07T16-13-09Z`，48 个资产）里 Windows exe 仍在，`github.com/minio/minio/releases/download/…/minio.windows-amd64.RELEASE.2025-09-07T16-13-09Z.exe` 实测 206 + `MZ`、113,115,136 字节，完整下载一次与 API 声明逐字节一致。**`dl.min.io` 全线 410 是事实，但"产品没有可用产物"是误判** —— 登记的是 release 资产上的直链，不是 `dl.min.io`。启停实测：两口齐听 1.6–2.9s、terminate 0.07s 退出、端口立即释放、无残留监听。⚠ 开源版已归档、不会再有更新；许可 GNU AGPLv3。
> - **`vmware-workstation` 确实拿不到直链**：`softwareupdate.vmware.com/cds/vmw-desktop/ws/`
>   回 404 `Object Not Found`（**绕开系统代理用 `Session(trust_env=False)` 复测过**，
>   第一轮那个 ProxyError 是本机代理拒的，不是它死了）、老构建路径 404、
>   `vmware.com/go/get-workstation` 404、brew cask `vmware-workstation` 也已下架。
>   ⇒ 现在只能从 Broadcom 支持门户登录后下，不符合"给官方直链"的模型。
> - **`parallels` 拿得到直链，本批没进是**产品定位**决定，不是源的问题**：
>   Homebrew cask 给的 `download.parallels.com/desktop/v27/27.0.3-58680/ParallelsDesktop-27.0.3-58680.dmg`
>   实测 **206 + 2.4 Mbps**（同格式的老版本 v26 那条我按规律拼的 → 404，
>   再次印证"版本号必须取接口，不能拼名"）。
>   没登记的理由是：macOS 专属 `.dmg`、商业授权、且版本清单只能依赖第三方 cask 接口。
>   ⚠ 早先这里写过"Parallels 拿不到直链"是**误判**（只试了猜测的 URL 形态就收工），
>   订正于当天第二轮实测 —— 记在这里防的就是后人把这句当事实、从此不再试。
>
> **一处已知偏差**：上面 Kotlin/GraalVM/Redis 三个的实测吞吐都是 `gh-proxy.com` 最快（18.4 / 14.7 / 17.9 Mbps），但 URL 顺序仍是 `_gh_accelerated` 的固定次序 `ghfast.top → gh-proxy.com → ghproxy.net`。改 `GH_ACCELERATORS` 的全局顺序会影响**所有**走加速器的组件，所以本批不改，只在此记账——真要按实测排序，得先对全部既用组件复测一遍再动。

#### 2026-10-12 B2/B4 服务批：ZooKeeper / Consul（etcd 在上表）

| key | 组件 | 国内镜像（按优先级） | 末位官网 | 默认清单实测 |
|------|------|-----------------------|---------|--------------|
| `zookeeper` | Apache ZooKeeper | 七家 Apache 分发 `…/apache/zookeeper/zookeeper-<v>/apache-zookeeper-<v>-bin.tar.gz`：`mirrors.huaweicloud.com` → 南大 → 清华 → 中科大 → 北外 → 腾讯云 → 阿里 | `dlcdn.apache.org/…` | 首源实装 200 + `gzip` 魔数，整包 **22,901,907 B / 26.2 Mbps**。目录段与文件名都带版本号，且文件名多一个 `-bin` 中缀（少写一处就 404）。⚠ 官方包**只有 `zoo_sample.cfg`，没有 `zoo.cfg`**，所以 `port_writeback="conf_copy"` 那条路是"整份 conf 拷进 `<key>-data/conf`，副本里没有 zoo.cfg 就按 sample 原文生成一份再改 `clientPort` / `dataDir`"，官方目录一个字都不动 |
| `consul` | HashiCorp Consul | **无**（`releases.hashicorp.com` 不是 GitHub，没有加速器可用；清华 `hashicorp/consul/` 404，华为 `repo.huaweicloud.com/hashicorp/consul/` 回 200 但只有 12,299 B HTML 门户壳 = 假源） | `releases.hashicorp.com/consul/<v>/consul_<v>_windows_amd64.zip` | 0/1 大陆源，已进 `OFFICIAL_ONLY_EXCEPTION`；206 + `PK`，整包 72,737,934 B，直连 **2.9 Mbps**（慢，但产品路径没有第二个源可换）。`-dev` 模式起，端口用 `-http-port` 直给，控制台 `/ui`、探活 `/v1/health` 两条路径**刻意不同**（R10） |

> **ZooKeeper 是第一个"绕开厂商包装器直接 spawn java"的 `needs=("jdk",)` 组件**，三条都是
> 真进程实测出来的（不是从文档推的）：① 官方包里只有 `zoo_sample.cfg`；② `zkServer.cmd`
> 不认 `ZOOCFGDIR`，还会把 `<home>\conf\zoo.cfg` 塞成第一个参数（我们再传一个就变成第二个
> 参数 → `NumberFormatException`），而且 `terminate()` 只杀掉 cmd 包装器、**留下监听端口的
> 孤儿 java**；③ sample 里 `dataDir=/tmp/zookeeper` 在 Windows 解析到盘符根，卸载删不掉、
> 多版本还会抢同一个目录。改成直接 `java -cp {home}/lib/* … {conf}` 之后实测
> `Popen.pid` 就是监听者（两边 PID 一致）、停止后端口立即释放。**门禁照旧：没有真机演练
> 输出不许扩 `LAUNCH_KEYS`** —— 本批三个的演练记录在下面"联调"一节。

#### 2026-10-12 B3/B5 我方那半批：8 个 CLI / 运行时（`_CLI_TOOLS` 表驱动）

| key | 组件 | 国内镜像（按优先级） | 末位官网 | 默认清单实测 |
|------|------|-----------------------|---------|--------------|
| `jq` | jq | 三个 GitHub 加速器 | `github.com/jqlang/jq/…/jq-windows-amd64.exe` | 206 + `MZ`，整包 1,035,264 B / 9.5 Mbps。**裸 exe**（走单文件拷贝分支），zip 变体不要：那个包里的 `jq.exe` 在 `jq-<v>/` 一层下 |
| `trivy` | Trivy | 三个加速器 | `github.com/aquasecurity/trivy/…/trivy_<v>_windows-64bit.zip` | 206 + `PK`，整包 52,927,180 B / 17.8 Mbps。⚠ 选 **64bit**（`windows-amd64` 是 Go 写法，trivy 用 `windows-64bit`），拼成 amd64 直接 404 |
| `k9s` | k9s | 三个加速器 | `github.com/derailed/k9s/…/k9s_Windows_amd64.zip` | 206 + `PK`，42,330,705 B / 13.9 Mbps；Windows 资产名 `k9s_Windows_amd64.zip`（大写 W，且**没有** v 前缀） |
| `docker-compose` | Docker Compose v2 | D1 `files.m.daocloud.io/github.com/docker/compose/releases/download/<tag>/…`（**GitHub 产物也能走 DaoCloud 的代理树**：实测 200 + `MZ` + `Content-Length 33,352,192` 与官方逐位一致，老版本 v2.29.7 同样在树里，3.5–7.0 Mbps），再三个加速器 | `github.com/docker/compose/…/docker-compose-windows-x86_64.exe` | 206 + `MZ`，33,352,192 B / 16.7 Mbps（加速器档）；⚠ 同一个手法在 npmmirror 上 404，所以这个开关是**逐组件实测**才登记的（`_CLI_TOOLS` 里的 `"dao": True`），没有实测证据的组件由护栏 `DaoCloudGithubProxyIsFirstForMeasuredComponents` 挡住不许沾 |
| `pnpm` | pnpm | 三个加速器 | `github.com/pnpm/pnpm/…/pnpm-win32-x64.zip` | 206 + `PK`，22,582,408 B / 17.6 Mbps。资产名是 `pnpm-win32-x64.zip`（win32 指的是 64 位 Windows 的 Node 惯例命名，别按字面改成 x64 以外的大小写） |
| `helm` | Helm | **无**（GitHub release 里只有 `.asc` / `.sha256sum` 签名，二进制不在那；清华 `helm/` 404、阿里 404） | `get.helm.sh/helm-v<v>-windows-amd64.zip` | 0/1，进 `OFFICIAL_ONLY_EXCEPTION`。版本入口用 `get.helm.sh/helm-latest-version`（纯文本），整包 404→改 `get.helm.sh` 后 206 + `PK` |
| `sqlite` | SQLite | **无**（清华 `sqlite/` 404；华为 `mirrors.huaweicloud.com/sqlite/` 回 200 但只有 12,299 B HTML 门户壳 —— 正是本文件反复防的那种假源） | `sqlite.org/<年>/sqlite-tools-win-x64-<六位版本>.zip` | 0/1，进 `OFFICIAL_ONLY_EXCEPTION`。⚠ 版本号是**六位无点**形式（3.54.0 → `3540000`）且路径带年份目录。sqlite.org **支持 Range 但对 `bytes=0-0` 回 200**（对 `bytes=0-15` 才回 206），审计脚本原来只按 0-0 探，于是把它误判成"不支持随机读"——改成探 16 字节后 sqlite 从 SKIP 变成真读清单：`sqlite3.exe` 在归档根 ⇒ `path_subdir=""` OK |
| `dotnet-sdk` | .NET SDK | **无**（`dotnetcli.azureedge.net` 本身是 CDN，但清华 / 阿里都没有同步它的制品树，实测 404） | `dotnetcli.azureedge.net/dotnet/Sdk/<sdk 版>/dotnet-sdk-<sdk 版>-win-x64.zip` | 0/1，进 `OFFICIAL_ONLY_EXCEPTION`。版本清单读 `release-metadata` JSON，登记的是 **sdk 版本号**（10.0.401）而不是 release 号（10.0.401 属于 release 10.0.12）；zip 顶层没有目录 ⇒ `path_subdir=""` |

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

## 规则 R2：组件分类分组与界面 Tab

### R2.1 规则描述

界面上 **182 个可见组件**归入且仅归入五个 Tab（183 个组件里含隐藏的 `erlang`），分类标准必须**机械可判**，不允许按感觉塞组件：

| 分类 | 判定标准 | 组件（含隐藏 erlang） |
|------|----------|--------------------|
| **一键启停** | 卡片上有「启动 / 停止」按钮 —— **成员由 `LAUNCH_KEYS` 派生，不另立清单** | activemq、consul、elasticsearch、etcd、jenkins、kafka、minio、nacos、nginx、rabbitmq、redis、rocketmq、seata、tomcat、zookeeper |
| **开发环境** | 装完进 PATH，直接用来写 / 编译 / 打包代码，**跑在本机开发机上** | ant、bat、bun、cmake、conda、dart、deno、dotnet-sdk、duckdb、eza、fd、fzf、git、go、graalvm、gradle、jdk、jq、kotlin、maven、ninja、node、pnpm、powershell、protoc、python、ripgrep、rust、sqlite、uv、yq、zoxide（+ 隐藏的 erlang） |
| **服务端组件** | 装在**服务器 / 集群**上、命令行操作的后台服务与运维组件（数据库 / 消息队列 / 网关 / 容器与编排 / K8s 运维）—— 原名「开发软件」，2026-10-14 改名 | caddy、docker、docker-compose、helm、jmeter、k9s、kubectl、mongodb、mysql、nats-server、postgresql、pulsar、traefik、trivy |
| **开发工具** | **只下载**的 GUI 软件：卡片只有「版本下拉 + 下载」，不解压、不配环境变量、不扫盘、不代跑安装器（`Component.download_only`，见 R13） | android-studio、apifox、apipost、ardm、bruno、clion、datagrip、dbeaver、dbx、eclipse、goland、hbuilderx、heidisql、idea、mongodb-compass、mysql-workbench、navicat、pgadmin4、postman、pycharm、redisinsight、visual-studio、vscode、webstorm,wechat-devtools、windterm |
| **Agent客户端** | 与「开发工具」**同类**（`download_only`，只下载不配置），单列一个 Tab 是因为它既不是开发环境也不是工具 —— AI 编程 / 办公 Agent 的桌面端与 CLI 发行包。成员由 `_AGENT_CLIENTS` 那张表派生（见 R13 与 R20） | cursor、zcode、claude-code、codex-cli、qoderwork-cn |

**Tab 顺序 = `COMPONENT_CATEGORIES` 的顺序**：

```
一键启停 → 服务端组件 → 开发环境 → 开发工具 → Agent客户端
```

顺序改过三次，都由用户指定：
- **2026-10-14**「一键启停」提到**第一个**（原先固定最后一个）—— 它是本工具最能干活的一组长，
  不许被埋在中间。
- **2026-10-14**「开发软件」改名「服务端组件」并提到**第二位**。
- **2026-10-15** 新增**第五个**「Agent客户端」，用户明确要求**放最后**。

后者为什么排第二：它与「开发环境」的界线是**东西跑在哪** —— 服务端组件装在服务器/集群上，
开发环境跑在你自己这台机器上。用户装东西时先问的就是"装服务器还是装本机"，
这个顺序直接对应那个问题。

`bt_component_category_tests` 里 `test_launch_tab_is_the_first_one`、
`test_server_tab_is_the_second_one`、`test_tab_order_is_exactly_launch_server_env_tool`
三条把整个顺序钉死。顺序断言换过三次方向（2026-10-08"紧贴「其它软件」"→
10-10"必须是最后一个"→ 10-14"必须是第一个"+整体序列），**意图始终是"这一组不许被埋没"**。

> **分类名请用 `CAT_LAUNCH` / `CAT_SERVER` / `CAT_ENV` / `CAT_TOOL` 四个常量，不要写裸字符串。**
> 这四个名字原先散落在 main.py 二十几处、tests 四个文件、六份文档里，改一次名要动 51 处。
> 其中一处尤其危险：`ComponentCard._render_icon` 的**分类色块**映射是拿分类名当键的，
> 键对不上**不会报错**，只会安静地落进兜底灰色，整个 Tab 的无图标组件一起变灰块。
> 现在那里也改用常量，并有 `test_color_map_keys_still_match_the_categories` 盯着。

> **上面这份名单与数字是 2026-10-14 的快照，且只作示例** —— 组件加得很快（2026-10-10 还是 43 个，
> 四天后就 87 个）。**权威值一律现算**，别照抄本文：
> `.venv/Scripts/python.exe -c "import _btprelude,main;cs=main.build_components();import collections;print(len(cs), collections.Counter(c.category for c in cs))"`
> 分类的**真源**始终是 `COMPONENT_CATEGORY_OF` + `LAUNCH_KEYS`（见 R2.3），不是这张表。

边界争议按此顺序裁决：**是不是只下载不配置的 GUI 软件** → 是则开发工具（这一条最先看，它决定卡片形态而不是归属）；否则**能不能在本工具里一键启停** → 是则一键启停（这一条优先，不看性质）；否则**是装在本机还是装在服务器上** → 装本机则开发环境，装服务器则服务端组件。

> 改名的理由（原「开发软件」为什么不行）：那个名字**太空**——"软件"是万金油，四个 Tab 里
> 唯一一个不描述功能的；而且它和隔壁「开发工具」在中文里近乎同义词，用户根本分不清界线。
> 「服务端组件」只说一件确凿的事：**这 14 个全是装在服务器上、命令行操作的，没有一个是 GUI**，
> 正好和「开发工具」（26 个全是 IDE / GUI 客户端）形成清晰对照。

（2026-10-10 取消「其它软件」Tab：它只剩 docker、kubectl 两张卡，用户要求并进服务端组件。注意 `group_components()` 给每个分类都建空列表、建 Tab 的循环**不跳过空组** —— 只挪成员而不从 `COMPONENT_CATEGORIES` 删名字，界面上会多出一个「其它软件（0）」空白页。）
（例：Maven / Gradle 是命令行构建工具，进 PATH 才能开工，属开发环境而非"服务"；PowerShell 是进 PATH 的 Shell / 脚本运行时，属开发环境；kubectl 虽然操作的是集群，但它是**本地命令行客户端**，按"装在哪"判属服务端组件。）
（例：Tomcat / Nginx / Jenkins 这类需要跑起来给项目用的服务属**一键启停** —— 能一键起停优先于性质，见上。）

### R2.2 适用范围

- `Component.category` 字段与 `COMPONENT_CATEGORY_OF` 登记表
- `group_components()` 与 `MainWindow._build_ui()` 的 Tab 构建
- 新增 / 改名 / 删除组件时的分类登记

### R2.3 实施指引

分类**只有一个真源**：`COMPONENT_CATEGORY_OF`（`main.py`，`build_components()` 之前）；
可启停那一组**由 `LAUNCH_KEYS` 派生**，不在分类表里重复登记。

```python
# 分类名一律用常量，不写裸字符串（见 R2.1 的说明）
CAT_LAUNCH, CAT_SERVER, CAT_ENV, CAT_TOOL = "一键启停", "服务端组件", "开发环境", "开发工具"

COMPONENT_CATEGORIES = (CAT_LAUNCH, CAT_SERVER, CAT_ENV, CAT_TOOL, CAT_AGENT)   # Tab 顺序即此顺序
COMPONENT_CATEGORY_OF = {
    ...
    "foo": CAT_SERVER,        # 新增组件在这里加一行（它接进 LAUNCH_OF 后会自动进「一键启停」）
}
```

> `COMPONENT_CATEGORIES` 这行是**代码片段示意**，不是当前值。Tab 顺序 2026-10-14 调整过两次，
> 权威值看 `main.COMPONENT_CATEGORIES`，或在测试里用
> `test_tab_order_is_exactly_launch_server_env_tool` 核对。

`build_components()` 末尾统一执行
`comp.category = "一键启停" if comp.key in LAUNCH_KEYS else COMPONENT_CATEGORY_OF[comp.key]`——
写成第二张表的话，接入第 11 个可启停组件时会出现"能启动、卡片却在别的 Tab"；
而分类表里的旧归属保留作 fallback，组件从白名单退下来时会自动回到原来那一组。
**不要**在各 `Component(...)` 构造处手写 `category=`，也**不要**给 `.get(key, 默认值)` 兜底：
**不要**在各 `Component(...)` 构造处手写 `category=`，也**不要**给 `.get(key, 默认值)` 兜底：
（上一段已写明不许 `.get` 兜底）漏登记必须 KeyError 炸出来，静默归到某个分类会让新组件"消失"在错误的 Tab 里。

`MainWindow.cards` 必须保持**全量平铺**（当前 87 项，跨 Tab 收集；数字会随组件增减而变，别写死）：刷新版本、读写配置、关窗前等探测线程都遍历它，分组只改变卡片的父布局。

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
  列表模式 = 强制 1 列，卡片内部一模一样。**按钮在搜索条上，不在标题栏**：标题栏已有 6 个按钮 + 3 个窗口控制，
  实测需要 ~992px，窗口才 1000 宽，再加必然把已有按钮压到裁字

底部日志区已**移出 `QSplitter` 的 3:2 分配**，改成浮层（同 parent + `raise_()`，几何随 resize 跟随），
展开时**遮住**最下面一行格子而不是把网格压扁。选浮层的理由：它不在 `body` 的布局里，`show/hide` 不触发
重排 ⇒ 列数与行数只由窗口宽度决定，开关日志不会让格子忽大忽小，也省掉"挤压式折叠"的二次 relayout。
触发规则（**2026-10-14 用户要求改写**）：**日志浮层永不自动弹开、也永不自动收起**。
`warn` / `error` 只累加未读数并写在 `📋 日志 (N)` 按钮文字里（不新增控件），
用户想看点一下按钮；再点一次收起。手动打开即视为已读，未读清零。

> **旧策略与它为什么失败**（别再改回去）：原先是"只有 warn/error 才自动弹开 + 静默
> `LOG_AUTO_HIDE_MS = 8000` 后自愈收起"，并配一个"启动后 `LOG_AUTO_POP_DELAY_MS = 10000`
> 内不自动弹"的静默期。那个静默期只挡住启动**头 10 秒**，而一轮版本抓取要 **30~40 秒**，
> 于是第 12 / 25 / 35 秒到达的告警（GitHub 限流、各组件抓取失败）全都晚于 10 秒，照弹不误。
> 表现上像随机 —— 网络快时失败来得早被挡住、看着正常；网络慢或撞限流时失败来得晚就弹，
> 于是用户报告"偶尔还是会自己打开"。
>
> 现在整套基础设施已删除：模块级常量 `LOG_AUTO_HIDE_MS` / `LOG_AUTO_POP_DELAY_MS`、
> 方法 `_log_autopop_allowed()` / `_on_log_auto_hide()`、窗口属性 `_log_auto_hide` /
> `_log_user_open` / `_startup_mono`。**一个都不许复活**——那个 bug 的成因正是
> "一个听起来合理的静默期其实盖不住真正的时长"。
> 护栏用例：`bt_install_safety_tests.LogOverlayNeverAutoPops`（6 条，含"连发 50 条告警
> 也不许弹"与"这一整套符号必须不存在"的反向断言）。

### R2.4 新增 / 调整组件分类 checklist

- [ ] `COMPONENT_CATEGORY_OF` 里登记了该 key，且值取自 `COMPONENT_CATEGORIES`
- [ ] 按 R2.1 的判定顺序核对归类理由，有争议的在 PR 说明里写清
- [ ] `bt_component_category_tests.py` 通过（其中 `EXPECTED_MEMBERSHIP` 是分类基线，改归类要同步改它）
- [ ] 未新增 `if category == ...` 之类的界面特判——分组渲染只走 `group_components()`
- [ ] README / README_EN 的四 Tab 表格与 `CODE_WIKI.md` 的 `category` 字段说明同步
- [ ] 只下载型的还要逐条过 R13.2 的八个短路点，并按 R1 实测过每一条 URL；新组件不许靠「表里没写就不用查」逃过 `bt_mirror_spec_tests`，要在豁免表里点名登记

### R2.5 组件搜索框

组件数上到 32 个后逐页翻不现实，Tab 上方有一条搜索框做名称模糊过滤。约束：

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
  右侧 `#searchHint` 仍显示"匹配 N / 87 个组件"（0 命中转警示红）。数字一律现算（别写死，组件数在涨）
- 这正是"全组件搜索、而不是只搜某个 table 内"的要求：结果跨三个分类，统一归并展示
- 新增组件**不需要**为搜索做任何登记：卡片建好就自动可搜。改匹配规则要同步 `bt_search_and_newcmp_tests.py`
- 外观约定：输入框不直接描边，而是套一层胶囊外壳 `#searchShell`（放大镜 + 输入框同属一块白底圆角），
  聚焦时**整条外壳**描蓝边 —— 为此 `MainWindow.eventFilter()` 监听输入框焦点、经 `_set_search_focus()`
  改外壳的 `focused` 属性并 `unpolish/polish` 重刷样式（QSS 的 `:focus` 选不到父级控件）。
  放大镜与清空按钮图标都用 `QPainter` 现画，不加图片资源；清空按钮用 `QLineEdit.TrailingPosition`
  的 QAction 代替内置清除按钮，以保证跨平台观感一致、颜色可控

### R2.6 搜索卡顿的真因：搬家会触发 QSS 重算（2026-10-15 实测）

用户报"左上角搜索响应太慢"。**先测再改**，实测口径是造一个真窗口（offscreen）、
让 128 张卡都在，然后按真实交互序列打点。最终结果：

| 场景（128 组件，命中数见括注） | 原始 | 现在 |
|---|---|---|
| 搜索态之间 `a` → `e`（各百余命中） | 4288 ms | **213 ms** |
| `e` → `i` | 3648 ms | **158 ms** |
| 输入 `a` 后改成 `zzzz`（→0 命中） | 1285 ms | **18 ms** |
| 逐字敲 `cursor` 小计（84→3→1） | 3978 ms | 2387 ms |
| 浏览态 → 搜 `a`（进入搜索，115 命中） | 2331 ms | 757 ms |
| 清空回浏览（退出搜索） | 1447 ms | 1442 ms |

**打字过程中改词**快了一个数量级（20 倍上下）——这正是用户抱怨的那件事。
剩下两个大数字是**进入/退出搜索那一次性**的：一百多张卡整体搬一次家，各约 0.7 s / 1.4 s，
那是 Qt 给每张卡重算样式的硬成本（见下）；要再压就得把浏览 Tab 的行也换成无宿主布局，
而浏览态的像素断言与 `_reveal_running_tabs` 都按 `cardRow` 找行，风险另算。

**真因不是"逻辑重"，是 Qt 的样式重算。**三组对照实验（同一个 `_apply_search('a')`）：

| 改动 | 耗时 | 说明 |
|---|---|---|
| 基线 | 2449 ms | |
| 套 `setUpdatesEnabled(False)` | 1622 ms | 只省掉重绘那部分，约 1/3 |
| **临时代码里摘掉窗口样式表** | **339 ms** | **7.2 倍** —— 82% 的时间是 QSS |

`theme.QSS` 挂在**窗口**上（`main.py` 的 `_apply_theme`），里面有 `#card` 这条规则；
于是**每搬一次家**（`setParent` / `layout.addWidget` 把卡片换父级）都会让
`QStyleSheetStyle` 把该卡**整棵子树**重新解析一遍样式。

一条特别反直觉、也最该记住的实测：

> **搬到"同一个父级"也不便宜。** `card.setParent(卡片当前父级)` 实测仍约 **5 ms/张**，
> 因为 Qt 照样走一遍 `inheritStyle` → 重新 polish。115 张就是 ~0.6 s。
> 所以"顺手再 setParent 一次确保正确"是纯粹的净损失，不是无操作。

### 由此得出的四条实现约定

1. **搜索结果的行用无宿主的 `QHBoxLayout`，不是 `QWidget#cardRow`**（`_make_layout_rows`）。
   `QLayout::addChildWidget` 把控件 reparent 到**布局的 `parentWidget()`** ——
   行是 `QWidget` 时卡片父级变成那个新行，而布局的 `parentWidget()` 就是容器本身，
   **卡片父级不变**，整条 polish 路径被跳过。实测同一份 115 张卡：

   | `_make_rows` 的做法 | 耗时 |
   |---|---|
   | 行控件 `QWidget#cardRow` | 1001 ms |
   | 行是 `QHBoxLayout` | **3.5 ms** |

   代价：行没有 `objectName` 了，`_drop_rows` / `_clear_results_layout` /
   `CardColumnLayout.indexOf` 三处都要认「行也可能是布局」。**Tab 的行不动**
   （浏览态的 `findChildren` / 像素断言 / `_reveal_running_tabs` 都按行控件写）。

2. **搜索期间一张卡都不许"搬家"**：不再是命中项就只 `setVisible(False)`，
   **不要**顺手送回 Tab。逐字输入时这最贵 —— 实测 `'c' → 'cu'`（84→3 命中）
   光是送回这 81 张卡就要 **0.7 s**。它们留在结果面板宿主上藏着，退出搜索时一次扫干净。

3. **退出搜索时那记扫尾不能省**（`_clear_results_layout(send_home=True)` 末尾按
   `card.parent() is self.results_content` 全量扫一遍）。搜索期间留下的卡片**不属于任何一行**，
   而"拆行"那圈只走到"行里的卡"—— 漏掉这步的后果是**清空搜索后卡片凭空少一批**：
   结果面板是 `top_stack` 的隐藏页，卡挂在那儿 = 浏览态里消失。
   2026-10-15 自查时实测到清空后仍有 **115 张**卡留在 `results_content` 上（自动化用例全绿、
   只有专门写脚本按"卡片的父级是谁"点数才看得出）。判据脚本见下方"自查"一句。

4. **重建期间关重绘**（`setUpdatesEnabled(False)`，`try/finally` 兜底 —— 异常也必须还回去，
   否则窗口从此不再刷新），以及**删掉 `_build_unified` 里那句多余的
   "先把命中的卡挂到 `results_content`"**（`_relayout_results` 紧接着会做同一件事）。

**自查这类"卡片搬家"改动的最小手段**（比看用例红绿可靠）：
起一个真窗口，按 `'a' → 'zzzz' → ''` 这类序列打完，然后数
`sum(1 for c in win.cards if c.parent() is win.results_content)` ——
**清空之后它必须是 0**；搜索态下它是"刻意的非零"（就是第 2 条省下来的那批）。

**这条 286 倍的收益已经在 2026-10-15 落地**（用户看过数据后拍板"现在就改"）。
改完同步了两处按"行是控件"写的测试断言：`bt_grid_layout_tests` 的
`_row_cards` / `_row_cells`（现在三种行形态都认）与 `bt_search_and_newcmp_tests._result_widgets`
（遇到 `item.layout()` 也要钻进去收卡片）；`CardColumnLayout.indexOf` 同样加了布局行分支
（`_reveal_running_tabs` 那一族按它判归属，漏了会静默失效）。

另外两条**试过但否掉**的方案，别再走一遍：把窗口样式表整段摘掉再挂回（恢复那一次
`setStyleSheet(QSS)` 本身要 681 ms，净赚只有 18%）；以及"防抖"（`textChanged` 后延时再搜）——
`bt_search_and_newcmp_tests` 有一批用例是 `search_box.setText(...)` 之后**立刻**断言的，
加防抖会成批变红，且会改变"同步出结果"这个既有语义。

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

**现在作废**：32 个组件**全部**支持多版本（用户 2026-06-06 要求）。理由与前提：
- 32 个组件本来就有 2-4 个版本的候选清单，能装多个版本不需要额外能力；
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

**一条仍然有效的豁免**：「安装」的"选中版本已装则置灰"对全部 32 个组件生效，
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

面向**全部 32 个组件**：`_installed_here(version)` 判"目录存在 **且** 里面找得见该组件可执行文件"
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

### R3.13 不提供"验证终端"入口，让用户用系统自己的新终端验证

> **2026-10-14 用户取消本节原先要求的功能。** 原先是顶栏 `btn_clean_terminal`（「🖥 开验证终端」）
> 用 `EnvManager.composed_env()` 现算的环境块起一个 `cmd.exe`，理由是"给一个必然干净的窗口才有结论"。
> 现按用户要求移除，连同 `open_clean_console()`、`_on_clean_terminal_clicked()` 与护栏用例
> `CleanTerminalWindow` 一并删除。原因有二：
>
> 1. **标题栏只留"每天都会用"的动作**。这一颗属于"出问题时才用"，常年占着最宽的位置却不点。
> 2. **那条能力是可替代的**：Windows 把环境块**复制**给新进程，用户**自己新开的**
>    PowerShell / cmd 窗口拿到的就是系统现算的那份环境，与工具开的窗口等价。
>    所以取消的是"替用户开"这个动作，不是"能不能验证"。
>
> 配套保留：`_log_verification_hint` / `stale_shell_lines`（R3.12）仍然把"比这次切换更早、
> 还开着的终端"点名到 pid，日志里也仍然给出原地刷新 PATH 的 PowerShell 命令。
> **回归护栏**：`bt_feedback_tests.DiagnosticsExport.test_export_button_is_wired` 里有一条
> 反向断言钉住 `btn_clean_terminal` / `btn_diagnostics` 不许复活。
>
> 若将来要重新加回来：能力本身没丢，从 git 历史取回 `open_clean_console()` 即可；
> 但**必须先量标题栏预算**（见下一段），并且不要把它做成唯一入口。

**加标题栏按钮要重量最窄窗口**：标题栏（标题 + 按钮 + 窗口控制）实测需要 ~992 像素，
而窗口最小宽原本只有 880 —— 布局早就在挤压标题文字，多一个按钮后开始把
「清理残留 PATH」压到裁字（178→144）。已把 `setMinimumSize` 抬到 1000（正好等于默认宽），
并给四个文字按钮设 `QSizePolicy.Fixed`。`test_title_bar_buttons_are_not_clipped_at_minimum_width`
钉住这条；注意 `QLabel.setMinimumWidth(0)` 和 `QSizePolicy.Fixed` **都挡不住**总宽不足时
布局的挤压（实测仍裁字），唯一有效的是把窗口最小宽抬到实际需要的值。

> 量预算的工具：`tools/bt_titlebar_budget.py`（它显式 `pop("QT_QPA_PLATFORM")` 走真实平台）。
> **2026-10-14 移除「开验证终端」「导出诊断」两颗按钮后，实测整行只需 580 像素**
> （chip 最长文案「↓ v1.10.0 待更新」占 111），1000 这一档余量充足。
> 该脚本的 `NAMES` 元组里还留着已删的两个按钮名 —— 无害（找不到就 `continue`），
> 但下次动它时顺手清掉。

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

- 2026-10-09 Python：当时 Windows 装的是 embeddable 包（`python-3.x-embed-amd64.zip`），
  `python.exe` 就在解压根目录、包里**压根没有 `Scripts`**，而组件声明写的是 `path_subdir="Scripts"`。
  后果不是"显示不好看"，是**整条切换链白做**：PATH 指向一个没有解释器的目录 →
  `python` 永远命中机器上自己装的那份 → R3.19 提权把这条没用的目录插到系统 PATH 最前，
  复验照样命中机器上原有那个 → 自动回滚，用户连着看到两次"系统变量已改，但复验未通过"。
  （2026-10-28 起 Windows 已换成 NuGet 完整包，布局变成 `tools/python.exe`，
  `path_subdir="tools"`；**布局会随发行形态变，所以这条实测纪律不能省**。）
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
5. **"解压后只有一个顶层目录 ⇒ 那个目录就是根"这条判定，必须再加一个条件：根上没有散文件。**
   2026-10-12 真机装机演练抓出来的两条同根因：
   `pnpm` 的 zip 是 `dist/` + 根上的 `pnpm.exe`，`trivy` 是 `contrib/` + 根上的
   `trivy.exe` + 一堆 `.tpl`。旧判定只数目录，于是 home 返回 `dist/` / `contrib/`，
   **把根上的可执行文件整个留在 install_dir 之外** —— 装完 PATH 指着一个只有
   node_modules 的目录，命令永远找不到，界面上只表现为"装了但用不了"。
   更值得记的是**审计脚本当时报的是 OK**：`tools/bt_archive_layout_audit.py` 的
   `_root_prefix()` 早就按"根上有散文件就不算单顶层"建模了，它建模的是**应有行为**，
   而代码是另一回事。所以这条规则的另一半是：**审计脚本与产品判定必须逐字同构**，
   改一边就同步改另一边（本轮已把 `extract_archive` 收成
   `len(dirs) == 1 and not loose`）。
    用例：`bt_new_components_tests.SingleTopDirRule`（三条边界：1 目录+散文件⇒根 /
   只有 1 目录⇒那层 / ≥2 目录⇒根，后两条是既有组件的保护栏，防止把改动波及 jdk/maven）。
   > **2026-10-12 缺口**：这组用例原先在 `bt_protoc_uv_tests.py` 里，那个文件**从未提交过**，
   > 收尾时被 `git clean` 误删且无备份可恢复；规则断言已迁到上面那个文件，
   > 同文件里 protoc / uv 的**资产名筛选**断言（"只发源码包的 tag 不许被收进清单"）
   > **目前缺失**，下批接 protoc 侧组件时必须补回。

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
10. **版本号够 ≠ 可用：还必须能建 venv**。`-c "import venv,ensurepip"` 不通过的一律跳过
    （记 `EMBED_SKIPPED`，继续走后面的发现 / 自举链，并打印 `step1_embed` 说明原因）。
    2026-10-28 真机：ByteTools 的 Python 组件在 Windows 装的是官方 **embeddable** zip
    （无 `Lib/`、无 `venv`、无 `ensurepip`），并且就在 PATH 上；旧发现逻辑只看版本号，
    选中它之后 `python -m venv` 直接 `No module named venv`，一键配置在第一步就断了。
    两个探测口（`:try_cmd` 与 `:try_exe`）必须都问这一句

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

- `LAUNCH_KEYS` 里的组件。**不手写清单**：真源是 `main.py` 的 `LAUNCH_OF`，
  `LAUNCH_KEYS = set(LAUNCH_OF)` 由它派生（`bt_launch_tests.py` 会把实际集合钉死）。
  此处曾写死 `{"jenkins", "activemq", "nacos"}` 并长期漂移到落后 12 个组件 ——
  手抄的第二份白名单必然对不上。
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
11. **占位符替换表只许有一份**（`_launch_mapping()`）。2026-10-12 真机第一次起 etcd，
    点「启动」当场 `KeyError: 'peer'` —— 那天早些时候为修 `{peer}` 只补了
    `_plan_mapping`（pre_start 走的重建表），而拼 argv 的 `build_launch_plan` 里
    还留着自己手写的第二份。两处各抄一遍，改一处必然漏另一处，而且**漏的那一处
    只在真点启动时才炸**，离线用例全绿。现在 `build_launch_plan` 与 `_plan_mapping`
    都调 `_launch_mapping()`；护栏 `LaunchMappingCoversEveryPlaceholder` 两头都过：
    走真实 `build_launch_plan` 断言 argv 里不许残留花括号，再走 `_plan_mapping`
    断言 spec 里出现过的每个 `{token}` 都取得到值。

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

`bt_launch_tests.py`（全离线，不真起中间件；用例数以 `.venv/Scripts/python.exe -u tests/run_all_tests.py` 的输出为准——数字写在文档里只会漂移，实测曾长期停在 133 而实际已 257）盯住：
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
> 的 `conf_copy` 分支改成"忽略回写失败、照样返回 True"时 129 条全绿）。原因是原有用例只分别钉住两端 ——> `ConfCopyWriteback` 钉 `set_property_line` / `set_openwire_port` 单独调用时会拒改，
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

### R5.7 访问页服务必须独立于主进程；MySQL 的初始化只在空目录上跑（2026-10-28）

**问题一（Redis 访问页随工具退出）**：访问页原先由主进程里的一个 daemon HTTP 线程提供。
组件进程是 `DETACHED_PROCESS` 拉起的，关掉工具它还在；页面却跟着主进程没了 ——
用户看到的是"服务还活着，访问页打不开"。

现在的结构：

- 页服务是一个**独立进程**：`ByteTools.exe --bt-page-server`（源码下是
  `python main.py --bt-page-server`），由 `_spawn_page_daemon()` 用
  `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` 拉起，**不随主程序退出**。
- 端口由 OS 分配，`{port, pid}` 写到 `~/.env-tools/page-server.json`；
  下次启动先读它、用 `/healthz` 确认是不是我们的服务，活着就复用，不再起第二个。
- 页面内容每次请求都从 `running.json` 现算（`_render_component_page`），
  不存回调、不存渲染好的 HTML；服务停了页面自己变成「已停止」。
- 卡片点「访问页」时**现取** `get_page_daemon().url_for(key)`，所以页服务换过端口
  （重启、崩溃后重拉）也不会给用户一个死链接。
- 进程内实现 `ComponentPageServer` 保留给单元测试（`BYTE_TOOLS_PAGE_SERVER=inproc`），
  独立进程起不来时也退回它（至少本次会话内页面可用）。
- 护栏：`bt_launch_tests.DetachedPageServer`（真起子进程、临时 HOME、/healthz、
  running.json 现渲染、停止后 404）。

**问题二（MySQL 启动状态 + 初始化）**：MySQL 之前不在 `LAUNCH_OF`，所以卡片没有启动/停止。
2026-10-28 接进「一键启停」，实测链路：`--initialize-insecure`（约 2s，root 无密码）→
启动（约 1s ready）→ `mysqladmin shutdown`（Normal shutdown，端口立即释放）。
两条硬约束：

1. **`--initialize-insecure` 只能跑在空数据目录上**。`start()` 不许在 pre_start 之前
   建 `data_dir/logs`（已改成先只建 `data_dir`，日志目录等 init 完再建）。
2. **`cluster.id` 只在模板真的引用 `{cluster_id}` 时才写**。`_launch_mapping` 原来
   无条件 `read_or_create_cluster_id()`，会给 MySQL 的数据目录塞一个 `cluster.id`，
   初始化当场报 `directory ... is unusable`。现在先扫所有模板，只有 Kafka 会落这个文件。
3. 首次初始化用 `LaunchSpec.pre_start_if_missing = "{data_dir}/mysql"` 做幂等哨兵；
   第二次点启动直接跳过 pre_start（护栏 `test_mysql_pre_start_runs_initialize_only_when_schema_is_missing`）。

---

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
`#versionChip`（点它按当前状态分派，见 R12.5），另有标题 tooltip、macOS bundle 的
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

新增文档里提到"这个软件"时用 **ByteTools**；提到上面几类时按原样写。

## 规则 R12：检查更新只读、后台、自动路径失败完全静默，且绝不替换自己

2026-10-10 加的功能，范围是用户拍定的 **A + B**：查版本 + 提示 + 应用内把新包下到
**用户挑的目录**；**不做"一键升级替换自己"**（要做必须单独出 spec）。

### R12.1 端点是实测出来的，不是想当然

| 端点 | 2026-10-10 本机实测 | 用法 |
|---|---|---|
| `https://api.github.com/repos/jilong2026/byte-tools/releases/latest` | **200 / 1.2s / 8.6KB / 免鉴权** | 主源 |
| `https://gh-proxy.com/<上面这个 URL>` | **200，代理回来的也是真 JSON** | 兜底源 |
| `gitee.com/api/v5/repos/jilong2026/byte-tools/releases` | 404 "Not Found Project" | **当时据此写了"Gitee 不能当更新源"，是错的**：Gitee 侧 owner 是 `jack_liujilong` 不是 `jilong2026`。用对 owner 免鉴权 200，见 R12.6 |
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

`bt_update_check_tests.py`（全离线，用例数以 `run_all_tests.py` 输出为准：`check_for_update(fetch=...)` 是可注入接缝，
测试不联网）：响应解析与拒绝形状、无产物 Release、数值版本比较、两时代产物挑选、
24 小时频控、同版本只提示一次、失败静默位、加速器兜底、隐私线、
chip 初始文字、自动失败不写日志 / 手动失败要回答，外加 R12.5 那五条：
有新版时 `↓` + 新版本号且 tooltip 同时给出当前版本、`latest` 与 `error` 两态可区分、
点击直接下载并**断言 `QFileDialog` 一次都没被调**、下载中再点不开第二路、
进度行只有百分比且封顶 99%。（`DownloadWorker` 与 `load_download_dir` 都打桩：
用例不许真下 49 MB，也不许写用户真实 config.json。）

### R12.5 chip 是一颗四态状态灯，不是一个「检查更新」按钮

2026-10-10 用户改的需求：点版本号时如果有新版就**直接开始下载**，chip 变成百分比；
没新版要提示已是最新；网络问题要提示网络问题。于是这颗 chip 从"永远检查一次"
变成**按当前状态分派**的控件，状态只有 `_set_chip_state()` 一个出口。

| 状态 | chip 文字 | 配色 | 点击行为 |
|---|---|---|---|
| `idle` / `checking` | `v1.2.1` | 默认 | 查一次 |
| `latest` | `v1.2.1` | 默认 | 再查一次（tooltip 写明"已是最新"） |
| `update` | `↓ v1.2.2` | 琥珀 | **直接下到 `download_dir`**，不弹确认、不弹目录框 |
| `downloading` | `↓ 37%` | 琥珀 | 不开第二路，只回一句"正在下载" |
| `error` | `? v1.2.1` | 灰 + 虚线边 | 再查一次（tooltip 带失败原因） |

四条不可回退的约束：

1. **版本号任何时刻都在**（只有 `downloading` 那一分钟换成百分比）。它是全 app 唯一的
   版本落点（底部那份 2026-10-10 已按要求删掉，见 R11），报问题、对 Release 全靠它，
   所以"换成一个下载图标"这个方案被否掉了 —— 省下的那点宽度不值这个代价。
2. **`latest` 与 `error` 必须一眼分得开**。R12.2 原来要求"自动检查失败完全静默"，
   那是不弹窗、不写日志；chip 一旦当状态灯用，**继续显示普通版本号就等于谎报"没有新版"**。
   所以"静默"的含义收窄成"不开口"，灰色 `?` 仍然要亮，tooltip 里带失败原因与"不影响使用"。
   代价：这台机器对 github.com 偶发整天连不上是常态，那种日子 chip 会常驻灰问号。
3. **进度只写百分比**，速度/剩余字节走日志。标题栏宽度是硬约束：历史上多加一个按钮
   就把「清理残留 PATH」压到裁字（最小宽 1000 那条教训）。
4. **下载中再点不许起第二路**（约 49 MB），也不许把 chip 打回 `update`。
   百分比封顶 99%：字节没落盘就说满 100% 是撒谎，落盘与核对由 `finished_ok` 另报。

仍然不做的事：**不替换、不重启正在运行的自己**（R12.2），下完只问一句"打开所在文件夹"。
点 chip 走的是 `_on_version_clicked()` → 有新版才 `_begin_app_update_download()`，
其余状态一律退回"查一次"。


---

### R12.6 下载第一源是 Gitee，查询第三源也是 Gitee（2026-10-10 实测改的）

**先记一条被打脸的结论**：R12.1 的表里原本写着「Gitee API 回 404『Not Found Project』
⇒ 不能当更新源」。那是**拿 GitHub 的 owner 去问 Gitee** —— 本仓库两边不同名
（GitHub `jilong2026`，Gitee `jack_liujilong`）。用对 owner 之后免鉴权 200。
又一例「0 命中 ≠ 不存在」：域名对了、路径对了，owner 猜错就是一份 404。

| 端点 | 实测（2026-10-10 深夜，UA=byte-tools） |
|---|---|
| `gitee.com/api/v5/repos/jack_liujilong/byte-tools/releases` | 200 / 5,835 B。**回的是数组、按 tag 升序**（v1.1.2 在 v1.2.0 前面），且没有 `draft` / `html_url` / `asset.size` 三个字段 ⇒ 单独一个 `parse_gitee_releases`，按版本号挑最大，size 记 0 |
| `gitee.com/<owner>/<repo>/releases/download/v1.2.0/ByteTools.exe` | 302 → 302 → `foruda.gitee.com/attach_file/...?token=<时效签名>` → **200 / 49,963,621 B / `MZ`，2 MB/s**，匿名可下。**Range 被忽略**（发 `-r 0-3` 照样回整包）⇒ 不能断点续传 |
| 同一形状、tag 换成没同步过的 | 404（Gitee 的附件靠本机 `同步Gitee产物.bat` 手工上传，没同步就是没有）|
| `gh-proxy.com` 代理 GitHub 产物 | 当天 116–225 KB/s（49 MB 要 4–7 分钟）|
| `api.github.com/.../releases/latest` | 未认证 **60 次/小时/IP**，今天被探测打到 403 `remaining=0` |

于是两条排序，理由不同：

- **查询**：GitHub 官方 → GitHub 加速器 → **Gitee**。GitHub 放前面只因为它的响应带 `size`，
  那是下载完成后唯一能核对的强校验；Gitee 排第三是给"GitHub 被拦/超配额"的日子兜底。
- **下载**：**Gitee 直链** → GitHub 加速器 → GitHub 裸地址。2 MB/s 对 0.12–0.23 MB/s，
  实测端到端 24.5 秒下完 49,963,621 字节。

三条纪律，都是这轮踩出来的：

1. **Gitee 的 URL 绝不进 `_gh_accelerated`**。首轮真机实测就中招了：把 Gitee 直链丢进去，
   得到 `ghfast.top/https://gitee.com/...` 这种没人代理过的地址，四个源全废，
   而 GitHub 兜底反而消失了。`update_download_urls()` 里对 `github.com/` 的判断就是这道闸。
2. **签名地址不许进日志**。302 链里那条 `foruda...?token=` 带令牌与时效；
   `DownloadWorker` 打的是我们自己传入的稳定 URL，实测整次日志 0 行含 `token=` / `foruda`。
   改成打 `url_effective` 就会泄漏 —— 别那么改。
3. **远端产物名要削**（`_safe_download_name`，见 R14.2）。Gitee 与 GitHub 的 `name` 都是外部输入，直接 `目录 / 名字` 会被绝对路径劫持。
4. **拿不到 size 时要如实说**。从 Gitee 清单来的产物 size=0，开始下载前记一句
   「本次的官方清单没给字节数，完成后只核对文件头魔数」，完成日志也不再写"字节数已核对"。
   魔数（`.exe` → `MZ` / `.zip` → `PK`）现在无论哪个源都必带。

用例在 `bt_update_check_tests.GiteeAsFirstSource`（6 条，全离线）：Gitee 只在 GitHub 两源
失败后才登场、URL 不带查询参数、Gitee 数组按版本号挑最大、size 记 0、
**Gitee 那条不许被加速器套前缀**、产物来自 Gitee 时仍要补出 GitHub 兜底、
下 `.exe` 必须带 `expect_magic=b"MZ"`。

---

## 规则 R13：「开发工具」是只下载的一类，八个短路点少一个就污染用户机器

### R13.1 为什么单独立一条规则

用户要的是别家工具箱那种「常见开发软件」页：IDEA / PyCharm / CLion / Navicat / Xshell / 微信开发者工具 / HBuilderX…
本工具原有的整条链路是为**可解压、靠环境变量生效**的组件设计的：下载 → 解压到 `~/.env-tools/<key>/<key>-<ver>`
→ 写 `XXX_HOME` + `PATH` → 下拉框绿勾 → 切换生效版本 → 卸载。GUI 软件走这条链的每一环都是错的：
`.exe` 解压不出可用程序，写 PATH 没有意义，"生效版本切换"更无从谈起。

结论是**不改造老链路，而是加一类**：`Component.download_only`。它只干两件事——列版本、把官方安装包下到用户挑的目录。

### R13.2 硬约束（缺一条就是 bug）

1. **绝不代跑安装器**。`installer_mode` 那条路（Miniconda 在用）会静默执行安装程序，
   而 JetBrains / 微信 / Apipost 的安装器第一步就是 EULA —— 静默跑等于**我们替用户点了同意**。
   只下载型组件的收尾最多是"要打开所在文件夹吗"，安装由用户自己双击。
2. **八个短路点**，逐条对应一个会被污染的地方：
   | 位置 | 不短路的后果 |
   |---|---|
   | `multi_version = not download_only`（`build_components` 末尾） | 长出「可多版本」角标（角标条件就是它） |
   | 卡片不创建 `btn_configure` / `btn_uninstall` 节点 | 给用户两个点了会写注册表的按钮 |
   | `_sync_action_buttons` 首行 return | 访问不存在的按钮 + 按"装没装"算启用条件（要扫盘） |
   | `_detect_status_impl` 首行 return | 建卡即 `installed_versions` → `installed_dirs` 扫 `~/.env-tools/<key>` |
   | `_reload_combo_items` 里"默认选中已装版本"那次扫描 | **计划里漏了这条**，是用例抓出来的：建卡时照样扫盘 |
   | `_combo_version_list` 只返回官方清单 | 合成"磁盘已装"的伪条目 |
   | `_refresh_installed_marks` 首行 return | 下拉框挂绿勾，用户以为已安装 |
   | 槽位用 `on_download_clicked` 而不是 `on_install_clicked` | 下游 `install_downloaded → _configure_after_extract → apply_active_version → _configure_env` 每步都写环境（`_configure_env` 连 `env_var=None` 都会 append PATH） |
3. **下载要校验文件头魔数**。`DownloadWorker` 的 `expect_magic` 默认空（32 个老组件行为逐字不变），
   只下载型必须传 `PK` / `MZ`。理由不是洁癖：实测 `mirrors.huaweicloud.com/jetbrains/…` 回
   **200 + 12 KB HTML**，这个体量轻松越过 `DOWNLOAD_MIN_VALID_BYTES`(4096) 那道字节数下限，
   只比字节数会判它成功，用户拿到的是后缀写着 `.exe`、内容是网页的文件。
4. **落盘不许覆盖同名文件**（补 ` (2)`），**目录记在 `config.json` 的 `download_dir`**
   （读-改-写，整体覆盖会连带清掉 `active` / `selections` / `takeover`），记录被删则安静回落 `~/Downloads`。
5. **商业档必须把"不含授权"写在看得见处**。只下载卡片没有卸载确认框，而 `data_note` 平时恰恰是靠那个框露出来的
   —— 所以这批的说明挂在主按钮 tooltip 上，有专门用例钉住（`test_commercial_products_are_labeled_no_license`）。
6. **版本号一律取接口给的 link，不按文件名规律拼**。JetBrains 把 Community 并进主线后
   `IIU` 的文件叫 `idea-2026.2.3.exe`（不再带 IC），而 `IIC` 这个码最新只停在 2025.3；
   产品码也要查官方清单（CLion 是 `CL`，不是猜的 `CLW`）。
7. **抓取器失败一律抛异常，不许返回空表**：返回空会让下拉框被灌成空的，
   用户看到的是"点了刷新版本，版本反而没了"。
8. **一个版本的多种产物走 `DownloadArtifact`，不许塞进 `url_list_map`**：
   后者是"同一个文件的不同镜像"（故障转移），前者是**两个不同的文件**（exe 安装器 /
   zip 便携包）。混用会让镜像测试以为有多源兜底，而实际下的是两个东西。
   界面上只有一种产物时直接下、不弹菜单；两种以上才弹，菜单文字带体积 ——
   选错一次是重下 1.5 GB。为什么不画两颗主按钮见 `pick_download_artifact` 的注释。
9. **遍历全组件的老断言一律按能力位改判据，不加豁免表**：
   `multi_version == not download_only`、角标存在 ⟺ `multi_version`、
   归档布局审计的豁免只能由能力位决定（**不许**把这些 key 写进 `EXPECTED_WIN_SUBDIR`，那等于谎称实测过归档布局）。

### R13.3 实测矩阵（2026-10-10，`User-Agent: byte-tools`）

| 端点 | 结果 |
|---|---|
| `data.services.jetbrains.com/products/releases?code=IIU&type=release` | 200；**不带 gzip 1 MB / 27–44 秒，带 gzip 700 KB–1.1 MB / 2.0–4.8 秒**（`requests` 默认发 `Accept-Encoding: gzip`，所以产品路径天然吃快的）；`items=` / `platform=` 参数**被忽略**，多码合并请求要 2.7 MB / >90 秒反而更慢 |
| `download.jetbrains.com/{idea,python,cpp,webstorm,go,datagrip}/*.exe` | range → 206，魔数 `MZ`，741–2938 KB/s；单包 **858 MB – 1.74 GB** |
| `update.code.visualstudio.com/api/releases/stable` | 200，稳定版号数组 |
| `update.code.visualstudio.com/<ver>/win32-x64-archive/stable` | 206 + `PK`，约 3.9 MB/s（便携 zip） |
| `servicewechat.com/wxa-dev-logic/download_redirect?type=x64&from=mpwiki` | 200，`Content-Length 190,935,184`，`MZ`；**无可机读版本号**，只有 `Last-Modified` |
| `api.github.com/repos/{t8y2/dbx,kingToolbox/WindTerm}/releases` | 200，都有 x64 便携 zip（DBX 38.6 MB / WindTerm 32.7 MB），另有 `.sha256` / `.sig` 旁证文件与 arm 包 |
| `github.com/.../releases/download/...`（裸地址） | 本机 **http=000 连不上** |
| `gh-proxy.com/https://github.com/...` | 206 + `PK` ✓；**当天实测 116–225 KB/s，而 2026-09-29 同一加速器实测约 9 MB/s** ⇒ 吞吐每天浮动，文档与注释里不写死数字 |
| `mirrors.huaweicloud.com/jetbrains/…` | **200 + 12 KB HTML，假源** |
| `mirrors.nju.edu.cn/jetbrains/…` | 404 |
| JetBrains `downloads.windowsZip`（第二种产物） | 六件逐个实测 206 + `PK`；idea 1,634,879,155 / pycharm 1,319,498,231 / clion 2,378,013,331 / webstorm 1,162,475,563 / goland 1,256,774,457 / datagrip 1,109,836,927 字节 |
| `update.code.visualstudio.com/<ver>/win32-x64-user/stable` | 206 + `MZ`；1.141.0=251,828,312 / 1.140.0=244,372,816 / 1.139.1=232,909,888 字节 |
| `github.com/t8y2/dbx/…/DBX_0.6.38_x64-setup.exe` | 206 + `MZ`，29,228,000 字节 |
| Eclipse `technology/epp/downloads/release/<列车>/R/eclipse-java-…-win32-x86_64.zip` | 清华 / 阿里 / 华为 / 官方**四个源都回同一个字节数**（2026-09=377,592,420、2026-06=368,384,084、2026-03=368,790,631），`PK` ✓；官方 CDN 只有 25 KB/s、清华 2.7–3.9 MB/s |
| `www.apipost.cn/dl.php?client=Win&arch=x64&version=8.2.7` | 302 → `dlcdn.apipost.cn/dl/8.2.7/Apipost_win_x64_8.2.7.exe?auth_key=<时效签名>` → 206 / 93,635,360 / `MZ`，7.43 MB/s；ia32 档 90,103,560。**登记分发器那条**，签名地址会过期。**不带 `version=` 时 dl.php 回 200 + 一小段 HTML** —— 正是"200 ≠ 真源"，靠 `expect_magic=b"MZ"` 挡在落盘前 |
| `download1.dcloud.net.cn/hbuilderx/release.json` | 200 / 928 B，`version` + `files[].code/path`；`win_simple` → `.../download/HBuilderX.<ver>.zip`。**同一份 JSON 在一小时内从 5.24.2026081301（91,325,223 B）变成 5.26.2026091802（93,908,502 B）**，两个都实测 206 + `PK` ⇒ 官方在滚动发版，这正是"手写离线清单必然腐烂"的现场证据，也是给它注册 fetcher 的理由 |
| `download.dcloud.io/hbuilderx/release.json` | 同一份 JSON；文件侧同一字节数、8.09 MB/s ⇒ 两个域名互为源 |
| `cdn.apifox.com/download/latest.yml` | 200 / 469 B，`version: 2.5.19` / `size: 139586536` / **`releaseDate: 2024-04-07`**；exe 206 + `MZ`、字节数与清单一致、7.66 MB/s。**清单里写的是 `http://`，登记前升 https** |
| `dl.google.com/dl/android/studio/install/2026.2.1.8/android-studio-rabbit1-windows.exe` | 206 / 1,511,692,296 / `MZ`，**6.15 MB/s**（1.51 GB 约 4 分钟） |
| `edgedl.me.gvt1.com/android/studio/install/…`（winget 清单原址） | 同一文件同字节数，但实测只有 **72 KB/s** ⇒ 排末位 |
| `api.github.com/repos/microsoft/winget-pkgs/contents/manifests/g/Google/AndroidStudio` | 200，版本目录列表；再进目录取 `*.installer.yaml` 的 `download_url`（`raw.githubusercontent.com` 本机可达），读出 `InstallerUrl`。**文件名带列车代号（rabbit1），按版本号拼必 404** |
| `aka.ms/vs/17/release/vs_Community.exe` | 302 → `download.visualstudio.microsoft.com/download/pr/<GUID>/…/vs_Community.exe`，200 / **4,474,136** / `MZ`。**这是在线引导器不是离线包**，卡片必须写明 |
| `download.navicat.com/download/navicat17_premium_cs_x64.exe` | 206 / 153,253,568 / `MZ`，804 KB/s；`en` 包 152,687,592。**根目录 403 但文件 206** —— 无 UA 时会误判成假源 |
| `www.navicat.com` / `www.netsarang.com` / `cdn.netsarang.net` / `developer.android.com` / `androidstudio.googleblog.com` | 本机 **http=000 连不上**（不是 403）⇒ Xshell / Xftp 至今取不到任何证据；Android Studio 的版本号改从 winget 索引取 |
| `data.services.jetbrains.com/products` | 200，82 个产品**里没有 Fleet**；`?code=FLEET` 回空对象 `{}` ⇒ 独立版已停，无可机读源 |

⇒ JetBrains / VS Code / 微信这批**只有官方直链**（Eclipse 例外，它有清华等三个真镜像），与 R1「镜像优先、官网末位」相反，是实测例外，
（**Eclipse 是例外中的反例**：官方 CDN 本机实测 25 KB/s，而清华 / 阿里 / 华为三个镜像都回
同一个 377,592,420 字节的 `PK` 包、清华 2.7–3.9 MB/s ⇒ 它按 R1 正常排多源，不进豁免表。）
在 `bt_mirror_spec_tests.OFFICIAL_ONLY_EXCEPTION` 里登记；那条用例断的是"大陆源恰好 0 个"而不是跳过，
以后有人挂镜像会红，逼他带实测来改表。**注意该表的口径是"有没有第三方镜像站"**：
dcloud / apipost / apifox 本身就是大陆 CDN（7.4–8.6 MB/s），但不是镜像，`is_mainland()` 按镜像域名认，
所以它们仍记 0 个大陆源。

#### R13.3b 2026-10-12 B6a：「开发工具」第三批 9 个只下载 GUI 的实测矩阵

| 端点 | 实测结论（状态码 + 魔数 + 字节数 + 吞吐） |
|---|---|
| `ghfast.top / gh-proxy.com / ghproxy.net` + `github.com/{dbeaver/dbeaver,HeidiSQL/HeidiSQL,usebruno/bruno,redis/RedisInsight,qishibo/AnotherRedisDesktopManager}` | 三个加速器全部 206 + `MZ`；**gh-proxy.com 最快（12.8–18.1 Mbps）、ghfast.top 4.4–7.4、ghproxy.net 0.2–3.0**。裸 `github.com` 本机 SSLError / 连不上。字节数：DBeaver 113,470,696 / HeidiSQL exe 17,813,608 + zip 29,789,003 / Bruno exe 121,897,928 + msi 133,836,800 / RedisInsight 115,599,376 / ARDM exe 61,935,432 + zip 83,654,756 |
| `dbeaver.io/…` | **只是 302 跳板**，最终 host 就是 `github.com` ⇒ 按 R1 走加速器，不能把 `dbeaver.io` 当"官方直链"登记。资产名 26.x 起是 `dbeaver-ce-<v>-windows-x86_64.exe`（25.3.0 及更早是 `…-x86_64-setup.exe`，跨代两种都验过）；`/releases/latest/<文件名>` 那种类别名 404 |
| `HeidiSQL_12.21.0.7344_Setup.exe` | ⚠ **Setup.exe 里那个 `.7344` build 号从版本号推不出来**，便携包名字又是第三种形态（`HeidiSQL_12.21_64_Portable.zip`）⇒ 文件名只能从 release 接口读，两处都按规律拼就都 404 |
| `redis/RedisInsight` | 仓库**已从 RedisInsight/RedisInsight 迁到 redis/RedisInsight**，且资产名不带版本号（`Redis-Insight-win-installer.exe`）⇒ 版本必须取自 tag，URL 只能拼 tag 目录 |
| `bruno` 与 `ARDM` 的 `latest.yml` | 200 + `version: 4.2.1` / `version: 1.7.4`（Squirrel 的机读清单，`/releases/download/latest/latest.yml` 会自动 302 到当前版）—— 这是这两件唯一"版本无关"的入口 |
| `downloads.mongodb.com/compass/…` | msi 203,259,904 / exe 196,987,944 / zip 226,785,146，全部 206 + 正确魔数。⚠ **这个桶对不存在的对象回 403 而不是 404**（`9.99.99` 与 `latest` 都 403 + 111 B XML），照状态码判"源挂了"会误判；也没有版本无关别名 |
| `mirror.nju.edu.cn/postgresql/pgadmin/pgadmin4/v<v>/windows/pgadmin4-<v>-x64.exe` | 206 + `MZ`，240,588,864 B，**29.1 Mbps**，同路径的官方 `ftp.postgresql.org` 25.9 Mbps ⇒ 南大是这批里少见"镜像比官方还快"的一家。清华 `postgresql/pgadmin/` 404。⚠ **`www.postgresql.org/ftp/...` 是软 404 陷阱**：404 + 4,223 B HTML 并 302 到一个尾部带斜杠的目录式 URL，绝不能登记它 |
| `cdn.mysql.com/Downloads/MySQLGUITools/mysql-workbench-26.7.0-winx64.{msi,zip}` | 206 + 正确魔数，273,879,040 / 333,111,094。⚠ Workbench 已切 **CalVer**：26.x 起文件名**去掉 `-community` 中缀**（8.0.47 及更早仍带，两种都实测过）；路径段必须是 `MySQLGUITools`（写成 `Workbench` 直接 404 + `Not found`）。`dev.mysql.com/get/...` 对非浏览器 UA 一律 403；清华 / 华为 / 阿里都**没有** MySQLGUITools 这棵树（404 或门户壳） |
| `dl.pstmn.io/download/version/<v>/win64` | 206 + `MZ`，212,922,848。**⚠ 不能用 `/download/latest/win64`**：它 200 但**没有 `Content-Length`**，本工具的字节数校验会判"拿不到长度"。版本号从 Squirrel 的 `RELEASES` 增量链读：那条链是**差量清单**，不是"给我最新版"的 oracle —— 从 12.31.7 请求返回 12.32.0，从 12.32.0 请求返回空，所以抓取要能容错地走若干跳（当前实现最多 8 跳）后取最高版本 |

> 这九件的分类登记在 `_DEVTOOLS` 那张表里（`download_only=True`）。它们**没有**任何可用大陆镜像（pgadmin4 的南大除外），
> 所以逐个进了 `bt_mirror_spec_tests.OFFICIAL_HOST` / `OFFICIAL_ONLY_EXCEPTION`；新增域名同时进了
> `bt_download_only_tests` 的"实测过的域名白名单"。**没有实测证据的域名不许进那张白名单**（R13.6）。

### R13.4 点名要过但没进表的（别当成漏加）

| 候选 | 为什么没进 |
|---|---|
| Xshell、Xftp | `netsarang.com` / `cdn.netsarang.net` 本机全部 **http=000**，连一份证据都取不到；按 R1 不许登记未实测的源 |
| JetBrains Ultimate | 同上（主线已含在 `idea` / `pycharm` 里，授权由用户自己解决） |
| Xcode | macOS 独占，且只走 Mac App Store / Apple 开发者账号登录，Windows 侧无可下直链 |
| Fleet | 官方产品目录 82 个产品里没有它，`?code=FLEET` 回 `{}` —— 独立版已停并回 IntelliJ IDEA |
| Lithe | 官方仓库 `1lck/Lithe-IDEA` 经 API 已 404，新 `Lithe-IDEA/Lithe-IDEA` 建于 2026-10-09、0 个 release |

**订正（2026-10-10 第二批）**：本节原先写着「HBuilderX、Apipost、Apifox 下载页全 JS 渲染，
拿不到可实测的官方直链」与「Visual Studio bootstrapper 不划算」，**四条全是错的**：
Apipost 有 `dl.php` 分发器、HBuilderX 有官方 `release.json`、Apifox 有 electron-updater 的
`latest.yml`（只是通道 2024-04 起停更）、VS 有 `aka.ms` 稳定别名。四个都已进表。
错因是**只搜了 `.exe` / `.zip` 字面量，0 命中就收工** —— 判"拿不到"之前必须先把页面里
所有下载锚点整串打出来，再顺着前端模板变量名（`ReleaseCfg`、`zh_downloadURL`）找它绑定的接口；
Electron 系应用一律先探 `<cdn>/download/latest.yml`。这条教训已写进
`bt_download_only_tests.DEFERRED_KEYS` 上方的注释与本节，防止下一个人重蹈。

补进来的前提是先按 R1 实测，然后"分类表一行 + `_DEVTOOLS` 一条 + 必要时注册 fetcher"，
并删掉 `bt_download_only_tests.DEFERRED_KEYS` 里对应那项。

---

## 规则 R14：四条通用不变量（2026-10-10 全面审计 + 2026-10-11 关窗崩溃查出来的）

这四条都不是"设计得不好"，是**会崩、会被劫持、会谎报**的缺陷。每条都有对应用例，
将来谁删了接线，源码守护用例就会红。

### R14.1 关窗前必须等完**所有** QThread，一类都不能漏

`QThread` 在运行时被析构，Windows 上是进程级 abort：`0xC0000409` / 退出码 127 /
`QThread: Destroyed while thread is still running` —— **一行 traceback 都没有**，
用户看到的只是"我关了个窗口，它闪退了"。

`closeEvent` 历史上只等三类：`LaunchWorker`、`card._version_worker`、`_fetch_workers`。
漏掉的有五类，全都是点得动的功能：`_update_dl`（下载新版本）、`_update_worker`（检查更新）、
`card.worker`（安装下载与「开发工具」的只下载）、`card.prereq_worker`（前置组件下载）、
`card._external_worker`（"系统里检测到的版本"探测，会真跑 `java -version`，多秒）。
现场就是：用户点左上角那颗 ↓ 下 49 MB，中途关窗 → 闪退。

还有第六类，是 2026-10-11 那台真机抓到的：**被顶替掉的版本探测线程**。
`card._version_worker` 只代表最新那一条，而 `_start_version_probe` 每次重探都换新 worker，
另有三处 `_version_worker = None` 直接把在跑的线程摘掉引用 —— 旧线程还在跑，closeEvent 却看不见它。
所以卡片上多了 `card._probe_workers`（起过、还没跑完的全部登记），
`_start_version_probe` 顶替前先把仍在跑的旧线程留下、再追自己。

收口在 `MainWindow._drain_background_workers()`：**先全部 cancel，再统一 wait**
（顺序反过来的话第二个 worker 要白等第一个的超时）。`UpdateCheckWorker` 没有 `cancel()`，
用 `getattr` 取，取不到就只等它自己跑完（它有 8 秒硬超时，见 R12.2）。

接线由 `bt_launch_tests.MainWindowAdopt.test_close_event_wires_the_background_drain`
用源码守护钉住 —— 和 `_cancel_launch_workers` 同一套规矩：`closeEvent` 本身测不了
（要调 `super()`），所以测收口函数 + 守护那一行调用。**断言要匹配调用形状**
（`self._drain_background_workers()`），只匹配函数名的话注释里提一句也算绿。

### R14.4 不许对可能被 `deleteLater` 的 worker 裸调方法

worker 连了 `finished → deleteLater`（探测线程、检查更新线程都这么写）之后，
**Python 侧那个引用照旧留着，但 C++ 对象已经被事件循环删了**。这时调任何方法
抛的都是 `RuntimeError: libshiboken: Internal C++ object (…) already deleted`，
**不是返回 False**。所以判定线程状态一律走 `main._qthread_state(worker)`
（`running` / `finished` / `idle` / `dead`）和 `main._qthread_wait(worker, ms)`。

这条不是理论：2026-10-11 用 `tools/bt_close_crash_repro.py` 在 HEAD 代码上稳定复现出两级后果——

| 炸点 | 后果 |
|---|---|
| `closeEvent` 里 `card._version_worker.isRunning()` | 异常把后半段（等 12~18 条在途 `VersionFetchWorker`）整段跳过 → 窗口析构时它们还在跑 → **退出码 -1073740791**，正是用户报的"关窗闪退" |
| `_start_update_check` 里 `worker.isRunning()` | 检查更新跑完后**第二次点版本号直接抛**，用户看到"这颗按钮点一次有效、之后再点没反应" |

`_qthread_state` 认得出 `idle`（错峰定时器排了还没启动）——那一类必须算"忙"，
否则会被 `_start_fetch_versions` 的 cleanup 提前 `deleteLater`，定时器回调再来访问就是已释放对象。

用例：`bt_launch_tests.DeadWorkerDrainGuards`（5 条，含用 `shiboken6.delete()` 造真死引用）、
`bt_update_check_tests.ChipStateMachine.test_second_click_after_a_finished_check_still_checks`。

### R14.2 远端 API 返回的字符串不许直接当路径用

产物名来自公开的 GitHub / Gitee release API，是**外部输入**。
`Path(目录) / 名字` 在名字是绝对路径或含 `..` 时会直接丢掉目录，实测：

| 远端 name | `Path("C:/Users/x/Downloads") / name` |
|---|---|
| `C:\Windows\System32\evil.exe` | `C:\Windows\System32\evil.exe`（目录整个被丢弃） |
| `/etc/passwd` | `C:\etc\passwd` |
| `../../escape.exe` | 逃出目录（解析时才生效，所以看起来"没越界"） |
| `sub/dir/x.zip` | 多深都建（`ensure_dir` 会把它爹们建出来） |

下载完成是 `tmp.replace(dest)`，所以这等于"往任意路径写文件"。
`_safe_download_name()` 只取最后一段、拒空名与 `.`/`..`、去掉 Windows 不允许的 `:*?"<>|`。
组件卡片那条不受影响：它的文件名是本地拼的 `{key}-{版本}{后缀}`。

### R14.3 `QThread.run()` 里任何异常都会变成进程 abort，终态信号只能发一次

`ensure_dir(self.dest.parent)` 原先写在 `run()` 的 `try` **外面**：目标目录建不出来
（同名文件挡路、只读盘、OneDrive 占位、盘满）时 `OSError` 逃出 `run()` → 就是 R14.1 那个 abort，
而且上层收不到 `finished_fail`，界面永远停在"下载中"。

同一个函数还有第二个毛病：取消时 `_try_download` 发一次 `finished_fail("用户取消")`，
`run()` 的循环下一圈又发一次，最后一次的文案还是"所有下载源均不可用" ——
**把用户主动取消说成了网络故障**，而且弹两次。
现在 `_try_download` 只置 `self._cancelled` 标志，终态由 `run()` 统一发一次。

用例：`bt_download_only_tests.WorkerRobustness`（四条：削名、目录建不出来要报错不抛异常、
取消只发一次终态、非法名字回落 fallback）。

---

## 规则 R15：GitHub 匿名额度是硬预算，抓到的清单必须落盘（2026-10-12）

`api.github.com` 未鉴权限额是 **60 次/小时/IP**，而本工具一次启动要替 59 个组件各打一次。
现场：用户日志里 11 个组件集体「官网版本获取失败」，同一时刻实测
`https://api.github.com/rate_limit` 回 `remaining=0/60` —— **一小时内第二次开工具、或者多点几次
「⟳ 刷新版本」，额度必然见底**。这不是源坏了，也不是软件坏了，是预算超了。

四条不变量：

### R15.1 抓成功的清单要落盘，启动那一次不许重复要打

`save_version_entry()` 把每个组件的清单写进 `~/.env-tools/version_cache.json`
（TTL 24 小时，`VERSION_CACHE_TTL_SEC`），`_start_fetch_versions(force=False)` 只给
"没缓存或已过期"的组件派线程，命中的直接 `card.set_versions()` 回填。
**点「⟳ 刷新版本」= `force=True`，绕过缓存全量重抓** —— 用户主动要最新，绝不能拿旧缓存糊他。

`version_cache_path()` 必须是**函数**而不是 import 期常量：常量会把缓存钉在真实用户目录上，
测试挪 `CONFIG_DIR` 就挪不动它。读缓存要容坏：文件被手改过 / 只写了一半时按"没有缓存"处理，
不许让启动抛异常。

### R15.2 `clicked` 会把 `checked=False` 当第一个实参传进来

按钮信号的第一个实参是**可选参数**，裸 `connect(self._start_fetch_versions)` 之后
那个位置就是新增的 `force` —— 于是"点刷新"变成 `force=False`，**按钮永远刷不动而且不报错**。
现在写成 `lambda _checked=False: self._start_fetch_versions(force=True)`。
**给已有槽函数加参数时，必须先查它被哪些信号直连过**；这条由
`bt_refresh_versions_tests.VersionListCache.test_button_wiring_does_not_swallow_checked_argument`
用源码守护钉住（断言里带调用形状，光匹配函数名拦不住）。

### R15.3 命中限流要立旗，整批快速收尾，别再一个个退避重试

原来 403 + `X-RateLimit-Remaining: 0` 走的是"退避 5s/10s 重试三次"，实测**每个组件白等 31 秒**，
11 个就是五分多钟的转圈，而且每次重试都在继续烧已经见底的额度。
现在 `_gh_mark_limited()` 记下解锁时刻（`_GH_LIMITED_UNTIL`，`X-RateLimit-Reset` 只信一小时内的，
缺头或被加速器改写时兜底 `GH_LIMIT_MIN_SEC = 60`），旗子没倒之前所有调用直接抛
`GH_LIMITED_TEXT`，一次网络都不发。

实现细节坑：`raise RuntimeError(...)` 写在 `try` 里会被下面的 `except Exception` 接去重试 ——
必须加一条 `except RuntimeError: raise` 让限流这个**终局判断**穿透出去。

### R15.4 失败原因要进日志面板，不能只 print 到 stdout

`VersionFetchWorker` 原来把原因 `print` 到 stdout —— **打包成 exe 后没有控制台，那句话永远不会
出现在界面上**，用户只剩一句误导性的「官网版本获取失败」。现在原因存在 `worker.error_text`，
`_on_versions_fetched` 按它分句：限流说"GitHub 匿名额度已用完，一小时后再刷新"，
其余把真实原因（含超时/404/DNS）带进同一行日志。

用例：`bt_refresh_versions_tests`（`VersionListCache` 6 条 + `WorkerFailureReason` 2 条，
外加原有 4 条刷新流程）。`RefreshVersionsFlow` 现在也 redirect 了 `CONFIG_DIR` 并在
`setUp` 里清缓存 —— 抓成功会写盘之后，不隔离的用例会写用户的
`~/.env-tools/version_cache.json`（R12 的教训再来一遍）。

### R15.5 并发闸门等不到槽位必须继续等，每个 worker 恰好发一次 `done`

右上角「⟳ 刷新版本」的收尾只靠 `_fetch_pending` 归零，而它只在
`_on_versions_fetched()` 里减一。所以**每一个派发出去的 `VersionFetchWorker` 都欠一次 `done`**。

原实现是 `if not self._gate.acquire(timeout=0.25): return` —— 等不到槽位就**静默退出**，
连 `done` 都不发。2026-10-28 真机复现：首启 70 多个抓取任务、并发上限 6，
只有 14 个报了结果，其余全部被丢掉；`_fetch_pending` 停在 N-6，`_fetch_finished()`
永不执行，按钮永远灰着、文字永远是「⟳ 抓取中…」，看起来就是卡死（进程和界面其实都活着）。

现在的写法是 `while not acquire(timeout=FETCH_ABORT_POLL_SEC)`：等不到就继续等，
只有 `FETCH_ABORT`（关窗）才退出。轮询只为让关窗能立刻打断，**不是放弃的理由**。
护栏：`bt_refresh_versions_tests.FetchGateContract.test_worker_queued_at_the_gate_still_reports_done`
（把闸门压到 1 个槽位、让第一个 worker 占住，断言排队的那个也必须发 `done`）。

同一族的坑：任何"收尾计数器"都要保证**派发数 == 完成数**。凡是提前 `return` 的分支，
要么先补一次通知，要么证明它走不到收尾逻辑。

---

## 规则 R16：像素裁字只能在真实渲染下判，offscreen 的度量会把你带偏

顶栏是一行 `QPushButton`，`setMinimumSize` 是它的唯一预算。给 chip 加状态文字
（`⟳ v1.2.0 检查中` / `v1.2.0 最新` / `↓ v1.2.1 待更新` / `? v1.2.0 未查到`）之前，
必须先量这一行还放不放得下 —— 但**量的人是谁很关键**：

| 环境 | `v1.2.0` 的 `minimumSizeHint` | `↓ v1.10.0 待更新` | 整行总需（含标题、五个按钮、三个窗口控制） |
|---|---|---|---|
| `QT_QPA_PLATFORM=offscreen` | 92 px | 174 px | 846 px（看起来 1000 一档已经不够） |
| 真实平台（不设 offscreen） | **54 px** | **110 px** | **697 px**（1000 一档余量充足） |

offscreen 没有系统中文字体的回退链，Qt 换了一个宽得多的替代字体，度量整体大约 **1.6 倍**。
2026-10-12 就是拿这套数字下结论，连着做了三件真机上根本不需要的事：把窗口最小宽从 1000
抬到 1060、把「🧹 清理残留 PATH」「🖥 开验证终端」两个文案削短、并据此认定
「清理残留 PATH 今天就在裁字」。**全部已回退**（真字体下它从来没裁过）。

三条落地规矩：

1. **量宽度用 `tools/bt_titlebar_budget.py`**（它显式 `pop("QT_QPA_PLATFORM")`，走真实平台），
   别在 offscreen 里量完就下结论。
2. **单元测试只断言与字体度量无关的不变量**：控件的文字内容、`sizePolicy` 是不是
   `QSizePolicy.Fixed`、谁在谁左边。裁字这类像素断言在 offscreen 下必然失真，
   `bt_multiversion_tests.test_title_bar_buttons_are_not_clipped_at_minimum_width`
   保留 `fontMetrics` 判据也是这个原因（它比 minimumSizeHint 更接近"文字本体"，
   且历史上真裁过字时它确实报红过）。
3. **chip 进定宽名单**（`btn_version` 与其余顶栏按钮一起 `QSizePolicy.Fixed`）：
   它的文字按状态变长，不定宽的话宽度一紧张布局先压它，状态字等于没写。这条与度量环境无关，
   是纯策略约束，所以可以放心写进用例。

另外两个通用细节：换文字或改窗口尺寸后要转一轮 `processEvents()` 再量几何，
不等这一轮量到的是旧尺寸（假绿假红都从这来）；`grab()` 出来的图在 offscreen 下也是替代字体，
**看版式可以，看文字有没有被裁不行**。

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

---

## 规则 R17：组件详情弹窗（2026-10-12）

### R17.1 规则描述

每张卡片名称右侧有一枚 `ℹ` 图标按钮，点开弹窗，回答用户两个问题：**这个组件是干嘛的、怎么用**。
弹窗内容为固定四段式：

1. **它是什么** —— 来自 `COMPONENT_SUMMARY`（一句话定位 + 解决什么问题）
2. **怎么用** —— 来自 `COMPONENT_USAGE`（可直接执行的命令 / 点击路径）
3. **本工具会替你做什么** —— 由能力位现场派生，**不新写文案**（避免第二份真相）
4. **平台说明** —— 登记了 `unsupported_platform_hint` 才显示

另有"官方地址"一行：从已登记 URL 取**末位官网**（不是首位镜像），用户可据此去官网核对。

### R17.2 硬约束

1. **点击弹窗外自动关闭**：`ComponentDetailDialog` 挂应用级事件过滤器，鼠标按下位置在
   `frameGeometry` 之外即 `accept()`。禁止改成 `setModal(True)` 死锁用户 —— 详情是
   "看一眼就走"的东西，不是向导。
2. **详情正文不进 data_note / 版本清单**：数据去处归卸载确认框，可选版本归下拉框。
   详情重复它们就是噪音（用户已能在那两处看到）。
3. **两张文案表必须与组件清单 key 严格一致**：`COMPONENT_SUMMARY` / `COMPONENT_USAGE`
   漏一条 → `build_components()` 末尾赋值 KeyError、主窗口构造不出来（与 category 同一套
   「漏登记即 KeyError」的做法）；护栏套件 `bt_component_detail_tests.py` 逐一钉住。
4. **端口显示必须是展开后的真实端口**：`port_offsets` 是「主口 + 偏移」不是绝对端口。
   详情里把偏移当端口拼，etcd 会显示成「端口 2379、1」（真机踩过，被护栏钉死）。
5. **只下载类不许承诺解压 / 写环境变量**：R13 的行为边界在详情里同样生效，
   `bt_component_detail_tests.DownloadOnlyWording` 逐条核对。
6. **文案长度有上限**（SUMMARY ≤110 / USAGE ≤160）："简洁且专业"必须能被机器判。

### R17.3 新增组件 checklist

- `build_components()` 加 `Component(...)` 的同时，必须在 `COMPONENT_SUMMARY` 与
  `COMPONENT_USAGE` 各加一条（漏了直接 KeyError）。
- 「它是什么」写定位 + 场景；「怎么用」给命令或点击路径；**拿不准的细节（版本号、
  端口、厂商行为）不编造** —— 详情里有"官方地址"行可以去官网核对。

---

## 规则 R18：冷启动预算——建卡不许逐个扫 PATH（2026-10-13）

### R18.1 背景与数字

`build_components()` 87 张卡建一次，`cProfile` 实测烧掉 **1.2 秒**在
`shutil.which`（105 次调用 × 整条 PATH × PATHEXT 逐个 `os.path.exists`，
约 4.2 万次系统调用）。这条成本随组件数**线性**恶化，2026-09 接 26 个组件时
没人察觉（30 毫秒），接满 87 个就变成了"双击图标后窗口 1 秒才出来"。

修复后的实测：建窗 1.12s → **0.64s**，首帧 1.4s → **0.7s**。

### R18.2 做法（`_path_index` / `_which_fast`）

1. **一次批扫**：建卡前对 PATH 的每个目录 `os.scandir` 一遍，建
   `(大写候选名 → 最左目录序)` 索引。目录条目自带类型信息，Windows 下判
   文件不再逐个 stat。
2. **语义逐条对齐 `shutil.which`**：候选名与顺序同 CPython 3.12（名字自带
   PATHEXT 扩展时先原名再补全，否则只查补全）；最左目录优先；返回值拼**候选名**
   而不是磁盘名（`which("python")` 回 `…python.EXE`，大小写都是接口的一部分，
   测试断言与路径比较都锚在这上面）。
3. **未命中就是未命中**：索引扫过全表后判负**不许**回退真实 `shutil.which` ——
   那等于把 4 万次 exists 重扫第二遍，而"没装"恰是建卡时的多数情况
   （首版就栽在这里：改了 `_which_fast` 建窗时间纹丝不动）。唯一要补的是
   Windows 的当前目录特例（`NeedCurrentDirectoryForExePath`），只对当前目录
   做那几次检查。
4. **失效策略**：索引以 `os.environ["PATH"]` 原文为键。本工具运行期会改写
   进程内 PATH（安装/切换生效），PATH 一变整表重扫——读到过期条目比慢更糟。
5. **测试桩兼容**：`_which_fast` 第一行比对 `shutil.which` 的函数身份，被测试
   换掉实现时直接走桩实现（`bt_launch_tests` 有四处打桩点，桩语义逐字保持）。
   带目录成分的名字（`a/b`、`.\x`）不属于纯 PATH 查找，同样直接交真实实现。

### R18.3 showEvent 的列数守卫（同轮修复）

构造期 `relayout_cards` 跑在窗口 show 之前，viewport 宽度未就绪时
`grid_columns_for` 算出的列数**已经记进 `_last_columns`**；show 期 showEvent
强制重排一次、resizeEvent 再补一次，等于把同一个行结构拆建三遍
（87 次 `setParent` ≈ 0.4s/遍）。现在：构造期记录真实列数，showEvent 仅在
**列数与构造期不同**时才重排（真机 2026-10-08 踩中的"构造期 1 列、show 后 3 列"
照旧被纠正），相同就跳过——拆建结果必然一模一样，白烧。
`bt_grid_layout_tests` 36 条全绿钉住行结构契约。

### R18.4 红线

- **新增建卡路径上的逐组件磁盘/系统调用前先数一遍 N**：单件 10ms 的探测在
  N=87 时就是 0.9s。要扫就批量化（一次 scandir 建索引，查表 O(1)）。
- 冷启动回归门槛：`python -X importtime` 之外，建窗（`MainWindow()` 构造）
  超过 **1.5s** 必须先 profile 再合并，不许"再等等优化"。

---

## 规则 R19：官网地址必须人工登记，不许从下载 URL 推导（2026-10-14）

### R19.1 背景：推导出来的东西根本不是官网

详情页一直有一行"官方地址 / 官方下载"，原先由 `comp_download_host(comp)` 从
组件的**下载 URL** 里切域名。2026-10-14 实测 88 个组件的推导结果：

| 推导出的域名类型 | 数量 | 例子 |
|---|---|---|
| `github.com`（仓库页，不是官网） | 39 | git / redis / minio / caddy / fd |
| CDN / 下载服务器 | 31 | `api.adoptium.net`、`artifacts.elastic.co`、`aka.ms`、`edgedl.me.gvt1.com`、`fastdl.mongodb.org` |
| Apache 归档站 | 10 | `archive.apache.org`（该是 `kafka.apache.org`） |
| 压根推不出来 | 1 | docker |
| **确实是官网** | **7** | nginx.org / python.org / nodejs.org / go.dev / gradle.org / sqlite.org / apipost.cn |

也就是说那行字**有 81/88 是错的**。写"官方地址"却给用户一个下载服务器，
比不写更糟。

### R19.2 做法

- `COMPONENT_OFFICIAL_URLS`（`main.py`）单点登记 88 条，每条带核实依据注释
  （`CN` = 大陆入口、`INT` = 国际官网、`403` = 站点有反爬但域名有效）。
- `build_components()` 末尾统一赋值 `comp.official_url`，**漏登记直接 KeyError**。
- 取值口径（用户 2026-10-14 拍板，乙档）：
  1. 有中国大陆官网入口的优先用 —— 含两种形态：**独立 CN 域名**
     （`golang.google.cn` / `navicat.com.cn` / `apifox.cn` / `dcloud.io` /
     `developers.weixin.qq.com`）与**同域名中文路径**
     （`nodejs.org/zh-cn`、`jetbrains.com/zh-cn`、`visualstudio.microsoft.com/zh-hans`、
     `code.visualstudio.com/docs/?locale=zh-cn`、`learn.microsoft.com/zh-cn/powershell/`、
     `kubernetes.io/zh-cn/…`）；
  2. 没有中文入口的，用该项目**真实国际官网首页**。
- 链接文字与 href **必须同源**：文字里的域名用 `_url_netloc(href)` 现切，
  不另写一份字符串。早先"文字显示下载域名、跳转却是官网"的写法已废弃。

### R19.3 红线

- **不许再写"从 URL 推导官网"的逻辑**。`comp_download_host()` 已连同它的两条
  用例一起删除。
- 登记表里出现 CDN / 下载服务器域名即为错，`tests/bt_component_detail_tests.py`
  的 `test_download_hosts_are_not_registered_as_official` 会拦。
- 这 88 条是人工核实的事实，**项目改名换域名后会悄悄过期**。接新组件时必须在
  `COMPONENT_OFFICIAL_URLS` 补一条（漏登记即测试变红），不是可选项。

---

## 规则 R20：「Agent客户端」是第五个只下载的 Tab（2026-10-15）

### R20.1 规则描述

用户 2026-10-15 要求：**在 Tab 末尾新增一个「Agent客户端」**，把 AI 编程 / 办公 Agent 的
桌面端与 CLI 发行包做成组件，"图标、详情、下载链接一律按现有组件的流程来"。

- **位置**：必须是**最后一个** Tab（用户原话"table 放在最后"）。插到中间即为违约。
- **形态**：与「开发工具」**同类** —— `download_only=True`，卡片只有「版本下拉 + 下载」，
  不解压、不配环境变量、不扫盘、不代跑安装器（R13 的八个短路点原样适用）。
- **成员真源**：`main.py` 的 `_AGENT_CLIENTS` 那张表（表驱动，与 `_DEVTOOLS` 同行格式、
  共用 `_download_only_components()` 生成器）。分类由
  `COMPONENT_CATEGORY_OF.update({s[0]: CAT_AGENT for s in _AGENT_CLIENTS})` 自动喂进去。

### R20.2 三条硬约束

1. **表驱动，不许手写 Component(...)**：两张只下载表共用一个 builder。抄十几遍必然漏一处，
   而漏抄的后果是建卡时去扫盘、或者往注册表写环境变量。
   接一个新客户端 = 只改 `_AGENT_CLIENTS` 一行 + 补三张登记表
   （`COMPONENT_SUMMARY` / `COMPONENT_USAGE` / `COMPONENT_OFFICIAL_URLS`，见 R19）——
   **漏登记直接 KeyError 或测试变红**，这是刻意的。
2. **版本位：拿不到版本列表就退而求其次，但不许编**。这批产品多数**只发滚动 latest**，
   官方没有"列历史版本"的接口（用户 2026-10-15 明确"只要能下载就好"）。取值顺序：
   ① 官方给的版本号（如 Cursor 的 golden 链按 `主.次` 发版）；
   ② 直链路径里的版本号（如 ZCode 的 `/releases/3.15.3/`）；
   ③ **实在没有就取服务端文件的 `Last-Modified` 年月**（先例：`wechat-devtools` 的 `2026.09`），
   并在 `data_note` 里写明"这不是软件版本号"。
3. **几乎没有大陆镜像 → 必须走 R1.5 例外登记**。这批全是各家官网 / 厂商自有 CDN 直发。
   `bt_mirror_spec_tests.WindowsDefaultMustHaveTwoMainlandSources.OFFICIAL_ONLY_EXCEPTION`
   里必须点名（否则"≥2 个大陆源"那条会红）；**GitHub 产物的**（`claude-code` / `codex-cli`）
   不在这张表里 —— `_gh_accelerated()` 会给它们挂 3 个加速器，而**加速器算大陆源**，
   它们走常规检查、登记在 `test_no_component_escapes_this_table` 的 `github_assets`。
   ⚠ 注意 `is_mainland()` 认的是**镜像站**标记，不是"域名在国内"：
   `cdn-zcode.z.ai` / `download.qoder.com` 是厂商自己的 CDN，仍算 0 源。

### R20.3 实测口径与首批登记

URL 与字节数**一律带 `byte-tools/1.2.1` UA 实测**（R1 的口径）。首批 5 个（用
`Content-Range` 拿总体积，不整包下载）：

| key | 显示名 | 版本位 | 实测字节 | 来源 |
|---|---|---|---|---|
| `cursor` | Cursor | 3.24 | 215,228,800 | `api2.cursor.sh/updates/download/golden/win32-x64-user/cursor/<主.次>` |
| `zcode` | ZCode | 3.15.3 | 181,367,144 | `cdn-zcode.z.ai/zcode/electron/releases/3.15.3/windows-x64/…` |
| `claude-code` | Claude Code | 2.1.300 | 121,043,936 | GitHub Releases（加速器优先） |
| `codex-cli` | Codex CLI | 0.162.1 | 333,479,728 | GitHub Releases（另发 zip，164,672,399） |
| `qoderwork-cn` | QoderWork CN | 2026.09 | 253,672,408 | `download.qoder.com/…/latest/…`（滚动，版本位取 Last-Modified 年月） |

**CLI ≠ GUI，`data_note` 要写清**：Claude Code / Codex CLI 是终端工具，下载解压后要自己
配 PATH 并登录授权 —— 卡片说明里必须点明"不是双击即用的窗口程序"，否则用户会以为是装了个失败的应用。

### R20.4 护栏

- `tests/bt_download_only_tests.py`：`TabStructure`（顺序 + 成员 + **最后一个必须是它**）、
  `CapabilityFlag`（`DOWNLOAD_ONLY_KEYS` 是「开发工具」∪「Agent客户端」的**并集**）、
  `test_visible_component_count_is_127`（全仓库唯一写死可见组件数的地方）。
- `tests/bt_component_category_tests.py`：`EXPECTED_MEMBERSHIP[CAT_AGENT]` 与
  `test_tab_order_is_exactly_launch_server_env_tool_agent`。
- `tests/bt_mirror_spec_tests.py`：R20.2 第 3 条的两张名单。
- `tests/bt_icon_assets_tests.py`：接新组件必须同时补图标（缺图标即红）。

### R20.5 第二批与第三批（2026-10-15 同一天扩到 40 个）

用户当天补了一句口径：「**把能做的都做了、全都接进来；拿不到下载方式的就做一个
『官网下载』按钮**」。于是这一 Tab 从 5 个扩到 **40 个**（34 有直链 + 6 只有官网入口），
并为此新增规则 **R21**（「官网下载」那一档）。

**这 40 个是怎么来的**：分三批调研（国产大厂助手 / 中文创业公司 / 国际编程 IDE），
每条 URL 都用 `byte-tools/1.2.1` 实测过 —— 不只是 `curl -I` 看 200，还要
**`Range: bytes=0-3` 读出前四字节确认是 `MZ` 或 `PK`**（镜像测试只看状态码，
挡不住"200 + 一张错误页"）。几个值得记住的坑：

| 现象 | 真相 | 处理 |
|---|---|---|
| Trae / CodeBuddy / WorkBuddy 的下载页 `<a>` 里没有 exe | 地址由 JS 运行时拼装 | 找它们的**版本接口**（`api.trae.cn/icube/…/version/<产品>/latest`、`www.codebuddy.cn/v2/update?platform=…`）拿到真 URL |
| 豆包版本接口里有**两个**版本字段 | `data.version`=1.49.10（2025-03 的老包）而 `data.newest_version`=2.32.4 | 取 `newest_version`，并在 `data_note` 里写明另一个字段是老的 |
| ChatGLM 的下载页没链接 | 配置接口 `operation-api/config/operation_data?tag=clientConfig` 给 `winUrl` | 从配置接口取 |
| 阶跃 AI 的 307 落点带签名 | `X-Tos-Expires=86400`，**一天后失效** | 登记**端点**而不是落点（`chat.stepfun.com/api/desktopversion/windows/latest`），下载侧会跟 307 |
| Kimi / DeepSeek Harness / 纳米 AI 的直链不带版本号 | 官方只发滚动 latest | 按 R20.2 第 3 条取服务端 `Last-Modified` 年月，`data_note` 写明"不是软件版本号" |
| Claude 桌面的旧 GCS 直链还能 200 | 那个桶的 `RELEASES` 末条是 **0.14.10 / 2025-10-29** —— 早就冻结了 | **不登记**（拿它当最新版是错的），改走 R21 官网入口 |
| Windsurf 的直链带发版 hash | `…/stable/<hash>/DevinUserSetup-x64-<v>.exe`，新版一发旧目录就没了 | 同上，走 R21 |
| Antigravity / Gemini 的官网 | DNS 能解析、TCP 连不上（大陆不可达） | 登记官网入口，`data_note` 写明"取决于你的网络环境" |
| 讯飞星火的官方图标只有 32×32 | `spark-icon.ico` / `favicon.ico` 最大都到 32；Simple Icons 未收录讯飞 | 图太小放大必糊 → 按既有做法用**名称文字图兜底**，并登记在 `IconCoverage.NAME_TEXT_FALLBACK`（附穷举过程） |
| 通义灵码的官方源在 `…aliyuncs.com` | `is_mainland()` 的 `"aliyun"` 是子串匹配，把它判成"1 个大陆源" | 结果是**对的**（确实是阿里云内地 OSS），登记进 `SINGLE_SOURCE_EXCEPTION`，末位断言另见模块级 `OFFICIAL_IS_MAINLAND_MARKED` |

**新组件必须同时补的四处**（少一处就有套件变红）：`_AGENT_CLIENTS` 一行、
三张登记表（`COMPONENT_SUMMARY` / `COMPONENT_USAGE` / `COMPONENT_OFFICIAL_URLS`）、
一个图标、以及 `EXPECTED_MEMBERSHIP[CAT_AGENT]` 与
`test_visible_component_count_is_127` 这两个常量。

**2026-10-15 又补了一个 `opencode`**（用户点名要的，当时 40 个里没有它）：21 万 star 的
开源编程 Agent，**同一次 release 同时发桌面端安装器与终端版便携包**，所以它是本项目第一个
"一行两个产物都登记"的 Agent 组件 —— 主产物写桌面端 exe，终端版 zip 放进第 4 项，
卡片上就是「下载 ▾」菜单（同 `codex-cli` 的写法）。版本位取 release tag 的数字
（`v1.19.0` → `1.19.0`），它是 GitHub 产物所以**不进** `OFFICIAL_ONLY_EXCEPTION`、
而是登记进 `bt_mirror_spec_tests.test_no_component_escapes_this_table` 的 `github_assets`。
找仓库时的坑：`opencode-ai/opencode` 已 archived（那是 Go 老版）、
`sst/opencode` 也已 301 跳到 `anomalyco/opencode` —— 别照着"opencode 是 SST 的"去登记旧仓库。
图标取自 Simple Icons 的 `opencode` 条目（该条目 `source` 指的就是
`anomalyco/opencode` 仓库里的 `packages/identity/mark.svg`，不是旧版的标）。

### R20.6 第四批：候选清单里用户点名的 11 个（2026-10-15）

用户看到"还有哪些热门的没接进来"的候选清单后，勾了 7 个我已实测过的 + OpenClaw / Hermes
+ 两个只能走「官网下载」的。**同一天这一 Tab 从 41 到 52**（44 有直链 + 8 只有官网入口）。

| key | 显示名 | 版本位 | 实测字节 | 来源 |
|---|---|---|---|---|
| `openhands` | OpenHands | 1.27.1 | 140,354,744 | GitHub Releases（`Agent-Canvas-Setup-*.exe`） |
| `cherry-studio` | Cherry Studio | 2.1.6 | 396,037,216 / 便携 395,662,608 | GitHub Releases |
| `goose` | Goose | 1.54.0 | 247,217,050 / CLI 77,666,256 | GitHub Releases（桌面 + CLI 同发） |
| `qwen-code` | Qwen Code | 0.25.1 | 52,505,536 / CLI 72,012,450 | GitHub Releases（tag 是 `desktop-v0.25.1`） |
| `crush` | Crush | 0.98.1 | 27,319,516 | GitHub Releases |
| `kiro` | Kiro | 1.3.0 | 210,208,904 | `prod.download.desktop.kiro.dev`（厂商 CDN、带签名） |
| `jan` | Jan | 0.8.6 | 556,441,144 | GitHub Releases |
| `openclaw` | OpenClaw | 2026.10 | 128,746,840 | GitHub `releases/latest/download/`（滚动，无版本号） |
| `hermes` | Hermes Agent | 2026.08 | 7,946,048 | `hermes-assets.nousresearch.com`（滚动，无版本号） |
| `gemini-cli` | Gemini CLI | —（空版本表） | — | **无 Windows 安装包**，只有 npm → 走 R21「官网下载」 |
| `aider` | Aider | —（空版本表） | — | **无安装包**，只有 pip/pipx → 走 R21「官网下载」 |

**这一批踩到/确认的几件事**（都影响后面接组件）：

1. **`ARTIFACT_LABELS` 多了一组 `cli` / `portable`**。原因是 Goose 与 Qwen Code 都
   "桌面端 + 终端版"同发，而两个若都标 `zip`，「下载 ▾」里会出现**两条一模一样的文案**。
   加标签键是安全的：全项目取标签都走 `ARTIFACT_LABELS.get(fmt, fmt)`。
2. **`bt_download_only_tests` 有一份"产物域名白名单"**（`test_every_artifact_url_is_a_measured_host`）——
   每个**新域名**都要在那里点名，包括「下载 ▾」里备选产物那条。这一批只多了两个非 GitHub 域名
   （kiro / hermes）；其余 7 个走 GitHub，加速器域名早已在白名单里。
3. **否定结论要穷举**：`gemini-cli` 的 release 资产实测只有 `gemini-cli-bundle.zip` +
   两个 darwin 包（10.7 万 star 的项目**不发 Windows 包**）；`aider` 官方装法只有 pip/pipx。
   这两条都不是"我没找到"，是把 `releases/expanded_assets/<tag>` 列完确认的。
4. **Hermes 的产物可疑，已在 `data_note` 里写明**：官方页面那个 Windows 按钮指向的安装器
   实测只有 **7.9 MB**、服务端 `Last-Modified` 停在 2026-08。多半是"联网拉取组件的小体积安装器"，
   但没验证过，所以文案里**不替它下结论**，只写实测数字并提示"装之前请自行确认"。
   它的图标是 Hermes 桌面页自己声明的 `<link rel="icon" sizes="48x48">`（
   `/marketing-static/assets/hermes-agent/icon.png`），是**产品自己的标**；不是
   nousresearch.com 首页那个 180×180 的插图版（那张在 32px 槽里会糊）。
   ⚠ Simple Icons 里那个 `hermes` **不是它** —— 那是爱马仕，别取错。
5. **Kiro 与官网逐字对齐**：`kiro.dev/downloads/` 页面上的 Windows 链接就是本工具登记的那条
   （含 `1.3.0` 版本目录），所以版本位不是猜的。

### R20.7 第五批：一次"各 Tab 还缺什么"的专项调研（2026-10-15）

用户问"各个 Tab 还有哪些热门组件没接入"，于是按 Tab 分头调研（服务端/运维、开发环境、
开发工具、Agent 客户端各一个子 agent），**每条直链都由我本人再用 `byte-tools/1.2.1` UA
复测一遍**（206 + 前四字节 `MZ`/`PK`/OLE + `Content-Range` 取字节）才写进表 ——
子 agent 的结论只当线索，不当数据。这一批落地 **22 个**（Agent 12 + 开发工具 10），
两个 Tab 的计数同步为 64 / 36。

**Agent 客户端（+12，全部有实测直链）**

| key | 显示名 | 版本位 | 实测字节 | 来源 |
|---|---|---|---|---|
| `ollama` | Ollama | 2026.10 | 1,581,967,176 | `ollama.com/download/OllamaSetup.exe`（滚动，无版本号） |
| `lm-studio` | LM Studio | 2026.10 | 618,785,040 | `lmstudio.ai/download/latest/win32/x64`（302 到版本化安装器） |
| `gpt4all` | GPT4All | 3.10.0 | 744,456,856 | GitHub Releases |
| `anything-llm` | AnythingLLM | 1.18.0 | 407,381,240 | GitHub Releases（资产名不带版本号） |
| `lobehub` | LobeHub | 2.2.19 | 151,357,692 | GitHub Releases（仓库已改名 `lobehub/lobehub`） |
| `copilot-cli` | GitHub Copilot CLI | 1.0.98 | 95,662,080 | GitHub Releases（主推 msi） |
| `ima` | ima（腾讯） | 2.3.0_3717 | 205,057,816 | `ima-app.image.myqcloud.com`（按版本目录） |
| `kilo-code` | Kilo Code | 2026.10 | 410,662,216 | `autoupdate.desktop.anaconda.com`（滚动 latest） |
| `wave-terminal` | Wave Terminal | 0.14.5 | 163,826,544 | GitHub Releases |
| `msty` | Msty Studio | 2026.10 | 226,457,032 | `next-assets.msty.studio`（滚动 latest） |
| `mistral-vibe` | Mistral Vibe | 2.26.1 | 61,496,201 | GitHub Releases（CLI zip） |
| `kimi-work` | Kimi Work | 2026.10 | 438,668,088 | `appsupport.kimi.ai`（滚动端点，302 到版本化文件） |

**开发工具（+10）**：Notepad++ 8.9.8.1 / Wireshark 4.6.9 / GitKraken 2026.10（稳定别名）/
SourceTree 3.4.20 / Insomnia 13.3.1 / Beekeeper Studio 6.1.6 / Obsidian 1.14.4 /
Zettlr 4.8.0 / Yaak 2026.9.0 / Vim (gVim) 9.2.1192。

**这一批抓到的坑（下次直接照抄）**

1. **`/releases/latest/download/<带版本号的资产名>` 是错的写法**。调研报告里有几条这么给
   （Notepad++ / VSCodium / gVim），而 `latest` 会随时间指向新 tag，资产名里的版本号却不跟着变 ——
   登记进去就是个定时炸弹。一律换成**带具体 tag 的** `/releases/download/<tag>/<资产>`，
   而且 tag 与版本号**不同形**的要注意：Insomnia 是 `core%4013.3.1`（`@` 要转义成 `%40`）、
   Ollama 是 `v0.40.5`、Copilot CLI 是 `v1.0.98`。
2. **`ARTIFACT_LABELS` 又加了一档 `msi`**（Copilot CLI 官方主推 msi）。
3. **图标别串品牌**：Simple Icons 的 `hermes` 是爱马仕、`mistral` 不存在（要 `mistralai`）；
   同家的两个组件共用一张标时必须**逐字节相同**并进 `ALLOWED_SHARED`（本批是 `kimi`/`kimi-work`，
   我第一版从 CDN 现取导致与仓库里那份不一致，`test_the_allowed_shared_pairs_still_exist`
   当场报"不再共用"—— 正确做法是 `cp` 仓库里已有那份）。
4. **msty 没有 PNG/SVG 的站点图标**（`/favicon.ico` 只有 16/32px，短边 <48 被护栏拒），
   用它 `/brands/studio.svg`（官方 Studio 品牌标）兜住。

**这一批我判定"不能接"的（附原因，供以后复核）**

| 组件 | 原因 |
|---|---|
| `warp` | 直链存在（`releases.warp.dev/stable/v<日期>.stable_00/WarpSetup.exe`，206），但**我 4 次都取不到前四字节** —— 验不出就登记不了（只有版本化目录，没有稳定入口） |
| `httpie-desktop` | 调研给的 tag `2025.2.0` 实测 **404**；该仓库 release 实际只到 `v2023.3.x`，资产名也对不上 |
| `chatbox` | GitHub Release **只有源码**，官网直链没挖到 |
| `void` | 项目已声明弃坑（GitHub deprecated，release 无资产） |
| `iflow-cli` / `roo-code` | 官方已停运 / 公告将停运（roo 迁 Kilo） |
| 只上微软商店的一批（`quark` / `perplexity` / `xiaoyi` / `lingguang` / `devtoys`） | 官方只发 msix / 商店分发，没有可直接下载的独立 exe |

**当时还剩下的那批（现已由 R20.8 接掉其中 19 个）**：本批只落了"只下载"类的两个 Tab，
「开发环境 / 服务端组件」的候选留到了下一排 —— 它们要额外做两件事：① 写进 `_CLI_TOOLS`
（GitHub 托管的能自动配抓取器，厂商 CDN 的**要另写版本抓取器**）；② 用
`tools/bt_archive_layout_audit.py` 逐个验证归档布局（`path_subdir` 写错会让"装好了但 PATH 里没东西"）。

### R20.8 第六批：「开发环境 / 服务端组件」里"解压即用"的 19 个（2026-10-15）

用户问"一键启停、服务端组件、开发环境，没有需要新增的组件吗" —— 于是把 R20.7 里
留给下一排的那批做了。**只收"解压即用"形态**（单二进制 exe 或 zip），
`installer_mode` 与 tar.gz / 7z 的都没收（前者要静默安装参数，后者本工具不解）。

| key | 显示名 | Tab | 版本位 | 实测字节 | 来源 |
|---|---|---|---|---|---|
| `terraform` | Terraform | 服务端 | 1.13.4 | 30,962,506 | `releases.hashicorp.com`（**唯一非 GitHub 的那个**） |
| `opentofu` | OpenTofu | 服务端 | 1.12.8 | 35,485,271 | GitHub Releases |
| `argocd` | Argo CD CLI | 服务端 | 3.5.5 | 252,547,072 | GitHub Releases（裸 exe） |
| `prometheus` | Prometheus | 服务端 | 3.15.0 | 114,650,144 | GitHub Releases |
| `victoriametrics` | VictoriaMetrics | 服务端 | 1.154.0 | 7,488,593 | GitHub Releases |
| `k6` | k6 | 服务端 | 2.3.0 | 31,706,650 | GitHub Releases |
| `pulumi` | Pulumi | 服务端 | 3.268.0 | 117,108,545 | GitHub Releases |
| `istioctl` | Istio CLI | 服务端 | 1.31.1 | 31,244,552 | GitHub Releases |
| `talosctl` | Talos Linux CLI | 服务端 | 1.11.0 | 94,281,216 | GitHub Releases（裸 exe） |
| `elixir` | Elixir | 开发环境 | 1.20.4 | 8,658,381 | GitHub Releases |
| `scala-cli` | Scala CLI | 开发环境 | 1.18.0 | 43,050,388 | GitHub Releases |
| `bazelisk` | Bazelisk | 开发环境 | 1.29.0 | 10,502,144 | GitHub Releases（裸 exe） |
| `just` | Just | 开发环境 | 1.59.0 | 2,292,448 | GitHub Releases |
| `task` | Task | 开发环境 | 3.54.0 | 17,023,230 | GitHub Releases |
| `oxlint` | Oxlint | 开发环境 | 1.88.0 | 5,762,811 | GitHub Releases |
| `biome` | Biome | 开发环境 | 2.5.15 | 79,007,744 | GitHub Releases（裸 exe） |
| `nushell` | Nushell | 开发环境 | 0.116.1 | 60,864,303 | GitHub Releases |
| `starship` | Starship | 开发环境 | 1.26.0 | 4,758,038 | GitHub Releases |
| `gh` | GitHub CLI | 开发环境 | 2.102.0 | 15,512,013 | GitHub Releases |

**这一批的方法论（可装配类通用，下次照抄）**

1. **`path_subdir` 先用 `""` 起手**，因为两条既有逻辑合起来覆盖了绝大多数归档：
   `extract_archive` 末尾会把"根上只有一个目录且没有散文件"塌成安装根，
   而 `exec_path_in_home` 会依次试 `path_subdir` → `bin` → `Scripts` → `condabin` → 根。
2. **但一定要跑 `tools/bt_archive_layout_audit.py` 终审**。我先按 `""` 登记，
   审计当场报出 5 个问题，全是"声明与归档不符"：
   - **BAD（exe 在子目录，要显式写 subdir）**：`pulumi` → `bin`、`elixir` → `bin`、`gh` → `bin`
   - **FAIL（归档里根本没有我登记的那个 exe 名）**：`victoriametrics` 实际叫
     `victoria-metrics-windows-amd64-prod.exe`、`oxlint` 实际叫
     `oxlint-x86_64-pc-windows-msvc.exe`
   `pulumi` 那次还栽了个跟头：先写 `subdir="pulumi/bin"`，审计报"PATH 指的
   `pulumi/pulumi/bin`"—— 因为塌了一层之后根已经是 `pulumi/`，所以只能写 `bin`。
3. **zip 里的二进制名是改不了的**：`install_binary` 的"按 exec_name 改名"只对
   **单文件形态**（exe/war/裸文件）生效；zip 解压出来的文件保持官方名。
   所以 `victoriametrics` / `oxlint` 的 `exec_name` 只能是那一长串官方名 ——
   功能没问题（探测/PATH 都按它找），只是用户敲的命令会长；要短名得自己复制一份改名。
4. **单文件 exe 的 SKIP 是正常的**：`argocd` / `talosctl` / `bazelisk` / `biome` 审计报
   SKIP（单二进制没有可随机读的清单），这类靠装完自检 `verify_bin_dir` 兜。
5. **`delta` 撤掉了**：它没有官方图形标识（仓库里只有终端截图），而 Simple Icons 的
   `delta` 是**三角洲航空**的标（还是横幅，护栏本身也会拒）。宁缺勿错，不接。

**镜像登记的新姿势**：可装配的 GitHub 组件登记进 `OFFICIAL_HOST`（值 `github.com`，
与 `deno`/`ripgrep` 同列），**不是** `github_assets`（那张是只下载类的）；
`terraform` 是唯一"官方单源、零大陆镜像"的，进 `OFFICIAL_ONLY_EXCEPTION`。

**仍未接（候选还在，方式同上）**：grafana / loki / jaeger / alertmanager / otelcol（多半要 tar.gz
或厂商 CDN 抓取器）、rclone / mariadb / influxdb / cockroachdb / nomad（厂商 CDN）、
gitea / gitlab-runner / nexus（厂商 CDN、且是**服务**不是 CLI）、
minikube / kind / k3d / kustomize / stern / nerdctl / velero / kubeseal / mkcert / sops / restic /
terragrunt / act（GitHub，多数也能接）、zig / julia / php / nim / groovy / tinygo / v / nasm /
clojure / jj / lazygit / aria2 / hyperfine / dust / duf / scc / miller（语言与效率 CLI）。
本批只挑了我能一次验完的 19 个。

### R20.9 nats-server 接进「一键启停」（2026-10-16）

「一键启停」从 15 个扩到 **16 个**：新增 `nats-server`（NATS Server，消息/流服务）。
它是**第一个**从「服务端组件」挪过来的组件 —— 进了 `LAUNCH_OF` 就自动归到「一键启停」
（`group_components()` 按 `LAUNCH_KEYS` 归类），所以 `EXPECTED_MEMBERSHIP` 里
CAT_SERVER 少一个、CAT_LAUNCH 多一个。（`caddy` / `traefik` 仍未接，原因见下。）

**当天在 %TEMP% 跑真进程实测出来的四条事实**（规格里逐条写了引用）：

1. 归档是「单顶层目录 + nats-server.exe」（条目只有 LICENSE / README / nats-server.exe）
   ⇒ 解压塌层后 `path_subdir=""` 正确 —— 与 `bt_archive_layout_audit` 的结论一致。
2. `-p <端口>` 能改口 ⇒ `port_writeback="cli_flag"`，不碰配置文件。
3. ⚠ **只给 `-sd <dir>` 不够**：实测数据目录根本不会被创建 —— NATS 只在启用 JetStream
   时才落盘。必须 `-js -sd <dir>` 一起给，才会建出 `<dir>/jetstream/`。
   **这条是纯实测得来的，凭直觉写会得到一个"看起来配了数据目录、其实什么都没存"的规格。**
4. `nats-server.exe` 自己就是监听进程（不是包装器）⇒ `stop_kind="pid"`，
   `terminate()` 后端口随即释放（实测 4224 从"在听"变"不在听"）。

没有网页控制台：4222 讲的是 NATS 协议（不带 `-m` 时连监控口都没有），
所以 `console_path` / `health_path` 都是 None、判活只看端口 —— 与 redis 同一档。

**`caddy` / `traefik` 为什么仍没接**：两者都能跑（单二进制），但
① caddy 的默认 80/443 在 Windows 上会撞 http.sys（本项目 nginx 就是因此特意用 8888），
要另定端口策略；② traefik 的 dashboard 在 8080、与 jwt/jenkins 那一簇口的避让关系要逐个核；
③ 两者的"优雅停"要区分 `caddy stop`（走 admin API）与按 PID；**都必须在真机上把
「起 → 端口整簇在听 → 停 → 端口释放」跑一遍才算数**（R5/R14 的口径）。
`prometheus` / `victoriametrics` 同理（单二进制、9090/8428，但要先定配置文件从哪来）。
这四个是下一批的自然候选，方法同本节。

## 规则 R21：「官网下载」是只下载里更弱的一档，为的是"先把组件都收进来"（2026-10-15）

### R21.1 规则描述

用户在接第二批 Agent 客户端时给了新口径：**"如果拿不到下载方式的就做一个『官网下载』
按钮，用户点击时就直接打开浏览器自行去官网下载，主要把这些组件都接进来"**。

即：一个组件**官方没有可直接下载的安装包直链**（只给网页入口 / 要真机抓包 / 只能用
npm・pip・插件装）时，**不是**从表里删掉、也不是放一张点不动的空卡片，而是给一颗
**「官网下载」**按钮 —— 点一下 `QDesktopServices.openUrl()` 打开它的官网，由用户自己下。

这不是"降级"或"兜底失败"，而是这类组件**应有**的形态：本工具的价值是"集中列出、一键找到
官方入口"，代不代下是第二位。

### R21.2 硬约束（缺一条就是 bug）

1. **`official_page_only` 是 `download_only` 的子集，不是并列档**。置上它的卡片仍必须是
   `download_only=True`（否则会走安装链去写注册表 / PATH）。二者关系由
   `bt_download_only_tests.WebFallback.test_web_only_implies_download_only` 钉死。
2. **必须同时有 `official_url`**（R19 那张**人工登记**的表），否则按钮点开是个空页面。
   由 `WebFallback.test_web_only_components_have_a_registered_official_url` 钉死。
   没登记时 `on_open_official_page_clicked()` 报错而**不是** `openUrl("")`。
3. **版本表为空**：表驱动里把这一行写成**空元组** `()` 即可 —— builder 用
   `official_page_only=not rows` 自动判定，**不需要**另写 `Component(...)`。
   由 `WebFallback.test_web_only_components_have_no_version_table` 钉死。
   （空版本表 → `bt_mirror_spec_tests.test_counts` 要 `continue` 跳过，否则 `versions[0]` 越界。）
4. **文案要说清"本工具不代下、不代装、不代跑安装器"** —— 否则用户以为点了就开始下。
   tooltip 同 R13：把 `data_note`（"这软件干嘛的、数据落在哪"）拼在提示里。
5. **官网必须是"下载入口"而非"品牌首页"**：能给下载页就给下载页（如 `…/download`），
   给不了才给首页。这条是人工判断，写进 `COMPONENT_OFFICIAL_URLS` 时顺手写准。

### R21.3 复用而非新造

- 卡片那**一颗**主按钮仍是 `self.btn_install`（属性名不改）—— `_sync_action_buttons`、
  布局与一批用例都按它找。分支只是多一层：
  `download_only → official_page_only ? 「官网下载」: 「下载/下载 ▾」`。
- 槽位是**独立**的 `on_open_official_page_clicked()`，**不复用** `on_download_clicked` ——
  后者的收尾是问目录、起 `DownloadWorker`；共用一个槽位等于给"顺手在这里加一行代下"留门。
- 只有 Windows 之外的平台、或直链失效时，`download_only` 那一档才用
  `unsupported_platform_hint`；`official_page_only` 与平台无关（任何平台都点开浏览器）。

### R21.4 护栏

- `tests/bt_download_only_tests.py`：`WebFallback` 三条（有官网 / 无版本表 / 蕴含 download_only）；
  `test_every_download_only_component_has_windows_urls_to_download` 开头 `if comp.official_page_only: continue`。
- `tests/bt_mirror_spec_tests.py`：`test_counts` 开头 `if not comp.versions: continue`。
- 新接这类组件仍须补 `COMPONENT_SUMMARY` / `COMPONENT_USAGE` / `COMPONENT_OFFICIAL_URLS`
  三张登记表 **+ 一个图标**（`bt_icon_assets_tests` 缺图标即红）。

## 规则 R22：每个 Tab 内的卡片按显示名 a→z 排（2026-10-15）

### R22.1 规则描述

用户要求："对我们软件内各个 table 下的组件做个字母 a-z 顺序排序"。

落点在**唯一一处**：`main.group_components()` 分组完，每个 Tab 内 `lst.sort(_tab_sort_key)`。
不逐张表手工调顺序 —— 那样接一个新组件就要想"该插在哪一行"，而人一定会插错。

### R22.2 排序键的三个决定（都别随手改）

1. **排显示名，不排 key**。界面上给用户看的是显示名；按 key 排会出现
   "`百度搭子 DuMate` 排进 D 段、`文心` 排进 E 段"这种念不出来的错位
   （key 是 `dumate` / `ernie`）。反过来，按显示名排时英文名与汉语拼音大体同序。
2. **`casefold()` 忽略大小写**，于是 `DBX` 与 `DBeaver` 按 `dbx` / `dbeaver` 相邻，
   而不是把大写全排到小写前面。
3. **显示名开头的标点先剥掉**（`.NET SDK` → `net sdk`）。`.` 的码位(0x2E)比所有字母小，
   不剥就永远排第一；而用户念它是"点 NET"，预期落在 N 段。

### R22.3 中文名怎么排（这是刻意选的，不是漏了）

中文没有"字母"，`casefold()` 之后按**码位**比较、**自然全部落在英文名之后**
（码位 U+4E00 以上远大于 `z`）。这是刻意选的：

- 用户要的是"念得出字母的排在前、a→z"；硬把中文混进字母序里，只会让英文段也被割碎。
- 按**拼音**排需要额外引一张拼音表（每个中文名一条），那是一份新的登记负担与新的
  失败模式（漏登记就悄悄排错位）。**要做就得单独立一条规则**，不在 R22 里顺手加。

当前效果：Agent客户端 Tab = 英文名 a→z（AutoClaw → Zed）→ 之后是中文名（码位序）。

### R22.4 护栏

- `tests/bt_component_category_tests.py`：
  `test_every_tab_is_sorted_a_to_z_by_display_name`（逐 Tab 断排序键单调不降，
  **并且**断"至少有一个 Tab 的顺序不同于 `build_components()` 的书写顺序"——
  否则这条用例分不清"排序生效了"和"没排也恰好有序"）、
  `test_alphabetical_sort_ignores_leading_punctuation`（`.NET SDK` 必须夹在
  Miniconda 与 Ninja 之间）。
- 顺带说明为什么 `test_grouping_preserves_order_and_covers_every_tab` **不用改**：
  它断的是 **Tab 之间**的顺序（等于 `COMPONENT_CATEGORIES`）与成员集合，
  组内顺序不归它管。

## 规则 R23：网格多余的**行高**必须落到布局末尾的 stretch 上（2026-10-15）

### R23.1 规则描述

卡片是网格排列的，**同一行的卡片会被 `QGridLayout` 拉成等高**。凡是"内容比别人少"
的卡片，就多出一段高度。这段高度必须有明确去处：

> **每张卡的 root 布局末尾都必须有一个 `addStretch(1)`。**

`_build_ui()` 末尾那一行是**无条件**的。少了它，那段高度会被布局按策略分给**能纵向
长大的控件**，而带背景色的 QLabel（`statusLabel` / `multiVersionBadge`）首当其冲 ——
用户看到的就是同一行里"颜色方块一个大、一个紧凑"。

### R23.2 这个缺陷真实发生过两次，第二次才修对

| 时间 | 症状 | 当时怎么处理的 | 为什么没修净 |
|---|---|---|---|
| 2026-10-10 | JDK / Python 卡的**「可多版本」角标**被拉成大盒子，同行的 Maven 是紧凑胶囊 | 加了 `root.addStretch(1)` | **加错了地方** —— 写进了 `_build_external_section()` 的末尾，也就是**只有那 7 个外部接管组件**（jdk / python / node / go / maven / gradle / bun）才有 |
| 2026-10-15 | Ant / bat 卡的**状态标签**（「○ 未安装」「● 已装 …」）被拉成空白大色块 | 把那一行挪到 `_build_ui()` 末尾，**所有卡片无条件都有** | —— |

**为什么隔了 5 天才露出来**：旧顺序下恰好没有排出"高矮混排"的一行（Maven 那次和
JDK / Python 同排，而那两张**都在白名单里**，本来就有 stretch）。2026-10-15 给 Tab
加了 a→z 排序（R22）后，高卡（Maven 238px）与矮卡（Ant / bat 178px）排进同一行，
缺陷立刻变成肉眼可见。**排序只是触发器，缺陷本身一直都在。**

### R23.3 护栏，以及"永真式"的教训

`tests/bt_grid_layout_tests.py::BadgeNeverStretchesVertically`：

- `test_badge_height_is_its_size_hint_not_the_leftover_space` —— 用 `jdk`（白名单内）
  当短卡片。**这条永远钉不住 2026-10-15 那个缺陷**，因为 jdk 自己就有 stretch。
- `test_status_label_is_not_stretched_when_a_row_mate_is_taller` —— 用 `ant`
  （**白名单外**）当短卡片，并且**显式断言**
  `assertFalse(supports_external_takeover(short.component))`：
  哪天有人把对照组换成白名单内的 key，这条会直接红，而不是悄悄退化成永真式。

**实测确认有牙**：把这条用例拿到修复前的代码上跑，红在
`AssertionError: 264 != 12`（statusLabel 被拉到 264px，它自己的 sizeHint 只有 12）。
写"防拉伸"这类用例时，**必须同时断言"这一行真的有多余空间"**
（`short.height() > short.sizeHint().height()`），否则控件没被拉高时它会假绿。

### R23.4 不要顺手改的：状态标签的**横向**裁字是有意为之

`status_label` 的 `setMinimumWidth(1)` + 不换行 = 超宽部分被**裁掉**，全量原文在
tooltip 里（源码注释写了理由：不同机器字体/缩放不同，不压掉最小宽会把格子撑开）。
这是刻意的，看到长状态文字在卡片右边缘被切断**不要去加省略号**。

## 规则 R24：Windows 上中文**不许走命令行 argv**（2026-10-15）

### R24.1 规则描述

Windows 上原生命令行的 `argv` 会按**系统 ANSI 代码页**（`GetACP()`）被 CRT 转一次码：

| 系统 ANSI 代码页 | 中文的命运 |
|---|---|
| **65001**（UTF-8） | 无损 —— 维护者本机正是这个，所以**本地永远看不出问题** |
| **1252**（英文 Windows / GitHub runner） | 全部变成 `?`（不可映射） |
| **936**（常见中文 Windows） | 变成 GBK 字节，对方按 UTF-8 读就是乱码 |

所以：**任何可能含非 ASCII 的内容，都不要作为命令行参数传给原生 exe**（`curl`、`git`、
`python.exe`…）。要传就**走文件**或**走 stdin**。

同一条根因的两种表现，2026-10-15 一天内各踩一次：

1. **stdout 编码**：CI 上 `python -u tests/run_all_tests.py` 只跑 1 秒就红 ——
   runner 是 en-US，Python 往**管道**写 stdout 按 cp1252 编码，项目输出几乎全是中文，
   第一句 `print("解释器：…")` 就抛 `UnicodeEncodeError`。修：workflow 顶层
   `PYTHONIOENCODING: utf-8`。
2. **argv 编码**：`同步Gitee产物.sh` 里 `curl -F "body=<正文>"` 把整段中文送上命令行，
   runner 上正文全变 `?`（本机 CP65001 恰好无损）。修：正文落临时文件，
   用 `-F "body=<文件"` 让 curl 读文件当字段值。

### R24.2 为什么这两个都特别难发现

**维护者本机是 CP65001（UTF-8），两类问题在本地都不会复现**，而 CI 是 CP1252。
并且第二类连"换个 locale 复跑"都验不出来 —— `LC_ALL=C` 也照样过（转码发生在
cmdline→CRT 那一层，与 shell 的 locale 无关）。

**本机的两个验伪手段**（都在 CI 上真红过之后才补的）：
- 查环境：`ctypes.windll.kernel32.GetACP()` 在本机是 65001，runner 上是 1252。
- 静态对账：`bt_gitee_sync_tests.test_release_body_never_travels_through_the_command_line`
  断"脚本里不许出现把正文插值进 `-F` 取值的写法"，并要求落盘那一行存在。
  **本机改不了 `GetACP`，所以跑一遍验不出转码；只有静态断言钉得住。**
  （写这条时它立刻抓到我自己解释性注释里写的那句字面量 —— 注释里别再抄那个写法。）

### R24.3 顺带记两条脚手架事实

- GitHub 的 `windows-latest` 是 **Windows Server 2025**，`platform.win32_ver()[0]`
  是 `2025Server`。断言"版本号必须是 10/11"这类**写死客户端 Windows** 的期望会在
  runner 上无条件红（`bt_startup_tests` 就是这么红的）。正确做法是用标准库自己的
  `platform._WIN32_{CLIENT,SERVER}_RELEASES` 表算期望值 —— 见该文件新增的
  `_expected_release()`。
- runner 的 `TEMP` 是 **8.3 短名**（`C:\Users\RUNNER~1\…`），而 `Path.resolve()`
  给的是长名。**比路径要么两边都 `resolve()`**（`bt_update_check_tests`），
  **要么就别依赖宿主机上恰好存在的目录**（`bt_external_version_tests` 里那个
  `path_effective_check` 是按真实文件系统找命令的，夹具必须自己造出"压住命令的那个目录"，
  不能指望宿主机装了 `E:\soft\maven\…`）。

---

## 规则 R25：可装配组件必须是官方**完整发行版**，不许用 embeddable / Mini 精简包（2026-10-28）

### R25.1 规则描述

用户 2026-10-28 要求：盘点全部可装配组件，凡是"便携版 / 精简版"一律换成官方完整版。

**准入规则（自本条起生效）：新接入组件只允许官方完整发行版；embeddable / Mini / 精简版一律不收。**
官方只发便携包的组件（Node / JDK 等）可以接，但必须是官方完整发行版；
「只下载」类同样适用（有安装器时默认形态必须是完整安装器，便携包只能作为备选）。
接新组件时先回答一句：**"这是官方完整发行版，还是为了省体积砍过功能的精简包？"**
答不上来就不许合入。

盘点结论：80 个可装配组件里只有两个是真正的精简形态，其余虽然多以 zip / tar 交付，
但都是官方完整发行版（Node / JDK / Maven / MongoDB 等上游本来就只有压缩包形态）。
要换的两个：

| 组件 | 旧（精简） | 新（完整） | 为什么必须换 |
|---|---|---|---|---|
| Python（Windows） | `python-<v>-embed-amd64.zip`（embeddable） | 官方 NuGet 包 `python.<v>.nupkg` 的 `tools/`（完整标准库 + pip + venv；NuGet 发行形态**不含 tkinter / IDLE**） | embeddable 没有 `Lib/`、`venv`、`ensurepip`；卡片写着"pip 包管理"，实际 `python -m pip` / `python -m venv` 都不可用 |
| Git（Windows） | `MinGit-<v>-64-bit.zip` | `PortableGit-<v>-64-bit.7z.exe` | MinGit 只有最小命令集，没有 Git Bash / Perl / OpenSSH |

### R25.2 硬约束

1. **判据是"官方发行形态是否完整"，不是"包是不是 zip"**。官方只发 zip 的组件（Node / JDK…）
   不算精简版，不许为了"完整"去换第三方安装器。
2. Python Windows 只许用 NuGet 完整包，**不许回到 embeddable**，也不许改用 exe 安装器：
   Burn 安装器的 provider key（`CPython-3.12`）是全局单实例，机器上已有同 minor 版本时
   装不进第二个目录，与多版本并存直接冲突（2026-10-28 实测退出码 0x642）。
3. Python 的 `path_subdir` 必须跟着发行形态走：NuGet 完整包是 `tools`
   （实测 `tools/python.exe`、`tools/Lib/site-packages/pip`）；
   `python -m pip` 与 `python -m venv` 都要真跑通之后才算接完。
4. Git Windows 只许用 PortableGit 完整包，**不许回到 MinGit**。归档后缀是 `.7z.exe`，
   由 `extract_archive` 的 `-o<dir> -y` 分支静默展开；**该分支必须排在通用 `.exe`
   单文件分支之前**，否则会被原样拷进安装目录，PATH 里永远找不到 git.exe。
5. 换发行形态必须同步四件事：`path_subdir`、`archive_map`、R1.5 镜像表、护栏用例。
6. 完整包同样遵守 R1。Python NuGet 目前只有华为云一个提供方（两个子域都实测
   200 + `PK`），nuget.org 官方末位；这是**已登记的源数量例外**，不许用假镜像凑数。
7. **旧版精简包不做自动迁移**：目录名相同（`python-3.12.4` / `git-2.47.1`）、布局不同，
   卡片仍会把它当成"已装"，安装按钮是灰的。用户要先点「卸载」再点「安装」
   （同版本安装本来就会覆盖目录）。不做自动删除/替换是有意的：未经确认删用户目录
   风险太高，且无法判断用户是否还在用那份旧环境。

### R25.3 真机验收（2026-10-28 实测记录）

- Python 3.12.4 NuGet：`tools/python.exe` → 3.12.4；`python -m pip --version` → pip 24.0；
  `python -m venv <tmp>` 建出的 venv 里 `python -m pip --version` → pip 24.0。
- Git 2.47.1 PortableGit：`cmd/git.exe --version` → `git version 2.47.1.windows.1`；
  `usr/bin/bash.exe --version` → `GNU bash, version 5.2.37(1)-release`。
- 两条都走 `install_downloaded()` 的完整落位路径（下载 → 解压 → move 到 install_dir），
  不是只解压到临时目录。

### R25.4 护栏

- `bt_mirror_spec_tests.test_python_versions_use_the_full_nuget_package`
- `bt_mirror_spec_tests.test_git_versions_use_portablegit_not_mingit`
- `bt_multiversion_tests.PythonPathDirHoldsTheInterpreter`
- `bt_install_safety_tests.ArchiveTraversalGuard.test_7z_sfx_is_extracted_not_copied_as_a_binary`
