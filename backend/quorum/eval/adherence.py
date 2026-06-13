"""Instruction-adherence scoring for the drawing pipeline (plan.md §11 D4).

JSON validity says the model produced *a* drawing; it says nothing about whether
the drawing matches what was asked. ``eval_llm.py`` already scores validity and
richness (parts-per-scene); this module scores the harder thing —
**instruction adherence** — deterministically and WITHOUT a vision model, by
reading the resulting :class:`~quorum.domain.geometry.GeometrySpec`:

  * ``count``     — "five thrusters", "two windows": the right NUMBER of the
                    named parts (matched by part name)?
  * ``color``     — "blue", "a red scarf", "colored in": the named colors
                    actually present (hue match via :mod:`quorum.domain.color`)?
  * ``coherence`` — do the parts attach into ONE connected body, or is it the
                    "exploded view" failure mode (disjoint islands)?
  * ``relations`` — "X inside Y", "A above B": does the spatial predicate hold?
  * ``solids3d``  — does a 3D/isometric prompt yield a coherent SHADED assembly
                    (the D3 projection signature), not a flat doodle?

Each applicable dimension scores in ``[0, 1]``; :attr:`AdherenceScore.overall`
is the mean of the dimensions that APPLY to a given prompt (a prompt that names
no color earns no color score — ``None``, not zero). The scorer is a pure
function of ``(GeometrySpec, Expectation)`` — the same "model proposes, code
disposes" split the rest of the pipeline uses: the model draws, this code
measures. No I/O, no network, no key — so the harness is verifiable on fixtures.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from statistics import mean

from quorum.domain.color import parse_hex, rgb_to_hsl
from quorum.domain.geometry import FillStyle, GeometrySpec, ShapeKind

# --------------------------------------------------------------------------- #
# Named colors → representative hex (the palette the LLM prompt teaches). Only
# the words the eval prompt set actually uses need an entry; unknown names are
# reported and skipped rather than silently scored.
# --------------------------------------------------------------------------- #
NAMED_COLORS: dict[str, str] = {
    "blue": "#2563eb",
    "red": "#dc2626",
    "green": "#16a34a",
    "orange": "#ea580c",
    "yellow": "#eab308",
    "purple": "#7c3aed",
    "pink": "#db2777",
    "brown": "#92400e",
    # black/white MUST be truly achromatic (saturation 0) so the achromatic
    # match branch fires — a near-black like #1f2937 (s≈0.28) reads as a dark
    # *blue* and would make "black" unmatchable. Caught by the harness review.
    "black": "#111111",
    "white": "#fafafa",
    "gray": "#6b7280",
    "grey": "#6b7280",
}

# Hue match tolerance (fraction of the [0,1] hue wheel ≈ 25°).
_HUE_TOL = 0.07
# A chromatic match must be saturated and mid-toned enough to exclude the near
# black DEFAULT stroke (#1f2937 is technically a desaturated blue at L≈0.17).
_CHROMA_SAT_MIN = 0.25
_CHROMA_LI_LO = 0.25
_CHROMA_LI_HI = 0.90
# Achromatic (black/white/gray) targets match by lightness, not hue.
_ACHROMA_SAT_MAX = 0.18
_ACHROMA_LI_TOL = 0.25
# Two bboxes "touch" if they overlap or share an edge within this slack (units).
_TOUCH_EPS = 1.0
# A part this wide AND tall is a near-full-canvas background: it would bridge
# every other part in the coherence graph (hiding an exploded foreground), so
# it is excluded as a connector (review find).
_BG_SPAN = 85.0
# A 3D prompt's shaded faces must span at least this lightness range to read as
# a deliberately-shaded solid rather than a flat fill.
_SHADE_SPAN_MIN = 0.18
# Near-white fills (above this lightness) are backgrounds, not shaded 3D faces:
# the isometric top face tops out at L=0.80 (projected) / ~0.91 (hand-drawn), so
# a pure-white fill must not count toward the shading signature (review find).
_SHADE_LI_MAX = 0.92


@dataclass(frozen=True)
class Relation:
    """A spatial predicate to verify between two named parts of the result.

    ``inner``/``outer`` are case-insensitive substrings matched against part
    names; the relation is only scored when EACH resolves to exactly one part
    (ambiguous or missing → unscorable, never a penalty).
    """

    kind: str  # "inside" | "above" | "below" | "beside"
    inner: str
    outer: str


@dataclass(frozen=True)
class Expectation:
    """The machine-checkable expectations annotated for one eval prompt."""

    # role-substring (singular, e.g. "thruster") -> expected count of parts.
    counts: Mapping[str, int] = field(default_factory=dict)
    # named colors that should appear on some part's fill or stroke.
    colors: tuple[str, ...] = ()
    # the utterance asked for the body to be filled in ("colored in").
    colored_in: bool = False
    relations: tuple[Relation, ...] = ()
    # a 3D / isometric prompt — expect a coherent shaded assembly.
    expect_3d: bool = False
    # a recognizable sketch needs at least this many parts (anti lone-rectangle).
    min_parts: int = 1
    check_coherence: bool = True


@dataclass(frozen=True)
class AdherenceScore:
    """Per-dimension and overall adherence for one result. ``None`` = the
    dimension did not apply to this prompt."""

    valid: bool
    count: float | None
    color: float | None
    coherence: float | None
    relations: float | None
    solids3d: float | None
    overall: float
    notes: tuple[str, ...]

    def applicable(self) -> dict[str, float]:
        """The dimensions that applied, as a name→score dict (drops ``None``)."""
        dims = {
            "count": self.count,
            "color": self.color,
            "coherence": self.coherence,
            "relations": self.relations,
            "solids3d": self.solids3d,
        }
        return {k: v for k, v in dims.items() if v is not None}


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def _leaf_parts(geom: GeometrySpec) -> list[GeometrySpec]:
    """A scene's drawable primitives: a GROUP's parts, else the shape itself."""
    return list(geom.parts) if geom.kind is ShapeKind.GROUP else [geom]


def _bbox(part: GeometrySpec) -> tuple[float, float, float, float]:
    """Axis-aligned (x1, y1, x2, y2). Polygons use their points; everything else
    (incl. paths) uses the nominal center+extent the spec carries."""
    if part.points:
        xs = [p[0] for p in part.points]
        ys = [p[1] for p in part.points]
        return min(xs), min(ys), max(xs), max(ys)
    hw, hh = part.width / 2.0, part.height / 2.0
    return part.x - hw, part.y - hh, part.x + hw, part.y + hh


def _boxes_touch(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    eps: float = _TOUCH_EPS,
) -> bool:
    """True if a and b overlap or share an edge within ``eps`` units."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return ax1 <= bx2 + eps and bx1 <= ax2 + eps and ay1 <= by2 + eps and by1 <= ay2 + eps


def _ranges_overlap(lo_a: float, hi_a: float, lo_b: float, hi_b: float) -> bool:
    return lo_a < hi_b and lo_b < hi_a


# --------------------------------------------------------------------------- #
# Color matching
# --------------------------------------------------------------------------- #
def _hue_dist(h1: float, h2: float) -> float:
    """Circular distance on the [0,1] hue wheel."""
    d = abs(h1 - h2)
    return min(d, 1.0 - d)


def _color_matches(part: GeometrySpec, target_hex: str) -> bool:
    """True if the part's fill OR stroke reads as the target color.

    Chromatic targets require a hue match on a sufficiently saturated, mid-toned
    color (so the near-black default stroke never counts as "blue"). Achromatic
    targets (black/white/gray) match by lightness with low saturation.
    """
    t_rgb = parse_hex(target_hex)
    if t_rgb is None:
        return False
    t_h, t_s, t_li = rgb_to_hsl(*t_rgb)
    chromatic = t_s >= _ACHROMA_SAT_MAX

    for color in (part.fill, part.stroke):
        if not color:
            continue
        rgb = parse_hex(color)
        if rgb is None:
            continue
        h, s, li = rgb_to_hsl(*rgb)
        if chromatic:
            if (
                s >= _CHROMA_SAT_MIN
                and _CHROMA_LI_LO <= li <= _CHROMA_LI_HI
                and _hue_dist(h, t_h) <= _HUE_TOL
            ):
                return True
        else:
            if s < _ACHROMA_SAT_MAX and abs(li - t_li) <= _ACHROMA_LI_TOL:
                return True
    return False


# --------------------------------------------------------------------------- #
# Per-dimension scorers (each appends a human-readable note)
# --------------------------------------------------------------------------- #
def _score_counts(
    parts: list[GeometrySpec], counts: Mapping[str, int], notes: list[str]
) -> float | None:
    scores: list[float] = []
    for role, expected in counts.items():
        if expected <= 0:
            continue
        actual = sum(1 for p in parts if p.name and role.lower() in p.name.lower())
        s = max(0.0, 1.0 - abs(actual - expected) / expected)
        scores.append(s)
        notes.append(f"count[{role}]: {actual}/{expected} -> {s:.2f}")
    return mean(scores) if scores else None


def _score_colors(
    parts: list[GeometrySpec], colors: tuple[str, ...], colored_in: bool, notes: list[str]
) -> float | None:
    reqs: list[float] = []
    for name in colors:
        target = NAMED_COLORS.get(name.lower())
        if target is None:
            notes.append(f"color[{name}]: unknown name, skipped")
            continue
        matched = any(_color_matches(p, target) for p in parts)
        reqs.append(1.0 if matched else 0.0)
        notes.append(f"color[{name}]: {'present' if matched else 'absent'}")
    if colored_in:
        has_fill = any(
            p.fill is not None and p.fill_style is not FillStyle.NONE for p in parts
        )
        reqs.append(1.0 if has_fill else 0.0)
        notes.append(f"colored_in: {'fills present' if has_fill else 'no fills'}")
    return mean(reqs) if reqs else None


def _is_background(box: tuple[float, float, float, float]) -> bool:
    """A near-full-canvas part — excluded as a coherence connector so it can't
    bridge an exploded foreground into a single fake component."""
    x1, y1, x2, y2 = box
    return (x2 - x1) >= _BG_SPAN and (y2 - y1) >= _BG_SPAN


def _score_coherence(parts: list[GeometrySpec], notes: list[str]) -> float:
    """Fraction of the (n-1) connections a fully-connected scene would have.

    1.0 = every part touches the single connected body; lower = exploded into
    disjoint islands. A single part is trivially coherent. A near-full-canvas
    background is excluded as a connector (it would bridge anything).
    """
    if len(parts) <= 1:
        return 1.0
    boxes = [b for b in (_bbox(p) for p in parts) if not _is_background(b)]
    n = len(boxes)
    n_bg = len(parts) - n
    if n <= 1:
        notes.append(f"coherence: {n} foreground part(s) (excluded {n_bg} bg) -> 1.00")
        return 1.0
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _boxes_touch(boxes[i], boxes[j]):
                parent[find(i)] = find(j)

    components = len({find(i) for i in range(n)})
    score = (n - components) / (n - 1)
    bg = f" (excluded {n_bg} bg)" if n_bg else ""
    notes.append(f"coherence: {components} component(s) / {n} parts{bg} -> {score:.2f}")
    return score


def _resolve_one(parts: list[GeometrySpec], role: str) -> GeometrySpec | None:
    """The single part whose name contains ``role``; None if 0 or >1 (ambiguous)."""
    hits = [p for p in parts if p.name and role.lower() in p.name.lower()]
    return hits[0] if len(hits) == 1 else None


def _relation_holds(
    kind: str,
    inner: tuple[float, float, float, float],
    outer: tuple[float, float, float, float],
) -> bool:
    ix1, iy1, ix2, iy2 = inner
    ox1, oy1, ox2, oy2 = outer
    icy = (iy1 + iy2) / 2.0
    ocy = (oy1 + oy2) / 2.0
    if kind == "inside":
        e = _TOUCH_EPS
        return ix1 >= ox1 - e and ix2 <= ox2 + e and iy1 >= oy1 - e and iy2 <= oy2 + e
    if kind == "above":  # y grows DOWN — "above" = smaller y, columns overlap
        return icy < ocy and _ranges_overlap(ix1, ix2, ox1, ox2)
    if kind == "below":
        return icy > ocy and _ranges_overlap(ix1, ix2, ox1, ox2)
    if kind == "beside":  # side by side — x ranges disjoint, rows overlap
        return not _ranges_overlap(ix1, ix2, ox1, ox2) and _ranges_overlap(iy1, iy2, oy1, oy2)
    return False


def _score_relations(
    parts: list[GeometrySpec], relations: tuple[Relation, ...], notes: list[str]
) -> float | None:
    scores: list[float] = []
    for rel in relations:
        inner = _resolve_one(parts, rel.inner)
        outer = _resolve_one(parts, rel.outer)
        if inner is None or outer is None:
            notes.append(f"relation[{rel.kind} {rel.inner}/{rel.outer}]: unresolved, skipped")
            continue
        ok = _relation_holds(rel.kind, _bbox(inner), _bbox(outer))
        scores.append(1.0 if ok else 0.0)
        notes.append(f"relation[{rel.kind} {rel.inner}/{rel.outer}]: {'ok' if ok else 'FAIL'}")
    return mean(scores) if scores else None


def _score_solids3d(
    parts: list[GeometrySpec], payload_kind: str | None, notes: list[str]
) -> float:
    """1.0 if the result is a coherent shaded 3D assembly, else 0.0.

    The crisp signal is ``payload_kind == "solids"`` (the model used the exact
    projection path). Failing that — or when the kind is unknown — we accept the
    geometry signature: 2+ SOLID-filled faces whose lightnesses span a shading
    range (the D3 projection AND a hand-drawn isometric both produce this; a flat
    or exploded doodle does not).
    """
    if payload_kind == "solids":
        notes.append("solids3d: model emitted solids -> 1.00")
        return 1.0
    lits: list[float] = []
    for p in parts:
        if p.fill and p.fill_style is FillStyle.SOLID:
            rgb = parse_hex(p.fill)
            if rgb is not None:
                li = rgb_to_hsl(*rgb)[2]
                if li <= _SHADE_LI_MAX:  # near-white = background, not a shaded face
                    lits.append(li)
    if len(lits) >= 2 and (max(lits) - min(lits)) >= _SHADE_SPAN_MIN:
        notes.append(f"solids3d: shaded faces span L {min(lits):.2f}..{max(lits):.2f} -> 1.00")
        return 1.0
    notes.append("solids3d: no 3D shading signature -> 0.00")
    return 0.0


# --------------------------------------------------------------------------- #
# Top-level
# --------------------------------------------------------------------------- #
def score(
    geom: GeometrySpec | None,
    expect: Expectation,
    *,
    rendered_ok: bool = True,
    payload_kind: str | None = None,
) -> AdherenceScore:
    """Score how well ``geom`` adheres to ``expect``.

    ``geom`` is the resulting op's geometry (``None`` if the op produced none);
    ``rendered_ok`` is whether the SVG renderer accepted it; ``payload_kind`` is
    an optional hint from the LLM stage ("solids"/"patch"/"geometry") that
    sharpens the ``solids3d`` signal. An invalid result scores 0 overall with all
    dimensions ``None``.
    """
    notes: list[str] = []
    if geom is None or not rendered_ok:
        notes.append("invalid: no geometry" if geom is None else "invalid: render failed")
        return AdherenceScore(False, None, None, None, None, None, 0.0, tuple(notes))

    parts = _leaf_parts(geom)
    # Projected solids decompose one named solid into many faces ("piston-1" ->
    # "piston-1-body" + "piston-1-top"), so role-substring counting over-counts;
    # skip count on the solids path and rely on solids3d + min_parts (review find).
    if payload_kind == "solids" and expect.counts:
        notes.append("count: skipped (projected solids multiply part names)")
        count: float | None = None
    else:
        count = _score_counts(parts, expect.counts, notes)
    color = _score_colors(parts, expect.colors, expect.colored_in, notes)
    coherence = _score_coherence(parts, notes) if expect.check_coherence else None
    relations = _score_relations(parts, expect.relations, notes)
    solids3d = _score_solids3d(parts, payload_kind, notes) if expect.expect_3d else None

    dims = [d for d in (count, color, coherence, relations, solids3d) if d is not None]
    overall = mean(dims) if dims else 1.0  # valid-but-unannotated → full marks

    # Sparsity penalty: a recognizable sketch needs >= min_parts. A lone
    # rectangle for "a coffee mug" is valid + coherent but not adherent.
    if expect.min_parts > 1 and len(parts) < expect.min_parts:
        factor = len(parts) / expect.min_parts
        notes.append(f"sparse: {len(parts)}/{expect.min_parts} parts -> overall x{factor:.2f}")
        overall *= factor

    return AdherenceScore(
        valid=True,
        count=count,
        color=color,
        coherence=coherence,
        relations=relations,
        solids3d=solids3d,
        overall=overall,
        notes=tuple(notes),
    )
