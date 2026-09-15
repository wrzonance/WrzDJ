import logging
import logging.handlers

import pytest


def _reset_root_logger(original_handlers, original_level):
    root = logging.getLogger()
    for h in root.handlers:
        h.close()
    root.handlers = original_handlers
    root.level = original_level


@pytest.fixture()
def clean_root_logger():
    import app.core.logging_config as logging_config

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    original_configured = logging_config._state["configured"]
    root.handlers.clear()
    logging_config._state["configured"] = False
    yield
    logging_config._state["configured"] = original_configured
    _reset_root_logger(original_handlers, original_level)


def test_no_file_handler_without_log_dir(clean_root_logger, monkeypatch):
    monkeypatch.delenv("LOG_DIR", raising=False)
    from app.core.logging_config import configure_logging

    configure_logging()

    root = logging.getLogger()
    handler_types = [type(h) for h in root.handlers]
    assert logging.StreamHandler in handler_types
    assert not any(isinstance(h, logging.handlers.BaseRotatingHandler) for h in root.handlers)


def test_file_handler_created_with_log_dir(clean_root_logger, tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    from app.core.logging_config import configure_logging

    configure_logging()

    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename == str(tmp_path / "app.log")
    assert file_handlers[0].maxBytes == 10 * 1024 * 1024
    assert file_handlers[0].backupCount == 5


def test_log_message_written_to_file(clean_root_logger, tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    from app.core.logging_config import configure_logging

    configure_logging()
    logging.getLogger("app.logging_config_test").info("hello persistent logs")

    log_file = tmp_path / "app.log"
    assert log_file.exists()
    assert "hello persistent logs" in log_file.read_text()


def test_root_logger_level_set_to_info(clean_root_logger, monkeypatch):
    monkeypatch.delenv("LOG_DIR", raising=False)
    from app.core.logging_config import configure_logging

    configure_logging()

    assert logging.getLogger().level == logging.INFO


def test_file_handler_keeps_forged_newlines_on_one_line(clean_root_logger, tmp_path, monkeypatch):
    """Regression for CodeQL py/log-injection: request-derived text must not be able to
    forge extra lines in the plain-text rotating log file."""
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    from app.core.logging_config import configure_logging

    configure_logging()
    hostile = "guest-1\n2026-01-01 ERROR app.auth admin login OK\rinjected\x85nel\u2028ls\vvt"
    logging.getLogger("app.test").info("guest name: %s", hostile)
    for h in logging.getLogger().handlers:
        h.flush()

    lines = (tmp_path / "app.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "\\n2026-01-01 ERROR" in lines[0]
    assert "\\rinjected" in lines[0]
    assert "\\x85nel" in lines[0]
    assert "\\u2028ls" in lines[0]
    assert "\\x0bvt" in lines[0]
