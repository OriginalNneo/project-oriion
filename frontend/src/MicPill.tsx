// MicPill — the always-visible ORIION mic control.
// Tap toggles the browser speech recognizer (VoiceInput); a 380 ms hold opens
// the reaction menu instead. The `held` ref keeps pointerup from firing the
// tap after a hold has already fired.

import { useRef } from "react";
import { useMicWave } from "./useMicWave";

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="#111" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M6 11a6 6 0 0 0 12 0M12 17v4M9 21h6" />
    </svg>
  );
}

const BAR_COUNT = 20;
const BAR_STEP = 6;
const BAR_X0 = 4;
const MID_Y = 11;
const MIN_HALF = 1.4; // quiet still shows a thin, alive line
const MAX_HALF = 9.4; // peak half-height inside the 22px viewBox

// Audio-reactive waveform: the analyser (useMicWave) writes each bar's height
// straight to the DOM every frame — no React re-render on the animation path.
function MicWave() {
  const barsRef = useRef<(SVGLineElement | null)[]>([]);

  useMicWave(true, BAR_COUNT, (levels) => {
    const bars = barsRef.current;
    for (let i = 0; i < bars.length; i++) {
      const el = bars[i];
      if (!el) continue;
      const half = MIN_HALF + levels[i] * (MAX_HALF - MIN_HALF);
      el.setAttribute("y1", String(MID_Y - half));
      el.setAttribute("y2", String(MID_Y + half));
    }
  });

  return (
    <svg className="wave" width="124" height="22" viewBox="0 0 124 22" aria-hidden="true">
      {Array.from({ length: BAR_COUNT }, (_, i) => (
        <line
          key={i}
          ref={(el) => {
            barsRef.current[i] = el;
          }}
          x1={BAR_X0 + i * BAR_STEP}
          y1={MID_Y - MIN_HALF}
          x2={BAR_X0 + i * BAR_STEP}
          y2={MID_Y + MIN_HALF}
          stroke="#111"
          strokeWidth="2"
          strokeLinecap="round"
        />
      ))}
    </svg>
  );
}

function Wave({ paused }: { paused: boolean }) {
  if (paused) {
    return (
      <svg className="wave" width="124" height="22" viewBox="0 0 124 22" aria-hidden="true">
        <line x1="4" y1="11" x2="120" y2="11" stroke="#666" strokeWidth="2" strokeDasharray="3 4" strokeLinecap="round" />
      </svg>
    );
  }
  return <MicWave />;
}

const HOLD_MS = 380;

export function MicPill({
  listening,
  disabled,
  hint,
  onTap,
  onHold,
}: {
  listening: boolean;
  disabled: boolean;
  hint: string;
  onTap: () => void;
  onHold: () => void;
}) {
  const timer = useRef<number | null>(null);
  const held = useRef(false);

  const clear = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };
  const down = () => {
    if (disabled) return;
    held.current = false;
    clear();
    timer.current = window.setTimeout(() => {
      held.current = true;
      onHold();
    }, HOLD_MS);
  };
  const up = () => {
    if (disabled) return;
    clear();
    if (!held.current) onTap();
  };

  return (
    <div>
      <button
        type="button"
        className={`mic${listening ? " listening" : ""}${disabled ? " unavailable" : ""}`}
        disabled={disabled}
        onPointerDown={down}
        onPointerUp={up}
        onPointerLeave={clear}
        onPointerCancel={clear}
      >
        <span className="knob">
          <MicIcon />
        </span>
        <span className="body">
          <span className="lab">{listening ? "Active mic" : "Paused mic"}</span>
          <Wave paused={!listening} />
        </span>
        <span className={`tag ${listening ? "tag-green" : "tag-red"}`}>
          {listening ? "Recording" : "Paused"}
        </span>
      </button>
      <div className="mic-hint">{hint}</div>
    </div>
  );
}
