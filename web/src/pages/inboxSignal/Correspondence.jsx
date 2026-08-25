import React from "react";
import { Card, SectionHead, useScrollHold } from "../../ui.jsx";
import {
  Empty, GUTTER, Pill, Spark, STANCE_LABEL, STANCE_ORDER, StanceChip,
} from "./shared.jsx";

/* Theme pills shown before the list folds into a "more" row. Forty-eight pills
   is a wall; the ones past this point are the long tail and are reachable by
   typing the theme name into the search instead. */
const THEME_PILLS = 12;

/* One extracted passage, with its attribution around it. */
function QuoteCard({ v, themeLabel, onTheme }) {
  return (
    <Card style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      <div className="spread" style={{ alignItems: "baseline", gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <b style={{ fontSize: 14 }}>{v.org}</b>
          {v.person && <span className="muted" style={{ fontSize: 12.5 }}> · {v.person}</span>}
        </div>
        <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
          <StanceChip stance={v.stance} />
          <span className="mono" style={{ fontSize: 10.5, color: "var(--stone-400)",
                                          whiteSpace: "nowrap" }}>
            {v.date}
          </span>
        </div>
      </div>

      <blockquote style={{
        margin: 0, paddingLeft: 13, borderLeft: "2px solid var(--teal-300)",
        font: "400 14px/1.6 var(--serif)", color: "var(--ink-800)",
      }}>
        “{v.quote}”
      </blockquote>

      {v.context && (
        <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.5, margin: 0,
                                      fontStyle: "italic" }}>
          {v.context}
        </p>
      )}

      <div className="row" style={{ gap: 6, marginTop: "auto", paddingTop: 8,
                                    borderTop: "1px solid var(--paper-200)",
                                    flexWrap: "wrap" }}>
        {/* Where these are the letter's themes rather than this passage's,
            say so. A letter covering AI, semiconductors and the Gulf had
            all three printed under a quote about one company's guidance,
            which reads as a claim about the quote. Letters extracted from
            now on carry their own per-quote themes. */}
        {v.themes_are_the_letters && (v.themes || []).length > 0 && (
          <span className="mono" style={{ fontSize: 9.5, letterSpacing: ".08em",
                textTransform: "uppercase", color: "var(--stone-400)" }}
                title="Recorded for the whole letter, not for this passage">
            letter:
          </span>
        )}
        {(v.themes || []).map((t) => (
          <button type="button" key={t} className="chip neutral" onClick={() => onTheme(t)}
                  style={{ border: "none", cursor: "pointer",
                           opacity: v.themes_are_the_letters ? 0.62 : 1 }}
                  title={v.themes_are_the_letters
                    ? `${themeLabel(t)} — a theme of this letter, not necessarily of this passage`
                    : themeLabel(t)}>
            {themeLabel(t)}
          </button>
        ))}
        {v.web_link && (
          <a href={v.web_link} target="_blank" rel="noreferrer"
             className="mono" style={{ fontSize: 10, letterSpacing: ".1em",
                                       textTransform: "uppercase", color: "var(--teal-700)",
                                       marginLeft: "auto", whiteSpace: "nowrap" }}>
            Open in Outlook
          </a>
        )}
      </div>

      {v.source && (
        <div className="mono" style={{ fontSize: 10, letterSpacing: ".08em",
                                       textTransform: "uppercase", color: "var(--stone-400)" }}>
          {v.source}
        </div>
      )}
    </Card>
  );
}

const QUOTE_GRID = { display: "grid", gap: 14,
                     gridTemplateColumns: "repeat(auto-fill,minmax(380px,1fr))" };

/* "Correspondence" — the searchable log of what was actually said.

   Every entry is a verbatim span from a real letter; the extractor drops any
   quote it cannot find in the source body. That is why this tab shows the
   quote as the primary content and everything else as attribution around it —
   the words are the evidence, and the rest is provenance for checking them. */
export default function Correspondence({ data, onRetheme, retheming }) {
  const voices = data.voices || [];
  const themes = data.themes || [];
  const periods = data.mailbox_periods || [];
  const retheme = data.retheme || {};

  const [query, setQuery] = React.useState("");
  const [theme, setTheme] = React.useState("all");
  const [stance, setStance] = React.useState("all");
  const [period, setPeriod] = React.useState("all");
  const [allThemes, setAllThemes] = React.useState(false);
  // Every filter change re-filters the whole log below the sticky bar; the
  // shrink would otherwise clamp the scroll back up (see useScrollHold).
  const hold = useScrollHold();

  const matches = voices.filter((v) => {
    if (theme !== "all" && !(v.themes || []).includes(theme)) return false;
    if (stance !== "all" && v.stance !== stance) return false;
    if (period !== "all" && v.period !== period) return false;
    if (query) {
      const hay = `${v.org} ${v.person} ${v.quote} ${v.context} ${v.source}`.toLowerCase();
      if (!hay.includes(query.trim().toLowerCase())) return false;
    }
    return true;
  });

  /* A theme filter splits its results in two, because the page holds two very
     different kinds of evidence for "this quote is about X".

     Where the extractor tagged the passage itself, the match is a finding.
     Where it did not — every letter read before per-quote themes existed — the
     quote inherits its letter's themes, and the match only means the letter
     mentioned X somewhere. QSP's July risk report is tagged vol, semis, Iran
     and crude; filtering on semiconductors surfaced a passage about single
     stock decorrelation and index volatility, which is about none of them.
     Dropping the inherited ones would empty the drawer for most of the corpus,
     so they are kept and separated rather than mixed in or hidden. */
  const filteringByTheme = theme !== "all";
  const confident = filteringByTheme
    ? matches.filter((v) => !v.themes_are_the_letters) : matches;
  const inherited = filteringByTheme
    ? matches.filter((v) => v.themes_are_the_letters) : [];

  const filtered = theme !== "all" || stance !== "all" || period !== "all" || query;
  const activeTheme = themes.find((t) => t.id === theme) || null;
  const themeLabel = (id) => themes.find((t) => t.id === id)?.label || id;

  /* Counts on the pills are what that pill would leave, given the *other*
     filters — a pill reading 0 is then a dead end you can see before clicking
     rather than an empty result you discover after. */
  const wouldMatch = (over) => voices.filter((v) => {
    const t = over.theme ?? theme, s = over.stance ?? stance, p = over.period ?? period;
    if (t !== "all" && !(v.themes || []).includes(t)) return false;
    if (s !== "all" && v.stance !== s) return false;
    if (p !== "all" && v.period !== p) return false;
    if (query) {
      const hay = `${v.org} ${v.person} ${v.quote} ${v.context} ${v.source}`.toLowerCase();
      if (!hay.includes(query.trim().toLowerCase())) return false;
    }
    return true;
  }).length;

  const shownThemes = allThemes ? themes : themes.slice(0, THEME_PILLS);

  return (
    <div className="fade-in">
      <div style={{
        position: "sticky", top: 0, zIndex: 20,
        margin: `0 calc(-1 * ${GUTTER})`,
        padding: `14px ${GUTTER} 16px`,
        background: "var(--paper-050)",
        borderBottom: "1px solid var(--paper-300)",
        display: "flex", flexDirection: "column", gap: 12,
      }}>
        <div className="row" style={{ gap: 10 }}>
          <input
            value={query}
            onChange={(e) => { const v = e.target.value; hold(() => setQuery(v)); }}
            placeholder="Search the text — manager, phrase, source…"
            aria-label="Search correspondence"
            style={{ flex: "1 1 280px", minWidth: 180, fontSize: 13.5, padding: "8px 11px" }} />
          <span className="microlabel" style={{ whiteSpace: "nowrap" }}>
            {matches.length} OF {voices.length}
          </span>
          {filtered && (
            <button type="button"
              className="mono is-pill"
              onClick={() => hold(() => {
                setQuery(""); setTheme("all"); setStance("all"); setPeriod("all");
              })}>
              Clear
            </button>
          )}
        </div>

        {themes.length > 0 && (
          <div className="row" style={{ gap: 5 }}>
            <Pill on={theme === "all"} onClick={() => hold(() => setTheme("all"))}>All themes</Pill>
            {shownThemes.map((t) => (
              <Pill key={t.id} on={theme === t.id} onClick={() => hold(() => setTheme(t.id))}
                    count={wouldMatch({ theme: t.id })}>
                {t.label}
              </Pill>
            ))}
            {themes.length > THEME_PILLS && (
              <button type="button" className="mono is-pill"
                      onClick={() => hold(() => setAllThemes(!allThemes))}>
                {allThemes ? "Fewer" : `+${themes.length - THEME_PILLS} more`}
              </button>
            )}
          </div>
        )}

        <div className="row" style={{ gap: 18 }}>
          <div className="row" style={{ gap: 5 }}>
            <Pill on={stance === "all"} onClick={() => hold(() => setStance("all"))}>Any stance</Pill>
            {STANCE_ORDER.map((s) => (
              <Pill key={s} on={stance === s} onClick={() => hold(() => setStance(s))}
                    count={wouldMatch({ stance: s })}>
                {STANCE_LABEL[s]}
              </Pill>
            ))}
          </div>
          <div className="row" style={{ gap: 5 }}>
            <Pill on={period === "all"} onClick={() => hold(() => setPeriod("all"))}>All windows</Pill>
            {periods.map((p) => (
              <Pill key={p.key} on={period === p.key} onClick={() => hold(() => setPeriod(p.key))}
                    count={wouldMatch({ period: p.key })}>
                {p.short}
              </Pill>
            ))}
          </div>
        </div>
      </div>

      {activeTheme && (
        <Card style={{ margin: "18px 0 0", display: "flex", alignItems: "center",
                       gap: 16, flexWrap: "wrap" }}>
          <div style={{ minWidth: 0 }}>
            <span className="microlabel">WHEN {activeTheme.label.toUpperCase()} WAS RAISED</span>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 3 }}>
              {activeTheme.series.map((n, i) => `${periods[i]?.short || i}: ${n}`).join(" · ")}
            </div>
          </div>
          <div style={{ marginLeft: "auto" }}><Spark series={activeTheme.series} width={140} height={28} /></div>
        </Card>
      )}

      {/* The coverage line for theme attribution, alongside the control that
          closes the gap. A drawer whose tags are mostly inherited is a
          different instrument from one whose tags are findings, and the desk
          should be able to see which it is holding — and fix it. */}
      {retheme.inheriting > 0 && (
        <Card style={{ margin: "18px 0 0", display: "flex", alignItems: "center",
                       gap: 18, flexWrap: "wrap" }}>
          <div style={{ minWidth: 0, flex: "1 1 420px" }}>
            <span className="microlabel">THEMES RECORDED PASSAGE BY PASSAGE</span>
            <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55, margin: "5px 0 0" }}>
              {retheme.attributed} of {retheme.quotes} quotes carry themes of their own.
              The other {retheme.inheriting} show their letter's themes, across{" "}
              {retheme.letters_pending} letter{retheme.letters_pending === 1 ? "" : "s"} —
              so a letter that discussed semiconductors somewhere tags every passage in it
              with semiconductors. Re-reading attributes each passage on its own; the letter
              bodies are not read again, only the quotes already held. About nine seconds a
              letter, and it can be stopped and resumed — nothing already attributed is
              read twice.
            </p>
          </div>
          <button type="button" className="mono is-pill" onClick={() => hold(onRetheme)}
                  disabled={retheming}
                  style={{ whiteSpace: "nowrap", cursor: retheming ? "default" : "pointer" }}>
            {retheming
              ? "Re-reading…"
              : `Re-read ${retheme.letters_pending} letter${retheme.letters_pending === 1 ? "" : "s"}`}
          </button>
        </Card>
      )}

      <SectionHead label="CORRESPONDENCE LOG" style={{ paddingTop: 22 }} />

      {voices.length === 0 && (
        <Empty>
          Nothing extracted yet. Put a shared-inbox snapshot in place
          (scripts/refresh_shared_inbox_snapshot.py explains how) and run a sweep — every
          quote that appears here will be a verbatim span from a real letter.
        </Empty>
      )}

      {voices.length > 0 && matches.length === 0 && (
        <Empty>No quote matches those filters. Clear one to widen the search.</Empty>
      )}

      {/* Not an empty result: everything that matched is downstairs under its
          own heading, and an unexplained blank here would read as a failure. */}
      {matches.length > 0 && confident.length === 0 && (
        <Empty>
          No passage is itself tagged {activeTheme?.label || theme}. Every letter that raised
          it is below, from before themes were recorded passage by passage.
        </Empty>
      )}

      <div style={QUOTE_GRID}>
        {confident.map((v, i) => (
          <QuoteCard key={i} v={v} themeLabel={themeLabel}
                     onTheme={(t) => hold(() => setTheme(t))} />
        ))}
      </div>

      {inherited.length > 0 && (
        <>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap",
                        borderTop: "1px solid var(--paper-300)",
                        margin: "26px 0 4px", paddingTop: 14 }}>
            <span className="microlabel">
              FROM LETTERS THAT RAISED {(activeTheme?.label || theme).toUpperCase()}
            </span>
            <span className="mono" style={{ fontSize: 11, color: "var(--stone-400)" }}>
              {inherited.length}
            </span>
          </div>
          <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55,
                                        margin: "0 0 14px", maxWidth: 780 }}>
            These were read before themes were recorded passage by passage, so what is known is
            that the <i>letter</i> raised {activeTheme?.label || theme} — not that this passage
            did. They are kept because they are the only route into most of the archive, and
            separated because the ones above are findings and these are leads.
          </p>
          <div style={QUOTE_GRID}>
            {inherited.map((v, i) => (
              <QuoteCard key={i} v={v} themeLabel={themeLabel}
                         onTheme={(t) => hold(() => setTheme(t))} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
