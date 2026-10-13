# 组件集成实施计划（2026-10-12）

**来源**：线上文档《查看README并推荐常用组件》，即「本工具现状 + 千问 + DeepSeek」三份清单合并去重后的候选池，按共识度分 P0 / P1 / P2 / P3。

**起点**：dev 分支，可见组件 **47**（+1 隐藏 erlang），`LAUNCH_KEYS` = 11，最新 tag v1.2.1。

**已确认的三条决策**：

1. 第 0 步先收尾当前未提交的 4 个组件（Kotlin / GraalVM / Rust / Redis），再开新批；
2. 只做 **Windows 实测**，其它平台不给 URL 并写 `unsupported_platform_hint`（与现有 47 个一致，符合 R13「不冒充能」）；
3. 每个组件的下载源必须跑 `tools/bt_bench_sources.py` 实测后排序，不套既有惯例。

---

## B0 · 收尾当前四个（Kotlin / GraalVM / Rust / Redis）— 0 新增

**现状核实（2026-10-12）**：代码侧已完整 —— URL 构造 + fetcher + `FETCHERS` 登记 + `build_components()` + `COMPONENT_CATEGORY_OF`；Redis 另登记了 `LAUNCH_OF`（6379 / `stop_kind="pid"` / `port_writeback="cli_flag"`）；Rust 新增了 `extract_archive` 的 `.msi` 分支（`msiexec /a` 管理性提取）。

原先预判的三处红灯**已经全部修好**（实测全绿）：`bt_mirror_spec_tests` 的 `MAINLAND_MARKERS` 已含 `rsproxy.cn`、`SINGLE_SOURCE_EXCEPTION` 已含 `rust: 1`、`OFFICIAL_HOST` 已登记四个；`bt_launch_tests` 的 `LAUNCH_KEYS` 已是 11 个；`bt_multiversion_tests.EXPECTED_WIN_SUBDIR` 也已同步。

**所以 B0 只剩文档与工作区卫生**，必须独立提交，否则后续每批都叠在它的 diff 上。

| 动作 | 文件 / 位置 |
|---|---|
| 组件数 43→47、可装配 26→30、启停 10→11；四个 Tab 成员表补 Kotlin / GraalVM / Rust；「一键启停」补 Redis；明细表补四行 | `README.md:81/92/132/136-139/342/458` |
| 同上的英文版 | `README_EN.md:9/83/85/94/344` |
| R1.5 标题 26→30，两张镜像台账表各加 4 行（Redis 那行必须写明「非官方 redis-windows 构建」）—— `main.py:4271` 的注释写着"台账见 R1.5"，目前是**唯一真实欠账** | `DEVELOPMENT.md:185-205`（R1.5） |
| 43/26/17 与四个 Tab 计数、`LAUNCH_OF` 成员 | `CODE_WIKI.md:31/198/608/737/741/840/952/969` |
| 删除 16 个实测临时文件 | `.probe*.py` `.probe*.out` `.drill_redis.py` `.extract_rust_msi.ps1` `.read_rust_msi.ps1` |
| 补探针忽略规则（否则下批再堆一轮） | `.gitignore` |
| `tools/bt_readme_shot.py` 随本批提交并登记进工具清单 | `CODE_WIKI.md:198` |

**验收**：定向跑 `bt_component_category_tests bt_download_only_tests bt_mirror_spec_tests bt_new_components_tests bt_launch_tests bt_multiversion_tests`；`git status --short` 只剩已跟踪文件的 M。

---

## 主线批次（47 → 81）

### B1 · 打通「单二进制 / 无 XXX_HOME」新路径 —— +2 → 49

**组件**：`protoc`、`uv`

这俩是同一条新路径的两个变体：`uv` 的 zip 顶层 **0 个目录**（直接 `uv.exe` + `uvx.exe`）→ `path_subdir=""`；`protoc` 顶层是 **2 个并列目录** `bin/` + `include/` → `path_subdir="bin"`。

现有 kubectl 走的是「单文件拷贝早退分支」（`extract_archive` 在到达底部 `entries` 判定之前就返回了），**没走到底部那个"单顶层即根"判定** —— 所以「zip 形态的无 HOME 组件」是真正没验过的组合，这正是本批要打通的。fetcher 可照 `fetch_kotlin_versions`（`main.py:4115`）改，源走 `_gh_accelerated`。

### B2 · 首个 `needs=("jdk",)` 启停服务 —— +1 → 50

**组件**：`ZooKeeper`

选它不选 Sentinel 的理由：Apache dist 有七家大陆镜像，天然满足「≥2 大陆源」；有 `conf/zoo_sample.cfg` 可练 `conf_copy`；端口簇是教科书式的 `2181 + 2888/3888`；且 `zkServer.cmd` 是包装器，要练 `port_lookup` 停止路径。

本批的成果不是 1 个组件，而是**可复制的启停类 SOP**。必实测链路：测速 → 下包 grep 配置抄端口（教训 2.2：别从文档推）→ 真跑一次 `zkServer.cmd` 看它认什么参数（教训 2.1）→ 定 `port_writeback="conf_copy"` → `--launch zookeeper --yes` 演练量耗时 → `startup_timeout = 实测 × 2` 向上取整到 10s。

**门禁**：没有真机演练输出，不许扩 `LAUNCH_KEYS`。

### B3 · P0 批量：运行时 / 构建 / 小工具 —— +8 → 58

**组件**：`dotnet-sdk`、`deno`、`pnpm`、`cmake`、`ninja`、`helm`、`sqlite`、`duckdb`

全部无启停、zip / 单二进制、不依赖 JDK，形态高度统一，适合参数化批量登记 —— 是摊薄单件成本的主力批。

- **`dotnet-sdk` 本批风险最高**（唯一可能需要 `installer_mode` 的 P0）→ 排本批第一个做：优先走 zip 便携包；若 zip 不可用、必须静默安装器，就拆出本批单独处理。
- 需实测定源：`sqlite`（sqlite.org，可能有华为云 / 清华镜像）、`dotnet-sdk`（微软 CDN）；其余 6 个都是 GitHub release → 直接用 `_gh_accelerated`。

### B4 · 启停第一批：单二进制服务 —— +3 → 61

**组件**：`etcd`（2379/2380）、`consul`（8500）、`minio`（9000/9001）

形态一致（单 exe + CLI flag 改端口 + 数据目录外移 + `stop_kind="pid"`），可一次演练会话串起来跑，摊掉环境准备成本。这批也是「大陆源不足」风险最集中的一批。

**预警**：`.probe*.out` 实测 MinIO 的 GitHub release 直链 **404**（三个加速器全 404）→ 必须换 `dl.min.io` 重测；仍拿不到就放弃，不许"先登记再说"。`consul` 的 `releases.hashicorp.com` 不是 GitHub，没有加速器可用。

> **2026-10-12 更新**：MinIO 的结论后来被推翻 —— 真实可下的是 release 资产上的
> `minio.windows-amd64.RELEASE.2025-09-07T16-13-09Z.exe`（实测 206 + `MZ`、
> 113,115,136 B，完整下载逐字节一致）。「直链 404」只对 `dl.min.io` 与**最新那个
> 0 资产的 tag**成立（见 `DEVELOPMENT.md` R1.5 的 MinIO 行）。

### B5 · 单二进制 CLI 全家桶 —— +11 → 72

**组件**：`jq`、`yq`、`ripgrep`、`fd`、`fzf`、`bat`、`eza`、`zoxide`、`trivy`、`k9s`、`docker-compose v2`

唯一一批可 95% 机械化的。`docker-compose` 走 DaoCloud `files.m.daocloud.io`（属单源档次）。

`fzf` / `zoxide` 有 shell 集成需求 —— **本工具不做 shell 集成**，只在 `data_note` 写明「仅保证命令可用，shell 插件请自行配置」。

测试走**参数化**（一张 `CLI_SPECS` 表 + `subTest`），不写 11 个 Spec 类。

### B6a · 只下载类 GUI —— +9 → 81

**组件**：`DBeaver`、`RedisInsight`、`Another Redis Desktop Manager`、`MongoDB Compass`、`pgAdmin`、`MySQL Workbench`、`HeidiSQL`、`Postman`、`Bruno`

放最后：`download_only=True` 受 `bt_multiversion_tests` 豁免、不需真机演练，成本最低、对其它断言冲击最小。

**最容易漏的一处**：`bt_download_only_tests.test_every_artifact_url_is_a_measured_host` 的域名白名单 —— 每加一个新产品就要加一个实测过的域名。

---

## 后续队列（本轮不排期，按前六批节奏决定）

- **B6b（+10）**：Notepad++、7-Zip、Wireshark、MobaXterm、Cursor、Zed、Trae、Rider、RustRover、Ollama
- **B7 · 语言与构建遗留（+4）**：PHP（仅 Windows zip，注意 VC 运行库）、Apache Ant、JMeter（需 JDK）、FFmpeg
- **B8 · 启停第二批（+16）**：Sentinel、Memcached、NATS、Prometheus、Grafana、OpenSearch、Zipkin、Jaeger、MariaDB、ClickHouse、EMQX、Apollo、XXL-JOB、SkyWalking、Loki、Caddy / Traefik / GitLab Runner
- **B9 · 长尾**：Ruby（**待 .7z 决策**，见风险 1）、Elixir、Dart、Scala / Groovy / Clojure

---

## 单组件最小落地清单（每批内逐个照跑）

| # | 步骤 | 性质 |
|---|---|---|
| 1 | `tools/bt_bench_sources.py` 测全部候选源（状态码 + 魔数 + 字节数 + Range 吞吐） | **必实测**，不许套惯例 |
| 2 | 按实测速度排序源列表，官方末位；GitHub 产物直接用 `_gh_accelerated` | 机械 |
| 3 | 写 `_xxx_urls(v)` + `_xxx_cv(v)`（多源模式必须 `url_map={}` 显式空字典） | 机械 |
| 4 | 写 `fetch_xxx_versions()`，失败 raise；**版本号 / 资产名从 release 资产名读，不按规律拼** | 半机械 |
| 5 | 未实测平台不给 URL + 写 `unsupported_platform_hint`（原因 + 替代做法，R13 硬要求） | **必逐个写** |
| 6 | `FETCHERS` 登记 | 机械 |
| 7 | `tools/bt_archive_layout_audit.py --only <key>` 定 `path_subdir` | **必实测**（单二进制最容易猜错） |
| 8 | `build_components()` 追加 `Component(...)` | 机械 |
| 9 | `COMPONENT_CATEGORY_OF` 加一行 —— **漏了直接 KeyError，主窗口构造不出来** | 机械 |
| 10 | 启停类才做：`LAUNCH_OF[key] = LaunchSpec(...)` + 真机演练 | **必实测** |
| 11 | 护栏用例（每组件 Spec 类 或 参数化表） | 半机械 |
| 12 | 四张断言表 + 总数 + README / EN / DEVELOPMENT R1.5 / CODE_WIKI | 机械 |
| 13 | `pyinstaller_no_wmi.py --noconfirm byte-tools.spec` 重新打包 —— 改源码 ≠ 用户拿到新程序 | 机械 |

---

## 每批必改的四张断言表（漏一个就红）

1. `bt_component_category_tests.py:36` `EXPECTED_MEMBERSHIP`（四个 Tab 严格相等）
2. `bt_download_only_tests.py:122` `test_visible_component_count_is_N`（全仓库唯一写死可见数的地方，函数名跟着改）
3. `bt_multiversion_tests.py:1034` `EXPECTED_WIN_SUBDIR`（非 download_only 的每个都要）或 `:1050` `NOT_AUDITABLE`
4. `bt_mirror_spec_tests.py:129/143/170` `SINGLE_SOURCE_EXCEPTION` / `OFFICIAL_ONLY_EXCEPTION` / `OFFICIAL_HOST`（新镜像域名还要加 `:69` `MAINLAND_MARKERS`）
5. 启停类额外：`bt_launch_tests.py:41` 的 `LAUNCH_KEYS` 白名单

---

## 大陆源不足的四档处置规则（B4 起固化为纪律）

1. **≥2 个**实测可用大陆镜像 → 按实测速度排序，常规登记
2. **恰好 1 个** → `SINGLE_SOURCE_EXCEPTION[key] = 1`，注释写清哪几家 404
3. **0 个** → 非 GitHub 产物进 `OFFICIAL_ONLY_EXCEPTION`（该断言要求大陆源恰好 0 个，以后真找到镜像会红，逼人带实测来改表），并在 `data_note` 写明"官方源直连、国内可能慢"
4. **官方直连本机都拿不到** → 换源；换不了 → **放弃该组件**

> ⚠ 四档规则要按**产物**判，不按"域名"。MinIO 就是反例：`dl.min.io` 全线 410
> 看着像第 4 档，但 release 资产上是真包（113 MB / `MZ` / 逐字节核对）⇒ 第 1 档处理。

---

## 风险与对策

### 1. `extract_archive` 无 `.7z` 分支（Ruby）→ 本轮不加

现状支持 zip / tar.gz / tar.xz / msi（`msiexec /a`）/ 单文件（`.exe` / `.war` / 无扩展名），其余 `raise RuntimeError`。

加 `.7z` 的代价：要么引入 `py7zr`（破坏「零第三方依赖 + 单文件打包」的前提，要改 `byte-tools.spec` 与产物体积），要么依赖本机 `7z.exe`（给"能用"加了一个未声明的前置）；收益只服务 Ruby 一个 P1 组件。

**对策**：Ruby 改用 RubyInstaller2 的 **exe 安装器**（走已有的 `installer_mode` + `installer_args`，Miniconda 是先例），或降级到"不做清单"。

### 2. 单二进制的四坑

- **坑 A**：同一组件不同版本 / 平台的 zip 布局可能不一致，而 `path_subdir` 只有一个值 → fetcher 里只收布局一致的资产名（照 `fetch_kotlin_versions` 严格匹配 `kotlin-compiler-{ver}.zip` 的做法），且**每个版本**都过一次布局审计。
- **坑 B**：`env_var=None` 时 `Component._detect_by_home_dir` 直接返回 False，检测**完全依赖 PATH 里的 `exec_name`** → `exec_name` 必须给，否则卡片永远显示未安装。
- **坑 C**：卸载 / 切版本的 PATH 定位靠 `_external_bin_dir(comp, home)`，无 `env_var` 也能工作（kubectl 已验证）。
- **坑 D（规模相关）**：单二进制组件若 `version_probe=True`，探测阶段会真跑 `<exec> --version`。B5 之后要在启动耗时里复测。

### 3. 启停类的演练成本怎么摊

每批最多 2~3 个，且同批内**共享演练形态**：B2 = cmd 包装器 + JDK；B4 = 单 exe + CLI flag；B8 = `java -jar`。

硬约束复述：`startup_timeout = 实测 × 2` 向上取整到 10s；端口绝不自动平移；`console_path ≠ health_path`；判"端口空闲"必须亲自 bind。

### 4. 47 → 80+ 对界面与启动性能

- **网格不会破**：`grid_columns_for()` 按窗口宽度算列数、`chunk_visible()` 按行切，数量增长只加行数。
- **真问题 1 · 无虚拟滚动**：`main.py` 一次性为全部组件建 `ComponentCard`。80+ 张卡的实例化 + 每张卡的 `detect()`（读注册表 + stat 磁盘）会线性吃掉冷启动时间。→ **B3 之后（约 58 个）实测一次冷启动耗时，超过 1.5s 再考虑按 Tab 懒建卡，本轮不提前优化。**
  > 2026-10-12 实测：源码模式 `import main` 326 ms + `MainWindow()` 构造 1.7 s，
  > 已超 1.5 s 阈值，但真正的用户侧瓶颈是 onefile 解压（已改 onedir，见 `DEVELOPMENT.md` R19）。
- **真问题 2 · 抓取错峰间隔写死**：`QTimer.singleShot(i * 150, ...)`，N=26 时最后一路 3.9s 启动；**N=80 时是 12s**，而刷新按钮要等全部归零才恢复 → 观感是"刷新卡 12 秒"。→ **B3 前后改成按 N 归一（如 `min(150, 4000 // N)`），或只对打 GitHub API 的那批错峰。**
- **真问题 3 · GitHub 匿名额度 60 次/小时/IP**：80 个组件里若 30 个是 GitHub fetcher，一次启动就吃掉一半额度。现有 `version_cache.json`（TTL 24h）能挡住重复启动，但首次仍会全打 → B5 的 CLI 批考虑"只缓存、不主动刷新"，或把它们的 fetcher 合并成一次 API 调用。

### 5. 其它能力缺口

| 缺口 | 影响候选 | 结论 |
|---|---|---|
| `.7z` | Ruby | 不加（见风险 1） |
| `.tar.zst` / `.tar.bz2` | 少数 CLI | 不加；选资产时避开 |
| 多文件单二进制（uv.exe + uvx.exe） | uv | **无需改码**：zip 顶层 0 目录 → 返回 `extract_to` |
| `installer_mode` 自定义目标目录 | .NET SDK | 走 zip 便携包避开 |
| 需 JDK 的启停 | ZooKeeper / Sentinel / SkyWalking / XXL-JOB | B2 打通一次（`needs=("jdk",)` + `min_java_major`，Nacos 是先例） |
| 端口簇 >2 | ZooKeeper 2181/2888/3888 | `port_offsets` + `extra_ports` 已支持 |
| 数据目录外移 | MinIO / etcd / Consul | `data_dir_env` 已支持 |
| Windows 服务注册 | MariaDB | **不做** |

### 6. 明确不做（写进平台例外 / 不做清单，别硬做）

驱动或内核级（CUDA 驱动、Docker Desktop、WSL、VirtualBox、VMware、Parallels）· 需服务注册（RabbitMQ on Windows 走前置 Erlang）· 只有源码包的（Nginx / PHP / PostgreSQL / Git on Linux/macOS）· 需 pip/conda 环境（Airflow、MLflow、Jupyter）· 依赖 Docker（Kong、APISIX、Harbor）· Hadoop / Spark / Flink / TiDB / Neo4j / SonarQube / Nexus。

---

## 验收命令（每批统一）

```bash
cd /e/file/test/byte-tools

# 1) 定向（每批必跑，约 1-2 分钟）
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost QT_QPA_PLATFORM=offscreen \
  .venv/Scripts/python.exe -m unittest \
  bt_component_category_tests bt_download_only_tests bt_mirror_spec_tests \
  bt_multiversion_tests bt_new_components_tests bt_grid_layout_tests bt_launch_tests
# 本机有 Windows 系统级代理，不加这套 env 会出 502 假红

# 2) 全量（约 845 条 / 18 分钟，后台跑；只在每批收尾与发版前跑。跑前先冻结产品代码）
.venv/Scripts/python.exe -m unittest discover -p "bt_*_tests.py"

# 3) 实测三件套（每批的必实测步骤）
.venv/Scripts/python.exe -u tools/bt_bench_sources.py
.venv/Scripts/python.exe -u tools/bt_archive_layout_audit.py --only <key>
.venv/Scripts/python.exe -u tools/bt_real_machine_drill.py --launch <key> --yes

# 4) 交付
.venv/Scripts/python.exe -u pyinstaller_no_wmi.py --noconfirm byte-tools.spec
```

---

## 关键文件

| 用途 | 路径 |
|---|---|
| 主程序 | `main.py`（`Component` / `ComponentVersion` / `LaunchSpec` / `extract_archive` / `_gh_accelerated` / `FETCHERS` / `COMPONENT_CATEGORY_OF` / `LAUNCH_OF` / `build_components`） |
| 分类断言 | `bt_component_category_tests.py:36` |
| 可见总数（唯一写死处） | `bt_download_only_tests.py:122` |
| 归档布局表 | `bt_multiversion_tests.py:1034` / `:1050` |
| 镜像三表 | `bt_mirror_spec_tests.py:69` / `:129` / `:143` / `:170` |
| 启停白名单 | `bt_launch_tests.py:41` |
| 护栏范本 | `bt_new_components_tests.py` |
| 流程规范 | `docs/ONBOARDING_NEW_COMPONENT.md` §6 / §6之二 |
| 镜像台账 | `DEVELOPMENT.md:185`（R1.5） |