# 镜像源实测报告（2026-09-28）

> 范围：byte-tools v2.0 全部 24 个组件的下载源配置。
> 方法：对代码实际生成的**每一个** URL 发真实 `GET`（带 `User-Agent: byte-tools`），记录状态码、
> `Content-Length` 与响应体首 4~8 字节魔数（zip→`PK\x03\x04`、tar.gz→`\x1f\x8b`、exe→`MZ`）。
> 判定「源可用」= 状态码 200 **且** 魔数是归档包 **且** 字节数 ≥ 4096。只看状态码不算数。

---

## 1. 一句话结论

24 个组件全部改到「大陆源在前 + 多源故障转移 + 末位官网」，实测覆盖 **212 个组件×平台×版本组合、1127 个 URL**（git 摘掉 Unix 占位源后重跑的最终矩阵）；
除 6 行「镜像站没同步该旧版本、只有官网出包」（正常，故障转移自动兜底）和 jdk 离线默认清单（设计如此）外，
**每一行都至少有一个大陆源实测 200**；4 套离线测试 **72 项全绿**；文档（DEVELOPMENT / CODE_WIKI / README / README_EN）已按实测结果同步。

本轮收尾另按你的决定改了一处行为：**git 在 macOS/Linux 不再给下载源**（上游只有 `git/git` 源码包，解压后不能直接用），
`_git_urls()` 现在只返回 `Windows` 一个键，其余平台走 `unsupported_platform_hint` 引导 apt / dnf / yum / brew。

---

## 2. 两个藏在下载层的缺陷（这是「镜像看起来配了却下不动」的真因）

| 缺陷 | 症状 | 修法 |
|------|------|------|
| 高校镜像屏蔽默认 UA | 清华 TUNA、北外 BFSU、中科大对 requests 默认 UA 与浏览器 UA 一律 **403**，日志表现为「所有源都失败」 | 所有出网请求固定携带 `HTTP_UA = {"User-Agent": "byte-tools"}`（`_get()` 与 `DownloadWorker._try_download()` 两处） |
| 假 200（软 404） | `repo.huaweicloud.com/anaconda/<任意路径>` 301 到软 404 HTML 页、`mirrors.huaweicloud.com/mongodb.org/...` 回「200 + 无 Content-Length + 空体」，旧代码把错误页当下载成功，留下坏包直到解压才炸 | 新增 `DOWNLOAD_MIN_VALID_BYTES = 4096`，下载完校验实际字节数与声明的 `Content-Length`，不达标就删 `.part` 换下一个源 |

顺带纠正了一次**自己的误判**：首轮探测没带 UA，把中科大的 `apache/*`、`jenkins` 当成「假 200 空体」删掉了。
带 UA 复测证明它们是真包，于是 ustc 重新纳入 maven / tomcat / kafka / rocketmq / pulsar / activemq / seata / jenkins
这 8 个构造器的镜像列表（位置在所有大陆源之后、官网之前）。
`ustc/golang/` 则确认**不是镜像**——它只是 302 跳回 `dl.google.com`，本机对 `dl.google.com` TLS 握手失败，所以 go 仍然只用阿里 + 南大两家。

---

## 3. 各组件源数量（由 `build_components()` 默认清单实测导出）

「大陆源」列含 GitHub 反向代理加速器（`ghproxy.net` / `gh-proxy.com` / `ghfast.top`，均为大陆运营）。

| 组件 | 平台 | 大陆源 | 总源 | 源顺序（末位必为官网） |
|------|------|--------|------|------------------------|
| jdk (Temurin) | Win/Mac/Linux | 0 | 1 | `api.adoptium.net`（**例外**，见第 4 节；点「刷新版本」后自动补清华 + 南大） |
| maven | Win/Mac/Linux | 7 | 8 | 华为 repo → 清华 → 阿里 → 南大 → 北外 → 腾讯 → 中科大 → `archive.apache.org` |
| tomcat | Win/Mac/Linux | 7 | 8 | 同上七家 → `archive.apache.org` |
| mysql | Windows | 2 | 3 | 阿里 → 华为 → `cdn.mysql.com` |
| mysql | Linux | 2 | 3 | 阿里 → 华为（glibc2.12 包名）→ `cdn.mysql.com`（glibc2.28 包名） |
| mysql | macOS | 4 | 5 | 阿里/华为 × `macos11`/`macos12` → `cdn.mysql.com`（只挂 `macos14`） |
| python | Win/Mac/Linux | 2 | 3 | npmmirror / 华为 mirrors → `python.org/ftp` |
| node | Win/Mac/Linux | 5 | 6 | 清华 → 南大 → 北外 → 华为 → npmmirror → `nodejs.org` |
| git | Windows | 6 | 7 | 华为 mirrors → 华为 repo → npmmirror → 3 个加速器 → `github.com` |
| git | Mac/Linux | — | 0 | **不给 URL**（上游只有源码 tar.gz），界面按 `unsupported_platform_hint` 提示 apt / dnf / yum / brew |
| conda | Win/Mac/Linux | 4 | 5 | 清华 → 南大 → 北外 → 中科大 → `repo.anaconda.com` |
| go | Win/Mac/Linux | 2 | 3 | 阿里 → 南大 → `go.dev` |
| gradle | Win/Mac/Linux | 4 | 5 | 华为 repo → 华为 mirrors → 南大 → 腾讯 → `services.gradle.org` |
| bun | Win/Mac/Linux | 1 + 3 加速器 | 5 | npmmirror → 3 加速器 → `github.com` |
| docker | Mac/Linux | 8 | 9 | 华为×2 → 清华 → 阿里 → 南大 → 北外 → 中科大 → 腾讯 → `download.docker.com` |
| mongodb | Win/Linux | 0 | 1 | `fastdl.mongodb.org`（**例外**） |
| postgresql | Windows | 0 | 1 | `get.enterprisedb.com`（**例外**） |
| kubectl | Win/Mac/Linux | 1 | 2 | DaoCloud `files.m.daocloud.io` → `dl.k8s.io` |
| jenkins | Win/Mac/Linux | 8 | 9 | 华为×2 → 清华 → 北外 → 南大 → 阿里 → 腾讯 → 中科大 → `get.jenkins.io` |
| rabbitmq | Mac/Linux | 2 + 3 加速器 | 6 | 华为×2 → 3 加速器 → `github.com` |
| kafka | Win/Mac/Linux | 7 | 8 | 华为 → 清华 → 阿里 → 南大 → 北外 → 腾讯 → 中科大 → `archive.apache.org` |
| rocketmq | Win/Mac/Linux | 7 | 8 | 同 kafka 七家 → `archive.apache.org` |
| pulsar | Win/Mac/Linux | 7 | 8 | 同 kafka 七家 → `archive.apache.org` |
| activemq | Win/Mac/Linux | 7 | 8 | 同 kafka 七家 → `archive.apache.org` |
| nacos | Win/Mac/Linux | 3 加速器 | 4 | 3 加速器 → `github.com` |
| seata | Win/Mac/Linux | 8 | 9 | 华为×2 → 清华 → 阿里 → 南大 → 北外 → 腾讯 → 中科大 → `archive.apache.org` |
| elasticsearch | Win/Mac/Linux | 2 | 3 | 华为 repo → 华为 mirrors → `artifacts.elastic.co` |

---

## 4. 凑不出 2 个大陆源的组件（已在 DEVELOPMENT.md R1.1 登记例外，不是偷懒）

| 组件 | 实测证据 |
|------|----------|
| mongodb | `repo.huaweicloud.com/mongodb/` 只有 C++ 驱动源码包，二进制包名一律 404；`mirrors.huaweicloud.com/mongodb.org/` 带 UA 回 401；清华 `/mongodb/` 是 apt/yum 仓库；阿里只有 `mongodb-upstart/`。fastdl 二进制树国内无人同步 |
| postgresql | 清华没有 `/postgresql/`（404）；华为 / 阿里 / 南大的 `/postgresql/` 只有 `latest/`、`source/` 源码 tarball（如 `postgresql-18.2.tar.gz`），`v17/`、`17.6/` binaries 树 404；EDB 根本不发布 Linux binaries |
| kubectl | 阿里 / 清华 / 华为的 `kubernetes/` 只同步 apt、yum 仓库，`.../release/v.../bin/...` 一律 404；GitHub Release 不发这个二进制，所以 gh 加速器无效。DaoCloud `files.m.daocloud.io/dl.k8s.io/...` 是唯一大陆源（实测 200 / 58 MB） |
| jdk | 镜像目录（清华 `/Adoptium/<major>/jdk/<arch>/<os>/`、南大 `/adoptium/...`）只暴露带 build 号的确切文件名，而官方 `latest-binary` 是按月滚动的重定向。默认离线清单不许联网，只能给官网单源；点「刷新版本」列目录后才会补成多源 |
| nacos / bun / rabbitmq | 制品在 GitHub Releases，大陆没有真镜像，只有反向代理加速器；bun 另加 npmmirror 一个大陆源 |
| git（Mac/Linux） | 上游只有 `git/git` 源码 tar.gz，解压后没有可执行文件（需自行 configure + make）——不是「凑不到镜像」而是**根本没有可安装的制品**，所以不给 URL，改走 `unsupported_platform_hint` |

**为什么要留例外而不凑数**：假的镜像地址不会加速，只会让每次下载先白撞几轮 404/403 才轮到真正可用的源。

---

## 5. 平台限制（不是下载失败，是官方根本没有这个包）

| 组件 | 限制 | 界面行为 |
|------|------|----------|
| docker | 不提供 Windows 静态包 | `unsupported_platform_hint` 引导安装 Docker Desktop |
| rabbitmq | Windows 版依赖 Erlang，没有解压即用的包 | 引导去官网下安装器；Linux/Mac 走 generic tar.xz |
| postgresql | EDB 不发 Linux binaries；macOS 用 brew | 只给 Windows 平台键，其余平台给提示 |
| mongodb | 官方不发 macOS community binary | 只给 Windows / Linux（Linux 包名必须带发行版段，如 `ubuntu2204`） |
| git | Mac/Linux 只有 `git/git` **源码 tar.gz**，解压后需要自己编译 | `_git_urls()` 只返回 `Windows` 键；Mac/Linux 点「安装」输出 `unsupported_platform_hint`，引导 `sudo apt install git` / `sudo dnf install git` / `brew install git` |
| jdk / kafka / rocketmq / pulsar / activemq / maven / tomcat / jenkins | 高校镜像只同步最近几个版本，旧版本会 404 | 由故障转移自动兜到华为 repo（保留全量历史）或 archive 官网 |

---

## 6. 测试结果

离线规格测试（可反复运行，不联网）：

```bash
cd /e/file/test/byte-tools
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe bt_mirror_spec_tests.py        # 27 项
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe /c/Users/E5430/AppData/Local/Temp/test_old_component_sources.py   # 18 项
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe /c/Users/E5430/AppData/Local/Temp/bt_dl_tests.py                    # 5 项
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe /c/Users/E5430/AppData/Local/Temp/bt_repro_tests.py                 # 22 项
```

```
bt_mirror_spec_tests.py        27 tests   OK   （全 24 组件 URL 配置规格：末位官网 / 大陆源数 / 已死源不得复现 / ustc 就位 / git 只在 Windows 出 URL）
test_old_component_sources.py  18 tests   OK   （首批 8 组件多源改造）
bt_dl_tests.py                  5 tests   OK   （DownloadWorker 故障转移 + 字节校验 + UA）
bt_repro_tests.py              22 tests   PASS （安装/卸载/PATH/探测回归）
py_compile main.py                       OK
```

联网全量实测（2026-09-28 收尾复跑，已含 git 改动）：

- **212 个组件×平台×版本行、1127 个 URL 全部 GET 过一遍**，逐行结果存于
  `C:\Users\E5430\AppData\Local\Temp\matrix_allv3.txt`；默认清单矩阵在 `bt_matrix_final3.txt`（67 行，每行一个组件×平台）。
- 每行的**第一个大陆源都实测 200 + 真包**（默认清单里除 jdk / mongodb / postgresql 三个登记例外）。
- 只有末位官网出包的 6 行，是镜像站没同步这些旧版本，属正常（故障转移自动兜底）：
  `mysql 8.0.37`（Win/Mac/Linux）、`elasticsearch 8.15.0`（Win/Mac/Linux）。
  上一轮 `elasticsearch 8.15.0 / Windows` 那次官网连接中断已消失，本轮直接 `200 / 450M`；
  此前该行的 `git 2.45.2 Mac/Linux` 两行随源码包占位一起被摘掉了。
- 新加的 ustc 源做过**端到端整包下载**校验（不只看头几字节）：
  maven 9.4 MB → zip 可解析 110 个条目；kafka 133.6 MB → gzip；jenkins 101.1 MB → zip 1021 个条目。
  注意这些站点对大文件常回 `Transfer-Encoding: chunked`（无 `Content-Length`），所以可用性判定用的是
  「实际累计字节数 ≥ 4096」，与 `DownloadWorker` 内部的校验方式一致。

---

## 7. 复跑方法（以后镜像变了怎么自查）

1. 先跑离线测试：`bt_mirror_spec_tests.py`（仓库根目录，27 项，1 秒内出结果）。
2. 再跑全量实测：`C:\Users\E5430\AppData\Local\Temp\bt_probe_allv.py`（GET 全部 URL，约 3 分钟，输出逐行矩阵）。
3. 判定「某镜像可用」的四条标准：状态码 200 **且** 魔数是归档包 **且** 字节数 ≥ 4096 **且** 带 `User-Agent: byte-tools`。
   缺任何一条都可能把 403 屏蔽或软 404 页当成可用源。
4. 结论有变化时，先改 `DEVELOPMENT.md` 的 R1.3 / R1.5 表，再改 `main.py`，最后同步 `CODE_WIKI.md` 与两份 README。

---

## 8. 文档同步情况

- `DEVELOPMENT.md`：R1.1 例外表、R1.3 11 家基址表（含 M5 中科大真实覆盖面 + 「已实测证伪禁止写入」清单）、R1.4 参数表（`HTTP_UA` / `DOWNLOAD_MIN_VALID_BYTES`）与流程图、R1.5 两张组件清单（逐行附实测结论）、R1.6 checklist（新增组件必须 GET + 魔数校验）、R1.7 常量样例、R1.8 两类假成功与判定标准。
- `CODE_WIKI.md`：常量表、URL 构造器表（逐组件源清单与个数）、DownloadWorker 的 UA 与字节校验说明。
- `README.md` / `README_EN.md`：11 家大陆基址 + 3 加速器、逐组件例外说明、平台支持矩阵修正、FAQ「更换下载镜像」重写。
- 全部文件保持 **LF** 行尾（脚本改写时以 `newline=""` 读写，已复核 CR 字节数为 0）。

---

## 9. 三个问题的落定情况

| 问题 | 你的决定 | 处理结果 |
|------|----------|----------|
| git 在 macOS/Linux 的源码包占位条目 | 摘掉 | 已摘。`_git_urls()` 只返回 `Windows`；`build_components()` 里给 git 加了 `unsupported_platform_hint`（apt / dnf / yum / brew）；新增 2 条规格测试锁住这个行为 |
| 要不要打 `v1.0.6` 发版 | 不发 | 未执行任何打包 / 打标签动作，改动只留在工作区 |
| `__pycache__` / `dist` 要不要进 `.gitignore` | 加 | **无需改动**：`.gitignore` 第 4 行已有 `__pycache__/`、第 11 与 138 行已有 `dist/`，本来就被忽略（`git status` 不会列出它们） |

按约定我不执行 git 命令，请你自己在 `E:\file\test\byte-tools` 下跑：

```bash
# 1) 先看改了哪些文件（__pycache__ / dist 不会出现在 untracked 里，因为已被忽略）
git status
git diff --stat

# 2) 核对 .gitignore 确实覆盖了这两个目录（可选，只读验证）
git check-ignore -v __pycache__ dist

# 3) 暂存（bt_mirror_spec_tests.py 与 MIRROR_REPORT.md 是本轮新增文件，要一起提交）
git add main.py bt_mirror_spec_tests.py MIRROR_REPORT.md DEVELOPMENT.md CODE_WIKI.md README.md README_EN.md

# 4) 提交
git commit -m "fix(mirrors): 按实测补齐中科大源并摘掉 git 的 Unix 源码包占位"
```
