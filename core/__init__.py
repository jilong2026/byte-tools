"""
Core modules package for byte-tools.

Exports common utilities for backward compatibility with existing code.
"""
from .exceptions import (
    ByteToolsException,
    ComponentDownloadError,
    safe_rmtree,
    UnsafePathError,
)
from .logger import get_logger, LogLevel
from .versioning import Version, version_is_newer

# Re-export constants for easy access
from .constants import CONFIG_DIR

__all__ = [
    "ByteToolsException",
    "ComponentDownloadError",
    "safe_rmtree",
    "UnsafePathError",
    "get_logger",
    "LogLevel",
    "Version",
    "version_is_newer",
    "CONFIG_DIR",
]
