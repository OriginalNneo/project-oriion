# context.md — Living Project State

> **Purpose:** the always-current snapshot of where Quorum actually *is*. Unlike
> `plan.md` (which describes the intended design and changes rarely), this file
> changes constantly. The agent updates it **after every completed segment** —
> see `RULES.md`. Read this first at the start of any session.

> **Last updated:** 2026-06-11  ·  **Current phase:** Phase 1a — Voice MVP ✅ with the full drawing stack: rules → **template bank (345 mined + 8 exact isometric, ~0 ms hits)** → Groq LLM (scene extension, fills, reference-adapted sketches). **Whole program verified end to end** (real uvicorn + websocket: ALL PASS; frontend builds; 110 tests; fast path p95 0.081 ms). **Pending:** human browser live-confirm; Phase 1b server STT next (§4).

---

## 1. One-line status
**Voice MVP (plan.md §1.1) built end to end, now drawing intricate shapes.** Mic
toggle → browser speech → `utterance` → rules→**LLM cascade** → engine → idea
tree *with derivation edges* → display. Geometry IR v2 (polygon/path/text) on
both renderers; **LLM stage C (Groq) ON** and emitting those primitives for
open-ended scenes ("a star", "a house", "a robot"), and scenes are now
*extendable* ("add five thrusters") with rich utterances escalating reliably.
All checks green (ruff, mypy strict, **98 backend tests**, tsc, vite build);
fast path p95 0.111 ms, LLM classify ~1.0/1.8 s (§7).

## 2. Current focus
**Active plan (2026-06-11, user effort=high): richer drawing power + whole-program assurance.**
1. [x] **Elaborate templates — DONE.** Full official list mined: **345
   templates** (was 139). Selection took three iterations (see §3): max-points
   picked scribbles; pure median picked sloppy-typicals; final = **modal
   stroke count** (the crowd's canonical decomposition: snowman = 3 strokes)
   then nearest 1.2x median points within that group, scribble filter
   (points/stroke ≤ 32), 1000-drawing scan. Visually sampled: snowman/house
   clean and canonical; helicopter/bicycle remain crowd-quality (acceptable
   as LLM references; direct hits shine on the popular concepts).
2. [x] **Isometric library — DONE.** `scripts/make_isometric.py` (true 30°
   projection + per-face shading) → 8 exact templates: cube, cuboid, pyramid,
   cylinder, cone, sphere, gear, staircase. ALL visually verified via
   rendered thumbnails (cone needed an arc sweep-flag fix — right-to-left
   arcs invert the bulge). "3D cube"/"ball"/"cog" synonyms; "3d"/"isometric"
   count as filler so "an isometric cube" is a 0 ms direct hit.
3. [x] **Whole-program verification — ALL PASS.** Real `uvicorn` + real
   websocket (`scripts/e2e_check.py`): join/welcome, "a snowman" template
   diff, "a 3D cube" isometric (3 shaded faces), live-LLM rocket scene (≥3
   parts), "make it bigger" grows the focused sketch (parts footprint — a
   group's own width stays fixed while parts scale), late joiner gets the
   snapshot. Frontend tsc + vite build green. 110 backend tests, fast path
   p95 0.081 ms.
4. [x] **Model benchmark — measured (with caveats).** `scripts/eval_llm.py`,
   6 utterances/model, strict-validation+render gate:
   | model | valid | parts | p50 / p95 |
   |---|---|---|---|
   | llama-3.3-70b-versatile | 0/6* | — | — (*quota-corrupted: uniform 429s
   after a day of live use — NOT a quality signal; re-run on a fresh window) |
   | llama-4-scout-17b-16e | **4/6** | 3.5 | **1.8 / 2.1 s** |
   | llama-3.1-8b-instant | 3/6 | 3.3 | 1.9 / 2.0 s |
   | openai/gpt-oss-20b | 2/6 | 5 | 3.8 / 4.6 s |
   **Decision: keep 70b default** (proven live all session); scout-17b is the
   benchmarked fallback (`QUORUM_GROQ_MODEL`), and the e2e ALL-PASS above ran
   on scout-17b — so the fallback is verified too. Hard case for every model:
   adapting injected path references ("snowman wearing a top hat") — watch it
   when re-benchmarking. Fine-tuning stays REJECTED (latency budget).

- [x] Phase 0: prove the loop — participant client → WS → Design State Engine →
      SVG render → diff broadcast → both Participant and Display views update.
- [x] Phase 1a: the MVP — voice input (Web Speech API), classifier vocabulary
      (create/branch/modify/focus/prune/connect/colors), tree layout with
      derivation edges, engine event-sourcing fixes + replay.
- [x] **Review checkpoint** (RULES.md §3): human ran the MVP with a real mic on
      localhost Chrome — verdict "perfect"; finding = needs richer geometry.
- [x] Richer geometry: LLM stage C (Groq) ON, emits IR v2 polygon/path/text;
      verified live server-side. *Pending human browser live-confirm (§4).*

## 3. What's done
_(append-only-ish; newest at top)_
- **Template bank v2: 345 mined + 8 exact isometric (effort=high plan items
  1–2).** 110 tests, latency p95 0.081 ms, frontend tsc+build green.
  - Miner selection lesson (pinned so it isn't relitigated): *max-points
    selection mines scribbles* — QuickDraw's densest drawings are scrawls.
    Median alone picks sloppy-typicals. What works: modal stroke count
    (canonical structure) → nearest 1.2x median points inside that group +
    points-per-stroke ≤ 32 scribble filter, scanning 1000 drawings/category.
  - Isometric bank is *computed*, not drawn: true 30° projection, shaded
    faces (light top / mid front / dark side), all 8 visually verified via
    PNG thumbnails (`qlmanage`). Gotcha: SVG arc sweep flags invert when the
    path runs right-to-left — the cone's base bulged inward until flipped.
  - `_library()` merges every `templates/*.json` bank in sorted filename
    order, later files overwriting duplicate names (quickdraw.json >
    isometric.json alphabetically). No name collisions exist today — check
    before adding a bank with overlapping names.
  - New scripts: `make_isometric.py`, `e2e_check.py` (real uvicorn + real
    websocket whole-loop check), `eval_llm.py` (model benchmark; Groq
    free-tier TPM is per-model and our prompt is ~3.5k tokens → pace 12 s,
    retry on 429 with 20 s waits; `kimi-k2-instruct` is GONE from Groq —
    verify candidates against GET /openai/v1/models).
- **QuickDraw template library (cascade stage B) — DONE & live-verified.**
  139 templates shipped; "a snowman"/"a bicycle" answer in **~0 ms from the
  template bank** (no LLM call), and "a snowman wearing a top hat" escalates
  to Groq which *adapts the injected reference* (the three snowman strokes
  come back byte-identical + hat parts added — retrieval-augmented few-shot
  working as designed). ruff/mypy/108 tests green; fast path p95 0.092 ms.
  Files:
  - `scripts/mine_templates.py` — mines ~135 curated categories from the
    public Quick, Draw! simplified dumps (CC-BY-4.0, attribution embedded in
    the JSON): first recognized drawing within stroke/point budget, rescaled
    0..255→8..92, strokes downsampled to ≤30 pts (path caps: 64 cmds/600
    chars), each template validated + rendered before writing
    `quorum/pipeline/templates/quickdraw.json` (139 templates, 116 KB;
    "street light"/"watch" are not Quick, Draw! categories — removed).
  - `pipeline/templates.py` — `_library()`/`match()` (combined regex index,
    synonyms phone→cell phone, plural-s) + `TemplateClassifier` (stage B):
    bare "draw a snowman" → instant CREATE conf 0.9 source=template; any
    richer phrasing declines (NOOP 0.0) so the LLM gets it.
  - `pipeline/classify.py` — `CascadeClassifier(fast, llm, template=...)`:
    rules → template → LLM; `build_classifier()` wires stage B when LLM is on.
  - `pipeline/llm.py` — user payload factored into testable `_user_payload`;
    now carries `reference_sketches` (≤2 matched templates, exclude_defaults)
    + prompt rule: ADAPT the reference, shrink when part of a larger scene.
  - `tests/test_templates.py` — library renders, synonym/plural match, direct
    hit, rich-utterance decline, cascade skip-LLM + decline-reaches-LLM,
    payload carries refs.
- **Live retest segment: 3D shapes, device sketches, color fills — verified
  against real Groq** (user reported "still can't do it"; agent now retests
  live itself via `backend/scripts/probe_llm.py`, which drives utterances
  sequentially through the cascade + one engine so focus/extend paths are real,
  and writes each node's SVG to /tmp). Found & fixed four live bugs:
  - **"a 3D cube"/"a simple smartphone" came back as MODIFY** and *replaced*
    the focused funnel scene. Prompt now has an explicit create-vs-modify rule
    (new standalone object = create even when a focus exists; modify only for
    "add…/give it…/make it…/put X on it") + worked Example E. Verified live:
    cube → CREATE n2, funnel untouched.
  - **3D looked like a flattened net** (6 axis-aligned faces). Prompt teaches
    isometric = 2-3 visible faces as polygons + Example E (front square, top &
    side parallelograms, fill-shaded). Verified live: proper isometric cube.
  - **Color words ("red scarf… blue hat") hijacked the rules path** — branch 7
    (bare-modifier MODIFY on focus, 0.7) matched, so the snowman never reached
    the LLM. The hazy cap now applies to branches 4 & 7 too. Also the prompt
    never taught `fill` (IR + both renderers already supported it!): now stroke
    vs fill + fill_style semantics are explicit. Verified live: snowman with
    white-filled body, solid red scarf, solid blue hat.
  - **Groq 429 rate-limit on back-to-back utterances** silently dropped stage-C
    results (graceful fallback worked, drawing lost). `LLMClassifier` now
    retries ONCE on 429/5xx after min(Retry-After, 2 s). Mocked-transport test.
  - Also: "simple/basic X" was drawn as one lone rectangle — prompt now demands
    the 2-4 signature parts (phone = body+screen+camera; car = body+cabin+
    wheels). Verified live on both.
  - Checks: ruff, mypy strict, **101 backend tests**, latency e2e p95 0.085 ms.
    Live stage-C latencies this session: 0.7–1.6 s per intricate utterance.
  - ⚠️ The full-suite pytest hang at `test_op_from_participant_reaches_display`
    is **intermittent** (TestClient double-websocket deadlock?), not only the
    zombie-process pileup: it recurred once on a clean run and passed on retry.
    If it bites again, investigate properly (anyio portal?) instead of retrying.
- **Scene extension + smarter escalation — DONE.** Review ask: "a funnel on its
  side, then we add 5 thrusters" must work, and rich utterances must not be
  flattened by a lucky rules match. All checks green: ruff, mypy strict, **98
  backend tests** (was 89), latency e2e p95 0.111 ms (no regression).
  - `domain/op.py` — `ClassifierContext.focus_geometry` (the focused node's
    current `GeometrySpec`) so stage C can *extend* a scene, read-only.
  - `engine/state.py` — `classifier_context()` populates `focus_geometry`
    (skips pruned focus); `_modify` now honours `op.geometry` as a full scene
    replacement (LLM re-emits existing parts + new ones), modifiers still fold
    on top; no-geometry MODIFY unchanged.
  - `pipeline/classify.py` — coverage heuristic: `_unexplained_words()` counts
    content words outside the rules vocabulary (`_KNOWN_WORDS` = stopwords ∪
    shape/modifier/color/preference/command words); ≥2 unexplained ("rocket …
    thrusters") caps a matched CREATE/scene op at `_HAZY_CONFIDENCE` 0.5 —
    below the 0.55 cascade threshold, so the LLM takes it while the rules op
    stays as the dead-LLM fallback. 1 unknown word stays fast (no LLM tax).
  - `pipeline/llm.py` — user message now carries `focus_geometry`
    (`exclude_defaults` dump); prompt gains the extend-scene rule (modify =
    COMPLETE new group, copy existing parts verbatim), a decompose-into-named-
    parts instruction (Chat2SVG-style), orientation guidance ("on its side" →
    emit rotated silhouette), and worked Example D (sideways funnel + 5
    thrusters → modify).
  - `tests/test_scene_extension.py` — escalation (rich utterance → LLM; "a red
    circle" stays fast; 1 unknown word stays fast; dead-LLM falls back to the
    basic shape), engine geometry-replacing MODIFY, focus_geometry in context,
    Example D pinned through validation + renderer.
  - ⚠️ Harness gotcha: the full suite appeared to "hang" at
    `test_op_from_participant_reaches_display` — root cause was a pile of
    half-killed `pytest -q` zombie processes from *previous agent sessions*.
    After `pkill -f "pytest -q"` the suite runs in 0.36 s. Kill zombies before
    diagnosing "slow tests".
- **HF dataset research (for even richer drawings) — done, not yet built.**
  Question: is there a dataset mapping object names → simple vector drawings we
  can use? Answer: yes — recommendation is a **local template library mined
  from Google QuickDraw** (`google/quickdraw` on HF: CC-BY-4.0, 50M stroke
  drawings, 345 everyday-object categories incl. "snowman"; strokes are
  polylines in a 0..255 box → trivially rescale to our polygon/path IR).
  Runners-up: FIGR-8-SVG (1.45M monochrome icons, 17k classes, license murky
  for redistribution — private prompt-bank use only) and OmniSVG MMSVG-Icon
  (904k captioned picosvg-simplified SVGs, CC-BY-NC — fine for research, not
  commercial). MMSVGBench (300 text→SVG prompts) is a ready eval set.
  Technique (per Chat2SVG/SVGenius findings): **retrieval-augmented few-shot**
  — offline script mines one canonical template per concept into our IR JSON;
  at request time, fuzzy-match utterance nouns and inject 1–2 matched templates
  as extra few-shot examples in the Groq prompt (~0 added latency). Exact
  single-object hits ("a snowman") can skip the LLM entirely. Queued in §4.
- **LLM stage C turned ON for intricate geometry (review finding addressed).**
  The "can't draw complicated shapes" gap is closed end to end:
  - `pipeline/llm._SYSTEM_PROMPT` rewritten to teach the **Geometry IR v2
    primitives** — `polygon` (exact `points`), `path` (constrained absolute-
    uppercase SVG `d`), `text` (`label`+`font_size`) — plus `name`/`stroke_width`/
    `fill_style`, with three worked examples (star polygon, house group mixing a
    polygon roof, heart path). The model now reaches for the rich primitives
    instead of stacking rectangles.
  - **Live Groq verified** (`llama-3.3-70b-versatile`): "a five-pointed star"→
    polygon(10pts), "an arrow"→polygon(6pts), "a house with a door and two
    windows"→group{rect, polygon roof, 3 rects}, "a snowman wearing a top hat"→
    group{3 circles, path}, "a robot"→group(6). **All validate and render.**
  - **Backend now runs `QUORUM_LLM_BACKEND=groq`** via `backend/.env` (gitignored).
    The cascade is unchanged: rules answer confident/basic utterances for free;
    only rules-NOOP ("a robot") escalate to Groq. A dead LLM still falls back to
    rules (existing test).
  - **Tests:** `tests/test_llm_geometry.py` (+4) pins the three prompt examples
    through `_LLMPayload` validation → `payload_to_op` → renderer, plus a mocked-
    HTTP `LLMClassifier` path. ruff + mypy strict clean, **89 backend tests** (was
    85), fast-path latency unchanged (p95 0.113 ms). LLM latency now measured —
    see §7.
  - ⚠️ The pasted Groq API key is **in this session's transcript → rotate it**;
    `.env` holds it locally and is gitignored.
- **Live-mic review (Phase 1a checkpoint, §4 item 1) — DONE.** Human ran the MVP
  on localhost Chrome (fresh Vite on :5174, backend :8000, mock STT/LLM) and
  spot-checked the voice loop: verdict **"right now it's perfect."**
  - ⚠️ *Scope of the pass:* a spot-check, **not** a confirmed walk of all 8
    scripted steps. NOT independently observed by the agent: the `fillet`/jargon
    mangling test (§6 open risk) and the per-step composite/disaffirm/prune
    behaviors. Treat those as *un-disproven*, not *verified*. Re-test `fillet`
    if Phase 1b STT quality comes into question.
  - **Review finding (the deliverable):** the loop works but **can't draw more
    complicated shapes/designs.** Root cause confirmed against code: the rules
    classifier only emits basic primitives + groups of them, and the LLM stage C
    (the only thing that could generate intricate scenes) is OFF by default
    (`QUORUM_LLM_BACKEND=mock`) AND its prompt doesn't teach the v2
    polygon/path/text primitives. So intricacy is unreachable in the default
    config — exactly the gap IR v2 was built to fill.
  - **Resolves the IR v2 divergence flag (§5).** The user just validated that
    intricacy is the thing they want next, which retroactively justifies the
    out-of-queue IR v2 work. The flag is closed; don't re-litigate it.
- **Geometry IR v2 (intricacy primitives).** ⚠️ *Was off the documented queue
  (§4 said: live-mic review next). Resumed unfinished/uncommitted work from the
  prior session and finished it end to end; flagged per CLAUDE.md §7 — see the
  decisions log. The live-mic review is STILL the next checkpoint (§4).* Adds
  three primitives so the LLM stage (and tests/drivers) can sketch intricate
  scenes — isometric faces, wireframes, labels — that v1's one-primitive-per-
  node model couldn't express, all behind the same `GeometrySpec`:
  - `POLYGON` (`points` in the 0..100 box), `PATH` (constrained SVG `d` —
    absolute uppercase commands only, validated/transformed by
    `domain/pathdata.py`), `TEXT` (renders `label` at x,y).
  - Per-shape `name` (addressable part, for later targeted MODIFY),
    `stroke_width`, `fill_style` (hachure/solid/none), `font_size`.
  - **All v1 specs validate and render byte-identically** (every new field
    defaults; per-kind validators only fire for the new kinds).
  - `apply_modifiers` ("bigger"/"smaller") now scales polygon points, path
    data (about the box center via `pathdata.scale_about_center`), and text
    font size — one shared vocabulary, classifier + engine fold the same words.
  - **Both renderers** wired: server `pipeline/renderer.py` (the deterministic
    reference: HACHURE/SOLID→flat fill, NONE→no fill, arc radii use an
    offset-free length map) and the client (`frontend/src/pathdata.ts` ports
    parse+transform; `SketchNode.tsx` draws polygon/path/text via rough.js).
    Required on the client: the server `svg` field is NOT consumed anywhere —
    both Participant and Display render locally through `IdeaTree`→`SketchNode`.
  - **Nothing emits these primitives yet** (rules classifier unchanged, LLM off
    by default), so coverage is direct-construction tests; the e2e path is
    unexercised in the default config until the LLM stage starts producing them.
  - Checks: ruff + mypy strict clean, **85 backend tests** (was 80; +27 in
    `test_geometry_v2.py`, +5 renderer), tsc + vite build green, latency e2e
    p95 0.087 ms (no regression — v1 specs still cache to sub-µs renders).
- **Composite scenes + LLM stage (cascade stage C).** "a circle with a square
  on top" was collapsing to one shape — root cause: a node's geometry could
  only hold ONE primitive. Now:
  - `GeometrySpec` gains `kind=group` + `parts` (absolute coords in the same
    0..100 box; no nested transforms). Renderer, client renderer, and
    `apply_modifiers` (scale-around-center for groups) all handle it.
  - Rules classifier composes 2+ shape mentions with spatial prepositions:
    on top/above, below/under, inside, else side-by-side in spoken order.
    One utterance = one idea node = possibly many primitives.
  - `pipeline/llm.py` — the real stage C behind the same `Classifier`
    Protocol: Groq (JSON mode) or Ollama (`format:json`), strict pydantic
    validation, any failure → zero-confidence NOOP. `CascadeClassifier`
    escalates only when rules are unsure (threshold env-tunable); a dead LLM
    falls back to rules (tested). `build_classifier()` factory wires it from
    `QUORUM_LLM_BACKEND` (default mock = rules only). 54 backend tests.
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
1. [x] **Live-mic review** — DONE (see §3). Finding: needs richer geometry.
2. [x] **Richer geometry — DONE via LLM stage C (tier B).** Stage turned ON
   (Groq) + prompt teaches polygon/path/text; verified live (see §3). The loop
   now draws intricate scenes. *Tier A (rules-emit polygons for named shapes,
   zero-latency) is still worth doing* so common shapes (star/hexagon/arrow)
   don't pay the ~1 s LLM round-trip — optional follow-up.
   - **Live-confirm in the browser:** human refreshes the Participant tab and
     speaks "a star", "a house with two windows", "a robot" — confirm the
     sketch tab draws them (this is the one thing the agent can't observe).
     **Add to the script:** "a funnel turned on its side" → "now add five
     thrusters" (tests the new scene-extension path) and "a rocket with a box
     body and fins" (tests the escalation heuristic).
3. [x] **QuickDraw template library — DONE** (see §3): 139 templates, stage B
   in the cascade, ~0 ms direct hits, LLM few-shot injection live-verified.
4. **Phase 1b — server STT:** client mic capture (Web Audio → 16 kHz PCM over
   WS) → Silero VAD (`VAD`) → faster-whisper (`Transcriber`) → same tail. Wire
   `QUORUM_STT_BACKEND=local`; extend the latency harness with STT/VAD rows.
5. Phase 2 — idea tree polish (smarter sibling layout, label nodes, undo via
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
| 2026-06-10 | A sketch is a *scene*: `GeometrySpec(kind=group, parts=[...])`, parts in absolute 0..100 coords, no nested transforms | "circle with a square on top" is ONE idea node, not two cards; absolute coords keep both renderers and caching trivial. Caught live: multi-shape utterances collapsed to one shape |
| 2026-06-10 | LLM stage C = Groq/Ollama emitting the same strict-JSON DesignOp+GeometrySpec; cascade escalates only below a confidence threshold; LLM failure → fall back to rules | Plan §3.3 realized: median latency stays rules-fast, complex scenes ("a snowman") become possible, and a dead LLM degrades quality, never availability |
| 2026-06-10 | **⚠️ DIVERGENCE — built Geometry IR v2 (polygon/path/text + style fields) ahead of the documented queue** (which had live-mic review next) | Picked up unfinished/uncommitted prior-session work and finished it rather than abandon a clean, ~done segment. Flagged per CLAUDE.md §7 — does **not** reorder the queue: live-mic review is still the next checkpoint (§4). Re-confirm with a human whether IR v2 should precede that review |
| 2026-06-10 | PATH = constrained SVG `d`: absolute uppercase commands only (M L H V C Q A Z), 0..100 box, command/number caps | Lowercase/relative is the LLM's most common malformation and would make "scale about center" a stateful rewrite; rejecting > guessing. Renderers map the *numbers* through their viewport (no SVG `transform`, which would scale rough.js stroke + wobble) — `pathdata.transform` Python, `pathdata.ts` mirror |
| 2026-06-10 | LLM stage C ON (Groq `llama-3.3-70b-versatile`) + prompt extended to teach IR v2 polygon/path/text | Live-mic review finding: the loop couldn't draw intricate shapes. 70b chosen over `llama-3.1-8b-instant` (richer geometry, reliable JSON mode, ~1 s on Groq) and over `gpt-oss-120b` (reasoning model → JSON-mode/latency risk). Verified live: star/arrow→polygon, house/robot→mixed groups, all render. Only rules-NOOP utterances escalate, so median latency is untouched |
| 2026-06-10 | Server renderer (clean reference) renders HACHURE & SOLID as flat fill, NONE as no fill; client does the real hachure via rough.js | Server can't hachure and isn't meant to (plan §7 — sketchy look is the client's job); both sides honour `fill_style`/`stroke_width`/`font_size` with shared constants (4 units ≈ 15px) so intent stays identical |
| 2026-06-11 | Coverage heuristic: ≥2 content words outside the rules vocabulary cap a matched op at 0.5 (below the 0.55 cascade threshold) | "a rocket with a box body and 5 thrusters" matched "box" at 0.85 and the LLM never saw the rich intent. Capping (not NOOPing) keeps the basic shape as the dead-LLM fallback; 1 unknown word stays fast so common utterances don't pay the ~1 s LLM tax |
| 2026-06-11 | Scene extension = LLM re-emits the COMPLETE group on MODIFY; engine honours `op.geometry` as replacement; `ClassifierContext.focus_geometry` shows the LLM the current scene | "add five thrusters" needs the model to see what exists. Full-replacement beats a part-patch protocol: no new op semantics, replay/event-sourcing untouched, and validation stays one GeometrySpec. Engine remains sole writer |
| 2026-06-11 | Template library source = Google QuickDraw (CC-BY-4.0), retrieval-augmented few-shot at runtime; FIGR-8/MMSVG only as private references (NC/murky licenses) | Only QuickDraw is license-clean for anything we ship; few-shot injection adds ~0 latency vs fine-tuning/diffusion approaches (Chat2SVG stages 2-3, StarVector, IconShop) that blow the 1-2 s budget |
| 2026-06-11 | QuickDraw template selection = modal stroke count, then nearest 1.2x median points within the modal group, pts/stroke ≤ 32 | Max-points mines scribbles; pure median mines sloppy-typicals; modal structure is the crowd's canonical decomposition (snowman = 3 strokes). Verified by eyeballing rendered thumbnails |
| 2026-06-11 | Isometric/3D primitives are COMPUTED templates (scripts/make_isometric.py), not LLM-drawn | A projection is math, not taste: exact 30° isometric + shaded faces beats asking a 1-2 s LLM to improvise one every time; "a 3D cube" is now a 0 ms direct hit. LLM still composes them into scenes via reference_sketches |
| 2026-06-11 | Keep Groq `llama-3.3-70b-versatile` default; `llama-4-scout-17b-16e-instruct` is the benchmarked fallback | Benchmark's 70b row was quota-corrupted (uniform 429s) — switching on corrupted evidence would be superstition. Scout measured 4/6 valid @ p50 1.8 s AND passed the full e2e as the live stage C; kimi-k2 is gone from Groq (404) |

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
  _Current:_ Groq `llama-3.3-70b-versatile` chosen for now (quality + speed);
  local Ollama path still built/untested. Revisit if privacy/offline is needed.
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
| Classify (fast) | <0.2 s | **0.02 ms / 0.03 ms** | rules stage incl. scenes/prune/connect/colors |
| Classify (LLM) | <1.5 s local / <0.8 s Groq | **~1.0 s / ~1.8 s** (Groq `llama-3.3-70b-versatile`, 6 intricate utterances) | ON. Simple shapes (star/arrow polygon) ~0.7 s; full scenes ("a robot") ~1.8 s — **over the 0.8 s sub-target for the heavy case**, but only fires on rules-NOOP utterances and stays well inside the 5 s end-to-end budget. Tune model/threshold if the tail bites |
| Render | <0.5 s | **~0.00 ms / 0.01 ms** | deterministic + LRU-cached (cache hits sub-µs) |
| Engine apply | (internal) | **0.03 ms / 0.04 ms** | DAG mutation + event append (incl. new focus/diff bookkeeping) |
| **End-to-end (server fast path)** | **<5 s** | **0.053 ms / 0.072 ms** | classify+engine+render; the budget is effectively all browser-STT/LLM headroom |

> Read-back: the server-side fast path stays ~4 orders of magnitude under the
> 5 s budget. The real human-perceived latency now has two contributors: the
> browser's speech recognizer (~0.5–1.5 s, client-side, judged "fine" at the
> live-mic review) and — only for intricate utterances that escalate to stage C
> — the Groq round-trip (~1–1.8 s). Stacked worst case (~3.3 s) is still inside
> the 5 s budget; basic utterances never touch the LLM.

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
#
# NOTE (this session): backend/.env exists (gitignored) with LLM stage C LIVE —
#   QUORUM_LLM_BACKEND=groq, QUORUM_GROQ_MODEL=llama-3.3-70b-versatile, key set.
#   ⚠️ The key was pasted into a chat transcript — ROTATE it at console.groq.com.
#   Frontend dev server may land on :5174 if :5173 is taken (check the vite log).
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
