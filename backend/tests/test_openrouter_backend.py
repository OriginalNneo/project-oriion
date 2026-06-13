"""OpenRouter backend wiring tests (no network).

Verifies that LLMClassifier posts to the correct URL, sends the correct
headers, and includes ``response_format`` in the body — for both the
OPENROUTER and the GROQ branches — by monkeypatching ``httpx.AsyncClient.post``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from quorum.config.settings import Backend
from quorum.pipeline.llm import LLMClassifier

_FAKE_RESPONSE_JSON = {
    "choices": [{"message": {"content": '{"op_type":"noop","confidence":0.0}'}}]
}

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _make_fake_response() -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = _FAKE_RESPONSE_JSON
    resp.raise_for_status = MagicMock(return_value=None)
    resp.status_code = 200
    resp.headers = {}
    return resp


async def test_openrouter_url_and_headers() -> None:
    """OPENROUTER branch posts to the OpenRouter endpoint with the right headers."""
    clf = LLMClassifier(backend=Backend.OPENROUTER, model="x", api_key="k")

    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = dict(kwargs.get("headers", {}))
        captured["json"] = kwargs.get("json", {})
        return _make_fake_response()

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        messages = [{"role": "user", "content": "hello"}]
        await clf._send(messages)

    assert captured["url"] == _OPENROUTER_URL, f"Wrong URL: {captured['url']}"
    assert "Authorization" in captured["headers"], "Missing Authorization header"
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert captured["headers"].get("HTTP-Referer") == "https://github.com/quorum"
    assert captured["headers"].get("X-Title") == "Quorum"
    assert captured["json"].get("response_format") == {"type": "json_object"}


async def test_groq_url_and_no_openrouter_headers() -> None:
    """GROQ branch posts to the Groq endpoint WITHOUT the OpenRouter-specific headers."""
    clf = LLMClassifier(backend=Backend.GROQ, model="llama-3.1-8b-instant", api_key="groq-k")

    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = dict(kwargs.get("headers", {}))
        captured["json"] = kwargs.get("json", {})
        return _make_fake_response()

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        messages = [{"role": "user", "content": "hello"}]
        await clf._send(messages)

    assert captured["url"] == _GROQ_URL, f"Wrong URL: {captured['url']}"
    assert "Authorization" in captured["headers"]
    assert captured["headers"]["Authorization"] == "Bearer groq-k"
    assert "HTTP-Referer" not in captured["headers"], "HTTP-Referer must NOT appear on Groq path"
    assert "X-Title" not in captured["headers"], "X-Title must NOT appear on Groq path"
    assert captured["json"].get("response_format") == {"type": "json_object"}
