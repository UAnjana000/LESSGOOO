import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Key } from "../i18n";
import { useSession } from "../state";
import { Loading } from "./Bits";
import { recorderMimeType, recordingSupported, voiceErrorKey, type TranscribeResult } from "../voice";

type Phase = "idle" | "recording" | "working";

const clock = (secs: number) => `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;

function MicIcon() {
  return (
    <svg aria-hidden="true" width="1.1em" height="1.1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}

/** Push-to-talk (start, then stop); the API transcribes the recording and the text goes to the question box. */
export function VoiceQuestion({ onText, disabled = false, hideNote = false }: { onText: (text: string) => void; disabled?: boolean; hideNote?: boolean }) {
  const s = useSession();
  const { t } = s;
  const max = s.config?.ask_voice_max_seconds ?? 120;
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState<{ key: Key; bad: boolean } | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const micButton = useRef<HTMLButtonElement>(null);

  useEffect(() => () => {
    const rec = recorder.current;
    if (!rec) return;
    rec.onstop = null;
    if (rec.state !== "inactive") rec.stop();
    rec.stream.getTracks().forEach((track) => track.stop());
  }, []);

  useEffect(() => {
    if (phase !== "recording") return;
    const started = Date.now();
    const id = setInterval(() => {
      const secs = Math.floor((Date.now() - started) / 1000);
      setElapsed(secs);
      // One second of margin so the server's own measurement stays inside the limit.
      if (secs >= max - 1 && recorder.current?.state === "recording") recorder.current.stop();
    }, 250);
    return () => clearInterval(id);
  }, [phase, max]);

  useEffect(() => {
    if (message?.bad && phase === "idle") micButton.current?.focus();
  }, [message, phase]);

  if (!s.config || !s.online) return null;
  if (!s.config.ask_voice_available) return <p className="muted voice-note">{t("askVoiceOff")}</p>;
  if (!recordingSupported()) return null;

  const send = async (audio: Blob, name: string) => {
    if (audio.size === 0) {
      setMessage({ key: "askVoiceNoSpeech", bad: true });
      setPhase("idle");
      return;
    }
    setPhase("working");
    const form = new FormData();
    form.append("file", audio, name);
    form.append("language", s.lang);
    try {
      const r = await api.post<TranscribeResult>("/api/visitor/ask/transcribe", form);
      onText(r.text);
      setMessage({ key: "askVoiceDone", bad: false });
    } catch (err) {
      setMessage({ key: voiceErrorKey(err), bad: true });
    } finally {
      setPhase("idle");
    }
  };

  const start = async () => {
    setMessage(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setMessage({ key: "askVoiceNoMic", bad: true });
      return;
    }
    const type = recorderMimeType();
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      recorder.current = null;
      const mime = rec.mimeType || type || "audio/webm";
      const ext = mime.split("/")[1]?.split(";")[0] || "webm";
      void send(new Blob(chunks, { type: mime }), `question.${ext}`);
    };
    recorder.current = rec;
    rec.start(1000);
    setElapsed(0);
    setPhase("recording");
  };

  const status = phase === "recording" ? t("askVoiceRecording")
    : message ? t(message.key, { seconds: max }) : "";

  return (
    <div className="voice-question">
      <div className="row">
        <button
          ref={micButton}
          type="button"
          className="btn secondary small"
          aria-describedby={!hideNote ? "voice-note" : undefined}
          disabled={disabled || phase === "working"}
          onClick={() => (phase === "recording" ? recorder.current?.stop() : void start())}
        >
          <MicIcon /> {phase === "recording" ? t("askVoiceStop") : t("askVoiceStart")}
        </button>
        {phase === "recording" && <span className="voice-clock" aria-hidden="true">{clock(elapsed)} / {clock(max)}</span>}
      </div>
      {!hideNote && <p id="voice-note" className="muted voice-note">{t("askVoiceNote", { seconds: max })}</p>}
      {phase === "working" ? (
        <Loading inline size="sm" label={t("askVoiceWorking")} />
      ) : (
        status && <p role="status" className={message?.bad && phase === "idle" ? "status bad voice-note" : "muted voice-note"}>{status}</p>
      )}
    </div>
  );
}
