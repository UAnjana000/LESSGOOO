// Archivist workspace. English only for now (staff tool); visitor UI carries EN/HI/MR.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { formatMs, useApi } from "../hooks";
import { StaffAuthProvider, useAuthedObjectUrl, useStaff } from "./auth";

type Json = Record<string, unknown>;

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    try {
      const parsed = JSON.parse(e.message);
      if (Array.isArray(parsed)) return parsed.map((p) => (typeof p === "string" ? p : p.msg ?? JSON.stringify(p))).join("; ");
      if (parsed?.problems) return `${parsed.message} ${parsed.problems.join("; ")}`;
    } catch {
      /* plain text */
    }
    return e.message;
  }
  return String(e);
}

function useAction() {
  const { token } = useStaff();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: (token: string) => Promise<unknown>, okText: string, after?: () => void) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn(token!);
      setMsg({ ok: true, text: okText });
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

export function StaffRoot() {
  return (
    <StaffAuthProvider>
      <Outlet />
    </StaffAuthProvider>
  );
}

export function StaffLogin() {
  const { login, token } = useStaff();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (token) return <Navigate to="/staff" replace />;
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
  return (
    <div className="staff">
      <div className="page" style={{ maxWidth: 460 }}>
        <h1>Archivist workspace</h1>
        <p className="muted">Sign in with a staff account. Local development accounts are created by <code>python -m archive.cli bootstrap</code> from the credentials in <code>.env</code>.</p>
        <form className="stack" onSubmit={submit}>
          <label>Email<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
          {error && <p className="notice bad" role="alert">{error}</p>}
          <button type="submit" className="btn">Sign in</button>
        </form>
      </div>
    </div>
  );
}

export function StaffLayout() {
  const { token, user, logout } = useStaff();
  if (!token) return <Navigate to="/staff/login" replace />;
  const links = [
    ["/staff", "Dashboard"],
    ["/staff/intake", "Intake"],
    ["/staff/review", "Review queue"],
    ["/staff/items", "Items"],
    ["/staff/rights", "Rights register"],
    ["/staff/jobs", "Jobs"],
    ["/staff/audit", "Audit log"],
  ];
  return (
    <div className="staff">
      <header className="staff-top">
        <strong>Archivist workspace</strong>
        <nav aria-label="Staff">
          {links.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/staff"}>{label}</NavLink>
          ))}
        </nav>
        <div className="who">
          <span>{user?.email} ({user?.roles.join(", ")})</span>
          <button type="button" className="btn secondary small" onClick={logout}>Sign out</button>
        </div>
      </header>
      <div className="page">
        <Outlet />
      </div>
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

// ---------------------------------------------------------------- dashboard

export function StaffDashboard() {
  const { token } = useStaff();
  const stats = useApi<Json>("/api/staff/stats", token);
  const status = useApi<Json>("/api/staff/settings/status", token);
  const queue = useApi<Json>("/api/staff/review/queue", token);
  const q = queue.data as Record<string, unknown[]> | null;
  return (
    <>
      <h1>Dashboard</h1>
      <div className="form-grid">
        <Section title="Waiting for review">
          {q ? (
            <dl className="facts">
              <dt>Pages needing full review or transcription</dt><dd>{q.pages.length}</dd>
              <dt>Batches with a sample to check</dt><dd>{q.batches.length}</dd>
              <dt>Transcript segments</dt><dd>{q.segments.length}</dd>
              <dt>Photo captions</dt><dd>{q.photos.length}</dd>
              <dt>Translations</dt><dd>{q.translations.length}</dd>
              <dt>Summaries and narration</dt><dd>{q.derivatives.length}</dd>
              <dt>Ready to publish</dt><dd>{q.ready_to_publish.length}</dd>
            </dl>
          ) : <p className="muted">Loading…</p>}
          <p style={{ marginTop: 12 }}><Link to="/staff/review">Open the review queue</Link></p>
        </Section>
        <Section title="Integrations on this installation">
          {status.data ? (
            <dl className="facts">
              <dt>Environment</dt><dd>{String(status.data.environment)}</dd>
              <dt>Sarvam (OCR fallback, translation, speech)</dt><dd className={`status ${status.data.sarvam_configured ? "ok" : "bad"}`}>{status.data.sarvam_configured ? "Configured" : "Not configured: failed pages stay pending"}</dd>
              <dt>Answer model</dt><dd className={`status ${status.data.llm_configured ? "ok" : "bad"}`}>{status.data.llm_configured ? String(status.data.llm_model) : "Not configured: Ask shows extractive passages"}</dd>
              <dt>Trace sink</dt><dd>{String(status.data.trace_backend)}</dd>
              <dt>OCR gate</dt><dd>{String(status.data.gate_config).split(/[\\/]/).pop()}</dd>
              <dt>Sufficiency threshold</dt><dd>{String(status.data.sufficiency_threshold)} ({String(status.data.sufficiency_threshold_version)})</dd>
            </dl>
          ) : <p className="muted">Loading…</p>}
        </Section>
      </div>
      {stats.data && (
        <Section title="Archive state">
          <div className="form-grid">
            <div><h3>Items by state</h3><Counts data={stats.data.items_by_state as Json} /></div>
            <div><h3>Pages by status</h3><Counts data={stats.data.pages_by_status as Json} /></div>
            <div><h3>Pages by OCR route</h3><Counts data={stats.data.pages_by_route as Json} /></div>
          </div>
          <h3 style={{ marginTop: 16 }}>Ask outcomes</h3>
          <table className="grid" aria-label="Ask outcomes">
            <thead><tr><th>Outcome</th><th>Count</th><th>Tokens in</th><th>Tokens out</th><th>Cost (USD)</th><th>Mean latency (ms)</th></tr></thead>
            <tbody>
              {(stats.data.answers as Json[]).map((a) => (
                <tr key={String(a.outcome)}><td>{String(a.outcome)}</td><td>{String(a.count)}</td><td>{String(a.tokens_in)}</td><td>{String(a.tokens_out)}</td><td>{Number(a.cost_usd).toFixed(4)}</td><td>{Math.round(Number(a.avg_latency_ms))}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted">Answer cache hits: {String(stats.data.cache_hits)}</p>
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

export function StaffIntake() {
  const { token } = useStaff();
  const rights = useApi<Json[]>("/api/staff/rights", token);
  const { run, busy, view } = useAction();
  const [result, setResult] = useState<Json | null>(null);
  const [form, setForm] = useState({
    title: "", item_type: "printed_scan", collection: "writings", doc_class: "printed", languages: "en",
    rights_source_key: "", date_text: "", creator: "", device: "capture-station-1", operator: "", access_level: "public",
  });
  const [files, setFiles] = useState<FileList | null>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!files?.length) return;
    const meta = {
      title: form.title, item_type: form.item_type, collection: form.collection, doc_class: form.doc_class,
      languages: form.languages.split(",").map((s) => s.trim()).filter(Boolean), rights_source_key: form.rights_source_key,
      date_text: form.date_text || undefined, creator: form.creator || undefined, access_level: form.access_level,
      capture: { device: form.device, operator: form.operator, date: new Date().toISOString().slice(0, 10) },
    };
    const fd = new FormData();
    fd.set("metadata", JSON.stringify(meta));
    for (const f of Array.from(files)) fd.append("files", f);
    void run(async (tk) => setResult(await api.post<Json>("/api/staff/intake", fd, tk)), "Stored. Ingestion job queued.");
  };

  const selectable = (rights.data ?? []).filter((r) => !r.discovery_only);
  return (
    <>
      <h1>Intake</h1>
      <p className="muted" style={{ maxWidth: "80ch" }}>
        Upload captured pages, a born-digital PDF, a photograph, or a recording. Each file is hashed (SHA-256), checked for duplicates, and stored read-only as the preservation master before any processing. Items must reference a rights register entry; discovery-only sources (such as NDLI links) cannot be ingested.
      </p>
      <form className="sheet stack" onSubmit={submit}>
        <div className="form-grid">
          <label>Title<input type="text" value={form.title} onChange={set("title")} required /></label>
          <label>Rights register entry
            <select value={form.rights_source_key} onChange={set("rights_source_key")} required>
              <option value="">Choose…</option>
              {selectable.map((r) => (
                <option key={String(r.source_key)} value={String(r.source_key)}>{String(r.source_key)} (display: {String(r.display_permission)})</option>
              ))}
            </select>
          </label>
          <label>Item type
            <select value={form.item_type} onChange={set("item_type")}>
              {["text", "printed_scan", "manuscript", "photograph", "audio", "video"].map((v) => <option key={v}>{v}</option>)}
            </select>
          </label>
          <label>Document class (sets the OCR route)
            <select value={form.doc_class} onChange={set("doc_class")}>
              {["born_digital", "printed", "handwritten", "photograph", "audio_video"].map((v) => <option key={v}>{v}</option>)}
            </select>
          </label>
          <label>Collection
            <select value={form.collection} onChange={set("collection")}>
              {["writings", "speeches", "debates", "manuscripts", "photographs", "audio_video"].map((v) => <option key={v}>{v}</option>)}
            </select>
          </label>
          <label>Access
            <select value={form.access_level} onChange={set("access_level")}>
              <option value="public">public (may be cached on kiosks)</option>
              <option value="public_online_only">public_online_only (never cached)</option>
              <option value="restricted">restricted (never shown to visitors)</option>
            </select>
          </label>
          <label>Languages (comma separated: en, hi, mr)<input type="text" value={form.languages} onChange={set("languages")} /></label>
          <label>Date as written<input type="text" value={form.date_text} onChange={set("date_text")} /></label>
          <label>Creator<input type="text" value={form.creator} onChange={set("creator")} /></label>
          <label>Capture device<input type="text" value={form.device} onChange={set("device")} /></label>
          <label>Operator<input type="text" value={form.operator} onChange={set("operator")} required /></label>
          <label>Files<input type="file" multiple onChange={(e) => setFiles(e.target.files)} required style={{ minHeight: 48 }} /></label>
        </div>
        <div className="row"><button type="submit" className="btn" disabled={busy}>{busy ? "Uploading…" : "Store and queue ingestion"}</button></div>
        {view}
      </form>
      {result && (
        <Section title="Intake result">
          <p>Item <Link to={`/staff/items/${String(result.item_id)}`}>#{String(result.item_id)}</Link>, {String(result.pages)} pages, job {String(result.job_id ?? "not queued")}.</p>
          <table className="grid" aria-label="Stored files">
            <thead><tr><th>File</th><th>Status</th><th>SHA-256</th><th>Note</th></tr></thead>
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
  const { token } = useStaff();
  const q = useApi<Record<string, Json[]>>("/api/staff/review/queue", token);
  const { run, busy, view } = useAction();
  if (!q.data) return <p className="muted">Loading…</p>;
  const d = q.data;
  return (
    <>
      <h1>Review queue</h1>
      {view}
      <Section title={`Pages (${d.pages.length})`}>
        {d.pages.length === 0 ? <p className="muted">Nothing waiting.</p> : (
          <table className="grid" aria-label="Pages waiting for review">
            <thead><tr><th>Item</th><th>Page</th><th>Status</th><th>Route</th><th>Priority</th><th /></tr></thead>
            <tbody>
              {d.pages.map((p) => (
                <tr key={String(p.id)}>
                  <td>{String(p.item_title)}</td><td>{String(p.label ?? p.sequence)}</td><td>{String(p.status)}{p.sarvam_last_error ? ` (${String(p.sarvam_last_error)})` : ""}</td>
                  <td>{String(p.ocr_route)}</td><td>{String(p.priority)}</td>
                  <td><Link className="btn small" to={`/staff/pages/${String(p.id)}`}>Review</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      <Section title={`Batches (${d.batches.length})`}>
        {d.batches.map((b) => (
          <p key={String(b.id)}>Batch {String(b.id)} (item {String(b.item_id)}, {String(b.pages)} pages, {(b.sample as number[]).length} to sample) <Link to={`/staff/batches/${String(b.id)}`}>Check sample</Link></p>
        ))}
        {d.batches.length === 0 && <p className="muted">Nothing waiting.</p>}
      </Section>
      <Section title={`Transcript segments (${d.segments.length})`}>
        {d.segments.map((s) => (
          <div key={String(s.id)} className="row" style={{ marginBottom: 8 }}>
            <span className="chip">{formatMs(Number(s.start_ms))}</span>
            <span style={{ flex: 1 }}>{String(s.text)}</span>
            <button type="button" className="btn small" disabled={busy} onClick={() => run((tk) => api.post(`/api/staff/segments/${String(s.id)}/review`, { action: "approve" }, tk), `Segment ${String(s.id)} approved.`, q.reload)}>Approve</button>
          </div>
        ))}
        {d.segments.length === 0 && <p className="muted">Nothing waiting.</p>}
      </Section>
      <Section title={`Photo captions (${d.photos.length})`}>
        {d.photos.map((p) => (
          <div key={String(p.item_id)} className="row" style={{ marginBottom: 8 }}>
            <span style={{ flex: 1 }}>{String(p.caption)}</span>
            <button type="button" className="btn small" disabled={busy} onClick={() => run((tk) => api.post(`/api/staff/photos/${String(p.item_id)}/review`, { action: "approve" }, tk), "Caption approved.", q.reload)}>Approve</button>
          </div>
        ))}
        {d.photos.length === 0 && <p className="muted">Nothing waiting.</p>}
      </Section>
      <Section title={`Translations (${d.translations.length})`}>
        {d.translations.map((t) => (
          <div key={String(t.id)} className="stack" style={{ marginBottom: 12 }}>
            <span className="chip">{String(t.target_language)} ({String(t.method)}), source passage {String(t.source_passage_id)}</span>
            <p lang={String(t.target_language)}>{String(t.text)}</p>
            <div className="row">
              <button type="button" className="btn small" disabled={busy} onClick={() => run((tk) => api.post(`/api/staff/translations/${String(t.id)}/review`, { action: "approve" }, tk), "Translation approved.", q.reload)}>Approve as reviewer</button>
            </div>
          </div>
        ))}
        {d.translations.length === 0 && <p className="muted">Nothing waiting.</p>}
      </Section>
      <Section title={`Ready to publish (${d.ready_to_publish.length})`}>
        {d.ready_to_publish.map((i) => (
          <div key={String(i.id)} className="row" style={{ marginBottom: 8 }}>
            <Link to={`/staff/items/${String(i.id)}`} style={{ flex: 1 }}>{String(i.title)}</Link>
            <button type="button" className="btn small" disabled={busy} onClick={() => run((tk) => api.post(`/api/staff/items/${String(i.id)}/publish`, {}, tk), "Publication queued. The worker switches the index atomically.", q.reload)}>Publish</button>
          </div>
        ))}
        {d.ready_to_publish.length === 0 && <p className="muted">Nothing waiting.</p>}
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- page review

export function StaffPage() {
  const { id } = useParams();
  const { token } = useStaff();
  const page = useApi<Json>(`/api/staff/pages/${id}`, token);
  const { run, busy, view } = useAction();
  const [text, setText] = useState("");
  const [compared, setCompared] = useState(false);
  const d = page.data;
  const img = useAuthedObjectUrl(d?.master_file_id ? `/api/staff/files/${String(d.master_file_id)}` : null);
  useEffect(() => {
    if (!d) return;
    const local = d.local as Json | null;
    const sarvam = d.sarvam as Json | null;
    setText(String(d.approved_text ?? sarvam?.text ?? local?.text ?? ""));
  }, [d]);
  if (page.error) return <p className="notice bad">{page.error.message}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const status = String(d.status);
  const act = (action: string, body: Json = {}) =>
    run((tk) => api.post(`/api/staff/pages/${id}/review`, { action, ...body }, tk), `Page ${action}d.`, page.reload);
  const signals = (d.quality_signals ?? {}) as Json;
  return (
    <>
      <p><Link to={`/staff/items/${String(d.item_id)}`}>{String(d.item_title)}</Link></p>
      <h1>Page {String(d.label ?? d.sequence)}</h1>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="chip">status: {status}</span>
        <span className="chip">route: {String(d.ocr_route)}</span>
        <span className="chip">gate: {d.gate_passed === null ? "n/a" : d.gate_passed ? "passed" : "failed"} ({String(d.gate_version ?? "")})</span>
        <span className={`chip${d.quote_verified ? " verified" : ""}`}>{d.quote_verified ? "quote-verified" : "not quote-verified"}</span>
        <span className="chip">external processing: {d.external_processing_allowed ? "allowed" : "not allowed"}</span>
      </div>
      {view}
      <div className="review-pair">
        <figure style={{ margin: 0 }}>
          {img ? <img src={img} alt={`Preservation master of page ${String(d.sequence)}`} /> : <div className="empty-state">Loading scan…</div>}
          <figcaption className="muted">Preservation master (read-only)</figcaption>
        </figure>
        <div className="stack">
          <label htmlFor="page-text">Text to approve</label>
          <textarea id="page-text" value={text} onChange={(e) => setText(e.target.value)} lang={String(d.language ?? "en")} />
          <div className="row">
            <button type="button" className="btn" disabled={busy || status === "approved"} onClick={() => act(text === String((d.sarvam as Json | null)?.text ?? (d.local as Json | null)?.text ?? "") ? "approve" : "correct", { text })}>Approve this text</button>
            <button type="button" className="btn secondary" disabled={busy} onClick={() => act("escalate", { reason: "needs second opinion" })}>Escalate</button>
            <button type="button" className="btn danger" disabled={busy} onClick={() => act("reject", { reason: "unusable capture" })}>Reject page</button>
            {(status === "sarvam_pending" || status === "needs_full_review") && Boolean(d.external_processing_allowed) && (
              <button type="button" className="btn secondary" disabled={busy} onClick={() => run((tk) => api.post(`/api/staff/pages/${id}/retry-sarvam`, {}, tk), "Sarvam retry queued.", page.reload)}>Retry Sarvam</button>
            )}
          </div>
          {status === "approved" && (
            <div className="sheet stack" style={{ padding: 14 }}>
              <strong>Quote verification</strong>
              <label className="row" style={{ fontWeight: 400 }}>
                <input type="checkbox" checked={compared} onChange={(e) => setCompared(e.target.checked)} style={{ width: 24, height: 24 }} />
                I compared the approved text with the original scan word for word.
              </label>
              <button type="button" className="btn secondary" disabled={!compared || busy || Boolean(d.quote_verified)} onClick={() => run((tk) => api.post(`/api/staff/pages/${id}/verify-quotes`, { confirm: true }, tk), "Recorded quote verification.", page.reload)}>Record quote verification</button>
            </div>
          )}
        </div>
      </div>
      <Section title="OCR results">
        <table className="grid" aria-label="OCR results">
          <thead><tr><th>Engine</th><th>Status</th><th>Confidence</th><th>Selected</th><th>Error</th></tr></thead>
          <tbody>
            {(d.results as Json[]).map((r) => (
              <tr key={String(r.id)}><td>{String(r.engine)} {String(r.engine_version ?? "")}</td><td>{String(r.status)}</td><td>{r.mean_confidence == null ? "" : Number(r.mean_confidence).toFixed(1)}</td><td>{r.selected ? "yes" : ""}</td><td>{String(r.error ?? "")}</td></tr>
            ))}
          </tbody>
        </table>
        {Object.keys(signals).length > 0 && <pre style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{JSON.stringify(signals, null, 1)}</pre>}
        {Array.isArray(d.diff) && (d.diff as string[]).length > 0 && (
          <>
            <h3>Local OCR compared with Sarvam</h3>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 13, background: "var(--paper)", padding: 10 }}>{(d.diff as string[]).join("\n")}</pre>
          </>
        )}
      </Section>
      <Section title="Decisions">
        <table className="grid" aria-label="Review decisions">
          <thead><tr><th>When</th><th>Action</th><th>Reviewer</th><th>Reason</th><th>Seeded fixture</th></tr></thead>
          <tbody>
            {(d.decisions as Json[]).map((x) => (
              <tr key={String(x.id)}><td>{String(x.at).slice(0, 19)}</td><td>{String(x.action)}</td><td>{String(x.reviewer)}</td><td>{String(x.reason ?? "")}</td><td>{x.seeded_fixture ? "yes (not a human review)" : ""}</td></tr>
            ))}
          </tbody>
        </table>
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- batch sample check

function SampleCheck({ page, value, onChange }: { page: Json; value: { checked: boolean; text: string }; onChange: (v: { checked: boolean; text: string }) => void }) {
  const img = useAuthedObjectUrl(page.delivery_file_id ? `/api/staff/files/${String(page.delivery_file_id)}` : null);
  return (
    <div className="review-pair" style={{ marginBottom: 20 }}>
      {img ? <img src={img} alt={`Sample page ${String(page.sequence)}`} /> : <div className="empty-state">Loading scan…</div>}
      <div className="stack">
        <textarea aria-label={`Candidate text for sample page ${String(page.sequence)}`} value={value.text} onChange={(e) => onChange({ ...value, text: e.target.value })} lang={String(page.language ?? "en")} />
        <label className="row" style={{ fontWeight: 400 }}>
          <input type="checkbox" checked={value.checked} onChange={(e) => onChange({ ...value, checked: e.target.checked })} style={{ width: 24, height: 24 }} />
          I checked this page against the scan (edit the text above if it needs correcting).
        </label>
      </div>
    </div>
  );
}

export function StaffBatch() {
  const { id } = useParams();
  const { token } = useStaff();
  const b = useApi<Json>(`/api/staff/batches/${id}`, token);
  const { run, busy, view } = useAction();
  const [checks, setChecks] = useState<Record<string, { checked: boolean; text: string }>>({});
  useEffect(() => {
    if (!b.data) return;
    const init: Record<string, { checked: boolean; text: string }> = {};
    for (const p of b.data.sample as Json[]) init[String(p.id)] = { checked: false, text: String(p.candidate_text ?? "") };
    setChecks(init);
  }, [b.data]);
  if (!b.data) return <p className="muted">Loading…</p>;
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
      passed ? "Batch passed: all pages approved on a sampled basis." : "Batch failed: every page moves to full review.", b.reload);
  };
  return (
    <>
      <h1>Batch {String(b.data.id)}</h1>
      <p className="muted">Status: {String(b.data.status)}. {(b.data.page_ids as number[]).length} pages; check each random sample page against its scan. If any sample page is wrong in a way that suggests the rest are wrong, fail the batch.</p>
      {view}
      {sample.map((p) => (
        <SampleCheck key={String(p.id)} page={p} value={checks[String(p.id)] ?? { checked: false, text: "" }} onChange={(v) => setChecks({ ...checks, [String(p.id)]: v })} />
      ))}
      <div className="row">
        <button type="button" className="btn" disabled={!allChecked || busy || b.data.status !== "open"} onClick={() => decide(true)}>Pass batch</button>
        <button type="button" className="btn danger" disabled={busy || b.data.status !== "open"} onClick={() => decide(false)}>Fail batch</button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- items

export function StaffItems() {
  const { token } = useStaff();
  const items = useApi<Json[]>("/api/staff/items", token);
  return (
    <>
      <h1>Items</h1>
      <table className="grid" aria-label="All items">
        <thead><tr><th>#</th><th>Title</th><th>Collection</th><th>State</th><th>Version</th><th>Pages approved</th><th>Display</th><th>Training</th><th>Access</th></tr></thead>
        <tbody>
          {(items.data ?? []).map((i) => (
            <tr key={String(i.id)}>
              <td>{String(i.id)}</td>
              <td><Link to={`/staff/items/${String(i.id)}`}>{String(i.title)}</Link>{i.is_fixture ? " (fixture)" : ""}</td>
              <td>{String(i.collection)}</td><td>{String(i.state)}</td><td>{String(i.version)}</td>
              <td>{String(i.pages_approved)} / {String(i.pages)}</td><td>{String(i.display_permission)}</td><td>{String(i.training_permission)}</td><td>{String(i.access_level)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function StaffItem() {
  const { id } = useParams();
  const { token } = useStaff();
  const item = useApi<Json>(`/api/staff/items/${id}`, token);
  const { run, busy, view } = useAction();
  const [reason, setReason] = useState("");
  const d = item.data;
  if (!d) return <p className="muted">Loading…</p>;
  const rights = d.rights as Json;
  return (
    <>
      <h1>{String(d.title)}</h1>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="chip">state: {String(d.state)}</span>
        <span className="chip">version {String(d.version)}</span>
        <span className="chip">access: {String(d.access_level)}</span>
        {Boolean(d.is_fixture) && <span className="chip fixture">synthetic fixture</span>}
        {d.state === "published" && <Link to={`/item/${String(d.id)}`}>Open visitor view</Link>}
      </div>
      {view}
      <Section title="Publication" actions={
        <>
          <button type="button" className="btn small" disabled={busy || !d.ready} onClick={() => run((tk) => api.post(`/api/staff/items/${id}/publish`, {}, tk), "Publication queued.", item.reload)}>Publish</button>
        </>
      }>
        {d.ready ? <p className="status ok">All review gates passed.</p> : (
          <ul>{(d.problems as string[]).map((p) => <li key={p}>{p}</li>)}</ul>
        )}
        {d.state === "published" && (
          <form className="row" onSubmit={(e) => { e.preventDefault(); void run((tk) => api.post(`/api/staff/items/${id}/withdraw`, { reason }, tk), "Withdrawn: removed from search, Ask, QR links and kiosk manifests. The preservation master is kept.", item.reload); }}>
            <label style={{ flex: 1 }}>Withdrawal reason<input type="text" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required /></label>
            <button type="submit" className="btn danger" disabled={busy}>Withdraw</button>
          </form>
        )}
      </Section>
      <Section title="Rights">
        <dl className="facts">
          <dt>Register entry</dt><dd>{String(rights.source_key)}</dd>
          <dt>Rights holder</dt><dd>{String(rights.rights_holder)}</dd>
          <dt>Display</dt><dd>{String(rights.display_permission)}</dd>
          <dt>Training</dt><dd>{String(rights.training_permission)}</dd>
          <dt>External processing</dt><dd>{String(rights.external_processing)}</dd>
          <dt>Evidence</dt><dd>{String(rights.evidence)}</dd>
        </dl>
      </Section>
      {(d.pages as Json[]).length > 0 && (
        <Section title="Pages">
          <table className="grid" aria-label="Pages of this item">
            <thead><tr><th>Page</th><th>Status</th><th>Route</th><th>Gate</th><th>Review</th><th>Quote-verified</th><th /></tr></thead>
            <tbody>
              {(d.pages as Json[]).map((p) => (
                <tr key={String(p.id)}>
                  <td>{String(p.label ?? p.sequence)}</td><td>{String(p.status)}</td><td>{String(p.ocr_route)}</td>
                  <td>{p.gate_passed === null ? "" : p.gate_passed ? "passed" : "failed"}</td><td>{String(p.review_mode ?? "")}</td>
                  <td>{p.quote_verified ? "yes" : ""}</td>
                  <td><Link to={`/staff/pages/${String(p.id)}`}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
      {(d.segments as Json[]).length > 0 && (
        <Section title="Transcript segments">
          {(d.segments as Json[]).map((s) => (
            <div key={String(s.id)} className="row" style={{ marginBottom: 8 }}>
              <span className="chip">{formatMs(Number(s.start_ms))}</span>
              <span style={{ flex: 1 }}>{String(s.text)}</span>
              <span className="chip">{String(s.status)}</span>
              {s.status === "approved" && !s.quote_verified && (
                <button type="button" className="btn secondary small" disabled={busy} title="Only after listening to the original recording"
                  onClick={() => window.confirm("Confirm you listened to the original recording and the transcript matches word for word.") && run((tk) => api.post(`/api/staff/segments/${String(s.id)}/verify-quotes`, { confirm: true }, tk), "Recorded.", item.reload)}>
                  Record quote check against audio
                </button>
              )}
              {Boolean(s.quote_verified) && <span className="chip verified">quote-verified</span>}
            </div>
          ))}
        </Section>
      )}
      {(d.derivatives as Json[]).length > 0 && (
        <Section title="Summaries and narration">
          {(d.derivatives as Json[]).map((x) => (
            <div key={String(x.id)} className="stack" style={{ marginBottom: 10 }}>
              <div className="row"><span className="chip">{String(x.kind)} ({String(x.language)})</span><span className="chip">{String(x.status)}</span><span className="muted">{String(x.generator ?? "")}</span></div>
              {x.content ? <p>{String(x.content)}</p> : null}
              {x.status === "draft" && (
                <div className="row"><button type="button" className="btn small" disabled={busy} onClick={() => run((tk) => api.post(`/api/staff/derivatives/${String(x.id)}/review`, { action: "approve" }, tk), "Approved.", item.reload)}>Approve</button></div>
              )}
            </div>
          ))}
        </Section>
      )}
      <Section title="Files">
        <table className="grid" aria-label="Files of this item">
          <thead><tr><th>#</th><th>Role</th><th>Kind</th><th>Format</th><th>Bytes</th><th>SHA-256</th><th>Generator</th></tr></thead>
          <tbody>
            {(d.files as Json[]).map((f) => (
              <tr key={String(f.id)} style={{ opacity: f.deleted ? 0.5 : 1 }}>
                <td>{String(f.id)}</td><td>{String(f.role)}</td><td>{String(f.kind)}</td><td>{String(f.format)}</td><td>{String(f.bytes)}</td><td><code>{String(f.sha256).slice(0, 16)}</code></td><td>{String(f.generator ?? "")}{f.deleted ? " (removed)" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </>
  );
}

// ---------------------------------------------------------------- rights register

const EMPTY_RIGHTS = {
  source_key: "", title: "", source_institution: "", rights_holder: "", basis_for_use: "", display_permission: "unknown",
  training_permission: "unknown", external_processing: "unknown", evidence: "", attribution: "", date_checked: new Date().toISOString().slice(0, 10), checked_by: "",
  source_url: "", edition: "", volume: "", discovery_only: false, notes: "",
};

export function StaffRights() {
  const { token } = useStaff();
  const rights = useApi<Json[]>("/api/staff/rights", token);
  const { run, busy, view } = useAction();
  const [form, setForm] = useState<typeof EMPTY_RIGHTS>(EMPTY_RIGHTS);
  const set = (k: keyof typeof EMPTY_RIGHTS) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const perm = (k: "display_permission" | "training_permission" | "external_processing") => (
    <label>{k.replace(/_/g, " ")}
      <select value={form[k]} onChange={set(k)}>
        {["unknown", "allowed", "not_allowed"].map((v) => <option key={v}>{v}</option>)}
      </select>
    </label>
  );
  return (
    <>
      <h1>Rights register</h1>
      <p className="muted" style={{ maxWidth: "80ch" }}>Permissions are never inferred from a download being available. Unknown means not allowed. Changing display from allowed withdraws that source's published items; changing training from allowed flags the datasets that used it.</p>
      <table className="grid" aria-label="Rights register entries" style={{ marginBottom: 20 }}>
        <thead><tr><th>Key</th><th>Title</th><th>Holder</th><th>Display</th><th>Training</th><th>External processing</th><th>Discovery only</th><th /></tr></thead>
        <tbody>
          {(rights.data ?? []).map((r) => (
            <tr key={String(r.id)}>
              <td>{String(r.source_key)}{r.is_fixture ? " (fixture)" : ""}</td><td>{String(r.title)}</td><td>{String(r.rights_holder)}</td>
              <td>{String(r.display_permission)}</td><td>{String(r.training_permission)}</td><td>{String(r.external_processing)}</td><td>{r.discovery_only ? "yes" : ""}</td>
              <td><button type="button" className="btn quiet small" onClick={() => setForm(Object.fromEntries(Object.keys(EMPTY_RIGHTS).map((k) => [k, r[k] ?? (EMPTY_RIGHTS as Json)[k]])) as typeof EMPTY_RIGHTS)}>Edit</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="sheet stack" onSubmit={(e) => { e.preventDefault(); void run((tk) => api.post("/api/staff/rights", form, tk), "Rights entry saved and audited.", rights.reload); }}>
        <h2 style={{ fontSize: "var(--step-1)" }}>Add or update an entry</h2>
        <div className="form-grid">
          <label>Source key<input type="text" value={form.source_key} onChange={set("source_key")} required /></label>
          <label>Title<input type="text" value={form.title} onChange={set("title")} required /></label>
          <label>Institution<input type="text" value={form.source_institution} onChange={set("source_institution")} required /></label>
          <label>Rights holder<input type="text" value={form.rights_holder} onChange={set("rights_holder")} required /></label>
          <label>Basis for use<input type="text" value={form.basis_for_use} onChange={set("basis_for_use")} required /></label>
          {perm("display_permission")}
          {perm("training_permission")}
          {perm("external_processing")}
          <label>Evidence (licence text, letter, agreement reference)<input type="text" value={form.evidence} onChange={set("evidence")} required /></label>
          <label>Attribution line<input type="text" value={form.attribution} onChange={set("attribution")} required /></label>
          <label>Date checked<input type="date" value={form.date_checked} onChange={set("date_checked")} required /></label>
          <label>Checked by<input type="text" value={form.checked_by} onChange={set("checked_by")} required /></label>
          <label>Source URL<input type="text" value={form.source_url ?? ""} onChange={set("source_url")} /></label>
        </div>
        <div className="row">
          <button type="submit" className="btn" disabled={busy}>Save entry</button>
          <button type="button" className="btn secondary" onClick={() => setForm(EMPTY_RIGHTS)}>Clear</button>
        </div>
        {view}
      </form>
    </>
  );
}

// ---------------------------------------------------------------- jobs and audit

export function StaffJobs() {
  const { token } = useStaff();
  const jobs = useApi<Json[]>("/api/staff/jobs", token);
  return (
    <>
      <div className="row"><h1>Jobs</h1><span className="spacer" /><button type="button" className="btn secondary small" onClick={jobs.reload}>Refresh</button></div>
      <table className="grid" aria-label="Recent jobs">
        <thead><tr><th>#</th><th>Kind</th><th>Status</th><th>Attempts</th><th>Payload</th><th>Error</th><th>Updated</th></tr></thead>
        <tbody>
          {(jobs.data ?? []).map((j) => (
            <tr key={String(j.id)}><td>{String(j.id)}</td><td>{String(j.kind)}</td><td>{String(j.status)}</td><td>{String(j.attempts)}</td><td><code>{JSON.stringify(j.payload)}</code></td><td>{String(j.error ?? "")}</td><td>{String(j.updated_at).slice(0, 19)}</td></tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function StaffAudit() {
  const { token, can } = useStaff();
  const audit = useApi<Json[]>("/api/staff/audit?limit=300", token);
  const { run, busy, view } = useAction();
  const [chain, setChain] = useState<string | null>(null);
  return (
    <>
      <div className="row">
        <h1>Audit log</h1>
        <span className="spacer" />
        {can("admin") && (
          <button type="button" className="btn secondary small" disabled={busy} onClick={() => run(async (tk) => {
            const r = await api.get<{ chain_ok: boolean; events_checked: number }>("/api/staff/audit/verify", tk);
            setChain(`${r.chain_ok ? "Hash chain intact" : "HASH CHAIN BROKEN"} across ${r.events_checked} events.`);
          }, "Verified.")}>Verify hash chain</button>
        )}
      </div>
      {view}
      {chain && <p className="notice">{chain}</p>}
      <p className="muted">Append-only: the database rejects updates and deletes on this table. Each row carries the hash of the previous row.</p>
      <table className="grid" aria-label="Audit events">
        <thead><tr><th>#</th><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Detail</th><th>Row hash</th></tr></thead>
        <tbody>
          {(audit.data ?? []).map((a) => (
            <tr key={String(a.id)}><td>{String(a.id)}</td><td>{String(a.at).slice(0, 19)}</td><td>{String(a.actor)}</td><td>{String(a.action)}</td><td>{String(a.entity)} {String(a.entity_id)}</td><td><code style={{ fontSize: 12 }}>{JSON.stringify(a.detail)}</code></td><td><code>{String(a.row_hash)}</code></td></tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
