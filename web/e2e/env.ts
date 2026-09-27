import path from "node:path";
import { fileURLToPath } from "node:url";

export const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(E2E_DIR, "..", "..");
export const ARTIFACTS = path.join(E2E_DIR, "artifacts");

/** The throwaway stack started by web/e2e/stack.ps1. Credentials are fixed e2e-only values, not secrets. */
export const E2E = {
  baseURL: process.env.E2E_BASE_URL ?? "https://localhost:9443",
  admin: {
    email: process.env.E2E_ADMIN_EMAIL ?? "admin@archive.local",
    password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-password",
  },
  dbUrl: process.env.E2E_DATABASE_URL ?? "postgresql://archive:e2e-throwaway-db@127.0.0.1:56432/archive",
  python: process.env.E2E_PYTHON ?? path.join(REPO_ROOT, "backend", ".venv", "Scripts", "python.exe"),
};

/** Ports of the demo stack (project ambedkar-archive). The suite mutates data, so it never runs there. */
export const MAIN_STACK_PORTS = [":8443", ":8088", ":55432"];

export function assertNotMainStack(url: string): void {
  if (MAIN_STACK_PORTS.some((p) => url.includes(p))) {
    throw new Error(`Refusing to run against ${url}: that is the shared demo stack. Use the ambedkar-e2e stack.`);
  }
}

/** Title fragments of the synthetic fixtures loaded by `archive.cli seed-fixtures`. */
export const FX = {
  essay: "On Public Reading Rooms",
  lecture: "Lecture on Education and Work",
  tank: "Lecture on Water and the Common Tank",
  proceedings: "Proceedings of the Samarpur Civic Assembly",
  pamphletHi: "Reading-room pamphlet",
  manuscript: "Handwritten note on the library board",
  photo: "Readers at the Samarpur reading room",
  audio: "Talk on the reading room",
  video: "Synthetic test-pattern video",
  petitionMr: "Water petition",
  onlineOnly: "Newspaper report on the library board",
  rightsUnknown: "Draft memorandum",
} as const;

/** The spec's required answer label (spec 5.7, policy rule 4). */
export const SPEC_ANSWER_LABEL = "AI-generated answer from archive sources";
