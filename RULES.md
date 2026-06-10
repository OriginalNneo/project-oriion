# RULES.md — Build Rules & Check Cadence

> Non-negotiables for building Quorum. `CLAUDE.md` says *how to work day to day*;
> this file is the *contract*. If a rule and a deadline conflict, the rule wins —
> raise it for review instead of breaking it.

---

## 1. The five standing rules
1. **Efficiency first.** Every pipeline stage has a latency budget (`plan.md`
   §5). A change that blows the budget is not "done" — it's a regression.
2. **Measure, don't guess.** Once a thing *can* be measured, the latency ledger
   in `context.md` carries real numbers, never estimates.
3. **Segment, then check.** Build in small segments; each one passes its checks
   (§3) before the next begins.
4. **Keep the docs live.** Update `context.md` after every segment — status,
   decisions, latency ledger. Stale context is worse than none.
5. **Async, never block.** No synchronous I/O on an async path. N speakers must
   process concurrently, not in a queue. This is the difference between the
   product working and not working.

## 2. Definition of "done" (per segment)
A segment is done only when **all** hold:
- [ ] Works end to end for its scope (demoable).
- [ ] Behind a clean interface; swappable; doesn't reach into other stages.
- [ ] Unit tests pass; integration test for the loop it participates in passes.
- [ ] **Latency measured** and within budget (logged to the ledger).
- [ ] `context.md` updated (status + any decision + ledger entry).
- [ ] Lint + type check clean.

## 3. Check cadence — run these, in segments
Run after each segment (and gate CI on them in Phase 5):
1. **Lint/format** — `ruff` (py), eslint/prettier (ts).
2. **Type** — `mypy` (py), `tsc` (ts).
3. **Unit** — the stage's own tests.
4. **Integration** — the loop the stage sits in still works.
5. **Latency benchmark** — the harness times each stage and the end-to-end
   common case; fail if over budget. **This is a first-class test, not optional.**
6. **Concurrency smoke** — simulate N concurrent speakers; confirm they process
   in parallel (no serial queueing) and nothing deadlocks.

Review checkpoints (human-in-the-loop): at the end of **each phase** in
`plan.md` §6, stop and review before starting the next phase.

## 4. Frontend rules
- Participant view and Display view share one codebase, differ by role.
- All server comms over the single WebSocket; no ad-hoc fetch side-channels for
  realtime data.
- Render is a pure function of the broadcast state diff — the client holds no
  authoritative state, only a view of it.
- No `localStorage`/`sessionStorage` reliance for session truth — the server is
  the source of truth.
- Show the user what the system *heard* (transcript) and offer correction.

## 5. Backend rules
- FastAPI async throughout; uvicorn workers.
- Each pipeline stage = a module behind a `Protocol`, chosen by env var
  (`STT_BACKEND`, `LLM_BACKEND`, …) — 12-factor config.
- The Design State Engine is the **only** writer of session state. Everything
  else produces DesignOps; the engine applies them.
- Event log is append-only (enables replay/undo; don't mutate past events).
- Gateways stay stateless; authoritative state is in the engine (memory now,
  Redis at Phase 5).

## 6. Efficiency / benchmarking rules
- Maintain a repeatable latency harness from Phase 1 onward (record fixed sample
  utterances → run the loop → log per-stage timings).
- Track p50 **and** p95 — the tail is what makes conversation feel laggy.
- Prefer the cascade fast path; only escalate to the LLM above the confidence
  threshold; use speculative parallelism (`plan.md` §5) for expected-LLM cases.
- Cache deterministic SVG renders for repeated geometry.
- Any latency regression > 20% on a stage blocks the segment until explained or
  fixed.

## 7. Documentation rules
- `plan.md` — change only when the *design intent* changes (rare). Log the change.
- `context.md` — update every segment (the living state).
- `CLAUDE.md` / `RULES.md` — change only by explicit review.
- If memory MCP is on, mirror every logged decision into the memory graph
  (`CLAUDE.md` §5) so the two stay consistent.
