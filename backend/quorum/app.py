"""FastAPI application — the async gateway entrypoint.

Wires: settings -> logging -> RoomManager -> WebSocket endpoint. Serves the
realtime loop over a single WebSocket (RULES.md §4: no ad-hoc fetch side-channels
for realtime data) and exposes a couple of read-only HTTP endpoints for health
and the live latency ledger (observability is a product requirement).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from quorum import __version__
from quorum.config import get_settings
from quorum.domain.messages import JoinMessage, Role
from quorum.gateway.connection import WebSocketConnection
from quorum.gateway.handler import MessageHandler
from quorum.gateway.rooms import RoomManager
from quorum.observability import configure_logging, get_ledger, get_logger

settings = get_settings()
configure_logging(level=settings.log_level, json_logs=settings.log_json)
_log = get_logger("app")

# One room manager for the process. Handlers are per-room and cached here so all
# connections in a room share utterance sequencing + the classifier.
_rooms = RoomManager()
_handlers: dict[str, MessageHandler] = {}
# Keeps a strong reference to the background warm-up task so it isn't GC'd
# mid-flight (asyncio only holds a weak ref to fire-and-forget tasks).
_background_tasks: set[asyncio.Task[None]] = set()


async def _warm_retrieval() -> None:
    """Build the semantic reference index off the request path at startup, so the
    first utterance doesn't pay the one-time ~3-4 s template-bank embedding cost.
    Idempotent with the lazy fallback in the LLM stage (index_references is
    locked), so an utterance arriving mid-warm is correct, just slower once."""
    from quorum.pipeline.retrieval import get_retrieval
    from quorum.pipeline.templates import all_templates

    try:
        retrieval = get_retrieval(settings)
        if retrieval is None or retrieval.indexed:
            return
        await asyncio.to_thread(retrieval.index_references, all_templates())
        _log.info("retrieval_index_warmed")
    except Exception as exc:  # best-effort warm; the lazy fallback still covers it
        # Surface through the app logger, not just asyncio's GC "never retrieved".
        _log.warning("retrieval_warm_failed", error=str(exc))


def _handler_for(room_name: str, manager_room: object) -> MessageHandler:
    handler = _handlers.get(room_name)
    if handler is None:
        handler = MessageHandler(manager_room)  # type: ignore[arg-type]
        _handlers[room_name] = handler
    return handler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _log.info(
        "startup",
        version=__version__,
        stt=str(settings.stt_backend),
        llm=str(settings.llm_backend),
        retrieval=str(settings.retrieval_backend),
        vad_silence_ms=settings.vad_silence_ms,
    )
    # Warm the semantic index in the background (no-op unless retrieval=local), so
    # startup stays instant but the index is ready before the first utterance.
    warm = asyncio.create_task(_warm_retrieval())
    _background_tasks.add(warm)
    warm.add_done_callback(_background_tasks.discard)
    yield
    # Let any in-flight cache write finish before the process exits.
    from quorum.pipeline.retrieval import get_retrieval

    retrieval = get_retrieval(settings)
    if retrieval is not None:
        await retrieval.flush()
    _log.info("shutdown")


app = FastAPI(title="Quorum Gateway", version=__version__, lifespan=lifespan)

# LAN access: phones on the network hit the Vite dev origin. Permissive in dev;
# Phase 5 tightens this to the known origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "rooms": len(_rooms.rooms),
            "backends": {
                "stt": str(settings.stt_backend),
                "llm": str(settings.llm_backend),
                "vad": str(settings.vad_backend),
            },
        }
    )


@app.get("/metrics/latency")
async def latency_metrics() -> JSONResponse:
    """Live per-stage latency ledger (p50/p95/mean). Feeds context.md §7."""
    return JSONResponse(get_ledger().summary())


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """The single realtime channel. First message MUST be a `join`."""
    await websocket.accept()
    conn: WebSocketConnection | None = None
    room = None
    room_name: str | None = None
    try:
        # Handshake: the first frame establishes identity + room.
        raw = await websocket.receive_text()
        try:
            join = JoinMessage.model_validate_json(raw)
        except Exception:
            await websocket.close(code=4400, reason="first message must be a valid join")
            return

        room_name = join.room
        room = await _rooms.get_or_create(room_name)
        conn = WebSocketConnection(websocket, join.speaker_id, join.role or Role.PARTICIPANT)
        room.add(conn)
        handler = _handler_for(room_name, room)

        # Send welcome + current snapshot so a late joiner is immediately in sync.
        await handler.dispatch(conn, join)
        await room.send_snapshot(conn)

        # Main receive loop.
        while True:
            frame = await websocket.receive_text()
            await handler.handle_raw(conn, frame)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _log.warning("ws_error", error=str(exc))
    finally:
        if room is not None and conn is not None:
            room.remove(conn)
            if room.is_empty and room_name is not None:
                _handlers.pop(room_name, None)
                await _rooms.drop_if_empty(room_name)


def main() -> None:
    """`python -m quorum.app` / console entrypoint for local runs."""
    import uvicorn

    uvicorn.run(
        "quorum.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
