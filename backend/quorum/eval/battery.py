"""The refinement-loop prompt battery (tuning + held-out split).

The autonomous drawing-quality refinement loop optimizes the pure adherence
scorer (:mod:`quorum.eval.adherence`) measured live through the real stage-C
:class:`~quorum.pipeline.llm.LLMClassifier`. To avoid Goodhart overfitting, the
battery is split:

  * ``TUNING``  — the loop MAY inspect these prompts/scores and tune code
                  (prompt, salvage, deterministic transforms) against them.
  * ``HELDOUT`` — the loop NEVER tunes against these. They exist only to
                  confirm a fix GENERALIZES and to judge the stop condition
                  (held-out strict-overall >= target with zero regressions).

The orchestrator owns this file; the code-fixing subagents must not edit it
(that would let the optimizer design its own test). Grow both sets over time
from documented weak cases — a bigger, fresher battery is the primary defense
against tuning to a fixed handful of prompts.

Each prompt is a single-shot CREATE (no follow-up dependency), so an empty
``ClassifierContext`` is correct and the LLM stage is isolated.

Fitness note: the loop drives **strict-overall** = mean of per-prompt overall
counting an INVALID (no-geometry) row as 0.0 — unlike the D4 table's ``overall``
which is conditional on a valid drawing and hides outright failures.
"""

from __future__ import annotations

from quorum.eval.adherence import Expectation, Relation

# --------------------------------------------------------------------------- #
# TUNING set — the loop optimizes against these.
# --------------------------------------------------------------------------- #
TUNING: list[tuple[str, Expectation]] = [
    # -- 3D / solids cluster (the documented weak spot) --
    ("a wedge ramp in 3D",
     Expectation(expect_3d=True, min_parts=2)),
    ("a 3D cube",
     Expectation(expect_3d=True, min_parts=3)),
    ("a 3D engine with three pistons",
     Expectation(expect_3d=True, min_parts=4)),
    ("a 3D cylinder standing upright",
     Expectation(expect_3d=True, min_parts=2)),
    # -- count fidelity cluster --
    ("a house with a door and two windows",
     Expectation(counts={"window": 2, "door": 1}, min_parts=4)),
    ("a robot with an antenna and two wheels",
     Expectation(counts={"wheel": 2, "antenna": 1}, min_parts=4)),
    ("a funnel turned on its side with five thrusters",
     Expectation(counts={"thruster": 5}, min_parts=6)),
    ("a coffee mug with a handle, colored in",
     Expectation(counts={"handle": 1}, colored_in=True, min_parts=3)),
    # -- color cluster --
    ("a simple car, colored blue",
     Expectation(colors=("blue",), colored_in=True, min_parts=3)),
    ("a snowman wearing a red scarf and a blue hat",
     Expectation(counts={"scarf": 1, "hat": 1}, colors=("red", "blue"), min_parts=4)),
    # -- relation cluster --
    ("a blue circle inside a red square",
     Expectation(colors=("blue", "red"),
                 relations=(Relation("inside", "circle", "square"),), min_parts=2)),
    ("a green triangle above a blue square",
     Expectation(colors=("green", "blue"),
                 relations=(Relation("above", "triangle", "square"),), min_parts=2)),
]

# --------------------------------------------------------------------------- #
# HELD-OUT set — never tuned against; judges generalization + the stop gate.
# --------------------------------------------------------------------------- #
HELDOUT: list[tuple[str, Expectation]] = [
    # -- 3D / solids generalization (wedge synonyms, sphere, stacked boxes) --
    ("a 3D ramp",
     Expectation(expect_3d=True, min_parts=2)),
    ("a triangular prism in 3D",
     Expectation(expect_3d=True, min_parts=2)),
    ("a 3D sphere",
     Expectation(expect_3d=True, min_parts=1)),
    ("a 3D box stacked on top of another box",
     Expectation(expect_3d=True, min_parts=6)),
    # -- count fidelity generalization --
    ("a face with two eyes and a nose",
     Expectation(counts={"eye": 2, "nose": 1}, min_parts=3)),
    ("a car with four wheels",
     Expectation(counts={"wheel": 4}, min_parts=5)),
    ("a robot head with two antennas",
     Expectation(counts={"antenna": 2}, min_parts=3)),
    # -- color generalization --
    ("a five-pointed star colored yellow",
     Expectation(colors=("yellow",), colored_in=True, min_parts=1)),
    ("a coffee cup with a handle, colored green",
     Expectation(counts={"handle": 1}, colors=("green",), colored_in=True, min_parts=3)),
    # -- relation generalization --
    ("a green triangle to the left of a red square",
     Expectation(colors=("green", "red"),
                 relations=(Relation("beside", "triangle", "square"),), min_parts=2)),
]

# The full battery (tuning first, then held-out).
ALL: list[tuple[str, Expectation]] = TUNING + HELDOUT

SETS: dict[str, list[tuple[str, Expectation]]] = {
    "tuning": TUNING,
    "heldout": HELDOUT,
    "all": ALL,
}
