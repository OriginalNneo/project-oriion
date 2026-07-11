// usePanZoom — pan/zoom/fit hook for the IdeaTree canvas (plan.md §15 canvas refactor).
// User intent: "make the mind map window bigger and adaptive, allow to zoom out, better following."
// All pointer events are attached imperatively (never via React props) so we can call
// preventDefault on wheel — React's synthetic onWheel is passive by default (Chrome 73+).
//
// Transform model: translate(tx px, ty px) scale(scale) with transform-origin:0 0.
//   World point under cursor (px,py): wx=(px-tx)/scale, wy=(py-ty)/scale
//   Zoom about cursor: s2=clamp(s*f,0.2,2.5); tx2=px-wx*s2; ty2=py-wy*s2
//   (order matters: translate in screen-space then scale about origin 0 0)

import { useCallback, useEffect, useRef, useState } from "react";

const SCALE_MIN = 0.2;
const SCALE_MAX = 2.5;

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

export interface ViewState {
  scale: number;
  tx: number;
  ty: number;
}

export interface PanZoomHelpers {
  view: ViewState;
  viewportRef: React.RefObject<HTMLDivElement>;
  fit: () => void;
  recenterOn: (cardX: number, cardY: number, cw: number, ch: number) => void;
  /** Zoom about a container-relative point (px,py) by factor f, committing to React state. */
  zoomAboutPoint: (px: number, py: number, factor: number) => void;
  resetUserAdjusted: () => void;
  isGesturing: boolean;
  follow: boolean;
  setFollow: (v: boolean) => void;
  userAdjusted: boolean;
}

interface ContentSize {
  w: number;
  h: number;
  cardCount: number;
}

// usePanZoom attaches imperative pointer+wheel listeners to containerRef.
// viewportRef is assigned by the caller to the .idea-viewport element so the
// hook can toggle transitions on it directly (avoids a React re-render on each frame).
export function usePanZoom(
  containerRef: React.RefObject<HTMLDivElement | null>,
  content: ContentSize,
): PanZoomHelpers {
  const [view, setView] = useState<ViewState>({ scale: 1, tx: 0, ty: 0 });
  const [viewSize, setViewSize] = useState({ w: 0, h: 0 });
  const [isGesturing, setIsGesturing] = useState(false);
  const [follow, setFollow] = useState(true);
  const [userAdjusted, setUserAdjusted] = useState(false);

  // Stable ref for the latest view (avoids stale-closure issues in event handlers).
  const viewRef = useRef(view);
  viewRef.current = view;

  const viewSizeRef = useRef(viewSize);
  viewSizeRef.current = viewSize;

  const contentRef = useRef(content);
  contentRef.current = content;

  const userAdjustedRef = useRef(userAdjusted);
  userAdjustedRef.current = userAdjusted;

  // viewportRef: caller assigns this to the .idea-viewport DOM node.
  const viewportRef = useRef<HTMLDivElement>(null);

  // Active pointer ids for drag/pinch tracking.
  const activePointers = useRef<Map<number, { x: number; y: number }>>(new Map());
  const dragAnchor = useRef<{ startTx: number; startTy: number; px: number; py: number } | null>(null);
  const pinchStart = useRef<{ dist: number; midX: number; midY: number; tx: number; ty: number; scale: number } | null>(null);

  // Apply transform to the DOM element directly (no React state update per frame).
  // React state is updated on gesture end for downstream effects.
  const applyTransform = useCallback((tx: number, ty: number, scale: number, animated: boolean) => {
    const vp = viewportRef.current;
    if (vp) {
      // order matters: translate in screen-space then scale about origin 0 0
      vp.style.transition = animated ? "transform 0.4s ease-out" : "none";
      vp.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    }
    viewRef.current = { scale, tx, ty };
  }, []);

  const commitView = useCallback((tx: number, ty: number, scale: number, animated: boolean) => {
    applyTransform(tx, ty, scale, animated);
    setView({ scale, tx, ty });
  }, [applyTransform]);

  // fit: fill viewport with content, center it.
  const fit = useCallback(() => {
    const { w: vw, h: vh } = viewSizeRef.current;
    const { w: cw, h: ch, cardCount } = contentRef.current;
    if (vw <= 0 || vh <= 0 || cw <= 0 || ch <= 0) return;
    if (cardCount === 1) {
      // Single card: center at scale 1 (or 1.2 max) rather than filling to 2.5.
      const s = clamp(Math.min(vw / cw, vh / ch) * 0.92, SCALE_MIN, 1.2);
      const tx = (vw - cw * s) / 2;
      const ty = (vh - ch * s) / 2;
      commitView(tx, ty, s, true);
    } else {
      const s = clamp(Math.min(vw / cw, vh / ch) * 0.92, SCALE_MIN, SCALE_MAX);
      const tx = (vw - cw * s) / 2;
      const ty = (vh - ch * s) / 2;
      commitView(tx, ty, s, true);
    }
  }, [commitView]);

  // recenterOn: center a specific card (by its layout top-left coords, post-PAD) at current scale.
  // cardX/cardY are the placed.x/placed.y values from layout() — already post-PAD-translate.
  // Coordinate origin: top-left of .idea-canvas (which is also world origin).
  const recenterOn = useCallback((cardX: number, cardY: number, cw: number, ch: number) => {
    const { w: vw, h: vh } = viewSizeRef.current;
    const s = viewRef.current.scale;
    // tx = viewW/2 - (cardX + cw/2)*scale  (center of card maps to center of viewport)
    const tx = vw / 2 - (cardX + cw / 2) * s;
    const ty = vh / 2 - (cardY + ch / 2) * s;
    commitView(tx, ty, s, true);
  }, [commitView]);

  // zoomAboutPoint: zoom by factor about a container-relative point (px,py),
  // committing to React state and marking userAdjusted. Used by ZoomControls +/− buttons.
  const zoomAboutPoint = useCallback((px: number, py: number, factor: number) => {
    const { tx, ty, scale } = viewRef.current;
    const s2 = clamp(scale * factor, SCALE_MIN, SCALE_MAX);
    const wx = (px - tx) / scale;
    const wy = (py - ty) / scale;
    const tx2 = px - wx * s2;
    const ty2 = py - wy * s2;
    commitView(tx2, ty2, s2, true);
    setUserAdjusted(true);
    userAdjustedRef.current = true;
  }, [commitView]);

  const resetUserAdjusted = useCallback(() => {
    setUserAdjusted(false);
    userAdjustedRef.current = false;
  }, []);

  // ResizeObserver: update viewSize from .idea-scroll dimensions.
  // Only update the stored size — fit() is triggered by a separate useEffect
  // to avoid a synchronous ResizeObserver loop (risk #17).
  useEffect(() => {
    // Read ref inside effect body — not outside — so StrictMode double-invoke works (risk #32).
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setViewSize({ w: width, h: height });
    });
    ro.observe(container);
    // Set initial size immediately.
    setViewSize({ w: container.clientWidth, h: container.clientHeight });
    return () => ro.disconnect();
  }, [containerRef]);

  // AUTO-FIT: fire when content extent changes and user has not manually adjusted.
  // Separated from follow effect to avoid fighting (risk #31, #38).
  useEffect(() => {
    if (userAdjusted) return;
    if (viewSize.w <= 0 || viewSize.h <= 0) return;
    if (content.w <= 0 || content.h <= 0) return;
    fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content.w, content.h, viewSize.w, viewSize.h, userAdjusted]);

  // Imperative pointer + wheel event handlers.
  // el is captured at effect-run time and asserted non-null (it was checked on same render).
  useEffect(() => {
    const maybeEl = containerRef.current;
    if (!maybeEl) return;
    // After the null check, TS needs a local const typed as non-null to use in closures.
    const el: HTMLDivElement = maybeEl;

    function pointerDist(a: { x: number; y: number }, b: { x: number; y: number }): number {
      return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
    }

    function onPointerDown(e: PointerEvent) {
      // Don't start a pan if the event originated on zoom controls or a node card (risk #14, #35, #36).
      if ((e.target as Element).closest(".zoom-controls") || (e.target as Element).closest(".node-card")) {
        return;
      }
      activePointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });

      if (activePointers.current.size === 1) {
        // Single pointer: start drag pan.
        dragAnchor.current = {
          startTx: viewRef.current.tx,
          startTy: viewRef.current.ty,
          px: e.clientX,
          py: e.clientY,
        };
        el.setPointerCapture(e.pointerId);
        setIsGesturing(true);
        // Disable CSS transition synchronously before any pointermove fires (risk #30).
        const vp = viewportRef.current;
        if (vp) vp.style.transition = "none";
        el.classList.add("grabbing");
      } else if (activePointers.current.size === 2) {
        // Second pointer: switch from drag to pinch (risk #28).
        if (dragAnchor.current !== null) {
          const firstId = [...activePointers.current.keys()][0];
          el.releasePointerCapture(firstId);
          dragAnchor.current = null;
        }
        el.setPointerCapture(e.pointerId);
        const pts = [...activePointers.current.values()];
        const dist = pointerDist(pts[0], pts[1]);
        const midX = (pts[0].x + pts[1].x) / 2;
        const midY = (pts[0].y + pts[1].y) / 2;
        const { tx, ty, scale } = viewRef.current;
        pinchStart.current = { dist, midX, midY, tx, ty, scale };
      }
    }

    function onPointerMove(e: PointerEvent) {
      if (!activePointers.current.has(e.pointerId)) return;
      activePointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });

      if (activePointers.current.size === 2 && pinchStart.current) {
        // Pinch zoom about mid-point.
        const pts = [...activePointers.current.values()];
        const dist = pointerDist(pts[0], pts[1]);
        const midX = (pts[0].x + pts[1].x) / 2;
        const midY = (pts[0].y + pts[1].y) / 2;
        const rect = el.getBoundingClientRect();
        const px = midX - rect.left;
        const py = midY - rect.top;

        const ps = pinchStart.current;
        const factor = dist / ps.dist;
        const s2 = clamp(ps.scale * factor, SCALE_MIN, SCALE_MAX);
        // World point under initial midpoint (snapshot-relative world origin).
        const wx = (ps.midX - rect.left - ps.tx) / ps.scale;
        const wy = (ps.midY - rect.top - ps.ty) / ps.scale;
        // Scale pivot: zoom about world origin wx/wy.
        // Translation delta: follow the simultaneous finger translation (midpoint drift).
        const tx2 = px - wx * s2 + (midX - ps.midX);
        const ty2 = py - wy * s2 + (midY - ps.midY);
        applyTransform(tx2, ty2, s2, false);
      } else if (activePointers.current.size === 1 && dragAnchor.current) {
        // Drag pan.
        const da = dragAnchor.current;
        const dx = e.clientX - da.px;
        const dy = e.clientY - da.py;
        applyTransform(da.startTx + dx, da.startTy + dy, viewRef.current.scale, false);
      }
    }

    function onPointerUp(e: PointerEvent) {
      activePointers.current.delete(e.pointerId);
      el.releasePointerCapture(e.pointerId);

      if (activePointers.current.size === 0) {
        dragAnchor.current = null;
        pinchStart.current = null;
        setIsGesturing(false);
        el.classList.remove("grabbing");
        // Mark user as having manually adjusted.
        setUserAdjusted(true);
        userAdjustedRef.current = true;
        // Commit the current transform to React state.
        const { tx, ty, scale } = viewRef.current;
        setView({ tx, ty, scale });
      } else if (activePointers.current.size === 1) {
        // One finger lifted: back to single-finger pan.
        pinchStart.current = null;
        const [[firstId, firstPos]] = [...activePointers.current.entries()];
        dragAnchor.current = {
          startTx: viewRef.current.tx,
          startTy: viewRef.current.ty,
          px: firstPos.x,
          py: firstPos.y,
        };
        el.setPointerCapture(firstId);
      }
    }

    function onPointerCancel(e: PointerEvent) {
      activePointers.current.delete(e.pointerId);
      el.releasePointerCapture(e.pointerId);
      if (activePointers.current.size === 0) {
        dragAnchor.current = null;
        pinchStart.current = null;
        setIsGesturing(false);
        el.classList.remove("grabbing");
        // Mark userAdjusted so auto-fit does not snap back after an iOS system-gesture
        // cancellation (e.g. swipe-back, notification pull-down) — mirrors onPointerUp.
        setUserAdjusted(true);
        userAdjustedRef.current = true;
        const { tx, ty, scale } = viewRef.current;
        setView({ tx, ty, scale });
      }
    }

    // Wheel: must be imperative with {passive:false} to call preventDefault (risk #5, #25).
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const { tx, ty, scale } = viewRef.current;

      if (e.ctrlKey || e.metaKey) {
        // Pinch-to-zoom arrives as ctrl+wheel (trackpad pinch).
        const f = Math.exp(-e.deltaY * 0.0015);
        const s2 = clamp(scale * f, SCALE_MIN, SCALE_MAX);
        const wx = (px - tx) / scale;
        const wy = (py - ty) / scale;
        const tx2 = px - wx * s2;
        const ty2 = py - wy * s2;
        // Disable transition for 1:1 feel (risk #9, #30).
        const vp = viewportRef.current;
        if (vp) vp.style.transition = "none";
        applyTransform(tx2, ty2, s2, false);
      } else {
        // Plain wheel: pan.
        const vp = viewportRef.current;
        if (vp) vp.style.transition = "none";
        applyTransform(tx - e.deltaX, ty - e.deltaY, scale, false);
      }
      // Wheel gestures count as user adjustment.
      setUserAdjusted(true);
      userAdjustedRef.current = true;
      // Sync React state (single render, fine here).
      const { tx: ntx, ty: nty, scale: ns } = viewRef.current;
      setView({ tx: ntx, ty: nty, scale: ns });
    }

    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerup", onPointerUp);
    el.addEventListener("pointercancel", onPointerCancel);
    // passive:false is mandatory for preventDefault to work (risk #5).
    el.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      // Release any captured pointers on cleanup (risk #7, #27).
      for (const id of activePointers.current.keys()) {
        try { el.releasePointerCapture(id); } catch { /* ignore — element may be detached */ }
      }
      activePointers.current.clear();
      dragAnchor.current = null;
      pinchStart.current = null;
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointermove", onPointerMove);
      el.removeEventListener("pointerup", onPointerUp);
      el.removeEventListener("pointercancel", onPointerCancel);
      el.removeEventListener("wheel", onWheel);
    };
  }, [containerRef, applyTransform]);

  return {
    view,
    viewportRef,
    fit,
    recenterOn,
    zoomAboutPoint,
    resetUserAdjusted,
    isGesturing,
    follow,
    setFollow,
    userAdjusted,
  };
}
