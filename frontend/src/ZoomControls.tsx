// ZoomControls — floating HUD for the pan/zoom canvas (plan.md §15).
// Positioned inside .idea-scroll (NOT inside .idea-viewport) so it stays
// pinned in the screen-space corner while the canvas transforms (risk #15).
// All buttons stop pointer propagation so they never trigger a canvas drag (risk #14, #35).

import React from "react";

interface Props {
  scale: number;
  follow: boolean;
  onZoomOut: () => void;
  onZoomIn: () => void;
  onFit: () => void;
  onRecenter: () => void;
  onToggleFollow: () => void;
}

function stopBoth(e: React.PointerEvent | React.MouseEvent) {
  e.stopPropagation();
}

export function ZoomControls({
  scale,
  follow,
  onZoomOut,
  onZoomIn,
  onFit,
  onRecenter,
  onToggleFollow,
}: Props) {
  return (
    <div
      className="zoom-controls"
      onClick={stopBoth}
      onPointerDown={stopBoth}
    >
      <button
        className="zc-btn"
        title="Zoom out"
        onClick={onZoomOut}
        onPointerDown={stopBoth}
      >
        −
      </button>
      <span className="zc-pct">{Math.round(scale * 100)}%</span>
      <button
        className="zc-btn"
        title="Zoom in"
        onClick={onZoomIn}
        onPointerDown={stopBoth}
      >
        +
      </button>
      <button
        className="zc-btn"
        title="Fit to screen"
        onClick={onFit}
        onPointerDown={stopBoth}
      >
        Fit
      </button>
      <button
        className="zc-btn"
        title="Re-center focused card"
        onClick={onRecenter}
        onPointerDown={stopBoth}
      >
        ⊙
      </button>
      <button
        className={`zc-btn${follow ? " active" : ""}`}
        title={follow ? "Following (click to disable)" : "Follow off (click to enable)"}
        aria-pressed={follow}
        onClick={onToggleFollow}
        onPointerDown={stopBoth}
      >
        {follow ? "Follow ●" : "Follow ○"}
      </button>
    </div>
  );
}
