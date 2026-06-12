"""Detection escalation + scene-extension tests (no network).

Two gaps closed here, found at the "draw more complicated things" review:

1. *False-confident rules matches*: "a rocket with a box body and five
   thrusters" contains "box", so the rules stage used to emit a lone rectangle
   at 0.85 and the LLM never saw the utterance. Now ≥2 unexplained content
   words push a matched op below the cascade threshold — the LLM takes it, and
   the rules op remains the dead-LLM fallback.

2. *Scenes couldn't be extended*: "now add five thrusters" needs the LLM to see
   the focused node's current geometry (``ClassifierContext.focus_geometry``)
   and the engine to accept replacement geometry on MODIFY. The prompt's
   Example D (funnel-on-its-side + thrusters) is pinned through validation and
   the reference renderer, like the other worked examples.
"""

from __future__ import annotations

import httpx

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.op import ClassifierContext, DesignOp, OpType
from quorum.engine import DesignStateEngine
from quorum.engine.clock import FixedClock
from quorum.pipeline.classify import CascadeClassifier, RulesClassifier
from quorum.pipeline.llm import LLMClassifier, _LLMPayload, payload_to_op
from quorum.pipeline.renderer import SvgRenderer

from .test_cascade import FakeLLM

_CTX = ClassifierContext()


async def _rules(text: str) -> DesignOp:
    return await RulesClassifier().classify(
        text, speaker_id="a", utterance_id="u1", context=_CTX
    )


# --------------------------------------------------------------------------- #
# 1) coverage heuristic: hazy utterances escalate, plain ones stay fast       #
# --------------------------------------------------------------------------- #
async def test_shape_word_inside_rich_utterance_escalates() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await cascade.classify(
        "a rocket with a box body and five thrusters",
        speaker_id="a",
        utterance_id="u1",
        context=_CTX,
    )
    assert llm.calls == 1  # "rocket"/"thrusters" outweigh the matched "box"
    assert op.source_stage == "llm"


async def test_plain_shape_utterance_stays_on_fast_path() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await cascade.classify(
        "a red circle", speaker_id="a", utterance_id="u1", context=_CTX
    )
    assert llm.calls == 0
    assert op.source_stage == "rules"
    assert op.confidence >= 0.85


async def test_one_unknown_word_does_not_escalate() -> None:
    # A single stray word ("wheel") isn't enough to pay the LLM round-trip.
    op = await _rules("a circle for the wheel")
    assert op.op_type == OpType.CREATE
    assert op.confidence >= 0.85


async def test_hazy_rules_op_is_the_dead_llm_fallback() -> None:
    llm = FakeLLM(op_type=OpType.NOOP, confidence=0.0)  # dead LLM
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await cascade.classify(
        "a rocket with a box body and five thrusters",
        speaker_id="a",
        utterance_id="u1",
        context=_CTX,
    )
    assert llm.calls == 1
    assert op.source_stage == "rules"  # degraded to the basic shape, not dropped
    assert op.op_type == OpType.CREATE


async def test_hazy_scene_composition_escalates_too() -> None:
    op = await _rules("a circle on top of a box for the snowman rocket thing")
    assert op.target_shape == ShapeKind.GROUP
    assert op.confidence < 0.55  # below the default cascade threshold


async def test_geometric_relation_word_escalates() -> None:
    # "line"+"circle" both match the rules shape table, so this used to win as
    # a side-by-side group at 0.75 — but "tangential" IS the meaning. One
    # relation word now outweighs any shape match.
    for text in (
        "a line tangential to a circle",
        "draw a line tangent to the circle",
        "two parallel lines",
        "a square inscribed in a circle",
    ):
        op = await _rules(text)
        assert op.confidence < 0.55, text


async def test_relation_utterance_reaches_llm() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await cascade.classify(
        "a line tangential to a circle", speaker_id="a", utterance_id="u1", context=_CTX
    )
    assert llm.calls == 1
    assert op.source_stage == "llm"


# --------------------------------------------------------------------------- #
# 1b) extend-intent escalation: "add a red sphere inside" must reach the LLM  #
# --------------------------------------------------------------------------- #
_ISO_FACES = [
    GeometrySpec(kind=ShapeKind.POLYGON, name="face-front", x=50, y=60, width=36,
                 height=36, points=[[32.0, 42.0], [68.0, 42.0], [68.0, 78.0], [32.0, 78.0]]),
    GeometrySpec(kind=ShapeKind.POLYGON, name="face-top", x=57, y=35, width=50,
                 height=14, points=[[32.0, 42.0], [46.0, 28.0], [82.0, 28.0], [68.0, 42.0]]),
    GeometrySpec(kind=ShapeKind.POLYGON, name="face-right", x=75, y=53, width=14,
                 height=50, points=[[68.0, 42.0], [82.0, 28.0], [82.0, 64.0], [68.0, 78.0]]),
]
_FOCUS_CTX = ClassifierContext(
    focus_node_id="n1",
    focus_geometry=GeometrySpec(kind=ShapeKind.GROUP, parts=list(_ISO_FACES)),
)


async def _rules_focused(text: str) -> DesignOp:
    return await RulesClassifier().classify(
        text, speaker_id="a", utterance_id="u1", context=_FOCUS_CTX
    )


async def test_add_shape_with_focus_escalates() -> None:
    """Live failure 2026-06-12: 'add a red sphere inside' (focused isometric
    box) was hijacked by the bare-modifier MODIFY branch at 0.70 — the LLM,
    the only stage that can compose INTO a scene, was never consulted."""
    for text in (
        "add a red sphere inside",
        "add a red circle inside it",
        "put a dot in the middle",
        "add a circle",
        "place a star on top of it",
    ):
        op = await _rules_focused(text)
        assert op.confidence < 0.55, text


async def test_plain_modifier_and_create_stay_fast() -> None:
    op = await _rules_focused("make it bigger")
    assert op.op_type == OpType.MODIFY and op.confidence == 0.7
    # extending NOTHING is a plain create — no LLM tax without a focus
    op = await _rules("add a circle")
    assert op.op_type == OpType.CREATE and op.confidence == 0.85


async def test_add_inside_reaches_llm() -> None:
    llm = FakeLLM()
    cascade = CascadeClassifier(RulesClassifier(), llm)
    op = await cascade.classify(
        "add a red sphere inside", speaker_id="a", utterance_id="u1", context=_FOCUS_CTX
    )
    assert llm.calls == 1
    assert op.source_stage == "llm"


# --------------------------------------------------------------------------- #
# 1c) containment snap: parts added "inside" land inside the host scene       #
# --------------------------------------------------------------------------- #
def test_snap_inside_moves_added_part_into_host() -> None:
    from quorum.pipeline.relations import snap_relations

    sphere = GeometrySpec(kind=ShapeKind.CIRCLE, name="sphere", x=92, y=12,
                          width=20, height=20, stroke="#b91c1c")
    geom = GeometrySpec(kind=ShapeKind.GROUP, parts=[*_ISO_FACES, sphere])
    snapped = snap_relations(
        "add a red sphere inside", geom,
        focus_geometry=_FOCUS_CTX.focus_geometry,
    )
    assert snapped is not None and snapped is not geom
    moved = snapped.parts[-1]
    # host union bbox of the three faces is (32,28)..(82,78) — center (57,53)
    assert (moved.x, moved.y) == (57.0, 53.0)
    assert moved.width == 20.0  # fits, so size untouched
    # existing parts byte-identical
    assert snapped.parts[:3] == _ISO_FACES


def test_snap_inside_shrinks_oversized_part() -> None:
    from quorum.pipeline.relations import snap_relations

    slab = GeometrySpec(kind=ShapeKind.RECTANGLE, name="slab", x=50, y=90,
                        width=90, height=90)
    geom = GeometrySpec(kind=ShapeKind.GROUP, parts=[*_ISO_FACES, slab])
    snapped = snap_relations("put a slab inside it", geom,
                             focus_geometry=_FOCUS_CTX.focus_geometry)
    assert snapped is not None
    moved = snapped.parts[-1]
    # host spans 50x50 -> oversized part shrinks to 80% of the smaller span
    assert moved.width == 40.0 and moved.height == 40.0
    assert (moved.x, moved.y) == (57.0, 53.0)


def test_snap_inside_leaves_compliant_and_unrelated_alone() -> None:
    from quorum.pipeline.relations import snap_relations

    inside_already = GeometrySpec(kind=ShapeKind.CIRCLE, name="sphere", x=57, y=53,
                                  width=10, height=10)
    geom = GeometrySpec(kind=ShapeKind.GROUP, parts=[*_ISO_FACES, inside_already])
    assert snap_relations("add a sphere inside", geom,
                          focus_geometry=_FOCUS_CTX.focus_geometry) is geom
    # no containment word -> untouched even when the part is outside
    outside = GeometrySpec(kind=ShapeKind.CIRCLE, name="sphere", x=92, y=12,
                           width=20, height=20)
    geom2 = GeometrySpec(kind=ShapeKind.GROUP, parts=[*_ISO_FACES, outside])
    assert snap_relations("add a sphere next to it", geom2,
                          focus_geometry=_FOCUS_CTX.focus_geometry) is geom2


def test_snap_inside_without_focus_treats_last_part_as_new() -> None:
    from quorum.pipeline.relations import snap_relations

    host = GeometrySpec(kind=ShapeKind.RECTANGLE, name="box", x=50, y=50,
                        width=40, height=40)
    dot = GeometrySpec(kind=ShapeKind.CIRCLE, name="dot", x=95, y=95,
                       width=6, height=6)
    geom = GeometrySpec(kind=ShapeKind.GROUP, parts=[host, dot])
    snapped = snap_relations("a box with a dot inside", geom, focus_geometry=None)
    assert snapped is not None
    assert (snapped.parts[-1].x, snapped.parts[-1].y) == (50.0, 50.0)


_TANGENT = """
{"op_type":"modify","target_shape":"group","target_node_id":"n2","confidence":0.88,
 "geometry":{"kind":"group","x":50,"y":50,"width":80,"height":70,"stroke":"#1f2937","parts":[
   {"kind":"circle","name":"circle","x":40,"y":55,"width":44,"height":44,"stroke":"#1f2937"},
   {"kind":"path","name":"tangent-line","x":55.6,"y":39.4,"width":39.6,"height":39.6,
    "stroke":"#b91c1c","d":"M 35.8 19.6 L 75.4 59.2"}]}}
"""


def _line_dist(circle: GeometrySpec, line: GeometrySpec) -> tuple[float, float]:
    cx, cy, r = circle.x, circle.y, circle.width / 2
    nums = [float(t) for t in (line.d or "").replace("M", " ").replace("L", " ").split()]
    (x1, y1, x2, y2) = nums
    dx, dy = x2 - x1, y2 - y1
    dist = abs(dx * (cy - y1) - dy * (cx - x1)) / (dx**2 + dy**2) ** 0.5
    return dist, r


def test_snap_relations_fixes_off_tangent_line() -> None:
    """The live failure case: LLM emitted a 'tangent' 7 units off — the
    snapper must translate it to exact tangency, preserving direction."""
    from quorum.pipeline.relations import snap_relations

    geom = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[
            GeometrySpec(kind=ShapeKind.CIRCLE, name="c", x=50, y=50, width=50, height=50),
            GeometrySpec(kind=ShapeKind.PATH, name="t", x=50, y=25,
                         width=50, height=50, d="M 25 0 L 75 50"),
        ],
    )
    snapped = snap_relations("a line tangential to the circle", geom)
    assert snapped is not None
    dist, r = _line_dist(snapped.parts[0], snapped.parts[1])
    assert abs(dist - r) < 0.2, f"distance {dist} vs radius {r}"
    # direction preserved (still the same 45-degree slope)
    nums = [float(t) for t in (snapped.parts[1].d or "")
            .replace("M", " ").replace("L", " ").split()]
    assert abs((nums[3] - nums[1]) - (nums[2] - nums[0])) < 1e-6
    # untouched without a relation word
    same = snap_relations("a circle and a line", geom)
    assert same is geom


def test_snap_relations_shortens_when_tangent_cannot_fit() -> None:
    """Live failure 2026-06-12: the LLM re-emitted the circle blown up to the
    full 100x100 box; a 45-degree tangent of the emitted length fits nowhere
    in the box, so the old code passed the center-chord through unchanged.
    The snapper must now SHORTEN the line (tangency is the meaning, length is
    incidental) instead of giving up."""
    from quorum.pipeline.relations import snap_relations

    geom = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[
            GeometrySpec(kind=ShapeKind.CIRCLE, name="c", x=50, y=50,
                         width=100, height=100),
            GeometrySpec(kind=ShapeKind.PATH, name="t", x=50, y=50,
                         width=44, height=44, d="M 28 72 L 72 28"),
        ],
    )
    snapped = snap_relations("now draw a line tangent to it", geom)
    assert snapped is not None and snapped is not geom
    dist, r = _line_dist(snapped.parts[0], snapped.parts[1])
    assert abs(dist - r) < 0.2, f"distance {dist} vs radius {r}"
    nums = [float(t) for t in (snapped.parts[1].d or "")
            .replace("M", " ").replace("L", " ").split()]
    assert all(0.0 <= v <= 100.0 for v in nums), f"out of box: {nums}"
    # still a visible line (>= 5 units), and still 45 degrees
    length = ((nums[2] - nums[0]) ** 2 + (nums[3] - nums[1]) ** 2) ** 0.5
    assert length >= 5.0
    assert abs((nums[3] - nums[1]) + (nums[2] - nums[0])) < 1e-6


def test_prompt_example_f_tangent_is_numerically_tangent() -> None:
    """The worked tangent example must actually BE tangent (distance == r)."""
    payload = _LLMPayload.model_validate_json(_TANGENT)
    op = payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="tangent")
    assert op.geometry is not None
    circle, line = op.geometry.parts
    cx, cy, r = circle.x, circle.y, circle.width / 2
    nums = [float(t) for t in (line.d or "").replace("M", " ").replace("L", " ").split()]
    (x1, y1, x2, y2) = nums
    # perpendicular distance from the circle center to the line
    dx, dy = x2 - x1, y2 - y1
    dist = abs(dx * (cy - y1) - dy * (cx - x1)) / (dx**2 + dy**2) ** 0.5
    assert abs(dist - r) < 0.5, f"distance {dist} vs radius {r}"
    assert SvgRenderer().render(op.geometry).startswith("<svg")


# --------------------------------------------------------------------------- #
# 2) engine: MODIFY accepts replacement geometry (LLM re-emits the scene)     #
# --------------------------------------------------------------------------- #
def _scene(parts: list[GeometrySpec]) -> GeometrySpec:
    return GeometrySpec(kind=ShapeKind.GROUP, parts=parts)


def test_modify_with_geometry_replaces_scene() -> None:
    eng = DesignStateEngine(room="t", clock=FixedClock())
    created = eng.apply(
        DesignOp(
            op_type=OpType.CREATE,
            target_shape=ShapeKind.GROUP,
            geometry=_scene([GeometrySpec(kind=ShapeKind.POLYGON, name="funnel-body",
                                          points=[[12.0, 28.0], [12.0, 72.0], [86.0, 50.0]])]),
            speaker_id="alice",
            utterance_id="u1",
        )
    ).upserted[0]

    extended = _scene(
        [
            GeometrySpec(kind=ShapeKind.POLYGON, name="funnel-body",
                         points=[[12.0, 28.0], [12.0, 72.0], [86.0, 50.0]]),
            GeometrySpec(kind=ShapeKind.RECTANGLE, name="thruster-1", x=7, y=40,
                         width=8, height=7),
            GeometrySpec(kind=ShapeKind.RECTANGLE, name="thruster-2", x=7, y=60,
                         width=8, height=7),
        ]
    )
    diff = eng.apply(
        DesignOp(
            op_type=OpType.MODIFY,
            target_node_id=created.id,
            geometry=extended,
            speaker_id="alice",
            utterance_id="u2",
        )
    )
    node = diff.upserted[0]
    assert [p.name for p in node.geometry.parts] == ["funnel-body", "thruster-1", "thruster-2"]
    assert node.svg and node.svg.startswith("<svg")


def test_modify_without_geometry_still_mutates_in_place() -> None:
    eng = DesignStateEngine(room="t", clock=FixedClock())
    created = eng.apply(
        DesignOp(
            op_type=OpType.CREATE,
            target_shape=ShapeKind.CIRCLE,
            geometry=GeometrySpec(kind=ShapeKind.CIRCLE, width=20, height=20),
            speaker_id="alice",
            utterance_id="u1",
        )
    ).upserted[0]
    diff = eng.apply(
        DesignOp(
            op_type=OpType.MODIFY,
            target_node_id=created.id,
            modifiers=["bigger"],
            speaker_id="alice",
            utterance_id="u2",
        )
    )
    assert diff.upserted[0].geometry.width > 20


def test_classifier_context_carries_focus_geometry() -> None:
    eng = DesignStateEngine(room="t", clock=FixedClock())
    assert eng.classifier_context().focus_geometry is None
    eng.apply(
        DesignOp(
            op_type=OpType.CREATE,
            target_shape=ShapeKind.CIRCLE,
            geometry=GeometrySpec(kind=ShapeKind.CIRCLE, width=33, height=33),
            speaker_id="alice",
            utterance_id="u1",
        )
    )
    ctx = eng.classifier_context()
    assert ctx.focus_geometry is not None
    assert ctx.focus_geometry.kind is ShapeKind.CIRCLE
    assert ctx.focus_geometry.width == 33


# --------------------------------------------------------------------------- #
# 3) prompt Example D (extend-scene) pinned through validation + renderer     #
# --------------------------------------------------------------------------- #
_EXTEND = """
{"op_type":"modify","target_shape":"group","target_node_id":"n3","confidence":0.85,
 "geometry":{"kind":"group","x":50,"y":50,"width":90,"height":60,"stroke":"#1f2937","parts":[
   {"kind":"polygon","name":"funnel-body","x":50,"y":50,"width":74,"height":44,
    "stroke":"#1f2937","points":[[12,28],[12,72],[58,56],[86,52],[86,48],[58,44]]},
   {"kind":"rectangle","name":"thruster-1","x":7,"y":32,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"},
   {"kind":"rectangle","name":"thruster-2","x":7,"y":41,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"},
   {"kind":"rectangle","name":"thruster-3","x":7,"y":50,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"},
   {"kind":"rectangle","name":"thruster-4","x":7,"y":59,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"},
   {"kind":"rectangle","name":"thruster-5","x":7,"y":68,"width":8,"height":7,"corner_radius":2,"stroke":"#b91c1c"}]}}
"""


async def test_color_words_in_rich_utterance_escalate_not_modify_focus() -> None:
    # "red"/"blue" used to match the color table and MODIFY the focus at 0.7,
    # so the snowman never reached the LLM. Hazy cap now applies to that path.
    ctx = ClassifierContext(focus_node_id="n1")
    op = await RulesClassifier().classify(
        "a snowman with a red scarf and a blue hat, colored in",
        speaker_id="a",
        utterance_id="u1",
        context=ctx,
    )
    assert op.confidence < 0.55  # escalates; rules MODIFY stays as fallback


async def test_rate_limited_post_retries_once_then_succeeds() -> None:
    # Groq 429s back-to-back utterances; one short retry must rescue the call.
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resp = await LLMClassifier._post_with_retry(client, "https://x/y", json={})
    assert calls == 2
    assert resp.status_code == 200


_CUBE = """
{"op_type":"create","target_shape":"group","confidence":0.9,
 "geometry":{"kind":"group","x":50,"y":50,"width":60,"height":60,"stroke":"#1f2937","parts":[
   {"kind":"polygon","name":"face-front","x":50,"y":60,"width":36,"height":36,"stroke":"#1f2937",
    "fill":"#9ca3af","fill_style":"solid","points":[[32,42],[68,42],[68,78],[32,78]]},
   {"kind":"polygon","name":"face-top","x":57,"y":35,"width":50,"height":14,"stroke":"#1f2937",
    "fill":"#e5e7eb","fill_style":"solid","points":[[32,42],[46,28],[82,28],[68,42]]},
   {"kind":"polygon","name":"face-right","x":75,"y":53,"width":14,"height":50,"stroke":"#1f2937",
    "fill":"#6b7280","fill_style":"solid","points":[[68,42],[82,28],[82,64],[68,78]]}]}}
"""


def test_prompt_example_e_isometric_cube_parses_renders_with_fills() -> None:
    payload = _LLMPayload.model_validate_json(_CUBE)
    op = payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="a 3D cube")
    assert op.op_type == OpType.CREATE  # new idea, not a modify of the focus
    assert op.geometry is not None and len(op.geometry.parts) == 3
    assert all(p.fill is not None and p.fill_style is not None for p in op.geometry.parts)
    svg = SvgRenderer().render(op.geometry)
    assert svg.startswith("<svg") and "#9ca3af" in svg  # fill colors reach the SVG


def test_prompt_example_d_extend_scene_parses_and_renders() -> None:
    payload = _LLMPayload.model_validate_json(_EXTEND)
    op = payload_to_op(payload, speaker_id="a", utterance_id="u1", raw_text="add five thrusters")
    assert op.op_type == OpType.MODIFY
    assert op.target_node_id == "n3"
    assert op.geometry is not None
    names = [p.name for p in op.geometry.parts]
    assert names[0] == "funnel-body" and len(names) == 6
    assert SvgRenderer().render(op.geometry).startswith("<svg")
