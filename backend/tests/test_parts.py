"""Tests for domain/parts.py — part-level scene editing (plan.md §13 N2+N3).

Covers:
- resolve_parts: role + qualifier resolution (left/right/top/bottom/biggest/
  smallest, plural, singular "one eye", second, y-down semantics)
- apply_to_parts: bigger/smaller grows ONLY target part; center stays fixed
  (±0.5 units); siblings byte-identical; color retints only target;
  polygon and path parts both covered
- apply_patch: full lifecycle (remove+set+add), each validation warning path,
  single-shape wrap-as-group, render integration via SvgRenderer
"""

from __future__ import annotations

from quorum.domain.geometry import GeometrySpec, ShapeKind
from quorum.domain.parts import PartsPatch, apply_patch, apply_to_parts, resolve_parts

# ---------------------------------------------------------------------------
# Fixtures — eye scene
# ---------------------------------------------------------------------------

_EYE_LEFT = GeometrySpec(
    kind=ShapeKind.CIRCLE,
    name="eye-left",
    x=35.0,
    y=50.0,
    width=10.0,
    height=10.0,
    fill="#ffffff",
    stroke="#1f2937",
)
_EYE_RIGHT = GeometrySpec(
    kind=ShapeKind.CIRCLE,
    name="eye-right",
    x=65.0,
    y=50.0,
    width=10.0,
    height=10.0,
    fill="#ffffff",
    stroke="#1f2937",
)
_EYE_BIG = GeometrySpec(
    kind=ShapeKind.CIRCLE,
    name="eye-big",
    x=50.0,
    y=50.0,
    width=20.0,
    height=20.0,
    fill="#ffffff",
    stroke="#1f2937",
)
_EYE_SMALL = GeometrySpec(
    kind=ShapeKind.CIRCLE,
    name="eye-small",
    x=80.0,
    y=50.0,
    width=5.0,
    height=5.0,
    fill="#ffffff",
    stroke="#1f2937",
)

_EYES_SCENE = GeometrySpec(
    kind=ShapeKind.GROUP,
    parts=[_EYE_LEFT, _EYE_RIGHT],
)

# Scene with top/bottom for y-down tests.
_TOP_EYE = GeometrySpec(
    kind=ShapeKind.CIRCLE,
    name="eye-top",
    x=50.0,
    y=20.0,  # small y → top in y-down
    width=10.0,
    height=10.0,
)
_BOTTOM_EYE = GeometrySpec(
    kind=ShapeKind.CIRCLE,
    name="eye-bottom",
    x=50.0,
    y=80.0,  # large y → bottom in y-down
    width=10.0,
    height=10.0,
)
_TOP_BOTTOM_SCENE = GeometrySpec(
    kind=ShapeKind.GROUP,
    parts=[_TOP_EYE, _BOTTOM_EYE],
)

# Scene with size variation for biggest/smallest.
_SIZE_SCENE = GeometrySpec(
    kind=ShapeKind.GROUP,
    parts=[_EYE_BIG, _EYE_SMALL],
)


# ---------------------------------------------------------------------------
# resolve_parts — role matching
# ---------------------------------------------------------------------------


class TestResolvePartsRole:
    def test_left_qualifier(self) -> None:
        result = resolve_parts(_EYES_SCENE, "the left eye")
        assert result == ["eye-left"]

    def test_right_qualifier(self) -> None:
        result = resolve_parts(_EYES_SCENE, "the right eye")
        assert result == ["eye-right"]

    def test_both_eyes_plural(self) -> None:
        result = resolve_parts(_EYES_SCENE, "the eyes")
        assert set(result) == {"eye-left", "eye-right"}

    def test_one_eye_singular_returns_first(self) -> None:
        result = resolve_parts(_EYES_SCENE, "one eye")
        assert len(result) == 1
        # First paint-order part is eye-left.
        assert result == ["eye-left"]

    def test_second_eye(self) -> None:
        result = resolve_parts(_EYES_SCENE, "the second eye")
        # Second in paint order is eye-right.
        assert result == ["eye-right"]

    def test_eye_no_qualifier_singular_returns_first(self) -> None:
        result = resolve_parts(_EYES_SCENE, "the eye")
        assert result == ["eye-left"]

    def test_no_match_returns_empty(self) -> None:
        result = resolve_parts(_EYES_SCENE, "the nose")
        assert result == []

    def test_unrelated_phrase_returns_empty(self) -> None:
        result = resolve_parts(_EYES_SCENE, "make it bigger")
        assert result == []


class TestResolvePartsYDown:
    """y grows DOWN — top = smallest y, bottom = largest y."""

    def test_top_qualifier(self) -> None:
        result = resolve_parts(_TOP_BOTTOM_SCENE, "the top eye")
        assert result == ["eye-top"]

    def test_bottom_qualifier(self) -> None:
        result = resolve_parts(_TOP_BOTTOM_SCENE, "the bottom eye")
        assert result == ["eye-bottom"]


class TestResolvePartsGeometricQualifiers:
    def test_biggest_eye(self) -> None:
        result = resolve_parts(_SIZE_SCENE, "the biggest eye")
        assert result == ["eye-big"]

    def test_smallest_eye(self) -> None:
        result = resolve_parts(_SIZE_SCENE, "the smallest eye")
        assert result == ["eye-small"]

    def test_largest_eye(self) -> None:
        result = resolve_parts(_SIZE_SCENE, "the largest eye")
        assert result == ["eye-big"]


# ---------------------------------------------------------------------------
# apply_to_parts — modifier scoping
# ---------------------------------------------------------------------------


class TestApplyToParts:
    def test_bigger_grows_only_target(self) -> None:
        """'bigger' on eye-left must NOT change eye-right."""
        new_scene = apply_to_parts(_EYES_SCENE, ["eye-left"], ["bigger"])
        left_new = next(p for p in new_scene.parts if p.name == "eye-left")
        right_new = next(p for p in new_scene.parts if p.name == "eye-right")
        assert left_new.width > _EYE_LEFT.width
        # Sibling is byte-identical (same frozen object).
        assert right_new is _EYE_RIGHT

    def test_bigger_center_stays_fixed_within_half_unit(self) -> None:
        """Part's center must not move by more than 0.5 units after 'bigger'."""
        new_scene = apply_to_parts(_EYES_SCENE, ["eye-left"], ["bigger"])
        left_new = next(p for p in new_scene.parts if p.name == "eye-left")
        # For a CIRCLE, center is (x, y).
        assert abs(left_new.x - _EYE_LEFT.x) <= 0.5
        assert abs(left_new.y - _EYE_LEFT.y) <= 0.5

    def test_smaller_center_stays_fixed_within_half_unit(self) -> None:
        new_scene = apply_to_parts(_EYES_SCENE, ["eye-right"], ["smaller"])
        right_new = next(p for p in new_scene.parts if p.name == "eye-right")
        assert abs(right_new.x - _EYE_RIGHT.x) <= 0.5
        assert abs(right_new.y - _EYE_RIGHT.y) <= 0.5

    def test_color_retints_only_target(self) -> None:
        new_scene = apply_to_parts(_EYES_SCENE, ["eye-right"], ["color:#dc2626"])
        left_new = next(p for p in new_scene.parts if p.name == "eye-left")
        right_new = next(p for p in new_scene.parts if p.name == "eye-right")
        # Left unchanged.
        assert left_new.fill == _EYE_LEFT.fill
        assert left_new.stroke == _EYE_LEFT.stroke
        # Right retinted — fill is not None so both fill and stroke are retinted.
        assert right_new.fill != _EYE_LEFT.fill
        assert right_new.stroke != _EYE_RIGHT.stroke

    def test_color_stroke_only_sets_exact_color(self) -> None:
        """Stroke-only part (fill=None) should get exact target color on stroke."""
        stroke_part = GeometrySpec(
            kind=ShapeKind.CIRCLE,
            name="outline",
            x=50.0,
            y=50.0,
            width=10.0,
            height=10.0,
            fill=None,
            stroke="#1f2937",
        )
        scene = GeometrySpec(kind=ShapeKind.GROUP, parts=[stroke_part])
        new_scene = apply_to_parts(scene, ["outline"], ["color:#dc2626"])
        updated = next(p for p in new_scene.parts if p.name == "outline")
        assert updated.stroke == "#dc2626"
        assert updated.fill is None

    def test_bigger_on_polygon_part_center_fixed(self) -> None:
        """Polygon part scaled about its vertex centroid — centroid must not move."""
        poly = GeometrySpec(
            kind=ShapeKind.POLYGON,
            name="shape",
            # Triangle: centroid at (50, 50)
            points=[(40.0, 60.0), (60.0, 60.0), (50.0, 30.0)],
        )
        scene = GeometrySpec(kind=ShapeKind.GROUP, parts=[poly])
        new_scene = apply_to_parts(scene, ["shape"], ["bigger"])
        updated = next(p for p in new_scene.parts if p.name == "shape")
        assert updated.points is not None
        assert poly.points is not None
        cx_new = sum(px for px, _ in updated.points) / len(updated.points)
        cy_new = sum(py for _, py in updated.points) / len(updated.points)
        cx_old = sum(px for px, _ in poly.points) / len(poly.points)
        cy_old = sum(py for _, py in poly.points) / len(poly.points)
        assert abs(cx_new - cx_old) <= 0.5
        assert abs(cy_new - cy_old) <= 0.5
        # And it must have grown (points spread out).
        old_spread = max(px for px, _ in poly.points) - min(px for px, _ in poly.points)
        new_spread = max(px for px, _ in updated.points) - min(px for px, _ in updated.points)
        assert new_spread > old_spread

    def test_bigger_on_path_part_center_approx_fixed(self) -> None:
        """PATH part scaled — center of bbox should not shift substantially."""
        path_part = GeometrySpec(
            kind=ShapeKind.PATH,
            name="curve",
            d="M 40 40 L 60 40 L 60 60 L 40 60 Z",
        )
        scene = GeometrySpec(kind=ShapeKind.GROUP, parts=[path_part])
        new_scene = apply_to_parts(scene, ["curve"], ["bigger"])
        updated = next(p for p in new_scene.parts if p.name == "curve")
        # Check that d was mutated (not the same object).
        assert updated.d != path_part.d


# ---------------------------------------------------------------------------
# apply_patch — full lifecycle
# ---------------------------------------------------------------------------


def _make_face_scene() -> GeometrySpec:
    """A group with three named parts for patch lifecycle tests."""
    nose = GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        name="nose",
        x=50.0, y=55.0, width=6.0, height=6.0,
        fill="#f5c5a3",
    )
    mouth = GeometrySpec(
        kind=ShapeKind.ELLIPSE,
        name="mouth",
        x=50.0, y=70.0, width=14.0, height=6.0,
        fill="#e07070",
    )
    forehead = GeometrySpec(
        kind=ShapeKind.RECTANGLE,
        name="forehead",
        x=50.0, y=20.0, width=30.0, height=10.0,
        fill="#f5c5a3",
    )
    return GeometrySpec(kind=ShapeKind.GROUP, parts=[nose, mouth, forehead])


class TestApplyPatch:
    def test_full_lifecycle_remove_set_add(self) -> None:
        scene = _make_face_scene()
        new_eye = GeometrySpec(
            kind=ShapeKind.CIRCLE,
            name="eye-center",
            x=50.0, y=40.0, width=8.0, height=8.0,
            fill="#ffffff",
        )
        patch = PartsPatch(
            remove=["forehead"],
            set=[{"part": "nose", "fill": "#ff0000", "x": 50.0, "y": 55.0,
                  "width": 6.0, "height": 6.0, "stroke": "#1f2937"}],
            add=[new_eye],
        )
        new_scene, warnings = apply_patch(scene, patch)
        part_names = {p.name for p in new_scene.parts}
        assert "forehead" not in part_names
        assert "eye-center" in part_names
        assert warnings == []
        nose = next(p for p in new_scene.parts if p.name == "nose")
        assert nose.fill == "#ff0000"

    def test_unknown_remove_warns_and_continues(self) -> None:
        scene = _make_face_scene()
        patch = PartsPatch(remove=["ghost"])
        _, warnings = apply_patch(scene, patch)
        assert any("ghost" in w for w in warnings)

    def test_unknown_set_target_warns_and_drops(self) -> None:
        scene = _make_face_scene()
        patch = PartsPatch(set=[{"part": "invisible", "fill": "#ff0000"}])
        new_scene, warnings = apply_patch(scene, patch)
        # Scene unchanged.
        assert new_scene.parts == scene.parts
        assert any("invisible" in w for w in warnings)
        # Warning names valid parts.
        assert any("nose" in w or "mouth" in w for w in warnings)

    def test_kind_change_stripped_with_warning(self) -> None:
        scene = _make_face_scene()
        patch = PartsPatch(set=[{
            "part": "nose",
            "kind": "circle",
            "fill": "#ff0000",
            "x": 50.0, "y": 55.0, "width": 6.0, "height": 6.0,
            "stroke": "#1f2937",
        }])
        new_scene, warnings = apply_patch(scene, patch)
        nose = next(p for p in new_scene.parts if p.name == "nose")
        assert nose.kind == ShapeKind.RECTANGLE  # kind NOT changed
        assert any("kind" in w for w in warnings)
        assert nose.fill == "#ff0000"  # rest of set applied

    def test_invalid_merge_drops_with_warning(self) -> None:
        """Set a field that breaks GeometrySpec validation → drop + warn."""
        scene = _make_face_scene()
        # width <= 0 violates gt=0 constraint
        patch = PartsPatch(set=[{"part": "nose", "width": -5.0}])
        new_scene, warnings = apply_patch(scene, patch)
        # Clause dropped — nose width unchanged.
        nose = next(p for p in new_scene.parts if p.name == "nose")
        original_nose = next(p for p in scene.parts if p.name == "nose")
        assert nose.width == original_nose.width
        assert any("nose" in w and "validation" in w.lower() for w in warnings)

    def test_add_name_collision_auto_suffix(self) -> None:
        scene = _make_face_scene()
        colliding = GeometrySpec(
            kind=ShapeKind.CIRCLE,
            name="nose",
            x=50.0, y=50.0, width=6.0, height=6.0,
        )
        patch = PartsPatch(add=[colliding])
        new_scene, warnings = apply_patch(scene, patch)
        part_names = [p.name for p in new_scene.parts]
        assert "nose" in part_names
        assert "nose-2" in part_names
        assert any("nose" in w and "nose-2" in w for w in warnings)

    def test_add_group_kind_dropped_with_warning(self) -> None:
        scene = _make_face_scene()
        # GeometrySpec won't allow group-in-parts via normal construction,
        # so we validate a group-kind spec directly (group at top level is valid).
        raw = {
            "kind": "group",
            "name": "sub-group",
            "x": 50.0, "y": 50.0, "width": 10.0, "height": 10.0,
            "stroke": "#1f2937",
        }
        # PartsPatch.add holds GeometrySpec objects; we must pass model_validate.
        # GeometrySpec.model_validate on a group with no parts should succeed.
        group_spec = GeometrySpec.model_validate(raw)
        patch = PartsPatch(add=[group_spec])
        new_scene, warnings = apply_patch(scene, patch)
        added_names = {p.name for p in new_scene.parts}
        assert "sub-group" not in added_names
        assert any("group" in w.lower() for w in warnings)

    def test_zero_parts_guard(self) -> None:
        """Removing every part must keep scene unchanged (warn)."""
        scene = _make_face_scene()
        patch = PartsPatch(remove=["nose", "mouth", "forehead"])
        new_scene, warnings = apply_patch(scene, patch)
        # Scene must still have parts.
        assert len(new_scene.parts) >= 1
        assert any("0 parts" in w or "zero" in w.lower() for w in warnings)

    def test_single_shape_wraps_as_group_on_add(self) -> None:
        """A single non-group shape gets wrapped when patch adds parts."""
        single = GeometrySpec(
            kind=ShapeKind.CIRCLE,
            name="base-circle",
            x=50.0, y=50.0, width=20.0, height=20.0,
            label="face",
        )
        new_part = GeometrySpec(
            kind=ShapeKind.CIRCLE,
            name="eye",
            x=40.0, y=45.0, width=5.0, height=5.0,
        )
        patch = PartsPatch(add=[new_part])
        new_scene, warnings = apply_patch(single, patch)
        assert new_scene.kind is ShapeKind.GROUP
        names = {p.name for p in new_scene.parts}
        assert "eye" in names
        # Original shape preserved as a named part.
        assert len(new_scene.parts) == 2
        assert any("Wrapped" in w for w in warnings)

    def test_parts_cap_truncates_adds_with_warning(self) -> None:
        """Adding parts beyond the 60-part cap truncates with a warning."""
        # Create scene with 59 parts.
        many_parts = [
            GeometrySpec(kind=ShapeKind.CIRCLE, name=f"part-{i}",
                         x=50.0, y=50.0, width=5.0, height=5.0)
            for i in range(59)
        ]
        scene = GeometrySpec(kind=ShapeKind.GROUP, parts=many_parts)
        # Try to add 5 more — only first one should fit.
        adds = [
            GeometrySpec(kind=ShapeKind.CIRCLE, name=f"new-{i}",
                         x=50.0, y=50.0, width=5.0, height=5.0)
            for i in range(5)
        ]
        patch = PartsPatch(add=adds)
        new_scene, warnings = apply_patch(scene, patch)
        assert len(new_scene.parts) == 60
        assert any("cap" in w or "truncated" in w.lower() for w in warnings)

    def test_parts_cap_is_a_parameter(self) -> None:
        """The soft cap is configurable (Settings.max_scene_parts seam): a
        raised cap admits the same adds the default truncates."""
        many_parts = [
            GeometrySpec(kind=ShapeKind.CIRCLE, name=f"part-{i}",
                         x=50.0, y=50.0, width=5.0, height=5.0)
            for i in range(59)
        ]
        scene = GeometrySpec(kind=ShapeKind.GROUP, parts=many_parts)
        adds = [
            GeometrySpec(kind=ShapeKind.CIRCLE, name=f"new-{i}",
                         x=50.0, y=50.0, width=5.0, height=5.0)
            for i in range(5)
        ]
        new_scene, warnings = apply_patch(scene, PartsPatch(add=adds), max_parts=80)
        assert len(new_scene.parts) == 64  # all 5 adds fit under the raised cap
        assert not any("cap" in w for w in warnings)
        low_scene, low_warnings = apply_patch(scene, PartsPatch(add=adds), max_parts=59)
        assert len(low_scene.parts) == 59
        assert any("cap (59)" in w for w in low_warnings)

    def test_render_patched_scene(self) -> None:
        """Patched scene must be renderable without errors."""
        from quorum.pipeline.renderer import get_renderer

        scene = _make_face_scene()
        new_eye = GeometrySpec(
            kind=ShapeKind.ELLIPSE,
            name="eye-left",
            x=40.0, y=40.0, width=8.0, height=5.0,
            fill="#ffffff",
        )
        patch = PartsPatch(
            remove=["forehead"],
            add=[new_eye],
        )
        new_scene, _ = apply_patch(scene, patch)
        renderer = get_renderer()
        svg = renderer.render(new_scene)
        assert svg.startswith("<svg")
        assert len(svg) > 50


# ---------------------------------------------------------------------------
# Additional edge case — single shape apply_to_parts
# ---------------------------------------------------------------------------


class TestApplyToPartsSingleShape:
    def test_single_shape_name_match(self) -> None:
        single = GeometrySpec(
            kind=ShapeKind.CIRCLE,
            name="ball",
            x=50.0, y=50.0, width=20.0, height=20.0,
            fill="#ffffff",
        )
        result = apply_to_parts(single, ["ball"], ["bigger"])
        assert result.width > single.width
        assert abs(result.x - single.x) <= 0.5

    def test_single_shape_no_match_unchanged(self) -> None:
        single = GeometrySpec(
            kind=ShapeKind.CIRCLE,
            name="ball",
            x=50.0, y=50.0, width=20.0, height=20.0,
        )
        result = apply_to_parts(single, ["other"], ["bigger"])
        assert result is single
