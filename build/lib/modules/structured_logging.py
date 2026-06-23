#!/usr/bin/env python3
"""
Structured Logging with Correlation IDs

Enables:
- Request tracing across system
- Structured JSON logs
- grep-able by correlation_id
- Full execution path visibility
"""

import logging
import json
import os
import uuid
import contextvars
from typing import Any, Dict, Optional
from datetime import datetime
from pathlib import Path

# Context variable for correlation ID
correlation_id_var = contextvars.ContextVar('correlation_id', default=None)


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if hasattr(record, "correlation_id"):
            log_obj["correlation_id"] = record.correlation_id

        for key, value in record.__dict__.items():
            if key not in [
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "message",
                "pathname", "process", "processName", "thread", "threadName",
                "exc_info", "exc_text", "stack_info",
            ]:
                log_obj[key] = value

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            log_obj["exc_type"] = exc_type.__name__ if exc_type else None
            log_obj["exc_message"] = str(exc_value) if exc_value else None

        return json.dumps(log_obj)


class RuntimeLogger:
    """Logger wrapper that accepts structured keyword arguments for runtime diagnostics."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self.name = logger.name

    def _emit(self, level: int, msg: str, **kwargs: Any) -> None:
        extra = kwargs.pop("extra", {})
        payload = dict(extra)
        payload.update(kwargs)
        self._logger.log(level, msg, extra=payload)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.CRITICAL, msg, **kwargs)

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.ERROR, msg, **kwargs)

    def setLevel(self, level: int) -> None:
        self._logger.setLevel(level)

    def addHandler(self, handler: logging.Handler) -> None:
        self._logger.addHandler(handler)

    def removeHandler(self, handler: logging.Handler) -> None:
        self._logger.removeHandler(handler)

    @property
    def handlers(self):
        return self._logger.handlers

    @property
    def propagate(self):
        return self._logger.propagate

    @propagate.setter
    def propagate(self, value: bool) -> None:
        self._logger.propagate = value


def configure_runtime_logging(
    log_file: Optional[Path | str] = None,
    level: int = logging.INFO,
    name: str = "NiblitRuntime",
) -> RuntimeLogger:
    """Create a logger that writes human-readable console output and JSON file output."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    resolved_log_file = None
    if log_file is not None:
        resolved_log_file = Path(log_file)
        if not resolved_log_file.is_absolute():
            resolved_log_file = (Path.cwd() / resolved_log_file).resolve()
        resolved_log_file.parent.mkdir(parents=True, exist_ok=True)

    has_file_handler = any(
        isinstance(handler, logging.FileHandler)
        and getattr(handler, "baseFilename", None) == str(resolved_log_file.resolve())
        for handler in logger.handlers
    ) if resolved_log_file is not None else False
    if resolved_log_file is not None and not has_file_handler:
        file_handler = logging.FileHandler(resolved_log_file)
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)

    has_stream_handler = any(type(handler) is logging.StreamHandler for handler in logger.handlers)
    if not has_stream_handler:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s"))
        logger.addHandler(stream_handler)

    return RuntimeLogger(logger)


def log_exception(logger: logging.Logger, operation: str, exc: BaseException, **extra: Any) -> None:
    """Log a caught exception with structured context for later diagnosis."""
    payload = {
        "operation": operation,
        "error": str(exc),
        "exc_type": type(exc).__name__,
    }
    payload.update(extra)
    logger.exception("[RUNTIME ERROR] %s", operation, extra=payload)


class StructuredLogger:
    """Structured logging with correlation IDs."""

    def __init__(self, name: str, log_file: Optional[Path] = None):
        self.logger = logging.getLogger(name)
        self.name = name
        self.log_file = log_file

        # Set up JSON formatter - only add handlers if not already present to
        # prevent duplicate log entries when StructuredLogger is instantiated
        # multiple times for the same logger name (e.g. inside RequestContext).
        if log_file:
            log_file_abs = str(Path(log_file).resolve())
            if not any(
                isinstance(h, logging.FileHandler)
                and str(Path(getattr(h, 'baseFilename', '')).resolve()) == log_file_abs
                for h in self.logger.handlers
            ):
                handler = logging.FileHandler(log_file)
                handler.setFormatter(JSONFormatter())
                self.logger.addHandler(handler)

        # Add console StreamHandler only if one is not already attached.
        # Use exact type check (not isinstance) so that FileHandler subclasses
        # (which are also StreamHandlers) are not mistaken for console handlers.
        has_stream = any(
            type(h) is logging.StreamHandler  # noqa: E721 — exact type, not isinstance
            for h in self.logger.handlers
        )
        if not has_stream:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(JSONFormatter())
            # Apply the notification-queue filter so background-thread records
            # don't flood the console.  Safe to call even before the queue
            # handler is installed (it will be a no-op).
            try:
                from core.notification_queue import apply_filter_to_handler
                apply_filter_to_handler(console_handler)
            except Exception:
                pass
            self.logger.addHandler(console_handler)

    def _get_context(self) -> Dict[str, Any]:
        """Get logging context."""
        correlation_id = correlation_id_var.get()
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
            correlation_id_var.set(correlation_id)

        return {
            "correlation_id": correlation_id,
            "timestamp": datetime.now().isoformat(),
        }

    def debug(self, message: str, **kwargs):
        """Log debug message."""
        context = self._get_context()
        self.logger.debug(message, extra={**context, **kwargs})

    def info(self, message: str, **kwargs):
        """Log info message."""
        context = self._get_context()
        self.logger.info(message, extra={**context, **kwargs})

    def warning(self, message: str, **kwargs):
        """Log warning message."""
        context = self._get_context()
        self.logger.warning(message, extra={**context, **kwargs})

    def error(self, message: str, **kwargs):
        """Log error message."""
        context = self._get_context()
        self.logger.error(message, extra={**context, **kwargs})

    def critical(self, message: str, **kwargs):
        """Log critical message."""
        context = self._get_context()
        self.logger.critical(message, extra={**context, **kwargs})


class RequestContext:
    """Context manager for request tracing."""

    def __init__(self, operation: str, correlation_id: Optional[str] = None):
        self.operation = operation
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.logger = StructuredLogger(__name__)

    def __enter__(self):
        """Enter context."""
        correlation_id_var.set(self.correlation_id)
        self.logger.info(
            f"[ENTER] {self.operation}",
            operation=self.operation,
            correlation_id=self.correlation_id
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context."""
        if exc_type:
            self.logger.error(
                f"[ERROR] {self.operation}",
                operation=self.operation,
                error=str(exc_val),
                exc_type=exc_type.__name__,
            )
        else:
            self.logger.info(
                f"[EXIT] {self.operation}",
                operation=self.operation,
            )


# Example usage
if __name__ == "__main__":
    logger = StructuredLogger("test", Path("test.jsonl"))

    # Simple logging
    logger.info("Application started", version="1.0")

    # With context
    with RequestContext("command_execution") as ctx:
        logger.debug("Processing command", command="help")
        logger.info("Command executed", result="success")

    # Check logs
    print("Logs written to test.jsonl")
