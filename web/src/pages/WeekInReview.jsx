/* Week in review — the week's Notion activity as a document: stats, funds
   that moved, and the reads worth carrying into next week. Built once per
   week (see api/main.py's /api/jobs/week-in-review) and served from the
   stored copy on every later visit — a page view must never itself trigger
   a Notion crawl plus a model call. */
import React from "react";
import { get, post } from "../api.js";
import {
  Banner, Button, Card, Chip, ErrorNote, KpiBand, Mascot, PageHeader,
  SectionHead, fmtDT,
} from "../ui.jsx";

/* First checks for a stored review of the week just finished; only starts
   (or re-attaches to) a background job if nothing is stored yet. Mirrors the
   background-job hooks used elsewhere in this app (felixStore.js's job
   polling, the old What's new page's useAutoJob). */
function useWeekInReview() {
  const [review, setReview] = React.useState(null);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [deferred, setDeferred] = React.useState(false);
  const pollRef = React.useRef(null);
  const startedRef = React.useRef(false);

  const attach = React.useCallback((jobId) => {
    clearInterval(pollRef.current);
    setRunning(true);
    pollRef.current = setInterval(async () => {
      try {
        const j = await get(`/api/jobs/${jobId}`);
        if (j.status !== "running") {
          clearInterval(pollRef.current);
          setRunning(false);
          if (j.status === "error") setError(j.error);
          else setReview(j.result);
        }
      } catch (e) {
        clearInterval(pollRef.current);
        setRunning(false); setError(e.message);
      }
    }, 1500);
  }, []);

  /* A page view is automatic work (auto=1): it stands down while a meeting
     is recording — see api/main.py's live_recording_active. Only the Rebuild
     button, an instruction, may start the job mid-meeting. */
  const start = React.useCallback(async (auto = false) => {
    setError(null);
    try {
      const job = await post(`/api/jobs/week-in-review${auto ? "?auto=1" : ""}`, {});
      if (job.deferred) { setDeferred(true); return; }
      setDeferred(false);
      attach(job.id);
    } catch (e) { setError(e.message); }
  }, [attach]);

  React.useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    (async () => {
      try {
        const { review: stored } = await get("/api/week-in-review");
        if (stored) { setReview(stored); return; }
        const { jobs } = await get("/api/jobs?kind=week-in-review");
        const latest = jobs[0];
        if (!latest) { start(true); return; }
        if (latest.status === "running") { attach(latest.id); return; }
        const j = await get(`/api/jobs/${latest.id}`);
        if (j.status === "error") setError(j.error); else setReview(j.result);
      } catch { start(true); }
    })();
    return () => clearInterval(pollRef.current);
  }, [start, attach]);

  // Rebuilding replaces this week's stored copy — start over from nothing
  // so the page shows the running state rather than the stale one.
  const rebuild = React.useCallback(() => { setReview(null); start(); }, [start]);

  return { review, running, error, deferred, rebuild };
}

/* **bold** -> <b>, the only markup the model is allowed to emit. */
function inlineBold(text) {
  return String(text || "").split(/\*\*(.+?)\*\*/g)
    .map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part));
}

const BADGE_TONE = { neutral: "neutral", field: "teal", brass: "brass",
                     positive: "positive", caution: "caution", critical: "critical" };
const NOTE_TONE = { risk: "critical", watch: "caution", good: "positive", next: "teal" };

function ReadNote({ note }) {
  return (
    <div style={{ background: "var(--paper-050)", border: "1px solid var(--paper-200)",
                  borderRadius: "var(--radius)", padding: "10px 13px" }}>
      <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".12em",
            textTransform: "uppercase", display: "block", marginBottom: 4,
            color: `var(--${NOTE_TONE[note.kind] || "teal"}-600)` }}>
        {note.label}
      </span>
      <p style={{ fontSize: "13px", lineHeight: 1.5, margin: 0, color: "var(--stone-600)" }}>
        {inlineBold(note.body)}
      </p>
    </div>
  );
}

function ReadCard({ read }) {
  const body = (
    <>
      {read.paragraphs.map((p, i) => (
        <p key={i} style={{ fontSize: "14px", lineHeight: 1.6,
                            margin: i ? "8px 0 0" : 0, color: "var(--stone-600)" }}>
          {inlineBold(p)}
        </p>
      ))}
      {read.quote && (
        <blockquote style={{ margin: "10px 0 0", padding: "1px 0 1px 14px",
                              borderLeft: "2px solid var(--teal-500)",
                              font: "italic 400 14px/1.55 var(--serif)",
                              color: "var(--ink-800)" }}>
          {read.quote}
        </blockquote>
      )}
    </>
  );
  return (
    <Card accent={read.wide ? "brass" : "teal"}
      style={read.wide
        ? { gridColumn: "1 / -1", display: "grid",
            gridTemplateColumns: "1fr 260px", gap: 22, alignItems: "start" }
        : { display: "flex", flexDirection: "column" }}>
      <div>
        <div className="spread" style={{ gap: 10, alignItems: "flex-start" }}>
          <div>
            <div style={{ font: `${read.wide ? "400 19px" : "500 15px"}/1.35 var(--serif)`,
                          color: "var(--ink-800)" }}>
              {read.title}
            </div>
            <div className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                          color: "var(--stone-400)", marginTop: 4 }}>
              {read.meta}
            </div>
          </div>
          <Chip tone={BADGE_TONE[read.badge.tone] || "neutral"}>{read.badge.label}</Chip>
        </div>
        <div style={{ marginTop: 9 }}>{body}</div>
        {!read.wide && read.note && <div style={{ marginTop: 9 }}><ReadNote note={read.note} /></div>}
        <div className="mono" style={{ fontSize: 10, color: "var(--stone-400)",
                      marginTop: 11, paddingTop: 8, borderTop: "1px solid var(--paper-200)" }}>
          Source ·{" "}
          {read.sources.map((s, i) => (
            <React.Fragment key={s.url}>
              {i > 0 && " · "}
              <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "var(--stone-500)" }}>
                {s.label}
              </a>
            </React.Fragment>
          ))}
        </div>
      </div>
      {read.wide && <div>{read.note && <ReadNote note={read.note} />}</div>}
    </Card>
  );
}

export default function WeekInReview() {
  const { review, running, error, deferred, rebuild } = useWeekInReview();
  const stats = review?.stats;

  return (
    <div className="fade-in">
      <PageHeader eyebrow={review ? `${review.ref} · PRIVATE & CONFIDENTIAL` : "WEEK IN REVIEW"}
        eyebrowTone="brass" title="What's new"
        actions={
          <Button variant="ghost" busy={running} onClick={rebuild}>
            Rebuild the briefing
          </Button>
        }>
        {review ? review.window_label
          : "Built automatically when you open this page — the week's notes, funds and contacts from Notion."}
      </PageHeader>

      <ErrorNote error={error} />

      {!review && (
        <div style={{ display: "flex", gap: 22, alignItems: "center", margin: "6px 0 30px" }}>
          <Mascot state={running ? "reading" : "presenting"} width={88} />
          <p style={{ font: "400 18px/1.6 var(--serif)", color: "var(--ink-800)",
                      maxWidth: "60ch", margin: 0 }}>
            {running ? "Reading the week's notes, funds and contacts…"
              : deferred ? "A meeting is recording, so the briefing is on hold — it protects "
                + "your transcription. It builds on your next visit, or use Rebuild."
              : "Nothing built yet."}
          </p>
        </div>
      )}

      {review && (
        <>
          <span className="microlabel" style={{ color: "var(--teal-700)" }}>
            THE WEEK, IN ONE PARAGRAPH
          </span>
          <h2 style={{ font: "400 26px/1.35 var(--serif)", color: "var(--ink-800)",
                       margin: "8px 0 10px", maxWidth: "70ch" }}>
            {review.headline}
          </h2>
          <p style={{ fontSize: 15, lineHeight: 1.6, color: "var(--stone-600)",
                      maxWidth: "72ch", margin: 0 }}>
            {review.standfirst}
          </p>

          <KpiBand items={[
            ["ENGAGEMENTS", stats.engagements, false,
             `${stats.note_records} note record(s) · ${stats.duplicate_sets} duplicate set(s)`],
            ["GP MEETINGS", stats.gp_meetings, false,
             `Plus ${stats.lp_meetings} LP, ${stats.internal_meetings} internal, ${stats.service_meetings} service`],
            ["DECLINED", stats.declined, stats.declined > 0,
             [...(review.declined || []).map((d) => d.name), ...(review.declined_names || [])]
               .slice(0, 2).join(", ") || "None this week"],
            ["NEW FUND RECORDS", stats.new_fund_records, false,
             `${stats.funds_touched} fund page(s) touched in total`],
            ["NEW CONTACTS", stats.new_contacts, false,
             `Across ${stats.firms_represented} firm(s)`],
          ]} />

          {review.urgent && (
            <Banner tone="error">
              <b>{review.urgent.badge_label}</b> — <b>{review.urgent.title}.</b>{" "}
              {review.urgent.paragraphs.join(" ")}
            </Banner>
          )}

          {review.moved.length > 0 && (
            <section style={{ marginTop: 30 }}>
              <SectionHead label="WHAT MOVED" right={(() => {
                const dec = review.moved.filter((m) => m.declined).length;
                return dec
                  ? `${review.moved.length} FUND(S) · ${dec} DECLINED`
                  : `${review.moved.length} FUND(S)`;
              })()} />
              <table className="wb">
                <thead>
                  <tr><th>Fund</th><th>Status</th><th>Focus</th><th>Why it matters</th></tr>
                </thead>
                <tbody>
                  {review.moved.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <a href={m.url} target="_blank" rel="noreferrer"
                           style={{ color: "var(--ink-800)", fontWeight: 500 }}>
                          {m.name}
                        </a>
                      </td>
                      <td style={{ textAlign: "left", fontFamily: "var(--sans)" }}>
                        <Chip tone={/\(Declined\)$/.test(m.status) ? "critical" : "teal"}>
                          {m.status}
                        </Chip>
                      </td>
                      <td style={{ textAlign: "left", fontFamily: "var(--mono)", fontSize: 11.5 }}>
                        {m.focus || <span style={{ color: "var(--stone-400)" }}>—</span>}
                      </td>
                      {/* An unevidenced reason is greyed and italic rather than
                          hidden: the row still says what happened, and the
                          styling says the desk never wrote down why. */}
                      <td style={{ textAlign: "left", fontFamily: "var(--sans)", fontSize: 13,
                                   color: m.why_evidenced === false
                                     ? "var(--stone-400)" : "var(--stone-600)",
                                   fontStyle: m.why_evidenced === false ? "italic" : "normal" }}>
                        {m.why}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {/* Declined funds are rows in WHAT MOVED now — declining a fund is a
              decision, not a footnote. This section is only for declines the
              table does NOT already carry: each declined fund is checked
              against the moved rows by id and name (older stored reviews
              never set the row's `declined` flag, so a flag test alone let
              the same fund appear twice — 18 Aug 2026). */}
          {(() => {
            const movedIds = new Set((review.moved || []).map((m) => m.id));
            const movedNames = new Set((review.moved || [])
              .map((m) => (m.name || "").toLowerCase()));
            const declinedRows = (review.declined || []).filter((d) =>
              !movedIds.has(d.id) && !movedNames.has((d.name || "").toLowerCase()));
            const declinedNames = (review.declined_names || []).filter((n) =>
              !movedNames.has((n || "").toLowerCase()));
            if (!declinedRows.length && !declinedNames.length) return null;
            return (
            <section style={{ marginTop: 30 }}>
              <SectionHead label="DECLINED THIS WEEK"
                right={`${declinedRows.length + declinedNames.length} FUND(S)`} />
              {declinedRows.length > 0 && (
                <table className="wb">
                  <thead>
                    <tr><th>Fund</th><th>Status</th><th>Focus</th><th>Why declined</th></tr>
                  </thead>
                  <tbody>
                    {declinedRows.map((d) => (
                      <tr key={d.id}>
                        <td>
                          <a href={d.url} target="_blank" rel="noreferrer"
                             style={{ color: "var(--ink-800)", fontWeight: 500 }}>
                            {d.name}
                          </a>
                        </td>
                        <td style={{ textAlign: "left", fontFamily: "var(--sans)" }}>
                          <Chip tone="critical">{d.status}</Chip>
                        </td>
                        <td style={{ textAlign: "left", fontFamily: "var(--mono)", fontSize: 11.5 }}>
                          {d.focus}
                        </td>
                        <td style={{ textAlign: "left", fontFamily: "var(--sans)",
                                     color: "var(--stone-600)", fontSize: 13 }}>
                          {d.why}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {declinedNames.length > 0 && (
                <div style={{ marginTop: declinedRows.length > 0 ? 12 : 0 }}>
                  <span className="microlabel">
                    {declinedRows.length > 0
                      ? "Also declined, no evidenced reason in the notes"
                      : `All ${declinedNames.length} declined this week`}
                  </span>
                  <p style={{ fontSize: 13, color: "var(--stone-600)", marginTop: 8 }}>
                    {declinedNames.join(" · ")}
                  </p>
                </div>
              )}
            </section>
            );
          })()}

          <section style={{ marginTop: 34 }}>
            <SectionHead label="THE READS THAT MATTER" right={String(review.reads.length)} />
            <div style={{ display: "grid",
                          gridTemplateColumns: "repeat(auto-fit,minmax(360px,1fr))", gap: 18 }}>
              {review.reads.map((r) => <ReadCard key={r.id} read={r} />)}
            </div>
          </section>

          <p className="muted" style={{ fontSize: "12.5px", marginTop: 34 }}>
            Weybourne · prepared from the Notes, Funds and Contacts databases, as at{" "}
            {fmtDT(review.generated_at)}.
          </p>
        </>
      )}
    </div>
  );
}
