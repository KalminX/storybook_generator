import logging

import pytest

from src.infrastructure.logger import LOG_FILENAME, log_duration, redact, setup_logging

FAKE_GOOGLE_KEY = "AIza" + "x" * 35


def test_redacts_known_secrets_and_key_patterns():
    text = f"key {FAKE_GOOGLE_KEY} url https://x/y?key=abc123&z=1 custom my-secret-token"
    result = redact(text, ["my-secret-token"])
    assert FAKE_GOOGLE_KEY not in result
    assert "abc123" not in result
    assert "my-secret-token" not in result
    assert "z=1" in result


def test_logs_to_file_with_redaction(tmp_path, restore_root_logger):
    log_file = setup_logging(tmp_path, "INFO", secrets=["super-secret-value"])
    assert log_file == tmp_path / LOG_FILENAME

    log = logging.getLogger("test.logger")
    log.info("Using key %s", "super-secret-value")
    try:
        raise RuntimeError(f"bad key {FAKE_GOOGLE_KEY}")
    except RuntimeError:
        log.exception("request failed")

    content = log_file.read_text()
    assert "Using key [REDACTED]" in content
    assert "super-secret-value" not in content
    assert FAKE_GOOGLE_KEY not in content
    assert "RuntimeError" in content  # traceback still present


def test_setup_is_idempotent(tmp_path, restore_root_logger):
    setup_logging(tmp_path)
    setup_logging(tmp_path)
    tagged = [h for h in logging.getLogger().handlers if getattr(h, "_storybook_handler", False)]
    assert len(tagged) == 2  # one file + one console handler


def test_log_duration(caplog):
    log = logging.getLogger("test.duration")
    with caplog.at_level(logging.INFO):
        with log_duration(log, "Rendering PDF"):
            pass
        with pytest.raises(ValueError), log_duration(log, "Uploading"):
            raise ValueError
    assert "Rendering PDF finished in" in caplog.text
    assert "Uploading failed after" in caplog.text
