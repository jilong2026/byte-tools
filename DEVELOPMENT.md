# byte-tools 开发文档

> 本文档面向本项目的二次开发者与维护者，记录开发约定、规则与设计指引。
> 新功能、新组件、新规则的引入必须先落入本文件，再写代码落地。

---

## 文档说明

- **适用范围**：本仓库所有 Python 源码改动、新增组件、URL 与下载逻辑改造
- **更新原则**：规则变化或新增规则必须先改本文档再改代码；代码与文档不一致时以本文档为准
- **与 README 的关系**：README.md 面向最终用户，本文档面向开发者

---

## 规则索引

- [规则 R1：国内镜像优先 + 多源故障转移](#规则-r1国内镜像优先--多源故障转移)

<!-- 后续新增规则在此追加索引 -->

---

## 规则 R1：国内镜像优先 + 多源故障转移

### R1.1 规则描述

所有组件的下载必须遵循以下优先级，**不得直接使用官网地址作为首选**：

1. **第一优先级**：中国大陆境内镜像加速地址
2. **故障转移**：第一个镜像不可用时按顺序切换到下一个国内镜像
3. **末位回退**：所有配置的国内镜像均失败后，才回退到组件官方下载地址

每个新组件**必须**配置 **≥2 个**国内镜像地址，否则不予合入。

### R1.2 适用范围

- **全部 24 个组件**（语言运行时：jdk / python / node / go / bun；构建工具：maven / gradle；应用服务器：tomcat；数据库：mysql / mongodb / postgresql；容器与编排：docker / kubectl；CI/CD：jenkins；消息队列：rabbitmq / kafka / rocketmq / pulsar / activemq；服务发现与事务：nacos / seata；搜索引擎：elasticsearch；版本控制：git；Python 发行版：conda）
- `build_components()` 的默认（离线）清单
- `fetch_xxx_versions()` 版本列表抓取请求（含公共辅助函数 `_fetch_github_releases_versions` / `_fetch_apache_versions`）
- `DownloadWorker` 的实际下载请求（按 `url_list_map` 顺序遍历，失败自动切换）
- `ComponentVersion.url_list_map` 多源故障转移 URL 列表（向后兼容旧的 `url_map` 单 URL 模式）
- 平台不支持场景的 `unsupported_platform_hint` 友好提示（如 Docker 在 Windows、PostgreSQL 在 macOS）

### R1.3 镜像源优先级表

下表为推荐的国内镜像源，**按稳定性与速度综合排序**。新增组件的镜像清单必须从下表挑选，不得引入表中未列出的源（保证可维护性）。

| 序号 | 镜像源 | 标识 | 域名 | 备注 |
|------|--------|------|------|------|
| M1 | 华为云 | `huaweicloud` | `repo.huaweicloud.com` | 覆盖最广，速度稳定，常作为第一优先级 |
| M2 | 清华 TUNA | `tuna` | `mirrors.tuna.tsinghua.edu.cn` | 高校镜像，覆盖面广，维护活跃 |
| M3 | 阿里云 | `aliyun` | `mirrors.aliyun.com` | 阿里云提供，国内速度快 |
| M4 | 南京大学 | `nju` | `mirrors.nju.edu.cn` | 高校镜像，作为备用 |
| M5 | 中科大 | `ustc` | `mirrors.ustc.edu.cn` | 高校镜像，作为备用 |
| M6 | 上海交大 | `sjtug` | `mirrors.sjtug.org` | 高校镜像，作为备用 |

> 镜像源清单本身视为配置常量，集中维护在源码的 `MIRROR_SOURCES` 常量或外部配置文件中，**严禁**散落在各 URL 构造器函数里硬编码。

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
            ┌──────▼──────┐
            │ HEAD/GET 探测│
            │ 超时=N 秒    │
            └──────┬──────┘
                   │
        ┌──────────┴──────────┐
        成功                   失败
        │                       │
        ▼                       ▼
   ┌─────────┐         ┌─────────────────┐
   │ 流式下载 │         │ 记录失败日志     │
   │ 走该 URL │         │ 切到下一个 URL  │
   └─────────┘         └─────────────────┘
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

**关键参数**（必须可配置，不得硬编码）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 单 URL 探测超时 | 5 秒 | HEAD 请求超时阈值 |
| 单 URL 下载超时 | 30 秒 | 流式下载连接超时阈值 |
| 单 URL 重试次数 | 2 | 同一 URL 内重试（指数退避） |
| 故障转移最大尝试数 | 镜像数 + 1 | 超过则判定为彻底失败 |

### R1.5 各组件镜像清单

#### 基础 8 个组件（首批落地）

| key | 组件 | 国内镜像（按优先级） | 末位官网 |
|-----|------|----------------------|---------|
| `jdk` | JDK (Temurin) | M1 `repo.huaweicloud.com/openjdk/`、M2 `mirrors.tuna.tsinghua.edu.cn/Adoptium/`、M3 `mirrors.aliyun.com/adoptium/` | `api.adoptium.net` |
| `maven` | Apache Maven | M1 `repo.huaweicloud.com/apache/maven/maven-3/`、M2 `mirrors.tuna.tsinghua.edu.cn/apache/maven/maven-3/`、M3 `mirrors.aliyun.com/apache/maven/maven-3/` | `archive.apache.org/dist/maven/maven-3/` |
| `tomcat` | Apache Tomcat | M1 `repo.huaweicloud.com/apache/tomcat/`、M2 `mirrors.tuna.tsinghua.edu.cn/apache/tomcat/`、M3 `mirrors.aliyun.com/apache/tomcat/` | `archive.apache.org/dist/tomcat/` |
| `mysql` | MySQL Server | M2 `mirrors.tuna.tsinghua.edu.cn/mysql/Downloads/`、M3 `mirrors.aliyun.com/mysql/Downloads/`、M1 `repo.huaweicloud.com/mysql/Downloads/` | `dev.mysql.com/get/Downloads/` |
| `python` | Python | M2 `mirrors.tuna.tsinghua.edu.cn/python/`、M3 `mirrors.aliyun.com/python/`、M1 `repo.huaweicloud.com/python/` | `www.python.org/ftp/python/` |
| `node` | Node.js | M2 `mirrors.tuna.tsinghua.edu.cn/node/`、M3 `mirrors.aliyun.com/node/`、M1 `repo.huaweicloud.com/nodejs/` | `nodejs.org/dist/` |
| `git` | Git for Windows | M1 `repo.huaweicloud.com/git-for-windows/`、M2 `mirrors.tuna.tsinghua.edu.cn/github-release/git-for-windows/git/`、M3 `mirrors.aliyun.com/github-release/git-for-windows/git/` | `github.com/git-for-windows/git/releases/download/` |
| `conda` | Miniconda | M2 `mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/`、M3 `mirrors.aliyun.com/anaconda/miniconda/`、M1 `repo.huaweicloud.com/anaconda/miniconda/` | `repo.anaconda.com/miniconda/` |

> 注：部分镜像可能未同步最新版本，故障转移时若镜像返回 404，直接切到下一个，**不要**对该 URL 内部反复重试。

#### 新增组件镜像清单

新增组件必须按下表登记其镜像配置，登记后再写代码：

| key | 组件 | 国内镜像（按优先级） | 末位官网 | 登记日期 | 状态 |
|------|------|-----------------------|---------|---------|------|
| `go` | Go | M1 `repo.huaweicloud.com/golang/`、M2 `mirrors.tuna.tsinghua.edu.cn/golang/`、M3 `mirrors.aliyun.com/golang/`、M5 `mirrors.ustc.edu.cn/golang/` | `go.dev/dl/` | 2026-09-24 | 已落地 |
| `gradle` | Gradle | M1 `repo.huaweicloud.com/gradle/`、M2 `mirrors.tuna.tsinghua.edu.cn/gradle/`、M3 `mirrors.aliyun.com/gradle/`、M5 `mirrors.ustc.edu.cn/gradle/` | `services.gradle.org/distributions/` | 2026-09-24 | 已落地 |
| `bun` | Bun | N1 `registry.npmmirror.com/-/binary/bun/`（淘宝 NPM 镜像，Bun 在国内最稳）、N2 `ghproxy.com` 加速 GitHub releases | `github.com/oven-sh/bun/releases` | 2026-09-24 | 已落地（含 R1.3 表外特殊源，Bun 在国内仅此两源稳定） |
| `docker` | Docker | M2 `mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/static/`、M3 `mirrors.aliyun.com/docker-ce/linux/static/`、M5 `mirrors.ustc.edu.cn/docker-ce/linux/static/` | `download.docker.com/linux/static/` | 2026-09-24 | 已落地（Linux/Mac static tgz 解压即用，Windows 不支持，提示用户用 Docker Desktop） |
| `mongodb` | MongoDB | M1 `repo.huaweicloud.com/mongodb/`、M2 `mirrors.tuna.tsinghua.edu.cn/mongodb/`、M3 `mirrors.aliyun.com/mongodb/`、M5 `mirrors.ustc.edu.cn/mongodb/` | `fastdl.mongodb.org/` | 2026-09-24 | 已落地（Windows zip + Linux tgz 解压即用） |
| `postgresql` | PostgreSQL | M2 `mirrors.tuna.tsinghua.edu.cn/postgresql/`（源码目录，binaries 路径占位 fallback）、M1 `repo.huaweicloud.com/postgresql/`（同上） | `get.enterprisedb.com/postgresql/` | 2026-09-24 | 已落地（国内镜像无 binaries，主走 EDB 官网；Mac 不支持，提示用 brew） |
| `kubectl` | kubectl | M3 `mirrors.aliyun.com/kubernetes/`、M2 `mirrors.tuna.tsinghua.edu.cn/kubernetes/`（部分路径）、N2 `ghproxy.com` 加速 GitHub releases | `dl.k8s.io/release/` | 2026-09-24 | 已落地（单二进制跨平台，Linux/Mac 无扩展名需 chmod +x） |
| `jenkins` | Jenkins | M1 `repo.huaweicloud.com/jenkins/`、M2 `mirrors.tuna.tsinghua.edu.cn/jenkins/`、M3 `mirrors.aliyun.com/jenkins/` | `get.jenkins.io/war-stable/` | 2026-09-24 | 已落地（单 war 文件，需用户用 `java -jar jenkins.war` 启动，本工具只做下载+配置环境变量） |
| `rabbitmq` | RabbitMQ | M1 `repo.huaweicloud.com/rabbitmq/`、M2 `mirrors.tuna.tsinghua.edu.cn/rabbitmq/`、M3 `mirrors.aliyun.com/rabbitmq/` | `github.com/rabbitmq/rabbitmq-server/releases` | 2026-09-24 | 已落地（Linux/Mac generic binary tar.gz 解压即用；Windows 不支持自动下载，引导用户去官网下安装器，因依赖 Erlang） |
| `kafka` | Apache Kafka | M1 `repo.huaweicloud.com/apache/kafka/`、M2 `mirrors.tuna.tsinghua.edu.cn/apache/kafka/`、M3 `mirrors.aliyun.com/apache/kafka/`、M5 `mirrors.ustc.edu.cn/apache/kafka/` | `archive.apache.org/dist/kafka/` | 2026-09-24 | 已落地（Scala 跨平台 tgz/zip 解压即用，需 JDK 运行） |
| `rocketmq` | Apache RocketMQ | M1 `repo.huaweicloud.com/apache/rocketmq/`、M2 `mirrors.tuna.tsinghua.edu.cn/apache/rocketmq/`、M3 `mirrors.aliyun.com/apache/rocketmq/`、M5 `mirrors.ustc.edu.cn/apache/rocketmq/` | `archive.apache.org/dist/rocketmq/` | 2026-09-24 | 已落地（Java 跨平台 zip 解压即用，需 JDK 运行） |
| `pulsar` | Apache Pulsar | M1 `repo.huaweicloud.com/apache/pulsar/`、M2 `mirrors.tuna.tsinghua.edu.cn/apache/pulsar/`、M3 `mirrors.aliyun.com/apache/pulsar/`、M5 `mirrors.ustc.edu.cn/apache/pulsar/` | `archive.apache.org/dist/pulsar/` | 2026-09-24 | 已落地（Java 跨平台 tar.gz 解压即用，需 JDK 运行） |
| `activemq` | ActiveMQ | M1 `repo.huaweicloud.com/apache/activemq/`、M2 `mirrors.tuna.tsinghua.edu.cn/apache/activemq/`、M3 `mirrors.aliyun.com/apache/activemq/`、M5 `mirrors.ustc.edu.cn/apache/activemq/` | `archive.apache.org/dist/activemq/` | 2026-09-24 | 已落地（Java 跨平台 tar.gz/zip 解压即用，需 JDK 运行） |
| `nacos` | Nacos | N2 `ghproxy.com` 加速 GitHub releases（Nacos 在国内无官方镜像，主走 ghproxy）、N3 `gh.idayer.com/` 加速 GitHub releases（备用） | `github.com/alibaba/nacos/releases` | 2026-09-24 | 已落地（Java 跨平台 zip/tgz 解压即用，需 JDK 运行） |
| `seata` | Seata | N2 `ghproxy.com` 加速 GitHub releases（Seata 在国内无官方镜像，主走 ghproxy）、N3 `gh.idayer.com/` 加速 GitHub releases（备用） | `github.com/apache/incubator-seata/releases` | 2026-09-24 | 已落地（Java 跨平台 zip/tgz 解压即用，需 JDK 运行） |
| `elasticsearch` | Elasticsearch | M2 `mirrors.tuna.tsinghua.edu.cn/elasticstack/`、M1 `repo.huaweicloud.com/elasticsearch/`（部分版本占位 fallback）、M3 `mirrors.aliyun.com/elasticsearch/`（同上） | `artifacts.elastic.co/downloads/elasticsearch/` | 2026-09-24 | 已落地（Java 跨平台 tar.gz/zip 解压即用，需 JDK 运行；版本 8.x 起 URL 含 -<platform>-<arch> 后缀） |
| _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ |

### R1.6 新增组件的镜像配置 checklist

新增一个组件 PR 之前，必须依次确认：

- [ ] 已从 R1.3 镜像源优先级表中挑选 ≥2 个镜像源
- [ ] 在 R1.5「新增组件镜像清单」表中登记该组件的镜像清单
- [ ] URL 构造器函数签名改为返回**镜像 URL 列表 + 官网 URL**，而非单 URL
- [ ] 版本抓取器 `fetch_xxx_versions()` 内部请求镜像索引页，失败回退官网索引页
- [ ] `DownloadWorker` 改造为按列表顺序尝试下载，单个 URL 失败自动切换
- [ ] 故障转移全程输出中文日志（哪个镜像失败、切换到哪个、最终用了哪个）
- [ ] 默认（离线）清单 `build_components()` 内的 URL 也走镜像优先
- [ ] 测试覆盖：模拟前 N 个镜像失败、验证能切到第 N+1 个；模拟全部失败、验证抛出中文异常

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
    return {
        "Windows": [
            "https://repo.huaweicloud.com/apache/maven/maven-3/<v>/binaries/apache-maven-<v>-bin.zip",
            "https://mirrors.tuna.tsinghua.edu.cn/apache/maven/maven-3/<v>/binaries/apache-maven-<v>-bin.zip",
            "https://mirrors.aliyun.com/apache/maven/maven-3/<v>/binaries/apache-maven-<v>-bin.zip",
            "https://archive.apache.org/dist/maven/maven-3/<v>/binaries/apache-maven-<v>-bin.zip",  # 末位官网
        ],
        "Darwin":  [...同上 .tar.gz...],
        "Linux":   [...同上 .tar.gz...],
    }
```

#### 2. 镜像源常量集中管理

```python
# 镜像源基址（R1.3 表的常量化表达）
MIRROR_BASES: List[Tuple[str, str]] = [
    ("huaweicloud", "https://repo.huaweicloud.com"),
    ("tuna",        "https://mirrors.tuna.tsinghua.edu.cn"),
    ("aliyun",      "https://mirrors.aliyun.com"),
    ("nju",         "https://mirrors.nju.edu.cn"),
    ("ustc",        "https://mirrors.ustc.edu.cn"),
    ("sjtug",       "https://mirrors.sjtug.org"),
]

# 故障转移参数（R1.4 表的常量化表达）
DOWNLOAD_PROBE_TIMEOUT = 5       # 单 URL 探测超时（秒）
DOWNLOAD_TIMEOUT       = 30     # 单 URL 下载连接超时（秒）
DOWNLOAD_RETRY_PER_URL = 2       # 单 URL 内重试次数
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

#### 4. 版本抓取器改造

`fetch_xxx_versions()` 内部对索引页的请求也走镜像优先 + 末位官网回退，复用 `_get()` 但需扩展为接受 URL 列表：

```python
def _get_first_working(urls: List[str], timeout: int = 10) -> requests.Response:
    """
    按 urls 顺序依次尝试 GET，第一个成功的返回；全部失败抛异常。

    入参 urls: List[str]  待尝试的 URL 列表
    入参 timeout: int      单 URL 超时秒数
    """
    last_exc: Optional[Exception] = None
    for url in urls:
        try:
            return _get(url, timeout=timeout)
        except Exception as exc:
            last_exc = exc
            continue
    assert last_exc is not None
    raise last_exc
```

### R1.8 镜像失效处理

- 镜像源突然下线、目录结构变更属常态，故障转移机制保证最终能从官网拿到包
- 若发现某个镜像源长期失效（连续 N 个版本都 404），应在 R1.3 表中标注并讨论是否替换
- 严禁为绕过故障转移而直接把镜像 URL 改成官网——这违反 R1.1

---

## 后续规则占位

> 后续新增的开发规则以「规则 R2 / R3 / ...」形式追加到本文件，并在「规则索引」中登记。
> 每条规则必须包含：规则描述、适用范围、实施指引、checklist 四节。

- R2: _待定_
- R3: _待定_
