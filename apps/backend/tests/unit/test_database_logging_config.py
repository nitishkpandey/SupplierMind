import logging

from app.core.config import Settings


def test_sql_echo_is_disabled_by_default_in_development():
    settings = Settings(APP_ENV="development")

    assert settings.SQL_ECHO is False


def test_http_dependency_request_lines_are_not_logged_at_info():
    import app.main  # noqa: F401

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
