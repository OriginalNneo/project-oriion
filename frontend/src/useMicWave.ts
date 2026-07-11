// useMicWave — audio-reactive waveform driver for the mic pill.
//
// The Web Speech API (speech.ts) does NOT expose the raw audio stream, so this
// is a SEPARATE, self-contained analyser: getUserMedia -> AudioContext ->
// AnalyserNode, sampled every animation frame. It writes bar levels via an
// imperative `draw` callback (no per-frame React re-render — same discipline as
// usePanZoom writing the transform straight to the DOM). SpeechRecognition and a
// second getUserMedia capture coexist fine on modern browsers.
//
// Approach (see the VU-meter reasoning): getByteTimeDomainData -> one RMS level
// per frame, spread across the bars as a lively band (centre bias + a little
// per-bar shimmer), with ATTACK-fast / RELEASE-slow smoothing so it tracks the
// voice but never jitters. Falls back to a calm idle shimmer when the mic is
// denied/unavailable or AudioContext is missing — it never throws.
//
// Lifecycle: only runs while `active`; the effect cleanup stops the rAF, the
// media tracks, and closes the AudioContext (StrictMode-safe via the cancelled
// flag — mirrors ws.ts / usePanZoom.ts teardown).

import { useEffect, useRef } from "react";

/** Called each animation frame with per-bar levels in 0..1. */
type DrawFn = (levels: number[]) => void;

function audioContextCtor(): typeof AudioContext | undefined {
  const w = window as unknown as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
  };
  return w.AudioContext ?? w.webkitAudioContext;
}

export function useMicWave(active: boolean, barCount: number, draw: DrawFn): void {
  // Keep the latest draw closure without re-running the audio effect.
  const drawRef = useRef(draw);
  drawRef.current = draw;

  useEffect(() => {
    if (!active) return;

    let cancelled = false;
    let raf = 0;
    let ctx: AudioContext | null = null;
    let stream: MediaStream | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let analyser: AnalyserNode | null = null;

    const levels = new Array<number>(barCount).fill(0); // smoothed, persists across frames
    let phase = 0;

    // Idle fallback — a gentle, calm shimmer so the pill reads "live" even with
    // no mic signal (permission denied, no AudioContext, or headless/no-device).
    const idle = () => {
      phase += 0.045;
      for (let i = 0; i < barCount; i++) {
        const s = Math.sin(phase + i * 0.6);
        levels[i] = 0.1 + 0.07 * s * s;
      }
      drawRef.current(levels);
      raf = requestAnimationFrame(idle);
    };

    const AC = audioContextCtor();
    if (!AC || !navigator.mediaDevices?.getUserMedia) {
      raf = requestAnimationFrame(idle);
      return () => {
        cancelled = true;
        cancelAnimationFrame(raf);
      };
    }

    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((s) => {
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        stream = s;
        ctx = new AC();
        // Autoplay policy can leave the context suspended until a gesture; the
        // mic toggle IS a gesture, so resume() succeeds.
        void ctx.resume();
        source = ctx.createMediaStreamSource(s);
        analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        source.connect(analyser);
        const data = new Uint8Array(analyser.fftSize); // reused every frame — no per-frame alloc

        const loop = () => {
          if (cancelled || !analyser) return;
          analyser.getByteTimeDomainData(data);
          // RMS deviation from the 128 midpoint = instantaneous loudness.
          let sum = 0;
          for (let i = 0; i < data.length; i++) {
            const v = (data[i] - 128) / 128;
            sum += v * v;
          }
          const rms = Math.sqrt(sum / data.length); // speech ~0.02..0.4
          const level = Math.min(1, rms * 3.4); // gain into a usable 0..1

          phase += 0.32;
          const mid = (barCount - 1) / 2;
          for (let i = 0; i < barCount; i++) {
            // Band shape: taller in the middle, a touch of per-bar shimmer so it
            // reads as a waveform rather than one flat block.
            const centerBias = 1 - Math.abs(i - mid) / (barCount * 0.85);
            const shimmer = 0.78 + 0.22 * Math.sin(phase + i * 0.9);
            const target = level * (0.5 + 0.7 * centerBias) * shimmer;
            const prev = levels[i];
            // Attack fast (jump to new peaks), release slow (gentle decay).
            levels[i] = target > prev ? target : prev * 0.82 + target * 0.18;
          }
          drawRef.current(levels);
          raf = requestAnimationFrame(loop);
        };
        loop();
      })
      .catch(() => {
        // Denied / no device / insecure — degrade to the calm idle animation.
        if (cancelled) return;
        raf = requestAnimationFrame(idle);
      });

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      try {
        source?.disconnect();
        analyser?.disconnect();
      } catch {
        /* nodes already gone */
      }
      stream?.getTracks().forEach((t) => t.stop());
      if (ctx && ctx.state !== "closed") void ctx.close();
    };
  }, [active, barCount]);
}
