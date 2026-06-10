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

## Using your voice (the MVP path)

Tap **🎤 Speak** in the Participant view and talk. The browser's speech
recognition (Web Speech API) endpoints your utterance and the final transcript
drives the pipeline. Things the rules classifier understands today:

| You say | What happens |
|---|---|
| "a red circle", "a rectangle with a fillet" | creates a sketch |
| "how about a triangle instead" | branches a sibling variant off the focus |
| "make the circle bigger", "make it rounded" | modifies the named node / the focus |
| "let's go with the triangle", "maybe the box" | focuses + affirms (strength-weighted) |
| "not the triangle" | dis-affirms; twice rejects it off the board |
| "scrap the circle", "get rid of that" | prunes a branch |
| "connect the box to the circle" | draws a workflow edge |

Anything else is a low-confidence NOOP (Phase 4 escalates those to the LLM).

> **Voice caveats (MVP):** Chrome/Safari only, and the mic needs a **secure
> context** — `localhost` works out of the box; a phone hitting a LAN IP needs
> HTTPS (e.g. `vite --https` + a local cert) or Chrome's
> `chrome://flags/#unsafely-treat-insecure-origin-as-secure` flag. The text box
> is the always-works fallback, and Phase 1b moves STT server-side (Silero VAD +
> faster-whisper) behind the same protocol, removing the browser dependency.

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

Phase 1a — **Voice MVP built** (see `plan.md` §1.1 for the MVP definition):
speak → intent → branching idea tree with visible derivation edges → shared
display, multi-user over LAN. Awaiting live-mic review; Phase 1b (server-side
STT) is next. See `context.md` for the live state.
