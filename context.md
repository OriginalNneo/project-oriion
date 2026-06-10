# context.md — Living Project State

> **Purpose:** the always-current snapshot of where Quorum actually *is*. Unlike
> `plan.md` (which describes the intended design and changes rarely), this file
> changes constantly. The agent updates it **after every completed segment** —
> see `RULES.md`. Read this first at the start of any session.

> **Last updated:** 2026-06-10  ·  **Current phase:** Phase 0 — Skeleton ✅ (done; ready for Phase 1 review)

---

## 1. One-line status
**Phase 0 complete and demoable.** React client ↔ FastAPI WebSocket ↔ engine ↔
SVG renderer ↔ broadcast loop runs end to end, verified live over a real socket.
All checks green (ruff, mypy strict, 34 backend tests, tsc, vite build).

## 2. Current focus
- [x] Phase 0: prove the loop — participant client → WS → Design State Engine →
      SVG render → diff broadcast → both Participant and Display views update.
- [ ] **Review checkpoint** (RULES.md §3): human review before starting Phase 1.

## 3. What's done
_(append-only-ish; newest at top)_
- **Phase 0 skeleton — the loop is proven.** Modular monolith stood up with every
  pipeline seam already behind a `Protocol` so Phases 1–4 slot in, not rewrite:
  - `domain/` — shared contracts: `GeometrySpec`, `DesignOp` (+ `ClassifierContext`/
    `NodeRef`), idea-tree `IdeaNode`, append-only `DesignEvent`, and the full WS
    wire protocol (`messages.py`), mirrored in TS (`frontend/src/protocol.ts`).
  - `pipeline/renderer.py` — pure, deterministic, LRU-cached SVG renderer behind
    `Renderer` Protocol. `pipeline/interfaces.py` declares VAD/STT/Classifier
    contracts for later phases. `pipeline/classify.py` — rules-only classifier
    (cascade stage A) + the Phase-0 `demo_op` translator.
  - `engine/` — **Design State Engine**: the sole state writer, event-sourced DAG,
    injectable clock + monotonic ids (deterministic/testable). Handles
    create/branch/modify/focus/prune/connect against one fixed contract.
  - `gateway/` — WebSocket rooms, sessions/identity, concurrent broadcast fan-out
    (transport abstracted behind `Connection` for testability); `app.py` FastAPI
    entrypoint with `/healthz` and `/metrics/latency`.
  - `observability/` — structlog + a per-stage latency ledger (p50/p95) + a
    repeatable latency harness (stood up early per RULES.md §6).
  - `frontend/` — React+Vite+Zustand+rough.js. One codebase, two roles:
    Participant (controls + transcript + correction) and Display (calm, view-only).
    Store holds only a *view* of broadcast state (RULES.md §4).
  - Tests: renderer/engine/classifier units, room/broadcast units, **WS
    integration loop test**, latency benchmark (first-class), concurrency smoke.
- Architecture, latency budget, and phased plan drafted → `plan.md`.
- Build rules and check cadence drafted → `RULES.md`.
- Agent operating instructions drafted → `CLAUDE.md`.

## 4. What's next (short queue)
1. **Phase 1 — single-mic E2E:** add the real audio path behind the existing
   Protocols: client mic capture (Web Audio → 16 kHz PCM over WS) → Silero VAD/
   endpointing (`VAD`) → faster-whisper STT (`Transcriber`) → the rules classifier
   (already built) → engine → render. Wire `QUORUM_STT_BACKEND=local`.
2. Extend the latency harness with the real STT/VAD timings; record to §7.
3. Phase 2 — idea tree polish (branch layout, affirmation/prune already in engine).

## 5. Decisions log
_(why we chose what — so we don't relitigate it)_
| Date | Decision | Reason |
|---|---|---|
| — | Web React, not React Native | Brief settled on browser web-app accessed by LAN IP |
| — | Speaker = mic = user; no diarization | Each user logs in on own device; removes a slow, error-prone stage |
| — | Per-utterance processing (VAD-bounded), not continuous streaming | Bounds latency; only acts on finished thoughts |
| — | 3-stage classifier cascade (rules→embeddings→LLM) | Keeps median latency low; LLM is the exception |
| — | Modular monolith for Phases 0–4; services only at Phase 5 | Avoid premature microservices |
| — | SVG via rough.js (low-fi look) | Sketchy output invites iteration; serves the alignment goal |
| 2026-06-10 | Build Phase 0 with all stage *seams* already behind Protocols (engine, renderer, classifier, VAD/STT interfaces) | Phase 0 "done when" is the loop, but RULES.md §2 demands swappable interfaces; doing seams now means Phases 1–4 slot in, not rewrite |
| 2026-06-10 | Server-side renderer is the deterministic *reference*; rough.js does the sketchy look client-side | One pure cacheable render for tests/benchmark/export; the low-fi aesthetic stays a client concern |
| 2026-06-10 | uv venv pinned to Python 3.12 (system is 3.14) | ML stack (faster-whisper/silero/sentence-transformers) lacks 3.14 wheels; 3.12 is safe for Phase 1 |
| 2026-06-10 | Heavy ML deps behind `[local]`/`[embeddings]`/`[groq]` extras | Phase 0 + CI stay lean and installable; pull extras when the stage lands |
| 2026-06-10 | Classifier takes a read-only `ClassifierContext` (focus + candidate NodeRefs), not just `focus_node_id` | Lets the rules stage resolve a *named* preference ("go with the triangle") to a node; same context feeds the Phase-4 LLM for relational intent. Caught live: bare focus_node_id mis-focused. Engine stays sole state owner. |
| 2026-06-10 | Engine uses injectable Clock + MonotonicCounter (no `time()`/uuid inline) | Deterministic ids/timestamps → replayable event log + testable engine |
| 2026-06-10 | Per-room asyncio lock around engine.apply; broadcast fan-out outside the lock | Serializes the single writer (RULES.md §5) without serializing slow client I/O; rooms are independent |

## 6. Open questions
- Preference-signal strength taxonomy ("maybe" vs "let's go with"). _Partially
  settled:_ rules classifier now scores by phrase strength (`_PREFERENCE_PHRASES`
  in `classify.py`): "let's go with"=1.0, "i prefer"=0.9, "maybe the"=0.3,
  "not the"=-0.6. Refine these once we have real sessions.
- Explicit verbal "commit/lock" command needed? (Still open; engine has `focus`
  but no hard lock — a high-affirmation focus is the current proxy.)
- Workflow mode: shared renderer with geometry mode or separate? _Leaning shared:_
  `node`/`edge` are already `ShapeKind`s rendered by the one renderer + `connect`
  op exists in the engine. Validate when workflow mode gets real UX.
- Phase-4 default LLM: local Llama 3.2 3B vs Groq (privacy vs speed) — benchmark.
- Resolving *non-shape* relational references ("the second one", "Bob's one") —
  rules can't; this is the concrete Phase-4 LLM (stage C) job. `ClassifierContext`
  already carries the candidate `NodeRef`s the LLM will need.

## 7. Latency ledger
_(measured numbers go here as soon as we have them — never guess once we can measure)_
_Phase 0 measured via `pytest -m latency` harness (200 iters, MacBook, mock backends — no STT/LLM yet)._
| Stage | Target | Measured (p50 / p95) | Notes |
|---|---|---|---|
| Endpointing | 0.2–0.5 s | — | Phase 1 (VAD) |
| STT | <1 s | — | Phase 1 (faster-whisper) |
| Classify (fast) | <0.2 s | **0.02 ms / 0.03 ms** | rules stage only; well under budget |
| Classify (LLM) | <1.5 s local | — | Phase 4 |
| Render | <0.5 s | **~0.00 ms / 0.01 ms** | deterministic + LRU-cached (cache hits sub-µs) |
| Engine apply | (internal) | **0.04 ms / 0.05 ms** | DAG mutation + event append |
| **End-to-end (common)** | **<5 s** | **0.058 ms / 0.089 ms** | fast path only (classify+engine+render); STT/LLM budget still free |

> Read-back: the existing fast-path tail is ~3–4 orders of magnitude under the
> 5 s budget, so the whole budget is available for STT/VAD/LLM when they land.
> Live `/metrics/latency` confirmed the same numbers over a real WS session.

## 8. Glossary
- **DesignOp** — the structured intent object the classifier emits (see plan §3.3).
- **Idea tree** — the branching DAG of sketch variants.
- **Affirmation score** — how much the group has verbally favored a node.
- **Focus** — the currently-preferred node; new ops default to modifying it.
- **Cascade** — the rules→embeddings→LLM classifier escalation.
- **Endpointing** — deciding when an utterance has ended (via VAD silence).

## 9. Environment / how to run
```
# --- backend (Python 3.12 via uv) ---
cd backend
uv sync                                   # add: --extra local  (Phase 1 STT/VAD)
uv run uvicorn quorum.app:app --reload --host 0.0.0.0 --port 8000
#   GET /healthz            -> status + active backends
#   GET /metrics/latency    -> live per-stage p50/p95 ledger
#   WS  /ws                 -> single realtime channel (first frame must be `join`)

# --- frontend (Node, Vite) ---
cd frontend
npm install
npm run dev                                # Vite on 0.0.0.0:5173, proxies /ws -> :8000
#   Participant (phone):  http://<LAN-IP>:5173/?room=demo&name=alice
#   Display (HDMI):       http://<LAN-IP>:5173/display?room=demo

# --- checks (per RULES.md §3) ---
cd backend && uv run ruff check . && uv run mypy quorum tests \
  && uv run pytest -q && uv run pytest -m latency -s
cd frontend && npm run typecheck && npm run build

# --- 12-factor env (backend/.env.example) ---
# QUORUM_STT_BACKEND=mock|local|groq   QUORUM_LLM_BACKEND=mock|local|groq
# QUORUM_VAD_BACKEND=mock|local        QUORUM_VAD_SILENCE_MS=300  (latency knob)
# QUORUM_GROQ_API_KEY=...              QUORUM_WHISPER_MODEL=small
```

## 10. Phase 1 entry notes (for next session)
- The classifier, engine, renderer, broadcast, and the `UtteranceMessage` path
  already work — Phase 1 only adds the *front* of the pipeline (mic → VAD → STT),
  feeding text into the existing `_on_utterance` handler. No tail changes.
- New impls go behind `pipeline/interfaces.py` (`VAD`, `Transcriber`); select via
  `QUORUM_VAD_BACKEND` / `QUORUM_STT_BACKEND`. Add their `stage_timer(...)` calls
  so the ledger fills in the empty rows automatically.
- `AudioMessage` is already in the wire protocol (accepted, currently a no-op).
