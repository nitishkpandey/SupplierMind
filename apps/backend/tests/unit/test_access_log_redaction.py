import logging


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_sse_access_log_redacts_token_and_preserves_other_query_params():
    from app.middleware.request_id import redact_access_log_credentials

    record = _access_record(
        "/api/v1/queries/query-1/stream?token=secret-jwt&view=progress"
    )

    redact_access_log_credentials(record)
    rendered = record.getMessage()

    assert "secret-jwt" not in rendered
    assert "token=%5BREDACTED%5D" in rendered
    assert "view=progress" in rendered


def test_access_log_redacts_each_supported_credential_parameter():
    from app.middleware.request_id import redact_access_log_credentials

    record = _access_record(
        "/callback?access_token=access-secret&refresh_token=refresh-secret"
    )

    redact_access_log_credentials(record)
    rendered = record.getMessage()

    assert "access-secret" not in rendered
    assert "refresh-secret" not in rendered
    assert rendered.count("%5BREDACTED%5D") == 2


def test_access_log_without_credentials_is_unchanged():
    from app.middleware.request_id import redact_access_log_credentials

    record = _access_record("/api/v1/queries/query-1?view=history")
    before = record.getMessage()

    redact_access_log_credentials(record)

    assert record.getMessage() == before
