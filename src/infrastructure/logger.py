"""Logging setup: a concise console stream plus a detailed rotating file.

Every formatted line (including tracebacks) passes through secret redaction,
so API keys cannot leak into the console or ``logs/app.log`` even if an
exception message happens to contain one.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILENAME = "app.log"
REDACTED = "[REDACTED]"

# Google API keys, and "key=..." query parameters in URLs.
_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"(?<=[?&]key=)[^&\s\"']+"),
)

# Third-party loggers that are chatty at INFO (e.g. one line per HTTP request).
_QUIET_LOGGERS = ("httpx", "httpcore", "urllib3", "google_genai", "google.auth", "PIL")

# Marks handlers installed by setup_logging so repeated calls replace them.
_HANDLER_TAG = "_storybook_handler"


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str, secrets: Iterable[str] = (), datefmt: str | None = None):
        super().__init__(fmt, datefmt=datefmt)
        # Longest first so a secret containing another is fully replaced.
        self._secrets = sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True)

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self._secrets)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def setup_logging(
    log_directory: Path,
    level: str = "INFO",
    secrets: Iterable[str] = (),
) -> Path:
    """Configure the root logger for console + file output. Returns the log file path.

    Safe to call more than once; previously installed handlers are replaced.
    """
    secrets = tuple(secrets)
    log_directory.mkdir(parents=True, exist_ok=True)
    log_file = log_directory / LOG_FILENAME

    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _HANDLER_TAG, False)]:
        root.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            secrets=secrets,
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level.upper())
    console_handler.setFormatter(RedactingFormatter("%(message)s", secrets=secrets))

    for handler in (file_handler, console_handler):
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)

    # The file keeps full detail (incl. failure tracebacks); the console shows `level`.
    root.setLevel(logging.DEBUG)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return log_file


@contextmanager
def log_duration(logger: logging.Logger, action: str, level: int = logging.INFO) -> Iterator[None]:
    """Log how long ``action`` took, or how long it ran before failing."""
    start = time.monotonic()
    try:
        yield
    except BaseException:
        logger.log(level, "%s failed after %.1fs", action, time.monotonic() - start)
        raise
    logger.log(level, "%s finished in %.1fs", action, time.monotonic() - start)
