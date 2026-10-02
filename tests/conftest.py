import logging

import pytest


@pytest.fixture
def restore_root_logger():
    """Undo handlers/levels installed by setup_logging during a test."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)
