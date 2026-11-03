"""
Centralized configuration constants for byte-tools.

All magic numbers, strings, and configuration values are defined here
to improve maintainability and reduce duplication across the codebase.

Categories:
- Download parameters
- Version checking intervals
- Timeout values
- Cache durations
- UI display settings
- Security thresholds
"""
from pathlib import Path


# =============================================================================
# DOWNLOAD PARAMETERS (R1 rules)
# =============================================================================

HTTP_UA = {"User-Agent": "byte-tools"}
"""Custom User-Agent required by mirror sites (清华 TUNA/BFSU require this)."""

DOWNLOAD_MIN_VALID_BYTES = 4096
"""Minimum valid download size in bytes. Prevents accepting empty HTML pages."""

DOWNLOAD_PROBE_TIMEOUT = 5
"""Timeout for listing directory/index page probes (seconds)."""

DOWNLOAD_TIMEOUT = 30
"""Stream download connection/read timeout (seconds)."""

DOWNLOAD_RETRY_PER_URL = 2
"""Retry attempts per URL (exponential backoff). Not retried on 404/403."""

MAX_MIRROR_ATTEMPTS = 15
"""Maximum number of mirror + official source attempts before failing download."""


# =============================================================================
# VERSION FETCHING & CACHING
# =============================================================================

VERSION_CACHE_TTL = 24 * 3600  # 24 hours
"""How long version cache remains valid (seconds)."""

UPDATE_CHECK_INTERVAL_SEC = 24 * 3600
"""Maximum interval between auto-update checks (once per day)."""

UPDATE_HTTP_TIMEOUT = 8.0
"""Hard timeout for update check requests (seconds)."""

GITHUB_ANONYMOUS_RATE_LIMIT = 60
"""GitHub API calls per hour from anonymous IP."""

GITHUB_TOKEN_RATE_LIMIT = 5000
"""GitHub API rate limit when GITHUB_TOKEN environment variable is set."""

VERSION_FETCH_CONCURRENCY = 10
"""Max concurrent version fetch requests (semaphore limit)."""


# =============================================================================
# NETWORK & TIMEOUTS
# =============================================================================

NETWORK_TIMEOUT_SHORT = 5  # Fast operations
NETWORK_TIMEOUT_NORMAL = 15  # Normal operations
NETWORK_TIMEOUT_LONG = 60  # Large downloads

PORT_PROBE_TIMEOUT = 2
"""Timeout for port listening probe (seconds)."""

# Additional timeout values from main.py (for backward compatibility)
DOWNLOAD_PROBE_TIMEOUT = 5     # Single URL probe timeout (seconds)
DOWNLOAD_CONNECT_TIMEOUT = 10
DOWNLOAD_READ_TIMEOUT = 60
DEVTOOL_FETCH_TIMEOUT = 15
_JAVA_MAJOR_TIMEOUT = 20
TK_SUPPRESS_BG_LIMIT = 600      # Background thread poll upper limit (600 × 50ms = 30s, prevents runaway)

# =============================================================================
# FILE OPERATIONS & SECURITY
# =============================================================================

SAFE_PATH_PREFIX = ".env-tools"
"""Required prefix for all tool-managed paths (security against path traversal)."""

MIN_ARCHIVE_VALID_SIZE = 1024
"""Minimum valid archive size to reject corrupted downloads."""

SHUTIL_Rmtree_IGNORE_ERRORS = False
"""Whether to use ignore_errors=True on shutil.rmtree. Should be False for safety."""


# =============================================================================
# SERVICE MANAGEMENT
# =============================================================================

SERVICE_STOP_TIMEOUT = 10
"""Maximum seconds to wait for service to stop gracefully."""

SERVICE_START_TIMEOUT = 30
"""Maximum seconds to wait for service to become listening."""

SERVICE_STATUS_CHECK_INTERVAL = 0.5
"""Interval between status polling checks (seconds)."""


# =============================================================================
# UI DISPLAY SETTINGS
# =============================================================================

LOG_MAX_ITEMS = 100
"""Maximum log entries kept in memory."""

CARD_LAYOUT_COLUMNS_MIN = 1
CARD_LAYOUT_COLUMNS_MAX = 5
"""Grid layout column range based on window width."""

PROGRESS_UPDATE_INTERVAL_MS = 100
"""Minimum milliseconds between progress bar updates."""


# =============================================================================
# ENVIRONMENT PATH MANAGEMENT
# =============================================================================

PATH_ENTRY_LIMIT = 1024
"""Windows PATH entry character warning threshold."""

ENV_VAR_MAX_LENGTH = 32767
"""System environment variable length limit (Windows)."""

USER_VAR_MAX_LENGTH = 32767
"""User environment variable length limit (Windows)."""


# =============================================================================
# WORK DIRECTORIES
# =============================================================================

CONFIG_DIR = Path.home() / ".env-tools"
"""Root directory for all tool data."""

DOWNLOADS_SUBDIR = "downloads"
"""Subdirectory within CONFIG_DIR for compressed archives."""

DATA_DIR = Path.home() / ".env-tools-data"
"""Directory for persistent data like MySQL dumps, Redis persistence."""

RUNNING_FILE = CONFIG_DIR / "running.json"
"""File tracking which services are currently running."""


# =============================================================================
# MIRROR SITES (R1.3 table)
# =============================================================================

MIRROR_BASES = [
    ("huaweicloud", "https://repo.huaweicloud.com"),
    ("huaweicloud-py", "https://mirrors.huaweicloud.com"),
    ("tuna", "https://mirrors.tuna.tsinghua.edu.cn"),
    ("aliyun", "https://mirrors.aliyun.com"),
    ("nju", "https://mirrors.nju.edu.cn"),
    ("ustc", "https://mirrors.ustc.edu.cn"),
    ("bfsu", "https://mirrors.bfsu.edu.cn"),
    ("tencent", "https://mirrors.cloud.tencent.com"),
    ("sjtug", "https://mirrors.sjtug.org"),
    ("npmmirror", "https://registry.npmmirror.com"),
    ("daocloud-files", "https://files.m.daocloud.io"),
]

GH_ACCELERATORS = [
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
]

OFFICIAL_ONLY_EXCEPTIONS = {
    "consul",      # releases.hashicorp.com - no accelerator
    "mongodb",     # fastdl.mongodb.org - mainland mirrors don't have binaries
    "postgresql",  # get.enterprisedb.com - only source tarballs in China
}


# =============================================================================
# COMPATIBILITY CONSTANTS
# =============================================================================

PYTEST_RUNNER_SCRIPT = "tests/run_all_tests.py"
"""Script to run offline test suite without pytest discovery issues."""

MAIN_PY_PATH = "main.py"
"""Path to main application entry point."""

CODE_WIKI_MD = "CODE_WIKI.md"
"""Code documentation file location."""

DEVELOPMENT_MD = "DEVELOPMENT.md"
"""Developer rules document location."""
