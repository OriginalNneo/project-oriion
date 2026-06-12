"""Deterministic recolor helpers — pure functions, no I/O.

Used by ``apply_modifiers`` to re-tint filled geometry when a ``color:<hex>``
modifier arrives.  The design goal: the target hue/saturation replaces the
original's, but lightness is a blend so the light/mid/dark shading of an
isometric cuboid (three gray faces) survives as light/mid/dark reds after
``retint(face_color, "#dc2626")``.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Hex parsing / formatting
# ---------------------------------------------------------------------------

_HEX_RGB_RE = re.compile(r"^#([0-9a-f]{3})$", re.IGNORECASE)
_HEX_RRGGBB_RE = re.compile(r"^#([0-9a-f]{6})$", re.IGNORECASE)


def parse_hex(color: str) -> tuple[int, int, int] | None:
    """Parse a CSS hex color into an (r, g, b) int triple in [0, 255].

    Accepts ``#rgb`` and ``#rrggbb``, case-insensitive.  Returns ``None`` for
    anything else (named colors, ``rgb()``, etc.).
    """
    s = color.strip()
    m3 = _HEX_RGB_RE.match(s)
    if m3:
        h = m3.group(1)
        r = int(h[0] * 2, 16)
        g = int(h[1] * 2, 16)
        b = int(h[2] * 2, 16)
        return r, g, b
    m6 = _HEX_RRGGBB_RE.match(s)
    if m6:
        h = m6.group(1)
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return r, g, b
    return None


def format_hex(r: int, g: int, b: int) -> str:
    """Format an (r, g, b) triple as lowercase ``#rrggbb``."""
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# RGB ↔ HSL conversion helpers
# ---------------------------------------------------------------------------


def rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert (r, g, b) in [0, 255] to (h, s, li) in [0, 1] each."""
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    cmax = max(rf, gf, bf)
    cmin = min(rf, gf, bf)
    delta = cmax - cmin

    li = (cmax + cmin) / 2.0

    if delta == 0.0:
        h = 0.0
        s = 0.0
    else:
        s = delta / (1.0 - abs(2.0 * li - 1.0))
        if cmax == rf:
            h = ((gf - bf) / delta) % 6.0
        elif cmax == gf:
            h = (bf - rf) / delta + 2.0
        else:
            h = (rf - gf) / delta + 4.0
        h /= 6.0

    return h, s, li


def hsl_to_rgb(h: float, s: float, li: float) -> tuple[int, int, int]:
    """Convert (h, s, li) in [0, 1] each to (r, g, b) in [0, 255]."""
    if s == 0.0:
        v = round(li * 255)
        return v, v, v

    c = (1.0 - abs(2.0 * li - 1.0)) * s
    x = c * (1.0 - abs((h * 6.0) % 2.0 - 1.0))
    m = li - c / 2.0

    hh = h * 6.0
    if hh < 1.0:
        rf, gf, bf = c, x, 0.0
    elif hh < 2.0:
        rf, gf, bf = x, c, 0.0
    elif hh < 3.0:
        rf, gf, bf = 0.0, c, x
    elif hh < 4.0:
        rf, gf, bf = 0.0, x, c
    elif hh < 5.0:
        rf, gf, bf = x, 0.0, c
    else:
        rf, gf, bf = c, 0.0, x

    r = min(255, max(0, round((rf + m) * 255)))
    g = min(255, max(0, round((gf + m) * 255)))
    b = min(255, max(0, round((bf + m) * 255)))
    return r, g, b


# ---------------------------------------------------------------------------
# Core retint function
# ---------------------------------------------------------------------------

# Lightness blend: 70% original + 30% target, clamped so recolored near-whites
# still read as the target color and near-blacks stay legible.
_LIGHTNESS_MIN = 0.08
_LIGHTNESS_MAX = 0.94


def retint(original: str, target: str) -> str:
    """Re-tint *original* toward *target* preserving the original's lightness.

    Returns a color with:
    - hue = target hue
    - saturation = target saturation
    - lightness = clamp(0.7 * orig_L + 0.3 * target_L, 0.08, 0.94)

    This keeps the shading order of a multi-face isometric object monotonic
    (light face stays lighter than mid face stays lighter than dark face) while
    pulling washed-out near-whites toward the target color's body so the
    lightest face of a recolored cuboid still reads as the target hue.

    If *original* is unparseable (e.g. a CSS named color such as "tomato"),
    returns *target* unchanged.  If *target* is unparseable, returns *original*
    unchanged.
    """
    t_rgb = parse_hex(target)
    if t_rgb is None:
        return original  # target not a valid hex → leave original alone

    o_rgb = parse_hex(original)
    if o_rgb is None:
        return target  # original not parseable → fall back to raw target

    t_h, t_s, t_li = rgb_to_hsl(*t_rgb)
    _, _, o_li = rgb_to_hsl(*o_rgb)

    new_li = 0.7 * o_li + 0.3 * t_li
    new_li = max(_LIGHTNESS_MIN, min(_LIGHTNESS_MAX, new_li))

    r, g, b = hsl_to_rgb(t_h, t_s, new_li)
    return format_hex(r, g, b)
