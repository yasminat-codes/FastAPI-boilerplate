"""Tests for the job payload serialization helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import BaseModel

from src.app.core.worker.serialization import (
    JobPayloadSerializationError,
    safe_payload,
    serialize_for_envelope,
    validate_json_safe,
)


class TestValidateJsonSafe:
    """Tests for validate_json_safe()."""

    def test_string_is_safe(self) -> None:
        validate_json_safe("hello")

    def test_int_is_safe(self) -> None:
        validate_json_safe(42)

    def test_float_is_safe(self) -> None:
        validate_json_safe(3.14)

    def test_bool_is_safe(self) -> None:
        validate_json_safe(True)

    def test_none_is_safe(self) -> None:
        validate_json_safe(None)

    def test_list_of_primitives_is_safe(self) -> None:
        validate_json_safe([1, "two", 3.0, None, True])

    def test_nested_dict_is_safe(self) -> None:
        validate_json_safe({"a": {"b": [1, 2, 3]}})

    def test_datetime_raises(self) -> None:
        with pytest.raises(JobPayloadSerializationError, match="not JSON-serializable"):
            validate_json_safe(datetime.now(tz=UTC))

    def test_decimal_raises(self) -> None:
        with pytest.raises(JobPayloadSerializationError, match="not JSON-serializable"):
            validate_json_safe(Decimal("1.23"))

    def test_uuid_raises(self) -> None:
        with pytest.raises(JobPayloadSerializationError, match="not JSON-serializable"):
            validate_json_safe(UUID("12345678-1234-5678-1234-567812345678"))

    def test_bytes_raises(self) -> None:
        with pytest.raises(JobPayloadSerializationError, match="not JSON-serializable"):
            validate_json_safe(b"raw bytes")

    def test_set_raises(self) -> None:
        with pytest.raises(JobPayloadSerializationError, match="not JSON-serializable"):
            validate_json_safe({1, 2, 3})


class TestSafePayload:
    """Tests for safe_payload()."""

    def test_valid_dict_returned(self) -> None:
        payload = {"user_id": "u1", "action": "create"}
        assert safe_payload(payload) == payload

    def test_non_dict_raises(self) -> None:
        with pytest.raises(JobPayloadSerializationError, match="must be a dict"):
            safe_payload("not a dict")  # type: ignore[arg-type]

    def test_dict_with_non_serializable_raises(self) -> None:
        with pytest.raises(JobPayloadSerializationError, match="not JSON-serializable"):
            safe_payload({"timestamp": datetime.now(tz=UTC)})


class SamplePayloadModel(BaseModel):
    user_id: str
    amount: float
    created_at: datetime


class TestSerializeForEnvelope:
    """Tests for serialize_for_envelope()."""

    def test_pydantic_model_serialized(self) -> None:
        model = SamplePayloadModel(
            user_id="u1",
            amount=99.99,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        result = serialize_for_envelope(model)
        assert isinstance(result, dict)
        assert result["user_id"] == "u1"
        assert result["amount"] == 99.99
        # datetime should be serialized as ISO string via mode="json"
        assert isinstance(result["created_at"], str)

    def test_plain_dict_passed_through(self) -> None:
        payload = {"key": "value", "count": 42}
        result = serialize_for_envelope(payload)
        assert result == payload

    def test_dict_with_non_serializable_raises(self) -> None:
        with pytest.raises(JobPayloadSerializationError):
            serialize_for_envelope({"bad": datetime.now(tz=UTC)})

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(JobPayloadSerializationError, match="Expected a Pydantic model or dict"):
            serialize_for_envelope([1, 2, 3])  # type: ignore[arg-type]

    def test_returns_copy_of_dict(self) -> None:
        original = {"key": "value"}
        result = serialize_for_envelope(original)
        assert result is not original
        assert result == original
