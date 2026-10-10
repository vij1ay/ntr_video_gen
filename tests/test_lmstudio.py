"""Tests for the LM Studio provider (mocked)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import LMStudioSettings
from app.providers.lmstudio import LMStudioProvider


def make_provider(model="test-model") -> LMStudioProvider:
    settings = LMStudioSettings(
        base_url="http://localhost:1234/v1",
        api_key="test",
        model=model,
        max_retries=2,
        timeout_seconds=10,
    )
    return LMStudioProvider(settings=settings)


class TestLMStudioProvider:
    @patch("app.providers.lmstudio.OpenAI")
    def test_health_check_success(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.models.list.return_value.data = [
            MagicMock(id="test-model")
        ]
        provider = make_provider("test-model")
        provider._client = mock_client
        assert provider.health_check() is True

    @patch("app.providers.lmstudio.OpenAI")
    def test_health_check_fail_on_connection_error(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.models.list.side_effect = Exception("Connection refused")
        provider = make_provider()
        provider._client = mock_client
        assert provider.health_check() is False

    @patch("app.providers.lmstudio.OpenAI")
    def test_generate_json_valid(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"key": "value"}'
        mock_client.chat.completions.create.return_value = mock_response

        provider = make_provider()
        provider._client = mock_client
        result = provider.generate_json("test prompt")
        assert result == {"key": "value"}

    @patch("app.providers.lmstudio.OpenAI")
    def test_generate_json_strips_fences(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '```json\n{"key": "value"}\n```'
        mock_client.chat.completions.create.return_value = mock_response

        provider = make_provider()
        provider._client = mock_client
        result = provider.generate_json("test prompt")
        assert result == {"key": "value"}

    def test_parse_json_direct(self):
        provider = make_provider()
        result = provider._parse_json('{"a": 1}')
        assert result == {"a": 1}

    def test_parse_json_with_prose(self):
        provider = make_provider()
        raw = 'Here is the JSON: {"a": 1} done.'
        result = provider._parse_json(raw)
        assert result == {"a": 1}

    def test_parse_json_invalid_raises(self):
        provider = make_provider()
        with pytest.raises(ValueError, match="not valid JSON"):
            provider._parse_json("This is not json at all.")
