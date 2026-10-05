# Byte Tools — by rgh

A cross-platform desktop GUI tool built with Python + PySide6 that automates the download, extraction and environment-variable configuration of common developer toolchains. Save yourself from tedious manual installation.

> Project: **byte-tools**
> Author: **rgh**
> Platforms: Windows 10/11, macOS 12+, Ubuntu 20.04+
> License: MIT License

---

## 1. Features

- 🖥️ **Cross-platform.** Detects Windows / macOS / Linux (and x64 / arm64) at runtime and picks the correct distribution.
- 📦 **One-click provisioning.** Preloaded with **26 built-in developer components** — the whole pipeline (download → unpack → configure) is automated. See [Supported Components](#2-supported-components) below for the full list.
- ▶️ **One-click launch + open console.** Components that ship their own web console no longer need a manual start command: hit **Launch** on the card and the tool brings it up, then **Open console** takes you straight to its page in the browser (**Jenkins, ActiveMQ and Nacos** today). If the default port is taken it silently moves to a free one and the UI follows the actual port; **Stop** only asks before force-killing and never does it behind your back. State is judged by **whether the port is actually listening** (for Nacos the whole cluster — main port plus its two gRPC ports — must be listening, anything less counts as half-alive), so reopening the tool recognises what is still running — and recognising never executes a start script. ⚠️ The feature is **implemented and guarded by 130 offline regression cases**, but **the end-to-end Windows verification has not been run yet** (it needs you on the machine, a JDK and the components installed, then one `--launch <key> --yes` drill per component). See rule R5 in [DEVELOPMENT.md](./DEVELOPMENT.md).
- 🇨🇳 **China mirror priority.** Since v2.0 the tool ships **11 mainland-China mirror bases** (Huawei Cloud repo / Huawei Cloud mirrors / Tsinghua TUNA / Aliyun / NJU / USTC / BFSU / Tencent Cloud / SJTUG / npmmirror / DaoCloud files) plus **3 GitHub accelerators** (ghproxy.net / gh-proxy.com / ghfast.top). Downloads try China sources first with multi-source failover — the official site is only used after all China sources fail (404 / timeout). Full Chinese logs report which source failed, which one it switched to, and which source finally served the file. Users do **not** need to manually edit URLs to enjoy China-mirror acceleration. Per-component exceptions measured on 2026-09-28: mongodb and postgresql have **no** China mirror (official site only); nacos, bun, powershell and the macOS/Linux source tarballs of git go through the GitHub accelerators (no true mirror exists); nginx ships Windows-only binaries and only the two Huawei Cloud sub-domains carry them (Tsinghua / BFSU / NJU / Aliyun / Tencent all 404); kubectl prefers the DaoCloud `files.m.daocloud.io` proxy; seata is served from the Apache distribution directory via eight China mirrors.
- 🛡️ **Reliable downloads.** Every request carries a custom `byte-tools` User-Agent (several university mirrors return 403 for the default UA), and each finished download is checked against the declared byte count — a "fake 200" empty file from a mirror automatically triggers a switch to the next source instead of leaving a broken archive behind.
- 🔍 **Smart detection.** Checks whether `JAVA_HOME` and friends already exist and are valid; missing/invalid entries are flagged for reconfiguration.
- 🔀 **Multiple versions + active-version switching.** Seven components (JDK / Python / Node.js / Go / Maven / Gradle / Bun) can keep several versions on disk at the same time, each in its own `~/.env-tools/<component>/<component>-<version>/` directory, and one of them is explicitly marked as the **active version**. Clicking **"Configure Only"** ("配置环境变量") makes the selected version active: `XXX_HOME` is repointed and this component's `PATH` entries are collapsed into the single entry of the active version. Any failure mid-switch is rolled back to the pre-switch state, so you never end up with `XXX_HOME` pointing at one version and `PATH` at another. In the version drop-down, a **green check mark** means that version is already installed on disk.
- 🧹 **Safe uninstall and stale-entry cleanup.** Uninstall always targets a directory that really exists on disk. For the seven multi-version components it removes **only the version selected in the drop-down** — its directory and its own `PATH` entries — and leaves the sibling versions untouched; `XXX_HOME` is deleted only when it points at the version being removed. Only when no installed version of that component is left does the cleanup fall back to sweeping the whole component directory (which also clears dead entries left by manual deletions). The "Clean stale PATH entries" button in the title bar removes entries that point into this tool's folder but no longer exist.
- 🛠️ **Environment-variable management.**
    - Windows: writes to `HKCU\Environment` via `winreg` and broadcasts `WM_SETTINGCHANGE` asynchronously (no `setx`, which truncates PATH at 1024 chars).
    - macOS / Linux: appends idempotent `export` blocks (with begin/end markers) to `.zshrc` / `.bash_profile` / `.bashrc` / `.profile`.
- 📊 **Live feedback.** Progress bar with real-time byte counts, cancel support, colour-coded log output (info / ok / warn / error).
- 🎨 **Modern UI.** Frameless custom title bar with a window icon (visible in the taskbar / Alt+Tab), rounded cards with drop shadows, gradient progress bars, hover/press animations, a component search box above the tabs, and a bottom status bar showing "Total components: 26".
- 🚀 **One-stop install.** The "Download & Install" button runs the whole flow in one shot — download → extract → auto-configure env vars → refresh card status — so you no longer need to click "Configure" afterwards.
- 🧠 **Preferences memory.** Remembers the last selected version per component.

---

## 2. Supported Components

> The component count is now **26**, covering language runtimes, shells, build tools, app servers / web servers, databases, containers & orchestration, CI/CD, message queues, service discovery / transaction, search engines, version control and Python distributions.

The UI groups them into **three tabs** along the top, each titled with its component count; a search box above the tabs filters cards by name across all three tabs (the subsections below still describe them by technology category):

| Tab | Count | Rule | Components |
|-----|-------|------|------------|
| **开发环境** (Dev environment) | 10 | Goes on PATH, used to write / compile / package code | JDK, Python, Node.js, Go, Bun, Miniconda, Git, Maven, Gradle, PowerShell 7 |
| **开发软件** (Dev services) | 13 | Runs locally as a project dependency | Tomcat, Nginx, MySQL, MongoDB, PostgreSQL, Elasticsearch, Nacos, Seata, Kafka, RocketMQ, Pulsar, ActiveMQ, RabbitMQ |
| **其它软件** (Other) | 3 | Container / orchestration / CI periphery, not part of coding | Docker, kubectl, Jenkins |

> To re-assign a component, edit the single `COMPONENT_CATEGORY_OF` map in `main.py`; the tabs follow automatically.

### Language Runtimes

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **JDK** | JDK (Temurin) | `JAVA_HOME` | `java -version` | 21 / 17 (LTS) / 11 / 8 (click "Refresh versions" before downloading — see note below the table) |
| **Python** | Python | — (via PATH) | `python --version` | 3.12 / 3.11 / 3.10 / 3.9 |
| **Node.js** | Node.js | `NODE_HOME` | `node --version` | 20 LTS / 18 LTS / 16 |
| **Go** | Go (golang) | `GOPATH` / `GOROOT` | `go version` | 1.24.x / 1.22.x |
| **Bun** | Bun | — (via PATH) | `bun --version` | 1.x |
| **PowerShell 7** | PowerShell 7 | — (via PATH) | `pwsh --version` | 7.6.x / 7.5.x / 7.4.x (portable packages for all three platforms: zip on Windows, tar.gz on Linux / macOS; upstream ships only on GitHub Releases, no true China mirror measured — served via the GitHub accelerators) |

### Build Tools

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Maven** | Apache Maven | `MAVEN_HOME` | `mvn -v` | 3.9.x / 3.8.x |
| **Gradle** | Gradle | `GRADLE_HOME` | `gradle -v` | 8.x / 7.x |

### App Server

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Tomcat** | Apache Tomcat | `CATALINA_HOME` | `catalina version` | 10.1 / 9.0 / 8.5 |
| **Nginx** | Nginx | — (via PATH) | `nginx -v` | 1.31.x / 1.30.x / 1.28.x (⚠️ auto-download is Windows-only: upstream ships a prebuilt Windows zip but only source tarballs for Linux / macOS — use `apt / dnf / yum install nginx` or `brew install nginx` there; measured 2026-09-28: only the two Huawei Cloud sub-domains mirror the zip) |

### Databases

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **MySQL** | MySQL Server | `MYSQL_HOME` | `mysql --version` | 8.0.x (Aliyun / Huawei Cloud mirrors + official) |
| **MongoDB** | MongoDB | — (via PATH) | `mongod --version` | 8.0.x / 8.0.0 (Windows / Linux; no China mirror — official site only) |
| **PostgreSQL** | PostgreSQL | `PG_HOME` | `psql --version` | 17.x / 16.x (Windows only; no China mirror — official site only) |

### Container & Orchestration

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Docker** | Docker Desktop | — (via PATH) | `docker --version` | 27.x / 26.x |
| **kubectl** | Kubernetes CLI | — (via PATH) | `kubectl version --client` | 1.31.x / 1.30.x (all three platforms; primary source is the DaoCloud proxy, official `dl.k8s.io` last; Linux/macOS binaries need `chmod +x`) |

### CI/CD

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Jenkins** | Jenkins | `JENKINS_HOME` | `jenkins --version` | 2.x / LTS |

### Message Queues

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **RabbitMQ** | RabbitMQ | `RABBITMQ_HOME` | `rabbitmqctl version` | 4.0.x / 3.13.x |
| **Apache Kafka** | Apache Kafka | `KAFKA_HOME` | `kafka-server-start.sh --version` | 4.1.x / 3.9.x |
| **Apache RocketMQ** | Apache RocketMQ | `ROCKETMQ_HOME` | `mqadmin version` | 5.x |
| **Apache Pulsar** | Apache Pulsar | `PULSAR_HOME` | `pulsar version` | 3.x |
| **ActiveMQ** | Apache ActiveMQ | `ACTIVEMQ_HOME` | `activemq --version` | 6.3.x / 5.18.x |

### Service Discovery / Transaction

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Nacos** | Nacos | `NACOS_HOME` | `sh startup.sh -m standalone` | 2.x (GitHub accelerator route; no true mirror) |
| **Seata** | Seata | `SEATA_HOME` | `sh seata-server.sh -h` | 2.x (Apache distribution directory, eight China mirrors) |

### Search Engine

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Elasticsearch** | Elasticsearch | `ES_HOME` | `elasticsearch --version` | 9.x / 8.x (Huawei Cloud mirrors + official; mirrors only sync recent releases, older ones fall through to the official site) |

### Version Control

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Git** | Git | — | `git --version` | MinGit for Windows (Huawei Cloud / npmmirror China sources first) / no auto-download on macOS and Linux (upstream ships only a source tarball; the UI points you to apt / dnf / yum / brew) |

### Python Distribution

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Miniconda** | Miniconda | `CONDA_HOME` | `conda --version` | py312 / py311 / py310 |

#### Platform limitations

- **Docker on Windows** — no auto-download. Docker Desktop requires its official installer (WSL2 / Hyper-V integration, service registration and other system-level configuration) and cannot be handled by a simple "download zip → extract" flow. The tool directs you to [docker.com](https://www.docker.com/products/docker-desktop/) to fetch the installer manually. macOS / Linux users get the normal download flow.
- **RabbitMQ on Windows** — no auto-download. RabbitMQ depends on Erlang at runtime; on Windows you must install Erlang first and then the RabbitMQ server, a typical "installer + service registration" scenario that is beyond this tool's "binary download + extract" model. The tool directs you to [rabbitmq.com](https://www.rabbitmq.com/download.html) for the official installer.
- **PostgreSQL on Linux / macOS** — auto-download is Windows-only (EnterpriseDB binary zip). On Linux use your distribution's package manager (apt / yum / dnf); on macOS the project only ships source / Homebrew formulae, so use `brew install postgresql`. The tool shows a Chinese guidance message instead of a broken "auto download".
- **MongoDB on macOS** — no auto-download; Windows and Linux are supported. On macOS use `brew install mongodb-community`.
- **No China mirror for mongodb / postgresql** — measured 2026-09-28: no mainland mirror serves these two, so the official site is their only source and downloads may be slower in China.
- **Nacos / Bun (and the Git source tarballs on macOS/Linux)** — no true China mirror: these are published on GitHub Releases, and the tool accelerates them transparently via [ghproxy.net](https://ghproxy.net/) / [gh-proxy.com](https://gh-proxy.com/) / [ghfast.top](https://ghfast.top/) and falls back to the bare GitHub URL last; the active proxy source is shown in the log. (The previously configured `ghproxy.com` and `gh.idayer.com` were measured dead and have been removed.) **Seata no longer uses this route**: GitHub releases stopped shipping binary assets since 2.1.0, so the tool now downloads it from the Apache distribution directory through eight mainland mirrors (Huawei Cloud ×2 / Tsinghua / Aliyun / NJU / BFSU / Tencent / USTC).
- **kubectl** — supported on all three platforms. The primary download source is the DaoCloud `files.m.daocloud.io` proxy (the `dl.k8s.io` path cannot be rewritten, so it must go through this files proxy), with official `dl.k8s.io` last. On Linux/macOS the result is an extension-less single binary — run `chmod +x` on it before use.

> 💡 After launching the app, click **"⟳ Refresh versions"** to pull the latest version list from each component's official source. If the fetch fails, the tool falls back to the built-in hardcoded list, so it still works offline. For **JDK** this matters: the offline default list only has the official Adoptium URL — the exact file names on the Tsinghua / NJU mirrors are resolved only after a refresh, so click "Refresh versions" first, then download.

---

## 3. Screenshot (ASCII sketch)

```
┌───────────────────────────────────────────────────────────────┐
│  Byte Tools By rgh                            ★ GitHub — ▢ × │
├───────────────────────────────────────────────────────────────┤
│  ┌─ JDK (Temurin) ────────────────────────────────────────┐   │
│  │  ● 2 versions installed · active 17 (17, 11)          │   │
│  │  Version [✓ 17 ▾]  [Install] [Configure] [Uninstall]   │   │
│  │  ████████████████░░░░░  85%                            │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
│  Log:                                                          │
│  [JDK] Downloading https://api.adoptium.net/v3/binary/...      │
│  [JDK] Extracted to /Users/x/.env-tools/jdk/jdk-17             │
│  [JDK] JAVA_HOME set                                           │
└───────────────────────────────────────────────────────────────┘
```

> The sketch is illustrative: every label in the real UI is Chinese
> (`● 已装 2 个版本 · 生效 17（17、11）`, `下载并安装` / `配置环境变量` / `卸载`); the `✓` in front of `17`
> marks a version that is already installed on disk — see [Multiple versions and the active version](#multiple-versions-and-the-active-version).

---

## 4. Quick Start

### 0. One-click Start on Windows (Recommended)

Two Chinese-named one-click scripts live in the project root — **just double-click**, no command-line work needed:

| Script | Purpose |
| --- | --- |
| `一键启动项目.bat` | Prepares the environment, then launches the GUI from source |
| `一键打包exe.bat` | Prepares the environment, then runs PyInstaller to build `dist/byte-tools.exe` |

Both share the same bootstrap flow:

1. Check whether `.venv` is already usable — if it is, the interpreter search is skipped entirely and nothing is downloaded
2. Find a usable Python (**3.10 – 3.14**, matching PySide6's `requires_python`): `py -3.12/3.13/…` → `python`/`python3` → a directory sweep of `%LOCALAPPDATA%\Programs\Python\*` and `%ProgramFiles%\Python*`. When the machine has none, the script installs one itself: `winget` first, then the official installer downloaded in **Huawei Cloud → npmmirror → python.org** order, silently, per-user, no admin, no PATH edit
3. Reuse the existing `.venv`; create or rebuild (`--clear`) it when missing or broken
4. Install `requirements.txt` when needed, mirroring **Tsinghua TUNA → Aliyun → official PyPI**; the build script additionally installs PyInstaller
5. Launch `main.py`, or build with `byte-tools.spec` and report the produced file size and timestamp

```text
double-click 一键启动项目.bat  →  auto-configure + launch GUI
double-click 一键打包exe.bat   →  auto-configure + build dist/byte-tools.exe
```

> 💡 The scripts only touch `.venv` inside the project directory — they never modify the system PATH or your global Python.
> Only when no usable Python exists at all do they install one, into the **current user's** `%LOCALAPPDATA%\Programs\Python` (per-user, no PATH edit, no admin).
> Pass `nopause` when invoking them from another script (skips the final "press any key").

> 🎨 The Windows build carries the project icon (`assets/byte-tools.ico`, derived from `assets/byte-tools.png` at 16–256 px). See [CODE_WIKI.md](./CODE_WIKI.md) 7.4 to regenerate it after a logo change. If Explorer still shows the old icon after an in-place rebuild, that is the Windows icon cache — rename the file or run `ie4uinit.exe -show`.

### Manual setup (for macOS / Linux or customization)

#### Requirements

- Python **3.10 – 3.14**
- A virtual environment is recommended (venv / conda).

#### Clone and install

```bash
git clone https://github.com/yourname/byte-tools.git
cd byte-tools

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

#### Launch

```bash
python main.py
```

The working directory `~/.env-tools/` is created automatically on first launch and stores downloaded archives and extracted components.

---

## 5. Usage

1. Pick the card for the component you want. Its status pill in the top-right corner reports what the system sees:
    - 🟢 `✓ 已配置（PATH）· openjdk version "17.0.10"` — already usable, no action needed
    - 🟠 `● 已下载，未配置` — downloaded but the environment variables are not set
    - 🔴 `○ 未安装` — nothing installed
    - The seven multi-version components (JDK / Python / Node.js / Go / Maven / Gradle / Bun) use their own wording, which states both how many versions are installed and which one is active:
        - 🟢 `● 已装 2 个版本 · 生效 21（21、17）` — the list in brackets is what is on disk (newest first), `生效 21` = the active version
        - 🟠 `● 已装 2 个版本 · 均未生效（21、17）` — versions are installed, but `XXX_HOME` / `PATH` point at none of them
        - 🔴 `○ 未安装` — no version installed at all
        - Once the exact version string of the active version has been probed it is appended: `● 已装 2 个版本 · 生效 21（21、17） · 21.0.4`

   (The pill texts above are quoted verbatim — the UI itself is Chinese-only.)
2. Choose a version from the drop-down.
    - A version with a **green check mark** in front of it is already installed on disk; entries without the mark are not.
3. Click **"Download & Install"** — a one-stop flow that runs automatically:
    - the archive is streamed to `~/.env-tools/<component>/downloads/` (China mirrors first, automatic source failover; cancelable at any time);
    - it is extracted to `~/.env-tools/<component>/<component>-<version>/` (Miniconda runs its silent installer);
    - the corresponding `XXX_HOME` variable is written and the `bin` directory is appended to `PATH`;
    - the card status is refreshed automatically — no need to click "Configure" afterwards;
    - previously installed versions of the same component are **not** deleted, so installing a second one gives you side-by-side versions. Installation repoints the environment variables at the version just installed; click **"Configure Only"** once more if you want the pill to state that version as the active one and this component's `PATH` entries collapsed into a single entry.
    - if the version selected in the drop-down **is already installed on disk**, **"Download & Install" is greyed out** and its tooltip says to uninstall first. This applies to all 26 components, so a finished install can never be overwritten by a second click; to reinstall, uninstall then install again.
4. Click **"Configure Only"** ("配置环境变量") to only write the environment variables:
    - **Multi-version components**: it makes the version selected in the drop-down the **active version** (`XXX_HOME` repointed, this component's `PATH` entries collapsed into that one entry). The button is greyed out when the selected version already is the active one, and its tooltip tells you to pick another version in the drop-down first.
    - **All other components**: it configures the highest version found among the locally extracted directories, without re-downloading (handy when you fetched the archive yourself).
5. All actions are echoed to the log panel (full Chinese logs, including mirror switching / failover).

### Multiple versions and the active version

JDK / Python / Node.js / Go / Maven / Gradle and Bun can keep several versions side by side, one directory per
version: `~/.env-tools/<component>/<component>-<version>/` (e.g. `jdk-21` and `jdk-17` under `~/.env-tools/jdk/`).
The **active version** is the one the operating system actually uses.

- **Green check mark = installed on disk.** A checked version can be uninstalled directly; if you select a version
  that is not installed, the **Uninstall** button is greyed out and its tooltip tells you to pick a checked version first.
- **An installed version always appears in the drop-down.** The mirrors' online version lists change over time, and a
  version you have installed can drop out of them. When that happens the drop-down re-inserts it at its semver position
  with the green check — otherwise such a version could not be selected, switched or uninstalled from the UI at all.
  This synthesis applies only to the seven multi-version components; every other component's list stays exactly as published.
- **"Configure Only" = make the selected version active.** It repoints `XXX_HOME` at that version's directory and
  collapses this component's `PATH` entries into the active version's single entry; entries belonging to other
  components (and your own) are left alone. If any step fails mid-switch, everything already written is rolled back
  from the pre-switch snapshot, so a half-configured state ("`JAVA_HOME` says 21, `PATH` says 17") cannot appear —
  the log line ends with "已开着的终端与 IDE 需重开才会读到新值" once the switch succeeds.
- **Uninstall removes only the selected version.** Just that version's directory and its own `PATH` entries; the
  other versions' directories, variables and entries are untouched, and `XXX_HOME` is deleted only when it points at
  the version being removed. The summary spells out each step, e.g. `已删除安装目录：…jdk-21`,
  `已删除环境变量：JAVA_HOME`, `已从 PATH 移除：…jdk-21\bin`, `PATH 中没有本次卸载范围的条目`.
- **Deleting the active version re-points automatically.** The log shows `生效版本已自动切到 17.0.12` (the highest of
  the remaining versions). When the active version itself survived but this uninstall knocked the environment
  off-line, you instead get `已按生效版本 21.0.4 重建环境变量与 PATH`; removing the last installed version yields
  `已无安装版本，生效登记已清除`.
- **Your own JDK outside this tool is never touched.** When `XXX_HOME` points outside the component folder the
  uninstall neither deletes it nor repoints it — the log records that the variable was kept ("未删除"). The automatic
  re-pointing that follows deleting the active version stays inside this tool's own component folders and never takes
  over a copy you installed elsewhere yourself.
- **Setups that predate this feature keep working.** For components installed before the active version was ever
  recorded, the card infers the active version from the `XXX_HOME` the system already has; clicking
  "Configure Only" once records it explicitly.
- The tool does **not** rewrite `pom.xml` / `build.gradle` in your projects and does not touch IDE SDK settings —
  multi-version setups are handled purely at the "active version" level. If an IDE needs a specific JDK, point its
  SDK setting at that version's directory yourself.

### Applying variables

- **Windows:** any new console window will see the fresh user variables. After every write the tool notifies
  the shell (`Shell_TrayWnd`) by name so it rebuilds its own environment block immediately — terminals opened
  from the Start menu, taskbar or desktop therefore pick up the new value within about a second.
- **If something still shows the old version, a long-lived host process is the cause.** Windows *copies* the
  environment block into each new process, so IDEs and any resident application that opens terminals on demand
  keep handing out the block they had at their own start time. After a switch the log names every terminal
  window older than that switch (pid plus start time) — close those windows entirely. When in doubt, click
  **"🖥 Open verification terminal"** in the title bar: that window is built from the environment Windows
  computes for a brand-new process.
- **`where java` may still resolve to Oracle's javapath first.** Oracle's Java auto-update inserts
  `C:\Program Files\Common Files\Oracle\Java\javapath` into the **system** `PATH`, and Windows puts system entries
  before user entries, so `java -version` can keep reporting that copy even after `JAVA_HOME` points at the version
  this tool installed. Run the self-check below; removing the javapath entry from the *system* `PATH` (requires
  administrator rights) is what makes plain `java` follow the active version.
- **macOS / Linux:**
    ```bash
    source ~/.zshrc     # or ~/.bashrc / ~/.bash_profile / ~/.profile
    ```
    or simply reopen a terminal.

### Verifying

```bash
java -version
mvn -v
python --version
node -v
mysql --version
```

After switching the active version of a multi-version component, run these three lines in a **newly opened** window
(`where` lists matches in `PATH` order — **the first line is the one that actually runs**):

```bat
echo %JAVA_HOME%
where java
%JAVA_HOME%\bin\java -version
```

- `echo %JAVA_HOME%` should print `C:\Users\<you>\.env-tools\jdk\jdk-<active version>`.
- The first line of `where java` should live under that same directory. If it is
  `C:\Program Files\Common Files\Oracle\Java\javapath\java.exe`, Oracle's shim still wins; the third command bypasses
  `PATH` and confirms that the copy this tool installed is fine.

---

## 6. Configuration

### Add / change component versions

Edit `build_components()` inside `main.py`. Each component owns a list of `ComponentVersion` entries. Example — adding JDK 22:

```python
for v in ("22", "21", "17", "11", "8"):
    jdk_versions.append(ComponentVersion(
        version=v,
        url_map=_adoptium_jdk_url(v),
        archive_map={"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.gz"},
    ))
```

### Change the download mirror

> **Since v2.0 the China-mirror-priority + multi-source failover mechanism is built in, so ordinary users do not need to change URLs manually.** The notes below are for users who want to understand the mechanism or do secondary development.

The tool ships **11 mainland-China mirror bases** (Huawei Cloud repo / Huawei Cloud mirrors / Tsinghua TUNA / Aliyun / NJU / USTC / BFSU / Tencent Cloud / SJTUG / npmmirror / DaoCloud files) plus **3 GitHub accelerators** (ghproxy.net / gh-proxy.com / ghfast.top — GitHub Releases have no true mirror, only reverse-proxy acceleration). The download flow follows the **"China sources first → multi-source failover → official site last"** rule:

1. Try the sources in order; on 404 / timeout / connection failure, switch to the next one immediately.
2. Only fall back to the official site after every China source has failed.
3. The whole process is logged in Chinese (which source failed, which one it switched to, which source finally served the file).
4. Two reliability guarantees: every request carries a custom `byte-tools` User-Agent (some university mirrors return 403 for the default UA), and each finished download is verified against the declared byte count — a "fake 200" empty file triggers an automatic switch to the next source rather than leaving a broken archive.

Per-component differences (measured 2026-09-28):

- **mongodb / postgresql** — no mainland mirror at all; the official site is the single source;
- **nacos, bun, powershell, and the macOS/Linux source tarballs of git** — no true mirror; the three GitHub accelerators come first and the bare GitHub URL last;
- **nginx** — only Windows gets a prebuilt official zip, and only the two Huawei Cloud sub-domains mirror it (Tsinghua / BFSU / NJU / Aliyun / Tencent all return 404), with `nginx.org` last; Linux / macOS upstream ships source tarballs only, so those platforms are not auto-downloaded;
- **kubectl** — DaoCloud `files.m.daocloud.io` proxy first (the `dl.k8s.io` path cannot be rewritten, so it must go through this files proxy), official `dl.k8s.io` last;
- **seata** — Apache distribution directory served by eight mainland mirrors (Huawei Cloud ×2 / Tsinghua / Aliyun / NJU / BFSU / Tencent / USTC);
- **jdk** — the offline default list has only the official URL; the exact file names on the Tsinghua / NJU mirrors are resolved only after clicking "⟳ Refresh versions" — **refresh first, then download**.

Net effect: **users inside China no longer need to edit any URL** to enjoy China-mirror acceleration — a big UX upgrade over the old "manually edit the URL function" approach.

> 💡 If a download fails: read the log panel first — it shows which source failed and where it switched. Clicking **"⟳ Refresh versions"** makes the tool re-resolve the mirrors' latest files; then retry.

> 📖 For the full technical implementation of the mirror mechanism (mirror list configuration, failover strategy, how components without a true mirror such as Nacos / Bun are accelerated via the GitHub proxies, and why version index pages still go straight to the official source), see the **R1 China Mirror Priority Rule** section in [`DEVELOPMENT.md`](./DEVELOPMENT.md).

### Change the working directory

Update the constant at the top of `main.py`:

```python
CONFIG_DIR = Path.home() / ".env-tools"
```

---

## 7. FAQ

**Q1. Download stuck at some percentage?**
Likely a slow or failed mirror. Since v2.0 the tool auto-fails over between China mirrors and the official site, so just click **Cancel** and retry — it will try the next source automatically. Check the log panel to see which source failed, and click **"Refresh versions"** to re-resolve the mirrors (no manual URL editing needed). See [Change the download mirror](#change-the-download-mirror) for the mechanism.

**Q2. Env-variable write fails?**
- Windows: relaunch as Administrator if you need system-scope variables. The tool defaults to **user scope**, which usually doesn't require elevation.
- macOS / Linux: make sure your shell rc files are writable.

**Q3. Will my existing `JAVA_HOME` be overwritten?**
Yes — the path written by the most recent install / configure wins, and the new `bin` directory is appended to `PATH` idempotently (the same entry is never duplicated). When you switch the active version of a multi-version component the tool goes one step further: `JAVA_HOME` is repointed at the active version and this component's other `PATH` entries are collapsed away, leaving exactly one entry — entries of other components and anything you keep outside this tool's folders are never touched.

**Q4. `.tar.xz` archives?**
Supported (MySQL Linux distribution uses it).

**Q5. PATH longer than 1024 characters on Windows?**
The tool never calls `setx` (it truncates at 1024 chars). It writes `HKCU\Environment` directly with `winreg` and broadcasts `WM_SETTINGCHANGE`; PATH is edited entry by entry so the process PATH is never overwritten with the user-only portion.

**Q6. Why does Docker on Windows say "no download available"?**
Docker Desktop must use its official installer (it involves WSL2 / Hyper-V integration, service registration and other system-level configuration) and cannot be handled by a simple "download zip → extract" flow. The tool does not auto-download Docker on Windows; it directs you to [docker.com](https://www.docker.com/products/docker-desktop/) to fetch the installer manually. macOS / Linux users get the normal download flow.

**Q7. Why can't RabbitMQ be auto-downloaded on Windows?**
RabbitMQ depends on Erlang at runtime. On Windows you must install Erlang first and then the RabbitMQ server — a typical "installer + service registration" scenario that is beyond the scope of this tool's "binary download + extract" model. The tool directs you to [rabbitmq.com](https://www.rabbitmq.com/download.html) for the official installer.

**Q8. Are downloads slow inside China?**
Mostly no. Since v2.0 the built-in China-mirror-priority rule provides **11 mainland mirror bases** (Huawei Cloud / Tsinghua TUNA / Aliyun / NJU / USTC / BFSU / Tencent Cloud / SJTUG / npmmirror / DaoCloud, etc.) plus **3 GitHub accelerators**. Downloads try them in order and automatically switch to the next one on 404 / timeout, with full Chinese logs (which source failed, which one it switched to, which one finally served the file). Every request also carries a custom User-Agent (some university mirrors block the default one with 403), and finished downloads are byte-count verified so a "fake 200" empty file switches to the next source instead of leaving a broken archive. Ordinary users do not need to configure anything manually. The exceptions: **mongodb and postgresql have no mainland mirror at all** (official site only), and **nacos, bun, powershell and the macOS/Linux source tarballs of git** rely on the GitHub accelerators; **nginx** ships Windows-only zips mirrored solely by the two Huawei Cloud sub-domains. kubectl, previously served only by the official `dl.k8s.io`, now uses the DaoCloud `files.m.daocloud.io` proxy as its first source.

**Q9. After clicking "Download & Install", do I still need to configure env vars manually?**
No. The "Download & Install" button is a **one-stop flow**: download → extract → auto-write `XXX_HOME` / `PATH` → refresh the card status. Once the flow finishes, the component is considered installed; you do not need to click "Configure Only" afterwards. That button is only for the case where you have already downloaded the archive manually and just want to write the environment variables.

**Q10. I switched the active version, but `java -version` in my terminal still shows the old one.**
First click **"🖥 Open verification terminal"** in the title bar: that window is started with the environment block Windows builds for a *new* process, so the version you see there is what any freshly opened terminal will report. If it is correct and your old window is not, that window simply predates the switch (see step 1 below).
Check these three things:
1. **The window was not reopened** — a switch only reaches newly started processes. Close and reopen terminals; fully restart IntelliJ IDEA / Eclipse / VS Code. After a successful switch the log names every terminal window still older than that switch (pid plus start time), so you can tell which window to close; entries marked as an administrator window cannot be reached by this tool's refresh notification at all — only closing the whole window and reopening it works. Windows Terminal tabs and IDE terminals inherit the host process' environment, so closing a tab is not reopening a terminal — a fresh tab even prints the PowerShell banner again while still carrying the host's old environment.
2. **Oracle's javapath wins.** If the *system* `PATH` contains `C:\Program Files\Common Files\Oracle\Java\javapath`, it is searched before user variables, so plain `java` still runs that copy. Run `where java` from the [Verifying](#verifying) section — the first line is what actually executes — and use `%JAVA_HOME%\bin\java -version` to confirm the copy this tool installed is healthy.
3. **The switch itself failed.** A log line containing "切换失败" means the tool rolled back from the pre-switch snapshot, so nothing effectively changed; click "Configure Only" again. If that log also says the rollback was not fully successful, it lists exactly which item could not be restored and what value it should have — fix those by hand and retry.

**Q11. Will uninstalling one version break the other installed versions of the same component?**
No. For the multi-version components, uninstall removes only the directory of the version selected in the drop-down plus that version's own `PATH` entries; sibling versions' directories, variables and entries stay as they are, and `XXX_HOME` is cleared only when it points at the version being deleted. If the removed version was the active one, the tool immediately makes the highest remaining version active and says so in the log (`生效版本已自动切到 …`). A version that is not on disk has no green check mark in the drop-down and cannot be uninstalled — the button is greyed out.

---

## 8. Notes & caveats

- Official download URLs may change over time. If a link 404s, update the URL for that version in `main.py`.
- Some components (e.g. MySQL) require additional post-install steps such as `mysqld --initialize`. This tool only covers **download + extraction + env-var configuration**.
- Prefer a virtual environment to avoid polluting your system Python.

---

## 9. Project layout

```
byte-tools/
├─ main.py              # entry point (UI + logic)
├─ 一键启动项目.bat      # One-click launcher: auto-provisions .venv + deps, then starts the GUI
├─ 一键打包exe.bat       # One-click builder: auto-provisions env + PyInstaller, then builds the exe
├─ pyinstaller_no_wmi.py # Build entry: keeps PyInstaller (and its child processes) from querying WMI
├─ requirements.txt     # dependency list
├─ byte-tools.spec  # PyInstaller build spec
├─ 同步Gitee产物.sh       # Gitee Release sync (Linux/macOS/CI; writes GitHub links only, no cross-ocean binary push; fast-fail + idempotent + verify), called by release.yml
├─ 同步Gitee产物.bat      # Windows LOCAL edition (double-click friendly) - it does upload the real artifacts, fine from mainland China
├─ README.md             # Chinese documentation
├─ README_EN.md          # English documentation (this file)
├─ DEVELOPMENT.md        # developer docs (incl. the R1 China-mirror-priority rule)
├─ CODE_WIKI.md          # code wiki (class / module / function index)
├─ LICENSE               # MIT License
├─ .gitignore            # Git ignore rules
├─ .github/
│   └─ workflows/
│       └─ release.yml            # three-platform auto build & release (+ Gitee sync)
└─ assets/               # static resources (screenshots, donation QR codes, etc.)
```

---

## 10. License

This project is released under the **MIT License**. Copyright (c) 2026 **rgh**.

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

See also <https://opensource.org/licenses/MIT>.
