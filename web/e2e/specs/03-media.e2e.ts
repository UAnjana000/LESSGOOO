import type { Locator, Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { FX } from "../env";

const toSeconds = (label: string) => {
  const m = label.match(/(\d+):(\d{2})$/);
  if (!m) throw new Error(`no m:ss in "${label}"`);
  return Number(m[1]) * 60 + Number(m[2]);
};

async function mediaState(player: Locator) {
  return player.evaluate((el: HTMLMediaElement) => ({
    paused: el.paused, time: el.currentTime, duration: el.duration, error: el.error?.code ?? null,
    ready: el.readyState, tracks: el.textTracks.length,
  }));
}

async function checkRecording(page: Page, id: number, title: string, tag: "audio" | "video") {
  await page.goto(`/item/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  const section = page.getByRole("region", { name: "Reviewed transcript" });
  await expect(section).toBeVisible();
  const player = section.locator(tag);
  await expect(player).toHaveCount(1);

  // Captions: a default <track kind="captions"> backed by a real WebVTT file.
  const track = player.locator('track[kind="captions"]');
  await expect(track).toHaveAttribute("src", `/api/visitor/items/${id}/captions.vtt`);
  const vtt = await page.request.get(`/api/visitor/items/${id}/captions.vtt`);
  expect(vtt.ok()).toBeTruthy();
  const cues = await vtt.text();
  expect(cues.startsWith("WEBVTT")).toBeTruthy();
  expect(cues).toContain("The reading room opened in two rented rooms above a grain shop.");

  // The file decodes: metadata loads without a media error.
  await expect.poll(async () => (await mediaState(player)).ready, { message: `${tag} metadata loads`, timeout: 30_000 }).toBeGreaterThanOrEqual(1);
  expect((await mediaState(player)).error, `${tag} decode error`).toBeNull();

  // Tapping a transcript line seeks there and plays.
  const segButtons = section.getByRole("button", { name: /^Play from here \d+:\d{2}$/ });
  await expect(segButtons).toHaveCount(4);
  const third = segButtons.nth(2);
  const start = toSeconds((await third.getAttribute("aria-label"))!);
  expect(start).toBe(11);
  await third.click();
  await expect.poll(async () => (await mediaState(player)).paused, { message: `${tag} plays after tapping a line` }).toBe(false);
  await expect.poll(async () => (await mediaState(player)).time, { message: `${tag} currentTime after seek` }).toBeGreaterThanOrEqual(start);
  expect((await mediaState(player)).time).toBeLessThan(start + 3.5);
  await expect(section.locator("li.segment").nth(2)).toHaveAttribute("aria-current", "true");
  expect((await mediaState(player)).tracks).toBeGreaterThanOrEqual(1);
  await player.evaluate((el: HTMLMediaElement) => el.pause());
}

test.describe("Recordings", () => {
  test("synthetic audio plays, transcript lines seek, captions exist", async ({ page, fx }) => {
    const audio = fx.get(FX.audio);
    await checkRecording(page, audio.id, audio.title, "audio");
  });

  test("synthetic video plays, transcript lines seek, captions exist", async ({ page, fx }) => {
    const video = fx.get(FX.video);
    await checkRecording(page, video.id, video.title, "video");
    const size = await page.locator("video").evaluate((el: HTMLVideoElement) => ({ w: el.videoWidth, h: el.videoHeight }));
    expect(size.w, "video frames decode").toBeGreaterThan(0);
  });

  test("?t= deep link starts the recording at the cited moment", async ({ page, fx }) => {
    const audio = fx.get(FX.audio);
    await page.goto(`/item/${audio.id}?t=15297`);
    const player = page.getByRole("region", { name: "Reviewed transcript" }).locator("audio");
    await expect.poll(async () => (await mediaState(player)).time, { timeout: 30_000 }).toBeGreaterThanOrEqual(15);
  });
});
