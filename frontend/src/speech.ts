// Voice input — the MVP speech path. Uses the browser's built-in speech
// recognition (Web Speech API): the browser does mic capture + endpointing +
// STT and hands us *final utterances*, which we feed into the existing
// `utterance` -> classify -> engine -> broadcast tail. Zero server ML deps.
//
// Server-side VAD + faster-whisper (plan.md Phase 1 "local" backend) replaces
// this behind the same wire protocol when privacy/offline matters; this client
// path stays as the zero-install fallback.
//
// Caveats: Chrome/Safari only (feature-detected via isSupported), and the mic
// requires a secure context — localhost works; a LAN IP needs HTTPS or a
// browser flag (documented in README).

// --- Minimal ambient types: lib.dom.d.ts doesn't ship the Web Speech API. ---
interface SpeechAlternative {
  transcript: string;
}
interface SpeechResult {
  isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechAlternative;
}
interface SpeechResultList {
  readonly length: number;
  [index: number]: SpeechResult;
}
interface SpeechResultEvent {
  resultIndex: number;
  results: SpeechResultList;
}
interface SpeechErrorEvent {
  error: string;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((ev: SpeechResultEvent) => void) | null;
  onerror: ((ev: SpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function recognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export interface VoiceOptions {
  lang?: string;
  /** A finished utterance (the browser endpointed it). */
  onFinal: (text: string) => void;
  /** Live partial transcript while the user is mid-sentence. */
  onInterim?: (text: string) => void;
  /** Listening state changed (drives the mic button / "listening…" UI). */
  onState?: (listening: boolean) => void;
  /** A non-recoverable problem (mic permission denied, etc.). */
  onError?: (message: string) => void;
}

export class VoiceInput {
  private rec: SpeechRecognitionLike | null = null;
  private enabled = false;
  private opts: VoiceOptions;

  constructor(opts: VoiceOptions) {
    this.opts = opts;
  }

  static isSupported(): boolean {
    return recognitionCtor() !== null && window.isSecureContext;
  }

  get listening(): boolean {
    return this.enabled;
  }

  start(): void {
    if (this.enabled) return;
    const Ctor = recognitionCtor();
    if (!Ctor) {
      this.opts.onError?.("speech recognition is not supported in this browser");
      return;
    }
    this.enabled = true;
    const rec = new Ctor();
    this.rec = rec;
    rec.lang = this.opts.lang ?? "en-US";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onresult = (ev) => {
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const result = ev.results[i];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal) {
          const finalText = text.trim();
          if (finalText) this.opts.onFinal(finalText);
        } else {
          interim += text;
        }
      }
      this.opts.onInterim?.(interim.trim());
    };

    rec.onerror = (ev) => {
      // "no-speech"/"aborted" are routine and the auto-restart absorbs them;
      // everything else must be VISIBLE or the mic just looks dead.
      console.debug("[voice] recognition error:", ev.error);
      const terminal: Record<string, string> = {
        "not-allowed": "microphone access was denied — allow it in the address bar",
        "service-not-allowed": "speech service blocked by the browser",
        "audio-capture": "no usable microphone was found",
        network: "speech service unreachable (browser STT needs internet)",
      };
      const message = terminal[ev.error];
      if (message) {
        this.enabled = false;
        this.opts.onState?.(false);
        this.opts.onError?.(message);
      }
    };

    // Browsers end recognition after a silence window; restart while enabled
    // so the mic toggle behaves like a continuous open mic.
    rec.onend = () => {
      this.opts.onInterim?.("");
      if (this.enabled) {
        setTimeout(() => {
          if (this.enabled) {
            try {
              rec.start();
            } catch {
              // already restarted elsewhere; ignore
            }
          }
        }, 200);
      } else {
        this.opts.onState?.(false);
      }
    };

    try {
      rec.start();
      this.opts.onState?.(true);
    } catch {
      this.enabled = false;
      this.opts.onError?.("could not start the microphone");
    }
  }

  stop(): void {
    this.enabled = false;
    this.opts.onInterim?.("");
    this.rec?.stop();
    this.rec = null;
    this.opts.onState?.(false);
  }
}
