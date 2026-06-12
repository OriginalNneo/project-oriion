"""Part-level scene editing — pure domain module (plan.md §13 N2+N3).

Three public entry points:

* :func:`resolve_parts` — resolve a spoken phrase ("the left eye") to a list of
  part names by role-token matching + geometric qualifiers computed in code.
* :func:`apply_to_parts` — fold the standard modifier vocabulary onto ONLY the
  named parts, scaling each part about ITS OWN center (so "make the left eye
  bigger" grows the eye in place, not the whole scene).
* :func:`apply_patch` — apply a ``PartsPatch`` (set / add / remove) in a single
  validated pass; returns (new_scene, warnings).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from quorum.domain import pathdata
from quorum.domain.color import retint
from quorum.domain.geometry import GeometrySpec, ShapeKind

# ---------------------------------------------------------------------------
# PartsPatch model
# ---------------------------------------------------------------------------


class PartsPatch(BaseModel):
    """Set/add/remove delta the LLM emits instead of re-emitting the scene."""

    model_config = {"frozen": True}

    set: list[dict[str, Any]] = Field(default_factory=list)
    add: list[GeometrySpec] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers — name tokenization
# ---------------------------------------------------------------------------

_SEP_RE = re.compile(r"[-_\s]+")


def _name_tokens(name: str) -> frozenset[str]:
    """Split a part name on separators and return lowercase tokens."""
    return frozenset(t for t in _SEP_RE.split(name.lower()) if t)


def _phrase_tokens(phrase: str) -> list[str]:
    """Tokenize the incoming phrase to lowercase words."""
    return [t for t in _SEP_RE.split(phrase.lower()) if t]


# ---------------------------------------------------------------------------
# Geometric qualifier helpers
# ---------------------------------------------------------------------------

_QUALIFIERS = frozenset(
    {
        "left", "right", "top", "bottom",
        "biggest", "largest", "smallest", "widest", "tallest",
        "first", "last", "second",
    }
)


def _bbox(part: GeometrySpec) -> tuple[float, float, float, float]:
    """Return (x_min, y_min, x_max, y_max) bounding box for a part.

    For polygons, bounds of vertices.  For paths, rough bounds via bounding box
    of the explicit coordinates (good enough for qualifier resolution).
    Everything else: center ± half-width/height.
    """
    if part.points is not None:
        pxs = [px for px, _ in part.points]
        pys = [py for _, py in part.points]
        return min(pxs), min(pys), max(pxs), max(pys)
    if part.d is not None:
        cmds = pathdata.parse(part.d)
        xs: list[float] = []
        ys: list[float] = []
        for cmd, vals in cmds:
            if cmd in ("M", "L", "C", "Q"):
                for i in range(0, len(vals) - 1, 2):
                    xs.append(vals[i])
                    ys.append(vals[i + 1])
            elif cmd == "H":
                xs.extend(vals)
            elif cmd == "V":
                ys.extend(vals)
            elif cmd == "A" and len(vals) == 7:
                xs.append(vals[5])
                ys.append(vals[6])
        if xs and ys:
            return min(xs), min(ys), max(xs), max(ys)
    hw = part.width / 2.0
    hh = part.height / 2.0
    return part.x - hw, part.y - hh, part.x + hw, part.y + hh


def _center(part: GeometrySpec) -> tuple[float, float]:
    """Return the center of a part.

    Polygon: vertex centroid.  Everything else: (x, y).
    """
    if part.points is not None:
        n = len(part.points)
        cx = sum(px for px, _ in part.points) / n
        cy = sum(py for _, py in part.points) / n
        return cx, cy
    return part.x, part.y


def _bbox_area(part: GeometrySpec) -> float:
    x0, y0, x1, y1 = _bbox(part)
    return (x1 - x0) * (y1 - y0)


def _bbox_width(part: GeometrySpec) -> float:
    x0, _, x1, _ = _bbox(part)
    return x1 - x0


def _bbox_height(part: GeometrySpec) -> float:
    _, y0, _, y1 = _bbox(part)
    return y1 - y0


# ---------------------------------------------------------------------------
# resolve_parts
# ---------------------------------------------------------------------------


def resolve_parts(scene: GeometrySpec, phrase: str) -> list[str]:
    """Resolve a spoken phrase to a list of addressable part names.

    Resolution rules (applied in order):

    1. **Role match** — for each part whose ``name`` shares at least one token
       with the phrase tokens, count how many phrase tokens are in the part's
       name tokens ("left eye" → eye-left scores 2 out of 2, eye-right scores 1).
    2. **Multi-match disambiguation** — if multiple parts tie on token-overlap:
       a. A **geometric qualifier** in the phrase selects the part whose geometry
          satisfies it (centroid x for left/right; centroid y (y grows DOWN) for
          top/bottom; bbox area for biggest/smallest; bbox width for widest; bbox
          height for tallest; paint-order index for first/second/last).
       b. "the eyes" / plural role with no qualifier → ALL role matches.
       c. "one eye" / singular with no qualifier → the first match (lowest index).
    3. **No role match at all** → empty list (caller falls back or escalates).
    """
    parts = scene.parts if scene.kind is ShapeKind.GROUP else [scene]
    named = [p for p in parts if p.name]

    phrase_toks = _phrase_tokens(phrase)
    phrase_set = frozenset(phrase_toks)
    # Also include depluralised forms so "eyes" can match against "eye" in a
    # part name.  Strategy: for any token ending in 's', add the version with
    # the trailing 's' stripped.  Also add the version with 'es' stripped for
    # tokens ending in 'es' (handles "boxes" → "box").  Always try -s first
    # since it covers "eyes" → "eye" correctly.
    singular_extras: set[str] = set()
    for tok in phrase_toks:
        if tok.endswith("s") and len(tok) > 2:
            singular_extras.add(tok[:-1])          # "eyes" → "eye", "boxes" → "boxe"
        if tok.endswith("es") and len(tok) > 3:
            singular_extras.add(tok[:-2])          # "boxes" → "box"
    expanded_phrase_set: frozenset[str] = phrase_set | frozenset(singular_extras)

    # Step 1 — score each named part by how many phrase tokens hit its name tokens.
    # Use expanded_phrase_set so plurals match singular name tokens.
    scored: list[tuple[int, int, GeometrySpec]] = []  # (score, paint_idx, part)
    for idx, part in enumerate(named):
        assert part.name is not None
        nt = _name_tokens(part.name)
        score = len(expanded_phrase_set & nt)
        if score > 0:
            scored.append((score, idx, part))

    if not scored:
        return []

    max_score = max(s for s, _, _ in scored)
    candidates = [(idx, part) for s, idx, part in scored if s == max_score]

    if len(candidates) == 1:
        name = candidates[0][1].name
        assert name is not None
        return [name]

    # Step 2 — check for geometric qualifiers
    qualifier_tokens = phrase_set & _QUALIFIERS
    if qualifier_tokens:
        # Apply each qualifier to narrow candidates.  Multiple qualifiers are
        # AND-ed: each one filters down the current candidate set.
        result = candidates[:]
        for qual in qualifier_tokens:
            if qual == "left":
                best = min(result, key=lambda ic: _center(ic[1])[0])
                cx = _center(best[1])[0]
                result = [(i, p) for i, p in result if abs(_center(p)[0] - cx) < 0.5]
            elif qual == "right":
                best = max(result, key=lambda ic: _center(ic[1])[0])
                cx = _center(best[1])[0]
                result = [(i, p) for i, p in result if abs(_center(p)[0] - cx) < 0.5]
            elif qual == "top":
                # y grows DOWN in 0..100 box → top = smallest y
                best = min(result, key=lambda ic: _center(ic[1])[1])
                cy = _center(best[1])[1]
                result = [(i, p) for i, p in result if abs(_center(p)[1] - cy) < 0.5]
            elif qual == "bottom":
                best = max(result, key=lambda ic: _center(ic[1])[1])
                cy = _center(best[1])[1]
                result = [(i, p) for i, p in result if abs(_center(p)[1] - cy) < 0.5]
            elif qual in ("biggest", "largest"):
                best = max(result, key=lambda ic: _bbox_area(ic[1]))
                ba = _bbox_area(best[1])
                result = [(i, p) for i, p in result if abs(_bbox_area(p) - ba) < 0.01]
            elif qual == "smallest":
                best = min(result, key=lambda ic: _bbox_area(ic[1]))
                ba = _bbox_area(best[1])
                result = [(i, p) for i, p in result if abs(_bbox_area(p) - ba) < 0.01]
            elif qual == "widest":
                best = max(result, key=lambda ic: _bbox_width(ic[1]))
                bw = _bbox_width(best[1])
                result = [(i, p) for i, p in result if abs(_bbox_width(p) - bw) < 0.01]
            elif qual == "tallest":
                best = max(result, key=lambda ic: _bbox_height(ic[1]))
                bh = _bbox_height(best[1])
                result = [(i, p) for i, p in result if abs(_bbox_height(p) - bh) < 0.01]
            elif qual == "first":
                result = [min(result, key=lambda ic: ic[0])]
            elif qual == "last":
                result = [max(result, key=lambda ic: ic[0])]
            elif qual == "second":
                sorted_r = sorted(result, key=lambda ic: ic[0])
                result = [sorted_r[1]] if len(sorted_r) >= 2 else sorted_r[:1]
        names = [p.name for _, p in result if p.name]
        return names if names else []

    # Step 3 — no qualifier: check for plurality cues
    # "the eyes" (plural noun) → all matches
    # "one eye" → first match only
    # "the eye" (singular, no qualifier) → first match
    #
    # Collect the role tokens that drove the match (using expanded set so that
    # "eyes" → "eye" is in the intersection).
    role_matched_tokens: set[str] = set()
    for _, part in candidates:
        assert part.name is not None
        nt = _name_tokens(part.name)
        role_matched_tokens |= expanded_phrase_set & nt

    # Detect explicit plural cue: does the phrase contain a plural form of any
    # role-matched token?  e.g. role_matched = {"eye"}, phrase has "eyes" → plural.
    is_plural = _has_plural_token(phrase_toks, role_matched_tokens)

    if is_plural:
        return [p.name for _, p in candidates if p.name]

    # Singular / ambiguous → first match (lowest paint-order index)
    first = min(candidates, key=lambda ic: ic[0])
    name = first[1].name
    assert name is not None
    return [name]


def _has_plural_token(phrase_toks: list[str], role_tokens: set[str]) -> bool:
    """Return True if the phrase contains a plural form of any role token."""
    for tok in phrase_toks:
        # check "eyes" → "eye", "boxes" → "box" etc.
        for role in role_tokens:
            if tok == role + "s" or tok == role + "es":
                return True
    return False


# ---------------------------------------------------------------------------
# _scale_part_about_center — part-local scaling
# ---------------------------------------------------------------------------

def _scale_part_about_center(
    part: GeometrySpec, scale: float
) -> GeometrySpec:
    """Scale a single part about ITS OWN center, clamped to [0, 100].

    This is the key difference from ``geometry.apply_modifiers``, which scales
    about the canvas center (50, 50).  Here the center is the part's centroid
    so the part grows in place.
    """
    cx, cy = _center(part)

    def sx(v: float) -> float:
        return min(100.0, max(0.0, cx + (v - cx) * scale))

    def sy(v: float) -> float:
        return min(100.0, max(0.0, cy + (v - cy) * scale))

    updates: dict[str, object] = {}

    if part.points is not None:
        updates["points"] = [(sx(px), sy(py)) for px, py in part.points]
    elif part.d is not None:
        updates["d"] = pathdata.transform(
            part.d, fx=sx, fy=sy, fr=lambda r: max(0.1, r * scale)
        )
    else:
        # Standard box geometry: keep center fixed, scale dimensions.
        new_w = min(100.0, max(1.0, part.width * scale))
        new_h = min(100.0, max(1.0, part.height * scale))
        # x,y are the center; no repositioning needed (center stays).
        updates["width"] = new_w
        updates["height"] = new_h

    if updates:
        return part.model_copy(update=updates)
    return part


# ---------------------------------------------------------------------------
# apply_to_parts
# ---------------------------------------------------------------------------


def apply_to_parts(
    scene: GeometrySpec, names: list[str], modifiers: list[str]
) -> GeometrySpec:
    """Apply modifiers to ONLY the named parts, each scaled about its own center.

    Modifier vocabulary mirrors ``geometry.apply_modifiers``:
    ``bigger``, ``smaller``, ``color:<hex>``, ``fillet``/``rounded``,
    ``radius:<n>``.

    If ``scene`` is not a GROUP, it is treated as its own sole part (name match
    checks against the scene's own ``name`` or any modifier applies to it
    directly).

    Parts NOT in ``names`` are returned byte-identical (same frozen object).
    """
    if scene.kind is not ShapeKind.GROUP:
        # Single shape — check if name matches; apply if so.
        if scene.name in names or names == [scene.name]:
            return _apply_mods_to_part(scene, modifiers)
        return scene

    new_parts: list[GeometrySpec] = []
    for part in scene.parts:
        if part.name in names:
            new_parts.append(_apply_mods_to_part(part, modifiers))
        else:
            new_parts.append(part)
    return scene.model_copy(update={"parts": new_parts})


def _apply_mods_to_part(part: GeometrySpec, modifiers: list[str]) -> GeometrySpec:
    """Fold all modifiers onto a single part, scaling about the part's center."""
    scale = 1.0
    updates: dict[str, object] = {}

    for mod in modifiers:
        m = mod.strip().lower()
        if m == "bigger":
            scale *= 1.3
        elif m == "smaller":
            scale *= 0.7
        elif m in ("fillet", "rounded"):
            updates["corner_radius"] = max(part.corner_radius, 12.0)
        elif m.startswith("radius:"):
            try:
                updates["corner_radius"] = min(50.0, max(0.0, float(m.split(":", 1)[1])))
            except ValueError:
                pass
        elif m.startswith("color:"):
            color = m.split(":", 1)[1].strip()
            if color:
                if part.fill is not None:
                    updates["fill"] = retint(part.fill, color)
                    updates["stroke"] = retint(part.stroke, color)
                else:
                    updates["stroke"] = color

    # Apply non-scale updates first.
    working = part.model_copy(update=updates) if updates else part

    # Then apply size scaling about the part's own center.
    if scale != 1.0:
        working = _scale_part_about_center(working, scale)

    return working


# ---------------------------------------------------------------------------
# apply_patch
# ---------------------------------------------------------------------------

_MAX_PARTS = 60


def apply_patch(
    scene: GeometrySpec, patch: PartsPatch
) -> tuple[GeometrySpec, list[str]]:
    """Apply a PartsPatch (remove → set → add) to a scene, with validation.

    Returns (new_scene, warnings) where warnings is a list of human-readable
    strings describing dropped/modified clauses.

    Rules:
    - ``remove`` of unknown name → warn, continue.
    - Removing ALL parts: if result would have 0 parts, keep the scene for
      the remove step (warn).
    - ``set`` entry with unknown ``part`` → drop clause, warn with valid names.
    - ``set`` may not change ``kind`` → strip key, warn.
    - ``set`` merges fields into part dict then re-validates; if validation
      fails → drop clause, warn.
    - ``add`` name collision → auto-suffix -2/-3/… and warn.
    - ``add`` kind=group → drop, warn.
    - Parts cap: 60.  Truncate adds beyond cap with a warning.
    - If scene is a single (non-GROUP) shape and the patch adds parts: wrap it
      as a group first, with the original shape named from its label or "base".
    - Result must validate as a GeometrySpec.
    """
    warnings: list[str] = []

    # -----------------------------------------------------------------------
    # Ensure scene is a group when the patch will add parts.
    # -----------------------------------------------------------------------
    if patch.add and scene.kind is not ShapeKind.GROUP:
        base_name = scene.label or "base"
        wrapped = scene.model_copy(update={"name": base_name})
        scene = GeometrySpec(
            kind=ShapeKind.GROUP,
            parts=[wrapped],
        )
        warnings.append(f"Wrapped single shape as group with part name '{base_name}'.")

    # Work on a mutable list of part dicts for the remove/set/add pipeline.
    # For a non-GROUP scene with no adds, parts is an empty list and operations
    # apply to a synthesised one-element list.
    if scene.kind is ShapeKind.GROUP:
        working: list[dict[str, Any]] = [p.model_dump() for p in scene.parts]
        is_group = True
    else:
        # Single non-group shape with no adds: treat as 1-element list.
        working = [scene.model_dump()]
        is_group = False

    def _part_names() -> list[str]:
        return [str(p.get("name", "")) for p in working if p.get("name")]

    # -----------------------------------------------------------------------
    # Step 1 — remove
    # -----------------------------------------------------------------------
    remove_set = set(patch.remove)
    if remove_set:
        unknown_removes = remove_set - set(_part_names())
        for name in sorted(unknown_removes):
            warnings.append(f"remove: unknown part '{name}' — skipped.")
        after_remove = [p for p in working if p.get("name") not in remove_set]
        if len(after_remove) == 0:
            warnings.append(
                "remove: would leave 0 parts — remove step skipped to preserve the scene."
            )
        else:
            working = after_remove

    # -----------------------------------------------------------------------
    # Step 2 — set
    # -----------------------------------------------------------------------
    for clause in patch.set:
        clause = dict(clause)  # shallow copy so we can mutate
        target_name = clause.pop("part", None)
        if target_name is None:
            warnings.append("set: clause missing 'part' key — dropped.")
            continue
        idx = next(
            (i for i, p in enumerate(working) if p.get("name") == target_name), None
        )
        if idx is None:
            valid = _part_names()
            warnings.append(
                f"set: unknown part '{target_name}' — dropped. "
                f"Valid names: {valid!r}."
            )
            continue

        existing = dict(working[idx])
        original_kind = existing.get("kind")

        if "kind" in clause and clause["kind"] != original_kind:
            warnings.append(
                f"set: 'kind' change on part '{target_name}' "
                f"({original_kind!r} → {clause['kind']!r}) — stripped."
            )
            del clause["kind"]

        merged = {**existing, **clause}
        try:
            validated = GeometrySpec.model_validate(merged)
        except Exception as exc:
            warnings.append(
                f"set: merged part '{target_name}' failed validation "
                f"({exc}) — dropped."
            )
            continue

        working[idx] = validated.model_dump()

    # -----------------------------------------------------------------------
    # Step 3 — add
    # -----------------------------------------------------------------------
    existing_names = set(_part_names())
    for new_part in patch.add:
        if new_part.kind is ShapeKind.GROUP:
            warnings.append(
                f"add: kind=group parts are not allowed (name={new_part.name!r}) — dropped."
            )
            continue

        if len(working) >= _MAX_PARTS:
            warnings.append(
                f"add: parts cap ({_MAX_PARTS}) reached — "
                f"'{new_part.name}' and subsequent adds truncated."
            )
            break

        part_name = new_part.name
        if part_name and part_name in existing_names:
            # Auto-suffix
            suffix = 2
            while f"{part_name}-{suffix}" in existing_names:
                suffix += 1
            new_name = f"{part_name}-{suffix}"
            warnings.append(
                f"add: name collision '{part_name}' — renamed to '{new_name}'."
            )
            new_part = new_part.model_copy(update={"name": new_name})
            part_name = new_name

        if part_name:
            existing_names.add(part_name)
        working.append(new_part.model_dump())

    # -----------------------------------------------------------------------
    # Reconstruct the GeometrySpec
    # -----------------------------------------------------------------------
    if is_group or scene.kind is ShapeKind.GROUP:
        validated_parts = [GeometrySpec.model_validate(p) for p in working]
        new_scene = scene.model_copy(update={"parts": validated_parts})
    else:
        # Single-shape, no-group path: apply set fields to the shape itself.
        new_scene = GeometrySpec.model_validate(working[0])

    return new_scene, warnings
