"""Tests for deterministic recolor (R2 segment, plan.md §12).

Covers:
- parse_hex / format_hex roundtrip (incl. #rgb shorthand, uppercase input)
- retint hue/saturation adoption and lightness ordering for the cuboid trio
- apply_modifiers cuboid scenario end-to-end (GROUP with three filled polygons)
- stroke-only PATH spec gets exact target hex
- unparseable original (CSS name) falls back to target
- recolor-twice: second retint reads the re-tinted first color's lightness
- v1 compatibility: spec with no fill and no color modifier is unchanged
"""

from __future__ import annotations

from quorum.domain.color import format_hex, hsl_to_rgb, parse_hex, retint, rgb_to_hsl
from quorum.domain.geometry import GeometrySpec, ShapeKind, apply_modifiers

# ---------------------------------------------------------------------------
# Hex parse/format
# ---------------------------------------------------------------------------


def test_parse_hex_shorthand() -> None:
    assert parse_hex("#f00") == (255, 0, 0)
    assert parse_hex("#0f0") == (0, 255, 0)
    assert parse_hex("#00f") == (0, 0, 255)
    assert parse_hex("#abc") == (0xAA, 0xBB, 0xCC)


def test_parse_hex_full() -> None:
    assert parse_hex("#dc2626") == (0xDC, 0x26, 0x26)
    assert parse_hex("#e5e7eb") == (0xE5, 0xE7, 0xEB)


def test_parse_hex_uppercase() -> None:
    assert parse_hex("#DC2626") == (0xDC, 0x26, 0x26)
    assert parse_hex("#E5E7EB") == (0xE5, 0xE7, 0xEB)


def test_parse_hex_returns_none_for_names() -> None:
    assert parse_hex("tomato") is None
    assert parse_hex("red") is None
    assert parse_hex("") is None
    assert parse_hex("rgb(255,0,0)") is None


def test_format_hex_roundtrip() -> None:
    for color in ("#dc2626", "#e5e7eb", "#9ca3af", "#6b7280", "#1f2937"):
        rgb = parse_hex(color)
        assert rgb is not None
        assert format_hex(*rgb) == color


def test_format_hex_shorthand_expands() -> None:
    # #f00 → #ff0000
    rgb = parse_hex("#f00")
    assert rgb is not None
    assert format_hex(*rgb) == "#ff0000"


# ---------------------------------------------------------------------------
# RGB ↔ HSL roundtrip
# ---------------------------------------------------------------------------


def test_rgb_hsl_roundtrip() -> None:
    for r, g, b in [(220, 38, 38), (229, 231, 235), (156, 163, 175), (107, 114, 128)]:
        h, s, li = rgb_to_hsl(r, g, b)
        rr, gg, bb = hsl_to_rgb(h, s, li)
        assert abs(rr - r) <= 1
        assert abs(gg - g) <= 1
        assert abs(bb - b) <= 1


# ---------------------------------------------------------------------------
# retint — cuboid trio ordering
# ---------------------------------------------------------------------------

# The isometric cuboid has three gray faces:
#   light top  #e5e7eb  (high lightness)
#   mid front  #9ca3af  (medium lightness)
#   dark side  #6b7280  (lower lightness)
# After retint to red #dc2626 they must stay ordered light > mid > dark.

_CUBOID_GRAYS = ("#e5e7eb", "#9ca3af", "#6b7280")
_TARGET_RED = "#dc2626"


def _lightness(hex_color: str) -> float:
    rgb = parse_hex(hex_color)
    assert rgb is not None
    _, _, li = rgb_to_hsl(*rgb)
    return li


def test_retint_adopts_target_hue_and_saturation() -> None:
    """All three re-tinted faces should have the target's hue (≈ 0°, i.e. red)."""
    t_rgb = parse_hex(_TARGET_RED)
    assert t_rgb is not None
    t_h, t_s, _ = rgb_to_hsl(*t_rgb)

    for gray in _CUBOID_GRAYS:
        result = retint(gray, _TARGET_RED)
        r_rgb = parse_hex(result)
        assert r_rgb is not None, f"retint({gray!r}, {_TARGET_RED!r}) not hex: {result!r}"
        r_h, r_s, _ = rgb_to_hsl(*r_rgb)
        assert abs(r_h - t_h) < 0.01, f"hue mismatch for {gray}: {r_h} vs {t_h}"
        assert abs(r_s - t_s) < 0.05, f"saturation mismatch for {gray}: {r_s} vs {t_s}"


def test_retint_preserves_lightness_ordering_for_cuboid_trio() -> None:
    """Light → mid → dark ordering must be preserved after recolor."""
    results = [retint(g, _TARGET_RED) for g in _CUBOID_GRAYS]
    lights = [_lightness(r) for r in results]
    # All three must be distinct
    assert len(set(results)) == 3, f"not all distinct: {results}"
    # Ordering preserved: light_top > mid_front > dark_side
    assert lights[0] > lights[1] > lights[2], (
        f"ordering broken: light={lights[0]:.3f} mid={lights[1]:.3f} dark={lights[2]:.3f}"
    )


def test_retint_unparseable_original_returns_target() -> None:
    """A CSS named color as original falls back to the raw target."""
    assert retint("tomato", _TARGET_RED) == _TARGET_RED
    assert retint("red", _TARGET_RED) == _TARGET_RED
    assert retint("", _TARGET_RED) == _TARGET_RED


def test_retint_unparseable_target_returns_original() -> None:
    """If target is not a hex, return original unchanged."""
    assert retint(_CUBOID_GRAYS[0], "red") == _CUBOID_GRAYS[0]
    assert retint(_CUBOID_GRAYS[0], "") == _CUBOID_GRAYS[0]


# ---------------------------------------------------------------------------
# apply_modifiers cuboid scenario (GROUP with three filled polygon parts)
# ---------------------------------------------------------------------------

def _make_cuboid_group() -> GeometrySpec:
    """Three-faced isometric cuboid: light top, mid front, dark side."""
    top = GeometrySpec(
        kind=ShapeKind.POLYGON,
        name="top",
        points=[(50, 20), (70, 30), (50, 40), (30, 30)],
        fill="#e5e7eb",
        stroke="#1f2937",
    )
    front = GeometrySpec(
        kind=ShapeKind.POLYGON,
        name="front",
        points=[(30, 30), (50, 40), (50, 60), (30, 50)],
        fill="#9ca3af",
        stroke="#1f2937",
    )
    side = GeometrySpec(
        kind=ShapeKind.POLYGON,
        name="side",
        points=[(50, 40), (70, 30), (70, 50), (50, 60)],
        fill="#6b7280",
        stroke="#1f2937",
    )
    return GeometrySpec(kind=ShapeKind.GROUP, parts=[top, front, side])


def test_apply_modifiers_cuboid_recolor_all_fills_are_red() -> None:
    """GROUP recolor: every part's fill adopts target hue (≈ red)."""
    cuboid = _make_cuboid_group()
    result = apply_modifiers(cuboid, ["color:#dc2626"])

    t_rgb = parse_hex(_TARGET_RED)
    assert t_rgb is not None
    t_h, t_s, _ = rgb_to_hsl(*t_rgb)

    for part in result.parts:
        assert part.fill is not None, f"part {part.name} lost its fill"
        f_rgb = parse_hex(part.fill)
        assert f_rgb is not None, f"part {part.name} fill is not hex: {part.fill!r}"
        f_h, f_s, _ = rgb_to_hsl(*f_rgb)
        assert abs(f_h - t_h) < 0.01, f"part {part.name} hue wrong: {f_h} vs {t_h}"
        assert abs(f_s - t_s) < 0.05, f"part {part.name} saturation wrong"


def test_apply_modifiers_cuboid_recolor_lightness_ordering() -> None:
    """GROUP recolor: lightness ordering top > front > side is preserved."""
    cuboid = _make_cuboid_group()
    result = apply_modifiers(cuboid, ["color:#dc2626"])
    fills = [part.fill for part in result.parts]
    assert all(f is not None for f in fills)
    lights = [_lightness(f) for f in fills]  # type: ignore[arg-type]
    # top (index 0) must be lightest, side (index 2) darkest
    assert lights[0] > lights[1] > lights[2], (
        f"ordering broken: {lights}"
    )
    # All three fills must be distinct
    assert len(set(fills)) == 3, f"fills not all distinct: {fills}"


def test_apply_modifiers_cuboid_recolor_strokes_also_retinted() -> None:
    """GROUP recolor: strokes are also re-tinted (dark red, not gray)."""
    cuboid = _make_cuboid_group()
    result = apply_modifiers(cuboid, ["color:#dc2626"])
    t_rgb = parse_hex(_TARGET_RED)
    assert t_rgb is not None
    t_h, _, _ = rgb_to_hsl(*t_rgb)

    for part in result.parts:
        s_rgb = parse_hex(part.stroke)
        assert s_rgb is not None, f"part {part.name} stroke is not hex: {part.stroke!r}"
        s_h, _, _ = rgb_to_hsl(*s_rgb)
        assert abs(s_h - t_h) < 0.01, f"part {part.name} stroke hue wrong: {s_h}"


# ---------------------------------------------------------------------------
# Stroke-only PATH spec
# ---------------------------------------------------------------------------


def test_apply_modifiers_stroke_only_gets_exact_target() -> None:
    """A PATH with fill=None takes the exact target hex for stroke."""
    path = GeometrySpec(kind=ShapeKind.PATH, d="M 10 10 L 90 90", stroke="#1f2937")
    # fill is None by default
    result = apply_modifiers(path, ["color:#dc2626"])
    assert result.stroke == "#dc2626"
    assert result.fill is None


# ---------------------------------------------------------------------------
# Recolor twice
# ---------------------------------------------------------------------------


def test_recolor_twice_second_reads_first_result() -> None:
    """Recoloring red→blue: the second retint reads the red fill's lightness."""
    top = GeometrySpec(
        kind=ShapeKind.POLYGON,
        name="top",
        points=[(50, 20), (70, 30), (50, 40), (30, 30)],
        fill="#e5e7eb",
        stroke="#1f2937",
    )
    group = GeometrySpec(kind=ShapeKind.GROUP, parts=[top])

    after_red = apply_modifiers(group, ["color:#dc2626"])
    after_blue = apply_modifiers(after_red, ["color:#2563eb"])

    red_fill = after_red.parts[0].fill
    blue_fill = after_blue.parts[0].fill

    assert red_fill is not None and blue_fill is not None
    # The blue fill must have blue hue
    blue_rgb = parse_hex("#2563eb")
    assert blue_rgb is not None
    b_h, _, _ = rgb_to_hsl(*blue_rgb)
    result_rgb = parse_hex(blue_fill)
    assert result_rgb is not None
    r_h, _, _ = rgb_to_hsl(*result_rgb)
    assert abs(r_h - b_h) < 0.01, f"expected blue hue {b_h:.3f}, got {r_h:.3f}"
    # Must differ from red fill
    assert blue_fill != red_fill


# ---------------------------------------------------------------------------
# v1 compatibility
# ---------------------------------------------------------------------------


def test_v1_compat_no_fill_no_color_modifier_unchanged() -> None:
    """A spec with no fill and no color modifier must be byte-identical after apply_modifiers."""
    spec = GeometrySpec(kind=ShapeKind.RECTANGLE, stroke="#1f2937")
    result = apply_modifiers(spec, ["fillet"])
    # stroke unchanged
    assert result.stroke == "#1f2937"
    assert result.fill is None


def test_v1_compat_no_modifiers_is_identity() -> None:
    """apply_modifiers([]) must return the exact same object (no copy)."""
    spec = GeometrySpec(kind=ShapeKind.RECTANGLE, corner_radius=5.0)
    result = apply_modifiers(spec, [])
    assert result is spec


# ---------------------------------------------------------------------------
# Existing test compatibility: color recurses into v2 parts (stroke-only)
# ---------------------------------------------------------------------------

def test_color_recurses_into_stroke_only_v2_parts() -> None:
    """GROUP where parts have no fill: stroke is set to exact target color."""
    scene = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[GeometrySpec(kind=ShapeKind.POLYGON, points=[(10, 10), (90, 10), (50, 80)])],
    )
    # The part has no fill (fill=None), so stroke = exact target
    out = apply_modifiers(scene, ["color:#dc2626"])
    assert out.parts[0].stroke == "#dc2626"
    assert out.parts[0].fill is None
