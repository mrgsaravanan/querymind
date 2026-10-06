"use client";
import { useEffect, useRef, useState } from "react";

/* Minimal typing for the (vendor-prefixed) Web Speech API. */
interface Rec {
  lang: string; interimResults: boolean; continuous: boolean; start(): void; stop(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null; onerror: (() => void) | null;
}

export default function VoiceButton({ onText }: { onText: (t: string) => void }) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const rec = useRef<Rec | null>(null);

  useEffect(() => {
    const w = window as unknown as { SpeechRecognition?: new () => Rec; webkitSpeechRecognition?: new () => Rec };
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Ctor) return;
    const r = new Ctor();
    r.lang = "en-US"; r.interimResults = true; r.continuous = false;
    r.onresult = (e) => onText(Array.from(e.results).map((x) => x[0].transcript).join(" "));
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    rec.current = r;
    setSupported(true);
    return () => { try { r.stop(); } catch { /* not started */ } };
  }, [onText]);

  if (!supported) return null;
  return (
    <button type="button" aria-pressed={listening} aria-label={listening ? "Stop voice input" : "Start voice input"}
      title="Speak your question" onClick={() => { if (listening) rec.current?.stop(); else { rec.current?.start(); setListening(true); } }}
      className={`rounded-md border px-3 py-2 text-sm ${listening ? "animate-pulse border-red-300 bg-red-50 text-red-700" : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"}`}>
      🎤
    </button>
  );
}
