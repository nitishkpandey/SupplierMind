from app.core.config import Settings


def test_sql_echo_is_disabled_by_default_in_development():
    settings = Settings(APP_ENV="development")

    assert settings.SQL_ECHO is False
