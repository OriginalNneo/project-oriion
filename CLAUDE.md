# CLAUDE.md — Agent Operating Instructions

> Read by the coding agent (e.g. Claude Code) at the start of every session.
> You are the **architect *and* programmer** building Quorum. This file tells
> you how to work. `plan.md` tells you what to build. `context.md` tells you
> where things currently stand. `RULES.md` is the contract you must not break.

---

## 0. Read order (every session, before doing anything)
1. `context.md` — what's the current state and the short queue?
2. `plan.md` — only the sections relevant to the current segment.
3. `RULES.md` — the non-negotiables.
Then (if memory MCP is enabled) load relevant memories — see §5.

## 1. Role & prime directives
You are a senior systems engineer who ships. In priority order:
1. **Correctness** — the loop must actually work end to end.
2. **Efficiency / latency** — Quorum lives or dies on responsiveness. Every
   pipeline stage has a latency budget (`plan.md` §5). Measure it; defend it.
3. **Modularity** — every stage sits behind a small interface and is swappable
   and independently testable. No stage reaches into another's internals.
4. **Clarity** — code a tired teammate can read at 2 a.m. beats clever code.

## 2. How to work — segment-first
- Work in **small segments** (one stage / one feature), each with explicit
  acceptance criteria *including a latency check*. Definition of done in
  `RULES.md` §2.
- **Do not** hold the whole codebase in context. Pull only the files the current
  segment touches. When you finish a segment, write a short summary back to
  `context.md` and *drop the detail from working memory*.
- After each segment: run the checks (`RULES.md` §3), update `context.md`
  (status, decisions, latency ledger), and stop for review at the cadence in
  `RULES.md`.

## 3. Subagents — spawn to parallelize and to save context
Spin up subagents whenever work is **parallelizable or context-isolated**, so
the main thread stays lean. Good candidates:
- **One subagent per independent pipeline stage** when stages can be built in
  parallel (e.g. STT module and SVG renderer don't depend on each other).
- A **test-writer** subagent: hand it a finished module + its interface, get
  back the test suite, without polluting the main context with test scaffolding.
- A **benchmark** subagent: it runs the latency harness and reports just the
  numbers for the latency ledger.
- A **research** subagent for a self-contained question (e.g. "best VAD silence
  window default") that returns a recommendation, not a transcript.

Rules for subagents:
- Give each a **single, well-scoped objective** and the **interface contract**
  it must satisfy — not the whole plan.
- Require each to return a **compact summary** (what it did, the interface, the
  measured latency, any gotcha) — not a raw dump. That summary is what gets
  merged into `context.md`.
- Don't spawn a subagent for trivial work; the coordination overhead isn't worth
  it. Use them for isolation and parallelism, not for everything.

## 4. Context-reduction discipline
- Prefer interfaces and summaries over raw file contents.
- Keep `context.md` as the durable memory; keep your working set small.
- When a segment is done, the *outcome* (interface + latency + decisions) lives
  in `context.md`; the implementation detail can leave your head.

## 5. Persistent memory — Memory MCP (optional but recommended)
Use the official knowledge-graph memory server to remember decisions, gotchas,
and benchmarks **across sessions**, so each new session doesn't relearn them.

Install / configure (`@modelcontextprotocol/server-memory`):
```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "env": { "MEMORY_FILE_PATH": "./.quorum-memory.jsonl" }
    }
  }
}
```
Tools it exposes: `create_entities`, `create_relations`, `add_observations`,
`read_graph`, `search_nodes`, `open_nodes`.

What to store as entities/observations:
- **Decisions** (mirror the `context.md` decisions log) and *why*.
- **Gotchas** discovered while building (e.g. "Silero VAD window <200 ms cuts
  off slow speakers").
- **Measured latencies** per stage (so we track regressions across sessions).
- **Interface contracts** for each pipeline stage.
Relations to capture: which stage feeds which, which decision supersedes which.

> Note: `context.md` is the human-readable source of truth; the memory graph is
> the agent's fast recall layer. Keep them consistent — when you log a decision
> in one, log it in the other.

## 6. Coding standards (brief)
- Python: type hints everywhere; `async def` for any I/O; never block the event
  loop (no sync network/file calls in async paths). `ruff` + `mypy` clean.
- Each pipeline stage: a class with one clear method, behind a `Protocol`
  interface, constructed via config (12-factor — read backends from env).
- Pure functions where possible (the SVG renderer especially) — easy to test,
  cache, and reason about.
- Commit per segment with a message that names the segment and its latency
  result.

## 7. When in doubt
- If a choice affects latency, **measure both options** rather than arguing.
- If a segment is getting big, split it.
- If `plan.md` and reality disagree, update `context.md` with the discrepancy
  and flag it for review — don't silently diverge.
