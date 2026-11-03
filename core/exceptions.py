"""
Custom exception hierarchy for byte-tools.

Replaces generic Exception catches with specific, actionable exception types.
Provides context-rich error messages matching UI log color scheme.

Usage pattern:
    try:
        risky_operation()
    except ComponentDownloadError as exc:
        logger.error(f"Download failed: {exc}")
    except ServiceStartFailedError as exc:
        handle_service_failure(exc)
"""
from typing import Optional, List


import requests


BEST_EFFORT_ERRORS = (
    requests.RequestException,
    OSError,
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    RuntimeError,
)
"""「尽力而为」路径允许吞掉的异常集合。

用于版本抓取 / 探测这类**失败也不影响主流程**的地方：网络错误、
解析形状不符、上游字段改名。它刻意**不**包含 BaseException
（KeyboardInterrupt / SystemExit 必须穿透），也不包含 MemoryError。

UI 线程的最后一道兜底仍可写 `except Exception`，但必须注明原因（R30）。
"""


class ByteToolsException(Exception):
    """Base exception for all byte-tools custom exceptions."""
    
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.details = details
    
    def __str__(self) -> str:
        if self.details:
            return f"{self.message}\n{self.details}"
        return self.message


# =============================================================================
# DOWNLOAD EXCEPTIONS
# =============================================================================

class ComponentDownloadError(ByteToolsException):
    """Raised when component download fails after exhausting all sources."""
    pass


class MirrorFailureError(ByteToolsException):
    """Single mirror source failed, but other sources may be tried."""
    pass


class ArchiveExtractionError(ByteToolsException):
    """Archive extraction failed (corrupted, wrong format, etc.)."""
    pass


class InvalidUrlError(ByteToolsException):
    """Invalid URL construction or inaccessible remote resource."""
    pass


# =============================================================================
# INSTALLATION & CONFIGURATION EXCEPTIONS
# =============================================================================

class InstallationError(ByteToolsException):
    """Generic installation failure."""
    pass


class EnvironmentVariableError(ByteToolsException):
    """Failed to set/read environment variables."""
    pass


class PathValidationError(ByteToolsException):
    """Path security validation failed (e.g., potential path traversal attack)."""
    pass


class VersionSwitchError(ByteToolsException):
    """Failed to switch active version (rollback needed)."""
    pass


# =============================================================================
# SERVICE MANAGEMENT EXCEPTIONS
# =============================================================================

class ServiceStartFailedError(ByteToolsException):
    """Service failed to start within timeout or port binding error."""
    pass


class ServiceStopFailedError(ByteToolsException):
    """Service failed to stop gracefully within timeout."""
    pass


class PortInUseError(ByteToolsException):
    """Requested port already in use by another process."""
    pass


class WindowsServiceError(ByteToolsException):
    """Windows Service Manager operation failed."""
    pass


class ServiceNotFoundException(ByteToolsException):
    """Specified service not found in Windows SCM."""
    pass


# =============================================================================
# VERSION FETCHING EXCEPTIONS
# =============================================================================

class VersionFetchError(ByteToolsException):
    """Failed to fetch latest version list from official sources."""
    pass


class VersionParsingError(ByteToolsException):
    """Version string cannot be parsed or compared."""
    pass


class CacheExpiredError(ByteToolsException):
    """Version cache expired and refresh failed."""
    pass


# =============================================================================
# PROCESS SUBPROCESS EXCEPTIONS
# =============================================================================

class SubprocessTimeoutError(ByteToolsException):
    """Process did not complete within expected timeout."""
    pass


class SubprocessExecutionError(ByteToolsException):
    """Command-line tool returned non-zero exit code."""
    pass


class CommandNotFoundError(ByteToolsException):
    """Required command not found in PATH."""
    pass


# =============================================================================
# SECURITY EXCEPTIONS
# =============================================================================

class SecurityValidationError(ByteToolsException):
    """Security check failed (path traversal, injection attempt, etc.)."""
    pass


class UnsafePathError(SecurityValidationError):
    """File path contains security risks (.. traversal, empty prefix, etc.)."""
    pass


# =============================================================================
# UI/THREAD EXCEPTIONS
# =============================================================================

class ThreadAbortError(ByteToolsException):
    """Worker thread aborted before completion."""
    pass


class UICallbackError(ByteToolsException):
    """UI callback function raised unexpected exception."""
    pass


# =============================================================================
# ERROR HANDLING DECORATOR
# =============================================================================

def retry_on_error(max_retries: int = 3, delay_seconds: float = 1.0):
    """
    Decorator to retry function on specific recoverable exceptions.
    
    Args:
        max_retries: Maximum retry attempts
        delay_seconds: Base delay between retries (exponential backoff)
    """
    import time
    from functools import wraps
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (MirrorFailureError, ComponentDownloadError) as exc:
                    last_exception = exc
                    if attempt < max_retries - 1:
                        wait_time = delay_seconds * (2 ** attempt)
                        print(f"Retry {attempt + 1}/{max_retries} "
                              f"in {wait_time:.1f}s: {exc}")
                        time.sleep(wait_time)
                    else:
                        raise ComponentDownloadError(
                            f"All {max_retries} attempts failed",
                            details=str(last_exception)
                        ) from last_exception
        
        return wrapper
    
    return decorator


# =============================================================================
# CONTEXT MANAGER FOR SAFE Rmtree
# =============================================================================

from pathlib import Path
import shutil
from typing import Union

def safe_rmtree(
    path: Union[str, Path],
    verify_deleted: bool = True,
    allowed_root: Optional[Union[str, Path]] = None,
) -> None:
    """
    Safely remove directory tree with optional verification.

    Security features:
    - Validates the resolved path is inside an allowed root
      (default: ~/.env-tools; callers with a relocatable root must pass allowed_root)
    - Does NOT use ignore_errors=True (reports real errors)
    - Verifies deletion if requested
    - Missing path is a no-op (idempotent uninstall)

    Args:
        path: Directory path to remove
        verify_deleted: Whether to verify path was actually deleted
        allowed_root: Root directory the target must stay inside

    Raises:
        UnsafePathError: Path traverses outside the allowed root
        InstallationError: Removal failed for a non-security reason
        RuntimeError: Verification shows directory still exists
    """
    path = Path(path).resolve()
    root = Path(allowed_root) if allowed_root is not None else Path.home() / ".env-tools"
    root = root.resolve()

    # Validate path safety (contains, not string-prefix: avoids /a/.env-tools-evil)
    try:
        path.relative_to(root)
    except ValueError:
        raise UnsafePathError(
            f"Path traversal detected: {path}",
            details=f"Allowed root: {root}",
        ) from None

    if not path.exists():
        return

    try:
        shutil.rmtree(path)
    except OSError as e:
        raise InstallationError(
            f"Failed to remove directory: {path}",
            details=str(e),
        ) from e

    if verify_deleted and path.exists():
        raise InstallationError(
            f"Directory verification failed: {path}",
            details="Still exists after rmtree()",
        )


# =============================================================================
# NICE CATCH PATTERN FOR UI THREADS
# =============================================================================

def catch_for_ui_thread(
    default_return_value=None,
    logger_callback=None
):
    """
    Context manager for catching exceptions in UI threads.
    
    Usage:
        with catch_for_ui_thread(logger=ui_log_callback) as ctx:
            result = ui_task()
            if ctx.failed:
                handle_error(ctx.exception)
    """
    class CatchContext:
        def __init__(self):
            self.failed = False
            self.exception = None
            self.return_value = default_return_value
        
        def __enter__(self):
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            self.failed = exc_type is not None
            self.exception = exc_val
            if exc_type is not None and logger_callback:
                logger_callback({
                    "level": "ERROR",
                    "message": str(exc_val),
                    "color": "red"
                })
            return True  # Suppress exception propagation
    
    return CatchContext()
