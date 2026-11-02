"use client";

import { useEffect, useRef, useState } from "react";
import { fmtTime } from "@/lib/format";

const MAX_SEC = 120;

/** ชนิดไฟล์ที่เบราว์เซอร์อัดได้ (Chrome/Firefox = webm, Safari = mp4) */
function pickType(): { mime: string; ext: string } {
  const types = [["audio/webm;codecs=opus", ".webm"], ["audio/webm", ".webm"], ["audio/mp4", ".m4a"], ["audio/ogg;codecs=opus", ".ogg"]];
  for (const [mime, ext] of types) if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(mime)) return { mime, ext };
  return { mime: "", ext: ".webm" };
}

/** อัดเสียงจากไมค์ในเบราว์เซอร์ มีแถบระดับเสียง ฟังซ้ำ และอัดใหม่ได้ ส่งไฟล์ที่อัดให้ onDone */
export default function Recorder({ onDone, disabled }: {
  onDone: (blob: Blob | null, filename: string) => void;
  disabled?: boolean;
}) {
  const [state, setState] = useState<"idle" | "recording" | "done">("idle");
  const [error, setError] = useState("");
  const [level, setLevel] = useState(0);
  const [secs, setSecs] = useState(0);
  const [url, setUrl] = useState("");
  const rec = useRef<MediaRecorder | null>(null);
  const stopAll = useRef<() => void>(() => undefined);

  useEffect(() => () => { stopAll.current(); }, []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  const start = async () => {
    setError("");
    let stream: MediaStream;
    try {
      // ปิดการปรับเสียงอัตโนมัติของเบราว์เซอร์ เสียงตัวอย่างต้องเป็นเสียงจริงของผู้พากย์
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
      });
    } catch {
      setError("เปิดไมค์ไม่ได้ ตรวจว่าอนุญาตให้เว็บนี้ใช้ไมโครโฟนแล้ว");
      return;
    }
    const { mime, ext } = pickType();
    const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks: Blob[] = [];
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    const t0 = performance.now();
    let raf = 0;
    const tick = () => {
      analyser.getFloatTimeDomainData(buf);
      let peak = 0;
      for (const x of buf) peak = Math.max(peak, Math.abs(x));
      setLevel(peak);
      const s = (performance.now() - t0) / 1000;
      setSecs(s);
      if (s >= MAX_SEC) r.stop();
      else raf = requestAnimationFrame(tick);
    };
    stopAll.current = () => {
      cancelAnimationFrame(raf);
      stream.getTracks().forEach((t) => t.stop());
      ctx.close().catch(() => undefined);
    };
    r.onstop = () => {
      stopAll.current();
      const blob = new Blob(chunks, { type: r.mimeType || mime || "audio/webm" });
      setUrl(URL.createObjectURL(blob));
      setLevel(0);
      setState("done");
      onDone(blob, `recording${ext}`);
    };
    rec.current = r;
    r.start(250);
    setState("recording");
    tick();
  };

  const stop = () => rec.current?.state === "recording" && rec.current.stop();
  const reset = () => { setUrl(""); setSecs(0); setState("idle"); onDone(null, ""); };

  const loud = level > 0.98;
  return (
    <div className="recorder">
      <div className="row" style={{ gap: 10 }}>
        {state === "recording" ? (
          <button type="button" className="btn primary" onClick={stop}>■ หยุดอัด</button>
        ) : (
          <button type="button" className="btn primary" disabled={disabled} onClick={state === "done" ? reset : start}>
            {state === "done" ? "อัดใหม่" : "● เริ่มอัด"}
          </button>
        )}
        <span className="mono" aria-live="off">{fmtTime(secs)} / {fmtTime(MAX_SEC)}</span>
      </div>
      {state === "recording" && (
        <div className="level" aria-label="ระดับเสียง">
          <div className={`level-bar${loud ? " clip" : ""}`} style={{ width: `${Math.min(100, level * 100)}%` }} />
        </div>
      )}
      {state === "recording" && loud && <span className="dim" style={{ color: "var(--danger)" }}>เสียงดังจนแตก ถอยห่างไมค์อีกนิด</span>}
      {state === "done" && url && <audio controls src={url} style={{ width: "100%" }} />}
      {error && <div className="alert error" role="alert">{error}</div>}
    </div>
  );
}
