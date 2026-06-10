"""Phase 0 integration test — the loop the phase must prove.

client (join) -> WS -> [demo_op] -> engine -> render -> broadcast (diff with SVG)

Also exercises the Phase-1 tail (a typed utterance -> rules classifier -> engine)
and the two-client broadcast (a participant's op reaches a display), since the
contract for those already exists.

Run synchronously via Starlette's TestClient websocket support.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from quorum.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _join(ws: WebSocketTestSession, room: str, speaker: str, role: str = "participant") -> None:
    ws.send_json({"type": "join", "room": room, "role": role, "speaker_id": speaker})


def _drain_until(ws: WebSocketTestSession, msg_type: str, limit: int = 10) -> dict[str, Any]:
    """Receive frames until one of `msg_type` arrives (or limit hit)."""
    for _ in range(limit):
        msg: dict[str, Any] = ws.receive_json()
        if msg["type"] == msg_type:
            return msg
    raise AssertionError(f"never saw a '{msg_type}' message")


@pytest.mark.integration
def test_demo_op_renders_and_broadcasts(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        _join(ws, "room0", "alice")
        # welcome + snapshot arrive first
        welcome = _drain_until(ws, "welcome")
        assert welcome["room"] == "room0"

        ws.send_json(
            {"type": "demo_op", "speaker_id": "alice", "shape": "rectangle", "fillet": True}
        )
        diff = _drain_until(ws, "diff")
        nodes = diff["diff"]["upserted"]
        assert len(nodes) == 1
        node = nodes[0]
        # the hardcoded SVG actually rendered and came back over the wire
        assert node["svg"].startswith("<svg")
        assert node["geometry"]["kind"] == "rectangle"
        assert node["geometry"]["corner_radius"] > 0  # fillet applied


@pytest.mark.integration
def test_utterance_path_classifies_and_renders(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        _join(ws, "room1", "bob")
        _drain_until(ws, "welcome")
        ws.send_json({"type": "utterance", "speaker_id": "bob", "text": "draw a circle"})
        diff = _drain_until(ws, "diff")
        assert diff["diff"]["upserted"][0]["geometry"]["kind"] == "circle"


@pytest.mark.integration
def test_op_from_participant_reaches_display(client: TestClient) -> None:
    with client.websocket_connect("/ws") as part, client.websocket_connect("/ws") as disp:
        _join(part, "room2", "alice", "participant")
        _drain_until(part, "welcome")
        _join(disp, "room2", "display", "display")
        _drain_until(disp, "welcome")

        part.send_json({"type": "demo_op", "speaker_id": "alice", "shape": "triangle"})
        # the display (a different client) receives the broadcast diff
        diff = _drain_until(disp, "diff")
        assert diff["diff"]["upserted"][0]["geometry"]["kind"] == "triangle"


@pytest.mark.integration
def test_late_joiner_gets_snapshot(client: TestClient) -> None:
    with client.websocket_connect("/ws") as a:
        _join(a, "room3", "alice")
        _drain_until(a, "welcome")
        a.send_json({"type": "demo_op", "speaker_id": "alice", "shape": "circle"})
        _drain_until(a, "diff")

        # a second client joining the same room sees the existing node immediately
        with client.websocket_connect("/ws") as b:
            _join(b, "room3", "display", "display")
            welcome = _drain_until(b, "welcome")
            assert len(welcome["snapshot"]["nodes"]) >= 1
