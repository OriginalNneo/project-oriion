# context.md — Living Project State

> **Purpose:** the always-current snapshot of where Quorum actually *is*. Unlike
> `plan.md` (which describes the intended design and changes rarely), this file
> changes constantly. The agent updates it **after every completed segment** —
> see `RULES.md`. Read this first at the start of any session.

> **Last updated:** 2026-06-13  ·  **Current phase:** Phase 1a — Voice MVP ✅ with the full drawing stack: rules (**named-geometry tier · part-scoped edits · deterministic extrusion · voice undo · compose-onto-existing**) → **template bank (345 mined + 8 exact isometric, named parts, ~0 ms hits)** → Groq LLM (**set/add/remove PATCH contract**, scene extension, restyle, exact-relation snapping, clamp/salvage/retry repair). **§12 mind-map iteration, §13 part editing + in-chain 3D, §14 voice undo + viewport follow, §15 canvas zoom/pan/adaptive + compose-onto-existing, AND D3 deterministic isometric projection — DONE, e2e ALL PASS.** Checks green: ruff, mypy, **568 backend tests** (+87 D4: adherence+openrouter), latency p95 0.129 ms (unchanged). **D4 part 1 — instruction-adherence eval harness + OpenRouter backend + cheap-tier benchmark — DONE; D3 live-probe DONE (model emits `solids`, projection lands).** Next: D4 part 2 (escalation tier + streamed fast tier); still-pending human browser confirm of §15 + merges to main (plan.md §11).

---

## 1. One-line status
**Voice MVP + compositional iteration (§12) + part-level editing & in-chain
3D conversion (§13) + voice undo (§14) + canvas zoom/pan/adaptive + compose-onto-existing (§15) + deterministic isometric projection (D3) shipped.**
Every modify branches a new mind-map child; recolors/restyles/extrusions/part edits are
deterministic where they can be ("a hexagon" → "turn this hexagon pink" →
"make this hexagon three dimensional" runs entirely rules-stage at 0 ms,
ending in a cabinet-extruded prism in three pink shades); the LLM edits
scenes via a compact set/add/remove PATCH against named parts ("add two eyes
to this mouse" = 1.2 s, originals byte-identical); "a box above the horse"
composes onto the horse node as a child (conf 0.8, rules, deterministic
placement). The canvas is now full-bleed with zoom/pan/Fit controls (0.2–2.5×),
a Follow toggle, and a uniform ring-step radial layout (bug: depth-compounding
was making each successive edge longer). All checks green (ruff, mypy, **436
backend tests**, tsc, vite build 193 kB); fast path p95 sub-ms; pending human
browser confirm of §15 on branch ui-zoom-adaptive-canvas.

## 2. Current focus
**Detection-accuracy + speed enhancements — DONE & live-verified (2026-06-14,
branch drawing-quality-d3, committed 63e917c).** User feedback: "it's doing
nicely; enhance detection (new shapes sometimes focus the OLD shape; placement
~20% accurate → want ~85%), speed, and UX (defer UX)." Fixed: (1) every CREATE
now takes focus (was: only the first ever) — the "edits the old shape" bug; (2)
deterministic directional placement snapping (above/below/left/right/beside) —
was raw model guesswork; (3) compose target resolves definite-only so a new
shape can't hijack an old node; (4) default model → `google/gemini-2.5-flash-lite`
(~2 s AND strong on color/placement/3D — bake-off winner). All live-verified.
570 tests, fast path p95 0.119 ms. Full record in §3 (top).

**Next:** (a) **vector DB** — semantic reference retrieval + utterance→geometry
cache (the user's idea; design in §4, propose-before-build since it adds a dep); (b) still pending (human-only): the **§15 browser confirm + merges
to main**; (c) D4 part 2 (escalation tier) is now largely moot for latency since
gemini-2.5-flash-lite is ~2 s — keep it only as a quality-escalation option.
UX/UI polish DEFERRED by the user.

**Prior — D4 part 1 — instruction-adherence eval + OpenRouter backend + cheap-tier
benchmark — DONE (2026-06-13).** Pure no-vision scorer
(`quorum/eval/adherence.py`) grades count/color/coherence/relations/solids3d; a
runner (`scripts/eval_adherence.py`) with a keyless `--self-test` benchmarks
models. Closed the owed D3 live probe. Benchmark + 5 adversarial-review fixes in
§3.

**Prior — D3 — deterministic isometric projection — DONE & eyeball-verified
(2026-06-13).** Branch: drawing-quality-d3 (off ui-zoom-adaptive-canvas, so it
carries §15). LLM emits axis-aligned 3D `solids`; pure `domain/isometric.py`
projects them to a flat isometric GROUP (model proposes, code disposes). 482
tests, ruff+mypy clean, latency p95 0.132 ms (no regression). Built by one
Sonnet subagent (the projection module) + main-thread LLM/prompt wiring, then a
3-lens adversarial-review workflow (2 HIGH + 3 MED real bugs fixed & pinned).
Eyeball gate ✓ (cube/engine/wedge/cylinder/stack). Full details + the

**Prior — D3 — deterministic isometric projection — DONE & eyeball-verified
(2026-06-13).** Branch: drawing-quality-d3 (off ui-zoom-adaptive-canvas, so it
carries §15). LLM emits axis-aligned 3D `solids`; pure `domain/isometric.py`
projects them to a flat isometric GROUP (model proposes, code disposes). 482
tests, ruff+mypy clean, latency p95 0.132 ms (no regression). Built by one
Sonnet subagent (the projection module) + main-thread LLM/prompt wiring, then a
3-lens adversarial-review workflow (2 HIGH + 3 MED real bugs fixed & pinned).
Eyeball gate ✓ (cube/engine/wedge/cylinder/stack). Full details + the
plan-divergence flag in §3 (top entry).

**Still pending (human-only): browser confirm of §15** (the agent can't observe
it). Servers were live :8000/:5173 on the §15 code. Then commit/merge §15 → main
and D3 → main (disjoint files: §15 frontend, D3 backend — independent PRs).

**Prior — §15 UI canvas (zoom/pan/adaptive + focus-follow) + compose-onto-
existing — DONE (2026-06-13), committed (1b732ae), pending the human browser
confirm above.** Built via a 5-phase workflow; 8 high/med review bugs fixed.
tsc + vite build green (193 kB bundle).

Key frontend changes: new `usePanZoom.ts` (pointer events, ctrl/pinch zoom,
drag-pan, clamp 0.2–2.5×, Fit/recenter, ResizeObserver, StrictMode-safe);
new `ZoomControls.tsx` (−/%/+/Fit/Recenter/Follow toggle); `IdeaTree.tsx`
redesigned as `.idea-scroll > .idea-viewport(CSS transform) > .idea-canvas`;
focus-follow pauses while gesturing; **radial layout bug fixed** (depth-
compounding: `kidRadius = childDepth*R` made chains land at 0,R,3R,7R… — now
uniform `kidRadius = R`, tightened from ~288 px to `max(cw,ch)+60`).
`styles.css` full-bleed map (overflow:hidden + transform pan replaces grid
overflow-clip that made large maps unreachable); transcript → collapsible
`<details>` drawer; `ParticipantView.tsx` controls width-capped; `DisplayView.tsx`
full-bleed stage.

Key backend change: **compose-onto-existing** (new `domain/compose.py`,
classifier branch 5b). "Draw a horse" then "draw a box above the horse" now
composes the box onto the horse as a child iteration, not a standalone node.
436 tests (was 393; +43), ruff+mypy clean, pytest 0.53 s, latency green.

**Prior programs still current:**
§14 UNDO op ✅ · undo grammar ✅ · viewport follow ✅ · e2e ALL PASS ✅.
§13/§12 all segments DONE. Fast path p95 sub-ms. ⚠️ Groq 70b AND scout both
quota-dead 2026-06-12; all deterministic paths run without the LLM.

**Previous program (2026-06-11): Drawing Quality D1–D5 — D1/D2 done, D3–D5
resume after the §12 browser confirm. Steps:**
1. [x] **Exact-relations segment — DONE & COMMITTED** (live re-probe passed
   2026-06-12; needed one fix first — see §3 entry).
2. [x] **D1 — routing + validation repair — DONE & COMMITTED** (2026-06-12,
   built by two parallel Sonnet subagents; live-verified — see §3 top entry).
3. [x] **D2 — prompt overhaul — DONE (2026-06-12).** See §3 for details.
4. **D3 — deterministic isometric projection** (highest leverage): IR gains
   `box`/`cylinder`/`wedge` (x,y,z,w,d,h); the pure renderer does the 30°
   projection + shading + z-sort (generalize `make_isometric.py::_project`).
   LLM emits axis-aligned 3D placement only — never projection math.
5. **D4 — adherence eval + tiered models**: extend `eval_llm.py` to score
   instruction adherence (counts/colors/coherence), benchmark GLM-5 / Kimi
   K2.5 / Cerebras-hosted Qwen3 & gpt-oss; wire an escalation tier (Gemini 3
   Flash or Sonnet 4.6) for intricate/3D prompts, streamed.
6. **D5 (optional)** — async render→VLM-critique→repair polish; frontier-batch
   template growth; verify TU-Berlin license.

Then back to the standing queue (§4): browser live-confirm, Phase 1b server STT.

**Previous plan (2026-06-11, user effort=high): richer drawing power + whole-program assurance — ALL DONE.**
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
- **Embeddings tier (the "vector DB"): semantic references + near-duplicate
  cache — DONE & live-verified (2026-06-14, branch drawing-quality-d3, committed
  c344d1e; 579 tests, ruff+mypy clean, fast path unchanged).** The user's idea;
  realizes the cascade's long-planned stage B. `pipeline/embeddings.py` (Embedder
  Protocol + lazy LocalEmbedder, sentence-transformers) + `pipeline/retrieval.py`
  (numpy-cosine `_Index` + `SemanticRetrieval` + a PROCESS-WIDE `get_retrieval`
  singleton so all rooms share one model + index, not N copies). Wired into the
  LLM stage's `classify`.
  - **Semantic references:** embed the utterance → inject the nearest known-good
    drawings (template bank + remembered CREATEs) as LLM few-shot refs. Live:
    "a frosty figure" → [snowflake, ice cream] (keyword match returns nothing).
    Safe in every context — only changes which examples the model sees.
  - **Near-duplicate cache:** remember each CREATE (utterance→geometry); a
    create-like near-duplicate (cosine ≥ 0.94, no modify/extend markers via
    `is_create_like`) reuses the stored geometry and SKIPS the LLM. Live: 2nd
    "a medieval castle" → stage=cache 0.01 s vs 48 s. Reuse is always a CREATE so
    it is NON-DESTRUCTIVE (the cache safety floor); modifies/composes
    (target_node_id set) are never cached.
  - **Gated:** `QUORUM_RETRIEVAL_BACKEND=mock` (default) = OFF, no heavy dep
    needed; `local` = sentence-transformers (the `embeddings` extra). 9 unit
    tests use a deterministic STUB embedder (no torch in CI). Enabled in .env now.
  - Follow-ups (noted, non-blocking): first novel utterance per process warms the
    345-template index (~3-4 s one-time — could warm at startup); the cache is
    in-memory (lost on restart — persist later); references quality is bounded by
    the template corpus ("frosty figure" found snowflake, not a snowman — corpus
    gap, fine).
- **Detection-accuracy fixes + fast/accurate model — DONE & live-verified
  (2026-06-14, branch drawing-quality-d3; 570 tests, ruff+mypy clean, fast path
  p95 0.119 ms; committed 63e917c).** Two live user-reported bugs, root-caused by
  a read-only investigation subagent, fixed and reproduced live:
  - **FOCUS BUG — "a new shape keeps editing the OLD shape."** `engine._create`
    only moved focus to a new node when the canvas was EMPTY (`first = _focus_id
    is None`), so every create after the first left focus on the prior node and
    follow-ups ("make it bigger") hit it. Now EVERY create takes focus + demotes
    the previous to ACTIVE (mirrors `_modify`; the demotion is an in-memory status
    mutation, replay re-derives statuses from the final focus). Live:
    circle→square→triangle each take focus. Regression-pinned incl. replay.
  - **PLACEMENT ~20% → deterministic.** above/below/left/right/beside were NEVER
    snapped — only inside/tangent were — so spatial placement was raw model
    guesswork. New `relations._snap_all_directional` translates the newly-added
    part(s) to the stated side of the host (shared `_partition_new` helper with
    the inside snap; same "model proposes, code disposes" pattern). Live: "a box
    above the horse" → box centre-y 21 vs horse 57 (ABOVE). Pinned (above +
    beside). "on top of" is intentionally left to the compose on_top (overlap)
    path, not directional snap.
  - **Compose target hardened (#3):** classify.py branch 5b now resolves the
    compose TARGET with `definite_only=True`, so an indefinite shape mention
    ("a line above the horse") can't stem-match and hijack a fresh create into a
    MODIFY of an existing "line" node.
  - **Default model → `google/gemini-2.5-flash-lite`** (adherence bake-off
    2026-06-14): ~2 s/call AND strong on color (blue car 1.0, yellow star 1.0),
    placement (blue circle inside red square 1.0) and 3D — vs the cheapest 'ling'
    (5-70 s, color 0.70, relations None/0). `gpt-5-nano` unusable (reasoning
    model: 65 s, null content → BAD). Set in settings.py default AND .env.
  - UX/UI polish bugs explicitly DEFERRED by the user ("down the road"); a vector
    DB (semantic retrieval + result cache) proposed as the next speed/consistency
    enhancement (§4).
- **D4 (part 1) — instruction-adherence eval + OpenRouter backend + cheap-tier
  benchmark — DONE (2026-06-13, branch drawing-quality-d3; 568 tests (+87:
  85 adherence, 2 openrouter), ruff+mypy clean (38 files), fast path p95
  0.129 ms unchanged).** Delivers the "measured adherence table" half of
  plan.md §11 D4; the escalation-tier + streamed-fast-tier half is the next
  segment (§4). Also closes the owed D3 live probe.
  - **`quorum/eval/adherence.py`** (NEW, pure, no vision model): scores how well
    a result GeometrySpec ADHERES to an utterance across `count` (role-name
    substring match), `color` (hue match via `domain/color.py` HSL — chromatic
    vs achromatic branches; the near-black default stroke deliberately does NOT
    count as "blue"), `coherence` (union-find bbox connectivity = anti
    exploded-view), `relations` (inside/above/below/beside bbox predicates,
    skip-if-unresolved), `solids3d` (the `solids` payload path OR a multi-band
    shaded-fill signature). `overall` = mean of the APPLICABLE dims; invalid → 0.
    Same "model proposes, code disposes" split: the model draws, the code
    measures.
  - **`scripts/eval_adherence.py`** (NEW): 11-prompt annotated set + multi-model
    runner; **keyless `--self-test` (8/8 PASS)** scores fixtures so the harness
    is verifiable WITHOUT a key.
  - **OpenRouter wired as an OpenAI-compatible backend** (`Backend.OPENROUTER` +
    settings + unified `_send` sharing the Groq code path; OpenRouter-only
    `HTTP-Referer`/`X-Title` headers). Opt-in `record_diagnostics` on
    `LLMClassifier` (default OFF → server writes no shared state) records each
    payload's kind (solids/patch/geometry/none) for the harness. Groq free tier
    was 429-dead; **OpenRouter (user's key, paid, $10 credit) is now the active
    backend** (`QUORUM_LLM_BACKEND=openrouter`, model `inclusionai/ling-2.6-flash`).
  - **D3 live probe (owed) — DONE & eyeball-verified:** "a 3D engine with three
    pistons" via the cheapest model (ling-2.6-flash) → stage=llm, `solids` path
    → a coherent isometric assembly (shaded block + 3 depth-sorted pistons,
    rendered PNG eyeballed). The model EMITS `solids` and the projection lands —
    closes the D3 debt (previously only the deterministic projection was verified).
  - **Cheap-tier adherence benchmark** (3 models, 7 s pacing to dodge per-model
    429s; OpenRouter passes upstream throttles through):
    | model | valid | solids | overall* | count | color | coher | rel | solids3d | p50/p95 s |
    |---|---|---|---|---|---|---|---|---|---|
    | inclusionai/ling-2.6-flash (cheapest) | 11/11 | 3/3 | 0.90 | 0.90 | 0.70 | 0.97 | — | 1.0 | 5.8/29.7 |
    | meta-llama/llama-3.1-8b-instruct | 11/11 | 2/3 | 0.91 | 1.0 | 0.80 | 0.0 | 1.0 | 10.8/41.7 |
    | qwen/qwen3-235b-a22b-2507 | 10/11† | 3/3 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 14.8/71.8 |
    *overall = mean over VALID rows (conditional on a drawing being produced).
    †qwen's one BAD row was a **429-exhausted NOOP, not a quality fail**
    (rate-limit-corrupted — same caveat as the 2026-06-11 Groq incident).
    **Findings:** all 3 reliably use the `solids` path (solids3d 1.0 — D3
    corroborated at the model level); **color-following is the cheap tier's weak
    spot** (ling 0.70); relations are the hardest dimension. **Every cheap
    OpenRouter route is 30–72 s p95 — escalation-tier latency, NOT the ≤2 s fast
    tier** (latencies include 429-retry waits but per-call is still seconds). So
    the benchmark INFORMS but does NOT promote a production default, and a
    rate-limit NOOP is never read as a quality signal (decisions log).
  - **Adversarial harness review (workflow, 3 lenses → verify): 5 real findings
    fixed + pinned by regression tests** — (MED) `count` over-counts on
    projected solids (face-decomposition multiplies role names: "piston-1" →
    "piston-1-body"+"piston-1-top") → skip count on the `solids` path; (MED) a
    full-canvas background rect bridged everything in `coherence` → exclude
    near-full-canvas parts (≥85 in both dims) as connectors; (MED) `overall`
    averaged NOOP zeros while dim columns didn't → condition `overall` on valid
    rows (validity column carries coverage); (LOW) `solids3d` false-positive on
    a white-bg+dark pair → exclude near-white (L>0.92) fills from the shading
    signature; (LOW) annotation gaps → added handle/scarf/hat counts. The review
    also independently CONFIRMED a self-caught bug fixed pre-review:
    `NAMED_COLORS` black/white must be truly achromatic (s=0) or they read as a
    dark blue / are unmatchable.
- **D3 — deterministic isometric projection — DONE & eyeball-verified
  (2026-06-13, branch drawing-quality-d3; ruff+mypy clean, 482 tests
  (+46: 35 isometric, 11 d3_solids), latency p95 0.132 ms unchanged).**
  The LLM now reasons only about axis-aligned 3D PLACEMENT; the code does the
  exact 30° projection — the relations.py/extrude.py "model proposes, code
  disposes" pattern applied to volumetric 3D. "a 3D engine with pistons" now
  renders as a coherent isometric assembly (was an exploded flat layout).
  - **DESIGN DIVERGENCE from plan.md §11 D3 (flagged per CLAUDE.md §7, does
    NOT change the queue):** plan said "the *renderer* does the projection".
    Built instead as a pure DOMAIN transform that projects solids to a flat
    GROUP of polygon/ellipse/path parts — because the codebase already
    establishes that pattern (extrude.py, make_isometric.py) and both renderers
    + the engine/replay/wire-contract already handle GROUPs. Net: **zero
    renderer changes, zero client TS changes**, projection written ONCE in
    Python. The plan's spirit (deterministic, pure, cached, LLM does no
    projection math) is fully honored; only the layer differs.
  - **`backend/quorum/domain/isometric.py`** (NEW, pure, Sonnet subagent):
    `Solid(shape,x,y,z,w,d,h,color,name)` dataclass + `project_solids(Sequence[
    Solid]) -> GeometrySpec|None`. Box/wedge → faces enumerated as 3D polygons,
    culled by `outward_normal · (1,1,1) > 0`, projected (`sx=(x-z)cos30`,
    `sy=(x+z)sin30-y`; world y is UP), shaded by normal orientation (L=0.80 top
    / 0.55 front / 0.40 side / 0.22 stroke, sat floor 0.18, gray default
    #9ca3af), z-sorted globally by world-centroid·(1,1,1) ascending (far first).
    Cylinder → body PATH (sides + bottom half-ellipse) + top ELLIPSE.
    Everything centered+scaled into [8,92] (fit ported from make_isometric).
  - **`backend/quorum/pipeline/llm.py`**: `_SolidSpec` model + `_LLMPayload.
    solids` (transient — projected in `payload_to_op` before the op leaves the
    stage, so engine/replay/renderers see only the flat GROUP); solids clamp in
    `_parse_and_repair`; prompt gains a "TRUE 3D — PREFER solids" rule + schema
    line + worked **Example J** (3D engine = block box + 3 piston cylinders);
    Example E re-marked as the hand-drawn FALLBACK (was contradicting the new
    rule for "a 3D cube").
  - **3-lens adversarial review (workflow, 3 Sonnet agents) found 9 issues; the
    real ones fixed + pinned by regression tests:** (HIGH) `snap_relations`
    must be SKIPPED for projected solids — its `inside`/`within` snap was
    yanking a cylinder cap into the body (`from_solids` guard); (HIGH) the
    60-part cap truncation kept the FARTHEST faces — now drops whole far CHUNKS
    so the NEAREST survive and cylinder body/top pairs never split; (MED)
    cylinder screen radii were missing a √2 factor (29% too narrow) — projected
    circle x-semi-axis is r·√2·cos30; (MED) modify+solids now pins
    target_node_id to focus (mirrors the patch branch); (MED) deleted dead
    `_scale_path_str`; (LOW) log when geometry+solids both sent. Skipped (out of
    scope, documented): shared cylinder z-key only mis-orders partial-
    interpenetration arrangements we don't support.
  - **Eyeball gate (`scripts/render_d3.py` → SVG+PNG via qlmanage):** cube
    (3 shaded faces), engine (pistons on block, depth-sorted), wedge (ramp),
    cylinder (foreshortened top), 3-box stack (cross-solid z-sort) — all ✓,
    re-verified after the √2 cylinder fix.
  - No classifier change needed: 3D intent already escalates to the LLM (D1),
    which now has the `solids` tool; named-shape extrude (N4-B) and the
    isometric template bank still serve the rules/template paths.
- **§15 — UI canvas zoom/pan/adaptive + compose-onto-existing — DONE
  (2026-06-13, branch ui-zoom-adaptive-canvas; tsc + vite build 193 kB,
  436 tests, ruff+mypy clean, pytest 0.53 s).** 5-phase workflow: design
  watchlist → 2 parallel implementers on disjoint files → build gate → 3
  adversarial review lenses → fix-pass; 8 confirmed high/med bugs caught & fixed.
  - **`frontend/src/usePanZoom.ts`** (new, zero deps): pointer events; ctrl/
    meta-wheel + 2-pointer pinch zoom-about-cursor; plain-wheel pan; drag-pan;
    clamp 0.2–2.5×; Fit/auto-fit/recenter; ResizeObserver; StrictMode-safe
    cleanup + pointer-capture release; wheel listener `{passive:false}` so
    `preventDefault` works (React `onWheel` is passive).
  - **`frontend/src/ZoomControls.tsx`** (new): −/%/+/Fit/Recenter/Follow
    toggle (`aria-pressed`); `stopPropagation` so control clicks never pan.
  - **`frontend/src/IdeaTree.tsx`**: structure now `.idea-scroll >
    .idea-viewport(CSS transform) > .idea-canvas`; focus-follow recenters the
    focused card in transform space, PAUSES while gesturing, gated on the
    Follow toggle; "sketching…" badge on the focused card when pipeline
    status != idle. **FIXED radial-layout depth-compounding bug:**
    `kidRadius = childDepth*R` made chains land at 0,R,3R,7R — now uniform
    `kidRadius = R`, tightened from ~288 px to `max(cw,ch)+60`.
  - **`frontend/src/styles.css`**: FIXED `.idea-scroll` `grid place-items:
    center overflow-clip` bug that made large maps unreachable (now
    `overflow:hidden` + transform pan; `.idea-canvas` drops `margin:auto`);
    participant map is full-bleed; transcript → collapsible `<details>` drawer;
    Display `.display-stage` full-bleed; `prefers-reduced-motion`;
    `max-width:640px` responsive pass; zoom-controls / `.zc-btn` / `.sketch-badge` CSS.
  - **`frontend/src/ParticipantView.tsx`**: controls inner block width-capped,
    transcript drawer, Undo button (sends utterance text "undo").
  - **`frontend/src/DisplayView.tsx`**: full-bleed stage.
  - **`backend/quorum/domain/compose.py`** (new, pure):
    `place_relative(target, new_part, relation)` → flat GROUP fit to the
    0..100 box; relations above/below/left/right/on_top/behind/inside;
    z-order (behind prepends, others append; on_top painted last); reuses
    `relations.py` `part_bbox` + `_contain`; guards the 60-part limit. Minor
    deferred: `_translate_part` clamps before fit-to-box so an added shape
    can be slightly squished when the target hugs a canvas edge.
  - **`backend/quorum/pipeline/classify.py`**: new branch 5b — "[create/draw/
    add/put/place] a <shape> <spatial relation> the <existing node>" → compose-
    MODIFY of the RESOLVED target node (conf 0.8, source=rules, modifiers=[]);
    engine branches a child (§12-R1); falls back to focus when no explicit
    target. Over-trigger guards: does NOT hijack plain create, multi-shape
    create, or recolor; unresolved definite reference blocks the implicit-focus
    fallback; `_detect_relation` maps "on top" (without "of") to `on_top` not
    `above`; branch 5 yields to 5b when a mentioned shape resolves to an
    existing definite node.
  - New tests: `backend/tests/test_compose.py` and additions to
    `backend/tests/test_classifier.py`.
- **§14 U1+U2+U4 — voice undo/go-back — DONE, e2e ALL PASS (2026-06-12;
  U1/U2 by a Sonnet subagent, integrated + gated on the main thread).**
  393 tests (was 354; +39 in test_undo.py), ruff+mypy clean, fast path p95
  **0.128 ms** (improved from 0.178 — undo's branch-0 early return is free).
  - **U1 engine:** `OpType.UNDO` → `_undo()` resolves focus →
    `parent_ids[0]`, moves focus via `_set_focus` (FOCUS_CHANGED enters the
    log; replay re-derives statuses from final focus — verified by test),
    abandoned child stays ACTIVE (user-confirmed), root focus = no-op (no
    event), both ends of the move upserted.
  - **U2 classifier:** branch 0 (before ALL content branches, EXEMPT from
    hazy caps — the phrase IS the meaning, never LLM work, quota-immune):
    undo/go back/revert/scratch that/never mind/zoom (back) out/previous
    one|version|situation|step|state, conf 0.9. GUARD: "go back to the
    <resolvable label/shape>" falls through to FOCUS resolution. "go
    backwards"/"the back of the house" don't fire (word-boundary regex).
    Watch live: bare "the previous version had a window" WOULD fire UNDO —
    revisit if it bites.
  - **U4 integration:** `e2e_check.py` §14 chain ALL PASS against a real
    server: hexagon chain → "never mind, go back" (focus→pink, no new
    nodes, prism stays visible) → "go back" (focus→root) → "make it blue"
    → blue SIBLING child of the hexagon. §12/§13 chains unregressed.
  - **Harness fix found by the gate:** a LIVE-but-quota-dead LLM (Groq
    429s) yields a NOOP fallback → NO diff broadcast → the old script hung
    at the rocket step and never reached the LLM-free steps. e2e_check.py
    now catches the 15 s timeout there and SKIPs loudly ("quota-dead?");
    assertions unchanged when a diff does arrive. Also confirmed: the
    template stage only exists when the LLM backend is on, so a mock-LLM
    run can NOT exercise the template steps — gate with the live backend.
  - **⚠️ Groq quota (2026-06-12): BOTH llama-3.3-70b AND llama-4-scout are
    now 429-dead for the day.** All §14 + §12/§13 deterministic paths run
    fine without the LLM (by design). The user has offered to supply more
    API keys — D4's tiered-models work should pick that up.
- **§14 U3 — viewport follow (frontend) — built (2026-06-12, main thread;
  tsc + vite build clean).** `IdeaTree.tsx`: the `.idea-scroll` container
  (already `overflow:auto`) gets a ref; a `useEffect` keyed on the focused
  card's LAYOUT position smooth-scrolls it to the viewport center on every
  focus change or reflow. Deliberately scrolls to the layout coords, not the
  rendered box — cards animate left/top over 0.45 s, so `scrollIntoView`
  would chase a mid-transition position. NO layout/redesign change (gated
  on the user's incoming design reference). Hook sits before the
  empty-state early return (hooks-order rule). Browser-confirm with the
  §14 acceptance script.
- **§13 INTEGRATION — ALL SEGMENTS DONE, e2e ALL PASS, live mouse + hexagon
  chains verified, eyeball-gated (2026-06-12).** 354 tests, ruff+mypy clean,
  fast path p95 0.178 ms (explained in §7). Two real bugs caught at the
  integration gate — both classes now pinned by tests:
  - **Extrude winding flip (eyeball gate caught it):** the agent's
    trapezoid-form shoelace has the OPPOSITE sign of the cross-product form
    its winding rule assumed — every outward normal flipped, the BACK edges
    extruded, and the bands hid behind the front face (render: pink hexagon
    with slivers — not 3D). One-line sign fix + a side-pinning regression
    test (bands must protrude up-right beyond the front face for BOTH
    windings) + the contiguity test made wraparound-aware (visible run
    {5,0,1} is contiguous mod 6). Count-based asserts alone could NOT catch
    a side flip — pin the SIDE.
  - **Double-fold on part-scoped MODIFY (live probe caught it):** branch 6c
    baked modifiers into op.geometry AND passed op.modifiers — the engine
    folds modifiers onto replacement geometry, so "make one eye bigger"
    grew the whole mouse ×1.3 and the eye ×1.69. Fix: emit modifiers=[]
    when geometry is pre-baked. New classifier+engine INTEGRATION test
    (op-level asserts could not see a downstream double-fold).
  - **Live verifications (scout model — 70b daily quota exhausted):**
    mouse → "add two eyes to this mouse" = LLM PATCH, 1.23 s (vs ~4-5 s
    full re-emission), originals byte-identical, eye-left/eye-right added
    on the head; → "make one eye bigger than the other" = rules 0.00 s,
    ONLY eye-left grew; rendered PNG eyeballed ✓. Hexagon → pink →
    three-dimensional: all three steps rules-stage 0.00 s, extruded prism
    in three pink bands, eyeballed ✓. e2e_check.py extended with the §13
    chain — 16/16 ALL PASS against a real server + live Groq.
  - **Safety inversion verified live:** with the LLM 429-dead, "make one
    eye bigger than the other" (no eyes yet) now does NOTHING (rules NOOP
    0.5) — previously it scaled the whole mouse.
  - **Ops:** backend/.env now pins QUORUM_GROQ_MODEL=llama-4-scout (per-
    model quotas; 70b's daily allowance is spent — tiny pings pass, real
    ~4k-token prompts 429). Code default stays 70b per the decisions log.
    Server restarted on scout; healthz green.
- **§13 N1/N2/N4 classifier routing — built (2026-06-12, Sonnet subagent;
  14 new tests, zero regressions).** `classify.py`: demonstratives
  this/that/my/our join "the" in definite shape AND label references
  (branch 4 wins over named-shape CREATE — "turn this hexagon pink" is a
  MODIFY now); new branch 6c part-scoped fast path (resolve_parts →
  apply_to_parts, conf 0.75); branch 7 fallback INVERSION — a determiner
  followed within 2 words by an unexplained unresolvable word = part-ish
  reference we can't find → hazy NOOP (dead LLM does nothing) instead of
  hazy whole-scene MODIFY; N4-A extrude routing (3D intent + target IS
  focus → MODIFY with extrude(focus_geometry) conf 0.8; extrude None →
  hazy as before); N4-B CREATE freebie ("a 3D hexagon" → extruded CREATE)
  for NAMED_SHAPES only — basic shapes stay hazy 0.5 so "a 3D cube" still
  hits the isometric TEMPLATE (D1 contract preserved).
- **§13 N2-N4 domain + LLM layers — built (2026-06-12); classifier routing
  in flight (superseded by the INTEGRATION entry above).** All checks green on a clean run: **338 tests** (the websocket
  timeouts two parallel agents reported were suite-stacking, per the pinned
  gotcha — single run passes).
  - **`domain/parts.py`** (Sonnet subagent, 33 tests): `PartsPatch`
    {set/add/remove}, `resolve_parts` (role-token match on part names +
    geometric qualifiers in CODE: left/right/top/bottom/biggest/smallest/
    widest/tallest/first/second/last; plural → all matches, bare singular →
    first), `apply_to_parts` (modifier fold scoped to named parts, size
    scales about the PART's center, color via §12 retint), `apply_patch`
    (remove→set→add; 10 validation warnings incl. unknown-target drop,
    kind-change strip, add-name auto-suffix, zero-parts guard, single-shape
    wrap-as-group).
  - **`domain/extrude.py`** (Sonnet subagent, 29 tests): oblique-cabinet
    extrusion — silhouette (polygon verbatim / rect / renderer-exact
    triangle / 16-gon circle+ellipse / single-part group) offset (k,-k),
    k=0.7071·depth (default 9); fit-shrink about centroid to [2,98]; edge
    visibility by winding-corrected outward normal · offset; band quads
    far-first, face-front LAST; three lightness bands of the shape's OWN
    hue (pink #db2777 → #ef9fc2/#de3a83/#a61c59). Unsupported kinds → None
    (stays LLM territory).
  - **`templates.py` `_name_parts`** (main thread): unnamed template strokes
    get stable `part-1..n` names at load — every template part is now
    addressable (was diagnosis root cause 3).
  - **`llm.py` patch contract** (main thread, surgical): `_LLMPayload.patch:
    PartsPatch`; prompt schema + "PREFER patch over geometry" edit rule
    (EXTENDING rewritten: full re-emit is now the fallback for restructures
    only), RESTYLING now patch-first, worked Examples H (add-eyes patch) and
    I (one-eye-bigger set patch); clamp repair covers patch.add/patch.set;
    `payload_to_op` composes the patch against focus_geometry (re-points
    the target to the focus, logs dropped clauses, all-clauses-dropped →
    no-geometry op = engine no-op). Engine/replay contract untouched.
    Eyeball gate pending Groq quota reset.
- **Live diagnosis: in-chain conversion + part-level edits (2026-06-12, user
  browser feedback + agent probes) — input to plan.md §13.** User: "make
  this hexagon 3D" fails; "make one eye bigger than the other" on a mouse
  fails. Probed root causes (5):
  1. **"turn THIS hexagon pink" → CREATE duplicate, not MODIFY** — definite-
     reference detection only knows "the", not this/that/my; demonstrative
     falls through to the named-shape CREATE branch (probe: n2 new pink
     hexagon, chain broken).
  2. **"make it 3D" has no deterministic path** — goes hazy→LLM (correct
     routing), but kind-conversion by re-emission is the model's weakest
     skill, and the dead-LLM fallback emits a FLAT duplicate.
  3. **Template parts are UNNAMED** (QuickDraw strokes) — "the left eye" has
     no handle to resolve against; only LLM-added parts carry names.
  4. **Dead-LLM fallback on part-scoped edits is actively wrong**: "make the
     left eye bigger than the right eye" → hazy bare-modifier MODIFY →
     429 → fallback folded "bigger" onto the WHOLE mouse (probe: n2 = scaled
     mouse). Wrong-everything beats wrong-nothing — must invert.
  5. **Groq free tier exhausted mid-session** (429 incl. retry) — the
     deterministic paths must carry these flows; LLM-only designs are
     quota-fragile. (User offered to supply more APIs — relevant to D4.)
- **§12 INTEGRATION — whole-program verified, live-probed, eyeball-gated
  (2026-06-12, main thread).** Full gate: ruff, mypy, **272 tests**, latency
  e2e p95 0.122 ms, tsc + vite build. `e2e_check.py` extended with the §12
  acceptance chain and ran ALL PASS against a real server + live Groq:
  "a rhombus" → exact labelled polygon; "draw a cuboid" → labelled isometric
  template; "i want the cube to be red" → **rules fast path** (no LLM),
  NEW child node, parent intact, three DISTINCT red-tinted face fills,
  coordinates byte-identical. Live probe (`probe_llm.py`): "a cat" (template
  0.02 s) → "make the cat orange" (stage=rules 0.00 s, child node, all 8
  strokes #ea580c) → "shade it into a tabby with stripes" (stage=llm ~4 s,
  all 8 cat paths byte-identical + beige hachure fills + thin brown stripes).
  **R5 eyeball gate: first probe FAILED usefully** — "stripes" came back as
  one solid brown block over the cat's eyes; one additive prompt line
  (details = SEVERAL thin shapes ≤4 high near edges, never cover
  eyes/face/screen) fixed it on re-probe. `probe_llm.py` gotcha fixed:
  diffs now upsert child+parent, so SVG filenames carry the node id
  (`probe_<i>_<node>.svg`) — the old per-step name silently overwrote the
  child's SVG with the parent's. e2e latency note (RULES.md §6, >20%
  explained): e2e p95 0.072 → 0.122 ms because every MODIFY now creates +
  renders a child node (intended §12-R1 semantics); still ~4 orders of
  magnitude under the 5 s budget.
- **§12 R3+R4 — labels, label resolution & named-geometry tier (classifier)
  — built (2026-06-12, Sonnet subagent; 80 new tests; 0 regressions in
  existing test files).** New `domain/shapes.py`: 18 named shapes — polygon
  generators (rhombus/diamond, parallelogram, trapezoid/trapezium,
  pentagon→octagon, star, arrow, cross/plus, kite) + constrained-path ones
  (semicircle, heart, crescent), all validate AND render. `classify.py`:
  branch 6b emits exact named-shape CREATEs at conf 0.85 with `label=word`;
  `_resolve_by_label` gives branch 4 (and branch 1 FOCUS) definite-reference
  resolution against candidate labels — match rule: exact → plural-s →
  3-char common stem when both words ≥4 chars ("cube"↔"cuboid" via "cub");
  label-matched tokens count as EXPLAINED before the hazy thresholds, so
  "i want the cube to be red" is now a clean conf-0.75 fast-path MODIFY.
  ShapeKind resolution still preferred over label; newest candidate wins.
  `templates.py` stamps `label=name` on template CREATEs. NOT done (left to
  LLM path): multi-named-shape scene composition ("a rhombus next to a
  hexagon" stays hazy→LLM). Watch live: the 3-char stem could over-match
  rare label pairs ("card"↔"cart") — newest-wins limits the blast radius.
- **§12 R2 — deterministic recolor (domain) — built (2026-06-12, Sonnet
  subagent; ruff+mypy clean; 19 new tests in test_recolor.py, all 27
  geometry-v2 tests green).** New `domain/color.py`: `parse_hex` (#rgb +
  #rrggbb), rgb↔hsl, `retint(original, target)` = target hue+saturation with
  `L' = clamp(0.7·L_orig + 0.3·L_target, 0.08, 0.94)` — monotonic in the
  original lightness (shading order survives) while pulling near-whites
  toward the target so they read as the color. `apply_modifiers` `color:`
  branch: fill set → retint fill AND stroke; fill None (stroke-only
  QuickDraw sketches) → stroke = exact target as before. Cuboid trio
  verified: #e5e7eb/#9ca3af/#6b7280 + red → #f0a2a2/#e35252/#d02222
  (ordering preserved). Gotcha: ruff E741 bans `l` — lightness vars are
  `li`. Unparseable original (CSS name) falls back to the target color.
- **§12 R1 — Iteration-as-branch (engine) — DONE (2026-06-12).** `engine/state.py`
  changes (method by method): `_new_node` now uses `op.label or geom.label`
  (op wins for R3 label inheritance). `_modify`: no-change guard returns early
  with current view when `new_geom == node.geometry` (no node, no event);
  real changes create a CHILD node via `_new_node(op, new_geom, parent_ids=[node.id])`,
  inherit parent label when op label is None, append child id to parent's
  `children_ids`, record `NODE_MODIFIED` carrying the child's snapshot (replay-
  safe: snapshot-driven fold registers the child by its new id), set child
  FOCUSED / parent ACTIVE, move focus via `_set_focus` so FOCUS_CHANGED enters
  the log. `_MAX_ACTIVE_BRANCHES` raised 8→16 (iteration chains consume cap
  budget). `_ancestor_ids()` new helper: walks `parent_ids` from focus, cycle-
  safe, returns the trunk set. `_enforce_caps` updated: both affirmation-floor
  prune and max-active-cap prune skip trunk nodes. `apply()` unchanged — focus-
  move logic already adds both ends to upserted; `final_upserts` dedup picks
  up the parent's updated view. Replay (`from_events`) unchanged — children_ids
  re-derived from parent_ids as before. Tests: 189 pass (was 178 before this
  segment; 11 new in `test_iteration_branch.py`, existing tests updated). Fast-
  path engine p95 = 0.100 ms (well under budget). Event semantics: NODE_MODIFIED
  carries the CHILD's snapshot; the parent's updated children_ids are re-derived
  at replay from the child's parent_ids — no replay breakage.
- **§12 R6 — radial mind-map canvas (frontend) — built (2026-06-12, Sonnet
  subagent; tsc + vite build clean).** `IdeaTree.tsx` layout rewritten as a
  pure radial function: single root at the exact center owning the full
  circle; multiple roots evenly spaced on ring 1 with outward sectors;
  children subdivide the parent's sector proportionally by subtree LEAF
  count (memoized, cycle-safe), child at radius `(depth+1)*R` (~270 px) on
  the sector bisector — so an unforked iteration chain extends straight
  outward, exactly the asked-for look. Cards keep numeric-id ordering
  (deterministic), canvas translated to positive coords + sized to extent
  inside the existing scroll container. CSS: `.node-title` label chip
  (renders only when `node.label` set), card-enter fade/scale keyframe,
  0.45 s left/top transition for map reflow. Watch live: 5+-deep chains
  scroll horizontally; near-vertical sibling edges draw a flat S-curve
  (acceptable; revisit if ugly).
- **§12 R5 — restyle prompt rule + op labels (LLM stage) — built (2026-06-12,
  main thread; ruff+mypy clean; full-suite gate pending integration).**
  Surgical/additive per the eyeball-gate decision: prompt gains a RESTYLING
  rule (appearance-only follow-ups re-emit `focus_geometry` with IDENTICAL
  structure/coords, changing only stroke/fill/fill_style; 3D keeps its shaded
  faces re-tinted in light/mid/dark of the same hue) + a `label` schema field
  (1-3 word concept name). `_LLMPayload.label` added; `payload_to_op` stamps
  `op.label` with a template-match fallback on CREATE/BRANCH ("a snowman" →
  "snowman") and leaves MODIFY None so the engine inherits the parent's
  label. `_user_payload` candidates now carry `label` so the model can
  resolve "the cat" to a node id. DesignOp gained the `label` field
  (domain/op.py) as the shared contract for R1/R3.
- **Compositional follow-ups fixed — live-verified (2026-06-12 live test).**
  User's live finding: "draw an isometric box" → "add a red sphere inside"
  drew an EXTERNAL sphere. Root cause: rules branch 7 (bare-modifier MODIFY)
  matched "red" at conf 0.70 — the LLM was never consulted; "sphere"/"add"/
  "inside" left only 1 unexplained word, under the ≥2 hazy threshold. Fixed
  in three layers (162 tests, ruff+mypy clean):
  - **Detection** (`classify.py`): `_EXTEND_RE` (add/put/place/insert/attach/
    stick/mount/embed + inside/into/within/onto/on top of/in front of/behind)
    makes any rules match hazy when a focus exists — composing INTO a scene
    is LLM work. Branch 7 additionally goes hazy on ≥1 unexplained word
    ("add a red SPHERE"). "make it bigger" stays fast (0.7); "add a circle"
    with no focus stays a fast CREATE (0.85).
  - **Wording** (`llm.py` prompt): PLACEMENT rule — "inside X" = fully within
    the scene's box, centered, listed AFTER so it paints on top; "on top of
    X" = bottom edge touches X's top edge.
  - **Enforcement** (`relations.py`): `_snap_all_inside` — new parts (names
    not in `focus_geometry`; last part when no focus) that lie outside the
    old parts' union box are centered into it, shrunk to 80% of the smaller
    span only if oversized. Paths pass through. Same "model proposes, code
    disposes" pattern as tangency; `payload_to_op` now takes
    `focus_geometry` to tell old parts from new.
  - **Template synonym**: "isometric box" → cuboid ("draw an isometric box"
    is now a 0.02 s direct hit; it was going to the LLM at 1.6 s).
  - **Live re-probe**: box = template hit with 3 shaded faces; "add a red
    sphere inside" → MODIFY, faces byte-identical, red solid sphere centered
    inside, painted on top. Rendered PNG eyeballed ✓.
  - **Suite-hang diagnostic captured + guarded**: caught the real deadlock
    live and sampled it — main thread in portal cond-wait, anyio loop thread
    in kevent (TestClient double-websocket theory CONFIRMED at C level).
    Added `pytest-timeout` (30 s, `timeout_method=thread`) so a future strike
    fails in 30 s WITH per-thread Python stacks instead of hanging forever.
- **D2 — prompt overhaul — DONE, eyeball-verified before/after (2026-06-12).**
  154 tests (was 148), ruff+mypy clean, fast path p95 0.084 ms (unchanged).
  **The subagent's first prompt rewrite FAILED the eyeball gate** — lesson
  pinned in the decisions log. What shipped after main-thread repair:
  - **Painter's z-order** rule block (parts render in list order, build
    back-to-front) + **decompose recipe** now demands ATTACH-and-OVERLAP
    (boxes share area or an edge; never disjoint side-by-side) while KEEPING
    the proven signature-parts examples (phone = body+screen+camera) and the
    orientation guidance — the v1 rewrite dropped those and regressed.
  - **3D rule**: the proven Example-E recipe (front face + top/side
    parallelograms, never hidden faces) + fills ON with three shades (light
    top #e5e7eb / mid front #9ca3af / dark side #6b7280). The v1 rewrite's
    "back face first" contradiction is gone.
  - **Example G = coffee mug with steam** (body, coffee surface occluding the
    rim, handle overlapping the right edge, steam into the coffee) — teaches
    attach/overlap/z-order WITHOUT mis-teaching isometric (v1's "isometric
    house" example was literally a flat front view; the model copied it).
    Pairwise-overlap pinned in tests (computed, not eyeballed).
  - **create-vs-modify + copy-verbatim** strengthened (the two live slips).
  - **Flat QuickDraw ref suppression** on 3D utterances via new shared
    `quorum/pipeline/intent.py::has_3d_intent` (classify.py imports llm.py,
    so the regex lives in a third module — no circular import).
  - **Fused-points repair** (`_split_concatenated_pair`): live scout-17b
    emits `[[3040]]` for `[[30,40]]` (comma dropped) — the engine's BLOCK was
    emitted every time and silently salvage-dropped. Split only when the
    digits parse uniquely into two 0..100 coords (no leading zeros).
  - **eval_d2.py**: fixed 10-prompt set, before/after run live on
    **scout-17b** (70b daily quota was exhausted — model held constant, fair
    prompt comparison). Eyeball verdicts: isometric house ✓ much better
    (true 3-face shaded cube + chimney), rocket ✓ (overlapping fins back),
    mug ✓, castle/snowman healthy; sailboat mixed; **3D engine still fails**
    (pistons w/o block; second probe emitted `kind:"cylinder"` — invalid).
    The model keeps reaching for volumetric primitives — direct evidence for
    D3's box/cylinder/wedge IR. Engine/desk-lamp stay open for D3/D4.
  - Net prompt: ~1,4xx tokens vs ~1,225 before (~+15%); LLM latency p50/p95
    on the 10-set: 1.8 / 5.3 s (scout) — no regression vs before (2.2/6.3).
- **D1 — routing + validation repair — DONE, live-verified (2026-06-12).**
  Built by two parallel Sonnet subagents (disjoint files), merged + verified
  on the main thread. 148 tests (was 115), ruff+mypy clean, fast path p95
  0.088 ms (unchanged).
  - **Routing** (`classify.py`): new `_3D_INTENT_RE` ("3d"/"3-d"/"iso(metric)"/
    "three[- ]dimensional") joins `_RELATION_RE` in the `hazy` clause — any 3D
    token caps a rules match at 0.5 so the cascade escalates. Template hits
    preserved: "a 3D box" → template synonym "3d box"→cuboid, **isometric
    3-shaded-face cuboid at conf 0.90 in 0.02 s live** (was: flat rect 0.85,
    LLM never consulted). +10 tests (`test_d1_routing.py`).
  - **Validation repair** (`llm.py`): pipeline is now **clamp → validate →
    salvage → one corrective retry → NOOP** (was: any error → silent NOOP).
    `_repair_geometry_dict` clamps x/y/points 0..100 etc. pre-validation
    (domain validators stay strict — the LLM stage repairs its own input);
    `_salvage_group_parts` drops rotten parts, keeps groups with ≥1 survivor,
    logs drops; `_corrective_retry` feeds the pydantic error back ONCE (no
    retry-on-retry; worst case 4 HTTP calls incl. 429 retries); explicit
    `max_tokens` via `QUORUM_LLM_MAX_TOKENS` (default 4096; Ollama
    `num_predict`). Path `d` data intentionally NOT clamped (would corrupt
    curves — pathdata stays the gatekeeper). +21 tests
    (`test_d1_validation.py`).
  - Live escalation probe: "a 3D engine with pistons" → stage=llm 2.11 s,
    extends the scene with named pistons. ⚠️ It chose MODIFY of the focused
    box, not CREATE — the create-vs-modify rule (Example E) still slips;
    folded into D2's prompt set alongside the copy-verbatim gap.
- **Tangency segment FINISHED: live re-probe passed, committed (2026-06-12).**
  First live probe FAILED usefully: the LLM re-emitted the focused circle blown
  up to the full 100x100 box (r=50 touching every edge), and a 45° tangent of
  the emitted length fits nowhere in the box — `_slide_into_box` returned None
  and the uncorrected center-chord passed through. Fix: `_shorten_into_box()`
  in `relations.py` — when sliding can't fit, clip the tangent segment to the
  box chord around the touch point (min visible length 5 units). **Tangency is
  the meaning; the length is incidental.** Re-probe: distance center→line =
  22.03 vs r=22 — exact within rounding, 45° direction preserved, in-box.
  115 tests, ruff+mypy clean. ⚠️ Adherence gap logged for D2/D4: the model
  does NOT copy existing parts verbatim on MODIFY (40x30 circle came back
  50x50, then 100x100) despite the prompt demanding it — add "copy verbatim"
  to the D4 adherence eval and the D2 prompt set.
- **Exploded-view diagnosis + model/dataset research — DONE (plan.md §11 added).**
  Why 3D/intricate requests render as flat part layouts — ranked, code-verified:
  1. prompt's decompose recipe + ALL few-shot examples place parts in disjoint
  regions (llm.py:69, Example B house, Example D thruster column) — an
  exploded-view algorithm; 2. painter's-algorithm z-order never explained +
  default `fill: null` → model avoids overlap (transparent overlaps look like
  crossed wireframes); 3. 3D guidance is cube-only (llm.py:62); 4. routing bug:
  `_unexplained_words` filters `len(t) > 2` so "3d" is invisible — "a 3D box"
  → rules CREATE flat rect conf 0.85, LLM never consulted (classify.py:383);
  5. flat QuickDraw few-shots actively fight 3D requests; 6. all-or-nothing
  pydantic validation + no `max_tokens` → ambitious output silently NOOPs
  (llm.py:184-194) — selection pressure for timid flat drawings. The IR itself
  CAN do occlusion (implicit paint order — the isometric cube proves it);
  missing: rotation, nesting, gradients; validators reject rather than clamp.
  Model research (June 2026): SVGBench = Opus 4.6 75.6%, GPT-5.2 74.4%; best
  open drawers GLM-5 70.3% / Kimi K2.5; only Groq (~450 tok/s) and Cerebras
  (~3k tok/s) fit the live budget at 1.5k output tokens → tiered strategy
  (plan.md §11). No isometric dataset exists on HF; TU-Berlin is the one
  ship-safe candidate (verify CC-BY-4.0); SketchGraphs murky (Onshape ToU).
  Techniques validated by literature: render→VLM-critique→repair
  (Render-in-the-Loop '26, IntroSVG '26), scene-graph-then-geometry planning,
  models repair vector code better than they generate it (SVGenius).
- **Exact geometric relations (tangency) — BUILT, checks green, UNCOMMITTED;
  live re-probe pending.** A live "line tangential to the circle" came back 7
  units off — LLMs don't do arithmetic. Pattern established: **model proposes,
  code disposes.**
  - `pipeline/relations.py` (new) — `snap_relations()`: pure function; any
    straight 2-point path in the emitted group is translated along its own
    normal to exact tangency with the group's circle (direction/length/side
    preserved); slides along the line direction if the shift exits the 0..100
    box; passes through anything it can't confidently fix. Surgical by design —
    perpendicular/parallel/concentric stay prompt-guided until a live failure
    motivates snapping them.
  - `pipeline/llm.py` — `payload_to_op` snaps geometry via `snap_relations`;
    prompt gains the GEOMETRIC RELATIONS rules (tangent touch-point math,
    perpendicular/parallel/concentric/inscribed, y-grows-downward angle note)
    + worked Example F (circle + exact tangent line as MODIFY).
  - `pipeline/classify.py` — `_RELATION_RE`: ONE relation word (tangent,
    perpendicular, parallel, concentric, inscribed, bisect, degrees, …) makes
    a rules match hazy (cap 0.5) — the relation IS the meaning; rules can only
    place shapes side-by-side.
  - `tests/test_scene_extension.py` +84 lines: snapping math (both sides,
    already-tangent no-op, box-slide, non-group/non-circle pass-through),
    relation-word escalation, Example F pinned through validation + renderer.
  - **114 tests, ruff + mypy clean.** Pytest-hang note: the "hung suite" bit
    twice more this session — both times stale zombies; after pkill the suite
    runs in 0.43 s. The TestClient deadlock theory remains unconfirmed.
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
-1. **Human browser confirm of §15 (the one thing the agent can't observe).**
   Servers live: backend :8000 (restarted with compose) and Vite :5173.
   Branch: ui-zoom-adaptive-canvas (uncommitted — commit after confirm).
   Check:
   - Zoom out with ctrl-wheel (or pinch on mobile) — map zooms about the cursor.
   - Pan by dragging — map pans, cards not clipped at edges.
   - Press Fit — map fits all cards into view.
   - Toggle Follow — enable it, say an utterance that creates a child: the
     focused card should scroll into view; drag-pan while it's auto-following
     and confirm follow pauses while gesturing.
   - **Uniform tighter spacing** — a 4-hop chain should look compact, not exploding.
   - **Compose:** restart backend if needed, say "draw a horse" then "draw a box
     above the horse" — the box should land as a child of the horse node with
     a compose-MODIFY, not a standalone new node.
   Then commit and merge ui-zoom-adaptive-canvas → main.
0. [x] **D3 — deterministic isometric projection — DONE (2026-06-13).** See §3
   top entry. `domain/isometric.py` + LLM `solids` payload; eyeball-verified.
1. [x] **D4 part 1 — adherence eval + cheap-model benchmark — DONE (2026-06-13).**
   See §3 top. `quorum/eval/adherence.py` (pure scorer) + `scripts/eval_adherence.py`
   (annotated set + keyless self-test) + OpenRouter backend; benchmark table +
   findings + 5 review fixes recorded. **D3 live-probe also DONE** (ling-2.6-flash
   emits `solids`; coherent isometric engine eyeballed).
1b. [x] **Detection accuracy + speed — DONE & live-verified (2026-06-14).** See
   §3 top + commit 63e917c. Focus-on-create fix, deterministic directional
   placement snapping, definite-only compose target, and the gemini-2.5-flash-lite
   model swap (~2 s). User goal "placement ~20%→85%, new shapes focus, faster" met.
2. [x] **Vector DB (embeddings tier) — DONE & live-verified (2026-06-14).** See
   §3 top + commit c344d1e. Semantic few-shot references + near-duplicate CREATE
   cache; gated (`QUORUM_RETRIEVAL_BACKEND=local`, default off). Follow-ups noted
   in §3 (warm index at startup; persist cache to disk).
3. **D4 part 2 (now OPTIONAL, latency no longer the driver):** gemini-2.5-flash-lite
   is ~2 s, so the escalation tier is only worth it for raw quality on hard
   prompts (stream stage-C output; an even stronger model for 3D/intricate). Gate
   any model change with `eval_adherence.py`. D5 (optional) = VLM-critique→repair.
4. **UX/UI polish — DEFERRED by the user** ("a bit buggy… work on this down the
   road"). Revisit after the vector DB.
5. **Still pending (human-only): §15 browser confirm + merges to main.**
2. [x] **Live-mic review** — DONE (see §3). Finding: needs richer geometry.
3. [x] **Richer geometry — DONE via LLM stage C (tier B).** Stage turned ON
   (Groq) + prompt teaches polygon/path/text; verified live (see §3).
   *Tier A is now DONE too* — §12 R4's named-geometry tier (18 exact shapes,
   0 ms, no LLM round-trip).
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
| 2026-06-11 | Exact geometric relations: **model proposes, code disposes** — `relations.py` snaps tangency deterministically after validation; ONE relation word makes a rules match hazy | A live tangent came back 7 units off; LLMs don't do arithmetic. Snapping preserves the model's intent (direction/side/length) and only fixes the perpendicular offset. Kept surgical: other relations stay prompt-guided until a live failure motivates them |
| 2026-06-11 | The exploded-view fix is a **program (plan.md §11 D1–D5), not a model swap** — prompt/routing/validation first, deterministic isometric projection (D3) as the centerpiece | Diagnosis traced 5 of 6 ranked root causes to our own code (decompose recipe, untaught z-order, cube-only 3D guidance, invisible "3d" token, all-or-nothing validation). Asking an LLM to do projection math token-by-token is the model-bound part — so the code does the projection, the LLM only places axis-aligned 3D primitives |
| 2026-06-11 | Model upgrades are **tiered** (fast Groq/Cerebras tier + escalation Gemini Flash/Sonnet tier + offline batch tier), gated on OUR adherence eval (D4) | At ~1.5k output tokens only Groq/Cerebras-class hosts fit the 1–2 s live budget; frontier models (SVGBench leaders) take 12–30 s — fine for an escalation tier with streaming, not for the default. Never swap defaults on benchmarks we didn't run (the 70b quota lesson) |
| 2026-06-12 | Tangency snap **shortens** the line to the box chord around the touch point when sliding can't fit it (`_shorten_into_box`, min 5 units) | Live failure: LLM emitted a box-filling circle; no 45° tangent of the emitted length fits 0..100, so the old pass-through shipped a center chord. Tangency is the meaning; length is incidental |
| 2026-06-12 | LLM output is **repaired, not rejected**: clamp coords pre-validation, salvage groups minus rotten parts, ONE corrective retry with the pydantic error — but domain validators stay strict | All-or-nothing validation selected for timid flat drawings (diagnosis root cause 6). Repair lives in the LLM stage (model proposes, code disposes); the domain contract is unchanged for every other caller |
| 2026-06-12 | 3D escalation = explicit `_3D_INTENT_RE` in the hazy clause, not relaxing the `len(t) > 2` token filter | A targeted regex catches "3-d"/"three dimensional" variants the length filter never could, and doesn't risk flooding the coverage heuristic with short stopword-ish tokens |
| 2026-06-12 | Prompt changes must pass the **eyeball gate**, and edits to a proven prompt are **additive/surgical, never rewrite-and-trim** | D2's first rewrite improved every scalar metric (parts/fills/overlap) while visibly regressing 3 of 10 renders — the metrics hid it. It had dropped proven content (signature-parts examples, orientation rule) and added a self-contradicting 3D rule + a flat "isometric" example. Numbers gate, eyes decide |
| 2026-06-12 | Fused-points repair: split `[[3040]]` → `[[30,40]]` only when the digit split is UNIQUE (both halves 0..100, no leading zeros); otherwise leave for the validator | Live scout-17b drops the comma in coordinate pairs — the engine block was emitted every probe and silently dropped. Guessing ambiguous splits (150 → 1\|50 or 15\|0?) would corrupt geometry; refusing keeps repair trustworthy |
| 2026-06-12 | Extend-intent escalation: ADD verbs/placement words with a focus make any rules match hazy; bare-modifier MODIFY (branch 7) goes hazy on even ONE unexplained word | Live test: "add a red sphere inside" was hijacked by the modifier-fold branch at 0.70 — composing INTO a scene is structurally beyond rules. "make it bigger" (0 unexplained, no extend words) keeps the fast path |
| 2026-06-12 | Containment is snapped deterministically (`_snap_all_inside`): new parts outside the old parts' union box get centered into it (shrunk only if oversized); `payload_to_op` carries `focus_geometry` to tell old from new | Same model-proposes-code-disposes pattern as tangency: "inside" IS the meaning; the LLM supplies the part, the code guarantees the containment |
| 2026-06-12 | Per-test `pytest-timeout` 30 s with `timeout_method=thread` | Finally sampled the live deadlock: main thread in TestClient portal cond-wait + anyio loop thread in kevent — confirmed at C level. A thread-method timeout converts the next infinite hang into a 30 s failure WITH every thread's Python stack (the missing diagnostic) |
| 2026-06-12 | **Iteration-as-branch**: a MODIFY that effects a change creates a CHILD node (focus moves to it); no-change MODIFYs are no-ops; focus's ancestor chain exempt from auto-prune, cap 8→16 | User wants a mind map: "make the cat orange" must keep the original cat visible and extend outward. Replay untouched (snapshot-driven fold); the trunk must never be pruned out from under the focused tip |
| 2026-06-12 | Recolor is deterministic: `retint` = target hue+sat at `L' = 0.7·L_orig + 0.3·L_target` (fills AND strokes when fill set; exact color when stroke-only) | "Make the cube red" must keep the three-face shading — preserving relative lightness IS the shading; the 0.3 pull keeps near-white faces from washing out. LLMs don't do color arithmetic; this is the tangency pattern applied to color |
| 2026-06-12 | Nodes carry a concept `label` (template name / shape word / LLM-supplied, with template-match fallback); "the cube"-style references resolve by label (exact → plural → 3-char stem, ≥4-char words); label-matched tokens count as EXPLAINED in the hazy calc | "I want the cube to be red" went hazy→LLM→flat redraw because resolution was ShapeKind-only and "cube" looked unexplained. Label resolution keeps appearance follow-ups on the 0-ms fast path. Watch: stem match can over-pair rare labels ("card"/"cart"); newest-wins bounds it |
| 2026-06-12 | Named geometric shapes are CODE generators (`domain/shapes.py`, 18 words → exact polygons/paths) at rules conf 0.85, not templates and not LLM work | A rhombus is math, not taste — same reasoning as the computed isometric bank. Works in every backend config (template stage only exists when LLM is on) and composes with the modifier fold |
| 2026-06-12 | LLM RESTYLE rule: appearance-only follow-ups re-emit `focus_geometry` byte-identical, changing only stroke/fill/fill_style; detail parts (stripes) = several thin shapes near edges, never blocks over features | First eyeball probe drew "stripes" as one brown block over the cat's eyes — the quality bar is structural preservation + unobtrusive detail. Color-only cases never reach the LLM at all (label resolution handles them) |
| 2026-06-12 | Scene edits = **set/add/remove PATCH against named parts** (LLM emits only the delta; `apply_patch` composes; full re-emission demoted to restructures-only) | Research (JSON Whisperer '25, SVGenius/SVGEditBench, aider): models pick edit targets reliably but fail at verbatim re-serialization — our live copy-verbatim failures confirm it. Live result: add-eyes 1.2 s with originals byte-identical vs ~4-5 s re-emission. Parts addressed BY NAME only (index arithmetic is the #1 patch failure mode) |
| 2026-06-12 | Spatial part qualifiers (left/right/top/bottom/biggest/widest/first/…) resolve in CODE from geometry; the LLM only ever names the role ("eye") | LLMs don't do arithmetic — same principle as tangency/recolor/extrusion. Singular ambiguous ("one eye") = first match, user corrects |
| 2026-06-12 | Part-scoped fallback INVERSION: an unresolvable determiner+noun reference makes the bare-modifier fallback a hazy NOOP, never a whole-scene MODIFY | Live: dead-LLM fallback scaled the WHOLE mouse on "make the left eye bigger". Wrong-nothing beats wrong-everything |
| 2026-06-12 | 2D→3D conversion = deterministic **oblique-cabinet extrusion** (front face true shape, 45° up-right half-scale depth, shading = three lightness bands of the shape's own hue) | A true front face is exactly what 30° isometric cannot give; extrusion is math, not taste. The isometric bank stays for canonical solids; extrude handles arbitrary silhouettes in-chain |
| 2026-06-12 | MODIFY ops carrying pre-baked replacement geometry must emit `modifiers=[]` | The engine folds op.modifiers onto replacement geometry — passing both double-applies (live: whole mouse ×1.3 + eye ×1.69). Pinned by a classifier+engine INTEGRATION test; op-level asserts can't see downstream double-folds |
| 2026-06-12 | Geometry tests must pin the SIDE/direction, not just counts (extrude regression test: bands protrude up-right for both windings) | The trapezoid-form shoelace has the opposite sign of the cross-product form — the winding flip extruded the BACK edges while every count-based assert stayed green; only the eyeball caught it |
| 2026-06-12 | Voice undo = meta-command branch 0 in the rules stage (EXEMPT from hazy caps) emitting `OpType.UNDO`; engine moves focus to `parent_ids[0]`; the abandoned child stays ACTIVE; root focus = no-op | The phrase IS the meaning — filler words must not make "never mind, go back" hazy, and undo must never depend on the LLM (quota-immune). User confirmed: "zoom back out" = go back, and history stays visible (no prune/fade). Replay safe for free: FOCUS_CHANGED already folds, statuses re-derive from final focus |
| 2026-06-12 | Undo guard: "go back to the <X>" where X resolves to a label/shape falls through to FOCUS resolution; parent-chain undo over focus-history undo | "go back to the cat" is a directed focus move, not an undo. Parent-chain semantics need zero new replayed state; focus-history undo (handles cross-root hops) deferred until live use demands it |
| 2026-06-12 | e2e harness: a LIVE-but-quota-dead LLM = loud SKIP of the LLM-scene step (15 s timeout-tolerant), never a hang | A 429-dead LLM falls back to NOOP → no diff is broadcast → the script hung at the rocket step and the LLM-FREE steps after it never ran. Mock-skip already existed; quota-dead is a distinct environment state. Assertions unchanged when a diff arrives |
| 2026-06-12 | Viewport follow scrolls to the focused card's LAYOUT coords, not its rendered box | Cards animate left/top over 0.45 s — `scrollIntoView` would chase a mid-transition position; the layout map already holds the final coordinates |
| 2026-06-13 | Radial mind-map uses a **UNIFORM ring step** (`kidRadius = R`, one card + ~60px gap); never compound radius with depth | `childDepth*R` made each successive iteration hop's edge longer than the last (0,R,3R,7R) — "line across too big" (user report). Uniform step + zoom/fit handles density. |
| 2026-06-13 | Canvas pan/zoom is **hand-rolled (zero deps)** and is LOCAL VIEW state (RULES.md §4 — not authoritative session state); imperative pointer/wheel listeners with `{passive:false}` | React's synthetic `onWheel` is passive so `preventDefault` can't be called on it; a local transform is not session state and must not flow through the engine. No external pan/zoom library — avoids bundle bloat and dependency lock-in. |
| 2026-06-13 | **Compose-onto-existing** = DETERMINISTIC placement (code proposes AND disposes), conf-0.8 rules fast path, modifiers=[] pre-baked, targets the RESOLVED named node (not just focus); over-trigger guards keep plain/multi-shape create intact | Quota-resilient (Groq often 429-dead) and "a box above the horse" must extend the horse, not spawn a standalone node. Deterministic `place_relative` matches the model-proposes-code-disposes pattern used throughout. |
| 2026-06-13 | **D3 true-3D = project to a flat GROUP in the DOMAIN, not in the renderer** (plan.md §11 D3 said "renderer does it"). LLM emits transient `solids` (box/cylinder/wedge, x,y,z,w,d,h); `domain/isometric.project_solids` does the 30° projection→shading→cull→z-sort→fit, producing polygon/ellipse/path parts | Both renderers + engine/replay/wire already handle GROUPs (the extrude.py / make_isometric.py precedent), so a domain transform = ZERO renderer/client changes and the projection written ONCE. Plan's spirit (deterministic, pure, cached, LLM does no math) fully honored; only the layer differs. Flagged per CLAUDE.md §7 — does NOT reorder the queue |
| 2026-06-13 | **Projected 3D bypasses `snap_relations`** (`from_solids` flag in `payload_to_op`) | A 3D utterance with "inside/within/in it" made `_snap_all_inside` treat the cylinder's top-cap (the last part) as "newly added" and yank it into the body — silent corruption. The projection is already exact; relation-snapping is for LLM-placed parts, not code-projected ones (adversarial-review HIGH find) |
| 2026-06-13 | **Isometric circle projects with a √2 factor**: screen semi-axes = r·√2·cos30 and r·√2·sin30 | The projected horizontal circle's extrema are at cos t ∓ sin t = ±√2; dropping √2 (first cut did) made every cylinder 29% too narrow. Math, not taste — the same "code does the arithmetic" principle as tangency/extrusion (adversarial-review MED find, pinned by test) |
| 2026-06-13 | **OpenRouter is an OpenAI-compatible LLM backend** (`Backend.OPENROUTER`), a config swap not a rewrite; it is the ACTIVE backend (Groq free tier 429-dead). User directive "use the cheapest model" → default `inclusionai/ling-2.6-flash` | Same 12-factor seam as Groq/Ollama (RULES.md §5): one `_send` path, per-backend URL + optional OpenRouter headers. A paid key with $10 credit removes the Groq quota fragility that broke §13/§14 live probes |
| 2026-06-13 | **Instruction-adherence is scored by a pure, deterministic, no-VLM scorer** (`quorum/eval/adherence.py`): count/color (HSL hue)/coherence (union-find)/relations (bbox)/solids3d (shading signature OR `solids` path); `overall` = mean of APPLICABLE dims; a keyless `--self-test` gates the harness itself | "Model proposes, code disposes" applied to evaluation: the model draws, the code measures. No vision model keeps it fast, free, deterministic and CI-able. The harness — not the model — is the thing we must trust, so it is adversarially reviewed and unit-tested (85 tests) before any number is believed |
| 2026-06-13 | **Adherence scoring guards (from the adversarial review):** coherence EXCLUDES near-full-canvas background parts (they'd bridge an exploded foreground); count SKIPS the `solids` path (projection face-decomposition multiplies role names); `overall` is conditioned on VALID rows (dim columns already are); near-white fills don't count as shaded 3D faces | A benchmark is only as trustworthy as its metric. Each guard closes a way a model could score high without adhering (or low despite adhering). Pinned by regression tests so the gaming vector can't silently return |
| 2026-06-13 | **Do NOT swap the production default on this benchmark.** Cheap OpenRouter routes measured 30–72 s p95 (escalation-tier latency, not the ≤2 s fast tier); qwen3-235b "won" on adherence (1.0) but had a 429-exhausted NOOP row and the slowest latency | Reinforces the 2026-06-11 Groq-quota lesson: rate-limit-corrupted rows are not quality signals, and a benchmark we ran on slow/throttled routes can't promote a live default. The benchmark INFORMS the D4-part-2 escalation tier; it does not auto-promote |
| 2026-06-14 | **Every CREATE takes focus** (was: only the first node ever, `first = _focus_id is None`); the previous focus steps back to ACTIVE | Live bug: a new shape kept editing the OLD shape because focus never moved off the first node, so follow-ups ("make it bigger") hit the stale node. Mirrors `_modify`'s focus move; demotion is in-memory and replay re-derives statuses from the final focus (no new event needed). The latest contribution is what you want to iterate on |
| 2026-06-14 | **Directional placement is snapped deterministically** (`relations._snap_all_directional`: above/below/left/right/beside translate the new part to the stated side of the host with a small gap); "on top of" stays the compose on_top (overlap) path | Placement was ~20% accurate because only inside/tangent were snapped — every directional relation was raw LLM guesswork. Same "model proposes, code disposes" as inside/tangent: the direction is the meaning, the exact coords are incidental. Shares `_partition_new` (new vs old part identification) with the inside snap |
| 2026-06-14 | **Default model swapped to `google/gemini-2.5-flash-lite`** on a CLEAN bake-off (0 429s, complete data): ~2 s/call AND strong on color/placement/3D | NOT a contradiction of the 2026-06-13 "don't swap on a corrupted benchmark" rule — that barred swapping on slow, rate-limited, NOOP-corrupted rows. This bake-off was clean and the model is both fast and accurate, fixing the latency AND the color/relations weakness at once. `gpt-5-nano` rejected (reasoning model: 65 s, returns null content). `eval_adherence.py` remains the gate for any future swap |
| 2026-06-14 | **Embeddings tier is gated + a process-wide singleton.** Default `QUORUM_RETRIEVAL_BACKEND=mock` (off, keyword refs, no torch); `local` enables semantic refs + the near-duplicate cache. `get_retrieval` is lru_cached so all rooms share ONE embedder+index | `build_classifier` runs per room — a per-instance embedder would load the model + re-embed 345 templates N times (memory + latency blowup). Gating keeps CI/basic checkouts torch-free. The result cache reuses CREATEs ONLY (non-destructive) on cosine ≥ 0.94 + no modify markers, so a near-duplicate can't corrupt a context-dependent edit |

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
| Classify (fast) | <0.2 s | **0.04 ms / 0.07 ms** | rules stage incl. scenes/colors + §12 label resolution & named shapes + §13 part resolution & extrusion checks + §14 undo branch 0 + §15 compose branch 5b (~0 ms) |
| Classify (LLM) | <1.5 s local / <0.8 s Groq | **ACTIVE: `google/gemini-2.5-flash-lite` via OpenRouter ≈ 1.6–2.7 s/call** (bake-off 2026-06-14; one 8.6 s outlier). Prior cheap 'ling' was 5.8–14.8 s p50 / 30–72 s p95 (incl. 429 waits) — replaced | ON. gemini-2.5-flash-lite picked for fast AND accurate (color/placement/3D). gpt-5-nano rejected (reasoning model: 65 s, null content). Patch edits ~3x faster than full re-emission; most follow-ups (recolor/size/extrude/compose/undo) never reach the LLM |
| Render | <0.5 s | **~0.00 ms / 0.01 ms** | deterministic + LRU-cached (cache hits sub-µs) |
| Engine apply | (internal) | **0.05 ms / 0.06 ms** | DAG mutation + event append; modify creates + renders a child node (§12); §14 undo = focus move only |
| **End-to-end (server fast path)** | **<5 s** | **0.093 ms / 0.129 ms** | classify+engine+render. D3 AND D4 add NOTHING to the fast path — D4 is offline eval tooling (`quorum/eval`, `scripts/eval_adherence.py`) plus a default-OFF `record_diagnostics` hook on the LLM stage; the `solids` projection still lives in the LLM stage. p95 0.132→0.129 ms is run-to-run variance; ~38,000x under budget |

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
