# Quorum — How It Works

> A walkthrough of the running system: the two displays, every button and gesture,
> what you can say, and how an utterance becomes a sketch on screen.
> Written 2026-06-14 against the live code (branch `drawing-quality-d3`).

---

## 1. What Quorum is

Quorum is a **real-time, voice-driven collaborative sketching tool for group alignment.**
People in a room talk; the system turns each spoken idea into a rough sketch on a shared
canvas, and every iteration becomes a new node in a **mind map** so the group can see how an
idea evolved and decide together. The conversation *is* the input device — you mostly talk,
and the drawings keep up.

The aesthetic is deliberately **hand-drawn / low-fi** (via rough.js): sketchy output says
"draft — keep iterating", which serves the alignment goal rather than implying a finished design.

---

## 2. Running it & the URLs

Two dev servers are hosted locally:

| Server | Port | What it is |
|---|---|---|
| Backend (FastAPI / uvicorn) | `8000` | the realtime gateway + pipeline |
| Frontend (Vite / React) | `5173` | the two web UIs |

**Open these (this machine):**
- **Participant** (you draw here): http://localhost:5173/?room=demo&name=alice
- **Display** (the shared screen): http://localhost:5173/display?room=demo

**On a phone / another device on the same Wi-Fi** (LAN IP `192.168.0.117`):
- Participant: `http://192.168.0.117:5173/?room=demo&name=alice`
- Display: `http://192.168.0.117:5173/display?room=demo`

The **role is chosen by the URL**: `/` → Participant, `/display` → Display.
Query params: `?room=<name>` (which board you join, default `demo`) and `?name=<handle>`
(your speaker id; a random animal handle is assigned if omitted). Everyone on the same
`room` shares one live board.

Start commands (if not already running):
```bash
# backend
cd backend && uv run uvicorn quorum.app:app --host 0.0.0.0 --port 8000
# frontend
cd frontend && npm run dev          # Vite on 0.0.0.0:5173, proxies /ws -> :8000
```

---

## 3. The two displays

Quorum ships **one codebase, two roles** (RULES.md §4) — they differ only by URL.

### 3a. Participant view (`/`) — the phone screen
This is where you **control** the session. Top to bottom:
- a **top bar** — the Quorum brand, a connection dot, your handle (`you: alice`), and a live
  status word (`listening…` / `sketching…`);
- a **controls block** (voice, text, undo, optional manual shapes);
- the **shared idea-tree canvas** (the mind map — same component the Display shows);
- a **"What the system heard" drawer** — the last 6 transcribed utterances, for transparency
  and trust (you can always see what it thought you said).

### 3b. Display view (`/display`) — the HDMI / shared screen
**View-only, calm, big.** No controls — it just reflects the broadcast state for the room:
- a **header** — brand + `room · demo` + connection dot;
- a **full-bleed canvas** with larger cards (240 px vs 190 px), auto-fitted;
- a **footer** — either the live activity (`alice sketching…`) or a tally (`5 ideas on the board`).
- Pruned (rejected) branches are **hidden** on the Display but shown faded to Participants.

Both views render from the *same* broadcast diff over the *same* WebSocket — the client holds
no authoritative state, only a view of it (RULES.md §4).

---

## 4. Buttons, controls & gestures (hosted and working)

### 4a. Participant controls

| Control | What it does |
|---|---|
| **🎤 Speak** (mic toggle) | Starts/stops browser speech recognition. While on it reads `● listening — tap to stop` and shows interim text as you talk. Each finished phrase is sent as an `utterance`. Disabled (with a reason tooltip) if the browser can't do speech. |
| **Text input + Send** | The no-mic fallback / correction path. Type `a red circle`, `make it bigger`, `go with the triangle`… and press Enter or **Send**. Runs the *exact same* pipeline as voice. |
| **↩ Undo** | Sends the utterance `undo` → the engine moves focus back to the parent node (step back through the mind map). History stays visible. |
| **manual shape buttons** (collapsible) | A fallback manual loop: a **fillet / rounded** checkbox + a grid of Rectangle / Circle / Triangle / Ellipse, each with a **create** button and a **branch** button (branch is enabled only when a node is focused). These bypass the classifier and emit shapes directly. |
| **"What the system heard" drawer** | Collapsible transcript of the last 6 utterances (speaker + text). |
| connection dot | green = connected to the gateway, red = disconnected. |

### 4b. Canvas HUD (bottom-right of the mind map — both views render the canvas; controls live here)

| Button | Action |
|---|---|
| **−** | Zoom out (about the canvas center) |
| **42%** (readout) | Current zoom level |
| **+** | Zoom in |
| **Fit** | Frame all cards into view |
| **⊙** | Re-center on the focused card |
| **Follow ● / ○** | Toggle: when ON, the canvas auto-centers the focused card as it changes; when OFF, the view stays put. |

### 4c. Canvas gestures (pan/zoom, hand-rolled, zero-dependency)

| Gesture | Effect |
|---|---|
| **Ctrl/⌘ + scroll**, or **two-finger pinch** | Zoom about the cursor |
| **Plain scroll / two-finger drag** | Pan |
| **Click-drag on empty canvas** | Pan |
| (zoom clamps to **0.2×–2.5×**) | |

The view auto-fits new boards and pauses following while you're actively gesturing.

---

## 5. What you can say (the command vocabulary)

You speak or type natural phrases. A 3-stage cascade decides what each means (see §6).
Many common things are **deterministic and instant** (no AI round-trip); richer/novel things
go to the LLM.

| You say… | What happens | Path |
|---|---|---|
| "a circle", "a red rectangle", "a rectangle with a fillet" | Creates a basic shape (with color/rounding folded in) | rules (instant) |
| "a rhombus", "a hexagon", "a star", "an arrow", "a heart", … | Creates one of **18 exact named shapes** (math, not guesswork) | rules (instant) |
| "a snowman", "a cat", "a cuboid", "an isometric cube" | Pulls a **template** (345 mined QuickDraw doodles + 8 computed isometric solids) | template (~0 ms) |
| "make it bigger / smaller", "turn it pink", "make the cube red" | Modifies the focused idea (size folds in; **recolor preserves shading**) — and creates a **new child node** so history is kept | rules (instant) |
| "make this hexagon 3D" | Deterministic **2D→3D extrusion** of the focused shape | rules (instant) |
| "a 3D engine with pistons", "a cylinder", "a wedge ramp" | The model emits axis-aligned **solids**; code does the exact **isometric projection + shading** | LLM → code |
| "add two eyes", "make one eye bigger" | **Part-level edits** against named parts (add/set/remove) | LLM patch / rules |
| "a box above the horse" | **Composes** the new shape onto an existing node as a child | rules (instant) |
| "shade it into a tabby with stripes" | Open-ended restyle of the same geometry | LLM |
| "go with the triangle", "let's use the circle", "not the triangle" | **Preference** — raises/lowers a node's affirmation score (drives focus; strong negatives prune) | rules (instant) |
| "remove the square" | Prunes a node | rules (instant) |
| "connect the circle and the box" | Draws a labeled connector between two nodes | rules (instant) |
| "undo", "go back", "never mind", "scratch that", "zoom back out" | Steps focus back to the parent | rules (instant) |

Anything the rules/templates can't confidently handle escalates to the LLM (stage C).

---

## 6. How it works under the hood (the pipeline)

```
  voice (browser Web Speech)  ─┐
  or typed text               ─┴─►  utterance  ──WebSocket──►  Gateway (per-room)
                                                                    │
                                                  ┌─────────────────┴───────────────────┐
                                                  │  Classifier CASCADE                  │
                                                  │   A. rules     (vocabulary, instant) │
                                                  │   B. templates (QuickDraw/isometric) │
                                                  │   C. LLM        (OpenRouter, novel)  │
                                                  └─────────────────┬───────────────────┘
                                                                    │ DesignOp
                                                          Design State Engine
                                                       (sole writer · event-sourced ·
                                                        "iteration = new child node")
                                                                    │ StateDiff
                                              broadcast over the single WebSocket
                                                          │                 │
                                                  Participant view     Display view
                                                  (rough.js render)    (rough.js render)
```

Key design ideas (all live):
- **Cascade, not one big model.** Most utterances never touch the LLM, so the common path is
  sub-millisecond. Only novel/intricate phrasing escalates (keeps latency low and the system
  usable even when the LLM is rate-limited or down).
- **"Model proposes, code disposes."** Wherever math beats taste — recolor, isometric
  projection, tangency, containment, 2D→3D extrusion, spatial composition — the LLM only
  supplies rough intent and **deterministic code computes the exact geometry.** This is why
  3D, color, and placement are reliable.
- **The engine is the only writer of state** (event-sourced, replayable). Everything else
  produces a `DesignOp`; the engine applies it and broadcasts a diff.
- **Iteration-as-branch.** A change to an idea doesn't overwrite it — it creates a **child
  node** and moves focus there, so the canvas grows outward as a mind map and nothing is lost.
- **One WebSocket, server is the source of truth.** No side-channel fetches; late joiners get
  a full snapshot on connect, so opening a second tab is instantly in sync.

### Mind-map canvas details
- **Radial layout**: the origin idea sits at the center; each iteration is a child one ring
  outward (uniform ring spacing, so a chain reads as evenly-spaced beads).
- **Cards** show the rough sketch + an optional **concept label** chip, a **focus outline** on
  the active card, a **"sketching…" badge** while the pipeline is working, **affirmation chips**
  (★ for favored, ▽ for disfavored, "suggested by <name>"), and **fade** when pruned.
- **Edges**: gray curved lines show derivation (parent→child); blue dashed lines show explicit
  `connect` relations with an optional label.

---

## 7. Backend surface (what's hosted)

| Endpoint | Method | Purpose |
|---|---|---|
| `/ws` | WebSocket | The single realtime channel. First frame must be a `join` (room + role + speaker id); then `utterance` / `demo_op` / `correction` messages flow in, `welcome` / `snapshot` / `diff` / `transcript` / `status` flow out. |
| `/healthz` | GET | Status + active backends, e.g. `{"status":"ok","backends":{"stt":"mock","llm":"openrouter","vad":"mock"}}` |
| `/metrics/latency` | GET | Live per-stage p50/p95 latency ledger |

Rooms are independent; each has its own state engine and classifier. CORS is open in dev so
phones on the LAN can connect.

---

## 8. What's instant vs what's slow (set expectations)

- **Instant (deterministic, no AI):** basic + named shapes, templates, recolor, resize,
  2D→3D extrude, compose/placement, preferences, prune, connect, undo. Server fast-path is
  **~0.13 ms p95** (the human-perceived delay here is just the browser's speech recognizer).
- **Slower (LLM stage C):** novel scenes, open-ended restyle, true-3D solids, multi-shape
  composition. **Currently routed to OpenRouter on the cheapest model** (`inclusionai/ling-2.6-flash`)
  because the previous Groq key was rate-limited. The cheap tier is **5–70 s** and occasionally
  rate-limits — so a slow "draw a horse" is the model tier, not a bug. (A fast escalation tier
  is the next planned step — see `context.md` §4 / `plan.md` §11 "D4 part 2".)

---

## 9. Current configuration (live right now)

| Stage | Backend | Notes |
|---|---|---|
| Speech-to-text | **mock** (server) | The browser's Web Speech API does STT client-side in this phase. Needs Chrome/Safari + a secure context (`localhost` works; a phone on the raw LAN IP needs HTTPS or the text box). |
| LLM (stage C) | **openrouter** | OpenAI-compatible; model `inclusionai/ling-2.6-flash`. Swappable via `QUORUM_OPENROUTER_MODEL`. |
| VAD | **mock** | Server-side voice-activity detection is Phase 1b (not yet built). |

What's built and verified: the full voice→sketch loop; compositional iteration (§12),
part-level editing + in-chain 3D (§13), voice undo + viewport follow (§14), the zoom/pan/
adaptive canvas + compose-onto-existing (§15), deterministic isometric projection (D3), and the
instruction-adherence eval harness + model benchmark (D4 part 1). 568 backend tests pass.

---

## 10. Directory map

Repository root: **`/Users/nathanielneo/Project Oriion`**

```
Project Oriion/
├── CLAUDE.md            # how the coding agent works (operating instructions)
├── plan.md              # the intended design (changes rarely)
├── context.md           # living project state — what's actually built, decisions, latency ledger
├── RULES.md             # the non-negotiable build contract
├── HOW_IT_WORKS.md      # ← this file
│
├── backend/             # Python 3.12 (uv), the gateway + pipeline
│   ├── .env             # local config (gitignored): active backends + API keys
│   └── quorum/
│       ├── app.py           # FastAPI app: /ws, /healthz, /metrics/latency
│       ├── config/          # 12-factor settings (Backend enum, env-driven)
│       ├── domain/          # pure data + logic: geometry, shapes, color, isometric,
│       │                    #   extrude, compose, parts, events, op, tree, pathdata
│       ├── engine/          # Design State Engine (sole writer, event-sourced, replay)
│       ├── pipeline/        # the cascade: classify (rules), templates, llm (stage C),
│       │                    #   relations, renderer, intent, interfaces
│       ├── eval/            # adherence.py — the D4 instruction-adherence scorer (no-VLM)
│       ├── gateway/         # WebSocket connection, rooms, message handler
│       └── observability/   # structured logging + the latency ledger
│   ├── scripts/         # eval_llm, eval_adherence, probe_llm, e2e_check, make_isometric, …
│   └── tests/           # 568 tests (unit + integration + latency harness)
│
└── frontend/            # React + Vite + rough.js (the two web UIs)
    └── src/
        ├── main.tsx          # entry
        ├── App.tsx           # role routing (/ = Participant, /display = Display) + socket
        ├── ParticipantView.tsx  # mic, text+Send, Undo, manual shapes, transcript drawer
        ├── DisplayView.tsx      # view-only big screen
        ├── IdeaTree.tsx         # the radial mind-map canvas + edges + cards
        ├── SketchNode.tsx       # rough.js hand-drawn rendering of one geometry spec
        ├── ZoomControls.tsx     # the −/%/+/Fit/⊙/Follow HUD
        ├── usePanZoom.ts        # pan/zoom gestures (pointer/wheel/pinch)
        ├── speech.ts            # browser Web Speech API wrapper
        ├── store.ts             # client state (applies server diffs)
        ├── ws.ts                # WebSocket client
        ├── protocol.ts          # the wire contract (mirrors backend messages)
        └── pathdata.ts          # constrained SVG path transform (mirrors backend)
```
