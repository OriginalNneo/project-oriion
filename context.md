# context.md — Living Project State

> **Purpose:** the always-current snapshot of where Quorum actually *is*. Unlike
> `plan.md` (which describes the intended design and changes rarely), this file
> changes constantly. The agent updates it **after every completed segment** —
> see `RULES.md`. Read this first at the start of any session.

> **Last updated:** 2026-06-10  ·  **Current phase:** Phase 1a — Voice MVP ✅ (built; ready for live-mic review)

---

## 1. One-line status
**Voice MVP (plan.md §1.1) built end to end.** Mic toggle → browser speech →
`utterance` → hardened rules classifier → engine → idea tree *with derivation
edges* → display. All checks green (ruff, mypy strict, 43 backend tests, tsc,
vite build); fast path p95 0.072 ms.

## 2. Current focus
- [x] Phase 0: prove the loop — participant client → WS → Design State Engine →
      SVG render → diff broadcast → both Participant and Display views update.
- [x] Phase 1a: the MVP — voice input (Web Speech API), classifier vocabulary
      (create/branch/modify/focus/prune/connect/colors), tree layout with
      derivation edges, engine event-sourcing fixes + replay.
- [ ] **Review checkpoint** (RULES.md §3): human review **with a real mic on
      localhost Chrome** before Phase 1b/2 (agent cannot exercise a microphone).

## 3. What's done
_(append-only-ish; newest at top)_
- **Fix: StrictMode dev double-mount froze the app.** The connect effect's
  "ran once" guard left mount #2 with a closed socket → UI rendered but dead
  (and the mic looked broken — utterances dropped into a dead socket). Gotcha
  for all future effects: **make them re-runnable, never guard with a ref** —
  StrictMode runs effect → cleanup → effect in dev. Verified with a driven
  headless Chromium (screenshot: dot green, sketch renders, console clean).
- **Phase 1a — the Voice MVP (plan.md §1.1).** Five segments, all checks green:
  - **Voice input** — `frontend/src/speech.ts`: Web Speech API wrapper
    (continuous, interim results, auto-restart after browser silence cutoff,
    feature-detected). Mic toggle + live interim line in ParticipantView; final
    utterances flow into the *existing* `utterance` path — zero protocol change.
    Server STT (Phase 1b) replaces it behind the same wire contract.
  - **Classifier hardened** (`RulesClassifier`, ex-`MockClassifier`): prune
    ("scrap the circle", "get rid of that"), connect ("connect the box to the
    circle"), modify-named ("make the circle bigger" now MODIFYs — it used to
    CREATE a second circle; the definite article is the discriminator), spoken
    colors → `color:<hex>` modifier → spec stroke, negative preference ("not
    the triangle") emits a negative signal.
  - **Engine correctness** — prune is now an *upsert* with `status=pruned`
    (diffs match snapshots; clients fade instead of delete); focus reassignment
    after prune is event-logged and the new focus's view rides the same diff;
    negative `preference_signal` *disaffirms* (lowers score, never focuses —
    two rejections sink a node past the prune floor); first-node event snapshot
    status fixed; `connect` keeps `children_ids` consistent.
  - **Replay made real** — `DesignStateEngine.from_events()` folds the event
    log back into state; test asserts live == replayed (nodes, focus, seq) and
    id-counter resume. Event sourcing is now a tested guarantee, not a claim.
  - **Idea tree is a tree** — depth-column layout, SVG derivation curves
    parent→child, workflow `edge` nodes drawn as dashed connector lines (not
    cards), pruned branches faded (participant) / hidden (display).
  - Shared `apply_modifiers()` moved to `domain/geometry.py` (classifier and
    engine fold the same vocabulary; `radius:N` now actually lands in CREATE
    geometry). Client store takes `diff.focus_node_id` as authoritative
    (stale-focus bug). 43 backend tests (was 34).
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
1. **Live-mic review:** a human runs the MVP on localhost Chrome (and a phone
   if HTTPS/flag is set up), speaks the §1.1 vocabulary, sanity-checks the tree.
2. **Phase 1b — server STT:** client mic capture (Web Audio → 16 kHz PCM over
   WS) → Silero VAD (`VAD`) → faster-whisper (`Transcriber`) → same tail. Wire
   `QUORUM_STT_BACKEND=local`; extend the latency harness with STT/VAD rows.
3. Phase 2 — idea tree polish (smarter sibling layout, label nodes, undo via
   the now-tested event log).

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
| 2026-06-10 | MVP voice = browser Web Speech API (client-side STT), server VAD/whisper deferred to Phase 1b | Real voice today with zero server ML deps and zero protocol change; the browser already does capture+endpointing+STT. Caveat: Chrome/Safari + secure context (localhost or HTTPS) — acceptable for MVP, and 1b removes it |
| 2026-06-10 | Prune = upsert with `status=pruned`, not `removed_ids` | Diffs and snapshots must say the same thing; late joiners saw faded cards while live clients deleted them. `removed_ids` reserved for future hard deletes |
| 2026-06-10 | Negative preference signal *disaffirms* (engine lowers score; never focuses) | "not the triangle" used to FOCUS the triangle with a bump — the exact opposite of intent. Two −0.6 rejections now sink a node past the −0.8 prune floor |
| 2026-06-10 | "the \<shape\>" (definite article) = reference to an existing node; "a \<shape\>" = create | Cheap, deterministic discriminator that fixed "make the circle bigger" creating a second circle. LLM stage will handle the long tail |
| 2026-06-10 | Modifier vocabulary (`fillet`, `radius:N`, `bigger`, `color:<hex>`…) folds in `domain/geometry.apply_modifiers` | Classifier and engine were drifting toward two interpretations of the same words; one domain function, used by both, behind no stage's internals |
| 2026-06-10 | Replay is a tested API (`DesignStateEngine.from_events`) | Event sourcing buys nothing if the fold is never exercised; also forced the missing FOCUS_CHANGED event on prune-reassignment into the log |

## 6. Open questions
- Preference-signal strength taxonomy ("maybe" vs "let's go with"). _Mostly
  settled:_ phrase-strength table in `classify.py` (+ negative phrases now
  *disaffirm* in the engine rather than focus). Refine weights with real
  sessions.
- Browser speech recognizer quality on design vocabulary ("fillet" especially)
  — evaluate at the live-mic review; if it mangles jargon badly, Phase 1b
  (whisper + keyterm biasing) moves up the queue.
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
_Phase 1a measured via `pytest -m latency` harness (200 iters, MacBook, expanded
corpus incl. colors/prune/modify-named — browser does STT client-side in 1a)._
| Stage | Target | Measured (p50 / p95) | Notes |
|---|---|---|---|
| Endpointing + STT (browser) | <1.5 s | — (client-side) | Web Speech API; not server-measurable — judge at live-mic review |
| STT (server, 1b) | <1 s | — | Phase 1b (faster-whisper) |
| Classify (fast) | <0.2 s | **0.02 ms / 0.03 ms** | rules stage incl. new prune/connect/color/named-modify paths |
| Classify (LLM) | <1.5 s local | — | Phase 4 |
| Render | <0.5 s | **~0.00 ms / 0.01 ms** | deterministic + LRU-cached (cache hits sub-µs) |
| Engine apply | (internal) | **0.03 ms / 0.04 ms** | DAG mutation + event append (incl. new focus/diff bookkeeping) |
| **End-to-end (server fast path)** | **<5 s** | **0.053 ms / 0.072 ms** | classify+engine+render; the budget is effectively all browser-STT/LLM headroom |

> Read-back: the server-side fast path stayed ~4 orders of magnitude under the
> 5 s budget after the classifier/engine work (no regression — actually faster
> than the Phase 0 numbers). In 1a the real human-perceived latency is the
> browser's own speech recognizer (typically 0.5–1.5 s after end of speech),
> which only a live-mic session can measure — first item in the queue.

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
# Voice (MVP path): tap the mic. Needs Chrome/Safari AND a secure context —
#   localhost just works; a phone on the LAN IP needs HTTPS (or Chrome's
#   "unsafely-treat-insecure-origin-as-secure" flag). Text box is the fallback.

# --- checks (per RULES.md §3) ---
cd backend && uv run ruff check . && uv run mypy quorum tests \
  && uv run pytest -q && uv run pytest -m latency -s
cd frontend && npm run typecheck && npm run build

# --- 12-factor env (backend/.env.example) ---
# QUORUM_STT_BACKEND=mock|local|groq   QUORUM_LLM_BACKEND=mock|local|groq
# QUORUM_VAD_BACKEND=mock|local        QUORUM_VAD_SILENCE_MS=300  (latency knob)
# QUORUM_GROQ_API_KEY=...              QUORUM_WHISPER_MODEL=small
```

## 10. Phase 1b entry notes (for next session)
- Voice already works end to end via the browser (1a); 1b adds the *server*
  audio path for privacy/offline: mic PCM (`AudioMessage`, already in the wire
  protocol, currently a no-op) → Silero VAD → faster-whisper, feeding the same
  `_on_utterance` tail. No tail changes, no client protocol changes.
- New impls go behind `pipeline/interfaces.py` (`VAD`, `Transcriber`); select via
  `QUORUM_VAD_BACKEND` / `QUORUM_STT_BACKEND` (`uv sync --extra local`). Add
  their `stage_timer(...)` calls so the ledger fills the empty rows automatically.
- The classifier is shared by both paths — no work needed there.
- Undo is now cheap if wanted: `DesignStateEngine.from_events(events[:-k])`.
