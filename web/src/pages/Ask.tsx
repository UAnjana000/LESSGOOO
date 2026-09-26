import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, type AskResult } from "../api";
import { useSession } from "../state";
import { AddToList, FixtureChip, KindChip, VerifiedChip } from "../components/Bits";

export function Ask() {
  const s = useSession();
  const { t } = s;
  const [params, setParams] = useSearchParams();
  const [question, setQuestion] = useState(params.get("q") ?? "");
  const [asked, setAsked] = useState<string | null>(null);
  const [result, setResult] = useState<AskResult | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const autoAsked = useRef(false);

  const submit = async (e?: FormEvent, override?: string) => {
    e?.preventDefault();
    const q = (override ?? question).trim();
    if (!q || busy) return;
    setBusy(true);
    setAsked(q);
    setResult(null);
    try {
      const r = await api.post<AskResult>("/api/visitor/ask", { question: q, history: s.askHistory, language: s.lang, session_id: s.sessionId });
      setResult(r);
      if (r.outcome === "answered" || r.outcome === "extractive") {
        s.pushAsk({ q, a: r.sentences.map((x) => x.text).join(" ").slice(0, 300) });
      }
    } catch (err) {
      const offline = err instanceof ApiError && (err.offline || err.status === 503);
      setResult({ outcome: offline ? "offline" : "error", language: s.lang, label: null, message: null, sentences: [], citations: [], paraphrase_only: false, retried_retrieval: false });
    } finally {
      setBusy(false);
      setQuestion("");
      setParams({}, { replace: true });
    }
  };

  useEffect(() => {
    const q = params.get("q");
    if (q && !autoAsked.current) {
      autoAsked.current = true;
      void submit(undefined, q);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const numberOf = (pid: number) => (result?.citations.findIndex((c) => c.passage_id === pid) ?? -1) + 1;

  return (
    <div className="page" style={{ maxWidth: 1000 }}>
      <h1>{t("askTitle")}</h1>
      <p className="muted" style={{ maxWidth: "70ch" }}>{t("askLead")}</p>
      {!s.online && <div className="notice">{t("askOffline")}</div>}
      {s.config && !s.config.ask_model_connected && <div className="notice">{t("askNoModel")}</div>}

      <form className="ask-form" onSubmit={submit}>
        <label htmlFor="ask-q" className="visually-hidden">{t("askPlaceholder")}</label>
        <textarea
          id="ask-q"
          ref={input}
          value={question}
          maxLength={500}
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

      <div aria-live="polite" aria-busy={busy}>
        {busy && <p role="status" className="muted" style={{ marginTop: 16 }}>{t("askThinking")}</p>}
        {result && asked && (
          <article className="answer">
            <h2 style={{ fontSize: "var(--step-1)" }}>{asked}</h2>
            <AnswerBody result={result} numberOf={numberOf} />
          </article>
        )}
      </div>
    </div>
  );
}

function AnswerBody({ result, numberOf }: { result: AskResult; numberOf: (pid: number) => number }) {
  const { t } = useSession();
  const r = result;
  if (r.outcome === "offline") return <div className="notice">{t("askOffline")}</div>;
  if (r.outcome === "error") return <div className="notice bad">{t("errorGeneric")}</div>;
  if (r.outcome === "refused" || r.outcome === "rejected_input") {
    return (
      <>
        <div className="label-row"><span className="chip">{t("askRefused")}</span></div>
        <p>{r.message}</p>
        {r.citations.length > 0 && <Sources result={r} heading={t("askRelated")} />}
      </>
    );
  }
  if (r.outcome === "insufficient") {
    return (
      <>
        <p className="notice">{r.message ?? t("askInsufficient")}</p>
        {r.citations.length > 0 && <Sources result={r} heading={t("askRelated")} />}
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
        <span className="chip verified">{t("askLabel")}</span>
        {r.paraphrase_only && <span className="chip">{t("askParaphrase")}</span>}
        {r.cache_hit && <span className="chip">{t("askCached")}</span>}
      </div>
      <div className="stack" style={{ gap: 8 }}>
        {r.sentences.map((sent, i) => (
          <p key={i} className="sentence" lang={r.language} style={{ margin: 0 }}>
            {sent.text}
            {sent.citations.map((pid) => (
              <sup key={pid}>
                <a href={`#src-${pid}`} aria-label={`${t("source")} ${numberOf(pid)}`}>{numberOf(pid)}</a>
              </sup>
            ))}
          </p>
        ))}
      </div>
      <p className="muted" style={{ fontSize: "var(--step--1)", marginTop: 12 }}>{t("claimNote")}</p>
      <Sources result={r} heading={t("sources")} />
    </>
  );
}

function Sources({ result, heading, showExcerpt = true }: { result: AskResult; heading: string; showExcerpt?: boolean }) {
  const { t } = useSession();
  return (
    <section aria-label={heading}>
      <h3 style={{ marginTop: 20 }}>{heading}</h3>
      <ol className="sources">
        {result.citations.map((c, i) => (
          <li key={c.passage_id} id={`src-${c.passage_id}`}>
            <div className="row">
              <span className="n">{i + 1}</span>
              <Link to={c.deep_link}><strong>{c.title}</strong></Link>
              <span className="spacer" />
              <KindChip label={c.kind_label} />
              <VerifiedChip verified={c.quote_verified} />
              <FixtureChip show={c.is_fixture} />
            </div>
            {showExcerpt && <blockquote>{c.excerpt}</blockquote>}
            <span className="cite">{t("citation")}: {c.label}</span>
            <div className="row" style={{ marginTop: 8 }}>
              <Link className="btn small" to={c.deep_link}>{t("openItem")}</Link>
              <AddToList entry={{ item_id: c.item_id, title: c.title, passage_id: c.passage_id, citation: c.label }} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
