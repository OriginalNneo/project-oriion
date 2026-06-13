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
> - 2026-06-11 — added §11 (Drawing-quality program: intricate shapes & true
>   3D). Reason: live use showed 3D/intricate requests render as "exploded
>   view" flat layouts and instruction-following is weak. A code-verified
>   diagnosis traced most of it to our own prompt/routing/validation (not the
>   model), so the fix is a five-segment program, not a model swap. §11 is the
>   design intent; the live segment status lives in `context.md` §2/§4.
> - 2026-06-12 — added §12 (Compositional iteration & the mind-map canvas).
>   Reason: live user feedback — follow-ups must restyle the SAME object
>   ("make the cube red" redrew a flat 2D cube instead of recoloring the
>   isometric cuboid), every iteration should extend outward as a new node in
>   a mind-map view (history visible), and nameable geometric shapes
>   (rhombus, parallelogram) must draw instantly instead of being skipped.
>   All three diagnosed as codebase gaps, not model gaps.
> - 2026-06-12 (later) — added §13 (Part-level editing & in-chain 3D
>   conversion). Reason: §12 browser feedback — "make this hexagon 3D" and
>   "make one eye bigger than the other" both fail. Probes traced five root
>   causes (demonstratives unresolved, no deterministic extrusion, unnamed
>   template parts, a dead-LLM fallback that scales the WHOLE scene on a
>   part-scoped ask, quota-fragile LLM-only flows). Research (JSON Whisperer,
>   SVGenius/SVGEditBench, aider diff benchmarks) backs an edit-as-PATCH
>   contract over full scene re-emission.
> - 2026-06-13 — added §15 (UI canvas zoom/pan/adaptive + compose-onto-existing).
>   Reason: §14 identified two remaining UX gaps — (a) the mind-map canvas had no
>   zoom/pan and cards became unreachable as the map grew; (b) "draw a box above the
>   horse" created a standalone node instead of composing onto the horse. The
>   full canvas REDESIGN remains gated on the user's pending design reference
>   (noted in §14); §15 is the interim layout-preserving zoom/adaptive pass plus
>   a layout bug fix (depth-compounding radial spacing), not that redesign.

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

---

## 11. Drawing-quality program — intricate shapes & true 3D (2026-06-11)

**The problem.** Live use shows two failure modes: (a) intricate/3D requests
("a 3D engine with pistons") come back as an **exploded view** — parts laid
out flat, side by side, instead of a coherent assembly; (b) instruction
following is weak (counts, colors, exact relations drift).

**The diagnosis (code-verified — full trace in `context.md` §3).** It is
mostly *not* the model. Ranked root causes:
1. The stage-C prompt's decompose-into-parts recipe + every few-shot example
   place parts in **disjoint, non-overlapping regions** — literally an
   exploded-view algorithm.
2. The prompt never explains **painter's-algorithm z-order** (parts render in
   list order; later filled parts occlude), and default `fill: null` makes any
   overlap look like crossing wireframes — so the model rationally avoids
   overlap.
3. 3D guidance exists **only for cubes**; no generalized projection recipe.
4. **Routing bug**: the coverage heuristic filters tokens of length ≤ 2, so
   "3d" is invisible — "a 3D box" matches "box" in rules at conf 0.85 and a
   flat rectangle ships without the LLM ever being consulted.
5. Flat QuickDraw few-shot references **fight** 3D requests ("a 3D car" gets
   the flat side-view doodle as its known-good reference).
6. **All-or-nothing validation selects for timid output**: one bad coordinate
   → the whole response silently becomes a NOOP (no retry-with-error, no
   clamping, no part salvage, no `max_tokens` → truncation = same silent drop).

What is genuinely model-bound: novel 3D projection of complex assemblies and
reliable arithmetic placement exceed llama-3.3-70b single-shot ability
(consistent with public evidence: it appears on no SVG leaderboard; June-2026
SVGBench leaders are Claude Opus 4.6 75.6% / GPT-5.2 74.4%; best open drawers
are GLM-5 70.3% and Kimi K2.5).

### The program — five segments, in order

| # | Segment | Design intent | Done when (incl. latency) |
|---|---|---|---|
| **D1** | Routing + validation repair | "3d/isometric" tokens escalate past rules; LLM output is *repaired*, not dropped: clamp out-of-range coords, salvage valid parts, one retry feeding the validation error back, explicit `max_tokens` | "a 3D box" → cuboid (not flat rect); injected-fault tests show partial salvage; fast-path p95 unchanged |
| **D2** | Prompt overhaul | Teach z-order/occlusion explicitly; fills ON for 3D; one worked example with **overlapping, occluding** parts; "parts attach and overlap — never lay components out side-by-side"; suppress flat QuickDraw refs when utterance says 3D/isometric | Before/after on a fixed 10-prompt intricate/3D set, rendered + eyeballed; no latency regression (same call count) |
| **D3** | **Deterministic isometric projection** (highest leverage) | New IR primitives `box`/`cylinder`/`wedge` with (x,y,z,w,d,h); the *pure renderer* does the 30° projection, face shading, hidden-face handling, z-sort (generalizing `make_isometric.py::_project`). The LLM only reasons about axis-aligned 3D placement — never projection math. Extends the proven `relations.py` pattern: **model proposes, code disposes** | "a 3D engine with pistons" renders as a coherent isometric assembly; renderer stays pure/deterministic/cached; round-trip ≤ current stage-C budget |
| **D4** | Adherence eval + tiered models | Extend `eval_llm.py` to score **instruction adherence** (part counts, colors, overlap/coherence, relations), not just JSON validity. Benchmark GLM-5, Kimi K2.5, Cerebras-hosted Qwen3/gpt-oss on it. Add an **escalation tier** (Gemini 3 Flash or Claude Sonnet 4.6) for intricate/3D-classified prompts, streamed so the canvas animates while drawing | Measured adherence table in the ledger; escalation tier behind env config; fast tier still ≤ 2 s p95 |
| **D5** | Polish loop + template growth (optional) | Async render→VLM-critique→repair pass (~$0.005–0.01/round) after the fast first draw; grow a curated intricate-template bank via frontier batch APIs (Opus/Gemini Pro at 50% batch discount, Recraft V4.1 Vector); verify TU-Berlin license (CC-BY-4.0?) and mine it | Polish round measurably improves the 10-prompt set without touching first-draw latency |

> **Status (2026-06-13): D1 ✅ · D2 ✅ · D3 ✅ · D4/D5 next.** D3 shipped as a
> pure DOMAIN transform (`domain/isometric.py` projects LLM-emitted axis-aligned
> `solids` to a flat polygon/ellipse/path GROUP), **not** inside the renderer as
> this table's wording suggested — both renderers + engine/replay already handle
> GROUPs, so the domain layer means zero renderer/client changes and the
> projection is written once. The plan's intent (deterministic, pure, cached,
> LLM does no projection math) is fully met. Full record + adversarial-review
> fixes in `context.md` §3 (top) and the decisions log. D4 still owes a live
> model probe that the LLM actually emits `solids` (only the projection is
> eyeball-verified so far).

### Model strategy (tiered — latency is the binding constraint)
At ~1.5k output tokens only Groq (~400–500 tok/s) and Cerebras (~3,000 tok/s)
fit the 1–2 s live budget; frontier models take 12–30 s. So: **fast tier**
(live, every utterance) on Groq/Cerebras — candidates GLM-5, Kimi K2.5,
Qwen3-235B, gpt-oss-120B, benchmarked on D4's adherence eval before any
switch; **escalation tier** (intricate/3D only, 5–15 s tolerated, streamed)
on Gemini 3 Flash / Claude Sonnet 4.6; **offline tier** (template-bank
generation, no latency constraint) on Opus / Gemini Pro batch / Recraft.
Never swap the default on benchmarks we didn't run ourselves.

### Dataset constraints (carried forward)
QuickDraw (CC-BY-4.0) remains the only proven ship-safe source. **No
isometric/3D sketch dataset exists on Hugging Face** — the scalable path is
programmatic synthesis (D3) + frontier batch generation (D5), not mining.
TU-Berlin (20k sketches, 250 categories) is the one candidate addition —
verify its CC-BY-4.0 status first. SketchGraphs/sam-dataset (CAD sketches
with constraint graphs) are legally murky to ship (Onshape ToU); MMSVG and
FIGR-8 stay rejected (NC / no-resale).

---

## 12. Compositional iteration & the mind-map canvas (2026-06-12)

### The user intent (live feedback, 2026-06-12)
1. **Iterations compose.** "Draw a cat" → "make the cat orange" must recolor
   THE cat (preserving its drawn shape); "make the cube red" on an isometric
   cuboid must produce the same cuboid with red-shaded faces — never a fresh
   flat 2D square. Later: "shade it into a tabby" (LLM restyle of the same
   geometry).
2. **The canvas is a mind map.** The original idea sits at the center; every
   iteration extends OUTWARD as a new linked node. History stays visible —
   "red phone" is a second-generation node hanging off "phone", not an
   in-place overwrite.
3. **Nameable geometric shapes always draw.** "A rhombus", "a parallelogram",
   "a trapezoid" must render instantly (they are math, not taste) — never be
   skipped because they're absent from the rules vocab and the template bank.
4. Slightly higher quality output, still the lo-fi sketch aesthetic.

### Code-verified diagnosis
- **F1 — "red cube" redraws flat.** `_SHAPE_WORDS` has no "cube"; named-node
  resolution (`_resolve_named`) matches on ShapeKind only, so "the cube"
  cannot resolve to the focused cuboid node. The utterance goes hazy → LLM →
  the model redraws instead of restyling (create-vs-modify slip). Worse, even
  a clean MODIFY can't recolor: `apply_modifiers` maps `color:<hex>` to
  `stroke` only — the cuboid's three shaded face FILLS never re-tint.
- **F2 — no iteration history.** `engine._modify` mutates the node in place;
  there is structurally nothing for a mind map to show.
- **F3 — rhombus skipped.** Not in rules vocab, not a QuickDraw category; a
  failed/dead LLM falls back to a silent NOOP.

### Design (the running pattern: model proposes, code disposes)
- **R1 — Iteration-as-branch (engine).** A MODIFY that effects a real change
  creates a *child* node (parent = target) carrying the new geometry; focus
  moves to the child so follow-ups chain outward. The parent stays intact.
  No-change MODIFYs don't spawn nodes. Ancestors of the focus are exempt
  from cap-pruning (the mind-map trunk must stay visible). Event sourcing
  is unchanged — replay folds node snapshots + FOCUS_CHANGED as today.
- **R2 — Deterministic recolor (domain).** `color:<hex>` re-tints every part:
  a part with a fill takes the target hue/saturation at the part's ORIGINAL
  lightness (HSL), so the cuboid's light/mid/dark grays become light/mid/dark
  reds — shading survives. Strokes likewise; stroke-only sketches (QuickDraw
  cats) take the color directly. Pure function in the domain; no LLM call.
- **R3 — Labels + label resolution (classifier).** `DesignOp` gains `label`;
  template hits stamp the canonical concept name ("cuboid", "cat"), rules
  stamp the shape word, the LLM stage stamps its matched concept. Nodes
  inherit labels through iterations. `_resolve_named` learns to match "the
  <word>" against candidate labels (exact / plural / prefix), and
  label-resolved words count as EXPLAINED — so "I want the cube to be red"
  becomes a clean fast-path MODIFY (0 ms) instead of hazy LLM work.
- **R4 — Named-geometry tier (rules).** Exact generators (pure functions →
  polygon/path specs) for: rhombus/diamond, parallelogram, trapezoid,
  pentagon, hexagon, octagon, star, arrow, cross, semicircle, kite, heart,
  crescent. CREATE conf 0.85, composable into scenes (branch 5), words added
  to the known vocabulary. Zero latency, zero LLM dependency — F3 dies here.
- **R5 — Restyle prompt rule (LLM, additive + eyeball-gated).** Appearance-
  only changes re-emit the SAME geometry with only colors/fills changed
  (coords verbatim); richer restyles ("tabby stripes") stay LLM work anchored
  on `focus_geometry`. Color-only cases never reach the LLM at all (R3).
- **R6 — Mind-map canvas (frontend).** Radial layout: roots at the center,
  depth = ring distance, children fan out within the parent's angular sector;
  curved derivation edges; node label chips; animated position transitions.
  Same component for Participant and Display (RULES.md §4).

### Capability verdict (API vs codebase)
All of F1–F3 are **codebase** gaps — current Groq models suffice because
recolor/containment/tangency/projection are deterministic code. The one
place a better API genuinely helps remains §11 D4's escalation tier
(raw sketch quality for arbitrary concepts); slot a Gemini-Flash/Sonnet key
in there when available — nothing in §12 blocks on it.

### Acceptance (live, end to end)
"draw a cuboid" → isometric template hit; "make the cube red" → NEW child
node, same cuboid geometry, three red-shaded faces, focus on child, parent
visible; "draw a cat" → template cat; "I want the cat to be orange" → child
cat, orange strokes; "a rhombus" → exact polygon, 0 ms; mind map shows the
chains radiating from the originals; all checks + latency budgets green.

---

## 13. Part-level editing & in-chain 3D conversion (2026-06-12)

### The user intent (live §12 browser feedback)
1. **In-chain kind conversion.** "Draw a hexagon" → "turn this hexagon pink"
   → "make this hexagon three-dimensional" must extrude THE pink hexagon
   into a 3D-looking prism, continuing the same mind-map chain.
2. **Part-level nuance edits.** "Draw a mouse" → "add two eyes" → "make one
   eye bigger than the other": humans iterate on tiny features; the system
   must address, add, resize, and restyle individual PARTS of a scene.

### Probe-verified diagnosis (context.md §3)
(1) demonstratives ("this/that hexagon") aren't definite references → CREATE
duplicates; (2) no deterministic 2D→3D path, and the dead-LLM fallback ships
a flat duplicate; (3) template parts are unnamed → unaddressable; (4) the
dead-LLM fallback folds part-scoped modifiers onto the WHOLE scene (probe:
the whole mouse scaled); (5) Groq free-tier quota died mid-session — these
flows must not be LLM-only.

### Research verdict (2026-06-12 subagent; full citations in context.md)
- **Edit-as-patch beats full re-emission** for small scene edits: JSON
  Whisperer (EMNLP '25) — patch ≈ full quality at −31% tokens; SVGenius /
  SVGEditBenchV2 — models pick the right edit TARGET reliably, they fail at
  re-serializing everything else; aider's whole-file-vs-diff results flip in
  favor of whole only when the whole file IS the target. Address parts **by
  stable name, never index** (index arithmetic is the #1 patch failure).
- **Resolve spatial qualifiers in CODE**: left/right = centroid x, top/
  bottom = centroid y, biggest/smallest = bbox area, first/last = paint
  order, widest/tallest. The LLM names the role ("eye"); geometry picks the
  instance.
- **Extrusion convention**: oblique cabinet — front face true-to-shape,
  depth recedes 45° up-right at ~half scale; three visible faces, light
  from top-left (top lightest, side darkest). A "true front face" is
  precisely what 30° isometric cannot give, so cabinet is the deterministic
  choice; shading reuses §12-R2's retint so the hue survives.

### Design (segments)
- **N1 — Reference grammar (classify):** demonstratives this/that/my/our
  join "the" for definite shape AND label references; a determiner + a
  shape/label word that resolves to an existing node + modifiers = MODIFY of
  that node, never a named-shape CREATE. ("turn this hexagon pink" → recolor
  child of the hexagon.)
- **N2 — Part addressing (new `domain/parts.py` + classify):**
  `resolve_parts(scene, phrase)` — role-token match on part names
  (eye-left ↔ "left eye") + geometric qualifiers computed in code;
  `apply_to_parts(scene, names, modifiers)` — modifier fold scoped to the
  matched parts (size scales about the PART's center). Rules fast path:
  modifiers + resolvable part reference → MODIFY with the patched scene,
  conf 0.75, zero LLM. **Fallback inversion:** a part-ish reference that
  does NOT resolve goes out as hazy NOOP (escalate; a dead LLM then does
  NOTHING) — never fold part-scoped modifiers onto the whole scene.
- **N3 — LLM patch contract (llm.py + domain/parts.py):** `PartsPatch`
  {set: [{part, <fields>}], add: [GeometrySpec], remove: [names]}, applied
  remove→set→add by `apply_patch` (pure). Validation per research: unknown
  `set`/`remove` target → drop clause + log (corrective retry once); `add`
  name collision → auto-suffix; `kind` change via set → stripped. The model
  emits ONLY the delta; `payload_to_op` composes the full replacement
  geometry so the engine/replay contract is untouched. Full re-emission
  stays legal for restructures. Template strokes get auto-names
  (`part-1..n`) at library load so every part is addressable. Prompt gains
  PATCH rules + worked examples (add-eyes patch; one-eye-bigger set patch);
  eyeball-gated.
- **N4 — Deterministic extrusion (new `domain/extrude.py` + classify):**
  `extrude(geom, depth≈9)` — silhouette (polygon verbatim; rect/ellipse/
  named shapes polygonalized ≤20 pts) extruded along (+d, −d); visible
  receding faces = silhouette edges whose outward normal faces the offset;
  painter order: receding faces back-to-front, front face LAST; fills =
  three lightness bands of the shape's own hue (retint); parts named
  face-front / face-top-i / face-side-i. Routing: 3D-intent + focus
  reference → MODIFY with extrude(focus_geometry) conf 0.8; 3D-intent + a
  shape word + no focus reference → CREATE extrude(named/basic shape)
  ("draw a 3D hexagon" instantly). Multi-part groups stay LLM territory in
  v1 (documented).
- **N5 — Integration:** e2e chain that runs WITHOUT the LLM: hexagon →
  "turn this hexagon pink" → "make this hexagon three dimensional" →
  n1→n2→n3 chain, n3 ≥3 faces in 3 pink shades. Mouse chain pinned with a
  mocked LLM patch (live re-probe when Groq quota resets). Docs, decisions,
  ledger, commits.

### Capability verdict (API vs codebase)
Still codebase. The patch contract makes part edits MORE reliable on the
SAME small models (less to emit); extrusion and qualifier resolution are
pure math. The quota incident strengthens the D4 case for a second/paid
key — the user has offered to supply APIs; nothing here blocks on it.

### Acceptance (live, end to end)
"a hexagon" → "turn this hexagon pink" (recolor child, same chain) →
"make this hexagon three dimensional" (extruded prism child, three pink
shades, no LLM call); "a mouse" → "add two eyes" (patch-add, named
eye-left/eye-right) → "make the left eye bigger" (rules fast path) and
"make one eye bigger than the other" (LLM set-patch); all §12 behaviors
unregressed; checks + latency green.

---

## 14. Voice undo & viewport follow (2026-06-12)

### The user intent (live §13 browser feedback, verdict "really nice")
1. **Voice undo / go-back.** "I don't really like... never mind, go back to
   the previous situation" must return to the previous iteration so the next
   edit chains from there. User confirmed (2026-06-12): "zoom back out"
   meant the SAME thing — go back, not a literal view zoom.
2. **Iterations land too far away.** Each iteration renders one ring
   (~270 px) further out, so the active sketch drifts off screen (R6's
   watch-item, confirmed live).
3. **The user has a mind-map design reference** (incoming). Any canvas
   REDESIGN is gated on it; only the minimal, layout-preserving viewport fix
   ships now.

### Design (segments)
- **U1 — UNDO op (domain + engine).** New `OpType.UNDO`. Engine: resolve the
  focused node → `parent_ids[0]` → `_set_focus(parent)`; FOCUS_CHANGED enters
  the log (replay fold already handles it — no new replayed state). The
  abandoned child stays ACTIVE and visible (user-confirmed: mind-map history
  stays on the map; no prune, no fade). Undo with no parent (root focus) =
  engine no-op (current view back, no event). Repeated undo walks up the
  trunk. A follow-up MODIFY after undo branches a SIBLING of the abandoned
  child — iteration-as-branch (§12-R1) unchanged.
- **U2 — Undo grammar (classify).** A meta-command branch checked BEFORE the
  content branches and EXEMPT from the hazy caps — the phrase IS the meaning;
  meta-commands never escalate to the LLM (quota-immune by construction).
  Vocabulary: undo, go back, revert, scratch that, never mind, zoom (back)
  out, (go back to the) previous (one/version/situation/step/state). conf
  0.9, source=rules. Guard: if the utterance also carries a resolvable
  label/shape reference ("go back to the cat"), defer to the existing FOCUS
  resolution — undo fires only for bare/previous-situation phrasings.
- **U3 — Viewport follow (frontend, minimal).** On focus change, smooth-
  scroll the focused card into view (centered) inside the existing scroll
  container. NO layout change, NO redesign — that waits for the user's
  design reference.
- **U4 — Integration.** e2e: chain a→b→c, "go back" ×2 walks to the root,
  "make it blue" then branches a SIBLING; §12/§13 chains unregressed;
  checks + ledger + docs + commit.

### Capability verdict (API vs codebase)
Codebase only. Undo never touches the LLM (rules branch + engine focus
move); the viewport fix is client-side. Nothing blocks on a key.

### Acceptance (live, end to end)
"a hexagon" → "turn this hexagon pink" → "never mind, go back" → focus back
on the plain hexagon (pink child still visible) → "make it blue" → NEW
sibling child, blue; "undo" at the root does nothing; the focused card is
always scrolled into view. All §12/§13 e2e steps unregressed; latency green.

---

## 15. UI canvas zoom/pan/adaptive + compose-onto-existing (2026-06-13)

### The user intent (live §14 feedback + UX gaps)
1. **The canvas is too cramped.** As the mind-map grows, cards overflow the
   fixed scroll area and become unreachable; there is no way to zoom out or
   pan freely.
2. **A spatial utterance creates a standalone node instead of extending the
   target.** "Draw a horse" → "draw a box above the horse" produced a new
   standalone box node. The intent is to compose the box onto the horse as a
   child iteration.
3. The earlier §14 note that the **full canvas redesign is GATED on the
   user's design reference** still holds — §15 is the interim, layout-
   preserving zoom/adaptive pass plus a layout bug fix, not that redesign.

### What shipped (2026-06-13)
**Frontend — canvas zoom/pan/adaptive + focus-follow (tsc + vite build green,
193 kB bundle; 8 review bugs caught and fixed via 5-phase workflow):**
- `usePanZoom.ts` (hand-rolled, zero deps): pointer events; ctrl/meta-wheel +
  2-pointer pinch zoom-about-cursor; plain-wheel pan; drag-pan; clamp
  0.2–2.5×; Fit/auto-fit/recenter; ResizeObserver; StrictMode-safe.
- `ZoomControls.tsx`: −/%/+/Fit/Recenter/Follow toggle.
- `IdeaTree.tsx`: `.idea-scroll > .idea-viewport(CSS transform) > .idea-canvas`;
  focus-follow pauses while gesturing; "sketching…" badge. **Fixed radial
  depth-compounding bug** (uniform ring step `kidRadius = R`; ring tightened
  from ~288 px to `max(cw,ch)+60`).
- `styles.css`: full-bleed map (overflow:hidden + transform pan replaces the
  grid overflow-clip that made large maps unreachable); transcript →
  collapsible `<details>` drawer.

**Backend — compose-onto-existing (deterministic; quota-resilient; 436 tests,
+43; ruff+mypy clean; pytest 0.53 s):**
- `domain/compose.py` (new, pure): `place_relative(target, new_part, relation)`
  → flat GROUP fit to the 0..100 box; relations above/below/left/right/
  on_top/behind/inside; z-order; 60-part limit guard.
- `classify.py` branch 5b: "[create/draw/add/put/place] a <shape> <spatial
  relation> the <existing node>" → compose-MODIFY of the RESOLVED target node
  (conf 0.8, source=rules, modifiers=[]); engine branches a child (§12-R1).
  Over-trigger guards keep plain/multi-shape create and recolor intact.

### Pending
Human browser confirm on branch ui-zoom-adaptive-canvas (servers live :8000 /
:5173), then commit and merge. The design-reference-gated canvas redesign
remains open for a future §16 program.
