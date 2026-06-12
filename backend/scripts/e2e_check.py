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
  6. "a rhombus"                       -> named-geometry tier (plan.md §12 R4)
  7. "draw a cuboid" then
     "i want the cube to be red"       -> label-resolved fast-path MODIFY:
                                          NEW child node, parent intact,
                                          fills re-tinted red, coords
                                          byte-identical (§12 R1-R3)
  8. a second client joins late        -> snapshot already holds the nodes

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

        # 5) rules modify on focus (iteration-as-branch, plan.md §12 R1).
        # The engine creates a NEW child node; the original node stays in the
        # snapshot unchanged. Compare the child's parts footprint to the
        # original focus's footprint to confirm growth.
        def footprint(geom: dict[str, Any]) -> float:
            parts = geom.get("parts") or [geom]
            left = min(float(p["x"]) - float(p["width"]) / 2 for p in parts)
            right = max(float(p["x"]) + float(p["width"]) / 2 for p in parts)
            return right - left

        focus_before_id = diff["diff"]["focus_node_id"]  # id of node before "bigger"
        before_geom = (rocket or cube)["geometry"]
        diff = await utter("make it bigger")
        # The diff must contain a NEW node (different id from previous focus).
        new_focus_id = diff["diff"]["focus_node_id"]
        check(new_focus_id != focus_before_id,
              "rules: 'make it bigger' creates a NEW focused child node")
        # Find the new focused node in upserted.
        upserted_by_id = {u["id"]: u for u in diff["diff"]["upserted"]}
        child_geom = upserted_by_id.get(new_focus_id, {}).get("geometry", {})
        check(footprint(child_geom) > footprint(before_geom),
              "rules: new child's footprint grew relative to parent")

        # 6) named-geometry tier (plan.md §12 R4): exact polygon, no LLM.
        diff = await utter("a rhombus")
        rhombus = diff["diff"]["upserted"][0]
        check(
            rhombus["geometry"]["kind"] == "polygon"
            and len(rhombus["geometry"].get("points") or []) >= 4
            and rhombus["label"] == "rhombus",
            "named shape: 'a rhombus' -> exact labelled polygon",
        )

        # 7) the §12 acceptance chain: cuboid -> label-resolved recolor.
        diff = await utter("draw a cuboid")
        cuboid = diff["diff"]["upserted"][0]
        check(
            cuboid["label"] == "cuboid" and len(cuboid["geometry"]["parts"]) >= 3,
            "template: 'draw a cuboid' -> labelled isometric cuboid",
        )

        def reddish(hex_color: str | None) -> bool:
            if not hex_color or not hex_color.startswith("#") or len(hex_color) != 7:
                return False
            r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
            return r > g and r > b

        diff = await utter("i want the cube to be red")
        red_id = diff["diff"]["focus_node_id"]
        upserted_by_id = {u["id"]: u for u in diff["diff"]["upserted"]}
        red = upserted_by_id.get(red_id)
        # "the cube" may resolve to the "cuboid" (newest, stem match) or the
        # step-3 "cube" node (exact label match) — both are correct §12-R3
        # resolutions; what matters is a NEW child of a cube-ish parent.
        cube_parents = {cuboid["id"]: cuboid, cube["id"]: cube}
        parent_node = cube_parents.get(((red or {}).get("parent_ids") or [None])[0])
        check(
            red is not None and red["id"] not in cube_parents and parent_node is not None,
            "'the cube' resolves by label; recolor lands as a NEW child node",
        )
        if red is not None and parent_node is not None:
            child_parts = red["geometry"]["parts"]
            parent_parts = parent_node["geometry"]["parts"]
            filled = [p for p in child_parts if p.get("fill")]
            check(
                len(filled) >= 3 and all(reddish(p["fill"]) for p in filled)
                and len({p["fill"] for p in filled}) >= 3,
                "recolor: three distinct red-tinted face fills (shading kept)",
            )
            check(
                [p.get("points") for p in child_parts] == [p.get("points") for p in parent_parts],
                "recolor: child coordinates byte-identical to the parent cuboid",
            )

        # 8) late joiner sees state
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
