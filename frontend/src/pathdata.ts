// Constrained SVG path data — the TypeScript mirror of backend/quorum/domain/
// pathdata.py. The server validates `d` before it ever reaches us (absolute
// uppercase commands only, 0..100 box), so this port only needs to TOKENIZE
// and REMAP coordinates: rough.js redraws path data point-by-point and an SVG
// `transform` would also scale stroke width + wobble, so we map the numbers
// through the viewport ourselves (see the Python module's docstring).
//
// Keep the slot tables in lockstep with pathdata.py's _X_SLOTS/_Y_SLOTS/_R_SLOTS.

const ARITY: Record<string, number> = { M: 2, L: 2, H: 1, V: 1, C: 6, Q: 4, A: 7, Z: 0 };
const X_SLOTS: Record<string, number[]> = { M: [0], L: [0], H: [0], C: [0, 2, 4], Q: [0, 2], A: [5] };
const Y_SLOTS: Record<string, number[]> = { M: [1], L: [1], V: [0], C: [1, 3, 5], Q: [1, 3], A: [6] };
const R_SLOTS: Record<string, number[]> = { A: [0, 1] }; // arc rx, ry are lengths

const TOKEN_RE = /[A-DF-Za-df-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g;

type Command = [string, number[]];

// Tolerant tokenizer: assumes server-validated input. Normalizes implicit
// linetos after a moveto, exactly like the Python parser.
function parse(d: string): Command[] {
  const tokens = d.match(TOKEN_RE) ?? [];
  const commands: Command[] = [];
  let i = 0;
  let current: string | null = null;
  while (i < tokens.length) {
    const tok = tokens[i];
    if (/^[A-Za-z]$/.test(tok)) {
      current = tok.toUpperCase();
      i += 1;
      if (current === "Z") {
        commands.push(["Z", []]);
        current = null;
        continue;
      }
    }
    if (current === null) break;
    const arity = ARITY[current] ?? 0;
    const values = tokens.slice(i, i + arity).map(Number);
    if (values.length < arity) break;
    commands.push([current, values]);
    if (current === "M") current = "L";
    i += arity;
  }
  return commands;
}

/** Map every coordinate of `d` through viewport functions (positions vs lengths). */
export function transform(
  d: string,
  fx: (x: number) => number,
  fy: (y: number) => number,
  fr: (r: number) => number,
): string {
  const out: string[] = [];
  for (const [cmd, values] of parse(d)) {
    const vals = values.slice();
    for (const idx of X_SLOTS[cmd] ?? []) vals[idx] = fx(vals[idx]);
    for (const idx of Y_SLOTS[cmd] ?? []) vals[idx] = fy(vals[idx]);
    for (const idx of R_SLOTS[cmd] ?? []) vals[idx] = fr(vals[idx]);
    out.push(vals.length ? `${cmd} ${vals.map((v) => +v.toFixed(3)).join(" ")}` : cmd);
  }
  return out.join(" ");
}
