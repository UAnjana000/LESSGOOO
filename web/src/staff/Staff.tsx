// Archivist workspace. Interface text comes from i18n (EN/HI/MR); values the API sends are shown as sent.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, resolveApiUrl } from "../api";
import { formatMs, useApi } from "../hooks";
import { ITEM_TYPES } from "../filters";
import { LANGS, type Key, type Lang } from "../i18n";
import { useSession } from "../state";
import { Loading } from "../components/Bits";
import { StaffAuthProvider, useAuthedObjectUrl, useStaff } from "./auth";
import { CERTAINTIES, detailText, fileNotes, metadataBody, metadataForm, parseList, rightsBody, rightsDowngrades, type FileNote, type ItemMetadata, type MetadataForm } from "./forms";

type Json = Record<string, unknown>;
type T = (key: Key, vars?: Record<string, string | number>) => string;

const COLLECTIONS = ["writings", "speeches", "debates", "manuscripts", "photographs", "audio_video"] as const;
const DOC_CLASSES = ["born_digital", "printed", "handwritten", "photograph", "audio_video"] as const;
const ACCESS_LEVELS = ["public", "public_online_only", "restricted"] as const;
const PERMISSIONS = ["unknown", "allowed", "not_allowed"] as const;
const BOOTSTRAP_COMMAND = "python -m archive.cli bootstrap";
const PAGE_ACTIONS: Record<string, Key> = { approve: "stApprove", correct: "stCorrect", escalate: "stEscalate", reject: "stReject" };

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    try {
      const parsed = JSON.parse(e.message);
      if (parsed && typeof parsed === "object") return detailText(parsed);
    } catch {
      /* plain text */
    }
    return e.message;
  }
  return String(e);
}

// api.post keeps only detail.message of a structured error; this keeps the whole detail (publish problems,
// per-file intake notes) as JSON in the message, for errText to spell out.
async function postDetailed<R>(path: string, body: unknown, token: string): Promise<R> {
  let res: Response;
  try {
    res = await fetch(resolveApiUrl(path), { method: "POST", headers: body instanceof FormData ? { Authorization: `Bearer ${token}` } : { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body instanceof FormData ? body : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "offline", true);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    throw new ApiError(res.status, typeof detail === "string" ? detail : detail != null ? JSON.stringify(detail) : res.statusText);
  }
  return data as R;
}

// A queued worker job finishes after the request that queued it, so poll until it settles (null on timeout).
async function waitForJob(jobId: number, token: string, timeoutMs = 300_000): Promise<Json | null> {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    const job = await api.get<Json>(`/api/staff/jobs/${jobId}`, token);
    if (job.status === "done" || job.status === "failed") return job;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  return null;
}

function useAction() {
  const { token } = useStaff();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async <R,>(fn: (token: string) => Promise<R>, okText: string | null | ((result: R) => string), after?: () => void) => {
    setBusy(true);
    setMsg(null);
    try {
      const result = await fn(token!);
      const text = typeof okText === "function" ? okText(result) : okText;
      if (text) setMsg({ ok: true, text });
      after?.();
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    } finally {
      setBusy(false);
    }
  };
  const view = msg ? <p className={`notice${msg.ok ? "" : " bad"}`} role={msg.ok ? "status" : "alert"}>{msg.text}</p> : null;
  return { run, busy, view };
}

/** Confirmation carried across a navigation (router state), e.g. after a page review decision. */
function Flash() {
  const flash = (useLocation().state as { flash?: string } | null)?.flash;
  return flash ? <p className="notice" role="status">{flash}</p> : null;
}

export function StaffRoot() {
  const { t } = useSession();
  useEffect(() => {
    document.title = t("stWorkspace");
  }, [t]);
  return (
    <StaffAuthProvider>
      <Outlet />
    </StaffAuthProvider>
  );
}

function StaffLanguage() {
  const { lang, setLang, t } = useSession();
  return (
    <label className="staff-lang">{t("language")}
      <select value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
        {LANGS.map((l) => <option key={l.code} value={l.code} lang={l.code}>{l.name}</option>)}
      </select>
    </label>
  );
}

export function StaffLogin() {
  const { login, loginAsJudge, token, open } = useStaff();
  const { t } = useSession();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [judgeBusy, setJudgeBusy] = useState(false);
  // Demo installations can switch on a read-only judge account; the button only shows when they have.
  const judge = useApi<{ enabled: boolean }>("/api/staff/judge-access");
  if (token || open) return <Navigate to="/staff" replace />;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await login(email, password);
      nav("/staff");
    } catch (err) {
      setError(errText(err));
    }
  };
  const judgeIn = async () => {
    setError(null);
    setJudgeBusy(true);
    try {
      await loginAsJudge();
      nav("/staff");
    } catch (err) {
      setError(errText(err));
    } finally {
      setJudgeBusy(false);
    }
  };
  return (
    <div className="staff">
      <main className="page" style={{ maxWidth: 460 }}>
        <div className="row"><span className="spacer" /><StaffLanguage /></div>
        <h1>{t("stWorkspace")}</h1>
        <p className="muted">{t("stSignInLead")} <code lang="en">{BOOTSTRAP_COMMAND}</code></p>
        <form className="stack" onSubmit={submit}>
          <label>{t("stEmail")}<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label>{t("stPassword")}<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
          {error && <p className="notice bad" role="alert">{error}</p>}
          <button type="submit" className="btn">{t("stSignIn")}</button>
        </form>
        {judge.data?.enabled && (
          <div className="sheet stack" style={{ padding: 14, marginTop: 20 }}>
            <p className="muted" style={{ margin: 0 }}>{t("stJudgeLead")}</p>
            <button type="button" className="btn secondary" disabled={judgeBusy} onClick={judgeIn}>{t("stJudgeContinue")}</button>
          </div>
        )}
      </main>
    </div>
  );
}

// Roles that can act somewhere in the workspace; anyone else (no role, an unknown role) only reads.
const ACTING_ROLES = ["admin", "archivist", "curator", "reviewer", "translation_reviewer"];

export function StaffLayout() {
  const { token, user, logout, can, open } = useStaff();
  const { t } = useSession();
  // Without a token, wait for the open-access check (it signs in when the login is switched off).
  if (!token) return open === false ? <Navigate to="/staff/login" replace /> : null;
  // Intake and the rights register are archivist work; the register stays readable by URL.
  const archivist = can("archivist");
  const links: [string, Key][] = [
    ["/staff", "stNavDashboard"],
    ...(archivist ? [["/staff/intake", "stNavIntake"] as [string, Key]] : []),
    ["/staff/review", "stNavReview"],
    ["/staff/items", "stNavItems"],
    ...(archivist ? [["/staff/rights", "stNavRights"] as [string, Key]] : []),
    ["/staff/jobs", "stNavJobs"],
    ["/staff/audit", "stNavAudit"],
  ];
  const readOnly = Boolean(user) && !ACTING_ROLES.some(can);
  return (
    <div className="staff">
      <a className="skip-link" href="#main">{t("skip")}</a>
      <header className="staff-top">
        <strong>{t("stWorkspace")}</strong>
        <nav aria-label={t("stNavLabel")}>
          {links.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/staff"}>{t(label)}</NavLink>
          ))}
        </nav>
        <div className="who">
          <StaffLanguage />
          <span>{user?.email} ({(user?.roles ?? []).join(", ")})</span>
          {!open && <button type="button" className="btn secondary small" onClick={logout}>{t("stSignOut")}</button>}
        </div>
      </header>
      <main id="main" className="page" tabIndex={-1}>
        {readOnly && <p className="notice" role="status">{t("stReadOnly")}</p>}
        <Outlet />
      </main>
    </div>
  );
}

function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="sheet" style={{ marginBottom: 18 }}>
      <div className="row" style={{ marginBottom: 10 }}>
        <h2 style={{ fontSize: "var(--step-1)", margin: 0 }}>{title}</h2>
        <span className="spacer" />
        {actions}
      </div>
      {children}
    </section>
  );
}

function Nothing() {
  const { t } = useSession();
  return <p className="muted">{t("stNothingWaiting")}</p>;
}

// ---------------------------------------------------------------- dashboard

export function StaffDashboard() {
  const { token } = useStaff();
  const { t } = useSession();
  const stats = useApi<Json>("/api/staff/stats", token);
  const status = useApi<Json>("/api/staff/settings/status", token);
  const queue = useApi<Json>("/api/staff/review/queue", token);
  const q = queue.data as Record<string, unknown[]> | null;
  return (
    <>
      <h1>{t("stNavDashboard")}</h1>
      <div className="form-grid">
        <Section title={t("stWaiting")}>
          {queue.loading && <Loading />}
          {queue.error && <p className="notice bad" role="alert">{errText(queue.error)}</p>}
          {q && (
            <dl className="facts">
              <dt>{t("stQPages")}</dt><dd>{q.pages.length}</dd>
              <dt>{t("stQBatches")}</dt><dd>{q.batches.length}</dd>
              <dt>{t("stQSegments")}</dt><dd>{q.segments.length}</dd>
              <dt>{t("stQPhotos")}</dt><dd>{q.photos.length}</dd>
              <dt>{t("stQTranslations")}</dt><dd>{q.translations.length}</dd>
              <dt>{t("stQDerivatives")}</dt><dd>{q.derivatives.length}</dd>
              <dt>{t("stQReady")}</dt><dd>{q.ready_to_publish.length}</dd>
            </dl>
          )}
          <p style={{ marginTop: 12 }}><Link to="/staff/review">{t("stOpenQueue")}</Link></p>
        </Section>
        <Section title={t("stIntegrations")}>
          {status.loading && <Loading />}
          {status.error && <p className="notice bad" role="alert">{errText(status.error)}</p>}
          {status.data && (
            <dl className="facts">
              <dt>{t("stEnvironment")}</dt><dd>{String(status.data.environment)}</dd>
              <dt>{t("stSarvam")}</dt><dd className={`status ${status.data.sarvam_configured ? "ok" : "bad"}`}>{status.data.sarvam_configured ? t("stConfigured") : t("stSarvamOff")}</dd>
              <dt>{t("stAnswerModel")}</dt><dd className={`status ${status.data.llm_configured ? "ok" : "bad"}`}>{status.data.llm_configured ? String(status.data.llm_model) : t("stLlmOff")}</dd>
              <dt>{t("stTraceSink")}</dt><dd>{String(status.data.trace_backend)}</dd>
              <dt>{t("stOcrGate")}</dt><dd>{String(status.data.gate_config).split(/[\\/]/).pop()}</dd>
              <dt>{t("stSufficiency")}</dt><dd>{String(status.data.sufficiency_threshold)} ({String(status.data.sufficiency_threshold_version)})</dd>
            </dl>
          )}
        </Section>
      </div>
      {stats.loading && <Loading />}
      {stats.error && <p className="notice bad" role="alert">{errText(stats.error)}</p>}
      {stats.data && (
        <Section title={t("stArchiveState")}>
          <div className="form-grid">
            <div><h3>{t("stItemsByState")}</h3><Counts data={stats.data.items_by_state as Json} /></div>
            <div><h3>{t("stPagesByStatus")}</h3><Counts data={stats.data.pages_by_status as Json} /></div>
            <div><h3>{t("stPagesByRoute")}</h3><Counts data={stats.data.pages_by_route as Json} /></div>
          </div>
          <h3 style={{ marginTop: 16 }}>{t("stAskOutcomes")}</h3>
          <table className="grid" aria-label={t("stAskOutcomes")}>
            <thead><tr><th>{t("stOutcome")}</th><th>{t("stCount")}</th><th>{t("stTokensIn")}</th><th>{t("stTokensOut")}</th><th>{t("stCost")}</th><th>{t("stMeanLatency")}</th></tr></thead>
            <tbody>
              {(stats.data.answers as Json[]).map((a) => (
                <tr key={String(a.outcome)}><td>{String(a.outcome)}</td><td>{String(a.count)}</td><td>{String(a.tokens_in)}</td><td>{String(a.tokens_out)}</td><td>{Number(a.cost_usd).toFixed(4)}</td><td>{Math.round(Number(a.avg_latency_ms))}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted">{t("stCacheHits", { n: String(stats.data.cache_hits) })}</p>
        </Section>
      )}
    </>
  );
}

function Counts({ data }: { data: Json }) {
  return (
    <dl className="facts">
      {Object.entries(data ?? {}).map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{String(v)}</dd></div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------- intake

const INTAKE_PRESETS = [
  { id: "baws", labelKey: "stPresetBaws", collection: "writings", item_type: "printed_scan", doc_class: "printed", languages: "en, mr", rights_source_key: "rights-daf-baws", access_level: "public" },
  { id: "speech", labelKey: "stPresetSpeech", collection: "speeches", item_type: "audio", doc_class: "audio_video", languages: "en", rights_source_key: "rights-daf-baws", access_level: "public" },
  { id: "photo", labelKey: "stPresetPhoto", collection: "photographs", item_type: "photograph", doc_class: "photograph", languages: "en", rights_source_key: "rights-daf-baws", access_level: "public" },
  { id: "cad", labelKey: "stPresetCad", collection: "debates", item_type: "printed_scan", doc_class: "printed", languages: "en, hi", rights_source_key: "rights-cad", access_level: "public" },
] as const;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function StaffIntake() {
  const { token, can } = useStaff();
  const { t } = useSession();
  const rights = useApi<Json[]>("/api/staff/rights", token);
  const { run, busy, view } = useAction();
  const [result, setResult] = useState<Json | null>(null);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [form, setForm] = useState({
    title: "", item_type: "printed_scan", collection: "writings", doc_class: "printed", languages: "en",
    rights_source_key: "", date_text: "", creator: "", device: "capture-station-1", operator: "", access_level: "public",
  });
  const [files, setFiles] = useState<File[]>([]);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  const applyPreset = (p: typeof INTAKE_PRESETS[number]) => {
    setActivePreset(p.id);
    setForm((f) => ({
      ...f,
      collection: p.collection,
      item_type: p.item_type,
      doc_class: p.doc_class,
      languages: p.languages,
      rights_source_key: p.rights_source_key,
      access_level: p.access_level,
    }));
  };

  const handleFilesAdded = (incoming: FileList | File[]) => {
    const list = Array.from(incoming);
    setFiles((prev) => [...prev, ...list]);
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!files.length) return;
    const meta = {
      title: form.title, item_type: form.item_type, collection: form.collection, doc_class: form.doc_class,
      languages: form.languages.split(",").map((s) => s.trim()).filter(Boolean), rights_source_key: form.rights_source_key,
      date_text: form.date_text || undefined, creator: form.creator || undefined, access_level: form.access_level,
      capture: { device: form.device, operator: form.operator, date: new Date().toISOString().slice(0, 10) },
    };
    const fd = new FormData();
    fd.set("metadata", JSON.stringify(meta));
    for (const f of files) fd.append("files", f);
    setResult(null);
    // Success only when a job was queued: duplicates and rejected files store nothing (422, or 200 with no job).
    void run(async (tk) => {
      const r = await postDetailed<Json>("/api/staff/intake", fd, tk);
      setResult(r);
      if (r.job_id == null) throw new ApiError(422, `${t("stNothingStored")} ${fileNotes(r.files as FileNote[])}`);
    }, t("stStored"));
  };

  const selectable = (rights.data ?? []).filter((r) => !r.discovery_only);
  const totalBytes = files.reduce((acc, f) => acc + f.size, 0);

  return (
    <>
      <h1>{t("stNavIntake")}</h1>
      <p className="muted" style={{ maxWidth: "80ch" }}>{t("stIntakeLead")}</p>
      {!can("archivist") ? <p className="notice">{t("stArchivistOnly")}</p> : (
        <>
          {/* Preset Profiles */}
          <div className="staff-presets" role="group" aria-label={t("stIntakePresets")}>
            <span className="muted" style={{ fontSize: "var(--step--1)", marginRight: 4 }}>{t("stIntakePresets")}:</span>
            {INTAKE_PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`staff-preset-btn ${activePreset === p.id ? "active" : ""}`}
                onClick={() => applyPreset(p)}
              >
                {t(p.labelKey)}
              </button>
            ))}
          </div>

          <form className="sheet stack" onSubmit={submit}>
            <div className="form-grid">
              <label>{t("stTitle")}<input type="text" value={form.title} onChange={set("title")} required /></label>
              <label>{t("stRightsEntry")}
                <select value={form.rights_source_key} onChange={set("rights_source_key")} required>
                  <option value="">{t("stChoose")}</option>
                  {selectable.map((r) => (
                    <option key={String(r.source_key)} value={String(r.source_key)}>{t("stRightsOption", { key: String(r.source_key), perm: String(r.display_permission) })}</option>
                  ))}
                </select>
              </label>
              <label>{t("stItemType")}
                <select value={form.item_type} onChange={set("item_type")}>
                  {ITEM_TYPES.map((v) => <option key={v} value={v}>{t(`type_${v}`)}</option>)}
                </select>
              </label>
              <label>{t("stDocClass")}
                <select value={form.doc_class} onChange={set("doc_class")}>
                  {DOC_CLASSES.map((v) => <option key={v} value={v}>{t(`stDoc_${v}`)}</option>)}
                </select>
              </label>
              <label>{t("stCollection")}
                <select value={form.collection} onChange={set("collection")}>
                  {COLLECTIONS.map((v) => <option key={v} value={v}>{t(`col_${v}`)}</option>)}
                </select>
              </label>
              <label>{t("stAccess")}
                <select value={form.access_level} onChange={set("access_level")}>
                  {ACCESS_LEVELS.map((v) => <option key={v} value={v}>{t(`stAccess_${v}`)}</option>)}
                </select>
              </label>
              <label>{t("stLanguages")}<input type="text" value={form.languages} onChange={set("languages")} /></label>
              <label>{t("stDateText")}<input type="text" value={form.date_text} onChange={set("date_text")} /></label>
              <label>{t("stCreator")}<input type="text" value={form.creator} onChange={set("creator")} /></label>
              <label>{t("stDevice")}<input type="text" value={form.device} onChange={set("device")} /></label>
              <label>{t("stOperator")}<input type="text" value={form.operator} onChange={set("operator")} required /></label>
            </div>

            {/* Drag & Drop Staging Area */}
            <div
              className={`staff-dropzone ${isDragging ? "dragover" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragging(false);
                if (e.dataTransfer.files?.length) handleFilesAdded(e.dataTransfer.files);
              }}
            >
              <div className="staff-dropzone-icon" aria-hidden="true">📥</div>
              <strong>{t("stDropZoneLead")}</strong>
              <span className="muted" style={{ fontSize: "var(--step--1)" }}>{t("stDropZoneHint")}</span>
              <input
                type="file"
                multiple
                aria-label={t("stFiles")}
                onChange={(e) => { if (e.target.files) handleFilesAdded(e.target.files); }}
              />
            </div>

            {/* Staged Pre-Flight Files Table */}
            {files.length > 0 && (
              <div className="staff-staged-tray">
                <div className="staff-staged-header">
                  <strong>{t("stStagedFiles", { n: files.length })}</strong>
                  <div className="row">
                    <span className="chip">{t("stTotalSize")}: {formatBytes(totalBytes)}</span>
                    <button type="button" className="btn quiet small" onClick={() => setFiles([])}>
                      {t("stClearStaging")}
                    </button>
                  </div>
                </div>
                <table className="grid" aria-label={t("stStagedFiles", { n: files.length })}>
                  <thead>
                    <tr>
                      <th>{t("stTitle")}</th>
                      <th>{t("stItemType")}</th>
                      <th>{t("stCost")}</th>
                      <th>{t("stStatus")}</th>
                      <th><span className="visually-hidden">{t("stActions")}</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {files.map((f, idx) => (
                      <tr key={`${f.name}-${idx}`}>
                        <td>{f.name}</td>
                        <td><span className="chip">{f.name.split(".").pop()?.toUpperCase() || f.type}</span></td>
                        <td>{formatBytes(f.size)}</td>
                        <td><span className="status ok">✓ {t("stPreflightReady")}</span></td>
                        <td>
                          <button type="button" className="btn quiet small" onClick={() => removeFile(idx)}>
                            {t("remove")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="row">
              <button type="submit" className="btn" disabled={busy || files.length === 0}>
                {busy ? t("stUploading") : t("stStoreQueue")}
              </button>
            </div>
            {view}
          </form>
        </>
      )}
      {result && (
        <Section title={t("stIntakeResult")}>
          <p>{t("stItemWord")} <Link to={`/staff/items/${String(result.item_id)}`}>#{String(result.item_id)}</Link>, {t("stIntakeTail", { pages: String(result.pages), job: String(result.job_id ?? t("stNotQueued")) })}</p>
          <table className="grid" aria-label={t("stStoredFiles")}>
            <thead><tr><th>{t("stFile")}</th><th>{t("stStatus")}</th><th>{"SHA-256"}</th><th>{t("stNote")}</th></tr></thead>
            <tbody>
              {(result.files as Json[]).map((f, i) => (
                <tr key={i}><td>{String(f.name)}</td><td>{String(f.status)}</td><td><code>{String(f.sha256 ?? "").slice(0, 16)}</code></td><td>{String(f.detail ?? "")}</td></tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </>
  );
}

// ---------------------------------------------------------------- review queue

export function StaffReview() {
  const { token, user, can } = useStaff();
  const { t } = useSession();
  const q = useApi<Record<string, Json[]>>("/api/staff/review/queue", token);
  const { run, busy, view } = useAction();
  const [selectedPages, setSelectedPages] = useState<Record<string, boolean>>({});

  if (q.error) return <p className="notice bad" role="alert">{errText(q.error)}</p>;
  if (!q.data) return <Loading center />;
  const d = q.data;
  const archivist = can("archivist");
  // Admins and archivists review any language; translation reviewers only the languages they are named for.
  const reviewsLanguage = (lang: string) => archivist || (can("translation_reviewer") && Boolean(user?.languages.includes(lang)));

  const selectedIds = Object.keys(selectedPages).filter((k) => selectedPages[k]);
  const allSelected = d.pages.length > 0 && d.pages.every((p) => selectedPages[String(p.id)]);

  const toggleAll = (checked: boolean) => {
    const next: Record<string, boolean> = {};
    for (const p of d.pages) next[String(p.id)] = checked;
    setSelectedPages(next);
  };

  const approveBatch = (ids: string[]) => {
    if (!ids.length) return;
    void run(async (tk) => {
      for (const pid of ids) {
        await api.post(`/api/staff/pages/${pid}/review`, { action: "approve" }, tk);
      }
    }, t("stBatchApproveHighConf"), () => {
      setSelectedPages({});
      q.reload();
    });
  };

  const approveHighConfidence = () => {
    const highConfIds = d.pages
      .filter((p) => String(p.status) !== "rejected" && !p.sarvam_last_error)
      .map((p) => String(p.id));
    if (!highConfIds.length) return;
    if (window.confirm(t("stBatchApproveConfirm", { n: highConfIds.length }))) {
      approveBatch(highConfIds);
    }
  };

  return (
    <>
      <h1>{t("stNavReview")}</h1>
      <Flash />
      {view}
      {!archivist && <p className="muted">{t("stArchivistOnly")}</p>}
      <Section title={t("stPagesN", { n: d.pages.length })} actions={
        archivist && d.pages.length > 0 ? (
          <div className="row">
            <button
              type="button"
              className="btn secondary small"
              disabled={busy}
              onClick={approveHighConfidence}
            >
              ⚡ {t("stBatchApproveHighConf")}
            </button>
            {selectedIds.length > 0 && (
              <button
                type="button"
                className="btn small"
                disabled={busy}
                onClick={() => approveBatch(selectedIds)}
              >
                ✓ {t("stApproveSelected", { n: selectedIds.length })}
              </button>
            )}
          </div>
        ) : undefined
      }>
        {d.pages.length === 0 ? <Nothing /> : (
          <table className="grid" aria-label={t("stPagesWaiting")}>
            <thead>
              <tr>
                {archivist && (
                  <th style={{ width: 44 }}>
                    <input
                      type="checkbox"
                      aria-label={t("stSelectAll")}
                      checked={allSelected}
                      onChange={(e) => toggleAll(e.target.checked)}
                      style={{ width: 20, height: 20 }}
                    />
                  </th>
                )}
                <th>{t("stItemWord")}</th>
                <th>{t("stPage")}</th>
                <th>{t("stStatus")}</th>
                <th>{t("stRoute")}</th>
                <th>{t("stPriority")}</th>
                <th><span className="visually-hidden">{t("stActions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {d.pages.map((p) => (
                <tr key={String(p.id)}>
                  {archivist && (
                    <td>
                      <input
                        type="checkbox"
                        aria-label={String(p.item_title)}
                        checked={Boolean(selectedPages[String(p.id)])}
                        onChange={(e) => setSelectedPages((prev) => ({ ...prev, [String(p.id)]: e.target.checked }))}
                        style={{ width: 20, height: 20 }}
                      />
                    </td>
                  )}
                  <td>{String(p.item_title)}</td>
                  <td>{String(p.label ?? p.sequence)}</td>
                  <td>{String(p.status)}{p.sarvam_last_error ? ` (${String(p.sarvam_last_error)})` : ""}</td>
                  <td>{String(p.ocr_route)}</td>
                  <td>
                    <span className="chip">{String(p.priority)}</span>
                    {!p.sarvam_last_error && <span className="chip verified" style={{ marginLeft: 6 }}>{t("stHighConfidenceChip")}</span>}
                  </td>
                  <td><Link className="btn small" to={`/staff/pages/${String(p.id)}`}>{t("stReview")}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      <Section title={t("stBatchesN", { n: d.batches.length })}>
        {d.batches.map((b) => (
          <p key={String(b.id)}>{t("stBatchLine", { id: String(b.id), item: String(b.item_id), pages: String(b.pages), n: (b.sample as number[]).length })} <Link to={`/staff/batches/${String(b.id)}`}>{t("stCheckSample")}</Link></p>
        ))}
        {d.batches.length === 0 && <Nothing />}
      </Section>
      <Section title={t("stSegmentsN", { n: d.segments.length })}>
        {d.segments.map((s) => (
          <div key={String(s.id)} className="row" style={{ marginBottom: 8 }}>
            <span className="chip">{formatMs(Number(s.start_ms))}</span>
            <span style={{ flex: 1 }}>{String(s.text)}</span>
            {Boolean(s.draft_engine) && <span className="chip mt">{t("stSttMachineDraft", { engine: String(s.draft_engine) })}</span>}
            {archivist && <button type="button" className="btn small" disabled={busy} onClick={() => run((tk) => api.post(`/api/staff/segments/${String(s.id)}/review`, { action: "approve" }, tk), t("stSegmentApproved", { id: String(s.id) }), q.reload)}>{t("stApprove")}</button>}
          </div>
        ))}
        {d.segments.length === 0 && <Nothing />}
      </Section>
      <Section title={t("stPhotosN", { n: d.photos.length })}>
        {d.photos.map((p) => (
          <div key={String(p.item_id)} className="row" style={{ marginBottom: 8 }}>
            <span style={{ flex: 1 }}>{String(p.caption)}</span>
            {archivist && <button type="button" className="btn small" disabled={busy} onClick={() => run((tk) => api.post(`/api/staff/photos/${String(p.item_id)}/review`, { action: "approve" }, tk), t("stCaptionApproved"), q.reload)}>{t("stApprove")}</button>}
          </div>
        ))}
        {d.photos.length === 0 && <Nothing />}
      </Section>
      <Section title={t("stTranslationsN", { n: d.translations.length })}>
        {d.translations.map((tr) => (
          <div key={String(tr.id)} className="stack" style={{ marginBottom: 12 }}>
            <span className="chip">{t("stTranslationChip", { lang: String(tr.target_language), method: String(tr.method), id: String(tr.source_passage_id) })}</span>
            <p lang={String(tr.target_language)}>{String(tr.text)}</p>
            <div className="row">
              {reviewsLanguage(String(tr.target_language))
                ? <button type="button" className="btn small" disabled={busy} onClick={() => run((tk) => api.post(`/api/staff/translations/${String(tr.id)}/review`, { action: "approve" }, tk), t("stTranslationApproved"), q.reload)}>{t("stApproveReviewer")}</button>
                : <span className="muted">{t("stTranslationLangOnly", { lang: String(tr.target_language) })}</span>}
            </div>
          </div>
        ))}
        {d.translations.length === 0 && <Nothing />}
      </Section>
      <Section title={t("stReadyN", { n: d.ready_to_publish.length })}>
        {d.ready_to_publish.map((i) => (
          <div key={String(i.id)} className="row" style={{ marginBottom: 8 }}>
            <Link to={`/staff/items/${String(i.id)}`} style={{ flex: 1 }}>{String(i.title)}</Link>
            {archivist && <button type="button" className="btn small" disabled={busy} onClick={() => run((tk) => postDetailed(`/api/staff/items/${String(i.id)}/publish`, {}, tk), t("stPublishQueuedAtomic"), q.reload)}>{t("stPublish")}</button>}
          </div>
        ))}
        {d.ready_to_publish.length === 0 && <Nothing />}
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- page review

export function StaffPage() {
  const { id } = useParams();
  const { token, can } = useStaff();
  const { t } = useSession();
  const nav = useNavigate();
  const page = useApi<Json>(`/api/staff/pages/${id}`, token);
  const { run, busy, view } = useAction();
  const [text, setText] = useState("");
  const [compared, setCompared] = useState(false);
  const [zoomLevel, setZoomLevel] = useState<number>(100);
  const d = page.data;
  const img = useAuthedObjectUrl(d?.preview_file_id ? `/api/staff/files/${String(d.preview_file_id)}` : null);

  useEffect(() => {
    setCompared(false);
    window.scrollTo(0, 0);
  }, [id]);

  useEffect(() => {
    if (!d) return;
    const local = d.local as Json | null;
    const sarvam = d.sarvam as Json | null;
    setText(String(d.approved_text ?? sarvam?.text ?? local?.text ?? ""));
  }, [d]);

  const status = d ? String(d.status) : "";
  const archivist = can("archivist");

  // After a decision the reviewer moves on: next queued page (same item first), else the queue itself.
  const leave = async (tk: string, done: string) => {
    let next: Json | undefined;
    try {
      const queue = await api.get<{ pages: Json[] }>("/api/staff/review/queue", tk);
      const others = queue.pages.filter((p) => String(p.id) !== id);
      next = others.find((p) => p.item_id === d?.item_id) ?? others[0];
    } catch {
      next = undefined;
    }
    if (next) nav(`/staff/pages/${String(next.id)}`, { state: { flash: `${done} ${t("stNextQueuedPage")}` } });
    else nav("/staff/review", { state: { flash: done } });
  };

  const recordQuote = (tk: string) => api.post(`/api/staff/pages/${id}/verify-quotes`, { confirm: true }, tk);

  // The retry runs on the worker; reload only once it has settled, or the page shows the old text.
  const retrySarvam = () =>
    run(
      async (tk) => {
        const { job_id } = await api.post<{ job_id: number }>(`/api/staff/pages/${id}/retry-sarvam`, {}, tk);
        const job = await waitForJob(job_id, tk);
        page.reload();
        if (job === null) throw new ApiError(0, t("stSarvamStillRunning"));
        if (job.status === "failed") throw new ApiError(0, t("stSarvamFailed", { error: String(job.error ?? "") }));
        return String((job.result as Json | null)?.status ?? "");
      },
      (outcome) => t("stSarvamDone", { outcome }),
    );
  const act = (action: string, body: Json = {}) =>
    run(async (tk) => {
      await api.post(`/api/staff/pages/${id}/review`, { action, ...body }, tk);
      let done = t("stPageDecision", { action: PAGE_ACTIONS[action] ? t(PAGE_ACTIONS[action]) : action });
      if (compared && (action === "approve" || action === "correct")) {
        try {
          await recordQuote(tk);
        } catch (e) {
          page.reload();
          throw e;
        }
        done = `${done} ${t("stRecordedQuote")}`;
      }
      await leave(tk, done);
    }, null);

  // Global Keyboard shortcuts for Triage Mode
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const isInput = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT");
      if (isInput && !e.altKey) return;

      const decides = ["a", "x", "r"].includes(e.key.toLowerCase());
      if (decides && !archivist) return;
      if (e.key === "a" || e.key === "A") {
        e.preventDefault();
        if (status !== "approved" && !busy) {
          const isOriginal = text === String((d?.sarvam as Json | null)?.text ?? (d?.local as Json | null)?.text ?? "");
          act(isOriginal ? "approve" : "correct", { text });
        }
      } else if (e.key === "e" || e.key === "E") {
        e.preventDefault();
        document.getElementById("page-text")?.focus();
      } else if (e.key === "x" || e.key === "X") {
        e.preventDefault();
        if (!busy) act("escalate", { reason: "needs second opinion" });
      } else if (e.key === "r" || e.key === "R") {
        e.preventDefault();
        if (!busy) act("reject", { reason: "unusable capture" });
      } else if (e.key === "z" || e.key === "Z") {
        e.preventDefault();
        setZoomLevel((z) => (z === 100 ? 150 : z === 150 ? 200 : 100));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [d, text, status, busy, archivist]);

  if (page.error) return <p className="notice bad" role="alert">{errText(page.error)}</p>;
  if (!d) return <Loading center />;

  const signals = (d.quality_signals ?? {}) as Json;
  const gate = d.gate_passed === null ? t("stNA") : d.gate_passed ? t("stPassed") : t("stFailed");

  return (
    <>
      <p><Link to={`/staff/items/${String(d.item_id)}`}>{String(d.item_title)}</Link></p>
      <h1>{t("stPageN", { n: String(d.label ?? d.sequence) })}</h1>

      {/* Triage Hotkey Banner */}
      <div className="triage-banner" role="region" aria-label={t("stTriageModeBanner")}>
        <span>{t("stTriageModeBanner")}</span>
        <div className="triage-keys" aria-hidden="true">
          <span className="triage-key-chip">A</span>
          <span className="triage-key-chip">E</span>
          <span className="triage-key-chip">X</span>
          <span className="triage-key-chip">R</span>
          <span className="triage-key-chip">Z</span>
        </div>
      </div>

      <div className="row" style={{ marginBottom: 12 }}>
        <span className="chip">{t("stChipStatus", { v: status })}</span>
        <span className="chip">{t("stChipRoute", { v: String(d.ocr_route) })}</span>
        <span className="chip">{d.gate_version ? t("stChipGate", { v: gate, ver: String(d.gate_version) }) : t("stChipGateNoVersion", { v: gate })}</span>
        <span className={`chip${d.quote_verified ? " verified" : ""}`}>{d.quote_verified ? t("stQuoteVerified") : t("stNotQuoteVerified")}</span>
        <span className="chip">{d.external_processing_allowed ? t("stExternalAllowed") : t("stExternalNotAllowed")}</span>
      </div>
      <Flash />
      {view}
      <div className="review-pair">
        <div className="scan-viewer-box">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
            <div className="scan-zoom-controls" role="group" aria-label={t("scanControls")}>
              <button
                type="button"
                className={`btn secondary small ${zoomLevel === 100 ? "active" : ""}`}
                onClick={() => setZoomLevel(100)}
              >
                {t("stScanZoomFit")}
              </button>
              <button
                type="button"
                className={`btn secondary small ${zoomLevel === 150 ? "active" : ""}`}
                onClick={() => setZoomLevel(150)}
              >
                {t("stScanZoom150")}
              </button>
              <button
                type="button"
                className={`btn secondary small ${zoomLevel === 200 ? "active" : ""}`}
                onClick={() => setZoomLevel(200)}
              >
                {t("stScanZoom200")}
              </button>
            </div>
            <span className="muted" style={{ fontSize: "var(--step--1)" }}>
              {t("stPageN", { n: String(d.sequence) })}
            </span>
          </div>
          <figure style={{ margin: 0 }}>
            <div className="scan-zoom-wrap">
              {img ? (
                <img
                  src={img}
                  alt={t("stMasterAlt", { n: String(d.sequence) })}
                  style={{ width: `${zoomLevel}%` }}
                />
              ) : (
                <div className="empty-state">{d.preview_file_id ? t("stLoadingScan") : t("stNoScanPreview")}</div>
              )}
            </div>
            <figcaption className="muted" style={{ marginTop: 6 }}>{t("stMasterCaption")}</figcaption>
          </figure>
        </div>

        <div className="stack">
          <label htmlFor="page-text">{t("stTextToApprove")}</label>
          <textarea id="page-text" value={text} onChange={(e) => setText(e.target.value)} lang={String(d.language ?? "en")} readOnly={!archivist} />
          {!archivist ? <p className="muted">{t("stArchivistOnly")}</p> : (
            <div className="row">
              <button type="button" className="btn" disabled={busy || status === "approved"} onClick={() => act(text === String((d.sarvam as Json | null)?.text ?? (d.local as Json | null)?.text ?? "") ? "approve" : "correct", { text })}>{t("stApproveText")}</button>
              <button type="button" className="btn secondary" disabled={busy} onClick={() => act("escalate", { reason: "needs second opinion" })}>{t("stEscalate")}</button>
              <button type="button" className="btn danger" disabled={busy} onClick={() => act("reject", { reason: "unusable capture" })}>{t("stRejectPage")}</button>
              {(status === "sarvam_pending" || status === "needs_full_review") && Boolean(d.external_processing_allowed) && (
                <button type="button" className="btn secondary" disabled={busy} onClick={retrySarvam}>{t("stRetrySarvam")}</button>
              )}
            </div>
          )}
          <div className="sheet stack" style={{ padding: 14 }}>
            <strong>{t("stQuoteVerification")}</strong>
            {d.quote_verified ? (
              <p className="muted" style={{ margin: 0 }}>{t("stQuoteAlreadyVerified")}</p>
            ) : !archivist ? (
              <p className="muted" style={{ margin: 0 }}>{t("stNotQuoteVerified")}</p>
            ) : (
              <>
                <label className="row" style={{ fontWeight: 400 }}>
                  <input type="checkbox" checked={compared} onChange={(e) => setCompared(e.target.checked)} style={{ width: 24, height: 24 }} />
                  {status === "approved" ? t("stComparedWords") : t("stComparedBeforeApprove")}
                </label>
                {status === "approved" && (
                  <button type="button" className="btn secondary" disabled={!compared || busy} onClick={() => run(async (tk) => { await recordQuote(tk); await leave(tk, t("stRecordedQuote")); }, null)}>{t("stRecordQuote")}</button>
                )}
              </>
            )}
          </div>
        </div>
      </div>
      <Section title={t("stOcrResults")}>
        <table className="grid" aria-label={t("stOcrResults")}>
          <thead><tr><th>{t("stEngine")}</th><th>{t("stStatus")}</th><th>{t("stConfidence")}</th><th>{t("stSelected")}</th><th>{t("stError")}</th></tr></thead>
          <tbody>
            {(d.results as Json[]).map((r) => (
              <tr key={String(r.id)}><td>{String(r.engine)} {String(r.engine_version ?? "")}</td><td>{String(r.status)}</td><td>{r.mean_confidence == null ? "" : Number(r.mean_confidence).toFixed(1)}</td><td>{r.selected ? t("stYes") : ""}</td><td>{String(r.error ?? "")}</td></tr>
            ))}
          </tbody>
        </table>
        {Object.keys(signals).length > 0 && <pre style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{JSON.stringify(signals, null, 1)}</pre>}
        {Array.isArray(d.diff) && (d.diff as string[]).length > 0 && (
          <>
            <h3>{t("stDiff")}</h3>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 13, background: "var(--paper)", padding: 10 }}>{(d.diff as string[]).join("\n")}</pre>
          </>
        )}
      </Section>
      <Section title={t("stDecisions")}>
        <table className="grid" aria-label={t("stReviewDecisions")}>
          <thead><tr><th>{t("stWhen")}</th><th>{t("stAction")}</th><th>{t("stReviewer")}</th><th>{t("stReason")}</th><th>{t("stSeeded")}</th></tr></thead>
          <tbody>
            {(d.decisions as Json[]).map((x) => (
              <tr key={String(x.id)}><td>{String(x.at).slice(0, 19)}</td><td>{String(x.action)}</td><td>{String(x.reviewer)}</td><td>{String(x.reason ?? "")}</td><td>{x.seeded_fixture ? t("stSeededYes") : ""}</td></tr>
            ))}
          </tbody>
        </table>
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- batch sample check

function SampleCheck({ page, value, onChange, readOnly }: { page: Json; value: { checked: boolean; text: string }; onChange: (v: { checked: boolean; text: string }) => void; readOnly: boolean }) {
  const { t } = useSession();
  const img = useAuthedObjectUrl(page.delivery_file_id ? `/api/staff/files/${String(page.delivery_file_id)}` : null);
  return (
    <div className="review-pair" style={{ marginBottom: 20 }}>
      {img ? <img src={img} alt={t("stSampleAlt", { n: String(page.sequence) })} /> : <div className="empty-state">{t("stLoadingScan")}</div>}
      <div className="stack">
        <textarea aria-label={t("stCandidateText", { n: String(page.sequence) })} value={value.text} onChange={(e) => onChange({ ...value, text: e.target.value })} lang={String(page.language ?? "en")} readOnly={readOnly} />
        {!readOnly && <label className="row" style={{ fontWeight: 400 }}>
          <input type="checkbox" checked={value.checked} onChange={(e) => onChange({ ...value, checked: e.target.checked })} style={{ width: 24, height: 24 }} />
          {t("stCheckedPage")}
        </label>}
      </div>
    </div>
  );
}

export function StaffBatch() {
  const { id } = useParams();
  const { token, can } = useStaff();
  const { t } = useSession();
  const b = useApi<Json>(`/api/staff/batches/${id}`, token);
  const { run, busy, view } = useAction();
  const [checks, setChecks] = useState<Record<string, { checked: boolean; text: string }>>({});
  useEffect(() => {
    if (!b.data) return;
    const init: Record<string, { checked: boolean; text: string }> = {};
    for (const p of b.data.sample as Json[]) init[String(p.id)] = { checked: false, text: String(p.candidate_text ?? "") };
    setChecks(init);
  }, [b.data]);
  if (b.error) return <p className="notice bad" role="alert">{errText(b.error)}</p>;
  if (!b.data) return <Loading center />;
  const archivist = can("archivist");
  const sample = b.data.sample as Json[];
  const allChecked = sample.every((p) => checks[String(p.id)]?.checked);
  const decide = (passed: boolean) => {
    const sample_checks: Record<string, Json> = {};
    for (const p of sample) {
      const c = checks[String(p.id)];
      if (!c?.checked) continue;
      sample_checks[String(p.id)] = c.text !== String(p.candidate_text ?? "") ? { ok: false, text: c.text } : { ok: true };
    }
    void run((tk) => api.post(`/api/staff/batches/${id}/decide`, { passed, reason: passed ? "sample checked" : "sample failed", sample_checks }, tk),
      passed ? t("stBatchPassed") : t("stBatchFailed"), b.reload);
  };
  return (
    <>
      <h1>{t("stBatchN", { n: String(b.data.id) })}</h1>
      <p className="muted">{t("stBatchLead", { status: String(b.data.status), n: (b.data.page_ids as number[]).length })}</p>
      {view}
      {sample.map((p) => (
        <SampleCheck key={String(p.id)} page={p} readOnly={!archivist} value={checks[String(p.id)] ?? { checked: false, text: "" }} onChange={(v) => setChecks({ ...checks, [String(p.id)]: v })} />
      ))}
      {!archivist ? <p className="muted">{t("stArchivistOnly")}</p> : (
        <div className="row">
          <button type="button" className="btn" disabled={!allChecked || busy || b.data.status !== "open"} onClick={() => decide(true)}>{t("stPassBatch")}</button>
          <button type="button" className="btn danger" disabled={busy || b.data.status !== "open"} onClick={() => decide(false)}>{t("stFailBatch")}</button>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------- items

export function StaffItems() {
  const { token } = useStaff();
  const { t } = useSession();
  const items = useApi<Json[]>("/api/staff/items", token);
  return (
    <>
      <h1>{t("stNavItems")}</h1>
      {items.loading && <Loading center />}
      {items.error && <p className="notice bad" role="alert">{errText(items.error)}</p>}
      {items.data && (
        <table className="grid" aria-label={t("stAllItems")}>
          <thead><tr><th>#</th><th>{t("stTitle")}</th><th>{t("stCollection")}</th><th>{t("stState")}</th><th>{t("stVersion")}</th><th>{t("stPagesApproved")}</th><th>{t("stDisplay")}</th><th>{t("stTraining")}</th><th>{t("stAccess")}</th></tr></thead>
          <tbody>
            {(items.data ?? []).map((i) => (
              <tr key={String(i.id)}>
                <td>{String(i.id)}</td>
                <td><Link to={`/staff/items/${String(i.id)}`}>{String(i.title)}</Link>{i.is_fixture ? ` (${t("stFixture")})` : ""}</td>
                <td>{String(i.collection)}</td><td>{String(i.state)}</td><td>{String(i.version)}</td>
                <td>{String(i.pages_approved)} / {String(i.pages)}</td><td>{String(i.display_permission)}</td><td>{String(i.training_permission)}</td><td>{String(i.access_level)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

interface StaffSegment { id: number; start_ms: number; end_ms: number; speaker: string | null; text: string; status: string; quote_verified: boolean; draft_engine: string | null }
interface StaffDerivative { id: number; kind: string; language: string; status: string; content: string | null; label: string | null; generator: string | null }
interface StaffPhoto { caption: string; people: string[] | null; place: string | null; event: string | null; date_text: string | null; photographer: string | null; source_reference: string | null; status: string }
interface PublishedPassage { id: number; page_sequence: number | null; start_ms: number | null; text: string }
interface ConstitutionLink { id: number; article_number: string; article_title: string; passage_id: number; note: string | null; created_by: string; created_at: string }
interface StaffArticle { number: string; titles: Record<string, string>; part: string | null }
interface MetadataChange { version: number; before: Json | null; after: Json | null; actor: string; reason: string; at: string }

/** A destructive action that asks for a reason inline before it runs. */
function ReasonAction({ label, confirmLabel, busy, onConfirm }: { label: string; confirmLabel: string; busy: boolean; onConfirm: (reason: string) => void }) {
  const { t } = useSession();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!open) return <button type="button" className="btn danger small" disabled={busy} onClick={() => setOpen(true)}>{label}</button>;
  return (
    <form className="row" onSubmit={(e) => { e.preventDefault(); onConfirm(reason.trim()); }}>
      <label className="row" style={{ fontWeight: 400 }}>{t("stReason")}
        <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required autoComplete="off" autoFocus style={{ width: 260 }} />
      </label>
      <button type="submit" className="btn danger small" disabled={busy || reason.trim().length < 3}>{confirmLabel}</button>
      <button type="button" className="btn quiet small" onClick={() => { setOpen(false); setReason(""); }}>{t("stCancel")}</button>
    </form>
  );
}

const fmtValue = (t: T, v: unknown) => (v == null || v === "" ? t("stEmpty") : Array.isArray(v) ? v.join(", ") || t("stEmpty") : String(v));

function MetadataSection({ id, metadata, version, reload }: { id: string; metadata: ItemMetadata | undefined; version: unknown; reload: () => void }) {
  const { token, can } = useStaff();
  const { t } = useSession();
  const { run, busy, view } = useAction();
  const [form, setForm] = useState<MetadataForm>(() => metadataForm(metadata));
  const [showHistory, setShowHistory] = useState(false);
  const history = useApi<MetadataChange[]>(showHistory ? `/api/staff/items/${id}/metadata/history` : null, token);
  const stored = JSON.stringify(metadata ?? null);
  useEffect(() => setForm(metadataForm(metadata)), [stored]);
  const set = (k: keyof MetadataForm) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const text = (k: keyof MetadataForm, label: Key, type = "text") => (
    <label>{t(label)}<input type={type} name={k} value={form[k]} onChange={set(k)} autoComplete="off" /></label>
  );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run((tk) => api.put(`/api/staff/items/${id}/metadata`, metadataBody(form), tk), t("stMetaSaved"), () => {
      reload();
      if (showHistory) history.reload();
    });
  };
  return (
    <Section title={t("stMetadata")} actions={<span className="chip">{t("stMetaVersion", { n: String(version ?? 0) })}</span>}>
      <form className="stack" onSubmit={submit}>
        {/* Read-only for anyone but archivists: the fields stay visible, disabled. */}
        <fieldset className="form-grid" disabled={!can("archivist")} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
          {text("subjects", "stSubjects")}
          {text("people", "stPeople")}
          {text("places", "stPlaces")}
          {text("date_text", "stDateText")}
          {text("date_start", "stDateStart", "date")}
          {text("date_end", "stDateEnd", "date")}
          <label>{t("stDateCertainty")}
            <select name="date_certainty" value={form.date_certainty} onChange={set("date_certainty")}>
              {CERTAINTIES.map((c) => <option key={c} value={c}>{t(`stCert_${c}`)}</option>)}
            </select>
          </label>
          {text("languages", "stLanguages")}
          {text("edition", "stEdition")}
          {text("volume", "stVolume")}
          {text("publisher", "stPublisher")}
          {text("creator", "stCreator")}
        </fieldset>
        {!can("archivist") ? <p className="muted">{t("stArchivistOnly")}</p> : (
          <div className="row" style={{ alignItems: "end" }}>
            <label style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>{t("stChangeReason")}
              <input type="text" name="reason" value={form.reason} onChange={set("reason")} minLength={3} required autoComplete="off" />
            </label>
            <button type="submit" className="btn" disabled={busy}>{busy ? t("stSaving") : t("stSaveMeta")}</button>
          </div>
        )}
        {view}
      </form>
      <details style={{ marginTop: 14 }} onToggle={(e) => setShowHistory(e.currentTarget.open)}>
        <summary style={{ cursor: "pointer", padding: "10px 0", fontWeight: 500 }}>{t("stHistory")}</summary>
        {history.loading && <Loading />}
        {history.error && <p className="notice bad">{errText(history.error)}</p>}
        {history.data && history.data.length === 0 && <p className="muted">{t("stNoChanges")}</p>}
        {history.data && history.data.length > 0 && (
          <table className="grid" aria-label={t("stHistoryTable")}>
            <thead><tr><th>{t("stVersion")}</th><th>{t("stWhen")}</th><th>{t("stWho")}</th><th>{t("stReason")}</th><th>{t("stChanged")}</th></tr></thead>
            <tbody>
              {history.data.map((h) => {
                const keys = [...new Set([...Object.keys(h.before ?? {}), ...Object.keys(h.after ?? {})])]
                  .filter((k) => JSON.stringify(h.before?.[k] ?? null) !== JSON.stringify(h.after?.[k] ?? null));
                return (
                  <tr key={h.version}>
                    <td>{h.version}</td><td>{String(h.at).slice(0, 19)}</td><td>{h.actor}</td><td>{h.reason}</td>
                    <td>{keys.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{keys.map((k) => <li key={k}><strong>{k}</strong>: {fmtValue(t, h.before?.[k])} → {fmtValue(t, h.after?.[k])}</li>)}</ul> : t("stNoFieldChanges")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </details>
    </Section>
  );
}

function SummariesSection({ id, derivatives, externalAllowed, reload }: { id: string; derivatives: StaffDerivative[]; externalAllowed: boolean; reload: () => void }) {
  const { can } = useStaff();
  const { t } = useSession();
  const { run, busy, view } = useAction();
  const [language, setLanguage] = useState("en");
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [edit, setEdit] = useState("");
  const draft = (withText: boolean) =>
    run((tk) => api.post(`/api/staff/items/${id}/summary`, withText ? { language, text: text.trim() } : { language }, tk),
      withText ? t("stHumanSaved") : t("stAiDrafted"),
      () => { if (withText) setText(""); reload(); });
  const review = (x: StaffDerivative, action: "approve" | "correct" | "reject", body: Json = {}) =>
    run((tk) => api.post(`/api/staff/derivatives/${x.id}/review`, { action, ...body }, tk),
      action === "reject" ? t("stDraftRejected") : t("stSummaryApproved"),
      () => { setEditing(null); reload(); });
  const archivist = can("archivist");
  return (
    <Section title={t("stSummaries")}>
      <p className="notice">{t("stSummariesNote")}</p>
      {!archivist ? <p className="muted">{t("stArchivistOnly")}</p> : (
        <>
          <div className="multilingual-nav" role="tablist" aria-label={t("stMultilingualMeta")}>
            {LANGS.map((l) => (
              <button
                key={l.code}
                type="button"
                role="tab"
                aria-selected={language === l.code}
                className={`multilingual-tab ${language === l.code ? "active" : ""}`}
                onClick={() => setLanguage(l.code)}
              >
                {l.name} ({l.code})
                {derivatives.some((d) => d.language === l.code) && <span style={{ marginLeft: 6 }}>✓</span>}
              </button>
            ))}
          </div>
          <div className="stack" style={{ gap: 10 }}>
            <label htmlFor="summary-draft">{t("stSummaryText")}</label>
            <textarea id="summary-draft" value={text} onChange={(e) => setText(e.target.value)} lang={language} rows={4} />
            <div className="row">
              <button type="button" className="btn" disabled={busy || !text.trim()} onClick={() => draft(true)}>{t("stSaveHuman")}</button>
              <button type="button" className="btn secondary" disabled={busy || !externalAllowed} onClick={() => draft(false)}>{t("stDraftAi")}</button>
            </div>
            {!externalAllowed && <p className="muted" style={{ margin: 0 }}>{t("stDraftAiRights")}</p>}
            {view}
          </div>
        </>
      )}
      {derivatives.length > 0 && (
        <div className="stack" style={{ marginTop: 18, gap: 14 }}>
          {derivatives.map((x) => (
            <div key={x.id} className="stack" style={{ gap: 8, paddingTop: 12, borderTop: "1px solid var(--rule)" }}>
              <div className="row">
                <span className="chip">{x.label ?? x.kind}</span>
                <span className="chip">{x.kind} ({x.language})</span>
                <span className="chip">{x.status}</span>
                {x.status === "draft" && <span className="chip mt">{t("stNotVisible")}</span>}
                {x.generator && <span className="muted">{x.generator}</span>}
              </div>
              {editing === x.id ? (
                <>
                  <label htmlFor={`deriv-${x.id}`} className="visually-hidden">{t("stCorrectedText")}</label>
                  <textarea id={`deriv-${x.id}`} value={edit} onChange={(e) => setEdit(e.target.value)} lang={x.language} rows={4} />
                  <div className="row">
                    <button type="button" className="btn small" disabled={busy || !edit.trim()} onClick={() => review(x, "correct", { text: edit.trim() })}>{t("stSaveCorrection")}</button>
                    <button type="button" className="btn quiet small" onClick={() => setEditing(null)}>{t("stCancel")}</button>
                  </div>
                </>
              ) : x.content ? <p lang={x.language} style={{ margin: 0 }}>{x.content}</p> : null}
              {archivist && x.status === "draft" && editing !== x.id && (
                <div className="row">
                  <button type="button" className="btn small" disabled={busy} onClick={() => review(x, "approve")}>{t("stApprove")}</button>
                  {x.content != null && <button type="button" className="btn secondary small" disabled={busy} onClick={() => { setEditing(x.id); setEdit(x.content ?? ""); }}>{t("stCorrect")}</button>}
                  <button type="button" className="btn danger small" disabled={busy} onClick={() => window.confirm(t("stConfirmRejectDraft")) && review(x, "reject")}>{t("stReject")}</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

function photoForm(p: StaffPhoto) {
  return {
    caption: p.caption ?? "", photographer: p.photographer ?? "", source_reference: p.source_reference ?? "",
    place: p.place ?? "", event: p.event ?? "", date_text: p.date_text ?? "", people: (p.people ?? []).join(", "),
  };
}

function PhotoSection({ id, photo, reload }: { id: string; photo: StaffPhoto; reload: () => void }) {
  const { can } = useStaff();
  const { t } = useSession();
  const { run, busy, view } = useAction();
  const [form, setForm] = useState(() => photoForm(photo));
  const stored = JSON.stringify(photo);
  useEffect(() => setForm(photoForm(photo)), [stored]);
  const set = (k: keyof ReturnType<typeof photoForm>) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const changed = JSON.stringify(form) !== JSON.stringify(photoForm(photo));
  const approve = () => {
    const updates = {
      caption: form.caption.trim(), photographer: form.photographer.trim() || null, source_reference: form.source_reference.trim() || null,
      place: form.place.trim() || null, event: form.event.trim() || null, date_text: form.date_text.trim() || null, people: parseList(form.people),
    };
    void run((tk) => api.post(`/api/staff/photos/${id}/review`, { action: changed ? "correct" : "approve", updates }, tk),
      changed ? t("stCaptionCorrected") : t("stCaptionApproved"), reload);
  };
  return (
    <Section title={t("stPhotoSection")} actions={<span className={`chip${photo.status === "approved" ? " verified" : ""}`}>{t("stChipStatus", { v: photo.status })}</span>}>
      <p className="muted">{t("stPhotoNote")}</p>
      <fieldset className="stack" disabled={!can("archivist")} style={{ gap: 10, border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <label htmlFor="photo-caption">{t("stCaption")}</label>
        <textarea id="photo-caption" value={form.caption} onChange={set("caption")} rows={3} />
        <div className="form-grid">
          <label>{t("stPhotographer")}<input type="text" value={form.photographer} onChange={set("photographer")} autoComplete="off" /></label>
          <label>{t("stSourceRef")}<input type="text" value={form.source_reference} onChange={set("source_reference")} autoComplete="off" /></label>
          <label>{t("stPlace")}<input type="text" value={form.place} onChange={set("place")} autoComplete="off" /></label>
          <label>{t("stEvent")}<input type="text" value={form.event} onChange={set("event")} autoComplete="off" /></label>
          <label>{t("stDateText")}<input type="text" value={form.date_text} onChange={set("date_text")} autoComplete="off" /></label>
          <label>{t("stPeople")}<input type="text" value={form.people} onChange={set("people")} autoComplete="off" /></label>
        </div>
        {!can("archivist") ? <p className="muted">{t("stArchivistOnly")}</p> : (
          <div className="row">
            <button type="button" className="btn" disabled={busy || !form.caption.trim()} onClick={approve}>{changed ? t("stSaveCorrections") : t("stApproveCaption")}</button>
            <button type="button" className="btn danger" disabled={busy} onClick={() => window.confirm(t("stConfirmRejectCaption")) && run((tk) => api.post(`/api/staff/photos/${id}/review`, { action: "reject" }, tk), t("stCaptionRejected"), reload)}>{t("stRejectCaption")}</button>
          </div>
        )}
        {view}
      </fieldset>
    </Section>
  );
}

function SegmentsSection({ segments, reload }: { segments: StaffSegment[]; reload: () => void }) {
  const { can } = useStaff();
  const { t } = useSession();
  const { run, busy, view } = useAction();
  const [editing, setEditing] = useState<number | null>(null);
  const [edit, setEdit] = useState("");
  const review = (s: StaffSegment, action: "approve" | "correct" | "reject", body: Json = {}) =>
    run((tk) => api.post(`/api/staff/segments/${s.id}/review`, { action, ...body }, tk),
      t(action === "reject" ? "stSegRejected" : action === "correct" ? "stSegCorrected" : "stSegApproved", { t: formatMs(s.start_ms) }),
      () => { setEditing(null); reload(); });
  const archivist = can("archivist");
  return (
    <Section title={t("stSegments")}>
      {!archivist && <p className="muted">{t("stArchivistOnly")}</p>}
      {view}
      {segments.map((s) => (
        <div key={s.id} className="row" style={{ marginBottom: 10, alignItems: "flex-start" }}>
          <span className="chip">{formatMs(s.start_ms)}</span>
          {editing === s.id ? (
            <div className="stack" style={{ flex: 1, gap: 6 }}>
              <label htmlFor={`seg-${s.id}`} className="visually-hidden">{t("stCorrectedTranscriptAt", { t: formatMs(s.start_ms) })}</label>
              <textarea id={`seg-${s.id}`} value={edit} onChange={(e) => setEdit(e.target.value)} rows={3} />
              <div className="row">
                <button type="button" className="btn small" disabled={busy || !edit.trim()} onClick={() => review(s, "correct", { text: edit.trim() })}>{t("stSaveCorrection")}</button>
                <button type="button" className="btn quiet small" onClick={() => setEditing(null)}>{t("stCancel")}</button>
              </div>
            </div>
          ) : <span style={{ flex: 1 }}>{s.speaker ? <strong>{s.speaker}: </strong> : null}{s.text}</span>}
          {s.draft_engine && (s.status === "draft"
            ? <span className="chip mt">{t("stSttMachineDraft", { engine: s.draft_engine })}</span>
            : <span className="muted">{t("stSttDraftedBy", { engine: s.draft_engine })}</span>)}
          <span className="chip">{s.status}</span>
          {archivist && s.status === "draft" && editing !== s.id && (
            <>
              <button type="button" className="btn small" disabled={busy} onClick={() => review(s, "approve")}>{t("stApprove")}</button>
              <button type="button" className="btn secondary small" disabled={busy} onClick={() => { setEditing(s.id); setEdit(s.text); }}>{t("stCorrect")}</button>
              <ReasonAction label={t("stReject")} confirmLabel={t("stConfirmReject")} busy={busy} onConfirm={(reason) => review(s, "reject", { reason })} />
            </>
          )}
          {archivist && s.status === "approved" && !s.quote_verified && (
            <button type="button" className="btn secondary small" disabled={busy} title={t("stAudioOnly")}
              onClick={() => window.confirm(t("stConfirmListened")) && run((tk) => api.post(`/api/staff/segments/${s.id}/verify-quotes`, { confirm: true }, tk), t("stRecorded"), reload)}>
              {t("stRecordAudioCheck")}
            </button>
          )}
          {s.quote_verified && <span className="chip verified">{t("stQuoteVerified")}</span>}
        </div>
      ))}
    </Section>
  );
}

/** Sarvam speech-to-text: queues a draft transcript that always goes to full review, never to publication. */
function SpeechToTextSection({ id, allowed, hasRecording, reload }: { id: string; allowed: boolean; hasRecording: boolean; reload: () => void }) {
  const { token, can } = useStaff();
  const { t } = useSession();
  const { run, busy, view } = useAction();
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const jobs = useApi<Json[]>(jobId ? "/api/staff/jobs" : null, token);
  const job = jobs.data?.find((j) => j.id === jobId);
  const status = job ? String(job.status) : null;
  useEffect(() => {
    if (!jobId || status === "failed") return;
    if (status === "done") {
      reload();
      return;
    }
    const timer = setTimeout(jobs.reload, 3000);
    return () => clearTimeout(timer);
  }, [jobId, status, jobs.data]);
  if (!can("archivist") && !can("reviewer")) return null;
  const start = (withFile: boolean) => {
    const fd = new FormData();
    if (language) fd.set("language", language);
    if (withFile && file) fd.set("file", file);
    void run(async (tk) => setJobId((await api.post<{ job_id: number }>(`/api/staff/items/${id}/speech-to-text`, fd, tk)).job_id), t("stSttQueued"));
  };
  return (
    <Section title={t("stSpeechToText")}>
      <p className="notice">{t("stSttWarning")}</p>
      <p className="muted">{t("stSttSent")}</p>
      {!allowed ? <p className="notice bad" role="alert">{t("stSttRights")}</p> : (
        <div className="stack" style={{ gap: 10 }}>
          <div className="form-grid">
            <label>{t("stSttRecording")}
              <input type="file" accept=".wav,.mp3,.m4a,.flac,.ogg,audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} style={{ minHeight: 48 }} />
            </label>
            <label>{t("stSttLanguage")}
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                <option value="">{t("stSttItemLanguage")}</option>
                {LANGS.map((l) => <option key={l.code} value={l.code} lang={l.code}>{l.name} ({l.code})</option>)}
              </select>
            </label>
          </div>
          <div className="row">
            <button type="button" className="btn" disabled={busy || !file} onClick={() => start(true)}>{t("stSttUpload")}</button>
            {hasRecording && <button type="button" className="btn secondary" disabled={busy} onClick={() => start(false)}>{t("stSttStored")}</button>}
          </div>
          {view}
          {jobId && (status === "queued" || status === "running" || !status) && <p className="muted" role="status">{t("stSttRunning", { id: jobId })}</p>}
          {status === "done" && <p className="notice" role="status">{t("stSttDone", { n: Number((job?.result as Json | undefined)?.segments ?? 0) })}</p>}
          {status === "failed" && <p className="notice bad" role="alert">{t("stSttFailed", { error: String(job?.error ?? "") })}</p>}
        </div>
      )}
    </Section>
  );
}

const passageWhere = (t: T, p: PublishedPassage) =>
  p.page_sequence != null ? t("stPageN", { n: p.page_sequence }) : p.start_ms != null ? t("stAtTime", { t: formatMs(p.start_ms) }) : t("stPassageN", { n: p.id });
const excerpt = (s: string, n = 90) => (s.length > n ? `${s.slice(0, n).trimEnd()}…` : s);

function ConstitutionSection({ passages, links, reload }: { passages: PublishedPassage[]; links: ConstitutionLink[]; reload: () => void }) {
  const { token, can } = useStaff();
  const { t } = useSession();
  const articles = useApi<StaffArticle[]>("/api/staff/constitution/articles", token);
  const { run, busy, view } = useAction();
  const [link, setLink] = useState({ passage_id: "", article_number: "", note: "" });
  const [art, setArt] = useState({ number: "", en: "", hi: "", mr: "", part: "" });
  const curator = can("curator");
  const byId = new Map(passages.map((p) => [p.id, p]));
  const addLink = (e: FormEvent) => {
    e.preventDefault();
    void run((tk) => api.post("/api/staff/constitution/links", { passage_id: Number(link.passage_id), article_number: link.article_number, note: link.note.trim() || undefined }, tk),
      t("stLinked", { n: link.article_number }), () => { setLink({ passage_id: "", article_number: "", note: "" }); reload(); });
  };
  const addArticle = (e: FormEvent) => {
    e.preventDefault();
    const titles: Record<string, string> = { en: art.en.trim() };
    if (art.hi.trim()) titles.hi = art.hi.trim();
    if (art.mr.trim()) titles.mr = art.mr.trim();
    const number = art.number.trim();
    void run((tk) => api.post("/api/staff/constitution/articles", { number, titles, part: art.part.trim() || undefined }, tk),
      t("stArticleAdded", { n: number }), () => { setArt({ number: "", en: "", hi: "", mr: "", part: "" }); setLink((l) => ({ ...l, article_number: number })); articles.reload(); });
  };
  return (
    <Section title={t("stConstLinks")}>
      <p className="muted">{t("stConstNote")}{!curator && <> {t("stConstCuratorOnly")}</>}</p>
      {view}
      {links.length === 0 ? <p className="muted">{t("stNoLinks")}</p> : (
        <table className="grid" aria-label={t("stConstLinksTable")} style={{ marginBottom: 16 }}>
          <thead><tr><th>{t("stArticle")}</th><th>{t("stPassage")}</th><th>{t("stNote")}</th><th>{t("stAdded")}</th><th><span className="visually-hidden">{t("stActions")}</span></th></tr></thead>
          <tbody>
            {links.map((l) => {
              const p = byId.get(l.passage_id);
              return (
                <tr key={l.id}>
                  <td>{t("stArticleTitle", { n: l.article_number, title: l.article_title })}</td>
                  <td>{p ? `${passageWhere(t, p)}: ${excerpt(p.text)}` : t("stPassageN", { n: l.passage_id })}</td>
                  <td>{l.note ?? ""}</td>
                  <td>{l.created_by}, {String(l.created_at).slice(0, 10)}</td>
                  <td>{curator && <ReasonAction label={t("stRemove")} confirmLabel={t("stConfirmRemoval")} busy={busy} onConfirm={(reason) => run((tk) => api.post(`/api/staff/constitution/links/${l.id}/remove`, { reason }, tk), t("stLinkRemoved", { n: l.article_number }), reload)} />}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {curator && (
        <>
          <form className="stack" onSubmit={addLink} style={{ gap: 10 }}>
            <h3 style={{ margin: 0 }}>{t("stAddLink")}</h3>
            <div className="form-grid">
              <label>{t("stPassage")}
                <select value={link.passage_id} onChange={(e) => setLink({ ...link, passage_id: e.target.value })} required>
                  <option value="">{t("stChoose")}</option>
                  {passages.map((p) => <option key={p.id} value={p.id}>{passageWhere(t, p)}: {excerpt(p.text, 70)}</option>)}
                </select>
              </label>
              <label>{t("stArticle")}
                <select value={link.article_number} onChange={(e) => setLink({ ...link, article_number: e.target.value })} required>
                  <option value="">{articles.loading ? t("loading") : t("stChoose")}</option>
                  {(articles.data ?? []).map((a) => <option key={a.number} value={a.number}>{t("stArticleTitle", { n: a.number, title: a.titles.en ?? Object.values(a.titles)[0] ?? "" })}</option>)}
                </select>
              </label>
              <label>{t("stNoteVisitors")}<input type="text" value={link.note} onChange={(e) => setLink({ ...link, note: e.target.value })} autoComplete="off" /></label>
            </div>
            <div className="row"><button type="submit" className="btn" disabled={busy}>{t("stAddLink")}</button></div>
          </form>
          <details style={{ marginTop: 14 }}>
            <summary style={{ cursor: "pointer", padding: "10px 0", fontWeight: 500 }}>{t("stArticleMissing")}</summary>
            <form className="stack" onSubmit={addArticle} style={{ gap: 10 }}>
              <div className="form-grid">
                <label>{t("stArticleNumber")}<input type="text" value={art.number} onChange={(e) => setArt({ ...art, number: e.target.value })} required placeholder={t("stArticleNumberEg")} autoComplete="off" /></label>
                <label>{t("stEnTitle")}<input type="text" lang="en" value={art.en} onChange={(e) => setArt({ ...art, en: e.target.value })} required autoComplete="off" /></label>
                <label>{t("stHiTitle")}<input type="text" lang="hi" value={art.hi} onChange={(e) => setArt({ ...art, hi: e.target.value })} autoComplete="off" /></label>
                <label>{t("stMrTitle")}<input type="text" lang="mr" value={art.mr} onChange={(e) => setArt({ ...art, mr: e.target.value })} autoComplete="off" /></label>
                <label>{t("stPart")}<input type="text" value={art.part} onChange={(e) => setArt({ ...art, part: e.target.value })} placeholder={t("stPartEg")} autoComplete="off" /></label>
              </div>
              <div className="row"><button type="submit" className="btn secondary" disabled={busy}>{t("stAddArticle")}</button></div>
            </form>
          </details>
        </>
      )}
    </Section>
  );
}

export function StaffItem() {
  const { id = "" } = useParams();
  const { token, can } = useStaff();
  const { t } = useSession();
  const item = useApi<Json>(`/api/staff/items/${id}`, token);
  const { run, busy, view } = useAction();
  const [withdrawReason, setWithdrawReason] = useState("");
  const [restoreReason, setRestoreReason] = useState("");
  if (item.error) return <p className="notice bad" role="alert">{errText(item.error)}</p>;
  if (!item.data) return <Loading center />;
  const d = item.data;
  const archivist = can("archivist");
  const rights = d.rights as Json;
  const externalAllowed = rights.external_processing === "allowed" && d.access_level !== "restricted";
  const segments = (d.segments ?? []) as StaffSegment[];
  const passages = (d.published_passages ?? []) as PublishedPassage[];
  return (
    <>
      <h1>{String(d.title)}</h1>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="chip">{t("stChipState", { v: String(d.state) })}</span>
        <span className="chip">{t("stChipVersion", { v: String(d.version) })}</span>
        <span className="chip">{t("stChipAccess", { v: String(d.access_level) })}</span>
        {Boolean(d.is_fixture) && <span className="chip fixture">{t("stSyntheticFixture")}</span>}
        {d.state === "published" && <Link to={`/item/${String(d.id)}`}>{t("stOpenVisitor")}</Link>}
      </div>
      {view}
      <Section title={t("stPublication")} actions={archivist && (
        <>
          <button type="button" className="btn small" disabled={busy || !d.ready || d.state === "published"} onClick={() => run((tk) => postDetailed(`/api/staff/items/${id}/publish`, {}, tk), t("stPublishQueued"), item.reload)}>{t("stPublish")}</button>
        </>
      )}>
        {d.ready ? <p className="status ok">{t("stGatesPassed")}</p> : (
          <ul>{(d.problems as string[]).map((p) => <li key={p}>{p}</li>)}</ul>
        )}
        {!archivist && <p className="muted">{t("stArchivistOnly")}</p>}
        {archivist && d.state === "published" && (
          <form className="row" onSubmit={(e) => { e.preventDefault(); void run((tk) => api.post(`/api/staff/items/${id}/withdraw`, { reason: withdrawReason }, tk), t("stWithdrawn"), () => { setWithdrawReason(""); item.reload(); }); }}>
            <label style={{ flex: 1 }}>{t("stWithdrawReason")}<input type="text" value={withdrawReason} onChange={(e) => setWithdrawReason(e.target.value)} minLength={3} required /></label>
            <button type="submit" className="btn danger" disabled={busy}>{t("stWithdraw")}</button>
          </form>
        )}
        {archivist && d.state === "withdrawn" && (
          <form className="row" onSubmit={(e) => { e.preventDefault(); void run((tk) => api.post(`/api/staff/items/${id}/restore`, { reason: restoreReason }, tk), t("stRestored"), () => { setRestoreReason(""); item.reload(); }); }}>
            <label style={{ flex: 1 }}>{t("stRestoreReason")}<input type="text" value={restoreReason} onChange={(e) => setRestoreReason(e.target.value)} minLength={3} required /></label>
            <button type="submit" className="btn" disabled={busy}>{t("stRestore")}</button>
          </form>
        )}
      </Section>
      <Section title={t("rights")} actions={
        <span className={`chip ${rights.display_permission === "allowed" ? "verified" : ""}`}>
          {rights.display_permission === "allowed" ? `✓ ${t("stClearanceAllowed")}` : t("stClearanceRestricted")}
        </span>
      }>
        <div className="rights-provenance-card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{t("stRightsCardTitle")}</strong>
            <span className="chip">{String(rights.source_key)}</span>
          </div>
          <dl className="facts">
            <dt>{t("stRightsHolder")}</dt><dd>{String(rights.rights_holder)}</dd>
            <dt>{t("stDisplay")}</dt><dd><span className={`chip ${rights.display_permission === "allowed" ? "verified" : ""}`}>{String(rights.display_permission)}</span></dd>
            <dt>{t("stTraining")}</dt><dd><span className="chip">{String(rights.training_permission)}</span></dd>
            <dt>{t("stExternalProcessing")}</dt><dd><span className="chip">{String(rights.external_processing)}</span></dd>
            <dt>{t("stEvidence")}</dt><dd style={{ fontStyle: "italic" }}>"{String(rights.evidence)}"</dd>
          </dl>
        </div>
      </Section>
      <MetadataSection id={id} metadata={d.metadata as ItemMetadata | undefined} version={d.metadata_version} reload={item.reload} />
      {Boolean(d.photo) && <PhotoSection id={id} photo={d.photo as StaffPhoto} reload={item.reload} />}
      {(d.pages as Json[]).length > 0 && (
        <Section title={t("stPages")}>
          <table className="grid" aria-label={t("stPagesOfItem")}>
            <thead><tr><th>{t("stPage")}</th><th>{t("stStatus")}</th><th>{t("stRoute")}</th><th>{t("stGate")}</th><th>{t("stReview")}</th><th>{t("stQuoteVerifiedCol")}</th><th><span className="visually-hidden">{t("stActions")}</span></th></tr></thead>
            <tbody>
              {(d.pages as Json[]).map((p) => (
                <tr key={String(p.id)}>
                  <td>{String(p.label ?? p.sequence)}</td><td>{String(p.status)}</td><td>{String(p.ocr_route)}</td>
                  <td>{p.gate_passed === null ? "" : p.gate_passed ? t("stPassed") : t("stFailed")}</td><td>{String(p.review_mode ?? "")}</td>
                  <td>{p.quote_verified ? t("stYes") : ""}</td>
                  <td><Link to={`/staff/pages/${String(p.id)}`}>{t("openItem")}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
      {(d.item_type === "audio" || d.item_type === "video") && (
        <SpeechToTextSection id={id} reload={item.reload}
          allowed={externalAllowed}
          hasRecording={(d.files as Json[]).some((f) => f.role === "preservation_master" && !f.deleted && /^(audio|video)\//.test(String(f.format)))} />
      )}
      {segments.length > 0 && <SegmentsSection segments={segments} reload={item.reload} />}
      <SummariesSection id={id} derivatives={(d.derivatives ?? []) as StaffDerivative[]} externalAllowed={externalAllowed} reload={item.reload} />
      {passages.length > 0 && <ConstitutionSection passages={passages} links={(d.constitution_links ?? []) as ConstitutionLink[]} reload={item.reload} />}
      <Section title={t("stFiles")}>
        <table className="grid" aria-label={t("stFilesOfItem")}>
          <thead><tr><th>#</th><th>{t("stRole")}</th><th>{t("stKind")}</th><th>{t("stFormat")}</th><th>{t("stBytes")}</th><th>{"SHA-256"}</th><th>{t("stGenerator")}</th></tr></thead>
          <tbody>
            {(d.files as Json[]).map((f) => (
              <tr key={String(f.id)} style={{ opacity: f.deleted ? 0.5 : 1 }}>
                <td>{String(f.id)}</td><td>{String(f.role)}</td><td>{String(f.kind)}</td><td>{String(f.format)}</td><td>{String(f.bytes)}</td><td><code>{String(f.sha256).slice(0, 16)}</code></td><td>{String(f.generator ?? "")}{f.deleted ? ` (${t("stRemoved")})` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- rights register

// Every RightsBody field: the server replaces the whole entry, so a field missing here is cleared on save.
// is_fixture is carried through unchanged (shown, not editable).
const EMPTY_RIGHTS = {
  source_key: "", title: "", source_institution: "", rights_holder: "", basis_for_use: "", display_permission: "unknown",
  training_permission: "unknown", training_basis: "", external_processing: "unknown", evidence: "", attribution: "",
  date_checked: new Date().toISOString().slice(0, 10), checked_by: "",
  source_url: "", edition: "", volume: "", pages: "", discovery_only: false, is_fixture: false, notes: "",
};

const PERMISSION_LABELS: Record<"display_permission" | "training_permission" | "external_processing", Key> = {
  display_permission: "stDisplayPermission",
  training_permission: "stTrainingPermission",
  external_processing: "stExternalProcessing",
};

interface RightsSaved { effects?: { withdrawn_items?: number[]; flagged?: { datasets?: number[]; models?: number[] } } }

export function StaffRights() {
  const { token, can } = useStaff();
  const { t } = useSession();
  const rights = useApi<Json[]>("/api/staff/rights", token);
  const { run, busy, view } = useAction();
  const [form, setForm] = useState<typeof EMPTY_RIGHTS>(EMPTY_RIGHTS);
  const set = (k: keyof typeof EMPTY_RIGHTS) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const archivist = can("archivist");
  const save = (e: FormEvent) => {
    e.preventDefault();
    // Moving display or training away from "allowed" withdraws items / flags datasets on the server: confirm first.
    const before = (rights.data ?? []).find((r) => r.source_key === form.source_key);
    if (rightsDowngrades(before, form).length && !window.confirm(t("stRightsCascadeConfirm"))) return;
    void run((tk) => api.post("/api/staff/rights", rightsBody(form), tk) as Promise<RightsSaved>, (r) => {
      const withdrawn = r.effects?.withdrawn_items ?? [];
      const flagged = r.effects?.flagged;
      return [
        t("stRightsSaved"),
        r.effects?.withdrawn_items ? t("stRightsWithdrawnItems", { ids: withdrawn.length ? withdrawn.map((i) => `#${i}`).join(", ") : t("stNone") }) : "",
        flagged ? t("stRightsFlagged", { datasets: (flagged.datasets ?? []).join(", ") || t("stNone"), models: (flagged.models ?? []).join(", ") || t("stNone") }) : "",
      ].filter(Boolean).join(" ");
    }, rights.reload);
  };
  const perm = (k: keyof typeof PERMISSION_LABELS) => (
    <label>{t(PERMISSION_LABELS[k])}
      <select value={form[k]} onChange={set(k)}>
        {PERMISSIONS.map((v) => <option key={v} value={v}>{t(`stPerm_${v}`)}</option>)}
      </select>
    </label>
  );
  return (
    <>
      <h1>{t("stNavRights")}</h1>
      <p className="muted" style={{ maxWidth: "80ch" }}>{t("stRightsLead")}</p>
      {rights.loading && <Loading center />}
      {rights.error && <p className="notice bad" role="alert">{errText(rights.error)}</p>}
      {rights.data && (
        <table className="grid" aria-label={t("stRightsTable")} style={{ marginBottom: 20 }}>
          <thead><tr><th>{t("stKey")}</th><th>{t("stTitle")}</th><th>{t("stHolder")}</th><th>{t("stDisplay")}</th><th>{t("stTraining")}</th><th>{t("stExternalProcessing")}</th><th>{t("stDiscoveryOnly")}</th>{archivist && <th><span className="visually-hidden">{t("stActions")}</span></th>}</tr></thead>
          <tbody>
            {rights.data.map((r) => (
              <tr key={String(r.id)}>
                <td>{String(r.source_key)}{r.is_fixture ? ` (${t("stFixture")})` : ""}</td><td>{String(r.title)}</td><td>{String(r.rights_holder)}</td>
                <td>{String(r.display_permission)}</td><td>{String(r.training_permission)}</td><td>{String(r.external_processing)}</td><td>{r.discovery_only ? t("stYes") : ""}</td>
                {archivist && <td><button type="button" className="btn quiet small" onClick={() => setForm(Object.fromEntries(Object.keys(EMPTY_RIGHTS).map((k) => [k, r[k] ?? (EMPTY_RIGHTS as Json)[k]])) as typeof EMPTY_RIGHTS)}>{t("stEdit")}</button></td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!archivist ? <p className="muted">{t("stArchivistOnly")}</p> : (
        <form className="sheet stack" onSubmit={save}>
          <h2 style={{ fontSize: "var(--step-1)" }}>{t("stAddUpdateEntry")}</h2>
          {form.is_fixture && <p><span className="chip fixture">{t("stSyntheticFixture")}</span></p>}
          <div className="form-grid">
            <label>{t("stSourceKey")}<input type="text" value={form.source_key} onChange={set("source_key")} required /></label>
            <label>{t("stTitle")}<input type="text" value={form.title} onChange={set("title")} required /></label>
            <label>{t("stInstitution")}<input type="text" value={form.source_institution} onChange={set("source_institution")} required /></label>
            <label>{t("stRightsHolder")}<input type="text" value={form.rights_holder} onChange={set("rights_holder")} required /></label>
            <label>{t("stBasis")}<input type="text" value={form.basis_for_use} onChange={set("basis_for_use")} required /></label>
            {perm("display_permission")}
            {perm("training_permission")}
            <label>{t("stTrainingBasis")}<input type="text" value={form.training_basis ?? ""} onChange={set("training_basis")} /></label>
            {perm("external_processing")}
            <label>{t("stEvidenceLong")}<input type="text" value={form.evidence} onChange={set("evidence")} required /></label>
            <label>{t("stAttribution")}<input type="text" value={form.attribution} onChange={set("attribution")} required /></label>
            <label>{t("stDateChecked")}<input type="date" value={form.date_checked} onChange={set("date_checked")} required /></label>
            <label>{t("stCheckedBy")}<input type="text" value={form.checked_by} onChange={set("checked_by")} required /></label>
            <label>{t("stSourceUrl")}<input type="text" value={form.source_url ?? ""} onChange={set("source_url")} /></label>
            <label>{t("stEdition")}<input type="text" value={form.edition ?? ""} onChange={set("edition")} /></label>
            <label>{t("stVolume")}<input type="text" value={form.volume ?? ""} onChange={set("volume")} /></label>
            <label>{t("stPages")}<input type="text" value={form.pages ?? ""} onChange={set("pages")} /></label>
            <label>{t("stRightsNotes")}<input type="text" value={form.notes ?? ""} onChange={set("notes")} /></label>
            <label className="row" style={{ fontWeight: 400, flexDirection: "row" }}>
              <input type="checkbox" checked={Boolean(form.discovery_only)} onChange={(e) => setForm({ ...form, discovery_only: e.target.checked })} style={{ width: 24, height: 24 }} />
              {t("stDiscoveryOnly")}
            </label>
          </div>
          <div className="row">
            <button type="submit" className="btn" disabled={busy}>{t("stSaveEntry")}</button>
            <button type="button" className="btn secondary" onClick={() => setForm(EMPTY_RIGHTS)}>{t("stClear")}</button>
          </div>
          {view}
        </form>
      )}
    </>
  );
}

// ---------------------------------------------------------------- jobs and audit

export function StaffJobs() {
  const { token } = useStaff();
  const { t } = useSession();
  const jobs = useApi<Json[]>("/api/staff/jobs", token);
  return (
    <>
      <div className="row"><h1>{t("stNavJobs")}</h1><span className="spacer" /><button type="button" className="btn secondary small" onClick={jobs.reload}>{t("stRefresh")}</button></div>
      {jobs.loading && <Loading center />}
      {jobs.error && <p className="notice bad" role="alert">{errText(jobs.error)}</p>}
      {jobs.data && (
        <table className="grid" aria-label={t("stRecentJobs")}>
          <thead><tr><th>#</th><th>{t("stKind")}</th><th>{t("stStatus")}</th><th>{t("stAttempts")}</th><th>{t("stPayload")}</th><th>{t("stError")}</th><th>{t("stUpdated")}</th></tr></thead>
          <tbody>
            {jobs.data.map((j) => (
              <tr key={String(j.id)}><td>{String(j.id)}</td><td>{String(j.kind)}</td><td>{String(j.status)}</td><td>{String(j.attempts)}</td><td><code>{JSON.stringify(j.payload)}</code></td><td>{String(j.error ?? "")}</td><td>{String(j.updated_at).slice(0, 19)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

export function StaffAudit() {
  const { token, can } = useStaff();
  const { t } = useSession();
  const audit = useApi<Json[]>("/api/staff/audit?limit=300", token);
  const { run, busy, view } = useAction();
  const [chain, setChain] = useState<string | null>(null);
  return (
    <>
      <div className="row">
        <h1>{t("stNavAudit")}</h1>
        <span className="spacer" />
        {can("admin") && (
          <button type="button" className="btn secondary small" disabled={busy} onClick={() => run(async (tk) => {
            const r = await api.get<{ chain_ok: boolean; events_checked: number }>("/api/staff/audit/verify", tk);
            setChain(t(r.chain_ok ? "stChainOk" : "stChainBroken", { n: r.events_checked }));
          }, t("stVerified"))}>{t("stVerifyChain")}</button>
        )}
      </div>
      {view}
      {chain && <p className="notice">{chain}</p>}
      <p className="muted">{t("stAuditNote")}</p>
      {audit.loading && <Loading center />}
      {audit.error && <p className="notice bad" role="alert">{errText(audit.error)}</p>}
      {audit.data && (
        <table className="grid" aria-label={t("stAuditEvents")}>
          <thead><tr><th>#</th><th>{t("stWhen")}</th><th>{t("stActor")}</th><th>{t("stAction")}</th><th>{t("stEntity")}</th><th>{t("stDetail")}</th><th>{t("stRowHash")}</th></tr></thead>
          <tbody>
            {audit.data.map((a) => (
              <tr key={String(a.id)}><td>{String(a.id)}</td><td>{String(a.at).slice(0, 19)}</td><td>{String(a.actor)}</td><td>{String(a.action)}</td><td>{String(a.entity)} {String(a.entity_id)}</td><td><code style={{ fontSize: 12 }}>{JSON.stringify(a.detail)}</code></td><td><code>{String(a.row_hash)}</code></td></tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
