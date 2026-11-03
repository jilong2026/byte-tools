"""
Structured logging for byte-tools.

Provides four UI-aligned levels (info / ok / warn / error), an optional UI
callback, and JSON diagnostic export. Built on the standard logging module so
files, handlers and formatters keep working.

Note: this module deliberately keeps the public methods (ok/info/warn/error)
thin wrappers around ``logging.Logger`` internals. Do not call them from inside
``_emit`` — that is what caused unbounded recursion in the first draft.
"""
import json
import logging
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class LogLevel(Enum):
    """Log level matching the byte-tools UI color scheme."""

    INFO = "INFO"
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"

    def to_color(self) -> str:
        return {
            LogLevel.INFO: "gray",
            LogLevel.OK: "green",
            LogLevel.WARNING: "orange",
            LogLevel.ERROR: "red",
        }[self]

    @staticmethod
    def from_level_str(level_str: str) -> "LogLevel":
        return {
            "info": LogLevel.INFO,
            "ok": LogLevel.OK,
            "warning": LogLevel.WARNING,
            "warn": LogLevel.WARNING,
            "error": LogLevel.ERROR,
        }.get(str(level_str).lower(), LogLevel.INFO)


class StructuredLogger(logging.Logger):
    """Logger with UI-aligned levels and a bounded in-memory history."""

    def __init__(self, name: str, level: int = logging.INFO) -> None:
        super().__init__(name, level)
        self._history: List[Dict[str, Any]] = []
        self._emit_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    # -- configuration -------------------------------------------------
    def set_emit_callback(self, callback: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        self._emit_callback = callback

    # -- public API ----------------------------------------------------
    def ok(self, msg: str, *args: Any) -> None:
        self._emit(LogLevel.OK, msg, args)

    def info(self, msg: str, *args: Any) -> None:  # noqa: D401 - logging override
        self._emit(LogLevel.INFO, msg, args)

    def warn(self, msg: str, *args: Any) -> None:
        self._emit(LogLevel.WARNING, msg, args)

    def warning(self, msg: str, *args: Any) -> None:
        self._emit(LogLevel.WARNING, msg, args)

    def error(self, msg: str, *args: Any) -> None:
        self._emit(LogLevel.ERROR, msg, args)

    def exception(self, msg: str, *args: Any) -> None:
        self._emit(LogLevel.ERROR, msg, args, exc_info=True)

    # -- internals -----------------------------------------------------
    def _emit(self, level: LogLevel, msg: str, args: tuple, exc_info: bool = False) -> None:
        # Route through logging.Logger directly: calling self.info() here
        # would re-enter _emit (unbounded recursion).
        log_method = {
            LogLevel.OK: super().info,
            LogLevel.INFO: super().info,
            LogLevel.WARNING: super().warning,
            LogLevel.ERROR: super().error,
        }[level]
        log_method(msg, *args, exc_info=exc_info)

        try:
            rendered = msg % args if args else msg
        except (TypeError, ValueError):
            rendered = " ".join([msg, *[str(a) for a in args]])

        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "level": level.value,
            "color": level.to_color(),
            "source": self.name,
            "message": rendered,
        }
        self._history.append(entry)
        if len(self._history) > 500:
            del self._history[: len(self._history) - 500]

        if self._emit_callback is not None:
            try:
                self._emit_callback(entry)
            except Exception:  # noqa: BLE001 - logging must never break the caller
                pass

    # -- diagnostics ---------------------------------------------------
    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent structured entries (oldest first)."""
        if limit <= 0:
            return []
        return list(self._history[-limit:])

    def export_json(self, filepath: Path) -> None:
        payload = {
            "export_time": datetime.now().isoformat(),
            "logger_name": self.name,
            "messages": self._history,
        }
        Path(filepath).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )


_loggers: Dict[str, StructuredLogger] = {}


def get_logger(name: str) -> StructuredLogger:
    """Return (and register) a named StructuredLogger."""
    if name not in _loggers:
        logging.setLoggerClass(StructuredLogger)
        _loggers[name] = StructuredLogger(name)
    return _loggers[name]


def setup_logging(
    log_file: Optional[Path] = None,
    console_output: bool = True,
) -> None:
    """Configure the root logger with console and/or file handlers."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if console_output:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def format_diagnostic_log(messages: List[Dict[str, Any]]) -> str:
    """Render history entries as a human-readable diagnostic report."""
    lines = [
        "=" * 80,
        "BYTE-TOOLS DIAGNOSTIC LOG",
        f"Generated: {datetime.now().isoformat()}",
        "=" * 80,
        "",
    ]
    for msg in messages:
        lines.append(
            "[{ts}] [{level:<7}] [{source}] {message}".format(
                ts=msg.get("timestamp", ""),
                level=msg.get("level", "INFO"),
                source=msg.get("source", "unknown"),
                message=msg.get("message", ""),
            )
        )
    lines.extend(["", "=" * 80])
    return "\n".join(lines)
