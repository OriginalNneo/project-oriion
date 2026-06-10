"""Constrained SVG path data — parse, validate, and transform.

PATH geometry lets the LLM stage sketch arbitrary curves (isometric edges,
filleted outlines) while staying inside a contract both renderers can honour:

  * coordinates live in the same abstract 0..100 box as every other primitive;
  * **absolute, uppercase commands only** (M L H V C Q A Z) — relative commands
    would make "scale about the box center" a stateful rewrite, and lowercase
    is the LLM's most common malformation, so we reject rather than guess;
  * bounded size (command/number caps) so a malformed payload can't balloon a
    render.

Renderers do NOT wrap paths in an SVG transform: rough.js redraws path data
point-by-point (a transform would also scale its stroke width and wobble), so
each renderer maps the *numbers* through its own viewport function instead.
That mapping — and "bigger"/"smaller" in :func:`~quorum.domain.geometry.
apply_modifiers` — is what :func:`transform` / :func:`scale_about_center` do.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# Per-command argument count, and which positions are x / y / radii / flags.
# A (arc): rx ry x-axis-rotation large-arc-flag sweep-flag x y
_ARITY: dict[str, int] = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4, "A": 7, "Z": 0}
_X_SLOTS: dict[str, tuple[int, ...]] = {
    "M": (0,),
    "L": (0,),
    "H": (0,),
    "V": (),
    "C": (0, 2, 4),
    "Q": (0, 2),
    "A": (5,),
}
_Y_SLOTS: dict[str, tuple[int, ...]] = {
    "M": (1,),
    "L": (1,),
    "H": (),
    "V": (0,),
    "C": (1, 3, 5),
    "Q": (1, 3),
    "A": (6,),
}
_R_SLOTS: dict[str, tuple[int, ...]] = {"A": (0, 1)}  # rx, ry scale with size

_TOKEN_RE = re.compile(r"[A-DF-Za-df-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

MAX_COMMANDS = 64
MAX_NUMBERS = 200

Command = tuple[str, list[float]]


def parse(d: str) -> list[Command]:
    """Tokenize + validate constrained path data; raise ``ValueError`` if bad.

    Returns the command list ``[("M", [10.0, 20.0]), ...]``. Implicit command
    repetition ("L 1 2 3 4") is normalized into explicit commands.
    """
    tokens = _TOKEN_RE.findall(d)
    if not tokens or "".join(tokens).strip() == "":
        raise ValueError("empty path")
    # Anything the tokenizer skipped must be separators only.
    leftover = _TOKEN_RE.sub("", d)
    if re.search(r"[^\s,]", leftover):
        raise ValueError(f"invalid characters in path: {leftover.strip()[:20]!r}")

    commands: list[Command] = []
    numbers_seen = 0
    i = 0
    current: str | None = None
    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            if tok not in _ARITY:
                raise ValueError(
                    f"unsupported path command {tok!r} (absolute M L H V C Q A Z only)"
                )
            current = tok
            i += 1
            if tok == "Z":
                commands.append(("Z", []))
                current = None
                continue
        if current is None:
            raise ValueError("path data must start with a command letter")
        arity = _ARITY[current]
        args = tokens[i : i + arity]
        if len(args) < arity or any(a.isalpha() for a in args):
            raise ValueError(f"command {current!r} expects {arity} numbers")
        values = [float(a) for a in args]
        numbers_seen += arity
        if numbers_seen > MAX_NUMBERS:
            raise ValueError(f"path too large (> {MAX_NUMBERS} numbers)")
        commands.append((current, values))
        if len(commands) > MAX_COMMANDS:
            raise ValueError(f"path too large (> {MAX_COMMANDS} commands)")
        if current == "M":
            current = "L"  # SVG spec: implicit pairs after a moveto are linetos
        i += arity
    if commands[0][0] != "M":
        raise ValueError("path must start with M")
    return commands


def _serialize(commands: list[Command]) -> str:
    out: list[str] = []
    for cmd, values in commands:
        if values:
            out.append(cmd + " " + " ".join(f"{v:g}" for v in values))
        else:
            out.append(cmd)
    return " ".join(out)


def transform(
    d: str,
    fx: Callable[[float], float],
    fy: Callable[[float], float],
    fr: Callable[[float], float],
) -> str:
    """Map every coordinate of ``d`` through viewport functions.

    ``fx``/``fy`` map x/y positions; ``fr`` maps lengths (arc radii). Arc
    rotation and flags pass through untouched.
    """
    commands = parse(d)
    mapped: list[Command] = []
    for cmd, values in commands:
        vals = list(values)
        for idx in _X_SLOTS.get(cmd, ()):
            vals[idx] = fx(vals[idx])
        for idx in _Y_SLOTS.get(cmd, ()):
            vals[idx] = fy(vals[idx])
        for idx in _R_SLOTS.get(cmd, ()):
            vals[idx] = fr(vals[idx])
        mapped.append((cmd, vals))
    return _serialize(mapped)


def scale_about_center(d: str, factor: float, *, cx: float = 50.0, cy: float = 50.0) -> str:
    """Scale path coordinates about the box center (for "bigger"/"smaller")."""
    return transform(
        d,
        fx=lambda x: min(100.0, max(0.0, cx + (x - cx) * factor)),
        fy=lambda y: min(100.0, max(0.0, cy + (y - cy) * factor)),
        fr=lambda r: max(0.1, r * factor),
    )
