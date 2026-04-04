from src.app.core import logger as logger_module


def test_redact_sensitive_log_fields_scrubs_nested_sensitive_values(monkeypatch) -> None:
    monkeypatch.setattr(logger_module.settings, "LOG_REDACTION_ENABLED", True)
    monkeypatch.setattr(logger_module.settings, "LOG_REDACTION_EXACT_FIELDS", ["authorization", "email"])
    monkeypatch.setattr(logger_module.settings, "LOG_REDACTION_SUBSTRING_FIELDS", ["token", "secret"])
    monkeypatch.setattr(logger_module.settings, "LOG_REDACTION_REPLACEMENT", "[FILTERED]")

    event_dict = {
        "event": "request completed",
        "headers": {
            "Authorization": "Bearer secret-token",
            "X-Request-ID": "req-123",
        },
        "user": {"email": "person@example.com", "name": "Taylor"},
        "metadata": {"refresh_token": "refresh-token", "attempt": 2},
    }

    redacted = logger_module.redact_sensitive_log_fields(None, None, event_dict)

    assert redacted["event"] == "request completed"
    assert redacted["headers"]["Authorization"] == "[FILTERED]"
    assert redacted["headers"]["X-Request-ID"] == "req-123"
    assert redacted["user"]["email"] == "[FILTERED]"
    assert redacted["user"]["name"] == "Taylor"
    assert redacted["metadata"]["refresh_token"] == "[FILTERED]"
    assert redacted["metadata"]["attempt"] == 2


def test_redact_sensitive_log_fields_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setattr(logger_module.settings, "LOG_REDACTION_ENABLED", False)

    event_dict = {"headers": {"Authorization": "Bearer secret-token"}}

    assert logger_module.redact_sensitive_log_fields(None, None, event_dict) == event_dict
