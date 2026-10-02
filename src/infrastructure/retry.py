"""Generic retry with exponential backoff.

This module knows nothing about any API provider. Callers decide what is
retryable: by default ``TransientError`` subclasses and the built-in network
errors (``TimeoutError``, ``ConnectionError``). Everything else is treated as
permanent and re-raised immediately.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Upper bound on honouring a server-supplied "retry after" hint.
_MAX_RETRY_AFTER_SECONDS = 300.0


class TransientError(Exception):
    """A failure that may succeed if tried again (rate limit, 5xx, timeout...).

    ``retry_after`` optionally carries a server-suggested wait in seconds.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    initial_delay: float = 2.0
    max_delay: float = 30.0
    multiplier: float = 2.0
    # Randomise each delay by +/- this fraction so parallel clients don't sync up.
    jitter: float = 0.1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay < 0 or self.max_delay < self.initial_delay:
            raise ValueError("require 0 <= initial_delay <= max_delay")
        if self.multiplier < 1:
            raise ValueError("multiplier must be >= 1")
        if not 0 <= self.jitter < 1:
            raise ValueError("jitter must be in [0, 1)")

    def backoff(self, retry_number: int, rand: float = 0.5) -> float:
        """Delay before retry ``retry_number`` (1-based). ``rand`` is in [0, 1)."""
        base = min(self.max_delay, self.initial_delay * self.multiplier ** (retry_number - 1))
        spread = base * self.jitter * (2 * rand - 1)
        return max(0.0, min(self.max_delay, base + spread))


def default_is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (TransientError, TimeoutError, ConnectionError))


def retry_call(
    func: Callable[[], T],
    *,
    policy: RetryPolicy,
    description: str,
    is_retryable: Callable[[BaseException], bool] = default_is_retryable,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> T:
    """Call ``func`` until it succeeds, a permanent error occurs, or attempts run out.

    The last exception is re-raised unchanged so callers can still inspect it.
    ``description`` names the operation in log messages (e.g. "page 3 image").
    """
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            if not is_retryable(exc):
                raise
            if attempt == policy.max_attempts:
                logger.error(
                    "%s failed after %d attempt(s): %s", description, attempt, _summarize(exc)
                )
                raise
            delay = policy.backoff(attempt, rand())
            retry_after = getattr(exc, "retry_after", None)
            if retry_after:
                delay = max(delay, min(float(retry_after), _MAX_RETRY_AFTER_SECONDS))
            logger.warning(
                "%s failed (attempt %d/%d): %s - retrying in %.1fs",
                description,
                attempt,
                policy.max_attempts,
                _summarize(exc),
                delay,
            )
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def _summarize(exc: BaseException) -> str:
    text = str(exc).strip() or "(no message)"
    if len(text) > 300:
        text = text[:297] + "..."
    return f"{type(exc).__name__}: {text}"
