import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { mergeTranscript, voiceErrorKey } from "./voice";

describe("mergeTranscript", () => {
  it("fills an empty question box with the transcript", () => {
    expect(mergeTranscript("", "  What is caste?  ", 500)).toBe("What is caste?");
  });

  it("appends to what the visitor already typed instead of replacing it", () => {
    expect(mergeTranscript("About the 1949 speech:", "what is hero-worship?", 500)).toBe("About the 1949 speech: what is hero-worship?");
  });

  it("never exceeds the question box limit", () => {
    expect(mergeTranscript("abc", "defghij", 6)).toBe("abc de");
  });
});

describe("voiceErrorKey", () => {
  it.each([
    [new ApiError(413, "too long"), "askVoiceTooLong"],
    [new ApiError(422, "no speech"), "askVoiceNoSpeech"],
    [new ApiError(400, "unreadable"), "askVoiceUnreadable"],
    [new ApiError(503, "no key"), "askVoiceUnavailable"],
    [new ApiError(0, "offline", true), "askVoiceUnavailable"],
    [new Error("boom"), "askVoiceUnavailable"],
  ])("maps %s to %s", (err, key) => {
    expect(voiceErrorKey(err)).toBe(key);
  });
});
