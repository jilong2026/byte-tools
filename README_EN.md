# ByteTools (字节工具箱)

<p align="center">
  <img src="assets/byte-tools.png" alt="ByteTools icon" height="132" width="132"/>
</p>

<p align="center">
  Set up a complete development environment on a fresh Windows / macOS / Linux machine<br/>
  <b>with a few clicks</b>.   <b>61 components</b> are handled end to end (download → unpack → set environment variables),<br/>
  <b>26 dev tools</b> get official installer direct links (download only), and <b>15 services</b> can be started and stopped in one click.
</p>

<p align="center">
  <a href="https://github.com/jilong2026/byte-tools/releases/latest"><img src="https://img.shields.io/github/v/release/jilong2026/byte-tools?color=orange" alt="release"/></a>
  <img src="https://img.shields.io/badge/python-3.10%20to%203.14-blue.svg" alt="python"/>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg" alt="platform"/>
  <img src="https://img.shields.io/badge/GUI-PySide6-brightgreen.svg" alt="pyside6"/>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="license"/>
</p>

<p align="center">
  <img src="assets/byte-tools-pt.png" alt="Main window" width="860"/>
</p>

> Chinese is the authoritative version of this document ([README.md](README.md)); this English file follows the same chapter structure. In-code comments and logs are in Chinese by design.

---

## Contents

- [What problem it solves](#what-problem-it-solves)
- [Download and run](#download-and-run)
- [Highlights](#highlights)
- [Getting started in 30 seconds](#getting-started-in-30-seconds)
- [Supported components](#supported-components)
- [Platform support and exceptions](#platform-support-and-exceptions)
- [In depth](#in-depth)
- [UI tour](#ui-tour)
- [Running from source](#running-from-source)
- [Configuration](#configuration)
- [Building and releasing](#building-and-releasing)
- [FAQ](#faq)
- [Stack · Layout · Contributing](#stack--layout--contributing)
- [License](#license)

---

## What problem it solves

Every new machine, and every time you onboard someone, the same five steps repeat: **find the right download page → match OS and CPU architecture → unpack it somewhere "correct" → set environment variables → open a new terminal and verify**. That is at least half an hour per machine, and it multiplies with every machine.

ByteTools collapses those five steps into one click: pick a version, press **Install**, and it does the rest — writing **every step to a Chinese log** (which mirror it used, why it switched, which variable it wrote).

It does exactly three things: **download, unpack, configure environment variables**. It does not touch your `pom.xml` / `build.gradle`, does not configure IDE SDKs, and does not initialize databases.

---

## Download and run

**No Python required. No source checkout required. Double-click and go.**

Grab the build for your system from the [Releases page](https://github.com/jilong2026/byte-tools/releases/latest):

| System | File | How to run |
|--------|------|------------|
| Windows 10 / 11 (x64) | [`ByteTools-windows-x64.zip`](https://github.com/jilong2026/byte-tools/releases/latest/download/ByteTools-windows-x64.zip) | Unzip, then double-click `ByteTools\ByteTools.exe` (onedir mode, zero-extraction startup) |
| macOS (Apple Silicon) | [`ByteTools-macos-arm64.zip`](https://github.com/jilong2026/byte-tools/releases/latest/download/ByteTools-macos-arm64.zip) | Unzip, then double-click `ByteTools.app` |
| Linux (x64) | [`ByteTools-linux-x64`](https://github.com/jilong2026/byte-tools/releases/latest/download/ByteTools-linux-x64) | `chmod +x` and run it |

> Intel Macs: since v1.0.5 there is no Intel universal build (GitHub removed Intel runners). Use [Running from source](#running-from-source).

Your OS may block the app on first launch. That is a "nobody paid for a code signature" signal, not a malware signal:

- **macOS**: "cannot be opened because the developer cannot be verified" → System Settings → Privacy & Security → **"Open Anyway"**, or strip the quarantine attribute with `xattr -cr ByteTools.app`.
- **Windows**: Defender / SmartScreen "unrecognized app" → **"More info → Run anyway"**.
- **Linux**: double-click does nothing → `chmod +x ByteTools-linux-x64 && ./ByteTools-linux-x64`.

---

## Highlights

- **One codebase, three platforms**: detects OS and CPU architecture (on Apple Silicon JDK resolves to aarch64, Node to arm64).
- **61 components installed end to end**: download → unpack → `XXX_HOME` + `PATH`, ready to use immediately.
- **26 dev tools, download only**: IDEs / database clients / terminals get official installer direct links, with a live version list, downloaded to a directory of your choosing (remembered between runs; you can open the folder afterwards). **This tool does not unpack them, does not set environment variables for them, and does not run installers on your behalf** — licence acceptance and install steps are yours. Where upstream ships both an installer and a portable archive (IDEA / PyCharm / CLion / WebStorm / GoLand / DataGrip / VS Code / DBX), the button reads **"Download ▾"** so you can pick which one, sizes shown.
- **15 services start and stop in one click**: Tomcat, Nginx, ActiveMQ, RocketMQ, Kafka, Elasticsearch, Seata, Nacos, RabbitMQ, Jenkins, Redis, etcd, Consul, Apache ZooKeeper, MinIO. Port conflicts are handled by a documented policy and explained in a confirmation dialog (ports are never silently shifted — shifting them breaks external clients). If "Stop" cannot stop cleanly, the tool only asks whether to force-kill; it never kills behind your back. Liveness is judged by **the whole port cluster listening** (Nacos main port + gRPC, Kafka 9092+9093, RocketMQ namesrv+broker). Running services are still recognised after you close and reopen the tool, and status detection **never executes a start script**. Protocol-port components that cannot be viewed in a browser (Kafka / RocketMQ / RabbitMQ) get a status page served by the tool itself: state, ports, how to connect, credentials and log paths — and it **flips to "stopped" on refresh once the service is gone**, instead of a notice that forever claims success. All of them were verified one by one on a real Windows machine through the full cycle (download/install → start → cluster ports listening → protocol probe, e.g. `rabbitmqctl status`, Kafka `BrokerApiVersions` → stop → ports released). **macOS and Linux are not yet verified on real hardware** (see rule R5 in `DEVELOPMENT.md`).
- **Prerequisite runtimes installed automatically**: components that need a JDK (Jenkins / Nacos / Kafka / RocketMQ / ActiveMQ / Tomcat / Seata) will download a suitable JDK first, then continue starting; same for the Erlang/OTP that RabbitMQ needs (27.x / 26.x matched to the RabbitMQ version). You never have to prepare dependencies yourself.
- **China-first mirrors with multi-source failover**: 11 mainland mirror bases and 3 GitHub accelerators, tried mainland-first, falling back to the official origin last, all narrated in the log. **No URL editing needed** (a few components genuinely have no mainland mirror — see [Platform support and exceptions](#platform-support-and-exceptions)).
- **Multiple coexisting versions + an explicit "active version"**: all 59 installable components can keep several versions side by side (opened to everything on 2026-06-06), and you name which one is active. A failed switch rolls back automatically, so you never end up with "variable points to A, `PATH` points to B". A **green tick** in the version dropdown means that version is already installed on disk.
- **Take over installations you put there yourself — and revert with one click**: JDK / Maven / Node etc. already on the machine, outside this tool's directory, can be discovered and made active (the scan is read-only and each candidate is confirmed by actually running its version command). Before touching your system settings the original text is snapshotted, and it can be written back verbatim. Five hard gates (original snapshot / minimal edit / critical-entry validation / re-verification / revertibility) must all pass or the operation is rolled back.
- **Uninstall removes only the version you selected**: other versions' directories, variables and `PATH` entries are untouched; deleting the active version triggers an automatic re-pick. The title bar's **"🧹 Clean PATH"（清理残留 PATH）** button clears dead entries that point into this tool's directory but no longer exist.
- **Update check that never replaces itself**: the version chip in the title bar doubles as a status light (six states, see [UI tour](#ui-tour)). When a newer release exists, one click downloads it to your chosen directory — **it never renames or overwrites the running program**, and it uploads nothing about you.
- **Download reliability**: every request carries a dedicated `byte-tools` User-Agent (several university mirrors 403 the default UA), and the byte count is verified after the download, so a "fake 200 empty file" from a mirror triggers a source switch rather than leaving you a broken archive.
- **Live version lists + a 24-hour cache**: version lists are fetched from official APIs/indexes at startup and cached on disk for a day (this saves GitHub's anonymous rate budget); when a fetch fails the tool quietly falls back to its built-in list, so it stays usable offline.
- **Search and filtering**: 87 components do not need page-by-page browsing — the search box above the tabs fuzzy-matches names and keys across all of them and groups hits by category; version dropdowns accept typing (`21`, `3.12`, `LTS`).
- **Environment variables without `setx`**: Windows writes the registry directly via `winreg` (`setx` truncates at 1024 characters), edits `PATH` entry by entry, and notifies Explorer by name after every write; macOS / Linux write a marked, idempotent block into your shell rc files.
- **UI**: frameless custom window, cards that re-flow into columns based on window width (toggle "▦ Grid / ☰ List"), gradient progress bars, status capsules, colour-coded Chinese log overlay (collapsed by default, auto-opens on warn/error with an unread counter), window icon visible in the taskbar and Alt+Tab, and remembered per-component version choices.
- **It says so when a platform is unsupported**: two components have no portable form on Windows (`Docker`, `Pulsar`). The card states why and what to do instead — it will not install something that cannot run and leave you guessing.

---

## Getting started in 30 seconds

1. Open the tool. Five tabs (Start-stop / Server components / Dev environment / Dev tools / Agent clients) list every component; each card's top-right corner is its **current state**:

   | State | Meaning |
   |---|---|
   | 🟢 `✓ Configured (PATH) · openjdk version "17.0.10"` | Already findable by the system; nothing to install (the exact version is filled in asynchronously) |
   | 🟠 `● Downloaded, not configured` | Archive is local, environment variables are not set yet |
   | 🟢 `● 2 versions installed · active 21 (21, 17)` | All 59 installable components use this form: parenthesised list = what is on disk (newest first); `active 21` = the one in use |
   | 🟠 `● 2 versions installed · none active (21, 17)` | Versions installed, but the system's `XXX_HOME` / `PATH` points to none of them |
   | 🔴 `○ Not installed` | Nothing installed |

   When the active version's exact string is detected it is appended: `● 2 versions installed · active 21 (21, 17) · 21.0.4`.

2. Pick a version in the dropdown (type to filter; a green tick means it is already on disk).
3. Press **Install**. The tool then: streams the archive to `~/.env-tools/<component>/downloads/` (mainland mirrors first, automatic source switching, cancellable) → unpacks to `~/.env-tools/<component>/<component>-<version>/` (Miniconda runs its silent installer) → writes `XXX_HOME` and appends `bin` to `PATH` → refreshes the card. **Old version directories are not deleted**, so installing a second version gives you coexisting versions.
4. Press "📋 Log" on the search bar to watch every step.

Two button-availability rules: **when the selected version is already installed, "Install" is disabled** (hover explains "uninstall first if you want to reinstall" — this protects an installed directory from being overwritten); **when the selected version is already the active one, "Switch" is disabled** (hover says to pick another version first).

Verify in a **newly opened** terminal:

```bash
java -version
mvn -v
python --version
node -v
```

---

## Supported components

**182 in total**: **80 installable end to end** + **102 download-only** (102 = 38 GUI tools + 64 agent clients; 15 of the 61 additionally support one-click start/stop). The tabs carry their counts in their titles:

| Tab | Count | Members |
|-----|-------|---------|
| Start-stop | 16 | Tomcat, Nginx, RabbitMQ, Kafka, RocketMQ, ActiveMQ, Nacos, Seata, Elasticsearch, Jenkins, Redis, NATS Server, etcd, Consul, Apache ZooKeeper, MinIO |
| Dev environment | 42 | JDK, Python, Node.js, Go, Bun, Miniconda, Git, Maven, Gradle, PowerShell 7, Kotlin, GraalVM, Rust, Dart, protoc, uv, .NET SDK, SQLite, jq, pnpm, Deno, Ninja, DuckDB CLI, CMake, ripgrep, fd, bat, eza, zoxide, fzf, yq, Apache Ant, Elixir, Scala CLI, Bazelisk, Just, Task, Oxlint, Biome, Nushell, Starship, GitHub CLI |
| Server components | 22 | MySQL, MongoDB, PostgreSQL, Pulsar, Docker, kubectl, Trivy, k9s, Docker Compose v2, Helm, Caddy, Traefik, Apache JMeter, Terraform, OpenTofu, Argo CD CLI, Prometheus, VictoriaMetrics, k6, Pulumi, Istio CLI, Talos Linux CLI |
| Dev tools | 38 | IntelliJ IDEA, PyCharm, CLion, WebStorm, GoLand, DataGrip, VS Code, DBX, WindTerm, WeChat DevTools, Eclipse IDE, Apipost, Apifox, HBuilderX, Android Studio, Visual Studio, Navicat, DBeaver, HeidiSQL, Bruno, RedisInsight, Another Redis Desktop Manager, MongoDB Compass, pgAdmin 4, MySQL Workbench, Postman, Notepad++, Wireshark, GitKraken, SourceTree, Insomnia, Beekeeper Studio, Obsidian, Zettlr, Yaak, Vim (gVim), CC-Switch, CodexAppManager |
| Agent clients | 64 | Cursor, ZCode, Claude Code, Codex CLI, opencode, OpenHands, Cherry Studio, Goose, Qwen Code, Crush, Kiro, Jan, OpenClaw, Hermes Agent, Gemini CLI, Aider, Ollama, LM Studio, GPT4All, AnythingLLM, LobeHub, GitHub Copilot CLI, ima (Tencent), Kilo Code, Wave Terminal, Msty Studio, Mistral Vibe, Kimi Work, QoderWork CN, Trae, Trae CN, Qoder IDE, Tencent CodeBuddy, Zed, Cline, Reasonix, ChatGPT, Claude Desktop, Google Gemini, Google Antigravity, Windsurf (Devin), Marvis (Tencent), Wukong (DingTalk), Kimi, Kimi Code, MiniMax Code, StepFun Desktop, Nano AI, Tiangong AI, DeepSeek Harness, Metaso, LobsterAI (Youdao), AutoClaw (Zhipu), Baidu DuMate, OpenWorker, Orkas, WorkBuddy, Doubao, Tencent Yuanbao, Tongyi Qianwen, Tongyi Lingma, ERNIE (Wenxiaoyan), ChatGLM, iFlytek Spark |

> **This tab has two tiers.** 34 of the 40 have a measured official direct link, so the card's main
> button says **Download**. The other 6 (Windsurf (Devin), Claude Desktop, Google Antigravity,
> Google Gemini, Metaso, iFlytek Spark) have no stable link we could register, so the button says
> **"Open official site"** — it opens the vendor's download page in your browser and you download
> there. **Neither tier downloads, installs, or runs an installer for you.**

> To regroup: edit the one line per component in `COMPONENT_CATEGORY_OF` in `main.py`. The Start-stop tab needs no registration — membership is derived from the launch whitelist `LAUNCH_OF`.

Details by technical category below (environment variable, detection command, default available versions). **The default versions are only the offline fallback**: at startup the tool pulls live lists from official sources and "⟳ Refresh versions" forces a re-fetch.

### Language runtimes

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| JDK (Temurin) | `JAVA_HOME` | `java -version` | 21 / 17 (LTS) / 11 / 8. Exact filenames on TUNA / NJU mirrors carry a build number — **refresh before downloading** |
| Python | — (PATH) | `python --version` | 3.12 / 3.11 / 3.10 / 3.9. Linux / macOS: see [exceptions](#platform-support-and-exceptions) |
| Node.js | `NODE_HOME` | `node --version` | 20 LTS / 18 LTS / 16 |
| Go (golang) | `GOPATH` / `GOROOT` | `go version` | 1.24.x / 1.22.x |
| Bun | — (PATH) | `bun --version` | 1.x |
| PowerShell 7 | — (PATH) | `pwsh --version` | 7.6.x / 7.5.x / 7.4.x. Portable packages exist for all three platforms; upstream ships only via GitHub Releases and has no real mainland mirror, so the GitHub accelerators are used |
| Kotlin compiler | — (PATH) | `kotlinc -version` | 2.4.x. One `kotlin-compiler-<v>.zip` for all three platforms (the compiler is a JVM artifact), unpacking to `kotlinc/`; GitHub Releases only, via the accelerators |
| GraalVM (CE) | `GRAALVM_HOME` | `java -version` | 25.x. **Deliberately not `JAVA_HOME`** — sharing it with JDK (Temurin) would make each component overwrite the other's active version. Assets are per-platform and the version number lives in the **asset name** (the tag `graal-…` is not the version) |
| Rust | — (PATH) | `rustc --version` | 1.99.x / 1.98.x / 1.97.x. **Windows only**: upstream stopped shipping the `.exe` installer and the combined tar.xz has no unified `bin/`, so the official MSI is **administratively extracted** (`msiexec /a`, no elevation, no registry writes). ⚠ A linker is still required: without VS Build Tools `rustc` compiles but cannot link (and Git for Windows' `link.exe` impersonates the MSVC linker, producing a baffling `link: extra operand`). See [exceptions](#platform-support-and-exceptions) |
| .NET SDK | — (PATH) | `dotnet --version` | 10.0.x. The official **zip portable package** (not the installer) — `dotnet.exe` sits right at the unpack root; the version list is read from Microsoft's `release-metadata` JSON and registers the **SDK version** (10.0.401), not the release it belongs to. Microsoft CDN is the only source (no mainland mirror carries its tree). |
| Deno | — (PATH) | `deno --version` | 2.x. Single-file runtime, `deno.exe` at the zip root; released only on GitHub Releases, so it goes through the GitHub accelerators. |

### Build tools

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| Apache Maven | `MAVEN_HOME` | `mvn -v` | 3.9.x / 3.8.x |
| Gradle | `GRADLE_HOME` | `gradle -v` | 8.x / 7.x |
| protoc (Protobuf compiler) | — (PATH) | `protoc --version` | 36.x. The zip holds two side-by-side directories, `bin/` + `include/`; only the Windows channel has been measured per R1 (npmmirror carries a real mirror) — Linux / macOS packages exist upstream but are unmeasured, see [exceptions](#platform-support-and-exceptions) |
| CMake | — (PATH) | `cmake --version` | 4.4.x. The package wraps everything in `cmake-<v>-windows-x86_64/`, and `cmake.exe` lives in **`bin/`** one level further in — not at that root. The archive-layout audit caught this; copying the neighbouring row would get it wrong. |
| Ninja | — (PATH) | `ninja --version` | 1.13.x. Single-file zip, `ninja.exe` at the root. |

### Application servers and web services

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| Apache Tomcat | `CATALINA_HOME` | `catalina version` | 10.1 / 9.0 / 8.5 |
| Nginx | — (PATH) | `nginx -v` | 1.31.x / 1.30.x / 1.28.x. Only Windows has official prebuilt zips — see [exceptions](#platform-support-and-exceptions) |
| Caddy | — (PATH) | `caddy --version` | 2.11.x. Single-file web server with automatic HTTPS; GitHub-only, via the accelerators. **Download and PATH only** — start it yourself with `caddy run`; this tool does not register start/stop for it. |
| Traefik | — (PATH) | `traefik version` | 3.7.x. Cloud-native reverse proxy, same: download only. ⚠ It accepts the `version` **subcommand**; `--version` prints the help and exits non-zero, so the probe command is written as measured. |

### Databases

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| MySQL Server | `MYSQL_HOME` | `mysql --version` | 8.0.x (Aliyun / Huawei Cloud mirrors + official). **After unpacking you still must run `mysqld --initialize`** — this tool does not initialise databases |
| MongoDB | — (PATH) | `mongod --version` | 8.0.x / 8.0.0 (Windows / Linux; macOS has no portable binary) |
| PostgreSQL | `PG_HOME` | `psql --version` | 17.x / 16.x (auto-download on Windows only) |
| SQLite (CLI) | — (PATH) | `sqlite3 --version` | 3.5x. Official `sqlite-tools-win-x64-<six-digit>.zip` (3.54.0 → `3540000`, with the year in the path); `sqlite3.exe` at the unpack root. **sqlite.org is the only source** (TUNA 404; the Huawei `sqlite/` page answers 200 but serves a 12 KB portal shell — a fake source). |
| DuckDB CLI | — (PATH) | `duckdb --version` | 1.5.x. Single-file analytical database, `duckdb.exe` at the root; GitHub Releases only. |

### Key-value cache

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| Redis | — (PATH) | `redis-server --version` | 8.10.x. **Windows only, and a community build** (`redis-windows`), not official — upstream ships source only and `download.redis.io`'s tar.gz yields no Windows executable; the card says so explicitly. Supports one-click start/stop: data lands in `~/.env-tools/redis-data`, and the command line uses Redis defaults (listens on 127.0.0.1 only, no password). This tool does not change `bind` and does not set `requirepass` |

### Containers and orchestration

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| Docker Desktop | — (PATH) | `docker --version` | 27.x / 26.x (no auto-download on Windows; the official installer is required) |
| kubectl | — (PATH) | `kubectl version --client` | 1.31.x / 1.30.x (all three platforms; DaoCloud proxy preferred; on Linux / macOS the file is extensionless — `chmod +x` it) |
| Helm | — (PATH) | `helm version` | 4.3.x. Kubernetes package manager. ⚠ Its GitHub release holds only `.asc` / `.sha256sum` sidecars — the real binary lives on `get.helm.sh` (which is also where the version pointer `helm-latest-version` comes from). |
| k9s | — (PATH) | `k9s version` | 0.51.x. Kubernetes terminal UI, single binary, via the accelerators. |
| Docker Compose v2 | — (PATH) | `docker-compose version` | 5.x. Standalone compose binary. **It installs and lands on PATH, but actually running it still needs a working Docker engine** (Docker Desktop has no portable form on Windows — see the Docker card). It is registered because `docker-compose version`-style self-checks need no engine. First source is DaoCloud's GitHub proxy tree (measured byte-identical to upstream). |
| Trivy | — (PATH) | `trivy --version` | 0.75.x. Container / filesystem vulnerability scanner, single binary, via the accelerators. |

### CI / CD

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| Jenkins | `JENKINS_HOME` | `jenkins --version` | 2.x / LTS |

### Message queues

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| RabbitMQ | `RABBITMQ_HOME` | `rabbitmqctl version` | 4.0.x / 3.13.x (needs Erlang/OTP; the tool matches 27.x / 26.x to the RabbitMQ version) |
| Apache Kafka | `KAFKA_HOME` | `kafka-server-start.sh --version` | 4.1.x / 3.9.x |
| Apache RocketMQ | `ROCKETMQ_HOME` | `mqadmin version` | 5.x |
| Apache Pulsar | `PULSAR_HOME` | `pulsar version` | 3.x (the main command is a POSIX shell script; not supported on Windows) |
| ActiveMQ | `ACTIVEMQ_HOME` | `activemq --version` | 6.3.x / 5.18.x |
| NATS Server | — (PATH) | `nats-server --version` | 2.15.x. Lightweight messaging server, single binary; GitHub Releases only. **Download only** — start/stop is not registered. |

### Service discovery / distributed transactions

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| Nacos | `NACOS_HOME` | `startup.sh` / `startup.cmd` | 2.x (published on GitHub Releases, no real mirror → GitHub accelerators) |
| Seata | `SEATA_HOME` | `seata-server.sh -h` | 2.x (Apache distribution directory, eight mainland mirrors) |
| Apache ZooKeeper | — (PATH) | detection looks at `bin/zkServer` | 3.9.x (seven Apache mirrors + the official CDN). **Supports one-click start/stop**: the official package ships only `zoo_sample.cfg`, so the tool generates a `zoo.cfg` copy under `~/.env-tools/zookeeper-data/conf` and edits `clientPort` / `dataDir` there (the install directory is never touched); it **spawns java directly instead of the vendor `zkServer.cmd` wrapper** (that wrapper forces `<home>\conf\zoo.cfg` as the first argument, and terminating it leaves an orphan java holding the port). Needs a JDK and installs one automatically if absent. |
| Consul | — (PATH) | `consul version` | 2.0.x. **Supports one-click start/stop**: `consul agent -dev` form, HTTP port handed over on the command line (`-http-port`, no config file), console at `/ui`, health check at `/v1/health`. Only `releases.hashicorp.com` (not GitHub, so no accelerator applies); direct connections from the mainland measured slow. |
| etcd | — (PATH) | `etcd --version` | 3.7.x. **Supports one-click start/stop**: single exe with the port on the command line, client 2379 and peer 2380 are judged as one cluster; data lives in `~/.env-tools/etcd-data`, no config file written. |

### Search engine

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| Elasticsearch | `ES_HOME` | `elasticsearch --version` | 9.x / 8.x (Huawei Cloud mirror + official; mirrors sync only recent releases, older ones are covered by failover) |

### Version control

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| Git | — | `git --version` | MinGit on Windows (Huawei Cloud / npmmirror first); no auto-download on macOS / Linux (upstream ships source only — use apt / dnf / yum / brew) |

### Python distributions

| Component | Env var | Detection | Default versions |
|---|---|---|---|
| Miniconda | `CONDA_HOME` | `conda --version` | py312 / py311 / py310 (silent installer) |
| uv (Python package/env manager) | — (PATH) | `uv --version` | 0.13.x. The zip has no directory at all — `uv.exe` / `uvw.exe` / `uvx.exe` sit at the root. **This tool only guarantees the `uv` command is on PATH**; shell integration and the Python versions uv manages live outside its directory. Windows-only for the same reason |


### Command-line utilities (single binary, unpack and go)

None of these has an `XXX_HOME` concept — the tool unpacks them into `~/.env-tools/<component>/<component>-<version>/` and puts that directory on `PATH`; uninstall removes exactly that entry. Every version list is matched **strictly against the release asset name** (a single release usually also holds `.sha256`, `.sbom` and arm builds, so guessing by suffix installs the wrong thing).

| Component | Detection | Default version | Notes |
|---|---|---|---|
| jq | `jq --version` | 1.8.x | Bare exe (not a zip). JSON processor. |
| yq | `yq --version` | 4.5x | Also a bare exe — the jq of YAML. |
| ripgrep (`rg`) | `rg --version` | 15.x | Recursive search; its release tag has **no `v` prefix** (pinned separately — guessing it yields 404). |
| fd | `fd --version` | 10.x | Filename search. |
| fzf | `fzf --version` | 0.74.x | Fuzzy finder. **Only the command is guaranteed** — configure the shell key bindings yourself. |
| bat | `bat --version` | 0.26.x | `cat` with syntax highlighting. |
| eza | `eza --version` | 0.23.x | A modern `ls`. |
| zoxide | `zoxide --version` | 0.10.x | Fuzzy `cd`. Also no shell integration (its `init` belongs in your rc file). |
| pnpm | `pnpm --version` | 12.x | Node package manager. **Binary only** — it does not touch `corepack` or global `node_modules`; run `corepack enable` yourself if you want it to take over `npm`. |
| uv | `uv --version` | 0.13.x | Python package / environment manager, see [Python distributions](#python-distributions). |
| protoc | `protoc --version` | 36.x | See [Build tools](#build-tools). |
### About those 26 "Dev tools"

They are GUI applications; this tool's only job is to fetch the official installer into the directory you choose. Their cards therefore have **only a version dropdown and a download button** — no green tick, no disk scan, no switch or uninstall buttons, no unpacking, no environment variables.

- Everything with a live version list has a machine-readable official source (JetBrains data endpoints, VS Code's `update.code.visualstudio.com`, GitHub Releases, vendor JSON). Where none exists (WeChat DevTools / Eclipse / Visual Studio / Navicat) the tool **does not invent a "latest version"**: lists are built-in and refresh skips them — direct downloads still work.
- **Commercially licensed software** (the JetBrains family, Navicat, some Visual Studio editions) is offered as official direct links **without any licence**; whether and where to install is your decision (the same note is in the "Download" button tooltip).

---

## Platform support and exceptions

Auto-download requires that upstream publishes something you can unpack and use. These combinations do not have it; the card **states the reason and the alternative** rather than installing something that cannot run:

| Component | Platform | Situation and alternative |
|---|---|---|
| Docker | Windows | Installer only (WSL2 / Hyper-V integration, service registration). Download it manually from docker.com |
| Apache Pulsar | Windows | The `pulsar` command is a POSIX shell script; upstream expects Docker or WSL |
| RabbitMQ | Windows | An "installer + service registration" case. The tool downloads RabbitMQ itself, auto-installs the matching Erlang/OTP prerequisite (4.x -> 27.x, 3.13 -> 26.x) and offers one-click start/stop; the official Windows installer remains an option where service registration is needed |
| Nginx | Linux / macOS | Source only upstream — use `apt / dnf / yum install nginx` or `brew install nginx`. The Windows zip is mirrored (measured) only on two Huawei Cloud subdomains; TUNA / BFSU / NJU / Aliyun / Tencent all 404 |
| Python | Linux / macOS | Upstream ships source tarballs only, not a ready interpreter (open item, see `DEVELOPMENT.md`) |
| PostgreSQL | Linux / macOS | EnterpriseDB provides Windows binary zips only; use your distro's package manager or `brew install postgresql` |
| MongoDB | macOS | Source or Homebrew formula only — `brew install mongodb-community` |
| Git | macOS / Linux | Source only upstream — use the package manager or brew |
| kubectl | Linux / macOS | Downloads fine; the artifact is an extensionless single file — `chmod +x` |
| JDK | all | Mirror filenames carry build numbers that only resolve after a refresh — **click "⟳ Refresh versions" first** |
| MongoDB / PostgreSQL | all | Measured: no mainland mirror at all; official single source, so downloads are slower in-country |
| Rust | Linux / macOS | Upstream ships `rustup-init` and source only; there is no "unpack and run" layout (the combined tar.xz holds `rustc/` + `cargo/` component directories that need the installer to merge a sysroot). Use official `rustup` or your package manager |
| Redis | Linux / macOS | Upstream ships source only; the Windows package registered here is a **community build** (not official) and is not carried over to POSIX platforms. `apt / dnf install redis`, or `brew install redis` |
| protoc | Linux / macOS | Upstream also ships `protoc-<v>-{linux-x86_64,osx-*}.zip`, but those sources are not measured per R1 yet. `apt install protobuf-compiler`, or `brew install protobuf` (may lag upstream) |
| uv | Linux / macOS | Upstream ships tar.gz too, likewise unmeasured. Use the official installer `curl -LsSf https://astral.sh/uv/install.sh | sh`, or `brew install uv` |

---

## In depth

### Multiple versions and the active version

All 59 installable components keep one directory per version (the 26 download-only tools put nothing on disk, so they are outside this category): `~/.env-tools/<component>/<component>-<version>/` (e.g. `jdk-21` and `jdk-17` side by side). "Active version" in the UI means "the one the system is currently using".

- **Green tick = installed on disk.** Ticked versions can be uninstalled; unticked ones keep the button disabled (there would be nothing to remove).
- **Installed versions always reappear in the dropdown.** Live lists change; a version may be dropped upstream while it is still on your disk. The dropdown re-inserts it, sorted by version, with its tick — otherwise that version could not be selected, switched to, or uninstalled except by deleting the directory by hand. The back-fill applies to every installable component alike (since 2026-10-06); before that only multi-version components got it, so jenkins / nacos still hit the case of something installed that the live list no longer carries.
- **"Switch" = make the selected version active**: `XXX_HOME` is repointed at that directory and this component's `PATH` entries are collapsed into the single active one. Other components' entries — and your own entries outside this tool's directory — are left alone. Any failure mid-way rolls back to the pre-switch state, logged explicitly, so "`XXX_HOME` says 21 while `PATH` says 17" cannot persist.
- **Uninstall touches only the selected version**: its directory and its own `PATH` entries. The summary lists each action, e.g. `removed install directory: …jdk-21`, `removed env var: JAVA_HOME`, `removed from PATH: …jdk-21\bin`, `no entries in PATH within this uninstall scope`.
- **Deleting the active version re-picks automatically**: the log says `active version switched automatically to 17.0.12` (the highest remaining); if the active version still exists but this uninstall disturbed the variables, it says `rebuilt env vars and PATH from active version 21.0.4`; deleting the last installed version says `no installed versions left; active registration cleared`.
- **The copy you installed yourself is not touched**: when `XXX_HOME` points outside this tool's component directory, neither the directory nor the variable is removed or repointed, and the log says so. Re-picking after a delete is also limited to this tool's own directories.
- **Old setups still work**: components installed before this feature existed are judged by the `XXX_HOME` already in the system; after one "Switch", the UI's own record becomes authoritative.
- Installing repoints the variables at the version just installed; press "Switch" once if you also want the card's active marker and the collapsed single `PATH` entry.
- On other components "Switch" means something simpler: pick the highest locally unpacked version and just configure environment variables, without re-downloading (useful if you placed the archive yourself).
- This tool does **not** rewrite `pom.xml` / `build.gradle` and does not configure IDE SDKs. To pin a JDK inside an IDE, use that IDE's own SDK settings and point it at the version directory.

### Taking over your own installation (and reverting)

The above covers versions this tool downloaded into `~/.env-tools/`. Versions you installed yourself elsewhere (`E:\soft\jdk\jdk17`) can also be discovered and made active:

1. **Scan**: expand "Versions detected on this machine" at the bottom of the card. It consults environment variables, `PATH` entries, and (for Python) `py -0p` / registry records. **The scan is read-only** — nothing changes until you act, and it only runs when you expand the section. Every row is confirmed by actually running that candidate's version command; a directory it cannot confirm is omitted rather than mislabelled.
2. **Switch to it**: user-level variables first, no elevation prompt. Then the tool **re-verifies** "which entry a new terminal actually hits first":
   - already the target version → done;
   - shadowed by an earlier entry (Windows composes the process `PATH` as *system segment entirely first, then user segment*, so user-level writes **cannot** override a system-level entry with the same command) → a confirmation dialog lists exactly what will change, to what, and what it was; only after you agree does it request elevation and **insert the target directory at the front of the system `PATH`**;
   - re-verification unavailable → **no elevation**, reported honestly as "could not re-verify, please check in a new terminal".
3. **Revert**: once a takeover is active the card keeps "↩ Restore my previous settings", which writes back the **original text verbatim** (including placeholders such as `%JAVA_HOME%` and the original value type). The button survives a restart.
4. **Safety boundary**: system-variable edits always go through "original snapshot (plus a backup file) + insert whole entries only into the original text, no reordering, no dedup, no case changes + reread and validate entry by entry (roll back immediately if a critical `system32` / `Windows` entry is missing) + re-verify + revertible". Fail any one of these and everything is restored and the error is reported — **you will never see "success" that did not take effect**. Answering "No" in the UAC dialog, or the helper timing out, is treated as "nothing was changed".

Externally discovered versions appear **only in this collapsed section**: never in the version dropdown (which is the reverse-lookup key) and never eligible for uninstall — this tool does not delete software you installed. The capability is limited to seven components: JDK / Python / Node.js / Go / Maven / Gradle / Bun.

### When "Switch" appears not to work: the tool fixes it

A third case is neither a takeover nor a plain failure: **a version installed by this tool is being shadowed by an older system-level entry.** Measured locally: the system `PATH` contained your own `E:\soft\maven\apache-maven-3.9.2\bin` while this tool's 3.10.0 was written into the user variable — and user-level writes can never outrank the system segment.

The tool branches on **which segment the winning entry lives in**, and solves what it can:

- **In the user variable** (merely ahead of ours): our entry is moved to the front of the user `PATH`, then re-verified — **no elevation prompt**.
- **In the system variable**: a confirmation dialog lists the changes; after you agree it requests elevation and **inserts this version's directory at the front of the system `PATH`**, **deleting no existing entry** (yours stays, just further back); re-verified afterwards. Explorer is then notified by name — elevated writes come from a helper process, and without that notification you would see "the registry is right, the tool's own verification terminal is right, but my new terminal still shows the old version".
- **Found in neither segment**: **no elevation prompt**, and the tool explains why it will not take this on (the cause is not in these two segments, so editing the system variable would likely be treating the wrong thing).

Both branches first record the original text and keep "↩ Restore my previous settings" available (restoring is also a system-level change, so Explorer is notified again). Also, **before switching to another version or uninstalling, the tool restores the system variable first**, so the system `PATH` never keeps an entry pointing at a stale or deleted directory. Answering "No" to either dialog means "nothing was changed".

### When environment changes take effect

- **Windows**: newly opened command prompts / PowerShell windows read the new value; already-open windows must be restarted. After **every** write (user-level and elevated system-level alike) the tool notifies Explorer by name (`Shell_TrayWnd`) so it rebuilds its own environment immediately — terminals started from the Start menu, taskbar or desktop therefore see the new value within about a second.
- **If it still does not change, the host process is stale**: Windows *copies* the environment block into new processes. IDEs and any long-lived process (including terminals they spawn) still carry the block from their own start time, so opening more tabs inside them never helps. After a switch the log names "terminal windows that were already open before this switch" (pid + start time) so you can close exactly those; windows flagged "elevated" cannot receive our notification and must be closed entirely.
- **Multi-version switches are bound by the same rule**: the tool syncs the new value to itself immediately, but already-open terminals and IDEs do not see it. Terminals need a full window close; IDEs (IntelliJ IDEA / Eclipse / VS Code …) need a restart, and creating a new terminal tab inside the IDE is sometimes still not enough. **Windows Terminal likewise**: its new tabs and windows inherit the environment block captured at its process start — closing a tab is not a restart, even though a fresh PowerShell banner makes it look like one. The log line "already-open terminals and IDEs must be restarted to see the new values" is exactly this.
- **When in doubt, open a brand-new terminal yourself**: Windows **copies** the environment block into each new process, so a freshly opened PowerShell / cmd window reads whatever is currently in effect. Already-open windows (including terminals spawned inside an IDE, and new Windows Terminal tabs) still hold the block they started with.
- **`where java` may still hit Oracle's javapath first**: Oracle's Java auto-update inserts `C:\Program Files\Common Files\Oracle\Java\javapath` into the **system** `PATH`, and ours is written to the **user** variable, which sorts after the system segment. Then even with `JAVA_HOME` pointing at our installation, plain `java -version` reports the javapath build. See "How to verify" below; the fix is removing that javapath entry from the system `PATH` (needs administrative rights).
- **macOS / Linux**: `source ~/.zshrc` (or `~/.bashrc` / `~/.bash_profile` / `~/.profile`), or just reopen the terminal.

### How to verify which copy is in use

```bash
java -version
mvn -v
python --version
node -v
mysql --version
git --version
conda --version
```

Just switched the active version of a multi-version component? Run these three lines in a **new** window — `where` lists matches in `PATH` order, and **only the first line is the one that actually executes**:

```bat
echo %JAVA_HOME%
where java
%JAVA_HOME%\bin\java -version
```

- `echo %JAVA_HOME%` should print `C:\Users\<you>\.env-tools\jdk\jdk-<active version>`.
- The first line of `where java` should be in the same directory. If it is `C:\Program Files\Common Files\Oracle\Java\javapath\java.exe`, Oracle's javapath wins; the third command bypasses `PATH` and proves our copy is fine.

### Cleaning dead PATH entries

Delete an install directory by hand, or interrupt an uninstall, and `PATH` can keep entries pointing into this tool's directory that no longer exist. The title bar's **"🧹 Clean PATH"（清理残留 PATH）** clears exactly those (entries into our own directory only; other programs' `PATH` entries are untouched).

---

## UI tour

| Area | What is there |
|---|---|
| Title bar (left) | Icon + app name + **version chip**. The chip is also a status light: plain = not checked yet; `⟳ v1.2.2 checking` = check in flight; `v1.2.2 up to date` = latest; `↓ v1.2.3 update available` (amber) = newer release exists, **one click downloads it**; `↓ 37%` = downloading; `? v1.2.2 unknown` (grey, dashed) = the check failed and the tooltip says why. **The version number is always visible** — that is the first thing needed when reporting a problem |
| Title bar (right) | "★ GitHub" opens the repository · "⟳ Refresh versions" bypasses the cache and re-fetches live lists · "🧹 Clean PATH"（清理残留 PATH） clears dead entries · "♥" supports the author · minimise / maximise / close |
| Search bar | Component search (fuzzy over names and keys, showing "matched N / 85"); while searching, the tabs collapse and hits are grouped by category with small headings; clearing restores everything. Next to it: "▦ Grid / ☰ List" and "📋 Log" |
| Cards | Five tabs (counts in titles). Each card: name, status capsule (hover for the full text), searchable version dropdown (green tick = installed), action buttons (Install / Switch / Uninstall; plus Start / Stop and Console or Page for services; download-only tools show just Download), gradient progress bar. Cards re-flow into columns with window width |
| Log overlay | Collapsed by default over the card area; "📋 Log" expands it, warn/error auto-opens it and puts an unread counter on the button. Four levels (info grey, ok green, warn orange, error red), Chinese throughout, including mirror switching and failover narration |
| Status bar | System info, the **clickable working directory**, component count. The version is not here — it is the chip |

Three promises about the update check (rule R12 in `DEVELOPMENT.md`):

1. **Read-only, background, silent on failure**: at most one automatic check per day, on a worker thread with an 8-second timeout; when it cannot reach anything it stays **completely silent** — no "check failed" nag (`github.com` being unreachable for whole days in-country is normal, and it is a network fact, not a software fault). A manual click on the chip always answers.
2. **Never replaces itself**: it finds the newest release, downloads the new package to your chosen directory and verifies the byte count. It never renames, overwrites or restarts the running program — antivirus and SmartScreen react badly to self-replacement, and one false positive would leave you neither updated nor able to launch.
3. **No telemetry**: requests carry no query parameters and no user data (that is the line between "update check" and "telemetry").

The **first download source is a Gitee direct link** (much faster in-country); if that attachment is missing on Gitee it falls back to the GitHub accelerators and then the official URL. If GitHub is blocked or the unauthenticated quota is exhausted, **the version query itself also falls back to Gitee**, so a blocked GitHub cannot masquerade as "no new version".

---

## Running from source

Only needed if a packaged build will not start on your machine, or you want to change the code.

**Requirements**: Python 3.10 – 3.14 (PySide6 6.11 declares `requires_python >=3.10,<3.15`); Windows 10 / 11, macOS 12+, Ubuntu 20.04+; network access to the sources you download from (Apache archives, Adoptium API, Node.js dist, …); disk depends on what you install — budget 3 GB+ (JDK + Maven + Node + Python + MySQL is about 1.5–2 GB).

### Windows: two double-click scripts

| Script | Does |
| --- | --- |
| `一键启动项目.bat` | Prepares the environment, then starts the GUI from source (code changes take effect immediately) |
| `一键打包exe.bat` | Prepares the environment, then runs PyInstaller to produce `dist/ByteTools/ByteTools.exe` (onedir, starts with no unpacking) |

Both share the same bootstrap:

1. Check whether `.venv` already works; if so, skip interpreter discovery entirely.
2. Find a usable Python (**3.10 – 3.14**, matching PySide6's `requires_python`): `py -3.12/3.13/…` → `python` / `python3` → scanning `%LOCALAPPDATA%\Programs\Python\*` and `%ProgramFiles%\Python*`. **If there is none, install one**: `winget` first, then the official installer fetched in order Huawei Cloud → npmmirror → python.org, silently, user-level, no PATH edits, no admin rights.
3. Reuse `.venv`; create or rebuild (`--clear`) it when missing or broken.
4. Install `requirements.txt` when dependencies are missing, mirror order TUNA → Aliyun → official PyPI; the packaging script also installs PyInstaller.
5. Launch `main.py`, or build per `byte-tools.spec` and print the artifact's size and timestamp at the end.

> The scripts only touch `.venv` inside the project: no system PATH edits, no changes to a system-wide Python. Only when the machine has no usable Python at all does one get installed under the **current user's** `%LOCALAPPDATA%\Programs\Python`. Pass `nopause` for scripted use (no "press any key" at the end).

### macOS / Linux: four steps

```bash
git clone https://github.com/jilong2026/byte-tools.git
cd byte-tools

python3 -m venv .venv
source .venv/bin/activate          # on Windows: .venv\Scripts\activate

pip install -r requirements.txt    # PySide6 + requests

python main.py
```

The working directory is created on first launch:

```
~/.env-tools/            # all archives and unpacked components live here
├── jdk/
│   ├── downloads/       # original archives
│   └── jdk-21/          # unpacked JDK
├── maven/
├── node/
├── config.json          # preferences and registries (selections, active versions, download dir, update-check state)
└── version_cache.json   # 24-hour cache of live version lists
```

---

## Configuration

### Editing a component's version list

Open `main.py` and find `build_components()`:

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
            for v in ("22", "21", "17", "11", "8")   # add 22
        ],
    )
)
```

> `versions` is only the **offline default list**: at startup the background fetch replaces it with live data (and falls back to it when fetching fails, so the tool works offline). To change fetching, edit `FETCHERS`. Adding a component properly is documented in [`docs/ONBOARDING_NEW_COMPONENT.md`](docs/ONBOARDING_NEW_COMPONENT.md).

### Mirrors and multi-source failover

11 mainland mirror bases (Huawei Cloud repo / Huawei Cloud mirrors / TUNA / Aliyun / NJU / USTC / BFSU / Tencent / SJTU / npmmirror / DaoCloud files) plus 3 GitHub accelerators (GitHub Releases have no true mirror, only reverse-proxy acceleration). The rules:

1. Try sources in order; on 404 / timeout / connection failure, switch immediately.
2. Fall back to the official origin only after all mainland sources failed.
3. Narrate it all in Chinese (which source failed, which we switched to, which one was used).
4. Two reliability guarantees: a fixed `byte-tools` User-Agent (some university mirrors 403 the default UA); byte-count verification after download, so "fake 200 empty file" switches source instead of leaving a broken archive.

**Ordinary users never edit URLs.** A few components differ (measured 2026-10): mongodb / postgresql have no mainland mirror; nacos / bun / powershell / erlang and git's macOS/Linux source packages use the GitHub accelerators with the bare GitHub URL last; nginx's Windows zip appears only on two Huawei Cloud subdomains; kubectl prefers the DaoCloud `files.m.daocloud.io` proxy (`dl.k8s.io` paths cannot be rewritten); seata uses the Apache distribution directory (eight mainland mirrors); jdk's exact filenames resolve only after a refresh. Full details: rule R1 in [`DEVELOPMENT.md`](DEVELOPMENT.md).

> Measured throughput differences between sources span two orders of magnitude on the same machine, so mirror order is based on **measured throughput**, not reputation. Numbers go stale; the method does not: probe status code + file magic + accumulated bytes and average speed with the project UA, then order.

### Version cache and GitHub's quota

Fetched version lists are **cached on disk** (`~/.env-tools/version_cache.json`, not re-fetched within a day). The reason is concrete: GitHub's anonymous API allows **60 requests/hour per IP**, while one startup would otherwise fetch lists for 77 components (many of them against GitHub) — a second launch inside the same hour, or a few refresh clicks, exhausts the budget and produces a wall of "fetch failed" lines.

- On a cache hit the log says "reusing version lists fetched within 24 hours (N components)" and makes no requests.
- For genuinely newest numbers, press **"⟳ Refresh versions"** — it bypasses the cache.
- If the quota really is exhausted, the log says so plainly ("anonymous GitHub quota exhausted, 60/hour per IP; using the built-in list this time; try again in an hour") instead of implying the vendor site is down. It recovers within an hour; if `GITHUB_TOKEN` / `GH_TOKEN` is set in your environment, the tool uses it and the limit becomes 5000/hour.

### Working directory and download directory

The component working directory defaults to `~/.env-tools/`; change it at the top of `main.py`:

```python
CONFIG_DIR = Path.home() / ".env-tools"
```

The **download directory** for the 26 dev tools is a separate preference: remembered from the first download (stored in `config.json`), falling back to the system Downloads folder when unset or deleted. It is not part of the working directory.

---

## Building and releasing

For maintainers. Day to day you only need "the three steps"; the rest is rationale and recovery.

### Local build (single platform)

On Windows double-click `一键打包exe.bat` (it prepares `.venv` and PyInstaller). Manually:

```bash
pip install pyinstaller
pyinstaller byte-tools.spec --noconfirm --clean
```

> If PyInstaller on this machine prints nothing for a long time at startup (WINMGMT cold start blocks `platform.win32_ver()`), use the ready entry point in the repo — same result, no WMI: `python pyinstaller_no_wmi.py byte-tools.spec --noconfirm --clean`. The `.bat` already uses it.

Artifacts: `dist/ByteTools/ByteTools.exe` (Windows, onedir folder) · `dist/ByteTools.app` (macOS) · `dist/ByteTools` (Linux). The Windows build carries the project icon (`assets/byte-tools.ico`, generated from `assets/byte-tools.png` at 16–256 px); how to regenerate the ICO after a logo change is in [`CODE_WIKI.md`](CODE_WIKI.md) §7.4. If Explorer still shows the old icon after an overwrite build, that is the Windows icon cache — rename the file or run `ie4uinit.exe -show`.

**Always run the built exe once and close it yourself, and confirm the exit code is 0** — the close-crash class and its forensic script are documented in rule R14 of `DEVELOPMENT.md`.

### Automated three-platform release (recommended)

Push a tag and `.github/workflows/release.yml` builds on Windows / macOS / Linux runners, uploads to the matching GitHub Release, and writes direct links into the Gitee Release:

```bash
git tag v1.2.1
git push origin v1.2.1
```

A few minutes later the GitHub Release is complete and published (3 platforms, 4 files); Gitee has a same-named Release whose body is a table of GitHub direct links. Fully automatic — no "Publish" click needed.

> The workflow triggers only on `v*.*.*` tag pushes; pushing `dev` / `master` starts nothing.

### The three steps per release

GitHub is automatic; **the Gitee upload must be done from your own machine** (an overseas runner pushing large binaries hangs; the domestic path takes tens of seconds). Prerequisite: the changes are already merged to `master` — order matters, because the workflow builds the commit the tag points at.

1. **Push the tag**: `git tag v1.2.1 && git push origin v1.2.1`
2. **Wait for Actions to go green.** Then: GitHub Release has the 4 artifacts and is published; Gitee has the same-named Release with the direct-link table in the body, but its **attachment area is still empty**.
3. **Upload the artifacts to Gitee from your machine** (the token is prompted interactively so it never lands in shell history):

   ```bat
   cd /d E:\file\test\byte-tools
   同步Gitee产物.bat v1.2.1
   ```

   That is all. The script creates `release-assets/`, downloads the four artifacts through `gh-proxy.com`, uploads each to Gitee, and in `[3/3]` checks that all four attachments exist. Existing local files are not re-downloaded (unless you cleared the directory). Double-clicking `同步Gitee产物.bat` works too — it asks only for the tag and the token.

To skip step 3 entirely: point `sync-to-gitee`'s `runs-on` at a self-hosted runner deployed in China and fill in `UPLOAD_ARTIFACTS` with the four names.

### Why the Gitee sync is built this way

Logic lives in `同步Gitee产物.sh` / `同步Gitee产物.bat`; offline end-to-end cases in `bt_gitee_sync_tests.py`.

- **Large binaries are not pushed to Gitee by default.** An overseas runner POSTing 84 MB to `gitee.com` hangs and nothing lands server-side — measured on v1.0.3: one POST hung for 70 minutes and the attachment list stayed empty. Writing GitHub direct links into the body reduced this job to a few kilobyte API calls.
- **Every request prints observable output**: status code, duration, bytes transferred and average speed. 4xx fails immediately without pointless retries; network-class errors back off per `MAX_ATTEMPTS` (default 3: 5s / 10s). Previously curl's `--retry` multiplied with the script's own retry and allowed 30 minutes per request — worst case six silent hours with no log line.
- `sync-to-gitee` has `timeout-minutes: 25` (it previously used GitHub's 360-minute default, which is why hangs went unnoticed).
- **Idempotent**: reuses an existing Release ID and skips existing attachments, so Re-running the job after a failure is safe. But note **a Re-run uses the code from that original run** — after editing the script, trigger a fresh run.
- **Missing direct links are repaired**: a historical body may be an old format or a placeholder without direct links, which makes the final check fail forever (v1.0.5 was stuck exactly there). The script now `PATCH`es `/repos/{owner}/{repo}/releases/{id}` to rewrite the body (route verified: unauthenticated → 401 "login invalid", nonexistent path → 404); only if that is refused does it error out with two manual options: paste the printed body into Gitee's editor, or delete that Gitee Release (and tag) and let the script recreate it.
- **Strict final verification**: the GitHub direct links in the body must read back, and every name in `UPLOAD_ARTIFACTS` must appear. Missing one is an error — never a silent "sync OK".
- **The token is passed only as a curl form field**, never in a URL, and the script deliberately avoids `curl -v` (which would log the token).

### `release-assets/` is cleared every run, on purpose

The four artifacts have **the same names across tags** (since v1.2.0 the main Windows build is `ByteTools-windows-x64.zip`; `ByteTools.exe` is the legacy onefile compat name), so "file already exists" says nothing about which version it belongs to. The old logic skipped download when a non-empty file existed, which uploaded the previous tag's binaries into the new tag's Gitee Release while the final check — comparing attachment names only — still reported OK (this is exactly how "everything uploaded was stale" happened on 2026-10-10).

Now `:clear_stale` deletes the staging directory before downloading; if it cannot delete (files locked), it **stops without uploading** rather than shipping an archive of unknown provenance. The price: re-running after a mid-way failure re-downloads about 218 MB.

Two boundaries: clearing applies only to a path whose **last element is exactly `release-assets`** (if a third argument points at a real repository directory such as `assets`, the script prints `notice:` and skips — it never `rmdir`s version-controlled content); with `AUTO_FETCH_ASSETS=0` (regression tests, or artifacts you placed manually) it neither clears nor downloads.

> ⚠️ Do **not** point the artifact directory at the repository's own `assets/` — that is the icon and QR-code directory and the `.bat` would find zero artifacts. The default is `release-assets/` (in `.gitignore`, so hundreds of MB never get committed), and the script now **checks the artifacts before contacting Gitee**.

### Re-syncing a historical tag

When GitHub succeeded but Gitee did not (e.g. v1.0.2), no re-release is needed:

- **Option 1 (recommended, nothing local)**: repository → Actions → `release` workflow → **Run workflow** → enter `tag_name` (e.g. `v1.0.2`). It runs only the sync job.
- **Option 2 (locally)**: on Windows `同步Gitee产物.bat` (it really uploads, fast domestic path); on Linux / macOS / Git Bash `同步Gitee产物.sh` (direct links only by default; set `UPLOAD_ARTIFACTS` to upload).

Manual fallback when automatic fetching fails — **the accelerator prefix is mandatory**: direct `github.com` downloads time out in-country (measured 2026-09-29: `curl` rc=28, no connection in 20 s, while at the same moment the `https://gh-proxy.com/` prefix returned 206 with a real file signature). The hint printed by `同步Gitee产物.bat` carries the prefix too.

```bat
REM Windows: fetch first, then run step 3 above
mkdir release-assets
curl -L -o release-assets\ByteTools.exe               "https://gh-proxy.com/https://github.com/jilong2026/byte-tools/releases/download/v1.2.1/ByteTools.exe"
curl -L -o release-assets\ByteTools-windows-x64.zip   "https://gh-proxy.com/https://github.com/jilong2026/byte-tools/releases/download/v1.2.1/ByteTools-windows-x64.zip"
curl -L -o release-assets\ByteTools-macos-arm64.zip   "https://gh-proxy.com/https://github.com/jilong2026/byte-tools/releases/download/v1.2.1/ByteTools-macos-arm64.zip"
curl -L -o release-assets\ByteTools-linux-x64         "https://gh-proxy.com/https://github.com/jilong2026/byte-tools/releases/download/v1.2.1/ByteTools-linux-x64"
dir release-assets       REM the four sizes must match what GitHub Release reports
```

```bash
# Linux / macOS / Git Bash
mkdir -p ./release-assets
for f in ByteTools.exe ByteTools-windows-x64.zip ByteTools-macos-arm64.zip ByteTools-linux-x64; do
  curl -L -o "./release-assets/$f" "https://gh-proxy.com/https://github.com/jilong2026/byte-tools/releases/download/v1.2.1/$f"
done

# Prompt for the token so it never lands in history or logs
read -rsp "Gitee Token: " GITEE_TOKEN; export GITEE_TOKEN; echo
GITEE_OWNER=jack_liujilong GITEE_REPO=byte-tools TAG_NAME=v1.2.1 \
GITHUB_REPO_SLUG=jilong2026/byte-tools ASSETS_DIR=./release-assets \
"./同步Gitee产物.sh"
unset GITEE_TOKEN
```

Both scripts need `curl`; the `.sh` also needs `awk`, and uses `python3` / `python` only to parse JSON (falling back to `grep` when no interpreter is usable — on Windows `python3` is often the Microsoft Store alias, so the script handshakes before choosing). `.bat` content stays **pure ASCII**: cmd parses a UTF-8 batch file as GBK, and non-ASCII text makes statements desync and get swallowed.

---

## FAQ

**Q1. A whole group of components reports "failed to fetch versions from the official site, using the built-in default list"?**
Two causes, and the log distinguishes them. ① **GitHub's anonymous quota is exhausted** (60/hour per IP while one startup fetches 77 component lists) — wait an hour, or stop hammering "⟳ Refresh versions"; if `GITHUB_TOKEN` / `GH_TOKEN` is set the limit becomes 5000/hour. ② Network or source trouble — the log carries the real reason (timeout / 404 / DNS). **Neither affects usability**: a failed fetch falls back to the built-in list, and those versions download and install normally. Lists are also cached for a day — see [Version cache](#version-cache-and-githubs-quota).

**Q2. A download sits at one percentage?**
Likely the network or a throttled mirror. Press **Cancel** and retry — the tool switches source. If it keeps failing, open "📋 Log" to see which source failed and where it switched, and press "⟳ Refresh versions" to re-resolve the mirror's current versions and exact filenames (JDK especially needs this) before retrying.

**Q3. It reports that writing environment variables failed?**
Windows: the default target is the **user-level** environment, which normally needs no elevation; if policy really blocks it (some corporate machines), relaunch as administrator. macOS / Linux: confirm you can write `~/.zshrc` etc.

**Q4. I already have an old `JAVA_HOME` — will it be overwritten?**
It is overwritten with the path from the most recent install/configure step, and the new `bin` directory is added to `PATH` (never duplicated). For multi-version components "Switch" goes further: `JAVA_HOME` repoints at the active version and this component's other `PATH` entries are collapsed into the active one — other components' entries and your own entries outside this tool's directory stay put.

**Q5. Can I use MySQL straight after unpacking?**
No. MySQL still needs `mysqld --initialize` and friends. This tool completes "download + unpack + environment variables" only; it does not initialise databases.

**Q6. Can it handle `.tar.xz` archives?**
Yes — `tarfile.open("r:xz")` is built in (used for the Linux MySQL build).

**Q7. What about Windows `PATH` longer than 1024 characters?**
It cannot happen here: the tool never uses `setx` (which truncates at 1024 characters) — it writes `HKCU\Environment` via `winreg` and broadcasts `WM_SETTINGCHANGE` (the Explorer path is a **targeted, synchronous** send; `HWND_BROADCAST` does not work for it). `PATH` is edited entry by entry; the registry's user segment is never dumped over the process `PATH`. Details: R3.15 / R3.20 in `DEVELOPMENT.md`.

**Q8. Where does Miniconda get installed?**
`~/.env-tools/conda/conda-<version>/`, with `CONDA_HOME` and its `bin` / `Scripts` registered.

**Q9. Can it only detect, without installing?**
Yes — status detection runs at startup for every component; if everything reads ✓ Configured the machine is ready and no button is needed. Installable components read `● N versions installed · active X (…)`, which means the same thing. To only configure variables without re-downloading, use "Switch".

**Q10. Does it track the latest component versions automatically?**
The dropdown starts from the built-in list, then a background job fetches the official sources and hot-swaps the list; "⟳ Refresh versions" forces a re-fetch. So "latest" really is live, provided the source is reachable (and the GitHub quota holds — see Q1).

**Q11. Are downloads slow in China?**
No. 11 mainland mirrors + 3 GitHub accelerators run mainland-first with failover and the official origin last, narrated in Chinese, with zero configuration for ordinary users. A few components genuinely have no mainland source (see [Platform support and exceptions](#platform-support-and-exceptions)); the log states whether an accelerator or the official site was used.

**Q12. Will uninstalling one version break the others?**
No. For multi-version components uninstall removes only the selected version's directory and its own `PATH` entries; other versions' directories, variables and entries are untouched, and `XXX_HOME` is cleared only when it pointed at the deleted version. If that was the active version, the UI switches to the highest remaining one and the log says so (`active version switched automatically to …`). A version that is not on disk has no green tick and "Uninstall" is disabled.

**Q13. I switched the active version but `java -version` still shows the old one?**
Open a **brand-new** PowerShell / cmd window yourself first: Windows **copies** the environment block into each new process, so a freshly opened window shows whatever is currently in effect. If it is right and your old window is wrong, that window predates the switch. Work through these three:

1. **The window was not restarted**: a switch only affects new processes. Close terminal windows entirely; restart IDEs (IDEA / Eclipse / VS Code) completely. After a successful switch the log names "terminal windows already open before this switch" (pid + start time) — close exactly those; windows marked "elevated" cannot receive our notification and must be closed by hand. Note that Windows Terminal's new tabs and windows inherit its process' stale environment — **closing a tab is not a restart**.
2. **Oracle's javapath wins**: if the system `PATH` contains `C:\Program Files\Common Files\Oracle\Java\javapath`, it precedes user entries, so bare `java` runs that build. `where java` (first line) proves it; `%JAVA_HOME%\bin\java -version` bypasses `PATH` and confirms our copy is fine.
3. **The switch itself failed**: if the log says "switch failed", the tool already rolled back to the pre-switch snapshot — effectively nothing changed; press "Switch" again. If it then says "not fully successful" with details, something could not be undone automatically: check `XXX_HOME` and `PATH` against those details (each names the item and the expected value).

**Q14. Will the update check upgrade me without asking, or send me data?**
Neither. It asks once which the newest stable release is (unauthenticated, no query parameters, no user data) and, if you agree, downloads the new package **to your chosen directory** and verifies its size. It never renames or overwrites the running program. Automatic checks run at most once per day and mention a given new version once; failures are **completely silent**. To check right now, click the version chip. See the three promises in [UI tour](#ui-tour).

**Q15. I have Docker Desktop — can the tool configure it for me?**
No, and it will not pretend. On Windows Docker exists only as an installer (WSL2 / Hyper-V integration, service registration), so "download a zip and unpack" is not a path. The card says so and points at docker.com instead of installing something that cannot run.

---

## Stack · Layout · Contributing

**Stack**: Python 3.10 – 3.14 · [PySide6](https://doc.qt.io/qtforpython-6/) (official Qt 6 Python bindings, LGPL) · [requests](https://requests.readthedocs.io/) · standard-library `zipfile` + `tarfile` · environment via `winreg` + `WM_SETTINGCHANGE` (Windows) or marked shell-config blocks (macOS / Linux) · `QThread` for downloads and version fetching, so the UI never blocks · **single-file architecture**: `main.py` holds the UI, data classes and all business logic.

**Repository layout**:

```
byte-tools/
├── main.py                     # the application (UI + all logic)
├── 一键启动项目.bat            # Windows: bootstrap environment, run GUI
├── 一键打包exe.bat             # Windows: bootstrap environment, build dist/ByteTools.exe
├── pyinstaller_no_wmi.py       # build entry that avoids WMI entirely
├── byte-tools.spec             # PyInstaller configuration
├── requirements.txt            # PySide6 + requests
├── README.md / README_EN.md    # Chinese / English documentation
├── DEVELOPMENT.md              # maintainer rules R1–R16 (mirrors, env vars, launch, thread invariants…)
├── CODE_WIKI.md                # code wiki (class / module / function index)
├── MIRROR_REPORT.md            # mirror measurement report
├── docs/                       # request templates, onboarding notes, live test reports
├── tools/                      # measurement / forensic / performance scripts (not runtime deps)
├── bt_*_tests.py               # offline regression suites (a dozen of them, never online)
├── 同步Gitee产物.bat / .sh     # Gitee sync (local and CI)
├── .github/workflows/release.yml   # three-platform build + release (incl. Gitee sync)
├── assets/                     # icon, screenshot, donation QR codes
└── LICENSE                     # MIT licence text
```

**Contributing**: stars, 🐛 [issues](https://github.com/jilong2026/byte-tools/issues) (please include the version chip and the relevant "📋 Log" lines) and 🔀 PRs are welcome. Before adding a component, read [`docs/ONBOARDING_NEW_COMPONENT.md`](docs/ONBOARDING_NEW_COMPONENT.md) and [`docs/HOW-TO-REQUEST-COMPONENT-LAUNCH.md`](docs/HOW-TO-REQUEST-COMPONENT-LAUNCH.md) — they record every rule that was learned the hard way.

**Support the author**: if this saved you time, coffee is appreciated ☕

<table>
  <tr>
    <td align="center"><img src="assets/wechat.png" alt="WeChat Pay" width="200"/><br/><b>WeChat</b></td>
    <td align="center"><img src="assets/alipay.png" alt="Alipay" width="200"/><br/><b>Alipay</b></td>
  </tr>
</table>

---

## License

[MIT License](LICENSE), Copyright (c) 2026 jilong2026. Full text also at <https://opensource.org/licenses/MIT>.

<p align="center">
  Made with ❤️ by <b>jilong2026</b> · <a href="README.md">中文</a>
</p>
