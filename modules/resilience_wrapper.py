#!/usr/bin/env python3
"""
modules/resilience_wrapper.py — Crash-isolation wrapper for Niblit modules.

Ensures that one module failing never cascades into bringing down the whole
system. Every wrapped call is isolated; failures are caught, logged, and
reported to NiblitKernel for self-repair scheduling.

Usage::

    from modules.resilience_wrapper import safe_init, safe_call, resilient

    # Safe module initialization:
    my_module = safe_init("MyModule", MyClass, arg1, arg2, kernel=kernel)

    # Safe method call:
    result = safe_call("MyModule.method", my_module.method, arg1, default="fallback")

    # Decorator:
    @resilient("my_operation", default=None)
    def my_fn():
        ...
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional, Type, TypeVar

log = logging.getLogger("ResilienceWrapper")

# ── Optional kernel import ────────────────────────────────────────────────────
try:
    from modules.niblit_kernel import NiblitKernel
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    NiblitKernel = None  # type: ignore[assignment,misc]

T = TypeVar("T")


# ══════════════════════════════════════════════════════════════════════════════
# safe_init
# ══════════════════════════════════════════════════════════════════════════════

def safe_init(
    name: str,
    cls: Type[T],
    *args: Any,
    kernel: Any = None,
    **kwargs: Any,
) -> Optional[T]:
    """
    Safely instantiate *cls* with the given arguments.

    If construction raises any exception the error is caught, logged, and
    (optionally) reported to *kernel*.  ``None`` is returned instead of
    propagating the exception.

    Parameters
    ----------
    name:
        Human-readable label for this module — used in log messages and
        kernel reports.
    cls:
        The class to instantiate.
    *args:
        Positional arguments forwarded to ``cls.__init__``.
    kernel:
        Optional :class:`~modules.niblit_kernel.NiblitKernel` instance.
        When provided, any construction error is reported via
        ``kernel.report_error``.
    **kwargs:
        Keyword arguments forwarded to ``cls.__init__``.

    Returns
    -------
    instance or None
        The constructed object on success, ``None`` on failure.
    """
    try:
        instance = cls(*args, **kwargs)
        log.debug("[ResilienceWrapper] safe_init '%s' succeeded.", name)
        return instance
    except Exception as exc:
        log.error("[ResilienceWrapper] safe_init '%s' failed: %s", name, exc)
        if kernel is not None:
            try:
                kernel.report_error(name, exc, context={"phase": "init", "cls": cls.__name__})
            except Exception:  # pragma: no cover
                pass
        return None


# ══════════════════════════════════════════════════════════════════════════════
# safe_call
# ══════════════════════════════════════════════════════════════════════════════

def safe_call(
    label: str,
    fn: Callable,
    *args: Any,
    default: Any = None,
    kernel: Any = None,
    **kwargs: Any,
) -> Any:
    """
    Safely call *fn* and return *default* if it raises.

    Parameters
    ----------
    label:
        Human-readable label for this call (e.g. ``"MyModule.my_method"``).
    fn:
        The callable to invoke.
    *args:
        Positional arguments forwarded to *fn*.
    default:
        Value returned when *fn* raises an exception.
    kernel:
        Optional kernel for error reporting.
    **kwargs:
        Keyword arguments forwarded to *fn*.

    Returns
    -------
    Any
        The return value of *fn*, or *default* on failure.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        log.error("[ResilienceWrapper] safe_call '%s' failed: %s", label, exc)
        if kernel is not None:
            try:
                kernel.report_error(label, exc, context={"phase": "call", "fn": str(fn)})
            except Exception:  # pragma: no cover
                pass
        return default


# ══════════════════════════════════════════════════════════════════════════════
# resilient — decorator factory
# ══════════════════════════════════════════════════════════════════════════════

def resilient(
    label: str,
    default: Any = None,
    kernel: Any = None,
) -> Callable:
    """
    Return a decorator that wraps a function with :func:`safe_call` semantics.

    Parameters
    ----------
    label:
        Human-readable operation label used in log messages and kernel reports.
    default:
        Value returned if the wrapped function raises.
    kernel:
        Optional kernel for error reporting.

    Returns
    -------
    Callable
        Decorator that makes the target function resilient to exceptions.

    Example
    -------
    ::

        @resilient("fetch_data", default=[])
        def fetch_data():
            return requests.get(url).json()
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return safe_call(label, fn, *args, default=default, kernel=kernel, **kwargs)
        return wrapper
    return decorator


# ══════════════════════════════════════════════════════════════════════════════
# IsolatedModule
# ══════════════════════════════════════════════════════════════════════════════

class IsolatedModule:
    """
    A transparent proxy around an arbitrary object that catches every attribute
    access and wraps callable attributes with :func:`safe_call`.

    Any method call on an ``IsolatedModule`` is therefore crash-isolated: if
    the underlying method raises, the exception is swallowed, logged, and
    optionally reported to the kernel.

    Parameters
    ----------
    name:
        Human-readable module name (used in log / kernel reports).
    instance:
        The underlying object to proxy.
    kernel:
        Optional kernel for error reporting.
    """

    # Store our own attributes under mangled names to avoid conflicts with
    # __getattr__ interception on the wrapped instance.
    def __init__(self, name: str, instance: Any, kernel: Any = None) -> None:
        object.__setattr__(self, "_iso_name", name)
        object.__setattr__(self, "_iso_instance", instance)
        object.__setattr__(self, "_iso_kernel", kernel)

    def __getattr__(self, attr: str) -> Any:
        """
        Return a wrapped version of the underlying attribute.

        If the attribute is callable it is wrapped with :func:`safe_call`.
        Non-callable attributes are returned directly (attribute access errors
        are still caught and logged).
        """
        name = object.__getattribute__(self, "_iso_name")
        instance = object.__getattribute__(self, "_iso_instance")
        kernel = object.__getattribute__(self, "_iso_kernel")

        try:
            value = getattr(instance, attr)
        except AttributeError as exc:
            log.error(
                "[ResilienceWrapper] IsolatedModule '%s' has no attribute '%s': %s",
                name, attr, exc,
            )
            raise

        if callable(value):
            label = f"{name}.{attr}"

            @functools.wraps(value)
            def _safe(*args: Any, **kwargs: Any) -> Any:
                return safe_call(label, value, *args, default=None, kernel=kernel, **kwargs)

            return _safe

        return value

    def is_alive(self) -> bool:
        """
        Return ``True`` if the underlying instance is not ``None``.

        Returns
        -------
        bool
        """
        instance = object.__getattribute__(self, "_iso_instance")
        return instance is not None

    def unwrap(self) -> Any:
        """
        Return the raw, unwrapped underlying instance.

        Returns
        -------
        Any
            The original object passed to the constructor.
        """
        return object.__getattribute__(self, "_iso_instance")

    def __repr__(self) -> str:
        name = object.__getattribute__(self, "_iso_name")
        instance = object.__getattribute__(self, "_iso_instance")
        return f"<IsolatedModule name={name!r} instance={instance!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# wrap_module
# ══════════════════════════════════════════════════════════════════════════════

def wrap_module(
    name: str,
    instance: Any,
    kernel: Any = None,
) -> IsolatedModule:
    """
    Wrap *instance* in an :class:`IsolatedModule` proxy.

    Parameters
    ----------
    name:
        Human-readable module name.
    instance:
        The object to wrap.
    kernel:
        Optional kernel for error reporting.

    Returns
    -------
    IsolatedModule
        The crash-isolated proxy.
    """
    return IsolatedModule(name=name, instance=instance, kernel=kernel)
