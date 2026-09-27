import { ApiError } from "./api";
import type { Key } from "./i18n";

export interface TranscribeResult {
  text: string;
  model: string;
  language: string | null;
  duration_ms: number | null;
  label: string;
  stored: false;
}

/** The transcript goes after anything already typed, so speaking never erases the visitor's own words. */
export function mergeTranscript(current: string, transcript: string, max: number): string {
  const typed = current.trimEnd();
  const heard = transcript.trim();
  return (typed ? `${typed} ${heard}` : heard).slice(0, max);
}

export function voiceErrorKey(err: unknown): Key {
  if (err instanceof ApiError && !err.offline) {
    if (err.status === 413) return "askVoiceTooLong";
    if (err.status === 422) return "askVoiceNoSpeech";
    if (err.status === 400) return "askVoiceUnreadable";
  }
  return "askVoiceUnavailable";
}

/** First recording format this browser can produce that Whisper also reads. */
export function recorderMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) => MediaRecorder.isTypeSupported(t));
}

export function recordingSupported(): boolean {
  return typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}
