# Quorum

> Multiple people in a design discussion each speak into their own mic. Quorum
> listens to everyone concurrently, understands the design intent, and renders
> shared low-fidelity 2D sketches live on a common display — growing a branching
> **idea tree** that tracks which direction the group is converging on.

The conversation *is* the input device.

See [`plan.md`](./plan.md) for the architecture, [`context.md`](./context.md) for
current state, [`RULES.md`](./RULES.md) for the build contract, and
[`CLAUDE.md`](./CLAUDE.md) for the agent operating instructions.

---

## Repo layout

```
backend/          FastAPI async gateway + pipeline (modular monolith)
  quorum/
    config/         12-factor settings (env-driven)
    domain/         core contracts: DesignOp, idea-tree Node, state diffs
    pipeline/       swappable stages behind Protocols (VAD, STT, classify, render)
    gateway/        WebSocket rooms, sessions, broadcast fan-out
    observability/  structlog + per-stage latency timing
    engine/         Design State Engine (the only writer of session state)
  tests/          unit + integration + latency harness
frontend/         React + Vite (Participant view + Display view, one codebase)
```

## Quickstart

### Backend
```bash
cd backend
uv sync                      # create venv + install deps
uv run uvicorn quorum.app:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev                  # Vite dev server on http://localhost:5173
```

Open the **Display** view fullscreen on the HDMI'd laptop:
`http://<LAN-IP>:5173/display?room=demo`

Open the **Participant** view on each phone:
`http://<LAN-IP>:5173/?room=demo`

## Configuration (12-factor — all via env)

| Var | Default | Meaning |
|---|---|---|
| `QUORUM_STT_BACKEND` | `mock` | `mock` \| `local` (faster-whisper) \| `groq` |
| `QUORUM_LLM_BACKEND` | `mock` | `mock` \| `local` (Ollama) \| `groq` |
| `QUORUM_VAD_SILENCE_MS` | `300` | endpointing silence window (latency knob) |
| `QUORUM_GROQ_API_KEY` | — | required if any backend is `groq` |
| `QUORUM_LOG_LEVEL` | `INFO` | structlog level |
| `QUORUM_HOST` / `QUORUM_PORT` | `0.0.0.0` / `8000` | bind address |

See `backend/.env.example`.

## Checks (run per segment — see `RULES.md` §3)

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy quorum
uv run pytest                       # unit + integration
uv run pytest -m latency            # latency benchmarks (first-class tests)
```

## Status

Phase 0 — Skeleton: React client ↔ FastAPI WS ↔ hardcoded SVG renders on the
Display view. See `context.md` for the live state.
