"""Whole-program functional check: REAL server, REAL websocket, full loop.

Boots ``uvicorn quorum.app:app`` as a subprocess (inheriting ``.env`` — so
with ``QUORUM_LLM_BACKEND=groq`` the LLM stage is genuinely exercised), then
drives a scripted participant through the wire protocol:

  1. join a room                       -> expects ``welcome`` + snapshot
  2. "a snowman"                       -> template stage, instant diff
  3. "a 3D cube"                       -> isometric template, instant diff
  4. "a rocket with two fins"          -> live LLM scene (skipped cleanly if
                                          the backend is mock/offline)
  5. "make it bigger"                  -> rules MODIFY on the focus
  6. a second client joins late        -> snapshot already holds the nodes

Exits non-zero on any broken expectation. Run:

    uv run python scripts/e2e_check.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx
import websockets

_PORT = 8123
_URI = f"ws://127.0.0.1:{_PORT}/ws"


async def _recv_until(ws: Any, msg_type: str, deadline_s: float = 15.0) -> dict[str, Any]:
    async with asyncio.timeout(deadline_s):
        while True:
            frame: dict[str, Any] = json.loads(await ws.recv())
            if frame.get("type") == msg_type:
                return frame


async def _drive() -> int:
    failures: list[str] = []

    def check(cond: bool, label: str) -> None:
        print(("PASS " if cond else "FAIL ") + label)
        if not cond:
            failures.append(label)

    async with websockets.connect(_URI) as ws:
        await ws.send(json.dumps({"type": "join", "room": "e2e", "speaker_id": "alice",
                                  "role": "participant"}))
        welcome = await _recv_until(ws, "welcome")
        check(welcome["snapshot"]["nodes"] == [], "join -> welcome with empty snapshot")
        speaker = welcome["speaker_id"]

        async def utter(text: str) -> dict[str, Any]:
            await ws.send(json.dumps({"type": "utterance", "speaker_id": speaker,
                                      "text": text}))
            return await _recv_until(ws, "diff")

        # 2) template bank: instant snowman
        diff = await utter("a snowman")
        node = diff["diff"]["upserted"][0]
        check(node["geometry"]["kind"] == "group" and len(node["geometry"]["parts"]) >= 2,
              "template: 'a snowman' -> multi-stroke group")
        check(node["svg"].startswith("<svg"), "template: snowman SVG rendered")

        # 3) isometric bank
        diff = await utter("a 3D cube")
        cube = diff["diff"]["upserted"][0]
        names = {p.get("name") for p in cube["geometry"]["parts"]}
        check({"face-top", "face-front", "face-right"} <= names,
              "isometric: 'a 3D cube' -> three shaded faces")

        # 4) live LLM scene (tolerate mock/offline backends). Ask the SERVER
        # which backend it runs — it loads .env itself; our shell env may lie.
        async with httpx.AsyncClient() as http:
            health = (await http.get(f"http://127.0.0.1:{_PORT}/healthz")).json()
        llm_live = health["backends"]["llm"] != "mock"
        diff = await utter("a rocket with two fins and a round window")
        rocket = diff["diff"]["upserted"][0] if diff["diff"]["upserted"] else None
        if llm_live:
            check(rocket is not None and len(rocket["geometry"].get("parts", [])) >= 3,
                  "LLM: rocket scene with >=3 parts")
        else:
            print("SKIP LLM scene (backend=mock)")

        # 5) rules modify on focus. A group's own width stays put while its
        # parts scale around the center, so compare the parts' footprint.
        def footprint(geom: dict[str, Any]) -> float:
            parts = geom.get("parts") or [geom]
            left = min(float(p["x"]) - float(p["width"]) / 2 for p in parts)
            right = max(float(p["x"]) + float(p["width"]) / 2 for p in parts)
            return right - left

        before = (rocket or cube)["geometry"]
        diff = await utter("make it bigger")
        bigger = diff["diff"]["upserted"][0]["geometry"]
        check(footprint(bigger) > footprint(before),
              "rules: 'make it bigger' grows the focused sketch")

        # 6) late joiner sees state
        async with websockets.connect(_URI) as ws2:
            await ws2.send(json.dumps({"type": "join", "room": "e2e",
                                       "speaker_id": "display", "role": "display"}))
            welcome2 = await _recv_until(ws2, "welcome")
            check(len(welcome2["snapshot"]["nodes"]) >= 2,
                  "late joiner: snapshot carries existing nodes")

    print(f"\n{'ALL PASS' if not failures else f'{len(failures)} FAILURE(S)'}")
    return 0 if not failures else 1


async def main() -> int:
    env = dict(os.environ)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn", "quorum.app:app",
        "--host", "127.0.0.1", "--port", str(_PORT), "--log-level", "warning",
        env=env,
    )
    try:
        async with asyncio.timeout(30):
            while True:  # wait for the socket to accept
                try:
                    async with websockets.connect(_URI, open_timeout=2):
                        pass
                    break
                except OSError:
                    await asyncio.sleep(0.3)
        return await _drive()
    finally:
        proc.terminate()
        await proc.wait()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
