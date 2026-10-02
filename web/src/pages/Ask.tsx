import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, type AskResult } from "../api";
import { useSession } from "../state";
import { AddToList, CitationLink, ContentText, FixtureChip, KindChip, Loading, useDocumentTitle, VerifiedChip } from "../components/Bits";
import { VoiceQuestion } from "../components/VoiceQuestion";
import { mergeTranscript } from "../voice";

const MAX_QUESTION = 500;

/** `autoAsk`: ask the ?q= question on arrival (links from Home). Off inside the /kiosk dock, where ?q= belongs to Search. */
export function Ask({ autoAsk = true }: { autoAsk?: boolean } = {}) {
  const s = useSession();
  const { t } = s;
  const [params, setParams] = useSearchParams();
  const [question, setQuestion] = useState((params.get("q") ?? "").slice(0, MAX_QUESTION));
  // The last answer of this visit comes back after Back, so it is not asked (and paid for) again.
  const [asked, setAsked] = useState<string | null>(s.askLast?.asked ?? null);
  const [result, setResult] = useState<AskResult | null>(s.askLast?.result ?? null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const autoAsked = useRef(false);
  // A ref, not `busy`: a double click fires twice before the re-render, and each question is a paid call.
  const inFlight = useRef(false);
  const pending = useRef<AbortController | null>(null);
  useDocumentTitle(t("askTitle"));

  // Leaving Ask or finishing the visit cancels the question in flight.
  useEffect(() => () => pending.current?.abort(), [s.sessionId]);

  const submit = async (e?: FormEvent, override?: string) => {
    e?.preventDefault();
    const q = (override ?? question).trim().slice(0, MAX_QUESTION);
    if (!q || inFlight.current) return;
    inFlight.current = true;
    const sessionId = s.sessionId;
    const ctrl = new AbortController();
    pending.current = ctrl;
    setBusy(true);
    setAsked(q);
    setResult(null);
    s.setAskLast(null);
    try {
      const r = await api.post<AskResult>("/api/visitor/ask", { question: q, history: s.askHistory, language: s.lang, session_id: sessionId }, null, ctrl.signal);
      // Finish was pressed while waiting: this answer belongs to the previous visitor.
      if (ctrl.signal.aborted || !s.isCurrentSession(sessionId)) return;
      setResult(r);
      if (r.outcome !== "rejected_input" && r.outcome !== "error") setQuestion((cur) => (cur === q ? "" : cur));
      if (r.outcome === "answered" || r.outcome === "extractive" || r.outcome === "background") {
        s.pushAsk({ q, a: r.sentences.map((x) => x.text).join(" ").slice(0, 300) });
        s.setAskLast({ asked: q, result: r });
      }
    } catch (err) {
      if (ctrl.signal.aborted || !s.isCurrentSession(sessionId)) return;
      const offline = err instanceof ApiError && err.offline;
      setResult({ outcome: offline ? "offline" : "error", language: s.lang, label: null, message: null, sentences: [], citations: [], paraphrase_only: false, retried_retrieval: false });
    } finally {
      if (pending.current === ctrl) pending.current = null;
      inFlight.current = false;
      setBusy(false);
      setParams({}, { replace: true });
    }
  };

  useEffect(() => {
    const q = params.get("q");
    if (autoAsk && q && !autoAsked.current) {
      autoAsked.current = true;
      void submit(undefined, q);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const numberOf = (pid: number) => (result?.citations.findIndex((c) => c.passage_id === pid) ?? -1) + 1;

  const hasUsed = Boolean(asked || result || s.askHistory.length > 0);

  return (
    <div className="page" style={{ maxWidth: 1000 }}>
      <h1>{t("askTitle")}</h1>
      {!hasUsed && <p className="muted" style={{ maxWidth: "70ch" }}>{t("askLead")}</p>}
      {!s.online && <div className="notice">{t("askOffline")}</div>}
      {s.config && !s.config.ask_model_connected && <div className="notice">{t("askNoModel")}</div>}

      <form className="ask-form" onSubmit={submit}>
        <label htmlFor="ask-q" className="visually-hidden">{t("askPlaceholder")}</label>
        <textarea
          id="ask-q"
          ref={input}
          value={question}
          maxLength={MAX_QUESTION}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder={s.askHistory.length ? t("askFollowUp") : t("askPlaceholder")}
        />
        <button type="submit" className="btn" disabled={busy || !question.trim()}>{t("askButton")}</button>
      </form>
      {/* The box stops at MAX_QUESTION characters; say so before the visitor runs into it. */}
      {question.length > MAX_QUESTION - 100 && (
        <p className={`muted ask-count${question.length >= MAX_QUESTION ? " full" : ""}`} aria-live="polite">
          {t("askCharCount", { n: question.length, max: MAX_QUESTION })}
        </p>
      )}
      <VoiceQuestion
        disabled={busy}
        hideNote={hasUsed}
        onText={(text) => {
          setQuestion((q) => mergeTranscript(q, text, MAX_QUESTION));
          input.current?.focus();
        }}
      />

      {busy && (
        <div style={{ marginTop: 20 }}>
          <Loading card label={t("askThinking")} />
        </div>
      )}
      <div aria-live="polite" aria-busy={busy}>
        {result && asked && (
          <article className="answer">
            <h2 style={{ fontSize: "var(--step-1)" }}>{asked}</h2>
            <AnswerBody result={result} numberOf={numberOf} onRetry={() => void submit(undefined, asked ?? undefined)} onAsk={(q) => void submit(undefined, q)} />
          </article>
        )}
      </div>
    </div>
  );
}

function AnswerBody({ result, numberOf, onRetry, onAsk }: { result: AskResult; numberOf: (pid: number) => number; onRetry: () => void; onAsk: (q: string) => void }) {
  const { t } = useSession();
  const r = result;
  const retry = <button type="button" className="btn small" onClick={onRetry}>{t("retry")}</button>;
  if (r.outcome === "offline") {
    return (
      <>
        <div className="notice">{t("askOffline")}</div>
        {retry}
      </>
    );
  }
  if (r.outcome === "error") {
    return (
      <>
        {/* The server says when the answer service failed; a request that never got a reply has no message. */}
        <div className="notice bad">{r.message ? t("askServiceError") : t("errorGeneric")}</div>
        {retry}
        {r.citations.length > 0 && <Sources result={r} heading={t("askRelated")} />}
      </>
    );
  }
  if (r.outcome === "off_topic") {
    return (
      <>
        <p>{t("askOffTopic")}</p>
        <div className="row ask-suggestions" style={{ flexWrap: "wrap", gap: 8 }}>
          {(["askSuggest1", "askSuggest2", "askSuggest3"] as const).map((k) => (
            <button key={k} type="button" className="btn small secondary" onClick={() => onAsk(t(k))}>{t(k)}</button>
          ))}
        </div>
      </>
    );
  }
  if (r.outcome === "background") {
    return (
      <>
        <div className="label-row"><span className="chip background">{t("askBackgroundLabel")}</span></div>
        <div className="stack background-answer" style={{ gap: 8 }}>
          {r.sentences.map((sent, i) => (
            <p key={i} lang={r.language} style={{ margin: 0 }}>{sent.text}</p>
          ))}
        </div>
        <p className="muted" style={{ fontSize: "var(--step--1)", marginTop: 12 }}>{t("askBackgroundNote")}</p>
        {r.citations.length > 0 && <Sources result={r} heading={t("askExploreArchive")} showExcerpt />}
      </>
    );
  }
  if (r.outcome === "refused" || r.outcome === "rejected_input") {
    return (
      <>
        <div className="label-row"><span className="chip">{t(r.reason === "too_long" ? "askTooLong" : "askRefused")}</span></div>
        <p>{r.message}</p>
        {r.citations.length > 0 && <Sources result={r} heading={t("askRelated")} />}
      </>
    );
  }
  if (r.outcome === "insufficient") {
    return (
      <>
        <div className="banner warn" style={{ borderRadius: "var(--radius)", margin: "14px 0" }}>
          <div>
            <strong>{r.message ?? t("askInsufficient")}</strong>
            <p style={{ margin: "4px 0 0", fontSize: "var(--step--1)" }}>
              {t("askInsufficientNote")}
            </p>
          </div>
        </div>
        {r.citations.length > 0 && <Sources result={r} heading={t("askRelated")} showExcerpt />}
      </>
    );
  }
  if (r.outcome === "extractive") {
    return (
      <>
        <div className="label-row"><span className="chip">{t("askExtractive")}</span></div>
        {r.message && <p className="muted">{r.message}</p>}
        <Sources result={r} heading={t("askExtractive")} showExcerpt />
      </>
    );
  }
  return (
    <>
      <div className="label-row">
        <span className="chip ai">{t("askLabel")}</span>
        {r.paraphrase_only && <span className="chip">{t("askParaphrase")}</span>}
        {r.cache_hit && <span className="chip">{t("askCached")}</span>}
      </div>
      <div className="stack" style={{ gap: 8 }}>
        {r.sentences.map((sent, i) => (
          <p key={i} className="sentence" lang={r.language} style={{ margin: 0 }}>
            {sent.text}
            {sent.citations.map((pid) => (
              <CitationLink key={pid} n={numberOf(pid)} targetId={`src-${pid}`} />
            ))}
          </p>
        ))}
      </div>
      {/* The note speaks of quotes matching, so it needs at least one quote: otherwise it sits beside sources
          marked "not yet quote-verified" and contradicts them. */}
      {r.checks?.citations_ok && r.checks.quotes > 0 && r.checks.quotes_verified === r.checks.quotes && (
        <p className="muted" style={{ fontSize: "var(--step--1)", marginTop: 12 }}>{t("claimNote")}</p>
      )}
      <Sources result={r} heading={t("sources")} showExcerpt />
    </>
  );
}

function Sources({ result, heading, showExcerpt = true }: { result: AskResult; heading: string; showExcerpt?: boolean }) {
  const { t } = useSession();
  return (
    <details className="sources-dropdown" open>
      <summary id="sources-h" aria-label={heading}>
        <span>{heading} ({result.citations.length})</span>
      </summary>
      <ol className="sources" style={{ listStyle: "none", padding: 0, margin: "16px 0 0", display: "flex", flexDirection: "column", gap: 14 }}>
        {result.citations.map((c, i) => (
          <li key={c.passage_id} id={`src-${c.passage_id}`} tabIndex={-1} className="result" style={{ padding: "16px 20px" }}>
            <div className="row" style={{ alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
              <span className="n" aria-hidden="true" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, borderRadius: "50%", background: "var(--indigo)", color: "#fff", fontSize: "0.8rem", fontWeight: 700 }}>
                {i + 1}
              </span>
              <Link className="title-link" to={c.deep_link} style={{ fontSize: "var(--step-0)", fontWeight: 600 }}>
                <ContentText text={c.title} />
              </Link>
              <span className="spacer" />
              <KindChip label={c.kind_label} />
              <VerifiedChip verified={c.quote_verified} />
              <FixtureChip show={c.is_fixture} />
            </div>
            {showExcerpt && c.excerpt && (
              <blockquote style={{ borderLeft: "3px solid var(--indigo)", paddingLeft: "14px", margin: "8px 0", color: "var(--ink)", fontStyle: "normal" }}>
                <ContentText text={c.excerpt} />
              </blockquote>
            )}
            <span className="cite" style={{ gridColumn: "1 / -1", marginTop: "4px" }}>
              {t("citation")}: {c.label}
            </span>
            <div className="row" style={{ marginTop: 8, gridColumn: "1 / -1" }}>
              <Link className="btn small" to={c.deep_link}>{t("openItem")}</Link>
              <AddToList entry={{ item_id: c.item_id, title: c.title, passage_id: c.passage_id, citation: c.label }} />
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}
