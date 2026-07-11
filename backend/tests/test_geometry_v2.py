"""Geometry IR v2 — polygon/path/text primitives and the pathdata contract."""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from quorum.domain import pathdata
from quorum.domain.geometry import FillStyle, GeometrySpec, ShapeKind, apply_modifiers

# ---------------------------------------------------------------- pathdata


def test_parse_accepts_absolute_uppercase_commands() -> None:
    cmds = pathdata.parse("M 10 20 L 30 40 H 50 V 60 C 1 2 3 4 5 6 Q 7 8 9 10 A 5 5 0 0 1 70 80 Z")
    assert [c for c, _ in cmds] == ["M", "L", "H", "V", "C", "Q", "A", "Z"]


def test_parse_normalizes_implicit_linetos_after_moveto() -> None:
    cmds = pathdata.parse("M 10 10 20 20 30 30")
    assert [c for c, _ in cmds] == ["M", "L", "L"]


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty
        "L 10 10",  # must start with M
        "m 10 10",  # lowercase/relative rejected
        "M 10 10 l 5 5",  # relative mid-path rejected
        "M 10 10 S 1 2 3 4",  # S not in the whitelist
        "M 10 10 L 20",  # wrong arity
        "M 10 10 # nope",  # junk characters
        "M " + " L ".join(f"{i} {i}" for i in range(200)),  # too large
    ],
)
def test_parse_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        pathdata.parse(bad)


def test_scale_about_center_golden() -> None:
    # (40,40) about (50,50) at 2x -> (30,30); (60,80) -> (70,110->clamped 100)
    out = pathdata.scale_about_center("M 40 40 L 60 80", 2.0)
    assert out == "M 30 30 L 70 100"


def test_transform_maps_arc_radii_but_not_flags() -> None:
    out = pathdata.transform(
        "M 0 0 A 10 10 45 1 0 20 20",
        fx=lambda x: x * 2,
        fy=lambda y: y * 3,
        fr=lambda r: r * 2,
    )
    assert out == "M 0 0 A 20 20 45 1 0 40 60"


def test_parse_latency_budget() -> None:
    # A near-max path must parse well under a millisecond (renderer hot path).
    d = "M 0 0 " + " ".join(f"L {i % 100} {(i * 7) % 100}" for i in range(60))
    start = time.perf_counter()
    for _ in range(10):
        pathdata.parse(d)
    per_call_ms = (time.perf_counter() - start) / 10 * 1000
    assert per_call_ms < 1.0, f"pathdata.parse took {per_call_ms:.3f} ms"


# ---------------------------------------------------------------- validators


def test_polygon_requires_points() -> None:
    with pytest.raises(ValidationError):
        GeometrySpec(kind=ShapeKind.POLYGON)
    spec = GeometrySpec(kind=ShapeKind.POLYGON, points=[(10, 10), (90, 10), (50, 80)])
    assert spec.points is not None and len(spec.points) == 3


def test_polygon_rejects_out_of_box_points() -> None:
    with pytest.raises(ValidationError):
        GeometrySpec(kind=ShapeKind.POLYGON, points=[(10, 10), (110, 10), (50, 80)])


def test_polygon_rejects_too_few_points() -> None:
    with pytest.raises(ValidationError):
        GeometrySpec(kind=ShapeKind.POLYGON, points=[(10, 10), (90, 10)])


def test_path_requires_valid_d() -> None:
    with pytest.raises(ValidationError):
        GeometrySpec(kind=ShapeKind.PATH)
    with pytest.raises(ValidationError):
        GeometrySpec(kind=ShapeKind.PATH, d="m 1 2 l 3 4")
    spec = GeometrySpec(kind=ShapeKind.PATH, d="M 10 10 L 90 90")
    assert spec.d == "M 10 10 L 90 90"


def test_text_requires_label() -> None:
    with pytest.raises(ValidationError):
        GeometrySpec(kind=ShapeKind.TEXT)
    spec = GeometrySpec(kind=ShapeKind.TEXT, label="9:41", font_size=3)
    assert spec.label == "9:41"


def test_groups_stay_flat() -> None:
    inner = GeometrySpec(kind=ShapeKind.GROUP, parts=[GeometrySpec(kind=ShapeKind.CIRCLE)])
    with pytest.raises(ValidationError):
        GeometrySpec(kind=ShapeKind.GROUP, parts=[inner])


def test_parts_hard_ceiling_at_120() -> None:
    """The model's HARD ceiling is PARTS_HARD_MAX (120); the configurable soft
    cap (Settings.max_scene_parts, default 60) is enforced by the code paths
    that build parts (apply_patch, project_solids), not by the frozen model."""
    ok = [GeometrySpec(kind=ShapeKind.CIRCLE) for _ in range(61)]
    GeometrySpec(kind=ShapeKind.GROUP, parts=ok)  # 61..120 validates now
    over = [GeometrySpec(kind=ShapeKind.CIRCLE) for _ in range(121)]
    with pytest.raises(ValidationError):
        GeometrySpec(kind=ShapeKind.GROUP, parts=over)


def test_v1_specs_still_validate_and_roundtrip() -> None:
    spec = GeometrySpec(kind=ShapeKind.RECTANGLE, corner_radius=12.0)
    again = GeometrySpec.model_validate_json(spec.cache_key())
    assert again == spec


# ------------------------------------------------------------ apply_modifiers


def test_bigger_scales_polygon_points_about_center() -> None:
    spec = GeometrySpec(kind=ShapeKind.POLYGON, points=[(40, 40), (60, 40), (50, 60)])
    out = apply_modifiers(spec, ["bigger"])
    assert out.points == [(37.0, 37.0), (63.0, 37.0), (50.0, 63.0)]


def test_bigger_scales_path_data() -> None:
    spec = GeometrySpec(kind=ShapeKind.PATH, d="M 40 40 L 60 60")
    out = apply_modifiers(spec, ["bigger"])
    assert out.d == "M 37 37 L 63 63"
    pathdata.parse(out.d or "")  # still valid


def test_smaller_scales_text_font() -> None:
    spec = GeometrySpec(kind=ShapeKind.TEXT, label="hi", font_size=10)
    out = apply_modifiers(spec, ["smaller"])
    assert out.font_size == pytest.approx(7.0)


def test_group_bigger_keeps_arrangement_with_v2_parts() -> None:
    scene = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[
            GeometrySpec(
                kind=ShapeKind.POLYGON, name="face", points=[(40, 40), (60, 40), (50, 60)]
            ),
            GeometrySpec(kind=ShapeKind.TEXT, label="cube", x=50, y=80, font_size=4),
        ],
    )
    out = apply_modifiers(scene, ["bigger"])
    face, text = out.parts
    # The polygon grew about the box center; the label moved outward with it.
    assert face.points == [(37.0, 37.0), (63.0, 37.0), (50.0, 63.0)]
    assert text.y == pytest.approx(89.0)
    assert text.font_size == pytest.approx(5.2)
    # Names and labels ride along untouched.
    assert face.name == "face" and text.label == "cube"


def test_color_recurses_into_v2_parts() -> None:
    scene = GeometrySpec(
        kind=ShapeKind.GROUP,
        parts=[GeometrySpec(kind=ShapeKind.POLYGON, points=[(10, 10), (90, 10), (50, 80)])],
    )
    out = apply_modifiers(scene, ["color:#dc2626"])
    assert out.parts[0].stroke == "#dc2626"


def test_fill_style_serializes() -> None:
    spec = GeometrySpec(kind=ShapeKind.RECTANGLE, fill="#eee", fill_style=FillStyle.NONE)
    again = GeometrySpec.model_validate_json(spec.cache_key())
    assert again.fill_style is FillStyle.NONE
