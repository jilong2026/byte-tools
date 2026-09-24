# Byte Tools — by rgh

A cross-platform desktop GUI tool built with Python + PySide6 that automates the download, extraction and environment-variable configuration of common developer toolchains. Save yourself from tedious manual installation.

> Project: **byte-tools**
> Author: **rgh**
> Platforms: Windows 10/11, macOS 12+, Ubuntu 20.04+
> License: MIT License

---

## 1. Features

- 🖥️ **Cross-platform.** Detects Windows / macOS / Linux (and x64 / arm64) at runtime and picks the correct distribution.
- 📦 **One-click provisioning.** Preloaded with **24 built-in developer components** — the whole pipeline (download → unpack → configure) is automated. See [Supported Components](#2-supported-components) below for the full list.
- 🇨🇳 **China mirror priority.** Since v2.0 every component ships with ≥2 China mirrors (Huawei Cloud / Tsinghua TUNA / Aliyun / USTC / NJU) plus one official source, with multi-source failover — the official site is only used after all China mirrors fail (404 / timeout). Full Chinese logs report which mirror failed, which one it switched to, and which source finally served the file. Users do **not** need to manually edit URLs to enjoy China-mirror acceleration.
- 🔍 **Smart detection.** Checks whether `JAVA_HOME` and friends already exist and are valid; missing/invalid entries are flagged for reconfiguration.
- 🛠️ **Environment-variable management.**
    - Windows: writes to `HKCU\Environment` via `winreg` and refreshes with `setx`.
    - macOS / Linux: appends idempotent `export` blocks (with begin/end markers) to `.zshrc` / `.bash_profile` / `.bashrc` / `.profile`.
- 📊 **Live feedback.** Progress bar with real-time byte counts, cancel support, colour-coded log output (info / ok / warn / error).
- 🎨 **Modern UI.** Frameless custom title bar with a window icon (visible in the taskbar / Alt+Tab), rounded cards with drop shadows, gradient progress bars, hover/press animations, and a bottom status bar showing "Total components: 24".
- 🚀 **One-stop install.** The "Download & Install" button runs the whole flow in one shot — download → extract → auto-configure env vars → refresh card status — so you no longer need to click "Configure" afterwards.
- 🧠 **Preferences memory.** Remembers the last selected version per component.

---

## 2. Supported Components

> Since v2.0 the component count has grown from 8 to **24**, covering language runtimes, build tools, app servers, databases, containers & orchestration, CI/CD, message queues, service discovery / transaction, search engines, version control and Python distributions.

### Language Runtimes

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **JDK** | JDK (Temurin) | `JAVA_HOME` | `java -version` | 21 / 17 (LTS) / 11 / 8 |
| **Python** | Python | — (via PATH) | `python --version` | 3.12 / 3.11 / 3.10 / 3.9 |
| **Node.js** | Node.js | `NODE_HOME` | `node --version` | 20 LTS / 18 LTS / 16 |
| **Go** | Go (golang) | `GOPATH` / `GOROOT` | `go version` | 1.22.x / 1.21.x |
| **Bun** | Bun | — (via PATH) | `bun --version` | 1.x |

### Build Tools

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Maven** | Apache Maven | `MAVEN_HOME` | `mvn -v` | 3.9.x / 3.8.x |
| **Gradle** | Gradle | `GRADLE_HOME` | `gradle -v` | 8.x / 7.x |

### App Server

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Tomcat** | Apache Tomcat | `CATALINA_HOME` | `catalina version` | 10.1 / 9.0 / 8.5 |

### Databases

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **MySQL** | MySQL Server | `MYSQL_HOME` | `mysql --version` | 8.0.x / 5.7.x |
| **MongoDB** | MongoDB | — (via PATH) | `mongod --version` | 7.x / 6.x |
| **PostgreSQL** | PostgreSQL | `PG_HOME` | `psql --version` | 16.x / 15.x |

### Container & Orchestration

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Docker** | Docker Desktop | — (via PATH) | `docker --version` | latest |
| **kubectl** | Kubernetes CLI | — (via PATH) | `kubectl version --client` | 1.29.x / 1.28.x |

### CI/CD

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Jenkins** | Jenkins | `JENKINS_HOME` | `jenkins --version` | 2.x / LTS |

### Message Queues

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **RabbitMQ** | RabbitMQ | `RABBITMQ_HOME` | `rabbitmqctl version` | 3.13.x / 3.12.x |
| **Apache Kafka** | Apache Kafka | `KAFKA_HOME` | `kafka-server-start.sh --version` | 3.7.x / 3.6.x |
| **Apache RocketMQ** | Apache RocketMQ | `ROCKETMQ_HOME` | `mqadmin version` | 5.x / 4.x |
| **Apache Pulsar** | Apache Pulsar | `PULSAR_HOME` | `pulsar version` | 3.x |
| **ActiveMQ** | Apache ActiveMQ | `ACTIVEMQ_HOME` | `activemq --version` | 5.18.x / 5.17.x |

### Service Discovery / Transaction

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Nacos** | Nacos | `NACOS_HOME` | `sh startup.sh -m standalone` | 2.x / 1.x |
| **Seata** | Seata | `SEATA_HOME` | `sh seata-server.sh -h` | 2.x / 1.x |

### Search Engine

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Elasticsearch** | Elasticsearch | `ES_HOME` | `elasticsearch --version` | 8.x / 7.x |

### Version Control

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Git** | Git | — | `git --version` | MinGit for Windows / system-provided |

### Python Distribution

| Component | Display name | Env var | Detect command | Default versions |
|-----------|--------------|---------|----------------|------------------|
| **Miniconda** | Miniconda | `CONDA_HOME` | `conda --version` | py312 / py311 / py310 |

#### Platform limitations

- **Docker on Windows** — no auto-download. Docker Desktop requires its official installer (WSL2 / Hyper-V integration, service registration and other system-level configuration) and cannot be handled by a simple "download zip → extract" flow. The tool directs you to [docker.com](https://www.docker.com/products/docker-desktop/) to fetch the installer manually. macOS / Linux users get the normal download flow.
- **RabbitMQ on Windows** — no auto-download. RabbitMQ depends on Erlang at runtime; on Windows you must install Erlang first and then the RabbitMQ server, a typical "installer + service registration" scenario that is beyond this tool's "binary download + extract" model. The tool directs you to [rabbitmq.com](https://www.rabbitmq.com/download.html) for the official installer.
- **PostgreSQL on macOS** — no auto-download. The project only ships source / Homebrew formulae for macOS, with no ready-to-extract binary tarball. Use `brew install postgresql`.
- **MongoDB on macOS** — no auto-download. Use `brew install mongodb-community`.
- **Nacos / Seata** — no official China mirror. They are published on GitHub Releases; the tool accelerates them transparently via [ghproxy](https://ghproxy.com/) / [gh.idayer.com](https://gh.idayer.com/), and the active proxy source is shown in the log.

> 💡 After launching the app, click **"⟳ Refresh versions"** to pull the latest version list from each component's official source. If the fetch fails, the tool falls back to the built-in hardcoded list, so it still works offline.

---

## 3. Screenshot (ASCII sketch)

```
┌───────────────────────────────────────────────────────────────┐
│  Byte Tools By rgh                            ★ GitHub — ▢ × │
├───────────────────────────────────────────────────────────────┤
│  ┌─ JDK (Temurin) ────────────────────────────────────────┐   │
│  │  Configured: JAVA_HOME=/Users/x/.env-tools/jdk/jdk-17  │   │
│  │  Version [17 ▾]   [Install]  [Configure Only]  [Cancel]│   │
│  │  ████████████████░░░░░  85%                            │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
│  Log:                                                          │
│  [JDK] Downloading https://api.adoptium.net/v3/binary/...      │
│  [JDK] Extracted to /Users/x/.env-tools/jdk/jdk-17             │
│  [JDK] JAVA_HOME set                                           │
└───────────────────────────────────────────────────────────────┘
```

---

## 4. Quick Start

### 0. One-click Start on Windows (Recommended)

The project ships a one-click launcher [`start-windows.bat`](./start-windows.bat) in the root directory — **just double-click it**, no command-line work needed:

1. Checks the Python version (≥ 3.9 required; exits with a hint if not satisfied)
2. Creates a `.venv` virtual environment automatically
3. Installs dependencies from `requirements.txt` via the **Tsinghua PyPI mirror** (faster inside China)
4. Launches `main.py` and brings up the GUI

```text
double-click start-windows.bat  →  auto-configure + launch GUI
```

> 💡 The script uses the Tsinghua PyPI mirror to avoid the slow / timeout-prone access to the official PyPI source from inside China. If you need a custom dependency source, use the manual flow below.

### Manual setup (for macOS / Linux or customization)

#### Requirements

- Python **3.9+**
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

1. Pick the card for the component you want.
2. Choose a version from the drop-down.
3. Click **"Download & Install"** — a one-stop flow that runs automatically:
    - the archive is streamed to `~/.env-tools/<component>/downloads/` (China mirrors first per the R1 rule; cancelable at any time);
    - it is extracted to `~/.env-tools/<component>/<component>-<version>/` (Miniconda runs its silent installer);
    - the corresponding `XXX_HOME` variable is written and the `bin` directory is appended to `PATH`;
    - the card status is refreshed automatically — no need to click "Configure" afterwards.
4. Already downloaded the archive manually but not configured? Click **"Configure Only"** to only write the environment variables.
5. All actions are echoed to the log panel (full Chinese logs, including mirror switching / failover).

### Applying variables

- **Windows:** any new console window will see the fresh user variables. Restart already-open windows.
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

> **Since v2.0 the R1 China-mirror-priority rule is built in, so ordinary users do not need to change URLs manually.** The notes below are for users who want to understand the mechanism or do secondary development.

Every component is configured with ≥2 China mirrors (Huawei Cloud / Tsinghua TUNA / Aliyun / USTC / NJU) plus one official source. The download flow follows the **"China mirrors first → multi-source failover → official site last"** rule:

1. Try the China mirrors in order; on 404 / timeout / connection failure, switch to the next one immediately.
2. Only fall back to the official site after every China mirror has failed.
3. The whole process is logged in Chinese (which mirror failed, which one it switched to, which source finally served the file).

Net effect: **users inside China no longer need to edit any URL** to enjoy China-mirror acceleration — a big UX upgrade over the old "manually edit the URL function" approach.

> 📖 For the full technical implementation of the R1 rule (mirror list configuration, failover strategy, and how Nacos / Seata — which have no China mirror — are accelerated via ghproxy / gh.idayer.com GitHub-release proxies), see the **R1 China Mirror Priority Rule** section in [`DEVELOPMENT.md`](./DEVELOPMENT.md).

### Change the working directory

Update the constant at the top of `main.py`:

```python
CONFIG_DIR = Path.home() / ".env-tools"
```

---

## 7. FAQ

**Q1. Download stuck at some percentage?**
Likely a slow or failed mirror. Since v2.0 the tool auto-fails over between China mirrors and the official site, so just click **Cancel** and retry — it will try the next source automatically. See [Change the download mirror](#change-the-download-mirror) for the mechanism.

**Q2. Env-variable write fails?**
- Windows: relaunch as Administrator if you need system-scope variables. The tool defaults to **user scope**, which usually doesn't require elevation.
- macOS / Linux: make sure your shell rc files are writable.

**Q3. Will my existing `JAVA_HOME` be overwritten?**
Yes — the most recent installation wins. The new `bin` directory is appended to `PATH` idempotently.

**Q4. `.tar.xz` archives?**
Supported (MySQL Linux distribution uses it).

**Q5. `setx` truncation on Windows?**
The tool bypasses `setx`'s 1024-char limit by writing to the registry with `winreg`.

**Q6. Why does Docker on Windows say "no download available"?**
Docker Desktop must use its official installer (it involves WSL2 / Hyper-V integration, service registration and other system-level configuration) and cannot be handled by a simple "download zip → extract" flow. The tool does not auto-download Docker on Windows; it directs you to [docker.com](https://www.docker.com/products/docker-desktop/) to fetch the installer manually. macOS / Linux users get the normal download flow.

**Q7. Why can't RabbitMQ be auto-downloaded on Windows?**
RabbitMQ depends on Erlang at runtime. On Windows you must install Erlang first and then the RabbitMQ server — a typical "installer + service registration" scenario that is beyond the scope of this tool's "binary download + extract" model. The tool directs you to [rabbitmq.com](https://www.rabbitmq.com/download.html) for the official installer.

**Q8. Are downloads slow inside China?**
No. Since v2.0 the built-in R1 China-mirror-priority rule gives every component at least 2 China mirrors (Huawei Cloud / Tsinghua TUNA / Aliyun / USTC / NJU, etc.) plus one official source. Downloads try them in order and automatically switch to the next one on 404 / timeout, with full Chinese logs (which mirror failed, which one it switched to, which one finally served the file). Ordinary users do not need to configure anything manually.

**Q9. After clicking "Download & Install", do I still need to configure env vars manually?**
No. The "Download & Install" button is a **one-stop flow**: download → extract → auto-write `XXX_HOME` / `PATH` → refresh the card status. Once the flow finishes, the component is considered installed; you do not need to click "Configure Only" afterwards. That button is only for the case where you have already downloaded the archive manually and just want to write the environment variables.

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
├─ start-windows.bat    # Windows one-click launcher (checks Python → creates .venv → installs deps via Tsinghua PyPI mirror → launches GUI)
├─ requirements.txt     # dependency list
├─ byte-tools.spec  # PyInstaller build spec
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
