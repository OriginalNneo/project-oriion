# Quorum — System Architecture & Build Plan

> **Working codename:** *Quorum* (a quorum is the group needed to reach a valid
> decision — fitting for a tool whose whole job is helping a group of voices
> converge on a shared design). Rename freely.

> **Status:** Building. This document is the source of truth for *what we are
> building and why*. Day-to-day state lives in `context.md`. Build discipline
> lives in `RULES.md`. The agent's operating instructions live in `CLAUDE.md`.
>
> **Change log** (RULES.md §7 — design-intent changes only):
> - 2026-06-10 — added §1.1 (explicit MVP definition) and split Phase 1 into a
>   browser-voice MVP track (1a) and a server-STT track (1b). Reason: "prove the
>   loop" was defined, but "what is the shippable MVP" was not; and the Web
>   Speech API gives a real voice path with zero server ML deps, behind the
>   *same* wire protocol the server STT will use.

---

## 1. Vision

Multiple people in a design discussion each speak naturally into their own
microphone. The system listens to everyone **concurrently**, understands the
design intent in what they say, and renders shared **low-fidelity 2D sketches**
live on a common display. As the conversation branches ("what about a triangle
instead?"), the system grows a **branching idea tree** that everyone can see and
align around — and quietly tracks which branch the group is gravitating toward.

The point is alignment. Today, one person drives the CAD tool / whiteboard /
Figma file while everyone else waits and describes. Quorum removes that
bottleneck: the conversation *is* the input device.

### Two example modes (from the brief)
- **Geometry mode:** "rectangle with a fillet" → sketch appears. "how about a
  triangle fillet" → a sibling variant appears next to it. "actually, prefer the
  triangle" → the system focuses that branch.
- **Workflow mode:** people describe a system/process out loud; nodes and arrows
  assemble live, no one has to stop and drag boxes.

### 1.1 The MVP — definition of done

The MVP is the smallest version a real group can actually *use* in a real
design conversation. It is done when all of these hold in one live session:

1. **Voice in.** A participant opens the web app on their own device, taps the
   mic, and speaks. No typing required for the happy path. (MVP voice = the
   browser's Web Speech API doing capture/endpointing/STT client-side, emitting
   final utterances over the existing `utterance` message — the server-side
   VAD + faster-whisper path is an *upgrade* behind the same protocol, not a
   prerequisite.)
2. **Intent out.** The rules classifier handles the core spoken vocabulary:
   create ("a red circle"), branch ("how about a triangle instead"), modify
   ("make the circle bigger"), preference ("let's go with the triangle",
   "not the triangle"), prune ("scrap the circle"), connect ("connect the box
   to the circle").
3. **A visible idea tree.** Derivation edges are drawn — variants visibly hang
   off the idea they came from; the focused branch is emphasized; rejected
   branches fade.
4. **Multi-user.** N participants + 1 display join the same room over the LAN;
   everyone sees the same tree update live; speaker attribution shows on each
   node.
5. **Trust loop.** Each utterance echoes back as a visible transcript line, and
   a text box doubles as the correction path.
6. **Inside budget.** End-to-end < 5 s common case, measured by the harness and
   the live `/metrics/latency` ledger.

Out of scope for the MVP (and explicitly so): server-side STT, the embedding/
LLM classifier stages, persistence beyond a session, auth, cloud deployment.

---

## 2. Requirements

### Functional
- F1 — Multi-user capture: each user = own device = own mic = own web session.
- F2 — Speaker attribution **for free**: because each mic maps to one logged-in
  user, we never need audio diarization. This is a major simplification — lean
  on it hard.
- F3 — Near-real-time transcription per stream.
- F4 — Intent extraction: transcript → structured **DesignOp**.
- F5 — 2D sketch generation (SVG, low-fidelity).
- F6 — Branching idea tree (DAG): variant spawning, preference tracking,
  focus/prune.
- F7 — Shared display: a presentation-mode client (view-only, fullscreen),
  intended to be driven over HDMI from a laptop.
- F8 — Local-first, then cloud.

### Non-functional (the "SaaS standard" attributes)
- **Latency** — end-to-end target **< 5 s** common case, **< 15 s** worst case
  (the brief's ask). Budget in §5.
- **Modularity** — every pipeline stage is a swappable module behind an
  interface. Swapping local Whisper for cloud Groq is a config change, not a
  rewrite.
- **Scalability** — stateless gateways, horizontal scaling, pub/sub fan-out.
- **Concurrency** — async end to end; nothing blocks the event loop; N speakers
  process in parallel, not in a queue.
- **Observability** — structured logs, per-stage latency metrics, request
  tracing. We cannot optimize what we don't measure.
- **Testability** — each segment independently testable; **latency benchmarks
  are first-class tests**, not an afterthought.
- **Fault tolerance** — graceful degradation: if the LLM stage is slow or down,
  the fast classifier path still produces a usable sketch.
- **12-factor** — config via env vars, stateless processes, attached backing
  services. Keeps the local→cloud jump cheap.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  CLIENTS (browser, React web app)                                     │
│                                                                       │
│   Participant client × N            Display client × 1                │
│   ┌──────────────────┐              ┌──────────────────────────┐      │
│   │ mic capture       │              │ fullscreen idea tree     │      │
│   │ client-side VAD?  │              │ (view-only, HDMI out)    │      │
│   │ live transcript   │              │ animated transitions     │      │
│   │ idea-tree view    │              └──────────────────────────┘      │
│   └────────┬─────────┘                          ▲                      │
└────────────│────────────────────────────────────│─────────────────────┘
        audio frames (WS)                    state diffs (WS)
             │                                     │
┌────────────▼─────────────────────────────────────┴─────────────────────┐
│  GATEWAY  (FastAPI + WebSocket, async, stateless)                        │
│  rooms · sessions/identity · audio ingest · broadcast fan-out            │
└────────────┬─────────────────────────────────────▲─────────────────────┘
             │                                       │
┌────────────▼───────────────────────────────────────────────────────────┐
│  PIPELINE  (async stages — each a swappable module)                      │
│                                                                          │
│  1. Buffer + VAD/endpointing  ── per-stream, emits "utterance complete"  │
│            │                                                             │
│  2. STT (transcription)       ── faster-whisper (local) | Groq (cloud)   │
│            │                                                             │
│  3. Intent classifier CASCADE ── A: rules  B: embeddings  C: LLM         │
│            │                       (see §5 — this is the latency story)  │
│  4. Design State Engine       ── applies DesignOp to the idea-tree DAG   │
│            │                       (single source of truth per session)  │
│  5. Sketch renderer           ── geometry spec → SVG (deterministic)     │
│            │                                                             │
│  6. Broadcast diff ───────────────────────────────────────────────▲     │
└──────────────────────────────────────────────────────────────────│─────┘
                                                              back to clients
```

### 3.1 Clients
- **React (web)**, served in the browser. The brief settled on *web apps*
  accessed over the LAN by IP — so web React, not React Native. (A native RN
  app is a possible Phase 6+ nicety; not now.)
- Two roles share one codebase:
  - **Participant** — mic capture + idea-tree view + a live transcript of *what
    the system heard you say* (transparency builds trust) + an "I meant X"
    correction affordance.
  - **Display** — fullscreen, view-only, minimal chrome, smooth animated
    transitions. This is the screen on the HDMI'd laptop / board.
- Audio: Web Audio API → 16 kHz mono PCM frames → WebSocket. Optional
  client-side VAD to only transmit speech (saves bandwidth + server load).

### 3.2 Gateway
- FastAPI with `websockets` (or Socket.IO for built-in rooms/reconnect).
- Responsibilities: connection lifecycle, room membership, session identity,
  audio ingest routing, state-diff broadcast.
- **Stateless** — holds no authoritative state itself, so it scales
  horizontally behind a load balancer (with sticky sessions for WS). In Phase
  5 the shared state moves to Redis so any gateway instance can serve any
  client.

### 3.3 Pipeline stages
Each stage implements a small interface so it's independently swappable and
testable.

1. **Buffer + VAD / endpointing.** Per-stream ring buffer. A VAD (Silero) finds
   utterance boundaries and emits an "utterance complete" event after a short
   silence window. *This is the design decision that bounds latency:* we
   transcribe per **utterance**, not continuously — so the clock only starts
   when someone finishes a thought. The silence window (≈200–500 ms) is a
   directly tunable latency knob.

2. **STT (transcription).** Pluggable behind a `Transcriber` interface.
   - Local: `faster-whisper` (`small` or `base`) — free, private, no network.
   - Cloud: **Groq Whisper Large v3 Turbo** — purpose-built inference hardware,
     ~200 ms round-trip for a ~5 s chunk; segmented (VAD-buffered) so it returns
     a clean final transcript per utterance.
   - Output: `{text, speaker_id (from mic), utterance_id, ts}`.

3. **Intent classifier — a 3-stage CASCADE.** This is the heart of the latency
   story; see §5 for the full timing breakdown.
   - **A — Rules / regex** (~1–10 ms): shape + modifier keywords
     ("rectangle", "fillet", "circle", "arrow", "connect to"). Catches the
     obvious majority.
   - **B — Embedding nearest-neighbor** (~20–100 ms): encode the utterance
     (`all-MiniLM-L6-v2`), match against a library of operation templates.
     Robust to natural phrasing that rules miss.
   - **C — Small LLM** (~0.2–0.8 s Groq / ~0.5–1.5 s local 3B): only for
     genuinely ambiguous, novel, or *relational* intent ("make the second one's
     corners match the first") and **preference signals** ("let's go with…",
     "I prefer…", "actually the triangle"). Emits structured JSON.
   - Output **DesignOp**:
     ```json
     {
       "op_type": "create | modify | branch | focus | prune | connect",
       "target_shape": "rectangle | circle | triangle | node | edge | ...",
       "modifiers": ["fillet", "radius:8", ...],
       "relation_to_node": "<node_id> | null",
       "preference_signal": -1.0 .. 1.0,
       "speaker_id": "...",
       "confidence": 0.0 .. 1.0
     }
     ```

4. **Design State Engine.** The single source of truth per session. Applies a
   DesignOp to the **idea-tree DAG**: creates nodes, links variants as siblings,
   updates `affirmation_score`, sets `focus`, prunes low-score branches. Backed
   by an **append-only event log** (event sourcing) so we get replay, audit, and
   undo for free.
   - **Node** = `{id, geometry_spec, svg, parent_ids[], provenance{speaker, ts,
     utterance}, affirmation_score, status: active|focused|pruned}`.

5. **Sketch renderer.** A *pure, deterministic* function: geometry spec → SVG.
   No side effects, so it's trivially testable and cacheable. Low-fidelity look
   via `rough.js` (see §7 for why the "sketchy" aesthetic matters).

6. **Broadcast.** Push a **state diff** (not the whole tree) to all clients over
   WebSocket. Clients animate the change.

### 3.4 State & data
- Local PoC: idea-tree DAG + event log in memory. No database needed.
- Cloud: session state + pub/sub in **Redis**; optional Postgres/SQLite for
  durable session history. The event log makes persistence a clean add-on.

---

## 4. The idea tree (F6) in detail

This is what makes Quorum more than "voice → drawing."

- Each design suggestion becomes a **node**. A variation of an existing idea
  becomes a **child/sibling** linked to its origin — so "rectangle fillet" →
  "triangle fillet" draws a visible derivation edge.
- Multiple live options coexist on screen (the "idea cloud").
- **Affirmation tracking:** preference signals from stage-C bump a node's
  `affirmation_score`. "Let's go with the triangle" raises that node and sets
  `focus`; the display emphasizes it and de-emphasizes the rest.
- **Pruning:** branches that stay un-affirmed past a threshold (or beyond a
  max-branch cap) fade/collapse so the tree doesn't explode.
- **Focus mode:** once a branch is clearly preferred, new ops default to
  modifying *that* node unless someone explicitly branches again.

---

## 5. Latency budget & the classifier timing (explicitly asked)

End-to-end latency = `endpointing + STT + classify + render + broadcast`.
Figures below are realistic ranges from current benchmarks; the **cascade** is
what keeps the *median* low.

| Stage | Local (MacBook) | Cloud (Groq) | Notes |
|---|---|---|---|
| Endpointing (VAD silence window) | 0.2–0.5 s | 0.2–0.5 s | Tunable knob; same either way |
| STT | 0.3–1.0 s (faster-whisper small) | ~0.2 s (Whisper v3 Turbo) | Per short utterance |
| **Classify — fast path (A+B)** | **0.05–0.2 s** | **0.05–0.2 s** | Rules + embeddings; **most utterances** |
| **Classify — LLM path (C)** | **0.5–1.5 s** (Llama 3.2 3B) | **0.2–0.8 s** (Groq) | Only ambiguous/relational/preference |
| Render SVG | 0.05–0.5 s | 0.05–0.5 s | Deterministic |
| Broadcast + client render | 0.05–0.2 s | 0.05–0.2 s | WS diff |

**Common case** (fast path hits): **≈ 0.6–2 s.**
**Worst case** (local LLM path, complex relational op): **≈ 3–5 s.**
Both sit comfortably inside the 5–15 s target, with room to spare.

### Why the classifier is fast *on average*
1. **Cascade, not monolith.** Simple utterances ("rectangle", "add a fillet",
   "go with the triangle one") never reach the LLM. The LLM is the exception,
   not the rule — so its 0.5–1.5 s cost is paid rarely.
2. **Speculative parallelism.** When we *do* expect to need the LLM, fire stage
   C in parallel with A+B rather than after them. If A+B come back confident, we
   ship that result and discard the LLM call; if not, the LLM result is already
   most of the way done. This **hides** LLM latency behind work we were doing
   anyway.
3. **Per-utterance, not streaming-token.** We only act on completed thoughts, so
   we never pay to re-classify partial words.
4. **Speaker is free.** No diarization stage (which would add seconds and
   error) because mic = user.

### Tuning levers, in order of impact
1. VAD silence window (lower = snappier but more premature cut-offs).
2. STT backend (Groq Turbo ≫ local for raw speed; local wins on privacy/cost).
3. Confidence threshold for escalating to the LLM (higher threshold = fewer LLM
   calls = lower median latency, at some accuracy cost).
4. SVG render caching for repeated geometry.

---

## 6. Phased rollout

| Phase | Goal | Done when… |
|---|---|---|
| **0 — Skeleton** | Prove the loop | React client ↔ FastAPI WS ↔ hardcoded SVG renders on screen |
| **1a — Voice MVP (browser STT)** | The §1.1 MVP | Mic toggle → Web Speech API → `utterance` → rules classifier → idea tree w/ derivation edges, multi-user |
| **1b — Server STT** | Privacy/offline voice | Client PCM over WS → Silero VAD → faster-whisper, same protocol, `QUORUM_STT_BACKEND=local` |
| **2 — Idea tree** | Branching + preference | DAG variant spawning, affirmation scoring, focus/prune working |
| **3 — Multi-client (LAN)** | Concurrency | Phones join by IP, each own mic/session, N streams process in parallel, shared display |
| **4 — Classifier upgrade** | Robustness + speed | Embedding stage + LLM stage + speculative parallelism |
| **5 — Cloud / SaaS** | Scale | Dockerized, Redis pub/sub + state, worker pools, LB w/ sticky WS, auth, rooms, persistence |

Rule of thumb: **don't microservice early.** Phases 0–4 are a clean modular
*monolith*. Phase 5 splits only the stages that actually need independent
scaling (STT, classify, render).

---

## 7. UI / UX

- **Low-fidelity on purpose.** Render with `rough.js` (hand-drawn look). This is
  not decoration: polished-looking output makes people defensive about changing
  it; sketchy output signals "this is a draft, keep iterating," which directly
  serves the alignment goal.
- **Transparency.** Each participant sees a live transcript of what the system
  *heard them say* and a one-tap "I meant X" correction. Trust is the whole
  game; a wrong sketch with no visible cause kills it.
- **Latency masking.** Show "listening… / sketching…" states so the unavoidable
  ~1–2 s feels intentional, not laggy.
- **Provenance.** Nodes carry a quiet "suggested by ___" label — useful for
  group dynamics and for the design record.
- **Display view ≠ participant view.** The HDMI screen is calm and big; the
  phones hold the controls and feedback.

---

## 8. Tech stack (with reasoning)

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite, Zustand, `rough.js` SVG | Fast dev loop; SVG scales without recompute; rough.js for low-fi feel |
| Gateway/Backend | Python 3.11+, FastAPI (async), uvicorn | Async-native → true concurrency; rich STT/ML ecosystem |
| Realtime | WebSocket (`websockets` or Socket.IO) | Bidirectional, low-overhead fan-out |
| VAD | Silero VAD | More accurate endpointing than WebRTC VAD |
| STT | `faster-whisper` (local) ⇄ Groq Whisper v3 Turbo (cloud) | Swappable behind one interface; local=private/free, cloud=fastest |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) | Tiny, fast, good enough for template matching |
| LLM | Ollama + Llama 3.2 3B (local) ⇄ Groq Llama (cloud) | Small model is plenty for structured intent JSON |
| State/PubSub (cloud) | Redis | Standard, fast, gives pub/sub + shared session state |
| Packaging | Docker / docker-compose | Clean local→cloud parity |
| Observability | structlog + Prometheus + OpenTelemetry | Per-stage latency is a product requirement, not a nice-to-have |

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| STT mangles domain jargon | Keyterm/vocabulary biasing; per-user transcript + correction affordance |
| Intent ambiguity → wrong sketch | Confidence threshold → escalate to LLM; "I heard X, correct?" UX |
| Latency spikes | Cascade + speculative parallelism + graceful degradation to fast path |
| People talk over each other | Mic-per-user already isolates streams; independent per-stream VAD |
| Idea tree explodes | Affirmation-based pruning, max-branch cap, focus mode |
| WS scaling under many rooms | Stateless gateways + Redis adapter + sticky sessions (Phase 5) |

---

## 10. Open questions (move to `context.md` as they resolve)
- Exact preference-signal taxonomy: is "maybe the triangle" weaker than "let's
  go with the triangle"? (Likely yes — score by signal strength.)
- Do we need an explicit "commit / lock this node" verbal command?
- Workflow mode: shared primitive vocabulary with geometry mode, or separate
  renderers?
- Local LLM vs. Groq for Phase 4 default (privacy vs. speed) — benchmark both.
