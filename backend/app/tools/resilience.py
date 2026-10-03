"""Safe tool invocation helpers: retries, typed failures, no silent success."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


class ToolFailureKind(str, Enum):
    NOT_FOUND = "not_found"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CONFIG = "config"
    UNEXPECTED = "unexpected"


@dataclass
class ToolResult:
    ok: bool
    value: Any = None
    error: str | None = None
    failure_kind: ToolFailureKind | None = None
    attempts: int = 1
    tool_name: str = ""
    fallback_applied: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.failure_kind is not None:
            payload["failure_kind"] = self.failure_kind.value
        return payload


def call_tool(
    tool_name: str,
    fn: Callable[..., T],
    *args: Any,
    retries: int = 1,
    retry_on: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError, OSError),
    **kwargs: Any,
) -> ToolResult:
    """Invoke a tool with limited retries. Never pretends success on failure."""
    attempts = 0
    last_error: BaseException | None = None
    max_attempts = max(1, retries + 1)

    while attempts < max_attempts:
        attempts += 1
        try:
            value = fn(*args, **kwargs)
            return ToolResult(ok=True, value=value, attempts=attempts, tool_name=tool_name)
        except retry_on as exc:
            last_error = exc
            if attempts >= max_attempts:
                break
            continue
        except Exception as exc:  # noqa: BLE001 — classified below
            kind = _classify_failure(exc)
            return ToolResult(
                ok=False,
                error=str(exc) or type(exc).__name__,
                failure_kind=kind,
                attempts=attempts,
                tool_name=tool_name,
                details={"exception_type": type(exc).__name__},
            )

    return ToolResult(
        ok=False,
        error=str(last_error) if last_error else "tool_failed",
        failure_kind=ToolFailureKind.TRANSIENT,
        attempts=attempts,
        tool_name=tool_name,
        details={"exception_type": type(last_error).__name__ if last_error else None},
    )


def _classify_failure(exc: BaseException) -> ToolFailureKind:
    name = type(exc).__name__
    message = str(exc).lower()
    if "config" in name.lower() or "must be configured" in message:
        return ToolFailureKind.CONFIG
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return ToolFailureKind.TRANSIENT
    if "not found" in message or "missing" in message:
        return ToolFailureKind.NOT_FOUND
    if name.endswith("LookupError") or name.endswith("ConfigurationError"):
        return ToolFailureKind.CONFIG if "Configuration" in name else ToolFailureKind.PERMANENT
    return ToolFailureKind.UNEXPECTED
