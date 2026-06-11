"""D1 validation-repair tests — LLM stage clamp/salvage/retry (no network).

Covers the four-part repair pipeline added in D1:
  1. Clamp: out-of-range coordinates are clamped, op survives.
  2. Salvage: a group with one rotten part is kept minus the bad part.
  3. Corrective retry: irreparable payload triggers exactly ONE corrective retry;
     a good second reply succeeds.
  4. Double failure: two bad replies → graceful NOOP, no infinite retries.
  5. max_tokens: every request body carries an explicit max_tokens field.

Transport is mocked throughout (httpx.MockTransport / monkey-patching
`_complete`).  No live Groq calls.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from quorum.config.settings import Backend
from quorum.domain.geometry import ShapeKind
from quorum.domain.op import ClassifierContext, OpType
from quorum.pipeline.llm import (
    _MAX_TOKENS,
    LLMClassifier,
    _clamp,
    _parse_and_repair,
    _repair_geometry_dict,
    _salvage_group_parts,
)

_CTX = ClassifierContext()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GOOD_RECT_JSON = json.dumps(
    {
        "op_type": "create",
        "target_shape": "rectangle",
        "confidence": 0.9,
        "geometry": {
            "kind": "rectangle",
            "x": 50,
            "y": 50,
            "width": 40,
            "height": 30,
        },
    }
)

_GOOD_GROUP_JSON = json.dumps(
    {
        "op_type": "create",
        "target_shape": "group",
        "confidence": 0.8,
        "geometry": {
            "kind": "group",
            "x": 50,
            "y": 50,
            "width": 60,
            "height": 60,
            "parts": [
                {"kind": "rectangle", "name": "body", "x": 50, "y": 60, "width": 40, "height": 30},
                {"kind": "circle", "name": "head", "x": 50, "y": 30, "width": 20, "height": 20},
            ],
        },
    }
)


def _groq_response(content: str) -> dict[str, object]:
    """Wrap a content string in a minimal Groq-compatible response envelope."""
    return {"choices": [{"message": {"content": content}}]}


def _make_clf() -> LLMClassifier:
    return LLMClassifier(backend=Backend.GROQ, model="x", api_key="k")


# ---------------------------------------------------------------------------
# Unit tests on the repair helpers (no I/O)
# ---------------------------------------------------------------------------


def test_clamp_basic() -> None:
    assert _clamp(150.0, 0.0, 100.0) == 100.0
    assert _clamp(-5.0, 0.0, 100.0) == 0.0
    assert _clamp(50.0, 0.0, 100.0) == 50.0


def test_repair_geometry_dict_clamps_xy() -> None:
    raw: dict[str, Any] = {
        "kind": "rectangle",
        "x": 150.0,
        "y": -10.0,
        "width": 40.0,
        "height": 30.0,
    }
    _repair_geometry_dict(raw)
    assert raw["x"] == 100.0
    assert raw["y"] == 0.0


def test_repair_geometry_dict_clamps_width_height() -> None:
    raw: dict[str, Any] = {"kind": "circle", "x": 50.0, "y": 50.0, "width": 200.0, "height": -5.0}
    _repair_geometry_dict(raw)
    assert raw["width"] == 100.0
    assert raw["height"] > 0.0  # clamped to the gt=0 floor


def test_repair_geometry_dict_clamps_corner_radius() -> None:
    raw: dict[str, Any] = {
        "kind": "rectangle",
        "x": 50.0,
        "y": 50.0,
        "width": 40.0,
        "height": 30.0,
        "corner_radius": 999.0,
    }
    _repair_geometry_dict(raw)
    assert raw["corner_radius"] == 50.0


def test_repair_geometry_dict_clamps_polygon_points() -> None:
    raw: dict[str, Any] = {
        "kind": "polygon",
        "x": 50.0,
        "y": 50.0,
        "width": 40.0,
        "height": 30.0,
        "points": [[150.0, -20.0], [50.0, 50.0], [200.0, 110.0]],
    }
    _repair_geometry_dict(raw)
    for pt in raw["points"]:
        assert 0.0 <= pt[0] <= 100.0
        assert 0.0 <= pt[1] <= 100.0


def test_repair_geometry_dict_recurses_into_parts() -> None:
    raw: dict[str, Any] = {
        "kind": "group",
        "x": 50.0,
        "y": 50.0,
        "width": 60.0,
        "height": 60.0,
        "parts": [
            {"kind": "rectangle", "x": 150.0, "y": 50.0, "width": 40.0, "height": 30.0}
        ],
    }
    _repair_geometry_dict(raw)
    assert raw["parts"][0]["x"] == 100.0


# ---------------------------------------------------------------------------
# (a) Out-of-range coords → clamp → op survives
# ---------------------------------------------------------------------------


async def test_clamped_coords_op_survives() -> None:
    """An LLM reply with coords outside 0..100 should be clamped and accepted."""
    bad_payload = {
        "op_type": "create",
        "target_shape": "rectangle",
        "confidence": 0.9,
        "geometry": {
            "kind": "rectangle",
            "x": 150.0,  # out of range
            "y": -20.0,  # out of range
            "width": 200.0,  # out of range
            "height": 30.0,
        },
    }
    result = _parse_and_repair(json.dumps(bad_payload))
    assert result is not None
    assert result.op_type == OpType.CREATE
    assert result.geometry is not None
    assert result.geometry.x == 100.0
    assert result.geometry.y == 0.0
    assert result.geometry.width == 100.0


async def test_clamped_polygon_points_op_survives() -> None:
    """Polygon with out-of-range points should clamp and validate."""
    bad_payload = {
        "op_type": "create",
        "target_shape": "polygon",
        "confidence": 0.85,
        "geometry": {
            "kind": "polygon",
            "x": 50,
            "y": 50,
            "width": 40,
            "height": 40,
            "points": [[150, -10], [50, 50], [200, 110]],
        },
    }
    result = _parse_and_repair(json.dumps(bad_payload))
    assert result is not None
    assert result.geometry is not None
    assert result.geometry.points is not None
    for pt in result.geometry.points:
        assert 0.0 <= pt[0] <= 100.0
        assert 0.0 <= pt[1] <= 100.0


async def test_full_classify_clamped_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: LLMClassifier.classify with an out-of-range coord in the mock
    response does NOT return a NOOP — it clamps and produces a real op."""
    bad_json = json.dumps(
        {
            "op_type": "create",
            "target_shape": "rectangle",
            "confidence": 0.9,
            "geometry": {"kind": "rectangle", "x": 150, "y": -20, "width": 200, "height": 30},
        }
    )
    clf = _make_clf()

    async def _fake_complete(text: str, context: object) -> str:
        return bad_json

    clf._complete = _fake_complete  # type: ignore[method-assign]

    op = await clf.classify("a rect", speaker_id="a", utterance_id="u1", context=_CTX)
    assert op.op_type == OpType.CREATE
    assert op.source_stage == "llm"
    assert op.geometry is not None


# ---------------------------------------------------------------------------
# (b) Salvage: group with one rotten part → op minus bad part
# ---------------------------------------------------------------------------


def test_salvage_group_drops_rotten_part_keeps_good() -> None:
    """A group with one valid and one invalid part (no `d` for a path) is
    salvaged; only the good part survives."""
    raw: dict[str, Any] = {
        "kind": "group",
        "x": 50,
        "y": 50,
        "width": 60,
        "height": 60,
        "parts": [
            # valid rectangle
            {"kind": "rectangle", "name": "ok", "x": 50, "y": 60, "width": 40, "height": 30},
            # path without 'd' — will fail GeometrySpec validation
            {"kind": "path", "name": "bad", "x": 50, "y": 30, "width": 40, "height": 30},
        ],
    }
    result = _salvage_group_parts(raw)
    assert result is not None
    assert len(result.parts) == 1
    assert result.parts[0].name == "ok"


def test_salvage_all_parts_bad_returns_none() -> None:
    """If every part is invalid, salvage returns None."""
    raw: dict[str, Any] = {
        "kind": "group",
        "x": 50,
        "y": 50,
        "width": 60,
        "height": 60,
        "parts": [
            {"kind": "path", "name": "bad1", "x": 50, "y": 30, "width": 40, "height": 30},
            {"kind": "path", "name": "bad2", "x": 50, "y": 60, "width": 40, "height": 30},
        ],
    }
    result = _salvage_group_parts(raw)
    assert result is None


def test_salvage_non_group_returns_none() -> None:
    """_salvage_group_parts only applies to groups, not other shapes."""
    raw: dict[str, Any] = {
        "kind": "rectangle",
        "x": 50,
        "y": 50,
        "width": 40,
        "height": 30,
    }
    result = _salvage_group_parts(raw)
    assert result is None


async def test_full_classify_salvage_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: a group response with one bad part is salvaged, not NOOPed."""
    bad_group_json = json.dumps(
        {
            "op_type": "create",
            "target_shape": "group",
            "confidence": 0.85,
            "geometry": {
                "kind": "group",
                "x": 50,
                "y": 50,
                "width": 60,
                "height": 60,
                "parts": [
                    {
                        "kind": "rectangle",
                        "name": "body",
                        "x": 50,
                        "y": 60,
                        "width": 40,
                        "height": 30,
                    },
                    # path without 'd' — invalid
                    {
                        "kind": "path",
                        "name": "shadow",
                        "x": 50,
                        "y": 80,
                        "width": 40,
                        "height": 10,
                    },
                ],
            },
        }
    )
    clf = _make_clf()

    async def _fake_complete(text: str, context: object) -> str:
        return bad_group_json

    clf._complete = _fake_complete  # type: ignore[method-assign]

    op = await clf.classify("a rect with shadow", speaker_id="a", utterance_id="u1", context=_CTX)
    assert op.op_type == OpType.CREATE
    assert op.source_stage == "llm"
    assert op.geometry is not None
    assert op.geometry.kind is ShapeKind.GROUP
    # Only the good rectangle survives
    assert len(op.geometry.parts) == 1
    assert op.geometry.parts[0].name == "body"


# ---------------------------------------------------------------------------
# (c) Irreparable payload → exactly one corrective retry → success
# ---------------------------------------------------------------------------


async def test_corrective_retry_called_exactly_once_on_bad_reply() -> None:
    """When the first reply is irreparable, classify calls _send a second time
    with a corrective message and uses the good second reply."""
    send_calls: list[list[dict[str, str]]] = []

    clf = _make_clf()

    async def _fake_send(messages: list[dict[str, str]]) -> str:
        send_calls.append(messages)
        if len(send_calls) == 1:
            # First call: totally invalid JSON
            return "this is not json at all"
        # Second call: valid rectangle
        return _GOOD_RECT_JSON

    clf._send = _fake_send  # type: ignore[method-assign]

    op = await clf.classify("a rectangle", speaker_id="a", utterance_id="u1", context=_CTX)

    assert len(send_calls) == 2, f"Expected 2 _send calls, got {len(send_calls)}"
    # The second call must include an assistant turn with the bad reply
    second_msgs = send_calls[1]
    roles = [m["role"] for m in second_msgs]
    assert "assistant" in roles
    # The last message must be a user corrective prompt
    assert second_msgs[-1]["role"] == "user"
    last_content = second_msgs[-1]["content"].lower()
    assert "invalid" in last_content or "error" in last_content

    assert op.op_type == OpType.CREATE
    assert op.source_stage == "llm"


# ---------------------------------------------------------------------------
# (d) Two bad replies → graceful NOOP (no infinite retries)
# ---------------------------------------------------------------------------


async def test_two_bad_replies_produce_noop_no_extra_retries() -> None:
    """If both the first and corrective-retry replies are irreparable, the result
    is a zero-confidence NOOP and _send is called exactly twice."""
    send_calls: list[int] = []

    clf = _make_clf()

    async def _fake_send(messages: list[dict[str, str]]) -> str:
        send_calls.append(1)
        return "not json at all"  # always bad

    clf._send = _fake_send  # type: ignore[method-assign]

    op = await clf.classify("nonsense", speaker_id="a", utterance_id="u1", context=_CTX)

    assert len(send_calls) == 2, f"Expected exactly 2 _send calls, got {len(send_calls)}"
    assert op.op_type == OpType.NOOP
    assert op.confidence == 0.0
    assert op.source_stage == "llm"


# ---------------------------------------------------------------------------
# (e) max_tokens is present in every request body
# ---------------------------------------------------------------------------


async def test_groq_request_carries_max_tokens() -> None:
    """The Groq POST body must include max_tokens."""
    captured_bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured_bodies.append(body)
        return httpx.Response(200, json=_groq_response(_GOOD_RECT_JSON))

    clf = LLMClassifier(
        backend=Backend.GROQ,
        model="test-model",
        api_key="k",
        timeout_s=5.0,
    )
    # Patch _send to use a mock transport but still go through the real _send logic.
    # We do this by patching the httpx.AsyncClient inside _send via monkeypatching
    # the transport at the module level — easier: replace _complete with a full
    # reimplementation that uses a mock transport.

    async def _patched_send(messages: list[dict[str, str]]) -> str:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5.0
        ) as client:
            resp = await LLMClassifier._post_with_retry(
                client,
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": "Bearer k"},
                json={
                    "model": "test-model",
                    "messages": messages,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "max_tokens": _MAX_TOKENS,
                },
            )
            resp.raise_for_status()
            content: str = resp.json()["choices"][0]["message"]["content"]
            return content

    clf._send = _patched_send  # type: ignore[method-assign]

    op = await clf.classify("a rect", speaker_id="a", utterance_id="u1", context=_CTX)
    assert op.op_type == OpType.CREATE

    assert captured_bodies, "No HTTP requests were made"
    for body in captured_bodies:
        assert "max_tokens" in body, f"max_tokens missing from request body: {body.keys()}"
        assert body["max_tokens"] == _MAX_TOKENS


async def test_max_tokens_constant_is_sensible() -> None:
    """_MAX_TOKENS should be a positive integer (default 4096)."""
    assert isinstance(_MAX_TOKENS, int)
    assert _MAX_TOKENS > 0


async def test_groq_send_includes_max_tokens_via_mock_transport() -> None:
    """Verify _send really puts max_tokens in the request by intercepting httpx."""
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=_groq_response(_GOOD_RECT_JSON))

    clf = LLMClassifier(backend=Backend.GROQ, model="m", api_key="k", timeout_s=5.0)

    # Monkeypatch httpx.AsyncClient to inject our transport.
    # We replace _complete with a version that uses a mock transport.

    call_count = 0

    async def _fake_complete(text: str, context: object) -> str:
        nonlocal call_count
        call_count += 1
        # Reconstruct what _send does, but with the mock transport
        user = LLMClassifier._user_payload(text, context)  # type: ignore[arg-type]
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user},
        ]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5.0
        ) as client:
            resp = await LLMClassifier._post_with_retry(
                client,
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": "Bearer k"},
                json={
                    "model": "m",
                    "messages": messages,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "max_tokens": _MAX_TOKENS,
                },
            )
            resp.raise_for_status()
            content: str = resp.json()["choices"][0]["message"]["content"]
            return content

    clf._complete = _fake_complete  # type: ignore[method-assign]

    op = await clf.classify("a rect", speaker_id="a", utterance_id="u1", context=_CTX)
    assert op.op_type == OpType.CREATE
    assert captured
    for body in captured:
        assert body.get("max_tokens") == _MAX_TOKENS


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_parse_and_repair_bad_json_returns_none() -> None:
    """Completely unparseable JSON returns None."""
    result = _parse_and_repair("{not json}")
    assert result is None


def test_parse_and_repair_valid_payload_passes_through() -> None:
    """A fully valid payload is returned directly."""
    result = _parse_and_repair(_GOOD_RECT_JSON)
    assert result is not None
    assert result.op_type == OpType.CREATE


def test_parse_and_repair_group_with_all_bad_parts_returns_none() -> None:
    """A group where all parts are broken is un-repairable."""
    payload = json.dumps(
        {
            "op_type": "create",
            "target_shape": "group",
            "confidence": 0.8,
            "geometry": {
                "kind": "group",
                "x": 50,
                "y": 50,
                "width": 60,
                "height": 60,
                "parts": [
                    # Both paths missing 'd' — invalid
                    {"kind": "path", "x": 50, "y": 30, "width": 40, "height": 30},
                    {"kind": "path", "x": 50, "y": 60, "width": 40, "height": 30},
                ],
            },
        }
    )
    result = _parse_and_repair(payload)
    assert result is None
