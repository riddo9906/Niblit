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
import uuid
import contextvars
from typing import Any, Dict, Optional
from datetime import datetime
from pathlib import Path

# Context variable for correlation ID
correlation_id_var = contextvars.ContextVar('correlation_id', default=None)


class StructuredLogger:
    """Structured logging with correlation IDs."""
    
    def __init__(self, name: str, log_file: Optional[Path] = None):
        self.logger = logging.getLogger(name)
        self.name = name
        self.log_file = log_file
        
        # Set up JSON formatter
        if log_file:
            handler = logging.FileHandler(log_file)
            handler.setFormatter(JSONFormatter())
            self.logger.addHandler(handler)
        
        # Also add console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(JSONFormatter())
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
        
        # Add extra fields
        if hasattr(record, "correlation_id"):
            log_obj["correlation_id"] = record.correlation_id
        
        # Add any extra kwargs
        for key, value in record.__dict__.items():
            if key not in [
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "message",
                "pathname", "process", "processName", "thread", "threadName",
            ]:
                log_obj[key] = value
        
        return json.dumps(log_obj)


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
